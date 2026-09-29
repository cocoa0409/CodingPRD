"""Advance routes: booking, funding, custody receipts, valuation, shipment and
the two exits (PRD 3.3 through 3.7)."""

from fractions import Fraction

from flask import Blueprint

from clock import clock, plus_days, plus_hours
from db import base_row, by_created_at, db, touch
from errors import ApiError
from middleware import (
    BORROWER,
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    CUSTODIAN,
    INVESTOR,
    WIRE_OPERATOR,
    mismatch,
    own_facility,
    require_auth,
)
from response import ok
from routes.common import (
    advance_facility,
    filter_by,
    get_advance,
    get_investor,
    list_response,
)
from serializers import (
    advance_out,
    bailee_letter_out,
    demand_out,
    ledger_entry_out,
    margin_call_out,
    receipt_out,
    wire_out,
)
from services import computed, sizing
from services.constants import (
    AGING_RUN_DEMAND_DAYS,
    DEMAND_REASONS,
    DOCUMENT_TYPES,
    EXCEPTION_CODES,
    FUNDING_TYPES,
    ON_BOOK_FUNDING,
    PRODUCT_CODES,
)
from services.ledger import post_entry
from services.states import (
    close_calls,
    create_margin_call,
    has_open_call,
    reevaluate_restricted,
    restrict_if_active,
)
from validation import (
    MISSING,
    bad,
    body,
    reject_system_fields,
    v_digits,
    v_enum,
    v_enum_array,
    v_id,
    v_int,
    v_rate,
    v_string,
    q_bool,
)

bp = Blueprint("advances", __name__)


ADVANCE_SYSTEM_FIELDS = {
    "id": MISSING,
    "created_at": MISSING,
    "updated_at": MISSING,
    "version": 1,
    "funding_status": "REQUESTED",
    "custody_status": "PENDING_RECEIPT",
    "rejected_reason": None,
    "advance_amount_cents": 0,
    "concentration_capped": False,
    "effective_advance_rate": 0,
    "eligible_collateral_value_cents": 0,
    "required_paydown_cents": 0,
    "outstanding_balance_cents": 0,
    "dwell_days": 0,
    "is_aged": False,
    "funded_at": None,
    "wet_receipt_deadline_at": None,
    "shipped_at": None,
    "purchased_at": None,
    "provisional_advance_amount_cents": MISSING,
}


def _live_bailee_letters(advance_id):
    """Letters still ISSUED whose half-open window covers the logical clock."""
    now = clock.now()
    return [b for b in computed.advance_bailee_letters(advance_id)
            if b["status"] == "ISSUED"
            and b["effective_from"] <= now < b["expires_at"]]


def _advance_investor_ids(advance):
    """The investor identities that may act on this advance: the investor behind
    its commitment, falling back to the investors named on its bailee letters."""
    ids = set()
    commitment = computed.advance_commitment(advance)
    if commitment is not None:
        ids.add(commitment["investor_id"])
    for letter in computed.advance_bailee_letters(advance["id"]):
        ids.add(letter["investor_id"])
    return ids


def _own_advance(user_id, role, advance):
    """Priority 4 for the entity-backed roles addressing one advance."""
    if role == BORROWER and advance["facility_id"] != user_id:
        mismatch()
    if role == CUSTODIAN and advance["custodian_id"] != user_id:
        mismatch()
    if role == INVESTOR and user_id not in _advance_investor_ids(advance):
        mismatch()


# ------------------------------------------------------------------- booking

