"""Asset findings: recording, verification and the custody split (PRD 3.3)."""

from flask import request

from auth import ALL_STAFF
from domain import (
    by_seq,
    debtor_of_judgment,
    get_finding,
    get_judgment,
    guard_judgment_alive,
    invalid_state,
    refresh_preliminary,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_ASSET_TYPE,
    ENUM_FINDING_SOURCE,
    check_enum,
    json_body,
    non_negative,
    pagination,
    present,
    require_int,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, serialize

READ_ROLES = ALL_STAFF


def register(app):
    # ---- POST /asset-findings --------------------------------------------
    @endpoint(app, "/asset-findings", "POST", ("AssetInvestigator",), 201)
    def create_finding(ctx):
        body = json_body()
        judgment = get_judgment(body.get("judgment_id")) if present(body, "judgment_id") else None
        judgment_id = require_string(body, "judgment_id")
        asset_type_raw = require_string(body, "asset_type")
        require_string(body, "institution_name")
        require_string(body, "identifier_last4")
        estimated_value = require_int(body, "estimated_value_cents")
        require_string(body, "source")
        earnings = None
        if asset_type_raw in ENUM_ASSET_TYPE:
            if asset_type_raw == "EMPLOYMENT":
                earnings = require_int(body, "weekly_disposable_earnings_cents")
            elif present(body, "weekly_disposable_earnings_cents"):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "weekly_disposable_earnings_cents may only be supplied for EMPLOYMENT findings.")
        asset_type = check_enum(body, "asset_type", ENUM_ASSET_TYPE)
        source = check_enum(body, "source", ENUM_FINDING_SOURCE)
        non_negative(estimated_value, "estimated_value_cents")
        non_negative(earnings, "weekly_disposable_earnings_cents")
        guard_judgment_alive(judgment)

        row = new_row({
            "judgment_id": judgment_id,
            "asset_type": asset_type,
            "institution_name": body["institution_name"],
            "identifier_last4": body["identifier_last4"],
            "estimated_value_cents": estimated_value,
            "available_cents": estimated_value,
            "frozen_cents": 0,
            "swept_cents": 0,
            "source": source,
            "status": "OPEN",
            "verified_by_user_id": None,
            "verified_on": None,
            "weekly_disposable_earnings_cents": earnings,
        })
        store.asset_findings[row["id"]] = row

        debtor = debtor_of_judgment(judgment)
        if debtor is not None:
            if asset_type == "EMPLOYMENT":
                debtor["weekly_disposable_earnings_cents"] = earnings
            refresh_preliminary(debtor)
            bump(debtor)
        return serialize(row)

    # ---- GET /asset-findings ---------------------------------------------
    @endpoint(app, "/asset-findings", "GET", READ_ROLES, 200)
    def list_findings(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.asset_findings.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "asset_type")
        rows = apply_filter(rows, request.args, "status")
        rows = apply_filter(rows, request.args, "source")
        return make_list(rows, limit, offset, serialize)

    # ---- GET /asset-findings/{asset_finding_id} --------------------------
    @endpoint(app, "/asset-findings/<asset_finding_id>", "GET", READ_ROLES, 200)
    def read_finding(ctx, asset_finding_id):
        return serialize(get_finding(asset_finding_id))

    # ---- POST /asset-findings/{asset_finding_id}/verify ------------------
    @endpoint(app, "/asset-findings/<asset_finding_id>/verify", "POST", ("AssetInvestigator",), 200)
    def verify_finding(ctx, asset_finding_id):
        finding = get_finding(asset_finding_id)
        if finding["status"] not in ("OPEN", "STALE"):
            invalid_state("Only an OPEN or STALE finding may be verified.")
        judgment = store.judgments.get(finding["judgment_id"])
        guard_judgment_alive(judgment)
        finding["status"] = "VERIFIED"
        finding["verified_by_user_id"] = ctx.user_id
        finding["verified_on"] = store.clock_date().isoformat()
        bump(finding)
        debtor = debtor_of_judgment(judgment)
        if debtor is not None:
            refresh_preliminary(debtor)
            bump(debtor)
        return serialize(finding)
