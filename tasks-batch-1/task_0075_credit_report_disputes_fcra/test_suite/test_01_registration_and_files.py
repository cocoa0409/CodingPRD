"""Registration, credit files, tradeline creation, listings, and OCC success.

Translates queue B (Corner) instances from sections entities / endpoints /
errors / cross_cutting_complexity_layers, plus the queue A (Difficulty)
empty-collection boundary instance.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_consumer, assert_tradeline, find_notification,
    create_consumer_payload, create_furnisher_payload,
    create_credit_file_payload, create_tradeline_payload,
    make_bureau_headers, make_furnisher_headers, make_consumer_headers,
    make_regulator_headers,
    setup_consumer_furnisher_file,
)

BUREAU = make_bureau_headers()
REGULATOR = make_regulator_headers()


def _consumer():
    return validate_success(api_client.create_consumer(create_consumer_payload()), 201)


def _furnisher():
    return validate_success(api_client.create_furnisher(create_furnisher_payload()), 201)


def _file(consumer_id, **ov):
    return validate_success(
        api_client.create_credit_file(create_credit_file_payload(consumer_id, **ov), BUREAU), 201
    )


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

def test_register_consumer_returns_201_active(api):
    """PRD §3.1: "Every consumer is created in, and permanently remains in, the
    ACTIVE status; the status field is set by the system at registration and is
    never anything else in this model."
    PRD §2.4: "carries a server-minted id formatted as a UUID with no type prefix"

    Design: Corner/entities/create_consumer_returns_201_with_fields
    """
    data = validate_success(
        api.create_consumer(create_consumer_payload(email="n1@x.com", full_name="N One", ssn_last4="1234")),
        201,
    )
    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
    assert is_valid_uuid(data["id"]), "id must be a non-prefixed UUID"
    assert_consumer(data)


def test_create_tradeline_missing_balance_returns_validation(api):
    """PRD §3.2: "Creating one requires the credit_file_id it attaches to, the
    furnisher_id that owns it, an account_type of REVOLVING, INSTALLMENT, or
    COLLECTION, a balance_cents reported balance that must be an integer of at
    least 0, a date_of_first_delinquency (the DOFD), and a reported_delinquency_date"
    PRD §2.7: "well-formedness of the request body — required input fields present,
    enum members valid, and numeric types correct, such as a balance supplied as a
    non-negative integer (ERR_VALIDATION)"

    Design: Corner/entities/create_tradeline_required_field_missing_returns_validation
    """
    consumer = _consumer()
    furnisher = _furnisher()
    cfile = _file(consumer["id"])
    payload = create_tradeline_payload(cfile["id"], furnisher["id"])
    payload.pop("balance_cents")
    resp = api.create_tradeline(payload, make_furnisher_headers(furnisher["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_tradeline_reported_before_dofd_rejected(api):
    """PRD §3.2: "On creation the reported delinquency date must be on or after the
    date of first delinquency; a reported delinquency date earlier than the DOFD is
    rejected with ERR_INVALID_DELINQUENCY_DATE."

    Design: Corner/entities/invalid_delinquency_date_on_tradeline_create
    """
    consumer = _consumer()
    furnisher = _furnisher()
    cfile = _file(consumer["id"])
    resp = api.create_tradeline(
        create_tradeline_payload(
            cfile["id"], furnisher["id"],
            date_of_first_delinquency="2021-06-01T00:00:00.000Z",
            reported_delinquency_date="2021-01-01T00:00:00.000Z",
        ),
        make_furnisher_headers(furnisher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DELINQUENCY_DATE.value)


def test_get_consumer_nonexistent_returns_not_found(api):
    """PRD §2.6: "the system validates existence left to right and rejects the
    request with ERR_NOT_FOUND at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_consumer_nonexistent_returns_not_found
    """
    resp = api.get_consumer(NON_EXISTENT_UUID, BUREAU)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_tradeline_computed_fields_derived_server_side(api):
    """PRD §3.2: "The second derived field is purge_due_at ... it is the date of
    first delinquency plus seven years (modeled as seven times 365, i.e. 2555 days,
    with leap days ignored) plus a further 180 days."
    PRD §3.2: "reage_violation, a boolean that is true exactly when the reported
    delinquency date lies strictly after the date of first delinquency, and false
    when the two dates are equal"

    Design: Corner/entities/tradeline_computed_fields_ignore_client_input
    """
    consumer = _consumer()
    furnisher = _furnisher()
    cfile = _file(consumer["id"])
    data = validate_success(
        api.create_tradeline(
            create_tradeline_payload(
                cfile["id"], furnisher["id"],
                date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                reported_delinquency_date="2020-03-01T00:00:00.000Z",
            ),
            make_furnisher_headers(furnisher["id"]),
        ),
        201,
    )
    assert data["reage_violation"] is False
    assert data["purge_due_at"] == "2027-08-27T00:00:00.000Z", (
        f"Expected 2027-08-27T00:00:00.000Z, got {data['purge_due_at']}"
    )


def test_notification_is_append_only_no_version(api):
    """PRD §2.4: "Two resource types are append-only event records and therefore
    carry only id and created_at — they have neither an updated_at nor a version,
    because they are never modified after they are written. The first is the
    Notification, an immutable entry in the file's event log."

    Design: Corner/entities/notification_is_immutable_no_version_field
    """
    consumer = _consumer()
    cfile = _file(consumer["id"])
    api.clock_set("2026-01-05T00:00:00.000Z", BUREAU)
    validate_success(
        api.create_security_freeze(
            {
                "credit_file_id": cfile["id"],
                "freeze_type": "LOCK",
                "effective_at": "2026-01-05T00:00:00.000Z",
                "expected_credit_file_version": cfile["version"],
            },
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )
    data, meta = validate_paginated(
        api.list_file_notifications(cfile["id"], make_consumer_headers(consumer["id"]))
    )
    assert meta["total_count"] >= 1
    for item in data:
        assert "id" in item and "created_at" in item
        assert "version" not in item, "Notification must not carry a version field"
        assert "updated_at" not in item, "Notification must not carry an updated_at field"


def test_credit_file_bad_consumer_fk_returns_not_found(api):
    """PRD §2.6: "For any request that carries one or more resource identifiers,
    whether in the path or as foreign-key fields in the body, the system validates
    existence left to right and rejects the request with ERR_NOT_FOUND at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/flat_fk_integrity_credit_file_bad_consumer
    """
    resp = api.create_credit_file(
        create_credit_file_payload("11111111-1111-4111-8111-111111111111"), BUREAU
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Difficulty: empty_tradeline_set_count_and_listing
# ---------------------------------------------------------------------------

def test_empty_file_reports_zero_tradeline_count(api):
    """PRD §3.1: "A freshly opened file starts with a protection_state of OPEN, an
    open_dispute_count of 0, a tradeline_count of 0, and a version of 1."

    Design: Difficulty/boundary_precision_check/empty_tradeline_set_count_and_listing
    """
    consumer = _consumer()
    cfile = _file(consumer["id"], bureau_code="EXPERIAN")
    data = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert data["tradeline_count"] == 0, f"Expected 0, got {data['tradeline_count']}"


def test_empty_file_tradeline_listing_is_empty_array(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."
    PRD §3.1: "A freshly opened file starts with a protection_state of OPEN, an
    open_dispute_count of 0, a tradeline_count of 0, and a version of 1."

    Design: Difficulty/boundary_precision_check/empty_tradeline_set_count_and_listing
    """
    consumer = _consumer()
    cfile = _file(consumer["id"], bureau_code="EXPERIAN")
    resp = api.list_file_tradelines(cfile["id"], BUREAU)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 0, f"Expected total_count 0, got {meta['total_count']}"
    assert data == [], f"Expected empty array, got {data}"


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_list_credit_files_pagination_shape(api):
    """PRD §2.3: "The limit parameter specifies the maximum number of items to
    return; it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_credit_files_pagination_shape
    """
    consumer = _consumer()
    _file(consumer["id"], bureau_code="EQUIFAX")
    _file(consumer["id"], bureau_code="EXPERIAN")
    data, meta = validate_paginated(
        api.list_credit_files(BUREAU, params={"consumer_id": consumer["id"]})
    )
    assert meta["total_count"] == 2, f"Expected 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 2


