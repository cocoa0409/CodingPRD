"""Entity projections: computed defaults, stored disclosures, filters and derived statements."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_case_label,
    assert_cents,
    assert_counter,
    assert_ice_bed_reading,
    assert_instant,
    assert_risk_index,
    assert_species,
    assert_supplier,
    assert_supplier_lot,
    assert_weight,
)
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_READ_USER_ID,
    make_chain_admin_headers,
    make_compliance_officer_headers,
    make_seafood_manager_headers,
)


def _frozen_tilapia_lot(api) -> dict:
    """A farmed Tilapia lot grown in EC, processed in CN and received previously frozen."""
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)
    supplier = fixtures.register_supplier(api)
    tilapia = fixtures.register_tilapia(api)
    lot = fixtures.receive_tilapia_lot(
        api,
        counter["id"],
        supplier["id"],
        tilapia["id"],
        lot_code="TIL-0801-R",
        processing_country_code="CN",
        previously_frozen=True,
        fresh_claim=False,
        received_weight_kg=10.000,
        unit_cost_cents_per_kg=1500,
        retail_price_cents_per_kg=2100,
        cooked_retail_price_cents_per_kg=2400,
    )
    return {"counter": counter, "supplier": supplier, "tilapia": tilapia, "lot": lot}


def _three_cod_lots_one_cased(api) -> dict:
    """Three cod lots received in order A, B, C with lot A moved into slot 1."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    species_id = env["cod"]["id"]
    lot_a = fixtures.receive_lot(
        api, counter_id, supplier_id, species_id, received_weight_kg=10.000
    )
    lot_b = fixtures.receive_lot(
        api, counter_id, supplier_id, species_id,
        lot_code="COD-0801-B", received_weight_kg=10.000,
    )
    lot_c = fixtures.receive_lot(
        api, counter_id, supplier_id, species_id,
        lot_code="COD-0801-C", received_weight_kg=10.000,
    )
    fixtures.case_lot(api, counter_id, lot_a["id"], 1)
    env.update({"lot_a": lot_a, "lot_b": lot_b, "lot_c": lot_c})
    return env


def _two_cased_lots_of_contrasting_provenance(api) -> dict:
    """A previously frozen farmed lot in slot 1 and a plain wild lot in slot 2."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    tilapia = fixtures.register_tilapia(api)
    farmed = fixtures.receive_tilapia_lot(
        api,
        counter_id,
        supplier_id,
        tilapia["id"],
        lot_code="TIL-0801-R",
        processing_country_code="CN",
        previously_frozen=True,
        fresh_claim=False,
        received_weight_kg=10.000,
        unit_cost_cents_per_kg=1500,
        retail_price_cents_per_kg=2100,
        cooked_retail_price_cents_per_kg=2400,
    )
    fixtures.case_lot(api, counter_id, farmed["id"], 1)
    wild = fixtures.receive_lot(
        api,
        counter_id,
        supplier_id,
        env["cod"]["id"],
        previously_frozen=False,
        fresh_claim=False,
        received_weight_kg=10.000,
    )
    fixtures.case_lot(api, counter_id, wild["id"], 2)
    env.update({"tilapia": tilapia, "farmed": farmed, "wild": wild})
    return env


def test_01_counter_registration_returns_every_computed_default(api):
    """PRD §3.1: "A freshly registered counter starts with `posture` `OPEN`,
    `verification_cycle_index` 0, `open_excursion_count` 0, `violation_points` 0,
    `last_cycle_required_samples` 0, `last_cycle_max_supplier_risk_index` 0.00, and all three
    shrink ledger totals — `shrink_gross_cents`, `shrink_net_cents` and
    `recovered_conversion_cents` — at 0."

    Design: Corner/entities/counter_creation_populates_all_computed_defaults
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")

    response = api.create_counter(factories.counter_payload(), make_chain_admin_headers())
    counter = validate_success(response, expected_status=201)

    assert_counter(counter)
    assert counter["store_number"] == "4120"
    assert counter["department_name"] == "Seafood Service Counter"
    assert counter["case_slot_count"] == 6
    assert counter["posture"] == "OPEN"
    assert counter["open_excursion_count"] == 0
    assert counter["violation_points"] == 0
    assert counter["verification_cycle_index"] == 0
    assert counter["last_cycle_required_samples"] == 0
    assert_risk_index(counter["last_cycle_max_supplier_risk_index"], 0.00)
    assert_cents(counter["shrink_gross_cents"], 0)
    assert_cents(counter["shrink_net_cents"], 0)
    assert_cents(counter["recovered_conversion_cents"], 0)
    assert_instant(counter["created_at"], "2026-08-01T08:00:00Z")
    assert counter["version"] == 1


