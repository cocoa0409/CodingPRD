"""Bubble-up cascades, dual-basis buyout savings, replacement exposure,
fiscal priority ordering, and the authentication/authorization envelope."""
import pytest

from test_helpers import (
    BL,
    OM,
    VP,
    ADMIN,
    ApiErrorId,
    api_client,
    award_sub,
    create_draft_subcontract,
    create_open_project,
    create_package,
    create_project,
    execute_sub,
    get_success_data,
    issue_sub,
    make_buyout_lead_headers,
    publish_package,
    recommend,
    register_compliant_cert,
    setup_awarded_subcontract,
    setup_executed_subcontract,
    setup_leveling_package,
    validate_error,
    validate_paginated,
    validate_success,
)


def _executed_lone_sub(name, number, trade_code, budget=10_000_000,
                       bid_amount=8_000_000, **kwargs):
    """One package holding exactly one EXECUTED subcontract: the package
    bubbles to AWARDED and the project to BUYOUT_COMPLETE."""
    proj, proj_v = create_open_project(name, number)
    ctx = setup_executed_subcontract(
        proj["id"], proj_v, name=name, trade_code=trade_code, budget=budget,
        bid_amount=bid_amount,
        contract_value_cents=kwargs.pop("contract_value_cents", bid_amount),
        **kwargs)
    return proj, ctx


class TestDefaultCascade:

    def test_default_bubbles_package_and_project_back_open(self):
        """PRD section 2.8: "a default or replacement that strips a package
        of its last `EXECUTED` subcontract drops the package back to
        `BUYOUT_IN_PROGRESS`, and a project that was `BUYOUT_COMPLETE`
        reopens (`BUYOUT_COMPLETE → BUYOUT_OPEN`) the moment any package
        leaves `AWARDED`."

        Design: Difficulty/transitive_cascade/default_cascade_subcontract_to_package_to_project_buyout_complete
        """
        proj, ctx = _executed_lone_sub("P-TC1", "TC1", "TC1-26")
        sub_id = ctx["subcontract"]["id"]
        tp_id = ctx["package"]["id"]
        pre_proj = get_success_data(api_client.get_project(proj["id"], BL))
        pre_tp = get_success_data(api_client.get_trade_package(tp_id, BL))
        assert pre_proj["status"] == "BUYOUT_COMPLETE", \
            "setup must reach the bubble-up end state"
        assert pre_tp["status"] == "AWARDED"
        assert pre_tp["awarded_value_cents"] == 8_000_000

        validate_success(api_client.declare_default(
            sub_id,
            {"reason": "abandoned submittals",
             "estimated_replacement_cost_cents": 9_000_000},
            OM,
        ))
        post_tp = get_success_data(api_client.get_trade_package(tp_id, BL))
        post_proj = get_success_data(api_client.get_project(proj["id"], BL))
        assert post_tp["status"] == "BUYOUT_IN_PROGRESS", \
            "hop 2: package leaves AWARDED"
        assert post_tp["awarded_value_cents"] == 0, \
            "DEFAULTED no longer counts as awarded anchor"
        assert post_proj["status"] == "BUYOUT_OPEN", \
            "hop 3: project recompute over package states"

    def test_default_marks_subcontract_and_stamps_logical_clock(self):
        """PRD section 3.9: "On declaration the subcontract moves `EXECUTED
        → DEFAULTED`, its `default_flag` becomes true, `default_recorded_at`
        is stamped from the project logical clock, and the estimated
        replacement cost is stored for exposure reporting."

        Design: Difficulty/transitive_cascade/default_cascade_subcontract_to_package_to_project_buyout_complete
        """
        proj, ctx = _executed_lone_sub("P-TC1B", "TC1B", "TC1B-26")
        sub_id = ctx["subcontract"]["id"]
        validate_success(api_client.declare_default(
            sub_id,
            {"reason": "abandoned submittals",
             "estimated_replacement_cost_cents": 9_000_000},
            OM,
        ))
        post_sub = get_success_data(api_client.get_subcontract(sub_id, BL))
        assert post_sub["status"] == "DEFAULTED"
        assert post_sub["default_flag"] is True
        proj_after = get_success_data(api_client.get_project(proj["id"], BL))
        assert post_sub["default_recorded_at"] == proj_after["current_time_utc"], \
            "default_recorded_at is stamped from the project logical clock"


