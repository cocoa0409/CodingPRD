"""Composite setup helpers.

Every test runs against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares.  Setup calls
use the lenient `get_success_data` validator so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion later.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_payload,
    create_appraisal_payload,
    create_appraiser_payload,
    create_asset_payload,
    create_category_schedule_payload,
    create_claim_line_payload,
    create_claim_payload,
    create_estate_plan_payload,
    create_household_payload,
    create_item_payload,
    create_member_payload,
    create_package_payload,
    create_policy_payload,
    create_room_payload,
    create_share_grant_payload,
    create_subscription_payload,
    unique_checksum,
    unique_email,
)
from .test_users import (
    make_appraiser_headers,
    make_claims_adjuster_headers,
    make_estate_executor_headers,
    make_homeowner_headers,
    make_household_member_headers,
    make_insurance_agent_headers,
    make_platform_admin_headers,
)

ADMIN = make_platform_admin_headers()
ADJUSTER = make_claims_adjuster_headers()
AGENT = make_insurance_agent_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def add_category_schedule(category: str = "GENERAL", **overrides) -> Dict[str, Any]:
    payload = create_category_schedule_payload(category, **overrides)
    return get_success_data(api_client.create_category_schedule(payload, ADMIN))


def add_general_schedule(**overrides) -> Dict[str, Any]:
    """The workhorse GENERAL schedule: 8%/yr, 20% salvage, 900000 sublimit."""
    return add_category_schedule("GENERAL", **overrides)


def register_member(email: Optional[str] = None, headers: Optional[Dict] = None, **overrides) -> Dict[str, Any]:
    from .test_users import make_anonymous_headers

    payload = create_member_payload(email=email or unique_email(), **overrides)
    return get_success_data(
        api_client.create_member(payload, headers or make_anonymous_headers())
    )


def register_owner(email: Optional[str] = None, full_name: str = "Test Owner") -> Dict[str, Any]:
    """Self-register an unattached member; PRD 3.1 makes them an OWNER."""
    return register_member(email=email, full_name=full_name)


def add_member_to_household(
    owner_headers: Dict[str, str],
    household_id: str,
    member_role: str,
    email: Optional[str] = None,
    full_name: str = "Test Household Member",
) -> Dict[str, Any]:
    payload = create_member_payload(
        email=email or unique_email(),
        full_name=full_name,
        member_role=member_role,
        household_id=household_id,
    )
    return get_success_data(api_client.create_member(payload, owner_headers))


def add_room(ctx: Dict[str, Any], name: str = "Test Room", floor_label: str = "1") -> Dict[str, Any]:
    payload = create_room_payload(ctx["household_id"], name=name, floor_label=floor_label)
    return get_success_data(api_client.create_room(payload, ctx["owner_headers"]))


def add_item(ctx: Dict[str, Any], room_id: str, **overrides) -> Dict[str, Any]:
    payload = create_item_payload(ctx["household_id"], room_id, **overrides)
    return get_success_data(api_client.create_item(payload, ctx["owner_headers"]))


def add_asset(ctx: Dict[str, Any], item_id: str, **overrides) -> Dict[str, Any]:
    payload = create_asset_payload(**overrides)
    return get_success_data(api_client.upload_asset(item_id, payload, ctx["owner_headers"]))


def declare_value(ctx: Dict[str, Any], item_id: str, declared_value_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.declare_value(
            item_id, {"declared_value_cents": declared_value_cents}, ctx["owner_headers"]
        )
    )


def add_policy(ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    payload = create_policy_payload(ctx["household_id"], **overrides)
    return get_success_data(api_client.create_policy(payload, ctx["owner_headers"]))


def add_package(ctx: Dict[str, Any], policy_id: str) -> Dict[str, Any]:
    payload = create_package_payload(ctx["household_id"], policy_id)
    return get_success_data(api_client.create_package(payload, ctx["owner_headers"]))


def read_household_version(ctx: Dict[str, Any]) -> int:
    data = get_success_data(
        api_client.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    return data["version"]


def read_policy_version(ctx: Dict[str, Any], policy_id: str) -> int:
    data = get_success_data(api_client.get_policy(policy_id, ctx["owner_headers"]))
    return data["version"]


def read_subscription_version(ctx: Dict[str, Any]) -> int:
    data = get_success_data(
        api_client.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    return data["version"]


def read_plan_version(plan_id: str, executor_headers: Dict[str, str]) -> int:
    data = get_success_data(api_client.get_estate_plan(plan_id, executor_headers))
    return data["version"]


# ---------------------------------------------------------------------------
# Tier 1 — household bootstrap
# ---------------------------------------------------------------------------


def bootstrap_household(
    tier: str = "PLUS",
    activate: bool = True,
    categories: Optional[List[Dict[str, Any]]] = None,
    clock: Optional[str] = "2026-05-01T00:00:00Z",
    with_subscription: bool = True,
    household_name: str = "Test Household",
    address_label: str = "1 Test Lane",
    owner_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Clock + category schedules + owner + household + subscription.

    Returns a context dict carrying `owner_id`, `owner_headers`,
    `household_id`, `subscription_id` and the created category schedules.
    """
    if clock is not None:
        set_clock(clock)

    schedules = {}
    for spec in categories or []:
        spec = dict(spec)
        category = spec.pop("category", "GENERAL")
        schedules[category] = add_category_schedule(category, **spec)

    owner = register_owner(email=owner_email)
    owner_headers = make_homeowner_headers(owner["id"])
    household = get_success_data(
        api_client.create_household(
            create_household_payload(name=household_name, address_label=address_label),
            owner_headers,
        )
    )

    ctx: Dict[str, Any] = {
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": owner_headers,
        "household": household,
        "household_id": household["id"],
        "subscription_id": None,
        "subscription": None,
        "schedules": schedules,
    }

    if with_subscription:
        subscription = get_success_data(
            api_client.create_subscription(
                create_subscription_payload(household["id"], tier), owner_headers
            )
        )
        ctx["subscription"] = subscription
        ctx["subscription_id"] = subscription["id"]
        if activate:
            ctx["subscription"] = get_success_data(
                api_client.billing_event(
                    subscription["id"], {"outcome": "PAYMENT_SUCCEEDED"}, ADMIN
                )
            )
    return ctx


