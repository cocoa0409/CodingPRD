"""Retiring a RevenueCode closes both doors into ACTIVE for the items mapped to it."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId,
    setup_northgate_item_scenario,
    create_item, reprice_item, item_lifecycle, read_item, read_facility,
    ADMIN, ANALYST, APPROVER,
)


def _setup():
    """CDM-40001 ACTIVE then DEACTIVATEd, CDM-40002 stopped at APPROVED, code 0300 retired."""
    s = setup_northgate_item_scenario()
    item1 = reprice_item(s["item"]["id"])
    item_lifecycle(item1["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    item_lifecycle(item1["id"], "APPROVE", APPROVER)
    item_lifecycle(item1["id"], "ACTIVATE", APPROVER)

    item2 = create_item(
        s, cdm_number="CDM-40002", description="Basic metabolic panel",
        code_type="CDM_INTERNAL",
        cost_basis_cents=60000, medicare_rate_cents=18000, market_p75_cents=200000,
        effective_from="2026-09-01T00:00:00Z",
    )
    reprice_item(item2["id"])
    item_lifecycle(item2["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    s["item2"] = item_lifecycle(item2["id"], "APPROVE", APPROVER)

    s["item"] = item_lifecycle(item1["id"], "DEACTIVATE", ANALYST,
                               note="temporarily withdrawn pending code retirement")
    s["revenue_code"] = get_success_data(
        api_client.retire_revenue_code(s["revenue_code"]["id"], ADMIN)
    )
    return s


def test_a_retired_revenue_code_blocks_the_first_activation_of_an_approved_item():
    """PRD §3.1: "Retiring a revenue code is a one-way flip of `status` from `ACTIVE` to
    `RETIRED`; items already `ACTIVE` under it keep billing, but no item mapped to a retired
    code may thereafter be activated or reactivated, which surfaces as
    `ERR_REVENUE_CODE_RETIRED`."
    PRD §3.3: "The mapped revenue code's `status` must still be `ACTIVE` — a cross-entity
    dependency on reference data that may have been retired since the item was drafted —
    otherwise `ERR_REVENUE_CODE_RETIRED` (409)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__item_activate_and_reactivate_gated_by_revenue_code_status
    """
    s = _setup()
    assert s["revenue_code"]["status"] == "RETIRED"
    assert s["item2"]["version"] == 4, (
        f"create, reprice, submit, approve is four writes: got {s['item2']['version']}"
    )
    assert s["item2"]["lifecycle_status"] == "APPROVED"
    assert s["item2"]["price_status"] == "PRICED_CURRENT"

    validate_error(
        api_client.charge_item_lifecycle(
            s["item2"]["id"], {"action": "ACTIVATE"}, APPROVER
        ),
        ApiErrorId.ERR_REVENUE_CODE_RETIRED.value,
        409,
    )

    blocked = read_item(s["item2"]["id"])
    assert blocked["lifecycle_status"] == "APPROVED", (
        "nothing about the item's own two dimensions changed; only the referenced "
        "reference-data row moved"
    )
    assert blocked["price_status"] == "PRICED_CURRENT"
    assert blocked["version"] == 4, "a refused action advances no version"


def test_a_retired_revenue_code_also_blocks_the_reactivation_of_an_inactive_item():
    """PRD §3.3: "`INACTIVE → ACTIVE`, the reactivation that closes the cleanup loop `ACTIVE →
    INACTIVE → ACTIVE`, is a `PricingCommitteeApprover` action with three preconditions beyond
    posture. The item's `duplicate_of_item_id` must be null — an item retired as a duplicate can
    never come back, and attempting it is `ERR_ITEM_RETIRED_AS_DUPLICATE` (409). The mapped
    revenue code's `status` must be `ACTIVE`, otherwise `ERR_REVENUE_CODE_RETIRED`."
    PRD §2.11: "`active_item_count` (the number of its charge items whose `lifecycle_status` is
    `ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__item_activate_and_reactivate_gated_by_revenue_code_status
    """
    s = _setup()
    assert s["item"]["lifecycle_status"] == "INACTIVE"
    assert s["item"]["price_status"] == "PRICED_CURRENT", (
        "deactivation touches only the lifecycle dimension"
    )
    assert s["item"]["duplicate_of_item_id"] is None
    assert s["item"]["version"] == 6, (
        f"create, reprice, submit, approve, activate, deactivate: got {s['item']['version']}"
    )

    validate_error(
        api_client.charge_item_lifecycle(
            s["item"]["id"], {"action": "REACTIVATE"}, APPROVER
        ),
        ApiErrorId.ERR_REVENUE_CODE_RETIRED.value,
        409,
    )

    still_inactive = read_item(s["item"]["id"])
    assert still_inactive["lifecycle_status"] == "INACTIVE"
    assert still_inactive["price_status"] == "PRICED_CURRENT"
    assert still_inactive["version"] == 6

    facility = read_facility(s["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert facility["aggregate_cost_basis_cents"] == 0
    assert facility["aggregate_markup_ratio_bp"] == 0
    assert facility["chargemaster_posture"] == "OPEN", (
        "no transparency file and no code-update cycle exist, and nothing is stale"
    )
