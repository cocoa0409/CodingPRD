"""Depth tests for the ``cross_entity_state_dependency`` rule.

Each scenario here turns on the state of an entity the failing request never
names. A ``SELF_THEN_FUNDER`` reservation depends on a ``Funder`` row that the
request body does not mention, and pausing that funder empties the waterfall's
eligibility pool so the error reported is the one belonging to the *last*
candidate rather than the first. A discount offer's fate depends entirely on its
parent auction session: the byte-identical naming body is refused, accepted and
then frozen purely by where the clock has driven the session, and after an
operator settlement close the same defective state is owned by two different
errors depending on which endpoint is called. And a reserved early payment
depends on the supplier's compliance axis mid-flight: a hold placed after the
reservation freezes execution without touching the encumbrance.
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
    ERR_ALREADY_TERMINAL,
    ERR_BUYER_CREDIT_LIMIT_EXCEEDED,
    ERR_NO_ELIGIBLE_FUNDER,
    ERR_SESSION_NOT_LIVE,
    ERR_SUPPLIER_SANCTIONS_HOLD,
)
from test_helpers.assertions import (
    assert_buyer,
    assert_cash_breakdown,
    assert_funder_capital_conserved,
    assert_invoice,
    assert_offer,
    assert_payment,
    assert_payment_axes,
    assert_supplier_axes,
)
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
    make_supplier_headers,
)

# ─── Setup 1: the waterfall with one funder ─────────────────────

WATERFALL_PROGRAM = {
    "name": "Waterfall Programme",
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_THEN_FUNDER",
}

# 1000000 cents at 900 bps over the 30 days from 2026-08-05 to 2026-09-04.
WF_FACE = 1_000_000
WF_DISCOUNT = 7_500
WF_PRE_FEE_NET = 992_500
WF_FEE = 4_466            # 45 bps on a pre-fee net below 5000000, spread 0
WF_NET = 988_034
WF_COMMITTED = 60_000_000


def _waterfall_ctx():
    """A SELF_THEN_FUNDER programme whose buyer has a 1000-cent credit limit and
    whose single ACTIVE funder can comfortably carry the payment, with the offer
    already ACCEPTED at clock 2026-08-02."""
    return fx.build_accepted_offer(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Waterfall Fallback Buyer",
            "credit_limit_cents": 1_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(WATERFALL_PROGRAM),
        supplier_overrides={
            "legal_name": "Waterfall Supply Co",
            "remittance_email": "ar@waterfall.example",
        },
        funders=[
            {
                "legal_name": "Only Funder Available",
                "capital_limit_cents": WF_COMMITTED,
                "min_apr_bps": 500,
                "fee_spread_bps": 0,
                "max_single_invoice_cents": 5_000_000,
                "committed_amount_cents": WF_COMMITTED,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            }
        ],
        face_cents=WF_FACE,
        net_due_date="2026-09-04T00:00:00Z",
        offered_apr_bps=900,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )


def _set_participation(funder_id, action):
    return validate_success(
        api_client.set_funder_participation(
            funder_id, f.funder_participation_payload(action), PLATFORM_OPS_HEADERS
        )
    )


def _reserve(ctx):
    return api_client.create_early_payment(
        f.early_payment_payload(ctx.offer_id, ctx.offer_version),
        make_buyer_treasury_headers(ctx.buyer_id),
    )


def _payments_of_offer(ctx):
    return validate_paginated(
        api_client.list_early_payments(
            make_buyer_treasury_headers(ctx.buyer_id), offer_id=ctx.offer_id
        )
    )


def test_pausing_the_only_funder_reports_the_last_candidates_error_not_the_first():
    """The buyer's 1000-cent limit loses the first hop of the SELF_THEN_FUNDER
    waterfall, so the answer belongs to the funder hop — and because the only
    funder is `PAUSED` the eligibility pool is empty and the reservation reports
    `ERR_NO_ELIGIBLE_FUNDER` (422) rather than the credit error of the candidate
    that actually failed first.

    PRD §3.7: "When the waterfall exhausts its candidates without a payer, the
    error reported is the one belonging to the **last** candidate in the order,
    never the first. If the last candidate was a third-party funder, the answer
    is `ERR_NO_ELIGIBLE_FUNDER` (HTTP 422)."

    PRD §3.7: "a `SELF_THEN_FUNDER` programme whose buyer has insufficient credit
    headroom and which then finds no eligible funder reports
    `ERR_NO_ELIGIBLE_FUNDER`, not the credit-limit error, because the funder was
    the last candidate tried."

    PRD §3.7: "`PAUSE` moves `ACTIVE → PAUSED` and requires the funder to be
    `ACTIVE`; a paused funder drops out of the selector's eligibility filter but
    its `encumbered_capital_cents` is left untouched"

    PRD §3.7: "a funder passes it only if all four of these hold — its `status`
    is `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/paused_funder_makes_the_waterfall_report_no_eligible_funder
    """
    ctx = _waterfall_ctx()
    funder_id = ctx.funder_id

    before_pause = fx.read_funder(funder_id)
    assert before_pause["status"] == "ACTIVE", (
        "the committed funder starts ACTIVE, got {}".format(before_pause["status"])
    )
    assert before_pause["available_capital_cents"] == WF_COMMITTED, (
        "an unencumbered tranche of {} leaves all of it available, got {}".format(
            WF_COMMITTED, before_pause["available_capital_cents"]
        )
    )

    paused = _set_participation(funder_id, "PAUSE")
    assert paused["status"] == "PAUSED", (
        "PAUSE must drive ACTIVE -> PAUSED, got {}".format(paused["status"])
    )
    assert paused["version"] == before_pause["version"] + 1, (
        "all three participation actions increment the funder's version by one"
    )

    refused = _reserve(ctx)
    body = validate_error(refused, ERR_NO_ELIGIBLE_FUNDER, 422)
    assert body["error_id"] != ERR_BUYER_CREDIT_LIMIT_EXCEEDED, (
        "the first candidate's credit error must never surface when a funder was "
        "the last candidate tried"
    )

    # No row was created, and neither ledger moved.
    rows, meta = _payments_of_offer(ctx)
    assert meta["total_count"] == 0, (
        "a refused waterfall creates no EarlyPayment, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert rows == [], "the offer's payment collection must still be empty"

    buyer = validate_success(
        api_client.get_buyer(ctx.buyer_id, make_buyer_admin_headers(ctx.buyer_id))
    )
    assert_buyer(buyer, credit_used_cents=0, credit_limit_cents=1_000)
    assert buyer["credit_used_cents"] != WF_NET, (
        "the self-funding hop was rejected, so no credit may be encumbered"
    )

    funder = fx.read_funder(funder_id)
    assert funder["encumbered_capital_cents"] == 0, (
        "a refused reservation encumbers nothing, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert_funder_capital_conserved(funder, WF_COMMITTED)

    # The offer itself is untouched and still awaiting its cash leg.
    assert_offer(fx.read_offer(ctx.offer_id, ctx.buyer_id), status="ACCEPTED")


def test_resuming_the_funder_lets_the_identical_reservation_land_on_the_second_hop():
    """`RESUME` restores the eligibility pool, and the byte-identical body that
    just returned 422 now succeeds on the *second* hop: `funding_source` is
    `FUNDER`, the winner's identifier is stamped on the row, and the encumbrance
    lands on the funder rather than on the buyer whose limit is still 1000 cents.

    PRD §3.7: "`RESUME` moves `PAUSED → ACTIVE` and requires the funder to be
    `PAUSED`; this edge is what makes the funder lifecycle cyclic."

    PRD §3.7: "The candidates are tried strictly left to right, and the first one
    that can pay wins." and "A third-party funder can pay when the selector
    described below returns a winner, in which case `funding_source` is set to
    `FUNDER` and `funder_id` is set to the winner's identifier."

    PRD §3.8: "the tier rate is 45 basis points when the pre-fee net is below
    5000000 cents"

    PRD §3.8: "it is the sum of `net_payment_cents` over the buyer's early
    payments whose `funding_source` is `BUYER_SELF` and whose `funding_status` is
    `RESERVED` or `DEPLOYED`"

    Design: Difficulty/cross_entity_state_dependency/paused_funder_makes_the_waterfall_report_no_eligible_funder
    """
    ctx = _waterfall_ctx()
    funder_id = ctx.funder_id

    _set_participation(funder_id, "PAUSE")
    validate_error(_reserve(ctx), ERR_NO_ELIGIBLE_FUNDER, 422)

    resumed = _set_participation(funder_id, "RESUME")
    assert resumed["status"] == "ACTIVE", (
        "RESUME must drive PAUSED -> ACTIVE, got {}".format(resumed["status"])
    )
    assert resumed["status"] != "PAUSED", "the funder lifecycle is cyclic here"

    payment = validate_success(_reserve(ctx), 201)
    assert_payment(
        payment,
        funding_source="FUNDER",
        funder_id=funder_id,
        accepted_apr_bps=900,
        face_covered_cents=WF_FACE,
    )
    assert payment["funding_source"] != "BUYER_SELF", (
        "the buyer's 1000-cent limit still loses the first hop"
    )
    assert_payment_axes(
        payment,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert_cash_breakdown(
        payment,
        days_early=30,
        discount_amount_cents=WF_DISCOUNT,
        funder_fee_cents=WF_FEE,
        net_payment_cents=WF_NET,
    )

    rows, meta = _payments_of_offer(ctx)
    assert meta["total_count"] == 1, (
        "exactly one payment now stands on the offer, got {}".format(
            meta["total_count"]
        )
    )
    assert rows[0]["id"] == payment["id"]

    funder = fx.read_funder(funder_id)
    assert funder["encumbered_capital_cents"] == WF_NET, (
        "the funder is encumbered by the net payment, got {}".format(
            funder["encumbered_capital_cents"]
        )
    )
    assert funder["available_capital_cents"] == WF_COMMITTED - WF_NET, (
        "available capital should fall to {}, got {}".format(
            WF_COMMITTED - WF_NET, funder["available_capital_cents"]
        )
    )
    assert funder["encumbered_capital_cents"] != WF_PRE_FEE_NET, (
        "the encumbrance stands at the net payment, not the pre-fee net"
    )
    assert_funder_capital_conserved(funder, WF_COMMITTED)

    buyer = validate_success(
        api_client.get_buyer(ctx.buyer_id, make_buyer_admin_headers(ctx.buyer_id))
    )
    assert_buyer(buyer, credit_used_cents=0)
    assert buyer["credit_used_cents"] != WF_NET, (
        "credit_used_cents counts BUYER_SELF payments only"
    )


# ─── Setup 2: one offer body, three session states ──────────────

GATE_PROGRAM = {
    "name": "Session Gate Programme",
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_ONLY",
}

GATE_FACE = 200_000


def _session_gate_ctx():
    """An OPEN SELF_ONLY programme with one ELIGIBLE invoice and a session
    scheduled for 2026-08-10..2026-08-20 while the clock reads 2026-08-05."""
    ctx = fx.build_base(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Session Gate Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(GATE_PROGRAM),
        supplier_overrides={
            "legal_name": "Session Gate Supply",
            "remittance_email": "ar@sessiongate.example",
        },
        session_window=("2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"),
    )
    fx.ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date="2026-07-22T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=GATE_FACE,
            )
        ],
    )
    fx.set_clock("2026-08-05T00:00:00Z")
    ctx.clock = "2026-08-05T00:00:00Z"
    fx.load_invoices(ctx)
    ctx.offer_body = f.offer_payload(
        ctx.invoice_id,
        ctx.session_id,
        ctx.invoice_version,
        offered_apr_bps=900,
        requested_pay_date="2026-08-12T00:00:00Z",
        acceptance_deadline="2026-08-19T00:00:00Z",
    )
    return ctx


def _name_it(ctx):
    return api_client.create_offer(
        ctx.offer_body, make_supplier_headers(ctx.supplier_id)
    )


def _sessions(ctx):
    rows, _meta = validate_paginated(
        api_client.list_program_sessions(
            ctx.program_id, make_buyer_admin_headers(ctx.buyer_id)
        )
    )
    return rows


def _session_status(ctx):
    rows = _sessions(ctx)
    match = [row for row in rows if row["id"] == ctx.session_id]
    assert len(match) == 1, "the programme's session collection must list it once"
    return match[0]


def test_the_same_naming_body_is_refused_before_opens_at_and_accepted_at_it():
    """At 2026-08-05 the parent session is still `SCHEDULED`, so naming is refused
    with `ERR_SESSION_NOT_LIVE`; moving the clock to exactly `opens_at` opens the
    session — the inclusive edge of the half-open window — and the byte-identical
    body then lands as `NAMED`.

    PRD §2.7 check 9: "the auction session referenced by the request holds
    `status` `LIVE` and the logical clock lies inside the window that starts at
    `opens_at` inclusive and ends at `closes_at` exclusive. Otherwise
    `ERR_SESSION_NOT_LIVE` (409)."

    PRD §3.5: "Step two opens and closes sessions: every `SCHEDULED` session
    whose `opens_at` has arrived becomes `LIVE`"

    PRD §3.5: "A session becomes `LIVE` only when the new clock instant is at or
    after its `opens_at` and strictly before its `closes_at`, and only while the
    governing programme is `OPEN` or `PAUSED`."

    PRD §3.6: "Naming a rate on an invoice that is already `ELIGIBLE` moves it
    `ELIGIBLE → OFFERED` and increments the invoice's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/session_lifecycle_gates_offer_naming_and_countering_differently
    """
    ctx = _session_gate_ctx()

    scheduled = _session_status(ctx)
    assert scheduled["status"] == "SCHEDULED", (
        "a window whose opens_at is still in the future stays SCHEDULED, got {}".format(
            scheduled["status"]
        )
    )
    assert scheduled["status"] != "LIVE", (
        "the clock at 2026-08-05 is before opens_at 2026-08-10"
    )
    assert scheduled["named_offer_count"] == 0

    too_early = validate_error(_name_it(ctx), ERR_SESSION_NOT_LIVE, 409)
    assert too_early["error_id"] != ERR_ALREADY_TERMINAL, (
        "a SCHEDULED session is not terminal — the live-window rule owns this"
    )

    # Nothing was written: the invoice keeps its status and its version.
    untouched = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(
        untouched,
        status="ELIGIBLE",
        face_amount_cents=GATE_FACE,
        version=ctx.invoice_version,
    )
    offers, offers_meta = validate_paginated(
        api_client.list_offers(
            make_buyer_admin_headers(ctx.buyer_id), invoice_id=ctx.invoice_id
        )
    )
    assert offers_meta["total_count"] == 0, (
        "the refused naming must not have created an offer, got {}".format(
            offers_meta["total_count"]
        )
    )
    assert offers == []

    # The clock lands exactly on opens_at, the inclusive edge.
    fx.set_clock("2026-08-10T00:00:00Z")
    ctx.clock = "2026-08-10T00:00:00Z"
    live = _session_status(ctx)
    assert live["status"] == "LIVE", (
        "an instant exactly equal to opens_at is inside the window, got {}".format(
            live["status"]
        )
    )
    assert live["status"] != "SCHEDULED", "step two of the sweep opened the window"

    offer = validate_success(_name_it(ctx), 201)
    assert_offer(
        offer,
        status="NAMED",
        offered_apr_bps=900,
        session_id=ctx.session_id,
        invoice_id=ctx.invoice_id,
        version=1,
    )
    assert offer["status"] != "COUNTERED", "a supplier-named rate opens in NAMED"

    offered = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)
    assert_invoice(offered, status="OFFERED", version=ctx.invoice_version + 1)
    assert offered["status"] != "ELIGIBLE", (
        "the accepted naming moved the invoice ELIGIBLE -> OFFERED"
    )
    assert _session_status(ctx)["named_offer_count"] == 1, (
        "named_offer_count tracks offers in NAMED, COUNTERED or ACCEPTED"
    )


def test_a_settlement_close_splits_the_error_owner_between_counter_and_accept():
    """One operator `SETTLE` close leaves a single defective state — an `EXPIRED`
    offer inside a `CLOSED` session — yet two endpoints report two different
    errors: `counter` is listed under the live-session rule at priority 9 and
    reports `ERR_SESSION_NOT_LIVE`, while `accept` is not, so the terminal rule at
    priority 10 owns it and reports `ERR_ALREADY_TERMINAL`.

    PRD §3.5: "With `mode` set to `SETTLE`, the session must currently be `LIVE`,
    and it moves `LIVE → CLOSED` with exactly the same effects as the
    clock-driven close: the clearing rate is written and outstanding offers
    expire."

    PRD §3.5: "When no offer on the session ever reached `ACCEPTED`, the clearing
    rate is exactly 0 rather than null. Closing also cascades: every `NAMED` or
    `COUNTERED` offer on the session becomes `EXPIRED`, in ascending `created_at`
    order, and the session's `version` increments."

    PRD §2.7 check 9: "Applies to `POST /discount-offers`,
    `POST /discount-offers/{id}/counter` and `POST /discount-offers/{id}/rename`."

    PRD §2.7 check 10: "Terminal for this purpose means: a discount offer in
    `ACCEPTED`, `EXPIRED`, `SUPERSEDED` or `VOIDED_BY_SUPPRESSION` ... Otherwise
    `ERR_ALREADY_TERMINAL` (409)."

    Design: Difficulty/cross_entity_state_dependency/session_lifecycle_gates_offer_naming_and_countering_differently
    """
    ctx = _session_gate_ctx()
    fx.set_clock("2026-08-10T00:00:00Z")
    ctx.clock = "2026-08-10T00:00:00Z"
    offer = validate_success(_name_it(ctx), 201)
    offer_id = offer["id"]
    live = _session_status(ctx)
    assert live["status"] == "LIVE"

    closed = fx.close_session(ctx.session_id, ctx.buyer_id, mode="SETTLE")
    assert closed["status"] == "CLOSED", (
        "SETTLE drives LIVE -> CLOSED, got {}".format(closed["status"])
    )
    assert closed["clearing_apr_bps"] == 0, (
        "with no ACCEPTED offer at the instant of close the clearing rate is "
        "exactly 0, got {}".format(closed["clearing_apr_bps"])
    )
    assert closed["clearing_apr_bps"] != 900, (
        "a merely NAMED offer is excluded from the face-weighted mean"
    )
    assert closed["clearing_apr_bps"] is not None, "0 rather than null"
    assert closed["version"] == live["version"] + 1, (
        "closing increments the session's version by one"
    )

    expired = fx.read_offer(offer_id, ctx.buyer_id)
    assert_offer(expired, status="EXPIRED", version=offer["version"] + 1)
    assert expired["status"] != "NAMED", (
        "the close cascade expired the outstanding offer"
    )

    # Priority 9 owns the endpoint that is listed under it.
    countered = api_client.counter_offer(
        offer_id, f.counter_payload(1_000), make_buyer_admin_headers(ctx.buyer_id)
    )
    counter_body = validate_error(countered, ERR_SESSION_NOT_LIVE, 409)
    assert counter_body["error_id"] != ERR_ALREADY_TERMINAL, (
        "counter is inside rule 9's applies_to, and 9 precedes 10"
    )

    # Accept is absent from rule 9's applies_to, so the terminal rule answers.
    accepted = api_client.accept_offer(offer_id, make_buyer_admin_headers(ctx.buyer_id))
    accept_body = validate_error(accepted, ERR_ALREADY_TERMINAL, 409)
    assert accept_body["error_id"] != ERR_SESSION_NOT_LIVE, (
        "accept is not listed under the live-session rule"
    )

    # Neither refusal moved the offer, the invoice or the cash ledger.
    still_expired = fx.read_offer(offer_id, ctx.buyer_id)
    assert_offer(
        still_expired,
        status="EXPIRED",
        version=expired["version"],
        counter_apr_bps=None,
        counter_round=0,
    )
    assert_invoice(
        fx.read_invoice(ctx.invoice_id, ctx.buyer_id),
        status="OFFERED",
        accepted_apr_bps=0,
        face_covered_cents=0,
    )
    _rows, meta = validate_paginated(
        api_client.list_early_payments(
            make_buyer_treasury_headers(ctx.buyer_id), offer_id=offer_id
        )
    )
    assert meta["total_count"] == 0, (
        "no cash leg may exist for an offer that was never accepted, got {}".format(
            meta["total_count"]
        )
    )


# ─── Setup 3: a hold placed after the reservation ───────────────

MID_FLIGHT_PROGRAM = {
    "name": "Mid Flight Programme",
    "program_type": "SUPPLIER_NAMED",
    "max_acceptable_apr_bps": 1200,
    "min_days_early": 5,
    "concentration_cap_pct": 100.00,
    "funding_policy": "SELF_ONLY",
}

# 100000 cents at 800 bps over the 56 days from 2026-08-05 to 2026-09-30.
MF_FACE = 100_000
MF_DISCOUNT = 1_244
MF_NET = 98_756


def _mid_flight_ctx():
    """A self-funded EarlyPayment already `RESERVED` at clock 2026-08-02, with the
    supplier's compliance axis then flipped and the clock moved to the intended
    execution date."""
    ctx = fx.build_reserved_payment(
        clock="2026-08-01T00:00:00Z",
        buyer_overrides={
            "legal_name": "Mid Flight Buyer",
            "credit_limit_cents": 100_000_000,
            "self_funding_enabled": True,
        },
        program_overrides=dict(MID_FLIGHT_PROGRAM),
        supplier_overrides={
            "legal_name": "Mid Flight Supply",
            "remittance_email": "ar@midflight.example",
            "identity_score": 93,
        },
        face_cents=MF_FACE,
        net_due_date="2026-09-30T00:00:00Z",
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
    )
    ctx.invoice_number = fx.read_invoice(ctx.invoice_id, ctx.buyer_id)["invoice_number"]
    return ctx


def _execute(ctx):
    return api_client.execute_early_payment(
        ctx.payment_id, make_buyer_treasury_headers(ctx.buyer_id)
    )


def _advices(ctx):
    return validate_paginated(
        api_client.list_remittance_advices(
            ctx.payment_id, make_buyer_treasury_headers(ctx.buyer_id)
        )
    )


def _read_buyer(ctx):
    return validate_success(
        api_client.get_buyer(ctx.buyer_id, make_buyer_admin_headers(ctx.buyer_id))
    )


def test_a_hold_placed_after_reservation_freezes_execution_without_releasing_credit():
    """The hold arrives while the payment is already `RESERVED` and the buyer's
    credit is already encumbered. Execution is refused with
    `ERR_SUPPLIER_SANCTIONS_HOLD` (403) — the compliance cause outranking the
    payment-readiness cause that fires alongside it — and the freeze changes
    nothing: the cash axis stays `RESERVED`, `execution_date` stays null, the
    encumbrance stands and no remittance advice is written.

    PRD §2.7 check 14: "the supplier that owns the invoice has `sanctions_hold`
    false. Otherwise `ERR_SUPPLIER_SANCTIONS_HOLD` (403). Applies to eight
    operations: ... `POST /early-payments/{id}/execute`. A supplier under a
    compliance hold is necessarily also not active, so this rule and the next one
    fire together; the compliance cause is the one reported."

    PRD §3.2: "A platform operator setting `hold` to true writes `sanctions_hold`
    true and forces `onboarding_status` to `SUSPENDED`" and "The hold blocks new
    actions only: offers that already reached `ACCEPTED` and early payments
    already in `RESERVED` are not voided by it."

    PRD §3.9: "Execution is the moment cash is instructed ... It requires
    `funding_status` `RESERVED`, `settlement_status` `UNSENT`, the invoice's
    `dispute_suppressed` false, the supplier's `sanctions_hold` false"

    PRD §3.9: "Execution also produces exactly one **remittance advice**"

    Design: Difficulty/cross_entity_state_dependency/mid_flight_sanctions_hold_freezes_execution_of_a_reserved_payment
    """
    ctx = _mid_flight_ctx()
    assert_cash_breakdown(
        ctx.payment,
        days_early=56,
        discount_amount_cents=MF_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=MF_NET,
    )
    assert ctx.payment["funder_fee_cents"] == 0, (
        "a BUYER_SELF payment always carries a zero funder fee"
    )
    assert _read_buyer(ctx)["credit_used_cents"] == MF_NET, (
        "the reservation encumbers the net payment against the buyer's limit"
    )

    held = fx.set_sanctions_hold(ctx.supplier_id, True)
    assert_supplier_axes(
        held, onboarding_status="SUSPENDED", idv_status="PASSED", bank_status="VERIFIED"
    )
    assert held["sanctions_hold"] is True, "the hold flag itself must be set"
    assert held["onboarding_status"] != "ACTIVE", (
        "a held supplier is forced out of ACTIVE"
    )
    assert held["version"] == ctx.supplier["version"] + 1, (
        "either direction of the hold increments the supplier's version by one"
    )

    fx.set_clock("2026-08-05T00:00:00Z")
    ctx.clock = "2026-08-05T00:00:00Z"
    frozen = validate_error(_execute(ctx), ERR_SUPPLIER_SANCTIONS_HOLD, 403)
    assert frozen["error_id"] != "ERR_SUPPLIER_NOT_PAYMENT_READY", (
        "both rules fire together and the compliance cause is the reported one"
    )

    payment = fx.read_payment(ctx.payment_id, ctx.buyer_id)
    assert_payment_axes(
        payment,
        funding_status="RESERVED",
        settlement_status="UNSENT",
        accounting_status="UNCLASSIFIED",
    )
    assert payment["funding_status"] != "DEPLOYED", (
        "the refused execution must not move the cash axis"
    )
    assert payment["execution_date"] is None, (
        "execution_date is stamped only by a successful execute, got {}".format(
            payment["execution_date"]
        )
    )
    assert payment["value_date"] is None, (
        "value_date follows execution_date, so it is still null"
    )
    assert_payment(payment, version=ctx.payment["version"], net_payment_cents=MF_NET)

    # The reservation is not voided by the hold: the credit is still standing.
    buyer = _read_buyer(ctx)
    assert_buyer(buyer, credit_used_cents=MF_NET)
    assert buyer["credit_used_cents"] != 0, (
        "a RESERVED payment survives the hold, so its encumbrance survives too"
    )

    rows, meta = _advices(ctx)
    assert meta["total_count"] == 0, (
        "no advice exists until execution succeeds, got {}".format(
            meta["total_count"]
        )
    )
    assert rows == []


def test_lifting_the_hold_lets_the_frozen_execution_through_and_writes_one_advice():
    """Setting `hold` back to false returns the supplier to `ACTIVE` — the state
    its two satisfied axes justify — and the execution that was refused a moment
    ago now moves both axes at once, stamping the clock's date as
    `execution_date`, the two-day lag as `value_date` and producing exactly one
    remittance advice snapshotting the same net payment.

    PRD §3.2: "Setting `hold` to false requires the supplier to be in `SUSPENDED`
    and returns it to whichever state its two axes justify — to `ACTIVE` when
    `idv_status` is `PASSED` and `bank_status` is `VERIFIED`"

    PRD §3.9: "The cash axis moves `RESERVED → DEPLOYED` and, on the very same
    call, the remittance axis moves `UNSENT → REMITTED`." and "`value_date` is
    then set to `execution_date` advanced by two days."

    PRD §3.9: "It records the `early_payment_id` it belongs to and an
    `advice_number` formed as the literal concatenation of `RA-`, the invoice's
    `invoice_number`, a hyphen, and a zero-padded two-digit number equal to the
    count of remittance advices already existing on that same invoice plus one."

    PRD §3.9: "Its `delivery_status` is `SENT` when the supplier had a non-null
    `remittance_email` at the moment of execution and `BOUNCED` otherwise"

    Design: Difficulty/cross_entity_state_dependency/mid_flight_sanctions_hold_freezes_execution_of_a_reserved_payment
    """
    ctx = _mid_flight_ctx()
    fx.set_sanctions_hold(ctx.supplier_id, True)
    fx.set_clock("2026-08-05T00:00:00Z")
    ctx.clock = "2026-08-05T00:00:00Z"
    validate_error(_execute(ctx), ERR_SUPPLIER_SANCTIONS_HOLD, 403)

    lifted = fx.set_sanctions_hold(ctx.supplier_id, False)
    assert_supplier_axes(
        lifted,
        onboarding_status="ACTIVE",
        idv_status="PASSED",
        bank_status="VERIFIED",
    )
    assert lifted["sanctions_hold"] is False, "the release clears the hold flag"
    assert lifted["onboarding_status"] != "VERIFYING", (
        "both axes are satisfied, so the release returns the supplier to ACTIVE"
    )
    assert lifted["payment_ready_at"] is not None, (
        "an ACTIVE supplier carries a non-null payment_ready_at"
    )

    deployed = validate_success(_execute(ctx))
    assert_payment_axes(
        deployed,
        funding_status="DEPLOYED",
        settlement_status="REMITTED",
        accounting_status="UNCLASSIFIED",
    )
    assert deployed["funding_status"] != "RESERVED", (
        "the identical call now moves the cash axis"
    )
    assert deployed["execution_date"].startswith("2026-08-05"), (
        "execution_date is stamped from the logical clock, got {}".format(
            deployed["execution_date"]
        )
    )
    assert deployed["value_date"].startswith("2026-08-07"), (
        "value_date is execution_date advanced by two days, got {}".format(
            deployed["value_date"]
        )
    )
    # The real execution date equals the requested pay date, so the pay-date
    # recomputation is a no-op and the encumbrance delta is zero.
    assert_cash_breakdown(
        deployed,
        days_early=56,
        discount_amount_cents=MF_DISCOUNT,
        funder_fee_cents=0,
        net_payment_cents=MF_NET,
    )
    assert_payment(deployed, version=ctx.payment["version"] + 1)
    assert_buyer(_read_buyer(ctx), credit_used_cents=MF_NET)
    assert_invoice(
        fx.read_invoice(ctx.invoice_id, ctx.buyer_id),
        status="AWARDED",
        provisional_discount_cents=MF_DISCOUNT,
        final_discount_cents=0,
        face_covered_cents=MF_FACE,
    )

    rows, meta = _advices(ctx)
    assert meta["total_count"] == 1, (
        "execution produces exactly one advice, got {}".format(meta["total_count"])
    )
    advice = rows[0]
    assert advice["early_payment_id"] == ctx.payment_id
    assert advice["advice_number"] == "RA-{}-01".format(ctx.invoice_number), (
        "the first advice on an invoice is numbered 01, got {}".format(
            advice["advice_number"]
        )
    )
    assert advice["advice_number"] != "RA-{}-1".format(ctx.invoice_number), (
        "the sequence is zero-padded to two digits"
    )
    assert advice["net_paid_cents"] == MF_NET, (
        "net_paid_cents snapshots the payment's net, got {}".format(
            advice["net_paid_cents"]
        )
    )
    assert advice["gross_face_cents"] == MF_FACE
    assert advice["discount_cents"] == MF_DISCOUNT
    assert advice["fee_cents"] == 0
    assert advice["value_date"].startswith("2026-08-07"), (
        "the advice snapshots the payment's value_date, got {}".format(
            advice["value_date"]
        )
    )
    assert advice["delivery_status"] == "SENT", (
        "a supplier with a remittance_email receives a SENT advice, got {}".format(
            advice["delivery_status"]
        )
    )
    assert advice["delivery_status"] != "BOUNCED", (
        "BOUNCED is reserved for a supplier registered without a remittance address"
    )
    assert advice["supplier_legal_name"] == "Mid Flight Supply", (
        "the advice snapshots the supplier's legal name"
    )
    assert advice["supplier_account_last4"] == "4321", (
        "the advice snapshots the verified account's last four digits, got {}".format(
            advice["supplier_account_last4"]
        )
    )
