"""Corner sections: consistency_model (immediate) and errors (logical clock)."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
)

ADMIN = TEST_USERS["admin_headers"]


def test_citation_issue_immediately_reflected_in_vehicle_balance(api):
    """PRD §2.8: "are all derived fields — never supplied by a client — and are
    recomputed immediately whenever anything that could affect them changes: a
    citation is issued, voided, contested, upheld, or dismissed; a payment is settled
    or refunded; or a supervisor applies a waiver or reassesses a fine."

    Design: Corner/consistency_model/citation_issue_immediately_reflected_in_vehicle_balance
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    issue_in_context(ctx, issued_via="HANDHELD")
    veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    assert veh["outstanding_balance_cents"] == 5000, \
        f"issue must immediately set outstanding to 5000, got {veh['outstanding_balance_cents']}"
    assert veh["unpaid_citation_count"] == 1, \
        f"issue must immediately set unpaid_citation_count to 1, got {veh['unpaid_citation_count']}"


def test_clock_default_and_set(api):
    """PRD §2.5: "An `Admin` may advance or set it by supplying a `to_iso8601` instant
    to the clock-setting capability, after which "now" is that instant."

    Design: Corner/errors/clock_default_and_set_covered
    """
    validate_success(
        api.set_clock({"to_iso8601": "2026-03-10T00:00:00Z"}, ADMIN), 200)
