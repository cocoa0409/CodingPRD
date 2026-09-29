"""Public representations.  Derived mirrors are recomputed on read where PRD 2.10
says so; stored mirrors are echoed as held."""

import conduct
from store import db, date_str, elapsed_days, iso, now


def _common(rec):
    """PRD 2.4: id, created_at, and (for all but TripCondition) updated_at + version."""
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------

def competency_confirmed(applicant_id):
    """PRD 2.10: true once any referral reached COMPLETED with a score >= 80."""
    for r in db.referrals.values():
        if r["applicant_id"] != applicant_id:
            continue
        if r["status"] == "COMPLETED" and (r["fixed_route_competency_score"] or 0) >= 80:
            return True
    return False


APPEAL_OPEN_STATUSES = ("FILED", "REVIEWER_ASSIGNED", "HEARING_SCHEDULED", "HEARD")


def continued_service_during_appeal(applicant_id):
    """PRD 2.10: true while one of the rider's appeals sits in an open status."""
    for appeal in db.appeals.values():
        det = db.determinations.get(appeal["determination_id"])
        if det is None or det["applicant_id"] != applicant_id:
            continue
        if appeal["status"] in APPEAL_OPEN_STATUSES:
            return True
    return False


def applicant(rec):
    block = conduct.compute_conduct(rec["id"])
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "date_of_birth": date_str(rec["date_of_birth"]),
            "residence_zone": rec["residence_zone"],
            "mobility_aid": rec["mobility_aid"],
            "primary_language": rec["primary_language"],
            "home_agency_name": rec["home_agency_name"],
            "current_eligibility_status": rec["current_eligibility_status"],
            "eligibility_category": rec["eligibility_category"],
            "active_determination_id": rec["active_determination_id"],
            "service_status": conduct.service_status(rec["id"]),
            "no_show_points_event_basis": block["no_show_points_event_basis"],
            "no_show_points_report_basis": block["no_show_points_report_basis"],
            "chargeable_miss_count_90d": block["chargeable_miss_count_90d"],
            "scheduled_trip_count_90d": block["scheduled_trip_count_90d"],
            "no_show_ratio_pct": float(block["no_show_ratio_pct"]),
            "prior_upheld_suspension_count": conduct.prior_upheld_count(rec["id"]),
            "suspension_days_ledger_total": conduct.ledger_total(rec["id"]),
            "fixed_route_competency_confirmed": competency_confirmed(rec["id"]),
            "continued_service_during_appeal": continued_service_during_appeal(rec["id"]),
        }
    )
    return out


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def pending_days(rec):
    """PRD 3.2: statutory is zero whenever completeness_established_at is null;
    both figures are frozen at issuance."""
    frozen = rec.get("_frozen_pending")
    if frozen is not None:
        return frozen[0], frozen[1]
    established = rec["completeness_established_at"]
    statutory = 0 if established is None else elapsed_days(established, now())
    if statutory < 0:
        statutory = 0
    net = statutory - rec["verification_excluded_days"] - rec["applicant_delay_days"]
    if net < 0:
        net = 0
    return statutory, net


def application(rec):
    statutory, net = pending_days(rec)
    out = _common(rec)
    out.update(
        {
            "applicant_id": rec["applicant_id"],
            "application_type": rec["application_type"],
            "status": rec["status"],
            "functional_answers": rec["functional_answers"],
            "claimed_conditions": list(rec["claimed_conditions"]),
            "submitted_at": iso(rec["submitted_at"]),
            "completeness_established_at": iso(rec["completeness_established_at"]),
            "missing_items": list(rec["missing_items"]),
            "resubmission_count": rec["resubmission_count"],
            "verification_excluded_days": rec["verification_excluded_days"],
            "applicant_delay_days": rec["applicant_delay_days"],
            "days_pending_statutory": statutory,
            "days_pending_net_agency": net,
            "determination_due_date": date_str(rec["determination_due_date"]),
            "presumptive_granted_at": iso(rec["presumptive_granted_at"]),
            "attests_permanent": rec["attests_permanent"],
        }
    )
    return out


