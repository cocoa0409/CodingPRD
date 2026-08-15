"""Restricted funds: activation boundary, endowment spending allowance,
disbursement caps, stewardship reporting periods, freeze/unfreeze posture."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_endowed_fund_active, setup_executed_agreement, setup_active_pledge,
    create_payment, create_valuation_payload, create_disbursement_payload,
    create_report_payload, get_fund, get_agreement, set_clock,
    create_prospect, rate_prospect, assign_prospect, move_prospect,
    create_approved_proposal, create_executed_agreement,
    create_pledge_for, create_fundraiser, make_gift_officer_headers,
    create_proposal_payload,
    assert_iso_instant_equal,
)

DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


class TestFundActivationBoundary:
    """Queue A: boundary_precision_check / fund_activation_boundary_at_exact_minimum."""

    def _setup_pending_fund(self):
        return setup_executed_agreement(
            5000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )

    def test_balance_one_cent_below_minimum_stays_pending(self, api):
        """PRD §3.8: "A `PENDING_MINIMUM` fund activates automatically: as soon
        as a payment credit brings `balance_cents` to at least
        `minimum_activation_cents`, the fund becomes `ACTIVE`."

        Design: Difficulty/boundary_precision_check/fund_activation_boundary_at_exact_minimum
        """
        ctx = self._setup_pending_fund()
        create_payment(ctx["p"]["id"], 2499999, fund_id=ctx["fund"]["id"])
        fund = get_fund(ctx["fund"]["id"])
        assert fund["balance_cents"] == 2499999
        assert fund["status"] == "PENDING_MINIMUM"  # 2499999 < 2500000

    def test_balance_exactly_at_minimum_activates(self, api):
        """PRD §3.8: "A `PENDING_MINIMUM` fund activates automatically: as soon
        as a payment credit brings `balance_cents` to at least
        `minimum_activation_cents`, the fund becomes `ACTIVE`."

        Design: Difficulty/boundary_precision_check/fund_activation_boundary_at_exact_minimum
        """
        ctx = self._setup_pending_fund()
        create_payment(ctx["p"]["id"], 2499999, fund_id=ctx["fund"]["id"])
        create_payment(ctx["p"]["id"], 1, received_at="2026-08-11T00:00:00Z",
                       payment_method="CHECK", fund_id=ctx["fund"]["id"])
        fund = get_fund(ctx["fund"]["id"])
        assert fund["balance_cents"] == 2500000  # exactly MINIMUM_ACTIVATION_CENTS
        assert fund["status"] == "ACTIVE"  # >= boundary activates at equality


class TestSpendingAllowancePinnedOrder:
    """Queue A: combinatorial_formula / spending_allowance_pinned_evaluation_order."""

    def _setup_allowance_fund(self, api):
        """Endowed fund ACTIVE with balance 5000000 and four pre-FY valuations
        averaging 100000000 -> spendable 4500000 in FY2026-27."""
        ctx = setup_executed_agreement(
            5000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="CHAIR_CS",
        )
        fund_id = ctx["fund"]["id"]
        create_payment(ctx["p"]["id"], 5000000, received_at="2025-06-15T00:00:00Z",
                       fund_id=fund_id)
        for quarter_end, value in [
            ("2025-09-30T00:00:00Z", 100000000),
            ("2025-12-31T00:00:00Z", 110000000),
            ("2026-03-31T00:00:00Z", 90000000),
            ("2026-06-30T00:00:00Z", 100000000),
        ]:
            validate_success(api.create_valuation(
                fund_id, create_valuation_payload(quarter_end=quarter_end, value_cents=value), FIN,
            ))
        ctx["fund"] = get_fund(fund_id)
        return ctx

    def test_current_fy_allowance_uses_only_pre_fy_quarters(self, api):
        """PRD §3.8: "The **spending allowance** for the current fiscal year uses
        only market history that predates the year: the fund's
        `trailing_market_values` entries — each a `quarter_end` paired with a
        `value_cents`, unique per fund by quarter — are filtered to those whose
        `quarter_end` is strictly before the current fiscal year's start, and at
        most the 12 most recent such entries participate."
        PRD §3.8: "Otherwise `spendable_fy_cents` is four and a half percent
        (0.045) of the average `value_cents` across the qualifying quarters,
        rounded half up to a whole cent."
        PRD §3.8: "Disbursements and valuations recorded during the current
        fiscal year never change the current year's `spendable_fy_cents`; they
        only affect later years."

        Design: Difficulty/combinatorial_formula/spending_allowance_pinned_evaluation_order
        """
        ctx = self._setup_allowance_fund(api)
        fund_id = ctx["fund"]["id"]
        # Default clock 2026-08-01 sits in FY2026-27 (start 2026-07-01).
        fund = get_fund(fund_id)
        assert fund["spendable_fy_cents"] == 4500000  # round_half_up(0.045 * 100000000)

        # A current-FY disbursement reduces the remaining allowance, never spendable.
        validate_success(api.disburse_fund(
            fund_id, create_disbursement_payload(amount_cents=1000000, purpose_note="FY27 chair stipend"), FIN,
        ))
        fund = get_fund(fund_id)
        assert fund["spendable_fy_cents"] == 4500000
        assert fund["allowance_remaining_cents"] == 3500000

        # A valuation inside the current FY only feeds later years.
        validate_success(api.create_valuation(
            fund_id, create_valuation_payload(quarter_end="2026-09-30T00:00:00Z", value_cents=60000000), FIN,
        ))
        set_clock("2027-08-01T00:00:00Z")  # FY2027-28
        fund = get_fund(fund_id)
        # quarters before 2027-07-01: 100, 110, 90, 100, 60 (millions) -> avg 92000000
        assert fund["spendable_fy_cents"] == 4140000  # round_half_up(0.045 * 92000000)
        assert fund["allowance_remaining_cents"] == 4140000  # FY26-27 disbursement does not carry

    def test_allowance_remaining_tracks_current_fy_disbursements(self, api):
        """PRD §3.8: "The `allowance_remaining_cents` is `spendable_fy_cents`
        minus the disbursement amounts posted with a `created_at` inside the
        current fiscal year."
        PRD §3.8: "Disbursements and valuations recorded during the current
        fiscal year never change the current year's `spendable_fy_cents`; they
        only affect later years."

        Design: Difficulty/combinatorial_formula/spending_allowance_pinned_evaluation_order
        """
        ctx = self._setup_allowance_fund(api)
        fund_id = ctx["fund"]["id"]
        fund = get_fund(fund_id)
        assert fund["spendable_fy_cents"] == 4500000
        assert fund["allowance_remaining_cents"] == 4500000

        validate_success(api.disburse_fund(
            fund_id, create_disbursement_payload(amount_cents=1000000, purpose_note="stipend"), FIN,
        ))
        fund = get_fund(fund_id)
        assert fund["spendable_fy_cents"] == 4500000
        assert fund["allowance_remaining_cents"] == 3500000

    def test_allowance_requires_minimum_four_quarters(self, api):
        """PRD §3.8: "Fewer than 4 qualifying quarters means no spending
        authority at all: `spendable_fy_cents` is 0."
        PRD §3.8: "for an endowed fund the amount must not exceed the smaller of
        `allowance_remaining_cents` and `balance_cents` — for a current-use fund,
        `balance_cents` alone caps it — with any excess rejected as
        `ERR_SPENDING_ALLOWANCE_EXCEEDED`."

        Design: Corner/calculations/allowance_requires_minimum_four_quarters
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        fund_id = ctx["fund"]["id"]
        create_payment(ctx["p"]["id"], 3000000, received_at="2025-06-15T00:00:00Z",
                       fund_id=fund_id)
        for quarter_end in ["2025-09-30T00:00:00Z", "2025-12-31T00:00:00Z", "2026-03-31T00:00:00Z"]:
            validate_success(api.create_valuation(
                fund_id, create_valuation_payload(quarter_end=quarter_end, value_cents=100000000), FIN,
            ))

        fund = get_fund(fund_id)
        assert fund["spendable_fy_cents"] == 0  # 3 quarters < MIN_QUARTERS 4

        resp = api.disburse_fund(fund_id, create_disbursement_payload(amount_cents=1), FIN)
        validate_error(resp, ApiErrorId.ERR_SPENDING_ALLOWANCE_EXCEEDED)
        assert get_fund(fund_id)["balance_cents"] == 3000000


