"""Election lifecycle: list/get, open-nominations, freeze-eligibility
(snapshot ElectionEligibility per electorate member), conclude, eligibility
listing."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, ALL_ROLES
from response import ok, ok_list
from services import rebate as rebate_svc

bp = Blueprint("elections", __name__, url_prefix="/api/elections")


def get_election_or_404(election_id):
    e = db.store.elections.get(election_id)
    if e is None:
        raise errors.election_not_found()
    return e


@bp.route("", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_elections(user_id, role):
    rows = list(db.store.elections.values())
    local_id = request.args.get("local_id")
    status = request.args.get("status")
    if local_id is not None:
        rows = [e for e in rows if e["local_id"] == local_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: e["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.election(e) for e in page], meta)


@bp.route("/<election_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_election(user_id, role, election_id):
    return ok(serializers.election(get_election_or_404(election_id)), 200)


@bp.route("/<election_id>/open-nominations", methods=["POST"])
@require_roles("LocalAdmin")
def open_nominations(user_id, role, election_id):
    e = get_election_or_404(election_id)
    if e["status"] != "SCHEDULED":
        raise errors.election_state_forbidden()
    if db.now() < utils.parse_datetime(e["nomination_open_at"]):
        raise errors.election_state_forbidden()
    e["status"] = "NOMINATION_OPEN"
    db.touch(e)
    return ok(serializers.election(e), 200)


@bp.route("/<election_id>/freeze-eligibility", methods=["POST"])
@require_roles("LocalAdmin")
def freeze_eligibility(user_id, role, election_id):
    e = get_election_or_404(election_id)
    if e["status"] != "NOMINATION_OPEN":
        raise errors.election_state_forbidden()
    if db.now() < utils.parse_datetime(e["nomination_close_at"]):
        raise errors.election_state_forbidden()
    electorate = [m for m in db.store.members.values()
                  if m["local_id"] == e["local_id"]
                  and m["status"] in ("ACTIVE", "DELINQUENT")]
    electorate.sort(key=lambda m: m["_seq"])
    ts = db.fmt_ts(db.now())
    for member in electorate:
        reasons, arrears = rebate_svc.evaluate_eligibility(member, e)
        snap = {
            "id": utils.new_id(),
            "election_id": e["id"],
            "member_id": member["id"],
            "eligible": len(reasons) == 0,
            "ineligibility_reasons": reasons,
            "arrears_at_freeze_cents": arrears,
            "last_suspension_ended_at": member.get("last_suspension_ended_at"),
            "created_at": ts,
            "_seq": db.store.next_seq(),
        }
        db.store.eligibilities[snap["id"]] = snap
    e["status"] = "ELIGIBILITY_FROZEN"
    db.touch(e)
    return ok(serializers.election(e), 200)


@bp.route("/<election_id>/conclude", methods=["POST"])
@require_roles("LocalAdmin")
def conclude(user_id, role, election_id):
    e = get_election_or_404(election_id)
    if e["status"] != "ELIGIBILITY_FROZEN":
        raise errors.election_state_forbidden()
    e["status"] = "CONCLUDED"
    db.touch(e)
    return ok(serializers.election(e), 200)


@bp.route("/<election_id>/eligibilities", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_eligibilities(user_id, role, election_id):
    get_election_or_404(election_id)
    rows = [s for s in db.store.eligibilities.values()
            if s["election_id"] == election_id]
    member_id = request.args.get("member_id")
    eligible = request.args.get("eligible")
    if member_id is not None:
        rows = [s for s in rows if s["member_id"] == member_id]
    if eligible is not None:
        want = eligible.strip().lower() == "true"
        rows = [s for s in rows if s["eligible"] == want]
    rows.sort(key=lambda s: s["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.eligibility(s) for s in page], meta)
