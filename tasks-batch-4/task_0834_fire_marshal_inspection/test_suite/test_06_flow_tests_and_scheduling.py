"""Hydrant flow tests (half-open validity windows, readings validation, the
projected-flow calculation, HAZMAT sufficiency gate, reverse listing) and the
symmetric 14-day inspection scheduling buffer.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_hydrant_with_flow_test, create_hydrant, create_flow_test, create_property,
    open_application, schedule_inspection,
    create_flow_test_payload, create_inspection_payload,
    make_applicant_headers,
    api_client,
    TEST_USERS,
)

INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty/resource_temporal_overlap/flow_test_window_overlap_halfopen ─
def test_flow_test_inside_existing_window_rejected(api):
    """PRD §3.2: "A new test's window may not overlap the window of any existing flow
    test on the same hydrant; if it does, the test is rejected with
    `ERR_FLOW_TEST_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/flow_test_window_overlap_halfopen
    """
    _prop, hydrant, _ft = setup_hydrant_with_flow_test(address="16 P St")
    res = api.create_flow_test(create_flow_test_payload(
        hydrant["id"], test_date="2026-09-01T00:00:00Z",
        static_psi=70, residual_psi=50, measured_flow_gpm=1500), INSPECTOR)
    validate_error(res, "ERR_FLOW_TEST_WINDOW_OVERLAP", expected_status=409)


def test_flow_test_adjacent_at_boundary_allowed(api):
    """PRD §3.2: "Adjacency at the boundary is explicitly allowed: an existing window
    that ends exactly at the new test's `test_date` does not count as an overlap."

    Design: Difficulty/resource_temporal_overlap/flow_test_window_overlap_halfopen
    """
    _prop, hydrant, _ft = setup_hydrant_with_flow_test(address="16 P2 St")
    # First window is [2026-03-01, 2027-03-01); a test dated exactly at 2027-03-01 abuts it.
    res = api.create_flow_test(create_flow_test_payload(
        hydrant["id"], test_date="2027-03-01T00:00:00Z",
        static_psi=70, residual_psi=50, measured_flow_gpm=1500), INSPECTOR)
    validate_success(res, 201)


# ─── Difficulty/resource_temporal_overlap/inspection_buffer_too_close ──────
def test_inspection_within_buffer_rejected(api):
    """PRD §3.6: "a new inspection's `scheduled_date` must be at least 14 days away
    from that of any other non-terminal inspection on the same property; the buffer is
    symmetric, so a proposed date fewer than 14 days before or after an existing
    scheduled inspection is rejected with `ERR_INSPECTION_TOO_CLOSE`."

    Design: Difficulty/resource_temporal_overlap/inspection_buffer_too_close
    """
    prop = create_property(address="17 Q St")
    schedule_inspection(prop["id"], scheduled_date="2026-03-10T00:00:00Z")
    res = api.create_inspection(create_inspection_payload(
        prop["id"], inspection_type="PERIODIC", scheduled_date="2026-03-20T00:00:00Z"), INSPECTOR)
    validate_error(res, "ERR_INSPECTION_TOO_CLOSE", expected_status=409)


def test_inspection_exactly_fourteen_days_allowed(api):
    """PRD §3.6: "a new inspection's `scheduled_date` must be at least 14 days away
    from that of any other non-terminal inspection on the same property"

    Design: Difficulty/resource_temporal_overlap/inspection_buffer_too_close
    """
    prop = create_property(address="17 Q2 St")
    schedule_inspection(prop["id"], scheduled_date="2026-03-10T00:00:00Z")
    # 2026-03-24 is exactly 14 days after 2026-03-10 — the buffer is satisfied.
    res = api.create_inspection(create_inspection_payload(
        prop["id"], inspection_type="PERIODIC", scheduled_date="2026-03-24T00:00:00Z"), INSPECTOR)
    validate_success(res, 201)


# ─── Corner/calculations/corner_flow_available_at_20psi_correct ────────────
def test_flow_available_at_20psi_projection(api):
    """PRD §3.2: "Form the pressure ratio as the static pressure minus 20, divided by
    the static pressure minus the residual pressure. Raise that ratio to the power 0.54,
    multiply by the `measured_flow_gpm`, and round the result to the nearest whole gpm
    using round-half-up."
    PRD §3.2: "The server also stamps the test's `valid_until` as the `test_date` plus
    365 days, the exclusive end of its validity window."

    Design: Corner/calculations/corner_flow_available_at_20psi_correct
    """
    _prop, _hydrant, ft = setup_hydrant_with_flow_test(
        address="26 Z St", test_date="2026-03-01T00:00:00Z",
        static_psi=70, residual_psi=50, measured_flow_gpm=1500)
    assert ft["available_flow_at_20psi"] == 2460, \
        f"available_flow_at_20psi expected 2460, got {ft['available_flow_at_20psi']}"
    assert ft["valid_until"].startswith("2027-03-01"), \
        f"valid_until expected 2027-03-01 (+365d), got {ft['valid_until']}"


# ─── Corner/validations/corner_flow_test_invalid_readings_returns_422 ──────
def test_flow_test_invalid_readings_rejected(api):
    """PRD §3.2: "the readings must be physically coherent: the residual pressure must
    be greater than 20 and strictly less than the static pressure, and the measured flow
    must be greater than zero; otherwise the test is rejected with
    `ERR_INVALID_FLOW_READINGS`."

    Design: Corner/validations/corner_flow_test_invalid_readings_returns_422
    """
    prop = create_property(address="30 DD St")
    hydrant = create_hydrant(prop["id"], location_desc="gate2", main_size_inches=6)
    res = api.create_flow_test(create_flow_test_payload(
        hydrant["id"], test_date="2026-03-01T00:00:00Z",
        static_psi=50, residual_psi=60, measured_flow_gpm=1000), INSPECTOR)
    validate_error(res, "ERR_INVALID_FLOW_READINGS", expected_status=422)


# ─── Corner/validations/corner_complaint_inspection_missing_description_returns_422
def test_complaint_inspection_without_description_rejected(api):
    """PRD §3.6: "a `COMPLAINT` inspection must also carry a `complaint_description`,
    and its absence is rejected with `ERR_MISSING_CONDITIONAL_FIELD`"

    Design: Corner/validations/corner_complaint_inspection_missing_description_returns_422
    """
    prop = create_property(address="31 EE St")
    res = api.create_inspection(create_inspection_payload(
        prop["id"], inspection_type="COMPLAINT", scheduled_date="2026-03-05T00:00:00Z"),
        INSPECTOR)
    validate_error(res, "ERR_MISSING_CONDITIONAL_FIELD", expected_status=422)


# ─── Corner/validations/corner_hazmat_submit_insufficient_fire_flow_returns_409
def test_hazmat_submit_insufficient_fire_flow_rejected(api):
    """PRD §3.3: "When a `flow_test_id` is present for such an application, the
    referenced flow test's `available_flow_at_20psi` must be at least the property's
    `required_fire_flow_gpm`; if the available flow falls short, the submit is rejected
    with `ERR_INSUFFICIENT_FIRE_FLOW`."

    Design: Corner/validations/corner_hazmat_submit_insufficient_fire_flow_returns_409
    """
    prop = create_property(occupancy_classification="FACTORY", construction_type="TYPE_V",
                           total_floor_area_sqft=20000, stories=2, address="32 FF St")
    hydrant = create_hydrant(prop["id"], location_desc="yard", main_size_inches=6)
    ft = create_flow_test(hydrant["id"], test_date="2026-03-01T00:00:00Z",
                          static_psi=30, residual_psi=25, measured_flow_gpm=300)
    app = open_application(prop["id"], applicant_user_id="app-12", permit_type="HAZMAT",
                           project_valuation_cents=500000, scope_area_sqft=4000,
                           flow_test_id=ft["id"])
    res = api.submit_permit_application(app["id"], make_applicant_headers("app-12"))
    validate_error(res, "ERR_INSUFFICIENT_FIRE_FLOW", expected_status=409)


# ─── Corner/endpoints/corner_reverse_reach_flow_tests_by_hydrant ───────────
def test_list_flow_tests_returns_hydrant_flow_test(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return
    resources sorted by their creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/corner_reverse_reach_flow_tests_by_hydrant
    """
    _prop, hydrant, ft = setup_hydrant_with_flow_test(address="34 HH St")
    body = api.list_flow_tests(INSPECTOR, params={"hydrant_id": hydrant["id"]}).json()
    ids = [row["id"] for row in body["data"]]
    assert ft["id"] in ids, "the hydrant's flow test must appear in the flow-test list"