class TestDisbursementCaps:
    def test_disburse_over_allowance_rejected_exact_allowed(self, api):
        """PRD §3.8: "for an endowed fund the amount must not exceed the smaller
        of `allowance_remaining_cents` and `balance_cents` — for a current-use
        fund, `balance_cents` alone caps it — with any excess rejected as
        `ERR_SPENDING_ALLOWANCE_EXCEEDED`."
        PRD §3.8: "A posted disbursement decrements `balance_cents`, recomputes
        `allowance_remaining_cents`, drops the fund to `PENDING_MINIMUM` if the
        balance fell below the minimum, and advances the fund's `version`."

        Design: Corner/validations/disburse_over_allowance_rejected_exact_allowed
        """
        ctx = setup_executed_agreement(
            5000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        fund_id = ctx["fund"]["id"]
        create_payment(ctx["p"]["id"], 5000000, received_at="2025-06-15T00:00:00Z",
                       fund_id=fund_id)
        for quarter_end in ["2025-09-30T00:00:00Z", "2025-12-31T00:00:00Z",
                            "2026-03-31T00:00:00Z", "2026-06-30T00:00:00Z"]:
            validate_success(api.create_valuation(
                fund_id, create_valuation_payload(quarter_end=quarter_end, value_cents=100000000), FIN,
            ))

        # spendable = 4500000; one cent over the cap is rejected.
        resp = api.disburse_fund(fund_id, create_disbursement_payload(amount_cents=4500001, purpose_note="one over"), FIN)
        validate_error(resp, ApiErrorId.ERR_SPENDING_ALLOWANCE_EXCEEDED)

        # Exactly the cap succeeds and zeroes the remaining allowance.
        validate_success(api.disburse_fund(fund_id, create_disbursement_payload(amount_cents=4500000, purpose_note="exact cap"), FIN))
        fund = get_fund(fund_id)
        assert fund["balance_cents"] == 500000
        assert fund["allowance_remaining_cents"] == 0
        assert fund["status"] == "PENDING_MINIMUM"  # 500000 < 2500000 deactivates


class TestStewardshipReports:
    def test_stewardship_period_closed_interval_overlap(self, api):
        """PRD §3.8: "Report periods for the same fund must not overlap under
        **closed-interval** semantics — both endpoints count as inside the
        period, so a new period that merely shares a boundary date with an
        existing report already overlaps and is rejected with
        `ERR_REPORT_PERIOD_OVERLAP`."
        PRD §3.8: "the report's `due_date` is set automatically to `period_end`
        plus 90 days, and it starts as `DRAFT`."

        Design: Difficulty/resource_temporal_overlap/stewardship_period_closed_interval_overlap
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        fund_id = ctx["fund"]["id"]
        validate_success(api.create_report(
            fund_id, create_report_payload(
                period_start="2025-07-01T00:00:00Z", period_end="2026-06-30T00:00:00Z",
            ), DRO,
        ), expected_status=201)

        # Shares the closed endpoint date 2026-06-30: overlap.
        resp = api.create_report(
            fund_id, create_report_payload(
                period_start="2026-06-30T00:00:00Z", period_end="2027-06-29T00:00:00Z",
            ), DRO,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        # Adjacent non-touching period accepted.
        resp = api.create_report(
            fund_id, create_report_payload(
                period_start="2026-07-01T00:00:00Z", period_end="2027-06-30T00:00:00Z",
            ), DRO,
        )
        report = validate_success(resp, expected_status=201)
        assert report["status"] == "DRAFT"
        assert_iso_instant_equal(report["due_date"], "2027-09-28T00:00:00Z")  # period_end + 90 days

    def test_fully_contained_period_also_overlaps(self, api):
        """PRD §3.8: "Report periods for the same fund must not overlap under
        **closed-interval** semantics — both endpoints count as inside the
        period, so a new period that merely shares a boundary date with an
        existing report already overlaps and is rejected with
        `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/stewardship_period_closed_interval_overlap
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        fund_id = ctx["fund"]["id"]
        validate_success(api.create_report(
            fund_id, create_report_payload(
                period_start="2025-07-01T00:00:00Z", period_end="2026-06-30T00:00:00Z",
            ), DRO,
        ), expected_status=201)

        # A period strictly inside the existing closed interval also overlaps.
        resp = api.create_report(
            fund_id, create_report_payload(
                period_start="2025-10-01T00:00:00Z", period_end="2025-12-31T00:00:00Z",
            ), DRO,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        rows, meta = validate_paginated(api.list_fund_reports(fund_id, DRO))
        assert len(rows) == 1 and meta["total_count"] == 1

    def test_report_invalid_period_range_rejected(self, api):
        """PRD §3.8: "A `DonorRelationsOfficer` opens a report on a fund with a
        `period_start`, a `period_end` that must be later than the start, and an
        optional `narrative`."
        PRD §2.10: "The body is well-formed: required fields present, types
        correct, enum values within their declared sets, integer money fields
        positive, unknown fields rejected, and split structures well-formed;
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/report_invalid_period_range_rejected
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        resp = api.create_report(
            ctx["fund"]["id"],
            create_report_payload(period_start="2026-06-30T00:00:00Z",
                                  period_end="2026-06-30T00:00:00Z"),
            DRO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_report_terminal_lockdown(self, api):
        """PRD §3.8: "The officer then submits the report, moving it to
        `SUBMITTED` with `submitted_by` recorded; submission is allowed from
        `DRAFT` and, as the catch-up path, from `OVERDUE` — any other state fails
        with `ERR_REPORT_TRANSITION_INVALID`."
        PRD §3.8: "`DELIVERED` is the report's terminal state."

        Design: Corner/state_machines/report_terminal_lockdown
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        resp = api.create_report(
            ctx["fund"]["id"],
            create_report_payload(period_start="2026-01-01T00:00:00Z",
                                  period_end="2026-06-30T00:00:00Z"),
            DRO,
        )
        report = validate_success(resp, expected_status=201)
        validate_success(api.submit_report(report["id"], DRO))
        validate_success(api.deliver_report(report["id"], DRO))

        resp = api.submit_report(report["id"], DRO)
        validate_error(resp, ApiErrorId.ERR_REPORT_TRANSITION_INVALID)
        rows, _ = validate_paginated(api.list_fund_reports(ctx["fund"]["id"], DRO))
        assert rows[0]["status"] == "DELIVERED"


class TestFundStewardshipPosture:
    """Queue A: cross_entity_state_dependency / fund_payment_gated_by_stewardship_posture."""

    def _frozen_fund(self, api):
        ctx = setup_endowed_fund_active(balance_cents=3000000)
        resp = api.create_report(
            ctx["fund"]["id"],
            create_report_payload(period_start="2025-01-01T00:00:00Z",
                                  period_end="2025-06-30T00:00:00Z"),
            DRO,
        )
        ctx["report"] = validate_success(resp, expected_status=201)
        set_clock("2026-08-02T00:00:00Z")  # sweep: report OVERDUE -> fund frozen
        return ctx

    def test_payment_to_frozen_fund_rejected_then_allowed_after_delivery(self, api):
        """PRD §2.10: "9. **Stewardship gates on money movement.** A payment may
        not credit a `SPENDING_FROZEN` fund (`ERR_STEWARDSHIP_LAPSED`) and a
        disbursement may not leave a `SPENDING_FROZEN` fund
        (`ERR_FUND_SPENDING_FROZEN`)."
        PRD §3.8: "Recovery is just as automatic: when the overdue report reaches
        `DELIVERED` and no other report of the fund remains `OVERDUE`, the fund
        returns from `SPENDING_FROZEN` to `ACTIVE` and the agreement's
        `compliance_status` returns to `COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/fund_payment_gated_by_stewardship_posture
        """
        ctx = self._frozen_fund(api)
        resp = api.create_gift_payment(
            {
                "donor_prospect_id": ctx["p"]["id"], "fund_id": ctx["fund"]["id"],
                "amount_cents": 1000, "received_at": "2026-08-03T00:00:00Z",
                "payment_method": "CHECK",
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_STEWARDSHIP_LAPSED)

        validate_success(api.submit_report(ctx["report"]["id"], DRO))
        validate_success(api.deliver_report(ctx["report"]["id"], DRO))

        pay = create_payment(ctx["p"]["id"], 1000, received_at="2026-08-04T00:00:00Z",
                             payment_method="CHECK", fund_id=ctx["fund"]["id"])
        assert pay["id"]
        fund = get_fund(ctx["fund"]["id"])
        assert fund["status"] == "ACTIVE"
        assert fund["balance_cents"] == 3001000

    def test_disbursement_from_frozen_fund_rejected(self, api):
        """PRD §2.10: "9. **Stewardship gates on money movement.** A payment may
        not credit a `SPENDING_FROZEN` fund (`ERR_STEWARDSHIP_LAPSED`) and a
        disbursement may not leave a `SPENDING_FROZEN` fund
        (`ERR_FUND_SPENDING_FROZEN`)."

        Design: Difficulty/cross_entity_state_dependency/fund_payment_gated_by_stewardship_posture
        """
        ctx = self._frozen_fund(api)
        assert get_fund(ctx["fund"]["id"])["status"] == "SPENDING_FROZEN"
        resp = api.disburse_fund(
            ctx["fund"]["id"], create_disbursement_payload(amount_cents=100, purpose_note="frozen probe"), FIN,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_SPENDING_FROZEN)
        assert get_fund(ctx["fund"]["id"])["balance_cents"] == 3000000


class TestStewardshipSafetyBeatsReferential:
    """Queue A: priority_pair_validation_conflict / stewardship_safety_error_beats_referential_error."""

    def _setup(self, api):
        """Pledge A on an ENDOWED agreement whose fund A is ACTIVE-then-frozen
        via an overdue stewardship report; fund B (prospect B's ENDOWED
        agreement) stays healthy at PENDING_MINIMUM.

        The frozen fund is the pledge's OWN fund — the fund the payment would
        credit per PRD §3.7 ("The credited fund — the pledge's fund for a
        pledge-linked payment") — so the §2.10 priority-9 stewardship gate
        applies to it regardless of the mismatched payload fund reference.
        """
        f = create_fundraiser()

        # Prospect A with ENDOWED PLEDGE agreement + ACTIVE pledge; fund A
        # credited to ACTIVE, then frozen by the overdue-report sweep.
        pa = create_prospect(full_name="Donor A", contact_email="a@x.com")
        rate_prospect(pa["id"])
        assign_prospect(f["id"], pa["id"])
        move_prospect(pa["id"], f["id"], "CULTIVATION")
        prop_a = create_approved_proposal(pa["id"], f["id"], 3000000, proposal_type="PLEDGE",
                                          designation_purpose="Endowed A")
        agr_a = create_executed_agreement(prop_a, f["id"], restriction_type="ENDOWED",
                                          purpose_code="ENDOW_A")
        pl_a = create_pledge_for(agr_a["id"], f["id"], 3000000, installment_count=3,
                                 frequency="MONTHLY", first_due_date="2026-09-01T00:00:00Z")
        from test_helpers import find_fund_for_agreement
        fund_a = find_fund_for_agreement(agr_a["id"])
        # A seed donor activates fund A so the tests' own donor (pa) keeps a
        # clean payment ledger for the "payment was not recorded" assertion.
        seed = create_prospect(full_name="Seed Donor", contact_email="seed@x.com")
        create_payment(seed["id"], 3000000, received_at="2026-08-05T00:00:00Z",
                       fund_id=fund_a["id"])
        validate_success(api.create_report(
            fund_a["id"],
            create_report_payload(period_start="2025-01-01T00:00:00Z",
                                  period_end="2025-06-30T00:00:00Z"),
            DRO,
        ), expected_status=201)
        set_clock("2026-08-02T00:00:00Z")
        assert get_fund(fund_a["id"])["status"] == "SPENDING_FROZEN"

        # Prospect B with ENDOWED OUTRIGHT agreement; fund B healthy (never
        # credited, still PENDING_MINIMUM).
        pb = create_prospect(full_name="Donor B", contact_email="b@x.com")
        rate_prospect(pb["id"])
        assign_prospect(f["id"], pb["id"])
        move_prospect(pb["id"], f["id"], "CULTIVATION")
        prop_b = create_approved_proposal(pb["id"], f["id"], 3000000,
                                          designation_purpose="Endowed B")
        agr_b = create_executed_agreement(prop_b, f["id"], restriction_type="ENDOWED",
                                          purpose_code="ENDOW_B")
        fund_b = find_fund_for_agreement(agr_b["id"])
        assert get_fund(fund_b["id"])["status"] == "PENDING_MINIMUM"
        return pa, pl_a, fund_b

    def test_frozen_fund_error_precedes_pledge_fund_mismatch(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "9. **Stewardship gates on money movement.** A payment may not
        credit a `SPENDING_FROZEN` fund (`ERR_STEWARDSHIP_LAPSED`)."
        PRD §2.10: "10. **Cross-reference consistency.** A payment carrying both
        a pledge and a fund reference must name the fund the pledge actually pays
        into; otherwise `ERR_FUND_PLEDGE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/stewardship_safety_error_beats_referential_error
        """
        pa, pl_a, fund_b = self._setup(api)
        # Payment names pledge A (whose fund A is frozen) but fund B: both the
        # priority-9 stewardship gate and the priority-10 referential rule fail.
        resp = api.create_gift_payment(
            {
                "donor_prospect_id": pa["id"], "pledge_id": pl_a["id"],
                "fund_id": fund_b["id"], "amount_cents": 100,
                "received_at": "2026-08-03T00:00:00Z", "payment_method": "CHECK",
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_STEWARDSHIP_LAPSED)

    def test_mismatched_healthy_fund_pair_isolated_referential_failure(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "9. **Stewardship gates on money movement.** A payment may not
        credit a `SPENDING_FROZEN` fund (`ERR_STEWARDSHIP_LAPSED`)."
        PRD §2.10: "10. **Cross-reference consistency.** A payment carrying both
        a pledge and a fund reference must name the fund the pledge actually pays
        into; otherwise `ERR_FUND_PLEDGE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/stewardship_safety_error_beats_referential_error
        """
        pa, pl_a, fund_b = self._setup(api)
        # The pledge's own fund is frozen AND the payload fund reference does not
        # match it: the referential rule would also fire, but the ordered chain
        # surfaces the earlier stewardship error.
        resp = api.create_gift_payment(
            {
                "donor_prospect_id": pa["id"], "pledge_id": pl_a["id"],
                "fund_id": fund_b["id"], "amount_cents": 50,
                "received_at": "2026-08-06T00:00:00Z", "payment_method": "WIRE",
            },
            FIN,
        )
        err = validate_error(resp, ApiErrorId.ERR_STEWARDSHIP_LAPSED)
        assert err["error_id"] == "ERR_STEWARDSHIP_LAPSED"
        # The payment was not recorded.
        rows, meta = validate_paginated(
            api.list_gift_payments(FIN, params={"donor_prospect_id": pa["id"]}),
        )
        assert rows == [] and meta["total_count"] == 0

    def test_healthy_mismatched_fund_surfaces_referential_error(self, api):
        """PRD §3.7: "when both `pledge_id` and `fund_id` are present, the
        `fund_id` must equal the pledge's own `fund_id` — both being null is
        allowed — else `ERR_FUND_PLEDGE_MISMATCH`."

        Design: Corner/validations/fund_pledge_mismatch_rejected
        """
        f = create_fundraiser()
        # Prospect A: UNRESTRICTED pledge (fund_id null).
        pa = create_prospect(full_name="Donor A", contact_email="a@x.com")
        rate_prospect(pa["id"])
        assign_prospect(f["id"], pa["id"])
        move_prospect(pa["id"], f["id"], "CULTIVATION")
        prop_a = create_approved_proposal(pa["id"], f["id"], 1000000, proposal_type="PLEDGE",
                                          designation_purpose="Unrestricted pledge")
        agr_a = create_executed_agreement(prop_a, f["id"])
        pl_a = create_pledge_for(agr_a["id"], f["id"], 1000000, installment_count=1,
                                 frequency="ANNUAL", first_due_date="2026-12-01T00:00:00Z")

        # Prospect B: ENDOWED agreement; fund B PENDING_MINIMUM (healthy).
        pb = create_prospect(full_name="Donor B", contact_email="b@x.com")
        rate_prospect(pb["id"])
        assign_prospect(f["id"], pb["id"])
        move_prospect(pb["id"], f["id"], "CULTIVATION")
        prop_b = create_approved_proposal(pb["id"], f["id"], 3000000,
                                          designation_purpose="Endowed B")
        agr_b = create_executed_agreement(prop_b, f["id"], restriction_type="ENDOWED",
                                          purpose_code="ENDOW_B")
        from test_helpers import find_fund_for_agreement
        fund_b = find_fund_for_agreement(agr_b["id"])
        assert fund_b["status"] == "PENDING_MINIMUM"  # healthy: the safety gate cannot fire

        resp = api.create_gift_payment(
            {
                "donor_prospect_id": pa["id"], "pledge_id": pl_a["id"],
                "fund_id": fund_b["id"], "amount_cents": 1000,
                "received_at": "2026-08-10T00:00:00Z", "payment_method": "CHECK",
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_PLEDGE_MISMATCH)


class TestDisburseOnFrozenFund:
    def test_disburse_on_frozen_fund_rejected(self, api):
        """PRD §3.8: "the disbursement is refused when the fund is
        `SPENDING_FROZEN` (`ERR_FUND_SPENDING_FROZEN`) or `CLOSED`
        (`ERR_FUND_NOT_ACTIVE`)."
        PRD §3.8: "While frozen, the fund rejects incoming credits and outgoing
        disbursements per §2.10."

        Design: Corner/validations/disburse_on_frozen_fund_rejected
        """
        ctx = setup_endowed_fund_active(balance_cents=3000000)
        resp = api.create_report(
            ctx["fund"]["id"],
            create_report_payload(period_start="2025-01-01T00:00:00Z",
                                  period_end="2025-06-30T00:00:00Z"),
            DRO,
        )
        validate_success(resp, expected_status=201)
        set_clock("2026-08-02T00:00:00Z")  # sweep: report OVERDUE -> fund frozen

        assert get_fund(ctx["fund"]["id"])["status"] == "SPENDING_FROZEN"
        resp = api.disburse_fund(
            ctx["fund"]["id"],
            create_disbursement_payload(amount_cents=100, purpose_note="frozen probe"),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_SPENDING_FROZEN)
        assert get_fund(ctx["fund"]["id"])["balance_cents"] == 3000000  # untouched


class TestClosedFund:
    def test_payment_to_closed_fund_rejected(self, api):
        """PRD §3.7: "a payment that would credit a `SPENDING_FROZEN` fund is
        refused with `ERR_STEWARDSHIP_LAPSED`, and one referencing a `CLOSED`
        fund with `ERR_FUND_NOT_ACTIVE`."
        PRD §3.8: "`CLOSED` is the fund's, reached only through rescission of its
        establishing agreement with a zero balance."

        Design: Corner/validations/payment_to_closed_fund_rejected
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        validate_success(api.rescind_agreement(ctx["agr"]["id"], VP))
        assert get_fund(ctx["fund"]["id"])["status"] == "CLOSED"

        resp = api.create_gift_payment(
            {
                "donor_prospect_id": ctx["p"]["id"], "fund_id": ctx["fund"]["id"],
                "amount_cents": 100, "received_at": "2026-08-10T00:00:00Z",
                "payment_method": "CHECK",
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_NOT_ACTIVE)


class TestValuationUniqueness:
    def test_duplicate_quarter_valuation_rejected(self, api):
        """PRD §3.8: "A `FinanceSteward` maintains the market history by
        appending valuations with a `quarter_end` and a `value_cents`; a quarter
        already recorded on the fund rejects the append with
        `ERR_DUPLICATE_QUARTER_VALUATION`."

        Design: Corner/validations/duplicate_quarter_valuation_rejected
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        fund_id = ctx["fund"]["id"]
        validate_success(api.create_valuation(
            fund_id, create_valuation_payload(quarter_end="2025-09-30T00:00:00Z", value_cents=100000000), FIN,
        ))
        resp = api.create_valuation(
            fund_id, create_valuation_payload(quarter_end="2025-09-30T00:00:00Z", value_cents=105000000), FIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUARTER_VALUATION)
        assert len(get_fund(fund_id)["trailing_market_values"]) == 1
