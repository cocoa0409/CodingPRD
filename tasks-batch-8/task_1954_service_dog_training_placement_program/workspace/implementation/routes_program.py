"""Routes: puppy raisers, trainers, dogs, health screenings, raiser placements, milestones."""
from flask import Blueprint, request

from core import (
    STORE,
    ApiError,
    base_fields,
    body,
    check_terminal,
    err_invalid_state,
    err_ownership,
    err_ref_not_found,
    err_validation,
    get_or_404,
    list_all,
    milestone_base_fields,
    now,
    paginate,
    require_roles,
    respond,
    today,
    touch,
    v_bool,
    v_date,
    v_enum,
    v_int,
    v_str,
)
from services import (
    check_advancement,
    end_placement_effects,
    milestone_figures,
    recompute_certified_tasks,
    screening_score_and_outcome,
    ser_dog,
    ser_match,
    ser_milestone,
    ser_partnership,
    ser_placement,
    ser_raiser,
    ser_screening,
    ser_trainer,
    TASK_CODES,
    career_change_dog,
)

bp = Blueprint("program", __name__)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------------------------
# Puppy raisers
# ---------------------------------------------------------------------------
@bp.route("/api/puppy-raisers", methods=["POST"])
def create_raiser():
    b = body()
    full_name = v_str(b, "full_name")
    region = v_str(b, "region")
    capacity = v_int(b, "foster_capacity", min_v=1)
    exp = v_int(b, "experience_score", min_v=0, max_v=100)
    role, uid = require_roles("ProgramAdmin")
    r = base_fields()
    r.update(
        {
            "full_name": full_name,
            "region": region,
            "foster_capacity": capacity,
            "experience_score": exp,
            "status": "APPLIED",
            "current_dog_count": 0,
            "last_placement_ended_at": None,
        }
    )
    STORE["puppy_raisers"][r["id"]] = r
    return respond(ser_raiser(r), 201)


@bp.route("/api/puppy-raisers/<rid>", methods=["GET"])
def get_raiser(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "PuppyRaiser")
    if role == "PuppyRaiser" and rid != uid:
        raise err_ownership("PuppyRaiser may only view its own profile")
    r = get_or_404("puppy_raisers", rid)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers", methods=["GET"])
