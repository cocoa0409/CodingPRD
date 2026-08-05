"""The sponsor-hospital claim cycle (PRD 3.10)."""

from flask import Blueprint

import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import billing, calc, serialize

bp = Blueprint("charges", __name__)


def _visit_and_student(charge):
    visit = store.get("visits", charge["visit_id"])
    student = store.get("students", charge["student_id"])
    return visit, student


def _settle(charge, rerun_floor):
    visit, student = _visit_and_student(charge)
    if visit is not None and student is not None:
        billing.settle_visit(visit, student, rerun_floor=rerun_floor)


@bp.get("/sbhc/charges/<id>")
def read_charge(id):
    op = Op("GET /sbhc/charges/{id}", ["BillingSpecialist", "Registrar", "SbhcAdmin"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("charge")))


@bp.get("/sbhc/charges")
def list_charges():
    op = Op("GET /sbhc/charges", ["BillingSpecialist", "Registrar", "SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("charges")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "visit_id": "visit_id",
            "status": "status",
            "service_category": "service_category",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/charges/<id>/submit-claim")
def submit_claim(id):
    op = Op("POST /sbhc/charges/{id}/submit-claim", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")

    def _state(op):
        if op.get("charge")["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only a PENDING charge may be submitted.")

    def _routing(op):
        if op.get("charge")["payer_route"] not in ("MEDICAID", "PRIVATE_INSURANCE"):
            raise ApiError(
                "ERR_CLAIM_NOT_APPLICABLE", "A self-pay charge cannot be claimed."
            )

    op.hook(17, _state)
    op.hook(32, _routing)
    op.run()

    charge = op.get("charge")
    charge["status"] = "CLAIM_SUBMITTED"
    store.touch(charge)
    _settle(charge, rerun_floor=False)
    return envelope.ok(serialize.dump(charge))


@bp.post("/sbhc/charges/<id>/adjudicate")
def adjudicate(id):
    op = Op("POST /sbhc/charges/{id}/adjudicate", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.schema(
        [
            Field("outcome", "enum", required=True, values=config.ADJUDICATION_OUTCOMES),
            Field("payer_paid_amount_cents", "integer"),
            Field("denial_reason", "string"),
        ]
    )

    def _outcome_fields(op):
        charge = op.get("charge")
        if op.body["outcome"] == "PAID":
            amount = op.body.get("payer_paid_amount_cents")
            if amount is None:
                raise ApiError(
                    "ERR_VALIDATION",
                    "payer_paid_amount_cents is required on a PAID adjudication.",
                )
            if amount < 0 or amount > charge["gross_amount_cents"]:
                raise ApiError(
                    "ERR_VALIDATION",
                    "payer_paid_amount_cents must be between 0 and the gross amount.",
                )
        else:
            reason = op.body.get("denial_reason")
            if not isinstance(reason, str) or not reason:
                raise ApiError(
                    "ERR_VALIDATION", "denial_reason is required on a DENIED adjudication."
                )

    def _state(op):
        if op.get("charge")["status"] not in ("CLAIM_SUBMITTED", "CLAIM_APPEALED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "Only a CLAIM_SUBMITTED or CLAIM_APPEALED charge may be adjudicated.",
            )

    op.custom(_outcome_fields)
    op.hook(17, _state)
    op.run()

    charge = op.get("charge")
    if op.body["outcome"] == "PAID":
        charge["payer_paid_amount_cents"] = op.body["payer_paid_amount_cents"]
        charge["final_patient_responsibility_cents"] = calc.final_responsibility(
            charge, charge["payer_paid_amount_cents"]
        )
        charge["patient_responsibility_cents"] = (
            charge["final_patient_responsibility_cents"] + charge["floor_adjustment_cents"]
        )
        charge["status"] = "PAID"
    else:
        charge["denial_reason"] = op.body["denial_reason"]
        charge["payer_paid_amount_cents"] = 0
        charge["status"] = "CLAIM_DENIED"
    store.touch(charge)
    _settle(charge, rerun_floor=True)
    return envelope.ok(serialize.dump(charge))


@bp.post("/sbhc/charges/<id>/appeal")
def appeal(id):
    op = Op("POST /sbhc/charges/{id}/appeal", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.schema([Field("appeal_note", "string", required=True)])

    def _state(op):
        if op.get("charge")["status"] != "CLAIM_DENIED":
            raise ApiError("ERR_INVALID_STATE", "Only a CLAIM_DENIED charge may be appealed.")

    def _cap(op):
        if op.get("charge")["appeal_count"] >= config.MAX_CLAIM_APPEALS:
            raise ApiError(
                "ERR_APPEAL_LIMIT_EXCEEDED", "Both appeals have already been used."
            )

    op.hook(17, _state)
    op.hook(32, _cap)
    op.run()

    charge = op.get("charge")
    charge["appeal_count"] = charge["appeal_count"] + 1
    charge["status"] = "CLAIM_APPEALED"
    store.touch(charge)
    _settle(charge, rerun_floor=False)
    return envelope.ok(serialize.dump(charge))


@bp.post("/sbhc/charges/<id>/write-off")
def write_off(id):
    op = Op("POST /sbhc/charges/{id}/write-off", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.schema([Field("reason", "string", required=True)])

    def _state(op):
        if op.get("charge")["status"] != "CLAIM_DENIED":
            raise ApiError("ERR_INVALID_STATE", "Only a CLAIM_DENIED charge may be written off.")

    def _cap(op):
        if op.get("charge")["appeal_count"] != config.MAX_CLAIM_APPEALS:
            raise ApiError(
                "ERR_WRITE_OFF_NOT_PERMITTED",
                "A write-off is only permitted once both appeals have been used.",
            )

    op.hook(17, _state)
    op.hook(32, _cap)
    op.run()

    charge = op.get("charge")
    charge["write_off_amount_cents"] = (
        charge["gross_amount_cents"]
        - charge["payer_paid_amount_cents"]
        - charge["patient_responsibility_cents"]
    )
    charge["status"] = "WRITTEN_OFF"
    store.touch(charge)
    _settle(charge, rerun_floor=False)
    return envelope.ok(serialize.dump(charge))


@bp.post("/sbhc/charges/<id>/record-patient-payment")
def record_patient_payment(id):
    op = Op("POST /sbhc/charges/{id}/record-patient-payment", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.schema([Field("amount_cents", "integer", required=True)])

    def _state(op):
        if op.get("charge")["status"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE", "Only a PENDING charge may record a family payment."
            )

    def _money(op):
        charge = op.get("charge")
        if charge["payer_route"] != "SELF_PAY":
            raise ApiError(
                "ERR_CLAIM_NOT_APPLICABLE",
                "Only a self-pay charge records a family payment.",
            )
        if op.body["amount_cents"] != charge["patient_responsibility_cents"]:
            raise ApiError(
                "ERR_PAYMENT_AMOUNT_MISMATCH",
                "amount_cents must equal the charge's patient responsibility exactly.",
            )

    op.hook(17, _state)
    op.hook(32, _money)
    op.run()

    charge = op.get("charge")
    charge["patient_paid_amount_cents"] = op.body["amount_cents"]
    charge["status"] = "PAID"
    store.touch(charge)
    _settle(charge, rerun_floor=False)
    return envelope.ok(serialize.dump(charge))


@bp.post("/sbhc/charges/<id>/reverse")
def reverse(id):
    op = Op("POST /sbhc/charges/{id}/reverse", ["BillingSpecialist"])
    op.path_id("charge", "charges", id, "ERR_CHARGE_NOT_FOUND")
    op.schema([Field("reason", "string", required=True)])

    def _state(op):
        if op.get("charge")["status"] not in (
            "PENDING",
            "CLAIM_SUBMITTED",
            "CLAIM_DENIED",
            "CLAIM_APPEALED",
        ):
            raise ApiError("ERR_INVALID_STATE", "This charge cannot be reversed.")

    op.hook(17, _state)
    op.run()

    charge = op.get("charge")
    charge["status"] = "REVERSED"
    charge["floor_adjustment_cents"] = 0
    store.touch(charge)
    _settle(charge, rerun_floor=True)
    return envelope.ok(serialize.dump(charge))
