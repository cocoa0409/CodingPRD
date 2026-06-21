"""HSA contribution-cap formula (tier x catch-up x running sum), the >= vs > cap boundary,
the DCFSA zero-funds approve edge, and the DCFSA separate election cap.

Translates Difficulty/combinatorial_formula, Difficulty/boundary_precision_check, and the
calculations/dcfsa_separate_election_cap_boundary corner instance.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_active_hsa, setup_active_fsa, setup_plan_year_and_participant,
    post_contribution, get_account, file_claim,
    make_adjudicator_headers, create_account_payload,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_hsa_family_plus_catchup_cap_rejects_one_cent_over(api):
    """PRD §3.3: "if that age is at least 55, the catch-up amount `hsa_catchup_cents` is
    added to the base cap, and otherwise nothing is added. The total allowed is the base cap
    plus any catch-up."
    PRD §3.3: "only a prospective total strictly greater than the allowed cap is rejected,
    with `ERR_CONTRIBUTION_CAP_EXCEEDED` (HTTP 422)."

    FAMILY base 865000 + catch-up 100000 (age 58) = 965000 allowed; contributed 900000,
    a new 65001 makes prospective 965001 > 965000 → rejected.

    Design: Difficulty/combinatorial_formula/hsa_cap_family_plus_catchup_mode_a
    """
    py, p, acc = setup_active_hsa(
        coverage_tier="FAMILY", elected_amount_cents=965000, birth_date="1968-03-01")
    post_contribution(acc["id"], 900000, acc["version"], source="PAYROLL")
    live = get_account(acc["id"])
    resp = api.create_contribution(
        acc["id"],
        {"amount_cents": 65001, "source": "EMPLOYER", "posted_at": "2026-03-01T00:00:00Z",
         "expected_account_version": live["version"]},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


def test_hsa_rejected_contribution_does_not_change_contributed(api):
    """PRD §3.3: "A successful contribution post appends a `CONTRIBUTION` `LedgerEntry`,
    recomputes the account's `contributed_cents` and `available_balance_cents` via the
    available-balance rule".

    A rejected over-cap contribution leaves contributed_cents at 900000 (only POSTED
    contributions count).

    Design: Difficulty/combinatorial_formula/hsa_cap_family_plus_catchup_mode_a
    """
    py, p, acc = setup_active_hsa(
        coverage_tier="FAMILY", elected_amount_cents=965000, birth_date="1968-03-01")
    post_contribution(acc["id"], 900000, acc["version"], source="PAYROLL")
    live = get_account(acc["id"])
    api.create_contribution(
        acc["id"],
        {"amount_cents": 65001, "source": "EMPLOYER", "posted_at": "2026-03-01T00:00:00Z",
         "expected_account_version": live["version"]},
        ADMIN)
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["contributed_cents"] == 900000, (
        f"rejected contribution must not count; expected 900000, "
        f"got {after['contributed_cents']}")


def test_hsa_cap_boundary_exact_total_accepted(api):
    """PRD §3.3: "A prospective total equal to the allowed cap is accepted; only a
    prospective total strictly greater than the allowed cap is rejected".

    Self-only cap 437500, no catch-up (age 40); contributed 400000, a 37500 contribution
    brings the prospective total to exactly 437500 — accepted (201).

    Design: Difficulty/boundary_precision_check/hsa_cap_exact_boundary_on_contributions_endpoint
    """
    py, p, acc = setup_active_hsa(
        coverage_tier="SELF_ONLY", elected_amount_cents=437500, birth_date="1986-01-01")
    post_contribution(acc["id"], 400000, acc["version"], source="PAYROLL")
    live = get_account(acc["id"])
    resp = api.create_contribution(
        acc["id"],
        {"amount_cents": 37500, "source": "INDIVIDUAL", "posted_at": "2026-03-01T00:00:00Z",
         "expected_account_version": live["version"]},
        ADMIN)
    validate_success(resp, expected_status=201)
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["contributed_cents"] == 437500


def test_hsa_cap_boundary_one_cent_over_rejected(api):
    """PRD §3.3: "only a prospective total strictly greater than the allowed cap is rejected,
    with `ERR_CONTRIBUTION_CAP_EXCEEDED` (HTTP 422)."

    With contributed exactly at the 437500 cap, one more cent (prospective 437501) is
    rejected.

    Design: Difficulty/boundary_precision_check/hsa_cap_exact_boundary_on_contributions_endpoint
    """
    py, p, acc = setup_active_hsa(
        coverage_tier="SELF_ONLY", elected_amount_cents=437500, birth_date="1986-01-01")
    post_contribution(acc["id"], 400000, acc["version"], source="PAYROLL")
    live = get_account(acc["id"])
    post_contribution(acc["id"], 37500, live["version"], source="INDIVIDUAL",
                      posted_at="2026-03-01T00:00:00Z")
    live2 = get_account(acc["id"])
    resp = api.create_contribution(
        acc["id"],
        {"amount_cents": 1, "source": "INDIVIDUAL", "posted_at": "2026-04-01T00:00:00Z",
         "expected_account_version": live2["version"]},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


def test_dcfsa_zero_contributed_blocks_approve_for_lack_of_funds(api):
    """PRD §3.4: "that the forward-looking reimbursable computation yield an amount greater
    than zero. If that projected amount would be zero, the approval is rejected for lack of
    funds with `ERR_INSUFFICIENT_FUNDS` (HTTP 422)."
    PRD §3.5: "and `contributed_cents` minus `reimbursed_cents` for a DCFSA (pay-as-you-go —
    only funds actually contributed so far are available)."

    A DCFSA with contributed_cents=0 projects basis 0, so APPROVE is rejected.

    Design: Difficulty/boundary_precision_check/dcfsa_zero_projected_basis_rejects_approve_on_adjudicate_endpoint
    """
    py, p, acc = setup_active_fsa(
        account_type="DCFSA", elected_amount_cents=500000,
        auto_adjudication_threshold_cents=1000000,
        participant_overrides={"marital_status": "SINGLE"})
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="DEPENDENT_CARE",
                       claimed_amount_cents=30000, substantiated=True)
    resp = api.adjudicate_claim(claim["id"], {"decision": "APPROVE"},
                                make_adjudicator_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


def test_dcfsa_zero_funds_approve_leaves_claim_submitted(api):
    """PRD §3.4: "Approval moves the claim from `SUBMITTED` to `APPROVED`".

    Because the zero-funds approve is rejected, the claim stays SUBMITTED.

    Design: Difficulty/boundary_precision_check/dcfsa_zero_projected_basis_rejects_approve_on_adjudicate_endpoint
    """
    py, p, acc = setup_active_fsa(
        account_type="DCFSA", elected_amount_cents=500000,
        auto_adjudication_threshold_cents=1000000,
        participant_overrides={"marital_status": "SINGLE"})
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="DEPENDENT_CARE",
                       claimed_amount_cents=30000, substantiated=True)
    api.adjudicate_claim(claim["id"], {"decision": "APPROVE"},
                         make_adjudicator_headers("adj-1"))
    after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "SUBMITTED", "rejected approve leaves claim unchanged"


def test_dcfsa_separate_marital_status_uses_separate_cap(api):
    """PRD §3.2: "For a DCFSA the cap depends on the owning participant's `marital_status`:
    a `MARRIED_SEPARATE` participant is held to `dcfsa_cap_separate_cents`".
    PRD §3.2: "An election equal to the applicable cap is accepted; only an
    `elected_amount_cents` strictly greater than the cap is rejected, with
    `ERR_ELECTION_CAP_EXCEEDED` (HTTP 422)."

    300000 exceeds the separate cap 250000 (though below the joint cap 500000) → rejected.

    Design: Corner/calculations/dcfsa_separate_election_cap_boundary
    """
    py, p = setup_plan_year_and_participant(
        clock=None, participant_overrides={"marital_status": "MARRIED_SEPARATE"})
    resp = api.create_account(
        create_account_payload(p["id"], py["id"], "DCFSA", elected_amount_cents=300000),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_ELECTION_CAP_EXCEEDED.value)
