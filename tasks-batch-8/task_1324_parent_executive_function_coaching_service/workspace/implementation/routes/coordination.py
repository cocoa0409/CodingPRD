"""CoordinationContact, ConsentGrant, CoordinationNote endpoints."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_body, require_fields, get_entity,
                        touch, new_common, contact_pub, consent_pub, note_pub,
                        list_response)
from response import success_object
from services import billing

bp = Blueprint("coordination", __name__)

_SCOPE_COVERAGE = {
    "PROGRESS_ONLY": {"PROGRESS"},
    "GOALS_AND_PROGRESS": {"PROGRESS", "GOALS"},
    "FULL_PLAN": {"PROGRESS", "GOALS", "PLAN_DETAIL"},
}


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@bp.post("/families/<fid>/contacts")
def create_contact(fid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    require_family_scope(auth, fid)
    get_entity("family", fid)
    body = get_body()
    require_fields(body, ["name", "organization", "contact_type", "email"])
    mw.enum_check(body["contact_type"], ["SCHOOL", "CLINICIAN"], "contact_type")
    c = new_common()
    c.update({
        "family_id": fid,
        "name": body["name"],
        "organization": body["organization"],
        "contact_type": body["contact_type"],
        "email": body["email"],
        "status": "ACTIVE",
    })
    db.contacts[c["id"]] = c
    return success_object(contact_pub(c), 201)


@bp.get("/families/<fid>/contacts")
def list_contacts(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    get_entity("family", fid)
    rows = [c for c in db.contacts.values() if c["family_id"] == fid]
    return list_response(rows, contact_pub, paginate=False)


@bp.get("/contacts/<cid>")
def get_contact(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    c = get_entity("contact", cid)
    require_family_scope(auth, c["family_id"])
    return success_object(contact_pub(c), 200)


@bp.post("/contacts/<cid>/transition")
def contact_transition(cid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    c = get_entity("contact", cid)
    require_family_scope(auth, c["family_id"])
    body = get_body()
    require_fields(body, ["to_state"])
    mw.enum_check(body["to_state"], ["INACTIVE"], "to_state")
    if c["status"] != "ACTIVE":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Cannot transition contact from %s to INACTIVE" % c["status"])
    c["status"] = "INACTIVE"
    touch(c)
    billing.revoke_consents_for_contact(cid)  # depth-2 cascade: revoke + seal
    return success_object(contact_pub(c), 200)


# ---------------------------------------------------------------------------
# Consents
# ---------------------------------------------------------------------------

@bp.post("/families/<fid>/consents")
def create_consent(fid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    require_family_scope(auth, fid)
    fam = get_entity("family", fid)
    body = get_body()
    require_fields(body, ["contact_id", "scope", "expires_at", "expected_family_version"])
    contact = get_entity("contact", body["contact_id"])
    mw.enum_check(body["scope"], ["PROGRESS_ONLY", "GOALS_AND_PROGRESS", "FULL_PLAN"],
                  "scope")
    expires = mw.parse_dt(body["expires_at"], "expires_at")
    if expires <= db.clock:
        E.raise_error(E.ERR_VALIDATION, "expires_at must be strictly in the future")
    # OCC (priority 7)
    if body["expected_family_version"] != fam["version"]:
        E.raise_error(E.ERR_STALE_FAMILY_VERSION,
                      "Family version has advanced since the caller last observed it")
    # Linkage (priority 22)
    if contact["family_id"] != fid:
        E.raise_error(E.ERR_CONTACT_NOT_LINKED,
                      "Contact does not belong to this family")

    # Supersede prior non-terminal grants for this contact.
    for cg in db.consents.values():
        if cg["contact_id"] == contact["id"] and cg["status"] in ("PENDING_SIGNATURE", "ACTIVE"):
            was_active = cg["status"] == "ACTIVE"
            cg["status"] = "SUPERSEDED"
            touch(cg)
            if was_active:
                billing.seal_notes_shared_to(contact["id"])

    cg = new_common()
    cg.update({
        "family_id": fid,
        "contact_id": contact["id"],
        "scope": body["scope"],
        "status": "PENDING_SIGNATURE",
        "signed_at": None,
        "expires_at": db.iso(expires),
        "expires_at_dt": expires,
    })
    db.consents[cg["id"]] = cg
    touch(fam)
    return success_object(consent_pub(cg), 201)


@bp.get("/families/<fid>/consents")
def list_family_consents(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    get_entity("family", fid)
    rows = [c for c in db.consents.values() if c["family_id"] == fid]
    return list_response(rows, consent_pub, paginate=False)


@bp.get("/contacts/<cid>/consents")
def list_contact_consents(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    c = get_entity("contact", cid)
    require_family_scope(auth, c["family_id"])
    rows = [cg for cg in db.consents.values() if cg["contact_id"] == cid]
    return list_response(rows, consent_pub, paginate=False)


@bp.post("/consents/<cid>/transition")
def consent_transition(cid):
    auth = get_auth()
    require_roles(auth, ["FamilyMember"])
    cg = get_entity("consent", cid)
    require_family_scope(auth, cg["family_id"])
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["ACTIVE", "REVOKED"], "to_state")

    if to == "ACTIVE":
        if cg["status"] != "PENDING_SIGNATURE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition consent from %s to ACTIVE" % cg["status"])
        if db.clock >= cg["expires_at_dt"]:
            E.raise_error(E.ERR_CONSENT_EXPIRED, "Consent has reached its expires_at")
        cg["status"] = "ACTIVE"
        cg["signed_at"] = db.now_iso()
    else:  # REVOKED
        if cg["status"] not in ("PENDING_SIGNATURE", "ACTIVE"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition consent from %s to REVOKED" % cg["status"])
        was_active = cg["status"] == "ACTIVE"
        cg["status"] = "REVOKED"
        if was_active:
            billing.seal_notes_shared_to(cg["contact_id"])
    touch(cg)
    return success_object(consent_pub(cg), 200)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@bp.post("/clients/<cid>/notes")
def create_note(cid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    client = get_entity("client", cid)
    body = get_body()
    require_fields(body, ["topic", "body"])
    mw.enum_check(body["topic"], ["PROGRESS", "GOALS", "PLAN_DETAIL"], "topic")
    n = new_common()
    n.update({
        "client_id": cid,
        "author_coach_id": auth["user_id"],
        "topic": body["topic"],
        "body": body["body"],
        "status": "DRAFT",
        "shared_with_contact_id": None,
        "shared_at": None,
    })
    db.notes[n["id"]] = n
    return success_object(note_pub(n), 201)


@bp.get("/clients/<cid>/notes")
def list_notes(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    rows = [n for n in db.notes.values() if n["client_id"] == cid]
    return list_response(rows, note_pub, paginate=False)


@bp.post("/notes/<nid>/transition")
def note_transition(nid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    n = get_entity("note", nid)
    require_coach_scope(auth, n["author_coach_id"])
    body = get_body()
    require_fields(body, ["to_state"])
    mw.enum_check(body["to_state"], ["FINALIZED"], "to_state")
    if n["status"] != "DRAFT":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Cannot transition note from %s to FINALIZED" % n["status"])
    n["status"] = "FINALIZED"
    touch(n)
    return success_object(note_pub(n), 200)


@bp.post("/notes/<nid>/share")
def share_note(nid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    n = get_entity("note", nid)
    require_coach_scope(auth, n["author_coach_id"])
    body = get_body()
    require_fields(body, ["contact_id"])
    contact = get_entity("contact", body["contact_id"])
    # State gate (priority 14)
    if n["status"] != "FINALIZED":
        E.raise_error(E.ERR_INVALID_STATE,
                      "Note is %s; only FINALIZED notes can be shared" % n["status"])
    if contact["status"] != "ACTIVE":
        E.raise_error(E.ERR_INVALID_STATE, "Contact is not ACTIVE")
    client = db.clients[n["client_id"]]
    # Consent existence (priority 16)
    grant = None
    for cg in db.consents.values():
        if (cg["contact_id"] == contact["id"] and cg["family_id"] == client["family_id"]
                and cg["status"] == "ACTIVE"):
            grant = cg
            break
    if grant is None:
        E.raise_error(E.ERR_CONSENT_NOT_ACTIVE,
                      "No ACTIVE consent grant for this family and contact")
    # Scope coverage (priority 17)
    if n["topic"] not in _SCOPE_COVERAGE[grant["scope"]]:
        E.raise_error(E.ERR_CONSENT_SCOPE_INSUFFICIENT,
                      "Consent scope %s does not cover topic %s"
                      % (grant["scope"], n["topic"]))
    # Linkage (priority 22)
    if contact["family_id"] != client["family_id"]:
        E.raise_error(E.ERR_CONTACT_NOT_LINKED,
                      "Contact belongs to a different family than the note's client")
    n["status"] = "SHARED"
    n["shared_with_contact_id"] = contact["id"]
    n["shared_at"] = db.now_iso()
    touch(n)
    return success_object(note_pub(n), 200)


@bp.get("/contacts/<cid>/shared-notes")
def shared_notes(cid):
    auth = get_auth()
    require_roles(auth, ["ExternalContact", "PracticeAdmin"])
    if auth["role"] == "ExternalContact" and auth["user_id"] != cid:
        E.raise_error(E.ERR_FORBIDDEN_SCOPE,
                      "ExternalContact may only read its own shared-notes view")
    c = get_entity("contact", cid)
    rows = [n for n in db.notes.values()
            if n["shared_with_contact_id"] == cid and n["status"] == "SHARED"]
    return list_response(rows, note_pub, paginate=False)
