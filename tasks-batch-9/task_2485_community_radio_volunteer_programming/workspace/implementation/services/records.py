"""Row constructors shared between routes and the daily sweep."""

from db import db, new_row


def create_incident_row(
    category,
    severity,
    program_id,
    episode_id,
    underwriting_spot_id,
    respondent_volunteer_id,
    complainant_note,
    occurred_at,
    sanction,
    status,
    safe_harbor,
    points,
    adjudicated_by_user_id=None,
):
    return new_row(db.incidents, {
        "category": category,
        "severity": severity,
        "program_id": program_id,
        "episode_id": episode_id,
        "underwriting_spot_id": underwriting_spot_id,
        "respondent_volunteer_id": respondent_volunteer_id,
        "complainant_note": complainant_note,
        "occurred_at": occurred_at,
        "status": status,
        "safe_harbor_violation": safe_harbor,
        "penalty_points": points,
        "sanction": sanction,
        "adjudicated_by_user_id": adjudicated_by_user_id,
        "remediation_note": None,
    })