@bp.post("/advances")
def create_advance():
    require_auth([COLLATERAL_ANALYST, BORROWER])
    data = body()

    # priority 5: every identifier supplied in the body resolves, and resolves
    # within the addressed facility
    facility_id = v_id(data, "facility_id")
    facility = db.facilities.get(facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND",
                       "No such facility: %s" % facility_id)
    custodian_id = v_id(data, "custodian_id")
    custodian = db.custodians.get(custodian_id)
    if custodian is None or custodian["facility_id"] != facility["id"]:
        raise ApiError("ERR_CUSTODIAN_NOT_FOUND",
                       "No such custodian on this facility: %s" % custodian_id)
    commitment = None
    commitment_id = data.get("investor_commitment_id")
    if commitment_id is not None:
        commitment_id = v_id(data, "investor_commitment_id")
        commitment = db.commitments.get(commitment_id)
        if commitment is None or commitment["facility_id"] != facility["id"]:
            raise ApiError("ERR_COMMITMENT_NOT_FOUND",
                           "No such commitment on this facility: %s" % commitment_id)

    # priority 6: the rate row must exist before any schema-independent rule runs
    raw_product = data.get("product_code")
    if isinstance(raw_product, str) and raw_product in PRODUCT_CODES:
        rate_row = computed.rate_row_for(facility["id"], raw_product)
        if rate_row is None:
            raise ApiError("ERR_ADVANCE_RATE_NOT_CONFIGURED",
                           "The facility has no advance rate for %s." % raw_product)

    # priority 7
    reject_system_fields(data, ADVANCE_SYSTEM_FIELDS)
    product_code = v_enum(data, "product_code", PRODUCT_CODES)
    loan_amount_cents = v_int(data, "loan_amount_cents", exclusive_min=0)
    note_rate = v_rate(data, "note_rate", exclusive_min=0, exclusive_max=0.5)
    funding_type = v_enum(data, "funding_type", FUNDING_TYPES)
    payee_name = v_string(data, "payee_name", max_len=200)
    payee_account_last4 = v_digits(data, "payee_account_last4", 4)
    payee_routing_last4 = v_digits(data, "payee_routing_last4", 4)
    # market_value_cents is computed: it initialises to the loan amount, so a
    # supplied value is tolerated only when it echoes that figure
    if data.get("market_value_cents") is not None \
            and data["market_value_cents"] != loan_amount_cents:
        bad("Field 'market_value_cents' is server-owned and may not be supplied.")
    expected_facility_version = v_int(data, "expected_facility_version", minimum=0)

    # priority 8
    if expected_facility_version != facility["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION",
                       "The facility version has moved on.")
    # priority 10
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The facility must be ACTIVE to request an advance.")
    # priority 26
    if custodian["status"] != "APPROVED":
        raise ApiError("ERR_CUSTODIAN_NOT_ACTIVE",
                       "The named custodian is not APPROVED.")
    rate_row = computed.rate_row_for(facility["id"], product_code)
    # priority 28
    if funding_type == "WET" and not rate_row["wet_funding_allowed"]:
        raise ApiError("ERR_WET_FUNDING_NOT_ALLOWED",
                       "Wet funding is not permitted for %s." % product_code)

    advance = base_row()
    advance.update({
        "facility_id": facility["id"],
        "custodian_id": custodian["id"],
        "investor_commitment_id": commitment["id"] if commitment is not None else None,
        "product_code": product_code,
        "loan_amount_cents": loan_amount_cents,
        "note_rate": note_rate,
        "funding_type": funding_type,
        "payee_name": payee_name,
        "payee_account_last4": payee_account_last4,
        "payee_routing_last4": payee_routing_last4,
        "funding_status": "REQUESTED",
        "custody_status": "PENDING_RECEIPT",
        "rejected_reason": None,
        "market_value_cents": loan_amount_cents,
        "provisional_advance_amount_cents": 0,
        "advance_amount_cents": 0,
        "concentration_capped": False,
        "funded_at": None,
        "wet_receipt_deadline_at": None,
        "shipped_at": None,
        "purchased_at": None,
        "_effective_advance_rate": Fraction(0),
        "_eligible_collateral_value_cents": 0,
        "_required_paydown_cents": 0,
    })
    advance["provisional_advance_amount_cents"] = sizing.provisional_amount(
        advance, rate_row, commitment)
    db.advances[advance["id"]] = advance

    # booking also mints the paired funding wire
    wire = base_row()
    wire.update({
        "advance_id": advance["id"],
        "payee_name": payee_name,
        "payee_account_last4": payee_account_last4,
        "payee_routing_last4": payee_routing_last4,
        "amount_cents": advance["provisional_advance_amount_cents"],
        "callback_reference": None,
        "decided_by_user_id": None,
        "status": "PENDING_VERIFICATION",
        "block_reason": None,
    })
    db.wires[wire["id"]] = wire

    # every booking invalidates any facility version token another client holds
    touch(facility)
    return ok(advance_out(advance), 201)


