"""Logical clock, ports, fuel grades and index quotes (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import serializers
from db import store
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from validation import (
    apply_page,
    body,
    pagination,
    v_bool,
    v_datetime,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("reference", __name__)

PORT_READERS = ("OpsCoordinator", "ComplianceOfficer", "CreditController", "Surveyor")
SPILL_TIERS = ("TIER_1", "TIER_2", "TIER_3")
CONTAMINATION_GROUPS = ("DISTILLATE", "RESIDUAL", "BIOBLEND")
QUOTE_SOURCES = ("PLATTS", "ARGUS")


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #


@bp.post("/_clock/set_current_utc")
@roles("OpsCoordinator")
def set_clock():
    data = body()
    instant = v_datetime(data, "to_iso8601", required=True)
    store.clock = instant
    return success({}, 200)


# --------------------------------------------------------------------------- #
# ports
# --------------------------------------------------------------------------- #


@bp.post("/ports")
@roles("OpsCoordinator")
def create_port():
    data = body()
    port_code = v_string(data, "port_code", min_len=1, max_len=16)
    name = v_string(data, "name", min_len=1)
    eca_zone = v_bool(data, "eca_zone", required=False, default=False)
    eca_sulfur_limit_pct = v_decimal(
        data, "eca_sulfur_limit_pct", 3, required=False, default=Decimal("0.100"), positive=True
    )
    notice_lead_hours = v_int(data, "notice_lead_hours", required=False, default=24, min_value=0)
    concurrent_ops_capacity = v_int(
        data, "concurrent_ops_capacity", required=False, default=2, min_value=1
    )
    spill_response_tier = v_enum(
        data, "spill_response_tier", SPILL_TIERS, required=False, default="TIER_2"
    )

    for existing in store.ports.values():
        if existing["port_code"] == port_code:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE")

    port = db.new_record()
    port.update(
        {
            "port_code": port_code,
            "name": name,
            "eca_zone": eca_zone,
            "eca_sulfur_limit_pct": eca_sulfur_limit_pct,
            "notice_lead_hours": notice_lead_hours,
            "concurrent_ops_capacity": concurrent_ops_capacity,
            "spill_response_tier": spill_response_tier,
        }
    )
    store.ports[port["id"]] = port
    return success(serializers.port(port), 201)


@bp.get("/ports/<rec_id>")
@roles(*PORT_READERS)
def get_port(rec_id):
    port = path_ref(store.ports, rec_id, "ERR_PORT_NOT_FOUND")
    return success(serializers.port(port))


@bp.get("/ports")
@roles(*PORT_READERS)
def list_ports():
    limit, offset = pagination()
    rows = db.sorted_rows(store.ports)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.port(r) for r in page], limit, offset, len(rows))


# --------------------------------------------------------------------------- #
# fuel grades
# --------------------------------------------------------------------------- #


@bp.post("/fuel-grades")
@roles("OpsCoordinator")
def create_fuel_grade():
    data = body()
    grade_code = v_string(data, "grade_code", min_len=1)
    max_sulfur_pct = v_decimal(data, "max_sulfur_pct", 3, positive=True)
    eca_permitted = v_bool(data, "eca_permitted", required=False, default=False)
    test_tolerance_pct = v_decimal(
        data, "test_tolerance_pct", 3, required=False, default=Decimal("0.010"), min_value=0
    )
    index_code = v_string(data, "index_code", min_len=1)
    base_barging_rate_usd_per_mt = v_decimal(
        data, "base_barging_rate_usd_per_mt", 2, min_value=0
    )
    min_barging_fee_usd = v_decimal(data, "min_barging_fee_usd", 2, min_value=0)
    cross_contamination_group = v_enum(data, "cross_contamination_group", CONTAMINATION_GROUPS)

    for existing in store.fuel_grades.values():
        if existing["grade_code"] == grade_code:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE")

    grade = db.new_record()
    grade.update(
        {
            "grade_code": grade_code,
            "max_sulfur_pct": max_sulfur_pct,
            "eca_permitted": eca_permitted,
            "test_tolerance_pct": test_tolerance_pct,
            "index_code": index_code,
            "base_barging_rate_usd_per_mt": base_barging_rate_usd_per_mt,
            "min_barging_fee_usd": min_barging_fee_usd,
            "cross_contamination_group": cross_contamination_group,
        }
    )
    store.fuel_grades[grade["id"]] = grade
    return success(serializers.fuel_grade(grade), 201)


@bp.get("/fuel-grades/<rec_id>")
@roles(*PORT_READERS)
def get_fuel_grade(rec_id):
    grade = path_ref(store.fuel_grades, rec_id, "ERR_FUEL_GRADE_NOT_FOUND")
    return success(serializers.fuel_grade(grade))


@bp.get("/fuel-grades/<rec_id>/index-quotes")
@roles("OpsCoordinator", "CreditController")
def list_grade_quotes(rec_id):
    grade = path_ref(store.fuel_grades, rec_id, "ERR_FUEL_GRADE_NOT_FOUND")
    limit, offset = pagination()
    rows = [q for q in store.index_quotes.values() if q["grade_id"] == grade["id"]]
    # PRD 2.3: the one documented exception to created_at ASC ordering.
    rows.sort(key=lambda q: (q["quote_date"], q["created_at"], q["_seq"]), reverse=True)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.index_quote(r) for r in page], limit, offset, len(rows))


# --------------------------------------------------------------------------- #
# index quotes
# --------------------------------------------------------------------------- #


@bp.post("/index-quotes")
@roles("OpsCoordinator", "CreditController")
def create_index_quote():
    data = body()
    grade = body_ref(data, "grade_id", store.fuel_grades, "ERR_FUEL_GRADE_NOT_FOUND")
    grade_id = v_string(data, "grade_id", min_len=1)
    quote_date = v_datetime(data, "quote_date")
    price_usd_per_mt = v_decimal(data, "price_usd_per_mt", 2, positive=True)
    source = v_enum(data, "source", QUOTE_SOURCES, required=False, default="PLATTS")
    if grade is None:
        raise ApiError("ERR_FUEL_GRADE_NOT_FOUND")

    quote = db.new_record(common_fields=False)
    quote.update(
        {
            "grade_id": grade_id,
            "quote_date": quote_date,
            "price_usd_per_mt": price_usd_per_mt,
            "source": source,
        }
    )
    store.index_quotes[quote["id"]] = quote
    return success(serializers.index_quote(quote), 201)
