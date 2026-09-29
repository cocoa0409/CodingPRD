"""Market transaction endpoints (PRD 3.7)."""

from flask import Blueprint

import serializers
from core import add_days, db, new_record, now, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import (ADMIN, ALL_ROLES, DEVELOPER, LANDOWNER, require_owner, require_roles,
                        require_suspension_clear)
from routes.certificates import assert_transferable, get_certificate_or_404, mint_child_certificate
from routes.parties import get_party_or_404
from services import calc
from services.derive import (append_transfer, available_units, certificate_easement,
                             easement_compliance_ok, municipal_bank, recompute_certificate_units,
                             recompute_easement_units, recompute_party_holdings)
from validators import body, field_cents, field_enum, field_int, field_str, filter_enum, filter_str

bp = Blueprint("market", __name__)

CHANNELS = ("PRIVATE", "BANK_PURCHASE", "BANK_RESALE")
CONVEYANCE_MODES = ("WHOLE", "PARTIAL")
TXN_STATUSES = ("PROPOSED", "SETTLED", "REVERSED", "CANCELLED")
CHANNEL_TRANSFER_TYPE = {
    "PRIVATE": "PRIVATE_SALE",
    "BANK_PURCHASE": "BANK_PURCHASE",
    "BANK_RESALE": "BANK_RESALE",
}


def get_transaction_or_404(txn_id):
    txn = db.market_transactions.get(txn_id)
    if txn is None:
        fail("ERR_MARKET_TRANSACTION_NOT_FOUND", "market transaction %s does not exist" % txn_id)
    return txn


@bp.post("/tdr/market-transactions")
def propose_transaction():
    user_id, role = require_roles(LANDOWNER, DEVELOPER, ADMIN)
    data = body()
    channel = field_enum(data, "channel", CHANNELS)
    units = field_int(data, "units", minimum=1)
    field_enum(data, "conveyance_mode", CONVEYANCE_MODES)  # supplied but not authoritative
    agreed_price_cents = field_cents(data, "agreed_price_cents", required=False)
    if channel == "PRIVATE":
        if agreed_price_cents is None:
            fail("ERR_INVALID_REQUEST", "agreed_price_cents is required for the PRIVATE channel")
        if agreed_price_cents <= 0:
            fail("ERR_INVALID_REQUEST", "agreed_price_cents must be greater than zero")
    elif agreed_price_cents is not None:
        fail("ERR_INVALID_REQUEST", "agreed_price_cents must be omitted for bank channels")

    certificate_id = field_str(data, "certificate_id", min_len=1)
    seller_id = field_str(data, "seller_party_id", min_len=1)
    buyer_id = field_str(data, "buyer_party_id", min_len=1)

    cert = get_certificate_or_404(certificate_id)
    seller = get_party_or_404(seller_id)
    buyer = get_party_or_404(buyer_id)

    require_owner(user_id, role, seller_id)
    if seller_id != cert["holder_party_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "seller_party_id is not the current holder of this certificate")

    if channel == "BANK_PURCHASE" and buyer["kind"] != "MUNICIPAL_BANK":
        fail("ERR_PARTY_KIND_MISMATCH", "a BANK_PURCHASE must be bought by the MUNICIPAL_BANK party")
    if channel == "BANK_RESALE" and seller["kind"] != "MUNICIPAL_BANK":
        fail("ERR_PARTY_KIND_MISMATCH", "a BANK_RESALE must be sold by the MUNICIPAL_BANK party")

    if channel == "PRIVATE" and role == ADMIN:
        fail("ERR_CHANNEL_ROLE_MISMATCH", "a PRIVATE channel may not be proposed by an administrator")
    if channel in ("BANK_PURCHASE", "BANK_RESALE") and role != ADMIN:
        fail("ERR_CHANNEL_ROLE_MISMATCH", "a bank channel must be proposed by an administrator")

    require_suspension_clear(seller_id, buyer_id)
    assert_transferable(cert)

    easement = certificate_easement(cert)
    if not easement_compliance_ok(easement):
        fail("ERR_CERTIFICATE_FROZEN", "the source easement is %s" % easement["compliance_status"])
    if cert["market_status"] != "HELD":
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is %s" % cert["market_status"])

    if units > available_units(cert):
        fail("ERR_INSUFFICIENT_CERTIFICATE_UNITS", "only %d units are unencumbered" % available_units(cert))

    schedule = calc.select_appraisal_schedule(cert["origin_neighborhood_code"], now())
    if schedule is None:
        fail("ERR_NO_ACTIVE_APPRAISAL_SCHEDULE", "no ACTIVE appraisal schedule covers the current clock")
    per_unit = calc.per_unit_base_cents(schedule)
    reference = calc.appraised_reference_cents(per_unit, units)
    gross = calc.channel_gross_cents(channel, per_unit, units, agreed_price_cents)
    deviation = calc.price_deviation_bps(gross, reference)
    if not calc.deviation_within_band(deviation):
        fail("ERR_PRICE_DEVIATION_EXCEEDS_BAND", "price deviation of %d bps exceeds the band" % deviation)

    rec = new_record(
        {
            "certificate_id": certificate_id,
            "seller_party_id": seller_id,
            "buyer_party_id": buyer_id,
            "channel": channel,
            "units": units,
            "agreed_price_cents": agreed_price_cents,
            "applied_neighborhood_code": cert["origin_neighborhood_code"],
            "applied_per_unit_value_cents": per_unit,
            "appraised_reference_cents": reference,
            "gross_price_cents": gross,
            "price_deviation_bps": deviation,
            "program_fee_cents": 0,
            "equity_surcharge_cents": 0,
            "net_to_seller_cents": 0,
            "status": "PROPOSED",
            "conveyance_mode": None,
            "conveyed_certificate_id": None,
            "settled_at": None,
            "reversed_at": None,
            "reversal_reason": None,
        }
    )
    db.market_transactions[rec["id"]] = rec

    cert["market_status"] = "UNDER_CONTRACT"
    cert["units_encumbered"] = int(cert["units_encumbered"]) + units
    touch(cert)
    return respond_object(serializers.market_transaction(rec), 201)


@bp.get("/tdr/market-transactions/<txn_id>")
def get_transaction(txn_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.market_transaction(get_transaction_or_404(txn_id)))


@bp.get("/tdr/market-transactions")
def list_transactions():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.market_transactions.values()),
        certificate_id=filter_str("certificate_id"),
        seller_party_id=filter_str("seller_party_id"),
        buyer_party_id=filter_str("buyer_party_id"),
        conveyed_certificate_id=filter_str("conveyed_certificate_id"),
        channel=filter_enum("channel", CHANNELS),
        status=filter_enum("status", TXN_STATUSES),
    )
    return paged(rows, serializers.market_transaction)


