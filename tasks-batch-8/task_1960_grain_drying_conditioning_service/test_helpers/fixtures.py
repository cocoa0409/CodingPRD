"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the server before each test) using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a
broken precondition raises a clear "Setup step failed" error.

Identity threading: every Grower-role call passes the owning Customer's id
through make_grower_headers(); opaque operator roles use the shared constants
or the per-id makers from test_users.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_blend_order_payload,
    create_charge_schedule_payload,
    create_customer_payload,
    create_damage_claim_payload,
    create_dryer_run_payload,
    create_dryer_unit_payload,
    create_grain_lot_payload,
    create_invoice_payload,
    create_moisture_test_payload,
    create_payment_payload,
    create_queue_ticket_payload,
    create_storage_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjuster_headers,
    make_grower_headers,
    make_manager_headers,
    make_operator_headers,
    make_technician_headers,
)

MGR = TEST_USERS["manager_headers"]
TECH = TEST_USERS["technician_headers"]
OP = TEST_USERS["operator_headers"]
ADJ = TEST_USERS["adjuster_headers"]


# ─── Tier 0: single-resource creation ────────────────────────────────────────

def create_customer(name="C1", credit_limit_cents=None, **overrides) -> dict:
    """Create a grower account. Returns the Customer."""
    payload = create_customer_payload(name=name, **overrides)
    if credit_limit_cents is not None:
        payload["credit_limit_cents"] = credit_limit_cents
    return get_success_data(api_client.create_customer(payload, MGR))


def create_schedule(**overrides) -> dict:
    """Create the canonical CORN tariff window (overridable)."""
    return get_success_data(api_client.create_charge_schedule(
        create_charge_schedule_payload(**overrides), MGR))


def create_unit(**overrides) -> dict:
    """Register the canonical dryer unit (overridable)."""
    return get_success_data(api_client.create_dryer_unit(
        create_dryer_unit_payload(**overrides), MGR))


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (ElevatorManager-only test-driving)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, MGR))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_grain_lot(lot_id, MGR))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_queue_ticket(ticket_id, MGR))


def get_run(run_id: str) -> dict:
    return get_success_data(api_client.get_dryer_run(run_id, MGR))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, MGR))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, MGR))


def capacity_calendar(unit_id: str, date: str) -> dict:
    return get_success_data(api_client.get_capacity_calendar(unit_id, date, MGR))


# ─── Tier 1: state progression ───────────────────────────────────────────────

def create_lot(customer_id: str, **overrides) -> dict:
    """Receive a lot at the scale. Returns the GrainLot (RECEIVED)."""
    return get_success_data(api_client.create_grain_lot(
        create_grain_lot_payload(customer_id, **overrides), TECH))


def create_moisture_test(lot_id: str, sample_moisture_pct=20.0,
                         expected_grain_lot_version=None, tech_id="tech-1",
                         **overrides) -> dict:
    """Create a PRELIMINARY moisture test. When expected_grain_lot_version is
    omitted, the lot's current version is read fresh (OCC field)."""
    if expected_grain_lot_version is None:
        expected_grain_lot_version = get_lot(lot_id)["version"]
    payload = create_moisture_test_payload(
        lot_id, expected_grain_lot_version,
        sample_moisture_pct=sample_moisture_pct, **overrides)
    return get_success_data(api_client.create_moisture_test(
        payload, make_technician_headers(tech_id)))


def certify_test(test_id: str, tech_id="tech-1") -> dict:
    """Certify a PRELIMINARY test. Returns the CERTIFIED MoistureTest."""
    return get_success_data(api_client.certify_moisture_test(
        test_id, make_technician_headers(tech_id)))


def create_tested_lot(customer_id: str, sample_moisture_pct=20.0, tech_id="tech-1",
                      **lot_overrides):
    """Lot + certified moisture test. Returns (lot_after_certify, test)."""
    lot = create_lot(customer_id, **lot_overrides)
    test = create_moisture_test(lot["id"], sample_moisture_pct,
                                expected_grain_lot_version=lot["version"],
                                tech_id=tech_id)
    certify_test(test["id"], tech_id=tech_id)
    return get_lot(lot["id"]), get_success_data(
        api_client.get_moisture_test(test["id"], MGR))


def create_ticket(lot: dict, unit_id: str, window_date="2026-09-12",
                  requested_bushels=200, as_manager=False) -> dict:
    """Book a PENDING ticket. Grower calls thread the lot's owning customer id."""
    payload = create_queue_ticket_payload(
        lot["id"], unit_id, window_date=window_date,
        requested_bushels=requested_bushels)
    headers = MGR if as_manager else make_grower_headers(lot["customer_id"])
    return get_success_data(api_client.create_queue_ticket(payload, headers))


def confirm_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.confirm_queue_ticket(ticket_id, MGR))


