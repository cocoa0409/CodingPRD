"""Role-based access control: the authorized-role list of every endpoint.

PRD §2.1 recognises exactly seven role names and states that "Once the role is
recognised, the endpoint's own permitted-role list governs: a recognised role
attempting an operation it does not own is rejected with
`ERR_ROLE_NOT_PERMITTED`." §4 carries that list in its final column, and its
preamble pins the refusal: "The role names in the final column are the values
`X-User-Role` may carry for that operation; any other recognised role receives
`ERR_ROLE_NOT_PERMITTED`."

Each role below gets an allowed call that resolves and a denied call that comes
back with the role refusal, plus the two structural consequences of the four
`role_class` values covering seven roles: the entity-backed roles carry an
Operator row and therefore the suspension gate, while the three opaque roles
carry only a header.
"""
from test_helpers import (
    COMPLIANCE,
    TRAFFIC,
    factories,
    fixtures as fx,
    make_admin_headers,
    make_traffic_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()


# ---------------------------------------------------------------------------
# Local setup helpers (built only from PRD endpoints)
# ---------------------------------------------------------------------------

def _received_asset(plant: dict, duration_seconds: int = 60) -> dict:
    """Register and deliver one asset, leaving it in RECEIVED."""
    asset = fx.create_asset(plant, expected_duration_seconds=duration_seconds)
    return fx.deliver_asset(plant, asset["id"],
                            measured_duration_seconds=duration_seconds)


def _waivable_failed_asset(plant: dict, duration_seconds: int = 60) -> dict:
    """Drive an asset to QC_FAILED on a score that is still above the waiver floor.

    Defect codes VIDEO_ARTIFACT (10) and FORMAT_MISMATCH (15) leave a score of
    75, so the waiver floor of 40 is met and FORMAT_MISMATCH is what forces the
    FAIL — nothing but a role list can refuse the waiver that follows.
    """
    asset = fx.setup_qc_failed_asset(
        plant, duration_seconds,
        defect_codes=["VIDEO_ARTIFACT", "FORMAT_MISMATCH"],
        qc_overrides={"measured_duration_seconds": duration_seconds},
    )
    assert asset["status"] == "QC_FAILED", "setup must leave the asset QC_FAILED"
    return asset


def _pending_power_reduction(plant: dict) -> dict:
    """Reduce licensed power to 50 percent so a PENDING filing obligation exists."""
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=50)
    notifications = fx.list_notifications(plant["transmitter"]["id"],
                                          plant["admin_headers"])
    assert notifications, "setup must mint one POWER_REDUCTION notification"
    return notifications[0]


def _single_program_day(channel_id: str, broadcast_day: str, start_utc: str,
                        asset_id=None) -> dict:
    """A one-element broadcast day whose first item starts at the schedule start."""
    item = {
        "sequence_number": 1,
        "element_kind": "PROGRAM",
        "scheduled_start_utc": start_utc,
        "scheduled_duration_seconds": 1800,
    }
    if asset_id:
        item["asset_id"] = asset_id
    return factories.ingest_playlist_payload(
        channel_id, [item], broadcast_day=broadcast_day,
        schedule_start_utc=start_utc,
    )


# ===========================================================================
# StationAdmin — the whole API surface, and not one business rule waived
# ===========================================================================

