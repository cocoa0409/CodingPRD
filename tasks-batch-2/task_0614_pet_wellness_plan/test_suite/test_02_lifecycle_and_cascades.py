"""Membership and contract-term lifecycle: renewal cycle, branch+resume cycle,
cancellation cascade, renewal cascade, and the renewal-window date boundary.

Difficulty queue (A): non_linear_state_machine, transitive_cascade,
boundary_precision_check (renewal window). Corner queue (B): invalid transitions,
preconditions, side effects, terminal lockdown, and state-related errors.
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
    term_by_index,
    first_active_term,
    get_term,
    list_term_credits,
    get_pet,
    get_account,
    list_billing_cycles,
    TEST_USERS,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]


def _plus_plan():
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    return plan


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================
def test_contract_term_renewal_cycle_returns_to_active(api):
    """PRD §3.9: "Once the clock instant reaches or passes the term's `ends_at`, a term in
    `RENEWAL_PENDING` expires: it moves from `RENEWAL_PENDING` to `EXPIRED` ... and a successor
    term is created — its `term_index` is one greater than the expiring term's, its `starts_at`
    equals the expiring term's `ends_at`, its `ends_at` is 365 days later, and its `status` is
    `ACTIVE`."

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

    set_clock("2026-12-28T00:00:00Z")  # inside renewal window -> RENEWAL_PENDING
    run_epoch()
    set_clock("2027-01-02T00:00:00Z")  # past ends_at -> EXPIRED + successor
    run_epoch()

    term1 = term_by_index(membership["id"], 1)
    assert term1["status"] == "EXPIRED", f"term 1 should be EXPIRED, got {term1['status']}"
    term2 = term_by_index(membership["id"], 2)
    assert term2 is not None, "successor term (term_index=2) must exist"
    assert term2["status"] == "ACTIVE", f"term 2 should be ACTIVE, got {term2['status']}"


def test_membership_suspend_resume_cycle(api):
    """PRD §3.6: "It moves the membership from `ENROLLED` to `SUSPENDED`, cascades every pet
    from `ENROLLED` to `SUSPENDED`".
    PRD §3.6: "Resumption moves the membership from `SUSPENDED` back to `ENROLLED`, cascades
    back to `ENROLLED` exactly those pets that the suspend action had suspended".

    Design: Difficulty/non_linear_state_machine/membership_branch_and_suspend_resume_cycle
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    api.suspend_membership(membership["id"], make_member_headers(account["id"]))

    resumed = validate_success(
        api.resume_membership(membership["id"], make_member_headers(account["id"])), 200
    )
    assert resumed["status"] == "ENROLLED"
    pet_after = get_pet(membership["id"], pet["id"])
    assert pet_after["status"] == "ENROLLED", "resume must restore pet to ENROLLED"


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================
def test_cancel_cascades_term_terminated_credits_forfeited(api):
    """PRD §3.8: "Cancellation moves the membership from `ENROLLED` or `SUSPENDED` to
    `CANCEL_PENDING` ... marks the contract for termination at the end of the current cycle by
    moving the active contract term from `ACTIVE` to `TERMINATED`, forfeits every still-`OPEN`
    credit bucket on that term by moving each from `OPEN` to `FORFEITED`".

    Design: Difficulty/transitive_cascade/cancel_cascade_membership_term_credit_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])

    cancelled = validate_success(
        api.cancel_membership(membership["id"], make_member_headers(account["id"])), 200
    )
    assert cancelled["status"] == "CANCEL_PENDING"

    term_after = get_term(term["id"])
    assert term_after["status"] == "TERMINATED", (
        f"term should be TERMINATED after cancel, got {term_after['status']}"
    )
    credits = list_term_credits(term["id"])
    assert credits, "term should have at least one credit bucket"
    assert all(c["status"] == "FORFEITED" for c in credits), (
        f"every credit must be FORFEITED, got {[c['status'] for c in credits]}"
    )


