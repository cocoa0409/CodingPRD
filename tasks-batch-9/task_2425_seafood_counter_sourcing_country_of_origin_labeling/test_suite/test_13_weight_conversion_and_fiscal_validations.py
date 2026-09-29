"""Ceilings that float on remaining weight, the conversion gates, timestamp order and the two fiscal gates."""
from test_helpers import ApiErrorId, factories, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_cents,
    assert_shrink_event,
    assert_simp_document,
    assert_supplier_lot,
    assert_weight,
)
from test_helpers.factories import ad_item_payload, ice_bed_reading_payload, simp_document_payload
from test_helpers.test_users import (
    OFFICER_LEDGER_USER_ID,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
    make_supplier_rep_headers,
)


def _labelled_lot_with_four_kilograms_already_sold(api) -> dict:
    """A 10.000 kg cod lot in slot 1 carrying a PUBLISHED label, with 4.000 kg gone."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    fixtures.record_sales(api, counter_id, lot["id"], 4.000)
    env.update({"lot": lot, "label": label})
    return env


def _three_valued_events_across_a_fresh_and_a_frozen_lot(api) -> dict:
    """Lot A never frozen and lot B previously frozen, each carrying UNSOLD_FRESH shrink."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot_a = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot_a["id"], 1)
    lot_b = fixtures.receive_lot(
        api,
        counter_id,
        supplier_id,
        env["cod"]["id"],
        lot_code="COD-0801-C",
        previously_frozen=True,
        fresh_claim=False,
        received_weight_kg=10.000,
    )
    fixtures.case_lot(api, counter_id, lot_b["id"], 2)
    over_allowance = fixtures.create_shrink_event(
        api, counter_id, lot_a["id"], shrink_weight_kg=8.000, conversion_requested_kg=7.000
    )
    zero_request = fixtures.create_shrink_event(
        api, counter_id, lot_a["id"], shrink_weight_kg=2.000, conversion_requested_kg=0.000
    )
    frozen_lot = fixtures.create_shrink_event(
        api, counter_id, lot_b["id"], shrink_weight_kg=5.000, conversion_requested_kg=2.000
    )
    env.update(
        {
            "lot_a": lot_a,
            "lot_b": lot_b,
            "over_allowance": over_allowance,
            "zero_request": zero_request,
            "frozen_lot": frozen_lot,
        }
    )
    return env


def _received_snapper_lot_at_eight_oclock(api) -> dict:
    """An import-monitored snapper lot still in receipt, with the clock at 08:00."""
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)
    supplier = fixtures.register_supplier(api)
    snapper = fixtures.register_red_snapper(api)
    lot = fixtures.receive_snapper_lot(api, counter["id"], supplier["id"], snapper["id"])
    return {"counter": counter, "supplier": supplier, "snapper": snapper, "lot": lot}


