"""Water-bank lease assignments: reservation, activation and settlement."""
from flask import Blueprint

import calc
import cascades
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("leases", __name__)

VALUATION_METHODS = ("PRO_RATA_DAILY", "SEASON_BLOCK")
LEASE_STATUSES = ("RESERVED", "ACTIVE", "SUSPENDED", "COMPLETED", "CANCELLED")
LEASABLE_RIGHT_STATUSES = ("ACTIVE", "ENCUMBERED", "PARTIALLY_TRANSFERRED")
ZERO2 = calc.D("0.00")


def _window(lease):
    return (
        clock.parse_date(lease["lease_start_date"]),
        clock.parse_date(lease["lease_end_date"]),
    )


@bp.route("/lease-assignments", methods=["POST"])
def create_lease():
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )

    body = validate.get_body()
    common.owner_precheck(
        caller,
        body,
        "water_bank_account_id",
        db.water_bank_accounts,
        common.account_owner,
    )

    account_id = validate.req_str(body, "water_bank_account_id")
    right_id = validate.req_str(body, "water_right_id")
    pod_id = validate.req_str(body, "point_of_diversion_id")
    lessee_name = validate.req_str(body, "lessee_name", 1, 160)
    start_raw, start_dt = validate.req_date(body, "lease_start_date")
    end_raw, end_dt = validate.req_date(body, "lease_end_date")
    requested_af = validate.req_decimal(body, "requested_af", gt=0)
    rate_cfs = validate.req_decimal(body, "diversion_rate_cfs", gt=0)
    rental = validate.req_decimal(body, "rental_rate_usd_per_af", gte=0)
    valuation = validate.req_enum(body, "valuation_method", VALUATION_METHODS)

    account = common.get_account(account_id)
    right = common.get_right(right_id)
    pod = common.get_pod(pod_id)

    if pod["water_right_id"] != right["id"]:
        raise ApiError(
            "ERR_POD_RIGHT_MISMATCH",
            "The point of diversion belongs to a different water right.",
        )
    if account["claimant_id"] != right["claimant_id"]:
        raise ApiError(
            "ERR_POD_RIGHT_MISMATCH",
            "The bank account and the water right belong to different claimants.",
        )

    derive.recompute_right(right)
    if right["status"] not in LEASABLE_RIGHT_STATUSES:
        raise ApiError(
            "ERR_RIGHT_NOT_TRANSFERABLE",
            "A right in status %s cannot back a lease." % right["status"],
        )

    claimant = db.claimants.get(account["claimant_id"])
    if claimant is not None and claimant["standing_status"] != "IN_GOOD_STANDING":
        raise ApiError(
            "ERR_CLAIMANT_NOT_IN_GOOD_STANDING",
            "The claimant's standing is %s." % claimant["standing_status"],
        )

    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_WINDOW",
            "lease_end_date must be strictly after lease_start_date.",
        )

    # priority 41 -- fallow buffer between different headgates on one right
    buffer = calc.LEASE_BUFFER_DAYS * clock.DAY
    for other in derive.leases_for_right(right["id"]):
        if other["status"] not in derive.LEASE_LIVE_STATUSES:
            continue
        if other["point_of_diversion_id"] == pod["id"]:
            continue
        o_start, o_end = _window(other)
        if start_dt <= o_end + buffer and end_dt >= o_start - buffer:
            raise ApiError(
                "ERR_LEASE_WINDOW_CONFLICT",
                "The window collides with lease %s (a 7-day fallow buffer applies "
                "between different points of diversion on one right)." % other["id"],
            )

    # priority 42 -- instantaneous rate aggregation at one headgate
    existing_rates = []
    for other in db.lease_assignments.values():
        if other["point_of_diversion_id"] != pod["id"]:
            continue
        if other["status"] not in derive.LEASE_LIVE_STATUSES:
            continue
        o_start, o_end = _window(other)
        if calc.intervals_overlap_half_open(start_dt, end_dt, o_start, o_end):
            existing_rates.append(other["diversion_rate_cfs"])
    peak = calc.pod_peak_rate(rate_cfs, existing_rates)
    if peak > calc.q3(pod["max_rate_cfs"]):
        raise ApiError(
            "ERR_POD_CAPACITY_EXCEEDED",
            "Aggregate diversion rate %s cfs exceeds the headgate capacity %s cfs."
            % (peak, pod["max_rate_cfs"]),
        )

    if pod["status"] != "AUTHORIZED":
        raise ApiError(
            "ERR_POD_NOT_AUTHORIZED",
            "The point of diversion is %s, not AUTHORIZED." % pod["status"],
        )

    derive.recompute_account(account)
    requested_af = calc.q2(requested_af)
    if requested_af > account["available_credit_af"]:
        raise ApiError(
            "ERR_INSUFFICIENT_BANK_CREDIT",
            "requested_af %s exceeds available_credit_af %s."
            % (requested_af, account["available_credit_af"]),
        )

    row = db.base_row()
    row.update({
        "water_bank_account_id": account["id"],
        "water_right_id": right["id"],
        "point_of_diversion_id": pod["id"],
        "lessee_name": lessee_name,
        "lease_start_date": start_raw,
        "lease_end_date": end_raw,
        "requested_af": requested_af,
        "diversion_rate_cfs": calc.q3(rate_cfs),
        "rental_rate_usd_per_af": calc.q2(rental),
        "valuation_method": valuation,
        "status": "RESERVED",
        "used_af": ZERO2,
        "settlement_credit_af": ZERO2,
        "suspension_count": 0,
    })
    db.lease_assignments[row["id"]] = row

    derive.recompute_account(account)
    db.touch(account)
    return response.object_response(serialize.lease_assignment(row), 201)


