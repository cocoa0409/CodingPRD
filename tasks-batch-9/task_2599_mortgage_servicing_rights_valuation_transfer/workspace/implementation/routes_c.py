"""Bid packages, tape lines, bids, award."""
from flask import Blueprint, request

import calcs
import serial
from core import (DB, D, READ_PKG, R_TXN, R_VALUATION, authenticate, body_of, f_bool,
                  f_dec, f_dt, f_enum, f_id, f_int, fail, filter_eq, lookup, new_row,
                  no_body, now_dt, now_iso, ok, paginate, rows, sort_created, touch)

bp = Blueprint("group_c", __name__)

SCHEMES = ("BY_STATE", "BY_NOTE_RATE", "BY_DELINQUENCY")
EXCLUSION_REASONS = ("DOCUMENT_DEFECT", "LITIGATION", "INVESTOR_RESTRICTION")
LIVE_MARKETING = ("STRATIFIED", "PUBLISHED", "BIDDING_SUSPENDED")


# ---------------------------------------------------------------- bid packages
@bp.post("/msr/bid-packages")
def create_bid_package():
    authenticate(("ValuationAnalyst", "TransactionManager"))
    body = body_of("portfolio_id", "valuation_run_id", "stratification_scheme",
                   "reserve_price_floor_pct", "marketing_start_at", "bid_deadline_at")
    pf_id = f_id(body, "portfolio_id")
    run_id = f_id(body, "valuation_run_id")
    scheme = f_enum(body, "stratification_scheme", SCHEMES)
    floor_pct = f_dec(body, "reserve_price_floor_pct", minimum=50, maximum=150, places=2)
    start_dt, start_raw = f_dt(body, "marketing_start_at")
    end_dt, end_raw = f_dt(body, "bid_deadline_at")
    if end_dt <= start_dt:
        fail("ERR_INVALID_REQUEST", "bid_deadline_at must be strictly after marketing_start_at")

    portfolio = lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    lookup("valuation_runs", run_id, "ERR_VALUATION_RUN_NOT_FOUND")
    if portfolio["status"] != "TAPE_LOCKED":
        fail("ERR_TAPE_NOT_LOCKED", "a bid package requires a locked tape")

    row = new_row("bid_packages")
    row.update({"portfolio_id": pf_id, "valuation_run_id": run_id,
                "stratification_scheme": scheme, "reserve_price_floor_pct": floor_pct,
                "marketing_start_at": start_raw, "_start": start_dt,
                "bid_deadline_at": end_raw, "_deadline": end_dt,
                "status": "DRAFT", "reserve_price_cents": None, "published_at": None,
                "suspended_reason": None})
    return ok(serial.ser_bid_package(row), 201)


@bp.get("/msr/bid-packages/<pkg_id>")
def get_bid_package(pkg_id):
    authenticate(READ_PKG)
    row = lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    return ok(serial.ser_bid_package(row))


@bp.get("/msr/bid-packages")
def list_bid_packages():
    authenticate(READ_PKG)
    items = sort_created(rows("bid_packages"))
    items = filter_eq(items, "portfolio_id")
    items = filter_eq(items, "valuation_run_id")
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_bid_package)


@bp.post("/msr/bid-packages/<pkg_id>/stratify")
def stratify(pkg_id):
    authenticate(R_VALUATION)
    no_body()
    package = lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    portfolio = DB["portfolios"][package["portfolio_id"]]
    if portfolio["status"] != "TAPE_LOCKED":
        fail("ERR_TAPE_NOT_LOCKED", "stratification requires a locked tape")
    if package["status"] != "DRAFT":
        fail("ERR_PACKAGE_INVALID_STATE", "only a DRAFT package can be stratified")

    scheme = package["stratification_scheme"]
    for loan in calcs.active_loans(portfolio["id"]):
        line = new_row("tape_lines")
        line.update({"bid_package_id": pkg_id, "loan_id": loan["id"],
                     "stratum_label": calcs.stratum_label(loan, scheme),
                     "included": True, "exclusion_reason": None,
                     "upb_snapshot_cents": loan["upb_cents"]})
    package["status"] = "STRATIFIED"
    touch(package)
    return ok(serial.ser_bid_package(package))


