"""Deposit ledger, neutral fee charges, compensation views, and party allocation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, make_party_headers,
    create_hearing_payload, create_fee_charge_payload, create_deposit_payload,
)
from test_helpers.fixtures import (
    ADMIN, get_case, case_version, find_party, post_fee_charge,
    setup_hearing_case, setup_hearing_case_with_paid_deposit,
    setup_filed_case_with_party, setup_paid_deposit_on_filed_case,
)

ADM = ADMIN


def _schedule_3h_hearing(api, case_id):
    return validate_success(api.create_hearing(case_id, create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:00:00Z",
        end_at="2026-06-20T12:00:00Z", location="Room A"), ADM), 201)


# ---- Difficulty: estimated vs actual neutral compensation ----------------

def test_estimated_and_actual_neutral_comp_values(api):
    """PRD 3.2: "it takes the appointed neutral's `hourly_rate_cents`, multiplies it by the
    total planned duration in hours of every hearing on the case whose status is
    `SCHEDULED` ... and rounds the product half up to whole cents." PRD 3.8: "The charge's
    `amount_cents` is computed as the logged `hours` multiplied by the neutral's
    `hourly_rate_cents`, rounded half up to whole cents." PRD 3.2: "The **actual**
    compensation ... always equals the case's `posted_fee_cents`".

    Design: Difficulty/dual_variant_calc/neutral_estimated_vs_actual_compensation
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    _schedule_3h_hearing(api, ctx["case"]["id"])
    post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 4)
    case = get_case(api, ctx["case"]["id"])
    assert case["estimated_neutral_fee_cents"] == 150_000
    assert case["actual_neutral_fee_cents"] == 200_000


def test_estimated_and_actual_neutral_comp_diverge(api):
    """PRD 3.2: "The two figures diverge whenever the hours actually logged differ from the
    planned hearing durations."

    Design: Difficulty/dual_variant_calc/neutral_estimated_vs_actual_compensation
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    _schedule_3h_hearing(api, ctx["case"]["id"])
    post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 4)
    case = get_case(api, ctx["case"]["id"])
    assert case["estimated_neutral_fee_cents"] != case["actual_neutral_fee_cents"]


# ---- Difficulty: party fee allocation floor-then-remainder ---------------

def test_party_fee_allocation_floor_then_remainder(api):
    """PRD 3.8: "each party's base share is the total multiplied by that party's
    `share_pct` divided by 100, rounded **down** to whole cents. Second, the leftover ...
    is distributed one cent at a time to the parties in that same `created_at`-ascending
    order, giving one extra cent to each of the first several parties until the leftover is
    exhausted."

    Design: Difficulty/combinatorial_formula/party_fee_allocation_floor_then_remainder
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=200_000, hourly_rate_cents=100_001)
    post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 1)
    assert get_case(api, ctx["case"]["id"])["posted_fee_cents"] == 100_001
    assert find_party(api, ctx["case"]["id"], ctx["pA"]["id"])["allocated_fee_share_cents"] == 50_001
    assert find_party(api, ctx["case"]["id"], ctx["pB"]["id"])["allocated_fee_share_cents"] == 50_000


def test_party_fee_allocation_accounts_for_every_cent(api):
    """PRD 3.8: "The parties' shares of the posted fees are allocated by a pinned two-step
    procedure so that every cent is accounted for." PRD 3.8: "The case's `posted_fee_cents`
    is the sum of `amount_cents` across the case's charges whose status is `POSTED`".

    Design: Difficulty/combinatorial_formula/party_fee_allocation_floor_then_remainder
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=200_000, hourly_rate_cents=100_001)
    post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 1)
    posted = get_case(api, ctx["case"]["id"])["posted_fee_cents"]
    a = find_party(api, ctx["case"]["id"], ctx["pA"]["id"])["allocated_fee_share_cents"]
    b = find_party(api, ctx["case"]["id"], ctx["pB"]["id"])["allocated_fee_share_cents"]
    assert posted == 100_001
    assert a + b == posted


# ---- Difficulty: fee reversal restores the deposit balance ---------------

def test_fee_reversal_restores_deposit_balance(api):
    """PRD 3.8: "reversal is compensating and recomputes the case's `posted_fee_cents`,
    `actual_neutral_fee_cents`, and `deposit_balance_cents` — returning the balance to its
    pre-charge value".

    Design: Difficulty/compensating_invariant/fee_reversal_restores_deposit_balance
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    fc = post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 4)
    validate_success(api.reverse_fee_charge(fc["id"], ADM), 200)
    case = get_case(api, ctx["case"]["id"])
    assert case["posted_fee_cents"] == 0
    assert case["deposit_balance_cents"] == 500_000


