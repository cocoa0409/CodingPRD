"""Relocation-benefit variants, review lifecycle, cap boundary, and occupant gate."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, assert_relocation_benefit,
    make_property_owner_headers,
    setup_occupant_parcel,
    TEST_USERS,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]


def _submit(api, ctx, occupant_type, **fields):
    owner = make_property_owner_headers(ctx["owner"]["id"])
    payload = {"claimant_name": "Occ", "occupant_type": occupant_type}
    payload.update(fields)
    return api.create_relocation_benefit(ctx["parcel"]["id"], payload, owner)


# ---- dual_variant_calc / relocation_residential_vs_business ----------------

def test_residential_benefit_caps_replacement_differential(api):
    """PRD §3.6: "For a `RESIDENTIAL` occupant, the replacement-housing
    differential is the greater of zero and (`comparable_replacement_cost_cents`
    minus `acquired_dwelling_price_cents`), capped at 3,150,000 cents (\\$31,500);
    the `benefit_amount_cents` is that capped differential plus the
    `moving_expense_cents`."

    Design: Difficulty/dual_variant_calc/relocation_residential_vs_business
    """
    ctx = setup_occupant_parcel(api=api)
    data = validate_success(_submit(
        api, ctx, "RESIDENTIAL", comparable_replacement_cost_cents=25_000_000,
        acquired_dwelling_price_cents=22_000_000, moving_expense_cents=100_000), 201)
    assert_relocation_benefit(data)
    assert data["benefit_amount_cents"] == 3_100_000


def test_business_benefit_caps_reestablishment_cost(api):
    """PRD §3.6: "For a `BUSINESS` occupant, the reestablishment component is the
    `reestablishment_cost_cents` capped at 5,000,000 cents (\\$50,000); the
    `benefit_amount_cents` is that capped component plus the
    `moving_expense_cents`."

    Design: Difficulty/dual_variant_calc/relocation_residential_vs_business
    """
    ctx = setup_occupant_parcel(api=api)
    data = validate_success(_submit(
        api, ctx, "BUSINESS", reestablishment_cost_cents=6_000_000,
        moving_expense_cents=200_000), 201)
    assert data["benefit_amount_cents"] == 5_200_000


# ---- Corner: deny reaches DENIED terminal ----------------------------------

def test_deny_submitted_benefit_reaches_denied(api):
    """PRD §3.6: "or denies it with a `reason`, moving it from `SUBMITTED` to
    `DENIED`."

    Design: Corner/state_machines/relocation_deny_reaches_denied_terminal
    """
    ctx = setup_occupant_parcel(api=api)
    rb = validate_success(_submit(
        api, ctx, "RESIDENTIAL", comparable_replacement_cost_cents=20_000_000,
        acquired_dwelling_price_cents=19_000_000, moving_expense_cents=50_000), 201)
    assert rb["benefit_amount_cents"] == 1_050_000
    data = validate_success(api.deny_relocation_benefit(
        rb["id"], {"reason": "insufficient documentation"}, AGENT))
    assert data["status"] == "DENIED"


# ---- Corner: pay reaches PAID ----------------------------------------------

def test_approve_then_pay_reaches_paid(api):
    """PRD §3.6: "An `EscrowOfficer` then pays an approved benefit, moving it from
    `APPROVED` to `PAID`."

    Design: Corner/state_machines/relocation_pay_reaches_paid
    """
    ctx = setup_occupant_parcel(api=api)
    rb = validate_success(_submit(
        api, ctx, "BUSINESS", reestablishment_cost_cents=3_000_000,
        moving_expense_cents=100_000), 201)
    assert rb["benefit_amount_cents"] == 3_100_000
    validate_success(api.approve_relocation_benefit(rb["id"], AGENT))
    data = validate_success(api.pay_relocation_benefit(rb["id"], ESCROW))
    assert data["status"] == "PAID"


# ---- Corner: residential cap boundary --------------------------------------

def test_residential_differential_clamped_to_cap(api):
    """PRD §3.6: "the replacement-housing differential is the greater of zero and
    (`comparable_replacement_cost_cents` minus `acquired_dwelling_price_cents`),
    capped at 3,150,000 cents (\\$31,500)".

    Design: Corner/calculations/relocation_residential_cap_boundary
    """
    ctx = setup_occupant_parcel(api=api)
    data = validate_success(_submit(
        api, ctx, "RESIDENTIAL", comparable_replacement_cost_cents=30_000_000,
        acquired_dwelling_price_cents=25_000_000, moving_expense_cents=0), 201)
    assert data["benefit_amount_cents"] == 3_150_000


# ---- Corner: deny an already-denied benefit --------------------------------

def test_deny_already_denied_returns_invalid_state(api):
    """PRD §3.6: "Any approve, deny, or pay attempt against a benefit that is not
    in the required originating state is rejected with
    `ERR_INVALID_RELOCATION_STATE`."

    Design: Corner/errors/deny_already_denied_relocation_returns_invalid_state
    """
    ctx = setup_occupant_parcel(api=api)
    rb = validate_success(_submit(
        api, ctx, "BUSINESS", reestablishment_cost_cents=2_000_000,
        moving_expense_cents=0), 201)
    validate_success(api.deny_relocation_benefit(rb["id"], {"reason": "x"}, AGENT))
    resp = api.deny_relocation_benefit(rb["id"], {"reason": "again"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_RELOCATION_STATE)


# ---- Corner: non-occupant cannot claim -------------------------------------

def test_non_occupant_relocation_claim_returns_not_occupant(api):
    """PRD §3.6: "the acting `OwnershipInterest` (identified through the owner's
    `X-User-ID`, per §2.1) must have `is_occupant` equal to true; a claim from a
    non-occupant is rejected with `ERR_NOT_OCCUPANT`."

    Design: Corner/rbac/non_occupant_relocation_claim_returns_not_occupant
    """
    ctx = setup_occupant_parcel(is_occupant=False, api=api)
    resp = _submit(
        api, ctx, "RESIDENTIAL", comparable_replacement_cost_cents=10_000_000,
        acquired_dwelling_price_cents=9_000_000, moving_expense_cents=0)
    validate_error(resp, ApiErrorId.ERR_NOT_OCCUPANT)
