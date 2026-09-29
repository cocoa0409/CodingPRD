"""Corner probes for the risk/vendor/oversight arithmetic, the ordered rejection
ladder, and the endpoint surfaces that read or drive it.

Every test builds its own preconditions: the runner restarts the server with an
empty database before each one, so nothing survives from the test above it.
"""

import pytest

from test_helpers import (
    ASSESSMENT_GRADE_D,
    ASSET_NOT_APPROVED_STATUS_ON_ASSET_ACTION,
    DEFAULT_CLOCK,
    EVAL_WINDOWS,
    FIRST_PARTY_ASSET,
    LEGAL_REVIEWER,
    LIMITED_EU_USE_CASE,
    LIMITED_USE_CASE,
    MINIMAL_USE_CASE,
    OFFICER,
    PRIVACY_REVIEWER,
    REQUESTER,
    ROLE_OFFICER,
    SECURITY_REVIEWER,
    THIRD_PARTY_ASSET_GRAYLINE,
    USER_PRIVACY_1,
    VARIANT_CONSERVATIVE,
    ApiErrorId,
    assert_classification_snapshot,
    assert_iso_instant,
    assert_ledger_entry,
    assert_model_asset,
    assert_model_binding,
    assert_monitoring_incident,
    assert_no_ledger_entries,
    assert_oversight_design,
    assert_reach_conserved,
    assert_review_gate,
    assert_shadow_deployment,
    assert_test_evaluation,
    assert_use_case,
    assert_vendor_assessment,
    asset_revision_payload,
    build_user_headers,
    classified_use_case,
    classify_payload,
    current_version,
    design_decision_payload,
    discover_shadow,
    entry_types,
    expected_adequacy_score,
    expected_base_score,
    expected_containment_hours,
    expected_effective_retention_days,
    expected_grace_days,
    expected_jurisdiction_points,
    expected_posture,
    expected_terms_risk_points,
    file_design,
    file_use_case,
    grade_for_points,
    grant_grace_payload,
    limited_use_case_under_review,
    limited_use_case_with_binding,
    list_bindings,
    list_ledger,
    list_snapshots,
    minimal_approved_use_case,
    minimal_use_case_under_review,
    monitoring_incident_payload,
    move_clock,
    pin_clock,
    plus_days,
    plus_hours,
    prohibited_rejected_use_case,
    read_asset,
    read_shadow,
    read_use_case,
    reassessment_payload,
    register_asset,
    report_incident,
    revocation_payload,
    shadow_deployment_past_grace,
    take_up_and_clear,
    take_up_gate,
    use_case_payload,
    use_case_revision_payload,
    use_case_under_reassessment,
    use_case_with_eu_notice,
    validate_error,
    validate_paginated,
    validate_success,
)

# ───────────────────────────── calculations ─────────────────────────────────


def test_jurisdiction_points_count_only_the_high_scrutiny_jurisdictions(api):
    """PRD §3.2: "Finally, `jurisdiction_points` is 3 points for each declared jurisdiction that is one of the three high-scrutiny jurisdictions `EU`, `UK` and `US_CO` — a use case declaring all three of those plus `US_FED` therefore earns 9 points, not 12. The five contributions add up to `base_score`."

    PRD §3.2: "Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`."

    PRD §3.2: "Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

    PRD §3.2: "`required_gate_types` is set from the provisional tier in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`: a `MINIMAL` tier demands only the `BUSINESS` gate, a `LIMITED` tier demands `PRIVACY` and `BUSINESS`, a `HIGH` tier demands all four, and a `PROHIBITED` tier demands none."

    Design: Corner/calculations/risk_score_counts_only_high_scrutiny_jurisdictions
    """
    pin_clock(api)
    intake = use_case_payload(
        title="Multi-region marketing copy assistant",
        business_unit="Marketing",
        description="drafts localised campaign copy for regional review",
        affects_individuals=True,
        decision_autonomy="ADVISORY",
        data_sensitivity="INTERNAL",
        individual_impact="MATERIAL",
        jurisdictions=["EU", "US_CA", "US_FED", "UK"],
        deployed_headcount_reach=1000,
    )
    use_case = file_use_case(api, intake)

    response = api.classify_use_case(
        use_case["id"], classify_payload(use_case["version"]), headers=OFFICER
    )
    classified = validate_success(response, expected_status=200)

    # Only EU and UK are high-scrutiny here; US_CA and US_FED earn nothing.
    assert expected_jurisdiction_points(intake["jurisdictions"]) == 6
    assert expected_base_score(intake) == 39

    assert_use_case(
        classified,
        status="UNDER_REVIEW",
        risk_score=39,
        risk_tier="LIMITED",
        required_gate_types=["PRIVACY", "BUSINESS"],
        classification_cycle_index=1,
        classification_stale=False,
    )

    snapshots = list_snapshots(api, use_case["id"])
    assert len(snapshots) == 1
    assert_classification_snapshot(
        snapshots[0],
        variant="INTAKE_PROVISIONAL",
        cycle_index=1,
        impact_points=25,
        autonomy_points=0,
        sensitivity_points=6,
        reach_points=2,
        jurisdiction_points=6,
        base_score=39,
        vendor_penalty=0,
        control_credit=0,
        risk_score=39,
        risk_tier="LIMITED",
        forced_prohibited=False,
    )


