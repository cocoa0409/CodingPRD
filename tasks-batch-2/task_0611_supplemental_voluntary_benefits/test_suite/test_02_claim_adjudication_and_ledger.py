"""Claim adjudication (provisional vs adjudicated), the benefit ledger and its
evaluation order, wellness cap-bypass, and immediate ledger consistency.

Difficulty queue A: dual_variant_calc (claim), combinatorial_formula (ledger),
compensating_invariant. Corner queue B: calculations (wellness),
consistency_model (immediate).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
    api_client,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / claim_provisional_vs_adjudicated_diverge_on_claim
# ---------------------------------------------------------------------------
def test_claim_filing_records_raw_schedule_amount(api):
    """PRD §3.8: "the claim is recorded in `SUBMITTED` `status` with a provisional
    `claimed_cents` equal to the raw scheduled flat benefit for the event — the
    `flat_benefit_cents` of the matching schedule line — and an `approved_cents`
    and `paid_cents` of 0; `claimed_cents` at this stage is the raw schedule
    amount, not yet limited by any cap or lifetime maximum."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_adjudicated_diverge_on_claim
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "FRACTURE", "flat_benefit_cents": 200000,
                 "lifetime_max_occurrences": 2},
                {"event_code": "HEART", "flat_benefit_cents": 300000},
            ]
        )
    )
    claim = fixtures.file_claim(enr["id"], acct["id"], "HEART", "2026-03-22T00:00:00Z")
    data = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert data["status"] == "SUBMITTED"
    assert data["claimed_cents"] == 300000
    assert data["approved_cents"] == 0
    assert data["paid_cents"] == 0


def test_claim_approval_caps_approved_to_remaining_room(api):
    """PRD §3.8: "the remaining annual room is the product's
    `annual_benefit_cap_cents` minus the enrollment's current
    `benefit_paid_cents`, floored at 0, and `approved_cents` is the lesser of
    `claimed_cents` and that remaining room"

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_adjudicated_diverge_on_claim
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "FRACTURE", "flat_benefit_cents": 200000,
                 "lifetime_max_occurrences": 2},
                {"event_code": "HEART", "flat_benefit_cents": 300000},
            ]
        )
    )
    # Two FRACTURE(200000) approved+paid -> benefit_paid_cents = 400000.
    fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-21T00:00:00Z"
    )
    # Cap remaining now 100000; HEART claimed 300000 -> approved min(300000,100000).
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "HEART", "2026-03-22T00:00:00Z"
    )
    cdata = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert cdata["claimed_cents"] == 300000
    assert cdata["approved_cents"] == 100000
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["benefit_paid_cents"] == 500000
    assert edata["benefit_remaining_cents"] == 0


# ---------------------------------------------------------------------------
# combinatorial_formula / benefit_ledger_eval_order_circular_cap
# ---------------------------------------------------------------------------
def test_ledger_accumulates_across_two_approvals_in_order(api):
    """PRD §3.8: "On a successful non-wellness approval the enrollment's
    `benefit_paid_cents` is increased by `approved_cents` and
    `benefit_remaining_cents` is recomputed as the cap minus the new paid total,
    floored at 0; wellness approvals leave the ledger untouched."

    Design: Difficulty/combinatorial_formula/benefit_ledger_eval_order_circular_cap
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "FRACTURE", "flat_benefit_cents": 200000},
                {"event_code": "HEART", "flat_benefit_cents": 300000},
            ]
        )
    )
    f_claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    h_claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "HEART", "2026-03-21T00:00:00Z"
    )
    fdata = validate_success(api.get_claim(f_claim["id"], _ADMIN))
    hdata = validate_success(api.get_claim(h_claim["id"], _ADMIN))
    assert fdata["approved_cents"] == 200000
    assert hdata["approved_cents"] == 300000


def test_ledger_reaches_exact_cap_after_two_approvals(api):
    """PRD §3.8: "`approved_cents` is the lesser of `claimed_cents` and that
    remaining room; if the remaining room is 0 the adjudication would yield 0,
    which is exactly the exhausted case rejected above."

    Design: Difficulty/combinatorial_formula/benefit_ledger_eval_order_circular_cap
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "FRACTURE", "flat_benefit_cents": 200000},
                {"event_code": "HEART", "flat_benefit_cents": 300000},
            ]
        )
    )
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "HEART", "2026-03-21T00:00:00Z"
    )
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["benefit_paid_cents"] == 500000
    assert edata["benefit_remaining_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: calculations / wellness_claim_uncapped_bypasses_benefit_ledger
# ---------------------------------------------------------------------------
def test_wellness_claim_uncapped_does_not_touch_ledger(api):
    """PRD §3.8: "For a wellness line, the approval is uncapped: `approved_cents`
    equals `claimed_cents`, the payout bypasses the annual cap entirely, and it
    does not touch `benefit_paid_cents`."

    Design: Corner/calculations/wellness_claim_uncapped_bypasses_benefit_ledger
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "BIGEVENT", "flat_benefit_cents": 500000},
                {"event_code": "WELLNESS_SCREENING", "flat_benefit_cents": 5000,
                 "is_wellness": True, "lifetime_max_occurrences": 1},
            ]
        )
    )
    # Exhaust the cap with one BIGEVENT (500000).
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "BIGEVENT", "2026-03-20T00:00:00Z"
    )
    # Wellness claim approves at full 5000 even though remaining is 0.
    w_claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "WELLNESS_SCREENING", "2026-03-21T00:00:00Z"
    )
    wdata = validate_success(api.get_claim(w_claim["id"], _ADMIN))
    assert wdata["approved_cents"] == 5000
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["benefit_paid_cents"] == 500000
    assert edata["benefit_remaining_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate_consistency_benefit_ledger_visible
# ---------------------------------------------------------------------------
def test_benefit_ledger_visible_immediately_after_approval(api):
    """PRD §3.8: "On a successful non-wellness approval the enrollment's
    `benefit_paid_cents` is increased by `approved_cents` and
    `benefit_remaining_cents` is recomputed as the cap minus the new paid total,
    floored at 0"

    Design: Corner/consistency_model/immediate_consistency_benefit_ledger_visible_in_response
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["benefit_paid_cents"] == 200000
    assert data["benefit_remaining_cents"] == 300000
