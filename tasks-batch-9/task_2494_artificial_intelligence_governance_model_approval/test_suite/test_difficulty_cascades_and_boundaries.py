"""Multi-hop cascades, first-error-wins rejection ordering, and inclusive boundaries.

Every test here builds its own preconditions from scratch through declared
endpoints, because the server is restarted against an empty database before each
individual test.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    POSTURE_IMPAIRED,
    POSTURE_WATCH,
    PORTFOLIO_HIGH_TIER_REACH_CAP,
    SUPERSEDED_APPROVAL_SUSPENDED,
    SUPERSEDED_ASSET_REAPPROVED,
    SUPERSEDED_USE_CASE_REVOKED,
    EVAL_WINDOWS,
    HIGH_PASSING_RUNS,
    OFFICER,
    SECURITY_REVIEWER,
    approval_payload,
    asset_revision_payload,
    assert_disclosure_notice,
    assert_iso_instant,
    assert_ledger_reach_balance,
    assert_metric_value,
    assert_model_asset,
    assert_model_binding,
    assert_monitoring_incident,
    assert_reach_conserved,
    assert_test_evaluation,
    assert_use_case,
    assert_vendor_assessment,
    clear_gate,
    clear_all_gates,
    complete_evaluation,
    current_version,
    entry_types,
    exactly_seventy_high_use_case,
    expected_containment_hours,
    high_tier_approved_use_case,
    high_tier_grade_c_large_reach,
    high_tier_use_case_ready_for_approval,
    limited_approved_use_case,
    list_assessments,
    list_bindings,
    list_evaluations,
    list_ledger,
    list_notices,
    list_snapshots,
    move_clock,
    plus_seconds,
    read_asset,
    read_incident,
    read_summary,
    read_use_case,
    report_incident,
    revocation_payload,
    run_evaluation,
    schedule_evaluation,
    suspended_use_case_via_sev1,
    validate_error,
    validate_success,
)

# Instants the recipes below depend on, all derived from the pinned logical clock.
SEV1_LIMITED_DEADLINE = "2026-08-01T04:00:00Z"
SEV2_LIMITED_DEADLINE = "2026-08-02T00:00:00Z"

# Windows laid out back to back after the four the standard evidence run occupies.
FAILING_BIAS_WINDOW = ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z")
LATE_ROBUSTNESS_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z")
LATE_HALLUCINATION_WINDOW = ("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")
LATE_REDTEAM_WINDOW = ("2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z")
REMEDIAL_BIAS_WINDOW = ("2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z")

# The three adjacent BIAS windows the threshold probes reserve, one run each.
BIAS_PROBE_WINDOWS = [
    ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"),
    ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"),
    ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z"),
]


def _revoke_for_programme_cancellation(api, use_case_id):
    """Revoke with an explicit reason, so the recorded reason can be asserted."""
    return validate_success(
        api.revoke_use_case(
            use_case_id,
            revocation_payload(revocation_reason="PROGRAMME_CANCELLED"),
            headers=OFFICER,
        )
    )


def _high_tier_approval_then_revoked(api):
    """A HIGH-tier approval taken through revocation with a named reason."""
    chain = high_tier_approved_use_case(api)
    chain.use_case = _revoke_for_programme_cancellation(api, chain.use_case_id)
    return chain


def _ready_high_tier_pushed_back_with_a_behind_binding(api):
    """A cleared HIGH-tier use case whose asset moved on and whose gate reopened.

    Revising the asset in place leaves the binding pinned one asset version behind,
    and reopening a cleared gate drops the use case out of ``READY_FOR_APPROVAL``,
    so an approval attempt now violates both a lifecycle check and a binding check.
    """
    chain = high_tier_use_case_ready_for_approval(api)
    validate_success(
        api.update_model_asset(
            chain.asset_id,
            asset_revision_payload(model_version="3.3.0"),
            headers=OFFICER,
        )
    )
    validate_success(api.reopen_gate(chain.gate_id("BUSINESS"), headers=OFFICER))
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def _ready_high_tier_with_failed_bias_and_oversized_reach(api):
    """A cleared HIGH-tier use case holding a raised safety flag and 300000 reach.

    The failing BIAS run is completed before the gates are cleared, because a failed
    run pushes the intake back and a reviewer taking a gate up is the route forward.
    """
    chain = high_tier_grade_c_large_reach(api)
    passing_bias_value = HIGH_PASSING_RUNS["BIAS"][0]
    chain.evaluations["BIAS_PASSED"] = run_evaluation(
        api,
        chain.binding_id,
        "BIAS",
        *EVAL_WINDOWS["BIAS"],
        passing_bias_value,
        1200,
        chain.use_case_id,
    )
    chain.evaluations["BIAS_FAILED"] = run_evaluation(
        api,
        chain.binding_id,
        "BIAS",
        *FAILING_BIAS_WINDOW,
        0.7000,
        1200,
        chain.use_case_id,
    )
    chain.evaluations["ROBUSTNESS"] = run_evaluation(
        api,
        chain.binding_id,
        "ROBUSTNESS",
        *LATE_ROBUSTNESS_WINDOW,
        0.9200,
        1200,
        chain.use_case_id,
    )
    chain.evaluations["HALLUCINATION"] = run_evaluation(
        api,
        chain.binding_id,
        "HALLUCINATION",
        *LATE_HALLUCINATION_WINDOW,
        0.9600,
        1200,
        chain.use_case_id,
    )
    chain.evaluations["SECURITY_REDTEAM"] = run_evaluation(
        api,
        chain.binding_id,
        "SECURITY_REDTEAM",
        *LATE_REDTEAM_WINDOW,
        0.9600,
        1200,
        chain.use_case_id,
    )
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def _attempt_approval(api, use_case_id):
    """Sign the approval against the use case's current version."""
    return api.approve_use_case(
        use_case_id,
        approval_payload(current_version(api, use_case_id)),
        headers=OFFICER,
    )


