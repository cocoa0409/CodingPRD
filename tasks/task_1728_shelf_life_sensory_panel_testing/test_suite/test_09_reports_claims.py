"""Study reports, recommendations, and claim substantiation: attachment gates,
the review loop, segregation of duties, claim evidence, release, and the
supersession cascade."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    attach_and_submit_report,
    create_client,
    create_draft_report,
    create_draft_study,
    create_claim_payload,
    create_lab_result_payload,
    get_report,
    get_study,
    get_client,
    get_success_data,
    list_sample_units,
    make_client_headers,
    make_qa_headers,
    make_scientist_headers,
    propose_and_accept_recommendation,
    propose_recommendation,
    pull_units,
    setup_client_review_report,
    setup_reporting_study,
    setup_study_in_analysis,
    setup_study_in_progress,
    walk_report_to_client_review,
    validate_error,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
AN = TEST_USERS["analyst_headers"]

AUTHOR = "sci-author"
QA1 = "qa-1"


def _client_review_report_with_tp(api, day_index=10):
    """REPORTING study (one SKIPPED time point at the given day) + the control
    arm's ACCEPTED recommendation + a report walked to CLIENT_REVIEW."""
    env = setup_study_in_analysis(day_indexes=(day_index,))
    rec = propose_and_accept_recommendation(env["study"]["id"],
                                            env["arms"][0]["id"])
    report = create_draft_report(env["study"]["id"])
    attach_and_submit_report(report["id"], rec["id"])
    walk_report_to_client_review(report["id"])
    return env, rec, report


def _release_ready_scenario(api):
    """REPORTING study with a surviving RETAIN unit; report in CLIENT_REVIEW
    with one PENDING SHELF_LIFE_DAYS claim (42 days vs fallback 42)."""
    env = setup_study_in_progress()
    study_id, arm_id = env["study"]["id"], env["arms"][0]["id"]
    tp_id, chamber_id = env["time_points"][0]["id"], env["chamber"]["id"]
    pull_units(tp_id, chamber_id, arm_id, quantity=1, unit_purpose="EVALUATION")
    pull_units(tp_id, chamber_id, arm_id, quantity=1, unit_purpose="RETAIN")
    get_success_data(api.skip_time_point(tp_id, SCI))
    get_success_data(api.close_fieldwork(study_id, SCI))
    rec = propose_and_accept_recommendation(study_id, arm_id)
    report = create_draft_report(study_id, author=AUTHOR)
    get_success_data(api.attach_recommendation(report["id"], rec["id"],
                                               make_scientist_headers(AUTHOR)))
    claim = get_success_data(api.create_claim(
        create_claim_payload(report["id"], "SHELF_LIFE_DAYS",
                             "Keeps 42 days", 42),
        make_scientist_headers(AUTHOR)))
    get_success_data(api.submit_report(report["id"],
                                       make_scientist_headers(AUTHOR)))
    walk_report_to_client_review(report["id"])
    env.update({"recommendation": rec, "report": report, "claim": claim})
    return env


class TestAttachmentAndSubmitGates:
    def test_attach_non_accepted_or_foreign_recommendation(self, api):
        """PRD §3.7: "attachment requires the report to be `DRAFT` (else `ERR_INVALID_REPORT_STATE`), the recommendation to be `ACCEPTED` (else `ERR_RECO_NOT_PROPOSED`), and the recommendation's study to match the report's study (else `ERR_REPORT_STUDY_MISMATCH`)"

        Design: Corner/validations/attach_non_accepted_or_foreign_recommendation
        """
        env_a = setup_study_in_analysis()
        rec_a = propose_recommendation(env_a["study"]["id"],
                                       env_a["arms"][0]["id"])  # stays PROPOSED
        env_b = setup_study_in_analysis(arm_variants=("MAP",))
        rec_b = propose_and_accept_recommendation(env_b["study"]["id"],
                                                  env_b["arms"][0]["id"])
        report = create_draft_report(env_a["study"]["id"])

        author = make_scientist_headers(AUTHOR)
        validate_error(api.attach_recommendation(report["id"], rec_a["id"],
                                                 author),
                       ApiErrorId.ERR_RECO_NOT_PROPOSED, 409)
        validate_error(api.attach_recommendation(report["id"], rec_b["id"],
                                                 author),
                       ApiErrorId.ERR_REPORT_STUDY_MISMATCH, 422)
        assert get_report(report["id"])["pinned_recommendation_id"] is None

    def test_report_submit_without_recommendation(self, api):
        """PRD §3.7: "it requires the report to be `DRAFT` (else `ERR_INVALID_REPORT_STATE`), requires a pinned recommendation that is `ACCEPTED` (else `ERR_NO_ACCEPTED_RECOMMENDATION`), and requires `requires_revision` to be false (else `ERR_REPORT_REQUIRES_REVISION`)"

        Design: Corner/validations/report_submit_without_recommendation
        """
        env = setup_study_in_analysis()
        report = create_draft_report(env["study"]["id"])
        validate_error(api.submit_report(report["id"],
                                         make_scientist_headers(AUTHOR)),
                       ApiErrorId.ERR_NO_ACCEPTED_RECOMMENDATION, 409)
        assert get_report(report["id"])["status"] == "DRAFT"


