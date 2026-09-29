"""Stations, affiliation agreements, distributors, the logical clock and the
time-driven maintenance sweep (PRD 3.1, 3.2, 3.9)."""
import re

from flask import Blueprint

import calc
import derive
from common import (
    authenticate,
    body_json,
    pagination,
    paginate,
    query_enum,
    take_dt,
    take_enum,
    take_enum_list,
    take_bool,
    take_int,
    take_str,
)
from envelope import array_response, object_response
from errors import ApiError
from store import (
    ALL_ROLES,
    AUDIT_RIGHTS_WINDOW_DAYS,
    add_days,
    base_row,
    db,
    fmt_dt,
    clock,
    now_iso,
    parse_iso,
    sort_rows,
    touch,
)

bp = Blueprint("setup", __name__)

NETWORKS = ["ABC", "CBS", "NBC", "FOX", "CW"]
NETWORK_AFFILIATIONS = NETWORKS + ["INDEPENDENT"]
TIERS = ["BROADCAST_BASIC", "EXPANDED_BASIC", "DIGITAL_TIER"]
DISTRIBUTOR_TYPES = ["CABLE", "DBS", "TELCO", "VMVPD"]
MEASUREMENT_METHODS = [
    "BILLED_HOUSEHOLDS", "WEIGHTED_STREAMING_DEVICES", "AVERAGE_MONTHLY_UNIQUE",
]
AFFILIATION_STATUSES = ["ACTIVE", "SUSPENDED", "EXPIRED"]

CALL_SIGN_RE = re.compile(r"^[A-Z]{4}$")
MARKET_CODE_RE = re.compile(r"^[A-Z]{3}$")


@bp.post("/retrans/stations")
def create_station():
    authenticate(["CarriageAdmin"])
    body = body_json()
    call_sign = take_str(body, "call_sign", min_len=4, max_len=4)
    if not CALL_SIGN_RE.match(call_sign):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'call_sign' must be four uppercase letters.")
    market_code = take_str(body, "market_code", min_len=3, max_len=3)
    if not MARKET_CODE_RE.match(market_code):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'market_code' must be three uppercase letters.")
    dma_rank = take_int(body, "dma_rank", minimum=1, maximum=210)
    households = take_int(body, "market_tv_households", minimum=1)
    affiliation = take_enum(body, "network_affiliation", NETWORK_AFFILIATIONS)
    for existing in db.stations.values():
        if existing["call_sign"] == call_sign:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'call_sign' must be globally unique.")
    row = base_row()
    row.update({
        "call_sign": call_sign,
        "market_code": market_code,
        "dma_rank": dma_rank,
        "market_tv_households": households,
        "network_affiliation": affiliation,
    })
    db.stations[row["id"]] = row
    return object_response(derive.station_json(row), 201)


@bp.get("/retrans/stations/<station_id>")
def read_station(station_id):
    authenticate(ALL_ROLES)
    station = derive.get_station(station_id)
    return object_response(derive.station_json(station))


@bp.post("/retrans/stations/<station_id>/affiliation-agreements")
def create_affiliation(station_id):
    authenticate(["CarriageAdmin"])
    body = body_json()
    network_name = take_enum(body, "network_name", NETWORKS)
    term_end = take_dt(body, "term_end_utc")
    floor_cents = take_int(body, "reverse_comp_floor_per_sub_cents", minimum=0, maximum=400)
    premium_bp = take_int(body, "split_premium_bp", minimum=0, maximum=2000)
    permitted = take_enum_list(body, "permitted_tiers", TIERS, min_items=1)
    digital = take_bool(body, "digital_rights_grantable")
    ooh = take_bool(body, "ooh_rights_grantable")
    streaming = take_bool(body, "streaming_rights_grantable")
    status = take_enum(body, "status", AFFILIATION_STATUSES, required=False, default="ACTIVE")

    station = derive.get_station(station_id)
    # Priority 36: the affiliation network must match the station's affiliation,
    # and an INDEPENDENT station holds no affiliation contract at all.
    if station["network_affiliation"] == "INDEPENDENT" or network_name != station["network_affiliation"]:
        raise ApiError("ERR_NETWORK_MISMATCH")

    row = base_row()
    row.update({
        "station_id": station_id,
        "network_name": network_name,
        "term_end_utc": fmt_dt(term_end),
        "reverse_comp_floor_per_sub_cents": floor_cents,
        "split_premium_bp": premium_bp,
        "digital_rights_grantable": digital,
        "ooh_rights_grantable": ooh,
        "streaming_rights_grantable": streaming,
        "permitted_tiers": permitted,
        "status": status,
    })
    db.affiliations[row["id"]] = row
    return object_response(derive.affiliation_json(row), 201)


