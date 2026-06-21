"""Check-ins, punctuality boundary, the compliance-rate calculation, and the
half-open check-in window overlap rule.

Difficulty queue: combinatorial_formula (compliance rate rounding order),
boundary_precision_check (punctuality inclusive boundary, empty-set vacuous 100),
resource_temporal_overlap (check-in half-open windows).
Corner queue: state_machines (mark-missed precondition, double-excuse lockdown),
endpoints (court report snapshot), cross-reference (drug-test reverse-reachable).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_officer_headers,
    setup_active_supervisee, set_clock, add_check_in, attend_check_in,
    create_check_in_payload,
)


# ─── Difficulty: combinatorial_formula / compliance_rate_ratio_times_100 ───
def test_compliance_rate_two_of_three_is_66_7(api):
    """PRD §3.10: "Otherwise the system computes the exact ratio of numerator to
    denominator, multiplies that ratio by 100, and only then rounds the product
    half-up to one decimal place."
    PRD §3.10: "the numerator be the count of check-ins that are ATTENDED with
    punctuality of ON_TIME"

    2 ON_TIME of 3 terminal check-ins -> (2/3)*100 = 66.666... -> 66.7.

    Design: Difficulty/combinatorial_formula/compliance_rate_ratio_times_100_then_round
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-02-01T09:00:00.000Z", officer["id"])

    ci1 = add_check_in(sup["id"], officer["id"], "2026-02-01T09:00:00.000Z", 60)
    attend_check_in(sup["id"], ci1["id"], officer["id"], "2026-02-01T09:30:00.000Z")
    ci2 = add_check_in(sup["id"], officer["id"], "2026-02-02T09:00:00.000Z", 60)
    attend_check_in(sup["id"], ci2["id"], officer["id"], "2026-02-02T09:15:00.000Z")
    ci3 = add_check_in(sup["id"], officer["id"], "2026-02-03T09:00:00.000Z", 60)
    set_clock("2026-02-03T11:00:00.000Z", officer["id"])
    validate_success(api.mark_missed_check_in(sup["id"], ci3["id"], oh), 200)

    comp = validate_success(api.get_compliance(sup["id"], oh), 200)
    assert comp["compliance_rate"] == 66.7

    ci1_after = validate_success(api.get_check_in(sup["id"], ci1["id"], oh), 200)
    assert ci1_after["punctuality"] == "ON_TIME"


def test_compliance_rate_all_on_time_is_100(api):
    """PRD §3.10: "the numerator be the count of check-ins that are ATTENDED with
    punctuality of ON_TIME ... computes the exact ratio of numerator to
    denominator, multiplies that ratio by 100"

    2 ON_TIME of 2 terminal check-ins -> (2/2)*100 = 100.0.

    Design: Difficulty/combinatorial_formula/compliance_rate_ratio_times_100_then_round
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-02-01T09:00:00.000Z", officer["id"])
    ci1 = add_check_in(sup["id"], officer["id"], "2026-02-01T09:00:00.000Z", 60)
    attend_check_in(sup["id"], ci1["id"], officer["id"], "2026-02-01T09:30:00.000Z")
    ci2 = add_check_in(sup["id"], officer["id"], "2026-02-02T09:00:00.000Z", 60)
    attend_check_in(sup["id"], ci2["id"], officer["id"], "2026-02-02T09:15:00.000Z")
    comp = validate_success(api.get_compliance(sup["id"], oh), 200)
    assert comp["compliance_rate"] == 100.0


# ─── Difficulty: boundary_precision_check / punctuality inclusive close ───
def test_attend_exactly_at_window_close_is_on_time(api):
    """PRD §3.4: "if attended_at is at or before the window close, punctuality is
    ON_TIME, and otherwise it is LATE. The boundary is inclusive — arriving
    exactly at the window-close instant counts as ON_TIME."

    Check-in 09:00 window 60 (close 10:00): attending at exactly 10:00:00 is
    ON_TIME.

    Design: Difficulty/boundary_precision_check/checkin_punctuality_inclusive_window_close_is_on_time
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-02-10T08:30:00.000Z", officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-02-10T09:00:00.000Z", 60)
    attended = validate_success(
        api.attend_check_in(sup["id"], ci["id"],
                            {"attended_at": "2026-02-10T10:00:00.000Z"}, oh),
        200,
    )
    assert attended["status"] == "ATTENDED"
    assert attended["punctuality"] == "ON_TIME"


