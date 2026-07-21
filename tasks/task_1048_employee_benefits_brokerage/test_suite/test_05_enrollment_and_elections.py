"""Open-enrollment windows, employee elections, tier costs, and headcount ledger."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_enrollment_window_payload, make_client_contact_headers,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine — election confirm vs waive branch
# ===========================================================================
def test_election_confirm_and_waive_reach_divergent_states(api):
    """PRD §3.6: "Confirming an election advances it from SELECTED to CONFIRMED".
    PRD §3.6: "Waiving an election advances it from SELECTED to WAIVED and requires the
    parent window to be OPEN; a waive makes no change to the client's enrolled_headcount."

    Design: Difficulty/non_linear_state_machine/election_branch_confirm_vs_waive
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=2, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    hdr = make_client_contact_headers(client["id"])
    e1 = validate_success(api.confirm_election(elections[0]["id"], hdr))
    e2 = validate_success(api.waive_election(elections[1]["id"], hdr))
    assert e1["status"] == "CONFIRMED"
    assert e2["status"] == "WAIVED"


def test_election_waive_leaves_headcount_at_confirmed_only(api):
    """PRD §2.8: "enrolled_headcount — the count of the client's elections in CONFIRMED
    status across all of the client's enrollment windows. Confirming an election adds one;
    withdrawing a confirmed election subtracts one; and finalizing a window confirms its
    still-SELECTED elections, each of which contributes one to the count."
    PRD §3.6: "Waiving an election advances it from SELECTED to WAIVED and requires the
    parent window to be OPEN; a waive makes no change to the client's enrolled_headcount."

    Design: Difficulty/non_linear_state_machine/election_branch_confirm_vs_waive
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=2, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    hdr = make_client_contact_headers(client["id"])
    validate_success(api.confirm_election(elections[0]["id"], hdr))
    validate_success(api.waive_election(elections[1]["id"], hdr))
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["enrolled_headcount"] == 1


# ===========================================================================
# Difficulty / transitive_cascade — finalize confirms elections then bumps client
# ===========================================================================
def test_window_finalize_confirms_selected_election(api):
    """PRD §3.6: "Finalization confirms every election for that window still in SELECTED
    (moving each to CONFIRMED), and each such newly confirmed election increments the
    client's enrolled_headcount by one."

    Design: Difficulty/transitive_cascade/window_finalize_cascade_election_then_client
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=1, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    fx.set_clock("2026-08-01T00:00:00Z")
    finalized = validate_success(api.finalize_window(window["id"], CONSULTANT))
    assert finalized["status"] == "FINALIZED"
    fresh_election = validate_success(api.get_election(elections[0]["id"], CONSULTANT))
    assert fresh_election["status"] == "CONFIRMED"


def test_window_finalize_increments_client_headcount(api):
    """PRD §3.6: "Finalization confirms every election for that window still in SELECTED
    (moving each to CONFIRMED), and each such newly confirmed election increments the
    client's enrolled_headcount by one."

    Design: Difficulty/transitive_cascade/window_finalize_cascade_election_then_client
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=1, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    fx.set_clock("2026-08-01T00:00:00Z")
    validate_success(api.finalize_window(window["id"], CONSULTANT))
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["enrolled_headcount"] == 1


# ===========================================================================
# Difficulty / combinatorial_formula — round-per-election-then-sum
# ===========================================================================
def test_election_tier_costs_rounded_per_election(api):
    """PRD §3.6: "On confirmation, the election's monthly_cost_cents is computed as the
    policy's monthly_premium_cents multiplied by the tier factor for the chosen tier — 1.00
    for EMPLOYEE_ONLY, 2.00 for EMPLOYEE_SPOUSE, 1.75 for EMPLOYEE_CHILD, and 2.85 for
    FAMILY — rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/election_premium_round_then_sum_mode_b
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=2, coverage_tier=["EMPLOYEE_CHILD", "FAMILY"], monthly_premium_cents=100_010)
    fx.set_clock("2026-08-01T00:00:00Z")
    validate_success(api.finalize_window(window["id"], CONSULTANT))
    e1 = validate_success(api.get_election(elections[0]["id"], CONSULTANT))
    e2 = validate_success(api.get_election(elections[1]["id"], CONSULTANT))
    assert e1["monthly_cost_cents"] == 175_018
    assert e2["monthly_cost_cents"] == 285_029


