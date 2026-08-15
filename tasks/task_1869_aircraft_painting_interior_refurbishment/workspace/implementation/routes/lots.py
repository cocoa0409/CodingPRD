"""SoftGoodLot and BurnTest endpoints (burn certification state machine)."""
from flask import Blueprint, request

from db import STORE, new_id, next_seq, now_iso
from domain import (new_entity, bump, get_or_404, by_created,
                    serialize_lot, serialize_burn_test)
from errors import ref_integrity, invalid_state
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("lots", __name__)

TEST_METHODS = ("VERTICAL_12S", "VERTICAL_60S", "HORIZONTAL_25")
RESULTS = ("PASS", "FAIL")
MAX_RETESTS = 3


@bp.post("/soft-good-lots")
def create_lot():
    auth("ShopTechnician")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    description = field(data, "description", "str")
    material = field(data, "material", "str")
    quantity = field(data, "quantity", "int")
    estimated_weight_lbs = field(data, "estimated_weight_lbs", "num")
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] in ("DELIVERED", "CANCELLED"):
        raise invalid_state("Cannot register a lot for a terminal program")
    lot = new_entity()
    lot.update({
        "program_id": program_id,
        "description": description,
        "material": material,
        "quantity": quantity,
        "estimated_weight_lbs": estimated_weight_lbs,
        "status": "UNCERTIFIED",
        "fail_count": 0,
    })
    STORE.soft_good_lots[lot["id"]] = lot
    return success(serialize_lot(lot), status=201)


@bp.get("/soft-good-lots/<lid>")
def get_lot(lid):
    auth()
    lot = get_or_404(STORE.soft_good_lots, lid, "SoftGoodLot")
    return success(serialize_lot(lot))


@bp.get("/soft-good-lots")
def list_lots():
    auth()
    items = by_created(list(STORE.soft_good_lots.values()))
    for key in ("program_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [l for l in items if l[key] == value]
    return paginate(items, serialize_lot)


@bp.post("/soft-good-lots/<lid>/burn-tests")
def record_burn_test(lid):
    auth("ShopTechnician")
    data = get_body(required=True)
    test_method = field(data, "test_method", "str", enum=TEST_METHODS)
    result = field(data, "result", "str", enum=RESULTS)
    lab_name = field(data, "lab_name", "str")
    lot = get_or_404(STORE.soft_good_lots, lid, "SoftGoodLot")
    if lot["status"] in ("CERTIFIED", "CERT_QUARANTINED"):
        raise invalid_state(
            "Burn tests may not be recorded on CERTIFIED or CERT_QUARANTINED lots")
    prior = [t for t in STORE.burn_tests.values() if t["lot_id"] == lid]
    test = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "lot_id": lid,
        "test_method": test_method,
        "result": result,
        "lab_name": lab_name,
        "test_sequence": len(prior) + 1,
    }
    STORE.burn_tests[test["id"]] = test
    # burn_certification_derivation: judged on the latest recorded test;
    # fails never reset.
    if result == "PASS":
        lot["status"] = "CERTIFIED"
    else:
        lot["fail_count"] += 1
        lot["status"] = ("CERT_QUARANTINED" if lot["fail_count"] >= MAX_RETESTS
                         else "CERT_FAILED")
    bump(lot)
    return success(serialize_burn_test(test), status=201)


@bp.get("/soft-good-lots/<lid>/burn-tests")
def list_burn_tests(lid):
    auth()
    get_or_404(STORE.soft_good_lots, lid, "SoftGoodLot")
    tests = [t for t in STORE.burn_tests.values() if t["lot_id"] == lid]
    tests.sort(key=lambda t: t["test_sequence"])
    return paginate(tests, serialize_burn_test)
