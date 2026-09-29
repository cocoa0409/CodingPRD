"""Endpoint-level behaviour: the consolidated dossier read, the clock capability,
disposition, and the three error families the envelope must carry."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_instant_equals,
    create_approved_revision,
    create_field_incident_payload,
    create_joint_sample_payload,
    create_listing_body,
    create_listing_record_payload,
    create_product,
    create_product_payload,
    disposition_payload,
    freeze_design_payload,
    get_listing_record_data,
    get_lot_data,
    get_product_data,
    get_registration_data,
    get_reservation_data,
    make_certification_body_headers,
    open_lot,
    quarantine_payload,
    report_incident,
    run_campaign_to_passed,
    setup_frozen_product,
    setup_retail_released_product,
    setup_shipping_product_with_registered_units,
    start_campaign_payload,
    start_lot_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
SYSOP = TEST_USERS["system_operator_headers"]

MANDATED_KINDS = {
    "DUTY_RATING_LABEL",
    "WARNING_LABEL",
    "INSTRUCTION_LABEL",
    "RETAIL_CARTON",
    "ASSEMBLY_INSTRUCTION_SHEET",
    "CONSUMER_SAFETY_SHEET",
}


def test_the_liability_dossier_read_agrees_with_the_records_behind_it():
    """PRD §2.10: "It answers with `product_id`, `model_code`,
    `design_history_revision_count` (how many design revisions exist for the model),
    `approved_document_kinds` (the distinct `doc_kind` values that currently have an
    approved document), `passed_campaign_count` (how many of the model's test
    campaigns are in `PASSED`), `released_lot_count` (how many of the model's lots
    are in `RELEASED`), `open_incident_count` (how many of the model's field
    incidents have not yet reached a terminal status, that is, are neither
    `NOT_SUBSTANTIATED` nor `CLOSED`), `risk_score_gross`, `risk_score_mitigated`,
    `dhf_retention_until`, and `retention_anchor_source`."
    PRD §2.10: "When two or more candidates are exactly equal to the anchor,
    `retention_anchor_source` is decided by a fixed precedence: `LOT_RELEASE` first,
    then `INCIDENT_CLOSURE`, then `RECALL`, then `DESIGN_FREEZE`."

    Design: Corner/endpoints/liability_dossier_computed_read_matches_underlying_records
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    reported = report_incident(
        ctx["product"]["id"], incident_type="SLIP_FALL", injury_severity="MINOR"
    )
    assert reported["status"] == "REPORTED"

    dossier = validate_success(
        api_client.get_liability_dossier(ctx["product"]["id"], OFFICER)
    )

    assert dossier["product_id"] == ctx["product"]["id"]
    assert dossier["model_code"] == ctx["product"]["model_code"]
    assert dossier["design_history_revision_count"] == 1
    assert set(dossier["approved_document_kinds"]) == MANDATED_KINDS
    assert len(dossier["approved_document_kinds"]) == 6
    assert dossier["passed_campaign_count"] == 2
    assert dossier["released_lot_count"] == 1
    assert dossier["open_incident_count"] == 1
    assert float(dossier["risk_score_gross"]) == 0.00
    assert float(dossier["risk_score_mitigated"]) == 0.00
    assert_instant_equals(
        dossier["dhf_retention_until"], "2033-08-01T00:00:00Z", "dhf_retention_until"
    )
    assert dossier["retention_anchor_source"] == "LOT_RELEASE"


