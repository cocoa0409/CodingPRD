"""Entity serializers. Computed/counter fields are derived from the store at read time."""
from decimal import Decimal, ROUND_HALF_UP

from store import STORE, iso


def dec2str_num(d):
    """Decimal -> JSON number (float, e.g. Decimal('100.50') -> 100.5)."""
    return float(d)


def parcel_frontage(p):
    return Decimal(p["frontage_ft"])


def eligible_parcels(district_id):
    return [p for p in STORE.parcels.values()
            if p["district_id"] == district_id
            and p["status"] == "ACTIVE" and not p["exempt"]]


def district_totals(d):
    eps = eligible_parcels(d["id"])
    total_frontage = sum((parcel_frontage(p) for p in eps), Decimal("0"))
    return total_frontage, len(eps)


def district_assessment_counts(d):
    paid = 0
    total = 0
    for a in STORE.assessments.values():
        if a["district_id"] != d["id"]:
            continue
        if a["status"] in ("REMOVED", "SUPERSEDED"):
            continue
        total += 1
        if a["status"] == "PAID_OFF":
            paid += 1
    return paid, total


def district_approved_change_total(d):
    return sum(co["amount_cents"] for co in STORE.change_orders.values()
               if co["district_id"] == d["id"] and co["status"] == "APPROVED")


