"""Observations, rubric scores and evidence artifacts."""
from datetime import timedelta
from decimal import Decimal

import calc
import services as svc
from auth import authenticate
from errors import err
from response import created, ok, paginated, pagination
from store import (S, D, clock_date, new_record, parse_date, sorted_records, touch)
from validation import body, query_enum, query_str, v_bool, v_datetime, v_enum, v_int, v_str

ALL_ROLES = ("HrAdmin", "Evaluator", "Teacher", "AppealPanelist", "UnionRep")
OBS_STATUSES = ("SCHEDULED", "CONDUCTED", "SCORED", "SUBMITTED", "RETURNED", "ACCEPTED", "VOIDED")
DOMAINS = ("PLANNING", "ENVIRONMENT", "INSTRUCTION", "PROFESSIONALISM")
ARTIFACT_TYPES = ("LESSON_PLAN", "STUDENT_WORK", "REFLECTION", "VIDEO")


def _require_certified(evaluator):
    if evaluator is None or evaluator["certification_status"] != "CERTIFIED":
        raise err("ERR_EVALUATOR_NOT_CERTIFIED")


def _require_unexpired(evaluator):
    expires = parse_date(evaluator["certification_expires_on"]) \
        if evaluator["certification_expires_on"] else None
    if expires is None or clock_date() > expires:
        raise err("ERR_EVALUATOR_CERTIFICATION_LAPSED")


def _recompute_scores(observation):
    """Refresh scored_domain_count and weighted_score from non-superseded rows."""
    rows = [r for r in svc.rubric_scores_of_observation(observation["id"]) if not r["superseded"]]
    by_domain = {}
    for row in rows:
        by_domain[row["domain_code"]] = row
    observation["scored_domain_count"] = len(by_domain)
    if len(by_domain) == 4:
        cycle = S.cycles.get(observation["cycle_id"])
        policy = svc.policy_of_cycle(cycle) if cycle else None
        if policy is not None:
            contributions = dict(
                (domain, D(by_domain[domain]["weighted_contribution"])) for domain in DOMAINS)
            observation["weighted_score"] = calc.observation_weighted_score(
                contributions, observation, policy)
    else:
        observation["weighted_score"] = None


