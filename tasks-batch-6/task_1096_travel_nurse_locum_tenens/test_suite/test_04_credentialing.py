"""License verification lifecycle and credential-packet RBAC / segregation of duties."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_clinician_headers,
    create_license_payload, create_credential_item_payload,
)
from test_helpers.fixtures import (
    provision, set_clock, create_clinician, get_packet_data, get_assignment_data,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]
CS2 = TEST_USERS["credentialing_specialist_2_headers"]


def test_license_starts_pending_and_verify_stamps_actor_and_clock(api):
    """PRD §3.1: "A newly filed license is created in PENDING_VERIFICATION."
    PRD §3.1: "Moving a PENDING_VERIFICATION or SUSPENDED license to VERIFIED records
    verified_by_user_id (the specialist's operator id) and stamps verified_at from the
    logical clock."

    Design: Corner/state_machines/corner_license_starts_pending_and_verify_stamps_actor_and_clock
    """
    set_clock(api, "2026-05-10T09:30:00Z")
    clin = create_clinician(api)
    lic = validate_success(api.create_license(create_license_payload(clin["id"]), RECRUITER), 201)
    assert lic["status"] == "PENDING_VERIFICATION" and lic["version"] == 1
    out = validate_success(api.transition_license(lic["id"], "VERIFIED", CS1), 200)
    assert out["status"] == "VERIFIED"
    assert out["verified_by_user_id"] == "cs-1"
    assert out["verified_at"] == "2026-05-10T09:30:00.000Z"
    assert out["version"] == 2


def test_license_expired_is_terminal_and_rejects_further_transition(api):
    """PRD §3.1: "A VERIFIED license may be moved to SUSPENDED ... or moved to the
    terminal EXPIRED state. Any requested license transition that is not an outgoing
    edge of the license's current state is rejected with ERR_INVALID_TRANSITION."

    Design: Corner/state_machines/corner_license_expired_is_terminal_and_rejects_further_transition
    """
    clin = create_clinician(api)
    lic = validate_success(api.create_license(create_license_payload(clin["id"]), RECRUITER), 201)
    validate_success(api.transition_license(lic["id"], "VERIFIED", CS1), 200)
    validate_success(api.transition_license(lic["id"], "EXPIRED", CS1), 200)
    validate_error(api.transition_license(lic["id"], "VERIFIED", CS1), ApiErrorId.ERR_INVALID_TRANSITION.value)
    licenses, _ = validate_paginated(api.list_clinician_licenses(clin["id"], RECRUITER))
    assert licenses[0]["status"] == "EXPIRED"


def test_license_transition_unknown_id_not_found(api):
    """PRD §2.10: "if a parent id in the path does not resolve, the corresponding
    not-found error is returned before any child filtering is attempted. Which error
    surfaces depends on which resource the unresolved id addresses: ...
    ERR_LICENSE_NOT_FOUND ..."

    Design: Corner/errors/corner_license_transition_unknown_id_not_found
    """
    resp = api.transition_license("99999999-8888-4777-8666-555555555555", "VERIFIED", CS1)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND.value)


def test_clinician_cannot_verify_credential_items(api):
    """PRD §3.4: "A new item is created in PENDING and its verification status moves
    through VERIFIED, REJECTED, REVOKED, or EXPIRED. A CredentialingSpecialist drives
    one item by supplying a target to ..."
    PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    invoke the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/corner_clinician_cannot_verify_credential_items
    """
    ctx = provision(api)  # DRAFT assignment, DRAFT packet
    clin_headers = make_clinician_headers(ctx.clin_id)
    item = validate_success(api.create_credential_item(
        ctx.pkt_id, create_credential_item_payload("BLS_CERT"), clin_headers), 201)
    resp = api.transition_credential_item(item["id"], "VERIFIED", clin_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["blocking_item_count_start_basis"] == 5


def test_clinician_cannot_submit_another_clinicians_packet(api):
    """PRD §2.1: "a Clinician may only act on an assignment whose clinician_id equals its
    X-User-ID ...; a mismatch yields ERR_OWNERSHIP_VIOLATION (HTTP 403). This ownership
    check runs on ... credential-packet transitions."

    Design: Corner/rbac/corner_clinician_cannot_submit_another_clinicians_packet
    """
    ctx = provision(api)  # Ada owns the assignment/packet
    other = create_clinician(api, full_name="Ben Osei")
    resp = api.transition_credential_packet(ctx.pkt_id, "SUBMITTED", make_clinician_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["status"] == "DRAFT" and pkt["submitted_by_user_id"] is None


def test_same_specialist_cannot_submit_and_clear_one_packet(api):
    """PRD §3.4: "Clearing a packet requires that it is UNDER_REVIEW, that
    blocking_item_count_start_basis is 0 under the start-date basis (else
    ERR_PACKET_NOT_CLEARED), and that the acting X-User-ID differs from the packet's
    submitted_by_user_id (else ERR_SEGREGATION_OF_DUTIES). On clearance the packet
    records cleared_by_user_id, and the effect bubbles up to the assignment's compliance
    dimension: compliance_status advances from PENDING_CREDENTIALS ... to CLEARED, leaving
    staffing_status untouched."

    Design: Corner/rbac/corner_same_specialist_cannot_submit_and_clear_one_packet
    """
    ctx = provision(api, add_items=True, verify_items=True, packet_stage="under_review",
                    submitter_headers=CS1)
    pkt = get_packet_data(api, ctx.pkt_id)
    assert pkt["submitted_by_user_id"] == "cs-1" and pkt["blocking_item_count_start_basis"] == 0
    # cs-1 both submitted and reviewed -> cannot clear.
    validate_error(api.transition_credential_packet(ctx.pkt_id, "CLEARED", CS1),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert get_packet_data(api, ctx.pkt_id)["status"] == "UNDER_REVIEW"
    # cs-2 clears successfully.
    out = validate_success(api.transition_credential_packet(ctx.pkt_id, "CLEARED", CS2), 200)
    assert out["status"] == "CLEARED" and out["cleared_by_user_id"] == "cs-2"
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["compliance_status"] == "CLEARED" and asg["staffing_status"] == "DRAFT"
