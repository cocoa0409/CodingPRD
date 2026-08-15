"""Substitution requests: negotiation rules, approval cascade, lead-time variants."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_bom_line,
    get_success_data,
    make_designer_headers,
    make_qa_headers,
    new_component,
    new_substitution_request,
    setup_panel_with_bom,
    validate_error,
    validate_paginated,
    validate_success,
    walk_panel_to_design_approved,
)


class TestSubstitutionDownrated:
    def test_substitution_downrated_sccr_rejected(self, api):
        """PRD §3.3: "Approval is gated on three further checks: the proposed
        component must be active (else `ERR_COMPONENT_INACTIVE`); when both the
        proposed and original components carry a non-null `sccr_ka`, the proposed
        component's `sccr_ka` must be at least the original's (else
        `ERR_SUBSTITUTION_DOWNRATED`, HTTP 422); and the owning job's customer must
        not be on `credit_hold` (else `ERR_CREDIT_HOLD`)."

        Design: Corner/validations/substitution_downrated_sccr_rejected
        """
        ctx = setup_panel_with_bom(
            company_name="DR Co", job_number="J-DR1", quoted_price_cents=100000,
            panel_tag="P-DR1", design_engineer_id="de-dr",
            component_spec={
                "part_number": "PS-DR10", "component_class": "POWER_SUPPLY",
                "unit_cost_cents": 30000, "lead_time_days": 10, "sccr_ka": 10,
                "heat_dissipation_w": 40,
            },
        )
        panel_id = ctx["panel"]["id"]
        line_id = ctx["lines"][0]["id"]
        ps_low = new_component(
            part_number="PS-DR5", component_class="POWER_SUPPLY", unit_cost_cents=25000,
            lead_time_days=3, sccr_ka=5, heat_dissipation_w=40,
        )
        ps_hi = new_component(
            part_number="PS-DR22", component_class="POWER_SUPPLY", unit_cost_cents=32000,
            lead_time_days=12, sccr_ka=22, heat_dissipation_w=40,
        )
        sub_lo = new_substitution_request(panel_id, line_id, ps_low["id"],
                                          requested_by="de-dr", reason="cheaper")
        sub_hi = new_substitution_request(panel_id, line_id, ps_hi["id"],
                                          requested_by="de-dr", reason="higher sccr")

        qa = make_qa_headers("qa-dr")
        resp = api.approve_substitution(sub_lo["id"], qa)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_DOWNRATED, 422)
        still = validate_success(api.get_substitution_request(sub_lo["id"], qa), 200)
        assert still["status"] == "REQUESTED", "rejected approval must not move the request"

        approved = validate_success(api.approve_substitution(sub_hi["id"], qa), 200)
        assert approved["status"] == "APPROVED"


class TestSubstitutionWithdraw:
    def test_substitution_withdraw_by_non_requester_rejected(self, api, pm_headers):
        """PRD §2.8: "A separate same-user rule in the other direction governs
        withdrawal: only the `DesignEngineer` whose id matches a
        `SubstitutionRequest`'s `requested_by_id` may withdraw that request".
        PRD §2.1: "A request whose role is authenticated but not listed in the target
        endpoint's Authorized Role(s) column is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/state_machines/substitution_withdraw_by_non_requester_rejected
        """
        ctx = setup_panel_with_bom(
            company_name="Wdr Co", job_number="J-WD1", quoted_price_cents=100000,
            panel_tag="P-WD1", design_engineer_id="de-w1",
            component_spec={
                "part_number": "PS-W1", "component_class": "POWER_SUPPLY",
                "unit_cost_cents": 30000, "lead_time_days": 10, "sccr_ka": 10,
                "heat_dissipation_w": 40,
            },
        )
        panel_id = ctx["panel"]["id"]
        line_id = ctx["lines"][0]["id"]
        ps_w2 = new_component(
            part_number="PS-W2", component_class="POWER_SUPPLY", unit_cost_cents=31000,
            lead_time_days=20, sccr_ka=10, heat_dissipation_w=40,
        )
        sub = new_substitution_request(panel_id, line_id, ps_w2["id"],
                                       requested_by="de-w1", reason="lead time")

        resp = api.withdraw_substitution(sub["id"], make_designer_headers("de-w2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        still = validate_success(api.get_substitution_request(sub["id"], pm_headers), 200)
        assert still["status"] == "REQUESTED"


class TestLeadTimeDeltaVariants:
    """Same swap (10-day -> 30-day, raw delta +20) priced under both variants."""

    def _components(self, api):
        orig = new_component(
            part_number="PS-10D", component_class="POWER_SUPPLY", unit_cost_cents=30000,
            lead_time_days=10, sccr_ka=10, heat_dissipation_w=40,
        )
        prop = new_component(
            part_number="PS-30D", component_class="POWER_SUPPLY", unit_cost_cents=28000,
            lead_time_days=30, sccr_ka=22, heat_dissipation_w=40,
        )
        return orig, prop

    def test_substitution_lead_time_delta_pessimistic_early_phase(self, api, pm_headers):
        """PRD §3.3: "The lead-time delta itself is signed:
        `Component(proposed).lead_time_days` minus `Component(original).lead_time_days`."
        PRD §3.3: "When the parent job is in `DESIGN` or `PROCUREMENT` — early-phase
        jobs where the shop absorbs raw vendor deltas plus a risk pad — the reported
        delta is the raw delta plus `7` days when the raw delta is positive, or the
        raw delta unchanged when it is zero or negative; the pad never applies to a
        decrease."

        Design: Difficulty/dual_variant_calc/substitution_delta_pessimistic_vs_optimistic_by_job_phase
        """
        orig, prop = self._components(api)
        ctx = setup_panel_with_bom(
            company_name="Beta Plastics", job_number="J-2001", quoted_price_cents=500000,
            warranty_months=12, panel_tag="P-E1", design_engineer_id="de-002",
            component_spec={
                "part_number": "PS-EARLY", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        # Put the 10-day component on its own BOM line and release to procurement:
        # the job rests in PROCUREMENT (an early phase) at approval time.
        orig_line = add_bom_line(panel_id, orig["id"])
        walk_panel_to_design_approved(panel_id, qa_user_id="qa-901")
        get_success_data(api.release_procurement(panel_id, pm_headers), 200)
        job = validate_success(api.get_job(ctx["job"]["id"], pm_headers), 200)
        assert job["status"] == "PROCUREMENT", (
            f"early-phase precondition: job must be PROCUREMENT, got {job['status']}"
        )

        sub = new_substitution_request(panel_id, orig_line["id"], prop["id"],
                                       requested_by="de-002", reason="vendor stockout")
        approved = validate_success(
            api.approve_substitution(sub["id"], make_qa_headers("qa-901")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["lead_time_delta_days"] == 27, (
            f"pessimistic variant: raw +20 plus 7-day risk pad = 27, got "
            f"{approved['lead_time_delta_days']}"
        )

    def test_substitution_lead_time_delta_optimistic_late_phase(self, api, sl_headers,
                                                                pm_headers):
        """PRD §3.3: "When the parent job is in `BUILD`, `TEST`, `READY_TO_SHIP`,
        `SHIPPED`, or `COMMISSIONED` — late-phase jobs where expediting is assumed to
        erase increases — the reported delta is the minimum of the raw delta and
        zero; increases are reported as zero because the shop expedites, while
        decreases are kept as-is."

        Design: Difficulty/dual_variant_calc/substitution_delta_pessimistic_vs_optimistic_by_job_phase
        """
        orig, prop = self._components(api)
        ctx = setup_panel_with_bom(
            company_name="Beta Plastics", job_number="J-2002", quoted_price_cents=500000,
            warranty_months=12, panel_tag="P-L1", design_engineer_id="de-002",
            component_spec={
                "part_number": "PS-LATE", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        orig_line = add_bom_line(panel_id, orig["id"])
        walk_panel_to_design_approved(panel_id, qa_user_id="qa-901")
        get_success_data(api.release_procurement(panel_id, pm_headers), 200)
        # Receive every line: the job auto-advances PROCUREMENT -> BUILD.
        lines, _ = validate_paginated(api.list_panel_components(panel_id, sl_headers))
        for line in lines:
            if line["line_status"] == "ORDERED":
                get_success_data(api.receive_panel_component(line["id"], sl_headers), 200)
        job = validate_success(api.get_job(ctx["job"]["id"], sl_headers), 200)
        assert job["status"] == "BUILD", (
            f"late-phase precondition: job must be BUILD, got {job['status']}"
        )

        sub = new_substitution_request(panel_id, orig_line["id"], prop["id"],
                                       requested_by="de-002", reason="vendor stockout")
        approved = validate_success(
            api.approve_substitution(sub["id"], make_qa_headers("qa-901")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["lead_time_delta_days"] == 0, (
            f"optimistic variant: min(+20, 0) = 0, got {approved['lead_time_delta_days']}"
        )


class TestSubstitutionApprovalCascade:
    def _setup_cascade(self, api, pm_headers, sl_headers):
        ctx = setup_panel_with_bom(
            company_name="Iota Paper", job_number="J-8001", quoted_price_cents=400000,
            panel_tag="P-SC1", design_engineer_id="de-007",
            component_spec={
                "part_number": "BPD-SC10", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        con5 = new_component(
            part_number="CON-SC5", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=5, heat_dissipation_w=20,
        )
        con22 = new_component(
            part_number="CON-SC22", component_class="CONTACTOR", unit_cost_cents=9000,
            lead_time_days=9, sccr_ka=22, heat_dissipation_w=20,
        )
        con_line = add_bom_line(panel_id, con5["id"])
        walk_panel_to_design_approved(panel_id, qa_user_id="qa-906")
        get_success_data(api.release_procurement(panel_id, pm_headers), 200)
        # Receive the BPD line so the CON swap is the last unreceived line.
        get_success_data(
            api.receive_panel_component(ctx["lines"][0]["id"], sl_headers), 200
        )
        sub = new_substitution_request(panel_id, con_line["id"], con22["id"],
                                       requested_by="de-007", reason="stockout")
        ctx.update({"con_line": con_line, "con22": con22, "sub": sub})
        return ctx

    def test_substitution_approval_swaps_bom_line_and_recomputes_sccr(self, api, pm_headers,
                                                                      sl_headers):
        """PRD §3.3: "A new `PanelComponent` line is created on the same panel,
        referencing the `proposed_component_id`, with `quantity` copied from the
        original line, `line_status` set to `SUBSTITUTED`, `substituted_for_id`
        pointing back to the original line, and `unit_cost_snapshot_cents` captured
        from the proposed component's current `unit_cost_cents`. The original line is
        retired from the active BOM: if its `line_status` was `PENDING` or `ORDERED`,
        it is set to `SUBSTITUTED` as a superseded marker".

        Design: Difficulty/transitive_cascade/substitution_approval_cascade_bom_sccr_posture_depth3
        """
        ctx = self._setup_cascade(api, pm_headers, sl_headers)
        approved = validate_success(
            api.approve_substitution(ctx["sub"]["id"], make_qa_headers("qa-906")), 200
        )
        assert approved["status"] == "APPROVED"

        lines, _ = validate_paginated(
            api.list_panel_components(ctx["panel"]["id"], pm_headers)
        )
        replacement = [l for l in lines if l.get("substituted_for_id") == ctx["con_line"]["id"]]
        assert len(replacement) == 1, "exactly one replacement line must reference the original"
        repl = replacement[0]
        assert repl["line_status"] == "SUBSTITUTED"
        assert repl["component_id"] == ctx["con22"]["id"]
        assert repl["unit_cost_snapshot_cents"] == 9000

        original = validate_success(
            api.get_panel_component(ctx["con_line"]["id"], pm_headers), 200
        )
        assert original["line_status"] == "SUBSTITUTED", (
            "original ORDERED line retires to SUBSTITUTED as a superseded marker"
        )

        panel = validate_success(api.get_panel(ctx["panel"]["id"], pm_headers), 200)
        assert panel["sccr_rating_ka"] == 10, (
            f"min over {{BPD 10, CON 22}} with no current-limiting raise = 10, got "
            f"{panel['sccr_rating_ka']}"
        )

    def test_substitution_approval_cascades_job_posture_to_build(self, api, pm_headers,
                                                                 sl_headers):
        """PRD §3.1: "When every BOM line across every panel has reached `RECEIVED`
        or `SUBSTITUTED`, the job auto-advances `PROCUREMENT → BUILD`."
        PRD §3.3: "The panel's `sccr_rating_ka` is recomputed under the new component
        mix".

        Design: Difficulty/transitive_cascade/substitution_approval_cascade_bom_sccr_posture_depth3
        """
        ctx = self._setup_cascade(api, pm_headers, sl_headers)
        job_before = validate_success(api.get_job(ctx["job"]["id"], pm_headers), 200)
        assert job_before["status"] == "PROCUREMENT", (
            f"precondition: job PROCUREMENT, got {job_before['status']}"
        )

        validate_success(
            api.approve_substitution(ctx["sub"]["id"], make_qa_headers("qa-906")), 200
        )
        job_after = validate_success(api.get_job(ctx["job"]["id"], pm_headers), 200)
        assert job_after["status"] == "BUILD", (
            f"posture cascade: no line remains PENDING/ORDERED, got {job_after['status']}"
        )


class TestBomRollupRetiredLine:
    def test_bom_rollup_excludes_retired_substituted_original(self, api, de_headers,
                                                              pm_headers):
        """PRD §3.3: "The original line is retired from the active BOM: if its
        `line_status` was `PENDING` or `ORDERED`, it is set to `SUBSTITUTED` as a
        superseded marker; if it was already `RECEIVED`, it stays `RECEIVED` for
        receipt-audit purposes but is excluded from both the BOM cost rollup and the
        SCCR weakest-link input sets (those input sets include a line only when no
        other line references it via `substituted_for_id`)."
        PRD §3.2: "it computes the line's `extended_cost_cents` as `quantity`
        multiplied by `unit_cost_snapshot_cents` rounded half-up to integer cents".

        Design: Corner/calculations/bom_rollup_excludes_retired_substituted_original
        """
        ctx = setup_panel_with_bom(
            company_name="Rollup Co", job_number="J-RU1", quoted_price_cents=100000,
            panel_tag="P-RU1", design_engineer_id="de-ru",
            component_spec={
                "part_number": "BPD-RU", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        con = new_component(
            part_number="CON-RU", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=5, heat_dissipation_w=20,
        )
        con_sub = new_component(
            part_number="CON-RU-S", component_class="CONTACTOR", unit_cost_cents=9000,
            lead_time_days=9, sccr_ka=22, heat_dissipation_w=20,
        )
        con_line = add_bom_line(panel_id, con["id"])
        walk_panel_to_design_approved(panel_id, qa_user_id="qa-ru")
        get_success_data(api.release_procurement(panel_id, pm_headers), 200)
        sub = new_substitution_request(panel_id, con_line["id"], con_sub["id"],
                                       requested_by="de-ru", reason="stockout")
        validate_success(api.approve_substitution(sub["id"], make_qa_headers("qa-ru")), 200)

        lines, _ = validate_paginated(api.list_panel_components(panel_id, de_headers))
        assert len(lines) == 3, (
            f"original BPD + retired CON + replacement CON = 3 rows, got {len(lines)}"
        )
        retired_ids = {l["substituted_for_id"] for l in lines if l.get("substituted_for_id")}
        assert retired_ids == {con_line["id"]}
        active_total = sum(
            l["extended_cost_cents"] for l in lines if l["id"] not in retired_ids
        )
        assert active_total == 19000, (
            f"active rollup 10000 + 9000 = 19000 (retired original excluded), got {active_total}"
        )
