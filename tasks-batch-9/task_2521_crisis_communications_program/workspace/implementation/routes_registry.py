"""Standing registries (PRD 3.1) plus the logical-clock endpoint (PRD 2.4).

Endpoints in this module (12):
  POST   /_clock/set_current_utc
  POST   /crisis/team-members
  GET    /crisis/team-members/{member_id}
  GET    /crisis/team-members
  POST   /crisis/monitored-channels
  GET    /crisis/monitored-channels/{channel_id}
  GET    /crisis/monitored-channels
  POST   /crisis/monitored-channels/{channel_id}/verify-escalation-path
  POST   /crisis/prepared-materials
  GET    /crisis/prepared-materials/{material_id}
  GET    /crisis/prepared-materials
  POST   /crisis/prepared-materials/{material_id}/review
"""

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    D,
    Field,
    authenticate,
    bool_filter,
    enum_filter,
    fail,
    iso,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    touch,
    validate_body,
)

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ProgramAdmin",))
    body = validate_body([Field("to_iso8601", "datetime", required=True)])
    # Repositioning mutates no entity and triggers no sweep (PRD 2.4).
    store.clock = body["to_iso8601"]
    return ok({"current_utc": iso(store.clock)})


# ---------------------------------------------------------------------------
# TeamMember
# ---------------------------------------------------------------------------
MEMBER_FIELDS = [
    Field("full_name", "string", required=True, max_len=120),
    Field("org_title", "string", required=True, max_len=120),
    Field("privilege_cleared", "bool", default=False),
    Field("media_training_status", "enum", values=("NONE", "CURRENT"), default="NONE"),
    Field("media_training_expires_at", "datetime", default=None, nullable=True),
]


@bp.post("/crisis/team-members")
def create_member():
    authenticate(("ProgramAdmin",))
    body = validate_body(MEMBER_FIELDS)
    expires = body["media_training_expires_at"]
    if body["media_training_status"] == "NONE":
        expires = None
    member = new_record(
        {
            "full_name": body["full_name"],
            "org_title": body["org_title"],
            "privilege_cleared": body["privilege_cleared"],
            "media_training_status": body["media_training_status"],
            "media_training_expires_at": expires,
            "scheduled_interview_minutes": 0,
            "active_assignment_count": 0,
        }
    )
    store.members[member["id"]] = member
    return ok(member, 201)


@bp.get("/crisis/team-members/<member_id>")
def read_member(member_id):
    authenticate(ALL_ROLES)
    return ok(L.get_member(member_id))


@bp.get("/crisis/team-members")
def list_members():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    cleared = bool_filter("privilege_cleared")
    training = enum_filter("media_training_status", ("NONE", "CURRENT"))
    rows = list(store.members.values())
    if cleared is not None:
        rows = [r for r in rows if r["privilege_cleared"] is cleared]
    if training is not None:
        rows = [r for r in rows if r["media_training_status"] == training]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ---------------------------------------------------------------------------
# MonitoredChannel
# ---------------------------------------------------------------------------
CHANNEL_FIELDS = [
    Field("name", "string", required=True, max_len=120),
    Field("channel_type", "enum", required=True, values=L.CHANNEL_TYPES),
    Field("platform_escalation_contact", "string", default=None, nullable=True),
    Field("max_concurrent_corrections", "int", default=1, min=1, max=5),
]


@bp.post("/crisis/monitored-channels")
def create_channel():
    authenticate(("ProgramAdmin",))
    body = validate_body(CHANNEL_FIELDS)
    channel = new_record(
        {
            "name": body["name"],
            "channel_type": body["channel_type"],
            "platform_escalation_contact": body["platform_escalation_contact"],
            "escalation_path_state": "UNVERIFIED",
            "verified_contact_reference": None,
            "max_concurrent_corrections": body["max_concurrent_corrections"],
            "reserved_correction_minutes": 0,
            "open_escalation_count": 0,
        }
    )
    store.channels[channel["id"]] = channel
    return ok(channel, 201)


@bp.get("/crisis/monitored-channels/<channel_id>")
def read_channel(channel_id):
    authenticate(ALL_ROLES)
    return ok(L.get_channel(channel_id))


@bp.get("/crisis/monitored-channels")
def list_channels():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    ctype = enum_filter("channel_type", L.CHANNEL_TYPES)
    path_state = enum_filter("escalation_path_state", ("UNVERIFIED", "VERIFIED"))
    rows = list(store.channels.values())
    if ctype is not None:
        rows = [r for r in rows if r["channel_type"] == ctype]
    if path_state is not None:
        rows = [r for r in rows if r["escalation_path_state"] == path_state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/monitored-channels/<channel_id>/verify-escalation-path")
def verify_escalation_path(channel_id):
    authenticate(("ProgramAdmin",))
    body = validate_body([Field("verified_contact_reference", "string", required=True)])
    channel = L.get_channel(channel_id)
    # No from-state rejection is declared for this endpoint (SCAFFOLD has no
    # MonitoredChannel state machine), so re-verification simply re-records.
    channel["verified_contact_reference"] = body["verified_contact_reference"]
    channel["escalation_path_state"] = "VERIFIED"
    touch(channel)
    return ok(channel)


# ---------------------------------------------------------------------------
# PreparedMaterial
# ---------------------------------------------------------------------------
MATERIAL_FIELDS = [
    Field("scenario_code", "enum", required=True, values=L.SCENARIO_CODES),
    Field("material_type", "enum", required=True, values=L.MATERIAL_TYPES),
    Field("title", "string", required=True, max_len=160),
    Field("dark_site_url", "string", default=None, nullable=True),
]


@bp.post("/crisis/prepared-materials")
def create_material():
    authenticate(("ProgramAdmin", "CommsLead"))
    body = validate_body(MATERIAL_FIELDS)
    material = new_record(
        {
            "scenario_code": body["scenario_code"],
            "material_type": body["material_type"],
            "title": body["title"],
            "dark_site_url": body["dark_site_url"],
            "last_reviewed_at": None,
            "readiness_score": D("0.00"),
            "readiness_state": "DRAFT",
            "reviewer_notes": None,
        }
    )
    store.materials[material["id"]] = material
    return ok(material, 201)


@bp.get("/crisis/prepared-materials/<material_id>")
def read_material(material_id):
    authenticate(ALL_ROLES)
    return ok(L.get_material(material_id))


@bp.get("/crisis/prepared-materials")
def list_materials():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    scenario = enum_filter("scenario_code", L.SCENARIO_CODES)
    mtype = enum_filter("material_type", L.MATERIAL_TYPES)
    rstate = enum_filter("readiness_state", ("DRAFT", "READY", "STALE"))
    rows = list(store.materials.values())
    if scenario is not None:
        rows = [r for r in rows if r["scenario_code"] == scenario]
    if mtype is not None:
        rows = [r for r in rows if r["material_type"] == mtype]
    if rstate is not None:
        rows = [r for r in rows if r["readiness_state"] == rstate]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/prepared-materials/<material_id>/review")
def review_material(material_id):
    authenticate(("CommsLead",))
    body = validate_body([Field("reviewer_notes", "string", required=True)])
    material = L.get_material(material_id)
    if material["readiness_state"] not in ("DRAFT", "STALE"):
        fail("ERR_MATERIAL_STATE_INVALID", "A review is only permitted from DRAFT or STALE.")
    material["last_reviewed_at"] = store.now()
    material["reviewer_notes"] = body["reviewer_notes"]
    material["readiness_score"] = D("100.00")
    material["readiness_state"] = "READY"
    touch(material)
    return ok(material)
