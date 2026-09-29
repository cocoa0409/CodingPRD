"""The tool's two axes, the toolroom order and the resin lot's disposition."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_maintenance_order,
    assert_resin_lot,
    close_maintenance_order,
    create_customer,
    create_job,
    create_mold,
    create_press,
    create_production_job_payload,
    create_press_qualification_payload,
    create_quote,
    create_resin_lot,
    create_resin_lot_payload,
    disposition_lot,
    mold_version,
    open_maintenance_order,
    open_qualification,
    qualify_pair,
    read_maintenance_order,
    read_mold,
    read_qualification,
    set_clock,
    setup_approved_tool,
    setup_qualified_shop,
    setup_scheduled_job,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]
TT = TEST_USERS["toolroom_tech_headers"]


def test_fresh_rows_land_on_their_declared_initial_states(api):
    """PRD §3.1: "A new tool starts with `status` `NEW`, `service_state`
    `SERVICEABLE`, `total_shot_count` and `shots_since_pm` both at 0, and
    `approved_max_regrind_bp`, `interim_expiry_shots` and `active_transfer_id` all
    unset."
    PRD §3.2: "The proof is a **qualification row**, a junction record opened by a
    `ProcessEngineer` or a `PlantAdmin` that names a `mold_id` and a `press_id` and
    begins life with `status` `UNQUALIFIED` and `attempt_count` at 0."
    PRD §3.3: "A new quote's `status` is `DRAFT` and no price exists yet."
    PRD §3.5: "A received lot begins in `QUARANTINE`, and its running balance
    `qty_grams_remaining` is initialised to the received kilograms multiplied by the
    1,000 grams in a kilogram."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    set_clock()
    customer = create_customer()
    press = create_press()

    mold = create_mold(customer["id"])
    qualification = validate_success(
        api.create_press_qualification(
            create_press_qualification_payload(mold["id"], press["id"]), PE
        ),
        201,
    )
    quote = create_quote(customer["id"], mold["id"])
    lot = create_resin_lot(supplier_lot_code="L-01", qty_kg_received=25, moisture_bp=100)

    assert mold["status"] == "NEW"
    assert mold["service_state"] == "SERVICEABLE"
    assert qualification["status"] == "UNQUALIFIED"
    assert qualification["attempt_count"] == 0
    assert quote["status"] == "DRAFT"
    assert lot["status"] == "QUARANTINE"
    assert lot["qty_grams_remaining"] == 25000


def test_release_moves_a_quarantined_lot_to_released_without_touching_its_balance(api):
    """PRD §3.5: "A `RELEASE` decision is accepted out of `QUARANTINE` and out of
    `HOLD`, and in both cases requires that the lot's `moisture_bp` is no greater
    than 200 basis points — two percent of mass — with a lot sitting exactly at 200
    basis points passing."
    PRD §3.5: "A received lot begins in `QUARANTINE`, and its running balance
    `qty_grams_remaining` is initialised to the received kilograms multiplied by the
    1,000 grams in a kilogram."

    Design: Corner/state_machines/resin_lot_release_moves_quarantine_to_released
    """
    set_clock()
    lot = create_resin_lot(supplier_lot_code="L-01", qty_kg_received=25, moisture_bp=120)

    data = validate_success(api.resin_lot_disposition(lot["id"], {"decision": "RELEASE"}, QE))

    assert_resin_lot(data)
    assert data["status"] == "RELEASED"
    assert data["qty_grams_remaining"] == 25000


def test_release_is_refused_above_the_moisture_limit_and_allowed_exactly_on_it(api):
    """PRD §3.5: "A `RELEASE` decision is accepted out of `QUARANTINE` and out of
    `HOLD`, and in both cases requires that the lot's `moisture_bp` is no greater
    than 200 basis points — two percent of mass — with a lot sitting exactly at 200
    basis points passing. A wetter lot is rejected with
    `ERR_RESIN_MOISTURE_TOO_HIGH`."

    Design: Corner/state_machines/resin_lot_release_above_moisture_limit_is_rejected
    """
    set_clock()
    wet = create_resin_lot(supplier_lot_code="L-WET", moisture_bp=201)
    edge = create_resin_lot(supplier_lot_code="L-EDGE", moisture_bp=200)

    wet_response = api.resin_lot_disposition(wet["id"], {"decision": "RELEASE"}, QE)
    assert wet_response.status_code == 422, f"Expected 422, got {wet_response.status_code}"
    validate_error(wet_response, ApiErrorId.ERR_RESIN_MOISTURE_TOO_HIGH.value)
    assert validate_success(api.get_resin_lot(wet["id"], QE))["status"] == "QUARANTINE"

    edge_data = validate_success(
        api.resin_lot_disposition(edge["id"], {"decision": "RELEASE"}, QE)
    )
    assert edge_data["status"] == "RELEASED", "a lot sitting exactly at 200 bp passes"


