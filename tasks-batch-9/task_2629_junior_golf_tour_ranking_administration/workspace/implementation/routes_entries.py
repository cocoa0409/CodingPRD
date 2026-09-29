"""Entries and assistance applications."""
from datetime import timedelta

from flask import Blueprint

import calc
import listing
import services
import validate
from auth import guard, require_member_ownership
from envelope import object_response
from errors import ApiError
from routes_core import handicap_is_stale
from store import (
    db, bump, clock, clock_iso, dt_of, date_of, day_start, find, insert,
    new_row, public,
)

bp = Blueprint("entries", __name__)

TERMINAL_ENTRY_STATUSES = (
    "REJECTED",
    "WITHDRAWN",
    "FORFEITED",
    "DISQUALIFIED",
    "CANCELLED",
)
REENTRY_ALLOWED_STATUSES = ("WITHDRAWN", "REJECTED", "CANCELLED")


def _schedule_conflict(member, tournament):
    this_start = date_of(tournament["start_date"])
    this_end = date_of(tournament["end_date"])
    for entry in services.entries_of_member(member["id"]):
        if entry["tournament_id"] == tournament["id"]:
            continue
        if entry["entry_status"] not in ("ACCEPTED", "WAITLISTED", "COMPETING", "FINISHED"):
            continue
        other = services.tournament_of_entry(entry)
        if other is None:
            continue
        other_start = date_of(other["start_date"]) - timedelta(days=1)
        other_end = date_of(other["end_date"]) + timedelta(days=1)
        if this_start <= other_end and this_end >= other_start:
            return True
    return False