def _limited_approval_with_two_sev2_incidents(api):
    """A LIMITED approval carrying two SEV2 incidents detected at the same instant."""
    chain = limited_approved_use_case(api)
    for _ in range(2):
        chain.incidents.append(
            report_incident(api, chain.use_case_id, "SEV2", category="DRIFT")
        )
    return chain


class TestRevokeCascadesFourHopsToVendorAssessmentExpiry:
    """Revocation of a HIGH-tier approval on a third-party asset, hop by hop."""

    def test_revocation_revokes_the_use_case_and_retires_its_binding(self, api):
        """PRD §3.8: "**Hop 1.** The use case moves to `REVOKED`, `revoked_at` is stamped with the current logical instant, `revocation_reason` records the supplied reason, and a `GovernanceLedgerEntry` of type `APPROVAL_REVOKED` is appended. Its `reach_delta` is minus the use case's `deployed_headcount_reach` when the use case was in an inventory status — `APPROVED`, `UNDER_REASSESSMENT` or `SUSPENDED` — and 0 when it was merely `READY_FOR_APPROVAL` and therefore never counted toward the portfolio. Its `debt_delta` is 0.00."

        PRD §3.8: "**Hop 2**, caused by hop 1. Every `ModelBinding` of the use case whose status is `PINNED` or `STALE` moves to `RETIRED` with `superseded_reason` `USE_CASE_REVOKED`, and a `GovernanceLedgerEntry` of type `BINDING_RETIRED` is appended for each retired binding."

        Design: Difficulty/transitive_cascade/revoke_cascades_four_hops_to_vendor_assessment_expiry
        """
        chain = high_tier_approved_use_case(api)
        assert_use_case(
            chain.use_case, status="APPROVED", deployed_headcount_reach=12000
        )

        revoked = _revoke_for_programme_cancellation(api, chain.use_case_id)

        assert_use_case(
            revoked, status="REVOKED", revocation_reason="PROGRAMME_CANCELLED"
        )
        assert_iso_instant(revoked["revoked_at"], DEFAULT_CLOCK)

        bindings = list_bindings(api, chain.use_case_id)
        assert len(bindings) == 1, f"expected one binding, got {len(bindings)}"
        assert_model_binding(
            bindings[0],
            status="RETIRED",
            superseded_reason=SUPERSEDED_USE_CASE_REVOKED,
        )

        entries = list_ledger(api, chain.use_case_id, limit=100)
        revocations = [e for e in entries if e["entry_type"] == "APPROVAL_REVOKED"]
        assert len(revocations) == 1, entry_types(entries)
        assert revocations[0]["reach_delta"] == -12000
        assert revocations[0]["debt_delta"] == pytest.approx(0.00, abs=0.01)
        assert entry_types(entries).count("BINDING_RETIRED") == 1, entry_types(entries)

    def test_retired_binding_restricts_the_asset_and_expires_its_vendor_terms(self, api):
        """PRD §3.8: "**Hop 3**, caused by hop 2. Each retired binding decrements the `active_binding_count` of the asset it named by 1. When that count reaches 0 while the asset's `is_third_party` is true and its status is `APPROVED_FOR_USE`, the asset moves to `RESTRICTED`."

        PRD §3.8: "**Hop 4**, caused by hop 3. On each asset that just became `RESTRICTED`, every `VendorModelAssessment` with status `ACCEPTED` moves to `EXPIRED`, the asset's `vendor_terms_grade` is set to null, and a `GovernanceLedgerEntry` of type `VENDOR_ASSESSMENT_EXPIRED` is appended against the use case whose revocation started the cascade."

        PRD §3.1: "Clearing an asset for use moves it from `REGISTERED` to `APPROVED_FOR_USE`, and this is the gate at which third-party supply is tested: if `is_third_party` is true, the asset must already carry a `VendorModelAssessment` with status `ACCEPTED` whose `terms_grade` is `A`, `B` or `C`, and without one the attempt is rejected with `ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED`."

        Design: Difficulty/transitive_cascade/revoke_cascades_four_hops_to_vendor_assessment_expiry
        """
        chain = _high_tier_approval_then_revoked(api)

        asset = read_asset(api, chain.asset_id)
        assert_model_asset(
            asset,
            status="RESTRICTED",
            is_third_party=True,
            active_binding_count=0,
            vendor_terms_grade=None,
        )

        assessments = list_assessments(api, chain.asset_id)
        assert len(assessments) == 1, f"expected one assessment, got {len(assessments)}"
        assert_vendor_assessment(assessments[0], status="EXPIRED", terms_grade="B")

        entries = list_ledger(api, chain.use_case_id, limit=100)
        assert entry_types(entries).count("VENDOR_ASSESSMENT_EXPIRED") == 1, entry_types(
            entries
        )

        validate_error(
            api.approve_asset_for_use(chain.asset_id, headers=OFFICER),
            ApiErrorId.VENDOR_ASSESSMENT_NOT_ACCEPTED,
        )

    def test_revocation_withdraws_the_notices_and_returns_the_reach_balance_to_zero(
        self, api
    ):
        """PRD §3.8: "Alongside those hops, every `TestEvaluation` in `PLANNED` on a retired binding moves to `VOIDED`, and every `DisclosureNotice` of the use case in `PUBLISHED` moves to `WITHDRAWN` with `withdrawn_at` stamped, each withdrawal appending a `GovernanceLedgerEntry` of type `DISCLOSURE_WITHDRAWN`. The use case's own `version` increments. Because hop 1's negative reach delta exactly offsets the positive one the approval booked, the sum of `reach_delta` for that use case returns to 0 and the portfolio reach returns to its pre-approval value."

        PRD §2.11: "The sum of `reach_delta` over all ledger entries — `ledger_reach_balance` — must equal `portfolio_approved_reach` at all times."

        Design: Difficulty/transitive_cascade/revoke_cascades_four_hops_to_vendor_assessment_expiry
        """
        chain = _high_tier_approval_then_revoked(api)

        notices = list_notices(api, chain.use_case_id)
        assert len(notices) == 2, f"expected two notices, got {len(notices)}"
        assert sorted(notice["jurisdiction"] for notice in notices) == ["EU", "UK"]
        for notice in notices:
            assert_disclosure_notice(notice, status="WITHDRAWN")
            assert_iso_instant(notice["withdrawn_at"], DEFAULT_CLOCK)

        entries = list_ledger(api, chain.use_case_id, limit=100)
        types = entry_types(entries)
        assert types.count("DISCLOSURE_WITHDRAWN") == 2, types
        granted = [e for e in entries if e["entry_type"] == "APPROVAL_GRANTED"]
        assert len(granted) == 1, types
        assert granted[0]["reach_delta"] == 12000
        assert_ledger_reach_balance(entries, 0)

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 0
        assert summary["ledger_reach_balance"] == 0
        assert_reach_conserved(summary)

        evaluations = list_evaluations(api, use_case_id=chain.use_case_id)
        assert len(evaluations) == 4, f"expected four runs, got {len(evaluations)}"
        for evaluation in evaluations:
            assert_test_evaluation(evaluation, status="PASSED")


