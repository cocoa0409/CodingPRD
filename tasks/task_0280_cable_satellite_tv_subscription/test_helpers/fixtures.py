"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: FieldTechnician calls use make_field_technician_headers with
the real Technician.id; Subscriber ownership calls use make_subscriber_headers
with the real Account.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_channel_package_payload,
    create_premium_channel_payload,
    create_equipment_model_payload,
    create_promotion_offer_payload,
    create_regional_sports_fee_rule_payload,
    create_technician_payload,
    create_account_payload,
    create_subscription_payload,
    tier_change_payload,
    attach_add_on_payload,
    assign_equipment_payload,
    schedule_visit_payload,
    complete_visit_payload,
    apply_promotion_payload,
    issue_statement_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_technician_headers,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ─── Clock ─────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Pin the server clock for deterministic visit-window validation."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ─── Tier 0: Catalog seeding ────────────────────────────────────────────────
def create_package(tier_code="PLUS", name=None, monthly_fee_cents=6000, rank=2,
                   channel_count=120, active=True):
    """Create one ChannelPackage. Returns the entity dict."""
    res = api_client.create_channel_package(
        create_channel_package_payload(
            tier_code=tier_code,
            name=name or tier_code.title(),
            monthly_fee_cents=monthly_fee_cents,
            channel_count=channel_count,
            rank=rank,
            active=active,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_premium_channel(code="HBOX", name=None, kind="PREMIUM",
                           monthly_fee_cents=1500, min_package_rank=2, active=True):
    res = api_client.create_premium_channel(
        create_premium_channel_payload(
            code=code, name=name or code, kind=kind,
            monthly_fee_cents=monthly_fee_cents,
            min_package_rank=min_package_rank, active=active,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_equipment_model(model_code="DVR-4K", kind="DVR",
                           monthly_lease_cents=1000, replacement_cost_cents=30000, active=True):
    res = api_client.create_equipment_model(
        create_equipment_model_payload(
            model_code=model_code, kind=kind,
            monthly_lease_cents=monthly_lease_cents,
            replacement_cost_cents=replacement_cost_cents, active=active,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_promotion_offer(code="SAVE20", discount_kind="PERCENT_OFF_PACKAGE",
                           percent_off=0.2, flat_off_cents=0, promo_months=6,
                           requires_min_rank=2, rollback_protected=False, active=True):
    res = api_client.create_promotion_offer(
        create_promotion_offer_payload(
            code=code, discount_kind=discount_kind, percent_off=percent_off,
            flat_off_cents=flat_off_cents, promo_months=promo_months,
            requires_min_rank=requires_min_rank, rollback_protected=rollback_protected,
            active=active,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500, active=True):
    res = api_client.create_regional_sports_fee_rule(
        create_regional_sports_fee_rule_payload(
            state_code=state_code, base_fee_cents=base_fee_cents,
            premier_surcharge_cents=premier_surcharge_cents, active=active,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_technician(name="Tech One", home_state_code="CA", active=True):
    res = api_client.create_technician(
        create_technician_payload(name=name, home_state_code=home_state_code, active=active),
        ADMIN,
    )
    return get_success_data(res)


# ─── Tier 1: Account state progression ──────────────────────────────────────
def create_prospect_account(customer_name="Test Customer", service_state_code="CA",
                            contract_term_months=0):
    """Create a PROSPECT account. Returns the account dict."""
    res = api_client.create_account(
        create_account_payload(
            customer_name=customer_name,
            service_state_code=service_state_code,
            contract_term_months=contract_term_months,
        ),
        CSA,
    )
    return get_success_data(res)


def activate_first_subscription(account_id, package_id):
    """Activate the account's first subscription (PROSPECT -> ACTIVE). Returns subscription."""
    res = api_client.create_subscription(
        account_id, create_subscription_payload(package_id), CSA,
    )
    return get_success_data(res)


def create_active_account(package, customer_name="Test Customer", service_state_code="CA",
                          contract_term_months=0):
    """Create a PROSPECT account and activate its first subscription on `package`.
    Returns (account, subscription) where account is re-fetched post-activation.
    """
    account = create_prospect_account(
        customer_name=customer_name,
        service_state_code=service_state_code,
        contract_term_months=contract_term_months,
    )
    subscription = activate_first_subscription(account["id"], package["id"])
    account = get_account(account["id"])
    return account, subscription


# ─── Read helpers ───────────────────────────────────────────────────────────
def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, CSA))


def account_version(account_id):
    return get_account(account_id)["version"]


# ─── Tier 2: Line-item attachers ────────────────────────────────────────────
def attach_add_on(account_id, premium_channel_id):
    res = api_client.attach_add_on(account_id, attach_add_on_payload(premium_channel_id), CSA)
    return get_success_data(res)


def assign_equipment(account_id, equipment_model_id, quantity=1):
    res = api_client.assign_equipment_lease(
        account_id, assign_equipment_payload(equipment_model_id, quantity), CSA,
    )
    return get_success_data(res)


def apply_promotion(account_id, promotion_offer_id, expected_account_version=None):
    """Apply a promotion using the current account version when none is supplied."""
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    res = api_client.apply_promotion(
        account_id, apply_promotion_payload(promotion_offer_id, expected_account_version), CSA,
    )
    return get_success_data(res)


# ─── Tier 3: Tier changes ───────────────────────────────────────────────────
def downgrade(account_id, subscription_id, target_package_id, expected_account_version=None):
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    res = api_client.downgrade_subscription(
        account_id, subscription_id,
        tier_change_payload(target_package_id, expected_account_version), CSA,
    )
    return get_success_data(res)


def upgrade(account_id, subscription_id, target_package_id, expected_account_version=None):
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    res = api_client.upgrade_subscription(
        account_id, subscription_id,
        tier_change_payload(target_package_id, expected_account_version), CSA,
    )
    return get_success_data(res)


# ─── Tier 3: Service visits ─────────────────────────────────────────────────
def schedule_visit(account_id, technician_id, window_start, window_end, visit_type="SERVICE"):
    res = api_client.schedule_service_visit(
        account_id,
        schedule_visit_payload(visit_type, window_start, window_end, technician_id),
        CSA,
    )
    return get_success_data(res)


def dispatch_visit(account_id, visit_id, technician_id):
    res = api_client.dispatch_service_visit(
        account_id, visit_id, make_field_technician_headers(technician_id),
    )
    return get_success_data(res)


def complete_visit(account_id, visit_id, technician_id, outcome_note="completed"):
    res = api_client.complete_service_visit(
        account_id, visit_id, complete_visit_payload(outcome_note),
        make_field_technician_headers(technician_id),
    )
    return get_success_data(res)


def no_show_visit(account_id, visit_id, technician_id):
    res = api_client.no_show_service_visit(
        account_id, visit_id, make_field_technician_headers(technician_id),
    )
    return get_success_data(res)


def schedule_and_dispatch_visit(account_id, technician_id, window_start, window_end,
                                visit_type="SERVICE"):
    """Schedule a visit then dispatch it to DISPATCHED. Returns the dispatched visit."""
    visit = schedule_visit(account_id, technician_id, window_start, window_end, visit_type)
    return dispatch_visit(account_id, visit["id"], technician_id)


# ─── Tier 4: Billing-cycle advancement ──────────────────────────────────────
def advance_cycle(account_id):
    res = api_client.advance_cycle(account_id, ADMIN)
    return get_success_data(res)


def advance_cycles(account_id, count):
    """Advance `count` billing cycles. Returns the final account view."""
    account = None
    for _ in range(count):
        account = advance_cycle(account_id)
    return account


def cancel_account(account_id):
    res = api_client.cancel_account(account_id, CSA)
    return get_success_data(res)


def issue_statement(account_id, cycle_index, proration_mode, days_in_cycle=30, active_days=None):
    payload = issue_statement_payload(cycle_index, proration_mode, days_in_cycle=days_in_cycle)
    if active_days is not None:
        payload["active_days"] = active_days
    res = api_client.issue_billing_statement(account_id, payload, ADMIN)
    return get_success_data(res)


# ─── Tier 5: Higher-level composite scenarios ───────────────────────────────
def setup_account_with_all_line_items(
    *, package_fee=5000, package_rank=2, premium_fee=1505, equip_lease=1000,
    rsf_base=800, rsf_surcharge=500, state="TX", equip_quantity=1,
):
    """Active account carrying one package + one premium add-on + one equipment lease,
    with a regional-sports-fee rule for its state. Returns a dict of created entities:
    {package, premium, equipment_model, account, subscription, add_on, lease}.
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=package_fee, rank=package_rank)
    premium = create_premium_channel(
        code="SHOWX", kind="PREMIUM", monthly_fee_cents=premium_fee, min_package_rank=package_rank,
    )
    equip_model = create_equipment_model(
        model_code="BOX-HD", kind="BOX", monthly_lease_cents=equip_lease, replacement_cost_cents=30000,
    )
    create_rsf_rule(state_code=state, base_fee_cents=rsf_base, premier_surcharge_cents=rsf_surcharge)
    account, subscription = create_active_account(package, service_state_code=state)
    add_on = attach_add_on(account["id"], premium["id"])
    lease = assign_equipment(account["id"], equip_model["id"], quantity=equip_quantity)
    account = get_account(account["id"])
    return {
        "package": package, "premium": premium, "equipment_model": equip_model,
        "account": account, "subscription": subscription, "add_on": add_on, "lease": lease,
    }


def setup_account_active_promo(
    *, package_fee=6000, package_rank=2, percent_off=0.2, promo_months=1,
    rollback_protected=False, rsf_base=800, rsf_surcharge=500, state="CA",
):
    """Active account with one PERCENT_OFF_PACKAGE promotion ACTIVE.
    Returns dict {package, offer, account, subscription, application}.
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=package_fee, rank=package_rank)
    create_rsf_rule(state_code=state, base_fee_cents=rsf_base, premier_surcharge_cents=rsf_surcharge)
    offer = create_promotion_offer(
        code="PROMO", discount_kind="PERCENT_OFF_PACKAGE", percent_off=percent_off,
        promo_months=promo_months, requires_min_rank=package_rank,
        rollback_protected=rollback_protected,
    )
    account, subscription = create_active_account(package, service_state_code=state)
    application = apply_promotion(account["id"], offer["id"])
    account = get_account(account["id"])
    return {
        "package": package, "offer": offer, "account": account,
        "subscription": subscription, "application": application,
    }
