"""Renewals, price adjustments and product line expansions (PRD 3.8)."""

from flask import Blueprint

import calc
import services
from calc import num
from db import (add_days, create_row, db, get_dt, logical_now, months_between,
                ordered, serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_SUPPLIER, actor_id, commit, require_roles, touch)
from response import created_response, object_response
from routes.common import (AMENDMENT_STATUS, AMENDMENT_TYPE, PRICE_INDEX,
                           fetch, list_endpoint)
from validation import (json_body, read_dec, read_dt, read_id, read_int,
                        read_new_line_items, read_str)

bp = Blueprint("contract_amendments", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_AUDITOR)
DECISION_ACTIONS = ("APPROVE", "REJECT")
WITHDRAWAL_ACTIONS = ("WITHDRAW",)

PAYLOAD_FIELDS = ("requested_term_end", "target_line_item_id",
                  "new_unit_price_cents", "price_index", "index_change_pct",
                  "new_line_items", "expansion_scope_overlap_pct")

REQUIRED_BY_TYPE = {
    "RENEWAL": ("requested_term_end",),
    "PRICE_ADJUSTMENT": ("target_line_item_id", "new_unit_price_cents",
                         "price_index", "index_change_pct"),
    "PRODUCT_LINE_EXPANSION": ("new_line_items", "expansion_scope_overlap_pct"),
}


# =========================================================================
# proposal
# =========================================================================

@bp.route("/coop/contract-amendments", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def create_amendment():
    body = json_body(
        allowed=("contract_id", "amendment_type", "expected_contract_version")
                + PAYLOAD_FIELDS,
        required=("contract_id", "amendment_type", "expected_contract_version"),
    )
    contract_id = read_id(body, "contract_id", required=True)
    amendment_type = read_str(body, "amendment_type", required=True,
                              enum=AMENDMENT_TYPE)
    expected = read_int(body, "expected_contract_version", required=True, minimum=1)
    term_raw, term_dt = read_dt(body, "requested_term_end")
    target_id = read_id(body, "target_line_item_id")
    new_price = read_int(body, "new_unit_price_cents", minimum=0)
    price_index = read_str(body, "price_index", enum=PRICE_INDEX)
    index_change = read_dec(body, "index_change_pct", minimum="0.0000",
                            maximum="1.0000")
    new_lines = read_new_line_items(body)
    overlap = read_dec(body, "expansion_scope_overlap_pct", minimum="0.0000",
                       maximum="1.0000")

    # 5. body foreign keys in entity field order
    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    line = None
    if target_id is not None:
        line = fetch(db.line_items, target_id, "ERR_LINE_ITEM_NOT_FOUND")

    # 7. the acting supplier must own the contract
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 9. optimistic concurrency on the pinned contract version
    if int(expected) != int(contract["version"]):
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version %s does not match the contract's "
             "current version %s" % (expected, contract["version"]))

    # 10. the contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "the master contract is not ACTIVE")

    # 20. a named line must be live
    if line is not None and line["status"] != "ACTIVE":
        fail("ERR_LINE_ITEM_NOT_ACTIVE", "the target price-sheet line is not ACTIVE")

    # 25. the supplier must be QUALIFIED
    supplier = db.suppliers[contract["supplier_id"]]
    if supplier["qualification_status"] != "QUALIFIED":
        fail("ERR_SUPPLIER_NOT_QUALIFIED", "the supplier is not QUALIFIED")

    # 34. a named line must belong to the named contract
    if line is not None and line["contract_id"] != contract_id:
        fail("ERR_LINE_ITEM_CONTRACT_MISMATCH",
             "the target line item does not belong to this contract")

    # 37. the payload block must match amendment_type exactly
    supplied = dict(
        requested_term_end=term_raw,
        target_line_item_id=target_id,
        new_unit_price_cents=new_price,
        price_index=price_index,
        index_change_pct=index_change,
        new_line_items=new_lines,
        expansion_scope_overlap_pct=overlap,
    )
    _check_payload(amendment_type, supplied)

    ceiling = None
    if amendment_type == "RENEWAL":
        # 46. renewal interval arithmetic
        _check_renewal(contract, term_dt)
    elif amendment_type == "PRODUCT_LINE_EXPANSION":
        # 55. the expansion must stay inside the solicited scope
        _check_scope(overlap)
    else:
        # 58. the price adjustment stays within its ceiling and above its floor
        ceiling = _check_price(line, contract, price_index, index_change, new_price)

    # Proposing supersedes any live proposal of the same type on the contract.
    for other in ordered(db.amendments):
        if (other["contract_id"] == contract_id
                and other["amendment_type"] == amendment_type
                and other["status"] == "PROPOSED"):
            other["status"] = "WITHDRAWN"
            touch(other)

    row = create_row(
        db.amendments,
        contract_id=contract_id,
        amendment_type=amendment_type,
        status="PROPOSED",
        requested_term_end=None,
        target_line_item_id=target_id,
        new_unit_price_cents=new_price,
        price_index=price_index,
        index_change_pct=num(index_change) if index_change is not None else None,
        price_ceiling_cents=ceiling,
        new_line_items=new_lines,
        expansion_scope_overlap_pct=num(overlap) if overlap is not None else None,
        effective_from=None,
        proposed_by_user_id=actor_id(),
        decided_by_user_id=None,
        decision_note=None,
    )
    set_dt(row, "requested_term_end", term_raw)
    set_dt(row, "effective_from", None)
    commit()
    return created_response(serialize(row))