@bp.get("/advances")
def list_advances():
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    rows = by_created_at(list(db.advances.values()))
    if role == BORROWER:
        rows = [a for a in rows if a["facility_id"] == user_id]
    rows = filter_by(rows, "facility_id")
    rows = filter_by(rows, "custodian_id")
    rows = filter_by(rows, "investor_commitment_id")
    rows = filter_by(rows, "product_code")
    rows = filter_by(rows, "funding_type")
    rows = filter_by(rows, "funding_status")
    rows = filter_by(rows, "custody_status")
    aged = q_bool("is_aged")
    if aged is not None:
        rows = [a for a in rows if computed.is_aged(a) == aged]
    return list_response(rows, advance_out)


@bp.get("/advances/<advance_id>")
def read_advance(advance_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, WIRE_OPERATOR,
                                  BORROWER, CUSTODIAN])
    advance = get_advance(advance_id)
    _own_advance(user_id, role, advance)
    return ok(advance_out(advance))


@bp.get("/advances/<advance_id>/wire-instructions")
def list_advance_wires(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, WIRE_OPERATOR])
    advance = get_advance(advance_id)
    rows = filter_by(computed.advance_wires(advance["id"]), "status")
    return list_response(rows, wire_out)


# ------------------------------------------------------------------- funding

@bp.post("/advances/<advance_id>/fund")
def fund_advance(advance_id):
    user_id, _role = require_auth([COLLATERAL_ANALYST, WIRE_OPERATOR])
    advance = get_advance(advance_id)
    body()
    facility = advance_facility(advance)

    # priority 10
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_NOT_ACTIVE",
                       "The facility must be ACTIVE to fund an advance.")
    # priority 11
    if advance["funding_status"] != "REQUESTED":
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a REQUESTED advance may be funded.")
    # priority 19
    wires = computed.advance_wires(advance["id"])
    wire = None
    for candidate in wires:
        if candidate["status"] == "VERIFIED":
            wire = candidate
    if wire is None:
        raise ApiError("ERR_WIRE_NOT_VERIFIED",
                       "The advance has no VERIFIED wire instruction.")
    # priority 20
    if wire["payee_account_last4"] != facility["settlement_account_last4"]:
        raise ApiError("ERR_PAYEE_ACCOUNT_MISMATCH",
                       "The wire payee account does not match the facility "
                       "settlement account.")
    # priority 21
    if wire["decided_by_user_id"] is not None \
            and wire["decided_by_user_id"] == user_id:
        raise ApiError("ERR_DUAL_CONTROL_VIOLATION",
                       "The operator who verified the wire may not release it.")
    # priority 22
    if advance["funding_type"] == "DRY":
        if advance["custody_status"] not in ("RECEIVED_CLEAR", "EXCEPTION_CURED"):
            raise ApiError("ERR_CUSTODY_RECEIPT_REQUIRED",
                           "A dry funding requires the collateral file in hand.")
    elif advance["custody_status"] == "RECEIVED_EXCEPTION":
        raise ApiError("ERR_CUSTODY_RECEIPT_REQUIRED",
                       "An advance with an uncured document exception cannot be "
                       "funded.")
    # priority 26
    custodian = db.custodians[advance["custodian_id"]]
    if custodian["status"] != "APPROVED":
        raise ApiError("ERR_CUSTODIAN_NOT_ACTIVE",
                       "The named custodian is not APPROVED.")

    # priorities 35, 36 and 38 through 43
    provisional, final, capped = sizing.size_advance(advance, facility)

    now = clock.now()
    advance["provisional_advance_amount_cents"] = provisional
    advance["advance_amount_cents"] = final
    advance["concentration_capped"] = capped
    advance["funding_status"] = "FUNDED"
    advance["funded_at"] = now
    if advance["funding_type"] == "WET":
        advance["wet_receipt_deadline_at"] = plus_hours(
            now, custodian["wet_receipt_deadline_hours"])
    post_entry(facility["id"], advance["id"], "ADVANCE_FUNDED", "DEBIT", final,
               "Advance funded")
    commitment = computed.advance_commitment(advance)
    if commitment is not None:
        computed.refresh_commitment_status(commitment)
        touch(commitment)
    wire["status"] = "RELEASED"
    touch(wire)
    computed.store_valuation(advance)
    touch(advance)
    touch(facility)
    return ok(advance_out(advance))


# ------------------------------------------------------------------ receipts