def test_grade_d_assessment_applies_every_conservative_constant(api):
    """PRD §3.1: "A new assessment lands in status `SUBMITTED` with `terms_variant` set to `CONSERVATIVE_LEGAL`, and it is graded immediately under that variant."

    PRD §3.1: "Grading turns the declared terms into a `terms_risk_points` total and bands that total into a `terms_grade`. Five contributions are added. Provenance contributes nothing when it is `DOCUMENTED_LICENSED`, 8 points when it is `DOCUMENTED_MIXED`, and 20 points when it is `UNDISCLOSED`; under the conservative variant an `UNDISCLOSED` provenance carries a further surcharge of 10 points on top of that 20. Output rights contribute nothing for `FULL_ASSIGNMENT`, 6 points for `LICENSE_WITH_RESTRICTIONS` and 16 points for `VENDOR_RETAINS`. Retention contributes according to the `effective_retention_days` the variant scored: nothing when that figure is at most 30 days, 5 points when it is above 30 and at most 90, 10 points when it is above 90 and at most 365, and 18 points when it exceeds 365. A further 6 points are added when `retention_opt_out` is false, and nothing when it is true. A final 5 points are added when `subprocessors_disclosed` is false, and nothing when it is true. The total is banded into a grade: at most 8 points is `A`, above 8 and at most 20 is `B`, above 20 and at most 34 is `C`, and anything above 34 is `D`."

    PRD §3.1: "Under `CONSERVATIVE_LEGAL`, `effective_retention_days` is taken as a worst-case assumption of 3650 days whenever `retention_days` is null **or** whenever `retention_opt_out` is false, and only otherwise is the declared `retention_days` used; the `UNDISCLOSED` provenance surcharge of 10 points also applies."

    PRD §3.1: "accepting moves the assessment `SUBMITTED → ACCEPTED` **and** copies its `terms_grade` onto the parent asset's `vendor_terms_grade`"

    Design: Corner/calculations/vendor_terms_grade_d_applies_every_declared_constant
    """
    pin_clock(api)
    asset = register_asset(api, dict(THIRD_PARTY_ASSET_GRAYLINE))

    response = api.create_vendor_assessment(
        asset["id"], dict(ASSESSMENT_GRADE_D), headers=LEGAL_REVIEWER
    )
    assessment = validate_success(response, expected_status=201)

    assert expected_effective_retention_days(ASSESSMENT_GRADE_D, VARIANT_CONSERVATIVE) == 3650
    assert expected_terms_risk_points(ASSESSMENT_GRADE_D, VARIANT_CONSERVATIVE) == 75
    assert grade_for_points(75) == "D"

    assert_vendor_assessment(
        assessment,
        status="SUBMITTED",
        terms_variant="CONSERVATIVE_LEGAL",
        effective_retention_days=3650,
        terms_risk_points=75,
        terms_grade="D",
        retention_days=400,
        retention_opt_out=False,
        subprocessors_disclosed=False,
        decided_by_user_id=None,
        decided_at=None,
    )

    # No acceptance has happened, so the grade has not landed on the asset.
    assert_model_asset(
        read_asset(api, asset["id"]),
        status="REGISTERED",
        version=1,
        vendor_terms_grade=None,
        active_binding_count=0,
        enforced_shadow_count=0,
    )


def test_containment_deadline_crosses_the_month_boundary_on_a_minimal_tier(api):
    """PRD §3.8: "The effective tier is the use case's `final_risk_tier` when that is non-null, and its provisional `risk_tier` otherwise. `containment_hours` is the base allowance for the severity — 4 hours for `SEV1`, 24 hours for `SEV2`, 72 hours for `SEV3` — multiplied by a tier speed factor of 1.5 for `MINIMAL`, 1.0 for `LIMITED`, 0.5 for `HIGH` and 0.5 for `PROHIBITED`, with the product rounded up to the next whole hour. `containment_deadline_at` is `detected_at` plus that many hours."

    PRD §2.5: "Hour arithmetic (incident containment) is exact hour addition in UTC. Instant comparisons are exact to the second in UTC. No rounding, truncation or timezone conversion is applied anywhere in temporal arithmetic."

    PRD §3.8: "Otherwise, if there is at least one unresolved incident of any severity, it becomes `WATCH`."

    PRD §3.8: "When posture re-derivation leaves a use case that is in `APPROVED` or `UNDER_REASSESSMENT` at `IMPAIRED`, that use case moves to `SUSPENDED`"

    Design: Corner/calculations/containment_deadline_crosses_a_month_boundary_on_minimal_tier
    """
    pin_clock(api, "2026-08-30T20:00:00Z")
    use_case = classified_use_case(api, MINIMAL_USE_CASE)
    assert_use_case(use_case, risk_tier="MINIMAL", final_risk_tier=None)

    response = api.create_monitoring_incident(
        monitoring_incident_payload(
            use_case["id"],
            "SEV3",
            "2026-08-30T18:00:00Z",
            category="DRIFT",
            summary="relevance drift observed on long-tail queries",
        ),
        headers=SECURITY_REVIEWER,
    )
    incident = validate_success(response, expected_status=201)

    assert expected_containment_hours("SEV3", "MINIMAL") == 108
    assert_monitoring_incident(
        incident,
        status="OPEN",
        severity="SEV3",
        containment_hours=108,
        contained_at=None,
        resolved_at=None,
        reported_to_regulator=False,
    )
    assert_iso_instant(incident["containment_deadline_at"], "2026-09-04T06:00:00Z")
    assert_iso_instant(
        incident["containment_deadline_at"], plus_hours("2026-08-30T18:00:00Z", 108)
    )

    assert_use_case(
        read_use_case(api, use_case["id"]),
        status="UNDER_REVIEW",
        monitoring_posture="WATCH",
    )


