"""Price index report endpoints (PRD 3.5)."""
from flask import Blueprint, request

import clock
import db
from errors import err
from middleware import ALL_ROLES, PRICING_ANALYST, PRICING_MANAGER, body, endpoint
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import calc, cascades, serialize
from util import as_enum, as_int, as_str, get_required

bp = Blueprint("index_reports", __name__)

BASES = ("MATCHED_BASKET", "IMPUTED_FULL_CATALOG")


@bp.post("/index-reports")
@endpoint([PRICING_ANALYST])
def create_index_report(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    category_code = as_str(get_required(payload, "category_code"),
                           "category_code", min_len=1)
    basis_raw = as_str(get_required(payload, "basis"), "basis", min_len=1)
    expected_market_version = as_int(
        get_required(payload, "expected_market_version"),
        "expected_market_version", minimum=0)
    perception_survey_index_bp = None
    if payload.get("perception_survey_index_bp") is not None:
        perception_survey_index_bp = as_int(payload["perception_survey_index_bp"],
                                           "perception_survey_index_bp", minimum=0)

    basis = as_enum(basis_raw, "basis", BASES)

    if expected_market_version != market["version"]:
        raise err("ERR_STALE_MARKET_VERSION",
                  "expected_market_version %d does not match the market's current "
                  "version %d." % (expected_market_version, market["version"]))

    computed = calc.price_index(market, category_code, basis)

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "category_code": category_code,
        "basis": basis,
        "perception_survey_index_bp": perception_survey_index_bp,
        "perception_validation": calc.perception_validation(
            perception_survey_index_bp, computed["index_bp"]),
        "status": "DRAFT",
        "published_at": None,
    })
    record.update(computed)
    db.reports[record["id"]] = record
    db.touch(market)
    return object_response(serialize.report(record), 201)


@bp.post("/index-reports/<report_id>/publish")
@endpoint([PRICING_MANAGER])
def publish_index_report(user_id, role, report_id):
    report = path_lookup("reports", report_id, "ERR_REPORT_NOT_FOUND")

    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT report may be published.")
    if report["data_sufficiency"] != "SUFFICIENT":
        raise err("ERR_INSUFFICIENT_INDEX_DATA",
                  "A report whose data_sufficiency is INSUFFICIENT cannot govern.")

    report["status"] = "PUBLISHED"
    report["published_at"] = clock.now()
    db.touch(report)

    for other in db.ordered(db.reports):
        if other["id"] == report["id"]:
            continue
        if other["market_id"] != report["market_id"]:
            continue
        if other["category_code"] != report["category_code"]:
            continue
        if other["basis"] != report["basis"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        other["status"] = "SUPERSEDED"
        db.touch(other)

    market = db.markets.get(report["market_id"])
    if market is not None:
        cascades.recompute_market_posture(market)

    return object_response(serialize.report(report))


@bp.get("/index-reports/<report_id>")
@endpoint(ALL_ROLES)
def read_index_report(user_id, role, report_id):
    report = path_lookup("reports", report_id, "ERR_REPORT_NOT_FOUND")
    return object_response(serialize.report(report))


@bp.get("/index-reports")
@endpoint(ALL_ROLES)
def list_index_reports(user_id, role):
    rows = filtered(db.ordered(db.reports), request.args,
                    [("market_id", "market_id"),
                     ("category_code", "category_code"), ("basis", "basis"),
                     ("status", "status"),
                     ("data_sufficiency", "data_sufficiency")])
    return list_page(rows, serialize.report)