class TestSev1IncidentCascadesPostureToSuspensionToStaleBinding:
    """One SEV1 report on a LIMITED approval, followed through three hops."""

    def test_sev1_report_impairs_the_posture_and_stamps_a_four_hour_deadline(self, api):
        """PRD §3.8: "The containment clock is derived at reporting time. The effective tier is the use case's `final_risk_tier` when that is non-null, and its provisional `risk_tier` otherwise. `containment_hours` is the base allowance for the severity — 4 hours for `SEV1`, 24 hours for `SEV2`, 72 hours for `SEV3` — multiplied by a tier speed factor of 1.5 for `MINIMAL`, 1.0 for `LIMITED`, 0.5 for `HIGH` and 0.5 for `PROHIBITED`, with the product rounded up to the next whole hour. `containment_deadline_at` is `detected_at` plus that many hours."

        PRD §3.8: "If any unresolved incident carries `SEV1`, `monitoring_posture` becomes `IMPAIRED`."

        Design: Difficulty/transitive_cascade/sev1_incident_cascades_posture_to_suspension_to_stale_binding
        """
        chain = suspended_use_case_via_sev1(api)

        incident = read_incident(api, chain.incidents[0]["id"])
        assert_monitoring_incident(
            incident,
            status="OPEN",
            severity="SEV1",
            category="HARMFUL_OUTPUT",
            containment_hours=4,
        )
        assert incident["containment_hours"] == expected_containment_hours(
            "SEV1", "LIMITED"
        )
        assert_iso_instant(incident["detected_at"], DEFAULT_CLOCK)
        assert_iso_instant(incident["containment_deadline_at"], SEV1_LIMITED_DEADLINE)

        use_case = read_use_case(api, chain.use_case_id)
        assert_use_case(
            use_case, final_risk_tier="LIMITED", monitoring_posture=POSTURE_IMPAIRED
        )

    def test_impaired_posture_suspends_the_approval_and_stales_the_binding(self, api):
        """PRD §3.8: "When posture re-derivation leaves a use case that is in `APPROVED` or `UNDER_REASSESSMENT` at `IMPAIRED`, that use case moves to `SUSPENDED`, every `ModelBinding` of the use case in `PINNED` drops to `STALE` with `superseded_reason` `APPROVAL_SUSPENDED`, every `TestEvaluation` in `PLANNED` on a binding that just went stale is `VOIDED`, and a `GovernanceLedgerEntry` of type `APPROVAL_SUSPENDED` is appended with `reach_delta` 0 and `debt_delta` 0.00."

        PRD §2.10: "`active_binding_count` on a `ModelAsset` is the number of bindings on that asset whose status is `PINNED` or `STALE`."

        Design: Difficulty/transitive_cascade/sev1_incident_cascades_posture_to_suspension_to_stale_binding
        """
        chain = suspended_use_case_via_sev1(api)

        use_case = read_use_case(api, chain.use_case_id)
        assert_use_case(
            use_case, status="SUSPENDED", monitoring_posture=POSTURE_IMPAIRED
        )

        bindings = list_bindings(api, chain.use_case_id)
        assert len(bindings) == 1, f"expected one binding, got {len(bindings)}"
        assert_model_binding(
            bindings[0],
            status="STALE",
            superseded_reason=SUPERSEDED_APPROVAL_SUSPENDED,
            pinned_model_version=2,
            model_asset_id=chain.asset_id,
        )

        asset = read_asset(api, chain.asset_id)
        assert_model_asset(asset, status="APPROVED_FOR_USE", active_binding_count=1)

    def test_suspension_books_a_zero_delta_entry_and_keeps_the_reach_in_inventory(
        self, api
    ):
        """PRD §3.8: "The reach delta is zero precisely because `SUSPENDED` remains an inventory status — a suspension does not take reach out of the portfolio."

        PRD §2.11: "The three statuses `APPROVED`, `UNDER_REASSESSMENT` and `SUSPENDED` constitute the *inventory statuses*: a use case in any of them is live in the governance inventory. `portfolio_approved_reach` is the sum of `deployed_headcount_reach` over every use case in an inventory status, and `portfolio_approved_reach_high_tier` is that same sum restricted to use cases whose `final_risk_tier` is `HIGH`."

        Design: Difficulty/transitive_cascade/sev1_incident_cascades_posture_to_suspension_to_stale_binding
        """
        chain = suspended_use_case_via_sev1(api)

        entries = list_ledger(api, chain.use_case_id, limit=100)
        suspensions = [e for e in entries if e["entry_type"] == "APPROVAL_SUSPENDED"]
        assert len(suspensions) == 1, entry_types(entries)
        assert suspensions[0]["reach_delta"] == 0
        assert suspensions[0]["debt_delta"] == pytest.approx(0.00, abs=0.01)

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 5000
        assert summary["inventory_count"] == 1
        assert_reach_conserved(summary)

        evaluations = list_evaluations(api, use_case_id=chain.use_case_id)
        assert len(evaluations) == 1, f"expected one run, got {len(evaluations)}"
        assert_test_evaluation(evaluations[0], eval_type="BIAS", status="PASSED")

    def test_a_later_sev3_leaves_the_posture_impaired(self, api):
        """PRD §3.8: "Posture is derived from unresolved incidents each time an incident is reported, contained or resolved, and it considers only incidents on that use case whose status is `OPEN` or `ESCALATED`; `CONTAINED` and `RESOLVED` incidents are excluded. If any unresolved incident carries `SEV1`, `monitoring_posture` becomes `IMPAIRED`. Otherwise, if there is at least one unresolved incident of any severity, it becomes `WATCH`. With none outstanding, it becomes `HEALTHY`. The derivation is order-independent, so no tie-break is needed."

        Design: Difficulty/transitive_cascade/sev1_incident_cascades_posture_to_suspension_to_stale_binding
        """
        chain = suspended_use_case_via_sev1(api)

        later = report_incident(api, chain.use_case_id, "SEV3", category="DRIFT")
        assert_monitoring_incident(later, status="OPEN", severity="SEV3")

        use_case = read_use_case(api, chain.use_case_id)
        assert_use_case(
            use_case, status="SUSPENDED", monitoring_posture=POSTURE_IMPAIRED
        )
        assert_monitoring_incident(
            read_incident(api, chain.incidents[0]["id"]), status="OPEN", severity="SEV1"
        )


