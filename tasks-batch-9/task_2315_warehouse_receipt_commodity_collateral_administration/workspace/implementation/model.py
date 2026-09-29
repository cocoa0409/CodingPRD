"""Derived figures, resource serialisation, lookups, ownership checks and the
cascade helpers shared by the route modules.
"""

from core import (ApiError, dec, fail, iso, now, now_iso, num_out, ordered,
                  store, touch)
import calc


# ===========================================================================
# Lookups (ladder rank 7 — the 404 family, resolved left to right)
# ===========================================================================

def get_warehouse(warehouse_id):
    row = store.warehouses.get(warehouse_id)
    if row is None:
        fail("ERR_WAREHOUSE_NOT_FOUND", 404)
    return row


def get_party(party_id):
    row = store.parties.get(party_id)
    if row is None:
        fail("ERR_PARTY_NOT_FOUND", 404)
    return row


def get_agreement(agreement_id):
    row = store.agreements.get(agreement_id)
    if row is None:
        fail("ERR_AGREEMENT_NOT_FOUND", 404)
    return row


def get_bin(bin_id):
    row = store.bins.get(bin_id)
    if row is None:
        fail("ERR_BIN_NOT_FOUND", 404)
    return row


def get_ticket(ticket_id):
    row = store.tickets.get(ticket_id)
    if row is None:
        fail("ERR_TICKET_NOT_FOUND", 404)
    return row


def get_receipt(receipt_id):
    row = store.receipts.get(receipt_id)
    if row is None:
        fail("ERR_RECEIPT_NOT_FOUND", 404)
    return row


def get_lien(lien_id):
    row = store.liens.get(lien_id)
    if row is None:
        fail("ERR_LIEN_NOT_FOUND", 404)
    return row


def get_report(report_id):
    row = store.reports.get(report_id)
    if row is None:
        fail("ERR_REPORT_NOT_FOUND", 404)
    return row


def get_order(order_id):
    row = store.orders.get(order_id)
    if row is None:
        fail("ERR_DELIVERY_ORDER_NOT_FOUND", 404)
    return row


def get_claim(claim_id):
    row = store.claims.get(claim_id)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", 404)
    return row


# ===========================================================================
# Relationship helpers
# ===========================================================================

def ticket_agreement(ticket):
    return store.agreements[ticket["storage_agreement_id"]]


def ticket_warehouse_id(ticket):
    return ticket_agreement(ticket)["warehouse_id"]


def receipt_agreement(receipt):
    return store.agreements[receipt["storage_agreement_id"]]


def order_receipt(order):
    return store.receipts[order["receipt_id"]]


def lien_receipt(lien):
    return store.receipts[lien["receipt_id"]]


def warehouse_of_order(order):
    return store.warehouses[order_receipt(order)["warehouse_id"]]


def warehouse_bins(warehouse_id):
    return [b for b in store.bins.values() if b["warehouse_id"] == warehouse_id]


def warehouse_receipts(warehouse_id):
    return [r for r in store.receipts.values()
            if r["warehouse_id"] == warehouse_id]


def warehouse_tickets(warehouse_id):
    return [t for t in store.tickets.values()
            if ticket_warehouse_id(t) == warehouse_id]


def warehouse_reports(warehouse_id):
    return [r for r in store.reports.values()
            if r["warehouse_id"] == warehouse_id]


def warehouse_claims(warehouse_id):
    return [c for c in store.claims.values()
            if c["warehouse_id"] == warehouse_id]


def agreement_tickets(agreement_id):
    return [t for t in store.tickets.values()
            if t["storage_agreement_id"] == agreement_id]


def agreement_receipts(agreement_id):
    return [r for r in store.receipts.values()
            if r["storage_agreement_id"] == agreement_id]


def bin_tickets(bin_id):
    return [t for t in store.tickets.values() if t["bin_id"] == bin_id]


def receipt_orders(receipt_id):
    return [o for o in store.orders.values() if o["receipt_id"] == receipt_id]


def receipt_liens(receipt_id):
    return [l for l in store.liens.values() if l["receipt_id"] == receipt_id]


