"""WageStatement endpoints (PRD §3.5). Append-only; OCC-guarded on claim version."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_STALE_CLAIM_VERSION
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_int
from services import calculations as calc
from routes._common import get_claim

bp = Blueprint("wage_statements", __name__)


@bp.post("/wage-statements")
def create_wage_statement():
    require_auth(["ClaimsAdjuster"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    claim = get_claim(claim_id)

    aww = require_int(body, "average_weekly_wage_cents", minimum=0)
    expected_version = require_int(body, "expected_claim_version")

    # OCC guard on the claim version (PRD §2.8).
    if expected_version != claim["version"]:
        raise APIError(ERR_STALE_CLAIM_VERSION, 412,
                       "expected_claim_version does not match the claim's version")

    rate = calc.ttd_weekly_rate(aww)
    ws = {
        "claim_id": claim_id,
        "average_weekly_wage_cents": aww,
        "ttd_weekly_rate_cents": rate,
    }
    db.stamp_immutable(ws)  # append-only: only id + created_at
    db.wage_statements[ws["id"]] = ws

    db.bump(claim)  # filing a wage statement increments the claim version
    return ok_object(ws, 201)


@bp.get("/claims/<rid>/wage-statements")
def list_claim_wage_statements(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [w for w in db.wage_statements.values() if w["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
