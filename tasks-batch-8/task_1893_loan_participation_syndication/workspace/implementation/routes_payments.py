"""Borrower payments, distribution runs, distribution lines."""
from flask import Blueprint

import errors
from auth import require_roles, body, req_int, req_enum, req_date, is_int
from domain import get_or_404, paginate, apply_filters, maybe_close_facility
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, parse_date
from calc import (
    facility_participants,
    facility_draws,
    servicing_fee,
    prospective_accrued,
    materialize_facility,
    split_pool,
    apply_principal_reduction,
    apply_interest_reduction,
    draw_order,
    draw_accrued_unpaid,
    facility_accrued,
    facility_outstanding,
)

bp = Blueprint("payments", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")
PAYMENT_TYPES = ("REGULAR", "PREPAYMENT")


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# payments
# ---------------------------------------------------------------------------

@bp.post("/payments")
@require_roles("Borrower")
def payment_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    if fac["borrower_id"] != uid:
        raise errors.not_owner("A borrower may only pay its own facility")
    ptype = req_enum(data, "payment_type", PAYMENT_TYPES)
    amount = req_int(data, "amount_cents", minimum=1)
    value_raw, _v = req_date(data, "value_date")
    if fac["status"] not in ("ACTIVE", "IN_DEFAULT", "ACCELERATED"):
        raise errors.invalid_state("Facility is not accepting payments")
    if ptype == "PREPAYMENT" and fac["status"] in ("IN_DEFAULT", "ACCELERATED"):
        raise errors.facility_in_default("Prepayment is blocked while in default")
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "borrower_id": fac["borrower_id"],
            "payment_type": ptype,
            "amount_cents": amount,
            "value_date": value_raw,
            "status": "RECEIVED",
            "received_at": now_ts(),
            "reversed_at": None,
        }
    )
    db["payments"][ent["id"]] = ent
    fac["undistributed_cash_cents"] += amount
    touch(fac)
    return ok(pub(ent), 201)


@bp.get("/payments/<paymentId>")
@require_roles(*READ_ROLES)
def payment_get(uid, role, paymentId):
    return ok(pub(get_or_404("payments", paymentId)))


