from flask import Blueprint, request

from core import (ERR_INVALID_REQUEST, ApiError, body, db, list_response,
                  new_resource, ok, opt_str, req_int, req_list_str, req_str,
                  require_roles, touch)
from serializers import ser_instrument

bp = Blueprint("instruments", __name__)


def get_instrument_or_404(instrument_id):
    i = db.instruments.get(instrument_id)
    if i is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    return i


def certified_locale_set(instrument):
    s = set()
    for t in db.translations.values():
        if (t["instrument_id"] == instrument["id"] and t["status"] == "CERTIFIED"
                and t["instrument_revision"] == instrument["revision"]):
            s.add(t["locale"])
    return s


@bp.post("/feedback-panel/instruments")
@require_roles("SurveyDesigner")
def create_instrument():
    data = body()
    title = req_str(data, "title")
    question_count = req_int(data, "question_count", min_value=1)
    required_locales = req_list_str(data, "required_locales")
    base_locale = opt_str(data, "base_locale", "en")
    if base_locale not in required_locales:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "base_locale must appear in required_locales")
    inst = new_resource()
    inst.update({
        "title": title,
        "question_count": question_count,
        "required_locales": list(required_locales),
        "base_locale": base_locale,
        "revision": 1,
        "status": "DRAFT",
    })
    db.instruments[inst["id"]] = inst
    return ok(ser_instrument(inst), 201)


@bp.get("/feedback-panel/instruments")
@require_roles("SurveyDesigner", "PanelManager")
def list_instruments():
    items = list(db.instruments.values())
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, ser_instrument)


@bp.get("/feedback-panel/instruments/<instrument_id>")
@require_roles("SurveyDesigner", "PanelManager", "DataAnalyst")
def get_instrument(instrument_id):
    return ok(ser_instrument(get_instrument_or_404(instrument_id)))


def _transition(instrument_id, allowed_from, error="ERR_INSTRUMENT_INVALID_STATE"):
    inst = get_instrument_or_404(instrument_id)
    if inst["status"] not in allowed_from:
        raise ApiError(error, 409,
                       "Instrument transition not valid from status %s" % inst["status"])
    return inst


@bp.post("/feedback-panel/instruments/<instrument_id>/submit-review")
@require_roles("SurveyDesigner")
def submit_review(instrument_id):
    inst = _transition(instrument_id, ("DRAFT",))
    inst["status"] = "IN_REVIEW"
    touch(inst)
    return ok(ser_instrument(inst))


@bp.post("/feedback-panel/instruments/<instrument_id>/approve")
@require_roles("SurveyDesigner")
def approve(instrument_id):
    inst = _transition(instrument_id, ("IN_REVIEW",))
    certified = certified_locale_set(inst)
    for loc in inst["required_locales"]:
        if loc not in certified:
            raise ApiError("ERR_TRANSLATION_NOT_CERTIFIED", 409,
                           "Locale %s lacks a CERTIFIED translation at the current revision" % loc)
    inst["status"] = "APPROVED"
    touch(inst)
    return ok(ser_instrument(inst))


@bp.post("/feedback-panel/instruments/<instrument_id>/revise")
@require_roles("SurveyDesigner")
def revise(instrument_id):
    inst = _transition(instrument_id, ("IN_REVIEW", "APPROVED"))
    if inst["status"] == "APPROVED":
        inst["revision"] += 1
        for t in db.translations.values():
            if (t["instrument_id"] == inst["id"] and t["status"] == "CERTIFIED"
                    and t["instrument_revision"] < inst["revision"]):
                t["status"] = "STALE"
                touch(t)
    inst["status"] = "DRAFT"
    touch(inst)
    return ok(ser_instrument(inst))


@bp.post("/feedback-panel/instruments/<instrument_id>/lock")
@require_roles("SurveyDesigner")
def lock(instrument_id):
    inst = _transition(instrument_id, ("APPROVED",))
    inst["status"] = "LOCKED"
    touch(inst)
    return ok(ser_instrument(inst))
