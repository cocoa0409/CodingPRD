"""The reference book: producers, vineyard blocks and quality specifications."""
import string

from flask import Blueprint

import derive
import validation as v
from authz import (ACCOUNTS_PAYABLE_CLERK, GROWER, GROWER_RELATIONS_MANAGER,
                   HARVEST_COORDINATOR, QUALITY_LAB_TECH, SCALE_OPERATOR,
                   auth, own)
from common import (DB, by_created_asc, by_created_desc, fail, new_record,
                    read_body, respond, respond_list, rows, touch)
from lookup import find

bp = Blueprint("ref", __name__)

UPPER_HYPHEN = set(string.ascii_uppercase + "-")
UPPER_UNDERSCORE = set(string.ascii_uppercase + "_")


# --------------------------------------------------------------------------
# Growers
# --------------------------------------------------------------------------
@bp.post("/grower-relations/growers")
def create_grower():
    auth(GROWER_RELATIONS_MANAGER)
    body = read_body()
    name = v.req_str(body, "name", 1, 120)
    license_number = v.req_str(body, "license_number", 4, 32)
    region_code = v.req_str(body, "region_code", 2, 16, UPPER_HYPHEN)
    status = v.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")

    for other in rows("growers"):
        if other["license_number"] == license_number:
            fail("ERR_DUPLICATE_CODE",
                 "License number '%s' is already registered." % license_number)

    row = new_record("growers", {
        "name": name,
        "license_number": license_number,
        "region_code": region_code,
        "status": status,
    })
    return respond(derive.grower_json(row), 201)


@bp.post("/grower-relations/growers/<grower_id>/suspend")
def suspend_grower(grower_id):
    auth(GROWER_RELATIONS_MANAGER)
    row = find("growers", grower_id)
    body = read_body()
    v.free_text(body, "reason")
    row["status"] = "SUSPENDED"
    touch(row)
    return respond(derive.grower_json(row))


@bp.post("/grower-relations/growers/<grower_id>/reinstate")
def reinstate_grower(grower_id):
    auth(GROWER_RELATIONS_MANAGER)
    row = find("growers", grower_id)
    row["status"] = "ACTIVE"
    touch(row)
    return respond(derive.grower_json(row))


@bp.get("/grower-relations/growers/<grower_id>")
def get_grower(grower_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         ACCOUNTS_PAYABLE_CLERK, GROWER)
    row = find("growers", grower_id)
    own(user_id, role, row["id"])
    return respond(derive.grower_json(row))


