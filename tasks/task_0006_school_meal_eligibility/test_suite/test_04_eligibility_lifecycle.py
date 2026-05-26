"""Tests covering EligibilityDetermination's two parallel state dimensions:
lifecycle_status (ACTIVE/SUPERSEDED/EXPIRED/REVOKED) evolves INDEPENDENTLY of
verification_status (UNVERIFIED/VERIFIED/DEFERRED).
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    setup_clean_world,
    create_household,
    create_direct_cert_eligibility,
    verify_eligibility,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Difficulty rule 3 / instance 2 — parallel lifecycle × verification dimensions
# ---------------------------------------------------------------------

def test_verify_changes_verification_dimension_without_touching_lifecycle(api):
    """PRD §3.4: "An `EligibilityDetermination` has two parallel status
    dimensions that evolve independently. `lifecycle_status` answers \"is this
    determination governing meals right now\" and moves through `ACTIVE` (the
    initial value), `SUPERSEDED` (a newer determination has displaced it),
    `EXPIRED` (the validity window has run out), and `REVOKED` (an auditor has
    cancelled it). ... `verification_status` answers \"has an auditor signed
    off on this determination\" and moves through `UNVERIFIED` (the initial
    value), `VERIFIED`, and `DEFERRED`. The two dimensions do not interlock:
    a determination can be `ACTIVE` and `UNVERIFIED`, `ACTIVE` and `VERIFIED`,
    `SUPERSEDED` and still `UNVERIFIED`, and so on."

    Design: Difficulty/non_linear_state_machine/eligibilitydetermination_parallel_lifecycle_and_verification
    """
    setup_clean_world("2026-02-15T10:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    assert elig["lifecycle_status"] == "ACTIVE"
    assert elig["verification_status"] == "UNVERIFIED"

    after_verify = verify_eligibility(elig["id"])
    assert after_verify["verification_status"] == "VERIFIED", (
        "verify must flip verification_status to VERIFIED; "
        f"got {after_verify['verification_status']!r}"
    )
    assert after_verify["lifecycle_status"] == "ACTIVE", (
        "verify must NOT touch lifecycle_status (independence of dimensions); "
        f"got {after_verify['lifecycle_status']!r}"
    )


def test_verify_bumps_eligibility_determination_version(api):
    """PRD §3.4: "Every transition on a determination — supersession,
    expiration, revocation, verification, deferral — bumps
    `EligibilityDetermination.version` by one and refreshes `updated_at`."

    Design: Difficulty/non_linear_state_machine/eligibilitydetermination_parallel_lifecycle_and_verification
    """
    setup_clean_world("2026-02-15T10:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    v_initial = elig["version"]
    after_verify = verify_eligibility(elig["id"])
    assert after_verify["version"] == v_initial + 1, (
        f"verify must bump version by exactly 1; "
        f"was {v_initial}, now {after_verify['version']}"
    )