def test_renewal_cascade_forfeits_old_grants_new(api):
    """PRD §3.9: "a term in `RENEWAL_PENDING` expires: it moves from `RENEWAL_PENDING` to
    `EXPIRED`, every still-`OPEN` credit bucket on it is forfeited by moving to `FORFEITED`
    because unused credits do not roll over, and a successor term is created".
    PRD §3.9: "The successor term is granted a fresh set of credit buckets by the forward
    valuation of §3.4 (re-reading the catalogue at the renewal instant)".

    Design: Difficulty/transitive_cascade/renewal_cascade_expire_forfeit_grant_depth2
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()  # EXAM 2@6000 -> granted 12000
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

    term1 = term_by_index(membership["id"], 1)
    old_credits = list_term_credits(term1["id"])
    assert old_credits, "term 1 should have credit buckets"
    assert all(c["status"] == "FORFEITED" for c in old_credits), (
        f"unused term-1 credits must be FORFEITED, got {[c['status'] for c in old_credits]}"
    )

    term2 = term_by_index(membership["id"], 2)
    new_credits = list_term_credits(term2["id"])
    assert any(c["status"] == "OPEN" for c in new_credits), "successor term must have OPEN credit"
    assert term2["entitlement_granted_cents"] == 12000, (
        f"successor grant should be 2*6000 = 12000, got {term2['entitlement_granted_cents']}"
    )


# ===========================================================================
# Difficulty: boundary_precision_check (renewal-window date)
# ===========================================================================
def test_renewal_window_opens_exactly_seven_days_before(api):
    """PRD §3.9: "A term that is `ACTIVE`, whose membership has `auto_renew` set to true, and
    for which the current clock instant has reached the point seven days before the term's
    `ends_at` (the renewal window), enters renewal by moving from `ACTIVE` to `RENEWAL_PENDING`".

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

    set_clock("2026-12-24T00:00:00Z")  # 8 days before ends_at 2027-01-01 -> still ACTIVE
    run_epoch()
    assert get_term(term1["id"])["status"] == "ACTIVE", "8 days out: term stays ACTIVE"

    set_clock("2026-12-25T00:00:00Z")  # exactly 7 days before -> RENEWAL_PENDING
    run_epoch()
    assert get_term(term1["id"])["status"] == "RENEWAL_PENDING", (
        "exactly 7 days out: term flips to RENEWAL_PENDING"
    )


# ===========================================================================
# Corner: state_machines
# ===========================================================================
def test_activate_already_enrolled_rejected(api):
    """PRD §3.3: "Activation is permitted only from `PENDING_PAYMENT`; attempting it from any
    other status is rejected with `ERR_MEMBERSHIP_NOT_PENDING`."

    Design: Corner/state_machines/activate_from_already_enrolled_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    res = api.activate_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_MEMBERSHIP_NOT_PENDING")


def test_activate_without_enrolled_pet_rejected(api):
    """PRD §3.3: "Activation additionally requires that at least one pet under the membership
    has status `ENROLLED`, failing which it is rejected with `ERR_NO_ENROLLED_PET`".

    Design: Corner/state_machines/activate_without_enrolled_pet_returns_no_enrolled_pet
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)

    res = api.activate_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_NO_ENROLLED_PET")


def test_activate_on_retired_plan_rejected(api):
    """PRD §3.3: "that the membership's plan is still `ACTIVE` rather than retired, failing
    which it is rejected with `ERR_PLAN_RETIRED`".

    Design: Corner/state_machines/activate_on_retired_plan_returns_plan_retired
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    validate_success(api.retire_plan(plan["id"], PLAN_ADMIN), 200)

    res = api.activate_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_PLAN_RETIRED")


def test_resume_non_suspended_rejected(api):
    """PRD §3.6: "Resumption reverses this and is permitted only from `SUSPENDED`, failing
    which it is rejected with `ERR_MEMBERSHIP_NOT_SUSPENDED`".

    Design: Corner/state_machines/resume_non_suspended_returns_not_suspended
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    res = api.resume_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_MEMBERSHIP_NOT_SUSPENDED")


