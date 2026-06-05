"""Corner: business validations + calculation boundaries (PRD §3.4-§3.8).
Queue B 'calculations' and 'validations' sections.
"""
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import (
    BILLING,
    INTAKE,
    SCHEDULER,
    create_oasis,
    file_mileage_claim,
    schedule_confirm_complete,
    schedule_visit,
    setup_active_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}
MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


# --- calculations section ---
def test_mileage_overclaim_rejected_boundary(api):
    """PRD §3.6: "the claimed distance does not exceed the computed distance
    inflated by the overclaim tolerance of 1.10 — that is, claimed_miles must be
    at most computed_miles multiplied by 1.10. A claim that exceeds this ceiling
    is rejected with ERR_MILEAGE_OVERCLAIM (HTTP 422)."

    Design: Corner/calculations/mileage_overclaim_rejected_boundary
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=27.0)
    resp = api.approve_mileage_claim(claim["id"], BILLING)
    validate_error(resp, "ERR_MILEAGE_OVERCLAIM", 422)
    fetched = validate_success(api.get_visit(visit["id"], SCHEDULER))
    assert fetched["status"] == "COMPLETED"


def test_mileage_reject_sets_reimbursement_zero(api):
    """PRD §3.6: "Rejecting a claim drives PENDING -> REJECTED, which is permitted
    only from PENDING, sets the claim's reimbursement to zero, and bumps the claim
    version."

    Design: Corner/calculations/mileage_reject_sets_reimbursement_zero
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=20.0)
    rejected = validate_success(api.reject_mileage_claim(claim["id"], BILLING))
    assert rejected["status"] == "REJECTED"
    assert rejected["reimbursement"] == 0


