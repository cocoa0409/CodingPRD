"""Judge endpoints: invite, lifecycle, conflict declarations, and
judge-scoped collections."""
from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, forbid
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_SEGREGATION_OF_DUTIES,
)
from util import (
    body_json, req_str, req_enum, opt_int, new_record, new_child_record, bump,
    success_object, list_response, get_or_404, ref_or_404,
)

bp = Blueprint("judges", __name__)

CONFLICT_TYPES = ["FINANCIAL", "FAMILIAL", "PROFESSIONAL", "PERSONAL", "OTHER"]
SEVERITIES = ["HARD", "SOFT"]


@bp.post("/awards/judges")
def invite_judge():
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    expertise_tags = body.get("expertise_tags") or []
    if not isinstance(expertise_tags, list):
        raise_err(ERR_INVALID_REQUEST, "expertise_tags must be an array")
    affiliated = body.get("affiliated_entrant_ids") or []
    if not isinstance(affiliated, list):
        raise_err(ERR_INVALID_REQUEST, "affiliated_entrant_ids must be an array")
    for j in store.judges.values():
        if j["email"] == email:
            raise_err(ERR_DUPLICATE, "judge email already exists: %s" % email)
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "expertise_tags": expertise_tags,
        "affiliated_entrant_ids": affiliated,
        "status": "INVITED",
        "reliability_score_bp": 10000,
    })
    store.judges[rec["id"]] = rec
    return success_object(services.serialize_judge(rec), 201)


@bp.get("/awards/judges")
def list_judges():
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    records = list(store.judges.values())
    status = request.args.get("status")
    if status:
        records = [j for j in records if j["status"] == status]
    return list_response(records, services.serialize_judge)


