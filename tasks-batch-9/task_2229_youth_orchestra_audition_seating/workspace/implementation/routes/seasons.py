"""Season lifecycle, the offer-expiry sweep and the aid award run."""

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, acting, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import clock_now, db
from validate import Body, pagination

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = ("PLANNING", "AUDITIONS_OPEN", "PLACEMENT", "IN_SEASON", "CLOSED")
SUCCESSOR = {
    "PLANNING": "AUDITIONS_OPEN",
    "AUDITIONS_OPEN": "PLACEMENT",
    "PLACEMENT": "IN_SEASON",
    "IN_SEASON": "CLOSED",
    "CLOSED": None,
}


@bp.route("/seasons", methods=["POST"])
@endpoint("ArtisticDirector")
def create_season():
    body = Body()
    name = body.string("name", required=True, min_len=1, max_len=120)
    year_label = body.string("year_label", required=True, min_len=1, max_len=40)
    window_start = body.datetime("audition_window_start", required=True)
    window_end = body.datetime("audition_window_end", required=True)
    base_cents = body.integer("tuition_base_cents", required=True, minimum=1)
    due_at = body.datetime("tuition_due_at", required=True)
    budget = body.integer("aid_budget_cents", required=True, minimum=0)

    row = svc.new_row()
    row.update({
        "name": name,
        "year_label": year_label,
        "status": "PLANNING",
        "audition_window_start": window_start,
        "audition_window_end": window_end,
        "tuition_base_cents": base_cents,
        "tuition_due_at": due_at,
        "aid_budget_cents": budget,
        "aid_committed_cents": 0,
    })
    db.seasons[row["id"]] = row
    return ok(svc.season_json(row), 201)


