"""Auth (PRD 2.1), RBAC, path resolution (PRD 2.9) and account scoping (PRD 2.10 #4)."""

import functools

from flask import g, request

import errors
from db import store
from errors import ApiError

UNDERWRITER = "Underwriter"
CLAIMS_ADJUSTER = "ClaimsAdjuster"
PORTFOLIO_ACTUARY = "PortfolioActuary"
PANEL_ADMIN = "PanelAdmin"
INSURED = "Insured"

ALL_ROLES = (UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED)


def endpoint(roles=None, anonymous=False):
    """Decorator enforcing precedence steps 1 and 2 before anything else runs."""

    allowed = tuple(roles or ())

    def decorate(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            g.touched_rows = set()
            if anonymous:
                g.user_id = request.headers.get("X-User-ID")
                g.role = request.headers.get("X-User-Role")
                return view(*args, **kwargs)
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not user_id.strip() or role is None or not role.strip():
                raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                               "X-User-ID and X-User-Role headers are required")
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError(errors.ERR_UNAUTHORIZED, 403,
                               "role %s may not call this endpoint" % role)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapped

    return decorate


def is_insured():
    return getattr(g, "role", None) == INSURED


# --------------------------------------------------------------------------
# path / body resolution
# --------------------------------------------------------------------------

def _find(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id, 404, "not found")
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, 404, "not found")
    return row


def find_account(account_id):
    return _find(store.insured_accounts, account_id, errors.ERR_INSURED_ACCOUNT_NOT_FOUND)


def find_application(application_id):
    return _find(store.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND)


def find_attestation(attestation_id):
    # PRD 2.9: no attestation-specific 404 exists, so it reports the application error.
    return _find(store.control_attestations, attestation_id, errors.ERR_APPLICATION_NOT_FOUND)


def find_scan(scan_id):
    return _find(store.external_scans, scan_id, errors.ERR_EXTERNAL_SCAN_NOT_FOUND)


def find_policy(policy_id):
    return _find(store.policies, policy_id, errors.ERR_POLICY_NOT_FOUND)


def find_section(section_id):
    return _find(store.coverage_sections, section_id, errors.ERR_COVERAGE_SECTION_NOT_FOUND)


def find_vendor(vendor_id):
    return _find(store.panel_vendors, vendor_id, errors.ERR_PANEL_VENDOR_NOT_FOUND)


def find_claim(claim_id):
    return _find(store.incident_claims, claim_id, errors.ERR_INCIDENT_CLAIM_NOT_FOUND)


def find_engagement(engagement_id):
    return _find(store.vendor_engagements, engagement_id, errors.ERR_VENDOR_ENGAGEMENT_NOT_FOUND)


def find_proof(proof_id):
    return _find(store.proofs_of_loss, proof_id, errors.ERR_PROOF_OF_LOSS_NOT_FOUND)


def find_payment(payment_id):
    return _find(store.claim_payments, payment_id, errors.ERR_CLAIM_PAYMENT_NOT_FOUND)


def find_assessment(assessment_id):
    return _find(store.renewal_assessments, assessment_id, errors.ERR_RENEWAL_ASSESSMENT_NOT_FOUND)


def find_scenario(scenario_id):
    return _find(store.systemic_scenarios, scenario_id, errors.ERR_SYSTEMIC_SCENARIO_NOT_FOUND)


# --------------------------------------------------------------------------
# ownership (transitive through the parent chain)
# --------------------------------------------------------------------------

def owner_of_application(application):
    return application["insured_account_id"]


def owner_of_policy(policy):
    return policy["insured_account_id"]


def owner_of_claim(claim):
    policy = store.policies.get(claim["policy_id"])
    return policy["insured_account_id"] if policy else None


def owner_of_engagement(engagement):
    claim = store.incident_claims.get(engagement["incident_claim_id"])
    return owner_of_claim(claim) if claim else None


def owner_of_proof(proof):
    claim = store.incident_claims.get(proof["incident_claim_id"])
    return owner_of_claim(claim) if claim else None


def owner_of_payment(payment):
    claim = store.incident_claims.get(payment["incident_claim_id"])
    return owner_of_claim(claim) if claim else None


def owner_of_section(section):
    policy = store.policies.get(section["policy_id"])
    return policy["insured_account_id"] if policy else None


def owner_of_assessment(assessment):
    policy = store.policies.get(assessment["policy_id"])
    return policy["insured_account_id"] if policy else None


def owner_of_attestation(attestation):
    application = store.applications.get(attestation["application_id"])
    return owner_of_application(application) if application else None


def owner_of_scan(scan):
    application = store.applications.get(scan["application_id"])
    return owner_of_application(application) if application else None


def scope_guard(owner_account_id):
    """Precedence step 4 -- Insured callers only touch their own account's rows."""
    if not is_insured():
        return
    if owner_account_id != g.user_id:
        raise ApiError(errors.ERR_ACCOUNT_SCOPE_VIOLATION, 403,
                       "this row belongs to another insured account")


def scoped_filter(rows, owner_fn):
    """Force-filter a list to the Insured caller's own account."""
    if not is_insured():
        return rows
    return [row for row in rows if owner_fn(row) == g.user_id]


def guard_account_filter(param_name="insured_account_id"):
    """An Insured supplying a conflicting owner filter on a list endpoint is 403."""
    if not is_insured():
        return
    supplied = request.args.get(param_name)
    if supplied is not None and supplied != g.user_id:
        raise ApiError(errors.ERR_ACCOUNT_SCOPE_VIOLATION, 403,
                       "an Insured may only list its own account's rows")
