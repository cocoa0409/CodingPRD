"""Maintenance plans and maintenance visits."""

import calc
import common
import serialize
from core import ApiError, F, add_days, d, db, endpoint, whole_days_between


def _plan_active(ctx):
    plan = ctx.path["maintenance_plan_id"]
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_MAINTENANCE_PLAN_INVALID_STATE",
                       "The plan is not ACTIVE.")


@endpoint("POST", "/water-service/maintenance-plans", ["PlatformAdmin", "Dispatcher"],
          code=201, fields=[F("well_profile_id", "string"), F("account_id", "string")])
def create_plan(ctx):
    well = common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Account", ctx.body["account_id"])
    for other in common.rows_where("MaintenancePlan", well_profile_id=well["id"]):
        if other["status"] in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_PLAN_ALREADY_EXISTS_FOR_WELL",
                           "This well already carries a live maintenance plan.")
    interval = calc.maintenance_interval_days(well["duty_cycle_class"],
                                              well["treatment_media"])
    row = ctx.new("MaintenancePlan", {
        "well_profile_id": well["id"],
        "account_id": ctx.body["account_id"],
        "status": "ACTIVE",
        "compliance_state": "COMPLIANT",
        "overdue_latched_at": None,
        "interval_days_as_designed": interval,
        "interval_days_as_operated": interval,
        "last_service_date": None,
        "next_due_at": None,
        "filter_media": well["treatment_media"],
        "last_filter_change_date": None,
        "salt_remaining_lbs": 0.0,
        "monthly_salt_lbs": 0.0,
        "last_salt_delivery_date": None,
    })
    row["last_service_date"] = row["created_at"]
    row["next_due_at"] = calc.next_due_at(row)
    return serialize.dump(row)


@endpoint("GET", "/water-service/maintenance-plans/<maintenance_plan_id>",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk",
           "CustomerContact"], read=True,
          path_params=[("maintenance_plan_id", "MaintenancePlan")])
def read_plan(ctx):
    return serialize.dump(ctx.path["maintenance_plan_id"])


@endpoint("GET", "/water-service/maintenance-plans",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk"], read=True,
          paginated=True, filters=["well_profile_id", "account_id", "status",
                                   "compliance_state", "filter_media"])
def list_plans(ctx):
    return db.all("MaintenancePlan")


@endpoint("POST",
          "/water-service/maintenance-plans/<maintenance_plan_id>/salt-deliveries",
          ["Dispatcher", "Technician", "PlatformAdmin"],
          path_params=[("maintenance_plan_id", "MaintenancePlan")], g5=_plan_active,
          occ=("expected_maintenance_plan_version",
               "ERR_STALE_MAINTENANCE_PLAN_VERSION",
               lambda c: c.path["maintenance_plan_id"]),
          fields=[F("delivered_lbs", "number", nonneg=True,
                    minimum=float(calc.SALT_DELIVERY_MIN_LBS)),
                  F("expected_maintenance_plan_version", "integer")])
def salt_delivery(ctx):
    plan = ctx.path["maintenance_plan_id"]
    total = d(plan["salt_remaining_lbs"]) + d(ctx.body["delivered_lbs"])
    if total > calc.SALT_TANK_CAPACITY_LBS:
        raise ApiError("ERR_SALT_DELIVERY_EXCEEDS_CAPACITY",
                       "The delivery would overfill the brine tank.")
    plan["salt_remaining_lbs"] = float(total)
    plan["last_salt_delivery_date"] = db.clock
    ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("POST",
          "/water-service/maintenance-plans/<maintenance_plan_id>/filter-change",
          ["Technician", "Dispatcher", "PlatformAdmin"],
          path_params=[("maintenance_plan_id", "MaintenancePlan")], g5=_plan_active)
def filter_change(ctx):
    plan = ctx.path["maintenance_plan_id"]
    previous = plan["last_filter_change_date"]
    if previous is not None:
        if whole_days_between(previous, db.clock) < calc.FILTER_MIN_DAYS_BETWEEN_CHANGES:
            raise ApiError("ERR_FILTER_CHANGE_TOO_SOON",
                           "A filter change was recorded too recently.")
    plan["last_filter_change_date"] = db.clock
    ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("POST",
          "/water-service/maintenance-plans/<maintenance_plan_id>/evaluate-compliance",
          ["PlatformAdmin"],
          path_params=[("maintenance_plan_id", "MaintenancePlan")], g5=_plan_active)
def evaluate_compliance(ctx):
    plan = ctx.path["maintenance_plan_id"]
    if plan["compliance_state"] == "COMPLIANT" and db.clock > plan["next_due_at"]:
        plan["compliance_state"] = "OVERDUE"
        plan["overdue_latched_at"] = db.clock
        ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("POST", "/water-service/maintenance-plans/<maintenance_plan_id>/suspend",
          ["PlatformAdmin"], path_params=[("maintenance_plan_id", "MaintenancePlan")],
          g5=common.state_gate("maintenance_plan_id", "status", ("ACTIVE",),
                               "ERR_MAINTENANCE_PLAN_INVALID_STATE"))
def suspend_plan(ctx):
    plan = ctx.path["maintenance_plan_id"]
    plan["status"] = "SUSPENDED"
    ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("POST", "/water-service/maintenance-plans/<maintenance_plan_id>/resume",
          ["PlatformAdmin"], path_params=[("maintenance_plan_id", "MaintenancePlan")],
          g5=common.state_gate("maintenance_plan_id", "status", ("SUSPENDED",),
                               "ERR_MAINTENANCE_PLAN_INVALID_STATE"))
def resume_plan(ctx):
    plan = ctx.path["maintenance_plan_id"]
    plan["status"] = "ACTIVE"
    well = db.get("WellProfile", plan["well_profile_id"])
    if well is not None:
        calc.recompute_operated_interval(plan, well)
    ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("POST", "/water-service/maintenance-plans/<maintenance_plan_id>/terminate",
          ["PlatformAdmin"], path_params=[("maintenance_plan_id", "MaintenancePlan")],
          g5=common.state_gate("maintenance_plan_id", "status", ("SUSPENDED",),
                               "ERR_MAINTENANCE_PLAN_INVALID_STATE"))
def terminate_plan(ctx):
    plan = ctx.path["maintenance_plan_id"]
    plan["status"] = "TERMINATED"
    ctx.touch(plan)
    return serialize.dump(plan)


@endpoint("GET", "/water-service/maintenance-plans/<maintenance_plan_id>/visits",
          ["PlatformAdmin", "Dispatcher", "Technician", "CustomerContact"],
          read=True, paginated=True,
          path_params=[("maintenance_plan_id", "MaintenancePlan")])
def plan_visits(ctx):
    return common.rows_where("MaintenanceVisit",
                             maintenance_plan_id=ctx.path["maintenance_plan_id"]["id"])


# ==========================================================================
# 4.20 Maintenance visits
# ==========================================================================

@endpoint("GET", "/water-service/maintenance-visits/<maintenance_visit_id>",
          ["PlatformAdmin", "Dispatcher", "Technician"], read=True,
          path_params=[("maintenance_visit_id", "MaintenanceVisit")])
def read_visit(ctx):
    return serialize.dump(ctx.path["maintenance_visit_id"])


@endpoint("GET", "/water-service/maintenance-visits",
          ["PlatformAdmin", "Dispatcher", "Technician"], read=True, paginated=True,
          filters=["maintenance_plan_id", "work_order_id", "visit_kind"])
def list_visits(ctx):
    return db.all("MaintenanceVisit")
