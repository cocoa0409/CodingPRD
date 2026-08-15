"""Capacity report endpoint."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from services import domain
from util import get_json_body, require_string
from flask import request

bp = Blueprint("reports", __name__)


@bp.route("/ucc/reports/capacity", methods=["GET"])
@require_roles("ClinicalDirector")
def capacity_report(_user_id: str, _role: str):
    # academic_term from query string
    academic_term = request.args.get("academic_term")
    if academic_term is None or academic_term == "":
        raise_err(ERR_INVALID_REQUEST, "academic_term query parameter is required")

    # delivered_minutes: sum of duration_minutes over COMPLETED sessions whose
    # episode's academic_term matches.
    delivered = 0
    for s in db.sessions.values():
        if s.get("status") != "COMPLETED":
            continue
        ep = db.episodes.get(s.get("episode_id"))
        if ep is None:
            continue
        if ep.get("academic_term") != academic_term:
            continue
        delivered += int(s.get("duration_minutes", 0))

    # bookable_minutes: sum over ACTIVE counselors of
    # weekly_individual_capacity * 60 * WEEKS_IN_TERM.
    bookable = 0
    for c in db.counselors.values():
        if not c.get("active", True):
            continue
        bookable += int(c.get("weekly_individual_capacity", 0)) * 60 * domain.WEEKS_IN_TERM

    if bookable > 0:
        util = (Decimal(10000) * Decimal(delivered) / Decimal(bookable)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        utilization_bps = int(util)
    else:
        utilization_bps = 0

    # outcomes_delta: mean over episodes CLOSED in the term that have both
    # BASELINE and DISCHARGE OutcomeMeasures, computed per instrument then
    # averaged across instruments. Report to 2 decimals ROUND_HALF_UP.
    # Collect per (episode_id, instrument): discharge - baseline.
    deltas = []
    closed_episodes = [
        e for e in db.episodes.values()
        if e.get("academic_term") == academic_term and e.get("status") == "CLOSED"
    ]
    for ep in closed_episodes:
        per_instrument = {}
        for om in db.outcome_measures.values():
            if om.get("episode_id") != ep["id"]:
                continue
            per_instrument.setdefault(om.get("instrument"), {})[om.get("phase")] = int(om.get("score", 0))
        for instrument, phases in per_instrument.items():
            if "BASELINE" in phases and "DISCHARGE" in phases:
                deltas.append(phases["DISCHARGE"] - phases["BASELINE"])
    if deltas:
        mean = Decimal(sum(deltas)) / Decimal(len(deltas))
        outcomes_delta = float(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        outcomes_delta = 0.0

    return success_object({
        "academic_term": academic_term,
        "delivered_minutes": delivered,
        "bookable_minutes": bookable,
        "utilization_bps": utilization_bps,
        "outcomes_delta": outcomes_delta,
    })
