"""CRUD basics, field defaults, RBAC, and not-found handling.

Queue B (Corner): entities, endpoints, rbac sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    make_clerk_headers,
    make_officer_headers,
    make_proctor_headers,
    build_user_headers,
    create_driver_record,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")
PROCTOR = make_proctor_headers("kp-1")


# ===========================================================================
# Corner/entities
# ===========================================================================
def test_create_driver_record_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created record opens with licensing_status of
    UNLICENSED, cdl_status of NONE, a point_balance of zero, a
    prior_suspension_count of zero, knowledge_test_passed false, real_id_status of
    NONE, and real_id_categories_met of zero."
    PRD §2.4: "an integer version that begins at 1 and increments by one with
    every mutation of that resource."

    Design: Corner/entities/create_driver_record_returns_201_with_defaults
    """
    resp = api.create_driver_record(
        {"full_name": "Amy New", "date_of_birth": "1990-04-04", "state_code": "CA"}, CLERK,
    )
    record = validate_success(resp, 201)
    assert record["licensing_status"] == "UNLICENSED"
    assert record["cdl_status"] == "NONE"
    assert record["point_balance"] == 0
    assert record["real_id_status"] == "NONE"
    assert record["version"] == 1


def test_create_driver_record_missing_state_code_rejected(api):
    """PRD §3.1: "created by a LicenseClerk who supplies the driver's full_name,
    date_of_birth as an ISO YYYY-MM-DD date, and the two-letter issuing
    state_code."
    PRD §2.9: "well-formedness of the request body — required fields present ...
    with any other malformed body rejected as ERR_INVALID_REQUEST."

    Omitting the required state_code -> ERR_INVALID_REQUEST 400.

    Design: Corner/entities/create_driver_record_missing_required_field_rejected
    """
    resp = api.create_driver_record(
        {"full_name": "Bad Body", "date_of_birth": "1990-04-04"}, CLERK,
    )
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_driver_record_not_found(api):
    """PRD §2.9: "existence of every resource id named in the path or body,
    validated left to right."
    PRD §5 error catalogue: ERR_NOT_FOUND -> 404 Not Found.

    Design: Corner/entities/get_driver_record_not_found
    """
    resp = api.get_driver_record(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_driver_record_point_balance_is_server_computed(api):
    """PRD §3.7: "the record's point_balance is recomputed."
    PRD §3.7: "The point_balance is the sum of the points of all of this record's
    violations that are still in ACTIVE status and that fall within the point
    window."

    After posting a 4-point ACTIVE violation, the read shows point_balance == 4 —
    a server-owned computed dimension.

    Design: Corner/entities/driver_record_computed_point_balance_is_server_owned
    """
    record = create_driver_record(full_name="Cal Comp", date_of_birth="1990-01-01")
    get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "SPEEDING_10_OVER",
             "points": 4, "occurred_period": 0}, OFFICER,
        )
    )
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["point_balance"] == 4


def test_opt_in_sets_donor_and_voter_flags_and_bumps_version(api):
    """PRD §3.1: "The opt-in flags organ_donor and voter_registration_opt_in may
    be supplied at creation and default to false when omitted."
    PRD §3.1: "A clerk may set organ_donor and/or voter_registration_opt_in on an
    existing record; whichever flags are supplied are updated, and the record's
    version increments by one."

    Design: Corner/entities/opt_in_sets_donor_and_voter_flags
    """
    record = create_driver_record(full_name="Dee Opt", date_of_birth="1990-01-01")
    assert record["version"] == 1
    updated = validate_success(
        api.opt_in(record["id"],
                   {"organ_donor": True, "voter_registration_opt_in": True}, CLERK),
        200,
    )
    assert updated["organ_donor"] is True
    assert updated["voter_registration_opt_in"] is True
    assert updated["version"] == 2


# ===========================================================================
# Corner/endpoints
# ===========================================================================
def test_knowledge_proctor_cannot_create_driver_record(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."
    PRD §4 endpoint table: POST /driver-records is authorized for LicenseClerk.

    A KnowledgeProctor calling the LicenseClerk-only create -> 403.

    Design: Corner/endpoints/knowledge_proctor_cannot_create_driver_record
    """
    resp = api.create_driver_record(
        {"full_name": "Una NoPerm", "date_of_birth": "1986-01-01", "state_code": "CA"}, PROCTOR,
    )
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory headers: X-User-ID,
    identifying the acting operator, and X-User-Role, declaring the capacity in
    which they act. A request missing either header, or carrying a malformed
    value, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/endpoints/missing_user_context_header_rejected
    """
    resp = api.create_driver_record(
        {"full_name": "Val NoHdr", "date_of_birth": "1986-01-01", "state_code": "CA"}, {},
    )
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_list_record_violations_returns_array(api):
    """PRD §3.9: "The record's knowledge tests, road-test appointments, licenses,
    violations, suspensions, CDL endorsements, medical cards, and fee payments are
    each listable under the record."
    PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    A record with two ACTIVE violations lists both (total_count == 2).

    Design: Corner/endpoints/list_record_violations_sub_resource_returns_array
    """
    record = create_driver_record(full_name="Wes List", date_of_birth="1986-01-01")
    get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "A", "points": 2, "occurred_period": 0},
            OFFICER,
        )
    )
    get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "B", "points": 3, "occurred_period": 0},
            OFFICER,
        )
    )
    data, meta = validate_paginated(api.list_record_violations(record["id"], OFFICER))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert len(data) == 2


# ===========================================================================
# Corner/rbac
# ===========================================================================
def test_license_clerk_cannot_record_violation(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."
    PRD §4 endpoint table: POST /violations is authorized for AdjudicationOfficer.

    A LicenseClerk recording a violation (AdjudicationOfficer-only) -> 403.

    Design: Corner/rbac/license_clerk_cannot_record_violation
    """
    record = create_driver_record(full_name="Zed Peer", date_of_birth="1986-01-01")
    resp = api.create_violation(
        {"driver_record_id": record["id"], "code": "X", "points": 2, "occurred_period": 0},
        CLERK,
    )
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
