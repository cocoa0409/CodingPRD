"""ConstructionProgram endpoints (PRD Section 3.6)."""
from flask import Blueprint

import validate
from db import db, insert, ordered
from middleware import authorize, chain_scope
from response import ok, created, ok_list
from routes.helpers import find, maybe, filter_by, unique_code

bp = Blueprint("construction_programs", __name__)

PROGRAM_TYPES = ("NEW_BUILD", "REMODEL")
POSTURES = ("ON_TRACK", "AT_RISK", "BREACHED")
ROLES = ("ChainAdmin", "ProductionPlanner", "ChannelManager", "PlatformAdmin")


@bp.post("/construction-programs")
def create_program():
    actor = authorize("ChainAdmin", "PlatformAdmin")
    payload = validate.body()
    raw_account_id = payload.get("chain_account_id")
    chain_scope(actor, raw_account_id if isinstance(raw_account_id, str) else None)

    chain_account_id = validate.string_field(payload, "chain_account_id")
    program_code = validate.string_field(payload, "program_code", min_len=1, max_len=32)
    program_type = validate.enum_field(payload, "program_type", PROGRAM_TYPES)
    site_count_planned = validate.int_field(payload, "site_count_planned", minimum=1)

    find(db.chain_accounts, chain_account_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    unique_code(db.construction_programs, chain_account_id=chain_account_id,
                program_code=program_code)

    program = insert(db.construction_programs, {
        "chain_account_id": chain_account_id,
        "program_code": program_code,
        "program_type": program_type,
        "site_count_planned": site_count_planned,
        "commit_posture": "ON_TRACK",
    })
    return created(program)


@bp.get("/construction-programs")
def list_programs():
    actor = authorize(*ROLES)
    chain_account_id = validate.str_arg("chain_account_id")
    if chain_account_id is not None:
        chain_scope(actor, chain_account_id)
    limit, offset = validate.pagination()
    program_type = validate.enum_arg("program_type", PROGRAM_TYPES)
    commit_posture = validate.enum_arg("commit_posture", POSTURES)

    items = ordered(db.construction_programs)
    if actor.is_chain_admin:
        items = [p for p in items if p["chain_account_id"] == actor.user_id]
    items = filter_by(items, "chain_account_id", chain_account_id)
    items = filter_by(items, "program_type", program_type)
    items = filter_by(items, "commit_posture", commit_posture)
    return ok_list(items, limit, offset)


@bp.get("/construction-programs/<program_id>")
def get_program(program_id):
    actor = authorize(*ROLES)
    existing = maybe(db.construction_programs, program_id)
    chain_scope(actor, existing["chain_account_id"] if existing else None)
    program = find(db.construction_programs, program_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    return ok(program)
