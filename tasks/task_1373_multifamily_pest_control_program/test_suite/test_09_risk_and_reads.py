"""Computed reads: the dual-variant unit risk score, list pagination and
filtering, and the property summary aggregate."""
from test_helpers import (
    complete_inspection_payload,
    get_success_data,
    make_technician_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    assess_chargeback,
    complete_positive_inspection,
    create_lease,
    create_unit,
    schedule_inspection,
    schedule_treatment,
    setup_community,
)


class TestRiskScoreVariants:
    def _setup_forward_historical(self, api):
        """One SEVERE bed-bug-positive inspection (at the default clock
        2026-08-01) plus one future SCHEDULED treatment on the same unit."""
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, tech = ctx["unit"], ctx["technician"]
        complete_positive_inspection(unit["id"], tech, scheduled_for="2026-08-05T09:00:00Z")
        schedule_treatment(unit["id"], tech["id"], pest_type="BED_BUGS",
                           window_start="2026-08-10T09:00:00Z",
                           window_end="2026-08-10T10:00:00Z")
        return ctx, unit

    def test_forward_variant_counts_scheduled_treatment(self, api):
        """PRD §3.9: "The recency term depends on the variant: under `FORWARD`,
        relevant treatments are those in `SCHEDULED`, `PREP_NOTIFIED`,
        `PREP_VERIFIED`, or `COMPLETED`, so a future-dated scheduled treatment
        zeroes the term; under `HISTORICAL`, only `COMPLETED` treatments count,
        so scheduled-but-incomplete work is invisible and the term stays high."
        PRD §3.9: "The severe-history term contributes 40 when the unit has any
        completed inspection with `severity` `SEVERE` whose `completed_at` lies
        within the trailing 90 days, and zero otherwise. The prior-cases term
        contributes 15 per bed bug case of the unit, regardless of status,
        counting at most 3 cases."

        Design: Difficulty/dual_variant_calc/unit_risk_forward_vs_historical
        """
        ctx, unit = self._setup_forward_historical(api)
        fwd = validate_success(api.get_unit_risk_score(unit["id"], MANAGER,
                                                       params={"variant": "FORWARD"}))
        assert fwd["variant"] == "FORWARD"
        assert fwd["severe_recent"] == 40
        assert fwd["prior_cases_points"] == 15
        assert fwd["adjacent_open_points"] == 0
        assert fwd["recency_points"] == 0
        assert fwd["score"] == 55

    def test_historical_variant_ignores_scheduled_treatment(self, api):
        """PRD §3.9: "The recency term depends on the variant: under `FORWARD`,
        relevant treatments are those in `SCHEDULED`, `PREP_NOTIFIED`,
        `PREP_VERIFIED`, or `COMPLETED`, so a future-dated scheduled treatment
        zeroes the term; under `HISTORICAL`, only `COMPLETED` treatments count,
        so scheduled-but-incomplete work is invisible and the term stays high.
        When no relevant treatment exists with a `window_start` inside the
        trailing 180 days, the recency term contributes its full 25; otherwise
        it contributes 5 points per whole 30-day step elapsed since the most
        recent relevant `window_start` — negative elapsed time floors at zero
        days — capped at 25."

        Design: Difficulty/dual_variant_calc/unit_risk_forward_vs_historical
        """
        ctx, unit = self._setup_forward_historical(api)
        hist = validate_success(api.get_unit_risk_score(unit["id"], MANAGER,
                                                        params={"variant": "HISTORICAL"}))
        assert hist["variant"] == "HISTORICAL"
        assert hist["recency_points"] == 25
        assert hist["score"] == 80


