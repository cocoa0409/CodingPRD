"""Composite setup helpers.

Every test runs against a freshly re-launched server with an empty database, so
each fixture rebuilds all of its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion failure deep in a test.

Identity threading: the Member role is entity_backed, so any member-owned call
(reload / redeem / WDF pay) is issued with make_member_headers(member_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_attendant_headers,
)
from . import factories as F

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]
ATTENDANT_OP_ID = "attendant-op"
DEFAULT_CLOCK = "2026-06-01T10:00:00Z"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the server capture clock to an absolute instant (Manager-only)."""
    return get_success_data(api_client.advance_clock(to_iso8601, MANAGER))


def create_plan(activate: bool = True, **plan_overrides) -> dict:
    """Create a DRAFT pricing plan and (by default) activate it. Returns the
    plan resource as last seen (activated form if activate=True)."""
    plan = get_success_data(
        api_client.create_pricing_plan(F.create_pricing_plan_payload(**plan_overrides), MANAGER)
    )
    if activate:
        plan = get_success_data(api_client.activate_pricing_plan(plan["id"], MANAGER))
    return plan


def create_machine(**overrides) -> dict:
    """Register a machine (defaults to an IDLE WASHER). Returns the machine."""
    return get_success_data(api_client.create_machine(F.create_machine_payload(**overrides), MANAGER))


def create_member(**overrides) -> dict:
    """Register a member (ACTIVE, zero balances). Returns the member."""
    return get_success_data(api_client.create_member(F.create_member_payload(**overrides), MANAGER))


def reload_wallet(member_id: str, principal_cents: int, tender: str = "APP") -> dict:
    """Reload a member's wallet as the member (entity_backed ownership)."""
    return get_success_data(
        api_client.create_reload(
            member_id,
            F.create_reload_payload(tender=tender, principal_cents=principal_cents),
            make_member_headers(member_id),
        )
    )


def get_machine_version(machine_id: str) -> int:
    return get_success_data(api_client.get_machine(machine_id, MANAGER))["version"]


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, MANAGER))


def get_vend(vend_id: str) -> dict:
    return get_success_data(api_client.get_vend(vend_id, MANAGER))


