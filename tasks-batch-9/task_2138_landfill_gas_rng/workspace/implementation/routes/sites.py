"""LandfillSite endpoints and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import derived
import store
from auth import authenticate, require_role
from common import fmt_iso, r2
from envelope import object_response, paginate, pagination
from helpers import arg, filter_equal, must_find
from serializers import raw, site_out
from validation import (
    Field,
    MONTH_PATTERN,
    STATE_CODE_PATTERN,
    parse_body,
    validate,
)

bp = Blueprint("sites", __name__)

ZERO = Decimal("0")

SITE_FIELDS = [
    Field("name", "string", required=True, max_len=120),
    Field("state_code", "string", required=True, min_len=2, max_len=2, pattern=STATE_CODE_PATTERN),
    Field("host_royalty_pct", "number", required=True, gt=0, lte=0.50),
    Field("royalty_variant", "enum", required=True, values=("GROSS_REVENUE_SHARE", "NETBACK_SHARE")),
    Field("permit_nmoc_limit_lb_per_hr", "number", required=True, gt=0),
    Field("royalty_floor_usd_per_mmbtu", "number", gte=0, default=Decimal("0.25")),
    Field("design_collection_efficiency_pct", "number", default=Decimal("85.0")),
]


@bp.post("/sites")
def create_site():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin"])
    body = parse_body()
    data = validate(body, SITE_FIELDS)

    row = store.new_row(
        name=data["name"],
        state_code=data["state_code"],
        host_royalty_pct=data["host_royalty_pct"],
        royalty_variant=data["royalty_variant"],
        royalty_floor_usd_per_mmbtu=data["royalty_floor_usd_per_mmbtu"],
        permit_nmoc_limit_lb_per_hr=data["permit_nmoc_limit_lb_per_hr"],
        design_collection_efficiency_pct=data["design_collection_efficiency_pct"],
        collected_flow_scfm=r2(ZERO),
        collection_efficiency_pct=r2(ZERO),
        energy_produced_mmbtu=r2(ZERO),
        energy_injected_mmbtu=r2(ZERO),
        energy_flared_mmbtu=r2(ZERO),
        energy_vented_mmbtu=r2(ZERO),
        rin_generated_total=0,
        rin_available_count=0,
        rin_retired_count=0,
        rin_reversed_count=0,
        royalty_payable_usd=r2(ZERO),
        compliance_posture="COMPLIANT",
    )
    store.sites[row["id"]] = row
    return object_response(site_out(row), 201)


@bp.get("/sites/<site_id>")
def read_site(site_id):
    caller = authenticate()
    require_role(
        caller,
        [
            "ProjectAdmin",
            "ComplianceOfficer",
            "CommercialScheduler",
            "HostRepresentative",
            "PlantOperator",
            "WellfieldTechnician",
        ],
    )
    row = must_find("site", site_id)
    return object_response(site_out(row))


@bp.get("/sites")
def list_sites():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer"])
    limit, offset = pagination()
    rows = store.ordered(store.sites.values())
    rows = filter_equal(rows, "state_code", arg("state_code"))
    rows = filter_equal(rows, "compliance_posture", arg("compliance_posture"))
    return paginate(rows, limit, offset, site_out)


@bp.get("/sites/<site_id>/energy-balance")
def energy_balance(site_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer", "HostRepresentative"])
    site = must_find("site", site_id)

    produced = r2(site["energy_produced_mmbtu"])
    destinations = r2(
        site["energy_injected_mmbtu"] + site["energy_flared_mmbtu"] + site["energy_vented_mmbtu"]
    )
    rin_total = site["rin_generated_total"]
    rin_sum = (
        site["rin_available_count"] + site["rin_retired_count"] + site["rin_reversed_count"]
    )
    payload = {
        "site_id": site["id"],
        "energy_produced_mmbtu": raw(site["energy_produced_mmbtu"]),
        "energy_injected_mmbtu": raw(site["energy_injected_mmbtu"]),
        "energy_flared_mmbtu": raw(site["energy_flared_mmbtu"]),
        "energy_vented_mmbtu": raw(site["energy_vented_mmbtu"]),
        "balance_ok": produced == destinations,
        "rin_generated_total": rin_total,
        "rin_available_count": site["rin_available_count"],
        "rin_retired_count": site["rin_retired_count"],
        "rin_reversed_count": site["rin_reversed_count"],
        "rin_ledger_ok": rin_total == rin_sum,
    }
    return object_response(payload)


CLOCK_FIELDS = [Field("to_iso8601", "datetime", required=True)]


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin"])
    body = parse_body()
    data = validate(body, CLOCK_FIELDS)
    store.set_clock(data["to_iso8601"])
    return object_response({"current_utc": fmt_iso(store.now())})


# Re-exported so app.py can register the module without unused-import noise.
__all__ = ["bp", "derived", "MONTH_PATTERN"]