def list_raisers():
    role, uid = require_roles("ProgramAdmin", "TrainingDirector")
    items = list(STORE["puppy_raisers"].values())
    status = _q("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    region = _q("region")
    if region is not None:
        items = [r for r in items if r["region"] == region]
    return paginate(items, ser_raiser)


def _raiser_action(rid, allowed_from, roles, self_service=False):
    role, uid = require_roles(*roles)
    if self_service and role == "PuppyRaiser" and rid != uid:
        raise err_ownership("PuppyRaiser may only act on its own profile")
    r = get_or_404("puppy_raisers", rid)
    check_terminal("puppy_raisers", r)
    if r["status"] not in allowed_from:
        raise err_invalid_state(
            "Raiser status %s not permitted here" % r["status"]
        )
    return r


@bp.route("/api/puppy-raisers/<rid>/vet", methods=["POST"])
def vet_raiser(rid):
    r = _raiser_action(rid, {"APPLIED"}, ("ProgramAdmin",))
    r["status"] = "VETTED"
    touch(r)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers/<rid>/approve", methods=["POST"])
def approve_raiser(rid):
    r = _raiser_action(rid, {"VETTED"}, ("ProgramAdmin",))
    r["status"] = "APPROVED"
    touch(r)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers/<rid>/hiatus", methods=["POST"])
def hiatus_raiser(rid):
    r = _raiser_action(
        rid, {"APPROVED", "ACTIVE"}, ("ProgramAdmin", "PuppyRaiser"), self_service=True
    )
    if r["current_dog_count"] != 0:
        raise err_invalid_state("Raiser has active foster dogs")
    r["status"] = "ON_HIATUS"
    touch(r)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers/<rid>/resume", methods=["POST"])
def resume_raiser(rid):
    r = _raiser_action(
        rid, {"ON_HIATUS"}, ("ProgramAdmin", "PuppyRaiser"), self_service=True
    )
    r["status"] = "APPROVED"
    touch(r)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers/<rid>/deactivate", methods=["POST"])
def deactivate_raiser(rid):
    r = _raiser_action(
        rid, {"APPLIED", "VETTED", "APPROVED", "ON_HIATUS"}, ("ProgramAdmin",)
    )
    if r["current_dog_count"] != 0:
        raise err_invalid_state("Raiser has active foster dogs")
    r["status"] = "INACTIVE"
    touch(r)
    return respond(ser_raiser(r))


@bp.route("/api/puppy-raisers/<rid>/placements", methods=["GET"])
def raiser_placements(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "PuppyRaiser")
    if role == "PuppyRaiser" and rid != uid:
        raise err_ownership("PuppyRaiser may only view its own placements")
    r = get_or_404("puppy_raisers", rid)
    items = [
        p
        for p in STORE["placements"].values()
        if p["puppy_raiser_id"] == r["id"]
    ]
    return list_all(items, ser_placement)


# ---------------------------------------------------------------------------
# Trainers
# ---------------------------------------------------------------------------
@bp.route("/api/trainers", methods=["POST"])
def create_trainer():
    b = body()
    full_name = v_str(b, "full_name")
    pat = v_bool(b, "pat_certified", default=False)
    role, uid = require_roles("ProgramAdmin")
    t = base_fields()
    t.update(
        {"full_name": full_name, "pat_certified": pat, "status": "PROBATION"}
    )
    STORE["trainers"][t["id"]] = t
    return respond(ser_trainer(t), 201)


@bp.route("/api/trainers/<rid>", methods=["GET"])
def get_trainer(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer", "Evaluator")
    t = get_or_404("trainers", rid)
    return respond(ser_trainer(t))


def _trainer_action(rid, allowed_from):
    role, uid = require_roles("ProgramAdmin")
    t = get_or_404("trainers", rid)
    check_terminal("trainers", t)
    if t["status"] not in allowed_from:
        raise err_invalid_state(
            "Trainer status %s not permitted here" % t["status"]
        )
    return t


@bp.route("/api/trainers/<rid>/certify", methods=["POST"])
def certify_trainer(rid):
    t = _trainer_action(rid, {"PROBATION"})
    t["status"] = "CERTIFIED"
    touch(t)
    return respond(ser_trainer(t))


@bp.route("/api/trainers/<rid>/suspend", methods=["POST"])
def suspend_trainer(rid):
    t = _trainer_action(rid, {"CERTIFIED"})
    t["status"] = "SUSPENDED"
    touch(t)
    return respond(ser_trainer(t))


@bp.route("/api/trainers/<rid>/reinstate", methods=["POST"])
def reinstate_trainer(rid):
    t = _trainer_action(rid, {"SUSPENDED"})
    t["status"] = "CERTIFIED"
    touch(t)
    return respond(ser_trainer(t))


@bp.route("/api/trainers/<rid>/deactivate", methods=["POST"])
def deactivate_trainer(rid):
    t = _trainer_action(rid, {"PROBATION", "CERTIFIED", "SUSPENDED"})
    t["status"] = "INACTIVE"
    touch(t)
    return respond(ser_trainer(t))


@bp.route("/api/trainers/<rid>/dogs", methods=["GET"])
def trainer_dogs(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer")
    t = get_or_404("trainers", rid)
    items = [
        d for d in STORE["dogs"].values() if d["primary_trainer_id"] == t["id"]
    ]
    return list_all(items, ser_dog)


@bp.route("/api/trainers/<rid>/classes", methods=["GET"])
def trainer_classes(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer")
    t = get_or_404("trainers", rid)
    items = [
        c for c in STORE["classes"].values() if c["lead_trainer_id"] == t["id"]
    ]
    from services import ser_class

    return list_all(items, ser_class)


@bp.route("/api/trainers/<rid>/evaluations", methods=["GET"])
def trainer_evaluations(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer", "Evaluator")
    t = get_or_404("trainers", rid)
    items = [p for p in STORE["pats"].values() if p["evaluator_id"] == t["id"]]
    from services import ser_pat

    return list_all(items, ser_pat)


@bp.route("/api/trainers/<rid>/milestones", methods=["GET"])
def trainer_milestones(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer")
    t = get_or_404("trainers", rid)
    items = [
        m
        for m in STORE["milestones"].values()
        if m["recorded_by_trainer_id"] == t["id"]
    ]
    return list_all(items, ser_milestone)


# ---------------------------------------------------------------------------
# Dogs
# ---------------------------------------------------------------------------
@bp.route("/api/dogs", methods=["POST"])
def create_dog():
    b = body()
    name = v_str(b, "name")
    origin = v_enum(b, "origin", {"BRED", "DONATED"})
    breed = v_str(b, "breed")
    sex = v_enum(b, "sex", {"MALE", "FEMALE"})
    born_on = v_date(b, "born_on")
    region = v_str(b, "region")
    sire_id = b.get("sire_id")
    dam_id = b.get("dam_id")
    donor_name = b.get("donor_name")
    if sire_id is not None and not isinstance(sire_id, str):
        raise err_validation("sire_id must be a string")
    if dam_id is not None and not isinstance(dam_id, str):
        raise err_validation("dam_id must be a string")
    if donor_name is not None and not isinstance(donor_name, str):
        raise err_validation("donor_name must be a string")
    role, uid = require_roles("ProgramAdmin")

    sire = None
    dam = None
    if origin == "BRED":
        # body references must resolve
        if sire_id is not None:
            sire = STORE["dogs"].get(sire_id)
            if sire is None:
                raise err_ref_not_found("sire_id does not resolve")
        if dam_id is not None:
            dam = STORE["dogs"].get(dam_id)
            if dam is None:
                raise err_ref_not_found("dam_id does not resolve")
        if sire is None or dam is None:
            raise ApiError(
                "ERR_DONOR_LINEAGE_INVALID",
                422,
                "BRED dogs require sire_id and dam_id",
            )
        if sire["sex"] != "MALE" or dam["sex"] != "FEMALE" or sire["id"] == dam["id"]:
            raise ApiError(
                "ERR_DONOR_LINEAGE_INVALID",
                422,
                "sire must be MALE, dam FEMALE, and distinct",
            )
        if donor_name is not None:
            raise ApiError(
                "ERR_DONOR_LINEAGE_INVALID",
                422,
                "BRED dogs must not carry donor_name",
            )
    else:  # DONATED
        if sire_id is not None or dam_id is not None or not donor_name:
            raise ApiError(
                "ERR_DONOR_LINEAGE_INVALID",
                422,
                "DONATED dogs require donor_name and forbid sire_id/dam_id",
            )

    d = base_fields()
    d.update(
        {
            "name": name,
            "origin": origin,
            "breed": breed,
            "sex": sex,
            "born_on": born_on.isoformat(),
            "region": region,
            "sire_id": sire_id if origin == "BRED" else None,
            "dam_id": dam_id if origin == "BRED" else None,
            "donor_name": donor_name if origin == "DONATED" else None,
            "status": "REGISTERED",
            "clearance_score": None,
            "primary_trainer_id": None,
            "certified_tasks": set(),
            "career_change_reason": None,
        }
    )
    STORE["dogs"][d["id"]] = d
    return respond(ser_dog(d), 201)


@bp.route("/api/dogs/<rid>", methods=["GET"])
def get_dog(rid):
    role, uid = require_roles(
        "ProgramAdmin",
        "TrainingDirector",
        "Veterinarian",
        "Trainer",
        "IntakeCoordinator",
        "PuppyRaiser",
    )
    d = get_or_404("dogs", rid)
    return respond(ser_dog(d))


@bp.route("/api/dogs", methods=["GET"])
def list_dogs():
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Veterinarian", "IntakeCoordinator"
    )
    items = list(STORE["dogs"].values())
    status = _q("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    origin = _q("origin")
    if origin is not None:
        items = [d for d in items if d["origin"] == origin]
    region = _q("region")
    if region is not None:
        items = [d for d in items if d["region"] == region]
    return paginate(items, ser_dog)


@bp.route("/api/dogs/<rid>/offspring", methods=["GET"])
def dog_offspring(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Veterinarian")
    d = get_or_404("dogs", rid)
    items = [
        x
        for x in STORE["dogs"].values()
        if x["sire_id"] == d["id"] or x["dam_id"] == d["id"]
    ]
    return list_all(items, ser_dog)


@bp.route("/api/dogs/<rid>/begin-screening", methods=["POST"])
def begin_screening(rid):
    role, uid = require_roles("Veterinarian")
    d = get_or_404("dogs", rid)
    check_terminal("dogs", d)
    if d["status"] != "REGISTERED":
        raise err_invalid_state("Dog is not REGISTERED")
    d["status"] = "IN_HEALTH_SCREENING"
    touch(d)
    return respond(ser_dog(d))


@bp.route("/api/dogs/<rid>/career-change", methods=["POST"])
def career_change(rid):
    b = body()
    reason = v_enum(b, "reason_category", {"HEALTH", "TEMPERAMENT", "OTHER"})
    notes = v_str(b, "notes", required=False)
    role, uid = require_roles("TrainingDirector")
    d = get_or_404("dogs", rid)
    check_terminal("dogs", d)
    if d["status"] not in (
        "RAISER_PLACED",
        "RECALLED",
        "IN_ADVANCED_TRAINING",
        "MATCH_READY",
        "MATCHED",
        "TEAM_TRAINING",
    ):
        raise err_invalid_state(
            "Dog status %s cannot be career-changed" % d["status"]
        )
    career_change_dog(d, reason)
    return respond(ser_dog(d))


@bp.route("/api/dogs/<rid>/screenings", methods=["GET"])
def dog_screenings(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Veterinarian")
    d = get_or_404("dogs", rid)
    items = [s for s in STORE["screenings"].values() if s["dog_id"] == d["id"]]
    return list_all(items, ser_screening)


@bp.route("/api/dogs/<rid>/milestones", methods=["GET"])
def dog_milestones_list(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Trainer", "IntakeCoordinator"
    )
    d = get_or_404("dogs", rid)
    from services import dog_milestones

    items = dog_milestones(d["id"])
    return _array([ser_milestone(m) for m in items])


def _array(data):
    from flask import jsonify
    from core import _meta

    return jsonify({"meta": _meta(), "response_type": "array", "data": data}), 200


@bp.route("/api/dogs/<rid>/raiser-placements", methods=["GET"])
def dog_placements(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector")
    d = get_or_404("dogs", rid)
    items = [p for p in STORE["placements"].values() if p["dog_id"] == d["id"]]
    return list_all(items, ser_placement)


@bp.route("/api/dogs/<rid>/matches", methods=["GET"])
def dog_matches(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "IntakeCoordinator")
    d = get_or_404("dogs", rid)
    items = [m for m in STORE["matches"].values() if m["dog_id"] == d["id"]]
    return list_all(items, ser_match)


@bp.route("/api/dogs/<rid>/partnerships", methods=["GET"])
def dog_partnerships(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "IntakeCoordinator")
    d = get_or_404("dogs", rid)
    items = [p for p in STORE["partnerships"].values() if p["dog_id"] == d["id"]]
    return list_all(items, ser_partnership)


# ---------------------------------------------------------------------------
# Health screenings
# ---------------------------------------------------------------------------
@bp.route("/api/dogs/<rid>/screenings", methods=["POST"])
def create_screening(rid):
    b = body()
    hip = v_enum(b, "hip_grade", {"EXCELLENT", "GOOD", "FAIR", "POOR"})
    elbow = v_enum(b, "elbow_grade", {"NORMAL", "GRADE1", "GRADE2"})
    eye = v_enum(b, "eye_result", {"CLEAR", "ABNORMAL"})
    cardiac = v_enum(b, "cardiac_result", {"NORMAL", "ABNORMAL"})
    genetic = v_enum(b, "genetic_panel", {"CLEAR", "CARRIER", "AFFECTED"})
    role, uid = require_roles("Veterinarian")
    d = get_or_404("dogs", rid)
    if d["status"] != "IN_HEALTH_SCREENING":
        raise err_invalid_state("Dog is not IN_HEALTH_SCREENING")
    s = base_fields()
    s.update(
        {
            "dog_id": d["id"],
            "hip_grade": hip,
            "elbow_grade": elbow,
            "eye_result": eye,
            "cardiac_result": cardiac,
            "genetic_panel": genetic,
            "clearance_score": None,
            "status": "DRAFT",
            "veterinarian_user_id": uid,
        }
    )
    STORE["screenings"][s["id"]] = s
    return respond(ser_screening(s), 201)


@bp.route("/api/screenings/<rid>", methods=["GET"])
def get_screening(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Veterinarian")
    s = get_or_404("screenings", rid)
    return respond(ser_screening(s))


@bp.route("/api/screenings/<rid>/submit", methods=["POST"])
def submit_screening(rid):
    role, uid = require_roles("Veterinarian")
    s = get_or_404("screenings", rid)
    # PRD §3.5: "Both screening outcomes are terminal" -> §2.6 step 8
    # terminal lockdown (ERR_ALREADY_TERMINAL) precedes from-state membership.
    check_terminal("screenings", s)
    if s["status"] != "DRAFT":
        raise err_invalid_state("Screening is not DRAFT")
    d = get_or_404("dogs", s["dog_id"])
    score, passed = screening_score_and_outcome(s, d["origin"])
    s["clearance_score"] = score
    s["status"] = "CLEARED" if passed else "FAILED"
    touch(s)
    if d["status"] == "IN_HEALTH_SCREENING":
        d["clearance_score"] = score
        if passed:
            d["status"] = "CLEARED"
        else:
            d["status"] = "CAREER_CHANGED"
            d["career_change_reason"] = "HEALTH"
        touch(d)
    return respond(ser_screening(s))


# ---------------------------------------------------------------------------
# Raiser placements
# ---------------------------------------------------------------------------
@bp.route("/api/dogs/<rid>/raiser-placements", methods=["POST"])
def create_placement(rid):
    b = body()
    raiser_id = b.get("puppy_raiser_id")
    if raiser_id is not None and not isinstance(raiser_id, str):
        raise err_validation("puppy_raiser_id must be a string")
    role, uid = require_roles("TrainingDirector")
    d = get_or_404("dogs", rid)
    raiser = None
    if raiser_id is not None:
        raiser = STORE["puppy_raisers"].get(raiser_id)
        if raiser is None:
            raise err_ref_not_found("puppy_raiser_id does not resolve")
    check_terminal("dogs", d)
    if d["status"] not in ("CLEARED", "RECALLED"):
        raise err_invalid_state("Dog must be CLEARED or RECALLED")
    if raiser is not None:
        # explicit pick: region match, then status/capacity
        if raiser["region"] != d["region"]:
            raise err_validation("Raiser region must equal dog region")
        if raiser["status"] not in ("APPROVED", "ACTIVE") or (
            raiser["current_dog_count"] >= raiser["foster_capacity"]
        ):
            raise ApiError(
                "ERR_RAISER_CAPACITY",
                409,
                "Raiser not APPROVED/ACTIVE or at foster capacity",
            )
    else:
        # selector: APPROVED/ACTIVE, under capacity, region match
        pool = [
            r
            for r in STORE["puppy_raisers"].values()
            if r["status"] in ("APPROVED", "ACTIVE")
            and r["current_dog_count"] < r["foster_capacity"]
            and r["region"] == d["region"]
        ]
        if not pool:
            raise ApiError(
                "ERR_NO_AVAILABLE_RAISER", 409, "No eligible puppy raiser available"
            )
        # experience DESC, last_placement_ended_at ASC nulls last, created_at ASC
        pool.sort(
            key=lambda r: (
                -r["experience_score"],
                r["last_placement_ended_at"] is None,
                r["last_placement_ended_at"] or d["created_at"],
                r["_seq"],
            )
        )
        raiser = pool[0]

    p = base_fields()
    p.update(
        {
            "dog_id": d["id"],
            "puppy_raiser_id": raiser["id"],
            "started_on": today(),
            "ended_on": None,
            "status": "ACTIVE",
        }
    )
    STORE["placements"][p["id"]] = p
    d["status"] = "RAISER_PLACED"
    touch(d)
    raiser["current_dog_count"] += 1
    if raiser["status"] == "APPROVED":
        raiser["status"] = "ACTIVE"
    touch(raiser)
    return respond(ser_placement(p), 201)


@bp.route("/api/raiser-placements/<rid>", methods=["GET"])
def get_placement(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "PuppyRaiser")
    p = get_or_404("placements", rid)
    if role == "PuppyRaiser" and p["puppy_raiser_id"] != uid:
        raise err_ownership("PuppyRaiser may only view its own placements")
    return respond(ser_placement(p))


@bp.route("/api/raiser-placements/<rid>/complete", methods=["POST"])
def complete_placement(rid):
    b = body()
    trainer_id = v_str(b, "primary_trainer_id")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("placements", rid)
    trainer = STORE["trainers"].get(trainer_id)
    if trainer is None:
        raise err_ref_not_found("primary_trainer_id does not resolve")
    check_terminal("placements", p)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Placement is not ACTIVE")
    if trainer["status"] != "CERTIFIED":
        raise err_invalid_state("primary_trainer_id must reference a CERTIFIED trainer")
    d = get_or_404("dogs", p["dog_id"])
    end_placement_effects(p, outcome="COMPLETED")
    d["status"] = "IN_ADVANCED_TRAINING"
    d["primary_trainer_id"] = trainer["id"]
    touch(d)
    return respond(ser_placement(p))


@bp.route("/api/raiser-placements/<rid>/early-return", methods=["POST"])
def early_return_placement(rid):
    b = body()
    reason = v_str(b, "reason", required=False)
    role, uid = require_roles("TrainingDirector", "PuppyRaiser")
    p = get_or_404("placements", rid)
    if role == "PuppyRaiser" and p["puppy_raiser_id"] != uid:
        raise err_ownership("PuppyRaiser may only return its own placement")
    check_terminal("placements", p)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Placement is not ACTIVE")
    d = get_or_404("dogs", p["dog_id"])
    end_placement_effects(p, outcome="EARLY_RETURN")
    if d["status"] == "RAISER_PLACED":
        d["status"] = "RECALLED"
        touch(d)
    return respond(ser_placement(p))


# ---------------------------------------------------------------------------
# Training milestones
# ---------------------------------------------------------------------------
@bp.route("/api/dogs/<rid>/milestones", methods=["POST"])
def create_milestone(rid):
    b = body()
    category = v_enum(
        b, "category", {"OBEDIENCE", "TASK_WORK", "PUBLIC_MANNERS", "SOCIALIZATION"}
    )
    score = v_int(b, "score", min_v=0, max_v=100)
    task_code = b.get("task_code")
    if category == "TASK_WORK":
        if task_code is None:
            raise err_validation("task_code is required for TASK_WORK milestones")
        if not isinstance(task_code, str) or task_code not in TASK_CODES:
            raise err_validation("task_code is invalid")
    else:
        if task_code is not None:
            raise err_validation("task_code is forbidden unless category is TASK_WORK")
    role, uid = require_roles("Trainer", "TrainingDirector")
    d = get_or_404("dogs", rid)
    if role == "Trainer":
        if d["primary_trainer_id"] != uid:
            raise err_ownership(
                "Trainer may only record milestones for their own dogs"
            )
    if d["status"] not in ("IN_ADVANCED_TRAINING", "TEAM_TRAINING"):
        raise err_invalid_state(
            "Dog must be IN_ADVANCED_TRAINING or TEAM_TRAINING"
        )
    if role == "Trainer":
        trainer = STORE["trainers"].get(uid)
        if trainer is not None and trainer["status"] == "SUSPENDED":
            raise err_invalid_state("SUSPENDED trainers may not record milestones")
    recorded_by = uid if role == "Trainer" else d["primary_trainer_id"]

    m = milestone_base_fields()
    m.update(
        {
            "dog_id": d["id"],
            "category": category,
            "task_code": task_code,
            "score": score,
            "recorded_at": now(),
            "recorded_by_trainer_id": recorded_by,
            "rolling_avg_3": None,
            "cumulative_gate_score": None,
            "career_change_recommended": False,
        }
    )
    STORE["milestones"][m["id"]] = m
    rolling, cumulative, career_flag = milestone_figures(d["id"])
    m["rolling_avg_3"] = rolling
    m["cumulative_gate_score"] = cumulative
    m["career_change_recommended"] = career_flag
    recompute_certified_tasks(d)
    check_advancement(d)
    return respond(ser_milestone(m), 201)


@bp.route("/api/milestones/<rid>", methods=["GET"])
def get_milestone(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Trainer")
    m = get_or_404("milestones", rid)
    return respond(ser_milestone(m))
