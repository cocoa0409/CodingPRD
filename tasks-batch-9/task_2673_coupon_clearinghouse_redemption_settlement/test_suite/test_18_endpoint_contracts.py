"""What each endpoint returns, in what order, and what it leaves untouched.

A bulk creation that is atomic and order-preserving, a computed read that
writes nothing, a release gate that is inclusive on its own date, an invoice
that links statements exactly once, and a listing that filters and pages.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    OFFICER,
    OFFICER_2,
    SETTLEMENT_OFFICER_2_ID,
    UNKNOWN_UUID_LOT,
    Channel,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotStatus,
    PaymentTerms,
    SettlementStatus,
    StatementStatus,
    ValuationVariant,
    api_errors as err,
    assert_fields,
    assert_lot_valuation,
    assert_manufacturer_ledger,
    assert_money,
    assert_nulls,
    assert_ordered_ascending,
    assert_page,
    assert_retailer_unpaid,
    assert_sweep_counters,
    factories as f,
    make_manufacturer_headers,
)


def test_01_bulk_capture_is_atomic_and_keeps_the_supplied_array_order(
        api, build):
    """Two refused batches leave the lot empty; the third lands in body order.

    "The `image_uri` is 1 to 300 non-blank characters locating the captured
    coupon image and is **mandatory on every element**, because validation
    against offer terms is image-based — a blank or missing one refuses the whole
    batch with `ERR_IMAGE_REQUIRED`."

    "The `pos_transaction_ref` is 1 to 40 characters when present and is the
    register transaction reference; it is required on every element when the
    owning submission's `channel` is `ELECTRONIC`, and its absence there refuses
    the batch with `ERR_POS_REF_REQUIRED`, whereas a `MAIL` submission may omit
    it and let the item fail adjudication instead."

    "On success one coupon item is created per element **in the supplied array
    order**, each in status `CAPTURED` with a null `reject_code`,
    `duplicate_of_item_id`, `matched_purchase_record_id` and `adjudicated_at`, and
    element number *k* receives a `created_at` of the logical clock plus *k*
    milliseconds — so `created_at` ascending is exactly the order of the request
    body, and the adjudication ladder's processing order is fully determined by how
    the clerk arranged the batch."

    Design: Corner/endpoints/bulk_image_capture_is_all_or_nothing_and_preserves_array_order
    """
    world = build.market()
    submission = build.verified_submission(
        world["retailer_id"], 3, channel=Channel.ELECTRONIC)
    lot = build.lot(submission["id"], world["offer_id"],
                    world["manufacturer_id"], 3)
    assert_fields(lot, {"sample_size": 3, "captured_item_count": 0})

    unimaged = f.item_batch(3, world["barcode"], "2026-07-05",
                            pos_transaction_ref="POS-1")
    unimaged[1]["image_uri"] = ""
    blank_image = api.capture_items(lot["id"], unimaged, CLERK)
    validate_error(blank_image, err.ERR_IMAGE_REQUIRED, expected_status=422)

    unreferenced = f.item_batch(3, world["barcode"], "2026-07-05",
                                pos_transaction_ref="POS-1")
    unreferenced[1].pop("pos_transaction_ref")
    no_pos_ref = api.capture_items(lot["id"], unreferenced, CLERK)
    validate_error(no_pos_ref, err.ERR_POS_REF_REQUIRED, expected_status=422)

    still_empty = validate_success(api.get_lot(lot["id"], CLERK))
    assert_fields(still_empty, {"captured_item_count": 0, "sample_size": 3,
                                "status": LotStatus.SORTED})

    ordered = f.item_batch(3, world["barcode"], "2026-07-05",
                           pos_transaction_ref="POS-1",
                           uri_stem="s3://coupon-images/e")
    created = validate_success(api.capture_items(lot["id"], ordered, CLERK), 201)
    assert len(created) == 3, (
        f"one coupon item per element of the array, got {len(created)}"
    )
    assert [row["image_uri"] for row in created] == [
        "s3://coupon-images/e1.jpg",
        "s3://coupon-images/e2.jpg",
        "s3://coupon-images/e3.jpg",
    ], "the response array follows the request array element for element"
    for row in created:
        assert_fields(row, {"status": ItemStatus.CAPTURED,
                            "lot_id": lot["id"],
                            "claimed_units": 1})
        assert_nulls(row, ["reject_code", "duplicate_of_item_id",
                           "matched_purchase_record_id", "adjudicated_at"])

    filled = validate_success(api.get_lot(lot["id"], CLERK))
    assert_fields(filled, {"captured_item_count": 3, "sample_size": 3})

    rows, meta = validate_paginated(
        api.list_items(CLERK, lot_id=lot["id"], limit=10))
    assert meta["total_count"] == 3
    assert_ordered_ascending(rows, "created_at")
    assert [row["image_uri"] for row in rows] == [
        "s3://coupon-images/e1.jpg",
        "s3://coupon-images/e2.jpg",
        "s3://coupon-images/e3.jpg",
    ], "created_at ascending replays the order the clerk arranged the batch in"


def test_02_the_valuation_read_returns_both_variants_and_writes_nothing(
        api, build):
    """One shipment, two totals: 450 forced full-count against 2250 sampled.

    "A submission valuation read recomputes that submission's face value
    **both** ways from the same stored rows — once forcing every lot through the
    full-count valuation variant and once forcing every lot through sampled
    extrapolation — and returns the two totals side by side without writing
    anything."

    "Its response body carries `submission_id`, `valuation_method`,
    `full_count_gross_face_value_cents`, `sampled_gross_face_value_cents`,
    `settled_gross_face_value_cents`, `settled_handling_fee_cents` and
    `lot_count`."

    "The threshold is inclusive on the full-count side, and the step at the
    boundary is dramatic: a bucket of 40 coupons stays `FULL_COUNT` and demands 40
    images, while a bucket of 41 coupons flips to `SAMPLED_EXTRAPOLATION` and
    demands only 5 (the ceiling of 4.1)."

    Design: Corner/endpoints/valuation_read_returns_both_variants_without_writing_anything
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-05", 5)
    submission = build.verified_submission(retailer_id, 45)

    sampled = build.lot(submission["id"], world["offer_id"],
                        world["manufacturer_id"], 41)
    counted_whole = build.lot(submission["id"], world["offer_id"],
                              world["manufacturer_id"], 4)
    assert_fields(sampled, {
        "sample_size": 5,
        "valuation_variant": ValuationVariant.SAMPLED_EXTRAPOLATION,
    })
    assert_fields(counted_whole, {
        "sample_size": 4,
        "valuation_variant": ValuationVariant.FULL_COUNT,
    })

    build.capture(sampled["id"], f.item_batch(
        5, world["barcode"], "2026-07-05", pos_transaction_ref="POS-1",
        uri_stem="s3://coupon-images/s"))
    build.capture(counted_whole["id"], f.item_batch(
        4, world["barcode"], "2026-07-05", pos_transaction_ref="POS-1",
        uri_stem="s3://coupon-images/w"))

    projected = build.finalize(sampled["id"])
    assert_lot_valuation(projected, LotStatus.VALIDATED, 5, 0, 41, 2050, 287)
    direct = build.finalize(counted_whole["id"])
    assert_lot_valuation(direct, LotStatus.VALIDATED, 4, 0, 4, 200, 28)

    before = validate_success(api.get_submission(submission["id"], OFFICER))
    assert_fields(before, {
        "intake_status": IntakeStatus.CLOSED,
        "valuation_method": ValuationVariant.SAMPLED_EXTRAPOLATION,
    })

    valuation = validate_success(api.get_valuation(submission["id"], OFFICER))
    assert_fields(valuation, {
        "submission_id": submission["id"],
        "valuation_method": ValuationVariant.SAMPLED_EXTRAPOLATION,
        "lot_count": 2,
    })
    assert_money(valuation, "full_count_gross_face_value_cents", 450)
    assert_money(valuation, "sampled_gross_face_value_cents", 2250)
    assert_money(valuation, "settled_gross_face_value_cents", 2250)
    assert_money(valuation, "settled_handling_fee_cents", 315)
    assert valuation["full_count_gross_face_value_cents"] != 2250, (
        "forcing the 41-coupon bucket through full count values only the five "
        "coupons that were actually imaged"
    )

    after = validate_success(api.get_submission(submission["id"], OFFICER))
    assert after["version"] == before["version"], (
        "the computed read writes nothing, so the submission version stands at "
        f"{before['version']}"
    )
    assert_money(after, "settled_gross_face_value_cents", 2250)
    assert_money(after, "settled_handling_fee_cents", 315)


