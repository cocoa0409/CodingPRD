"""Serialized assets: firmware, usage, trade-in, refurbishment and resale (PRD 3.7, 3.9)."""

from flask import Blueprint

import calc
from auth import (
    asset_servicing_partners,
    check_partner_scope,
    get_asset,
    get_facility,
    get_release,
    require,
)
from constants import ANY_ROLE, ASSET_STATUSES, CONNECTIVITY_STATUSES, GRADES
from envelope import ok, ok_list
from errors import ApiError
from store import mutate, store
from validation import (
    field_decimal,
    field_enum,
    field_id,
    field_str,
    get_body,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("assets", __name__)


def _console_support_live(asset):
    """Ladder rung 19."""
    model = calc.model_of_asset(asset)
    if not model["connected"]:
        return
    horizon = calc.dt(asset["firmware_support_expires_at"])
    if horizon is not None and horizon <= store.now():
        raise ApiError(
            "ERR_FIRMWARE_SUPPORT_EXPIRED",
            "The console's firmware support commitment has lapsed.",
        )


@bp.get("/serialized-assets")
@require(*ANY_ROLE)
def list_serialized_assets():
    limit, offset = paging()
    facility_id = query_str("facility_id")
    model_revision_id = query_str("model_revision_id")
    order_line_id = query_str("order_line_id")
    installed_firmware_release_id = query_str("installed_firmware_release_id")
    status = query_enum("status", ASSET_STATUSES)
    connectivity_support_status = query_enum(
        "connectivity_support_status", CONNECTIVITY_STATUSES
    )

    rows = list(store.serialized_assets.values())
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if model_revision_id is not None:
        rows = [r for r in rows if r["model_revision_id"] == model_revision_id]
    if order_line_id is not None:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if installed_firmware_release_id is not None:
        rows = [
            r
            for r in rows
            if r["installed_firmware_release_id"] == installed_firmware_release_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if connectivity_support_status is not None:
        rows = [
            r
            for r in rows
            if r["connectivity_support_status"] == connectivity_support_status
        ]
    # documented ordering exception: created_at ASC then sequence_no ASC
    page, total = paginate(
        rows, limit, offset, sort_key=lambda row: (row["created_at"], row["sequence_no"])
    )
    return ok_list(page, limit, offset, total)


@bp.get("/serialized-assets/<asset_id>")
@require(*ANY_ROLE)
def read_serialized_asset(asset_id):
    asset = get_asset(asset_id)
    check_partner_scope(asset_servicing_partners(asset))
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/load-firmware")
@require("ProductEngineer", "ServicePartnerTech")
def load_firmware(asset_id):
    asset = get_asset(asset_id)
    check_partner_scope(asset_servicing_partners(asset))
    body = get_body()
    firmware_release_id = field_id(body, "firmware_release_id")

    # rung 9
    release = get_release(firmware_release_id)

    revision = calc.revision_of_asset(asset)
    model = calc.model_of_revision(revision)

    # rung 14 — a certified, non-withdrawn pairing for this build and revision
    if model["connected"]:
        certified = False
        for cert in calc.revision_certifications(revision["id"]):
            if (
                cert["firmware_release_id"] == release["id"]
                and cert["cert_status"] == "CERTIFIED"
            ):
                certified = True
                break
        if not certified or release["status"] == "WITHDRAWN":
            raise ApiError(
                "ERR_FIRMWARE_NOT_CERTIFIED",
                "No certified, non-withdrawn build pairing exists for this asset.",
            )

    # rung 22 — console platform compatibility
    if not model["connected"] or release["console_platform"] != model["console_platform"]:
        raise ApiError(
            "ERR_PLATFORM_INCOMPATIBLE",
            "The build's console platform does not match a connected model.",
        )

    with mutate(asset):
        asset["installed_firmware_release_id"] = release["id"]
    calc.recompute_asset_support(asset)
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/usage-report")
@require("ServicePartnerTech")
def usage_report(asset_id):
    asset = get_asset(asset_id)
    check_partner_scope(asset_servicing_partners(asset))
    body = get_body()
    annual_usage_hours = field_decimal(body, "annual_usage_hours", minimum=0)

    with mutate(asset):
        asset["annual_usage_hours"] = annual_usage_hours
    calc.recompute_facility_programs(asset["facility_id"], ("ACTIVE",))
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/trade-in")
@require("OrderPlanner")
def trade_in(asset_id):
    asset = get_asset(asset_id)
    body = get_body()
    grade = field_enum(body, "declared_condition_grade", GRADES)

    if asset["status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an IN_SERVICE asset may be traded in."
        )

    valuation = calc.trade_in_valuation(asset, grade)
    with mutate(asset):
        asset["status"] = "TRADE_IN_RETURNED"
        asset["declared_condition_grade"] = grade
        asset["trade_in_valuation_cents"] = valuation

    # scheduled visits for this asset release their spare units
    partners = set()
    for visit in sorted(
        calc.asset_visits(asset["id"]), key=lambda row: (row["created_at"], row["id"])
    ):
        if visit["status"] != "SCHEDULED":
            continue
        with mutate(visit):
            visit["status"] = "CANCELLED"
        program = store.pm_programs.get(visit["pm_program_id"])
        if program is not None:
            partners.add(program["service_partner_id"])

    calc.recompute_facility(store.facilities[asset["facility_id"]])
    for program in calc.facility_programs(asset["facility_id"], ("ACTIVE",)):
        calc.recompute_program(program)
        partners.add(program["service_partner_id"])
    calc.recompute_partners(partners)
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/trade-in/reverse")
@require("OrderPlanner")
def reverse_trade_in(asset_id):
    asset = get_asset(asset_id)
    body = get_body()
    field_str(body, "reverse_reason", min_len=1)

    if asset["status"] != "TRADE_IN_RETURNED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a TRADE_IN_RETURNED asset may have its trade-in reversed.",
        )

    facility = store.facilities[asset["facility_id"]]
    # rung 38 — the granted credit must still be unspent
    valuation = asset["trade_in_valuation_cents"] or 0
    if facility["tradein_credit_balance_cents"] < valuation:
        raise ApiError(
            "ERR_TRADEIN_CREDIT_ALREADY_APPLIED",
            "The granted trade-in credit has already been spent.",
        )

    with mutate(asset):
        asset["status"] = "IN_SERVICE"
        asset["declared_condition_grade"] = None
        asset["trade_in_valuation_cents"] = None

    calc.recompute_facility(facility)
    calc.recompute_facility_programs(asset["facility_id"], ("ACTIVE",))
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/refurb/intake")
@require("ServiceOpsAdmin")
def refurb_intake(asset_id):
    asset = get_asset(asset_id)
    get_body()

    if asset["status"] != "TRADE_IN_RETURNED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a TRADE_IN_RETURNED asset may be taken into refurbishment.",
        )

    with mutate(asset):
        asset["status"] = "REFURB_INTAKE"
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/refurb/certify")
@require("ServiceOpsAdmin")
def refurb_certify(asset_id):
    asset = get_asset(asset_id)
    body = get_body()
    refurb_grade = field_enum(body, "refurb_grade", GRADES)

    if asset["status"] != "REFURB_INTAKE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a REFURB_INTAKE asset may be certified.",
        )

    # rung 19
    _console_support_live(asset)

    with mutate(asset):
        asset["status"] = "REFURB_CERTIFIED"
        asset["refurb_grade"] = refurb_grade
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/resell")
@require("OrderPlanner")
def resell(asset_id):
    asset = get_asset(asset_id)
    body = get_body()
    buyer_facility_id = field_id(body, "buyer_facility_id")

    # rung 9
    buyer = get_facility(buyer_facility_id)

    if asset["status"] != "REFURB_CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a REFURB_CERTIFIED asset may be resold.",
        )

    # rung 19
    _console_support_live(asset)

    # rung 28
    if buyer["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_SUSPENDED", "The buyer facility is suspended.")

    with mutate(asset):
        asset["status"] = "RESOLD"
        asset["facility_id"] = buyer["id"]
        asset["warranty_starts_at"] = None
        asset["warranty_expires_at"] = None
    calc.recompute_asset_support(asset)
    return ok(asset)


@bp.post("/serialized-assets/<asset_id>/scrap")
@require("ServiceOpsAdmin")
def scrap(asset_id):
    asset = get_asset(asset_id)
    body = get_body()
    field_str(body, "scrap_reason", min_len=1)

    if asset["status"] not in ("REFURB_INTAKE", "REFURB_CERTIFIED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a REFURB_INTAKE or REFURB_CERTIFIED asset may be scrapped.",
        )

    with mutate(asset):
        asset["status"] = "SCRAPPED"
    return ok(asset)
