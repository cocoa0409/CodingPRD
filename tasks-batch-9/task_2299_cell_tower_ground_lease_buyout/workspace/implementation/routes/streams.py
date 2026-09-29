"""Lease streams, carrier tenancies and stream valuations (PRD 3.2 - 3.4)."""

from flask import Blueprint

import calc
import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("streams", __name__)

ESCALATORS = ("NONE", "FIXED_PCT", "CPI_CAPPED")
ACQUISITION_STATUSES = ("PROSPECT", "UNDER_OFFER", "ACQUIRED", "LOST")
SERVICING_STATUSES = ("PERFORMING", "WATCHLIST", "IMPAIRED", "DELINQUENT")
CREDIT_TIERS = ("INVESTMENT_GRADE", "CROSSOVER", "SPECULATIVE")
TENANCY_TYPES = ("ANCHOR", "COLOCATION")
TENANCY_STATUSES = ("ACTIVE", "HOLDOVER", "TERMINATED")
METHODS = ("LUMP_SUM_PERPETUAL", "PREPAID_RENT_TERM")
VALUATION_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED", "STALE")

STREAM_LIST_ROLES = ("AcquisitionAnalyst", "PlatformAdmin", "PortfolioManager",
                     "TreasuryOfficer", "ServicingAgent")
STREAM_GET_ROLES = STREAM_LIST_ROLES + ("Landowner",)
TENANCY_READ_ROLES = ("AcquisitionAnalyst", "PlatformAdmin", "PortfolioManager", "ServicingAgent")
VALUATION_READ_ROLES = ("AcquisitionAnalyst", "PortfolioManager", "PlatformAdmin", "TreasuryOfficer")


# --------------------------------------------------------------- lease streams

@bp.post("/lease-streams")
def create_stream():
    principal("AcquisitionAnalyst", "PlatformAdmin")
    b = V.body()
    site = E.fk(b, "tower_site_id", "tower_sites", "ERR_TOWER_SITE_NOT_FOUND")
    landowner = E.fk(b, "landowner_id", "landowners", "ERR_LANDOWNER_NOT_FOUND")
    if site is None or landowner is None:
        V.bad()
    rent = V.req_int(b, "current_annual_rent_cents", minimum=1)
    escalator = V.req_enum(b, "escalator_type", ESCALATORS)
    term = V.req_int(b, "remaining_term_months", minimum=1, maximum=600)
    pct = V.opt_int(b, "escalator_pct_bps", default=0, minimum=0, maximum=1000)

    stream = E.new_entity(
        tower_site_id=site["id"],
        landowner_id=landowner["id"],
        current_annual_rent_cents=rent,
        escalator_type=escalator,
        escalator_pct_bps=pct,
        remaining_term_months=term,
        rent_redirection_status="NOT_APPLICABLE",
        tenancy_quality_score=0,
        anchor_carrier_name="UNASSIGNED",
        acquisition_status="PROSPECT",
        servicing_status="PERFORMING",
        cumulative_revenue_share_landowner_cents=0,
        cumulative_revenue_share_acquirer_cents=0,
        active_tenancy_count=0,
    )
    db.lease_streams[stream["id"]] = stream
    site["lease_stream_count"] += 1
    E.touch(site)
    return created(E.stream_json(stream))


@bp.get("/lease-streams")
def list_streams():
    principal(*STREAM_LIST_ROLES)
    limit, offset = V.pagination()
    site_id = V.str_filter("tower_site_id")
    landowner_id = V.str_filter("landowner_id")
    acquisition = V.enum_filter("acquisition_status", ACQUISITION_STATUSES)
    servicing = V.enum_filter("servicing_status", SERVICING_STATUSES)
    rows = E.ordered(list(db.lease_streams.values()))
    if site_id is not None:
        rows = [r for r in rows if r["tower_site_id"] == site_id]
    if landowner_id is not None:
        rows = [r for r in rows if r["landowner_id"] == landowner_id]
    if acquisition is not None:
        rows = [r for r in rows if r["acquisition_status"] == acquisition]
    if servicing is not None:
        rows = [r for r in rows if r["servicing_status"] == servicing]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.stream_json(r) for r in page], total, limit, offset)


