"""Payout batch lifecycle: line generation bases, period overlap, segregation
of duties, release cascade, and the reject revision loop."""
from test_helpers import (
    ApiErrorId,
    approve_batch,
    assert_payout_batch,
    assert_payout_line,
    confirm_record,
    create_batch,
    create_deal_for,
    create_package_for,
    create_partner,
    create_publisher,
    create_payout_batch_payload,
    create_report,
    fill_auction,
    get_publisher,
    list_lines,
    make_exchange_admin_headers,
    make_finance_officer_headers,
    release_batch,
    resolve_report,
    setup_active_deal,
    setup_submitted_batch_with_line,
    submit_and_approve_deal,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _sl_g_scenario(api):
    """Two publishers with byte-identical auction history (two canonical fills
    apiece, net 850,000 per record): P_SL is SEQUENTIAL_LIABILITY with only its
    first record billing-confirmed; P_G is GUARANTEED with no confirmations.
    Returns the submitted batch covering both."""
    pub_sl = create_publisher("Pub SL", "sl.com", "SEQUENTIAL_LIABILITY")
    pub_g = create_publisher("Pub G", "g.com", "GUARANTEED")
    partner = create_partner()
    pkg_sl = create_package_for(pub_sl["id"])
    pkg_g = create_package_for(pub_g["id"])
    submit_and_approve_deal(
        create_deal_for(pub_sl["id"], pkg_sl["id"], partner["id"])["id"],
        pub_sl["id"])
    submit_and_approve_deal(
        create_deal_for(pub_g["id"], pkg_g["id"], partner["id"])["id"],
        pub_g["id"])
    rec_sl_1 = fill_auction(pub_sl["id"])
    fill_auction(pub_sl["id"])
    fill_auction(pub_g["id"])
    fill_auction(pub_g["id"])
    confirm_record(rec_sl_1["id"])
    batch = create_batch()
    submit_batch(batch["id"])
    return batch


class TestPayoutBasisVariants:
    def test_sequential_liability_line_pays_confirmed_only(self, api):
        """PRD §3.8: "under `SEQUENTIAL_LIABILITY`, `payable_micros` is
        `confirmed_micros` plus `adjustment_micros` — the exchange pays only
        what DSPs have confirmed, plus any make-goods"
        PRD §3.8: "Every line starts `PENDING`, and lines for `GUARANTEED`
        publishers promote immediately to `ELIGIBLE` at generation."

        Design: Difficulty/dual_variant_calc/sequential_liability_vs_guaranteed_payout_basis
        """
        batch = _sl_g_scenario(api)
        pending = list_lines(batch["id"], status="PENDING")
        assert len(pending) == 1
        line = pending[0]
        assert_payout_line(line)
        assert line["payable_micros"] == 850000, (
            "Only the confirmed record's net is payable")
        assert line["gross_micros"] == 1700000
        assert line["confirmed_micros"] == 850000
        assert line["unconfirmed_micros"] == 850000
        assert line["status"] == "PENDING", (
            "A SEQUENTIAL_LIABILITY line does not promote at generation")

    def test_guaranteed_line_pays_full_ssp_net(self, api):
        """PRD §3.8: "under `GUARANTEED`, `payable_micros` is `gross_micros`
        plus `adjustment_micros` — the exchange stands behind the full recorded
        amount."
        PRD §3.8: "Every line starts `PENDING`, and lines for `GUARANTEED`
        publishers promote immediately to `ELIGIBLE` at generation."

        Design: Difficulty/dual_variant_calc/sequential_liability_vs_guaranteed_payout_basis
        """
        batch = _sl_g_scenario(api)
        eligible = list_lines(batch["id"], status="ELIGIBLE")
        assert len(eligible) == 1
        line = eligible[0]
        assert_payout_line(line)
        assert line["payable_micros"] == 1700000, (
            "GUARANTEED pays the full SSP net regardless of confirmation")
        assert line["gross_micros"] == 1700000
        assert line["status"] == "ELIGIBLE"
        pending = list_lines(batch["id"], status="PENDING")
        assert line["payable_micros"] - pending[0]["payable_micros"] == 850000, (
            "Identical gross history; the 850,000 gap is driven only by "
            "payment_terms")


class TestReleaseCascade:
    def test_release_pays_eligible_line_and_settles_batch(self, api):
        """PRD §3.8: "every `ELIGIBLE` line is paid: it transitions to `PAID`,
        snapshots `payable_micros` into `paid_micros`, adds that amount to the
        publisher's `paid_out_micros`, and recomputes the publisher's
        `accrued_open_micros`."
        PRD §3.8: "The batch itself moves to `RELEASED` and then immediately to
        the terminal `SETTLED`"

        Design: Difficulty/transitive_cascade/batch_release_cascades_line_payment_then_publisher_accrual
        """
        sc = setup_submitted_batch_with_line(payment_terms="GUARANTEED")
        approve_batch(sc["batch"]["id"])
        settled = release_batch(sc["batch"]["id"])
        assert_payout_batch(settled)
        assert settled["status"] == "SETTLED", (
            "APPROVED -> RELEASED -> SETTLED within the release call")

        paid = list_lines(sc["batch"]["id"], status="PAID")
        assert len(paid) == 1
        line = paid[0]
        assert line["status"] == "PAID"
        assert line["paid_micros"] == 850000, (
            "paid_micros snapshots payable_micros at the moment of payment")

    def test_release_cascade_reaches_publisher_accrual(self, api):
        """PRD §2.10: "for each publisher: `lifetime_net_micros` plus the sum of
        open make-good adjustments always equals `paid_out_micros` plus
        `written_off_micros` plus `accrued_open_micros`; nothing may be created
        or destroyed silently, only moved between those buckets."

        Design: Difficulty/transitive_cascade/batch_release_cascades_line_payment_then_publisher_accrual
        """
        sc = setup_submitted_batch_with_line(payment_terms="GUARANTEED")
        approve_batch(sc["batch"]["id"])
        release_batch(sc["batch"]["id"])
        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["lifetime_net_micros"] == 850000
        assert publisher["paid_out_micros"] == 850000
        assert publisher["written_off_micros"] == 0
        assert publisher["accrued_open_micros"] == 0, (
            "850,000 lifetime net - 850,000 paid: the cascade's third hop")


class TestAccrualIdentity:
    def _makegood_scenario(self, api):
        """SL publisher, two fills (net 850,000 each, first confirmed), a
        DISPUTED auto-flagged report resolved MAKE_GOOD 100,000, and a
        submitted+approved batch over the default window."""
        sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
        rec1 = fill_auction(sc["pub"]["id"])
        fill_auction(sc["pub"]["id"])
        confirm_record(rec1["id"])
        report = create_report(sc["deal"]["id"], "2026-08-01", "2026-08-15")
        assert report["status"] == "DISPUTED", (
            "ssp 2000 vs dsp 1000 auto-flags the report")
        resolved = resolve_report(report["id"], "MAKE_GOOD",
                                  adjustment_micros=100000)
        assert resolved["status"] == "RESOLVED"
        batch = create_batch()
        submit_batch(batch["id"])
        approve_batch(batch["id"])
        return sc, batch

    def test_release_pays_confirmed_plus_adjustment(self, api):
        """PRD §3.8: "under `SEQUENTIAL_LIABILITY`, `payable_micros` is
        `confirmed_micros` plus `adjustment_micros`"
        PRD §3.8: "First, every line still `PENDING` has its payable basis
        re-evaluated at that moment: sequential-liability lines whose DSP
        confirmations have since arrived, lifting `payable_micros` above zero,
        promote to `ELIGIBLE`"

        Design: Difficulty/compensating_invariant/publisher_accrual_identity_across_payment_and_makegood
        """
        sc, batch = self._makegood_scenario(api)
        release_batch(batch["id"])
        lines = list_lines(batch["id"])
        assert len(lines) == 1
        line = lines[0]
        assert line["gross_micros"] == 1700000
        assert line["confirmed_micros"] == 850000
        assert line["adjustment_micros"] == 100000, (
            "The overlapping RESOLVED make-good report feeds the line")
        assert line["status"] == "PAID"
        assert line["paid_micros"] == 950000, "850,000 confirmed + 100,000 make-good"

    def test_publisher_accrual_identity_holds_across_payment(self, api):
        """PRD §2.10: "for each publisher: `lifetime_net_micros` plus the sum of
        open make-good adjustments always equals `paid_out_micros` plus
        `written_off_micros` plus `accrued_open_micros`"
        PRD §3.7: "A make-good's `adjustment_micros` is immediately added to the
        publisher's `accrued_open_micros`"

        Design: Difficulty/compensating_invariant/publisher_accrual_identity_across_payment_and_makegood
        """
        sc, batch = self._makegood_scenario(api)
        release_batch(batch["id"])
        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["lifetime_net_micros"] == 1700000
        assert publisher["paid_out_micros"] == 950000
        assert publisher["written_off_micros"] == 0
        assert publisher["accrued_open_micros"] == 850000, (
            "1,700,000 + 100,000 - 950,000 - 0 == 850,000: no drift through the "
            "report -> batch -> release chain")


class TestPayoutPeriodOverlap:
    def test_overlapping_submit_rejected_boundary_allowed(self, api):
        """PRD §3.8: "Submission first checks period exclusivity: no other batch
        whose period overlaps this one as a half-open interval — one's
        `period_start` falling before the other's `period_end` while the other's
        `period_start` falls before the one's `period_end` — may exist outside
        `DRAFT`, and a conflict is rejected with `ERR_PAYOUT_PERIOD_OVERLAP`;
        batches sharing an exact boundary date do not conflict"
        PRD §3.8: "even a batch that generated zero lines settles."

        Design: Difficulty/resource_temporal_overlap/payout_period_half_open_overlap
        """
        b1 = create_batch("2026-08-01", "2026-09-01")
        submitted = submit_batch(b1["id"])
        assert submitted["status"] == "PENDING_APPROVAL"
        assert submitted["line_count"] == 0, "Empty batches are legal"

        b2 = create_batch("2026-08-15", "2026-10-01")
        resp = api.submit_payout_batch(b2["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_PERIOD_OVERLAP)

        b3 = create_batch("2026-09-01", "2026-10-01")
        submitted3 = submit_batch(b3["id"])
        assert submitted3["status"] == "PENDING_APPROVAL", (
            "B3.start == B1.end: a shared boundary is not an overlap")

    def test_failed_submit_leaves_draft_which_never_blocks(self, api):
        """PRD §3.8: "rejected batches never block anyone because they return to
        `DRAFT` with their lines deleted."
        PRD §3.8: "may exist outside `DRAFT`"

        Design: Difficulty/resource_temporal_overlap/payout_period_half_open_overlap
        """
        b1 = create_batch("2026-08-01", "2026-09-01")
        submit_batch(b1["id"])
        b2 = create_batch("2026-08-15", "2026-10-01")
        validate_error(api.submit_payout_batch(b2["id"], FINANCE),
                       ApiErrorId.ERR_PAYOUT_PERIOD_OVERLAP)
        state = validate_success(api.get_payout_batch(b2["id"], ADMIN))
        assert state["status"] == "DRAFT", "A failed submit leaves the batch in DRAFT"

        # B2 (DRAFT) must not block a later batch that overlaps only B2's span.
        b4 = create_batch("2026-09-15", "2026-10-15")
        submitted4 = submit_batch(b4["id"])
        assert submitted4["status"] == "PENDING_APPROVAL"


class TestBatchRejectLoop:
    def test_batch_reject_deletes_lines_and_unblocks_period(self, api):
        """PRD §3.8: "Rejection returns the batch to `DRAFT`, deletes every
        generated line, and resets all three aggregates to zero, forming a
        revision loop with submission."

        Design: Corner/state_machines/batch_reject_deletes_lines_and_unblocks_period
        """
        sc = setup_submitted_batch_with_line(payment_terms="GUARANTEED")
        batch = sc["batch"]
        assert batch["line_count"] == 1
        assert batch["total_payable_micros"] == 850000

        rejected = validate_success(api.reject_payout_batch(batch["id"], ADMIN))
        assert rejected["status"] == "DRAFT"
        assert rejected["line_count"] == 0
        assert rejected["total_gross_micros"] == 0
        assert rejected["total_payable_micros"] == 0

        lines, meta = validate_paginated(api.list_batch_lines(batch["id"], FINANCE))
        assert meta["total_count"] == 0, "Generated lines are deleted on reject"

        resubmitted = submit_batch(batch["id"])
        assert resubmitted["status"] == "PENDING_APPROVAL"
        assert resubmitted["line_count"] == 1, (
            "The revision loop regenerates the line on re-submit")


class TestApproveValidationOrder:
    def test_approve_draft_batch_reports_state_gate_not_segregation(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the request fails at the first check that does not pass — later
        checks never mask earlier ones."
        PRD §3.8: "An `ExchangeAdmin` approves a batch in `PENDING_APPROVAL` —
        any other state draws `ERR_BATCH_NOT_PENDING_APPROVAL`"
        (Pipeline stage 6, state, fires before stage 15, segregation of duties,
        so the creator-as-approver detail is never reached on a DRAFT batch.)

        Design: Difficulty/priority_pair_validation_conflict/batch_state_gate_beats_segregation_of_duties
        """
        batch = create_batch(creator="fin-1")
        resp = api.approve_payout_batch(
            batch["id"], make_exchange_admin_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING_APPROVAL)

    def test_rejected_approve_leaves_batch_in_draft(self, api):
        """PRD §2.8: "and a state failure always surfaces before any
        business-temporal or business-fiscal rule on the same endpoint."
        PRD §3.8: "The batch is born in `DRAFT`, remembers its creator in
        `created_by_user_id`"

        Design: Difficulty/priority_pair_validation_conflict/batch_state_gate_beats_segregation_of_duties
        """
        batch = create_batch(creator="fin-1")
        # Even a non-creator approver hits the state gate on a DRAFT batch.
        resp = api.approve_payout_batch(
            batch["id"], make_exchange_admin_headers("admin-2"))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING_APPROVAL)
        after = validate_success(api.get_payout_batch(batch["id"], ADMIN))
        assert after["status"] == "DRAFT"
        assert after["created_by_user_id"] == "fin-1"
