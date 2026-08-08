"""Patient statements: zero-balance send guard and aging-bucket boundaries
(day 90 vs day 91 into collections).

Translates the zero-patient-balance boundary difficulty instance plus the
statement-aging corner instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_account_manager_headers, make_payment_poster_headers,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
PP = make_payment_poster_headers()


def _draft_statement_zero_balance(api):
    """Scrubbed claim with patient_responsibility_cents == 0, and a DRAFT statement
    whose statement_amount_cents is therefore 0. Returns the statement id."""
    ctx = fx.setup_scrubbed_claim(
        api, prices={"99213": 10000}, credential="none", enrollment="none",
        deductible_remaining_cents=0, coinsurance_pct=0, copay_cents=0,
        lines=[{"cpt_code": "99213", "units": 1, "charge_amount_cents": 15000}],
        coder_user_id="coder-6")
    stmt = fx.new_statement(api, ctx["claim"]["id"])
    return stmt["id"]


# ---- Difficulty: boundary_precision_check / zero-balance statement send rejected ----
def test_send_zero_balance_statement_rejected(api):
    """PRD §3.7: "A `PaymentPoster` sends the statement to the patient, moving it from
    `DRAFT` to `SENT`, which is permitted only when the `statement_amount_cents` is
    greater than 0."
    PRD §3: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/zero_patient_balance_statement_send_rejected
    """
    stmt_id = _draft_statement_zero_balance(api)
    resp = api.send_statement(stmt_id, PP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_zero_balance_statement_stays_draft(api):
    """PRD §3.7: "the statement copies the claim's `practice_id` into its own
    `practice_id` for practice-scoped queries, opens its `statement_amount_cents` at the
    claim's current `patient_responsibility_cents`, sets `amount_paid_cents` to 0, leaves
    `first_sent_date` null, and starts in `DRAFT` with `aging_bucket` of `CURRENT`."

    Design: Difficulty/boundary_precision_check/zero_patient_balance_statement_send_rejected
    """
    stmt_id = _draft_statement_zero_balance(api)
    api.send_statement(stmt_id, PP)
    stmt = validate_success(api.get_statement(stmt_id, PP), 200)
    assert stmt["status"] == "DRAFT", stmt["status"]
    assert stmt["statement_amount_cents"] == 0, stmt["statement_amount_cents"]


# ---- Corner: calculations / aging day 90 is DAYS_61_90 ----
def test_statement_aging_day90_is_days_61_90(api):
    """PRD §3.7: "the bucket is `CURRENT` when the elapsed days are 30 or fewer,
    `DAYS_31_60` when they are 31 through 60, `DAYS_61_90` when they are 61 through 90,
    and `OVER_90` only when they strictly exceed 90 days. The bucket boundaries fall on
    the lower bucket: day 30 is still `CURRENT`, day 90 is still `DAYS_61_90`, and day 91
    is the first day in `OVER_90`."

    Design: Corner/calculations/statement_aging_day90_is_days_61_90
    """
    ctx = fx.setup_sent_statement(api, credential="none", enrollment="none",
                                  deductible_remaining_cents=3000, coinsurance_pct=0.20,
                                  copay_cents=2000, coder_user_id="coder-c3")
    fx.set_clock(api, "2026-08-30T00:00:00Z")
    stmt = validate_success(api.get_statement(ctx["statement"]["id"], PP), 200)
    assert stmt["aging_bucket"] == "DAYS_61_90", stmt["aging_bucket"]
    assert stmt["statement_amount_cents"] == 6400, stmt["statement_amount_cents"]


# ---- Corner: calculations / aging day 91 is OVER_90 and permits collections ----
def test_statement_aging_day91_over_90_allows_collections(api):
    """PRD §3.7: "`OVER_90` only when they strictly exceed 90 days ... day 91 is the
    first day in `OVER_90`."
    PRD §3.7: "When a statement has aged into the `OVER_90` bucket, a `PaymentPoster` may
    send it to collections, moving it from `SENT` or `PARTIAL` to `COLLECTIONS`; the move
    is allowed only when the current `aging_bucket` is `OVER_90`."

    Design: Corner/calculations/statement_aging_day91_over_90_allows_collections
    """
    ctx = fx.setup_sent_statement(api, credential="none", enrollment="none",
                                  deductible_remaining_cents=3000, coinsurance_pct=0.20,
                                  copay_cents=2000, coder_user_id="coder-c3")
    fx.set_clock(api, "2026-08-31T00:00:00Z")
    stmt = validate_success(api.statement_collections(ctx["statement"]["id"], PP), 200)
    assert stmt["status"] == "COLLECTIONS", stmt["status"]
    assert stmt["aging_bucket"] == "OVER_90", stmt["aging_bucket"]
