"""Resource serializers. Common fields per PRD 2.4:
- twelve mutable resources carry id, created_at, updated_at, version
- CustodyEvent and CoinOrderLine are append-only: id + created_at only
"""

from core import dec2


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def _appendonly(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    return out


def vault_out(v):
    return _common(v, {
        "vault_code": v["vault_code"],
        "name": v["name"],
        "posture": v["posture"],
        "pickup_concurrency_limit": v["pickup_concurrency_limit"],
        "cash_letter_adjustment_cents": v["cash_letter_adjustment_cents"],
        "coin_face_value_on_hand_cents": v["coin_face_value_on_hand_cents"],
    })


def customer_out(c):
    return _common(c, {
        "account_number": c["account_number"],
        "customer_name": c["customer_name"],
        "tier": c["tier"],
        "status": c["status"],
        "ledger_balance_cents": c["ledger_balance_cents"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "available_balance_cents": c["available_balance_cents"],
        "risk_score": dec2(c["risk_score"]),
        "risk_grade": c["risk_grade"],
        "denied_claim_count": c["denied_claim_count"],
        "counterfeit_incident_count": c["counterfeit_incident_count"],
        "hold_count": c["hold_count"],
    })


def ticket_out(t):
    return _common(t, {
        "customer_account_id": t["customer_account_id"],
        "vault_id": t["vault_id"],
        "courier_manifest_number": t["courier_manifest_number"],
        "carrier_courier_user_id": t["carrier_courier_user_id"],
        "declared_bag_count": t["declared_bag_count"],
        "status": t["status"],
        "declared_total_cents": t["declared_total_cents"],
        "counted_total_cents": t["counted_total_cents"],
        "processing_fee_total_cents": t["processing_fee_total_cents"],
        "provisional_credit_cents": t["provisional_credit_cents"],
        "final_settlement_cents": t["final_settlement_cents"],
        "settlement_delta_cents": t["settlement_delta_cents"],
        "material_variance_open_count": t["material_variance_open_count"],
        "hold_reason": t["hold_reason"],
    })


def bag_out(b):
    return _common(b, {
        "deposit_ticket_id": b["deposit_ticket_id"],
        "seal_number": b["seal_number"],
        "bag_type": b["bag_type"],
        "declared_amount_cents": b["declared_amount_cents"],
        "declared_note_count": b["declared_note_count"],
        "declared_coin_weight_grams": b["declared_coin_weight_grams"],
        "custody_status": b["custody_status"],
        "count_status": b["count_status"],
        "counted_amount_cents": b["counted_amount_cents"],
        "counted_note_count": b["counted_note_count"],
        "counted_coin_weight_grams": b["counted_coin_weight_grams"],
        "variance_cents": b["variance_cents"],
        "materiality_flag": b["materiality_flag"],
        "processing_fee_cents": b["processing_fee_cents"],
        "seized_amount_cents": b["seized_amount_cents"],
        "claim_adjustment_cents": b["claim_adjustment_cents"],
        "settlement_amount_cents": b["settlement_amount_cents"],
        "counted_at": b["counted_at"],
    })


def custody_event_out(e):
    return _appendonly(e, {
        "sealed_bag_id": e["sealed_bag_id"],
        "event_type": e["event_type"],
        "actor_user_id": e["actor_user_id"],
        "location_code": e["location_code"],
        "observed_seal_number": e["observed_seal_number"],
        "sequence_no": e["sequence_no"],
        "seal_intact": e["seal_intact"],
    })


def machine_out(m):
    return _common(m, {
        "vault_id": m["vault_id"],
        "machine_code": m["machine_code"],
        "machine_type": m["machine_type"],
        "status": m["status"],
    })


def session_out(s):
    return _common(s, {
        "sealed_bag_id": s["sealed_bag_id"],
        "counting_machine_id": s["counting_machine_id"],
        "operator_user_id": s["operator_user_id"],
        "verifier_user_id": s["verifier_user_id"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "status": s["status"],
        "counted_amount_cents": s["counted_amount_cents"],
        "counted_note_count": s["counted_note_count"],
        "counted_coin_weight_grams": s["counted_coin_weight_grams"],
        "seized_face_value_cents": s["seized_face_value_cents"],
        "completed_at": s["completed_at"],
    })


def lot_out(l):
    return _common(l, {
        "count_session_id": l["count_session_id"],
        "fed_deposit_id": l["fed_deposit_id"],
        "category": l["category"],
        "denomination_cents": l["denomination_cents"],
        "note_count": l["note_count"],
        "face_value_cents": l["face_value_cents"],
        "status": l["status"],
    })


def report_out(r):
    return _common(r, {
        "fitness_lot_id": r["fitness_lot_id"],
        "serial_number": r["serial_number"],
        "denomination_cents": r["denomination_cents"],
        "note_count": r["note_count"],
        "status": r["status"],
        "seized_face_value_cents": r["seized_face_value_cents"],
        "submitted_at": r["submitted_at"],
        "case_number": r["case_number"],
        "correction_note": r["correction_note"],
    })


def claim_out(c):
    return _common(c, {
        "sealed_bag_id": c["sealed_bag_id"],
        "customer_account_id": c["customer_account_id"],
        "claim_type": c["claim_type"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "status": c["status"],
        "review_round": c["review_round"],
        "resolution_amount_cents": c["resolution_amount_cents"],
        "filed_at": c["filed_at"],
        "decided_by_user_id": c["decided_by_user_id"],
        "info_request_note": c["info_request_note"],
        "denial_reason": c["denial_reason"],
    })


def fed_deposit_out(f):
    return _common(f, {
        "vault_id": f["vault_id"],
        "cash_letter_number": f["cash_letter_number"],
        "deposit_date": f["deposit_date"],
        "status": f["status"],
        "declared_total_cents": f["declared_total_cents"],
        "credited_total_cents": f["credited_total_cents"],
        "adjustment_cents": f["adjustment_cents"],
        "attached_lot_count": f["attached_lot_count"],
        "submitted_at": f["submitted_at"],
        "confirmed_at": f["confirmed_at"],
    })


def coin_order_out(o):
    return _common(o, {
        "customer_account_id": o["customer_account_id"],
        "vault_id": o["vault_id"],
        "pickup_window_start": o["pickup_window_start"],
        "pickup_window_end": o["pickup_window_end"],
        "status": o["status"],
        "approved_by_user_id": o["approved_by_user_id"],
        "released_by_user_id": o["released_by_user_id"],
        "total_boxes_requested": o["total_boxes_requested"],
        "total_boxes_allocated": o["total_boxes_allocated"],
        "fill_ratio_pct": dec2(o["fill_ratio_pct"]),
        "charge_cents": o["charge_cents"],
        "return_reason": o["return_reason"],
    })


def coin_line_out(l):
    return _appendonly(l, {
        "coin_order_id": l["coin_order_id"],
        "denomination": l["denomination"],
        "boxes_requested": l["boxes_requested"],
        "boxes_allocated": l["boxes_allocated"],
        "boxes_returned": l["boxes_returned"],
        "line_face_value_cents": l["line_face_value_cents"],
    })


def inventory_out(i):
    return _common(i, {
        "vault_id": i["vault_id"],
        "denomination": i["denomination"],
        "on_hand_boxes": i["on_hand_boxes"],
        "reserved_boxes": i["reserved_boxes"],
        "available_boxes": i["available_boxes"],
    })