def _assessed_chargeback_of_forty_seven_thousand_eight_hundred_forty(api) -> dict:
    """A 10.000 kg lot at 2300 cents retail whose laboratory mismatch assessed 47840 cents."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    pacific = fixtures.register_species(api, factories.pacific_cod_payload())
    lot = fixtures.receive_lot(
        api,
        counter_id,
        env["supplier"]["id"],
        env["cod"]["id"],
        lot_code="COD-0801-S",
        received_weight_kg=10.000,
        unit_cost_cents_per_kg=1600,
        retail_price_cents_per_kg=2300,
        cooked_retail_price_cents_per_kg=2600,
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.publish_case_label(api, counter_id, lot["id"])
    fixtures.sample_with_result(api, lot["id"], pacific["id"], lab_reference="LAB-2026-0801-2")
    env.update({"lot": lot, "pacific": pacific})
    return env


def _supplier_holding_a_hundred_and_forty_nine_thousand_outstanding(api) -> dict:
    """Two counters served by one dealer whose Counter A mislabelling left 149000 cents unsettled."""
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter_a = fixtures.register_counter(api)
    counter_b = fixtures.register_counter(api, store_number="4130", case_slot_count=4)
    supplier = fixtures.register_supplier(api)
    cod = fixtures.register_atlantic_cod(api)
    pacific = fixtures.register_species(api, factories.pacific_cod_payload())
    lot = fixtures.receive_lot(
        api,
        counter_a["id"],
        supplier["id"],
        cod["id"],
        lot_code="COD-0801-H",
        received_weight_kg=40.000,
        unit_cost_cents_per_kg=2000,
        retail_price_cents_per_kg=3000,
        cooked_retail_price_cents_per_kg=3400,
    )
    fixtures.case_lot(api, counter_a["id"], lot["id"], 1)
    fixtures.publish_case_label(api, counter_a["id"], lot["id"])
    fixtures.sample_with_result(api, lot["id"], pacific["id"], lab_reference="LAB-2026-0801-3")
    return {
        "counter_a": counter_a,
        "counter_b": counter_b,
        "supplier": supplier,
        "cod": cod,
        "lot": lot,
    }


def test_01_the_sales_ceiling_follows_the_remaining_weight_down(api):
    """PRD §3.3: "A `sold_weight_kg` greater than the lot's current `remaining_weight_kg` is
    rejected with `ERR_INSUFFICIENT_REMAINING_WEIGHT`."

    Design: Corner/validations/weight_ceilings_on_sales_and_shrink_are_enforced_against_remaining
    """
    env = _labelled_lot_with_four_kilograms_already_sold(api)
    counter_id = env["counter"]["id"]

    response = api.record_sales(
        env["lot"]["id"], {"sold_weight_kg": 6.001}, make_seafood_manager_headers(counter_id)
    )
    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_REMAINING_WEIGHT.value, expected_status=422
    )

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert_supplier_lot(lot)
    assert_weight(lot["remaining_weight_kg"], 6.000)
    assert lot["intake_status"] == "CASED"


def test_02_the_shrink_ceiling_stops_at_six_and_posting_six_depletes_the_lot(api):
    """PRD §3.9: "The `shrink_weight_kg` may not exceed the lot's current `remaining_weight_kg`,
    failing which the request is rejected with `ERR_SHRINK_EXCEEDS_REMAINING`."

    Design: Corner/validations/weight_ceilings_on_sales_and_shrink_are_enforced_against_remaining
    """
    env = _labelled_lot_with_four_kilograms_already_sold(api)
    counter_id = env["counter"]["id"]

    refused = api.create_shrink_event(
        factories.shrink_event_payload(
            env["lot"]["id"], shrink_weight_kg=6.500, conversion_requested_kg=0.000
        ),
        make_seafood_manager_headers(counter_id),
    )
    validate_error(refused, ApiErrorId.ERR_SHRINK_EXCEEDS_REMAINING.value, expected_status=422)
    assert_weight(
        fixtures.read_lot(api, counter_id, env["lot"]["id"])["remaining_weight_kg"], 6.000
    )

    event = fixtures.create_shrink_event(
        api, counter_id, env["lot"]["id"], shrink_weight_kg=6.000, conversion_requested_kg=0.000
    )
    assert_shrink_event(event)
    assert event["status"] == "VALUED"
    assert_cents(event["provisional_value_cents"], 10950)

    posted = fixtures.post_shrink_event(api, counter_id, event["id"])
    assert posted["status"] == "POSTED"

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert_weight(lot["remaining_weight_kg"], 0.000)

    counter = fixtures.read_counter(api, counter_id)
    assert_cents(counter["shrink_gross_cents"], 10950)
    assert_cents(counter["shrink_net_cents"], 10950)
    assert_cents(counter["recovered_conversion_cents"], 0)


def test_03_a_request_above_the_sixty_percent_allowance_is_refused_outright(api):
    """PRD §3.9: "A `conversion_requested_kg` that exceeds the computed `allowance_kg` is
    rejected outright with `ERR_CONVERSION_ALLOWANCE_EXCEEDED`."

    Design: Corner/validations/conversion_gates_reject_over_allowance_zero_request_and_frozen_lots
    """
    env = _three_valued_events_across_a_fresh_and_a_frozen_lot(api)
    counter_id = env["counter"]["id"]

    response = api.approve_conversion(
        env["over_allowance"]["id"], {}, make_seafood_manager_headers(counter_id)
    )
    validate_error(
        response, ApiErrorId.ERR_CONVERSION_ALLOWANCE_EXCEEDED.value, expected_status=422
    )

    event = fixtures.read_shrink_event(api, counter_id, env["over_allowance"]["id"])
    assert event["status"] == "VALUED"
    assert_weight(event["approved_conversion_kg"], 0.000)
    assert_weight(
        fixtures.read_lot(api, counter_id, env["lot_a"]["id"])["remaining_weight_kg"], 10.000
    )


def test_04_a_zero_request_and_a_previously_frozen_lot_share_the_eligibility_refusal(api):
    """PRD §3.9: "Approving a conversion requires the event's `status` to be `VALUED`, its
    `reason` to be `UNSOLD_FRESH`, its `conversion_requested_kg` to be greater than 0.000, and
    the lot's `previously_frozen` to be false; any of those failing yields
    `ERR_CONVERSION_NOT_PERMITTED`."

    Design: Corner/validations/conversion_gates_reject_over_allowance_zero_request_and_frozen_lots
    """
    env = _three_valued_events_across_a_fresh_and_a_frozen_lot(api)
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)

    for event_id in (env["zero_request"]["id"], env["frozen_lot"]["id"]):
        validate_error(
            api.approve_conversion(event_id, {}, manager),
            ApiErrorId.ERR_CONVERSION_NOT_PERMITTED.value,
            expected_status=422,
        )

    for key in ("over_allowance", "zero_request", "frozen_lot"):
        event = fixtures.read_shrink_event(api, counter_id, env[key]["id"])
        assert event["status"] == "VALUED", f"{key} must still be VALUED"
        assert_weight(event["approved_conversion_kg"], 0.000)

    assert_weight(
        fixtures.read_lot(api, counter_id, env["lot_a"]["id"])["remaining_weight_kg"], 10.000
    )
    assert_weight(
        fixtures.read_lot(api, counter_id, env["lot_b"]["id"])["remaining_weight_kg"], 10.000
    )


def test_05_three_timestamp_orderings_are_policed_against_three_references(api):
    """PRD §3.6: "`ad_end_at` must be strictly after `ad_start_at`, failing which the draft is
    rejected with `ERR_AD_WINDOW_INVALID`."

    Design: Corner/validations/temporal_input_order_rules_on_readings_ads_and_documents
    """
    env = _received_snapper_lot_at_eight_oclock(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]

    equal_instants = api.create_ad_item(
        ad_item_payload(
            counter_id,
            lot_id,
            headline="Red Snapper Weekend",
            ad_start_at="2026-08-01T12:00:00Z",
            ad_end_at="2026-08-01T12:00:00Z",
        ),
        make_merchandising_lead_headers(),
    )
    validate_error(equal_instants, ApiErrorId.ERR_AD_WINDOW_INVALID.value, expected_status=422)

    post_dated = api.create_ice_bed_reading(
        ice_bed_reading_payload(counter_id, 3, "2026-08-01T09:00:00Z", 3.0),
        make_seafood_manager_headers(counter_id),
    )
    validate_error(post_dated, ApiErrorId.ERR_READING_IN_FUTURE.value, expected_status=422)

    landed_before_harvest = api.create_simp_document(
        simp_document_payload(
            lot_id,
            harvesting_vessel_name="Estrella del Golfo",
            harvest_date="2026-07-25T00:00:00Z",
            landing_date="2026-07-22T00:00:00Z",
            chain_of_custody_ref="COC-55210",
        ),
        make_supplier_rep_headers(env["supplier"]["id"]),
    )
    validate_error(landed_before_harvest, ApiErrorId.ERR_SIMP_DATE_ORDER.value, expected_status=422)


def test_06_each_refusal_has_a_legal_sibling_accepted_in_the_same_run(api):
    """PRD §3.7: "The `case_slot` must be at least 1 and at most the counter's
    `case_slot_count`, and `reading_at` must not be later than the logical clock — a reading from
    the future is rejected with `ERR_READING_IN_FUTURE`."

    Design: Corner/validations/temporal_input_order_rules_on_readings_ads_and_documents
    """
    env = _received_snapper_lot_at_eight_oclock(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]

    one_second_window = validate_success(
        api.create_ad_item(
            ad_item_payload(
                counter_id,
                lot_id,
                headline="Red Snapper Weekend",
                ad_start_at="2026-08-01T12:00:00Z",
                ad_end_at="2026-08-01T12:00:01Z",
            ),
            make_merchandising_lead_headers(),
        ),
        expected_status=201,
    )
    assert one_second_window["status"] == "DRAFT"

    at_the_clock = fixtures.submit_reading(api, counter_id, 3, "2026-08-01T08:00:00Z", 3.0)
    assert at_the_clock["breach"] is False

    same_day = fixtures.create_simp_document(
        api,
        env["supplier"]["id"],
        lot_id,
        harvesting_vessel_name="Estrella del Golfo",
        harvest_date="2026-07-22T00:00:00Z",
        landing_date="2026-07-22T00:00:00Z",
        chain_of_custody_ref="COC-55210",
    )
    assert_simp_document(same_day)
    assert same_day["status"] == "DRAFT"

    excursions = fixtures.list_excursions(api, counter_id)
    assert excursions == [], f"a compliant reading must open no excursion, got {excursions}"


def test_07_settlement_is_exact_amount_and_refuses_a_partial_payment(api):
    """PRD §2.9: "`ERR_SETTLEMENT_AMOUNT_MISMATCH` (422) — on chargeback settlement:
    `payment_amount_cents` equals the supplier's `chargeback_outstanding_cents` exactly."

    Design: Corner/validations/settlement_amount_must_equal_outstanding_exactly
    """
    env = _assessed_chargeback_of_forty_seven_thousand_eight_hundred_forty(api)
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot_id = env["lot"]["id"]

    assert_cents(fixtures.read_lot(api, counter_id, lot_id)["chargeback_assessed_cents"], 47840)

    partial = api.settle_chargeback(
        lot_id, {"payment_amount_cents": 40000}, make_supplier_rep_headers(supplier_id)
    )
    validate_error(partial, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH.value, expected_status=422)

    assert fixtures.read_lot(api, counter_id, lot_id)["chargeback_status"] == "ASSESSED"
    unpaid = fixtures.read_supplier(api, supplier_id)
    assert_cents(unpaid["chargeback_outstanding_cents"], 47840)
    assert_cents(unpaid["chargeback_settled_cents"], 0)

    settled = fixtures.settle_chargeback(api, supplier_id, lot_id, 47840)
    assert settled["chargeback_status"] == "SETTLED"

    supplier = fixtures.read_supplier(api, supplier_id)
    assert_cents(supplier["chargeback_assessed_total_cents"], 47840)
    assert_cents(supplier["chargeback_settled_cents"], 47840)
    assert_cents(supplier["chargeback_outstanding_cents"], 0)
    assert_cents(supplier["chargeback_reversed_cents"], 0)


def test_08_credit_hold_refuses_receipt_at_a_second_counter_until_reversal(api):
    """PRD §3.1: "A dealer whose `chargeback_outstanding_cents` has reached 75,000 cents, which
    is to say 750 dollars of unsettled mislabelling recovery, is on credit hold, and any attempt
    to receive one of its lots fails with `ERR_SUPPLIER_CREDIT_HOLD`."

    Design: Corner/validations/lot_receipt_blocked_while_the_supplier_is_on_credit_hold
    """
    env = _supplier_holding_a_hundred_and_forty_nine_thousand_outstanding(api)
    counter_b_id = env["counter_b"]["id"]
    supplier_id = env["supplier"]["id"]

    assert_cents(
        fixtures.read_lot(api, env["counter_a"]["id"], env["lot"]["id"])[
            "chargeback_assessed_cents"
        ],
        149000,
    )
    assert_cents(
        fixtures.read_supplier(api, supplier_id)["chargeback_outstanding_cents"], 149000
    )

    fresh_receipt = factories.lot_payload(
        counter_b_id,
        supplier_id,
        env["cod"]["id"],
        lot_code="COD-0801-J",
        received_weight_kg=8.000,
        unit_cost_cents_per_kg=2000,
        retail_price_cents_per_kg=3000,
        cooked_retail_price_cents_per_kg=3400,
    )
    held = api.create_lot(fresh_receipt, make_seafood_manager_headers(counter_b_id))
    validate_error(held, ApiErrorId.ERR_SUPPLIER_CREDIT_HOLD.value, expected_status=402)
    assert fixtures.read_counter(api, counter_b_id)["posture"] == "OPEN"

    reversed_lot = fixtures.reverse_chargeback(
        api,
        env["lot"]["id"],
        "lab retest cleared the supplier",
        officer_id=OFFICER_LEDGER_USER_ID,
    )
    assert reversed_lot["chargeback_status"] == "REVERSED"
    cleared = fixtures.read_supplier(api, supplier_id)
    assert_cents(cleared["chargeback_outstanding_cents"], 0)
    assert_cents(cleared["chargeback_reversed_cents"], 149000)
    assert_cents(cleared["chargeback_assessed_total_cents"], 149000)

    accepted = validate_success(
        api.create_lot(fresh_receipt, make_seafood_manager_headers(counter_b_id)),
        expected_status=201,
    )
    assert accepted["counter_id"] == counter_b_id
    assert accepted["intake_status"] == "RECEIVED"
