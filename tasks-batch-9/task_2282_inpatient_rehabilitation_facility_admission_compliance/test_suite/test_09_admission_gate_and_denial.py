"""Opening an admission, crossing the 48-hour gate, and denial."""

from test_helpers import (
    ApiErrorId,
    admit_admission_payload,
    api_client,
    assert_admission,
    assert_admission_dimensions,
    create_admission_payload,
    create_concurred_screening,
    create_draft_screening,
    deny_admission_payload,
    open_admission,
    read_admission,
    register_patient,
    set_clock,
    setup_facility_with_staff,
    setup_stay,
    validate_error,
    validate_success,
)


def test_admission_takes_its_facility_from_the_patient_and_starts_pending():
    """A freshly opened admission is unpriced, undocumented and unevaluated.

    PRD §3.3: "The new record copies `facility_id` from the patient's own
    facility and never changes it thereafter, and it starts with all three of its
    independent status dimensions at their initial values: `stay_status` is
    `PENDING`, `payment_status` is `NOT_PRICED`, `documentation_status` is
    `INCOMPLETE`, and `compliance_class` is `PENDING_EVALUATION`."

    Design: Corner/entities/admission_copies_facility_id_from_patient_at_creation
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_concurred_screening(env, patient["id"])

    response = api_client.create_admission(
        create_admission_payload(patient["id"], screening["id"]),
        env["nurse_headers"],
    )

    admission = validate_success(response, expected_status=201)
    assert_admission(admission)
    assert admission["facility_id"] == env["facility_id"]
    assert_admission_dimensions(admission, stay_status="PENDING",
                                payment_status="NOT_PRICED",
                                documentation_status="INCOMPLETE",
                                compliance_class="PENDING_EVALUATION")
    assert admission["admitted_at"] is None
    assert admission["screening_window_hours"] is None


def test_denying_a_pending_admission_stores_the_reason_and_excludes_the_stay():
    """The physician turns the patient away and the stay leaves every cohort.

    PRD §3.3: "Denial moves `stay_status` from `PENDING` to `ADMISSION_DENIED`,
    stores the reason, and sets `compliance_class` to `EXCLUDED` — a denied stay
    never enters any compliance cohort."

    Design: Corner/state_machines/admission_deny_stores_reason_and_marks_excluded
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_concurred_screening(env, patient["id"])
    admission = open_admission(env, patient["id"], screening["id"])

    response = api_client.deny_admission(
        admission["id"],
        deny_admission_payload(denial_reason="Acute care remains appropriate"),
        env["physician_headers"],
    )

    denied = validate_success(response, expected_status=200)
    assert denied["stay_status"] == "ADMISSION_DENIED"
    assert denied["denial_reason"] == "Acute care remains appropriate"
    assert denied["compliance_class"] == "EXCLUDED"
    assert denied["admitted_at"] is None


def test_admitting_a_denied_admission_is_refused():
    """ADMISSION_DENIED is terminal, so the admit transition has nowhere to start.

    PRD §3.3: "`stay_status` runs `PENDING` → `ADMITTED` → `DISCHARGED`, with
    `ADMISSION_DENIED` as the alternative terminal from `PENDING`."

    PRD §2.5: "the target resource must currently be in a state from which the
    requested transition is declared, else `ERR_INVALID_STATE` (409), on every
    transition endpoint"

    Design: Corner/state_machines/admission_admit_after_denial_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_concurred_screening(env, patient["id"])
    admission = open_admission(env, patient["id"], screening["id"])
    validate_success(api_client.deny_admission(admission["id"],
                                               deny_admission_payload(),
                                               env["physician_headers"]))
    set_clock("2026-08-04T12:00:00Z")

    response = api_client.admit_admission(
        admission["id"], admit_admission_payload("2026-08-04T12:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    unchanged = read_admission(admission["id"])
    assert unchanged["stay_status"] == "ADMISSION_DENIED"
    assert unchanged["admitted_at"] is None


def test_admission_opened_on_a_draft_screening_is_refused():
    """The authorising screening has never been through physician review.

    PRD §3.3: "The screening must belong to the same patient as the admission,
    and it must already be `PHYSICIAN_CONCURRED` with a `reviewed_at` no later
    than the eventual admission instant — a screening in any other state is
    `ERR_SCREENING_NOT_CONCURRED`."

    Design: Corner/validations/admission_on_draft_screening_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_draft_screening(env, patient["id"])

    response = api_client.create_admission(
        create_admission_payload(patient["id"], screening["id"]),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_NOT_CONCURRED)


def test_admitting_forty_nine_hours_after_the_screening_is_refused():
    """One hour past the 48-hour window the gate closes on the patient.

    PRD §3.3: "The elapsed time from the screening's `conducted_at` to
    `admitted_at` must be at most 48 hours, or the attempt fails with
    `ERR_SCREENING_WINDOW_EXPIRED`."

    Design: Corner/validations/admit_forty_nine_hours_after_screening_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    screening = create_concurred_screening(
        env, patient["id"], expected_admission_at="2026-08-05T09:00:00Z"
    )
    admission = open_admission(env, patient["id"], screening["id"])
    assert screening["conducted_at"].startswith("2026-08-03T08:00:00")
    set_clock("2026-08-05T09:00:00Z")

    response = api_client.admit_admission(
        admission["id"], admit_admission_payload("2026-08-05T09:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_WINDOW_EXPIRED)
    unchanged = read_admission(admission["id"])
    assert unchanged["stay_status"] == "PENDING"
    assert unchanged["screening_window_hours"] is None


def test_admission_read_exposes_the_derived_screening_window_and_tier():
    """Screened 08-03T08:00Z and admitted 08-04T12:00Z is 28.00 hours of window.

    PRD §3.3: "`screening_window_hours` is the number of hours between the
    screening's `conducted_at` and `admitted_at`, held to two decimals; it too is
    null while the stay is `PENDING`."

    PRD §3.3: "code `0008` maps to `TIER_B`, code `0110` to `TIER_C`, codes `0704`
    and `1101` to `TIER_A`, and any other impairment group code falls back to
    `TIER_A`."

    Design: Corner/endpoints/admission_get_exposes_computed_screening_window_hours
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env, with_plan=False)

    response = api_client.get_admission(stay["admission"]["id"],
                                        env["nurse_headers"])

    admission = validate_success(response)
    assert float(admission["screening_window_hours"]) == 28.00
    assert admission["admitted_at"].startswith("2026-08-04T12:00:00")
    assert admission["cmg_tier"] == "TIER_B"
    assert admission["screening_compliant"] is True
    assert float(admission["qrp_penalty_pct_snapshot"]) == 0.00


def test_him_coder_may_read_an_admission_they_did_not_write():
    """The coder never touches the admission workflow but can still read it.

    PRD §2.1: "All read endpoints are available to all five roles."

    Design: Corner/rbac/him_coder_can_read_shared_admission_get
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "coder"))
    stay = setup_stay(env, with_plan=False)

    response = api_client.get_admission(stay["admission"]["id"],
                                        env["coder_headers"])

    admission = validate_success(response)
    assert admission["id"] == stay["admission"]["id"]
    assert admission["stay_status"] == "ADMITTED"
