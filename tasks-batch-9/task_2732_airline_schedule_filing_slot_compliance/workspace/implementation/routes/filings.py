"""Filing submissions: the frozen charge, the codeshare gate and the transmit stack."""
from flask import Blueprint

import calc
import db
import derive
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import acting_user, authenticate
from response import ok, written
from routes.common import READ_ROLES, decision_of, list_response, read_one
from util import dt_of, fmt_dt

bp = Blueprint("filing_submissions", __name__)

AGENT = ("FilingAgent",)
COUNTED_LEG_STATUSES = ("SLOT_BACKED", "CANCELLED")


def _changed_leg_count(version_id):
    """Frozen at creation: the legs that represent a change worth publishing."""
    return len([
        leg for leg in derive.legs_of_version(version_id)
        if leg["status"] in COUNTED_LEG_STATUSES
    ])


def _sync_status(version_id, acknowledged):
    required = derive.marketing_carriers_of_version(version_id)
    if not required:
        return "NOT_REQUIRED"
    if all(carrier_id in acknowledged for carrier_id in required):
        return "SYNCHRONIZED"
    return "PENDING_ACK"


@bp.post("/filing-submissions")
def create_filing_submission():
    authenticate(AGENT)
    payload = rv.body()
    version_id = rv.req_str(payload, "schedule_version_id", 1)
    system = rv.req_enum(payload, "distribution_system", "distribution_system")
    window = rv.req_enum(payload, "change_window", "change_window")
    version = store.require("schedule_versions", version_id)
    derive.recompute_all()
    if version["filing_status"] != "VALIDATED":
        raise ApiError("ERR_SCHEDULE_VERSION_STATE_INVALID")

    changed = _changed_leg_count(version_id)
    charge = calc.filing_charge(changed, window)
    row = store.insert("filing_submissions", {
        "schedule_version_id": version_id,
        "distribution_system": system,
        "change_window": window,
        "status": "QUEUED",
        "changed_leg_count": changed,
        "base_charge_subtotal_cents": charge["base_charge_subtotal_cents"],
        "expedite_rate_pct": charge["expedite_rate_pct"],
        "expedite_fee_cents": charge["expedite_fee_cents"],
        "total_charge_cents": charge["total_charge_cents"],
        "codeshare_sync_status": _sync_status(version_id, []),
        "codeshare_ack_carrier_ids": [],
        "submitted_by_user_id": acting_user(),
        "transmitted_by_user_id": None,
        "transmitted_at_utc": None,
        "acknowledged_at_utc": None,
        "resync_required": False,
        "rejection_reason": None,
    })
    return written(row, 201)


@bp.get("/filing-submissions/<filing_submission_id>")
def get_filing_submission(filing_submission_id):
    return ok(read_one("filing_submissions", filing_submission_id))


@bp.get("/filing-submissions")
def list_filing_submissions():
    authenticate(READ_ROLES)
    return list_response("filing_submissions", [
        ("schedule_version_id", rv.q_str("schedule_version_id")),
        ("distribution_system", rv.q_enum("distribution_system", "distribution_system")),
        ("change_window", rv.q_enum("change_window", "change_window")),
        ("status", rv.q_enum("status", "submission_status")),
        ("codeshare_sync_status", rv.q_enum("codeshare_sync_status", "codeshare_sync_status")),
        ("resync_required", rv.q_bool("resync_required")),
    ])


@bp.post("/filing-submissions/<filing_submission_id>/codeshare-ack")
def codeshare_ack(filing_submission_id):
    authenticate(("FilingAgent", "PartnerCarrier"))
    submission = store.require("filing_submissions", filing_submission_id)
    payload = rv.body()
    carrier_id = rv.req_str(payload, "marketing_carrier_id", 1)
    store.require("carriers", carrier_id)
    if submission["status"] != "QUEUED":
        raise ApiError("ERR_FILING_SUBMISSION_STATE_INVALID")
    if carrier_id not in submission["codeshare_ack_carrier_ids"]:
        submission["codeshare_ack_carrier_ids"] = (
            submission["codeshare_ack_carrier_ids"] + [carrier_id]
        )
    submission["codeshare_sync_status"] = _sync_status(
        submission["schedule_version_id"], submission["codeshare_ack_carrier_ids"]
    )
    mark(submission)
    return written(submission)


@bp.post("/filing-submissions/<filing_submission_id>/transmit")
def transmit(filing_submission_id):
    authenticate(AGENT)
    submission = store.require("filing_submissions", filing_submission_id)
    rv.body()
    version = store.require("schedule_versions", submission["schedule_version_id"])
    derive.recompute_all()

    if version["compliance_state"] == "BLOCKED":
        raise ApiError("ERR_SCHEDULE_BLOCKED")
    if submission["status"] != "QUEUED":
        raise ApiError("ERR_FILING_SUBMISSION_STATE_INVALID")
    if acting_user() == version["validated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if submission["codeshare_sync_status"] == "PENDING_ACK":
        raise ApiError("ERR_CODESHARE_NOT_SYNCHRONIZED")
    season = store.get("seasons", version["season_id"])
    if submission["change_window"] == "STANDARD" and season is not None:
        if db.now() > dt_of(season["filing_change_window_close_utc"]):
            raise ApiError("ERR_CHANGE_WINDOW_CLOSED")
    projected = version["filing_charge_accrued_cents"] + submission["total_charge_cents"]
    if projected > version["filing_charge_budget_cents"]:
        raise ApiError("ERR_FILING_CHARGE_BUDGET_EXCEEDED")

    submission["status"] = "TRANSMITTED"
    submission["transmitted_by_user_id"] = acting_user()
    submission["transmitted_at_utc"] = fmt_dt(db.now())
    mark(submission)
    version["filing_status"] = "FILED"
    version["filing_charge_accrued_cents"] = projected
    mark(version)
    for leg in derive.active(derive.legs_of_version(version["id"])):
        if leg["status"] == "SLOT_BACKED":
            leg["status"] = "FILED"
            mark(leg)
    return written(submission)


@bp.post("/filing-submissions/<filing_submission_id>/acknowledge")
def acknowledge(filing_submission_id):
    authenticate(AGENT)
    submission = store.require("filing_submissions", filing_submission_id)
    payload = rv.body()
    outcome = decision_of(payload, "outcome", ("ACCEPT", "REJECT"))
    reason = rv.opt_str(payload, "rejection_reason", 1, 500)
    if outcome == "REJECT" and reason is None:
        rv.bad("Field 'rejection_reason' is required when rejecting a submission.")
    version = store.require("schedule_versions", submission["schedule_version_id"])
    if submission["status"] != "TRANSMITTED":
        raise ApiError("ERR_FILING_SUBMISSION_STATE_INVALID")

    submission["acknowledged_at_utc"] = fmt_dt(db.now())
    if outcome == "ACCEPT":
        submission["status"] = "ACKNOWLEDGED"
        submission["resync_required"] = False
        mark(submission)
        return written(submission)

    submission["status"] = "REJECTED"
    submission["rejection_reason"] = reason
    mark(submission)
    version["filing_charge_accrued_cents"] = (
        version["filing_charge_accrued_cents"] - submission["total_charge_cents"]
    )
    if version["filing_status"] == "FILED":
        version["filing_status"] = "VALIDATED"
    mark(version)
    for leg in derive.active(derive.legs_of_version(version["id"])):
        if leg["status"] == "FILED":
            leg["status"] = "SLOT_BACKED"
            mark(leg)
    return written(submission)
