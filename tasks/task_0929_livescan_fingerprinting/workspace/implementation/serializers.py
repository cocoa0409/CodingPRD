"""Resource projections.  Every datetime leaves through render_instant and every
date through render_date -- one rendering path, no exceptions."""

import derive
from store import db
from timeutil import render_date, render_instant


def _common(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "updated_at": render_instant(row["updated_at"]),
        "version": row["version"],
    }


def agency(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "account_code": row["account_code"],
            "billing_status": row["billing_status"],
            "payer_regime_default": row["payer_regime_default"],
            "invoice_terms_days": row["invoice_terms_days"],
            "outstanding_balance_cents": row["outstanding_balance_cents"],
            "max_aging_days": row["max_aging_days"],
            "mtd_billed_cents": row["mtd_billed_cents"],
            "suspended_at": render_instant(row["suspended_at"]),
        }
    )
    return out


def ori(row):
    out = _common(row)
    out.update(
        {
            "agency_id": row["agency_id"],
            "ori_code": row["ori_code"],
            "statutory_authority": row["statutory_authority"],
            "destination_requirement": row["destination_requirement"],
            "dissemination_tier": row["dissemination_tier"],
            "retention_permitted": row["retention_permitted"],
            "rapback_authority": row["rapback_authority"],
            "authority_status": row["authority_status"],
            "fee_waiver_eligible": row["fee_waiver_eligible"],
            "tcn_consumed_count": row["tcn_consumed_count"],
            "tcn_released_count": row["tcn_released_count"],
        }
    )
    return out


def service_type(row):
    out = _common(row)
    out.update(
        {
            "ori_id": row["ori_id"],
            "code": row["code"],
            "applicant_type": row["applicant_type"],
            "slot_duration_minutes": row["slot_duration_minutes"],
            "required_document_codes": list(row["required_document_codes"]),
            "accepted_id_document_types": list(row["accepted_id_document_types"]),
            "state_fee_cents": row["state_fee_cents"],
            "federal_fee_cents": row["federal_fee_cents"],
            "retention_offered": row["retention_offered"],
            "status": row["status"],
        }
    )
    return out


def site(row):
    out = _common(row)
    out.update(
        {
            "site_kind": row["site_kind"],
            "name": row["name"],
            "concurrent_capacity": row["concurrent_capacity"],
            "walkin_usable_capacity": row["walkin_usable_capacity"],
            "host_agency_id": row["host_agency_id"],
            "event_window_start": render_instant(row["event_window_start"]),
            "event_window_end": render_instant(row["event_window_end"]),
            "min_billable_prints": row["min_billable_prints"],
            "billable_print_count": row["billable_print_count"],
            "reconciliation_status": row["reconciliation_status"],
            "shortfall_charge_cents": row["shortfall_charge_cents"],
        }
    )
    return out


def device(row):
    out = _common(row)
    out.update(
        {
            "serial_number": row["serial_number"],
            "home_site_id": row["home_site_id"],
            "last_calibrated_at": render_instant(row["last_calibrated_at"]),
            "calibration_expires_at": render_instant(row["calibration_expires_at"]),
            "calibration_status": derive.device_status(row),
            "capture_count": row["capture_count"],
            "tainted_card_count": row["tainted_card_count"],
        }
    )
    return out


def device_assignment(row):
    out = _common(row)
    out.update(
        {
            "device_id": row["device_id"],
            "site_id": row["site_id"],
            "window_start": render_instant(row["window_start"]),
            "window_end": render_instant(row["window_end"]),
            "status": derive.assignment_status(row),
            "calibration_expires_at_snapshot": render_instant(
                row["calibration_expires_at_snapshot"]
            ),
            "billable_print_count": row["billable_print_count"],
            "tainted_print_count": row["tainted_print_count"],
        }
    )
    return out


def applicant(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "date_of_birth": render_date(row["date_of_birth"]),
            "sex": row["sex"],
            "place_of_birth": row["place_of_birth"],
            "id_document_type": row["id_document_type"],
            "id_document_expires_on": render_date(row["id_document_expires_on"]),
            "demographics_complete": row["demographics_complete"],
        }
    )
    return out


