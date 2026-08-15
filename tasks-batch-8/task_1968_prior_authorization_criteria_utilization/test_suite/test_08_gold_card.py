"""Provider statistics and the gold-carding program (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accumulate_human_determinations,
    assert_provider,
    assert_provider_stats_invariants,
    basic_um_environment,
    create_guideline_version,
    create_provider,
    get_criteria_set,
    get_provider,
    get_request_determination,
    gold_card_evaluation_payload,
    list_gold_card_evaluations,
    list_provider_events,
    make_active_criteria_set,
    make_gold_carded_provider,
    pended_request,
    publish_guideline_version,
    reviewer_decide,
    run_gold_card_evaluation,
    set_clock,
    validate_error,
    validate_success,
    create_prior_auth_request_payload,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


class TestProviderDefaults:
    def test_provider_creation_applies_defaults(self, api):
        """PRD §3.6: "New providers start `NOT_GOLD_CARDED` with all counters at zero and `gold_card_service_category` null."
        PRD §2.4: "Most resources additionally carry `updated_at` (same format, refreshed on any mutation) and `version` (an integer starting at 1 that increments by one on every mutation)."
        PRD §2.10: "A rate whose denominator count is zero is represented as null rather than zero."

        Design: Corner/entities/provider_creation_applies_defaults
        """
        created = validate_success(
            api.create_provider(
                {"npi": "2000000001", "name": "Defaults Provider"}, ADMIN,
            ),
            expected_status=201,
        )
        provider = get_provider(created["id"])
        assert_provider(provider)
        assert provider["gold_card_status"] == "NOT_GOLD_CARDED"
        assert provider["gold_card_service_category"] is None
        assert provider["rolling_determination_count"] == 0
        assert provider["rolling_approval_count"] == 0
        assert provider["rolling_approval_rate"] is None
        assert provider["lifetime_determination_count"] == 0
        assert provider["lifetime_approval_count"] == 0
        assert provider["lifetime_approval_rate"] is None
        assert provider["version"] == 1

    def test_provider_missing_required_npi_rejected(self, api):
        """PRD §3.6: "Providers enter the registry through a `UMAdmin` supplying a unique `npi` (a duplicate `npi` is rejected under `ERR_INVALID_REQUEST`), a `name`, and an optional `specialty`."
        PRD §2.7: "Fourth, request-body well-formedness under `ERR_INVALID_REQUEST` (HTTP 400): required fields present and correctly typed, enum values inside their domains, body-supplied foreign keys (`provider_id`, `criteria_set_id`, `determination_id`, `supersedes_version_id`) referencing existing resources, `member_ref` non-empty, `scheduled_end` strictly after `scheduled_start`, `reason_code` consistent with the decision mapping (an `APPROVE` decision pairs with `MEDICAL_NECESSITY_MET`; a `DENY` decision pairs with one of the three denial codes; `reason_code` must be omitted on `ESCALATE` and `SEND_BACK`), and no duplicate `npi` across providers."

        Design: Corner/entities/provider_missing_required_npi_rejected
        """
        resp = api.create_provider({"name": "No NPI Provider"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRollingVsLifetime:
    def _setup_provider(self):
        """5 approvals + 5 denials issued at clock 2026-03-01, then 2 more
        approvals at clock 2026-08-01 (all reviewer tier)."""
        set_clock("2026-03-01T00:00:00Z")
        cs, _gv = make_active_criteria_set()
        provider = create_provider(name="Imaging Partners")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=5, member_prefix="A",
        )
        accumulate_human_determinations(
            provider["id"], cs["id"], denials=5, member_prefix="D",
            deny_reason_code="EXPERIMENTAL_INVESTIGATIONAL",
        )
        sweep = set_clock("2026-08-01T00:00:00Z")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=2, member_prefix="L",
        )
        return provider, sweep

    def test_rolling_window_variant_counts_only_recent(self, api):
        """PRD §3.6: "Two variants derive from the same set: the **rolling** variant restricts to determinations whose `issued_at` falls within the trailing 90 days of the logical clock — both bounds inclusive, 2,160 hours — and the **lifetime** variant applies no window."
        PRD §2.10: "All approval and overturn rates in the system are computed to 4 decimal places using round-half-up. A rate whose denominator count is zero is represented as null rather than zero."

        Design: Difficulty/dual_variant_calc/provider_approval_rate_rolling_vs_lifetime
        """
        provider, _sweep = self._setup_provider()
        data = get_provider(provider["id"])
        # The window [2026-05-03, 2026-08-01] excludes all ten March rows.
        assert data["rolling_determination_count"] == 2
        assert data["rolling_approval_count"] == 2
        assert data["rolling_approval_rate"] == pytest.approx(1.0)

    def test_lifetime_variant_counts_everything_and_sweep_skips_decided(self, api):
        """PRD §3.6: "Two variants derive from the same set: the **rolling** variant restricts to determinations whose `issued_at` falls within the trailing 90 days of the logical clock — both bounds inclusive, 2,160 hours — and the **lifetime** variant applies no window."
        PRD §2.5: "The clock-advance sweep flags every undetermined request (one in `PENDED_REVIEW` or `ESCALATED_MD`) and every undecided appeal (one in `RECEIVED` or `IN_REVIEW`) whose `due_at` is strictly before the new clock, setting the sticky boolean `is_tat_breached` and emitting a `TAT_BREACHED` compliance event per flagged row."

        Design: Difficulty/dual_variant_calc/provider_approval_rate_rolling_vs_lifetime
        """
        provider, sweep = self._setup_provider()
        assert sweep["requests_flagged"] == 0, (
            "all March requests were already determined when the clock advanced"
        )
        data = get_provider(provider["id"])
        assert data["lifetime_determination_count"] == 12
        assert data["lifetime_approval_count"] == 7
        assert data["lifetime_approval_rate"] == pytest.approx(0.5833), (
            "7/12 at 4 decimal places round-half-up"
        )


class TestEligibilityBoundaries:
    def test_rate_exactly_at_threshold_is_eligible(self, api):
        """PRD §3.6: "Otherwise the rolling statistics are recomputed first — counting only human-lane determinations, which breaks the circular dependency in which gold-card auto-approvals would otherwise inflate the very rate used to keep the gold card — and eligibility requires a `rolling_determination_count` of at least 10 and a `rolling_approval_rate` of at least 0.90, both thresholds inclusive (exactly 0.9000 is eligible; a zero count yields a null rate and is never eligible)."

        Design: Difficulty/boundary_precision_check/gold_card_rate_exactly_at_threshold
        """
        _provider, cs, _gv = basic_um_environment()
        provider = create_provider(name="Boundary Provider")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=9, denials=1, member_prefix="B",
        )
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["window_determination_count"] == 10
        assert evaluation["window_approval_rate"] == pytest.approx(0.9), (
            "9/10 sits exactly on the 0.90 threshold"
        )
        assert evaluation["decision"] == "GRANTED", ">= is inclusive"

    def test_threshold_grant_sets_gold_card(self, api):
        """PRD §3.6: "The provider becomes `GOLD_CARDED` with `gold_card_service_category` set to the evaluated category, and a `GOLD_CARD_GRANTED` event is recorded."

        Design: Difficulty/boundary_precision_check/gold_card_rate_exactly_at_threshold
        """
        _p, cs, _gv = basic_um_environment()
        provider = create_provider(name="Boundary Provider")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=9, denials=1, member_prefix="B",
        )
        run_gold_card_evaluation(provider["id"], "IMAGING")
        after = get_provider(provider["id"])
        assert after["gold_card_status"] == "GOLD_CARDED"
        assert after["gold_card_service_category"] == "IMAGING"
        events = list_provider_events(provider["id"], event_type="GOLD_CARD_GRANTED")
        assert len(events) == 1

    def test_below_threshold_rejected_without_record(self, api):
        """PRD §3.6: "An ineligible evaluation is rejected with `ERR_GOLD_CARD_NOT_ELIGIBLE` (HTTP 422) and creates no record."

        Design: Corner/validations/gold_card_below_threshold_rejected
        """
        _p, cs, _gv = basic_um_environment()
        provider = create_provider(name="Below Threshold Provider")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=8, denials=2, member_prefix="B",
        )
        resp = api.create_gold_card_evaluation(
            provider["id"], gold_card_evaluation_payload("IMAGING"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_GOLD_CARD_NOT_ELIGIBLE)
        after = get_provider(provider["id"])
        assert after["gold_card_status"] == "NOT_GOLD_CARDED"
        assert after["rolling_approval_rate"] == pytest.approx(0.8)
        assert list_gold_card_evaluations(provider["id"]) == [], (
            "rejected evaluations persist nothing"
        )

    def test_already_gold_carded_evaluation_rejected(self, api):
        """PRD §3.6: "Evaluation is blocked outright for a provider already `GOLD_CARDED` (`ERR_ALREADY_GOLD_CARDED`)."

        Design: Corner/validations/already_gold_carded_evaluation_rejected
        """
        _p, cs, _gv = basic_um_environment()
        provider, _evaluation = make_gold_carded_provider(cs["id"], "IMAGING")
        resp = api.create_gold_card_evaluation(
            provider["id"], gold_card_evaluation_payload("IMAGING"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_GOLD_CARDED)
        evaluations = list_gold_card_evaluations(provider["id"])
        assert len(evaluations) == 1, "no second record persisted"


class TestEvaluationWindowSnapshot:
    def test_granted_evaluation_records_window_fields(self, api):
        """PRD §3.6: "A successful evaluation writes a `GoldCardEvaluation` capturing the `window_start` (evaluation time minus 90 days, an inclusive lower bound), `window_end` (the evaluation instant), the observed `window_determination_count`, the observed `window_approval_rate` at 4 decimal places, and a `decision` of `REINSTATED` when the provider was `SUSPENDED` or `GRANTED` otherwise."

        Design: Corner/entities/gold_card_evaluation_record_window_fields
        """
        _p, cs, _gv = basic_um_environment()
        provider = create_provider(name="Window Provider")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=10, member_prefix="W",
        )
        run_gold_card_evaluation(provider["id"], "IMAGING")
        evaluations = list_gold_card_evaluations(provider["id"])
        assert len(evaluations) == 1
        record = evaluations[0]
        assert record["window_start"] == "2026-05-03T00:00:00.000Z", (
            "evaluation clock 2026-08-01 minus 90 days"
        )
        assert record["window_end"] == "2026-08-01T00:00:00.000Z"
        assert record["window_determination_count"] == 10
        assert record["window_approval_rate"] == pytest.approx(1.0)
        assert record["decision"] == "GRANTED"

    def test_rolling_window_inclusive_lower_bound(self, api):
        """PRD §3.6: "Two variants derive from the same set: the **rolling** variant restricts to determinations whose `issued_at` falls within the trailing 90 days of the logical clock — both bounds inclusive, 2,160 hours — and the **lifetime** variant applies no window."

        Design: Corner/calculations/rolling_window_inclusive_lower_bound
        """
        set_clock("2026-05-03T00:00:00Z")
        cs, _gv = make_active_criteria_set()
        provider = create_provider(name="Inclusive Provider")
        # Issued exactly at the evaluation's window_start (2026-08-01 minus
        # 2160 hours): the inclusive lower bound keeps it inside.
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=1, member_prefix="E0",
        )
        set_clock("2026-05-04T00:00:00Z")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=8, denials=1, member_prefix="E",
        )
        set_clock("2026-08-01T00:00:00Z")
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["window_determination_count"] == 10
        assert evaluation["window_approval_rate"] == pytest.approx(0.9)
        assert evaluation["decision"] == "GRANTED"


class TestEligibilityExcludesAutoLane:
    def _setup_circular_dependency(self, api):
        """9 reviewer approvals + 1 reviewer denial on v1 (not eligible);
        v2 (auto-eligible) supersedes v1; 5 PORTAL/complete intakes then
        auto-approve through the rules lane."""
        cs, gv1 = make_active_criteria_set(auto_approve_eligible=False)
        provider = create_provider(name="Circular Provider")
        accumulate_human_determinations(
            provider["id"], cs["id"], approvals=9, denials=1, member_prefix="H",
        )
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0", content="Clinical criteria v2",
            auto_approve_eligible=True, effective_from="2026-01-01T00:00:00Z",
            supersedes_version_id=gv1["id"],
        )
        publish_guideline_version(gv2["id"], get_criteria_set(cs["id"])["version"])
        auto_requests = []
        for i in range(5):
            payload = create_prior_auth_request_payload(
                provider_id=provider["id"], criteria_set_id=cs["id"],
                member_ref=f"A-{i + 1:02d}", intake_channel="PORTAL",
                documentation_complete=True,
            )
            auto_requests.append(
                validate_success(
                    api.create_prior_auth_request(payload, INTAKE),
                    expected_status=201,
                )
            )
        return provider, auto_requests

    def test_evaluation_window_excludes_system_rule_determinations(self, api):
        """PRD §3.6: "Provider oversight rests on a single inclusion set: determinations joined through their requests' `provider_id` whose status is `FINAL` or `OVERTURNED` and whose `decided_by_role` is `CLINICAL_REVIEWER` or `MEDICAL_DIRECTOR`. System-rule auto-approvals and voided determinations never count."
        PRD §3.6: "Otherwise the rolling statistics are recomputed first — counting only human-lane determinations, which breaks the circular dependency in which gold-card auto-approvals would otherwise inflate the very rate used to keep the gold card — and eligibility requires a `rolling_determination_count` of at least 10 and a `rolling_approval_rate` of at least 0.90, both thresholds inclusive (exactly 0.9000 is eligible; a zero count yields a null rate and is never eligible)."

        Design: Difficulty/combinatorial_formula/gold_card_eligibility_excludes_auto_lane
        """
        provider, auto_requests = self._setup_circular_dependency(api)
        assert auto_requests[0]["status"] == "AUTO_APPROVED"
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["window_determination_count"] == 10, (
            "the 5 SYSTEM_RULE determinations are excluded from the input set"
        )
        assert evaluation["window_approval_rate"] == pytest.approx(0.9), (
            "9/10 human-lane; auto-lane inclusion would have produced 14/15"
        )

    def test_evaluation_grants_gold_card_on_human_lane_only(self, api):
        """PRD §3.6: "The provider becomes `GOLD_CARDED` with `gold_card_service_category` set to the evaluated category, and a `GOLD_CARD_GRANTED` event is recorded."

        Design: Difficulty/combinatorial_formula/gold_card_eligibility_excludes_auto_lane
        """
        provider, _auto = self._setup_circular_dependency(api)
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["decision"] == "GRANTED"
        after = get_provider(provider["id"])
        assert after["gold_card_status"] == "GOLD_CARDED"
        assert after["gold_card_service_category"] == "IMAGING"
        assert_provider_stats_invariants(after)


class TestSuspendReinstateCycle:
    def _setup_gold_then_two_denials(self):
        """Provider GOLD_CARDED for IMAGING, then two reviewer denials routed
        through a CARDIOLOGY criteria set. Per PRD §3.2 the gold lane fires
        only when the gold-card category equals the criteria set's
        service_category, so the CARDIOLOGY intakes pend and the reviewer
        tier actually decides them; the resulting human-lane determinations
        still join the provider-wide inclusion set of PRD §3.6."""
        cs_img, _gv1 = make_active_criteria_set(
            name="Spine Imaging Criteria", service_category="IMAGING",
        )
        cs_other, _gv2 = make_active_criteria_set(
            name="Cardiac Criteria", service_category="CARDIOLOGY",
        )
        provider = create_provider(name="Cycle Gold Provider")
        accumulate_human_determinations(
            provider["id"], cs_img["id"], approvals=10, member_prefix="G",
        )
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["decision"] == "GRANTED"
        det1 = None
        det2 = None
        req1 = pended_request(provider["id"], cs_other["id"], member_ref="D-01")
        reviewer_decide(req1["id"], "DENY",
                        reason_code="MEDICAL_NECESSITY_NOT_MET")
        det1 = get_request_determination(req1["id"])
        after_d1 = get_provider(provider["id"])
        req2 = pended_request(provider["id"], cs_other["id"], member_ref="D-02")
        reviewer_decide(req2["id"], "DENY",
                        reason_code="MEDICAL_NECESSITY_NOT_MET")
        det2 = get_request_determination(req2["id"])
        after_d2 = get_provider(provider["id"])
        events = list_provider_events(
            provider["id"], event_type="GOLD_CARD_SUSPENDED",
        )
        return provider, det1, det2, after_d1, after_d2, events

    def test_first_denial_does_not_cross_threshold(self, api):
        """PRD §3.6: "Suspension is automatic, not administrative. Whenever provider statistics recompute after a human-lane determination insert or a determination void, the auto-suspend check runs: if the provider is `GOLD_CARDED` and the recomputed rolling count is at least 10 while the rolling rate is strictly below 0.90, the provider flips to `SUSPENDED`, `gold_card_service_category` clears to null, and a `GOLD_CARD_SUSPENDED` event is recorded."

        Design: Difficulty/non_linear_state_machine/provider_gold_card_suspend_reinstate_cycle
        """
        _p, _d1, _d2, after_d1, _after_d2, _ev = self._setup_gold_then_two_denials()
        assert after_d1["gold_card_status"] == "GOLD_CARDED"
        assert after_d1["rolling_approval_rate"] == pytest.approx(0.9091), (
            "10/11: the first denial does not cross below 0.90"
        )

    def test_second_denial_suspends_and_clears_category(self, api):
        """PRD §3.6: "Suspension is automatic, not administrative. Whenever provider statistics recompute after a human-lane determination insert or a determination void, the auto-suspend check runs: if the provider is `GOLD_CARDED` and the recomputed rolling count is at least 10 while the rolling rate is strictly below 0.90, the provider flips to `SUSPENDED`, `gold_card_service_category` clears to null, and a `GOLD_CARD_SUSPENDED` event is recorded."

        Design: Difficulty/non_linear_state_machine/provider_gold_card_suspend_reinstate_cycle
        """
        _p, _d1, _d2, _a1, after_d2, events = self._setup_gold_then_two_denials()
        assert after_d2["gold_card_status"] == "SUSPENDED"
        assert after_d2["rolling_approval_rate"] == pytest.approx(0.8333), (
            "10/12 < 0.90 with count >= 10 triggers auto-suspension"
        )
        assert after_d2["gold_card_service_category"] is None
        assert len(events) == 1
        assert events[0]["event_type"] == "GOLD_CARD_SUSPENDED"

    def test_voids_restore_stats_and_reinstate(self, api):
        """PRD §3.4: "In every void, `determined_at` is cleared to null, provider statistics recompute excluding the voided row (void rows never count toward any rate), and a `DETERMINATION_VOIDED` event is recorded with the request and provider ids."
        PRD §3.6: "Reinstatement is simply another evaluation that passes eligibility on the freshly recomputed rolling stats."
        PRD §3.6: "A successful evaluation writes a `GoldCardEvaluation` capturing the `window_start` (evaluation time minus 90 days, an inclusive lower bound), `window_end` (the evaluation instant), the observed `window_determination_count`, the observed `window_approval_rate` at 4 decimal places, and a `decision` of `REINSTATED` when the provider was `SUSPENDED` or `GRANTED` otherwise."

        Design: Difficulty/non_linear_state_machine/provider_gold_card_suspend_reinstate_cycle
        """
        provider, det1, det2, _a1, after_d2, _ev = self._setup_gold_then_two_denials()
        assert after_d2["gold_card_status"] == "SUSPENDED"
        validate_success(api.void_determination(det1["id"], ADMIN))
        validate_success(api.void_determination(det2["id"], ADMIN))
        restored = get_provider(provider["id"])
        assert restored["rolling_determination_count"] == 10
        assert restored["rolling_approval_rate"] == pytest.approx(1.0), (
            "voided denials are excluded from the stats"
        )
        evaluation = run_gold_card_evaluation(provider["id"], "IMAGING")
        assert evaluation["decision"] == "REINSTATED"
        final = get_provider(provider["id"])
        assert final["gold_card_status"] == "GOLD_CARDED"
        assert final["gold_card_service_category"] == "IMAGING"