class TestStatePrecedesBusinessReferentialOnApprove:
    """An approval violating both the lifecycle check and the binding check."""

    def test_not_ready_for_approval_wins_over_the_stale_binding_condition(self, api):
        """PRD §2.9: "The order below is normative: checks are evaluated top to bottom and the **first** one that fails determines the response. A later check never masks an earlier one."

        PRD §2.9: "9. `expected_use_case_version` equals the use case's current `version` — `ERR_STALE_USE_CASE_VERSION` (412), on classification, binding creation, oversight-design filing and approval."

        PRD §2.9: "13. The use case is in `READY_FOR_APPROVAL` — `ERR_USE_CASE_NOT_READY_FOR_APPROVAL` (409), on approval."

        PRD §2.9: "28. A `PINNED` `ModelBinding` exists on the use case — `ERR_MODEL_BINDING_MISSING` (422). This guards two operations: approval, and clearance of a `LEGAL` gate only."

        PRD §2.9: "29. The `PINNED` binding's `pinned_model_version` equals its asset's current `version` — `ERR_MODEL_BINDING_STALE` (409), on approval."

        PRD §3.1: "This is the ordinary way a vendor shipping a new model version reaches the governance record, and it carries the same consequence: the asset's `version` increments, every `PINNED` binding pinned to an older asset version drops to `STALE` with `superseded_reason` `ASSET_REAPPROVED`, and every `TestEvaluation` still in `PLANNED` on a binding that just went stale is moved to `VOIDED`, freeing the test window it had reserved."

        PRD §3.3: "The use case's `cleared_gate_count` and `open_conditions_count` are recomputed and the use case is pushed `READY_FOR_APPROVAL → UNDER_REVIEW`."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_referential_on_approve
        """
        chain = _ready_high_tier_pushed_back_with_a_behind_binding(api)

        assert_use_case(chain.use_case, status="UNDER_REVIEW", cleared_gate_count=3)
        assert_model_asset(
            read_asset(api, chain.asset_id), version=3, status="APPROVED_FOR_USE"
        )
        bindings = list_bindings(api, chain.use_case_id)
        assert len(bindings) == 1, f"expected one binding, got {len(bindings)}"
        assert_model_binding(
            bindings[0],
            pinned_model_version=2,
            status="STALE",
            superseded_reason=SUPERSEDED_ASSET_REAPPROVED,
        )

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.USE_CASE_NOT_READY_FOR_APPROVAL,
        )

    def test_the_rejected_approval_writes_nothing(self, api):
        """PRD §3.7: "On success the use case moves `READY_FOR_APPROVAL → APPROVED`. A `ClassificationSnapshot` with `variant` `DEPLOYMENT_FINAL` is appended under the current `classification_cycle_index`, recording the frozen `cleared_gate_count` and `passed_eval_count`, the `control_credit` and `vendor_penalty` applied, and the resulting score and tier. `control_credit`, `vendor_penalty`, `final_risk_score` and `final_risk_tier` are written onto the use case, `approved_by_user_id` records the signing `X-User-ID`, `monitoring_posture` is set to `HEALTHY`, and a `GovernanceLedgerEntry` of type `APPROVAL_GRANTED` is appended with a `reach_delta` of plus the use case's `deployed_headcount_reach` and a `debt_delta` of 0.00. The use case's `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_referential_on_approve
        """
        chain = _ready_high_tier_pushed_back_with_a_behind_binding(api)
        version_before = chain.use_case["version"]

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.USE_CASE_NOT_READY_FOR_APPROVAL,
        )

        use_case = read_use_case(api, chain.use_case_id)
        assert_use_case(
            use_case,
            status="UNDER_REVIEW",
            version=version_before,
            approved_at=None,
            approved_by_user_id=None,
            final_risk_tier=None,
            final_risk_score=None,
        )

        entries = list_ledger(api, chain.use_case_id, limit=100)
        assert "APPROVAL_GRANTED" not in entry_types(entries), entry_types(entries)

        variants = [
            snapshot["variant"]
            for snapshot in list_snapshots(api, chain.use_case_id, limit=100)
        ]
        assert "DEPLOYMENT_FINAL" not in variants, variants

        summary = read_summary(api)
        assert summary["portfolio_approved_reach"] == 0
        assert_reach_conserved(summary)

    def test_the_binding_check_surfaces_only_once_the_lifecycle_blocker_is_gone(
        self, api
    ):
        """PRD §2.9: "The order below is normative: checks are evaluated top to bottom and the **first** one that fails determines the response. A later check never masks an earlier one."

        PRD §3.7: "A `ModelBinding` with status `PINNED` must exist, or it fails with `ERR_MODEL_BINDING_MISSING`, and that binding's `pinned_model_version` must still equal its asset's current `version`, or it fails with `ERR_MODEL_BINDING_STALE`."

        PRD §3.3: "When, after this clearance, every non-`VOIDED` gate on the use case is `CLEARED` and `cleared_gate_count` equals the number of entries in `required_gate_types`, the use case bubbles `UNDER_REVIEW → READY_FOR_APPROVAL`."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_referential_on_approve
        """
        chain = _ready_high_tier_pushed_back_with_a_behind_binding(api)

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.USE_CASE_NOT_READY_FOR_APPROVAL,
        )

        clear_gate(api, chain.gate_id("BUSINESS"), "BUSINESS")
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="READY_FOR_APPROVAL",
            cleared_gate_count=4,
        )

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.MODEL_BINDING_MISSING,
        )


