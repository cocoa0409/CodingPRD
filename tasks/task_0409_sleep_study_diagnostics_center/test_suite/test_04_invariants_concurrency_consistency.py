"""Compensating invariants (bed occupancy, study counts), optimistic-concurrency
stale-version rejection, and immediate-consistency propagation.

Covers difficulty queue (A) compensating-invariant instances and corner queue (B)
cross-cutting-complexity-layer and consistency-model instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_authorized_referral,
    create_scheduled_study,
    create_scored_study,
    create_fulfilled_dme_with_window,
    create_ordered_study,
    create_bed,
    create_study_order_payload,
    schedule_study_payload,
    score_study_payload,
    create_compliance_record_payload,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]
TECH = TEST_USERS["sleep_technologist_headers"]
PHYS = TEST_USERS["physician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]


# ─── Compensating invariant: bed occupancy conserved ───────────────────────

def test_bed_night_rebookable_after_schedule_then_cancel(api):
    """PRD 3.8: "A successful cancel moves the study to CANCELLED, which is
    terminal, and if the study was holding a bed night, that occupancy — including
    its trailing turnover buffer — is released so the interval becomes bookable
    again."

    Schedule a study on night N, cancel it, then a fresh study books the exact
    same night N without ERR_BED_DOUBLE_BOOKED.

    Design: Difficulty/compensating_invariant/bed_occupation_conserved_on_schedule_then_cancel
    """
    bed = create_bed()
    _, _, study1, _ = create_scheduled_study(
        modality="IN_LAB_PSG", bed=bed,
        night_start_utc="2026-07-25T22:00:00Z", night_end_utc="2026-07-26T06:00:00Z",
    )
    cancelled = validate_success(api.cancel_study(study1["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"

    _, ref2 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-INV1")
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-25T22:00:00Z",
                               night_end_utc="2026-07-26T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    rebooked = validate_success(res, 200)
    assert rebooked["status"] == "SCHEDULED", "Cancelled night must be re-bookable"


def test_cancelled_study_releases_held_bed_night(api):
    """PRD 3.8: "if the study was holding a bed night, that occupancy — including
    its trailing turnover buffer — is released so the interval becomes bookable
    again."

    The cancel transition itself leaves the original study CANCELLED, freeing the
    occupied interval.

    Design: Difficulty/compensating_invariant/bed_occupation_conserved_on_schedule_then_cancel
    """
    bed = create_bed()
    _, _, study1, _ = create_scheduled_study(
        modality="IN_LAB_PSG", bed=bed,
        night_start_utc="2026-07-25T22:00:00Z", night_end_utc="2026-07-26T06:00:00Z",
    )
    cancelled = validate_success(api.cancel_study(study1["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"
    # The freed interval is immediately re-bookable by a second study.
    _, ref2 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-INV2")
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-25T22:00:00Z",
                               night_end_utc="2026-07-26T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    assert get_success_data(res)["status"] == "SCHEDULED"


# ─── Compensating invariant: non-cancelled study count conserved ───────────

def test_noncancelled_study_count_restored_after_create_then_cancel(api):
    """PRD 3.8: "Independent of the referral-level cascade, a SchedulingCoordinator
    may cancel an individual study while it is in either ORDERED or SCHEDULED."
    PRD 2.3: "A referral, study-order, DME-order, or bed list may be filtered by
    status; the referral list also accepts patient_id; the study-order list
    accepts referral_id and bed_id."

    Start with one ORDERED study (count 1). Create a second (count 2), cancel it,
    and the ORDERED-filtered list returns to total_count 1.

    Design: Difficulty/compensating_invariant/noncancelled_study_count_conserved_on_create_then_cancel
    """
    _, referral, study1 = create_ordered_study(modality="HSAT")
    referral_after = get_success_data(api.get_referral(referral["id"], COORD))
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], referral_after["version"],
                                       modality="HSAT"),
            COORD,
        )
    )
    cancelled = validate_success(api.cancel_study(study2["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"
    data, meta = validate_paginated(
        api.list_study_orders(COORD, params={"referral_id": referral["id"], "status": "ORDERED"})
    )
    assert meta["total_count"] == 1, f"Expected 1 ORDERED study, got {meta['total_count']}"


def test_cancelled_study_excluded_first_study_remains_ordered(api):
    """PRD 3.8: "A successful cancel moves the study to CANCELLED, which is
    terminal."
    PRD 2.3: "A referral, study-order, DME-order, or bed list may be filtered by
    status."

    After cancelling the second study, the first remains ORDERED and the cancelled
    one is excluded from the ORDERED-filtered tally.

    Design: Difficulty/compensating_invariant/noncancelled_study_count_conserved_on_create_then_cancel
    """
    _, referral, study1 = create_ordered_study(modality="HSAT")
    referral_after = get_success_data(api.get_referral(referral["id"], COORD))
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], referral_after["version"],
                                       modality="HSAT"),
            COORD,
        )
    )
    api.cancel_study(study2["id"], COORD)
    study1_after = get_success_data(api.get_study_order(study1["id"], COORD))
    study2_after = get_success_data(api.get_study_order(study2["id"], COORD))
    assert study1_after["status"] == "ORDERED"
    assert study2_after["status"] == "CANCELLED"


# ─── OCC: stale referral version on study create (corner) ──────────────────

def test_stale_referral_version_on_study_create_rejected(api):
    """PRD 2.9: "Creating a study order against a referral requires
    expected_referral_version to equal the referral's current version. If a prior
    write — an authorization approval that stamped the authorization number and
    expiry, or a cancellation — has advanced the referral's version since the
    client read it, the create is refused with ERR_STALE_REFERRAL_VERSION so that
    the client does not act on a referral it has not observed."

    One study already created (referral version advanced); reusing the old version
    is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_referral_on_study_create
    """
    _, referral = create_authorized_referral(modality="HSAT", prior_auth_number="PA-OCC1")
    stale_version = referral["version"]
    get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], stale_version, modality="HSAT"),
            COORD,
        )
    )
    res = api.create_study_order(
        create_study_order_payload(referral["id"], stale_version, modality="HSAT"),
        COORD,
    )
    validate_error(res, "ERR_STALE_REFERRAL_VERSION")


# ─── OCC: stale study version on score after return (corner) ───────────────

def test_stale_study_version_on_rescore_after_return_rejected(api):
    """PRD 2.9: "Submitting scoring against a study requires
    expected_study_order_version to equal the study's current version; if a
    physician return bounced the study back to IN_PROGRESS and bumped its version,
    or another technologist already scored it, the submission is refused with
    ERR_STALE_STUDY_VERSION."

    Capture the pre-score version, score (bump), then a physician return (bump).
    Re-scoring with the pre-score version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_study_on_score_after_return
    """
    from test_helpers import create_in_progress_study
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    pre_score_version = study["version"]
    api.score_study(study["id"], score_study_payload(480, 120, pre_score_version), TECH)
    reports = get_success_data(api.list_scoring_reports_for_study(study["id"], PHYS))
    api.return_scoring_report(reports[0]["id"], PHYS)
    res = api.score_study(
        study["id"], score_study_payload(480, 120, pre_score_version), TECH
    )
    validate_error(res, "ERR_STALE_STUDY_VERSION")


# ─── Consistency: schedule bubble-up visible immediately (corner) ──────────

def test_schedule_bubble_up_visible_immediately(api):
    """PRD 3.5: "If at that moment the parent referral is still AUTHORIZED,
    scheduling also carries the referral forward to SCHEDULED — the first hop of
    the bubble-up cascade between a child study and its parent."
    PRD 2.5: "When the first study under an authorized referral is scheduled, the
    referral itself is carried forward from AUTHORIZED to SCHEDULED."

    Immediately after scheduling, GET on the referral shows SCHEDULED.

    Design: Corner/consistency_model/schedule_response_reflects_referral_bubble_up_immediately
    """
    _, referral, study, _ = create_scheduled_study(modality="HSAT")
    referral_after = get_success_data(api.get_referral(referral["id"], COORD))
    assert referral_after["status"] == "SCHEDULED"


# ─── Consistency: touching compliance windows allowed (corner) ─────────────

def test_compliance_window_touching_endpoints_allowed(api):
    """PRD 3.10: "A new window must not overlap any existing compliance window for
    the same device; windows are treated as half-open intervals where touching
    endpoints do not constitute an overlap, and a true overlap is rejected with
    ERR_COMPLIANCE_WINDOW_OVERLAP."

    Existing [2026-08-01, 2026-08-31); new [2026-08-31, 2026-09-30) starts exactly
    at the prior end -> touching, accepted (201).

    Design: Corner/consistency_model/compliance_window_touching_allowed
    """
    _, dme, _ = create_fulfilled_dme_with_window(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
        nights_used_4h_plus=21, total_usage_minutes=5040,
    )
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"], "2026-08-31T00:00:00Z", "2026-09-30T00:00:00Z",
            nights_used_4h_plus=25, total_usage_minutes=7500,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is True
