"""Participant CRUD + decease cascade."""
from __future__ import annotations

from flask import Blueprint

from ..auth import (
    ROLE_AUDITOR,
    ROLE_COMPLIANCE,
    ROLE_CUSTODIAN,
    ROLE_PARTICIPANT,
    require_roles,
)
from ..clock import current_date, parse_date_str
from ..errors import err_not_found, err_validation
from ..helpers import (
    assert_enum,
    assert_string,
    occ_check,
    parse_iso_date,
    require_json_object,
)
from ..responses import created, ok
from ..services.constants import TAX_STATUSES
from ..services.lookups import (
    bump_version,
    get_participant_or_404,
    init_common,
)
from ..services.serialize import serialize_participant
from ..store import store

bp = Blueprint("participants", __name__)


@bp.post("/participants")
@require_roles(ROLE_CUSTODIAN)
def create_participant(**_kw):
    body = require_json_object(allow_empty=False)
    full_name = assert_string(body.get("full_name"), "full_name", max_len=120)
    dob_str = body.get("date_of_birth")
    if not isinstance(dob_str, str):
        raise err_validation("date_of_birth is required")
    dob = parse_iso_date(dob_str, "date_of_birth")
    tax_status = assert_enum(body.get("tax_status"), "tax_status", TAX_STATUSES)

    # Real past date + age >= 18 on creation
    today = current_date()
    if dob >= today:
        raise err_validation("date_of_birth must be a real past date")
    # Age check (>=18 today)
    age = today.year - dob.year - (1 if (today.month, today.day) < (dob.month, dob.day) else 0)
    if age < 18:
        raise err_validation("participant must be at least 18 years old at creation")

    with store().lock:
        p = init_common(
            {
                "full_name": full_name,
                "date_of_birth": dob.isoformat(),
                "tax_status": tax_status,
                "is_deceased": False,
                "date_of_death": None,
            }
        )
        store().participants[p["id"]] = p
        return created(serialize_participant(p))


@bp.get("/participants/<participant_id>")
@require_roles(ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR, ROLE_PARTICIPANT)
def read_participant(participant_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    p = get_participant_or_404(participant_id)
    if role == ROLE_PARTICIPANT and caller != participant_id:
        raise err_not_found(f"Participant {participant_id} not found")
    return ok(serialize_participant(p))


@bp.patch("/participants/<participant_id>")
@require_roles(ROLE_CUSTODIAN)
def update_participant(participant_id: str, **_kw):
    body = require_json_object(allow_empty=False)
    with store().lock:
        p = get_participant_or_404(participant_id)
        # OCC if version supplied
        occ_check(body.get("version"), p["version"])

        new_full_name = None
        if "full_name" in body and body["full_name"] is not None:
            new_full_name = assert_string(body["full_name"], "full_name", max_len=120)
        new_tax_status = None
        if "tax_status" in body and body["tax_status"] is not None:
            new_tax_status = assert_enum(body["tax_status"], "tax_status", TAX_STATUSES)

        if new_full_name is not None:
            p["full_name"] = new_full_name
        if new_tax_status is not None:
            p["tax_status"] = new_tax_status
        bump_version(p)
        return ok(serialize_participant(p))


@bp.post("/participants/<participant_id>/decease")
@require_roles(ROLE_CUSTODIAN)
def decease_participant(participant_id: str, **_kw):
    body = require_json_object(allow_empty=False)
    dod = parse_iso_date(body.get("date_of_death"), "date_of_death")
    with store().lock:
        p = get_participant_or_404(participant_id)
        if p["is_deceased"]:
            # Already deceased — treat as no-op idempotent? scaffold doesn't
            # define an explicit error. Apply the same precondition strictly.
            from ..errors import err_invalid_state
            raise err_invalid_state("Participant is already deceased")

        p["is_deceased"] = True
        p["date_of_death"] = dod.isoformat()
        bump_version(p)

        # Cascade depth 1: every owned Account OPEN -> FROZEN
        for account in store().accounts.values():
            if account["participant_id"] != participant_id:
                continue
            if account["status"] == "OPEN":
                account["status"] = "FROZEN"
                bump_version(account)

        # Cascade depth 2: every PENDING ConversionRequest on those accounts -> CANCELED
        # Scaffold wording: "every PENDING ConversionRequest on those accounts"
        # Per PRD §3.1 "every PENDING ConversionRequest belonging to the participant
        # transitions to CANCELED". Use participant ownership as the source of truth.
        for cr in store().conversions.values():
            if cr["participant_id"] != participant_id:
                continue
            if cr["status"] == "PENDING":
                cr["status"] = "CANCELED"
                bump_version(cr)

        return ok(serialize_participant(p))
