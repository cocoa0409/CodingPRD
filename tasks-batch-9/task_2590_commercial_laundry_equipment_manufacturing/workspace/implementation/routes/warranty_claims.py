"""Warranty claims: filing, adjudication, void and part-stock movement (PRD 3.9)."""

from flask import g

import lookup
import response
import validate
from db import base_row, bump, db, order_created_asc
from errors import (ERR_BUILD_STATE_INVALID, ERR_CLAIM_NOT_COVERABLE,
                    ERR_CLAIM_STATE_INVALID, ERR_DISTRIBUTOR_STATE_INVALID,
                    ERR_INSUFFICIENT_PART_STOCK, ERR_OWNERSHIP_VIOLATION,
                    ERR_PART_NOT_FITTED, ERR_STALE_PART_VERSION,
                    ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH, fail)
from middleware import (CHANNEL_MANAGER, DISTRIBUTOR, WARRANTY_ANALYST,
                        acting_distributor, endpoint, require_certified)
from services import calc
from services.cascades import refresh_open_claim_count, reproject_part_stock

CLAIM_STATES = ["SUBMITTED", "FULFILLMENT_BLOCKED", "APPROVED", "DENIED", "VOIDED"]
DUTY_CYCLE_CLASSES = ["LIGHT", "STANDARD", "HEAVY"]
DENIAL_REASONS = ["OUT_OF_WARRANTY", "DUTY_CYCLE_ABUSE", "PART_NOT_FITTED"]


def _submitted_count(distributor_id):
    return len([c for c in db.claims.values()
                if c["distributor_id"] == distributor_id
                and c["claim_state"] == "SUBMITTED"])


