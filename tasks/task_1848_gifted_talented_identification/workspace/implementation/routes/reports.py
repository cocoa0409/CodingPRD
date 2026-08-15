"""Disproportionality report (computed read)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_CYCLE_STATE, ERR_INVALID_REQUEST
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.common import get_or_404

bp = Blueprint("reports", __name__)

BAND_RANGES = {
    "ELEMENTARY": (0, 5),
    "MIDDLE": (6, 8),
    "HIGH": (9, 12),
}

# deterministic group ordering for output
GROUP_ORDER = [
    "AMERICAN_INDIAN",
    "ASIAN",
    "BLACK",
    "HISPANIC",
    "WHITE",
    "MULTIRACIAL",
    "PACIFIC_ISLANDER",
]

FLAG_THRESHOLD = Decimal("0.800")
MIN_CELL = 10

INTERIM_STATUSES = {"IDENTIFIED", "AWAITING_COMMITTEE", "APPEAL_PENDING"}
FINAL_STATUSES = {"IDENTIFIED"}


@bp.route("/gifted/screening-cycles/<cid>/disproportionality-report", methods=["GET"])
def disproportionality_report(cid):
    require_roles(*ALL_ROLES)
    cycle = get_or_404(db.screening_cycles, cid, "screening cycle")

    variant = request.args.get("variant", "INTERIM")
    if variant not in {"INTERIM", "FINAL"}:
        raise ApiError(ERR_INVALID_REQUEST, "variant must be INTERIM or FINAL", 400)

    # availability gates
    if variant == "INTERIM":
        if cycle["status"] not in {"REVIEW", "FINALIZED"}:
            raise ApiError(ERR_INVALID_CYCLE_STATE, "INTERIM report requires cycle REVIEW or FINALIZED", 409)
    else:
        if cycle["status"] != "FINALIZED":
            raise ApiError(ERR_INVALID_CYCLE_STATE, "FINAL report requires cycle FINALIZED", 409)

    lo, hi = BAND_RANGES[cycle["grade_band"]]
    in_scope = [s for s in db.students.values() if lo <= s["grade_level"] <= hi]

    # enrolled per group
    enrolled = {}
    for s in in_scope:
        enrolled[s["demographic_group"]] = enrolled.get(s["demographic_group"], 0) + 1

    # identified per group (a student counts if they hold a qualifying case
    # in this cycle)
    counted_statuses = INTERIM_STATUSES if variant == "INTERIM" else FINAL_STATUSES
    identified_student_ids = set()
    for c in db.gifted_cases.values():
        if c["cycle_id"] == cid and c["status"] in counted_statuses:
            identified_student_ids.add(c["student_id"])

    identified = {}
    for s in in_scope:
        if s["id"] in identified_student_ids:
            identified[s["demographic_group"]] = identified.get(s["demographic_group"], 0) + 1

    # omit zero-enrolled groups entirely
    groups = [g for g in enrolled if enrolled[g] > 0]

    # reference group: largest enrolled; tie-break name ASC
    reference_group = None
    if groups:
        reference_group = sorted(groups, key=lambda g: (-enrolled[g], g))[0]

    def rate(g):
        if enrolled[g] == 0:
            return Decimal("0")
        r = Decimal(identified.get(g, 0)) / Decimal(enrolled[g])
        return r.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    rates = {g: rate(g) for g in groups}
    rate_ref = rates[reference_group] if reference_group else Decimal("0")

    group_metrics = []
    flagged_groups = []
    total_identified = 0
    for g in sorted(groups, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99):
        idg = identified.get(g, 0)
        total_identified += idg
        if rate_ref == 0:
            ratio = None
        else:
            ratio = float((rates[g] / rate_ref).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
        metric = {
            "demographic_group": g,
            "enrolled": enrolled[g],
            "identified": idg,
            "identification_rate": float(rates[g]),
            "risk_ratio": ratio,
        }
        is_flagged = False
        if ratio is not None and Decimal(str(ratio)) < FLAG_THRESHOLD and enrolled[g] >= MIN_CELL:
            is_flagged = True
            flagged_groups.append(g)
        metric["flagged"] = is_flagged
        group_metrics.append(metric)

    payload = {
        "cycle_id": cid,
        "variant": variant,
        "reference_group": reference_group,
        "total_identified": total_identified,
        "group_metrics": group_metrics,
        "flagged_groups": flagged_groups,
    }
    return success_object(payload, 200)