def bin_receipts(bin_id):
    return [r for r in store.receipts.values() if r["bin_id"] == bin_id]


# ===========================================================================
# Bin derived figures (PRD §3.2)
# ===========================================================================

def bin_held_bushels(bin_id):
    total = 0
    for order in store.orders.values():
        if order["delivery_state"] not in ("REQUESTED", "LOADED"):
            continue
        receipt = store.receipts.get(order["receipt_id"])
        if receipt is not None and receipt["bin_id"] == bin_id:
            total += order["requested_bushels"]
    return total


def bin_scheduled_inbound_bushels(bin_id, exclude_ticket_id=None):
    total = 0
    for ticket in store.tickets.values():
        if ticket["bin_id"] != bin_id or ticket["ticket_state"] != "WEIGHED":
            continue
        if exclude_ticket_id is not None and ticket["id"] == exclude_ticket_id:
            continue
        total += ticket["net_bushels"]
    return total


def bin_blended_grade(bin_id):
    """PRD §3.2 — the worst assigned_grade among the tickets accepted into the
    bin, and null while the bin is empty.  Receipting a ticket does not move its
    grain out of the bin, so a RECEIPTED ticket still contributes to the blend.
    """
    bin_row = store.bins.get(bin_id)
    if bin_row is not None and bin_row["stored_bushels"] <= 0:
        return None
    worst = None
    for ticket in store.tickets.values():
        if (ticket["bin_id"] != bin_id
                or ticket["ticket_state"] not in ("ACCEPTED", "RECEIPTED")):
            continue
        grade = ticket["assigned_grade"]
        if worst is None or calc.GRADE_RANK[grade] > calc.GRADE_RANK[worst]:
            worst = grade
    return worst


def bin_headroom(bin_row, exclude_ticket_id=None):
    return (bin_row["capacity_bushels"] - bin_row["stored_bushels"]
            - bin_held_bushels(bin_row["id"])
            - bin_scheduled_inbound_bushels(bin_row["id"], exclude_ticket_id))


# ===========================================================================
# Warehouse derived figures (PRD §3.7, §2.11)
# ===========================================================================

def receipted_obligation_bushels(warehouse_id):
    return sum(r["quantity_bushels"] for r in store.receipts.values()
               if r["warehouse_id"] == warehouse_id
               and r["receipt_state"] == "ISSUED")


def unreceipted_obligation_bushels(warehouse_id):
    total = 0
    for ticket in store.tickets.values():
        if ticket["ticket_state"] != "ACCEPTED":
            continue
        if ticket_warehouse_id(ticket) == warehouse_id:
            total += ticket["net_bushels"]
    return total


def obligation_bushels(warehouse_id):
    return (receipted_obligation_bushels(warehouse_id)
            + unreceipted_obligation_bushels(warehouse_id))


def system_physical_bushels(warehouse_id):
    return sum(b["stored_bushels"] for b in warehouse_bins(warehouse_id))


def sound_physical_bushels(warehouse_id):
    return sum(b["stored_bushels"] for b in warehouse_bins(warehouse_id)
               if b["condition_state"] in ("SOUND", "WATCH"))


def latest_submitted_report(warehouse_id):
    submitted = [r for r in warehouse_reports(warehouse_id)
                 if r["submitted_at"] is not None]
    if not submitted:
        return None
    submitted.sort(key=lambda r: (r["submitted_at"], r["created_at"], r["_seq"]))
    best = submitted[-1]
    # ties on submitted_at broken by the earlier created_at
    tied = [r for r in submitted if r["submitted_at"] == best["submitted_at"]]
    tied.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return tied[0]


def operational_posture(warehouse):
    if (warehouse["license_state"] != "LICENSED"
            or warehouse["insolvency_state"] != "SOLVENT"):
        return "CLOSED"
    obligation = obligation_bushels(warehouse["id"])
    variance = sound_physical_bushels(warehouse["id"]) - obligation
    tolerance = calc.examination_tolerance(obligation)
    if abs(variance) > tolerance:
        return "RESTRICTED"
    latest = latest_submitted_report(warehouse["id"])
    if latest is not None and latest["report_state"] == "REJECTED":
        return "RESTRICTED"
    return "OPEN"


