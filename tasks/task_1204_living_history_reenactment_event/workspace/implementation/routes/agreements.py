"""Agreement endpoints: submit (OCC-guarded, superseding), sign, list."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_agreement, get_event
from response import success
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import body, is_int, opt_int, req_dt, req_enum, req_str

bp = Blueprint("agreements", __name__)

AGREEMENT_TYPES = ("LANDOWNER_USE", "INSURANCE_LIABILITY")


@bp.post("/events/<event_id>/agreements")
def create_agreement(event_id):
    authenticate(["EventOrganizer"], creation=True)
    ev = get_event(event_id)
    data = body(request)
    # OCC (priority 4) — a present integer expected_event_version must match.
    eev = data.get("expected_event_version")
    if is_int(eev) and eev != ev["version"]:
        fail("ERR_STALE_VERSION", "expected_event_version does not match current version")
    # Posture (priority 5): submission allowed in any non-terminal posture.
    if ev["event_posture"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_INVALID_EVENT_POSTURE", "agreements cannot be submitted for a terminal event")
    # Body shape (priority 7)
    if "expected_event_version" not in data or not is_int(eev):
        fail("ERR_VALIDATION", "expected_event_version is required")
    agreement_type = req_enum(data, "agreement_type", AGREEMENT_TYPES)
    document_ref = req_str(data, "document_ref")
    effective_from = req_dt(data, "effective_from")
    effective_until = req_dt(data, "effective_until")
    if agreement_type == "INSURANCE_LIABILITY":
        coverage = opt_int(data, "coverage_amount_cents", None, minimum=0)
        if coverage is None:
            fail("ERR_VALIDATION", "coverage_amount_cents is required for INSURANCE_LIABILITY")
    else:
        if data.get("coverage_amount_cents") is not None:
            fail("ERR_VALIDATION", "coverage_amount_cents must be absent for LANDOWNER_USE")
        coverage = None
    # Temporal (priority 8)
    if effective_from > effective_until:
        fail("ERR_INVALID_TIME_RANGE", "effective_from must be on or before effective_until")

    # Side effect: supersede same-type agreements in SUBMITTED or SIGNED.
    for a in db.agreements.values():
        if (
            a["event_id"] == ev["id"]
            and a["agreement_type"] == agreement_type
            and a["status"] in ("SUBMITTED", "SIGNED")
        ):
            a["status"] = "SUPERSEDED"
            touch(a)
    # Agreement activity advances the event version.
    touch(ev)

    rec = new_record()
    rec.update(
        event_id=ev["id"],
        agreement_type=agreement_type,
        document_ref=document_ref,
        coverage_amount_cents=coverage,
        effective_from=effective_from,
        effective_until=effective_until,
        status="SUBMITTED",
        signed_at=None,
        signer_name=None,
    )
    db.agreements[rec["id"]] = rec
    return success(serializers.agreement(rec), 201)


@bp.post("/agreements/<agreement_id>/sign")
def sign_agreement(agreement_id):
    authenticate(["EventOrganizer"])
    ag = get_agreement(agreement_id)
    if ag["status"] != "SUBMITTED":
        fail("ERR_INVALID_AGREEMENT_STATUS", "only a SUBMITTED agreement can be signed")
    signer = req_str(body(request), "signer_name")
    ag["status"] = "SIGNED"
    ag["signed_at"] = db.now()
    ag["signer_name"] = signer
    touch(ag)
    return success(serializers.agreement(ag), 200)


@bp.get("/events/<event_id>/agreements")
def list_agreements(event_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    ev = get_event(event_id)
    items = sorted_all(a for a in db.agreements.values() if a["event_id"] == ev["id"])
    page, meta = paginate(items)
    return success([serializers.agreement(a) for a in page], 200, pagination=meta)
