"""Quarter close and the deterministic logical clock (PRD 3.9, 2.6)."""

from flask import Blueprint

import db
import response
import validate as V
from db import S, touch
from errors import ApiError
from middleware import ALL_ROLES, ROLE_FINANCE, ROLE_MANAGER, guard
from services import domain

bp = Blueprint("ops", __name__)

EXPIRY_REJECT_STATES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "REVISION_REQUESTED",
                        "SAMPLE_REQUESTED", "SAMPLE_PASSED")


def _ordered(rows):
    return sorted(rows, key=lambda r: r["created_at"])


def _expire_agreement(agreement):
    agreement["contract_status"] = "EXPIRED"
    final = domain.assess_final_shortfall(agreement)
    agreement["mg_final_shortfall_cents"] = final
    agreement["mg_accrued_shortfall_cents"] = final
    for sub in _ordered(domain.submissions_of(agreement["id"])):
        if sub["status"] in EXPIRY_REJECT_STATES:
            sub["status"] = "REJECTED"
            sub["rejection_reason"] = "AGREEMENT_EXPIRED"
            touch(sub)
    approved = domain.compute_approved_sku_count(agreement)
    channels = domain.compute_authorized_channel_count(agreement)
    agreement["approved_sku_count"] = approved
    agreement["authorized_channel_count"] = channels
    agreement["distribution_ready"] = domain.compute_distribution_ready(
        agreement, approved, channels)
    touch(agreement)


@bp.post("/licensing/ops/quarter-close")
def quarter_close():
    ctx = guard([ROLE_MANAGER, ROLE_FINANCE])
    as_of_quarter = V.req_quarter(ctx.body, "as_of_quarter")

    if as_of_quarter != db.current_quarter() or as_of_quarter in S.closed_quarters:
        raise ApiError("ERR_QUARTER_ALREADY_CLOSED")

    quarter_end = db.quarter_end_date(as_of_quarter)

    # one: expiry
    agreements_expired = 0
    for agreement in _ordered(S.agreements.values()):
        if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if db.parse_date(agreement["term_end_date"]) < quarter_end:
            _expire_agreement(agreement)
            agreements_expired += 1

    # two: interim minimum-guarantee shortfalls
    shortfalls_assessed = 0
    for agreement in _ordered(S.agreements.values()):
        if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        domain.assess_interim_shortfall(agreement, as_of_quarter)
        shortfalls_assessed += 1

    # three: rolling risk index for every ACTIVE licensee
    risk_indexes_recomputed = 0
    for licensee in _ordered(S.licensees.values()):
        if licensee["status"] != "ACTIVE":
            continue
        domain.refresh_risk_index(licensee, as_of_quarter)
        risk_indexes_recomputed += 1

    # four and five: posture transitions and the review holds they imply
    postures_changed = 0
    submissions_held = 0
    submissions_released = 0
    for agreement in _ordered(S.agreements.values()):
        changed, held, released = domain.posture_recompute(agreement, as_of_quarter)
        if changed:
            postures_changed += 1
        submissions_held += held
        submissions_released += released

    S.closed_quarters.add(as_of_quarter)

    return response.ok({
        "as_of_quarter": as_of_quarter,
        "agreements_expired": agreements_expired,
        "shortfalls_assessed": shortfalls_assessed,
        "risk_indexes_recomputed": risk_indexes_recomputed,
        "postures_changed": postures_changed,
        "submissions_held": submissions_held,
        "submissions_released": submissions_released,
    })


@bp.post("/licensing/_clock/set_current_utc")
def set_clock():
    ctx = guard(ALL_ROLES)
    moment = V.req_instant(ctx.body, "current_utc")
    if moment < S.clock:
        raise ApiError("ERR_CLOCK_BACKWARD")
    S.clock = moment
    return response.ok({"current_utc": db.iso(S.clock)})
