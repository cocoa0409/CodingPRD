"""Entity serializers (stored datetimes -> ISO strings, lazy statuses)."""
import db
import services


def writer_view(w):
    return {
        "id": w["id"],
        "legal_name": w["legal_name"],
        "ipi_number": w["ipi_number"],
        "pro_affiliation": w["pro_affiliation"],
        "status": w["status"],
        "payable_balance_cents": w["payable_balance_cents"],
        "advance_outstanding_cents": w["advance_outstanding_cents"],
        "lifetime_earned_cents": w["lifetime_earned_cents"],
        "created_at": db.iso(w["created_at"]),
        "updated_at": db.iso(w["updated_at"]),
        "version": w["version"],
    }


def work_view(w):
    return {
        "id": w["id"],
        "title": w["title"],
        "alternate_titles": list(w["alternate_titles"]),
        "parent_work_id": w["parent_work_id"],
        "work_code": w["work_code"],
        "iswc": w["iswc"],
        "grant_date": db.iso(w["grant_date"]),
        "registration_status": w["registration_status"],
        "copyright_status": w["copyright_status"],
        "total_collected_cents": w["total_collected_cents"],
        "total_distributed_cents": w["total_distributed_cents"],
        "created_at": db.iso(w["created_at"]),
        "updated_at": db.iso(w["updated_at"]),
        "version": w["version"],
    }


def society_view(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "code": s["code"],
        "society_type": s["society_type"],
        "territory_code": s["territory_code"],
        "created_at": db.iso(s["created_at"]),
        "updated_at": db.iso(s["updated_at"]),
        "version": s["version"],
    }


