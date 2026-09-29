from decimal import Decimal

from flask import Blueprint

import auth
import clock
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("env", __name__)
ZERO = Decimal("0")
DESTINATIONS = ["LANDFILL", "LAND_APPLICATION", "FUEL"]
SOURCE_KINDS = ["PULP_REJECT", "DEINK_SLUDGE", "MACHINE_BROKE", "TRANSITION_WASTE"]
DISPOSITIONS = ["PENDING", "MANIFESTED", "REPULPED"]


# ------------------------------------------------------------- permits ---
@bp.post("/effluent-permits")
def create_permit():
    auth.require_roles("EnvironmentalOfficer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "permit_number": shape.get_str(data, "permit_number", min_len=1, max_len=40),
        "bod_limit_kg_per_day": shape.get_num(data, "bod_limit_kg_per_day", exclusive_min=0, places=2),
        "tss_limit_kg_per_day": shape.get_num(data, "tss_limit_kg_per_day", exclusive_min=0, places=2),
        "flow_limit_m3_per_day": shape.get_num(data, "flow_limit_m3_per_day", exclusive_min=0, places=2),
        "rolling_window_days": shape.get_int(data, "rolling_window_days", required=False,
                                             minimum=7, maximum=30, default=30),
        "rolling_bod_kg_per_day": float(q(ZERO, 3)),
        "rolling_tss_kg_per_day": float(q(ZERO, 3)),
        "exceedance_day_count": 0,
        "compliance_posture": "COMPLIANT",
        "posture_changed_at": None,
    }
    common.unique_or_conflict("effluent_permits", "permit_number", row["permit_number"])
    store.insert("effluent_permits", row)
    return response.ok(common.view(row), 201)


@bp.get("/effluent-permits/<pid>")
def get_permit(pid):
    auth.require_roles("EnvironmentalOfficer", "MillPlanner", "MachineOperator")
    return response.ok(common.view(common.need("effluent_permits", pid, "ERR_PERMIT_NOT_FOUND")))


