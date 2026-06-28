"""Entitlement valuation, à-la-carte pricing, and credit-consumption boundaries.

Difficulty queue (A): dual-variant grants, the three-input non-linear à-la-carte
formula, the pinned plan-change proration rounding, and the credit-count boundary.
Corner queue (B): med-tier dental surcharge, downgrade proration, chronological
consumption totals, and the derived-balance reconciliation.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    set_clock,
    run_epoch,
    create_plan_with_services,
    create_clinic,
    create_account_and_membership,
    add_pet,
    activate_membership,
    record_visit,
    make_member_headers,
    plan_change_payload,
    first_active_term,
    term_by_index,
    get_term,
    list_term_credits,
    get_account,
    TEST_USERS,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================
def test_entitlement_grant_differs_enrollment_vs_renewal(api):
    """PRD §3.4: "The renewal grant re-reads the catalogue at the renewal instant,
    which has a consequence worth stating plainly: an inclusion line that was retired
    at some point during the prior term is not re-granted on the successor term,
    because it is no longer `ACTIVE` when the successor is valued."
    PRD §3.4: "The term's `entitlement_granted_cents` is the sum, over every created
    bucket, of that bucket's granted quantity multiplied by its unit value in cents".

    Design: Difficulty/dual_variant_calc/entitlement_grant_enrollment_vs_renewal_on_contract_term
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, services = create_plan_with_services(
        [
            {"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000},
            {"service_code": "VACCINE", "included_quantity": 3, "unit_value_cents": 3500},
            {"service_code": "DENTAL", "included_quantity": 1, "unit_value_cents": 22000},
        ],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=3000,
    )
    dental_ps = next(s for s in services if s["service_code"] == "DENTAL")
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=True
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    term1 = term_by_index(membership["id"], 1)
    assert term1["entitlement_granted_cents"] == 44500, (
        f"enrollment grant should be 2*6000 + 3*3500 + 1*22000 = 44500, "
        f"got {term1['entitlement_granted_cents']}"
    )

    # Retire DENTAL mid-term, then run the term to expiry past 2027-01-01.
    get_success_data(api.retire_plan_service(dental_ps["id"], PLAN_ADMIN))
    set_clock("2027-01-02T00:00:00Z")
    run_epoch()

    term2 = term_by_index(membership["id"], 2)
    assert term2 is not None, "successor term (term_index=2) must exist after renewal"
    assert term2["entitlement_granted_cents"] == 22500, (
        f"renewal grant should drop DENTAL: 2*6000 + 3*3500 = 22500, "
        f"got {term2['entitlement_granted_cents']}"
    )
    dental_credits = [c for c in list_term_credits(term2["id"], service_code="DENTAL")
                      if c["status"] == "OPEN"]
    assert dental_credits == [], "successor term must have no OPEN DENTAL credit"


def test_early_cancel_settlement_uses_gross_basis(api):
    """PRD §3.8: "The unused value is the fees paid minus the consumed value, floored
    at zero so it is never negative. From that unused value an early-termination fee is
    taken, equal to the lesser of a flat 5000 cents and the unused value itself, so the
    fee never exceeds what is available. The settlement credit applied to the member's
    `wallet_credit_cents` is then the unused value minus the early-termination fee,
    again floored at zero."

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_discounted_basis_on_membership
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=3000,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=False
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    # Second monthly cycle.
    set_clock("2026-02-01T00:00:00Z")
    run_epoch()

    cancel_res = api.cancel_membership(membership["id"], make_member_headers(account["id"]))
    cancelled = validate_success(cancel_res, 200)
    assert cancelled["status"] == "CANCEL_PENDING"

    # fees_paid = 3000 + 4500 + 4500 = 12000; consumed 0; unused 12000;
    # ETF = min(5000, 12000) = 5000; settlement = 7000.
    # Wallet: -3000 - 4500 - 4500 + 7000 = -5000.
    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -5000, (
        f"gross-basis settlement should leave wallet at -5000, got {acct['wallet_credit_cents']}"
    )


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================
def test_alacarte_dental_large_dog_three_input_formula(api):
    """PRD §3.5: "a pet weighing at least 25 kg adds a surcharge of 4000 cents".
    PRD §3.5: "The gross amount is the base plus the surcharge. The member discount is
    then applied with the rounding order pinned: first compute the discount as the gross
    multiplied by the plan's `alacarte_discount_pct` and round that product half up to a
    whole cent, then subtract the rounded discount from the gross to obtain `charged_cents`."
    PRD §3.5: "if the plan has no inclusion line for that code ... the base instead comes
    from a catalogue default of 6000 cents for `EXAM`, 3500 cents for `VACCINE`, and
    22000 cents for `DENTAL`."

    Design: Difficulty/combinatorial_formula/alacarte_price_three_input_nonlinear_dental_tier
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [
            {"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000},
            {"service_code": "VACCINE", "included_quantity": 1, "unit_value_cents": 3500},
        ],
        tier="ESSENTIAL", name="Essential", monthly_fee_cents=2500, annual_value_cents=30000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="BigDog", species="DOG", weight_kg=30)
    activate_membership(membership["id"], account["id"])

    visit = record_visit(membership["id"], pet["id"], clinic["id"], "DENTAL")
    # base 22000 (catalogue default, no DENTAL line) + 4000 surcharge = 26000;
    # discount = round(26000 * 0.20) = 5200; charged = 26000 - 5200 = 20800.
    assert visit["covered_by_credit"] is False
    assert visit["charged_cents"] == 20800, (
        f"30kg DENTAL à-la-carte should be 20800, got {visit['charged_cents']}"
    )


def test_plan_change_proration_rounds_once_at_end(api):
    """PRD §3.6: "The proration delta is the incoming daily rate minus the departing daily
    rate, multiplied by the days remaining, computed as an exact rational and rounded half
    up to a whole number of cents exactly once at the end; rounding the two daily rates first
    and then multiplying can differ and is not the rule."
    PRD §3.6: "The `change_kind` is `UPGRADE` when the target plan's monthly fee is greater
    than the current plan's monthly fee, and `DOWNGRADE` otherwise."
    PRD §3.6: "A positive delta — the upgrade case — is an additional charge that debits the
    wallet now".

    Design: Difficulty/combinatorial_formula/plan_change_proration_pinned_round_once
    """
    set_clock("2026-01-01T00:00:00Z")
    plus, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    premium, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 4, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plus["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    mem_v = membership["version"]

    set_clock("2026-01-16T00:00:00Z")
    pc_res = api.plan_change(
        membership["id"], plan_change_payload(premium["id"], mem_v),
        make_member_headers(account["id"]),
    )
    pcr = validate_success(pc_res, 200)
    assert pcr["change_kind"] == "UPGRADE"
    # cycle Jan1..Feb1 = 31 days; days remaining from Jan16 = 16.
    # delta = (9000/31 - 4500/31) * 16 = 4500/31*16 = 72000/31 = 2322.58 -> 2323.
    assert pcr["proration_delta_cents"] == 2323, (
        f"round-once proration should be 2323, got {pcr['proration_delta_cents']}"
    )
    # Wallet: activate debited 4500 (monthly, enrollment 0); upgrade debits +2323.
    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -6823, (
        f"wallet should be -4500 - 2323 = -6823, got {acct['wallet_credit_cents']}"
    )


# ===========================================================================
# Difficulty: boundary_precision_check (credit count Nth vs N+1)
# ===========================================================================
def test_credit_consumption_nth_covered_n_plus_one_alacarte(api):
    """PRD §3.5: "Stated as a boundary: the Nth visit of a service code is covered exactly
    when N is at most the granted quantity, and the very next visit after the bucket is full
    is billed à-la-carte."
    PRD §3.5: "When capacity remains ... the visit's `covered_by_credit` is set to true and
    its `charged_cents` to 0. When no capacity remains, the visit's `covered_by_credit` is
    false and its `charged_cents` is the à-la-carte price computed below".

    Design: Difficulty/boundary_precision_check/credit_consumption_nth_vs_n_plus_one_boundary_on_visits
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # N=1, covered
    v2 = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # N=2 == granted, covered
    v3 = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # N=3 == granted+1, à-la-carte

    assert v2["covered_by_credit"] is True
    assert v2["charged_cents"] == 0
    assert v3["covered_by_credit"] is False
    # gross 6000, discount round(6000*0.20)=1200, charged 4800.
    assert v3["charged_cents"] == 4800, f"3rd EXAM should be à-la-carte 4800, got {v3['charged_cents']}"


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_alacarte_dental_med_tier_surcharge(api):
    """PRD §3.5: "a pet weighing at least 10 kg but under 25 kg adds 1500 cents".
    PRD §3.5: "first compute the discount as the gross multiplied by the plan's
    `alacarte_discount_pct` and round that product half up to a whole cent, then subtract
    the rounded discount from the gross to obtain `charged_cents`."

    Design: Corner/calculations/dental_med_tier_surcharge_at_12kg
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="ESSENTIAL", name="Ess", monthly_fee_cents=2500, annual_value_cents=30000,
        alacarte_discount_pct=0.20,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="MedDog", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    visit = record_visit(membership["id"], pet["id"], clinic["id"], "DENTAL")
    # base 22000 (default) + 1500 (med tier) = 23500; discount round(23500*0.20)=4700; charged 18800.
    assert visit["covered_by_credit"] is False
    assert visit["charged_cents"] == 18800, (
        f"12kg DENTAL à-la-carte should be 18800, got {visit['charged_cents']}"
    )


def test_downgrade_proration_credits_wallet(api):
    """PRD §3.6: "The `change_kind` is `UPGRADE` when the target plan's monthly fee is greater
    than the current plan's monthly fee, and `DOWNGRADE` otherwise."
    PRD §3.6: "a negative delta — the downgrade case — is a credit that adds its absolute value
    to the wallet now."

    Design: Corner/calculations/downgrade_proration_credits_wallet
    """
    set_clock("2026-01-01T00:00:00Z")
    premium, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 4, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30, enrollment_fee_cents=0,
    )
    plus, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(premium["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    mem_v = membership["version"]

    set_clock("2026-01-16T00:00:00Z")
    pc_res = api.plan_change(
        membership["id"], plan_change_payload(plus["id"], mem_v), make_member_headers(account["id"])
    )
    pcr = validate_success(pc_res, 200)
    assert pcr["change_kind"] == "DOWNGRADE"
    # delta = (4500/31 - 9000/31) * 16 = -4500/31*16 = -2322.58 -> -2323.
    assert pcr["proration_delta_cents"] == -2323, (
        f"round-once downgrade proration should be -2323, got {pcr['proration_delta_cents']}"
    )
    # Wallet: activate debited 9000; downgrade credits +2323 -> -6677.
    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -6677, (
        f"wallet should be -9000 + 2323 = -6677, got {acct['wallet_credit_cents']}"
    )


def test_entitlement_consumed_after_two_exam_visits(api):
    """PRD §3.7: "The term's `entitlement_consumed_cents` is recomputed as the sum, over every
    credit bucket of that term regardless of its status, of the bucket's `consumed_quantity`
    multiplied by its `unit_value_cents`".
    PRD §3.7: "The term's `entitlement_balance_cents` is then the term's
    `entitlement_granted_cents` minus the freshly recomputed consumed total."

    Design: Corner/calculations/entitlement_consumed_chronological_after_two_exam_visits
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [
            {"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000},
            {"service_code": "VACCINE", "included_quantity": 3, "unit_value_cents": 3500},
            {"service_code": "DENTAL", "included_quantity": 1, "unit_value_cents": 22000},
        ],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])

    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")

    term = get_term(term["id"])
    assert term["entitlement_consumed_cents"] == 12000, (
        f"two EXAM visits consume 2*6000 = 12000, got {term['entitlement_consumed_cents']}"
    )
    assert term["entitlement_balance_cents"] == 32500, (
        f"balance = 44500 - 12000 = 32500, got {term['entitlement_balance_cents']}"
    )


def test_derived_balance_reconciles_after_one_visit(api):
    """PRD §3.7: "After every event that can touch the credit ledger — recording a visit,
    voiding a visit, a plan change, or a billing-epoch run — the system reconciles the owning
    contract term's derived balances so they always agree with the ServiceCredit ledger."
    PRD §3.4: "The term's `entitlement_granted_cents` is the sum, over every created bucket,
    of that bucket's granted quantity multiplied by its unit value in cents".

    Design: Corner/cross_cutting_complexity_layers/derived_entitlement_balance_reconciles_after_visit
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])

    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")

    term = get_term(term["id"])
    assert term["entitlement_granted_cents"] == 12000
    assert term["entitlement_balance_cents"] == 6000, (
        f"one covered EXAM visit drops balance to 6000, got {term['entitlement_balance_cents']}"
    )
