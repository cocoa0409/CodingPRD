"""Royalty agreements (amendment chains) and statements (tiered royalty,
period rules, issuance SoD, payment penalties)."""
import pytest

from test_helpers import (
    FINANCE,
    MANAGER,
    ApiErrorId,
    complete_ticket,
    create_agreement,
    create_royalty_agreement_payload,
    create_site,
    generate_statement,
    get_statement,
    get_ticket,
    make_finance_clerk_headers,
    make_site_manager_headers,
    set_clock,
    setup_ticketing_site,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE_2 = make_finance_clerk_headers("fc-2")


class TestAgreementLifecycle:
    def test_agreement_active_uniqueness_rejected(self, api):
        """PRD 3.8: "At most one agreement per site may stand `ACTIVE` — a
        second creation is rejected with `ERR_AGREEMENT_ALREADY_ACTIVE`,
        directing the clerk to amendments".

        Design: Corner/validations/agreement_active_uniqueness_rejected
        """
        site = create_site()
        agr = create_agreement(site["id"])
        payload = create_royalty_agreement_payload(
            site["id"], landowner_name="LW2", base_rate_per_ton=0.30,
            tier_threshold_tons=60, tier_rate_per_ton=0.45,
            effective_from="2026-06-01")
        resp = api.create_royalty_agreement(payload, FINANCE)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_ALREADY_ACTIVE)
        agr = validate_success(api.get_royalty_agreement(agr["id"], FINANCE))
        assert agr["status"] == "ACTIVE"

    def test_amendment_supersede_chain_and_double_amend_rejected(self, api):
        """PRD 3.8: "Amending is a create-with-supersede act against an
        agreement that must stand `ACTIVE` — attempting it against an
        already superseded or terminated agreement is a state failure,
        `ERR_INVALID_STATE`, not a race. The old agreement moves `ACTIVE` →
        `SUPERSEDED`, its `effective_to` is set to the amendment's
        `effective_from`, and its `version` increments; the payload rates
        (`base_rate_per_ton`, `tier_threshold_tons`, `tier_rate_per_ton`,
        `effective_from`) create a new agreement that is born `ACTIVE` with
        its `supersedes_agreement_id` pointing back at the old one."

        Design: Corner/validations/amendment_supersede_chain_and_double_amend_rejected
        """
        site = create_site()
        agr_a = create_agreement(site["id"])
        agr_a_v = agr_a["version"]
        agr_b = validate_success(api.amend_royalty_agreement(
            agr_a["id"],
            {"base_rate_per_ton": 0.30, "tier_threshold_tons": 60,
             "tier_rate_per_ton": 0.45, "effective_from": "2026-07-01"},
            FINANCE), 201)
        assert agr_b["status"] == "ACTIVE"
        assert agr_b["supersedes_agreement_id"] == agr_a["id"]
        assert agr_b["base_rate_per_ton"] == pytest.approx(0.30, abs=1e-9)
        agr_a = validate_success(api.get_royalty_agreement(agr_a["id"],
                                                           FINANCE))
        assert agr_a["status"] == "SUPERSEDED"
        assert agr_a["effective_to"] == "2026-07-01"
        assert agr_a["version"] == agr_a_v + 1
        resp = api.amend_royalty_agreement(
            agr_a["id"],
            {"base_rate_per_ton": 0.35, "tier_threshold_tons": 70,
             "tier_rate_per_ton": 0.50, "effective_from": "2026-08-01"},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data, _meta = validate_paginated(api.list_royalty_agreements(
            FINANCE, params={"supersedes_agreement_id": agr_a["id"]}))
        assert [a["id"] for a in data] == [agr_b["id"]]


class TestStatementRules:
    def test_statement_pay_from_draft_rejected(self, api):
        """PRD 3.8: "Payment is recorded by a `FinanceClerk` with a
        `paid_on` date, moving the statement `ISSUED` → `PAID`" — a `DRAFT`
        statement cannot be paid.
        PRD 2.7 tier 5: "Own state — the target resource's own state must
        permit the requested transition ... otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/statement_pay_from_draft_rejected
        """
        site = create_site()
        create_agreement(site["id"])
        stmt = generate_statement(site["id"], "2026-01-01", "2026-02-01")
        assert stmt["status"] == "DRAFT"
        resp = api.pay_royalty_statement(stmt["id"],
                                         {"paid_on": "2026-08-15"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        stmt = get_statement(stmt["id"])
        assert stmt["status"] == "DRAFT"
        assert stmt.get("penalty_usd") is None

    def test_sod_statement_issue_same_user_rejected(self, api):
        """PRD 2.10: "A royalty statement may not be issued by the clerk
        who generated it. ... Each violation is rejected with
        `ERR_SOD_VIOLATION` (403)."

        Design: Corner/validations/sod_statement_issue_same_user_rejected
        """
        site = create_site()
        create_agreement(site["id"])
        stmt = generate_statement(site["id"], "2026-01-01", "2026-02-01")
        assert stmt["generated_by_user_id"] == "fc-1"
        resp = api.issue_royalty_statement(stmt["id"],
                                           make_site_manager_headers("fc-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert get_statement(stmt["id"])["status"] == "DRAFT"

    def test_statement_not_chronological_rejected(self, api):
        """PRD 3.8: "A site's non-`VOID` statement periods must not overlap
        under that half-open comparison (`ERR_STATEMENT_PERIOD_OVERLAP`)
        and must be generated in chronological order — a new `period_start`
        earlier than an existing statement's `period_end` is rejected with
        `ERR_STATEMENT_NOT_CHRONOLOGICAL`."

        Design: Corner/validations/statement_not_chronological_rejected
        """
        site = create_site()
        create_agreement(site["id"])
        generate_statement(site["id"], "2026-02-01", "2026-03-01")
        # [2026-01-01, 2026-02-01) does not overlap [2026-02-01, 2026-03-01)
        # under the half-open comparison, but it breaks generation order.
        resp = api.create_royalty_statement(
            {"site_id": site["id"], "period_start": "2026-01-01",
             "period_end": "2026-02-01"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_CHRONOLOGICAL)

    def test_statement_period_overlap_rejected(self, api):
        """PRD 3.8: "A site's non-`VOID` statement periods must not overlap
        under that half-open comparison (`ERR_STATEMENT_PERIOD_OVERLAP`)".

        Design: Difficulty/resource_temporal_overlap/statement_period_half_open_adjacency
        """
        site = create_site()
        create_agreement(site["id"])
        s1 = generate_statement(site["id"], "2026-01-01", "2026-02-01")
        resp = api.create_royalty_statement(
            {"site_id": site["id"], "period_start": "2026-01-15",
             "period_end": "2026-02-15"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)
        assert get_statement(s1["id"])["status"] == "DRAFT"

    def test_statement_period_adjacency_accepted(self, api):
        """PRD 3.8: "Periods are half-open: a ticket belongs to the period
        when its `completed_at` falls on or after `period_start` and
        strictly before `period_end`." A new period starting exactly at the
        prior period's end shares no instant with it, so it is accepted.

        Design: Difficulty/resource_temporal_overlap/statement_period_half_open_adjacency
        """
        site = create_site()
        create_agreement(site["id"])
        generate_statement(site["id"], "2026-01-01", "2026-02-01")
        s2 = generate_statement(site["id"], "2026-02-01", "2026-03-01")
        assert s2["status"] == "DRAFT"
        assert s2["tons_sold"] == pytest.approx(0, abs=1e-9)


class TestRoyaltyAmounts:
    def test_provisional_royalty_flat_rate_per_ticket(self, api):
        """PRD 3.7: "The provisional royalty `royalty_provisional_usd`
        accrues at the flat base rate — `net_tons` times the covering
        agreement's `base_rate_per_ton`, rounded half-up to two decimals —
        with no tier awareness; §3.8 finalizes it."

        Design: Difficulty/dual_variant_calc/royalty_provisional_flat_vs_final_marginal_tier
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                                   calibrated_on="2025-12-01")
        set_clock("2026-01-10T12:00:00Z")
        _e1, t1 = complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        _e2, t2 = complete_ticket(ctx, truck_id="TRK-2", gross_lbs=80000)
        # 26.000 t x 0.25 = 6.50 per ticket (provisional total 13.00).
        assert t1["net_tons"] == pytest.approx(26.000, abs=1e-6)
        assert t1["royalty_provisional_usd"] == pytest.approx(6.50, abs=1e-6)
        assert t2["royalty_provisional_usd"] == pytest.approx(6.50, abs=1e-6)

    def test_final_royalty_marginal_tier_diverges(self, api):
        """PRD 3.8: "Each ticket in turn is split at the tier threshold
        against the running total: the below-tier portion is the smaller of
        the ticket's `net_tons` and the distance remaining from the running
        total up to `tier_threshold_tons`, floored at zero when the
        threshold is already passed, and the above-tier portion is whatever
        tonnage remains. The ticket's royalty is the below-tier portion
        times `base_rate_per_ton` plus the above-tier portion times
        `tier_rate_per_ton`, rounded half-up to two decimals per ticket".

        Design: Difficulty/dual_variant_calc/royalty_provisional_flat_vs_final_marginal_tier
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                                   calibrated_on="2025-12-01")
        set_clock("2026-01-10T12:00:00Z")
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=80000)
        stmt = generate_statement(ctx["site"]["id"], "2026-01-01",
                                  "2026-02-01")
        # t1: 26.000 all at base = 6.50; t2: 24 at base + 2 at tier
        # = 6.00 + 0.80 = 6.80; total 13.30 (provisional total was 13.00).
        assert stmt["royalty_due_usd"] == pytest.approx(13.30, abs=1e-6)
        assert stmt["tons_sold"] == pytest.approx(52.000, abs=1e-6)
        assert stmt["ytd_tons_before"] == pytest.approx(0, abs=1e-9)
        assert stmt["ytd_tons_after"] == pytest.approx(52.000, abs=1e-6)

    def test_royalty_per_ticket_rounding_order_net_tons(self, api):
        """PRD 3.7: "The `net_tons` are `gross_lbs` minus `tare_lbs`,
        divided by 2,000 pounds per ton, rounded half-up to three
        decimals."

        Design: Difficulty/combinatorial_formula/royalty_per_ticket_rounding_order
        """
        ctx = setup_ticketing_site(
            on_hand=100.0, quantity_tons=25,
            agreement_overrides={"base_rate_per_ton": 0.50,
                                 "tier_threshold_tons": 1000000,
                                 "tier_rate_per_ton": 0.75})
        _e1, t1 = complete_ticket(ctx, truck_id="TRK-1", gross_lbs=48020)
        _e2, t2 = complete_ticket(ctx, truck_id="TRK-2", gross_lbs=48020)
        assert t1["net_tons"] == pytest.approx(10.010, abs=1e-6)
        assert t2["net_tons"] == pytest.approx(10.010, abs=1e-6)

    def test_royalty_per_ticket_rounding_order_statement_total(self, api):
        """PRD 3.8: "The rounding order is part of the contract: each
        ticket is rounded to cents first and the cents are summed —
        summing tonnage first and rounding once yields different cents and
        is wrong."

        Design: Difficulty/combinatorial_formula/royalty_per_ticket_rounding_order
        """
        ctx = setup_ticketing_site(
            on_hand=100.0, quantity_tons=25,
            agreement_overrides={"base_rate_per_ton": 0.50,
                                 "tier_threshold_tons": 1000000,
                                 "tier_rate_per_ton": 0.75})
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=48020)
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=48020)
        stmt = generate_statement(ctx["site"]["id"], "2026-08-01",
                                  "2026-09-01")
        # round_half_up(10.010 x 0.50, 2) = 5.01 per ticket -> 10.02
        # (summing tons first would yield round(20.020 x 0.50) = 10.01).
        assert stmt["royalty_due_usd"] == pytest.approx(10.02, abs=1e-6)

    def test_royalty_tier_exact_threshold_january(self, api):
        """PRD 3.8: "the below-tier portion is the smaller of the ticket's
        `net_tons` and the distance remaining from the running total up to
        `tier_threshold_tons`, floored at zero when the threshold is
        already passed" — landing exactly on the threshold leaves zero
        above-tier tons.

        Design: Difficulty/boundary_precision_check/royalty_tier_exact_threshold_boundary
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                                   calibrated_on="2025-12-01")
        set_clock("2026-01-10T12:00:00Z")
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)   # 26.000
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=76000)   # 24.000
        stmt = generate_statement(ctx["site"]["id"], "2026-01-01",
                                  "2026-02-01")
        # 26.000x0.25 + 24.000x0.25 = 6.50 + 6.00 = 12.50; YTD lands
        # exactly on the 50 t threshold with zero tier-rate tonnage.
        assert stmt["tons_sold"] == pytest.approx(50.000, abs=1e-6)
        assert stmt["ytd_tons_after"] == pytest.approx(50.000, abs=1e-6)
        assert stmt["royalty_due_usd"] == pytest.approx(12.50, abs=1e-6)

    def test_royalty_tier_exact_threshold_february_all_tier(self, api):
        """PRD 3.8: "The running total starts at `ytd_tons_before`: the sum
        of `tons_sold` over the site's other non-`VOID` statements whose
        `period_start` lies in the same calendar year as this statement's
        `period_start` and is strictly earlier". With the threshold exactly
        exhausted, the next period's tonnage is entirely above-tier.

        Design: Difficulty/boundary_precision_check/royalty_tier_exact_threshold_boundary
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                                   calibrated_on="2025-12-01")
        set_clock("2026-01-10T12:00:00Z")
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)   # 26.000
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=76000)   # 24.000
        generate_statement(ctx["site"]["id"], "2026-01-01", "2026-02-01")
        set_clock("2026-02-10T12:00:00Z")
        complete_ticket(ctx, truck_id="TRK-3", gross_lbs=80000)   # 26.000
        stmt = generate_statement(ctx["site"]["id"], "2026-02-01",
                                  "2026-03-01")
        assert stmt["ytd_tons_before"] == pytest.approx(50.000, abs=1e-6)
        # 26.000 t entirely at the tier rate 0.40 -> 10.40.
        assert stmt["royalty_due_usd"] == pytest.approx(10.40, abs=1e-6)

    def test_statement_input_set_excludes_voided_and_out_of_period(self,
                                                                   api):
        """PRD 3.8: "The input set is the site's tickets standing
        `COMPLETED` — voided tickets are never included — with
        `completed_at` inside the half-open period, processed in
        chronological order by `completed_at` with ties broken by
        `created_at` ascending; order matters because of the year-to-date
        tier."

        Design: Corner/calculations/statement_input_set_excludes_voided_and_out_of_period
        """
        ctx = setup_ticketing_site(on_hand=500.0, quantity_tons=500,
                                   calibrated_on="2025-12-01")
        # T3 completes before the statement period starts.
        set_clock("2026-01-05T09:00:00Z")
        _e3, t3 = complete_ticket(ctx, truck_id="TRK-3", gross_lbs=88000)
        assert t3["net_tons"] == pytest.approx(30.000, abs=1e-6)
        set_clock("2026-01-15T09:00:00Z")
        _e1, _t1 = complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        _e2, t2 = complete_ticket(ctx, truck_id="TRK-2", gross_lbs=76000)
        # Void the second in-period ticket before any statement covers it.
        t2 = validate_success(api.void_scale_ticket(
            t2["id"], {"void_reason": "mis-keyed gross"}, MANAGER))
        assert t2["status"] == "VOIDED"
        stmt = generate_statement(ctx["site"]["id"], "2026-01-10",
                                  "2026-02-10")
        # Only T1 counts: T2 is VOIDED, T3 completed outside the period.
        assert stmt["tons_sold"] == pytest.approx(26.000, abs=1e-6)
        assert stmt["royalty_due_usd"] == pytest.approx(6.50, abs=1e-6)
        assert get_ticket(t3["id"])["status"] == "COMPLETED"


