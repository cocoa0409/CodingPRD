"""Building manifests: routes, stops, specimens, recurring templates, listing and access."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_driver_headers,
    make_lab_client_headers,
    create_route_payload,
    create_stop_payload,
    create_specimen_payload,
    assert_route,
    assert_same_instant,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Creating a route
# ---------------------------------------------------------------------------
def test_creating_a_stat_route_computes_its_sla_deadline(api):
    """PRD §3.2: "The route begins in `PLANNED` state."
    PRD §3.2: "On creation the route's `sla_deadline` is computed: the deadline is the
    `scheduled_start` plus 120 minutes (two hours) for a `STAT` run, or plus 480 minutes
    (eight hours) for a `SCHEDULED` run."

    Design: Corner/entities/create_route_returns_201_with_computed_sla
    """
    rate_card = fixtures.create_rate_card()
    lab = fixtures.create_lab_client()

    route = validate_success(
        api.create_route(
            create_route_payload(
                lab["id"], rate_card["id"],
                run_type="STAT",
                scheduled_start="2026-05-05T09:00:00Z",
                scheduled_end="2026-05-05T11:00:00Z",
            ),
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert_route(route)
    assert route["status"] == "PLANNED"
    assert_same_instant(route["sla_deadline"], "2026-05-05T11:00:00Z", "sla_deadline")


def test_creating_a_route_without_a_run_type_is_rejected(api):
    """PRD §3.2: "Creating one takes a `lab_client_id`, a `rate_card_id`, a `run_type` of
    `STAT` or `SCHEDULED`, a `scheduled_start`, a `scheduled_end`, and a
    `planned_total_miles` that must be zero or greater."
    PRD §3.2: "Its `scheduled_end` must be strictly later than its `scheduled_start`; a
    body that violates this — or that omits a required field or carries an out-of-range
    enum — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_route_missing_required_field_returns_400
    """
    rate_card = fixtures.create_rate_card()
    lab = fixtures.create_lab_client()

    payload = create_route_payload(lab["id"], rate_card["id"])
    payload.pop("run_type")

    resp = api.create_route(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_registering_a_specimen_with_an_inverted_temperature_band_is_rejected(api):
    """PRD §3.2: "Registering a **specimen** supplies a `pickup_stop_id`, a
    `dropoff_stop_id`, a `specimen_type` of `BLOOD`, `TISSUE`, `URINE`, `SWAB`, or
    `CULTURE`, a `temp_requirement` of `AMBIENT`, `REFRIGERATED`, or `FROZEN`, and an
    inclusive acceptable band given by `required_temp_min_c` and `required_temp_max_c`,
    where the maximum must be greater than or equal to the minimum (a body with the
    maximum below the minimum is rejected with `ERR_VALIDATION`)."

    Design: Corner/entities/create_specimen_invalid_temp_band_returns_400
    """
    rate_card = fixtures.create_rate_card()
    lab = fixtures.create_lab_client()
    route = fixtures.create_route(lab["id"], rate_card["id"])
    stop = fixtures.add_stop(route["id"], sequence=1, address="A", stop_kind="PICKUP",
                             planned_leg_miles=2.5)

    resp = api.add_specimen(
        route["id"],
        create_specimen_payload(
            stop["id"], stop["id"],
            specimen_type="BLOOD", temp_requirement="REFRIGERATED",
            required_temp_min_c=8, required_temp_max_c=2,
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_fetching_a_non_existent_route_is_rejected(api):
    """PRD §2.5: "When a path names a nested resource, the server validates identifiers
    left to right and returns the first failure it meets: a scan against a stop under a
    non-existent route surfaces `ERR_ROUTE_NOT_FOUND` before the stop is ever examined,
    and a missing stop surfaces `ERR_STOP_NOT_FOUND`, a missing specimen
    `ERR_SPECIMEN_NOT_FOUND`, and so on for `ERR_DRIVER_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_LAB_CLIENT_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`,
    `ERR_TEMPLATE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, and `ERR_BILLING_NOT_FOUND`."

    Design: Corner/entities/route_not_found_returns_404
    """
    resp = api.get_route(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------
def test_appending_a_stop_with_a_duplicate_sequence_is_rejected(api):
    """PRD §3.2: "A `sequence` already used on the route is rejected with
    `ERR_DUPLICATE_STOP_SEQUENCE`."

    Design: Corner/validations/add_stop_duplicate_sequence_returns_409
    """
    rate_card = fixtures.create_rate_card()
    lab = fixtures.create_lab_client()
    route = fixtures.create_route(lab["id"], rate_card["id"])
    fixtures.add_stop(route["id"], sequence=1, address="A", stop_kind="PICKUP",
                      planned_leg_miles=2.5)

    resp = api.add_stop(
        route["id"],
        create_stop_payload(sequence=1, address="B", stop_kind="DROPOFF", planned_leg_miles=3.5),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE.value)


# ---------------------------------------------------------------------------
# Recurring templates
# ---------------------------------------------------------------------------
def test_generating_a_route_from_a_template_synthesizes_its_stops(api):
    """PRD §3.2: "Instantiating a run from a template creates a new route in `PLANNED`
    state with its `template_id` set to the source template, synthesizes one stop from
    each `stop_specs` entry, and computes the route's service-level deadline."

    Design: Corner/cross_cutting_complexity_layers/generate_route_from_template_cascades_stops
    """
    ctx = fixtures.setup_template()

    route = validate_success(
        api.generate_route(
            ctx["template"]["id"],
            {"scheduled_start": "2026-05-05T09:00:00Z", "scheduled_end": "2026-05-05T11:00:00Z"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert route["status"] == "PLANNED"
    assert route["template_id"] == ctx["template"]["id"]

    stops, meta = validate_paginated(api.list_stops(DISPATCHER, params={"route_id": route["id"]}))
    assert meta["total_count"] == 2, (
        f"The two-entry stop_specs array must synthesize exactly two stops, "
        f"got {meta['total_count']}"
    )
    assert sorted(stop["sequence"] for stop in stops) == [1, 2]


# ---------------------------------------------------------------------------
# Listing and pagination
# ---------------------------------------------------------------------------
def test_route_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints are paginated through two query parameters. `limit` sets
    the maximum number of records returned; it defaults to 10, with a minimum of 1 and a
    maximum of 100. `offset` sets the number of records skipped and defaults to 0."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/routes_list_pagination_reports_total_and_has_more
    """
    rate_card = fixtures.create_rate_card()
    lab = fixtures.create_lab_client()
    fixtures.create_route(lab["id"], rate_card["id"], run_type="SCHEDULED")
    fixtures.create_route(
        lab["id"], rate_card["id"], run_type="STAT",
        scheduled_start="2026-05-06T09:00:00Z", scheduled_end="2026-05-06T11:00:00Z",
    )

    rows, meta = validate_paginated(
        api.list_routes(DISPATCHER, params={"lab_client_id": lab["id"], "limit": 1, "offset": 0})
    )
    assert len(rows) == 1, f"limit=1 must return a single record, got {len(rows)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------
def test_driver_cannot_dispatch_a_route(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation — or an ownership-scoped role reaches for a resource it does not
    own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A driver may record scans only against stops belonging to a route whose
    `driver_id` equals their own `X-User-ID`, and may read only their own routes, stops,
    specimens, and scan events."

    Dispatch is a dispatcher's operation; the route's own driver may not perform it.

    Design: Corner/rbac/driver_cannot_dispatch_returns_unauthorized
    """
    ctx = fixtures.setup_scenario(assign=True)
    resp = api.dispatch_route(ctx["route"]["id"], make_driver_headers(ctx["driver"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_lab_client_cannot_add_a_stop_to_another_labs_route(api):
    """PRD §2.1: "When `X-User-Role` is `LabClient`, `X-User-ID` is the `id` of the acting
    `LabClient`; ownership checks compare a resource's `lab_client_id` foreign key to
    `X-User-ID`. A laboratory may build routes, stops, and specimens only under its own
    `lab_client_id`, and may read only its own routes, specimens, exceptions, and
    billings."

    Design: Corner/rbac/labclient_cannot_add_stop_to_other_labs_route_returns_unauthorized
    """
    ctx = fixtures.setup_two_labs_with_route_owned_by_first()

    resp = api.add_stop(
        ctx["route"]["id"],
        create_stop_payload(sequence=1, address="A", stop_kind="PICKUP", planned_leg_miles=2.5),
        make_lab_client_headers(ctx["lab_b"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