def test_granting_grace_overwrites_the_shadow_deadline_rather_than_accumulating(api):
    """PRD §3.9: "The record lands in status `DISCOVERED` with `grace_days_granted` 0, and `grace_deadline_at` computed as `discovered_at` plus the environment's base grace plus `grace_days_granted` days. Base grace is generous where the risk is low and short where it is not: a month (30 days) in `SANDBOX`, a fortnight (14 days) in `INTERNAL_PILOT`, and one week (7 days) in `PRODUCTION`."

    PRD §3.9: "It moves the record to `GRACE_GRANTED`, sets `grace_days_granted` to the supplied `grace_days` — **overwriting** any previous grant rather than accumulating on top of it — and recomputes `grace_deadline_at` as `discovered_at` plus base grace plus the new `grace_days_granted` days."

    PRD §2.10: "`enforced_shadow_count` on a `ModelAsset` is the number of shadow deployments on that asset whose status is `ENFORCED_BLOCK`."

    Design: Corner/calculations/shadow_grace_deadline_overwrites_rather_than_accumulates
    """
    pin_clock(api)
    asset = register_asset(api, dict(FIRST_PARTY_ASSET))
    shadow = discover_shadow(api, asset["id"], "SANDBOX", DEFAULT_CLOCK)

    assert_shadow_deployment(
        shadow,
        status="DISCOVERED",
        environment="SANDBOX",
        claimed_use_case_id=None,
        grace_days_granted=0,
    )
    assert_iso_instant(shadow["grace_deadline_at"], "2026-08-31T00:00:00Z")

    response = api.grant_shadow_grace(
        shadow["id"], grant_grace_payload(10), headers=OFFICER
    )
    granted = validate_success(response, expected_status=200)

    assert expected_grace_days("SANDBOX", 10) == 40
    assert_shadow_deployment(granted, status="GRACE_GRANTED", grace_days_granted=10)
    assert_iso_instant(granted["grace_deadline_at"], "2026-09-10T00:00:00Z")
    assert_iso_instant(granted["grace_deadline_at"], plus_days(DEFAULT_CLOCK, 40))

    assert_model_asset(
        read_asset(api, asset["id"]), status="REGISTERED", enforced_shadow_count=0
    )


def test_posture_is_derived_only_from_open_or_escalated_incidents(api):
    """PRD §3.8: "Posture is derived from unresolved incidents each time an incident is reported, contained or resolved, and it considers only incidents on that use case whose status is `OPEN` or `ESCALATED`; `CONTAINED` and `RESOLVED` incidents are excluded. If any unresolved incident carries `SEV1`, `monitoring_posture` becomes `IMPAIRED`. Otherwise, if there is at least one unresolved incident of any severity, it becomes `WATCH`. With none outstanding, it becomes `HEALTHY`."

    PRD §3.8: "When the incident is `OPEN` and the current logical instant is at or before `containment_deadline_at`, it moves `OPEN → CONTAINED` and `contained_at` is stamped with the current instant."

    PRD §3.8: "It moves the incident `CONTAINED → RESOLVED`, stamps `resolved_at`, and re-derives the posture."

    Design: Corner/calculations/monitoring_posture_counts_only_unresolved_incidents
    """
    pin_clock(api)
    use_case = classified_use_case(api, MINIMAL_USE_CASE)
    assert_use_case(use_case, risk_tier="MINIMAL", affects_individuals=False)

    sev3 = report_incident(
        api,
        use_case["id"],
        "SEV3",
        category="DRIFT",
        summary="relevance drift on long-tail queries",
    )
    assert_use_case(read_use_case(api, use_case["id"]), monitoring_posture="WATCH")

    sev1 = report_incident(
        api,
        use_case["id"],
        "SEV1",
        category="HARMFUL_OUTPUT",
        summary="reranker surfaced a restricted internal document",
    )
    assert expected_containment_hours("SEV1", "MINIMAL") == 6
    assert_monitoring_incident(sev1, status="OPEN", containment_hours=6)
    assert_iso_instant(sev1["containment_deadline_at"], "2026-08-01T06:00:00Z")
    assert_use_case(read_use_case(api, use_case["id"]), monitoring_posture="IMPAIRED")

    contained = validate_success(
        api.contain_incident(sev1["id"], headers=SECURITY_REVIEWER),
        expected_status=200,
    )
    assert_monitoring_incident(contained, status="CONTAINED", reported_to_regulator=False)
    assert_iso_instant(contained["contained_at"], DEFAULT_CLOCK)
    assert expected_posture([("CONTAINED", "SEV1"), ("OPEN", "SEV3")]) == "WATCH"
    assert_use_case(read_use_case(api, use_case["id"]), monitoring_posture="WATCH")

    resolved = validate_success(
        api.resolve_incident(sev1["id"], headers=OFFICER), expected_status=200
    )
    assert_monitoring_incident(resolved, status="RESOLVED")
    assert_iso_instant(resolved["resolved_at"], DEFAULT_CLOCK)
    assert_use_case(read_use_case(api, use_case["id"]), monitoring_posture="WATCH")

    open_rows, _ = validate_paginated(
        api.list_monitoring_incidents(
            headers=OFFICER, use_case_id=use_case["id"], status="OPEN"
        )
    )
    assert [row["id"] for row in open_rows] == [sev3["id"]]


def test_inventory_summary_excludes_a_use_case_that_was_never_approved(api):
    """PRD §2.11: "The three statuses `APPROVED`, `UNDER_REASSESSMENT` and `SUSPENDED` constitute the *inventory statuses*: a use case in any of them is live in the governance inventory. `portfolio_approved_reach` is the sum of `deployed_headcount_reach` over every use case in an inventory status, and `portfolio_approved_reach_high_tier` is that same sum restricted to use cases whose `final_risk_tier` is `HIGH`. The sum of `reach_delta` over all ledger entries — `ledger_reach_balance` — must equal `portfolio_approved_reach` at all times."

    PRD §2.11: "`control_debt_index_total` is the sum of `control_debt_index` over every gate whose status is `PENDING`, `IN_REVIEW`, `CONDITIONS_ISSUED` or `CLEARED`; `VOIDED` gates are excluded entirely."

    PRD §2.11: "A reconciliation read exposes both quantities alongside their ledger balances: `inventory_count`, `portfolio_approved_reach`, `portfolio_approved_reach_high_tier`, `control_debt_index_total`, `ledger_reach_balance`, `ledger_debt_balance`, `open_incident_count` and `unapproved_shadow_count`. It is a pure computation and writes nothing."

    Design: Corner/calculations/inventory_summary_excludes_use_cases_that_were_never_approved
    """
    chain = minimal_use_case_under_review(api)
    take_up_and_clear(api, chain.gate_id("BUSINESS"), "BUSINESS")

    assert_use_case(
        read_use_case(api, chain.use_case_id),
        status="READY_FOR_APPROVAL",
        deployed_headcount_reach=500,
        cleared_gate_count=1,
    )

    summary = validate_success(
        api.get_inventory_summary(headers=OFFICER), expected_status=200
    )

    assert summary["inventory_count"] == 0
    assert summary["portfolio_approved_reach"] == 0
    assert summary["portfolio_approved_reach_high_tier"] == 0
    assert summary["control_debt_index_total"] == pytest.approx(0.00, abs=0.01)
    assert summary["ledger_reach_balance"] == 0
    assert summary["ledger_debt_balance"] == pytest.approx(0.00, abs=0.01)
    assert summary["open_incident_count"] == 0
    assert summary["unapproved_shadow_count"] == 0
    assert_reach_conserved(summary)

    ledger = list_ledger(api, chain.use_case_id)
    assert entry_types(ledger) == ["GATE_CLEARED"]
    assert_ledger_entry(ledger[0], entry_type="GATE_CLEARED", reach_delta=0, debt_delta=0.00)


