"""Release-notes documents and compliance evidence packets."""

from flask import Blueprint, request

import db
import validate as v
from db import make, now, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("docs", __name__)

PUBLISHABLE_PHASES = ("CUT", "STABILIZING", "RELEASED")


# ---------------------------------------------------------------------------
# release notes
# ---------------------------------------------------------------------------
@bp.post("/releases/<release_id>/release-notes")
def generate_release_notes(release_id):
    authenticate(("ReleaseManager",))
    body = v.get_body()
    audience = v.req_enum(body, "audience", ("CUSTOMER", "INTERNAL"))
    release = db.get_release(release_id)

    ids, entry_count, excluded = calc.release_note_generation(release, audience)
    note = make(
        "release_notes",
        {
            "release_id": release_id,
            "audience": audience,
            "state": "DRAFT",
            "included_change_ids": ids,
            "entry_count": entry_count,
            "excluded_change_count": excluded,
            "generated_at": now(),
            "published_at": None,
        },
    )
    return object_response(db.public(note), 201)


@bp.get("/releases/<release_id>/release-notes")
def list_release_notes(release_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_release(release_id)
    records = db.by_creation(db.notes_of_release(release_id))
    audience = request.args.get("audience")
    if audience is not None:
        records = [n for n in records if n["audience"] == audience]
    items = [db.public(n) for n in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/release-notes/<note_id>/publish")
def publish_release_notes(note_id):
    authenticate(("ReleaseManager",))
    v.get_body()
    note = db.get_note(note_id)
    release = db.get_release(note["release_id"])

    if note["state"] != "DRAFT":
        fail("ERR_NOTE_ALREADY_PUBLISHED", "This document has already been published")
    if note["entry_count"] < 1:
        fail("ERR_EMPTY_RELEASE_NOTES", "An empty release-notes document may not be published")
    if release["phase"] not in PUBLISHABLE_PHASES:
        fail("ERR_RELEASE_PHASE_INVALID", "The release has not been cut yet")

    upd(note, state="PUBLISHED", published_at=now())
    cascade.refresh_draft_packets(release)
    return object_response(db.public(note))


# ---------------------------------------------------------------------------
# evidence packets
# ---------------------------------------------------------------------------
@bp.post("/releases/<release_id>/evidence-packets")
def assemble_packet(release_id):
    authenticate(("ComplianceOfficer",))
    body = v.get_body()
    expected_version = v.req_int(body, "expected_release_version")
    release = db.get_release(release_id)

    if expected_version != release["version"]:
        fail(
            "ERR_STALE_RELEASE_VERSION",
            "expected_release_version %s does not match %s"
            % (expected_version, release["version"]),
        )

    for prior in db.by_creation(db.packets_of_release(release_id)):
        if prior["state"] == "DRAFT":
            upd(prior, state="SUPERSEDED")

    computed = calc.evidence_completeness(release, [])
    packet = make(
        "evidence_packets",
        {
            "release_id": release_id,
            "state": "DRAFT",
            "base_index": computed["base_index"],
            "waiver_credit_points": computed["waiver_credit_points"],
            "waiver_count": 0,
            "completeness_index": computed["completeness_index"],
            "missing_items": computed["missing_items"],
            "waivers": [],
            "sealed_at": None,
            "sealed_by_user_id": None,
        },
    )
    packet["_satisfied"] = computed["_satisfied"]
    db.touch(release)
    return object_response(db.public(packet), 201)


@bp.get("/releases/<release_id>/evidence-packets")
def list_packets(release_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_release(release_id)
    records = db.by_creation(db.packets_of_release(release_id))
    state = request.args.get("state")
    if state is not None:
        records = [p for p in records if p["state"] == state]
    items = [db.public(p) for p in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/evidence-packets/<packet_id>/waivers")
def waive_item(packet_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    body = v.get_body()
    item_code = v.req_enum(body, "item_code", calc.ITEM_CODES)
    justification = v.req_str(body, "justification", allow_blank=False)
    packet = db.get_packet(packet_id)

    if packet["state"] != "DRAFT":
        fail("ERR_PACKET_STATE_INVALID", "Only a DRAFT packet may receive a waiver")

    satisfied = packet.get("_satisfied") or {}
    already = set(w["item_code"] for w in packet["waivers"])
    if packet["base_index"] < 50:
        fail("ERR_WAIVER_NOT_ALLOWED", "base_index below 50 earns no waiver credit")
    if satisfied.get(item_code):
        fail("ERR_WAIVER_NOT_ALLOWED", "Item %s is already satisfied" % item_code)
    if item_code in already:
        fail("ERR_WAIVER_NOT_ALLOWED", "Item %s has already been waived" % item_code)

    waivers = list(packet["waivers"]) + [
        {
            "item_code": item_code,
            "justification": justification,
            "waived_by_user_id": user_id,
        }
    ]
    totals = calc.waiver_totals(packet["base_index"], satisfied, waivers)
    upd(
        packet,
        waivers=waivers,
        waiver_count=totals["waiver_count"],
        waiver_credit_points=totals["waiver_credit_points"],
        completeness_index=totals["completeness_index"],
        missing_items=totals["missing_items"],
    )
    return object_response(db.public(packet))


@bp.post("/evidence-packets/<packet_id>/seal")
def seal_packet(packet_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    v.get_body()
    packet = db.get_packet(packet_id)

    if packet["state"] != "DRAFT":
        fail("ERR_PACKET_STATE_INVALID", "Only a DRAFT packet may be sealed")
    if packet["completeness_index"] < 90:
        fail("ERR_EVIDENCE_INCOMPLETE", "completeness_index is below 90")

    upd(packet, state="SEALED", sealed_at=now(), sealed_by_user_id=user_id)
    return object_response(db.public(packet))
