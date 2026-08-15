"""Deal endpoints."""
from flask import request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import (
    deal_assumptions,
    deal_memos,
    deal_properties,
    supersede_all_computed_scenarios,
    supersede_other_computed_scenarios,
    recompute_final_noi_if_pinned,
)
from util import (
    deal_view,
    get_deal,
    init_common_fields,
    json_body,
    paginate,
    parse_enum_field,
    parse_int_field,
    parse_pagination,
    parse_str_field,
    touch,
)

STRATEGIES = ["CORE", "CORE_PLUS", "VALUE_ADD", "OPPORTUNISTIC"]


def register(app):
    @app.post("/re-underwriting/deals")
    def create_deal():
        user_id, _role = auth(allowed=["Analyst"])
        body = json_body()
        deal_code = parse_str_field(body, "deal_code")
        if not (4 <= len(deal_code) <= 32):
            raise ApiError("ERR_INVALID_REQUEST", 400, "deal_code must be 4-32 chars")
        deal_name = parse_str_field(body, "deal_name")
        strategy = parse_enum_field(body, "strategy", STRATEGIES)
        target = parse_int_field(body, "target_purchase_price_cents")

        # uniqueness on deal_code
        for d in DB["deals"].values():
            if d["deal_code"] == deal_code:
                raise ApiError(
                    "ERR_DUPLICATE_DEAL_CODE", 409, "deal_code already in use"
                )

        rec = {
            "id": new_id(),
            "deal_code": deal_code,
            "deal_name": deal_name,
            "strategy": strategy,
            "status": "DRAFT",
            "target_purchase_price_cents": target,
            "analyst_id": user_id,
            "asset_manager_id": None,
            "current_scenario_id": None,
            "approved_at": None,
            "rejected_reason": None,
        }
        init_common_fields(rec)
        DB["deals"][rec["id"]] = rec
        return ok(deal_view(rec), status=201)

    @app.get("/re-underwriting/deals")
    def list_deals():
        auth(allowed=READ_ROLES)
        limit, offset = parse_pagination()
        status = request.args.get("status")
        analyst_id = request.args.get("analyst_id")
        asset_manager_id = request.args.get("asset_manager_id")
        current_scenario_id = request.args.get("current_scenario_id")

        items = list(DB["deals"].values())
        if status is not None:
            items = [d for d in items if d["status"] == status]
        if analyst_id is not None:
            items = [d for d in items if d["analyst_id"] == analyst_id]
        if asset_manager_id is not None:
            items = [d for d in items if d["asset_manager_id"] == asset_manager_id]
        if current_scenario_id is not None:
            items = [d for d in items if d["current_scenario_id"] == current_scenario_id]
        items.sort(key=lambda d: d["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([deal_view(d) for d in page], total, limit, offset)

    @app.get("/re-underwriting/deals/<deal_id>")
    def get_deal_route(deal_id):
        auth(allowed=READ_ROLES)
        d = get_deal(deal_id)
        return ok(deal_view(d))

    @app.post("/re-underwriting/deals/<deal_id>/submit-underwriting")
    def submit_underwriting(deal_id):
        user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        if d["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Deal is not in DRAFT status")
        if d["analyst_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Caller is not the deal's analyst")
        # business preconditions: at least one property + active assumption
        if not deal_properties(deal_id):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Deal must have at least one property"
            )
        if not any(m["is_active"] for m in deal_assumptions(deal_id)):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Deal must have an active MarketAssumption",
            )
        am_id = request.headers.get("X-AssetManager-ID")
        d["asset_manager_id"] = am_id
        d["status"] = "UNDERWRITING"
        touch(d)
        return ok(deal_view(d))

    @app.post("/re-underwriting/deals/<deal_id>/submit-ic")
    def submit_ic(deal_id):
        user_id, _role = auth(allowed=["AssetManager"])
        d = get_deal(deal_id)
        if d["status"] != "UNDERWRITING":
            raise ApiError("ERR_INVALID_STATE", 409, "Deal is not in UNDERWRITING status")
        if d["asset_manager_id"] != user_id:
            raise ApiError(
                "ERR_FORBIDDEN", 403, "Caller is not the deal's asset manager"
            )
        # require a SUBMITTED memo
        submitted = [m for m in deal_memos(deal_id) if m["status"] == "SUBMITTED"]
        if not submitted:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "No ICMemo in SUBMITTED status exists for this deal",
            )
        submitted.sort(key=lambda m: m["created_at"])
        memo = submitted[-1]
        scenario = DB["scenarios"].get(memo["scenario_id"])
        if scenario is None or scenario["status"] != "COMPUTED":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Memo's scenario is not in COMPUTED status",
            )

        # Pin scenario
        d["current_scenario_id"] = memo["scenario_id"]
        # Cascade other COMPUTED scenarios to SUPERSEDED with superseded_by_id = pinned id
        supersede_other_computed_scenarios(deal_id, memo["scenario_id"], memo["scenario_id"])
        # Memo transitions SUBMITTED -> UNDER_VOTE
        memo["status"] = "UNDER_VOTE"
        touch(memo)
        # Deal status
        d["status"] = "IC_REVIEW"
        touch(d)
        # Recompute scenario NOI with FINAL variant (pinned)
        recompute_final_noi_if_pinned(scenario)
        return ok(deal_view(d))

    @app.post("/re-underwriting/deals/<deal_id>/reopen")
    def reopen(deal_id):
        user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        if d["status"] not in ("UNDERWRITING", "REJECTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Deal can only be reopened from UNDERWRITING or REJECTED",
            )
        if d["analyst_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Caller is not the deal's analyst")

        if d["status"] == "UNDERWRITING":
            # require no ICMemo in SUBMITTED or UNDER_VOTE
            for m in deal_memos(deal_id):
                if m["status"] in ("SUBMITTED", "UNDER_VOTE"):
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        409,
                        "An ICMemo in SUBMITTED or UNDER_VOTE status blocks reopen",
                    )
            d["status"] = "DRAFT"
        else:  # REJECTED
            d["status"] = "UNDERWRITING"
            d["current_scenario_id"] = None

        # Cascade: all COMPUTED scenarios -> SUPERSEDED with superseded_by_id null
        supersede_all_computed_scenarios(deal_id)
        touch(d)
        return ok(deal_view(d))

    @app.post("/re-underwriting/deals/<deal_id>/mark-dead")
    def mark_dead(deal_id):
        user_id, _role = auth(allowed=["AssetManager"])
        d = get_deal(deal_id)
        if d["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Deal is not in REJECTED status")
        if d["asset_manager_id"] != user_id:
            raise ApiError(
                "ERR_FORBIDDEN", 403, "Caller is not the deal's asset manager"
            )
        d["status"] = "DEAD"
        touch(d)
        return ok(deal_view(d))