@bp.get("/payments")
@require_roles(*READ_ROLES)
def payment_list(uid, role):
    items = apply_filters(
        list(db["payments"].values()),
        [("facility_id", "facility_id"), ("borrower_id", "borrower_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/payments/<paymentId>/reverse")
@require_roles("AgentBank")
def payment_reverse(uid, role, paymentId):
    pay = get_or_404("payments", paymentId)
    if pay["status"] not in ("RECEIVED", "ALLOCATED", "REMITTED"):
        raise errors.invalid_state("Payment cannot be reversed from its state")
    fac = db["facilities"][pay["facility_id"]]
    runs = [r for r in db["runs"].values() if r["payment_id"] == pay["id"]]

    if pay["status"] == "RECEIVED":
        fac["undistributed_cash_cents"] -= pay["amount_cents"]
        touch(fac)
    elif pay["status"] == "ALLOCATED":
        # void COMPUTED runs and their PENDING lines; cash already deducted
        for r in runs:
            if r["status"] == "COMPUTED":
                r["status"] = "VOIDED"
                touch(r)
                for ln in db["lines"].values():
                    if ln["run_id"] == r["id"] and ln["status"] == "PENDING":
                        ln["status"] = "VOID"
                        touch(ln)
    else:  # REMITTED clawback
        run = next((r for r in runs if r["status"] == "REMITTED"), None)
        if run is not None:
            # hop 1: lines REMITTED -> CLAWED_BACK
            lines = [ln for ln in db["lines"].values() if ln["run_id"] == run["id"]]
            for ln in lines:
                if ln["status"] == "REMITTED":
                    ln["status"] = "CLAWED_BACK"
                    touch(ln)
            # hop 2: debit participant cumulative ledgers
            for ln in lines:
                p = db["participants"].get(ln["participant_id"])
                if p is None:
                    continue
                p["cumulative_interest_cents"] -= ln["interest_cents"]
                p["cumulative_principal_cents"] -= ln["principal_cents"]
                touch(p)
            # hop 2b: restore draw outstanding / interest from the remit snapshot
            effects = run.get("_remit_effects") or {"draws": {}}
            for did, eff in effects["draws"].items():
                d = db["draws"].get(did)
                if d is None:
                    continue
                d["outstanding_cents"] += eff.get("principal", 0)
                d["_net_distributed"] -= eff.get("interest", 0)
                # roll back the accrual ledger to the pre-run snapshot so the
                # facility ledgers equal their exact pre-payment values
                snap = (run.get("_accrual_snapshot") or {}).get(did)
                if snap is not None:
                    d["_ledger"] = d["_ledger"][: snap["ledger_len"]]
                    d["accrual_as_of_date"] = snap["as_of"]
                d["accrued_unpaid_interest_cents"] = draw_accrued_unpaid(d)
                touch(d)
            # hop 3: facility ledgers restored
            fac["outstanding_principal_cents"] = facility_outstanding(fac)
            fac["accrued_interest_cents"] = facility_accrued(fac)
            touch(fac)
            if fac["status"] == "CLOSED":
                fac["status"] = "ACTIVE"
                touch(fac)

    pay["status"] = "REVERSED"
    pay["reversed_at"] = now_ts()
    touch(pay)
    return ok(pub(pay))


# ---------------------------------------------------------------------------
# distribution runs
# ---------------------------------------------------------------------------

@bp.post("/payments/<paymentId>/distribution_runs")
@require_roles("AgentBank")
def run_create(uid, role, paymentId):
    pay = get_or_404("payments", paymentId)
    data = body()
    if "expected_payment_version" not in data or not is_int(data.get("expected_payment_version")):
        raise errors.invalid_request("expected_payment_version is required")
    expected = data["expected_payment_version"]
    if pay["status"] not in ("RECEIVED", "ALLOCATED"):
        raise errors.invalid_state("Payment cannot accept a new distribution run")
    if expected != pay["version"]:
        raise errors.stale_version()
    fac = db["facilities"][pay["facility_id"]]
    value_date = parse_date(pay["value_date"])

    # pinned order: (1) servicing fee on pre-run outstanding, (2) accrual to
    # value_date, (3) waterfall. Computed prospectively first so a fiscal
    # rejection leaves no mutation behind.
    fee = servicing_fee(fac, pay)
    fee = min(fee, pay["amount_cents"])
    accrued_after = prospective_accrued(fac, value_date)
    remaining = pay["amount_cents"] - fee
    interest_pool = min(remaining, accrued_after)
    remaining -= interest_pool
    principal_pool = remaining
    if principal_pool > fac["outstanding_principal_cents"]:
        raise errors.payment_exceeds_outstanding()

    # --- commit the run -----------------------------------------------------
    # snapshot per-draw accrual state for the reversal path
    snapshot = {}
    for d in facility_draws(fac["id"]):
        if d["status"] == "SETTLED":
            snapshot[d["id"]] = {
                "ledger_len": len(d["_ledger"]),
                "as_of": d["accrual_as_of_date"],
            }
    materialize_facility(fac, value_date)

    # supersede the prior COMPUTED run
    prior = None
    for r in db["runs"].values():
        if r["payment_id"] == pay["id"] and r["status"] == "COMPUTED":
            prior = r
            break
    run_number = 1 + max(
        [r["run_number"] for r in db["runs"].values() if r["payment_id"] == pay["id"]] or [0]
    )

    ent = new_entity()
    ent.update(
        {
            "payment_id": pay["id"],
            "facility_id": fac["id"],
            "run_number": run_number,
            "servicing_fee_cents": fee,
            "interest_pool_cents": interest_pool,
            "principal_pool_cents": principal_pool,
            "agent_retained_cents": 0,
            "status": "COMPUTED",
            "superseded_by_run_id": None,
            "remitted_at": None,
            "_accrual_snapshot": snapshot,
            "_remit_effects": None,
        }
    )
    db["runs"][ent["id"]] = ent

    funded = [p for p in facility_participants(fac["id"]) if p["status"] == "FUNDED"]
    interest_allocs = split_pool(interest_pool, funded)
    principal_allocs = split_pool(principal_pool, funded)
    total_lines = 0
    for p in funded:
        ln = new_entity()
        ln.update(
            {
                "run_id": ent["id"],
                "participant_id": p["id"],
                "interest_cents": interest_allocs[p["id"]],
                "principal_cents": principal_allocs[p["id"]],
                "total_cents": interest_allocs[p["id"]] + principal_allocs[p["id"]],
                "status": "PENDING",
            }
        )
        db["lines"][ln["id"]] = ln
        total_lines += ln["total_cents"]
    ent["agent_retained_cents"] = (interest_pool + principal_pool) - total_lines

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_run_id"] = ent["id"]
        touch(prior)
        for ln in db["lines"].values():
            if ln["run_id"] == prior["id"] and ln["status"] == "PENDING":
                ln["status"] = "VOID"
                touch(ln)

    if pay["status"] == "RECEIVED":
        fac["undistributed_cash_cents"] -= pay["amount_cents"]
    pay["status"] = "ALLOCATED"
    touch(pay)
    fac["last_distribution_value_date"] = pay["value_date"]
    touch(fac)
    return ok(pub(ent), 201)


@bp.get("/distribution_runs/<runId>")
@require_roles(*READ_ROLES)
def run_get(uid, role, runId):
    return ok(pub(get_or_404("runs", runId)))


@bp.get("/distribution_runs")
@require_roles(*READ_ROLES)
def run_list(uid, role):
    items = apply_filters(
        list(db["runs"].values()),
        [
            ("payment_id", "payment_id"),
            ("facility_id", "facility_id"),
            ("status", "status"),
            ("superseded_by_run_id", "superseded_by_run_id"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/distribution_runs/<runId>/remit")
@require_roles("AgentBank")
def run_remit(uid, role, runId):
    run = get_or_404("runs", runId)
    if run["status"] != "COMPUTED":
        raise errors.invalid_state("Only a COMPUTED run can be remitted")
    fac = db["facilities"][run["facility_id"]]
    pay = db["payments"][run["payment_id"]]

    # hop 1: lines PENDING -> REMITTED; run COMPUTED -> REMITTED
    lines = [ln for ln in db["lines"].values() if ln["run_id"] == run["id"]]
    for ln in lines:
        if ln["status"] == "PENDING":
            ln["status"] = "REMITTED"
            touch(ln)
    run["status"] = "REMITTED"
    run["remitted_at"] = now_ts()
    touch(run)

    # hop 2: credit participants; reduce draw principal and interest oldest-first
    for ln in lines:
        p = db["participants"].get(ln["participant_id"])
        if p is None:
            continue
        p["cumulative_interest_cents"] += ln["interest_cents"]
        p["cumulative_principal_cents"] += ln["principal_cents"]
        touch(p)
    principal_applied = apply_principal_reduction(fac, run["principal_pool_cents"])
    interest_applied = apply_interest_reduction(fac, run["interest_pool_cents"])
    effects = {"draws": {}}
    for did, cents in principal_applied.items():
        effects["draws"].setdefault(did, {})["principal"] = cents
    for did, cents in interest_applied.items():
        effects["draws"].setdefault(did, {})["interest"] = cents
    run["_remit_effects"] = effects

    # hop 3: facility aggregates; last_distribution_value_date already set
    fac["outstanding_principal_cents"] = facility_outstanding(fac)
    fac["accrued_interest_cents"] = facility_accrued(fac)
    fac["last_distribution_value_date"] = pay["value_date"]
    touch(fac)

    # hop 4: payment bubble first (the closure rule requires a REMITTED
    # payment), then the facility closure bubble
    if pay["status"] == "ALLOCATED":
        pay["status"] = "REMITTED"
        touch(pay)
    maybe_close_facility(fac)
    return ok(pub(run))


# ---------------------------------------------------------------------------
# distribution lines
# ---------------------------------------------------------------------------

@bp.get("/distribution_lines/<lineId>")
@require_roles(*READ_ROLES)
def line_get(uid, role, lineId):
    return ok(pub(get_or_404("lines", lineId)))


@bp.get("/distribution_lines")
@require_roles(*READ_ROLES)
def line_list(uid, role):
    items = apply_filters(
        list(db["lines"].values()),
        [("run_id", "run_id"), ("participant_id", "participant_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)
