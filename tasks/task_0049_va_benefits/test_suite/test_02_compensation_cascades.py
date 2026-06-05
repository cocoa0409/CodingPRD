"""Compensation cascades and dependent-driven recomputation.

Difficulty queue: transitive_cascade and the boundary_precision dependent-bump
instance, plus corner instances for dependent add/remove and immediate consistency.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_veteran,
    create_granted_claim,
    add_dependent,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]


# ─── transitive_cascade / grant_cascade_condition_rating_compensation ─────

def test_grant_cascade_conditions_become_service_connected(api):
    """PRD §3.4: "First, every condition on the claim has its
    `service_connection` set to `SERVICE_CONNECTED` and its `final_rating_pct`
    set equal to its `proposed_rating_pct`."

    Design: Difficulty/transitive_cascade/grant_cascade_condition_rating_compensation
    """
    vet = create_veteran(total_active_duty_days=1200)
    add_dependent(vet["id"], "SPOUSE")
    claim, _ = create_granted_claim(
        vet["id"],
        [{"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    data, _meta = _list_conditions(api, claim["id"])
    assert len(data) == 2
    for cond in data:
        assert cond["service_connection"] == "SERVICE_CONNECTED", (
            f"granted condition should be SERVICE_CONNECTED, got "
            f"{cond['service_connection']}"
        )


def test_grant_cascade_recomputes_rating_and_compensation(api):
    """PRD §3.4: "the veteran's `combined_rating_pct` is recomputed by the
    combined-rating algorithm over the veteran's entire set of service-connected
    conditions. Third — cascade hop two to three — the veteran's
    `monthly_compensation_cents` is recomputed from that new combined rating
    together with the veteran's active dependents."
    PRD §3.8: "70 pays 175,800 cents".

    Design: Difficulty/transitive_cascade/grant_cascade_condition_rating_compensation
    """
    vet = create_veteran(total_active_duty_days=1200)
    add_dependent(vet["id"], "SPOUSE")
    create_granted_claim(
        vet["id"],
        [{"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 70
    # base(70)=175800 + spouse 10000 scaled by 70% = 7000 -> 182800.
    assert after["monthly_compensation_cents"] == 182800, (
        f"rating 70 + one spouse -> 182800, got {after['monthly_compensation_cents']}"
    )


# ─── transitive_cascade / dependent_add_cascade_compensation ──────────────

def test_dependent_add_recomputes_compensation(api):
    """PRD §3.2: "Adding a dependent immediately recomputes the veteran's
    `monthly_compensation_cents` and increments the veteran's `version`."
    PRD §3.8: "7,000 cents for each active child who is *not* marked as the
    in-school eighteen-to-twenty-three category".

    Design: Difficulty/transitive_cascade/dependent_add_cascade_compensation
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 40}])
    add_dependent(vet["id"], "SPOUSE")
    before = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    # base(40)=77200 + spouse 10000 scaled by 40% = 4000 -> 81200.
    assert before["monthly_compensation_cents"] == 81200, (
        f"rating 40 + spouse -> 81200, got {before['monthly_compensation_cents']}"
    )
    add_dependent(vet["id"], "CHILD", in_school_18_to_23=False)
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    # dep sum = 10000 + 7000 = 17000 scaled by 40% = 6800 -> 77200 + 6800 = 84000.
    assert after["monthly_compensation_cents"] == 84000, (
        f"after adding under-18 child -> 84000, got {after['monthly_compensation_cents']}"
    )


def test_dependent_add_distinct_trigger_from_grant(api):
    """PRD §3.2: "Adding a dependent immediately recomputes the veteran's
    `monthly_compensation_cents` and increments the veteran's `version`."
    PRD §3.8: "10,000 cents if the veteran has exactly one active spouse".

    Design: Difficulty/transitive_cascade/dependent_add_cascade_compensation
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 40}])
    base_vet = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert base_vet["monthly_compensation_cents"] == 77200, (
        "rating 40 with no dependents -> base 77200"
    )
    add_dependent(vet["id"], "SPOUSE")
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["monthly_compensation_cents"] == 81200


# ─── boundary_precision_check / dependent_bump_threshold_at_rating_30 ─────

def test_dependent_bump_active_at_rating_exactly_30(api):
    """PRD §3.8: "the boundary sits exactly at thirty, so a rating of twenty
    ignores dependents while a rating of thirty includes them."
    PRD §3.8: "30 pays 53,600 cents".

    Design: Difficulty/boundary_precision_check/dependent_bump_threshold_at_rating_30
    """
    vet = create_veteran(total_active_duty_days=1200)
    add_dependent(vet["id"], "SPOUSE")
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 30}])
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 30
    # base(30)=53600 + spouse 10000 scaled by 30% = 3000 -> 56600.
    assert after["monthly_compensation_cents"] == 56600, (
        f"at exactly rating 30 the spouse counts -> 56600, got "
        f"{after['monthly_compensation_cents']}"
    )


def test_dependent_ignored_below_30_at_rating_20(api):
    """PRD §3.8: "When the combined rating is strictly below thirty, the monthly
    compensation is exactly that base amount and no dependent additions are made
    at all, even if the veteran has active dependents".
    PRD §3.8: "20 pays 34,600 cents".

    Design: Difficulty/boundary_precision_check/dependent_bump_threshold_at_rating_30
    """
    vet = create_veteran(total_active_duty_days=1200)
    add_dependent(vet["id"], "SPOUSE")
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 20}])
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 20
    assert after["monthly_compensation_cents"] == 34600, (
        f"at rating 20 the spouse adds nothing -> 34600, got "
        f"{after['monthly_compensation_cents']}"
    )


# ─── Corner / cross_cutting_complexity_layers ─────────────────────────────

def test_dependent_remove_recomputes_compensation(api):
    """PRD §3.2: "Removing a dependent is a distinct action that flips the
    dependent's `status` to `REMOVED`, then likewise recomputes
    `monthly_compensation_cents` and increments the veteran's `version`. A
    `REMOVED` dependent is excluded from all compensation arithmetic from that
    point on."

    Design: Corner/cross_cutting_complexity_layers/dependent_remove_recomputes_compensation
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    dep = add_dependent(vet["id"], "SPOUSE")
    before = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    # base(50)=109900 + spouse 10000 scaled by 50% = 5000 -> 114900.
    assert before["monthly_compensation_cents"] == 114900, (
        f"rating 50 + spouse -> 114900, got {before['monthly_compensation_cents']}"
    )
    get_success_data(api.remove_dependent(vet["id"], dep["id"], ADMIN))
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["monthly_compensation_cents"] == 109900, (
        f"after removing spouse -> 109900, got {after['monthly_compensation_cents']}"
    )


# ─── Corner / consistency_model ───────────────────────────────────────────

def test_grant_changes_visible_same_request(api):
    """PRD §2.7: "Whenever the server recomputes one of these in response to an
    action elsewhere — a claim being granted, a dependent being added or removed,
    a service-time edit — that recomputation is a mutation of the veteran record".
    PRD §3.8: "40 pays 77,200 cents".

    Design: Corner/consistency_model/grant_changes_visible_same_request
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 40}])
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 40, (
        f"combined rating visible immediately as 40, got {after['combined_rating_pct']}"
    )


# ─── helpers ──────────────────────────────────────────────────────────────

def _list_conditions(api, claim_id):
    from test_helpers import validate_paginated
    return validate_paginated(
        api.list_conditions(ADMIN, params={"claim_id": claim_id})
    )
