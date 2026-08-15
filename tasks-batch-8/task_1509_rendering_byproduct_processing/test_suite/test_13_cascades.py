"""Transitive cascades: odor-confirm -> permit -> plant -> routes/stops, and
stop-rejection -> strikes -> supplier -> agreement -> stops (PRD §2.7, §3.2, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    confirm_odor_event,
    create_active_agreement,
    create_active_permit,
    create_odor_event,
    create_plant,
    create_route,
    create_supplier,
    create_vehicle,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


def _setup_odor_cascade(api):
    """Plant with an ACTIVE permit (threshold 2); route R1 DISPATCHED with stop1 ARRIVED
    and stop2 SCHEDULED; route R2 (next day, same vehicle) PLANNED with stop3 SCHEDULED;
    two HIGH odor events REPORTED; the first already confirmed (score 850, count 1)."""
    plant = create_plant()
    permit = create_active_permit(plant["id"], odor_event_threshold=2)
    supplier = create_supplier(plant["id"])
    agreement = create_active_agreement(plant["id"], supplier["id"])
    vehicle = create_vehicle(plant["id"])

    r1 = create_route(plant["id"], vehicle["id"], route_code="R1")
    s1 = add_stop(r1["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=1)
    s2 = add_stop(r1["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=2,
                  scheduled_window_start="2026-08-10T10:00:00Z",
                  scheduled_window_end="2026-08-10T11:00:00Z",
                  estimated_weight_lbs=4000, estimated_distance_miles=5)
    validate_success(api.dispatch_route(r1["id"], RD), 200)
    validate_success(api.arrive_stop(s1["id"], RD), 200)

    r2 = create_route(plant["id"], vehicle["id"], route_code="R2",
                      service_date="2026-08-11",
                      scheduled_departure="2026-08-11T06:00:00Z",
                      scheduled_return="2026-08-11T18:00:00Z")
    s3 = add_stop(r2["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=1,
                  scheduled_window_start="2026-08-11T08:00:00Z",
                  scheduled_window_end="2026-08-11T09:00:00Z",
                  estimated_weight_lbs=3000, estimated_distance_miles=8)

    ev1 = create_odor_event(plant["id"], reported_at="2026-08-10T09:30:00Z",
                            location_description="East fence", severity="HIGH")
    ev2 = create_odor_event(plant["id"], reported_at="2026-08-10T11:00:00Z",
                            location_description="North gate", severity="HIGH")
    confirm_odor_event(ev1["id"])

    return {"plant": plant, "permit": permit, "supplier": supplier,
            "agreement": agreement, "vehicle": vehicle, "r1": r1, "r2": r2,
            "s1": s1, "s2": s2, "s3": s3, "ev1": ev1, "ev2": ev2}


class TestOdorConfirmPermitPlantRouteCascade:
    def test_second_confirm_suspends_permit_and_plant(self, api):
        """PRD §3.2: "The current period settlement's `confirmed_odor_events` increments by
        one, and when a permit was linked, its `confirmed_violation_count` increments by one
        — reaching the permit's `odor_event_threshold` suspends the permit, which suspends
        the plant, which cancels non-terminal routes and stops and voids collected-stop fees
        per §2.7."
        PRD §3.2: "If the penalized score falls below 600 while the plant is `OPERATING`,
        posture drops to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/odor_confirm_permit_plant_route_cascade
        """
        ctx = _setup_odor_cascade(api)

        # Second confirm: score 1000 - 150 - 150 = 700 (NOT below 600), but the permit's
        # violation count reaches its threshold 2, so the suspension is permit-driven.
        confirmed = validate_success(api.confirm_odor_event(ctx["ev2"]["id"], CO2), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by"] == "co-2"
        assert confirmed["permit_id"] == ctx["permit"]["id"]

        permit = validate_success(api.get_permit(ctx["permit"]["id"], ANY), 200)
        assert permit["confirmed_violation_count"] == 2
        assert permit["status"] == "SUSPENDED"

        plant = validate_success(api.get_plant(ctx["plant"]["id"], ANY), 200)
        assert plant["odor_score"] == 700  # >= 600, so this is not a score-driven drop
        assert plant["posture"] == "SUSPENDED"

    def test_plant_suspension_cancels_routes_and_stops(self, api):
        """PRD §2.7: "When a plant falls to `SUSPENDED` — whether by permit suspension,
        revocation, or expiry — every collection route still in `PLANNED`, `DISPATCHED`, or
        `IN_PROGRESS` is cancelled; every stop on those routes in `SCHEDULED` or `ARRIVED`
        is cancelled; every stop in `COLLECTED` is instead moved to `VOIDED`, its final fee
        and transport cost reversed out of the current period settlement, and the inbound
        batch it created is moved to `REJECTED`."

        Design: Difficulty/transitive_cascade/odor_confirm_permit_plant_route_cascade
        """
        ctx = _setup_odor_cascade(api)
        validate_success(api.confirm_odor_event(ctx["ev2"]["id"], CO2), 200)

        r1 = validate_success(api.get_collection_route(ctx["r1"]["id"], ANY), 200)
        r2 = validate_success(api.get_collection_route(ctx["r2"]["id"], ANY), 200)
        assert r1["status"] == "CANCELLED"  # was IN_PROGRESS (one stop had ARRIVED)
        assert r2["status"] == "CANCELLED"  # was PLANNED

        s1 = validate_success(api.get_route_stop(ctx["s1"]["id"], ANY), 200)
        s2 = validate_success(api.get_route_stop(ctx["s2"]["id"], ANY), 200)
        s3 = validate_success(api.get_route_stop(ctx["s3"]["id"], ANY), 200)
        assert s1["status"] == "CANCELLED"  # was ARRIVED
        assert s2["status"] == "CANCELLED"  # was SCHEDULED
        assert s3["status"] == "CANCELLED"  # was SCHEDULED


def _setup_strike_cascade(api):
    """Supplier with an ACTIVE ZERO_TOLERANCE agreement; route R1 DISPATCHED with stops
    s1/s2/s3 all ARRIVED; route R2 (next day, same vehicle) PLANNED with stop s4
    SCHEDULED; s1 and s2 already rejected for PROHIBITED_MATERIAL (strikes 2)."""
    plant = create_plant()
    supplier = create_supplier(plant["id"])
    agreement = create_active_agreement(plant["id"], supplier["id"],
                                        prohibited_material_policy="ZERO_TOLERANCE")
    vehicle = create_vehicle(plant["id"])

    r1 = create_route(plant["id"], vehicle["id"], route_code="R1")
    s1 = add_stop(r1["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=1)
    s2 = add_stop(r1["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=2,
                  scheduled_window_start="2026-08-10T10:00:00Z",
                  scheduled_window_end="2026-08-10T11:00:00Z",
                  estimated_weight_lbs=4000, estimated_distance_miles=5)
    s3 = add_stop(r1["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=3,
                  scheduled_window_start="2026-08-10T12:00:00Z",
                  scheduled_window_end="2026-08-10T13:00:00Z",
                  estimated_weight_lbs=3000, estimated_distance_miles=6)

    r2 = create_route(plant["id"], vehicle["id"], route_code="R2",
                      service_date="2026-08-11",
                      scheduled_departure="2026-08-11T06:00:00Z",
                      scheduled_return="2026-08-11T18:00:00Z")
    s4 = add_stop(r2["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=1,
                  scheduled_window_start="2026-08-11T08:00:00Z",
                  scheduled_window_end="2026-08-11T09:00:00Z",
                  estimated_weight_lbs=2000, estimated_distance_miles=4)

    validate_success(api.dispatch_route(r1["id"], RD), 200)
    for stop in (s1, s2, s3):
        validate_success(api.arrive_stop(stop["id"], RD), 200)
    for stop in (s1, s2):
        validate_success(
            api.reject_stop_at_site(stop["id"], {"rejection_reason": "PROHIBITED_MATERIAL"},
                                    RD),
            200,
        )

    return {"plant": plant, "supplier": supplier, "agreement": agreement,
            "vehicle": vehicle, "r1": r1, "r2": r2, "s1": s1, "s2": s2, "s3": s3,
            "s4": s4}


class TestStopRejectionStrikeCascade:
    def test_third_strike_suspends_supplier_and_agreement(self, api):
        """PRD §3.3: "Contamination is a three-strikes discipline. Each site rejection for
        prohibited material (§3.4) adds one strike; the instant `contamination_strikes`
        reaches 3 the supplier is automatically `SUSPENDED`, every one of its `ACTIVE`
        agreements is suspended, and every one of its stops still in `SCHEDULED` or
        `ARRIVED` is cancelled."
        PRD §3.4: "When the reason is `PROHIBITED_MATERIAL`, the supplier's
        `contamination_strikes` increments by one, and the third strike triggers the
        supplier suspension cascade of §3.3."

        Design: Difficulty/transitive_cascade/stop_rejection_strike_agreement_cascade
        """
        ctx = _setup_strike_cascade(api)
        supplier_mid = validate_success(api.get_supplier(ctx["supplier"]["id"], ANY), 200)
        assert supplier_mid["contamination_strikes"] == 2
        assert supplier_mid["status"] == "ACTIVE"

        # The third prohibited-material rejection trips the limit.
        rejected = validate_success(
            api.reject_stop_at_site(ctx["s3"]["id"],
                                    {"rejection_reason": "PROHIBITED_MATERIAL"}, RD),
            200,
        )
        assert rejected["status"] == "REJECTED_AT_SITE"
        assert rejected["rejection_reason"] == "PROHIBITED_MATERIAL"

        supplier = validate_success(api.get_supplier(ctx["supplier"]["id"], ANY), 200)
        assert supplier["contamination_strikes"] == 3
        assert supplier["status"] == "SUSPENDED"

        agreement = validate_success(
            api.get_supplier_agreement(ctx["agreement"]["id"], ANY), 200
        )
        assert agreement["status"] == "SUSPENDED"

    def test_supplier_suspension_cancels_open_stops(self, api):
        """PRD §3.3: "the instant `contamination_strikes` reaches 3 the supplier is
        automatically `SUSPENDED`, every one of its `ACTIVE` agreements is suspended, and
        every one of its stops still in `SCHEDULED` or `ARRIVED` is cancelled."
        PRD §3.4: "A stop rejected at the supplier's site — from `ARRIVED`
        (`ERR_STOP_INVALID_STATE` otherwise) — becomes `REJECTED_AT_SITE` with a
        `rejection_reason` of `PROHIBITED_MATERIAL`, `TEMPERATURE_EXCURSION`, or `OTHER`; no
        fee accrues and `final_fee_cents` stays null."

        Design: Difficulty/transitive_cascade/stop_rejection_strike_agreement_cascade
        """
        ctx = _setup_strike_cascade(api)
        validate_success(
            api.reject_stop_at_site(ctx["s3"]["id"],
                                    {"rejection_reason": "PROHIBITED_MATERIAL"}, RD),
            200,
        )

        # The supplier's remaining open stop (SCHEDULED on the not-yet-dispatched R2)
        # is cancelled by the cascade.
        s4 = validate_success(api.get_route_stop(ctx["s4"]["id"], ANY), 200)
        assert s4["status"] == "CANCELLED"

        # The three rejected stops are terminal REJECTED_AT_SITE and accrued no fee.
        for key in ("s1", "s2", "s3"):
            stop = validate_success(api.get_route_stop(ctx[key]["id"], ANY), 200)
            assert stop["status"] == "REJECTED_AT_SITE"
            assert stop["rejection_reason"] == "PROHIBITED_MATERIAL"
            assert stop["final_fee_cents"] is None
