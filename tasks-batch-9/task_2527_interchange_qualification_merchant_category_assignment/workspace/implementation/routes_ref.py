"""Network reference data: platforms, acquirers, the category directory, rate
programs, quarterly versions and currency-conversion rows (PRD 3.1 and 3.2)."""

from flask import Blueprint

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate
from envelope import array_response, object_response, paginate
from errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_STATE,
    ERR_RATE_VERSION_WINDOW_OVERLAP,
    fail,
)
from store import (
    PROGRAM_ELIGIBILITY_VOCAB,
    RATE_PROGRAM_CATEGORIES,
    REGION_CODES,
    DATA_ELEMENT_VOCAB,
    new_row,
    serialize,
    serialize_many,
    sorted_rows,
    store,
    touch,
)
from validate import FOUR_DIGITS

bp = Blueprint("ref", __name__)


# ---------------------------------------------------------------------------
# Processing platforms
# ---------------------------------------------------------------------------

@bp.post("/processing-platforms")
def create_platform():
    authenticate(["NetworkAdmin"])
    data = v.body()
    row = new_row({
        "name": v.req_str(data, "name", 1, 80),
        "region_code": v.req_enum(data, "region_code", REGION_CODES),
        "max_concurrent_windows": v.req_int(data, "max_concurrent_windows", 1),
        "blackout_buffer_days": v.req_int(data, "blackout_buffer_days", 0),
    })
    store.platforms[row["id"]] = row
    return object_response(serialize("ProcessingPlatform", row), 201)


@bp.get("/processing-platforms/<row_id>")
def get_platform(row_id):
    authenticate(ALL_ROLES)
    row = resolve.platform(row_id)
    return object_response(serialize("ProcessingPlatform", row))


@bp.get("/processing-platforms")
def list_platforms():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.platforms.values()))
    rows = listing.string_filter(rows, "region_code", "region_code")
    rows = listing.string_filter(rows, "region", "region_code")
    page, meta = paginate(rows)
    return array_response(serialize_many("ProcessingPlatform", page), meta)


# ---------------------------------------------------------------------------
# Acquirers
# ---------------------------------------------------------------------------

@bp.post("/acquirers")
def create_acquirer():
    authenticate(["NetworkAdmin"])
    data = v.body()
    platform_id = v.raw_id(data, "platform_id")
    if platform_id is not None:
        resolve.platform(platform_id)
    fields = {
        "name": v.req_str(data, "name", 1, 120),
        "bin_prefix": v.req_str(data, "bin_prefix"),
        "platform_id": v.req_str(data, "platform_id"),
        "country_code": v.req_country(data, "country_code"),
        "settlement_currency": v.req_currency(data, "settlement_currency"),
        "compliance_status": "COMPLIANT",
        "missed_window_count": 0,
    }
    if not v.SIX_DIGITS.match(fields["bin_prefix"]):
        v.bad("Field 'bin_prefix' must be exactly six digits.")
    for existing in store.acquirers.values():
        if existing["bin_prefix"] == fields["bin_prefix"]:
            fail(ERR_DUPLICATE_RESOURCE, "bin_prefix is already registered.")
    row = new_row(fields)
    store.acquirers[row["id"]] = row
    return object_response(serialize("Acquirer", row), 201)


@bp.get("/acquirers/<row_id>")
def get_acquirer(row_id):
    authenticate(ALL_ROLES)
    row = resolve.acquirer(row_id)
    return object_response(serialize("Acquirer", row))


