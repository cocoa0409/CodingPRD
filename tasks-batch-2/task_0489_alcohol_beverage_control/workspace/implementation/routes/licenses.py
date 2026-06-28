"""Licenses: fetch/list, check-renewal-window, renew, reinstate, pay-fine, and
the reverse-reachable child collections."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from auth import require_auth, ALL_READERS
from clock import clock, add_months
from db import db, touch
from helpers import (
    body, paginate, sort_created, out, out_list, get_or_404,
    find_license_class_by_code,
)
import validate
from calculations import renewal_fee
from cascades import expire_active_permits
from response import ok, listed

bp = Blueprint("licenses", __name__)


@bp.route("/licenses/<id>", methods=["GET"])
def get_license(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.licenses, id)
    return ok(out(ent))


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    require_auth(ALL_READERS)
    items = list(db.licenses.values())
    for key in ("application_id", "license_class_code", "region_code", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/licenses/<id>/check-renewal-window", methods=["POST"])
def check_renewal_window(id):
    require_auth(["Director", "LicensingExaminer"])
    lic = get_or_404(db.licenses, id)
    now = clock.now()
    if lic["status"] == "ACTIVE" and now >= lic["renewal_window_opens_at"]:
        lic["status"] = "RENEWAL_DUE"
        touch(lic)
    elif lic["status"] == "RENEWAL_DUE" and now >= lic["term_end_at"]:
        lic["status"] = "EXPIRED"
        expire_active_permits(lic["id"])
        touch(lic)
    return ok(out(lic))


@bp.route("/licenses/<id>/renew", methods=["POST"])
def renew_license(id):
    require_auth(["Applicant"])
    lic = get_or_404(db.licenses, id)
    # State gate (PRD 2.8, priority 4): renewal is part of the ACTIVE<->RENEWAL_DUE
    # term cycle. ACTIVE and RENEWAL_DUE are the in-bounds states; an ACTIVE license
    # whose window has not yet opened is surfaced by the renewal-timing business rule
    # below (PRD 3.8 folds "the license is in RENEWAL_DUE" into the
    # ERR_RENEWAL_WINDOW_NOT_OPEN condition). Genuinely off-cycle states
    # (SUSPENDED, EXPIRED, REVOKED) are undefined for renew -> ERR_INVALID_STATE.
    if lic["status"] not in ("ACTIVE", "RENEWAL_DUE"):
        raise errors.err(errors.ERR_INVALID_STATE, "License not renewable from this state")
    data = body()
    renewal_fee_paid = validate.require_int(data, "renewal_fee_paid_cents", minimum=0)

    now = clock.now()
    # priority 15 (PRD 3.8): renewal window must be open AND license in RENEWAL_DUE
    if lic["status"] != "RENEWAL_DUE" or now < lic["renewal_window_opens_at"]:
        raise errors.err(errors.ERR_RENEWAL_WINDOW_NOT_OPEN, "Renewal window not open")
    # priority 16: no outstanding fines
    if lic["outstanding_fine_cents"] > 0:
        raise errors.err(errors.ERR_OUTSTANDING_FINE, "Outstanding fine")
    # priority 17: demerit threshold
    if lic["demerit_points"] >= 10:
        raise errors.err(errors.ERR_DEMERIT_THRESHOLD, "Demerit threshold breached")

    lc = find_license_class_by_code(lic["license_class_code"])
    grace_lapsed = now >= lic["term_end_at"]
    due = renewal_fee(lc, grace_lapsed)
    if renewal_fee_paid < due:
        raise errors.err(errors.ERR_FEE_UNPAID, "Renewal fee not fully paid")

    # roll the term forward
    old_term_end = lic["term_end_at"]
    lic["term_start_at"] = old_term_end
    lic["term_end_at"] = add_months(old_term_end, lc["renewal_cycle_months"])
    lic["renewal_window_opens_at"] = lic["term_end_at"] - timedelta(days=60)
    lic["renewal_count"] = lic["renewal_count"] + 1
    lic["status"] = "ACTIVE"
    touch(lic)
    return ok(out(lic))


@bp.route("/licenses/<id>/reinstate", methods=["POST"])
def reinstate_license(id):
    require_auth(["Director"])
    lic = get_or_404(db.licenses, id)
    if lic["status"] != "SUSPENDED":
        raise errors.err(errors.ERR_INVALID_STATE, "License not SUSPENDED")
    # priority 16: outstanding fine
    if lic["outstanding_fine_cents"] > 0:
        raise errors.err(errors.ERR_OUTSTANDING_FINE, "Outstanding fine")
    # priority 17: demerit threshold
    if lic["demerit_points"] >= 10:
        raise errors.err(errors.ERR_DEMERIT_THRESHOLD, "Demerit threshold breached")
    lic["status"] = "ACTIVE"
    touch(lic)
    return ok(out(lic))


@bp.route("/licenses/<id>/pay-fine", methods=["POST"])
def pay_fine(id):
    require_auth(["Applicant"])
    lic = get_or_404(db.licenses, id)
    data = body()
    action_id = validate.require_str(data, "action_id")
    action = db.administrative_actions.get(action_id)
    if action is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Administrative action not found")
    amount = validate.require_int(data, "amount_cents", minimum=0)

    action["fine_paid_cents"] = action["fine_paid_cents"] + amount
    touch(action)
    lic["outstanding_fine_cents"] = max(lic["outstanding_fine_cents"] - amount, 0)
    touch(lic)
    return ok(out(lic))


# --- reverse-reachable children ----------------------------------------------
@bp.route("/licenses/<id>/server-permits", methods=["GET"])
def list_license_permits(id):
    require_auth(ALL_READERS)
    get_or_404(db.licenses, id)
    items = [p for p in db.server_permits.values() if p["license_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/licenses/<id>/violations", methods=["GET"])
def list_license_violations(id):
    require_auth(ALL_READERS)
    get_or_404(db.licenses, id)
    items = [v for v in db.violations.values() if v["license_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/licenses/<id>/administrative-actions", methods=["GET"])
def list_license_actions(id):
    require_auth(ALL_READERS)
    get_or_404(db.licenses, id)
    items = [a for a in db.administrative_actions.values() if a["license_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/licenses/<id>/compliance-reports", methods=["GET"])
def list_license_reports(id):
    require_auth(ALL_READERS)
    get_or_404(db.licenses, id)
    items = [c for c in db.compliance_reports.values() if c["license_id"] == id]
    period = request.args.get("period_code")
    if period is not None:
        items = [c for c in items if c["period_code"] == period]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/licenses/<id>/transfer-requests", methods=["GET"])
def list_license_transfers(id):
    require_auth(ALL_READERS)
    get_or_404(db.licenses, id)
    items = [t for t in db.transfer_requests.values() if t["license_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)
