"""Entity -> JSON.  Every instant goes through core.clock.render (the ONE
renderer); plain calendar dates are echoed verbatim as YYYY-MM-DD strings."""

from core import db
from core.clock import render
from services import derive, pricing, tat


def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": render(rec["created_at"])}
    if with_version and "version" in rec:
        out["updated_at"] = render(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def clinic(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "address_zone": rec["address_zone"],
            "status": rec["status"],
            "billing_hold_status": rec["billing_hold_status"],
            "business_open_minute": rec["business_open_minute"],
            "business_close_minute": rec["business_close_minute"],
            "business_days": list(rec["business_days"]),
        }
    )
    return out


def contract(rec):
    out = _common(rec)
    consumed = derive.contract_consumed(rec)
    out.update(
        {
            "clinic_id": rec["clinic_id"],
            "kind": rec["kind"],
            "block_purchased_studies": rec["block_purchased_studies"],
            "block_consumed_studies": consumed,
            "block_remaining_studies": rec["block_purchased_studies"] - consumed,
            "valid_from": render(rec["valid_from"]),
            "valid_until": render(rec["valid_until"]),
            "suspended": rec["suspended"],
            "status": derive.contract_status(rec),
        }
    )
    return out


def mobile_unit(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "service_status": rec["service_status"],
            "max_stops": rec["max_stops"],
            "max_shift_minutes": rec["max_shift_minutes"],
        }
    )
    return out


def equipment(rec):
    out = _common(rec)
    out.update(
        {
            "assigned_unit_id": rec["assigned_unit_id"],
            "modality": rec["modality"],
            "serial_label": rec["serial_label"],
            "calibration_valid_from": render(rec["calibration_valid_from"]),
            "calibration_valid_until": render(rec["calibration_valid_until"]),
            "calibration_status": derive.calibration_status(rec),
            "usage_count_since_qc": rec["usage_count_since_qc"],
            "last_passing_qc_at": render(rec["last_passing_qc_at"]),
            "quarantined_at": render(rec["quarantined_at"]),
        }
    )
    return out


def technician(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "certified_modalities": list(rec["certified_modalities"]),
            "status": rec["status"],
        }
    )
    return out


def specialist(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "modality_privileges": list(rec["modality_privileges"]),
            "species_privileges": list(rec["species_privileges"]),
            "stat_eligible": rec["stat_eligible"],
            "status": rec["status"],
            "open_read_count": derive.specialist_open_read_count(rec),
            "workload_score": derive.specialist_workload_score(rec),
        }
    )
    return out


def route(rec):
    out = _common(rec)
    out.update(
        {
            "mobile_unit_id": rec["mobile_unit_id"],
            "technician_id": rec["technician_id"],
            "service_date": rec["service_date"],
            "shift_start_minute": rec["shift_start_minute"],
            "shift_end_minute": rec["shift_end_minute"],
            "status": rec["status"],
            "stop_count": derive.route_stop_count(rec),
            "planned_occupied_minutes": derive.route_planned_occupied_minutes(rec),
            "actual_occupied_minutes": derive.route_actual_occupied_minutes(rec),
            "slack_minutes": derive.route_slack_minutes(rec),
            "published_at": render(rec["published_at"]),
            "dispatched_at": render(rec["dispatched_at"]),
            "completed_at": render(rec["completed_at"]),
        }
    )
    return out


def route_stop(rec):
    out = _common(rec)
    out.update(
        {
            "route_id": rec["route_id"],
            "clinic_id": rec["clinic_id"],
            "bumped_by_stop_id": rec["bumped_by_stop_id"],
            "sequence": derive.stop_sequence(rec),
            "planned_arrival_minute": rec["planned_arrival_minute"],
            "service_minutes": rec["service_minutes"],
            "drive_minutes_from_prev": rec["drive_minutes_from_prev"],
            "stop_priority": rec["stop_priority"],
            "status": rec["status"],
            "trip_fee_cents": rec["trip_fee_cents"],
            "arrived_at": render(rec["arrived_at"]),
            "departed_at": render(rec["departed_at"]),
            "actual_service_minutes": derive.stop_actual_service_minutes(rec),
            "cancel_reason": rec["cancel_reason"],
        }
    )
    return out


