"""Evaluation cycle lifecycle."""
from decimal import Decimal

import calc
import services as svc
from auth import authenticate
from errors import err
from response import created, ok, paginated
from store import S, add_days, new_record, now, sorted_records, touch
from validation import body, query_enum, query_str, v_enum, v_str

ALL_ROLES = ("HrAdmin", "Evaluator", "Teacher", "AppealPanelist", "UnionRep")
CYCLE_STATUSES = ("SCHEDULING", "SCORING", "SUBMITTED", "FINALIZED", "CLOSED")
DISPUTE_STATES = ("NONE", "APPEALED", "APPEAL_RESOLVED", "GRIEVED", "GRIEVANCE_RESOLVED")


def register(app):
    @app.post("/evaluation-cycles")
    def create_cycle():
        authenticate(("HrAdmin",))
        data = body()
        educator_id = v_str(data, "educator_id")
        policy_id = v_str(data, "policy_id")
        school_year = v_str(data, "school_year")
        cycle_type = v_enum(data, "cycle_type", ("COMPREHENSIVE", "FOCUSED"),
                            required=False, default="COMPREHENSIVE")
        if educator_id not in S.educators:
            raise err("ERR_EDUCATOR_NOT_FOUND")
        if policy_id not in S.policies:
            raise err("ERR_RESOURCE_NOT_FOUND")
        record = new_record(
            educator_id=educator_id,
            policy_id=policy_id,
            school_year=school_year,
            cycle_type=cycle_type,
            status="SCHEDULING",
            dispute_state="NONE",
            completed_formal_count=0,
            completed_informal_count=0,
            evidence_artifact_count=0,
            observation_component=None,
            growth_component=None,
            evidence_adjustment=Decimal("0.00"),
            composite_score=None,
            composite_rating=None,
            composite_variant=None,
            finalized_at=None,
            appeal_deadline=None,
        )
        S.cycles[record["id"]] = record
        return created(svc.ser_cycle(record))

    @app.get("/evaluation-cycles/<cycle_id>")
    def read_cycle(cycle_id):
        authenticate(ALL_ROLES)
        record = S.cycles.get(cycle_id)
        if record is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        return ok(svc.ser_cycle(record))

    @app.get("/evaluation-cycles")
    def list_cycles():
        authenticate(ALL_ROLES)
        educator_id = query_str("educator_id")
        policy_id = query_str("policy_id")
        school_year = query_str("school_year")
        status = query_enum("status", CYCLE_STATUSES)
        dispute_state = query_enum("dispute_state", DISPUTE_STATES)
        items = sorted_records(S.cycles.values())
        if educator_id is not None:
            items = [i for i in items if i["educator_id"] == educator_id]
        if policy_id is not None:
            items = [i for i in items if i["policy_id"] == policy_id]
        if school_year is not None:
            items = [i for i in items if i["school_year"] == school_year]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        if dispute_state is not None:
            items = [i for i in items if i["dispute_state"] == dispute_state]
        return paginated(items, svc.ser_cycle)

    @app.post("/evaluation-cycles/<cycle_id>/submit")
    def submit_cycle(cycle_id):
        authenticate(("Evaluator", "HrAdmin"))
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        if cycle["status"] != "SCORING":
            raise err("ERR_CYCLE_STATE_INVALID")
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        svc.recompute_cycle_counts(cycle)
        pending = [o for o in svc.observations_of_cycle(cycle_id)
                   if o["status"] in svc.PENDING_OBS]
        if pending or cycle["completed_formal_count"] < 1:
            raise err("ERR_CYCLE_OBSERVATIONS_PENDING")
        policy = svc.policy_of_cycle(cycle)
        svc.recompute_cycle_evidence(cycle)
        svc.recompute_observation_component(cycle, "PROVISIONAL")
        svc.recompute_growth_component(cycle)
        pre = calc.composite_pre(cycle["observation_component"], cycle["growth_component"], policy)
        cycle["evidence_adjustment"] = Decimal("0.00")
        cycle["composite_score"] = pre
        cycle["composite_variant"] = "PROVISIONAL"
        cycle["composite_rating"] = calc.band(pre, policy) if pre is not None else None
        cycle["status"] = "SUBMITTED"
        touch(cycle)
        return ok(svc.ser_cycle(cycle))

    @app.post("/evaluation-cycles/<cycle_id>/finalize")
    def finalize_cycle(cycle_id):
        authenticate(("HrAdmin",))
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        if cycle["status"] != "SUBMITTED" or cycle["composite_variant"] != "PROVISIONAL":
            raise err("ERR_CYCLE_STATE_INVALID")
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        pending = [o for o in svc.observations_of_cycle(cycle_id)
                   if o["status"] in svc.PENDING_OBS]
        if pending:
            raise err("ERR_CYCLE_OBSERVATIONS_PENDING")
        policy = svc.policy_of_cycle(cycle)
        svc.recompute_cycle_counts(cycle)
        svc.recompute_cycle_evidence(cycle)
        svc.recompute_observation_component(cycle, "FINAL")
        svc.recompute_growth_component(cycle)
        pre = calc.composite_pre(cycle["observation_component"], cycle["growth_component"], policy)
        adjustment, adjusted = calc.evidence_sufficiency_adjustment(
            pre, cycle["evidence_artifact_count"], policy)
        cycle["evidence_adjustment"] = adjustment
        cycle["composite_score"] = adjusted
        cycle["composite_variant"] = "FINAL"
        cycle["composite_rating"] = calc.band(adjusted, policy) if adjusted is not None else None
        finalized_at = now()
        cycle["finalized_at"] = finalized_at
        cycle["appeal_deadline"] = add_days(finalized_at, int(policy["appeal_window_days"]))
        cycle["status"] = "FINALIZED"
        touch(cycle)

        educator = S.educators.get(cycle["educator_id"])
        svc.recompute_educator_rating(educator)
        if cycle["composite_rating"] == "INEFFECTIVE":
            svc.create_improvement_plan(cycle, cycle["educator_id"], "INEFFECTIVE_RATING", 1, None)
        return ok(svc.ser_cycle(cycle))

    @app.post("/evaluation-cycles/<cycle_id>/close")
    def close_cycle(cycle_id):
        authenticate(("HrAdmin",))
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        if cycle["status"] != "FINALIZED":
            raise err("ERR_CYCLE_STATE_INVALID")
        if cycle["dispute_state"] not in ("NONE", "APPEAL_RESOLVED", "GRIEVANCE_RESOLVED"):
            raise err("ERR_CYCLE_STATE_INVALID")
        deadline = cycle["appeal_deadline"]
        if deadline is None or now() <= deadline:
            raise err("ERR_CLOSE_BEFORE_APPEAL_DEADLINE")
        cycle["status"] = "CLOSED"
        touch(cycle)
        svc.recompute_educator_rating(S.educators.get(cycle["educator_id"]))
        return ok(svc.ser_cycle(cycle))
