"""Equipment models and engineering revisions (PRD 3.1, 3.4)."""

from flask import Blueprint

import calc
from auth import get_model, get_revision, require
from constants import (
    ANY_ROLE,
    CATEGORIES,
    CONSOLE_PLATFORMS,
    DUTY_CLASSES,
    DUTY_MIN_CYCLES,
    FINISH_CODES,
    MODEL_LIFECYCLE,
    REVISION_STATUSES,
    REWORK_LIMIT,
    SUPERSEDE_CHAIN_MAX_DEPTH,
)
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, mutate_forced, new_entity, store
from validation import (
    field_decimal,
    field_enum,
    field_enum_array,
    field_id,
    field_int,
    field_str,
    get_body,
    invalid,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("catalogue", __name__)


# ---------------------------------------------------------------------------
# equipment models
# ---------------------------------------------------------------------------
def _chain_depth(model_id):
    """Number of supersession edges reachable from model_id."""
    depth = 0
    seen = set()
    current = model_id
    while current is not None and current not in seen:
        seen.add(current)
        row = store.equipment_models.get(current)
        if row is None:
            break
        nxt = row.get("supersedes_model_id")
        if nxt is None:
            break
        depth += 1
        current = nxt
        if depth > SUPERSEDE_CHAIN_MAX_DEPTH + 4:
            break
    return depth


@bp.post("/equipment-models")
@require("ProductEngineer")
def create_equipment_model():
    body = get_body()
    name = field_str(body, "name", min_len=1, max_len=120)
    category = field_enum(body, "category", CATEGORIES)
    duty_class = field_enum(body, "duty_class", DUTY_CLASSES)
    unit_list_price_cents = field_int(body, "unit_list_price_cents", minimum=1)
    shipping_weight_kg = field_decimal(body, "shipping_weight_kg", exclusive_min=0)
    allowed_finish_codes = field_enum_array(
        body, "allowed_finish_codes", FINISH_CODES, non_empty=True
    )
    console_platform = field_enum(
        body, "console_platform", CONSOLE_PLATFORMS, required=False
    )
    supersedes_model_id = field_id(body, "supersedes_model_id", required=False)

    if category == "CONNECTED":
        if console_platform is None:
            invalid("Field 'console_platform' is required when category is CONNECTED.")
    elif console_platform is not None:
        invalid("Field 'console_platform' must be null unless category is CONNECTED.")

    # rung 9 — body reference existence
    if supersedes_model_id is not None:
        get_model(supersedes_model_id)

    # rung 24 — global name uniqueness
    for row in store.equipment_models.values():
        if row["name"] == name:
            raise ApiError(
                "ERR_DUPLICATE_REVISION_CODE", "An equipment model name must be unique."
            )

    # rung 25 — supersession graph integrity
    if supersedes_model_id is not None:
        if _chain_depth(supersedes_model_id) + 1 > SUPERSEDE_CHAIN_MAX_DEPTH:
            raise ApiError(
                "ERR_SUPERSEDE_CYCLE",
                "The supersession chain may be at most %d edges long."
                % SUPERSEDE_CHAIN_MAX_DEPTH,
            )

    model = new_entity(
        {
            "name": name,
            "category": category,
            "duty_class": duty_class,
            "unit_list_price_cents": unit_list_price_cents,
            "shipping_weight_kg": shipping_weight_kg,
            "allowed_finish_codes": allowed_finish_codes,
            "console_platform": console_platform,
            "connected": category == "CONNECTED",
            "supersedes_model_id": supersedes_model_id,
            "lifecycle_status": "PRE_RELEASE",
            "released_revision_count": 0,
        }
    )
    store.equipment_models[model["id"]] = model
    return created(model)


@bp.get("/equipment-models")
@require(*ANY_ROLE)
def list_equipment_models():
    limit, offset = paging()
    category = query_enum("category", CATEGORIES)
    lifecycle_status = query_enum("lifecycle_status", MODEL_LIFECYCLE)
    supersedes_model_id = query_str("supersedes_model_id")

    rows = list(store.equipment_models.values())
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if lifecycle_status is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle_status]
    if supersedes_model_id is not None:
        rows = [r for r in rows if r["supersedes_model_id"] == supersedes_model_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/equipment-models/<model_id>")
@require(*ANY_ROLE)
def get_equipment_model(model_id):
    return ok(get_model(model_id))


# ---------------------------------------------------------------------------
# model revisions
# ---------------------------------------------------------------------------
@bp.post("/model-revisions")
@require("ProductEngineer")
def create_model_revision():
    body = get_body()
    equipment_model_id = field_id(body, "equipment_model_id")
    revision_code = field_str(body, "revision_code", min_len=1, max_len=40)
    target_cycle_count = field_int(body, "target_cycle_count", minimum=1000)
    firmware_baseline_version = field_str(
        body, "firmware_baseline_version", required=False, min_len=1
    )
    expected_version = field_int(body, "expected_equipment_model_version", minimum=0)

    # rung 9
    model = get_model(equipment_model_id)

    # rung 10 — version pinning
    if expected_version != model["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "The equipment model has been modified since it was read.",
        )

    # rung 24 — revision code uniqueness within the model
    for row in calc.model_revisions(model["id"]):
        if row["revision_code"] == revision_code and row["status"] != "SUPERSEDED":
            raise ApiError(
                "ERR_DUPLICATE_REVISION_CODE",
                "The revision code is already in use on this model.",
            )

    revision = new_entity(
        {
            "equipment_model_id": model["id"],
            "revision_code": revision_code,
            "status": "DRAFT",
            "target_cycle_count": target_cycle_count,
            "firmware_baseline_version": firmware_baseline_version,
            "min_required_cycles": DUTY_MIN_CYCLES[model["duty_class"]],
            "verified_cycle_count": 0,
            "projected_cycle_count": 0,
            "rework_count": 0,
            "qualified_at": None,
            "released_at": None,
            "sunset_announced_at": None,
            "firmware_support_until": None,
        }
    )
    store.model_revisions[revision["id"]] = revision

    with mutate_forced(model):
        calc.recompute_model(model)
    return created(revision)


@bp.get("/model-revisions")
@require(*ANY_ROLE)
def list_model_revisions():
    limit, offset = paging()
    equipment_model_id = query_str("equipment_model_id")
    status = query_enum("status", REVISION_STATUSES)

    rows = list(store.model_revisions.values())
    if equipment_model_id is not None:
        rows = [r for r in rows if r["equipment_model_id"] == equipment_model_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/model-revisions/<revision_id>")
@require(*ANY_ROLE)
def get_model_revision(revision_id):
    return ok(get_revision(revision_id))


@bp.post("/model-revisions/<revision_id>/submit-for-testing")
@require("ProductEngineer")
def submit_for_testing(revision_id):
    revision = get_revision(revision_id)
    get_body()
    model = calc.model_of_revision(revision)

    if revision["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a DRAFT revision may be submitted for testing.",
        )
    if model["lifecycle_status"] == "OBSOLETE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "The owning model is obsolete."
        )
    if model["connected"] and not model["console_platform"]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A connected model must declare a console platform.",
        )

    with mutate(revision):
        revision["status"] = "IN_TESTING"
    calc.recompute_model(model)
    return ok(revision)