@bp.post("/advances/<advance_id>/receipts")
def create_receipt(advance_id):
    user_id, role = require_auth([CUSTODIAN, COLLATERAL_ANALYST])
    advance = get_advance(advance_id)
    # priority 4
    if role == CUSTODIAN and advance["custodian_id"] != user_id:
        mismatch()
    data = body()
    custodian_id = v_id(data, "custodian_id")
    custodian = db.custodians.get(custodian_id)
    if custodian is None or custodian["facility_id"] != advance["facility_id"]:
        raise ApiError("ERR_CUSTODIAN_NOT_FOUND",
                       "No such custodian on this facility: %s" % custodian_id)
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "received_at": MISSING, "status": MISSING,
                                "cured_exception_codes": [],
                                "advance_id": advance["id"]})
    document_types = v_enum_array(data, "document_types", DOCUMENT_TYPES)
    exception_codes = v_enum_array(data, "exception_codes", EXCEPTION_CODES,
                                   required=False, non_empty=False, default=[])

    # priority 11
    if advance["funding_status"] not in ("REQUESTED", "FUNDED", "SHIPPED"):
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "The advance's funding axis is terminal.")
    # priority 12
    if advance["custody_status"] not in ("PENDING_RECEIPT", "RECEIPT_OVERDUE"):
        raise ApiError("ERR_CUSTODY_INVALID_STATE",
                       "The custody axis does not accept a new receipt.")
    for existing in computed.advance_receipts(advance["id"]):
        if existing["status"] in ("CLEAR", "CURED"):
            raise ApiError("ERR_CUSTODY_INVALID_STATE",
                           "A settled receipt already exists for this advance.")
    # priority 26
    if custodian["status"] != "APPROVED":
        raise ApiError("ERR_CUSTODIAN_NOT_ACTIVE",
                       "The filing custodian is not APPROVED.")

    receipt = base_row()
    receipt.update({
        "advance_id": advance["id"],
        "custodian_id": custodian["id"],
        "document_types": document_types,
        "exception_codes": exception_codes,
        "cured_exception_codes": [],
        "received_at": clock.now(),
        "status": "CLEAR" if not exception_codes else "EXCEPTION",
    })
    db.receipts[receipt["id"]] = receipt

    facility = advance_facility(advance)
    if receipt["status"] == "CLEAR":
        advance["custody_status"] = "RECEIVED_CLEAR"
        touch(advance)
        computed.store_valuation(advance)
        if close_calls(advance["id"], "CUSTODY_EXCEPTION"):
            reevaluate_restricted(facility)
    else:
        advance["custody_status"] = "RECEIVED_EXCEPTION"
        touch(advance)
        result = computed.store_valuation(advance)
        if advance["funding_status"] == "FUNDED" \
                and result["required_paydown_cents"] > 0:
            call = create_margin_call(facility, advance, "CUSTODY_EXCEPTION",
                                      result["required_paydown_cents"])
            if call is not None:
                restrict_if_active(facility)
    return ok(receipt_out(receipt), 201)


@bp.get("/advances/<advance_id>/receipts")
def list_advance_receipts(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, CUSTODIAN])
    advance = get_advance(advance_id)
    rows = filter_by(computed.advance_receipts(advance["id"]), "status")
    return list_response(rows, receipt_out)


# ----------------------------------------------------------------- valuation

@bp.post("/advances/<advance_id>/valuation")
def value_advance(advance_id):
    require_auth([COLLATERAL_ANALYST])
    advance = get_advance(advance_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING})
    market_value_cents = v_int(data, "market_value_cents", exclusive_min=0)
    expected_advance_version = v_int(data, "expected_advance_version", minimum=0)
    # priority 8
    if expected_advance_version != advance["version"]:
        raise ApiError("ERR_STALE_ADVANCE_VERSION",
                       "The advance version has moved on.")
    # priority 11
    if advance["funding_status"] not in ON_BOOK_FUNDING:
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a FUNDED or SHIPPED advance may be marked to market.")

    facility = advance_facility(advance)
    advance["market_value_cents"] = market_value_cents
    touch(advance)
    result = computed.store_valuation(advance)
    if result["required_paydown_cents"] > 0 and not has_open_call(advance["id"]):
        call = create_margin_call(facility, advance, "VALUATION_DECLINE",
                                  result["required_paydown_cents"])
        if call is not None:
            restrict_if_active(facility)
    return ok(advance_out(advance))


