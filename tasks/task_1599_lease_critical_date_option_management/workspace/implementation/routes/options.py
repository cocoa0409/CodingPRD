"""Option endpoints (§3.3, §3.8): register/get/list, withdraw."""
from flask import Blueprint, request

from errors import (
    raise_error, ERR_INVALID_STATE, ERR_TEMPORAL_ORDER, ERR_RATE_TERMS_INCOHERENT,
    ERR_STALE_VERSION, ERR_VALIDATION,
)
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, refresh, public, NONTERMINAL_OPTION_STATES,
    cancel_pending_reminders_for_option,
)
from routes.helpers import resolve_lease, resolve_option, sorted_items, paged
from util import fmt_date_midnight
from validate import get_body, req_int, opt_int, req_enum, req_dateish

bp = Blueprint("options", __name__)

OPTION_TYPES = ["RENEWAL", "EXPANSION", "TERMINATION", "ROFR"]
RATE_DETERMINATIONS = ["FIXED", "FAIR_MARKET"]


@bp.post("/portfolios/<pid>/leases/<lid>/options")
def create_option(pid, lid):
    authorized(["AssetManager"])
    _p, lease = resolve_lease(pid, lid)
    body = get_body()
    option_type = req_enum(body, "option_type", OPTION_TYPES)
    open_d = req_dateish(body, "notice_window_open_date")
    close_d = req_dateish(body, "notice_window_close_date")
    target = req_dateish(body, "target_commencement_date")
    rate_determination = req_enum(body, "rate_determination", RATE_DETERMINATIONS)
    fixed_rent = opt_int(body, "fixed_rent_cents_per_rsf_year", None)
    if fixed_rent is not None and fixed_rent <= 0:
        raise_error(ERR_VALIDATION, "fixed_rent_cents_per_rsf_year must be > 0")
    exercise_fee = opt_int(body, "exercise_fee_cents", 0, non_negative=True)
    penalty = opt_int(body, "missed_option_penalty_cents", 0, non_negative=True)
    if option_type == "RENEWAL":
        ext = req_int(body, "extension_years", minimum=1, maximum=10)
    else:
        ext = None  # ignored and stored as null for non-RENEWAL types

    # priority 10: window close must be on or after open (both bounds inclusive)
    if close_d < open_d:
        raise_error(ERR_TEMPORAL_ORDER,
                    "notice_window_close_date must be >= notice_window_open_date")

    # priority 11: rate determination coherence
    if rate_determination == "FIXED":
        # FIXED semantics (incl. TERMINATION/ROFR) require a positive fixed rent
        if fixed_rent is None:
            raise_error(ERR_RATE_TERMS_INCOHERENT,
                        "FIXED rate_determination requires fixed_rent_cents_per_rsf_year > 0")
    else:  # FAIR_MARKET — meaningful only for RENEWAL and EXPANSION
        if option_type in ("TERMINATION", "ROFR"):
            raise_error(ERR_RATE_TERMS_INCOHERENT,
                        "TERMINATION and ROFR options must use FIXED rate semantics")
        if fixed_rent is not None:
            raise_error(ERR_RATE_TERMS_INCOHERENT,
                        "FAIR_MARKET options must not carry fixed_rent_cents_per_rsf_year")

    option = new_record("options", {
        "lease_id": lid,
        "option_type": option_type,
        "notice_window_open_date": fmt_date_midnight(open_d),
        "notice_window_close_date": fmt_date_midnight(close_d),
        "target_commencement_date": fmt_date_midnight(target),
        "extension_years": ext,
        "rate_determination": rate_determination,
        "fixed_rent_cents_per_rsf_year": fixed_rent,
        "exercise_fee_cents": exercise_fee,
        "missed_option_penalty_cents": penalty,
        "status": "AVAILABLE",
        "exercised_at": None,
        "lapsed_at": None,
        "determined_rent_cents_per_rsf_year": None,
    })
    return success_object(public(option), 201)


@bp.get("/portfolios/<pid>/leases/<lid>/options")
def list_options(pid, lid):
    authorized(READ_ROLES)
    resolve_lease(pid, lid)
    items = sorted_items("options", {
        "lease_id": lid,
        "status": request.args.get("status"),
        "option_type": request.args.get("option_type"),
    })
    return paged(items, public)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>")
def get_option(pid, lid, oid):
    authorized(READ_ROLES)
    _p, _l, option = resolve_option(pid, lid, oid)
    return success_object(public(option))


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/withdraw")
def withdraw_option(pid, lid, oid):
    authorized(["AssetManager"])
    _p, lease, option = resolve_option(pid, lid, oid)
    body = get_body()
    expected = req_int(body, "expected_lease_version")
    # priority 5: state admissibility, checked before the version token (§3.8)
    if option["status"] not in NONTERMINAL_OPTION_STATES:
        raise_error(ERR_INVALID_STATE, "option cannot be withdrawn from its current state")
    # priority 14: OCC on Lease.version
    if expected != lease["version"]:
        raise_error(ERR_STALE_VERSION, "expected_lease_version does not match the lease version")
    option["status"] = "WITHDRAWN"
    refresh(option)
    cancel_pending_reminders_for_option(oid)
    from db import db
    for n in db["notices"].values():
        if n["option_id"] == oid and n["status"] in ("SENT", "DELIVERED"):
            n["status"] = "VOID"
            touch(n)
    touch(lease)
    return success_object(public(option))