class TestBusinessSafetyPrecedesBusinessFiscalOnApprove:
    """An approval violating both the safety-flag check and the portfolio cap."""

    def test_the_raised_safety_flag_wins_over_the_portfolio_reach_cap(self, api):
        """PRD §2.9: "The order below is normative: checks are evaluated top to bottom and the **first** one that fails determines the response. A later check never masks an earlier one."

        PRD §2.9: "22. The use case's `safety_flag` is false — `ERR_BIAS_EVALUATION_FAILED` (422), on approval."

        PRD §2.9: "41. When — and only when — the finalization has produced a `final_risk_tier` of `HIGH`, the portfolio's high-tier reach after this approval must not exceed its cap — `ERR_PORTFOLIO_REACH_CAP_EXCEEDED` (422), on approval. This is the last check in the ladder and is evaluated after the finalization arithmetic has run. A use case whose final tier is `LIMITED` or `MINIMAL` never consults the cap at all."

        PRD §3.4: "The `safety_flag` therefore reads true precisely when some `BIAS` evaluation on the use case has ended `FAILED` and no later `BIAS` evaluation has ended `PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_precedes_business_fiscal_on_approve
        """
        chain = _ready_high_tier_with_failed_bias_and_oversized_reach(api)

        assert_use_case(
            chain.use_case,
            status="READY_FOR_APPROVAL",
            risk_tier="HIGH",
            safety_flag=True,
            deployed_headcount_reach=300000,
            cleared_gate_count=4,
        )
        assert chain.use_case["deployed_headcount_reach"] > PORTFOLIO_HIGH_TIER_REACH_CAP
        assert_test_evaluation(
            chain.evaluations["BIAS_FAILED"], eval_type="BIAS", status="FAILED"
        )
        assert_test_evaluation(
            chain.evaluations["BIAS_PASSED"], eval_type="BIAS", status="PASSED"
        )

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.BIAS_EVALUATION_FAILED,
        )

    def test_the_safety_rejection_writes_no_finalization(self, api):
        """PRD §3.7: "On success the use case moves `READY_FOR_APPROVAL → APPROVED`. A `ClassificationSnapshot` with `variant` `DEPLOYMENT_FINAL` is appended under the current `classification_cycle_index`, recording the frozen `cleared_gate_count` and `passed_eval_count`, the `control_credit` and `vendor_penalty` applied, and the resulting score and tier. `control_credit`, `vendor_penalty`, `final_risk_score` and `final_risk_tier` are written onto the use case, `approved_by_user_id` records the signing `X-User-ID`, `monitoring_posture` is set to `HEALTHY`, and a `GovernanceLedgerEntry` of type `APPROVAL_GRANTED` is appended with a `reach_delta` of plus the use case's `deployed_headcount_reach` and a `debt_delta` of 0.00. The use case's `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_precedes_business_fiscal_on_approve
        """
        chain = _ready_high_tier_with_failed_bias_and_oversized_reach(api)

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.BIAS_EVALUATION_FAILED,
        )

        use_case = read_use_case(api, chain.use_case_id)
        assert_use_case(
            use_case,
            status="READY_FOR_APPROVAL",
            final_risk_tier=None,
            final_risk_score=None,
            approved_at=None,
            approved_by_user_id=None,
        )

        variants = [
            snapshot["variant"]
            for snapshot in list_snapshots(api, chain.use_case_id, limit=100)
        ]
        assert "DEPLOYMENT_FINAL" not in variants, variants
        assert "APPROVAL_GRANTED" not in entry_types(
            list_ledger(api, chain.use_case_id, limit=100)
        )

        summary = read_summary(api)
        assert summary["portfolio_approved_reach_high_tier"] == 0
        assert summary["portfolio_approved_reach"] == 0
        assert_reach_conserved(summary)

    def test_the_reach_cap_surfaces_only_once_the_safety_flag_clears(self, api):
        """PRD §3.4: "A `PASSED` run of any type sets `observed_metric_value` and `completed_at`, and if its `eval_type` is `BIAS` it additionally clears the use case's `safety_flag` to false."

        PRD §3.7: "Only after step 4 has produced `final_risk_tier`, and only when that tier is `HIGH`, does the portfolio limit apply. The sum of `deployed_headcount_reach` over every use case already in an inventory status whose `final_risk_tier` is `HIGH`, plus this use case's own `deployed_headcount_reach`, must not exceed 250,000 individuals; exceeding it is rejected with `ERR_PORTFOLIO_REACH_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_precedes_business_fiscal_on_approve
        """
        chain = _ready_high_tier_with_failed_bias_and_oversized_reach(api)

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.BIAS_EVALUATION_FAILED,
        )

        remedial = run_evaluation(
            api,
            chain.binding_id,
            "BIAS",
            *REMEDIAL_BIAS_WINDOW,
            0.8100,
            1000,
            chain.use_case_id,
        )
        assert_test_evaluation(remedial, eval_type="BIAS", status="PASSED")
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            safety_flag=False,
            status="READY_FOR_APPROVAL",
        )

        validate_error(
            _attempt_approval(api, chain.use_case_id),
            ApiErrorId.PORTFOLIO_REACH_CAP_EXCEEDED,
        )


