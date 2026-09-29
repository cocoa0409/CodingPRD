"""Distributor chargebacks: assessment, dispute and decision (PRD §3.9)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_BRAND_LEGAL_COUNSEL, ROLE_DISTRIBUTOR,
    STAFF_AND_DISTRIBUTOR, authenticate, require_owner,
)
from calc import (
    SCORE_PER_UNIT, apply_standing, dec, refresh_review_required_for_distributor, rhu, tier_rate,
)
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, serialize, store, touch
from validate import body, req_enum, req_int, req_str

bp = Blueprint("chargebacks", __name__)

DISPUTE_ROUND_CAP = 2
DECISIONS = ["UPHOLD", "REVERSE"]


@bp.post("/distributor-chargebacks")
def assess_chargeback():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    distributor_id = req_str(b, "distributor_id")
    test_purchase_id = req_str(b, "test_purchase_id")
    diverted_units = req_int(b, "diverted_units", 1, None)
    expected_version = req_int(b, "expected_distributor_version", 1, None)

    distributor = lookup.distributor(distributor_id)
    purchase = lookup.test_purchase(test_purchase_id)

    if expected_version != distributor["version"]:
        fail("ERR_STALE_DISTRIBUTOR_VERSION",
             "expected_distributor_version does not match the distributor's current version.")
    if purchase["status"] != "CONFIRMED_UNAUTHORIZED":
        fail("ERR_TEST_PURCHASE_NOT_CONFIRMED",
             "The referenced test purchase must be CONFIRMED_UNAUTHORIZED.")
    unit = store.serial_units.get(purchase.get("traced_serial_unit_id"))
    if unit is None or unit.get("shipped_distributor_id") != distributor_id:
        fail("ERR_DIVERSION_NOT_ATTRIBUTED",
             "The traced unit was not shipped by the accountable distributor.")

    # Pricing reads the pre-event score (PRD §3.9).
    pre_score = dec(distributor["diversion_score"])
    rate = tier_rate(pre_score)
    amount = rate * diverted_units
    delta = SCORE_PER_UNIT * dec(diverted_units)

    # Fiscal ceiling, checked last of all.
    if distributor["chargeback_balance_cents"] + amount > distributor["annual_chargeback_cap_cents"]:
        fail("ERR_CHARGEBACK_CAP_EXCEEDED",
             "The chargeback would exceed the distributor's annual ceiling.")

    row = new_row({
        "distributor_id": distributor_id,
        "test_purchase_id": test_purchase_id,
        "diverted_units": diverted_units,
        "tier_rate_cents_per_unit": rate,
        "amount_cents": amount,
        "score_delta_applied": float(rhu(delta, 1)),
        "status": "ASSESSED",
        "dispute_rounds": 0,
        "dispute_reason": None,
        "decision_reason": None,
    })
    store.chargebacks[row["id"]] = row

    distributor["chargeback_balance_cents"] = distributor["chargeback_balance_cents"] + amount
    apply_standing(distributor, pre_score + delta)
    touch(distributor)
    refresh_review_required_for_distributor(distributor_id)
    return created(serialize(row))


@bp.post("/distributor-chargebacks/<chargeback_id>/dispute")
def dispute(chargeback_id):
    ctx = authenticate([ROLE_DISTRIBUTOR])
    b = body()
    dispute_reason = req_str(b, "dispute_reason", 1, None)
    chargeback = lookup.chargeback(chargeback_id)
    require_owner(ctx, chargeback, distributor_field="distributor_id")
    if chargeback["status"] not in ("ASSESSED", "UPHELD"):
        fail("ERR_INVALID_STATE", "Only an ASSESSED or UPHELD chargeback may be disputed.")
    if chargeback["dispute_rounds"] >= DISPUTE_ROUND_CAP:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED", "The right to dispute has been exhausted.")

    chargeback["status"] = "DISPUTED"
    chargeback["dispute_reason"] = dispute_reason
    touch(chargeback)
    return ok(serialize(chargeback))


@bp.post("/distributor-chargebacks/<chargeback_id>/dispute-decision")
def dispute_decision(chargeback_id):
    authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    decision_reason = req_str(b, "decision_reason", 1, None)
    chargeback = lookup.chargeback(chargeback_id)
    if chargeback["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE", "Only a DISPUTED chargeback may receive a decision.")

    if decision == "UPHOLD":
        chargeback["status"] = "UPHELD"
        chargeback["dispute_rounds"] = chargeback["dispute_rounds"] + 1
        chargeback["decision_reason"] = decision_reason
        touch(chargeback)
        return ok(serialize(chargeback))

    chargeback["status"] = "REVERSED"
    chargeback["decision_reason"] = decision_reason
    touch(chargeback)
    distributor = store.distributors.get(chargeback["distributor_id"])
    if distributor is not None:
        distributor["chargeback_balance_cents"] = (
            distributor["chargeback_balance_cents"] - chargeback["amount_cents"])
        restored = dec(distributor["diversion_score"]) - dec(chargeback["score_delta_applied"])
        apply_standing(distributor, restored)
        touch(distributor)
        refresh_review_required_for_distributor(distributor["id"])
    return ok(serialize(chargeback))


@bp.get("/distributor-chargebacks/<chargeback_id>")
def read_chargeback(chargeback_id):
    ctx = authenticate(STAFF_AND_DISTRIBUTOR)
    row = lookup.chargeback(chargeback_id)
    require_owner(ctx, row, distributor_field="distributor_id")
    return ok(serialize(row))


@bp.get("/distributor-chargebacks")
def list_chargebacks():
    authenticate(STAFF_AND_DISTRIBUTOR)
    rows = lookup.filtered("chargebacks", {
        "distributor_id": "distributor_id",
        "test_purchase_id": "test_purchase_id",
        "status": "status",
    })
    return ok_list(rows)
