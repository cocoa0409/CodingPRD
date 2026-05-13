from datetime import timedelta

from flask import Blueprint, request

from clock import clock
from db import store
from errors import err
from middleware import require_roles
from response import success, list_response
from services.common import (check_version, emit_audit, emit_external_sync, parse_iso_datetime,
                              parse_pagination, serialize_project, sort_by_created_at,
                              stamp_create, touch)
from services.pricing import (MIN_HIGH_REPETITION_PRICE_CENTS, REPETITION_HIGH_THRESHOLD,
                                compute_final_payout, compute_quote, compute_tax,
                                repetition_rate, segments_for_project)
from services.quality import refresh_translator_rating
from services.terminology import project_has_open_terminology_conflict
from services.validation import (DOMAINS, PRICING_MODES, require_enum, require_field,
                                  require_int, require_string, validate_lang)

bp = Blueprint("projects", __name__)


def _validate_project_create_body(body: dict) -> dict:
    client_id = require_string(body, "client_id")
    client = store.clients.get(client_id)
    if not client:
        raise err("ERR_NOT_FOUND", "client not found")
    name = require_string(body, "name", min_len=1, max_len=200)
    source_lang = validate_lang(require_string(body, "source_lang"))
    target_lang = validate_lang(require_string(body, "target_lang"))
    domain = require_enum(body, "domain", DOMAINS)
    deadline_at_str = require_field(body, "deadline_at")
    if not isinstance(deadline_at_str, str):
        raise err("ERR_VALIDATION_FAILED", "deadline_at must be a string.")
    deadline_at = parse_iso_datetime(deadline_at_str)
    unit_pricing_mode = require_enum(body, "unit_pricing_mode", PRICING_MODES)
    base_unit_price_cents = body.get("base_unit_price_cents")
    if not isinstance(base_unit_price_cents, int) or isinstance(base_unit_price_cents, bool):
        raise err("ERR_VALIDATION_FAILED", "base_unit_price_cents must be an integer.")
    package_size_segments = body.get("package_size_segments", 50)
    if not isinstance(package_size_segments, int) or isinstance(package_size_segments, bool):
        raise err("ERR_VALIDATION_FAILED", "package_size_segments must be an integer.")
    if package_size_segments < 1 or package_size_segments > 500:
        raise err("ERR_VALIDATION_FAILED", "package_size_segments out of range.")
    template_id = body.get("template_id")

    return {
        "client_id": client_id,
        "name": name,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "domain": domain,
        "deadline_at": deadline_at,
        "unit_pricing_mode": unit_pricing_mode,
        "base_unit_price_cents": base_unit_price_cents,
        "package_size_segments": package_size_segments,
        "template_id": template_id,
    }


@bp.post("/projects")
@require_roles("ProjectManager")
def create_project():
    body = request.get_json(silent=True) or {}

    # Apply template defaults BEFORE per-field validation: template seeds default
    # values, explicit body fields override.
    template_id = body.get("template_id")
    template = None
    if template_id is not None:
        if not isinstance(template_id, str):
            raise err("ERR_VALIDATION_FAILED", "template_id must be a string.")
        template = store.project_templates.get(template_id)
        if template is None:
            raise err("ERR_NOT_FOUND", "project_template not found")
        for src, dst in [
            ("default_domain", "domain"),
            ("default_unit_pricing_mode", "unit_pricing_mode"),
            ("default_base_unit_price_cents", "base_unit_price_cents"),
            ("default_package_size_segments", "package_size_segments"),
        ]:
            if dst not in body or body.get(dst) is None:
                body[dst] = template[src]

    fields = _validate_project_create_body(body)

    # Priority 15: ERR_INVALID_PRICE
    if fields["base_unit_price_cents"] < 1:
        raise err("ERR_INVALID_PRICE", "base_unit_price_cents must be >= 1.")
    # Priority 16: ERR_DEADLINE_NOT_IN_FUTURE
    now = clock.now()
    if fields["deadline_at"] <= now:
        raise err("ERR_DEADLINE_NOT_IN_FUTURE", "deadline_at must be strictly in the future.")
    # Priority 17: ERR_SAME_SOURCE_TARGET
    if fields["source_lang"] == fields["target_lang"]:
        raise err("ERR_SAME_SOURCE_TARGET", "source_lang must differ from target_lang.")

    p = {
        **fields,
        "word_count": 0,
        "urgency_tier": "STANDARD",
        "state": "DRAFT",
        "quoted_total_cents": None,
        "final_payout_cents": None,
        "tax_amount_cents": None,
        "payable_at": None,
    }
    stamp_create(p)
    store.projects[p["id"]] = p

    emit_audit(
        subject_type="Project",
        subject_id=p["id"],
        event="STATE_TRANSITION",
        from_state=None,
        to_state="DRAFT",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={"created": True},
    )
    return success(serialize_project(p), status=201)


@bp.get("/projects/<id>")
@require_roles("ProjectManager", "Translator")
def get_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    return success(serialize_project(p))