# ------------------------------------------------------------ readings ---
@bp.post("/effluent-permits/<pid>/readings")
def log_reading(pid):
    auth.require_roles("EnvironmentalOfficer")
    permit = common.need("effluent_permits", pid, "ERR_PERMIT_NOT_FOUND")
    data = shape.body()
    shape.reject_unexpected_version(data)
    reading_date = shape.get_str(data, "reading_date", pattern=r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    flow = shape.get_num(data, "flow_m3", minimum=0, places=2)
    bod = shape.get_num(data, "bod_kg", minimum=0, places=2)
    tss = shape.get_num(data, "tss_kg", minimum=0, places=2)
    for r in store.all_rows("effluent_readings"):
        if r["permit_id"] == permit["id"] and not r["voided"] \
                and r["reading_date"] == reading_date:
            raise err("ERR_DUPLICATE_KEY", "a non-voided reading already exists for that date")
    if reading_date > clock.now().date().isoformat():
        raise err("ERR_DATE_OUT_OF_RANGE", "reading_date is later than the logical clock's date")
    row = {
        "permit_id": permit["id"],
        "reading_date": reading_date,
        "flow_m3": flow,
        "bod_kg": bod,
        "tss_kg": tss,
        "logged_by_user_id": auth.user_id(),
        "voided": False,
    }
    store.insert("effluent_readings", row)
    common.recompute_permit(permit)
    return response.ok(common.view(row), 201)


@bp.get("/effluent-permits/<pid>/readings")
def list_permit_readings(pid):
    auth.require_roles("EnvironmentalOfficer", "MillPlanner")
    permit = common.need("effluent_permits", pid, "ERR_PERMIT_NOT_FOUND")
    limit, offset = shape.pagination()
    rows = common.filtered("effluent_readings", {"voided": "voided"},
                           extra=lambda r: r["permit_id"] == permit["id"])
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.get("/effluent-readings/<rid>")
def get_reading(rid):
    auth.require_roles("EnvironmentalOfficer", "MillPlanner")
    return response.ok(common.view(common.need("effluent_readings", rid, "ERR_ENV_RECORD_NOT_FOUND")))


@bp.post("/effluent-readings/<rid>/void")
def void_reading(rid):
    auth.require_roles("EnvironmentalOfficer")
    reading = common.need("effluent_readings", rid, "ERR_ENV_RECORD_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if reading["voided"]:
        raise err("ERR_ENV_RECORD_INVALID_STATE", "reading is already voided")
    reading["voided"] = True
    store.touch("effluent_readings", reading)
    permit = store.get("effluent_permits", reading["permit_id"])
    if permit is not None:
        common.recompute_permit(permit)
    return response.ok(common.view(reading))


# ----------------------------------------------------- sludge manifests ---
def _posture_is_exceedance():
    for p in store.all_rows("effluent_permits"):
        if p["compliance_posture"] == "EXCEEDANCE":
            return True
    return False


@bp.post("/sludge-manifests")
def create_manifest():
    auth.require_roles("EnvironmentalOfficer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    number = shape.get_str(data, "manifest_number", min_len=1, max_len=40)
    destination = shape.get_enum(data, "destination", DESTINATIONS)
    ids = shape.get_list(data, "reject_stream_ids", 1, 20)
    seen = set()
    for i, entry in enumerate(ids):
        if not isinstance(entry, str):
            raise err("ERR_VALIDATION", "reject_stream_ids[%d] must be a string" % i)
        if entry in seen:
            raise err("ERR_VALIDATION", "reject_stream_ids entries must be unique")
        seen.add(entry)
    rows = []
    for entry in ids:
        rs = store.get("reject_streams", entry)
        if rs is None or rs.get("reversal_of_id") is not None:
            raise err("ERR_REJECT_STREAM_REFERENCE_INVALID",
                      "reject_stream_ids entry does not resolve to an ordinary solids row")
        rows.append(rs)
    if destination == "LAND_APPLICATION" and _posture_is_exceedance():
        raise err("ERR_LAND_APPLICATION_BARRED",
                  "LAND_APPLICATION is barred while the permit posture is EXCEEDANCE")
    common.unique_or_conflict("sludge_manifests", "manifest_number", number)
    total = ZERO
    for rs in rows:
        total += D(rs["dry_solids_tons"])
    row = {
        "manifest_number": number,
        "destination": destination,
        "reject_stream_ids": list(ids),
        "total_dry_solids_tons": float(q(total, 3)),
        "prepared_by_user_id": auth.user_id(),
        "signed_by_user_id": None,
        "status": "DRAFT",
    }
    store.insert("sludge_manifests", row)
    return response.ok(common.view(row), 201)


@bp.get("/sludge-manifests/<mid>")
def get_manifest(mid):
    auth.require_roles("EnvironmentalOfficer", "MillPlanner")
    return response.ok(common.view(common.need("sludge_manifests", mid, "ERR_ENV_RECORD_NOT_FOUND")))


@bp.post("/sludge-manifests/<mid>/sign")
def sign_manifest(mid):
    auth.require_roles("EnvironmentalOfficer")
    manifest = common.need("sludge_manifests", mid, "ERR_ENV_RECORD_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if manifest["status"] != "DRAFT":
        raise err("ERR_ENV_RECORD_INVALID_STATE", "manifest is not DRAFT")
    actor = auth.user_id()
    if actor == manifest["prepared_by_user_id"]:
        raise err("ERR_SOD_SAME_ENV_OFFICER", "the preparing officer may not sign the manifest")
    permit = common.the_permit()
    if permit is not None:
        res = common.permit_window_readings(permit)
        for r in res.get("window", []):
            if r.get("logged_by_user_id") == actor:
                raise err("ERR_SOD_SAME_ENV_OFFICER",
                          "the signer logged a reading inside the current rolling window")
    if manifest["destination"] == "LAND_APPLICATION" and _posture_is_exceedance():
        raise err("ERR_LAND_APPLICATION_BARRED",
                  "LAND_APPLICATION is barred while the permit posture is EXCEEDANCE")
    manifest["signed_by_user_id"] = actor
    manifest["status"] = "SIGNED"
    store.touch("sludge_manifests", manifest)
    for entry in manifest["reject_stream_ids"]:
        rs = store.get("reject_streams", entry)
        if rs is not None:
            rs["manifest_id"] = manifest["id"]
            rs["disposition"] = "MANIFESTED"
    return response.ok(common.view(manifest))


@bp.post("/sludge-manifests/<mid>/void")
def void_manifest(mid):
    auth.require_roles("EnvironmentalOfficer")
    manifest = common.need("sludge_manifests", mid, "ERR_ENV_RECORD_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if manifest["status"] not in ("DRAFT", "SIGNED"):
        raise err("ERR_ENV_RECORD_INVALID_STATE", "manifest is not DRAFT or SIGNED")
    manifest["status"] = "VOIDED"
    store.touch("sludge_manifests", manifest)
    for entry in manifest["reject_stream_ids"]:
        rs = store.get("reject_streams", entry)
        if rs is not None and rs.get("manifest_id") == manifest["id"]:
            rs["manifest_id"] = None
            rs["disposition"] = "PENDING"
    return response.ok(common.view(manifest))


# ------------------------------------------------------ solids ledger ---
@bp.get("/reject-streams/summary")
def reject_summary():
    auth.require_roles("EnvironmentalOfficer", "MillPlanner")
    gross = ZERO
    reversed_ = ZERO
    manifested = ZERO
    unmanifested = ZERO
    repulped = ZERO
    for rs in store.all_rows("reject_streams"):
        tons = D(rs["dry_solids_tons"])
        if rs.get("reversal_of_id") is not None:
            reversed_ += tons
            continue
        gross += tons
        if rs["disposition"] == "MANIFESTED":
            manifested += tons
        elif rs["disposition"] == "PENDING":
            unmanifested += tons
        elif rs["disposition"] == "REPULPED":
            repulped += tons
    gross = q(gross, 3)
    reversed_ = q(reversed_, 3)
    return response.ok({
        "gross_solids_tons": float(gross),
        "reversed_solids_tons": float(reversed_),
        "net_solids_tons": float(q(gross - reversed_, 3)),
        "manifested_dry_solids_tons": float(q(manifested, 3)),
        "unmanifested_dry_solids_tons": float(q(unmanifested, 3)),
        "repulped_dry_solids_tons": float(q(repulped, 3)),
    })


@bp.get("/reject-streams/<rid>")
def get_reject_stream(rid):
    auth.require_roles("EnvironmentalOfficer", "MillPlanner", "QualityLab")
    return response.ok(common.view(common.need("reject_streams", rid, "ERR_ENV_RECORD_NOT_FOUND")))


@bp.get("/reject-streams")
def list_reject_streams():
    auth.require_roles("EnvironmentalOfficer", "MillPlanner", "QualityLab")
    limit, offset = shape.pagination()
    rows = common.filtered("reject_streams", {
        "source_ref_id": "source_ref_id",
        "manifest_id": "manifest_id",
        "reversal_of_id": "reversal_of_id",
        "source_kind": "source_kind",
        "disposition": "disposition",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/reject-streams/<rid>/reverse")
def reverse_reject_stream(rid):
    auth.require_roles("EnvironmentalOfficer")
    rs = common.need("reject_streams", rid, "ERR_ENV_RECORD_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if rs["disposition"] != "PENDING":
        raise err("ERR_ENV_RECORD_INVALID_STATE", "solids row disposition is not PENDING")
    reversal = store.insert("reject_streams", {
        "source_kind": rs["source_kind"],
        "source_ref_id": rs["source_ref_id"],
        "dry_solids_tons": float(q(D(rs["dry_solids_tons"]), 3)),
        "disposition": "PENDING",
        "manifest_id": None,
        "reversal_of_id": rs["id"],
    })
    rs["disposition"] = "REPULPED"
    return response.ok(common.view(reversal), 201)