# ───────────────────────────── validations ──────────────────────────────────


def test_oversight_design_two_points_short_is_refused_on_approve(api):
    """PRD §3.5: "The mode base contributes nothing for `NONE`, 30 points for `SAMPLED`, 70 points for `PRE_DECISION_REVIEW` and 90 points for `DUAL_REVIEW`. The sample component applies only when `review_mode` is `SAMPLED`, and is `sample_pct` multiplied by three tenths, taken down to the next whole number, then capped at 30 — so sampling every decision earns the full 30 while sampling half of them earns 15; for every other review mode the sample component is 0 regardless of what `sample_pct` says. The SLA component starts from 20 points and subtracts one point for every whole 6 hours of `escalation_sla_hours`, with the result floored at 0 so it can never go negative — an SLA of 6 hours costs 1 point, an SLA of 240 hours costs the full 20 and leaves nothing. The override component is 10 points when `override_capability` is true and nothing when it is false. `adequacy_score` is the sum of the four, capped at 100."

    PRD §3.5: "At a `LIMITED` tier it is 45, 60, 70 and 80 for those same four autonomy levels."

    PRD §3.5: "Approving moves the design `DRAFT → APPROVED` and requires `adequacy_score` to be at least `required_adequacy_score`; a shortfall is rejected with `ERR_OVERSIGHT_DESIGN_INADEQUATE`. Rejecting moves it `DRAFT → REJECTED` and applies no adequacy test at all."

    Design: Corner/validations/oversight_design_two_points_short_violation
    """
    pin_clock(api)
    use_case = classified_use_case(api, LIMITED_USE_CASE)
    assert_use_case(use_case, risk_tier="LIMITED", decision_autonomy="HUMAN_IN_LOOP")

    thin_design = dict(
        review_mode="SAMPLED",
        sample_pct=40,
        escalation_sla_hours=24,
        reviewer_role="BusinessReviewer",
        override_capability=False,
    )
    design = file_design(api, use_case["id"], **thin_design)

    # 30 mode base + 12 sample + 16 SLA + 0 override = 58, against a required 60.
    assert expected_adequacy_score(thin_design) == 58
    assert_oversight_design(
        design, status="DRAFT", adequacy_score=58, required_adequacy_score=60
    )

    validate_error(
        api.decide_oversight_design(
            design["id"], design_decision_payload("APPROVE"), headers=OFFICER
        ),
        ApiErrorId.OVERSIGHT_DESIGN_INADEQUATE,
    )

    designs, _ = validate_paginated(
        api.list_oversight_designs(use_case["id"], headers=OFFICER)
    )
    assert len(designs) == 1
    assert_oversight_design(
        designs[0], status="DRAFT", decided_by_user_id=None, decided_at=None
    )


def test_privacy_gate_clears_with_a_published_eu_notice(api):
    """PRD §3.3: "A `PRIVACY` gate requires that for every jurisdiction in the use case's `jurisdictions` array there exists a `PUBLISHED` `DisclosureNotice` on that use case for that jurisdiction; a jurisdiction without one fails the clearance with `ERR_DISCLOSURE_NOT_PUBLISHED`."

    PRD §3.6: "Clearing a `PRIVACY` gate requires merely that a `PUBLISHED` notice exists on the use case for each declared jurisdiction."

    PRD §3.3: "Once those pass, the clearance captures `debt_before_clear` from the gate's current `control_debt_index` (this is what makes the compensating reopen exact), zeroes `control_debt_index` to 0.00 and `open_condition_count` to 0, records `cleared_by_user_id` and `cleared_at`, and appends a `GovernanceLedgerEntry` of type `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the captured `debt_before_clear`. The use case's `cleared_gate_count` is recomputed. When, after this clearance, every non-`VOIDED` gate on the use case is `CLEARED` and `cleared_gate_count` equals the number of entries in `required_gate_types`, the use case bubbles `UNDER_REVIEW → READY_FOR_APPROVAL`."

    Design: Corner/validations/privacy_gate_clear_with_published_eu_notice_passes
    """
    chain = use_case_with_eu_notice(api)
    assert_use_case(
        chain.use_case,
        risk_score=52,
        risk_tier="LIMITED",
        required_gate_types=["PRIVACY", "BUSINESS"],
    )
    take_up_gate(api, chain.gate_id("PRIVACY"), "PRIVACY")

    response = api.clear_gate(
        chain.gate_id("PRIVACY"),
        {"decision_note": "notice published and DPIA filed"},
        headers=PRIVACY_REVIEWER,
    )
    gate = validate_success(response, expected_status=200)

    assert_review_gate(
        gate,
        gate_type="PRIVACY",
        status="CLEARED",
        cleared_by_user_id=USER_PRIVACY_1,
        open_condition_count=0,
        control_debt_index=0.00,
    )
    assert_iso_instant(gate["cleared_at"], DEFAULT_CLOCK)

    assert_use_case(
        read_use_case(api, chain.use_case_id),
        status="UNDER_REVIEW",
        cleared_gate_count=1,
    )

    ledger = list_ledger(api, chain.use_case_id)
    assert entry_types(ledger) == ["GATE_CLEARED"]
    assert_ledger_entry(ledger[0], entry_type="GATE_CLEARED", reach_delta=0, debt_delta=0.00)