@bp.put("/projects/<id>")
@require_roles("ProjectManager")
def update_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    if p["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "project not in DRAFT.")
    body = request.get_json(silent=True) or {}

    # OCC check (priority 19)
    check_version(p, body.get("version"))

    new_name = p["name"]
    new_deadline_at = p["deadline_at"]
    new_base = p["base_unit_price_cents"]
    new_pkg = p["package_size_segments"]

    if "name" in body:
        new_name = require_string(body, "name", min_len=1, max_len=200)
    if "deadline_at" in body:
        if body["deadline_at"] is None:
            raise err("ERR_VALIDATION_FAILED", "deadline_at cannot be null.")
        new_deadline_at = parse_iso_datetime(body["deadline_at"])
    if "base_unit_price_cents" in body:
        v = body["base_unit_price_cents"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_VALIDATION_FAILED", "base_unit_price_cents must be integer.")
        new_base = v
    if "package_size_segments" in body:
        v = body["package_size_segments"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_VALIDATION_FAILED", "package_size_segments must be integer.")
        if v < 1 or v > 500:
            raise err("ERR_VALIDATION_FAILED", "package_size_segments out of range.")
        new_pkg = v

    # Priority 14: repetition price gate
    rate = repetition_rate(p["id"])
    if rate >= REPETITION_HIGH_THRESHOLD and new_base < MIN_HIGH_REPETITION_PRICE_CENTS:
        raise err("ERR_REPETITION_PRICE_TOO_LOW", "Project repetition rate >= 75% but unit price below floor.")
    # Priority 15
    if new_base < 1:
        raise err("ERR_INVALID_PRICE", "base_unit_price_cents must be >= 1.")
    # Priority 16
    if new_deadline_at <= p["created_at"]:
        raise err("ERR_DEADLINE_NOT_IN_FUTURE", "deadline_at must be strictly greater than created_at.")

    p["name"] = new_name
    p["deadline_at"] = new_deadline_at
    p["base_unit_price_cents"] = new_base
    p["package_size_segments"] = new_pkg
    touch(p)
    return success(serialize_project(p))


@bp.post("/projects/<id>/quote")
@require_roles("ProjectManager")
def quote_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    if p["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "project not in DRAFT.")

    # PRD §3.2: "The quote runs only when every document under the project
    # is in SPLIT and the project's word_count is strictly greater than zero
    # (otherwise ERR_EMPTY_PROJECT)." Both gates surface the same error.
    docs = [d for d in store.documents.values() if d["project_id"] == id]
    if not docs or any(d["state"] != "SPLIT" for d in docs):
        raise err("ERR_EMPTY_PROJECT", "Project has no split documents.")
    if int(p.get("word_count", 0)) <= 0:
        raise err("ERR_EMPTY_PROJECT", "Project has no segments.")

    # Repetition-price gate re-check on quote (priority 14)
    rate = repetition_rate(p["id"])
    if rate >= REPETITION_HIGH_THRESHOLD and p["base_unit_price_cents"] < MIN_HIGH_REPETITION_PRICE_CENTS:
        raise err("ERR_REPETITION_PRICE_TOO_LOW", "Project repetition rate >= 75% but unit price below floor.")

    # Compute urgency_tier from remaining hours. PRD §3.2 says the boundary
    # is strict (<48 -> CRITICAL, <168 -> RUSH; exactly-48 -> RUSH, exactly-168
    # -> STANDARD). We compute remaining hours by ceiling the second-precision
    # delta so that small processing latency does not flip a user-supplied
    # 48-hour deadline into the CRITICAL bucket.
    import math
    secs_remaining = (p["deadline_at"] - clock.now()).total_seconds()
    hours_to_deadline = math.ceil(secs_remaining / 3600.0)
    if hours_to_deadline < 48:
        urgency = "CRITICAL"
    elif hours_to_deadline < 168:
        urgency = "RUSH"
    else:
        urgency = "STANDARD"
    p["urgency_tier"] = urgency

    # Compute quote
    quoted_total, _ = compute_quote(p)
    p["quoted_total_cents"] = quoted_total
    from_state = p["state"]
    p["state"] = "QUOTED"
    touch(p)
    emit_audit(
        subject_type="Project",
        subject_id=p["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="QUOTED",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={"quoted_total_cents": quoted_total, "urgency_tier": urgency},
    )
    return success(serialize_project(p))


@bp.post("/projects/<id>/activate")
@require_roles("ProjectManager")
def activate_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    if p["state"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "project not in QUOTED.")
    if p.get("quoted_total_cents") is None:
        raise err("ERR_INVALID_STATE", "project not yet quoted.")
    has_translator_assignment = any(
        a["project_id"] == id and a["role"] == "TRANSLATOR"
        for a in store.assignments.values()
    )
    if not has_translator_assignment:
        raise err("ERR_INVALID_STATE", "no TRANSLATOR assignment exists.")
    from_state = p["state"]
    p["state"] = "ACTIVE"
    touch(p)
    emit_audit(
        subject_type="Project",
        subject_id=p["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="ACTIVE",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={},
    )
    return success(serialize_project(p))


@bp.post("/projects/<id>/publish")
@require_roles("ProjectManager")
def publish_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    # State must be ALL_REVIEWED at publish time
    if p["state"] != "ALL_REVIEWED":
        raise err("ERR_PROJECT_NOT_READY", "project not ready: state must be ALL_REVIEWED.")
    # Every segment must be FINAL_APPROVED
    segs = [s for s in store.segments.values() if s["project_id"] == id and s["state"] not in ("REJECTED", "REASSIGNED")]
    if not segs or any(s["state"] != "FINAL_APPROVED" for s in segs):
        raise err("ERR_PROJECT_NOT_READY", "not every segment is FINAL_APPROVED.")
    if int(p.get("word_count", 0)) <= 0:
        raise err("ERR_EMPTY_PROJECT", "Project has no segments.")
    # Terminology gate (priority 13)
    if project_has_open_terminology_conflict(id):
        raise err("ERR_TERMINOLOGY_CONFLICT", "project has open terminology conflicts.")

    # Run final_payout + tax
    final_payout, _ = compute_final_payout(p)
    client = store.clients[p["client_id"]]
    tax = compute_tax(final_payout, int(client["tax_rate_bps"]))
    p["final_payout_cents"] = final_payout
    p["tax_amount_cents"] = tax
    now = clock.now()
    p["payable_at"] = now + timedelta(days=int(client["payment_cycle_days"]))

    from_state = p["state"]
    p["state"] = "PUBLISHED"
    touch(p)

    # Refresh translator ratings for every TRANSLATOR-role COMPLETED assignment translator
    translator_ids = set()
    for a in store.assignments.values():
        if a["project_id"] == id and a["role"] == "TRANSLATOR":
            translator_ids.add(a["translator_id"])
    for tid in translator_ids:
        refresh_translator_rating(tid)

    emit_audit(
        subject_type="Project",
        subject_id=p["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="PUBLISHED",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={"final_payout_cents": final_payout, "tax_amount_cents": tax},
    )
    # Three external sync rows
    for target in ("PAYMENT", "STORAGE", "IM"):
        emit_external_sync(
            project_id=p["id"],
            target_system=target,
            trigger_event="PROJECT_PUBLISHED",
            payload={
                "project_id": p["id"],
                "final_payout_cents": final_payout,
                "tax_amount_cents": tax,
                "payable_at": None if p["payable_at"] is None else p["payable_at"].isoformat(),
            },
            actor_role="ProjectManager",
            actor_id=request.headers.get("X-User-ID"),
        )
    return success(serialize_project(p))


@bp.post("/projects/<id>/cancel")
@require_roles("ProjectManager")
def cancel_project(id):
    p = store.projects.get(id)
    if not p:
        raise err("ERR_NOT_FOUND", "project not found")
    if p["state"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "project cannot be cancelled in this state.")
    # No assignment in ACCEPTED
    if any(a["project_id"] == id and a["state"] == "ACCEPTED" for a in store.assignments.values()):
        raise err("ERR_INVALID_STATE", "an ACCEPTED assignment exists.")

    from_state = p["state"]
    p["state"] = "CANCELLED"
    touch(p)

    # Cascade: reject all non-terminal segments + PENDING assignments
    for seg in store.segments.values():
        if seg["project_id"] != id:
            continue
        if seg["state"] in ("REJECTED", "REASSIGNED", "FINAL_APPROVED"):
            # In DRAFT cascade, set every segment to REJECTED (even FINAL_APPROVED can't exist in DRAFT)
            if from_state == "DRAFT" and seg["state"] == "FINAL_APPROVED":
                pass
            else:
                continue
        prev = seg["state"]
        seg["state"] = "REJECTED"
        touch(seg)
        emit_audit(
            subject_type="Segment",
            subject_id=seg["id"],
            event="STATE_TRANSITION",
            from_state=prev,
            to_state="REJECTED",
            actor_role="system",
            actor_id=None,
            payload={"reason": "project_cancelled"},
        )

    for a in store.assignments.values():
        if a["project_id"] != id:
            continue
        if a["state"] == "PENDING":
            prev = a["state"]
            a["state"] = "REJECTED"
            touch(a)
            emit_audit(
                subject_type="Assignment",
                subject_id=a["id"],
                event="STATE_TRANSITION",
                from_state=prev,
                to_state="REJECTED",
                actor_role="system",
                actor_id=None,
                payload={"reason": "project_cancelled"},
            )

    # Recompute workloads for affected translators
    from services.workload import recompute_workload
    affected_translators = {a["translator_id"] for a in store.assignments.values() if a["project_id"] == id}
    for tid in affected_translators:
        recompute_workload(tid)

    emit_audit(
        subject_type="Project",
        subject_id=p["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="CANCELLED",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={},
    )
    return success(serialize_project(p))


@bp.get("/projects")
@require_roles("ProjectManager")
def list_projects():
    limit, offset = parse_pagination(request.args)
    state_filter = request.args.get("state")
    client_filter = request.args.get("client_id")
    items = list(store.projects.values())
    if state_filter:
        items = [p for p in items if p["state"] == state_filter]
    if client_filter:
        items = [p for p in items if p["client_id"] == client_filter]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_project(p) for p in sliced], total, limit, offset)
