from flask import Blueprint, request

from core import (ApiError, body, db, list_response, new_resource, ok,
                  req_str, require_roles, touch)
from serializers import ser_translation

bp = Blueprint("translations", __name__)


def get_translation_or_404(translation_id):
    t = db.translations.get(translation_id)
    if t is None:
        raise ApiError("ERR_TRANSLATION_NOT_FOUND", 404, "Translation not found")
    return t


@bp.post("/feedback-panel/translations")
@require_roles("SurveyDesigner")
def create_translation():
    data = body()
    instrument_id = req_str(data, "instrument_id")
    instrument = db.instruments.get(instrument_id)
    if instrument is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    locale = req_str(data, "locale")
    translator_ref = req_str(data, "translator_ref")
    for t in db.translations.values():
        if (t["instrument_id"] == instrument_id and t["locale"] == locale
                and t["status"] != "REJECTED"):
            raise ApiError("ERR_DUPLICATE_TRANSLATION", 409,
                           "A non-REJECTED translation already exists for this instrument and locale")
    t = new_resource()
    t.update({
        "instrument_id": instrument_id,
        "locale": locale,
        "translator_ref": translator_ref,
        "instrument_revision": instrument["revision"],
        "status": "SUBMITTED",
    })
    db.translations[t["id"]] = t
    return ok(ser_translation(t), 201)


@bp.get("/feedback-panel/translations")
@require_roles("SurveyDesigner", "PanelManager")
def list_translations():
    items = list(db.translations.values())
    instrument_id = request.args.get("instrument_id")
    if instrument_id is not None:
        items = [t for t in items if t["instrument_id"] == instrument_id]
    locale = request.args.get("locale")
    if locale is not None:
        items = [t for t in items if t["locale"] == locale]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, ser_translation)


@bp.get("/feedback-panel/translations/<translation_id>")
@require_roles("SurveyDesigner")
def get_translation(translation_id):
    return ok(ser_translation(get_translation_or_404(translation_id)))


@bp.post("/feedback-panel/translations/<translation_id>/certify")
@require_roles("SurveyDesigner")
def certify(translation_id):
    t = get_translation_or_404(translation_id)
    if t["status"] != "SUBMITTED":
        raise ApiError("ERR_TRANSLATION_INVALID_STATE", 409,
                       "Certify requires translation status SUBMITTED")
    inst = db.instruments[t["instrument_id"]]
    if inst["status"] not in ("IN_REVIEW", "APPROVED"):
        raise ApiError("ERR_INSTRUMENT_NOT_IN_REVIEW", 409,
                       "Certify requires instrument status IN_REVIEW or APPROVED")
    if t["instrument_revision"] != inst["revision"]:
        raise ApiError("ERR_TRANSLATION_STALE_REVISION", 409,
                       "Translation certifies an older instrument revision")
    t["status"] = "CERTIFIED"
    touch(t)
    return ok(ser_translation(t))


@bp.post("/feedback-panel/translations/<translation_id>/reject")
@require_roles("SurveyDesigner")
def reject(translation_id):
    t = get_translation_or_404(translation_id)
    if t["status"] != "SUBMITTED":
        raise ApiError("ERR_TRANSLATION_INVALID_STATE", 409,
                       "Reject requires translation status SUBMITTED")
    t["status"] = "REJECTED"
    touch(t)
    return ok(ser_translation(t))


@bp.post("/feedback-panel/translations/<translation_id>/resubmit")
@require_roles("SurveyDesigner")
def resubmit(translation_id):
    t = get_translation_or_404(translation_id)
    if t["status"] not in ("REJECTED", "STALE"):
        raise ApiError("ERR_TRANSLATION_INVALID_STATE", 409,
                       "Resubmit requires translation status REJECTED or STALE")
    inst = db.instruments[t["instrument_id"]]
    t["instrument_revision"] = inst["revision"]
    t["status"] = "SUBMITTED"
    touch(t)
    return ok(ser_translation(t))
