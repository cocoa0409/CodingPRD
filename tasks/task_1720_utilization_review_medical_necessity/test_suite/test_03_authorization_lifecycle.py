"""Authorization request lifecycle: parallel case axes, the pend/resubmit
cycle, optimistic concurrency, and fiscal/content gates (PRD §2.4, §2.9,
§2.10, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_auth,
    auth_payer_decision_payload,
    assert_authorization_request,
    create_authorization_request_payload,
    get_auth,
    get_case,
    list_auths,
    make_auth,
    make_review,
    pend_auth,
    resubmit_auth,
    setup_approved_auth,
    setup_case,
    setup_submitted_auth,
    submit_review,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]


class TestParallelStateAxes:
    def test_axes_at_creation_and_after_review_submit(self, api):
        """PRD §2.4: "The first axis, `review_status`, tracks the hospital-side review lifecycle: `INTAKE` at case opening, advancing to `ADMISSION_REVIEWED` when an admission review is submitted, then to `MONITORING` when any authorization request of the case is approved, and finally to `CLOSED` at discharge."
        PRD §2.4: "The second axis, `auth_status`, tracks the payer-side authorization lifecycle independently: `AUTH_PENDING` at case opening, `AUTH_IN_PROGRESS` once the first authorization request is created, `AUTHORIZED` when an authorization request is approved, and `DENIED` on any payer denial; a `DENIED` case returns to `AUTHORIZED` when a peer-to-peer conference or appeal overturns the denial."

        Design: Difficulty/non_linear_state_machine/utilization_case_parallel_state_axes
        """
        ctx = setup_case(patient_mrn="MRN-AX1")
        case = ctx["case"]
        assert case["review_status"] == "INTAKE"
        assert case["auth_status"] == "AUTH_PENDING"

        review = submit_review(make_review(
            case["id"], severity_of_illness_points=10,
            intensity_of_service_points=8, comorbidity_count=2,
            two_midnight_attestation=True)["id"])
        assert review["status"] == "SUBMITTED"
        after_submit = get_case(case["id"])
        assert after_submit["review_status"] == "ADMISSION_REVIEWED"
        assert after_submit["auth_status"] == "AUTH_PENDING", (
            "the review-axis transition must not touch the auth axis")

    def test_axes_after_auth_create_and_approval(self, api):
        """PRD §3.3: "The case's `auth_status` axis moves from `AUTH_PENDING` to `AUTH_IN_PROGRESS` on the first request, the case `version` increments, and `AUTH_SUBMITTED` is appended."
        PRD §3.3: "Approval sets `decided_at`, flips the case's `auth_status` to `AUTHORIZED`, advances `review_status` from `ADMISSION_REVIEWED` to `MONITORING` when applicable, recomputes the case's certified counters, increments the case `version`, and appends `AUTH_APPROVED`."

        Design: Difficulty/non_linear_state_machine/utilization_case_parallel_state_axes
        """
        ctx = setup_case(patient_mrn="MRN-AX2")
        case = ctx["case"]
        submit_review(make_review(
            case["id"], severity_of_illness_points=10,
            intensity_of_service_points=8, comorbidity_count=2,
            two_midnight_attestation=True)["id"])

        auth = make_auth(case["id"])
        after_create = get_case(case["id"])
        assert after_create["auth_status"] == "AUTH_IN_PROGRESS"
        assert after_create["review_status"] == "ADMISSION_REVIEWED", (
            "the auth-axis transition must not touch the review axis")

        approve_auth(auth["id"], certified_day_start=1, certified_day_count=3)
        after_approval = get_case(case["id"])
        assert after_approval["auth_status"] == "AUTHORIZED"
        assert after_approval["review_status"] == "MONITORING"
        assert after_approval["certified_day_count"] == 3


class TestPendResubmitCycle:
    def test_pend_resubmit_cycle_increments_submission_round(self, api):
        """PRD §3.3: "The `SUBMITTED` → `PENDED` → `SUBMITTED` cycle may repeat without bound: a `URNurse` resubmits a `PENDED` request with a refreshed `clinical_summary` (the 50-character completeness gate applies again, and failing it yields `ERR_CLINICAL_DOC_INCOMPLETE`), which replaces the stored summary, increments `submission_round` by 1, and appends `AUTH_RESUBMITTED`."
        PRD §3.3: "while the new request is born in `SUBMITTED` with `submission_round` set to 1."

        Design: Difficulty/non_linear_state_machine/authorization_request_pend_resubmit_cycle
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-CYC")
        auth = ctx["auth"]
        assert auth["status"] == "SUBMITTED" and auth["submission_round"] == 1

        assert pend_auth(auth["id"], "Need updated cardiology notes")["status"] == "PENDED"
        assert resubmit_auth(auth["id"], "Updated packet with cardiology consult and echo findings attached.")["submission_round"] == 2
        assert pend_auth(auth["id"], "Need discharge disposition plan")["status"] == "PENDED"
        assert resubmit_auth(auth["id"], "Final packet with disposition plan, pharmacy reconciliation, and consults.")["submission_round"] == 3

        approved = approve_auth(auth["id"], certified_day_start=1,
                                certified_day_count=3)
        assert_authorization_request(approved)
        assert approved["submission_round"] == 3, (
            "two PENDED -> SUBMITTED cycles advance the round from 1 to 3")
        assert approved["status"] == "APPROVED"
        assert approved["certified_day_start"] == 1
        assert approved["certified_day_end"] == 4

    def test_pend_resubmit_cycle_ends_in_approval_axes(self, api):
        """PRD §3.3: "Approval sets `decided_at`, flips the case's `auth_status` to `AUTHORIZED`, advances `review_status` from `ADMISSION_REVIEWED` to `MONITORING` when applicable, recomputes the case's certified counters, increments the case `version`, and appends `AUTH_APPROVED`."

        Design: Difficulty/non_linear_state_machine/authorization_request_pend_resubmit_cycle
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-CYC2")
        auth = ctx["auth"]
        # PRD §3.3 pins the review-axis transition "from ADMISSION_REVIEWED to
        # MONITORING", so the case must reach ADMISSION_REVIEWED (via an
        # admission-review submit) before the approval for MONITORING to be
        # the determined outcome.
        submit_review(make_review(
            ctx["case"]["id"], severity_of_illness_points=10,
            intensity_of_service_points=8, comorbidity_count=2,
            two_midnight_attestation=True)["id"])
        pend_auth(auth["id"])
        resubmit_auth(auth["id"])
        pend_auth(auth["id"])
        resubmit_auth(auth["id"])
        approve_auth(auth["id"], certified_day_start=1, certified_day_count=3)

        case = get_case(ctx["case"]["id"])
        assert case["auth_status"] == "AUTHORIZED"
        assert case["review_status"] == "MONITORING"
        assert case["certified_day_count"] == 3


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_auth_create_rejected(self, api):
        """PRD §2.10: "If the value does not equal the case's current `version` — because another writer has advanced the case since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from superseding requests or rewriting case-level status on a view it has not observed."

        Design: Corner/complexity_layers/occ_stale_version_on_auth_create_rejected
        """
        ctx = setup_case(patient_mrn="MRN-OCC1")
        case = ctx["case"]
        observed_version = case["version"]
        first = make_auth(case["id"], expected_case_version=observed_version)
        assert first["status"] == "SUBMITTED"

        resp = api.create_authorization_request(
            case["id"],
            create_authorization_request_payload(
                observed_version, level_of_care="OBSERVATION",
                requested_day_count=2,
                clinical_summary="Competing writer replaying the originally observed case version."),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        auths = list_auths(case["id"])
        assert len(auths) == 1 and auths[0]["id"] == first["id"]
        assert auths[0]["status"] == "SUBMITTED", (
            "a stale-version rejection must not supersede the live request")

    def test_occ_correct_version_succeeds_and_increments(self, api):
        """PRD §3.3: "This is one of the two OCC-guarded create-with-supersede writers described in §2.10: the payload must carry `expected_case_version` equal to the case's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`."
        PRD §2.4: "Every mutation of a case or one of its descendants that touches case-level computed state refreshes the case's `updated_at` and increments its `version` by exactly 1, so clients can always detect that a cascade has run by watching `version`."

        Design: Corner/complexity_layers/occ_correct_version_succeeds_and_increments
        """
        ctx = setup_case(patient_mrn="MRN-OCC2")
        case = ctx["case"]
        auth = validate_success(api.create_authorization_request(
            case["id"],
            create_authorization_request_payload(case["version"]),
            NURSE), expected_status=201)
        assert_authorization_request(auth)
        assert auth["status"] == "SUBMITTED"

        after = get_case(case["id"])
        assert after["version"] == case["version"] + 1, (
            "the create must advance the case version by exactly 1")
        assert after["auth_status"] == "AUTH_IN_PROGRESS"


class TestDecisionStateGates:
    def test_payer_decision_pend_from_approved_rejected(self, api):
        """PRD §3.3: "A `PayerReviewer` then renders the payer decision — a `decision` value of `APPROVE`, `PEND`, or `DENY` — against a `SUBMITTED` request."
        PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/payer_decision_pend_from_approved_rejected
        """
        ctx = setup_approved_auth(clock=None, patient_mrn="MRN-INV")
        auth = ctx["auth"]
        assert auth["status"] == "APPROVED"

        resp = api.auth_payer_decision(
            auth["id"],
            auth_payer_decision_payload("PEND", pend_reason="late pend attempt"),
            PAYER_REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_auth(auth["id"])["status"] == "APPROVED"

    def test_withdraw_then_rewithdraw_rejected(self, api):
        """PRD §3.3: "A nurse may also withdraw any request still in `SUBMITTED` or `PENDED`, moving it to terminal `WITHDRAWN` with an `AUTH_WITHDRAWN` event."
        PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/withdraw_then_rewithdraw_rejected
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-WD")
        auth = ctx["auth"]
        withdrawn = validate_success(
            api.withdraw_authorization_request(auth["id"], {}, NURSE))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.withdraw_authorization_request(auth["id"], {}, NURSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_auth(auth["id"])["status"] == "WITHDRAWN"

    def test_resubmit_clinical_doc_incomplete(self, api):
        """PRD §3.3: "The `SUBMITTED` → `PENDED` → `SUBMITTED` cycle may repeat without bound: a `URNurse` resubmits a `PENDED` request with a refreshed `clinical_summary` (the 50-character completeness gate applies again, and failing it yields `ERR_CLINICAL_DOC_INCOMPLETE`), which replaces the stored summary, increments `submission_round` by 1, and appends `AUTH_RESUBMITTED`."

        Design: Corner/validations/resubmit_clinical_doc_incomplete
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-RSM")
        auth = pend_auth(ctx["auth"]["id"], "need more clinical detail")
        assert auth["status"] == "PENDED" and auth["submission_round"] == 1

        resp = api.resubmit_authorization_request(
            auth["id"], {"clinical_summary": "too short a summary"}, NURSE)
        validate_error(resp, ApiErrorId.ERR_CLINICAL_DOC_INCOMPLETE,
                       expected_status=422)
        after = get_auth(auth["id"])
        assert after["status"] == "PENDED"
        assert after["submission_round"] == 1, (
            "a rejected resubmit must not advance the submission round")


class TestFiscalGateAndCounters:
    def test_bed_day_budget_exceeded_on_approve(self, api):
        """PRD §2.9: "The payer's `bed_day_budget_per_case` caps cumulative certified days: any decision — initial authorization approval or concurrent-review approval or partial — that would push `certified_day_count` past the budget is rejected with `ERR_BED_DAY_BUDGET_EXCEEDED`, and the same cap applies to `requested_day_count` at authorization-request creation."

        Design: Corner/errors/bed_day_budget_exceeded_on_approve
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Narrow HMO",
                         bed_day_budget_per_case=5, patient_mrn="MRN-BUD")
        auth = make_auth(ctx["case"]["id"], requested_day_count=5)
        assert auth["status"] == "SUBMITTED"

        resp = api.auth_payer_decision(
            auth["id"],
            auth_payer_decision_payload("APPROVE", certified_day_start=1,
                                        certified_day_count=6),
            PAYER_REVIEWER)
        validate_error(resp, ApiErrorId.ERR_BED_DAY_BUDGET_EXCEEDED,
                       expected_status=422)
        assert get_auth(auth["id"])["status"] == "SUBMITTED"
        assert get_case(ctx["case"]["id"])["certified_day_count"] == 0

    def test_auth_create_safety_beats_fiscal_error_id(self, api):
        """PRD §3.3: "Two content gates also apply at creation: the `requested_day_count` may not exceed the payer's `bed_day_budget_per_case` (`ERR_BED_DAY_BUDGET_EXCEEDED`), and the `clinical_summary` must be at least 50 characters long — the completeness gate, `ERR_CLINICAL_DOC_INCOMPLETE` on failure."
        PRD §2.5: "A request that would trip two gates is reported against the earliest gate in this ordering — so, for instance, an unauthenticated caller with a malformed body receives `ERR_UNAUTHENTICATED`, and a stale-version create on a case that is also closed receives `ERR_CASE_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/auth_create_safety_beats_fiscal
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Commercial PPO",
                         bed_day_budget_per_case=30, patient_mrn="MRN-PP2")
        case = ctx["case"]
        # One call violating both the completeness gate (5 chars < 50) and the
        # budget gate (99 days > 30): the safety gate reports first.
        resp = api.create_authorization_request(
            case["id"],
            create_authorization_request_payload(
                case["version"], requested_day_count=99,
                clinical_summary="short"),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CLINICAL_DOC_INCOMPLETE,
                       expected_status=422)

    def test_auth_create_safety_beats_fiscal_no_side_effects(self, api):
        """PRD §3.3: "The case's `auth_status` axis moves from `AUTH_PENDING` to `AUTH_IN_PROGRESS` on the first request, the case `version` increments, and `AUTH_SUBMITTED` is appended."
        PRD §2.5: "A request that would trip two gates is reported against the earliest gate in this ordering — so, for instance, an unauthenticated caller with a malformed body receives `ERR_UNAUTHENTICATED`, and a stale-version create on a case that is also closed receives `ERR_CASE_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/auth_create_safety_beats_fiscal
        """
        ctx = setup_case(plan_class="COMMERCIAL", name="Commercial PPO",
                         bed_day_budget_per_case=30, patient_mrn="MRN-PP2B")
        case = ctx["case"]
        resp = api.create_authorization_request(
            case["id"],
            create_authorization_request_payload(
                case["version"], requested_day_count=99,
                clinical_summary="short"),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CLINICAL_DOC_INCOMPLETE,
                       expected_status=422)
        assert list_auths(case["id"]) == [], (
            "a rejected create must not persist an authorization request")
        assert get_case(case["id"])["auth_status"] == "AUTH_PENDING"


class TestApprovalConsistency:
    def test_immediate_consistency_on_approve(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "Approval sets `decided_at`, flips the case's `auth_status` to `AUTHORIZED`, advances `review_status` from `ADMISSION_REVIEWED` to `MONITORING` when applicable, recomputes the case's certified counters, increments the case `version`, and appends `AUTH_APPROVED`."

        Design: Corner/consistency_model/immediate_consistency_on_approve
        """
        ctx = setup_submitted_auth(patient_mrn="MRN-IMM")
        # Establish ADMISSION_REVIEWED first: PRD §3.3 pins the approval-time
        # review-axis transition as "from ADMISSION_REVIEWED to MONITORING".
        submit_review(make_review(
            ctx["case"]["id"], severity_of_illness_points=10,
            intensity_of_service_points=8, comorbidity_count=2,
            two_midnight_attestation=True)["id"])
        decided = validate_success(api.auth_payer_decision(
            ctx["auth"]["id"],
            auth_payer_decision_payload("APPROVE", certified_day_start=1,
                                        certified_day_count=3),
            PAYER_REVIEWER))
        assert decided["status"] == "APPROVED"
        assert decided["certified_day_start"] == 1
        assert decided["certified_day_end"] == 4
        assert decided.get("decided_at"), "decided_at must be stamped"

        case = get_case(ctx["case"]["id"])
        assert case["certified_day_count"] == 3
        assert case["auth_status"] == "AUTHORIZED"
        assert case["review_status"] == "MONITORING"

    def test_certified_day_count_aggregates_across_requests(self, api):
        """PRD §2.9: "Each case aggregates three computed counters over its certified intervals: `certified_day_count` (the sum of all interval lengths, both levels of care), `certified_inpatient_day_count` (the sum over intervals tagged `INPATIENT`), and `certified_observation_day_count` (the sum over intervals tagged `OBSERVATION`)."
        PRD §3.3: "Creation is a superseding event: every existing authorization request of the case in `SUBMITTED` or `PENDED` status transitions to `SUPERSEDED` (each appending `AUTH_SUPERSEDED`), while the new request is born in `SUBMITTED` with `submission_round` set to 1."

        Design: Corner/calculations/certified_day_count_aggregates_across_requests
        """
        ctx = setup_approved_auth(clock=None, patient_mrn="MRN-AGG",
                                  plan_class="COMMERCIAL", name="Commercial PPO")
        case = ctx["case"]
        auth_a = ctx["auth"]

        auth_b = make_auth(case["id"], level_of_care="OBSERVATION",
                           requested_day_count=3,
                           clinical_summary="Step-down observation monitoring after stabilization on oral therapy.")
        auth_b = approve_auth(auth_b["id"], certified_day_start=4,
                              certified_day_count=3)
        assert auth_b["status"] == "APPROVED"
        assert auth_b["certified_day_start"] == 4
        assert auth_b["certified_day_end"] == 7

        case_after = get_case(case["id"])
        assert case_after["certified_day_count"] == 6
        assert case_after["certified_inpatient_day_count"] == 3
        assert case_after["certified_observation_day_count"] == 3
        assert get_auth(auth_a["id"])["status"] == "APPROVED", (
            "supersede clears only SUBMITTED or PENDED requests, never APPROVED")
