"""Codes that only fire on their own collection, their own flag, their own row.

Nine existence codes that must not collapse into one generic refusal, a clock
that refuses the instant it already holds, one flag gating two digital
endpoints, and a reversal that a single released payment locks out.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN,
    OFFICER,
    OFFICER_2,
    UNKNOWN_UUID,
    ClipStatus,
    InvoiceStatus,
    OfferStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_sweep_counters,
    databar_payload,
    factories as f,
    make_manufacturer_headers,
    make_retailer_headers,
)


def test_01_every_not_found_code_in_the_catalogue_is_reachable(api):
    """Nine collections, nine distinct 404s, one unknown identifier.

    "This level holds thirteen sibling rules, one per addressable collection,
    each with its own code: `ERR_MANUFACTURER_NOT_FOUND` (404) on the
    manufacturer read and suspend routes; `ERR_RETAILER_NOT_FOUND` (404) on the
    retailer read, suspend, reinstate and fraud-rescore routes;
    `ERR_OFFER_NOT_FOUND` (404) on the offer read, register, activate and
    withdraw routes; `ERR_SUBMISSION_NOT_FOUND` (404) on the submission read,
    submission-valuation, verify-count and lot-creation routes;
    `ERR_LOT_NOT_FOUND` (404) on the lot read, item-capture and finalize
    routes; `ERR_COUPON_ITEM_NOT_FOUND` (404) on the coupon-item read and
    adjudicate routes; `ERR_PURCHASE_RECORD_NOT_FOUND` (404) on the
    purchase-data-record read route; `ERR_STATEMENT_NOT_FOUND` (404) on the
    statement read, schedule and release-payment routes;
    `ERR_INVOICE_NOT_FOUND` (404) on the invoice read, fund and reverse-funding
    routes; `ERR_DISPUTE_NOT_FOUND` (404) on the dispute read, request-info,
    resubmit and resolve routes; `ERR_CLIP_NOT_FOUND` (404) on the digital-clip
    read route; and `ERR_REDEMPTION_EVENT_NOT_FOUND` (404) on the
    digital-redemption-event read route."

    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/every_not_found_code_in_the_catalog_is_reachable
    """
    probes = [
        (api.get_manufacturer(UNKNOWN_UUID, ADMIN),
         err.ERR_MANUFACTURER_NOT_FOUND),
        (api.get_retailer(UNKNOWN_UUID, ADMIN),
         err.ERR_RETAILER_NOT_FOUND),
        (api.get_item(UNKNOWN_UUID, ADMIN),
         err.ERR_COUPON_ITEM_NOT_FOUND),
        (api.get_purchase_record(UNKNOWN_UUID, ADMIN),
         err.ERR_PURCHASE_RECORD_NOT_FOUND),
        (api.get_statement(UNKNOWN_UUID, ADMIN),
         err.ERR_STATEMENT_NOT_FOUND),
        (api.get_invoice(UNKNOWN_UUID, ADMIN),
         err.ERR_INVOICE_NOT_FOUND),
        (api.get_dispute(UNKNOWN_UUID, ADMIN),
         err.ERR_DISPUTE_NOT_FOUND),
        (api.get_clip(UNKNOWN_UUID, ADMIN),
         err.ERR_CLIP_NOT_FOUND),
        (api.get_redemption_event(UNKNOWN_UUID, ADMIN),
         err.ERR_REDEMPTION_EVENT_NOT_FOUND),
    ]

    for response, code in probes:
        validate_error(response, code, expected_status=404)
        body = response.json()
        assert body["data"]["error_id"] == code, (
            f"each collection answers with its own code, expected {code}, got "
            f"{body['data']['error_id']!r}"
        )
        message = body["data"]["message"]
        assert isinstance(message, str) and message.strip(), (
            f"the {code} envelope must carry a human-readable message, got "
            f"{message!r}"
        )

    codes = {code for _, code in probes}
    assert len(codes) == 9, (
        "the nine reads must not share one generic refusal, got "
        f"{sorted(codes)}"
    )


def test_02_the_clock_refuses_the_instant_it_already_holds(api, build):
    """The same instant twice is a refusal, and no refusal runs a sweep.

    "The clock is strictly monotonic: a requested `current_utc` that is less
    than or equal to the stored instant is refused with `ERR_CLOCK_NOT_MONOTONIC`
    (HTTP 422), so the clock never moves backward and never repeats an instant."

    "A successful clock advance runs three deterministic sweeps, in exactly this
    order, and reports how many rows each one touched."

    "Every `Offer` whose status is `ACTIVE` and whose `expiration_date` is
    strictly earlier than the new clock's calendar date moves from `ACTIVE` to
    `EXPIRED`, processed in `created_at` ascending order."

    Design: Corner/errors/logical_clock_refuses_a_repeated_or_earlier_instant
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    offer = build.active_offer(mfr["id"], offer_code="SOUP50",
                               expiration_date="2026-08-31")
    assert_fields(offer, {"status": OfferStatus.ACTIVE})

    forward = validate_success(api.set_clock("2026-08-15T00:00:00Z", ADMIN))
    assert_sweep_counters(forward, "2026-08-15T00:00:00Z", 0, 0, 0)

    repeated = api.set_clock("2026-08-15T00:00:00Z", ADMIN)
    validate_error(repeated, err.ERR_CLOCK_NOT_MONOTONIC, expected_status=422)

    backward = api.set_clock("2026-08-01T00:00:00Z", ADMIN)
    validate_error(backward, err.ERR_CLOCK_NOT_MONOTONIC, expected_status=422)

    still_live = validate_success(
        api.get_offer(offer["id"], make_manufacturer_headers(mfr["id"])))
    assert_fields(still_live, {"status": OfferStatus.ACTIVE})

    past_expiry = validate_success(api.set_clock("2026-09-01T00:00:00Z", ADMIN))
    assert_sweep_counters(past_expiry, "2026-09-01T00:00:00Z", 1, 0, 0)

    expired = validate_success(
        api.get_offer(offer["id"], make_manufacturer_headers(mfr["id"])))
    assert_fields(expired, {
        "status": OfferStatus.EXPIRED,
        "barcode_payload": databar_payload("038000", 50, 1, "2026-08-31", 30),
    })


