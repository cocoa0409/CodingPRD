"""Bed-hold leaves, paid-day caps, bed-hold-driven recomputes, and therapy capture.

Covers difficulty rules: transitive_cascade (bed-hold close recompute depth-2),
boundary_precision_check (qualifying midnights, therapy 25% cap),
resource_temporal_overlap (bed-hold half-open overlap), compensating_invariant
(covered_day_count paid bed-hold round trip), priority_pair_validation_conflict
(state beats referential on claim estimate), plus corner therapy/bed-hold instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
)

COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
THERAPIST = TEST_USERS["therapist_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


# =====================================================================
# Difficulty/boundary_precision_check/qualifying_stay_exactly_three_midnights_qualifies
# =====================================================================

@pytest.mark.parametrize(
    "admit_at,discharge_at,expected_midnights,expected_qualifies",
    [
        ("2026-01-27T08:00:00Z", "2026-01-29T20:00:00Z", 2, False),  # X-1: 2 midnights
        ("2026-01-26T08:00:00Z", "2026-01-29T20:00:00Z", 3, True),   # X: 3 midnights
        ("2026-01-25T08:00:00Z", "2026-01-29T20:00:00Z", 4, True),   # X+1: 4 midnights
    ],
)
def test_qualifying_stay_midnights_boundary(admit_at, discharge_at, expected_midnights, expected_qualifies):
    """PRD §3.2: "The system computes midnights_count as the number of calendar-date
    boundaries crossed between the two datetimes — that is, the UTC calendar date of
    the discharge minus the UTC calendar date of the admit, expressed in whole days.
    The stay qualifies (a computed boolean) precisely when midnights_count is at least 3".

    Design: Difficulty/boundary_precision_check/qualifying_stay_exactly_three_midnights_qualifies
    """
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    data = validate_success(
        api_client.create_qualifying_stay(
            resident["id"],
            f.create_qualifying_stay_payload(hospital_admit_at=admit_at, hospital_discharge_at=discharge_at),
            COORD,
        ),
        expected_status=201,
    )
    assert data["midnights_count"] == expected_midnights, (
        f"expected {expected_midnights} midnights, got {data['midnights_count']}")
    assert data["qualifies"] is expected_qualifies, (
        f"expected qualifies={expected_qualifies}, got {data['qualifies']}")


def test_qualifying_stay_exactly_three_midnights_qualifies():
    """PRD §3.2: "The stay qualifies (a computed boolean) precisely when midnights_count
    is at least 3".

    Design: Difficulty/boundary_precision_check/qualifying_stay_exactly_three_midnights_qualifies
    """
    # Exactly the >= boundary: 2026-01-26 -> 2026-01-29 spans 3 UTC midnights.
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    data = validate_success(
        api_client.create_qualifying_stay(
            resident["id"],
            f.create_qualifying_stay_payload(hospital_admit_at="2026-01-26T08:00:00Z",
                                             hospital_discharge_at="2026-01-29T20:00:00Z"),
            COORD),
        expected_status=201,
    )
    assert data["midnights_count"] == 3, f"expected 3 midnights, got {data['midnights_count']}"
    assert data["qualifies"] is True, "exactly 3 midnights must satisfy the >= 3 threshold"


# =====================================================================
# Difficulty/boundary_precision_check/therapy_group_cap_exactly_25pct_not_exceeded
# =====================================================================

def test_therapy_group_cap_exactly_25pct_not_exceeded():
    """PRD §3.5: "The exceeds_group_cap flag is true precisely when that percentage is
    strictly greater than 0.25 — i.e., when more than a quarter of delivered minutes
    came from group or concurrent sessions".

    Design: Difficulty/boundary_precision_check/therapy_group_cap_exactly_25pct_not_exceeded
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    get_success_data(api_client.create_therapy_log(
        admission["id"],
        f.create_therapy_log_payload(discipline="PT", mode="INDIVIDUAL", minutes=60,
                                     session_date="2026-02-02T00:00:00Z"), THERAPIST))
    get_success_data(api_client.create_therapy_log(
        admission["id"],
        f.create_therapy_log_payload(discipline="PT", mode="GROUP", minutes=20,
                                     session_date="2026-02-03T00:00:00Z"), THERAPIST))
    data = validate_success(api_client.get_therapy_summary(admission["id"], "PT", THERAPIST))
    assert data["group_concurrent_pct"] == pytest.approx(0.25), (
        f"20 group of 80 raw must be exactly 0.25, got {data['group_concurrent_pct']}")
    assert data["exceeds_group_cap"] is False, (
        "exactly 0.25 must NOT exceed the strict-> cap")