@bp.get("/acquirers")
def list_acquirers():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.acquirers.values()))
    rows = listing.apply_string_filters(rows, [
        ("platform_id", "platform_id"),
        ("compliance_status", "compliance_status"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("Acquirer", page), meta)


# ---------------------------------------------------------------------------
# The merchant category directory
# ---------------------------------------------------------------------------

@bp.post("/mcc-definitions")
def create_mcc_definition():
    authenticate(["NetworkAdmin"])
    data = v.body()
    fields = {
        "mcc_code": v.req_mcc(data, "mcc_code"),
        "description": v.req_str(data, "description", 1, 200),
        "business_type_key": v.req_business_type_key(data, "business_type_key"),
        "program_eligibility": v.req_code_list(
            data, "program_eligibility", PROGRAM_ELIGIBILITY_VOCAB,
            required=False, default=[],
        ),
        "requires_documentation": v.req_bool(data, "requires_documentation"),
        "high_risk": v.req_bool(data, "high_risk"),
    }
    if calc.mcc_code_exists(fields["mcc_code"]):
        fail(ERR_DUPLICATE_RESOURCE, "mcc_code is already defined.")
    row = new_row(fields)
    store.mcc_definitions[row["id"]] = row
    return object_response(serialize("MccDefinition", row), 201)


@bp.get("/mcc-definitions/<row_id>")
def get_mcc_definition(row_id):
    authenticate(ALL_ROLES)
    row = resolve.mcc_definition(row_id)
    return object_response(serialize("MccDefinition", row))


@bp.get("/mcc-definitions")
def list_mcc_definitions():
    authenticate(ALL_ROLES)
    rows = sorted(store.mcc_definitions.values(), key=calc.assignment_rank)
    rows = listing.apply_string_filters(rows, [
        ("business_type_key", "business_type_key"),
        ("mcc_code", "mcc_code"),
    ])
    rows = listing.bool_filter(rows, "high_risk", "high_risk")
    page, meta = paginate(rows)
    return array_response(serialize_many("MccDefinition", page), meta)


# ---------------------------------------------------------------------------
# Rate programs
# ---------------------------------------------------------------------------

@bp.post("/rate-programs")
def create_rate_program():
    authenticate(["NetworkAdmin"])
    data = v.body()
    fields = {
        "program_code": v.req_str(data, "program_code", 1, 40),
        "name": v.req_str(data, "name", 1, 120),
        "category": v.req_enum(data, "category", RATE_PROGRAM_CATEGORIES),
        "eligible_mcc_codes": v.req_code_list(
            data, "eligible_mcc_codes", None, required=True,
            pattern=FOUR_DIGITS, non_empty=True,
        ),
        "base_rate_bps": v.req_int(data, "base_rate_bps", 0, 1000),
        "per_item_fee_cents": v.req_int(data, "per_item_fee_cents", 0, 500),
        "requires_data_elements": v.req_code_list(
            data, "requires_data_elements", DATA_ELEMENT_VOCAB,
            required=False, default=[],
        ),
        "max_clearing_delay_hours": v.req_int(data, "max_clearing_delay_hours", 0, 8760),
    }
    for existing in store.rate_programs.values():
        if existing["program_code"] == fields["program_code"]:
            fail(ERR_DUPLICATE_RESOURCE, "program_code is already defined.")
    row = new_row(fields)
    store.rate_programs[row["id"]] = row
    return object_response(serialize("RateProgram", row), 201)


@bp.get("/rate-programs/<row_id>")
def get_rate_program(row_id):
    authenticate(ALL_ROLES)
    row = resolve.rate_program(row_id)
    return object_response(serialize("RateProgram", row))


@bp.get("/rate-programs")
def list_rate_programs():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.rate_programs.values()))
    rows = listing.apply_string_filters(rows, [
        ("category", "category"),
        ("program_code", "program_code"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("RateProgram", page), meta)


# ---------------------------------------------------------------------------
# Quarterly rate program versions
# ---------------------------------------------------------------------------

@bp.post("/rate-programs/<program_id>/versions")
def create_rate_version(program_id):
    authenticate(["NetworkAdmin"])
    program = resolve.rate_program(program_id)
    data = v.body()
    quarter = v.req_str(data, "publication_quarter", 1, 6)
    if not v.QUARTER_LABEL.match(quarter):
        v.bad("Field 'publication_quarter' must look like 2026Q3.")
    effective_from = v.req_ts(data, "effective_from")
    effective_to = v.req_ts(data, "effective_to")
    if not effective_from < effective_to:
        v.bad("'effective_from' must be strictly earlier than 'effective_to'.")
    fields = {
        "rate_program_id": program["id"],
        "publication_quarter": quarter,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "base_rate_bps": v.req_int(data, "base_rate_bps", 0, 1000),
        "per_item_fee_cents": v.req_int(data, "per_item_fee_cents", 0, 500),
        "implementation_deadline": v.req_ts(data, "implementation_deadline"),
        "status": "DRAFT",
        "published_at": None,
    }
    for existing in store.rate_versions.values():
        if (existing["rate_program_id"] == program["id"]
                and existing["publication_quarter"] == quarter):
            fail(ERR_DUPLICATE_RESOURCE,
                 "This program already carries a version for that quarter.")
    row = new_row(fields)
    store.rate_versions[row["id"]] = row
    return object_response(serialize("RateProgramVersion", row), 201)


@bp.post("/rate-program-versions/<row_id>/publish")
def publish_rate_version(row_id):
    authenticate(["NetworkAdmin"])
    row = resolve.rate_version(row_id)
    if row["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Only a DRAFT version may be published.")
    if calc.rate_version_overlaps(row):
        fail(ERR_RATE_VERSION_WINDOW_OVERLAP)
    row["status"] = "PUBLISHED"
    row["published_at"] = store.now_ms()
    touch(row)
    return object_response(serialize("RateProgramVersion", row))


@bp.get("/rate-program-versions/<row_id>")
def get_rate_version(row_id):
    authenticate(ALL_ROLES)
    row = resolve.rate_version(row_id)
    return object_response(serialize("RateProgramVersion", row))


@bp.get("/rate-program-versions")
def list_rate_versions():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.rate_versions.values()))
    rows = listing.apply_string_filters(rows, [
        ("rate_program_id", "rate_program_id"),
        ("status", "status"),
        ("publication_quarter", "publication_quarter"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("RateProgramVersion", page), meta)


# ---------------------------------------------------------------------------
# Currency-conversion rows
# ---------------------------------------------------------------------------

@bp.post("/fx-rates")
def create_fx_rate():
    authenticate(["NetworkAdmin"])
    data = v.body()
    fields = {
        "base_currency": v.req_currency(data, "base_currency"),
        "quote_currency": v.req_currency(data, "quote_currency"),
        "rate": v.req_number(data, "rate", 0, None, 6, exclusive_min=True),
        "markup_bps": v.req_int(data, "markup_bps", 0, 500),
        "effective_from": v.req_ts(data, "effective_from"),
    }
    for existing in store.fx_rates.values():
        if (existing["base_currency"] == fields["base_currency"]
                and existing["quote_currency"] == fields["quote_currency"]
                and existing["effective_from"] == fields["effective_from"]):
            fail(ERR_DUPLICATE_RESOURCE,
                 "That currency pair is already published at that instant.")
    row = new_row(fields)
    store.fx_rates[row["id"]] = row
    return object_response(serialize("FxRate", row), 201)


@bp.get("/fx-rates/<row_id>")
def get_fx_rate(row_id):
    authenticate(ALL_ROLES)
    row = resolve.fx_rate(row_id)
    return object_response(serialize("FxRate", row))


@bp.get("/fx-rates")
def list_fx_rates():
    authenticate(ALL_ROLES)
    rows = sorted(
        store.fx_rates.values(),
        key=lambda r: (r["effective_from"], r["_created_ms"], r["_seq"]),
        reverse=True,
    )
    rows = listing.apply_string_filters(rows, [
        ("base_currency", "base_currency"),
        ("quote_currency", "quote_currency"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("FxRate", page), meta)
