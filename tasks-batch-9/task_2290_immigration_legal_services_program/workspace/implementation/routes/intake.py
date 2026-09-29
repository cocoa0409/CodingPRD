"""Intake screenings: creation, screening, the decision fork and withdrawal."""

import datetime

from flask import Blueprint, request

import auth
import calc
import cascades
import response
import serialize
import store
import validation as v
from errors import ApiError
from routes.core import recompute_client

bp = Blueprint("intake", __name__)

DECISIONS = ("ACCEPT", "WAITLIST", "DECLINE", "REFER_OUT")
ALL_REASONS = ("ACCEPTED_ON_MERIT", "ACCEPTED_DETAINED_PRIORITY", "CAPACITY_FULL",
               "OUTSIDE_SERVICE_AREA", "NO_LEGAL_RELIEF", "INCOME_ABOVE_THRESHOLD",
               "CONFLICT_OF_INTEREST", "CLIENT_WITHDREW")
ACCEPT_REASONS = ("ACCEPTED_ON_MERIT", "ACCEPTED_DETAINED_PRIORITY")
DECLINE_REASONS = ("NO_LEGAL_RELIEF", "INCOME_ABOVE_THRESHOLD", "OUTSIDE_SERVICE_AREA",
                   "CONFLICT_OF_INTEREST")
REFER_REASONS = ("OUTSIDE_SERVICE_AREA", "CONFLICT_OF_INTEREST", "NO_LEGAL_RELIEF")


def _indigency_refuses(case_type, client):
    """Whether PRD 3.1's financial refusal applies to this pair.

    PRD 3.1: "a `fpl_percent` above 200.00 on a case type that is not fee-exempt
    is rejected with `ERR_INDIGENCY_CEILING_EXCEEDED`".
    """
    if client is None or case_type in calc.FEE_EXEMPT_CASE_TYPES:
        return False
    return not calc.indigency_eligible(client)


def _check_indigency_ceiling(case_type, client):
    """Raise on the two operations PRD 3.1 names: opening a screening and deciding one."""
    if _indigency_refuses(case_type, client):
        raise ApiError("ERR_INDIGENCY_CEILING_EXCEEDED",
                       "fpl_percent is above 200.00 on a case type that is not "
                       "fee-exempt.")


@bp.post("/intake-screenings")
@auth.requires("ProgramDirector", "IntakeScreener")
def create_screening():
    payload = v.body()
    client_id = v.as_id(payload, "client_id")
    cycle_id = v.as_id(payload, "cycle_id")
    facility_id = v.as_id(payload, "facility_id", required=False, default=None)
    client = store.get("clients", client_id)
    if client is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    cycle = store.get("cycles", cycle_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    if facility_id is not None and store.get("facilities", facility_id) is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    case_type = v.as_enum(payload, "case_type", calc.CASE_TYPES)
    detained = v.as_bool(payload, "detained", default=False)
    deadline = v.as_date(payload, "statutory_deadline_date", required=False, default=None)
    one_year = v.as_bool(payload, "one_year_bar_applies", default=False)
    prior_removal = v.as_bool(payload, "prior_removal_order", default=False)
    minor = v.as_bool(payload, "unaccompanied_minor", default=False)
    if detained and facility_id is None:
        raise ApiError("ERR_FACILITY_REQUIRED_FOR_DETAINED",
                       "facility_id is required when detained is true.")
    _check_indigency_ceiling(case_type, client)
    row = store.new_row({
        "client_id": client_id,
        "cycle_id": cycle_id,
        "screener_representative_id": None,
        "decided_by_representative_id": None,
        "facility_id": facility_id,
        "case_type": case_type,
        "detained": detained,
        "statutory_deadline_date": deadline.isoformat() if deadline else None,
        "one_year_bar_applies": one_year,
        "prior_removal_order": prior_removal,
        "unaccompanied_minor": minor,
        "legal_eligibility_verdict": "PENDING",
        "urgency_score": None,
        "urgency_tier": None,
        "urgency_variant_applied": None,
        "urgency_anchor_date": None,
        "status": "DRAFT",
        "decision_reason_code": None,
        "referral_partner_code": None,
        "waitlist_rank": None,
        "waitlist_expires_at_utc": None,
        "screened_at_utc": None,
        "decided_at_utc": None,
    })
    store.insert("screenings", row)
    return response.created(serialize.screening(row))


@bp.get("/intake-screenings")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney", "GrantAnalyst")
def list_screenings():
    rows = store.rows("screenings")
    args = request.args
    for key in ("client_id", "cycle_id", "screener_representative_id",
                "decided_by_representative_id", "facility_id", "status", "urgency_tier"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.screening(r) for r in page], meta)


