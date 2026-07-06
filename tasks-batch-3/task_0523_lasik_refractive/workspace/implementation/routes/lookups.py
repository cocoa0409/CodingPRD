from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success
from helpers import serialize, get_or_404, paginate, sorted_by_created

bp = Blueprint("lookups", __name__)


# ---- Bookings ----
@bp.get("/refractive/bookings")
@require_auth(["Coordinator", "Surgeon"])
def list_bookings():
    items = list(db.bookings.values())
    for field in ("suite_id", "surgeon_id", "case_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [x for x in items if x[field] == v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.get("/refractive/bookings/<bid>")
@require_auth(["Coordinator", "Surgeon", "Patient"])
def get_booking(bid):
    return success(serialize(get_or_404(db.bookings, bid)), 200)


# ---- Consent forms ----
@bp.get("/refractive/consent-forms")
@require_auth(["Coordinator", "Surgeon", "Patient"])
def list_consent_forms():
    items = list(db.consents.values())
    for field in ("signed_by_patient_id", "case_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [x for x in items if x[field] == v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.get("/refractive/consent-forms/<cid>")
@require_auth(["Coordinator", "Surgeon", "Patient"])
def get_consent_form(cid):
    return success(serialize(get_or_404(db.consents, cid)), 200)
