"""Committee member and conflict declaration endpoints."""

from decimal import Decimal

from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import (ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, endpoint)
from response import created, ok, ok_list
from routes.helpers import filtered, lookup, resolve_fk
from services import derive, logic
from validators import (body_json, paginate, present, q_str, v_decimal, v_enum,
                        v_int, v_str_list, v_string)

bp = Blueprint("members", __name__)

MEMBER_STATUSES = ("INVITED", "ACTIVE", "SUSPENDED", "RESIGNED")
SUBJECT_TYPES = ("AUTHOR_EMAIL", "AFFILIATION", "NONE")
CONFLICT_TYPES = ("COAUTHOR", "INSTITUTIONAL", "FINANCIAL", "ADVISORY", "NONE")


@bp.post("/committee-members")
@endpoint(ROLE_ADMIN)
def create_member(actor):
    body = body_json()
    conference = resolve_fk(body, "conference_id")
    full_name = v_string(body, "full_name", required=True, min_len=1, max_len=200)
    email = v_string(body, "email", required=True, min_len=3, max_len=254, lower=True)
    expertise = v_str_list(body, "expertise_keywords", required=True, min_items=1,
                           max_items=8, unique=True, lower=True)
    member_role = v_enum(body, "member_role", ("REVIEWER", "CHAIR"), required=True)
    max_review_load = v_int(body, "max_review_load", minimum=1, maximum=20, default=4)
    bias = v_decimal(body, "calibration_bias", minimum=Decimal("-1.00"),
                     maximum=Decimal("1.00"), default=Decimal("0.00"))
    if conference is None:
        fail("ERR_VALIDATION", "conference_id is required.")
    if bias.as_tuple().exponent < -2:
        fail("ERR_VALIDATION", "calibration_bias supports at most two decimal places.")
    bias = bias.quantize(Decimal("0.01"))

    for existing in db.members.values():
        if existing["conference_id"] == conference["id"] and existing["email"] == email:
            fail("ERR_VALIDATION", "email must be unique within the conference.")

    row = new_row({
        "conference_id": conference["id"],
        "full_name": full_name,
        "email": email,
        "expertise_keywords": expertise,
        "member_role": member_role,
        "max_review_load": max_review_load,
        "calibration_bias": bias,
        "status": "INVITED",
        "coi_declaration_status": "PENDING",
    })
    db.members[row["id"]] = row
    return created(derive.member_out(row))


@bp.get("/committee-members")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def list_members(actor):
    rows = filtered(db.members.values(), {
        "conference_id": q_str("conference_id"),
        "member_role": q_str("member_role"),
        "status": q_str("status"),
        "coi_declaration_status": q_str("coi_declaration_status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.member_out(r) for r in page], meta)


@bp.get("/committee-members/<member_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def get_member(actor, member_id):
    row = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(derive.member_out(row))


@bp.patch("/committee-members/<member_id>")
@endpoint(ROLE_ADMIN)
def patch_member(actor, member_id):
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    body = body_json()
    expertise = v_str_list(body, "expertise_keywords", min_items=1, max_items=8,
                           unique=True, lower=True)
    max_review_load = v_int(body, "max_review_load", minimum=1, maximum=20)
    bias = v_decimal(body, "calibration_bias", minimum=Decimal("-1.00"),
                     maximum=Decimal("1.00"))
    if bias is not None:
        if bias.as_tuple().exponent < -2:
            fail("ERR_VALIDATION", "calibration_bias supports at most two decimal places.")
        bias = bias.quantize(Decimal("0.01"))

    changed = False
    if expertise is not None:
        member["expertise_keywords"] = expertise
        changed = True
    if max_review_load is not None:
        member["max_review_load"] = max_review_load
        changed = True
    if bias is not None:
        member["calibration_bias"] = bias
        changed = True
    if changed:
        touch(member)
    return ok(derive.member_out(member))


@bp.post("/committee-members/<member_id>/status-transitions")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def member_status_transition(actor, member_id):
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    body = body_json()
    to_status = v_enum(body, "to_status", MEMBER_STATUSES, required=True)
    current = member["status"]

    if to_status == "ACTIVE" and current == "INVITED":
        if not derive.member_declarations(member_id):
            fail("ERR_COI_NOT_DECLARED")
        member["status"] = "ACTIVE"
        member["coi_declaration_status"] = "SUBMITTED"
        touch(member)

    elif to_status == "ACTIVE" and current == "SUSPENDED":
        member["status"] = "ACTIVE"
        touch(member)

    elif to_status == "SUSPENDED" and current == "ACTIVE":
        logic.suspend_member(member)

    elif to_status == "RESIGNED" and current in ("INVITED", "ACTIVE", "SUSPENDED"):
        if derive.chaired_session_count(member_id) > 0:
            fail("ERR_MEMBER_STILL_CHAIRING")
        member["status"] = "RESIGNED"
        touch(member)
        for review in list(db.reviews.values()):
            if review["reviewer_member_id"] == member_id and review["status"] == "ASSIGNED":
                logic.void_review(review)

    else:
        fail("ERR_MEMBER_STATE_INVALID",
             "Member cannot move from %s to %s." % (current, to_status))

    return ok(derive.member_out(member))


# ---------------------------------------------------------------------------
# conflict declarations
# ---------------------------------------------------------------------------

declarations_bp = Blueprint("declarations", __name__)


@declarations_bp.post("/conflict-declarations")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def create_declaration(actor):
    body = body_json()
    member = resolve_fk(body, "member_id")
    subject_type = v_enum(body, "conflict_subject_type", SUBJECT_TYPES, required=True)
    conflict_type = v_enum(body, "conflict_type", CONFLICT_TYPES, required=True)
    subject_value = None
    if present(body, "conflict_subject_value"):
        subject_value = v_string(body, "conflict_subject_value", min_len=1, max_len=254)
    if member is None:
        fail("ERR_VALIDATION", "member_id is required.")
    if subject_type == "NONE":
        if subject_value is not None:
            fail("ERR_VALIDATION",
                 "conflict_subject_value must be null when conflict_subject_type is NONE.")
    else:
        if subject_value is None:
            fail("ERR_VALIDATION",
                 "conflict_subject_value is required unless conflict_subject_type is NONE.")
        if subject_type == "AUTHOR_EMAIL" and subject_value != subject_value.lower():
            fail("ERR_VALIDATION", "conflict_subject_value must be lowercase.")

    # ConflictDeclaration carries only id + created_at (no updated_at / version).
    row = new_row({
        "member_id": member["id"],
        "conflict_subject_type": subject_type,
        "conflict_subject_value": subject_value,
        "conflict_type": conflict_type,
        "declared_at": db.now_raw(),
    })
    row.pop("updated_at", None)
    row.pop("version", None)
    db.declarations[row["id"]] = row
    return created(derive.declaration_out(row))


@declarations_bp.get("/conflict-declarations")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def list_declarations(actor):
    rows = filtered(db.declarations.values(), {
        "member_id": q_str("member_id"),
        "conflict_type": q_str("conflict_type"),
        "conflict_subject_type": q_str("conflict_subject_type"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.declaration_out(r) for r in page], meta)


@declarations_bp.get("/conflict-declarations/<declaration_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def get_declaration(actor, declaration_id):
    row = lookup("declarations", declaration_id, "ERR_DECLARATION_NOT_FOUND")
    return ok(derive.declaration_out(row))