def appointment(row):
    out = _common(row)
    out.update(
        {
            "applicant_id": row["applicant_id"],
            "site_id": row["site_id"],
            "service_type_id": row["service_type_id"],
            "booking_channel": row["booking_channel"],
            "scheduled_start": render_instant(row["scheduled_start"]),
            "scheduled_end": render_instant(row["scheduled_end"]),
            "status": row["status"],
            "reschedule_count": row["reschedule_count"],
            "presented_document_type": row["presented_document_type"],
            "presented_documents": (
                list(row["presented_documents"]) if row["presented_documents"] is not None else None
            ),
            "checked_in_at": render_instant(row["checked_in_at"]),
            "no_show_fee_assessed": row["no_show_fee_assessed"],
        }
    )
    return out


def card(row):
    out = _common(row)
    out.update(
        {
            "appointment_id": row["appointment_id"],
            "device_id": row["device_id"],
            "site_id": row["site_id"],
            "captured_by_user_id": row["captured_by_user_id"],
            "status": row["status"],
            "positions_passed_count": row["positions_passed_count"],
            "positions_exception_count": row["positions_exception_count"],
            "mean_quality_score": float(row["mean_quality_score"]),
            "worst_position_score": row["worst_position_score"],
            "submittable": row["submittable"],
            "exception_override_by_user_id": row["exception_override_by_user_id"],
            "superseded_by_card_id": row["superseded_by_card_id"],
            "reprint_of_submission_id": row["reprint_of_submission_id"],
            "free_reprint_granted": row["free_reprint_granted"],
            "taint_reason": row["taint_reason"],
            "first_capture_at": render_instant(row["first_capture_at"]),
            "last_capture_at": render_instant(row["last_capture_at"]),
        }
    )
    return out


def position(row):
    out = _common(row)
    out.update(
        {
            "card_id": row["card_id"],
            "position_code": row["position_code"],
            "attempt_count": row["attempt_count"],
            "best_score": row["best_score"],
            "status": row["status"],
            "exception_code": row["exception_code"],
            "closed_at": render_instant(row["closed_at"]),
        }
    )
    return out


def submission(row):
    out = _common(row)
    out.update(
        {
            "card_id": row["card_id"],
            "ori_id": row["ori_id"],
            "original_submission_id": row["original_submission_id"],
            "reprint_sequence": row["reprint_sequence"],
            "transmitted_at": render_instant(row["transmitted_at"]),
            "destinations": list(row["destinations"]),
            "state_status": row["state_status"],
            "fbi_status": row["fbi_status"],
            "composite_disposition": derive.composite_disposition(row),
            "retention_requested": row["retention_requested"],
            "retention_status": row["retention_status"],
            "tcn_root": row["tcn_root"],
            "tcn_suffix": row["tcn_suffix"],
            "tcn_full": row["tcn_full"],
            "state_resulted_at": render_instant(row["state_resulted_at"]),
            "fbi_resulted_at": render_instant(row["fbi_resulted_at"]),
            "reprint_count": row["reprint_count"],
            "free_reprint_count": row["free_reprint_count"],
            "purge_requested_at": render_instant(row["purge_requested_at"]),
            "purge_requested_by_user_id": row["purge_requested_by_user_id"],
            "purge_decided_by_user_id": row["purge_decided_by_user_id"],
        }
    )
    return out


def chr_response(row):
    out = _common(row)
    out.update(
        {
            "submission_id": row["submission_id"],
            "destination": row["destination"],
            "record_count": row["record_count"],
            "disqualifying_offense_count": row["disqualifying_offense_count"],
            "record_detail": row["record_detail"],
            "fitness_code": row["fitness_code"],
            "routing_status": row["routing_status"],
            "routed_at": render_instant(row["routed_at"]),
            "routed_recipient_roles": (
                list(row["routed_recipient_roles"])
                if row["routed_recipient_roles"] is not None
                else None
            ),
        }
    )
    return out


