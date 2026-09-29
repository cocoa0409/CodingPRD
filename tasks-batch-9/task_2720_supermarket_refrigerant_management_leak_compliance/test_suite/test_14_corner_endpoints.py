"""
The endpoint corners: the sweep that touches five deadline families at once, the
read-only projection with its `as_of` override, the three envelope shapes, the
clock swap that reports both sides, and the closure that freezes an exposure.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_STORE_NOT_FOUND
from test_helpers.assertions import (
    assert_array_envelope,
    assert_error_envelope,
    assert_instant,
    assert_mass,
    assert_object_envelope,
    assert_penalty_exposure,
    assert_projection,
    assert_store_posture,
    assert_sweep_report,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REGULATOR_2_HEADERS,
    REGULATOR_2_USER_ID,
    REGULATOR_HEADERS,
    make_store_manager_headers,
)
from test_helpers.types import (
    EQUIPMENT_VERIFICATION_OVERDUE,
    EVENT_REPAIR_OVERDUE,
    EXTENSION_EXPIRED,
    INSPECTION_CLOSED,
    INSPECTION_ESCALATED,
    INSPECTION_RESPONDED,
    METHOD_ROLLING_AVERAGE,
    POSTURE_AT_RISK,
    POSTURE_NON_COMPLIANT,
    REGION_SOUTH,
    SERVICE_ADD_REFRIGERANT,
)


def test_one_compliance_run_sweeps_all_five_deadline_families(api):
    """
    §3.6 runs five independent lapse rules in one pass, and each populates its own
    array. A single run eleven months late moves the event, the request, the machine
    and the inspection, and re-prices the exposure into the NON_COMPLIANT band.

    Design: Corner/endpoints/compliance_run_sweeps_all_five_deadline_families_in_one_call
    """
    env = X.manual_event_env(api, with_second_technician=False, with_cylinder=False)
    request = X.file_extension_request(api, env["event_id"])
    inspection = X.open_inspection(
        api,
        env["store_id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    assert_penalty_exposure(
        inspection, penalty_exposure_usd=344.44, chronic_multiplier_applied=1.25
    )

    X.set_clock(api, "2027-07-01T00:00:00Z")
    report = X.run_sweep(api)

    assert_sweep_report(
        report,
        repair_overdue=[env["event_id"]],
        verification_overdue=[],
        expired_extensions=[request["id"]],
        overdue_equipment=[env["eq1_id"]],
        escalated_inspections=[inspection["id"]],
        stores_recomputed_count=1,
        as_of="2027-07-01T00:00:00Z",
    )

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_REPAIR_OVERDUE
    assert_instant(event["repair_deadline"], "2026-08-31T00:00:00Z", "repair_deadline")
    assert X.get_extension_request(api, request["id"])["status"] == EXTENSION_EXPIRED
    assert X.get_equipment(api, env["eq1_id"])["status"] == EQUIPMENT_VERIFICATION_OVERDUE

    escalated = X.get_inspection(api, inspection["id"])
    assert escalated["status"] == INSPECTION_ESCALATED
    assert_penalty_exposure(
        escalated, penalty_exposure_usd=413.33, chronic_multiplier_applied=1.50
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_NON_COMPLIANT,
        overdue_leak_event_count=1,
        penalty_exposure_total_usd=413.33,
    )


def test_the_leak_rate_projection_honours_an_as_of_override_and_persists_nothing(api):
    """
    §3.4's projection is a pure read that re-runs the rolling window at any instant:
    at the clock the 30.0 lb addition is inside the window, a year later it has aged
    out, and the stored leak rate never moves.

    Design: Corner/endpoints/leak_rate_projection_honours_the_as_of_override
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        system_overrides={"full_charge_lbs": 200.0, "initial_charge_lbs": 0.0},
        cylinder_overrides={
            "nominal_capacity_lbs": 100.0,
            "initial_contents_lbs": 80.0,
        },
    )
    X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        service_type=SERVICE_ADD_REFRIGERANT,
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=30.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=60,
    )
    version_before = X.system_version(api, env["system_id"])

    at_the_clock = validate_success(
        api.get_leak_rate_projection(
            env["system_id"], make_store_manager_headers(env["store_id"])
        )
    )
    assert_projection(
        at_the_clock,
        method=METHOD_ROLLING_AVERAGE,
        leak_rate_pct=15.0,
        refrigerant_added_lbs_in_window=30.0,
        window_start="2025-08-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        threshold_pct=20.0,
        would_trigger_leak_event=False,
    )

    a_year_on = validate_success(
        api.get_leak_rate_projection(
            env["system_id"],
            COMPLIANCE_MANAGER_HEADERS,
            {"as_of": "2027-08-02T00:00:00Z"},
        )
    )
    assert_projection(
        a_year_on,
        leak_rate_pct=0.0,
        refrigerant_added_lbs_in_window=0.0,
        window_start="2026-08-02T00:00:00Z",
        window_end="2027-08-02T00:00:00Z",
        would_trigger_leak_event=False,
    )

    system = X.get_system(api, env["system_id"])
    assert_mass(system["leak_rate_pct"], 15.0, "leak_rate_pct")
    assert system["version"] == version_before
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0