def test_02_a_lot_read_returns_every_stored_receipt_disclosure(api):
    """PRD §3.1: "A successfully received lot has `remaining_weight_kg` initialised to the
    full `received_weight_kg`, `received_at` stamped from the logical clock, and its three
    independent status dimensions initialised to `intake_status` `RECEIVED`, `label_status`
    `UNVERIFIED` and `chargeback_status` `NONE`, with `chargeback_assessed_cents` at 0 and
    `case_slot`, `cased_at` and `vacated_at` all null."

    Design: Corner/entities/lot_retrieval_returns_every_stored_receipt_disclosure
    """
    env = _frozen_tilapia_lot(api)

    response = api.get_lot(
        env["lot"]["id"], make_compliance_officer_headers(OFFICER_READ_USER_ID)
    )
    lot = validate_success(response, expected_status=200)

    assert_supplier_lot(lot)
    assert lot["lot_code"] == "TIL-0801-R"
    assert lot["harvest_method"] == "AQUACULTURE_POND"
    assert lot["production_method"] == "FARMED"
    assert lot["origin_country_code"] == "EC"
    assert lot["processing_country_code"] == "CN"
    assert lot["previously_frozen"] is True
    assert lot["fresh_claim"] is False
    assert_weight(lot["received_weight_kg"], 10.000)
    assert_weight(lot["remaining_weight_kg"], 10.000)
    assert_instant(lot["received_at"], "2026-08-01T08:00:00Z")
    assert lot["intake_status"] == "RECEIVED"
    assert lot["label_status"] == "UNVERIFIED"
    assert lot["chargeback_status"] == "NONE"
    assert_cents(lot["chargeback_assessed_cents"], 0)
    assert lot["case_slot"] is None
    assert lot["cased_at"] is None
    assert lot["vacated_at"] is None


