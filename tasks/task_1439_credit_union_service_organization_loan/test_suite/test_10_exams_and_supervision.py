"""Regulatory exams: window adjacency, finding remediation cycle, segregation of
duties, and the finalize cascade that suspends a CUSO (PRD §3.3, §3.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    register_credit_union, register_cuso, create_active_agreement,
    create_open_offering, create_draft_agreement,
    open_exam, record_finding, finalize_exam,
    setup_exam_with_finding, suspend_cuso_with_open_critical,
    make_cuso_officer_headers, make_regulator_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestExamWindowHalfOpenAdjacency:
    def test_adjacent_exam_window_allowed(self, api):
        """PRD §3.9: "Windows for the same CUSO must not overlap: a new exam whose half-open window intersects an existing exam's window is rejected with `ERR_EXAM_WINDOW_OVERLAP`, though adjacency is allowed — one exam's start may equal another's end."

        Design: Difficulty/resource_temporal_overlap/exam_window_half_open_adjacency
        """
        cuso = register_cuso()
        open_exam(cuso["id"], start_date="2026-03-01T00:00:00Z",
                  end_date="2026-03-15T00:00:00Z")
        # E2 starts exactly when E1 ends: half-open adjacency is allowed.
        e2 = open_exam(cuso["id"], start_date="2026-03-15T00:00:00Z",
                       end_date="2026-03-31T00:00:00Z")
        assert e2["status"] == "IN_PROGRESS"

    def test_overlapping_exam_window_rejected(self, api):
        """PRD §3.9: "Windows for the same CUSO must not overlap: a new exam whose half-open window intersects an existing exam's window is rejected with `ERR_EXAM_WINDOW_OVERLAP`, though adjacency is allowed — one exam's start may equal another's end."

        Design: Difficulty/resource_temporal_overlap/exam_window_half_open_adjacency
        """
        cuso = register_cuso()
        open_exam(cuso["id"], start_date="2026-03-01T00:00:00Z",
                  end_date="2026-03-15T00:00:00Z")
        res = api.create_exam(
            {"cuso_id": cuso["id"], "start_date": "2026-03-14T00:00:00Z",
             "end_date": "2026-03-20T00:00:00Z"},
            make_regulator_headers("reg-1"))
        validate_error(res, ApiErrorId.ERR_EXAM_WINDOW_OVERLAP)


class TestExamFinalizeCriticalCascade:
    def _setup_cuso_with_open_critical_and_active_pool(self, api):
        """CUSO with an ACTIVE agreement and an OPEN offering, plus an
        IN_PROGRESS exam carrying one OPEN CRITICAL finding."""
        originator = register_credit_union(charter_number="CU-ORIG", cu_type="ORIGINATOR")
        cuso = register_cuso()
        agreement = create_active_agreement(cuso["id"], originator["id"])
        offering = create_open_offering(agreement["id"], originator["id"])
        exam = open_exam(cuso["id"], regulator_id="reg-1")
        finding = record_finding(exam["id"], severity="CRITICAL",
                                 description="Missing participation agreements",
                                 regulator_id="reg-1")
        return {"cuso": cuso, "agreement": agreement, "offering": offering,
                "exam": exam, "finding": finding}

    def test_finalize_with_open_critical_suspends_cuso(self, api):
        """PRD §3.9: "Finalization is the supervisory tripwire: if the exam carries at least one finding with severity `CRITICAL` still in `OPEN`, `VERIFYING`, or `REOPENED`, the CUSO flips from `ACTIVE` to `SUSPENDED`, every `ACTIVE` servicing agreement of that CUSO flips to `SUSPENDED`, and every `OPEN` offering under those agreements flips to `SUSPENDED` — certificate records are not mutated, but funding and opening are gated while the offering is suspended."

        Design: Difficulty/transitive_cascade/exam_finalize_critical_cascade
        """
        ctx = self._setup_cuso_with_open_critical_and_active_pool(api)
        exam = validate_success(api.finalize_exam(ctx["exam"]["id"],
                                                  make_regulator_headers("reg-2")), 200)
        assert exam["status"] == "FINALIZED"
        cuso = validate_success(api.get_cuso(ctx["cuso"]["id"], ADMIN), 200)
        assert cuso["status"] == "SUSPENDED"

    def test_finalize_cascade_reaches_agreement_and_offering(self, api):
        """PRD §3.9: "Finalization is the supervisory tripwire: if the exam carries at least one finding with severity `CRITICAL` still in `OPEN`, `VERIFYING`, or `REOPENED`, the CUSO flips from `ACTIVE` to `SUSPENDED`, every `ACTIVE` servicing agreement of that CUSO flips to `SUSPENDED`, and every `OPEN` offering under those agreements flips to `SUSPENDED` — certificate records are not mutated, but funding and opening are gated while the offering is suspended."
        PRD §2.8: "First, the supervisory cascade: a CUSO dropping to `SUSPENDED` drags every one of its `ACTIVE` servicing agreements to `SUSPENDED`, and each such agreement's `OPEN` offerings drop to `SUSPENDED` in turn; when the CUSO recovers to `ACTIVE`, the same chain unwinds — `SUSPENDED` agreements return to `ACTIVE` and their `SUSPENDED` offerings return to `OPEN`."

        Design: Difficulty/transitive_cascade/exam_finalize_critical_cascade
        """
        ctx = self._setup_cuso_with_open_critical_and_active_pool(api)
        finalize_exam(ctx["exam"]["id"], regulator_id="reg-2")
        agreement = validate_success(
            api.get_servicing_agreement(ctx["agreement"]["id"], ADMIN), 200)
        assert agreement["status"] == "SUSPENDED"
        offering = validate_success(api.get_offering(ctx["offering"]["id"], ADMIN), 200)
        assert offering["status"] == "SUSPENDED"


class TestExamFindingReopenCycle:
    def test_failed_verification_loops_back_to_verifying(self, api):
        """PRD §3.9: "Remediation is submitted by the `CUSOOfficer` who owns the exam's CUSO (the caller's `X-User-ID` must equal the exam's `cuso_id`, else `ERR_NOT_RESOURCE_OWNER`), supplying `remediation_notes`; this moves a finding from `OPEN`, or from `REOPENED` after a failed verification, to `VERIFYING` and stores the latest notes."
        PRD §3.9: "Verifying with `verification_passed` false moves the finding to `REOPENED`, returning it to the remediation loop."

        Design: Difficulty/non_linear_state_machine/exam_finding_reopen_cycle
        """
        ctx = setup_exam_with_finding(severity="CRITICAL", regulator_id="reg-1")
        cuso, finding = ctx["cuso"], ctx["finding"]
        officer = make_cuso_officer_headers(cuso["id"])
        reg2 = make_regulator_headers("reg-2")

        f1 = validate_success(api.submit_remediation(
            finding["id"], {"remediation_notes": "Plan v1"}, officer), 200)
        assert f1["status"] == "VERIFYING"
        f2 = validate_success(api.verify_finding(
            finding["id"], {"verification_passed": False}, reg2), 200)
        assert f2["status"] == "REOPENED"
        f3 = validate_success(api.submit_remediation(
            finding["id"], {"remediation_notes": "Plan v2"}, officer), 200)
        assert f3["status"] == "VERIFYING"

    def test_cycle_ends_closed_and_cuso_stays_active(self, api):
        """PRD §3.9: "Verifying with `verification_passed` true moves the finding from `VERIFYING` to `CLOSED`, its terminal state, and recomputes the CUSO's `open_critical_finding_count`; when the closed finding was `CRITICAL`, the count has fallen to zero, and the CUSO is `SUSPENDED`, the CUSO is reinstated to `ACTIVE`, cascading its `SUSPENDED` agreements back to `ACTIVE` and their `SUSPENDED` offerings back to `OPEN`."

        Design: Difficulty/non_linear_state_machine/exam_finding_reopen_cycle
        """
        ctx = setup_exam_with_finding(severity="CRITICAL", regulator_id="reg-1")
        cuso, finding = ctx["cuso"], ctx["finding"]
        officer = make_cuso_officer_headers(cuso["id"])
        reg2 = make_regulator_headers("reg-2")

        api.submit_remediation(finding["id"], {"remediation_notes": "Plan v1"}, officer)
        api.verify_finding(finding["id"], {"verification_passed": False}, reg2)
        api.submit_remediation(finding["id"], {"remediation_notes": "Plan v2"}, officer)
        f4 = validate_success(api.verify_finding(
            finding["id"], {"verification_passed": True}, reg2), 200)
        assert f4["status"] == "CLOSED"
        # The exam was never finalized with an open CRITICAL finding, so the CUSO
        # is never suspended.
        cuso_after = validate_success(api.get_cuso(cuso["id"], ADMIN), 200)
        assert cuso_after["status"] == "ACTIVE"


class TestFindingSegregationOfDuties:
    def test_verifier_must_differ_from_recorder(self, api):
        """PRD §3.9: "Verification is performed by a `RegulatorUser` who must not be the finding's recorder: a verifier whose `X-User-ID` equals the finding's `recorded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/finding_verify_same_recorder_segregation
        """
        ctx = setup_exam_with_finding(severity="HIGH", regulator_id="reg-1")
        cuso, finding = ctx["cuso"], ctx["finding"]
        officer = make_cuso_officer_headers(cuso["id"])
        validate_success(api.submit_remediation(
            finding["id"], {"remediation_notes": "Fixed posting job"}, officer), 200)

        res = api.verify_finding(finding["id"], {"verification_passed": True},
                                 make_regulator_headers("reg-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = validate_success(api.verify_finding(
            finding["id"], {"verification_passed": True},
            make_regulator_headers("reg-2")), 200)
        assert ok["status"] == "CLOSED"


class TestAgreementCreateOnSuspendedCuso:
    def test_agreement_create_on_suspended_cuso_rejected(self, api):
        """PRD §3.3: "The CUSO must be `ACTIVE` at creation, else the request is rejected with `ERR_CUSO_SUSPENDED`; a new agreement starts in `DRAFT`."
        PRD §3.9: "Finalization is the supervisory tripwire: if the exam carries at least one finding with severity `CRITICAL` still in `OPEN`, `VERIFYING`, or `REOPENED`, the CUSO flips from `ACTIVE` to `SUSPENDED`, every `ACTIVE` servicing agreement of that CUSO flips to `SUSPENDED`, and every `OPEN` offering under those agreements flips to `SUSPENDED` — certificate records are not mutated, but funding and opening are gated while the offering is suspended."

        Design: Corner/errors/agreement_create_on_suspended_cuso_rejected
        """
        originator = register_credit_union(charter_number="CU-ORIG", cu_type="ORIGINATOR")
        cuso = register_cuso()
        suspend_cuso_with_open_critical(cuso["id"])
        cuso_after = validate_success(api.get_cuso(cuso["id"], ADMIN), 200)
        assert cuso_after["status"] == "SUSPENDED"

        res = api.create_servicing_agreement(
            {"cuso_id": cuso["id"], "originator_id": originator["id"],
             "servicing_fee_bps": 25, "remittance_due_day": 15,
             "day_count_convention": "THIRTY_360"},
            make_cuso_officer_headers(cuso["id"]))
        validate_error(res, ApiErrorId.ERR_CUSO_SUSPENDED)