# ===========================================================================
# Party derived figures (PRD §3.2)
# ===========================================================================

def committed_advance_cents(party_id):
    return sum(l["advance_limit_cents"] for l in store.liens.values()
               if l["lender_party_id"] == party_id
               and l["lien_state"] == "PERFECTED")


def available_credit_cents(party):
    return party["credit_line_cents"] - committed_advance_cents(party["id"])


def settlement_balance_cents(party_id):
    total = 0
    for order in store.orders.values():
        if order["delivery_state"] not in ("SETTLED_FULL", "SETTLED_PARTIAL"):
            continue
        if order["requester_party_id"] == party_id:
            total += order["net_settlement_cents"] or 0
    return total


# ===========================================================================
# Receipt derived figures
# ===========================================================================

def quality_flag(receipt):
    bin_row = store.bins.get(receipt["bin_id"])
    if bin_row is not None and bin_row["condition_state"] == "OUT_OF_CONDITION":
        return "IMPAIRED"
    return "SOUND"


def provisional_storage_charge_cents(receipt, as_of_date=None):
    agreement = receipt_agreement(receipt)
    if as_of_date is None:
        as_of_date = now().date()
    return calc.storage_charge_accrual(
        "PROVISIONAL", receipt["quantity_bushels"],
        agreement["storage_rate_millicents_per_bushel_day"],
        agreement["free_storage_days"], receipt["_issued_at_dt"], as_of_date)


# ===========================================================================
# Serialisers
# ===========================================================================

def warehouse_out(w):
    financials = calc.license_financials(
        w["license_program"], w["licensed_capacity_bushels"],
        w["bond_amount_cents"], w["net_worth_cents"])
    obligation = obligation_bushels(w["id"])
    sound = sound_physical_bushels(w["id"])
    claims = warehouse_claims(w["id"])
    out = {
        "id": w["id"],
        "name": w["name"],
        "operator_name": w["operator_name"],
        "state_code": w["state_code"],
        "license_program": w["license_program"],
        "licensed_capacity_bushels": w["licensed_capacity_bushels"],
        "bond_amount_cents": w["bond_amount_cents"],
        "net_worth_cents": w["net_worth_cents"],
        "loadout_lane_count": w["loadout_lane_count"],
        "registry_participant": w["registry_participant"],
        "license_state": w["license_state"],
        "insolvency_state": w["insolvency_state"],
        "licensed_by_user_id": w["licensed_by_user_id"],
        "license_effective_date": w["license_effective_date"],
        "license_expiry_date": w["license_expiry_date"],
        "obligation_bushels": obligation,
        "receipted_obligation_bushels": receipted_obligation_bushels(w["id"]),
        "system_physical_bushels": system_physical_bushels(w["id"]),
        "sound_physical_bushels": sound,
        "position_variance_bushels": sound - obligation,
        "examination_tolerance_bushels": calc.examination_tolerance(obligation),
        "operational_posture": operational_posture(w),
        "insolvency_declared_at": w["insolvency_declared_at"],
        "insolvency_price_cents_per_bushel":
            w["insolvency_price_cents_per_bushel"],
        "allowed_claim_total_cents": sum(
            c["allowed_cents"] for c in claims
            if c["claim_state"] in ("ALLOWED", "SETTLED")),
        "bond_allocated_cents": sum(c["bond_share_cents"] for c in claims),
        "fund_allocated_cents": sum(c["fund_share_cents"] for c in claims),
        "unpaid_claim_total_cents": sum(c["unpaid_cents"] for c in claims),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }
    out.update(financials)
    out["allocated_total_cents"] = (out["bond_allocated_cents"]
                                   + out["fund_allocated_cents"])
    return out