def create_queued_lot(customer_id: str, unit_id: str, window_date="2026-09-12",
                      requested_bushels=200, sample_moisture_pct=20.0,
                      **lot_overrides):
    """Tested lot + CONFIRMED ticket. Returns (lot_QUEUED, test, ticket)."""
    lot, test = create_tested_lot(customer_id, sample_moisture_pct=sample_moisture_pct,
                                  **lot_overrides)
    ticket = create_ticket(lot, unit_id, window_date=window_date,
                           requested_bushels=requested_bushels)
    confirm_ticket(ticket["id"])
    return get_lot(lot["id"]), test, get_ticket(ticket["id"])


# ─── Tier 2/3: dryer-run lifecycle ───────────────────────────────────────────

def schedule_run(unit_id: str, lot_id: str, ticket_id: str,
                 scheduled_start=None, scheduled_end=None, op_id="op-1") -> dict:
    overrides = {}
    if scheduled_start is not None:
        overrides["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        overrides["scheduled_end"] = scheduled_end
    return get_success_data(api_client.create_dryer_run(
        create_dryer_run_payload(unit_id, lot_id, ticket_id, **overrides),
        make_operator_headers(op_id)))


def start_run(run_id: str, meter_start_therms=1200.0, op_id="op-1") -> dict:
    return get_success_data(api_client.start_dryer_run(
        run_id, {"meter_start_therms": meter_start_therms},
        make_operator_headers(op_id)))


def complete_run(run_id: str, scale_out_weight_lbs=9050, discharge_moisture_pct=15.0,
                 meter_end_therms=1265.0, energy_estimated=False, op_id="op-1") -> dict:
    payload = {
        "scale_out_weight_lbs": scale_out_weight_lbs,
        "discharge_moisture_pct": discharge_moisture_pct,
    }
    if energy_estimated:
        payload["energy_estimated"] = True
    else:
        payload["meter_end_therms"] = meter_end_therms
    return get_success_data(api_client.complete_dryer_run(
        run_id, payload, make_operator_headers(op_id)))


def create_dried_lot(customer_id: str, unit_id: str, *,
                     commodity="CORN",
                     gross_weight_lbs=None, tare_weight_lbs=None,
                     target_moisture_pct=15.0, foreign_material_pct=None,
                     sample_moisture_pct=22.5, tech_id="tech-1",
                     window_date="2026-09-05", requested_bushels=200,
                     run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T12:00:00Z",
                     meter_start=1200.0, meter_end=1265.0,
                     scale_out=9050, discharge=15.0,
                     energy_estimated=False, op_id="op-1") -> dict:
    """Full drying chain: lot -> test -> certify -> ticket -> confirm ->
    run -> (clock=run_start) start -> (clock=run_end) complete.

    Returns {"lot", "test", "ticket", "run"} re-read after completion;
    the lot is DRIED (no storage agreement involved).
    """
    lot_overrides = {"target_moisture_pct": target_moisture_pct,
                     "commodity": commodity}
    if gross_weight_lbs is not None:
        lot_overrides["gross_weight_lbs"] = gross_weight_lbs
    if tare_weight_lbs is not None:
        lot_overrides["tare_weight_lbs"] = tare_weight_lbs
    if foreign_material_pct is not None:
        lot_overrides["foreign_material_pct"] = foreign_material_pct
    lot, test = create_tested_lot(customer_id, sample_moisture_pct=sample_moisture_pct,
                                  tech_id=tech_id, **lot_overrides)
    ticket = create_ticket(lot, unit_id, window_date=window_date,
                           requested_bushels=requested_bushels)
    confirm_ticket(ticket["id"])
    run = schedule_run(unit_id, lot["id"], ticket["id"],
                       scheduled_start=run_start, scheduled_end=run_end, op_id=op_id)
    set_clock(run_start)
    start_run(run["id"], meter_start_therms=meter_start, op_id=op_id)
    set_clock(run_end)
    run = complete_run(run["id"], scale_out_weight_lbs=scale_out,
                       discharge_moisture_pct=discharge, meter_end_therms=meter_end,
                       energy_estimated=energy_estimated, op_id=op_id)
    return {
        "lot": get_lot(lot["id"]),
        "test": test,
        "ticket": get_ticket(ticket["id"]),
        "run": run,
    }


# ─── Tier 3: claims lifecycle ────────────────────────────────────────────────

def create_filed_claim(lot: dict, run: dict, claimed_amount_cents=20000,
                       damage_type="HEAT_DAMAGE") -> dict:
    """Owning grower files a claim; lot must be DRIED (moves to DAMAGE_HOLD)."""
    headers = make_grower_headers(lot["customer_id"])
    return get_success_data(api_client.create_damage_claim(
        create_damage_claim_payload(
            lot["id"], run["id"],
            claimed_amount_cents=claimed_amount_cents, damage_type=damage_type),
        headers))


def review_claim(claim_id: str, adj_id="adj-1") -> dict:
    return get_success_data(api_client.review_damage_claim(
        claim_id, make_adjuster_headers(adj_id)))


def assess_claim(claim_id: str, adj_id="adj-1") -> dict:
    return get_success_data(api_client.assess_damage_claim(
        claim_id, make_adjuster_headers(adj_id)))


def deny_claim(claim_id: str, adj_id="adj-1") -> dict:
    return get_success_data(api_client.deny_damage_claim(
        claim_id, make_adjuster_headers(adj_id)))


def create_assessed_claim(lot: dict, run: dict, claimed_amount_cents=20000,
                          damage_type="HEAT_DAMAGE", adj_id="adj-1") -> dict:
    """File -> review -> assess. Returns the ASSESSED claim."""
    claim = create_filed_claim(lot, run, claimed_amount_cents=claimed_amount_cents,
                               damage_type=damage_type)
    review_claim(claim["id"], adj_id=adj_id)
    return assess_claim(claim["id"], adj_id=adj_id)


# ─── Tier 3: billing lifecycle ───────────────────────────────────────────────

def create_draft_invoice(customer_id: str, period_start="2026-09-01",
                         period_end="2026-09-30") -> dict:
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(customer_id, period_start=period_start,
                               period_end=period_end), MGR))