# ------------------------------------------------------------------ shipment

@bp.post("/advances/<advance_id>/ship")
def ship_advance(advance_id):
    require_auth([COLLATERAL_ANALYST])
    advance = get_advance(advance_id)
    data = body()
    investor_id = v_id(data, "investor_id")
    investor = get_investor(investor_id)
    if investor["facility_id"] != advance["facility_id"]:
        raise ApiError("ERR_INVESTOR_NOT_FOUND",
                       "No such investor on this facility: %s" % investor_id)

    # priority 11
    if advance["funding_status"] not in ON_BOOK_FUNDING:
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a FUNDED or SHIPPED advance may be shipped.")
    # priority 12 (custody axis must have the file in hand)
    if advance["funding_status"] == "FUNDED" \
            and advance["custody_status"] not in ("RECEIVED_CLEAR",
                                                  "EXCEPTION_CURED"):
        raise ApiError("ERR_CUSTODY_INVALID_STATE",
                       "The collateral file is not in hand.")
    # priority 24: half-open windows, so a letter expiring exactly now is clear
    if _live_bailee_letters(advance["id"]):
        raise ApiError("ERR_BAILEE_WINDOW_OVERLAP",
                       "A live bailee letter already covers this instant.")
    # priority 25
    if investor["status"] != "APPROVED":
        raise ApiError("ERR_INVESTOR_NOT_APPROVED",
                       "The named investor is not APPROVED.")
    # priority 27
    commitment = computed.advance_commitment(advance)
    if commitment is None or commitment["investor_id"] != investor_id:
        raise ApiError("ERR_COMMITMENT_INVESTOR_MISMATCH",
                       "The advance is not allocated to this investor.")
    if has_open_call(advance["id"]):
        raise ApiError("ERR_OPEN_MARGIN_CALL",
                       "The advance has an open margin call.")

    facility = advance_facility(advance)
    now = clock.now()
    period_days = facility["bailee_period_days"]
    letter = base_row()
    letter.update({
        "advance_id": advance["id"],
        "investor_id": investor_id,
        "effective_from": now,
        "expires_at": plus_days(now, period_days),
        "bailee_period_days": period_days,
        "status": "ISSUED",
    })
    db.bailee_letters[letter["id"]] = letter

    advance["funding_status"] = "SHIPPED"
    advance["shipped_at"] = now
    advance["custody_status"] = "RELEASED_TO_INVESTOR"
    touch(advance)
    computed.store_valuation(advance)
    # Shipment creates a new stored resource (the BaileeLetter), so PRD 4 gives
    # it HTTP 201 with that created resource in `data`.
    return ok(bailee_letter_out(letter), 201)


@bp.get("/advances/<advance_id>/bailee-letters")
def list_advance_bailee_letters(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    advance = get_advance(advance_id)
    rows = filter_by(computed.advance_bailee_letters(advance["id"]), "status")
    return list_response(rows, bailee_letter_out)


# --------------------------------------------------------------- the two exits

@bp.post("/advances/<advance_id>/purchase")
def purchase_advance(advance_id):
    user_id, role = require_auth([COLLATERAL_ANALYST, INVESTOR])
    advance = get_advance(advance_id)
    # priority 4
    if role == INVESTOR and user_id not in _advance_investor_ids(advance):
        mismatch()
    data = body()
    v_string(data, "proceeds_reference", required=False, max_len=200)

    # priority 11
    if advance["funding_status"] != "SHIPPED":
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a SHIPPED advance may be purchased.")
    # priority 23
    live = _live_bailee_letters(advance["id"])
    if not live:
        raise ApiError("ERR_BAILEE_LETTER_REQUIRED",
                       "The advance has no live bailee letter.")
    letter = live[-1]
    if role == INVESTOR:
        owned = [b for b in live if b["investor_id"] == user_id]
        if not owned:
            mismatch()
        letter = owned[-1]

    outstanding = computed.advance_outstanding(advance)
    if outstanding <= 0:
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "The advance has no outstanding balance to settle.")

    facility = advance_facility(advance)
    now = clock.now()
    post_entry(facility["id"], advance["id"], "INVESTOR_PROCEEDS", "CREDIT",
               outstanding, "Investor purchase at par outstanding")
    letter["status"] = "HONORED"
    touch(letter)
    advance["purchased_at"] = now
    advance["funding_status"] = "PURCHASED"
    touch(advance)
    computed.store_valuation(advance)
    commitment = computed.advance_commitment(advance)
    if commitment is not None:
        computed.refresh_commitment_status(commitment)
        touch(commitment)
    if close_calls(advance["id"]):
        reevaluate_restricted(facility)
    return ok(advance_out(advance))


