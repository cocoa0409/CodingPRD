"""Co-op running cap boundary (PRD §3.9): inclusive <= at 4x weekly budget."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_distributor,
    setup_market,
    setup_film,
    setup_theatre,
    setup_committed_marketing_commitment,
    create_marketing_commitment_payload,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MARKETING = TEST_USERS["marketing_lead_headers"]

WEEKLY_BUDGET = 100000
CAP = RUNNING_CAP = 4 * WEEKLY_BUDGET  # 400000


def _setup(api):
    distributor = setup_distributor()
    did = distributor["id"]
    market = setup_market(did, weekly_coop_budget_cents=WEEKLY_BUDGET)
    film = setup_film(did)
    theatre = setup_theatre(did)
    return did, market, film, theatre


def test_commit_landing_exactly_at_cap_is_allowed(api):
    """PRD §3.9: "the market's `coop_committed_cents` plus the new `committed_cents`
    must not exceed four times its `weekly_coop_budget_cents`. Equality with the cap is
    permitted; only strict overflow is rejected with `ERR_COOP_BUDGET_EXCEEDED`."
    300000 already committed + 100000 new = exactly 400000 == 4 * 100000 -> COMMITTED.

    Design: Difficulty/boundary_precision_check/coop_budget_cap_lte_boundary
    """
    did, market, film, theatre = _setup(api)
    setup_committed_marketing_commitment(
        did, market["id"], film["id"], theatre["id"], committed_cents=300000
    )
    mc2 = validate_success(api.create_marketing_commitment(
        did, market["id"],
        create_marketing_commitment_payload(
            film["id"], committed_cents=100000, coop_share_pct=0.50
        ),
        MARKETING,
    ), 201)
    committed = validate_success(
        api.commit_marketing_commitment(did, market["id"], mc2["id"], MARKETING), 200
    )
    assert committed["status"] == "COMMITTED", (
        f"equality with the cap must be permitted, got {committed['status']}"
    )
    market_after = validate_success(api.get_market(did, market["id"], MARKETING), 200)
    assert market_after["coop_committed_cents"] == 400000


def test_commit_one_cent_under_cap_is_allowed(api):
    """PRD §3.9: "the market's `coop_committed_cents` plus the new `committed_cents`
    must not exceed four times its `weekly_coop_budget_cents`."
    300000 + 99999 = 399999 < 400000 -> COMMITTED.

    Design: Difficulty/boundary_precision_check/coop_budget_cap_lte_boundary
    """
    did, market, film, theatre = _setup(api)
    setup_committed_marketing_commitment(
        did, market["id"], film["id"], theatre["id"], committed_cents=300000
    )
    mc2 = validate_success(api.create_marketing_commitment(
        did, market["id"],
        create_marketing_commitment_payload(
            film["id"], committed_cents=99999, coop_share_pct=0.50
        ),
        MARKETING,
    ), 201)
    committed = validate_success(
        api.commit_marketing_commitment(did, market["id"], mc2["id"], MARKETING), 200
    )
    assert committed["status"] == "COMMITTED"
    market_after = validate_success(api.get_market(did, market["id"], MARKETING), 200)
    assert market_after["coop_committed_cents"] == 399999


def test_commit_one_cent_over_cap_is_rejected(api):
    """PRD §3.9: "Equality with the cap is permitted; only strict overflow is rejected
    with `ERR_COOP_BUDGET_EXCEEDED`."
    300000 + 100001 = 400001 > 400000 -> ERR_COOP_BUDGET_EXCEEDED (409).

    Design: Difficulty/boundary_precision_check/coop_budget_cap_lte_boundary
    """
    did, market, film, theatre = _setup(api)
    setup_committed_marketing_commitment(
        did, market["id"], film["id"], theatre["id"], committed_cents=300000
    )
    mc2 = validate_success(api.create_marketing_commitment(
        did, market["id"],
        create_marketing_commitment_payload(
            film["id"], committed_cents=100001, coop_share_pct=0.50
        ),
        MARKETING,
    ), 201)
    res = api.commit_marketing_commitment(did, market["id"], mc2["id"], MARKETING)
    validate_error(res, ApiErrorId.ERR_COOP_BUDGET_EXCEEDED)
    market_after = validate_success(api.get_market(did, market["id"], MARKETING), 200)
    assert market_after["coop_committed_cents"] == 300000, (
        "a rejected commit must not change coop_committed_cents"
    )
