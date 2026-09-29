"""League transaction report endpoints (PRD Section 3.8)."""
from flask import Blueprint

import auth
import common
import config
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("reports", __name__)

TRANSITIONS = {
    "FILE": ("PENDING",),
    "LEAGUE_ACCEPT": ("FILED",),
    "LEAGUE_REJECT": ("FILED",),
    "REFILE": ("REJECTED_BY_LEAGUE",),
}


@bp.post("/transaction-reports/<report_id>/disposition")
def dispose_report(report_id):
    user_id, role = auth.require(config.ROLE_COMPLIANCE)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), role, config.REPORT_ACTION_ROLES)
    report = common.need("reports", report_id)

    # Segregation of duties (check 6) precedes the state check (check 11).
    if raw.get("action") == "FILE" and user_id == report["initiated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    body = validate.json_body()
    action = auth.require_action(body, config.REPORT_ACTION_ROLES)
    league_note = validate.str_field(body, "league_note", required=False,
                                    default=None, allow_blank=True)

    if report["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "A report in status %s does not accept %s."
                       % (report["status"], action))

    if action == "FILE":
        assignment = store.assignments.get(report["assignment_id"])
        if assignment is not None and assignment["status"] == "REVOKED":
            raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                           "The producing assignment has been revoked.")

    if action == "REFILE" and report["refile_count"] >= config.MAX_REPORT_REFILES:
        raise ApiError("ERR_CYCLE_LIMIT_REACHED")

    store.touch(report)
    if action == "FILE":
        report["status"] = "FILED"
        report["certified_by_user_id"] = user_id
        report["filed_at"] = store.now_iso()
    elif action == "LEAGUE_ACCEPT":
        report["status"] = "ACCEPTED"
    elif action == "LEAGUE_REJECT":
        report["status"] = "REJECTED_BY_LEAGUE"
        report["league_note"] = league_note
    elif action == "REFILE":
        report["status"] = "PENDING"
        report["refile_count"] = report["refile_count"] + 1
        report["certified_by_user_id"] = None
        report["filed_at"] = None

    common.commit()
    return envelope.object_response(serialize.report(report))