def referral(rec):
    out = _common(rec)
    out.update(
        {
            "clinic_id": rec["clinic_id"],
            "patient_name": rec["patient_name"],
            "species": rec["species"],
            "study_kind": rec["study_kind"],
            "requested_modality": rec["requested_modality"],
            "priority": rec["priority"],
            "clinical_history": rec["clinical_history"],
            "status": rec["status"],
            "return_reason": rec["return_reason"],
            "reject_reason": rec["reject_reason"],
        }
    )
    return out


def appointment(rec):
    out = _common(rec)
    out.update(
        {
            "referral_id": rec["referral_id"],
            "route_stop_id": rec["route_stop_id"],
            "status": rec["status"],
            "cancel_reason": rec["cancel_reason"],
            "cancelled_at": render(rec["cancelled_at"]),
        }
    )
    out.update(derive.appointment_counts(rec))
    return out


# workflow states whose pricing block is pinned at null/0 by PRD prose:
#  * ORDERED          — "A newly ordered study has ... price_basis null, and
#                        every money field at 0." (PRD 3.5)
#  * CANCELLED /
#    NOT_PERFORMED    — "a cancelled study is priced solely by
#                        cancellation_fee_cents" (PRD 3.9 step 6)
_UNPRICED_WORKFLOW = ("ORDERED", "CANCELLED", "NOT_PERFORMED")


def study(rec):
    tat.evaluate(rec)
    out = _common(rec)
    out.update(
        {
            "appointment_id": rec["appointment_id"],
            "equipment_id": rec["equipment_id"],
            "technician_id": rec["technician_id"],
            "repeat_of_study_id": rec["repeat_of_study_id"],
            "study_kind": rec["study_kind"],
            "species": rec["species"],
            "modality": rec["modality"],
            "body_region": rec["body_region"],
            "priority": rec["priority"],
            "priority_source": rec["priority_source"],
            "workflow_status": rec["workflow_status"],
            "qc_status": rec["qc_status"],
            "tat_status": rec["tat_status"],
            "billing_status": rec["billing_status"],
            "image_count": rec["image_count"],
            "acquired_at": render(rec["acquired_at"]),
            "escalated_at": render(rec["escalated_at"]),
            "pause_started_at": render(rec["pause_started_at"]),
            "hold_reason": rec["hold_reason"],
            "repeat_cause": rec["repeat_cause"],
            "repeat_count": rec["repeat_count"],
            "read_attempt_count": rec["read_attempt_count"],
            "cancellation_fee_cents": rec["cancellation_fee_cents"],
            "cancel_reason": rec["cancel_reason"],
            "tat_anchor_at": render(tat.anchor_at(rec)),
            "tat_target_minutes": tat.target_minutes(rec),
            "tat_deadline_at": render(tat.deadline_at(rec)),
            "tat_elapsed_minutes": tat.elapsed_minutes(rec),
            "tat_paused_minutes": tat.paused_minutes(rec),
            "tat_accrued_minutes": tat.accrued_minutes(rec),
        }
    )
    if rec["workflow_status"] in _UNPRICED_WORKFLOW:
        out.update(
            {
                "price_basis": None,
                "base_price_cents": 0,
                "trip_share_cents": 0,
                "stat_surcharge_cents": 0,
                "admin_fee_cents": 0,
                "total_price_cents": 0,
            }
        )
    else:
        parts = pricing.decomposition(rec)
        out.update(
            {
                "price_basis": parts["price_basis"],
                "base_price_cents": parts["base_price_cents"],
                "trip_share_cents": parts["trip_share_cents"],
                "stat_surcharge_cents": parts["stat_surcharge_cents"],
                "admin_fee_cents": parts["admin_fee_cents"],
                "total_price_cents": parts["total_price_cents"],
            }
        )
    return out


