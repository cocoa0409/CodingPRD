"""Design values and attainment determination."""
from flask import Blueprint

import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_not_terminal, ensure_from_state, get_design_value,
                           get_pollutant, get_site)
from services import compute as K
from services import serialize as S

bp = Blueprint("design_values", __name__)


@bp.post("/design-values")
@require("ProgramManager")
def compute_design_value():
    data = V.body()
    site_id = V.req_id(data, "site_id")
    pollutant_id = V.req_id(data, "pollutant_id")
    period_end_year = V.req_int(data, "period_end_year", lo=2000, hi=2100)
    variant = V.req_enum(data, "variant", C.DESIGN_VALUE_VARIANTS)
    expected = V.req_int(data, "expected_monitoring_site_version")
    site = get_site(site_id)
    pollutant = get_pollutant(pollutant_id)
    if expected != site["version"]:
        raise ApiError("ERR_STALE_SITE_VERSION",
                       "expected_monitoring_site_version %d does not match the site's current "
                       "version %d." % (expected, site["version"]))
    # The primary-sampler gate is evaluated before the already-finalized gate.
    primary = K.primary_monitor_selection(site_id, pollutant_id)
    if primary is None:
        raise ApiError("ERR_PRIMARY_MONITOR_MISSING",
                       "No eligible primary sampler exists at this site for this pollutant.")
    for row in store.design_values.values():
        if (row["site_id"] == site_id and row["pollutant_id"] == pollutant_id
                and row["period_end_year"] == period_end_year and row["variant"] == variant
                and row["status"] == "FINAL"):
            raise ApiError("ERR_DESIGN_VALUE_FINALIZED",
                           "A design value for this key has already been finalized.")
    computed = K.design_value_computation(pollutant, primary["id"], period_end_year, variant)
    rec = new_record()
    rec.update({
        "site_id": site_id,
        "pollutant_id": pollutant_id,
        "primary_monitor_id": primary["id"],
        "period_end_year": period_end_year,
        "variant": variant,
        "status": "PROVISIONAL",
        "stale_reason": None,
        "finalized_by_user_id": None,
    })
    rec.update(computed)
    # Any earlier still-provisional row for the same key is retired.
    for row in store.design_values.values():
        if row["id"] == rec["id"]:
            continue
        if (row["site_id"] == site_id and row["pollutant_id"] == pollutant_id
                and row["period_end_year"] == period_end_year and row["variant"] == variant
                and row["status"] == "PROVISIONAL"):
            row["status"] = "SUPERSEDED"
            row["stale_reason"] = "RECOMPUTED"
            touch(row)
    store.design_values[rec["id"]] = rec
    touch(site)
    site["current_attainment_status"] = K.current_attainment_status(site_id)
    return response.object_response(S.design_value(rec), 201)


@bp.post("/design-values/<design_value_id>/finalize")
@require("EpaRegionalReviewer")
def finalize_design_value(design_value_id):
    data = V.body()
    V.opt_string(data, "finalization_note")
    row = get_design_value(design_value_id)
    ensure_not_terminal(row["status"], C.DESIGN_VALUE_TERMINAL, "design value")
    ensure_from_state(row["status"], ("PROVISIONAL",), "design value")
    pollutant = store.pollutants.get(row["pollutant_id"])
    required_years = pollutant["design_value_years"] if pollutant is not None else 3
    if row["complete_year_count"] != required_years:
        raise ApiError("ERR_DESIGN_VALUE_INCOMPLETE",
                       "The design value rests on %d complete years; %d are required."
                       % (row["complete_year_count"], required_years))
    row["status"] = "FINAL"
    row["finalized_by_user_id"] = actor()
    touch(row)
    site = store.sites.get(row["site_id"])
    if site is not None:
        site["current_attainment_status"] = K.current_attainment_status(site["id"])
        touch(site)
    return response.object_response(S.design_value(row))


@bp.get("/design-values/<design_value_id>")
@require(*ALL_ROLES)
def read_design_value(design_value_id):
    return response.object_response(S.design_value(get_design_value(design_value_id)))


@bp.get("/design-values")
@require(*ALL_ROLES)
def list_design_values():
    limit, offset = V.pagination()
    site_id = V.q_string("site_id")
    pollutant_id = V.q_string("pollutant_id")
    primary_monitor_id = V.q_string("primary_monitor_id")
    period_end_year = V.q_int("period_end_year")
    variant = V.q_enum("variant", C.DESIGN_VALUE_VARIANTS)
    status = V.q_enum("status", C.DESIGN_VALUE_STATUSES)
    rows = list(store.design_values.values())
    if site_id is not None:
        rows = [d for d in rows if d["site_id"] == site_id]
    if pollutant_id is not None:
        rows = [d for d in rows if d["pollutant_id"] == pollutant_id]
    if primary_monitor_id is not None:
        rows = [d for d in rows if d["primary_monitor_id"] == primary_monitor_id]
    if period_end_year is not None:
        rows = [d for d in rows if d["period_end_year"] == period_end_year]
    if variant is not None:
        rows = [d for d in rows if d["variant"] == variant]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.design_value(d) for d in page], pagination=meta)