def round_half_up_cents(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def district_overrun_flag(d, approved_total):
    est_id = d.get("approved_estimate_id")
    if not est_id:
        return False
    est = STORE.estimates.get(est_id)
    if not est:
        return False
    cap = round_half_up_cents(Decimal(est["contract_price_cents"]) * Decimal("0.10"))
    return approved_total > cap


def ser_district(d):
    total_frontage, eligible_count = district_totals(d)
    paid, total = district_assessment_counts(d)
    approved_change_total = district_approved_change_total(d)
    return {
        "id": d["id"],
        "name": d["name"],
        "methodology": d["methodology"],
        "interest_method": d["interest_method"],
        "annual_interest_rate_bp": d["annual_interest_rate_bp"],
        "season_start_mmdd": d["season_start_mmdd"],
        "season_end_mmdd": d["season_end_mmdd"],
        "status": d["status"],
        "remand_count": d["remand_count"],
        "total_frontage_ft": dec2str_num(total_frontage),
        "eligible_parcel_count": eligible_count,
        "protest_frontage_pct": d["protest_frontage_pct"],
        "approved_estimate_id": d["approved_estimate_id"],
        "approved_change_total_cents": approved_change_total,
        "overrun_flag": district_overrun_flag(d, approved_change_total),
        "final_total_cost_cents": d["final_total_cost_cents"],
        "levy_date": iso(d["levy_date"]),
        "payment_option_deadline": iso(d["payment_option_deadline"]),
        "paid_assessment_count": paid,
        "total_assessment_count": total,
        "all_assessments_paid": total > 0 and paid == total,
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def ser_owner(o):
    return {
        "id": o["id"],
        "full_name": o["full_name"],
        "email": o["email"],
        "mailing_address": o["mailing_address"],
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_parcel(p):
    return {
        "id": p["id"],
        "district_id": p["district_id"],
        "owner_id": p["owner_id"],
        "parcel_number": p["parcel_number"],
        "frontage_ft": dec2str_num(Decimal(p["frontage_ft"])),
        "exempt": p["exempt"],
        "status": p["status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def petition_tallies(pet):
    count = 0
    frontage = Decimal("0")
    for s in STORE.signatures.values():
        if s["petition_id"] == pet["id"] and s["status"] == "VERIFIED":
            count += 1
            parcel = STORE.parcels.get(s["parcel_id"])
            if parcel:
                frontage += parcel_frontage(parcel)
    return count, frontage


def ser_petition(pet):
    count, frontage = petition_tallies(pet)
    return {
        "id": pet["id"],
        "district_id": pet["district_id"],
        "status": pet["status"],
        "opened_at": iso(pet["opened_at"]),
        "closed_at": iso(pet["closed_at"]),
        "verified_signature_count": count,
        "verified_frontage_ft": dec2str_num(frontage),
        "eligible_parcel_count_snapshot": pet["eligible_parcel_count_snapshot"],
        "eligible_frontage_snapshot": (
            dec2str_num(pet["eligible_frontage_snapshot"])
            if pet["eligible_frontage_snapshot"] is not None else None),
        "support_count_pct": pet["support_count_pct"],
        "support_frontage_pct": pet["support_frontage_pct"],
        "created_at": iso(pet["created_at"]),
        "updated_at": iso(pet["updated_at"]),
        "version": pet["version"],
    }


def ser_signature(s):
    return {
        "id": s["id"],
        "petition_id": s["petition_id"],
        "parcel_id": s["parcel_id"],
        "owner_id": s["owner_id"],
        "signed_at": iso(s["signed_at"]),
        "status": s["status"],
        "rejection_reason": s["rejection_reason"],
        "verified_by": s["verified_by"],
        "verified_at": iso(s["verified_at"]),
        "withdrawn_at": iso(s["withdrawn_at"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_estimate(e):
    return {
        "id": e["id"],
        "district_id": e["district_id"],
        "estimate_seq": e["estimate_seq"],
        "contract_price_cents": e["contract_price_cents"],
        "contingency_cents": e["contingency_cents"],
        "total_estimated_cost_cents": e["total_estimated_cost_cents"],
        "status": e["status"],
        "submitted_by": e["submitted_by"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_hearing(h):
    return {
        "id": h["id"],
        "district_id": h["district_id"],
        "hearing_date": iso(h["hearing_date"]),
        "venue": h["venue"],
        "status": h["status"],
        "objection_window_end": iso(h["objection_window_end"]),
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }


def ser_objection(o):
    return {
        "id": o["id"],
        "district_id": o["district_id"],
        "hearing_id": o["hearing_id"],
        "parcel_id": o["parcel_id"],
        "owner_id": o["owner_id"],
        "grounds": o["grounds"],
        "status": o["status"],
        "filed_at": iso(o["filed_at"]),
        "reviewed_by": o["reviewed_by"],
        "adjudicated_at": iso(o["adjudicated_at"]),
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_resolution(r):
    return {
        "id": r["id"],
        "district_id": r["district_id"],
        "motion": r["motion"],
        "votes_for": r["votes_for"],
        "votes_against": r["votes_against"],
        "outcome": r["outcome"],
        "protest_pct_snapshot": r["protest_pct_snapshot"],
        "required_votes_snapshot": r["required_votes_snapshot"],
        "recorded_by": r["recorded_by"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_assessment(a):
    return {
        "id": a["id"],
        "district_id": a["district_id"],
        "parcel_id": a["parcel_id"],
        "preliminary_amount_cents": a["preliminary_amount_cents"],
        "final_levy_cents": a["final_levy_cents"],
        "payment_option": a["payment_option"],
        "term_years": a["term_years"],
        "principal_balance_cents": a["principal_balance_cents"],
        "total_paid_cents": a["total_paid_cents"],
        "credit_balance_cents": a["credit_balance_cents"],
        "total_refunded_cents": a["total_refunded_cents"],
        "status": a["status"],
        "option_selected_at": iso(a["option_selected_at"]),
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_phase(p):
    return {
        "id": p["id"],
        "district_id": p["district_id"],
        "name": p["name"],
        "crew_name": p["crew_name"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "estimated_cost_cents": p["estimated_cost_cents"],
        "status": p["status"],
        "started_at": iso(p["started_at"]),
        "completed_at": iso(p["completed_at"]),
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_change_order(c):
    return {
        "id": c["id"],
        "district_id": c["district_id"],
        "phase_id": c["phase_id"],
        "description": c["description"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "proposed_by_user_id": c["proposed_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "district_id": inv["district_id"],
        "parcel_assessment_id": inv["parcel_assessment_id"],
        "kind": inv["kind"],
        "year_index": inv["year_index"],
        "issue_date": iso(inv["issue_date"]),
        "due_date": iso(inv["due_date"]),
        "principal_cents": inv["principal_cents"],
        "interest_cents": inv["interest_cents"],
        "penalty_cents": inv["penalty_cents"],
        "paid_cents": inv["paid_cents"],
        "status": inv["status"],
        "created_at": iso(inv["created_at"]),
        "updated_at": iso(inv["updated_at"]),
        "version": inv["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "parcel_assessment_id": p["parcel_assessment_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "received_at": iso(p["received_at"]),
        "applied_penalty_cents": p["applied_penalty_cents"],
        "applied_interest_cents": p["applied_interest_cents"],
        "applied_principal_cents": p["applied_principal_cents"],
        "created_at": iso(p["created_at"]),
    }
