"""Composite setup helpers for multi-step test prerequisites.

All helpers build state purely through PRD-declared endpoints and use
get_success_data() internally so setup failures surface as clear "Setup failed"
errors. OCC-guarded writes (scenario create, memo create — PRD §2.7) always
re-read the deal's current version immediately before the write so fixtures are
robust regardless of which intermediate steps bumped the parent version.
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BPS_DENOM, CANONICAL
from .factories import (
    create_assumption_payload,
    create_deal_payload,
    create_ic_memo_payload,
    create_operating_expense_payload,
    create_property_payload,
    create_rent_roll_payload,
    create_scenario_payload,
)
from .test_users import (
    ASSET_MANAGER_USER_ID,
    IC_MEMBER_1_USER_ID,
    IC_MEMBER_2_USER_ID,
    TEST_USERS,
    make_asset_manager_headers,
    make_ic_member_headers,
    submit_underwriting_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
ASSET_MANAGER = TEST_USERS["asset_manager_headers"]
IC_MEMBER = TEST_USERS["ic_member_headers"]
IC_MEMBER_2 = TEST_USERS["ic_member_2_headers"]
IC_CHAIR = TEST_USERS["ic_chair_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators and state progression
# ---------------------------------------------------------------------------

def create_deal(**overrides):
    """Create a Deal in DRAFT (PRD §3.1). Returns the Deal dict."""
    res = api_client.create_deal(create_deal_payload(**overrides), ANALYST)
    return get_success_data(res)


def add_property(deal_id, **overrides):
    res = api_client.create_property(deal_id, create_property_payload(**overrides), ANALYST)
    return get_success_data(res)


def add_rent_roll(property_id, **overrides):
    res = api_client.create_rent_roll(property_id, create_rent_roll_payload(**overrides), ANALYST)
    return get_success_data(res)


def add_operating_expense(property_id, **overrides):
    res = api_client.create_operating_expense(
        property_id, create_operating_expense_payload(**overrides), ANALYST
    )
    return get_success_data(res)


def add_assumption(deal_id, **overrides):
    res = api_client.create_assumption(deal_id, create_assumption_payload(**overrides), ANALYST)
    return get_success_data(res)


def get_deal(deal_id):
    return get_success_data(api_client.get_deal(deal_id, ANALYST))


def get_deal_version(deal_id) -> int:
    """Current Deal.version, read fresh (PRD §2.4)."""
    return get_deal(deal_id)["version"]


def submit_underwriting(deal_id, asset_manager_id=ASSET_MANAGER_USER_ID):
    """DRAFT -> UNDERWRITING; records X-AssetManager-ID onto deal.asset_manager_id
    (PRD §3.1). Returns the updated Deal."""
    res = api_client.submit_underwriting(
        deal_id, submit_underwriting_headers(asset_manager_id)
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_underwriting_env(
    deal_overrides=None,
    property_overrides=None,
    rent_rolls=None,
    expenses=None,
    assumption_overrides=None,
    submit=True,
    asset_manager_id=ASSET_MANAGER_USER_ID,
):
    """Deal (+ one Property, rent-roll rows, expense rows, one
    MarketAssumption). With submit=True the deal is moved DRAFT ->
    UNDERWRITING. Returns an env dict.

    When rent_rolls / expenses are None, a minimal one-row data room is
    installed so that downstream scenario computation (PRD §3.4.1) always has
    a latest rent roll and a latest expense year to read."""
    if rent_rolls is None:
        rent_rolls = [{
            "period_month": "2026-06",
            "occupied_units": 9,
            "total_units": 10,
            "gross_potential_rent_cents": 1_000_000,
            "collected_rent_cents": 900_000,
            "concessions_cents": 0,
            "source_doc_ref": "rr",
        }]
    if expenses is None:
        expenses = [{"period_year": 2025, "category": "TAXES", "amount_cents": 1_000_000}]
    deal = create_deal(**(deal_overrides or {}))
    prop = add_property(deal["id"], **(property_overrides or {}))
    for rr in rent_rolls:
        add_rent_roll(prop["id"], **rr)
    for oe in expenses:
        add_operating_expense(prop["id"], **oe)
    assumption = add_assumption(deal["id"], **(assumption_overrides or {}))
    if submit:
        deal = submit_underwriting(deal["id"], asset_manager_id)
    return {
        "deal": deal,
        "property": prop,
        "assumption": assumption,
        "asset_manager_id": asset_manager_id,
    }


# ---------------------------------------------------------------------------
# Tier 3: scenarios and computation
# ---------------------------------------------------------------------------

def create_scenario_fresh(deal_id, assumption_id, **overrides):
    """Create a Scenario with expected_deal_version read fresh (PRD §2.7)."""
    payload = create_scenario_payload(
        assumption_id, expected_deal_version=get_deal_version(deal_id), **overrides
    )
    res = api_client.create_scenario(deal_id, payload, ANALYST)
    return get_success_data(res)


def compute_scenario(scenario_id):
    """DRAFT -> COMPUTED (PRD §3.4). Returns the computed Scenario."""
    res = api_client.compute_scenario(scenario_id, ANALYST)
    return get_success_data(res)


def setup_computed_scenario(env=None, scenario_overrides=None, **env_kwargs):
    """Underwriting deal + one COMPUTED scenario. Returns env dict with
    env["scenario"] set."""
    env = env or setup_underwriting_env(**env_kwargs)
    scenario = create_scenario_fresh(
        env["deal"]["id"], env["assumption"]["id"], **(scenario_overrides or {})
    )
    env["scenario"] = compute_scenario(scenario["id"])
    return env


def create_memo_fresh(deal_id, scenario_id, **overrides):
    """Create an ICMemo (DRAFT) with expected_deal_version read fresh (PRD §3.7)."""
    payload = create_ic_memo_payload(
        scenario_id, expected_deal_version=get_deal_version(deal_id), **overrides
    )
    res = api_client.create_ic_memo(deal_id, payload, ANALYST)
    return get_success_data(res)


def setup_submitted_memo(env=None, **env_kwargs):
    """Computed scenario + memo submitted (DRAFT -> SUBMITTED, PRD §3.7)."""
    env = env or setup_computed_scenario(**env_kwargs)
    memo = create_memo_fresh(env["deal"]["id"], env["scenario"]["id"])
    env["memo"] = get_success_data(api_client.submit_ic_memo(memo["id"], ANALYST))
    return env


# ---------------------------------------------------------------------------
# Tier 5: IC review / terminal lifecycles
# ---------------------------------------------------------------------------

def setup_deal_in_ic_review(env=None, asset_manager_id=ASSET_MANAGER_USER_ID, **env_kwargs):
    """Full walk to deal IC_REVIEW with the memo in UNDER_VOTE (PRD §3.7):
    submitted memo + submit-ic by the deal's asset manager."""
    env = env or setup_submitted_memo(**env_kwargs)
    am_headers = make_asset_manager_headers(env.get("asset_manager_id", asset_manager_id))
    env["deal"] = get_success_data(api_client.submit_ic(env["deal"]["id"], am_headers))
    env["memo"] = get_success_data(api_client.get_ic_memo(env["memo"]["id"], ANALYST))
    return env


