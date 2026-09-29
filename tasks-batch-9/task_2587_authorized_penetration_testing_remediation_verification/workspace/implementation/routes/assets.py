"""Asset inventory (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint, request

import serialize
from auth import authorize
from core import new_record
from envelope import object_response
from resolve import filtered, get_asset, paginate
from store import store
from validate import body, get_enum, get_enum_array, get_int, get_number, get_str, get_datetime

bp = Blueprint("assets", __name__)

ASSET_CLASSES = ("APPLICATION", "NETWORK", "CLOUD")
COMPLIANCE_REGIMES = ("PCI_DSS", "HIPAA", "SOX", "SOC2", "FEDRAMP")
EXPOSURE_STATES = ("MONITORED", "ELEVATED", "CLEARED")
READ_ROLES = ("PlatformAdmin", "ProgramManager", "ComplianceOfficer", "Tester")


@bp.post("/assets")
def register_asset():
    authorize("PlatformAdmin")
    data = body()
    name = get_str(data, "name", min_len=1, max_len=120)
    asset_class = get_enum(data, "asset_class", ASSET_CLASSES)
    tier = get_int(data, "criticality_tier", minimum=1, maximum=4)
    regimes = get_enum_array(data, "compliance_regimes", COMPLIANCE_REGIMES, required=True)
    exposure = get_number(data, "exposure_score", minimum=0, maximum=100, max_decimals=2)
    last_tested_raw, last_tested = get_datetime(data, "last_tested_at", required=False)
    record = new_record(
        name=name,
        asset_class=asset_class,
        criticality_tier=tier,
        compliance_regimes=regimes,
        exposure_score=exposure,
        last_tested_at=last_tested,
        last_tested_at_raw=last_tested_raw,
        exposure_state="MONITORED",
        open_finding_count=0,
        open_critical_finding_count=0,
        remediated_finding_count=0,
        last_cleared_at=None,
    )
    store.assets[record["id"]] = record
    return object_response(serialize.asset(record), 201)


@bp.get("/assets/<asset_id>")
def read_asset(asset_id):
    authorize(*READ_ROLES)
    return object_response(serialize.asset(get_asset(asset_id)))


@bp.get("/assets")
def list_assets():
    authorize(*READ_ROLES)
    rows = list(store.assets.values())
    rows = filtered(
        rows,
        asset_class=request.args.get("asset_class"),
        exposure_state=request.args.get("exposure_state"),
    )
    tier = request.args.get("criticality_tier")
    if tier is not None:
        try:
            wanted = int(str(tier).strip())
        except (TypeError, ValueError):
            wanted = None
        rows = [row for row in rows if row["criticality_tier"] == wanted]
    return paginate(rows, serialize.asset)
