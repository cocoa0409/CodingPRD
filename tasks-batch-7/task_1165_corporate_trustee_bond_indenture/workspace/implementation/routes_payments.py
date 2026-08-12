"""Routes: PaymentRun and DistributionRecord (PRD 3.4)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, check_issuer_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_INDENTURE_NOT_ACTIVE,
                    ERR_PERIOD_OVERLAP, ERR_NOTICE_PERIOD_SHORT,
                    ERR_FUNDING_SHORTFALL, ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, now_iso, mutate, touch, fmt_ts
from validate import (req_str, req_int, req_enum, req_date, opt_date,
                      parse_date_strict, is_int)
from calc import compute_interest_gross, pro_rata_allocation
from domain import (positions_of_tranche, records_of_run,
                    recompute_tranche_outstanding,
                    recompute_indenture_outstanding,
                    recompute_all_account_totals, bubble_up_satisfaction)

bp = Blueprint("payments", __name__)

REDEMPTION_TYPES = ("SINKING_FUND_REDEMPTION", "FULL_REDEMPTION", "FINAL_MATURITY")


def _active_positions(tranche_id):
    return sorted(
        [p for p in positions_of_tranche(tranche_id) if p["status"] == "ACTIVE"],
        key=lambda p: (p["created_at"], -p["original_principal_cents"]))


# ---------------------------------------------------------------------------
# PaymentRun
# ---------------------------------------------------------------------------

@bp.route("/payment-runs", methods=["POST"])
@require_roles("TrustOfficer")
def create_payment_run():
    body = get_body()
    with LOCK:
        # Rule 4: tranche reference must exist.
        tranche_id = body.get("tranche_id")
        tr = DB["tranches"].get(tranche_id) if isinstance(tranche_id, str) else None
        if tr is None:
            raise_err(ERR_NOT_FOUND, "Tranche not found")
        # Rule 5: tranche must be ACTIVE.
        if tr["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE,
                      "Payment runs may be scheduled only on ACTIVE tranches")
        ptype = body.get("payment_type")
        start = body.get("period_start_date")
        end = body.get("period_end_date")
        sched = body.get("scheduled_payment_date")
        # Rule 10: INTEREST window half-open non-overlap vs non-REVERSED runs.
        if (ptype == "INTEREST"
                and parse_date_strict(start) is not None
                and parse_date_strict(end) is not None):
            s1, e1 = parse_date_strict(start), parse_date_strict(end)
            for r in DB["payment_runs"].values():
                if (r["tranche_id"] == tr["id"]
                        and r["payment_type"] == "INTEREST"
                        and r["distribution_status"] != "REVERSED"):
                    s2 = parse_date_strict(r.get("period_start_date"))
                    e2 = parse_date_strict(r.get("period_end_date"))
                    if s2 is None or e2 is None:
                        continue
                    if s1 < e2 and s2 < e1:  # half-open overlap; adjacency OK
                        raise_err(ERR_PERIOD_OVERLAP,
                                  "INTEREST window overlaps an existing run")
        # Rule 14: redemption notice period (dates: scheduled - creation >= notice).
        if ptype in REDEMPTION_TYPES and parse_date_strict(sched) is not None:
            creation_date = now().date()
            if (parse_date_strict(sched) - creation_date).days < tr["notice_period_days"]:
                raise_err(ERR_NOTICE_PERIOD_SHORT,
                          "scheduled_payment_date is inside the notice period")
        # Rule 26: shape.
        req_str(body, "tranche_id")
        ptype = req_enum(body, "payment_type",
                         ["INTEREST"] + list(REDEMPTION_TYPES))
        sched = req_date(body, "scheduled_payment_date")
        target = None
        if ptype == "INTEREST":
            start = req_date(body, "period_start_date")
            end = req_date(body, "period_end_date")
        else:
            target = req_int(body, "target_amount_cents")
        # gross: INTEREST provisionally computed at creation; redemption = target.
        if ptype == "INTEREST":
            gross = compute_interest_gross(tr, _active_positions(tr["id"]),
                                           start, end)
            notice_sent = None
        else:
            gross = target
            notice_sent = now_iso()
        e = new_entity("payment_runs")
        e.update({
            "tranche_id": tranche_id,
            "payment_type": ptype,
            "period_start_date": start if ptype == "INTEREST" else None,
            "period_end_date": end if ptype == "INTEREST" else None,
            "scheduled_payment_date": sched,
            "target_amount_cents": target,
            "notice_sent_at": notice_sent,
            "gross_amount_cents": gross,
            "funded_amount_cents": 0,
            "funding_status": "UNFUNDED",
            "distribution_status": "SCHEDULED",
            "executed_at": None,
            "_redeemed_position_ids": [],
            "_caused_tranche_terminal": False,
        })
    return ok(public(e), 201)


@bp.route("/payment-runs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_payment_runs():
    return list_response(DB["payment_runs"].values(), {
        "tranche_id": request.args.get("tranche_id"),
        "funding_status": request.args.get("funding_status"),
        "distribution_status": request.args.get("distribution_status"),
    })


@bp.route("/payment-runs/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_payment_run(rid):
    e = DB["payment_runs"].get(rid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "PaymentRun not found")
    return ok(public(e))


@bp.route("/payment-runs/<rid>/fund", methods=["POST"])
@require_roles("Issuer")
def fund_payment_run(rid):
    body = get_body()
    with LOCK:
        run = DB["payment_runs"].get(rid)
        if run is None:
            raise_err(ERR_NOT_FOUND, "PaymentRun not found")
        # Rule 3: issuer owns the run's indenture.
        tr = DB["tranches"].get(run["tranche_id"])
        ind = DB["indentures"].get(tr["indenture_id"]) if tr else None
        check_issuer_owns(ind)
        # Rule 5: only while distribution SCHEDULED.
        if run["distribution_status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE,
                      "Funding requires distribution_status SCHEDULED")
        # Rule 26: amount_cents must be a positive integer.
        amount = body.get("amount_cents")
        if not is_int(amount) or amount <= 0:
            raise_err(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
        funded = run["funded_amount_cents"] + amount
        status = "FUNDED" if funded >= run["gross_amount_cents"] else "PARTIALLY_FUNDED"
        mutate(run, funded_amount_cents=funded, funding_status=status)
    return ok(public(run))


@bp.route("/payment-runs/<rid>/execute", methods=["POST"])
@require_roles("TrustOfficer")
def execute_payment_run(rid):
    with LOCK:
        run = DB["payment_runs"].get(rid)
        if run is None:
            raise_err(ERR_NOT_FOUND, "PaymentRun not found")
        tr = DB["tranches"].get(run["tranche_id"])
        ind = DB["indentures"].get(tr["indenture_id"]) if tr else None
        # Rule 5 (state): indenture must be ACTIVE.
        if ind is None or ind["status"] != "ACTIVE":
            raise_err(ERR_INDENTURE_NOT_ACTIVE,
                      "Execution requires Indenture.status ACTIVE")
        # Rule 5: distribution must be SCHEDULED (SUSPENDED refuses execute).
        if run["distribution_status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE,
                      "Execution requires distribution_status SCHEDULED")
        # Rule 5: tranche must be ACTIVE.
        if tr is None or tr["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE,
                      "Execution requires an ACTIVE tranche")
        positions = _active_positions(tr["id"])
        # INTEREST gross is authoritatively recomputed at execute time.
        if run["payment_type"] == "INTEREST":
            gross = compute_interest_gross(tr, positions,
                                           run["period_start_date"],
                                           run["period_end_date"])
            mutate(run, gross_amount_cents=gross)
        # Rule 20: funded >= gross (equality executes).
        if run["funded_amount_cents"] < run["gross_amount_cents"]:
            raise_err(ERR_FUNDING_SHORTFALL,
                      "funded_amount_cents is below gross_amount_cents")
        # Mark the run DISTRIBUTED up front so the reduction ledger (which
        # counts only DISTRIBUTED runs) includes this run's own reductions.
        mutate(run, distribution_status="DISTRIBUTED", executed_at=now_iso())
        # Allocations and per-position distribution records (zero-cent included).
        if run["payment_type"] == "INTEREST":
            from calc import interest_for_position
            alloc = {p["id"]: interest_for_position(
                tr, p, run["period_start_date"], run["period_end_date"])
                for p in positions}
        else:
            alloc = pro_rata_allocation(run["gross_amount_cents"], positions)
        redeemed_now = []
        for p in positions:
            rec = new_entity("distribution_records")
            rec.update({
                "payment_run_id": run["id"],
                "position_id": p["id"],
                "allocated_cents": alloc[p["id"]],
                "status": "PENDING",
                "paid_at": None,
            })
        if run["payment_type"] != "INTEREST":
            for p in positions:
                share = alloc[p["id"]]
                if share:
                    new_val = p["principal_amount_cents"] - share
                    p["principal_amount_cents"] = new_val
                    p["principal_history"].append({
                        "effective_from": now_iso(),
                        "principal_cents": new_val,
                    })
                    if new_val == 0:
                        p["status"] = "REDEEMED"
                        redeemed_now.append(p["id"])
                    touch(p)
                elif p["principal_amount_cents"] == 0:
                    p["status"] = "REDEEMED"
                    redeemed_now.append(p["id"])
                    touch(p)
            recompute_tranche_outstanding(tr)
            if run["payment_type"] in ("FULL_REDEMPTION", "FINAL_MATURITY") \
                    and tr["outstanding_principal_cents"] == 0:
                terminal = ("REDEEMED" if run["payment_type"] == "FULL_REDEMPTION"
                            else "MATURED")
                for p in positions_of_tranche(tr["id"]):
                    if p["status"] == "ACTIVE":
                        p["status"] = "REDEEMED"
                        if p["id"] not in redeemed_now:
                            redeemed_now.append(p["id"])
                        touch(p)
                mutate(tr, status=terminal)
                run["_caused_tranche_terminal"] = True
            recompute_indenture_outstanding(ind)
            bubble_up_satisfaction(ind)
        run["_redeemed_position_ids"] = redeemed_now
    return ok(public(run))


@bp.route("/payment-runs/<rid>/reverse", methods=["POST"])
@require_roles("TrustManager")
def reverse_payment_run(rid):
    with LOCK:
        run = DB["payment_runs"].get(rid)
        if run is None:
            raise_err(ERR_NOT_FOUND, "PaymentRun not found")
        # Rule 5: only a DISTRIBUTED run reverses; no record may be RETURNED yet.
        if run["distribution_status"] != "DISTRIBUTED":
            raise_err(ERR_INVALID_STATE,
                      "Only a DISTRIBUTED run can be reversed")
        records = records_of_run(run["id"])
        if any(r["status"] == "RETURNED" for r in records):
            raise_err(ERR_INVALID_STATE,
                      "A record of this run is already RETURNED")
        tr = DB["tranches"].get(run["tranche_id"])
        ind = DB["indentures"].get(tr["indenture_id"]) if tr else None
        for rec in records:
            if rec["status"] in ("PENDING", "HELD", "PAID"):
                mutate(rec, status="RETURNED")
        # Mark the run REVERSED before recomputing tranche outstanding, so the
        # reduction ledger (which counts only DISTRIBUTED runs) excludes it.
        mutate(run, distribution_status="REVERSED")
        if run["payment_type"] != "INTEREST":
            # Undo principal reductions; positions redeemed by this run reactivate.
            for rec in records:
                p = DB["positions"].get(rec["position_id"])
                if p is None:
                    continue
                restored = p["principal_amount_cents"] + rec["allocated_cents"]
                p["principal_amount_cents"] = restored
                p["principal_history"].append({
                    "effective_from": now_iso(),
                    "principal_cents": restored,
                })
                if p["id"] in run.get("_redeemed_position_ids", []):
                    p["status"] = "ACTIVE"
                touch(p)
            recompute_tranche_outstanding(tr)
            if run.get("_caused_tranche_terminal") and \
                    tr["status"] in ("REDEEMED", "MATURED"):
                mutate(tr, status="ACTIVE")
            if ind is not None:
                recompute_indenture_outstanding(ind)
                # Satisfaction bubble-up is undone if a tranche is live again.
                if ind["status"] == "SATISFIED":
                    from domain import tranches_of
                    if any(t["status"] not in ("REDEEMED", "MATURED")
                           for t in tranches_of(ind["id"])):
                        mutate(ind, status="ACTIVE")
        recompute_all_account_totals()
    return ok(public(run))


# ---------------------------------------------------------------------------
# DistributionRecord
# ---------------------------------------------------------------------------

@bp.route("/distribution-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_records():
    return list_response(DB["distribution_records"].values(), {
        "payment_run_id": request.args.get("payment_run_id"),
        "position_id": request.args.get("position_id"),
        "status": request.args.get("status"),
    })


@bp.route("/distribution-records/<did>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_record(did):
    e = DB["distribution_records"].get(did)
    if e is None:
        raise_err(ERR_NOT_FOUND, "DistributionRecord not found")
    return ok(public(e))


@bp.route("/distribution-records/<did>/return", methods=["POST"])
@require_roles("TrustOfficer")
def return_record(did):
    with LOCK:
        rec = DB["distribution_records"].get(did)
        if rec is None:
            raise_err(ERR_NOT_FOUND, "DistributionRecord not found")
        if rec["status"] == "RETURNED":
            raise_err(ERR_ALREADY_TERMINAL, "Record is terminal (RETURNED)")
        if rec["status"] != "PAID":
            raise_err(ERR_INVALID_STATE, "Only a PAID record can be returned")
        run = DB["payment_runs"].get(rec["payment_run_id"])
        if run is None or run["distribution_status"] != "DISTRIBUTED":
            raise_err(ERR_INVALID_STATE,
                      "The parent run must be DISTRIBUTED")
        mutate(rec, status="RETURNED")
        recompute_all_account_totals()
    return ok(public(rec))