def register(app):
    # --------------------------------------------------------- observations
    @app.post("/observations")
    def create_observation():
        user_id, role = authenticate(("Evaluator", "HrAdmin"))
        data = body()
        cycle_id = v_str(data, "cycle_id")
        evaluator_id = v_str(data, "evaluator_id")
        observation_type = v_enum(data, "observation_type", ("FORMAL", "INFORMAL"))
        scheduled_start = v_datetime(data, "scheduled_start")
        scheduled_end = v_datetime(data, "scheduled_end")
        announced = v_bool(data, "announced", required=False, default=True)
        if scheduled_end <= scheduled_start:
            raise err("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        evaluator = S.evaluators.get(evaluator_id)
        if evaluator is None:
            raise err("ERR_EVALUATOR_NOT_FOUND")
        if role == "Evaluator" and user_id != evaluator_id:
            raise err("ERR_NOT_RESOURCE_OWNER")
        _require_certified(evaluator)
        _require_unexpired(evaluator)
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        for other in svc.observations_of_evaluator(evaluator_id):
            if other["status"] == "VOIDED":
                continue
            if scheduled_start < other["scheduled_end"] and other["scheduled_start"] < scheduled_end:
                raise err("ERR_EVALUATOR_WINDOW_CONFLICT")
        if observation_type == "FORMAL":
            policy = svc.policy_of_cycle(cycle)
            min_days = int(policy["min_days_between_formals"]) if policy else 0
            gap = timedelta(days=min_days)
            educator_cycle_ids = set(
                c["id"] for c in svc.cycles_of_educator(cycle["educator_id"]))
            for other in sorted_records(S.observations.values()):
                if other["status"] == "VOIDED" or other["observation_type"] != "FORMAL":
                    continue
                if other["cycle_id"] not in educator_cycle_ids:
                    continue
                delta = other["scheduled_start"] - scheduled_start
                if delta < timedelta(0):
                    delta = -delta
                if delta < gap:
                    raise err("ERR_FORMAL_SPACING_VIOLATION")
        record = new_record(
            cycle_id=cycle_id,
            evaluator_id=evaluator_id,
            observation_type=observation_type,
            announced=announced,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status="SCHEDULED",
            scored_domain_count=0,
            weighted_score=None,
            evidence_count=0,
            stipend_cents=0,
            return_count=0,
            return_reason=None,
            void_reason=None,
        )
        S.observations[record["id"]] = record
        return created(svc.ser_observation(record))

    @app.get("/observations/<observation_id>")
    def read_observation(observation_id):
        authenticate(ALL_ROLES)
        record = S.observations.get(observation_id)
        if record is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        return ok(svc.ser_observation(record))

    @app.get("/observations")
    def list_observations():
        authenticate(ALL_ROLES)
        cycle_id = query_str("cycle_id")
        evaluator_id = query_str("evaluator_id")
        status = query_enum("status", OBS_STATUSES)
        observation_type = query_enum("observation_type", ("FORMAL", "INFORMAL"))
        items = sorted_records(S.observations.values())
        if cycle_id is not None:
            items = [i for i in items if i["cycle_id"] == cycle_id]
        if evaluator_id is not None:
            items = [i for i in items if i["evaluator_id"] == evaluator_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        if observation_type is not None:
            items = [i for i in items if i["observation_type"] == observation_type]
        return paginated(items, svc.ser_observation)

    @app.post("/observations/<observation_id>/conduct")
    def conduct_observation(observation_id):
        user_id, _role = authenticate(("Evaluator",))
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if user_id != observation["evaluator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if observation["status"] != "SCHEDULED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        if cycle["status"] not in ("SCHEDULING", "SCORING"):
            raise err("ERR_CYCLE_STATE_INVALID")
        evaluator = S.evaluators.get(observation["evaluator_id"])
        _require_certified(evaluator)
        _require_unexpired(evaluator)
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        observation["status"] = "CONDUCTED"
        touch(observation)
        if cycle["status"] == "SCHEDULING":
            cycle["status"] = "SCORING"
            touch(cycle)
        return ok(svc.ser_observation(observation))

    # -------------------------------------------------------- rubric scores
    @app.post("/observations/<observation_id>/rubric-scores")
    def create_rubric_score(observation_id):
        authenticate(("Evaluator",))
        data = body()
        domain_code = v_enum(data, "domain_code", DOMAINS)
        raw_score = v_int(data, "raw_score", minimum=1, maximum=4)
        expected = v_int(data, "expected_observation_version")
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if expected != observation["version"]:
            raise err("ERR_STALE_OBSERVATION_VERSION")
        if observation["status"] not in ("CONDUCTED", "SCORED", "RETURNED"):
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        policy = svc.policy_of_cycle(cycle)
        for row in svc.rubric_scores_of_observation(observation_id):
            if row["domain_code"] == domain_code and not row["superseded"]:
                row["superseded"] = True
                touch(row)
        record = new_record(
            observation_id=observation_id,
            domain_code=domain_code,
            raw_score=raw_score,
            weighted_contribution=calc.weighted_contribution(
                raw_score, domain_code, observation, policy),
            superseded=False,
            observation_version_after=None,
            scored_domain_count=0,
        )
        S.rubric_scores[record["id"]] = record
        _recompute_scores(observation)
        if observation["scored_domain_count"] == 4 and observation["status"] in ("CONDUCTED", "RETURNED"):
            observation["status"] = "SCORED"
        touch(observation)
        record["observation_version_after"] = observation["version"]
        record["scored_domain_count"] = observation["scored_domain_count"]
        return created(svc.ser_rubric_score(record))

    @app.get("/observations/<observation_id>/rubric-scores")
    def list_rubric_scores(observation_id):
        authenticate(("HrAdmin", "Evaluator", "Teacher", "AppealPanelist"))
        domain_code = query_enum("domain_code", DOMAINS)
        pagination()
        if observation_id not in S.observations:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        items = svc.rubric_scores_of_observation(observation_id)
        if domain_code is not None:
            items = [i for i in items if i["domain_code"] == domain_code]
        return paginated(items, svc.ser_rubric_score)

    # ---------------------------------------------------- evidence artifacts
    @app.post("/observations/<observation_id>/evidence-artifacts")
    def attach_artifact(observation_id):
        user_id, role = authenticate(("Evaluator", "Teacher"))
        data = body()
        artifact_type = v_enum(data, "artifact_type", ARTIFACT_TYPES)
        title = v_str(data, "title")
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        cycle = S.cycles.get(observation["cycle_id"])
        if role == "Evaluator" and user_id != observation["evaluator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if role == "Teacher" and (cycle is None or user_id != cycle["educator_id"]):
            raise err("ERR_NOT_RESOURCE_OWNER")
        record = new_record(
            observation_id=observation_id,
            artifact_type=artifact_type,
            title=title,
            status="ATTACHED",
            submitted_by_role="EVALUATOR" if role == "Evaluator" else "TEACHER",
        )
        S.artifacts[record["id"]] = record
        observation["evidence_count"] += 1
        touch(observation)
        if cycle is not None:
            svc.recompute_cycle_evidence(cycle)
            touch(cycle)
        return created(svc.ser_artifact(record))

    @app.get("/observations/<observation_id>/evidence-artifacts")
    def list_artifacts(observation_id):
        authenticate(("HrAdmin", "Evaluator", "Teacher", "AppealPanelist"))
        status = query_enum("status", ("ATTACHED", "WITHDRAWN"))
        pagination()
        if observation_id not in S.observations:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        items = svc.artifacts_of_observation(observation_id)
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return paginated(items, svc.ser_artifact)

    @app.post("/evidence-artifacts/<artifact_id>/withdraw")
    def withdraw_artifact(artifact_id):
        user_id, role = authenticate(("Evaluator", "Teacher"))
        artifact = S.artifacts.get(artifact_id)
        if artifact is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        observation = S.observations.get(artifact["observation_id"])
        cycle = S.cycles.get(observation["cycle_id"]) if observation else None
        if role == "Evaluator" and user_id != observation["evaluator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if role == "Teacher" and (cycle is None or user_id != cycle["educator_id"]):
            raise err("ERR_NOT_RESOURCE_OWNER")
        if artifact["status"] != "ATTACHED":
            raise err("ERR_INVALID_REQUEST", "The artifact has already been withdrawn.")
        if observation["status"] == "VOIDED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        if cycle["status"] not in ("SCHEDULING", "SCORING", "SUBMITTED"):
            raise err("ERR_CYCLE_STATE_INVALID")
        artifact["status"] = "WITHDRAWN"
        touch(artifact)
        observation["evidence_count"] -= 1
        touch(observation)
        svc.recompute_cycle_evidence(cycle)
        touch(cycle)
        return ok(svc.ser_artifact(artifact))

    # ------------------------------------------------------- adjudication
    @app.post("/observations/<observation_id>/submit")
    def submit_observation(observation_id):
        user_id, _role = authenticate(("Evaluator",))
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if user_id != observation["evaluator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if observation["status"] != "SCORED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        if cycle["status"] not in ("SCHEDULING", "SCORING"):
            raise err("ERR_CYCLE_STATE_INVALID")
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        policy = svc.policy_of_cycle(cycle)
        stipend = calc.stipend_for(observation, policy)
        school = svc.school_of_cycle(cycle)
        if school is not None:
            committed = int(school["evaluation_budget_committed_cents"]) + stipend
            if committed > int(school["evaluation_budget_allocated_cents"]):
                raise err("ERR_EVALUATION_BUDGET_EXCEEDED")
        observation["stipend_cents"] = stipend
        observation["status"] = "SUBMITTED"
        touch(observation)
        svc.commit_stipend(cycle, stipend)
        svc.recompute_cycle_counts(cycle)
        svc.recompute_cycle_evidence(cycle)
        svc.recompute_observation_component(cycle, "PROVISIONAL")
        touch(cycle)
        return ok(svc.ser_observation(observation))

    @app.post("/observations/<observation_id>/return")
    def return_observation(observation_id):
        authenticate(("HrAdmin",))
        data = body()
        return_reason = v_str(data, "return_reason")
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if observation["status"] != "SUBMITTED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        if cycle["status"] not in ("SCHEDULING", "SCORING"):
            raise err("ERR_CYCLE_STATE_INVALID")
        if cycle["dispute_state"] != "NONE":
            raise err("ERR_DISPUTE_IN_PROGRESS")
        released = int(observation["stipend_cents"])
        observation["return_count"] += 1
        observation["return_reason"] = return_reason
        observation["stipend_cents"] = 0
        observation["status"] = "RETURNED"
        touch(observation)
        svc.release_stipend(cycle, released)
        svc.recompute_cycle_counts(cycle)
        svc.recompute_observation_component(cycle, "PROVISIONAL")
        touch(cycle)
        return ok(svc.ser_observation(observation))

    @app.post("/observations/<observation_id>/accept")
    def accept_observation(observation_id):
        authenticate(("HrAdmin",))
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if observation["status"] != "SUBMITTED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        if cycle["status"] not in ("SCHEDULING", "SCORING", "SUBMITTED"):
            raise err("ERR_CYCLE_STATE_INVALID")
        observation["status"] = "ACCEPTED"
        touch(observation)
        svc.recompute_cycle_counts(cycle)
        svc.recompute_observation_component(cycle, "PROVISIONAL")
        return ok(svc.ser_observation(observation))

    @app.post("/observations/<observation_id>/void")
    def void_observation(observation_id):
        authenticate(("HrAdmin",))
        data = body()
        void_reason = v_str(data, "void_reason")
        observation = S.observations.get(observation_id)
        if observation is None:
            raise err("ERR_OBSERVATION_NOT_FOUND")
        if observation["status"] == "VOIDED":
            raise err("ERR_OBSERVATION_STATE_INVALID")
        cycle = S.cycles.get(observation["cycle_id"])
        if cycle["status"] == "CLOSED":
            raise err("ERR_CYCLE_STATE_INVALID")
        had_money = observation["status"] in ("SUBMITTED", "ACCEPTED")
        released = int(observation["stipend_cents"])
        observation["status"] = "VOIDED"
        observation["void_reason"] = void_reason
        if had_money:
            observation["stipend_cents"] = 0
        touch(observation)
        if had_money:
            svc.release_stipend(cycle, released)
        svc.recompute_cycle_counts(cycle)
        svc.recompute_cycle_evidence(cycle)
        if had_money:
            svc.recompute_observation_component(cycle, "PROVISIONAL")
            touch(cycle)
        svc.maybe_bubble_down(cycle)
        return ok(svc.ser_observation(observation))
