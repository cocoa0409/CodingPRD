"""The two independent Assignment dimensions, the depth-4 credential-revocation cascade,
the compliance-suspension work guard, and the remaining RBAC / authentication corners."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_clinician_headers, make_facility_manager_headers,
    raw_headers, create_timesheet_payload, create_extension_payload, create_clinician_payload,
)
from test_helpers.fixtures import (
    setup_active_assignment, provision, create_clinician,
    get_assignment_data, get_packet_data, execute_contract, activate, send_contract,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


# --- Difficulty: staffing and compliance dimensions evolve independently ---
def test_compliance_clears_while_staffing_still_draft(api):
    """PRD §2.7: "The staffing_status dimension tracks the placement lifecycle ... The
    compliance_status dimension tracks credentialing posture ... and evolves entirely
    separately: a transition that advances one dimension leaves the other untouched unless
    a rule explicitly says otherwise."
    PRD §3.4: "the effect bubbles up to the assignment's compliance dimension:
    compliance_status advances from PENDING_CREDENTIALS ... to CLEARED, leaving
    staffing_status untouched."

    Design: Difficulty/non_linear_state_machine/assignment_staffing_and_compliance_dimensions_evolve_independently
    """
    ctx = provision(api, add_items=True, verify_items=True, packet_stage="cleared")
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "DRAFT" and asg["compliance_status"] == "CLEARED"
    send_contract(api, ctx.con_id)
    execute_contract(api, ctx.con_id, ctx.clin_id)
    asg2 = get_assignment_data(api, ctx.asg_id)
    assert asg2["staffing_status"] == "PENDING_START" and asg2["compliance_status"] == "CLEARED"


def test_compliance_suspends_while_staffing_stays_active(api):
    """PRD §2.7: "a transition that advances one dimension leaves the other untouched
    unless a rule explicitly says otherwise."
    PRD §3.4: "the assignment's compliance_status moves from CLEARED to SUSPENDED; and
    every open extension negotiation on that assignment ... is withdrawn"

    Design: Difficulty/non_linear_state_machine/assignment_staffing_and_compliance_dimensions_evolve_independently
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "ACTIVE" and asg["compliance_status"] == "CLEARED"
    validate_success(api.transition_credential_item(ctx.items["DRUG_SCREEN"]["id"], "REVOKED", CS1), 200)
    asg2 = get_assignment_data(api, ctx.asg_id)
    assert asg2["staffing_status"] == "ACTIVE" and asg2["compliance_status"] == "SUSPENDED"
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["status"] == "CHANGES_REQUESTED" and pkt["revision_round"] == 1


# --- Difficulty: revoke credential item cascades depth 4 ---
def test_revoke_item_cascades_to_packet_and_compliance(api):
    """PRD §3.4: "When a CredentialingSpecialist revokes or expires a previously VERIFIED
    item, the packet's readiness is recomputed, and if a required type is no longer
    satisfied on the start-date basis while the packet is CLEARED, a synchronized cascade
    fires: the packet moves from CLEARED to CHANGES_REQUESTED and its revision_round
    increments; the assignment's compliance_status moves from CLEARED to SUSPENDED"

    Design: Difficulty/transitive_cascade/revoke_credential_item_cascades_to_packet_assignment_and_extension_depth4
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    v = get_assignment_data(api, ctx.asg_id)["version"]
    validate_success(api.create_extension(
        ctx.asg_id, create_extension_payload(v, 13, 5300, 14200), RECRUITER), 201)
    lvf = ctx.items["LICENSE_VERIFICATION"]["id"]
    revoked = validate_success(api.transition_credential_item(lvf, "REVOKED", CS1), 200)
    assert revoked["status"] == "REVOKED"
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["blocking_item_count_start_basis"] == 1 and pkt["readiness_score_start_basis"] == 80
    assert pkt["blocking_item_count_full_term_basis"] == 1 and pkt["readiness_score_full_term_basis"] == 80
    assert pkt["status"] == "CHANGES_REQUESTED" and pkt["revision_round"] == 1
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["compliance_status"] == "SUSPENDED" and asg["staffing_status"] == "ACTIVE"


def test_revoke_item_withdraws_open_extension(api):
    """PRD §3.4: "and every open extension negotiation on that assignment whose status is
    PROPOSED or COUNTERED is withdrawn, each stamping its resolved_at."

    Design: Difficulty/transitive_cascade/revoke_credential_item_cascades_to_packet_assignment_and_extension_depth4
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    v = get_assignment_data(api, ctx.asg_id)["version"]
    ext = validate_success(api.create_extension(
        ctx.asg_id, create_extension_payload(v, 13, 5300, 14200), RECRUITER), 201)
    validate_success(api.transition_credential_item(ctx.items["LICENSE_VERIFICATION"]["id"], "REVOKED", CS1), 200)
    exts, _ = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    e = next(x for x in exts if x["id"] == ext["id"])
    assert e["status"] == "WITHDRAWN" and e["resolved_at"] is not None


def test_timesheet_create_rejected_while_compliance_suspended(api):
    """PRD §3.6: "A timesheet may only be filed while the parent assignment's
    staffing_status is ACTIVE (else ERR_ASSIGNMENT_NOT_ACTIVE) and its compliance_status
    is not SUSPENDED (else ERR_COMPLIANCE_SUSPENDED)."

    Design: Corner/errors/corner_timesheet_create_rejected_while_compliance_suspended
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    validate_success(api.transition_credential_item(ctx.items["DRUG_SCREEN"]["id"], "REVOKED", CS1), 200)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "ACTIVE" and asg["compliance_status"] == "SUSPENDED"
    resp = api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0]),
        make_clinician_headers(ctx.clin_id))
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_SUSPENDED.value)
    data, _ = validate_paginated(api.list_assignment_timesheets(ctx.asg_id, RECRUITER))
    assert data == []


def test_facility_manager_cannot_create_clinicians(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    invoke the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: "POST | /clinicians | Register a traveling clinician | Recruiter"

    Design: Corner/rbac/corner_facility_manager_cannot_create_clinicians
    """
    resp = api.create_clinician(create_clinician_payload(),
                                make_facility_manager_headers("77777777-8888-4999-8aaa-bbbbbbbbbbbb"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    _, meta = validate_paginated(api.list_assignments(RECRUITER))
    assert meta["total_count"] == 0


def test_request_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty, or if X-User-Role is not one of
    these six exact strings, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."
    PRD §2.8: "1. Authentication ... else ERR_UNAUTHENTICATED. 2. Authorization ... else
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_request_without_role_header_is_unauthenticated
    """
    body = create_clinician_payload()
    # Both auth headers omitted.
    validate_error(api._request("POST", "/clinicians", body, raw_headers()),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
    # Undeclared role value.
    validate_error(api._request("POST", "/clinicians", body, raw_headers("someone", "Auditor")),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
    # Well-formed but unauthorized role -> 403 (proves priority 1 precedes priority 2).
    validate_error(api.create_clinician(body, make_facility_manager_headers("fm-x")),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_timesheet_create_with_unknown_assignment_not_found(api):
    """PRD §2.10: "the same not-found errors apply to any body foreign key (for instance
    assignment_id or clinician_id) that fails to resolve."

    Design: Corner/errors/corner_timesheet_create_with_unknown_assignment_not_found
    """
    clin = create_clinician(api)
    resp = api.create_timesheet(
        create_timesheet_payload("00000000-1111-4222-8333-444444444444", "2026-06-07",
                                 [0, 12, 12, 12, 0, 0, 0]),
        make_clinician_headers(clin["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value)
