"""One request breaking several rules at once reports exactly one of them.

Each ladder here is peeled a rung at a time, so the loser is observed in
isolation before it is buried by the winner.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST,
    CLERK,
    OFFICER,
    Channel,
    IntakeStatus,
    InvoiceStatus,
    OfferStatus,
    RetailerStatus,
    SettlementStatus,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_money,
    assert_page,
    assert_sweep_counters,
    factories as f,
)


def _standard_market(build):
    """The contract-rate issuer and the STANDARD, NET_30 retailer they settle."""
    return build.market(
        gs1_company_prefix="038000",
        handling_fee_policy="CONTRACT_RATE",
        dispute_window_days=45,
        channel_capability="BOTH",
        payment_terms="NET_30",
        base_fee_tier="STANDARD",
        fraud_scoring_mode="ROLLING_WINDOW",
        offer_code="SOUP50",
        face_value_cents=50,
        handling_fee_cents=7,
        expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans",
        max_redemptions=100000,
        purchase_requirement_units=2,
        digital_enabled=False,
        clip_validity_days=14,
    )


@pytest.fixture
def issued_invoice(build):
    """One ISSUED invoice of 116 cents over a single scheduled statement."""
    market = _standard_market(build)
    for ref in ("POS-H1", "POS-H2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       "2026-07-05", pos_transaction_ref=ref, claimed_units=1)
        for ref in ("POS-H1", "POS-H2")
    ])
    build.finalize(lot["id"])
    statement = build.issue_statement(submission["id"])
    build.schedule(statement["id"])
    invoice = build.invoice(market["manufacturer_id"], "2026-07-01",
                           "2026-07-31", [statement["id"]])
    return {"market": market, "invoice": invoice, "invoice_id": invoice["id"],
            "manufacturer_id": market["manufacturer_id"],
            "mfr_headers": market["mfr_headers"]}


def test_01_overfunding_an_issued_invoice_reports_the_money_problem(
        api, issued_invoice):
    """With only the ceiling broken, 500 against 116 is the fiscal refusal.

    "The invoice must be in `ISSUED` or `SHORT_FUNDED`, and the wire's
    `amount_cents` — a positive integer — must not push `funded_amount_cents` past
    `billed_total_cents`; overfunding is refused with
    `ERR_FUNDING_EXCEEDS_BILLED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_invoice_fund
    """
    assert_money(issued_invoice["invoice"], "billed_total_cents", 116)

    refused = api.fund_invoice(issued_invoice["invoice_id"], 500,
                               issued_invoice["mfr_headers"])
    validate_error(refused, err.ERR_FUNDING_EXCEEDS_BILLED)

    invoice = validate_success(
        api.get_invoice(issued_invoice["invoice_id"], OFFICER))
    assert_fields(invoice, {"status": InvoiceStatus.ISSUED})
    assert_money(invoice, "funded_amount_cents", 0)


def test_02_overfunding_a_funded_invoice_reports_the_state_problem_instead(
        api, build, issued_invoice):
    """The same 500 cents now returns 409, because the state check outranks it.

    "Because that arithmetic check sits below the state check in the ladder of
    §2.11, an attempt to overfund an already-`RECONCILED` invoice reports the
    state problem, not the amount problem."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_invoice_fund
    """
    funded = build.fund(issued_invoice["invoice"], 116)
    assert_fields(funded, {"status": InvoiceStatus.FUNDED})
    assert_money(funded, "funded_amount_cents", 116)
    assert_money(funded, "funding_shortfall_cents", 0)

    refused = api.fund_invoice(issued_invoice["invoice_id"], 500,
                               issued_invoice["mfr_headers"])
    validate_error(refused, err.ERR_INVALID_STATE_TRANSITION)

    invoice = validate_success(
        api.get_invoice(issued_invoice["invoice_id"], OFFICER))
    assert_money(invoice, "funded_amount_cents", 116)

    manufacturer = validate_success(
        api.get_manufacturer(issued_invoice["manufacturer_id"], OFFICER))
    assert_manufacturer_ledger(manufacturer, funded_total=116,
                               disbursed_total=0)


@pytest.fixture
def two_lapsed_offers(build, api):
    """Two offers of one issuer past grace, one EXPIRED and one still REGISTERED.

    A second issuer exists purely to be the wrong owner, and the submission is
    parked at COUNT_VERIFIED so every sort attempt clears the state gate.
    """
    mfr_a = build.manufacturer(gs1_company_prefix="038000",
                               legal_name="Kellwood Foods",
                               handling_fee_policy="CONTRACT_RATE",
                               dispute_window_days=45)
    mfr_b = build.manufacturer(gs1_company_prefix="072250",
                               legal_name="Thrift Beverage",
                               handling_fee_policy="TIERED_RATE",
                               dispute_window_days=30)
    retailer = build.retailer(legal_name="Northgate Markets",
                              channel_capability="BOTH", payment_terms="NET_30",
                              base_fee_tier="STANDARD",
                              fraud_scoring_mode="ROLLING_WINDOW")
    terms = {"face_value_cents": 50, "handling_fee_cents": 7,
             "expiration_date": "2026-08-10",
             "redemption_instructions": "Save 50c on two cans",
             "max_redemptions": 100000, "purchase_requirement_units": 2,
             "redemption_grace_days": 5, "digital_enabled": False,
             "clip_validity_days": 14}
    offer_p1 = build.active_offer(mfr_a["id"], offer_code="SOUP50", **terms)
    offer_p2 = build.offer(mfr_a["id"], offer_code="SOUP50X", **terms)
    build.register(offer_p2)

    submission = build.verified_submission(retailer["id"], 2, "2026-07-01",
                                           "2026-07-31")
    sweep = validate_success(api.set_clock("2026-08-16T00:00:00Z"))
    return {"manufacturer_a_id": mfr_a["id"], "manufacturer_b_id": mfr_b["id"],
            "offer_p1_id": offer_p1["id"], "offer_p2_id": offer_p2["id"],
            "submission_id": submission["id"], "sweep": sweep}


def test_03_the_wrong_issuer_id_outranks_both_later_rungs(api, two_lapsed_offers):
    """A never-activated offer past grace still reports the referential problem.

    "The submission must be `COUNT_VERIFIED`; the retailer must not be
    `SUSPENDED`; the offer's issuer must not be `SUSPENDED`; the supplied
    `manufacturer_id` must be exactly the offer's own issuer, or the bucket is
    refused with `ERR_OFFER_MANUFACTURER_MISMATCH`; the offer must be `ACTIVE` or
    `EXPIRED`, or the bucket is refused with `ERR_OFFER_NOT_CLEARABLE`; and the
    offer must still be inside its redemption window, meaning the clock's calendar
    date is on or before the offer's `expiration_date` plus its
    `redemption_grace_days`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_clearability_beats_grace_on_lot_sort
    """
    assert_sweep_counters(two_lapsed_offers["sweep"], "2026-08-16T00:00:00Z",
                          expired_offer_count=1, expired_clip_count=0,
                          withdrawn_dispute_count=0)
    lapsed = validate_success(
        api.get_offer(two_lapsed_offers["offer_p1_id"], ANALYST))
    assert_fields(lapsed, {"status": OfferStatus.EXPIRED})
    never_live = validate_success(
        api.get_offer(two_lapsed_offers["offer_p2_id"], ANALYST))
    assert_fields(never_live, {"status": OfferStatus.REGISTERED})

    refused = api.create_lot(
        two_lapsed_offers["submission_id"],
        f.lot_payload(two_lapsed_offers["offer_p2_id"],
                      two_lapsed_offers["manufacturer_b_id"], 2), CLERK)
    validate_error(refused, err.ERR_OFFER_MANUFACTURER_MISMATCH)


def test_04_the_unclearable_offer_outranks_the_grace_window(
        api, two_lapsed_offers):
    """Naming the right issuer exposes the clearability rung underneath.

    "On lot creation, the offer's status must be `ACTIVE` or `EXPIRED` — a
    `DRAFT`, `REGISTERED` or `WITHDRAWN` offer is not clearable — otherwise
    `ERR_OFFER_NOT_CLEARABLE` (422); because this sits above the grace-window
    check at level 20, a lot sorted against a withdrawn offer past its grace
    period reports the offer problem, not the date problem."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_clearability_beats_grace_on_lot_sort
    """
    refused = api.create_lot(
        two_lapsed_offers["submission_id"],
        f.lot_payload(two_lapsed_offers["offer_p2_id"],
                      two_lapsed_offers["manufacturer_a_id"], 2), CLERK)
    validate_error(refused, err.ERR_OFFER_NOT_CLEARABLE)


def test_05_the_grace_window_is_the_last_rung_standing(api, two_lapsed_offers):
    """With owner and clearability satisfied, only the date remains to refuse.

    "That last comparison is inclusive on the final grace day: a lot sorted
    exactly on the last grace day is accepted and one day later is refused with
    `ERR_SUBMISSION_PAST_GRACE`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_clearability_beats_grace_on_lot_sort
    """
    refused = api.create_lot(
        two_lapsed_offers["submission_id"],
        f.lot_payload(two_lapsed_offers["offer_p1_id"],
                      two_lapsed_offers["manufacturer_a_id"], 2), CLERK)
    validate_error(refused, err.ERR_SUBMISSION_PAST_GRACE)

    submission = validate_success(
        api.get_submission(two_lapsed_offers["submission_id"], CLERK))
    assert_fields(submission, {"sorted_lot_count": 0,
                               "intake_status": IntakeStatus.COUNT_VERIFIED})


@pytest.fixture
def suspended_mail_only(build):
    """A MAIL_ONLY retailer, suspended, already holding one July submission.

    The open submission covers the whole of July, so a second submission on the
    same dates collides once the suspension is lifted.
    """
    market = build.market(
        gs1_company_prefix="038000",
        handling_fee_policy="CONTRACT_RATE",
        dispute_window_days=45,
        channel_capability="MAIL_ONLY",
        payment_terms="NET_30",
        base_fee_tier="STANDARD",
        fraud_scoring_mode="ROLLING_WINDOW",
        offer_code="SOUP50",
        face_value_cents=50,
        handling_fee_cents=7,
        expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans",
        max_redemptions=100000,
        purchase_requirement_units=2,
        digital_enabled=False,
        clip_validity_days=14,
    )
    held = build.submission(market["retailer_id"], 2, "2026-07-01",
                            "2026-07-31")
    build.suspend_retailer(market["retailer_id"], "Fraud review pending")
    return {"market": market, "retailer_id": market["retailer_id"],
            "open_submission": held}


def test_06_the_suspension_answers_before_the_dates_or_the_channel_are_read(
        api, suspended_mail_only):
    """An electronic submission overlapping July reports only the suspension.

    "While a retailer is `SUSPENDED`, seven operations are blocked with
    `ERR_RETAILER_SUSPENDED`: opening a submission, verifying its count, sorting
    it into lots, capturing images into a lot, finalizing a lot, filing a dispute
    and reporting a digital redemption."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_beats_capability_on_submission_intake
    """
    assert_fields(suspended_mail_only["open_submission"],
                  {"intake_status": IntakeStatus.RECEIVED})

    refused = api.create_submission(
        f.submission_payload(suspended_mail_only["retailer_id"], 2,
                             "2026-07-10", "2026-07-20",
                             channel=Channel.ELECTRONIC), CLERK)
    validate_error(refused, err.ERR_RETAILER_SUSPENDED)


def test_07_reinstatement_uncovers_the_overlap_rung_below_the_suspension(
        api, build, suspended_mail_only):
    """The identical request now reports the July window it collides with.

    "Reinstatement, also taking a `reason`, is available only from `SUSPENDED`:
    the retailer returns to `ACTIVE` and its `handling_fee_tier` is restored to
    `base_fee_tier`, again leaving `fraud_score` untouched — which means the very
    next rescore may push it straight back to `WATCHLIST` or `SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_beats_capability_on_submission_intake
    """
    reinstated = build.reinstate_retailer(suspended_mail_only["retailer_id"],
                                          "Review closed with no finding")
    assert_fields(reinstated, {"status": RetailerStatus.ACTIVE,
                               "handling_fee_tier": "STANDARD"})

    refused = api.create_submission(
        f.submission_payload(suspended_mail_only["retailer_id"], 2,
                             "2026-07-10", "2026-07-20",
                             channel=Channel.ELECTRONIC), CLERK)
    validate_error(refused, err.ERR_POSTMARK_WINDOW_OVERLAP)


def test_08_an_adjacent_window_leaves_only_the_channel_to_refuse(
        api, build, suspended_mail_only):
    """Starting exactly where July ends is legal, so capability answers instead.

    "Because the interval is half-open, exact adjacency is legal — an existing
    window ending 2026-07-31 and a new window starting 2026-07-31 do not overlap
    — while any genuine overlap is refused with `ERR_POSTMARK_WINDOW_OVERLAP`."

    "The chosen channel must be permitted by the retailer's
    `channel_capability`: a `MAIL` submission requires `MAIL_ONLY` or `BOTH`, an
    `ELECTRONIC` submission requires `ELECTRONIC_ONLY` or `BOTH`, and anything
    else is refused with `ERR_CHANNEL_NOT_SUPPORTED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_beats_capability_on_submission_intake
    """
    build.reinstate_retailer(suspended_mail_only["retailer_id"],
                             "Review closed with no finding")

    refused = api.create_submission(
        f.submission_payload(suspended_mail_only["retailer_id"], 2,
                             "2026-07-31", "2026-08-10",
                             channel=Channel.ELECTRONIC), CLERK)
    validate_error(refused, err.ERR_CHANNEL_NOT_SUPPORTED)


def test_09_the_contracted_channel_on_the_adjacent_window_is_accepted(
        api, build, suspended_mail_only):
    """With every rung satisfied the mail shipment opens on both dimensions.

    "The two dimensions never read one another during intake — verifying a count
    leaves `settlement_status` entirely untouched — and a fully finished
    submission is one that has reached `CLOSED` on the first dimension and `PAID`
    on the second."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_beats_capability_on_submission_intake
    """
    retailer_id = suspended_mail_only["retailer_id"]
    build.reinstate_retailer(retailer_id, "Review closed with no finding")

    created = validate_success(api.create_submission(
        f.submission_payload(retailer_id, 2, "2026-07-31", "2026-08-10",
                             channel=Channel.MAIL), CLERK), 201)
    assert_fields(created, {
        "channel": Channel.MAIL,
        "intake_status": IntakeStatus.RECEIVED,
        "settlement_status": SettlementStatus.PENDING,
    })

    rows, meta = validate_paginated(
        api.list_submissions(CLERK, retailer_id=retailer_id))
    assert len(rows) == 2, (
        "the retailer holds the July shipment and the new August one"
    )
    assert_page(meta, total_count=2, limit=10, offset=0, has_more=False)
