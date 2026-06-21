"""Validation-priority masking tests: when multiple validation arms could
fire, the earlier-priority rule wins per PRD §2.8.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, add_member,
    create_and_submit_application, approve_application,
    setup_household_active_with_substantiated_flag,
)

CW = TEST_USERS["caseworker_headers"]
INV = TEST_USERS["fraud_investigator_headers"]


# ─── Difficulty / priority_pair_validation_conflict / state_beats_business_fiscal_on_double_approve ──

def test_double_approve_returns_invalid_state_not_income_limit(api):
    """Setup: a household is approved once at a low income, then a member
    update raises the income above the eligibility ceiling. A second
    /approve attempt hits two failure arms simultaneously: the state check
    (already APPROVED — priority 6) and the income-limit check (would now
    exceed — priority 17). PRD §2.8's masking rule means ERR_INVALID_STATE
    surfaces, not ERR_INCOME_LIMIT_EXCEEDED.

    PRD §2.8: "When several validation rules might reject the same request,
    they are evaluated in a fixed priority order so that the rejection a
    caller sees is the one closest to the root cause."
    PRD §2.8: "Earlier rules mask later ones: a missing role header is
    reported as `ERR_UNAUTHENTICATED` even when the body would also be
    malformed; a not-found URL segment is reported as `ERR_NOT_FOUND`
    even when a stale `expected_household_version` would also have been
    rejected."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_double_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="OH-900001", state_code="OH",
                          address_line="9 Birch St")
    m = add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
                   relationship="HEAD", monthly_earned_income_cents=10000,
                   disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"], decision_reason="Initially eligible")
    # Raise income above the size-1 limit (117500 cents). Use 200000.
    validate_success(api.patch_household_member(
        m["id"], {"monthly_earned_income_cents": 200000}, CW), 200)

    resp = api.approve_application(
        app["id"], {"decision_reason": "Second attempt"}, CW,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_first_approve_succeeds_even_under_low_income(api):
    """Complement: when only the income arm is in play (single approve, no
    prior state conflict), the income-limit check governs the outcome.
    Confirms the previous test's ERR_INVALID_STATE truly came from the
    state-check arm rather than from an incidental disabling of the income
    check.

    PRD §2.8: "(17) the income-limit check on application approve, ..."
    PRD §3.4: "The limit-check value is compared, inside application
    approve, against `NET_INCOME_LIMIT_BY_SIZE`: 117,500 cents for size 1,
    158,900 cents for size 2, 200,300 cents for size 3, 241,700 cents for
    size 4, 283,100 cents for size 5, and 324,500 cents for size 6, with
    an additional 41,400 cents added per person beyond 6. A limit-check
    value at or below the size-indexed ceiling passes; a value above it
    fails with `ERR_INCOME_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_double_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="OH-900002", state_code="OH",
                          address_line="10 Birch St")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=10000,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    approved = approve_application(app["id"], decision_reason="Eligible")
    assert approved["status"] == "APPROVED"


# ─── Difficulty / priority_pair_validation_conflict / auth_beats_state_on_wrong_role_suspend ──

def test_wrong_role_on_suspend_returns_forbidden_even_when_state_also_invalid(api):
    """A household that is already SUSPENDED is targeted by a /suspend call
    made by a FraudInvestigator (not the Caseworker-only role for /suspend
    per PRD §4). Two arms could fire: the role-auth check at priority 3,
    and the state-check at priority 6 (cannot suspend an already-SUSPENDED
    household). PRD §2.8's masking rule means ERR_FORBIDDEN surfaces,
    not ERR_INVALID_STATE.

    PRD §2.8: "When several validation rules might reject the same request,
    they are evaluated in a fixed priority order so that the rejection a
    caller sees is the one closest to the root cause. The order is: (1)
    `X-User-Role` present and recognised, (2) `X-User-ID` present, (3)
    role authorised for the endpoint, (4) every URL-path `{id}` resolves,
    (5) every body foreign key resolves, (6) the entity is in a from-state
    listed for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §4: "POST /snap/households/{id}/suspend | Suspend an `ACTIVE`
    household. | Caseworker"

    Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_on_wrong_role_suspend
    """
    hh, _card, _ff = setup_household_active_with_substantiated_flag(
        case_number="MI-110001", state_code="MI",
        clock_iso="2026-09-01T00:00:00Z",
    )
    # First suspend by Caseworker is legitimate; HH lands in SUSPENDED.
    validate_success(api.suspend_household(hh["id"], CW), 200)
    # Second /suspend by FraudInvestigator hits BOTH the role-auth check
    # (FraudInvestigator is not authorised for /suspend) and the state check
    # (already SUSPENDED — no ACTIVE from-state). The earlier priority wins.
    resp = api.suspend_household(hh["id"], INV)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_authorised_caseworker_on_already_suspended_returns_invalid_state(api):
    """Complement: a Caseworker (authorised role) calling /suspend on the
    already-SUSPENDED household passes the role-auth gate and hits the
    state-check arm only — the response is ERR_INVALID_STATE. Confirms the
    previous test's ERR_FORBIDDEN really came from the role gate, not the
    state gate.

    PRD §2.8: "(6) the entity is in a from-state listed for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §4: "POST /snap/households/{id}/suspend | Suspend an `ACTIVE`
    household. | Caseworker"

    Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_on_wrong_role_suspend
    """
    hh, _card, _ff = setup_household_active_with_substantiated_flag(
        case_number="MI-110002", state_code="MI",
        clock_iso="2026-09-01T00:00:00Z",
    )
    validate_success(api.suspend_household(hh["id"], CW), 200)
    resp = api.suspend_household(hh["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
