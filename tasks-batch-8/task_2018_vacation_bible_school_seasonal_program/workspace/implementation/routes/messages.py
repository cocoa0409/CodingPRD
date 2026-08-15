"""Family messages: draft, send with recipient resolution, cancel (PRD §3.8)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from derived import message_view, classrooms_of_program
from envelope import ok_object
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from routes.common import paginate, empty_body, guard_program_writable
from validate import Field, get_body, validate_body, bad

bp = Blueprint("messages", __name__)

AUDIENCES = {"ALL_FAMILIES", "CLASSROOM", "ALLERGY_ALERT", "VOLUNTEERS"}

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "subject": Field("str", required=True),
    "body": Field("str", required=True),
    "audience": Field("enum", enum=AUDIENCES, required=True),
    "classroom_id": Field("str", default=None, nullable=True),
}


def get_message_or_404(message_id):
    message = store.get("family_messages", message_id)
    if message is None:
        raise_err(ERR_NOT_FOUND, "family message not found")
    return message


def _resolve_recipient_count(message):
    program_id = message["program_id"]
    audience = message["audience"]
    if audience == "VOLUNTEERS":
        return sum(
            1
            for v in store.all_of("volunteers")
            if v["program_id"] == program_id and v["status"] == "CLEARED"
        )
    classroom_ids = {c["id"] for c in classrooms_of_program(program_id)}
    if audience == "CLASSROOM":
        classroom_ids &= {message["classroom_id"]}
    regs = [
        r
        for r in store.all_of("registrations")
        if r["classroom_id"] in classroom_ids
    ]
    if audience in ("ALL_FAMILIES", "CLASSROOM"):
        regs = [r for r in regs if r["status"] in ("ENROLLED", "WAITLISTED", "OFFERED")]
    elif audience == "ALLERGY_ALERT":
        allergy_children = {
            p["child_id"]
            for p in store.all_of("accommodation_plans")
            if p["status"] == "APPROVED" and p["severity"] == "FOOD_ALLERGY"
        }
        regs = [
            r
            for r in regs
            if r["status"] == "ENROLLED" and r["child_id"] in allergy_children
        ]
    child_ids = {r["child_id"] for r in regs}
    family_ids = set()
    for child in store.all_of("children"):
        if child["id"] in child_ids:
            family_ids.add(child["family_id"])
    return len(family_ids)


@bp.post("/vbs/messages")
def create_message():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    # Conditional field rule (P0): classroom_id required iff audience == CLASSROOM.
    if data["audience"] == "CLASSROOM":
        if data.get("classroom_id") is None:
            bad("classroom_id is required when audience is CLASSROOM")
    elif data.get("classroom_id") is not None:
        bad("classroom_id is forbidden unless audience is CLASSROOM")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    if data["audience"] == "CLASSROOM":
        classroom = store.get("classrooms", data["classroom_id"])
        if classroom is None:
            raise_err(ERR_NOT_FOUND, "classroom not found")
    guard_program_writable(program)
    message = store.new_record(
        program_id=program["id"],
        subject=data["subject"],
        body=data["body"],
        audience=data["audience"],
        classroom_id=data.get("classroom_id"),
        status="DRAFT",
        recipient_count=0,
        sent_at=None,
    )
    store.put("family_messages", message)
    return ok_object(message_view(message), status=201)


@bp.post("/vbs/messages/<message_id>/send")
def send_message(message_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    message = get_message_or_404(message_id)
    guard_program_writable(store.get("programs", message["program_id"]))
    if message["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT message may be sent")
    message["recipient_count"] = _resolve_recipient_count(message)
    message["status"] = "SENT"
    message["sent_at"] = clock.now()
    store.touch(message)
    return ok_object(message_view(message))


@bp.post("/vbs/messages/<message_id>/cancel")
def cancel_message(message_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    message = get_message_or_404(message_id)
    guard_program_writable(store.get("programs", message["program_id"]))
    if message["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT message may be cancelled")
    message["status"] = "CANCELLED"
    store.touch(message)
    return ok_object(message_view(message))


@bp.get("/vbs/messages/<message_id>")
def get_message(message_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    return ok_object(message_view(get_message_or_404(message_id)))


@bp.get("/vbs/messages")
def list_messages():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    items = list(store.all_of("family_messages"))
    program_id = request.args.get("program_id")
    classroom_id = request.args.get("classroom_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if classroom_id is not None:
        items = [m for m in items if m["classroom_id"] == classroom_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paginate(items, message_view)
