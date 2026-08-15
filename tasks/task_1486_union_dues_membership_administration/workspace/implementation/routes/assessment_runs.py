"""Monthly assessment runs: create PROVISIONALs for the period and finalize
stale PROVISIONALs of earlier periods at gross wages 0."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles
from response import ok
from services import dues as dues_svc
from services import ledger as ledger_svc

bp = Blueprint("assessment_runs", __name__, url_prefix="/api/assessment-runs")


@bp.route("", methods=["POST"])
@require_roles("SecretaryTreasurer")
def create_assessment_run(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    local_id = utils.require_field(body, "local_id")
    period = utils.require_field(body, "period")
    local = db.store.locals.get(local_id)
    if local is None:
        raise errors.local_not_found_body()
    if local["status"] != "ACTIVE":
        raise errors.local_not_active()
    utils.parse_period(period)
    if utils.period_key(period) > utils.period_key(db.current_period()):
        raise errors.invalid_period()
    for r in db.store.assessment_runs.values():
        if r["local_id"] == local_id and r["period"] == period:
            raise errors.assessment_run_exists()

    affected_members = set()
    created_count = 0
    finalized_count = 0

    local_members = [m for m in db.store.members.values()
                     if m["local_id"] == local_id]
    member_ids = {m["id"] for m in local_members}

    # Finalize stale PROVISIONALs (periods < run period) at gross wages 0.
    stale = [a for a in db.store.assessments.values()
             if a["member_id"] in member_ids
             and a["status"] == "PROVISIONAL" and a["period"] < period]
    stale.sort(key=lambda a: (a["period"], a["_seq"]))
    for a in stale:
        dues_svc.finalize_assessment(a, 0)
        finalized_count += 1
        affected_members.add(a["member_id"])

    # Create a PROVISIONAL per member in {ACTIVE, DELINQUENT, SUSPENDED} with
    # no existing assessment for the period (member_id + period is unique).
    local_members.sort(key=lambda m: m["_seq"])
    for member in local_members:
        if member["status"] not in ("ACTIVE", "DELINQUENT", "SUSPENDED"):
            continue
        if any(a["member_id"] == member["id"] and a["period"] == period
               for a in db.store.assessments.values()):
            continue
        gross = dues_svc.provisional_wage_base(member["id"], period)
        assessment = dues_svc.create_assessment(member, period, gross,
                                                "PROVISIONAL")
        ledger_svc.post_entry(
            member["id"], "ASSESSMENT_CHARGE", assessment["assessed_cents"],
            period, memo="assessment run %s" % period,
            assessment_id=assessment["id"])
        created_count += 1
        affected_members.add(member["id"])

    for mid in affected_members:
        db.touch(db.store.members[mid])

    run = {
        "id": utils.new_id(),
        "local_id": local_id,
        "period": period,
        "assessments_created_count": created_count,
        "assessments_finalized_count": finalized_count,
        "created_at": db.fmt_ts(db.now()),
        "_seq": db.store.next_seq(),
    }
    db.store.assessment_runs[run["id"]] = run
    return ok(serializers.assessment_run(run), 201)