def cast_vote(memo_id, vote, user_id=IC_MEMBER_1_USER_ID, role="IC_Member", **overrides):
    """Cast an ICVote (PRD §3.8). Returns the raw response."""
    if role == "IC_Chair":
        from .test_users import make_ic_chair_headers
        headers = make_ic_chair_headers(user_id)
    else:
        headers = make_ic_member_headers(user_id)
    return api_client.vote_ic_memo(memo_id, {"vote": vote, **overrides}, headers)


def setup_approved_deal(**env_kwargs):
    """Full walk to deal APPROVED via two YES votes (PRD §3.8)."""
    env = setup_deal_in_ic_review(**env_kwargs)
    get_success_data(cast_vote(env["memo"]["id"], "YES", IC_MEMBER_1_USER_ID))
    get_success_data(cast_vote(env["memo"]["id"], "YES", IC_MEMBER_2_USER_ID))
    env["deal"] = get_deal(env["deal"]["id"])
    env["memo"] = get_success_data(api_client.get_ic_memo(env["memo"]["id"], ANALYST))
    return env


def setup_rejected_deal_via_no_vote(comment="market too rich", **env_kwargs):
    """Full walk to deal REJECTED via a single NO vote (PRD §3.8)."""
    env = setup_deal_in_ic_review(**env_kwargs)
    get_success_data(cast_vote(env["memo"]["id"], "NO", IC_MEMBER_1_USER_ID, comment=comment))
    env["deal"] = get_deal(env["deal"]["id"])
    env["memo"] = get_success_data(api_client.get_ic_memo(env["memo"]["id"], ANALYST))
    return env


# ---------------------------------------------------------------------------
# Tier 4: canonical data room for calculation tests
# ---------------------------------------------------------------------------

