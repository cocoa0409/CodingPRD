"""Bed and maintenance-window state machine claims."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_maintenance_window_payload,
    create_unit_payload,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_bed_discharge_requires_occupied_state(api):
    """PRD §3.3: "When a `BedPlacementCoordinator` discharges a bed, the bed
    must currently be `OCCUPIED` — otherwise the call is rejected with
    `ERR_BED_NOT_OCCUPIED`."

    Design: Corner/state_machines/bed_discharge_requires_occupied_state
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    # ROUTINE standard must exist: §2.10 resolves the discharge's clean_type
    # standard (404 family) before state rules run, so the state gate can only
    # surface once the standard row is present.
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    assert bed["bed_status"] == "VACANT_DIRTY"

    r = api.discharge_bed(bed["id"], {}, COORDINATOR)
    validate_error(r, ApiErrorId.ERR_BED_NOT_OCCUPIED)

    fetched = validate_success(api.get_bed(bed["id"], ANY))
    assert fetched["bed_status"] == "VACANT_DIRTY"

    reqs, meta = validate_paginated(
        api.list_clean_requests(ANY, params={"bed_id": bed["id"]})
    )
    assert reqs == [], "a rejected discharge must not auto-create a clean request"


def test_bed_admit_and_mark_soiled_require_ready_state(api):
    """PRD §3.7: "Admitting requires the bed to be `READY` (`ERR_BED_NOT_READY`
    otherwise)."
    PRD §3.7: "Marking soiled likewise requires `READY` (`ERR_BED_NOT_READY`)
    and moves the bed `READY → VACANT_DIRTY`."

    Design: Corner/state_machines/bed_admit_and_mark_soiled_require_ready_state
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    # ROUTINE standard must exist so mark-soiled's auto-create (§3.7) does not
    # fail on ERR_STANDARD_NOT_FOUND before the READY state gate is reached.
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )

    r_admit = api.admit_bed(bed["id"], COORDINATOR)
    validate_error(r_admit, ApiErrorId.ERR_BED_NOT_READY)

    r_soil = api.mark_soiled_bed(bed["id"], COORDINATOR)
    validate_error(r_soil, ApiErrorId.ERR_BED_NOT_READY)

    fetched = validate_success(api.get_bed(bed["id"], ANY))
    assert fetched["bed_status"] == "VACANT_DIRTY"

    notifs, _ = validate_paginated(
        api.list_bed_ready_notifications(ANY, params={"bed_id": bed["id"]})
    )
    assert notifs == []
    reqs, _ = validate_paginated(
        api.list_clean_requests(ANY, params={"bed_id": bed["id"]})
    )
    assert reqs == []


def test_bed_out_of_service_blocks_admit_and_discharge(api):
    """PRD §3.9: "**Activating** a window takes the bed out of service. Beyond
    state, activation requires the bed to be `VACANT_DIRTY` or `READY`
    (`ERR_BED_NOT_AVAILABLE_FOR_MAINTENANCE` otherwise) ... The bed moves to
    `OUT_OF_SERVICE`."
    PRD §3.7: "Admitting requires the bed to be `READY` (`ERR_BED_NOT_READY`
    otherwise)."
    PRD §3.3: "the bed must currently be `OCCUPIED` — otherwise the call is
    rejected with `ERR_BED_NOT_OCCUPIED`."

    Design: Corner/state_machines/bed_out_of_service_blocks_admit_and_discharge
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    # ROUTINE standard must exist so the discharge attempt resolves its
    # clean_type standard before the OCCUPIED state gate is evaluated.
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    window = get_success_data(
        api.create_maintenance_window(
            create_maintenance_window_payload(bed_id=bed["id"]), ADMIN
        )
    )
    activated = validate_success(
        api.activate_maintenance_window(window["id"], ADMIN)
    )
    assert activated["status"] == "ACTIVE"

    bed_after = validate_success(api.get_bed(bed["id"], ANY))
    assert bed_after["bed_status"] == "OUT_OF_SERVICE"

    r_admit = api.admit_bed(bed["id"], COORDINATOR)
    validate_error(r_admit, ApiErrorId.ERR_BED_NOT_READY)

    r_dis = api.discharge_bed(bed["id"], {}, COORDINATOR)
    validate_error(r_dis, ApiErrorId.ERR_BED_NOT_OCCUPIED)

    window_after = validate_success(api.get_maintenance_window(window["id"], ANY))
    assert window_after["status"] == "ACTIVE"


def test_maintenance_window_state_transition_errors(api):
    """PRD §3.9: "Windows can be listed filtered by `bed_id` or `status`, and a
    scheduled window can be **cancelled**; activation, closure, and
    cancellation each require the matching state — `SCHEDULED` for activate
    and cancel, `ACTIVE` for close — with violations answered
    `ERR_WINDOW_INVALID_STATE`."

    Design: Corner/state_machines/maintenance_window_state_transition_errors
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    window = get_success_data(
        api.create_maintenance_window(
            create_maintenance_window_payload(bed_id=bed["id"]), ADMIN
        )
    )

    r_close = api.close_maintenance_window(window["id"], ADMIN)
    validate_error(r_close, ApiErrorId.ERR_WINDOW_INVALID_STATE)

    cancelled = validate_success(api.cancel_maintenance_window(window["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"

    r_activate = api.activate_maintenance_window(window["id"], ADMIN)
    validate_error(r_activate, ApiErrorId.ERR_WINDOW_INVALID_STATE)

    r_recancel = api.cancel_maintenance_window(window["id"], ADMIN)
    validate_error(r_recancel, ApiErrorId.ERR_WINDOW_INVALID_STATE)

    bed_after = validate_success(api.get_bed(bed["id"], ANY))
    assert bed_after["bed_status"] == "VACANT_DIRTY"


def test_maintenance_close_returns_bed_dirty_with_routine_request(api):
    """PRD §3.9: "**Closing** an active window returns the bed
    `OUT_OF_SERVICE → VACANT_DIRTY` and auto-creates a `ROUTINE` clean request
    for it, since maintenance dirties the room."

    Design: Corner/state_machines/maintenance_close_returns_bed_dirty_with_routine_request
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    window = get_success_data(
        api.create_maintenance_window(
            create_maintenance_window_payload(bed_id=bed["id"]), ADMIN
        )
    )
    validate_success(api.activate_maintenance_window(window["id"], ADMIN))

    closed = validate_success(api.close_maintenance_window(window["id"], ADMIN))
    assert closed["status"] == "CLOSED"

    bed_after = validate_success(api.get_bed(bed["id"], ANY))
    assert bed_after["bed_status"] == "VACANT_DIRTY"

    reqs, _ = validate_paginated(
        api.list_clean_requests(
            ANY, params={"bed_id": bed["id"], "status": "QUEUED"}
        )
    )
    assert len(reqs) == 1
    auto = reqs[0]
    assert auto["clean_type"] == "ROUTINE"
    assert auto["sla_target_minutes"] == 45
