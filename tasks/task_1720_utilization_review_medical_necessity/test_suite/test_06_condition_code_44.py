"""Condition-code-44 inpatient-to-observation flow: creation gates, the
pinned rebill rounding order, concurrence/committee forks, the approval and
rescission cascades, and segregation of duties (PRD §2.5, §2.7, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cc44_request,
    cc44_committee_payload,
    committee_cc44,
    concur_cc44,
    create_cc44_payload,
    approve_auth,
    discharge_case,
    get_auth,
    get_case,
    get_cc44,
    list_cc44,
    make_advisor_headers,
    make_attending_headers,
    make_advisor,
    make_auth,
    make_case,
    make_cc44,
    make_payer,
    make_physician,
    make_review,
    case_version,
    setup_case_with_submitted_review,
    setup_cc44_committee_pending,
    setup_cc44_open,
    submit_review,
    validate_error,
    validate_success,
    assert_certified_counters_consistent,
)

NURSE = TEST_USERS["ur_nurse_headers"]
DIRECTOR = TEST_USERS["ur_director_headers"]


class TestRebillEstimate:
    def test_cc44_rebill_per_line_round_then_sum(self, api):
        """PRD §2.7: "The one monetary calculation in the system, the condition-code-44 rebill estimate, rounds **half-up to whole cents per service line first, then sums the rounded lines** to an exact integer total."
        PRD §3.6: "At creation, the server computes `rebill_estimate_cents` from the service lines per the pinned rounding rule of §2.7 — each line's charge is multiplied by its milli-rate, divided by 1000, and rounded half-up to whole cents, and the rounded line values are then summed exactly."

        Design: Difficulty/combinatorial_formula/cc44_rebill_per_line_round_then_sum
        """
        ctx = setup_cc44_open(patient_mrn="MRN-RB", service_lines=[
            {"description": "Room and board", "charge_cents": 100001,
             "rate_milli": 385},
            {"description": "Lab panel", "charge_cents": 100001,
             "rate_milli": 385},
        ])
        cc44 = ctx["cc44"]
        assert_cc44_request(cc44)
        # Per line: round_half_up(100001 * 385 / 1000) = round_half_up(38500.385)
        # = 38500; the pinned order sums 38500 + 38500 = 77000. The rejected
        # sum-then-round order would yield round_half_up(77000.77) = 77001.
        assert cc44["rebill_estimate_cents"] == 77000
        assert cc44["status"] == "CONCURRENCE_PENDING"

    def test_cc44_rebill_rounds_half_up_per_line(self, api):
        """PRD §2.7: "The one monetary calculation in the system, the condition-code-44 rebill estimate, rounds **half-up to whole cents per service line first, then sums the rounded lines** to an exact integer total."

        Design: Difficulty/combinatorial_formula/cc44_rebill_per_line_round_then_sum
        """
        ctx = setup_cc44_open(patient_mrn="MRN-RB2", service_lines=[
            {"description": "Line A", "charge_cents": 1001, "rate_milli": 500},
            {"description": "Line B", "charge_cents": 1001, "rate_milli": 500},
        ])
        # Per line: round_half_up(500.5) = 501 (half-up, not banker's), so the
        # pinned total is 501 + 501 = 1002; sum-then-round would give 1001.
        assert ctx["cc44"]["rebill_estimate_cents"] == 1002


class TestCreationGates:
    def test_cc44_payer_ineligible_commercial(self, api):
        """PRD §3.6: "The case's payer must be in the Medicare family — a `plan_class` of `MEDICARE` or `MANAGED_MEDICARE`; any other plan class yields `ERR_CC44_PAYER_INELIGIBLE`."

        Design: Corner/validations/cc44_payer_ineligible_commercial
        """
        ctx = setup_case_with_submitted_review(plan_class="COMMERCIAL",
                                               patient_mrn="MRN-INEL")
        resp = api.create_cc44_request(
            ctx["case"]["id"], create_cc44_payload(case_version(ctx["case"]["id"])),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CC44_PAYER_INELIGIBLE,
                       expected_status=422)

    def test_cc44_rejected_while_latest_review_criteria_met(self, api):
        """PRD §3.6: "And the clinical basis must be present: the case's latest submitted-or-advisor-reviewed admission review must carry a determination of `CRITERIA_NOT_MET`; when the latest review still reads `CRITERIA_MET`, creation fails with `ERR_CC44_CRITERIA_STILL_MET`."

        Design: Difficulty/cross_entity_state_dependency/cc44_requires_latest_review_not_met
        """
        ctx = setup_case_with_submitted_review(
            severity=10, intensity=8, comorbidity=2, attestation=True,
            patient_mrn="MRN-CE2")
        assert ctx["review"]["determination"] == "CRITERIA_MET"

        resp = api.create_cc44_request(
            ctx["case"]["id"],
            create_cc44_payload(case_version(ctx["case"]["id"]),
                                rationale="Attempt while criteria met."),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CC44_CRITERIA_STILL_MET,
                       expected_status=422)
        assert list_cc44(ctx["case"]["id"]) == []

    def test_cc44_allowed_after_latest_review_not_met(self, api):
        """PRD §3.6: "And the clinical basis must be present: the case's latest submitted-or-advisor-reviewed admission review must carry a determination of `CRITERIA_NOT_MET`; when the latest review still reads `CRITERIA_MET`, creation fails with `ERR_CC44_CRITERIA_STILL_MET`."
        PRD §3.2: "A successful submit stamps `submitted_at` from the logical clock, moves the review to `SUBMITTED`, advances the parent case's `review_status` from `INTAKE` to `ADMISSION_REVIEWED` — a no-op when the case is already in `MONITORING`, since a re-review during monitoring is free-standing and causes no axis transition — increments the case's `version`, and appends `REVIEW_SUBMITTED`."

        Design: Difficulty/cross_entity_state_dependency/cc44_requires_latest_review_not_met
        """
        ctx = setup_case_with_submitted_review(
            severity=10, intensity=8, comorbidity=2, attestation=True,
            patient_mrn="MRN-CE2B")
        case_id = ctx["case"]["id"]
        submit_review(make_review(case_id, criteria_set="MCG")["id"])

        cc44 = make_cc44(case_id, rationale="Latest review now CRITERIA_NOT_MET.")
        assert cc44["status"] == "CONCURRENCE_PENDING"
        assert get_case(case_id)["review_status"] == "ADMISSION_REVIEWED", (
            "the second review does not regress the review axis")

    def test_cc44_second_open_request_rejected(self, api):
        """PRD §3.6: "Additionally, at most one CC44 request per case may be open at a time — one already in `CONCURRENCE_PENDING` or `COMMITTEE_PENDING` blocks a new initiation with `ERR_CC44_ALREADY_OPEN`."

        Design: Corner/validations/cc44_second_open_request_rejected
        """
        ctx = setup_cc44_open(patient_mrn="MRN-OPEN")
        resp = api.create_cc44_request(
            ctx["case"]["id"],
            create_cc44_payload(case_version(ctx["case"]["id"]),
                                rationale="Duplicate open request."),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CC44_ALREADY_OPEN,
                       expected_status=409)
        assert len(list_cc44(ctx["case"]["id"])) == 1

    def test_cc44_create_after_discharge_rejected(self, api):
        """PRD §3.6: "The case must not be discharged — initiating a CC44 on a `CLOSED` case is rejected with `ERR_CC44_POST_DISCHARGE`."
        PRD §2.4: "The sole exception is the condition-code-44 flow: initiating one on a discharged case surfaces the domain-specific `ERR_CC44_POST_DISCHARGE` rather than the generic closure error, because CMS regulation frames CC44 as a pre-discharge process."

        Design: Corner/validations/cc44_create_after_discharge_rejected
        """
        ctx = setup_case_with_submitted_review(patient_mrn="MRN-PD")
        discharge_case(ctx["case"]["id"], "2026-08-03T09:00:00Z")
        resp = api.create_cc44_request(
            ctx["case"]["id"],
            create_cc44_payload(case_version(ctx["case"]["id"]),
                                rationale="Post-discharge attempt."),
            NURSE)
        validate_error(resp, ApiErrorId.ERR_CC44_POST_DISCHARGE,
                       expected_status=409)


class TestConcurrenceFork:
    def test_cc44_decline_fork_leaves_case_unchanged(self, api):
        """PRD §3.6: "On `DECLINE`, `attending_concurrence` becomes `DECLINED`, the request closes to terminal `DECLINED_CLOSED`, the case is left entirely unchanged — this branch carries no flip side effects — and `CC44_DECLINED` is appended."

        Design: Difficulty/non_linear_state_machine/cc44_fork_join_with_rescind_revert
        """
        ctx = setup_cc44_open(patient_mrn="MRN-F1")
        declined = validate_success(api.cc44_concurrence(
            ctx["cc44"]["id"],
            {"decision": "DECLINE",
             "concurrence_note": "I believe inpatient is warranted"},
            make_attending_headers(ctx["attending"]["id"])))
        assert declined["status"] == "DECLINED_CLOSED"
        assert declined["attending_concurrence"] == "DECLINED"

        case = get_case(ctx["case"]["id"])
        assert case["current_admission_status"] == "INPATIENT", (
            "the DECLINE fork carries no flip side effects")

    def test_cc44_approve_then_rescind_reverts_status(self, api):
        """PRD §3.6: "On `APPROVE` (with an optional `committee_note`), the `committee_reviewer_id` is set from the caller's `X-User-ID`, `effective_at` stamps the logical clock, and the full status-change cascade fires: the case's `current_admission_status` flips from `INPATIENT` to `OBSERVATION`"
        PRD §3.6: "An approved CC44 can be undone before discharge by a `URDirector` supplying a `rescind_reason`: the request moves from `APPROVED` to terminal `RESCINDED`, the case's `current_admission_status` is restored from `OBSERVATION` to `INPATIENT`"

        Design: Difficulty/non_linear_state_machine/cc44_fork_join_with_rescind_revert
        """
        ctx = setup_cc44_committee_pending(patient_mrn="MRN-F2")
        approved = committee_cc44(ctx["cc44"]["id"], ctx["advisor"]["id"],
                                  "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["committee_reviewer_id"] == ctx["advisor"]["id"]
        assert get_case(ctx["case"]["id"])["current_admission_status"] == "OBSERVATION"

        rescinded = validate_success(api.cc44_rescind(
            ctx["cc44"]["id"],
            {"rescind_reason": "New clinical information requalifies inpatient"},
            DIRECTOR))
        assert rescinded["status"] == "RESCINDED"
        assert get_case(ctx["case"]["id"])["current_admission_status"] == "INPATIENT"


class TestApprovalCascade:
    def _setup_concurred_cc44_with_auth(self, api, approve_first: bool,
                                        mrn: str):
        """Medicare case with a submitted CRITERIA_NOT_MET review, one
        INPATIENT authorization (SUBMITTED, or APPROVED [1,4) when
        approve_first), and a CC44 request advanced to COMMITTEE_PENDING."""
        ctx = setup_case_with_submitted_review(with_advisor=True,
                                               patient_mrn=mrn)
        ctx["auth"] = make_auth(ctx["case"]["id"])
        if approve_first:
            ctx["auth"] = approve_auth(ctx["auth"]["id"],
                                       certified_day_start=1,
                                       certified_day_count=3)
        ctx["cc44"] = make_cc44(ctx["case"]["id"])
        ctx["cc44"] = concur_cc44(ctx["cc44"]["id"], ctx["attending"]["id"])
        return ctx

    def test_cc44_approval_flips_admission_status(self, api):
        """PRD §3.6: "the full status-change cascade fires: the case's `current_admission_status` flips from `INPATIENT` to `OBSERVATION`; every authorization request of the case whose `level_of_care` is `INPATIENT` and whose status is `SUBMITTED` or `PENDED` moves to `WITHDRAWN`"

        Design: Difficulty/transitive_cascade/cc44_approval_withdrawal_cascade
        """
        ctx = self._setup_concurred_cc44_with_auth(api, approve_first=False,
                                                   mrn="MRN-C44")
        approved = committee_cc44(ctx["cc44"]["id"], ctx["advisor"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved.get("effective_at"), "effective_at must be stamped"

        case = get_case(ctx["case"]["id"])
        assert case["current_admission_status"] == "OBSERVATION"

    def test_cc44_approval_withdraws_inpatient_auth(self, api):
        """PRD §3.6: "every authorization request of the case whose `level_of_care` is `INPATIENT` and whose status is `SUBMITTED` or `PENDED` moves to `WITHDRAWN`"

        Design: Difficulty/transitive_cascade/cc44_approval_withdrawal_cascade
        """
        ctx = self._setup_concurred_cc44_with_auth(api, approve_first=False,
                                                   mrn="MRN-C44B")
        assert ctx["auth"]["status"] == "SUBMITTED"
        committee_cc44(ctx["cc44"]["id"], ctx["advisor"]["id"])
        assert get_auth(ctx["auth"]["id"])["status"] == "WITHDRAWN", (
            "the status flip itself withdraws the non-terminal INPATIENT request")

    def test_cc44_approve_conserves_certified_days(self, api):
        """PRD §3.6: "every already-approved certified interval tagged `INPATIENT` is re-tagged `OBSERVATION` with its range unchanged, so the total `certified_day_count` is conserved and the inpatient/observation split moves one-for-one; the two per-level counters are recomputed"

        Design: Difficulty/compensating_invariant/cc44_pair_conserves_certified_days
        """
        ctx = self._setup_concurred_cc44_with_auth(api, approve_first=True,
                                                   mrn="MRN-INV1")
        before = get_case(ctx["case"]["id"])
        assert before["certified_day_count"] == 3
        assert before["certified_inpatient_day_count"] == 3
        assert before["certified_observation_day_count"] == 0

        committee_cc44(ctx["cc44"]["id"], ctx["advisor"]["id"])
        after = get_case(ctx["case"]["id"])
        assert after["certified_day_count"] == 3, (
            "the retag conserves the total certified day count")
        assert after["certified_inpatient_day_count"] == 0
        assert after["certified_observation_day_count"] == 3
        assert_certified_counters_consistent(after)

    def test_cc44_rescind_restores_certified_split(self, api):
        """PRD §3.6: "the re-tagged certified intervals are restored to `INPATIENT` — total certified days again conserved across the approve-and-rescind pair — the per-level counters are recomputed"

        Design: Difficulty/compensating_invariant/cc44_pair_conserves_certified_days
        """
        ctx = self._setup_concurred_cc44_with_auth(api, approve_first=True,
                                                   mrn="MRN-INV1R")
        committee_cc44(ctx["cc44"]["id"], ctx["advisor"]["id"])
        validate_success(api.cc44_rescind(
            ctx["cc44"]["id"],
            {"rescind_reason": "Criteria requalified after new imaging"},
            DIRECTOR))

        case = get_case(ctx["case"]["id"])
        assert case["certified_day_count"] == 3
        assert case["certified_inpatient_day_count"] == 3
        assert case["certified_observation_day_count"] == 0
        assert case["current_admission_status"] == "INPATIENT"
        assert get_auth(ctx["auth"]["id"])["status"] == "APPROVED", (
            "only interval tags moved; the approved request itself is untouched")


class TestCommitteeGates:
    def _setup_rejected_cc44_with_attending_advisor(self, api):
        """CC44 already terminally REJECTED by a second advisor; the case
        attending is itself registered as an advisor."""
        payer = make_payer()
        attending_advisor = make_physician(is_advisor=True,
                                           full_name="Dr. AttendAdvisor")
        advisor = make_advisor()
        case = make_case(payer["id"], attending_advisor["id"],
                         patient_mrn="MRN-PP1")
        submit_review(make_review(case["id"])["id"])
        cc44 = make_cc44(case["id"])
        concur_cc44(cc44["id"], attending_advisor["id"], "CONCUR")
        rejected = committee_cc44(cc44["id"], advisor["id"], "REJECT")
        assert rejected["status"] == "REJECTED"
        return {"case": case, "attending_advisor": attending_advisor,
                "advisor": advisor, "cc44": rejected}

    def test_cc44_committee_terminal_state_beats_sod(self, api):
        """PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."
        PRD §2.5: "A request that would trip two gates is reported against the earliest gate in this ordering — so, for instance, an unauthenticated caller with a malformed body receives `ERR_UNAUTHENTICATED`, and a stale-version create on a case that is also closed receives `ERR_CASE_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/cc44_committee_terminal_state_beats_sod
        """
        ctx = self._setup_rejected_cc44_with_attending_advisor(api)
        # The caller is simultaneously the case attending (SoD violation) and
        # the request is already terminally REJECTED (state violation): the
        # state gate, earlier in the pipeline, must report.
        resp = api.cc44_committee_review(
            ctx["cc44"]["id"], cc44_committee_payload("APPROVE"),
            make_advisor_headers(ctx["attending_advisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_cc44(ctx["case"]["id"], ctx["cc44"]["id"])["status"] == "REJECTED"

    def test_cc44_terminal_rejection_has_no_side_effects(self, api):
        """PRD §3.6: "On `REJECT`, the `committee_reviewer_id` is set, the case is unchanged, the request reaches terminal `REJECTED`, and `CC44_REJECTED` is appended."
        PRD §2.5: "State-machine legality — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/cc44_committee_terminal_state_beats_sod
        """
        ctx = self._setup_rejected_cc44_with_attending_advisor(api)
        resp = api.cc44_committee_review(
            ctx["cc44"]["id"], cc44_committee_payload("APPROVE"),
            make_advisor_headers(ctx["attending_advisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        cc44 = get_cc44(ctx["case"]["id"], ctx["cc44"]["id"])
        assert cc44["status"] == "REJECTED"
        assert cc44["committee_reviewer_id"] == ctx["advisor"]["id"], (
            "the rejected committee call must not rewrite the reviewer")
        assert get_case(ctx["case"]["id"])["current_admission_status"] == "INPATIENT"

    def test_cc44_rescind_requires_approved_state(self, api):
        """PRD §3.6: "while the case is open, rescission from any state other than `APPROVED` fails state-machine legality."

        Design: Corner/state_machines/cc44_rescind_requires_approved_state
        """
        ctx = setup_cc44_open(patient_mrn="MRN-RSC")
        resp = api.cc44_rescind(ctx["cc44"]["id"],
                                {"rescind_reason": "premature rescind"},
                                DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_cc44(ctx["case"]["id"],
                        ctx["cc44"]["id"])["status"] == "CONCURRENCE_PENDING"


class TestCommitteeRoleEnforcement:
    def test_attending_cannot_committee_review_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/attending_cannot_committee_review_forbidden
        """
        ctx = setup_cc44_committee_pending(patient_mrn="MRN-RBAC1")
        resp = api.cc44_committee_review(
            ctx["cc44"]["id"], cc44_committee_payload("APPROVE"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_cc44(ctx["case"]["id"],
                        ctx["cc44"]["id"])["status"] == "COMMITTEE_PENDING"

    def test_advisor_cannot_concur_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.6: "Concurrence belongs to the attending of record — again an attending-ownership action."

        Design: Corner/rbac/advisor_cannot_concur_forbidden
        """
        ctx = setup_cc44_open(patient_mrn="MRN-RBAC3")
        resp = api.cc44_concurrence(
            ctx["cc44"]["id"], {"decision": "CONCUR"},
            make_advisor_headers(ctx["advisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_cc44(ctx["case"]["id"],
                        ctx["cc44"]["id"])["attending_concurrence"] == "PENDING"
