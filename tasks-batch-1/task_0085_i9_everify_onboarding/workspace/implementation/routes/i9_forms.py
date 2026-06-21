"""I-9 form endpoints (list, get) + Section 3 reverification (list, record)."""

from flask import Blueprint, request

from errors import err
from db import db, stamp_create, touch
from middleware import require_roles, require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
from validation import get_json_body, require_str, require_enum, require_datetime
from clock import now, format_iso8601, parse_iso8601
import serializers
from services import audit

bp = Blueprint("i9_forms", __name__)

REVERIFICATION_REASON = {"EXPIRING_AUTH", "REHIRE", "NAME_CHANGE"}


def _get_form_or_404(form_id):
    form = db.i9_forms.get(form_id)
    if form is None:
        raise err("ERR_NOT_FOUND", "I9Form not found")
    return form


@bp.route("/i9-forms", methods=["GET"])
def list_forms():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.i9_forms)
    onboarding_id = request.args.get("onboarding_id")
    if onboarding_id is not None:
        records = [r for r in records if r.get("onboarding_id") == onboarding_id]
    return paginate_and_respond(records, limit, offset, serializers.i9_form)


@bp.route("/i9-forms/<form_id>", methods=["GET"])
def get_form(form_id):
    require_read_role()
    form = _get_form_or_404(form_id)
    return object_response(serializers.i9_form(form))


@bp.route("/i9-forms/<form_id>/section3", methods=["GET"])
def list_section3(form_id):
    require_read_role()
    form = _get_form_or_404(form_id)
    limit, offset = parse_pagination()
    records = [r for r in sorted_collection(db.reverification_events)
               if r.get("i9_form_id") == form_id]
    return paginate_and_respond(records, limit, offset,
                                serializers.reverification_event)


@bp.route("/i9-forms/<form_id>/section3", methods=["POST"])
def record_section3(form_id):
    user_id, role = require_roles({"HRReviewer"})

    # priority 4: existence, left-to-right — form (path) first, then the
    # work_authorization_id (body) (PRD §2.5).
    form = _get_form_or_404(form_id)
    body = get_json_body()

    work_authorization_id = require_str(body, "work_authorization_id")
    new_auth = db.work_authorizations.get(work_authorization_id)
    if new_auth is None:
        raise err("ERR_NOT_FOUND", "WorkAuthorization not found")

    reverification_reason = require_enum(body, "reverification_reason",
                                         REVERIFICATION_REASON)
    new_expiration_dt = require_datetime(body, "new_expiration_date")

    onboarding = db.onboardings.get(form.get("onboarding_id"))
    if onboarding is None:
        raise err("ERR_NOT_FOUND", "Onboarding not found")

    # priority 5: state guard — onboarding must be REVERIFICATION_DUE.
    if onboarding.get("status") != "REVERIFICATION_DUE":
        raise err("ERR_INVALID_STATE",
                  "Section 3 requires onboarding status REVERIFICATION_DUE")

    # priority 10: the presented authorization must be valid — its
    # effective_valid_until strictly after the clock (PRD §3.6).
    clock = now()
    evu_iso = new_auth.get("effective_valid_until") or new_auth.get("valid_until")
    if evu_iso is None or parse_iso8601(evu_iso) <= clock:
        raise err("ERR_DOCUMENT_EXPIRED",
                  "Presented work authorization is already expired")

    # --- side effects ---
    event = {
        "i9_form_id": form_id,
        "work_authorization_id": work_authorization_id,
        "reverification_reason": reverification_reason,
        "new_expiration_date": format_iso8601(new_expiration_dt),
        "reviewer_id": user_id,
        "completed_at": format_iso8601(clock),
        "status": "RECORDED",
    }
    stamp_create(event)
    db.reverification_events[event["id"]] = event

    # Supersede the prior controlling authorization for this onboarding. The
    # "prior" record (PRD §3.6) is the controlling authorization being replaced,
    # which may already have lapsed to EXPIRED via a clock-driven advance; it is
    # found by excluding the just-presented new auth so the latter is never
    # mistaken for the prior record.
    from services import lifecycle
    prior = lifecycle.controlling_work_auth(onboarding["id"],
                                            exclude_id=new_auth["id"])
    if prior is not None and prior["id"] != new_auth["id"] \
            and prior.get("status") in ("ACTIVE", "EXTENDED", "EXPIRED"):
        prior["status"] = "SUPERSEDED"
        touch(prior)

    # The new auth stays ACTIVE/EXTENDED (do not flip it).
    if new_auth.get("status") not in ("ACTIVE", "EXTENDED"):
        new_auth["status"] = "ACTIVE"
        touch(new_auth)

    form["current_section3_count"] = form.get("current_section3_count", 0) + 1
    form["status"] = "REVERIFIED"
    touch(form)

    onboarding["status"] = "AUTHORIZED"
    touch(onboarding)

    audit.append(onboarding["id"], role, user_id, "REVERIFIED",
                 "Section 3 reverification recorded (%s)" % reverification_reason)

    return object_response(serializers.reverification_event(event), status=201)
