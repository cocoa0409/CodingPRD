"""Evaluations (immutable records, dual-variant ratings, probation cascade) and the
engagement-termination cascade."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_evaluation, assert_expert, ApiErrorId,
    create_expert, create_case, open_request, screen_candidate,
    create_draft_engagement, propose_engagement, sign_engagement,
    fund_retainer, close_engagement, create_evaluation,
    create_report, submit_report, finalize_report,
    create_confirmed_schedule, create_document, deliver_document,
    submit_invoice,
    setup_scenario, setup_active_engagement, setup_closed_engagement, set_clock,
    TEST_USERS, make_expert_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
CONFLICT = TEST_USERS["conflict_analyst_headers"]


class TestEvaluationRecord:

    def test_evaluation_is_immutable_record(self, api):
        """PRD §2.4: "The Evaluation record is the single exception. Evaluations are
        terminal records, immutable once created, and carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from an Evaluation."
        PRD §3.8: "The record's `expert_id` is denormalized from the engagement, and
        `evaluated_at` stamps the logical clock at creation".

        Design: Corner/entities/evaluation_immutable_record
        """
        sc = setup_closed_engagement()
        evaluation = validate_success(api.create_evaluation(
            sc["engagement"]["id"], {"overall_score": 4.5, "comments": "solid"}, CM), 201)
        assert_evaluation(evaluation)
        assert evaluation["overall_score"] == 4.5
        assert evaluation["expert_id"] == sc["expert"]["id"]
        assert evaluation["engagement_id"] == sc["engagement"]["id"]
        assert evaluation["evaluated_at"] is not None
        assert "updated_at" not in evaluation
        assert "version" not in evaluation


class TestRatingDualVariant:

    def _closed_engagement_for(self, api, expert, trial_date, report_deadline, score):
        """Closed engagement for `expert` on a fresh case; records evaluation `score`."""
        case = create_case(trial_date=trial_date, report_deadline=report_deadline)
        request = open_request(case["id"], specialty_area=expert["specialty_area"])
        screen_candidate(request["id"], expert["id"])
        eng = create_draft_engagement(request["id"], expert["id"])
        eng = propose_engagement(eng["id"])
        eng = sign_engagement(eng["id"], expert["id"])
        eng = fund_retainer(eng["id"], eng["retainer_cents"])
        eng = close_engagement(eng["id"])
        evaluation = create_evaluation(eng["id"], score)
        return {"engagement": eng, "evaluation": evaluation, "case": case}

    def test_simple_and_decayed_variants_diverge(self, api):
        """PRD §3.1: "`rating_simple` is the unweighted mean of the evaluations'
        `overall_score` values, rounded half-up to two decimal places" and "an evaluation's
        age in days is the whole number of days between its `evaluated_at` instant and the
        current logical-clock time, discarding any partial day, and its weight is one-half
        raised to the number of complete 180-day periods contained in that age — an
        evaluation under 180 days old weighs 1, one between 180 and 359 days old weighs
        one-half" and "The decayed rating is the sum of each evaluation's weight times its
        `overall_score`, divided by the sum of the weights, rounded half-up to two decimal
        places".

        Design: Difficulty/dual_variant_calc/expert_rating_simple_vs_decayed
        """
        expert = create_expert(full_name="B Hale", specialty_area="biomech")
        # Eval 5.0 at default clock (2026-05-01).
        self._closed_engagement_for(api, expert, "2026-09-01T00:00:00Z",
                                    "2026-07-01T17:00:00Z", 5.0)
        # Advance 200 days; eval 1.0.
        set_clock("2026-11-17T00:00:00Z")
        self._closed_engagement_for(api, expert, "2027-03-01T00:00:00Z",
                                    "2027-01-15T17:00:00Z", 1.0)

        fetched = validate_success(api.get_expert(expert["id"], CM), 200)
        assert_expert(fetched)
        assert fetched["evaluation_count"] == 2
        assert fetched["rating_simple"] == pytest.approx(3.0, abs=1e-9)
        # (0.5*5.0 + 1.0*1.0) / (0.5 + 1.0) = 3.5/1.5 = 2.33 (half-up 2dp)
        assert fetched["rating_decayed"] == pytest.approx(2.33, abs=1e-9)

    def test_probation_trigger_consumes_only_the_decayed_variant(self, api):
        """PRD §3.1: "An automatic demotion fires the moment a newly recorded evaluation
        leaves an `ACTIVE` expert with at least two evaluations and a `rating_decayed`
        below 3.0: the expert's standing moves `ACTIVE` → `PROBATION`". The simple variant
        here (3.0) would not trip the threshold; only the decayed variant (2.33) does.

        Design: Difficulty/dual_variant_calc/expert_rating_simple_vs_decayed
        """
        expert = create_expert(full_name="B Hale", specialty_area="biomech")
        self._closed_engagement_for(api, expert, "2026-09-01T00:00:00Z",
                                    "2026-07-01T17:00:00Z", 5.0)
        set_clock("2026-11-17T00:00:00Z")
        self._closed_engagement_for(api, expert, "2027-03-01T00:00:00Z",
                                    "2027-01-15T17:00:00Z", 1.0)

        fetched = validate_success(api.get_expert(expert["id"], CM), 200)
        assert fetched["rating_simple"] == pytest.approx(3.0, abs=1e-9)
        assert fetched["rating_decayed"] == pytest.approx(2.33, abs=1e-9)
        assert fetched["roster_status"] == "PROBATION", (
            "decayed 2.33 < 3.0 with 2 evaluations triggers automatic demotion")


class TestProbationCascade:

    def _setup_cascade(self, api):
        """Expert with two closed engagements (eval 5.0 at default clock, clock +200d);
        a third case whose SCREENING request holds this expert's PENDING check."""
        expert = create_expert(full_name="H Paz", specialty_area="accident")

        def closed_engagement(trial, deadline, score=None):
            case = create_case(trial_date=trial, report_deadline=deadline)
            request = open_request(case["id"], specialty_area="accident")
            screen_candidate(request["id"], expert["id"])
            eng = create_draft_engagement(request["id"], expert["id"])
            eng = propose_engagement(eng["id"])
            eng = sign_engagement(eng["id"], expert["id"])
            eng = fund_retainer(eng["id"], eng["retainer_cents"])
            eng = close_engagement(eng["id"])
            if score is not None:
                create_evaluation(eng["id"], score)
            return eng

        closed_engagement("2026-09-01T00:00:00Z", "2026-07-01T17:00:00Z", score=5.0)
        set_clock("2026-11-17T00:00:00Z")
        eng2 = closed_engagement("2027-03-01T00:00:00Z", "2027-01-15T17:00:00Z")

        # Third case: request in SCREENING with a PENDING conflict check for this expert.
        case3 = create_case(trial_date="2027-03-01T00:00:00Z",
                            report_deadline="2027-01-15T17:00:00Z")
        request3 = open_request(case3["id"], specialty_area="accident")
        pending_check = get_success_data(api.create_conflict_check(
            request3["id"], {"expert_id": expert["id"], "adverse_parties": ["V Corp"]},
            CONFLICT))
        req3 = validate_success(api.get_engagement_request(request3["id"], CM), 200)
        assert req3["status"] == "SCREENING"
        return expert, eng2, request3, pending_check

    def test_evaluation_triggers_probation(self, api):
        """PRD §3.1: "An automatic demotion fires the moment a newly recorded evaluation
        leaves an `ACTIVE` expert with at least two evaluations and a `rating_decayed`
        below 3.0: the expert's standing moves `ACTIVE` → `PROBATION`, its `version`
        increments, and a cascade runs."

        Design: Difficulty/transitive_cascade/evaluation_low_rating_probation_cascade
        """
        expert, eng2, request3, pending_check = self._setup_cascade(api)

        create_evaluation(eng2["id"], 1.0)

        fetched = validate_success(api.get_expert(expert["id"], CM), 200)
        assert fetched["roster_status"] == "PROBATION", "rating recompute drives the auto-transition"
        assert fetched["rating_decayed"] == pytest.approx(2.33, abs=1e-9)
        assert fetched["evaluation_count"] == 2

    def test_cascade_flags_pending_checks_and_reverts_request(self, api):
        """PRD §3.1: "Every conflict check still `PENDING` for that expert becomes
        `FLAGGED` with its `resolution_rationale` set to `ROSTER_PROBATION`. Any sourcing
        request still in `SCREENING` whose conflict checks have thereby all landed
        `FLAGGED` — and in which no expert any longer satisfies the readiness predicate of
        §3.2 — reverts from `SCREENING` to `OPEN`."

        Design: Difficulty/transitive_cascade/evaluation_low_rating_probation_cascade
        """
        expert, eng2, request3, pending_check = self._setup_cascade(api)

        create_evaluation(eng2["id"], 1.0)

        checks = validate_success(api.list_request_conflict_checks(request3["id"], CONFLICT), 200)
        flagged = [c for c in checks if c["id"] == pending_check["id"]]
        assert flagged, "pending check must still exist"
        assert flagged[0]["status"] == "FLAGGED", "probation flags PENDING checks"
        assert flagged[0]["resolution_rationale"] == "ROSTER_PROBATION"

        req3 = validate_success(api.get_engagement_request(request3["id"], CM), 200)
        assert req3["status"] == "OPEN", "no qualified candidate remains: SCREENING reverts to OPEN"