def issue_invoice(invoice_id: str, pinned_schedule_version) -> dict:
    return get_success_data(api_client.issue_invoice(
        invoice_id, {"pinned_schedule_version": pinned_schedule_version}, MGR))


def create_issued_invoice(customer_id: str, schedule: dict,
                          period_start="2026-09-01", period_end="2026-09-30") -> dict:
    """Compose + issue against the schedule's current version."""
    invoice = create_draft_invoice(customer_id, period_start=period_start,
                                   period_end=period_end)
    return issue_invoice(invoice["id"], schedule["version"])


def create_payment(invoice: dict, amount_cents: int, as_manager=True,
                   expected_invoice_version=None) -> dict:
    """Post a payment; reads the invoice version fresh when not supplied."""
    if expected_invoice_version is None:
        expected_invoice_version = get_invoice(invoice["id"])["version"]
    headers = MGR if as_manager else make_grower_headers(invoice["customer_id"])
    return get_success_data(api_client.create_payment(
        invoice["id"],
        create_payment_payload(amount_cents, expected_invoice_version),
        headers))


# ─── Tier 3: storage & blending lifecycle ────────────────────────────────────

def create_storage_agreement(lot_id: str, **overrides) -> dict:
    """Create a storage agreement (ACTIVE when the lot is DRIED, else RESERVED)."""
    return get_success_data(api_client.create_storage_agreement(
        create_storage_agreement_payload(lot_id, **overrides), MGR))


def create_blend_order(high_lot_id: str, low_lot_id: str, target_moisture_pct=15.5,
                       creator_id="mgr-1") -> dict:
    return get_success_data(api_client.create_blend_order(
        create_blend_order_payload(high_lot_id, low_lot_id,
                                   target_moisture_pct=target_moisture_pct),
        make_manager_headers(creator_id)))


def approve_blend_order(order_id: str, approver_id="mgr-2") -> dict:
    return get_success_data(api_client.approve_blend_order(
        order_id, make_manager_headers(approver_id)))


def create_approved_blend_order(high_lot_id: str, low_lot_id: str,
                                target_moisture_pct=15.5, creator_id="mgr-1",
                                approver_id="mgr-2") -> dict:
    order = create_blend_order(high_lot_id, low_lot_id, target_moisture_pct,
                               creator_id=creator_id)
    return approve_blend_order(order["id"], approver_id=approver_id)


# ─── Tier 2: composite scenario roots ────────────────────────────────────────

def setup_base(*, with_schedule=False, with_unit=True,
               clock="2026-09-01T08:00:00Z", customer_name="C1",
               credit_limit_cents=None, customer_overrides=None,
               schedule_overrides=None, unit_overrides=None) -> dict:
    """Customer (+ optional tariff) (+ dryer unit) + logical clock set.

    Returns {"cust", "sched"?, "unit"?} — the common root of most scenarios.
    """
    ctx = {}
    ctx["cust"] = create_customer(name=customer_name,
                                  credit_limit_cents=credit_limit_cents,
                                  **(customer_overrides or {}))
    if with_schedule:
        ctx["sched"] = create_schedule(**(schedule_overrides or {}))
    if with_unit:
        ctx["unit"] = create_unit(**(unit_overrides or {}))
    set_clock(clock)
    return ctx


def setup_dried_lot_scenario(*, with_schedule=True, customer_name="C1",
                             credit_limit_cents=None, prepaid_balance_cents=None,
                             customer_overrides=None, schedule_overrides=None,
                             unit_overrides=None, **dry_kwargs) -> dict:
    """setup_base + one fully dried lot.

    Returns {"cust", "sched"?, "unit", "lot", "test", "ticket", "run"}.
    """
    cust_ov = dict(customer_overrides or {})
    if prepaid_balance_cents is not None:
        cust_ov["prepaid_balance_cents"] = prepaid_balance_cents
    ctx = setup_base(with_schedule=with_schedule, with_unit=True,
                     customer_name=customer_name,
                     credit_limit_cents=credit_limit_cents,
                     customer_overrides=cust_ov,
                     schedule_overrides=schedule_overrides,
                     unit_overrides=unit_overrides)
    ctx.update(create_dried_lot(ctx["cust"]["id"], ctx["unit"]["id"], **dry_kwargs))
    return ctx
