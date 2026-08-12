"""Claim lock/unlock cycle, filing window boundary, release, lazy foreclosure
expiry, pre-judgment interest tiers, and the state-over-temporal validation
priority (PRD §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_draft_claim,
    create_verified_project,
    file_claim,
    get_lien_claim,
    get_project,
    lock_claim,
    make_customer_admin_headers,
    order_notice,
    publish_rule,
    record_proof,
    record_span,
    serve_notice,
    set_clock,
    setup_filed_claim,
    setup_locked_claim,
    setup_project_with_proofed_notice,
    setup_verified_ca_project,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Lock/unlock revision cycle (queue A: non_linear_state_machine) ──

def _setup_unlock_cycle():
    """Verified CA project (contract 200000, no payments/waivers) with a DRAFT
    claim."""
    ctx = setup_project_with_proofed_notice(
        name="Lock Job", county="Marin", contract_value_cents=200000,
    )
    ctx["claim"] = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    return ctx


def test_unlock_clears_pinned_fields():
    """PRD §3.5: "Unlocking reverses the lock: a `CustomerAdmin` moves an
    `AMOUNT_LOCKED` claim back to `DRAFT`, clearing `final_amount_cents`,
    `gross_snapshot_cents`, `filing_window_end`, and `locked_rule_id`, and
    recomputing the provisional amount."
    PRD §3.5: "Locking computes and pins everything the claim will need:
    `final_amount_cents`; `gross_snapshot_cents`, the gross claimable value as
    computed at lock; `locked_rule_id`, the identity of the effective rule; and
    `filing_window_end`, the `last_furnishing_date` plus the locked rule's
    `filing_window_days` in calendar days."

    Design: Difficulty/non_linear_state_machine/lien_lock_unlock_cycle_then_file
    """
    ctx = _setup_unlock_cycle()
    company_id = ctx["company"]["id"]
    claim_id = ctx["claim"]["id"]

    locked = lock_claim(claim_id, company_id)
    assert locked["status"] == "AMOUNT_LOCKED"
    assert locked["final_amount_cents"] == 200000
    assert locked["filing_window_end"] == "2026-09-08"
    assert locked["locked_rule_id"] == ctx["rule"]["id"]

    unlocked = validate_success(
        api.unlock_lien_claim(claim_id, make_customer_admin_headers(company_id)),
        200,
    )
    assert unlocked["status"] == "DRAFT"
    assert unlocked["final_amount_cents"] is None
    assert unlocked["gross_snapshot_cents"] is None
    assert unlocked["filing_window_end"] is None
    assert unlocked["locked_rule_id"] is None
    assert unlocked["provisional_amount_cents"] == 200000


def test_relock_then_file_computes_foreclosure_deadline():
    """PRD §3.5: "A successful filing moves the claim `AMOUNT_LOCKED` → `FILED`,
    stamps `filed_at` (null until this moment), freezes `final_amount_cents`,
    computes the previously null `foreclosure_deadline` as `filed_at` plus the
    locked rule's `foreclosure_deadline_days` calendar days"
    (filed 2026-07-01 + 90 calendar days = 2026-09-29.)

    Design: Difficulty/non_linear_state_machine/lien_lock_unlock_cycle_then_file
    """
    ctx = _setup_unlock_cycle()
    company_id = ctx["company"]["id"]
    claim_id = ctx["claim"]["id"]

    lock_claim(claim_id, company_id)
    api.unlock_lien_claim(claim_id, make_customer_admin_headers(company_id))
    relocked = lock_claim(claim_id, company_id)
    assert relocked["status"] == "AMOUNT_LOCKED"
    assert relocked["final_amount_cents"] == 200000

    filed = file_claim(claim_id, "2026-07-01")
    assert filed["status"] == "FILED"
    assert filed["filed_at"] == "2026-07-01"
    assert filed["foreclosure_deadline"] == "2026-09-29"


# ─── Filing-window boundary (queue B) ────────────────────────────────

def test_filing_window_last_day_inclusive():
    """PRD §3.5: "the `filed_at` must fall on or before the pinned
    `filing_window_end`, the last day inclusive, or the filing is rejected with
    `ERR_FILING_WINDOW_CLOSED` (HTTP 409)."
    (window end 2026-09-08; filing again on the last day succeeds after the
    rejected attempt left the claim AMOUNT_LOCKED.)

    Design: Corner/calculations/filing_window_last_day_inclusive
    """
    ctx = setup_locked_claim(name="FW Job", contract_value_cents=400000)
    claim_id = ctx["claim"]["id"]
    assert ctx["claim"]["filing_window_end"] == "2026-09-08"

    res = api.file_lien_claim(claim_id, {"filed_at": "2026-09-09"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_FILING_WINDOW_CLOSED)
    assert get_lien_claim(claim_id)["status"] == "AMOUNT_LOCKED"

    filed = file_claim(claim_id, "2026-09-08")
    assert filed["status"] == "FILED"
    assert filed["foreclosure_deadline"] == "2026-12-07"


# ─── Pre-judgment interest tiers (queue B) ───────────────────────────

def test_prejudgment_interest_tier_boundary():
    """PRD §3.5: "the annual rate is the pinned rule's `interest_annual_rate`,
    increased by a tier bump of two percentage points (0.02) when the base
    strictly exceeds the tier threshold of 1,000,000 cents, and equal to the
    pinned rate otherwise — the tier test depends on the base alone, never on
    the total, which keeps the definition free of circularity." and "The
    `interest_cents` is the base multiplied by the rate, multiplied by the day
    count, divided by 365, rounded half-up to whole cents, and the
    `total_with_interest_cents` is the base plus interest, capped at a maximum
    award of 1,000,000,000 cents"
    (30 days elapsed; A: 500000 at 0.10 -> 4110; B: 2000000 at 0.12 -> 19726.)

    Design: Corner/calculations/prejudgment_interest_tier_boundary
    """
    company = create_company(name="Int Co", seed_balance_cents=1000000)
    publish_rule()
    claims = {}
    for name, contract in (("Int A", 500000), ("Int B", 2000000)):
        project, parties = create_verified_project(
            company["id"], name=name, contract_value_cents=contract,
        )
        record_span(project["id"], company["id"])
        notice = order_notice(project["id"], company["id"], parties["OWNER"]["id"])
        serve_notice(notice["id"], "2026-05-20")
        record_proof(notice["id"])
        claim = create_draft_claim(project["id"], company["id"])
        lock_claim(claim["id"], company["id"])
        claims[name] = file_claim(claim["id"], "2026-07-01")

    set_clock("2026-07-31T00:00:00Z")

    claim_a = get_lien_claim(claims["Int A"]["id"])
    assert claim_a["interest_cents"] == 4110
    assert claim_a["total_with_interest_cents"] == 504110

    claim_b = get_lien_claim(claims["Int B"]["id"])
    assert claim_b["interest_cents"] == 19726
    assert claim_b["total_with_interest_cents"] == 2019726


# ─── Release lockdown and lazy foreclosure expiry (queue B) ──────────

def test_lien_release_twice_rejected():
    """PRD §3.5: "Either way, release decrements the project's
    `open_lien_count` by one" and "The claim's full state space is `DRAFT`,
    `AMOUNT_LOCKED`, `FILED`, `RELEASED`, `BONDED_OFF`, `FORECLOSED`, and
    `EXPIRED`, the latter four being terminal."
    PRD §2.10: "when no specific state error applies, the generic
    `ERR_INVALID_STATE` is used."

    Design: Corner/state_machines/lien_release_twice_rejected
    """
    ctx = setup_filed_claim(name="LR Job", contract_value_cents=100000)
    claim_id = ctx["claim"]["id"]
    company_id = ctx["company"]["id"]

    released = validate_success(
        api.release_lien_claim(claim_id, make_customer_admin_headers(company_id)),
        200,
    )
    assert released["status"] == "RELEASED"

    res = api.release_lien_claim(claim_id, make_customer_admin_headers(company_id))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_project(ctx["project"]["id"])["open_lien_count"] == 0


def test_lien_auto_expires_after_foreclosure_deadline():
    """PRD §3.5: "A `FILED` claim whose `foreclosure_deadline` falls behind the
    logical clock — with no referral for the claim having reached `SUIT_FILED` —
    auto-expires, lazily, on its next read or mutation: the claim moves to
    `EXPIRED`, the project's `open_lien_count` decrements by one, the posture is
    recomputed, and open referrals are cancelled with `cancel_reason`
    `MOOT_EXPIRED`."

    Design: Corner/state_machines/lien_auto_expires_after_foreclosure_deadline
    """
    ctx = setup_filed_claim(name="LX Job", contract_value_cents=100000,
                            filed_at="2026-07-01")
    assert ctx["claim"]["foreclosure_deadline"] == "2026-09-29"
    assert get_project(ctx["project"]["id"])["open_lien_count"] == 1

    set_clock("2026-09-30T00:00:00Z")

    assert get_lien_claim(ctx["claim"]["id"])["status"] == "EXPIRED"
    assert get_project(ctx["project"]["id"])["open_lien_count"] == 0


# ─── Validation priority: state over temporal (queue A) ──────────────

def test_file_draft_claim_reports_state_error_not_temporal():
    """PRD §2.10: "All remaining checks run as a fixed ladder. The first failing
    rung determines the response, and later rungs are never evaluated for that
    request" — rung 5 state preconditions include `ERR_CLAIM_NOT_LOCKED` while
    rung 9 temporal checks include `ERR_FILING_WINDOW_CLOSED`, so filing a
    never-locked claim after the would-be window reports the state error.
    PRD §3.5: "Only an `AMOUNT_LOCKED` claim can be filed — any other state
    fails with `ERR_CLAIM_NOT_LOCKED` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/claim_file_from_draft_past_window_state_wins
    """
    ctx = setup_verified_ca_project(name="Prio Job", county="Butte")
    claim = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    set_clock("2026-12-01T00:00:00Z")  # past any filing window

    res = api.file_lien_claim(claim["id"], {"filed_at": "2026-11-01"}, _OPS_AGENT)
    err = validate_error(res, ApiErrorId.ERR_CLAIM_NOT_LOCKED)
    assert err["error_id"] != ApiErrorId.ERR_FILING_WINDOW_CLOSED
    assert get_lien_claim(claim["id"])["status"] == "DRAFT"


def test_file_locked_claim_past_window_reports_temporal_error():
    """PRD §2.10: "All remaining checks run as a fixed ladder. The first failing
    rung determines the response, and later rungs are never evaluated for that
    request" — with the state rung satisfied (claim AMOUNT_LOCKED), the temporal
    rung is reached and reports `ERR_FILING_WINDOW_CLOSED` per PRD §3.5: "the
    `filed_at` must fall on or before the pinned `filing_window_end`, the last
    day inclusive, or the filing is rejected with `ERR_FILING_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/claim_file_from_draft_past_window_state_wins
    """
    ctx = setup_locked_claim(name="Prio Job", county="Butte")
    claim_id = ctx["claim"]["id"]
    set_clock("2026-12-01T00:00:00Z")  # window ended 2026-09-08

    res = api.file_lien_claim(claim_id, {"filed_at": "2026-11-01"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_FILING_WINDOW_CLOSED)
    assert get_lien_claim(claim_id)["status"] == "AMOUNT_LOCKED"
