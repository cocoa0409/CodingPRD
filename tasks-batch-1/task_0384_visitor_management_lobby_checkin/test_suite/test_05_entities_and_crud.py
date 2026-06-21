"""Entity creation, defaults, type constraints, FK existence, and listing.

Corner queue (B): section entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    setup_site_floor_host, setup_site_host,
    create_site, create_floor, create_host, create_visit,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_create_site_returns_computed_badge_fields(api):
    """PRD 3.1: "At creation the site's `badge_in_use` is zero and its
    `badge_available` equals `badge_total`, establishing the badge-inventory invariant
    from the first moment."

    POST /sites with badge_total 7 -> 201; badge_in_use 0, badge_available 7.

    Note: the PRD defines `version` only as "a non-negative integer that increments by
    one on every mutation" (§2.4) and never names the value of a freshly created
    resource. Both an initial version of 0 (creation is the first persist, not a
    mutation of existing state) and 1 are PRD-faithful, so the concrete `version == 1`
    assertion was removed as a DEFAULT-VALUE SILENCE collapse (not uniquely derivable).

    Design: Corner/entities/create_site_returns_201_with_computed_badge_fields
    """
    res = api.create_site({"name": "HQ", "badge_total": 7}, SO)
    site = validate_success(res, 201)
    assert site["badge_in_use"] == 0, f"expected badge_in_use 0, got {site['badge_in_use']}"
    assert site["badge_available"] == 7, (
        f"expected badge_available 7, got {site['badge_available']}"
    )


def test_get_nonexistent_visit_returns_not_found(api):
    """PRD 2.6: "The system validates path identifiers left to right and rejects the
    first one that does not resolve to an existing resource with `ERR_NOT_FOUND`
    (HTTP 404)."

    GET /visits/{nonexistent} -> ERR_NOT_FOUND.

    Design: Corner/entities/get_visit_not_found_returns_404
    """
    res = api.get_visit(NON_EXISTENT_UUID, LA)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_visit_missing_visitor_full_name_rejected(api):
    """PRD 2.7: "Request well-formedness comes fourth: a missing required body field,
    an illegal enum value, or a numeric value outside its declared constraint (such as
    a negative `badge_total`) yields `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD 3.3: "The creating request supplies the `site_id`, the `host_id` of the host
    being visited, the `floor_id` the visitor will occupy, the visitor's
    `visitor_full_name` and `visitor_company`, and the planned `scheduled_start` and
    `scheduled_end` timestamps."

    Omitting required visitor_full_name -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_visit_missing_required_field_returns_invalid_request
    """
    site, floor, host = setup_site_floor_host()
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "visitor_company": "ACo",
            "scheduled_start": "2026-06-16T09:00:00Z",
            "scheduled_end": "2026-06-16T11:00:00Z",
        },
        LA,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_host_defaults_department_to_facilities(api):
    """PRD 3.1: "an optional `department` drawn from `ENGINEERING`, `SALES`,
    `FACILITIES`, or `EXECUTIVE` (defaulting to `FACILITIES`). Each host tracks a
    `notify_count` that starts at zero".

    Omitting department -> department FACILITIES, notify_count 0.

    Design: Corner/entities/create_host_default_department_facilities
    """
    site = create_site(badge_total=5)
    res = api.create_host(
        {"site_id": site["id"], "full_name": "Dana Host", "email": "dana@x.com"}, SO
    )
    host = validate_success(res, 201)
    assert host["department"] == "FACILITIES", (
        f"expected FACILITIES, got {host['department']}"
    )
    assert host["notify_count"] == 0, f"expected notify_count 0, got {host['notify_count']}"


def test_create_site_negative_badge_total_rejected(api):
    """PRD 3.1: "The `badge_total` must be zero or greater; a negative value is
    rejected as a constraint violation."
    PRD 2.7: "a numeric value outside its declared constraint (such as a negative
    `badge_total`) yields `ERR_INVALID_REQUEST` (HTTP 422)."

    badge_total -1 -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_site_negative_badge_total_returns_invalid_request
    """
    res = api.create_site({"name": "HQ", "badge_total": -1}, SO)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_delivery_bad_carrier_enum_rejected(api):
    """PRD 3.8: "recording the `carrier` — one of `FEDEX`, `UPS`, `USPS`, `DHL`, or
    `COURIER`".
    PRD 2.7: "Request well-formedness comes fourth: a missing required body field, an
    illegal enum value, or a numeric value outside its declared constraint ... yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    carrier 'OWL_POST' (not in the enum) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_visit_bad_carrier_enum_on_delivery_returns_invalid_request
    """
    site, host = setup_site_host()
    res = api.create_delivery(
        {"host_id": host["id"], "carrier": "OWL_POST", "parcel_fees_cents": [100]}, LA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_floor_with_nonexistent_site_returns_not_found(api):
    """PRD 2.6: "The same `ERR_NOT_FOUND` covers any foreign-key value in a request
    body that points at a non-existent row — for example, a `floor_id` or `host_id` on
    a visit, or a `visit_id` on an agreement, that names no such resource."

    POST /floors with a site_id that does not exist -> ERR_NOT_FOUND.

    Design: Corner/entities/create_floor_with_nonexistent_site_returns_not_found
    """
    res = api.create_floor(
        {"site_id": NON_EXISTENT_UUID, "label": "L3", "capacity": 5}, SO
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_visits_pagination_envelope(api):
    """PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD 2.3: "The `limit` parameter caps the number of items returned".

    Two visits exist for the host; GET /visits?limit=1 returns total_count 2 and
    has_more true.

    Design: Corner/entities/list_visits_pagination_envelope
    """
    site, floor, host = setup_site_floor_host()
    create_visit(site["id"], host["id"], floor["id"],
                 visitor_full_name="V One", visitor_company="OneCo")
    create_visit(site["id"], host["id"], floor["id"],
                 visitor_full_name="V Two", visitor_company="TwoCo")
    data, meta = validate_paginated(
        api.list_visits(LA, params={"limit": 1, "offset": 0, "host_id": host["id"]})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"
