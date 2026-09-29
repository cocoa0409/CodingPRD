"""Grape contracts and their block allocations."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import validation as v
from authz import (ACCOUNTS_PAYABLE_CLERK, GROWER, GROWER_RELATIONS_MANAGER,
                   HARVEST_COORDINATOR, QUALITY_LAB_TECH, SCALE_OPERATOR,
                   auth, own)
from common import (CLOCK, D, add_days, by_created_asc, by_created_desc, cents,
                    fail, new_record, q2, q3, read_body, respond, respond_list,
                    rows, touch)
from lookup import contract_in, contract_writable, find, not_suspended

bp = Blueprint("contract", __name__)

BASIS = ("TONNAGE", "ACREAGE", "BLOCK")
OVER_DELIVERY = ("ACCEPT_AT_CONTRACT", "ACCEPT_AT_SPOT", "REJECT")
SETTLEMENT_BASIS = ("LOAD_BY_LOAD", "WEIGHTED_BLEND")
ALLOCATION_STATES = ("DRAFT", "OFFERED", "ACTIVE")
ZERO3 = Decimal("0.000")


def basis_mismatch(message):
    fail("ERR_BASIS_FIELD_MISMATCH", message)


def bad_plan(message):
    fail("ERR_INVALID_INSTALLMENT_PLAN", message)


def read_installment_plan(body):
    """Rank-7 shape only: presence, array, element objects and JSON types."""
    if "installment_plan" not in body or body["installment_plan"] is None:
        v.bad("installment_plan", "is required")
    raw = body["installment_plan"]
    if not isinstance(raw, list):
        v.bad("installment_plan", "must be an array")
    plan = []
    for index, element in enumerate(raw):
        if not isinstance(element, dict):
            v.bad("installment_plan[%d]" % index, "must be an object")
        label = "installment_plan[%d]" % index
        no = element.get("installment_no")
        if not v._is_int(no):
            v.bad(label + ".installment_no", "must be an integer")
        pct = element.get("pct_of_settlement")
        if isinstance(pct, bool) or not isinstance(pct, (int, Decimal)):
            v.bad(label + ".pct_of_settlement", "must be a number")
        offset = element.get("due_offset_days")
        if not v._is_int(offset):
            v.bad(label + ".due_offset_days", "must be an integer")
        protected = element.get("lien_protected")
        if not isinstance(protected, bool):
            v.bad(label + ".lien_protected", "must be a boolean")
        plan.append({
            "installment_no": int(no),
            "pct_of_settlement": D(pct),
            "due_offset_days": int(offset),
            "lien_protected": protected,
        })
    return plan


def check_installment_plan(plan):
    """Rank-10 internal consistency."""
    if len(plan) < 1 or len(plan) > 6:
        bad_plan("The installment plan must carry 1 to 6 elements.")
    numbers = [element["installment_no"] for element in plan]
    if sorted(numbers) != list(range(1, len(plan) + 1)):
        bad_plan("installment_no values must be exactly 1 through n with no gaps "
                 "and no repeats.")
    for element in plan:
        if element["pct_of_settlement"] <= 0:
            bad_plan("Every pct_of_settlement must be strictly greater than 0.")
    total = Decimal("0")
    for element in plan:
        total += element["pct_of_settlement"]
    if total != Decimal("100.0"):
        bad_plan("The pct_of_settlement values must sum to exactly 100.0.")


# --------------------------------------------------------------------------
# Draft a contract
# --------------------------------------------------------------------------
@bp.post("/grower-relations/grape-contracts")
def create_contract():
    auth(GROWER_RELATIONS_MANAGER)
    body = read_body()

    grower_id = v.req_id(body, "grower_id")
    grower = find("growers", grower_id)
    spec_id = v.req_id(body, "quality_spec_id")
    spec = find("specs", spec_id)

    contract_code = v.req_str(body, "contract_code", 3, 32)
    base_price = v.req_int(body, "base_price_per_ton_cents", minimum=1)
    contract_basis = v.req_enum(body, "contract_basis", BASIS)
    committed_tons = v.opt_num(body, "committed_tons", 3, exclusive_min=0)
    contracted_yield = v.opt_num(body, "contracted_yield_tons_per_acre", 3,
                                 exclusive_min=0)
    over_delivery_policy = v.req_enum(body, "over_delivery_policy", OVER_DELIVERY)
    term_start = v.req_int(body, "term_start_vintage", minimum=2000, maximum=2100)
    term_end = v.req_int(body, "term_end_vintage", minimum=2000, maximum=2100)
    if term_end < term_start:
        v.bad("term_end_vintage", "must be no earlier than term_start_vintage")

    spot_price_pct = v.opt_num(body, "spot_price_pct", 1, exclusive_min=0, maximum=100,
                               default=D("70.0"))
    tolerance_pct = v.opt_num(body, "over_delivery_tolerance_pct", 1, minimum=0,
                              maximum=100, default=D("10.0"))
    settlement_basis = v.opt_enum(body, "settlement_basis", SETTLEMENT_BASIS,
                                  "LOAD_BY_LOAD")
    provisional_pct = v.opt_num(body, "provisional_payment_pct", 1, exclusive_min=0,
                                maximum=100, default=D("60.0"))
    lien_holdback_pct = v.opt_num(body, "lien_holdback_pct", 1, minimum=0, maximum=50,
                                  default=D("5.0"))
    min_pick_notice_hours = v.opt_int(body, "min_pick_notice_hours", minimum=0,
                                      default=48)
    ack_window_hours = v.opt_int(body, "pick_call_ack_window_hours", minimum=1,
                                 default=24)
    evergreen_flag = v.opt_bool(body, "evergreen_flag", False)
    evergreen_term_years = v.opt_int(body, "evergreen_term_years", minimum=1, maximum=5,
                                     default=1)
    termination_notice_days = v.opt_int(body, "termination_notice_days", minimum=1,
                                        default=90)
    plan = read_installment_plan(body)

    # rank 9 -- the basis decides which tonnage field the request must carry
    if contract_basis == "TONNAGE":
        if committed_tons is None:
            basis_mismatch("A TONNAGE contract requires committed_tons.")
        if contracted_yield is not None:
            basis_mismatch("A TONNAGE contract must not carry "
                           "contracted_yield_tons_per_acre.")
    elif contract_basis == "ACREAGE":
        if contracted_yield is None:
            basis_mismatch("An ACREAGE contract requires "
                           "contracted_yield_tons_per_acre.")
        if committed_tons is not None:
            basis_mismatch("An ACREAGE contract must not carry committed_tons.")
    else:
        if committed_tons is not None:
            basis_mismatch("A BLOCK contract must not carry committed_tons.")
        if contracted_yield is not None:
            basis_mismatch("A BLOCK contract must not carry "
                           "contracted_yield_tons_per_acre.")

    # rank 10
    check_installment_plan(plan)

    # rank 11
    for other in rows("contracts"):
        if other["contract_code"] == contract_code:
            fail("ERR_DUPLICATE_CODE",
                 "Contract code '%s' already exists." % contract_code)

    row = new_record("contracts", {
        "grower_id": grower["id"],
        "quality_spec_id": spec["id"],
        "contract_code": contract_code,
        "contract_basis": contract_basis,
        "base_price_per_ton_cents": base_price,
        "committed_tons": committed_tons,
        "contracted_yield_tons_per_acre": contracted_yield,
        "over_delivery_policy": over_delivery_policy,
        "spot_price_pct": spot_price_pct,
        "over_delivery_tolerance_pct": tolerance_pct,
        "settlement_basis": settlement_basis,
        "provisional_payment_pct": provisional_pct,
        "lien_holdback_pct": lien_holdback_pct,
        "min_pick_notice_hours": min_pick_notice_hours,
        "pick_call_ack_window_hours": ack_window_hours,
        "term_start_vintage": term_start,
        "term_end_vintage": term_end,
        "evergreen_flag": evergreen_flag,
        "evergreen_term_years": evergreen_term_years,
        "termination_notice_days": termination_notice_days,
        "installment_plan": plan,
        "lifecycle_status": "DRAFT",
        "renewal_status": "NOT_DUE",
        "offer_round": 0,
        "countered_price_per_ton_cents": None,
        "contract_cap_tons": None,
        "hard_cap_tons": None,
        "cap_scope": None,
        "prompt_pay_credit_cents": 0,
        "lien_holdback_cents": 0,
        "net_payable_cents": 0,
        "settlement_closed_at": None,
        "renewal_window_opens_at": None,
        "renewal_window_closes_at": None,
        "termination_effective_at": None,
        "lien_released_at": None,
    })
    return respond(derive.contract_json(row), 201)


# --------------------------------------------------------------------------
# Negotiation
# --------------------------------------------------------------------------
@bp.post("/grower-relations/grape-contracts/<contract_id>/offer")
def offer_contract(contract_id):
    auth(GROWER_RELATIONS_MANAGER)
    contract = find("contracts", contract_id)
    body = read_body()
    base_price = v.opt_int(body, "base_price_per_ton_cents", minimum=1)

    contract_in(contract, ("DRAFT", "COUNTERED"))
    if int(contract["offer_round"]) >= calc.MAX_OFFER_ROUNDS:
        fail("ERR_MAX_OFFER_ROUNDS_EXCEEDED",
             "The contract has already been offered %d times."
             % calc.MAX_OFFER_ROUNDS)
    not_suspended(find("growers", contract["grower_id"]))

    if base_price is not None:
        contract["base_price_per_ton_cents"] = base_price
    contract["offer_round"] = int(contract["offer_round"]) + 1
    contract["lifecycle_status"] = "OFFERED"
    touch(contract)
    return respond(derive.contract_json(contract))


@bp.post("/grower-relations/grape-contracts/<contract_id>/counter")
def counter_contract(contract_id):
    user_id, role = auth(GROWER)
    contract = find("contracts", contract_id)
    own(user_id, role, contract["grower_id"])
    body = read_body()
    price = v.req_int(body, "counter_base_price_per_ton_cents", minimum=1)

    contract_in(contract, ("OFFERED",))

    contract["countered_price_per_ton_cents"] = price
    contract["lifecycle_status"] = "COUNTERED"
    touch(contract)
    return respond(derive.contract_json(contract))


@bp.post("/grower-relations/grape-contracts/<contract_id>/withdraw-offer")
def withdraw_offer(contract_id):
    auth(GROWER_RELATIONS_MANAGER)
    contract = find("contracts", contract_id)
    contract_in(contract, ("OFFERED",))
    contract["lifecycle_status"] = "WITHDRAWN"
    contract["renewal_status"] = "NOT_RENEWING"
    touch(contract)
    return respond(derive.contract_json(contract))


@bp.post("/grower-relations/grape-contracts/<contract_id>/accept")
def accept_contract(contract_id):
    user_id, role = auth(GROWER)
    contract = find("contracts", contract_id)
    own(user_id, role, contract["grower_id"])

    contract_in(contract, ("OFFERED",))
    allocations = derive.allocations_of_contract(contract["id"])
    if not allocations:
        fail("ERR_NO_ALLOCATIONS",
             "The contract has no block allocations and cannot be accepted.")
    not_suspended(find("growers", contract["grower_id"]))

    tolerance = contract["over_delivery_tolerance_pct"]
    basis = contract["contract_basis"]
    if basis == "BLOCK":
        contract["cap_scope"] = "PER_BLOCK"
        total = ZERO3
        for allocation in allocations:
            block = find("blocks", allocation["block_id"])
            block_cap = q3(D(block["acres"]) * D(block["expected_yield_tons_per_acre"]))
            allocation["block_cap_tons"] = block_cap
            allocation["block_hard_cap_tons"] = calc.inflate(block_cap, tolerance)
            touch(allocation)
            total += block_cap
        cap = q3(total)
    elif basis == "ACREAGE":
        contract["cap_scope"] = "PER_CONTRACT"
        acres = Decimal("0")
        for allocation in allocations:
            acres += D(allocation["allocated_acres"])
        cap = q3(acres * D(contract["contracted_yield_tons_per_acre"]))
    else:
        contract["cap_scope"] = "PER_CONTRACT"
        cap = q3(D(contract["committed_tons"]))

    contract["contract_cap_tons"] = cap
    contract["hard_cap_tons"] = calc.inflate(cap, tolerance)
    cascades.set_renewal_window(contract)
    contract["lifecycle_status"] = "ACTIVE"

    for element in sorted(contract["installment_plan"],
                          key=lambda e: e["installment_no"]):
        new_record("installments", {
            "contract_id": contract["id"],
            "installment_no": element["installment_no"],
            "pct_of_settlement": element["pct_of_settlement"],
            "due_offset_days": element["due_offset_days"],
            "lien_protected": element["lien_protected"],
            "planned_amount_cents": 0,
            "paid_amount_cents": 0,
            "due_at": None,
            "status": "PENDING_SETTLEMENT",
        })

    touch(contract)
    return respond(derive.contract_json(contract))


# --------------------------------------------------------------------------
# Closing the vintage settlement
# --------------------------------------------------------------------------
def finalise_lines(contract):
    """Return the settlement total, having stamped every PROVISIONAL line."""
    provisional = by_created_asc([line for line in derive.lines_of_contract(contract["id"])
                                 if line["status"] == "PROVISIONAL"])

    if contract["settlement_basis"] == "LOAD_BY_LOAD":
        total = 0
        for line in provisional:
            line["final_amount_cents"] = int(line["gross_amount_cents"])
            total += int(line["final_amount_cents"])
    else:
        contract_lines = [line for line in provisional if line["bucket"] == "CONTRACT"]
        over_lines = [line for line in provisional if line["bucket"] != "CONTRACT"]

        blend_tons = ZERO3
        for line in contract_lines:
            blend_tons += D(line["tons"])
        blend_tons = q3(blend_tons)

        bucket_total = 0
        if contract_lines and blend_tons > 0:
            weighted = Decimal("0")
            for line in contract_lines:
                grade = derive.DB["grades"].get(line["quality_grade_id"])
                raw = D(grade["raw_adjustment_pct"]) if grade is not None else Decimal("0")
                weighted += D(line["tons"]) * raw
            blend_raw = q2(weighted / blend_tons)
            spec = derive.DB["specs"][contract["quality_spec_id"]]
            blend = calc.clamp_raw(spec, blend_raw)
            blended_price = cents(D(contract["base_price_per_ton_cents"])
                                 * (Decimal(1) + blend / D(100)))
            bucket_total = cents(D(blended_price) * blend_tons)

            assigned = 0
            for line in contract_lines:
                amount = cents(D(bucket_total) * D(line["tons"]) / blend_tons)
                line["final_amount_cents"] = amount
                assigned += amount
            residual = bucket_total - assigned
            if residual:
                last = contract_lines[-1]
                last["final_amount_cents"] = int(last["final_amount_cents"]) + residual

        total = bucket_total
        for line in over_lines:
            line["final_amount_cents"] = int(line["gross_amount_cents"])
            total += int(line["final_amount_cents"])

    for line in provisional:
        line["status"] = "FINAL"
        touch(line)
    return total


@bp.post("/grower-relations/grape-contracts/<contract_id>/settlement-close")
def close_settlement(contract_id):
    auth(GROWER_RELATIONS_MANAGER)
    contract = find("contracts", contract_id)

    contract_in(contract, ("ACTIVE",))

    tags = derive.tags_of_contract(contract["id"])
    for tag in tags:
        if tag["weigh_status"] == "GROSS_CAPTURED":
            fail("ERR_TAG_WEIGH_STATE_INVALID",
                 "An untared load still sits on the pad and blocks the close.")
    for tag in tags:
        if tag["disposition"] in ("PENDING", "DISPUTED"):
            fail("ERR_TAG_NOT_DISPUTABLE",
                 "An ungraded or contested load blocks the close.")

    if not any(line["status"] == "PROVISIONAL"
               for line in derive.lines_of_contract(contract["id"])):
        fail("ERR_NO_PROVISIONAL_LINES", "The contract has nothing to settle.")

    contract["settlement_closed_at"] = CLOCK.now
    total = finalise_lines(contract)

    money = calc.net_payable_derivation(total, contract["lien_holdback_pct"])
    contract["prompt_pay_credit_cents"] = money["prompt_pay_credit_cents"]
    contract["lien_holdback_cents"] = money["lien_holdback_cents"]
    contract["net_payable_cents"] = money["net_payable_cents"]
    net_payable = money["net_payable_cents"]

    installments = derive.installments_of_contract(contract["id"])
    pending = [i for i in installments if i["status"] == "PENDING_SETTLEMENT"]
    pending.sort(key=lambda i: int(i["installment_no"]))
    assigned = 0
    for installment in pending:
        planned = cents(D(net_payable) * D(installment["pct_of_settlement"]) / D(100))
        installment["planned_amount_cents"] = planned
        installment["due_at"] = add_days(contract["settlement_closed_at"],
                                         installment["due_offset_days"])
        assigned += planned
    if pending:
        residual = net_payable - assigned
        if residual:
            highest = max(pending, key=lambda i: int(i["installment_no"]))
            highest["planned_amount_cents"] = int(highest["planned_amount_cents"]) + residual
    for installment in pending:
        installment["status"] = "SCHEDULED"
        touch(installment)

    contract["lifecycle_status"] = "SETTLED"
    cascades.withdraw_calls(contract, ("ISSUED", "ACKNOWLEDGED", "SUSPENDED_CAP"))
    touch(contract)
    cascades.touch_grower(contract["grower_id"])
    return respond(derive.contract_json(contract))


# --------------------------------------------------------------------------
# Renewal and termination
# --------------------------------------------------------------------------
@bp.post("/grower-relations/grape-contracts/<contract_id>/renew")
def renew_contract(contract_id):
    auth(GROWER_RELATIONS_MANAGER)
    contract = find("contracts", contract_id)
    body = read_body()
    term_years = v.req_int(body, "renewal_term_years", minimum=1)
    renewed_price = v.opt_int(body, "renewed_base_price_per_ton_cents", minimum=1)

    contract_in(contract, ("ACTIVE",))

    closes = contract["renewal_window_closes_at"]
    if contract["renewal_status"] != "RENEWAL_WINDOW_OPEN":
        fail("ERR_RENEWAL_WINDOW_NOT_OPEN",
             "The renewal window is not open (renewal_status is '%s')."
             % contract["renewal_status"])
    if closes is None or not CLOCK.now < closes:
        fail("ERR_RENEWAL_WINDOW_NOT_OPEN", "The renewal window has closed.")

    counters = derive.grower_counters(contract["grower_id"])
    if counters["reliability_score_lifetime"] < calc.RENEWAL_MIN_RELIABILITY_SCORE:
        fail("ERR_RELIABILITY_BELOW_RENEWAL_THRESHOLD",
             "The producer's lifetime reliability score is below the renewal "
             "threshold.")

    contract["term_end_vintage"] = int(contract["term_end_vintage"]) + term_years
    if renewed_price is not None:
        contract["base_price_per_ton_cents"] = renewed_price
    cascades.set_renewal_window(contract)
    contract["renewal_status"] = "RENEWED"
    touch(contract)
    return respond(derive.contract_json(contract))


@bp.post("/grower-relations/grape-contracts/<contract_id>/termination-notice")
def terminate_contract(contract_id):
    auth(GROWER_RELATIONS_MANAGER)
    contract = find("contracts", contract_id)
    body = read_body()
    effective_at = v.req_dt(body, "effective_at")
    v.free_text(body, "reason")

    contract_in(contract, ("ACTIVE",))

    earliest = add_days(CLOCK.now, int(contract["termination_notice_days"]))
    if effective_at < earliest:
        fail("ERR_TERMINATION_NOTICE_TOO_SHORT",
             "effective_at must be at or after the clock plus %d days."
             % int(contract["termination_notice_days"]))

    if derive.outstanding_lien_balance_cents(contract["grower_id"]) != 0:
        fail("ERR_LIEN_OUTSTANDING",
             "The producer's statutory lien balance is not yet clear.")

    contract["termination_effective_at"] = effective_at
    contract["lifecycle_status"] = "TERMINATION_PENDING"
    contract["renewal_status"] = "NOT_RENEWING"
    cascades.withdraw_calls(contract, ("ISSUED", "ACKNOWLEDGED"))
    cascades.cancel_sampling_visits(contract)
    touch(contract)
    return respond(derive.contract_json(contract))


# --------------------------------------------------------------------------
# Contract reads
# --------------------------------------------------------------------------
@bp.get("/grower-relations/grape-contracts/<contract_id>")
def get_contract(contract_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         QUALITY_LAB_TECH, SCALE_OPERATOR, ACCOUNTS_PAYABLE_CLERK,
                         GROWER)
    contract = find("contracts", contract_id)
    own(user_id, role, contract["grower_id"])
    return respond(derive.contract_json(contract))


@bp.get("/grower-relations/grape-contracts")
def list_contracts():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH,
         ACCOUNTS_PAYABLE_CLERK)
    limit, offset = v.pagination()
    grower_id = v.filt("grower_id")
    quality_spec_id = v.filt("quality_spec_id")
    lifecycle_status = v.filt("lifecycle_status")
    renewal_status = v.filt("renewal_status")
    tonnage_status = v.filt("tonnage_status")

    items = rows("contracts")
    if grower_id is not None:
        items = [r for r in items if r["grower_id"] == grower_id]
    if quality_spec_id is not None:
        items = [r for r in items if r["quality_spec_id"] == quality_spec_id]
    if lifecycle_status is not None:
        items = [r for r in items if r["lifecycle_status"] == lifecycle_status]
    if renewal_status is not None:
        items = [r for r in items if r["renewal_status"] == renewal_status]
    if tonnage_status is not None:
        items = [r for r in items
                 if derive.contract_tonnage_status(r) == tonnage_status]
    items = by_created_desc(items)
    total = len(items)
    return respond_list([derive.contract_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


@bp.get("/grower-relations/grape-contracts/<contract_id>/settlement-summary")
def contract_settlement_summary(contract_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, ACCOUNTS_PAYABLE_CLERK, GROWER)
    contract = find("contracts", contract_id)
    own(user_id, role, contract["grower_id"])
    return respond(derive.settlement_summary(contract))


# --------------------------------------------------------------------------
# Contract block allocations
# --------------------------------------------------------------------------
@bp.post("/grower-relations/contract-block-allocations")
def create_allocation():
    auth(GROWER_RELATIONS_MANAGER)
    body = read_body()

    contract_id = v.req_id(body, "contract_id")
    contract = find("contracts", contract_id)
    block_id = v.req_id(body, "block_id")
    block = find("blocks", block_id)

    allocated_acres = v.opt_num(body, "allocated_acres", 3, exclusive_min=0)
    if allocated_acres is not None and allocated_acres > D(block["acres"]):
        v.bad("allocated_acres", "may not exceed the block's own acres")

    # rank 9
    if contract["contract_basis"] == "ACREAGE":
        if allocated_acres is None:
            basis_mismatch("An ACREAGE-basis contract requires allocated_acres.")
    elif allocated_acres is not None:
        basis_mismatch("allocated_acres is only accepted on an ACREAGE-basis "
                       "contract.")

    # rank 11
    for other in rows("allocations"):
        if other["contract_id"] == contract["id"] and other["block_id"] == block["id"]:
            fail("ERR_DUPLICATE_CODE",
                 "This block is already committed to this contract.")

    # rank 20
    contract_in(contract, ALLOCATION_STATES)

    # rank 43
    if block["grower_id"] != contract["grower_id"] or block["status"] == "RETIRED":
        fail("ERR_BLOCK_GROWER_MISMATCH",
             "The block must belong to the contract's producer and must not be "
             "retired.")

    row = new_record("allocations", {
        "contract_id": contract["id"],
        "block_id": block["id"],
        "allocated_acres": allocated_acres,
        "block_cap_tons": None,
        "block_hard_cap_tons": None,
    })
    return respond(derive.allocation_json(row), 201)


@bp.get("/grower-relations/contract-block-allocations/<allocation_id>")
def get_allocation(allocation_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         QUALITY_LAB_TECH, SCALE_OPERATOR, GROWER)
    row = find("allocations", allocation_id)
    contract = find("contracts", row["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.allocation_json(row))


@bp.get("/grower-relations/contract-block-allocations")
def list_allocations():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH,
         SCALE_OPERATOR)
    limit, offset = v.pagination()
    contract_id = v.filt("contract_id")
    block_id = v.filt("block_id")
    items = rows("allocations")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if block_id is not None:
        items = [r for r in items if r["block_id"] == block_id]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.allocation_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)
