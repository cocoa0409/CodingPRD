"""Casting roles, auditions, contract sign/substitute routes."""
import copy
from flask import Blueprint, g

import errors as E
from db import store, init_common, init_append_only, touch
from clock import clock
from middleware import require_roles, parse_pagination
from response import ok_object, ok_array
from body import (
    get_json_body, require_string, require_enum, require_int,
)
from services.occ import check_version
from services.audit import log as audit_log
from services.budget import find_category, recompute_posture, categories_for_production
from services.calc import cast_commit_estimate
from services.serializers import serialize_role, serialize_audition, paginate
from services.conflicts import (
    check_actor_cross_project_conflict,
    actor_signed_role_ids_for_production,
    check_callsheet_conflict_for_role_sign,
    check_cross_project_conflict_for_role_sign,
)


bp = Blueprint("roles", __name__)


UNION_TIERS = {"PRINCIPAL", "SUPPORTING", "FEATURED_BACKGROUND"}
AUDITION_OUTCOMES = {"PASS", "REJECT", "CALLBACK"}


def _get_production(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    return p


def _get_role(pid, rid):
    r = store.roles.get(rid)
    if not r or r["production_id"] != pid:
        E.not_found(f"Role {rid} not found in production {pid}")
    return r


def _ensure_posture_ok(p):
    if p.get("posture") == "FROZEN":
        E.posture_blocked("Production posture is FROZEN")


@bp.route("/productions/<pid>/roles", methods=["POST"])
@require_roles("CastingDirector")
def create_role(pid):
    body = get_json_body()
    p = _get_production(pid)
    _ensure_posture_ok(p)
    role_name = require_string(body, "role_name")
    desc = require_string(body, "description", allow_empty=True)
    tier = require_enum(body, "union_tier", UNION_TIERS)
    rate = require_int(body, "day_rate_cents", minv=0)
    with store.lock:
        for r in store.roles.values():
            if r["production_id"] == pid and r["role_name"] == role_name:
                E.validation_err("role_name already used in this production")
        rec = {
            "production_id": pid,
            "role_name": role_name,
            "description": desc,
            "union_tier": tier,
            "day_rate_cents": rate,
            "casting_status": "OPEN",
            "signed_actor_id": None,
            "signed_at": None,
        }
        init_common(rec)
        store.roles[rec["id"]] = rec
        return ok_object(serialize_role(rec), http_status=201)


@bp.route("/productions/<pid>/roles/<rid>/auditions", methods=["POST"])
@require_roles("CastingDirector")
def create_audition(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        _ensure_posture_ok(p)
        actor_id = require_string(body, "actor_id")
        if not store.actors.get(actor_id):
            E.reference_mismatch(f"Actor {actor_id} not found")
        audition_at = require_string(body, "audition_at")
        outcome = require_enum(body, "outcome", AUDITION_OUTCOMES)
        notes = body.get("notes", "") or ""
        if not isinstance(notes, str):
            E.validation_err("notes must be a string")
        # Auto-transition role OPEN → AUDITIONING on first audition
        if r["casting_status"] not in {"OPEN", "AUDITIONING", "SHORTLISTED", "OFFERED"}:
            E.invalid_state("Cannot create audition in current role state")
        if r["casting_status"] == "OPEN":
            r["casting_status"] = "AUDITIONING"
            touch(r)
            audit_log(
                production_id=pid, actor_user_id=g.user_id,
                action="SCHEDULE_CHANGE", subject_entity="Role", subject_id=rid,
                before=None, after=copy.deepcopy(r),
            )
        rec = {
            "role_id": rid,
            "actor_id": actor_id,
            "audition_at": audition_at,
            "outcome": outcome,
            "notes": notes,
        }
        init_append_only(rec)
        store.auditions[rec["id"]] = rec
        return ok_object(serialize_audition(rec), http_status=201)


@bp.route("/productions/<pid>/roles/<rid>/auditions", methods=["GET"])
@require_roles("CastingDirector", "LineProducer")
def list_auditions(pid, rid):
    _get_production(pid)
    _get_role(pid, rid)
    limit, offset = parse_pagination()
    items = [a for a in store.auditions.values() if a["role_id"] == rid]
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize_audition(a) for a in page], limit, offset, total, has_more)


