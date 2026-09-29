"""Authentication and role authorization: rejection-ladder positions 1-3.

Position 1  ERR_MISSING_AUTH_HEADERS (401) - X-User-ID / X-User-Role absent or blank
Position 2  ERR_UNKNOWN_ROLE         (401) - X-User-Role outside the six roles
Position 3  ERR_ROLE_NOT_PERMITTED   (403) - role not in the endpoint's authorized set
"""
from flask import request

from errors import fail

CATASTROPHE_MANAGER = "CatastropheManager"
DEPLOYMENT_COORDINATOR = "DeploymentCoordinator"
CLAIMS_EXAMINER = "ClaimsExaminer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
ADJUSTER = "Adjuster"
VENDOR_COORDINATOR = "VendorCoordinator"

KNOWN_ROLES = {
    CATASTROPHE_MANAGER, DEPLOYMENT_COORDINATOR, CLAIMS_EXAMINER,
    COMPLIANCE_OFFICER, ADJUSTER, VENDOR_COORDINATOR,
}

CM = CATASTROPHE_MANAGER
DC = DEPLOYMENT_COORDINATOR
CE = CLAIMS_EXAMINER
CO = COMPLIANCE_OFFICER
AD = ADJUSTER
VC = VENDOR_COORDINATOR

# (METHOD, flask rule) -> frozenset of authorized roles.  Taken verbatim from
# the endpoint table in PRD section 4.
ENDPOINT_ROLES = {
    ("POST", "/_clock/set_current_utc"): {CM, DC, CE, CO, VC, AD},

    ("POST", "/catastrophe-events"): {CM},
    ("GET", "/catastrophe-events"): {CM, DC, CE, CO, VC},
    ("GET", "/catastrophe-events/<event_id>"): {CM, DC, CE, CO, VC},
    ("POST", "/catastrophe-events/<event_id>/declare"): {CM},
    ("POST", "/catastrophe-events/<event_id>/activate-surge"): {CM},
    ("POST", "/catastrophe-events/<event_id>/demobilize"): {CM},
    ("POST", "/catastrophe-events/<event_id>/close"): {CM},

    ("POST", "/regulatory-bulletins"): {CO},
    ("GET", "/regulatory-bulletins"): {CO, CM, CE},
    ("GET", "/regulatory-bulletins/<bulletin_id>"): {CO, CM, CE},
    ("POST", "/regulatory-bulletins/<bulletin_id>/activate"): {CO},
    ("POST", "/regulatory-bulletins/<bulletin_id>/withdraw"): {CO},

    ("POST", "/adjusters"): {DC},
    ("GET", "/adjusters"): {DC, CM, CE, CO},
    ("GET", "/adjusters/<adjuster_id>"): {DC, CM, CE, CO, AD},
    ("POST", "/adjusters/<adjuster_id>/set-unavailable"): {DC},
    ("POST", "/adjusters/<adjuster_id>/set-available"): {DC},
    ("POST", "/adjusters/<adjuster_id>/apply-license-waiver"): {CO},

    ("POST", "/housing-blocks"): {DC},
    ("GET", "/housing-blocks"): {DC, CM},
    ("GET", "/housing-blocks/<housing_block_id>"): {DC, CM},
    ("POST", "/housing-blocks/<housing_block_id>/open"): {DC},
    ("POST", "/housing-blocks/<housing_block_id>/release"): {DC},

    ("POST", "/deployments"): {DC},
    ("GET", "/deployments"): {DC, CM, AD},
    ("GET", "/deployments/<deployment_id>"): {DC, CM, AD},
    ("POST", "/deployments/<deployment_id>/confirm"): {DC},
    ("POST", "/deployments/<deployment_id>/check-in"): {DC},
    ("POST", "/deployments/<deployment_id>/demobilize"): {DC},
    ("POST", "/deployments/<deployment_id>/cancel"): {DC},

    ("POST", "/claims"): {CE},
    ("GET", "/claims"): {CE, CM, CO, DC},
    ("GET", "/claims/<claim_id>"): {CE, CM, CO, AD, VC},
    ("POST", "/claims/<claim_id>/assign-cat-code"): {CE},
    ("POST", "/claims/<claim_id>/triage"): {CE},
    ("POST", "/claims/<claim_id>/close"): {CE},
    ("POST", "/claims/<claim_id>/reopen"): {CE},
    ("POST", "/claims/<claim_id>/reserve-entries"): {CE},

    ("GET", "/reserve-entries"): {CE, CM, CO},
    ("GET", "/reserve-entries/<reserve_entry_id>"): {CE, CM, CO},

    ("POST", "/inspection-assignments"): {DC},
    ("GET", "/inspection-assignments"): {DC, CE, CM, AD},
    ("GET", "/inspection-assignments/<assignment_id>"): {DC, CE, CM, AD},
    ("POST", "/inspection-assignments/<assignment_id>/start"): {AD},
    ("POST", "/inspection-assignments/<assignment_id>/complete"): {AD},
    ("POST", "/inspection-assignments/<assignment_id>/report-no-access"): {AD},
    ("POST", "/inspection-assignments/<assignment_id>/cancel"): {DC},

    ("POST", "/advance-payments"): {CE},
    ("GET", "/advance-payments"): {CE, CM, CO},
    ("GET", "/advance-payments/<advance_id>"): {CE, CM, CO},
    ("POST", "/advance-payments/<advance_id>/void"): {CE},

    ("POST", "/vendor-firms"): {VC},
    ("GET", "/vendor-firms"): {VC, CE, CM},
    ("GET", "/vendor-firms/<vendor_firm_id>"): {VC, CE, CM},
    ("POST", "/vendor-firms/<vendor_firm_id>/activate"): {VC},
    ("POST", "/vendor-firms/<vendor_firm_id>/suspend"): {VC},

    ("POST", "/vendor-assignments"): {CE},
    ("GET", "/vendor-assignments"): {VC, CE, CM},
    ("GET", "/vendor-assignments/<vendor_assignment_id>"): {VC, CE, CM},
    ("POST", "/vendor-assignments/<vendor_assignment_id>/accept"): {VC},
    ("POST", "/vendor-assignments/<vendor_assignment_id>/decline"): {VC},
    ("POST", "/vendor-assignments/<vendor_assignment_id>/complete"): {VC},
    ("POST", "/vendor-assignments/<vendor_assignment_id>/cancel"): {CE},

    ("POST", "/loss-estimates"): {CM},
    ("GET", "/loss-estimates"): {CM, CE, CO},
    ("GET", "/loss-estimates/<snapshot_id>"): {CM, CE, CO},

    ("POST", "/file-transfer-batches"): {CE},
    ("GET", "/file-transfer-batches"): {CE, CM},
    ("GET", "/file-transfer-batches/<batch_id>"): {CE, CM},
    ("POST", "/file-transfer-batches/<batch_id>/claims"): {CE},
    ("POST", "/file-transfer-batches/<batch_id>/submit"): {CE},
    ("POST", "/file-transfer-batches/<batch_id>/accept"): {CM},
    ("POST", "/file-transfer-batches/<batch_id>/reject"): {CM},
    ("POST", "/file-transfer-batches/<batch_id>/reopen-batch"): {CE},
}


def current_user():
    return request.environ.get("cat.user_id")


def current_role():
    return request.environ.get("cat.role")


def enforce():
    """Ladder positions 1-3.  Called on every business request."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None \
            or not str(user_id).strip() or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in KNOWN_ROLES:
        fail("ERR_UNKNOWN_ROLE")
    rule = request.url_rule
    allowed = ENDPOINT_ROLES.get((request.method, str(rule.rule))) if rule else None
    if allowed is None:
        allowed = KNOWN_ROLES
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
    request.environ["cat.user_id"] = user_id
    request.environ["cat.role"] = role
    return user_id, role
