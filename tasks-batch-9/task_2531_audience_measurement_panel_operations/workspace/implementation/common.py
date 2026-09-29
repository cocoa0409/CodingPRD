"""Shared route helpers: reference resolution and concurrency checks."""
from errors import ApiError
from store import NOT_FOUND, db
from util import bad_request

BODY_REF_KIND = {
    "market_id": "markets",
    "quota_cell_id": "quota_cells",
    "universe_estimate_id": "universe_estimates",
    "edit_rule_set_id": "edit_rule_sets",
    "target_edit_rule_set_id": "edit_rule_sets",
    "proposed_edit_rule_set_id": "edit_rule_sets",
    "scope_edit_rule_set_id": "edit_rule_sets",
    "household_id": "households",
    "meter_id": "meters",
    "processing_run_id": "processing_runs",
    "baseline_processing_run_id": "processing_runs",
    "client_id": "clients",
    "supersedes_change_id": "methodology_changes",
}


def must(kind, row_id):
    """Resolve a path or body identifier, or raise that entity's not-found."""
    row = db.get(kind, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def body_ref(body, field, required=True):
    """Body reference existence: ladder step 5, before required/shape checks."""
    kind = BODY_REF_KIND[field]
    if field not in body or body[field] is None:
        if required:
            return None
        return None
    return must(kind, body[field])


def check_expected_version(body, field, row, error_id):
    """Optimistic concurrency against the pinned parent's version."""
    if field not in body or body[field] is None:
        raise bad_request("%s is required" % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer" % field)
    if value != row["version"]:
        raise ApiError(error_id, "%s does not match the current version" % field)


def unique_str_list(body, field, values, min_items=1, max_items=10):
    if len(values) < min_items:
        raise bad_request("%s must contain at least %d item(s)"
                          % (field, min_items))
    if len(values) > max_items:
        raise bad_request("%s must contain at most %d item(s)"
                          % (field, max_items))
    if len(set(values)) != len(values):
        raise bad_request("%s must not contain duplicates" % field)
    return values
