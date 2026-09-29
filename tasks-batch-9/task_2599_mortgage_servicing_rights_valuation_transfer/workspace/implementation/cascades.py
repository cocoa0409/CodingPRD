"""Cascading side effects: curve supersession (PRD 2.8), completion and
termination unwinds (PRD 2.9). Every touched row gets its own updated_at
refresh and its own version increment -- a cascade is not a silent write."""
from core import DB, now_dt, now_iso, rows, sort_created, touch
import calcs


def remark_open_hedges(curve):
    """Fan-out that is explicitly NOT part of the supersession chain."""
    if curve is None:
        return
    for position in sort_created(rows("hedge_positions")):
        if position["status"] != "OPEN":
            continue
        position["mark_to_market_cents"] = calcs.hedge_mtm(position, curve["base_rate_bps"])
        touch(position)


def supersede_curve_cascade(incumbent):
    """Links 1-4 of the mandatory curve-supersession chain, in order."""
    # Link 1 -- the incumbent ACTIVE snapshot leaves ACTIVE.
    incumbent["status"] = "SUPERSEDED"
    incumbent["superseded_at"] = now_iso()
    touch(incumbent)

    # Link 2 -- COMPLETED runs bound to that snapshot go STALE.
    staled_run_ids = set()
    for run in sort_created(rows("valuation_runs")):
        if run["rate_curve_snapshot_id"] != incumbent["id"]:
            continue
        if run["status"] != "COMPLETED":
            continue
        run["status"] = "STALE"
        run["staled_at"] = now_iso()
        touch(run)
        staled_run_ids.add(run["id"])

    # Link 3 -- PUBLISHED packages bound to a just-staled run suspend bidding.
    for package in sort_created(rows("bid_packages")):
        if package["valuation_run_id"] not in staled_run_ids:
            continue
        if package["status"] != "PUBLISHED":
            continue
        package["status"] = "BIDDING_SUSPENDED"
        package["suspended_reason"] = "VALUATION_STALE"
        touch(package)

        # Link 4 -- live bids on such a package lapse.
        for bid in sort_created(rows("bids")):
            if bid["bid_package_id"] != package["id"]:
                continue
            if bid["status"] not in ("SUBMITTED", "COUNTERED", "REVISED"):
                continue
            bid["status"] = "LAPSED"
            touch(bid)


def close_hedge_position(position, curve):
    """Stamps a close exactly as a manual close would."""
    base = curve["base_rate_bps"] if curve is not None else position["entry_base_rate_bps"]
    position["mark_to_market_cents"] = calcs.hedge_mtm(position, base)
    position["status"] = "CLOSED"
    position["closed_at"] = now_iso()
    position["close_base_rate_bps"] = base
    position["realized_pnl_cents"] = position["mark_to_market_cents"]
    touch(position)


def completion_cascade(transfer, agreement, package, portfolio):
    """PRD 2.9 -- three conditional links behind completing a transfer."""
    tape_lines = calcs.included_lines(package["id"])
    transferred = len(tape_lines)
    transfer["transferred_loan_count"] = transferred
    transfer["completed_at"] = now_iso()
    transfer["status"] = "COMPLETED"
    touch(transfer)

    # Link 1 -- every loan on the awarded tape that is still included transfers.
    for line in tape_lines:
        loan = DB["loans"].get(line["loan_id"])
        if loan is None or loan["status"] != "ACTIVE":
            continue
        loan["status"] = "TRANSFERRED"
        loan["transferred_at"] = now_iso()
        touch(loan)

    # Link 2 -- conditional on no loan on the portfolio remaining ACTIVE.
    remaining = [l for l in calcs.portfolio_loans(portfolio["id"]) if l["status"] == "ACTIVE"]
    if remaining or portfolio["status"] != "UNDER_CONTRACT":
        return
    portfolio["status"] = "TRANSFERRED"
    touch(portfolio)

    # Link 3 -- reaching TRANSFERRED closes the remaining hedge book.
    curve = calcs.active_curve()
    for position in sort_created(rows("hedge_positions")):
        if position["portfolio_id"] != portfolio["id"] or position["status"] != "OPEN":
            continue
        close_hedge_position(position, curve)


def terminate_agreement_cascade(agreement):
    """PRD 2.9 -- a DENIED decision unwinds the whole marketing chain."""
    agreement["status"] = "TERMINATED"
    agreement["termination_reason"] = "APPROVAL_DENIED"
    touch(agreement)

    package = DB["bid_packages"].get(agreement["bid_package_id"])
    if package is None:
        return

    siblings = [a for a in rows("agreements")
                if a["bid_package_id"] == package["id"] and a["id"] != agreement["id"]]
    consummated = any(a["status"] in ("SETTLED", "HOLDBACK_RELEASED", "CLOSED")
                      for a in siblings)

    if not consummated and package["status"] in ("AWARDED", "PUBLISHED", "BIDDING_SUSPENDED"):
        package["status"] = "CANCELLED"
        touch(package)

    for bid in sort_created(rows("bids")):
        if bid["bid_package_id"] != package["id"]:
            continue
        if bid["status"] in ("ACCEPTED", "SUBMITTED"):
            bid["status"] = "REJECTED"
            touch(bid)

    portfolio = DB["portfolios"].get(package["portfolio_id"])
    if portfolio is None or portfolio["status"] != "UNDER_CONTRACT":
        return
    portfolio_pkg_ids = {p["id"] for p in rows("bid_packages")
                         if p["portfolio_id"] == portfolio["id"]}
    live = [a for a in rows("agreements")
            if a["bid_package_id"] in portfolio_pkg_ids and a["status"] != "TERMINATED"]
    if live:
        return
    portfolio["status"] = "TAPE_LOCKED"
    touch(portfolio)


def supersede_older_runs(portfolio_id, new_run_id):
    """A newer run supersedes earlier COMPLETED/STALE runs unless a live package
    still points at them."""
    live_run_ids = {p["valuation_run_id"] for p in rows("bid_packages")
                    if p["status"] in ("PUBLISHED", "BIDDING_SUSPENDED", "AWARDED")}
    for run in sort_created(rows("valuation_runs")):
        if run["portfolio_id"] != portfolio_id or run["id"] == new_run_id:
            continue
        if run["status"] not in ("COMPLETED", "STALE"):
            continue
        if run["id"] in live_run_ids:
            continue
        run["status"] = "SUPERSEDED"
        touch(run)