def test_privacy_gate_clear_without_the_eu_notice_is_refused(api):
    """PRD §3.3: "A `PRIVACY` gate requires that for every jurisdiction in the use case's `jurisdictions` array there exists a `PUBLISHED` `DisclosureNotice` on that use case for that jurisdiction; a jurisdiction without one fails the clearance with `ERR_DISCLOSURE_NOT_PUBLISHED`."

    PRD §3.3: "A `BUSINESS` gate requires no evaluation evidence, no vendor terms and no notices — only the ordinary status, role and segregation checks."

    Design: Corner/validations/privacy_gate_clear_without_eu_notice_violation
    """
    chain = limited_use_case_under_review(api, LIMITED_EU_USE_CASE)
    assert_use_case(chain.use_case, jurisdictions=["EU"], risk_tier="LIMITED")
    take_up_gate(api, chain.gate_id("PRIVACY"), "PRIVACY")

    validate_error(
        api.clear_gate(
            chain.gate_id("PRIVACY"),
            {"decision_note": "attempting to clear before the notice exists"},
            headers=PRIVACY_REVIEWER,
        ),
        ApiErrorId.DISCLOSURE_NOT_PUBLISHED,
    )

    gates, _ = validate_paginated(
        api.list_review_gates(chain.use_case_id, headers=OFFICER, gate_type="PRIVACY")
    )
    assert len(gates) == 1
    assert_review_gate(
        gates[0], status="IN_REVIEW", cleared_by_user_id=None, cleared_at=None
    )

    assert_use_case(
        read_use_case(api, chain.use_case_id),
        status="UNDER_REVIEW",
        cleared_gate_count=0,
    )
    assert_no_ledger_entries(list_ledger(api, chain.use_case_id))


def test_terminal_use_case_outranks_not_in_draft_on_a_classify_retry(api):
    """PRD §2.9: "The order below is normative: checks are evaluated top to bottom and the **first** one that fails determines the response. A later check never masks an earlier one."

    PRD §2.9: "9. `expected_use_case_version` equals the use case's current `version` — `ERR_STALE_USE_CASE_VERSION` (412), on classification, binding creation, oversight-design filing and approval."

    PRD §2.9: "10. The addressed use case, or the parent use case of the addressed child, is not `REJECTED` or `REVOKED` — `ERR_USE_CASE_TERMINAL` (409), on every mutating endpoint whose target resolves to a use case or one of its children."

    PRD §2.9: "11. The use case is in `DRAFT` — `ERR_USE_CASE_NOT_IN_DRAFT` (409), on classification."

    Design: Corner/validations/terminal_precedes_not_in_draft_on_classify
    """
    chain = prohibited_rejected_use_case(api)
    assert_use_case(
        chain.use_case,
        status="REJECTED",
        risk_tier="PROHIBITED",
        rejection_reason="PROHIBITED_COMBINATION",
        classification_cycle_index=1,
    )

    validate_error(
        api.classify_use_case(
            chain.use_case_id,
            classify_payload(current_version(api, chain.use_case_id)),
            headers=OFFICER,
        ),
        ApiErrorId.USE_CASE_TERMINAL,
    )

    assert_use_case(
        read_use_case(api, chain.use_case_id),
        status="REJECTED",
        classification_cycle_index=1,
    )
    assert len(list_snapshots(api, chain.use_case_id)) == 1


def test_blank_user_id_outranks_a_missing_use_case(api):
    """PRD §2.1: "If either header is absent or blank, or if `X-User-Role` is a string outside the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.9: "1. Header presence and role validity — `ERR_UNAUTHENTICATED` (401), on every endpoint."

    PRD §2.9: "3. The `{id}` of a `/use-cases/{id}...` path resolves — `ERR_USE_CASE_NOT_FOUND` (404), on every such path."

    Design: Corner/validations/unauthenticated_precedes_not_found
    """
    pin_clock(api)

    blank_identity = build_user_headers("", ROLE_OFFICER)
    validate_error(
        api.get_use_case("uc_missing_404", headers=blank_identity),
        ApiErrorId.UNAUTHENTICATED,
    )


# ────────────────────────────── endpoints ───────────────────────────────────


def test_model_asset_register_read_approve_and_revise_round_trip(api):
    """PRD §3.1: "A freshly registered asset lands in status `REGISTERED` with `version` 1, `active_binding_count` 0, `enforced_shadow_count` 0 and `vendor_terms_grade` null."

    PRD §3.1: "Clearing an asset for use moves it from `REGISTERED` to `APPROVED_FOR_USE`"

    PRD §3.1: "In both directions, clearing increments the asset's `version`, and that increment is exactly what makes previously pinned bindings stale"

    PRD §3.1: "An `APPROVED_FOR_USE` asset may also be revised in place. A `GovernanceOfficer` may overwrite any combination of `model_version`, `hosting` and `modality`, and at least one of those three must be supplied. This is the ordinary way a vendor shipping a new model version reaches the governance record, and it carries the same consequence: the asset's `version` increments, every `PINNED` binding pinned to an older asset version drops to `STALE` with `superseded_reason` `ASSET_REAPPROVED`, and every `TestEvaluation` still in `PLANNED` on a binding that just went stale is moved to `VOIDED`, freeing the test window it had reserved."

    Design: Corner/endpoints/model_asset_crud_surface_round_trip
    """
    pin_clock(api)

    created = validate_success(
        api.create_model_asset(dict(FIRST_PARTY_ASSET), headers=OFFICER),
        expected_status=201,
    )
    assert_model_asset(
        created,
        status="REGISTERED",
        version=1,
        model_version="1.0.0",
        hosting="INTERNAL",
        modality="TEXT",
        is_third_party=False,
        vendor_terms_grade=None,
    )

    approved = validate_success(
        api.approve_asset_for_use(created["id"], headers=OFFICER), expected_status=200
    )
    assert_model_asset(approved, status="APPROVED_FOR_USE", version=2)

    read_back = validate_success(
        api.get_model_asset(created["id"], headers=SECURITY_REVIEWER),
        expected_status=200,
    )
    assert_model_asset(
        read_back,
        id=created["id"],
        status="APPROVED_FOR_USE",
        version=2,
        active_binding_count=0,
        enforced_shadow_count=0,
    )

    revised = validate_success(
        api.update_model_asset(
            created["id"],
            asset_revision_payload(model_version="1.0.1"),
            headers=OFFICER,
        ),
        expected_status=200,
    )
    assert_model_asset(
        revised,
        status="APPROVED_FOR_USE",
        version=3,
        model_version="1.0.1",
        hosting="INTERNAL",
        modality="TEXT",
    )

    bindings, _ = validate_paginated(
        api.list_asset_model_bindings(created["id"], headers=OFFICER)
    )
    assert bindings == []