def billing_event(ctx: Dict[str, Any], outcome: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.billing_event(ctx["subscription_id"], {"outcome": outcome}, ADMIN)
    )


def drive_subscription_to_lapsed(ctx: Dict[str, Any], lapse_clock: str) -> Dict[str, Any]:
    """ACTIVE -> PAST_DUE -> (clock past the 10-day grace) -> LAPSED."""
    billing_event(ctx, "PAYMENT_FAILED")
    set_clock(lapse_clock)
    return billing_event(ctx, "LAPSE")


# ---------------------------------------------------------------------------
# Tier 2 — items carried to CATALOGED
# ---------------------------------------------------------------------------


def add_cataloged_item(
    ctx: Dict[str, Any],
    room_id: str,
    declared_value_cents: int,
    photo_bytes: int = 9000,
    **item_overrides,
) -> Dict[str, Any]:
    """Create an item, give it one PHOTO, declare a value.

    Evidence tier climbs to PHOTO_ONLY (or PHOTO_SERIAL when the item carries a
    `serial_number`) and the declared value completes the draft-to-catalogued
    gate of PRD 3.3.
    """
    item = add_item(ctx, room_id, **item_overrides)
    add_asset(
        ctx,
        item["id"],
        asset_kind="PHOTO",
        byte_size=photo_bytes,
        checksum=unique_checksum("sha-photo"),
    )
    return declare_value(ctx, item["id"], declared_value_cents)


def add_photo_serial_item(
    ctx: Dict[str, Any],
    room_id: str,
    declared_value_cents: int,
    serial_number: str,
    **item_overrides,
) -> Dict[str, Any]:
    """A CATALOGED item at evidence tier PHOTO_SERIAL (serial + photo)."""
    return add_cataloged_item(
        ctx,
        room_id,
        declared_value_cents,
        serial_number=serial_number,
        **item_overrides,
    )


