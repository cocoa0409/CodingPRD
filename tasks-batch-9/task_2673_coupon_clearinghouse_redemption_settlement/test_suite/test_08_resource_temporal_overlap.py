"""Three contended resources with three different interval rules.

A retailer's intake stream is half-open, an issuer's billing calendar is closed
with a clear day either side, and a consumer's clip slots are pure capacity.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    CLERK,
    OFFICER,
    Channel,
    ClipStatus,
    IntakeStatus,
    InvoiceStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_money,
    assert_sweep_counters,
    factories as f,
)


def _standard_market(build, **overrides):
    """The contract-rate issuer and the STANDARD, NET_30 retailer they settle."""
    terms = dict(
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
    terms.update(overrides)
    return build.market(**terms)


@pytest.fixture
def open_window(build):
    """A retailer holding an un-closed shipment on the half-open [07-01, 07-16).

    Its single lot is fully imaged but not finalized, so the shipment is still
    contending for the retailer's intake stream.
    """
    market = _standard_market(build)
    for ref in ("POS-P1", "POS-P2"):
        build.purchase_record(market["retailer_id"], market["offer_id"], ref,
                              "2026-07-05", 2)
    submission = build.verified_submission(market["retailer_id"], 2,
                                           "2026-07-01", "2026-07-16")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 2)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{ref.lower()}.jpg",
                       "2026-07-05", pos_transaction_ref=ref, claimed_units=1)
        for ref in ("POS-P1", "POS-P2")
    ])
    return {"market": market, "retailer_id": market["retailer_id"],
            "submission_id": submission["id"], "lot_id": lot["id"]}


def test_01_a_one_day_overlap_is_refused_but_exact_adjacency_is_not(
        api, open_window):
    """Sharing 2026-07-15 collides; starting on 2026-07-16 does not.

    "Because the interval is half-open, exact adjacency is legal — an existing
    window ending 2026-07-31 and a new window starting 2026-07-31 do not overlap
    — while any genuine overlap is refused with `ERR_POSTMARK_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/postmark_window_half_open_adjacency_allowed
    """
    retailer_id = open_window["retailer_id"]

    refused = api.create_submission(
        f.submission_payload(retailer_id, 2, "2026-07-15", "2026-07-20"), CLERK)
    validate_error(refused, err.ERR_POSTMARK_WINDOW_OVERLAP)

    adjacent = validate_success(api.create_submission(
        f.submission_payload(retailer_id, 2, "2026-07-16", "2026-07-31"),
        CLERK), 201)
    assert_fields(adjacent, {"postmark_window_start": "2026-07-16",
                             "postmark_window_end": "2026-07-31",
                             "intake_status": IntakeStatus.RECEIVED})


def test_02_a_window_wholly_inside_the_incumbent_is_refused(api, open_window):
    """Containment is overlap, and the refusal creates nothing.

    "The clearinghouse can reconcile only one postmark window of a given retailer
    at a time, so the new half-open interval must not overlap the interval of any
    existing submission of the same retailer whose `intake_status` is not yet
    `CLOSED`; the rule is channel-independent, so a mail window and an electronic
    window of one retailer contend exactly the same way."

    Design: Difficulty/resource_temporal_overlap/postmark_window_half_open_adjacency_allowed
    """
    retailer_id = open_window["retailer_id"]

    refused = api.create_submission(
        f.submission_payload(retailer_id, 2, "2026-07-10", "2026-07-12",
                             channel=Channel.ELECTRONIC), CLERK)
    validate_error(refused, err.ERR_POSTMARK_WINDOW_OVERLAP)

    rows, meta = validate_paginated(
        api.list_submissions(CLERK, retailer_id=retailer_id))
    assert len(rows) == 1, "the refused call must not have created a shipment"
    assert_fields(meta, {"total_count": 1})


def test_03_closing_the_incumbent_frees_the_dates_it_was_holding(
        api, build, open_window):
    """The identical window is refused, then accepted, with no date changing.

    "And at the end of every lot creation the system tests one thing: once the
    running sum of `counted_qty` over the submission's lots exactly equals the
    submission's `verified_count`, the submission advances `COUNT_VERIFIED` →
    `SORTED`, which closes it to any further lots."

    "When the submission is in `SORTED` and every one of its lots has reached
    `VALIDATED` or `LOT_REJECTED`, the submission advances `SORTED` → `CLOSED`."

    Design: Difficulty/resource_temporal_overlap/postmark_window_half_open_adjacency_allowed
    """
    retailer_id = open_window["retailer_id"]
    contained = f.submission_payload(retailer_id, 2, "2026-07-10",
                                     "2026-07-12")

    validate_success(api.create_submission(
        f.submission_payload(retailer_id, 2, "2026-07-16", "2026-07-31"),
        CLERK), 201)
    validate_error(api.create_submission(contained, CLERK),
                   err.ERR_POSTMARK_WINDOW_OVERLAP)

    build.finalize(open_window["lot_id"])
    closed = validate_success(
        api.get_submission(open_window["submission_id"], CLERK))
    assert_fields(closed, {"intake_status": IntakeStatus.CLOSED})

    accepted = validate_success(api.create_submission(contained, CLERK), 201)
    assert_fields(accepted, {"postmark_window_start": "2026-07-10",
                             "postmark_window_end": "2026-07-12"})

    rows, meta = validate_paginated(
        api.list_submissions(CLERK, retailer_id=retailer_id))
    assert len(rows) == 3, "the retailer now owns three shipments"
    assert_fields(meta, {"total_count": 3})


@pytest.fixture
def billed_period(build):
    """One issuer billed for July, and a second scheduled statement left free.

    The two shipments sit on adjacent half-open postmark windows and each settles
    at 100 gross and 14 fee, so every candidate period below bills 116.
    """
    market = _standard_market(build)
    statement_ids = []
    submission_ids = []
    for index, (window, day, refs) in enumerate(
            ((("2026-07-01", "2026-07-16"), "2026-07-05", ("POS-Q1", "POS-Q2")),
             (("2026-07-16", "2026-07-31"), "2026-07-20", ("POS-Q3", "POS-Q4"))),
            start=1):
        for ref in refs:
            build.purchase_record(market["retailer_id"], market["offer_id"],
                                  ref, day, 2)
        submission = build.verified_submission(market["retailer_id"], 2,
                                               window[0], window[1])
        lot = build.lot(submission["id"], market["offer_id"],
                        market["manufacturer_id"], 2)
        build.capture(lot["id"], [
            f.item_payload(market["barcode"],
                           f"s3://img/q{index}{position}.jpg", day,
                           pos_transaction_ref=ref, claimed_units=1)
            for position, ref in enumerate(refs, start=1)
        ])
        build.finalize(lot["id"])
        statement = build.issue_statement(submission["id"])
        build.schedule(statement["id"])
        statement_ids.append(statement["id"])
        submission_ids.append(submission["id"])

    invoice = build.invoice(market["manufacturer_id"], "2026-07-01",
                            "2026-07-31", [statement_ids[0]])
    return {"market": market, "manufacturer_id": market["manufacturer_id"],
            "invoice_one": invoice, "statement_two_id": statement_ids[1],
            "submission_two_id": submission_ids[1]}


def test_04_a_period_starting_the_day_after_the_incumbent_ends_is_refused(
        api, billed_period):
    """July ends on the 31st, so August the 1st leaves no clear day.

    "Billing periods of one manufacturer must not crowd each other: the new
    closed period must be separated from the period of every non-`REVERSED`
    invoice of the same manufacturer by at least one clear day."

    Design: Difficulty/resource_temporal_overlap/billing_period_buffer_adjacency_rejected_both_sides
    """
    assert_fields(billed_period["invoice_one"], {
        "billing_period_start": "2026-07-01",
        "billing_period_end": "2026-07-31",
        "status": InvoiceStatus.ISSUED,
    })

    refused = api.create_invoice(f.invoice_payload(
        billed_period["manufacturer_id"], "2026-08-01", "2026-08-31",
        [billed_period["statement_two_id"]]), OFFICER)
    validate_error(refused, err.ERR_BILLING_PERIOD_BUFFER_VIOLATION)


def test_05_a_period_ending_the_day_before_the_incumbent_starts_is_refused(
        api, billed_period):
    """The buffer guards both edges of the closed interval, not just the later one.

    "Billing periods of one manufacturer must not crowd each other: the new
    closed period must be separated from the period of every non-`REVERSED`
    invoice of the same manufacturer by at least one clear day."

    Design: Difficulty/resource_temporal_overlap/billing_period_buffer_adjacency_rejected_both_sides
    """
    refused = api.create_invoice(f.invoice_payload(
        billed_period["manufacturer_id"], "2026-06-01", "2026-06-30",
        [billed_period["statement_two_id"]]), OFFICER)
    validate_error(refused, err.ERR_BILLING_PERIOD_BUFFER_VIOLATION)

    statement = validate_success(
        api.get_statement(billed_period["statement_two_id"], OFFICER))
    assert statement["manufacturer_invoice_id"] is None, (
        "a refused billing attempt must not link the statement it named"
    )


def test_06_one_clear_day_is_enough_and_the_refusals_left_no_trace(
        api, billed_period):
    """2026-08-02 clears 2026-08-01, and the issuer ends with exactly two invoices.

    "`billed_total_cents` is the face value plus the handling fee plus the
    clearing fee."

    "The invoice is created in status `ISSUED`, and each named statement has its
    `manufacturer_invoice_id` set to the new invoice."

    Design: Difficulty/resource_temporal_overlap/billing_period_buffer_adjacency_rejected_both_sides
    """
    manufacturer_id = billed_period["manufacturer_id"]
    statement_two_id = billed_period["statement_two_id"]

    for start, end in (("2026-08-01", "2026-08-31"), ("2026-06-01", "2026-06-30")):
        validate_error(api.create_invoice(f.invoice_payload(
            manufacturer_id, start, end, [statement_two_id]), OFFICER),
            err.ERR_BILLING_PERIOD_BUFFER_VIOLATION)

    accepted = validate_success(api.create_invoice(f.invoice_payload(
        manufacturer_id, "2026-08-02", "2026-08-31", [statement_two_id]),
        OFFICER), 201)

    assert_fields(accepted, {"status": InvoiceStatus.ISSUED,
                             "billing_period_start": "2026-08-02",
                             "billing_period_end": "2026-08-31"})
    assert_money(accepted, "billed_face_value_cents", 100)
    assert_money(accepted, "billed_handling_fee_cents", 14)
    assert_money(accepted, "billed_clearing_fee_cents", 2)
    assert_money(accepted, "billed_total_cents", 116)

    statement = validate_success(api.get_statement(statement_two_id, OFFICER))
    assert_fields(statement, {"manufacturer_invoice_id": accepted["id"],
                              "status": StatementStatus.SCHEDULED})

    rows, meta = validate_paginated(
        api.list_invoices(OFFICER, manufacturer_id=manufacturer_id))
    assert len(rows) == 2, "only the July invoice and the cleared August one exist"
    assert_fields(meta, {"total_count": 2})


@pytest.fixture
def digital_offer(api, build):
    """One consumer holding two live clips on a digital offer, staggered by four days.

    The first clip is taken at the 2026-08-01 clock and the second after the clock
    moves to 2026-08-05, so their fourteen-day validity dates fall apart.
    """
    market = _standard_market(build, offer_code="SOUP50D", digital_enabled=True,
                              clip_validity_days=14,
                              redemption_instructions="Clip and save 50c")
    clip_one = build.clip(market["offer_id"], "consumer-771")
    validate_success(api.set_clock("2026-08-05T00:00:00Z"))
    clip_two = build.clip(market["offer_id"], "consumer-771")
    return {"market": market, "offer_id": market["offer_id"],
            "clip_one": clip_one, "clip_one_id": clip_one["id"],
            "clip_two": clip_two, "clip_two_id": clip_two["id"]}


def test_07_a_third_clip_is_refused_while_two_perfectly_valid_ones_are_live(
        api, digital_offer):
    """Neither existing clip is wrong; only their collective count blocks the third.

    "One consumer may hold only so many live clips on one offer at a time, and the
    limit is 2."

    "This is an aggregate refusal, not an individual one: each of the two existing
    clips is perfectly valid on its own, and it is only their collective count
    that blocks the request — so the error message should speak about occupancy,
    not about any one clip being wrong."

    Design: Difficulty/resource_temporal_overlap/clip_concurrency_aggregate_limit_and_slot_release
    """
    assert_fields(digital_offer["clip_one"], {
        "clip_expires_at": "2026-08-15", "status": ClipStatus.CLIPPED})
    assert_fields(digital_offer["clip_two"], {
        "clip_expires_at": "2026-08-19", "status": ClipStatus.CLIPPED})

    refused = api.create_clip(digital_offer["offer_id"], "consumer-771", ADMIN)
    validate_error(refused, err.ERR_CLIP_CONCURRENCY_LIMIT)

    for clip_id in (digital_offer["clip_one_id"], digital_offer["clip_two_id"]):
        clip = validate_success(api.get_clip(clip_id, ADMIN))
        assert_fields(clip, {"status": ClipStatus.CLIPPED})


def test_08_the_sweep_frees_exactly_one_slot_and_the_same_request_then_passes(
        api, digital_offer):
    """The stagger means 2026-08-16 expires the first clip and spares the second.

    "Every `DigitalClip` whose status is `CLIPPED` and whose `clip_expires_at` is
    strictly earlier than the new clock's calendar date moves from `CLIPPED` to
    `EXPIRED_UNUSED`, processed in `created_at` ascending order. The count is
    returned as `expired_clip_count`."

    "A clip the clock sweep has already moved to `EXPIRED_UNUSED` no longer
    occupies a slot, and neither does one consumed into `MATCHED`."

    Design: Difficulty/resource_temporal_overlap/clip_concurrency_aggregate_limit_and_slot_release
    """
    offer_id = digital_offer["offer_id"]
    validate_error(api.create_clip(offer_id, "consumer-771", ADMIN),
                   err.ERR_CLIP_CONCURRENCY_LIMIT)

    sweep = validate_success(api.set_clock("2026-08-16T00:00:00Z"))
    assert_sweep_counters(sweep, "2026-08-16T00:00:00Z", expired_offer_count=0,
                          expired_clip_count=1, withdrawn_dispute_count=0)

    lapsed = validate_success(api.get_clip(digital_offer["clip_one_id"], ADMIN))
    assert_fields(lapsed, {"status": ClipStatus.EXPIRED_UNUSED,
                           "clip_expires_at": "2026-08-15"})
    survivor = validate_success(api.get_clip(digital_offer["clip_two_id"], ADMIN))
    assert_fields(survivor, {"status": ClipStatus.CLIPPED,
                             "clip_expires_at": "2026-08-19"})

    accepted = validate_success(
        api.create_clip(offer_id, "consumer-771", ADMIN), 201)
    assert_fields(accepted, {"status": ClipStatus.CLIPPED,
                             "clip_expires_at": "2026-08-30",
                             "consumer_ref": "consumer-771"})


def test_09_the_freed_slot_refills_and_neither_refusal_created_a_clip(
        api, digital_offer):
    """Capacity is capacity: with two live clips again, the fourth is refused too.

    "`clip_expires_at`, the inclusive upper bound, is computed once at creation
    and never recomputed afterwards, even if the offer is later amended."

    Design: Difficulty/resource_temporal_overlap/clip_concurrency_aggregate_limit_and_slot_release
    """
    offer_id = digital_offer["offer_id"]
    validate_error(api.create_clip(offer_id, "consumer-771", ADMIN),
                   err.ERR_CLIP_CONCURRENCY_LIMIT)
    validate_success(api.set_clock("2026-08-16T00:00:00Z"))
    validate_success(api.create_clip(offer_id, "consumer-771", ADMIN), 201)

    validate_error(api.create_clip(offer_id, "consumer-771", ADMIN),
                   err.ERR_CLIP_CONCURRENCY_LIMIT)

    survivor = validate_success(api.get_clip(digital_offer["clip_two_id"], ADMIN))
    assert_fields(survivor, {"clip_expires_at": "2026-08-19"})

    rows, meta = validate_paginated(api.list_clips(ADMIN, offer_id=offer_id))
    assert len(rows) == 3, "the two refused calls must have created nothing"
    assert_fields(meta, {"total_count": 3})
