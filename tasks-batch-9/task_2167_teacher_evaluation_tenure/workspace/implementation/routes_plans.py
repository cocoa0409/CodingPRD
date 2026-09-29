"""Improvement plans: remediation, extension and escalation."""
import services as svc
from auth import authenticate
from errors import err
from response import ok, paginated
from store import S, add_days, now, sorted_records, touch
from validation import body, query_enum, query_str, v_enum, v_int

PLAN_ROLES = ("HrAdmin", "Teacher", "UnionRep", "Evaluator")
PLAN_STATUSES = ("ACTIVE", "EXTENDED", "COMPLETED_SUCCESS", "COMPLETED_FAIL", "VOIDED")


def register(app):
    @app.get("/improvement-plans/<plan_id>")
    def read_plan(plan_id):
        authenticate(PLAN_ROLES)
        record = S.plans.get(plan_id)
        if record is None:
            raise err("ERR_PLAN_NOT_FOUND")
        return ok(svc.ser_plan(record))

    @app.get("/improvement-plans")
    def list_plans():
        authenticate(PLAN_ROLES)
        cycle_id = query_str("cycle_id")
        educator_id = query_str("educator_id")
        prior_plan_id = query_str("prior_plan_id")
        status = query_enum("status", PLAN_STATUSES)
        items = sorted_records(S.plans.values())
        if cycle_id is not None:
            items = [i for i in items if i["cycle_id"] == cycle_id]
        if educator_id is not None:
            items = [i for i in items if i["educator_id"] == educator_id]
        if prior_plan_id is not None:
            items = [i for i in items if i["prior_plan_id"] == prior_plan_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return paginated(items, svc.ser_plan)

    @app.post("/improvement-plans/<plan_id>/extend")
    def extend_plan(plan_id):
        authenticate(("HrAdmin",))
        data = body()
        additional_days = v_int(data, "additional_days")
        expected = v_int(data, "expected_plan_version")
        plan = S.plans.get(plan_id)
        if plan is None:
            raise err("ERR_PLAN_NOT_FOUND")
        if expected != plan["version"]:
            raise err("ERR_STALE_PLAN_VERSION")
        if plan["status"] not in ("ACTIVE", "EXTENDED"):
            raise err("ERR_PLAN_STATE_INVALID")
        if now() > plan["due_at"]:
            raise err("ERR_PLAN_PAST_DUE")
        cycle = S.cycles.get(plan["cycle_id"])
        policy = svc.policy_of_cycle(cycle) if cycle else None
        cap = int(policy["max_plan_extension_days"]) if policy else 45
        if int(plan["extension_days_used"]) + int(additional_days) > cap:
            raise err("ERR_PLAN_EXTENSION_LIMIT")
        plan["due_at"] = add_days(plan["due_at"], additional_days)
        plan["extension_days_used"] = int(plan["extension_days_used"]) + int(additional_days)
        plan["status"] = "EXTENDED"
        touch(plan)
        return ok(svc.ser_plan(plan))

    @app.post("/improvement-plans/<plan_id>/close")
    def close_plan(plan_id):
        authenticate(("HrAdmin",))
        data = body()
        outcome = v_enum(data, "outcome", ("SUCCESS", "FAIL"))
        plan = S.plans.get(plan_id)
        if plan is None:
            raise err("ERR_PLAN_NOT_FOUND")
        if plan["status"] not in ("ACTIVE", "EXTENDED"):
            raise err("ERR_PLAN_STATE_INVALID")
        if now() > plan["due_at"]:
            raise err("ERR_PLAN_PAST_DUE")
        educator = S.educators.get(plan["educator_id"])
        if outcome == "SUCCESS":
            plan["status"] = "COMPLETED_SUCCESS"
            touch(plan)
            return ok(svc.ser_plan(plan))
        plan["status"] = "COMPLETED_FAIL"
        touch(plan)
        cycle = S.cycles.get(plan["cycle_id"])
        if int(plan["escalation_level"]) == 1:
            svc.create_improvement_plan(cycle, plan["educator_id"], "PRIOR_PLAN_FAILED", 2,
                                        plan["id"])
        else:
            if educator is not None:
                educator["tenure_status"] = "NON_RENEWED"
                touch(educator)
        return ok(svc.ser_plan(plan))