@bp.get("/msr/bid-packages/<pkg_id>/tape-lines")
def list_package_tape_lines(pkg_id):
    authenticate(READ_PKG)
    lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    items = calcs.package_lines(pkg_id)
    included = request.args.get("included")
    if included is not None:
        want = str(included).strip().lower()
        if want not in ("true", "false"):
            fail("ERR_INVALID_REQUEST", "included filter must be true or false")
        items = [t for t in items if t["included"] == (want == "true")]
    items = filter_eq(items, "stratum_label")
    return paginate(items, serial.ser_tape_line)


@bp.get("/msr/tape-lines/<line_id>")
def get_tape_line(line_id):
    authenticate(READ_PKG)
    row = lookup("tape_lines", line_id, "ERR_TAPE_LINE_NOT_FOUND")
    return ok(serial.ser_tape_line(row))


@bp.patch("/msr/tape-lines/<line_id>")
def patch_tape_line(line_id):
    authenticate(R_VALUATION)
    body = body_of("included", "exclusion_reason")
    included = f_bool(body, "included")
    reason = f_enum(body, "exclusion_reason", EXCLUSION_REASONS, required=False)
    if included is False and reason is None:
        fail("ERR_INVALID_REQUEST", "exclusion_reason is required when included is false")
    if included is True and "exclusion_reason" in body and body["exclusion_reason"] is not None:
        fail("ERR_INVALID_REQUEST", "exclusion_reason must be absent when included is true")

    line = lookup("tape_lines", line_id, "ERR_TAPE_LINE_NOT_FOUND")
    package = DB["bid_packages"][line["bid_package_id"]]
    if package["status"] != "STRATIFIED":
        fail("ERR_PACKAGE_INVALID_STATE",
             "tape membership is only editable while the package is STRATIFIED")

    line["included"] = included
    line["exclusion_reason"] = reason if included is False else None
    touch(line)
    touch(package)
    return ok(serial.ser_tape_line(line))


@bp.post("/msr/bid-packages/<pkg_id>/publish")
def publish(pkg_id):
    authenticate(R_TXN)
    no_body()
    package = lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    if package["status"] != "STRATIFIED":
        fail("ERR_PACKAGE_INVALID_STATE", "only a STRATIFIED package can be published")

    run = DB["valuation_runs"][package["valuation_run_id"]]
    if run["status"] != "COMPLETED":
        fail("ERR_VALUATION_STALE", "the bound valuation run is no longer COMPLETED")

    for other in rows("bid_packages"):
        if other["id"] == pkg_id or other["portfolio_id"] != package["portfolio_id"]:
            continue
        if other["status"] not in LIVE_MARKETING:
            continue
        if package["_start"] < other["_deadline"] and other["_start"] < package["_deadline"]:
            fail("ERR_MARKETING_WINDOW_OVERLAP",
                 "marketing window overlaps a live package on the same portfolio")

    if calcs.tape_loan_count(pkg_id) == 0:
        fail("ERR_TAPE_EMPTY", "the package tape holds no included loans")

    portfolio = DB["portfolios"][package["portfolio_id"]]
    package["reserve_price_cents"] = calcs.reserve_price(package, run, portfolio)
    package["published_at"] = now_iso()
    package["status"] = "PUBLISHED"
    touch(package)
    return ok(serial.ser_bid_package(package))


# ---------------------------------------------------------------- bids
def _bidder_eligible(bidder, portfolio):
    if bidder["status"] != "ACTIVE":
        return False
    return portfolio["agency_type"] in bidder["agency_approvals"]