def test_retiring_a_never_sampled_tool_still_revokes_its_qualified_rows(api):
    """PRD §3.1: "Retirement drives the lifecycle axis to `RETIRED` and, in both
    cases equally, revokes every qualification row on that tool whose status is
    `QUALIFIED` — a tool scrapped before it ever sampled carries its qualifications
    down with it exactly as an approved one does — and each such revocation then
    fires its own job-cancellation cascade as described in §3.2."

    Design: Corner/state_machines/mold_retire_cascades_revocation_to_its_qualifications
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold_one = create_mold(customer["id"], mold_code="M-1")
    mold_two = create_mold(customer["id"], mold_code="M-2")
    qualification_one = qualify_pair(mold_one["id"], press["id"])
    qualification_two = qualify_pair(mold_two["id"], press["id"])
    assert qualification_one["status"] == "QUALIFIED"
    assert qualification_two["status"] == "QUALIFIED"

    retired = validate_success(
        api.retire_mold(mold_one["id"], {"reason": "cavity block cracked beyond repair"}, PA)
    )

    assert retired["status"] == "RETIRED"
    assert read_qualification(qualification_one["id"])["status"] == "REVOKED"
    assert read_qualification(qualification_two["id"])["status"] == "QUALIFIED", (
        "a qualification on a different tool is left alone"
    )
    _, meta = validate_paginated(
        api.list_press_qualifications(PE, params={"mold_id": mold_one["id"]})
    )
    assert meta["total_count"] == 1


def test_closing_a_toolroom_order_with_a_reset_zeroes_only_the_pm_counter(api):
    """PRD §3.8: "When `reset_shot_counter` is true, the tool moves `IN_MAINTENANCE
    → SERVICEABLE`, its `shots_since_pm` is set to 0, and the order's `shots_reset`
    is set to true — this is the one and only mechanism in the system that zeroes
    the PM counter, and note that `total_shot_count` is deliberately *not* reset,
    since a tool's lifetime shot history survives every maintenance event."
    PRD §3.8: "The order moves `OPEN → CLOSED` and the tool's `version` is
    incremented by 1 either way, but the two branches are not symmetric."

    Design: Corner/state_machines/maintenance_close_with_reset_zeroes_pm_counter_but_not_lifetime_shots
    """
    shop = setup_qualified_shop()
    order = open_maintenance_order(shop["mold"]["id"], kind="PM")
    version_before = mold_version(shop["mold"]["id"])

    data = validate_success(
        api.close_maintenance_order(
            order["id"],
            {"reset_shot_counter": True, "expected_mold_version": version_before},
            TT,
        )
    )

    assert_maintenance_order(data)
    assert data["status"] == "CLOSED"
    assert data["shots_reset"] is True
    mold = read_mold(shop["mold"]["id"])
    assert mold["service_state"] == "SERVICEABLE"
    assert mold["shots_since_pm"] == 0
    assert mold["total_shot_count"] == 0
    assert mold["version"] == version_before + 1


def test_closing_without_a_reset_below_the_pm_interval_is_refused(api):
    """PRD §3.8: "When `reset_shot_counter` is false, the tool moves
    `IN_MAINTENANCE → PM_DUE`, `shots_since_pm` is left exactly as it was and
    `shots_reset` stays false; that branch is declared only when `shots_since_pm` is
    at or above `pm_interval_shots`, and a close-without-reset on a tool that is not
    yet due is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/maintenance_close_without_reset_below_pm_interval_returns_invalid_state
    """
    shop = setup_qualified_shop()
    order = open_maintenance_order(shop["mold"]["id"], kind="REPAIR")
    version_before = mold_version(shop["mold"]["id"])

    response = api.close_maintenance_order(
        order["id"],
        {"reset_shot_counter": False, "expected_mold_version": version_before},
        TT,
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    order_now = read_maintenance_order(order["id"])
    assert order_now["status"] == "OPEN"
    assert order_now["shots_reset"] is False
    mold = read_mold(shop["mold"]["id"])
    assert mold["service_state"] == "IN_MAINTENANCE"
    assert mold["version"] == version_before


def test_a_second_open_toolroom_order_on_the_same_tool_is_refused(api):
    """PRD §3.8: "At most one order per tool may be `OPEN` at a time; a second is
    rejected with `ERR_MAINTENANCE_ALREADY_OPEN`."

    Design: Corner/errors/second_open_maintenance_order_on_the_same_mold_is_rejected
    """
    shop = setup_qualified_shop()
    first = open_maintenance_order(
        shop["mold"]["id"],
        kind="PM",
        window_start="2026-09-20T08:00:00Z",
        window_end="2026-09-20T12:00:00Z",
    )

    response = api.create_maintenance_order(
        {
            "mold_id": shop["mold"]["id"],
            "kind": "REPAIR",
            "window_start": "2026-09-21T08:00:00Z",
            "window_end": "2026-09-21T12:00:00Z",
        },
        TT,
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MAINTENANCE_ALREADY_OPEN.value)
    _, meta = validate_paginated(
        api.list_maintenance_orders(TT, params={"mold_id": shop["mold"]["id"]})
    )
    assert meta["total_count"] == 1
    assert read_maintenance_order(first["id"])["status"] == "OPEN"
    assert read_mold(shop["mold"]["id"])["service_state"] == "IN_MAINTENANCE"


def test_a_tool_in_the_toolroom_takes_no_new_work_until_the_order_closes(api):
    """PRD §3.6: "The tool's lifecycle status must be `PPAP_APPROVED` or
    `INTERIM_APPROVED`, otherwise `ERR_MOLD_NOT_PPAP_APPROVED`; its `service_state`
    must be `SERVICEABLE`, otherwise `ERR_PM_OVERDUE`; and its `active_transfer_id`
    must be unset, otherwise `ERR_MOLD_TRANSFER_IN_PROGRESS` — a tool with a
    transfer in flight takes no new work."
    PRD §3.8: "Any job operation attempted on a tool whose `service_state` is
    `PM_DUE` or `IN_MAINTENANCE` is rejected with `ERR_PM_OVERDUE`."

    Design: Corner/errors/job_creation_while_tool_is_in_maintenance_returns_pm_overdue
    """
    shop = setup_approved_tool(with_lot=False)
    order = open_maintenance_order(
        shop["mold"]["id"],
        kind="PM",
        window_start="2026-09-25T08:00:00Z",
        window_end="2026-09-25T12:00:00Z",
    )

    payload = create_production_job_payload(
        shop["quote"]["id"], planned_qty=1000, press_id=shop["press"]["id"]
    )
    blocked = api.create_production_job(payload, PE)
    assert blocked.status_code == 409, f"Expected 409, got {blocked.status_code}"
    validate_error(blocked, ApiErrorId.ERR_PM_OVERDUE.value)
    assert read_mold(shop["mold"]["id"])["status"] == "PPAP_APPROVED", (
        "the lifecycle axis was never the problem; the service axis was"
    )

    close_maintenance_order(order["id"], shop["mold"]["id"], reset_shot_counter=True)
    assert read_mold(shop["mold"]["id"])["service_state"] == "SERVICEABLE"

    allowed = validate_success(api.create_production_job(payload, PE), 201)
    assert allowed["run_status"] == "DRAFT"


def test_a_toolroom_window_touching_a_scheduled_jobs_end_collides_on_the_tool(api):
    """PRD §2.9: "A tool is physically in exactly one place at a time, so two
    occupancies that merely touch at an endpoint do collide, and the buffer between
    mold occupancies is zero minutes."
    PRD §2.9: "A candidate window collides with an existing one when the candidate's
    start is at or before the existing window's end *and* the existing window's
    start is at or before the candidate's end."
    PRD §3.8: "The window is checked against the tool's other occupancies under the
    closed-interval, zero-buffer mold semantics of §2.9, which means a maintenance
    window that merely touches a scheduled job's window on the same tool is a
    conflict and is rejected with `ERR_MOLD_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/mold_closed_window_rejects_touching_endpoints
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T08:00:00Z",
            "scheduled_end": "2026-09-10T12:00:00Z",
        }
    )

    response = api.create_maintenance_order(
        {
            "mold_id": shop["mold"]["id"],
            "kind": "PM",
            "window_start": "2026-09-10T12:00:00Z",
            "window_end": "2026-09-10T14:00:00Z",
        },
        TT,
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MOLD_WINDOW_CONFLICT.value)
    assert read_mold(shop["mold"]["id"])["service_state"] == "SERVICEABLE"