@bp.get("/retrans/stations/<station_id>/affiliation-agreements")
def list_affiliations(station_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", AFFILIATION_STATUSES)
    derive.get_station(station_id)
    rows = derive.affiliations_of(station_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.affiliation_json)
    return array_response(items, limit, offset, total)


@bp.post("/retrans/distributors")
def create_distributor():
    authenticate(["CarriageAdmin"])
    body = body_json()
    name = take_str(body, "name", min_len=1, max_len=80)
    dist_type = take_enum(body, "distributor_type", DISTRIBUTOR_TYPES)
    method = take_enum(body, "subscriber_measurement_method", MEASUREMENT_METHODS)
    households = take_int(body, "video_household_count", minimum=1)
    for existing in db.distributors.values():
        if existing["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'name' must be globally unique.")
    row = base_row()
    row.update({
        "name": name,
        "distributor_type": dist_type,
        "subscriber_measurement_method": method,
        "video_household_count": households,
        "required_blackout_notice_days": calc.required_notice_days(dist_type),
    })
    db.distributors[row["id"]] = row
    return object_response(derive.distributor_json(row), 201)


@bp.get("/retrans/distributors/<distributor_id>")
def read_distributor(distributor_id):
    authenticate(ALL_ROLES)
    distributor = derive.get_distributor(distributor_id)
    return object_response(derive.distributor_json(distributor))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["CarriageAdmin"])
    body = body_json()
    instant = take_dt(body, "to_iso8601")
    db.clock = instant
    return object_response({"current_utc": fmt_dt(instant)})


@bp.post("/retrans/expiration-sweep")
def expiration_sweep():
    authenticate(["CarriageAdmin"])
    now = clock()
    expired_agreements = 0
    lapsed_extensions = 0
    lapsed_elections = 0
    accepted_reports = 0
    expired_affiliations = 0

    # 1. EXECUTED agreements whose effective_end_utc is at or before the clock.
    for agreement in sort_rows(list(db.agreements.values())):
        if agreement["execution_status"] != "EXECUTED":
            continue
        end = parse_iso(agreement.get("effective_end_utc"))
        if end is not None and end <= now:
            agreement["execution_status"] = "EXPIRED"
            touch(agreement)
            expired_agreements += 1

    # 2. ACTIVE extensions whose extension_end_utc is at or before the clock;
    #    their days stay inside the budget.
    for extension in sort_rows(list(db.extensions.values())):
        if extension["status"] != "ACTIVE":
            continue
        end = parse_iso(extension.get("extension_end_utc"))
        if end is not None and end <= now:
            extension["status"] = "LAPSED"
            touch(extension)
            lapsed_extensions += 1

    # 3. NEGOTIATING elections past incumbent expiry with no agreement on their
    #    negotiation and no ACTIVE extension covering the clock.
    for election in sort_rows(list(db.elections.values())):
        if election["status"] != "NEGOTIATING":
            continue
        expiry = parse_iso(election.get("incumbent_expiry_utc"))
        if expiry is None or expiry > now:
            continue
        negotiation = None
        for row in db.negotiations.values():
            if row["election_id"] == election["id"]:
                negotiation = row
                break
        if negotiation is None:
            continue
        agreements = [a for a in db.agreements.values() if a["negotiation_id"] == negotiation["id"]]
        if agreements:
            continue
        # "no interim extension in status ACTIVE covers the current logical clock
        # for any agreement of that election" (PRD 3.3) -- the extension windows
        # are closed at both endpoints.
        covered = False
        for agreement in agreements:
            for extension in derive.extensions_of(agreement["id"]):
                if extension["status"] != "ACTIVE":
                    continue
                start = parse_iso(extension.get("extension_start_utc"))
                end = parse_iso(extension.get("extension_end_utc"))
                if start is not None and end is not None and start <= now <= end:
                    covered = True
                    break
        if covered:
            continue
        election["status"] = "ELECTION_LAPSED"
        touch(election)
        lapsed_elections += 1
        negotiation["status"] = "CANCELLED"
        touch(negotiation)
        for offer in derive.offers_of(negotiation["id"]):
            if offer["status"] == "SUBMITTED":
                offer["status"] = "EXPIRED"
                touch(offer)

    # 4. Reports past the 180-day audit window with no OPEN finding.
    for report in sort_rows(list(db.reports.values())):
        if report["status"] not in ("REPORTED", "UNDER_AUDIT", "ADJUSTED"):
            continue
        period_end = parse_iso(report.get("period_end_utc"))
        if period_end is None or now <= add_days(period_end, AUDIT_RIGHTS_WINDOW_DAYS):
            continue
        if any(f["status"] == "OPEN" for f in derive.findings_of(report["id"])):
            continue
        report["status"] = "ACCEPTED"
        touch(report)
        accepted_reports += 1

    # 5. ACTIVE affiliation agreements whose term_end_utc is at or before the clock.
    for affiliation in sort_rows(list(db.affiliations.values())):
        if affiliation["status"] != "ACTIVE":
            continue
        end = parse_iso(affiliation.get("term_end_utc"))
        if end is not None and end <= now:
            affiliation["status"] = "EXPIRED"
            touch(affiliation)
            expired_affiliations += 1

    return object_response({
        "expired_agreement_count": expired_agreements,
        "lapsed_extension_count": lapsed_extensions,
        "lapsed_election_count": lapsed_elections,
        "accepted_report_count": accepted_reports,
        "expired_affiliation_count": expired_affiliations,
    })