@bp.post("/model-revisions/<revision_id>/rework")
@require("ProductEngineer")
def rework_revision(revision_id):
    revision = get_revision(revision_id)
    body = get_body()
    field_str(body, "rework_note", min_len=1)

    if revision["status"] not in ("IN_TESTING", "TEST_FAILED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an IN_TESTING or TEST_FAILED revision may be reworked.",
        )
    if calc.has_outstanding_runs(revision["id"]):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A durability run is still outstanding for this revision.",
        )
    if revision["rework_count"] >= REWORK_LIMIT:
        raise ApiError(
            "ERR_REWORK_LIMIT_EXCEEDED",
            "The revision has exhausted its rework budget.",
        )

    for run in calc.revision_runs(revision["id"]):
        if run["status"] == "COMPLETED" and not run["superseded_by_rework"]:
            with mutate(run):
                run["superseded_by_rework"] = True

    with mutate(revision):
        revision["status"] = "DRAFT"
        revision["rework_count"] += 1
    calc.recompute_revision_cycles(revision)
    calc.recompute_model(calc.model_of_revision(revision))
    return ok(revision)


@bp.post("/model-revisions/<revision_id>/qualify")
@require("ProductEngineer")
def qualify_revision(revision_id):
    revision = get_revision(revision_id)
    get_body()

    if revision["status"] != "IN_TESTING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an IN_TESTING revision may be qualified.",
        )
    if revision["verified_cycle_count"] < revision["min_required_cycles"]:
        raise ApiError(
            "ERR_CYCLE_TARGET_NOT_MET",
            "The verified cycle count has not reached the qualification gate.",
        )
    if calc.has_outstanding_runs(revision["id"]):
        raise ApiError(
            "ERR_CYCLE_TARGET_NOT_MET",
            "A durability run is still outstanding for this revision.",
        )

    with mutate(revision):
        revision["status"] = "QUALIFIED"
        revision["qualified_at"] = store.now_iso()
    calc.recompute_model(calc.model_of_revision(revision))
    return ok(revision)


