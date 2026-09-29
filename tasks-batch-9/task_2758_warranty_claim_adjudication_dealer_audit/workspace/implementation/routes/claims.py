"""Claim intake, pricing, the edit engine, adjudication, payment and voiding."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    DEALER_WARRANTY_ADMIN,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
    auth,
    fetch,
    scope,
    scope_body,
)
from routes.common import ALL_ROLES, MANUFACTURER_ROLES, apply_filters, one_decimal, resolve_fk, str_filter
from services import calc, cascade
from util import as_date, dec

bp = Blueprint("claims", __name__)

NARRATIVE_FIELDS = ("complaint_text", "cause_text", "correction_text")


# ---------------------------------------------------------------- shared checks
def narrative_values(data):
    values = {}
    for field in NARRATIVE_FIELDS:
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            util.bad("Field '%s' must be a string." % field)
        values[field] = value
    return values


def check_narrative(values):
    for field in NARRATIVE_FIELDS:
        value = values.get(field)
        if value is None or len(value.strip()) < calc.NARRATIVE_FLOOR_CHARS:
            raise ApiError(
                "ERR_NARRATIVE_INCOMPLETE",
                "Field '%s' must be present and at least %d characters after trimming."
                % (field, calc.NARRATIVE_FLOOR_CHARS),
            )


def check_qty_shape(causal_part_id, qty):
    if causal_part_id is not None:
        if qty < 1:
            util.bad("Field 'claimed_parts_qty' must be at least 1 when a causal part is named.")
    elif qty != 0:
        util.bad("Field 'claimed_parts_qty' must be 0 when no causal part is named.")


def check_duplicate_repair_order(dealer_id, repair_order_number, exclude_id=None):
    for other in db.ordered(db.claims):
        if other["id"] == exclude_id:
            continue
        if other["dealer_id"] != dealer_id or other["status"] not in calc.LIVE_CLAIM_STATUSES:
            continue
        if other["repair_order_number"] == repair_order_number:
            raise ApiError("ERR_DUPLICATE_REPAIR_ORDER", "This repair order number is already on a live claim.")


def check_overlapping_repair(vehicle_id, overlap_group, repair_date, exclude_ids):
    for other in db.ordered(db.claims):
        if other["id"] in exclude_ids:
            continue
        if other["vehicle_id"] != vehicle_id or other["status"] not in calc.LIVE_CLAIM_STATUSES:
            continue
        other_op = db.labor_operations.get(other["labor_operation_id"])
        if other_op is None or other_op["overlap_group"] != overlap_group:
            continue
        if abs((repair_date - as_date(other["repair_date"])).days) <= calc.OVERLAP_BUFFER_DAYS:
            raise ApiError(
                "ERR_OVERLAPPING_REPAIR_CLAIM",
                "Another live claim on this vehicle in the same overlap group lies within %d days."
                % calc.OVERLAP_BUFFER_DAYS,
            )


def check_causal_part(operation, part, qty):
    if operation["requires_causal_part"]:
        if part is None:
            raise ApiError("ERR_CAUSAL_PART_REQUIRED", "This labor operation requires a causal part.")
        if part["failure_group"] != operation["causal_failure_group"]:
            raise ApiError(
                "ERR_CAUSAL_PART_REQUIRED",
                "The causal part's failure group does not match the operation's causal failure group.",
            )
        if qty < 1:
            raise ApiError("ERR_CAUSAL_PART_REQUIRED", "At least one unit of the causal part must be claimed.")
    elif part is not None:
        raise ApiError("ERR_CAUSAL_PART_REQUIRED", "This labor operation does not accept a causal part.")


def check_labor_time(hours, operation, field):
    if dec(hours) > dec(operation["max_time_hours"]):
        raise ApiError(
            "ERR_LABOR_TIME_EXCEEDS_MAX",
            "Field '%s' exceeds the operation's maximum of %s hours." % (field, operation["max_time_hours"]),
        )


def run_provisional_pricing(claim, dealer, part):
    labor, parts, total = calc.price(
        dealer["approved_labor_rate_cents"],
        dealer["approved_parts_markup_pct"],
        claim["claimed_labor_hours"],
        claim["claimed_parts_qty"],
        part,
    )
    claim["provisional_labor_amount_cents"] = labor
    claim["provisional_parts_amount_cents"] = parts
    claim["provisional_total_cents"] = total


def run_edit_engine(claim, operation):
    for edit_code, severity, detail, conflicting in calc.claim_edit_engine(claim, operation):
        cascade.append_edit(claim, edit_code, severity, detail, conflicting)
    claim["suspend_edit_count"] = len(cascade.open_suspend_edits(claim["id"]))
    claim["status"] = "SUSPENDED" if claim["suspend_edit_count"] > 0 else "SUBMITTED"


# ---------------------------------------------------------------- submission
@bp.post("/warranty/claims")
def submit_claim():
    actor = auth(DEALER_WARRANTY_ADMIN)
    data = util.body()
    scope_body(actor, data, "dealer_id")
    dealer = resolve_fk(data, "dealer_id", db.dealers, "ERR_DEALER_NOT_FOUND")
    vehicle = resolve_fk(data, "vehicle_id", db.vehicles, "ERR_VEHICLE_NOT_FOUND")
    operation = resolve_fk(data, "labor_operation_id", db.labor_operations, "ERR_LABOR_OPERATION_NOT_FOUND")
    part = resolve_fk(data, "causal_part_id", db.parts, "ERR_CATALOG_ITEM_NOT_FOUND")
    predecessor = resolve_fk(data, "resubmission_of_claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    # ---- body shape ----
    util.get_str(data, "dealer_id")
    util.get_str(data, "vehicle_id")
    util.get_str(data, "labor_operation_id")
    causal_part_id = util.get_str(data, "causal_part_id", required=False)
    resubmission_of_claim_id = util.get_str(data, "resubmission_of_claim_id", required=False)
    repair_order_number = util.get_str(data, "repair_order_number")
    repair_date = util.get_date(data, "repair_date")
    odometer_at_repair = util.get_int(data, "odometer_at_repair", minimum=0)
    claimed_labor_hours = one_decimal(util.get_dec(data, "claimed_labor_hours"), "claimed_labor_hours")
    if claimed_labor_hours <= 0:
        util.bad("Field 'claimed_labor_hours' must be strictly positive.")
    claimed_parts_qty = util.get_int(data, "claimed_parts_qty", minimum=0)
    narratives = narrative_values(data)
    check_qty_shape(causal_part_id, claimed_parts_qty)
    # ---- dealer posture ----
    if dealer["status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED", "A suspended dealer may not submit claims.")
    # ---- collision rules, then narrative, causal part and labor time ----
    check_duplicate_repair_order(dealer["id"], repair_order_number)
    exempt = {predecessor["id"]} if predecessor is not None else set()
    check_overlapping_repair(data["vehicle_id"], operation["overlap_group"], repair_date, exempt)
    check_narrative(narratives)
    check_causal_part(operation, part, claimed_parts_qty)
    check_labor_time(claimed_labor_hours, operation, "claimed_labor_hours")
    # ---- create ----
    claim = db.new_record(
        db.claims,
        dealer_id=dealer["id"],
        vehicle_id=vehicle["id"],
        labor_operation_id=operation["id"],
        causal_part_id=causal_part_id,
        resubmission_of_claim_id=resubmission_of_claim_id,
        repair_order_number=repair_order_number,
        repair_date=repair_date.isoformat(),
        odometer_at_repair=odometer_at_repair,
        claimed_labor_hours=claimed_labor_hours,
        claimed_parts_qty=claimed_parts_qty,
        complaint_text=narratives["complaint_text"],
        cause_text=narratives["cause_text"],
        correction_text=narratives["correction_text"],
        coverage_type="NONE",
        status="SUBMITTED",
        payment_status="UNPAID",
        provisional_labor_amount_cents=0,
        provisional_parts_amount_cents=0,
        provisional_total_cents=0,
        approved_labor_hours=None,
        approved_parts_qty=None,
        approved_labor_amount_cents=None,
        approved_parts_amount_cents=None,
        approved_total_cents=None,
        dealer_participation_cents=0,
        oem_payable_cents=None,
        debited_amount_cents=0,
        reinstated_amount_cents=0,
        suspend_edit_count=0,
        void_reason=None,
        denial_reason=None,
    )
    claim["coverage_type"] = calc.claim_coverage_determination(claim, vehicle, operation)
    run_provisional_pricing(claim, dealer, part)
    run_edit_engine(claim, operation)
    # ---- parts-return obligation ----
    if part is not None and part["return_required"]:
        created = db.now()
        due = db.add_days(created, part["retention_days"])
        row = db.new_record(
            db.parts_returns,
            claim_id=claim["id"],
            part_id=part["id"],
            due_date=db.iso3(due),
            received_date=None,
            status="REQUESTED",
            analysis_result=None,
            analysis_note=None,
            debit_amount_cents=0,
            reversed_amount_cents=0,
        )
        row["_due_dt"] = due
        dealer["open_parts_return_count"] = dealer["open_parts_return_count"] + 1
        db.touch(dealer)
    return response.created(claim)


# ---------------------------------------------------------------- reads
@bp.get("/warranty/claims/<claim_id>")
def read_claim(claim_id):
    actor = auth(*ALL_ROLES)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    scope(actor, claim["dealer_id"])
    return response.ok(claim)


@bp.get("/warranty/claims")
def list_claims():
    auth(*MANUFACTURER_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.claims)
    rows = apply_filters(
        rows,
        [
            (str_filter("dealer_id"), "dealer_id"),
            (str_filter("vehicle_id"), "vehicle_id"),
            (str_filter("labor_operation_id"), "labor_operation_id"),
            (str_filter("causal_part_id"), "causal_part_id"),
            (str_filter("resubmission_of_claim_id"), "resubmission_of_claim_id"),
            (str_filter("status"), "status"),
            (str_filter("payment_status"), "payment_status"),
            (str_filter("coverage_type"), "coverage_type"),
        ],
    )
    date_from = util.date_filter("repair_date_from")
    date_to = util.date_filter("repair_date_to")
    if date_from is not None:
        rows = [row for row in rows if as_date(row["repair_date"]) >= date_from]
    if date_to is not None:
        rows = [row for row in rows if as_date(row["repair_date"]) <= date_to]
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.get("/warranty/claims/<claim_id>/edits")
def list_claim_edits(claim_id):
    actor = auth(
        WARRANTY_ADMIN,
        CLAIM_ADJUDICATOR,
        ADJUDICATION_MANAGER,
        FIELD_AUDITOR,
        AUDIT_MANAGER,
        DEALER_WARRANTY_ADMIN,
    )
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    scope(actor, claim["dealer_id"])
    limit, offset = util.pagination()
    rows = cascade.edits_of(claim_id)
    rows = apply_filters(rows, [(str_filter("edit_code"), "edit_code"), (str_filter("severity"), "severity")])
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


# ---------------------------------------------------------------- correction
@bp.post("/warranty/claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    actor = auth(DEALER_WARRANTY_ADMIN)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    scope(actor, claim["dealer_id"])
    data = util.body()
    dealer = db.dealers[claim["dealer_id"]]
    operation = db.labor_operations[claim["labor_operation_id"]]
    part = db.parts.get(claim["causal_part_id"]) if claim["causal_part_id"] else None
    # ---- body shape ----
    claimed_labor_hours = one_decimal(util.get_dec(data, "claimed_labor_hours"), "claimed_labor_hours")
    if claimed_labor_hours <= 0:
        util.bad("Field 'claimed_labor_hours' must be strictly positive.")
    claimed_parts_qty = util.get_int(data, "claimed_parts_qty", minimum=0)
    narratives = narrative_values(data)
    check_qty_shape(claim["causal_part_id"], claimed_parts_qty)
    # ---- state, then posture ----
    if claim["status"] != "SUSPENDED" or claim["payment_status"] != "UNPAID":
        raise ApiError(
            "ERR_CLAIM_NOT_RESUBMITTABLE",
            "Only a SUSPENDED, UNPAID claim may be corrected in place.",
        )
    if dealer["status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED", "A suspended dealer may not correct claims.")
    # ---- the four intake rules, re-applied ----
    check_duplicate_repair_order(dealer["id"], claim["repair_order_number"], exclude_id=claim["id"])
    exempt = {claim["id"]}
    if claim["resubmission_of_claim_id"]:
        exempt.add(claim["resubmission_of_claim_id"])
    check_overlapping_repair(
        claim["vehicle_id"], operation["overlap_group"], as_date(claim["repair_date"]), exempt
    )
    check_narrative(narratives)
    check_causal_part(operation, part, claimed_parts_qty)
    check_labor_time(claimed_labor_hours, operation, "claimed_labor_hours")
    # ---- overwrite, resolve, re-run ----
    claim["claimed_labor_hours"] = claimed_labor_hours
    claim["claimed_parts_qty"] = claimed_parts_qty
    for field in NARRATIVE_FIELDS:
        claim[field] = narratives[field]
    cascade.resolve_open_edits(claim)
    vehicle = db.vehicles[claim["vehicle_id"]]
    claim["coverage_type"] = calc.claim_coverage_determination(claim, vehicle, operation)
    run_provisional_pricing(claim, dealer, part)
    run_edit_engine(claim, operation)
    db.touch(claim)
    return response.ok(claim)


# ---------------------------------------------------------------- adjudication
def approved_goodwill(claim_id):
    for row in reversed(db.ordered(db.goodwill_auths)):
        if row["claim_id"] == claim_id and row["status"] == "APPROVED":
            return row
    return None


def goodwill_decider_ids(claim_id):
    return {
        row["decided_by_user_id"]
        for row in db.goodwill_auths.values()
        if row["claim_id"] == claim_id and row["decided_by_user_id"]
    }


def run_final_pricing(claim, dealer, operation, part):
    profile = db.state_law_profiles[dealer["state_law_profile_id"]]
    markup = min(dec(dealer["approved_parts_markup_pct"]), dec(profile["markup_cap_pct"]))
    hours = min(dec(claim["approved_labor_hours"]), dec(operation["standard_time_hours"]))
    labor, parts, unadjusted = calc.price(
        dealer["approved_labor_rate_cents"], markup, hours, claim["approved_parts_qty"], part
    )
    claim["approved_labor_amount_cents"] = labor
    claim["approved_parts_amount_cents"] = parts
    if claim["coverage_type"] == "GOODWILL":
        auth_row = approved_goodwill(claim["id"])
        if auth_row is not None:
            total = min(unadjusted, int(auth_row["approved_amount_cents"]))
            participation = util.rhu(dec(total) * dec(auth_row["policy_adjustment_pct"]))
        else:
            total, participation = unadjusted, 0
    else:
        total, participation = unadjusted, 0
    claim["approved_total_cents"] = total
    claim["dealer_participation_cents"] = participation
    claim["oem_payable_cents"] = total - participation


@bp.post("/warranty/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    actor = auth(CLAIM_ADJUDICATOR, ADJUDICATION_MANAGER)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if actor.user_id in goodwill_decider_ids(claim["id"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who decided a goodwill authorization on this claim may not adjudicate it.",
        )
    data = util.body()
    decision = util.get_enum(data, "decision", ("APPROVE", "DENY"))
    approved_labor_hours = None
    approved_parts_qty = None
    denial_reason = None
    if decision == "APPROVE":
        approved_labor_hours = one_decimal(util.get_dec(data, "approved_labor_hours"), "approved_labor_hours")
        if approved_labor_hours < 0:
            util.bad("Field 'approved_labor_hours' must not be negative.")
        approved_parts_qty = util.get_int(data, "approved_parts_qty", minimum=0)
        if approved_parts_qty > claim["claimed_parts_qty"]:
            util.bad("Field 'approved_parts_qty' may not exceed the claimed quantity.")
    else:
        denial_reason = util.get_str(data, "denial_reason")
    # ---- state ----
    if claim["status"] not in ("SUBMITTED", "SUSPENDED"):
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE", "Only a SUBMITTED or SUSPENDED claim may be adjudicated.")
    if decision == "APPROVE" and any(
        edit["edit_code"] == "DEALER_POSTURE_HOLD" for edit in cascade.open_suspend_edits(claim["id"])
    ):
        raise ApiError(
            "ERR_CLAIM_STILL_SUSPENDED",
            "An open DEALER_POSTURE_HOLD is lifted only by the dealer's balance recovering.",
        )
    dealer = db.dealers[claim["dealer_id"]]
    operation = db.labor_operations[claim["labor_operation_id"]]
    part = db.parts.get(claim["causal_part_id"]) if claim["causal_part_id"] else None
    if decision == "APPROVE":
        check_labor_time(approved_labor_hours, operation, "approved_labor_hours")
        if claim["coverage_type"] == "NONE":
            raise ApiError(
                "ERR_NO_COVERAGE_WITHOUT_GOODWILL",
                "A claim with no coverage needs an APPROVED goodwill authorization before approval.",
            )
        claim["approved_labor_hours"] = approved_labor_hours
        claim["approved_parts_qty"] = approved_parts_qty
        run_final_pricing(claim, dealer, operation, part)
        cascade.resolve_open_edits(claim)
        claim["suspend_edit_count"] = 0
        claim["status"] = "APPROVED"
        db.touch(claim)
    else:
        claim["denial_reason"] = denial_reason
        cascade.resolve_open_edits(claim)
        claim["suspend_edit_count"] = 0
        claim["status"] = "DENIED"
        db.touch(claim)
        cascade.waive_open_returns(claim, dealer)
    return response.ok(claim)


# ---------------------------------------------------------------- voiding
@bp.post("/warranty/claims/<claim_id>/void")
def void_claim(claim_id):
    auth(WARRANTY_ADMIN, CLAIM_ADJUDICATOR)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = util.body()
    void_reason = util.get_str(data, "void_reason")
    voidable = claim["status"] in ("SUBMITTED", "SUSPENDED") or (
        claim["status"] == "APPROVED" and claim["payment_status"] == "UNPAID"
    )
    if not voidable:
        raise ApiError(
            "ERR_CLAIM_NOT_VOIDABLE",
            "Only a SUBMITTED or SUSPENDED claim, or an APPROVED claim still UNPAID, may be voided.",
        )
    dealer = db.dealers[claim["dealer_id"]]
    claim["void_reason"] = void_reason
    cascade.resolve_open_edits(claim)
    claim["suspend_edit_count"] = 0
    claim["status"] = "VOID"
    db.touch(claim)
    cascade.waive_open_returns(claim, dealer)
    return response.ok(claim)


# ---------------------------------------------------------------- payment
@bp.post("/warranty/claims/<claim_id>/pay")
def pay_claim(claim_id):
    auth(WARRANTY_ADMIN)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "APPROVED" or claim["payment_status"] != "UNPAID" or claim["suspend_edit_count"] != 0:
        raise ApiError(
            "ERR_CLAIM_NOT_PAYABLE",
            "Only an APPROVED, UNPAID claim with no open suspending edit may be paid.",
        )
    dealer = db.dealers[claim["dealer_id"]]
    if dealer["status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED", "A suspended dealer may not be paid.")
    if dealer["audit_hold"]:
        raise ApiError("ERR_DEALER_UNDER_AUDIT_HOLD", "Payment is frozen while this dealer is under audit.")
    clock = db.now()
    for row in cascade.returns_of_claim(claim["id"]):
        if row["status"] == "REQUESTED" and clock >= row["_due_dt"]:
            raise ApiError(
                "ERR_PARTS_RETURN_OVERDUE",
                "A parts-return obligation on this claim is overdue; run the non-return sweep first.",
            )
    claim["payment_status"] = "PAID"
    db.touch(claim)
    return response.ok(claim)
