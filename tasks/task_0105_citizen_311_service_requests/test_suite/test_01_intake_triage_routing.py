"""Intake, triage (priority + jurisdiction derivation), and routing.

Covers queue A (Difficulty): jurisdiction_match smallest-box selection and the
priority-drives-SLA-deadline evaluation order. Covers queue B (Corner): category
creation, not-found, required-field, defaults, system-managed status, the
triage invalid-transition, the no-box jurisdiction fallback, double-route,
notifications listing, no-SLA-policy at route, geolocation-required and
inactive-category intake guards, and maintenance-window routing block.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_category,
    assert_service_request,
    factories as fac,
    fixtures as fx,
    TEST_USERS,
    make_citizen_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: jurisdiction_match smallest-box selection
# ---------------------------------------------------------------------------
def _setup_overlapping_jurisdictions():
    """OUTER (area 0.0225) created first, INNER (area 0.0004) created second,
    a geo category, a citizen, and a request at a point inside BOTH boxes."""
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    outer = fx.create_jurisdiction(41.80, 41.95, -87.70, -87.55, name="OUTER")
    inner = fx.create_jurisdiction(41.87, 41.89, -87.64, -87.62, name="INNER")
    category = fx.create_category(dept["id"], requires_geolocation=True)
    citizen = fx.create_citizen()
    request = fx.create_request(
        citizen["id"], category["id"], description="pothole", lat=41.880, lng=-87.630
    )
    return outer, inner, request


def test_triage_selects_smallest_box_jurisdiction(api):
    """PRD §2.9: "When a point falls inside more than one box, the system selects
    the jurisdiction with the smallest box area, where area is computed as
    `(max_lat - min_lat)` multiplied by `(max_lng - min_lng)`; this deliberately
    picks the tightest (most specific) jurisdiction rather than the first one
    created."

    Design: Difficulty/dual_variant_calc/jurisdiction_match_smallest_box_vs_first_created
    """
    outer, inner, request = _setup_overlapping_jurisdictions()
    data = validate_success(
        api.triage_service_request(request["id"], {}, DISPATCHER), 200
    )
    assert data["jurisdiction_id"] == inner["id"], (
        f"Expected inner (smallest box) {inner['id']}, got {data['jurisdiction_id']}"
    )
    assert data["jurisdiction_id"] != outer["id"]


def test_triage_smallest_box_moves_request_to_triaged(api):
    """PRD §3.2: "A dispatcher then triages a `SUBMITTED` request, which moves it
    `SUBMITTED → TRIAGED`."
    PRD §2.9: "When a point falls inside more than one box, the system selects the
    jurisdiction with the smallest box area ... this deliberately picks the tightest
    (most specific) jurisdiction rather than the first one created."

    Design: Difficulty/dual_variant_calc/jurisdiction_match_smallest_box_vs_first_created
    """
    outer, inner, request = _setup_overlapping_jurisdictions()
    data = validate_success(
        api.triage_service_request(request["id"], {}, DISPATCHER), 200
    )
    assert data["status"] == "TRIAGED"
    assert data["jurisdiction_id"] == inner["id"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: priority drives SLA deadline (eval order)
# ---------------------------------------------------------------------------
def _setup_high_override_request():
    """Category default STANDARD; two SLA policies (STANDARD 24h, HIGH 4h);
    a request triaged with requested_priority HIGH at 2026-06-01T08:00:00Z."""
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"], priority="STANDARD", resolution_sla_hours=24,
                         escalation_tier1_hours=2, escalation_tier2_hours=6)
    fx.create_sla_policy(category["id"], priority="HIGH", resolution_sla_hours=4,
                         escalation_tier1_hours=1, escalation_tier2_hours=2)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"], requested_priority="HIGH")
    return request


def test_route_uses_high_priority_sla_deadline(api):
    """PRD §3.3: "When routing succeeds, the system stamps `routed_at` with the
    current logical instant and computes `sla_deadline_at` as that instant plus the
    matching policy's `resolution_sla_hours`, added as an exact whole-hour offset and
    stored to millisecond precision."
    PRD §3.2: "It sets the effective `priority`: if a `requested_priority` was supplied
    (either originally or as a triage-time override), that value becomes the priority;
    otherwise the category's `default_priority` is used."

    Design: Difficulty/combinatorial_formula/priority_drives_sla_deadline_eval_order_mode_c
    """
    request = _setup_high_override_request()
    data = validate_success(api.route_service_request(request["id"], DISPATCHER), 200)
    assert data["priority"] == "HIGH"
    assert data["routed_at"] == "2026-06-01T08:00:00.000Z"
    assert data["sla_deadline_at"] == "2026-06-01T12:00:00.000Z", (
        f"HIGH SLA is 4h => 12:00Z, got {data['sla_deadline_at']}"
    )


def test_triage_high_override_sets_priority_high(api):
    """PRD §3.2: "It sets the effective `priority`: if a `requested_priority` was
    supplied (either originally or as a triage-time override), that value becomes the
    priority; otherwise the category's `default_priority` is used."

    Design: Difficulty/combinatorial_formula/priority_drives_sla_deadline_eval_order_mode_c
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    data = validate_success(
        api.triage_service_request(request["id"], {"requested_priority": "HIGH"}, DISPATCHER),
        200,
    )
    assert data["priority"] == "HIGH"
    assert data["status"] == "TRIAGED"


