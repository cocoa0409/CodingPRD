"""Revenue distribution runs: compute, settle, void."""
from decimal import Decimal

from flask import Blueprint

from db import DB, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok
from services import (
    LEVY_HIGH_PCT,
    LEVY_LOW_PCT,
    LEVY_TIER_THRESHOLD_CENTS,
    base_entity,
    run_view,
)
from util import body, req_dt, round_half_up_cents

bp = Blueprint("distribution", __name__)


def _get_run(rid):
    r = DB["distribution_runs"].get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Distribution run does not exist")
    return r


@bp.post("/pilotage/distribution-runs")
def create_run():
    auth(["FinanceOfficer"])
    data = body()
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "period_end must be strictly after period_start",
        )

    # Half-open window overlap against existing COMPUTED/SETTLED runs
    # (priority 21); adjacency (new start == existing end) is allowed.
    for r in DB["distribution_runs"].values():
        if r["status"] not in ("COMPUTED", "SETTLED"):
            continue
        if period_start < r["period_end"] and period_end > r["period_start"]:
            raise ApiError(
                "ERR_PERIOD_OVERLAP",
                409,
                "Distribution window overlaps an existing run window",
            )

    # Pool: FINALIZED invoices with finalized_at in [period_start, period_end).
    pool = [
        i
        for i in DB["invoices"].values()
        if i["status"] == "FINALIZED"
        and i["finalized_at"] is not None
        and period_start <= i["finalized_at"] < period_end
    ]
    if not pool:
        raise ApiError(
            "ERR_EMPTY_DISTRIBUTION_POOL",
            422,
            "No FINALIZED invoices fall inside the requested window",
        )
    pool.sort(key=lambda i: (i["created_at"], i["_seq"]))

    gross = sum(i["total_cents"] for i in pool)

    # Pinned anti-circular order: the levy tier keys on the gross pool BEFORE
    # any deduction; the levy is computed; net = gross - levy.
    levy_pct = LEVY_HIGH_PCT if gross >= LEVY_TIER_THRESHOLD_CENTS else LEVY_LOW_PCT
    levy = round_half_up_cents(Decimal(gross) * levy_pct)
    net = gross - levy

    # Eligible pilots: the distinct pilots behind the pooled invoices (via
    # their assignments), ordered by pilot created_at ascending.
    pilot_ids = []
    for inv in pool:
        assignment = DB["assignments"].get(inv["assignment_id"])
        if assignment is None:
            continue
        pid = assignment["pilot_id"]
        if pid not in pilot_ids:
            pilot_ids.append(pid)
    pilots = [DB["pilots"][pid] for pid in pilot_ids if pid in DB["pilots"]]
    pilots.sort(key=lambda p: (p["created_at"], p["_seq"]))

    total_units = sum(p["share_units"] for p in pilots)

    # Per-share round_half_up FIRST, then reconcile the remainder one cent
    # per pass (positive: created_at ASC; negative: created_at DESC).
    shares = []
    for p in pilots:
        raw = Decimal(net) * Decimal(p["share_units"]) / Decimal(total_units)
        shares.append(
            {
                "pilot_id": p["id"],
                "share_units": p["share_units"],
                "share_cents": round_half_up_cents(raw),
            }
        )
    remainder = net - sum(s["share_cents"] for s in shares)
    if remainder > 0:
        idx = 0
        while remainder > 0:
            shares[idx % len(shares)]["share_cents"] += 1
            remainder -= 1
            idx += 1
    elif remainder < 0:
        idx = 0
        while remainder < 0:
            shares[len(shares) - 1 - (idx % len(shares))]["share_cents"] -= 1
            remainder += 1
            idx += 1

    run = base_entity()
    run.update(
        {
            "period_start": period_start,
            "period_end": period_end,
            "gross_pool_cents": gross,
            "levy_cents": levy,
            "net_pool_cents": net,
            "shares": shares,
            "invoice_ids": [i["id"] for i in pool],
            "status": "COMPUTED",
        }
    )
    DB["distribution_runs"][run["id"]] = run
    return ok(run_view(run), status=201)


@bp.get("/pilotage/distribution-runs/<rid>")
def get_run(rid):
    auth(ANY_ROLE)
    return ok(run_view(_get_run(rid)))


@bp.post("/pilotage/distribution-runs/<rid>/settle")
def settle_run(rid):
    auth(["FinanceOfficer"])
    run = _get_run(rid)
    if run["status"] != "COMPUTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Distribution run cannot be settled from {run['status']}",
        )
    # Sweep every snapshotted invoice FINALIZED -> DISTRIBUTED and advance the
    # assignment billing dimension INVOICED -> SETTLED.
    for invoice_id in run["invoice_ids"]:
        invoice = DB["invoices"].get(invoice_id)
        if invoice is None or invoice["status"] != "FINALIZED":
            continue
        invoice["status"] = "DISTRIBUTED"
        touch(invoice)
        assignment = DB["assignments"].get(invoice["assignment_id"])
        if assignment is not None and assignment["billing_status"] == "INVOICED":
            assignment["billing_status"] = "SETTLED"
            touch(assignment)
    run["status"] = "SETTLED"
    touch(run)
    return ok(run_view(run))


@bp.post("/pilotage/distribution-runs/<rid>/void")
def void_run(rid):
    auth(["FinanceOfficer"])
    run = _get_run(rid)
    if run["status"] != "COMPUTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Distribution run cannot be voided from {run['status']}",
        )
    # Compensation: no invoice or assignment mutation — swept invoices remain
    # FINALIZED and the run's reservation is released.
    run["status"] = "VOID"
    touch(run)
    return ok(run_view(run))
