"""The first two rungs of the precedence ladder: identity, then existence."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    SUPPORT_HEADERS,
    ApiErrorId,
    api_client,
    assert_error_envelope,
    create_host_site_payload,
    create_station_payload,
    create_uptime_report_payload,
    make_headers,
    register_host_site,
    validate_error,
    validate_paginated,
)


def test_a_malformed_identity_outranks_both_a_bogus_path_id_and_a_bogus_body():
    """An auth gate implemented after body parsing leaks 404s and 400s.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity that user is acting in.
    If either header is missing or empty, or if `X-User-Role` is not one of the six
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401).  When the headers are well-formed but the acting role is not authorised
    for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."  PRD §2.11 puts "Header authentication — `ERR_UNAUTHENTICATED`"
    first and "Existence of every identifier" third, so that "the error the client
    sees is always the most fundamental one".

    Design: Corner/errors/request_without_identity_headers_is_rejected_before_every_other_check
    """
    site = register_host_site("HS-1", committed_service_capacity_kw=400.00)

    headerless = api_client.raw_get(f"/host-sites/{site['id']}")
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(headerless.json())

    empty_id = api_client.create_host_site(
        create_host_site_payload("HS-2", committed_service_capacity_kw=250.00),
        make_headers("", "NetworkOperator"),
    )
    validate_error(empty_id, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(empty_id.json())

    unknown_role = api_client.create_station(
        create_station_payload(site["id"], "ST-1", declared_port_count=1),
        make_headers("op-1", "SiteInspector"),
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(unknown_role.json())

    headerless_and_missing = api_client.raw_get(f"/host-sites/{NON_EXISTENT_UUID}")
    validate_error(headerless_and_missing, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(headerless_and_missing.json())

    rows, meta = validate_paginated(api_client.list_host_sites(OPERATOR_HEADERS))
    assert len(rows) == 1, "not one of the four rejected calls wrote anything"
    assert meta["total_count"] == 1


def test_each_missing_identifier_names_the_entity_that_is_actually_absent():
    """A single generic not-found id would hide which lookup failed.

    PRD §2.5: "Any request that names resources resolves them before it evaluates
    business rules.  Identifiers embedded in the URL path are resolved **left to
    right**, and the first path segment that names nothing aborts the request with
    that segment's own 404 error.  A request for the ports of a non-existent station
    therefore fails with `ERR_STATION_NOT_FOUND`, never with a port-level error."
    PRD §2.5 on body-borne keys: "foreign keys carried in the request body are
    resolved in this declaration order: `host_site_id`, `station_id`, `port_id`,
    `outage_event_id`, `dispatch_id`, `spare_part_id`, `uptime_report_id`,
    `complaint_id`, and finally each `port_id` inside `line_items`.  The matching
    failures are `ERR_HOST_SITE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
    `ERR_PORT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`,
    `ERR_SPARE_PART_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
    `ERR_UPTIME_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and
    `ERR_COMPLAINT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/unknown_identifiers_return_entity_specific_not_found_errors
    """
    register_host_site("HS-1", committed_service_capacity_kw=400.00)

    validate_error(
        api_client.get_host_site(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_HOST_SITE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_station(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_STATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_charging_port(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_PORT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_outage_event(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_OUTAGE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_maintenance_dispatch(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_DISPATCH_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_spare_part(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_SPARE_PART_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_part_reservation(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_RESERVATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_uptime_report(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_UPTIME_REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_reimbursement_claim(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_customer_complaint(NON_EXISTENT_UUID, SUPPORT_HEADERS),
        ApiErrorId.ERR_COMPLAINT_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_station(
            create_station_payload(NON_EXISTENT_UUID, "ST-1", declared_port_count=1),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_HOST_SITE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.list_station_charging_ports(NON_EXISTENT_UUID, OPERATOR_HEADERS),
        ApiErrorId.ERR_STATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_uptime_report(
            create_uptime_report_payload(
                NON_EXISTENT_UUID, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_STATION_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(api_client.list_host_sites(OPERATOR_HEADERS))
    assert meta["total_count"] == 1, "no rejected call leaked a partial write"