def test_revoking_a_never_approved_use_case_moves_no_reach(api):
    """PRD §3.8: "Revocation is the terminal exit, available to a `GovernanceOfficer` against a use case in `READY_FOR_APPROVAL`, `APPROVED`, `UNDER_REASSESSMENT` or `SUSPENDED`, and it takes a free-text `revocation_reason`."

    PRD §3.8: "The use case moves to `REVOKED`, `revoked_at` is stamped with the current logical instant, `revocation_reason` records the supplied reason, and a `GovernanceLedgerEntry` of type `APPROVAL_REVOKED` is appended. Its `reach_delta` is minus the use case's `deployed_headcount_reach` when the use case was in an inventory status — `APPROVED`, `UNDER_REASSESSMENT` or `SUSPENDED` — and 0 when it was merely `READY_FOR_APPROVAL` and therefore never counted toward the portfolio. Its `debt_delta` is 0.00."

    PRD §3.8: "Every `ModelBinding` of the use case whose status is `PINNED` or `STALE` moves to `RETIRED` with `superseded_reason` `USE_CASE_REVOKED`, and a `GovernanceLedgerEntry` of type `BINDING_RETIRED` is appended for each retired binding."

    PRD §2.8: "A record whose parent use case has reached a terminal status is frozen. If the addressed use case — or the parent use case of the addressed child record — is `REJECTED` or `REVOKED`, every mutating request against it is rejected with `ERR_USE_CASE_TERMINAL` (HTTP 409). Reads are unaffected."

    Design: Corner/endpoints/revoke_action_on_never_approved_use_case_moves_no_reach
    """
    chain = minimal_use_case_under_review(api)
    take_up_and_clear(api, chain.gate_id("BUSINESS"), "BUSINESS")
    assert_use_case(
        read_use_case(api, chain.use_case_id), status="READY_FOR_APPROVAL"
    )
    move_clock(api, "2026-08-02T00:00:00Z")

    response = api.revoke_use_case(
        chain.use_case_id,
        revocation_payload(revocation_reason="business unit withdrew the request"),
        headers=OFFICER,
    )
    revoked = validate_success(response, expected_status=200)

    assert_use_case(
        revoked,
        status="REVOKED",
        revocation_reason="business unit withdrew the request",
    )
    assert_iso_instant(revoked["revoked_at"], "2026-08-02T00:00:00Z")

    ledger = list_ledger(api, chain.use_case_id)
    assert entry_types(ledger) == ["GATE_CLEARED", "APPROVAL_REVOKED"]
    assert_ledger_entry(
        ledger[1], entry_type="APPROVAL_REVOKED", reach_delta=0, debt_delta=0.00
    )

    summary = validate_success(
        api.get_inventory_summary(headers=OFFICER), expected_status=200
    )
    assert summary["portfolio_approved_reach"] == 0
    assert summary["ledger_reach_balance"] == 0

    validate_error(
        api.update_use_case(
            chain.use_case_id, use_case_revision_payload(), headers=REQUESTER
        ),
        ApiErrorId.USE_CASE_TERMINAL,
    )


def test_governance_sweep_enforces_an_elapsed_shadow_grace(api):
    """PRD §3.9: "It reports back how much work it did: `reassessments_opened`, `approvals_suspended`, `shadows_enforced`, `assets_restricted` and `assessments_expired`."

    PRD §3.9: "Every shadow deployment in `DISCOVERED` or `GRACE_GRANTED` whose `grace_deadline_at` is strictly before the current logical instant moves to `ENFORCED_BLOCK` (hop 1). Caused by that, the named asset's `enforced_shadow_count` increments by 1, and once that count is at least 1 an asset in `APPROVED_FOR_USE` moves to `RESTRICTED` (hop 2). Caused by that, every `VendorModelAssessment` on the asset with status `ACCEPTED` moves to `EXPIRED` and the asset's `vendor_terms_grade` is set to null (hop 3)."

    PRD §3.1: "When an asset becomes `RESTRICTED`, every `VendorModelAssessment` on it with status `ACCEPTED` is moved to `EXPIRED`, the asset's `vendor_terms_grade` is set back to null, and the asset's `version` increments."

    Design: Corner/endpoints/governance_sweep_bulk_enforces_expired_shadow_grace
    """
    chain = shadow_deployment_past_grace(api, "PRODUCTION")
    shadow = chain.shadows[0]
    assert_shadow_deployment(shadow, status="DISCOVERED", environment="PRODUCTION")
    assert_iso_instant(shadow["grace_deadline_at"], "2026-08-08T00:00:00Z")
    assert_model_asset(chain.asset, status="APPROVED_FOR_USE", version=2)

    sweep = validate_success(
        api.run_governance_sweep(headers=OFFICER), expected_status=200
    )
    assert sweep["reassessments_opened"] == 0
    assert sweep["approvals_suspended"] == 0
    assert sweep["shadows_enforced"] == 1
    assert sweep["assets_restricted"] == 1
    assert sweep["assessments_expired"] == 0

    assert_shadow_deployment(read_shadow(api, shadow["id"]), status="ENFORCED_BLOCK")
    assert_model_asset(
        read_asset(api, chain.asset_id),
        status="RESTRICTED",
        enforced_shadow_count=1,
        version=3,
        vendor_terms_grade=None,
    )