@bp.route("/seasons", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_seasons():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.seasons.values())),
                             request.args, ["status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.season_json(r) for r in page], limit, offset, len(rows))


@bp.route("/seasons/<season_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_season(season_id):
    return ok(svc.season_json(svc.season_or_404(season_id)))


@bp.route("/seasons/<season_id>/advance-status", methods=["POST"])
@endpoint("ArtisticDirector")
def advance_status(season_id):
    season = svc.season_or_404(season_id)
    body = Body()
    to_status = body.enum("to_status", SEASON_STATUSES, required=True)

    if SUCCESSOR.get(season["status"]) != to_status:
        raise ApiError("ERR_INVALID_SEASON_TRANSITION",
                       "%s is not the successor of %s." % (to_status, season["status"]))

    if to_status == "CLOSED":
        for account in svc.accounts_of_season(season["id"]):
            if account["billing_status"] == "DELINQUENT":
                raise ApiError("ERR_DELINQUENT_ACCOUNT_BLOCKS_CLOSE",
                               "A delinquent tuition account blocks the close.")

    if to_status == "AUDITIONS_OPEN":
        ensembles = svc.ensembles_of_season(season["id"])
        if not ensembles:
            raise ApiError("ERR_SEASON_PRECONDITION_UNMET",
                           "The season owns no ensemble.")
        for ensemble in ensembles:
            if not svc.quotas_of_ensemble(ensemble["id"]):
                raise ApiError("ERR_SEASON_PRECONDITION_UNMET",
                               "Ensemble %s owns no section." % ensemble["id"])
    elif to_status == "PLACEMENT":
        for audition in db.auditions.values():
            if (audition["season_id"] == season["id"]
                    and audition["status"] in ("SCORED", "REVISION_REQUESTED")):
                raise ApiError("ERR_SEASON_PRECONDITION_UNMET",
                               "An audition is still open for adjudication.")
    elif to_status == "IN_SEASON":
        if svc.seated_ensemble_count(season) != svc.ensemble_count(season):
            raise ApiError("ERR_SEASON_PRECONDITION_UNMET",
                           "Not every ensemble of the season is seated.")

    season["status"] = to_status
    svc.touch(season)

    if to_status == "CLOSED":
        _close_cascade(season)
    return ok(svc.season_json(season))


def _close_cascade(season):
    closing_year = season["tuition_due_at"].year
    graduated = []
    graduated_ids = set()
    for ensemble in svc.ordered(svc.ensembles_of_season(season["id"])):
        if ensemble["roster_state"] not in ("FORMING", "SEATED"):
            continue
        seat_members = []
        for quota in svc.quotas_of_ensemble(ensemble["id"]):
            for seat in svc.active_seats_of_quota(quota["id"]):
                seat_members.append(seat["member_id"])
        ensemble["roster_state"] = "CLOSED"
        svc.touch(ensemble)
        for member_id in seat_members:
            member = db.members.get(member_id)
            if member is None or member["id"] in graduated_ids:
                continue
            if (member["enrollment_status"] == "ENROLLED"
                    and member["graduation_year"] == closing_year):
                member["enrollment_status"] = "GRADUATED"
                svc.touch(member)
                graduated.append(member)
                graduated_ids.add(member["id"])
    for member in graduated:
        if member["alumni_engagement_opt_in"]:
            member["enrollment_status"] = "ALUMNI"
            svc.touch(member)


@bp.route("/seasons/<season_id>/offer-expiry-sweep", methods=["POST"])
@endpoint("RegistrarStaff")
def offer_expiry_sweep(season_id):
    season = svc.season_or_404(season_id)
    now = clock_now()
    lapsed = []
    for placement in svc.ordered(list(db.placements.values())):
        if placement["status"] != "OFFERED":
            continue
        ensemble = db.ensembles.get(placement["ensemble_id"])
        if ensemble is None or ensemble["season_id"] != season["id"]:
            continue
        expires = placement["offer_expires_at"]
        if expires is not None and expires <= now:
            lapsed.append((placement, ensemble))

    freed = []
    for placement, ensemble in lapsed:
        placement["status"] = "EXPIRED"
        svc.touch(placement)
        svc.touch(ensemble)
        member = db.members[placement["member_id"]]
        key = (ensemble["id"], member["primary_instrument"])
        if key not in freed:
            freed.append(key)

    promoted = 0
    for ensemble_id, instrument in freed:
        promoted += svc.waitlist_promotion(db.ensembles[ensemble_id], instrument)
    return ok({"expired_count": len(lapsed), "promoted_count": promoted})


@bp.route("/seasons/<season_id>/aid-award-run", methods=["POST"])
@endpoint("FinanceOfficer")
def aid_award_run(season_id):
    season = svc.season_or_404(season_id)
    body = Body()
    expected = body.integer("expected_season_version", required=True)
    if expected != season["version"]:
        raise ApiError("ERR_STALE_SEASON_VERSION",
                       "The season has moved on since your last read.")

    user_id, _role = acting()
    queue = [a for a in svc.accounts_of_season(season["id"])
             if a["aid_status"] == "UNDER_REVIEW"]
    for account in queue:
        if account["aid_reviewed_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The reviewing officer may not fund the request.")

    queue = sorted(queue, key=lambda a: (-a["aid_need_score"], -a["assessed_cents"],
                                         a["created_at"], a["_seq"]))
    ceiling = calc.per_member_ceiling(season["aid_budget_cents"])
    remainder = season["aid_budget_cents"] - season["aid_committed_cents"]
    approved = 0
    denied = 0
    for account in queue:
        grant = min(account["aid_requested_cents"], ceiling, remainder)
        if grant >= calc.MIN_AWARD_CENTS:
            account["aid_awarded_cents"] = grant
            account["aid_effective_cents"] = grant
            account["aid_awarded_by_user_id"] = user_id
            account["aid_status"] = "APPROVED"
            remainder -= grant
            season["aid_committed_cents"] += grant
            approved += 1
            svc.recompute_balance(account)
            svc.touch(account)
            svc.apply_billing_status(account)
        else:
            account["aid_awarded_cents"] = 0
            account["aid_status"] = "DENIED"
            account["aid_denial_reason"] = ("INSUFFICIENT_BUDGET"
                                           if remainder < calc.MIN_AWARD_CENTS
                                           else "BELOW_MIN_AWARD")
            denied += 1
            svc.touch(account)

    svc.touch(season)
    return ok({
        "approved_count": approved,
        "denied_count": denied,
        "aid_committed_cents": season["aid_committed_cents"],
        "aid_available_cents": season["aid_budget_cents"] - season["aid_committed_cents"],
    })
