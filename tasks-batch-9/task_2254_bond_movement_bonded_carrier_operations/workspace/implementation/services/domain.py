"""Domain services: serialisation, the obligation ledger, and every cascade."""
from decimal import Decimal

from db import db, iso, new_record, order_key, touch
from response import num
from services import calc


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------
def rows(table):
    return sorted(table.values(), key=order_key)


def movements_of_carrier(carrier_id):
    return [m for m in rows(db.movements) if m["carrier_id"] == carrier_id]


def claims_of_carrier(carrier_id):
    out = []
    for claim in rows(db.claims):
        movement = db.movements.get(claim["movement_id"])
        if movement is not None and movement["carrier_id"] == carrier_id:
            out.append(claim)
    return out


def open_holds(movement_id):
    return [h for h in rows(db.holds)
            if h["movement_id"] == movement_id and h["status"] == "OPEN"]


def seal_events_of(movement_id):
    return [e for e in rows(db.seal_events) if e["movement_id"] == movement_id]


def reports_of(movement_id):
    return [r for r in rows(db.reports) if r["movement_id"] == movement_id]


def amendments_of(movement_id):
    return [a for a in rows(db.amendments) if a["movement_id"] == movement_id]


def petitions_of(claim_id):
    return [p for p in rows(db.petitions) if p["claim_id"] == claim_id]


def port_by_code(port_code):
    for port in rows(db.ports):
        if port["port_code"] == port_code:
            return port
    return None


def claim_carrier(claim):
    movement = db.movements.get(claim["movement_id"])
    if movement is None:
        return None
    return db.carriers.get(movement["carrier_id"])


# --------------------------------------------------------------------------
# the bond obligation ledger (PRD 2.6)
# --------------------------------------------------------------------------
def recompute_bond(bond, mark=True):
    """Replay the ledger, re-derive the balances, the count and the status."""
    if bond is None:
        return False
    before = (bond.get("obligated_amount"), bond.get("available_amount"),
              bond.get("status"), bond.get("open_movement_count"))

    balance = Decimal("0.00")
    entries = [e for e in rows(db.ledger_entries) if e["bond_id"] == bond["id"]]
    for entry in entries:
        balance = calc.round2(balance + entry["amount"])
        entry["balance_after"] = balance

    available = calc.round2(bond["limit_amount"] - balance)
    open_count = len([m for m in db.movements.values()
                      if m["bond_id"] == bond["id"]
                      and m["transit_status"] in calc.OPEN_MOVEMENT_STATUSES])

    status = bond["status"]
    if status == "ACTIVE" and available <= Decimal("0.00"):
        status = "SATURATED"
    elif status == "SATURATED" and available > Decimal("0.00"):
        status = "ACTIVE"

    bond["obligated_amount"] = balance
    bond["available_amount"] = available
    bond["open_movement_count"] = open_count
    bond["status"] = status

    after = (balance, available, status, open_count)
    changed = before != after
    if changed and mark:
        touch(bond)
    return changed


def append_ledger(bond, movement_id, entry_type, amount, reason_code, claim_id=None):
    entry = new_record(full=False)
    entry.update({
        "bond_id": bond["id"] if bond else None,
        "movement_id": movement_id,
        "claim_id": claim_id,
        "entry_type": entry_type,
        "amount": calc.round2(amount),
        "balance_after": Decimal("0.00"),
        "reason_code": reason_code,
        "recorded_at": db.now,
    })
    db.ledger_entries[entry["id"]] = entry
    recompute_bond(bond)
    return entry


# --------------------------------------------------------------------------
# ports
# --------------------------------------------------------------------------
def recompute_port(port):
    if port is None:
        return
    count = len([h for h in db.holds.values()
                 if h["port_id"] == port["id"] and h["status"] == "OPEN"])
    if port["open_hold_count"] != count:
        port["open_hold_count"] = count
        touch(port)


