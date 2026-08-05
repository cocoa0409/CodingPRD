"""Curfew-window geometry, half-open ping evaluation, and pairwise overlap.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules boundary_precision_check.
curfew_ping_end_minute_exclusive and resource_temporal_overlap.curfew_window_pairwise_overlap;
and SCAFFOLD_CORNER_DESIGN.yaml calculations.curfew_ping_at_home_true_no_violation.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_defendant, create_device, create_pending_enrollment,
    create_curfew_window_payload, create_ping_payload,
    setup_enrollment_with_curfew,
)

SUPERVISING = TEST_USERS["supervising_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]


# ─── boundary_precision_check / curfew_ping_end_minute_exclusive ───────────

def test_ping_at_end_minute_is_not_curfew_violation(api):
    """PRD §3.5: "whose half-open interval contains the ping's minute-of-day (that is, the
    minute is at least the window's `start_minute` and strictly less than its `end_minute`)."

    Design: Difficulty/boundary_precision_check/curfew_ping_end_minute_exclusive
    """
    ctx = setup_enrollment_with_curfew(day_of_week=0, start_minute=1200, end_minute=1320)
    enr_id = ctx["enrollment"]["id"]
    ping = validate_success(api.create_ping(
        enr_id, create_ping_payload("2026-06-01T22:00:00Z", at_home=False), SUPERVISING), 201)
    assert ping["is_curfew_violation"] is False, \
        "minute 1320 == end_minute is excluded from the half-open window"


def test_ping_one_minute_before_end_is_curfew_violation(api):
    """PRD §3.5: "the ping is a curfew violation exactly when `at_home` is false **and** the
    enrollment has a curfew window whose `day_of_week` matches the ping's day and whose
    half-open interval contains the ping's minute-of-day."

    Design: Difficulty/boundary_precision_check/curfew_ping_end_minute_exclusive
    """
    ctx = setup_enrollment_with_curfew(day_of_week=0, start_minute=1200, end_minute=1320)
    enr_id = ctx["enrollment"]["id"]
    ping = validate_success(api.create_ping(
        enr_id, create_ping_payload("2026-06-01T21:59:00Z", at_home=False), SUPERVISING), 201)
    assert ping["is_curfew_violation"] is True, \
        "minute 1319 is inside [1200,1320) with at_home false"


# ─── resource_temporal_overlap / curfew_window_pairwise_overlap ────────────

def _enr_version(api, enr_id):
    return validate_success(api.get_em_enrollment(enr_id, SUPERVISING), 200)["version"]


def test_overlapping_curfew_window_rejected(api):
    """PRD §3.5: "A new window may not overlap an existing window on the same enrollment and
    the same `day_of_week` ... while any true overlap is rejected with
    `ERR_CURFEW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/curfew_window_pairwise_overlap
    """
    d = create_defendant()
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(d["id"], dev["id"])
    v0 = enr["version"]
    validate_success(api.create_curfew_window(
        enr["id"], create_curfew_window_payload(v0, 0, 1200, 1320), SUPERVISING), 201)
    v1 = _enr_version(api, enr["id"])
    resp = api.create_curfew_window(
        enr["id"], create_curfew_window_payload(v1, 0, 1300, 1400), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_CURFEW_WINDOW_OVERLAP, 409)


def test_adjacent_curfew_window_accepted(api):
    """PRD §3.5: "two windows that merely touch end-to-start are adjacent and allowed."

    Design: Difficulty/resource_temporal_overlap/curfew_window_pairwise_overlap
    """
    d = create_defendant()
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(d["id"], dev["id"])
    v0 = enr["version"]
    validate_success(api.create_curfew_window(
        enr["id"], create_curfew_window_payload(v0, 0, 1200, 1320), SUPERVISING), 201)
    v1 = _enr_version(api, enr["id"])
    window = validate_success(api.create_curfew_window(
        enr["id"], create_curfew_window_payload(v1, 0, 1320, 1380), SUPERVISING), 201)
    assert window["day_of_week"] == 0
    assert window["start_minute"] == 1320 and window["end_minute"] == 1380


# ─── Corner: calculations.curfew_ping_at_home_true_no_violation ────────────

def test_ping_inside_window_but_at_home_is_no_violation(api):
    """PRD §3.5: "the ping is a curfew violation exactly when `at_home` is false **and** the
    enrollment has a curfew window whose `day_of_week` matches the ping's day and whose
    half-open interval contains the ping's minute-of-day."

    Design: Corner/calculations/curfew_ping_at_home_true_no_violation
    """
    ctx = setup_enrollment_with_curfew(day_of_week=0, start_minute=1200, end_minute=1320)
    def_id = ctx["defendant"]["id"]
    enr_id = ctx["enrollment"]["id"]
    ping = validate_success(api.create_ping(
        enr_id, create_ping_payload("2026-06-01T21:00:00Z", at_home=True), SUPERVISING), 201)
    assert ping["is_curfew_violation"] is False

    data, _ = validate_paginated(api.list_defendant_violations(def_id, JUDICIAL))
    curfew_violations = [v for v in data if v["violation_type"] == "CURFEW"]
    assert len(curfew_violations) == 0, "an at-home ping creates no CURFEW violation"
