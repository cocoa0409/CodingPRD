"""Incidents, the review fork, the grounding cascade, and the maintenance work orders that
return an airframe to service."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_instant,
    assert_km,
    assert_money,
    assert_pct,
    create_drone,
    create_maintenance_log_payload,
    create_nest,
    create_ready_battery,
    create_service_area,
    install_battery,
    read_authorization,
    read_battery,
    read_customer,
    read_drone,
    read_flight,
    read_incident,
    read_maintenance_log,
    read_nest,
    read_order,
    set_clock,
    setup_grounding_cascade,
    setup_launched_flight,
    setup_open_incident,
    setup_reviewed_incident,
    setup_retired_pack_and_grounded_drone,
    setup_world,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


# ============================================================== filing and the fork
def test_incident_against_an_unknown_drone_is_not_found(api):
    """PRD §2.6: "A dangling body-level foreign key yields the corresponding not-found code,
    not a validation error."
    PRD §2.6: "The full family of not-found codes is `ERR_SERVICE_AREA_NOT_FOUND`,
    `ERR_NEST_NOT_FOUND`, `ERR_DRONE_NOT_FOUND`, `ERR_BATTERY_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`,
    `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_GEOFENCE_ZONE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    and `ERR_MAINTENANCE_LOG_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/errors/incident_against_unknown_drone_returns_drone_not_found
    """
    resp = api.create_incident(
        {
            "drone_id": NON_EXISTENT_UUID,
            "severity": "MINOR",
            "category": "GROUND_DAMAGE",
            "narrative": "phantom",
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_DRONE_NOT_FOUND.value)


def test_recording_an_outcome_before_the_review_is_rejected(api):
    """PRD §3.8: "The review then forks. A `MaintenanceTech` records the `outcome`, and the two
    branches have deliberately disjoint effects. An incident that is not `UNDER_REVIEW` when an
    outcome is recorded is rejected with `ERR_INCIDENT_NOT_UNDER_REVIEW` (HTTP 409)."

    Design: Corner/state_machines/incident_outcome_before_review_rejected
    """
    w = setup_open_incident(severity="MINOR", category="HARD_LANDING")

    resp = api.record_incident_outcome(
        w["incident"]["id"], "MAINTENANCE_REQUIRED", TECH
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_UNDER_REVIEW.value)

    assert read_incident(w["incident"]["id"])["status"] == "OPEN"
    assert read_drone(w["drone"]["id"])["status"] == "IDLE"

    _, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"drone_id": w["drone"]["id"]})
    )
    assert meta["total_count"] == 0, "the rejected outcome creates no work order"


def test_no_action_branch_closes_the_incident_without_grounding_the_airframe(api):
    """PRD §3.8: "**Branch A — `NO_ACTION`.** The incident moves `UNDER_REVIEW → CLOSED` and
    its `version` advances. The drone is *not* grounded. No maintenance log is created. The one
    visible effect is a shift in the risk ledger: the incident's severity points now count
    toward `advisory_risk_score` as well, where before they did not, while `blocking_risk_score`
    is unchanged (they already counted there). Closing an incident with no action is therefore
    the operation that makes the advisory score catch up to the blocking score."

    Design: Corner/state_machines/incident_no_action_branch_closes_without_grounding
    """
    w = setup_reviewed_incident(severity="MINOR", category="HARD_LANDING")

    incident = validate_success(
        api.record_incident_outcome(w["incident"]["id"], "NO_ACTION", TECH)
    )
    assert incident["status"] == "CLOSED"

    drone = read_drone(w["drone"]["id"])
    assert drone["status"] == "IDLE", "the NO_ACTION branch never grounds the airframe"
    # 0 h since service and a fresh pack, so the 5 MINOR points are the whole score — and now
    # they sit in both buckets.
    assert_pct(drone["advisory_risk_score"], 5.0, "advisory_risk_score")
    assert_pct(drone["blocking_risk_score"], 5.0, "blocking_risk_score")

    _, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"drone_id": w["drone"]["id"]})
    )
    assert meta["total_count"] == 0, "the NO_ACTION branch creates no work order"


# ============================================================= the grounding cascade
def test_grounding_cascade_grounds_the_airframe_and_force_aborts_its_live_sortie(api):
    """PRD §3.8: "1. The incident moves `UNDER_REVIEW → MAINTENANCE_REQUIRED` and its `version`
    advances."
    PRD §3.8: "2. Because of hop 1, the drone named on the incident is forced to `GROUNDED`
    from whatever state it currently occupies — `IDLE`, `RESERVED` or `IN_FLIGHT` — and its
    `version` advances."
    PRD §3.8: "3. Because of hop 2, every flight of that drone whose `ops_state` is `PLANNED`,
    `LAUNCHED`, `DROPPING` or `RETURNING` is force-aborted, with `abort_reason` set to
    `DRONE_GROUNDED` and `actual_route_km` set to 0.0."
    PRD §3.7: "The flight's `actual_energy_pct` is computed with the actual variant exactly as
    on recovery."

    Design: Difficulty/transitive_cascade/grounding_cascade_incident_to_drone_to_flight_to_order_and_nest
    """
    w = setup_launched_flight()
    w = setup_grounding_cascade(world=w, severity="CRITICAL", category="AIRSPACE_DEVIATION")

    assert read_incident(w["incident"]["id"])["status"] == "MAINTENANCE_REQUIRED"
    assert read_drone(w["drone"]["id"])["status"] == "GROUNDED"

    flight = read_flight(w["flight"]["id"])
    assert flight["ops_state"] == "ABORTED"
    assert flight["abort_reason"] == "DRONE_GROUNDED"
    assert_km(flight["actual_route_km"], 0.0, "actual_route_km")
    # a 0.0 km route consumes nothing but the 3.0 hover allowance.
    assert_pct(flight["actual_energy_pct"], 3.0, "actual_energy_pct")


def test_grounding_cascade_revokes_the_clearance_and_gives_back_pad_and_funds(api):
    """PRD §3.8: "4. Because of hop 3, each force-aborted flight unwinds through the very same
    abort path a human-initiated abort would take: its `clearance_state` moves to `REVOKED`, its
    airspace authorization moves to `REVOKED`, its recovery nest's `reserved_pads` decreases by
    one, its order — when the order's `status` is `ASSIGNED` or `IN_TRANSIT` — reverts to
    `QUOTED` with the customer's `held_total` reduced by that order's `order_total`, and its
    pack — when the pack was `IN_USE` — moves to `COOLDOWN` with its `cycle_count` incremented.
    An order already `DELIVERED` is left alone, exactly as in the `RETURNING` abort case of
    §3.7."
    PRD §3.8: "Alongside those four hops, a maintenance work order is created for the drone with
    `work_type` `REPAIR`, `status` `SCHEDULED`, `incident_id` pointing back at this incident,
    `scheduled_start` at the current logical clock, and `scheduled_end` 120 minutes later."

    Design: Difficulty/transitive_cascade/grounding_cascade_incident_to_drone_to_flight_to_order_and_nest
    """
    w = setup_launched_flight()
    w = setup_grounding_cascade(world=w, severity="CRITICAL", category="AIRSPACE_DEVIATION")

    assert read_flight(w["flight"]["id"])["clearance_state"] == "REVOKED"
    assert read_authorization(w["auth"]["id"])["status"] == "REVOKED"
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0, "the cascade must not leak the pad"

    assert read_order(w["order"]["id"])["status"] == "QUOTED"
    customer = read_customer(w["customer"]["id"])
    assert_money(customer["held_total"], 0.00, "held_total")
    assert_money(customer["billed_total"], 0.00, "billed_total")

    battery = read_battery(w["battery"]["id"])
    assert battery["state"] == "COOLDOWN"
    assert battery["cycle_count"] == 1
    assert_pct(battery["charge_pct"], 97.0, "charge_pct")

    logs, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"incident_id": w["incident"]["id"]})
    )
    assert meta["total_count"] == 1
    assert logs[0]["work_type"] == "REPAIR"
    assert logs[0]["status"] == "SCHEDULED"


# ====================================================== maintenance window geometry
def test_maintenance_window_overlapping_by_one_minute_is_rejected(api):
    """PRD §3.9: "Windows on the same airframe may not overlap, and the overlap geometry here
    is **half-open** and **exclusive** — deliberately different from the closed, buffered,
    aggregate-capacity geometry of the nest pad hold in §3.4. Only `SCHEDULED` logs of the same
    drone participate; `COMPLETED` logs never conflict with anything. A conflict exists when the
    new window's `scheduled_start` falls strictly before an existing window's `scheduled_end`
    **and** that existing window's `scheduled_start` falls strictly before the new window's
    `scheduled_end`. Because both bounds are half-open, a new window beginning at exactly the
    instant an existing window ends does *not* conflict — adjacency is legal — while one
    beginning a single second earlier does. Capacity is one: a single overlapping window is
    fatal, and the request is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_exclusive_adjacency
    """
    w = setup_world(with_battery=False)
    drone = w["drone"]

    validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(
                drone["id"],
                drone["version"],
                work_type="INSPECTION",
                scheduled_start="2026-06-02T10:00:00Z",
                scheduled_end="2026-06-02T12:00:00Z",
                notes="100-hour inspection",
            ),
            TECH,
        ),
        201,
    )

    current_version = read_drone(drone["id"])["version"]
    resp = api.create_maintenance_log(
        create_maintenance_log_payload(
            drone["id"],
            current_version,
            work_type="REPAIR",
            scheduled_start="2026-06-02T11:59:00Z",
            scheduled_end="2026-06-02T13:00:00Z",
            notes="overlapping by one minute",
        ),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT.value)


def test_maintenance_window_starting_at_an_existing_windows_end_is_accepted(api):
    """PRD §3.9: "Because both bounds are half-open, a new window beginning at exactly the
    instant an existing window ends does *not* conflict — adjacency is legal — while one
    beginning a single second earlier does. Capacity is one: a single overlapping window is
    fatal, and the request is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.9: "A newly scheduled work order has `status` `SCHEDULED`, a null `completed_at`,
    and — when it is booked manually rather than generated by a cascade — a null `incident_id`."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_exclusive_adjacency
    """
    w = setup_world(with_battery=False)
    drone = w["drone"]

    validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(
                drone["id"],
                drone["version"],
                work_type="INSPECTION",
                scheduled_start="2026-06-02T10:00:00Z",
                scheduled_end="2026-06-02T12:00:00Z",
                notes="100-hour inspection",
            ),
            TECH,
        ),
        201,
    )

    current_version = read_drone(drone["id"])["version"]
    adjacent = validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(
                drone["id"],
                current_version,
                work_type="REPAIR",
                scheduled_start="2026-06-02T12:00:00Z",
                scheduled_end="2026-06-02T13:00:00Z",
                notes="adjacent, no overlap",
            ),
            TECH,
        ),
        201,
    )

    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["completed_at"] is None
    assert adjacent["incident_id"] is None
    assert_instant(adjacent["scheduled_start"], "2026-06-02T12:00:00Z", "scheduled_start")

    logs, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"drone_id": drone["id"]})
    )
    assert meta["total_count"] == 2
    assert all(log["status"] == "SCHEDULED" for log in logs)


def test_stale_expected_drone_version_on_maintenance_scheduling_is_rejected(api):
    """PRD §2.9: "Scheduling a maintenance window requires `expected_drone_version` in the
    request body. This field is likewise not optional, and must carry the client's last observed
    `version` of the target drone. A mismatch with the drone's current `version` is rejected with
    `ERR_STALE_DRONE_VERSION` (HTTP 412)."
    PRD §3.9: "Creating a maintenance log advances the drone's `version` by one."
    PRD §3.2: "On success the drone's `installed_battery_id` is set to the named pack, any pack
    that was previously installed is un-linked, both risk scores are recomputed, and the drone's
    `version` advances by one."

    Design: Corner/cross_cutting_layers/occ_stale_drone_version_on_maintenance_schedule
    """
    set_clock("2026-06-01T09:00:00Z")
    sa = create_service_area()
    nest = create_nest(sa["id"])
    battery = create_ready_battery(nest["id"])
    drone = create_drone(nest["id"])
    stale_version = drone["version"]  # version 1, read at registration
    install_battery(drone["id"], battery["id"])  # bumps the drone to version 2

    stale = api.create_maintenance_log(
        create_maintenance_log_payload(drone["id"], stale_version, notes="stale"), TECH
    )
    validate_error(stale, ApiErrorId.ERR_STALE_DRONE_VERSION.value)

    _, meta = validate_paginated(
        api.list_maintenance_logs(TECH, params={"drone_id": drone["id"]})
    )
    assert meta["total_count"] == 0, "a 412 mutates nothing"

    fresh_version = read_drone(drone["id"])["version"]
    log = validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(drone["id"], fresh_version, notes="fresh"), TECH
        ),
        201,
    )
    assert log["status"] == "SCHEDULED"
    assert read_drone(drone["id"])["version"] == 3, "creating the log advanced the drone again"


# ==================================================== returning an airframe to service
def test_completing_a_battery_swap_without_an_installed_pack_is_rejected(api):
    """PRD §3.9: "Completing a work order is what returns a grounded airframe to service. It
    requires the log to be `SCHEDULED` — a log already `COMPLETED` is rejected with
    `ERR_MAINTENANCE_NOT_SCHEDULED` (HTTP 409) — and it requires the drone to have a pack
    installed whose `state` is `READY`. A drone with `installed_battery_id` null, or with a pack
    that is not `READY`, cannot be signed back into service and the completion is rejected with
    `ERR_BATTERY_NOT_READY` (HTTP 409). That gate is why a `BATTERY_SWAP` work order raised by a
    retirement cannot be closed until a technician has actually bolted in a fresh pack and
    charged it."

    Design: Difficulty/cross_entity_state_dependency/maintenance_completion_gated_by_installed_battery_readiness
    """
    w = setup_retired_pack_and_grounded_drone()
    log = w["battery_swap_log"]
    assert log is not None and log["work_type"] == "BATTERY_SWAP"

    resp = api.complete_maintenance_log(log["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_BATTERY_NOT_READY.value)

    assert read_maintenance_log(log["id"])["status"] == "SCHEDULED"
    drone = read_drone(w["drone"]["id"])
    assert drone["status"] == "GROUNDED"
    assert drone["installed_battery_id"] is None


def test_completing_the_battery_swap_after_a_fresh_pack_returns_the_airframe_to_service(api):
    """PRD §3.9: "On success the log moves `SCHEDULED → COMPLETED`, its `completed_at` is
    stamped with the current logical clock, and its `version` advances. The drone's
    `hours_since_service` is reset to exactly 0 — which collapses the service term of its risk
    scores to zero — and the drone moves `GROUNDED → IDLE`, with its `version` advancing. Note
    that `flight_hours` is *not* reset; it is the airframe's lifetime total and only ever grows."
    PRD §3.2: "Bolting a pack into an airframe is likewise a `MaintenanceTech` or
    `PlatformAdmin` operation, naming the `battery_id` to install. It requires the drone to be
    `IDLE` or `GROUNDED`, and requires the named pack to be stored at the drone's home nest and
    to be neither `IN_USE` nor `RETIRED`; any of those conditions failing yields
    `ERR_BATTERY_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/maintenance_completion_gated_by_installed_battery_readiness
    """
    w = setup_retired_pack_and_grounded_drone()
    log = w["battery_swap_log"]

    fresh_pack = create_ready_battery(w["nest"]["id"], serial="B-10")
    install_battery(w["drone"]["id"], fresh_pack["id"])

    completed = validate_success(api.complete_maintenance_log(log["id"], TECH))
    assert completed["status"] == "COMPLETED"
    assert_instant(completed["completed_at"], "2026-06-01T09:00:00Z", "completed_at")

    drone = read_drone(w["drone"]["id"])
    assert drone["status"] == "IDLE"
    assert_hours(drone["hours_since_service"], 0, "hours_since_service")
    assert_hours(drone["flight_hours"], 0.19, "flight_hours (lifetime hours are never reset)")


def test_completing_a_work_order_twice_is_rejected(api):
    """PRD §3.9: "Completing a work order is what returns a grounded airframe to service. It
    requires the log to be `SCHEDULED` — a log already `COMPLETED` is rejected with
    `ERR_MAINTENANCE_NOT_SCHEDULED` (HTTP 409) — and it requires the drone to have a pack
    installed whose `state` is `READY`."
    PRD §3.9: "On success the log moves `SCHEDULED → COMPLETED`, its `completed_at` is stamped
    with the current logical clock, and its `version` advances. The drone's `hours_since_service`
    is reset to exactly 0 — which collapses the service term of its risk scores to zero — and the
    drone moves `GROUNDED → IDLE`, with its `version` advancing."

    Design: Corner/state_machines/maintenance_log_completed_twice_rejected
    """
    w = setup_world(hours_since_service=30)
    drone_version = read_drone(w["drone"]["id"])["version"]

    log = validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(w["drone"]["id"], drone_version), TECH
        ),
        201,
    )
    validate_success(api.complete_maintenance_log(log["id"], TECH))

    second = api.complete_maintenance_log(log["id"], TECH)
    validate_error(second, ApiErrorId.ERR_MAINTENANCE_NOT_SCHEDULED.value)

    reread = read_maintenance_log(log["id"])
    assert reread["status"] == "COMPLETED"
    assert_instant(reread["completed_at"], "2026-06-01T09:00:00Z", "completed_at")

    drone = read_drone(w["drone"]["id"])
    assert_hours(drone["hours_since_service"], 0, "hours_since_service")
    assert drone["status"] == "IDLE"


def test_the_logical_clock_starts_at_its_fixed_default(api):
    """PRD §2.4: "Nothing in this system consults wall-clock time. The server maintains a
    **logical clock** that begins at exactly `2026-05-01T00:00:00Z` when the process starts and
    moves only when a `PlatformAdmin` explicitly sets it, supplying the target instant as
    `to_iso8601`."
    PRD §3.9: "On success the log moves `SCHEDULED → COMPLETED`, its `completed_at` is stamped
    with the current logical clock, and its `version` advances. The drone's `hours_since_service`
    is reset to exactly 0 — which collapses the service term of its risk scores to zero — and the
    drone moves `GROUNDED → IDLE`, with its `version` advancing."

    Design: Corner/cross_cutting_layers/logical_clock_default_before_any_set_call
    """
    w = setup_world(clock=None, hours_since_service=12)  # the clock endpoint is never called
    drone_version = read_drone(w["drone"]["id"])["version"]

    log = validate_success(
        api.create_maintenance_log(
            create_maintenance_log_payload(
                w["drone"]["id"],
                drone_version,
                scheduled_start="2026-05-02T10:00:00Z",
                scheduled_end="2026-05-02T12:00:00Z",
            ),
            TECH,
        ),
        201,
    )

    completed = validate_success(api.complete_maintenance_log(log["id"], TECH))
    assert completed["status"] == "COMPLETED"
    assert_instant(completed["completed_at"], "2026-05-01T00:00:00Z", "completed_at")
    assert_hours(read_drone(w["drone"]["id"])["hours_since_service"], 0, "hours_since_service")