def test_weekly_cap_exceeded_on_confirm(api):
    """PRD §3.4: "A clinician may hold at most weekly_visit_cap visits in
    CONFIRMED or COMPLETED status within any single ISO week ... rejects the
    operation when adding one more would carry the count above the cap; the
    rejection is ERR_WEEKLY_CAP_EXCEEDED (HTTP 422). This same capacity rule is
    evaluated both when a visit is scheduled and when a clinician confirms one."

    Design: Corner/calculations/weekly_cap_exceeded_on_confirm
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        rn_overrides={"full_name": "RN Cap", "discipline": "RN", "weekly_visit_cap": 1},
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v1 = schedule_visit(ep_id, rn_id, api,
                        scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    v2 = schedule_visit(ep_id, rn_id, api,
                        scheduled_start="2026-02-04T09:00:00Z", scheduled_end="2026-02-04T10:00:00Z")
    validate_success(api.confirm_visit(v1["id"], make_clinician_headers(rn_id)))
    resp = api.confirm_visit(v2["id"], make_clinician_headers(rn_id))
    validate_error(resp, "ERR_WEEKLY_CAP_EXCEEDED", 422)
    fetched = validate_success(api.get_visit(v2["id"], SCHEDULER))
    assert fetched["status"] == "SCHEDULED"


# --- validations section ---
def test_visit_out_of_cert_window_rejected(api):
    """PRD §3.4: "both ends must fall within the episode's cert_start through
    cert_end window inclusive; otherwise the schedule fails with
    ERR_VISIT_OUT_OF_CERT_WINDOW (HTTP 422)."

    Design: Corner/validations/visit_out_of_cert_window_rejected
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    resp = api.create_visit(ep_id, {
        "clinician_id": rn_id, "discipline": "RN",
        "scheduled_start": "2026-05-01T09:00:00Z", "scheduled_end": "2026-05-01T10:00:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_VISIT_OUT_OF_CERT_WINDOW", 422)


def test_license_inactive_blocks_confirm(api):
    """PRD §3.4: "Confirmation requires that the acting clinician be the visit's
    assigned clinician_id, that the parent episode be ACTIVE, and that the
    clinician's license_active be true. An inactive license is rejected with
    ERR_LICENSE_INACTIVE (HTTP 422)".

    Design: Corner/validations/license_inactive_blocks_confirm
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v = schedule_visit(ep_id, rn_id, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    validate_success(api.update_clinician(rn_id, {"license_active": False}, SCHEDULER))
    resp = api.confirm_visit(v["id"], make_clinician_headers(rn_id))
    validate_error(resp, "ERR_LICENSE_INACTIVE", 422)


def test_companion_shift_requires_hha_discipline(api):
    """PRD §3.5: "The referenced clinician's discipline must be HHA, or the
    booking is rejected with ERR_DISCIPLINE_MISMATCH (HTTP 422)".

    Design: Corner/validations/companion_shift_requires_hha_discipline
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 4},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    resp = api.create_companion_shift(ep_id, {
        "clinician_id": rn_id,
        "shift_start": "2026-02-03T13:00:00Z", "shift_end": "2026-02-03T14:00:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_DISCIPLINE_MISMATCH", 422)


def test_oasis_invalid_wrong_type_on_episode_create(api):
    """PRD §3.2: "The seeding assessment must be of type START_OF_CARE, must
    belong to the same patient, and must not already be locked; otherwise the
    create fails with ERR_OASIS_INVALID (HTTP 422)."

    Design: Corner/validations/oasis_invalid_wrong_type_on_episode_create
    """
    from test_helpers.factories import clinician_payload, patient_payload
    set_clock("2026-02-01T08:00:00Z", api)
    validate_success(api.create_rate_config(WOUND_RATE | {"active": True}, BILLING), 201)
    clinician = validate_success(api.create_clinician(clinician_payload(), SCHEDULER), 201)
    patient = validate_success(api.create_patient(patient_payload(), INTAKE), 201)
    recert_oasis = validate_success(api.create_oasis({
        "patient_id": patient["id"], "clinician_id": clinician["id"],
        "assessment_type": "RECERTIFICATION", "assessment_date": "2026-02-01T08:00:00Z",
        "clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2,
    }, INTAKE), 201)
    resp = api.create_episode({"patient_id": patient["id"], "soc_oasis_id": recert_oasis["id"]}, INTAKE)
    validate_error(resp, "ERR_OASIS_INVALID", 422)


def test_finalize_with_open_visit_not_settleable(api):
    """PRD §3.8: "Finalize is permitted only when every visit on the episode is in
    a terminal state — none may remain SCHEDULED or CONFIRMED — and the episode
    holds no SUBMITTED recertification request; otherwise it is rejected with
    ERR_EPISODE_NOT_SETTLEABLE (HTTP 409)."

    Design: Corner/validations/finalize_with_open_visit_not_settleable
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v = schedule_visit(ep_id, rn_id, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    validate_success(api.confirm_visit(v["id"], make_clinician_headers(rn_id)))
    resp = api.finalize_episode(ep_id, BILLING)
    validate_error(resp, "ERR_EPISODE_NOT_SETTLEABLE", 409)


def test_max_recert_revisions_exceeded(api):
    """PRD §3.7: "The revision loop is bounded — at most three revisions are
    allowed, so a resubmission attempted when revision_count already equals 3 is
    rejected with ERR_MAX_REVISIONS_EXCEEDED (HTTP 422)."

    Design: Corner/validations/max_recert_revisions_exceeded
    """
    from test_helpers.fixtures import COMPLIANCE
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id = base["episode"]["id"]
    recert_oasis = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="RECERTIFICATION", assessment_date="2026-03-25T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    set_clock("2026-03-25T08:00:00Z", api)
    rr = validate_success(api.create_recert_request(ep_id, {"recert_oasis_id": recert_oasis["id"]}, INTAKE), 201)
    # Drive revision_count to 3 via three return/resubmit cycles (0->1->2->3),
    # each resubmit allowed because revision_count is below MAX at the time.
    for _ in range(3):
        validate_success(api.return_recert_request(rr["id"], {"review_note": "fix"}, COMPLIANCE))
        validate_success(api.resubmit_recert_request(rr["id"], INTAKE))
    # revision_count is now 3 (== MAX). One more return, then the resubmit is
    # rejected because revision_count already equals 3.
    validate_success(api.return_recert_request(rr["id"], {"review_note": "fix"}, COMPLIANCE))
    resp = api.resubmit_recert_request(rr["id"], INTAKE)
    validate_error(resp, "ERR_MAX_REVISIONS_EXCEEDED", 422)
