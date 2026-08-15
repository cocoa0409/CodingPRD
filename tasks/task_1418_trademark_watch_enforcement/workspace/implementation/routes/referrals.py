"""CounterfeitReferral endpoints (PRD 3.7)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_CUSTOMS_RECORDATION_REQUIRED,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import ser_counterfeit_referral
from util import get_payload, reject_unknown_fields, touch
from routes.common import do_list, bool_param

bp = Blueprint("counterfeit_referrals", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")


def _get_referral(referral_id):
    referral = db.counterfeit_referrals.get(referral_id)
    if referral is None:
        raise_error(ERR_NOT_FOUND, "CounterfeitReferral not found")
    return referral


@bp.route("/brand/counterfeit-referrals", methods=["GET"])
def list_referrals():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.counterfeit_referrals.values(), ser_counterfeit_referral,
                   [("watch_alert_id", "watch_alert_id", None),
                    ("enforcement_matter_id", "enforcement_matter_id", None),
                    ("status", "status", None),
                    ("auto_created", "auto_created", bool_param)],
                   user_id, role, "counterfeit_referral")


@bp.route("/brand/counterfeit-referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    user_id, role = require_roles(*READ_ROLES)
    referral = _get_referral(referral_id)
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("counterfeit_referral", referral))
    return success(ser_counterfeit_referral(referral), 200)


@bp.route("/brand/counterfeit-referrals/<referral_id>/refer", methods=["POST"])
def refer_referral(referral_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    referral = _get_referral(referral_id)
    if referral["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "refer is declared only from DRAFT")
    if referral["referral_channel"] == "CUSTOMS_SEIZE":
        # CUSTOMS_SEIZE requires an ACTIVE CustomsRecordation on the alert's record.
        alert = db.watch_alerts.get(referral["watch_alert_id"])
        record_id = alert["trademark_record_id"] if alert else None
        has_active = any(
            c["trademark_record_id"] == record_id and c["status"] == "ACTIVE"
            for c in db.customs_recordations.values()
        )
        if not has_active:
            raise_error(ERR_CUSTOMS_RECORDATION_REQUIRED,
                        "CUSTOMS_SEIZE requires an ACTIVE CustomsRecordation on the record")
    referral["status"] = "REFERRED"
    touch(referral)
    return success(ser_counterfeit_referral(referral), 200)


@bp.route("/brand/counterfeit-referrals/<referral_id>/acknowledge", methods=["POST"])
def acknowledge_referral(referral_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    referral = _get_referral(referral_id)
    if referral["status"] != "REFERRED":
        raise_error(ERR_INVALID_STATE, "acknowledge is declared only from REFERRED")
    referral["status"] = "ACKNOWLEDGED"
    touch(referral)
    return success(ser_counterfeit_referral(referral), 200)