@bp.route("/productions/<pid>/roles/<rid>/shortlist", methods=["POST"])
@require_roles("CastingDirector")
def shortlist_role(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        _ensure_posture_ok(p)
        if r["casting_status"] != "AUDITIONING":
            E.invalid_state("shortlist requires AUDITIONING")
        # at least one Audition with PASS for this role
        if not any(a["role_id"] == rid and a["outcome"] == "PASS" for a in store.auditions.values()):
            E.invalid_state("At least one PASS audition required to shortlist")
        r["casting_status"] = "SHORTLISTED"
        touch(r)
        return ok_object(serialize_role(r))


@bp.route("/productions/<pid>/roles/<rid>/reopen-auditions", methods=["POST"])
@require_roles("CastingDirector")
def reopen_auditions(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        _ensure_posture_ok(p)
        if r["casting_status"] != "SHORTLISTED":
            E.invalid_state("reopen-auditions requires SHORTLISTED")
        if p["status"] != "PLANNING":
            E.invalid_state("Production must be PLANNING to reopen auditions")
        before = copy.deepcopy(r)
        r["casting_status"] = "AUDITIONING"
        touch(r)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE", subject_entity="Role", subject_id=rid,
            before=before, after=copy.deepcopy(r),
        )
        return ok_object(serialize_role(r))


@bp.route("/productions/<pid>/roles/<rid>/offer", methods=["POST"])
@require_roles("CastingDirector")
def offer_role(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        _ensure_posture_ok(p)
        if r["casting_status"] != "SHORTLISTED":
            E.invalid_state("offer requires SHORTLISTED")
        actor_id = require_string(body, "actor_id")
        if not store.actors.get(actor_id):
            E.reference_mismatch(f"Actor {actor_id} not found")
        # Audition.outcome=PASS exists for this actor on this role (priority 13)
        has_pass = any(
            a["role_id"] == rid and a["actor_id"] == actor_id and a["outcome"] == "PASS"
            for a in store.auditions.values()
        )
        if not has_pass:
            E.audition_not_passed("Actor has no PASS audition for this role")
        r["casting_status"] = "OFFERED"
        # Stash the offered actor on the record so /sign can use it
        r["offered_actor_id"] = actor_id
        touch(r)
        return ok_object(serialize_role(r))


@bp.route("/productions/<pid>/roles/<rid>/sign", methods=["POST"])
@require_roles("LineProducer")
def sign_role(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        if r["casting_status"] != "OFFERED":
            E.invalid_state("sign requires OFFERED")
        _ensure_posture_ok(p)
        actor_id = r.get("offered_actor_id")
        if not actor_id:
            E.invalid_state("No offered actor on this role")

        # Cross-production conflict: need to check existing reservations of scenes
        # featuring this role against the actor's other signed productions.
        if check_cross_project_conflict_for_role_sign(pid, r, actor_id):
            E.cross_project_conflict("Cross-production conflict on sign")
        if check_callsheet_conflict_for_role_sign(pid, r, actor_id):
            E.actor_callsheet_conflict("Same-production callsheet conflict on sign")

        # Budget headroom: CAST.planned - committed - actual >= projected_cast_commit
        cast_cat = find_category(pid, "CAST")
        projected = cast_commit_estimate(pid, r, variant="at_sign_time")
        if cast_cat is None:
            if projected > 0:
                E.budget_overallocated("CAST budget category not allocated")
        else:
            slack = cast_cat.get("planned_cents", 0) - cast_cat.get("committed_cents", 0) - cast_cat.get("actual_cents", 0)
            if slack < projected:
                E.budget_overallocated("Insufficient CAST budget headroom for sign")

        before = copy.deepcopy(r)
        r["casting_status"] = "SIGNED"
        r["signed_actor_id"] = actor_id
        r["signed_at"] = clock.now_iso()
        r["projected_cast_commit_cents"] = projected
        touch(r)
        if cast_cat is not None and projected > 0:
            cast_cat["committed_cents"] = cast_cat.get("committed_cents", 0) + projected
            touch(cast_cat)
        recompute_posture(p, actor_user_id=g.user_id)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="CONTRACT_SIGNED", subject_entity="Role", subject_id=rid,
            before=before, after=copy.deepcopy(r),
        )
        return ok_object(serialize_role(r))


@bp.route("/productions/<pid>/roles/<rid>/recast", methods=["POST"])
@require_roles("CastingDirector")
def recast_role(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        _ensure_posture_ok(p)
        if r["casting_status"] != "AUDITIONING":
            E.invalid_state("recast (this endpoint) requires AUDITIONING")
        r["casting_status"] = "RECAST"
        touch(r)
        return ok_object(serialize_role(r))


@bp.route("/productions/<pid>/roles/<rid>/substitute", methods=["POST"])
@require_roles("LineProducer")
def substitute_role(pid, rid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        r = _get_role(pid, rid)
        check_version(r, body)
        _ensure_posture_ok(p)
        if r["casting_status"] != "SIGNED":
            E.invalid_state("substitute requires SIGNED")
        if p["status"] not in {"PLANNING", "IN_PRODUCTION"}:
            E.invalid_state("substitute requires production PLANNING or IN_PRODUCTION")
        replacement_actor_id = require_string(body, "replacement_actor_id")
        if not store.actors.get(replacement_actor_id):
            E.reference_mismatch("Replacement actor not found")
        if replacement_actor_id == r.get("signed_actor_id"):
            E.validation_err("Replacement must be a different actor")
        replacement_role_name = require_string(body, "replacement_role_name")
        replacement_rate = require_int(body, "replacement_day_rate_cents", minv=0)

        # Build a temporary role-like dict to check conflicts with the new actor
        # Use the same scenes that reference the original role
        tmp_role = {**r}

        # Cross-production / call-sheet conflict checks for replacement actor against
        # the SAME role's scenes
        if check_cross_project_conflict_for_role_sign(pid, tmp_role, replacement_actor_id):
            E.cross_project_conflict("Cross-production conflict on substitute")
        if check_callsheet_conflict_for_role_sign(pid, tmp_role, replacement_actor_id):
            E.actor_callsheet_conflict("Same-production callsheet conflict on substitute")

        # Decrement previous CAST committed
        cast_cat = find_category(pid, "CAST")
        prev_commit = r.get("projected_cast_commit_cents", 0) or 0
        if cast_cat is not None and prev_commit:
            cast_cat["committed_cents"] = cast_cat.get("committed_cents", 0) - prev_commit
            touch(cast_cat)

        before = copy.deepcopy(r)
        # Old role moves to RECAST
        r["casting_status"] = "RECAST"
        touch(r)

        # Create a brand-new Role record carrying the replacement values, immediately SIGN it
        new_role = {
            "production_id": pid,
            "role_name": replacement_role_name,
            "description": r.get("description", ""),
            "union_tier": r["union_tier"],
            "day_rate_cents": replacement_rate,
            "casting_status": "SIGNED",
            "signed_actor_id": replacement_actor_id,
            "signed_at": clock.now_iso(),
        }
        init_common(new_role)
        # Compute new commit. Reuse existing scene set (the one that referenced original role).
        # Since the new role isn't in any scene's required_actor_role_ids yet, it would be 0.
        # Best approximation: use the same scenes that referenced the original role.
        # Make the new role appear in those scenes — but PRD says it's a fresh Role record.
        # We'll compute the projected commit by acting as if scenes that referenced the old
        # role now reference the new role.
        original_role_id = r["id"]
        for s in store.scenes.values():
            if s["production_id"] != pid:
                continue
            if original_role_id in (s.get("required_actor_role_ids") or []):
                ids = list(s["required_actor_role_ids"])
                if new_role["id"] not in ids:
                    ids.append(new_role["id"])
                    s["required_actor_role_ids"] = ids
                    touch(s)
        new_commit = cast_commit_estimate(pid, new_role, variant="at_sign_time")
        new_role["projected_cast_commit_cents"] = new_commit
        store.roles[new_role["id"]] = new_role
        if cast_cat is not None and new_commit:
            cast_cat["committed_cents"] = cast_cat.get("committed_cents", 0) + new_commit
            touch(cast_cat)
        recompute_posture(p, actor_user_id=g.user_id)

        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="CONTRACT_SIGNED", subject_entity="Role", subject_id=rid,
            before=before, after=copy.deepcopy(r),
        )
        return ok_object(serialize_role(r))
