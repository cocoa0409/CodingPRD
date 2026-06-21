"""Second test per difficulty instance — exercises a distinct observable
consequence of the SAME PRD rule that drives the corresponding primary test.

Each test docstring carries the same Difficulty tag as its primary partner
in another file; the coverage audit requires every difficulty instance to
be covered by at least two tests.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_donor_beneficiary_account,
    setup_account_with_earnings,
    set_clock,
    create_and_post_contribution,
    credit_market_earnings,
    create_draft_withdrawal,
    submit_withdrawal,
    approve_withdrawal,
    disburse_withdrawal,
    create_beneficiary,
    create_beneficiary_change,
    approve_beneficiary_change,
    create_state_tax_incentive,
    calculate_state_tax_incentive,
    create_form_1099q,
    create_donor,
    get_account,
    make_account_owner_headers,
    make_compliance_headers,
    make_custodian_headers,
    make_tax_authority_headers,
    create_donor_payload,
    approve_withdrawal_payload,
)


# ---------------------------------------------------------------------------
# dual_variant_calc/earnings_ratio_pre_vs_post_disbursal_divergence
# ---------------------------------------------------------------------------

def test_audit_does_not_mutate_pinned_split_after_new_contribution(api):
    """PRD §3.6: "The pinned fields on the withdrawal row are not mutated by this audit; the
    response simply returns what the split would be if recomputed today."

    Design: Difficulty/dual_variant_calc/earnings_ratio_pre_vs_post_disbursal_divergence
    """
    donor, _ben, account, a_v_after_market = setup_account_with_earnings(
        contribution_cents=300_000,
        market_credit_cents=200_000,
        donor_email="d1b@x.com",
    )
    account_id = account["id"]
    w = create_draft_withdrawal(account_id, donor["id"], 100_000, "NON_QUALIFIED")
    submit_withdrawal(w["id"], donor["id"])
    approve_withdrawal(w["id"], a_v_after_market)
    disburse_withdrawal(w["id"])
    # Capture pinned values now.
    pre_audit = api.get_withdrawal(w["id"], make_compliance_headers()).json()["data"]
    pre_basis = pre_audit["basis_portion_cents"]
    pre_earnings = pre_audit["earnings_portion_cents"]
    # New contribution shifts account totals.
    create_and_post_contribution(account_id, 200_000)
    # Audit returns recomputed split, but the persisted record stays untouched.
    api.audit_withdrawal(w["id"], make_compliance_headers())
    post_audit = api.get_withdrawal(w["id"], make_compliance_headers()).json()["data"]
    assert post_audit["basis_portion_cents"] == pre_basis
    assert post_audit["earnings_portion_cents"] == pre_earnings


# ---------------------------------------------------------------------------
# dual_variant_calc/state_tax_incentive_ca_cap_vs_ny_tiered_divergence
# ---------------------------------------------------------------------------

def test_ca_cap_clamps_eligible_contributions_above_cap(api):
    """PRD §3.8: "For donors in California, the match is the lesser of the eligible contributions
    or 600,000 cents ($6,000 — the CA annual cap), multiplied by the California rate of 0.10
    (10%), rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/state_tax_incentive_ca_cap_vs_ny_tiered_divergence
    """
    # CA donor with 1,200,000 cents posted — well above the 600k cap. Match must be 60,000.
    donor, _ben, account = setup_donor_beneficiary_account(
        donor_email="dca-clamp@x.com", donor_state="CA"
    )
    create_and_post_contribution(account["id"], 1_200_000)
    sti = create_state_tax_incentive(donor["id"], 2026)
    result = calculate_state_tax_incentive(sti["id"])
    assert result["match_cents"] == 60_000  # min(1200000, 600000) * 0.10


# ---------------------------------------------------------------------------
# combinatorial_formula/excess_withdrawal_penalty_multi_input_nonlinear
# ---------------------------------------------------------------------------

def test_non_qualified_full_earnings_penalty_branch(api):
    """PRD §3.6: "The system first computes a penalty_base_cents value according to fixed
    branching: when the expense_class is NON_QUALIFIED, the penalty base is the entire
    earnings_portion_cents just pinned"

    Design: Difficulty/combinatorial_formula/excess_withdrawal_penalty_multi_input_nonlinear
    """
    donor, _ben, account, a_v = setup_account_with_earnings(
        contribution_cents=300_000,
        market_credit_cents=200_000,
        donor_email="d2b@x.com",
    )
    # balance=500000 basis=300000 earnings=200000.
    # W amount=100000 NON_QUALIFIED -> earnings_portion = round_half_up(100000*200000/500000) = 40000.
    # penalty_base = 40000 (full earnings, NON_QUALIFIED branch). penalty = 4000.
    w = create_draft_withdrawal(account["id"], donor["id"], 100_000, "NON_QUALIFIED")
    submit_withdrawal(w["id"], donor["id"])
    approved = approve_withdrawal(w["id"], a_v)
    assert approved["earnings_portion_cents"] == 40_000
    assert approved["penalty_cents"] == 4_000


# ---------------------------------------------------------------------------
# combinatorial_formula/ny_tiered_match_pinned_per_tier_rounding_order
# ---------------------------------------------------------------------------

def test_ny_tier1_only_when_below_tier1_ceiling(api):
    """PRD §3.8: "the first tier applies a 5% rate to the eligible contributions up to the NY
    first-tier ceiling of 500,000 cents ($5,000)"

    Design: Difficulty/combinatorial_formula/ny_tiered_match_pinned_per_tier_rounding_order
    """
    # NY donor with 400000 cents — entirely within tier 1. Match = 400000 * 0.05 = 20000.
    donor, _ben, account = setup_donor_beneficiary_account(
        donor_email="dny-tier1@x.com", donor_state="NY"
    )
    create_and_post_contribution(account["id"], 400_000)
    sti = create_state_tax_incentive(donor["id"], 2026)
    result = calculate_state_tax_incentive(sti["id"])
    assert result["match_cents"] == 20_000


# ---------------------------------------------------------------------------
# transitive_cascade/contribution_post_cascade_to_state_tax_incentive_via_account
# ---------------------------------------------------------------------------

def test_account_version_increments_on_contribution_post(api):
    """PRD §3.4: "The Account.version is incremented and updated_at refreshed."

    Design: Difficulty/transitive_cascade/contribution_post_cascade_to_state_tax_incentive_via_account
    """
    _donor, _ben, account = setup_donor_beneficiary_account(donor_email="d5b@x.com")
    v_before = account["version"]
    create_and_post_contribution(account["id"], 100_000)
    a_after = get_account(account["id"])
    assert a_after["version"] == v_before + 1


# ---------------------------------------------------------------------------
# transitive_cascade/withdrawal_disburse_cascade_to_form_1099q_via_account_ytd
# ---------------------------------------------------------------------------

def test_disburse_updates_account_balance_and_basis(api):
    """PRD §3.5: "On success, disbursed_at_utc is pinned to the current clock, the account ledger
    is re-aggregated (the same primary-source pass as on posting: account_balance_cents
    decreases by amount_cents, total_basis_cents decreases by the pinned basis_portion_cents,
    and total_earnings_cents is recomputed as balance minus basis), and Account.version is
    incremented."

    Design: Difficulty/transitive_cascade/withdrawal_disburse_cascade_to_form_1099q_via_account_ytd
    """
    donor, _ben, account, a_v1 = setup_account_with_earnings(
        contribution_cents=2_000_000,
        market_credit_cents=500_000,
        donor_email="d6b@x.com",
    )
    # balance=2500000 basis=2000000 earnings=500000.
    w = create_draft_withdrawal(account["id"], donor["id"], 300_000, "HIGHER_ED_TUITION")
    submit_withdrawal(w["id"], donor["id"])
    approved = approve_withdrawal(w["id"], a_v1)
    # earnings_portion = round_half_up(300000*500000/2500000) = 60000; basis = 240000.
    assert approved["earnings_portion_cents"] == 60_000
    assert approved["basis_portion_cents"] == 240_000
    disburse_withdrawal(w["id"])
    after = get_account(account["id"])
    # balance decreases by 300000 -> 2200000; basis decreases by 240000 -> 1760000.
    assert after["account_balance_cents"] == 2_200_000
    assert after["total_basis_cents"] == 1_760_000


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict/state_beats_business_fiscal_on_revise_after_three_rejections
# ---------------------------------------------------------------------------

def test_state_precondition_surfaces_before_balance_check_on_approve(api):
    """PRD §2.8: "Where a single endpoint is guarded by checks from more than one tier, the tier
    order is authoritative: a state-precondition failure surfaces before an OCC-stale failure,
    an OCC-stale failure surfaces before a balance failure"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_revise_after_three_rejections
    """
    # Two failures coexist on /approve: (a) status != SUBMITTED [state, priority 6]
    # AND (b) amount > balance [fiscal, priority 15]. State must surface first.
    donor, _ben, account = setup_donor_beneficiary_account(donor_email="d7b@x.com")
    posted = create_and_post_contribution(account["id"], 50_000)
    a_v = posted["version"]
    # Withdrawal of 200000 in DRAFT (never submitted) AND amount > balance (50000).
    w = create_draft_withdrawal(account["id"], donor["id"], 200_000, "HIGHER_ED_TUITION")
    resp = api.approve_withdrawal(
        w["id"], approve_withdrawal_payload(a_v), make_compliance_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict/auth_segregation_beats_state_occ_on_beneficiary_change_approve
# ---------------------------------------------------------------------------

def test_segregation_surfaces_before_occ_when_same_user_approves_own_change(api):
    """PRD §2.8: "Segregation-of-duties (ERR_SEGREGATION_OF_DUTIES) on the two approve endpoints
    where it applies. ... Optimistic-concurrency stale-version (ERR_STALE_ACCOUNT_VERSION) on
    the two approve endpoints that take expected_account_version."

    Design: Difficulty/priority_pair_validation_conflict/auth_segregation_beats_state_occ_on_beneficiary_change_approve
    """
    # Without bumping the account version (so OCC alone would pass), the same X-User-ID who
    # created the change tries to approve — segregation must still fire.
    donor, b1, account = setup_donor_beneficiary_account(donor_email="d8b@x.com")
    a_v0 = account["version"]
    b2 = create_beneficiary(
        full_name="B8c",
        date_of_birth="2010-06-01",
        relationship_class="SIBLING",
        federal_tax_id_last4="3333",
    )
    bc = create_beneficiary_change(account["id"], donor["id"], b2["id"])
    # Approver = same X-User-ID, as ComplianceOfficer. OCC version is fresh.
    from prd_bench_local_runner.testing import build_user_headers
    same_user_compliance_headers = build_user_headers(donor["id"], "ComplianceOfficer")
    resp = api.approve_beneficiary_change(
        bc["id"], {"expected_account_version": a_v0}, same_user_compliance_headers
    )
    validate_error(
        resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )


# ---------------------------------------------------------------------------
# boundary_precision_check/k12_cap_exact_equality_no_excess
# ---------------------------------------------------------------------------

def test_k12_cap_one_cent_over_creates_one_cent_excess(api):
    """PRD §3.6: "the k12_excess_cents is the larger of zero and that projected value minus the
    1,000,000-cent annual cap. The cap is inclusive of equality at the boundary: a projected
    running total of exactly 1,000,000 cents yields k12_excess_cents of zero."

    Design: Difficulty/boundary_precision_check/k12_cap_exact_equality_no_excess
    """
    donor, _ben, account = setup_donor_beneficiary_account(donor_email="d9b@x.com")
    posted = create_and_post_contribution(account["id"], 2_000_000)
    a_v1 = posted["version"]
    # W1 K_12 600000.
    w1 = create_draft_withdrawal(account["id"], donor["id"], 600_000, "K_12_TUITION")
    submit_withdrawal(w1["id"], donor["id"])
    approve_withdrawal(w1["id"], a_v1)
    disbursed = disburse_withdrawal(w1["id"])
    a_v3 = disbursed["version"]
    # W2 K_12 400001 -> projected ytd = 1000001 -> k12_excess = 1.
    w2 = create_draft_withdrawal(account["id"], donor["id"], 400_001, "K_12_TUITION")
    submit_withdrawal(w2["id"], donor["id"])
    approved = approve_withdrawal(w2["id"], a_v3)
    assert approved["k12_excess_cents"] == 1


# ---------------------------------------------------------------------------
# boundary_precision_check/form_1099q_issuance_year_boundary_dec_31_vs_jan_1
# ---------------------------------------------------------------------------

def test_form_1099q_issuance_late_year_after_jan_1_succeeds(api):
    """PRD §3.9: "The issue step requires the current clock to be at or after January 1 of the
    year following the tax_year — pre-year-end issuance is rejected with
    ERR_FORM_PREMATURE_ISSUANCE."

    Design: Difficulty/boundary_precision_check/form_1099q_issuance_year_boundary_dec_31_vs_jan_1
    """
    set_clock("2026-06-01T00:00:00.000Z")
    donor, _ben, account = setup_donor_beneficiary_account(
        clock_iso=None, donor_email="d10b@x.com"
    )
    posted = create_and_post_contribution(account["id"], 500_000)
    w = create_draft_withdrawal(account["id"], donor["id"], 200_000, "HIGHER_ED_TUITION")
    submit_withdrawal(w["id"], donor["id"])
    approve_withdrawal(w["id"], posted["version"])
    disburse_withdrawal(w["id"])
    form = create_form_1099q(account["id"], 2026)
    # Now well past Jan 1 of (tax_year + 1).
    set_clock("2027-03-15T00:00:00.000Z")
    resp = api.issue_form_1099q(form["id"], make_tax_authority_headers())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency/withdrawal_submit_blocked_by_pending_beneficiary_change
# ---------------------------------------------------------------------------

def test_withdrawal_submit_succeeds_after_pending_change_is_rejected(api):
    """PRD §3.5: "it must not be in flight with any PENDING BeneficiaryChange (the account's
    beneficiary is allowed to change only while no withdrawal is mid-review)"

    Design: Difficulty/cross_entity_state_dependency/withdrawal_submit_blocked_by_pending_beneficiary_change
    """
    donor, _b1, account = setup_donor_beneficiary_account(donor_email="d11b@x.com")
    create_and_post_contribution(account["id"], 200_000)
    b2 = create_beneficiary(
        full_name="B11c",
        date_of_birth="2010-06-01",
        relationship_class="SIBLING",
        federal_tax_id_last4="3333",
    )
    bc = create_beneficiary_change(account["id"], donor["id"], b2["id"])
    # Reject the pending change -> no longer PENDING.
    api.reject_beneficiary_change(bc["id"], make_compliance_headers())
    # Now the submit must succeed.
    w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
    submitted = submit_withdrawal(w["id"], donor["id"])
    assert submitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency/withdrawal_submit_blocked_by_account_restricted_status
# ---------------------------------------------------------------------------

def test_withdrawal_submit_succeeds_after_account_released_back_to_open(api):
    """PRD §3.5: "The submit step requires the account to be in OPEN status"
    PRD §3.2: "the same officer (or a colleague) later returns the account to OPEN by lifting the
    hold, driving the transition RESTRICTED -> OPEN."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_submit_blocked_by_account_restricted_status
    """
    donor, _ben, account = setup_donor_beneficiary_account(donor_email="d12b@x.com")
    create_and_post_contribution(account["id"], 200_000)
    w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
    api.restrict_account(account["id"], make_compliance_headers())
    api.release_account(account["id"], make_compliance_headers())
    submitted = submit_withdrawal(w["id"], donor["id"])
    assert submitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap/k12_annual_cap_aggregate_capacity_interval_on_account
# ---------------------------------------------------------------------------

def test_k12_qualified_portion_only_increments_ytd(api):
    """PRD §3.5: "When the expense_class is K_12_TUITION, the account's running
    ytd_qualified_k12_cents is incremented by the qualified portion of this withdrawal only —
    that is, by amount_cents minus k12_excess_cents — so that the running total reflects only
    the cents that actually counted as qualified K-12 distribution under the annual cap."

    Design: Difficulty/resource_temporal_overlap/k12_annual_cap_aggregate_capacity_interval_on_account
    """
    donor, _ben, account = setup_donor_beneficiary_account(donor_email="d13b@x.com")
    posted = create_and_post_contribution(account["id"], 2_000_000)
    a_v1 = posted["version"]
    # W1 K_12 800000 (no excess) -> ytd=800000.
    w1 = create_draft_withdrawal(account["id"], donor["id"], 800_000, "K_12_TUITION")
    submit_withdrawal(w1["id"], donor["id"])
    approve_withdrawal(w1["id"], a_v1)
    disbursed = disburse_withdrawal(w1["id"])
    a_after_w1 = get_account(account["id"])
    assert a_after_w1["ytd_qualified_k12_cents"] == 800_000
    a_v3 = disbursed["version"]
    # W2 K_12 500000 -> excess=300000; qualified portion = 200000; ytd += 200000 = 1000000.
    w2 = create_draft_withdrawal(account["id"], donor["id"], 500_000, "K_12_TUITION")
    submit_withdrawal(w2["id"], donor["id"])
    approve_withdrawal(w2["id"], a_v3)
    disburse_withdrawal(w2["id"])
    a_after_w2 = get_account(account["id"])
    assert a_after_w2["ytd_qualified_k12_cents"] == 1_000_000


# ---------------------------------------------------------------------------
# resource_temporal_overlap/contribution_reverse_72h_strict_adjacency_window_on_contribution
# ---------------------------------------------------------------------------

def test_contribution_reverse_one_second_inside_window_succeeds(api):
    """PRD §3.4: "the clock-time delta between the current clock and the contribution's
    posted_at_utc must be strictly less than 72 hours, or the request is rejected with
    ERR_REVERSE_WINDOW_CLOSED."

    Design: Difficulty/resource_temporal_overlap/contribution_reverse_72h_strict_adjacency_window_on_contribution
    """
    _donor, _ben, account = setup_donor_beneficiary_account(donor_email="d14b@x.com")
    posted = create_and_post_contribution(account["id"], 100_000)
    # Advance to +71h59m59.999s — strictly less than 72h.
    set_clock("2026-03-03T23:59:59.999Z")
    resp = api.reverse_contribution(posted["id"], make_custodian_headers())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "REVERSED"


# ---------------------------------------------------------------------------
# compensating_invariant/contribution_post_reverse_preserves_account_balance_cents
# ---------------------------------------------------------------------------

def test_contribution_reverse_restores_basis_after_nonzero_pre_state(api):
    """PRD §3.4: "On success, the same re-aggregation pass refreshes the account's
    account_balance_cents, total_basis_cents, and total_earnings_cents; Account.version is
    incremented; and the donor's StateTaxIncentive for the original tax_year is recomputed."

    Design: Difficulty/compensating_invariant/contribution_post_reverse_preserves_account_balance_cents
    """
    # Pre-state: one already-POSTED contribution of 50000. Reverse of a second contribution
    # restores balance/basis to (50000, 50000), not to (0, 0).
    _donor, _ben, account = setup_donor_beneficiary_account(donor_email="d15b@x.com")
    first = create_and_post_contribution(account["id"], 50_000)
    pre = get_account(account["id"])
    assert pre["account_balance_cents"] == 50_000
    assert pre["total_basis_cents"] == 50_000
    second = create_and_post_contribution(account["id"], 100_000)
    # Reverse within 72h.
    set_clock("2026-03-02T00:00:00.000Z")
    resp = api.reverse_contribution(second["id"], make_custodian_headers())
    validate_success(resp, expected_status=200)
    post = get_account(account["id"])
    assert post["account_balance_cents"] == 50_000
    assert post["total_basis_cents"] == 50_000


# ---------------------------------------------------------------------------
# compensating_invariant/beneficiary_change_round_trip_preserves_account_beneficiary_id
# ---------------------------------------------------------------------------

def test_beneficiary_change_round_trip_bumps_account_version_twice(api):
    """PRD §3.7: "on approval, the account's beneficiary_id is overwritten with the change's
    to_beneficiary_id, and Account.version is incremented along with a refresh of updated_at."

    Design: Difficulty/compensating_invariant/beneficiary_change_round_trip_preserves_account_beneficiary_id
    """
    donor, b1, account = setup_donor_beneficiary_account(donor_email="d16b@x.com")
    v0 = account["version"]
    b2 = create_beneficiary(
        full_name="B16c",
        date_of_birth="2010-06-01",
        relationship_class="CHILD",
        federal_tax_id_last4="3333",
    )
    bc1 = create_beneficiary_change(account["id"], donor["id"], b2["id"])
    approve_beneficiary_change(bc1["id"], v0)
    mid = get_account(account["id"])
    assert mid["version"] == v0 + 1
    bc2 = create_beneficiary_change(account["id"], donor["id"], b1["id"])
    approve_beneficiary_change(bc2["id"], mid["version"])
    final = get_account(account["id"])
    assert final["version"] == v0 + 2
    assert final["beneficiary_id"] == b1["id"]
