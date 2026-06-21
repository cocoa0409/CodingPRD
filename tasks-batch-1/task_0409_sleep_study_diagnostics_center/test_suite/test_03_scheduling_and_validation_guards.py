"""Study scheduling guards, cross-entity state gates, validation priority
ordering, bed/turnover overlap, and compliance-window overlap.

Covers difficulty queue (A) cross-entity-state-dependency,
priority-pair-validation-conflict, and resource-temporal-overlap instances, and
corner queue (B) validation instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_ordered_study,
    create_authorized_referral,
    create_scheduled_study,
    create_draft_dme,
    create_fulfilled_dme,
    create_fulfilled_dme_with_window,
    create_bed,
    create_submitted_dme,
    create_interpreted_study,
    create_study_order_payload,
    schedule_study_payload,
    create_compliance_record_payload,
    create_dme_order_payload,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]
TECH = TEST_USERS["sleep_technologist_headers"]
PHYS = TEST_USERS["physician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]

PROBE_UUID = "00000000-0000-0000-0000-000000000000"


# ─── Cross-entity: schedule requires referral AUTHORIZED ───────────────────

def test_schedule_requires_referral_authorized(api):
    """PRD 3.5: "The parent referral must be in AUTHORIZED status; if it is not,
    scheduling is refused with ERR_REFERRAL_NOT_AUTHORIZED."

    Referral still SUBMITTED (prior auth required, never approved); the lone study
    is ORDERED.

    Design: Difficulty/cross_entity_state_dependency/study_schedule_requires_referral_authorized
    """
    from test_helpers import create_submitted_referral
    bed = create_bed()
    _, referral = create_submitted_referral(modality="IN_LAB_PSG", prior_auth_required=True)
    study = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], referral["version"],
                                       modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study["id"],
        schedule_study_payload(bed_id=bed["id"]),
        COORD,
    )
    validate_error(res, "ERR_REFERRAL_NOT_AUTHORIZED")
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "ORDERED"


def test_schedule_leaves_study_ordered_when_referral_not_authorized(api):
    """PRD 3.5: "The parent referral must be in AUTHORIZED status; if it is not,
    scheduling is refused with ERR_REFERRAL_NOT_AUTHORIZED."
    PRD 3.4: "A newly created study begins in ORDERED status."

    The blocked schedule must not advance the study out of ORDERED.

    Design: Difficulty/cross_entity_state_dependency/study_schedule_requires_referral_authorized
    """
    from test_helpers import create_submitted_referral
    bed = create_bed()
    _, referral = create_submitted_referral(modality="IN_LAB_PSG", prior_auth_required=True)
    study = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], referral["version"],
                                       modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(study["id"], schedule_study_payload(bed_id=bed["id"]), COORD)
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "ORDERED"


# ─── Cross-entity: DME submit requires study INTERPRETED ───────────────────

def test_dme_submit_requires_study_interpreted(api):
    """PRD 3.9: "Submitting an order advances it from DRAFT to SUBMITTED, but only
    when the linked study is in INTERPRETED status — a submission against a study
    that is not interpreted is rejected with ERR_STUDY_NOT_INTERPRETED."

    Build a DRAFT DME against a study that is only SCORED (report still DRAFT).

    Design: Difficulty/cross_entity_state_dependency/dme_submit_requires_study_interpreted
    """
    from test_helpers import create_scored_study
    _, _, study, _, _ = create_scored_study(modality="HSAT")
    dme = get_success_data(
        api.create_dme_order(create_dme_order_payload(study["id"]), DME)
    )
    res = api.submit_dme_order(dme["id"], DME)
    validate_error(res, "ERR_STUDY_NOT_INTERPRETED")
    dme_after = get_success_data(api.get_dme_order(dme["id"], DME))
    assert dme_after["status"] == "DRAFT"


def test_dme_stays_draft_when_study_not_interpreted(api):
    """PRD 3.9: "a submission against a study that is not interpreted is rejected
    with ERR_STUDY_NOT_INTERPRETED."
    PRD 3.9: "A new DME order begins in DRAFT status."

    The blocked submit must leave the DME in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/dme_submit_requires_study_interpreted
    """
    from test_helpers import create_scored_study
    _, _, study, _, _ = create_scored_study(modality="HSAT")
    dme = get_success_data(
        api.create_dme_order(create_dme_order_payload(study["id"]), DME)
    )
    api.submit_dme_order(dme["id"], DME)
    dme_after = get_success_data(api.get_dme_order(dme["id"], DME))
    assert dme_after["status"] == "DRAFT"


# ─── Priority: forbidden role beats not-found ──────────────────────────────

def test_forbidden_role_beats_study_not_found(api):
    """PRD 2.7: "second, whether the declared role is permitted for the operation
    (ERR_FORBIDDEN_ROLE); third, the existence of every resource named by a path
    identifier or a foreign-key body field."

    A Physician (not a SleepTechnologist) calling start on a non-existent study
    fails the role check (403) before the existence check (404).

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_study_not_found
    """
    res = api.start_study(PROBE_UUID, PHYS)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_forbidden_role_returns_403_not_404(api):
    """PRD 2.7: "second, whether the declared role is permitted for the operation
    (ERR_FORBIDDEN_ROLE); third, the existence of every resource named by a path
    identifier or a foreign-key body field."

    The 403 status confirms role precedence over the not-found family.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_study_not_found
    """
    res = api.start_study(PROBE_UUID, PHYS)
    assert res.status_code == 403, f"Expected 403 (role before existence), got {res.status_code}"


# ─── Priority: auth-expired beats bed-double-booked ────────────────────────

def test_auth_expired_beats_bed_double_booked(api):
    """PRD 2.7: "the authorization-expiry check at scheduling (priority seven); the
    modality-and-bed coherence check (priority eight); the bed-collision and
    bed-availability check (priority nine)."
    PRD 3.5: "a night that starts after the authorization has expired is rejected
    with ERR_AUTH_EXPIRED."

    A schedule whose night both exceeds the auth expiry AND collides with an
    existing bed night returns ERR_AUTH_EXPIRED (priority 7 < 9).

    Design: Difficulty/priority_pair_validation_conflict/auth_expired_beats_bed_double_booked
    """
    bed = create_bed()
    # First study occupies the colliding interval.
    _, ref1 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-A")
    study1 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref1["id"], ref1["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(
        study1["id"],
        schedule_study_payload(night_start_utc="2026-07-10T22:00:00Z",
                               night_end_utc="2026-07-11T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    # Second study: auth expires 2026-07-05, scheduling for a colliding 2026-07-10 night.
    _, ref2 = create_authorized_referral(
        modality="IN_LAB_PSG", prior_auth_number="PA-B", prior_auth_expires_on="2026-07-05"
    )
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-10T22:00:00Z",
                               night_end_utc="2026-07-11T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    validate_error(res, "ERR_AUTH_EXPIRED")


def test_auth_expired_returns_409(api):
    """PRD 3.5: "when the referral carries a prior_auth_expires_on date, the date
    portion of night_start_utc must be on or before that expiry date, and a night
    that starts after the authorization has expired is rejected with
    ERR_AUTH_EXPIRED."

    Design: Difficulty/priority_pair_validation_conflict/auth_expired_beats_bed_double_booked
    """
    bed = create_bed()
    _, ref1 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-C")
    study1 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref1["id"], ref1["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(
        study1["id"],
        schedule_study_payload(night_start_utc="2026-07-10T22:00:00Z",
                               night_end_utc="2026-07-11T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    _, ref2 = create_authorized_referral(
        modality="IN_LAB_PSG", prior_auth_number="PA-D", prior_auth_expires_on="2026-07-05"
    )
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-10T22:00:00Z",
                               night_end_utc="2026-07-11T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    assert res.status_code == 409


# ─── Resource overlap: bed night + turnover buffer ─────────────────────────

def test_bed_night_overlap_includes_turnover_buffer(api):
    """PRD 3.5: "The collision test is not a naive interval overlap — it must also
    honor the bed's turnover_buffer_minutes, which is treated as a mandatory gap
    inserted after each existing booked night. In other words, the new night
    conflicts not only when it overlaps an existing night directly but also when it
    begins within the turnover buffer that trails an existing night."

    First night ends 06:00 with a 60-min buffer (blocked until 07:00); a second
    night starting 06:30 is rejected ERR_BED_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/bed_night_overlap_with_turnover_buffer
    """
    bed = create_bed(turnover_buffer_minutes=60)
    _, ref1 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-E")
    study1 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref1["id"], ref1["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(
        study1["id"],
        schedule_study_payload(night_start_utc="2026-07-20T22:00:00Z",
                               night_end_utc="2026-07-21T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    _, ref2 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-F")
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-21T06:30:00Z",
                               night_end_utc="2026-07-21T14:30:00Z", bed_id=bed["id"]),
        COORD,
    )
    validate_error(res, "ERR_BED_DOUBLE_BOOKED")
    study2_after = get_success_data(api.get_study_order(study2["id"], COORD))
    assert study2_after["status"] == "ORDERED"


def test_bed_night_within_buffer_leaves_second_study_ordered(api):
    """PRD 3.5: "the new night conflicts not only when it overlaps an existing
    night directly but also when it begins within the turnover buffer that trails
    an existing night. A collision under this rule is rejected with
    ERR_BED_DOUBLE_BOOKED."

    The rejected schedule must leave the second study in ORDERED.

    Design: Difficulty/resource_temporal_overlap/bed_night_overlap_with_turnover_buffer
    """
    bed = create_bed(turnover_buffer_minutes=60)
    _, ref1 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-G")
    study1 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref1["id"], ref1["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(
        study1["id"],
        schedule_study_payload(night_start_utc="2026-07-20T22:00:00Z",
                               night_end_utc="2026-07-21T06:00:00Z", bed_id=bed["id"]),
        COORD,
    )
    _, ref2 = create_authorized_referral(modality="IN_LAB_PSG", prior_auth_number="PA-H")
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(ref2["id"], ref2["version"], modality="IN_LAB_PSG"),
            COORD,
        )
    )
    api.schedule_study(
        study2["id"],
        schedule_study_payload(night_start_utc="2026-07-21T06:30:00Z",
                               night_end_utc="2026-07-21T14:30:00Z", bed_id=bed["id"]),
        COORD,
    )
    study2_after = get_success_data(api.get_study_order(study2["id"], COORD))
    assert study2_after["status"] == "ORDERED"


# ─── Resource overlap: compliance window half-open ─────────────────────────

def test_compliance_window_overlap_rejected(api):
    """PRD 3.10: "A new window must not overlap any existing compliance window for
    the same device; windows are treated as half-open intervals where touching
    endpoints do not constitute an overlap, and a true overlap is rejected with
    ERR_COMPLIANCE_WINDOW_OVERLAP."

    Existing [2026-08-01, 2026-08-31); new [2026-08-15, 2026-09-14) straddles it.

    Design: Difficulty/resource_temporal_overlap/compliance_window_half_open_overlap
    """
    _, dme, _ = create_fulfilled_dme_with_window(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
        nights_used_4h_plus=25, total_usage_minutes=7500,
    )
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"], "2026-08-15T00:00:00Z", "2026-09-14T00:00:00Z",
            nights_used_4h_plus=22, total_usage_minutes=6000,
        ),
        DME,
    )
    validate_error(res, "ERR_COMPLIANCE_WINDOW_OVERLAP")


def test_compliance_window_straddling_overlap_returns_409(api):
    """PRD 3.10: "A new window must not overlap any existing compliance window for
    the same device; windows are treated as half-open intervals where touching
    endpoints do not constitute an overlap, and a true overlap is rejected with
    ERR_COMPLIANCE_WINDOW_OVERLAP."

    A straddling (not merely touching) window is a true overlap (409).

    Design: Difficulty/resource_temporal_overlap/compliance_window_half_open_overlap
    """
    _, dme, _ = create_fulfilled_dme_with_window(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
        nights_used_4h_plus=25, total_usage_minutes=7500,
    )
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"], "2026-08-15T00:00:00Z", "2026-09-14T00:00:00Z",
            nights_used_4h_plus=22, total_usage_minutes=6000,
        ),
        DME,
    )
    assert res.status_code == 409


# ─── Corner: HSAT scheduled with a bed ─────────────────────────────────────

def test_schedule_hsat_with_bed_rejected(api):
    """PRD 3.5: "A home test requires the opposite: an HSAT study must be scheduled
    with no bed_id at all, and supplying one is rejected with
    ERR_HSAT_BED_NOT_ALLOWED."

    Design: Corner/validations/schedule_hsat_with_bed_rejected
    """
    bed = create_bed()
    _, _, study = create_ordered_study(modality="HSAT")
    res = api.schedule_study(
        study["id"], schedule_study_payload(bed_id=bed["id"]), COORD
    )
    validate_error(res, "ERR_HSAT_BED_NOT_ALLOWED")


# ─── Corner: in-lab scheduled without a bed ────────────────────────────────

def test_schedule_in_lab_without_bed_rejected(api):
    """PRD 3.5: "An in-lab study — whether IN_LAB_PSG or IN_LAB_TITRATION —
    requires a bed_id; scheduling such a study without one is rejected with
    ERR_BED_REQUIRED."

    Design: Corner/validations/schedule_in_lab_without_bed_rejected
    """
    _, _, study = create_ordered_study(modality="IN_LAB_PSG")
    res = api.schedule_study(study["id"], schedule_study_payload(), COORD)
    validate_error(res, "ERR_BED_REQUIRED")


# ─── Corner: out-of-service bed ────────────────────────────────────────────

def test_schedule_out_of_service_bed_rejected(api):
    """PRD 3.5: "For an in-lab study the named bed must be bookable: a bed in
    OUT_OF_SERVICE status is rejected with ERR_BED_OUT_OF_SERVICE."

    Design: Corner/validations/schedule_out_of_service_bed_rejected
    """
    bed = create_bed()
    api.set_bed_out_of_service(bed["id"], COORD)
    _, _, study = create_ordered_study(modality="IN_LAB_PSG")
    res = api.schedule_study(
        study["id"], schedule_study_payload(bed_id=bed["id"]), COORD
    )
    validate_error(res, "ERR_BED_OUT_OF_SERVICE")


# ─── Corner: invalid night window ──────────────────────────────────────────

def test_schedule_invalid_night_window_rejected(api):
    """PRD 3.5: "The night window itself must be well-formed, meaning
    night_end_utc must be strictly later than night_start_utc; otherwise the
    request is rejected with ERR_INVALID_NIGHT_WINDOW."

    Design: Corner/validations/schedule_invalid_night_window
    """
    _, _, study = create_ordered_study(modality="HSAT")
    res = api.schedule_study(
        study["id"],
        schedule_study_payload(night_start_utc="2026-07-02T06:00:00Z",
                               night_end_utc="2026-07-01T22:00:00Z"),
        COORD,
    )
    validate_error(res, "ERR_INVALID_NIGHT_WINDOW")


# ─── Corner: DME submit without CPAP recommendation ────────────────────────

def test_dme_submit_without_cpap_recommendation_rejected(api):
    """PRD 3.9: "and only when that study's FINALIZED scoring report carries
    physician_recommends_cpap equal to true; a submission for a study whose
    interpretation did not recommend CPAP is rejected with ERR_CPAP_NOT_RECOMMENDED."

    Design: Corner/validations/dme_submit_without_cpap_recommendation
    """
    study, _, dme = create_draft_dme(modality="HSAT", physician_recommends_cpap=False)
    res = api.submit_dme_order(dme["id"], DME)
    validate_error(res, "ERR_CPAP_NOT_RECOMMENDED")


# ─── Corner: resupply predecessor not fulfilled ────────────────────────────

def test_resupply_predecessor_not_fulfilled_rejected(api):
    """PRD 3.9: "Resupply integrity is enforced: the predecessor named by
    supersedes_dme_order_id must itself be in FULFILLED status and must share the
    same study_order_id as the new order; a predecessor that is not fulfilled, or
    that belongs to a different study, is rejected with
    ERR_RESUPPLY_PREDECESSOR_INVALID."

    Predecessor is only SUBMITTED (not FULFILLED).

    Design: Corner/validations/resupply_predecessor_not_fulfilled
    """
    study, _, dme1 = create_submitted_dme(modality="HSAT")
    res = api.create_dme_order(
        create_dme_order_payload(
            study["id"],
            supersedes_dme_order_id=dme1["id"],
            expected_supersedes_version=dme1["version"],
        ),
        DME,
    )
    validate_error(res, "ERR_RESUPPLY_PREDECESSOR_INVALID")


# ─── Corner: cancel a FULFILLED (terminal) DME ─────────────────────────────

def test_cancel_fulfilled_dme_not_cancellable(api):
    """PRD 3.9: "An order may be cancelled while it is in DRAFT or SUBMITTED; a
    cancel attempted from any other state is rejected with ERR_DME_NOT_CANCELLABLE,
    and a successful cancel moves the order to CANCELLED."

    FULFILLED is outside {DRAFT, SUBMITTED}.

    Design: Corner/state_machines/dme_cancel_from_fulfilled_not_cancellable
    """
    _, _, dme = create_fulfilled_dme(modality="HSAT")
    res = api.cancel_dme_order(dme["id"], DME)
    validate_error(res, "ERR_DME_NOT_CANCELLABLE")


# ─── Corner: compliance on unfulfilled DME ─────────────────────────────────

def test_compliance_on_unfulfilled_dme_rejected(api):
    """PRD 3.10: "After a device has been fulfilled, the DMECoordinator files
    compliance downloads that report how the patient is actually using the
    equipment."
    PRD 2.7: "fifth, whether the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE and its specific siblings)."

    A SUBMITTED (not FULFILLED) device cannot receive a compliance record.

    Design: Corner/validations/compliance_on_unfulfilled_dme_rejected
    """
    study, _, dme = create_submitted_dme(modality="HSAT")
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"], "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
            nights_used_4h_plus=21, total_usage_minutes=5040,
        ),
        DME,
    )
    validate_error(res, "ERR_INVALID_STATE")