@bp.get("/grower-relations/growers")
def list_growers():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, ACCOUNTS_PAYABLE_CLERK)
    limit, offset = v.pagination()
    region_code = v.filt("region_code")
    status = v.filt("status")
    items = rows("growers")
    if region_code is not None:
        items = [r for r in items if r["region_code"] == region_code]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created_desc(items)
    total = len(items)
    return respond_list([derive.grower_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Vineyard blocks
# --------------------------------------------------------------------------
@bp.post("/grower-relations/vineyard-blocks")
def create_block():
    auth(GROWER_RELATIONS_MANAGER)
    body = read_body()
    grower_id = v.req_id(body, "grower_id")
    grower = find("growers", grower_id)

    block_code = v.req_str(body, "block_code", 1, None)
    varietal = v.req_str(body, "varietal", 3, 40, UPPER_UNDERSCORE)
    acres = v.req_num(body, "acres", 3, exclusive_min=0)
    yield_tpa = v.req_num(body, "expected_yield_tons_per_acre", 3, exclusive_min=0)
    ava_code = v.req_str(body, "ava_code", 2, 24, UPPER_HYPHEN)
    status = v.opt_enum(body, "status", ("ACTIVE", "RETIRED"), "ACTIVE")

    for other in rows("blocks"):
        if other["grower_id"] == grower["id"] and other["block_code"] == block_code:
            fail("ERR_DUPLICATE_CODE",
                 "Block code '%s' is already used by this producer." % block_code)

    row = new_record("blocks", {
        "grower_id": grower["id"],
        "block_code": block_code,
        "varietal": varietal,
        "acres": acres,
        "expected_yield_tons_per_acre": yield_tpa,
        "ava_code": ava_code,
        "status": status,
    })
    return respond(derive.block_json(row), 201)


@bp.get("/grower-relations/vineyard-blocks/<block_id>")
def get_block(block_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         QUALITY_LAB_TECH, SCALE_OPERATOR, GROWER)
    row = find("blocks", block_id)
    own(user_id, role, row["grower_id"])
    return respond(derive.block_json(row))


@bp.get("/grower-relations/vineyard-blocks")
def list_blocks():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH, SCALE_OPERATOR)
    limit, offset = v.pagination()
    grower_id = v.filt("grower_id")
    status = v.filt("status")
    varietal = v.filt("varietal")
    items = rows("blocks")
    if grower_id is not None:
        items = [r for r in items if r["grower_id"] == grower_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if varietal is not None:
        items = [r for r in items if r["varietal"] == varietal]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.block_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Quality specifications
# --------------------------------------------------------------------------
@bp.post("/grower-relations/quality-specs")
def create_spec():
    auth(GROWER_RELATIONS_MANAGER, QUALITY_LAB_TECH)
    body = read_body()
    spec_code = v.req_str(body, "spec_code", 3, 32)
    min_brix_pick_call = v.opt_num(body, "min_brix_pick_call", 1, exclusive_min=0,
                                   default=v.D("21.0"))
    min_brix_accept = v.req_num(body, "min_brix_accept", 1, exclusive_min=0)
    brix_bonus_start = v.req_num(body, "brix_bonus_start", 1, exclusive_min=0)
    brix_penalty_start = v.req_num(body, "brix_penalty_start", 1, exclusive_min=0)
    brix_step = v.opt_num(body, "brix_step", 1, exclusive_min=0, default=v.D("0.5"))
    brix_bonus_pct_per_step = v.opt_num(body, "brix_bonus_pct_per_step", 1, minimum=0,
                                        default=v.D("1.5"))
    brix_penalty_pct_per_step = v.opt_num(body, "brix_penalty_pct_per_step", 1, minimum=0,
                                          default=v.D("2.0"))
    ta_min_gl = v.opt_num(body, "ta_min_gl", 1, exclusive_min=0, default=v.D("5.5"))
    ta_max_gl = v.opt_num(body, "ta_max_gl", 1, default=v.D("9.0"))
    acid_penalty = v.opt_num(body, "acid_out_of_spec_penalty_pct", 1, minimum=0,
                             default=v.D("3.0"))
    rot_free_pct = v.opt_num(body, "rot_free_pct", 1, minimum=0, default=v.D("2.0"))
    rot_penalty = v.opt_num(body, "rot_penalty_pct_per_point", 1, minimum=0,
                            default=v.D("1.5"))
    rot_rejection_pct = v.req_num(body, "rot_rejection_pct", 1)
    mog_max_pct = v.opt_num(body, "mog_max_pct", 1, minimum=0, default=v.D("1.0"))
    mog_penalty_pct = v.opt_num(body, "mog_penalty_pct", 1, minimum=0, default=v.D("2.5"))
    max_total_bonus_pct = v.opt_num(body, "max_total_bonus_pct", 1, minimum=0,
                                    default=v.D("8.0"))
    max_total_penalty_pct = v.opt_num(body, "max_total_penalty_pct", 1, minimum=0,
                                      maximum=100, default=v.D("20.0"))

    if not brix_bonus_start > min_brix_accept:
        v.bad("brix_bonus_start", "must be strictly greater than min_brix_accept")
    if brix_penalty_start < min_brix_accept:
        v.bad("brix_penalty_start", "must be at least min_brix_accept")
    if brix_penalty_start > brix_bonus_start:
        v.bad("brix_penalty_start", "must be at most brix_bonus_start")
    if not ta_max_gl > ta_min_gl:
        v.bad("ta_max_gl", "must be strictly greater than ta_min_gl")
    if not rot_rejection_pct > rot_free_pct:
        v.bad("rot_rejection_pct", "must be strictly greater than rot_free_pct")

    for other in rows("specs"):
        if other["spec_code"] == spec_code:
            fail("ERR_DUPLICATE_CODE", "Spec code '%s' already exists." % spec_code)

    row = new_record("specs", {
        "spec_code": spec_code,
        "min_brix_pick_call": min_brix_pick_call,
        "min_brix_accept": min_brix_accept,
        "brix_bonus_start": brix_bonus_start,
        "brix_penalty_start": brix_penalty_start,
        "brix_step": brix_step,
        "brix_bonus_pct_per_step": brix_bonus_pct_per_step,
        "brix_penalty_pct_per_step": brix_penalty_pct_per_step,
        "ta_min_gl": ta_min_gl,
        "ta_max_gl": ta_max_gl,
        "acid_out_of_spec_penalty_pct": acid_penalty,
        "rot_free_pct": rot_free_pct,
        "rot_penalty_pct_per_point": rot_penalty,
        "rot_rejection_pct": rot_rejection_pct,
        "mog_max_pct": mog_max_pct,
        "mog_penalty_pct": mog_penalty_pct,
        "max_total_bonus_pct": max_total_bonus_pct,
        "max_total_penalty_pct": max_total_penalty_pct,
    })
    return respond(derive.spec_json(row), 201)


@bp.get("/grower-relations/quality-specs/<spec_id>")
def get_spec(spec_id):
    auth(GROWER_RELATIONS_MANAGER, QUALITY_LAB_TECH, HARVEST_COORDINATOR, GROWER)
    row = find("specs", spec_id)
    return respond(derive.spec_json(row))


@bp.get("/grower-relations/quality-specs")
def list_specs():
    auth(GROWER_RELATIONS_MANAGER, QUALITY_LAB_TECH, HARVEST_COORDINATOR)
    limit, offset = v.pagination()
    spec_code = v.filt("spec_code")
    items = rows("specs")
    if spec_code is not None:
        items = [r for r in items if r["spec_code"] == spec_code]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.spec_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)
