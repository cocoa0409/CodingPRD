"""Inspections, water tests and treatment recommendations."""

import calc
import common
import serialize
from core import (
    ApiError, F, add_days, d, db, endpoint, hours_between, whole_days_between,
)

RETEST_WINDOW_SECONDS = calc.RETEST_WINDOW_DAYS * 86400


# ==========================================================================
# 4.8 Inspections
# ==========================================================================

@endpoint("POST", "/water-service/inspections", ["Dispatcher", "PlatformAdmin"],
          code=201, fields=[
              F("well_profile_id", "string"),
              F("technician_id", "string"),
              F("scheduled_for", "datetime"),
          ])
def create_inspection(ctx):
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Technician", ctx.body["technician_id"])
    row = ctx.new("Inspection", {
        "well_profile_id": ctx.body["well_profile_id"],
        "technician_id": ctx.body["technician_id"],
        "status": "SCHEDULED",
        "scheduled_for": ctx.body["scheduled_for"],
        "measured_yield_gpm": None,
        "static_level_feet": None,
        "observed_drawdown_gallons": None,
        "completed_at": None,
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/inspections/<inspection_id>",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician"], read=True,
          path_params=[("inspection_id", "Inspection")])
def read_inspection(ctx):
    return serialize.dump(ctx.path["inspection_id"])


@endpoint("GET", "/water-service/inspections",
          ["PlatformAdmin", "Dispatcher", "Estimator", "Technician"], read=True,
          paginated=True, filters=["well_profile_id", "technician_id", "status"])
def list_inspections(ctx):
    return db.all("Inspection")


@endpoint("POST", "/water-service/inspections/<inspection_id>/start", ["Technician"],
          path_params=[("inspection_id", "Inspection")],
          scope=common.scope(technician=lambda c: c.path["inspection_id"]["technician_id"]),
          g5=common.state_gate("inspection_id", "status", ("SCHEDULED",),
                               "ERR_INSPECTION_INVALID_STATE"))
def start_inspection(ctx):
    inspection = ctx.path["inspection_id"]
    technician = db.get("Technician", inspection["technician_id"])
    if technician is None or technician["status"] != "AVAILABLE":
        raise ApiError("ERR_TECHNICIAN_UNAVAILABLE", "The technician is not available.")
    inspection["status"] = "IN_PROGRESS"
    ctx.touch(inspection)
    return serialize.dump(inspection)


@endpoint("POST", "/water-service/inspections/<inspection_id>/complete", ["Technician"],
          path_params=[("inspection_id", "Inspection")],
          scope=common.scope(technician=lambda c: c.path["inspection_id"]["technician_id"]),
          g5=common.state_gate("inspection_id", "status", ("IN_PROGRESS",),
                               "ERR_INSPECTION_INVALID_STATE"),
          fields=[
              F("measured_yield_gpm", "number", minimum=0.0, maximum=200.0),
              F("static_level_feet", "number"),
              F("observed_drawdown_gallons", "number", minimum=1.0, maximum=120.0),
          ])
def complete_inspection(ctx):
    inspection = ctx.path["inspection_id"]
    inspection["measured_yield_gpm"] = ctx.body["measured_yield_gpm"]
    inspection["static_level_feet"] = ctx.body["static_level_feet"]
    inspection["observed_drawdown_gallons"] = ctx.body["observed_drawdown_gallons"]
    inspection["completed_at"] = db.clock
    inspection["status"] = "COMPLETED"
    ctx.touch(inspection)

    well = db.get("WellProfile", inspection["well_profile_id"])
    if well is not None:
        well["measured_yield_gpm"] = inspection["measured_yield_gpm"]
        well["last_inspection_completed_at"] = inspection["completed_at"]
        well["pressure_tank_drawdown_gallons"] = inspection["observed_drawdown_gallons"]
        calc.apply_duty_cycle(well)
        common.recompute_plans_for_well(ctx, well)
        ctx.touch(well)
    return serialize.dump(inspection)


@endpoint("POST", "/water-service/inspections/<inspection_id>/cancel",
          ["Dispatcher", "PlatformAdmin"],
          path_params=[("inspection_id", "Inspection")],
          g5=common.state_gate("inspection_id", "status", ("SCHEDULED", "IN_PROGRESS"),
                               "ERR_INSPECTION_INVALID_STATE"))
