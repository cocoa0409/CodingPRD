"""Valve isolation: execution cascade, zone-deduped outage extent, the 500-customer
auto-advisory boundary, plan supersession, and OCC on plan creation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_isolation_event,
    confirm_break,
    create_break,
    create_isolation_plan,
    create_segment,
    create_valve,
    get_break,
    list_break_advisories,
    list_break_isolations,
    list_segment_valves,
    setup_confirmed_break,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import (
    create_isolation_event_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _cedar_segment_two_zones():
    """Segment MAIN-8-CEDAR with valves Z1/300 + Z2/250 (distinct zones, 550 total)."""
    seg = create_segment(segment_ref="MAIN-8-CEDAR", material="DUCTILE_IRON",
                         diameter_inches=8, install_year=1970)
    v1 = create_valve(seg["id"], "V-CED-1", coverage_zone="Z1", customers_served=300)
    v2 = create_valve(seg["id"], "V-CED-2", coverage_zone="Z2", customers_served=250)
    return seg, v1, v2


def _confirmed_cedar_break(seg):
    br = create_break(location_description="5 Cedar Rd", source="SENSOR_SCADA")
    return confirm_break(br["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                         severity="HIGH")


# ---------------------------------------------------------------------------
# Difficulty: isolation_execute_cascade_depth3 (2 tests)
# ---------------------------------------------------------------------------

def test_isolation_execute_closes_valves_and_isolates_break(api):
    """PRD §3.3: "On execution all listed valves flip to `CLOSED`, `executed_at`
    is stamped, and the outage extent is computed by zone deduplication: the
    closed valves are grouped by `coverage_zone`, and `outage_extent_customers`
    is the sum over distinct zones of the largest `customers_served` among the
    closed valves in that zone — the largest valve in a zone is taken to cover
    the others' customers. The computed extent is copied onto the break's
    `customers_out_of_service`, and the break itself moves from `CONFIRMED` (or
    `REPAIRED`, in the rework loop) to `ISOLATED`."

    Design: Difficulty/transitive_cascade/isolation_execute_cascade_depth3
    """
    seg, v1, v2 = _cedar_segment_two_zones()
    br = _confirmed_cedar_break(seg)
    plan = create_isolation_plan(br["id"], [v1["id"], v2["id"]], br["version"])

    resp = _api.execute_isolation_event(plan["id"], DISPATCHER)
    iso = validate_success(resp, 200)
    assert_isolation_event(iso)
    assert iso["isolation_status"] == "EXECUTED"
    assert iso["outage_extent_customers"] == 550, (
        f"extent must be 300 + 250 across distinct zones, got {iso['outage_extent_customers']}"
    )
    assert iso["executed_at"] is not None

    valves = list_segment_valves(seg["id"])
    by_id = {v["id"]: v for v in valves}
    assert by_id[v1["id"]]["valve_status"] == "CLOSED"
    assert by_id[v2["id"]]["valve_status"] == "CLOSED"

    br_after = get_break(br["id"])
    assert br_after["break_status"] == "ISOLATED"
    assert br_after["customers_out_of_service"] == 550


def test_isolation_execute_auto_issues_advisory_at_550(api):
    """PRD §3.3: "If `outage_extent_customers` is at least 500 — the boundary is
    inclusive, so exactly 500 triggers and 499 does not — and no advisory in
    `ISSUED` status already exists for the break, the system automatically
    creates a boil-water advisory with `issue_reason` `AUTO_OUTAGE_THRESHOLD`,
    `advisory_status` `ISSUED`, `issued_by_user_id` set to the literal string
    "system", and `issued_at` stamped with the clock now."

    Design: Difficulty/transitive_cascade/isolation_execute_cascade_depth3
    """
    seg, v1, v2 = _cedar_segment_two_zones()
    br = _confirmed_cedar_break(seg)
    plan = create_isolation_plan(br["id"], [v1["id"], v2["id"]], br["version"])
    validate_success(_api.execute_isolation_event(plan["id"], DISPATCHER), 200)

    advisories = list_break_advisories(br["id"])
    assert len(advisories) == 1, f"expected exactly 1 auto advisory, got {len(advisories)}"
    adv = advisories[0]
    assert adv["advisory_status"] == "ISSUED"
    assert adv["issue_reason"] == "AUTO_OUTAGE_THRESHOLD"
    assert adv["issued_by_user_id"] == "system"
    assert adv["break_report_id"] == br["id"]


# ---------------------------------------------------------------------------
# Difficulty: advisory_threshold_499_vs_500 (2 tests)
# ---------------------------------------------------------------------------

def _cedar_segment_four_zones():
    seg = create_segment(segment_ref="MAIN-8-CEDAR", material="DUCTILE_IRON",
                         diameter_inches=8, install_year=1970)
    v1 = create_valve(seg["id"], "V-CED-1", coverage_zone="Z1", customers_served=300)
    v2 = create_valve(seg["id"], "V-CED-2", coverage_zone="Z2", customers_served=199)
    v3 = create_valve(seg["id"], "V-CED-3", coverage_zone="Z3", customers_served=300)
    v4 = create_valve(seg["id"], "V-CED-4", coverage_zone="Z4", customers_served=200)
    return seg, v1, v2, v3, v4


def test_advisory_threshold_499_does_not_trigger(api):
    """PRD §3.3: "If `outage_extent_customers` is at least 500 — the boundary is
    inclusive, so exactly 500 triggers and 499 does not — and no advisory in
    `ISSUED` status already exists for the break, the system automatically
    creates a boil-water advisory with `issue_reason` `AUTO_OUTAGE_THRESHOLD`,
    `advisory_status` `ISSUED`, `issued_by_user_id` set to the literal string
    "system", and `issued_at` stamped with the clock now."

    Design: Difficulty/boundary_precision_check/advisory_threshold_499_vs_500
    """
    seg, v1, v2, _v3, _v4 = _cedar_segment_four_zones()
    br = create_break(location_description="5 Cedar Rd", source="CUSTOMER_CALL")
    br = confirm_break(br["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                       severity="MEDIUM")
    plan = create_isolation_plan(br["id"], [v1["id"], v2["id"]], br["version"])
    iso = validate_success(_api.execute_isolation_event(plan["id"], DISPATCHER), 200)
    assert iso["outage_extent_customers"] == 499, (
        f"extent must be 300 + 199 = 499, got {iso['outage_extent_customers']}"
    )
    advisories = list_break_advisories(br["id"])
    assert advisories == [], (
        f"499 < 500 must not auto-issue an advisory, got {len(advisories)}"
    )


def test_advisory_threshold_500_triggers(api):
    """PRD §3.3: "If `outage_extent_customers` is at least 500 — the boundary is
    inclusive, so exactly 500 triggers and 499 does not — and no advisory in
    `ISSUED` status already exists for the break, the system automatically
    creates a boil-water advisory with `issue_reason` `AUTO_OUTAGE_THRESHOLD`,
    `advisory_status` `ISSUED`, `issued_by_user_id` set to the literal string
    "system", and `issued_at` stamped with the clock now."

    Design: Difficulty/boundary_precision_check/advisory_threshold_499_vs_500
    """
    seg, _v1, _v2, v3, v4 = _cedar_segment_four_zones()
    br = create_break(location_description="900 Cedar Rd", source="SENSOR_SCADA")
    br = confirm_break(br["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                       severity="HIGH")
    plan = create_isolation_plan(br["id"], [v3["id"], v4["id"]], br["version"])
    iso = validate_success(_api.execute_isolation_event(plan["id"], DISPATCHER), 200)
    assert iso["outage_extent_customers"] == 500, (
        f"extent must be 300 + 200 = 500, got {iso['outage_extent_customers']}"
    )
    advisories = list_break_advisories(br["id"])
    assert len(advisories) == 1, (
        f"exactly 500 must auto-issue one advisory, got {len(advisories)}"
    )
    assert advisories[0]["advisory_status"] == "ISSUED"
    assert advisories[0]["issue_reason"] == "AUTO_OUTAGE_THRESHOLD"


# ---------------------------------------------------------------------------
# Corner: outage_extent_zone_dedup_max
# ---------------------------------------------------------------------------

def test_outage_extent_zone_dedup_max(api):
    """PRD §3.3: "the outage extent is computed by zone deduplication: the
    closed valves are grouped by `coverage_zone`, and `outage_extent_customers`
    is the sum over distinct zones of the largest `customers_served` among the
    closed valves in that zone — the largest valve in a zone is taken to cover
    the others' customers."

    Design: Corner/calculations/outage_extent_zone_dedup_max
    """
    seg = create_segment(segment_ref="MAIN-8-CEDAR", material="DUCTILE_IRON",
                         diameter_inches=8, install_year=1970)
    v1 = create_valve(seg["id"], "V-CED-1", coverage_zone="Z1", customers_served=300)
    v2 = create_valve(seg["id"], "V-CED-2", coverage_zone="Z1", customers_served=200)
    br = create_break(location_description="5 Cedar Rd", source="CUSTOMER_CALL")
    br = confirm_break(br["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                       severity="MEDIUM")
    plan = create_isolation_plan(br["id"], [v1["id"], v2["id"]], br["version"])
    iso = validate_success(_api.execute_isolation_event(plan["id"], DISPATCHER), 200)
    assert iso["outage_extent_customers"] == 300, (
        f"same-zone valves dedupe to the zone max 300, not the naive sum 500; "
        f"got {iso['outage_extent_customers']}"
    )
    advisories = list_break_advisories(br["id"])
    assert advisories == [], (
        f"extent 300 < 500 must not auto-issue an advisory, got {len(advisories)}"
    )


# ---------------------------------------------------------------------------
# Corner: new_isolation_plan_supersedes_planned
# ---------------------------------------------------------------------------

def test_new_isolation_plan_supersedes_planned(api):
    """PRD §3.3: "Creating a new plan for a break supersedes any prior plan
    still in `PLANNED` status for that same break (the older plan's
    `isolation_status` becomes `SUPERSEDED`), and the creation itself
    increments the break's `version`, which is exactly why the OCC check
    exists."

    Design: Corner/state_machines/new_isolation_plan_supersedes_planned
    """
    ctx = setup_confirmed_break(
        valve_specs=[
            {"valve_code": "V-1", "coverage_zone": "Z1", "customers_served": 100},
            {"valve_code": "V-2", "coverage_zone": "Z2", "customers_served": 80},
        ]
    )
    br, v1, v2 = ctx["break"], ctx["valves"][0], ctx["valves"][1]
    plan_a = create_isolation_plan(br["id"], [v1["id"]], br["version"])

    current = get_break(br["id"])
    plan_b = create_isolation_plan(
        br["id"], [v1["id"], v2["id"]], current["version"]
    )

    plans = {p["id"]: p for p in list_break_isolations(br["id"])}
    assert plans[plan_a["id"]]["isolation_status"] == "SUPERSEDED", (
        f"prior PLANNED plan must be SUPERSEDED, got {plans[plan_a['id']]['isolation_status']!r}"
    )
    assert plans[plan_b["id"]]["isolation_status"] == "PLANNED"
    for v in list_segment_valves(ctx["segment"]["id"]):
        assert v["valve_status"] == "OPEN", (
            "supersession does not execute; valves must remain OPEN"
        )


# ---------------------------------------------------------------------------
# Corner: occ_stale_isolation_plan_rejected
# ---------------------------------------------------------------------------

def test_occ_stale_isolation_plan_rejected(api):
    """PRD §2.6: "That request must carry `expected_break_report_version`, set
    to the `version` of the parent break report the client last observed. If
    the value does not equal the break report's current `version` at the moment
    of creation, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
    Because creating an isolation plan legitimately advances the break report's
    `version` (see §3.3), a client holding a pre-supersede version is told its
    view is stale rather than being allowed to silently supersede a plan it
    never saw."

    Design: Corner/complexity_layers/occ_stale_isolation_plan_rejected
    """
    ctx = setup_confirmed_break()
    br, v1 = ctx["break"], ctx["valves"][0]
    observed_version = br["version"]
    plan_a = create_isolation_plan(br["id"], [v1["id"]], observed_version)
    assert plan_a["isolation_status"] == "PLANNED"

    # Second create carrying the pre-supersede version must be rejected.
    resp = _api.create_isolation_event(
        create_isolation_event_payload(
            break_report_id=br["id"], valve_ids=[v1["id"]],
            expected_break_report_version=observed_version,
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    plans = {p["id"]: p for p in list_break_isolations(br["id"])}
    assert plans[plan_a["id"]]["isolation_status"] == "PLANNED", (
        "the rejected create must not supersede the existing PLANNED plan"
    )