def test_cancel_after_finalize_rejected_terminal(api):
    """PRD §3.8: "Cancellation is permitted only when the membership is `ENROLLED` or
    `SUSPENDED`, failing which it is rejected with `ERR_MEMBERSHIP_NOT_CANCELLABLE`."
    PRD §3.8: "Finalisation moves the membership from `CANCEL_PENDING` to `CANCELLED` ...
    `CANCELLED` is the terminal state of the membership lifecycle."

    Design: Corner/state_machines/finalize_cancel_then_terminal_lockdown
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    api.cancel_membership(membership["id"], make_member_headers(account["id"]))
    validate_success(api.finalize_cancel_membership(membership["id"], BILLING_ADMIN), 200)

    res = api.cancel_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_MEMBERSHIP_NOT_CANCELLABLE")


def test_suspend_zeroes_next_billing_fee(api):
    """PRD §3.6: "while suspended, future billing cycles charge a `fee_charged_cents` of 0."
    PRD §3.9: "A membership that is `SUSPENDED` is charged a `fee_charged_cents` of 0".

    Design: Corner/state_machines/suspend_zeroes_fee_on_next_billing_cycle
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # wallet -4500
    api.suspend_membership(membership["id"], make_member_headers(account["id"]))

    set_clock("2026-02-01T00:00:00Z")
    run_epoch()

    cycles, _meta = list_billing_cycles(membership["id"])
    feb_cycles = [c for c in cycles if c["fee_charged_cents"] == 0]
    assert feb_cycles, "a suspended-membership cycle with fee_charged_cents == 0 must exist"
    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -4500, (
        f"suspended billing must not debit wallet; expected -4500, got {acct['wallet_credit_cents']}"
    )


def test_suspend_cascades_pet_to_suspended(api):
    """PRD §3.6: "It moves the membership from `ENROLLED` to `SUSPENDED`, cascades every pet
    from `ENROLLED` to `SUSPENDED`, and increments the membership's `version` by one".

    Design: Corner/state_machines/suspend_cascades_pets_to_suspended
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    suspended = validate_success(
        api.suspend_membership(membership["id"], make_member_headers(account["id"])), 200
    )
    assert suspended["status"] == "SUSPENDED"
    pet_after = get_pet(membership["id"], pet["id"])
    assert pet_after["status"] == "SUSPENDED", "suspend must cascade pet to SUSPENDED"


def test_void_already_voided_rejected(api):
    """PRD §3.5: "Voiding is permitted only when the visit is `COMPLETED`, failing which it is
    rejected with `ERR_VISIT_NOT_VOIDABLE`".

    Design: Corner/state_machines/void_already_voided_returns_not_voidable
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    visit = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")
    validate_success(api.void_visit(visit["id"], TEST_USERS["clinic_staff_headers"]), 200)

    res = api.void_visit(visit["id"], TEST_USERS["clinic_staff_headers"])
    validate_error(res, "ERR_VISIT_NOT_VOIDABLE")


# ===========================================================================
# Corner: errors
# ===========================================================================
def test_resume_after_term_expired_rejected(api):
    """PRD §3.6: "it additionally requires that the contract term is still `ACTIVE` and that
    the current logical-clock instant is before the term's `ends_at`, failing which it is
    rejected with `ERR_TERM_EXPIRED`".

    Design: Corner/errors/resume_after_term_expired_returns_term_expired
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=False
    )
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    api.suspend_membership(membership["id"], make_member_headers(account["id"]))
    set_clock("2027-02-01T00:00:00Z")  # past ends_at, no auto-renew successor

    res = api.resume_membership(membership["id"], make_member_headers(account["id"]))
    validate_error(res, "ERR_TERM_EXPIRED")


def test_finalize_cancel_on_enrolled_rejected(api):
    """PRD §3.8: "Finalising a cancellation is a `BillingAdmin` action that closes the
    membership out at cycle end. It is permitted only from `CANCEL_PENDING`, failing which it
    is rejected with `ERR_MEMBERSHIP_NOT_CANCEL_PENDING`."

    Design: Corner/errors/finalize_cancel_on_enrolled_returns_not_cancel_pending
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    res = api.finalize_cancel_membership(membership["id"], BILLING_ADMIN)
    validate_error(res, "ERR_MEMBERSHIP_NOT_CANCEL_PENDING")