@bp.post("/advances/<advance_id>/repurchase")
def repurchase_advance(advance_id):
    require_auth([COLLATERAL_ANALYST, BORROWER])
    advance = get_advance(advance_id)
    data = body()
    payment_amount_cents = v_int(data, "payment_amount_cents", exclusive_min=0)

    # priority 11
    if advance["funding_status"] not in ON_BOOK_FUNDING:
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a FUNDED or SHIPPED advance may be repurchased.")
    outstanding = computed.advance_outstanding(advance)
    # priority 34
    if payment_amount_cents != outstanding:
        raise ApiError("ERR_REPURCHASE_AMOUNT_MISMATCH",
                       "A repurchase must pay the outstanding balance exactly.")

    facility = advance_facility(advance)
    was_shipped = advance["funding_status"] == "SHIPPED"
    post_entry(facility["id"], advance["id"], "REPURCHASE", "CREDIT",
               payment_amount_cents, "Borrower repurchase at par outstanding")
    advance["funding_status"] = "REPURCHASED"
    touch(advance)
    computed.store_valuation(advance)
    if was_shipped:
        for letter in computed.advance_bailee_letters(advance["id"]):
            if letter["status"] != "ISSUED":
                continue
            letter["status"] = "REVOKED"
            touch(letter)
    commitment = computed.advance_commitment(advance)
    if commitment is not None:
        computed.refresh_commitment_status(commitment)
        touch(commitment)
    for demand in computed.advance_demands(advance["id"]):
        if demand["status"] not in ("OPEN", "ESCALATED"):
            continue
        demand["status"] = "SATISFIED"
        touch(demand)
    close_calls(advance["id"])
    reevaluate_restricted(facility)
    touch(facility)
    return ok(advance_out(advance))


# ---------------------------------------------------------- repurchase demands

@bp.post("/advances/<advance_id>/repurchase-demands")
def create_demand(advance_id):
    require_auth([CREDIT_OFFICER, INVESTOR])
    advance = get_advance(advance_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "status": "OPEN", "raised_at": MISSING,
                                "deadline_at": MISSING,
                                "advance_id": advance["id"]})
    reason = v_enum(data, "reason", DEMAND_REASONS)
    # priority 11
    if advance["funding_status"] not in ON_BOOK_FUNDING:
        raise ApiError("ERR_ADVANCE_INVALID_STATE",
                       "Only a FUNDED or SHIPPED advance may be demanded back.")
    now = clock.now()
    demand = base_row()
    demand.update({
        "advance_id": advance["id"],
        "reason": reason,
        "demand_amount_cents": computed.advance_outstanding(advance),
        "raised_at": now,
        "deadline_at": plus_days(now, AGING_RUN_DEMAND_DAYS),
        "status": "OPEN",
    })
    db.demands[demand["id"]] = demand
    return ok(demand_out(demand), 201)


@bp.get("/advances/<advance_id>/repurchase-demands")
def list_advance_demands(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    advance = get_advance(advance_id)
    rows = computed.advance_demands(advance["id"])
    rows = filter_by(rows, "status")
    rows = filter_by(rows, "reason")
    return list_response(rows, demand_out)


# --------------------------------------------------------- advance sub-lists

@bp.get("/advances/<advance_id>/margin-calls")
def list_advance_margin_calls(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    advance = get_advance(advance_id)
    rows = computed.advance_margin_calls(advance["id"])
    rows = filter_by(rows, "status")
    rows = filter_by(rows, "trigger_reason")
    return list_response(rows, margin_call_out)


@bp.get("/advances/<advance_id>/ledger-entries")
def list_advance_ledger(advance_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST])
    advance = get_advance(advance_id)
    rows = computed.advance_ledger(advance["id"])
    rows = filter_by(rows, "entry_type")
    rows = filter_by(rows, "direction")
    return list_response(rows, ledger_entry_out)