@bp.post("/msr/bid-packages/<pkg_id>/bids")
def submit_bid(pkg_id):
    authenticate(("BuyerServicer", "TransactionManager"))
    body = body_of("bidder_id", "price_bps", "holdback_pct", "expected_bid_package_version")
    bidder_id = f_id(body, "bidder_id")
    price_bps = f_int(body, "price_bps", minimum=1, maximum=1000)
    holdback_pct = f_dec(body, "holdback_pct", minimum=0, maximum=25, places=2)
    expected = f_int(body, "expected_bid_package_version", minimum=0)

    package = lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    bidder = lookup("counterparties", bidder_id, "ERR_COUNTERPARTY_NOT_FOUND")
    if bidder["role_type"] != "BUYER":
        fail("ERR_COUNTERPARTY_ROLE_MISMATCH", "named counterparty is not a BUYER")
    if package["status"] != "PUBLISHED":
        fail("ERR_PACKAGE_NOT_ACCEPTING_BIDS", "the package is not accepting bids")
    if expected != package["version"]:
        fail("ERR_STALE_BID_PACKAGE_VERSION",
             "expected_bid_package_version does not match the stored package version")

    portfolio = DB["portfolios"][package["portfolio_id"]]
    if not _bidder_eligible(bidder, portfolio):
        fail("ERR_BIDDER_NOT_ELIGIBLE", "bidder is suspended or lacks the agency approval")
    if calcs.risk_score(bidder, "PRE_AWARD")["score"] < 40:
        fail("ERR_BIDDER_RISK_TIER_TOO_HIGH", "bidder transfer risk score is below 40")

    clock = now_dt()
    if clock < package["_start"] or clock >= package["_deadline"]:
        fail("ERR_BID_DEADLINE_PASSED", "the marketing window is not open")

    value = calcs.bid_value_cents(pkg_id, price_bps)
    if package["reserve_price_cents"] is not None and value < package["reserve_price_cents"]:
        fail("ERR_BID_BELOW_RESERVE", "bid value is below the reserve price")

    row = new_row("bids")
    row.update({"bid_package_id": pkg_id, "bidder_id": bidder_id, "price_bps": price_bps,
                "holdback_pct": holdback_pct, "round_number": 1, "status": "SUBMITTED",
                "bid_value_cents": value, "counter_price_bps": None,
                "counter_expires_at": None, "_counter_expires": None})
    touch(package)
    return ok(serial.ser_bid(row), 201)


@bp.get("/msr/bids/<bid_id>")
def get_bid(bid_id):
    authenticate(READ_PKG)
    row = lookup("bids", bid_id, "ERR_BID_NOT_FOUND")
    return ok(serial.ser_bid(row))


@bp.get("/msr/bids")
def list_bids():
    authenticate(READ_PKG)
    items = sort_created(rows("bids"))
    items = filter_eq(items, "bid_package_id")
    items = filter_eq(items, "bidder_id")
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_bid)


@bp.post("/msr/bids/<bid_id>/counter")
def counter_bid(bid_id):
    authenticate(R_TXN)
    body = body_of("counter_price_bps", "counter_expires_at")
    counter_price = f_int(body, "counter_price_bps", minimum=1)
    expires_dt, expires_raw = f_dt(body, "counter_expires_at")

    bid = lookup("bids", bid_id, "ERR_BID_NOT_FOUND")
    if bid["status"] not in ("SUBMITTED", "REVISED"):
        fail("ERR_BID_INVALID_STATE", "only a SUBMITTED or REVISED bid can be countered")
    package = DB["bid_packages"][bid["bid_package_id"]]
    if package["status"] != "PUBLISHED":
        fail("ERR_PACKAGE_NOT_ACCEPTING_BIDS", "the package is not accepting negotiation")

    bid["counter_price_bps"] = counter_price
    bid["counter_expires_at"] = expires_raw
    bid["_counter_expires"] = expires_dt
    bid["status"] = "COUNTERED"
    touch(bid)
    return ok(serial.ser_bid(bid))


