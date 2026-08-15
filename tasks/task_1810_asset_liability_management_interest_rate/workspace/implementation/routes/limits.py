"""PolicyLimit endpoints (PRD 3.5)."""

import store
from envelope import list_response, object_response
from errors import ApiError
from serializers import policy_limit_json
from services import stamp_new, touch
from validate import req_enum, req_num

from routes.common import READ_ROLES, endpoint, get_or_404

METRICS = ("NII_DELTA_PCT", "EVE_DELTA_PCT")
SCENARIO_KINDS = ("PARALLEL_SHOCK", "RAMP", "REGULATORY_PRESET")
LIMIT_STATUSES = ("ACTIVE", "SUSPENDED")


def _validate_applies_to_kinds(body):
    """applies_to_kinds: the single string ALL, or a list of scenario kinds.
    A list carrying "ALL" (e.g. ["ALL"]) is accepted and normalized to the
    bare "ALL" string, so the stored scope is always either "ALL" or a list
    of scenario kinds."""
    if "applies_to_kinds" not in body or body["applies_to_kinds"] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    kinds = body["applies_to_kinds"]
    if isinstance(kinds, str):
        if kinds != "ALL":
            raise ApiError("ERR_INVALID_REQUEST")
        return kinds
    if isinstance(kinds, list) and kinds and all(
            k in SCENARIO_KINDS or k == "ALL" for k in kinds):
        if "ALL" in kinds:
            return "ALL"
        return kinds
    raise ApiError("ERR_INVALID_REQUEST")


def _scope_key(kinds):
    """Canonical scope identity: the bare string "ALL" and any list containing
    "ALL" are the identical all-kinds scope; kind lists compare as sets."""
    if kinds == "ALL" or (isinstance(kinds, list) and "ALL" in kinds):
        return ("ALL",)
    return tuple(sorted(set(kinds)))


def _scope_conflict(book_id, metric, kinds, exclude_id=None):
    """One ACTIVE limit per (book, metric, applies_to_kinds) scope."""
    key = _scope_key(kinds)
    for limit in store.policy_limits.values():
        if limit["id"] == exclude_id:
            continue
        if (
            limit["book_id"] == book_id
            and limit["metric"] == metric
            and limit["status"] == "ACTIVE"
            and _scope_key(limit["applies_to_kinds"]) == key
        ):
            return True
    return False


@endpoint("POST", "/books/<book_id>/policy-limits", roles=["ALCOChair"])
def create_policy_limit(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    # Rung 4: body shape.
    metric = req_enum(body, "metric", METRICS)
    kinds = _validate_applies_to_kinds(body)
    threshold = req_num(body, "threshold_pct", min_v=0)
    from decimal import Decimal as _D
    if _D(str(threshold)) <= 0:  # decline tolerance strictly greater than 0
        raise ApiError("ERR_INVALID_REQUEST")
    # Rung 8: scope uniqueness.
    if _scope_conflict(book["id"], metric, kinds):
        raise ApiError("ERR_LIMIT_SCOPE_CONFLICT")
    limit = {
        "book_id": book["id"],
        "metric": metric,
        "applies_to_kinds": kinds,
        "threshold_pct": threshold,
        "status": "ACTIVE",
    }
    stamp_new(limit)
    store.policy_limits[limit["id"]] = limit
    return object_response(policy_limit_json(limit), 201)


@endpoint("GET", "/books/<book_id>/policy-limits", roles=READ_ROLES)
def list_policy_limits(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = [l for l in store.policy_limits.values() if l["book_id"] == book["id"]]
    metric = ctx.args.get("metric")
    if metric is not None:
        rows = [l for l in rows if l["metric"] == metric]
    status = ctx.args.get("status")
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    return list_response(rows, ctx.args, policy_limit_json)


@endpoint("GET", "/policy-limits/<limit_id>", roles=READ_ROLES)
def get_policy_limit(ctx):
    limit = get_or_404(store.policy_limits, ctx.param("limit_id"))
    return object_response(policy_limit_json(limit))


@endpoint("PATCH", "/policy-limits/<limit_id>", roles=["ALCOChair"])
def patch_policy_limit(ctx):
    limit = get_or_404(store.policy_limits, ctx.param("limit_id"))
    body = ctx.body
    # Rung 4: optional fields validated when present.
    if "threshold_pct" in body and body["threshold_pct"] is not None:
        threshold = req_num(body, "threshold_pct", min_v=0)
        from decimal import Decimal as _D
        if _D(str(threshold)) <= 0:
            raise ApiError("ERR_INVALID_REQUEST")
    else:
        threshold = None
    new_status = None
    if "status" in body and body["status"] is not None:
        new_status = req_enum(body, "status", LIMIT_STATUSES)
    # Rung 8: resuming (SUSPENDED -> ACTIVE) re-runs the scope uniqueness check.
    if new_status == "ACTIVE" and limit["status"] == "SUSPENDED":
        if _scope_conflict(limit["book_id"], limit["metric"], limit["applies_to_kinds"],
                           exclude_id=limit["id"]):
            raise ApiError("ERR_LIMIT_SCOPE_CONFLICT")
    if threshold is not None:
        limit["threshold_pct"] = threshold
    if new_status is not None and new_status != limit["status"]:
        # Only ACTIVE <-> SUSPENDED transitions exist; both are permitted.
        limit["status"] = new_status
    if threshold is not None or new_status is not None:
        touch(limit)
    return object_response(policy_limit_json(limit))