def test_therapy_group_cap_just_over_25pct_exceeded():
    """PRD §3.5: "The exceeds_group_cap flag is true precisely when that percentage is
    strictly greater than 0.25".

    Design: Difficulty/boundary_precision_check/therapy_group_cap_exactly_25pct_not_exceeded
    """
    # X+1 boundary: one more group minute (21 group of 81 raw) pushes pct > 0.25.
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    get_success_data(api_client.create_therapy_log(
        admission["id"],
        f.create_therapy_log_payload(discipline="PT", mode="INDIVIDUAL", minutes=60,
                                     session_date="2026-02-02T00:00:00Z"), THERAPIST))
    get_success_data(api_client.create_therapy_log(
        admission["id"],
        f.create_therapy_log_payload(discipline="PT", mode="GROUP", minutes=21,
                                     session_date="2026-02-03T00:00:00Z"), THERAPIST))
    data = validate_success(api_client.get_therapy_summary(admission["id"], "PT", THERAPIST))
    assert data["exceeds_group_cap"] is True, (
        "21/81 > 0.25 must exceed the cap")


# =====================================================================
# Difficulty/transitive_cascade/bedhold_close_returned_recompute_covered_day_count_depth2
# =====================================================================

def test_bedhold_close_returned_recomputes_covered_day_count():
    """PRD §3.6: "When the outcome is RETURNED, the bed-hold moves from OPEN to CLOSED:
    the actual_return_at is set ... and leave_day_count and paid_day_count are
    recomputed against the actual return ... and the admission's covered_day_count is
    reduced by the leave's unpaid portion (its leave_day_count minus its
    paid_day_count)".
    PRD §3.6: "Because the Medicare cap is 0, every leave day on a Medicare-A admission
    is unpaid".

    Design: Difficulty/transitive_cascade/bedhold_close_returned_recompute_covered_day_count_depth2
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    # Seed covered_day_count to 6 via a fully PAID claim.
    claim = fixtures.create_draft_claim(
        admission["id"], assessment["id"],
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    get_success_data(api_client.estimate_claim(claim["id"], {}, BILLING))
    fin = get_success_data(api_client.finalize_claim(claim["id"], {}, BILLING))
    get_success_data(api_client.submit_claim(
        claim["id"], {"expected_claim_version": fin["version"]}, BILLING))
    get_success_data(api_client.adjudicate_claim(claim["id"], {"decision": "PAID"}, BILLING))

    # 3-midnight Medicare-unpaid bed-hold opened after the claim window.
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-10T00:00:00Z",
                                  expected_return_at="2026-02-13T00:00:00Z"), COORD))
    closed = validate_success(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-13T00:00:00Z"}, COORD))
    assert closed["leave_day_count"] == 3, f"expected leave_day_count 3, got {closed['leave_day_count']}"
    assert closed["paid_day_count"] == 0, f"Medicare cap 0 -> paid_day_count 0, got {closed['paid_day_count']}"

    adm = validate_success(api_client.get_admission(admission["id"], COORD))
    assert adm["covered_day_count"] == 3, (
        f"covered_day_count must drop from 6 by 3 unpaid days to 3, got {adm['covered_day_count']}")


def test_bedhold_close_returned_returns_resident_to_admitted():
    """PRD §3.6: "When the outcome is RETURNED, the bed-hold moves from OPEN to CLOSED:
    the actual_return_at is set ... the resident moves from ON_LEAVE back to ADMITTED".
    PRD §3.6: "leave_day_count and paid_day_count are recomputed against the actual
    return".

    Design: Difficulty/transitive_cascade/bedhold_close_returned_recompute_covered_day_count_depth2
    """
    # Isolates hop 1 of the depth-2 chain (the bed_hold_days recompute on close) and
    # the accompanying resident state hop, without a pre-seeded covered_day_count.
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True)
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-10T00:00:00Z",
                                  expected_return_at="2026-02-13T00:00:00Z"), COORD))
    closed = validate_success(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-13T00:00:00Z"}, COORD))
    assert closed["leave_day_count"] == 3, f"expected leave_day_count 3, got {closed['leave_day_count']}"
    assert closed["paid_day_count"] == 0, f"Medicare cap 0 -> paid 0, got {closed['paid_day_count']}"
    res = validate_success(api_client.get_resident(resident["id"], COORD))
    assert res["status"] == "ADMITTED", f"resident must return to ADMITTED, got {res['status']}"


# =====================================================================
# Difficulty/compensating_invariant/covered_day_count_paid_bedhold_round_trip_conserved
# =====================================================================

def test_covered_day_count_conserved_paid_medicaid_bedhold():
    """PRD §3.6: "The paid_day_count is the subset of leave days the payer credits: it
    is the lesser of leave_day_count and the payer's paid bed-hold cap, where the caps
    are 10 days for MEDICAID".
    PRD §3.6: "the admission's covered_day_count is reduced by the leave's unpaid
    portion (its leave_day_count minus its paid_day_count)".

    Design: Difficulty/compensating_invariant/covered_day_count_paid_bedhold_round_trip_conserved
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="MEDICAID")
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-08T00:00:00Z"), COORD))
    closed = validate_success(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-08T00:00:00Z"}, COORD))
    assert closed["leave_day_count"] == 3, f"expected leave_day_count 3, got {closed['leave_day_count']}"
    assert closed["paid_day_count"] == 3, f"all 3 under MEDICAID cap -> paid 3, got {closed['paid_day_count']}"

    adm = validate_success(api_client.get_admission(admission["id"], COORD))
    assert adm["covered_day_count"] == 0, (
        f"unpaid portion 0 -> covered_day_count conserved at 0, got {adm['covered_day_count']}")


def test_covered_day_count_unchanged_round_trip_resident_readmitted():
    """PRD §3.6: "Opening a bed-hold creates a BedHold in OPEN status and moves the
    resident from ADMITTED to ON_LEAVE".
    PRD §3.6: "the admission's covered_day_count is reduced by the leave's unpaid
    portion (its leave_day_count minus its paid_day_count)".

    Design: Difficulty/compensating_invariant/covered_day_count_paid_bedhold_round_trip_conserved
    """
    # ADMITTED -> ON_LEAVE -> ADMITTED round trip; with a fully-paid Medicaid hold the
    # unpaid portion is 0, so the close subtracts nothing and covered_day_count is conserved.
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="MEDICAID")
    before = validate_success(api_client.get_admission(admission["id"], COORD))
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="THERAPEUTIC",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-08T00:00:00Z"), COORD))
    on_leave = validate_success(api_client.get_resident(resident["id"], COORD))
    assert on_leave["status"] == "ON_LEAVE", f"expected ON_LEAVE during hold, got {on_leave['status']}"
    get_success_data(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-08T00:00:00Z"}, COORD))
    readmitted = validate_success(api_client.get_resident(resident["id"], COORD))
    assert readmitted["status"] == "ADMITTED", f"expected ADMITTED after return, got {readmitted['status']}"
    after = validate_success(api_client.get_admission(admission["id"], COORD))
    assert after["covered_day_count"] == before["covered_day_count"], (
        f"fully-paid hold must conserve covered_day_count "
        f"({before['covered_day_count']} -> {after['covered_day_count']})")


# =====================================================================
# Difficulty/resource_temporal_overlap/bedhold_overlap_half_open_touching_allowed
# =====================================================================

def test_bedhold_overlap_strict_rejected():
    """PRD §3.6: "the new leave window, treated as the half-open interval from
    leave_start_at (inclusive) to expected_return_at (exclusive), must not overlap any
    existing bed-hold window for the same admission; touching endpoints are permitted
    (an end exactly equal to a start is not an overlap), but a true overlap is rejected
    with ERR_BEDHOLD_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/bedhold_overlap_half_open_touching_allowed
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    bh1 = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="THERAPEUTIC",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-09T00:00:00Z"), COORD))
    # Close RETURNED so the admission is ACTIVE again, leaving the recorded window.
    get_success_data(api_client.close_bed_hold(
        bh1["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-09T00:00:00Z"}, COORD))
    # New window 02-07..02-11 strictly overlaps the recorded 02-05..02-09.
    resp = api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-07T00:00:00Z",
                                  expected_return_at="2026-02-11T00:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_BEDHOLD_OVERLAP.value)


def test_bedhold_touching_endpoint_allowed():
    """PRD §3.6: "touching endpoints are permitted (an end exactly equal to a start is
    not an overlap)".

    Design: Difficulty/resource_temporal_overlap/bedhold_overlap_half_open_touching_allowed
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    bh1 = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="THERAPEUTIC",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-09T00:00:00Z"), COORD))
    get_success_data(api_client.close_bed_hold(
        bh1["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-09T00:00:00Z"}, COORD))
    # New window starts exactly at the prior window's end -> not an overlap.
    data = validate_success(
        api_client.create_bed_hold(
            admission["id"],
            f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                      leave_start_at="2026-02-09T00:00:00Z",
                                      expected_return_at="2026-02-11T00:00:00Z"), COORD),
        expected_status=201,
    )
    assert data["status"] == "OPEN", f"touching bed-hold should be created OPEN, got {data['status']}"


