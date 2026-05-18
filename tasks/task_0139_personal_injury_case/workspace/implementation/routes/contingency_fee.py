"""ContingencyFeeAgreement endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

from config import ROLE_ATTORNEY, ROLE_MANAGING_PARTNER, ROLE_PARALEGAL
from db import store
from errors import raise_error
from middleware import require_auth
from response import success
from routes._helpers import get_json_body
from services.case_engine import assert_case_not_closed, get_case_or_404, now
from services.serializers import fee_agreement_to_dict
from utils import new_uuid


bp = Blueprint("contingency_fee", __name__)


def _validate_rate(name, value, default):
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise_error("ERR_VALIDATION", f"{name} must be an integer.")
    if value <= 0 or value > 5000:
        raise_error("ERR_VALIDATION", f"{name} must satisfy 0 < value <= 5000.")
    return value


@bp.post("/pi-cases/<cid>/contingency-fee")
@require_auth([ROLE_ATTORNEY, ROLE_MANAGING_PARTNER])
def create_fee_agreement(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    pre_suit = _validate_rate("pre_suit_rate_bps", body.get("pre_suit_rate_bps"), 3333)
    post_suit = _validate_rate("post_suit_rate_bps", body.get("post_suit_rate_bps"), 4000)
    trial = _validate_rate("trial_rate_bps", body.get("trial_rate_bps"), 4500)

    with store.lock:
        if cid in store.fee_agreement_by_case:
            raise_error(
                "ERR_FEE_AGREEMENT_ALREADY_EXISTS",
                "A contingency-fee agreement already exists for this case.",
            )
        ts = now()
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "pre_suit_rate_bps": pre_suit,
            "post_suit_rate_bps": post_suit,
            "trial_rate_bps": trial,
            "signed_at": ts,
            "created_at": ts,
        }
        store.fee_agreements[row["id"]] = row
        store.fee_agreement_by_case[cid] = row["id"]

    return success(fee_agreement_to_dict(row), 201)


@bp.get("/pi-cases/<cid>/contingency-fee")
@require_auth([ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER])
def fetch_fee_agreement(cid):
    get_case_or_404(cid)
    fee_id = store.fee_agreement_by_case.get(cid)
    if not fee_id:
        raise_error("ERR_NOT_FOUND", "ContingencyFeeAgreement not found.")
    return success(fee_agreement_to_dict(store.fee_agreements[fee_id]), 200)
