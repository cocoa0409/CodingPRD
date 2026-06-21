"""Facility, PdpmRate, and QualityMeasure endpoints (PRD §3.1)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from gate import gate
from services import calc, lookups


def register(app):
    # ---- Facility ----
    @app.route("/snf/facilities", methods=["POST"])
    def create_facility():
        gate(["Administrator"])
        body = V.get_body()
        name = V.as_str(V.require(body, "name"), "name")
        ccn = V.as_str(V.require(body, "cms_certification_number"), "cms_certification_number")
        bed_count = V.as_int(V.require(body, "certified_bed_count"), "certified_bed_count", minimum=1)
        health = V.opt(body, "health_inspection_rating", 3)
        staffing = V.opt(body, "staffing_rating", 3)
        health = V.as_int(health, "health_inspection_rating", minimum=1, maximum=5)
        staffing = V.as_int(staffing, "staffing_rating", minimum=1, maximum=5)
        # cms_certification_number unique across all Facility
        for f in db.facilities.values():
            if f["cms_certification_number"] == ccn:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 "cms_certification_number must be unique")
        obj = {
            "name": name,
            "cms_certification_number": ccn,
            "certified_bed_count": bed_count,
            "occupied_bed_count": 0,
            "health_inspection_rating": health,
            "staffing_rating": staffing,
            "quality_measure_rating": None,
            "overall_star_rating": None,
        }
        db.stamp_create(obj)
        db.facilities[obj["id"]] = obj
        # Initialize computed star components via the baseline (no QM rows yet).
        lookups.recompute_facility_stars(obj, touch_if_changed=False)
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/facilities/<fid>", methods=["GET"])
    def get_facility(fid):
        gate(["Administrator", "AdmissionsCoordinator", "MdsCoordinator",
              "BillingAnalyst", "Physician", "Therapist"])
        obj = lookups.get_facility(fid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/facilities/<fid>/star-summary", methods=["GET"])
    def facility_star_summary(fid):
        gate(["Administrator", "BillingAnalyst"])
        obj = lookups.get_facility(fid)
        # Recompute (a mutation if anything changed) before returning (PRD §3.1).
        lookups.recompute_facility_stars(obj, touch_if_changed=True)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/facilities/<fid>/quality-measures", methods=["POST"])
    def create_quality_measure(fid):
        gate(["Administrator"])
        facility = lookups.get_facility(fid)
        body = V.get_body()
        code = V.as_enum(V.require(body, "measure_code"), "measure_code", set(calc.MEASURE_CODES))
        numerator = V.as_int(V.require(body, "numerator"), "numerator", minimum=0)
        denominator = V.as_int(V.require(body, "denominator"), "denominator", minimum=1)
        reporting_period = V.as_str(V.require(body, "reporting_period"), "reporting_period")
        pts = calc.measure_points(code, numerator, denominator)
        obj = {
            "facility_id": fid,
            "measure_code": code,
            "numerator": numerator,
            "denominator": denominator,
            "reporting_period": reporting_period,
            "measure_points": pts,
        }
        db.stamp_create(obj)
        db.quality_measures[obj["id"]] = obj
        # Recording a quality measure recomputes the facility star rating (PRD §3.1).
        lookups.recompute_facility_stars(facility, touch_if_changed=True)
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/facilities/<fid>/quality-measures", methods=["GET"])
    def list_quality_measures(fid):
        gate(["Administrator", "BillingAnalyst"])
        lookups.get_facility(fid)
        limit, offset = V.pagination(request.args)
        rows = lookups.quality_measures_for_facility(fid)
        code = request.args.get("measure_code")
        if code is not None:
            rows = [r for r in rows if r["measure_code"] == code]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    # ---- PdpmRate ----
    @app.route("/snf/pdpm-rates", methods=["POST"])
    def create_pdpm_rate():
        gate(["Administrator"])
        body = V.get_body()
        component = V.as_enum(V.require(body, "component"), "component",
                              {"PT", "OT", "SLP", "NURSING", "NTA"})
        case_mix_group = V.as_str(V.require(body, "case_mix_group"), "case_mix_group")
        case_mix_index = V.as_number(V.require(body, "case_mix_index"), "case_mix_index", gt=0)
        base_rate_cents = V.as_int(V.require(body, "base_rate_cents"), "base_rate_cents", minimum=0)
        effective_from = V.require(body, "effective_from")
        V.as_datetime(effective_from, "effective_from")
        active = V.opt(body, "active", True)
        active = V.as_bool(active, "active")
        obj = {
            "component": component,
            "case_mix_group": case_mix_group,
            "case_mix_index": case_mix_index,
            "base_rate_cents": base_rate_cents,
            "effective_from": effective_from,
            "active": active,
        }
        db.stamp_create(obj)
        db.pdpm_rates[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/pdpm-rates", methods=["GET"])
    def list_pdpm_rates():
        gate(["Administrator", "BillingAnalyst"])
        limit, offset = V.pagination(request.args)
        rows = list(db.pdpm_rates.values())
        component = request.args.get("component")
        if component is not None:
            rows = [r for r in rows if r["component"] == component]
        active = request.args.get("active")
        if active is not None:
            want = active.lower() == "true"
            rows = [r for r in rows if bool(r.get("active")) == want]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)
