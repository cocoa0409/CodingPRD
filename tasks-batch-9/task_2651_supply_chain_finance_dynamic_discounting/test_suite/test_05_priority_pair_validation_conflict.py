"""Depth tests for the ``priority_pair_validation_conflict`` rule.

The rejection-precedence list of §2.7 is only interesting where two of its
checks are violated by the same request, because that is where an
implementation that evaluates its guards in a convenient order rather than the
specified one produces the wrong error identifier while still refusing the
call. The PRD names the three pairs implementations most often get backwards,
and each test below constructs one of them, asserts that the higher-priority
cause is the one reported, and then removes that cause so the suppressed lower
check fires on its own — which is what proves it really was violated the first
time rather than merely absent.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_ACCEPTANCE_WINDOW_CLOSED,
    ERR_APR_OUT_OF_PROGRAM_BOUNDS,
    ERR_BUYER_CREDIT_LIMIT_EXCEEDED,
    ERR_PROGRAM_NOT_OPEN,
    ERR_SUPPLIER_NOT_PAYMENT_READY,
    ERR_SUPPLIER_SANCTIONS_HOLD,
)
from test_helpers.assertions import (
    assert_analytics,
    assert_cash_breakdown,
    assert_invoice,
    assert_offer,
    assert_payment_axes,
    assert_supplier_axes,
)
from test_helpers.test_users import (
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
    make_supplier_headers,
)

# The pay-date-basis pricing every test in the first pair works from:
# a face of 1000000 at 900 bps over the 30 days between the requested pay date
# 2026-08-05 and the net due date 2026-09-04 discounts 7500 cents, so the
# pre-fee net that check 28 measures against the credit limit is 992500.
HEADROOM_FACE = 1_000_000
HEADROOM_DISCOUNT = 7_500
HEADROOM_PRE_FEE_NET = 992_500

SELF_ONLY_PROGRAM = {
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_ONLY",
}


def _accepted_offer_on_thin_headroom(credit_limit_cents):
    """An OPEN SELF_ONLY programme on a buyer whose credit limit is
    ``credit_limit_cents``, one onboarded supplier, a LIVE session and an
    ACCEPTED 900 bps offer on a 1000000-cent invoice due 2026-09-04."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Thin Headroom Buyer",
            "credit_limit_cents": credit_limit_cents,
            "self_funding_enabled": True,
        },
        program_overrides=dict(SELF_ONLY_PROGRAM, name="Headroom Programme"),
        supplier_overrides={"legal_name": "Headroom Supply"},
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="HD-1",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-04T00:00:00Z",
                line_amount_cents=HEADROOM_FACE,
                tax_rate_bps=0,
            )
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    fx.load_invoices(ctx)
    offer = fx.name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.offer_id = offer["id"]
    accepted = fx.accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    ctx.offer_version = accepted["version"]
    return ctx


def _reserve(ctx, expected_offer_version=None):
    """POST /early-payments as the treasury officer, returning the raw
    response so a rejection can be inspected."""
    version = (
        ctx.offer_version if expected_offer_version is None else expected_offer_version
    )
    return api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, version),
        make_buyer_treasury_headers(ctx.buyer_id),
    )


def _read_buyer(buyer_id):
    return validate_success(
        api_client.get_buyer(buyer_id, make_buyer_admin_headers(buyer_id))
    )


