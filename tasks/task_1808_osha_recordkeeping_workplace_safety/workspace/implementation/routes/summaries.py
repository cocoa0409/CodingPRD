"""Annual summary (300A) endpoints (PRD §3.7)."""
from flask import Blueprint

from db import STORE, now_dt, now_iso, parse_datetime
from errors import (raise_error, ERR_DUPLICATE, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_CASES_UNRESOLVED,
                    ERR_HOURS_INCOMPLETE, ERR_DUTY_SEGREGATION,
                    ERR_SUMMARY_STALE, ERR_POSTING_WINDOW)
from middleware import get_auth, require_roles, RATES_READ_ROLES
from response import success_object
from services.core import (get_body, req_str, req_int, req_version,
                           base_fields, bump, serialize, lookup,
                           summary_full_rollup, case_set_pin)

bp = Blueprint("summaries", __name__)

RKC = ("RecordkeepingCoordinator",)


@bp.post("/safety/summaries")
def create_summary():
    auth = get_auth()
    require_roles(auth, RKC)
    data = get_body()
    establishment_id = req_str(data, "establishment_id")
    year = req_int(data, "year")
    lookup(STORE.establishments, establishment_id)
    if any(s["establishment_id"] == establishment_id and s["year"] == year
           for s in STORE.summaries.values()):
        raise_error(ERR_DUPLICATE,
                    "A summary already exists for this establishment-year")
    summary = base_fields()
    summary.update({
        "establishment_id": establishment_id,
        "year": year,
        "status": "DRAFT",
        "total_recordable_cases": 0,
        "total_dart_cases": 0,
        "total_days_away": 0,
        "total_restricted_days": 0,
        "annual_avg_employment": 0,
        "total_hours_worked": 0,
        "trir": None,
        "dart_rate": None,
        "prepared_by": None,
        "certified_by": None,
        "certified_at": None,
        "posting_window_open": "%04d-02-01T00:00:00.000Z" % (year + 1),
        "posting_window_close": "%04d-04-30T23:59:59.000Z" % (year + 1),
        "posted_at": None,
        "_prepared_pin": None,
        "_amendment_required": False,
    })
    STORE.summaries[summary["id"]] = summary
    return success_object(serialize(summary), status=201)


@bp.get("/safety/summaries/<summaryId>")
def get_summary(summaryId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    summary = lookup(STORE.summaries, summaryId)
    return success_object(serialize(summary))


@bp.post("/safety/summaries/<summaryId>/prepare")
def prepare_summary(summaryId):
    auth = get_auth()
    require_roles(auth, RKC)
    summary = lookup(STORE.summaries, summaryId)
    if summary["status"] not in ("DRAFT", "AMENDED"):
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    est_id, year = summary["establishment_id"], summary["year"]
    unresolved = [c for c in STORE.cases.values()
                  if c["establishment_id"] == est_id and c["log_year"] == year
                  and c["status"] in ("INTAKE", "PENDING_REVIEW")]
    if unresolved:
        raise_error(ERR_CASES_UNRESOLVED,
                    "Cases for the year are still in INTAKE/PENDING_REVIEW")
    logs = [h for h in STORE.hour_logs.values()
            if h["establishment_id"] == est_id and h["year"] == year
            and h["status"] in ("APPROVED", "LOCKED")]
    if len({h["month"] for h in logs}) < 12:
        raise_error(ERR_HOURS_INCOMPLETE,
                    "All twelve monthly hour logs must exist and be "
                    "APPROVED or LOCKED")
    if sum(h["hours_worked"] for h in logs) <= 0:
        raise_error(ERR_HOURS_INCOMPLETE,
                    "Total hours worked must be greater than zero")
    summary_full_rollup(summary)
    summary["status"] = "PREPARED"
    summary["prepared_by"] = auth.user_id
    summary["_prepared_pin"] = case_set_pin(est_id, year)
    bump(summary)
    return success_object(serialize(summary))


@bp.post("/safety/summaries/<summaryId>/certify")
def certify_summary(summaryId):
    auth = get_auth()
    require_roles(auth, ("SafetyOfficer",))
    summary = lookup(STORE.summaries, summaryId)
    data = get_body()
    expected = req_version(data, "expected_summary_version")
    # OCC check precedes the state check: a case mutation after prepare
    # bounces the summary to DRAFT and advances its version, and the stale
    # certifier observes ERR_STALE_VERSION (PRD §2.8).
    if expected != summary["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_summary_version does not match the current "
                    "summary version")
    if summary["status"] != "PREPARED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if auth.user_id == summary["prepared_by"]:
        raise_error(ERR_DUTY_SEGREGATION,
                    "Certifier must differ from the preparer")
    est_id, year = summary["establishment_id"], summary["year"]
    if case_set_pin(est_id, year) != summary["_prepared_pin"]:
        raise_error(ERR_SUMMARY_STALE,
                    "A case for the year mutated after preparation")
    summary["status"] = "CERTIFIED"
    summary["certified_by"] = auth.user_id
    summary["certified_at"] = now_iso()
    bump(summary)
    # Certified rates are frozen as stored; APPROVED hour logs lock.
    for h in STORE.hour_logs.values():
        if (h["establishment_id"] == est_id and h["year"] == year
                and h["status"] == "APPROVED"):
            h["status"] = "LOCKED"
            bump(h)
    return success_object(serialize(summary))


@bp.post("/safety/summaries/<summaryId>/post")
def post_summary(summaryId):
    auth = get_auth()
    require_roles(auth, RKC)
    summary = lookup(STORE.summaries, summaryId)
    if summary["status"] != "CERTIFIED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    now = now_dt()
    open_dt = parse_datetime(summary["posting_window_open"])
    close_dt = parse_datetime(summary["posting_window_close"])
    if not (open_dt <= now <= close_dt):
        raise_error(ERR_POSTING_WINDOW,
                    "300A may only be posted inside [Feb 1, Apr 30] of the "
                    "following year")
    summary["status"] = "POSTED"
    summary["posted_at"] = now_iso()
    bump(summary)
    return success_object(serialize(summary))


@bp.post("/safety/summaries/<summaryId>/amend")
def amend_summary(summaryId):
    auth = get_auth()
    require_roles(auth, RKC)
    summary = lookup(STORE.summaries, summaryId)
    if summary["status"] != "CERTIFIED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    close_dt = parse_datetime(summary["posting_window_close"])
    if not (now_dt() > close_dt or summary["_amendment_required"]):
        raise_error(ERR_INVALID_STATE,
                    "Amendment requires the posting window to have passed or "
                    "a reclassified case to have changed totals")
    summary_full_rollup(summary)
    summary["status"] = "AMENDED"
    summary["_amendment_required"] = False
    summary["_prepared_pin"] = None
    bump(summary)
    return success_object(serialize(summary))
