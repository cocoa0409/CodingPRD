"""Physical estate creation and section inventory reconciliation.

Covers corner entities/state_machines instances for cemetery/section/gravesite
creation, plus compensating-invariant and consistency-model difficulty instances
that assert Section inventory conservation.
"""
from test_helpers import (
    TEST_USERS,
    NO_AUTH_HEADERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_cemetery,
    create_in_ground_section,
    create_columbarium_section,
    setup_cemetery_with_gravesite,
    open_and_approve_case,
    assign_plot_auto,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ===========================================================================
# Corner: entities — cemetery creation
# ===========================================================================
def test_create_overseas_cemetery_computes_is_overseas(api):
    """PRD §2.10: "From this the system computes the boolean is_overseas, which is
    true exactly when the country_code is not US."

    Design: Corner/entities/create_cemetery_returns_201_with_computed_is_overseas
    """
    cem = validate_success(api.create_cemetery({
        "name": "Manila American", "country_code": "PH", "honors_squad_capacity": 2,
    }, ADMIN), expected_status=201)
    assert cem["is_overseas"] is True
    assert cem["country_code"] == "PH"


def test_create_cemetery_missing_capacity_rejected(api):
    """PRD §2.6: "Malformed bodies, missing required fields, and invalid enum values
    surface as ERR_VALIDATION."

    Design: Corner/entities/create_cemetery_missing_required_field_rejected
    """
    resp = api.create_cemetery({"name": "NoCapacity National", "country_code": "US"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_cemetery_country_code_defaults_to_us(api):
    """PRD §3.1: "A cemetery is created with a name, an optional country_code
    (defaulting to US), and an honors_squad_capacity"
    PRD §2.10: "which is true exactly when the country_code is not US."

    Design: Corner/entities/cemetery_country_code_defaults_to_US
    """
    cem = validate_success(api.create_cemetery({
        "name": "Default National", "honors_squad_capacity": 1,
    }, ADMIN), expected_status=201)
    assert cem["country_code"] == "US"
    assert cem["is_overseas"] is False


def test_get_cemetery_not_found(api):
    """PRD §2.5: "the server validates the identifiers in the path from left to
    right and rejects the request with ERR_NOT_FOUND at the first identifier in the
    path that does not name an existing resource."

    Design: Corner/entities/get_cemetery_not_found_returns_404
    """
    resp = api.get_cemetery(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_gravesite_created_available_interment_count_zero(api):
    """PRD §3.1: "A new gravesite starts with status of AVAILABLE and an
    interment_count of zero; its reserved_by_case_id is null while it remains
    available."

    Design: Corner/entities/gravesite_system_fields_input_ignored
    """
    cem = create_cemetery(name="SysF National", honors_squad_capacity=1)
    sec = create_in_ground_section(cem["id"], code="A")
    grv = validate_success(api.create_gravesite(cem["id"], sec["id"], {
        "section_id": sec["id"], "grid_ref": "R1C1",
        "gravesite_class": "STANDARD", "depth_capacity": 1,
    }, ADMIN), expected_status=201)
    assert grv["status"] == "AVAILABLE"
    assert grv["interment_count"] == 0


# ===========================================================================
# Corner: state_machines — unit kind guard on creation
# ===========================================================================
def test_gravesite_under_columbarium_rejected(api):
    """PRD §3.1: "Attempting to add a gravesite under a COLUMBARIUM section is
    rejected with ERR_UNIT_KIND_MISMATCH."

    Design: Corner/state_machines/gravesite_created_under_columbarium_section_rejected
    """
    cem = create_cemetery(name="Guard National", honors_squad_capacity=1)
    sec = create_columbarium_section(cem["id"], code="C")
    resp = api.create_gravesite(cem["id"], sec["id"], {
        "section_id": sec["id"], "grid_ref": "R1C1",
        "gravesite_class": "STANDARD", "depth_capacity": 1,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNIT_KIND_MISMATCH, expected_status=422)


# ===========================================================================
# compensating_invariant — assign then release conserves section available_units
# ===========================================================================
def test_assign_release_conserves_section_available_units(api):
    """PRD §3.4: "Releasing moves the reserved unit from RESERVED back to AVAILABLE,
    clears its reserved_by_case_id, clears the case's assigned_unit_type,
    assigned_gravesite_id, and assigned_niche_id, and recomputes the parent
    section's inventory."
    PRD §2.7: "Its available_units is the count of those children whose status is
    AVAILABLE."

    Design: Difficulty/compensating_invariant/assign_release_conserves_section_available_units
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case["id"])
    validate_success(api.release_plot(cem["id"], case["id"], CLERK))
    sec_read = validate_success(api.get_section(cem["id"], sec["id"], ADMIN))
    assert sec_read["capacity_units"] == 1
    assert sec_read["available_units"] == 1
    assert sec_read["interred_units"] == 0
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], ADMIN))
    assert grv_read["status"] == "AVAILABLE"


def test_release_after_assign_returns_case_to_eligible(api):
    """PRD §3.4: "A clerk may undo an assignment by releasing the plot, reverting
    the case from ASSIGNED back to ELIGIBLE."

    Design: Difficulty/compensating_invariant/assign_release_conserves_section_available_units
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case["id"])
    released = validate_success(api.release_plot(cem["id"], case["id"], CLERK))
    assert released["status"] == "ELIGIBLE"
    assert released["assigned_gravesite_id"] is None


# ===========================================================================
# consistency_model — assign-plot side effects visible immediately
# ===========================================================================
def test_assign_plot_side_effects_visible_immediately(api):
    """PRD §3.4: "It moves the chosen unit from AVAILABLE to RESERVED, sets that
    unit's reserved_by_case_id to the case's id, and increments the reserved unit's
    version by one. The parent section's inventory counts are recomputed."
    PRD §2.7: "A unit in the intermediate RESERVED status counts toward neither
    available_units nor interred_units"

    Design: Corner/consistency_model/assign_plot_side_effects_visible_in_same_response
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    assigned = validate_success(api.assign_plot(cem["id"], case["id"], CLERK, payload={}))
    assert assigned["status"] == "ASSIGNED"
    sec_read = validate_success(api.get_section(cem["id"], sec["id"], CLERK))
    assert sec_read["available_units"] == 0
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], CLERK))
    assert grv_read["status"] == "RESERVED"
