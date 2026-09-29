"""Customers, subpoenas, accounts, funding sources and association links."""
import random

from flask import Blueprint, g

import calc
import serial
from core import (
    API_PREFIX,
    DIGITS4,
    ApiError,
    bad,
    body,
    db,
    endpoint,
    fail,
    get_account,
    get_customer,
    get_funding_source,
    get_subpoena,
    now,
    ok,
    ok_list,
    opt_bool,
    opt_enum,
    opt_str,
    pagination,
    paginate,
    query_enum,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
    sort_rows,
    touch,
    base_row,
)

bp = Blueprint("a", __name__)

READERS = ["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "BsaOfficer", "LegalCounsel"]

KYC_TIERS = {"TIER_1", "TIER_2", "TIER_3"}
PRODUCT_TYPES = {"CHECKING", "SAVINGS", "MONEY_MARKET"}
OPEN_CHANNELS = {"BRANCH", "ONLINE", "MOBILE"}
SOURCE_TYPES = {"EXTERNAL_ACH", "WIRE", "CARD_PUSH"}
VERIFICATION_STATUSES = {
    "DECLARED",
    "MICRO_DEPOSIT_SENT",
    "FAILED_ATTEMPT",
    "VERIFIED",
    "BLOCKED",
}
LINK_TYPES = {"SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_PHONE", "TRANSFER_COUNTERPARTY"}
LIFECYCLE_STATUSES = {"PENDING_FUNDING", "ACTIVE", "RESTRICTED", "CLOSED", "CHARGED_OFF"}
SUBPOENA_STATUSES = {"RECEIVED", "UNDER_LEGAL_REVIEW", "PRODUCED", "OBJECTED", "QUASHED"}


def mint_micro_deposit():
    return random.randint(1, 99)


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/customers")
@endpoint(["OperationsAdmin"])
def create_customer():
    data = body()
    legal_name = req_str(data, "legal_name", 1, 120)
    tin = req_str(data, "tin_last4", 1, None)
    if not DIGITS4.match(tin):
        bad("tin_last4 must be exactly 4 ASCII digits.")
    kyc = opt_enum(data, "kyc_tier", KYC_TIERS, "TIER_2")
    watchlist = opt_bool(data, "watchlist_hit", False)

    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "tin_last4": tin,
            "kyc_tier": kyc,
            "watchlist_hit": watchlist,
        }
    )
    db.customers[row["id"]] = row
    return ok(serial.customer(row), 201)


@bp.get(API_PREFIX + "/customers/<cid>")
@endpoint(READERS)
def read_customer(cid):
    row = get_customer(cid)
    return ok(serial.customer(row))