def party_out(p):
    committed = committed_advance_cents(p["id"])
    return {
        "id": p["id"],
        "name": p["name"],
        "party_kind": p["party_kind"],
        "state_code": p["state_code"],
        "credit_line_cents": p["credit_line_cents"],
        "committed_advance_cents": committed,
        "available_credit_cents": p["credit_line_cents"] - committed,
        "settlement_balance_cents": settlement_balance_cents(p["id"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def agreement_out(a):
    return {
        "id": a["id"],
        "warehouse_id": a["warehouse_id"],
        "depositor_party_id": a["depositor_party_id"],
        "commodity": a["commodity"],
        "storage_kind": a["storage_kind"],
        "min_grade": a["min_grade"],
        "max_moisture_pct": num_out(a["max_moisture_pct"]),
        "storage_rate_millicents_per_bushel_day":
            a["storage_rate_millicents_per_bushel_day"],
        "receiving_charge_cents_per_bushel": a["receiving_charge_cents_per_bushel"],
        "loadout_charge_cents_per_bushel": a["loadout_charge_cents_per_bushel"],
        "free_storage_days": a["free_storage_days"],
        "declared_value_cents_per_bushel": a["declared_value_cents_per_bushel"],
        "agreement_state": a["agreement_state"],
        "termination_reason": a["termination_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def bin_out(b):
    held = bin_held_bushels(b["id"])
    return {
        "id": b["id"],
        "warehouse_id": b["warehouse_id"],
        "bin_code": b["bin_code"],
        "capacity_bushels": b["capacity_bushels"],
        "commodity": b["commodity"],
        "commingling_allowed": b["commingling_allowed"],
        "dedicated_agreement_id": b["dedicated_agreement_id"],
        "stored_bushels": b["stored_bushels"],
        "held_bushels": held,
        "available_bushels": b["stored_bushels"] - held,
        "scheduled_inbound_bushels": bin_scheduled_inbound_bushels(b["id"]),
        "condition_state": b["condition_state"],
        "last_moisture_pct": num_out(b["last_moisture_pct"]),
        "last_temperature_f": num_out(b["last_temperature_f"]),
        "last_treatment_action": b["last_treatment_action"],
        "last_assessed_at": b["last_assessed_at"],
        "cumulative_shrink_bushels": b["cumulative_shrink_bushels"],
        "blended_grade": bin_blended_grade(b["id"]),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ticket_out(t):
    return {
        "id": t["id"],
        "storage_agreement_id": t["storage_agreement_id"],
        "bin_id": t["bin_id"],
        "gross_bushels": t["gross_bushels"],
        "test_weight_lbs": num_out(t["test_weight_lbs"]),
        "moisture_pct": num_out(t["moisture_pct"]),
        "damage_pct": num_out(t["damage_pct"]),
        "foreign_material_pct": num_out(t["foreign_material_pct"]),
        "dockage_pct": num_out(t["dockage_pct"]),
        "fill_start_at": t["fill_start_at"],
        "fill_end_at": t["fill_end_at"],
        "assigned_grade": t["assigned_grade"],
        "dockage_bushels": t["dockage_bushels"],
        "clean_bushels": t["clean_bushels"],
        "shrink_bushels": t["shrink_bushels"],
        "net_bushels": t["net_bushels"],
        "settlement_variant": t["settlement_variant"],
        "ticket_state": t["ticket_state"],
        "rejection_reason": t["rejection_reason"],
        "accepted_at": t["accepted_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def receipt_out(r):
    return {
        "id": r["id"],
        "warehouse_id": r["warehouse_id"],
        "deposit_ticket_id": r["deposit_ticket_id"],
        "storage_agreement_id": r["storage_agreement_id"],
        "bin_id": r["bin_id"],
        "holder_party_id": r["holder_party_id"],
        "registry_control_party_id": r["registry_control_party_id"],
        "receipt_number": r["receipt_number"],
        "form": r["form"],
        "medium": r["medium"],
        "quantity_bushels": r["quantity_bushels"],
        "grade": r["grade"],
        "moisture_pct": num_out(r["moisture_pct"]),
        "face_price_cents_per_bushel": r["face_price_cents_per_bushel"],
        "receiving_charge_cents": r["receiving_charge_cents"],
        "issued_at": r["issued_at"],
        "receipt_state": r["receipt_state"],
        "encumbrance_state": r["encumbrance_state"],
        "quality_flag": quality_flag(r),
        "provisional_storage_charge_cents": provisional_storage_charge_cents(r),
        "transfer_log": r["transfer_log"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def lien_out(l):
    return {
        "id": l["id"],
        "receipt_id": l["receipt_id"],
        "lender_party_id": l["lender_party_id"],
        "pledgor_party_id": l["pledgor_party_id"],
        "principal_cents": l["principal_cents"],
        "valuation_basis": l["valuation_basis"],
        "mark_price_cents_per_bushel": l["mark_price_cents_per_bushel"],
        "perfection_method": l["perfection_method"],
        "gross_value_cents": l["gross_value_cents"],
        "grade_discount_bps": l["grade_discount_bps"],
        "eligible_value_cents": l["eligible_value_cents"],
        "admin_fee_cents": l["admin_fee_cents"],
        "warehouseman_lien_cents": l["warehouseman_lien_cents"],
        "net_collateral_cents": l["net_collateral_cents"],
        "advance_rate_bps": l["advance_rate_bps"],
        "advance_limit_cents": l["advance_limit_cents"],
        "margin_deficiency_cents": l["margin_deficiency_cents"],
        "margin_status": l["margin_status"],
        "lien_state": l["lien_state"],
        "perfected_at": l["perfected_at"],
        "released_at": l["released_at"],
        "payoff_received_cents": l["payoff_received_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def report_out(r):
    return {
        "id": r["id"],
        "warehouse_id": r["warehouse_id"],
        "period_start_date": r["period_start_date"],
        "period_end_date": r["period_end_date"],
        "as_of_date": r["as_of_date"],
        "reported_physical_bushels": r["reported_physical_bushels"],
        "reported_obligation_bushels": r["reported_obligation_bushels"],
        "obligation_bushels": r["obligation_bushels"],
        "system_physical_bushels": r["system_physical_bushels"],
        "sound_physical_bushels": r["sound_physical_bushels"],
        "position_variance_bushels": r["position_variance_bushels"],
        "count_discrepancy_bushels": r["count_discrepancy_bushels"],
        "obligation_misstatement_bushels": r["obligation_misstatement_bushels"],
        "examination_tolerance_bushels": r["examination_tolerance_bushels"],
        "examination_required": r["examination_required"],
        "report_state": r["report_state"],
        "revision_count": r["revision_count"],
        "examination_result": r["examination_result"],
        "examined_by_user_id": r["examined_by_user_id"],
        "findings_note": r["findings_note"],
        "submitted_at": r["submitted_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def order_out(o):
    return {
        "id": o["id"],
        "receipt_id": o["receipt_id"],
        "requester_party_id": o["requester_party_id"],
        "requested_bushels": o["requested_bushels"],
        "appointment_start_at": o["appointment_start_at"],
        "appointment_end_at": o["appointment_end_at"],
        "lane_index": o["lane_index"],
        "delivered_bushels": o["delivered_bushels"],
        "delivered_test_weight_lbs": num_out(o["delivered_test_weight_lbs"]),
        "delivered_moisture_pct": num_out(o["delivered_moisture_pct"]),
        "delivered_damage_pct": num_out(o["delivered_damage_pct"]),
        "delivered_foreign_material_pct":
            num_out(o["delivered_foreign_material_pct"]),
        "delivered_grade": o["delivered_grade"],
        "grade_delta_bps": o["grade_delta_bps"],
        "settlement_price_cents_per_bushel":
            o["settlement_price_cents_per_bushel"],
        "quality_adjustment_cents": o["quality_adjustment_cents"],
        "storage_charge_cents": o["storage_charge_cents"],
        "loadout_charge_cents": o["loadout_charge_cents"],
        "net_settlement_cents": o["net_settlement_cents"],
        "delivery_state": o["delivery_state"],
        "loaded_at": o["loaded_at"],
        "settled_at": o["settled_at"],
        "cancelled_at": o["cancelled_at"],
        "cancellation_reason": o["cancellation_reason"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def claim_out(c):
    return {
        "id": c["id"],
        "warehouse_id": c["warehouse_id"],
        "receipt_id": c["receipt_id"],
        "claimant_party_id": c["claimant_party_id"],
        "claimed_cents": c["claimed_cents"],
        "entitlement_cents": c["entitlement_cents"],
        "allowed_cents": c["allowed_cents"],
        "fund_eligible": c["fund_eligible"],
        "bond_share_cents": c["bond_share_cents"],
        "fund_share_cents": c["fund_share_cents"],
        "unpaid_cents": c["unpaid_cents"],
        "claim_state": c["claim_state"],
        "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        "adjudication_note": c["adjudication_note"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ===========================================================================
# Ownership (ladder rank 3 — ERR_NOT_RESOURCE_OWNER)
# ===========================================================================

def not_owner():
    fail("ERR_NOT_RESOURCE_OWNER", 403)


def require_operator_warehouse(caller, warehouse_id):
    if caller.role == "WarehouseOperator" and caller.user_id != warehouse_id:
        not_owner()


def require_depositor_party(caller, *party_ids):
    if caller.role == "Depositor" and caller.user_id not in party_ids:
        not_owner()


# ===========================================================================
# Regulatory gates (ladder ranks 11-13)
# ===========================================================================

def gate_licensed(warehouse):
    if warehouse["license_state"] != "LICENSED":
        fail("ERR_WAREHOUSE_NOT_LICENSED", 422)


def gate_solvent(warehouse):
    if warehouse["insolvency_state"] != "SOLVENT":
        fail("ERR_WAREHOUSE_INSOLVENT", 422)


def gate_not_restricted(warehouse):
    if operational_posture(warehouse) == "RESTRICTED":
        fail("ERR_POSTURE_RESTRICTED", 422)


def gate_bin_condition(bin_row):
    if bin_row["condition_state"] == "OUT_OF_CONDITION":
        fail("ERR_BIN_OUT_OF_CONDITION", 422)


# ===========================================================================
# Cascades (PRD §2.12)
# ===========================================================================

def revalue_lien(lien):
    """Re-run the seven-step valuation at the current logical clock."""
    receipt = lien_receipt(lien)
    result = calc.collateral_valuation(
        lien["valuation_basis"], lien["mark_price_cents_per_bushel"],
        receipt["quantity_bushels"], receipt["grade"], quality_flag(receipt),
        receipt["face_price_cents_per_bushel"],
        provisional_storage_charge_cents(receipt),
        receipt["receiving_charge_cents"], lien["principal_cents"])
    lien.update(result)
    return result


def cascade_impairment(bin_row):
    """Bin -> WarehouseReceipt -> CollateralLien -> Party, three hops."""
    touched_parties = set()
    for receipt in bin_receipts(bin_row["id"]):
        if receipt["receipt_state"] != "ISSUED":
            continue
        touch(receipt)          # quality_flag is recomputed on the row
        for lien in receipt_liens(receipt["id"]):
            if lien["lien_state"] != "PERFECTED":
                continue
            revalue_lien(lien)
            touch(lien)
            touched_parties.add(lien["lender_party_id"])
    for party_id in touched_parties:
        party = store.parties.get(party_id)
        if party is not None:
            touch(party)


def reject_weighed_tickets(warehouse_id, reason):
    for ticket in warehouse_tickets(warehouse_id):
        if ticket["ticket_state"] != "WEIGHED":
            continue
        ticket["ticket_state"] = "REJECTED"
        ticket["rejection_reason"] = reason
        touch(ticket)


def cancel_requested_orders(warehouse_id, reason):
    for order in store.orders.values():
        if order["delivery_state"] != "REQUESTED":
            continue
        receipt = store.receipts.get(order["receipt_id"])
        if receipt is None or receipt["warehouse_id"] != warehouse_id:
            continue
        order["delivery_state"] = "CANCELLED"
        order["cancelled_at"] = now_iso()
        order["cancellation_reason"] = reason
        touch(order)