# =====================================================================
# Difficulty/priority_pair_validation_conflict/state_beats_referential_on_claim_estimate
# =====================================================================

def test_estimate_reports_state_before_referential():
    """PRD §2.7: "Fifth, state — on a transition endpoint, the target resource must be
    in a state from which the requested transition is legal, else ERR_INVALID_STATE.
    Only after all five of these structural gates pass does the system evaluate the
    operation-specific business rules described throughout §3".
    PRD §3.9: "Estimating ... requires ... that the driving assessment be SUBMITTED".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_claim_estimate
    """
    facility, admission, assessment, estimated = fixtures.setup_estimated_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    # Supersede the driving assessment via a submitted correction so it is no longer
    # SUBMITTED. Now the claim is in the wrong state (ESTIMATED, not DRAFT) AND the
    # driving assessment is not SUBMITTED: both the state gate and the referential rule
    # would fail, and the state gate (priority 5) must win.
    fixtures.supersede_assessment(admission["id"], assessment)
    resp = api_client.estimate_claim(estimated["id"], {}, BILLING)
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_estimate_wrong_state_does_not_surface_referential_error():
    """PRD §2.7: "Only after all five of these structural gates pass does the system
    evaluate the operation-specific business rules described throughout §3".
    PRD §3.9: "Estimating a draft claim moves it from DRAFT to ESTIMATED".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_claim_estimate
    """
    # Re-estimating an already-ESTIMATED claim whose driving assessment was superseded
    # to non-SUBMITTED must NOT surface the referential ERR_ASSESSMENT_NOT_SUBMITTED.
    facility, admission, assessment, estimated = fixtures.setup_estimated_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    fixtures.supersede_assessment(admission["id"], assessment)
    err = validate_error(
        api_client.estimate_claim(estimated["id"], {}, BILLING),
        ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTED.value


# =====================================================================
# Corner/calculations/therapy_summary_individual_equivalent_weighting
# =====================================================================

def test_therapy_summary_individual_equivalent_weighting():
    """PRD §3.5: "The individual_equivalent_minutes for a row equal its raw minutes when
    the mode is INDIVIDUAL, the raw minutes divided by 2 and rounded down to a whole
    number when the mode is CONCURRENT, and the raw minutes divided by 4 and rounded
    down to a whole number when the mode is GROUP".
    PRD §3.5: "The exceeds_group_cap flag is true precisely when that percentage is
    strictly greater than 0.25".

    Design: Corner/calculations/therapy_summary_individual_equivalent_weighting
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    logs = [
        ("INDIVIDUAL", 60, "2026-02-02T00:00:00Z"),
        ("CONCURRENT", 60, "2026-02-03T00:00:00Z"),
        ("GROUP", 60, "2026-02-04T00:00:00Z"),
        ("INDIVIDUAL", 40, "2026-02-05T00:00:00Z"),
    ]
    for mode, minutes, date in logs:
        get_success_data(api_client.create_therapy_log(
            admission["id"],
            f.create_therapy_log_payload(discipline="PT", mode=mode, minutes=minutes, session_date=date),
            THERAPIST))
    data = validate_success(api_client.get_therapy_summary(admission["id"], "PT", THERAPIST))
    assert data["total_raw"] == 220, f"expected total_raw 220, got {data['total_raw']}"
    assert data["total_individual_equiv"] == 145, (
        f"60+30+15+40 == 145, got {data['total_individual_equiv']}")
    assert data["exceeds_group_cap"] is True, "120/220 > 0.25 must exceed the cap"


# =====================================================================
# Corner/calculations/bed_hold_medicaid_partial_paid_over_cap
# =====================================================================

def test_bedhold_medicaid_paid_capped_at_ten():
    """PRD §3.6: "The paid_day_count is the subset of leave days the payer credits: it
    is the lesser of leave_day_count and the payer's paid bed-hold cap, where the caps
    are 10 days for MEDICAID".

    Design: Corner/calculations/bed_hold_medicaid_partial_paid_over_cap
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="MEDICAID")
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-17T00:00:00Z"), COORD))
    closed = validate_success(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-17T00:00:00Z"}, COORD))
    assert closed["leave_day_count"] == 12, f"expected leave_day_count 12, got {closed['leave_day_count']}"
    assert closed["paid_day_count"] == 10, (
        f"MEDICAID cap 10 -> paid_day_count capped at 10, got {closed['paid_day_count']}")


# =====================================================================
# Corner/validations/error_therapy_out_of_stay_before_admit
# =====================================================================

def test_therapy_out_of_stay_before_admit():
    """PRD §3.5: "A session may only be logged while its session_date falls within the
    admission's stay window — on or after the admission's admit_at and not in the
    future ... a session outside the stay window or against an admission in a
    therapy-ineligible state is rejected with ERR_THERAPY_OUT_OF_STAY".

    Design: Corner/validations/error_therapy_out_of_stay_before_admit
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    # admit_at 2026-02-01; session dated 2026-01-15 is before the stay window.
    resp = api_client.create_therapy_log(
        admission["id"],
        f.create_therapy_log_payload(discipline="PT", mode="INDIVIDUAL", minutes=45,
                                     session_date="2026-01-15T00:00:00Z"), THERAPIST)
    validate_error(resp, ApiErrorId.ERR_THERAPY_OUT_OF_STAY.value)


# =====================================================================
# Corner/validations/error_bedhold_already_open
# =====================================================================

def test_bedhold_already_open_rejected():
    """PRD §3.6: "A bed-hold may only be opened while the admission is ACTIVE and while
    no other bed-hold for that admission is currently OPEN; an attempt while the
    admission is not ACTIVE or while another hold is already open is rejected with
    ERR_BEDHOLD_ALREADY_OPEN".

    Design: Corner/validations/error_bedhold_already_open
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-08T00:00:00Z"), COORD))
    resp = api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="THERAPEUTIC",
                                  leave_start_at="2026-02-10T00:00:00Z",
                                  expected_return_at="2026-02-12T00:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_BEDHOLD_ALREADY_OPEN.value)
