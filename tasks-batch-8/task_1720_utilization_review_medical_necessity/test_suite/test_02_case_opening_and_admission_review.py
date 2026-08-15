"""Case opening, computed intake fields, the audit trail's append-only shape,
and the admission medical-necessity review (PRD §2.6, §2.8, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_admission_review,
    assert_audit_event,
    assert_utilization_case,
    create_admission_review_payload,
    create_utilization_case_payload,
    get_review,
    make_advisor_headers,
    make_case,
    make_payer,
    make_physician,
    make_review,
    setup_case,
    setup_case_with_submitted_review,
    submit_review,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["ur_director_headers"]
NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]


class TestCaseCreation:
    def test_utilization_case_create_computed_and_system_fields(self, api):
        """PRD §3.2: "The server immediately initializes `current_admission_status` from `requested_admission_status`, sets `review_status` to `INTAKE` and `auth_status` to `AUTH_PENDING`, computes the PROVISIONAL two-midnight benchmark per §2.8, and appends a `CASE_OPENED` audit event."
        PRD §2.8: "At case creation, the **PROVISIONAL** variant runs: `expected_midnight_count` is computed from `admit_at` and the physician-documented `expected_discharge_at`, `two_midnight_benchmark_met` is evaluated against that count, and `benchmark_basis` is set to `PROVISIONAL`."
        PRD §2.8: "`actual_midnight_count` remains null until discharge."

        Design: Corner/entities/utilization_case_create_computed_and_system_fields
        """
        payer = make_payer()
        attending = make_physician()
        case = validate_success(api.create_utilization_case(
            create_utilization_case_payload(payer["id"], attending["id"],
                                            patient_mrn="MRN-ENT"),
            NURSE), expected_status=201)
        assert_utilization_case(case)
        assert isinstance(case["version"], int)
        # 2026-08-01 -> 2026-08-03 crosses exactly two calendar-date boundaries.
        assert case["expected_midnight_count"] == 2
        assert case["two_midnight_benchmark_met"] == "MET"
        assert case["benchmark_basis"] == "PROVISIONAL"
        assert case.get("actual_midnight_count") is None
        assert case.get("discharge_at") is None
        assert case["review_status"] == "INTAKE"
        assert case["auth_status"] == "AUTH_PENDING"
        assert case["current_admission_status"] == "INPATIENT"
        assert case["certified_day_count"] == 0
        assert case["certified_inpatient_day_count"] == 0
        assert case["certified_observation_day_count"] == 0
        assert case["open_avoidable_day_count"] == 0
        assert case["escalation_tier"] == 0

    def test_case_create_computed_field_input_rejected(self, api):
        """PRD §2.5: "Request-shape integrity — required fields present, enum members valid, numeric ranges honored (including the conference-duration floor of at least 15 minutes with the end strictly after the start), and no client-supplied computed or system-managed fields; failure yields `ERR_VALIDATION_FAILED`."

        Design: Corner/entities/case_create_computed_field_input_rejected
        """
        payer = make_payer()
        attending = make_physician()
        payload = create_utilization_case_payload(payer["id"], attending["id"],
                                                  patient_mrn="MRN-SYS")
        payload["two_midnight_benchmark_met"] = "MET"
        resp = api.create_utilization_case(payload, NURSE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED,
                       expected_status=400)

    def test_audit_event_has_no_version_field(self, api):
        """PRD §2.6: "The **AuditEvent** resource is the single exception: it is append-only and immutable, so it carries `id` and `created_at` only; both `updated_at` and `version` are absent."
        PRD §3.2: "The server immediately initializes `current_admission_status` from `requested_admission_status`, sets `review_status` to `INTAKE` and `auth_status` to `AUTH_PENDING`, computes the PROVISIONAL two-midnight benchmark per §2.8, and appends a `CASE_OPENED` audit event."

        Design: Corner/entities/audit_event_has_no_version_field
        """
        ctx = setup_case(patient_mrn="MRN-AUD")
        events, meta = validate_paginated(
            api.list_audit_events(ctx["case"]["id"], DIRECTOR))
        assert meta["total_count"] == 1 and len(events) == 1
        event = events[0]
        assert_audit_event(event)
        assert event["event_type"] == "CASE_OPENED"
        assert event["actor_role"] == "URNurse"


class TestAdmissionReviewCreation:
    def test_admission_review_child_listing_under_case(self, api):
        """PRD §3.2: "Reviews of a case list in `created_at` ascending order."

        Design: Corner/entities/admission_review_child_listing_under_case
        """
        ctx = setup_case(patient_mrn="MRN-PAR")
        review = make_review(ctx["case"]["id"], criteria_set="MCG",
                             severity_of_illness_points=4,
                             intensity_of_service_points=4,
                             comorbidity_count=1)
        data, meta = validate_paginated(
            api.list_admission_reviews(ctx["case"]["id"], PAYER_REVIEWER))
        assert meta["total_count"] == 1 and len(data) == 1
        assert_admission_review(data[0])
        assert data[0]["id"] == review["id"]
        assert data[0]["case_id"] == ctx["case"]["id"]

    def test_admission_review_initial_state_draft(self, api):
        """PRD §3.2: "The review is born in `DRAFT`, with `necessity_score`, `determination`, and `recommended_status` all unset; its `determination` reads `PENDING` while drafting."

        Design: Corner/state_machines/admission_review_initial_state_draft
        """
        ctx = setup_case(patient_mrn="MRN-INIT")
        review = validate_success(api.create_admission_review(
            ctx["case"]["id"],
            create_admission_review_payload(
                severity_of_illness_points=9, intensity_of_service_points=7,
                comorbidity_count=1, two_midnight_attestation=True),
            NURSE), expected_status=201)
        assert_admission_review(review)
        assert review["status"] == "DRAFT"
        assert review["determination"] == "PENDING"
        assert review.get("necessity_score") is None
        assert review.get("submitted_at") is None


class TestTwoMidnightBoundary:
    def test_two_midnight_exactly_two_crossings_is_met(self, api):
        """PRD §2.8: "A **midnight count** between two timestamps is the number of calendar-date boundaries crossed — the whole-calendar-day difference between the two dates; the times of day are irrelevant."
        PRD §2.8: "The benchmark is `MET` when the applicable count is at least 2 and `NOT_MET` otherwise; exactly two midnights is `MET`."

        Design: Difficulty/boundary_precision_check/two_midnight_exactly_two_is_met
        """
        ctx = setup_case(patient_mrn="MRN-B2")
        case = ctx["case"]
        assert case["expected_midnight_count"] == 2, (
            "2026-08-01 -> 2026-08-03 crosses exactly two calendar-date boundaries")
        assert case["two_midnight_benchmark_met"] == "MET"

    def test_two_midnight_single_crossing_is_not_met(self, api):
        """PRD §2.8: "The benchmark is `MET` when the applicable count is at least 2 and `NOT_MET` otherwise; exactly two midnights is `MET`."

        Design: Difficulty/boundary_precision_check/two_midnight_exactly_two_is_met
        """
        payer = make_payer()
        attending = make_physician()
        case = make_case(payer["id"], attending["id"], patient_mrn="MRN-B1",
                         expected_discharge_at="2026-08-02T06:00:00Z")
        assert case["expected_midnight_count"] == 1, (
            "2026-08-01 -> 2026-08-02 crosses exactly one calendar-date boundary")
        assert case["two_midnight_benchmark_met"] == "NOT_MET"


class TestNecessityScore:
    def test_necessity_score_caps_and_boundary_on_medicare(self, api):
        """PRD §3.2: "the server computes the **medical necessity score** from the three point inputs and the case's payer plan class: severity points are capped at 12 and multiplied by 5; intensity points are capped at 12 and multiplied by 5; the comorbidity count is capped at 3 and multiplied by 4 when the payer is in the Medicare family (`MEDICARE` or `MANAGED_MEDICARE`) or by 2 otherwise; the three weighted components are summed and the total is capped at 100."
        PRD §3.2: "The `determination` is then `CRITERIA_MET` when the score reaches at least 60, and `CRITERIA_NOT_MET` below that threshold."

        Design: Difficulty/combinatorial_formula/necessity_score_caps_branch_threshold
        """
        payer = make_payer(plan_class="MEDICARE")
        attending = make_physician()

        # Case A: 10*5 + 8*5 + 2*4 = 98 -> CRITERIA_MET, recommended INPATIENT.
        case_a = make_case(payer["id"], attending["id"], patient_mrn="MRN-A")
        review_a = make_review(case_a["id"],
                               severity_of_illness_points=10,
                               intensity_of_service_points=8,
                               comorbidity_count=2,
                               two_midnight_attestation=True)
        submitted_a = submit_review(review_a["id"])
        assert submitted_a["necessity_score"] == 98
        assert submitted_a["determination"] == "CRITERIA_MET"
        assert submitted_a["recommended_status"] == "INPATIENT", (
            "CRITERIA_MET with a MET provisional benchmark recommends INPATIENT")

        # Case B: caps bind — min(20,12)*5 + 0 + min(5,3)*4 = 60 + 0 + 12 = 72.
        case_b = make_case(payer["id"], attending["id"], patient_mrn="MRN-B")
        review_b = make_review(case_b["id"], criteria_set="MCG",
                               severity_of_illness_points=20,
                               intensity_of_service_points=0,
                               comorbidity_count=5,
                               two_midnight_attestation=True)
        submitted_b = submit_review(review_b["id"])
        assert submitted_b["necessity_score"] == 72, (
            "severity is capped at 12 and comorbidity at 3 before weighting")
        assert submitted_b["determination"] == "CRITERIA_MET"

        # Case C: 7*5 + 5*5 + 0 = 60 — exactly the inclusive threshold.
        case_c = make_case(payer["id"], attending["id"], patient_mrn="MRN-C")
        review_c = make_review(case_c["id"],
                               severity_of_illness_points=7,
                               intensity_of_service_points=5,
                               comorbidity_count=0,
                               two_midnight_attestation=True)
        submitted_c = submit_review(review_c["id"])
        assert submitted_c["necessity_score"] == 60
        assert submitted_c["determination"] == "CRITERIA_MET", (
            "a score of exactly 60 reaches the inclusive threshold")

    def test_necessity_score_commercial_comorbidity_branch(self, api):
        """PRD §3.2: "the comorbidity count is capped at 3 and multiplied by 4 when the payer is in the Medicare family (`MEDICARE` or `MANAGED_MEDICARE`) or by 2 otherwise"
        PRD §3.2: "The `recommended_status` is `INPATIENT` only when the determination is `CRITERIA_MET` **and** the case's current `two_midnight_benchmark_met` reads `MET`; in every other combination it is `OBSERVATION`."

        Design: Difficulty/combinatorial_formula/necessity_score_caps_branch_threshold
        """
        payer = make_payer(name="Commercial PPO", plan_class="COMMERCIAL")
        attending = make_physician()
        case_d = make_case(payer["id"], attending["id"], patient_mrn="MRN-D")
        review_d = make_review(case_d["id"],
                               severity_of_illness_points=5,
                               intensity_of_service_points=5,
                               comorbidity_count=1,
                               two_midnight_attestation=False)
        submitted_d = submit_review(review_d["id"])
        # 5*5 + 5*5 + min(1,3)*2 = 52 < 60 — the COMMERCIAL branch weights 2.
        assert submitted_d["necessity_score"] == 52
        assert submitted_d["determination"] == "CRITERIA_NOT_MET"
        assert submitted_d["recommended_status"] == "OBSERVATION"


class TestSubmitDocumentationGateAndAdvisorReview:
    def test_two_midnight_doc_required_on_submit(self, api):
        """PRD §3.2: "A documentation gate guards the combination of a favorable score and a missing attestation: when the computed recommendation would be `INPATIENT` but `two_midnight_attestation` is false, the submit is rejected with `ERR_TWO_MIDNIGHT_DOC_REQUIRED`."

        Design: Corner/validations/two_midnight_doc_required_on_submit
        """
        ctx = setup_case(patient_mrn="MRN-TMD")
        review = make_review(ctx["case"]["id"],
                             severity_of_illness_points=10,
                             intensity_of_service_points=8,
                             comorbidity_count=2,
                             two_midnight_attestation=False)
        resp = api.submit_admission_review(review["id"], {}, NURSE)
        validate_error(resp, ApiErrorId.ERR_TWO_MIDNIGHT_DOC_REQUIRED,
                       expected_status=422)
        assert get_review(review["id"])["status"] == "DRAFT", (
            "a rejected submit leaves the review in DRAFT")

    def test_advisor_review_requires_not_met_determination(self, api):
        """PRD §3.2: "Advisor review is defined only for `SUBMITTED` reviews whose determination is `CRITERIA_NOT_MET`; any other combination fails state-machine legality."

        Design: Corner/state_machines/advisor_review_requires_not_met_determination
        """
        ctx = setup_case_with_submitted_review(
            severity=10, intensity=8, comorbidity=2, attestation=True,
            with_advisor=True, patient_mrn="MRN-ADV")
        assert ctx["review"]["determination"] == "CRITERIA_MET"
        resp = api.advisor_review(
            ctx["review"]["id"], {"advisor_decision": "REVERSE"},
            make_advisor_headers(ctx["advisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_review(ctx["review"]["id"])["determination"] == "CRITERIA_MET"

    def test_advisor_reverse_rewrites_determination(self, api):
        """PRD §3.2: "On `REVERSE`, the determination is rewritten to `CRITERIA_MET` and the `recommended_status` is recomputed under the same rule as at submit; on `UPHOLD`, the determination stands."

        Design: Corner/state_machines/advisor_reverse_rewrites_determination
        """
        ctx = setup_case_with_submitted_review(
            severity=2, intensity=2, comorbidity=0, attestation=False,
            with_advisor=True, patient_mrn="MRN-REV")
        assert ctx["review"]["determination"] == "CRITERIA_NOT_MET"
        assert ctx["review"]["recommended_status"] == "OBSERVATION"

        reviewed = validate_success(api.advisor_review(
            ctx["review"]["id"],
            {"advisor_decision": "REVERSE",
             "advisor_note": "Severity understated by initial screen"},
            make_advisor_headers(ctx["advisor"]["id"])))
        assert reviewed["status"] == "ADVISOR_REVIEWED"
        assert reviewed["determination"] == "CRITERIA_MET"
        # The case's provisional benchmark is MET, so the recomputed
        # recommendation moves from OBSERVATION to INPATIENT.
        assert reviewed["recommended_status"] == "INPATIENT"

    def test_sod_on_advisor_review_of_own_case(self, api):
        """PRD §3.2: "Segregation of duties applies: the reviewing advisor's `X-User-ID` must differ from the case's `attending_physician_id`, on pain of `ERR_SOD_ROLE_CONFLICT`."

        Design: Corner/validations/sod_on_advisor_review_of_own_case
        """
        payer = make_payer()
        attending_advisor = make_physician(is_advisor=True,
                                           full_name="Dr. AttendAdvisor")
        case = make_case(payer["id"], attending_advisor["id"],
                         patient_mrn="MRN-SOD")
        review = submit_review(make_review(case["id"])["id"])
        assert review["determination"] == "CRITERIA_NOT_MET"

        resp = api.advisor_review(
            review["id"], {"advisor_decision": "REVERSE"},
            make_advisor_headers(attending_advisor["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_ROLE_CONFLICT,
                       expected_status=422)
        assert get_review(review["id"])["determination"] == "CRITERIA_NOT_MET"
