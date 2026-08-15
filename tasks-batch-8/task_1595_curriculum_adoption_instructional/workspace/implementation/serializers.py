"""Entity serializers — every scaffold field, nulls included.

CommitteeVote is the single exception to the common-fields contract
(PRD §2.5): it carries only id + created_at (no updated_at, no version).
"""

from db import fmt_dt
from services.calculations import (ledger_available, lot_allocated_units,
                                   lot_available_units, pilot_submitted_review_count)


def _num(value):
    """Decimal -> float for JSON; ints and None pass through."""
    if value is None:
        return None
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_dt(entity["created_at"]),
        "updated_at": fmt_dt(entity["updated_at"]),
        "version": entity["version"],
    }


def framework(f):
    d = _common(f)
    d.update({
        "code": f["code"],
        "subject_area": f["subject_area"],
        "grade_band": f["grade_band"],
        "standards_required_count": f["standards_required_count"],
        "effective_year": f["effective_year"],
        "status": f["status"],
    })
    return d


def cycle(c):
    d = _common(c)
    d.update({
        "subject_area": c["subject_area"],
        "grade_band": c["grade_band"],
        "school_year_start": c["school_year_start"],
        "framework_id": c["framework_id"],
        "award_method": c["award_method"],
        "district_enrollment": c["district_enrollment"],
        "status": c["status"],
        "public_review_opens_at": fmt_dt(c.get("public_review_opens_at")),
        "public_review_closes_at": fmt_dt(c.get("public_review_closes_at")),
        "adopted_material_id": c.get("adopted_material_id"),
        "pinned_quote_id": c.get("pinned_quote_id"),
        "quote_version_pin": c.get("quote_version_pin"),
        "open_backorder_count": c.get("open_backorder_count", 0),
        "replacement_due": c.get("replacement_due", False),
    })
    return d


def material(m):
    d = _common(m)
    d.update({
        "cycle_id": m["cycle_id"],
        "title": m["title"],
        "publisher_name": m["publisher_name"],
        "isbn": m.get("isbn"),
        "material_type": m["material_type"],
        "adoption_status": m["adoption_status"],
        "availability_status": m["availability_status"],
        "coverage_pct": _num(m.get("coverage_pct")),
        "provisional_composite": _num(m.get("provisional_composite")),
        "official_composite": _num(m.get("official_composite")),
        "participation_rate": _num(m.get("participation_rate")),
        "adopted_at": fmt_dt(m.get("adopted_at")),
    })
    return d


def alignment(a):
    d = _common(a)
    d.update({
        "material_id": a["material_id"],
        "standard_code": a["standard_code"],
        "coverage_rating": a["coverage_rating"],
    })
    return d


def pilot(p):
    d = _common(p)
    d.update({
        "cycle_id": p["cycle_id"],
        "material_id": p["material_id"],
        "school_code": p["school_code"],
        "starts_on": p["starts_on"].isoformat(),
        "ends_on": p["ends_on"].isoformat(),
        "teacher_count": p["teacher_count"],
        "status": p["status"],
        "submitted_review_count": pilot_submitted_review_count(p),
    })
    return d


def review(rv):
    d = _common(rv)
    d.update({
        "pilot_id": rv["pilot_id"],
        "teacher_user_id": rv["teacher_user_id"],
        "pedagogy_score": rv["pedagogy_score"],
        "alignment_score": rv["alignment_score"],
        "usability_score": rv["usability_score"],
        "equity_score": rv["equity_score"],
        "review_composite": _num(rv["review_composite"]),
        "status": rv["status"],
        "submitted_at": fmt_dt(rv["submitted_at"]),
    })
    return d


def quote(q):
    d = _common(q)
    d.update({
        "cycle_id": q["cycle_id"],
        "material_id": q["material_id"],
        "publisher_name": q["publisher_name"],
        "print_unit_price": _num(q["print_unit_price"]),
        "print_quantity": q["print_quantity"],
        "digital_seat_rate": _num(q["digital_seat_rate"]),
        "digital_seat_count": q["digital_seat_count"],
        "bundle_discount_pct": _num(q.get("bundle_discount_pct")),
        "training_sessions": q["training_sessions"],
        "license_years": q["license_years"],
        "evaluated_total": _num(q.get("evaluated_total")),
        "best_value_score": _num(q.get("best_value_score")),
        "status": q["status"],
        "submitted_at": fmt_dt(q["submitted_at"]),
    })
    return d


def purchase_order(po):
    d = _common(po)
    d.update({
        "cycle_id": po["cycle_id"],
        "quote_id": po["quote_id"],
        "print_quantity": po["print_quantity"],
        "digital_seat_count": po["digital_seat_count"],
        "total_amount": _num(po["total_amount"]),
        "amount_paid": _num(po["amount_paid"]),
        "received_print_qty": po["received_print_qty"],
        "quote_version_pin": po["quote_version_pin"],
        "order_status": po["order_status"],
        "payment_status": po["payment_status"],
    })
    return d


def inventory_lot(lot):
    d = _common(lot)
    allocated = lot_allocated_units(lot["material_id"])
    d.update({
        "material_id": lot["material_id"],
        "on_hand_units": lot["on_hand_units"],
        "in_transit_units": lot["in_transit_units"],
        "delivered_units": lot["delivered_units"],
        "total_received_units": lot["total_received_units"],
        "allocated_units": allocated,
        "available_units": lot["on_hand_units"] - allocated,
    })
    return d


def distribution_order(do):
    d = _common(do)
    d.update({
        "material_id": do["material_id"],
        "school_code": do["school_code"],
        "classroom_label": do["classroom_label"],
        "quantity": do["quantity"],
        "need_priority": do["need_priority"],
        "status": do["status"],
    })
    return d


def supplemental_request(sr):
    d = _common(sr)
    d.update({
        "cycle_id": sr["cycle_id"],
        "requester_user_id": sr["requester_user_id"],
        "title": sr["title"],
        "publisher_name": sr["publisher_name"],
        "estimated_cost": _num(sr["estimated_cost"]),
        "subject_area": sr["subject_area"],
        "grade_band": sr["grade_band"],
        "school_code": sr["school_code"],
        "justification": sr.get("justification"),
        "approver_user_id": sr.get("approver_user_id"),
        "approved_at": fmt_dt(sr.get("approved_at")),
        "status": sr["status"],
    })
    return d


def challenge_case(cc):
    d = _common(cc)
    d.update({
        "target_type": cc["target_type"],
        "target_id": cc["target_id"],
        "grounds": cc["grounds"],
        "filer_user_id": cc["filer_user_id"],
        "status": cc["status"],
        "decision": cc.get("decision"),
        "vote_round": cc["vote_round"],
        "appeal_used": cc["appeal_used"],
        "filed_at": fmt_dt(cc["filed_at"]),
        "decided_at": fmt_dt(cc.get("decided_at")),
    })
    return d


def committee_vote(v):
    # Immutable record: only id + created_at (PRD §2.5 exception).
    return {
        "id": v["id"],
        "challenge_id": v["challenge_id"],
        "voter_user_id": v["voter_user_id"],
        "vote": v["vote"],
        "vote_round": v["vote_round"],
        "created_at": fmt_dt(v["created_at"]),
    }


def budget_ledger(ledger):
    d = _common(ledger)
    d.update({
        "cycle_id": ledger["cycle_id"],
        "appropriation_total": _num(ledger["appropriation_total"]),
        "encumbered_total": _num(ledger["encumbered_total"]),
        "expended_total": _num(ledger["expended_total"]),
        "available_balance": _num(ledger_available(ledger)),
    })
    return d
