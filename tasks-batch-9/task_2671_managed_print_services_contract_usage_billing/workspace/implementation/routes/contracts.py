"""ServiceContract and CostTier endpoints (PRD 3.1)."""
from flask import Blueprint

import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract
from store import db, new_row, touch
from util import overlaps

bp = Blueprint("contracts", __name__)

SCOPES = ("BASIC", "FULL")
PAGE_CLASSES = ("MONO", "COLOR")
SUSPEND_REASONS = ("NONPAYMENT", "DISPUTE", "CUSTOMER_REQUEST")
_INF = float("inf")


@bp.post("/service-contracts")
def create_contract():
    require("AccountManager")
    body = v.body()
    customer_name = v.string_field(body, "customer_name", max_len=120)
    term_months = v.int_field(body, "term_months", minimum=12, maximum=60)
    scope = v.enum_field(body, "included_service_scope", SCOPES)
    minimum_mono = v.int_field(body, "minimum_mono_pages_per_period", minimum=0)
    minimum_color = v.int_field(body, "minimum_color_pages_per_period", minimum=0)
    fee = v.int_field(body, "monthly_service_fee_cents", minimum=0)
    sla_critical = v.int_field(body, "response_sla_hours_critical", required=False,
                               minimum=1, maximum=72, default=4)
    sla_standard = v.int_field(body, "response_sla_hours_standard", required=False,
                               minimum=1, maximum=168, default=24)
    labor_rate = v.int_field(body, "labor_rate_cents_per_hour", required=False,
                             minimum=0, default=9500)
    early_fee = v.int_field(body, "early_termination_fee_cents", required=False,
                            minimum=0, default=0)

    row = new_row()
    row.update({
        "customer_name": customer_name,
        "term_months": term_months,
        "status": "DRAFT",
        "included_service_scope": scope,
        "minimum_mono_pages_per_period": minimum_mono,
        "minimum_color_pages_per_period": minimum_color,
        "monthly_service_fee_cents": fee,
        "response_sla_hours_critical": sla_critical,
        "response_sla_hours_standard": sla_standard,
        "labor_rate_cents_per_hour": labor_rate,
        "early_termination_fee_cents": early_fee,
        "true_up_balance_cents": 0,
        "lifetime_billed_cents": 0,
        "suspension_count": 0,
        "suspension_reason": "NONE",
    })
    db.contracts[row["id"]] = row
    return created(serialize.contract(row))


@bp.get("/service-contracts/<contract_id>")
def read_contract(contract_id):
    require("AccountManager", "BillingAnalyst", "FleetOpsController",
            "FieldTechnician", "CustomerAdmin")
    contract = get_contract(contract_id)
    return ok(serialize.contract(contract))


@bp.post("/service-contracts/<contract_id>/cost-tiers")
def create_cost_tier(contract_id):
    require("AccountManager")
    contract = get_contract(contract_id)
    body = v.body()
    page_class = v.enum_field(body, "page_class", PAGE_CLASSES)
    tier_index = v.int_field(body, "tier_index", minimum=1)
    from_page = v.int_field(body, "from_page", minimum=1)
    to_page = v.int_field(body, "to_page", required=False, default=None)
    rate = v.int_field(body, "rate_micro_dollars_per_page", minimum=1)
    if to_page is not None and to_page < from_page:
        fail("ERR_INVALID_REQUEST", "Field 'to_page' must not be smaller than 'from_page'.")
    if tier_index == 1 and from_page != 1:
        fail("ERR_INVALID_REQUEST", "The tier_index 1 row must have from_page 1.")

    existing = derive.tier_rows(contract["id"], page_class)
    for row in existing:
        if row["tier_index"] == tier_index:
            fail("ERR_TIER_BAND_CONFLICT",
                 "tier_index %d already exists for %s on this contract." % (tier_index, page_class))
    # Inclusive bands are compared as half-open [from, to+1); a null to_page is
    # unbounded above, so two unbounded top bands always intersect.
    new_upper = _INF if to_page is None else to_page + 1
    for row in existing:
        other_upper = _INF if row["to_page"] is None else row["to_page"] + 1
        if overlaps(from_page, new_upper, row["from_page"], other_upper):
            fail("ERR_TIER_BAND_CONFLICT",
                 "The requested page band intersects an existing %s band." % page_class)

    row = new_row(with_common=False)
    row.update({
        "contract_id": contract["id"],
        "page_class": page_class,
        "tier_index": tier_index,
        "from_page": from_page,
        "to_page": to_page,
        "rate_micro_dollars_per_page": rate,
    })
    db.cost_tiers[row["id"]] = row
    return created(serialize.cost_tier(row))


@bp.get("/service-contracts/<contract_id>/cost-tiers")
def list_cost_tiers(contract_id):
    require("AccountManager", "BillingAnalyst", "FleetOpsController")
    contract = get_contract(contract_id)
    rows = [t for t in db.sorted_rows("cost_tiers") if t["contract_id"] == contract["id"]]
    page_class = v.query_filter("page_class")
    if page_class is not None:
        rows = [t for t in rows if t["page_class"] == page_class]
    data, meta = v.paginate(rows, serialize.cost_tier)
    return ok_list(data, meta)


@bp.post("/service-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    require("AccountManager")
    contract = get_contract(contract_id)
    v.body()
    if contract["status"] != "DRAFT":
        fail("ERR_CONTRACT_INVALID_STATE",
             "A contract in %s cannot be activated." % contract["status"])
    if not _entry_row(contract["id"], "MONO"):
        fail("ERR_RATE_CARD_INCOMPLETE",
             "A MONO tier_index 1 row with from_page 1 is required to activate.")
    color_needed = any(d["color_capable"] for d in derive.contract_devices(contract["id"]))
    if color_needed and not _entry_row(contract["id"], "COLOR"):
        fail("ERR_RATE_CARD_INCOMPLETE",
             "A COLOR tier_index 1 row with from_page 1 is required for a colour-capable fleet.")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(serialize.contract(contract))


def _entry_row(contract_id, page_class):
    for row in derive.tier_rows(contract_id, page_class):
        if row["tier_index"] == 1 and row["from_page"] == 1:
            return row
    return None


@bp.post("/service-contracts/<contract_id>/suspend")
def suspend_contract(contract_id):
    require("AccountManager")
    contract = get_contract(contract_id)
    body = v.body()
    reason = v.enum_field(body, "reason", SUSPEND_REASONS)
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_INVALID_STATE",
             "A contract in %s cannot be suspended." % contract["status"])
    for period in derive.contract_periods(contract["id"]):
        if period["status"] == "PROVISIONAL":
            fail("ERR_CONTRACT_INVALID_STATE",
                 "A billing period is still PROVISIONAL; close or regenerate it first.")
    contract["status"] = "SUSPENDED"
    contract["suspension_reason"] = reason
    contract["suspension_count"] += 1
    touch(contract)
    return ok(serialize.contract(contract))


@bp.post("/service-contracts/<contract_id>/resume")
def resume_contract(contract_id):
    require("AccountManager")
    contract = get_contract(contract_id)
    v.body()
    if contract["status"] != "SUSPENDED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "A contract in %s cannot be resumed." % contract["status"])
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(serialize.contract(contract))
