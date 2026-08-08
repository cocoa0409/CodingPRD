"""Resource serialisation.

System-generated datetimes go through render_datetime (3 fractional digits).
Input-supplied datetimes (survey window_start/window_end) are stored raw and
echoed verbatim.
"""

from clock import render_datetime


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": render_datetime(rec["created_at"]),
        "updated_at": render_datetime(rec["updated_at"]),
        "version": rec["version"],
    }


def pole_owner_json(rec):
    out = {
        "legal_name": rec["legal_name"],
        "owner_category": rec["owner_category"],
        "annual_rental_rate_cents": rec["annual_rental_rate_cents"],
        "make_ready_labor_rate_cents_per_hour": rec["make_ready_labor_rate_cents_per_hour"],
    }
    out.update(_common(rec))
    return out


def crew_json(rec):
    out = {
        "pole_owner_id": rec["pole_owner_id"],
        "crew_name": rec["crew_name"],
        "region": rec["region"],
    }
    out.update(_common(rec))
    return out


def pole_json(rec):
    out = {
        "pole_owner_id": rec["pole_owner_id"],
        "tag": rec["tag"],
        "height_ft": rec["height_ft"],
        "usable_communication_space_inches": rec["usable_communication_space_inches"],
        "occupied_space_inches": rec["occupied_space_inches"],
        "reserved_space_inches": rec["reserved_space_inches"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def attacher_json(rec):
    out = {
        "company_name": rec["company_name"],
        "cin": rec["cin"],
        "contact_email": rec["contact_email"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "account_balance_cents": rec["account_balance_cents"],
    }
    out.update(_common(rec))
    return out


def application_json(rec):
    out = {
        "pole_id": rec["pole_id"],
        "attacher_id": rec["attacher_id"],
        "requested_space_inches": rec["requested_space_inches"],
        "requested_position_inches": rec["requested_position_inches"],
        "purpose": rec["purpose"],
        "reserved_space_inches": rec["reserved_space_inches"],
        "submitted_at": render_datetime(rec["submitted_at"]),
        "surveyed_at": render_datetime(rec["surveyed_at"]),
        "estimate_issued_at": render_datetime(rec["estimate_issued_at"]),
        "estimate_expires_at": render_datetime(rec["estimate_expires_at"]),
        "estimate_accepted_at": render_datetime(rec["estimate_accepted_at"]),
        "survey_deadline": render_datetime(rec["survey_deadline"]),
        "estimate_deadline": render_datetime(rec["estimate_deadline"]),
        "permit_deadline": render_datetime(rec["permit_deadline"]),
        "make_ready_required": rec["make_ready_required"],
        "make_ready_fee_estimate_cents": rec["make_ready_fee_estimate_cents"],
        "make_ready_fee_final_cents": rec["make_ready_fee_final_cents"],
        "annual_rental_fee_cents": rec["annual_rental_fee_cents"],
        "surveyor_user_id": rec["surveyor_user_id"],
        "permit_officer_user_id": rec["permit_officer_user_id"],
        "permit_decision": rec["permit_decision"],
        "permit_issued_at": render_datetime(rec["permit_issued_at"]),
        "shot_clock_status": rec["shot_clock_status"],
        "make_ready_invoice_id": rec["make_ready_invoice_id"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def survey_json(rec):
    out = {
        "application_id": rec["application_id"],
        "crew_id": rec["crew_id"],
        "surveyor_user_id": rec["surveyor_user_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "estimated_labor_hours": rec["estimated_labor_hours"],
        "make_ready_required": rec["make_ready_required"],
        "existing_attacher_count": rec["existing_attacher_count"],
        "complexity_class": rec["complexity_class"],
        "findings": rec["findings"],
    }
    out.update(_common(rec))
    return out


def attachment_json(rec):
    out = {
        "pole_id": rec["pole_id"],
        "attacher_id": rec["attacher_id"],
        "application_id": rec["application_id"],
        "allotted_space_inches": rec["allotted_space_inches"],
        "position_inches": rec["position_inches"],
        "authorized": rec["authorized"],
        "transferred_from_attacher_id": rec["transferred_from_attacher_id"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def finding_json(rec):
    out = {
        "pole_id": rec["pole_id"],
        "attacher_id": rec["attacher_id"],
        "auditor_user_id": rec["auditor_user_id"],
        "audited_at": render_datetime(rec["audited_at"]),
        "discovered_space_inches": rec["discovered_space_inches"],
        "discovered_position_inches": rec["discovered_position_inches"],
        "good_faith": rec["good_faith"],
        "estimated_install_years_ago": rec["estimated_install_years_ago"],
        "penalty_cents": rec["penalty_cents"],
        "back_rental_cents": rec["back_rental_cents"],
        "penalty_invoice_id": rec["penalty_invoice_id"],
        "resulting_attachment_id": rec["resulting_attachment_id"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def invoice_json(rec):
    out = {
        "attacher_id": rec["attacher_id"],
        "pole_owner_id": rec["pole_owner_id"],
        "application_id": rec["application_id"],
        "finding_id": rec["finding_id"],
        "invoice_type": rec["invoice_type"],
        "amount_cents": rec["amount_cents"],
        "line_items": rec["line_items"],
        "issued_at": render_datetime(rec["issued_at"]),
        "due_at": render_datetime(rec["due_at"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def dispute_json(rec):
    out = {
        "attacher_id": rec["attacher_id"],
        "invoice_id": rec["invoice_id"],
        "finding_id": rec["finding_id"],
        "reason": rec["reason"],
        "round_count": rec["round_count"],
        "resolution": rec["resolution"],
        "adjusted_amount_cents": rec["adjusted_amount_cents"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out