def test_filing_a_listing_record_resolves_both_of_its_foreign_keys():
    """PRD §2.5: "Existence of every foreign-key identifier in the request
    **body**, validated in the order the fields are declared for that operation,
    answering with `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_LISTING_BODY_NOT_FOUND`, `ERR_LISTING_RECORD_NOT_FOUND`,
    `ERR_PRODUCTION_LOT_NOT_FOUND`"
    PRD §3.5: "The same officer then files a **listing record** naming the
    `product_id`, the `listing_body_id` of the body that will own the listing, and
    the `standard_code` the model is to be listed against. A filed record begins at
    `status` `APPLIED` with `listed_at`, `audit_due_at`, `listing_expires_at`,
    `suspended_at`, and `suspension_reason` all null."

    Design: Corner/endpoints/listing_record_link_requires_existing_product_and_body
    """
    ctx = setup_frozen_product()
    body = create_listing_body(
        accredited_standards=["ANSI_ASC_A14_2"], audit_interval_days=180
    )

    unknown_body = api_client.create_listing_record(
        create_listing_record_payload(
            ctx["product"]["id"], NON_EXISTENT_UUID, standard_code="ANSI_ASC_A14_2"
        ),
        OFFICER,
    )
    validate_error(unknown_body, ApiErrorId.ERR_LISTING_BODY_NOT_FOUND.value, 404)

    record = validate_success(
        api_client.create_listing_record(
            create_listing_record_payload(
                ctx["product"]["id"], body["id"], standard_code="ANSI_ASC_A14_2"
            ),
            OFFICER,
        ),
        201,
    )

    assert record["status"] == "APPLIED"
    assert record["product_id"] == ctx["product"]["id"]
    assert record["listing_body_id"] == body["id"]
    assert record["listed_at"] is None
    assert record["audit_due_at"] is None
    assert record["listing_expires_at"] is None

    _, meta = validate_paginated(
        api_client.list_listing_records(OFFICER, {"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 1


def test_scrapping_a_quarantined_lot_moves_its_units_and_clears_the_holds():
    """PRD §3.6: "Scrapping moves the lot `QUARANTINED` → `SCRAPPED`, which is
    terminal, moves the whole `units_quarantined` bucket into `units_scrapped` with
    the conserved sum unchanged, sets `disposition` to `SCRAP`, clears `hold_flag` to
    false on every consumer registration of the lot, and recomputes the model's
    `held_registration_count`."
    PRD §3.6: "Choosing `SCRAP` is reserved to a `SafetyDirector`, and a
    `ProductionSupervisor` who asks for it is rejected with
    `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR` even though that supervisor is authorized to
    reach the disposition operation at all."

    Design: Corner/endpoints/scrap_disposition_action_moves_units_and_clears_holds
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    released_at = ctx["lot"]["released_at"]
    quarantined = validate_success(
        api_client.quarantine_production_lot(
            ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
        )
    )
    assert quarantined["units_quarantined"] == 400
    assert get_registration_data(ctx["registrations"][0]["id"])["hold_flag"] is True

    scrapped = validate_success(
        api_client.disposition_production_lot(
            ctx["lot"]["id"], disposition_payload("SCRAP"), DIRECTOR
        )
    )

    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["disposition"] == "SCRAP"
    assert scrapped["units_scrapped"] == 400
    assert scrapped["units_quarantined"] == 0
    assert scrapped["units_released"] == 0
    assert scrapped["released_at"] == released_at

    assert get_registration_data(ctx["registrations"][0]["id"])["hold_flag"] is False
    assert get_product_data(ctx["product"]["id"])["held_registration_count"] == 0


def test_moving_the_clock_only_affects_writes_that_come_after_it():
    """PRD §2.4: "The clock starts at `2026-08-01T00:00:00Z` when the process
    starts, never advances on its own, and is moved only by a `SystemOperator`
    supplying a `to_iso8601` instant to the clock-setting capability, which answers
    with the resulting `current_utc`."

    Design: Corner/endpoints/clock_endpoint_moves_the_logical_clock_for_later_writes
    """
    before = create_product()
    assert_instant_equals(before["created_at"], "2026-08-01T00:00:00Z", "created_at")

    clock = validate_success(
        api_client.set_clock("2026-08-20T00:00:00Z", SYSOP)
    )
    assert_instant_equals(clock["current_utc"], "2026-08-20T00:00:00Z", "current_utc")

    after = validate_success(
        api_client.create_product(
            create_product_payload(
                product_type="STEP_LADDER",
                material="ALUMINUM_EXTRUSION",
                duty_rating="TYPE_II",
                working_length_ft=12.0,
            ),
            ENGINEER,
        ),
        201,
    )

    assert_instant_equals(after["created_at"], "2026-08-20T00:00:00Z", "created_at")
    assert_instant_equals(after["updated_at"], "2026-08-20T00:00:00Z", "updated_at")

    untouched = get_product_data(before["id"])
    assert_instant_equals(untouched["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(untouched["updated_at"], "2026-08-01T00:00:00Z", "updated_at")


def test_freezing_the_design_stamps_the_retention_window_for_the_first_time():
    """PRD §3.7: "On success `design_status` moves `DRAFT` → `DESIGN_FROZEN`,
    `design_frozen_at` is stamped with the logical clock, `frozen_revision_id` is
    recorded, the model's `version` increments, and `dhf_retention_until` with
    `retention_anchor_source` is computed for the first time per §2.10 — on a model
    with no lots, no closed incidents, and no recall, the anchor is
    `design_frozen_at` and the source is `DESIGN_FREEZE`. Freezing never touches
    `market_status`."
    PRD §2.10: "Otherwise the anchor is the latest of the candidates that are not
    null, and `dhf_retention_until` is that anchor plus seven calendar years."

    Design: Corner/endpoints/freeze_design_conditional_action_stamps_retention_window
    """
    product = create_product(material="FIBERGLASS_PULTRUSION")
    revision = create_approved_revision(product["id"])
    qualification = run_campaign_to_passed(
        get_product_data(product["id"]), revision["id"], "DESIGN_QUALIFICATION"
    )
    assert qualification["status"] == "PASSED"

    frozen = validate_success(
        api_client.freeze_design(
            product["id"], freeze_design_payload(revision["id"]), APPROVER
        )
    )

    assert frozen["design_status"] == "DESIGN_FROZEN"
    assert frozen["frozen_revision_id"] == revision["id"]
    assert_instant_equals(
        frozen["design_frozen_at"], "2026-08-01T00:00:00Z", "design_frozen_at"
    )
    assert frozen["market_status"] == "NOT_RELEASED"
    assert_instant_equals(
        frozen["dhf_retention_until"], "2033-08-01T00:00:00Z", "dhf_retention_until"
    )
    assert frozen["retention_anchor_source"] == "DESIGN_FREEZE"


def test_every_resource_family_answers_its_own_not_found_code():
    """PRD §2.5: "Existence of every identifier in the request **path**, validated
    left to right, answering with the not-found code of the first unresolvable
    segment: `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_PRODUCT_DOCUMENT_NOT_FOUND`, `ERR_TEST_BENCH_NOT_FOUND`,
    `ERR_BENCH_RESERVATION_NOT_FOUND`, `ERR_TEST_CAMPAIGN_NOT_FOUND`,
    `ERR_PRODUCTION_LOT_NOT_FOUND`"
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"

    Design: Corner/errors/every_not_found_error_id_is_triggerable_with_unknown_ids
    """
    product = create_product()

    probes = [
        (api_client.get_product(NON_EXISTENT_UUID, OFFICER), "ERR_PRODUCT_NOT_FOUND"),
        (
            api_client.get_design_revision(NON_EXISTENT_UUID, OFFICER),
            "ERR_DESIGN_REVISION_NOT_FOUND",
        ),
        (
            api_client.approve_product_document(NON_EXISTENT_UUID, OFFICER),
            "ERR_PRODUCT_DOCUMENT_NOT_FOUND",
        ),
        (
            api_client.get_test_bench(NON_EXISTENT_UUID, OFFICER),
            "ERR_TEST_BENCH_NOT_FOUND",
        ),
        (
            api_client.get_bench_reservation(NON_EXISTENT_UUID, OFFICER),
            "ERR_BENCH_RESERVATION_NOT_FOUND",
        ),
        (
            api_client.get_test_campaign(NON_EXISTENT_UUID, OFFICER),
            "ERR_TEST_CAMPAIGN_NOT_FOUND",
        ),
        (
            api_client.get_production_lot(NON_EXISTENT_UUID, OFFICER),
            "ERR_PRODUCTION_LOT_NOT_FOUND",
        ),
        (
            api_client.create_listing_record(
                create_listing_record_payload(product["id"], NON_EXISTENT_UUID),
                OFFICER,
            ),
            "ERR_LISTING_BODY_NOT_FOUND",
        ),
        (
            api_client.get_listing_record(NON_EXISTENT_UUID, OFFICER),
            "ERR_LISTING_RECORD_NOT_FOUND",
        ),
        (
            api_client.get_consumer_registration(NON_EXISTENT_UUID, OFFICER),
            "ERR_CONSUMER_REGISTRATION_NOT_FOUND",
        ),
        (
            api_client.get_field_incident(NON_EXISTENT_UUID, OFFICER),
            "ERR_FIELD_INCIDENT_NOT_FOUND",
        ),
        (
            api_client.get_corrective_action(NON_EXISTENT_UUID, OFFICER),
            "ERR_CORRECTIVE_ACTION_NOT_FOUND",
        ),
        (
            api_client.get_recall_event(NON_EXISTENT_UUID, OFFICER),
            "ERR_RECALL_EVENT_NOT_FOUND",
        ),
    ]

    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == expected_error_id
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != ""


def test_each_already_advanced_entity_answers_its_own_state_conflict_code():
    """PRD §3.4: "Cancelling a `HELD` reservation moves it `HELD` → `CANCELLED`
    and subtracts its `duration_minutes` from the bench's `reserved_minutes_total`;
    cancellation requested on a reservation that is already `CONSUMED` or `CANCELLED`
    is rejected with `ERR_RESERVATION_NOT_HELD`."
    PRD §3.3: "Approval requested on a document that is already `APPROVED` or
    `SUPERSEDED` is rejected with `ERR_DOCUMENT_NOT_DRAFT`."
    PRD §3.4: "A campaign that is not `PLANNED` when a start is requested — and a
    campaign that is not `IN_PROGRESS` when a load test is recorded or a conclusion
    is requested — is rejected with `ERR_CAMPAIGN_STATE_INVALID`."
    PRD §3.5: "Granting the listing moves it `APPLIED` → `LISTED` and is gated on
    four things: the record must be `APPLIED`, or the request is rejected with
    `ERR_LISTING_STATE_INVALID`"

    Design: Corner/errors/state_conflict_errors_on_already_advanced_entities_rejected
    """
    ctx = setup_retail_released_product()
    campaign = ctx["qualification_campaign"]
    reservations, _ = validate_paginated(
        api_client.list_bench_reservations(
            TECHNICIAN, {"test_campaign_id": campaign["id"]}
        )
    )
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation["status"] == "CONSUMED"
    document = ctx["documents"][0]
    assert document["status"] == "APPROVED"

    validate_error(
        api_client.cancel_bench_reservation(reservation["id"], TECHNICIAN),
        ApiErrorId.ERR_RESERVATION_NOT_HELD.value,
        409,
    )
    validate_error(
        api_client.approve_product_document(document["id"], OFFICER),
        ApiErrorId.ERR_DOCUMENT_NOT_DRAFT.value,
        409,
    )
    validate_error(
        api_client.start_test_campaign(
            campaign["id"], start_campaign_payload(reservation["id"]), TECHNICIAN
        ),
        ApiErrorId.ERR_CAMPAIGN_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.grant_listing(
            ctx["listing_record"]["id"],
            make_certification_body_headers(ctx["listing_body"]["id"]),
        ),
        ApiErrorId.ERR_LISTING_STATE_INVALID.value,
        409,
    )

    assert get_reservation_data(reservation["id"])["status"] == "CONSUMED"
    assert validate_success(
        api_client.get_test_campaign(campaign["id"], TECHNICIAN)
    )["status"] == "PASSED"
    assert get_listing_record_data(ctx["listing_record"]["id"])["status"] == "LISTED"

    approved_rows, _ = validate_paginated(
        api_client.list_product_documents(
            ctx["product"]["id"], OFFICER, {"status": "APPROVED"}
        )
    )
    assert document["id"] in {row["id"] for row in approved_rows}


def test_missing_fields_unknown_enums_and_malformed_dates_share_one_code():
    """PRD §2.5: "Request-body shape on every creating or acting operation —
    required fields present, enum values drawn from their declared sets, numbers
    inside their declared ranges, datetimes valid ISO 8601 (`ERR_INVALID_REQUEST`)."
    PRD §3.6: "`quarantine_reason_code` is set to the supplied `reason_code` — one
    of `JOINT_INTEGRITY`, `LABEL_DEFECT`, `AUDIT_FAILURE`, or `FIELD_INCIDENT`"

    Design: Corner/errors/invalid_request_error_covers_shape_and_enum_and_range_rejected
    """
    ctx = setup_frozen_product(material="FIBERGLASS_PULTRUSION")
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)

    missing_field = create_joint_sample_payload(1, 462.00)
    missing_field.pop("pull_force_lbf")
    validate_error(
        api_client.create_joint_sample(lot["id"], missing_field, TECHNICIAN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.quarantine_production_lot(
            lot["id"], quarantine_payload("BECAUSE_I_SAID_SO"), SUPERVISOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_field_incident(
            create_field_incident_payload(
                ctx["product"]["id"],
                incident_type="SLIP_FALL",
                injury_severity="MINOR",
                occurred_at="20-07-2026",
            ),
            DIRECTOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 0
    assert reread["status"] == "IN_PROCESS"
    _, meta = validate_paginated(
        api_client.list_field_incidents(DIRECTOR, {"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 0
