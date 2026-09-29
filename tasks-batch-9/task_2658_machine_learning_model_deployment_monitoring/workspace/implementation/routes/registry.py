"""Registry entries, training-data snapshots and artifact versions."""

import re

from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
from errors import ApiError
from middleware import ALL_ROLES, DS, MA, MLE, PA, RE

bp = Blueprint("registry", __name__)

TASK_TYPES = ("CLASSIFICATION", "REGRESSION", "RANKING")
LICENSE_CLASSES = ("OPEN", "INTERNAL", "RESTRICTED")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

DATASET_TERMINAL = ("REVOKED",)
VERSION_TERMINAL = ("REJECTED", "DEPRECATED")


def require_present(payload, *fields):
    for field in fields:
        if not mw.present(payload, field):
            mw.bad("%s is required" % field)


def need(table, row_id, error_id):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def body_fk(payload, field, table, error_id, required=True):
    """PRD 2.7 band 3 — body FK ids resolved in declared input field order."""
    if not mw.present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str):
        return None
    row = db.get(table, value)
    if row is None:
        raise ApiError(error_id)
    return row


# =========================================================================
# Models
# =========================================================================
@bp.post("/models")
def create_model():
    user_id, _ = mw.auth(MLE, PA)
    payload = mw.body()
    require_present(payload, "name", "task_type", "owner_team")
    name = mw.vstr(payload, "name", minlen=1, maxlen=120)
    task_type = mw.venum(payload, "task_type", TASK_TYPES)
    owner_team = mw.vstr(payload, "owner_team", minlen=1, maxlen=60)
    interval = mw.vint(payload, "revalidation_interval_days", required=False,
                       minimum=1, maximum=365, default=90)

    for existing in db.rows("models"):
        if existing["name"] == name and existing["owner_team"] == owner_team:
            raise ApiError("ERR_DUPLICATE_MODEL_NAME")

    row = db.insert("models", {
        "name": name,
        "task_type": task_type,
        "owner_team": owner_team,
        "registry_status": "ACTIVE",
        "revalidation_interval_days": interval,
        "champion_version_id": None,
        "champion_promoted_at": None,
        "open_retraining_trigger_count": 0,
        "registered_by_user_id": user_id,
    })
    return response.created(db.public(row))


@bp.get("/models/<model_id>")
def get_model(model_id):
    mw.auth(*ALL_ROLES)
    row = need("models", model_id, "ERR_MODEL_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/models")