@bp.post("/tdr/market-transactions/<txn_id>/settle")
def settle_transaction(txn_id):
    require_roles(ADMIN)
    txn = get_transaction_or_404(txn_id)
    data = body()
    field_str(data, "settlement_note", required=False)

    require_suspension_clear(txn["seller_party_id"], txn["buyer_party_id"])
    if txn["status"] != "PROPOSED":
        fail("ERR_TRANSACTION_NOT_PROPOSED", "transaction is %s" % txn["status"])

    cert = db.certificates[txn["certificate_id"]]
    easement = certificate_easement(cert)
    if not easement_compliance_ok(easement):
        fail("ERR_CERTIFICATE_FROZEN", "the source easement is %s" % easement["compliance_status"])

    units = int(txn["units"])
    other_encumbrance = int(cert["units_encumbered"]) - units
    if units > int(cert["units_remaining"]) - max(0, other_encumbrance):
        fail("ERR_INSUFFICIENT_CERTIFICATE_UNITS", "the certificate no longer carries these units")

    seller = db.parties[txn["seller_party_id"]]
    buyer = db.parties[txn["buyer_party_id"]]
    gross = int(txn["gross_price_cents"])
    area = db.sending_areas.get(cert["origin_sending_area_id"])
    equity_tier = area["equity_tier"] if area else "UNDERSERVED"
    fee, surcharge, net = calc.settlement_split(gross, equity_tier)

    if int(buyer["cash_balance_cents"]) < gross:
        fail("ERR_INSUFFICIENT_FUNDS", "buyer cannot cover the gross price")

    whole = units == int(cert["units_remaining"])
    txn["conveyance_mode"] = "WHOLE" if whole else "PARTIAL"
    if whole:
        cert["holder_party_id"] = buyer["id"]
        conveyed = cert
    else:
        conveyed = mint_child_certificate(cert, buyer["id"], units)
        append_transfer(cert, "SPLIT_OUT", seller["id"], seller["id"], units)
    txn["conveyed_certificate_id"] = conveyed["id"]

    cert["units_encumbered"] = max(0, int(cert["units_encumbered"]) - units)
    cert["market_status"] = "HELD"
    recompute_certificate_units(cert)
    touch(cert)
    if conveyed is not cert:
        touch(conveyed)

    append_transfer(conveyed, CHANNEL_TRANSFER_TYPE[txn["channel"]], seller["id"], buyer["id"], units,
                    price_cents=gross, market_transaction_id=txn["id"])

    buyer["cash_balance_cents"] = int(buyer["cash_balance_cents"]) - gross
    seller["cash_balance_cents"] = int(seller["cash_balance_cents"]) + net
    bank = municipal_bank()
    if bank is not None:
        bank["fee_revenue_cents"] = int(bank["fee_revenue_cents"]) + fee + surcharge

    txn["program_fee_cents"] = fee
    txn["equity_surcharge_cents"] = surcharge
    txn["net_to_seller_cents"] = net
    txn["status"] = "SETTLED"
    txn["settled_at"] = now()
    touch(txn)

    recompute_party_holdings(seller)
    recompute_party_holdings(buyer)
    recompute_easement_units(easement)
    return respond_object(serializers.market_transaction(txn))