@bp.get(API_PREFIX + "/customers/<cid>/accounts")
@endpoint(READERS)
def list_customer_accounts(cid):
    get_customer(cid)
    limit, offset = pagination()
    status = query_enum("lifecycle_status", LIFECYCLE_STATUSES)
    rows = [a for a in db.accounts.values() if a["customer_id"] == cid]
    if status:
        rows = [a for a in rows if a["lifecycle_status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.account)
    return ok_list(items, limit, offset, total)


@bp.get(API_PREFIX + "/customers/<cid>/subpoenas")
@endpoint(READERS)
def list_customer_subpoenas(cid):
    get_customer(cid)
    limit, offset = pagination()
    status = query_enum("status", SUBPOENA_STATUSES)
    rows = [s for s in db.subpoenas.values() if s["customer_id"] == cid]
    if status:
        rows = [s for s in rows if s["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.subpoena)
    return ok_list(items, limit, offset, total)


@bp.post(API_PREFIX + "/customers/<cid>/subpoenas")
@endpoint(["LegalCounsel"])
def create_subpoena(cid):
    customer = get_customer(cid)
    data = body()
    agency = req_str(data, "issuing_agency", 1, 120)
    docket = req_str(data, "docket_number", 1, 64)
    due = req_dt(data, "response_due_at")
    start = req_dt(data, "preservation_start_at")
    end = req_dt(data, "preservation_end_at")
    clock = now()
    if not (due > clock):
        bad("response_due_at must be strictly after the logical clock.")
    if not (end > start):
        bad("preservation_end_at must be strictly after preservation_start_at.")

    # rank 16 — preservation window buffer
    buffer_delta = calc.days(calc.PRESERVATION_BUFFER_DAYS)
    for other in db.subpoenas.values():
        if other["customer_id"] != cid:
            continue
        if other["status"] not in calc.PRESERVATION_STATUSES:
            continue
        ok_gap = (
            start >= other["preservation_end_at"] + buffer_delta
            or end + buffer_delta <= other["preservation_start_at"]
        )
        if not ok_gap:
            fail(
                "ERR_PRESERVATION_WINDOW_CONFLICT",
                "Preservation window conflicts with an existing window on this customer.",
            )

    row = base_row()
    row.update(
        {
            "customer_id": cid,
            "issuing_agency": agency,
            "docket_number": docket,
            "received_at": clock,
            "response_due_at": due,
            "preservation_start_at": start,
            "preservation_end_at": end,
            "status": "RECEIVED",
            "legal_reviewed_by_user_id": None,
            "responded_by_user_id": None,
            "is_late": False,
            "production_note": None,
        }
    )
    db.subpoenas[row["id"]] = row
    return ok(serial.subpoena(row), 201)


# --------------------------------------------------------------------------
# Subpoena handling
# --------------------------------------------------------------------------
@bp.get(API_PREFIX + "/subpoenas/<sid>")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor", "LegalCounsel"])
def read_subpoena(sid):
    return ok(serial.subpoena(get_subpoena(sid)))


@bp.post(API_PREFIX + "/subpoenas/<sid>/legal-review")
@endpoint(["LegalCounsel"])
def subpoena_legal_review(sid):
    row = get_subpoena(sid)
    if row["status"] != "RECEIVED":
        fail("ERR_SUBPOENA_INVALID_STATE", "Legal review requires status RECEIVED.")
    row["status"] = "UNDER_LEGAL_REVIEW"
    row["legal_reviewed_by_user_id"] = g.user_id
    touch(row)
    return ok(serial.subpoena(row))


@bp.post(API_PREFIX + "/subpoenas/<sid>/respond")
@endpoint(["LegalCounsel"])
def subpoena_respond(sid):
    row = get_subpoena(sid)
    data = body()
    disposition = req_enum(data, "disposition", {"PRODUCE", "OBJECT", "QUASH"})
    production_note = opt_str(data, "production_note")
    late_justification = opt_str(data, "late_justification")

    if row["status"] != "UNDER_LEGAL_REVIEW":
        fail("ERR_SUBPOENA_INVALID_STATE", "Response requires status UNDER_LEGAL_REVIEW.")
    if g.user_id == row["legal_reviewed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The counsel who reviewed the process may not sign the response.",
        )
    clock = now()
    is_late = clock > row["response_due_at"]
    if is_late and not (late_justification or "").strip():
        fail("ERR_LATE_JUSTIFICATION_REQUIRED", "A late response requires late_justification.")

    row["status"] = {
        "PRODUCE": "PRODUCED",
        "OBJECT": "OBJECTED",
        "QUASH": "QUASHED",
    }[disposition]
    row["responded_by_user_id"] = g.user_id
    row["production_note"] = production_note
    row["is_late"] = is_late
    touch(row)
    return ok(serial.subpoena(row))


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts")
@endpoint(["OperationsAdmin"])
def create_account():
    data = body()
    customer_id = req_id(data, "customer_id")
    product_type = req_enum(data, "product_type", PRODUCT_TYPES)
    open_channel = req_enum(data, "open_channel", OPEN_CHANNELS)
    get_customer(customer_id)

    row = base_row()
    row.update(
        {
            "customer_id": customer_id,
            "product_type": product_type,
            "open_channel": open_channel,
            "opened_at": now(),
            "lifecycle_status": "PENDING_FUNDING",
            "access_posture": "NORMAL",
            "risk_score": 0,
            "risk_score_basis": "PROVISIONAL_AT_OPEN",
            "risk_band": "STANDARD",
            "ato_indicator_codes": [],
            "ato_score": 0,
            "step_up_failure_count": 0,
            "ledger_balance_cents": 0,
            "available_balance_cents": 0,
            "charged_off_amount_cents": 0,
            "closure_scheduled_at": None,
            "closure_reason": None,
        }
    )
    db.accounts[row["id"]] = row
    calc.apply_risk_score(row, "PROVISIONAL_AT_OPEN")
    return ok(serial.account(row), 201)


@bp.get(API_PREFIX + "/accounts/<aid>")
@endpoint(READERS + ["AccountHolder"])
def read_account(aid):
    row = get_account(aid)
    if g.user_role == "AccountHolder" and g.user_id != row["customer_id"]:
        fail("ERR_NOT_ACCOUNT_OWNER", "Caller does not own this account.")
    return ok(serial.account(row))


# --------------------------------------------------------------------------
# Funding sources
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/accounts/<aid>/funding-sources")
@endpoint(["OperationsAdmin"])
def create_funding_source(aid):
    acct = get_account(aid)
    data = body()
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    routing = req_str(data, "routing_last4", 1, None)
    if not DIGITS4.match(routing):
        bad("routing_last4 must be exactly 4 ASCII digits.")

    row = base_row()
    row.update(
        {
            "account_id": aid,
            "source_type": source_type,
            "routing_last4": routing,
            "micro_deposit_cents": mint_micro_deposit(),
            "verification_status": "MICRO_DEPOSIT_SENT",
            "attempt_count": 0,
            "total_attempt_count": 0,
            "verified_at": None,
        }
    )
    db.funding_sources[row["id"]] = row

    snap = calc.snapshot_account(acct)
    calc.refresh_risk(acct)
    calc.bump_if_dirty(acct, snap)
    return ok(serial.funding_source(row), 201)


@bp.get(API_PREFIX + "/accounts/<aid>/funding-sources")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def list_funding_sources(aid):
    get_account(aid)
    limit, offset = pagination()
    status = query_enum("verification_status", VERIFICATION_STATUSES)
    rows = [f for f in db.funding_sources.values() if f["account_id"] == aid]
    if status:
        rows = [f for f in rows if f["verification_status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.funding_source)
    return ok_list(items, limit, offset, total)


@bp.post(API_PREFIX + "/funding-sources/<fid>/verification-attempts")
@endpoint(["OperationsAdmin"])
def verification_attempt(fid):
    src = get_funding_source(fid)
    data = body()
    submitted = req_int(data, "micro_deposit_cents", 0, 99999)

    if src["verification_status"] not in ("MICRO_DEPOSIT_SENT", "FAILED_ATTEMPT"):
        fail(
            "ERR_FUNDING_INVALID_STATE",
            "Verification attempts require MICRO_DEPOSIT_SENT or FAILED_ATTEMPT.",
        )

    src["attempt_count"] += 1
    src["total_attempt_count"] += 1
    acct = db.accounts.get(src["account_id"])
    snap = calc.snapshot_account(acct) if acct is not None else None

    if submitted == src["micro_deposit_cents"]:
        src["verification_status"] = "VERIFIED"
        src["verified_at"] = now()
        if acct is not None and acct["lifecycle_status"] == "PENDING_FUNDING":
            acct["lifecycle_status"] = "ACTIVE"
    else:
        if src["total_attempt_count"] >= calc.FUNDING_MAX_TOTAL_ATTEMPTS:
            src["verification_status"] = "BLOCKED"
        else:
            src["verification_status"] = "FAILED_ATTEMPT"
    touch(src)

    # Every verification attempt re-evaluates the account under REFRESHED.
    if acct is not None:
        calc.refresh_risk(acct)
        calc.bump_if_dirty(acct, snap)
    return ok(serial.funding_source(src))


@bp.post(API_PREFIX + "/funding-sources/<fid>/resend")
@endpoint(["OperationsAdmin"])
def funding_resend(fid):
    src = get_funding_source(fid)
    if (
        src["verification_status"] != "FAILED_ATTEMPT"
        or src["total_attempt_count"] >= calc.FUNDING_MAX_TOTAL_ATTEMPTS
    ):
        fail(
            "ERR_FUNDING_INVALID_STATE",
            "Resend requires FAILED_ATTEMPT with lifetime budget remaining.",
        )
    src["micro_deposit_cents"] = mint_micro_deposit()
    src["attempt_count"] = 0
    src["verification_status"] = "MICRO_DEPOSIT_SENT"
    touch(src)

    acct = db.accounts.get(src["account_id"])
    if acct is not None:
        snap = calc.snapshot_account(acct)
        calc.refresh_risk(acct)
        calc.bump_if_dirty(acct, snap)
    return ok(serial.funding_source(src))


# --------------------------------------------------------------------------
# Association links
# --------------------------------------------------------------------------
@bp.post(API_PREFIX + "/account-links")
@endpoint(["FraudAnalyst", "OperationsAdmin"])
def create_account_link():
    data = body()
    from_id = req_id(data, "from_account_id")
    to_id = req_id(data, "to_account_id")
    link_type = req_enum(data, "link_type", LINK_TYPES)
    confidence = req_int(data, "confidence_bps", 0, 10000)

    get_account(from_id)
    get_account(to_id)

    if from_id == to_id:
        fail("ERR_SELF_LINK", "An account may not be linked to itself.")
    for link in db.account_links.values():
        if (
            link["from_account_id"] == from_id
            and link["to_account_id"] == to_id
            and link["link_type"] == link_type
        ):
            fail("ERR_DUPLICATE_LINK", "This association edge already exists.")

    row = base_row()
    row.update(
        {
            "from_account_id": from_id,
            "to_account_id": to_id,
            "link_type": link_type,
            "confidence_bps": confidence,
            "is_risk_bearing": link_type in calc.RISK_LINK_TYPES
            and confidence >= calc.LINK_CONFIDENCE_MIN_BPS,
        }
    )
    db.account_links[row["id"]] = row

    for aid in (from_id, to_id):
        acct = db.accounts[aid]
        snap = calc.snapshot_account(acct)
        calc.refresh_risk(acct)
        calc.bump_if_dirty(acct, snap)
    return ok(serial.account_link(row), 201)


@bp.get(API_PREFIX + "/accounts/<aid>/links")
@endpoint(["OperationsAdmin", "FraudAnalyst", "FraudSupervisor"])
def list_account_links(aid):
    get_account(aid)
    limit, offset = pagination()
    link_type = query_enum("link_type", LINK_TYPES)
    rows = [
        l
        for l in db.account_links.values()
        if l["from_account_id"] == aid or l["to_account_id"] == aid
    ]
    if link_type:
        rows = [l for l in rows if l["link_type"] == link_type]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serial.account_link)
    return ok_list(items, limit, offset, total)
