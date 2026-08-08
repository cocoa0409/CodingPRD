"""Client discharge and the depth-5 consistency cascade.

Queue A: transitive_cascade (discharge_cascade_client_to_material).
"""
from test_helpers import validate_success, TEST_USERS
from test_helpers import fixtures as fx


def _discharge_scenario(api):
    """Insurance client with an ACTIVE plan+goal and a FUTURE SCHEDULED session that
    reserves 1 of 3 material units, with the client enrolled. Returns the context
    extended with material_id, session_id, enrollment_id, then discharges the client."""
    ctx = fx.setup_active_plan(api, payer="INSURANCE", clock="2026-06-01T00:00:00Z")
    mat = fx.new_material(api, name="Guitar", on_hand_quantity=3, unit_charge_cents=500)
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                  start_utc="2026-06-05T09:00:00Z", end_utc="2026-06-05T10:00:00Z",
                                  material_item_id=mat["id"], material_qty=1)
    enrollment = fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    ctx["material_id"] = mat["id"]
    ctx["session_id"] = session["id"]
    ctx["enrollment_id"] = enrollment["id"]
    validate_success(api.discharge_client(ctx["client_id"], {"discharge_reason": "Goals met early"},
                                          TEST_USERS["clinical_headers"]), expected_status=200)
    return ctx


def test_discharge_cascades_client_plan_goal(api):
    """PRD §3.9: "the client moves `ACTIVE → DISCHARGED`. From there the cascade flows
    down five levels. The client's plan that is currently `ACTIVE` or `UNDER_REVISION`
    transitions to `DISCHARGED`. Each `OPEN` goal of that plan transitions to
    `DISCONTINUED`."

    Design: Difficulty/transitive_cascade/discharge_cascade_client_to_material
    """
    ctx = _discharge_scenario(api)
    client = validate_success(api.get_client(ctx["client_id"], TEST_USERS["clinical_headers"]),
                              expected_status=200)
    assert client["status"] == "DISCHARGED"
    plan = validate_success(api.get_treatment_plan(ctx["plan_id"], TEST_USERS["clinical_headers"]),
                            expected_status=200)
    assert plan["status"] == "DISCHARGED"
    goal = fx.fetch_goal(api, ctx["plan_id"], ctx["goal_id"])
    assert goal["status"] == "DISCONTINUED"


def test_discharge_cascades_session_enrollment_material(api):
    """PRD §3.9: "Each still-`SCHEDULED` session tied to such a goal transitions
    `SCHEDULED → CANCELLED`. Each non-terminal enrollment of those cancelled sessions
    transitions to `CANCELLED`. And every cancelled session releases its held
    resources exactly as a manual cancellation would: its material reservation is
    returned (the item's `reserved_quantity` drops by `material_qty`)".

    Design: Difficulty/transitive_cascade/discharge_cascade_client_to_material
    """
    ctx = _discharge_scenario(api)
    session = validate_success(api.get_session(ctx["session_id"], TEST_USERS["clinical_headers"]),
                               expected_status=200)
    assert session["scheduling_status"] == "CANCELLED"
    enrollment = validate_success(
        api.get_enrollment(ctx["enrollment_id"], TEST_USERS["clinical_headers"]), expected_status=200)
    assert enrollment["status"] == "CANCELLED"
    material = validate_success(api.get_material(ctx["material_id"], TEST_USERS["clinical_headers"]),
                                expected_status=200)
    assert material["reserved_quantity"] == 0
    assert material["available_quantity"] == 3