def test_paused_programme_outranks_the_buyer_credit_limit_breach():
    """One reservation violates check 8 and check 28 at once; the programme-state
    cause must be the reported one, and resuming the programme then exposes the
    credit breach that was genuinely there all along.

    PRD §2.7: "A reservation request on an accepted offer whose programme has
    since been paused, submitted for a self-funding buyer whose remaining
    headroom is smaller than the pre-fee net, violates both check 8 and check
    28; the reported error is `ERR_PROGRAM_NOT_OPEN`, because programme state
    outranks credit capacity."

    PRD §2.7 check 28: "the buyer's `credit_used_cents` plus the pre-fee net of
    this payment is at most the buyer's `credit_limit_cents` when the resolved
    funding source is buyer self-funding; exact equality is allowed. Otherwise
    `ERR_BUYER_CREDIT_LIMIT_EXCEEDED` (402)."

    PRD §3.7: "The pre-fee net used throughout this decision is the invoice's
    `face_amount_cents` minus the payment's provisional
    `discount_amount_cents`, computed before any funder fee exists."

    Design: Difficulty/priority_pair_validation_conflict/paused_program_state_beats_buyer_credit_limit
    """
    ctx = _accepted_offer_on_thin_headroom(500_000)

    paused = fx.set_program_status(ctx.program_id, ctx.buyer_id, "PAUSE")
    assert paused["status"] == "PAUSED", (
        "PAUSE must leave the programme in PAUSED, got {}".format(paused["status"])
    )

    # Both check 8 and check 28 are violated: the programme is PAUSED and the
    # 500000-cent limit cannot absorb the 992500-cent pre-fee net.
    both_violated = _reserve(ctx)
    body = validate_error(both_violated, ERR_PROGRAM_NOT_OPEN, 409)
    assert body["error_id"] != ERR_BUYER_CREDIT_LIMIT_EXCEEDED, (
        "programme state outranks credit capacity, so the 402 must stay hidden"
    )
    assert both_violated.status_code != 402, (
        "the reported status must be the 409 of check 8, not the 402 of check 28"
    )

    resumed = fx.set_program_status(ctx.program_id, ctx.buyer_id, "RESUME")
    assert resumed["status"] == "OPEN", (
        "RESUME must return the programme to OPEN, got {}".format(resumed["status"])
    )

    # With the higher-priority cause removed, the suppressed lower check fires.
    only_credit = _reserve(ctx)
    validate_error(only_credit, ERR_BUYER_CREDIT_LIMIT_EXCEEDED, 402)

    # Neither rejection created a row, encumbered anything or moved the OCC anchor.
    rows, meta = validate_paginated(
        api_client.list_early_payments(
            make_buyer_treasury_headers(ctx.buyer_id), offer_id=ctx.offer_id
        )
    )
    assert meta["total_count"] == 0, (
        "a rejected reservation must not persist an EarlyPayment, got {}".format(
            meta["total_count"]
        )
    )
    assert rows == [], "no early-payment row may exist for the offer"

    buyer = _read_buyer(ctx.buyer_id)
    assert buyer["credit_used_cents"] == 0, (
        "a rejected reservation encumbers nothing, got credit_used_cents {}".format(
            buyer["credit_used_cents"]
        )
    )

    offer = fx.read_offer(ctx.offer_id, ctx.buyer_id)
    assert_offer(offer, status="ACCEPTED", version=ctx.offer_version)

    invoice = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        invoice,
        status="AWARDED",
        face_amount_cents=HEADROOM_FACE,
        face_covered_cents=0,
        remaining_face_cents=HEADROOM_FACE,
    )