def test_fee_post_then_reverse_conserves_balance(api):
    """PRD 3.8: "The case's `deposit_balance_cents` is the paid deposits less the posted
    fees less the administrative fee". PRD 3.8: "reversal is compensating and recomputes
    the case's `posted_fee_cents`, `actual_neutral_fee_cents`, and `deposit_balance_cents`
    — returning the balance to its pre-charge value".

    Design: Difficulty/compensating_invariant/fee_reversal_restores_deposit_balance
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    fc = post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 4)
    posted = get_case(api, ctx["case"]["id"])
    assert posted["posted_fee_cents"] == 200_000
    assert posted["deposit_balance_cents"] == 300_000
    validate_success(api.reverse_fee_charge(fc["id"], ADM), 200)
    restored = get_case(api, ctx["case"]["id"])
    assert restored["posted_fee_cents"] == 0
    assert restored["deposit_balance_cents"] == 500_000


# ---- Corner: fiscal gate / computed reads / immediate consistency --------

def test_fee_charge_exceeds_balance_returns_insufficient_deposit(api):
    """PRD 3.8: "a fiscal gate — the charge's `amount_cents` must not exceed the case's
    current `deposit_balance_cents`, otherwise the post is rejected with
    `ERR_INSUFFICIENT_DEPOSIT`."

    Design: Corner/validations/fee_charge_exceeds_balance_returns_insufficient_deposit
    """
    ctx = setup_hearing_case(api, hourly_rate_cents=50_000)  # no paid deposit -> balance 0
    resp = api.create_fee_charge(ctx["case"]["id"], create_fee_charge_payload(
        neutral_id=ctx["neutral"]["id"], hours=1,
        expected_case_version=case_version(api, ctx["case"]["id"])), ADM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DEPOSIT.value)


def test_pay_deposit_updates_case_paid_deposit_computed_read(api):
    """PRD 3.8: "payment stamps `paid_at` with the logical clock and recomputes the case's
    `paid_deposit_cents` and `deposit_balance_cents`." PRD 3.8: "The case's
    `paid_deposit_cents` is the sum of `amount_cents` across the case's deposits whose
    status is `PAID`."

    Design: Corner/endpoints/pay_deposit_updates_case_paid_deposit_computed_read
    """
    ctx = setup_paid_deposit_on_filed_case(api, amount_cents=100_000)
    case = get_case(api, ctx["case"]["id"])
    assert case["paid_deposit_cents"] == 100_000
    assert case["deposit_balance_cents"] == 100_000


def test_list_fee_charges_filtered_by_neutral_reverse_fk(api):
    """PRD 4 (endpoint): "List fee charges (paginated; optional case_id / neutral_id
    filters)". PRD 3.8: "The charge's `amount_cents` is computed as the logged `hours`
    multiplied by the neutral's `hourly_rate_cents`, rounded half up to whole cents."

    Design: Corner/endpoints/list_fee_charges_filtered_by_neutral_reverse_fk
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    fc = post_fee_charge(api, ctx["case"]["id"], ctx["neutral"]["id"], 4)
    data, _ = validate_paginated(api.list_fee_charges(ADM, params={"neutral_id": ctx["neutral"]["id"]}))
    found = [f for f in data if f["id"] == fc["id"]]
    assert found and found[0]["amount_cents"] == 200_000


def test_deposit_pay_immediately_reflected_in_pay_response(api):
    """PRD 3.8: "A `Party` pays a requested deposit, moving it from `REQUESTED` to `PAID`;
    payment stamps `paid_at` with the logical clock".

    Design: Corner/consistency_model/deposit_pay_immediately_reflected_in_pay_response
    """
    ctx = setup_filed_case_with_party(api, clock="2026-06-05T00:00:00Z")
    dep = validate_success(api.create_deposit(create_deposit_payload(
        case_id=ctx["case"]["id"], amount_cents=100_000), ADM), 201)
    data = validate_success(api.pay_deposit(dep["id"], make_party_headers(ctx["pA"]["id"])), 200)
    assert data["status"] == "PAID"
    assert data["paid_at"] is not None