@bp.post("/model-revisions/<revision_id>/release")
@require("ComplianceOfficer")
def release_revision(revision_id):
    revision = get_revision(revision_id)
    get_body()
    model = calc.model_of_revision(revision)

    if revision["status"] != "QUALIFIED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a QUALIFIED revision may be released.",
        )
    if model["connected"]:
        certified = any(
            cert["cert_status"] == "CERTIFIED"
            for cert in calc.revision_certifications(revision["id"])
        )
        if not certified:
            raise ApiError(
                "ERR_FIRMWARE_NOT_CERTIFIED",
                "A connected model requires a certified firmware pairing.",
            )

    with mutate(revision):
        revision["status"] = "RELEASED"
        revision["released_at"] = store.now_iso()
    calc.recompute_model(model)

    predecessor_id = model["supersedes_model_id"]
    if predecessor_id:
        predecessor = store.equipment_models.get(predecessor_id)
        if predecessor is not None:
            for row in calc.model_revisions(predecessor_id):
                if row["status"] == "RELEASED":
                    with mutate(row):
                        row["status"] = "SUPERSEDED"
            calc.recompute_model(predecessor)
    return ok(revision)


@bp.post("/model-revisions/<revision_id>/sunset")
@require("ComplianceOfficer")
def sunset_revision(revision_id):
    revision = get_revision(revision_id)
    body = get_body()
    field_str(body, "sunset_reason", min_len=1)

    if revision["status"] != "RELEASED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a RELEASED revision may be sunset.",
        )

    announced = store.now()
    with mutate(revision):
        revision["status"] = "SUNSET_ANNOUNCED"
        revision["sunset_announced_at"] = store.now_iso()
        revision["firmware_support_until"] = calc.sunset_horizon(announced)
    calc.recompute_model(calc.model_of_revision(revision))
    calc.sunset_cascade(revision)
    return ok(revision)


@bp.post("/model-revisions/<revision_id>/mark-obsolete")
@require("ComplianceOfficer")
def mark_revision_obsolete(revision_id):
    revision = get_revision(revision_id)
    get_body()

    if revision["status"] != "SUNSET_ANNOUNCED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SUNSET_ANNOUNCED revision may be declared obsolete.",
        )
    horizon = calc.dt(revision["firmware_support_until"])
    if horizon is None or horizon > store.now():
        raise ApiError(
            "ERR_SUPPORT_WINDOW_ACTIVE",
            "The firmware support commitment has not lapsed yet.",
        )

    with mutate(revision):
        revision["status"] = "OBSOLETE"
    calc.recompute_model(calc.model_of_revision(revision))
    return ok(revision)


@bp.get("/model-revisions/<revision_id>/qualification-report")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def qualification_report(revision_id):
    revision = get_revision(revision_id)
    verified, projected, completed, running = calc.cycle_counts(revision["id"])
    return ok(
        {
            "verified_cycle_count": verified,
            "projected_cycle_count": projected,
            "min_required_cycles": revision["min_required_cycles"],
            "completed_run_count": completed,
            "running_run_count": running,
            "qualifies": verified >= revision["min_required_cycles"],
        }
    )
