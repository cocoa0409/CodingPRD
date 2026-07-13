"""Serialize raw records into their public JSON representation."""
import store
import calc


def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = rec["created_at"]
    if "version" in rec:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def s_incident(r):
    out = {
        "name": r["name"],
        "incident_type": r["incident_type"],
        "ics_incident_number": r["ics_incident_number"],
        "operational_period_hours": r["operational_period_hours"],
        "status": r["status"],
        "total_approved_reimbursement_cents": r["total_approved_reimbursement_cents"],
    }
    roll = calc.incident_rollups(r["id"])
    out["active_task_count"] = roll["active_task_count"]
    out["total_logged_hours"] = roll["total_logged_hours"]
    out["total_mileage_miles"] = roll["total_mileage_miles"]
    return _common(r, out)


def s_task(r):
    out = {
        "incident_id": r["incident_id"],
        "task_number": r["task_number"],
        "task_type": r["task_type"],
        "priority": r["priority"],
        "segment_area_sqkm": r["segment_area_sqkm"],
        "planned_searcher_hours": r["planned_searcher_hours"],
        "required_cert_types": r["required_cert_types"],
        "max_responders": r["max_responders"],
        "planned_start": r["planned_start"],
        "planned_end": r["planned_end"],
        "status": r["status"],
        "estimated_coverage_pct": r["estimated_coverage_pct"],
        "actual_coverage_pct": r["actual_coverage_pct"],
    }
    return _common(r, out)


def s_team(r):
    return _common(r, {
        "name": r["name"],
        "team_type": r["team_type"],
        "base_location": r["base_location"],
        "status": r["status"],
    })


def s_member(r):
    return _common(r, {
        "team_id": r["team_id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "member_role": r["member_role"],
        "status": r["status"],
    })


def s_certification(r):
    return _common(r, {
        "member_id": r["member_id"],
        "cert_type": r["cert_type"],
        "issued_date": r["issued_date"],
        "expires_date": r["expires_date"],
        "status": calc.cert_status(r),
    })


def s_callout(r):
    return _common(r, {
        "task_id": r["task_id"],
        "member_id": r["member_id"],
        "status": r["status"],
        "requested_at": r["requested_at"],
        "deployed_at": r["deployed_at"],
    })


def s_resource(r):
    return _common(r, {
        "name": r["name"],
        "resource_type": r["resource_type"],
        "handler_member_id": r["handler_member_id"],
        "status": calc.resource_status(r),
        "out_of_service": r["out_of_service"],
        "active_assignment_count": r["active_assignment_count"],
    })


def s_resource_assignment(r):
    return _common(r, {
        "resource_id": r["resource_id"],
        "task_id": r["task_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
    })


def s_ground_track(r):
    # Append-only: only id + created_at (no updated_at / version).
    return {
        "id": r["id"],
        "task_id": r["task_id"],
        "member_id": r["member_id"],
        "recorded_at": r["recorded_at"],
        "distance_km": r["distance_km"],
        "duration_min": r["duration_min"],
        "coverage_area_sqkm": r["coverage_area_sqkm"],
        "created_at": r["created_at"],
    }


def s_clue(r):
    return _common(r, {
        "incident_id": r["incident_id"],
        "task_id": r["task_id"],
        "clue_number": r["clue_number"],
        "clue_priority": r["clue_priority"],
        "description": r["description"],
        "found_at": r["found_at"],
        "status": r["status"],
    })


def s_claim(r):
    return _common(r, {
        "member_id": r["member_id"],
        "incident_id": r["incident_id"],
        "declared_mileage_miles": r["declared_mileage_miles"],
        "meal_count": r["meal_count"],
        "lodging_nights": r["lodging_nights"],
        "status": r["status"],
        "estimated_amount_cents": r["estimated_amount_cents"],
        "final_amount_cents": r["final_amount_cents"],
    })


def s_aar(r):
    return _common(r, {
        "incident_id": r["incident_id"],
        "summary": r["summary"],
        "lessons_learned": r["lessons_learned"],
        "status": r["status"],
    })


_DISPATCH = {
    "Incident": s_incident,
    "Task": s_task,
    "Team": s_team,
    "Member": s_member,
    "Certification": s_certification,
    "Callout": s_callout,
    "Resource": s_resource,
    "ResourceAssignment": s_resource_assignment,
    "GroundTrack": s_ground_track,
    "Clue": s_clue,
    "ReimbursementClaim": s_claim,
    "AfterActionReport": s_aar,
}


def serialize(rec):
    return _DISPATCH[rec["_type"]](rec)
