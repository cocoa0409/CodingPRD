"""SecretAsset register + ReasonableMeasure routes (PRD §3.1)."""

from flask import Blueprint

from db import all_rows, by_id, created_asc, db, new_record, serialize, touch
from errors import (
    err_grants_remain,
    err_invalid_request,
    err_invalid_state,
    err_measure_evidence,
    err_not_found,
    err_preservation,
    err_sod,
    err_stale_version,
    err_unauthorized_role,
)
from middleware import (
    actor,
    body,
    optional_str,
    require_enum,
    require_field,
    require_int,
    require_roles,
    require_str,
)
from response import ok_list, ok_object
from services import (
    lapse_measure,
    recompute_asset_scores,
    refresh_measure_derived,
    retire_asset_cascade,
)

bp = Blueprint("assets", __name__)

CLASSIFICATIONS = ("INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CROWN_JEWEL")
ASSET_STATUSES = ("DRAFT", "REGISTERED", "SUSPENDED", "RETIRED")
MEASURE_TYPES = ("POLICY", "TRAINING", "PHYSICAL", "CONTRACTUAL", "TECHNICAL")
MEASURE_STATUSES = ("PLANNED", "IMPLEMENTED", "VERIFIED", "LAPSED", "ABANDONED")
POSTURES = ("DEFICIENT", "ADEQUATE", "STRONG")


def _list(rows, filters):
    out = []
    for r in created_asc(rows):
        if all(r.get(k) == v for k, v in filters):
            out.append(serialize(r))
    return out


# ---------------------------------------------------------------------------
# SecretAsset
# ---------------------------------------------------------------------------
@bp.post("/api/assets")
def create_asset():
    _uid, _role = actor()
    require_roles(_role, "IPCounsel")
    data = body()
    rec = new_record(
        "assets",
        {
            "title": require_str(data, "title"),
            "description": require_str(data, "description"),
            "classification": require_enum(data, "classification", CLASSIFICATIONS),
            "owner_department": require_str(data, "owner_department"),
            "exposure_estimate_cents": _nonneg_int(data, "exposure_estimate_cents"),
            "status": "DRAFT",
            "score_operational": 0,
            "score_documentary": 0,
            "protection_posture": "DEFICIENT",
            "active_grant_count": 0,
        },
    )
    return ok_object(serialize(rec), code=201)


def _nonneg_int(data, field):
    val = require_int(data, field)
    if val < 0:
        raise err_invalid_request(f"{field} must be >= 0")
    return val