def get_machine(machine_id: str) -> dict:
    return get_success_data(api_client.get_machine(machine_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1/2: plan + machine + (optional funded member) bootstrap
# ---------------------------------------------------------------------------
def setup_active_plan_and_washer(clock=DEFAULT_CLOCK, plan_overrides=None, machine_overrides=None):
    """Clock + ACTIVE plan + one IDLE WASHER. Returns (plan, machine)."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    machine = create_machine(**(machine_overrides or {"label": "W1"}))
    return plan, machine


def setup_active_plan_and_dryer(clock=DEFAULT_CLOCK, plan_overrides=None):
    """Clock + ACTIVE plan + one IDLE DRYER. Returns (plan, machine)."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    machine = create_machine(label="D1", machine_type="DRYER", capacity_lb=30)
    return plan, machine


def setup_funded_member(principal_cents=5000, tender="APP", clock=DEFAULT_CLOCK,
                        plan_overrides=None, member_overrides=None):
    """Clock + ACTIVE plan + IDLE washer + ACTIVE member whose wallet has been
    reloaded. Returns (plan, machine, member). Re-reads the member so wallet_cents
    reflects the credited reload."""
    plan, machine = setup_active_plan_and_washer(clock, plan_overrides)
    member = create_member(**(member_overrides or {}))
    if principal_cents:
        reload_wallet(member["id"], principal_cents, tender=tender)
        member = get_member(member["id"])
    return plan, machine, member


# ---------------------------------------------------------------------------
# Tier 3: vend lifecycle shortcuts
# ---------------------------------------------------------------------------
def capture_coin_vend(machine_id: str, attendant_id=ATTENDANT_OP_ID, **vend_overrides) -> dict:
    """Capture a COIN vend on an IDLE machine as an attendant. Returns the vend."""
    version = get_machine_version(machine_id)
    return get_success_data(
        api_client.create_vend(
            machine_id,
            F.create_vend_payload(version, payment_method="COIN", **vend_overrides),
            make_attendant_headers(attendant_id),
        )
    )


def capture_app_wallet_vend(machine_id: str, member_id: str, **vend_overrides) -> dict:
    """Capture an APP_WALLET vend on an IDLE machine as the owning member.
    Returns the vend."""
    version = get_machine_version(machine_id)
    return get_success_data(
        api_client.create_vend(
            machine_id,
            F.create_vend_payload(version, payment_method="APP_WALLET",
                                  member_id=member_id, **vend_overrides),
            make_member_headers(member_id),
        )
    )


def setup_app_wallet_vend(charged_clock=DEFAULT_CLOCK, principal_cents=5000,
                          plan_overrides=None):
    """Full path to a single CAPTURED/RUNNING APP_WALLET washer vend.
    Returns (plan, machine, member, vend). The member is funded first."""
    plan, machine, member = setup_funded_member(
        principal_cents=principal_cents, tender="APP", clock=charged_clock,
        plan_overrides=plan_overrides,
    )
    vend = capture_app_wallet_vend(machine["id"], member["id"])
    return plan, machine, member, vend


# ---------------------------------------------------------------------------
# Tier 3: refund-claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def file_refund_claim(vend_id: str, reported_by_id: str, reason="MACHINE_FAULT",
                      refund_destination="WALLET", as_member_id=None) -> dict:
    """File a SUBMITTED refund claim. If as_member_id is given the call is issued
    as that member; otherwise as an attendant. Returns the claim."""
    headers = make_member_headers(as_member_id) if as_member_id else ATTENDANT
    return get_success_data(
        api_client.create_refund_claim(
            F.create_refund_claim_payload(
                vend_id, reported_by_id, reason=reason, refund_destination=refund_destination),
            headers,
        )
    )


def approve_refund_claim(claim_id: str, expected_claim_version: int) -> dict:
    """Approve a refund claim as Manager with the given expected version."""
    return get_success_data(
        api_client.approve_refund_claim(
            claim_id, F.approve_refund_claim_payload(expected_claim_version), MANAGER)
    )


def setup_submitted_wallet_claim(reason="NO_CYCLE", principal_cents=5000,
                                 plan_overrides=None):
    """Funded member -> APP_WALLET washer vend (charged) -> a SUBMITTED WALLET
    refund claim against it. Returns (plan, machine, member, vend, claim)."""
    plan, machine, member, vend = setup_app_wallet_vend(
        principal_cents=principal_cents, plan_overrides=plan_overrides)
    claim = file_refund_claim(vend["id"], member["id"], reason=reason,
                              refund_destination="WALLET", as_member_id=member["id"])
    return plan, machine, member, vend, claim


def setup_refunded_vend(reason="MACHINE_FAULT", principal_cents=5000, plan_overrides=None):
    """Drive a vend all the way to payment_status=REFUNDED via an approved WALLET
    claim. Returns (plan, machine, member, vend, claim) with the claim APPROVED."""
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason=reason, principal_cents=principal_cents, plan_overrides=plan_overrides)
    approve_refund_claim(claim["id"], claim["version"])
    return plan, machine, member, vend, claim


# ---------------------------------------------------------------------------
# Tier 4: shift / drawer reconciliation
# ---------------------------------------------------------------------------
def open_shift(attendant_id: str, opening_float_cents=5000) -> dict:
    """Open a shift owned by attendant_id (opaque). Returns the shift."""
    return get_success_data(
        api_client.create_shift(
            F.create_shift_payload(attendant_id, opening_float_cents=opening_float_cents),
            make_attendant_headers(attendant_id),
        )
    )


def setup_shift_with_coin_and_cash_reload(opening_float_cents=5000, wash_base_cents=300,
                                          reload_principal_cents=2000):
    """Attendant A1 opens a shift, captures one COIN washer vend (charged
    wash_base_cents), and takes one CASH reload (principal reload_principal_cents)
    on a walk-in member. Returns (shift, attendant_id, washer, vend, walk_member).

    expected_drawer = opening_float + coin_collected + cash_reload - cash_refund_paid.
    """
    set_clock(DEFAULT_CLOCK)
    create_plan(wash_base_cents=wash_base_cents)
    washer = create_machine(label="W1")
    # The attendant is identified by an opaque operator handle; we mint a member
    # solely so it has a stable id to use as the attendant_id handle, mirroring
    # how a staff person both attends and could be a registered member. The
    # opaque attendant id need not be a member, but using a real id keeps it
    # distinct from the walk-in.
    attendant_member = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    attendant_id = attendant_member["id"]
    walk_member = create_member(full_name="Walk In", phone="555-0200", card_token="tok-w")
    shift = open_shift(attendant_id, opening_float_cents=opening_float_cents)
    vend = capture_coin_vend(washer["id"], attendant_id=attendant_id)
    get_success_data(
        api_client.create_reload(
            walk_member["id"],
            F.create_reload_payload(tender="CASH", principal_cents=reload_principal_cents),
            make_attendant_headers(attendant_id),
        )
    )
    return shift, attendant_id, washer, vend, walk_member


