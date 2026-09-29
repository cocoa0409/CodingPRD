"""Feedstock lots, quality tests, pretreatment and acceptance (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import response
import store
import validate
from constants import FEEDSTOCK_TYPES, PRETREAT_CI_ADDER
from errors import (
    ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED,
    ERR_INVALID_LOT_STATE,
    ERR_PRETREATMENT_MASS_EXCEEDED,
    ERR_STALE_LOT_VERSION,
    fail,
)
from routes.helpers import body_ref, find, listing
from store import bump, q

bp = Blueprint("lots", __name__)
ZERO = Decimal("0")


@bp.post("/feedstock-lots")
def create_lot():
    validate.auth("FeedstockTrader")
    data = validate.body()
    supplier = body_ref("supplier", data, "supplier_id")
    feedstock_type = validate.get_enum(data, "feedstock_type", FEEDSTOCK_TYPES)
    mass_mt = validate.get_num(data, "mass_mt", 0, 20000, 3, exclusive_min=True)
    attested = validate.get_num(data, "attested_ci_gco2e_per_mj", 0, 120, 2)
    price = validate.get_num(data, "purchase_price_usd_per_mt", 0, 5000, 2,
                             exclusive_min=True)
    received_at = validate.get_dt(data, "received_at")

    if feedstock_type not in supplier["feedstock_types"]:
        fail(ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED,
             "Supplier is not approved to deliver %s." % feedstock_type)

    row = store.new_row()
    row.update({
        "supplier_id": supplier["id"],
        "source_lot_id": None,
        "feedstock_type": feedstock_type,
        "mass_mt": q(mass_mt, 3),
        "attested_ci_gco2e_per_mj": q(attested, 2),
        "purchase_price_usd_per_mt": q(price, 2),
        "received_at": received_at,
        "status": "RECEIVED",
        "pretreatment_tier": "NONE",
        "pretreatment_fee_usd": q(ZERO, 2),
        "pretreatment_loss_mt": q(ZERO, 3),
        "pretreatment_consumed_mt": q(ZERO, 3),
        "allocated_mass_mt": q(ZERO, 3),
        "remaining_mass_mt": q(mass_mt, 3),
    })
    store.lots[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/feedstock-lots/<lot_id>")
def read_lot(lot_id):
    validate.auth("FeedstockTrader", "QualityAnalyst", "ComplianceOfficer", "PlantOperator")
    lot = find("lot", lot_id)
    return response.ok(lot)


@bp.get("/feedstock-lots")
def list_lots():
    validate.auth("FeedstockTrader", "QualityAnalyst", "ComplianceOfficer", "PlantOperator")
    rows, limit, offset = listing(store.table_rows(store.lots), {
        "supplier_id": "supplier_id",
        "source_lot_id": "source_lot_id",
        "feedstock_type": "feedstock_type",
        "status": "status",
    })
    return response.page(rows, limit, offset)


@bp.post("/feedstock-lots/<lot_id>/quality-tests")
def append_quality_test(lot_id):
    validate.auth("QualityAnalyst")
    lot = find("lot", lot_id)
    data = validate.body()
    ffa = validate.get_num(data, "ffa_pct", 0, 100, 2)
    moisture = validate.get_num(data, "moisture_pct", 0, 20, 2)
    insolubles = validate.get_int(data, "insolubles_ppm", 0, 50000)
    phosphorus = validate.get_int(data, "phosphorus_ppm", 0, 2000)
    sampled_at = validate.get_dt(data, "sampled_at")
    expected_version = validate.get_int(data, "expected_lot_version")

    if expected_version != lot["version"]:
        fail(ERR_STALE_LOT_VERSION,
             "Lot version is %d, not %d." % (lot["version"], expected_version))

    if lot["status"] not in ("RECEIVED", "TESTED", "PRETREAT_REQUIRED"):
        fail(ERR_INVALID_LOT_STATE,
             "A lot in %s cannot accept a quality test." % lot["status"])

    assessment = calc.pretreatment_tier_and_fee(
        lot["feedstock_type"], lot["mass_mt"], ffa, moisture, insolubles, phosphorus)

    row = store.new_row(versioned=False)
    row.update({
        "lot_id": lot["id"],
        "ffa_pct": q(ffa, 2),
        "moisture_pct": q(moisture, 2),
        "insolubles_ppm": insolubles,
        "phosphorus_ppm": phosphorus,
        "sampled_at": sampled_at,
        "ffa_tier_index": assessment["ffa_tier_index"],
        "moisture_tier_index": assessment["moisture_tier_index"],
        "insolubles_tier_index": assessment["insolubles_tier_index"],
        "phosphorus_tier_index": assessment["phosphorus_tier_index"],
        "tier": assessment["tier"],
        "disposition": assessment["disposition"],
        "_fee": assessment["fee"],
    })
    store.tests[row["id"]] = row

    domain.apply_governing_test(lot)
    bump(lot)
    return response.ok(row, 201)


@bp.get("/feedstock-lots/<lot_id>/quality-tests")
def list_quality_tests(lot_id):
    validate.auth("QualityAnalyst", "ComplianceOfficer")
    lot = find("lot", lot_id)
    rows, limit, offset = listing(domain.lot_tests(lot["id"]),
                                  {"disposition": "disposition"})
    return response.page(rows, limit, offset)


@bp.post("/feedstock-lots/<lot_id>/pretreatments")
def pretreat_lot(lot_id):
    validate.auth("QualityAnalyst")
    lot = find("lot", lot_id)
    data = validate.body()
    output_mass = validate.get_num(data, "output_mass_mt", places=3)

    if lot["status"] != "PRETREAT_REQUIRED" or lot["pretreatment_tier"] not in ("LIGHT", "HEAVY"):
        fail(ERR_INVALID_LOT_STATE,
             "Only a PRETREAT_REQUIRED lot with a LIGHT or HEAVY tier may be pretreated.")

    if output_mass <= 0 or output_mass > lot["mass_mt"]:
        fail(ERR_PRETREATMENT_MASS_EXCEEDED,
             "Field 'output_mass_mt' must be greater than 0 and no greater than the "
             "source lot's mass_mt.")

    output_mass = q(output_mass, 3)
    source_tier = lot["pretreatment_tier"]
    source_fee = lot["pretreatment_fee_usd"]

    lot["status"] = "PRETREATED"
    lot["pretreatment_consumed_mt"] = q(lot["mass_mt"], 3)
    lot["pretreatment_loss_mt"] = q(lot["mass_mt"] - output_mass, 3)
    lot["remaining_mass_mt"] = q(ZERO, 3)
    bump(lot)

    child = store.new_row()
    child.update({
        "supplier_id": lot["supplier_id"],
        "source_lot_id": lot["id"],
        "feedstock_type": lot["feedstock_type"],
        "mass_mt": output_mass,
        "attested_ci_gco2e_per_mj": q(
            lot["attested_ci_gco2e_per_mj"] + PRETREAT_CI_ADDER[source_tier], 2),
        "purchase_price_usd_per_mt": q(
            (lot["mass_mt"] * lot["purchase_price_usd_per_mt"] + source_fee) / output_mass, 2),
        "received_at": lot["received_at"],
        "status": "ACCEPTED",
        "pretreatment_tier": "NONE",
        "pretreatment_fee_usd": q(ZERO, 2),
        "pretreatment_loss_mt": q(ZERO, 3),
        "pretreatment_consumed_mt": q(ZERO, 3),
        "allocated_mass_mt": q(ZERO, 3),
        "remaining_mass_mt": output_mass,
    })
    store.lots[child["id"]] = child
    return response.ok(child, 201)


@bp.post("/feedstock-lots/<lot_id>/acceptances")
def accept_lot(lot_id):
    validate.auth("QualityAnalyst")
    lot = find("lot", lot_id)
    if lot["status"] != "TESTED" or lot["pretreatment_tier"] != "NONE":
        fail(ERR_INVALID_LOT_STATE,
             "Only a TESTED lot whose pretreatment_tier is NONE may be accepted.")
    lot["status"] = "ACCEPTED"
    bump(lot)
    return response.ok(lot)


@bp.get("/feedstock-lots/<lot_id>/allocations")
def list_lot_allocations(lot_id):
    validate.auth("FeedstockTrader", "PlantOperator", "ComplianceOfficer")
    lot = find("lot", lot_id)
    rows, limit, offset = listing(domain.lot_allocations(lot["id"]), {"status": "status"})
    return response.page(rows, limit, offset)
