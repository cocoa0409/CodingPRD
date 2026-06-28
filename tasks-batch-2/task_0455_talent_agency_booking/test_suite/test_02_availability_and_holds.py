"""Availability summaries and conflict-hold interactions.

Covers the forward-looking projected vs chronological committed availability
calculations, the same-kind half-open overlap rejection, and the
confirmed-booking-beats-first-refusal conflict side effect.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_availability_hold_payload,
    setup_rostered_talent,
    create_availability_hold,
)

AGENT = TEST_USERS["agent_headers"]


# ─── dual_variant_calc: projected vs committed availability ──────────────────
def test_projected_blocked_days_counts_all_active_holds(api):
    """PRD §3.4: "the forward-looking **projected blocked days**
    (`projected_blocked_days`), counts every `ACTIVE` hold regardless of kind —
    both first-refusal and confirmed ... It is the sum, over every `ACTIVE` hold
    for the talent, of that hold's inclusive day span (end date minus start
    date, plus one)."

    Design: Difficulty/dual_variant_calc/availability_projection_vs_committed_diverges
    """
    base = setup_rostered_talent(union_status="SAG")
    talent_id = base["talent"]["id"]
    # FIRST_REFUSAL 3 days + CONFIRMED_BOOKING 5 days = 8 projected.
    create_availability_hold(
        talent_id, start_date="2026-03-10T00:00:00Z",
        end_date="2026-03-12T00:00:00Z", hold_kind="FIRST_REFUSAL",
    )
    create_availability_hold(
        talent_id, start_date="2026-03-15T00:00:00Z",
        end_date="2026-03-19T00:00:00Z", hold_kind="CONFIRMED_BOOKING",
    )
    summary = validate_success(
        api.get_talent_availability_summary(talent_id, AGENT), 200
    )
    assert summary["projected_blocked_days"] == 8


def test_committed_days_excludes_first_refusal_holds(api):
    """PRD §3.4: "the chronological **committed days** (`committed_days`), counts
    only days actually committed: it considers only `ACTIVE` holds whose
    `hold_kind` is `CONFIRMED_BOOKING`, processes them in ascending `created_at`
    order, merges overlapping confirmed windows so that any calendar day is
    counted exactly once, and reports the resulting merged inclusive day count."

    Design: Difficulty/dual_variant_calc/availability_projection_vs_committed_diverges
    """
    base = setup_rostered_talent(union_status="SAG")
    talent_id = base["talent"]["id"]
    create_availability_hold(
        talent_id, start_date="2026-03-10T00:00:00Z",
        end_date="2026-03-12T00:00:00Z", hold_kind="FIRST_REFUSAL",
    )
    create_availability_hold(
        talent_id, start_date="2026-03-15T00:00:00Z",
        end_date="2026-03-19T00:00:00Z", hold_kind="CONFIRMED_BOOKING",
    )
    summary = validate_success(
        api.get_talent_availability_summary(talent_id, AGENT), 200
    )
    # Only the CONFIRMED_BOOKING 5-day hold counts.
    assert summary["committed_days"] == 5
    assert summary["projected_blocked_days"] != summary["committed_days"]


# ─── resource_temporal_overlap: same-kind hold overlap rejected ──────────────
def test_same_kind_hold_overlap_rejected(api):
    """PRD §3.4: "Two holds of the **same** kind on the **same** talent may not
    overlap. Overlap here is measured on the half-open interval running from the
    start date up to but not including the day after the end date ... A same-kind
    overlap is rejected with `ERR_HOLD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/availability_hold_same_kind_overlap_rejected
    """
    base = setup_rostered_talent(union_status="SAG")
    talent_id = base["talent"]["id"]
    create_availability_hold(
        talent_id, start_date="2026-03-10T00:00:00Z",
        end_date="2026-03-12T00:00:00Z", hold_kind="FIRST_REFUSAL",
    )
    # Second FIRST_REFUSAL hold sharing 2026-03-12 overlaps under half-open rule.
    resp = api.create_availability_hold(
        create_availability_hold_payload(
            talent_id, start_date="2026-03-12T00:00:00Z",
            end_date="2026-03-14T00:00:00Z", hold_kind="FIRST_REFUSAL",
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_HOLD_OVERLAP.value, 409)


def test_back_to_back_same_kind_holds_allowed(api):
    """PRD §3.4: "two same-kind holds that sit exactly back-to-back — one ending
    the day before the next begins — are allowed."

    Design: Difficulty/resource_temporal_overlap/availability_hold_same_kind_overlap_rejected
    """
    base = setup_rostered_talent(union_status="SAG")
    talent_id = base["talent"]["id"]
    create_availability_hold(
        talent_id, start_date="2026-03-10T00:00:00Z",
        end_date="2026-03-12T00:00:00Z", hold_kind="FIRST_REFUSAL",
    )
    # Next hold starts the day after the first ends — back-to-back, allowed.
    resp = api.create_availability_hold(
        create_availability_hold_payload(
            talent_id, start_date="2026-03-13T00:00:00Z",
            end_date="2026-03-15T00:00:00Z", hold_kind="FIRST_REFUSAL",
        ),
        AGENT,
    )
    hold = validate_success(resp, 201)
    assert hold["status"] == "ACTIVE"


# ─── state_machine: confirmed booking conflicts first-refusal hold ──────────
def test_confirmed_booking_hold_conflicts_overlapping_first_refusal(api):
    """PRD §3.4: "when a `CONFIRMED_BOOKING` hold is created and it overlaps an
    existing `ACTIVE` `FIRST_REFUSAL` hold on the same talent, that first-refusal
    hold is bumped from `ACTIVE` to `CONFLICTED` as a side effect — a confirmed
    booking beats a speculative first refusal."

    Design: Corner/state_machines/confirmed_booking_conflicts_first_refusal_hold
    """
    base = setup_rostered_talent(union_status="SAG")
    talent_id = base["talent"]["id"]
    fr_hold = create_availability_hold(
        talent_id, start_date="2026-03-15T00:00:00Z",
        end_date="2026-03-19T00:00:00Z", hold_kind="FIRST_REFUSAL",
    )
    resp = api.create_availability_hold(
        create_availability_hold_payload(
            talent_id, start_date="2026-03-17T00:00:00Z",
            end_date="2026-03-21T00:00:00Z", hold_kind="CONFIRMED_BOOKING",
        ),
        AGENT,
    )
    cb_hold = validate_success(resp, 201)
    assert cb_hold["status"] == "ACTIVE"

    refreshed_fr = validate_success(
        api.get_availability_hold(fr_hold["id"], AGENT), 200
    )
    assert refreshed_fr["status"] == "CONFLICTED"
