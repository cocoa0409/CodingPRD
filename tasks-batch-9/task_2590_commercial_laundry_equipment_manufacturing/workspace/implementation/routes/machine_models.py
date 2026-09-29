"""Machine models: registration, reads, lifecycle actions, warranty analysis."""

from decimal import Decimal

import lookup
import response
import validate
from db import base_row, bump, db, order_created_desc
from errors import (ERR_CAPACITY_RATING_OUT_OF_BAND, ERR_DUPLICATE_RESOURCE_CODE,
                    ERR_MODEL_STATE_INVALID, ERR_PAYMENT_MODULE_NOT_SUPPORTED, fail)
from middleware import (CHANNEL_MANAGER, COMPLIANCE_OFFICER, DISTRIBUTOR,
                        PLANT_MANAGER, PRODUCT_ENGINEER, QUALITY_INSPECTOR,
                        TECHNICIAN, TRAINING_ADMINISTRATOR, WARRANTY_ANALYST,
                        endpoint)
from services import calc
from services.cascades import builds_of_model
from validate import PAYMENT_MODULES, PRODUCT_LINES

CERTIFICATION_STATES = ["DRAFT", "CERTIFIED", "RELEASED", "SUSPENDED"]
DUTY_CYCLE_CLASSES = ["LIGHT", "STANDARD", "HEAVY"]
COMPONENT_CLASSES = ["DRUM", "BEARING", "CONTROL_BOARD", "PAYMENT_MODULE", "MOTOR",
                     "DIAGNOSTIC_TOOL"]


