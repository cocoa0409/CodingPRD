"""Remittances and the four-intent allocation waterfall (PRD 3.7)."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import ledger, serial, spec

bp = Blueprint("remittances", __name__)

READ_ROLES = (
    middleware.CREDIT_OFFICER,
    middleware.CREDIT_RISK_MANAGER,
    middleware.AUDIT_MANAGER,
    middleware.DEALER_PRINCIPAL,
    middleware.SYSTEM_OPERATOR,
)


def _element(bucket, target_id, principal_cents, fee_cents):
    return {
        "bucket": bucket,
        "target_id": target_id,
        "principal_cents": principal_cents,
        "fee_cents": fee_cents,
    }


def _pay_unit_principal(unit, amount):
    unit["principal_paid_cents"] = int(unit["principal_paid_cents"]) + amount
    unit["outstanding_principal_cents"] = int(unit["outstanding_principal_cents"]) - amount
    db.touch(unit)


@bp.route("/floorplan/remittances", methods=["POST"])
def post_remittance():
    middleware.require(middleware.DEALER_PRINCIPAL)
    data = validate.body()
    dealer_id = validate.req_ref(data, "dealer_id")
    middleware.guard_dealer_id(dealer_id)
    dealer = lookup.dealer(dealer_id)

    target_unit_id = validate.opt_ref(data, "target_unit_id")
    target_unit = lookup.unit(target_unit_id) if target_unit_id is not None else None
    target_obligation_id = validate.opt_ref(data, "target_obligation_id")
    target_obligation = (
        lookup.obligation(target_obligation_id) if target_obligation_id is not None else None
    )

    intent = validate.req_enum(data, "intent", spec.REMITTANCE_INTENTS)
    amount = validate.req_int(data, "amount_cents", minimum=1)
    payment_reference = validate.req_str(data, "payment_reference")
    expected_version = validate.req_int(data, "expected_dealer_version", minimum=0)

    if expected_version != int(dealer["version"]):
        raise ApiError(
            "ERR_STALE_DEALER_VERSION",
            "expected_dealer_version %s does not match the dealership." % expected_version,
        )

    if target_unit is not None:
        if intent == "SOT_CURE":
            if target_unit["funding_status"] != "SOT_OPEN":
                raise ApiError("ERR_UNIT_NOT_FLOORED")
        elif target_unit["funding_status"] not in spec.COLLATERAL_FUNDING_STATUSES:
            raise ApiError("ERR_UNIT_NOT_FLOORED")

    if intent == "CURTAILMENT":
        if target_unit is not None and target_obligation is not None:
            raise ApiError("ERR_REMITTANCE_INTENT_TARGET_MISMATCH")
    else:
        if target_unit is None or target_obligation is not None:
            raise ApiError("ERR_REMITTANCE_INTENT_TARGET_MISMATCH")
    if target_unit is not None and target_unit["dealer_id"] != dealer["id"]:
        raise ApiError("ERR_REMITTANCE_INTENT_TARGET_MISMATCH")
    if target_obligation is not None and target_obligation["dealer_id"] != dealer["id"]:
        raise ApiError("ERR_REMITTANCE_INTENT_TARGET_MISMATCH")

    remaining = amount
    breakdown = []
    applied_principal = 0
    applied_fee = 0
    applied_cure = 0
    touched_units = []
    touched_lines = set()

    def note_unit(unit):
        if unit["id"] not in [u["id"] for u in touched_units]:
            touched_units.append(unit)
        touched_lines.add(unit["credit_line_id"])

    if intent == "CURTAILMENT":
        candidates = ledger.dealer_obligations(dealer["id"], ("DELINQUENT", "DUE"))
        if target_obligation is not None:
            candidates = [o for o in candidates if o["id"] == target_obligation["id"]]
        elif target_unit is not None:
            candidates = [o for o in candidates if o["unit_id"] == target_unit["id"]]
        bucket_one = [o for o in candidates if o["status"] == "DELINQUENT"]
        bucket_two = [o for o in candidates if o["status"] == "DUE"]
        if not bucket_one and not bucket_two:
            raise ApiError("ERR_NO_ALLOCATABLE_OBLIGATION")
        for obligation in bucket_one + bucket_two:
            if remaining == 0:
                break
            unit = db.get("inventory_units", obligation["unit_id"])
            fee_gap = int(obligation["late_fee_cents"]) - int(obligation["fee_paid_cents"])
            take_fee = min(remaining, max(0, fee_gap))
            obligation["fee_paid_cents"] = int(obligation["fee_paid_cents"]) + take_fee
            applied_fee += take_fee
            remaining -= take_fee
            principal_gap = int(obligation["required_principal_cents"]) - int(
                obligation["principal_paid_cents"]
            )
            take_principal = min(remaining, max(0, principal_gap))
            obligation["principal_paid_cents"] = (
                int(obligation["principal_paid_cents"]) + take_principal
            )
            applied_principal += take_principal
            remaining -= take_principal
            if take_principal:
                _pay_unit_principal(unit, take_principal)
            note_unit(unit)
            breakdown.append(
                _element("CURTAILMENT", obligation["id"], take_principal, take_fee)
            )
            if int(obligation["fee_paid_cents"]) == int(obligation["late_fee_cents"]) and int(
                obligation["principal_paid_cents"]
            ) == int(obligation["required_principal_cents"]):
                obligation["status"] = "PAID"
            db.touch(obligation)

    elif intent == "PRINCIPAL_PREPAYMENT":
        take = min(remaining, int(target_unit["outstanding_principal_cents"]))
        if take:
            _pay_unit_principal(target_unit, take)
        applied_principal += take
        remaining -= take
        note_unit(target_unit)
        breakdown.append(_element("PRINCIPAL_PREPAYMENT", target_unit["id"], take, 0))

    elif intent == "UNIT_PAYOFF":
        open_obligations = ledger.unit_obligations(
            target_unit["id"], ("DUE", "DELINQUENT")
        )
        fee_due = sum(
            max(0, int(o["late_fee_cents"]) - int(o["fee_paid_cents"])) for o in open_obligations
        )
        payoff_due = int(target_unit["outstanding_principal_cents"]) + fee_due
        if remaining < payoff_due:
            raise ApiError("ERR_REMITTANCE_BELOW_PAYOFF")
        for obligation in open_obligations:
            gap = max(0, int(obligation["late_fee_cents"]) - int(obligation["fee_paid_cents"]))
            if not gap:
                continue
            obligation["fee_paid_cents"] = int(obligation["fee_paid_cents"]) + gap
            applied_fee += gap
            remaining -= gap
            db.touch(obligation)
            breakdown.append(_element("UNIT_PAYOFF", obligation["id"], 0, gap))
        principal = int(target_unit["outstanding_principal_cents"])
        applied_principal += principal
        remaining -= principal
        breakdown.append(_element("UNIT_PAYOFF", target_unit["id"], principal, 0))
        target_unit["outstanding_principal_cents"] = 0
        target_unit["principal_paid_cents"] = int(target_unit["advance_amount_cents"])
        for obligation in ledger.unit_obligations(
            target_unit["id"], spec.OPEN_OBLIGATION_STATUSES
        ):
            obligation["status"] = "CANCELLED"
            db.touch(obligation)
        target_unit["funding_status"] = "PAID_OFF"
        db.touch(target_unit)
        touched_lines.add(target_unit["credit_line_id"])

    else:  # SOT_CURE
        for incident in ledger.unit_incidents(target_unit["id"], ("OPEN",)):
            if remaining == 0:
                break
            exposure = int(incident["exposure_cents"])
            take = min(remaining, exposure)
            applied_cure += take
            remaining -= take
            breakdown.append(_element("SOT_CURE", incident["id"], take, 0))
            if take >= exposure:
                incident["status"] = "CURED"
                incident["cured_at"] = db.now_str()
                incident["resolution_reason_code"] = "DEALER_PAYOFF"
                db.touch(incident)
                _pay_unit_principal(target_unit, take)
                target_unit["funding_status"] = "FLOORED"
                target_unit["eligibility_status"] = "ELIGIBLE"
                target_unit["ineligibility_reason_code"] = None
                db.touch(target_unit)
                note_unit(target_unit)

    for unit in touched_units:
        if unit["funding_status"] in spec.COLLATERAL_FUNDING_STATUSES:
            ledger.settle_unit_after_payment(unit)

    record = db.insert(
        "remittances",
        {
            "dealer_id": dealer["id"],
            "target_unit_id": target_unit["id"] if target_unit is not None else None,
            "target_obligation_id": (
                target_obligation["id"] if target_obligation is not None else None
            ),
            "intent": intent,
            "status": "APPLIED" if remaining == 0 else "PARTIALLY_APPLIED",
            "amount_cents": amount,
            "payment_reference": payment_reference,
            "applied_principal_cents": applied_principal,
            "applied_fee_cents": applied_fee,
            "applied_sot_cure_cents": applied_cure,
            "unapplied_cents": remaining,
            "allocation_breakdown": breakdown,
            "applied_at": db.now_str(),
        },
    )

    if remaining:
        dealer["unapplied_credit_cents"] = int(dealer["unapplied_credit_cents"]) + remaining
    ledger.recompute_dealer_counters(dealer)
    ledger.recompute_risk(dealer)
    db.touch(dealer)
    for line_id in touched_lines:
        ledger.recompute_availability(db.get("credit_lines", line_id))
    return response.created(serial.remittance(record))


@bp.route("/floorplan/remittances/<remittance_id>", methods=["GET"])
def read_remittance(remittance_id):
    middleware.require(*READ_ROLES)
    record = lookup.remittance(remittance_id)
    middleware.guard_owned(record)
    return response.ok(serial.remittance(record))


@bp.route("/floorplan/remittances", methods=["GET"])
def list_remittances():
    middleware.require(*READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    target_unit_id = response.filter_value("target_unit_id")
    target_obligation_id = response.filter_value("target_obligation_id")
    intent = response.filter_value("intent", spec.REMITTANCE_INTENTS)
    status = response.filter_value("status", spec.REMITTANCE_STATUSES)
    records = response.apply_filters(
        db.rows("remittances"),
        [
            ("dealer_id", dealer_id),
            ("target_unit_id", target_unit_id),
            ("target_obligation_id", target_obligation_id),
            ("intent", intent),
            ("status", status),
        ],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [r for r in records if r["dealer_id"] == scope]
    return response.paginate(records, serial.remittance)
