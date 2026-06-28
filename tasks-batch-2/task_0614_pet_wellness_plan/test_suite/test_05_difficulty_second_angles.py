"""Second-angle difficulty tests (queue A).

Each difficulty instance carries two tests: the primary in test_01-test_03 and a
distinct, equally PRD-derivable facet of the same rule here. Tags match the
primary so both map to the same upstream §1.8 instance.
"""
from test_helpers import (
    validate_success,
    validate_error,
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
    get_membership,
    get_visit,
    TEST_USERS,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
CLINIC_STAFF = TEST_USERS["clinic_staff_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]


def _plus_plan():
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    return plan


# ===========================================================================
# dual_variant_calc
# ===========================================================================
def test_enrollment_grant_seeds_balance_equal_to_granted(api):
    """PRD §3.4: "`entitlement_consumed_cents` is initialised to 0 and
    `entitlement_balance_cents` to the granted total."
    PRD §3.4: "The term's `entitlement_granted_cents` is the sum, over every created bucket,
    of that bucket's granted quantity multiplied by its unit value in cents".

    Design: Difficulty/dual_variant_calc/entitlement_grant_enrollment_vs_renewal_on_contract_term
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [
            {"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000},
            {"service_code": "VACCINE", "included_quantity": 3, "unit_value_cents": 3500},
            {"service_code": "DENTAL", "included_quantity": 1, "unit_value_cents": 22000},
        ],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=3000,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    term1 = term_by_index(membership["id"], 1)
    assert term1["entitlement_granted_cents"] == 44500
    assert term1["entitlement_consumed_cents"] == 0
    assert term1["entitlement_balance_cents"] == 44500, (
        "at enrolment grant, balance equals granted total with nothing consumed"
    )


def test_settlement_values_consumed_at_full_catalogue(api):
    """PRD §3.8: "The value of credits already consumed is the term's
    `entitlement_consumed_cents`, with consumed credits valued at full catalogue unit value."
    PRD §3.8: "This gross basis — valuing consumed credits at full catalogue value — is the
    pinned rule; an alternative that valued consumed credits at the discounted à-la-carte
    price would yield a larger refund and is deliberately not used."

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_discounted_basis_on_membership
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=False
    )
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # wallet -9000
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # covered, consumed 6000
    set_clock("2026-02-01T00:00:00Z")
    run_epoch()  # second cycle 9000 -> wallet -18000

    validate_success(api.cancel_membership(membership["id"], make_member_headers(account["id"])), 200)

    # fees_paid 18000, consumed (gross) 6000, unused 12000, ETF 5000, settlement 7000.
    # net-discounted basis would value consumed at 4200 and refund more (-9200); gross gives -11000.
    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -11000, (
        f"gross-basis settlement should leave wallet at -11000, got {acct['wallet_credit_cents']}"
    )


# ===========================================================================
# combinatorial_formula
# ===========================================================================
def test_alacarte_nondental_has_no_surcharge(api):
    """PRD §3.5: "A surcharge applies only to dental visits and is driven by the pet's
    `weight_kg`: a pet weighing at least 25 kg adds a surcharge of 4000 cents, a pet weighing at
    least 10 kg but under 25 kg adds 1500 cents, and a lighter pet adds nothing; for non-dental
    services the surcharge is zero."
    PRD §3.5: "first compute the discount as the gross multiplied by the plan's
    `alacarte_discount_pct` and round that product half up to a whole cent, then subtract the
    rounded discount from the gross to obtain `charged_cents`."

    Design: Difficulty/combinatorial_formula/alacarte_price_three_input_nonlinear_dental_tier
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="ESSENTIAL", name="Essential", monthly_fee_cents=2500, annual_value_cents=30000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="BigDog", species="DOG", weight_kg=30)
    activate_membership(membership["id"], account["id"])
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # covered (granted 1)

    v2 = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # à-la-carte EXAM
    # base 6000, no surcharge (non-dental), discount round(6000*0.20)=1200, charged 4800.
    assert v2["covered_by_credit"] is False
    assert v2["charged_cents"] == 4800, (
        f"non-dental à-la-carte should carry no surcharge: 4800, got {v2['charged_cents']}"
    )


def test_plan_change_apply_updates_snapshot_and_version(api):
    """PRD §3.6: "Applying the change adjusts the wallet by the proration delta, updates the
    membership's `plan_id` and re-snapshots its `monthly_fee_cents`, and increments the
    membership's `version` by one."
    PRD §3.6: "capturing the `membership_id`, the `from_plan_id` that was in force before the
    change, the `to_plan_id` target".

    Design: Difficulty/combinatorial_formula/plan_change_proration_pinned_round_once
    """
    set_clock("2026-01-01T00:00:00Z")
    plus = _plus_plan()
    premium, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 4, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plus["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    v_before = membership["version"]

    set_clock("2026-01-16T00:00:00Z")
    pcr = validate_success(
        api.plan_change(membership["id"], plan_change_payload(premium["id"], v_before),
                        make_member_headers(account["id"])),
        200,
    )
    assert pcr["from_plan_id"] == plus["id"]
    assert pcr["to_plan_id"] == premium["id"]
    after = get_membership(membership["id"])
    assert after["plan_id"] == premium["id"]
    assert after["monthly_fee_cents"] == 9000, "monthly_fee_cents must re-snapshot from the new plan"
    assert after["version"] == v_before + 1, "plan-change increments the membership version by one"


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
def test_renewal_passes_through_renewal_pending(api):
    """PRD §3.9: "A term that is `ACTIVE`, whose membership has `auto_renew` set to true, and
    for which the current clock instant has reached the point seven days before the term's
    `ends_at` (the renewal window), enters renewal by moving from `ACTIVE` to `RENEWAL_PENDING`;
    this merely flags the impending renewal and grants no credits yet."

    Design: Difficulty/non_linear_state_machine/contract_term_renewal_cycle_active_renewalpending_expired_successor_active
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=True
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term1 = first_active_term(membership["id"])

    set_clock("2026-12-28T00:00:00Z")  # within renewal window, before ends_at
    run_epoch()

    refreshed = get_term(term1["id"])
    assert refreshed["status"] == "RENEWAL_PENDING", (
        "inside the renewal window but before ends_at, the term is RENEWAL_PENDING"
    )
    assert term_by_index(membership["id"], 2) is None, "no successor term is created yet"


def test_membership_branches_enrolled_to_cancel_pending(api):
    """PRD §3.8: "Cancellation moves the membership from `ENROLLED` or `SUSPENDED` to
    `CANCEL_PENDING`, computes the early-termination settlement described below and records its
    credit on the wallet, sets `auto_renew` to false, marks the contract for termination at the
    end of the current cycle by moving the active contract term from `ACTIVE` to `TERMINATED`,
    forfeits every still-`OPEN` credit bucket on that term by moving each from `OPEN` to
    `FORFEITED` (whereupon the term's frozen balance is the basis for settlement), and increments
    the membership's `version` by one."

    Design: Difficulty/non_linear_state_machine/membership_branch_and_suspend_resume_cycle
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    v_before = membership["version"]

    cancelled = validate_success(
        api.cancel_membership(membership["id"], make_member_headers(account["id"])), 200
    )
    assert cancelled["status"] == "CANCEL_PENDING", "ENROLLED branches to CANCEL_PENDING on cancel"
    assert cancelled["auto_renew"] is False
    assert cancelled["version"] == v_before + 1


# ===========================================================================
# transitive_cascade
# ===========================================================================
def test_cancel_sets_auto_renew_false_and_bumps_version(api):
    """PRD §3.8: "forfeits every still-`OPEN` credit bucket on that term by moving each from
    `OPEN` to `FORFEITED` (whereupon the term's frozen balance is the basis for settlement),
    and increments the membership's `version` by one."

    Design: Difficulty/transitive_cascade/cancel_cascade_membership_term_credit_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])
    v_before = membership["version"]

    cancelled = validate_success(
        api.cancel_membership(membership["id"], make_member_headers(account["id"])), 200
    )
    assert cancelled["auto_renew"] is False
    assert cancelled["version"] == v_before + 1
    # The OPEN EXAM bucket becomes FORFEITED as the cascade leaf.
    credits = list_term_credits(term["id"], service_code="EXAM")
    assert credits and credits[0]["status"] == "FORFEITED"


