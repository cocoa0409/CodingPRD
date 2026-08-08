"""Violation lifecycle: contest cycle, four-eyes adjudication, points threshold
suspension, and fine charge/dismiss money conservation
(Difficulty: non_linear_state_machine, boundary_precision_check,
compensating_invariant; Corner: state_machines, rbac)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    make_vendor_headers, make_enforcement_headers,
    OFFICER_ISSUER_ID, OFFICER_ADJUDICATOR_ID,
    create_violation_payload, adjudicate_payload,
    FEE_NEW_STANDARD_MEDIUM, VIOLATION_FINE_CENTS,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
EO1 = make_enforcement_headers(OFFICER_ISSUER_ID)
EO2 = make_enforcement_headers(OFFICER_ADJUDICATOR_ID)


def _issued_permit_with_minor_violation():
    ctx = fx.setup_issued_permit()
    vio = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MINOR", "no bin"), EO1))
    return ctx, vio


# --------------------------------------------------------------------------- #
# non_linear_state_machine / violation_cycle_issued_contested_withdrawn
# --------------------------------------------------------------------------- #
def test_violation_contest_moves_to_contested(api):
    """PRD §3.7: "The owning vendor may contest a citation, moving it ISSUED →
    CONTESTED, and may later withdraw that contest, moving it CONTESTED → ISSUED;
    this negotiation loop may repeat."

    Design: Difficulty/non_linear_state_machine/violation_cycle_issued_contested_withdrawn
    """
    ctx, vio = _issued_permit_with_minor_violation()
    vh = make_vendor_headers(ctx["vendor"]["id"])
    contested = validate_success(api.contest_violation(vio["id"], vh), 200)
    assert contested["status"] == "CONTESTED"


def test_violation_withdraw_contest_returns_to_issued(api):
    """PRD §3.7: "The owning vendor may contest a citation, moving it ISSUED →
    CONTESTED, and may later withdraw that contest, moving it CONTESTED → ISSUED;
    this negotiation loop may repeat."

    Design: Difficulty/non_linear_state_machine/violation_cycle_issued_contested_withdrawn
    """
    ctx, vio = _issued_permit_with_minor_violation()
    vh = make_vendor_headers(ctx["vendor"]["id"])
    get_success_data(api.contest_violation(vio["id"], vh))
    back = validate_success(api.withdraw_contest_violation(vio["id"], vh), 200)
    assert back["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# boundary_precision_check / points_threshold_exactly_twelve_suspends
# --------------------------------------------------------------------------- #
def _permit_with_two_major_violations():
    ctx = fx.setup_issued_permit()
    v1 = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MAJOR", "v1"), EO1))
    v2 = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MAJOR", "v2"), EO1))
    return ctx, v1, v2


def test_permit_below_threshold_stays_issued(api):
    """PRD §3.7: "the permit's points are recomputed over the trailing window, and if
    they reach or exceed the suspension threshold of 12 while the permit is ISSUED,
    the permit is suspended (ISSUED → SUSPENDED)"
    PRD §3.7: "Its points are set from the violation type — 3 for MINOR, 6 for MAJOR,
    12 for CRITICAL"

    Design: Difficulty/boundary_precision_check/points_threshold_exactly_twelve_suspends
    """
    ctx, v1, _ = _permit_with_two_major_violations()
    get_success_data(api.adjudicate_violation(v1["id"], adjudicate_payload("UPHOLD"), EO2))
    permit = validate_success(api.get_permit(ctx["permit"]["id"], PO), 200)
    assert permit["violation_points"] == 6
    assert permit["status"] == "ISSUED"


def test_permit_at_threshold_twelve_suspends(api):
    """PRD §3.7: "the permit's points are recomputed over the trailing window, and if
    they reach or exceed the suspension threshold of 12 while the permit is ISSUED,
    the permit is suspended (ISSUED → SUSPENDED) with the spot-release cascade of
    Section 2.7."

    Design: Difficulty/boundary_precision_check/points_threshold_exactly_twelve_suspends
    """
    ctx, v1, v2 = _permit_with_two_major_violations()
    get_success_data(api.adjudicate_violation(v1["id"], adjudicate_payload("UPHOLD"), EO2))
    get_success_data(api.adjudicate_violation(v2["id"], adjudicate_payload("UPHOLD"), EO2))
    permit = validate_success(api.get_permit(ctx["permit"]["id"], PO), 200)
    assert permit["violation_points"] == 12
    assert permit["status"] == "SUSPENDED"


# --------------------------------------------------------------------------- #
# compensating_invariant / money_conservation_fine_charge_then_dismiss
# --------------------------------------------------------------------------- #
def test_fine_charge_raises_balance(api):
    """PRD §3.7: "the fine is charged to the vendor's total_charged_cents at
    issuance"
    PRD §2.5: "The derived balance_owed_cents is always total_charged_cents minus
    total_credited_cents."

    Design: Difficulty/compensating_invariant/money_conservation_fine_charge_then_dismiss
    """
    ctx = fx.setup_issued_permit()
    vendor = ctx["vendor"]
    bal0 = validate_success(api.get_vendor(vendor["id"], PO), 200)["balance_owed_cents"]
    assert bal0 == FEE_NEW_STANDARD_MEDIUM  # 34257
    get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MAJOR", "fine"), EO1))
    bal1 = validate_success(api.get_vendor(vendor["id"], PO), 200)["balance_owed_cents"]
    assert bal1 == bal0 + VIOLATION_FINE_CENTS["MAJOR"]  # 46257


def test_dismiss_reverses_fine_restoring_balance(api):
    """PRD §3.7: "A DISMISS outcome moves the violation to DISMISSED and reverses the
    issue-time charge by adding the violation's fine_cents to the vendor's
    total_credited_cents, recomputing the balance."
    PRD §2.5: "every forward charge that is later reversed (for example, a fine that
    is dismissed) is offset by an equal credit, so the outstanding balance returns to
    exactly its pre-charge value with no drift."

    Design: Difficulty/compensating_invariant/money_conservation_fine_charge_then_dismiss
    """
    ctx = fx.setup_issued_permit()
    vendor = ctx["vendor"]
    vio = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MAJOR", "fine"), EO1))
    get_success_data(api.adjudicate_violation(vio["id"], adjudicate_payload("DISMISS"), EO2))
    bal2 = validate_success(api.get_vendor(vendor["id"], PO), 200)["balance_owed_cents"]
    assert bal2 == FEE_NEW_STANDARD_MEDIUM  # 34257, back to pre-fine value


# --------------------------------------------------------------------------- #
# Corner rbac: same_officer_cannot_adjudicate_own_citation
# --------------------------------------------------------------------------- #
def test_same_officer_cannot_adjudicate_own_citation(api):
    """PRD §3.7: "Adjudication enforces four-eyes segregation: the adjudicating
    officer's X-User-ID must differ from the violation's issuer_user_id, otherwise
    the request is rejected with ERR_SELF_ADJUDICATION."

    Design: Corner/rbac/same_officer_cannot_adjudicate_own_citation
    """
    ctx = fx.setup_issued_permit()
    vio = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MAJOR", "x"), EO1))
    # off-1 issued and now off-1 attempts to adjudicate.
    res = api.adjudicate_violation(vio["id"], adjudicate_payload("UPHOLD"), EO1)
    validate_error(res, "ERR_SELF_ADJUDICATION", expected_status=403)


# --------------------------------------------------------------------------- #
# Corner state_machines: contest_uncited_state_from_upheld_invalid_state
# --------------------------------------------------------------------------- #
def test_contest_upheld_violation_invalid_state(api):
    """PRD §3.7: "The new violation begins ISSUED (its enum ranges over ISSUED,
    CONTESTED, UPHELD, and DISMISSED; UPHELD and DISMISSED are terminal)."
    PRD §4: "one attempted from a terminal state returns ERR_TERMINAL_STATE"

    An UPHELD violation is an explicitly-labeled terminal state, so contesting it
    is a transition from a terminal state and yields ERR_TERMINAL_STATE (not the
    illegal-source-state ERR_INVALID_STATE).

    Design: Corner/state_machines/contest_uncited_state_from_upheld_invalid_state
    """
    ctx = fx.setup_issued_permit()
    vh = make_vendor_headers(ctx["vendor"]["id"])
    vio = get_success_data(fx.api_client.create_violation(
        ctx["permit"]["id"], create_violation_payload("MINOR", "x"), EO1))
    get_success_data(api.adjudicate_violation(vio["id"], adjudicate_payload("UPHOLD"), EO2))
    res = api.contest_violation(vio["id"], vh)
    validate_error(res, "ERR_TERMINAL_STATE", expected_status=409)
