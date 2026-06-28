"""Fee schedule endpoints (PRD §3.1; scaffold §1.5)."""

from flask import Blueprint

import errors
import repo
from db import db
from helpers import (get_json_body, require_str, require_int, opt_bool,
                     parse_pagination, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import fee_schedule_out

bp = Blueprint("fee_schedules", __name__)


@bp.route("/dmv/fee-schedules", methods=["POST"])
@require_roles("PlatformAdmin")
def create_fee_schedule():
    body = get_json_body()
    state_code = require_str(body, "state_code")
    title_fee_cents = require_int(body, "title_fee_cents")
    registration_fee_cents = require_int(body, "registration_fee_cents")
    transfer_fee_cents = require_int(body, "transfer_fee_cents")
    lien_recording_fee_cents = require_int(body, "lien_recording_fee_cents")
    use_tax_rate_bps = require_int(body, "use_tax_rate_bps")
    trade_in_credit_allowed = opt_bool(body, "trade_in_credit_allowed", True)

    # use_tax_rate_bps must be >= 0 (scaffold constraint / §3.1).
    if use_tax_rate_bps < 0:
        raise errors.validation("use_tax_rate_bps must be >= 0")

    # Publishing a newer schedule supersedes any prior ACTIVE schedule for the
    # same state_code so at most one per state is ACTIVE.
    for s in db.fee_schedules.values():
        if s["state_code"] == state_code and s["status"] == "ACTIVE":
            s["status"] = "SUPERSEDED"
            repo.bump(s)

    rec = repo.make_fee_schedule(
        state_code, title_fee_cents, registration_fee_cents, transfer_fee_cents,
        lien_recording_fee_cents, use_tax_rate_bps, trade_in_credit_allowed,
    )
    return success(fee_schedule_out(rec), 201)


@bp.route("/dmv/fee-schedules", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst")
def list_fee_schedules():
    from flask import request
    limit, offset = parse_pagination()
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    items = list(db.fee_schedules.values())
    if state_code is not None:
        items = [s for s in items if s["state_code"] == state_code]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_success([fee_schedule_out(s) for s in page], limit, offset, total)


@bp.route("/dmv/fee-schedules/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst")
def get_fee_schedule(sid):
    s = db.fee_schedules.get(sid)
    if s is None:
        raise errors.not_found("fee schedule not found")
    return success(fee_schedule_out(s), 200)