def test_03_the_intake_status_filter_is_applied_before_the_page_is_cut(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside the envelope's `meta` object, where `total_count` is the number of records matching
    the request's filters before pagination is applied and `has_more` states whether any
    matching record remains beyond the returned page."

    Design: Corner/entities/lot_listing_filters_by_intake_status_and_paginates
    """
    env = _three_cod_lots_one_cased(api)
    counter_id = env["counter"]["id"]
    headers = make_seafood_manager_headers(counter_id)

    first_page, first_meta = validate_paginated(
        api.list_lots(
            headers,
            params={
                "counter_id": counter_id,
                "intake_status": "RECEIVED",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_lots(
            headers,
            params={
                "counter_id": counter_id,
                "intake_status": "RECEIVED",
                "limit": 1,
                "offset": 1,
            },
        )
    )

    assert first_meta["total_count"] == 2, "the CASED lot must not be counted"
    assert first_meta["has_more"] is True
    assert len(first_page) == 1
    assert first_page[0]["id"] == env["lot_b"]["id"]

    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert len(second_page) == 1
    assert second_page[0]["id"] == env["lot_c"]["id"]

    returned = {first_page[0]["id"], second_page[0]["id"]}
    assert env["lot_a"]["id"] not in returned, "lot A is CASED and must be filtered out"


def test_04_thirteen_existence_rules_answer_with_thirteen_distinct_codes(api):
    """PRD §2.5: "The first identifier that fails to resolve determines the returned 404
    error, and no later check runs."

    Design: Corner/entities/not_found_sweep_across_all_thirteen_existence_rules
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    headers = make_chain_admin_headers()

    probes = [
        (api.get_counter, ApiErrorId.ERR_COUNTER_NOT_FOUND),
        (api.get_supplier, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
        (api.get_species, ApiErrorId.ERR_SPECIES_NOT_FOUND),
        (api.get_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_case_label, ApiErrorId.ERR_CASE_LABEL_NOT_FOUND),
        (api.get_ad_item, ApiErrorId.ERR_AD_ITEM_NOT_FOUND),
        (api.get_ice_bed_reading, ApiErrorId.ERR_READING_NOT_FOUND),
        (api.get_excursion, ApiErrorId.ERR_EXCURSION_NOT_FOUND),
        (api.get_verification_sample, ApiErrorId.ERR_SAMPLE_NOT_FOUND),
        (api.get_simp_document, ApiErrorId.ERR_SIMP_DOCUMENT_NOT_FOUND),
        (api.get_certification, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (api.get_shrink_event, ApiErrorId.ERR_SHRINK_EVENT_NOT_FOUND),
        (api.get_violation, ApiErrorId.ERR_VIOLATION_NOT_FOUND),
    ]

    seen = []
    for read, expected in probes:
        error = validate_error(
            read(NON_EXISTENT_UUID, headers), expected.value, expected_status=404
        )
        seen.append(error["error_id"])

    assert len(set(seen)) == 13, f"expected thirteen distinct codes, got {sorted(set(seen))}"


def test_05_an_omitted_field_a_bad_enum_and_a_broken_bound_all_report_invalid_request(api):
    """PRD §2.9: "`ERR_INVALID_REQUEST` (400) — on every endpoint: every required body field
    is present, of the declared type, within its declared numeric bounds, and — for enumerated
    fields — one of the declared members."

    Design: Corner/entities/lot_receipt_rejects_missing_required_and_out_of_range_fields
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)

    without_origin = factories.lot_payload(
        counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    del without_origin["origin_country_code"]
    validate_error(
        api.create_lot(without_origin, manager),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    bad_enum = factories.lot_payload(
        counter_id,
        env["supplier"]["id"],
        env["cod"]["id"],
        harvest_method="WILD_TRAWL",
        received_weight_kg=10.000,
    )
    validate_error(
        api.create_lot(bad_enum, manager),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    out_of_bound = factories.counter_payload(
        store_number="4130", department_name="Second Counter", case_slot_count=0
    )
    validate_error(
        api.create_counter(out_of_bound, make_chain_admin_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    lots, _ = validate_paginated(api.list_lots(manager, params={"counter_id": counter_id}))
    assert lots == [], f"no lot may be written by a rejected receipt, got {lots}"
    counters, counter_meta = validate_paginated(api.list_counters(make_chain_admin_headers()))
    assert counter_meta["total_count"] == 1, "the out-of-bound registration must write no row"


def test_06_omitted_optional_inputs_fall_back_to_their_declared_defaults(api):
    """PRD §3.9: "Every shrink event, whether client-written or server-created, is valued
    immediately at cost and lands in `status` `VALUED` with `provisional_value_cents`
    populated and `approved_conversion_kg`, `allowance_kg`, `cook_yield_kg`,
    `final_value_cents` and `recovery_credit_cents` all at their zero defaults, `posted_at`,
    `reversed_at` and `reversal_note` null."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)

    payload = factories.shrink_event_payload(lot["id"], shrink_weight_kg=2.000)
    del payload["conversion_requested_kg"]
    event = validate_success(
        api.create_shrink_event(payload, make_seafood_manager_headers(counter_id)),
        expected_status=201,
    )
    label = fixtures.publish_case_label(api, counter_id, lot["id"])

    assert fixtures.read_lot(api, counter_id, lot["id"])["processing_country_code"] is None
    assert_weight(event["conversion_requested_kg"], 0.000)
    assert_weight(event["approved_conversion_kg"], 0.000)
    assert_weight(event["allowance_kg"], 0.000)
    assert event["status"] == "VALUED"
    assert_cents(event["provisional_value_cents"], 3650)
    assert_cents(event["final_value_cents"], 0)
    assert_cents(event["recovery_credit_cents"], 0)
    assert label["certification_id"] is None
    assert label["sustainability_claim_text"] is None
    assert label["withdraw_reason"] is None
    assert label["withdrawn_at"] is None


def test_07_a_client_supplied_id_and_version_are_ignored_on_dealer_registration(api):
    """PRD §2.4: "Most records additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that starts at 1 on creation and
    increments by one on every mutation of that record — including mutations the server
    performs on its own initiative as part of a cascade, and including refreshes of purely
    derived fields such as a counter's posture or shrink ledger totals."

    Design: Corner/entities/supplier_system_fields_are_server_minted_and_input_ignored
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")

    payload = factories.supplier_payload(id="client-chosen-id", version=77)
    supplier = validate_success(
        api.create_supplier(payload, make_chain_admin_headers()), expected_status=201
    )

    assert_supplier(supplier)
    assert supplier["id"] != "client-chosen-id"
    assert supplier["version"] == 1
    assert_instant(supplier["created_at"], "2026-08-01T08:00:00Z")
    assert_instant(supplier["updated_at"], "2026-08-01T08:00:00Z")
    assert supplier["name"] == "Gulf Bay Dealers"
    assert supplier["permit_number"] == "PERMIT-8801"


def test_08_a_species_and_a_probe_reading_carry_no_version_or_updated_at(api):
    """PRD §2.4: "A `Species` record is immutable configuration data and an `IceBedReading`
    is an append-only observation; both carry only `id` and `created_at`. Neither `updated_at`
    nor `version` exists on a `Species` or on an `IceBedReading`, and no request may expect
    those fields to appear on either."

    Design: Corner/entities/species_and_readings_are_immutable_rows_without_version
    """
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)
    cod = fixtures.register_atlantic_cod(api)
    reading = fixtures.submit_reading(api, counter["id"], 1, "2026-08-01T07:30:00Z", 4.0)
    reader = make_compliance_officer_headers(OFFICER_READ_USER_ID)

    species_read = validate_success(api.get_species(cod["id"], reader), expected_status=200)
    reading_read = validate_success(
        api.get_ice_bed_reading(reading["id"], reader), expected_status=200
    )

    assert_species(species_read)
    assert species_read["market_name"] == "Atlantic Cod"
    assert_ice_bed_reading(reading_read)
    assert reading_read["breach"] is False
    assert reading_read["taken_by_user_id"] == "assoc-7"
    assert fixtures.list_excursions(api, counter["id"]) == []


def test_09_a_farmed_label_names_both_countries_and_declares_previously_frozen(api):
    """PRD §3.4: "For a `FARMED` lot whose `processing_country_code` is non-null and differs
    from its `origin_country_code`, it is the words `Farm raised in `, then the
    `origin_country_code`, then `, processed in `, then the `processing_country_code` — for
    example, `Farm raised in EC, processed in CN`."

    Design: Corner/entities/case_label_statements_are_computed_from_lot_and_species
    """
    env = _two_cased_lots_of_contrasting_provenance(api)
    counter_id = env["counter"]["id"]

    label = fixtures.publish_case_label(api, counter_id, env["farmed"]["id"])

    assert_case_label(label)
    assert label["display_market_name"] == "Tilapia"
    assert label["origin_statement"] == "Farm raised in EC, processed in CN"
    assert label["production_method_statement"] == "FARM RAISED"
    assert label["frozen_disclosure_statement"] == "PREVIOUSLY FROZEN"
    assert label["status"] == "PUBLISHED"
    assert_instant(label["published_at"], "2026-08-01T08:00:00Z")


def test_10_a_wild_lot_with_no_fresh_claim_falls_through_to_the_bare_disclosure(api):
    """PRD §3.4: "`frozen_disclosure_statement` is resolved by a three-way ladder tested in
    this order: if `previously_frozen` is true the statement is the literal `PREVIOUSLY
    FROZEN`; otherwise if `fresh_claim` is true it is the literal `FRESH - NEVER FROZEN`;
    otherwise it is the literal `FRESH`."

    Design: Corner/entities/case_label_statements_are_computed_from_lot_and_species
    """
    env = _two_cased_lots_of_contrasting_provenance(api)
    counter_id = env["counter"]["id"]

    label = fixtures.publish_case_label(api, counter_id, env["wild"]["id"])

    assert_case_label(label)
    assert label["display_market_name"] == "Atlantic Cod"
    assert label["origin_statement"] == "Wild caught in US (WILD_LONGLINE)"
    assert label["production_method_statement"] == "WILD CAUGHT"
    assert label["frozen_disclosure_statement"] == "FRESH"
    assert label["frozen_disclosure_statement"] != "FRESH - NEVER FROZEN"
    assert label["status"] == "PUBLISHED"
    assert_instant(label["published_at"], "2026-08-01T08:00:00Z")


def test_11_slot_zero_slot_seven_and_probe_slot_nine_are_all_out_of_range(api):
    """PRD §2.9: "`ERR_CASE_SLOT_OUT_OF_RANGE` (422) — on casing a lot and on ice-bed reading
    submission: the submitted `case_slot` is at least 1 and at most the counter's
    `case_slot_count`."

    Design: Corner/entities/case_slot_bounds_rejected_below_one_and_above_slot_count
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )

    for slot in (0, 7):
        validate_error(
            api.case_lot(lot["id"], {"case_slot": slot}, manager),
            ApiErrorId.ERR_CASE_SLOT_OUT_OF_RANGE.value,
            expected_status=422,
        )
    validate_error(
        api.create_ice_bed_reading(
            factories.ice_bed_reading_payload(counter_id, 9, "2026-08-01T07:30:00Z", 4.0),
            manager,
        ),
        ApiErrorId.ERR_CASE_SLOT_OUT_OF_RANGE.value,
        expected_status=422,
    )

    readings, meta = validate_paginated(
        api.list_ice_bed_readings(manager, params={"counter_id": counter_id})
    )
    assert meta["total_count"] == 0, f"no reading may survive the bound check, got {readings}"

    cased = validate_success(
        api.case_lot(lot["id"], {"case_slot": 6}, manager), expected_status=200
    )
    assert cased["case_slot"] == 6
    assert cased["intake_status"] == "CASED"


def test_12_a_certificate_for_another_species_fails_the_claim_triplet(api):
    """PRD §2.9: "`ERR_CLAIM_NOT_SUBSTANTIATED` (422) — on case-label publication,
    advertisement drafting and the sustainability-claim review: when a `certification_id` is
    supplied, that certificate's `status` is `ACTIVE` and its `counter_id`, `supplier_id` and
    `species_id` all equal the lot's `counter_id`, `supplier_id` and `species_id`."

    Design: Corner/entities/certification_triplet_must_match_the_lot_it_labels
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    salmon = fixtures.register_species(api, factories.sockeye_salmon_payload())
    lot = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    certification = fixtures.file_certification(
        api,
        counter_id,
        supplier_id,
        salmon["id"],
        certificate_number="BOC-90411",
        claim_text="Certified sustainable salmon fishery",
    )
    fixtures.review_certification(
        api,
        certification["id"],
        "APPROVE",
        review_note="salmon certificate verified",
        officer_id=OFFICER_CLAIM_USER_ID,
    )

    payload = factories.case_label_payload(
        lot["id"],
        fixtures.lot_version(api, counter_id, lot["id"]),
        certification_id=certification["id"],
    )
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))

    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, expected_status=422)
    assert fixtures.read_certification(api, supplier_id, certification["id"])["status"] == "ACTIVE"
    assert fixtures.list_case_labels(api, counter_id, {"lot_id": lot["id"]}) == []
    assert fixtures.read_lot(api, counter_id, lot["id"])["intake_status"] == "CASED"
