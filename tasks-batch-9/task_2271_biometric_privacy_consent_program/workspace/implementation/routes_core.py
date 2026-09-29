"""Programs, state statutory profiles, the destruction sweep and the clock."""

from decimal import Decimal

from flask import Blueprint

import constants as K
import derive
import serialize
from authz import actor, require_role
from calc import refresh_destruction_due_at
from common import READ_ROLES_ALL, respond, respond_list, respond_raw
from errors import fail
from ops import consents_for_asset
from store import db, fmt_iso, new_record, ordered, touch
from validate import (
    body,
    find_jurisdiction,
    find_program,
    opt_int,
    opt_str_array,
    query_str,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("core", __name__)


# --- ComplianceProgram ------------------------------------------------------

@bp.post("/programs")
def create_program():
    _, role = actor()
    require_role(role, ("SystemOperator",))
    data = body()
    org_name = req_str(data, "org_name")
    org_type = req_enum(data, "org_type", K.ORG_TYPES)
    ceiling = req_int(data, "exposure_ceiling_cents", minimum=0)

    rec = new_record()
    rec.update(
        {
            "org_name": org_name,
            "org_type": org_type,
            "exposure_ceiling_cents": ceiling,
            "posture": "OPEN",
            "consent_gap_count": 0,
            "gated_asset_count": 0,
            "open_deletion_obligation_count": 0,
            "pra_exposure_cents": 0,
            "inventory_completeness_pct": Decimal("100.00"),
        }
    )
    db.programs[rec["id"]] = rec
    return respond(serialize.program, rec, 201)


@bp.get("/programs/<program_id>")
def read_program(program_id):
    _, role = actor()
    require_role(role, READ_ROLES_ALL)
    program = find_program(program_id)
    # Read-through: recomputes inventory_completeness_pct and posture without
    # refreshing updated_at or incrementing version.
    return respond(serialize.program, program)


@bp.post("/programs/<program_id>/destruction-sweeps")
def destruction_sweep(program_id):
    _, role = actor()
    require_role(role, ("SystemOperator",))
    find_program(program_id)
    body()
    program = db.programs[program_id]

    assets = ordered(
        [
            a
            for a in db.assets.values()
            if a["program_id"] == program_id and a["status"] in ("ACTIVE", "GATED")
        ]
    )
    for asset in assets:
        refresh_destruction_due_at(asset)

    due = [
        a
        for a in assets
        if a["destruction_due_at"] is not None and db.clock >= a["destruction_due_at"]
    ]

    swept_asset_count = len(due)
    destroyed_template_count = 0
    expired_consent_count = 0

    for asset in due:
        if asset["templates_destroyed_at"] is None:
            destroyed_template_count += 1
        asset["templates_destroyed_at"] = db.clock
        if asset["status"] == "ACTIVE":
            asset["status"] = "GATED"
        touch(asset)

    for asset in due:
        for consent in consents_for_asset(asset["id"], ("GRANTED",)):
            consent["status"] = "EXPIRED"
            touch(consent)
            expired_consent_count += 1

    program_asset_ids = set(
        a["id"] for a in db.assets.values() if a["program_id"] == program_id
    )
    sla_breached_accommodation_count = 0
    for accommodation in ordered(list(db.accommodations.values())):
        if accommodation["asset_id"] not in program_asset_ids:
            continue
        if accommodation["status"] != "REQUESTED":
            continue
        if accommodation["sla_due_at"] is None or db.clock <= accommodation["sla_due_at"]:
            continue
        accommodation["sla_breached"] = True
        touch(accommodation)
        sla_breached_accommodation_count += 1

    touch(program)
    derive.refresh_all()

    return respond_raw(
        {
            "swept_asset_count": swept_asset_count,
            "destroyed_template_count": destroyed_template_count,
            "expired_consent_count": expired_consent_count,
            "sla_breached_accommodation_count": sla_breached_accommodation_count,
            "program_posture": program["posture"],
        }
    )


# --- Jurisdiction -----------------------------------------------------------

def _validate_state_code(value):
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        fail("ERR_INVALID_REQUEST", "Field 'state_code' must be exactly 2 uppercase letters.")


@bp.post("/jurisdictions")
def create_jurisdiction():
    _, role = actor()
    require_role(role, ("SystemOperator",))
    data = body()
    program_id = req_str(data, "program_id")
    state_code = req_str(data, "state_code")
    _validate_state_code(state_code)
    statute_name = req_str(data, "statute_name")
    pra = req_enum(data, "private_right_of_action", K.PRIVATE_RIGHT_OF_ACTION)
    damages_model = req_enum(data, "damages_model", K.DAMAGES_MODEL)
    requires_written_release = req_bool(data, "requires_written_release")
    translation_required = req_bool(data, "translation_required")
    required_locales = opt_str_array(data, "required_locales", default=[])
    retention_max_days = req_int(data, "retention_max_days", minimum=1)
    notice_lead_days = req_int(data, "notice_lead_days", minimum=0)
    negligent = req_int(data, "per_violation_negligent_cents", minimum=0)
    reckless = req_int(data, "per_violation_reckless_cents", minimum=0)
    cure_period_days = req_int(data, "cure_period_days", minimum=0)
    statutory_cap = opt_int(data, "statutory_cap_cents", minimum=0)

    for existing in db.jurisdictions.values():
        if existing["program_id"] == program_id and existing["state_code"] == state_code:
            fail(
                "ERR_INVALID_REQUEST",
                "state_code %s already exists for this program." % state_code,
            )

    program = find_program(program_id)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "state_code": state_code,
            "statute_name": statute_name,
            "private_right_of_action": pra,
            "damages_model": damages_model,
            "requires_written_release": requires_written_release,
            "translation_required": translation_required,
            "required_locales": list(required_locales),
            "retention_max_days": retention_max_days,
            "notice_lead_days": notice_lead_days,
            "per_violation_negligent_cents": negligent,
            "per_violation_reckless_cents": reckless,
            "cure_period_days": cure_period_days,
            "statutory_cap_cents": statutory_cap,
        }
    )
    db.jurisdictions[rec["id"]] = rec
    touch(program)
    return respond(serialize.jurisdiction, rec, 201)


