"""NotaryReferral routes."""

from flask import Blueprint, request

import constants
import errors
import validators
from common import base_entity, get_or_404, list_collection, serialize
from db import store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("notary_referrals", __name__)


@bp.route("/legal/notary-referrals", methods=["POST"])
@roles("Customer")
def create_notary_referral():
    body = get_json_body()
    sr_id = validators.require_string(body, "signature_request_id")
    state = validators.require_enum(body, "referral_state_code", constants.STATE_CODES)

    # Existence (404).
    sr = store.signature_requests.get(sr_id)
    if sr is None:
        raise errors.not_found("signature_request_id does not exist")

    # Notary must be required on the envelope (409).
    if sr["notary_required"] is not True:
        raise errors.ApiError(errors.ERR_NOTARY_NOT_REQUIRED, 409,
                              "Envelope does not require notarization")

    ent = base_entity()
    ent.update({
        "signature_request_id": sr_id,
        "referral_state_code": state,
        "status": "REFERRED",
    })
    store.notary_referrals[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/notary-referrals/<nid>", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def get_notary_referral(nid):
    ent = get_or_404(store.notary_referrals, nid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/notary-referrals", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def list_notary_referrals():
    limit, offset = parse_pagination()
    sr_id = request.args.get("signature_request_id")

    def predicate(e):
        if sr_id is not None and e["signature_request_id"] != sr_id:
            return False
        return True

    page, total = list_collection(store.notary_referrals, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