class TestReviewLoop:
    def test_report_revision_loop_cycle(self, api):
        """PRD §3.7: "A softer path, the QA return, sends `INTERNAL_REVIEW → DRAFT` and increments `revision_count` by 1"
        PRD §3.7: "A `Client` may request changes on a report in `CLIENT_REVIEW` — only when the acting `X-User-ID` equals the study's `client_id` (else `ERR_FORBIDDEN_ROLE`) — which returns it `CLIENT_REVIEW → DRAFT`, clears `requires_revision` to false, and increments `revision_count` by 1."

        Design: Corner/state_machines/report_revision_loop_cycle
        """
        env = setup_reporting_study()
        report = create_draft_report(env["study"]["id"])
        submitted = attach_and_submit_report(report["id"],
                                             env["recommendations"][0]["id"])
        assert submitted["status"] == "INTERNAL_REVIEW"

        returned = validate_success(api.qa_return_report(report["id"],
                                                         make_qa_headers(QA1)))
        assert returned["status"] == "DRAFT"
        assert returned["revision_count"] == 1

        resubmitted = validate_success(api.submit_report(
            report["id"], make_scientist_headers(AUTHOR)))
        assert resubmitted["status"] == "INTERNAL_REVIEW"
        approved = validate_success(api.qa_approve_report(report["id"],
                                                          make_qa_headers(QA1)))
        assert approved["status"] == "CLIENT_REVIEW"

        bounced = validate_success(api.request_changes(
            report["id"], make_client_headers(env["client"]["id"])))
        assert bounced["status"] == "DRAFT"
        assert bounced["revision_count"] == 2, (
            "each re-entry into DRAFT increments the counter")
        assert bounced["requires_revision"] is False

    def test_report_resubmit_and_lab_result_state_gates(self, api):
        """PRD §3.7: "it requires the report to be `DRAFT` (else `ERR_INVALID_REPORT_STATE`)"
        PRD §3.6: "The study must be `IN_PROGRESS`, `ANALYSIS`, or `REPORTING` (else `ERR_INVALID_STUDY_STATE`)."

        Design: Corner/state_machines/report_resubmit_and_lab_result_state_gates
        """
        env = setup_reporting_study()
        report = create_draft_report(env["study"]["id"])
        attach_and_submit_report(report["id"], env["recommendations"][0]["id"])
        validate_error(api.submit_report(report["id"],
                                         make_scientist_headers(AUTHOR)),
                       ApiErrorId.ERR_INVALID_REPORT_STATE, 409)
        assert get_report(report["id"])["status"] == "INTERNAL_REVIEW"

        # a DRAFT study (fieldwork never started) rejects lab results outright
        client = create_client()
        study_b = create_draft_study(client["id"], product_name="Vinegar B")
        arm_b = add_arm(study_b["id"], "MAP", is_control=True)
        tp_b = add_time_point(study_b["id"], 0)
        validate_error(api.create_lab_result(
            create_lab_result_payload(study_b["id"], arm_b["id"], tp_b["id"],
                                      "WATER_ACTIVITY", 0.5), AN),
            ApiErrorId.ERR_INVALID_STUDY_STATE, 409)


