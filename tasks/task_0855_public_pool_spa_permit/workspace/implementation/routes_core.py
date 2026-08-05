"""Clock control, operators, fee ledger and facilities."""

from flask import g

import constants as C
import domain
from auth import authenticate, authorize, own_or_403
from clock import LOGICAL_CLOCK, render_datetime
from errors import ApiError
from helpers import facility_or_404, get_or_404, matches, paged_list
from response import object_response
from serializers import (facility_json, ledger_entry_json, operator_json)
from store import DB, base_record, touch
from validation import (bad, json_body, opt_bool, opt_date, opt_enum,
                        opt_enum_list, opt_int, opt_number, opt_string, qs,
                        req_date, req_datetime, req_enum, req_int, req_number,
                        req_string)


def register(app):

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authenticate()
        authorize("HealthAuthorityAdmin")
        body = json_body()
        moment = req_datetime(body, "to_iso8601")
        LOGICAL_CLOCK.set(moment)
        return object_response({"current_utc": render_datetime(LOGICAL_CLOCK.now())})

    # ------------------------------------------------------------------
    # operators
    # ------------------------------------------------------------------
    @app.route("/operators", methods=["POST"])
    def create_operator():
        authenticate()
        authorize("Anonymous")
        body = json_body()
        legal_name = req_string(body, "legal_name", min_len=1, max_len=200)
        contact_email = req_string(body, "contact_email", min_len=1)
        if "@" not in contact_email:
            bad("Field 'contact_email' must contain '@'.")
        phone = opt_string(body, "phone")
        rec = base_record()
        rec.update({
            "legal_name": legal_name,
            "contact_email": contact_email,
            "phone": phone,
        })
        DB.operators[rec["id"]] = rec
        return object_response(operator_json(rec), 201)

    @app.route("/operators/<operator_id>", methods=["GET"])
    def read_operator(operator_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        rec = get_or_404(DB.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
        return object_response(operator_json(rec))

    @app.route("/operators/<operator_id>/payments", methods=["POST"])
    def create_payment(operator_id):
        authenticate()
        authorize("Operator")
        operator = get_or_404(DB.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
        body = json_body()
        amount_cents = req_int(body, "amount_cents", minimum=1)
        reference_note = opt_string(body, "reference_note")
        own_or_403(operator["id"])
        entry = domain.post_ledger_entry(operator["id"], "PAYMENT", -amount_cents,
                                         permit_id=None,
                                         reference_note=reference_note)
        return object_response(ledger_entry_json(entry), 201)

    # ------------------------------------------------------------------
    # fee ledger
    # ------------------------------------------------------------------
    @app.route("/fee-ledger-entries/<entry_id>", methods=["GET"])
    def read_ledger_entry(entry_id):
        authenticate()
        authorize("Operator", "HealthAuthorityAdmin")
        rec = get_or_404(DB.ledger_entries, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")
        return object_response(ledger_entry_json(rec))

    @app.route("/fee-ledger-entries", methods=["GET"])
    def list_ledger_entries():
        authenticate()
        authorize("Operator", "HealthAuthorityAdmin")
        f_operator = qs("operator_id")
        f_permit = qs("permit_id")
        f_type = qs("entry_type")
        rows = [e for e in DB.ledger_entries.values()
                if matches(e["operator_id"], f_operator)
                and matches(e["permit_id"], f_permit)
                and matches(e["entry_type"], f_type)]
        return paged_list(rows, ledger_entry_json)

    # ------------------------------------------------------------------
    # facilities
    # ------------------------------------------------------------------
    @app.route("/facilities", methods=["POST"])
    def create_facility():
        authenticate()
        authorize("Operator")
        body = json_body()
        operator_id = req_string(body, "operator_id")
        name = req_string(body, "name", min_len=1, max_len=200)
        facility_class = req_enum(body, "facility_class", C.FACILITY_CLASSES)
        surface_area_sqft = req_number(body, "surface_area_sqft", exclusive_min=0)
        water_volume_gallons = req_int(body, "water_volume_gallons", minimum=0)
        max_depth_feet = req_number(body, "max_depth_feet", exclusive_min=0)
        drain_count = req_int(body, "drain_count", minimum=1)
        features = opt_enum_list(body, "features", C.FEATURES, default=[])
        is_seasonal = opt_bool(body, "is_seasonal", default=False)
        season_start_date = opt_date(body, "season_start_date")
        season_end_date = opt_date(body, "season_end_date")
        requires_plan_review = opt_bool(body, "requires_plan_review", default=False)

        if is_seasonal:
            if season_start_date is None or season_end_date is None:
                bad("A seasonal facility requires both season_start_date and "
                    "season_end_date.")
            if season_end_date < season_start_date:
                bad("season_end_date must be on or after season_start_date.")
        else:
            if season_start_date is not None or season_end_date is not None:
                bad("A non-seasonal facility must not carry season dates.")

        own_or_403(operator_id)
        get_or_404(DB.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")

        rec = base_record()
        rec.update({
            "operator_id": operator_id,
            "name": name,
            "facility_class": facility_class,
            "surface_area_sqft": surface_area_sqft,
            "water_volume_gallons": water_volume_gallons,
            "max_depth_feet": max_depth_feet,
            "drain_count": drain_count,
            "features": features,
            "is_seasonal": is_seasonal,
            "season_start_date": season_start_date,
            "season_end_date": season_end_date,
            "requires_plan_review": requires_plan_review,
        })
        DB.facilities[rec["id"]] = rec
        return object_response(facility_json(rec), 201)

    @app.route("/facilities/<facility_id>", methods=["GET"])
    def read_facility(facility_id):
        authenticate()
        authorize("Operator", "Inspector", "PlanReviewer", "HealthAuthorityAdmin")
        rec = facility_or_404(facility_id)
        return object_response(facility_json(rec))

    @app.route("/facilities", methods=["GET"])
    def list_facilities():
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        f_operator = qs("operator_id")
        f_class = qs("facility_class")
        f_posture = qs("operating_posture")
        rows = []
        for fac in DB.facilities.values():
            if not matches(fac["operator_id"], f_operator):
                continue
            if not matches(fac["facility_class"], f_class):
                continue
            if f_posture is not None:
                posture, _reason = domain.operating_posture(fac)
                if posture != f_posture:
                    continue
            rows.append(fac)
        return paged_list(rows, facility_json)

    @app.route("/facilities/<facility_id>", methods=["PATCH"])
    def patch_facility(facility_id):
        authenticate()
        authorize("Operator")
        rec = facility_or_404(facility_id)
        body = json_body()

        name = opt_string(body, "name", min_len=1, max_len=200)
        facility_class = opt_enum(body, "facility_class", C.FACILITY_CLASSES)
        surface_area_sqft = opt_number(body, "surface_area_sqft", exclusive_min=0)
        water_volume_gallons = opt_int(body, "water_volume_gallons", minimum=0)
        max_depth_feet = opt_number(body, "max_depth_feet", exclusive_min=0)
        drain_count = opt_int(body, "drain_count", minimum=1)
        features = opt_enum_list(body, "features", C.FEATURES)
        is_seasonal = opt_bool(body, "is_seasonal")
        requires_plan_review = opt_bool(body, "requires_plan_review")
        season_start_date = opt_date(body, "season_start_date")
        season_end_date = opt_date(body, "season_end_date")
        start_given = "season_start_date" in body
        end_given = "season_end_date" in body

        effective_seasonal = rec["is_seasonal"] if is_seasonal is None else is_seasonal
        new_start = season_start_date if start_given else rec["season_start_date"]
        new_end = season_end_date if end_given else rec["season_end_date"]

        if effective_seasonal:
            if new_start is None or new_end is None:
                bad("A seasonal facility requires both season_start_date and "
                    "season_end_date.")
            if new_end < new_start:
                bad("season_end_date must be on or after season_start_date.")
        else:
            if (start_given and season_start_date is not None) or \
               (end_given and season_end_date is not None):
                bad("A non-seasonal facility must not carry season dates.")
            new_start = None
            new_end = None

        own_or_403(rec["operator_id"])

        if name is not None:
            rec["name"] = name
        if facility_class is not None:
            rec["facility_class"] = facility_class
        if surface_area_sqft is not None:
            rec["surface_area_sqft"] = surface_area_sqft
        if water_volume_gallons is not None:
            rec["water_volume_gallons"] = water_volume_gallons
        if max_depth_feet is not None:
            rec["max_depth_feet"] = max_depth_feet
        if drain_count is not None:
            rec["drain_count"] = drain_count
        if features is not None:
            rec["features"] = features
        if requires_plan_review is not None:
            rec["requires_plan_review"] = requires_plan_review
        rec["is_seasonal"] = effective_seasonal
        rec["season_start_date"] = new_start
        rec["season_end_date"] = new_end
        touch(rec)
        return object_response(facility_json(rec))