@bp.post("/tdr/market-transactions/<txn_id>/cancel")
def cancel_transaction(txn_id):
    user_id, role = require_roles(LANDOWNER, DEVELOPER, ADMIN)
    txn = get_transaction_or_404(txn_id)
    data = body()
    reason = field_str(data, "reason", required=False)

    require_owner(user_id, role, txn["seller_party_id"])
    if txn["status"] != "PROPOSED":
        fail("ERR_TRANSACTION_NOT_PROPOSED", "transaction is %s" % txn["status"])

    cert = db.certificates[txn["certificate_id"]]
    cert["units_encumbered"] = max(0, int(cert["units_encumbered"]) - int(txn["units"]))
    if cert["market_status"] == "UNDER_CONTRACT":
        cert["market_status"] = "HELD"
    touch(cert)

    txn["status"] = "CANCELLED"
    if reason is not None:
        txn["reversal_reason"] = reason
    touch(txn)
    return respond_object(serializers.market_transaction(txn))


@bp.post("/tdr/market-transactions/<txn_id>/reverse")
def reverse_transaction(txn_id):
    require_roles(ADMIN)
    txn = get_transaction_or_404(txn_id)
    data = body()
    reversal_reason = field_str(data, "reversal_reason", min_len=1)

    if txn["status"] != "SETTLED":
        fail("ERR_TRANSACTION_NOT_SETTLED", "transaction is %s" % txn["status"])

    if now() > add_days(txn["settled_at"], calc.REVERSAL_WINDOW_DAYS):
        fail("ERR_REVERSAL_WINDOW_EXPIRED", "the 30 day reversal window has closed")

    conveyed = db.certificates.get(txn["conveyed_certificate_id"])
    if txn["conveyance_mode"] != "WHOLE" or conveyed is None:
        fail("ERR_REVERSAL_NOT_PERMITTED", "only a WHOLE conveyance can be reversed")
    if int(conveyed["units_redeemed"]) != 0 or int(conveyed["units_encumbered"]) != 0 \
            or int(conveyed["units_retired"]) != 0:
        fail("ERR_REVERSAL_NOT_PERMITTED", "the conveyed certificate has moved on since settlement")

    seller = db.parties[txn["seller_party_id"]]
    buyer = db.parties[txn["buyer_party_id"]]
    gross = int(txn["gross_price_cents"])
    fee = int(txn["program_fee_cents"])
    surcharge = int(txn["equity_surcharge_cents"])
    net = int(txn["net_to_seller_cents"])
    bank = municipal_bank()

    if int(seller["cash_balance_cents"]) < net:
        fail("ERR_INSUFFICIENT_FUNDS", "seller cannot return the net proceeds")
    if bank is not None and int(bank["fee_revenue_cents"]) < fee + surcharge:
        fail("ERR_INSUFFICIENT_FUNDS", "the program cannot return the collected fees")

    seller["cash_balance_cents"] = int(seller["cash_balance_cents"]) - net
    buyer["cash_balance_cents"] = int(buyer["cash_balance_cents"]) + gross
    if bank is not None:
        bank["fee_revenue_cents"] = int(bank["fee_revenue_cents"]) - fee - surcharge

    conveyed["holder_party_id"] = seller["id"]
    if conveyed["market_status"] != "FROZEN":
        conveyed["market_status"] = "HELD"
    touch(conveyed)
    append_transfer(conveyed, "REVERSAL", buyer["id"], seller["id"], int(txn["units"]),
                    price_cents=-gross, market_transaction_id=txn["id"])

    txn["status"] = "REVERSED"
    txn["reversed_at"] = now()
    txn["reversal_reason"] = reversal_reason
    touch(txn)

    recompute_party_holdings(seller)
    recompute_party_holdings(buyer)
    return respond_object(serializers.market_transaction(txn))
