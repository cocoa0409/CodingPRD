"""NDA agreement & signature endpoints with the re-papering cascade."""

from datetime import timedelta

import db
from db import _format_iso, _parse_iso
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_SIGNATURE_EXPIRED,
)
from services.serializers import public

bp = make_blueprint("nda")


def _get_agreement(aid):
    a = db.nda_agreements.get(aid)
    if a is None:
        raise_error(ERR_NOT_FOUND, "NDA agreement not found")
    return a


def _get_signature(sid):
    s = db.nda_signatures.get(sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "NDA signature not found")
    return s


@bp.route("/playtests/nda-agreements", methods=["POST"])
def create_agreement():
    require_roles("LegalCounsel")
    body = get_payload()
    study_id = require_string(body, "study_id")
    version_label = require_string(body, "version_label")
    body_text = require_string(body, "body_text")
    if study_id not in db.studies:
        raise_error(ERR_NOT_FOUND, "Study not found")
    # version_label unique per study
    for a in db.nda_agreements.values():
        if a["study_id"] == study_id and a["version_label"] == version_label:
            raise_error(ERR_INVALID_REQUEST, "version_label must be unique per study")
    rec = {
        "study_id": study_id,
        "version_label": version_label,
        "body_text": body_text,
        "status": "DRAFT",
        "published_at": None,
    }
    stamp_new(rec)
    db.nda_agreements[rec["id"]] = rec
    return success(public(rec, "nda_agreement"), status=201)


@bp.route("/playtests/nda-agreements", methods=["GET"])
def list_agreements():
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.nda_agreements.values())
    for param in ("study_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if str(a.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(a, "nda_agreement") for a in page], status=200, pagination=pagination)


@bp.route("/playtests/nda-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    a = _get_agreement(aid)
    return success(public(a, "nda_agreement"), status=200)


@bp.route("/playtests/nda-agreements/<aid>/publish", methods=["POST"])
def publish_agreement(aid):
    require_roles("LegalCounsel")
    agreement = _get_agreement(aid)
    if agreement["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Agreement must be DRAFT to publish")
    if agreement["study_id"] not in db.studies:
        raise_error(ERR_NOT_FOUND, "Study not found")

    study = db.studies[agreement["study_id"]]
    now_iso = db.clock.now_iso()
    agreement["status"] = "PUBLISHED"
    agreement["published_at"] = now_iso
    touch(agreement)

    # CASCADE link 1: retire the previously PUBLISHED agreement for the same study
    previous = None
    for other in db.nda_agreements.values():
        if (other["study_id"] == agreement["study_id"] and other["id"] != agreement["id"]
                and other["status"] == "PUBLISHED"):
            previous = other
            break

    if previous is not None:
        previous["status"] = "RETIRED"
        touch(previous)

        # CASCADE link 2: void every PENDING / SIGNED signature on the retired agreement
        voided_signed_sigs = []
        for sig in list(db.nda_signatures.values()):
            if sig["agreement_id"] == previous["id"] and sig["status"] in ("PENDING", "SIGNED"):
                was_signed = sig["status"] == "SIGNED"
                sig["status"] = "VOIDED"
                touch(sig)
                if was_signed:
                    voided_signed_sigs.append(sig)

        # CASCADE link 3: re-paper ENROLLED applications back to APPROVED with a
        # fresh PENDING signature on the newly published agreement.
        for sig in voided_signed_sigs:
            app = db.applications.get(sig["application_id"])
            if app is None or app["status"] != "ENROLLED":
                continue
            app["status"] = "APPROVED"
            app["pinned_nda_agreement_id"] = agreement["id"]
            touch(app)
            study["enrolled_count"] = max(0, study.get("enrolled_count", 0) - 1)
            touch(study)
            expires = db.clock.now() + timedelta(days=7)
            new_sig = {
                "agreement_id": agreement["id"],
                "participant_id": app["participant_id"],
                "study_id": study["id"],
                "application_id": app["id"],
                "status": "PENDING",
                "expires_at": _format_iso(expires),
                "signed_at": None,
            }
            stamp_new(new_sig)
            db.nda_signatures[new_sig["id"]] = new_sig

    return success(public(agreement, "nda_agreement"), status=200)


@bp.route("/playtests/nda-signatures", methods=["GET"])
def list_signatures():
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.nda_signatures.values())
    for param in ("agreement_id", "participant_id", "study_id", "application_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(s, "nda_signature") for s in page], status=200, pagination=pagination)


@bp.route("/playtests/nda-signatures/<sid>", methods=["GET"])
def get_signature(sid):
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    s = _get_signature(sid)
    return success(public(s, "nda_signature"), status=200)


@bp.route("/playtests/nda-signatures/<sid>/sign", methods=["POST"])
def sign_signature(sid):
    user_id, _role = require_roles("Participant")
    sig = _get_signature(sid)
    if user_id != sig["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the owning participant may sign")
    if sig["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Signature must be PENDING to sign")
    agreement = db.nda_agreements.get(sig["agreement_id"])
    if agreement is None:
        raise_error(ERR_NOT_FOUND, "NDA agreement not found")
    if agreement["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "Agreement is no longer PUBLISHED")
    now = db.clock.now()
    if now >= _parse_iso(sig["expires_at"]):
        raise_error(ERR_SIGNATURE_EXPIRED, "Signature has expired")

    sig["status"] = "SIGNED"
    sig["signed_at"] = _format_iso(now)
    touch(sig)

    # BUBBLE UP: application APPROVED -> ENROLLED; study.enrolled_count += 1
    app = db.applications.get(sig["application_id"])
    if app is not None and app["status"] == "APPROVED":
        app["status"] = "ENROLLED"
        touch(app)
        study = db.studies.get(app["study_id"])
        if study is not None:
            study["enrolled_count"] = study.get("enrolled_count", 0) + 1
            touch(study)

    return success(public(sig, "nda_signature"), status=200)
