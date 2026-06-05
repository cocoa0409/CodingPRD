"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the API server (empty DB) before every test, so every helper
builds its preconditions from scratch using only PRD-declared endpoints. All
helpers use get_success_data() (lenient) so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing assertion error.

Identity threading: every Veteran created here is entity_backed. Ownership-gated
Veteran calls (submit enrollment, cancel enrollment, etc.) thread the real
Veteran.id through make_veteran_headers(veteran_id) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_veteran_payload,
    update_veteran_payload,
    create_claim_payload,
    create_condition_payload,
    create_school_payload,
    create_enrollment_payload,
    add_dependent_payload,
    create_voc_rehab_plan_payload,
    unique_file_number,
)
from .test_users import TEST_USERS, make_veteran_headers

ADMIN = TEST_USERS["claims_admin_headers"]
RATER = TEST_USERS["rating_specialist_headers"]
SCO = TEST_USERS["school_official_headers"]


# ─── Tier 1: Basic entity creation ────────────────────────────────────────

def create_veteran(total_active_duty_days=1200, file_number=None, **overrides):
    """Create a Veteran. Returns the created veteran dict (award_status=DRAFT)."""
    payload = create_veteran_payload(
        total_active_duty_days=total_active_duty_days,
        file_number=file_number or unique_file_number("FN"),
        **overrides,
    )
    return get_success_data(api_client.create_veteran(payload, ADMIN))


def create_school(**overrides):
    """Create a School. Returns the created school dict."""
    return get_success_data(
        api_client.create_school(create_school_payload(**overrides), ADMIN)
    )


def create_claim(veteran_id, **overrides):
    """Create a Claim in SUBMITTED status. Returns the created claim dict."""
    return get_success_data(
        api_client.create_claim(create_claim_payload(veteran_id, **overrides), ADMIN)
    )


# ─── Tier 2: Claim lifecycle shortcuts ────────────────────────────────────

def create_rated_claim(veteran_id, conditions, claim_type="ORIGINAL",
                       received_date="2026-01-01T00:00:00Z"):
    """Create a claim, attach `conditions`, open development, and rate it.

    `conditions` is a list of dicts; each may carry proposed_rating_pct,
    diagnostic_code, body_side, is_extremity. Returns (claim, condition_ids)
    where claim reflects RATED status (fetched fresh so version is current).
    """
    claim = create_claim(veteran_id, claim_type=claim_type, received_date=received_date)
    cond_ids = []
    for spec in conditions:
        payload = create_condition_payload(
            veteran_id, spec.get("proposed_rating_pct", 0),
            **{k: v for k, v in spec.items() if k != "proposed_rating_pct"},
        )
        cond = get_success_data(api_client.add_condition(claim["id"], payload, RATER))
        cond_ids.append(cond["id"])
    get_success_data(api_client.open_development(claim["id"], ADMIN))
    get_success_data(api_client.rate_claim(claim["id"], RATER))
    fresh = get_success_data(api_client.get_claim(claim["id"], ADMIN))
    return fresh, cond_ids


def create_granted_claim(veteran_id, conditions, claim_type="ORIGINAL",
                         received_date="2026-01-01T00:00:00Z"):
    """Create -> rate -> grant a claim, threading the fresh expected_claim_version.

    Returns (claim, condition_ids) with claim reflecting GRANTED status. The grant
    cascade has already run, so the veteran's combined_rating_pct /
    monthly_compensation_cents are finalized.
    """
    claim, cond_ids = create_rated_claim(
        veteran_id, conditions, claim_type=claim_type, received_date=received_date
    )
    get_success_data(
        api_client.grant_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, ADMIN
        )
    )
    fresh = get_success_data(api_client.get_claim(claim["id"], ADMIN))
    return fresh, cond_ids


def veteran_with_granted_rating(rating_pct, total_active_duty_days=1200,
                                file_number=None):
    """Create a veteran and grant a single condition at `rating_pct`.

    Returns the veteran fetched fresh after the grant cascade (combined_rating_pct
    reflects the granted single condition). Used wherever a test needs a veteran at
    a known combined rating.
    """
    vet = create_veteran(
        total_active_duty_days=total_active_duty_days, file_number=file_number
    )
    create_granted_claim(vet["id"], [{"proposed_rating_pct": rating_pct}])
    return get_success_data(api_client.get_veteran(vet["id"], ADMIN))


# ─── Tier 3: Dependents ───────────────────────────────────────────────────

def add_dependent(veteran_id, relationship, **overrides):
    """Add a dependent to a veteran (ClaimsAdmin path). Returns the dependent dict."""
    return get_success_data(
        api_client.add_dependent(
            veteran_id, add_dependent_payload(relationship, **overrides), ADMIN
        )
    )


# ─── Tier 4: Enrollment lifecycle shortcuts ───────────────────────────────

def submit_enrollment(veteran_id, school_id, **overrides):
    """Submit an enrollment as the owning veteran (ownership-gated). Returns the
    enrollment dict in SUBMITTED status."""
    payload = create_enrollment_payload(veteran_id, school_id, **overrides)
    return get_success_data(
        api_client.create_enrollment(payload, make_veteran_headers(veteran_id))
    )


def certify_enrollment(enrollment):
    """Certify a SUBMITTED enrollment, threading its fresh version. Returns the
    certified enrollment dict."""
    return get_success_data(
        api_client.certify_enrollment(
            enrollment["id"],
            {"expected_enrollment_version": enrollment["version"]},
            SCO,
        )
    )


def setup_certified_enrollment(veteran_total_days=1200, school_overrides=None,
                               enrollment_overrides=None):
    """Tier-N veteran + school + a CERTIFIED enrollment.

    Returns (veteran, school, enrollment) where enrollment is fetched fresh after
    certification (monthly_housing_allowance_cents / yellow_ribbon_match_cents
    finalized).
    """
    vet = create_veteran(total_active_duty_days=veteran_total_days)
    school = create_school(**(school_overrides or {}))
    enr = submit_enrollment(vet["id"], school["id"], **(enrollment_overrides or {}))
    certify_enrollment(enr)
    fresh = get_success_data(api_client.get_enrollment(enr["id"], ADMIN))
    return vet, school, fresh


# ─── Tier 5: Voc Rehab ────────────────────────────────────────────────────

def propose_voc_rehab_plan(veteran_id, planned_months=12, track="REEMPLOYMENT"):
    """Propose a voc-rehab plan (PROPOSED). Returns the plan dict."""
    payload = create_voc_rehab_plan_payload(
        veteran_id, planned_months=planned_months, track=track
    )
    return get_success_data(api_client.create_voc_rehab_plan(payload, ADMIN))