def cancel_inspection(ctx):
    inspection = ctx.path["inspection_id"]
    inspection["status"] = "CANCELLED"
    ctx.touch(inspection)
    return serialize.dump(inspection)


# ==========================================================================
# 4.9 Water tests
# ==========================================================================

@endpoint("POST", "/water-service/water-tests",
          ["Technician", "ComplianceOfficer", "PlatformAdmin"], code=201, fields=[
              F("well_profile_id", "string"),
              F("collected_by_technician_id", "string"),
              F("panel_type", "string", enum=["BACTERIOLOGICAL", "CHEMICAL"]),
              F("sample_datetime", "datetime"),
          ])
def create_water_test(ctx):
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Technician", ctx.body["collected_by_technician_id"])
    row = ctx.new("WaterTest", {
        "well_profile_id": ctx.body["well_profile_id"],
        "collected_by_technician_id": ctx.body["collected_by_technician_id"],
        "parent_test_id": None,
        "panel_type": ctx.body["panel_type"],
        "sample_datetime": ctx.body["sample_datetime"],
        "analyzed_at": None,
        "result_status": "COLLECTED",
        "coliform_present": None,
        "nitrate_mg_l": None,
        "arsenic_mg_l": None,
        "lead_mg_l": None,
        "iron_mg_l": None,
        "hardness_gpg": None,
        "recorded_by_user_id": None,
        "confirmed_by_user_id": None,
        "hold_time_valid": None,
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/water-tests/<water_test_id>",
          ["PlatformAdmin", "ComplianceOfficer", "Technician", "Estimator",
           "CustomerContact"], read=True, path_params=[("water_test_id", "WaterTest")])
def read_water_test(ctx):
    return serialize.dump(ctx.path["water_test_id"])


@endpoint("GET", "/water-service/water-tests",
          ["PlatformAdmin", "ComplianceOfficer", "Technician", "Estimator"], read=True,
          paginated=True, filters=["well_profile_id", "collected_by_technician_id",
                                   "parent_test_id", "panel_type", "result_status"])
def list_water_tests(ctx):
    return db.all("WaterTest")


def _lab_date_range(ctx):
    test = ctx.path["water_test_id"]
    if ctx.body["analyzed_at"] < test["sample_datetime"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "analyzed_at precedes sample_datetime.")


@endpoint("POST", "/water-service/water-tests/<water_test_id>/lab-result",
          ["ComplianceOfficer"], path_params=[("water_test_id", "WaterTest")],
          g5=common.state_gate("water_test_id", "result_status", ("COLLECTED",),
                               "ERR_WATER_TEST_INVALID_STATE"),
          fields=[
              F("analyzed_at", "datetime"),
              F("coliform_present", "boolean", required=False),
              F("nitrate_mg_l", "number", required=False),
              F("arsenic_mg_l", "number", required=False),
              F("lead_mg_l", "number", required=False),
              F("iron_mg_l", "number", required=False),
              F("hardness_gpg", "number", required=False),
          ], g8_post=_lab_date_range)
def lab_result(ctx):
    test = ctx.path["water_test_id"]
    for name in ("coliform_present", "nitrate_mg_l", "arsenic_mg_l", "lead_mg_l",
                 "iron_mg_l", "hardness_gpg"):
        test[name] = ctx.body[name]
    test["analyzed_at"] = ctx.body["analyzed_at"]
    test["recorded_by_user_id"] = ctx.user_id
    ctx.touch(test)

    well = db.get("WellProfile", test["well_profile_id"])
    valid = calc.hold_time_valid(test["panel_type"], test["sample_datetime"],
                                 test["analyzed_at"])
    test["hold_time_valid"] = bool(valid)
    if not valid:
        # The result is discarded as evidence: the well does not move at all.
        test["result_status"] = "INVALID_HOLD_TIME"
        return serialize.dump(test)

    if test["panel_type"] == "BACTERIOLOGICAL":
        if test["coliform_present"] is True:
            test["result_status"] = "ANALYZED_PRESUMPTIVE_POSITIVE"
            well["potability_status"] = "ADVISORY"
            well["advisory_reason"] = "PRESUMPTIVE_COLIFORM"
        else:
            test["result_status"] = "ANALYZED_NEGATIVE"
            well["potability_status"] = "SAFE"
            well["advisory_reason"] = None
    else:
        test["result_status"] = "ANALYZED_CHEMICAL_EXCEEDANCE"
        well["hardness_gpg"] = test["hardness_gpg"]
        if calc.chemical_exceedance(test):
            well["potability_status"] = "ADVISORY"
            well["advisory_reason"] = "CHEMICAL_EXCEEDANCE"
    ctx.touch(well)
    return serialize.dump(test)


def _confirmatory_regulatory(ctx):
    """G6 -- the three regulatory checks, in the order PRD 3.3 gives them.

    The two window checks read body instants; when an instant does not parse the
    check is skipped so that G8 can answer with ERR_INVALID_TIMESTAMP.
    """
    from core import parse_instant, peek_json
    test = ctx.path["water_test_id"]
    raw = peek_json()
    ctx.raw_body = raw
    sample = parse_instant(raw.get("confirm_sample_datetime")) if isinstance(raw, dict) else None
    analyzed = parse_instant(raw.get("confirm_analyzed_at")) if isinstance(raw, dict) else None
    if sample is not None:
        elapsed = (sample - test["sample_datetime"]).total_seconds()
        if elapsed > RETEST_WINDOW_SECONDS:
            raise ApiError("ERR_RETEST_WINDOW_EXPIRED",
                           "The confirmatory sample falls outside the retest window.")
    if sample is not None and analyzed is not None:
        if hours_between(sample, analyzed) > calc.HOLD_TIME_HOURS_BACTERIOLOGICAL:
            raise ApiError("ERR_WATER_TEST_HOLD_TIME_EXCEEDED",
                           "The confirmatory sample breached its hold time.")
    if ctx.user_id == test["recorded_by_user_id"]:
        raise ApiError("ERR_CONFIRMATORY_SAME_OFFICER",
                       "The confirming officer must differ from the recording officer.")


@endpoint("POST", "/water-service/water-tests/<water_test_id>/confirmatory-result",
          ["ComplianceOfficer"], path_params=[("water_test_id", "WaterTest")],
          g5=common.state_gate("water_test_id", "result_status",
                               ("ANALYZED_PRESUMPTIVE_POSITIVE",),
                               "ERR_WATER_TEST_INVALID_STATE"),
          g6=_confirmatory_regulatory,
          fields=[
              F("confirm_sample_datetime", "datetime"),
              F("confirm_analyzed_at", "datetime"),
              F("confirm_coliform_present", "boolean"),
              F("collected_by_technician_id", "string"),
          ])
def confirmatory_result(ctx):
    test = ctx.path["water_test_id"]
    common.resolve("Technician", ctx.body["collected_by_technician_id"])
    well = db.get("WellProfile", test["well_profile_id"])
    confirmed = ctx.body["confirm_coliform_present"] is True
    outcome = "CONFIRMED_POSITIVE" if confirmed else "CLEARED_NEGATIVE"

    ctx.new("WaterTest", {
        "well_profile_id": test["well_profile_id"],
        "collected_by_technician_id": ctx.body["collected_by_technician_id"],
        "parent_test_id": test["id"],
        "panel_type": "BACTERIOLOGICAL",
        "sample_datetime": ctx.body["confirm_sample_datetime"],
        "analyzed_at": ctx.body["confirm_analyzed_at"],
        "result_status": outcome,
        "coliform_present": ctx.body["confirm_coliform_present"],
        "nitrate_mg_l": None,
        "arsenic_mg_l": None,
        "lead_mg_l": None,
        "iron_mg_l": None,
        "hardness_gpg": None,
        "recorded_by_user_id": None,
        "confirmed_by_user_id": None,
        "hold_time_valid": True,
    })
    test["result_status"] = outcome
    test["confirmed_by_user_id"] = ctx.user_id
    ctx.touch(test)
    if confirmed:
        well["potability_status"] = "UNSAFE"
        well["advisory_reason"] = "CONFIRMED_COLIFORM"
    else:
        well["potability_status"] = "SAFE"
        well["advisory_reason"] = None
    ctx.touch(well)

    if confirmed:
        # PRD 2.11 rung 1: every write above persists behind the error.
        raise ApiError("ERR_RETEST_CONFIRMED_POSITIVE",
                       "The confirmatory retest confirmed coliform.", persist=True)
    return serialize.dump(test)


@endpoint("POST", "/water-service/water-tests/<water_test_id>/lapse-retest-window",
          ["ComplianceOfficer", "PlatformAdmin"],
          path_params=[("water_test_id", "WaterTest")],
          g5=common.state_gate("water_test_id", "result_status",
                               ("ANALYZED_PRESUMPTIVE_POSITIVE",),
                               "ERR_WATER_TEST_INVALID_STATE"))
def lapse_retest_window(ctx):
    test = ctx.path["water_test_id"]
    elapsed = (db.clock - test["sample_datetime"]).total_seconds()
    if not elapsed > RETEST_WINDOW_SECONDS:
        raise ApiError("ERR_RETEST_WINDOW_STILL_OPEN",
                       "The retest window has not closed yet.")
    test["result_status"] = "CONFIRMED_POSITIVE"
    ctx.touch(test)
    well = db.get("WellProfile", test["well_profile_id"])
    well["potability_status"] = "UNSAFE"
    well["advisory_reason"] = "RETEST_WINDOW_LAPSED"
    ctx.touch(well)
    return serialize.dump(test)


@endpoint("GET",
          "/water-service/water-tests/<water_test_id>/treatment-recommendations",
          ["PlatformAdmin", "ComplianceOfficer", "Estimator", "CustomerContact"],
          read=True, paginated=True, path_params=[("water_test_id", "WaterTest")])
def test_recommendations(ctx):
    return common.rows_where("TreatmentRecommendation",
                             water_test_id=ctx.path["water_test_id"]["id"])


# ==========================================================================
# 4.10 Treatment recommendations
# ==========================================================================

@endpoint("GET",
          "/water-service/treatment-recommendations/<treatment_recommendation_id>",
          ["PlatformAdmin", "ComplianceOfficer", "Estimator", "CustomerContact"],
          read=True,
          path_params=[("treatment_recommendation_id", "TreatmentRecommendation")])
def read_recommendation(ctx):
    return serialize.dump(ctx.path["treatment_recommendation_id"])


@endpoint("GET", "/water-service/treatment-recommendations",
          ["PlatformAdmin", "ComplianceOfficer", "Estimator", "CustomerContact"],
          read=True, paginated=True,
          filters=["well_profile_id", "water_test_id", "superseded_by_id", "status"])
def list_recommendations(ctx):
    return db.all("TreatmentRecommendation")


def _rec_owner(ctx):
    rec = ctx.path["treatment_recommendation_id"]
    well = db.get("WellProfile", rec["well_profile_id"])
    return common.account_of_well(well)


@endpoint("POST",
          "/water-service/treatment-recommendations/<treatment_recommendation_id>/accept",
          ["CustomerContact"],
          path_params=[("treatment_recommendation_id", "TreatmentRecommendation")],
          scope=common.scope(customer=_rec_owner),
          g5=common.state_gate("treatment_recommendation_id", "status", ("PROPOSED",),
                               "ERR_TREATMENT_RECOMMENDATION_INVALID_STATE"))
def accept_recommendation(ctx):
    rec = ctx.path["treatment_recommendation_id"]
    well = db.get("WellProfile", rec["well_profile_id"])
    # PRD 2.6: within a single gate, checks run in the order the sections give
    # them, and PRD 3.4 names effective expiry before the potability question.
    if calc.recommendation_status_effective(rec) == "EXPIRED":
        raise ApiError("ERR_TREATMENT_RECOMMENDATION_EXPIRED",
                       "The recommendation has expired.")
    if well["potability_status"] == "ADVISORY" \
            and well["advisory_reason"] == "PRESUMPTIVE_COLIFORM":
        raise ApiError("ERR_POTABILITY_PENDING_CONFIRMATION",
                       "An unresolved bacteriological question blocks acceptance.")

    rec["status"] = "ACCEPTED"
    ctx.touch(rec)
    well["treatment_media"] = rec["recommended_media"]
    ctx.touch(well)
    monthly = rec["monthly_salt_lbs"] if rec["recommended_media"] == "SOFTENER_RESIN" \
        else 0.0
    for plan in common.active_plans_of_well(well["id"]):
        plan["filter_media"] = rec["recommended_media"]
        plan["monthly_salt_lbs"] = monthly if monthly is not None else 0.0
        calc.recompute_operated_interval(plan, well)
        ctx.touch(plan)
    return serialize.dump(rec)
