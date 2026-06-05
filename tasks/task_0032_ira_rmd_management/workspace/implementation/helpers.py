"""Cross-cutting helpers: input parsing, datetime parsing, RMD posture recompute,
audit-event creation, pagination."""

from datetime import datetime, timezone

import db
from errors import ERR_INVALID_REQUEST, raise_api


# ----- Input parsing ----------------------------------------------------------

def get_json_body():
    """Return the parsed JSON body of the current request, or {} for empty bodies.

    Returns an ERR_INVALID_REQUEST when the body is present-but-malformed.
    """
    from flask import request
    if request.method in ("GET", "DELETE"):
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_api(ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_api(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_str(body: dict, key: str) -> str:
    if key not in body or body[key] is None:
        raise_api(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise_api(ERR_INVALID_REQUEST, f"Field {key} must be a non-empty string.")
    return v


def require_int(body: dict, key: str) -> int:
    if key not in body or body[key] is None:
        raise_api(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_api(ERR_INVALID_REQUEST, f"Field {key} must be an integer.")
    return v


def optional_int(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_api(ERR_INVALID_REQUEST, f"Field {key} must be an integer.")
    return v


def optional_bool(body: dict, key: str, default=False) -> bool:
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise_api(ERR_INVALID_REQUEST, f"Field {key} must be a boolean.")
    return v


def require_enum(body: dict, key: str, allowed: set) -> str:
    v = require_str(body, key)
    if v not in allowed:
        raise_api(ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(allowed)}.")
    return v


def parse_iso_datetime(value: str, field_name: str = "datetime"):
    """Parse an ISO 8601 string. Accept a trailing Z. Raise ERR_INVALID_REQUEST on bad input."""
    if not isinstance(value, str) or value == "":
        raise_api(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 string.")
    s = value
    # Python's fromisoformat doesn't accept trailing Z; substitute +00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_api(ERR_INVALID_REQUEST, f"Field {field_name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# ----- Pagination -------------------------------------------------------------

def get_pagination_params():
    """Read limit and offset from query string. Defaults: limit=10, offset=0.
    Constraints: 1 <= limit <= 100; offset >= 0.
    """
    from flask import request
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_str is not None:
        try:
            limit = int(limit_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise_api(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset_str is not None:
        try:
            offset = int(offset_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise_api(ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def paginate(rows: list, limit: int, offset: int):
    """Sort by created_at ASC (PRD §2.3), then apply offset/limit."""
    ordered = sorted(rows, key=lambda r: r["created_at"])
    total = len(ordered)
    sliced = ordered[offset:offset + limit]
    return sliced, total


# ----- Audit events ------------------------------------------------------------

def append_audit_event(owner_id: str, account_id, event_kind: str, tax_year: int, amount_cents: int = 0):
    now = db.now_utc()
    event = {
        "id": db.new_id(),
        "owner_id": owner_id,
        "account_id": account_id,
        "event_kind": event_kind,
        "tax_year": tax_year,
        "amount_cents": amount_cents,
        "occurred_at": now,
        "created_at": now,
    }
    db.audit_events[event["id"]] = event
    return event


# ----- RMD posture recomputation ----------------------------------------------

def recompute_rmd_posture(owner_id: str):
    """PRD §3 — recompute AccountOwner.rmd_posture across all of that owner's
    Traditional accounts. Determined by the union of RMDSchedule rows for the owner.
    """
    owner = db.owners.get(owner_id)
    if owner is None:
        return
    schedules = [s for s in db.rmd_schedules.values() if s["owner_id"] == owner_id]
    if not schedules:
        # No schedules → either not required yet or accounts not Traditional.
        owner["rmd_posture"] = "NOT_REQUIRED"
        owner["updated_at"] = db.now_utc()
        owner["version"] += 1
        return

    # Priority order: DELINQUENT > OPEN with shortfall > SATISFIED > NOT_REQUIRED.
    has_delinquent = any(s["status"] == "DELINQUENT" for s in schedules)
    has_open_shortfall = any(
        s["status"] == "OPEN" and s["satisfied_amount_cents"] < s["required_amount_cents"]
        for s in schedules
    )
    all_satisfied = all(s["status"] == "SATISFIED" for s in schedules)

    if has_delinquent:
        new_posture = "REQUIRED_DELINQUENT"
    elif has_open_shortfall:
        new_posture = "REQUIRED_PENDING"
    elif all_satisfied:
        new_posture = "REQUIRED_MET"
    else:
        new_posture = "NOT_REQUIRED"

    if owner["rmd_posture"] != new_posture:
        owner["rmd_posture"] = new_posture
        owner["updated_at"] = db.now_utc()
        owner["version"] += 1


# ----- Lookups ----------------------------------------------------------------

def get_owner_or_404(owner_id: str):
    from errors import ERR_NOT_FOUND
    owner = db.owners.get(owner_id)
    if owner is None:
        raise_api(ERR_NOT_FOUND, f"AccountOwner {owner_id} not found.")
    return owner


def get_account_or_404(account_id: str):
    from errors import ERR_NOT_FOUND
    acct = db.accounts.get(account_id)
    if acct is None:
        raise_api(ERR_NOT_FOUND, f"IRAAccount {account_id} not found.")
    return acct


def get_contribution_or_404(contrib_id: str):
    from errors import ERR_NOT_FOUND
    c = db.contributions.get(contrib_id)
    if c is None:
        raise_api(ERR_NOT_FOUND, f"Contribution {contrib_id} not found.")
    return c


def get_distribution_or_404(dist_id: str):
    from errors import ERR_NOT_FOUND
    d = db.distributions.get(dist_id)
    if d is None:
        raise_api(ERR_NOT_FOUND, f"Distribution {dist_id} not found.")
    return d


def get_conversion_or_404(conv_id: str):
    from errors import ERR_NOT_FOUND
    c = db.conversions.get(conv_id)
    if c is None:
        raise_api(ERR_NOT_FOUND, f"Conversion {conv_id} not found.")
    return c


def get_beneficiary_or_404(b_id: str):
    from errors import ERR_NOT_FOUND
    b = db.beneficiary_designations.get(b_id)
    if b is None:
        raise_api(ERR_NOT_FOUND, f"BeneficiaryDesignation {b_id} not found.")
    return b


def get_rmd_schedule_or_404(s_id: str):
    from errors import ERR_NOT_FOUND
    s = db.rmd_schedules.get(s_id)
    if s is None:
        raise_api(ERR_NOT_FOUND, f"RMDSchedule {s_id} not found.")
    return s


def get_form_1099r_or_404(f_id: str):
    from errors import ERR_NOT_FOUND
    f = db.forms_1099r.get(f_id)
    if f is None:
        raise_api(ERR_NOT_FOUND, f"Form1099R {f_id} not found.")
    return f


def get_audit_event_or_404(e_id: str):
    from errors import ERR_NOT_FOUND
    e = db.audit_events.get(e_id)
    if e is None:
        raise_api(ERR_NOT_FOUND, f"AuditEvent {e_id} not found.")
    return e


# ----- Form 1099-R helpers ----------------------------------------------------

def void_form_1099r_for_distribution(distribution_id: str):
    """When a distribution is reversed, the form's gross_distribution_cents
    is reset to 0 (the row is retained as evidence)."""
    for f in db.forms_1099r.values():
        if f["distribution_id"] == distribution_id:
            f["gross_distribution_cents"] = 0
