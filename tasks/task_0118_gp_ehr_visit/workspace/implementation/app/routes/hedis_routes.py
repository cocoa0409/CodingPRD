"""HEDIS endpoints: get measurements (final or YTD); POST recompute."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_CLINIC_ADMIN, ROLE_PROVIDER, require_roles
from ..errors import err_invalid_input
from ..helpers import assert_array, assert_integer, require_json_object
from ..responses import listing
from ..services.hedis import (
    HEDIS_MEASURES,
    recompute_final,
    recompute_provisional_ytd,
)
from ..services.lookups import get_patient
from ..services.serialize import hedis_to_dict
from ..store import store

bp = Blueprint("hedis_routes", __name__)


@bp.route("/hedis/measurements/<patient_id>/<int:year>", methods=["GET"])
@require_roles(ROLE_PROVIDER, ROLE_CLINIC_ADMIN)
def get_hedis(patient_id: str, year: int, **_kwargs):
    s = store()
    with s.lock:
        patient = get_patient(patient_id)
        as_of = request.args.get("as_of")
        if as_of == "YTD":
            rows = recompute_provisional_ytd(patient_id, year)
            out = []
            for r in rows:
                # provisional doesn't have id; emit with empty string id
                out.append({
                    "id": r["id"],
                    "patient_id": r["patient_id"],
                    "measure_id": r["measure_id"],
                    "measurement_year": r["measurement_year"],
                    "in_denominator": r["in_denominator"],
                    "in_numerator": r["in_numerator"],
                    "computed_at": _iso_from(r["computed_at"]),
                })
            return listing(out, len(out), limit=len(out) or 1, offset=0)
        else:
            # Final: read stored snapshots; if none for this year, return empty list
            rows = [
                r for r in s.hedis_measurements.values()
                if r["patient_id"] == patient_id and r["measurement_year"] == year
            ]
            rows.sort(key=lambda r: r["measure_id"])
            out = [hedis_to_dict(r) for r in rows]
            return listing(out, len(out), limit=len(out) or 1, offset=0)


@bp.route("/hedis/recompute", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def recompute_hedis(**_kwargs):
    body = require_json_object()
    year = assert_integer(body.get("year"), "year", minimum=1000, maximum=9999)
    patient_ids = body.get("patient_ids")
    if patient_ids is None:
        s = store()
        patient_ids = list(s.patients.keys())
    else:
        patient_ids = assert_array(patient_ids, "patient_ids")
        for pid in patient_ids:
            if not isinstance(pid, str):
                raise err_invalid_input("patient_ids entries must be strings")
    s = store()
    out = []
    with s.lock:
        for pid in patient_ids:
            if pid not in s.patients:
                continue
            rows = recompute_final(pid, year)
            for r in rows:
                out.append(hedis_to_dict(r))
    return listing(out, len(out), limit=len(out) or 1, offset=0)


def _iso_from(dt):
    from ..clock import iso_format
    return iso_format(dt)
