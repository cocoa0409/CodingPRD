"""Derived-field reconciliation and cascade side effects (PRD §2.7, §2.8, §2.11)."""

from datetime import timedelta

import calc
from db import clock, db
from util import dec, iso_clock, touch, two_dp


# --------------------------------------------------------------------------
# StateProgram — every computed field is re-derived from primary records
# --------------------------------------------------------------------------
def refresh_program(program):
    pid = program["id"]
    site_ids = set(s["id"] for s in db.collection_sites.values()
                   if s["state_program_id"] == pid)

    fee_collected = 0
    receivable = 0
    for rem in db.sales_remittances.values():
        if rem["state_program_id"] != pid:
            continue
        if rem["status"] in calc.LEDGER_REMITTANCE_STATUSES:
            fee_collected += rem["fee_paid_cents"] - rem["fee_refunded_cents"]
        if rem["status"] == "AUDIT_CLOSED":
            receivable += rem["balance_due_cents"]

    site_credit = 0
    reported_units = 0
    for report in db.volume_reports.values():
        if report["collection_site_id"] in site_ids and report["status"] == "ACCEPTED":
            site_credit += report["credit_cents"]
            reported_units += report["credited_units"]

    hauler_paid = 0
    for order in db.pickup_orders.values():
        if order["collection_site_id"] in site_ids and order["settlement_status"] == "FINALIZED":
            hauler_paid += order["final_payment_cents"] or 0

    for delivery in db.take_back_deliveries.values():
        if delivery["collection_site_id"] in site_ids and \
                delivery["status"] in ("OBLIGATION_MET", "OBLIGATION_BREACHED"):
            reported_units += delivery["units_takeback_collected"] or 0

    delinquent_ids = set()
    for rem in db.sales_remittances.values():
        if rem["state_program_id"] != pid:
            continue
        if rem["status"] != "AUDIT_CLOSED" or rem["balance_due_cents"] <= 0:
            continue
        registrant = db.registrants.get(rem["registrant_id"])
        if registrant and registrant["compliance_status"] in ("DELINQUENT", "SUSPENDED"):
            delinquent_ids.add(registrant["id"])

    program["fee_collected_cents"] = fee_collected
    program["site_credit_paid_cents"] = site_credit
    program["hauler_payment_paid_cents"] = hauler_paid
    program["reserve_balance_cents"] = (program["reserve_opening_cents"] + fee_collected
                                        - site_credit - hauler_paid)
    program["receivable_cents"] = receivable
    program["enrolled_site_count"] = sum(
        1 for s in db.collection_sites.values()
        if s["state_program_id"] == pid and s["enrollment_status"] == "ENROLLED")
    program["reported_units_total"] = reported_units
    program["delinquent_registrant_count"] = len(delinquent_ids)
    program["enforcement_posture"] = (
        "ELEVATED" if len(delinquent_ids) >= program["delinquency_alert_threshold"]
        else "NORMAL")
    program["reserve_coverage_months"] = float(calc.reserve_coverage_months_decimal(program))
    program["recommended_rate_cents"] = \
        calc.fee_rate_recommendation(program)["recommended_rate_cents"]
    return program


def refresh_program_and_touch(program):
    refresh_program(program)
    touch(program)
    return program


# --------------------------------------------------------------------------
# Registrant
# --------------------------------------------------------------------------
def refresh_registrant(registrant):
    rid = registrant["id"]
    balance = 0
    for rem in db.sales_remittances.values():
        if rem["registrant_id"] == rid and rem["status"] == "AUDIT_CLOSED":
            balance += rem["balance_due_cents"]
    breaches = 0
    for delivery in db.take_back_deliveries.values():
        if delivery["registrant_id"] == rid and delivery["status"] == "OBLIGATION_BREACHED":
            balance += delivery["breach_penalty_cents"]
            breaches += 1
    registrant["delinquent_balance_cents"] = balance
    registrant["takeback_breach_count"] = breaches
    if balance >= calc.REGISTRANT_SUSPENSION_BALANCE_CENTS:
        registrant["compliance_status"] = "SUSPENDED"
    elif balance > 0:
        registrant["compliance_status"] = "DELINQUENT"
    else:
        registrant["compliance_status"] = "COMPLIANT"
    return registrant