def schedule_item(
    ctx: Dict[str, Any], item_id: str, policy_id: str, scheduled_value_cents: int
) -> Dict[str, Any]:
    """Schedule an item, reading the policy's current version first."""
    payload = {
        "policy_id": policy_id,
        "scheduled_value_cents": scheduled_value_cents,
        "expected_policy_version": read_policy_version(ctx, policy_id),
    }
    return get_success_data(
        api_client.schedule_item(item_id, payload, ctx["owner_headers"])
    )


# ---------------------------------------------------------------------------
# Tier 3 — documentation packages
# ---------------------------------------------------------------------------


def generate_package(ctx: Dict[str, Any], package_id: str) -> Dict[str, Any]:
    """Generate a package, reading the household's current version first."""
    payload = {"expected_household_version": read_household_version(ctx)}
    return get_success_data(
        api_client.generate_package(package_id, payload, ctx["owner_headers"])
    )


def deliver_package(ctx: Dict[str, Any], package_id: str, recipient_ref: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.deliver_package(
            package_id, {"recipient_ref": recipient_ref}, ctx["owner_headers"]
        )
    )


def add_generated_package(ctx: Dict[str, Any], policy_id: str) -> Dict[str, Any]:
    """DRAFT package -> GENERATED in one step."""
    package = add_package(ctx, policy_id)
    return generate_package(ctx, package["id"])