@bp.get("/awards/judges/<jid>")
def get_judge(jid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    if role == "Judge" and uid != j["id"]:
        forbid("Judge may only read their own record")
    return success_object(services.serialize_judge(j), 200)


def _own_judge_or_forbid(judge, uid):
    if judge["id"] != uid:
        forbid("Judge may only act on their own record")


@bp.post("/awards/judges/<jid>/accept")
def accept_judge(jid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    _own_judge_or_forbid(j, uid)
    services.guard_transition("judge", j, {"INVITED"})
    j["status"] = "ACCEPTED"
    bump(j)
    # auto-seed conflict declarations from affiliations; the season scope is
    # resolved per assignment (null season scope covers every season)
    for entrant_id in j["affiliated_entrant_ids"]:
        d = new_child_record()
        d.update({
            "judge_id": j["id"],
            "season_id": None,
            "entrant_id": entrant_id,
            "category_id": None,
            "conflict_type": "OTHER",
            "severity": "HARD",
            "note": "auto-seeded from affiliated_entrant_ids",
            "status": "DECLARED",
        })
        store.declarations[d["id"]] = d
    return success_object(services.serialize_judge(j), 200)


@bp.post("/awards/judges/<jid>/decline")
def decline_judge(jid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    _own_judge_or_forbid(j, uid)
    services.guard_transition("judge", j, {"INVITED"})
    j["status"] = "DECLINED"
    bump(j)
    return success_object(services.serialize_judge(j), 200)


@bp.post("/awards/judges/<jid>/activate")
def activate_judge(jid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    j = get_or_404(store.judges, jid, "Judge")
    services.guard_transition("judge", j, {"ACCEPTED", "SUSPENDED"})
    if j["status"] == "ACCEPTED":
        has_declaration = any(
            d["judge_id"] == j["id"] and d["status"] in ("DECLARED", "ACKNOWLEDGED")
            for d in store.declarations.values())
        if not has_declaration and j["affiliated_entrant_ids"]:
            raise_err(ERR_INVALID_STATE,
                      "activation requires a declared conflict or empty affiliations")
    j["status"] = "ACTIVE"
    bump(j)
    return success_object(services.serialize_judge(j), 200)


@bp.post("/awards/judges/<jid>/suspend")
def suspend_judge(jid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    j = get_or_404(store.judges, jid, "Judge")
    services.guard_transition("judge", j, {"ACTIVE"})
    j["status"] = "SUSPENDED"
    bump(j)
    affected_rounds = set()
    for a in store.assignments.values():
        if a["judge_id"] == j["id"] and a["status"] in ("PROPOSED", "ACTIVE"):
            a["status"] = "REMOVED"
            bump(a)
            affected_rounds.add(a["scoring_round_id"])
            for s in services.scores_of_round(a["scoring_round_id"]):
                if s["judge_id"] == j["id"] and s["status"] == "DRAFT":
                    s["status"] = "VOIDED"
    services.recompute_reliability(j)
    for rid in affected_rounds:
        rnd = store.rounds.get(rid)
        if rnd is not None:
            services.demote_round_if_understaffed(rnd)
    return success_object(services.serialize_judge(j), 200)


@bp.post("/awards/judges/<jid>/retire")
def retire_judge(jid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    j = get_or_404(store.judges, jid, "Judge")
    services.guard_transition("judge", j, {"ACTIVE", "SUSPENDED"})
    for a in store.assignments.values():
        if a["judge_id"] == j["id"] and a["status"] == "ACTIVE":
            rnd = store.rounds.get(a["scoring_round_id"])
            if rnd is not None and rnd["status"] == "OPEN":
                raise_err(ERR_INVALID_STATE,
                          "judge holds an ACTIVE assignment in an OPEN round")
    j["status"] = "RETIRED"
    bump(j)
    return success_object(services.serialize_judge(j), 200)


# ---------------------------------------------------------------------------
# conflict declarations
# ---------------------------------------------------------------------------
@bp.post("/awards/judges/<jid>/conflict-declarations")
def file_declaration(jid):
    uid, role = authenticate()
    authorize(role, ["Judge", "ProgramAdmin"])
    j = get_or_404(store.judges, jid, "Judge")
    body = body_json()
    season_id = req_str(body, "season_id")
    entrant_id = req_str(body, "entrant_id")
    category_id = body.get("category_id")
    if category_id is not None and not isinstance(category_id, str):
        raise_err(ERR_INVALID_REQUEST, "category_id must be a string or null")
    conflict_type = req_enum(body, "conflict_type", CONFLICT_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise_err(ERR_INVALID_REQUEST, "note must be a string or null")
    expected = body.get("expected_judge_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_judge_version is required and must be an integer")
    ref_or_404(store.seasons, season_id, "Season")
    ref_or_404(store.entrants, entrant_id, "Entrant")
    if category_id is not None:
        ref_or_404(store.categories, category_id, "Category")
    if role == "Judge" and uid != j["id"]:
        forbid("Judge may only file their own declarations")
    if expected != j["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_judge_version %s != current %s" % (expected, j["version"]))
    rec = new_child_record()
    rec.update({
        "judge_id": j["id"],
        "season_id": season_id,
        "entrant_id": entrant_id,
        "category_id": category_id,
        "conflict_type": conflict_type,
        "severity": severity,
        "note": note,
        "status": "DECLARED",
    })
    store.declarations[rec["id"]] = rec
    bump(j)
    return success_object(services.serialize_declaration(rec), 201)


@bp.get("/awards/judges/<jid>/conflict-declarations")
def list_judge_declarations(jid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    if role == "Judge" and uid != j["id"]:
        forbid("Judge may only list their own declarations")
    records = [d for d in store.declarations.values() if d["judge_id"] == j["id"]]
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    if season_id:
        records = [d for d in records if d.get("season_id") == season_id]
    if status:
        records = [d for d in records if d["status"] == status]
    return list_response(records, services.serialize_declaration)


@bp.get("/awards/seasons/<sid>/conflict-declarations")
def list_season_declarations(sid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    s = get_or_404(store.seasons, sid, "Season")
    records = [d for d in store.declarations.values() if d.get("season_id") == s["id"]]
    judge_id = request.args.get("judge_id")
    entrant_id = request.args.get("entrant_id")
    if judge_id:
        records = [d for d in records if d["judge_id"] == judge_id]
    if entrant_id:
        records = [d for d in records if d.get("entrant_id") == entrant_id]
    return list_response(records, services.serialize_declaration)


@bp.get("/awards/categories/<cid>/conflict-declarations")
def list_category_declarations(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    c = get_or_404(store.categories, cid, "Category")
    records = [d for d in store.declarations.values() if d.get("category_id") == c["id"]]
    return list_response(records, services.serialize_declaration)


@bp.post("/awards/conflict-declarations/<did>/acknowledge")
def acknowledge_declaration(did):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    d = get_or_404(store.declarations, did, "ConflictDeclaration")
    services.guard_transition("declaration", d, {"DECLARED"})
    d["status"] = "ACKNOWLEDGED"
    return success_object(services.serialize_declaration(d), 200)


@bp.post("/awards/conflict-declarations/<did>/rescind")
def rescind_declaration(did):
    uid, role = authenticate()
    authorize(role, ["Judge", "ProgramAdmin"])
    d = get_or_404(store.declarations, did, "ConflictDeclaration")
    if role == "Judge" and uid != d["judge_id"]:
        forbid("Judge may only rescind their own declarations")
    services.guard_transition("declaration", d, {"DECLARED"})
    d["status"] = "RESCINDED"
    return success_object(services.serialize_declaration(d), 200)


# ---------------------------------------------------------------------------
# judge-scoped collections
# ---------------------------------------------------------------------------
@bp.get("/awards/judges/<jid>/panel-assignments")
def list_judge_assignments(jid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    if role == "Judge" and uid != j["id"]:
        forbid("Judge may only list their own assignments")
    records = [a for a in store.assignments.values() if a["judge_id"] == j["id"]]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_assignment)


@bp.get("/awards/judges/<jid>/scores")
def list_judge_scores(jid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    j = get_or_404(store.judges, jid, "Judge")
    if role == "Judge" and uid != j["id"]:
        forbid("Judge may only list their own scores")
    records = [s for s in store.scores.values() if s["judge_id"] == j["id"]]
    round_id = request.args.get("scoring_round_id")
    if round_id:
        records = [s for s in records if s["scoring_round_id"] == round_id]
    return list_response(records, services.serialize_score)