# --------------------------------------------------------------------------
# Hauler
# --------------------------------------------------------------------------
def refresh_hauler(hauler):
    hid = hauler["id"]
    active = 0
    paid = 0
    for order in db.pickup_orders.values():
        if order["hauler_id"] != hid:
            continue
        if order["fulfillment_status"] in calc.ACTIVE_ROUTE_STATUSES:
            active += 1
        if order["settlement_status"] == "FINALIZED":
            paid += order["final_payment_cents"] or 0
    hauler["active_route_count"] = active
    hauler["total_paid_cents"] = paid
    return hauler


# --------------------------------------------------------------------------
# Recycler
# --------------------------------------------------------------------------
def refresh_recycler(recycler):
    rid = recycler["id"]
    order_ids = set()
    received = 0
    for order in db.pickup_orders.values():
        if order["recycler_id"] != rid:
            continue
        order_ids.add(order["id"])
        if order["units_delivered"] is not None:
            received += order["units_delivered"]
    processed = 0
    rejected = 0
    for inspection in db.load_inspections.values():
        if inspection["pickup_order_id"] not in order_ids:
            continue
        order = db.pickup_orders[inspection["pickup_order_id"]]
        processed += inspection["units_accepted"]
        rejected += (order["units_delivered"] or 0) - inspection["units_accepted"]
    weight = dec(0)
    for record in db.commodity_output_records.values():
        if record["recycler_id"] == rid and record["record_status"] == "VERIFIED":
            weight += dec(record["output_weight_kg"])
    recycler["units_received_count"] = received
    recycler["units_processed_count"] = processed
    recycler["units_rejected_count"] = rejected
    recycler["verified_output_weight_kg"] = float(weight)
    recycler["diversion_rate_pct"] = calc.recycler_diversion_rate(weight, processed)
    return recycler


# --------------------------------------------------------------------------
# CollectionSite suspension cascade (admin suspend + strike cascade)
# --------------------------------------------------------------------------
def cancel_open_orders_of_site(site, skip_order_id=None):
    """Cancel SCHEDULED / PICKED_UP orders, returning units to on-hand."""
    for order in list(db.pickup_orders.values()):
        if order["collection_site_id"] != site["id"]:
            continue
        if order["id"] == skip_order_id:
            continue
        if order["fulfillment_status"] not in ("SCHEDULED", "PICKED_UP"):
            continue
        order["fulfillment_status"] = "CANCELLED"
        order["settlement_status"] = "VOIDED"
        site["units_in_transit"] -= order["units_manifested"]
        site["units_on_hand"] += order["units_manifested"]
        touch(order)
        hauler = db.haulers.get(order["hauler_id"])
        if hauler is not None:
            refresh_hauler(hauler)
            touch(hauler)


def suspend_site(site, program, skip_order_id=None):
    """ENROLLED -> SUSPENDED with its full cascade."""
    site["enrollment_status"] = "SUSPENDED"
    site["suspended_at"] = clock.stamp()
    touch(site)
    cancel_open_orders_of_site(site, skip_order_id=skip_order_id)
    refresh_program_and_touch(program)


def quarantine_active(site):
    until = site.get("infestation_quarantine_until")
    if not until:
        return False
    from util import parse_dt
    return clock.now() < parse_dt(until)


def set_quarantine(site):
    site["infestation_quarantine_until"] = iso_clock(
        clock.now() + timedelta(days=calc.INFESTATION_QUARANTINE_DAYS))


def two_decimals(value):
    return two_dp(value)