class TestBiasMetricAndSampleSizeExactlyOnTheirThresholds:
    """The two inclusive comparisons a BIAS run at the HIGH-tier profile makes."""

    def test_a_run_exactly_on_both_thresholds_passes(self, api):
        """PRD §3.4: "The run lands in `PASSED` when `observed_metric_value` is at least `required_metric_threshold` **and** `sample_size` is at least `required_sample_size`; a value exactly equal to the threshold passes, because both comparisons are inclusive. If either comparison fails, the run lands in `FAILED`. Metrics are compared at the four decimal places supplied with no rounding beforehand."

        PRD §3.4: "At the moment of scheduling, and never again, the evaluation freezes a threshold profile from the parent use case's provisional `risk_tier`. `required_metric_name` is the field the profile will score: `worst_group_parity_ratio` for a `BIAS` run, `adversarial_pass_rate` for a `ROBUSTNESS` run, `grounded_accuracy` for a `HALLUCINATION` run, and `adversarial_pass_rate` again for a `SECURITY_REDTEAM` run. `required_metric_threshold` is drawn from the tier: at `HIGH` the thresholds are 0.80 for `BIAS`, 0.90 for `ROBUSTNESS`, 0.95 for `HALLUCINATION` and 0.95 for `SECURITY_REDTEAM`; at `LIMITED` they are 0.70, 0.80, 0.85 and 0.85 respectively; at `MINIMAL` they are 0.60, 0.70, 0.75 and 0.75; and at `PROHIBITED` every threshold is 1.00. `required_sample_size` is likewise drawn from the tier: 100 scored examples at `MINIMAL`, 300 at `LIMITED`, and 1000 at both `HIGH` and `PROHIBITED`."

        PRD §3.2: "Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        Design: Difficulty/boundary_precision_check/bias_metric_and_sample_size_exactly_on_their_thresholds
        """
        chain = exactly_seventy_high_use_case(api)
        assert_use_case(chain.use_case, risk_score=70, risk_tier="HIGH")

        scheduled = schedule_evaluation(
            api, chain.binding_id, "BIAS", *BIAS_PROBE_WINDOWS[0], chain.use_case_id
        )
        assert_test_evaluation(
            scheduled,
            status="PLANNED",
            required_metric_name="worst_group_parity_ratio",
            required_sample_size=1000,
        )
        assert scheduled["required_metric_threshold"] == pytest.approx(0.80, abs=0.01)

        completed = complete_evaluation(api, scheduled["id"], 0.8000, 1000)

        assert_test_evaluation(completed, status="PASSED", sample_size=1000)
        assert_metric_value(completed["observed_metric_value"], 0.8000)
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            safety_flag=False,
            status="UNDER_REVIEW",
        )

    def test_a_ratio_one_ten_thousandth_below_the_threshold_fails(self, api):
        """PRD §3.4: "The run lands in `PASSED` when `observed_metric_value` is at least `required_metric_threshold` **and** `sample_size` is at least `required_sample_size`; a value exactly equal to the threshold passes, because both comparisons are inclusive. If either comparison fails, the run lands in `FAILED`. Metrics are compared at the four decimal places supplied with no rounding beforehand."

        Design: Difficulty/boundary_precision_check/bias_metric_and_sample_size_exactly_on_their_thresholds
        """
        chain = exactly_seventy_high_use_case(api)

        scheduled = schedule_evaluation(
            api, chain.binding_id, "BIAS", *BIAS_PROBE_WINDOWS[0], chain.use_case_id
        )
        assert scheduled["required_metric_threshold"] == pytest.approx(0.80, abs=0.01)

        completed = complete_evaluation(api, scheduled["id"], 0.7999, 1000)

        assert_test_evaluation(completed, status="FAILED", sample_size=1000)
        assert_metric_value(completed["observed_metric_value"], 0.7999)

    def test_a_sample_size_one_short_of_the_minimum_fails(self, api):
        """PRD §3.4: "The run lands in `PASSED` when `observed_metric_value` is at least `required_metric_threshold` **and** `sample_size` is at least `required_sample_size`; a value exactly equal to the threshold passes, because both comparisons are inclusive. If either comparison fails, the run lands in `FAILED`. Metrics are compared at the four decimal places supplied with no rounding beforehand."

        Design: Difficulty/boundary_precision_check/bias_metric_and_sample_size_exactly_on_their_thresholds
        """
        chain = exactly_seventy_high_use_case(api)

        scheduled = schedule_evaluation(
            api, chain.binding_id, "BIAS", *BIAS_PROBE_WINDOWS[0], chain.use_case_id
        )
        assert_test_evaluation(scheduled, required_sample_size=1000)

        completed = complete_evaluation(api, scheduled["id"], 0.8000, 999)

        assert_test_evaluation(completed, status="FAILED", sample_size=999)
        assert_metric_value(completed["observed_metric_value"], 0.8000)

    def test_the_last_failing_run_leaves_the_flag_up_and_the_intake_pushed_back(
        self, api
    ):
        """PRD §3.4: "A `FAILED` run also sets `observed_metric_value` and `completed_at`, but if its `eval_type` is `BIAS` it raises the use case's `safety_flag` to true, and — whatever its type — if the use case is currently in `UNDER_REVIEW` or `READY_FOR_APPROVAL` it pushes the use case to `CHANGES_REQUESTED`."

        PRD §3.4: "The `safety_flag` therefore reads true precisely when some `BIAS` evaluation on the use case has ended `FAILED` and no later `BIAS` evaluation has ended `PASSED`."

        Design: Difficulty/boundary_precision_check/bias_metric_and_sample_size_exactly_on_their_thresholds
        """
        chain = exactly_seventy_high_use_case(api)
        runs = [(0.8000, 1000), (0.7999, 1000), (0.8000, 999)]
        outcomes = []
        for window, (value, samples) in zip(BIAS_PROBE_WINDOWS, runs):
            scheduled = schedule_evaluation(
                api, chain.binding_id, "BIAS", *window, chain.use_case_id
            )
            outcomes.append(complete_evaluation(api, scheduled["id"], value, samples))

        assert [run["status"] for run in outcomes] == ["PASSED", "FAILED", "FAILED"]
        for run, (value, samples) in zip(outcomes, runs):
            assert_metric_value(run["observed_metric_value"], value)
            assert run["sample_size"] == samples

        assert_use_case(
            read_use_case(api, chain.use_case_id),
            safety_flag=True,
            status="CHANGES_REQUESTED",
        )


