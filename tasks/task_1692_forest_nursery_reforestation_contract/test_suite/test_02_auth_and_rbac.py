"""Authentication, authorization, and entity-backed ownership rules."""
from test_helpers import (
    validate_error, build_user_headers, ApiErrorId, TEST_USERS,
    create_seed_zone, create_seed_lot, create_landowner, create_order,
    create_contract, create_enrollment,
    create_seed_zone_payload,
    make_landowner_headers,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]
PA = TEST_USERS["program_administrator_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request with missing headers, an undeclared role, or an
    unresolvable Landowner id is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    res = api.create_seed_zone(
        create_seed_zone_payload(zone_code="Z-1", min_elevation_ft=100, max_elevation_ft=900),
        {"Content-Type": "application/json"},
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unknown_role_rejected(api):
    """PRD §2.1: "A request with missing headers, an undeclared role, or an
    unresolvable Landowner id is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unknown_role_rejected
    """
    headers = build_user_headers("test-superuser-1", "SuperUser")
    res = api.create_seed_zone(
        create_seed_zone_payload(zone_code="Z-1", min_elevation_ft=100, max_elevation_ft=900),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_landowner_order_for_other_landowner_forbidden(api):
    """PRD §3.3: "A landowner places a seedling order for their own account: the
    `landowner_id` in the payload must equal the caller's `X-User-ID` (a mismatch
    is rejected with `ERR_UNAUTHORIZED`)"

    Design: Corner/validations/landowner_order_for_other_landowner_forbidden
    """
    zone = create_seed_zone(zone_min=1400, zone_max=2400)
    lo_a = create_landowner(legal_name="Owner A", contact_email="a@x.com", tax_id="T-A")
    lo_b = create_landowner(legal_name="Owner B", contact_email="b@x.com", tax_id="T-B")

    res = api.create_seedling_order(
        {
            "landowner_id": lo_a["id"],
            "destination_zone_id": zone["id"],
            "species": "DOUGLAS_FIR",
            "quantity": 100,
            "requested_ship_date": "2027-04-05",
        },
        make_landowner_headers(lo_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_landowner_cannot_create_seed_zone(api):
    """PRD §4: "POST | `/reforestation/seed-zones` | Create a seed collection
    zone | NurseryManager" and PRD §2.1: "A request whose role is not in the
    endpoint's authorized role list — or a `Landowner` reaching for another
    landowner's resource — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/landowner_cannot_create_seed_zone
    """
    lo = create_landowner(legal_name="Owner U", contact_email="u@x.com", tax_id="T-U")
    res = api.create_seed_zone(
        create_seed_zone_payload(zone_code="Z-1", min_elevation_ft=100, max_elevation_ft=900),
        make_landowner_headers(lo["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_nursery_manager_cannot_approve_enrollment(api):
    """PRD §4: "POST | `/reforestation/cost-share-enrollments/{id}/approve` |
    Approve and fix the final award | ProgramAdministrator" and PRD §2.6: "Every
    request passes through a fixed pipeline of checks, and when several checks
    could reject the same request, the one earliest in this order fires."
    (Authorization, rule 2, precedes state legality, rule 5.)

    Design: Corner/rbac/nursery_manager_cannot_approve_enrollment
    """
    lo = create_landowner(legal_name="Owner V", contact_email="v@x.com", tax_id="T-V")
    enr = create_enrollment(lo["id"])  # stays in DRAFT

    res = api.approve_cost_share_enrollment(enr["id"], NM)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_contract_officer_cannot_create_survey(api):
    """PRD §4: "POST | `/reforestation/survival-surveys` | Record a survival
    survey; fires threshold verdict and CASCADE B | FieldAuditor" and PRD §2.6:
    "Every request passes through a fixed pipeline of checks, and when several
    checks could reject the same request, the one earliest in this order fires."
    (Authorization, rule 2, precedes existence, rule 3.)

    Design: Corner/rbac/contract_officer_cannot_create_survey
    """
    res = api.create_survival_survey(
        {
            "planting_contract_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "surveyed_on": "2028-02-15",
            "alive_count": 10,
        },
        CO,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_program_admin_cannot_quarantine_lot(api):
    """PRD §4: "POST | `/reforestation/seed-lots/{id}/quarantine` | Quarantine a
    lot after a failed germination retest | NurseryManager" and PRD §2.1: "A
    request whose role is not in the endpoint's authorized role list — or a
    `Landowner` reaching for another landowner's resource — is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/program_admin_cannot_quarantine_lot
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=100, germination_pct=0.8)
    res = api.quarantine_seed_lot(lot["id"], PA)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_landowner_cannot_read_others_contract(api):
    """PRD §2.1: "ownership checks on any resource that references a landowner
    compare the resource's `landowner_id` field to `X-User-ID`, and a `Landowner`
    caller may touch only resources whose `landowner_id` matches." and PRD §4:
    "GET | `/reforestation/planting-contracts/{id}` | Read one contract;
    Landowner reads only its own"

    Design: Corner/rbac/landowner_cannot_read_others_contract
    """
    zone = create_seed_zone(zone_min=1400, zone_max=2400)
    lo_a = create_landowner(legal_name="Owner A", contact_email="a@x.com", tax_id="T-A")
    lo_b = create_landowner(legal_name="Owner B", contact_email="b@x.com", tax_id="T-B")
    order = create_order(lo_a["id"], zone["id"], 100)
    contract = create_contract(lo_a["id"], order["id"], zone["id"], acres=1)

    res = api.get_planting_contract(contract["id"], make_landowner_headers(lo_b["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
