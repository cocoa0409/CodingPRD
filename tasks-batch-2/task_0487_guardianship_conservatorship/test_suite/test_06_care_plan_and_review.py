"""Care-plan timeline tiling and the court-review lifecycle.

Difficulty: half-open window overlap on care-plan activate, point-in-time window
gate on review hold.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty: care-plan half-open [start, end) overlap vs adjacency
# ===========================================================================
def test_care_plan_overlap_rejected(api):
    """PRD 3.8: "the half-open window from window_start_iso up to but not including
    window_end_iso must not overlap the window of any other ACTIVE care plan on the
    same case (else ERR_CARE_PLAN_OVERLAP)."

    Design: Difficulty/resource_temporal_overlap/rto_care_plan_half_open_overlap
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2026-06-01T00:00:00Z",
    )
    overlap = get_success_data(
        api.create_care_plan(
            F.create_care_plan_payload(
                ctx["case_id"], residence_type="ASSISTED_LIVING", visitation_min_per_month=2,
                window_start_iso="2026-05-01T00:00:00Z", window_end_iso="2026-09-01T00:00:00Z",
            ),
            fx.make_fiduciary_headers(fid),
        )
    )
    validate_error(
        api.activate_care_plan(overlap["id"], fx.make_fiduciary_headers(fid)),
        ApiErrorId.ERR_CARE_PLAN_OVERLAP,
    )


def test_care_plan_adjacent_boundary_not_overlap(api):
    """PRD 3.8: "Because the upper bound is exclusive, one plan ending exactly when
    another begins is not an overlap."

    Design: Difficulty/resource_temporal_overlap/rto_care_plan_half_open_overlap
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2026-06-01T00:00:00Z",
    )
    adjacent = get_success_data(
        api.create_care_plan(
            F.create_care_plan_payload(
                ctx["case_id"], residence_type="ASSISTED_LIVING", visitation_min_per_month=2,
                window_start_iso="2026-06-01T00:00:00Z", window_end_iso="2026-09-01T00:00:00Z",
            ),
            fx.make_fiduciary_headers(fid),
        )
    )
    result = validate_success(
        api.activate_care_plan(adjacent["id"], fx.make_fiduciary_headers(fid))
    )
    assert result["status"] == "ACTIVE"


def test_care_plan_invalid_window_rejected(api):
    """PRD 3.8: "the window must be well-formed with window_start_iso strictly
    before window_end_iso (else ERR_INVALID_WINDOW)".

    Design: Corner/validations/care_plan_invalid_window_start_not_before_end
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = get_success_data(
        api.create_care_plan(
            F.create_care_plan_payload(
                ctx["case_id"],
                window_start_iso="2026-03-01T00:00:00Z", window_end_iso="2026-03-01T00:00:00Z",
            ),
            fx.make_fiduciary_headers(fid),
        )
    )
    validate_error(
        api.activate_care_plan(cp["id"], fx.make_fiduciary_headers(fid)),
        ApiErrorId.ERR_INVALID_WINDOW,
    )


