"""Shutoff scheduling/execution guardrails and adjudication preconditions:
arrears threshold (boundary), moratorium window overlap, shutoff protection,
validation precedence, and leak-approval state dependency.

Translates Difficulty queue: priority_pair_validation_conflict,
boundary_precision_check (arrears), resource_temporal_overlap (moratorium),
cross_entity_state_dependency (leak approve requires POSTED). Corner queue:
shutoff/leak precondition errors.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    setup_flat_past_due_account, setup_scheduled_shutoff,
    setup_pending_leak_on_draft,
    fixtures, factories, TEST_USERS, ApiErrorId,
)

CLERK = TEST_USERS["billing_clerk_headers"]
FIELDOPS = TEST_USERS["field_ops_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ===========================================================================
# Arrears threshold boundary (boundary_precision_check)
# ===========================================================================
def test_arrears_exactly_at_threshold_allows_shutoff(api):
    """PRD §3.9: "The account's `past_due_cents` must be at or above the schedule's
    `arrears_shutoff_threshold_cents`; below that, scheduling is rejected with
    `ERR_ARREARS_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/arrears_threshold_at_exact_value_allows_shutoff
    """
    # Flat schedule, potable 15000 @500/kgal = 7500, late_fee 0 -> past_due 7500
    account, bill, rs, cycle = setup_flat_past_due_account(potable=15000, arrears_threshold=7500)
    assert account["past_due_cents"] == 7500
    order = validate_success(
        api.create_shutoff_order(
            factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-10T00:00:00Z"),
            FIELDOPS), 201)
    assert order["status"] == "SCHEDULED"
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["billing_status"] == "SHUTOFF_PENDING"


def test_arrears_one_below_threshold_rejects_shutoff(api):
    """PRD §3.9: "The account's `past_due_cents` must be at or above the schedule's
    `arrears_shutoff_threshold_cents`; below that, scheduling is rejected with
    `ERR_ARREARS_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/arrears_threshold_at_exact_value_allows_shutoff
    """
    # past_due 7500 (potable 15000 @500) against a threshold of 7501 -> just below.
    account, bill, rs, cycle = setup_flat_past_due_account(potable=15000, arrears_threshold=7501)
    assert account["past_due_cents"] == 7500
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-10T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_ARREARS_BELOW_THRESHOLD.value)


def test_arrears_below_threshold_rejects_shutoff(api):
    """PRD §3.9: "The account's `past_due_cents` must be at or above the schedule's
    `arrears_shutoff_threshold_cents`; below that, scheduling is rejected with
    `ERR_ARREARS_BELOW_THRESHOLD`."

    Design: Corner/state_machines/error_arrears_below_threshold_on_shutoff
    """
    # Flat schedule, potable 6000 @500 = 3000 < 7500
    account, bill, rs, cycle = setup_flat_past_due_account(potable=6000, arrears_threshold=7500)
    assert account["past_due_cents"] == 3000
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-10T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_ARREARS_BELOW_THRESHOLD.value)


# ===========================================================================
# Shutoff protection (corner)
# ===========================================================================
def test_shutoff_protected_when_assistance_grants_protection(api):
    """PRD §3.9: "The account must not be protected: if it has an `ACTIVE` assistance
    enrollment that grants shutoff protection, scheduling is rejected with
    `ERR_SHUTOFF_PROTECTED`."

    Design: Corner/state_machines/shutoff_protected_when_assistance_grants_protection
    """
    # Flat schedule, potable 30000 @500 = 15000 arrears (well above 7500).
    # Protection is enrolled while the account is still CURRENT, so the account
    # ends in PAST_DUE (not DELINQUENT_PROTECTED) carrying an ACTIVE protection
    # enrollment — the only state from which the §3.9 protection guard is
    # reachable (scheduling out of any non-PAST_DUE state is an ERR_INVALID_STATE
    # of higher precedence per §2.9).
    account, bill, rs, cycle = fixtures.setup_protected_past_due_account(
        potable=30000, arrears_threshold=7500)
    assert account["billing_status"] == "PAST_DUE"
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-10T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_SHUTOFF_PROTECTED.value)


# ===========================================================================
# Moratorium window overlap (resource_temporal_overlap) + safety precedence
# ===========================================================================
def test_shutoff_schedule_inside_moratorium_window_barred(api):
    """PRD §3.9: "And no active moratorium may cover the `scheduled_for` date; if one
    does, scheduling is rejected with `ERR_MORATORIUM_ACTIVE`."
    PRD §3.11: "Its `active` flag is derived: it is true exactly when the current
    server clock falls at or after `window_start` and strictly before `window_end`."

    Design: Difficulty/resource_temporal_overlap/shutoff_schedule_inside_moratorium_window_barred
    """
    fixtures.set_clock("2026-11-15T00:00:00Z")
    account, bill, rs, cycle = setup_flat_past_due_account(
        potable=30000, arrears_threshold=7500,
        initial_clock="2026-11-15T00:00:00Z", close_clock="2026-12-20T00:00:00Z")
    validate_success(
        api.create_moratorium(
            factories.moratorium_payload("Winter", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"),
            CASEWORKER), 201)
    # scheduled_for = window_start (inclusive boundary) -> barred
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-12-01T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_MORATORIUM_ACTIVE.value)


def test_shutoff_barred_in_moratorium_creates_no_order(api):
    """PRD §3.9: "And no active moratorium may cover the `scheduled_for` date; if one
    does, scheduling is rejected with `ERR_MORATORIUM_ACTIVE`."
    PRD §3.9: "When scheduling succeeds, the order is created in `SCHEDULED` status
    and the account's `billing_status` advances to `SHUTOFF_PENDING`."

    Design: Difficulty/resource_temporal_overlap/shutoff_schedule_inside_moratorium_window_barred
    """
    fixtures.set_clock("2026-11-15T00:00:00Z")
    account, bill, rs, cycle = setup_flat_past_due_account(
        potable=30000, arrears_threshold=7500,
        initial_clock="2026-11-15T00:00:00Z", close_clock="2026-12-20T00:00:00Z")
    validate_success(
        api.create_moratorium(
            factories.moratorium_payload("Winter", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"),
            CASEWORKER), 201)
    api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-12-15T00:00:00Z"), FIELDOPS)
    # The barred attempt left no SHUTOFF_PENDING transition: account remains PAST_DUE.
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["billing_status"] == "PAST_DUE"


def test_moratorium_safety_over_arrears_on_shutoff(api):
    """PRD §3.9: "And no active moratorium may cover the `scheduled_for` date; if one
    does, scheduling is rejected with `ERR_MORATORIUM_ACTIVE`."
    PRD §3.9: "The account's `past_due_cents` must be at or above the schedule's
    `arrears_shutoff_threshold_cents`; below that, scheduling is rejected with
    `ERR_ARREARS_BELOW_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/moratorium_safety_beats_arrears_fiscal_on_shutoff
    """
    # Account both below arrears threshold (3000 < 7500) AND inside a moratorium.
    # PRD lists business rules within one tier without committing to a strict
    # intra-tier order, so either domain error is a PRD-faithful outcome.
    fixtures.set_clock("2026-11-15T00:00:00Z")
    account, bill, rs, cycle = setup_flat_past_due_account(
        potable=6000, arrears_threshold=7500,
        initial_clock="2026-11-15T00:00:00Z", close_clock="2026-12-20T00:00:00Z")
    validate_success(
        api.create_moratorium(
            factories.moratorium_payload("Winter", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"),
            CASEWORKER), 201)
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-12-15T00:00:00Z"), FIELDOPS)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_MORATORIUM_ACTIVE.value, ApiErrorId.ERR_ARREARS_BELOW_THRESHOLD.value])


# ===========================================================================
# State legality precedes domain rules (priority_pair_validation_conflict)
# ===========================================================================
def test_double_shutoff_rejected_with_invalid_state(api):
    """PRD §3.9: "The transition into `SHUTOFF_PENDING` is defined out of
    `PAST_DUE`."
    PRD §2.9: "Only then does the system evaluate state legality, namely whether the
    targeted resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`), then the optimistic-concurrency check on budget-plan
    enrollment (`ERR_STALE_ACCOUNT_VERSION`), and finally the business-rule checks
    specific to each workflow"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_arrears_fiscal_on_double_shutoff
    """
    # First shutoff moves account to SHUTOFF_PENDING; a second schedule attempt
    # is an undefined transition out of SHUTOFF_PENDING -> ERR_INVALID_STATE,
    # evaluated before any business-rule (arrears) check per §2.9.
    account, bill, order, rs, cycle = setup_scheduled_shutoff(potable=12000, irrigation=8000)
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-12T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_shutoff_leaves_first_order_scheduled(api):
    """PRD §2.9: "Only then does the system evaluate state legality, namely whether
    the targeted resource is in a state from which the requested transition is
    defined (`ERR_INVALID_STATE`), then the optimistic-concurrency check on
    budget-plan enrollment (`ERR_STALE_ACCOUNT_VERSION`), and finally the
    business-rule checks specific to each workflow"
    PRD §3.9: "The transition into `SHUTOFF_PENDING` is defined out of `PAST_DUE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_arrears_fiscal_on_double_shutoff
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(potable=12000, irrigation=8000)
    api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-03-12T00:00:00Z"), FIELDOPS)
    # The original order is untouched and the account stays SHUTOFF_PENDING.
    first = validate_success(api.get_shutoff_order(order["id"], FIELDOPS))
    assert first["status"] == "SCHEDULED"
    acct = validate_success(api.get_account(account["id"], CLERK))
    assert acct["billing_status"] == "SHUTOFF_PENDING"


