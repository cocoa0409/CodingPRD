"""ComplianceAccount endpoints: register, get, position, exposure, purge-records."""
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, retention_active,
)
from middleware import require_roles, json_body
from response import ok_object
from serializers import account_view
from services import calculations
from services.calculations import round_half_up_int, round_half_up_4dp, _d

bp = Blueprint("accounts", __name__)


@bp.route("/rfs/compliance-accounts", methods=["POST"])
def create_account():
    require_roles("OpsAdmin")
    body = json_body()
    company_name = body.get("company_name")
    epa_registration_id = body.get("epa_registration_id")
    if not company_name or not isinstance(company_name, str):
        raise invalid_request("company_name is required")
    if not epa_registration_id or not isinstance(epa_registration_id, str):
        raise invalid_request("epa_registration_id is required")
    # Natural-key uniqueness: epa_registration_id unique across accounts
    for existing in db.compliance_accounts.values():
        if existing["epa_registration_id"] == epa_registration_id:
            raise invalid_request("epa_registration_id must be unique")

    now = db.now_utc()
    account = {
        "id": db.new_id(),
        "company_name": company_name,
        "epa_registration_id": epa_registration_id,
        "escrow_reserved_cents": 0,
        "spent_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.compliance_accounts[account["id"]] = account
    return ok_object(account_view(account), status=201)


def _get_account(account_id):
    account = db.compliance_accounts.get(account_id)
    if account is None:
        raise not_found("Compliance account not found")
    return account


@bp.route("/rfs/compliance-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader", "Auditor")
    return ok_object(account_view(_get_account(account_id)))


@bp.route("/rfs/compliance-accounts/<account_id>/position", methods=["GET"])
def get_position(account_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    account = _get_account(account_id)

    # Group all of the account's lots (regardless of status) by (d_code, vintage_year)
    buckets = {}
    for lot in db.rin_lots.values():
        if lot["account_id"] != account["id"]:
            continue
        key = (lot["d_code"], lot["vintage_year"])
        bucket = buckets.setdefault(key, {
            "d_code": lot["d_code"],
            "vintage_year": lot["vintage_year"],
            "generated_rins": 0,
            "purchased_rins": 0,
            "separated_rins": 0,
            "retired_rins": 0,
            "invalidated_rins": 0,
            "expired_rins": 0,
            "available_rins": 0,
            "eligible_rins": 0,
        })
        if lot["origin"] == "GENERATED":
            bucket["generated_rins"] += lot["rin_qty"]
        else:
            bucket["purchased_rins"] += lot["rin_qty"]
        bucket["separated_rins"] += lot["separated_qty"]
        bucket["retired_rins"] += lot["retired_qty"]
        bucket["invalidated_rins"] += lot["invalidated_qty"]
        bucket["expired_rins"] += lot["expired_qty"]
        bucket["available_rins"] += lot["available_qty"]

        # eligible_rins: lots passing the retirement eligibility screen with the
        # vintage-year term set aside
        if lot["status"] == "ACTIVE" and lot["available_qty"] > 0:
            if lot["origin"] == "PURCHASED":
                trade = db.rin_trades.get(lot["trade_id"])
                if trade is None or trade["transfer_status"] != "VERIFIED":
                    continue
            bucket["eligible_rins"] += lot["available_qty"]

    bucket_list = [buckets[k] for k in sorted(buckets.keys(), key=lambda k: (k[0], k[1]))]
    return ok_object({
        "buckets": bucket_list,
        "total_available_rins": sum(b["available_rins"] for b in bucket_list),
        "total_retired_rins": sum(b["retired_rins"] for b in bucket_list),
        "total_invalidated_rins": sum(b["invalidated_rins"] for b in bucket_list),
    })


@bp.route("/rfs/compliance-accounts/<account_id>/exposure", methods=["GET"])
def get_exposure(account_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    account = _get_account(account_id)
    now = db.now_utc()

    # Buckets: ACTIVE lots with available_qty > 0, grouped by (d_code, vintage_year)
    buckets = {}
    for lot in db.rin_lots.values():
        if lot["account_id"] != account["id"]:
            continue
        if lot["status"] != "ACTIVE" or lot["available_qty"] <= 0:
            continue
        key = (lot["d_code"], lot["vintage_year"])
        bucket = buckets.setdefault(key, {"qty": 0, "cost_qty": 0})
        bucket["qty"] += lot["available_qty"]
        bucket["cost_qty"] += lot["available_qty"] * lot["unit_cost_cents"]

    total_exposure_cents = 0
    priced_bucket_count = 0
    unpriced_bucket_count = 0

    for (d_code, vintage_year), bucket in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        # wac 4dp half-up
        wac_cents = _d(bucket["cost_qty"]) / _d(bucket["qty"])
        wac_cents = Decimal(str(round_half_up_4dp(wac_cents)))
        # Covering quote: closed window [effective_start, effective_end] contains now
        quote = None
        for q in db.price_quotes.values():
            if q["account_id"] != account["id"]:
                continue
            if q["d_code"] != d_code or q["vintage_year"] != vintage_year:
                continue
            if q["effective_start"] <= now <= q["effective_end"]:
                quote = q
                break
        if quote is None:
            unpriced_bucket_count += 1
            continue
        priced_bucket_count += 1
        gain = round_half_up_int(_d(bucket["qty"]) * (_d(quote["price_cents"]) - wac_cents))
        total_exposure_cents += gain

    return ok_object({
        "total_exposure_cents": total_exposure_cents,
        "priced_bucket_count": priced_bucket_count,
        "unpriced_bucket_count": unpriced_bucket_count,
    })


@bp.route("/rfs/compliance-accounts/<account_id>/purge-records", methods=["POST"])
def purge_records(account_id):
    require_roles("OpsAdmin")
    account = _get_account(account_id)
    now = db.now_utc()

    # Collect the account's blending records and price quotes
    target_blending = [b for b in db.blending_records.values() if b["account_id"] == account["id"]]
    target_quotes = [q for q in db.price_quotes.values() if q["account_id"] == account["id"]]

    # All-or-nothing: any record not yet purgeable fails the entire request
    for record in target_blending + target_quotes:
        if record["retention_until"] > now:
            raise retention_active("A targeted record is still within its retention window")

    for record in target_blending:
        del db.blending_records[record["id"]]
    for record in target_quotes:
        del db.price_quotes[record["id"]]

    return ok_object({
        "purged_blending_records": len(target_blending),
        "purged_price_quotes": len(target_quotes),
    })