def setup_household_with_generated_package(
    declared_value_cents: int = 150000,
    tier: str = "PLUS",
    activate: bool = True,
    policy_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    categories: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Owner + household + subscription + room + one CATALOGED item + policy +
    GENERATED package.  The most common preamble in this suite."""
    ctx = bootstrap_household(
        tier=tier,
        activate=activate,
        categories=categories if categories is not None else [{"category": "GENERAL"}],
    )
    room = add_room(ctx, name="Room A", floor_label="1")
    item = add_cataloged_item(
        ctx, room["id"], declared_value_cents, **(item_overrides or {})
    )
    policy = add_policy(ctx, **(policy_overrides or {}))
    package = add_generated_package(ctx, policy["id"])
    ctx.update({"room": room, "item": item, "policy": policy, "package": package})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — loss claims
# ---------------------------------------------------------------------------


def open_claim(ctx: Dict[str, Any], package_id: str, policy_id: str, affected_room_ids, **overrides) -> Dict[str, Any]:
    payload = create_claim_payload(
        ctx["household_id"], package_id, policy_id, affected_room_ids, **overrides
    )
    return get_success_data(api_client.create_claim(payload, ctx["owner_headers"]))


def add_claim_line(ctx: Dict[str, Any], claim_id: str, item_id: str, claimed_quantity: int = 1) -> Dict[str, Any]:
    return get_success_data(
        api_client.add_claim_line(
            claim_id, create_claim_line_payload(item_id, claimed_quantity), ctx["owner_headers"]
        )
    )


def submit_claim(ctx: Dict[str, Any], claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_claim(claim_id, {}, ctx["owner_headers"]))


def adjudicate(claim_line_id: str, decision: str, denial_reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.adjudicate_claim_line(claim_line_id, payload, ADJUSTER)
    )


def appeal(ctx: Dict[str, Any], claim_line_id: str, appeal_note: str = "appeal") -> Dict[str, Any]:
    return get_success_data(
        api_client.appeal_claim_line(
            claim_line_id, {"appeal_note": appeal_note}, ctx["owner_headers"]
        )
    )


def setup_submitted_claim(
    ctx: Dict[str, Any],
    package_id: str,
    policy_id: str,
    affected_room_ids,
    item_ids,
    **claim_overrides,
) -> Dict[str, Any]:
    """Open a claim, add one line per item id, submit it. Returns
    {"claim": ..., "lines": [...]}"""
    claim = open_claim(ctx, package_id, policy_id, affected_room_ids, **claim_overrides)
    lines = [add_claim_line(ctx, claim["id"], item_id) for item_id in item_ids]
    claim = submit_claim(ctx, claim["id"])
    return {"claim": claim, "lines": lines}


# ---------------------------------------------------------------------------
# Tier 5 — appraisers, appraisals
# ---------------------------------------------------------------------------


def add_appraiser(**overrides) -> Dict[str, Any]:
    payload = create_appraiser_payload(**overrides)
    return get_success_data(api_client.create_appraiser(payload, ADMIN))


def request_appraisal(ctx: Dict[str, Any], item_id: str, appraiser_id: str, **overrides) -> Dict[str, Any]:
    payload = create_appraisal_payload(item_id, appraiser_id, **overrides)
    return get_success_data(api_client.create_appraisal(payload, ctx["owner_headers"]))


def certify_appraisal(appraisal_id: str, appraiser_id: str, appraised_value_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_appraisal(
            appraisal_id,
            {"appraised_value_cents": appraised_value_cents},
            make_appraiser_headers(appraiser_id),
        )
    )


def void_appraisal(appraisal_id: str, void_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.void_appraisal(appraisal_id, {"void_reason": void_reason}, ADMIN)
    )


def suspend_appraiser(appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.suspend_appraiser(appraiser_id, {}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 6 — estate plans
# ---------------------------------------------------------------------------


def add_estate_plan(ctx: Dict[str, Any], executor_member_id: str, **overrides) -> Dict[str, Any]:
    payload = create_estate_plan_payload(
        ctx["household_id"], executor_member_id, **overrides
    )
    return get_success_data(api_client.create_estate_plan(payload, ctx["owner_headers"]))


def allocate(
    plan_id: str,
    executor_headers: Dict[str, str],
    item_id: str,
    disposition: str,
    quantity: int,
    heir_member_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one allocation, reading the plan's current version first."""
    payload = create_allocation_payload(
        item_id, disposition, quantity, read_plan_version(plan_id, executor_headers)
    )
    if heir_member_id is not None:
        payload["heir_member_id"] = heir_member_id
    return get_success_data(
        api_client.create_allocation(plan_id, payload, executor_headers)
    )


def propose_plan(plan_id: str, executor_headers: Dict[str, str], valuation_mode: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if valuation_mode is not None:
        payload["valuation_mode"] = valuation_mode
    return get_success_data(api_client.propose_plan(plan_id, payload, executor_headers))


def setup_estate_plan_household(
    tier: str = "PLUS",
    activate: bool = True,
    heir_count: int = 1,
) -> Dict[str, Any]:
    """Household with an EXECUTOR member, `heir_count` HEIR members, a room and
    a DRAFT estate plan.  Returns the context extended with `executor`,
    `executor_headers`, `heirs`, `room` and `plan`."""
    ctx = bootstrap_household(
        tier=tier, activate=activate, categories=[{"category": "GENERAL"}]
    )
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Test Executor"
    )
    heirs = [
        add_member_to_household(
            ctx["owner_headers"],
            ctx["household_id"],
            "HEIR",
            full_name=f"Test Heir {index + 1}",
        )
        for index in range(heir_count)
    ]
    room = add_room(ctx, name="Estate Room", floor_label="1")
    ctx.update(
        {
            "executor": executor,
            "executor_headers": make_estate_executor_headers(executor["id"]),
            "heirs": heirs,
            "room": room,
        }
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 7 — share grants
# ---------------------------------------------------------------------------


def add_share_grant(ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    payload = create_share_grant_payload(ctx["household_id"], **overrides)
    return get_success_data(
        api_client.create_share_grant(payload, ctx["owner_headers"])
    )


def make_limited_member(ctx: Dict[str, Any], email: Optional[str] = None) -> Dict[str, Any]:
    """A LIMITED household member plus its HouseholdMember headers."""
    member = add_member_to_household(
        ctx["owner_headers"],
        ctx["household_id"],
        "LIMITED",
        email=email,
        full_name="Limited Member",
    )
    return {"member": member, "headers": make_household_member_headers(member["id"])}
