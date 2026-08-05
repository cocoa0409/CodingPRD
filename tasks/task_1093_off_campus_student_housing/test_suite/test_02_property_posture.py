"""Property listing posture: invalid transitions, no-unit guard, auto-posture.

Corner coverage index, property entries of the state_machines section
(queue B).
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def test_property_posture_invalid_transitions_rejected(api):
    """PRD §3.2: "Listing a property that is not DRAFT is
    ERR_PROPERTY_INVALID_STATE." PRD §3.2: "suspending a DRAFT or
    already-SUSPENDED property is ERR_PROPERTY_INVALID_STATE." PRD §3.2:
    "reinstating a property that is not SUSPENDED is ERR_PROPERTY_INVALID_STATE."

    Design: Corner/state_machines/property_posture_invalid_transitions_rejected
    """
    uni = fx.create_university(api)
    prop1 = fx.create_property(api, uni["id"], name="Maple Commons")
    fx.create_unit(api, prop1["id"], bedroom_count=4, bed_labels=["A", "B", "C", "D"])
    fx.list_property(api, prop1["id"])
    prop2 = fx.create_property(api, uni["id"], name="Birch House")
    validate_error(api.list_property(prop1["id"], MGR), ApiErrorId.ERR_PROPERTY_INVALID_STATE.value)
    validate_error(api.suspend_property(prop2["id"], ADMIN, {"reason": "premature"}),
                   ApiErrorId.ERR_PROPERTY_INVALID_STATE.value)
    validate_error(api.reinstate_property(prop1["id"], ADMIN),
                   ApiErrorId.ERR_PROPERTY_INVALID_STATE.value)
    assert fx.get_property(api, prop1["id"])["status"] == "LISTED"
    assert fx.get_property(api, prop2["id"])["status"] == "DRAFT"


def test_property_list_without_any_unit_rejected(api):
    """PRD §3.2: "provided it has at least one unit - a property with unit_count
    of 0 is refused with ERR_PROPERTY_HAS_NO_UNITS".

    Design: Corner/state_machines/property_list_without_any_unit_rejected
    """
    uni = fx.create_university(api)
    prop = fx.create_property(api, uni["id"])
    validate_error(api.list_property(prop["id"], MGR), ApiErrorId.ERR_PROPERTY_HAS_NO_UNITS.value)
    assert fx.get_property(api, prop["id"])["status"] == "DRAFT"
    fx.create_unit(api, prop["id"], bedroom_count=4, bed_labels=["A", "B", "C", "D"])
    after = fx.get_property(api, prop["id"])
    assert after["unit_count"] == 1 and after["total_bed_count"] == 4 and after["available_bed_count"] == 4
    listed = validate_success(api.list_property(prop["id"], MGR), 200)
    assert listed["status"] == "LISTED"


def test_property_returns_from_fully_committed_to_listed_when_a_bed_frees(api):
    """PRD §2.8: "A LISTED property whose available_bed_count reaches 0
    auto-transitions to FULLY_COMMITTED; a FULLY_COMMITTED property whose
    available_bed_count rises above 0 auto-transitions back to LISTED."

    Design: Corner/state_machines/property_returns_from_fully_committed_to_listed_when_a_bed_frees
    """
    base = fx.base_property(api, bed_labels=("A",), unit_over={"unit_number": "S1",
                            "floorplan_code": "1x1", "bathroom_count": 1})
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.draft_lease(api, student["id"], base["unit"]["id"], "A")
    fx.submit_lease(api, lease["id"], student["id"])
    unit = fx.get_unit(api, base["unit"]["id"])
    prop = fx.get_property(api, base["prop"]["id"])
    assert unit["occupancy_status"] == "FULLY_LEASED" and prop["available_bed_count"] == 0
    assert prop["status"] == "FULLY_COMMITTED"
    api.cancel_lease(lease["id"], make_student_headers(student["id"]), {"reason": "changed mind"})
    unit2 = fx.get_unit(api, base["unit"]["id"])
    prop2 = fx.get_property(api, base["prop"]["id"])
    assert unit2["occupancy_status"] == "AVAILABLE" and prop2["available_bed_count"] == 1
    assert prop2["status"] == "LISTED"
