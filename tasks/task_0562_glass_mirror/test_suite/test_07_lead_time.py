"""Lead-time estimation: the quoted (queue-blind) variant vs the committed variant that
folds in the current scheduled furnace backlog."""
from test_helpers import validate_success, TEST_USERS
from test_helpers import fixtures as fx

LINE_90_SQFT = {
    "product_type": "SHOWER_ENCLOSURE", "glass_type": "TEMPERED", "thickness_mm": 10,
    "width_in": 60, "height_in": 72, "quantity": 3,  # 30 sqft/pane * 3 = 90 sqft
}
LINE_15_SQFT = {
    "product_type": "SHOWER_ENCLOSURE", "glass_type": "TEMPERED", "thickness_mm": 10,
    "width_in": 30, "height_in": 72, "quantity": 1,  # 15 sqft
}


# ==========================================================================
# dual_variant_calc / lead_time_quoted_vs_committed_diverges
# ==========================================================================
def test_committed_lead_exceeds_quoted_when_backlog_present(api):
    """PRD §3.3: "The `quoted_lead_days` is a provisional estimate that ignores the furnace
    queue: it is a base fabrication allowance of 3 days, plus the number of days needed to
    fabricate this quote's glass, plus a fixed install allowance of 2 days. The fabrication
    days are the quote's total billable area — the sum over lines of `billable_sqft`
    multiplied by `quantity` — divided by a standard throughput of 50 square feet per day,
    rounded up to the next whole day."
    PRD §3.4: "The combined workload is the current scheduled backlog — the sum of
    `total_sqft` over *all* tempering batches in `SCHEDULED` status across the shop — added
    to this job's `job_fab_sqft`. Because the backlog term is included, identical glass
    yields a longer committed lead time than its quoted lead time whenever the furnace queue
    is non-empty."

    Design: Difficulty/dual_variant_calc/lead_time_quoted_vs_committed_diverges
    """
    account = fx.create_account(api, tier="GOLD", credit_limit_cents=100_000_000)
    # job0: 90 sqft, accepted; a SCHEDULED (uncompleted) batch leaves a 90-sqft backlog.
    q0 = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, q0["id"], **LINE_90_SQFT)
    fx.send_quote(api, q0["id"])
    accepted0 = fx.accept_quote(api, q0["id"], account["id"], account["version"])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch0 = fx.create_batch(api, accepted0["ordered_job_id"], furnace["id"])
    assert batch0["total_sqft"] == 90.0, batch0["total_sqft"]

    # quote1: 15 sqft; quoted ignores the 90-sqft backlog.
    q1 = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, q1["id"], **LINE_15_SQFT)
    sent1 = fx.send_quote(api, q1["id"])
    assert sent1["quoted_lead_days"] == 6, sent1["quoted_lead_days"]  # 3 + ceil(15/50) + 2

    current = fx.get_account(api, account["id"])  # version advanced by job0 accept
    accepted1 = fx.accept_quote(api, q1["id"], account["id"], current["version"])
    job1 = validate_success(api.get_job(accepted1["ordered_job_id"], TEST_USERS["shop_admin_headers"]), 200)
    # committed = 3 + ceil((90 + 15)/50) + 2 = 3 + 3 + 2 = 8
    assert job1["committed_lead_days"] == 8, job1["committed_lead_days"]
    assert job1["committed_lead_days"] != sent1["quoted_lead_days"]


def test_committed_equals_quoted_when_no_backlog(api):
    """PRD §3.4: "The `committed_lead_days` is the base fabrication allowance of 3 days, plus
    the number of days to fabricate the combined workload divided by the standard throughput
    of 50 square feet per day and rounded up to the next whole day, plus the fixed install
    allowance of 2 days."
    PRD §3.3: "The `quoted_lead_days` is a provisional estimate that ignores the furnace
    queue: it is a base fabrication allowance of 3 days, plus the number of days needed to
    fabricate this quote's glass, plus a fixed install allowance of 2 days."

    Design: Difficulty/dual_variant_calc/lead_time_quoted_vs_committed_diverges
    """
    account = fx.create_account(api, tier="GOLD", credit_limit_cents=100_000_000)
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **LINE_15_SQFT)
    sent = fx.send_quote(api, quote["id"])
    assert sent["quoted_lead_days"] == 6, sent["quoted_lead_days"]
    accepted = fx.accept_quote(api, quote["id"], account["id"], account["version"])
    job = validate_success(api.get_job(accepted["ordered_job_id"], TEST_USERS["shop_admin_headers"]), 200)
    # No SCHEDULED batches anywhere: committed = 3 + ceil(15/50) + 2 = 6 == quoted
    assert job["committed_lead_days"] == 6, job["committed_lead_days"]
    assert job["committed_lead_days"] == sent["quoted_lead_days"]