def test_credit_headroom_admits_the_pre_fee_net_at_exact_equality():
    """Check 28 is measured against the pre-fee net and allows exact equality,
    so a limit one cent short rejects with 402 while a limit equal to the
    pre-fee net reserves cleanly.

    PRD §2.7 check 28: "the buyer's `credit_used_cents` plus the pre-fee net of
    this payment is at most the buyer's `credit_limit_cents` when the resolved
    funding source is buyer self-funding; exact equality is allowed."

    PRD §3.7: "Buyer self-funding can pay when the buyer's
    `self_funding_enabled` is true and the buyer's `credit_used_cents` plus the
    pre-fee net of this payment is at most the buyer's `credit_limit_cents`;
    exact equality is acceptable. In that case the payment's `funding_source` is
    set to `BUYER_SELF` and its `funder_id` stays null."

    Design: Difficulty/priority_pair_validation_conflict/paused_program_state_beats_buyer_credit_limit
    """
    one_cent_short = _accepted_offer_on_thin_headroom(HEADROOM_PRE_FEE_NET - 1)
    validate_error(
        _reserve(one_cent_short), ERR_BUYER_CREDIT_LIMIT_EXCEEDED, 402
    )
    assert _read_buyer(one_cent_short.buyer_id)["credit_used_cents"] == 0

    exactly_enough = _accepted_offer_on_thin_headroom(HEADROOM_PRE_FEE_NET)
    payment = validate_success(_reserve(exactly_enough), 201)
    assert_payment_axes(
        payment,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert payment["funding_source"] == "BUYER_SELF", (
        "a SELF_ONLY waterfall resolves to BUYER_SELF, got {}".format(
            payment["funding_source"]
        )
    )
    assert payment["funder_id"] is None, "a self-funded payment leaves funder_id null"
    assert_cash_breakdown(
        payment,
        days_early=30,
        discount_amount_cents=HEADROOM_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=HEADROOM_PRE_FEE_NET,
    )

    buyer = _read_buyer(exactly_enough.buyer_id)
    assert buyer["credit_used_cents"] == HEADROOM_PRE_FEE_NET, (
        "reservation encumbers the whole net payment, got {}".format(
            buyer["credit_used_cents"]
        )
    )
    assert buyer["credit_used_cents"] == buyer["credit_limit_cents"], (
        "the buyer is now exactly at its limit, which check 28 permits"
    )


def _compliance_ctx():
    """An OPEN SELF_ONLY programme, a LIVE session, supplier S driven all the
    way to ACTIVE, supplier T whose identity axis passed but whose bank axis was
    never opened, and one payable file carrying a 100000-cent invoice for each."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Compliance First Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(SELF_ONLY_PROGRAM, name="Compliance Programme"),
        supplier_overrides={
            "legal_name": "Sanctioned Later Supply S",
            "remittance_email": "ar@sls.example",
            "identity_score": 94,
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    ctx.s_id = ctx.supplier_id
    ctx.supplier_s = ctx.supplier

    bankless = fx.new_supplier(legal_name="Bankless Supply T", tax_id_last4="8282")
    ctx.t_id = bankless["id"]
    fx.submit_onboarding(ctx.t_id)
    ctx.supplier_t = fx.adjudicate_idv(ctx.t_id, "PASSED", 81)

    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.s_id,
                invoice_number="CM-S",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
            f.payable_row(
                ctx.t_id,
                invoice_number="CM-T",
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            ),
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    invoices = fx.load_invoices(ctx)
    by_number = {row["invoice_number"]: row for row in invoices}
    ctx.inv_s = by_number["CM-S"]
    ctx.inv_t = by_number["CM-T"]
    return ctx


def _name_offer_raw(ctx, invoice, supplier_id, offered_apr_bps=900):
    """POST /discount-offers as the named supplier, returning the raw response."""
    return api_client.create_offer(
        f.offer_payload(
            invoice["id"],
            ctx.session_id,
            invoice["version"],
            offered_apr_bps=offered_apr_bps,
            requested_pay_date="2026-08-05T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        make_supplier_headers(supplier_id),
    )


def test_compliance_hold_outranks_the_payment_readiness_failure():
    """A hold forces the supplier out of ACTIVE, so one naming attempt violates
    check 14 and check 15 together and must report the compliance cause; a
    second supplier whose only defect is the unopened bank axis isolates the
    lower check.

    PRD §2.7: "A rate-naming request for a supplier whose compliance hold is set
    — which also forced that supplier out of `ACTIVE` and therefore fails
    payment readiness — violates both check 14 and check 15; the reported error
    is `ERR_SUPPLIER_SANCTIONS_HOLD`."

    PRD §2.7 check 14: "the supplier that owns the invoice has `sanctions_hold`
    false. Otherwise `ERR_SUPPLIER_SANCTIONS_HOLD` (403)."

    PRD §2.7 check 15: "the supplier that owns the invoice has
    `onboarding_status` `ACTIVE`, `bank_status` `VERIFIED` and a non-null
    `payment_ready_at`. Otherwise `ERR_SUPPLIER_NOT_PAYMENT_READY` (409)."

    PRD §3.2: "A platform operator setting `hold` to true writes
    `sanctions_hold` true and forces `onboarding_status` to `SUSPENDED`"

    Design: Difficulty/priority_pair_validation_conflict/sanctions_hold_beats_supplier_payment_readiness
    """
    ctx = _compliance_ctx()

    assert_supplier_axes(
        ctx.supplier_s,
        onboarding_status="ACTIVE",
        idv_status="PASSED",
        bank_status="VERIFIED",
    )
    # The bank axis of T "opens only when a settlement account is registered",
    # so it is still NOT_STARTED and the fork-join never fired.
    assert_supplier_axes(
        ctx.supplier_t,
        onboarding_status="VERIFYING",
        idv_status="PASSED",
        bank_status="NOT_STARTED",
    )
    assert ctx.supplier_t["payment_ready_at"] is None, (
        "T never reached the join, so payment_ready_at must still be null"
    )

    s_version_before = ctx.supplier_s["version"]
    held = fx.set_sanctions_hold(ctx.s_id, True)
    assert held["sanctions_hold"] is True
    assert_supplier_axes(
        held, onboarding_status="SUSPENDED", idv_status="PASSED", bank_status="VERIFIED"
    )
    assert held["version"] == s_version_before + 1, (
        "either direction of the hold increments the supplier's version"
    )

    # Both check 14 and check 15 are violated for S: the hold is on and the
    # forced SUSPENDED state means the supplier is not payment-ready either.
    both_violated = _name_offer_raw(ctx, ctx.inv_s, ctx.s_id)
    body = validate_error(both_violated, ERR_SUPPLIER_SANCTIONS_HOLD, 403)
    assert body["error_id"] != ERR_SUPPLIER_NOT_PAYMENT_READY, (
        "the compliance cause is the one reported when both rules fire together"
    )
    assert both_violated.status_code != 409, (
        "the reported status must be the 403 of check 14, not the 409 of check 15"
    )

    # T carries no hold at all, so only the lower check can fire for it.
    only_readiness = _name_offer_raw(ctx, ctx.inv_t, ctx.t_id)
    validate_error(only_readiness, ERR_SUPPLIER_NOT_PAYMENT_READY, 409)

    restored = fx.set_sanctions_hold(ctx.s_id, False)
    assert restored["sanctions_hold"] is False
    assert_supplier_axes(restored, onboarding_status="ACTIVE")
    assert restored["version"] == s_version_before + 2

    # The very same request body now succeeds.
    offer = validate_success(_name_offer_raw(ctx, ctx.inv_s, ctx.s_id), 201)
    assert_offer(offer, status="NAMED", offered_apr_bps=900, counter_round=0)
    assert_invoice(
        fx.read_invoice(ctx.inv_s["id"], ctx.buyer_id),
        status="OFFERED",
        dispute_suppressed=False,
    )

    # T's rejected attempt left its invoice completely untouched.
    invoice_t = fx.read_invoice(ctx.inv_t["id"], ctx.buyer_id)
    assert_invoice(
        invoice_t, status="ELIGIBLE", version=ctx.inv_t["version"], face_covered_cents=0
    )


def test_lifting_a_hold_returns_the_supplier_only_to_the_state_its_axes_justify():
    """Release is not a promotion: the supplier whose two axes are complete comes
    back to ACTIVE, while the supplier with an unopened bank axis comes back only
    to VERIFYING and still cannot name a rate.

    PRD §3.2: "Setting `hold` to false requires the supplier to be in
    `SUSPENDED` and returns it to whichever state its two axes justify — to
    `ACTIVE` when `idv_status` is `PASSED` and `bank_status` is `VERIFIED`, and
    to `VERIFYING` when that combination does not hold. Release never pushes a
    supplier past the join it has not earned."

    PRD §3.2: "The hold blocks new actions only"

    Design: Difficulty/priority_pair_validation_conflict/sanctions_hold_beats_supplier_payment_readiness
    """
    ctx = _compliance_ctx()

    t_version_before = ctx.supplier_t["version"]
    held_t = fx.set_sanctions_hold(ctx.t_id, True)
    assert_supplier_axes(
        held_t,
        onboarding_status="SUSPENDED",
        idv_status="PASSED",
        bank_status="NOT_STARTED",
    )
    assert held_t["sanctions_hold"] is True
    assert held_t["version"] == t_version_before + 1

    released_t = fx.set_sanctions_hold(ctx.t_id, False)
    assert released_t["sanctions_hold"] is False
    assert released_t["onboarding_status"] == "VERIFYING", (
        "release must not push T past the join it never earned, got {}".format(
            released_t["onboarding_status"]
        )
    )
    assert released_t["onboarding_status"] != "ACTIVE", (
        "T's bank axis is still NOT_STARTED, so ACTIVE is unreachable"
    )
    assert released_t["payment_ready_at"] is None, (
        "payment_ready_at is stamped only at the join, never by a hold release"
    )
    assert released_t["version"] == t_version_before + 2

    # Still not payment-ready, so the lower check fires on its own.
    validate_error(
        _name_offer_raw(ctx, ctx.inv_t, ctx.t_id), ERR_SUPPLIER_NOT_PAYMENT_READY, 409
    )

    # The same round trip on S, whose axes are both complete, lands on ACTIVE.
    held_s = fx.set_sanctions_hold(ctx.s_id, True)
    assert held_s["onboarding_status"] == "SUSPENDED"
    released_s = fx.set_sanctions_hold(ctx.s_id, False)
    assert released_s["onboarding_status"] == "ACTIVE", (
        "both axes complete, so release returns S to ACTIVE, got {}".format(
            released_s["onboarding_status"]
        )
    )
    assert released_s["payment_ready_at"] is not None, (
        "check 15 needs a non-null payment_ready_at, so S must carry one again"
    )
    offer = validate_success(_name_offer_raw(ctx, ctx.inv_s, ctx.s_id), 201)
    assert_offer(offer, status="NAMED", offered_apr_bps=900)


def _ceiling_ctx():
    """An OPEN SELF_ONLY programme whose ceiling starts at 1200 bps, one
    onboarded supplier, a LIVE session and four ELIGIBLE 100000-cent invoices
    due 2026-09-30, with the clock parked at 2026-08-02."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Ceiling Tightener Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(SELF_ONLY_PROGRAM, name="Ceiling Programme"),
        supplier_overrides={
            "legal_name": "Ceiling Supply Co",
            "remittance_email": "ar@ceiling.example",
            "identity_score": 92,
        },
        session_window=("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                invoice_number="CL-{}".format(n),
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            )
            for n in (1, 2, 3, 4)
        ],
    )
    fx.set_clock("2026-08-02T00:00:00Z")
    ctx.clock = "2026-08-02T00:00:00Z"
    ctx.by_number = {
        row["invoice_number"]: row for row in fx.load_invoices(ctx)
    }
    return ctx


