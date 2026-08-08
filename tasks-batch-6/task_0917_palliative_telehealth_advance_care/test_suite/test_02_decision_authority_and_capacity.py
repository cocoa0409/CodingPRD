"""Who may lawfully decide: surrogate designations, capacity and consent."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_conference,
    assert_instant_equals_offset,
    assert_surrogate,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    BILLING,
    PHYSICIAN,
    SOCIAL_WORKER,
    active_care_plan,
    attest_conference,
    book_conference,
    caregiver_headers_for,
    designate_surrogate,
    determine_capacity,
    draft_code_status_order,
    effective_code_status_order,
    enroll_patient,
    hold_conference,
    read_patient,
    set_clock,
)


# ---------------------------------------------------------------------------
# The empty candidate pool
# ---------------------------------------------------------------------------
def test_family_hold_with_only_a_proposed_surrogate_finds_an_empty_hierarchy(api):
    """PRD 2.5: "**Empty surrogate hierarchy.** A `FAMILY` conference held while
    the patient's `capacity_status` is `LACKS_CAPACITY` and no `decision_maker_id`
    was supplied requires at least one surrogate designation for this patient with
    `status` `ACTIVE`. Otherwise `ERR_SURROGATE_HIERARCHY_EMPTY` (422)."
    PRD 3.2: "It considers only designations for this patient whose `status` is
    exactly `ACTIVE`; rows sitting in `PROPOSED` or `REVOKED` never enter the
    candidate set."

    Design: Difficulty/boundary_precision_check/family_conference_hold_with_empty_active_surrogate_pool
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Liam Petrov")
    designation = designate_surrogate(
        patient["id"],
        person_user_id="u_spouse_1",
        person_name="Mara Petrov",
        relationship="SPOUSE",
        is_beneficiary=False,
    )
    assert_surrogate(designation)
    assert designation["status"] == "PROPOSED", "a new designation opens in PROPOSED"

    determine_capacity(patient["id"], "LACKS_CAPACITY", "delirium, unable to state preferences")
    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        scheduled_start="2026-06-03T14:00:00Z",
        scheduled_end="2026-06-03T15:00:00Z",
    )

    rejected = api.hold_conference(
        conference["id"], {"documented_minutes": 40}, SOCIAL_WORKER
    )
    validate_error(rejected, ApiErrorId.ERR_SURROGATE_HIERARCHY_EMPTY.value, 422)

    unchanged = validate_success(api.get_conference(conference["id"], SOCIAL_WORKER))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["consent_recorded"] is False


