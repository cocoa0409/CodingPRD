"""Owner settlement: the STANDARD vs GUARANTEED payout variants, the
split-conservation invariant, and statement issuance."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_owner_statement, assert_statement_conservation,
    ApiErrorId,
    issue_statement, setup_completed_trip,
    make_ops_admin_headers,
)

OPS_ADMIN = make_ops_admin_headers()

# Identical trip economics for both variants: legs REV 120 + POS 30,
# actuals 100 + 30 on a 240000/h LIGHT_JET -> gross 472000, 130 logged min.
LEGS = ((120, "REVENUE", False), (30, "POSITIONING", False))
ACTUALS = [100, 30]


def _completed_statement(owner_overrides, tail_number):
    ctx = setup_completed_trip(
        legs=LEGS, actual_minutes=ACTUALS,
        owner_overrides=owner_overrides,
        aircraft_overrides={"tail_number": tail_number, "hourly_rate_cents": 240000})
    assert len(ctx["statements"]) == 1
    stmt = ctx["statements"][0]
    assert_owner_statement(stmt)
    assert stmt["gross_cents"] == 472000
    return stmt


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / owner_standard_vs_guaranteed_diverge
# ---------------------------------------------------------------------------

def test_standard_variant_owner_share_equals_standard_share(api):
    """PRD §3.9: "Under the STANDARD variant — an owner whose per-minute
    guarantee is zero — the owner share equals the standard share; under the
    GUARANTEED variant, the floor exceeds the standard share and binds, so
    identical trip economics pay out differently."
    PRD §3.9: "The `standard_share_cents` is the gross multiplied by the
    owner's `revenue_share_pct` and divided by one hundred, rounded half up."

    Design: Difficulty/dual_variant_calc/owner_standard_vs_guaranteed_diverge
    """
    stmt = _completed_statement(
        {"name": "Owner S", "contact_email": "s@x.com",
         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 0}, "N200SS")
    assert stmt["standard_share_cents"] == 377600, "80% of 472000"
    assert stmt["guarantee_floor_cents"] == 0
    assert stmt["owner_share_cents"] == 377600, "STANDARD variant: share == standard"


def test_guaranteed_variant_floor_binds_over_standard_share(api):
    """PRD §3.9: "The `guarantee_floor_cents` is the owner's
    `guarantee_cents_per_block_min` multiplied by the total logged
    `actual_block_minutes` across every flight log of the trip — revenue and
    positioning legs alike. The `owner_share_cents` is the greater of the
    standard share and the guarantee floor, and the
    `operator_retained_cents` is the residual gross minus the owner share,
    which may legitimately go negative when the guarantee binds."
    Guarantee 4000/min x 130 logged = 520000 > standard 377600, so the
    residual goes to -48000.

    Design: Difficulty/dual_variant_calc/owner_standard_vs_guaranteed_diverge
    """
    stmt = _completed_statement(
        {"name": "Owner G", "contact_email": "g@x.com",
         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 4000}, "N300GG")
    assert stmt["standard_share_cents"] == 377600
    assert stmt["guarantee_floor_cents"] == 520000
    assert stmt["owner_share_cents"] == 520000, "GUARANTEED variant: floor binds"
    assert stmt["operator_retained_cents"] == -48000


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / owner_statement_split_conservation
# ---------------------------------------------------------------------------

def test_statement_split_conserves_gross_guaranteed_variant(api):
    """PRD §3.9: "Conservation holds always: owner share plus operator
    retained equals the gross."
    Invariant checked in the GUARANTEED variant, where the residual is
    negative: 520000 + (-48000) == 472000.

    Design: Difficulty/compensating_invariant/owner_statement_split_conservation
    """
    stmt = _completed_statement(
        {"name": "Owner GS", "contact_email": "gs@x.com",
         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 4000}, "N330GS")
    assert stmt["owner_share_cents"] == 520000
    assert stmt["operator_retained_cents"] == -48000
    assert_statement_conservation(stmt)


def test_statement_split_conserves_gross_standard_variant(api):
    """PRD §3.9: "Conservation holds always: owner share plus operator
    retained equals the gross."
    Invariant checked in the STANDARD variant: 377600 + 94400 == 472000.

    Design: Difficulty/compensating_invariant/owner_statement_split_conservation
    """
    stmt = _completed_statement(
        {"name": "Owner ST", "contact_email": "st@x.com",
         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 0}, "N331ST")
    assert stmt["owner_share_cents"] == 377600
    assert stmt["operator_retained_cents"] == 94400
    assert_statement_conservation(stmt)


# ---------------------------------------------------------------------------
# Queue B: state_machines / issue_statement_twice_rejected
# ---------------------------------------------------------------------------

def test_issue_statement_twice_rejected(api):
    """PRD §3.9: "The statement is born `DRAFT`; an `OpsAdmin` issues it,
    which requires `DRAFT` status (`ERR_STATEMENT_NOT_DRAFT` otherwise),
    moves it to `ISSUED`, and stamps `issued_at`."

    Design: Corner/state_machines/issue_statement_twice_rejected
    """
    ctx = setup_completed_trip(
        owner_overrides={"name": "Owner IS", "contact_email": "is@x.com"},
        aircraft_overrides={"tail_number": "N200IS"}, customer_name="Cust IS")
    stmt = ctx["statements"][0]
    issued = issue_statement(stmt["id"])
    assert issued["status"] == "ISSUED"
    assert issued["issued_at"], "issued_at stamped at the current clock"
    resp = api_client.issue_owner_statement(stmt["id"], OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DRAFT)
