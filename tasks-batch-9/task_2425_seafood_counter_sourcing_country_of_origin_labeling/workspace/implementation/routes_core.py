"""Clock, counters, suppliers and species (PRD 3.1)."""

from decimal import Decimal

import serializers
import services
from auth import counter_scope
from common import base_record
from envelope import empty_result, obj_result
from errors import fail
from store import db
from validators import (
    req_datetime,
    req_int,
    req_bool,
    req_store_number,
    req_str,
    req_str_array,
)
from web import listing, route

ALL_ROLES = (
    "ChainAdmin",
    "SeafoodManager",
    "ComplianceOfficer",
    "MerchandisingLead",
    "SupplierRep",
)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@route("/_clock/set_current_utc", methods=["POST"], roles=("ChainAdmin",))
def set_clock(body):
    instant = req_datetime(body, "to_iso8601")
    db.clock = instant
    return empty_result(200)


# --------------------------------------------------------------------------
# counters
# --------------------------------------------------------------------------

@route("/counters", methods=["POST"], roles=("ChainAdmin",))
def create_counter(body):
    store_number = req_store_number(body, "store_number")
    department_name = req_str(body, "department_name")
    case_slot_count = req_int(body, "case_slot_count", minimum=1, maximum=12)

    record = base_record("counter")
    record.update(
        {
            "store_number": store_number,
            "department_name": department_name,
            "case_slot_count": case_slot_count,
            "posture": "OPEN",
            "open_excursion_count": 0,
            "violation_points": 0,
            "verification_cycle_index": 0,
            "last_cycle_required_samples": 0,
            "last_cycle_max_supplier_risk_index": Decimal("0.00"),
            "shrink_gross_cents": 0,
            "shrink_net_cents": 0,
            "recovered_conversion_cents": 0,
        }
    )
    db.counters[record["id"]] = record
    return obj_result(serializers.counter, record, 201)


@route(
    "/counters/<counter_id>",
    methods=["GET"],
    roles=("ChainAdmin", "SeafoodManager", "ComplianceOfficer", "MerchandisingLead"),
)
def get_counter(body, counter_id):
    counter_scope(counter_id)
    counter = db.counters.get(counter_id)
    if counter is None:
        fail("ERR_COUNTER_NOT_FOUND")
    return obj_result(serializers.counter, counter)


@route(
    "/counters",
    methods=["GET"],
    roles=("ChainAdmin", "ComplianceOfficer", "MerchandisingLead"),
)
def list_counters(body):
    return listing(
        serializers.counter,
        list(db.counters.values()),
        string_fields=("store_number", "posture"),
    )


@route(
    "/counters/<counter_id>/close-verification-cycle",
    methods=["POST"],
    roles=("ComplianceOfficer",),
)
def close_cycle(body, counter_id):
    counter = db.counters.get(counter_id)
    if counter is None:
        fail("ERR_COUNTER_NOT_FOUND")
    expected = req_int(body, "expected_counter_version")
    if expected != counter["version"]:
        fail("ERR_STALE_COUNTER_VERSION")
    services.close_verification_cycle(counter)
    return obj_result(serializers.counter, counter)


# --------------------------------------------------------------------------
# suppliers
# --------------------------------------------------------------------------

@route("/suppliers", methods=["POST"], roles=("ChainAdmin",))
def create_supplier(body):
    name = req_str(body, "name")
    permit_number = req_str(body, "permit_number")

    record = base_record("supplier")
    record.update(
        {
            "name": name,
            "permit_number": permit_number,
            "status": "GOOD_STANDING",
            "lifetime_sample_count": 0,
            "lifetime_mismatch_count": 0,
            "substitution_risk_index_rolling": Decimal("0.00"),
            "substitution_risk_index_lifetime": Decimal("0.00"),
            "chargeback_assessed_total_cents": 0,
            "chargeback_outstanding_cents": 0,
            "chargeback_settled_cents": 0,
            "chargeback_reversed_cents": 0,
        }
    )
    db.suppliers[record["id"]] = record
    return obj_result(serializers.supplier, record, 201)


@route(
    "/suppliers/<supplier_id>",
    methods=["GET"],
    roles=("ChainAdmin", "ComplianceOfficer", "SupplierRep", "SeafoodManager"),
)
def get_supplier(body, supplier_id):
    supplier = db.suppliers.get(supplier_id)
    if supplier is None:
        fail("ERR_SUPPLIER_NOT_FOUND")
    return obj_result(serializers.supplier, supplier)


# --------------------------------------------------------------------------
# species
# --------------------------------------------------------------------------

@route("/species", methods=["POST"], roles=("ChainAdmin",))
def create_species(body):
    market_name = req_str(body, "market_name")
    scientific_name = req_str(body, "scientific_name")
    acceptable = req_str_array(body, "acceptable_market_names")
    simp_covered = req_bool(body, "simp_covered")
    high_risk = req_bool(body, "high_risk_substitution")
    eligible = req_bool(body, "sustainability_program_eligible")

    record = base_record("species", versioned=False)
    record.update(
        {
            "market_name": market_name,
            "scientific_name": scientific_name,
            "acceptable_market_names": acceptable,
            "simp_covered": simp_covered,
            "high_risk_substitution": high_risk,
            "sustainability_program_eligible": eligible,
        }
    )
    db.species[record["id"]] = record
    return obj_result(serializers.species, record, 201)


@route("/species/<species_id>", methods=["GET"], roles=ALL_ROLES)
def get_species(body, species_id):
    record = db.species.get(species_id)
    if record is None:
        fail("ERR_SPECIES_NOT_FOUND")
    return obj_result(serializers.species, record)