def _check_payload(amendment_type, supplied):
    required = REQUIRED_BY_TYPE[amendment_type]
    for field in required:
        if supplied[field] is None:
            fail("ERR_AMENDMENT_PAYLOAD_MISMATCH",
                 "%s requires '%s'" % (amendment_type, field))
    for field in PAYLOAD_FIELDS:
        if field not in required and supplied[field] is not None:
            fail("ERR_AMENDMENT_PAYLOAD_MISMATCH",
                 "'%s' does not belong to a %s amendment" % (field, amendment_type))


def _check_renewal(contract, requested_dt):
    current_end = get_dt(contract, "current_term_end")
    base_start = get_dt(contract, "base_term_start")
    if requested_dt <= current_end:
        fail("ERR_RENEWAL_TERM_NOT_EXTENDING",
             "requested_term_end does not extend the current term")
    if months_between(current_end, requested_dt) > calc.MAX_RENEWAL_EXTENSION_MONTHS:
        fail("ERR_RENEWAL_TERM_TOO_LONG",
             "a renewal may extend the term by at most %d months"
             % calc.MAX_RENEWAL_EXTENSION_MONTHS)
    if months_between(base_start, requested_dt) > calc.MAX_TOTAL_TERM_MONTHS:
        fail("ERR_TOTAL_TERM_EXCEEDS_MAX",
             "the merged term would exceed %d months" % calc.MAX_TOTAL_TERM_MONTHS)


def _check_scope(overlap):
    if overlap < calc.EXPANSION_SCOPE_MIN_PCT:
        fail("ERR_EXPANSION_OUT_OF_SCOPE",
             "expansion_scope_overlap_pct must be at least 0.8000")


def _check_price(line, contract, price_index, index_change, new_price):
    ceiling, _effective = calc.price_ceiling(
        line["base_unit_price_cents"], contract["price_escalation_cap_pct"],
        price_index, index_change)
    if new_price > ceiling:
        fail("ERR_PRICE_ESCALATION_EXCEEDS_CAP",
             "new_unit_price_cents exceeds the %d cent ceiling" % ceiling)
    if new_price < int(line["price_floor_cents"]):
        fail("ERR_PRICE_BELOW_FLOOR",
             "new_unit_price_cents is below the line's price floor")
    return ceiling


# =========================================================================
# reads
# =========================================================================

@bp.route("/coop/contract-amendments", methods=["GET"])
@require_roles(*READ_ROLES)
def list_amendments():
    return list_endpoint(
        lambda: ordered(db.amendments),
        {"contract_id": ("contract_id", None),
         "target_line_item_id": ("target_line_item_id", None),
         "amendment_type": ("amendment_type", AMENDMENT_TYPE),
         "status": ("status", AMENDMENT_STATUS)},
    )


