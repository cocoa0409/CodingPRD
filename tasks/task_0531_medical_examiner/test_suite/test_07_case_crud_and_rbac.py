"""Case creation, computed fields, triage/state validity, RBAC, versioning."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_investigator, create_pathologist, create_cooler,
    create_reported_case, create_investigating_case, create_accepted_case,
    store_body,
    make_investigator_headers, make_pathologist_headers,
    create_case_payload, triage_payload, create_body_payload,
    store_body_payload, create_investigator_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_case_returns_201_with_defaults(api):
    """PRD §3.2: "Reporting creates a case in the REPORTED state with its case_type initialized
    to PENDING; no authentication is required for this single intake operation."

    Design: Corner/entities/create_case_returns_201_with_defaults
    """
    inv = create_investigator("Inv CA1")
    inv_headers = make_investigator_headers(inv["id"])
    res = api.create_case(create_case_payload(inv["id"], decedent_name="Doe CA1"), inv_headers)
    case = validate_success(res, 201)
    assert case["status"] == "REPORTED"
    assert case["case_type"] == "PENDING"


def test_get_case_not_found_returns_404(api):
    """PRD §2.6: "the system validates each identifier in strict left-to-right order and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier that does not
    resolve to an existing resource."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    res = api.get_case("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_case_missing_required_field_returns_400(api):
    """PRD §2.12: "Malformed request bodies — missing required fields, wrong types,
    out-of-domain enum values, or violated numeric constraints — are rejected with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_case_missing_required_field_returns_400
    """
    inv = create_investigator("Inv CA2")
    inv_headers = make_investigator_headers(inv["id"])
    payload = create_case_payload(inv["id"])
    del payload["death_location_county"]
    res = api.create_case(payload, inv_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_triage_bad_case_type_enum_returns_400(api):
    """PRD §2.12: "Malformed request bodies — missing required fields, wrong types,
    out-of-domain enum values, or violated numeric constraints — are rejected with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_case_bad_case_type_enum_returns_400
    """
    inv = create_investigator("Inv CA3")
    inv_headers = make_investigator_headers(inv["id"])
    case = create_reported_case(inv)
    res = api.triage_case(case["id"], {"case_type": "SUICIDE"}, inv_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_duplicate_badge_no_returns_409(api):
    """PRD §3.1: "An Admin registers an investigator by supplying a full_name and a unique
    badge_no ... an attempt to reuse a badge_no already on file is rejected with ERR_DUPLICATE."

    Design: Corner/entities/duplicate_badge_no_returns_409
    """
    validate_success(
        api.create_investigator(create_investigator_payload(full_name="Inv First", badge_no="CB-DUP"), ADMIN),
        201,
    )
    res = api.create_investigator(
        create_investigator_payload(full_name="Inv Second", badge_no="CB-DUP"), ADMIN
    )
    validate_error(res, "ERR_DUPLICATE", expected_status=409)


def test_system_fields_version_starts_at_one(api):
    """PRD §2.4: "an integer version that starts at its initial value and increments by exactly
    one on each mutation."

    Design: Corner/entities/system_fields_generated_on_case_create
    """
    inv = create_investigator("Inv CA5")
    inv_headers = make_investigator_headers(inv["id"])
    case = validate_success(
        api.create_case(create_case_payload(inv["id"], decedent_name="Doe CA5"), inv_headers), 201
    )
    assert case["version"] == 1


def test_computed_jurisdiction_declined_out_of_county(api):
    """PRD §3.2: "If instead the county is not among the served counties, triage advances
    REPORTED -> DECLINED, a terminal state, setting jurisdiction_status to DECLINED and
    served_county to false."

    Design: Corner/entities/computed_jurisdiction_declined_out_of_county
    """
    from test_helpers.constants import UNSERVED_COUNTY
    inv = create_investigator("Inv CA6")
    inv_headers = make_investigator_headers(inv["id"])
    case = create_reported_case(inv, county=UNSERVED_COUNTY, decedent_name="Doe CA6")
    triaged = validate_success(
        api.triage_case(case["id"], triage_payload("NATURAL"), inv_headers), 200
    )
    assert triaged["jurisdiction_status"] == "DECLINED"
    assert triaged["status"] == "DECLINED"


def test_list_cases_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following fields
    in the meta object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_cases_pagination_envelope
    """
    inv = create_investigator("Inv CA7")
    create_reported_case(inv, decedent_name="Doe CA7")
    data, meta = validate_paginated(api.list_cases(ADMIN, params={"limit": 5, "offset": 0}))
    assert meta["total_count"] >= 1
    assert isinstance(data, list)


def test_triage_from_investigating_returns_invalid_state(api):
    """PRD §3.2: "Triage is legal only from REPORTED; attempting it from any other state yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/triage_from_investigating_returns_invalid_state
    """
    inv = create_investigator("Inv CS1")
    inv_headers = make_investigator_headers(inv["id"])
    case, body = create_investigating_case(inv, case_type="NATURAL")
    res = api.triage_case(case["id"], triage_payload("HOMICIDE"), inv_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_artifact_on_declined_case_returns_case_declined(api):
    """PRD §3.2: "A declined case is a dead end — any subsequent attempt to intake a body,
    schedule an autopsy, or draft a certificate for it is rejected with ERR_CASE_DECLINED
    (HTTP 409)."

    Design: Corner/state_machines/artifact_on_declined_case_returns_case_declined
    """
    from test_helpers.constants import UNSERVED_COUNTY
    inv = create_investigator("Inv CS2")
    inv_headers = make_investigator_headers(inv["id"])
    case = create_reported_case(inv, county=UNSERVED_COUNTY, decedent_name="Doe CS2")
    validate_success(api.triage_case(case["id"], triage_payload("NATURAL"), inv_headers), 200)
    res = api.create_body(case["id"], create_body_payload(tag_no="CS-T2"), inv_headers)
    validate_error(res, "ERR_CASE_DECLINED", expected_status=409)


def test_close_case_blocked_while_body_stored(api):
    """PRD §3.8: "Closure is permitted only when the case's body has been RELEASED and no
    property item for the case remains in HELD."

    Design: Corner/state_machines/close_case_blocked_while_body_stored
    """
    from test_helpers import setup_certified_case_natural
    inv = create_investigator("Inv CS3")
    me = create_pathologist("ME CS3", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    # Certified case, body still STORED (not released).
    case, body = setup_certified_case_natural(inv, me, cooler=cooler)
    assert body["storage_status"] == "STORED"

    inv_headers = make_investigator_headers(inv["id"])
    res = api.close_case(case["id"], inv_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pathologist_cannot_triage_case(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the rejection is ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/pathologist_cannot_triage_case
    """
    inv = create_investigator("Inv CR1")
    path = create_pathologist("Path CR1")
    case = create_reported_case(inv, decedent_name="Doe CR1")
    path_headers = make_pathologist_headers(path["id"])
    res = api.triage_case(case["id"], triage_payload("NATURAL"), path_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing on an operation that requires authentication, or
    if X-User-Role is not one of the roles enumerated below, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    inv = create_investigator("Inv CR2")
    case = create_reported_case(inv, decedent_name="Doe CR2")
    res = api.get_case(case["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_cooler_occupied_slots_after_store(api):
    """PRD §2.9: "a computed occupied_slots count that always equals the number of bodies
    currently stored in that unit."

    Design: Corner/cross_cutting_complexity_layers/cooler_version_increments_on_store
    """
    inv = create_investigator("Inv CX3")
    cooler = create_cooler(slot_capacity=2)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body, cooler)

    inv_headers = make_investigator_headers(inv["id"])
    cooler_after = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    assert cooler_after["occupied_slots"] == 1
