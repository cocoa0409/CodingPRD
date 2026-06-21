"""Role-based access control and optimistic concurrency on award activation.

Corner queue: rbac section (peer-role exclusivity, entity-backed ownership,
unauthenticated) and cross_cutting_complexity_layers OCC instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_veteran_headers,
    make_unauthenticated_headers,
    create_veteran,
    create_school,
    create_rated_claim,
    create_granted_claim,
    create_claim,
    submit_enrollment,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]
RATER = TEST_USERS["rating_specialist_headers"]


# ─── Corner / rbac ────────────────────────────────────────────────────────

def test_rating_specialist_cannot_grant_claim(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: the grant action is authorized for ClaimsAdmin only — the routing
    table lists "POST /claims/{claimId}/grant ... ClaimsAdmin".

    Design: Corner/rbac/rating_specialist_cannot_grant_claim
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim, _ = create_rated_claim(vet["id"], [{"proposed_rating_pct": 40}])
    res = api.grant_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, RATER
    )
    validate_error(res, "ERR_FORBIDDEN", 403)
    still = validate_success(api.get_claim(claim["id"], ADMIN), 200)
    assert still["status"] == "RATED"


def test_claims_admin_cannot_rate_claim(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.4: "When development is complete, a rating examiner rates the claim".

    Design: Corner/rbac/claims_admin_cannot_rate_claim
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim = create_claim(vet["id"])
    get_success_data(
        api.add_condition(
            claim["id"],
            {"veteran_id": vet["id"], "diagnostic_code": "5260", "proposed_rating_pct": 40},
            RATER,
        )
    )
    get_success_data(api.open_development(claim["id"], ADMIN))
    res = api.rate_claim(claim["id"], ADMIN)  # ClaimsAdmin attempting rate
    validate_error(res, "ERR_FORBIDDEN", 403)
    still = validate_success(api.get_claim(claim["id"], ADMIN), 200)
    assert still["status"] == "DEVELOPMENT"


def test_veteran_cannot_act_on_other_veterans_enrollment(api):
    """PRD §2.1: "a veteran may only act on resources that belong to them. For any
    resource that carries a `veteran_id` — a `Claim`, a `Condition`, a
    `Dependent`, an `Enrollment`, or a `VocRehabPlan` — ownership is checked by
    comparing that resource's `veteran_id` to `X-User-ID` ... A `Veteran`
    attempting to read or mutate another veteran's data is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/veteran_cannot_act_on_other_veterans_enrollment
    """
    vet_a = create_veteran(total_active_duty_days=1095)
    vet_b = create_veteran(total_active_duty_days=1095)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet_a["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    # Veteran B attempts to cancel Veteran A's enrollment.
    res = api.cancel_enrollment(enr["id"], make_veteran_headers(vet_b["id"]))
    validate_error(res, "ERR_FORBIDDEN", 403)
    still = validate_success(api.get_enrollment(enr["id"], ADMIN), 200)
    assert still["status"] == "SUBMITTED"


def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    these four declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    res = api.list_veterans(make_unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


# ─── Corner / cross_cutting_complexity_layers (OCC) ───────────────────────

def test_occ_stale_veteran_version_on_activate(api):
    """PRD §2.6: "If a grant has advanced the veteran's version since the operator
    last read the record, an activation that still carries the pre-cascade value
    is operating on a stale view of the award amount; the request is therefore
    rejected with `ERR_STALE_VERSION` at HTTP status 412, forcing the operator to
    re-read the freshly computed compensation before committing the award."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_veteran_version_on_activate
    """
    vet = create_veteran(total_active_duty_days=1095)
    stale_version = vet["version"]
    # Grant a claim — cascade bumps the veteran's version.
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    res = api.activate_award(
        vet["id"], {"expected_veteran_version": stale_version}, ADMIN
    )
    validate_error(res, "ERR_STALE_VERSION", 412)
    still = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert still["award_status"] == "DRAFT"


def test_occ_correct_veteran_version_succeeds(api):
    """PRD §3.9: "A claims officer activates the monthly award, moving
    `award_status` from `DRAFT` to `ACTIVE`. Activation is permitted only when the
    award is in `DRAFT` status, requires the veteran's `combined_rating_pct` to be
    strictly greater than 0 (otherwise `ERR_NO_COMPENSABLE_RATING`), and requires
    `expected_veteran_version` to match the veteran's current `version` (otherwise
    `ERR_STALE_VERSION`, as detailed in §2.6)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_veteran_version_succeeds
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    fresh = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    activated = validate_success(
        api.activate_award(
            vet["id"], {"expected_veteran_version": fresh["version"]}, ADMIN
        ),
        200,
    )
    assert activated["award_status"] == "ACTIVE"