def test_station_admin_may_create_an_operator_record(api):
    """The operator-minting endpoint names StationAdmin as its only role.

    PRD §4: "| POST | `/operators` | Create an operator record with its role class, override authority and certification expiry. | StationAdmin |"

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    resp = api.create_operator(
        factories.create_operator_payload(
            "PROGRAM_DIRECTOR",
            full_name="Gil Payne",
            override_authority="FULL",
            certification_expires_utc="2026-12-31T00:00:00Z",
        ),
        ADMIN,
    )
    created = validate_success(resp, 201)
    assert created["role_class"] == "PROGRAM_DIRECTOR", \
        "the created record must carry the requested role class"


def test_a_program_director_may_not_create_an_operator_record(api):
    """Every role other than StationAdmin is refused on the operator endpoint.

    PRD §4: "The role names in the final column are the values `X-User-Role` may carry for that operation; any other recognised role receives `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    plant = fx.bootstrap_operators()

    resp = api.create_operator(
        factories.create_operator_payload(
            "QC", full_name="Imposter", override_authority="NONE",
            certification_expires_utc="2026-12-31T00:00:00Z",
        ),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_broadcast_engineer_may_not_suspend_an_operator(api):
    """Suspension is a StationAdmin-only write, so the engineer is refused.

    PRD §4: "| POST | `/operators/{id}/status` | Suspend or reinstate an operator, or extend certification and override authority. | StationAdmin |"

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    plant = fx.bootstrap_operators()

    resp = api.update_operator_status(plant["pd"]["id"], {"status": "SUSPENDED"},
                                     plant["eng_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")

    after = fx.read_operator(plant["pd"]["id"])
    assert after["status"] == "ACTIVE", "the refused suspension must not land"


def test_station_admin_takes_a_channel_to_bars_without_any_operator_row(api):
    """The air-state write resolves for StationAdmin's opaque identifier.

    PRD §2.1: "`StationAdmin` may perform every mutating operation in the domain, but because it acts with an opaque identifier it can never satisfy one half of a two-person rule"

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    plant = fx.setup_base_plant()
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")

    resp = api.change_channel_air_state(
        plant["ch1"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="ADMIN_INTERVENTION"),
        ADMIN,
    )
    channel = validate_success(resp)
    assert channel["air_status"] == "BARS_AND_TONE", \
        "the admin's air-state write must take effect"


def test_station_admin_files_a_qc_report_by_naming_a_qc_class_inspector(api):
    """Permission comes from the role list; the inspector comes from the body.

    PRD §4: "| POST | `/assets/{id}/qc-reports` | Submit a quality-control inspection on an ingest or air-check basis. | QCTechnician, StationAdmin |"

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    plant = fx.bootstrap_operators()
    asset = fx.setup_qc_passed_asset(plant, 60)

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(asset["version"], plant["qc"]["id"],
                                    basis="AIR_CHECK", measured_duration_seconds=60),
        ADMIN,
    )
    report = validate_success(resp, 201)
    assert report["inspected_by_operator_id"] == plant["qc"]["id"], \
        "the report must record the named QC-class inspector"


def test_station_admin_naming_an_engineer_as_inspector_is_refused(api):
    """The role_class of the referenced operator is checked independently of permission.

    PRD §3.4: "`inspected_by_operator_id` must reference an operator whose `role_class` is `QC` and whose `status` is `ACTIVE`; a wrong role class yields `ERR_OPERATOR_ROLE_CLASS_INVALID`."

    Design: Corner/rbac/station_admin_is_a_strict_superset_of_all_59_endpoints_but_bypasses_no_business_rule
    """
    plant = fx.bootstrap_operators()
    asset = fx.setup_qc_passed_asset(plant, 60)

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(asset["version"], plant["eng"]["id"],
                                    basis="AIR_CHECK", measured_duration_seconds=60),
        ADMIN,
    )
    validate_error(resp, "ERR_OPERATOR_ROLE_CLASS_INVALID")


# ===========================================================================
# BroadcastEngineer — the RF and capacity plane, locked out of content
# ===========================================================================

def test_broadcast_engineer_creates_a_multiplex(api):
    """Transport-stream capacity is the engineer's own plane.

    PRD §4: "| POST | `/multiplexes` | Create a transport-stream multiplex on a transmitter with its capacity and pilot reservation. | BroadcastEngineer, StationAdmin |"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    plant = fx.bootstrap_operators()
    transmitter = fx.create_transmitter(plant["eng_headers"])

    resp = api.create_multiplex(
        factories.create_multiplex_payload(
            transmitter["id"], name="MUX-D", total_capacity_kbps=12000,
            pilot_reserved_kbps=500, live_encoder_units_total=2,
        ),
        plant["eng_headers"],
    )
    multiplex = validate_success(resp, 201)
    assert multiplex["transmitter_id"] == transmitter["id"], \
        "the multiplex must hang off the engineer's transmitter"


def test_a_broadcast_engineer_may_not_change_a_channel_air_state(api):
    """Air state belongs to master control, not to the engineer.

    PRD §4: "| POST | `/channels/{id}/air-state` | Take the channel to air, to bars-and-tone, or dark. | MasterControlOperator, StationAdmin |"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    plant = fx.setup_base_plant()

    resp = api.change_channel_air_state(
        plant["ch1"]["id"],
        factories.air_state_payload("DARK", reason="ENGINEER_ATTEMPT"),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_broadcast_engineer_may_not_report_a_playout_event(api):
    """The automation axis is closed to the engineer.

    PRD §4: "| POST | `/playlist-items/{id}/playout-events` | Report an automation playout event and append the corresponding as-run entry. | MasterControlOperator, StationAdmin |"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    scn = fx.setup_playlist_scenario()

    resp = api.post_playout_event(
        scn["items"][0]["id"],
        factories.playout_event_payload("CUE", "2026-08-01T09:00:00Z",
                                        source="OPERATOR"),
        scn["eng_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_broadcast_engineer_may_not_submit_a_qc_report(api):
    """Grading media is not part of the engineer's surface.

    PRD §4: "| POST | `/assets/{id}/qc-reports` | Submit a quality-control inspection on an ingest or air-check basis. | QCTechnician, StationAdmin |"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    plant = fx.bootstrap_operators()
    asset = fx.setup_qc_passed_asset(plant, 60)

    resp = api.submit_qc_report(
        asset["id"],
        factories.qc_report_payload(asset["version"], plant["qc"]["id"],
                                    basis="AIR_CHECK", measured_duration_seconds=60),
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_broadcast_engineer_may_not_read_the_reconciliation_view(api):
    """The settlement projection is outside the engineer's read surface.

    PRD §4: "| GET | `/playlists/{id}/reconciliation` | Computed read reconciling the as-run log against the spot orders this playlist touched. | ProgramDirector, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    scn = fx.setup_playlist_scenario()

    resp = api.get_playlist_reconciliation(scn["playlist"]["id"], scn["eng_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_the_engineer_darkens_a_channel_it_may_not_command_directly(api):
    """Taking the plant off air drives every carried channel DARK.

    PRD §3.1: "every channel on every one of those multiplexes is driven to `allocation_state` `STARVED`; each such channel's `posture` becomes `SUSPENDED` and its `air_status` becomes `DARK`"

    Design: Corner/rbac/broadcast_engineer_owns_the_rf_and_capacity_plane_and_is_locked_out_of_content
    """
    scn = fx.setup_on_air_playlist()

    resp = api.change_transmitter_power_state(
        scn["transmitter"]["id"],
        factories.power_state_payload("OFF_AIR", reason="TOTAL_POWER_LOSS"),
        scn["eng_headers"],
    )
    transmitter = validate_success(resp)
    assert transmitter["operational_state"] == "OFF_AIR", \
        "the engineer's power write must take the plant off air"

    channel = validate_success(api.get_channel(scn["ch1"]["id"], scn["eng_headers"]))
    assert channel["air_status"] == "DARK", \
        "the cascade must dark the channel the engineer cannot command"
    assert channel["posture"] == "SUSPENDED", \
        "the cascade must suspend the channel's posture"


# ===========================================================================
# MasterControlOperator — the air chain, without the money view
# ===========================================================================

def test_master_control_cues_an_element_on_the_on_air_day(api):
    """Only master control can move an element through the playout machine.

    PRD §4: "| POST | `/playlist-items/{id}/playout-events` | Report an automation playout event and append the corresponding as-run entry. | MasterControlOperator, StationAdmin |"

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    scn = fx.setup_on_air_playlist()

    resp = api.post_playout_event(
        scn["items"][0]["id"],
        factories.playout_event_payload("CUE", "2026-08-01T11:59:00Z",
                                        source="OPERATOR"),
        scn["mco_headers"],
    )
    entry = validate_success(resp, 201)
    assert entry["event_kind"] == "CUE", "the as-run entry must record the cue"


def test_master_control_may_not_read_the_reconciliation_view(api):
    """The role that writes the as-run log is excluded from the money view.

    PRD §4: "| GET | `/playlists/{id}/reconciliation` | Computed read reconciling the as-run log against the spot orders this playlist touched. | ProgramDirector, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    scn = fx.setup_playlist_scenario()

    resp = api.get_playlist_reconciliation(scn["playlist"]["id"], scn["mco_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_master_control_may_not_list_regulatory_notifications(api):
    """Air decisions create outages, but the filing catalogue is not an MCO read.

    PRD §4: "| GET | `/transmitters/{id}/notifications` | List the regulatory notifications raised for this transmitter. | BroadcastEngineer, ComplianceOfficer, StationAdmin |"

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    plant = fx.bootstrap_operators()
    transmitter = fx.create_transmitter(plant["eng_headers"])

    resp = api.list_transmitter_notifications(transmitter["id"], plant["mco_headers"])
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_master_control_may_still_read_the_order_it_credits(api):
    """The exclusion is specific to the projection, not to the order entity.

    PRD §4: "| GET | `/spot-orders/{id}` | Read one order with its inventory counters and accrued credit. | MasterControlOperator, ProgramDirector, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    PRD §3.9: "An order is created in `status` `OPEN` with every counter at 0 except `unplaced_spots`, which starts equal to `ordered_spots`."

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    plant = fx.setup_base_plant()
    order = fx.create_order(plant)

    resp = api.get_spot_order(order["id"], plant["mco_headers"])
    read = validate_success(resp)
    assert read["status"] == "OPEN", "the freshly created order reads OPEN"


def test_master_control_may_not_ingest_a_playlist(api):
    """Playlist authoring belongs to traffic, not to master control.

    PRD §4: "| POST | `/playlists` | Ingest a broadcast-day playlist with its elements from the traffic system. | TrafficCoordinator, StationAdmin |"

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    plant = fx.setup_base_plant()

    resp = api.ingest_playlist(
        _single_program_day(plant["ch2"]["id"], "2026-08-05",
                            "2026-08-05T12:00:00Z"),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_master_control_may_not_waive_qc_even_naming_a_legitimate_director(api):
    """The role list is checked before any body reference is resolved.

    PRD §4: "| POST | `/assets/{id}/qc-waivers` | Waive a quality-control failure so the asset may air anyway. | ProgramDirector, StationAdmin |"

    Design: Corner/rbac/master_control_owns_the_air_chain_but_is_the_only_content_role_denied_the_money_view
    """
    plant = fx.bootstrap_operators()
    asset = _waivable_failed_asset(plant)

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["pd"]["id"],
            waiver_justification="Operational necessity for the top of hour.",
        ),
        plant["mco_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_FAILED", "the refused waiver must not move the asset"


# ===========================================================================
# TrafficCoordinator — the commercial plane, plus the clock everyone shares
# ===========================================================================

def test_traffic_coordinator_creates_a_spot_order(api):
    """Selling inventory is the traffic desk's own write.

    PRD §4: "| POST | `/spot-orders` | Create a commercial order for a channel with its spot count, unit length and rate. | TrafficCoordinator, StationAdmin |"

    PRD §3.9: "An order is created in `status` `OPEN` with every counter at 0 except `unplaced_spots`, which starts equal to `ordered_spots`."

    Design: Corner/rbac/traffic_owns_ingest_and_orders_and_can_still_trigger_an_air_cascade_through_the_clock
    """
    plant = fx.setup_base_plant()

    resp = api.create_spot_order(
        factories.create_spot_order_payload(
            plant["ch1"]["id"], advertiser_name="Riverbend Dental",
            order_reference="ORD-2026-0002", ordered_spots=2,
            unit_duration_seconds=30, rate_cents_total=60000, daypart="PRIME",
            priority_class="PREEMPTIBLE",
            makegood_deadline_utc="2026-08-02T23:00:00Z",
        ),
        TRAFFIC,
    )
    order = validate_success(resp, 201)
    assert order["status"] == "OPEN", "a new order opens"
    assert order["unplaced_spots"] == 2, \
        "every ordered spot starts unplaced"


def test_a_traffic_coordinator_may_not_change_a_channel_air_state(api):
    """Traffic never touches the air chain.

    PRD §4: "| POST | `/channels/{id}/air-state` | Take the channel to air, to bars-and-tone, or dark. | MasterControlOperator, StationAdmin |"

    Design: Corner/rbac/traffic_owns_ingest_and_orders_and_can_still_trigger_an_air_cascade_through_the_clock
    """
    plant = fx.setup_base_plant()

    resp = api.change_channel_air_state(
        plant["ch1"]["id"],
        factories.air_state_payload("DARK", reason="TRAFFIC_ATTEMPT"),
        TRAFFIC,
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_traffic_coordinator_may_not_even_list_technical_faults(api):
    """The faults that preempt traffic's spots are outside its read surface.

    PRD §4: "| GET | `/technical-faults` | List faults, optionally filtered by channel, transmitter, element, state or severity. | MasterControlOperator, QCTechnician, BroadcastEngineer, ComplianceOfficer, StationAdmin |"

    Design: Corner/rbac/traffic_owns_ingest_and_orders_and_can_still_trigger_an_air_cascade_through_the_clock
    """
    plant = fx.setup_base_plant()

    resp = api.list_faults(TRAFFIC, params={"channel_id": plant["ch1"]["id"]})
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_traffic_coordinator_clock_advance_expires_an_undelivered_asset(api):
    """The clock is open to every role, and its sweeps run regardless of caller.

    PRD §4: "| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the five-step ops-run checkpoint. | MasterControlOperator, QCTechnician, ProgramDirector, BroadcastEngineer, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    PRD §3.4: "When the logical clock advances past `delivery_deadline_utc` plus 3600 seconds and the asset is still `EXPECTED`, it moves to `EXPIRED`, which is terminal"

    Design: Corner/rbac/traffic_owns_ingest_and_orders_and_can_still_trigger_an_air_cascade_through_the_clock
    """
    plant = fx.bootstrap_operators()
    asset = fx.create_asset(
        plant, house_number="HN-NEVER-01", title="Never Arrives",
        source="SATELLITE_FEED", expected_duration_seconds=60,
        delivery_deadline_utc="2026-08-01T12:00:00Z",
        required_resolution_class="HD_1080I", captions_required=False,
    )
    assert asset["status"] == "EXPECTED", "the asset must start merely expected"

    validate_success(api.set_clock("2026-08-01T13:00:01Z", TRAFFIC))

    after = validate_success(api.get_asset(asset["id"], TRAFFIC))
    assert after["status"] == "EXPIRED", \
        "the traffic-triggered checkpoint must expire the undelivered asset"


# ===========================================================================
# QCTechnician — the narrowest surface, and never its own forgiveness
# ===========================================================================

def test_a_qc_technician_authors_the_failing_verdict(api):
    """The inspection that blocks the station's content is QC's own write.

    PRD §4: "| POST | `/assets/{id}/qc-reports` | Submit a quality-control inspection on an ingest or air-check basis. | QCTechnician, StationAdmin |"

    PRD §3.4: "The verdict is `FAIL` if the score is below 70, **or** if any of the report's distinct defect codes is `AUDIO_LOSS` or `FORMAT_MISMATCH`"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    plant = fx.bootstrap_operators()
    delivered = _received_asset(plant, 60)

    resp = api.submit_qc_report(
        delivered["id"],
        factories.qc_report_payload(
            delivered["version"], plant["qc"]["id"], basis="INGEST",
            defect_codes=["VIDEO_ARTIFACT", "FORMAT_MISMATCH"],
            measured_duration_seconds=58,
        ),
        plant["qc_headers"],
    )
    report = validate_success(resp, 201)
    assert report["verdict"] == "FAIL", \
        "a FORMAT_MISMATCH defect is non-negotiable"


def test_a_qc_technician_may_not_waive_the_failure_it_graded(api):
    """Waiving is a ProgramDirector duty, so QC is refused on the role list.

    PRD §4: "| POST | `/assets/{id}/qc-waivers` | Waive a quality-control failure so the asset may air anyway. | ProgramDirector, StationAdmin |"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    plant = fx.bootstrap_operators()
    asset = _waivable_failed_asset(plant)

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["qc"]["id"],
            waiver_justification="I graded it and I forgive it entirely.",
        ),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_FAILED", "the refused waiver must not move the asset"


def test_a_qc_technician_may_not_change_a_channel_air_state(api):
    """QC holds no air authority at all.

    PRD §4: "| POST | `/channels/{id}/air-state` | Take the channel to air, to bars-and-tone, or dark. | MasterControlOperator, StationAdmin |"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    plant = fx.setup_base_plant()

    resp = api.change_channel_air_state(
        plant["ch2"]["id"],
        factories.air_state_payload("BARS_AND_TONE", reason="QC_ATTEMPT"),
        plant["qc_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_qc_technician_may_not_drive_the_playlist_lifecycle(api):
    """Validating a day is not on QC's surface either.

    PRD §4: "| POST | `/playlists/{id}/state` | Drive the playlist lifecycle: validate, arm, take to air, close or abandon. | MasterControlOperator, ProgramDirector, StationAdmin |"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    scn = fx.setup_playlist_scenario()

    resp = api.change_playlist_state(
        scn["playlist"]["id"],
        factories.playlist_state_payload("VALIDATED"),
        scn["qc_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_a_qc_technician_may_observe_the_elements_its_verdict_blocked(api):
    """The element list is one of the reads QC is listed on.

    PRD §4: "| GET | `/playlists/{id}/items` | List the playlist's elements in sequence order with playout and clearance status. | MasterControlOperator, QCTechnician, ProgramDirector, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    PRD §3.4: "every playlist item referencing the asset whose `playout_status` is `SCHEDULED` or `CUED` has its `clearance_status` flipped to `BLOCKED`"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    scn = fx.setup_playlist_scenario()
    fx.retract(scn, scn["assets"]["short"]["id"])

    blocked, _meta = validate_paginated(
        api.list_playlist_items(scn["playlist"]["id"], scn["qc_headers"],
                                params={"clearance_status": "BLOCKED"})
    )
    assert blocked, "the retraction must leave at least one blocked element"
    assert all(item["clearance_status"] == "BLOCKED" for item in blocked), \
        "the filter must return only blocked elements"


def test_the_programme_director_waiver_succeeds_where_the_technician_was_refused(api):
    """The forgiveness QC cannot grant is granted by the director.

    PRD §3.4: "A granted waiver writes `waived_by_operator_id` and `waiver_justification`, moves the asset to `QC_WAIVED`"

    Design: Corner/rbac/qc_technician_has_the_narrowest_surface_and_can_never_forgive_its_own_verdict
    """
    plant = fx.bootstrap_operators()
    asset = _waivable_failed_asset(plant)

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["pd"]["id"],
            waiver_justification="Cleared for air by program management.",
        ),
        plant["pd_headers"],
    )
    waived = validate_success(resp)
    assert waived["status"] == "QC_WAIVED", "the director's waiver must land"


# ===========================================================================
# ProgramDirector — the forgiveness powers, and a two-field waiver body
# ===========================================================================

def test_the_waiver_body_is_exactly_two_fields_and_is_accepted(api):
    """No version token is declared on the waiver, and none may be demanded.

    PRD §3.4: "The waiver supplies `waived_by_operator_id` and a `waiver_justification`, and is legal only from `QC_FAILED`"

    PRD §2.6: "No other endpoint accepts a version field, and none should be invented for them."

    Design: Corner/rbac/program_director_holds_the_forgiveness_powers_and_the_waiver_endpoint_declares_an_impossible_occ
    """
    plant = fx.bootstrap_operators()
    asset = _waivable_failed_asset(plant)

    payload = factories.qc_waiver_payload(
        plant["pd"]["id"],
        waiver_justification="Approved for air by program management.",
    )
    assert set(payload) == {"waived_by_operator_id", "waiver_justification"}, \
        "the request carries only the two declared inputs"

    waived = validate_success(api.sign_qc_waiver(asset["id"], payload,
                                                plant["pd_headers"]))
    assert waived["status"] == "QC_WAIVED", \
        "the two-field body must be accepted as declared"
    assert waived["waived_by_operator_id"] == plant["pd"]["id"], \
        "the waiver records its signer"


def test_a_programme_director_may_retract_an_asset(api):
    """Retraction is one of the director's escape hatches.

    PRD §4: "| POST | `/assets/{id}/retract` | Withdraw an asset from all use, blocking every unaired element that references it. | ProgramDirector, TrafficCoordinator, StationAdmin |"

    PRD §3.4: "Retraction is legal from any status except `EXPIRED` and `RETRACTED`"

    Design: Corner/rbac/program_director_holds_the_forgiveness_powers_and_the_waiver_endpoint_declares_an_impossible_occ
    """
    plant = fx.bootstrap_operators()
    asset = fx.setup_qc_passed_asset(plant, 60)

    resp = api.retract_asset(asset["id"],
                             factories.retract_payload(reason="Rights pull"),
                             plant["pd_headers"])
    retracted = validate_success(resp)
    assert retracted["status"] == "RETRACTED", "the director's retraction must land"


def test_a_programme_director_may_not_change_transmitter_power(api):
    """The director holds no engineering authority.

    PRD §4: "| POST | `/transmitters/{id}/power-state` | Change transmitter power state, republishing the derate factor and running the RF cascade. | BroadcastEngineer, StationAdmin |"

    Design: Corner/rbac/program_director_holds_the_forgiveness_powers_and_the_waiver_endpoint_declares_an_impossible_occ
    """
    plant = fx.setup_base_plant()

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        factories.power_state_payload("REDUCED_POWER", power_pct=50,
                                      reason="PD_ATTEMPT"),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")

    after = fx.read_transmitter(plant["transmitter"]["id"])
    assert after["operational_state"] == "FULL_POWER", \
        "the refused power write must not derate the plant"


# ===========================================================================
# ComplianceOfficer — a read-only auditor with exactly one write
# ===========================================================================

def test_the_compliance_officer_reads_the_filing_obligation(api):
    """The notification catalogue is part of the auditor's read surface.

    PRD §4: "| GET | `/transmitters/{id}/notifications` | List the regulatory notifications raised for this transmitter. | BroadcastEngineer, ComplianceOfficer, StationAdmin |"

    PRD §3.1: "a reduction to below 80 percent of licensed power creates a `POWER_REDUCTION` notification in status `PENDING`"

    Design: Corner/rbac/compliance_officer_is_read_only_across_28_endpoints_with_exactly_one_write_that_stops_a_clock_sweep
    """
    plant = fx.setup_base_plant()
    _pending_power_reduction(plant)

    listed, _meta = validate_paginated(
        api.list_transmitter_notifications(plant["transmitter"]["id"], COMPLIANCE,
                                           params={"kind": "POWER_REDUCTION"})
    )
    assert listed, "the auditor must see the obligation it has to file"
    assert listed[0]["status"] == "PENDING", "the fresh obligation is still pending"


def test_the_compliance_officer_files_the_notification_on_time(api):
    """Filing is the one write the auditor owns.

    PRD §3.1: "A notification whose `status` is `PENDING` becomes `FILED` when the logical clock is at or before `due_utc` — the boundary instant counts as on time"

    Design: Corner/rbac/compliance_officer_is_read_only_across_28_endpoints_with_exactly_one_write_that_stops_a_clock_sweep
    """
    plant = fx.setup_base_plant()
    notification = _pending_power_reduction(plant)

    resp = api.file_notification(
        notification["id"],
        {
            "filed_reference": "FCC-EFR-2026-08-02-0001",
            "narrative": "Power reduced on the primary program channel; "
                         "backup path engaged within the reporting window.",
        },
        COMPLIANCE,
    )
    filed = validate_success(resp)
    assert filed["status"] == "FILED", "an on-time filing lands as FILED"


def test_the_compliance_officer_may_not_advance_a_technical_fault(api):
    """A perfectly legal fault transition still dies on the role list.

    PRD §4: "| POST | `/technical-faults/{id}/state` | Advance a fault: acknowledge, escalate, mitigate, resolve or reopen a recurrence. | MasterControlOperator, BroadcastEngineer, StationAdmin |"

    Design: Corner/rbac/compliance_officer_is_read_only_across_28_endpoints_with_exactly_one_write_that_stops_a_clock_sweep
    """
    plant = fx.setup_base_plant()
    fault = fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR",
                                    "2026-08-01T09:00:00Z")

    resp = api.change_fault_state(fault["id"], {"target_state": "ACKNOWLEDGED"},
                                 COMPLIANCE)
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")

    after = fx.read_fault(fault["id"])
    assert after["state"] == "DETECTED", "the refused transition must not land"


def test_the_compliance_officer_may_not_waive_a_qc_failure(api):
    """The auditor can change nothing about content.

    PRD §4: "| POST | `/assets/{id}/qc-waivers` | Waive a quality-control failure so the asset may air anyway. | ProgramDirector, StationAdmin |"

    Design: Corner/rbac/compliance_officer_is_read_only_across_28_endpoints_with_exactly_one_write_that_stops_a_clock_sweep
    """
    plant = fx.bootstrap_operators()
    asset = _waivable_failed_asset(plant)

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["pd"]["id"],
            waiver_justification="Compliance approves this promotional element.",
        ),
        COMPLIANCE,
    )
    validate_error(resp, "ERR_ROLE_NOT_PERMITTED")


def test_the_compliance_officer_may_set_the_logical_clock(api):
    """The checkpoint endpoint lists all seven roles, the auditor included.

    PRD §4: "| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the five-step ops-run checkpoint. | MasterControlOperator, QCTechnician, ProgramDirector, BroadcastEngineer, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    PRD §2.4: "a request whose `current_utc` equals or precedes the present clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`"

    Design: Corner/rbac/compliance_officer_is_read_only_across_28_endpoints_with_exactly_one_write_that_stops_a_clock_sweep
    """
    fx.bootstrap_operators()

    validate_success(api.set_clock("2026-08-02T12:29:00Z", COMPLIANCE))

    replay = api.set_clock("2026-08-02T12:29:00Z", COMPLIANCE)
    validate_error(replay, "ERR_CLOCK_NOT_MONOTONIC")


# ===========================================================================
# Header-only identities — three roles no Operator row can represent
# ===========================================================================

def test_no_operator_row_can_carry_the_traffic_role_class(api):
    """The role_class enum has exactly four members for seven roles.

    PRD §2.9: "Operator `role_class`: `MASTER_CONTROL`, `QC`, `PROGRAM_DIRECTOR`, `ENGINEER`."

    PRD §2.9: "Every enum-typed field must carry one of the exact literals below, matched case-sensitively; anything else yields `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

    Design: Corner/rbac/three_roles_are_header_only_identities_so_the_operator_lifecycle_rules_are_structurally_inapplicable_to_them
    """
    resp = api.create_operator(
        factories.create_operator_payload(
            "TRAFFIC", full_name="Traffic Desk Two", override_authority="NONE",
            certification_expires_utc="2027-01-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(resp, "ERR_INVALID_ENUM_VALUE")


def test_suspension_locks_the_entity_backed_operator_out_of_its_own_endpoint(api):
    """Suspension is refused before any air-safety or state check.

    PRD §2.1: "A suspended operator — one whose `status` is `SUSPENDED` rather than `ACTIVE` — is refused every mutating request with `ERR_OPERATOR_SUSPENDED`"

    Design: Corner/rbac/three_roles_are_header_only_identities_so_the_operator_lifecycle_rules_are_structurally_inapplicable_to_them
    """
    scn = fx.setup_on_air_playlist()
    suspended = fx.suspend_operator(scn["mco"]["id"])
    assert suspended["status"] == "SUSPENDED", "setup must suspend the operator"

    resp = api.post_playout_event(
        scn["items"][0]["id"],
        factories.playout_event_payload("CUE", "2026-08-01T11:59:00Z",
                                        source="AUTOMATION"),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_OPERATOR_SUSPENDED")


def test_the_same_suspended_identifier_under_an_opaque_role_is_unaffected(api):
    """An opaque role's identifier is never compared to any Operator row.

    PRD §2.1: "When `X-User-Role` is `TrafficCoordinator`, `ComplianceOfficer` or `StationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it ... but never compares it to any entity's `id`. Opaque roles skip operator resolution and role-class matching entirely."

    Design: Corner/rbac/three_roles_are_header_only_identities_so_the_operator_lifecycle_rules_are_structurally_inapplicable_to_them
    """
    plant = fx.setup_base_plant()
    suspended = fx.suspend_operator(plant["mco"]["id"])
    assert suspended["status"] == "SUSPENDED", "setup must suspend the operator"

    resp = api.ingest_playlist(
        _single_program_day(plant["ch2"]["id"], "2026-08-03",
                            "2026-08-03T12:00:00Z"),
        make_traffic_headers(plant["mco"]["id"]),
    )
    playlist = validate_success(resp, 201)
    assert playlist["channel_id"] == plant["ch2"]["id"], \
        "the ingest must land for the header-only role"


def test_station_admin_still_writes_air_state_while_master_control_is_suspended(api):
    """The opaque admin identity is the escalation path when the shift is locked out.

    PRD §2.1: "`StationAdmin` may perform every mutating operation in the domain, but because it acts with an opaque identifier it can never satisfy one half of a two-person rule"

    Design: Corner/rbac/three_roles_are_header_only_identities_so_the_operator_lifecycle_rules_are_structurally_inapplicable_to_them
    """
    plant = fx.setup_base_plant()
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.suspend_operator(plant["mco"]["id"])

    resp = api.change_channel_air_state(
        plant["ch1"]["id"],
        factories.air_state_payload(
            "BARS_AND_TONE", reason="Admin intervention during investigation."),
        ADMIN,
    )
    channel = validate_success(resp)
    assert channel["air_status"] == "BARS_AND_TONE", \
        "the admin write must land with no Operator row of its own"