def test_pagination_limit_out_of_range(api):
    """PRD §2.3: "A request whose limit falls outside 1 through 100, or whose offset
    is negative, is rejected with ERR_PAGINATION_RANGE."

    Design: Corner/endpoints/pagination_limit_out_of_range
    """
    consumer = _consumer()
    resp = api.list_credit_files(BUREAU, params={"consumer_id": consumer["id"], "limit": 500})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_RANGE.value)


def test_list_reverifications_filtered_by_furnisher(api):
    """PRD §3.5: "the bureau dispatches a reverification request to the furnisher
    that owns the disputed tradeline, supplying the dispute_id and the furnisher_id.
    ... Dispatch creates a reverification request in status PENDING"
    PRD Endpoint table: "GET /reverification-requests | List reverification requests,
    filterable by dispute or furnisher"

    Design: Corner/endpoints/list_reverifications_filtered_by_furnisher
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    tl = validate_success(
        api.create_tradeline(
            create_tradeline_payload(cfile["id"], furnisher["id"]),
            make_furnisher_headers(furnisher["id"]),
        ),
        201,
    )
    v = validate_success(api.get_credit_file(cfile["id"], BUREAU))["version"]
    dispute = validate_success(
        api.create_dispute(
            {
                "credit_file_id": cfile["id"], "tradeline_id": tl["id"],
                "dispute_reason": "NOT_MINE", "clock_mode": "CALENDAR",
                "expected_credit_file_version": v,
            },
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    rv = validate_success(
        api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU),
        201,
    )
    data, meta = validate_paginated(
        api.list_reverifications(make_furnisher_headers(furnisher["id"]), params={"furnisher_id": furnisher["id"]})
    )
    assert meta["total_count"] == 1, f"Expected 1, got {meta['total_count']}"
    assert data[0]["id"] == rv["id"]


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

def test_adjudicate_invalid_decision_returns_validation_error(api):
    """PRD §3.8: "the regulator adjudicates it by supplying a decision of either
    UPHOLD or DISMISS; any other decision value is rejected with ERR_INVALID_DECISION."

    Design: Corner/errors/invalid_decision_on_adjudicate
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    tl = validate_success(
        api.create_tradeline(create_tradeline_payload(cfile["id"], furnisher["id"]),
                             make_furnisher_headers(furnisher["id"])), 201)
    v = validate_success(api.get_credit_file(cfile["id"], BUREAU))["version"]
    dispute = validate_success(
        api.create_dispute(
            {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
             "clock_mode": "CALENDAR", "expected_credit_file_version": v},
            make_consumer_headers(consumer["id"])), 201)
    complaint = validate_success(
        api.create_complaint({"dispute_id": dispute["id"], "narrative": "Bad data."},
                             make_consumer_headers(consumer["id"])), 201)
    validate_success(api.review_complaint(complaint["id"], REGULATOR))
    resp = api.adjudicate_complaint(complaint["id"], {"decision": "MAYBE"}, REGULATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_DECISION.value)


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers (OCC success, reage-event append)
# ---------------------------------------------------------------------------