# --------------------------------------------------------------------------
# carriers: sanction posture and the suspension cascade (PRD 3.7)
# --------------------------------------------------------------------------
def cascade_cancel_filed(carrier, reason_code):
    """Cancel every FILED movement of the carrier, created_at ASC."""
    for movement in movements_of_carrier(carrier["id"]):
        if movement["transit_status"] != "FILED":
            continue
        movement["transit_status"] = "CANCELLED"
        movement["cancellation_reason"] = reason_code
        touch(movement)
        bond = db.bonds.get(movement["bond_id"])
        append_ledger(bond, movement["id"], "RELEASE",
                      -movement["obligation_amount"], reason_code)


def recompute_sanctions(carrier):
    if carrier is None:
        return
    countable = [c for c in claims_of_carrier(carrier["id"])
                 if c["status"] in calc.COUNTABLE_CLAIM_STATUSES]
    points = calc.sanction_points(countable, db.now)

    changed = False
    if carrier["sanction_points"] != points:
        carrier["sanction_points"] = points
        changed = True

    suspend = False
    if points >= calc.SANCTION_SUSPENSION_THRESHOLD and carrier["custodial_status"] == "ACTIVE":
        carrier["custodial_status"] = "SUSPENDED"
        carrier["suspension_reason"] = "SANCTION_POINTS_THRESHOLD"
        changed = True
        suspend = True
    elif points < calc.SANCTION_SUSPENSION_THRESHOLD and carrier["custodial_status"] == "SUSPENDED":
        carrier["custodial_status"] = "ACTIVE"
        carrier["suspension_reason"] = None
        changed = True

    if changed:
        touch(carrier)
    if suspend:
        cascade_cancel_filed(carrier, "CARRIER_SUSPENSION_CASCADE")


# --------------------------------------------------------------------------
# movements
# --------------------------------------------------------------------------
def close_if_exported(movement):
    """An EXPORTED movement closes once no examination hold remains OPEN."""
    if movement["transit_status"] != "EXPORTED":
        return False
    if open_holds(movement["id"]):
        return False
    movement["transit_status"] = "CLOSED"
    touch(movement)
    bond = db.bonds.get(movement["bond_id"])
    append_ledger(bond, movement["id"], "RELEASE",
                  -movement["obligation_amount"], "MOVEMENT_EXPORTED")
    return True


def apply_go_grace(movement):
    """One-time general-order grace when a hold opens on an ARRIVED movement."""
    if movement["transit_status"] != "ARRIVED":
        return False
    if movement.get("go_grace_applied"):
        return False
    if movement.get("go_deadline_utc") is None:
        return False
    movement["go_deadline_utc"] = movement["go_deadline_utc"] + calc.days(calc.GO_HOLD_GRACE_DAYS)
    movement["go_grace_applied"] = True
    return True


def recompute_transit_window(movement, anchor=None):
    """Re-derive transit_days_allowed and transit_deadline_utc."""
    carrier = db.carriers.get(movement["carrier_id"])
    origin = db.ports.get(movement["origin_port_id"])
    destination = db.ports.get(movement["destination_port_id"])
    points = carrier["sanction_points"] if carrier else Decimal("0.0")
    if anchor is not None:
        movement["deadline_anchor_utc"] = anchor
    allowed = calc.transit_allowance(
        movement["in_bond_type"],
        origin["region_code"] if origin else None,
        destination["region_code"] if destination else None,
        points,
        movement["extension_days_granted"],
    )
    movement["transit_days_allowed"] = allowed
    movement["transit_deadline_utc"] = calc.deadline_from(
        movement["deadline_anchor_utc"], allowed)
    return movement["transit_deadline_utc"]