def test_a_second_governance_sweep_re_enforces_nothing(api):
    """PRD §3.9: "It reports back how much work it did: `reassessments_opened`, `approvals_suspended`, `shadows_enforced`, `assets_restricted` and `assessments_expired`."

    PRD §3.1: "The same clearing action also brings an asset back from `RESTRICTED` to `APPROVED_FOR_USE`, with one extra precondition: the asset's `enforced_shadow_count` must be 0, because an asset with an enforced shadow block outstanding cannot be rehabilitated."

    PRD §2.9: "20. The addressed model asset is in a status the requested action has a transition out of: approving for use needs `REGISTERED` or `RESTRICTED`, and a `RESTRICTED` asset additionally needs `enforced_shadow_count` equal to 0, while revising an asset in place needs `APPROVED_FOR_USE` because the revise transition is declared only on that state — `ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE` (409), on asset approve-for-use and asset revision."

    Design: Corner/endpoints/governance_sweep_bulk_enforces_expired_shadow_grace
    """
    chain = shadow_deployment_past_grace(api, "PRODUCTION")
    shadow_id = chain.shadows[0]["id"]

    validate_success(api.run_governance_sweep(headers=OFFICER), expected_status=200)
    enforced_shadow = read_shadow(api, shadow_id)
    restricted_asset = read_asset(api, chain.asset_id)

    second = validate_success(
        api.run_governance_sweep(headers=OFFICER), expected_status=200
    )
    assert second["reassessments_opened"] == 0
    assert second["approvals_suspended"] == 0
    assert second["shadows_enforced"] == 0
    assert second["assets_restricted"] == 0
    assert second["assessments_expired"] == 0

    assert_shadow_deployment(
        read_shadow(api, shadow_id),
        status="ENFORCED_BLOCK",
        version=enforced_shadow["version"],
    )
    assert_model_asset(
        read_asset(api, chain.asset_id),
        status="RESTRICTED",
        enforced_shadow_count=1,
        version=restricted_asset["version"],
    )

    validate_error(
        api.approve_asset_for_use(chain.asset_id, headers=OFFICER),
        ApiErrorId.MODEL_ASSET_NOT_APPROVED_FOR_USE,
        expected_status=ASSET_NOT_APPROVED_STATUS_ON_ASSET_ACTION,
    )


def test_shadow_link_claims_a_matching_approved_use_case(api):
    """PRD §3.9: "**Linking** claims that the deployment turns out to be covered by an existing approval: the officer supplies a `use_case_id`, the record moves to `LINKED` from either `DISCOVERED` or `GRACE_GRANTED`, and `claimed_use_case_id` is set to the supplied value. The link target must be a use case in status `APPROVED` that holds a `ModelBinding` in `PINNED` whose `model_asset_id` equals the shadow deployment's own `model_asset_id`; anything else is rejected with `ERR_SHADOW_LINK_MISMATCH`."

    PRD §3.9: "Base grace is generous where the risk is low and short where it is not: a month (30 days) in `SANDBOX`, a fortnight (14 days) in `INTERNAL_PILOT`, and one week (7 days) in `PRODUCTION`."

    PRD §2.10: "`enforced_shadow_count` on a `ModelAsset` is the number of shadow deployments on that asset whose status is `ENFORCED_BLOCK`."

    Design: Corner/endpoints/shadow_link_associates_with_matching_approved_use_case
    """
    chain = minimal_approved_use_case(api)
    assert_use_case(chain.use_case, status="APPROVED")
    assert_model_binding(
        chain.binding, status="PINNED", model_asset_id=chain.asset_id
    )

    shadow = discover_shadow(api, chain.asset_id, "INTERNAL_PILOT", DEFAULT_CLOCK)
    assert_shadow_deployment(shadow, status="DISCOVERED", claimed_use_case_id=None)
    assert_iso_instant(shadow["grace_deadline_at"], "2026-08-15T00:00:00Z")

    response = api.link_shadow_deployment(
        shadow["id"], {"use_case_id": chain.use_case_id}, headers=OFFICER
    )
    linked = validate_success(response, expected_status=200)

    assert_shadow_deployment(
        linked,
        status="LINKED",
        claimed_use_case_id=chain.use_case_id,
        grace_days_granted=0,
    )
    assert_iso_instant(linked["grace_deadline_at"], "2026-08-15T00:00:00Z")

    assert_model_asset(
        read_asset(api, chain.asset_id),
        status="APPROVED_FOR_USE",
        enforced_shadow_count=0,
    )

    claimed, _ = validate_paginated(
        api.list_shadow_deployments(
            headers=OFFICER, claimed_use_case_id=chain.use_case_id
        )
    )
    assert [row["id"] for row in claimed] == [shadow["id"]]