def test_activating_the_designation_lets_the_identical_family_hold_succeed(api):
    """PRD 3.2: "`PROPOSED → ACTIVE` puts the designation into the authority
    candidate pool."
    PRD 3.7: "On success the conference moves to `HELD`, `consent_recorded`
    becomes true and `decision_maker_kind` is stamped `PATIENT` when the patient
    consented personally and `SURROGATE` when a designation did."

    Design: Difficulty/boundary_precision_check/family_conference_hold_with_empty_active_surrogate_pool
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Liam Petrov")
    designation = designate_surrogate(
        patient["id"],
        person_user_id="u_spouse_1",
        person_name="Mara Petrov",
        relationship="SPOUSE",
    )
    determine_capacity(patient["id"], "LACKS_CAPACITY")
    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        scheduled_start="2026-06-03T14:00:00Z",
        scheduled_end="2026-06-03T15:00:00Z",
    )

    validate_error(
        api.hold_conference(conference["id"], {"documented_minutes": 40}, SOCIAL_WORKER),
        ApiErrorId.ERR_SURROGATE_HIERARCHY_EMPTY.value,
        422,
    )

    activated = validate_success(
        api.set_surrogate_status(designation["id"], {"target_status": "ACTIVE"}, SOCIAL_WORKER)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["hierarchy_rank"] == 2, "SPOUSE derives hierarchy_rank 2"

    held = validate_success(
        api.hold_conference(conference["id"], {"documented_minutes": 40}, SOCIAL_WORKER)
    )
    assert_conference(held)
    assert held["status"] == "HELD"
    assert held["decision_maker_kind"] == "SURROGATE"
    assert held["consent_recorded"] is True
    assert held["documented_minutes"] == 40


# ---------------------------------------------------------------------------
# The authority selector picks the top-ranked candidate
# ---------------------------------------------------------------------------
def test_naming_a_lower_ranked_surrogate_is_not_an_authorized_decision_maker(api):
    """PRD 2.5: "When `decision_maker_id` **is** supplied, it must name the
    highest-ranked `ACTIVE` surrogate designation for this patient as resolved by
    the authority selector of section 3.2, and the patient's `capacity_status`
    must be `LACKS_CAPACITY`. Supplying a `decision_maker_id` while the patient
    has capacity, or naming any surrogate other than the top-ranked one, is
    rejected with `ERR_NOT_AUTHORIZED_DECISION_MAKER` (422)."
    PRD 3.2: "Candidates are ordered by `hierarchy_rank` ascending — a lower rank
    outranks a higher one — and ties between two candidates of equal rank are
    broken by `created_at` ascending, the earlier designation winning."

    Design: Corner/validations/decision_maker_that_is_not_top_ranked_returns_not_authorized
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Kaya Lindberg")

    sibling = designate_surrogate(
        patient["id"],
        person_user_id="u_sibling_1",
        person_name="Nils Lindberg",
        relationship="SIBLING",
        activate=True,
    )
    agent = designate_surrogate(
        patient["id"],
        person_user_id="u_agent_1",
        person_name="Ove Lindberg",
        relationship="HEALTHCARE_AGENT",
        activate=True,
    )
    assert sibling["hierarchy_rank"] == 5
    assert agent["hierarchy_rank"] == 1

    determine_capacity(patient["id"], "LACKS_CAPACITY", "no longer able to state preferences")
    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        scheduled_start="2026-06-03T14:00:00Z",
        scheduled_end="2026-06-03T15:00:00Z",
    )

    rejected = api.hold_conference(
        conference["id"],
        {"documented_minutes": 40, "decision_maker_id": sibling["id"]},
        SOCIAL_WORKER,
    )
    validate_error(rejected, ApiErrorId.ERR_NOT_AUTHORIZED_DECISION_MAKER.value, 422)

    held = validate_success(
        api.hold_conference(
            conference["id"],
            {"documented_minutes": 40, "decision_maker_id": agent["id"]},
            SOCIAL_WORKER,
        )
    )
    assert held["status"] == "HELD"
    assert held["decision_maker_id"] == agent["id"]
    assert held["decision_maker_kind"] == "SURROGATE"


