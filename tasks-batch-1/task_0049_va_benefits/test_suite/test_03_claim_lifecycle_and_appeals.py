"""Claim adjudication lifecycle, appeal loop, and conserved-rating invariants.

Difficulty queue: non_linear_state_machine (claim cycle), compensating_invariant
(claim deny+remand conserves rating). Corner queue: claim state-machine instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_veteran,
    create_claim,
    create_rated_claim,
    create_granted_claim,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]
RATER = TEST_USERS["rating_specialist_headers"]


# ─── non_linear_state_machine / claim_appeal_cycle_rated_remand_development ─

def test_remand_from_rated_increments_remand_count(api):
    """PRD §3.4: "Remanding from `RATED` is the third branch and is the lighter
    of the two remand paths: it is permitted only from `RATED` and only while the
    claim's `remand_count` is strictly less than the appeal cap of two rounds
    (otherwise `ERR_APPEAL_EXHAUSTED`); its sole effect is to advance the claim to
    `REMANDED` and increase `remand_count` by one."

    Design: Difficulty/non_linear_state_machine/claim_appeal_cycle_rated_remand_development
    """
    vet = create_veteran(total_active_duty_days=1200)
    claim, _ = create_rated_claim(vet["id"], [{"proposed_rating_pct": 40}])
    remanded = validate_success(api.remand_claim(claim["id"], ADMIN), 200)
    assert remanded["status"] == "REMANDED"
    assert remanded["remand_count"] == 1, (
        f"remand_count should be 1 after one remand, got {remanded['remand_count']}"
    )


def test_remanded_claim_reopens_development(api):
    """PRD §3.5: "Once in `REMANDED`, the claim re-enters development through the
    same development-opening action described in §3.3, and the loop `REMANDED →
    DEVELOPMENT → RATED → REMANDED` may repeat until the remand cap is reached."

    Design: Difficulty/non_linear_state_machine/claim_appeal_cycle_rated_remand_development
    """
    vet = create_veteran(total_active_duty_days=1200)
    claim, _ = create_rated_claim(vet["id"], [{"proposed_rating_pct": 40}])
    get_success_data(api.remand_claim(claim["id"], ADMIN))
    reopened = validate_success(api.open_development(claim["id"], ADMIN), 200)
    assert reopened["status"] == "DEVELOPMENT", (
        f"REMANDED -> open-development should yield DEVELOPMENT, got {reopened['status']}"
    )


# ─── compensating_invariant / claim_deny_then_remand_restores_combined_rating ─

def test_second_claim_deny_conserves_first_claim_rating(api):
    """PRD §3.4: "On a deny, every condition on the claim has its
    `service_connection` set to `NOT_CONNECTED` and its `final_rating_pct` left
    at 0."
    PRD §3.6: "The input set is the collection of conditions whose
    `service_connection` is `SERVICE_CONNECTED` and whose `final_rating_pct` is
    greater than 0".

    Design: Difficulty/compensating_invariant/claim_deny_then_remand_restores_combined_rating
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(
        vet["id"], [{"proposed_rating_pct": 50}],
        claim_type="ORIGINAL", received_date="2026-01-02T00:00:00Z",
    )
    claim_b, _ = create_rated_claim(
        vet["id"], [{"diagnostic_code": "6260", "proposed_rating_pct": 40}],
        claim_type="SECONDARY", received_date="2026-02-10T00:00:00Z",
    )
    get_success_data(
        api.deny_claim(
            claim_b["id"], {"expected_claim_version": claim_b["version"]}, ADMIN
        )
    )
    after_deny = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after_deny["combined_rating_pct"] == 50, (
        f"denying claim B leaves claim A's 50 intact, got {after_deny['combined_rating_pct']}"
    )