class TestStatementPenalty:
    def test_statement_penalty_on_time_vs_late(self, api):
        """PRD 3.8: "Issuance moves the statement `DRAFT` → `ISSUED`,
        records `issued_by_user_id`, stamps `issued_on` from the logical
        date, and sets `due_on` thirty days after `issued_on`. Payment is
        recorded by a `FinanceClerk` with a `paid_on` date, moving the
        statement `ISSUED` → `PAID` and computing `penalty_usd`: zero when
        `paid_on` is on or before `due_on` — paying exactly on the due date
        incurs no penalty — and otherwise five percent of
        `royalty_due_usd`, rounded half-up to two decimals."

        Design: Corner/calculations/statement_penalty_on_time_vs_late
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100,
                                   calibrated_on="2025-12-01")
        set_clock("2026-01-10T09:00:00Z")
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)   # 26.000
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=76000)   # 24.000
        s1 = generate_statement(ctx["site"]["id"], "2026-01-01", "2026-02-01")
        assert s1["royalty_due_usd"] == pytest.approx(12.50, abs=1e-6)
        set_clock("2026-01-20T09:00:00Z")
        s1 = validate_success(api.issue_royalty_statement(s1["id"], MANAGER))
        assert s1["issued_on"] == "2026-01-20"
        assert s1["due_on"] == "2026-02-19"
        s1 = validate_success(api.pay_royalty_statement(
            s1["id"], {"paid_on": "2026-02-19"}, FINANCE_2))
        assert s1["status"] == "PAID"
        assert s1["penalty_usd"] == pytest.approx(0.00, abs=1e-9)
        # February: one 26.000 t ticket, all above the exhausted threshold.
        set_clock("2026-02-15T09:00:00Z")
        complete_ticket(ctx, truck_id="TRK-3", gross_lbs=80000)
        s2 = generate_statement(ctx["site"]["id"], "2026-02-01", "2026-03-01")
        assert s2["royalty_due_usd"] == pytest.approx(10.40, abs=1e-6)
        set_clock("2026-02-20T09:00:00Z")
        s2 = validate_success(api.issue_royalty_statement(s2["id"], MANAGER))
        assert s2["due_on"] == "2026-03-22"
        s2 = validate_success(api.pay_royalty_statement(
            s2["id"], {"paid_on": "2026-04-01"}, FINANCE_2))
        assert s2["status"] == "PAID"
        # round_half_up(10.40 x 0.05, 2) == 0.52
        assert s2["penalty_usd"] == pytest.approx(0.52, abs=1e-6)