def test_care_plan_expires_when_clock_passes_window_end(api):
    """PRD 3.8: "A plan is treated as EXPIRED once the logical clock reaches or
    passes its window_end_iso; this is re-derived on read and on operations rather
    than driven by a client call."

    Design: Corner/state_machines/care_plan_expires_when_clock_passes_window_end
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2026-06-01T00:00:00Z",
    )
    fx.set_clock("2026-06-01T00:00:00Z")
    read = get_success_data(api.get_care_plan(cp["id"], fx.make_fiduciary_headers(fid)))
    assert read["status"] == "EXPIRED"


# ===========================================================================
# Difficulty: review hold point-in-time window gate
# ===========================================================================
def test_review_hold_before_window_open_rejected(api):
    """PRD 3.9: "A judge holds a SCHEDULED review, moving it to HELD, which
    requires the case to be UNDER_REVIEW (else ERR_CASE_NOT_UNDER_REVIEW) and the
    clock to have reached or passed review_window_start_iso (else
    ERR_REVIEW_WINDOW_NOT_OPEN)."

    Design: Difficulty/resource_temporal_overlap/rto_review_window_point_gate
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2027-01-01T00:00:00Z",
    )
    api.open_review(ctx["case_id"], fx.JUDGE)
    rev = fx.schedule_review(
        ctx["case_id"], "CARE_PLAN", cp["id"],
        review_window_start_iso="2026-04-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    fx.set_clock("2026-03-01T00:00:00Z")
    validate_error(
        api.hold_review(rev["id"], fx.JUDGE), ApiErrorId.ERR_REVIEW_WINDOW_NOT_OPEN
    )


def test_review_hold_succeeds_after_window_opens(api):
    """PRD 3.9: "the clock to have reached or passed review_window_start_iso (else
    ERR_REVIEW_WINDOW_NOT_OPEN)."

    Design: Difficulty/resource_temporal_overlap/rto_review_window_point_gate
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2027-01-01T00:00:00Z",
    )
    api.open_review(ctx["case_id"], fx.JUDGE)
    rev = fx.schedule_review(
        ctx["case_id"], "CARE_PLAN", cp["id"],
        review_window_start_iso="2026-04-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    fx.set_clock("2026-04-01T00:00:00Z")
    result = validate_success(api.hold_review(rev["id"], fx.JUDGE))
    assert result["status"] == "HELD"


# ===========================================================================
# Review hold while case not under review
# ===========================================================================
def test_review_hold_rejected_when_case_active(api):
    """PRD 3.9: "A judge holds a SCHEDULED review, moving it to HELD, which
    requires the case to be UNDER_REVIEW (else ERR_CASE_NOT_UNDER_REVIEW)".

    Design: Corner/errors/error_case_not_under_review_hold_in_active_case
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2027-01-01T00:00:00Z",
    )
    # Schedule a review while the case is ACTIVE (POST /gc/reviews has no
    # case-state precondition) so hold fails on the case-state guard, not window.
    rev = fx.schedule_review(
        ctx["case_id"], "CARE_PLAN", cp["id"],
        review_window_start_iso="2026-01-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    validate_error(
        api.hold_review(rev["id"], fx.JUDGE), ApiErrorId.ERR_CASE_NOT_UNDER_REVIEW
    )


# ===========================================================================
# Review disposition with SANCTIONED cascade
# ===========================================================================
def test_review_dispose_sanctioned_returns_accounting(api):
    """PRD 3.9: "when the outcome is SANCTIONED, the subject kind is ACCOUNTING,
    and the subject AccountingReport is currently SUBMITTED, that report is driven
    to RETURNED_FOR_CORRECTION."

    Design: Corner/state_machines/review_dispose_sanctioned_returns_accounting
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=0,
    )
    api.open_review(ctx["case_id"], fx.JUDGE)
    rev = fx.schedule_review(
        ctx["case_id"], "ACCOUNTING", ar["id"],
        review_window_start_iso="2026-01-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    api.hold_review(rev["id"], fx.JUDGE)
    disposed = validate_success(
        api.dispose_review(rev["id"], F.dispose_review_payload("SANCTIONED"), fx.JUDGE)
    )
    assert disposed["outcome"] == "SANCTIONED"
    assert disposed["status"] == "CLOSED"
    ar_after = get_success_data(api.get_accounting(ar["id"], fx.JUDGE))
    assert ar_after["status"] == "RETURNED_FOR_CORRECTION"


# ===========================================================================
# Close-review / restore preconditions
# ===========================================================================
def test_close_review_blocked_by_open_review(api):
    """PRD 3.9: "closing is refused while any CourtReview on the case remains in
    SCHEDULED or HELD status, with ERR_OPEN_REVIEW_PENDING."

    Design: Corner/state_machines/close_review_blocked_by_open_review
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = ctx["fiduciary_id"]
    cp = fx.create_active_care_plan(
        ctx["case_id"], fid,
        window_start_iso="2026-01-01T00:00:00Z", window_end_iso="2027-01-01T00:00:00Z",
    )
    api.open_review(ctx["case_id"], fx.JUDGE)
    fx.schedule_review(
        ctx["case_id"], "CARE_PLAN", cp["id"],
        review_window_start_iso="2026-01-01T00:00:00Z",
        review_window_end_iso="2026-12-01T00:00:00Z",
    )
    validate_error(
        api.close_review(ctx["case_id"], fx.JUDGE), ApiErrorId.ERR_OPEN_REVIEW_PENDING
    )


def test_restore_blocked_without_accepted_review(api):
    """PRD 3.9: "A judge restores a case only from UNDER_REVIEW (else
    ERR_INVALID_STATE), and only when a CourtReview on the case has an outcome of
    ACCEPTED and a status of CLOSED (else ERR_RESTORATION_NOT_REVIEWED)".

    Design: Corner/state_machines/restore_blocked_without_accepted_review
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    api.open_review(ctx["case_id"], fx.JUDGE)
    validate_error(
        api.restore_case(ctx["case_id"], fx.JUDGE),
        ApiErrorId.ERR_RESTORATION_NOT_REVIEWED,
    )
