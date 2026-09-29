"""Logical clock, shippers, commodities, the compatibility matrix, tariff
filings, the diesel index and river stage readings."""
from flask import Blueprint, request

import calc
from common import (ALL_ROLES, ApiError, apply_filters, authenticate, caller_id,
                    clock, created, dec, f_bool, f_date, f_dt, f_enum, f_int,
                    f_num, f_str, fetch, fmt_dt, get_body, make_record, ok,
                    paged_response, pagination, parse_date, sorted_rows, store,
                    touch)
from schema import (ser_commodity, ser_filing, ser_posting, ser_reading,
                    ser_rule, ser_shipper)

bp = Blueprint("reference", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    to_iso = f_dt(body, "to_iso8601")
    clock.set(to_iso)
    return ok({"current_utc": fmt_dt(clock.now())})


# ---------------------------------------------------------------------------
# Shippers
# ---------------------------------------------------------------------------
@bp.post("/shippers")
def create_shipper():
    authenticate(["ContractManager"])
    body = get_body()
    name = f_str(body, "name")
    credit_limit = f_int(body, "credit_limit_cents", ge=0)
    rec = make_record({
        "name": name,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
        "open_claim_count": 0,
    })
    store.shippers[rec["id"]] = rec
    return created(ser_shipper(rec))


@bp.get("/shippers/<shipper_id>")
def get_shipper(shipper_id):
    authenticate(ALL_ROLES)
    return ok(ser_shipper(fetch(store.shippers, shipper_id, "ERR_SHIPPER_NOT_FOUND")))


@bp.get("/shippers")
def list_shippers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.shippers), [("status", "status")])
    return paged_response(rows, ser_shipper, limit, offset)


# ---------------------------------------------------------------------------
# Commodities
# ---------------------------------------------------------------------------
@bp.post("/commodities")
def create_commodity():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    code = f_str(body, "code")
    group = f_enum(body, "commodity_group", calc.COMMODITY_GROUPS)
    residue = f_enum(body, "residue_class", calc.RESIDUE_CLASSES)
    hazard = f_bool(body, "hazard_flag")
    stowage = f_num(body, "stowage_factor", gt=0)
    for existing in store.commodities.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_HULL_NUMBER",
                           "Commodity code '%s' is already registered." % code)
    rec = make_record({
        "code": code,
        "commodity_group": group,
        "residue_class": residue,
        "hazard_flag": hazard,
        "stowage_factor": stowage,
    }, versioned=False)
    store.commodities[rec["id"]] = rec
    return created(ser_commodity(rec))


@bp.get("/commodities/<commodity_id>")
def get_commodity(commodity_id):
    authenticate(ALL_ROLES)
    return ok(ser_commodity(fetch(store.commodities, commodity_id,
                                  "ERR_COMMODITY_NOT_FOUND")))


@bp.get("/commodities")
def list_commodities():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.commodities),
                         [("commodity_group", "commodity_group")])
    return paged_response(rows, ser_commodity, limit, offset)


# ---------------------------------------------------------------------------
# Prior-cargo compatibility matrix
# ---------------------------------------------------------------------------
@bp.post("/compatibility-rules")
def create_rule():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    prior = f_enum(body, "prior_commodity_group", calc.COMMODITY_GROUPS)
    nxt = f_enum(body, "next_commodity_group", calc.COMMODITY_GROUPS)
    level = f_enum(body, "required_cleaning_level", calc.CLEANING_LEVELS)
    prohibited = f_bool(body, "prohibited", required=False, default=False)
    rec = make_record({
        "prior_commodity_group": prior,
        "next_commodity_group": nxt,
        "required_cleaning_level": level,
        "prohibited": prohibited,
    }, versioned=False)
    store.compatibility_rules[rec["id"]] = rec
    return created(ser_rule(rec))


@bp.get("/compatibility-rules")
def list_rules():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.compatibility_rules),
                         [("prior_commodity_group", "prior_commodity_group"),
                          ("next_commodity_group", "next_commodity_group")])
    return paged_response(rows, ser_rule, limit, offset)