@bp.get("/api/assets")
def list_assets():
    _uid, _role = actor()
    require_roles(_role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    from flask import request

    filters = []
    for f in ("classification", "status", "protection_posture"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    rows = _list(all_rows("assets"), filters)
    from response import paginate

    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


@bp.get("/api/assets/<rid>")
def get_asset(rid):
    _uid, _role = actor()
    require_roles(_role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    asset = by_id("assets", rid)
    if asset is None:
        raise err_not_found("asset not found")
    return ok_object(serialize(asset))


@bp.patch("/api/assets/<rid>")
def patch_asset(rid):
    """OCC-guarded descriptive update (PRD §2.6): expected_asset_version is
    non-optional; a stale view is the only thing that can reject the write."""
    _uid, _role = actor()
    require_roles(_role, "IPCounsel")
    asset = by_id("assets", rid)
    if asset is None:
        raise err_not_found("asset not found")
    data = body()
    expected = require_field(data, "expected_asset_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_asset_version must be an integer")
    if expected != asset["version"]:
        raise err_stale_version()
    if "title" in data and data["title"] is not None:
        if not isinstance(data["title"], str):
            raise err_invalid_request("title must be a string")
        asset["title"] = data["title"]
    if "description" in data and data["description"] is not None:
        if not isinstance(data["description"], str):
            raise err_invalid_request("description must be a string")
        asset["description"] = data["description"]
    if "classification" in data and data["classification"] is not None:
        if data["classification"] not in CLASSIFICATIONS:
            raise err_invalid_request("classification is invalid")
        asset["classification"] = data["classification"]
    if "exposure_estimate_cents" in data and data["exposure_estimate_cents"] is not None:
        val = data["exposure_estimate_cents"]
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise err_invalid_request("exposure_estimate_cents must be a non-negative integer")
        asset["exposure_estimate_cents"] = val
    touch(asset)
    return ok_object(serialize(asset))


@bp.post("/api/assets/<rid>/state")
def asset_state(rid):
    _uid, _role = actor()
    require_roles(_role, "IPCounsel")
    asset = by_id("assets", rid)
    if asset is None:
        raise err_not_found("asset not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in ASSET_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(ASSET_STATUSES)}")
    cur = asset["status"]
    if to_status == "REGISTERED":
        if cur not in ("DRAFT", "SUSPENDED"):
            raise err_invalid_state(f"Cannot move asset from {cur} to REGISTERED")
        asset["status"] = "REGISTERED"
        touch(asset)
        recompute_asset_scores(asset)
    elif to_status == "SUSPENDED":
        if cur != "REGISTERED":
            raise err_invalid_state(f"Cannot move asset from {cur} to SUSPENDED")
        asset["status"] = "SUSPENDED"
        touch(asset)
    elif to_status == "RETIRED":
        if cur not in ("REGISTERED", "SUSPENDED"):
            raise err_invalid_state(f"Cannot move asset from {cur} to RETIRED")
        _retire_guards(asset)
        asset["status"] = "RETIRED"
        touch(asset)
        retire_asset_cascade(asset)
    else:  # DRAFT is never a valid manual target
        raise err_invalid_state(f"Cannot move asset from {cur} to {to_status}")
    return ok_object(serialize(asset))


def _retire_guards(asset):
    """Retirement gates in PRD §2.12 priority order: in-flight disclosures
    (cat 6 state) -> preservation hold (cat 7 safety) -> active grants (cat 9)."""
    for d in all_rows("disclosures"):
        if d["asset_id"] == asset["id"] and d["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            raise err_invalid_state("Asset has disclosure requests in flight")
    for n in all_rows("preservation_notices"):
        if n["status"] in ("DRAFT", "ISSUED", "ACTIVE") and asset["id"] in (n["asset_ids"] or []):
            raise err_preservation("Asset is covered by a preservation notice")
    from services import recompute_grant_count

    recompute_grant_count(asset)
    if asset["active_grant_count"] != 0:
        raise err_grants_remain("Asset retirement attempted while active grants remain")


@bp.get("/api/assets/<rid>/posture-report")
def posture_report(rid):
    _uid, _role = actor()
    require_roles(_role, "IPCounsel", "SeniorCounsel")
    asset = by_id("assets", rid)
    if asset is None:
        raise err_not_found("asset not found")
    recompute_asset_scores(asset)
    measures = [
        {
            "id": m["id"],
            "measure_type": m["measure_type"],
            "title": m["title"],
            "status": m["status"],
            "weight_points": m["weight_points"],
            "points_effective": m["points_effective"],
        }
        for m in created_asc([x for x in all_rows("measures") if x["asset_id"] == rid])
    ]
    return ok_object(
        {
            "asset_id": asset["id"],
            "score_operational": asset["score_operational"],
            "score_documentary": asset["score_documentary"],
            "protection_posture": asset["protection_posture"],
            "measures": measures,
        }
    )


# ---------------------------------------------------------------------------
# ReasonableMeasure
# ---------------------------------------------------------------------------
@bp.post("/api/measures")
def create_measure():
    _uid, _role = actor()
    require_roles(_role, "SecurityOfficer", "IPCounsel")
    data = body()
    asset_id = require_str(data, "asset_id")
    asset = by_id("assets", asset_id)
    if asset is None:
        raise err_not_found("asset not found")
    measure = new_record(
        "measures",
        {
            "asset_id": asset_id,
            "measure_type": require_enum(data, "measure_type", MEASURE_TYPES),
            "title": require_str(data, "title"),
            "evidence_uri": optional_str(data, "evidence_uri") or "",
            "status": "PLANNED",
            "implemented_by_user_id": None,
            "verified_by_user_id": None,
            "weight_points": 0,
            "points_effective": 0,
        },
    )
    refresh_measure_derived(measure)
    recompute_asset_scores(asset)
    return ok_object(serialize(measure), code=201)


@bp.get("/api/measures")
def list_measures():
    _uid, _role = actor()
    require_roles(_role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    from flask import request

    filters = [(f, request.args[f]) for f in ("asset_id", "status", "measure_type") if f in request.args]
    rows = _list(all_rows("measures"), filters)
    from response import paginate

    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


@bp.get("/api/measures/<rid>")
def get_measure(rid):
    _uid, _role = actor()
    require_roles(_role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    m = by_id("measures", rid)
    if m is None:
        raise err_not_found("measure not found")
    return ok_object(serialize(m))


@bp.post("/api/measures/<rid>/state")
def measure_state(rid):
    user_id, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    m = by_id("measures", rid)
    if m is None:
        raise err_not_found("measure not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in MEASURE_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(MEASURE_STATUSES)}")
    cur = m["status"]
    asset = by_id("assets", m["asset_id"])

    if to_status == "IMPLEMENTED":
        # actor: SecurityOfficer | IPCounsel (endpoint roles already allow both)
        if cur not in ("PLANNED", "LAPSED"):
            raise err_invalid_state(f"Cannot move measure from {cur} to IMPLEMENTED")
        if asset is None or asset["status"] not in ("DRAFT", "REGISTERED"):
            raise err_invalid_state("Parent asset must be DRAFT or REGISTERED")
        if not m["evidence_uri"]:
            raise err_measure_evidence()
        m["status"] = "IMPLEMENTED"
        m["implemented_by_user_id"] = user_id
        touch(m)
        refresh_measure_derived(m)
        recompute_asset_scores(asset)
    elif to_status == "VERIFIED":
        if role != "IPCounsel":
            raise err_unauthorized_role("VERIFIED requires IPCounsel")
        if m["implemented_by_user_id"] is not None and user_id == m["implemented_by_user_id"]:
            raise err_sod("Measure implementer may not verify it")
        if cur != "IMPLEMENTED":
            raise err_invalid_state(f"Cannot move measure from {cur} to VERIFIED")
        m["status"] = "VERIFIED"
        m["verified_by_user_id"] = user_id
        touch(m)
        refresh_measure_derived(m)
        recompute_asset_scores(asset)
    elif to_status == "LAPSED":
        if role != "IPCounsel":
            raise err_unauthorized_role("LAPSED requires IPCounsel")
        if cur not in ("VERIFIED", "IMPLEMENTED"):
            raise err_invalid_state(f"Cannot move measure from {cur} to LAPSED")
        lapse_measure(m)
    elif to_status == "ABANDONED":
        if role != "IPCounsel":
            raise err_unauthorized_role("ABANDONED requires IPCounsel")
        if cur not in ("PLANNED", "LAPSED"):
            raise err_invalid_state(f"Cannot move measure from {cur} to ABANDONED")
        m["status"] = "ABANDONED"
        touch(m)
        refresh_measure_derived(m)
        if asset is not None:
            recompute_asset_scores(asset)
    else:  # PLANNED is never a valid manual target
        raise err_invalid_state(f"Cannot move measure from {cur} to {to_status}")
    return ok_object(serialize(m))
