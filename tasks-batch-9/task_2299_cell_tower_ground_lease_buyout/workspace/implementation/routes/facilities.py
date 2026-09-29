"""Financing facilities, collateral pledges and advances (PRD 3.9)."""

from flask import Blueprint

import calc
import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("facilities", __name__)

BASIS = ("MARK_TO_MODEL", "COST_BASIS")
PLEDGE_STATUSES = ("PLEDGED", "INELIGIBLE", "RELEASED")

FACILITY_READ_ROLES = ("TreasuryOfficer", "PortfolioManager", "PlatformAdmin")
PLEDGE_READ_ROLES = ("TreasuryOfficer", "PortfolioManager", "PlatformAdmin", "ServicingAgent")


@bp.post("/financing-facilities")
def create_facility():
    principal("TreasuryOfficer")
    b = V.body()
    portfolio = E.fk(b, "portfolio_id", "portfolios", "ERR_PORTFOLIO_NOT_FOUND")
    if portfolio is None:
        V.bad()
    name = V.req_str(b, "facility_name")
    advance_rate = V.req_int(b, "advance_rate_bps", minimum=1, maximum=9500)
    basis = V.req_enum(b, "valuation_basis", BASIS)
    limit_bps = V.opt_int(b, "carrier_concentration_limit_bps", default=5000,
                          minimum=1, maximum=10000)

    facility = E.new_entity(
        portfolio_id=portfolio["id"],
        facility_name=name,
        advance_rate_bps=advance_rate,
        valuation_basis=basis,
        carrier_concentration_limit_bps=limit_bps,
        pledged_eligible_total_cents=0,
        concentration_excess_cents=0,
        borrowing_base_cents=0,
        advances_outstanding_cents=0,
        compliance_state="COMPLIANT",
        pledged_stream_count=0,
    )
    db.facilities[facility["id"]] = facility
    return created(E.facility_json(facility))


@bp.get("/financing-facilities/<fid>")
def get_facility(fid):
    principal(*FACILITY_READ_ROLES)
    facility = E.find("facilities", fid, "ERR_FACILITY_NOT_FOUND")
    return ok(E.facility_json(facility))


@bp.post("/financing-facilities/<fid>/pledges")
def create_pledge(fid):
    principal("TreasuryOfficer")
    facility = E.find("facilities", fid, "ERR_FACILITY_NOT_FOUND")
    b = V.body()
    stream = E.fk(b, "lease_stream_id", "lease_streams", "ERR_LEASE_STREAM_NOT_FOUND")
    if stream is None:
        V.bad()
    start = V.req_date(b, "pledge_start_date")
    end = V.req_date(b, "pledge_end_date")
    expected = V.req_int(b, "expected_facility_version")

    if expected != facility["version"]:
        fail("ERR_STALE_FACILITY_VERSION")

    if stream["acquisition_status"] != "ACQUIRED":
        fail("ERR_STREAM_NOT_ACQUIRED")

    for existing in E.pledges_of_stream(stream["id"]):
        if existing["status"] == "RELEASED":
            continue
        if start <= existing["pledge_end_date"] and end >= existing["pledge_start_date"]:
            fail("ERR_PLEDGE_PERIOD_OVERLAP")

    basis_value = E.pledge_basis_value(facility, stream)
    haircut = calc.haircut_bps_for(stream["servicing_status"])
    pledge = E.new_entity(
        facility_id=facility["id"],
        lease_stream_id=stream["id"],
        pledge_start_date=start,
        pledge_end_date=end,
        valuation_basis_snapshot=facility["valuation_basis"],
        basis_value_cents=basis_value,
        haircut_bps=haircut,
        eligible_value_cents=0,
        status="PLEDGED",
    )
    if stream["servicing_status"] in ("IMPAIRED", "DELINQUENT"):
        pledge["status"] = "INELIGIBLE"
    pledge["eligible_value_cents"] = calc.eligible_value(
        pledge["status"], stream["servicing_status"], basis_value)
    db.pledges[pledge["id"]] = pledge
    E.recompute_facility(facility)
    return created(E.pledge_json(pledge))


@bp.post("/financing-facilities/<fid>/advances")
def create_advance(fid):
    principal("TreasuryOfficer")
    facility = E.find("facilities", fid, "ERR_FACILITY_NOT_FOUND")
    b = V.body()
    amount = V.req_int(b, "amount_cents", minimum=1)

    if facility["advances_outstanding_cents"] + amount > facility["borrowing_base_cents"]:
        fail("ERR_ADVANCE_EXCEEDS_BORROWING_BASE")

    facility["advances_outstanding_cents"] += amount
    E.touch(facility)
    E.recompute_facility(facility)
    return ok(E.facility_json(facility))


@bp.get("/collateral-pledges")
def list_pledges():
    principal(*PLEDGE_READ_ROLES)
    limit, offset = V.pagination()
    facility_id = V.str_filter("facility_id")
    stream_id = V.str_filter("lease_stream_id")
    status = V.enum_filter("status", PLEDGE_STATUSES)
    rows = E.ordered(list(db.pledges.values()))
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if stream_id is not None:
        rows = [r for r in rows if r["lease_stream_id"] == stream_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.pledge_json(r) for r in page], total, limit, offset)


@bp.get("/collateral-pledges/<pid>")
def get_pledge(pid):
    principal(*PLEDGE_READ_ROLES)
    pledge = E.find("pledges", pid, "ERR_PLEDGE_NOT_FOUND")
    return ok(E.pledge_json(pledge))


@bp.post("/collateral-pledges/<pid>/release")
def release_pledge(pid):
    principal("TreasuryOfficer")
    pledge = E.find("pledges", pid, "ERR_PLEDGE_NOT_FOUND")
    facility = db.facilities.get(pledge["facility_id"])

    if pledge["status"] == "RELEASED":
        fail("ERR_INVALID_PLEDGE_STATE")

    if pledge["status"] == "PLEDGED" and facility is not None:
        projected = E.projected_borrowing_base(facility, exclude_pledge_id=pledge["id"])
        if facility["advances_outstanding_cents"] > projected:
            fail("ERR_BORROWING_BASE_DEFICIT")

    pledge["status"] = "RELEASED"
    pledge["eligible_value_cents"] = 0
    E.touch(pledge)
    E.recompute_facility(facility)
    return ok(E.pledge_json(pledge))