def register(app):
    @app.post("/clm/machine-models")
    @endpoint([PRODUCT_ENGINEER])
    def create_machine_model():
        body = validate.parse_body()
        model_code = body.code("model_code")
        product_line = body.enum("product_line", PRODUCT_LINES)
        capacity_rating_lb = body.integer("capacity_rating_lb")
        rated_water = body.decimal("rated_water_gal_per_cwt", gt=Decimal(0))
        rated_kwh = body.decimal("rated_kwh_per_cwt", gt=Decimal(0))
        drum_alloy_grade = body.enum("drum_alloy_grade",
                                     ["AISI_304", "AISI_316", "DUPLEX_2205"])
        payment_module_options = body.enum_array("payment_module_options",
                                                 PAYMENT_MODULES, required=False,
                                                 default=[], non_empty=False)
        list_price_cents = body.integer("list_price_cents", minimum=1)
        max_rework_cycles = body.integer("max_rework_cycles", minimum=0, maximum=3,
                                         required=False, default=2)
        min_first_pass_yield_pct = body.decimal(
            "min_first_pass_yield_pct", minimum=Decimal("0.00"),
            maximum=Decimal("100.00"), required=False, default=Decimal("80.00"))

        # rule 42: payment-module compatibility
        if product_line == "VENDED" and len(payment_module_options) == 0:
            fail(ERR_PAYMENT_MODULE_NOT_SUPPORTED,
                 "A VENDED model must offer at least one payment module.")
        if product_line != "VENDED" and len(payment_module_options) > 0:
            fail(ERR_PAYMENT_MODULE_NOT_SUPPORTED,
                 "Only a VENDED model may declare payment_module_options.")
        # rule 48: natural-key uniqueness
        if any(m["model_code"] == model_code for m in db.models.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "model_code '%s' already exists." % model_code)
        # rule 49: capacity band, inclusive at both ends
        low, high = calc.CAPACITY_BANDS[product_line]
        if capacity_rating_lb < low or capacity_rating_lb > high:
            fail(ERR_CAPACITY_RATING_OUT_OF_BAND,
                 "capacity_rating_lb must be between %d and %d for %s."
                 % (low, high, product_line))

        row = base_row()
        row.update({
            "model_code": model_code,
            "product_line": product_line,
            "capacity_rating_lb": capacity_rating_lb,
            "rated_water_gal_per_cwt": rated_water,
            "rated_kwh_per_cwt": rated_kwh,
            "drum_alloy_grade": drum_alloy_grade,
            "payment_module_options": payment_module_options,
            "max_rework_cycles": max_rework_cycles,
            "min_first_pass_yield_pct": min_first_pass_yield_pct,
            "list_price_cents": list_price_cents,
            "certification_state": "DRAFT",
            "suspended_reason": "NONE",
            "accepted_unit_count": 0,
            "scrapped_unit_count": 0,
            "quality_hold_unit_count": 0,
            "first_pass_yield_pct": Decimal("0.00"),
            "rebate_program_codes": [],
            "rebate_amount_cents": 0,
        })
        db.models[row["id"]] = row
        return response.created(row)

    @app.get("/clm/machine-models/<model_id>")
    @endpoint([PRODUCT_ENGINEER, COMPLIANCE_OFFICER, PLANT_MANAGER,
               TRAINING_ADMINISTRATOR, CHANNEL_MANAGER, WARRANTY_ANALYST,
               TECHNICIAN, QUALITY_INSPECTOR, DISTRIBUTOR])
    def read_machine_model(model_id):
        return response.ok(lookup.model(model_id))

    @app.get("/clm/machine-models")
    @endpoint([PRODUCT_ENGINEER, COMPLIANCE_OFFICER, PLANT_MANAGER, CHANNEL_MANAGER,
               WARRANTY_ANALYST, DISTRIBUTOR])
    def list_machine_models():
        limit, offset = validate.q_pagination()
        product_line = validate.q_enum("product_line", PRODUCT_LINES)
        certification_state = validate.q_enum("certification_state",
                                              CERTIFICATION_STATES)
        rows = list(db.models.values())
        if product_line is not None:
            rows = [r for r in rows if r["product_line"] == product_line]
        if certification_state is not None:
            rows = [r for r in rows if r["certification_state"] == certification_state]
        rows = order_created_desc(rows)
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/machine-models/<model_id>/lifecycle-actions")
    @endpoint([PRODUCT_ENGINEER])
    def machine_model_lifecycle_action(model_id):
        body = validate.parse_body()
        action = body.enum("action", ["RELEASE", "SUSPEND"])
        body.string("reason", maxlen=500, required=False)
        model = lookup.model(model_id)
        # rule 24: the model's certification_state permits the action
        if action == "RELEASE":
            if model["certification_state"] != "CERTIFIED":
                fail(ERR_MODEL_STATE_INVALID,
                     "A release requires certification_state CERTIFIED.")
            model["certification_state"] = "RELEASED"
            bump(model)
        else:
            if model["certification_state"] != "RELEASED":
                fail(ERR_MODEL_STATE_INVALID,
                     "A manual suspension requires certification_state RELEASED.")
            model["certification_state"] = "SUSPENDED"
            model["suspended_reason"] = "MANUAL"
            model["rebate_program_codes"] = []
            model["rebate_amount_cents"] = 0
            bump(model)
        return response.ok(model)

    @app.get("/clm/machine-models/<model_id>/warranty-analysis")
    @endpoint([WARRANTY_ANALYST, PRODUCT_ENGINEER])
    def machine_model_warranty_analysis(model_id):
        duty_cycle_class = validate.q_enum("duty_cycle_class", DUTY_CYCLE_CLASSES)
        model = lookup.model(model_id)
        build_ids = {b["id"] for b in builds_of_model(model["id"])}
        claims = [c for c in db.claims.values() if c["build_order_id"] in build_ids]
        if duty_cycle_class is not None:
            claims = [c for c in claims if c["duty_cycle_class"] == duty_cycle_class]

        def covered(claim):
            return 0 if claim["claim_state"] == "VOIDED" else claim["covered_amount_cents"]

        component_breakdown = {}
        duty_breakdown = {}
        for claim in claims:
            part = db.parts.get(claim["part_id"])
            key = part["component_class"] if part is not None else "UNKNOWN"
            bucket = component_breakdown.setdefault(
                key, {"claim_count": 0, "covered_amount_total_cents": 0})
            bucket["claim_count"] += 1
            bucket["covered_amount_total_cents"] += covered(claim)
            bucket = duty_breakdown.setdefault(
                claim["duty_cycle_class"],
                {"claim_count": 0, "covered_amount_total_cents": 0})
            bucket["claim_count"] += 1
            bucket["covered_amount_total_cents"] += covered(claim)

        data = {
            "model_id": model["id"],
            "claim_count": len(claims),
            "approved_claim_count": len([c for c in claims
                                         if c["claim_state"] == "APPROVED"]),
            "denied_claim_count": len([c for c in claims
                                       if c["claim_state"] == "DENIED"]),
            "blocked_claim_count": len([c for c in claims
                                        if c["claim_state"] == "FULFILLMENT_BLOCKED"]),
            "voided_claim_count": len([c for c in claims
                                       if c["claim_state"] == "VOIDED"]),
            "covered_amount_total_cents": sum(covered(c) for c in claims),
            "full_replacement_count": len([c for c in claims
                                           if c["coverage_variant"] == "FULL_REPLACEMENT"]),
            "pro_rata_count": len([c for c in claims
                                   if c["coverage_variant"] == "PRO_RATA"]),
            "component_class_breakdown": component_breakdown,
            "duty_cycle_breakdown": duty_breakdown,
        }
        return response.ok(data)