@bp.route("/entries", methods=["POST"])
def create_entry():
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    member_id = validate.req_id(body, "member_id")
    tournament_id = validate.req_id(body, "tournament_id")
    exemption_grant_id = validate.opt_id(body, "exemption_grant_id")
    request_assistance = validate.opt_bool(body, "request_assistance", False)
    aid_application_id = validate.opt_id(body, "aid_application_id")

    # existence, outermost referent first
    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")
    if aid_application_id is not None:
        find("aid_applications", aid_application_id, "ERR_AID_APPLICATION_NOT_FOUND")
    grant = None
    if exemption_grant_id is not None:
        grant = find("exemption_grants", exemption_grant_id, "ERR_GRANT_NOT_FOUND")

    # ownership
    require_member_ownership(caller, member["id"])

    # state gates
    if tournament["status"] != "ENTRY_OPEN":
        raise ApiError("ERR_INVALID_TOURNAMENT_STATE")

    # safety gates
    if member["eligibility_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED")
    if member["eligibility_status"] != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED")

    # business and referential constraints
    if member["age_division"] != tournament["division"]:
        raise ApiError("ERR_DIVISION_MISMATCH")
    if member["handicap_index"] > tournament["max_handicap_index"]:
        raise ApiError("ERR_HANDICAP_ABOVE_LIMIT")
    if handicap_is_stale(member):
        raise ApiError("ERR_HANDICAP_STALE")
    if member["handicap_source"] == "SELF_ATTESTED" and tournament["tier"] in (
        "NATIONAL",
        "INVITATIONAL",
    ):
        raise ApiError(
            "ERR_HANDICAP_STALE",
            "A self-attested index is not adequate for this tier",
        )
    if grant is not None:
        if grant["status"] != "ACTIVE":
            raise ApiError("ERR_EXEMPTION_NOT_APPLICABLE")
        if grant["member_id"] != member["id"] or grant["tournament_id"] != tournament["id"]:
            raise ApiError("ERR_EXEMPTION_NOT_APPLICABLE")
        expires = dt_of(grant["expires_at"])
        if expires is None or not (expires > clock()):
            grant["status"] = "EXPIRED"
            bump(grant)
            raise ApiError("ERR_EXEMPTION_NOT_APPLICABLE")
    application = None
    if request_assistance:
        approved = [
            a
            for a in db.aid_applications.values()
            if a["member_id"] == member["id"]
            and a["season_id"] == tournament["season_id"]
            and a["status"] == "APPROVED"
        ]
        if len(approved) != 1 or aid_application_id != approved[0]["id"]:
            raise ApiError("ERR_AID_NOT_APPROVED")
        application = approved[0]
    for existing in services.entries_of_tournament(tournament["id"]):
        if existing["member_id"] != member["id"]:
            continue
        if existing["entry_status"] not in REENTRY_ALLOWED_STATUSES:
            raise ApiError("ERR_DUPLICATE_ENTRY")

    # clock windows
    now = clock()
    if not (now >= dt_of(tournament["entry_open_at"]) and now < dt_of(tournament["entry_close_at"])):
        raise ApiError("ERR_ENTRY_WINDOW_CLOSED")

    # capacity and overlap
    if _schedule_conflict(member, tournament):
        raise ApiError("ERR_SCHEDULE_CONFLICT")

    # money: the pinned four-step fee settlement
    season = db.seasons.get(tournament["season_id"])
    gross_fee_cents = tournament["entry_fee_cents"]
    late_cutoff = dt_of(tournament["entry_close_at"]) - timedelta(
        hours=calc.ENTRY_LATE_WINDOW_HOURS
    )
    surcharge = calc.late_surcharge(gross_fee_cents, now > late_cutoff)
    award = 0
    if application is not None:
        award = calc.settlement_award(
            application["covered_pct"],
            gross_fee_cents,
            application["per_member_cap_cents"],
            application["consumed_cents"],
        )
        if award <= 0:
            raise ApiError("ERR_AID_ALLOCATION_EXHAUSTED")
        if season is not None and award > season["assistance_available_cents"]:
            raise ApiError("ERR_AID_BUDGET_EXHAUSTED")
    net = calc.net_fee_due(gross_fee_cents, surcharge, award)

    row = new_row()
    row.update(
        {
            "member_id": member["id"],
            "tournament_id": tournament["id"],
            "exemption_grant_id": grant["id"] if grant is not None else None,
            "aid_application_id": application["id"] if application is not None else None,
            "request_assistance": bool(request_assistance),
            "entry_status": "APPLIED",
            "fee_status": calc.fee_status_after_settlement(award, net),
            "priority_band": calc.priority_band(member, grant),
            "rank_at_entry": member["certified_rank_position"],
            "submitted_at": clock_iso(),
            "waitlist_position": None,
            "rejection_reason": None,
            "gross_fee_cents": gross_fee_cents,
            "late_entry_surcharge_cents": surcharge,
            "aid_award_cents": award,
            "net_fee_due_cents": net,
            "amount_paid_cents": 0,
            "refunded_cents": 0,
            "certified_round_count": 0,
            "total_adjusted_strokes": 0,
            "avg_scoring_differential": None,
            "finish_position": None,
            "event_points": None,
            "withdrawn_at": None,
        }
    )
    insert("entries", row)
    if award > 0 and season is not None and application is not None:
        services.settle_award(season, application, row, award)
    services.recompute_census(tournament)
    bump(tournament)
    return object_response(public(row), 201)


@bp.route("/entries", methods=["GET"])
def list_entries():
    guard(("TourAdmin", "RulesOfficial", "ChiefReferee", "ConductCommittee"))
    return listing.listing(
        "entries",
        ("member_id", "tournament_id", "exemption_grant_id", "aid_application_id",
         "entry_status", "fee_status"),
    )


@bp.route("/entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    caller = guard(
        ("TourAdmin", "RulesOfficial", "ChiefReferee", "ConductCommittee", "Member")
    )
    entry = find("entries", entry_id, "ERR_ENTRY_NOT_FOUND")
    require_member_ownership(caller, entry["member_id"])
    return object_response(public(entry))


@bp.route("/entries/<entry_id>/withdraw", methods=["POST"])
def withdraw_entry_route(entry_id):
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    validate.opt_str(body, "reason", 1, 2000)
    entry = find("entries", entry_id, "ERR_ENTRY_NOT_FOUND")
    require_member_ownership(caller, entry["member_id"])
    if entry["entry_status"] not in ("APPLIED", "ACCEPTED", "WAITLISTED", "COMPETING"):
        raise ApiError("ERR_INVALID_ENTRY_STATE")
    tournament = services.tournament_of_entry(entry)
    if entry["entry_status"] in ("APPLIED", "WAITLISTED"):
        services.withdraw_entry(entry, tournament)
    else:
        deadline = dt_of(tournament["withdrawal_deadline_at"])
        if deadline is not None and clock() > deadline:
            services.forfeit_entry(entry, tournament, charge_late_withdrawal=True)
        else:
            services.withdraw_entry(entry, tournament)
    return object_response(public(entry))


