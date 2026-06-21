"""Demerit-point ledger, rolling-window aggregation, and traffic-school reduction.

Covers dual-variant raw-vs-windowed point balance, the rolling-window and cooldown
interval semantics, and the uphold-then-school compensating invariant.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_enrollment_payload,
    create_contest_request_payload,
    create_schedule_payload,
    create_decide_payload,
    make_driver_headers,
)
from test_helpers.fixtures import (
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_driver_with_uphold,
    uphold_citation_points,
    pay_citation_in_full,
    file_contest,
    set_clock,
    list_point_ledger,
    CLERK,
    HEARING,
)
from test_helpers.api_client import api_client as _api


def _assess_uphold_citation(api, driver_id, issued_at, appear_by, hearing_at,
                            points=2, base_fine_cents=10000):
    """Create + charge + assess + contest + schedule + UPHOLD. Returns citation."""
    cit = validate_success(
        api.create_citation(
            create_citation_payload(driver_id, issued_at=issued_at, appear_by=appear_by),
            CLERK,
        ),
        201,
    )
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC23103", description="Reckless",
            base_fine_cents=base_fine_cents, points=points,
        ),
        CLERK,
    )
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    contest = file_contest(cit["id"], driver_id)
    api.schedule_hearing(contest["id"], create_schedule_payload(hearing_at), CLERK)
    api.decide_contest(contest["id"], create_decide_payload("UPHOLD"), HEARING)
    return assessed


def test_raw_posted_points_vs_active_windowed_point_balance(api):
    """PRD §3.8: "The driver's `point_balance` is the sum of the `points` over the
    driver's `ACTIVE` entries whose `effective_at` falls on or after the window
    start ... masked entries are excluded from the sum."
    PRD §3.9: "On completion the server freezes `points_reduced` ... and masks that
    many points' worth of those entries by flipping their `state` from `ACTIVE` to
    `MASKED`."

    Design: Difficulty/dual_variant_calc/raw_posted_points_vs_active_windowed_point_balance
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = _assess_uphold_citation(
        api, driver["id"], "2026-01-04T00:00:00Z", "2026-02-04T00:00:00Z",
        "2026-03-01T00:00:00Z", points=1, base_fine_cents=10000,
    )
    # Pay fully, then enroll and complete traffic school -> the 1-point entry masked.
    pay_citation_in_full(
        validate_success(api.get_citation(cit["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    completed = validate_success(api.complete_enrollment(enrollment["id"], CLERK), 200)
    assert completed["points_reduced"] == 1
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 0
    # The raw entry still exists in the ledger, now MASKED.
    entries = list_point_ledger(citation_id=cit["id"])
    masked = [e for e in entries if e["state"] == "MASKED"]
    assert len(masked) == 1
    assert masked[0]["points"] == 1


def test_masked_entry_persists_but_excluded_from_balance(api):
    """PRD §2.4: "When the system masks a point entry as part of a traffic-school
    reduction, that is modeled as a state change on the entry's `state` field, but
    the entry itself does not expose the standard mutation bookkeeping that other
    resources do."
    PRD §3.8: "masked entries are excluded from the sum."

    Design: Difficulty/dual_variant_calc/raw_posted_points_vs_active_windowed_point_balance
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = _assess_uphold_citation(
        _api, driver["id"], "2026-01-04T00:00:00Z", "2026-02-04T00:00:00Z",
        "2026-03-01T00:00:00Z", points=1, base_fine_cents=10000,
    )
    pay_citation_in_full(
        validate_success(_api.get_citation(cit["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        _api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    _api.complete_enrollment(enrollment["id"], CLERK)
    # The ledger still has exactly one entry (now MASKED) — raw row count unchanged.
    all_entries = list_point_ledger(citation_id=cit["id"])
    assert len(all_entries) == 1
    assert all_entries[0]["state"] == "MASKED"
    # But the driver's windowed ACTIVE balance is 0.
    driver_after = validate_success(_api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 0


def test_point_rolling_window_aggregate_excludes_aged_entry(api):
    """PRD §3.8: "The driver's `point_balance` is the sum of the `points` over the
    driver's `ACTIVE` entries whose `effective_at` falls on or after the window
    start, where the window start is the current moment less the jurisdiction's
    `point_window_months`; masked entries are excluded from the sum."
    PRD §3.8: "Each entry carries its `driver_id`, the `citation_id` it stems from,
    the `points` posted, an `effective_at` date equal to the source citation's
    `issued_at` (which drives the rolling window), and a `state` of `ACTIVE` or
    `MASKED`."

    Design: Difficulty/resource_temporal_overlap/point_rolling_window_aggregate_excludes_aged_entry
    """
    set_clock("2025-01-10T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    # Citation P: issued 2025-01-02, UPHELD 2 pts -> will age out of a window at 2026-05-01.
    _assess_uphold_citation(
        api, driver["id"], "2025-01-02T00:00:00Z", "2025-03-02T00:00:00Z",
        "2025-02-01T00:00:00Z", points=2,
    )
    set_clock("2026-04-10T00:00:00Z")
    # Citation Q: issued 2026-04-02, UPHELD 2 pts -> in-window.
    cit_q = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-04-02T00:00:00Z",
                appear_by="2026-06-02T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(
        create_charge_payload(
            cit_q["id"], violation_code="VC23103", description="Reckless",
            base_fine_cents=10000, points=2,
        ),
        CLERK,
    )
    api.assess_citation(cit_q["id"], CLERK)
    contest_q = file_contest(cit_q["id"], driver["id"])
    api.schedule_hearing(contest_q["id"], create_schedule_payload("2026-05-15T00:00:00Z"), CLERK)
    set_clock("2026-05-01T00:00:00Z")
    api.decide_contest(contest_q["id"], create_decide_payload("UPHOLD"), HEARING)
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    # Only citation Q's entry (2026-04-02) is inside the 12-month window from 2026-05-01.
    assert driver_after["point_balance"] == 2
    assert driver_after["license_status"] != "SUSPENDED"


def test_school_cooldown_lookback_window_overlap(api):
    """PRD §3.9: "the driver must not have completed traffic school within the
    jurisdiction's `school_cooldown_months` ... A request that fails any of these is
    rejected with `ERR_SCHOOL_INELIGIBLE`."
    PRD §3.1: "The `school_cooldown_months` (default 18) caps how often a driver may
    complete traffic school."

    Design: Difficulty/resource_temporal_overlap/school_cooldown_lookback_window_overlap
    """
    set_clock("2026-01-15T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    # Citation X: paid, enrolled, completed at clock 2026-02-01.
    cit_x = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-28T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit_x["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit_x["id"], CLERK)
    pay_citation_in_full(
        validate_success(api.get_citation(cit_x["id"], CLERK), 200), driver["id"]
    )
    enr_x = validate_success(
        api.create_enrollment(
            cit_x["id"], create_enrollment_payload("2026-03-15T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    set_clock("2026-02-01T00:00:00Z")
    api.complete_enrollment(enr_x["id"], CLERK)
    # Citation Y: 4 months later (< 18-month cooldown), paid, enrollment attempted.
    set_clock("2026-06-01T00:00:00Z")
    cit_y = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-05-04T00:00:00Z",
                appear_by="2026-07-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit_y["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit_y["id"], CLERK)
    pay_citation_in_full(
        validate_success(api.get_citation(cit_y["id"], CLERK), 200), driver["id"]
    )
    res = api.create_enrollment(
        cit_y["id"], create_enrollment_payload("2026-07-01T00:00:00Z"),
        make_driver_headers(driver["id"]),
    )
    validate_error(res, "ERR_SCHOOL_INELIGIBLE")


def test_point_window_in_window_entry_contributes(api):
    """PRD §3.8: "The driver's `point_balance` is the sum of the `points` over the
    driver's `ACTIVE` entries whose `effective_at` falls on or after the window
    start, where the window start is the current moment less the jurisdiction's
    `point_window_months`; masked entries are excluded from the sum."

    Design: Difficulty/resource_temporal_overlap/point_rolling_window_aggregate_excludes_aged_entry
    """
    # A single recent UPHELD 2-point entry is well inside the 12-month window.
    jur, driver, cit = setup_driver_with_uphold(points=2, clock="2026-05-01T00:00:00Z")
    driver_after = validate_success(_api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 2


def test_school_cooldown_first_completion_allows_enrollment(api):
    """PRD §3.9: "the driver must not have completed traffic school within the
    jurisdiction's `school_cooldown_months` ... A request that fails any of these is
    rejected with `ERR_SCHOOL_INELIGIBLE`."
    PRD §3.9: "A `Driver` (or clerk) enrolls under a citation by supplying the
    `completion_due_at` deadline; the enrollment also records the `driver_id` behind
    the citation, freezes `eligible_points` as the total `points` across the
    citation's charges at the moment of enrollment, opens with `status` `ENROLLED`,
    and starts `points_reduced` at zero."

    Design: Difficulty/resource_temporal_overlap/school_cooldown_lookback_window_overlap
    """
    set_clock("2026-01-15T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    # First-ever enrollment for this driver: no prior completion, so cooldown is satisfied.
    cit = validate_success(
        _api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-28T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    _api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    _api.assess_citation(cit["id"], CLERK)
    pay_citation_in_full(
        validate_success(_api.get_citation(cit["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        _api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-03-15T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    assert enrollment["status"] == "ENROLLED"


def test_uphold_then_school_conserves_driver_point_balance(api):
    """PRD §3.7: "as a cascade the server posts one **PointLedgerEntry** with `state`
    `ACTIVE` for each charge whose `points` are greater than zero, and those new
    entries re-evaluate the driver's point suspension, potentially opening a
    point-suspension hold and re-deriving the driver's `license_status` to
    `SUSPENDED`."
    PRD §3.9: "On completion the server freezes `points_reduced` as the smaller of
    the enrollment's `eligible_points` and the candidate total — the sum of `points`
    across the citation's still-`ACTIVE` point ledger entries — and masks that many
    points' worth of those entries by flipping their `state` from `ACTIVE` to
    `MASKED`."

    Design: Difficulty/compensating_invariant/uphold_then_school_conserves_driver_point_balance
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver(
        jurisdiction_overrides={
            "name": "Court D", "state_code": "OR", "school_eligible_max_points": 2
        }
    )
    cit = _assess_uphold_citation(
        api, driver["id"], "2026-01-04T00:00:00Z", "2026-02-04T00:00:00Z",
        "2026-03-01T00:00:00Z", points=2,
    )
    before = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert before["point_balance"] == 2  # post-uphold
    pay_citation_in_full(
        validate_success(api.get_citation(cit["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    completed = validate_success(api.complete_enrollment(enrollment["id"], CLERK), 200)
    assert completed["points_reduced"] == 2
    after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    # Returned to its pre-uphold value (0): +2 from UPHOLD fully offset by -2 mask.
    assert after["point_balance"] == 0


def test_uphold_posts_point_ledger_entry_active(api):
    """PRD §3.7: "as a cascade the server posts one **PointLedgerEntry** with `state`
    `ACTIVE` for each charge whose `points` are greater than zero, and those new
    entries re-evaluate the driver's point suspension, potentially opening a
    point-suspension hold and re-deriving the driver's `license_status` to
    `SUSPENDED`."

    Design: Difficulty/compensating_invariant/uphold_then_school_conserves_driver_point_balance
    """
    jur, driver, cit = setup_driver_with_uphold(points=2)
    entries = list_point_ledger(driver_id=driver["id"])
    active = [e for e in entries if e["state"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["points"] == 2
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 2