class TestTerminationCascade:

    def _setup_terminable(self, api):
        """ACTIVE engagement (rate 40000, retainer 100000 funded); report DISCLOSED (case
        TRIAL_PREP); one CONFIRMED deposition; one DELIVERED WORK_PRODUCT document; one
        SUBMITTED invoice (50000)."""
        sc = setup_active_engagement(engagement_overrides={"retainer_cents": 100_000})
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]

        report = create_report(gid, title="Damages", report_type="DAMAGES")
        submit_report(report["id"], eid)
        finalize_report(report["id"])
        report = validate_success(api.disclose_report(report["id"], CM), 200)

        schedule = create_confirmed_schedule(gid, kind="DEPOSITION",
                                             start_at="2026-06-15T10:00:00Z",
                                             end_at="2026-06-15T12:00:00Z", estimated_hours=4)

        document = create_document(gid, privilege_tier="WORK_PRODUCT",
                                   title="Claim file", content_ref="s3://bucket/doc1")
        document = deliver_document(document["id"])

        invoice = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 1.25}], 50_000)

        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert case["status"] == "TRIAL_PREP"
        sc.update({"report": report, "schedule": schedule, "document": document,
                   "invoice": invoice})
        return sc

    def test_terminate_withdraws_report_and_reverts_case(self, api):
        """PRD §3.8: "Every report of the engagement in `DRAFT`, `IN_REVIEW`,
        `REVISION_REQUESTED`, `FINALIZED`, or `DISCLOSED` is withdrawn to `WITHDRAWN`; and
        when the withdrawn report was the case's only `DISCLOSED` one — that is, when no
        other disclosed report remains across the case's engagements — the case itself
        reverts `TRIAL_PREP` → `DISCOVERY`."

        Design: Difficulty/transitive_cascade/engagement_termination_full_cascade
        """
        sc = self._setup_terminable(api)
        terminated = validate_success(api.terminate_engagement(
            sc["engagement"]["id"], {"reason": "settlement"}, CM), 200)
        assert terminated["status"] == "TERMINATED"

        reports = validate_success(api.list_reports(sc["engagement"]["id"], CM), 200)
        report = [r for r in reports if r["id"] == sc["report"]["id"]][0]
        assert report["status"] == "WITHDRAWN", "cascade link 1: DISCLOSED report withdrawn"

        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert case["status"] == "DISCOVERY", (
            "cascade link 2: TRIAL_PREP reverts — no DISCLOSED report remains")

    def test_terminate_cancels_recalls_rejects_and_refunds(self, api):
        """PRD §3.8: "Every testimony session of the engagement still in `PROPOSED` or
        `CONFIRMED` is cancelled — with no cancellation fee on this path, regardless of the
        clock." PRD §3.8: "Every document production still in `REQUESTED` or `DELIVERED` is
        recalled to `RECALLED`. Every invoice in `SUBMITTED` or `DISPUTED` is rejected to
        `REJECTED`. The remaining retainer — funded minus drawn minus any amount already
        refunded — moves into `retainer_refunded_cents`."

        Design: Difficulty/transitive_cascade/engagement_termination_full_cascade
        """
        sc = self._setup_terminable(api)
        validate_success(api.terminate_engagement(
            sc["engagement"]["id"], {"reason": "settlement"}, CM), 200)

        schedules = validate_success(api.list_engagement_schedules(sc["engagement"]["id"], CM), 200)
        schedule = [s for s in schedules if s["id"] == sc["schedule"]["id"]][0]
        assert schedule["status"] == "CANCELLED"
        assert schedule["cancellation_fee_cents"] == 0, "firm-initiated termination: no fee"

        docs = validate_success(api.list_document_productions(sc["engagement"]["id"], CM), 200)
        doc = [d for d in docs if d["id"] == sc["document"]["id"]][0]
        assert doc["status"] == "RECALLED"

        invoices = validate_success(
            api.list_invoices(sc["engagement"]["id"], TEST_USERS["billing_reviewer_headers"]), 200)
        invoice = [i for i in invoices if i["id"] == sc["invoice"]["id"]][0]
        assert invoice["status"] == "REJECTED"

        engagement = validate_success(api.get_engagement(sc["engagement"]["id"], CM), 200)
        assert engagement["retainer_refunded_cents"] == 100_000
        assert engagement["retainer_remaining_cents"] == 0
