"""Rejection-ladder precedence, numeric and cardinality boundaries, and the
cross-entity gates that read a field living on another record.

Every test builds its own plant, ledger and paperwork from scratch: the harness
restarts the server with an empty database before each test, so nothing here may
lean on state a neighbouring test created.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    SURVEY_PRESETS,
    activate_sector,
    change_capacity_policy,
    change_circuit_state,
    change_subscriber_status,
    change_tower_status,
    create_backhaul_circuit,
    create_sector,
    create_serviceability_request,
    create_spectrum_license,
    create_tower,
    create_work_order,
    get_assignment_for_subscriber,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    get_tower,
    get_work_order,
    reserve_bandwidth,
    set_clock,
    setup_active_plant,
    setup_active_subscriber,
    setup_neighbor_sectors,
    setup_work_order_in_state,
    survey_work_order,
)

# The reference sector is `capacity_mbps` 25 with `max_oversubscription_ratio`
# 8.0, so floor(25 * 8.0) = 200 Mbps of ceiling and the watch, withhold and
# freeze lines fall at 100, 150 and 200 committed Mbps.
#
# The logical clock starts at 2026-08-01T00:00:00Z, so a qualification taken at
# startup expires 30 days later.
QUALIFICATION_EXPIRY = "2026-08-31T00:00:00Z"


def _setup_qualified_request(lapse: bool = False, withhold: bool = False) -> dict:
    """Active plant plus one enquiry qualified against its sector.

    `lapse` moves the logical clock to exactly the enquiry's
    `qualification_expires_at`; `withhold` then takes 150 Mbps of the sector's
    200 Mbps ceiling so its `oversubscription_ratio` lands on 6.000 and the
    posture is `HOLD`. The two switches are independent, which is what lets one
    scenario violate the state rung, the capacity rung, or both at once.
    """
    scenario = setup_active_plant()
    request = create_serviceability_request(
        scenario["tower"]["id"], scenario["plan"]["id"]
    )
    assert request["status"] == "QUALIFIED", (
        f"Setup failed: enquiry should qualify on the empty sector, got {request['status']}"
    )
    assert str(request["qualification_expires_at"]).startswith("2026-08-31T00:00:00"), (
        "Setup failed: a qualification taken at the clock's startup reading expires "
        f"30 days later, got {request['qualification_expires_at']}"
    )
    if lapse:
        set_clock(QUALIFICATION_EXPIRY)
    if withhold:
        reserve_bandwidth(scenario, 150)
    scenario["request"] = get_serviceability_request(request["id"])
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    return scenario


class TestExpiredQualificationOutranksCapacityHold:
    """Reserving against a lapsed enquiry on a sector that is also withholding."""

    def test_lapsed_qualification_beats_hold_posture_on_one_reservation(
        self, api, sales_agent
    ):
        """PRD §2.7: "Implementations must evaluate the rungs in this order and stop at the first violated rung:"
        PRD §2.7: "**State** — the addressed record is in a state that permits the operation, judged against the transition tables of §3. The error is the state error of the addressed entity: `ERR_INVALID_TOWER_STATE`, `ERR_INVALID_CIRCUIT_STATE`, `ERR_INVALID_SECTOR_STATE`, `ERR_COORDINATION_NOT_OPEN`, `ERR_REQUEST_NOT_QUALIFIED`, `ERR_QUALIFICATION_EXPIRED`, `ERR_HOLD_NOT_HELD`, `ERR_SUBSCRIBER_NOT_ACTIVE`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_ASSIGNMENT_NOT_RETURNABLE`, `ERR_OUTAGE_ALREADY_CLOSED`, `ERR_OUTAGE_NOT_CLOSED`, `ERR_CREDIT_NOT_PENDING`, or `ERR_CREDIT_NOT_APPLIED`, all HTTP 409."
        PRD §2.7: "**Capacity and fiscal gates** — `ERR_SECTOR_CAPACITY_HOLD`, `ERR_SECTOR_FROZEN`, and `ERR_INSUFFICIENT_SECTOR_CAPACITY`, all HTTP 409."
        PRD §2.7: "The practical reading of this ladder is that identity beats existence, existence beats state, state beats concurrency, concurrency beats physics, physics beats process, and process beats capacity."
        PRD §3.6: "The current logical clock must be strictly before the enquiry's `qualification_expires_at`, else the request is refused with `ERR_QUALIFICATION_EXPIRED` — this is the point-of-use enforcement described at the end of §3.5, and a clock landing exactly on the expiry instant is already too late."

        Design: Difficulty/priority_pair_validation_conflict/expired_qualification_outranks_sector_capacity_hold_posture
        """
        scenario = _setup_qualified_request(lapse=True, withhold=True)
        sector_before = scenario["sector"]
        assert sector_before["capacity_posture"] == "HOLD", (
            "Setup failed: 150 committed Mbps on a 25 Mbps sector with an 8.0 ceiling "
            f"is the withhold line, got {sector_before['capacity_posture']}"
        )

        response = api.create_capacity_hold(
            {
                "serviceability_request_id": scenario["request"]["id"],
                "expected_sector_version": sector_before["version"],
            },
            sales_agent,
        )
        validate_error(response, ApiErrorId.ERR_QUALIFICATION_EXPIRED, 409)

        reported = response.json()["data"]["error_id"]
        assert reported != ApiErrorId.ERR_SECTOR_CAPACITY_HOLD.value, (
            "the state rung is evaluated before the capacity rung, so the lapsed "
            f"qualification must be the reported error, got {reported}"
        )

        sector_after = get_sector(sector_before["id"])
        assert sector_after["version"] == sector_before["version"], (
            "a refused reservation must not mutate the sector"
        )
        assert sector_after["held_mbps"] == 150
        assert sector_after["committed_mbps"] == 150
        assert sector_after["oversubscription_ratio"] == pytest.approx(6.0, abs=0.0005)
        assert sector_after["capacity_posture"] == "HOLD"

        request_after = get_serviceability_request(scenario["request"]["id"])
        assert request_after["status"] == "QUALIFIED", (
            "there is no clock-driven transition out of QUALIFIED, so the lapsed "
            f"enquiry still reports QUALIFIED, got {request_after['status']}"
        )

        holds, _meta = validate_paginated(
            api.list_capacity_holds(
                sales_agent,
                params={"serviceability_request_id": scenario["request"]["id"]},
            )
        )
        assert holds == [], f"the refused call must create no reservation, got {holds}"

    def test_withholding_sector_alone_reports_the_capacity_gate(self, api, sales_agent):
        """PRD §3.6: "The sector's `capacity_posture` must not be `HOLD`, else `ERR_SECTOR_CAPACITY_HOLD`, and must not be `FROZEN`, else `ERR_SECTOR_FROZEN`."
        PRD §3.3: "A sector whose `capacity_posture` is `HOLD` accepts no new reservation and refuses one with `ERR_SECTOR_CAPACITY_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/expired_qualification_outranks_sector_capacity_hold_posture
        """
        scenario = _setup_qualified_request(lapse=False, withhold=True)
        sector_before = scenario["sector"]
        assert sector_before["capacity_posture"] == "HOLD", (
            "Setup failed: the sector should sit on its withhold line, got "
            f"{sector_before['capacity_posture']}"
        )

        response = api.create_capacity_hold(
            {
                "serviceability_request_id": scenario["request"]["id"],
                "expected_sector_version": sector_before["version"],
            },
            sales_agent,
        )
        validate_error(response, ApiErrorId.ERR_SECTOR_CAPACITY_HOLD, 409)

        sector_after = get_sector(sector_before["id"])
        assert sector_after["version"] == sector_before["version"]
        assert sector_after["held_mbps"] == 150

    def test_lapsed_qualification_alone_reports_the_state_gate(self, api, sales_agent):
        """PRD §3.6: "The current logical clock must be strictly before the enquiry's `qualification_expires_at`, else the request is refused with `ERR_QUALIFICATION_EXPIRED` — this is the point-of-use enforcement described at the end of §3.5, and a clock landing exactly on the expiry instant is already too late."

        Design: Difficulty/priority_pair_validation_conflict/expired_qualification_outranks_sector_capacity_hold_posture
        """
        scenario = _setup_qualified_request(lapse=True, withhold=False)
        sector_before = scenario["sector"]
        assert sector_before["capacity_posture"] == "OPEN", (
            "Setup failed: an empty sector on accepted transport is OPEN, got "
            f"{sector_before['capacity_posture']}"
        )

        response = api.create_capacity_hold(
            {
                "serviceability_request_id": scenario["request"]["id"],
                "expected_sector_version": sector_before["version"],
            },
            sales_agent,
        )
        validate_error(response, ApiErrorId.ERR_QUALIFICATION_EXPIRED, 409)

        sector_after = get_sector(sector_before["id"])
        assert sector_after["held_mbps"] == 0, (
            "a reservation refused on the state rung must not touch the ledger"
        )
        assert sector_after["version"] == sector_before["version"]


def _setup_same_tower_sector_pair() -> dict:
    """One ACTIVE tower carrying two ACTIVE sectors bound to the same licence.

    The licence covers 3550.0-3650.0 MHz with `max_eirp_dbm` 47.0. The requesting
    sector S1 points at 90.0 degrees on 3555.0/10.0 MHz; the neighbour S2 points
    at 135.0 degrees on 3600.0/10.0 MHz, so a proposal on S1's own channel
    inflated by a 2.0 MHz guard band stays clear of S2's occupied block and the
    guard-band test cannot fire.
    """
    scenario = setup_active_plant()
    neighbor = create_sector(
        scenario["tower"]["id"],
        scenario["license"]["id"],
        azimuth_deg=135.0,
        channel_center_mhz=3600.0,
        channel_width_mhz=10.0,
    )
    scenario["neighbor_sector"] = activate_sector(neighbor["id"])
    return scenario


class TestEirpCeilingOutranksSameTowerCoordination:
    """POST /interference-coordinations over the licence ceiling AND intra-site."""

    def test_over_ceiling_proposal_on_same_tower_reports_the_spectrum_error(
        self, api, network_engineer
    ):
        """PRD §2.7: "Implementations must evaluate the rungs in this order and stop at the first violated rung:"
        PRD §2.7: "**Spectrum compliance** — the proposed radiated power fits inside the licence (`ERR_EIRP_EXCEEDS_LICENSE`), the proposed channel lies wholly inside the licence (`ERR_CHANNEL_OUTSIDE_LICENSE`), the licence is effective at the current logical clock (`ERR_LICENSE_NOT_EFFECTIVE`), and the guard-band-inflated proposal does not collide with the neighbour's occupied channel (`ERR_CHANNEL_OVERLAP_GUARD_BAND`). All HTTP 422."
        PRD §2.7: "**Referential compatibility** — coordination is between sectors on different towers (`ERR_SAME_TOWER_COORDINATION`, 422), the plan permits the chosen equipment acquisition mode and matches the qualified plan (`ERR_PLAN_MISMATCH`, 422), the credited account is served from the tower that went down (`ERR_SUBSCRIBER_NOT_AFFECTED`, 422), and the account has no install work order already open (`ERR_WORK_ORDER_ALREADY_OPEN`, 409)."
        PRD §3.4: "The `proposed_eirp_dbm` must not exceed that licence's `max_eirp_dbm`, else `ERR_EIRP_EXCEEDS_LICENSE`."

        Design: Difficulty/priority_pair_validation_conflict/eirp_over_licence_ceiling_outranks_same_tower_coordination_referential_check
        """
        scenario = _setup_same_tower_sector_pair()
        requester_before = get_sector(scenario["sector"]["id"])
        assert requester_before["eirp_dbm"] == pytest.approx(42.0, abs=0.05), (
            "Setup failed: 25.0 dBm of conducted power plus 17.0 dBi of gain is "
            f"42.0 dBm of EIRP, got {requester_before['eirp_dbm']}"
        )

        response = api.create_coordination(
            {
                "requesting_sector_id": scenario["sector"]["id"],
                "neighbor_sector_id": scenario["neighbor_sector"]["id"],
                "proposed_channel_center_mhz": 3555.0,
                "proposed_channel_width_mhz": 10.0,
                "proposed_eirp_dbm": 50.0,
                "guard_band_mhz": 2.0,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_EIRP_EXCEEDS_LICENSE, 422)

        reported = response.json()["data"]["error_id"]
        assert reported != ApiErrorId.ERR_SAME_TOWER_COORDINATION.value, (
            "the spectrum-compliance rung is evaluated before the "
            f"referential-compatibility rung, got {reported}"
        )

        coordinations, _meta = validate_paginated(
            api.list_coordinations(
                network_engineer,
                params={"requesting_sector_id": scenario["sector"]["id"]},
            )
        )
        assert coordinations == [], (
            f"the refused call must open no coordination, got {coordinations}"
        )

        requester_after = get_sector(scenario["sector"]["id"])
        assert requester_after["eirp_dbm"] == pytest.approx(42.0, abs=0.05)
        assert requester_after["tx_power_dbm"] == pytest.approx(25.0, abs=0.05)
        assert requester_after["version"] == requester_before["version"], (
            "a refused coordination must leave the requesting sector untouched"
        )

    @pytest.mark.parametrize(
        "proposed_eirp_dbm, expected_error",
        [
            (46.9, ApiErrorId.ERR_SAME_TOWER_COORDINATION),
            (47.0, ApiErrorId.ERR_SAME_TOWER_COORDINATION),
            (47.1, ApiErrorId.ERR_EIRP_EXCEEDS_LICENSE),
        ],
    )
    def test_same_tower_pair_reports_eirp_only_once_the_ceiling_is_exceeded(
        self, api, network_engineer, proposed_eirp_dbm, expected_error
    ):
        """PRD §3.4: "The `proposed_eirp_dbm` must not exceed that licence's `max_eirp_dbm`, else `ERR_EIRP_EXCEEDS_LICENSE`."
        PRD §3.4: "If the two named sectors share a `tower_id` the request is refused with `ERR_SAME_TOWER_COORDINATION` — intra-site channel planning is an internal matter and needs no negotiation."
        PRD §2.7: "Implementations must evaluate the rungs in this order and stop at the first violated rung:"

        Design: Difficulty/priority_pair_validation_conflict/eirp_over_licence_ceiling_outranks_same_tower_coordination_referential_check
        """
        scenario = _setup_same_tower_sector_pair()
        assert scenario["license"]["max_eirp_dbm"] == pytest.approx(47.0, abs=0.05), (
            "Setup failed: the reference licence caps radiated power at 47.0 dBm, got "
            f"{scenario['license']['max_eirp_dbm']}"
        )

        response = api.create_coordination(
            {
                "requesting_sector_id": scenario["sector"]["id"],
                "neighbor_sector_id": scenario["neighbor_sector"]["id"],
                "proposed_channel_center_mhz": 3555.0,
                "proposed_channel_width_mhz": 10.0,
                "proposed_eirp_dbm": proposed_eirp_dbm,
                "guard_band_mhz": 2.0,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            network_engineer,
        )
        validate_error(response, expected_error, 422)

    def test_cross_tower_pair_reports_the_eirp_ceiling_on_its_own(
        self, api, network_engineer
    ):
        """PRD §3.4: "The `proposed_eirp_dbm` must not exceed that licence's `max_eirp_dbm`, else `ERR_EIRP_EXCEEDS_LICENSE`."
        PRD §3.4: "Coordination is between towers, never within one."

        Design: Difficulty/priority_pair_validation_conflict/eirp_over_licence_ceiling_outranks_same_tower_coordination_referential_check
        """
        pair = setup_neighbor_sectors()
        requesting_sector_id = pair["local"]["sector"]["id"]
        neighbor_sector_id = pair["neighbor"]["sector"]["id"]
        assert pair["local"]["tower"]["id"] != pair["neighbor"]["tower"]["id"], (
            "Setup failed: the two sectors must sit on different towers"
        )

        response = api.create_coordination(
            {
                "requesting_sector_id": requesting_sector_id,
                "neighbor_sector_id": neighbor_sector_id,
                "proposed_channel_center_mhz": 3570.0,
                "proposed_channel_width_mhz": 20.0,
                "proposed_eirp_dbm": 50.0,
                "guard_band_mhz": 1.0,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_EIRP_EXCEEDS_LICENSE, 422)

        requester_after = get_sector(requesting_sector_id)
        assert requester_after["tx_power_dbm"] == pytest.approx(25.0, abs=0.05)
        assert requester_after["eirp_dbm"] == pytest.approx(42.0, abs=0.05)


class TestWatchLineIsInclusive:
    """The watch line at exactly half the ceiling, from both sides of the `>=`."""

    def test_ratio_exactly_half_the_ceiling_reads_watch_and_follows_the_ceiling(
        self, api, sales_agent, capacity_planner
    ):
        """PRD §3.3: "Three fractions of the sector's own ceiling define the bands: the watch line sits at 0.50 of the ceiling, the withhold line at 0.75 of the ceiling, and the freeze line at 1.00 of the ceiling — that is, at `max_oversubscription_ratio` itself."
        PRD §3.3: "All three comparisons are inclusive, so a ratio landing exactly on a line takes the stricter posture."
        PRD §3.3: "Otherwise a provisional posture is read off the air ratio: `HOLD` when `oversubscription_ratio` is at or above three-quarters of `max_oversubscription_ratio`, `WATCH` when it is at or above half of `max_oversubscription_ratio`, and `OPEN` otherwise."
        PRD §3.3: "The new ratio is stored, the `justification` text is recorded on the sector as its `capacity_policy_note` — which stays absent until the first such override — and `oversubscription_ratio` and `capacity_posture` are recomputed immediately against the commitments already on the sector."

        Design: Difficulty/boundary_precision_check/sector_posture_watch_at_exactly_half_the_oversubscription_ceiling
        """
        scenario = setup_active_plant()
        reserve_bandwidth(scenario, 50)
        half_way = get_sector(scenario["sector"]["id"])
        assert half_way["committed_mbps"] == 50
        assert half_way["oversubscription_ratio"] == pytest.approx(2.0, abs=0.0005)
        assert half_way["capacity_posture"] == "OPEN", (
            "Setup failed: a ratio of 2.000 is below half of the 8.0 ceiling, got "
            f"{half_way['capacity_posture']}"
        )

        second_request = create_serviceability_request(
            scenario["tower"]["id"], scenario["plan"]["id"]
        )
        assert second_request["status"] == "QUALIFIED", (
            f"Setup failed: the sector is still OPEN, got {second_request['status']}"
        )

        hold = validate_success(
            api.create_capacity_hold(
                {
                    "serviceability_request_id": second_request["id"],
                    "expected_sector_version": half_way["version"],
                },
                sales_agent,
            ),
            201,
        )
        assert hold["status"] == "HELD"
        assert hold["held_mbps"] == 50, (
            f"the reservation takes the plan's 50 downstream Mbps, got {hold['held_mbps']}"
        )

        on_the_line = get_sector(scenario["sector"]["id"])
        assert on_the_line["held_mbps"] == 100
        assert on_the_line["committed_mbps"] == 100
        assert on_the_line["oversubscription_ratio"] == pytest.approx(4.0, abs=0.0005), (
            "100 committed Mbps over 25 Mbps of capacity is 4.000, got "
            f"{on_the_line['oversubscription_ratio']}"
        )
        assert on_the_line["capacity_posture"] == "WATCH", (
            "4.000 is exactly half of the 8.0 ceiling and the comparison is "
            f"inclusive, so the stricter posture wins, got {on_the_line['capacity_posture']}"
        )
        assert on_the_line["capacity_posture"] != "OPEN"

        retuned = change_capacity_policy(
            scenario["sector"]["id"],
            8.1,
            justification="Ceiling raised one notch to move the watch line above the current ratio",
            headers=capacity_planner,
        )
        assert retuned["max_oversubscription_ratio"] == pytest.approx(8.1, abs=0.005)
        assert retuned["committed_mbps"] == 100, (
            "retuning the ceiling does not touch the commitments, got "
            f"{retuned['committed_mbps']}"
        )
        assert retuned["oversubscription_ratio"] == pytest.approx(4.0, abs=0.0005), (
            "the ratio is committed over capacity and ignores the ceiling entirely, got "
            f"{retuned['oversubscription_ratio']}"
        )
        assert retuned["capacity_posture"] == "OPEN", (
            "half of 8.1 is 4.05, so the unchanged ratio of 4.000 now sits below the "
            f"watch line, got {retuned['capacity_posture']}"
        )

    @pytest.mark.parametrize(
        "second_reservation_mbps, expected_committed, expected_ratio, expected_posture",
        [
            (49, 99, 3.96, "OPEN"),
            (50, 100, 4.0, "WATCH"),
            (51, 101, 4.04, "WATCH"),
        ],
    )
    def test_posture_flips_to_watch_exactly_at_half_the_ceiling(
        self,
        api,
        second_reservation_mbps,
        expected_committed,
        expected_ratio,
        expected_posture,
    ):
        """PRD §3.3: "All three comparisons are inclusive, so a ratio landing exactly on a line takes the stricter posture."
        PRD §3.3: "`committed_mbps` is simply `sold_mbps` plus `held_mbps`, and `oversubscription_ratio` is `committed_mbps` divided by `capacity_mbps`, rounded half up to three decimal places."
        PRD §3.3: "Otherwise a provisional posture is read off the air ratio: `HOLD` when `oversubscription_ratio` is at or above three-quarters of `max_oversubscription_ratio`, `WATCH` when it is at or above half of `max_oversubscription_ratio`, and `OPEN` otherwise."

        Design: Difficulty/boundary_precision_check/sector_posture_watch_at_exactly_half_the_oversubscription_ceiling
        """
        scenario = setup_active_plant()
        reserve_bandwidth(scenario, 50)
        reserve_bandwidth(scenario, second_reservation_mbps)

        sector = get_sector(scenario["sector"]["id"])
        assert sector["max_oversubscription_ratio"] == pytest.approx(8.0, abs=0.005)
        assert sector["committed_mbps"] == expected_committed
        assert sector["oversubscription_ratio"] == pytest.approx(
            expected_ratio, abs=0.0005
        ), (
            f"{expected_committed} committed Mbps over 25 Mbps of capacity is "
            f"{expected_ratio:.3f}, got {sector['oversubscription_ratio']}"
        )
        assert sector["capacity_posture"] == expected_posture, (
            f"a ratio of {expected_ratio:.3f} against a watch line of 4.000 must read "
            f"{expected_posture}, got {sector['capacity_posture']}"
        )
        assert sector["remaining_allowance_mbps"] == 200 - expected_committed, (
            "floor(25 * 8.0) is 200 Mbps of ceiling, so the allowance is what is "
            f"left of it, got {sector['remaining_allowance_mbps']}"
        )


# The reference premise: tower antenna at 1200.0 + 45.0 = 1245.0 m AMSL, tree line
# top at 1210.0 + 3.0 = 1213.0 m, mounting surface at 1210.0 + 4.0 = 1214.0 m, and a
# 5.0 km CLEAR link, so 3.0 m of Fresnel clearance plus the 0.5 m safety margin puts
# the required antenna height at 1216.5 m: a margin of 28.5 m and a 2.5 m mast.
REFERENCE_PREMISE = {
    "contact_name": "Dana Reyes",
    "premise_latitude": 41.26,
    "premise_longitude": -104.76,
    "premise_ground_elevation_m": 1210.0,
    "roof_height_m": 4.0,
    "declared_tree_line_height_m": 3.0,
    "obstruction_class": "CLEAR",
    "path_distance_km": 5.0,
}


def _premise_payload(tower_id: str, plan_id: str, **overrides) -> dict:
    payload = dict(REFERENCE_PREMISE)
    payload["candidate_tower_id"] = tower_id
    payload["requested_plan_id"] = plan_id
    payload.update(overrides)
    return payload


class TestEmptyActiveSectorSetDeniesQualification:
    """The zero-cardinality edge of the candidate pool on POST /serviceability-requests."""

    def test_tower_with_no_active_sector_denies_the_enquiry(
        self, api, sales_agent, capacity_planner
    ):
        """PRD §3.5: "In the desktop study only, five refusal conditions are tested in strict sequence and the **first** one that holds decides the outcome; later conditions are not evaluated and their fields are not filled in:"
        PRD §3.5: "no sector on the candidate tower is in `ACTIVE` status — `DENIED` with `NO_ACTIVE_SECTOR`."
        PRD §3.5: "Otherwise, if the tower has no sector in `ACTIVE` status at all, the enquiry moves `EVALUATING → DENIED` with `denial_reason` `NO_ACTIVE_SECTOR`."
        PRD §3.5: "The desktop study writes its findings onto the enquiry as `desktop_los_margin_m`, `desktop_required_mast_height_m` and `desktop_mounting_type`; a denial reached at step 1 or step 2 records no geometry, and a denial for mast limit records the margin and the mast requirement while leaving `desktop_mounting_type` absent. A denied enquiry has no `qualified_sector_id` and no `qualification_expires_at`, and `DENIED` is terminal."
        PRD §3.5: "The rounded mast requirement selects a mounting band, with every upper bound inclusive: at or below 1.0 metre a `WALL_BRACKET`; above that and at or below 3.0 metres a `NON_PEN_ROOF_TRIPOD`; above that and at or below 6.0 metres a `ROOF_MAST_GUYED`; above that and at or below 12.0 metres a `GROUND_POLE_MAST`."
        PRD §3.1: "A tower's `active_sector_count` is at all times the number of its sectors whose `status` is `ACTIVE`, so decommissioning drives it to zero."

        Design: Difficulty/boundary_precision_check/serviceability_denied_when_active_sector_candidate_set_is_empty
        """
        scenario = setup_active_plant(activate_the_sector=False)
        tower = get_tower(scenario["tower"]["id"])
        assert tower["status"] == "ACTIVE", (
            f"Setup failed: the site itself must be on air, got {tower['status']}"
        )
        assert tower["backhaul_accepted_mbps"] == 500, (
            "Setup failed: the accepted 500 Mbps circuit is what makes the tower "
            f"serviceable, got {tower['backhaul_accepted_mbps']}"
        )
        assert tower["active_sector_count"] == 0, (
            "Setup failed: the tower's only sector was never activated, got "
            f"{tower['active_sector_count']}"
        )
        assert get_sector(scenario["sector"]["id"])["status"] == "PLANNED"

        request = validate_success(
            api.create_serviceability_request(
                _premise_payload(tower["id"], scenario["plan"]["id"]), sales_agent
            ),
            201,
        )
        assert request["status"] == "DENIED", (
            "an empty ACTIVE-sector set is a denial, not a deferral, got "
            f"{request['status']}"
        )
        assert request["denial_reason"] == "NO_ACTIVE_SECTOR"
        assert request.get("qualified_sector_id") is None, (
            f"a denied enquiry has no qualified sector, got {request.get('qualified_sector_id')}"
        )
        assert request.get("qualification_expires_at") is None, (
            "a denied enquiry has no qualification expiry, got "
            f"{request.get('qualification_expires_at')}"
        )
        assert request["desktop_los_margin_m"] == pytest.approx(28.5, abs=0.05), (
            "the geometry runs before the sector search, so 1245.0 less 1216.5 is "
            f"recorded, got {request['desktop_los_margin_m']}"
        )
        assert request["desktop_required_mast_height_m"] == pytest.approx(2.5, abs=0.05), (
            "1216.5 less the 1214.0 mounting surface is 2.5 m, already a whole "
            f"half-metre, got {request['desktop_required_mast_height_m']}"
        )
        assert request["desktop_mounting_type"] == "NON_PEN_ROOF_TRIPOD", (
            "2.5 m is above 1.0 and at or below 3.0 m, got "
            f"{request['desktop_mounting_type']}"
        )

        sectors, meta = validate_paginated(
            api.list_sectors(
                capacity_planner, params={"tower_id": tower["id"], "status": "ACTIVE"}
            )
        )
        assert sectors == [], f"the ACTIVE-sector candidate set is empty, got {sectors}"
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_same_premise_qualifies_once_one_sector_is_on_air(self, api, sales_agent):
        """PRD §3.5: "Only when none of the five refusals holds does the sector search run."
        PRD §3.5: "When at least one sector is eligible, the top-ranked one becomes the enquiry's `qualified_sector_id`, the enquiry moves `EVALUATING → QUALIFIED`, and `qualification_expires_at` is set to the current logical clock advanced by the qualification validity of 30 days."
        PRD §3.5: "Otherwise, if the tower has no sector in `ACTIVE` status at all, the enquiry moves `EVALUATING → DENIED` with `denial_reason` `NO_ACTIVE_SECTOR`."

        Design: Difficulty/boundary_precision_check/serviceability_denied_when_active_sector_candidate_set_is_empty
        """
        scenario = setup_active_plant(activate_the_sector=False)
        denied = validate_success(
            api.create_serviceability_request(
                _premise_payload(scenario["tower"]["id"], scenario["plan"]["id"]),
                sales_agent,
            ),
            201,
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "NO_ACTIVE_SECTOR"

        sector = activate_sector(scenario["sector"]["id"])
        assert sector["status"] == "ACTIVE"
        assert get_tower(scenario["tower"]["id"])["active_sector_count"] == 1, (
            "activation recomputes the parent tower's ACTIVE-sector count"
        )

        qualified = validate_success(
            api.create_serviceability_request(
                _premise_payload(scenario["tower"]["id"], scenario["plan"]["id"]),
                sales_agent,
            ),
            201,
        )
        assert qualified["status"] == "QUALIFIED", (
            "the identical premise now finds a candidate, which is what proves the "
            f"earlier denial turned on the empty set, got {qualified['status']}"
        )
        assert qualified["qualified_sector_id"] == sector["id"]
        assert qualified.get("denial_reason") is None
        assert str(qualified["qualification_expires_at"]).startswith(
            "2026-08-31T00:00:00"
        ), (
            "the clock is at its startup reading, so 30 days on is 2026-08-31, got "
            f"{qualified['qualification_expires_at']}"
        )
        assert qualified["desktop_los_margin_m"] == pytest.approx(28.5, abs=0.05)
        assert qualified["desktop_required_mast_height_m"] == pytest.approx(2.5, abs=0.05)

        denied_after = get_serviceability_request(denied["id"])
        assert denied_after["status"] == "DENIED", (
            "`DENIED` is terminal, so bringing a sector on air does not revive the "
            f"earlier enquiry, got {denied_after['status']}"
        )

    def test_distance_denial_preempts_the_empty_candidate_set(self, api, sales_agent):
        """PRD §3.5: "`path_distance_km` strictly greater than 15.0 — the enquiry is `DENIED` with `denial_reason` `LINK_DISTANCE_EXCEEDED`."
        PRD §3.5: "Because the geometry runs before the sector search, a premise beyond 15.0 kilometres of a tower with no sectors at all is denied for distance and not for absence of sectors."
        PRD §3.5: "The desktop study writes its findings onto the enquiry as `desktop_los_margin_m`, `desktop_required_mast_height_m` and `desktop_mounting_type`; a denial reached at step 1 or step 2 records no geometry, and a denial for mast limit records the margin and the mast requirement while leaving `desktop_mounting_type` absent. A denied enquiry has no `qualified_sector_id` and no `qualification_expires_at`, and `DENIED` is terminal."

        Design: Difficulty/boundary_precision_check/serviceability_denied_when_active_sector_candidate_set_is_empty
        """
        scenario = setup_active_plant(activate_the_sector=False)
        request = validate_success(
            api.create_serviceability_request(
                _premise_payload(
                    scenario["tower"]["id"],
                    scenario["plan"]["id"],
                    path_distance_km=15.1,
                ),
                sales_agent,
            ),
            201,
        )
        assert request["status"] == "DENIED"
        assert request["denial_reason"] == "LINK_DISTANCE_EXCEEDED", (
            "the first refusal that holds decides the outcome, and distance is tested "
            f"before the sector search, got {request['denial_reason']}"
        )
        assert request.get("desktop_los_margin_m") is None, (
            "a denial reached at step 1 records no geometry, got "
            f"{request.get('desktop_los_margin_m')}"
        )
        assert request.get("desktop_required_mast_height_m") is None
        assert request.get("desktop_mounting_type") is None
        assert request.get("qualification_expires_at") is None


class TestSectorActivationReadsTheParentTowerStatus:
    """POST /sectors/{id}/activation is gated on a field of the parent tower."""

    def test_planned_tower_blocks_activation_until_transport_is_accepted(
        self, api, network_engineer
    ):
        """PRD §3.2: "Bringing a sector on air moves it `PLANNED → ACTIVE`. Three preconditions apply, and each has its own code: the sector's `status` must be `PLANNED`, and activating a sector in any other status is refused with `ERR_INVALID_SECTOR_STATE`; the parent tower's `status` must be `ACTIVE`, and a tower in any other status is refused with `ERR_INVALID_TOWER_STATE`; and the bound licence's clock-derived `status` must be `ACTIVE` at the current logical clock, a `PENDING` or `EXPIRED` licence being refused with `ERR_LICENSE_NOT_EFFECTIVE`. Activation recomputes the parent tower's `active_sector_count` and the sector's own `capacity_posture`."
        PRD §3.1: "Bringing a `PLANNED` site to `ACTIVE` requires that at least one circuit on the tower be in `ACCEPTED` state; if none is, the request is refused with `ERR_BACKHAUL_NOT_ACCEPTED`. Activation recomputes `backhaul_accepted_mbps` and recomputes `capacity_posture` on every sector of the tower."
        PRD §3.1: "A tower's `active_sector_count` is at all times the number of its sectors whose `status` is `ACTIVE`, so decommissioning drives it to zero."

        Design: Difficulty/cross_entity_state_dependency/sector_activation_gated_on_parent_tower_status_active
        """
        tower = create_tower()
        circuit = create_backhaul_circuit(tower["id"])
        license_ = create_spectrum_license()
        sector = create_sector(tower["id"], license_["id"])
        assert tower["status"] == "PLANNED"
        assert circuit["state"] == "ORDERED", (
            f"Setup failed: a fresh circuit opens in ORDERED, got {circuit['state']}"
        )
        assert sector["status"] == "PLANNED"
        assert get_tower(tower["id"])["backhaul_accepted_mbps"] == 0, (
            "Setup failed: no circuit is ACCEPTED yet"
        )

        blocked_tower = api.change_tower_status(
            tower["id"], {"to_status": "ACTIVE"}, network_engineer
        )
        validate_error(blocked_tower, ApiErrorId.ERR_BACKHAUL_NOT_ACCEPTED, 409)

        blocked_sector = api.activate_sector(sector["id"], network_engineer)
        validate_error(blocked_sector, ApiErrorId.ERR_INVALID_TOWER_STATE, 409)

        assert get_sector(sector["id"])["status"] == "PLANNED", (
            "a refused activation leaves the sector where it was"
        )
        assert get_tower(tower["id"])["active_sector_count"] == 0

        change_circuit_state(circuit["id"], "INSTALLED")
        accepted = change_circuit_state(circuit["id"], "ACCEPTED", measured_mbps=505.0)
        assert accepted["state"] == "ACCEPTED"
        live_tower = change_tower_status(tower["id"], "ACTIVE")
        assert live_tower["status"] == "ACTIVE"
        assert live_tower["backhaul_accepted_mbps"] == 500, (
            "the tower counts the circuit's committed 500 Mbps once it is ACCEPTED, got "
            f"{live_tower['backhaul_accepted_mbps']}"
        )

        activated = validate_success(
            api.activate_sector(sector["id"], network_engineer), 200
        )
        assert activated["status"] == "ACTIVE", (
            "the identical activation call now succeeds because the parent tower's "
            f"status changed, got {activated['status']}"
        )
        assert activated["capacity_posture"] == "OPEN", (
            "an empty sector on accepted transport recomputes to OPEN, got "
            f"{activated['capacity_posture']}"
        )
        assert get_tower(tower["id"])["active_sector_count"] == 1, (
            "activation recomputes the parent tower's ACTIVE-sector count"
        )

    def test_tower_in_maintenance_blocks_activation_despite_accepted_transport(
        self, api, network_engineer
    ):
        """PRD §3.2: "Bringing a sector on air moves it `PLANNED → ACTIVE`. Three preconditions apply, and each has its own code: the sector's `status` must be `PLANNED`, and activating a sector in any other status is refused with `ERR_INVALID_SECTOR_STATE`; the parent tower's `status` must be `ACTIVE`, and a tower in any other status is refused with `ERR_INVALID_TOWER_STATE`; and the bound licence's clock-derived `status` must be `ACTIVE` at the current logical clock, a `PENDING` or `EXPIRED` licence being refused with `ERR_LICENSE_NOT_EFFECTIVE`. Activation recomputes the parent tower's `active_sector_count` and the sector's own `capacity_posture`."
        PRD §3.1: "`ACTIVE → MAINTENANCE` carries no additional precondition beyond the site currently being `ACTIVE`; maintenance does **not** freeze sectors and does not disturb capacity — it is an operational marker used by outage reporting."

        Design: Difficulty/cross_entity_state_dependency/sector_activation_gated_on_parent_tower_status_active
        """
        scenario = setup_active_plant(activate_the_sector=False)
        sector_before = get_sector(scenario["sector"]["id"])
        assert sector_before["status"] == "PLANNED"

        in_maintenance = change_tower_status(scenario["tower"]["id"], "MAINTENANCE")
        assert in_maintenance["status"] == "MAINTENANCE"
        assert in_maintenance["backhaul_accepted_mbps"] == 500, (
            "maintenance does not disturb transport, so the gate cannot be about "
            f"backhaul, got {in_maintenance['backhaul_accepted_mbps']}"
        )

        response = api.activate_sector(sector_before["id"], network_engineer)
        validate_error(response, ApiErrorId.ERR_INVALID_TOWER_STATE, 409)

        sector_after = get_sector(sector_before["id"])
        assert sector_after["status"] == "PLANNED", (
            "the sector's own status permitted activation; only the parent's status "
            f"did not, got {sector_after['status']}"
        )
        assert sector_after["version"] == sector_before["version"]
        assert get_tower(scenario["tower"]["id"])["active_sector_count"] == 0

        change_tower_status(scenario["tower"]["id"], "ACTIVE")
        activated = validate_success(
            api.activate_sector(sector_before["id"], network_engineer), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["capacity_posture"] == "OPEN"


class TestInstallCompletionReadsTheAccountStatus:
    """POST /install-work-orders/{id}/completion is gated on the account's status."""

    def test_revisit_on_an_active_account_reaches_mount_approved_but_never_completes(
        self, api, field_tech
    ):
        """PRD §3.7: "The linked account's `service_status` must be `PENDING_INSTALL`, else `ERR_SUBSCRIBER_NOT_ACTIVE`; an account already `ACTIVE` cannot be activated a second time."
        PRD §4: "Accepted for any account whose `service_status` is `PENDING_INSTALL`, `ACTIVE` or `SUSPENDED` so that re-visits on a live account are possible; a `CANCELLED` account is refused with `ERR_SUBSCRIBER_NOT_ACTIVE`. Only completion requires `service_status` of `PENDING_INSTALL`, so a re-visit work order on an `ACTIVE` account can be surveyed and approved but never completed."
        PRD §3.7: "On success the work order moves `MOUNT_APPROVED → INSTALLED`, which is terminal, storing `installed_mast_height_m`, `radio_serial` and an `installed_at` stamp taken from the logical clock, and computing `install_invoice_total_cents`."

        Design: Difficulty/cross_entity_state_dependency/install_completion_gated_on_subscriber_pending_install_status
        """
        scenario = setup_active_subscriber()
        subscriber_id = scenario["subscriber"]["id"]
        first_order = get_work_order(scenario["work_order"]["id"])
        assert first_order["status"] == "INSTALLED", (
            f"Setup failed: the first visit must be finished, got {first_order['status']}"
        )
        assert get_subscriber(subscriber_id)["service_status"] == "ACTIVE", (
            "Setup failed: completing the first install turns the account live"
        )

        revisit = create_work_order(subscriber_id, scheduled_at="2026-08-07T15:00:00Z")
        assert revisit["status"] == "SCHEDULED", (
            "a re-visit is bookable on a live account, got " f"{revisit['status']}"
        )
        assert revisit["id"] != first_order["id"]

        revisit = survey_work_order(revisit["id"], **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"])
        assert revisit["status"] == "MOUNT_APPROVED", (
            "the re-visit is surveyed and approved just like any other, got "
            f"{revisit['status']}"
        )
        assert revisit["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD"

        response = api.complete_work_order(
            revisit["id"],
            {"installed_mast_height_m": 2.5, "radio_serial": "RAD-0009"},
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE, 409)

        revisit_after = get_work_order(revisit["id"])
        assert revisit_after["status"] == "MOUNT_APPROVED", (
            "the work order itself was in the one status completion permits, so the "
            f"refusal must leave it there, got {revisit_after['status']}"
        )
        assert revisit_after["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD"
        assert revisit_after.get("install_invoice_total_cents") is None, (
            "no invoice is computed for a refused completion, got "
            f"{revisit_after.get('install_invoice_total_cents')}"
        )
        assert revisit_after.get("installed_at") is None
        assert revisit_after.get("radio_serial") is None, (
            f"the reported serial must not be stored, got {revisit_after.get('radio_serial')}"
        )

        first_after = get_work_order(first_order["id"])
        assert first_after["status"] == "INSTALLED"
        assert (
            first_after["install_invoice_total_cents"]
            == first_order["install_invoice_total_cents"]
        ), "the finished visit's invoice must not be touched"

        subscriber_after = get_subscriber(subscriber_id)
        assert subscriber_after["service_status"] == "ACTIVE", (
            f"the account stays exactly as it was, got {subscriber_after['service_status']}"
        )
        assignment = get_assignment_for_subscriber(subscriber_id)
        assert assignment["status"] == "DEPLOYED", (
            f"the radio already on the wall is untouched, got {assignment['status']}"
        )
        assert subscriber_after["equipment_monthly_charge_cents"] == 1000, (
            "the rental charge began at the first deployment and does not change, got "
            f"{subscriber_after['equipment_monthly_charge_cents']}"
        )

    def test_suspended_account_also_blocks_completion(self, api, field_tech):
        """PRD §3.7: "The linked account's `service_status` must be `PENDING_INSTALL`, else `ERR_SUBSCRIBER_NOT_ACTIVE`; an account already `ACTIVE` cannot be activated a second time."
        PRD §3.7: "Booking is accepted for an account whose `service_status` is `PENDING_INSTALL`, `ACTIVE` or `SUSPENDED` — a visit to an existing account is a legitimate re-install or relocation — but an account already `CANCELLED` is refused with `ERR_SUBSCRIBER_NOT_ACTIVE`."
        PRD §3.8: "`ACTIVE → SUSPENDED` is a billing suspension; it explicitly does **not** release the account's share of the sector's `sold_mbps`, because a suspended household is expected back and its bandwidth is still allocated."

        Design: Difficulty/cross_entity_state_dependency/install_completion_gated_on_subscriber_pending_install_status
        """
        scenario = setup_active_subscriber()
        subscriber_id = scenario["subscriber"]["id"]
        suspended = change_subscriber_status(
            subscriber_id, "SUSPENDED", reason="Payment arrears"
        )
        assert suspended["service_status"] == "SUSPENDED"

        revisit = create_work_order(subscriber_id, scheduled_at="2026-08-07T15:00:00Z")
        assert revisit["status"] == "SCHEDULED", (
            "booking is accepted for a SUSPENDED account, got " f"{revisit['status']}"
        )
        revisit = survey_work_order(revisit["id"], **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"])
        assert revisit["status"] == "MOUNT_APPROVED"

        response = api.complete_work_order(
            revisit["id"],
            {"installed_mast_height_m": 2.5, "radio_serial": "RAD-0010"},
            field_tech,
        )
        validate_error(response, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE, 409)

        assert get_work_order(revisit["id"])["status"] == "MOUNT_APPROVED"
        assert get_subscriber(subscriber_id)["service_status"] == "SUSPENDED", (
            "the refused completion must not move the account"
        )

    def test_pending_install_account_completes_the_same_work_order(self, api, field_tech):
        """PRD §3.7: "The linked account's `service_status` must be `PENDING_INSTALL`, else `ERR_SUBSCRIBER_NOT_ACTIVE`; an account already `ACTIVE` cannot be activated a second time."
        PRD §3.7: "On success the work order moves `MOUNT_APPROVED → INSTALLED`, which is terminal, storing `installed_mast_height_m`, `radio_serial` and an `installed_at` stamp taken from the logical clock, and computing `install_invoice_total_cents`."
        PRD §3.7: "Begin with a labour charge selected by `approved_mounting_type`: 4900 cents for a `WALL_BRACKET`, 9900 for a `NON_PEN_ROOF_TRIPOD`, 19900 for a `ROOF_MAST_GUYED`, and 34900 for a `GROUND_POLE_MAST`. Add a mast kit charge of 1750 cents per half-metre section, where the number of sections is `installed_mast_height_m` divided by 0.5 and rounded **upward** to a whole number — a 2.6 metre mast bills six sections. Add the fixed trip charge of 9900 cents. The sum of trip charge, labour and mast kit is the subtotal."
        PRD §3.7: "A volume discount is then read off the **subtotal only**, with inclusive lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above 20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns nothing. The net amount is the subtotal less that discount. A regulatory cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded half up to whole cents, and `install_invoice_total_cents` is the net amount plus that fee."
        PRD §3.7: "The account's `equipment_monthly_charge_cents` is then recomputed and becomes the equipment record's `monthly_rental_cents` — 1000 cents for a rental, zero for a purchase — because the recurring charge only begins once the radio is deployed."

        Design: Difficulty/cross_entity_state_dependency/install_completion_gated_on_subscriber_pending_install_status
        """
        scenario = setup_work_order_in_state("MOUNT_APPROVED")
        subscriber_id = scenario["subscriber"]["id"]
        work_order = scenario["work_order"]
        assert work_order["status"] == "MOUNT_APPROVED"
        assert work_order["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD"
        assert get_subscriber(subscriber_id)["service_status"] == "PENDING_INSTALL", (
            "Setup failed: the account is still waiting for its first install"
        )

        completed = validate_success(
            api.complete_work_order(
                work_order["id"],
                {"installed_mast_height_m": 2.5, "radio_serial": "RAD-0001"},
                field_tech,
            ),
            200,
        )
        assert completed["status"] == "INSTALLED", (
            "the identical call succeeds on a PENDING_INSTALL account, which is what "
            f"pins the gate to the account's status, got {completed['status']}"
        )
        assert completed["radio_serial"] == "RAD-0001"
        assert completed["installed_at"] is not None
        assert completed["install_invoice_total_cents"] == 26380, (
            "9900 labour plus five 1750-cent sections plus the 9900 trip charge is a "
            "subtotal of 28550, less the 3000 discount is 25550 net, plus 830 of "
            f"regulatory fee is 26380, got {completed['install_invoice_total_cents']}"
        )

        subscriber_after = get_subscriber(subscriber_id)
        assert subscriber_after["service_status"] == "ACTIVE"
        assert subscriber_after["equipment_monthly_charge_cents"] == 1000, (
            "the rental charge begins at deployment, got "
            f"{subscriber_after['equipment_monthly_charge_cents']}"
        )
        assignment = get_assignment_for_subscriber(subscriber_id)
        assert assignment["status"] == "DEPLOYED"
        assert assignment["radio_serial"] == "RAD-0001", (
            "the record of the unit and the unit on the wall must agree, got "
            f"{assignment.get('radio_serial')}"
        )
