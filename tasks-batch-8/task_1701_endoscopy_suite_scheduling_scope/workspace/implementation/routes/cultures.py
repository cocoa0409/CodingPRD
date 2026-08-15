"""ScopeCultureTest endpoints and the POSITIVE-result quarantine cascade
(PRD 3.7, calculation culture_exposure_window)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CULTURE_TEST_NOT_FOUND,
    ERR_SCOPE_NOT_FOUND,
    ERR_REPROCESSING_CYCLE_NOT_FOUND,
    ERR_SCOPE_NOT_AVAILABLE,
    ERR_CULTURE_SCOPE_MISMATCH,
    ERR_CYCLE_NOT_COMPLETE,
    ERR_CULTURE_ALREADY_RESULTED,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import now
from validate import get_body, opt_int, opt_str, req_enum, req_int, req_str, require_path_resource, resolve_ref

bp = Blueprint("culture_tests", __name__)

CULTURE_RESULTS = {"NEGATIVE", "POSITIVE"}


@bp.post("/endoscopy/culture-tests")
def create_culture_test():
    caller = authorized(["InfectionControlNurse"])
    body = get_body()
    # Rung 3 (existence): scope_id, then reprocessing_cycle_id
    scope = resolve_ref("scopes", body.get("scope_id"), ERR_SCOPE_NOT_FOUND)
    cycle = resolve_ref("reprocessing_cycles", body.get("reprocessing_cycle_id"),
                        ERR_REPROCESSING_CYCLE_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "scope_id")
    req_str(body, "reprocessing_cycle_id")
    # Rung 7 (state): a retired scope cannot be cultured.
    if scope["status"] == "OUT_OF_SERVICE":
        raise_error(ERR_SCOPE_NOT_AVAILABLE, "scope is OUT_OF_SERVICE")
    # Rung 11 (referential): the cycle must belong to this very scope and must
    # already be COMPLETE.
    if cycle["scope_id"] != scope["id"]:
        raise_error(ERR_CULTURE_SCOPE_MISMATCH,
                    "reprocessing_cycle_id belongs to a different scope")
    if cycle["status"] != "COMPLETE":
        raise_error(ERR_CYCLE_NOT_COMPLETE, "referenced cycle is not COMPLETE")
    rec = new_record("culture_tests", {
        "scope_id": scope["id"],
        "reprocessing_cycle_id": cycle["id"],
        "recorded_by": caller.user_id,
        "sampled_at": now(),
        "status": "PENDING",
        "result": None,
        "organism": None,
        "cfu_count": None,
        "resulted_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/culture-tests")
def list_culture_tests():
    return list_response("culture_tests", {
        "scope_id": request.args.get("scope_id"),
        "reprocessing_cycle_id": request.args.get("reprocessing_cycle_id"),
        "status": request.args.get("status"),
    })


@bp.get("/endoscopy/culture-tests/<rid>")
def get_culture_test(rid):
    return get_one("culture_tests", rid, ERR_CULTURE_TEST_NOT_FOUND)


def compute_exposure_window(scope_id, trigger_sampled_at):
    """culture_exposure_window: window_start is the sampled_at of the latest
    NEGATIVE culture on the scope strictly before the trigger sample (ties
    break toward the later-created culture); null when none exists."""
    negatives = [
        c for c in db["culture_tests"].values()
        if c["scope_id"] == scope_id
        and c["result"] == "NEGATIVE"
        and c["sampled_at"] < trigger_sampled_at
    ]
    if not negatives:
        return None
    latest = max(negatives, key=lambda c: (c["sampled_at"], c.get("_seq", 0)))
    return latest["sampled_at"]


def exposures_in_window(scope_id, window_start, window_end):
    """ScopeUsage rows of the scope (VOID included) whose booking's actual_end
    falls in (window_start, window_end] — left-exclusive, right-inclusive."""
    out = []
    for u in db["scope_usages"].values():
        if u["scope_id"] != scope_id:
            continue
        booking = db["bookings"].get(u["booking_id"])
        if booking is None or booking["actual_end"] is None:
            continue
        actual_end = booking["actual_end"]
        if window_start is not None and not (actual_end > window_start):
            continue
        if not (actual_end <= window_end):
            continue
        out.append(u)
    return out


@bp.post("/endoscopy/culture-tests/<rid>/result")
def record_culture_result(rid):
    authorized(["InfectionControlNurse"])
    culture = require_path_resource("culture_tests", rid, ERR_CULTURE_TEST_NOT_FOUND)
    body = get_body()
    # Rung 4 (schema): POSITIVE requires organism and cfu_count.
    result = req_enum(body, "result", CULTURE_RESULTS)
    organism = None
    cfu_count = None
    if result == "POSITIVE":
        organism = req_str(body, "organism")
        cfu_count = req_int(body, "cfu_count", minimum=0)
    else:
        organism = opt_str(body, "organism", None)
        cfu_count = opt_int(body, "cfu_count", None, minimum=0)
    # Rung 7 (state): results are recorded once.
    if culture["status"] != "PENDING":
        raise_error(ERR_CULTURE_ALREADY_RESULTED, "culture test already RESULTED")
    current = now()
    culture["status"] = "RESULTED"
    culture["result"] = result
    culture["organism"] = organism
    culture["cfu_count"] = cfu_count
    culture["resulted_at"] = current
    touch(culture)

    if result == "POSITIVE":
        scope = db["scopes"].get(culture["scope_id"])
        if scope is not None:
            window_end = culture["sampled_at"]
            window_start = compute_exposure_window(scope["id"], window_end)
            if scope["status"] == "OUT_OF_SERVICE":
                # No scope transition is possible; the case opens pre-settled.
                new_record("quarantine_cases", {
                    "scope_id": scope["id"],
                    "triggering_culture_id": culture["id"],
                    "status": "SCOPE_RETIRED",
                    "opened_at": current,
                    "exposure_window_start": window_start,
                    "exposure_window_end": window_end,
                    "reculture_cycle_id": None,
                    "released_by": None,
                    "resolved_at": current,
                })
            else:
                # The quarantine cascade: scope -> QUARANTINED; case OPEN with
                # the computed window; in-window usages flagged; their bookings
                # notified (the recall list).
                scope["status"] = "QUARANTINED"
                touch(scope)
                new_record("quarantine_cases", {
                    "scope_id": scope["id"],
                    "triggering_culture_id": culture["id"],
                    "status": "OPEN",
                    "opened_at": current,
                    "exposure_window_start": window_start,
                    "exposure_window_end": window_end,
                    "reculture_cycle_id": None,
                    "released_by": None,
                    "resolved_at": None,
                })
                for usage in exposures_in_window(scope["id"], window_start, window_end):
                    if not usage["exposure_flagged"]:
                        usage["exposure_flagged"] = True
                        touch(usage)
                    booking = db["bookings"].get(usage["booking_id"])
                    if booking is not None and not booking["notification_flag"]:
                        booking["notification_flag"] = True
                        touch(booking)
    return success_object(public(culture))
