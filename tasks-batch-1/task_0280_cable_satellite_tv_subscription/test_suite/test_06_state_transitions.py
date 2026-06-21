"""State-machine breadth: invalid transitions, terminal lockdown, precondition
enforcement, initial state, and single-effect transitions (corner `state_machines`).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_field_technician_headers,
    create_package,
    create_technician,
    create_prospect_account,
    create_active_account,
    activate_first_subscription,
    apply_promotion,
    account_version,
    set_clock,
    schedule_visit,
    schedule_and_dispatch_visit,
    create_rsf_rule,
    create_promotion_offer,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


def test_new_account_starts_in_prospect(api):
    """PRD §3.2: "A freshly created account starts with `lifecycle_status` of `PROSPECT`,
    `promo_status` of `NONE`, a `tenure_months` of 0, a null `active_package_id`, and a null
    `cancellation_effective_cycle`."

    Design: Corner/state_machines/new_account_starts_in_prospect_initial_state
    """
    res = api.create_account({"customer_name": "Init", "service_state_code": "CA", "contract_term_months": 0}, CSA)
    account = validate_success(res, 201)
    assert account["lifecycle_status"] == "PROSPECT"


def test_second_subscription_on_active_account_invalid_state(api):
    """PRD §3.2: "Service begins when a `CustomerServiceAgent` activates the account's **first
    subscription**, supplying the chosen `package_id`. This is permitted only while the account
    is in `PROSPECT` and the referenced channel package is active."

    Design: Corner/state_machines/subscribe_twice_second_returns_invalid_state
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    res = api.create_subscription(account["id"], {"package_id": package["id"]}, CSA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_already_cancelled_invalid_state(api):
    """PRD §3.3: "It is permitted from either `ACTIVE` or `SUSPENDED`; from any other state the
    attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    validate_success(api.cancel_account(account["id"], CSA), 200)
    res = api.cancel_account(account["id"], CSA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reactivate_active_account_invalid_state(api):
    """PRD §3.2: "A suspended account may be **reactivated** by a `CustomerServiceAgent`, moving
    `SUSPENDED → ACTIVE`, recomputing the recurring charge, and incrementing the version."

    Design: Corner/state_machines/reactivate_active_account_returns_invalid_state
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    res = api.reactivate_account(account["id"], CSA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dispatch_completed_visit_invalid_state(api):
    """PRD §3.9: "Any transition attempted from a state the machine does not permit — completing
    a visit that was never dispatched, dispatching a cancelled visit — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/dispatch_from_completed_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="T1", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_and_dispatch_visit(
        account["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="INSTALL"
    )
    validate_success(
        api.complete_service_visit(
            account["id"], visit["id"], {"outcome_note": "done"}, make_field_technician_headers(tech["id"])
        ),
        200,
    )
    res = api.dispatch_service_visit(account["id"], visit["id"], make_field_technician_headers(tech["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_complete_without_dispatch_invalid_state(api):
    """PRD §3.9: "Any transition attempted from a state the machine does not permit — completing
    a visit that was never dispatched, dispatching a cancelled visit — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/complete_from_scheduled_without_dispatch_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="T1", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_visit(
        account["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="SERVICE"
    )
    res = api.complete_service_visit(
        account["id"], visit["id"], {"outcome_note": "x"}, make_field_technician_headers(tech["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_scheduled_visit_sets_zero_fee(api):
    """PRD §3.9: "Separately, a `SCHEDULED` visit may be **cancelled** by a `CustomerServiceAgent`
    or the owning `Subscriber`, moving `SCHEDULED → CANCELLED` with a fee of 0 and no billing
    impact."

    Design: Corner/state_machines/visit_cancel_sets_zero_fee
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="T1", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_visit(
        account["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="SERVICE"
    )
    cancelled = validate_success(api.cancel_service_visit(account["id"], visit["id"], CSA), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["truck_roll_fee_cents"] == 0


def test_upgrade_supersedes_old_subscription(api):
    """PRD §3.4: "The current subscription transitions `ACTIVE → SUPERSEDED`, and a **new**
    subscription row is created carrying `previous_subscription_id` pointing back at the one it
    replaced; that new row is `ACTIVE` for an upgrade and `DOWNGRADED` for a downgrade."

    Design: Corner/state_machines/upgrade_supersedes_old_subscription
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    plus = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, old_sub = create_active_account(basic, service_state_code="CA")
    v = account_version(account["id"])
    res = api.upgrade_subscription(
        account["id"], old_sub["id"], {"package_id": plus["id"], "expected_account_version": v}, CSA
    )
    new_sub = validate_success(res, 201)
    assert new_sub["status"] == "ACTIVE"
    assert new_sub["previous_subscription_id"] == old_sub["id"]


def test_promo_rollback_on_advance_cycle_resets_price(api):
    """PRD §3.6: "the application is rolled back, its `discount_cents_snapshot` contribution drops
    to 0, the recurring charge is recomputed back up to catalog price, and the account `version`
    increments."

    Design: Corner/state_machines/promo_rollback_on_advance_cycle_resets_price
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    offer = create_promotion_offer(
        code="P20", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.2, promo_months=1,
        requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    advanced = validate_success(api.advance_cycle(account["id"], ADMIN), 200)
    assert advanced["promo_status"] == "ROLLED_BACK"
    # catalog price restored: 6000 package + 800 rsf = 6800
    assert advanced["monthly_recurring_cents"] == 6800