def registration_view(r):
    return {
        "id": r["id"],
        "work_id": r["work_id"],
        "society_id": r["society_id"],
        "status": r["status"],
        "society_work_number": r["society_work_number"],
        "rejection_reason": r["rejection_reason"],
        "submitted_at": db.iso(r["submitted_at"]),
        "registered_at": db.iso(r["registered_at"]),
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def split_set_view(ss):
    return {
        "id": ss["id"],
        "work_id": ss["work_id"],
        "revision_index": ss["revision_index"],
        "status": ss["status"],
        "writer_pool_total_bp": ss["writer_pool_total_bp"],
        "publisher_pool_total_bp": ss["publisher_pool_total_bp"],
        "dispute_reason": ss["dispute_reason"],
        "created_at": db.iso(ss["created_at"]),
        "updated_at": db.iso(ss["updated_at"]),
        "version": ss["version"],
    }


def split_line_view(sl):
    return {
        "id": sl["id"],
        "split_set_id": sl["split_set_id"],
        "participant_type": sl["participant_type"],
        "writer_id": sl["writer_id"],
        "publisher_name": sl["publisher_name"],
        "share_bp": sl["share_bp"],
        "confirmation_status": sl["confirmation_status"],
        "rejection_reason": sl["rejection_reason"],
        "confirmed_at": db.iso(sl["confirmed_at"]),
        "created_at": db.iso(sl["created_at"]),
        "updated_at": db.iso(sl["updated_at"]),
        "version": sl["version"],
    }


def sub_publisher_view(sp):
    return {
        "id": sp["id"],
        "name": sp["name"],
        "home_territory_code": sp["home_territory_code"],
        "status": sp["status"],
        "created_at": db.iso(sp["created_at"]),
        "updated_at": db.iso(sp["updated_at"]),
        "version": sp["version"],
    }


def agreement_view(ag):
    return {
        "id": ag["id"],
        "sub_publisher_id": ag["sub_publisher_id"],
        "territory_codes": list(ag["territory_codes"]),
        "income_types": list(ag["income_types"]),
        "retention_bp": ag["retention_bp"],
        "effective_from": db.iso(ag["effective_from"]),
        "effective_to": db.iso(ag["effective_to"]),
        "status": services.agreement_status(ag),
        "created_at": db.iso(ag["created_at"]),
        "updated_at": db.iso(ag["updated_at"]),
        "version": ag["version"],
    }


def licensee_view(lc):
    return {
        "id": lc["id"],
        "name": lc["name"],
        "licensee_type": lc["licensee_type"],
        "created_at": db.iso(lc["created_at"]),
        "updated_at": db.iso(lc["updated_at"]),
        "version": lc["version"],
    }


def statement_view(st):
    return {
        "id": st["id"],
        "source_type": st["source_type"],
        "source_id": st["source_id"],
        "income_type": st["income_type"],
        "territory_code": st["territory_code"],
        "period_start": db.iso(st["period_start"]),
        "period_end": db.iso(st["period_end"]),
        "gross_amount_cents": st["gross_amount_cents"],
        "amends_statement_id": st["amends_statement_id"],
        "status": st["status"],
        "retained_cents": st["retained_cents"],
        "suspense_cents": st["suspense_cents"],
        "allocated_total_cents": st["allocated_total_cents"],
        "created_at": db.iso(st["created_at"]),
        "updated_at": db.iso(st["updated_at"]),
        "version": st["version"],
    }


def statement_line_view(l):
    return {
        "id": l["id"],
        "statement_id": l["statement_id"],
        "line_number": l["line_number"],
        "reported_title": l["reported_title"],
        "reported_iswc": l["reported_iswc"],
        "reported_work_code": l["reported_work_code"],
        "gross_cents": l["gross_cents"],
        "work_id": l["work_id"],
        "match_status": l["match_status"],
        "created_at": db.iso(l["created_at"]),
        "updated_at": db.iso(l["updated_at"]),
        "version": l["version"],
    }


def allocation_line_view(al):
    return {
        "id": al["id"],
        "statement_line_id": al["statement_line_id"],
        "split_line_id": al["split_line_id"],
        "statement_id": al["statement_id"],
        "writer_id": al["writer_id"],
        "participant_type": al["participant_type"],
        "provisional_amount_cents": al["provisional_amount_cents"],
        "final_amount_cents": al["final_amount_cents"],
        "advance_applied_cents": al["advance_applied_cents"],
        "net_payable_cents": al["net_payable_cents"],
        "status": al["status"],
        "created_at": db.iso(al["created_at"]),
        "updated_at": db.iso(al["updated_at"]),
        "version": al["version"],
    }


def advance_view(a):
    return {
        "id": a["id"],
        "writer_id": a["writer_id"],
        "agreement_ref": a["agreement_ref"],
        "amount_cents": a["amount_cents"],
        "recoup_rate_bp": a["recoup_rate_bp"],
        "status": a["status"],
        "recouped_cents": a["recouped_cents"],
        "outstanding_cents": a["outstanding_cents"],
        "paid_at": db.iso(a["paid_at"]),
        "created_at": db.iso(a["created_at"]),
        "updated_at": db.iso(a["updated_at"]),
        "version": a["version"],
    }


def distribution_run_view(r):
    return {
        "id": r["id"],
        "period_label": r["period_label"],
        "status": r["status"],
        "calculated_by_user_id": r["calculated_by_user_id"],
        "approved_by_user_id": r["approved_by_user_id"],
        "writer_payouts": [dict(p) for p in r["writer_payouts"]],
        "included_statement_ids": list(r["included_statement_ids"]),
        "total_payable_cents": r["total_payable_cents"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def audit_view(a):
    return {
        "id": a["id"],
        "licensee_id": a["licensee_id"],
        "period_start": db.iso(a["period_start"]),
        "period_end": db.iso(a["period_end"]),
        "valuation_method": a["valuation_method"],
        "status": a["status"],
        "actual_shortfall_cents": a["actual_shortfall_cents"],
        "sampled_base_cents": a["sampled_base_cents"],
        "reported_base_cents": a["reported_base_cents"],
        "claim_amount_cents": a["claim_amount_cents"],
        "settlement_cents": a["settlement_cents"],
        "created_at": db.iso(a["created_at"]),
        "updated_at": db.iso(a["updated_at"]),
        "version": a["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "work_id": c["work_id"],
        "statute_basis": c["statute_basis"],
        "intended_effective_date": db.iso(c["intended_effective_date"]),
        "window_open_date": db.iso(c["window_open_date"]),
        "window_close_date": db.iso(c["window_close_date"]),
        "notice_earliest_date": db.iso(c["notice_earliest_date"]),
        "notice_latest_date": db.iso(c["notice_latest_date"]),
        "notice_ref": c["notice_ref"],
        "notice_filed_at": db.iso(c["notice_filed_at"]),
        "status": services.claim_status(c),
        "created_at": db.iso(c["created_at"]),
        "updated_at": db.iso(c["updated_at"]),
        "version": c["version"],
    }