def test_03_release_is_refused_the_day_before_and_legal_on_the_pay_date(
        api, build):
    """A NET_30 statement pays on 2026-08-31 and not on 2026-08-30.

    "The logical clock's calendar date must have reached `scheduled_pay_date` —
    the comparison is inclusive, so release on the pay date itself is legal, and an
    earlier date is refused with `ERR_PAY_DATE_NOT_REACHED`."

    "Release sets the statement to `PAID` — a terminal state — records
    `released_by_user_id` as the acting user, moves the submission's
    `settlement_status` `STATEMENT_ISSUED` → `PAID` and clears its `hold_reason`,
    increases the manufacturer's `disbursed_total_cents` by the statement's
    `net_payable_cents` with `funding_balance_cents` recomputed and the
    manufacturer's `version` bumped, and decreases the retailer's
    `unpaid_balance_cents` by the same `net_payable_cents` with the retailer's
    `version` bumped."

    "Finally, the same call evaluates a bubble-up: once **every** statement
    carrying this `manufacturer_invoice_id` is `PAID`, the invoice advances
    `FUNDED` → `RECONCILED`, its own terminal state."

    Design: Corner/endpoints/release_payment_is_allowed_on_exactly_the_scheduled_date
    """
    world = build.market(payment_terms=PaymentTerms.NET_30)
    manufacturer_id = world["manufacturer_id"]
    retailer_id = world["retailer_id"]
    chain = build.funded_chain(world)
    statement = chain["statement"]
    assert_fields(statement, {
        "status": StatementStatus.SCHEDULED,
        "scheduled_pay_date": "2026-08-31",
    })
    assert_money(statement, "net_payable_cents", 57)
    assert_fields(chain["invoice"], {"status": InvoiceStatus.FUNDED})
    assert_money(chain["invoice"], "billed_total_cents", 58)

    day_before = validate_success(api.set_clock("2026-08-30T09:00:00Z", ADMIN))
    assert_sweep_counters(day_before, "2026-08-30T09:00:00Z", 0, 0, 0)

    early = api.release_payment(statement["id"], OFFICER_2)
    validate_error(early, err.ERR_PAY_DATE_NOT_REACHED, expected_status=422)

    unmoved = validate_success(api.get_statement(statement["id"], OFFICER))
    assert_fields(unmoved, {"status": StatementStatus.SCHEDULED})
    assert_nulls(unmoved, ["released_by_user_id"])

    pay_date = validate_success(api.set_clock("2026-08-31T09:00:00Z", ADMIN))
    assert_sweep_counters(pay_date, "2026-08-31T09:00:00Z", 0, 0, 0)

    paid = validate_success(api.release_payment(statement["id"], OFFICER_2))
    assert_fields(paid, {
        "status": StatementStatus.PAID,
        "released_by_user_id": SETTLEMENT_OFFICER_2_ID,
    })
    assert_money(paid, "net_payable_cents", 57)

    reconciled = validate_success(api.get_invoice(
        chain["invoice_id"], make_manufacturer_headers(manufacturer_id)))
    assert_fields(reconciled, {"status": InvoiceStatus.RECONCILED})
    assert_money(reconciled, "funded_amount_cents", 58)

    issuer = validate_success(api.get_manufacturer(
        manufacturer_id, make_manufacturer_headers(manufacturer_id)))
    assert_manufacturer_ledger(issuer, funded_total=58, disbursed_total=57)
    assert_money(issuer, "funding_balance_cents", 1)

    retailer = validate_success(api.get_retailer(retailer_id, OFFICER))
    assert_retailer_unpaid(retailer, 0)

    submission = validate_success(
        api.get_submission(chain["submission_id"], OFFICER))
    assert_fields(submission, {
        "intake_status": IntakeStatus.CLOSED,
        "settlement_status": SettlementStatus.PAID,
    })
    assert_nulls(submission, ["hold_reason"])