def test_attend_one_second_after_window_close_is_late(api):
    """PRD §3.4: "if attended_at is at or before the window close, punctuality is
    ON_TIME, and otherwise it is LATE."

    One second past the 10:00:00 close is LATE — the X+1 side of the inclusive
    boundary.

    Design: Difficulty/boundary_precision_check/checkin_punctuality_inclusive_window_close_is_on_time
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-02-10T08:30:00.000Z", officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-02-10T09:00:00.000Z", 60)
    attended = validate_success(
        api.attend_check_in(sup["id"], ci["id"],
                            {"attended_at": "2026-02-10T10:00:01.000Z"}, oh),
        200,
    )
    assert attended["punctuality"] == "LATE"


# ─── Difficulty: boundary_precision_check / compliance empty terminal set ───
def test_compliance_rate_empty_terminal_set_is_100(api):
    """PRD §3.10: "When there are no terminal check-ins, the rate is exactly 100.0
    (an empty history is vacuously compliant)."

    With only a SCHEDULED check-in (zero terminal), the rate is 100.0, not 0.0 or
    a division error.

    Design: Difficulty/boundary_precision_check/compliance_rate_empty_terminal_set_is_100
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-02-10T08:00:00.000Z", officer["id"])
    add_check_in(sup["id"], officer["id"], "2026-03-01T09:00:00.000Z", 60)
    comp = validate_success(api.get_compliance(sup["id"], oh), 200)
    assert comp["compliance_rate"] == 100.0


def test_compliance_rate_no_checkins_is_100(api):
    """PRD §3.10: "When there are no terminal check-ins, the rate is exactly 100.0
    (an empty history is vacuously compliant)."

    With no check-ins at all (also an empty terminal set), the rate is 100.0.

    Design: Difficulty/boundary_precision_check/compliance_rate_empty_terminal_set_is_100
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    comp = validate_success(api.get_compliance(sup["id"], oh), 200)
    assert comp["compliance_rate"] == 100.0


# ─── Difficulty: resource_temporal_overlap / checkin half-open windows ───
def test_checkin_overlapping_window_rejected(api):
    """PRD §3.4: "Two such intervals overlap when one begins strictly before the
    other ends and ends strictly after the other begins ... A new check-in whose
    window would overlap an existing window for the same supervisee is rejected
    with ERR_CHECKIN_WINDOW_OVERLAP (HTTP 409)."

    With an existing window [09:00,10:00), a new check-in at 09:30 (inside it) is
    rejected.

    Design: Difficulty/resource_temporal_overlap/checkin_window_overlap_halfopen_adjacency_allowed
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    add_check_in(sup["id"], officer["id"], "2026-02-15T09:00:00.000Z", 60)
    res = api.create_check_in(
        sup["id"],
        create_check_in_payload("2026-02-15T09:30:00.000Z", window_minutes=60),
        oh,
    )
    validate_error(res, "ERR_CHECKIN_WINDOW_OVERLAP")