# ---------------------------------------------------------------------------
# The capacity cascade
# ---------------------------------------------------------------------------
def test_restoring_capacity_invalidates_consent_and_unwinds_the_surrogate_order(api):
    """PRD 3.2: "Because a change of capacity can change who may lawfully consent,
    the determination propagates: any `FAMILY` conference for this patient that
    recorded consent and sits in `HELD` or `ATTESTED`, whose recorded
    `decision_maker_kind` no longer matches the lawful decision maker under the
    new capacity, moves to `CONSENT_INVALIDATED` with `consent_recorded` set
    false; because that consent is gone, every `EFFECTIVE` code-status order for
    the patient with `surrogate_stated` true moves to `SUPERSEDED` and the
    patient's `code_status` reverts to the most recently executed directive's
    `stated_code_status` (or to `FULL_CODE` when the patient has none); and
    because `code_status` moved, every code-status order still in `DRAFT` or
    `ATTESTED` is parked in `CONFLICT_HOLD`."
    PRD 3.2: "Alongside that chain, any claim resting on an invalidated conference
    and sitting in `DRAFT` or `ATTESTED` drops back to `DRAFT` with
    `documentation_attested` false and `attested_by_user_id` cleared."

    Design: Corner/state_machines/capacity_determination_invalidates_family_consent_and_surrogate_stated_order
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Noor Rahimi")
    surrogate = designate_surrogate(
        patient["id"],
        person_user_id="u_spouse_1",
        person_name="Sam Rahimi",
        relationship="SPOUSE",
        activate=True,
    )
    determine_capacity(patient["id"], "LACKS_CAPACITY", "advanced encephalopathy")

    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")
    hold_conference(
        conference["id"],
        documented_minutes=46,
        disciplines_present=["PHYSICIAN", "SOCIAL_WORKER"],
        decision_maker_id=surrogate["id"],
    )
    attest_conference(conference["id"], "PHYSICIAN", "family meeting documented")
    attested_conference = attest_conference(
        conference["id"], "SOCIAL_WORKER", "surrogate consent documented"
    )
    assert attested_conference["status"] == "ATTESTED"

    effective_order = effective_code_status_order(
        patient["id"], "DNR", surrogate_stated=True
    )
    assert effective_order["status"] == "EFFECTIVE"
    assert read_patient(patient["id"])["code_status"] == "DNR"

    draft_order = draft_code_status_order(patient["id"], "DNR_DNI")

    claim = validate_success(
        api.create_claim(
            f.claim_payload(
                patient["id"],
                service_date="2026-06-02T09:30:00Z",
                documented_minutes=46,
                modality="TELEHEALTH",
                conference_id=conference["id"],
            ),
            BILLING,
        ),
        201,
    )
    attested_claim = validate_success(
        api.attest_claim(
            claim["id"], {"attestation_statement": "conference documentation complete"}, BILLING
        )
    )
    assert attested_claim["status"] == "ATTESTED"

    restored = validate_success(
        api.create_capacity_determination(
            patient["id"],
            {
                "capacity_status": "HAS_CAPACITY",
                "determination_note": "encephalopathy resolved, patient can state preferences",
            },
            PHYSICIAN,
        )
    )

    assert restored["capacity_status"] == "HAS_CAPACITY"
    assert restored["code_status"] == "FULL_CODE"
    assert restored["code_status_rank"] == 1

    after_conference = validate_success(api.get_conference(conference["id"], SOCIAL_WORKER))
    assert after_conference["status"] == "CONSENT_INVALIDATED"
    assert after_conference["consent_recorded"] is False

    after_effective = validate_success(
        api.get_code_status_order(effective_order["id"], PHYSICIAN)
    )
    assert after_effective["status"] == "SUPERSEDED"

    after_draft = validate_success(api.get_code_status_order(draft_order["id"], PHYSICIAN))
    assert after_draft["status"] == "CONFLICT_HOLD"

    after_claim = validate_success(api.get_claim(claim["id"], BILLING))
    assert after_claim["status"] == "DRAFT"
    assert after_claim["documentation_attested"] is False


# ---------------------------------------------------------------------------
# The Caregiver role acts as a surrogate designation row
# ---------------------------------------------------------------------------
def test_caregiver_files_a_proxy_symptom_report_using_the_designation_id(api):
    """PRD 2.1: "When `X-User-Role` is `Caregiver`, `X-User-ID` is the `id` of the
    acting `SurrogateDesignation` row; a resource that references a surrogate
    designation does so through `decision_maker_id`, and an ownership check on
    such a resource would compare `decision_maker_id` to `X-User-ID`."
    PRD 3.5: "Under the `PROXY` variant the subjective sum is first discounted to
    six tenths of its value — a weight of 0.6 — added to the undiscounted
    objective sum, and the total scaled by two and a half, a multiplier of 2.5."

    Design: Corner/rbac/caregiver_files_a_proxy_symptom_assessment_as_an_entity_backed_role
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Xu Liang")
    designation = designate_surrogate(
        patient["id"],
        person_user_id="u_daughter_1",
        person_name="Mei Liang",
        relationship="ADULT_CHILD",
        activate=True,
    )
    assert designation["hierarchy_rank"] == 3
    plan = active_care_plan(patient["id"], problem_list=["dyspnea"])

    response = api.create_symptom_assessment(
        f.symptom_assessment_payload(
            patient["id"],
            plan["id"],
            reporter_type="PROXY",
            item_pain=8,
            item_dyspnea=8,
            item_nausea=8,
            item_anxiety=4,
            item_fatigue=4,
        ),
        caregiver_headers_for(designation),
    )
    assessment = validate_success(response, 201)

    assert assessment["reporter_type"] == "PROXY"
    assert assessment["distress_score"] == 72, (
        "objective 24 plus subjective 8*0.6 = 4.8, times 2.5, is 72, "
        f"got {assessment['distress_score']}"
    )
    assert assessment["severity_tier"] == "SEVERE"
    assert_instant_equals_offset(
        assessment["response_due_at"],
        assessment["created_at"],
        minutes=30,
        label="SymptomAssessment.response_due_at",
    )
