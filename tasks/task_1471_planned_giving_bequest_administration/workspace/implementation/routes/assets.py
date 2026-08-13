"""Gift assets: pledge, receive, appraise, liquidate, return, distribute (PRD 3.5)."""
from flask import Blueprint

import store
from calc import div_rhu
from domain import (
    ASSET_KINDS,
    lookup,
    matches,
    paginate,
    reevaluate_funding,
    sort_created,
    update_reserve,
    view,
)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import get_body, validate_body

bp = Blueprint("assets", __name__)

ACTIONS = ("RECEIVE", "APPRAISE", "LIQUIDATE", "RETURN", "DISTRIBUTE")


def _fmv_for(asset, estate):
    """Securities FMV: round_half_up((high+low)/2) over the selected basis pair.
    Agreement-linked assets always use the DOD pair; estate-linked assets use
    the ALT pair only when the estate elected alternate valuation AND the alt
    pair is present."""
    use_alt = (
        estate is not None
        and estate.get("alternate_valuation_elected")
        and asset.get("alt_high_price_cents") is not None
        and asset.get("alt_low_price_cents") is not None
    )
    if use_alt:
        return div_rhu(asset["alt_high_price_cents"] + asset["alt_low_price_cents"], 2)
    if asset.get("dod_high_price_cents") is None:
        return None
    return div_rhu(asset["dod_high_price_cents"] + asset["dod_low_price_cents"], 2)


@bp.post("/giving/gift-assets")
@require_roles("EstateManager")
def create_asset():
    body = get_body()
    validate_body(
        body,
        {
            "asset_kind": ("str", True, ASSET_KINDS),
            "pledged_value_cents": ("int", True, None),
            "gift_agreement_id": ("str", False, None),
            "estate_id": ("str", False, None),
            "description": ("str", False, None),
        },
    )
    # existence of supplied FKs first (left to right), then parentage
    agreement = None
    estate = None
    if body.get("gift_agreement_id") is not None:
        agreement = lookup(store.agreements, body["gift_agreement_id"], "GiftAgreement")
    if body.get("estate_id") is not None:
        estate = lookup(store.estates, body["estate_id"], "Estate")
    if (agreement is None) == (estate is None):
        raise ApiError(
            "ERR_ASSET_ORPHAN",
            422,
            "Exactly one of gift_agreement_id / estate_id is required",
        )

    asset = base_fields()
    asset.update(
        {
            "gift_agreement_id": agreement["id"] if agreement else None,
            "estate_id": estate["id"] if estate else None,
            "asset_kind": body["asset_kind"],
            "description": body.get("description"),
            "pledged_value_cents": body["pledged_value_cents"],
            "status": "PLEDGED",
            "dod_high_price_cents": None,
            "dod_low_price_cents": None,
            "alt_high_price_cents": None,
            "alt_low_price_cents": None,
            "fmv_cents": None,
            "appraised_value_cents": None,
            "gross_proceeds_cents": None,
            "liquidation_costs_cents": 0,
            "net_proceeds_cents": None,
        }
    )
    store.assets[asset["id"]] = asset
    return success(view(asset), 201)


@bp.get("/giving/gift-assets")
@require_roles(*ALL_ROLES)
def list_assets():
    items = [
        a
        for a in sort_created(store.assets.values())
        if matches(
            a,
            {
                "gift_agreement_id": None,
                "estate_id": None,
                "asset_kind": None,
                "status": None,
            },
        )
    ]
    page, meta = paginate(items)
    return success([view(a) for a in page], 200, meta)


@bp.get("/giving/gift-assets/<asset_id>")
@require_roles(*ALL_ROLES)
def get_asset(asset_id):
    return success(view(lookup(store.assets, asset_id, "GiftAsset")), 200)


