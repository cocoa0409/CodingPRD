"""Pre-built role headers for the six roles the PRD declares.

Four roles carry an opaque identity — ``ProjectCoordinator``, ``FieldTechnician``,
``LicensedSiteProfessional`` and ``ComplianceOfficer`` — so a shared constant is
their canonical form.  Two roles are entity-backed and therefore have no
meaningful shared constant: a ``LabAnalyst``'s ``X-User-ID`` is the ``id`` of the
acting ``Laboratory``, and a ``Homeowner``'s ``X-User-ID`` is the ``id`` of the
acting ``Property``.  Calls made as those two roles MUST build headers from the
real row id via :func:`make_lab_analyst_headers` and
:func:`make_homeowner_headers`; the shared placeholder below never matches a
real row and so fails every ownership comparison.

Two distinct ``LicensedSiteProfessional`` identities are provided because
closure-letter issuance requires the signer to differ from the drafter.
"""
from prd_bench_local_runner.testing import build_user_headers

PROJECT_COORDINATOR_USER_ID = "pc-1"
SECOND_PROJECT_COORDINATOR_USER_ID = "pc-2"
FIELD_TECHNICIAN_USER_ID = "ft-1"
SECOND_FIELD_TECHNICIAN_USER_ID = "ft-2"
#: The drafting licensed site professional.
LSP_DRAFTER_USER_ID = "lsp-1"
#: The second licensed site professional, who signs what the first drafted.
LSP_SIGNER_USER_ID = "lsp-2"
COMPLIANCE_OFFICER_USER_ID = "co-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "co-2"

#: Placeholder identity for the two entity-backed roles, usable only where the
#: call under test is rejected before any ownership comparison happens.
PLACEHOLDER_ENTITY_USER_ID = "00000000-0000-4000-8000-0000000000ff"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "project_coordinator_headers": build_user_headers(
        PROJECT_COORDINATOR_USER_ID, "ProjectCoordinator"
    ),
    "second_project_coordinator_headers": build_user_headers(
        SECOND_PROJECT_COORDINATOR_USER_ID, "ProjectCoordinator"
    ),
    "field_technician_headers": build_user_headers(
        FIELD_TECHNICIAN_USER_ID, "FieldTechnician"
    ),
    "second_field_technician_headers": build_user_headers(
        SECOND_FIELD_TECHNICIAN_USER_ID, "FieldTechnician"
    ),
    "lsp_drafter_headers": build_user_headers(
        LSP_DRAFTER_USER_ID, "LicensedSiteProfessional"
    ),
    "lsp_signer_headers": build_user_headers(
        LSP_SIGNER_USER_ID, "LicensedSiteProfessional"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    # Entity-backed roles — placeholders for non-owned calls only.
    "lab_analyst_headers": build_user_headers(
        PLACEHOLDER_ENTITY_USER_ID, "LabAnalyst"
    ),
    "homeowner_headers": build_user_headers(
        PLACEHOLDER_ENTITY_USER_ID, "Homeowner"
    ),
}

PROJECT_COORDINATOR = TEST_USERS["project_coordinator_headers"]
PROJECT_COORDINATOR_2 = TEST_USERS["second_project_coordinator_headers"]
FIELD_TECHNICIAN = TEST_USERS["field_technician_headers"]
FIELD_TECHNICIAN_2 = TEST_USERS["second_field_technician_headers"]
LSP_DRAFTER = TEST_USERS["lsp_drafter_headers"]
LSP_SIGNER = TEST_USERS["lsp_signer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_OFFICER_2 = TEST_USERS["second_compliance_officer_headers"]


def make_project_coordinator_headers(user_id: str) -> dict:
    """For a ProjectCoordinator acting under a specific operator identifier."""
    return build_user_headers(user_id, "ProjectCoordinator")


def make_field_technician_headers(user_id: str) -> dict:
    """For a FieldTechnician acting under a specific operator identifier.

    The identifier is recorded as ``collected_by_user_id`` on a soil sample.
    """
    return build_user_headers(user_id, "FieldTechnician")


def make_lsp_headers(user_id: str) -> dict:
    """For a LicensedSiteProfessional acting under a specific identifier.

    The identifier is recorded as ``requested_by_user_id`` on a change order and
    as ``drafted_by_user_id`` or ``issued_by_user_id`` on a closure letter.
    """
    return build_user_headers(user_id, "LicensedSiteProfessional")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For a ComplianceOfficer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_lab_analyst_headers(laboratory_id: str) -> dict:
    """For a LabAnalyst: pass the acting ``Laboratory``'s own ``id``.

    Every sample ownership check compares the sample's ``laboratory_id`` against
    ``X-User-ID``, so a laboratory-facing call must carry the real row id.
    """
    return build_user_headers(laboratory_id, "LabAnalyst")


def make_homeowner_headers(property_id: str) -> dict:
    """For a Homeowner: pass the acting ``Property``'s own ``id``.

    Every homeowner ownership check compares the ``property_id`` of the addressed
    project — or of the project behind the addressed disclosure or letter —
    against ``X-User-ID``, so an owned call must carry the real property row id.
    """
    return build_user_headers(property_id, "Homeowner")


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/identifier pair, including undeclared roles."""
    return build_user_headers(user_id, role)


def headers_without_identity() -> dict:
    """Headers carrying neither ``X-User-ID`` nor ``X-User-Role``."""
    return {"Content-Type": "application/json"}