class TestIncidentContainmentDeadlineAtTheExactSecond:
    """Containment recorded at the deadline instant and one second past it."""

    def test_two_sev2_reports_share_the_same_derived_deadline(self, api):
        """PRD §3.8: "The containment clock is derived at reporting time. The effective tier is the use case's `final_risk_tier` when that is non-null, and its provisional `risk_tier` otherwise. `containment_hours` is the base allowance for the severity — 4 hours for `SEV1`, 24 hours for `SEV2`, 72 hours for `SEV3` — multiplied by a tier speed factor of 1.5 for `MINIMAL`, 1.0 for `LIMITED`, 0.5 for `HIGH` and 0.5 for `PROHIBITED`, with the product rounded up to the next whole hour. `containment_deadline_at` is `detected_at` plus that many hours."

        Design: Difficulty/boundary_precision_check/incident_containment_deadline_at_the_exact_second
        """
        chain = _limited_approval_with_two_sev2_incidents(api)
        assert_use_case(chain.use_case, status="APPROVED", final_risk_tier="LIMITED")

        for reported in chain.incidents:
            incident = read_incident(api, reported["id"])
            assert_monitoring_incident(
                incident,
                status="OPEN",
                severity="SEV2",
                category="DRIFT",
                containment_hours=24,
            )
            assert incident["containment_hours"] == expected_containment_hours(
                "SEV2", "LIMITED"
            )
            assert_iso_instant(incident["detected_at"], DEFAULT_CLOCK)
            assert_iso_instant(
                incident["containment_deadline_at"], SEV2_LIMITED_DEADLINE
            )

    def test_containment_at_the_deadline_instant_contains(self, api):
        """PRD §3.8: "When the incident is `OPEN` and the current logical instant is at or before `containment_deadline_at`, it moves `OPEN → CONTAINED` and `contained_at` is stamped with the current instant."

        PRD §2.5: "Instant comparisons are exact to the second in UTC. No rounding, truncation or timezone conversion is applied anywhere in temporal arithmetic."

        Design: Difficulty/boundary_precision_check/incident_containment_deadline_at_the_exact_second
        """
        chain = _limited_approval_with_two_sev2_incidents(api)
        move_clock(api, SEV2_LIMITED_DEADLINE)

        contained = validate_success(
            api.contain_incident(
                chain.incidents[0]["id"],
                {"reported_to_regulator": False},
                headers=SECURITY_REVIEWER,
            ),
            expected_status=200,
        )

        assert_monitoring_incident(contained, status="CONTAINED", severity="SEV2")
        assert_iso_instant(contained["contained_at"], SEV2_LIMITED_DEADLINE)
        assert_iso_instant(
            contained["containment_deadline_at"], SEV2_LIMITED_DEADLINE
        )

    def test_containment_one_second_past_the_deadline_escalates(self, api):
        """PRD §3.8: "When the incident is `OPEN` and the current instant is strictly after `containment_deadline_at`, the very same action instead moves it `OPEN → ESCALATED`, and `contained_at` stays null — an escalated incident still counts as unresolved for posture purposes, so the posture does not improve."

        PRD §2.5: "Instant comparisons are exact to the second in UTC. No rounding, truncation or timezone conversion is applied anywhere in temporal arithmetic."

        Design: Difficulty/boundary_precision_check/incident_containment_deadline_at_the_exact_second
        """
        chain = _limited_approval_with_two_sev2_incidents(api)
        move_clock(api, plus_seconds(SEV2_LIMITED_DEADLINE, 1))

        escalated = validate_success(
            api.contain_incident(
                chain.incidents[1]["id"],
                {"reported_to_regulator": False},
                headers=SECURITY_REVIEWER,
            ),
            expected_status=200,
        )

        assert_monitoring_incident(
            escalated, status="ESCALATED", severity="SEV2", contained_at=None
        )
        assert_iso_instant(
            escalated["containment_deadline_at"], SEV2_LIMITED_DEADLINE
        )
        assert escalated["containment_hours"] == 24

    def test_the_boundary_pair_leaves_one_unresolved_incident_and_a_watch_posture(
        self, api
    ):
        """PRD §3.8: "Either branch re-derives the use case's `monitoring_posture`."

        PRD §3.8: "Posture is derived from unresolved incidents each time an incident is reported, contained or resolved, and it considers only incidents on that use case whose status is `OPEN` or `ESCALATED`; `CONTAINED` and `RESOLVED` incidents are excluded. If any unresolved incident carries `SEV1`, `monitoring_posture` becomes `IMPAIRED`. Otherwise, if there is at least one unresolved incident of any severity, it becomes `WATCH`. With none outstanding, it becomes `HEALTHY`."

        PRD §3.8: "Note that when a posture returns to `HEALTHY` on containment, a suspended use case is *not* reinstated here — reinstatement happens only on resolution."

        Design: Difficulty/boundary_precision_check/incident_containment_deadline_at_the_exact_second
        """
        chain = _limited_approval_with_two_sev2_incidents(api)

        move_clock(api, SEV2_LIMITED_DEADLINE)
        contained = validate_success(
            api.contain_incident(
                chain.incidents[0]["id"], headers=SECURITY_REVIEWER
            ),
            expected_status=200,
        )
        move_clock(api, plus_seconds(SEV2_LIMITED_DEADLINE, 1))
        escalated = validate_success(
            api.contain_incident(
                chain.incidents[1]["id"], headers=SECURITY_REVIEWER
            ),
            expected_status=200,
        )

        assert_monitoring_incident(contained, status="CONTAINED")
        assert_monitoring_incident(escalated, status="ESCALATED")
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="APPROVED",
            monitoring_posture=POSTURE_WATCH,
        )
