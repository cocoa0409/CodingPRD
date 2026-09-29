"""Carrier onboarding: field contract, schema refusals, not-found codes and RBAC."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AUGMENT_ORDER_NOT_FOUND,
    ERR_CARRIER_NOT_FOUND,
    ERR_CDR_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_FACTOR_FILING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
    ERR_MEASUREMENT_NOT_FOUND,
    ERR_OFFER_NOT_FOUND,
    ERR_RECONCILIATION_CASE_NOT_FOUND,
    ERR_TARIFF_FILING_NOT_FOUND,
    ERR_TRUNK_GROUP_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_USAGE_BATCH_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_envelope,
    assert_error_payload_shape,
    assert_money,
    assert_versioned_entity,
)
from test_helpers.constants import (
    CARRIER_NAME,
    CARRIER_OCN,
    CARRIER_TYPE,
    SECOND_CARRIER_NAME,
    SECOND_CARRIER_OCN,
    SECOND_CARRIER_TYPE,
    T_2026_08_01,
)
from test_helpers.factories import carrier_payload, second_carrier_payload
from test_helpers.fixtures import setup_carrier

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_carrier_creation_returns_every_declared_field_with_zeroed_reserves(
    api, admin_headers
):
    """Registering the first carrier answers 201 with every reserve figure at 0.00.

    PRD 3.1: "A freshly registered carrier's six financial figures — `uncollectible_reserve_balance_usd`, `disputed_reserve_balance_usd`, `open_receivable_usd`, `disputed_receivable_usd`, `net_receivable_usd` — all initialise to 0.00, and are thereafter maintained entirely by the reserve recomputation of §2.11."
    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID with no type prefix and no client-supplied component, and a `created_at` timestamp in ISO 8601 UTC form with exactly three fractional digits, stamped from the logical clock at creation."
    PRD 2.5: "Before any request is made, the logical clock reads exactly `2026-08-01T00:00:00Z`; that is a mandatory startup default and the server never falls back to real time."

    Design: Corner/entities/carrier_creation_returns_every_declared_field_with_zeroed_reserves
    """
    empty, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 0, "the suite must start from an empty carrier table"
    assert empty == []

    response = api.create_carrier(carrier_payload(), admin_headers)
    carrier = validate_success(response, expected_status=201)

    assert is_valid_uuid(carrier["id"]), f"id must be a UUID, got {carrier['id']!r}"
    assert "_" not in carrier["id"] and "-" in carrier["id"]
    assert carrier["carrier_name"] == CARRIER_NAME
    assert carrier["ocn"] == CARRIER_OCN
    assert carrier["carrier_type"] == CARRIER_TYPE

    for field in (
        "uncollectible_reserve_balance_usd",
        "disputed_reserve_balance_usd",
        "open_receivable_usd",
        "disputed_receivable_usd",
        "net_receivable_usd",
    ):
        assert_money(carrier[field], 0.00, field)

    assert_versioned_entity(carrier, expected_version=1, label="carrier")
    assert carrier["created_at"] == T_2026_08_01, (
        f"created_at must be stamped from the logical clock default, got {carrier['created_at']}"
    )
    assert_envelope(response, "object")


def test_carrier_creation_without_ocn_is_an_invalid_request(api, admin_headers):
    """A registration missing the required `ocn` is a schema violation, not a duplicate.

    PRD 3.1: "A `PlatformAdmin` brings a counterparty onto the platform by registering it with a `carrier_name` of at most 120 characters, an `ocn` — the four-character, uppercase-alphanumeric Operating Company Number that identifies the carrier in industry databases — and a `carrier_type` drawn from `ILEC`, `CLEC`, `IXC` and `CMRS`, which is the regulatory classification that governs which rate elements may be billed against it."
    PRD 2.7: "**Request schema** — every required body field is present; types, enum membership, decimal scales, the string patterns for OCN, CLLI, LATA, NPA-NXX and calendar quarter, all declared numeric ranges, and the pagination bounds are satisfied. Any violation yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/carrier_creation_without_ocn_is_an_invalid_request
    """
    payload = carrier_payload()
    payload.pop("ocn")

    response = api.create_carrier(payload, admin_headers)
    validate_error(response, ERR_INVALID_REQUEST, expected_status=422)

    _, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 0, "a refused registration must not write a carrier"


def test_carrier_system_fields_input_ignored(api, admin_headers):
    """A client-supplied id, version and created_at are all discarded on registration.

    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID with no type prefix and no client-supplied component, and a `created_at` timestamp in ISO 8601 UTC form with exactly three fractional digits, stamped from the logical clock at creation."
    PRD 2.4: "Most resources additionally carry `updated_at`, refreshed to the logical clock on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 each time the row is mutated."

    Design: Corner/entities/carrier_system_fields_input_ignored
    """
    response = api.create_carrier(
        carrier_payload(
            id=UNKNOWN_ID, version=77, created_at="2020-01-01T00:00:00.000Z"
        ),
        admin_headers,
    )
    carrier = validate_success(response, expected_status=201)

    assert carrier["id"] != UNKNOWN_ID, "the client-supplied id must be discarded"
    assert is_valid_uuid(carrier["id"])
    assert carrier["version"] == 1, f"version must start at 1, got {carrier['version']}"
    assert carrier["created_at"] == T_2026_08_01, (
        f"created_at must come from the logical clock, got {carrier['created_at']}"
    )
    assert carrier["updated_at"] == T_2026_08_01


def test_carrier_type_outside_the_enum_is_an_invalid_request(api, admin_headers):
    """An unlisted carrier_type and a five-character OCN are both schema violations.

    PRD 3.1: "A `PlatformAdmin` brings a counterparty onto the platform by registering it with a `carrier_name` of at most 120 characters, an `ocn` — the four-character, uppercase-alphanumeric Operating Company Number that identifies the carrier in industry databases — and a `carrier_type` drawn from `ILEC`, `CLEC`, `IXC` and `CMRS`, which is the regulatory classification that governs which rate elements may be billed against it."
    PRD 2.7: "**Request schema** — every required body field is present; types, enum membership, decimal scales, the string patterns for OCN, CLLI, LATA, NPA-NXX and calendar quarter, all declared numeric ranges, and the pagination bounds are satisfied. Any violation yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/carrier_type_outside_the_enum_is_an_invalid_request
    """
    out_of_enum = api.create_carrier(carrier_payload(carrier_type="RBOC"), admin_headers)
    validate_error(out_of_enum, ERR_INVALID_REQUEST, expected_status=422)

    long_ocn = api.create_carrier(carrier_payload(ocn="92415"), admin_headers)
    validate_error(long_ocn, ERR_INVALID_REQUEST, expected_status=422)

    _, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 0, "neither refused registration may persist a carrier"


def test_unknown_ids_on_read_endpoints_return_their_own_not_found_error(
    api, admin_headers, planner_headers, analyst_headers
):
    """Carrier, measurement and call-record reads each answer their own 404 code.

    PRD 2.7: "Path parameters are resolved strictly left to right, and the first unresolvable segment decides the error."
    PRD 2.7: "Each addressable resource has exactly one path identifier, and the failure code follows from which identifier failed to resolve: a `carrier_id` segment yields `ERR_CARRIER_NOT_FOUND`; an `agreement_id` segment yields `ERR_AGREEMENT_NOT_FOUND`; an `offer_id` segment yields `ERR_OFFER_NOT_FOUND`; a `trunk_group_id` segment yields `ERR_TRUNK_GROUP_NOT_FOUND`; a `measurement_id` segment yields `ERR_MEASUREMENT_NOT_FOUND`; a `cdr_id` segment yields `ERR_CDR_NOT_FOUND`; an `order_id` segment, which addresses a trunk augment order, yields `ERR_AUGMENT_ORDER_NOT_FOUND`; a `filing_id` segment, which addresses a tariff filing, yields `ERR_TARIFF_FILING_NOT_FOUND`; a `factor_filing_id` segment yields `ERR_FACTOR_FILING_NOT_FOUND`; a `batch_id` segment, which addresses a usage batch, yields `ERR_USAGE_BATCH_NOT_FOUND`; an `invoice_id` segment yields `ERR_INVOICE_NOT_FOUND`; a `dispute_id` segment yields `ERR_DISPUTE_NOT_FOUND`; a `case_id` segment, which addresses a reconciliation case, yields `ERR_RECONCILIATION_CASE_NOT_FOUND`; and an `entry_id` segment addresses a single reserve ledger entry."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/unknown_ids_on_read_endpoints_return_their_own_not_found_error
    """
    _, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 0, "no carrier, measurement or call record exists yet"

    reads = (
        (api.get_carrier(UNKNOWN_ID, admin_headers), ERR_CARRIER_NOT_FOUND),
        (
            api.get_traffic_measurement(UNKNOWN_ID, planner_headers),
            ERR_MEASUREMENT_NOT_FOUND,
        ),
        (api.get_call_detail_record(UNKNOWN_ID, analyst_headers), ERR_CDR_NOT_FOUND),
    )
    for response, expected_error in reads:
        validate_error(response, expected_error, expected_status=404)
        assert_envelope(response, "error")
        data = assert_error_payload_shape(response)
        assert data["message"], f"{expected_error} must carry a human-readable message"


def test_unknown_negotiation_and_trunk_ids_return_their_own_not_found_ids(
    api, admin_headers, planner_headers
):
    """Offer, trunk group and augment order reads each answer their own 404 code.

    PRD 2.7: "Path parameters are resolved strictly left to right, and the first unresolvable segment decides the error."
    PRD 2.7: "All thirteen not-found codes carry HTTP 404."
    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/unknown_negotiation_and_trunk_ids_return_their_own_not_found_ids
    """
    setup_carrier(api)

    reads = (
        (api.get_offer(UNKNOWN_ID, admin_headers), ERR_OFFER_NOT_FOUND),
        (api.get_trunk_group(UNKNOWN_ID, planner_headers), ERR_TRUNK_GROUP_NOT_FOUND),
        (
            api.get_augment_order(UNKNOWN_ID, planner_headers),
            ERR_AUGMENT_ORDER_NOT_FOUND,
        ),
    )
    for response, expected_error in reads:
        validate_error(response, expected_error, expected_status=404)
        assert_envelope(response, "error")
        assert_error_payload_shape(response)
        assert set(response.json()["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, "an error meta block carries only the two request fields"


def test_unknown_filing_and_batch_ids_return_their_own_not_found_ids(
    api, regulator_headers, analyst_headers
):
    """Tariff filing, factor filing and usage batch reads each answer their own 404 code.

    PRD 2.7: "Path parameters are resolved strictly left to right, and the first unresolvable segment decides the error."
    PRD 2.7: "All thirteen not-found codes carry HTTP 404."

    Design: Corner/errors/unknown_filing_and_batch_ids_return_their_own_not_found_ids
    """
    setup_carrier(api)

    reads = (
        (
            api.get_tariff_filing(UNKNOWN_ID, regulator_headers),
            ERR_TARIFF_FILING_NOT_FOUND,
        ),
        (
            api.get_factor_filing(UNKNOWN_ID, analyst_headers),
            ERR_FACTOR_FILING_NOT_FOUND,
        ),
        (api.get_usage_batch(UNKNOWN_ID, analyst_headers), ERR_USAGE_BATCH_NOT_FOUND),
    )
    for response, expected_error in reads:
        validate_error(response, expected_error, expected_status=404)
        assert_error_payload_shape(response)


def test_unknown_billing_ids_return_their_own_not_found_ids(
    api, analyst_headers, officer_headers, controller_headers
):
    """Invoice, dispute and reconciliation case reads each answer their own 404 code.

    PRD 2.7: "Path parameters are resolved strictly left to right, and the first unresolvable segment decides the error."
    PRD 2.7: "All thirteen not-found codes carry HTTP 404."

    Design: Corner/errors/unknown_billing_ids_return_their_own_not_found_ids
    """
    setup_carrier(api)

    reads = (
        (api.get_invoice(UNKNOWN_ID, analyst_headers), ERR_INVOICE_NOT_FOUND),
        (api.get_dispute(UNKNOWN_ID, officer_headers), ERR_DISPUTE_NOT_FOUND),
        (
            api.get_reconciliation_case(UNKNOWN_ID, controller_headers),
            ERR_RECONCILIATION_CASE_NOT_FOUND,
        ),
    )
    for response, expected_error in reads:
        validate_error(response, expected_error, expected_status=404)
        assert_error_payload_shape(response)


def test_request_with_no_role_header_is_unauthenticated(api, admin_headers):
    """A registration carrying neither identity header is refused before any other check.

    PRD 2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting in."
    PRD 2.1: "If either header is absent or empty, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD 2.7: "**Authentication** — both headers present and non-empty, else `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/request_with_no_role_header_is_unauthenticated
    """
    setup_carrier(api)

    response = api.create_carrier(
        second_carrier_payload(), {"Content-Type": "application/json"}
    )
    validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)

    carriers, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 1, "the unauthenticated request must write nothing"
    assert [row["ocn"] for row in carriers] == [CARRIER_OCN]


def test_network_planner_cannot_register_a_carrier(api, planner_headers, admin_headers):
    """Only PlatformAdmin registers carriers; the identical body succeeds as admin.

    PRD 2.1: "If both headers are present but the named role is not among the roles authorised for the endpoint being called, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "**`NetworkPlanner`** is the engineer who requests trunk groups, provisions and activates them, disconnects them at teardown, records traffic studies, and completes or reverses augment installation work."
    PRD 3.1: "A `PlatformAdmin` brings a counterparty onto the platform by registering it with a `carrier_name` of at most 120 characters, an `ocn` — the four-character, uppercase-alphanumeric Operating Company Number that identifies the carrier in industry databases — and a `carrier_type` drawn from `ILEC`, `CLEC`, `IXC` and `CMRS`, which is the regulatory classification that governs which rate elements may be billed against it."

    Design: Corner/rbac/network_planner_cannot_register_a_carrier
    """
    setup_carrier(api)
    body = second_carrier_payload()

    refused = api.create_carrier(dict(body), planner_headers)
    validate_error(refused, ERR_UNAUTHORIZED, expected_status=403)

    allowed = api.create_carrier(dict(body), admin_headers)
    second = validate_success(allowed, expected_status=201)
    assert second["ocn"] == SECOND_CARRIER_OCN
    assert second["carrier_name"] == SECOND_CARRIER_NAME
    assert second["carrier_type"] == SECOND_CARRIER_TYPE
    assert second["version"] == 1

    _, meta = validate_paginated(api.list_carriers(admin_headers))
    assert meta["total_count"] == 2, "only the role blocked the first attempt"