@bp.route("/lease-assignments", methods=["GET"])
def list_leases():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    account_id = validate.query_str("water_bank_account_id")
    right_id = validate.query_str("water_right_id")
    pod_id = validate.query_str("point_of_diversion_id")
    status = validate.query_enum("status", LEASE_STATUSES)

    rows = []
    for row in db.lease_assignments.values():
        if account_id is not None and row["water_bank_account_id"] != account_id:
            continue
        if right_id is not None and row["water_right_id"] != right_id:
            continue
        if pod_id is not None and row["point_of_diversion_id"] != pod_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = common.sort_by(rows, lambda r: r["lease_start_date"])
    return common.emit(rows, serialize.lease_assignment, limit, offset)


@bp.route("/lease-assignments/<lid>", methods=["GET"])
def get_lease(lid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    lease = common.get_lease(lid)
    middleware.require_owner(caller, common.lease_owner(lease))
    return response.object_response(serialize.lease_assignment(lease))


def _refresh_after_lease_move(lease):
    account = db.water_bank_accounts.get(lease["water_bank_account_id"])
    if account is not None:
        derive.recompute_account(account)
        db.touch(account)
    right = db.water_rights.get(lease["water_right_id"])
    if right is not None:
        derive.recompute_right(right, bump=True)


@bp.route("/lease-assignments/<lid>/activate", methods=["POST"])
def activate_lease(lid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )
    lease = common.get_lease(lid)
    middleware.require_owner(caller, common.lease_owner(lease))
    validate.get_body(required=False)

    if lease["status"] != "RESERVED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a RESERVED lease may be activated (status is %s)." % lease["status"],
        )

    account = db.water_bank_accounts.get(lease["water_bank_account_id"])
    if account is not None:
        derive.recompute_account(account)
        if account["posture"] != "OPEN":
            raise ApiError(
                "ERR_ACCOUNT_POSTURE_BLOCKED",
                "The bank account posture is %s." % account["posture"],
            )

    pod = db.points_of_diversion.get(lease["point_of_diversion_id"])
    if pod is None or pod["status"] != "AUTHORIZED":
        raise ApiError(
            "ERR_POD_NOT_AUTHORIZED",
            "The point of diversion is no longer AUTHORIZED.",
        )

    start_dt, end_dt = _window(lease)
    now = clock.now()
    if not (start_dt <= now < end_dt):
        raise ApiError(
            "ERR_LEASE_WINDOW_TIMING",
            "The lease may only be activated inside its window [%s, %s)."
            % (lease["lease_start_date"], lease["lease_end_date"]),
        )

    lease["status"] = "ACTIVE"
    db.touch(lease)
    _refresh_after_lease_move(lease)
    return response.object_response(serialize.lease_assignment(lease))


@bp.route("/lease-assignments/<lid>/resume", methods=["POST"])
def resume_lease(lid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    lease = common.get_lease(lid)
    validate.get_body(required=False)

    if lease["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUSPENDED lease may be resumed (status is %s)." % lease["status"],
        )

    right = db.water_rights.get(lease["water_right_id"])
    if right is not None:
        derive.recompute_right(right)
        if right["status"] not in LEASABLE_RIGHT_STATUSES:
            raise ApiError(
                "ERR_RIGHT_NOT_TRANSFERABLE",
                "The backing right is %s." % right["status"],
            )

    start_dt, end_dt = _window(lease)
    now = clock.now()
    if not (start_dt <= now < end_dt):
        raise ApiError(
            "ERR_LEASE_WINDOW_TIMING",
            "The lease window [%s, %s) is not current."
            % (lease["lease_start_date"], lease["lease_end_date"]),
        )

    lease["status"] = "ACTIVE"
    db.touch(lease)
    _refresh_after_lease_move(lease)
    return response.object_response(serialize.lease_assignment(lease))


@bp.route("/lease-assignments/<lid>/complete", methods=["POST"])
def complete_lease(lid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    lease = common.get_lease(lid)
    validate.get_body(required=False)

    if lease["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE lease may be completed (status is %s)." % lease["status"],
        )

    start_dt, end_dt = _window(lease)
    if clock.now() < end_dt:
        raise ApiError(
            "ERR_LEASE_WINDOW_TIMING",
            "The lease runs until %s." % lease["lease_end_date"],
        )

    lease["status"] = "COMPLETED"
    lease["used_af"] = calc.q2(lease["requested_af"])
    lease["settlement_credit_af"] = ZERO2
    db.touch(lease)
    _refresh_after_lease_move(lease)
    return response.object_response(serialize.lease_assignment(lease))


@bp.route("/lease-assignments/<lid>/cancel", methods=["POST"])
def cancel_lease(lid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )
    lease = common.get_lease(lid)
    middleware.require_owner(caller, common.lease_owner(lease))

    body = validate.get_body()
    validate.req_str(body, "cancellation_reason", min_len=1, max_len=500)

    if lease["status"] not in derive.LEASE_LIVE_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A lease in status %s can no longer be cancelled." % lease["status"],
        )

    start_dt, end_dt = _window(lease)
    if lease["status"] == "ACTIVE" and clock.now() >= end_dt:
        raise ApiError(
            "ERR_LEASE_WINDOW_TIMING",
            "The lease term ended on %s; complete it instead."
            % lease["lease_end_date"],
        )

    cascades.settle_lease(lease, lease["status"])
    lease["status"] = "CANCELLED"
    db.touch(lease)
    _refresh_after_lease_move(lease)
    return response.object_response(serialize.lease_assignment(lease))