@bp.get("/intake-screenings/<intake_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney", "GrantAnalyst",
               "ClientPortalUser", scoped=True)
def read_screening(intake_id):
    row = store.get("screenings", intake_id)
    portal = auth.portal_client_id()
    if portal is not None:
        if row is None or row.get("client_id") != portal:
            raise ApiError("ERR_ACTOR_NOT_ON_CASE",
                           "The screening does not belong to the acting client.")
    auth.check_rep_active()
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The intake screening does not exist.")
    return response.ok(serialize.screening(row))


@bp.post("/intake-screenings/<intake_id>/screen")
@auth.requires("IntakeScreener", "ProgramDirector")
def screen_screening(intake_id):
    row = store.get("screenings", intake_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The intake screening does not exist.")
    if row["status"] not in ("DRAFT", "SCREENED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Screening is only legal from DRAFT or SCREENED.")
    client = store.get("clients", row["client_id"])
    if client is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    client["fpl_percent"] = calc.fpl_percent(client["household_size"],
                                             client["annual_household_income_cents"])
    store.touch(client)
    row["screener_representative_id"] = auth.user_id()
    row["legal_eligibility_verdict"] = calc.eligibility_verdict(row, client)
    row.update(calc.compute_urgency(row, client))
    row["screened_at_utc"] = store.clock_iso()
    row["status"] = "SCREENED"
    store.touch(row)
    return response.ok(serialize.screening(row))


def _stamp_decider(row):
    """Record the deciding identity and instant.

    PRD 3.4 attributes this to the decision branches themselves, so it is
    written only once a branch has cleared every gate: a rejected decide leaves
    the screening exactly as it found it.
    """
    row["decided_by_representative_id"] = auth.user_id()
    row["decided_at_utc"] = store.clock_iso()


def _accept(row, cycle, principal_matter_id, reason):
    posture = calc.effective_posture(cycle)
    tier = row.get("urgency_tier")
    detained = bool(row.get("detained"))
    pool = calc.resolve_pool(cycle, detained)
    if pool is None:
        raise ApiError("ERR_NO_SLOT_AVAILABLE",
                       "No capacity pool has a free seat for this screening.")
    if posture == "FROZEN" and not (detained and tier == "EMERGENCY"):
        raise ApiError("ERR_CYCLE_CAPACITY_FROZEN",
                       "The cycle capacity posture is FROZEN.")
    if posture == "RESTRICTED" and tier not in ("URGENT", "EMERGENCY"):
        raise ApiError("ERR_CYCLE_CAPACITY_FROZEN",
                       "A RESTRICTED posture only admits URGENT or EMERGENCY intakes.")
    # PRD 2.7 tier 6 orders slot availability, then the freeze, then the ceiling.
    _check_indigency_ceiling(row.get("case_type"),
                             store.get("clients", row["client_id"]))
    if principal_matter_id is not None:
        principal = store.get("matters", principal_matter_id)
        if principal.get("client_id") != row["client_id"]:
            raise ApiError("ERR_DERIVATIVE_CLIENT_MISMATCH",
                           "principal_matter_id belongs to a different client.")
    was_waitlisted = row["status"] == "WAITLISTED"
    _stamp_decider(row)
    row["status"] = "ACCEPTED"
    row["decision_reason_code"] = reason
    row["waitlist_rank"] = None
    row["waitlist_expires_at_utc"] = None
    store.touch(row)
    cascades.create_matter_for_screening(row, pool, principal_matter_id)
    calc.recompute_cycle(cycle)
    if was_waitlisted:
        cascades.rerank_waitlist(cycle["id"])
    client = store.get("clients", row["client_id"])
    if client is not None:
        recompute_client(client)


@bp.post("/intake-screenings/<intake_id>/decide")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def decide_screening(intake_id):
    row = store.get("screenings", intake_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The intake screening does not exist.")
    payload = v.body()
    principal_matter_id = v.as_id(payload, "principal_matter_id", required=False,
                                 default=None)
    if principal_matter_id is not None and store.get("matters", principal_matter_id) is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    cycle = store.get("cycles", row["cycle_id"])
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    decision = v.as_enum(payload, "decision", DECISIONS)
    reason = v.as_enum(payload, "decision_reason_code", ALL_REASONS)
    partner = v.as_str(payload, "referral_partner_code", required=False, min_len=1,
                       max_len=40, default=None)

    if auth.user_id() == row.get("screener_representative_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The screener may not decide its own screening.")

    promotion = decision == "ACCEPT" and row["status"] == "WAITLISTED"
    if promotion:
        expires = store.parse_dt(row.get("waitlist_expires_at_utc"))
        if expires is None or store.clock_dt() >= expires:
            raise ApiError("ERR_INTAKE_NOT_ACCEPTED",
                           "The waitlist reservation has expired.")
    elif row["status"] != "SCREENED":
        raise ApiError("ERR_INTAKE_NOT_ACCEPTED",
                       "The screening is not in SCREENED.")

    if decision == "ACCEPT":
        if reason not in ACCEPT_REASONS:
            v.bad("decision_reason_code is not an accept reason.")
        if row.get("legal_eligibility_verdict") != "ELIGIBLE" and not _indigency_refuses(
                row.get("case_type"), store.get("clients", row["client_id"])):
            # A purely financial ineligibility is reported by PRD 3.1's own id from
            # tier 6 instead, so it is left to the accept branch below.
            raise ApiError("ERR_INTAKE_NOT_ACCEPTED",
                           "The screening is not legally eligible.")
        _accept(row, cycle, principal_matter_id, reason)
    elif decision == "WAITLIST":
        if reason != "CAPACITY_FULL":
            v.bad("decision_reason_code must be CAPACITY_FULL for a waitlist decision.")
        _stamp_decider(row)
        # PRD 3.4 ranks the new row "one more than the count of screenings of the
        # same cycle already in WAITLISTED", so the count is taken before this row
        # joins that set.
        rank = cascades.next_waitlist_rank(cycle["id"])
        row["status"] = "WAITLISTED"
        row["decision_reason_code"] = reason
        row["waitlist_rank"] = rank
        row["waitlist_expires_at_utc"] = store.iso(
            store.clock_dt() + datetime.timedelta(days=calc.WAITLIST_TTL_DAYS))
        store.touch(row)
        calc.recompute_cycle(cycle)
    elif decision == "DECLINE":
        if reason not in DECLINE_REASONS:
            v.bad("decision_reason_code is not a decline reason.")
        _stamp_decider(row)
        row["status"] = "DECLINED"
        row["decision_reason_code"] = reason
        store.touch(row)
    else:
        if reason not in REFER_REASONS:
            v.bad("decision_reason_code is not a refer-out reason.")
        if partner is None:
            v.bad("referral_partner_code is required for a refer-out decision.")
        _stamp_decider(row)
        row["status"] = "REFERRED_OUT"
        row["decision_reason_code"] = reason
        row["referral_partner_code"] = partner
        store.touch(row)
    return response.ok(serialize.screening(row))


@bp.post("/intake-screenings/<intake_id>/withdraw")
@auth.requires("IntakeScreener", "ProgramDirector", "ClientPortalUser", scoped=True)
def withdraw_screening(intake_id):
    row = store.get("screenings", intake_id)
    portal = auth.portal_client_id()
    if portal is not None:
        if row is None or row.get("client_id") != portal:
            raise ApiError("ERR_ACTOR_NOT_ON_CASE",
                           "The screening does not belong to the acting client.")
    auth.check_rep_active()
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The intake screening does not exist.")
    status = row["status"]
    if status not in ("DRAFT", "SCREENED", "WAITLISTED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Withdrawal is not legal from %s." % status)
    if status == "ACCEPTED":
        matter = cascades.matter_for_screening(row["id"])
        if matter is not None and matter.get("filing_status") in ("FILED", "DECIDED",
                                                                 "APPEALED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The matter has already been filed with the adjudicator.")
    cycle = store.get("cycles", row["cycle_id"])
    row["status"] = "WITHDRAWN"
    row["decision_reason_code"] = "CLIENT_WITHDREW"
    row["decided_at_utc"] = store.clock_iso()
    if status == "WAITLISTED":
        row["waitlist_rank"] = None
        row["waitlist_expires_at_utc"] = None
    store.touch(row)
    if status == "WAITLISTED" and cycle is not None:
        calc.recompute_cycle(cycle)
        cascades.rerank_waitlist(cycle["id"])
    if status == "ACCEPTED":
        cascades.withdraw_accepted_screening(row)
    return response.ok(serialize.screening(row))