class TestRiskScoreCaps:
    def test_risk_score_component_caps_and_total_ceiling(self, api):
        """PRD §3.9: "The severe-history term contributes 40 when the unit has
        any completed inspection with `severity` `SEVERE` whose `completed_at`
        lies within the trailing 90 days, and zero otherwise. The prior-cases
        term contributes 15 per bed bug case of the unit, regardless of status,
        counting at most 3 cases. The adjacent-exposure term contributes 10 per
        live case — status `OPEN`, `TREATING`, `MONITORING`, or `REOPENED` — on
        units the adjacency predicate of §3.3 would select for this unit,
        counting at most 2 such cases."
        PRD §3.9: "The score sums four terms, capped at 100."

        Design: Corner/calculations/risk_score_component_caps_and_total_ceiling
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        prop, tech = ctx["property"], ctx["technician"]
        u202 = create_unit(prop["id"], unit_number="202", floor=2, stack_index=2)
        u102 = create_unit(prop["id"], unit_number="102", floor=1, stack_index=2)
        u302 = create_unit(prop["id"], unit_number="302", floor=3, stack_index=2)
        u201 = create_unit(prop["id"], unit_number="201", floor=2, stack_index=1)
        complete_positive_inspection(u102["id"], tech, scheduled_for="2026-08-05T09:00:00Z")
        complete_positive_inspection(u302["id"], tech, scheduled_for="2026-08-05T10:00:00Z")
        complete_positive_inspection(u201["id"], tech, scheduled_for="2026-08-05T11:00:00Z")
        complete_positive_inspection(u202["id"], tech, scheduled_for="2026-08-05T12:00:00Z")

        risk = validate_success(api.get_unit_risk_score(u202["id"], MANAGER,
                                                        params={"variant": "HISTORICAL"}))
        assert risk["adjacent_open_points"] == 20, "3 adjacent open cases capped at 2 x 10"
        assert risk["recency_points"] == 25, "no treatments at all -> full recency term"
        assert risk["severe_recent"] == 40
        assert risk["score"] == 100, "40 + 15 + 20 + 25 reaches the ceiling exactly"


class TestListPagination:
    def test_list_pagination_defaults_and_filtering(self, api):
        """PRD §2.3: "All list endpoints accept the query parameters `limit`
        and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0. List responses order results by
        `created_at` ascending, and the `meta` object of a list response
        carries `limit`, `offset`, `total_count`, and `has_more`. Certain list
        endpoints accept additional filter parameters — `floor` on the unit
        list, `status` on lease-chargeback, technician-treatment,
        technician-inspection, unit-treatment, bed-bug-case, and
        furniture-disposal lists, and `kind` on the unit-inspection list — all
        of which are optional."

        Design: Corner/endpoints/list_pagination_defaults_and_filtering
        """
        from test_helpers.fixtures import create_property
        prop = create_property(name="Page Hall", address="36 Page Way")
        for floor, prefix in ((1, 10), (2, 20)):
            for stack in range(1, 7):
                create_unit(prop["id"], unit_number=f"{prefix}{stack}", floor=floor,
                            stack_index=stack, bedrooms=1)

        data, meta = validate_paginated(api.list_units(prop["id"], ADMIN))
        assert len(data) == 10, "default limit is 10"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_units(prop["id"], ADMIN, params={"limit": 5, "offset": 10})
        )
        assert len(data2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

        data3, meta3 = validate_paginated(
            api.list_units(prop["id"], ADMIN, params={"floor": 1})
        )
        assert len(data3) == 6
        assert all(u["floor"] == 1 for u in data3)
        assert meta3["total_count"] == 6


class TestPropertySummary:
    def test_property_summary_aggregates_lease_balances(self, api):
        """PRD §3.1: "A computed summary read returns `posture`,
        `open_bed_bug_case_count`, and `total_outstanding_balance_cents`, the
        aggregate of outstanding balances across the property."
        PRD §3.2: "`outstanding_balance_cents` is the sum of
        `provisional_amount_cents` over the lease's chargebacks in `ASSESSED`
        or `DISPUTED`, plus the sum of `final_amount_cents` over chargebacks in
        `UPHELD` or `BILLED`; chargebacks that are `WAIVED` or `PAID`
        contribute zero."

        Design: Corner/endpoints/property_summary_aggregates_lease_balances
        """
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"],
                                                  "coverage_per_incident_cents": 20000})
        u1, u2 = ctx["units"]
        lease1 = create_lease(u1["id"])
        lease2 = create_lease(u2["id"])
        assess_chargeback(lease1["id"], kind="NON_COMPLIANCE_FEE")
        assess_chargeback(lease2["id"], kind="REPEAT_INFESTATION")

        summary = validate_success(api.get_property_summary(ctx["property"]["id"], MANAGER))
        assert summary["total_outstanding_balance_cents"] == 18275, "16125 + 2150"
        assert summary["posture"] == "STANDARD"
        assert summary["open_bed_bug_case_count"] == 0
