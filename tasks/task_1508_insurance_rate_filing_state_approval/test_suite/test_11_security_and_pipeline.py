"""Authentication, role authorization, and validation-pipeline ordering
(PRD §2.1, §2.8, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_product_payload,
    validate_error,
)
from test_helpers import fixtures as fx


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request that arrives without both headers present and
    well-formed is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    res = api.create_product(create_product_payload(), headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_existence_check_precedes_state_check(api):
    """PRD §2.8: "fourth, the existence of every resource referenced by path
    identifiers and body foreign keys, resolved left to right, with the first
    unresolvable reference rejected as `ERR_NOT_FOUND` (HTTP 404); fifth, the
    optimistic-concurrency version check of §2.7 where the endpoint declares
    one; sixth, whether the target resource is in a state from which the
    requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409)".

    Design: Corner/validations/existence_beats_state_priority
    """
    res = api.submit_filing(NON_EXISTENT_UUID, fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_analyst_cannot_approve_filing(api):
    """PRD §2.1: "Once identified, the caller's role must be authorized for the
    target operation; an attempt to perform an action outside the role's
    designated permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: `POST /filings/{filingId}/approve` — "StateRegulator".

    Design: Corner/rbac/rbac_analyst_cannot_approve_filing
    """
    res = api.approve_filing(NON_EXISTENT_UUID, fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_regulator_cannot_create_filing(api):
    """PRD §2.1: "an attempt to perform an action outside the role's
    designated permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: `POST /filings` — "FilingAnalyst".

    Design: Corner/rbac/rbac_regulator_cannot_create_filing
    """
    res = api.create_filing(
        {
            "product_id": NON_EXISTENT_UUID,
            "state_code": "CA",
            "filing_type": "RATE_CHANGE",
            "proposed_change_pct": 0.10,
            "proposed_effective_date": "2026-10-01",
            "indication_id": NON_EXISTENT_UUID,
        },
        fx.REGULATOR,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_actuary_cannot_release_wave(api):
    """PRD §2.1: "an attempt to perform an action outside the role's
    designated permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: `POST /waves/{waveId}/release` — "ImplementationLead".

    Design: Corner/rbac/rbac_actuary_cannot_release_wave
    """
    res = api.release_wave(NON_EXISTENT_UUID, fx.ACT1)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_regulator_cannot_submit_response(api):
    """PRD §2.1: "an attempt to perform an action outside the role's
    designated permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: `POST /responses/{responseId}/submit` — "ComplianceOfficer".

    Design: Corner/rbac/rbac_regulator_cannot_submit_response
    """
    res = api.submit_response(NON_EXISTENT_UUID, fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_officer_cannot_set_clock(api):
    """PRD §2.4: "the only way time advances is through an admin-only,
    test-driving capability restricted to `PlatformAdmin`".
    PRD §2.1: "an attempt to perform an action outside the role's designated
    permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_officer_cannot_set_clock
    """
    res = api.set_clock("2026-09-01T00:00:00Z", fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
