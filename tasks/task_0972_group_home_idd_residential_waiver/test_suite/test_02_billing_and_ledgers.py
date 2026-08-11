"""Billing claims: recoupment netting, void compensation, correction cycle.

PRD 3.10.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_and_verify_visit,
    create_authorization_payload,
    create_evv_visit_payload,
    get_success_data,
    make_billing_headers,
    set_clock,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_claim_for_individual,
    setup_enrolled_individual,
    setup_submitted_claim,
    submit_claim_as,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


def _pay_full(claim_id, total_cents, payer="bill-2"):
    return get_success_data(api_client.post_claim_payment(
        claim_id, {"paid_amount_cents": total_cents}, make_billing_headers(payer),
    ))


class TestRecoupmentNettingOrderPinned:
    """Recoupment netting pinned evaluation order (PRD 3.10)."""

    def _setup_recoupment_scenario(self, api):
        """Claim1 (30000 cents) paid in full then voided -> balance 30000.
        Then claim2 (30000 cents) submitted, ready for payment."""
        ctx = setup_billable_pipeline(authorized_units=60, rate_cents=1500)
        # Two verified 150-min visits on 2026-06-02 (10 units each).
        create_and_verify_visit(ctx, "2026-06-02T08:00:00Z", "2026-06-02T10:30:00Z")
        create_and_verify_visit(ctx, "2026-06-02T12:00:00Z", "2026-06-02T14:30:00Z")
        claim1 = setup_submitted_claim(ctx, "2026-06-02", "2026-06-02", submitter="bill-1")
        _pay_full(claim1["id"], 30000, payer="bill-2")
        get_success_data(api_client.void_claim(claim1["id"], make_billing_headers("bill-1")))
        # Two more verified visits on 2026-06-03.
        create_and_verify_visit(ctx, "2026-06-03T08:00:00Z", "2026-06-03T10:30:00Z", service_date="2026-06-03")
        create_and_verify_visit(ctx, "2026-06-03T12:00:00Z", "2026-06-03T14:30:00Z", service_date="2026-06-03")
        claim2 = setup_submitted_claim(ctx, "2026-06-03", "2026-06-03", submitter="bill-1")
        return ctx, claim2

    def test_recoup_computed_on_gross_against_pre_payment_balance(self, api):
        """PRD 3.10: "the recouped portion is the smaller of two values — the
        floor of ten percent of the gross, and the agency's
        `recoupment_balance_cents` measured before this payment; the
        `posted_net_cents` is the gross minus the recouped portion".

        Design: Difficulty/combinatorial_formula/recoupment_netting_order_pinned
        """
        ctx, claim2 = self._setup_recoupment_scenario(api)
        paid = _pay_full(claim2["id"], 30000, payer="bill-2")
        # recoup = min(floor(30000*0.10), 30000) = 3000; net = 27000.
        assert paid["posted_net_cents"] == 27000, (
            f"net 30000 - 3000 = 27000, got {paid['posted_net_cents']}"
        )
        assert paid["status"] == "PAID"

    def test_agency_ledgers_after_recoupment(self, api):
        """PRD 3.10: "the agency's `cash_collected_cents` is incremented by
        `posted_net_cents`; and the agency's `recoupment_balance_cents` becomes
        its pre-payment balance minus the recouped portion."

        Design: Difficulty/combinatorial_formula/recoupment_netting_order_pinned
        """
        ctx, claim2 = self._setup_recoupment_scenario(api)
        _pay_full(claim2["id"], 30000, payer="bill-2")
        agency = get_success_data(api_client.get_agency(ctx["agency"]["id"], ANY))
        # Claim1's 30000 was reversed by void; claim2 nets 27000.
        assert agency["cash_collected_cents"] == 27000
        # 30000 balance - 3000 recouped.
        assert agency["recoupment_balance_cents"] == 27000


class TestPayThenVoidRestoresCashLedger:
    """Void compensation conserves agency cash (PRD 3.10)."""

    def _setup_paid_claim(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        create_and_verify_visit(ctx, "2026-06-02T08:00:00Z", "2026-06-02T10:30:00Z")
        create_and_verify_visit(ctx, "2026-06-02T12:00:00Z", "2026-06-02T14:30:00Z")
        claim = setup_submitted_claim(ctx, submitter="bill-1")
        assert claim["total_amount_cents"] == 30000
        return ctx, claim

    def test_full_payment_posts_net_equal_to_gross_when_no_balance(self, api):
        """PRD 3.10: "the recouped portion is the smaller of two values — the
        floor of ten percent of the gross, and the agency's
        `recoupment_balance_cents` measured before this payment". With a zero
        pre-payment balance the recoup is zero.

        Design: Difficulty/compensating_invariant/pay_then_void_restores_cash_ledger
        """
        _ctx, claim = self._setup_paid_claim(api)
        paid = _pay_full(claim["id"], 30000, payer="bill-2")
        assert paid["posted_net_cents"] == 30000
        assert paid["status"] == "PAID"

    def test_void_restores_cash_and_tracks_recoupment_balance(self, api):
        """PRD 3.10: "On void: the agency's `cash_collected_cents` is decremented
        by the claim's `posted_net_cents`, and the agency's
        `recoupment_balance_cents` is incremented by the same amount".

        Design: Difficulty/compensating_invariant/pay_then_void_restores_cash_ledger
        """
        ctx, claim = self._setup_paid_claim(api)
        _pay_full(claim["id"], 30000, payer="bill-2")
        voided = get_success_data(api_client.void_claim(claim["id"], make_billing_headers("bill-1")))
        assert voided["status"] == "VOIDED"
        agency = get_success_data(api_client.get_agency(ctx["agency"]["id"], ANY))
        assert agency["cash_collected_cents"] == 0, (
            f"cash conserved at pre-payment value, got {agency['cash_collected_cents']}"
        )
        assert agency["recoupment_balance_cents"] == 30000


class TestVerifyThenVoidRestoresUnitPool:
    """Void releases waterfall allocations LIFO, restoring units (PRD 3.10)."""

    def _setup_two_authorization_paid_claim(self, api):
        # The pipeline's own authorization uses RES_HAB so the DAY_PROG
        # waterfall below involves exactly A1 and A2.
        ctx = setup_billable_pipeline(service_code="RES_HAB")
        cm_h, q_h = ctx["cm_headers"], ctx["q_headers"]
        ind, isp = ctx["individual"], ctx["isp"]
        # A1: span ends 2026-06-30; A2: span starts 2026-06-01 (successor).
        a1 = get_success_data(api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], authorized_units=24, rate_cents=1500,
                span_start="2026-01-01", span_end="2026-06-30",
            ), cm_h,
        ))
        a1 = get_success_data(api_client.approve_authorization(a1["id"], q_h))
        a2 = get_success_data(api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], authorized_units=24, rate_cents=1500,
                span_start="2026-06-01", span_end="2026-12-31",
            ), cm_h,
        ))
        a2 = get_success_data(api_client.approve_authorization(a2["id"], q_h))
        # PRD 3.8 gates EVV creation on the authorization being ACTIVE, so all
        # four visits are created up front, before any verification consumes
        # A1's units and drives it to EXHAUSTED.
        visits = []
        for ci, co in [("06:00", "08:00"), ("09:00", "11:00"), ("12:00", "14:00"),
                       ("15:00", "16:00")]:
            visits.append(get_success_data(api_client.create_evv_visit(
                create_evv_visit_payload(
                    ind["id"], a1["id"],
                    service_date="2026-06-15",
                    check_in_at=f"2026-06-15T{ci}:00Z",
                    check_out_at=f"2026-06-15T{co}:00Z",
                ), ctx["d1_headers"],
            )))
        # Verify the three 120-min visits (8 units each) -> A1: 24, EXHAUSTED.
        for v in visits[:3]:
            get_success_data(api_client.verify_evv_visit(v["id"], q_h))
        # Verify the 60-min visit (4 units): A1 has nothing left -> spills to A2.
        visits[3] = get_success_data(api_client.verify_evv_visit(visits[3]["id"], q_h))
        claim = get_success_data(api_client.create_claim(
            {"individual_id": ind["id"],
             "service_period_start": "2026-06-15",
             "service_period_end": "2026-06-15"},
            TEST_USERS["billing_headers"],
        ))
        submit_claim_as(claim["id"], "bill-1")
        _pay_full(claim["id"], claim["total_amount_cents"], payer="bill-2")
        return ctx, a1, a2, visits, claim

    def test_waterfall_spill_and_claim_aggregation_before_void(self, api):
        """PRD 3.10: "each swept visit contributes its `allocated_units_entries`
        to the line of the entry's `authorization_id`, so a visit whose units
        spilled onto a successor authorization lands on the successor's line."

        Design: Difficulty/compensating_invariant/verify_then_void_restores_unit_pool
        """
        _ctx, a1, _a2, visits, claim = self._setup_two_authorization_paid_claim(api)
        # 3 visits x 8 units onto A1 (= 24, EXHAUSTED) + 4 units spill onto A2.
        assert claim["total_units"] == 28
        assert claim["total_amount_cents"] == 42000  # 24*1500 + 4*1500
        a1_after = get_success_data(api_client.get_authorization(a1["id"], ANY))
        assert a1_after["status"] == "EXHAUSTED"
        assert a1_after["consumed_units"] == 24
        # The spilling visit carries the waterfall allocation log.
        assert any(
            e["authorization_id"] != a1["id"] for e in visits[-1]["allocated_units_entries"]
        ), "v4 allocation entries must show the spill to the successor"

    def test_void_releases_units_lifo_and_recovers_exhausted(self, api):
        """PRD 3.10: "each visit's `allocated_units_entries` is released in
        reverse order (last-in-first-out), decrementing each referenced
        authorization's `consumed_units` by the entry's `units`. An
        authorization whose `consumed_units` thereby drops below its
        `authorized_units` and that was in `EXHAUSTED` status transitions back
        to `ACTIVE`."

        Design: Difficulty/compensating_invariant/verify_then_void_restores_unit_pool
        """
        _ctx, a1, a2, _visits, claim = self._setup_two_authorization_paid_claim(api)
        get_success_data(api_client.void_claim(claim["id"], make_billing_headers("bill-1")))
        a1_after = get_success_data(api_client.get_authorization(a1["id"], ANY))
        a2_after = get_success_data(api_client.get_authorization(a2["id"], ANY))
        assert a1_after["consumed_units"] == 0
        assert a1_after["status"] == "ACTIVE"
        assert a2_after["consumed_units"] == 0
        assert a2_after["status"] == "ACTIVE"
        # All visits returned to UNBILLED.
        visits = get_success_data(api_client.list_evv_visits(
            ANY, params={"authorization_id": a1["id"], "billing_status": "UNBILLED"},
        ))
        assert isinstance(visits, list)


class TestClaimCorrectThenResubmit:
    """Deny -> correct -> resubmit cycle (PRD 3.10)."""

    def _setup_denied_claim(self, api):
        ctx = setup_billable_pipeline(authorized_units=60, rate_cents=1500)
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
        claim = setup_submitted_claim(ctx, submitter="bill-1")
        denied = get_success_data(api_client.deny_claim(
            claim["id"], {"denial_reason": "Documentation mismatch on units"},
            make_billing_headers("bill-2"),
        ))
        return ctx, denied

    def test_correction_recomputes_lines_and_totals(self, api):
        """PRD 3.10: "On success the claim's `lines` are recomputed — `units`
        from `lines_override`, `amount_cents` equal to `units` multiplied by
        `rate_cents` — and the totals are recomputed".

        Design: Corner/state_machines/claim_correct_then_resubmit_cycle
        """
        ctx, denied = self._setup_denied_claim(api)
        assert denied["status"] == "DENIED"
        corrected = get_success_data(api_client.correct_claim(
            denied["id"],
            {"lines_override": [{"authorization_id": ctx["auth"]["id"], "units": 8}]},
            make_billing_headers("bill-1"),
        ))
        assert corrected["status"] == "CORRECTED"
        assert corrected["total_units"] == 8
        assert corrected["total_amount_cents"] == 12000

    def test_corrected_claim_resubmits_to_submitted(self, api):
        """PRD 3.10: "the corrected claim is then resubmitted through the normal
        submit path." Submit moves a claim from `DRAFT` or `CORRECTED` to
        `SUBMITTED`.

        Design: Corner/state_machines/claim_correct_then_resubmit_cycle
        """
        ctx, denied = self._setup_denied_claim(api)
        get_success_data(api_client.correct_claim(
            denied["id"],
            {"lines_override": [{"authorization_id": ctx["auth"]["id"], "units": 8}]},
            make_billing_headers("bill-1"),
        ))
        resubmitted = submit_claim_as(denied["id"], "bill-1")
        assert resubmitted["status"] == "SUBMITTED"


class TestOverpaymentBoundary:
    """Overpayment rejection vs exact full payment (PRD 3.10)."""

    def _setup_submitted_6000_claim(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
        claim = setup_submitted_claim(ctx, submitter="bill-1")
        assert claim["total_amount_cents"] == 6000
        return ctx, claim

    def test_overpayment_by_one_cent_rejected(self, api):
        """PRD 3.10: "The `paid_amount_cents` must be no greater than the claim's
        `total_amount_cents` (otherwise `ERR_OVERPAYMENT`, HTTP 400)."

        Design: Corner/validations/overpayment_rejected_exact_total_accepted
        """
        _ctx, claim = self._setup_submitted_6000_claim(api)
        resp = api_client.post_claim_payment(
            claim["id"], {"paid_amount_cents": 6001}, make_billing_headers("bill-2"),
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

    def test_exact_total_payment_accepted_as_paid(self, api):
        """PRD 3.10: "When `paid_amount_cents` equals `total_amount_cents`, the
        claim transitions to `PAID`".

        Design: Corner/validations/overpayment_rejected_exact_total_accepted
        """
        _ctx, claim = self._setup_submitted_6000_claim(api)
        # Overpayment attempt first leaves the claim SUBMITTED.
        validate_error(api_client.post_claim_payment(
            claim["id"], {"paid_amount_cents": 6001}, make_billing_headers("bill-2"),
        ), ApiErrorId.ERR_OVERPAYMENT)
        current = get_success_data(api_client.get_claim(claim["id"], ANY))
        assert current["status"] == "SUBMITTED"
        paid = _pay_full(claim["id"], 6000, payer="bill-2")
        assert paid["status"] == "PAID"
        assert paid["posted_net_cents"] == 6000


class TestClaimGenerationGuards:
    """Claim period validity and sweep emptiness (PRD 3.10)."""

    def _setup_enrolled_no_visits(self, api):
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        return ind

    def test_inverted_period_rejected_first(self, api):
        """PRD 3.10: "The `service_period_end` must be on or after
        `service_period_start` (otherwise `ERR_CLAIM_PERIOD_INVALID`, HTTP 400),
        and this check runs before the sweep-emptiness check."

        Design: Corner/validations/claim_generation_requires_billable_visits
        """
        ind = self._setup_enrolled_no_visits(api)
        resp = api_client.create_claim(
            {"individual_id": ind["id"],
             "service_period_start": "2026-06-10",
             "service_period_end": "2026-06-01"},
            TEST_USERS["billing_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_PERIOD_INVALID)

    def test_valid_empty_period_rejected_no_claim_persisted(self, api):
        """PRD 3.10: "If the sweep set is empty, generation is rejected with
        `ERR_NO_BILLABLE_VISITS` (HTTP 422) and no claim is created."

        Design: Corner/validations/claim_generation_requires_billable_visits
        """
        ind = self._setup_enrolled_no_visits(api)
        resp = api_client.create_claim(
            {"individual_id": ind["id"],
             "service_period_start": "2026-06-01",
             "service_period_end": "2026-06-10"},
            TEST_USERS["billing_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_VISITS)
        _data, meta = validate_paginated(
            api_client.list_claims(ANY, params={"individual_id": ind["id"]})
        )
        assert meta["total_count"] == 0


class TestClaimSweepInputSet:
    """Claim sweep includes only VERIFIED + UNBILLED visits (PRD 3.10)."""

    def _setup_mixed_visits(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        v1 = create_and_verify_visit(ctx, "2026-06-02T08:00:00Z", "2026-06-02T09:00:00Z")
        # v2 stays PENDING.
        v2 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T10:00:00Z", check_out_at="2026-06-02T11:00:00Z",
            ), ctx["d1_headers"],
        ))
        v3 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T12:00:00Z", check_out_at="2026-06-02T13:00:00Z",
            ), ctx["d1_headers"],
        ))
        get_success_data(api_client.reject_evv_visit(
            v3["id"], {"reason": "Could not confirm service delivery"}, ctx["q_headers"],
        ))
        return ctx, v1, v2, v3

    def test_sweep_totals_include_only_verified_visits(self, api):
        """PRD 3.10: "The sweep selects the individual's EVV visits whose
        `verification_status` is `VERIFIED`, whose `billing_status` is
        `UNBILLED`, and whose `service_date` lies inside the closed claim period".

        Design: Corner/calculations/claim_sweep_excludes_pending_and_rejected_visits
        """
        ctx, _v1, _v2, _v3 = self._setup_mixed_visits(api)
        claim = setup_claim_for_individual(ctx)
        assert claim["total_units"] == 4
        assert claim["total_amount_cents"] == 6000

    def test_unswept_visits_remain_unbilled(self, api):
        """PRD 3.10: "every swept visit's `billing_status` flips from `UNBILLED`
        to `BILLED` with `billed_claim_id` set to the new claim's `id`" — visits
        outside the sweep set are untouched.

        Design: Corner/calculations/claim_sweep_excludes_pending_and_rejected_visits
        """
        ctx, _v1, _v2, _v3 = self._setup_mixed_visits(api)
        setup_claim_for_individual(ctx)
        billed = get_success_data(api_client.list_evv_visits(
            ANY, params={"authorization_id": ctx["auth"]["id"], "billing_status": "BILLED"},
        ))
        unbilled = get_success_data(api_client.list_evv_visits(
            ANY, params={"authorization_id": ctx["auth"]["id"], "billing_status": "UNBILLED"},
        ))
        assert len(billed) == 1
        assert len(unbilled) == 2
