"""Federal award applications, matching funds and draw control."""
from decimal import Decimal

import calc
import services as svc
import shape
from auth import authenticate, scope, segregation
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, db, ordered, touch

bp = Blueprint("awards", __name__)

AWARD_WRITE_ROLES = ("AwardAdministrator", "InstitutionOfficer")
AWARD_READ_ROLES = ("AwardAdministrator", "InstitutionOfficer", "ComplianceAnalyst")
AWARD_LIST_ROLES = ("AwardAdministrator", "ComplianceAnalyst")
COMMITMENT_READ_ROLES = ("InstitutionOfficer", "AwardAdministrator",
                         "ComplianceAnalyst")
PROGRAMS = ("CDFI_PROGRAM_FA", "CDFI_PROGRAM_TA", "NEW_MARKETS", "CMF")
SOURCE_TYPES = ("CASH_PRIVATE", "CASH_PUBLIC_NON_FEDERAL", "IN_KIND",
                "DEFERRED_PLEDGE", "FEDERAL")
DECISIONS = ("AWARD", "REJECT")
PLEDGE_OPEN_STATES = ("DRAFT", "SUBMITTED", "AWARDED", "DISBURSING")
UNSETTLED = ("PLEDGED", "HELD")


def _award_owner(award_id):
    row = db.awards.get(award_id)
    return row["institution_id"] if row else None


def _commitment_owner(commitment_id):
    row = db.commitments.get(commitment_id)
    if row is None:
        return None
    award = db.awards.get(row["award_application_id"])
    return award["institution_id"] if award else None


@bp.post("/institutions/<institution_id>/award-applications")
def create_award(institution_id):
    caller = authenticate(AWARD_WRITE_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    program = shape.req_enum(data, "program", PROGRAMS)
    requested = shape.req_int(data, "requested_amount_cents", minimum=1)
    ratio = shape.req_dec(data, "match_ratio_pct", places=2, minimum=0, maximum=200)
    goal_jobs = shape.req_int(data, "performance_goal_jobs", minimum=0)
    goal_units = shape.req_int(data, "performance_goal_housing_units", minimum=0)
    start_raw, start = shape.req_dt(data, "period_start")
    end_raw, end = shape.req_dt(data, "period_end")
    if not end > start:
        fail("ERR_PERIOD_BOUNDS_INVALID")
    required = calc.required_match_cents(requested, ratio)
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "program": program,
        "requested_amount_cents": requested,
        "match_ratio_pct": ratio,
        "required_match_cents": required,
        "match_eligible_cents": 0,
        "match_shortfall_cents": required,
        "performance_goal_jobs": goal_jobs,
        "performance_goal_housing_units": goal_units,
        "period_start": start_raw,
        "period_end": end_raw,
        "awarded_amount_cents": 0,
        "goal_attainment_pct": Decimal("0.00"),
        "state": "DRAFT",
        "suspension_reason": None,
        "decided_by_user_id": None,
    })
    db.awards[row["id"]] = row
    return created(row)


@bp.get("/award-applications/<award_id>")
def read_award(award_id):
    caller = authenticate(AWARD_READ_ROLES)
    scope(caller, _award_owner(award_id))
    return ok(svc.get_award(award_id))