def test_the_envelope_shape_differs_for_an_object_a_list_and_an_error(api):
    """
    §2.2 gives one collection three envelope shapes: an object read with no
    pagination keys, an array read carrying `total_count` and `has_more`, and an
    error body carrying an identifier and a message instead of an entity.

    Design: Corner/endpoints/response_envelope_shape_differs_for_object_array_and_error
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store_a = X.create_store(api)
    store_b = X.create_second_store(api, state_code="TX", region=REGION_SOUTH)

    object_body = assert_object_envelope(api.get_store(store_a["id"], REGULATOR_HEADERS))
    assert object_body["data"]["store_code"] == "NG-001"
    assert "total_count" not in object_body["meta"]
    assert "has_more" not in object_body["meta"]

    list_body = assert_array_envelope(
        api.list_stores(REGULATOR_HEADERS, {"region": REGION_SOUTH})
    )
    assert list_body["meta"]["total_count"] == 1
    assert list_body["meta"]["has_more"] is False
    assert [row["id"] for row in list_body["data"]] == [store_b["id"]]

    missing = api.get_store(NON_EXISTENT_UUID, REGULATOR_HEADERS)
    assert missing.status_code == 404
    error_body = assert_error_envelope(missing)
    assert error_body["data"]["error_id"] == ERR_STORE_NOT_FOUND
    assert error_body["data"]["message"].strip() != ""
    assert "id" not in error_body["data"]
    assert "store_code" not in error_body["data"]


def test_the_clock_endpoint_reports_the_instant_it_replaced(api):
    """
    §2.4 starts the logical clock at 2026-08-01T00:00:00Z and has the setter report
    both the instant it installed and the one it replaced, so the first call on a
    fresh server echoes the documented default on both sides.

    Design: Corner/endpoints/clock_endpoint_reports_the_instant_it_replaced
    """
    first = validate_success(
        api.set_clock(F.clock_payload("2026-08-01T00:00:00Z"), PLATFORM_ADMIN_HEADERS)
    )
    assert_instant(first["current_utc"], "2026-08-01T00:00:00Z", "current_utc")
    assert_instant(first["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

    second = validate_success(
        api.set_clock(F.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN_HEADERS)
    )
    assert_instant(second["current_utc"], "2026-09-01T00:00:00Z", "current_utc")
    assert_instant(second["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

    store = X.create_store(api)
    assert_instant(store["created_at"], "2026-09-01T00:00:00Z", "created_at")


def test_closing_an_inspection_freezes_its_exposure_and_drops_it_from_the_total(api):
    """
    §3.9 makes closure the freeze point: the closed inspection leaves the exposure
    pool and is never recomputed again, so a leak event opened afterwards moves the
    store's posture without disturbing the frozen figure.

    Design: Corner/endpoints/closing_an_inspection_freezes_its_exposure_and_drops_it_from_the_store_total
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    inspection = X.open_inspection(
        api,
        store["id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    responded = validate_success(
        api.respond_to_inspection(
            inspection["id"],
            F.inspection_response_payload(
                response_summary="All leak records reconciled and refiled.",
                corrective_action_code="RECORDS_CORRECTED",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert responded["status"] == INSPECTION_RESPONDED
    assert_penalty_exposure(
        responded, penalty_exposure_usd=275.55, chronic_multiplier_applied=1.00
    )
    assert_store_posture(
        X.get_store(api, store["id"]), penalty_exposure_total_usd=275.55
    )

    closed = validate_success(
        api.close_inspection(
            inspection["id"],
            F.inspection_closure_payload(
                closure_note="Corrective action accepted; matter closed."
            ),
            REGULATOR_2_HEADERS,
        )
    )
    assert closed["status"] == INSPECTION_CLOSED
    assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")
    assert closed["closed_by_user_id"] == REGULATOR_2_USER_ID
    assert_store_posture(
        X.get_store(api, store["id"]), penalty_exposure_total_usd=0.00
    )

    late_system = X.create_system(
        api, store["id"], rt404["id"], full_charge_lbs=60.0, initial_charge_lbs=0.0
    )
    X.declare_leak_event(api, late_system["id"], detected_at="2026-08-01T00:00:00Z")

    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_AT_RISK,
        open_leak_event_count=1,
        penalty_exposure_total_usd=0.00,
    )
    assert_penalty_exposure(
        X.get_inspection(api, inspection["id"]),
        penalty_exposure_usd=275.55,
        chronic_multiplier_applied=1.00,
    )
