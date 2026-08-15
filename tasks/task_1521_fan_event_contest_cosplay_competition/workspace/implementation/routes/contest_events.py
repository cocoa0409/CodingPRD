"""ContestEvent routes."""

from flask import Blueprint

from db import DB, new_id, now_ts
from errors import err_not_found, err_invalid_state, err_validation
from middleware import require_roles
from response import success
from services.calculations import tax_summary
from services.cascades import contest_cancel_cascade
from services.helpers import body_json, req_str, req_int, req_iso, req_enum
from services.serializers import contest_view, category_view, judge_view, paginate

bp = Blueprint("contest_events", __name__)

READ_ROLES = ("ContestLead", "Treasurer", "StageManager", "Judge", "SafetyOfficer", "Contestant")

# Allowed transitions of the ContestEvent machine (directed edges).
CONTEST_TRANSITIONS = {
    "SETUP": {"REGISTRATION_OPEN", "CANCELLED"},
    "REGISTRATION_OPEN": {"REGISTRATION_CLOSED", "CANCELLED"},
    "REGISTRATION_CLOSED": {"JUDGING", "CANCELLED"},
    "JUDGING": {"TABULATION"},
    "TABULATION": {"COMPLETED"},
}


@bp.route("/contest-events", methods=["POST"])
def create_contest():
    user_id, _ = require_roles("ContestLead")
    body = body_json()
    name = req_str(body, "name")
    start_at = req_iso(body, "start_at")
    end_at = req_iso(body, "end_at")
    prize_budget_cents = req_int(body, "prize_budget_cents", minimum=0)
    max_entries = body.get("max_entries_per_contestant", 2)
    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
        raise err_validation("max_entries_per_contestant must be an integer >= 1")

    from db import parse_iso
    if parse_iso(end_at) <= parse_iso(start_at):
        raise err_validation("end_at must be strictly after start_at")

    ts = now_ts()
    contest = {
        "id": new_id(),
        "name": name,
        "start_at": start_at,
        "end_at": end_at,
        "prize_budget_cents": prize_budget_cents,
        "max_entries_per_contestant": max_entries,
        "status": "SETUP",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.contest_events[contest["id"]] = contest
    return success(contest_view(contest), status=201)


@bp.route("/contest-events/<cid>", methods=["GET"])
def get_contest(cid):
    require_roles(*READ_ROLES)
    contest = DB.contest_events.get(cid)
    if contest is None:
        raise err_not_found("ContestEvent not found")
    return success(contest_view(contest))


@bp.route("/contest-events/<cid>/transition", methods=["POST"])
def transition_contest(cid):
    require_roles("ContestLead")
    body = body_json()
    to = req_enum(body, "to", {
        "SETUP", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "JUDGING",
        "TABULATION", "COMPLETED", "CANCELLED",
    })
    contest = DB.contest_events.get(cid)
    if contest is None:
        raise err_not_found("ContestEvent not found")

    allowed = CONTEST_TRANSITIONS.get(contest["status"], set())
    if to not in allowed:
        raise err_invalid_state(
            f"Cannot transition contest from {contest['status']} to {to}"
        )

    if contest["status"] == "SETUP" and to == "REGISTRATION_OPEN":
        has_category = any(c["contest_id"] == cid for c in DB.categories.values())
        if not has_category:
            raise err_invalid_state("At least one Category must exist to open registration")

    if contest["status"] == "JUDGING" and to == "TABULATION":
        all_tabulated = all(
            c["status"] == "TABULATED"
            for c in DB.categories.values()
            if c["contest_id"] == cid
        )
        if not all_tabulated:
            raise err_invalid_state("All categories must be TABULATED before TABULATION")

    ts = now_ts()
    # Cascades first (each cascaded child bumps its own version/timestamp).
    if to == "REGISTRATION_OPEN":
        for cat in DB.categories.values():
            if cat["contest_id"] == cid and cat["status"] == "DRAFT":
                cat["status"] = "OPEN"
                cat["updated_at"] = ts
                cat["version"] += 1
    elif to == "JUDGING":
        for cat in DB.categories.values():
            if cat["contest_id"] == cid and cat["status"] == "OPEN":
                cat["status"] = "SCORING"
                cat["updated_at"] = ts
                cat["version"] += 1
    elif to == "CANCELLED":
        contest_cancel_cascade(contest)

    contest["status"] = to
    contest["updated_at"] = ts
    contest["version"] += 1
    return success(contest_view(contest))


@bp.route("/contest-events/<cid>/tax-summary", methods=["GET"])
def get_tax_summary(cid):
    require_roles("Treasurer", "ContestLead")
    contest = DB.contest_events.get(cid)
    if contest is None:
        raise err_not_found("ContestEvent not found")
    return success(tax_summary(cid))


@bp.route("/contest-events/<cid>/categories", methods=["GET"])
def list_contest_categories(cid):
    from flask import request
    require_roles(*READ_ROLES)
    contest = DB.contest_events.get(cid)
    if contest is None:
        raise err_not_found("ContestEvent not found")
    items = [c for c in DB.categories.values() if c["contest_id"] == cid]
    items.sort(key=lambda c: c["created_at"])
    page, pag = paginate([category_view(c) for c in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/contest-events/<cid>/judges", methods=["GET"])
def list_contest_judges(cid):
    from flask import request
    require_roles("ContestLead", "Judge")
    contest = DB.contest_events.get(cid)
    if contest is None:
        raise err_not_found("ContestEvent not found")
    items = [j for j in DB.judges.values() if j["contest_id"] == cid]
    items.sort(key=lambda j: j["created_at"])
    page, pag = paginate([judge_view(j) for j in items], request.args)
    return success(page, response_type="array", pagination=pag)
