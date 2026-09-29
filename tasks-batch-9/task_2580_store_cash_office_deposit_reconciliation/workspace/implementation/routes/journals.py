"""Sales journals and card settlement advices (PRD sections 3.1 and 3.7)."""
from flask import Blueprint

import calc
import db
import domain
import response
import serializers
import validation
from auth import endpoint
from errors import err
from routes.common import list_collection

bp = Blueprint("journals", __name__)

CARD_NETWORKS = ("VISA_MC", "AMEX")
JOURNAL_READ_ROLES = [
    "CashOfficeClerk",
    "StoreManager",
    "TreasuryAnalyst",
    "LossPreventionInvestigator",
]
SETTLEMENT_READ_ROLES = ["TreasuryAnalyst", "CashOfficeClerk", "StoreManager"]


@bp.post("/cash-ops/sales-journals")
@endpoint(["CashOfficeClerk"])
def create_journal():
    data = validation.body()
    store_id = validation.req_str(data, "store_id")
    business_date = validation.req_date(data, "business_date")
    store = domain.get_store(store_id)
    for existing in db.sales_journals.values():
        if existing["store_id"] == store["id"] and existing["business_date"] == business_date:
            raise err(
                "ERR_DUPLICATE_BUSINESS_DATE",
                "a sales journal already exists for this store and business date",
            )
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "business_date": business_date,
            "status": "OPEN",
            "journal_cash_sales_cents": None,
            "journal_card_sales_cents": None,
        }
    )
    db.sales_journals[record["id"]] = record
    return response.object_response(serializers.sales_journal(record), 201)


@bp.post("/cash-ops/sales-journals/<journal_id>/post-tenders")
@endpoint(["CashOfficeClerk"])
def post_tenders(journal_id):
    data = validation.body()
    cash = validation.req_int(data, "journal_cash_sales_cents", minimum=0)
    card = validation.req_int(data, "journal_card_sales_cents", minimum=0)
    journal = domain.get_journal(journal_id)
    if journal["status"] != "OPEN":
        raise err("ERR_TENDERS_ALREADY_POSTED", "tender totals have already been posted")
    journal["journal_cash_sales_cents"] = cash
    journal["journal_card_sales_cents"] = card
    journal["status"] = "TENDERS_POSTED"
    db.touch(journal)
    domain.reevaluate_journal(journal)
    return response.object_response(serializers.sales_journal(journal))


@bp.get("/cash-ops/sales-journals/<journal_id>")
@endpoint(JOURNAL_READ_ROLES)
def read_journal(journal_id):
    return response.object_response(serializers.sales_journal(domain.get_journal(journal_id)))


@bp.get("/cash-ops/sales-journals")
@endpoint(JOURNAL_READ_ROLES)
def list_journals():
    return list_collection(
        db.sales_journals,
        [("store_id", "store_id"), ("business_date", "business_date"), ("status", "status")],
        serializers.sales_journal,
    )


@bp.post("/cash-ops/card-settlements")
@endpoint(["TreasuryAnalyst"])
def create_settlement():
    data = validation.body()
    journal_id = validation.req_str(data, "sales_journal_id")
    network = validation.req_enum(data, "card_network", CARD_NETWORKS)
    gross = validation.req_int(data, "gross_card_sales_cents", minimum=0)
    txn_count = validation.req_int(data, "txn_count", minimum=0)
    monthly_volume = validation.req_int(data, "monthly_volume_cents", minimum=0)
    funded = validation.req_int(data, "funded_amount_cents", minimum=0)
    chargeback = validation.opt_int(data, "chargeback_cents", 0, minimum=0)
    journal = domain.get_journal(journal_id)
    for existing in db.card_settlements.values():
        if existing["sales_journal_id"] == journal["id"] and existing["card_network"] == network:
            raise err(
                "ERR_SETTLEMENT_ALREADY_POSTED",
                "a settlement already exists for this journal and network",
            )
    figures = calc.card_settlement(gross, txn_count, chargeback, monthly_volume, funded, network)
    record = db.base_record()
    record.update(
        {
            "sales_journal_id": journal["id"],
            "card_network": network,
            "gross_card_sales_cents": gross,
            "txn_count": txn_count,
            "chargeback_cents": chargeback,
            "monthly_volume_cents": monthly_volume,
            "funded_amount_cents": funded,
        }
    )
    record.update(figures)
    db.card_settlements[record["id"]] = record
    db.touch(journal)
    domain.reevaluate_journal(journal)
    return response.object_response(serializers.card_settlement(record), 201)


@bp.get("/cash-ops/card-settlements/<settlement_id>")
@endpoint(SETTLEMENT_READ_ROLES)
def read_settlement(settlement_id):
    return response.object_response(
        serializers.card_settlement(domain.get_settlement(settlement_id))
    )


@bp.get("/cash-ops/card-settlements")
@endpoint(SETTLEMENT_READ_ROLES)
def list_settlements():
    return list_collection(
        db.card_settlements,
        [
            ("sales_journal_id", "sales_journal_id"),
            ("card_network", "card_network"),
            ("settlement_status", "settlement_status"),
        ],
        serializers.card_settlement,
    )
