"""Depth tests for the ``transitive_cascade`` rule.

Two single writes in this contract each move four hops of state. Raising a
dispute suppresses the invoice, voids its live offers, voids the early payment
financed against them and unwinds both the funder's encumbrance and the invoice
face ledger; confirming a settlement releases the payment, early-pays the
invoice, moves the programme's adoption band and rewrites the programme's rate
ceiling.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_analytics,
    assert_cash_breakdown,
    assert_funder_capital_conserved,
    assert_invoice_face_conserved,
    assert_payment_axes,
)
from test_helpers.test_users import PLATFORM_OPS_HEADERS

CASCADE_FACE = 1_000_000


def _cascade_ctx():
    """A funder-financed, DEPLOYED early payment standing on an invoice that also
    carries one SUPERSEDED offer, with the logical clock parked at 2026-08-06."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={"credit_limit_cents": 1000, "self_funding_enabled": False},
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "FUNDER_ONLY",
        },
        funders=[
            {
                "legal_name": "Unwind Capital",
                "capital_limit_cents": 60_000_000,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": 60_000_000,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            }
        ],
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CAS-1",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-04T00:00:00Z",
                line_amount_cents=CASCADE_FACE,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.load_invoices(ctx)

    # O1 is named first and is superseded by O2, so the invoice carries one
    # terminal offer and one live one when the dispute lands.
    o1 = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=700,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.o1_id = o1["id"]
    bumped = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    o2 = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        bumped["version"],
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.o2_id = o2["id"]
    accepted = fx.accept_offer_as_buyer(ctx.o2_id, ctx.buyer_id)
    ctx.payment = fx.reserve_payment(ctx.o2_id, accepted["version"], ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    fx.set_clock("2026-08-05T00:00:00Z")
    ctx.payment = fx.execute_payment(ctx.payment_id, ctx.buyer_id)
    fx.set_clock("2026-08-06T00:00:00Z")
    return ctx


def test_dispute_suppression_cascades_four_hops_and_releases_funder_capital():
    """One POST to the invoice's disputes collection suppresses the invoice, voids
    the ACCEPTED offer, voids the DEPLOYED payment and unwinds both the funder's
    encumbrance and the invoice face ledger, leaving the SUPERSEDED offer and the
    remittance advice untouched.

    PRD (§3.4): "Hop one creates the dispute in `OPEN`, sets the invoice's
    `dispute_suppressed` to true and drives the invoice to `SUPPRESSED`"
    PRD (§3.4): "Hop two applies when the invoice carried offers: every discount
    offer on that invoice whose `status` is `NAMED`, `COUNTERED` or `ACCEPTED`
    becomes `VOIDED_BY_SUPPRESSION`, processed in ascending `created_at` order, each
    with its own `version` increment."
    PRD (§3.4): "Hop three applies when one of those offers had been `ACCEPTED` and
    financed: every early payment on it whose `funding_status` is `RESERVED` or
    `DEPLOYED` becomes `VOID`, and its encumbrance is released according to that
    payment's own funding source — a funder-financed payment decrements its funder's
    `encumbered_capital_cents` by that payment's `net_payment_cents` and triggers a
    recomputation of the funder's `available_capital_cents`"
    PRD (§3.4): "Hop four is the ledger consequence: because those payments have
    left the reserved-deployed-released set, the invoice's `face_covered_cents`
    drops back to 0 and `remaining_face_cents` returns to `face_amount_cents`,
    restoring face conservation."

    Design: Difficulty/transitive_cascade/dispute_suppression_cascades_four_hops_and_releases_funder_capital
    """
    ctx = _cascade_ctx()
    assert_cash_breakdown(
        ctx.payment,
        days_early=30,
        discount_amount_cents=7_500,
        funder_fee_cents=4_466,
        net_payment_cents=988_034,
    )
    before = fx.read_funder(ctx.funder_id)
    assert before["encumbered_capital_cents"] == 988_034, (
        "the deployed payment stands on the funder's book, got {}".format(
            before["encumbered_capital_cents"]
        )
    )

    dispute = fx.raise_dispute(ctx.invoice_id, ctx.buyer_id, 250_000, "SHORT_SHIPMENT")
    assert dispute["status"] == "OPEN", (
        "hop 1 creates the dispute in OPEN, got {}".format(dispute["status"])
    )
    assert dispute["invoice_id"] == ctx.invoice_id, (
        "the dispute records the invoice it contests, got {}".format(
            dispute["invoice_id"]
        )
    )
    ctx.dispute_id = dispute["id"]

    # Hop 1: the invoice.
    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice["status"] == "SUPPRESSED", (
        "hop 1 drives AWARDED -> SUPPRESSED, got {}".format(invoice["status"])
    )
    assert invoice["dispute_suppressed"] is True, (
        "hop 1 sets dispute_suppressed true, got {!r}".format(
            invoice["dispute_suppressed"]
        )
    )

    # Hop 2: the live offer, and only the live offer.
    voided_offer = fx.read_offer(ctx.o2_id, ctx.buyer_id)
    assert voided_offer["status"] == "VOIDED_BY_SUPPRESSION", (
        "hop 2 voids the ACCEPTED offer, got {}".format(voided_offer["status"])
    )
    superseded_offer = fx.read_offer(ctx.o1_id, ctx.buyer_id)
    assert superseded_offer["status"] == "SUPERSEDED", (
        "hop 2 touches only NAMED / COUNTERED / ACCEPTED offers, so the superseded "
        "one keeps its status, got {}".format(superseded_offer["status"])
    )

    # Hop 3: the payment, on the funding axis only.
    payment = fx.read_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        payment,
        funding_status="VOID",
        settlement_status="REMITTED",
        accounting_status="UNCLASSIFIED",
    )
    assert payment["net_payment_cents"] == 988_034, (
        "the cascade releases the encumbrance without re-pricing the payment, got {}".format(
            payment["net_payment_cents"]
        )
    )

    # Hop 4: the funder ledger and the invoice face ledger.
    funder = fx.read_funder(ctx.funder_id)
    assert funder["encumbered_capital_cents"] == 0, (
        "hop 3 decrements the encumbrance by the payment's net, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert funder["available_capital_cents"] == 60_000_000, (
        "available capital is recomputed back to the full tranche, got {}".format(
            funder["available_capital_cents"]
        )
    )
    assert_funder_capital_conserved(funder, 60_000_000)
    assert invoice["face_covered_cents"] == 0, (
        "hop 4 returns face_covered_cents to 0, got {}".format(
            invoice["face_covered_cents"]
        )
    )
    assert invoice["remaining_face_cents"] == CASCADE_FACE, (
        "hop 4 returns remaining_face_cents to the full face, got {}".format(
            invoice["remaining_face_cents"]
        )
    )
    assert_invoice_face_conserved(invoice)

    # The append-only audit record of the remittance survives the void.
    advices, meta = _advices(ctx)
    assert meta["total_count"] == 1, (
        "execution produced exactly one advice and the void does not remove it, "
        "got total_count {}".format(meta["total_count"])
    )
    assert advices[0]["delivery_status"] == "SENT", (
        "the supplier had a remittance_email at execution, got {}".format(
            advices[0]["delivery_status"]
        )
    )
    assert advices[0]["net_paid_cents"] == 988_034, (
        "the advice keeps its snapshot of the net that was sent, got {}".format(
            advices[0]["net_paid_cents"]
        )
    )


def _advices(ctx):
    return validate_paginated(
        api_client.list_remittance_advices(ctx.payment_id, ctx.treasury)
    )


def test_rejecting_the_dispute_releases_the_invoice_without_resurrecting_anything():
    """Resolving the dispute REJECTED walks the invoice back to ELIGIBLE, but the
    voided offer stays VOIDED_BY_SUPPRESSION and the voided payment stays VOID.

    PRD (§3.4): "A `resolution` of `REJECTED`, available to a platform operator,
    moves it `OPEN → RESOLVED_REJECTED`."
    PRD (§3.4): "both cascade identically: once no dispute on that invoice still
    holds `status` `OPEN`, the invoice's `dispute_suppressed` returns to false and
    the invoice moves `SUPPRESSED → ELIGIBLE`. This revert edge is what makes the
    invoice lifecycle non-linear — a payable may be suppressed and released
    repeatedly — but it does not resurrect anything: offers voided by the
    suppression stay `VOIDED_BY_SUPPRESSION`, and the supplier must name a fresh
    rate."

    Design: Difficulty/transitive_cascade/dispute_suppression_cascades_four_hops_and_releases_funder_capital
    """
    ctx = _cascade_ctx()
    dispute = fx.raise_dispute(ctx.invoice_id, ctx.buyer_id, 250_000, "SHORT_SHIPMENT")

    resolved = validate_success(
        api_client.resolve_dispute(
            dispute["id"],
            f.dispute_resolution_payload(
                "REJECTED", resolution_note="Carrier proof of delivery accepted"
            ),
            PLATFORM_OPS_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED_REJECTED", (
        "a REJECTED resolution moves the dispute to RESOLVED_REJECTED, got {}".format(
            resolved["status"]
        )
    )
    assert resolved["resolution_note"] == "Carrier proof of delivery accepted", (
        "the note is stored on the dispute, got {!r}".format(
            resolved["resolution_note"]
        )
    )
    assert resolved["version"] == dispute["version"] + 1, (
        "every branch increments the dispute's version by one, got {}".format(
            resolved["version"]
        )
    )

    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert invoice["status"] == "ELIGIBLE", (
        "the revert edge returns the invoice to ELIGIBLE, not OFFERED or AWARDED, "
        "got {}".format(invoice["status"])
    )
    assert invoice["dispute_suppressed"] is False, (
        "dispute_suppressed returns to false, got {!r}".format(
            invoice["dispute_suppressed"]
        )
    )
    assert invoice["face_covered_cents"] == 0, (
        "the released invoice carries no covered face, got {}".format(
            invoice["face_covered_cents"]
        )
    )
    assert_invoice_face_conserved(invoice)

    assert fx.read_offer(ctx.o2_id, ctx.buyer_id)["status"] == "VOIDED_BY_SUPPRESSION", (
        "the resolution does not resurrect the voided offer"
    )
    assert fx.read_offer(ctx.o1_id, ctx.buyer_id)["status"] == "SUPERSEDED", (
        "the superseded offer is still superseded"
    )
    payment = fx.read_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        payment,
        funding_status="VOID",
        settlement_status="REMITTED",
        accounting_status="UNCLASSIFIED",
    )
    funder = fx.read_funder(ctx.funder_id)
    assert funder["encumbered_capital_cents"] == 0, (
        "the released capital is not re-encumbered, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert_funder_capital_conserved(funder, 60_000_000)


def _adoption_ctx(second_face=100_000):
    """A SELF_ONLY programme carrying four ELIGIBLE invoices, keyed by invoice
    number so the arithmetic below never depends on collection order."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
            "reclass_days_threshold": 30,
            "reclass_apr_threshold_bps": 900,
        },
        program_overrides={
            "program_type": "SUPPLIER_NAMED",
            "max_acceptable_apr_bps": 1200,
            "min_days_early": 5,
            "concentration_cap_pct": 100.00,
            "funding_policy": "SELF_ONLY",
        },
    )
    faces = [100_000, second_face, 100_000, 100_000]
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="AD-{}".format(n),
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=face,
            )
            for n, face in enumerate(faces, start=1)
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    fx.load_invoices(ctx)
    ctx.by_number = {row["invoice_number"]: row for row in ctx.invoices}
    assert len(ctx.by_number) == 4, (
        "the file produced four invoices, got {}".format(sorted(ctx.by_number))
    )
    return ctx


def _analytics(ctx):
    return validate_success(
        api_client.get_program_analytics(ctx.program_id, ctx.admin)
    )


def _early_pay(
    ctx,
    invoice,
    offered_apr_bps,
    requested_pay_date,
    execute_at,
    confirm_at,
    acceptance_deadline="2026-08-20T00:00:00Z",
):
    """Name, accept, reserve, execute and confirm one invoice end to end."""
    offer = fx.name_offer(
        invoice["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice["version"],
        offered_apr_bps=offered_apr_bps,
        requested_pay_date=requested_pay_date,
        acceptance_deadline=acceptance_deadline,
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    payment = fx.reserve_payment(offer["id"], accepted["version"], ctx.buyer_id)
    fx.set_clock(execute_at)
    deployed = fx.execute_payment(payment["id"], ctx.buyer_id)
    fx.set_clock(confirm_at)
    released = fx.confirm_settlement(payment["id"], ctx.buyer_id)
    return deployed, released


def test_settlement_confirmation_cascades_into_programme_rate_ceiling():
    """Confirming one settlement releases the payment, early-pays the invoice, moves
    the programme from DISCOVERY at 0.00 percent to OPTIMISED at 25.00 percent and
    rewrites the rate ceiling from 1200 to 900 basis points.

    PRD (§3.8): "The remittance axis moves `REMITTED → CONFIRMED` and the cash axis
    moves `DEPLOYED → RELEASED`, releasing the encumbrance in full"
    PRD (§3.8): "Because the remittance axis reached `CONFIRMED`, the invoice moves
    `AWARDED → EARLY_PAID`, its `final_discount_cents` is written from the
    value-date-basis discount, and its `discount_true_up_cents` is written as
    `final_discount_cents` minus `provisional_discount_cents`"
    PRD (§3.10): "An adoption rate at 25.00 percent or above but below 60.00 percent
    is `OPTIMISED` — so 25.00 is `OPTIMISED` and 59.99 is still `OPTIMISED`."
    PRD (§3.10): "Under `OPTIMISED`, the candidate is the weighted average accepted
    APR multiplied by 90 percent, truncated toward zero to a whole basis point, and
    then raised to 200 basis points if that product fell below it."

    Design: Difficulty/transitive_cascade/settlement_confirmation_cascades_into_programme_rate_ceiling
    """
    ctx = _adoption_ctx()
    invoice = ctx.by_number["AD-1"]

    before = _analytics(ctx)
    assert_analytics(
        before,
        eligible_invoice_count=4,
        adopted_invoice_count=0,
        adoption_rate_pct=0.00,
        rate_posture="DISCOVERY",
        weighted_avg_accepted_apr_bps=0,
        max_acceptable_apr_bps=1200,
    )

    offer = fx.name_offer(
        invoice["id"],
        ctx.session_id,
        ctx.supplier_id,
        invoice["version"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    accepted = fx.accept_offer_as_buyer(offer["id"], ctx.buyer_id)
    payment = fx.reserve_payment(offer["id"], accepted["version"], ctx.buyer_id)
    fx.set_clock("2026-08-05T00:00:00Z")
    deployed = fx.execute_payment(payment["id"], ctx.buyer_id)
    assert_cash_breakdown(
        deployed,
        days_early=56,
        discount_amount_cents=1556,
        funder_fee_cents=0,
        net_payment_cents=98_444,
    )
    assert str(deployed["value_date"])[:10] == "2026-08-07", (
        "the value date is two days after execution, got {!r}".format(
            deployed["value_date"]
        )
    )
    buyer_mid = validate_success(api_client.get_buyer(ctx.buyer_id, PLATFORM_OPS_HEADERS))
    assert buyer_mid["credit_used_cents"] == 98_444, (
        "the deployed net stands on the buyer's credit, got {}".format(
            buyer_mid["credit_used_cents"]
        )
    )
    still_discovery = _analytics(ctx)
    assert still_discovery["adopted_invoice_count"] == 0, (
        "a deployed payment has not early-paid anything yet, got {}".format(
            still_discovery["adopted_invoice_count"]
        )
    )

    fx.set_clock("2026-08-07T00:00:00Z")
    released = fx.confirm_settlement(payment["id"], ctx.buyer_id)

    # Hop 1: the payment.
    assert_payment_axes(
        released, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    assert_cash_breakdown(
        released,
        days_early=54,
        discount_amount_cents=1500,
        funder_fee_cents=0,
        net_payment_cents=98_500,
    )

    # Hop 2: the invoice.
    early_paid = fx.read_invoice(invoice["id"], ctx.buyer_id)
    assert early_paid["status"] == "EARLY_PAID", (
        "confirmation drives AWARDED -> EARLY_PAID, got {}".format(
            early_paid["status"]
        )
    )
    assert early_paid["provisional_discount_cents"] == 1556, (
        "the provisional figure is the pay-date one, got {}".format(
            early_paid["provisional_discount_cents"]
        )
    )
    assert early_paid["final_discount_cents"] == 1500, (
        "the final figure is the value-date one, got {}".format(
            early_paid["final_discount_cents"]
        )
    )
    assert early_paid["discount_true_up_cents"] == -56, (
        "the true-up is 1500 minus 1556, got {}".format(
            early_paid["discount_true_up_cents"]
        )
    )

    # Hops 3 and 4: the programme's adoption band and its rate ceiling.
    after = _analytics(ctx)
    assert_analytics(
        after,
        eligible_invoice_count=4,
        adopted_invoice_count=1,
        adoption_rate_pct=25.00,
        rate_posture="OPTIMISED",
        weighted_avg_accepted_apr_bps=1000,
        max_acceptable_apr_bps=900,
    )
    assert after["max_acceptable_apr_bps"] != 1200, (
        "the ceiling must have been rewritten by the OPTIMISED candidate"
    )

    buyer = validate_success(api_client.get_buyer(ctx.buyer_id, PLATFORM_OPS_HEADERS))
    assert buyer["credit_used_cents"] == 0, (
        "the encumbrance is released in full, leaving no residue from the "
        "value-date rewrite, got {}".format(buyer["credit_used_cents"])
    )


def test_second_settlement_reweights_the_average_by_face_and_tightens_again():
    """A second early payment of face 300000 at 900 bps drags the face-weighted
    average to 925 basis points — not the plain mean of 950 — and the ceiling
    tightens again from 900 to 832.

    PRD (§3.10): "Take every invoice on the programme whose `status` is
    `EARLY_PAID`, multiply each one's `accepted_apr_bps` by its
    `face_amount_cents`, sum those products, divide by the sum of those same faces,
    and round the quotient half up to a whole basis point."
    PRD (§3.10): "The programme's `max_acceptable_apr_bps` is then set to the
    smaller of its current value and that candidate. This last step makes the
    ceiling **monotone**: it can only ever tighten, and no adoption movement, band
    change or invoice reversal ever loosens it again."

    Design: Difficulty/transitive_cascade/settlement_confirmation_cascades_into_programme_rate_ceiling
    """
    ctx = _adoption_ctx(second_face=300_000)
    assert ctx.by_number["AD-2"]["face_amount_cents"] == 300_000, (
        "AD-2 is the heavy invoice, got face {}".format(
            ctx.by_number["AD-2"]["face_amount_cents"]
        )
    )

    _early_pay(
        ctx,
        ctx.by_number["AD-1"],
        offered_apr_bps=1000,
        requested_pay_date="2026-08-05T00:00:00Z",
        execute_at="2026-08-05T00:00:00Z",
        confirm_at="2026-08-07T00:00:00Z",
    )
    after_first = _analytics(ctx)
    assert_analytics(
        after_first,
        adopted_invoice_count=1,
        adoption_rate_pct=25.00,
        weighted_avg_accepted_apr_bps=1000,
        max_acceptable_apr_bps=900,
    )

    # The tightened ceiling of 900 admits a rate of exactly 900.
    heavy = fx.read_invoice(ctx.by_number["AD-2"]["id"], ctx.buyer_id)
    deployed, released = _early_pay(
        ctx,
        heavy,
        offered_apr_bps=900,
        requested_pay_date="2026-08-10T00:00:00Z",
        execute_at="2026-08-10T00:00:00Z",
        confirm_at="2026-08-12T00:00:00Z",
    )
    assert_cash_breakdown(
        deployed,
        days_early=51,
        discount_amount_cents=3825,
        funder_fee_cents=0,
        net_payment_cents=296_175,
    )
    assert_cash_breakdown(
        released,
        days_early=49,
        discount_amount_cents=3675,
        funder_fee_cents=0,
        net_payment_cents=296_325,
    )
    heavy_paid = fx.read_invoice(heavy["id"], ctx.buyer_id)
    assert heavy_paid["status"] == "EARLY_PAID", (
        "the second invoice is early paid, got {}".format(heavy_paid["status"])
    )
    assert heavy_paid["discount_true_up_cents"] == -150, (
        "3675 minus 3825 is -150, got {}".format(heavy_paid["discount_true_up_cents"])
    )

    after_second = _analytics(ctx)
    assert_analytics(
        after_second,
        eligible_invoice_count=4,
        adopted_invoice_count=2,
        adoption_rate_pct=50.00,
        rate_posture="OPTIMISED",
        weighted_avg_accepted_apr_bps=925,
        max_acceptable_apr_bps=832,
    )
    assert after_second["weighted_avg_accepted_apr_bps"] != 950, (
        "950 is the unweighted mean of 1000 and 900, which is not the rule"
    )
    assert after_second["max_acceptable_apr_bps"] != 833, (
        "832.5 is truncated toward zero, not rounded up"
    )
    assert after_second["max_acceptable_apr_bps"] < after_first["max_acceptable_apr_bps"], (
        "the ceiling only ever tightens, got {} after {}".format(
            after_second["max_acceptable_apr_bps"],
            after_first["max_acceptable_apr_bps"],
        )
    )

    buyer = validate_success(api_client.get_buyer(ctx.buyer_id, PLATFORM_OPS_HEADERS))
    assert buyer["credit_used_cents"] == 0, (
        "both payments are RELEASED, so no credit is used, got {}".format(
            buyer["credit_used_cents"]
        )
    )