def test_successor_term_grants_fresh_open_buckets(api):
    """PRD §3.9: "The successor term is granted a fresh set of credit buckets by the forward
    valuation of §3.4 (re-reading the catalogue at the renewal instant)".
    PRD §3.4: "For each such line it creates one `ServiceCredit` bucket whose `granted_quantity`
    equals the line's `included_quantity` ... the bucket opens `OPEN` if the granted quantity is
    greater than zero".

    Design: Difficulty/transitive_cascade/renewal_cascade_expire_forfeit_grant_depth2
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()  # EXAM 2@6000
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=True
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    set_clock("2026-12-28T00:00:00Z")
    run_epoch()
    set_clock("2027-01-02T00:00:00Z")
    run_epoch()

    term2 = term_by_index(membership["id"], 2)
    new_credits = list_term_credits(term2["id"], service_code="EXAM")
    assert new_credits, "successor term must carry a fresh EXAM bucket"
    assert new_credits[0]["granted_quantity"] == 2
    assert new_credits[0]["consumed_quantity"] == 0
    assert new_credits[0]["status"] == "OPEN"


# ===========================================================================
# boundary_precision_check
# ===========================================================================
def test_credit_bucket_exhausts_at_granted_quantity(api):
    """PRD §3.5: "When capacity remains, the system increments that bucket's `consumed_quantity`
    by one; if the consumed quantity then equals the granted quantity, the bucket's `status`
    becomes `EXHAUSTED`".

    Design: Difficulty/boundary_precision_check/credit_consumption_nth_vs_n_plus_one_boundary_on_visits
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()  # EXAM granted 2
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])

    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # 1st
    bucket_after_1 = list_term_credits(term["id"], service_code="EXAM")[0]
    assert bucket_after_1["status"] == "OPEN", "still OPEN after 1 of 2 consumed"

    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # 2nd == granted
    bucket_after_2 = list_term_credits(term["id"], service_code="EXAM")[0]
    assert bucket_after_2["consumed_quantity"] == 2
    assert bucket_after_2["status"] == "EXHAUSTED", "bucket EXHAUSTED once consumed reaches granted"


