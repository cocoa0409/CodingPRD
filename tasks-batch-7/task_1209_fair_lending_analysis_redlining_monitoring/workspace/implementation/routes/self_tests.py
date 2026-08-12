"""Self-tests and privilege."""
from flask import Blueprint, request

import db
from errors import already_terminal, err, invalid_request, invalid_state
from middleware import (
    body, check_enum, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj

bp = Blueprint("self_tests", __name__)

ROLES = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")
TERMINAL = ("CLOSED_NO_VIOLATION", "REMEDIATED", "PRIVILEGE_LOST")
OUTCOMES = ("NO_VIOLATION", "VIOLATION_FOUND")


@bp.post("/fair-lending/self-tests")
@require_roles("FairLendingAnalyst")
def create_self_test():
    data = body()
    market_id = require_field(data, "market_id")
    window_start = require_field(data, "window_start")
    window_end = require_field(data, "window_end")
    if not (window_start <= window_end):
        raise invalid_request("window_start must not be after window_end")
    run_id = data.get("analysis_run_id")
    get_or_404("markets", market_id, "Market")
    if run_id is not None:
        get_or_404("runs", run_id, "AnalysisRun")
    # Closed-interval overlap: touching boundaries count as overlap.
    for st in db.STORES["self_tests"].values():
        if (
            st["market_id"] == market_id
            and st["status"] in ("ACTIVE", "CLOSED_VIOLATION")
            and window_start <= st["window_end"]
            and st["window_start"] <= window_end
        ):
            raise err(
                "ERR_SELF_TEST_WINDOW_OVERLAP",
                "Self-test window overlaps an ACTIVE/CLOSED_VIOLATION self-test",
            )
    rec = db.new_record(
        {
            "market_id": market_id,
            "analysis_run_id": run_id,
            "window_start": window_start,
            "window_end": window_end,
            "privileged": False,
            "disclosure_status": "DISCLOSABLE",
            "status": "ACTIVE",
            "cycles_open": 0,
        }
    )
    db.STORES["self_tests"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/self-tests")
@require_roles(*ROLES)
def list_self_tests():
    page, total, limit, offset = list_page(
        "self_tests",
        {
            "market_id": request.args.get("market_id"),
            "analysis_run_id": request.args.get("analysis_run_id"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/self-tests/<selfTestId>")
@require_roles(*ROLES)
def get_self_test(selfTestId):
    rec = get_or_404("self_tests", selfTestId, "SelfTest")
    return success_obj(db.public(rec))


def _load(selfTestId):
    rec = get_or_404("self_tests", selfTestId, "SelfTest")
    if rec["status"] in TERMINAL:
        raise already_terminal("SelfTest is in terminal state %s" % rec["status"])
    return rec


@bp.post("/fair-lending/self-tests/<selfTestId>/designate-privileged")
@require_roles("ComplianceDirector")
def designate_privileged(selfTestId):
    rec = _load(selfTestId)
    if rec["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE self-test can be designated privileged")
    rec["privileged"] = True
    rec["disclosure_status"] = "PRIVILEGED"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/self-tests/<selfTestId>/close")
@require_roles("FairLendingOfficer")
def close_self_test(selfTestId):
    rec = _load(selfTestId)
    if rec["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE self-test can be closed")
    data = body()
    outcome = check_enum(require_field(data, "outcome"), OUTCOMES, "outcome")
    if outcome == "NO_VIOLATION":
        rec["status"] = "CLOSED_NO_VIOLATION"
    else:
        run_id = rec.get("analysis_run_id")
        has_substantiated = False
        if run_id is not None:
            has_substantiated = any(
                f["analysis_run_id"] == run_id
                and f["status"] in ("SUBSTANTIATED", "CLOSED")
                for f in db.STORES["findings"].values()
            )
        if not has_substantiated:
            raise err(
                "ERR_NO_SUBSTANTIATED_FINDING",
                "VIOLATION_FOUND requires a SUBSTANTIATED/CLOSED finding on the linked run",
            )
        rec["status"] = "CLOSED_VIOLATION"
        rec["cycles_open"] = 0
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/self-tests/<selfTestId>/mark-remediated")
@require_roles("FairLendingOfficer")
def mark_remediated(selfTestId):
    rec = _load(selfTestId)
    if rec["status"] != "CLOSED_VIOLATION":
        raise invalid_state("Only a CLOSED_VIOLATION self-test can be marked remediated")
    run_id = rec.get("analysis_run_id")
    has_completed_cap = False
    if run_id is not None:
        run_finding_ids = {
            f["id"]
            for f in db.STORES["findings"].values()
            if f["analysis_run_id"] == run_id
        }
        has_completed_cap = any(
            c["finding_id"] in run_finding_ids and c["status"] == "COMPLETED"
            for c in db.STORES["caps"].values()
        )
    if not has_completed_cap:
        raise err(
            "ERR_REMEDIATION_OUTSTANDING",
            "A COMPLETED CAP on the linked run's findings is required",
        )
    rec["status"] = "REMEDIATED"
    # Privilege preserved: disclosure_status stays PRIVILEGED.
    db.touch(rec)
    return success_obj(db.public(rec))
