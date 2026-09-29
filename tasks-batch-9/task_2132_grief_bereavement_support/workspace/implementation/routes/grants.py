"""Grant awards, funding allocations and funder reporting (§3.9)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (CATEGORIES, bad, body, iso_date, opt_int, opt_str, req_array,
                        req_date, req_enum, req_int, req_str)
from core.store import public, store
from services import cascade, derive, reporting
from services.state import must_exist, transition

bp = Blueprint("grants", __name__)

MONEY_READ_ROLES = ["ProgramDirector", "GrantOfficer"]
FUNDABLE_COHORT_STATES = {"OPEN_ENROLLMENT", "RUNNING", "SUSPENDED"}
FUNDABLE_EVENT_STATES = {"PLANNED", "CONFIRMED"}


# ------------------------------------------------------------ grant awards
@bp.route("/bereavement/grant-awards", methods=["POST"])
def create_award():
    authenticate(["ProgramDirector"])
    data = body()
    funder_name = req_str(data, "funder_name")
    award_reference = req_str(data, "award_reference")
    awarded_cents = req_int(data, "awarded_cents", 0)
    allowed_categories = req_array(data, "allowed_categories", CATEGORIES)
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    indirect_rate = opt_int(data, "indirect_rate_bps", 1200, 0, 10000)

    for other in store.all("GrantAward"):
        if other["award_reference"] == award_reference:
            raise ApiError("ERR_DUPLICATE_AWARD_REFERENCE", "award_reference already exists.")

    rec = store.create("GrantAward", {
        "funder_name": funder_name,
        "award_reference": award_reference,
        "awarded_cents": awarded_cents,
        "committed_cents": 0,
        "spent_cents": 0,
        "available_cents": awarded_cents,
        "allowed_categories": allowed_categories,
        "period_start": iso_date(period_start),
        "period_end": iso_date(period_end),
        "indirect_rate_bps": indirect_rate,
        "status": "ACTIVE",
    })
    return created(public(rec))


@bp.route("/bereavement/grant-awards/<aid>", methods=["GET"])
def read_award(aid):
    authenticate(MONEY_READ_ROLES)
    return ok(public(must_exist("GrantAward", aid)))


@bp.route("/bereavement/grant-awards/<aid>/close", methods=["POST"])
def close_award(aid):
    authenticate(["ProgramDirector"])
    award = must_exist("GrantAward", aid)
    body()
    transition(award, {"ACTIVE"})
    if award["committed_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE", "Money is still committed against this award.")
    award["status"] = "CLOSED"
    store.touch(award)
    return ok(public(award))


# ------------------------------------------------------ funding allocations
def _provisional_for_cohort(cohort):
    projected = cohort["seats_filled"] + cohort["seats_held"]
    if projected > cohort["seats_total"]:
        projected = cohort["seats_total"]
    return calc.money(calc.dec(cohort["program_cost_total_cents"]) * calc.dec(projected)
                      / calc.dec(cohort["seats_total"]))


@bp.route("/bereavement/funding-allocations", methods=["POST"])
def create_allocation():
    authenticate(["ProgramDirector"])
    data = body()
    award_id = req_str(data, "grant_award_id")
    category = req_enum(data, "category", CATEGORIES)
    expected_version = req_int(data, "expected_grant_award_version")
    cohort_id = opt_str(data, "cohort_id")
    event_id = opt_str(data, "event_id")
    if category == "GROUP_PROGRAM":
        if cohort_id is None:
            bad("cohort_id is required for a GROUP_PROGRAM allocation.")
        if event_id is not None:
            bad("event_id must be null for a GROUP_PROGRAM allocation.")
    elif category == "REMEMBRANCE_EVENT":
        if event_id is None:
            bad("event_id is required for a REMEMBRANCE_EVENT allocation.")
        if cohort_id is not None:
            bad("cohort_id must be null for a REMEMBRANCE_EVENT allocation.")
    else:
        if cohort_id is not None:
            bad("cohort_id must be null for this category.")
        if event_id is not None:
            bad("event_id must be null for this category.")

    award = must_exist("GrantAward", award_id)
    cohort = must_exist("Cohort", cohort_id) if cohort_id else None
    event = must_exist("RemembranceEvent", event_id) if event_id else None

    if expected_version != award["version"]:
        raise ApiError("ERR_STALE_GRANT_VERSION", "The grant award version has moved.")

    if award["status"] == "CLOSED":
        raise ApiError("ERR_GRANT_CLOSED", "The award is closed.")
    if cohort is not None and cohort["status"] not in FUNDABLE_COHORT_STATES:
        raise ApiError("ERR_COHORT_NOT_FUNDABLE", "The cohort is not fundable in its current state.")
    if event is not None and event["status"] not in FUNDABLE_EVENT_STATES:
        raise ApiError("ERR_EVENT_NOT_FUNDABLE", "The event is not fundable in its current state.")

    if category not in award["allowed_categories"]:
        raise ApiError("ERR_CATEGORY_NOT_ALLOWED", "The category is not allowed by this award.")
    if category == "GROUP_PROGRAM":
        basis = "PROJECTED_ENROLLMENT"
    elif category == "REMEMBRANCE_EVENT":
        basis = "EVENT_PLAN"
    else:
        raise ApiError("ERR_ALLOCATION_SUBJECT_MISMATCH", "The category has no fundable subject.")

    effective = store.today().isoformat()
    if not (award["period_start"] <= effective <= award["period_end"]):
        raise ApiError("ERR_OUTSIDE_GRANT_PERIOD", "The effective date is outside the award period.")

    if basis == "PROJECTED_ENROLLMENT":
        provisional = _provisional_for_cohort(cohort)
    else:
        provisional = event["program_cost_total_cents"]

    if award["available_cents"] < provisional:
        raise ApiError("ERR_GRANT_FUNDS_INSUFFICIENT", "The award cannot afford this commitment.")

    rec = store.create("FundingAllocation", {
        "grant_award_id": award_id,
        "cohort_id": cohort_id,
        "event_id": event_id,
        "category": category,
        "provisional_cents": provisional,
        "settled_cents": None,
        "basis": basis,
        "status": "COMMITTED",
        "settled_at": None,
    })
    derive.recompute_award(award)
    store.touch(award)
    return created(public(rec))


@bp.route("/bereavement/funding-allocations/<fid>", methods=["GET"])
def read_allocation(fid):
    authenticate(MONEY_READ_ROLES)
    return ok(public(must_exist("FundingAllocation", fid)))


@bp.route("/bereavement/funding-allocations", methods=["GET"])
def list_allocations():
    authenticate(MONEY_READ_ROLES)
    rows = store.all("FundingAllocation")
    for key in ("grant_award_id", "cohort_id", "event_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/funding-allocations/<fid>/release", methods=["POST"])
def release_allocation(fid):
    authenticate(["ProgramDirector"])
    alloc = must_exist("FundingAllocation", fid)
    body()
    transition(alloc, {"COMMITTED"})
    cascade.release_allocation(alloc)
    return ok(public(alloc))


# ------------------------------------------------------------ grant reports
@bp.route("/bereavement/grant-reports", methods=["POST"])
def create_report():
    authenticate(["ProgramDirector"])
    data = body()
    award_id = req_str(data, "grant_award_id")
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")

    award = must_exist("GrantAward", award_id)
    if award["status"] == "CLOSED":
        raise ApiError("ERR_GRANT_CLOSED", "The award is closed.")

    start = iso_date(period_start)
    end = iso_date(period_end)
    for other in store.find("GrantReport", grant_award_id=award_id):
        if other["status"] in ("DRAFT", "SUBMITTED", "RETURNED"):
            if other["period_start"] <= end and start <= other["period_end"]:
                raise ApiError("ERR_REPORT_PERIOD_OVERLAP",
                               "An open report already covers an overlapping window.")

    rec = store.create("GrantReport", {
        "grant_award_id": award_id,
        "period_start": start,
        "period_end": end,
        "status": "DRAFT",
        "line_count": 0,
        "direct_total_cents": 0,
        "indirect_total_cents": 0,
        "reported_total_cents": 0,
        "participants_served": 0,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "return_reason": None,
        "revision_index": 0,
    })
    reporting.compute_totals(rec)
    return created(public(rec))


@bp.route("/bereavement/grant-reports/<rid>", methods=["GET"])
def read_report(rid):
    authenticate(MONEY_READ_ROLES)
    return ok(public(must_exist("GrantReport", rid)))


@bp.route("/bereavement/grant-reports", methods=["GET"])
def list_reports():
    authenticate(MONEY_READ_ROLES)
    rows = store.all("GrantReport")
    for key in ("grant_award_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/grant-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    ctx = authenticate(["ProgramDirector"])
    report = must_exist("GrantReport", rid)
    body()
    transition(report, {"DRAFT"})
    award = store.get("GrantAward", report["grant_award_id"])
    if award is None or award["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_CLOSED", "The award is closed.")
    reporting.compute_totals(report)
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = ctx.user_id
    report["submitted_at"] = store.now_iso()
    store.touch(report)
    return ok(public(report))


@bp.route("/bereavement/grant-reports/<rid>/return", methods=["POST"])
def return_report(rid):
    authenticate(["GrantOfficer"])
    report = must_exist("GrantReport", rid)
    data = body()
    reason = req_str(data, "return_reason")
    transition(report, {"SUBMITTED"})
    report["status"] = "RETURNED"
    report["return_reason"] = reason
    report["revision_index"] += 1
    store.touch(report)
    return ok(public(report))


@bp.route("/bereavement/grant-reports/<rid>/revise", methods=["POST"])
def revise_report(rid):
    authenticate(["ProgramDirector"])
    report = must_exist("GrantReport", rid)
    body()
    transition(report, {"RETURNED"})
    report["status"] = "DRAFT"
    report["submitted_by_user_id"] = None
    report["submitted_at"] = None
    reporting.compute_totals(report)
    store.touch(report)
    return ok(public(report))


@bp.route("/bereavement/grant-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    ctx = authenticate(["GrantOfficer"])
    report = must_exist("GrantReport", rid)
    if report["submitted_by_user_id"] is not None and report["submitted_by_user_id"] == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The accepting operator must differ from the submitting operator.")
    body()
    transition(report, {"SUBMITTED"})
    report["status"] = "ACCEPTED"
    store.touch(report)
    return ok(public(report))