def test_checkin_adjacent_window_allowed(api):
    """PRD §3.4: "pure adjacency, where one window begins exactly at the instant a
    prior window closes, is permitted."

    A window [09:00,10:00) and a new one starting at exactly 10:00 (adjacency) are
    both accepted.

    Design: Difficulty/resource_temporal_overlap/checkin_window_overlap_halfopen_adjacency_allowed
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    add_check_in(sup["id"], officer["id"], "2026-02-15T09:00:00.000Z", 60)
    res = api.create_check_in(
        sup["id"],
        create_check_in_payload("2026-02-15T10:00:00.000Z", window_minutes=30),
        oh,
    )
    adj = validate_success(res, 201)
    assert adj["status"] == "SCHEDULED"


# ─── Corner: state_machines / mark_missed_before_window_close_rejected ───
def test_mark_missed_before_window_close_rejected(api):
    """PRD §3.4: "An Officer may mark a SCHEDULED check-in as missed, but only after
    the on-time window has fully closed ... Attempting to mark a check-in missed
    before the window has closed is rejected with ERR_WINDOW_NOT_CLOSED (HTTP 409)"

    Design: Corner/state_machines/mark_missed_before_window_close_rejected
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-05-05T08:30:00.000Z", officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-05-05T09:00:00.000Z", 60)
    set_clock("2026-05-05T09:30:00.000Z", officer["id"])  # window not closed
    res = api.mark_missed_check_in(sup["id"], ci["id"], oh)
    validate_error(res, "ERR_WINDOW_NOT_CLOSED")
    after = validate_success(api.get_check_in(sup["id"], ci["id"], oh), 200)
    assert after["status"] == "SCHEDULED"


# ─── Corner: state_machines / double_excuse_checkin_terminal_lockdown ───
def test_double_excuse_check_in_rejected(api):
    """PRD §3.4: "an Officer may excuse a SCHEDULED check-in, moving it to the
    terminal EXCUSED status"
    PRD §3.4: "attempting to attend without the required test (or from a
    non-SCHEDULED status) is rejected with ERR_INVALID_STATE (HTTP 409)"

    EXCUSED is terminal; excusing again must fail with ERR_INVALID_STATE (excuse
    requires SCHEDULED status).

    Design: Corner/state_machines/double_excuse_checkin_terminal_lockdown
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-05-01T09:00:00.000Z", 60)
    validate_success(api.excuse_check_in(sup["id"], ci["id"], oh), 200)
    res = api.excuse_check_in(sup["id"], ci["id"], oh)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: endpoints / court_report_computed_snapshot ───
def test_court_report_freezes_compliance_snapshot(api):
    """PRD §3.10: "On creation the report is minted in DRAFT status with a frozen
    snapshot capturing the restitution_balance_cents, fee_balance_cents,
    cumulative_violation_points, supervision_level, and compliance_rate at filing,
    computed by the same compliance-rate rule above."
    PRD §3.10: "When there are no terminal check-ins, the rate is exactly 100.0"

    Filing a court report with no terminal check-ins freezes compliance_rate 100.0
    and cumulative_violation_points 0.

    Design: Corner/endpoints/court_report_computed_snapshot
    """
    from test_helpers import create_court_report_payload
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    res = api.create_court_report(
        sup["id"],
        create_court_report_payload(report_type="PROGRESS",
                                    as_of_date="2026-01-01T00:00:00.000Z"),
        oh,
    )
    cr = validate_success(res, 201)
    assert cr["snapshot"]["compliance_rate"] == 100.0
    assert cr["snapshot"]["cumulative_violation_points"] == 0


# ─── Corner: endpoints / drugtest_subresource_reverse_reachable ───
def test_drug_test_discoverable_under_check_in(api):
    """PRD §2.5: "the system also exposes flat top-level collections for each child
    entity type that can be filtered by their owning foreign keys (for example ...
    all drug tests for a given check_in_id ...). These reverse-reachability reads
    return the same resource shapes as their nested counterparts."

    A drug test recorded under a check-in is returned by the nested drug-tests
    list of length 1.

    Design: Corner/endpoints/drugtest_subresource_reverse_reachable
    """
    from test_helpers import create_drug_test_payload
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    ci = add_check_in(sup["id"], officer["id"], "2026-06-01T09:00:00.000Z", 60,
                      requires_drug_test=True)
    validate_success(
        api.create_drug_test(sup["id"], ci["id"],
                             create_drug_test_payload(result="NEGATIVE",
                                                      panel="FIVE_PANEL"), oh),
        201,
    )
    items, _ = validate_paginated(api.list_drug_tests(sup["id"], ci["id"], oh))
    assert len(items) == 1
    assert items[0]["result"] == "NEGATIVE"