def test_freeze_with_correct_version_succeeds_and_increments(api):
    """PRD §2.8: "When a consumer places a security freeze on a credit file, the
    request must carry expected_credit_file_version matching that file's current
    version."
    PRD §3.7: "Placing a freeze recomputes the file's protection posture, mints a
    notification with event_code FREEZE_PLACED, and increments the file's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    consumer = _consumer()
    cfile = _file(consumer["id"])
    api.clock_set("2026-01-05T00:00:00.000Z", BUREAU)
    freeze = validate_success(
        api.create_security_freeze(
            {"credit_file_id": cfile["id"], "freeze_type": "LOCK",
             "effective_at": "2026-01-05T00:00:00.000Z",
             "expected_credit_file_version": cfile["version"]},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert freeze["status"] == "ACTIVE"
    after = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert after["version"] == cfile["version"] + 1, (
        f"Expected version {cfile['version'] + 1}, got {after['version']}"
    )


def test_reage_event_appended_on_direct_furnisher_reage(api):
    """PRD §3.2: "appends an immutable re-age event to the tradeline's audit trail.
    Each re-age event records the tradeline_id it concerns ... a was_violation
    boolean that is true when the new reported delinquency date is strictly later
    than the date of first delinquency at the moment of the event, and a
    source_dispute_id identifying the dispute whose reverification triggered the
    re-age, or null for a direct furnisher edit such as this one."

    Design: Corner/cross_cutting_complexity_layers/reage_event_appended_on_direct_furnisher_reage
    """
    consumer = _consumer()
    furnisher = _furnisher()
    cfile = _file(consumer["id"])
    tl = validate_success(
        api.create_tradeline(
            create_tradeline_payload(
                cfile["id"], furnisher["id"],
                date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                reported_delinquency_date="2020-03-01T00:00:00.000Z",
            ),
            make_furnisher_headers(furnisher["id"]),
        ),
        201,
    )
    validate_success(
        api.reage_tradeline(tl["id"], {"reported_delinquency_date": "2022-01-01T00:00:00.000Z"},
                           make_furnisher_headers(furnisher["id"]))
    )
    data, meta = validate_paginated(
        api.list_tradeline_reage_events(tl["id"], make_furnisher_headers(furnisher["id"]))
    )
    assert meta["total_count"] == 1, f"Expected 1, got {meta['total_count']}"
    assert data[0]["was_violation"] is True
    assert data[0]["source_dispute_id"] is None
