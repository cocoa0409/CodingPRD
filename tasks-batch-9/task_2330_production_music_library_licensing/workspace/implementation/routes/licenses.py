"""License issuance and lifecycle (PRD §3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import DB, add_months, fmt_ts
from errors import fail
from middleware import (
    body,
    opt_datetime,
    opt_enum,
    opt_int,
    opt_string,
    present,
    req_enum,
    req_int,
    req_string,
    require_role,
)
from response import object_response, page_response, pagination
from routes.common import (
    MEDIA_TYPES,
    PREFIX,
    SCALES,
    guard_licensee,
    require_state,
    set_clock_dt,
    set_dt,
)
from services import calc
from services.cascade import append_ledger, bump_once, revoke_license, sheet_entries
from services.derive import (
    committed_spend_cents,
    exclusive_block_until,
    lookup,
    open_claim_count,
    rows,
    serialize_license,
)

bp = Blueprint("licenses", __name__)

MODES = ("PER_USE", "BLANKET")
BLANKET_REQUIRED = (
    "composition_id",
    "blanket_agreement_id",
    "tier_id",
    "media_type",
    "distribution_scale",
    "term_start",
    "term_months",
)


@bp.post(PREFIX + "/licenses")
def create_license():
    data = body()
    mode = req_enum(data, "license_mode", MODES)
    expected_version = req_int(data, "expected_composition_version", 0, None)
    sync_request_id = opt_string(data, "sync_request_id")
    composition_id = opt_string(data, "composition_id")
    blanket_agreement_id = opt_string(data, "blanket_agreement_id")
    tier_id = opt_string(data, "tier_id")
    media_type = opt_enum(data, "media_type", MEDIA_TYPES)
    scale = opt_enum(data, "distribution_scale", SCALES)
    raw_term_start, term_start = opt_datetime(data, "term_start")
    term_months = opt_int(data, "term_months", 1, 120)

    # ---- shape check evaluated with the schema pass ------------------------
    if mode == "PER_USE":
        if sync_request_id is None or blanket_agreement_id is not None:
            fail(
                "ERR_LICENSE_MODE_FIELDS_INVALID",
                "PER_USE needs sync_request_id and may not carry blanket_agreement_id.",
            )
    else:
        for name in BLANKET_REQUIRED:
            if not present(data, name):
                fail(
                    "ERR_LICENSE_MODE_FIELDS_INVALID",
                    "BLANKET requires %s." % (", ".join(BLANKET_REQUIRED),),
                )

    # ---- 3 body foreign keys, in the order License declares them ----------
    sync_request = None
    if sync_request_id is not None:
        sync_request = lookup("sync_requests", sync_request_id)
    if composition_id is not None:
        lookup("compositions", composition_id)
    tier = None
    if tier_id is not None:
        tier = lookup("tiers", tier_id)
    blanket = None
    if blanket_agreement_id is not None:
        blanket = lookup("blankets", blanket_agreement_id)

    require_role("LicensingAgent")                                       # 4

    if mode == "PER_USE":
        composition = DB.compositions[sync_request["composition_id"]]
        tier = DB.tiers[sync_request["tier_id"]]
        licensee = DB.licensees[sync_request["licensee_id"]]
    else:
        composition = DB.compositions[composition_id]
        licensee = DB.licensees[blanket["licensee_id"]]

    if composition["version"] != expected_version:                       # 8
        fail(
            "ERR_COMPOSITION_VERSION_CONFLICT",
            "expected composition version %s but the row is at %s."
            % (expected_version, composition["version"]),
        )

    if mode == "PER_USE":
        require_state(sync_request, "status", ("ACCEPTED",), "sync_request")   # 10

    if (
        composition["catalog_status"] != "CATALOGED"
        or composition["availability_status"] == "WITHDRAWN"
    ):                                                                   # 14
        fail("ERR_COMPOSITION_NOT_LICENSABLE", "the work is not licensable.")

    exclusive = bool(mode == "PER_USE" and sync_request["exclusive_requested"])
    if exclusive and open_claim_count(composition["id"]) > 0:             # 15
        fail(
            "ERR_ACTIVE_CLAIM_BLOCKS_LICENSE",
            "an open infringement claim blocks exclusive issuance.",
        )

    if mode == "PER_USE":
        expires = sync_request["_quote_expires_at_dt"]
        if expires is not None and DB.now > expires:                      # 16
            fail("ERR_QUOTE_EXPIRED", "the quote has expired.")

    if mode == "PER_USE":
        effective_start = sync_request["_requested_term_start_dt"]
        effective_raw = sync_request["requested_term_start"]
        effective_months = sync_request["requested_term_months"]
        effective_media = sync_request["media_type"]
        effective_scale = sync_request["distribution_scale"]
    else:
        effective_start = term_start
        effective_raw = raw_term_start
        effective_months = term_months
        effective_media = media_type
        effective_scale = scale

    block = exclusive_block_until(composition["id"])
    if block is not None and effective_start <= block:                    # 17
        fail("ERR_EXCLUSIVE_WINDOW_CONFLICT", "the work is inside an exclusivity block.")

    if mode == "BLANKET":
        if not (
            blanket["_coverage_start_dt"] <= effective_start < blanket["_coverage_end_dt"]
        ):                                                                # 18
            fail("ERR_TERM_OUTSIDE_COVERAGE", "term_start is outside the coverage interval.")
        if blanket["coverage_status"] != "ACTIVE" or blanket["reporting_status"] == "DELINQUENT":
            fail("ERR_BLANKET_NOT_ACTIVE", "the blanket agreement is not available.")   # 19

    if mode == "PER_USE" and not tier["per_use_eligible"]:                # 26
        fail("ERR_TIER_INCOMPATIBLE", "this tier may not be cited by a PER_USE licence.")
    if mode == "BLANKET" and not tier["blanket_eligible"]:
        fail("ERR_TIER_INCOMPATIBLE", "this tier may not be cited by a BLANKET licence.")

    committed = committed_spend_cents(licensee["id"])
    if mode == "PER_USE":
        fee, basis, pct, _pre = calc.license_fee(
            tier["base_rate_cents"],
            effective_media,
            effective_scale,
            effective_months,
            exclusive,
            sync_request["rush_requested"],
            sync_request["custom_edit_requested"],
            sync_request["stems_requested"],
            len(sync_request["alternate_lengths_sec"]),
            committed,
        )
    else:
        fee, basis, pct = 0, 0, Decimal("0.00")

    if committed + fee > licensee["credit_limit_cents"]:                  # 29
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "issuance would exceed the licensee credit limit.")

    agreement = DB.agreements.get(composition["agreement_id"])
    term_end = add_months(effective_start, effective_months) - timedelta(days=1)
    if exclusive and agreement is not None:
        block_until = term_end + timedelta(days=agreement["holdback_days"])
    else:
        block_until = term_end
    share_pct = agreement["_sync_fee_share_pct"] if agreement is not None else Decimal("0")
    composer_share = calc.cents(Decimal(fee) * share_pct / Decimal(100))

    row = DB.new_row()
    row.update(
        {
            "sync_request_id": sync_request["id"] if sync_request is not None else None,
            "composition_id": composition["id"],
            "licensee_id": licensee["id"],
            "tier_id": tier["id"],
            "blanket_agreement_id": blanket["id"] if blanket is not None else None,
            "license_mode": mode,
            "media_type": effective_media,
            "distribution_scale": effective_scale,
            "is_exclusive": exclusive,
            "term_months": effective_months,
            "final_fee_cents": fee,
            "final_spend_basis_cents": basis,
            "_final_discount_pct": calc.dp2(pct),
            "composer_sync_share_cents": composer_share,
            "collected_amount_cents": 0,
            "collected_at": None,
            "status": "ISSUED",
            "revoke_reason": None,
        }
    )
    set_dt(row, "term_start", effective_raw, effective_start)
    set_clock_dt(row, "term_end", term_end)
    set_clock_dt(row, "exclusive_block_until", block_until)
    DB.licenses[row["id"]] = row

    bump_once(composition)
    if sync_request is not None:
        sync_request["license_id"] = row["id"]
        bump_once(sync_request)
    bump_once(licensee)
    if composer_share != 0:
        append_ledger(
            composition["composer_id"],
            "SYNC_FEE",
            row["id"],
            composer_share,
            "LICENSE_SYNC_FEE",
            cash=False,
        )
    return object_response(serialize_license(row), 201)


@bp.get(PREFIX + "/licenses/<license_id>")
def get_license(license_id):
    row = lookup("licenses", license_id)
    require_role(
        "LicensingAgent", "RightsManager", "CatalogAdmin", "RoyaltyAccountant", "Licensee"
    )
    guard_licensee(row["licensee_id"])
    return object_response(serialize_license(row))


@bp.get(PREFIX + "/licenses")
def list_licenses():
    limit, offset = pagination(request.args)
    require_role("LicensingAgent", "RightsManager", "CatalogAdmin", "RoyaltyAccountant")
    result = rows("licenses")
    for name in (
        "composition_id",
        "licensee_id",
        "tier_id",
        "sync_request_id",
        "blanket_agreement_id",
        "status",
    ):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_license)


@bp.post(PREFIX + "/licenses/<license_id>/activate")
def activate(license_id):
    row = lookup("licenses", license_id)
    require_role("LicensingAgent")
    require_state(row, "status", ("ISSUED",), "license")
    from db import date_only

    if date_only(DB.now) < row["_term_start_dt"]:                          # 50
        fail("ERR_TERM_NOT_STARTED", "the licence term has not started yet.")
    row["status"] = "ACTIVE"
    bump_once(row)
    return object_response(serialize_license(row))


@bp.post(PREFIX + "/licenses/<license_id>/revoke")
def revoke(license_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("licenses", license_id)
    require_role("RightsManager")
    require_state(row, "status", ("ISSUED", "ACTIVE"), "license")
    revoke_license(row, reason)
    return object_response(serialize_license(row))


@bp.post(PREFIX + "/licenses/<license_id>/record-payment")
def record_payment(license_id):
    data = body()
    amount = req_int(data, "amount_cents")
    row = lookup("licenses", license_id)
    require_role("RoyaltyAccountant")
    if amount <= 0 or row["collected_amount_cents"] + amount > row["final_fee_cents"]:
        fail("ERR_PAYMENT_EXCEEDS_FEE", "the payment does not fit the outstanding fee.")  # 51

    row["collected_amount_cents"] = row["collected_amount_cents"] + amount
    if row["collected_amount_cents"] >= row["final_fee_cents"] and row["collected_at"] is None:
        row["collected_at"] = DB.now_iso
        stamp = DB.now_iso
        for entry in sheet_entries(row["id"], "SYNC_FEE"):
            if entry["cash_recognized_at"] is None:
                entry["cash_recognized_at"] = stamp
    bump_once(row)
    return object_response(serialize_license(row))