def test_moratorium_bars_shutoff_even_with_sufficient_arrears(api):
    """PRD §3.9: "And no active moratorium may cover the `scheduled_for` date; if one
    does, scheduling is rejected with `ERR_MORATORIUM_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/moratorium_safety_beats_arrears_fiscal_on_shutoff
    """
    # Sufficient arrears (15000 >= threshold) but a covering moratorium: the safety
    # guard bars scheduling regardless of the satisfied fiscal precondition.
    fixtures.set_clock("2026-11-15T00:00:00Z")
    account, bill, rs, cycle = setup_flat_past_due_account(
        potable=30000, arrears_threshold=7500,
        initial_clock="2026-11-15T00:00:00Z", close_clock="2026-12-20T00:00:00Z")
    validate_success(
        api.create_moratorium(
            factories.moratorium_payload("Winter", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"),
            CASEWORKER), 201)
    resp = api.create_shutoff_order(
        factories.shutoff_order_payload(account["id"], bill["id"], "2026-12-15T00:00:00Z"), FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_MORATORIUM_ACTIVE.value)


# ===========================================================================
# Leak approval gated by bill POSTED (cross_entity_state_dependency)
# ===========================================================================
def test_leak_approve_on_draft_bill_rejected(api):
    """PRD §3.8: "**Approving** a leak adjustment moves it from `PENDING` to
    `APPROVED` and is permitted only when the referenced bill is in `POSTED` status —
    a leak credit cannot be applied to a `DRAFT`, `VOID`, or `PAID` bill, and an
    attempt to approve against a non-posted bill is rejected with
    `ERR_BILL_NOT_POSTED`."

    Design: Difficulty/cross_entity_state_dependency/leak_approve_requires_bill_posted
    """
    account, bill, leak = setup_pending_leak_on_draft(baseline_gallons=4000, potable=12000)
    resp = api.approve_leak_adjustment(leak["id"], CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_BILL_NOT_POSTED.value)
    after = validate_success(api.get_leak_adjustment(leak["id"], CASEWORKER))
    assert after["status"] == "PENDING"


def test_leak_approve_on_draft_leaves_status_pending(api):
    """PRD §3.8: "a leak credit cannot be applied to a `DRAFT`, `VOID`, or `PAID`
    bill, and an attempt to approve against a non-posted bill is rejected with
    `ERR_BILL_NOT_POSTED`."

    Design: Difficulty/cross_entity_state_dependency/leak_approve_requires_bill_posted
    """
    account, bill, leak = setup_pending_leak_on_draft(baseline_gallons=4000, potable=12000)
    api.approve_leak_adjustment(leak["id"], CASEWORKER)
    after = validate_success(api.get_leak_adjustment(leak["id"], CASEWORKER))
    assert after["status"] == "PENDING"
    assert after["credit_cents"] == 0


def test_leak_approve_no_over_baseline_rejected(api):
    """PRD §3.8: "Approval also requires genuine over-baseline volume: the
    adjustment's `baseline_gallons` must be strictly below the bill's
    `potable_consumption_gallons`, otherwise the approval is rejected with
    `ERR_NO_LEAK_VOLUME`."

    Design: Corner/state_machines/leak_approve_no_over_baseline_returns_422
    """
    account, bill, leak = fixtures.setup_pending_leak_on_posted(
        baseline_gallons=12000, potable=12000, irrigation=8000)
    resp = api.approve_leak_adjustment(leak["id"], CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_NO_LEAK_VOLUME.value)