class TestReplacementCascade:

    def _executed_plus_pending(self):
        """Package BUYOUT_IN_PROGRESS: sub_i EXECUTED, sub_j DRAFT sibling
        blocking the AWARDED bubble-up."""
        proj, proj_v = create_open_project("P-TC2", "TC2")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="TC2", trade_code="TC2-09",
            budget=20_000_000,
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_500_000, "2026-05-15T13:00:00Z"),
                  (9_800_000, "2026-05-15T14:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        sub_i = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"],
                                         "Iota Elec")
        sub_j = create_draft_subcontract(pkg["id"], ctx["bids"][1]["id"],
                                         "Kappa Elec")
        recommend(sub_i["id"], 9_000_000)
        award_sub(sub_i["id"])
        cert = register_compliant_cert(sub_i["id"],
                                       certificate_number="CERT-TC2")
        issue_sub(sub_i["id"])
        execute_sub(sub_i["id"])
        pre_tp = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert pre_tp["status"] == "BUYOUT_IN_PROGRESS", \
            "DRAFT sibling blocks the AWARDED bubble-up"
        assert pre_tp["awarded_value_cents"] == 9_000_000
        return proj, pkg, sub_i, sub_j, cert

    def test_replace_spawns_draft_and_resets_negotiation_and_insurance(self):
        """PRD section 3.9: "a fresh replacement subcontract is spawned on
        the same package in `DRAFT` with its `replaces_subcontract_id`
        pointing back, `negotiation_round` reset to 0, `insurance_status` at
        `MISSING`, and `contract_value_cents` at 0; the replaced
        subcontract's `replacement_subcontract_id` is set to the new spawn
        and exposed on the response".

        Design: Difficulty/transitive_cascade/replacement_cascade_spawns_draft_and_rearms_bond_and_insurance
        """
        _proj, pkg, sub_i, _sub_j, _cert = self._executed_plus_pending()
        resp = api_client.replace_subcontract(
            sub_i["id"],
            {"reason": "failed precon",
             "estimated_replacement_cost_cents": 10_000_000},
            OM,
        )
        data = validate_success(resp)
        repl_id = data["replacement_subcontract_id"]
        assert repl_id, "response exposes replacement_subcontract_id"
        repl = get_success_data(api_client.get_subcontract(repl_id, BL))
        assert repl["status"] == "DRAFT"
        assert repl["replaces_subcontract_id"] == sub_i["id"], \
            "spawn carries the cross-aggregate link"
        assert repl["trade_package_id"] == pkg["id"], \
            "spawn inherits the package"
        assert repl["insurance_status"] == "MISSING"
        assert repl["negotiation_round"] == 0
        assert repl["contract_value_cents"] == 0, \
            "insurance and negotiation state reset by the cascade"

    def test_replace_supersedes_certificates_and_recomputes_package(self):
        """PRD section 3.9: "every insurance certificate on the replaced
        subcontract moves into the `SUPERSEDED` state (`ISSUED →
        SUPERSEDED`). The package recomputes exactly as in the default path,
        since a `REPLACED` subcontract no longer anchors awarded value."

        Design: Difficulty/transitive_cascade/replacement_cascade_spawns_draft_and_rearms_bond_and_insurance
        """
        _proj, pkg, sub_i, _sub_j, cert = self._executed_plus_pending()
        validate_success(api_client.replace_subcontract(
            sub_i["id"],
            {"reason": "failed precon",
             "estimated_replacement_cost_cents": 10_000_000},
            OM,
        ))
        post_sub = get_success_data(api_client.get_subcontract(sub_i["id"], BL))
        assert post_sub["status"] == "REPLACED"
        certs, _meta = validate_paginated(
            api_client.list_insurance_certificates(sub_i["id"], BL))
        by_id = {c["id"]: c["status"] for c in certs}
        assert by_id[cert["id"]] == "SUPERSEDED", \
            "old certificates retired by the cascade"
        post_tp = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert post_tp["status"] == "BUYOUT_IN_PROGRESS"
        assert post_tp["awarded_value_cents"] == 0, \
            "REPLACED no longer counts as awarded anchor"


