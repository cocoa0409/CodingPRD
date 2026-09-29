"""Certification dossiers: opening, the two review dimensions, resurveys."""

from decimal import Decimal

import lookup
import response
import validate
from db import base_row, bump, db
from errors import (ERR_DOSSIER_ALREADY_OPEN, ERR_DOSSIER_STATE_INVALID,
                    ERR_SEGREGATION_OF_DUTIES, fail)
from flask import g
from middleware import CHANNEL_MANAGER, COMPLIANCE_OFFICER, PRODUCT_ENGINEER, endpoint
from services import calc
from services.cascades import dossiers_of_model

DOSSIER_STATES = ["IN_REVIEW", "CERTIFIED", "REJECTED", "RESURVEY_REQUIRED"]
OPEN_DOSSIER_STATES = ("IN_REVIEW", "CERTIFIED", "RESURVEY_REQUIRED")


def _measurements(body):
    water = body.decimal("measured_water_gal_per_cwt", gt=Decimal(0))
    kwh = body.decimal("measured_kwh_per_cwt", gt=Decimal(0))
    cycles = body.integer("test_cycle_count", minimum=50)
    return water, kwh, cycles


def certify_model(model, dossier):
    """The certification cascade's first hop into the parent model (PRD 3.3)."""
    if model["certification_state"] not in ("DRAFT", "SUSPENDED"):
        return
    model["certification_state"] = "CERTIFIED"
    model["suspended_reason"] = "NONE"
    model["rebate_program_codes"] = list(dossier["qualified_program_codes"])
    model["rebate_amount_cents"] = dossier["rebate_amount_cents"]
    bump(model)


def register(app):
    @app.post("/clm/machine-models/<model_id>/certification-dossiers")
    @endpoint([COMPLIANCE_OFFICER])
    def create_dossier(model_id):
        body = validate.parse_body()
        water, kwh, cycles = _measurements(body)
        model = lookup.model(model_id)
        # rule 50: only one dossier in play per model
        for existing in dossiers_of_model(model["id"]):
            if existing["dossier_state"] in OPEN_DOSSIER_STATES:
                fail(ERR_DOSSIER_ALREADY_OPEN,
                     "The model already has a dossier in %s."
                     % existing["dossier_state"])

        row = base_row()
        row.update({
            "model_id": model["id"],
            "prepared_by_user_id": g.user_id,
            "measured_water_gal_per_cwt": water,
            "measured_kwh_per_cwt": kwh,
            "test_cycle_count": cycles,
            "energy_review_state": "PENDING",
            "water_review_state": "PENDING",
            "energy_reviewer_user_id": None,
            "water_reviewer_user_id": None,
            "dossier_state": "IN_REVIEW",
            "resurvey_reason": "NONE",
            "qualified_program_codes": [],
            "rebate_amount_cents": 0,
            "certified_at": None,
            "resurvey_count": 0,
        })
        db.dossiers[row["id"]] = row
        return response.created(row)

    @app.get("/clm/certification-dossiers/<dossier_id>")
    @endpoint([COMPLIANCE_OFFICER, PRODUCT_ENGINEER, CHANNEL_MANAGER])
    def read_dossier(dossier_id):
        return response.ok(lookup.dossier(dossier_id))

    @app.get("/clm/machine-models/<model_id>/certification-dossiers")
    @endpoint([COMPLIANCE_OFFICER, PRODUCT_ENGINEER, CHANNEL_MANAGER])
    def list_model_dossiers(model_id):
        limit, offset = validate.q_pagination()
        dossier_state = validate.q_enum("dossier_state", DOSSIER_STATES)
        model = lookup.model(model_id)
        rows = dossiers_of_model(model["id"])
        if dossier_state is not None:
            rows = [r for r in rows if r["dossier_state"] == dossier_state]
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/certification-dossiers/<dossier_id>/reviews")
    @endpoint([COMPLIANCE_OFFICER])
    def review_dossier(dossier_id):
        body = validate.parse_body()
        dimension = body.enum("dimension", ["ENERGY", "WATER"])
        decision = body.enum("decision", ["APPROVE", "REJECT"])
        body.string("note", maxlen=1000, required=False)
        dossier = lookup.dossier(dossier_id)

        this_state = "energy_review_state" if dimension == "ENERGY" else "water_review_state"
        this_reviewer = "energy_reviewer_user_id" if dimension == "ENERGY" else "water_reviewer_user_id"
        other_reviewer = "water_reviewer_user_id" if dimension == "ENERGY" else "energy_reviewer_user_id"
        other_state = "water_review_state" if dimension == "ENERGY" else "energy_review_state"

        # rule 25: dossier IN_REVIEW with the addressed dimension still PENDING
        if dossier["dossier_state"] != "IN_REVIEW":
            fail(ERR_DOSSIER_STATE_INVALID,
                 "A review requires dossier_state IN_REVIEW.")
        if dossier[this_state] != "PENDING":
            fail(ERR_DOSSIER_STATE_INVALID,
                 "The %s dimension has already been decided." % dimension)
        # rule 34: segregation of duties
        if g.user_id == dossier["prepared_by_user_id"]:
            fail(ERR_SEGREGATION_OF_DUTIES,
                 "The preparing officer may not review the dossier.")
        if dossier[other_reviewer] is not None and g.user_id == dossier[other_reviewer]:
            fail(ERR_SEGREGATION_OF_DUTIES,
                 "The officer who decided the other dimension may not decide this one.")

        dossier[this_reviewer] = g.user_id
        if decision == "APPROVE":
            dossier[this_state] = "APPROVED"
            if dossier[other_state] == "APPROVED":
                dossier["dossier_state"] = "CERTIFIED"
                dossier["certified_at"] = db.now
                model = db.models.get(dossier["model_id"])
                codes, amount = calc.rebate_qualification(
                    model, dossier, list(db.programs.values()))
                dossier["qualified_program_codes"] = codes
                dossier["rebate_amount_cents"] = amount
                bump(dossier)
                if model is not None:
                    certify_model(model, dossier)
                return response.ok(dossier)
        else:
            dossier[this_state] = "REJECTED"
            dossier["dossier_state"] = "REJECTED"
            dossier["qualified_program_codes"] = []
            dossier["rebate_amount_cents"] = 0
        bump(dossier)
        return response.ok(dossier)

    @app.post("/clm/certification-dossiers/<dossier_id>/resurvey-submissions")
    @endpoint([COMPLIANCE_OFFICER])
    def resurvey_dossier(dossier_id):
        body = validate.parse_body()
        water, kwh, cycles = _measurements(body)
        dossier = lookup.dossier(dossier_id)
        # rule 25: a resurvey submission requires RESURVEY_REQUIRED
        if dossier["dossier_state"] != "RESURVEY_REQUIRED":
            fail(ERR_DOSSIER_STATE_INVALID,
                 "A resurvey submission requires dossier_state RESURVEY_REQUIRED.")
        dossier["measured_water_gal_per_cwt"] = water
        dossier["measured_kwh_per_cwt"] = kwh
        dossier["test_cycle_count"] = cycles
        dossier["dossier_state"] = "IN_REVIEW"
        dossier["energy_review_state"] = "PENDING"
        dossier["water_review_state"] = "PENDING"
        dossier["energy_reviewer_user_id"] = None
        dossier["water_reviewer_user_id"] = None
        dossier["resurvey_reason"] = "NONE"
        dossier["prepared_by_user_id"] = g.user_id
        bump(dossier)
        return response.ok(dossier)