def test_test_evaluation_read_exposes_the_frozen_limited_tier_profile(api):
    """PRD §3.4: "At the moment of scheduling, and never again, the evaluation freezes a threshold profile from the parent use case's provisional `risk_tier`."

    PRD §3.4: "`required_metric_name` is the field the profile will score: `worst_group_parity_ratio` for a `BIAS` run, `adversarial_pass_rate` for a `ROBUSTNESS` run, `grounded_accuracy` for a `HALLUCINATION` run, and `adversarial_pass_rate` again for a `SECURITY_REDTEAM` run."

    PRD §3.4: "at `LIMITED` they are 0.70, 0.80, 0.85 and 0.85 respectively"

    PRD §3.4: "`required_sample_size` is likewise drawn from the tier: 100 scored examples at `MINIMAL`, 300 at `LIMITED`, and 1000 at both `HIGH` and `PROHIBITED`."

    PRD §3.4: "The new binding lands in status `PINNED` with `pinned_model_version` set to the asset's `version` at that instant and `pinned_at` set to the current logical instant."

    Design: Corner/endpoints/test_evaluation_computed_read_exposes_the_tier_profile
    """
    chain = limited_use_case_with_binding(api)
    assert_use_case(chain.use_case, risk_tier="LIMITED")
    window_start, window_end = EVAL_WINDOWS["BIAS"]

    scheduled = validate_success(
        api.create_test_evaluation(
            {
                "use_case_id": chain.use_case_id,
                "model_binding_id": chain.binding_id,
                "eval_type": "BIAS",
                "window_start_at": window_start,
                "window_end_at": window_end,
            },
            headers=SECURITY_REVIEWER,
        ),
        expected_status=201,
    )

    evaluation = validate_success(
        api.get_test_evaluation(scheduled["id"], headers=SECURITY_REVIEWER),
        expected_status=200,
    )

    assert_test_evaluation(
        evaluation,
        status="PLANNED",
        use_case_id=chain.use_case_id,
        model_binding_id=chain.binding_id,
        eval_type="BIAS",
        required_metric_name="worst_group_parity_ratio",
        required_sample_size=300,
        observed_metric_value=None,
        sample_size=None,
        completed_at=None,
        evidence_uri=None,
    )
    assert evaluation["required_metric_threshold"] == pytest.approx(0.70, abs=0.01)
    assert_iso_instant(evaluation["window_start_at"], window_start)
    assert_iso_instant(evaluation["window_end_at"], window_end)

    bindings = list_bindings(api, chain.use_case_id)
    assert len(bindings) == 1
    assert_model_binding(bindings[0], status="PINNED", pinned_model_version=2)
    assert_model_asset(read_asset(api, chain.asset_id), active_binding_count=1)


def test_completing_a_reassessment_with_suspend_takes_the_suspend_branch(api):
    """PRD §3.9: "every use case in `APPROVED` whose `reassessment_due_at` is at or before the current logical instant moves to `UNDER_REASSESSMENT`, with `reassessment_status` set to `IN_PROGRESS` or, when the clock is more than 30 days past due, to `OVERDUE`."

    PRD §3.7: "5. **Select the reassessment interval.** `reassessment_interval_days` is 730 days (two years) for a `MINIMAL` final tier, 365 days (one year) for a `LIMITED` final tier, and 180 days (half a year) for a `HIGH` final tier."

    PRD §3.7: "6. **Stamp the approval clock.** `approved_at` is the current logical instant, `approval_expires_at` is that instant plus `reassessment_interval_days` days, `reassessment_due_at` is set to the very same instant as `approval_expires_at`, `reassessment_cycle_index` becomes 1 and `reassessment_status` becomes `SCHEDULED`."

    PRD §3.9: "An outcome of `SUSPEND` moves it `UNDER_REASSESSMENT → SUSPENDED`, sets `reassessment_status` to `SCHEDULED` and pushes `reassessment_due_at` out to the current instant plus `reassessment_interval_days` days, drops every `ModelBinding` of the use case in `PINNED` to `STALE` with `superseded_reason` `APPROVAL_SUSPENDED`, and appends a `GovernanceLedgerEntry` of type `APPROVAL_SUSPENDED` with `reach_delta` 0 and `debt_delta` 0.00."

    PRD §3.9: "An outcome of `CONFIRMED` requires the use case's `monitoring_posture` to be `HEALTHY` and moves it `UNDER_REASSESSMENT → APPROVED`. `reassessment_cycle_index` increments by 1"

    PRD §3.9: "Closing a reassessment strictly after the use case's `approval_expires_at` is rejected with `ERR_APPROVAL_EXPIRED`; at exactly that instant the call still succeeds, for the reason set out in §2.9."

    PRD §2.11: "The three statuses `APPROVED`, `UNDER_REASSESSMENT` and `SUSPENDED` constitute the *inventory statuses*: a use case in any of them is live in the governance inventory."

    Design: Corner/endpoints/complete_reassessment_suspend_branch_is_conditional_on_outcome
    """
    chain = use_case_under_reassessment(api)
    sweep = chain.extra["sweep"]
    assert sweep["reassessments_opened"] == 1
    assert sweep["approvals_suspended"] == 0

    opened = chain.use_case
    assert_use_case(
        opened,
        status="UNDER_REASSESSMENT",
        reassessment_status="IN_PROGRESS",
        reassessment_cycle_index=1,
        reassessment_interval_days=730,
        deployed_headcount_reach=500,
    )
    due_at = opened["reassessment_due_at"]
    assert_iso_instant(due_at, "2028-07-31T00:00:00Z")
    assert_iso_instant(opened["approval_expires_at"], due_at)

    response = api.complete_reassessment(
        chain.use_case_id, reassessment_payload("SUSPEND"), headers=OFFICER
    )
    suspended = validate_success(response, expected_status=200)

    assert_use_case(
        suspended,
        status="SUSPENDED",
        reassessment_status="SCHEDULED",
        reassessment_cycle_index=1,
    )
    assert_iso_instant(suspended["reassessment_due_at"], plus_days(due_at, 730))
    assert_iso_instant(suspended["reassessment_due_at"], "2030-07-31T00:00:00Z")

    bindings = list_bindings(api, chain.use_case_id)
    assert len(bindings) == 1
    assert_model_binding(
        bindings[0], status="STALE", superseded_reason="APPROVAL_SUSPENDED"
    )

    ledger = list_ledger(api, chain.use_case_id)
    assert entry_types(ledger)[-1] == "APPROVAL_SUSPENDED"
    assert_ledger_entry(
        ledger[-1], entry_type="APPROVAL_SUSPENDED", reach_delta=0, debt_delta=0.00
    )

    summary = validate_success(
        api.get_inventory_summary(headers=OFFICER), expected_status=200
    )
    assert summary["inventory_count"] == 1
    assert summary["portfolio_approved_reach"] == 500
    assert summary["ledger_reach_balance"] == 500
    assert_reach_conserved(summary)