def _name(ctx, invoice_number, offered_apr_bps, requested_pay_date, acceptance_deadline):
    invoice = ctx.by_number[invoice_number]
    return validate_success(
        api_client.create_offer(
            f.offer_payload(
                invoice["id"],
                ctx.session_id,
                invoice["version"],
                offered_apr_bps=offered_apr_bps,
                requested_pay_date=requested_pay_date,
                acceptance_deadline=acceptance_deadline,
            ),
            make_supplier_headers(ctx.supplier_id),
        ),
        201,
    )


def _analytics(ctx):
    return validate_success(
        api_client.get_program_analytics(
            ctx.program_id, make_buyer_admin_headers(ctx.buyer_id)
        )
    )


def test_lapsed_acceptance_window_outranks_the_tightened_apr_ceiling():
    """A settled payment tightens the programme ceiling from 1200 to 900 bps while
    an offer's acceptance deadline lapses; the one acceptance that breaches both
    must report the window error, and a fresh 1000 bps naming then isolates the
    APR breach.

    PRD §2.7: "An acceptance submitted after the clock has passed the offer's
    acceptance deadline, on an offer whose named APR now sits above a programme
    ceiling that was tightened in the meantime, violates both check 16 and check
    19; the reported error is `ERR_ACCEPTANCE_WINDOW_CLOSED`."

    PRD §2.7 check 19: "the APR being named, countered or accepted lies at or
    above 200 basis points and at or below the programme's current
    `max_acceptable_apr_bps` ... Otherwise `ERR_APR_OUT_OF_PROGRAM_BOUNDS`
    (422). ... The re-check at acceptance reads the programme's bounds as they
    stand at that moment, which the rate-optimisation ceiling may have tightened
    after the offer was originally named."

    PRD §3.10: "a programme whose `max_acceptable_apr_bps` is 1200 and which has
    a single `EARLY_PAID` invoice at 1000 basis points, at an adoption rate of
    exactly 25.00 percent and therefore in `OPTIMISED`, produces a candidate of
    900 basis points and a new ceiling of 900."

    Design: Difficulty/priority_pair_validation_conflict/acceptance_window_beats_tightened_apr_ceiling
    """
    ctx = _ceiling_ctx()

    # Both offers are legal at naming time, under the untightened 1200 ceiling.
    o1 = _name(ctx, "CL-1", 1000, "2026-08-05T00:00:00Z", "2026-08-20T00:00:00Z")
    o2 = _name(ctx, "CL-2", 1000, "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")

    accepted = fx.accept_offer_as_buyer(o1["id"], ctx.buyer_id)
    assert_offer(accepted, status="ACCEPTED", accepted_apr_bps=1000)

    payment = fx.reserve_payment(o1["id"], accepted["version"], ctx.buyer_id)

    fx.set_clock("2026-08-05T00:00:00Z")
    deployed = fx.execute_payment(payment["id"], ctx.buyer_id)
    assert_payment_axes(deployed, funding_status="DEPLOYED", settlement_status="REMITTED")
    # 56 days from the real execution date 2026-08-05 to 2026-09-30:
    # 100000 * 1000 * 56 / (10000 * 360) = 1555.55..., half up 1556.
    assert_cash_breakdown(
        deployed,
        days_early=56,
        discount_amount_cents=1556,
        funder_fee_cents=0,
        net_payment_cents=98_444,
    )

    fx.set_clock("2026-08-07T00:00:00Z")
    released = fx.confirm_settlement(payment["id"], ctx.buyer_id)
    assert_payment_axes(
        released, funding_status="RELEASED", settlement_status="CONFIRMED"
    )
    # The value-date basis spans two fewer days: 54 days gives exactly 1500.
    assert_cash_breakdown(
        released,
        days_early=54,
        discount_amount_cents=1500,
        funder_fee_cents=0,
        net_payment_cents=98_500,
        check_identity=False,
    )
    assert_invoice(
        fx.read_invoice(ctx.by_number["CL-1"]["id"], ctx.buyer_id),
        status="EARLY_PAID",
        accepted_apr_bps=1000,
        final_discount_cents=1500,
        provisional_discount_cents=1556,
        discount_true_up_cents=-56,
    )

    # The ceiling has tightened, so O2's 1000 bps is now out of bounds too.
    view = _analytics(ctx)
    assert_analytics(
        view,
        eligible_invoice_count=4,
        adopted_invoice_count=1,
        adoption_rate_pct=25.00,
        rate_posture="OPTIMISED",
        weighted_avg_accepted_apr_bps=1000,
        max_acceptable_apr_bps=900,
    )
    assert view["max_acceptable_apr_bps"] != 1200, (
        "the ceiling must have tightened away from its configured 1200"
    )

    # Clock 2026-08-07 is past O2's 2026-08-06 deadline AND 1000 > 900, so
    # check 16 and check 19 are both violated by this single acceptance.
    both_violated = api_client.accept_offer(
        o2["id"], make_buyer_admin_headers(ctx.buyer_id)
    )
    body = validate_error(both_violated, ERR_ACCEPTANCE_WINDOW_CLOSED, 409)
    assert body["error_id"] != ERR_APR_OUT_OF_PROGRAM_BOUNDS, (
        "the window error wins even though the APR breach is the permanent defect"
    )
    assert both_violated.status_code != 422, (
        "the reported status must be the 409 of check 16, not the 422 of check 19"
    )
    # Step three of the clock sweep expires offers only when step two closed
    # their session, so a lapsed acceptance window leaves the offer NAMED.
    assert_offer(fx.read_offer(o2["id"], ctx.buyer_id), status="NAMED")
    assert_invoice(
        fx.read_invoice(ctx.by_number["CL-2"]["id"], ctx.buyer_id), status="OFFERED"
    )

    # With no window to lapse, the suppressed lower check fires on its own.
    invoice_3 = ctx.by_number["CL-3"]
    only_apr = api_client.create_offer(
        f.offer_payload(
            invoice_3["id"],
            ctx.session_id,
            invoice_3["version"],
            offered_apr_bps=1000,
            requested_pay_date="2026-08-10T00:00:00Z",
            acceptance_deadline="2026-08-20T00:00:00Z",
        ),
        make_supplier_headers(ctx.supplier_id),
    )
    validate_error(only_apr, ERR_APR_OUT_OF_PROGRAM_BOUNDS, 422)
    assert_invoice(
        fx.read_invoice(invoice_3["id"], ctx.buyer_id),
        status="ELIGIBLE",
        version=invoice_3["version"],
    )

    # 800 bps sits inside the tightened [200, 900] band and accepts cleanly.
    o4 = _name(ctx, "CL-4", 800, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z")
    accepted_4 = fx.accept_offer_as_buyer(o4["id"], ctx.buyer_id)
    assert_offer(accepted_4, status="ACCEPTED", accepted_apr_bps=800)
    assert_invoice(
        fx.read_invoice(ctx.by_number["CL-4"]["id"], ctx.buyer_id),
        status="AWARDED",
        accepted_apr_bps=800,
    )


def test_an_acceptance_deadline_exactly_equal_to_the_clock_is_already_closed():
    """The acceptance window is half-open at the top: one second before the
    deadline the acceptance succeeds, and at the deadline instant itself the same
    acceptance is rejected.

    PRD §2.7 check 16: "the logical clock is strictly before the offer's
    `acceptance_deadline`; the window is half-open, so an instant exactly equal
    to the deadline is already closed. Otherwise `ERR_ACCEPTANCE_WINDOW_CLOSED`
    (409)."

    PRD §3.5: "the acceptance window is half-open, running from the offer's
    `created_at` up to but not including its `acceptance_deadline`."

    Design: Difficulty/priority_pair_validation_conflict/acceptance_window_beats_tightened_apr_ceiling
    """
    ctx = _ceiling_ctx()
    inside = _name(ctx, "CL-1", 900, "2026-08-10T00:00:00Z", "2026-08-06T00:00:00Z")
    at_the_edge = _name(ctx, "CL-2", 900, "2026-08-10T00:00:00Z", "2026-08-06T00:00:00Z")

    fx.set_clock("2026-08-05T23:59:59Z")
    accepted = fx.accept_offer_as_buyer(inside["id"], ctx.buyer_id)
    assert_offer(accepted, status="ACCEPTED", accepted_apr_bps=900)
    assert accepted["accepted_at"].startswith("2026-08-05T23:59:59"), (
        "accepted_at is stamped from the logical clock, got {}".format(
            accepted["accepted_at"]
        )
    )

    fx.set_clock("2026-08-06T00:00:00Z")
    closed = api_client.accept_offer(
        at_the_edge["id"], make_buyer_admin_headers(ctx.buyer_id)
    )
    validate_error(closed, ERR_ACCEPTANCE_WINDOW_CLOSED, 409)
    assert_offer(
        fx.read_offer(at_the_edge["id"], ctx.buyer_id),
        status="NAMED",
        version=at_the_edge["version"],
        accepted_apr_bps=0,
    )
    assert_invoice(
        fx.read_invoice(ctx.by_number["CL-2"]["id"], ctx.buyer_id), status="OFFERED"
    )