class TestReplacementLinkValidation:

    def test_replacement_link_to_non_draft_rejected(self):
        """PRD section 3.9: "when present, the referenced subcontract must
        exist, must be in `DRAFT`, and must live on the same package —
        otherwise the call is rejected with `ERR_REPLACEMENT_LINK_INVALID`".

        Design: Corner/validations/replacement_link_to_non_draft_rejected
        """
        proj, proj_v = create_open_project("P-V15", "V15")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V15", trade_code="V15-26",
            budget=20_000_000,
            bids=((8_000_000, "2026-05-15T12:00:00Z"),
                  (8_500_000, "2026-05-15T13:00:00Z"),
                  (8_700_000, "2026-05-15T14:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        sub_a = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"], "AT")
        sub_b = create_draft_subcontract(pkg["id"], ctx["bids"][1]["id"], "AU")
        recommend(sub_a["id"], 8_000_000)
        recommend(sub_b["id"], 8_500_000)
        award_sub(sub_a["id"])
        register_compliant_cert(sub_a["id"], certificate_number="CERT-V15")
        issue_sub(sub_a["id"])
        execute_sub(sub_a["id"])
        resp = api_client.declare_default(
            sub_a["id"],
            {"reason": "walked off",
             "estimated_replacement_cost_cents": 9_000_000,
             "replacement_subcontract_id": sub_b["id"]},
            OM,
        )
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_LINK_INVALID)
        after = get_success_data(api_client.get_subcontract(sub_a["id"], BL))
        assert after["status"] == "EXECUTED", "no drift"


