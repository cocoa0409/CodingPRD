"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BRK_MANUFACTURER,
    BRK_PRICE_CENTS,
    BRK_SKU,
    FAR_FUTURE_VALID_UNTIL,
    THHN_CUT_CHARGE_CENTS,
    THHN_MANUFACTURER,
    THHN_MIN_CUT_FT,
    THHN_PRICE_CENTS,
    THHN_REEL_LENGTH_FT,
    THHN_SKU,
)
from .factories import (
    create_catalog_item_payload,
    create_clock_payload,
    create_contractor_payload,
    create_decision_payload,
    create_index_reading_payload,
    create_job_account_payload,
    create_lien_waiver_payload,
    create_payment_payload,
    create_quote_line_payload,
    create_quote_payload,
    create_rebate_claim_payload,
    create_rebate_program_payload,
    create_release_payload,
    create_schedule_payload,
    create_stock_receipt_payload,
    create_substitution_request_payload,
)
from .test_users import TEST_USERS

SALES_REP = TEST_USERS["sales_rep_headers"]
BRANCH_MGR = TEST_USERS["branch_manager_headers"]
CREDIT_MGR = TEST_USERS["credit_manager_headers"]
WH_MGR = TEST_USERS["warehouse_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
REBATE_CLERK = TEST_USERS["rebate_clerk_headers"]


def _ok(step, resp, expected_state=None):
    data = get_success_data(resp)
    if expected_state is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_state, (
            f"Setup failed at {step}: expected state {expected_state}, "
            f"got {status}")
    return data


# ---------------------------------------------------------------------------
# Tier 0 — atomic creators
# ---------------------------------------------------------------------------

def create_contractor(name="Test Electric", credit_limit_cents=10_000_000):
    resp = api_client.create_contractor(
        create_contractor_payload(name=name, credit_limit_cents=credit_limit_cents),
        CREDIT_MGR)
    return _ok("create_contractor", resp)


def create_ea_item(sku=BRK_SKU, manufacturer_name=BRK_MANUFACTURER,
                   list_price_cents=BRK_PRICE_CENTS):
    resp = api_client.create_catalog_item(
        create_catalog_item_payload(
            sku=sku, manufacturer_name=manufacturer_name,
            sell_uom="EA", list_price_cents=list_price_cents),
        WH_MGR)
    return _ok("create_catalog_item(EA)", resp)


def create_foot_item(sku=THHN_SKU, manufacturer_name=THHN_MANUFACTURER,
                     list_price_cents=THHN_PRICE_CENTS,
                     reel_length_ft=THHN_REEL_LENGTH_FT,
                     min_cut_ft=THHN_MIN_CUT_FT,
                     cut_charge_cents=THHN_CUT_CHARGE_CENTS):
    resp = api_client.create_catalog_item(
        create_catalog_item_payload(
            sku=sku, manufacturer_name=manufacturer_name, sell_uom="FOOT",
            list_price_cents=list_price_cents, reel_length_ft=reel_length_ft,
            min_cut_ft=min_cut_ft, cut_charge_cents=cut_charge_cents),
        WH_MGR)
    return _ok("create_catalog_item(FOOT)", resp)


def receive_stock(item_id, qty):
    resp = api_client.receive_stock(
        item_id, create_stock_receipt_payload(qty=qty), WH_MGR)
    return _ok("receive_stock", resp)


def get_catalog_item(item_id):
    return _ok("get_catalog_item", api_client.get_catalog_item(item_id, WH_MGR))


def create_job_account(contractor_id, job_name="Test Job",
                       jobsite_address="1 Site Rd", pricing_mode="FIRM_PRICE",
                       escalation_cap_pct=None, lien_waiver_required=None):
    overrides = {}
    if escalation_cap_pct is not None:
        overrides["escalation_cap_pct"] = escalation_cap_pct
    if lien_waiver_required is not None:
        overrides["lien_waiver_required"] = lien_waiver_required
    resp = api_client.create_job_account(
        create_job_account_payload(
            contractor_id=contractor_id, job_name=job_name,
            jobsite_address=jobsite_address, pricing_mode=pricing_mode,
            **overrides),
        SALES_REP)
    return _ok("create_job_account", resp, expected_state="OPEN")


def get_job_account(job_account_id):
    return _ok("get_job_account",
               api_client.get_job_account(job_account_id, SALES_REP))


def get_job_account_version(job_account_id):
    return get_job_account(job_account_id)["version"]


def file_lien_waiver(job_account_id, expires_on):
    resp = api_client.file_lien_waiver(
        job_account_id, create_lien_waiver_payload(expires_on=expires_on),
        CREDIT_MGR)
    return _ok("file_lien_waiver", resp)


def record_payment(contractor_id, amount_cents):
    resp = api_client.record_payment(
        contractor_id, create_payment_payload(amount_cents=amount_cents),
        CREDIT_MGR)
    return _ok("record_payment", resp)


def get_contractor(contractor_id):
    return _ok("get_contractor",
               api_client.get_contractor(contractor_id, CREDIT_MGR))


def set_clock(to_iso8601):
    resp = api_client.set_clock(
        create_clock_payload(to_iso8601=to_iso8601), BRANCH_MGR)
    return _ok("set_clock", resp)


def set_index_reading(month, index_value):
    resp = api_client.set_index_reading(
        create_index_reading_payload(month=month, index_value=index_value),
        BRANCH_MGR)
    return _ok("set_index_reading", resp)


# ---------------------------------------------------------------------------
# Tier 1 — quote lifecycle
# ---------------------------------------------------------------------------

def create_quote(job_account_id, valid_until=FAR_FUTURE_VALID_UNTIL):
    resp = api_client.create_quote(
        create_quote_payload(job_account_id=job_account_id,
                             valid_until=valid_until),
        SALES_REP)
    return _ok("create_quote", resp, expected_state="DRAFT")


def add_quote_line(quote_id, catalog_item_id, qty, unit_price_cents):
    resp = api_client.create_quote_line(
        create_quote_line_payload(
            quote_id=quote_id, catalog_item_id=catalog_item_id, qty=qty,
            unit_price_cents=unit_price_cents),
        SALES_REP)
    return _ok("add_quote_line", resp)


def submit_quote(quote_id):
    resp = api_client.submit_quote(quote_id, SALES_REP)
    return _ok("submit_quote", resp, expected_state="SUBMITTED")


def revise_quote(quote_id, expected_quote_version):
    resp = api_client.revise_quote(
        quote_id, {"expected_quote_version": expected_quote_version}, SALES_REP)
    return _ok("revise_quote", resp, expected_state="DRAFT")


def award_quote(quote_id):
    resp = api_client.award_quote(quote_id, BRANCH_MGR)
    return _ok("award_quote", resp, expected_state="AWARDED")


def get_quote(quote_id):
    return _ok("get_quote", api_client.get_quote(quote_id, SALES_REP))


def create_draft_quote_with_lines(job_account_id, lines,
                                  valid_until=FAR_FUTURE_VALID_UNTIL):
    """DRAFT quote carrying the given (item_id, qty, unit_price_cents) lines."""
    quote = create_quote(job_account_id, valid_until=valid_until)
    for item_id, qty, unit_price_cents in lines:
        add_quote_line(quote["id"], item_id, qty, unit_price_cents)
    return quote


def create_submitted_quote(job_account_id, lines,
                           valid_until=FAR_FUTURE_VALID_UNTIL):
    quote = create_draft_quote_with_lines(job_account_id, lines, valid_until)
    return submit_quote(quote["id"])


def create_awarded_quote(job_account_id, lines,
                         valid_until=FAR_FUTURE_VALID_UNTIL):
    """Quote walked DRAFT -> SUBMITTED -> AWARDED."""
    quote = create_submitted_quote(job_account_id, lines, valid_until)
    return award_quote(quote["id"])


# ---------------------------------------------------------------------------
# Tier 1b — substitution requests
# ---------------------------------------------------------------------------

def create_substitution(quote_line_id, proposed_item_id, reason="lead time"):
    resp = api_client.create_substitution_request(
        create_substitution_request_payload(
            quote_line_id=quote_line_id, proposed_item_id=proposed_item_id,
            reason=reason),
        SALES_REP)
    return _ok("create_substitution_request", resp, expected_state="PROPOSED")


def decide_substitution(request_id, decision="APPROVE"):
    resp = api_client.decide_substitution_request(
        request_id, create_decision_payload(decision=decision), BRANCH_MGR)
    return _ok("decide_substitution_request", resp)


def get_quote_line(quote_line_id):
    return _ok("get_quote_line",
               api_client.get_quote_line(quote_line_id, SALES_REP))


def get_substitution_request(request_id):
    return _ok("get_substitution_request",
               api_client.get_substitution_request(request_id, SALES_REP))


# ---------------------------------------------------------------------------
# Tier 2 — release lifecycle walkers
# ---------------------------------------------------------------------------

def create_release(job_account_id, quote_id, lines,
                   expected_job_account_version=None, as_headers=None):
    """Create a REQUESTED release. lines is a list of (item_id, qty) pairs.
    When expected_job_account_version is None the account's current version
    is read first (the create bumps the account version by 1, PRD 3.6)."""
    if expected_job_account_version is None:
        expected_job_account_version = get_job_account_version(job_account_id)
    resp = api_client.create_release(
        create_release_payload(
            job_account_id=job_account_id, quote_id=quote_id,
            expected_job_account_version=expected_job_account_version,
            lines=[{"catalog_item_id": item_id, "qty": qty}
                   for item_id, qty in lines]),
        as_headers or SALES_REP)
    return _ok("create_release", resp, expected_state="REQUESTED")


def get_release(release_id):
    return _ok("get_release", api_client.get_release(release_id, SALES_REP))


def credit_approve_release(release_id):
    resp = api_client.credit_approve_release(release_id, CREDIT_MGR)
    return _ok("credit_approve_release", resp, expected_state="CREDIT_APPROVED")


def allocate_release(release_id):
    resp = api_client.allocate_release(release_id, WH_MGR)
    return _ok("allocate_release", resp)


def schedule_release(release_id, truck_id="T1", delivery_date="2026-08-10",
                     window_start_hour=8, window_end_hour=12):
    resp = api_client.schedule_release(
        release_id,
        create_schedule_payload(
            truck_id=truck_id, delivery_date=delivery_date,
            window_start_hour=window_start_hour,
            window_end_hour=window_end_hour),
        DISPATCHER)
    return _ok("schedule_release", resp, expected_state="SCHEDULED")


def deliver_release(release_id):
    resp = api_client.deliver_release(release_id, DISPATCHER)
    return _ok("deliver_release", resp, expected_state="DELIVERED")


def invoice_release(release_id):
    resp = api_client.invoice_release(release_id, CREDIT_MGR)
    return _ok("invoice_release", resp, expected_state="INVOICED")


def cancel_release(release_id, as_headers=None):
    resp = api_client.cancel_release(release_id, as_headers or SALES_REP)
    return _ok("cancel_release", resp, expected_state="CANCELLED")


def walk_release(release_id, target_status, truck_id="T1",
                 delivery_date="2026-08-10", window=(8, 12)):
    """Walk a release along the linear happy path to target_status.
    Requires stock to fully cover every line (no backorders)."""
    steps = {
        "CREDIT_APPROVED": lambda: credit_approve_release(release_id),
        "ALLOCATED": lambda: allocate_release(release_id),
        "SCHEDULED": lambda: schedule_release(
            release_id, truck_id=truck_id, delivery_date=delivery_date,
            window_start_hour=window[0], window_end_hour=window[1]),
        "DELIVERED": lambda: deliver_release(release_id),
        "INVOICED": lambda: invoice_release(release_id),
    }
    order = ["REQUESTED", "CREDIT_APPROVED", "ALLOCATED", "SCHEDULED",
             "DELIVERED", "INVOICED"]
    release = get_release(release_id)
    current = release["status"]
    assert current in order, f"walk_release: unexpected start state {current}"
    while current != target_status:
        nxt = order[order.index(current) + 1]
        release = steps[nxt]()
        current = release["status"]
        assert current == nxt, (
            f"walk_release: expected {nxt} after step, got {current}")
    return release


def list_release_lines(release_id):
    data = _ok("list_release_lines", api_client.list_release_lines(
        WH_MGR, params={"release_id": release_id}))
    assert isinstance(data, list), "release-lines list must return an array"
    return data


def list_backorder_allocations(release_line_id):
    data = _ok("list_backorder_allocations",
               api_client.list_backorder_allocations(
                   WH_MGR, params={"release_line_id": release_line_id}))
    assert isinstance(data, list), "backorder-allocations list must return an array"
    return data


# ---------------------------------------------------------------------------
# Tier 3 — composite scenarios
# ---------------------------------------------------------------------------

def setup_requested_release(item_kind="ea", line_qty=1, line_price=5000,
                            stock_qty=5, credit_limit_cents=100_000,
                            pricing_mode="FIRM_PRICE", **job_overrides):
    """Contractor + item (+ stock) + job + awarded quote + REQUESTED release."""
    contractor = create_contractor("Scenario Electric", credit_limit_cents)
    if item_kind == "ea":
        item = create_ea_item(list_price_cents=line_price)
    else:
        item = create_foot_item()
    if stock_qty is not None:
        receive_stock(item["id"], stock_qty)
    job = create_job_account(contractor["id"], "Scenario Job",
                             pricing_mode=pricing_mode, **job_overrides)
    quote = create_awarded_quote(job["id"],
                                 [(item["id"], line_qty, line_price)])
    release = create_release(job["id"], quote["id"],
                             [(item["id"], line_qty)])
    return {"contractor": contractor, "item": item, "job": job,
            "quote": quote, "release": release}


def setup_allocated_release(**kwargs):
    ctx = setup_requested_release(**kwargs)
    credit_approve_release(ctx["release"]["id"])
    ctx["release"] = allocate_release(ctx["release"]["id"])
    assert ctx["release"]["status"] == "ALLOCATED"
    return ctx


def setup_delivered_release(**kwargs):
    ctx = setup_allocated_release(**kwargs)
    walk_release(ctx["release"]["id"], "DELIVERED")
    ctx["release"] = get_release(ctx["release"]["id"])
    return ctx


def setup_partially_allocated_release(stock_qty=100, request_qty=300,
                                      credit_limit_cents=10_000_000):
    """FOOT release that the warehouse cannot fully cover: line allocated up
    to stock, one OPEN backorder for the remainder, release PARTIALLY_ALLOCATED."""
    contractor = create_contractor("Backorder Electric", credit_limit_cents)
    thhn = create_foot_item()
    receive_stock(thhn["id"], stock_qty)
    job = create_job_account(contractor["id"], "Backorder Job",
                             jobsite_address="8 Site Rd")
    quote = create_awarded_quote(job["id"],
                                 [(thhn["id"], request_qty, THHN_PRICE_CENTS)])
    release = create_release(job["id"], quote["id"],
                             [(thhn["id"], request_qty)])
    credit_approve_release(release["id"])
    release = allocate_release(release["id"])
    assert release["status"] == "PARTIALLY_ALLOCATED", (
        f"Setup failed: expected PARTIALLY_ALLOCATED, got {release['status']}")
    line = list_release_lines(release["id"])[0]
    backorders = list_backorder_allocations(line["id"])
    assert len(backorders) == 1, "Setup failed: expected exactly one backorder"
    return {"contractor": contractor, "item": thhn, "job": job,
            "quote": quote, "release": release, "line": line,
            "backorder": backorders[0]}


def setup_credit_hold_scenario(second_job=False, pending_release_on=None,
                               draft_quote_on_j1=False):
    """Drive a contractor (limit 20000) into credit contagion.

    ESCALATION job J1 holds a release for 300 ft of THHN quoted at 45.25 with
    the August index at 100 (estimate 15075). Once the September index jumps
    to 200 and the clock moves to 2026-09-05, the release is scheduled,
    delivered, and invoiced at 28650 — pushing invoiced_balance_cents over the
    limit and placing every OPEN job account of the contractor on CREDIT_HOLD.

    Options:
      second_job            — add a plain FIRM job J2 (contagion target).
      pending_release_on    — "j1" or "j2": leave a REQUESTED breaker release
                              (1000 on J1 / 5000 on J2) created before the
                              breach.
      draft_quote_on_j1     — leave an unsubmitted DRAFT quote on J1.
    """
    contractor = create_contractor("Hold Electric", 20_000)
    thhn = create_foot_item()
    brk = create_ea_item(list_price_cents=1000)
    receive_stock(thhn["id"], 300)
    set_index_reading("2026-08", 100.0)
    j1 = create_job_account(contractor["id"], "Esc Job",
                            jobsite_address="11 Site Rd",
                            pricing_mode="ESCALATION")
    j2 = (create_job_account(contractor["id"], "Firm Job",
                             jobsite_address="12 Site Rd")
          if second_job else None)
    q1 = create_awarded_quote(j1["id"], [(thhn["id"], 300, THHN_PRICE_CENTS)])

    pending_release = None
    if pending_release_on == "j1":
        q2 = create_awarded_quote(j1["id"], [(brk["id"], 1, 1000)])
        pending_release = create_release(j1["id"], q2["id"], [(brk["id"], 1)])
    elif pending_release_on == "j2":
        assert j2 is not None, "pending_release_on='j2' requires second_job=True"
        q3 = create_awarded_quote(j2["id"], [(brk["id"], 1, 5000)])
        pending_release = create_release(j2["id"], q3["id"], [(brk["id"], 1)])

    draft_quote = None
    if draft_quote_on_j1:
        draft_quote = create_quote(j1["id"])
        add_quote_line(draft_quote["id"], brk["id"], 1, 1000)

    r1 = create_release(j1["id"], q1["id"], [(thhn["id"], 300)])
    walk_release(r1["id"], "ALLOCATED")
    set_index_reading("2026-09", 200.0)
    set_clock("2026-09-05T00:00:00Z")
    r1 = walk_release(r1["id"], "INVOICED", truck_id="T9",
                      delivery_date="2026-09-06", window=(8, 12))

    return {"contractor": contractor, "thhn": thhn, "brk": brk, "j1": j1,
            "j2": j2, "q1": q1, "r1": r1, "pending_release": pending_release,
            "draft_quote": draft_quote}


def setup_firm_and_escalation_delivered_pair():
    """Two delivered releases on the same THHN line (200 ft @ 45.25), one on a
    FIRM_PRICE job and one on an uncapped ESCALATION job, ready to invoice in
    September after the index moved 100 -> 110."""
    contractor = create_contractor("Acme Electric", 10_000_000)
    thhn = create_foot_item()
    receive_stock(thhn["id"], 1000)
    set_index_reading("2026-08", 100.0)
    jf = create_job_account(contractor["id"], "Firm Job",
                            jobsite_address="1 Site Rd",
                            pricing_mode="FIRM_PRICE")
    je = create_job_account(contractor["id"], "Esc Job",
                            jobsite_address="2 Site Rd",
                            pricing_mode="ESCALATION")
    qf = create_awarded_quote(jf["id"], [(thhn["id"], 200, THHN_PRICE_CENTS)])
    qe = create_awarded_quote(je["id"], [(thhn["id"], 200, THHN_PRICE_CENTS)])
    rf = create_release(jf["id"], qf["id"], [(thhn["id"], 200)])
    walk_release(rf["id"], "DELIVERED", truck_id="T1",
                 delivery_date="2026-08-10", window=(8, 12))
    re = create_release(je["id"], qe["id"], [(thhn["id"], 200)])
    walk_release(re["id"], "DELIVERED", truck_id="T2",
                 delivery_date="2026-08-10", window=(8, 12))
    set_index_reading("2026-09", 110.0)
    set_clock("2026-09-05T00:00:00Z")
    return {"contractor": contractor, "thhn": thhn, "jf": jf, "je": je,
            "qf": qf, "qe": qe, "rf": get_release(rf["id"]),
            "re": get_release(re["id"])}


def setup_cut_boundary_delivered_pair():
    """FIRM job with two delivered releases straddling the 500-ft reel:
    RA ships 499 ft (cut charge applies), RB ships 500 ft (full reel)."""
    contractor = create_contractor("Gamma Electric", 10_000_000)
    thhn = create_foot_item()
    receive_stock(thhn["id"], 1200)
    job = create_job_account(contractor["id"], "Cut Job",
                             jobsite_address="4 Site Rd")
    quote = create_awarded_quote(job["id"], [
        (thhn["id"], 499, THHN_PRICE_CENTS),
        (thhn["id"], 500, THHN_PRICE_CENTS),
    ])
    ra = create_release(job["id"], quote["id"], [(thhn["id"], 499)])
    walk_release(ra["id"], "DELIVERED", truck_id="T1",
                 delivery_date="2026-08-05", window=(8, 10))
    rb = create_release(job["id"], quote["id"], [(thhn["id"], 500)])
    walk_release(rb["id"], "DELIVERED", truck_id="T1",
                 delivery_date="2026-08-06", window=(8, 10))
    return {"contractor": contractor, "thhn": thhn, "job": job,
            "quote": quote, "ra": get_release(ra["id"]),
            "rb": get_release(rb["id"])}


def setup_two_release_backorder_waterfall():
    """Two FIRM jobs, each with a PARTIALLY_ALLOCATED release for 100 ft of
    THHN against zero stock: two OPEN backorders of 100 ft, R1 older than R2."""
    contractor = create_contractor("Waterfall Electric", 10_000_000)
    thhn = create_foot_item()
    j1 = create_job_account(contractor["id"], "WF Job 1",
                            jobsite_address="41 Site Rd")
    j2 = create_job_account(contractor["id"], "WF Job 2",
                            jobsite_address="42 Site Rd")
    q1 = create_awarded_quote(j1["id"], [(thhn["id"], 100, THHN_PRICE_CENTS)])
    q2 = create_awarded_quote(j2["id"], [(thhn["id"], 100, THHN_PRICE_CENTS)])
    r1 = create_release(j1["id"], q1["id"], [(thhn["id"], 100)])
    credit_approve_release(r1["id"])
    r1 = allocate_release(r1["id"])
    r2 = create_release(j2["id"], q2["id"], [(thhn["id"], 100)])
    credit_approve_release(r2["id"])
    r2 = allocate_release(r2["id"])
    assert r1["status"] == "PARTIALLY_ALLOCATED"
    assert r2["status"] == "PARTIALLY_ALLOCATED"
    line1 = list_release_lines(r1["id"])[0]
    line2 = list_release_lines(r2["id"])[0]
    bo1 = list_backorder_allocations(line1["id"])[0]
    bo2 = list_backorder_allocations(line2["id"])[0]
    return {"contractor": contractor, "thhn": thhn, "j1": j1, "j2": j2,
            "r1": r1, "r2": r2, "line1": line1, "line2": line2,
            "bo1": bo1, "bo2": bo2}


def setup_truck_window_world():
    """Three jobs each holding an ALLOCATED breaker release; R1 is already
    scheduled on truck T1 for 2026-08-20 window [8, 12)."""
    contractor = create_contractor("Truck Electric", 10_000_000)
    brk = create_ea_item()
    receive_stock(brk["id"], 10)
    jobs, quotes, releases = [], [], []
    for i in range(3):
        job = create_job_account(contractor["id"], f"Job {i + 1}",
                                 jobsite_address=f"{19 + i} Site Rd")
        quote = create_awarded_quote(job["id"],
                                     [(brk["id"], 1, BRK_PRICE_CENTS)])
        release = create_release(job["id"], quote["id"], [(brk["id"], 1)])
        credit_approve_release(release["id"])
        release = allocate_release(release["id"])
        assert release["status"] == "ALLOCATED"
        jobs.append(job)
        quotes.append(quote)
        releases.append(release)
    schedule_release(releases[0]["id"], truck_id="T1",
                     delivery_date="2026-08-20", window_start_hour=8,
                     window_end_hour=12)
    return {"contractor": contractor, "brk": brk, "jobs": jobs,
            "quotes": quotes, "releases": releases}


def setup_past_window_world():
    """R1 scheduled on truck T1 for 2026-08-20 window [8, 12) while the clock
    reads 2026-08-15; R2 (another job) ALLOCATED; the clock then advances to
    2026-08-25 so any 2026-08-20 delivery is in the past."""
    contractor = create_contractor("Past Electric", 10_000_000)
    brk = create_ea_item()
    receive_stock(brk["id"], 10)
    j1 = create_job_account(contractor["id"], "Job A",
                            jobsite_address="13 Site Rd")
    j2 = create_job_account(contractor["id"], "Job B",
                            jobsite_address="14 Site Rd")
    q1 = create_awarded_quote(j1["id"], [(brk["id"], 1, BRK_PRICE_CENTS)])
    q2 = create_awarded_quote(j2["id"], [(brk["id"], 1, BRK_PRICE_CENTS)])
    set_clock("2026-08-15T00:00:00Z")
    r1 = create_release(j1["id"], q1["id"], [(brk["id"], 1)])
    credit_approve_release(r1["id"])
    allocate_release(r1["id"])
    schedule_release(r1["id"], truck_id="T1", delivery_date="2026-08-20",
                     window_start_hour=8, window_end_hour=12)
    r2 = create_release(j2["id"], q2["id"], [(brk["id"], 1)])
    credit_approve_release(r2["id"])
    r2 = allocate_release(r2["id"])
    assert r2["status"] == "ALLOCATED"
    set_clock("2026-08-25T00:00:00Z")
    return {"contractor": contractor, "brk": brk, "j1": j1, "j2": j2,
            "q1": q1, "q2": q2, "r1": r1, "r2": r2}


def setup_rebate_claim_world(manufacturer="Southwire", sku="SWD-SENSOR",
                             unit_price=None, per_release_qty=1,
                             num_releases=2, tiers=((0, 0.05),),
                             period=("2026-08-01", "2026-08-31"),
                             move_clock_past_end=True):
    """Rebate program + claim. When unit_price is given, invoices
    num_releases releases of an EA item (one line each) at the default clock
    so they land inside the August period, then opens the claim. The clock is
    moved past period end when move_clock_past_end is true."""
    program_resp = api_client.create_rebate_program(
        create_rebate_program_payload(
            manufacturer_name=manufacturer, period_start=period[0],
            period_end=period[1],
            tiers=[{"threshold_cents": t, "rebate_pct": p} for t, p in tiers]),
        REBATE_CLERK)
    program = _ok("create_rebate_program", program_resp)

    contractor = item = job = quote = None
    releases = []
    if unit_price is not None:
        contractor = create_contractor("Rebate Electric", 10_000_000)
        item = create_ea_item(sku=sku, manufacturer_name=manufacturer,
                              list_price_cents=unit_price)
        receive_stock(item["id"], 10)
        job = create_job_account(contractor["id"], "Rebate Job",
                                 jobsite_address="3 Site Rd")
        quote = create_awarded_quote(
            job["id"],
            [(item["id"], per_release_qty * num_releases, unit_price)])
        for i in range(num_releases):
            release = create_release(job["id"], quote["id"],
                                     [(item["id"], per_release_qty)])
            walk_release(release["id"], "INVOICED", truck_id="T1",
                         delivery_date=f"2026-08-{2 + i:02d}", window=(8, 10))
            releases.append(get_release(release["id"]))

    claim_resp = api_client.create_rebate_claim(
        create_rebate_claim_payload(rebate_program_id=program["id"]),
        REBATE_CLERK)
    claim = _ok("create_rebate_claim", claim_resp, expected_state="DRAFT")
    if move_clock_past_end:
        set_clock("2026-09-01T00:00:00Z")
    return {"program": program, "contractor": contractor, "item": item,
            "job": job, "quote": quote, "releases": releases, "claim": claim}


def get_rebate_claim(claim_id):
    return _ok("get_rebate_claim",
               api_client.get_rebate_claim(claim_id, REBATE_CLERK))


def setup_draft_quote_with_substitution(submit_after=False):
    """DRAFT quote on BRK-20A with a PROPOSED substitution to BRK-20B.
    When submit_after is true the quote is SUBMITTED after the proposal."""
    contractor = create_contractor("Sub Electric", 100_000)
    item_a = create_ea_item(sku="BRK-20A", manufacturer_name="SquareD",
                            list_price_cents=2500)
    item_b = create_ea_item(sku="BRK-20B", manufacturer_name="Eaton",
                            list_price_cents=2400)
    job = create_job_account(contractor["id"], "Sub Job",
                             jobsite_address="18 Site Rd")
    quote = create_quote(job["id"])
    line = add_quote_line(quote["id"], item_a["id"], 4, 2500)
    sub = create_substitution(line["id"], item_b["id"], "A on shortage")
    if submit_after:
        submit_quote(quote["id"])
    return {"contractor": contractor, "item_a": item_a, "item_b": item_b,
            "job": job, "quote": quote, "line": line, "sub": sub}
