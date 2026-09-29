"""Resource shapes, defaults, envelopes and the not-found discipline.

The registry entities are where the response envelope, the system-owned field
defaults, the closed enums and the two immutable event-record shapes are all
observable on a nearly empty store.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_bidder_headers


def test_01_creating_a_parcel_echoes_every_input_and_materialises_the_defaults(api):
    """The create response carries the six inputs, the four defaults and the envelope.

    "Recording one requires the assessor parcel number `apn` (1 to 40 characters,
    unique across every parcel in the inventory), a street `address` or legal
    location description, the parcel size in `acreage` which must be strictly
    greater than zero, the current `zoning_code`, the carrying value on the
    agency's books in `book_value_cents` which may not be negative, and
    `custodian_agency_id` naming the public agency that holds custody. A new parcel
    starts in `ownership_status` `AGENCY_OWNED`, `valuation_status` `UNVALUED`,
    `open_title_item_count` zero and `disposition_ready` false."

    Design: Corner/entities/create_parcel_returns_201_with_all_declared_fields
    """
    agency = fx.make_agency(api)
    response = api.create_parcel(
        f.parcel_payload(
            agency["id"],
            apn="APN-2693-101",
            address="9 Canal Street",
            acreage=3.1,
            zoning_code="M-1",
            book_value_cents=70000000,
        ),
        fx.OFFICER_HEADERS,
    )
    parcel = validate_success(response, 201)

    assert parcel["apn"] == "APN-2693-101", f"the apn is echoed, got {parcel['apn']!r}"
    assert parcel["address"] == "9 Canal Street", (
        f"as is the address, got {parcel['address']!r}"
    )
    assert parcel["acreage"] == 3.1, f"and the acreage, got {parcel['acreage']!r}"
    assert parcel["zoning_code"] == "M-1", (
        f"and the zoning code, got {parcel['zoning_code']!r}"
    )
    assert parcel["book_value_cents"] == 70000000, (
        f"and the carrying value, got {parcel['book_value_cents']}"
    )
    assert parcel["custodian_agency_id"] == agency["id"], (
        f"and the custodian, got {parcel['custodian_agency_id']!r}"
    )

    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        f"a new parcel is agency-owned, got {parcel['ownership_status']!r}"
    )
    assert parcel["valuation_status"] == "UNVALUED", (
        f"and unvalued, got {parcel['valuation_status']!r}"
    )
    assert parcel["open_title_item_count"] == 0, (
        f"with no open title item, got {parcel['open_title_item_count']}"
    )
    assert parcel["disposition_ready"] is False, (
        f"and not disposition-ready, got {parcel['disposition_ready']!r}"
    )

    assert is_valid_uuid(parcel["id"]), (
        f"the id is a server-minted UUID, got {parcel['id']!r}"
    )
    assert is_iso8601_timestamp(parcel["created_at"]), (
        f"created_at is an ISO 8601 instant, got {parcel['created_at']!r}"
    )
    assert is_iso8601_timestamp(parcel["updated_at"]), (
        f"as is updated_at, got {parcel['updated_at']!r}"
    )
    assert parcel["version"] == 1, (
        f"and the row version starts at 1, got {parcel['version']}"
    )

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource is an object, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"the request id is prefixed, got {body['meta']['api_request_id']!r}"
    )
    assert body["meta"]["api_request_timestamp"], (
        "and the envelope stamps the request instant"
    )


def test_02_reading_a_parcel_back_returns_the_row_that_was_stored(api):
    """Every input field survives the round trip and any role may read it.

    "The parcel list can be narrowed by `custodian_agency_id` — the reverse lookup
    from an agency to the parcels it holds — and by `ownership_status`,
    `valuation_status` and `disposition_ready`."

    Design: Corner/entities/get_parcel_by_id_returns_stored_entity
    """
    agency = fx.make_agency(api)
    created = fx.make_parcel(
        api,
        agency["id"],
        apn="APN-2693-102",
        address="11 Canal Street",
        acreage=2.5,
        zoning_code="C-2",
        book_value_cents=51000000,
    )
    bidder = fx.make_bidder(api)

    response = api.get_parcel(created["id"], make_bidder_headers(bidder["id"]))
    parcel = validate_success(response, 200)
    assert response.json()["response_type"] == "object", (
        "a single-resource read is an object envelope"
    )

    assert parcel["id"] == created["id"], (
        f"the same row comes back, got {parcel['id']!r}"
    )
    assert parcel["apn"] == "APN-2693-102", (
        f"with the stored apn, got {parcel['apn']!r}"
    )
    assert parcel["acreage"] == 2.5, f"the stored acreage, got {parcel['acreage']!r}"
    assert parcel["zoning_code"] == "C-2", (
        f"the stored zoning code, got {parcel['zoning_code']!r}"
    )
    assert parcel["book_value_cents"] == 51000000, (
        f"the stored carrying value, got {parcel['book_value_cents']}"
    )
    assert parcel["custodian_agency_id"] == agency["id"], (
        f"and the stored custodian, got {parcel['custodian_agency_id']!r}"
    )
    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        f"still agency-owned, got {parcel['ownership_status']!r}"
    )
    assert parcel["valuation_status"] == "UNVALUED", (
        f"and still unvalued, got {parcel['valuation_status']!r}"
    )


def test_03_the_custodian_filter_is_applied_before_the_total_is_counted(api):
    """total_count reports the filtered population, not the whole inventory.

    "List responses populate four pagination fields inside `meta`: `limit` and
    `offset` echo the effective values used for the query, `total_count` reports how
    many records match the filters before pagination is applied, and `has_more` is
    true exactly when records remain beyond the returned page."

    Design: Corner/entities/list_parcels_filtered_by_custodian_agency_returns_paginated_envelope
    """
    agency_a = fx.make_agency(api)
    agency_b = fx.make_transit_agency(api)
    for number, book_value in ((103, 30000000), (104, 31000000), (105, 32000000)):
        fx.make_parcel(
            api,
            agency_a["id"],
            apn=f"APN-2693-{number}",
            address=f"{number} Canal Street",
            acreage=1.0,
            book_value_cents=book_value,
        )
    fx.make_parcel(
        api,
        agency_b["id"],
        apn="APN-2693-106",
        address="6 Depot Road",
        acreage=1.0,
        book_value_cents=33000000,
    )

    rows, meta = validate_paginated(
        api.list_parcels(
            fx.OFFICER_HEADERS,
            {"custodian_agency_id": agency_a["id"], "limit": 2, "offset": 1},
        )
    )
    assert len(rows) == 2, f"a limit of 2 returns two rows, got {len(rows)}"
    for row in rows:
        assert row["custodian_agency_id"] == agency_a["id"], (
            f"every row is held by the filtered agency, got {row['custodian_agency_id']!r}"
        )
    assert meta["total_count"] == 3, (
        "the fourth parcel belongs to the other agency and is filtered out before "
        f"the count, got {meta['total_count']}"
    )
    assert meta["limit"] == 2, f"the effective limit is echoed, got {meta['limit']}"
    assert meta["offset"] == 1, f"as is the offset, got {meta['offset']}"
    assert meta["has_more"] is False, (
        "one skipped plus two returned exhausts the three matches, got "
        f"{meta['has_more']!r}"
    )
    assert all(row["apn"] != "APN-2693-106" for row in rows), (
        "the other agency's parcel never appears"
    )

    first_page, first_meta = validate_paginated(
        api.list_parcels(
            fx.OFFICER_HEADERS,
            {"custodian_agency_id": agency_a["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2, f"the first page holds two rows, got {len(first_page)}"
    assert first_meta["total_count"] == 3, (
        f"against the same filtered total, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        f"and a third match remains beyond it, got {first_meta['has_more']!r}"
    )


def test_04_reading_a_parcel_that_was_never_minted_is_a_parcel_not_found(api):
    """The miss is reported with the parcel's own 404 code, not a generic one.

    "Each entity has its own 404 code: `ERR_AGENCY_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
    `ERR_PREFERENCE_OFFER_NOT_FOUND`, `ERR_APPRAISER_NOT_FOUND`,
    `ERR_APPRAISAL_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`,
    `ERR_ENV_REVIEW_NOT_FOUND`, `ERR_TITLE_ITEM_NOT_FOUND`,
    `ERR_OFFERING_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
    `ERR_CONVEYANCE_NOT_FOUND` and `ERR_FUND_NOT_FOUND`, each returned with HTTP
    404."

    Design: Corner/entities/get_parcel_with_unknown_id_returns_parcel_not_found
    """
    fx.make_agency(api)

    response = api.get_parcel(NON_EXISTENT_UUID, fx.OFFICER_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_PARCEL_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error", (
        "a refusal carries the error envelope"
    )
    assert isinstance(error["message"], str) and error["message"], (
        f"with a non-empty message, got {error.get('message')!r}"
    )

    _, meta = validate_paginated(api.list_parcels(fx.OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        f"and no parcel was ever stored, got {meta['total_count']}"
    )


def test_05_omitting_the_required_apn_is_a_malformed_request(api):
    """A required source field with no default cannot be defaulted away.

    "Request shape is next: required fields present, enum values drawn from their
    declared members, every `_cents` integer at or above zero, every date field a
    parseable ISO 8601 UTC instant, and every declared list-length and numeric range
    respected."

    Design: Corner/entities/create_parcel_missing_required_apn_returns_invalid_request
    """
    agency = fx.make_agency(api)
    payload = f.parcel_payload(agency["id"])
    payload.pop("apn")

    response = api.create_parcel(payload, fx.OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_parcels(fx.OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "the refused create persists no partial row, got " f"{meta['total_count']}"
    )


def test_06_the_optional_agency_flags_are_materialised_at_creation(api):
    """Omitted optional fields come back carrying their declared defaults.

    "Two optional flags describe the agency's statutory standing:
    `is_preference_entity` records whether the agency holds a preference right on
    surplus land and defaults to false when omitted, and `preference_category`
    names the class of preference asserted — `AFFORDABLE_HOUSING`,
    `PARK_OPEN_SPACE`, `SCHOOL_SITE`, `INFILL_INFRASTRUCTURE` or `NONE` — and
    defaults to `NONE`. Every newly registered agency starts with
    `notice_registry_status` set to `REGISTERED`."

    Design: Corner/entities/create_agency_omitting_is_preference_entity_applies_default_false
    """
    response = api.create_agency(
        {
            "name": "Riverbend Transit District",
            "agency_type": "TRANSIT",
            "contact_email": "clerk@rtd.gov",
        },
        fx.ADMIN_HEADERS,
    )
    agency = validate_success(response, 201)

    assert agency["is_preference_entity"] is False, (
        f"the omitted flag defaults to false, got {agency['is_preference_entity']!r}"
    )
    assert agency["preference_category"] == "NONE", (
        f"the omitted category defaults to NONE, got {agency['preference_category']!r}"
    )
    assert agency["notice_registry_status"] == "REGISTERED", (
        "and the registry standing starts registered, got "
        f"{agency['notice_registry_status']!r}"
    )

    rows, meta = validate_paginated(
        api.list_agencies(fx.ADMIN_HEADERS, {"is_preference_entity": False})
    )
    assert meta["total_count"] == 1, (
        "the default is stored rather than left null, so the filter finds it, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == agency["id"], "and the row it finds is the new agency"


def test_07_client_supplied_system_fields_on_a_parcel_are_ignored(api):
    """The request is accepted and the usurped values are silently discarded.

    "Clients never supply an `id`; a client-supplied `id`, like any other
    client-supplied computed or system-owned field, is ignored rather than
    honoured."

    Design: Corner/entities/create_parcel_system_fields_input_ignored
    """
    agency = fx.make_agency(api)
    response = api.create_parcel(
        f.parcel_payload(
            agency["id"],
            apn="APN-2693-107",
            address="7 Canal Street",
            acreage=1.4,
            book_value_cents=20000000,
            ownership_status="CONVEYED",
            valuation_status="CURRENT",
            disposition_ready=True,
            open_title_item_count=9,
            id="client-chosen-id-2693",
            version=42,
        ),
        fx.OFFICER_HEADERS,
    )
    parcel = validate_success(response, 201)

    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        "the usurped ownership status is discarded, got "
        f"{parcel['ownership_status']!r}"
    )
    assert parcel["valuation_status"] == "UNVALUED", (
        f"as is the valuation status, got {parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        f"and the readiness flag, got {parcel['disposition_ready']!r}"
    )
    assert parcel["open_title_item_count"] == 0, (
        f"and the derived count, got {parcel['open_title_item_count']}"
    )
    assert parcel["id"] != "client-chosen-id-2693", (
        f"the id is server-minted, got {parcel['id']!r}"
    )
    assert is_valid_uuid(parcel["id"]), (
        f"and is a UUID with no embedded meaning, got {parcel['id']!r}"
    )
    assert parcel["version"] == 1, (
        f"and the row version starts at 1 regardless, got {parcel['version']}"
    )

    stored = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert stored["ownership_status"] == "AGENCY_OWNED", (
        "and what was persisted matches what was answered, got "
        f"{stored['ownership_status']!r}"
    )
    assert stored["disposition_ready"] is False, (
        f"on both fields, got {stored['disposition_ready']!r}"
    )


def test_08_an_agency_type_outside_the_declared_members_is_refused(api):
    """A closed enum is a set-membership test rather than a string type check.

    "A `SystemAdministrator` registers a public agency with its legal `name`
    (between 1 and 200 characters), its statutory class in `agency_type` — one of
    `STATE`, `COUNTY`, `MUNICIPAL`, `SCHOOL_DISTRICT`, `TRANSIT`,
    `HOUSING_AUTHORITY` or `FEDERAL` — and a `contact_email` to which statutory
    notices are delivered."

    Design: Corner/entities/create_agency_with_invalid_enum_agency_type_rejected
    """
    response = api.create_agency(
        {
            "name": "Orbital Works",
            "agency_type": "SPACE_AGENCY",
            "contact_email": "ops@orbital.example",
        },
        fx.ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert response.json()["response_type"] == "error", (
        "the refusal carries the error envelope"
    )

    _, meta = validate_paginated(api.list_agencies(fx.ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        f"and no agency was registered, got {meta['total_count']}"
    )


def test_09_a_body_foreign_key_naming_no_parcel_is_a_parcel_not_found(api):
    """A resolvable appraiser is not enough when the parcel does not exist.

    "The same codes are used for foreign keys carried in a request body rather than
    a path. A `parcel_id`, `custodian_agency_id`, `declaration_id`, `appraiser_id`,
    `counterparty_bidder_id`, `counterparty_agency_id`, or any entry of
    `recipient_agency_ids` that names no existing row produces the corresponding
    not-found code."

    Design: Corner/entities/create_appraisal_with_unknown_parcel_id_returns_not_found
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(
        api,
        agency["id"],
        apn="APN-2693-108",
        address="8 Canal Street",
        acreage=1.0,
        book_value_cents=25000000,
    )
    appraiser = fx.make_appraiser(api)
    version_before = fx.parcel_version(api, parcel["id"])

    response = api.create_appraisal(
        f.appraisal_order_payload(NON_EXISTENT_UUID, appraiser["id"], version_before),
        fx.OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PARCEL_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_appraisals(fx.OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused order books no engagement, got {meta['total_count']}"
    )
    stored = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert stored["version"] == version_before, (
        "and the real parcel's concurrency token is not spent: "
        f"{stored['version']} against {version_before}"
    )
    loaded = get_success_data(api.get_appraiser(appraiser["id"], fx.OFFICER_HEADERS))
    assert loaded["active_engagement_count"] == 0, (
        "nor is the appraiser engaged, got " f"{loaded['active_engagement_count']}"
    )


def test_10_a_negotiation_round_carries_no_updated_at_and_no_version(api):
    """The append-only evidentiary log deliberately carries less than a resource.

    "A `NegotiationRound` and a `ProceedsAllocation` each carry only `id` and
    `created_at`: neither exposes `updated_at` and neither exposes `version`. A
    negotiation round is never edited once tendered — it is the evidentiary log the
    good-faith score is computed from — and a proceeds allocation is never edited
    either; reversing one changes its own `status` and `reversed_at` fields only,
    which is the single exception to the no-mutation rule and does not introduce
    `updated_at` or `version` onto the row."

    Design: Corner/entities/negotiation_round_is_immutable_with_no_update_endpoint
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_preference_offer(api, ctx)

    response = api.append_round(
        ctx["offer"]["id"],
        f.officer_round_payload(
            price_offered_cents=66000000,
            terms_summary=(
                "Opening position at the affordable-housing floor plus carrying costs."
            ),
        ),
        fx.OFFICER_HEADERS,
    )
    round_row = validate_success(response, 201)

    assert round_row["round_number"] == 1, (
        f"the first round is numbered 1, got {round_row['round_number']}"
    )
    assert is_valid_uuid(round_row["id"]), (
        f"the row carries an id, got {round_row['id']!r}"
    )
    assert is_iso8601_timestamp(round_row["created_at"]), (
        f"and a creation instant, got {round_row['created_at']!r}"
    )
    assert "updated_at" not in round_row, (
        f"but no updated_at, got {sorted(round_row)}"
    )
    assert "version" not in round_row, f"and no version, got {sorted(round_row)}"

    rows, _ = validate_paginated(api.list_rounds(ctx["offer"]["id"], fx.OFFICER_HEADERS))
    assert len(rows) == 1, f"exactly one round stands on the log, got {len(rows)}"
    assert rows[0]["id"] == round_row["id"], "and it is the round just tendered"
    assert "version" not in rows[0], (
        f"which reads back with no version either, got {sorted(rows[0])}"
    )
    assert "updated_at" not in rows[0], (
        f"and no updated_at either, got {sorted(rows[0])}"
    )
