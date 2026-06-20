"""Documentation lifecycle: coding, necessity attestation, PCS signing, the
RETURNED revision loop, and the documentation-state guards.

Translates corner queue (state_machines, calculations/pcs, rbac auth/authority).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_agency_org,
    create_patient_with_coverages,
    import_transport,
    code_transport,
    import_and_code,
)
from test_helpers import factories as F
from test_helpers.test_users import make_compliance_headers


# ---------------------------------------------------------------------------
# corner / state_machines
# ---------------------------------------------------------------------------

def test_code_transport_twice_rejected(api):
    """PRD §3.3: "Coding is permitted only while the transport's `billing_status` is
    `UNBILLED`; once billing has started the transport cannot be recoded, and an
    attempt is rejected with `ERR_INVALID_DOCUMENTATION_STATE` (HTTP 409)."
    PRD §3.3: "Coding the transport advances `documentation_status` from `IMPORTED`
    to `CODED`".

    Design: Corner/state_machines/code_transport_twice_returns_invalid_documentation_state
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "RE1", "BLS", loaded_miles=10.0)
    resp = api.code_transport(t["id"], F.code_transport_payload("ALS1"), org["coder_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_DOCUMENTATION_STATE.value)


def test_attest_necessity_before_coding_rejected(api):
    """PRD §3.4: "Attestation is admitted only from `CODED` or `RETURNED`; from any
    other documentation state the request is rejected with
    `ERR_INVALID_DOCUMENTATION_STATE` (HTTP 409)."

    Design: Corner/state_machines/attest_necessity_before_coding_returns_invalid_documentation_state
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "ATT1", loaded_miles=10.0, emergency_indicator=True)
    resp = api.attest_necessity(t["id"], org["coder_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_DOCUMENTATION_STATE.value)


def test_return_documentation_revision_loop_then_reattest(api):
    """PRD §3.4: "the compliance officer may return the documentation for revision,
    advancing `documentation_status` from `NECESSITY_REVIEW` to `RETURNED` and
    resetting `medical_necessity_met` to false."
    PRD §3.4: "the revision loop in which the coder re-attests to return the
    transport to `NECESSITY_REVIEW`."

    Design: Corner/state_machines/return_documentation_revision_loop_then_reattest
    """
    org = setup_agency_org()
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "LOOP1", "ALS1", loaded_miles=12.0)
    get_success_data(api.attest_necessity(t["id"], org["coder_h"]))
    get_success_data(api.return_documentation(t["id"], org["compliance_h"]))
    reattested = get_success_data(api.attest_necessity(t["id"], org["coder_h"]))
    assert reattested["documentation_status"] == "NECESSITY_REVIEW"
    assert reattested["medical_necessity_met"] is True


# ---------------------------------------------------------------------------
# corner / calculations  (PCS requirement)
# ---------------------------------------------------------------------------

def test_pcs_not_required_for_emergency_scene_run(api):
    """PRD §3.4: "if the transport's `emergency_indicator` is true the requirement is
    `NOT_REQUIRED`".
    PRD §3.4: "when the requirement is `NOT_REQUIRED`, the step still completes and
    leaves `pcs_signed` false. Either way the transport reaches
    `DOCUMENTATION_COMPLETE`".

    Design: Corner/calculations/pcs_not_required_for_emergency_scene_run
    """
    org = setup_agency_org()
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "PCS1", "ALS1", origin_modifier="S",
                        destination_modifier="H", loaded_miles=12.0, emergency_indicator=True)
    get_success_data(api.attest_necessity(t["id"], org["coder_h"]))
    signed = get_success_data(api.sign_pcs(t["id"], org["compliance_h"]))
    assert signed["documentation_status"] == "DOCUMENTATION_COMPLETE"
    assert signed["pcs_signed"] is False


# ---------------------------------------------------------------------------
# corner / rbac  (auth, authorization, PCS authority)
# ---------------------------------------------------------------------------

def test_dispatcher_cannot_code_transport(api):
    """PRD §4 endpoint table: `POST /transports/{id}/code` is authorized for Coder.
    PRD §2.1: "When the headers are present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_code_transport
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "RB1", loaded_miles=10.0, emergency_indicator=True)
    resp = api.code_transport(t["id"], F.code_transport_payload("BLS"), org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_coder_cannot_sign_pcs(api):
    """PRD §4 endpoint table: `POST /transports/{id}/sign-pcs` is authorized for
    ComplianceOfficer.
    PRD §2.1: "When the headers are present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/coder_cannot_sign_pcs
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "RC1", "BLS", loaded_miles=10.0)
    get_success_data(api.attest_necessity(t["id"], org["coder_h"]))
    resp = api.sign_pcs(t["id"], org["coder_h"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than the three bootstrap-open creation
    endpoints must be authenticated through two mandatory HTTP headers."
    PRD §2.1: "When either header is missing or invalid on a protected endpoint,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "RA1", loaded_miles=10.0, emergency_indicator=True)
    resp = api.code_transport(t["id"], F.code_transport_payload("BLS"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_pcs_authority_required_for_signer_without_authority(api):
    """PRD §3.4: "This step requires that the acting `AgencyStaff` member hold
    `pcs_signature_authority` equal to true; a compliance officer lacking that
    authority is rejected with `ERR_PCS_AUTHORITY_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/pcs_authority_required_for_signer_without_authority
    """
    org = setup_agency_org()  # default compliance officer with authority unused here
    pat = create_patient_with_coverages(org, [])
    # Register a compliance officer WITHOUT pcs_signature_authority.
    no_auth = get_success_data(api.create_staff(
        F.create_staff_payload(org["agency"]["id"], "ComplianceOfficer",
                               full_name="No Auth", pcs_signature_authority=False), org["admin_h"]))
    no_auth_h = make_compliance_headers(no_auth["id"])
    t = import_and_code(org, pat["id"], "PA1", "BLS", loaded_miles=10.0)
    get_success_data(api.attest_necessity(t["id"], org["coder_h"]))
    resp = api.sign_pcs(t["id"], no_auth_h)
    validate_error(resp, ApiErrorId.ERR_PCS_AUTHORITY_REQUIRED.value)