@bp.post("/msr/bids/<bid_id>/revise")
def revise_bid(bid_id):
    user_id, _ = authenticate(("BuyerServicer",))
    body = body_of("price_bps", "holdback_pct")
    price_bps = f_int(body, "price_bps", minimum=1, maximum=1000)
    holdback_pct = f_dec(body, "holdback_pct", minimum=0, maximum=25, places=2)

    bid = lookup("bids", bid_id, "ERR_BID_NOT_FOUND")
    if user_id != bid["bidder_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "acting identity is not the bidder on this bid")
    if bid["status"] != "COUNTERED":
        fail("ERR_BID_INVALID_STATE", "only a COUNTERED bid can be revised")
    package = DB["bid_packages"][bid["bid_package_id"]]
    if package["status"] != "PUBLISHED":
        fail("ERR_PACKAGE_NOT_ACCEPTING_BIDS", "the package is not accepting negotiation")
    if bid["_counter_expires"] is not None and now_dt() >= bid["_counter_expires"]:
        fail("ERR_BID_DEADLINE_PASSED", "the counter has expired")
    if bid["round_number"] >= 3:
        fail("ERR_MAX_NEGOTIATION_ROUNDS", "the negotiation round ceiling has been reached")

    value = calcs.bid_value_cents(package["id"], price_bps)
    if package["reserve_price_cents"] is not None and value < package["reserve_price_cents"]:
        fail("ERR_BID_BELOW_RESERVE", "revised bid value is below the reserve price")

    bid["price_bps"] = price_bps
    bid["holdback_pct"] = holdback_pct
    bid["bid_value_cents"] = value
    bid["round_number"] = bid["round_number"] + 1
    bid["counter_price_bps"] = None
    bid["counter_expires_at"] = None
    bid["_counter_expires"] = None
    bid["status"] = "REVISED"
    touch(bid)
    return ok(serial.ser_bid(bid))


@bp.post("/msr/bid-packages/<pkg_id>/award")
def award(pkg_id):
    user_id, _ = authenticate(R_TXN)
    body = body_of("winning_bid_id", "rep_warrant_days", "indemnification_days")
    bid_id = f_id(body, "winning_bid_id")
    rep_days = f_int(body, "rep_warrant_days", required=False, minimum=30, maximum=730,
                     default=180)
    indem_days = f_int(body, "indemnification_days", required=False, minimum=1,
                       maximum=1825, default=365)
    if indem_days < rep_days:
        fail("ERR_INVALID_REQUEST",
             "indemnification_days must not be shorter than rep_warrant_days")

    package = lookup("bid_packages", pkg_id, "ERR_BID_PACKAGE_NOT_FOUND")
    bid = lookup("bids", bid_id, "ERR_BID_NOT_FOUND")
    if package["status"] != "PUBLISHED":
        fail("ERR_PACKAGE_INVALID_STATE", "only a PUBLISHED package can be awarded")
    if bid["bid_package_id"] != pkg_id or bid["status"] not in ("SUBMITTED", "REVISED"):
        fail("ERR_BID_INVALID_STATE", "the nominated bid is not awardable on this package")

    run = DB["valuation_runs"][package["valuation_run_id"]]
    if user_id == run["run_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the analyst who produced the valuation may not award the sale")

    bidder = DB["counterparties"][bid["bidder_id"]]
    portfolio = DB["portfolios"][package["portfolio_id"]]
    if not _bidder_eligible(bidder, portfolio):
        fail("ERR_BIDDER_NOT_ELIGIBLE", "bidder is no longer eligible to be awarded")

    price, breakdown = calcs.purchase_price(pkg_id, bid["price_bps"])
    agreement = new_row("agreements")
    agreement.update({"bid_package_id": pkg_id, "winning_bid_id": bid_id,
                      "buyer_id": bid["bidder_id"], "purchase_price_cents": price,
                      "stratum_price_breakdown": breakdown,
                      "holdback_pct": bid["holdback_pct"],
                      "rep_warrant_days": rep_days, "indemnification_days": indem_days,
                      "sale_date": None, "transfer_date": None,
                      "holdback_release_eligible_at": None, "status": "DRAFTED",
                      "approval_pending_count": 0, "condition_count": 0,
                      "condition_waiver_reference": None, "drafted_by_user_id": user_id,
                      "termination_reason": None})
    calcs.size_holdback(agreement)

    bid["status"] = "ACCEPTED"
    touch(bid)
    for other in sort_created(rows("bids")):
        if other["id"] == bid_id or other["bid_package_id"] != pkg_id:
            continue
        if other["status"] in ("SUBMITTED", "COUNTERED", "REVISED"):
            other["status"] = "REJECTED"
            touch(other)

    package["status"] = "AWARDED"
    touch(package)
    if portfolio["status"] == "TAPE_LOCKED":
        portfolio["status"] = "UNDER_CONTRACT"
        touch(portfolio)
    return ok(serial.ser_agreement(agreement), 201)
