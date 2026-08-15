"""Supplier engagement workflow: respond/decision negotiation loop, role and
ownership gates, and clock-driven automatic closure."""
from test_helpers import (
    ApiErrorId, decide_engagement, get_inventory_for_cycle,
    make_collecting_cycle, make_engagement, make_supplier_headers,
    recalc_inventory, respond_payload, respond_to_engagement, set_clock,
    validate_error, validate_success,
)


def test_engagement_revision_negotiation_loop(api, analyst_headers):
    """PRD §3.5: "`REINVITE` returns a `NEEDS_REVISION` engagement to
    `INVITED` and increments `round` by one, so the `INVITED` → `RESPONDED` →
    `NEEDS_REVISION` → `INVITED` negotiation loop can repeat." and "From
    `NEEDS_REVISION`, the same respond action returns the engagement to
    `RESPONDED`, overwriting the previous `supplier_tco2e` and refreshing
    `responded_at`."

    Design: Difficulty/non_linear_state_machine/engagement_revision_negotiation_loop
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(cycle["id"], contact_user_id="supplier-1")
    respond_to_engagement(engagement["id"], 7.5, contact_user_id="supplier-1")
    decide_engagement(engagement["id"], "REQUEST_REVISION")

    reinvited = decide_engagement(engagement["id"], "REINVITE")
    assert reinvited["status"] == "INVITED"
    assert reinvited["round"] == 2, "round increments only on the REINVITE edge"

    responded = respond_to_engagement(engagement["id"], 6.5, contact_user_id="supplier-1")
    assert responded["supplier_tco2e"] == 6.5, (
        "the second respond overwrites the previous supplier_tco2e"
    )
    accepted = decide_engagement(engagement["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["supplier_tco2e"] == 6.5


def test_engagement_negotiation_round_increments_per_reinvite(api, analyst_headers):
    """PRD §3.5: "`REINVITE` returns a `NEEDS_REVISION` engagement to
    `INVITED` and increments `round` by one, so the `INVITED` → `RESPONDED` →
    `NEEDS_REVISION` → `INVITED` negotiation loop can repeat."

    Design: Difficulty/non_linear_state_machine/engagement_revision_negotiation_loop
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(cycle["id"], contact_user_id="supplier-1")
    assert engagement["round"] == 1

    for expected_round in (2, 3):
        respond_to_engagement(
            engagement["id"], 7.0 + expected_round, contact_user_id="supplier-1"
        )
        decide_engagement(engagement["id"], "REQUEST_REVISION")
        reinvited = decide_engagement(engagement["id"], "REINVITE")
        assert reinvited["status"] == "INVITED"
        assert reinvited["round"] == expected_round, (
            f"each REINVITE adds exactly one round; expected {expected_round}"
        )


def test_manager_cannot_respond_to_engagement(api, manager_headers):
    """PRD §3.5: "The supplier answers through the respond action, permitted
    only to the `SupplierContact` role and only when the caller's `X-User-ID`
    equals the engagement's `contact_user_id` — any other caller is refused
    with `ERR_UNAUTHORIZED`."

    Design: Corner/roles/manager_cannot_respond_to_engagement
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(cycle["id"], contact_user_id="supplier-1")
    resp = api.respond_to_engagement(
        engagement["id"], respond_payload(7.5), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_wrong_supplier_contact_cannot_respond(api):
    """PRD §3.5: "The supplier answers through the respond action, permitted
    only to the `SupplierContact` role and only when the caller's `X-User-ID`
    equals the engagement's `contact_user_id` — any other caller is refused
    with `ERR_UNAUTHORIZED`." PRD §2.1: "when `X-User-Role` is
    `SupplierContact` and the supplier responds to an engagement, the
    caller's `X-User-ID` must equal that engagement's `contact_user_id`, or
    the call fails with `ERR_UNAUTHORIZED`."

    Design: Corner/roles/wrong_supplier_contact_cannot_respond
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(cycle["id"], contact_user_id="supplier-1")

    wrong = api.respond_to_engagement(
        engagement["id"], respond_payload(7.5), make_supplier_headers("supplier-2")
    )
    validate_error(wrong, ApiErrorId.ERR_UNAUTHORIZED, 403)

    right = validate_success(
        api.respond_to_engagement(
            engagement["id"], respond_payload(7.5), make_supplier_headers("supplier-1")
        )
    )
    assert right["status"] == "RESPONDED"


def test_engagement_respond_after_close_returns_invalid_state(api):
    """PRD §3.5: "A response carries the supplier's emissions figure
    `supplier_tco2e`, expressed to two decimal places, and moves the
    engagement from `INVITED` to `RESPONDED`" and "From `NEEDS_REVISION`, the
    same respond action returns the engagement to `RESPONDED`"; PRD §2.10:
    "State gates — the target entity's own state permits the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/errors/engagement_respond_after_close_returns_invalid_state
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(
        cycle["id"], supplier_name="Late Co", category="CAPITAL_GOODS",
        spend_usd=5000, contact_user_id="supplier-9",
        due_date="2026-06-01T00:00:00Z",
    )
    clock = set_clock("2026-09-01T00:00:00Z")
    assert clock["engagements_closed"] == 1
    closed = validate_success(
        api.get_supplier_engagement(engagement["id"], make_supplier_headers("supplier-9"))
    )
    assert closed["status"] == "CLOSED_NO_DATA"

    resp = api.respond_to_engagement(
        engagement["id"], respond_payload(3.0), make_supplier_headers("supplier-9")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_clock_past_due_date_closes_engagement_and_stales_inventory(api, manager_headers):
    """PRD §2.5: "Advancing the clock evaluates every due-based transition in
    the domain: engagements still in `INVITED` or `NEEDS_REVISION` whose
    `due_date` is now strictly in the past close automatically (§3.5)". PRD
    §3.5: "the engagement automatically moves to the terminal
    `CLOSED_NO_DATA` state, the inventory is marked `STALE`, and both the
    engagement's and the cycle's versions advance."

    Design: Corner/cross_cutting_layers/clock_advances_past_due_date_closes_engagement
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(
        cycle["id"], supplier_name="Late Co", category="UPSTREAM_TRANSPORT",
        spend_usd=5000, contact_user_id="supplier-1",
        due_date="2026-06-01T00:00:00Z",
    )
    assert recalc_inventory(cycle["id"])["status"] == "CURRENT"

    clock = set_clock("2026-09-01T00:00:00Z")
    assert clock["engagements_closed"] == 1, (
        "due_date 2026-06-01 is strictly before 2026-09-01"
    )
    closed = validate_success(
        api.get_supplier_engagement(engagement["id"], manager_headers)
    )
    assert closed["status"] == "CLOSED_NO_DATA"
    assert get_inventory_for_cycle(cycle["id"])["status"] == "STALE", (
        "the automatic closure marks the cycle's inventory STALE"
    )
