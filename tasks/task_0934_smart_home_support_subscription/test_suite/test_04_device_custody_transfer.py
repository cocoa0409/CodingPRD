"""Device custody: offering a transfer, accepting it, and the entitlement conservation."""

from typing import Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_is_null,
    claim,
    claim_and_activate,
    fetch_device,
    fetch_household,
    make_owner_headers,
    new_catalog,
    new_household,
    new_member,
    new_plan,
    new_subscription,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _two_household_world(target_plan_kind: str, target_prefill: bool) -> Dict[str, object]:
    """Household A (PRO, one ACTIVE HUB offered to B) and household B on a chosen plan."""
    set_clock("2026-05-01T00:00:00Z")
    pro_plan = new_plan("PRO")
    target_plan = pro_plan if target_plan_kind == "PRO" else new_plan(target_plan_kind)
    hub = new_catalog("HUB")
    sensor = new_catalog("SENSOR")

    household_a = new_household(
        name="Transfer A", region_code="NWA", billing_email="ta@example.com"
    )
    owner_a = new_member(
        household_a["id"], "OWNER", full_name="Tra A", email="tra@example.com"
    )
    headers_a = make_owner_headers(owner_a["id"])
    new_subscription(household_a["id"], pro_plan["id"], allow_overage=False)

    household_b = new_household(
        name="Transfer B", region_code="NWA", billing_email="tb@example.com"
    )
    owner_b = new_member(
        household_b["id"], "OWNER", full_name="Trb B", email="trb@example.com"
    )
    headers_b = make_owner_headers(owner_b["id"])
    new_subscription(household_b["id"], target_plan["id"], allow_overage=False)

    if target_prefill:
        claim(household_b["id"], sensor["id"], "SNB000001", headers_b)

    device = claim_and_activate(household_a["id"], hub["id"], "HBX000001", headers_a)
    validate_success(
        api_client.transfer_device(
            device["id"], {"target_household_id": household_b["id"]}, headers_a
        ),
        200,
    )
    return {
        "household_a": household_a,
        "household_b": household_b,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "device": device,
    }


# ==========================================================================
# Difficulty: acceptance is gated by the RECEIVING household's entitlement
# ==========================================================================
def test_accept_transfer_is_refused_when_the_target_household_is_at_its_cap(api):
    """PRD 3.4: "It also runs the receiving household's entitlement check: if moving
    the unit in would push the target household's `entitled_device_count` above the
    target plan's `included_device_count` while the target subscription's
    `allow_overage` is false, the acceptance is refused with
    `ERR_DEVICE_CAP_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/accept_transfer_depends_on_target_subscription_entitlement
    """
    world = _two_household_world("BASIC", target_prefill=True)

    response = api.accept_transfer(world["device"]["id"], {}, world["headers_b"])
    validate_error(response, ApiErrorId.ERR_DEVICE_CAP_EXCEEDED.value, 409)


def test_refused_acceptance_leaves_the_device_pending_in_the_source_household(api):
    """PRD 3.4: "On success `transfer_target_household_id` is set to the target and
    `lifecycle_status` moves from `ACTIVE` to `TRANSFER_PENDING`."
    PRD 3.4: "The unit stays in the source household's `entitled_device_count` while
    it is pending, which is why `TRANSFER_PENDING` is one of the entitled states."

    Design: Difficulty/cross_entity_state_dependency/accept_transfer_depends_on_target_subscription_entitlement
    """
    world = _two_household_world("BASIC", target_prefill=True)

    api.accept_transfer(world["device"]["id"], {}, world["headers_b"])

    device = fetch_device(world["device"]["id"])
    assert device["lifecycle_status"] == "TRANSFER_PENDING"
    assert device["household_id"] == world["household_a"]["id"]
    assert fetch_household(world["household_a"]["id"])["entitled_device_count"] == 1
    assert fetch_household(world["household_b"]["id"])["entitled_device_count"] == 1


# ==========================================================================
# Difficulty: the transfer pair conserves the global entitled-device total
# ==========================================================================
def test_accepting_a_transfer_moves_the_device_row_to_the_target_household(api):
    """PRD 3.4: "On success `household_id` becomes the target household,
    `transfer_target_household_id` is cleared to null, `lifecycle_status` returns to
    `ACTIVE`, `entitled_device_count` and `active_device_count` are recomputed on
    **both** the source and the target households, and `is_overage` is recomputed
    against the target plan."

    Design: Difficulty/compensating_invariant/entitled_device_total_conserved_across_transfer_and_accept
    """
    world = _two_household_world("PRO", target_prefill=False)

    accepted = validate_success(
        api.accept_transfer(world["device"]["id"], {}, world["headers_b"]), 200
    )

    assert accepted["household_id"] == world["household_b"]["id"]
    assert accepted["lifecycle_status"] == "ACTIVE"
    assert_is_null(accepted, "transfer_target_household_id", "Device")
    assert accepted["is_overage"] is False


def test_transfer_pair_conserves_the_global_entitled_device_total(api):
    """PRD 2.10: "Summing `entitled_device_count` over all households equals the number
    of `Device` rows whose `lifecycle_status` is `CLAIMED`, `ACTIVE`, `SERVICE_HOLD`,
    `SUSPENDED_RMA` or `TRANSFER_PENDING`. Offering a device and then accepting the
    transfer moves one unit from the source household's count to the target's; the
    global total is unchanged."
    PRD 3.1: "`active_device_count` is the narrower count of devices whose
    `lifecycle_status` is `ACTIVE`, `SERVICE_HOLD` or `SUSPENDED_RMA`."

    Design: Difficulty/compensating_invariant/entitled_device_total_conserved_across_transfer_and_accept
    """
    world = _two_household_world("PRO", target_prefill=False)

    # While the offer is pending the single unit is still counted against A.
    assert fetch_household(world["household_a"]["id"])["entitled_device_count"] == 1
    assert fetch_household(world["household_b"]["id"])["entitled_device_count"] == 0

    validate_success(api.accept_transfer(world["device"]["id"], {}, world["headers_b"]), 200)

    source = fetch_household(world["household_a"]["id"])
    target = fetch_household(world["household_b"]["id"])
    assert source["entitled_device_count"] == 0
    assert source["active_device_count"] == 0
    assert target["entitled_device_count"] == 1
    assert target["active_device_count"] == 1
    assert source["entitled_device_count"] + target["entitled_device_count"] == 1