# ---------------------------------------------------------------------------
# Tariff filings
# ---------------------------------------------------------------------------
def _validate_surcharge_table(value):
    if not isinstance(value, list) or not value:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'fuel_surcharge_table' must be a non-empty list.")
    previous = None
    cleaned = []
    for tier in value:
        if not isinstance(tier, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'fuel_surcharge_table' entries must be objects.")
        threshold = tier.get("threshold_cents_per_gallon")
        pct = tier.get("pct")
        if (threshold is None or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'threshold_cents_per_gallon' must be a number.")
        if pct is None or isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'pct' must be a number.")
        if previous is not None and not dec(threshold) > dec(previous):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Fuel surcharge thresholds must be strictly ascending.")
        previous = threshold
        cleaned.append({"threshold_cents_per_gallon": threshold, "pct": pct})
    return cleaned


@bp.post("/tariff-filings")
def create_filing():
    authenticate(["TariffAnalyst"])
    body = get_body()
    tariff_code = f_str(body, "tariff_code")
    group = f_enum(body, "commodity_group", calc.COMMODITY_GROUPS)
    base_rate = f_num(body, "base_rate_cents_per_ton_mile", gt=0)
    min_charge = f_int(body, "min_charge_cents", ge=0)
    demurrage_rate = f_int(body, "demurrage_rate_cents_per_hour", ge=0)
    if "fuel_surcharge_table" not in body or body["fuel_surcharge_table"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'fuel_surcharge_table' is required.")
    table = _validate_surcharge_table(body["fuel_surcharge_table"])
    effective_from = f_dt(body, "effective_from")
    effective_to = f_dt(body, "effective_to")
    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'effective_to' must be strictly later than 'effective_from'.")
    supersedes = f_str(body, "supersedes_tariff_filing_id", required=False)
    if supersedes is not None:
        fetch(store.tariff_filings, supersedes, "ERR_TARIFF_FILING_NOT_FOUND")
    rec = make_record({
        "tariff_code": tariff_code,
        "commodity_group": group,
        "base_rate_cents_per_ton_mile": base_rate,
        "min_charge_cents": min_charge,
        "demurrage_rate_cents_per_hour": demurrage_rate,
        "fuel_surcharge_table": table,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "filed_by_user_id": None,
        "effectuated_by_user_id": None,
        "supersedes_tariff_filing_id": supersedes,
    })
    store.tariff_filings[rec["id"]] = rec
    return created(ser_filing(rec))


@bp.post("/tariff-filings/<tariff_filing_id>/file")
def file_filing(tariff_filing_id):
    authenticate(["TariffAnalyst"])
    filing = fetch(store.tariff_filings, tariff_filing_id, "ERR_TARIFF_FILING_NOT_FOUND")
    if filing["status"] != "DRAFT":
        raise ApiError("ERR_TARIFF_FILING_INVALID_STATE")
    if not filing["effective_to"] > filing["effective_from"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'effective_to' must be strictly later than 'effective_from'.")
    filing["status"] = "FILED"
    filing["filed_by_user_id"] = caller_id()
    touch(filing)
    return ok(ser_filing(filing))


@bp.post("/tariff-filings/<tariff_filing_id>/effectuate")
def effectuate_filing(tariff_filing_id):
    authenticate(["RateAuthority"])
    filing = fetch(store.tariff_filings, tariff_filing_id, "ERR_TARIFF_FILING_NOT_FOUND")
    # priority 8 - segregation of duties, ahead of the state precondition
    if filing.get("filed_by_user_id") is not None and caller_id() == filing["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if filing["status"] != "FILED":
        raise ApiError("ERR_TARIFF_FILING_INVALID_STATE")
    superseded_id = filing.get("supersedes_tariff_filing_id")
    for other in store.tariff_filings.values():
        if other["id"] == filing["id"] or other["id"] == superseded_id:
            continue
        if other["status"] != "EFFECTIVE":
            continue
        if other["commodity_group"] != filing["commodity_group"]:
            continue
        if (filing["effective_from"] <= other["effective_to"]
                and other["effective_from"] <= filing["effective_to"]):
            raise ApiError("ERR_TARIFF_WINDOW_OVERLAP")
    filing["status"] = "EFFECTIVE"
    filing["effectuated_by_user_id"] = caller_id()
    touch(filing)
    if superseded_id:
        older = store.tariff_filings.get(superseded_id)
        if older is not None and older["status"] == "EFFECTIVE":
            older["status"] = "SUPERSEDED"
            older["effective_to"] = filing["effective_from"]
            touch(older)
    return ok(ser_filing(filing))


@bp.get("/tariff-filings/<tariff_filing_id>")
def get_filing(tariff_filing_id):
    authenticate(ALL_ROLES)
    return ok(ser_filing(fetch(store.tariff_filings, tariff_filing_id,
                               "ERR_TARIFF_FILING_NOT_FOUND")))


@bp.get("/tariff-filings")
def list_filings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.tariff_filings),
                         [("status", "status"),
                          ("commodity_group", "commodity_group"),
                          ("supersedes_tariff_filing_id", "supersedes_tariff_filing_id")])
    return paged_response(rows, ser_filing, limit, offset)


# ---------------------------------------------------------------------------
# Fuel index postings
# ---------------------------------------------------------------------------
@bp.post("/fuel-index-postings")
def create_posting():
    authenticate(["TariffAnalyst"])
    body = get_body()
    posting_date = f_date(body, "posting_date")
    price = f_int(body, "diesel_price_cents_per_gallon", gt=0)
    rec = make_record({
        "posting_date": posting_date,
        "diesel_price_cents_per_gallon": price,
        "_posting_date": parse_date(posting_date),
    }, versioned=False)
    store.fuel_index_postings[rec["id"]] = rec
    return created(ser_posting(rec))


@bp.get("/fuel-index-postings")
def list_postings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_rows(store.fuel_index_postings)
    return paged_response(rows, ser_posting, limit, offset)


# ---------------------------------------------------------------------------
# River stage readings
# ---------------------------------------------------------------------------
@bp.post("/river-stage-readings")
def create_reading():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    station = f_str(body, "gauge_station")
    reading_at = f_dt(body, "reading_at")
    stage_feet = f_num(body, "stage_feet")
    band = calc.resolve_band(stage_feet)
    rec = make_record({
        "gauge_station": station,
        "reading_at": reading_at,
        "stage_feet": stage_feet,
        "draft_restriction_band": band,
        "max_draft_feet": calc.BAND_MAX_DRAFT_FEET[band],
        "tow_size_cap_barges": calc.BAND_TOW_SIZE_CAP[band],
    }, versioned=False)
    store.river_stage_readings[rec["id"]] = rec
    return created(ser_reading(rec))


@bp.get("/river-stage-readings")
def list_readings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.river_stage_readings),
                         [("gauge_station", "gauge_station")])
    return paged_response(rows, ser_reading, limit, offset)