def test_04_an_invoice_bundles_two_submissions_and_never_relinks_a_statement(
        api, build):
    """Two of three statements bill together; the third resists three bad calls.

    "The officer supplies the `manufacturer_id` being billed, the inclusive
    `billing_period_start` and inclusive `billing_period_end` of the period (the
    start on or before the end), and `statement_ids`, an ordered list of 1 to 200
    statement identifiers with no repeats — an empty list or a repeated element is
    refused with `ERR_STATEMENT_LINES_EMPTY`."

    "Each named statement must be in `DRAFT` or `SCHEDULED`, must not already
    carry a `manufacturer_invoice_id`, and must belong to a submission whose
    `VALIDATED` and `REINSTATED` lots all point at this same manufacturer;
    statements in `HELD` or `PAID` are not billable at all, and a violation is
    `ERR_STATEMENT_NOT_BILLABLE`."

    "The invoice is created in status `ISSUED`, and each named statement has its
    `manufacturer_invoice_id` set to the new invoice."

    Design: Corner/endpoints/invoice_links_statements_from_two_submissions_and_refuses_relinking
    """
    world = build.market()
    manufacturer_id = world["manufacturer_id"]
    build.purchase_record(world["retailer_id"], world["offer_id"], "POS-1",
                          "2026-07-01", 5)

    statements = []
    for start, end, redeemed in (("2026-07-01", "2026-07-05", "2026-07-03"),
                                 ("2026-07-06", "2026-07-10", "2026-07-08"),
                                 ("2026-07-11", "2026-07-15", "2026-07-13")):
        submission = build.verified_submission(world["retailer_id"], 1, start, end)
        lot = build.lot(submission["id"], world["offer_id"], manufacturer_id, 1)
        build.capture(lot["id"], [f.item_payload(
            world["barcode"], f"s3://coupon-images/{start}.jpg", redeemed,
            pos_transaction_ref="POS-1")])
        build.finalize(lot["id"])
        statement = build.issue_statement(submission["id"])
        assert_money(statement, "net_payable_cents", 57)
        assert_nulls(statement, ["manufacturer_invoice_id"])
        statements.append(statement)

    invoice = build.invoice(manufacturer_id, "2026-07-01", "2026-07-31",
                           [statements[0]["id"], statements[1]["id"]])
    assert_fields(invoice, {"status": InvoiceStatus.ISSUED,
                            "manufacturer_id": manufacturer_id})
    assert_money(invoice, "billed_face_value_cents", 100)
    assert_money(invoice, "billed_handling_fee_cents", 14)
    assert_money(invoice, "billed_clearing_fee_cents", 2)
    assert_money(invoice, "billed_total_cents", 116)
    assert_money(invoice, "funded_amount_cents", 0)
    assert_money(invoice, "funding_shortfall_cents", 116)

    for billed in statements[:2]:
        linked = validate_success(api.get_statement(billed["id"], OFFICER))
        assert_fields(linked, {"manufacturer_invoice_id": invoice["id"],
                               "status": StatementStatus.DRAFT})

    relink = api.create_invoice(f.invoice_payload(
        manufacturer_id, "2026-09-01", "2026-09-15",
        [statements[0]["id"], statements[2]["id"]]), OFFICER)
    validate_error(relink, err.ERR_STATEMENT_NOT_BILLABLE, expected_status=422)

    empty = api.create_invoice(f.invoice_payload(
        manufacturer_id, "2026-09-01", "2026-09-15", []), OFFICER)
    validate_error(empty, err.ERR_STATEMENT_LINES_EMPTY, expected_status=422)

    repeated = api.create_invoice(f.invoice_payload(
        manufacturer_id, "2026-09-01", "2026-09-15",
        [statements[2]["id"], statements[2]["id"]]), OFFICER)
    validate_error(repeated, err.ERR_STATEMENT_LINES_EMPTY,
                   expected_status=422)

    unbilled = validate_success(api.get_statement(statements[2]["id"], OFFICER))
    assert_fields(unbilled, {"status": StatementStatus.DRAFT})
    assert_nulls(unbilled, ["manufacturer_invoice_id"])

    rows, meta = validate_paginated(api.list_invoices(
        OFFICER, manufacturer_id=manufacturer_id, limit=10))
    assert meta["total_count"] == 1, (
        "none of the three refused calls created a second invoice"
    )
    assert rows[0]["id"] == invoice["id"]

    billed_rows, billed_meta = validate_paginated(api.list_statements(
        OFFICER, manufacturer_invoice_id=invoice["id"], limit=10))
    assert billed_meta["total_count"] == 2, (
        "exactly the two named statements carry the new invoice id"
    )
    assert {row["id"] for row in billed_rows} == {
        statements[0]["id"], statements[1]["id"]}