def test_second_claim_remand_after_deny_conserves_rating(api):
    """PRD §3.5: "Because those conditions were already excluded from the
    service-connected set while denied, reopening them leaves that set unchanged;
    nonetheless the veteran's `combined_rating_pct` and
    `monthly_compensation_cents` are recomputed as part of this step so the
    figures reflect the current service-connected population, with any conditions
    granted on other claims remaining in place."

    Design: Difficulty/compensating_invariant/claim_deny_then_remand_restores_combined_rating
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(
        vet["id"], [{"proposed_rating_pct": 50}],
        claim_type="ORIGINAL", received_date="2026-01-02T00:00:00Z",
    )
    claim_b, _ = create_rated_claim(
        vet["id"], [{"diagnostic_code": "6260", "proposed_rating_pct": 40}],
        claim_type="SECONDARY", received_date="2026-02-10T00:00:00Z",
    )
    get_success_data(
        api.deny_claim(
            claim_b["id"], {"expected_claim_version": claim_b["version"]}, ADMIN
        )
    )
    get_success_data(api.remand_claim(claim_b["id"], ADMIN))
    after_remand = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after_remand["combined_rating_pct"] == 50, (
        f"deny+remand of claim B conserves claim A's 50, got "
        f"{after_remand['combined_rating_pct']}"
    )


# ─── Corner / state_machines (Claim) ──────────────────────────────────────

def test_claim_initial_state_submitted(api):
    """PRD §3.3: "A new claim is created in `SUBMITTED` status with its
    `remand_count` set to 0."

    Design: Corner/state_machines/claim_initial_state_submitted
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim = validate_success(
        api.create_claim(
            {"veteran_id": vet["id"], "claim_type": "ORIGINAL",
             "received_date": "2026-01-01T00:00:00Z"},
            ADMIN,
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["remand_count"] == 0


def test_rate_from_submitted_invalid_state(api):
    """PRD §3.4: "Rating is permitted only from `DEVELOPMENT` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/rate_claim_from_submitted_invalid_state
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
    res = api.rate_claim(claim["id"], RATER)
    validate_error(res, "ERR_INVALID_STATE", 409)
    still = validate_success(api.get_claim(claim["id"], ADMIN), 200)
    assert still["status"] == "SUBMITTED"


def test_grant_from_closed_terminal_rejected(api):
    """PRD §3.5: "closing is permitted from `GRANTED` (moving it to `CLOSED`) and
    from `DENIED` (also moving it to `CLOSED`), and `CLOSED` is terminal."
    PRD §3.4: "A grant is permitted only from `RATED`".

    Design: Corner/state_machines/grant_claim_from_terminal_closed_rejected
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim, _ = create_granted_claim(vet["id"], [{"proposed_rating_pct": 40}])
    closed = validate_success(api.close_claim(claim["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    res = api.grant_claim(
        claim["id"], {"expected_claim_version": closed["version"]}, ADMIN
    )
    validate_error(res, "ERR_INVALID_STATE", 409)
    still = validate_success(api.get_claim(claim["id"], ADMIN), 200)
    assert still["status"] == "CLOSED"


def test_open_development_zero_conditions_rejected(api):
    """PRD §3.3: "It additionally requires that at least one condition reference
    this claim — opening development on a claim with zero conditions is rejected
    with `ERR_CLAIM_HAS_NO_CONDITIONS`."

    Design: Corner/state_machines/open_development_zero_conditions_precondition
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim = create_claim(vet["id"])
    res = api.open_development(claim["id"], ADMIN)
    validate_error(res, "ERR_CLAIM_HAS_NO_CONDITIONS", 409)


def test_rate_development_claim_with_all_conditions_rated(api):
    """PRD §3.4: "Rating is permitted only from `DEVELOPMENT` (otherwise
    `ERR_INVALID_STATE`) and requires that *every* condition on the claim already
    carry a `proposed_rating_pct` in the valid multiple-of-ten range".

    Design: Corner/state_machines/rate_claim_with_unrated_condition
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
    rated = validate_success(api.rate_claim(claim["id"], RATER), 200)
    assert rated["status"] == "RATED", (
        f"a fully-rated DEVELOPMENT claim rates successfully, got {rated['status']}"
    )


def test_appeal_exhausted_after_max_remands(api):
    """PRD §3.4: "only while the claim's `remand_count` is strictly less than the
    appeal cap of two rounds (otherwise `ERR_APPEAL_EXHAUSTED`)".
    PRD §3.5: "again only while `remand_count` is strictly below the cap of two
    (otherwise `ERR_APPEAL_EXHAUSTED`)".

    Design: Corner/state_machines/appeal_exhausted_after_max_remands
    """
    vet = create_veteran(total_active_duty_days=1095)
    claim, _ = create_rated_claim(vet["id"], [{"proposed_rating_pct": 40}])
    # Cycle to remand_count = 2.
    get_success_data(api.remand_claim(claim["id"], ADMIN))           # count -> 1
    get_success_data(api.open_development(claim["id"], ADMIN))
    get_success_data(api.rate_claim(claim["id"], RATER))
    get_success_data(api.remand_claim(claim["id"], ADMIN))           # count -> 2
    get_success_data(api.open_development(claim["id"], ADMIN))
    get_success_data(api.rate_claim(claim["id"], RATER))
    res = api.remand_claim(claim["id"], ADMIN)
    validate_error(res, "ERR_APPEAL_EXHAUSTED", 409)
    still = validate_success(api.get_claim(claim["id"], ADMIN), 200)
    assert still["remand_count"] == 2, (
        f"remand_count caps at 2, got {still['remand_count']}"
    )