def test_renewal_window_not_open_one_day_early(api):
    """PRD §3.9: "for which the current clock instant has reached the point seven days before
    the term's `ends_at` (the renewal window), enters renewal by moving from `ACTIVE` to
    `RENEWAL_PENDING`".

    Design: Difficulty/boundary_precision_check/renewal_window_date_boundary_on_run_epoch
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=True
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term1 = first_active_term(membership["id"])

    set_clock("2026-12-24T00:00:00Z")  # 8 days before ends_at 2027-01-01 -> not yet in window
    run_epoch()
    assert get_term(term1["id"])["status"] == "ACTIVE", (
        "eight days before ends_at, the renewal window has not opened; term stays ACTIVE"
    )


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
# NOTE: test_visit_on_suspended_membership_no_active_term was DELETED.
# Its premise — that a SUSPENDED membership "has no ACTIVE term" — directly
# contradicts PRD §3.6: "The contract-term clock continues to run during
# suspension — the term is not extended — and existing credit buckets remain
# `OPEN`." A suspended membership therefore retains its ACTIVE term. Suspension
# cascades the pet to SUSPENDED (PRD §3.6), and PRD §2.9 pins the pet-active
# check (ERR_PET_NOT_ACTIVE) BEFORE the active-term resolution. A faithful
# PRD-only implementation deterministically returns ERR_PET_NOT_ACTIVE here,
# not ERR_NO_ACTIVE_TERM, so the asserted outcome is not uniquely derivable
# from PRD (STEP 1b). ERR_NO_ACTIVE_TERM is faithfully covered by
# test_visit_on_pending_membership_no_active_term (PENDING_PAYMENT, no term).


def test_void_blocked_visit_stays_completed(api):
    """PRD §3.5: "only when the owning contract term is `ACTIVE`, failing which it is rejected
    with `ERR_TERM_NOT_ACTIVE_FOR_VOID`."
    PRD §3.5: "A void moves the visit's `status` from `COMPLETED` to `VOIDED`."

    Design: Difficulty/cross_entity_state_dependency/visit_void_requires_contract_term_active
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    visit = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")
    api.cancel_membership(membership["id"], make_member_headers(account["id"]))  # term -> TERMINATED

    res = api.void_visit(visit["id"], CLINIC_STAFF)
    validate_error(res, "ERR_TERM_NOT_ACTIVE_FOR_VOID")
    assert get_visit(visit["id"])["status"] == "COMPLETED", "a rejected void leaves the visit COMPLETED"


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
def test_visit_at_term_start_instant_inside_window(api):
    """PRD §3.5: "The visit instant must fall inside the active term's window, treated as
    inclusive of `starts_at` and exclusive of `ends_at`".

    Design: Difficulty/resource_temporal_overlap/visit_must_lie_in_half_open_contract_term_window
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # term starts_at == clock 2026-01-01

    # Clock is exactly at starts_at (the inclusive left edge): a visit here is accepted.
    res = api.record_visit(
        membership["id"],
        {"enrolled_pet_id": pet["id"], "clinic_id": clinic["id"], "service_code": "EXAM"},
        CLINIC_STAFF,
    )
    visit = validate_success(res, 201)
    assert visit["status"] == "COMPLETED", "a visit exactly at starts_at is inside the term window"


# ===========================================================================
# compensating_invariant
# ===========================================================================
def test_void_restores_exhausted_bucket_to_open(api):
    """PRD §3.5: "If the visit had been covered by a credit, the system restores one unit to the
    bucket it consumed by decrementing that bucket's `consumed_quantity` by one, and if the
    bucket had been full it moves from `EXHAUSTED` back to `OPEN`."

    Design: Difficulty/compensating_invariant/void_covered_visit_conserves_entitlement_consumed
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])
    visit = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # consumes the only credit
    assert list_term_credits(term["id"], service_code="EXAM")[0]["status"] == "EXHAUSTED"

    validate_success(api.void_visit(visit["id"], CLINIC_STAFF), 200)

    bucket = list_term_credits(term["id"], service_code="EXAM")[0]
    assert bucket["consumed_quantity"] == 0
    assert bucket["status"] == "OPEN", "voiding the covering visit moves the full bucket back to OPEN"


def test_void_alacarte_returns_wallet_to_pre_visit_value(api):
    """PRD §3.5: "If instead the visit had been billed à-la-carte, the system credits its
    `charged_cents` back to the member's `wallet_credit_cents`."
    PRD §3.5: "in that case the à-la-carte charge debits the member's `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/void_alacarte_visit_conserves_wallet_credit
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="ESSENTIAL", name="Ess", monthly_fee_cents=2500, annual_value_cents=30000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="MedDog", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # wallet -2500
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # covered (granted 1)
    wallet_before = get_account(account["id"])["wallet_credit_cents"]
    v2 = record_visit(membership["id"], pet["id"], clinic["id"], "DENTAL")  # à-la-carte dental
    assert v2["covered_by_credit"] is False
    charged = v2["charged_cents"]
    assert get_account(account["id"])["wallet_credit_cents"] == wallet_before - charged

    validate_success(api.void_visit(v2["id"], CLINIC_STAFF), 200)

    assert get_account(account["id"])["wallet_credit_cents"] == wallet_before, (
        "voiding the à-la-carte visit refunds its exact charge, restoring the pre-visit wallet"
    )
    assert get_visit(v2["id"])["status"] == "VOIDED"
