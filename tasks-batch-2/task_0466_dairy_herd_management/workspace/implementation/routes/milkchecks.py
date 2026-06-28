"""MilkCheck routes (PRD §3.7, §3.8) — provisional advance, finalize, cancel."""
from flask import Blueprint, request

import db
import errors
import serializers
import calculations
import domain
from errors import err
from middleware import require_roles
from records import make_record, touch
from response import object_response, array_response
from domain import paginate, sorted_by_creation
from util import parse_datetime
import clock
import validators as V

bp = Blueprint("milkchecks", __name__)


def _eligible_pool(herd_id, settlement_month):
    """Test-day records whose herd_id == herd, whose test_date month ==
    settlement_month, whose owning animal is milk_eligible at the current clock,
    and whose included_in_milk_check_id is null (PRD §3.8).

    Eligibility evaluated against the live logical clock so that advancing the
    clock past a withhold makes the animal's milk poolable again.
    """
    pool = []
    for tdr in db.test_day_records.values():
        if tdr["herd_id"] != herd_id:
            continue
        if tdr.get("included_in_milk_check_id") is not None:
            continue
        test_dt = parse_datetime(tdr["test_date"])
        month = "%04d-%02d" % (test_dt.year, test_dt.month)
        if month != settlement_month:
            continue
        animal = db.animals.get(tdr["animal_id"])
        if animal is None:
            continue
        if not _animal_milk_eligible_now(animal):
            continue
        pool.append(tdr)
    return pool


def _animal_milk_eligible_now(animal):
    """Live milk-eligibility against the logical clock (PRD §3.8/§3.9)."""
    if animal["status"] in ("SOLD", "CULLED", "DIED"):
        return animal["milk_eligible"]
    return not domain.has_live_milk_withhold(animal["id"])


# ---------------------------------------------------------------------------
# Create — open a provisional check and pay an advance (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/herds/milk-checks", methods=["POST"])
@require_roles("CoopSettlementAgent")
def create_milk_check():
    body = V.require_json_object()
    herd_id = V.require_fk(body, "herd_id")
    price_sheet_id = V.require_fk(body, "price_sheet_id")
    # existence
    herd = V.get_or_404("herd", herd_id)
    price_sheet = V.get_or_404("price_sheet", price_sheet_id)
    with db.lock:
        # cross-herd referential (priority 8): price sheet must belong to herd
        if price_sheet["herd_id"] != herd_id:
            raise err(errors.ERR_CROSS_HERD_REFERENCE,
                      "Price sheet belongs to a different herd")
        settlement_month = price_sheet["settlement_month"]
        pool = _eligible_pool(herd_id, settlement_month)
        pooled_milk_lbs = sum(t["milk_weight_lbs"] for t in pool)
        advance_paid = calculations.provisional_advance(
            pooled_milk_lbs, price_sheet["advance_rate_per_cwt"])
        rec = make_record({
            "herd_id": herd_id,
            "price_sheet_id": price_sheet_id,
            "settlement_month": settlement_month,
            "pooled_milk_lbs": pooled_milk_lbs,
            "pooled_fat_lbs": 0,
            "pooled_protein_lbs": 0,
            "pooled_other_solids_lbs": 0,
            "weighted_scc_thousands": 0,
            "advance_paid": advance_paid,
            "gross_settlement": 0,
            "net_payable": 0,
            "status": "PROVISIONAL",
        })
        db.milk_checks[rec["id"]] = rec
        return object_response(serializers.milk_check_out(rec), 201)


@bp.route("/herds/milk-checks", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def list_milk_checks():
    items = list(db.milk_checks.values())
    herd_id = request.args.get("herd_id")
    price_sheet_id = request.args.get("price_sheet_id")
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if price_sheet_id is not None:
        items = [r for r in items if r["price_sheet_id"] == price_sheet_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.milk_check_out(r) for r in page], limit, offset, total)


@bp.route("/herds/milk-checks/<milk_check_id>", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def get_milk_check(milk_check_id):
    rec = V.get_or_404("milk_check", milk_check_id)
    return object_response(serializers.milk_check_out(rec), 200)


def _check_occ(body, milk_check):
    """OCC: expected_milk_check_version must equal MilkCheck.version
    (PRD §2.7). Checked before any business precondition. The field is
    non-optional on these two mutations."""
    if "expected_milk_check_version" not in body or body["expected_milk_check_version"] is None:
        raise err(errors.ERR_INVALID_REQUEST,
                  "expected_milk_check_version is required")
    expected = body["expected_milk_check_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(errors.ERR_INVALID_REQUEST,
                  "expected_milk_check_version must be an integer")
    if expected != milk_check["version"]:
        raise err(errors.ERR_STALE_MILK_CHECK_VERSION,
                  "expected_milk_check_version does not match")


# ---------------------------------------------------------------------------
# Finalize (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/herds/milk-checks/<milk_check_id>/finalize", methods=["POST"])
@require_roles("CoopSettlementAgent")
def finalize_milk_check(milk_check_id):
    body = V.require_json_object()
    rec = V.get_or_404("milk_check", milk_check_id)
    with db.lock:
        # OCC first (priority 4)
        _check_occ(body, rec)
        # state precondition (priority 5)
        if rec["status"] != "PROVISIONAL":
            raise err(errors.ERR_MILK_CHECK_NOT_PROVISIONAL,
                      "Milk check is not PROVISIONAL")
        # non-empty pool (priority 13)
        pool = _eligible_pool(rec["herd_id"], rec["settlement_month"])
        if not pool:
            raise err(errors.ERR_EMPTY_MILK_POOL, "No eligible test-day records to pool")
        price_sheet = db.coop_price_sheets[rec["price_sheet_id"]]
        # pool components
        components = calculations.pool_components(pool)
        rec["pooled_milk_lbs"] = components["pooled_milk_lbs"]
        rec["pooled_fat_lbs"] = components["pooled_fat_lbs"]
        rec["pooled_protein_lbs"] = components["pooled_protein_lbs"]
        rec["pooled_other_solids_lbs"] = components["pooled_other_solids_lbs"]
        rec["weighted_scc_thousands"] = components["weighted_scc_thousands"]
        # settlement
        settlement = calculations.final_settlement(components, price_sheet, rec["advance_paid"])
        rec["gross_settlement"] = settlement["gross_settlement"]
        rec["net_payable"] = settlement["net_payable"]
        # stamp pooled records
        for tdr in pool:
            tdr["included_in_milk_check_id"] = rec["id"]
        rec["status"] = "FINALIZED"
        touch(rec)
        # recompute herd milk_quality_status
        herd = db.herds.get(rec["herd_id"])
        if herd is not None:
            herd["milk_quality_status"] = calculations.herd_milk_quality_status(
                rec["weighted_scc_thousands"])
            touch(herd)
        return object_response(serializers.milk_check_out(rec), 200)


# ---------------------------------------------------------------------------
# Cancel (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/herds/milk-checks/<milk_check_id>/cancel", methods=["POST"])
@require_roles("CoopSettlementAgent")
def cancel_milk_check(milk_check_id):
    body = V.require_json_object()
    rec = V.get_or_404("milk_check", milk_check_id)
    with db.lock:
        _check_occ(body, rec)
        if rec["status"] != "PROVISIONAL":
            raise err(errors.ERR_MILK_CHECK_NOT_PROVISIONAL,
                      "Milk check is not PROVISIONAL")
        rec["status"] = "CANCELLED"
        touch(rec)
        return object_response(serializers.milk_check_out(rec), 200)
