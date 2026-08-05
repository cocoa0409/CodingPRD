"""Reporting and listing: referral summary, list pagination, pagination bounds, and
FK reverse-reachability filters.

Covers Corner queue instances under section `endpoints`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_list_referrals_returns_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of every list response reports `limit`, `offset`, `total_count` (the total
    number of matching records ignoring the window), and `has_more` (true when records
    remain beyond the current window)."

    Design: Corner/endpoints/list_referrals_returns_pagination_envelope
    """
    part = fx.new_participant()
    fx.new_referral(part["id"], hours_ordered=8, court_case_number="CR-D18")
    fx.new_referral(part["id"], hours_ordered=40, court_case_number="CR-D19",
                    offense_class="FELONY", indigency="PARTIAL")
    res = api.list_referrals(COORD, params={"participant_id": part["id"],
                                            "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_pagination_invalid_limit_zero_rejected(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` outside 1–100 or a negative `offset` is rejected with `ERR_PAGINATION_INVALID`
    (HTTP 400)."

    Design: Corner/endpoints/pagination_invalid_limit_zero_rejected
    """
    res = api.list_participants(COORD, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID", 400)


def test_filter_placements_by_referral_reverse_reachability(api):
    """PRD §2.3: "The `meta` block of every list response reports `limit`, `offset`, `total_count` (the total
    number of matching records ignoring the window), and `has_more` (true when records
    remain beyond the current window)."
    PRD §3.3: "a `ProgramCoordinator` proposes a placement, tying a referral to a host site under a named
    supervisor. The proposal supplies the `referral_id`, the `site_id`, and the
    `supervisor_id`."

    Design: Corner/endpoints/filter_placements_by_referral_reverse_reachability
    """
    base = fx.accepting_site_with_supervisor()
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-D20")
    plc = fx.new_placement(ref["id"], base["site"]["id"], base["supervisor"]["id"])
    res = api.list_placements(COORD, params={"referral_id": ref["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert data[0]["id"] == plc["id"]


def test_referral_summary_reports_hours_breakdown(api):
    """PRD §3.2: "A dedicated summary view returns a computed breakdown for a single referral: its
    `referral_id`, `hours_ordered`, `hours_completed`, `hours_converted`,
    `hours_outstanding`, `fees_settled_cents`, `status`, and `certificate_id`."

    Design: Corner/endpoints/referral_summary_reports_hours_breakdown
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=12, court_case_number="CR-D21")
    res = api.get_referral_summary(ref["id"], CLERK)
    data = validate_success(res, 200)
    assert data["hours_ordered"] == 12
    assert data["hours_completed"] == 0
    assert data["hours_outstanding"] == 12
    assert data["status"] == "ACTIVE"
