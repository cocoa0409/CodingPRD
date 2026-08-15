"""Estates: open, probate lifecycle, alternate valuation election,
distribution waterfall (PRD 3.7)."""
from flask import Blueprint, g

import store
from calc import div_rhu
from domain import estate_view, lookup, matches, paginate, sort_created, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, iso, now, touch
from validate import get_body, validate_body

bp = Blueprint("estates", __name__)

ACTIONS = (
    "OPEN_PROBATE",
    "CONTEST",
    "RESOLVE_CONTEST",
    "ELECT_ALTERNATE_VALUATION",
    "BEGIN_DISTRIBUTION",
    "MARK_DISTRIBUTED",
    "CLOSE",
)


@bp.post("/giving/estates")
@require_roles("EstateManager")
def create_estate():
    body = get_body()
    validate_body(
        body,
        {
            "donor_id": ("str", True, None),
            "notified_on": ("datetime", True, None),
            "gift_agreement_id": ("str", False, None),
        },
    )
    donor = lookup(store.donors, body["donor_id"], "Donor")
    if body.get("gift_agreement_id") is not None:
        lookup(store.agreements, body["gift_agreement_id"], "GiftAgreement")
    if donor["vital_status"] != "DECEASED":
        raise ApiError(
            "ERR_DONOR_STATE_MISMATCH",
            409,
            "An estate may only be opened for a DECEASED donor",
        )
    estate = base_fields()
    estate.update(
        {
            "donor_id": donor["id"],
            "gift_agreement_id": body.get("gift_agreement_id"),
            "status": "NOTIFIED",
            "notified_on": body["notified_on"],
            "recorded_by_user_id": g.user_id,
            "alternate_valuation_elected": False,
            "administration_costs_cents": 0,
            "specific_bequests_cents": 0,
            "residual_to_university_cents": None,
            "distributed_on": None,
        }
    )
    store.estates[estate["id"]] = estate
    return success(estate_view(estate), 201)


@bp.get("/giving/estates")
@require_roles(*ALL_ROLES)
def list_estates():
    items = [
        e
        for e in sort_created(store.estates.values())
        if matches(e, {"donor_id": None, "gift_agreement_id": None, "status": None})
    ]
    page, meta = paginate(items)
    return success([estate_view(e) for e in page], 200, meta)


@bp.get("/giving/estates/<estate_id>")
@require_roles(*ALL_ROLES)
def get_estate(estate_id):
    return success(estate_view(lookup(store.estates, estate_id, "Estate")), 200)


@bp.post("/giving/estates/<estate_id>/transition")
@require_roles("EstateManager")
def estate_transition(estate_id):
    estate = lookup(store.estates, estate_id, "Estate")
    body = get_body()
    validate_body(
        body,
        {
            "action": ("str", True, ACTIONS),
            "administration_costs_cents": ("int", False, None),
            "specific_bequests_cents": ("int", False, None),
        },
    )
    action = body["action"]
    status = estate["status"]

    if action == "OPEN_PROBATE":
        if status != "NOTIFIED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot OPEN_PROBATE from %s" % status
            )
        estate["status"] = "PROBATE_OPEN"

    elif action == "CONTEST":
        if status != "PROBATE_OPEN":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot CONTEST from %s" % status
            )
        estate["status"] = "CONTESTED"

    elif action == "RESOLVE_CONTEST":
        if status != "CONTESTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot RESOLVE_CONTEST from %s" % status
            )
        estate["status"] = "PROBATE_OPEN"

    elif action == "ELECT_ALTERNATE_VALUATION":
        if status not in ("NOTIFIED", "PROBATE_OPEN"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot elect alternate valuation from %s" % status,
            )
        if estate["alternate_valuation_elected"]:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Alternate valuation is a one-way election",
            )
        estate["alternate_valuation_elected"] = True
        # flip the basis of every linked SECURITIES asset not still PLEDGED;
        # assets missing the alt pair keep the DOD basis
        for asset in store.assets.values():
            if (
                asset.get("estate_id") == estate["id"]
                and asset["asset_kind"] == "SECURITIES"
                and asset["status"] != "PLEDGED"
                and asset.get("alt_high_price_cents") is not None
                and asset.get("alt_low_price_cents") is not None
            ):
                new_fmv = div_rhu(
                    asset["alt_high_price_cents"] + asset["alt_low_price_cents"], 2
                )
                if new_fmv != asset.get("fmv_cents"):
                    asset["fmv_cents"] = new_fmv
                    touch(asset)

    elif action == "BEGIN_DISTRIBUTION":
        # SoD (priority 3): actor differs from the estate recorder
        if g.user_id == estate["recorded_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "Distribution must be begun by a different EstateManager",
            )
        if status != "PROBATE_OPEN":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot BEGIN_DISTRIBUTION from %s" % status,
            )
        # milestone gate (22) is always evaluated before the asset gate (23)
        open_milestones = any(
            m["estate_id"] == estate["id"] and m["status"] != "CLOSED"
            for m in store.milestones.values()
        )
        if open_milestones:
            raise ApiError(
                "ERR_MILESTONES_OPEN",
                409,
                "All probate milestones must be CLOSED",
            )
        unliquidated = any(
            a.get("estate_id") == estate["id"]
            and a["status"] not in ("LIQUIDATED", "DISTRIBUTED", "RETURNED")
            for a in store.assets.values()
        )
        if unliquidated:
            raise ApiError(
                "ERR_ASSETS_NOT_LIQUIDATED",
                409,
                "All estate assets must be LIQUIDATED, DISTRIBUTED or RETURNED",
            )
        admin = body.get("administration_costs_cents", 0)
        bequests = body.get("specific_bequests_cents", 0)
        gross = estate_view(estate)["gross_proceeds_cents"]
        residual = gross - admin - bequests
        if residual < 0:
            raise ApiError(
                "ERR_DISTRIBUTION_OVERFLOW",
                422,
                "Costs plus specific bequests exceed gross proceeds",
            )
        estate["administration_costs_cents"] = admin
        estate["specific_bequests_cents"] = bequests
        estate["residual_to_university_cents"] = residual
        estate["status"] = "DISTRIBUTION_PENDING"
        # residual cascades to the bequest agreement's fund, if named
        agreement = store.agreements.get(estate.get("gift_agreement_id") or "")
        if agreement is not None and agreement.get("fund_id"):
            fund = store.funds.get(agreement["fund_id"])
            if fund is not None:
                fund["balance_cents"] += residual
                if (
                    fund["status"] == "PROPOSED"
                    and fund["balance_cents"] >= fund["minimum_endowment_cents"]
                ):
                    fund["status"] = "ENDOWED"
                touch(fund)

    elif action == "MARK_DISTRIBUTED":
        if status != "DISTRIBUTION_PENDING":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot MARK_DISTRIBUTED from %s" % status,
            )
        estate["distributed_on"] = iso(now())
        estate["status"] = "DISTRIBUTED"

    else:  # CLOSE
        if status != "DISTRIBUTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot CLOSE from %s" % status)
        # closing an estate does NOT settle the linked agreement (PRD 3.7)
        estate["status"] = "CLOSED"

    touch(estate)
    return success(estate_view(estate), 200)