def test_window_total_confirmed_rounds_then_sums(api):
    """PRD §3.6: "The window's total_confirmed_cents is then computed by rounding each
    confirmed election's cost (policy monthly premium times its tier factor) to whole cents
    and summing those rounded per-election amounts; the per-election rounding always precedes
    the summation."

    Design: Difficulty/combinatorial_formula/election_premium_round_then_sum_mode_b
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=2, coverage_tier=["EMPLOYEE_CHILD", "FAMILY"], monthly_premium_cents=100_010)
    fx.set_clock("2026-08-01T00:00:00Z")
    finalized = validate_success(api.finalize_window(window["id"], CONSULTANT))
    assert finalized["total_confirmed_cents"] == 460_047


# ===========================================================================
# Difficulty / boundary_precision_check — finalize with empty confirmed set
# ===========================================================================
def test_finalize_empty_window_total_is_zero(api):
    """PRD §3.6: "The window's total_confirmed_cents is then computed by rounding each
    confirmed election's cost (policy monthly premium times its tier factor) to whole cents
    and summing those rounded per-election amounts; the per-election rounding always precedes
    the summation."

    Design: Difficulty/boundary_precision_check/enrollment_finalize_empty_confirmed_set
    """
    client = fx.create_client(legal_name="Mu Co")
    window = fx.create_open_window(client["id"])
    fx.set_clock("2026-08-01T00:00:00Z")
    finalized = validate_success(api.finalize_window(window["id"], CONSULTANT))
    assert finalized["status"] == "FINALIZED"
    assert finalized["total_confirmed_cents"] == 0


def test_finalize_empty_window_leaves_headcount_zero(api):
    """PRD §2.8: "enrolled_headcount — the count of the client's elections in CONFIRMED
    status across all of the client's enrollment windows."

    Design: Difficulty/boundary_precision_check/enrollment_finalize_empty_confirmed_set
    """
    client = fx.create_client(legal_name="Mu Co")
    window = fx.create_open_window(client["id"])
    fx.set_clock("2026-08-01T00:00:00Z")
    validate_success(api.finalize_window(window["id"], CONSULTANT))
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["enrolled_headcount"] == 0


# ===========================================================================
# Difficulty / cross_entity_state_dependency — election requires OPEN window
# ===========================================================================
def test_create_election_on_scheduled_window_invalid_state(api):
    """PRD §3.6: "An election may only be created while its window is OPEN (otherwise
    ERR_INVALID_STATE), and its window, member, and policy must all belong to the same client
    (otherwise ERR_CLIENT_MISMATCH)."

    Design: Difficulty/cross_entity_state_dependency/election_create_requires_open_window
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=500_000)
    member = fx.create_member(client["id"], full_name="Early Bird")
    window = fx.create_scheduled_window(client["id"])  # not opened
    resp = api.create_election(
        {"window_id": window["id"], "census_member_id": member["id"],
         "policy_id": policy["id"], "coverage_tier": "EMPLOYEE_ONLY"},
        make_client_contact_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_rejected_election_creates_no_row(api):
    """PRD §3.6: "An election may only be created while its window is OPEN (otherwise
    ERR_INVALID_STATE), and its window, member, and policy must all belong to the same client
    (otherwise ERR_CLIENT_MISMATCH)."

    Design: Difficulty/cross_entity_state_dependency/election_create_requires_open_window
    """
    client, policy = fx.setup_client_with_active_policy(monthly_premium_cents=500_000)
    member = fx.create_member(client["id"], full_name="Early Bird")
    window = fx.create_scheduled_window(client["id"])
    api.create_election(
        {"window_id": window["id"], "census_member_id": member["id"],
         "policy_id": policy["id"], "coverage_tier": "EMPLOYEE_ONLY"},
        make_client_contact_headers(client["id"]))
    data, meta = validate_paginated(api.list_elections(CONSULTANT, params={"window_id": window["id"]}))
    assert meta["total_count"] == 0


# ===========================================================================
# Difficulty / compensating_invariant — confirm then withdraw conserves headcount
# ===========================================================================
def test_withdraw_confirmed_election_reaches_withdrawn(api):
    """PRD §3.6: "Withdrawing a confirmed election advances it from CONFIRMED to WITHDRAWN
    and decreases the client's enrolled_headcount by one."

    Design: Difficulty/compensating_invariant/enrolled_headcount_conserved_confirm_then_withdraw
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=1, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    hdr = make_client_contact_headers(client["id"])
    validate_success(api.confirm_election(elections[0]["id"], hdr))
    withdrawn = validate_success(api.withdraw_election(elections[0]["id"], hdr))
    assert withdrawn["status"] == "WITHDRAWN"


def test_confirm_then_withdraw_conserves_headcount_to_zero(api):
    """PRD §2.8: "enrolled_headcount — the count of the client's elections in CONFIRMED
    status across all of the client's enrollment windows. Confirming an election adds one;
    withdrawing a confirmed election subtracts one".

    Design: Difficulty/compensating_invariant/enrolled_headcount_conserved_confirm_then_withdraw
    """
    client, policy, window, members, elections = fx.setup_enrollment_scenario(
        members=1, coverage_tier="EMPLOYEE_ONLY", monthly_premium_cents=500_000)
    hdr = make_client_contact_headers(client["id"])
    validate_success(api.confirm_election(elections[0]["id"], hdr))
    validate_success(api.withdraw_election(elections[0]["id"], hdr))
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["enrolled_headcount"] == 0


# ===========================================================================
# Difficulty / resource_temporal_overlap — window overlap (half-open)
# ===========================================================================
def test_enrollment_window_overlap_rejected(api):
    """PRD §3.6: "A new window's half-open [opens_at, closes_at) interval must not overlap
    any existing window for the same client; a create that would overlap is rejected with
    ERR_WINDOW_OVERLAP, though adjacency — one window's closes_at equal to another's opens_at
    — is allowed."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_overlap_half_open
    """
    client = fx.create_client(legal_name="Omicron Co")
    validate_success(api.create_enrollment_window(
        create_enrollment_window_payload(client["id"], plan_year=2027,
                                          opens_at="2027-01-01T00:00:00Z",
                                          closes_at="2027-02-01T00:00:00Z"), CONSULTANT), 201)
    resp = api.create_enrollment_window(
        create_enrollment_window_payload(client["id"], plan_year=2027,
                                          opens_at="2027-01-15T00:00:00Z",
                                          closes_at="2027-03-01T00:00:00Z"), CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_enrollment_window_adjacency_allowed(api):
    """PRD §3.6: "A new window's half-open [opens_at, closes_at) interval must not overlap
    any existing window for the same client; a create that would overlap is rejected with
    ERR_WINDOW_OVERLAP, though adjacency — one window's closes_at equal to another's opens_at
    — is allowed."

    Design: Difficulty/resource_temporal_overlap/enrollment_window_overlap_half_open
    """
    client = fx.create_client(legal_name="Omicron Co")
    validate_success(api.create_enrollment_window(
        create_enrollment_window_payload(client["id"], plan_year=2027,
                                          opens_at="2027-01-01T00:00:00Z",
                                          closes_at="2027-02-01T00:00:00Z"), CONSULTANT), 201)
    data = validate_success(api.create_enrollment_window(
        create_enrollment_window_payload(client["id"], plan_year=2027,
                                          opens_at="2027-02-01T00:00:00Z",
                                          closes_at="2027-03-01T00:00:00Z"), CONSULTANT), 201)
    assert data["status"] == "SCHEDULED"


# ===========================================================================
# Corner / validations — election cross-client policy
# ===========================================================================
def test_election_cross_client_policy_rejected(api):
    """PRD §3.6: "An election may only be created while its window is OPEN (otherwise
    ERR_INVALID_STATE), and its window, member, and policy must all belong to the same client
    (otherwise ERR_CLIENT_MISMATCH)."

    Design: Corner/validations/election_cross_client_policy_rejected
    """
    client_x = fx.create_client(legal_name="ClientX")
    client_y, policy_y = fx.setup_client_with_active_policy(legal_name="ClientY",
                                                            monthly_premium_cents=500_000)
    window_x = fx.create_open_window(client_x["id"])
    member_x = fx.create_member(client_x["id"], full_name="X Member")
    resp = api.create_election(
        {"window_id": window_x["id"], "census_member_id": member_x["id"],
         "policy_id": policy_y["id"], "coverage_tier": "EMPLOYEE_ONLY"},
        make_client_contact_headers(client_x["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_MISMATCH.value)


# ===========================================================================
# Corner / validations — clock-gated window transitions
# ===========================================================================
def test_open_window_before_opens_at_rejected(api):
    """PRD §3.6: "Opening the window advances it from SCHEDULED to OPEN and requires the
    logical clock to have reached opens_at; an attempt before that instant is rejected with
    ERR_WINDOW_NOT_YET_OPEN."

    Design: Corner/validations/open_window_before_opens_at_rejected
    """
    client = fx.create_client(legal_name="Future Co")
    window = fx.create_scheduled_window(client["id"], opens_at="2026-09-01T00:00:00Z",
                                       closes_at="2026-09-30T00:00:00Z")
    resp = api.open_window(window["id"], CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_YET_OPEN.value)


def test_finalize_window_before_closes_at_rejected(api):
    """PRD §3.6: "Finalizing the window advances it from OPEN to FINALIZED and requires the
    logical clock to have reached closes_at; an attempt before that instant is rejected with
    ERR_WINDOW_NOT_CLOSED."

    Design: Corner/validations/finalize_window_before_closes_at_rejected
    """
    client = fx.create_client(legal_name="Early Fin Co")
    window = fx.create_open_window(client["id"], opens_at="2026-07-01T00:00:00Z",
                                  closes_at="2026-07-31T00:00:00Z")
    resp = api.finalize_window(window["id"], CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CLOSED.value)