def verification(rec):
    out = _common(rec)
    out.update(
        {
            "application_id": rec["application_id"],
            "provider_name": rec["provider_name"],
            "provider_type": rec["provider_type"],
            "provider_license_number": rec["provider_license_number"],
            "status": rec["status"],
            "requested_at": iso(rec["requested_at"]),
            "received_at": iso(rec["received_at"]),
            "attests_conditions": rec["attests_conditions"],
            "attests_permanent": rec["attests_permanent"],
            "insufficiency_reason": rec["insufficiency_reason"],
            "wait_days": rec["wait_days"],
        }
    )
    return out


def slot(rec):
    out = _common(rec)
    out.update(
        {
            "site_name": rec["site_name"],
            "site_is_wheelchair_accessible": rec["site_is_wheelchair_accessible"],
            "evaluator_user_id": rec["evaluator_user_id"],
            "starts_at": iso(rec["starts_at"]),
            "ends_at": iso(rec["ends_at"]),
            "capacity": rec["capacity"],
            "booked_count": rec["booked_count"],
            "status": rec["status"],
        }
    )
    return out


def assessment(rec):
    out = _common(rec)
    out.update(
        {
            "application_id": rec["application_id"],
            "slot_id": rec["slot_id"],
            "rescheduled_from_assessment_id": rec["rescheduled_from_assessment_id"],
            "requires_wheelchair_position": rec["requires_wheelchair_position"],
            "attendance_status": rec["attendance_status"],
            "scoring_status": rec["scoring_status"],
            "board_alight_score": rec["board_alight_score"],
            "wayfinding_score": rec["wayfinding_score"],
            "distance_meters_walked": rec["distance_meters_walked"],
            "heat_sensitivity_flag": rec["heat_sensitivity_flag"],
            "evaluator_notes": rec["evaluator_notes"],
            "recommended_category": rec["recommended_category"],
            "recommended_term_days": rec["recommended_term_days"],
            "scored_by_user_id": rec["scored_by_user_id"],
            "signed_off_by_user_id": rec["signed_off_by_user_id"],
            "attendance_recorded_at": iso(rec["attendance_recorded_at"]),
        }
    )
    return out


def vehicle(rec):
    out = _common(rec)
    out.update(
        {
            "vehicle_number": rec["vehicle_number"],
            "wheelchair_positions": rec["wheelchair_positions"],
            "ambulatory_seats": rec["ambulatory_seats"],
            "open_wheelchair_reservations": rec["open_wheelchair_reservations"],
            "open_ambulatory_reservations": rec["open_ambulatory_reservations"],
            "status": rec["status"],
        }
    )
    return out


def booking(rec):
    out = _common(rec)
    out.update(
        {
            "assessment_id": rec["assessment_id"],
            "vehicle_id": rec["vehicle_id"],
            "pickup_window_start": iso(rec["pickup_window_start"]),
            "pickup_window_end": iso(rec["pickup_window_end"]),
            "requires_wheelchair_position": rec["requires_wheelchair_position"],
            "status": rec["status"],
            "cancelled_reason": rec["cancelled_reason"],
        }
    )
    return out


def determination(rec):
    out = _common(rec)
    out.update(
        {
            "application_id": rec["application_id"],
            "applicant_id": rec["applicant_id"],
            "category": rec["category"],
            "status": rec["status"],
            "effective_date": date_str(rec["effective_date"]),
            "term_days": rec["term_days"],
            "expires_at": date_str(rec["expires_at"]),
            "rationale": rec["rationale"],
            "determined_by_user_id": rec["determined_by_user_id"],
            "issued_at": iso(rec["issued_at"]),
            "under_appeal": rec["under_appeal"],
            "origin": rec["origin"],
            "trip_condition_count": rec["trip_condition_count"],
            "fixed_route_competency_confirmed": rec["fixed_route_competency_confirmed"],
        }
    )
    return out


