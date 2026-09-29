"""Record shapes: created defaults, derived fields, reads, listing and rejects."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_instant_equals,
    assert_timestamp_format,
    create_campaign,
    create_draft_revision,
    create_joint_sample_payload,
    create_consumer_registration_payload,
    create_field_incident_payload,
    create_listing_body_payload,
    create_load_test_payload,
    create_product,
    create_product_document_payload,
    create_product_payload,
    create_production_lot_payload,
    create_test_bench,
    create_test_bench_payload,
    get_product_data,
    is_valid_uuid,
    open_lot,
    reserve_bench,
    setup_frozen_product,
    setup_released_lot,
    start_campaign,
    start_lot_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
CONSUMER = TEST_USERS["consumer_headers"]


def test_product_creation_returns_every_derived_threshold():
    """PRD §3.1: "`rated_load_lb` is 200 pounds for `TYPE_III`, 225 for
    `TYPE_II`, 250 for `TYPE_I`, 300 for `TYPE_IA`, and 375 for `TYPE_IAA`."
    PRD §3.1: "`required_test_load_lb` is `rated_load_lb` multiplied by the
    already-rounded `safety_factor`, the product rounded half up to two decimal
    places; this is the load a qualifying static test must reach."
    PRD §3.1: "A newly catalogued model starts with `design_status` at `DRAFT`,
    `market_status` at `NOT_RELEASED`, `held_registration_count` at 0,
    `risk_score_gross` and `risk_score_mitigated` both at 0.00"

    Design: Corner/entities/product_creation_returns_all_derived_thresholds
    """
    payload = create_product_payload(
        product_type="STEP_LADDER",
        material="ALUMINUM_EXTRUSION",
        duty_rating="TYPE_II",
        working_length_ft=12.0,
    )

    product = validate_success(api_client.create_product(payload, ENGINEER), 201)

    assert product["model_code"] == payload["model_code"]
    assert product["product_type"] == "STEP_LADDER"
    assert product["material"] == "ALUMINUM_EXTRUSION"
    assert product["duty_rating"] == "TYPE_II"
    assert float(product["working_length_ft"]) == 12.0
    assert product["retail_sku"] == payload["retail_sku"]

    assert float(product["rated_load_lb"]) == 225
    assert float(product["safety_factor"]) == 4.00
    assert float(product["required_test_load_lb"]) == 900.00
    assert float(product["required_pull_force_lbf"]) == 337.50
    assert float(product["max_allowed_deflection_in"]) == 0.800

    assert product["design_status"] == "DRAFT"
    assert product["market_status"] == "NOT_RELEASED"
    assert product["version"] == 1
    assert is_valid_uuid(product["id"])


def test_design_revision_read_returns_its_stored_engineering_fields():
    """PRD §3.2: "A new revision begins at `status` `DRAFT` with `review_round`
    at 1, and with `submitted_by_user_id`, `reviewed_by_user_id`,
    `reviewer_notes`, and `superseded_at` all null."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/design_revision_retrieval_returns_stored_fields
    """
    product = create_product()
    revision = create_draft_revision(
        product["id"],
        revision_label="A",
        joint_type="RIVETED",
        structural_margin_pct=6.50,
        rail_section_modulus_in3=0.250,
    )

    response = api_client.get_design_revision(revision["id"], ENGINEER)
    data = validate_success(response)

    assert data["id"] == revision["id"]
    assert data["product_id"] == product["id"]
    assert data["revision_label"] == "A"
    assert data["joint_type"] == "RIVETED"
    assert float(data["structural_margin_pct"]) == 6.50
    assert float(data["rail_section_modulus_in3"]) == 0.250
    assert data["status"] == "DRAFT"
    assert data["review_round"] == 1
    assert data["submitted_by_user_id"] is None
    assert data["superseded_at"] is None

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]


def test_product_list_reports_total_count_has_more_and_honours_filters():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.5: "Products may be filtered by `frozen_revision_id`,
    `product_type`, `material`, `duty_rating`, `design_status`, and
    `market_status`."

    Design: Corner/entities/product_listing_pagination_reports_total_count_and_has_more
    """
    create_product(material="FIBERGLASS_PULTRUSION")
    aluminium = create_product(material="ALUMINUM_EXTRUSION")
    create_product(material="FIBERGLASS_PULTRUSION")

    rows, meta = validate_paginated(
        api_client.list_products(OFFICER, {"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api_client.list_products(OFFICER, {"limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_products(OFFICER, {"material": "ALUMINUM_EXTRUSION"})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == aluminium["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_unknown_production_lot_read_returns_a_not_found_error():
    """PRD §2.5: "Existence of every identifier in the request **path**,
    validated left to right, answering with the not-found code of the first
    unresolvable segment: `ERR_PRODUCT_NOT_FOUND`,
    `ERR_DESIGN_REVISION_NOT_FOUND`, `ERR_PRODUCT_DOCUMENT_NOT_FOUND`,
    `ERR_TEST_BENCH_NOT_FOUND`, `ERR_BENCH_RESERVATION_NOT_FOUND`,
    `ERR_TEST_CAMPAIGN_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`"

    Design: Corner/entities/production_lot_not_found_returns_404
    """
    response = api_client.get_production_lot(NON_EXISTENT_UUID, SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""


def test_test_bench_creation_without_cooldown_minutes_is_rejected():
    """PRD §3.4: "A `TestLabTechnician` registers a **test bench** with a
    globally unique `bench_code`, a `max_load_capacity_lb` greater than zero, and
    a `cooldown_minutes` buffer between zero and 480 minutes"
    PRD §2.5: "Request-body shape on every creating or acting operation —
    required fields present, enum values drawn from their declared sets, numbers
    inside their declared ranges, datetimes valid ISO 8601
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/test_bench_missing_required_cooldown_minutes_rejected
    """
    payload = create_test_bench_payload()
    payload.pop("cooldown_minutes")

    response = api_client.create_test_bench(payload, TECHNICIAN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api_client.list_bench_reservations(TECHNICIAN))
    assert meta["total_count"] == 0, "the rejected request created nothing"


def test_product_document_optional_fields_take_their_documented_defaults():
    """PRD §3.3: "Three further fields are optional in the payload:
    `placement_zone`, `pictogram_count`, which defaults to 0, and
    `includes_assembly_instructions`, which defaults to false. Documents begin at
    `status` `DRAFT` with `approved_at` null."

    Design: Corner/entities/product_document_defaults_applied_when_optional_fields_omitted
    """
    product = create_product()
    payload = create_product_document_payload(
        product["id"], "CONSUMER_SAFETY_SHEET", document_version="1.0"
    )

    document = validate_success(
        api_client.create_product_document(payload, OFFICER), 201
    )

    assert document["pictogram_count"] == 0
    assert document["includes_assembly_instructions"] is False
    assert document["placement_zone"] is None
    assert document["status"] == "DRAFT"
    assert document["approved_at"] is None
    assert document["version"] == 1


def test_new_production_lot_starts_with_every_counter_at_zero():
    """PRD §3.6: "A new lot begins at `status` `OPEN` with `produced_units`,
    `units_wip`, `units_quarantined`, `units_released`, and `units_scrapped` all
    0, with `joint_sample_count`, `joint_fail_count`, and
    `required_joint_sample_count` all 0, with `conformance_index` null, and with
    `released_at`, `quarantine_reason_code`, and `disposition` null."
    PRD §3.6: "while `produced_units` is 0 the required count stays 0."

    Design: Corner/entities/production_lot_counter_fields_are_computed_at_create
    """
    ctx = setup_frozen_product(material="FIBERGLASS_PULTRUSION")
    payload = create_production_lot_payload(
        ctx["product"]["id"],
        ctx["revision"]["id"],
        planned_units=500,
        pultrusion_batch_id="PB-77",
    )

    lot = validate_success(api_client.create_production_lot(payload, SUPERVISOR), 201)

    assert lot["planned_units"] == 500
    assert lot["produced_units"] == 0
    assert lot["units_wip"] == 0
    assert lot["units_quarantined"] == 0
    assert lot["units_released"] == 0
    assert lot["units_scrapped"] == 0
    assert lot["status"] == "OPEN"
    assert lot["joint_sample_count"] == 0
    assert lot["joint_fail_count"] == 0
    assert lot["required_joint_sample_count"] == 0
    assert lot["conformance_index"] is None
    assert lot["released_at"] is None
    assert lot["quarantine_reason_code"] is None
    assert lot["disposition"] is None


def test_consumer_registration_recall_event_id_is_server_computed():
    """PRD §3.8: "A new registration begins at `registration_status`
    `REGISTERED` with `hold_flag` false, `recall_event_id` null, and
    `notified_at`, `acknowledged_at`, and `remedy_choice` all null"

    Design: Corner/entities/consumer_registration_recall_event_id_is_computed_not_input
    """
    ctx, lot = setup_released_lot(produced_units=400)
    payload = create_consumer_registration_payload(
        lot["id"], purchase_channel="ONLINE", serial_suffix="0009"
    )

    registration = validate_success(
        api_client.create_consumer_registration(payload, CONSUMER), 201
    )

    assert registration["recall_event_id"] is None
    assert registration["registration_status"] == "REGISTERED"
    assert registration["hold_flag"] is False
    assert registration["notified_at"] is None
    assert registration["acknowledged_at"] is None
    assert registration["remedy_choice"] is None
    assert get_product_data(ctx["product"]["id"])["held_registration_count"] == 0


def test_listing_body_creation_generates_the_common_system_fields():
    """PRD §2.4: "Every persisted resource carries an `id`, which is a
    server-minted UUID with no type prefix, and a `created_at` timestamp
    formatted as ISO 8601 UTC with three fractional digits."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation, and `version`, an integer that
    increments by one on every mutation"

    Design: Corner/entities/listing_body_system_fields_generated_on_create
    """
    payload = create_listing_body_payload(
        accredited_standards=["ANSI_ASC_A14_2", "EN_131_2"], audit_interval_days=180
    )

    body = validate_success(api_client.create_listing_body(payload, OFFICER), 201)

    assert is_valid_uuid(body["id"])
    assert_timestamp_format(body["created_at"])
    assert_instant_equals(body["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(body["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert body["version"] == 1
    assert body["accredited_standards"] == ["ANSI_ASC_A14_2", "EN_131_2"]
    assert body["audit_interval_days"] == 180


def test_product_creation_with_an_unknown_duty_rating_or_length_is_rejected():
    """PRD §3.1: "`duty_rating` is the declared duty class and is one of
    `TYPE_III`, `TYPE_II`, `TYPE_I`, `TYPE_IA`, or `TYPE_IAA`."
    PRD §3.1: "`working_length_ft` is the maximum working length in feet,
    recorded to one decimal place; it must be greater than zero and no greater
    than 60 feet."

    Design: Corner/entities/product_invalid_duty_rating_enum_rejected
    """
    bad_enum = api_client.create_product(
        create_product_payload(product_type="STEP_LADDER", duty_rating="TYPE_IV"),
        ENGINEER,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    out_of_range = api_client.create_product(
        create_product_payload(product_type="STEP_LADDER", working_length_ft=61.0),
        ENGINEER,
    )
    validate_error(out_of_range, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api_client.list_products(OFFICER))
    assert meta["total_count"] == 0, "neither request persisted a row"


def test_load_test_rows_carry_no_version_or_updated_at():
    """PRD §2.4: "Two record types are append-only measurement records and
    therefore carry **only** `id` and `created_at`: a load test record and a
    joint integrity sample record. Neither has an `updated_at` field and neither
    has a `version` field."
    PRD §2.5: "a campaign's load tests accept `outcome` and `test_code`."

    Design: Corner/entities/load_test_immutable_entity_has_no_version_field
    """
    product = create_product()
    revision = create_draft_revision(product["id"])
    bench = create_test_bench()
    campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    reservation = reserve_bench(bench["id"], campaign["id"])
    start_campaign(campaign["id"], reservation["id"])
    recorded = validate_success(
        api_client.create_load_test(
            campaign["id"],
            create_load_test_payload(
                test_code="STATIC_VERTICAL", applied_load_lb=1400.00
            ),
            TECHNICIAN,
        ),
        201,
    )

    rows, _ = validate_paginated(
        api_client.list_load_tests(
            campaign["id"], TECHNICIAN, {"test_code": "STATIC_VERTICAL"}
        )
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == recorded["id"]
    assert row["outcome"] == "PASS"
    assert row["failure_reason_code"] is None
    assert "version" not in row
    assert "updated_at" not in row
    assert_timestamp_format(row["created_at"])


def test_joint_integrity_samples_are_immutable_measurement_records():
    """PRD §2.4: "Once written they are never modified and are never excluded
    from any aggregate that reads them."
    PRD §3.6: "Each sample snapshots the model's `required_pull_force_lbf` at
    insert time into its own `required_pull_force_lbf`, so later changes elsewhere
    cannot rewrite history, and its `result` is `PASS` when the measured
    `pull_force_lbf` is greater than or equal to that snapshot and `FAIL`
    otherwise."

    Design: Corner/entities/joint_integrity_sample_immutable_and_cannot_be_updated
    """
    ctx = setup_frozen_product(
        product_type="EXTENSION_LADDER",
        material="FIBERGLASS_PULTRUSION",
        duty_rating="TYPE_IA",
        working_length_ft=24.0,
    )
    assert float(ctx["product"]["required_pull_force_lbf"]) == 450.00
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    sample = validate_success(
        api_client.create_joint_sample(
            lot["id"], create_joint_sample_payload(1, 470.00), TECHNICIAN
        ),
        201,
    )

    rows, _ = validate_paginated(
        api_client.list_joint_samples(lot["id"], SUPERVISOR, {"result": "PASS"})
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == sample["id"]
    assert row["sample_seq"] == 1
    assert float(row["pull_force_lbf"]) == 470.00
    assert float(row["required_pull_force_lbf"]) == 450.00
    assert int(row["margin_pct"]) == 4
    assert row["result"] == "PASS"
    assert "version" not in row
    assert "updated_at" not in row


def test_field_incident_naming_an_unknown_lot_returns_not_found():
    """PRD §2.5: "Existence of every foreign-key identifier in the request
    **body**, validated in the order the fields are declared for that operation,
    answering with `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_LISTING_BODY_NOT_FOUND`, `ERR_LISTING_RECORD_NOT_FOUND`,
    `ERR_PRODUCTION_LOT_NOT_FOUND`"
    PRD §3.8: "Two optional links improve traceability: `production_lot_id` for
    the lot involved when it is traceable, and `consumer_registration_id` for the
    reporting consumer's registration when it is known."

    Design: Corner/entities/field_incident_unknown_production_lot_fk_returns_404
    """
    product = create_product()
    payload = create_field_incident_payload(
        product["id"],
        incident_type="SLIP_FALL",
        injury_severity="MINOR",
        production_lot_id=NON_EXISTENT_UUID,
    )

    response = api_client.create_field_incident(payload, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api_client.list_field_incidents(DIRECTOR, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0
    assert float(get_product_data(product["id"])["risk_score_gross"]) == 0.00
