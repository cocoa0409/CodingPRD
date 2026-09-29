"""Shared rejection-ladder guards (PRD 2.9).

Every guard here corresponds to one numbered step of the normative ladder; the
route handlers invoke them in ladder order.
"""
import constants
import db
import errors
from errors import ApiError


# --- steps 3-6: path existence --------------------------------------------
def get_use_case(use_case_id):
    record = db.use_cases.get(use_case_id)
    if record is None:
        raise ApiError(errors.ERR_USE_CASE_NOT_FOUND, "use case %s does not exist" % use_case_id)
    return record


def get_model_asset(asset_id):
    record = db.model_assets.get(asset_id)
    if record is None:
        raise ApiError(
            errors.ERR_MODEL_ASSET_NOT_FOUND, "model asset %s does not exist" % asset_id
        )
    return record


def get_review_gate(gate_id):
    record = db.review_gates.get(gate_id)
    if record is None:
        raise ApiError(
            errors.ERR_REVIEW_GATE_NOT_FOUND, "review gate %s does not exist" % gate_id
        )
    return record


def get_record(collection, record_id, label="governance record"):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(
            errors.ERR_GOVERNANCE_RECORD_NOT_FOUND,
            "%s %s does not exist" % (label, record_id),
        )
    return record


# --- step 7: body foreign keys, resolved left to right --------------------
def resolve_fk(body, field, collection, error_id, label):
    """Resolve a foreign key carried in the body.

    A value that is present but unresolvable is a 404 (step 7). A value that is
    absent, null or not a string is left to body-shape validation (step 8).
    """
    if field not in body:
        return None
    value = body[field]
    if value is None or not isinstance(value, str):
        return None
    record = collection.get(value)
    if record is None:
        raise ApiError(error_id, "%s %s does not exist" % (label, value))
    return record


def resolve_use_case_fk(body, field="use_case_id"):
    return resolve_fk(
        body, field, db.use_cases, errors.ERR_USE_CASE_NOT_FOUND, "use case"
    )


def resolve_model_asset_fk(body, field="model_asset_id"):
    return resolve_fk(
        body, field, db.model_assets, errors.ERR_MODEL_ASSET_NOT_FOUND, "model asset"
    )


def resolve_binding_fk(body, field="model_binding_id"):
    return resolve_fk(
        body,
        field,
        db.model_bindings,
        errors.ERR_GOVERNANCE_RECORD_NOT_FOUND,
        "model binding",
    )


# --- step 9: optimistic concurrency --------------------------------------
def check_use_case_version(use_case, expected_use_case_version):
    if expected_use_case_version != use_case["version"]:
        raise ApiError(
            errors.ERR_STALE_USE_CASE_VERSION,
            "expected_use_case_version %s does not match current version %s"
            % (expected_use_case_version, use_case["version"]),
        )


# --- step 10: terminal parent --------------------------------------------
def check_not_terminal(use_case):
    if use_case is None:
        return
    if use_case["status"] in constants.TERMINAL_USE_CASE_STATUSES:
        raise ApiError(
            errors.ERR_USE_CASE_TERMINAL,
            "use case %s is %s and admits no further mutation"
            % (use_case["id"], use_case["status"]),
        )