def setup_canonical_computed_scenario(
    deal_code="D-CANON",
    occupancy_stress_pct=92,
    scenario_kind="BASE",
    assumption_overrides=None,
):
    """The canonical data room (PRD §3.4.1 inputs): price 1_000_000_000 cents,
    one multifamily property (100 units), one rent-roll month (GPR 10_000_000,
    concessions 200_000, 92/100 occupied), five 2025 expense rows totalling
    25_200_000, and the canonical assumption set (yr1 growth 250 bps, steady
    300 bps, expense growth 200 bps, exit cap 550 bps, hold 5, capex 500_000
    per unit, lease-up 6 months). Returns env with env["scenario"] COMPUTED."""
    assumption = dict(CANONICAL["ASSUMPTION"])
    if assumption_overrides:
        assumption.update(assumption_overrides)
    env = setup_underwriting_env(
        deal_overrides={
            "deal_code": deal_code,
            "deal_name": "Canonical",
            "strategy": "CORE_PLUS",
            "target_purchase_price_cents": CANONICAL["PRICE_CENTS"],
        },
        property_overrides={
            "address_line": "1 Main St",
            "market": "Austin, TX",
            "property_type": "MULTIFAMILY",
            "units": CANONICAL["UNITS"],
            "rentable_sqft": CANONICAL["RENTABLE_SQFT"],
            "year_built": CANONICAL["YEAR_BUILT"],
        },
        rent_rolls=[{
            "period_month": CANONICAL["PERIOD_MONTH"],
            "occupied_units": CANONICAL["OCCUPIED_UNITS"],
            "total_units": CANONICAL["TOTAL_UNITS"],
            "gross_potential_rent_cents": CANONICAL["GPR_CENTS"],
            "collected_rent_cents": CANONICAL["COLLECTED_CENTS"],
            "concessions_cents": CANONICAL["CONCESSIONS_CENTS"],
            "source_doc_ref": "rr-2026-06",
        }],
        expenses=[
            {"period_year": CANONICAL["EXPENSE_YEAR"], "category": cat, "amount_cents": amt}
            for cat, amt in CANONICAL["EXPENSE_ROWS"]
        ],
        assumption_overrides=assumption,
    )
    return setup_computed_scenario(
        env=env,
        scenario_overrides={
            "scenario_kind": scenario_kind,
            "occupancy_stress_pct": occupancy_stress_pct,
        },
    )


def setup_negative_noi_scenario():
    """A COMPUTED scenario whose computed_noi_yr1_cents is not positive
    (PRD §3.5 precondition): 5% occupancy stress against heavy expenses."""
    return setup_computed_scenario(
        deal_overrides={
            "deal_code": "D-NEGN",
            "deal_name": "Neg NOI",
            "strategy": "OPPORTUNISTIC",
            "target_purchase_price_cents": 500_000_000,
        },
        property_overrides={
            "address_line": "1 Bad",
            "market": "M",
            "property_type": "OFFICE",
            "units": 100,
            "rentable_sqft": 100_000,
            "year_built": 2000,
        },
        rent_rolls=[{
            "period_month": "2026-06",
            "occupied_units": 5,
            "total_units": 100,
            "gross_potential_rent_cents": 1_000_000,
            "collected_rent_cents": 50_000,
            "concessions_cents": 0,
            "source_doc_ref": "rr",
        }],
        expenses=[{"period_year": 2025, "category": "TAXES", "amount_cents": 50_000_000}],
        assumption_overrides={
            "market_rent_growth_yr1_bps": 0,
            "market_rent_growth_steady_bps": 0,
            "expense_growth_bps": 0,
            "exit_cap_rate_bps": 800,
            "hold_period_years": 3,
            "capex_per_unit_cents": 100_000,
            "lease_up_months": 12,
        },
        scenario_overrides={"scenario_kind": "STRESS", "occupancy_stress_pct": 5},
    )


# ---------------------------------------------------------------------------
# PRD §3.4.2 projection helper — used only to express the waterfall cash
# conservation property against the scenario's API-returned computed NOI.
# ---------------------------------------------------------------------------

def _round_half_up(x) -> int:
    return int(Decimal(repr(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_total_distributions_cents(noi_yr1_cents, steady_growth_bps, hold_years, exit_cap_bps):
    """PRD §3.4.2: "Total distributions are the sum of every projected year-NOI
    across the hold plus the exit value." Projections use the steady growth
    factor; the exit value is the terminal NOI divided by the exit cap rate,
    rounded half-up to integer cents (PRD §3.4.2, §2.5)."""
    g = steady_growth_bps / BPS_DENOM
    noi_sum = sum(noi_yr1_cents * (1 + g) ** (t - 1) for t in range(1, hold_years + 1))
    noi_terminal = noi_yr1_cents * (1 + g) ** hold_years
    exit_value = _round_half_up(noi_terminal / (exit_cap_bps / BPS_DENOM))
    return noi_sum + exit_value