def begin_reconcile(shift_id: str, attendant_id: str) -> dict:
    return get_success_data(
        api_client.begin_reconcile(shift_id, make_attendant_headers(attendant_id)))


def close_shift(shift_id: str, attendant_id: str, counted_drawer_cents: int) -> dict:
    return get_success_data(
        api_client.close_shift(
            shift_id, F.close_shift_payload(counted_drawer_cents),
            make_attendant_headers(attendant_id)))


# ---------------------------------------------------------------------------
# Tier 4: loyalty earn + redeem to grant a free-wash credit
# ---------------------------------------------------------------------------
def setup_member_with_free_credit(loyalty_cents_per_point=1, redeem_threshold=50,
                                  principal_cents=5000):
    """Funded member earns enough points on an APP_WALLET washer vend to redeem a
    free-wash credit; the washer is then completed and cleared so it is IDLE again.
    Returns (plan, washer, member) with member.free_wash_credits >= 1.

    Uses two machines is unnecessary — the same washer is reused after a full
    IDLE->RUNNING->DONE->IDLE loop.
    """
    plan_overrides = {
        "wash_base_cents": 300,
        "loyalty_cents_per_point": loyalty_cents_per_point,
        "loyalty_redeem_threshold_points": redeem_threshold,
    }
    plan, washer, member = setup_funded_member(
        principal_cents=principal_cents, tender="APP", plan_overrides=plan_overrides)
    capture_app_wallet_vend(washer["id"], member["id"])
    # Complete + clear so the washer returns to IDLE for the trigger vend.
    get_success_data(api_client.complete_cycle(washer["id"], ATTENDANT))
    get_success_data(api_client.clear_machine(washer["id"], ATTENDANT))
    get_success_data(api_client.redeem(member["id"], make_member_headers(member["id"])))
    member = get_member(member["id"])
    return plan, washer, member


# ---------------------------------------------------------------------------
# Tier 3/5: WDF order lifecycle
# ---------------------------------------------------------------------------
def intake_wdf_order(intake_attendant_id: str, weight_lb: int, member_id=None, rush=False) -> dict:
    """Intake a DROPPED WDF order as an attendant. Returns the order."""
    overrides = {"rush": rush}
    if member_id is not None:
        overrides["member_id"] = member_id
    return get_success_data(
        api_client.create_wdf_order(
            F.create_wdf_order_payload(intake_attendant_id, weight_lb, **overrides),
            make_attendant_headers(intake_attendant_id),
        )
    )


def setup_ready_wdf_order(weight_lb=20, member_principal_cents=5000, rush=False):
    """ACTIVE plan + attendant + funded member; a WDF order advanced DROPPED ->
    WASHING -> READY (not yet paid). Returns (plan, attendant_id, member, order)."""
    set_clock(DEFAULT_CLOCK)
    plan = create_plan()
    attendant_member = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    attendant_id = attendant_member["id"]
    member = create_member(full_name="M One", phone="555-0001", card_token="tok-m1")
    if member_principal_cents:
        reload_wallet(member["id"], member_principal_cents, tender="APP")
        member = get_member(member["id"])
    order = intake_wdf_order(attendant_id, weight_lb, member_id=member["id"], rush=rush)
    get_success_data(api_client.start_wdf_order(order["id"], make_attendant_headers(attendant_id)))
    get_success_data(api_client.ready_wdf_order(order["id"], make_attendant_headers(attendant_id)))
    order = get_success_data(api_client.get_wdf_order(order["id"], MANAGER))
    return plan, attendant_id, member, order


def setup_paid_wdf_order(weight_lb=20, member_principal_cents=5000):
    """A WDF order driven all the way to PAID via APP_WALLET. Returns
    (plan, attendant_id, member, order) with order.status == PAID."""
    plan, attendant_id, member, order = setup_ready_wdf_order(
        weight_lb=weight_lb, member_principal_cents=member_principal_cents)
    get_success_data(
        api_client.pay_wdf_order(
            order["id"], F.pay_wdf_order_payload("APP_WALLET"),
            make_member_headers(member["id"])))
    order = get_success_data(api_client.get_wdf_order(order["id"], MANAGER))
    return plan, attendant_id, member, order


# ---------------------------------------------------------------------------
# Lost & found
# ---------------------------------------------------------------------------
def log_lost_found(logged_by_id: str, description="found item", **overrides) -> dict:
    """Log a LOGGED lost-and-found item as an attendant. Returns the item."""
    return get_success_data(
        api_client.create_lost_found(
            F.create_lost_found_payload(logged_by_id, description, **overrides),
            make_attendant_headers(logged_by_id),
        )
    )
