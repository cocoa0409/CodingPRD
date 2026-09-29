"""Earn-out tranches: a conserved cents ledger with two calculation variants (PRD 3.9)."""

from flask import Blueprint, g

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError, invalid
from services import calc, derive, uow

bp = Blueprint("earnout", __name__)

READ_ROLES = (
    config.ROLE_FINANCE_CONTROLLER,
    config.ROLE_DEAL_COUNSEL,
    config.ROLE_INTEGRATION_LEAD,
)


def _require_tranche_status(tranche, expected):
    if tranche["status"] != expected:
        raise ApiError(
            "ERR_INVALID_TRANCHE_STATE",
            "The tranche must be in %s for this operation." % expected,
        )


def _stamp(tranche, result):
    tranche["variant_applied"] = result["variant_applied"]
    tranche["lag_holdback_cents"] = result["lag_holdback_cents"]
    tranche["management_fee_cents"] = result["management_fee_cents"]
    tranche["adjusted_ebitda_cents"] = result["adjusted_ebitda_cents"]
    tranche["growth_bps"] = result["growth_bps"]
    tranche["multiple_bps"] = result["multiple_bps"]


@bp.post("/earnout-tranches")
@support.transactional
def create_tranche():
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    data = payload.body()
    affiliation = support.load_fk(data, "affiliation_id", "affiliations")
    payload.string(data, "affiliation_id")
    period_label = payload.string(data, "period_label")
    measurement_start = payload.timestamp(data, "measurement_start")
    measurement_end = payload.timestamp(data, "measurement_end")
    if measurement_end <= measurement_start:
        raise invalid("'measurement_end' must be strictly after 'measurement_start'.")
    expected_affiliation_version = payload.integer(
        data, "expected_affiliation_version"
    )
    support.require_occ_affiliation(affiliation, expected_affiliation_version)

    for existing in derive.tranches_of_affiliation(affiliation["id"]):
        if existing["status"] == "CLAWED_BACK":
            continue
        if (
            measurement_start < existing["measurement_end"]
            and existing["measurement_start"] < measurement_end
        ):
            raise ApiError(
                "ERR_MEASUREMENT_PERIOD_OVERLAP",
                "The requested measurement period overlaps an existing tranche.",
            )

    row = db.insert(
        "earnout_tranches",
        {
            "affiliation_id": affiliation["id"],
            "period_label": period_label,
            "measurement_start": measurement_start,
            "measurement_end": measurement_end,
            "status": "PROJECTED",
            "variant_applied": None,
            "reported_net_collections_cents": None,
            "reported_expenses_cents": None,
            "annualized_net_collections_cents": None,
            "annualized_expenses_cents": None,
            "final_net_collections_cents": None,
            "final_expenses_cents": None,
            "lag_holdback_cents": None,
            "management_fee_cents": None,
            "adjusted_ebitda_cents": None,
            "growth_bps": None,
            "multiple_bps": None,
            "reserved_cents": 0,
            "awarded_cents": 0,
            "clawed_back_cents": 0,
            "reserved_by_user_id": None,
            "settled_by_user_id": None,
        },
    )
    uow.touch(affiliation)
    return "earnout_tranches", row, 201


@bp.get("/earnout-tranches/<earnout_tranche_id>")
def get_tranche(earnout_tranche_id):
    middleware.authorize(READ_ROLES)
    row = support.load("earnout_tranches", earnout_tranche_id)
    return support.read_one("earnout_tranches", row)


@bp.get("/earnout-tranches")
def list_tranches():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("earnout_tranches")
    rows = support.filter_rows(
        rows, "affiliation_id", payload.filter_value("affiliation_id")
    )
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("earnout_tranches", rows)