def register(app):
    @app.post("/clm/warranty-claims")
    @endpoint([DISTRIBUTOR])
    def file_warranty_claim():
        body = validate.parse_body()
        build_order_id = body.id_ref("build_order_id")
        part_id = body.id_ref("part_id")
        distributor_id = body.id_ref("distributor_id")
        technician_id = body.id_ref("reported_by_technician_id")
        failure_cycle_count = body.integer("failure_cycle_count", minimum=1)
        in_service_months = body.integer("in_service_months", minimum=0)
        duty_cycle_class = body.enum("duty_cycle_class", DUTY_CYCLE_CLASSES)
        diagnostics_code = body.string("diagnostics_code", 1, 32)
        part = lookup.part(part_id)                     # rule 17
        build = lookup.build(build_order_id)            # rule 18
        technician = lookup.technician(technician_id)   # rule 20
        distributor = lookup.distributor(distributor_id)  # rule 21
        acting_distributor()                            # rule 22
        if distributor["id"] != g.user_id:              # rule 23
            fail(ERR_OWNERSHIP_VIOLATION,
                 "A distributor may only file claims under its own identity.")
        if build["build_state"] != "ACCEPTED":          # rule 26
            fail(ERR_BUILD_STATE_INVALID,
                 "Only an ACCEPTED unit may carry a warranty claim.")
        if distributor["distributor_state"] == "TERMINATED":   # rule 29
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "A TERMINATED distributor may not file warranty claims.")
        if part["requires_cert_scope"] != "NONE":       # rule 36
            require_certified(technician, part["requires_cert_scope"])
        if (technician["employer"] != "DISTRIBUTOR"     # rule 41
                or technician["distributor_id"] != distributor["id"]):
            fail(ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH,
                 "The reporting technician is not employed by this distributor.")

        model = db.models.get(build["model_id"])
        row = base_row()
        row.update({
            "build_order_id": build["id"],
            "part_id": part["id"],
            "distributor_id": distributor["id"],
            "reported_by_technician_id": technician["id"],
            "failure_cycle_count": failure_cycle_count,
            "in_service_months": in_service_months,
            "duty_cycle_class": duty_cycle_class,
            "diagnostics_code": diagnostics_code,
            "claim_state": "SUBMITTED",
            "effective_rated_cycles": calc.effective_rated_cycles(
                part["rated_duty_cycles"], duty_cycle_class,
                model["product_line"]),
            "coverage_variant": "NONE",
            "covered_amount_cents": 0,
            "denial_reason": "NONE",
            "block_reason": "NONE",
            "adjudicated_by_user_id": None,
            "voided_at": None,
        })
        db.claims[row["id"]] = row
        refresh_open_claim_count(distributor)
        return response.created(row)

    @app.get("/clm/warranty-claims/<claim_id>")
    @endpoint([WARRANTY_ANALYST, CHANNEL_MANAGER, DISTRIBUTOR])
    def read_warranty_claim(claim_id):
        claim = lookup.claim(claim_id)   # rule 15
        if g.role == DISTRIBUTOR:
            distributor = acting_distributor()          # rule 22
            if claim["distributor_id"] != distributor["id"]:   # rule 23
                fail(ERR_OWNERSHIP_VIOLATION,
                     "This claim belongs to another distributor.")
        return response.ok(claim)

    @app.get("/clm/warranty-claims")
    @endpoint([WARRANTY_ANALYST, CHANNEL_MANAGER, DISTRIBUTOR])
    def list_warranty_claims():
        limit, offset = validate.q_pagination()
        build_order_id = validate.q_str("build_order_id")
        part_id = validate.q_str("part_id")
        distributor_id = validate.q_str("distributor_id")
        technician_id = validate.q_str("reported_by_technician_id")
        claim_state = validate.q_enum("claim_state", CLAIM_STATES)
        rows = list(db.claims.values())
        if build_order_id is not None:
            rows = [r for r in rows if r["build_order_id"] == build_order_id]
        if part_id is not None:
            rows = [r for r in rows if r["part_id"] == part_id]
        if distributor_id is not None:
            rows = [r for r in rows if r["distributor_id"] == distributor_id]
        if technician_id is not None:
            rows = [r for r in rows
                    if r["reported_by_technician_id"] == technician_id]
        if claim_state is not None:
            rows = [r for r in rows if r["claim_state"] == claim_state]
        rows = order_created_asc(rows)
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/warranty-claims/<claim_id>/adjudicate")
    @endpoint([WARRANTY_ANALYST])
    def adjudicate_warranty_claim(claim_id):
        body = validate.parse_body()
        decision = body.enum("decision", ["APPROVE", "DENY"])
        expected_part_version = body.integer("expected_part_version")
        denial_reason = body.enum("denial_reason", DENIAL_REASONS,
                                  required=(decision == "DENY"))
        claim = lookup.claim(claim_id)   # rule 15
        if claim["claim_state"] != "SUBMITTED":       # rule 31
            fail(ERR_CLAIM_STATE_INVALID, "Only a SUBMITTED claim may be adjudicated.")
        part = db.parts[claim["part_id"]]
        if expected_part_version != part["version"]:  # rule 33
            fail(ERR_STALE_PART_VERSION,
                 "expected_part_version %s does not match the part's version %s."
                 % (expected_part_version, part["version"]))

        claim["adjudicated_by_user_id"] = g.user_id
        if decision == "DENY":
            claim["claim_state"] = "DENIED"
            claim["denial_reason"] = denial_reason
            bump(claim)
            bump(part)
            distributor = db.distributors.get(claim["distributor_id"])
            if distributor is not None:
                refresh_open_claim_count(distributor)
            return response.ok(claim)

        build = db.builds[claim["build_order_id"]]
        model = db.models[build["model_id"]]
        # rule 38: fitment
        if (model["product_line"] not in part["fits_product_lines"]
                or model["capacity_rating_lb"] < part["fits_min_capacity_lb"]
                or model["capacity_rating_lb"] > part["fits_max_capacity_lb"]):
            fail(ERR_PART_NOT_FITTED, "The claimed part does not fit the built model.")
        # rule 55: coverability
        if (claim["in_service_months"] > part["warranty_months"]
                or claim["failure_cycle_count"] > claim["effective_rated_cycles"]):
            fail(ERR_CLAIM_NOT_COVERABLE,
                 "The failure lies outside the part's warranty entitlement.")
        # rule 56: stock on the shelf
        if part["on_hand_qty"] < 1:
            fail(ERR_INSUFFICIENT_PART_STOCK,
                 "The claimed part has no on-hand stock to reserve.")

        variant, covered = calc.settlement(
            part["unit_price_cents"], part["warranty_months"],
            claim["in_service_months"], claim["failure_cycle_count"],
            claim["effective_rated_cycles"])
        claim["claim_state"] = "APPROVED"
        claim["coverage_variant"] = variant
        claim["covered_amount_cents"] = covered
        bump(claim)

        part["on_hand_qty"] = part["on_hand_qty"] - 1
        part["reserved_qty"] = part["reserved_qty"] + 1
        bump(part)
        reproject_part_stock(part)

        distributor = db.distributors.get(claim["distributor_id"])
        if distributor is not None:
            distributor["warranty_credit_cents"] = (
                distributor["warranty_credit_cents"] + covered)
            distributor["open_claim_count"] = _submitted_count(distributor["id"])
            bump(distributor)
        return response.ok(claim)

    @app.post("/clm/warranty-claims/<claim_id>/void")
    @endpoint([WARRANTY_ANALYST])
    def void_warranty_claim(claim_id):
        body = validate.parse_body()
        body.string("reason", maxlen=500)
        claim = lookup.claim(claim_id)   # rule 15
        if claim["claim_state"] != "APPROVED":       # rule 31
            fail(ERR_CLAIM_STATE_INVALID, "Only an APPROVED claim may be voided.")

        claim["claim_state"] = "VOIDED"
        claim["voided_at"] = db.now
        bump(claim)

        part = db.parts.get(claim["part_id"])
        if part is not None:
            part["on_hand_qty"] = part["on_hand_qty"] + 1
            part["reserved_qty"] = part["reserved_qty"] - 1
            bump(part)
            reproject_part_stock(part)

        distributor = db.distributors.get(claim["distributor_id"])
        if distributor is not None:
            distributor["warranty_credit_cents"] = (
                distributor["warranty_credit_cents"]
                - claim["covered_amount_cents"])
            distributor["open_claim_count"] = _submitted_count(distributor["id"])
            bump(distributor)
        return response.ok(claim)