@bp.route("/entries/<entry_id>/pay", methods=["POST"])
def pay_entry(entry_id):
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    amount_cents = validate.req_int(body, "amount_cents")
    entry = find("entries", entry_id, "ERR_ENTRY_NOT_FOUND")
    require_member_ownership(caller, entry["member_id"])
    if entry["entry_status"] in TERMINAL_ENTRY_STATUSES:
        raise ApiError("ERR_INVALID_ENTRY_STATE")
    if entry["net_fee_due_cents"] <= 0:
        raise ApiError("ERR_INVALID_ENTRY_STATE")
    outstanding = entry["net_fee_due_cents"] - entry["amount_paid_cents"]
    if amount_cents <= 0 or amount_cents != outstanding:
        raise ApiError("ERR_PAYMENT_AMOUNT_INVALID")
    entry["amount_paid_cents"] += amount_cents
    entry["fee_status"] = "PAID"
    bump(entry)
    return object_response(public(entry))


# ---------------------------------------------------------------------------
# assistance applications
# ---------------------------------------------------------------------------
@bp.route("/aid-applications", methods=["POST"])
def create_aid_application():
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    member_id = validate.req_id(body, "member_id")
    season_id = validate.req_id(body, "season_id")
    household_income_cents = validate.req_int(body, "household_income_cents", minimum=0)
    dependents = validate.req_int(body, "dependents", minimum=1)
    expected_version = validate.req_int(body, "expected_member_version")

    season = find("seasons", season_id, "ERR_SEASON_NOT_FOUND")
    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    require_member_ownership(caller, member["id"])
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if member["eligibility_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED")

    prior = [
        a
        for a in db.aid_applications.values()
        if a["member_id"] == member["id"]
        and a["season_id"] == season["id"]
        and a["status"] in ("SUBMITTED", "APPROVED")
    ]
    for old in prior:
        if old["consumed_cents"] > 0:
            raise ApiError("ERR_DUPLICATE_ENTRY")
    for old in prior:
        old["status"] = "SUPERSEDED"
        bump(old)

    per_dependent = calc.income_per_dependent(household_income_cents, dependents)
    row = new_row()
    row.update(
        {
            "member_id": member["id"],
            "season_id": season["id"],
            "household_income_cents": household_income_cents,
            "dependents": dependents,
            "income_per_dependent_cents": per_dependent,
            "covered_pct": float(calc.covered_pct(per_dependent)),
            "estimated_award_cents": None,
            "per_member_cap_cents": calc.PER_MEMBER_CAP_CENTS,
            "consumed_cents": 0,
            "status": "SUBMITTED",
            "decided_by_user_id": None,
            "decided_at": None,
        }
    )
    insert("aid_applications", row)
    bump(member)
    return object_response(public(row), 201)


@bp.route("/aid-applications", methods=["GET"])
def list_aid_applications():
    guard(("TourAdmin",))
    return listing.listing("aid_applications", ("member_id", "season_id", "status"))


@bp.route("/aid-applications/<application_id>", methods=["GET"])
def get_aid_application(application_id):
    caller = guard(("TourAdmin", "Member"))
    application = find(
        "aid_applications", application_id, "ERR_AID_APPLICATION_NOT_FOUND"
    )
    require_member_ownership(caller, application["member_id"])
    return object_response(public(application))


@bp.route("/aid-applications/<application_id>/decide", methods=["POST"])
def decide_aid_application(application_id):
    caller = guard(("TourAdmin",))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("APPROVED", "DENIED"))
    application = find(
        "aid_applications", application_id, "ERR_AID_APPLICATION_NOT_FOUND"
    )
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_GRANT_STATE")
    if decision == "APPROVED":
        pct = calc.D(application["covered_pct"])
        if pct <= 0:
            raise ApiError("ERR_INCOME_INELIGIBLE")
        application["status"] = "APPROVED"
        application["estimated_award_cents"] = calc.estimated_award(pct)
    else:
        application["status"] = "DENIED"
        application["covered_pct"] = 0.00
        application["estimated_award_cents"] = 0
    application["decided_by_user_id"] = caller.user_id
    application["decided_at"] = clock_iso()
    bump(application)
    return object_response(public(application))