@bp.post("/earnout-tranches/<earnout_tranche_id>/reserve")
@support.transactional
def reserve_tranche(earnout_tranche_id):
    user_id, _ = middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    tranche = support.load("earnout_tranches", earnout_tranche_id)
    data = payload.body()
    reported_net = payload.integer(data, "reported_net_collections_cents", minimum=0)
    reported_expenses = payload.integer(data, "reported_expenses_cents", minimum=0)

    affiliation = db.get("affiliations", tranche["affiliation_id"])
    if (
        affiliation["status"] != "CLOSED"
        or affiliation["earnout_measurement_state"] != "OPEN"
    ):
        raise ApiError(
            "ERR_INVALID_AFFILIATION_STATE",
            "Reservation requires a closed affiliation with an open measurement window.",
        )
    _require_tranche_status(tranche, "PROJECTED")

    days_elapsed = clock.whole_days_between(
        tranche["measurement_start"], clock.now()
    )
    if days_elapsed <= 0:
        raise ApiError(
            "ERR_MEASUREMENT_PERIOD_NOT_STARTED",
            "The measurement period has not elapsed by at least one whole day.",
        )

    result = calc.earnout_payout(
        "PROVISIONAL",
        reported_net,
        reported_expenses,
        affiliation["baseline_ebitda_cents"],
        days_elapsed,
    )
    if result["payout_cents"] > derive.earnout_unallocated_cents(affiliation):
        raise ApiError(
            "ERR_EARNOUT_POOL_EXCEEDED",
            "The computed payout exceeds the unallocated earn-out pool.",
        )

    tranche["reported_net_collections_cents"] = reported_net
    tranche["reported_expenses_cents"] = reported_expenses
    tranche["annualized_net_collections_cents"] = result["net_collections_cents"]
    tranche["annualized_expenses_cents"] = result["expenses_cents"]
    _stamp(tranche, result)
    tranche["status"] = "RESERVED"
    tranche["reserved_cents"] = result["payout_cents"]
    tranche["reserved_by_user_id"] = user_id
    uow.touch(tranche)
    uow.touch(affiliation)
    return "earnout_tranches", tranche, 200


@bp.post("/earnout-tranches/<earnout_tranche_id>/settle")
@support.transactional
def settle_tranche(earnout_tranche_id):
    user_id, _ = middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    tranche = support.load("earnout_tranches", earnout_tranche_id)
    data = payload.body()
    final_net = payload.integer(data, "final_net_collections_cents", minimum=0)
    final_expenses = payload.integer(data, "final_expenses_cents", minimum=0)

    _require_tranche_status(tranche, "RESERVED")
    if user_id == tranche["reserved_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The settling user must differ from the reserving user.",
        )

    affiliation = db.get("affiliations", tranche["affiliation_id"])
    result = calc.earnout_payout(
        "FINAL", final_net, final_expenses, affiliation["baseline_ebitda_cents"]
    )
    available = (
        derive.earnout_unallocated_cents(affiliation) + tranche["reserved_cents"]
    )
    if result["payout_cents"] > available:
        raise ApiError(
            "ERR_EARNOUT_POOL_EXCEEDED",
            "The computed payout exceeds the available earn-out pool.",
        )

    tranche["final_net_collections_cents"] = final_net
    tranche["final_expenses_cents"] = final_expenses
    _stamp(tranche, result)
    tranche["status"] = "SETTLED"
    tranche["awarded_cents"] = result["payout_cents"]
    tranche["reserved_cents"] = 0
    tranche["settled_by_user_id"] = user_id
    uow.touch(tranche)
    uow.touch(affiliation)
    return "earnout_tranches", tranche, 200


@bp.post("/earnout-tranches/<earnout_tranche_id>/claw-back")
@support.transactional
def claw_back_tranche(earnout_tranche_id):
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    tranche = support.load("earnout_tranches", earnout_tranche_id)
    data = payload.body()
    payload.string(data, "clawback_reason")
    affiliation = db.get("affiliations", tranche["affiliation_id"])
    if affiliation["status"] != "CLOSED":
        raise ApiError(
            "ERR_INVALID_AFFILIATION_STATE",
            "Claw-back requires a closed affiliation.",
        )
    _require_tranche_status(tranche, "SETTLED")
    # The awarded cents return to the unallocated pool with zero drift.
    tranche["clawed_back_cents"] = tranche["awarded_cents"]
    tranche["awarded_cents"] = 0
    tranche["status"] = "CLAWED_BACK"
    uow.touch(tranche)
    uow.touch(affiliation)
    return "earnout_tranches", tranche, 200
