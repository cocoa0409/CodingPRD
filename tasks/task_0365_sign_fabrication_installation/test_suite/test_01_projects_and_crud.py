"""Project creation, computed defaults, input validation, and RBAC/auth basics.

Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_sign_project, assert_equipment, assert_art_proof,
    create_sign_project_payload, create_art_proof_payload, create_estimate_payload,
    create_equipment_payload,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
DES = TEST_USERS["designer_headers"]
CUST = TEST_USERS["customer_headers"]

NONEXISTENT_PROJECT = "00000000-0000-4000-8000-000000000000"


def test_create_sign_project_returns_computed_defaults(api):
    """PRD §3.1: "A fresh project is created in DESIGN phase, with permit_required
    computed per §2.9, and contract_total_cents initialized to 0."
    PRD §2.9: "permit_required is true unless the project is both in COUNTY_C and
    not illuminated."
    PRD §2.4: an integer version "that begins at its initial value on creation".

    Design: Corner/entities/create_sign_project_returns_201_with_computed_defaults
    """
    res = api.create_sign_project(create_sign_project_payload(
        customer_name="New Co", site_address="1 Open St",
        jurisdiction_code="COUNTY_C", sign_type="WALL",
        face_width_in=36, face_height_in=24, placement_height_ft=6), SM)
    project = validate_success(res, 201)
    assert_sign_project(project)
    assert project["phase"] == "DESIGN"
    assert project["contract_total_cents"] == 0
    assert project["permit_required"] is False
    assert project["version"] == 1


def test_permit_required_true_when_illuminated_in_county_c(api):
    """PRD §2.9: "A project requires permits when its jurisdiction_code is not
    COUNTY_C, or when the sign is illuminated — that is, permit_required is true
    unless the project is both in COUNTY_C and not illuminated."

    Design: Corner/entities/permit_required_true_when_illuminated_in_county_c
    """
    res = api.create_sign_project(create_sign_project_payload(
        customer_name="Lit Co", site_address="2 Glow St",
        jurisdiction_code="COUNTY_C", sign_type="WALL",
        face_width_in=36, face_height_in=24, placement_height_ft=6,
        illuminated=True), SM)
    project = validate_success(res, 201)
    assert project["permit_required"] is True


def test_get_sign_project_not_found_returns_404(api):
    """PRD §2.6: "If the project id does not exist, or if the child id does not
    exist or belongs to a different project, the request is rejected with
    ERR_NOT_FOUND."

    Design: Corner/entities/get_sign_project_not_found_returns_404
    """
    res = api.get_sign_project(NONEXISTENT_PROJECT, SM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_sign_project_missing_required_field_returns_422(api):
    """PRD §3.1: "a non-positive dimension is rejected with ERR_INVALID_REQUEST,
    as is a missing required field or an out-of-range enum."

    Design: Corner/entities/create_sign_project_missing_required_field_returns_422
    """
    payload = create_sign_project_payload(
        customer_name="Bad Co", site_address="3 Gap St",
        jurisdiction_code="COUNTY_C", sign_type="WALL",
        face_height_in=24, placement_height_ft=6)
    del payload["face_width_in"]
    res = api.create_sign_project(payload, SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_sign_project_invalid_enum_returns_422(api):
    """PRD §3.1: "a non-positive dimension is rejected with ERR_INVALID_REQUEST,
    as is a missing required field or an out-of-range enum."

    Design: Corner/entities/create_sign_project_invalid_enum_returns_422
    """
    res = api.create_sign_project(create_sign_project_payload(
        customer_name="Enum Co", site_address="4 Bad St",
        jurisdiction_code="COUNTY_C", sign_type="BILLBOARD",
        face_width_in=36, face_height_in=24, placement_height_ft=6), SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_sign_project_nonpositive_dimension_returns_422(api):
    """PRD §3.1: "face_width_in and face_height_in must each be greater than zero,
    and placement_height_ft must be at least zero; a non-positive dimension is
    rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_sign_project_nonpositive_dimension_returns_422
    """
    res = api.create_sign_project(create_sign_project_payload(
        customer_name="Zero Co", site_address="5 Null St",
        jurisdiction_code="COUNTY_C", sign_type="WALL",
        face_width_in=36, face_height_in=0, placement_height_ft=6), SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_equipment_server_mints_id_and_defaults_in_service(api):
    """PRD §2.4: "Every entity in the system carries a server-minted id formatted
    as a UUID with no type prefix."
    PRD §3.5: an optional in_service flag "(defaulting to true) that, when false,
    marks a unit down for maintenance and unbookable."

    Design: Corner/entities/equipment_immutable_no_version_field
    """
    res = api.create_equipment(create_equipment_payload(
        asset_tag="LAD-X", equipment_class="LADDER", max_reach_ft=16), SM)
    equip = validate_success(res, 201)
    assert_equipment(equip)
    assert equip["equipment_class"] == "LADDER"
    assert equip["in_service"] is True
    # The server-minted id is what GET resolves.
    got = validate_success(api.get_equipment(equip["id"], SM), 200)
    assert got["id"] == equip["id"]


def test_art_proof_default_revision_no_is_one(api):
    """PRD §3.1: "The system stamps each proof with a revision_no: the very first
    proof of a project is revision 1, and each successive proof takes the prior
    maximum revision number plus one." "A new proof is born in DRAFT."

    Design: Corner/entities/art_proof_default_revision_no_is_one
    """
    project = validate_success(api.create_sign_project(create_sign_project_payload(
        customer_name="Rev Co", site_address="6 First St"), SM), 201)
    res = api.create_art_proof(project["id"], create_art_proof_payload(color_count=2), DES)
    proof = validate_success(res, 201)
    assert_art_proof(proof)
    assert proof["revision_no"] == 1
    assert proof["status"] == "DRAFT"


# ─── RBAC / auth (queue B: rbac section) ─────────────────────────────────────

def test_designer_cannot_create_estimate(api):
    """PRD §2.1: "When the header is present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN." PRD §4: POST /sign-projects/{id}/estimates is authorized for
    ShopManager.

    Design: Corner/rbac/designer_cannot_create_estimate
    """
    project = validate_success(api.create_sign_project(create_sign_project_payload(
        customer_name="Rb Co", site_address="30 Role St"), SM), 201)
    proof = validate_success(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES), 201)
    api.submit_art_proof(project["id"], proof["id"], DES)
    api.decide_art_proof(project["id"], proof["id"], {"decision": "APPROVE"}, CUST)
    res = api.create_estimate(
        project["id"], create_estimate_payload(proof["id"], substrate="ALUMINUM"), DES)
    validate_error(res, "ERR_FORBIDDEN")


def test_customer_cannot_submit_art_proof(api):
    """PRD §2.1: "When the header is present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN." PRD §4: POST /sign-projects/{id}/art-proofs/{proof_id}/submit
    is authorized for Designer.

    Design: Corner/rbac/customer_cannot_accept_someone_elses_step_proof_submit
    """
    project = validate_success(api.create_sign_project(create_sign_project_payload(
        customer_name="Rb2 Co", site_address="31 Role St"), SM), 201)
    proof = validate_success(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES), 201)
    res = api.submit_art_proof(project["id"], proof["id"], CUST)
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or names a role the system does not
    recognize, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.create_sign_project(
        create_sign_project_payload(customer_name="Anon Co", site_address="32 Null St"),
        {"X-User-ID": "nobody", "X-User-Role": "Nobody"})
    validate_error(res, "ERR_UNAUTHENTICATED")