@bp.route("/coop/contract-amendments/<amendment_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_amendment(amendment_id):
    row = fetch(db.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    return object_response(serialize(row))


# =========================================================================
# decision
# =========================================================================

@bp.route("/coop/contract-amendments/<amendment_id>/decision", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def decision(amendment_id):
    body = json_body(allowed=("action", "decision_note"), required=("action",))
    action = read_str(body, "action", required=True, enum=DECISION_ACTIONS)
    note = read_str(body, "decision_note", max_len=500)

    amendment = fetch(db.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    contract = db.contracts[amendment["contract_id"]]
    supplier = db.suppliers[contract["supplier_id"]]

    # 10. approval requires the contract to still be ACTIVE
    if action == "APPROVE" and contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "the master contract is not ACTIVE")

    # 11. the amendment must be PROPOSED
    if amendment["status"] != "PROPOSED":
        fail("ERR_AMENDMENT_NOT_PROPOSED", "the amendment is not PROPOSED")

    # 25. and the supplier still QUALIFIED
    if action == "APPROVE" and supplier["qualification_status"] != "QUALIFIED":
        fail("ERR_SUPPLIER_NOT_QUALIFIED", "the supplier is not QUALIFIED")

    amendment_type = amendment["amendment_type"]
    line = None
    if amendment["target_line_item_id"] is not None:
        line = db.line_items.get(amendment["target_line_item_id"])
    now = logical_now()
    ceiling = amendment["price_ceiling_cents"]

    if action == "APPROVE":
        if amendment_type == "PRICE_ADJUSTMENT":
            # 45. the price-stability window
            last_change = get_dt(line, "last_price_change_at") if line else None
            if last_change is not None:
                if now < add_days(last_change, calc.PRICE_STABILITY_BUFFER_DAYS):
                    fail("ERR_PRICE_WINDOW_TOO_SOON",
                         "the ninety-day price-stability window has not elapsed")
        elif amendment_type == "RENEWAL":
            # 46. renewal interval arithmetic, re-run against today's term
            _check_renewal(contract, get_dt(amendment, "requested_term_end"))
            # 54. renewals are bounded by the contract's allowance
            if int(contract["renewals_used"]) >= int(contract["max_renewals"]):
                fail("ERR_RENEWAL_LIMIT_REACHED",
                     "the contract's renewal allowance is exhausted")
        else:
            # 55. the expansion must stay inside the solicited scope
            _check_scope(calc.D(amendment["expansion_scope_overlap_pct"]))
            # 56. catalogue numbers stay unique within the contract
            taken = services.active_skus(contract["id"])
            for spec in amendment["new_line_items"] or []:
                if spec["sku"] in taken:
                    fail("ERR_DUPLICATE_SKU",
                         "sku %s already exists on this contract" % spec["sku"])
                taken.add(spec["sku"])

        if amendment_type == "PRICE_ADJUSTMENT":
            # 58. the ceiling and the floor, re-run against today's base price
            ceiling = _check_price(line, contract, amendment["price_index"],
                                   calc.D(amendment["index_change_pct"]),
                                   int(amendment["new_unit_price_cents"]))

    if action == "REJECT":
        amendment["status"] = "REJECTED"
        amendment["decided_by_user_id"] = actor_id()
        amendment["decision_note"] = note
        touch(amendment)
        commit()
        return object_response(serialize(amendment))

    amendment["status"] = "APPROVED"
    amendment["price_ceiling_cents"] = ceiling
    set_dt(amendment, "effective_from", now)
    amendment["decided_by_user_id"] = actor_id()
    amendment["decision_note"] = note
    touch(amendment)

    if amendment_type == "RENEWAL":
        set_dt(contract, "current_term_end", amendment["requested_term_end"])
        contract["renewals_used"] = int(contract["renewals_used"]) + 1
        touch(contract)
    elif amendment_type == "PRICE_ADJUSTMENT":
        line["base_unit_price_cents"] = int(amendment["new_unit_price_cents"])
        set_dt(line, "price_effective_from", amendment["effective_from"])
        set_dt(line, "last_price_change_at", amendment["effective_from"])
        line["price_change_count"] = int(line["price_change_count"]) + 1
        touch(line)
    else:
        for spec in amendment["new_line_items"] or []:
            services.build_line_item(contract, spec, "EXPANSION")

    # In every branch the solicitation's documentation package goes stale.
    solicitation = db.solicitations.get(contract["solicitation_id"])
    if solicitation is not None:
        services.mark_audit_stale(solicitation)

    commit()
    return object_response(serialize(amendment))


# =========================================================================
# withdrawal
# =========================================================================

@bp.route("/coop/contract-amendments/<amendment_id>/withdrawal", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def withdrawal(amendment_id):
    body = json_body(allowed=("action", "note"), required=())
    read_str(body, "action", enum=WITHDRAWAL_ACTIONS)
    read_str(body, "note")

    amendment = fetch(db.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    contract = db.contracts[amendment["contract_id"]]

    # 7. the acting supplier must own the contract
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 11. the amendment must be PROPOSED
    if amendment["status"] != "PROPOSED":
        fail("ERR_AMENDMENT_NOT_PROPOSED", "the amendment is not PROPOSED")

    amendment["status"] = "WITHDRAWN"
    touch(amendment)
    commit()
    return object_response(serialize(amendment))