def determination(row):
    out = _common(row)
    out.update(
        {
            "submission_id": row["submission_id"],
            "ori_id": row["ori_id"],
            "basis_response_id": row["basis_response_id"],
            "outcome": row["outcome"],
            "issued_by_user_id": row["issued_by_user_id"],
            "resolved_by_user_id": row["resolved_by_user_id"],
            "status": row["status"],
            "challenge_count": row["challenge_count"],
            "challenge_filed_at": render_instant(row["challenge_filed_at"]),
            "issued_at": render_instant(row["issued_at"]),
        }
    )
    return out


def subscription(row):
    out = _common(row)
    out.update(
        {
            "submission_id": row["submission_id"],
            "ori_id": row["ori_id"],
            "term_start": render_instant(row["term_start"]),
            "term_end": render_instant(row["term_end"]),
            "status": derive.subscription_status(row),
            "renewal_count": row["renewal_count"],
            "notifications_received_count": row["notifications_received_count"],
            "notifications_routed_count": row["notifications_routed_count"],
            "notifications_voided_count": row["notifications_voided_count"],
        }
    )
    return out


def notification(row):
    out = _common(row)
    out.update(
        {
            "subscription_id": row["subscription_id"],
            "ori_code": row["ori_code"],
            "subject_submission_tcn": row["subject_submission_tcn"],
            "event_type": row["event_type"],
            "event_date": render_date(row["event_date"]),
            "status": row["status"],
            "acknowledged_by_user_id": row["acknowledged_by_user_id"],
        }
    )
    return out


def assessment(row):
    out = _common(row)
    out.update(
        {
            "agency_id": row["agency_id"],
            "submission_id": row["submission_id"],
            "appointment_id": row["appointment_id"],
            "invoice_id": row["invoice_id"],
            "assessment_kind": row["assessment_kind"],
            "payer_regime": row["payer_regime"],
            "state_fee_cents": row["state_fee_cents"],
            "federal_fee_cents": row["federal_fee_cents"],
            "processing_surcharge_cents": row["processing_surcharge_cents"],
            "vendor_convenience_fee_cents": row["vendor_convenience_fee_cents"],
            "vendor_tax_cents": row["vendor_tax_cents"],
            "trip_surcharge_cents": row["trip_surcharge_cents"],
            "reprint_fee_cents": row["reprint_fee_cents"],
            "waived_cents": row["waived_cents"],
            "discount_cents": row["discount_cents"],
            "total_cents": row["total_cents"],
            "paid_cents": row["paid_cents"],
            "credited_cents": row["credited_cents"],
            "status": row["status"],
        }
    )
    return out


def invoice(row):
    out = _common(row)
    out.update(
        {
            "agency_id": row["agency_id"],
            "period_key": row["period_key"],
            "issued_on": render_date(row["issued_on"]),
            "due_on": render_date(row["due_on"]),
            "subtotal_cents": row["subtotal_cents"],
            "late_fee_cents": row["late_fee_cents"],
            "total_cents": row["total_cents"],
            "paid_cents": row["paid_cents"],
            "aging_days": derive.invoice_aging_days(row),
            "status": row["status"],
        }
    )
    return out


def project_chr_response(row, role, include_detail):
    """PRD 3.6 -- the per-role, per-tier projection of the single-response read.

    Friction point 3 is resolved the other way for the submission-scoped listing,
    which returns the stored rows unprojected; this function is only used by
    GET /livescan/chr-responses/{id}.
    """
    out = chr_response(row)
    submission_row = db.submissions[row["submission_id"]]
    tier = db.oris[submission_row["ori_id"]]["dissemination_tier"]

    if role == "AgencyAdjudicator" and tier == "FULL_CHR":
        if not include_detail:
            out["record_detail"] = None
    elif role == "AgencyAdjudicator":
        out["record_count"] = None
        out["disqualifying_offense_count"] = None
        out["record_detail"] = None
    elif role == "Applicant":
        out["record_count"] = None
        out["disqualifying_offense_count"] = None
        out["record_detail"] = None
    elif role == "VendorAdmin":
        out["fitness_code"] = None
        out["record_count"] = None
        out["disqualifying_offense_count"] = None
        out["record_detail"] = None

    if row["routing_status"] == "VOIDED":
        out["record_detail"] = None
        out["record_count"] = 0
    return out
