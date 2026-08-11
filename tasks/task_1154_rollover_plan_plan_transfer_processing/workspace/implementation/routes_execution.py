"""Case money-movement endpoints: issue-disbursement, confirm-receipt,
execute-transfer, execute-conversion, post-credit (PRD §3.6–§3.8)."""

from flask import Blueprint, g

import errors
from db import clock_date, create_entity, store, touch
from middleware import body, req_enum, require_roles
from response import ok
from routes_cases import get_case_or_404
from services import (
    AGE_THRESHOLD_MONTHS,
    DISB_METHODS,
    SOURCE_ORDER,
    account_total,
    active_loans_of_account,
    age_months_on,
    case_receiving_account,
    case_source_account,
    draft_1099,
    find_or_create_source_row,
    has_verified_verification,
    indirect_withholding,
    maybe_close_account,
    msb_rows_of,
    non_cancelled_disbursement,
    parse_date,
    serialize_case,
    serialize_disbursement,
    source_allocation,
    update_5498,
)

bp = Blueprint("execution", __name__)


def _sod_check(case):
    if case.get("eligibility_decided_by") is not None and g.user_id == case["eligibility_decided_by"]:
        raise errors.err_sod()


def _run_allocation(case, eligible_types):
    """source_allocation + indirect_withholding; locks amounts on the case (PRD §3.6).

    Returns (rows, alloc) where alloc maps row id -> {"amount", "basis"}.
    """
    src = case_source_account(case)
    rows = [
        r
        for r in msb_rows_of(src["id"])
        if r["balance_cents"] > 0 and r["source_type"] in eligible_types
    ]
    if case.get("requested_amount_cents") is not None:
        gross = case["requested_amount_cents"]
    else:
        gross = sum((r["balance_cents"] * r["vested_pct"]) // 100 for r in rows)
    alloc = source_allocation(rows, gross)
    basis_portion = sum(a["basis"] for a in alloc.values())
    taxable = gross - basis_portion
    if case["case_type"] == "INDIRECT_ROLLOVER_OUT":
        withholding = indirect_withholding(taxable)
    else:
        withholding = 0
    case["gross_cents"] = gross
    case["basis_portion_cents"] = basis_portion
    case["taxable_cents"] = taxable
    case["withholding_cents"] = withholding
    case["net_cents"] = gross - withholding
    touch(case)
    return rows, alloc


@bp.post("/v1/rollover-cases/<case_id>/issue-disbursement")
@require_roles("RolloverProcessor")
def issue_disbursement(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    data = body()
    method = req_enum(data, "method", DISB_METHODS)
    if case["status"] != "ELIGIBLE" or case["case_type"] not in ("DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT"):
        raise errors.err_case_invalid_state(
            "Case must be ELIGIBLE and of type DIRECT_ROLLOVER_OUT or INDIRECT_ROLLOVER_OUT"
        )
    _sod_check(case)
    if non_cancelled_disbursement(case["id"]) is not None:
        raise errors.err_disbursement_already_exists()
    if case["case_type"] == "DIRECT_ROLLOVER_OUT" and not has_verified_verification(case["id"], "OUTBOUND"):
        raise errors.err_verification_not_verified()

    src = case_source_account(case)
    rows, alloc = _run_allocation(case, set(SOURCE_ORDER))

    # Full-vested election forfeits the unvested employer remainder (PRD §3.6).
    forfeit = {}
    forfeiture_total = 0
    if case.get("requested_amount_cents") is None:
        for r in rows:
            if r["source_type"] != "EMPLOYER_PRETAX":
                continue
            vested = (r["balance_cents"] * r["vested_pct"]) // 100
            remainder = r["balance_cents"] - vested
            if remainder > 0:
                forfeit[r["id"]] = {"amount": remainder, "basis": 0}
                forfeiture_total += remainder
        if forfeiture_total:
            case["forfeiture_cents"] = forfeiture_total
            touch(case)

    # Ledger sync: debit each source row by its allocation (basis travels pro-rata),
    # then zero the forfeited unvested employer remainder.
    for r in rows:
        a = alloc.get(r["id"])
        f = forfeit.get(r["id"])
        if a:
            r["balance_cents"] -= a["amount"]
            r["basis_cents"] -= a["basis"]
        if f:
            r["balance_cents"] -= f["amount"]
            r["basis_cents"] = min(r["basis_cents"], r["balance_cents"])
        if a or f:
            touch(r)
    touch(src)

    disb = create_entity(
        store.disbursements,
        {
            "rollover_case_id": case["id"],
            "method": method,
            "gross_cents": case["gross_cents"],
            "withholding_cents": case["withholding_cents"],
            "net_cents": case["net_cents"],
            "issued_date": None,
            "status": "PENDING",
        },
    )
    disb["_alloc"] = alloc
    disb["_forfeit"] = forfeit
    return ok(serialize_disbursement(disb))


@bp.post("/v1/rollover-cases/<case_id>/confirm-receipt")
@require_roles("RolloverProcessor")
def confirm_receipt(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    if case["status"] != "DISBURSED" or case["case_type"] != "DIRECT_ROLLOVER_OUT":
        raise errors.err_case_invalid_state(
            "Case must be DISBURSED and of type DIRECT_ROLLOVER_OUT"
        )
    disb = non_cancelled_disbursement(case["id"])
    if disb is None or disb["status"] != "ISSUED":
        raise errors.err_disbursement_invalid_state("Case disbursement is not ISSUED")
    case["status"] = "COMPLETED"
    touch(case)
    maybe_close_account(case_source_account(case))
    return ok(serialize_case(case))


@bp.post("/v1/rollover-cases/<case_id>/execute-transfer")
@require_roles("RolloverProcessor")
def execute_transfer(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    if case["status"] != "ACCEPTANCE_PENDING" or case["case_type"] != "PLAN_TRANSFER":
        raise errors.err_case_invalid_state("Case must be an ACCEPTANCE_PENDING PLAN_TRANSFER")
    _sod_check(case)
    src = case_source_account(case)
    recv = case_receiving_account(case)
    if active_loans_of_account(src["id"]):
        raise errors.err_loans_outstanding()
    # Book-entry move preserving balance/basis/vesting per source, in pinned order;
    # unvested employer money moves too — a transfer is not a distribution (PRD §3.8).
    src_rows = {r["source_type"]: r for r in msb_rows_of(src["id"])}
    moved = False
    for st in SOURCE_ORDER:
        row = src_rows.get(st)
        if row is None or (row["balance_cents"] == 0 and row["basis_cents"] == 0):
            continue
        target = None
        for tr in msb_rows_of(recv["id"]):
            if tr["source_type"] == st:
                target = tr
                break
        if target is None:
            create_entity(
                store.msb,
                {
                    "account_id": recv["id"],
                    "source_type": st,
                    "balance_cents": row["balance_cents"],
                    "basis_cents": row["basis_cents"],
                    "vested_pct": row["vested_pct"],
                },
            )
        else:
            target["balance_cents"] += row["balance_cents"]
            target["basis_cents"] += row["basis_cents"]
            touch(target)
        row["balance_cents"] = 0
        row["basis_cents"] = 0
        touch(row)
        moved = True
    if moved:
        touch(src)
        touch(recv)
    src["status"] = "CLOSED"
    touch(src)
    case["status"] = "COMPLETED"
    touch(case)
    return ok(serialize_case(case))


@bp.post("/v1/rollover-cases/<case_id>/execute-conversion")
@require_roles("RolloverProcessor")
def execute_conversion(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    if case["status"] != "ELIGIBLE" or case["case_type"] != "IN_PLAN_ROTH_CONVERSION":
        raise errors.err_case_invalid_state("Case must be an ELIGIBLE IN_PLAN_ROTH_CONVERSION")
    _sod_check(case)
    src = case_source_account(case)
    rows, alloc = _run_allocation(case, {"PRE_TAX", "AFTER_TAX"})
    # Conversions never withhold.
    case["withholding_cents"] = 0
    case["net_cents"] = case["gross_cents"]
    # Debit elected sources; credit ROTH (converted amounts are tax-paid basis).
    for r in rows:
        a = alloc.get(r["id"])
        if a:
            r["balance_cents"] -= a["amount"]
            r["basis_cents"] -= a["basis"]
            touch(r)
    roth = find_or_create_source_row(src["id"], "ROTH")
    roth["balance_cents"] += case["gross_cents"]
    roth["basis_cents"] += case["gross_cents"]
    touch(roth)
    touch(src)
    participant = store.participants.get(src["participant_id"])
    months = 0
    if participant is not None:
        dob = parse_date(participant["date_of_birth"])
        if dob is not None:
            months = age_months_on(dob, clock_date())
    code = "CODE_7" if months >= AGE_THRESHOLD_MONTHS else "CODE_1"
    draft_1099(
        case_id=case["id"],
        loan_id=None,
        participant_id=src["participant_id"],
        tax_year=clock_date().year,
        gross=case["gross_cents"],
        withholding=0,
        taxable=case["gross_cents"] - case["basis_portion_cents"],
        code=code,
    )
    case["status"] = "COMPLETED"  # irrevocable; terminal
    touch(case)
    maybe_close_account(src)
    return ok(serialize_case(case))


@bp.post("/v1/rollover-cases/<case_id>/post-credit")
@require_roles("RolloverProcessor")
def post_credit(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    data = body()
    for field in ("pre_tax_cents", "roth_cents", "roth_basis_cents", "after_tax_basis_cents"):
        v = data.get(field)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise errors.err_validation("%s must be an integer >= 0" % field)
    pre_tax = data["pre_tax_cents"]
    roth = data["roth_cents"]
    roth_basis = data["roth_basis_cents"]
    after_tax = data["after_tax_basis_cents"]
    if roth_basis > roth:
        raise errors.err_validation("roth_basis_cents must not exceed roth_cents")
    if pre_tax + roth + after_tax <= 0:
        raise errors.err_validation("credit breakdown must total a positive amount")
    if case["status"] != "ACCEPTANCE_PENDING" or case["case_type"] != "ROLLOVER_IN":
        raise errors.err_case_invalid_state("Case must be an ACCEPTANCE_PENDING ROLLOVER_IN")
    _sod_check(case)
    if not has_verified_verification(case["id"], "INBOUND"):
        raise errors.err_verification_not_verified()
    recv = case_receiving_account(case)
    recv_plan = store.plans.get(recv["plan_id"])
    if after_tax > 0 and recv_plan is not None and not recv_plan.get("accepts_after_tax_basis", True):
        raise errors.err_plan_capability("Receiving plan does not accept after-tax basis")

    if pre_tax > 0:
        row = find_or_create_source_row(recv["id"], "PRE_TAX")
        row["balance_cents"] += pre_tax
        touch(row)
    if roth > 0 or roth_basis > 0:
        row = find_or_create_source_row(recv["id"], "ROTH")
        row["balance_cents"] += roth
        row["basis_cents"] += roth_basis
        touch(row)
    if after_tax > 0:
        row = find_or_create_source_row(recv["id"], "AFTER_TAX")
        row["balance_cents"] += after_tax
        row["basis_cents"] += after_tax
        touch(row)
    touch(recv)
    total = pre_tax + roth + after_tax
    update_5498(recv["participant_id"], recv["id"], clock_date().year, total)
    case["status"] = "COMPLETED"
    touch(case)
    return ok(serialize_case(case))