# --------------------------------------------------------------------------
# serialisers
# --------------------------------------------------------------------------
def _common(rec, full=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if full:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def carrier_json(rec):
    overdue = len([m for m in db.movements.values()
                   if m["carrier_id"] == rec["id"] and m["transit_status"] == "OVERDUE"])
    open_claims = len([c for c in claims_of_carrier(rec["id"])
                       if c["status"] in calc.LIVE_CLAIM_STATUSES])
    out = {
        "name": rec["name"],
        "irs_number": rec["irs_number"],
        "custodial_status": rec["custodial_status"],
        "sanction_points": num(rec["sanction_points"]),
        "overdue_movement_count": overdue,
        "open_claim_count": open_claims,
        "suspension_reason": rec["suspension_reason"],
    }
    out.update(_common(rec))
    return out


def bond_json(rec):
    out = {
        "carrier_id": rec["carrier_id"],
        "bond_type": rec["bond_type"],
        "limit_amount": num(rec["limit_amount"]),
        "obligated_amount": num(rec["obligated_amount"]),
        "available_amount": num(rec["available_amount"]),
        "status": rec["status"],
        "effective_date": iso(rec["effective_date"]),
        "expiry_date": iso(rec["expiry_date"]),
        "surety_code": rec["surety_code"],
        "open_movement_count": rec["open_movement_count"],
    }
    out.update(_common(rec))
    return out


def port_json(rec):
    out = {
        "port_code": rec["port_code"],
        "name": rec["name"],
        "region_code": rec["region_code"],
        "exam_capacity_slots": rec["exam_capacity_slots"],
        "go_warehouse_available": rec["go_warehouse_available"],
        "open_hold_count": rec["open_hold_count"],
    }
    out.update(_common(rec))
    return out


def movement_json(rec):
    out = {
        "carrier_id": rec["carrier_id"],
        "bond_id": rec["bond_id"],
        "origin_port_id": rec["origin_port_id"],
        "destination_port_id": rec["destination_port_id"],
        "arrival_port_id": rec["arrival_port_id"],
        "predecessor_movement_id": rec["predecessor_movement_id"],
        "in_bond_type": rec["in_bond_type"],
        "manifest_reference": rec["manifest_reference"],
        "cargo_value": num(rec["cargo_value"]),
        "gross_weight_kg": num(rec["gross_weight_kg"]),
        "package_count": rec["package_count"],
        "transit_status": rec["transit_status"],
        "custody_status": rec["custody_status"],
        "obligation_amount": num(rec["obligation_amount"]),
        "transit_days_allowed": rec["transit_days_allowed"],
        "deadline_anchor_utc": iso(rec["deadline_anchor_utc"]),
        "transit_deadline_utc": iso(rec["transit_deadline_utc"]),
        "extension_days_granted": rec["extension_days_granted"],
        "overdue_days": rec["overdue_days"],
        "filed_at": iso(rec["filed_at"]),
        "seal_number": rec["seal_number"],
        "seal_intact": rec["seal_intact"],
        "arrival_reported_at": iso(rec["arrival_reported_at"]),
        "export_reported_at": iso(rec["export_reported_at"]),
        "go_deadline_utc": iso(rec["go_deadline_utc"]),
        "go_grace_applied": rec["go_grace_applied"],
        "diversion_flag": rec["diversion_flag"],
        "cancellation_reason": rec["cancellation_reason"],
    }
    out.update(_common(rec))
    return out


def ledger_json(rec):
    out = {
        "bond_id": rec["bond_id"],
        "movement_id": rec["movement_id"],
        "claim_id": rec["claim_id"],
        "entry_type": rec["entry_type"],
        "amount": num(rec["amount"]),
        "balance_after": num(rec["balance_after"]),
        "reason_code": rec["reason_code"],
        "recorded_at": iso(rec["recorded_at"]),
    }
    out.update(_common(rec, full=False))
    return out


def seal_event_json(rec):
    out = {
        "movement_id": rec["movement_id"],
        "seal_number": rec["seal_number"],
        "event_type": rec["event_type"],
        "port_code": rec["port_code"],
        "recorded_by_user_id": rec["recorded_by_user_id"],
        "occurred_at": iso(rec["occurred_at"]),
        "resulting_seal_intact": rec["resulting_seal_intact"],
    }
    out.update(_common(rec, full=False))
    return out


def hold_json(rec):
    out = {
        "movement_id": rec["movement_id"],
        "port_id": rec["port_id"],
        "hold_type": rec["hold_type"],
        "status": rec["status"],
        "scheduled_start": iso(rec["scheduled_start"]),
        "scheduled_end": iso(rec["scheduled_end"]),
        "reason_code": rec["reason_code"],
        "placed_by_user_id": rec["placed_by_user_id"],
        "released_at": iso(rec["released_at"]),
        "findings_code": rec["findings_code"],
        "discrepancy_pieces": rec["discrepancy_pieces"],
        "created_by_system": rec["created_by_system"],
    }
    out.update(_common(rec))
    return out


def amendment_json(rec):
    out = {
        "movement_id": rec["movement_id"],
        "amendment_type": rec["amendment_type"],
        "requested_destination_port_code": rec["requested_destination_port_code"],
        "requested_in_bond_type": rec["requested_in_bond_type"],
        "requested_days": rec["requested_days"],
        "justification_code": rec["justification_code"],
        "status": rec["status"],
        "granted_days": rec["granted_days"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "decided_at": iso(rec["decided_at"]),
        "decision_reason_code": rec["decision_reason_code"],
        "resulting_deadline_utc": iso(rec["resulting_deadline_utc"]),
    }
    out.update(_common(rec))
    return out


def report_json(rec):
    out = {
        "movement_id": rec["movement_id"],
        "port_id": rec["port_id"],
        "report_type": rec["report_type"],
        "packages_reported": rec["packages_reported"],
        "proof_of_export_ref": rec["proof_of_export_ref"],
        "export_conveyance_ref": rec["export_conveyance_ref"],
        "status": rec["status"],
        "reported_at": iso(rec["reported_at"]),
        "package_discrepancy": rec["package_discrepancy"],
    }
    out.update(_common(rec))
    return out


def claim_json(rec):
    out = {
        "movement_id": rec["movement_id"],
        "bond_id": rec["bond_id"],
        "claim_type": rec["claim_type"],
        "overdue_days_at_issue": rec["overdue_days_at_issue"],
        "assessed_amount": num(rec["assessed_amount"]),
        "mitigated_amount": num(rec["mitigated_amount"]),
        "paid_amount": num(rec["paid_amount"]),
        "status": rec["status"],
        "issued_by_officer_id": rec["issued_by_officer_id"],
        "issued_at": iso(rec["issued_at"]),
        "sanction_points_applied": num(rec["sanction_points_applied"]),
        "cancellation_reason": rec["cancellation_reason"],
    }
    out.update(_common(rec))
    return out


def petition_json(rec):
    out = {
        "claim_id": rec["claim_id"],
        "mitigation_factors": list(rec["mitigation_factors"]),
        "narrative_reference": rec["narrative_reference"],
        "round": rec["round"],
        "status": rec["status"],
        "mitigation_pct": num(rec["mitigation_pct"]),
        "net_before_fee": num(rec["net_before_fee"]),
        "processing_fee": num(rec["processing_fee"]),
        "offer_amount": num(rec["offer_amount"]),
        "prior_violation_count": rec["prior_violation_count"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "decision_reason_code": rec["decision_reason_code"],
        "filed_by_user_id": rec["filed_by_user_id"],
    }
    out.update(_common(rec))
    return out


def sweep_json(rec):
    out = {
        "run_at": iso(rec["run_at"]),
        "executed_by_officer_id": rec["executed_by_officer_id"],
        "overdue_marked_count": rec["overdue_marked_count"],
        "bonds_expired_count": rec["bonds_expired_count"],
        "general_order_count": rec["general_order_count"],
        "overdue_movement_ids": list(rec["overdue_movement_ids"]),
        "note": rec["note"],
    }
    out.update(_common(rec, full=False))
    return out