def test_a_toolroom_window_one_minute_clear_of_the_job_opens_the_order(api):
    """PRD §2.9: "A candidate window collides with an existing one when the
    candidate's start is at or before the existing window's end *and* the existing
    window's start is at or before the candidate's end."
    PRD §3.8: "On success the order is created with `status` `OPEN`, `shots_reset`
    false, and `shots_at_open` snapshotting the tool's `shots_since_pm` at that
    instant; the tool's `service_state` moves to `IN_MAINTENANCE`, and it may do so
    from either `SERVICEABLE` or `PM_DUE`."

    Design: Difficulty/resource_temporal_overlap/mold_closed_window_rejects_touching_endpoints
    """
    shop = setup_scheduled_job(
        job_overrides={
            "scheduled_start": "2026-09-10T08:00:00Z",
            "scheduled_end": "2026-09-10T12:00:00Z",
        }
    )

    data = validate_success(
        api.create_maintenance_order(
            {
                "mold_id": shop["mold"]["id"],
                "kind": "PM",
                "window_start": "2026-09-10T12:01:00Z",
                "window_end": "2026-09-10T14:00:00Z",
            },
            TT,
        ),
        201,
    )

    assert_maintenance_order(data)
    assert data["status"] == "OPEN"
    assert data["shots_at_open"] == 0
    assert read_mold(shop["mold"]["id"])["service_state"] == "IN_MAINTENANCE"
    job = validate_success(api.get_production_job(shop["job"]["id"], PE))
    assert job["run_status"] == "SCHEDULED"
    press = validate_success(api.get_press(shop["press"]["id"], PE))
    assert press["committed_minutes_scheduled"] == 240