class TestReplacementExposure:

    def test_replacement_cost_exposure_with_subguard_claim(self):
        """PRD section 3.9: "For every subcontract on the package whose
        `default_flag` is true, the analysis computes an exposure: the
        subcontract's estimated replacement cost minus its contract value at
        default, floored at zero, plus — only when the subcontract's
        `bonding_requirement` is `SUBGUARD` — a subguard claim estimate equal
        to the original `contract_value_cents` multiplied by 0.20, rounded
        half-up to integer cents."

        Design: Corner/calculations/replacement_cost_exposure_with_subguard_claim
        """
        proj, proj_v = create_open_project("P-C8", "C8")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="C8", trade_code="C8-03",
            budget=12_000_000, bonding_policy="PER_TRADE_RISK",
            bids=((12_000_000, "2026-05-15T12:00:00Z"),
                  (12_100_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        sub = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"], "W1")
        recommend(sub["id"], 12_000_000)
        award_sub(sub["id"])
        bond = validate_success(api_client.create_bond_decision(
            sub["id"], {"trade_history": "CLAIMS"}, OM), expected_status=201)
        # 35 (value > 10M) + 25 (ratio 1.0 > 0.25) + 25 (CLAIMS) = 85
        assert bond["decision"] == "SUBGUARD"
        register_compliant_cert(sub["id"], certificate_number="CERT-C8")
        issue_sub(sub["id"])
        execute_sub(sub["id"])
        validate_success(api_client.declare_default(
            sub["id"],
            {"reason": "abandoned",
             "estimated_replacement_cost_cents": 14_000_000},
            OM,
        ))
        report = get_success_data(
            api_client.get_replacement_analysis(pkg["id"], BL))
        items = report["items"]
        assert len(items) == 1
        # max(0, 14_000_000 - 12_000_000) + round_half_up(12_000_000 * 0.20)
        assert items[0]["exposure_cents"] == 4_400_000


class TestDualBasisSavings:

    def _executed_plus_pending(self):
        proj, proj_v = create_open_project("P-DV1", "DV1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="DV1", trade_code="DV1-26",
            budget=10_000_000,
            bids=((8_000_000, "2026-05-15T12:00:00Z"),
                  (9_500_000, "2026-05-15T13:00:00Z"),
                  (10_000_000, "2026-05-15T14:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        tiers = [
            {"max_value_cents": 500_000, "max_cumulative_pct": 0.05,
             "roles": ["ProjectExecutive"]},
            {"max_value_cents": 2_500_000, "max_cumulative_pct": 0.10,
             "roles": ["ProjectExecutive", "ProjectManager"]},
            {"max_value_cents": -1, "max_cumulative_pct": -1,
             "roles": ["ProjectExecutive", "ProjectManager",
                       "OperationsManager"]},
        ]
        sub_a = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"],
                                         "Alpha Mech",
                                         change_authority_limits=tiers)
        recommend(sub_a["id"], 8_000_000)
        sub_b = create_draft_subcontract(pkg["id"], ctx["bids"][1]["id"],
                                         "Beta Mech",
                                         change_authority_limits=tiers)
        recommend(sub_b["id"], 1_000_000)
        award_sub(sub_a["id"])
        register_compliant_cert(sub_a["id"], certificate_number="CERT-DV1")
        issue_sub(sub_a["id"])
        execute_sub(sub_a["id"])
        return pkg

    def test_provisional_basis_counts_only_executed(self):
        """PRD section 2.11: "Under the `PROVISIONAL` basis — the working
        view during buyout — only subcontracts in `EXECUTED` status anchor
        value."

        Design: Difficulty/dual_variant_calc/buyout_savings_provisional_excludes_pending_vs_final_includes
        """
        pkg = self._executed_plus_pending()
        data = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert data["awarded_value_cents"] == 8_000_000, \
            "PENDING_AWARD subcontract excluded from PROVISIONAL"
        # savings = 10_000_000 - 8_000_000 - 0
        assert data["buyout_savings_cents"] == 2_000_000
        # target = round_half_up(0.05 * 10_000_000) = 500_000
        assert data["buyout_posture"] == "FAVORABLE"

    def test_final_basis_adds_pending_award(self):
        """PRD section 2.11: "Under the `FINAL` basis — used for buyout
        close-out reporting — both `EXECUTED` and `PENDING_AWARD`
        subcontracts anchor value."

        Design: Difficulty/dual_variant_calc/buyout_savings_provisional_excludes_pending_vs_final_includes
        """
        pkg = self._executed_plus_pending()
        data = get_success_data(api_client.get_trade_package(
            pkg["id"], BL, params={"basis": "FINAL"}))
        assert data["awarded_value_cents"] == 9_000_000, \
            "PENDING_AWARD subcontract included in FINAL"
        assert data["buyout_savings_cents"] == 1_000_000
        assert data["buyout_posture"] == "FAVORABLE"
        prov = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert prov["awarded_value_cents"] != data["awarded_value_cents"], \
            "identical ledger data, two variants, different results"

    def test_buyout_posture_target_boundary_favorable_vs_neutral(self):
        """PRD section 3.9: "The posture threshold converts the project's
        `buyout_target_savings_pct` into cents by multiplying it by the
        package's `estimated_budget_cents` and rounding half-up; the
        package's `buyout_posture` is then `FAVORABLE` when the savings meet
        or exceed that target, `NEUTRAL` when the savings are zero or better
        but below target, and `UNFAVORABLE` when the savings are negative."

        Design: Corner/calculations/buyout_posture_target_boundary_favorable_vs_neutral
        """
        proj, proj_v = create_open_project("P-C4", "C4")
        # Package A: PENDING_AWARD subcontract at 9_500_000 (savings 500_000)
        ctx_a = setup_leveling_package(
            proj["id"], proj_v, name="C4A", trade_code="C4-A",
            budget=10_000_000,
            bids=((9_500_000, "2026-05-15T12:00:00Z"),
                  (9_600_000, "2026-05-15T13:00:00Z")),
        )
        sub_a = create_draft_subcontract(
            ctx_a["package"]["id"], ctx_a["bids"][0]["id"], "R1")
        recommend(sub_a["id"], 9_500_000)
        # Re-read the project to obtain the OCC version for package B
        proj_mid = get_success_data(api_client.get_project(proj["id"], BL))
        ctx_b = setup_leveling_package(
            proj["id"], proj_mid["version"], name="C4B", trade_code="C4-B",
            budget=10_000_000,
            bids=((9_500_001, "2026-05-15T12:00:00Z"),
                  (9_600_001, "2026-05-15T13:00:00Z")),
        )
        sub_b = create_draft_subcontract(
            ctx_b["package"]["id"], ctx_b["bids"][0]["id"], "S1")
        recommend(sub_b["id"], 9_500_001)

        a = get_success_data(api_client.get_trade_package(
            ctx_a["package"]["id"], BL, params={"basis": "FINAL"}))
        assert a["awarded_value_cents"] == 9_500_000
        assert a["buyout_savings_cents"] == 500_000
        assert a["buyout_posture"] == "FAVORABLE", \
            "savings >= target 500000, inclusive boundary"

        b = get_success_data(api_client.get_trade_package(
            ctx_b["package"]["id"], BL, params={"basis": "FINAL"}))
        assert b["awarded_value_cents"] == 9_500_001
        assert b["buyout_savings_cents"] == 499_999
        assert b["buyout_posture"] == "NEUTRAL", "one cent below target"

    def test_buyout_summary_final_basis_totals(self):
        """PRD section 3.9: "The project-level buyout summary rolls these
        per-package figures up into `total_estimated_cents`,
        `total_awarded_cents`, and `total_savings_cents` alongside the
        per-package array, honoring the same `basis` selector."

        Design: Corner/endpoints/buyout_summary_final_basis_totals
        """
        proj, proj_v = create_open_project("P-P1", "P1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="P1", trade_code="P1-26",
            budget=10_000_000,
            bids=((9_500_000, "2026-05-15T12:00:00Z"),
                  (9_600_000, "2026-05-15T13:00:00Z")),
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "BC")
        recommend(sub["id"], 9_500_000)
        data = get_success_data(api_client.get_buyout_summary(
            proj["id"], OM, params={"basis": "FINAL"}))
        assert data["total_estimated_cents"] == 10_000_000
        assert data["total_awarded_cents"] == 9_500_000
        assert data["total_savings_cents"] == 500_000


class TestFiscalChecksAndPriority:

    def test_recommend_over_contingency_cap_rejected(self):
        """PRD section 3.5: "the package's projected total — its current
        `awarded_value_cents`, plus this subcontract's proposed
        `contract_value_cents`, plus the pinned values of every other
        subcontract sitting in `PENDING_AWARD` on the package — must not
        exceed the package's `estimated_budget_cents` plus its remaining
        contingency (the `budgeted_contingency_cents` less whatever has
        already been consumed by contingency draws); a breach is rejected
        with `ERR_CONTINGENCY_EXCEEDED`."

        Design: Corner/validations/recommend_over_contingency_cap_rejected
        """
        proj, proj_v = create_open_project("P-V11", "V11")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V11", trade_code="V11-26",
            budget=9_900_000, contingency=200_000,
            bids=((10_200_000, "2026-05-15T12:00:00Z"),
                  (10_300_000, "2026-05-15T13:00:00Z")),
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "AL")
        resp = api_client.recommend_award(
            sub["id"], {"contract_value_cents": 10_200_000}, BL)
        validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXCEEDED)
        after = get_success_data(api_client.get_subcontract(sub["id"], BL))
        assert after["status"] == "DRAFT", "no drift"

    def _contingency_drawn_package(self, name, number, trade_code):
        """Package budget 9_900_000, contingency 200_000 fully consumed by a
        CONTINGENCY_DRAW resolution; one PENDING_AWARD subcontract at
        10_000_000 (recommended while the pool was intact)."""
        proj, proj_v = create_open_project(name, number)
        ctx = setup_leveling_package(
            proj["id"], proj_v, name=name, trade_code=trade_code,
            budget=9_900_000, contingency=200_000,
            bids=((10_000_000, "2026-05-15T12:00:00Z"),
                  (9_900_000, "2026-05-15T13:00:00Z"),
                  (9_800_000, "2026-05-15T14:00:00Z")),
        )
        pkg = ctx["package"]
        sub_m = create_draft_subcontract(pkg["id"], ctx["bids"][0]["id"],
                                         "Mu Mech")
        recommend(sub_m["id"], 10_000_000)
        gap = validate_success(api_client.create_gap(
            pkg["id"],
            {"category": "SCOPE", "description": "fixture allowance overrun",
             "estimated_impact_cents": 200_000},
            BL,
        ), expected_status=201)
        validate_success(api_client.resolve_gap(
            gap["id"],
            {"resolution_kind": "CONTINGENCY_DRAW",
             "priced_amount_cents": 200_000},
            BL,
        ))
        return proj, pkg, ctx, sub_m

    def test_award_headline_breach_rejected(self):
        """PRD section 3.6: "first the headline check, where this
        subcontract's `contract_value_cents` alone exceeding the package's
        `estimated_budget_cents` plus remaining contingency is rejected with
        `ERR_AWARD_EXCEEDS_BUDGET`; then the projected-total check identical
        in shape to §3.5, whose breach yields `ERR_CONTINGENCY_EXCEEDED`."

        Design: Corner/validations/award_headline_breach_rejected
        """
        _proj, _pkg, _ctx, sub_m = self._contingency_drawn_package(
            "P-V10", "V10", "V10-26")
        resp = api_client.award_subcontract(sub_m["id"], OM)
        validate_error(resp, ApiErrorId.ERR_AWARD_EXCEEDS_BUDGET)
        after = get_success_data(api_client.get_subcontract(sub_m["id"], BL))
        assert after["status"] == "PENDING_AWARD", "no drift"

    def test_safety_beats_fiscal_at_award(self):
        """PRD section 2.10: "The life-safety gap block outranks the fiscal
        checks."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_life_safety_gap_over_contingency_exceeded
        """
        proj, pkg, _ctx, sub_m = self._contingency_drawn_package(
            "P-PP2", "PP2", "PP2-21")
        gap_ls = validate_success(api_client.create_gap(
            pkg["id"],
            {"category": "LIFE_SAFETY",
             "description": "sprinkler drawings exclude stairwell coverage",
             "estimated_impact_cents": 0},
            BL,
        ), expected_status=201)
        # Headline fiscal breach also holds: 10_000_000 > 9_900_000 + 0.
        resp = api_client.award_subcontract(sub_m["id"], OM)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LIFE_SAFETY_GAP)
        after = get_success_data(api_client.get_subcontract(sub_m["id"], BL))
        assert after["status"] == "PENDING_AWARD", "blocked; no state drift"
        gap_after = get_success_data(api_client.get_gap(gap_ls["id"], BL))
        assert gap_after["status"] == "OPEN", "the blocking gap remains open"

    def test_resolving_safety_gap_unmasks_fiscal_breach(self):
        """PRD section 2.10: "The life-safety gap block outranks the fiscal
        checks."
        PRD section 3.6: "first the headline check, where this subcontract's
        `contract_value_cents` alone exceeding the package's
        `estimated_budget_cents` plus remaining contingency is rejected with
        `ERR_AWARD_EXCEEDS_BUDGET`".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_life_safety_gap_over_contingency_exceeded
        """
        proj, pkg, _ctx, sub_m = self._contingency_drawn_package(
            "P-PP2B", "PP2B", "PP2B-21")
        gap_ls = validate_success(api_client.create_gap(
            pkg["id"],
            {"category": "LIFE_SAFETY",
             "description": "sprinkler drawings exclude stairwell coverage",
             "estimated_impact_cents": 0},
            BL,
        ), expected_status=201)
        resp = api_client.award_subcontract(sub_m["id"], OM)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LIFE_SAFETY_GAP)
        # Remove the safety violation; the fiscal breach it masked surfaces.
        validate_success(api_client.resolve_gap(
            gap_ls["id"],
            {"resolution_kind": "BID_CLARIFICATION",
             "priced_amount_cents": 0},
            BL,
        ))
        resp2 = api_client.award_subcontract(sub_m["id"], OM)
        validate_error(resp2, ApiErrorId.ERR_AWARD_EXCEEDS_BUDGET)

    def test_state_beats_fiscal_at_award(self):
        """PRD section 2.10: "State-validity checks (from-state gates,
        derived-field gates such as the project being `BUYOUT_OPEN`, the
        negotiation round cap, terminal-subcontract protection, the
        approved-SOV precondition on change-order creation, the insurance
        and bonding gates at issue and execute, and the withdrawn-bid block
        on SOV submission) come after that."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_over_contingency_exceeded
        """
        proj, pkg, ctx, sub_m = self._contingency_drawn_package(
            "P-PP1", "PP1", "PP1-05")
        # Second subcontract left in DRAFT; the package's headroom is already
        # blown by the PENDING_AWARD sibling (10_000_000 > 9_900_000 + 0).
        sub_x = create_draft_subcontract(pkg["id"], ctx["bids"][1]["id"],
                                         "Xi Mech")
        resp = api_client.award_subcontract(sub_x["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after_x = get_success_data(api_client.get_subcontract(sub_x["id"], BL))
        assert after_x["status"] == "DRAFT", \
            "no state drift from the rejected award"
        after_m = get_success_data(api_client.get_subcontract(sub_m["id"], BL))
        assert after_m["status"] == "PENDING_AWARD", "sibling untouched"

    def test_contingency_draw_visible_on_package_before_masked_award(self):
        """PRD section 3.3: "`CONTINGENCY_DRAW` requires
        `priced_amount_cents` to be present, and resolving it consumes that
        amount from the package's contingency pool: the package's consumed
        contingency increases by `priced_amount_cents`, which in turn
        reduces the headroom available to later award recommendations
        (§3.5)."
        PRD section 3.9: "The `buyout_savings_cents` is the package's
        `estimated_budget_cents` minus its `awarded_value_cents` minus the
        consumed contingency."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_over_contingency_exceeded
        """
        proj, pkg, ctx, sub_m = self._contingency_drawn_package(
            "P-PP1B", "PP1B", "PP1B-05")
        # The draw is already reflected: savings = 9_900_000 - 0 - 200_000.
        tp = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert tp["buyout_savings_cents"] == 9_700_000, \
            "consumed contingency reduces the computed savings"
        sub_x = create_draft_subcontract(pkg["id"], ctx["bids"][1]["id"],
                                         "Xi Mech")
        # Both violations hold for the DRAFT award (from-state + projected
        # 0 + 0 + 10_000_000 > 9_900_000 + 0); the state check wins.
        resp = api_client.award_subcontract(sub_x["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestSecurityEnvelope:

    def test_request_missing_auth_headers_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or presenting
        a role string outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        proj = create_project("P-V1", "V1")
        resp = api_client.get_project(proj["id"], headers={})
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )

    def test_estimator_cannot_award_bid_forbidden(self, estimator_headers):
        """PRD section 2.1: "A request whose role is well-formed but not
        permitted on the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD section 3.4: "Bid award is the leveling table's verdict. A
        `BuyoutLead` names the winning bid".

        Design: Corner/validations/estimator_cannot_award_bid_forbidden
        """
        proj, proj_v = create_open_project("P-V2", "V2")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V2", trade_code="V2-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),),
            withdraw_last=False,
        )
        # Place the bid as the Estimator (a shared capability) so the role is
        # exercised on both sides of the matrix.
        pkg = ctx["package"]
        bid = ctx["bids"][0]
        resp = api_client.award_bid(pkg["id"], bid["id"], estimator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                       expected_status=403)
        after = get_success_data(api_client.get_bid(bid["id"], BL))
        assert after["status"] == "PLACED", "no drift"

    def test_buyout_lead_cannot_record_bond_decision_forbidden(self):
        """PRD section 3.7: "The bonding decision is the
        `OperationsManager`'s call".
        PRD section 2.1: "A request whose role is well-formed but not
        permitted on the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/validations/buyout_lead_cannot_record_bond_decision_forbidden
        """
        proj, proj_v = create_open_project("P-V3", "V3")
        ctx = setup_awarded_subcontract(
            proj["id"], proj_v, name="V3", trade_code="V3-26",
            bonding_policy="PER_TRADE_RISK", bid_amount=1_000_000,
            contract_value_cents=1_000_000)
        resp = api_client.create_bond_decision(
            ctx["subcontract"]["id"], {"trade_history": "CLEAN"}, BL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                       expected_status=403)

    def test_gcadmin_cannot_publish_package_forbidden(self, gc_admin_headers):
        """PRD section 3.2: "Publishing a package — a `BuyoutLead` action
        moving it `DRAFT → PUBLISHED`".
        PRD section 2.1: "A request whose role is well-formed but not
        permitted on the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/gcadmin_cannot_publish_package_forbidden
        """
        proj, proj_v = create_open_project("P-R2", "R2")
        pkg = create_package(proj["id"], proj_v, name="Mechanical",
                             trade_code="R2-26", as_headers=gc_admin_headers)
        resp = api_client.publish_trade_package(pkg["id"], gc_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                       expected_status=403)


class TestProjectRequiredFields:

    def test_project_create_missing_required_returns_validation(self):
        """PRD section 3.1: "A `GCAdmin` creates a `Project` by supplying
        its `name`, a unique `project_number`, the `estimated_budget_cents`
        for the whole job, and the `buyout_target_savings_pct`".

        Design: Corner/entities/project_create_missing_required_returns_validation
        """
        resp = api_client.create_project(
            {"name": "P-E7", "estimated_budget_cents": 50_000_000,
             "buyout_target_savings_pct": 0.05},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)
