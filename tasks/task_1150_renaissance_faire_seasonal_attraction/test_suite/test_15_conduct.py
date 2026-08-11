"""Conduct enforcement: linkage gates, double-resolve guard, and the BAN_GUEST
ticket-voiding cascade."""
from test_helpers import (
    ApiErrorId,
    get_order,
    get_season,
    make_conduct_case,
    make_season,
    set_clock,
    setup_paid_day_order,
    tickets_of_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR


def test_conduct_resolve_linkage_and_double_resolve_guards(api, operator_headers):
    """PRD §3.9: "An `UPHELD` outcome sets the case's `sanction` from the payload
    and enforces linkage: `BAN_GUEST` requires the case's `linked_order_id` to be
    present and `REVOKE_PERMIT` requires its `linked_permit_id`, with a missing link
    rejected as `ERR_CASE_LINKAGE_INVALID`, while `NONE` carries no further effect."
    PRD §3.9: "The case must still be `REPORTED` — resolving an already-resolved
    case fails with `ERR_CASE_ALREADY_RESOLVED`."

    Design: Corner/errors/conduct_resolve_linkage_and_double_resolve_guards
    """
    season = make_season(name="Conduct Revel")
    case_a = make_conduct_case(
        season["id"], category="COSTUME_POLICY",
        subject_description="Modern sneakers in the lanes",
    )
    case_b = make_conduct_case(
        season["id"], category="BEHAVIOR",
        subject_description="Heckling the juggler",
    )
    validate_success(
        api.resolve_conduct_case(
            case_b["id"], {"outcome": "DISMISSED", "sanction": "NONE"}, OPERATOR
        ),
        200,
    )

    # BAN_GUEST without a linked order is rejected.
    res = api.resolve_conduct_case(
        case_a["id"], {"outcome": "UPHELD", "sanction": "BAN_GUEST"}, OPERATOR
    )
    validate_error(res, ApiErrorId.ERR_CASE_LINKAGE_INVALID, expected_status=409)

    # Retried with sanction NONE the same case resolves cleanly.
    resolved = validate_success(
        api.resolve_conduct_case(
            case_a["id"], {"outcome": "UPHELD", "sanction": "NONE"}, OPERATOR
        ),
        200,
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["sanction"] == "NONE"

    # The DISMISSED case is terminal.
    res = api.resolve_conduct_case(
        case_b["id"], {"outcome": "UPHELD", "sanction": "NONE"}, OPERATOR
    )
    validate_error(res, ApiErrorId.ERR_CASE_ALREADY_RESOLVED, expected_status=409)


def test_ban_guest_voids_tickets_cascade(api, operator_headers, any_headers):
    """PRD §3.9: "An upheld `BAN_GUEST` voids every `VALID` ticket of the linked
    order, moves the order's `redemption_status` to `VOID` — from `UNREDEEMED` when
    every ticket is voided together, or from `PARTIALLY_REDEEMED` when the ban voids
    only the remaining `VALID` tickets and the order carries a mix of `REDEEMED` and
    `VOID` — and decrements the season's `outstanding_admissions` by one per voided
    ticket."

    Design: Corner/state_machines/ban_guest_voids_tickets_cascade
    """
    set_clock()
    season, day, order = setup_paid_day_order(quantity=2, buyer_email="g-ban@example.com")
    assert get_season(season["id"])["outstanding_admissions"] == 2

    case = make_conduct_case(
        season["id"], category="WEAPON_UNTIED",
        subject_description="Steel blade not peace-tied at the gate",
        linked_order_id=order["id"],
    )
    resolved = validate_success(
        api.resolve_conduct_case(
            case["id"], {"outcome": "UPHELD", "sanction": "BAN_GUEST"}, OPERATOR
        ),
        200,
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["sanction"] == "BAN_GUEST"

    for ticket in tickets_of_order(order["id"]):
        assert ticket["status"] == "VOID"

    order_after = get_order(order["id"])
    assert order_after["redemption_status"] == "VOID"
    assert get_season(season["id"])["outstanding_admissions"] == 0