@bp.get("/lease-streams/<sid>")
def get_stream(sid):
    principal(*STREAM_GET_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    return ok(E.stream_json(stream))


# ------------------------------------------------------------ carrier tenancies

@bp.post("/lease-streams/<sid>/tenancies")
def create_tenancy(sid):
    principal("AcquisitionAnalyst", "ServicingAgent")
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    b = V.body()
    carrier_name = V.req_str(b, "carrier_name")
    tier = V.req_enum(b, "carrier_credit_tier", CREDIT_TIERS)
    tenancy_type = V.req_enum(b, "tenancy_type", TENANCY_TYPES)
    rent_share = V.req_int(b, "monthly_rent_share_cents", minimum=0)
    term_end = V.req_date(b, "term_end_date")

    acquired = stream["acquisition_status"] == "ACQUIRED"
    tenancy = E.new_entity(
        lease_stream_id=stream["id"],
        carrier_name=carrier_name,
        carrier_credit_tier=tier,
        tenancy_type=tenancy_type,
        monthly_rent_share_cents=rent_share,
        term_end_date=term_end,
        status="ACTIVE",
        redirection_notice_status="PENDING" if acquired else "NOT_APPLICABLE",
        quality_points=0,
    )
    db.tenancies[tenancy["id"]] = tenancy
    if acquired:
        stream["rent_redirection_status"] = "PARTIAL"
    E.roster_write(stream)
    return created(E.tenancy_json(tenancy))


@bp.get("/lease-streams/<sid>/tenancies")
def list_tenancies(sid):
    principal(*TENANCY_READ_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    limit, offset = V.pagination()
    status = V.enum_filter("status", TENANCY_STATUSES)
    tenancy_type = V.enum_filter("tenancy_type", TENANCY_TYPES)
    rows = E.tenancies_of(stream["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tenancy_type is not None:
        rows = [r for r in rows if r["tenancy_type"] == tenancy_type]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.tenancy_json(r) for r in page], total, limit, offset)


@bp.post("/carrier-tenancies/<tid>/status")
def set_tenancy_status(tid):
    principal("ServicingAgent")
    tenancy = E.find("tenancies", tid, "ERR_TENANCY_NOT_FOUND")
    b = V.body()
    status = V.req_enum(b, "status", TENANCY_STATUSES)

    if tenancy["status"] != status:
        tenancy["status"] = status
        E.touch(tenancy)
    stream = db.lease_streams.get(tenancy["lease_stream_id"])
    if stream is not None:
        E.roster_write(stream)
    return ok(E.tenancy_json(tenancy))


# ------------------------------------------------------------------ valuations

@bp.post("/lease-streams/<sid>/valuations")
def create_valuation(sid):
    principal("AcquisitionAnalyst")
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    b = V.body()
    method = V.req_enum(b, "method", METHODS)
    expected = V.req_int(b, "expected_lease_stream_version")
    prepaid_months = V.opt_int(b, "prepaid_term_months", default=120, minimum=12, maximum=600)

    if expected != stream["version"]:
        fail("ERR_STALE_LEASE_STREAM_VERSION")

    score = stream["tenancy_quality_score"]
    figures = calc.valuation_figures(
        method,
        score,
        stream["current_annual_rent_cents"],
        stream["escalator_type"],
        stream["escalator_pct_bps"],
        stream["remaining_term_months"],
        prepaid_months,
    )
    valuation = E.new_entity(
        lease_stream_id=stream["id"],
        method=method,
        prepaid_term_months=prepaid_months,
        tenancy_quality_score_snapshot=score,
        discount_rate_bps=figures["discount_rate_bps"],
        growth_rate_bps=figures["growth_rate_bps"],
        horizon_years=figures["horizon_years"],
        value_cents=figures["value_cents"],
        max_bid_cents=calc.max_bid_cents(figures["value_cents"]),
        status="DRAFT",
        approved_by_user_id=None,
        approved_at=None,
    )
    db.valuations[valuation["id"]] = valuation
    return created(E.valuation_json(valuation))


@bp.get("/lease-streams/<sid>/valuations")
def list_valuations(sid):
    principal(*VALUATION_READ_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    limit, offset = V.pagination()
    status = V.enum_filter("status", VALUATION_STATUSES)
    method = V.enum_filter("method", METHODS)
    rows = E.valuations_of(stream["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.valuation_json(r) for r in page], total, limit, offset)


@bp.post("/stream-valuations/<vid>/approve")
def approve_valuation(vid):
    user_id, _role = principal("PortfolioManager")
    valuation = E.find("valuations", vid, "ERR_VALUATION_NOT_FOUND")
    stream = db.lease_streams.get(valuation["lease_stream_id"])

    if valuation["status"] != "DRAFT":
        fail("ERR_VALUATION_STALE")
    if stream is None or stream["active_tenancy_count"] < 1:
        fail("ERR_NO_ACTIVE_TENANCY")
    if valuation["tenancy_quality_score_snapshot"] != stream["tenancy_quality_score"]:
        fail("ERR_VALUATION_STALE")

    for other in E.valuations_of(stream["id"]):
        if other["id"] != valuation["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            E.touch(other)

    valuation["status"] = "APPROVED"
    valuation["approved_by_user_id"] = user_id
    valuation["approved_at"] = E.now()
    E.touch(valuation)
    return ok(E.valuation_json(valuation))
