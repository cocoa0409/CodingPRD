"""CoveragePeriod: attest, list, supersede (PRD §3.3)."""
from flask import Blueprint

import serializers
from db import db, stamp_create, touch
from errors import err
from helpers import get_json_body, paginate, qarg, require_enum, require_int
from lookups import get_account, get_coverage_period
from middleware import caller, require_role
from response import success
from services.account_calc import recompute_derived

bp = Blueprint("coverage", __name__)


@bp.route("/hsa/accounts/<account_id>/coverage-periods", methods=["POST"])
def attest_coverage(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    body = get_json_body()
    coverage_tier = require_enum(body, "coverage_tier", {"SELF_ONLY", "FAMILY"})
    effective_month = require_int(body, "effective_month")
    end_month = require_int(body, "end_month")

    # Bad month bounds OR overlap -> ERR_COVERAGE_OVERLAP (PRD §3.3).
    # Months 1..12, effective_month <= end_month.
    if not (1 <= effective_month <= 12 and 1 <= end_month <= 12 and effective_month <= end_month):
        raise err("ERR_COVERAGE_OVERLAP", "Invalid coverage month bounds")

    # Closed-closed overlap vs existing ATTESTED periods on this account:
    # overlap iff a.effective <= b.end AND b.effective <= a.end.
    for cp in db.coverage_periods.values():
        if cp["account_id"] != account_id or cp["status"] != "ATTESTED":
            continue
        if effective_month <= cp["end_month"] and cp["effective_month"] <= end_month:
            raise err("ERR_COVERAGE_OVERLAP", "Coverage interval overlaps an existing ATTESTED period")

    o = {
        "account_id": account_id,
        "coverage_tier": coverage_tier,
        "effective_month": effective_month,
        "end_month": end_month,
        "status": "ATTESTED",
    }
    stamp_create(o)
    db.coverage_periods[o["id"]] = o
    # Recompute limit / excess / posture (PRD §3.3 triggers on coverage create).
    recompute_derived(account)
    return success(serializers.coverage_period(o), status=201)


@bp.route("/hsa/accounts/<account_id>/coverage-periods", methods=["GET"])
def list_coverage(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    status_filter = qarg("status")
    items = [
        cp for cp in db.coverage_periods.values()
        if cp["account_id"] == account_id
        and (status_filter is None or cp["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.coverage_period(cp) for cp in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/coverage-periods/<cp_id>/supersede", methods=["POST"])
def supersede_coverage(account_id, cp_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    cp = get_coverage_period(account_id, cp_id)
    # Allowed only while ATTESTED and while account not CLOSED (each -> ERR_INVALID_STATE).
    if cp["status"] != "ATTESTED":
        raise err("ERR_INVALID_STATE", "CoveragePeriod is not ATTESTED")
    if account["lifecycle_status"] == "CLOSED":
        raise err("ERR_INVALID_STATE", "Account is CLOSED")
    cp["status"] = "SUPERSEDED"
    touch(cp)
    # Recompute limit / excess / posture (may newly LOCK).
    recompute_derived(account)
    return success(serializers.coverage_period(cp), status=200)