@bp.get("/institutions/<institution_id>/award-applications")
def list_institution_awards(institution_id):
    caller = authenticate(AWARD_READ_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = svc.institution_awards(institution_id)
    return page(_filter_awards(rows), limit, offset)


@bp.get("/award-applications")
def list_awards():
    authenticate(AWARD_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.awards.values())
    institution_id = qs("institution_id")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    return page(_filter_awards(rows), limit, offset)


def _filter_awards(rows):
    for name in ("state", "program"):
        value = qs(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return rows


@bp.post("/award-applications/<award_id>/submit")
def submit_award(award_id):
    caller = authenticate(AWARD_WRITE_ROLES)
    scope(caller, _award_owner(award_id))
    award = svc.get_award(award_id)
    if award["state"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    inst = svc.get_institution(award["institution_id"])
    if inst["certification_state"] != "CERTIFIED":
        fail("ERR_INSTITUTION_NOT_CERTIFIED")
    if not svc.award_commitments(award["id"]):
        fail("ERR_NO_MATCH_COMMITMENTS")
    award["state"] = "SUBMITTED"
    touch(award)
    return ok(award)


@bp.post("/award-applications/<award_id>/decide")
def decide_award(award_id):
    caller = authenticate(("AwardAdministrator",))
    award = svc.get_award(award_id)
    data = shape.body()
    decision = shape.req_enum(data, "decision", DECISIONS)
    amount = shape.opt_int(data, "awarded_amount_cents", minimum=0)
    if award["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    award["decided_by_user_id"] = caller.user_id
    if decision == "AWARD":
        award["state"] = "AWARDED"
        award["awarded_amount_cents"] = (amount if amount is not None
                                         else award["requested_amount_cents"])
    else:
        award["state"] = "REJECTED"
        award["awarded_amount_cents"] = None
    touch(award)
    return ok(award)


@bp.post("/award-applications/<award_id>/activate-disbursing")
def activate_disbursing(award_id):
    authenticate(("AwardAdministrator",))
    award = svc.get_award(award_id)
    if award["state"] != "AWARDED":
        fail("ERR_AWARD_NOT_AWARDED")
    inst = svc.get_institution(award["institution_id"])
    if inst["compliance_posture"] not in ("COMPLIANT", "WATCH"):
        fail("ERR_POSTURE_NOT_COMPLIANT")
    for commitment in svc.award_commitments(award["id"]):
        if commitment["status"] in UNSETTLED:
            fail("ERR_MATCH_COMMITMENTS_UNVERIFIED")
    if award["match_shortfall_cents"] != 0:
        fail("ERR_MATCH_SHORTFALL")
    award["state"] = "DISBURSING"
    award["suspension_reason"] = None
    touch(award)
    return ok(award)


@bp.post("/award-applications/<award_id>/resume-draws")
def resume_draws(award_id):
    authenticate(("AwardAdministrator",))
    award = svc.get_award(award_id)
    if award["state"] != "DRAW_SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION")
    inst = svc.get_institution(award["institution_id"])
    # Strictly tighter than activation: WATCH is not sufficient here.
    if inst["compliance_posture"] != "COMPLIANT":
        fail("ERR_POSTURE_NOT_COMPLIANT")
    svc.resume_draws(award)
    return ok(award)


# --------------------------------------------------------------------------- #
# matching-fund commitments
# --------------------------------------------------------------------------- #
@bp.post("/award-applications/<award_id>/matching-fund-commitments")
def create_commitment(award_id):
    caller = authenticate(AWARD_WRITE_ROLES)
    scope(caller, _award_owner(award_id))
    award = svc.get_award(award_id)
    data = shape.body()
    source_name = shape.req_str(data, "source_name", 1)
    source_type = shape.req_enum(data, "source_type", SOURCE_TYPES)
    amount = shape.req_int(data, "amount_cents", minimum=1)
    committed_raw, _ = shape.req_dt(data, "committed_on")
    if award["state"] not in PLEDGE_OPEN_STATES:
        fail("ERR_INVALID_STATE_TRANSITION")
    row = base_row()
    row.update({
        "award_application_id": award["id"],
        "source_name": source_name,
        "source_type": source_type,
        "amount_cents": amount,
        "committed_on": committed_raw,
        "eligible_cents": 0,
        "status": "PLEDGED",
        "verified_by_user_id": None,
        "withdraw_reason": None,
    })
    db.commitments[row["id"]] = row
    return created(row)


@bp.get("/award-applications/<award_id>/matching-fund-commitments")
def list_award_commitments(award_id):
    caller = authenticate(AWARD_READ_ROLES)
    scope(caller, _award_owner(award_id))
    svc.get_award(award_id)
    limit, offset = pagination()
    rows = svc.award_commitments(award_id)
    return page(_filter_commitments(rows), limit, offset)


@bp.get("/matching-fund-commitments")
def list_commitments():
    authenticate(AWARD_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.commitments.values())
    award_id = qs("award_application_id")
    if award_id is not None:
        rows = [r for r in rows if r["award_application_id"] == award_id]
    return page(_filter_commitments(rows), limit, offset)


def _filter_commitments(rows):
    for name in ("status", "source_type"):
        value = qs(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return rows


@bp.get("/matching-fund-commitments/<commitment_id>")
def read_commitment(commitment_id):
    caller = authenticate(COMMITMENT_READ_ROLES)
    scope(caller, _commitment_owner(commitment_id))
    return ok(svc.get_commitment(commitment_id))


@bp.post("/matching-fund-commitments/<commitment_id>/verify")
def verify_commitment(commitment_id):
    caller = authenticate(("AwardAdministrator",))
    existing = db.commitments.get(commitment_id)
    if existing is not None:
        award_row = db.awards.get(existing["award_application_id"])
        if award_row is not None:
            segregation(caller, award_row["decided_by_user_id"])
    commitment = svc.get_commitment(commitment_id)
    award = svc.get_award(commitment["award_application_id"])
    if commitment["status"] != "PLEDGED":
        fail("ERR_COMMITMENT_NOT_PLEDGED")
    if commitment["source_type"] == "FEDERAL":
        # Federal money is never verifiable as match.
        fail("ERR_FEDERAL_SOURCE_INELIGIBLE")
    commitment["status"] = "VERIFIED"
    commitment["verified_by_user_id"] = caller.user_id
    commitment["eligible_cents"] = calc.commitment_eligible_cents(
        commitment["amount_cents"], commitment["source_type"])
    touch(commitment)
    svc.recompute_match_ledger(award)
    touch(award)
    return ok(commitment)


@bp.post("/matching-fund-commitments/<commitment_id>/withdraw")
def withdraw_commitment(commitment_id):
    caller = authenticate(AWARD_WRITE_ROLES)
    scope(caller, _commitment_owner(commitment_id))
    commitment = svc.get_commitment(commitment_id)
    award = svc.get_award(commitment["award_application_id"])
    data = shape.body()
    reason = shape.req_str(data, "withdraw_reason", 1)
    if commitment["status"] not in ("PLEDGED", "VERIFIED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    commitment["status"] = "WITHDRAWN"
    commitment["withdraw_reason"] = reason
    # Withdrawing a VERIFIED source reverses its contribution exactly; a merely
    # PLEDGED source never entered the ledger.
    commitment["eligible_cents"] = 0
    touch(commitment)
    svc.recompute_match_ledger(award)
    touch(award)
    return ok(commitment)
