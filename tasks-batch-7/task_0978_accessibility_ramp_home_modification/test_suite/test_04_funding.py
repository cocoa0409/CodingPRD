"""Funding sources, allocations, posture bands, and the commit/reverse invariant."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_funding_source, assert_funding_allocation,
    create_case, create_assessed_case, create_draft_quote, add_quote_line,
    setup_case_with_draft_quote, setup_submitted_quote, setup_under_review_quote,
    setup_approved_quote, add_funding_source, approve_funding, add_allocation,
    submit_quote, set_clock, get_case, case_version,
)

IC = TEST_USERS["intake_coordinator_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: review fork — APPROVED branch commits allocations
# ---------------------------------------------------------------------------

def _setup_fork(api):
    """Quote UNDER_REVIEW (total 30000) + APPROVED source 50000 + PENDING
    QUOTE_LEVEL allocation 30000."""
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=30000, contingency_pct=0.0)
    src = setup_approved_funding_for(case_id=case["id"], approved=50000)
    submit_quote(case["id"], quote["id"])
    validate_success(api.start_quote_review(case["id"], quote["id"], FC), 200)
    alloc = add_allocation(case["id"], src["id"], quote["id"], 30000)
    return case, quote, src, alloc


def setup_approved_funding_for(case_id, approved):
    return approve_funding(case_id, add_funding_source(
        case_id, approved, source_type="VA_BENEFIT", program_name="VA HISA")["id"], approved)


def test_quote_approve_commits_quote_and_stamps_decision(api):
    """PRD §3.3: "A successful approval moves the quote to `APPROVED`, stamps
    `decided_at`, and commits money: every `PENDING` funding allocation attached
    to the quote becomes `COMMITTED`, each such allocation's `committed_at` is
    stamped, and each allocation's amount is subtracted from its funding source's
    `remaining_cents`."

    Design: Difficulty/non_linear_state_machine/quote_review_fork_approve_commit_vs_reject_release
    """
    case, quote, src, alloc = _setup_fork(api)
    approved = validate_success(api.approve_quote(case["id"], quote["id"], FC), 200)
    assert approved["status"] == "APPROVED"
    assert approved["decided_at"] is not None


def test_quote_approve_commits_allocation_and_draws_source(api):
    """PRD §3.3: "every `PENDING` funding allocation attached to the quote becomes
    `COMMITTED`, each such allocation's `committed_at` is stamped, and each
    allocation's amount is subtracted from its funding source's `remaining_cents`."
    PRD §3.4: "Approval moves the source from `PENDING` to `APPROVED`, stamps
    `decision_date`, and initializes `remaining_cents` equal to the full
    `approved_cents`".

    Design: Difficulty/non_linear_state_machine/quote_review_fork_approve_commit_vs_reject_release
    """
    case, quote, src, alloc = _setup_fork(api)
    validate_success(api.approve_quote(case["id"], quote["id"], FC), 200)
    allocs, _ = validate_paginated(api.list_funding_allocations(case["id"], src["id"], IC))
    mine = {a["id"]: a for a in allocs}[alloc["id"]]
    assert mine["status"] == "COMMITTED"
    assert mine["committed_at"] is not None
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["remaining_cents"] == 20000, (
        "50000 - 30000 committed; the REJECTED branch would leave 50000")


# ---------------------------------------------------------------------------
# Difficulty: funding posture exact-equality boundary
# ---------------------------------------------------------------------------

def _setup_equality(api):
    """ASSESSED case, DRAFT quote total 20000, two PENDING sources 19999 + 1."""
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=10000, quantity=2,
                                              contingency_pct=0.0)
    fs_a = add_funding_source(case["id"], 19999, priority_rank=1,
                              source_type="MEDICAID_WAIVER", program_name="Waiver A")
    fs_b = add_funding_source(case["id"], 1, priority_rank=2,
                              source_type="CHARITY", program_name="Charity B")
    return case, quote, fs_a, fs_b


def test_funding_below_quoted_yields_partially_funded(api):
    """PRD §2.8: "When the funded amount is greater than zero but strictly less
    than `total_quoted_cents` the posture is `PARTIALLY_FUNDED`."

    Design: Difficulty/boundary_precision_check/funding_exact_equality_yields_fully_funded
    """
    case, quote, fs_a, fs_b = _setup_equality(api)
    approve_funding(case["id"], fs_a["id"], 19999)
    c = get_case(case["id"])
    assert c["total_funded_cents"] == 19999
    assert c["funding_posture"] == "PARTIALLY_FUNDED", "19999 < 20000 must stay PARTIALLY_FUNDED"


def test_funding_exact_equality_yields_fully_funded(api):
    """PRD §2.8: "When the funded amount exactly equals the quoted total the
    posture is `FULLY_FUNDED`." "`total_funded_cents` is the sum of the approved
    amounts of all of the case's funding sources whose status is APPROVED."

    Design: Difficulty/boundary_precision_check/funding_exact_equality_yields_fully_funded
    """
    case, quote, fs_a, fs_b = _setup_equality(api)
    approve_funding(case["id"], fs_a["id"], 19999)
    approve_funding(case["id"], fs_b["id"], 1)
    c = get_case(case["id"])
    assert c["total_funded_cents"] == 20000
    assert c["funding_posture"] == "FULLY_FUNDED", "equality (>= boundary) must flip the posture"


# ---------------------------------------------------------------------------
# Difficulty: restriction error beats fiscal error (priority pair)
# ---------------------------------------------------------------------------

def _setup_restriction_conflict_full(api):
    set_clock()
    case, _ = create_assessed_case(mobility_score=60, hazard_count=2,
                                   client_name="Milo Napp", client_address="10 Grant Ave",
                                   client_phone="555-0110")
    quote = create_draft_quote(case["id"], contingency_pct=0.0)
    line = add_quote_line(case["id"], quote["id"], line_type="EQUIPMENT_RENTAL",
                          description="Ramp rental month", quantity=1, unit="day",
                          unit_price_cents=5000, tax_rate_pct=0.0, sort_order=1)
    src = approve_funding(case["id"], add_funding_source(
        case["id"], 10000, source_type="STATE_GRANT", program_name="Perm-Only Grant",
        restrictions=["NO_RENTAL"])["id"], 10000)
    submit_quote(case["id"], quote["id"])
    return case, quote, line, src


def test_restriction_error_beats_fiscal_error(api):
    """PRD §2.6: "(9) allocating a funding source to line items its restrictions
    prohibit fails with `ERR_FUNDING_RESTRICTION_VIOLATION` (HTTP 422); (10)
    allocating more than a funding source's remaining balance fails with
    `ERR_ALLOCATION_EXCEEDS_REMAINING` (HTTP 422)". "Because the ladder is
    ordered, a single request can only ever surface the earliest failing check".

    Design: Difficulty/priority_pair_validation_conflict/allocation_restriction_error_beats_fiscal_error
    """
    case, quote, line, src = _setup_restriction_conflict_full(api)
    res = api.create_funding_allocation(
        case["id"], src["id"],
        {"quote_id": quote["id"], "quote_line_item_id": line["id"],
         "amount_cents": 20000, "allocation_type": "LINE_LEVEL"},
        FC)
    validate_error(res, ApiErrorId.ERR_FUNDING_RESTRICTION_VIOLATION, expected_status=422)


def test_restriction_rejection_creates_no_allocation(api):
    """PRD §3.4: "A new allocation starts in `PENDING` and stays there until the
    quote's decision". A rejected create must persist nothing.
    PRD §3.4: "Approval moves the source from `PENDING` to `APPROVED`, stamps
    `decision_date`, and initializes `remaining_cents` equal to the full
    `approved_cents`".

    Design: Difficulty/priority_pair_validation_conflict/allocation_restriction_error_beats_fiscal_error
    """
    case, quote, line, src = _setup_restriction_conflict_full(api)
    validate_error(api.create_funding_allocation(
        case["id"], src["id"],
        {"quote_id": quote["id"], "quote_line_item_id": line["id"],
         "amount_cents": 20000, "allocation_type": "LINE_LEVEL"},
        FC), ApiErrorId.ERR_FUNDING_RESTRICTION_VIOLATION, expected_status=422)
    allocs, _ = validate_paginated(api.list_funding_allocations(case["id"], src["id"], IC))
    assert allocs == [], "no allocation may be persisted for a rejected request"
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["remaining_cents"] == 10000


# ---------------------------------------------------------------------------
# Difficulty: commit/reverse conserves the funding pool
# ---------------------------------------------------------------------------

def _setup_commit(api):
    """Quote APPROVED with a 30000 QUOTE_LEVEL allocation on a 50000 source."""
    case, quote, src, alloc = setup_approved_quote(quote_total=30000, approved_cents=50000)
    return case, quote, src, alloc


def test_commit_decrements_remaining_cents(api):
    """PRD §3.3: "A successful approval moves the quote to `APPROVED`, stamps
    `decided_at`, and commits money: every `PENDING` funding allocation attached
    to the quote becomes `COMMITTED`, each such allocation's `committed_at` is
    stamped, and each allocation's amount is subtracted from its funding source's
    `remaining_cents`."

    Design: Difficulty/compensating_invariant/allocation_commit_reverse_conserves_remaining_cents
    """
    case, quote, src, alloc = _setup_commit(api)
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["remaining_cents"] == 20000, "50000 approved - 30000 committed"


def test_reverse_restores_remaining_cents_exactly(api):
    """PRD §3.4: "A `FundingCoordinator` may reverse a `COMMITTED` allocation
    provided no invoice has yet been paid against it; reversal moves the
    allocation to `REVERSED`, adds its `amount_cents` back to the source's
    `remaining_cents`, and recomputes the case's `total_funded_cents`."
    PRD §2.8: "`total_funded_cents` is the sum of the approved amounts of all of
    the case's funding sources whose status is APPROVED."

    Design: Difficulty/compensating_invariant/allocation_commit_reverse_conserves_remaining_cents
    """
    case, quote, src, alloc = _setup_commit(api)
    reversed_alloc = validate_success(
        api.reverse_funding_allocation(case["id"], src["id"], alloc["id"], FC), 200)
    assert reversed_alloc["status"] == "REVERSED"
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["remaining_cents"] == 50000, (
        "reverse must restore remaining to exactly approved_cents — zero drift")
    c = get_case(case["id"])
    assert c["total_funded_cents"] == 50000, "approved-source sum is unchanged by commit/reverse"


# ---------------------------------------------------------------------------
# Corner: posture bands, gap floor, source transitions, fiscal guard
# ---------------------------------------------------------------------------

def test_funding_posture_partially_funded_band(api):
    """PRD §2.8: "When the funded amount is greater than zero but strictly less
    than `total_quoted_cents` the posture is `PARTIALLY_FUNDED`."
    PRD §2.8: "`total_funded_cents` is the sum of the approved amounts of all of
    the case's funding sources whose status is APPROVED."

    Design: Corner/calculations/funding_posture_partially_funded_band
    """
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=10000, quantity=2,
                                              contingency_pct=0.0)
    approve_funding(case["id"], add_funding_source(
        case["id"], 10000, source_type="MEDICAID_WAIVER", program_name="W1")["id"], 10000)
    c = get_case(case["id"])
    assert c["funding_posture"] == "PARTIALLY_FUNDED"
    assert c["total_funded_cents"] == 10000


def test_funding_posture_overfunded_band(api):
    """PRD §2.8: "When the funded amount exceeds the quoted total the posture is
    `OVERFUNDED`."

    Design: Corner/calculations/funding_posture_overfunded_band
    """
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=10000, quantity=2,
                                              contingency_pct=0.0)
    approve_funding(case["id"], add_funding_source(
        case["id"], 25000, source_type="VA_BENEFIT", program_name="VA1")["id"], 25000)
    c = get_case(case["id"])
    assert c["funding_posture"] == "OVERFUNDED"
    assert c["total_funded_cents"] == 25000


def test_funding_gap_floored_at_zero_on_overfunding(api):
    """PRD §3.3: "Submission moves the quote from `DRAFT` to `SUBMITTED`, stamps
    `submitted_at`, computes `funding_gap_cents` as the quote's `total_cents`
    minus the case's `total_funded_cents` with the result floored at zero so it
    can never be negative, and moves the case from `QUOTE_DRAFTED` to
    `QUOTE_SUBMITTED`."

    Design: Corner/calculations/funding_gap_floored_at_zero_on_overfunding
    """
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=10000, quantity=2,
                                              contingency_pct=0.0)
    approve_funding(case["id"], add_funding_source(
        case["id"], 25000, source_type="VA_BENEFIT", program_name="VA2")["id"], 25000)
    submitted = submit_quote(case["id"], quote["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["funding_gap_cents"] == 0, "floored at zero; never -5000"
    assert submitted["submitted_at"] is not None


def test_funding_source_double_approve_rejected(api):
    """PRD §3.4: "Approval moves the source from `PENDING` to `APPROVED`".
    "`APPROVED`, `DENIED`, `WITHDRAWN`, and `EXHAUSTED` are all terminal."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/funding_source_double_approve_rejected
    """
    set_clock()
    case = create_case(client_name="Rae Sipp", client_address="18 Idem Ave",
                       client_phone="555-0220")
    src = approve_funding(case["id"], add_funding_source(
        case["id"], 7000, source_type="PRIVATE_INSURANCE", program_name="InsCo")["id"], 7000)
    assert src["status"] == "APPROVED"
    res = api.approve_funding_source(case["id"], src["id"],
                                     {"approved_cents": 7000,
                                      "expected_case_version": case_version(case["id"])}, FC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert after["status"] == "APPROVED"
    assert after["remaining_cents"] == 7000


def test_funding_source_withdraw_from_denied_rejected(api):
    """PRD §3.4: "Withdrawal moves a `PENDING` source to `WITHDRAWN` and releases
    every `PENDING` allocation it held." "`APPROVED`, `DENIED`, `WITHDRAWN`, and
    `EXHAUSTED` are all terminal."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/funding_source_withdraw_from_denied_rejected
    """
    case = create_case(client_name="Sam Tew", client_address="19 Deny Dr",
                       client_phone="555-0221")
    src = add_funding_source(case["id"], 9000, program_name="Grant Y")
    denied = validate_success(api.deny_funding_source(case["id"], src["id"], FC), 200)
    assert denied["status"] == "DENIED"
    res = api.withdraw_funding_source(case["id"], src["id"], FC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert after["status"] == "DENIED"


def test_allocation_above_remaining_rejected(api):
    """PRD §3.4: "The amount must not exceed the source's `remaining_cents`, or
    the create fails with `ERR_ALLOCATION_EXCEEDS_REMAINING`."

    Design: Corner/validations/allocation_above_remaining_rejected
    """
    set_clock()
    case, quote = setup_submitted_quote(unit_price_cents=5000, contingency_pct=0.0)
    src = approve_funding(case["id"], add_funding_source(
        case["id"], 10000, program_name="G1")["id"], 10000)
    res = api.create_funding_allocation(
        case["id"], src["id"],
        {"quote_id": quote["id"], "amount_cents": 10001, "allocation_type": "QUOTE_LEVEL"},
        FC)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDS_REMAINING, expected_status=422)
    after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert after["remaining_cents"] == 10000, "rejected allocation must not draw the source"


def test_funding_source_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/funding_source_not_found_returns_404
    """
    case = create_case(client_name="NF Fund", client_address="53 NF Rd",
                       client_phone="555-0603")
    res = api.get_funding_source(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND, expected_status=404)