def trip_condition(rec):
    """PRD 2.4: immutable — only id and created_at; no updated_at, no version."""
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "determination_id": rec["determination_id"],
        "condition_type": rec["condition_type"],
        "comparator": rec["comparator"],
        "threshold_value": rec["threshold_value"],
        "note": rec["note"],
    }


def appeal(rec):
    out = _common(rec)
    out.update(
        {
            "determination_id": rec["determination_id"],
            "grounds": rec["grounds"],
            "request_hearing": rec["request_hearing"],
            "filed_at": iso(rec["filed_at"]),
            "filing_deadline_date": date_str(rec["filing_deadline_date"]),
            "status": rec["status"],
            "reviewer_user_id": rec["reviewer_user_id"],
            "hearing_at": iso(rec["hearing_at"]),
            "heard_at": iso(rec["heard_at"]),
            "decision_due_date": date_str(rec["decision_due_date"]),
            "outcome": rec["outcome"],
            "granted_category": rec["granted_category"],
            "decided_at": iso(rec["decided_at"]),
            "decision_note": rec["decision_note"],
            "continued_service_extended": rec["continued_service_extended"],
        }
    )
    return out


def trip_event(rec):
    out = _common(rec)
    out.update(
        {
            "applicant_id": rec["applicant_id"],
            "trip_date": date_str(rec["trip_date"]),
            "event_type": rec["event_type"],
            "recorded_at": iso(rec["recorded_at"]),
            "excused": rec["excused"],
            "excuse_reason": rec["excuse_reason"],
            "points_assessed": rec["points_assessed"],
        }
    )
    return out


def proceeding(rec):
    served = conduct.days_served_now(rec)
    forgiven = rec["duration_days"] - served
    out = _common(rec)
    out.update(
        {
            "applicant_id": rec["applicant_id"],
            "status": rec["status"],
            "origin": rec["origin"],
            "proposed_by_user_id": rec["proposed_by_user_id"],
            "grounds_note": rec["grounds_note"],
            "review_window_end_date": date_str(rec["review_window_end_date"]),
            "points_at_proposal": rec["points_at_proposal"],
            "notice_sent_at": iso(rec["notice_sent_at"]),
            "response_deadline_date": date_str(rec["response_deadline_date"]),
            "rider_response_at": iso(rec["rider_response_at"]),
            "rider_response_note": rec["rider_response_note"],
            "decided_by_user_id": rec["decided_by_user_id"],
            "decision": rec["decision"],
            "duration_days": rec["duration_days"],
            "suspension_start_date": date_str(rec["suspension_start_date"]),
            "suspension_end_date": date_str(rec["suspension_end_date"]),
            "days_served": served,
            "days_forgiven": forgiven,
        }
    )
    return out


def referral(rec):
    out = _common(rec)
    out.update(
        {
            "applicant_id": rec["applicant_id"],
            "determination_id": rec["determination_id"],
            "referral_reason": rec["referral_reason"],
            "status": rec["status"],
            "referral_response_deadline_date": date_str(rec["referral_response_deadline_date"]),
            "fixed_route_competency_score": rec["fixed_route_competency_score"],
            "completed_at": iso(rec["completed_at"]),
            "withdrawal_reason": rec["withdrawal_reason"],
        }
    )
    return out


def visitor_record(rec):
    out = _common(rec)
    out.update(
        {
            "applicant_id": rec["applicant_id"],
            "home_agency_name": rec["home_agency_name"],
            "home_agency_certification_provided": rec["home_agency_certification_provided"],
            "visit_start_date": date_str(rec["visit_start_date"]),
            "service_dates": [date_str(d) for d in rec["service_dates"]],
            "days_used_365": rec["days_used_365"],
            "days_remaining_365": rec["days_remaining_365"],
            "status": rec["status"],
        }
    )
    return out
