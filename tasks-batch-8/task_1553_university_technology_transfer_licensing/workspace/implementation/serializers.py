"""Entity serializers — one per resource, using scaffold field names."""
from util import fmt_dt


def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_department(d):
    out = {
        "id": d["id"],
        "name": d["name"],
        "college_name": d["college_name"],
        "distribution_pool_cents": d["distribution_pool_cents"],
    }
    out.update(_common(d))
    return out


def ser_inventor(i):
    out = {
        "id": i["id"],
        "full_name": i["full_name"],
        "email": i["email"],
        "department_id": i["department_id"],
        "appointment_type": i["appointment_type"],
    }
    out.update(_common(i))
    return out


def ser_disclosure(d):
    out = {
        "id": d["id"],
        "title": d["title"],
        "description": d["description"],
        "funding_source": d["funding_source"],
        "federal_agency": d["federal_agency"],
        "grant_number": d["grant_number"],
        "public_disclosure_date": fmt_dt(d["public_disclosure_date"]),
        "submitter_inventor_id": d["submitter_inventor_id"],
        "status": d["status"],
        "patentability_rating": d["patentability_rating"],
        "market_rating": d["market_rating"],
        "unreimbursed_cost_cents": d["unreimbursed_cost_cents"],
        "written_off_cost_cents": d["written_off_cost_cents"],
        "cost_writeoff_review_required": d["cost_writeoff_review_required"],
    }
    out.update(_common(d))
    return out


def ser_entry(e):
    out = {
        "id": e["id"],
        "disclosure_id": e["disclosure_id"],
        "inventor_id": e["inventor_id"],
        "share_bp": e["share_bp"],
        "confirmation_status": e["confirmation_status"],
        "confirmed_at": fmt_dt(e["confirmed_at"]),
    }
    out.update(_common(e))
    return out


def ser_dispute(d):
    out = {
        "id": d["id"],
        "disclosure_id": d["disclosure_id"],
        "entry_id": d["entry_id"],
        "raised_by_inventor_id": d["raised_by_inventor_id"],
        "reason": d["reason"],
        "status": d["status"],
        "resolution_notes": d["resolution_notes"],
    }
    out.update(_common(d))
    return out


def ser_application(a):
    out = {
        "id": a["id"],
        "disclosure_id": a["disclosure_id"],
        "docket_number": a["docket_number"],
        "application_type": a["application_type"],
        "filed_date": fmt_dt(a["filed_date"]),
        "status": a["status"],
        "total_cost_cents": a["total_cost_cents"],
        "unreimbursed_cost_cents": a["unreimbursed_cost_cents"],
    }
    out.update(_common(a))
    return out


def ser_cost(c):
    out = {
        "id": c["id"],
        "patent_application_id": c["patent_application_id"],
        "cost_type": c["cost_type"],
        "amount_cents": c["amount_cents"],
        "incurred_date": fmt_dt(c["incurred_date"]),
        "reimbursed_amount_cents": c["reimbursed_amount_cents"],
        "reimbursement_status": c["reimbursement_status"],
    }
    out.update(_common(c))
    return out


def ser_startup(s):
    out = {
        "id": s["id"],
        "disclosure_id": s["disclosure_id"],
        "name": s["name"],
        "founded_date": fmt_dt(s["founded_date"]),
        "equity_model": s["equity_model"],
        "university_equity_bp": s["university_equity_bp"],
        "equity_issued": s["equity_issued"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_coi_plan(p):
    out = {
        "id": p["id"],
        "startup_id": p["startup_id"],
        "inventor_id": p["inventor_id"],
        "coverage_start": fmt_dt(p["coverage_start"]),
        "coverage_end": fmt_dt(p["coverage_end"]),
        "management_plan_text": p["management_plan_text"],
        "rejection_reason": p["rejection_reason"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_license(l):
    out = {
        "id": l["id"],
        "disclosure_id": l["disclosure_id"],
        "startup_id": l["startup_id"],
        "licensee_name": l["licensee_name"],
        "exclusivity": l["exclusivity"],
        "effective_date": fmt_dt(l["effective_date"]),
        "expiration_date": fmt_dt(l["expiration_date"]),
        "royalty_rate_bp": l["royalty_rate_bp"],
        "minimum_annual_royalty_cents": l["minimum_annual_royalty_cents"],
        "upfront_fee_cents": l["upfront_fee_cents"],
        "status": l["status"],
        "default_notice_date": fmt_dt(l["default_notice_date"]),
        "cure_deadline": fmt_dt(l["cure_deadline"]),
        "cumulative_sales_cents": l["cumulative_sales_cents"],
        "cumulative_royalty_cents": l["cumulative_royalty_cents"],
    }
    out.update(_common(l))
    return out


def ser_milestone(m):
    out = {
        "id": m["id"],
        "license_id": m["license_id"],
        "description": m["description"],
        "due_date": fmt_dt(m["due_date"]),
        "amount_cents": m["amount_cents"],
        "waiver_reason": m["waiver_reason"],
        "status": m["status"],
    }
    out.update(_common(m))
    return out


def ser_report(r):
    out = {
        "id": r["id"],
        "license_id": r["license_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "reported_sales_cents": r["reported_sales_cents"],
        "earned_royalty_cents": r["earned_royalty_cents"],
        "true_up_cents": r["true_up_cents"],
        "accepted_royalty_cents": r["accepted_royalty_cents"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_distribution(d):
    out = {
        "id": d["id"],
        "royalty_report_id": d["royalty_report_id"],
        "gross_cents": d["gross_cents"],
        "cost_offset_cents": d["cost_offset_cents"],
        "net_cents": d["net_cents"],
        "admin_fee_cents": d["admin_fee_cents"],
        "inventor_pool_cents": d["inventor_pool_cents"],
        "department_pool_cents": d["department_pool_cents"],
        "university_pool_cents": d["university_pool_cents"],
        "inventor_shares": d["inventor_shares"],
        "department_shares": d["department_shares"],
        "cost_applications": d["cost_applications"],
        "prepared_by_user_id": d["prepared_by_user_id"],
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def ser_compliance_report(r):
    out = {
        "id": r["id"],
        "disclosure_id": r["disclosure_id"],
        "report_type": r["report_type"],
        "due_date": fmt_dt(r["due_date"]),
        "prepared_by_user_id": r["prepared_by_user_id"],
        "certified_by_user_id": r["certified_by_user_id"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "late_flag": r["late_flag"],
        "rejection_reason": r["rejection_reason"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out