def list_models():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("models"), {
        "owner_team": ("owner_team", "str"),
        "task_type": ("task_type", "str"),
        "registry_status": ("registry_status", "str"),
        "champion_version_id": ("champion_version_id", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/models/<model_id>/archive")
def archive_model(model_id):
    mw.auth(PA)
    row = need("models", model_id, "ERR_MODEL_NOT_FOUND")
    row["registry_status"] = "ARCHIVED"
    db.touch(row)
    return response.ok(db.public(row))


# =========================================================================
# Training-data snapshots
# =========================================================================
@bp.post("/training-datasets")
def create_dataset():
    user_id, _ = mw.auth(MLE, DS)
    payload = mw.body()
    require_present(payload, "name", "snapshot_uri", "row_count", "feature_hash",
                    "baseline_bin_proportions", "baseline_positive_rate",
                    "license_class")
    bins = mw.bin_proportions(payload, "baseline_bin_proportions")
    name = mw.vstr(payload, "name", minlen=1, maxlen=120)
    snapshot_uri = mw.vstr(payload, "snapshot_uri", minlen=1, maxlen=400)
    row_count = mw.vint(payload, "row_count", minimum=1)
    feature_hash = mw.vstr(payload, "feature_hash", minlen=1, maxlen=80)
    baseline_positive_rate = mw.vnum(payload, "baseline_positive_rate",
                                     minimum=0, maximum=1)
    license_class = mw.venum(payload, "license_class", LICENSE_CLASSES)
    pii = mw.vbool(payload, "pii_review_passed", required=False, default=False)

    row = db.insert("training_datasets", {
        "name": name,
        "snapshot_uri": snapshot_uri,
        "row_count": row_count,
        "feature_hash": feature_hash,
        "baseline_bin_proportions": bins,
        "baseline_positive_rate": baseline_positive_rate,
        "pii_review_passed": pii,
        "license_class": license_class,
        "approval_state": "DRAFT",
        "registered_by_user_id": user_id,
        "decided_by_user_id": None,
        "decided_at": None,
        "revocation_reason": None,
        "dependent_version_count": 0,
    })
    return response.created(db.public(row))


@bp.get("/training-datasets/<dataset_id>")
def get_dataset(dataset_id):
    mw.auth(*ALL_ROLES)
    row = need("training_datasets", dataset_id, "ERR_TRAINING_DATASET_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/training-datasets")
def list_datasets():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("training_datasets"), {
        "approval_state": ("approval_state", "str"),
        "license_class": ("license_class", "str"),
        "pii_review_passed": ("pii_review_passed", "bool"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/training-datasets/<dataset_id>/submit")
def submit_dataset(dataset_id):
    mw.auth(MLE, DS)
    row = need("training_datasets", dataset_id, "ERR_TRAINING_DATASET_NOT_FOUND")
    if row["approval_state"] in DATASET_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")
    if not row["pii_review_passed"]:
        raise ApiError("ERR_PII_REVIEW_MISSING")
    if row["approval_state"] == "REJECTED":
        # resubmission loop: REJECTED -> DRAFT (clearing the decision) -> SUBMITTED
        row["decided_by_user_id"] = None
        row["decided_at"] = None
    row["approval_state"] = "SUBMITTED"
    db.touch(row)
    return response.ok(db.public(row))


@bp.post("/training-datasets/<dataset_id>/decision")
def decide_dataset(dataset_id):
    user_id, _ = mw.auth(DS)
    row = need("training_datasets", dataset_id, "ERR_TRAINING_DATASET_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "decision")
    decision = mw.venum(payload, "decision", ("APPROVE", "REJECT"))
    mw.vstr(payload, "note", required=False)

    if row["approval_state"] in DATASET_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if user_id == row["registered_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    row["decided_by_user_id"] = user_id
    row["decided_at"] = db.now()
    if decision == "APPROVE":
        row["approval_state"] = "APPROVED"
        db.touch(row)
    else:
        row["approval_state"] = "REJECTED"
        cascades.recompute_dependent_version_count(row)
        db.touch(row)
    return response.ok(db.public(row))


@bp.post("/training-datasets/<dataset_id>/revoke")
def revoke_dataset(dataset_id):
    mw.auth(DS, PA)
    row = need("training_datasets", dataset_id, "ERR_TRAINING_DATASET_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "revocation_reason")
    reason = mw.vstr(payload, "revocation_reason", minlen=1)

    if row["approval_state"] in DATASET_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")

    row["approval_state"] = "REVOKED"
    row["revocation_reason"] = reason
    row["decided_at"] = db.now()
    cascades.revoke_cascade(row)
    db.touch(row)
    return response.ok(db.public(row))


# =========================================================================
# Artifact versions
# =========================================================================
@bp.post("/model-versions")
def create_version():
    mw.auth(MLE)
    payload = mw.body()

    model = body_fk(payload, "model_id", "models", "ERR_MODEL_NOT_FOUND")
    dataset = body_fk(payload, "training_dataset_id", "training_datasets",
                      "ERR_TRAINING_DATASET_NOT_FOUND")
    parent = body_fk(payload, "parent_version_id", "model_versions",
                     "ERR_MODEL_VERSION_NOT_FOUND")

    require_present(payload, "model_id", "training_dataset_id", "semver")
    if not mw.present(payload, "artifact_digest") and not mw.present(payload,
                                                                     "artifact_uri"):
        mw.bad("artifact_digest is required")
    require_present(payload, "feature_spec_hash", "baseline_accuracy",
                    "baseline_positive_rate", "baseline_p95_latency_ms")
    mw.vstr(payload, "model_id")
    mw.vstr(payload, "training_dataset_id")
    semver = mw.vstr(payload, "semver", minlen=1)
    if not SEMVER_RE.match(semver):
        mw.bad("semver must be major.minor.patch")
    if mw.present(payload, "artifact_digest"):
        artifact_digest = mw.vstr(payload, "artifact_digest", minlen=1, maxlen=120)
    else:
        artifact_digest = mw.vstr(payload, "artifact_uri", minlen=1, maxlen=120)
    feature_spec_hash = mw.vstr(payload, "feature_spec_hash", minlen=1, maxlen=80)
    baseline_accuracy = mw.vnum(payload, "baseline_accuracy", minimum=0, maximum=1)
    baseline_positive_rate = mw.vnum(payload, "baseline_positive_rate",
                                     minimum=0, maximum=1)
    baseline_latency = mw.vint(payload, "baseline_p95_latency_ms", minimum=1)
    if mw.present(payload, "parent_version_id"):
        mw.vstr(payload, "parent_version_id")
    doc_sections = mw.vkeylist(payload, "doc_sections", calc.DOC_SECTION_KEYS, [])
    repro_artifacts = mw.vkeylist(payload, "repro_artifacts",
                                  calc.REPRO_ARTIFACT_KEYS, [])
    quota = mw.vint(payload, "evaluation_sample_quota", required=False,
                    minimum=1, maximum=1000000, default=50000)

    if feature_spec_hash != dataset["feature_hash"]:
        raise ApiError("ERR_FEATURE_SPEC_MISMATCH")
    if parent is not None and parent["model_id"] != model["id"]:
        raise ApiError("ERR_LINEAGE_MODEL_MISMATCH")
    for existing in db.rows("model_versions"):
        if existing["model_id"] == model["id"] and existing["semver"] == semver:
            raise ApiError("ERR_DUPLICATE_SEMVER")
    if model["registry_status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_ARCHIVED")

    doc_pct, repro_pct = calc.doc_scores(doc_sections, repro_artifacts)
    row = db.insert("model_versions", {
        "model_id": model["id"],
        "training_dataset_id": dataset["id"],
        "parent_version_id": parent["id"] if parent is not None else None,
        "semver": semver,
        "artifact_digest": artifact_digest,
        "feature_spec_hash": feature_spec_hash,
        "baseline_accuracy": baseline_accuracy,
        "baseline_positive_rate": baseline_positive_rate,
        "baseline_p95_latency_ms": baseline_latency,
        "doc_sections": doc_sections,
        "repro_artifacts": repro_artifacts,
        "doc_completeness_pct": doc_pct,
        "reproducibility_score": repro_pct,
        "approval_state": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "approved_at": None,
        "revalidation_due_at": None,
        "evaluation_sample_quota": quota,
        "evaluation_sample_budget": quota,
        "blocked_reason": None,
    })
    cascades.recompute_dependent_version_count(dataset)
    db.touch(dataset)
    return response.created(db.public(row))


@bp.get("/model-versions/<version_id>")
def get_version(version_id):
    mw.auth(*ALL_ROLES)
    row = need("model_versions", version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/model-versions")
def list_versions():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("model_versions"), {
        "model_id": ("model_id", "str"),
        "training_dataset_id": ("training_dataset_id", "str"),
        "parent_version_id": ("parent_version_id", "str"),
        "approval_state": ("approval_state", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.patch("/model-versions/<version_id>/documentation")
def patch_documentation(version_id):
    mw.auth(MLE)
    row = need("model_versions", version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "doc_sections", "repro_artifacts")
    doc_sections = mw.vkeylist(payload, "doc_sections", calc.DOC_SECTION_KEYS, [])
    repro_artifacts = mw.vkeylist(payload, "repro_artifacts",
                                  calc.REPRO_ARTIFACT_KEYS, [])

    if row["approval_state"] in VERSION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")

    row["doc_sections"] = doc_sections
    row["repro_artifacts"] = repro_artifacts
    doc_pct, repro_pct = calc.doc_scores(doc_sections, repro_artifacts)
    row["doc_completeness_pct"] = doc_pct
    row["reproducibility_score"] = repro_pct
    if row["approval_state"] == "CHANGES_REQUESTED":
        row["approval_state"] = "DRAFT"
        row["decided_by_user_id"] = None
    db.touch(row)
    return response.ok(db.public(row))


@bp.post("/model-versions/<version_id>/submit-for-review")
def submit_version(version_id):
    user_id, _ = mw.auth(MLE)
    row = need("model_versions", version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    if row["approval_state"] in VERSION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    doc_pct, repro_pct = calc.doc_scores(row["doc_sections"], row["repro_artifacts"])
    row["doc_completeness_pct"] = doc_pct
    row["reproducibility_score"] = repro_pct
    if not calc.doc_gate_ok(row):
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
    model = db.get("models", row["model_id"])
    if model is None or model["registry_status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_ARCHIVED")

    row["approval_state"] = "PENDING_REVIEW"
    row["submitted_by_user_id"] = user_id
    db.touch(row)
    return response.ok(db.public(row))


@bp.post("/model-versions/<version_id>/decision")
def decide_version(version_id):
    user_id, _ = mw.auth(MA)
    row = need("model_versions", version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "decision")
    decision = mw.venum(payload, "decision",
                        ("APPROVE", "REQUEST_CHANGES", "REJECT"))
    mw.vstr(payload, "note", required=False)

    if row["approval_state"] in VERSION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    state = row["approval_state"]
    if decision == "APPROVE":
        if state not in ("PENDING_REVIEW", "BLOCKED"):
            raise ApiError("ERR_INVALID_STATE")
    else:
        if state != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_STATE")

    if user_id == row["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    model = db.get("models", row["model_id"])
    dataset = db.get("training_datasets", row["training_dataset_id"])

    if decision == "REQUEST_CHANGES":
        row["approval_state"] = "CHANGES_REQUESTED"
        row["decided_by_user_id"] = user_id
        db.touch(row)
        return response.ok(db.public(row))

    if decision == "REJECT":
        row["approval_state"] = "REJECTED"
        row["decided_by_user_id"] = user_id
        db.touch(row)
        if dataset is not None:
            cascades.recompute_dependent_version_count(dataset)
            db.touch(dataset)
        return response.ok(db.public(row))

    # APPROVE
    if state == "PENDING_REVIEW":
        doc_pct, repro_pct = calc.doc_scores(row["doc_sections"],
                                             row["repro_artifacts"])
        row["doc_completeness_pct"] = doc_pct
        row["reproducibility_score"] = repro_pct
        if not calc.doc_gate_ok(row):
            raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
        if dataset is None or not dataset["pii_review_passed"]:
            raise ApiError("ERR_PII_REVIEW_MISSING")
        if dataset["approval_state"] != "APPROVED":
            raise ApiError("ERR_DATASET_NOT_APPROVED")
        row["approval_state"] = "APPROVED"
        row["decided_by_user_id"] = user_id
        row["approved_at"] = db.now()
        row["revalidation_due_at"] = cascades.revalidation_due(model,
                                                               row["approved_at"])
        db.touch(row)
        if model is not None:
            db.touch(model)
        if dataset is not None:
            cascades.recompute_dependent_version_count(dataset)
        return response.ok(db.public(row))

    # APPROVE from BLOCKED — the unblock path
    if dataset is None or dataset["approval_state"] != "APPROVED":
        raise ApiError("ERR_DATASET_NOT_APPROVED")
    row["approval_state"] = "APPROVED"
    row["blocked_reason"] = None
    row["decided_by_user_id"] = user_id
    row["approved_at"] = db.now()
    row["revalidation_due_at"] = cascades.revalidation_due(model, row["approved_at"])
    db.touch(row)
    if dataset is not None:
        cascades.recompute_dependent_version_count(dataset)
    return response.ok(db.public(row))


@bp.post("/model-versions/<version_id>/deprecate")
def deprecate_version(version_id):
    mw.auth(MA, PA)
    row = need("model_versions", version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    if row["approval_state"] in VERSION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["approval_state"] not in ("APPROVED", "BLOCKED"):
        raise ApiError("ERR_INVALID_STATE")

    for deployment in db.rows("deployments"):
        if (deployment["model_version_id"] == row["id"]
                and deployment["rollout_state"] in calc.LEDGER_STATES):
            raise ApiError("ERR_VERSION_STILL_SERVING")
    model = db.get("models", row["model_id"])
    if model is not None and model["champion_version_id"] == row["id"]:
        raise ApiError("ERR_CANNOT_DEPRECATE_CHAMPION")

    row["approval_state"] = "DEPRECATED"
    row["revalidation_due_at"] = None
    for task in db.sorted_created([t for t in db.rows("revalidation_tasks")
                                   if t["model_version_id"] == row["id"]
                                   and t["status"] in ("DUE", "IN_REVIEW")]):
        task["status"] = "PASSED"
        task["findings"] = "VERSION_DEPRECATED"
        db.touch(task)
    dataset = db.get("training_datasets", row["training_dataset_id"])
    if dataset is not None:
        cascades.recompute_dependent_version_count(dataset)
    db.touch(row)
    return response.ok(db.public(row))