@bp.post("/giving/gift-assets/<asset_id>/transition")
@require_roles("EstateManager")
def asset_transition(asset_id):
    asset = lookup(store.assets, asset_id, "GiftAsset")
    body = get_body()
    validate_body(
        body,
        {
            "action": ("str", True, ACTIONS),
            "dod_high_price_cents": ("int", False, None),
            "dod_low_price_cents": ("int", False, None),
            "alt_high_price_cents": ("int", False, None),
            "alt_low_price_cents": ("int", False, None),
            "appraised_value_cents": ("int", False, None),
            "gross_proceeds_cents": ("int", False, None),
            "liquidation_costs_cents": ("int", False, None),
        },
    )
    action = body["action"]
    status = asset["status"]

    if action == "RECEIVE":
        if status != "PLEDGED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot RECEIVE from %s" % status)
        if asset["asset_kind"] == "SECURITIES":
            if (
                body.get("dod_high_price_cents") is None
                or body.get("dod_low_price_cents") is None
            ):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "SECURITIES receipt requires dod_high_price_cents and dod_low_price_cents",
                )
            asset["dod_high_price_cents"] = body["dod_high_price_cents"]
            asset["dod_low_price_cents"] = body["dod_low_price_cents"]
            asset["alt_high_price_cents"] = body.get("alt_high_price_cents")
            asset["alt_low_price_cents"] = body.get("alt_low_price_cents")
            estate = store.estates.get(asset.get("estate_id") or "")
            asset["fmv_cents"] = _fmv_for(asset, estate)
        asset["status"] = "RECEIVED"
        touch(asset)
        # recompute received value + evaluate EXECUTED -> FUNDED (inclusive >=)
        if asset.get("gift_agreement_id"):
            agreement = store.agreements.get(asset["gift_agreement_id"])
            if agreement is not None:
                reevaluate_funding(agreement)

    elif action == "APPRAISE":
        if status != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot APPRAISE from %s" % status)
        if asset["asset_kind"] != "REAL_ESTATE":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Appraisal exists only for real estate"
            )
        if body.get("appraised_value_cents") is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "appraised_value_cents is required"
            )
        asset["appraised_value_cents"] = body["appraised_value_cents"]
        asset["status"] = "APPRAISED"
        touch(asset)
        if asset.get("gift_agreement_id"):
            agreement = store.agreements.get(asset["gift_agreement_id"])
            if agreement is not None:
                reevaluate_funding(agreement)

    elif action == "LIQUIDATE":
        if status not in ("RECEIVED", "APPRAISED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot LIQUIDATE from %s" % status
            )
        if asset["asset_kind"] == "REAL_ESTATE" and status != "APPRAISED":
            raise ApiError(
                "ERR_ASSET_KIND_REQUIRES_APPRAISAL",
                409,
                "REAL_ESTATE must be APPRAISED before liquidation",
            )
        if body.get("gross_proceeds_cents") is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "gross_proceeds_cents is required"
            )
        costs = body.get("liquidation_costs_cents", 0)
        asset["gross_proceeds_cents"] = body["gross_proceeds_cents"]
        asset["liquidation_costs_cents"] = costs
        # per-asset rounding step: net proceeds computed per asset at LIQUIDATE
        asset["net_proceeds_cents"] = body["gross_proceeds_cents"] - costs
        asset["status"] = "LIQUIDATED"
        touch(asset)
        # CGA-linked liquidation credits the reserve; coverage/posture recompute
        if asset.get("gift_agreement_id"):
            agreement = store.agreements.get(asset["gift_agreement_id"])
            if agreement is not None and agreement["vehicle_type"] == "CGA":
                update_reserve(
                    new_balance=store.reserve_fund["balance_cents"]
                    + asset["net_proceeds_cents"]
                )

    elif action == "RETURN":
        if status != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot RETURN from %s" % status)
        if asset.get("gift_agreement_id"):
            agreement = store.agreements.get(asset["gift_agreement_id"])
            if agreement is None or agreement["status"] not in ("EXECUTED", "RESCINDED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "Assets of a funded/active agreement cannot be returned",
                )
        asset["status"] = "RETURNED"
        touch(asset)

    else:  # DISTRIBUTE
        if status != "LIQUIDATED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot DISTRIBUTE from %s" % status
            )
        if asset.get("estate_id"):
            estate = store.estates.get(asset["estate_id"])
            if estate is None or estate["status"] not in (
                "DISTRIBUTION_PENDING",
                "DISTRIBUTED",
            ):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "Estate is not in distribution",
                )
        asset["status"] = "DISTRIBUTED"
        touch(asset)

    return success(view(asset), 200)
