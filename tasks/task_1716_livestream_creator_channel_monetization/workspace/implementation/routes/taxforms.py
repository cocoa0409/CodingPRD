"""Tax form submission (supersession, OCC-guarded), reads, and adjudication."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_invalid_state,
                  err_not_found, err_ownership, ok_obj, opt_str, paginate,
                  pagination, req_enum, req_int, req_str, require_role)

bp = Blueprint("taxforms", __name__)

FORM_TYPES = ("W9", "W8BEN", "W8BENE")
READ_ROLES = ("PlatformAdmin", "Creator", "TrustAgent")


@bp.post("/api/channels/<channel_id>/tax-forms")
def submit_tax_form(channel_id):
    uid, role = auth()
    b = body()
    form_type = req_enum(b, "form_type", FORM_TYPES)
    legal_name = req_str(b, "legal_name")
    tax_id_last4 = req_str(b, "tax_id_last4")
    expected_version = req_int(b, "expected_channel_version")
    require_role(role, ("Creator",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    if uid != ch["id"]:
        raise err_ownership()
    if expected_version != ch["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_channel_version does not match the channel's current version")
    old_posture = domain.monetization_posture(ch)
    # Supersession: the new form is born SUBMITTED and becomes current; the
    # previous current form is chained via prior_form_id (null for the first).
    form = db.new_entity(
        channel_id=ch["id"],
        form_type=form_type,
        legal_name=legal_name,
        tax_id_last4=tax_id_last4,
        tax_status="SUBMITTED",
        submitted_at=db.now(),
        verified_at=None,
        rejection_reason=None,
        expires_on=None,
        prior_form_id=ch.get("tax_form_current_id"),
    )
    db.store.tax_forms[form["id"]] = form
    ch["tax_form_current_id"] = form["id"]
    db.touch(ch)  # supersession increments Channel.version by 1
    # Posture recomputed on every tax-form transition; a new unverified current
    # form can pull STANDARD -> RESTRICTED and hold SCHEDULED payouts.
    domain.posture_cascade(ch, old_posture, cause="TAX_FORM")
    return ok_obj(domain.tax_form_json(form), status=201)


@bp.get("/api/tax-forms/<tax_form_id>")
def get_tax_form(tax_form_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    form = db.store.tax_forms.get(tax_form_id)
    if form is None:
        raise err_not_found("Tax form not found")
    return ok_obj(domain.tax_form_json(form))


@bp.get("/api/tax-forms")
def list_tax_forms():
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, READ_ROLES)
    forms = list(db.store.tax_forms.values())
    channel_id = request_channel_id()
    if channel_id is not None:
        forms = [f for f in forms if f["channel_id"] == channel_id]
    tax_status = request_arg("tax_status")
    if tax_status is not None:
        forms = [f for f in forms if f["tax_status"] == tax_status]
    prior_form_id = request_arg("prior_form_id")
    if prior_form_id is not None:
        forms = [f for f in forms if f["prior_form_id"] == prior_form_id]
    return paginate(forms, limit, offset, domain.tax_form_json)


def request_channel_id():
    return request_arg("channel_id")


def request_arg(name):
    return request.args.get(name)


@bp.post("/api/tax-forms/<tax_form_id>/transition")
def transition_tax_form(tax_form_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("VERIFY", "REJECT"))
    rejection_reason = opt_str(b, "rejection_reason")
    if action == "REJECT" and not rejection_reason:
        raise err_invalid_request("Field 'rejection_reason' is required for REJECT")
    require_role(role, ("TrustAgent",))
    form = db.store.tax_forms.get(tax_form_id)
    if form is None:
        raise err_not_found("Tax form not found")
    if form["tax_status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED tax form can be verified or rejected")
    ch = domain.get_channel(form["channel_id"])
    old_posture = domain.monetization_posture(ch)
    if action == "VERIFY":
        form["tax_status"] = "VERIFIED"
        form["verified_at"] = db.now()
        form["expires_on"] = db.now() + timedelta(days=365)
        db.touch(form)
        domain.posture_cascade(ch, old_posture, cause="TAX_FORM")
        # Release TAX_FORM holds provided the posture is not SUSPENDED.
        if domain.monetization_posture(ch) != "SUSPENDED":
            domain.release_held_payouts(ch["id"], "TAX_FORM")
    else:  # REJECT
        form["tax_status"] = "REJECTED"
        form["rejection_reason"] = rejection_reason
        db.touch(form)
        # A rejected current form fires the hold cascade (PRD §3.3).
        domain.posture_cascade(ch, old_posture, cause="TAX_FORM")
    return ok_obj(domain.tax_form_json(form))