@bp.patch("/jurisdictions/<jurisdiction_id>")
def amend_jurisdiction(jurisdiction_id):
    _, role = actor()
    require_role(role, ("SystemOperator",))
    data = body()

    updates = {}
    if "private_right_of_action" in data:
        updates["private_right_of_action"] = req_enum(
            data, "private_right_of_action", K.PRIVATE_RIGHT_OF_ACTION
        )
    if "damages_model" in data:
        updates["damages_model"] = req_enum(data, "damages_model", K.DAMAGES_MODEL)
    if "requires_written_release" in data:
        updates["requires_written_release"] = req_bool(data, "requires_written_release")
    if "translation_required" in data:
        updates["translation_required"] = req_bool(data, "translation_required")
    if "required_locales" in data:
        updates["required_locales"] = req_str_array(data, "required_locales", non_empty=False)
    if "retention_max_days" in data:
        updates["retention_max_days"] = req_int(data, "retention_max_days", minimum=1)
    if "notice_lead_days" in data:
        updates["notice_lead_days"] = req_int(data, "notice_lead_days", minimum=0)
    if "per_violation_negligent_cents" in data:
        updates["per_violation_negligent_cents"] = req_int(
            data, "per_violation_negligent_cents", minimum=0
        )
    if "per_violation_reckless_cents" in data:
        updates["per_violation_reckless_cents"] = req_int(
            data, "per_violation_reckless_cents", minimum=0
        )
    if "cure_period_days" in data:
        updates["cure_period_days"] = req_int(data, "cure_period_days", minimum=0)
    if "statutory_cap_cents" in data:
        if data["statutory_cap_cents"] is None:
            updates["statutory_cap_cents"] = None
        else:
            updates["statutory_cap_cents"] = req_int(data, "statutory_cap_cents", minimum=0)

    juris = find_jurisdiction(jurisdiction_id)
    juris.update(updates)
    touch(juris)

    # A statutory ceiling just moved: refresh the horizon of every live point.
    for asset in ordered(list(db.assets.values())):
        if asset["jurisdiction_id"] == jurisdiction_id and asset["status"] in ("ACTIVE", "GATED"):
            refresh_destruction_due_at(asset)

    return respond(serialize.jurisdiction, juris)


@bp.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    _, role = actor()
    require_role(role, READ_ROLES_ALL)
    juris = find_jurisdiction(jurisdiction_id)
    return respond(serialize.jurisdiction, juris)


@bp.get("/jurisdictions")
def list_jurisdictions():
    _, role = actor()
    require_role(role, READ_ROLES_ALL)
    program_id = query_str("program_id")
    state_code = query_str("state_code")
    rows = list(db.jurisdictions.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    return respond_list(rows, serialize.jurisdiction)


# --- logical clock ----------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = actor()
    require_role(role, ("SystemOperator",))
    data = body()
    instant = req_datetime(data, "to_iso8601")
    db.clock = instant
    return respond_raw({"current_utc": fmt_iso(db.clock)})