def test_05_the_lot_listing_filters_and_pages_and_an_unknown_id_is_not_found(
        api, build):
    """Four buckets, one filter, two pages, and a path segment that resolves to nothing.

    "Submission lots may be filtered by `submission_id`, `offer_id`,
    `manufacturer_id` and `status`."

    "Unless a listing endpoint's description in §4 states otherwise, results are
    ordered by `created_at` ascending."

    "Both are echoed back in `meta`, alongside `total_count` (the number of rows
    matching the filter before the page window is applied) and `has_more` (true when
    `offset` plus the number of returned rows is still below `total_count`)."

    "The `{id}` path segment resolves to an existing row of its own collection."

    Design: Corner/endpoints/lot_list_filters_and_paginates_and_unknown_ids_are_not_found
    """
    world = build.market()
    offer_id = world["offer_id"]
    manufacturer_id = world["manufacturer_id"]

    sorted_shipment = build.verified_submission(
        world["retailer_id"], 6, "2026-07-01", "2026-07-10")
    first = build.lot(sorted_shipment["id"], offer_id, manufacturer_id, 1)
    second = build.lot(sorted_shipment["id"], offer_id, manufacturer_id, 2)
    third = build.lot(sorted_shipment["id"], offer_id, manufacturer_id, 3)

    other_shipment = build.verified_submission(
        world["retailer_id"], 1, "2026-07-11", "2026-07-20")
    stranger = build.lot(other_shipment["id"], offer_id, manufacturer_id, 1)

    everything, all_meta = validate_paginated(api.list_lots(CLERK, limit=10))
    assert all_meta["total_count"] == 4, (
        "all four buckets of both shipments are visible unfiltered"
    )
    assert stranger["id"] in {row["id"] for row in everything}

    rows, meta = validate_paginated(api.list_lots(
        CLERK, submission_id=sorted_shipment["id"], limit=10))
    assert_page(meta, total_count=3, limit=10, offset=0, has_more=False)
    assert_ordered_ascending(rows, "created_at")
    assert [row["counted_qty"] for row in rows] == [1, 2, 3], (
        "the filtered page carries the three buckets of one shipment only, "
        "oldest first"
    )
    assert stranger["id"] not in {row["id"] for row in rows}

    page_one, page_one_meta = validate_paginated(api.list_lots(
        CLERK, submission_id=sorted_shipment["id"], limit=2, offset=0))
    assert_page(page_one_meta, total_count=3, limit=2, offset=0, has_more=True)
    assert len(page_one) == 2
    assert [row["id"] for row in page_one] == [first["id"], second["id"]]

    page_two, page_two_meta = validate_paginated(api.list_lots(
        CLERK, submission_id=sorted_shipment["id"], limit=2, offset=2))
    assert_page(page_two_meta, total_count=3, limit=2, offset=2, has_more=False)
    assert len(page_two) == 1
    assert page_two[0]["id"] == third["id"]
    assert_fields(page_two[0], {"counted_qty": 3, "status": LotStatus.SORTED})

    one = validate_success(api.get_lot(third["id"], ANALYST))
    assert_fields(one, {
        "id": third["id"],
        "submission_id": sorted_shipment["id"],
        "offer_id": offer_id,
        "manufacturer_id": manufacturer_id,
        "counted_qty": 3,
    })

    missing = api.get_lot(UNKNOWN_UUID_LOT, ANALYST)
    validate_error(missing, err.ERR_LOT_NOT_FOUND, expected_status=404)