# ---------------------------------------------------------------------------
# Queue B — Corner: entities
# ---------------------------------------------------------------------------
def test_create_category_returns_201_with_system_fields(api):
    """PRD §2.4: "Every resource is assigned an `id`, a server-minted UUID with no
    type prefix ... and a `version`, an integer that begins at its initial value and
    increments by one on every mutation."
    PRD §3.1: "Each category carries a `default_priority` — one of `LOW`, `STANDARD`,
    `HIGH`, or `EMERGENCY`, defaulting to `STANDARD` ... A category's `active` flag
    (default true) governs whether new intake referencing it is accepted."

    Design: Corner/entities/create_category_returns_201_with_system_fields
    """
    dept = fx.create_department(backlog_threshold=5)
    resp = api.create_category(
        fac.create_category_payload(dept["id"], name="Pothole", code="POTHOLE"),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_category(data)
    assert data["version"] == 1
    assert data["active"] is True
    assert data["default_priority"] == "STANDARD"


def test_get_service_request_not_found(api):
    """PRD §2.5: "The system validates the existence of every such identifier from
    left to right, returning `ERR_NOT_FOUND` (HTTP 404) on the first identifier that
    does not resolve to an existing resource before any deeper identifier or business
    rule is considered."

    Design: Corner/entities/get_service_request_not_found
    """
    citizen = fx.create_citizen()
    resp = api.get_service_request(
        "00000000-0000-4000-8000-000000000000", make_citizen_headers(citizen["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_request_missing_required_category_id(api):
    """PRD §3.2: "A citizen files a request by supplying their `citizen_id`, the chosen
    `category_id`, and a free-text `description`."
    PRD §2.6: "and finally a general request-body schema check yielding
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_request_missing_required_category_id
    """
    citizen = fx.create_citizen()
    resp = api.create_service_request(
        {"citizen_id": citizen["id"], "description": "no category"},
        make_citizen_headers(citizen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_citizen_notify_channel_default_applied(api):
    """PRD §3.1: "A citizen self-registers with a unique `email`, a `full_name`, and an
    optional `notify_channel` — one of `EMAIL`, `SMS`, or `NONE`, defaulting to `EMAIL`."

    Design: Corner/entities/citizen_notify_channel_default_applied
    """
    resp = api.create_citizen({"email": f"def{id(api)}@x.com", "full_name": "C"}, ANON)
    data = validate_success(resp, 201)
    assert data["notify_channel"] == "EMAIL"


def test_request_status_ignored_on_create(api):
    """PRD §3.2: "A successfully filed request is created in the `SUBMITTED` state with
    `priority`, `jurisdiction_id`, `department_id`, `cluster_id`, `sla_deadline_at`,
    `routed_at`, and `resolved_at` all still unset, `sla_breached` false, and
    `reopen_count` zero."

    Design: Corner/entities/request_status_ignored_on_create
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    resp = api.create_service_request(
        fac.create_service_request_payload(citizen["id"], category["id"], description="r"),
        make_citizen_headers(citizen["id"]),
    )
    data = validate_success(resp, 201)
    assert_service_request(data)
    assert data["status"] == "SUBMITTED"
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Queue B — Corner: state_machines / triage invalid transition
# ---------------------------------------------------------------------------
def test_triage_from_already_triaged_returns_invalid_state(api):
    """PRD §3.2: "Triage requires that the request currently be `SUBMITTED`."
    PRD §2.6: "(6) that the target resource is in a state from which the requested
    transition is defined, yielding `ERR_INVALID_STATE`."

    Design: Corner/state_machines/triage_from_already_triaged_returns_invalid_state
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"])
    resp = api.triage_service_request(request["id"], {}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Queue B — Corner: calculations / jurisdiction no-box fallback
# ---------------------------------------------------------------------------
def test_jurisdiction_match_no_box_yields_null(api):
    """PRD §2.9: "If the request has no latitude or no longitude, or if no box contains
    the point, the match yields no jurisdiction."
    PRD §3.2: "It sets `jurisdiction_id` by the smallest-box containment rule described
    in §2.9, leaving it null when the request has no coordinates or no box contains them."

    Design: Corner/calculations/jurisdiction_match_no_box_yields_null
    """
    dept = fx.create_department(backlog_threshold=5)
    fx.create_jurisdiction(10.0, 11.0, 10.0, 11.0, name="Far")
    category = fx.create_category(dept["id"], requires_geolocation=True)
    citizen = fx.create_citizen()
    request = fx.create_request(
        citizen["id"], category["id"], description="r", lat=41.8800, lng=-87.6300
    )
    data = validate_success(api.triage_service_request(request["id"], {}, DISPATCHER), 200)
    assert data["jurisdiction_id"] is None
    assert data["status"] == "TRIAGED"


# ---------------------------------------------------------------------------
# Queue B — Corner: endpoints / double-route + notifications
# ---------------------------------------------------------------------------
def test_double_route_blocked_one_workorder_per_request(api):
    """PRD §3.3: "an attempt to route a request that already has a work order is
    rejected with `ERR_DUPLICATE_WORK_ORDER` (HTTP 409)."
    PRD §2.6: "(6) that the target resource is in a state from which the requested
    transition is defined, yielding `ERR_INVALID_STATE`."

    Design: Corner/endpoints/double_route_blocked_one_workorder_per_request
    """
    env = fx.setup_routed_request()
    resp = api.route_service_request(env["request"]["id"], DISPATCHER)
    # The request is already ROUTED, so the state check (priority 6) fires first.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    _, meta = validate_paginated(
        api.list_work_orders(DISPATCHER, params={"request_id": env["request"]["id"]})
    )
    assert meta["total_count"] == 1, "a request has at most one work order"


def test_notifications_listed_for_request_after_triage(api):
    """PRD §3.2: "And it synthesizes a status notification recording the
    `SUBMITTED → TRIAGED` transition for the filing citizen."

    Design: Corner/endpoints/notifications_listed_for_request_after_triage
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"])
    data, meta = validate_paginated(
        api.list_request_notifications(request["id"], DISPATCHER)
    )
    assert meta["total_count"] >= 1
    assert data[0]["to_status"] == "TRIAGED"


# ---------------------------------------------------------------------------
# Queue B — Corner: validations on intake / route
# ---------------------------------------------------------------------------
def test_route_no_sla_policy_standalone(api):
    """PRD §3.3: "Routing requires that an SLA policy exist for the pair of the
    request's `category_id` and its effective `priority`; if none exists, routing is
    rejected with `ERR_NO_SLA_POLICY` (HTTP 409)."

    Design: Corner/validations/route_no_sla_policy_standalone
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"])
    resp = api.route_service_request(request["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NO_SLA_POLICY.value, 409)


def test_intake_geo_required_missing_coordinates(api):
    """PRD §3.2: "if the chosen category has `requires_geolocation` set, both `lat` and
    `lng` must be present or the filing is rejected with `ERR_GEOLOCATION_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/intake_geo_required_missing_coordinates
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=True)
    citizen = fx.create_citizen()
    resp = api.create_service_request(
        fac.create_service_request_payload(citizen["id"], category["id"], description="no geo"),
        make_citizen_headers(citizen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GEOLOCATION_REQUIRED.value, 422)


def test_intake_inactive_category_rejected(api):
    """PRD §3.2: "Intake against a category whose `active` is false is rejected with
    `ERR_CATEGORY_INACTIVE` (HTTP 409)."

    Design: Corner/validations/intake_inactive_category_rejected
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False, active=False)
    citizen = fx.create_citizen()
    resp = api.create_service_request(
        fac.create_service_request_payload(citizen["id"], category["id"], description="r"),
        make_citizen_headers(citizen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_INACTIVE.value, 409)


def test_routing_blocked_by_active_maintenance_window(api):
    """PRD §3.8: "For a maintenance window on the request's routed department, the
    instant is inside when it is at or after `starts_at` and at or before `ends_at`
    (closed on both ends). ... Either condition blocks routing with
    `ERR_WINDOW_BLOCKS_ROUTING` (HTTP 409)."

    Design: Corner/validations/routing_blocked_by_active_maintenance_window
    """
    fx.set_clock("2026-06-01T09:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    fx.api_client.create_service_window(
        fac.create_service_window_payload(
            "MAINTENANCE", "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z",
            department_id=dept["id"],
        ),
        ADMIN,
    )
    category = fx.create_category(dept["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"])
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"])
    resp = api.route_service_request(request["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_BLOCKS_ROUTING.value, 409)
    after = fx.get_request(request["id"])
    assert after["status"] == "TRIAGED"