class TestSegregationAndOwnership:
    def test_client_cannot_request_changes_on_others_report(self, api):
        """PRD §3.7: "A `Client` may request changes on a report in `CLIENT_REVIEW` — only when the acting `X-User-ID` equals the study's `client_id` (else `ERR_FORBIDDEN_ROLE`)"
        PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks compare the study's `client_id` on the relevant report chain to `X-User-ID`."

        Design: Corner/rbac/client_cannot_request_changes_on_others_report
        """
        env = setup_client_review_report()
        other_client = create_client(name="Other B")

        validate_error(api.request_changes(
            env["report"]["id"], make_client_headers(other_client["id"])),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        bounced = validate_success(api.request_changes(
            env["report"]["id"], make_client_headers(env["client"]["id"])))
        assert bounced["status"] == "DRAFT"
        assert bounced["revision_count"] == 1

    def test_qa_cannot_approve_own_authored_report(self, api):
        """PRD §3.7: "in both cases the acting `QAOfficer`'s `X-User-ID` must differ from the report's `author_user_id` — an officer may never approve or reject a report they authored, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/qa_cannot_approve_own_authored_report
        """
        env = setup_reporting_study()
        report = create_draft_report(env["study"]["id"], author=AUTHOR)
        attach_and_submit_report(report["id"], env["recommendations"][0]["id"],
                                 author=AUTHOR)

        # same opaque id, QAOfficer hat on: still the author -> denied
        validate_error(api.qa_approve_report(report["id"],
                                             make_qa_headers(AUTHOR)),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        approved = validate_success(api.qa_approve_report(
            report["id"], make_qa_headers(QA1)))
        assert approved["status"] == "CLIENT_REVIEW"


class TestClaimEvidence:
    def test_claim_verify_terminal_and_evidence_mismatch(self, api):
        """PRD §3.7: "the outcome is `SUPPORTED` exactly when `claimed_value` is less than or equal to the pinned recommendation's `computed_days`, and `NOT_SUPPORTED` otherwise"
        PRD §3.7: "the chosen verdict must equal the evidence outcome exactly, else `ERR_CLAIM_EVIDENCE_MISMATCH`, and on success `verified_by` records the acting `X-User-ID`"
        PRD §3.7: "only a claim whose `verdict` is still `PENDING` may be verified, else `ERR_CLAIM_ALREADY_VERIFIED`"

        Design: Corner/validations/claim_verify_terminal_and_evidence_mismatch
        """
        env = setup_reporting_study()  # fallback rec: target 60 -> 42 days
        report = create_draft_report(env["study"]["id"])
        get_success_data(api.attach_recommendation(
            report["id"], env["recommendations"][0]["id"],
            make_scientist_headers(AUTHOR)))
        claim = get_success_data(api.create_claim(
            create_claim_payload(report["id"], "SHELF_LIFE_DAYS",
                                 "Stays fresh 50 days", 50),
            make_scientist_headers(AUTHOR)))

        # evidence: 50 > 42 -> NOT_SUPPORTED; claiming SUPPORTED mismatches
        validate_error(api.verify_claim(claim["id"], "SUPPORTED",
                                        make_qa_headers(QA1)),
                       ApiErrorId.ERR_CLAIM_EVIDENCE_MISMATCH, 422)

        verified = validate_success(api.verify_claim(claim["id"], "NOT_SUPPORTED",
                                                     make_qa_headers(QA1)))
        assert verified["verdict"] == "NOT_SUPPORTED"
        assert verified["verified_by"] == QA1

        validate_error(api.verify_claim(claim["id"], "SUPPORTED",
                                        make_qa_headers(QA1)),
                       ApiErrorId.ERR_CLAIM_ALREADY_VERIFIED, 409)

    def test_packaging_superiority_claim_evidence(self, api):
        """PRD §3.7: "The evidence looks up the `ACCEPTED` recommendation of the study's control arm and that of the named arm; when either is missing the outcome is `INSUFFICIENT_DATA`. Otherwise the actual percentage improvement is the named arm's `computed_days` minus the control arm's `computed_days`, divided by the control arm's `computed_days`, multiplied by 100, and rounded half-up to 2 decimal places; the outcome is `SUPPORTED` exactly when that actual percentage is at least `claimed_value`, and `NOT_SUPPORTED` otherwise."
        PRD §3.7: "when the acceptance leaves every arm of the study holding at least one `ACCEPTED` recommendation and the study is still in `ANALYSIS`, the study advances automatically `ANALYSIS → REPORTING`"

        Design: Corner/validations/packaging_superiority_claim_evidence
        """
        env = setup_study_in_progress(
            arm_variants=("STANDARD_FILM", "HIGH_BARRIER", "VACUUM"),
            day_indexes=(70,), with_chamber=False)
        study_id = env["study"]["id"]
        arm_c, arm_v, arm_x = env["arms"]
        tp70 = env["time_points"][0]
        # variant arm trips PEROXIDE_VALUE (25.0 >= 20.0) at day 70 while
        # the study is IN_PROGRESS -> failure day 70.0
        tripped = get_success_data(api.create_lab_result(
            create_lab_result_payload(study_id, arm_v["id"], tp70["id"],
                                      "PEROXIDE_VALUE", 25.0), AN))
        assert tripped["tripped"] is True
        get_success_data(api.skip_time_point(tp70["id"], SCI))
        get_success_data(api.close_fieldwork(study_id, SCI))

        rec_c = propose_and_accept_recommendation(study_id, arm_c["id"])
        rec_v = propose_and_accept_recommendation(study_id, arm_v["id"])
        assert rec_c["computed_days"] == 42, "control: fallback from target 60"
        assert rec_v["computed_days"] == 56, (
            "variant: floor(70 * 0.8) = 56 -> 7-day tier -> 56")

        # VACUUM has no recommendation, so the study must not auto-advance
        assert get_study(study_id)["status"] == "ANALYSIS"

        report = create_draft_report(study_id)
        get_success_data(api.attach_recommendation(
            report["id"], rec_c["id"], make_scientist_headers(AUTHOR)))
        author = make_scientist_headers(AUTHOR)
        cl30 = get_success_data(api.create_claim(
            create_claim_payload(report["id"], "PACKAGING_SUPERIORITY",
                                 "High barrier lasts 30% longer", 30,
                                 arm_id=arm_v["id"]), author))
        cl40 = get_success_data(api.create_claim(
            create_claim_payload(report["id"], "PACKAGING_SUPERIORITY",
                                 "High barrier lasts 40% longer", 40,
                                 arm_id=arm_v["id"]), author))
        clx = get_success_data(api.create_claim(
            create_claim_payload(report["id"], "PACKAGING_SUPERIORITY",
                                 "Vacuum lasts 10% longer", 10,
                                 arm_id=arm_x["id"]), author))

        # actual_pct = (56 - 42) / 42 * 100 = 33.33
        v30 = validate_success(api.verify_claim(cl30["id"], "SUPPORTED",
                                                make_qa_headers(QA1)))
        assert v30["verdict"] == "SUPPORTED", "33.33 >= 30 supports the claim"
        v40 = validate_success(api.verify_claim(cl40["id"], "NOT_SUPPORTED",
                                                make_qa_headers(QA1)))
        assert v40["verdict"] == "NOT_SUPPORTED", "33.33 < 40 refutes the claim"
        vx = validate_success(api.verify_claim(clx["id"], "INSUFFICIENT_DATA",
                                               make_qa_headers(QA1)))
        assert vx["verdict"] == "INSUFFICIENT_DATA", (
            "the named arm has no ACCEPTED recommendation")


class TestReleaseAndCascade:
    def test_release_blocked_by_pending_claim_then_succeeds(self, api):
        """PRD §3.7: "Release is the laboratory's final word: a `LabDirector` releases a report from `CLIENT_REVIEW` (else `ERR_INVALID_REPORT_STATE`), requiring `requires_revision` false (else `ERR_REPORT_REQUIRES_REVISION`), requiring every claim substantiation of the report to hold a `verdict` of `SUPPORTED` (else `ERR_UNVERIFIED_CLAIMS`), and requiring the study to be `REPORTING` (else `ERR_INVALID_STUDY_STATE`)."
        PRD §3.7: "Release moves the report to `RELEASED` and completes the study `REPORTING → COMPLETED` in the same stroke"

        Design: Difficulty/cross_entity_state_dependency/report_release_requires_all_claims_supported
        """
        env = _release_ready_scenario(api)
        report_id = env["report"]["id"]

        resp = api.release_report(report_id, LD)
        validate_error(resp, ApiErrorId.ERR_UNVERIFIED_CLAIMS, 409)
        assert get_report(report_id)["status"] == "CLIENT_REVIEW"

        # evidence: claimed 42 <= pinned computed_days 42 -> SUPPORTED
        verified = validate_success(api.verify_claim(
            env["claim"]["id"], "SUPPORTED", make_qa_headers(QA1)))
        assert verified["verdict"] == "SUPPORTED"
        assert verified["verified_by"] == QA1

        released = validate_success(api.release_report(report_id, LD))
        assert released["status"] == "RELEASED"
        assert get_study(env["study"]["id"])["status"] == "COMPLETED"

    def test_release_runs_closing_trio(self, api):
        """PRD §3.7: "the closing trio: every `RETAIN` sample unit of the study in `STORED` or `CHECKED_OUT` receives its `retention_until_utc` of the current logical clock plus 90 days; the retainer settles (below); and the client's `active_study_count` decreases by 1."
        PRD §3.7: "Settlement then credits the client's `retainer_hours_balance` with the difference between the `reserved_hours_escrow` and `consumed_hours`, and zeroes the escrow"

        Design: Difficulty/cross_entity_state_dependency/report_release_requires_all_claims_supported
        """
        env = _release_ready_scenario(api)
        get_success_data(api.verify_claim(env["claim"]["id"], "SUPPORTED",
                                          make_qa_headers(QA1)))
        validate_success(api.release_report(env["report"]["id"], LD))

        # clock has been pinned at 2026-08-01T00:00:00Z since setup start
        retain_units = list_sample_units(study_id=env["study"]["id"],
                                         unit_purpose="RETAIN")
        assert len(retain_units) == 1
        retention = datetime.fromisoformat(
            retain_units[0]["retention_until_utc"].replace("Z", "+00:00"))
        assert retention == datetime(2026, 10, 30, tzinfo=timezone.utc), (
            "retention window = completion instant + 90 days")

        study = get_study(env["study"]["id"])
        assert study["consumed_hours"] == 0, (
            "no ANALYZED sessions and no lab results were recorded")
        assert study["reserved_hours_escrow"] == 0
        client = get_client(env["client"]["id"])
        # 100 topped up - 16 reserved at activation + 16 refunded at settlement
        assert client["retainer_hours_balance"] == 100
        assert client["active_study_count"] == 0

    def test_tripped_result_recomputes_failure_days_and_supersedes(self, api):
        """PRD §3.6: "a result is `tripped` — the flag defaults to false — when an `APC` value is at least 6.0"
        PRD §3.6: "Recording a tripped lab result runs the same cascade as a session lock that flips failure earlier: the arm's `computed_failure_day_equiv` is recomputed, the study's `earliest_failure_day_equiv` is recomputed, any recommendations of that arm in `PROPOSED` or `ACCEPTED` are superseded whenever the failure day changed"

        Design: Difficulty/transitive_cascade/lab_result_trip_supersedes_recommendation_reverts_report
        """
        env, rec, _report = _client_review_report_with_tp(api, day_index=10)
        result = get_success_data(api.create_lab_result(
            create_lab_result_payload(env["study"]["id"], env["arms"][0]["id"],
                                      env["time_points"][0]["id"], "APC", 9.0),
            AN))
        assert result["tripped"] is True, "9.0 >= APC limit 6.0"

        arm = get_success_data(api.get_study_arm(env["arms"][0]["id"], SCI))
        assert arm["computed_failure_day_equiv"] == pytest.approx(10.0, abs=0.0005), (
            "REAL_TIME: the observed day_index 10 as-is")
        assert get_study(env["study"]["id"])["earliest_failure_day_equiv"] == \
            pytest.approx(10.0, abs=0.0005)
        assert get_success_data(api.get_recommendation(rec["id"], SCI))["status"] \
            == "SUPERSEDED", "the ACCEPTED recommendation is superseded"

    def test_tripped_result_reverts_client_review_report(self, api):
        """PRD §3.7: "Every supersession flags the reports pinned to that recommendation: a pinned report in `DRAFT` or `INTERNAL_REVIEW` gets `requires_revision` set true, while one in `CLIENT_REVIEW` is sent back to `DRAFT` with `requires_revision` true and `revision_count` incremented by 1."

        Design: Difficulty/transitive_cascade/lab_result_trip_supersedes_recommendation_reverts_report
        """
        env, _rec, report = _client_review_report_with_tp(api, day_index=10)
        assert get_report(report["id"])["status"] == "CLIENT_REVIEW"

        get_success_data(api.create_lab_result(
            create_lab_result_payload(env["study"]["id"], env["arms"][0]["id"],
                                      env["time_points"][0]["id"], "APC", 9.0),
            AN))

        reverted = get_report(report["id"])
        assert reverted["status"] == "DRAFT", (
            "CLIENT_REVIEW auto-reverts to DRAFT on supersession")
        assert reverted["requires_revision"] is True
        assert reverted["revision_count"] == 1