def read_assignment(rec):
    out = _common(rec)
    out.update(
        {
            "study_id": rec["study_id"],
            "specialist_id": rec["specialist_id"],
            "attempt_number": rec["attempt_number"],
            "status": rec["status"],
            "offered_at": render(rec["offered_at"]),
            "responded_at": render(rec["responded_at"]),
            "decline_reason": rec["decline_reason"],
        }
    )
    return out


def report(rec):
    out = _common(rec)
    out.update(
        {
            "study_id": rec["study_id"],
            "author_specialist_id": rec["author_specialist_id"],
            "supersedes_report_id": rec["supersedes_report_id"],
            "kind": rec["kind"],
            "report_version": rec["report_version"],
            "status": rec["status"],
            "findings": rec["findings"],
            "published_at": render(rec["published_at"]),
            "retracted_at": render(rec["retracted_at"]),
            "retract_reason": rec["retract_reason"],
        }
    )
    return out


def qc_check(rec):
    out = _common(rec, with_version=False)
    out.update(
        {
            "equipment_id": rec["equipment_id"],
            "performed_by_technician_id": rec["performed_by_technician_id"],
            "result": rec["result"],
            "note": rec["note"],
            "performed_at": render(rec["performed_at"]),
            "affected_study_count": rec["affected_study_count"],
        }
    )
    return out


def peer_review(rec):
    out = _common(rec)
    out.update(
        {
            "report_id": rec["report_id"],
            "reviewer_specialist_id": rec["reviewer_specialist_id"],
            "status": rec["status"],
            "score": rec["score"],
            "outcome_note": rec["outcome_note"],
        }
    )
    return out


def invoice(rec):
    out = _common(rec)
    out.update(
        {
            "clinic_id": rec["clinic_id"],
            "period_start": rec["period_start"],
            "period_end": rec["period_end"],
            "status": rec["status"],
            "total_cents": derive.invoice_total_cents(rec),
            "finalized_total_cents": rec["finalized_total_cents"],
            "finalized_at": render(rec["finalized_at"]),
            "posted_study_count": derive.invoice_posted_study_count(rec),
        }
    )
    return out


def charge_line(rec):
    out = _common(rec)
    out.update(
        {
            "invoice_id": rec["invoice_id"],
            "study_id": rec["study_id"],
            "kind": rec["kind"],
            "amount_cents": rec["amount_cents"],
            "status": rec["status"],
            "reversal_reason": rec["reversal_reason"],
        }
    )
    return out


def block_ledger_entry(rec):
    out = _common(rec, with_version=False)
    out.update(
        {
            "contract_id": rec["contract_id"],
            "study_id": rec["study_id"],
            "delta_studies": rec["delta_studies"],
            "balance_after_studies": rec["balance_after_studies"],
            "reason": rec["reason"],
        }
    )
    return out


def notification(rec):
    out = _common(rec, with_version=False)
    out.update(
        {
            "clinic_id": rec["clinic_id"],
            "study_id": rec["study_id"],
            "kind": rec["kind"],
            "message": rec["message"],
        }
    )
    return out


SERIALIZERS = {
    "clinics": clinic,
    "contracts": contract,
    "mobile_units": mobile_unit,
    "equipment": equipment,
    "technicians": technician,
    "specialists": specialist,
    "routes": route,
    "route_stops": route_stop,
    "referrals": referral,
    "appointments": appointment,
    "studies": study,
    "read_assignments": read_assignment,
    "reports": report,
    "qc_checks": qc_check,
    "peer_reviews": peer_review,
    "invoices": invoice,
    "charge_lines": charge_line,
    "block_ledger_entries": block_ledger_entry,
    "notifications": notification,
}


def paged(collection, rows, limit, offset):
    rows = db.sort_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    fn = SERIALIZERS[collection]
    return [fn(r) for r in page], total