def test_03_one_flag_on_the_offer_gates_both_digital_endpoints(api, build):
    """The same loyalty handle is refused on paper and clipped on digital.

    "On clip creation and on digital-redemption reporting, the offer's
    `digital_enabled` must be true — otherwise `ERR_OFFER_NOT_DIGITAL` (422)."

    "The offer must have `digital_enabled` set to true; an offer that exists but
    was never enabled for digital distribution is refused with
    `ERR_OFFER_NOT_DIGITAL`, which is the sole gate the digital pipeline shares
    with redemption ingest."

    "The clip's `clipped_at` is the logical clock's calendar date at creation and
    is **never** supplied by the caller — a client cannot backdate a clip to widen
    its own eligibility window — and it is the inclusive lower bound of the clip's
    occupancy interval."

    Design: Corner/errors/digital_endpoints_refuse_an_offer_that_is_not_digital_enabled
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    retailer = build.retailer(legal_name="Northgate Markets")
    headers = make_retailer_headers(retailer["id"])

    paper = build.active_offer(mfr["id"], offer_code="PAPER50")
    digital = build.active_offer(mfr["id"], offer_code="DIGI50",
                                 digital_enabled=True, clip_validity_days=60)

    no_clip = api.create_clip(paper["id"], "LOYAL-9001", headers)
    validate_error(no_clip, err.ERR_OFFER_NOT_DIGITAL, expected_status=422)

    no_event = api.create_redemption_event(
        paper["id"], retailer["id"], "LOYAL-9001", headers)
    validate_error(no_event, err.ERR_OFFER_NOT_DIGITAL, expected_status=422)

    clipped = validate_success(
        api.create_clip(digital["id"], "LOYAL-9001", headers), 201)
    assert_fields(clipped, {
        "status": ClipStatus.CLIPPED,
        "consumer_ref": "LOYAL-9001",
        "clipped_at": "2026-08-01",
        "clip_expires_at": "2026-09-30",
    })
    assert_nulls(clipped, ["matched_event_id"])

    never_enabled = validate_success(api.get_offer(paper["id"], ADMIN))
    assert_fields(never_enabled, {"digital_enabled": False,
                                  "status": OfferStatus.ACTIVE})


def test_04_one_released_payment_locks_the_funding_reversal_out(api, build):
    """Two billed statements, one released, and the wire can no longer come back.

    "On funding reversal, no statement billed onto the invoice may have status
    `PAID` — otherwise `ERR_STATEMENT_ALREADY_PAID` (409)."

    "Finally, the same call evaluates a bubble-up: once **every** statement
    carrying this `manufacturer_invoice_id` is `PAID`, the invoice advances
    `FUNDED` → `RECONCILED`, its own terminal state."

    "`billed_clearing_fee_cents` is the clearinghouse's own cut: 1.5 percent
    charged on the **summed face value only** and never on the handling fee, rounded
    half up to whole cents — and that single rounding point is over the sum, not per
    statement."

    Design: Corner/errors/funding_reversal_is_refused_once_any_billed_statement_is_paid
    """
    world = build.market()
    manufacturer_id = world["manufacturer_id"]
    mfr_headers = make_manufacturer_headers(manufacturer_id)
    build.purchase_record(world["retailer_id"], world["offer_id"], "POS-1",
                          "2026-07-01", 5)

    statements = []
    for start, end, redeemed in (("2026-07-01", "2026-07-15", "2026-07-03"),
                                 ("2026-07-16", "2026-07-31", "2026-07-20")):
        submission = build.verified_submission(world["retailer_id"], 1, start, end)
        lot = build.lot(submission["id"], world["offer_id"], manufacturer_id, 1)
        build.capture(lot["id"], [f.item_payload(
            world["barcode"], f"s3://coupon-images/{start}.jpg", redeemed,
            pos_transaction_ref="POS-1")])
        build.finalize(lot["id"])
        statements.append(build.issue_statement(submission["id"]))

    invoice = build.invoice(manufacturer_id, "2026-07-01", "2026-07-31",
                           [row["id"] for row in statements])
    assert_money(invoice, "billed_face_value_cents", 100)
    assert_money(invoice, "billed_handling_fee_cents", 14)
    assert_money(invoice, "billed_clearing_fee_cents", 2)
    assert_money(invoice, "billed_total_cents", 116)

    funded = build.fund(invoice, 116)
    assert_fields(funded, {"status": InvoiceStatus.FUNDED})
    assert_money(funded, "funded_amount_cents", 116)
    assert_money(funded, "funding_shortfall_cents", 0)

    for statement in statements:
        scheduled = build.schedule(statement["id"])
        assert_fields(scheduled, {"status": StatementStatus.SCHEDULED,
                                  "scheduled_pay_date": "2026-08-31"})

    pay_date = validate_success(api.set_clock("2026-08-31T09:00:00Z", ADMIN))
    assert_sweep_counters(pay_date, "2026-08-31T09:00:00Z", 0, 0, 0)

    paid = validate_success(
        api.release_payment(statements[0]["id"], OFFICER_2))
    assert_fields(paid, {"status": StatementStatus.PAID})
    assert_money(paid, "net_payable_cents", 57)

    clawback = api.reverse_funding(
        invoice["id"], "Manufacturer disputes the July clearing volume.", ADMIN)
    validate_error(clawback, err.ERR_STATEMENT_ALREADY_PAID,
                   expected_status=409)

    intact = validate_success(api.get_invoice(invoice["id"], OFFICER))
    assert_fields(intact, {"status": InvoiceStatus.FUNDED})
    assert_money(intact, "funded_amount_cents", 116)
    assert_money(intact, "funding_shortfall_cents", 0)

    issuer = validate_success(api.get_manufacturer(manufacturer_id, mfr_headers))
    assert_manufacturer_ledger(issuer, funded_total=116, disbursed_total=57)
    assert_money(issuer, "funding_balance_cents", 59)

    unpaid = validate_success(api.get_statement(statements[1]["id"], OFFICER))
    assert_fields(unpaid, {
        "status": StatementStatus.SCHEDULED,
        "scheduled_pay_date": "2026-08-31",
        "manufacturer_invoice_id": invoice["id"],
    })
    assert_nulls(unpaid, ["released_by_user_id"])
