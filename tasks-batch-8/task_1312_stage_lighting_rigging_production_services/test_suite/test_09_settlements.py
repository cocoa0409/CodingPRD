"""Settlement statements: the provisional vs final damage variants, the
charge/waive conservation pair, issuance gates, disputes, and the
production -> settlement reverse lookup."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_planning_production, setup_load_in_production,
    setup_closed_production_with_assessed_damage,
    create_settlement, get_settlement, transition_settlement,
    charge_report, waive_report, get_damage_report, get_production,
    file_damage_report, assess_report,
)

PM = TEST_USERS["production_manager_headers"]
WH = TEST_USERS["warehouse_chief_headers"]
CLIENT = TEST_USERS["client_contact_headers"]


class TestProvisionalVsFinalDamage:
    def test_settlement_provisional_vs_final_damage_inclusion(self, api):
        """PRD §3.9: "Alongside the live totals, generation freezes a forward-looking snapshot: `provisional_damage_cents` captures the sum of `assessed_charge_cents` over reports then in `ASSESSED` or `CHARGED` at creation time, and `provisional_grand_total_cents` is `labor_total_cents` plus `equipment_total_cents` plus that provisional damage figure. Neither provisional field is ever recomputed."
        PRD §3.9: "Issuing the statement (`DRAFT` → `ISSUED`) requires every damage report of the production to be in `CHARGED` or `WAIVED` — open reports block issuance with `ERR_UNRESOLVED_DAMAGE_REPORTS` (HTTP 409) — and recomputes `damage_total_cents` over `CHARGED` reports and the `grand_total_cents` as the final variant, after which the totals stop moving; the provisional fields stay frozen regardless."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_damage_inclusion
        """
        # labor 100000 (8.00h IATSE) + equipment 5000 (same-day) + report ASSESSED 80000.
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        assert st["provisional_damage_cents"] == 80000
        assert st["provisional_grand_total_cents"] == 185000
        assert st["damage_total_cents"] == 0, "the FINAL variant counts CHARGED only"
        assert st["grand_total_cents"] == 105000
        waive_report(ctx["report"]["id"])
        st = transition_settlement(st["id"], {"to": "ISSUED"})
        assert st["damage_total_cents"] == 0
        assert st["grand_total_cents"] == 105000
        st = get_settlement(st["id"])
        assert st["provisional_grand_total_cents"] == 185000, "provisional stays frozen"

    def test_charged_report_flows_into_final_variant_on_issue(self, api):
        """PRD §3.9: "The live totals are `labor_total_cents` — the sum of `labor_cost_cents` over the production's `COMPLETED` crew calls — `equipment_total_cents` — the sum of `rental_charge_cents` over entries in `RETURNED`, `DAMAGED`, or `LOST` — and `damage_total_cents`, which counts `assessed_charge_cents` over `CHARGED` reports only and moves with every subsequent charge or waive while the settlement is `DRAFT`."
        PRD §3.9: "The `grand_total_cents` is the sum of the three."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_damage_inclusion
        """
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        charge_report(ctx["report"]["id"])
        st = transition_settlement(st["id"], {"to": "ISSUED"})
        assert st["labor_total_cents"] == 100000
        assert st["equipment_total_cents"] == 5000
        assert st["damage_total_cents"] == 80000
        assert st["grand_total_cents"] == 185000
        assert st["provisional_grand_total_cents"] == 185000


class TestSettlementDamageConservation:
    def test_settlement_damage_total_conservation(self, api):
        """PRD §3.8: "Charging (`ASSESSED` → `CHARGED`, by the `WarehouseChief`) requires the production's settlement to exist and still be `DRAFT` (otherwise `ERR_SETTLEMENT_NOT_DRAFT`, HTTP 409); the report's `assessed_charge_cents` is debited into the settlement's `damage_total_cents`, its `grand_total_cents` is recomputed, and both the report's and the settlement's `version` increment. A `ProductionManager` may waive an `ASSESSED` report outright, or waive a `CHARGED` report — compensation after the fact — which again requires the settlement to be `DRAFT` (same `ERR_SETTLEMENT_NOT_DRAFT`) and credits the `assessed_charge_cents` back out of `damage_total_cents` with the grand total recomputed."

        Design: Difficulty/compensating_invariant/settlement_damage_total_conservation
        """
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        assert st["damage_total_cents"] == 0 and st["grand_total_cents"] == 105000
        charge_report(ctx["report"]["id"])
        st = get_settlement(st["id"])
        assert st["damage_total_cents"] == 80000 and st["grand_total_cents"] == 185000
        waive_report(ctx["report"]["id"])
        st = get_settlement(st["id"])
        assert st["damage_total_cents"] == 0 and st["grand_total_cents"] == 105000, \
            "the charge/waive pair must leave the settlement exactly as before"

    def test_waive_from_assessed_leaves_settlement_untouched(self, api):
        """PRD §3.8: "A `ProductionManager` may waive an `ASSESSED` report outright, or waive a `CHARGED` report — compensation after the fact — which again requires the settlement to be `DRAFT` (same `ERR_SETTLEMENT_NOT_DRAFT`) and credits the `assessed_charge_cents` back out of `damage_total_cents` with the grand total recomputed. Both waive paths land in `WAIVED`."

        Design: Difficulty/compensating_invariant/settlement_damage_total_conservation
        """
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        data = waive_report(ctx["report"]["id"])
        assert data["status"] == "WAIVED"
        st = get_settlement(st["id"])
        assert st["damage_total_cents"] == 0
        assert st["grand_total_cents"] == 105000


class TestSettlementGates:
    def test_charge_without_draft_settlement(self, api):
        """PRD §3.8: "Charging (`ASSESSED` → `CHARGED`, by the `WarehouseChief`) requires the production's settlement to exist and still be `DRAFT` (otherwise `ERR_SETTLEMENT_NOT_DRAFT`, HTTP 409); the report's `assessed_charge_cents` is debited into the settlement's `damage_total_cents`, its `grand_total_cents` is recomputed, and both the report's and the settlement's `version` increment."

        Design: Corner/errors/charge_without_draft_settlement
        """
        ctx = setup_load_in_production()
        report = file_damage_report(ctx["production"]["id"], ctx["entry"]["id"], "DAMAGE")
        assess_report(report["id"], "DEPRECIATED")
        resp = api.transition_damage_report(report["id"], {"to": "CHARGED"}, WH)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_DRAFT)
        assert get_damage_report(report["id"])["status"] == "ASSESSED"

    def test_settlement_issue_and_duplicate_gates(self, api):
        """PRD §3.9: "Issuing the statement (`DRAFT` → `ISSUED`) requires every damage report of the production to be in `CHARGED` or `WAIVED` — open reports block issuance with `ERR_UNRESOLVED_DAMAGE_REPORTS` (HTTP 409) — and recomputes `damage_total_cents` over `CHARGED` reports and the `grand_total_cents` as the final variant, after which the totals stop moving; the provisional fields stay frozen regardless."
        PRD §3.9: "Exactly one settlement may exist per production; a second generation attempt is rejected with `ERR_SETTLEMENT_EXISTS` (HTTP 409)."

        Design: Corner/errors/settlement_issue_and_duplicate_gates
        """
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        # R1 is still ASSESSED (open), so issuance is blocked.
        resp = api.transition_settlement(st["id"], {"to": "ISSUED"}, PM)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DAMAGE_REPORTS)
        resp = api.create_settlement(ctx["production"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXISTS)

    def test_dispute_resolve_adjustment_bounds(self, api):
        """PRD §3.9: "A `ClientContact` disputes an issued statement (`ISSUED` → `DISPUTED`), and the `ProductionManager` resolves the dispute (`DISPUTED` → `RESOLVED`) by supplying a signed `dispute_adjustment_cents`, a field that defaults to 0 and stays there on a statement that is paid without dispute. The adjustment's magnitude may not exceed the settlement's `damage_total_cents` at resolve time — a larger swing is rejected with `ERR_ADJUSTMENT_OUT_OF_RANGE` (HTTP 422) — and a valid adjustment is added into `grand_total_cents`."
        PRD §3.9: "Either terminal outcome — `RESOLVED` or `PAID` — fires the production's own final transition, `CLOSED` → `SETTLED`, closing the lifecycle that began with the venue booking."

        Design: Corner/errors/dispute_resolve_adjustment_bounds
        """
        ctx = setup_closed_production_with_assessed_damage()
        st = create_settlement(ctx["production"]["id"])
        charge_report(ctx["report"]["id"])
        st = transition_settlement(st["id"], {"to": "ISSUED"})
        assert st["grand_total_cents"] == 185000
        # DISPUTED belongs to ClientContact; the ProductionManager is denied.
        resp = api.transition_settlement(st["id"], {"to": "DISPUTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        st = transition_settlement(st["id"], {"to": "DISPUTED"}, CLIENT)
        assert st["status"] == "DISPUTED"
        # |80001| > damage_total 80000 -> out of range.
        resp = api.transition_settlement(
            st["id"], {"to": "RESOLVED", "dispute_adjustment_cents": 80001}, PM)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_OUT_OF_RANGE)
        st = transition_settlement(
            st["id"], {"to": "RESOLVED", "dispute_adjustment_cents": -5000}, PM)
        assert st["status"] == "RESOLVED"
        assert st["grand_total_cents"] == 180000
        assert get_production(ctx["production"]["id"])["status"] == "SETTLED"


class TestSettlementReverseLookup:
    def test_settlement_fk_reverse_lookup(self, api):
        """PRD §4: "Fetch the production's settlement (array of length 0 or 1)" — the reverse lookup is an array endpoint, never a bare 404 or bare object.

        Design: Corner/endpoints/settlement_fk_reverse_lookup
        """
        ctx = setup_planning_production()
        data, meta = validate_paginated(
            api.get_production_settlement(ctx["production"]["id"], PM))
        assert data == [] and meta["total_count"] == 0
