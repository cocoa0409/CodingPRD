"""The fleet: airframes, packs, charging and the two airworthiness risk numbers."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    assert_battery,
    assert_drone,
    assert_pct,
    create_battery,
    create_drone_payload,
    create_incident,
    create_nest,
    create_service_area,
    read_drone,
    review_incident,
    setup_approved_flight,
    setup_launched_flight,
    setup_world,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


def test_duplicate_tail_number_is_rejected(api):
    """PRD §3.2: "A `PlatformAdmin` registers an airframe against its `home_nest_id`, giving it
    a `tail_number` (its registration mark, which must be globally unique across all drones — a
    collision is rejected with `ERR_DUPLICATE_TAIL_NUMBER`, HTTP 409), an `airframe_class` of
    either `LIGHT` or `HEAVY`, a `max_payload_g` strictly greater than zero, and a
    `cruise_speed_kmh` strictly greater than zero that will be used to estimate every recovery
    time it ever flies."

    Design: Corner/entities/duplicate_tail_number_rejected
    """
    sa = create_service_area()
    nest = create_nest(sa["id"])
    validate_success(
        api.create_drone(create_drone_payload(nest["id"], tail_number="N101"), ADMIN), 201
    )

    clash = api.create_drone(
        create_drone_payload(
            nest["id"],
            tail_number="N101",
            airframe_class="LIGHT",
            max_payload_g=1000,
            cruise_speed_kmh=80,
        ),
        ADMIN,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_TAIL_NUMBER.value)

    listed, meta = validate_paginated(
        api.list_drones(ADMIN, params={"home_nest_id": nest["id"]})
    )
    assert meta["total_count"] == 1, "the colliding registration must not persist a second drone"
    assert len(listed) == 1


def test_battery_health_pct_is_rounded_to_one_decimal_place(api):
    """PRD §3.2: "Every pack publishes a computed `health_pct`: one hundred, minus the pack's
    `cycle_count` divided by 300 and expressed as a percentage — that is, one hundred minus one
    hundred times the ratio of `cycle_count` to 300 — rounded half up to one decimal place, and
    floored at zero so that it never goes negative."
    PRD §3.2: "A new pack's `state` is `CHARGING`."

    Design: Corner/calculations/battery_health_pct_precision
    """
    sa = create_service_area()
    nest = create_nest(sa["id"])

    battery = create_battery(nest["id"], serial="B-7", charge_pct=100, cycle_count=100)

    assert_battery(battery)
    # 100 - (100 / 300) * 100 = 66.666... -> 66.7 at one decimal place (not 66.6, not 66.67).
    assert_pct(battery["health_pct"], 66.7, "health_pct")
    assert battery["state"] == "CHARGING"

    _, meta = validate_paginated(api.list_batteries(TECH, params={"nest_id": nest["id"]}))
    assert meta["total_count"] == 1


def test_charging_an_in_use_pack_is_rejected(api):
    """PRD §3.2: "It is accepted only when the pack is currently `CHARGING`, `COOLDOWN` or
    `READY`; a pack that is `IN_USE` or `RETIRED` cannot be charged and the attempt is rejected
    with `ERR_BATTERY_NOT_READY` (HTTP 409)."
    PRD §3.6: "The pack goes `READY → IN_USE` and its `version` advances — no charge is debited
    yet, because the system does not know what the airframe actually flew."

    Design: Corner/errors/charging_an_in_use_pack_rejected
    """
    w = setup_launched_flight()

    resp = api.charge_battery(w["battery"]["id"], 50, TECH)
    validate_error(resp, ApiErrorId.ERR_BATTERY_NOT_READY.value)

    battery = validate_success(api.get_battery(w["battery"]["id"], TECH))
    assert battery["state"] == "IN_USE"
    assert_pct(battery["charge_pct"], 100, "charge_pct")


def test_risk_scores_are_recomputed_on_every_drone_read(api):
    """PRD §3.2: "**Airworthiness risk.** Every drone publishes two risk numbers, recomputed
    freshly on every read of the drone, on every dispatch-eligibility evaluation, and on every
    BVLOS release."
    PRD §3.8: "Filing has an immediate consequence: an `OPEN` incident counts toward the
    drone's `blocking_risk_score` from the moment it exists, so a `CRITICAL` incident can push
    an airframe over the 70.0 threshold and remove it from dispatch and from release the
    instant it is logged. It does *not* count toward `advisory_risk_score`, which continues to
    reflect only `CLOSED` paperwork."
    PRD §3.8: "Review changes neither risk score: `UNDER_REVIEW` still counts toward the
    blocking score (as `OPEN` did) and still does not count toward the advisory score."

    Design: Corner/cross_cutting_layers/derived_scores_recomputed_after_source_incident_changes
    """
    w = setup_world(hours_since_service=0, battery_cycle_count=0)

    before = read_drone(w["drone"]["id"])
    assert_drone(before)
    assert_pct(before["advisory_risk_score"], 0.0, "advisory_risk_score")
    assert_pct(before["blocking_risk_score"], 0.0, "blocking_risk_score")

    incident = create_incident(w["drone"]["id"], severity="MINOR", category="HARD_LANDING")

    filed = read_drone(w["drone"]["id"])
    assert_pct(filed["advisory_risk_score"], 0.0, "advisory_risk_score")
    assert_pct(filed["blocking_risk_score"], 5.0, "blocking_risk_score")

    reviewed = review_incident(incident["id"])
    assert reviewed["status"] == "UNDER_REVIEW"

    after_review = read_drone(w["drone"]["id"])
    assert_pct(after_review["advisory_risk_score"], 0.0, "advisory_risk_score")
    assert_pct(after_review["blocking_risk_score"], 5.0, "blocking_risk_score")


def test_advisory_and_blocking_risk_diverge_on_an_open_incident(api):
    """PRD §3.2: "The *service term* is 40.0 multiplied by the ratio of the drone's
    `hours_since_service` to a 50-hour service interval, with that ratio capped at 1.0 — so an
    airframe at or beyond 50 hours since its last service contributes the full 40.0 points."
    PRD §3.2: "The *cycle term* is 30.0 multiplied by the ratio of the installed pack's
    `cycle_count` to the 300-cycle retirement life, again with the ratio capped at 1.0."
    PRD §3.2: "`advisory_risk_score` is the sum of the service term, the cycle term, and the
    severity points of incidents whose `status` is `CLOSED` — rounded half up to one decimal
    place. `blocking_risk_score` is the sum of the service term, the cycle term, and the
    severity points of incidents in **any** status — `OPEN`, `UNDER_REVIEW`,
    `MAINTENANCE_REQUIRED` or `CLOSED` — likewise rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/risk_advisory_vs_blocking_on_drone
    """
    w = setup_approved_flight(
        tail_number="N102",
        hours_since_service=50,
        battery_serial="B-2",
        battery_cycle_count=150,
    )
    create_incident(
        w["drone"]["id"],
        severity="MAJOR",
        category="LOST_LINK",
        narrative="C2 link dropped on the previous sortie",
        flight_id=w["flight"]["id"],
    )

    drone = read_drone(w["drone"]["id"])

    # service term 40.0 (50/50 h) + cycle term 15.0 (150/300 cycles) = 55.0 shared base.
    assert_pct(drone["advisory_risk_score"], 55.0, "advisory_risk_score")
    # the OPEN MAJOR incident adds its 15 points to the blocking bucket only.
    assert_pct(drone["blocking_risk_score"], 70.0, "blocking_risk_score")
    assert drone["advisory_risk_score"] != drone["blocking_risk_score"], (
        "an OPEN incident makes the two published numbers diverge"
    )
