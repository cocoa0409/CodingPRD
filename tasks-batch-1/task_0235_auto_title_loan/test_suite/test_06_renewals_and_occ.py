"""Renewals: rollover limit boundary, capitalization, OCC stale-version guard, and
the state-beats-fiscal precedence on a charged-off loan at its renewal cap."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
    setup_charged_off_loan,
    set_clock,
    create_renewal_payload,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]
_RECOVERY = TEST_USERS["recovery_manager_headers"]


def _loan_version(api, loan_id):
    return get_success_data(api.get_loan(loan_id, _SERVICER))["version"]


# ─────────────────────────────────────────────────────────────────────────
# Boundary precision: renewal_count == max_renewals barred
# ─────────────────────────────────────────────────────────────────────────
def test_renewal_count_boundary_second_renewal_succeeds(api):
    """PRD §3.8: "The renewal records two computed amounts and a system ordinal:
    rolled_fees_cents, new_principal_cents, and renewal_index (the 1-based ordinal of
    this renewal on the loan, which equals the loan's renewal_count after the renewal)."

    Design: Difficulty/boundary_precision_check/renewal_count_boundary_at_max_renewals_barred
    """
    ctx = setup_originated_loan()  # CA profile max_renewals 2
    loan_id = ctx["loan"]["id"]
    r1 = validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 6), _SERVICER), 201)
    assert r1["renewal_index"] == 1
    r2 = validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 9), _SERVICER), 201)
    assert r2["renewal_index"] == 2
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["renewal_count"] == 2


def test_renewal_count_boundary_third_renewal_barred(api):
    """PRD §3.8: "The rollover limit must not be reached: a renewal is barred once the
    loan's renewal_count is at or above the borrower-state max_renewals, in which case
    the create is rejected with ERR_RENEWAL_LIMIT_REACHED."

    Design: Difficulty/boundary_precision_check/renewal_count_boundary_at_max_renewals_barred
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 6), _SERVICER), 201)
    validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 9), _SERVICER), 201)
    res = api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 12), _SERVICER)
    validate_error(res, "ERR_RENEWAL_LIMIT_REACHED")


# ─────────────────────────────────────────────────────────────────────────
# Priority pair: STATE (p6) beats BUSINESS_FISCAL/renewal-limit (p13)
# on a CHARGED_OFF loan that is also at its renewal cap
# ─────────────────────────────────────────────────────────────────────────
def test_state_beats_renewal_limit_on_chargedoff_loan(api):
    """PRD §3.8: "The loan must be in a renewable state: its `payoff_status` must be
    `OUTSTANDING`, because a `REDEEMED`, `PAID_OFF`, or `CHARGED_OFF` loan cannot be
    renewed; a non-renewable state is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "The rollover limit must not be reached: a renewal is barred once the
    loan's `renewal_count` is at or above the borrower-state `max_renewals`, in which
    case the create is rejected with `ERR_RENEWAL_LIMIT_REACHED`." (the state guard is
    introduced before the rollover-limit guard in this ordered list)

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_renewal_of_chargedoff_loan
    """
    # Originate, renew twice (count -> 2 == max_renewals), then default and charge off.
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 6), _SERVICER), 201)
    validate_success(
        api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 9), _SERVICER), 201)
    # Drive to CHARGED_OFF.
    set_clock("2026-09-15T00:00:00.000Z")
    get_success_data(api.assess_delinquency(loan_id, _SERVICER))
    get_success_data(api.declare_default(loan_id, _SERVICER))
    orders, _m = _list(api.list_loan_repossession_orders(loan_id, _RECOVERY))
    repo_id = orders[0]["id"]
    get_success_data(api.create_assignment(
        repo_id, {"agent_name": "Agent B", "window_start": "2026-09-16T08:00:00.000Z",
                  "window_end": "2026-09-16T12:00:00.000Z"}, _RECOVERY))
    get_success_data(api.assign_repossession_order(repo_id, _RECOVERY))
    get_success_data(api.recover_repossession_order(repo_id, _RECOVERY))
    set_clock("2026-09-30T00:00:00.000Z")
    get_success_data(api.sell_repossession_order(repo_id, {"sale_proceeds_cents": 500000}, _RECOVERY))
    # Loan is now CHARGED_OFF and at renewal cap. A renewal must report state, not limit.
    res = api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 12), _SERVICER)
    validate_error(res, "ERR_INVALID_STATE")


def test_renew_chargedoff_loan_does_not_report_renewal_limit(api):
    """PRD §3.8: "a `REDEEMED`, `PAID_OFF`, or `CHARGED_OFF` loan cannot be renewed; a
    non-renewable state is rejected with `ERR_INVALID_STATE`." (the state guard precedes
    the renewal-limit guard in the same ordered list)

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_renewal_of_chargedoff_loan
    """
    ctx = setup_charged_off_loan()  # renewal_count 0, but CHARGED_OFF
    loan_id = ctx["loan"]["id"]
    res = api.create_renewal(loan_id, create_renewal_payload(_loan_version(api, loan_id), 12), _SERVICER)
    # Charged-off loan is non-renewable regardless of count -> state error, never limit.
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Corner / cross-cutting: OCC stale-version on renewal
# ─────────────────────────────────────────────────────────────────────────
def test_occ_stale_loan_version_on_renewal(api):
    """PRD §2.7: "If `expected_loan_version` does not equal the loan's current
    `version`, the create is rejected with `ERR_STALE_LOAN_VERSION` at HTTP 412."
    PRD §3.8: "The `expected_loan_version` must equal the loan's current `version`, or
    the create is rejected with `ERR_STALE_LOAN_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_loan_version_on_renewal
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    v0 = _loan_version(api, loan_id)
    validate_success(
        api.create_renewal(loan_id, create_renewal_payload(v0, 6), _SERVICER), 201)
    # The first renewal advanced loan.version; re-sending v0 is now stale.
    res = api.create_renewal(loan_id, create_renewal_payload(v0, 9), _SERVICER)
    validate_error(res, "ERR_STALE_LOAN_VERSION")


# ─────────────────────────────────────────────────────────────────────────
# Corner / cross-cutting: clean-loan renewal capitalization
# ─────────────────────────────────────────────────────────────────────────
def test_occ_renewal_capitalization_clean_loan(api):
    """PRD §3.8: "rolled_fees_cents is the sum of the loan's current
    accrued_interest_cents and fees_balance_cents; new_principal_cents is the loan's
    current principal_balance_cents plus rolled_fees_cents."

    Design: Corner/cross_cutting_complexity_layers/occ_renewal_capitalization_clean_loan
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    v0 = _loan_version(api, loan_id)
    renewal = validate_success(
        api.create_renewal(loan_id, create_renewal_payload(v0, 6), _SERVICER), 201)
    assert renewal["new_principal_cents"] == 600000
    assert renewal["renewal_index"] == 1
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["principal_balance_cents"] == 600000


def _list(response):
    body = get_success_data(response)
    return (body, {}) if isinstance(body, list) else (body, {})
