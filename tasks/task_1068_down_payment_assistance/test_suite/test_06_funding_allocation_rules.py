"""Funding-allocation screening: the award-approved state gate ahead of the
fiscal check, the zero-pool / inclusive fiscal boundary, the award ceiling, the
lien subordination order, and optimistic concurrency on the source version.

Difficulty:
  priority_pair_validation_conflict / state_beats_fiscal_on_allocation
  boundary_precision_check / funding_zero_available_pool_rejected
Corner:
  validations / allocation_exceeds_award_returns_error
  validations / lien_position_decreasing_returns_error
  cross_cutting_complexity_layers / occ_stale_funding_source_version_returns_412
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import create_funding_allocation_payload

CASE_MANAGER = fx.CASE_MANAGER


def _alloc(award_id, funding_source_id, amount_cents, lien_position, expected_version):
    return create_funding_allocation_payload(
        award_id=award_id, funding_source_id=funding_source_id,
        amount_cents=amount_cents, lien_position=lien_position,
        expected_funding_source_version=expected_version,
    )


# --- priority_pair_validation_conflict / state_beats_fiscal_on_allocation ----
def test_state_gate_beats_fiscal_when_both_fail(api):
    """PRD 3.5: "the award must be in `APPROVED` status — this state gate is
    evaluated before any concurrency or fiscal check, and a draw against an
    award in any other status is rejected with `ERR_AWARD_NOT_APPROVED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation
    """
    ctx = fx.setup_eligible_application(api, with_education=False)
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")  # PENDING_EDUCATION
    fs = fx.new_funding_source(api, total_appropriation_cents=100_000)  # far too little
    resp = api.create_funding_allocation(_alloc(award["id"], fs["id"], 5_000_000, 1, fs["version"]), CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_APPROVED.value)


def test_state_gate_fires_even_with_sufficient_funds(api):
    """PRD 3.5: "the award must be in `APPROVED` status — this state gate is
    evaluated before any concurrency or fiscal check, and a draw against an
    award in any other status is rejected with `ERR_AWARD_NOT_APPROVED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation
    """
    # Funds are ample (10,000,000 available), but the award is unapproved:
    # the state gate must still win, proving it precedes the fiscal check.
    ctx = fx.setup_eligible_application(api, with_education=False)
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")  # PENDING_EDUCATION
    fs = fx.new_funding_source(api, total_appropriation_cents=10_000_000)
    resp = api.create_funding_allocation(_alloc(award["id"], fs["id"], 5_000_000, 1, fs["version"]), CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_APPROVED.value)


# --- boundary_precision_check / funding_zero_available_pool_rejected ---------
def test_draw_against_empty_pool_rejected(api):
    """PRD 3.5: "Finally, the fiscal check, evaluated only after the
    award-approved state gate: the `amount_cents` must not exceed the funding
    source's `available_cents`, otherwise `ERR_INSUFFICIENT_FUNDS` (HTTP 409) is
    returned."

    Design: Difficulty/boundary_precision_check/funding_zero_available_pool_rejected
    """
    # Source available is exactly 0; a 1-cent draw exceeds it.
    ctx = fx.setup_approved_award(api, total_appropriation_cents=0)
    fs = ctx["funding_source"]
    resp = api.create_funding_allocation(_alloc(ctx["award"]["id"], fs["id"], 1, 1, fs["version"]), CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


def test_draw_equal_to_available_succeeds(api):
    """PRD 3.5: "Finally, the fiscal check, evaluated only after the
    award-approved state gate: the `amount_cents` must not exceed the funding
    source's `available_cents`, otherwise `ERR_INSUFFICIENT_FUNDS` (HTTP 409) is
    returned."

    Design: Difficulty/boundary_precision_check/funding_zero_available_pool_rejected
    """
    # amount_cents == available_cents does not exceed it, so the draw is accepted.
    ctx = fx.setup_approved_award(api, total_appropriation_cents=1_000_000)
    fs = ctx["funding_source"]
    resp = api.create_funding_allocation(_alloc(ctx["award"]["id"], fs["id"], 1_000_000, 1, fs["version"]), CASE_MANAGER)
    data = validate_success(resp, 201)
    assert data["status"] == "RESERVED"


# --- Corner / allocation_exceeds_award_returns_error ------------------------
def test_allocation_exceeds_award_returns_error(api):
    """PRD 3.5: "the award's current `allocated_cents` plus the new `amount_cents`
    must not exceed the award's `assistance_amount_cents`, otherwise the draw is
    rejected with `ERR_ALLOCATION_EXCEEDS_AWARD` (HTTP 422)."

    Design: Corner/validations/allocation_exceeds_award_returns_error
    """
    ctx = fx.setup_approved_award(api, total_appropriation_cents=10_000_000)  # assistance 5,000,000
    fs = ctx["funding_source"]
    resp = api.create_funding_allocation(_alloc(ctx["award"]["id"], fs["id"], 6_000_000, 1, fs["version"]), CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_AWARD.value)


# --- Corner / lien_position_decreasing_returns_error ------------------------
def test_lien_position_decreasing_returns_error(api):
    """PRD 3.5: "the supplied `lien_position` must be at least as large as the
    maximum `lien_position` among the award's existing `RESERVED` or `DISBURSED`
    allocations, and it must be non-decreasing with respect to the drawn
    source's `priority` so that the award's allocations preserve senior-to-junior
    order; a violation is rejected with `ERR_LIEN_ORDER_INVALID` (HTTP 422)."

    Design: Corner/validations/lien_position_decreasing_returns_error
    """
    ctx = fx.setup_approved_award(api, total_appropriation_cents=10_000_000)
    fs = ctx["funding_source"]
    fx.allocate(api, ctx["award"]["id"], fs["id"], 1_000_000, 2, fs["version"])  # existing max lien = 2
    fs_after = validate_success(api.get_funding_source(fs["id"], CASE_MANAGER), 200)
    resp = api.create_funding_allocation(
        _alloc(ctx["award"]["id"], fs["id"], 1_000_000, 1, fs_after["version"]), CASE_MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_LIEN_ORDER_INVALID.value)


# --- Corner / occ_stale_funding_source_version_returns_412 ------------------
def test_stale_funding_source_version_returns_412(api):
    """PRD 2.9: "If another writer has drawn against that source in the interim,
    the source's `version` will have advanced past the value the client
    supplied; the client's view of the remaining balance is therefore stale, and
    the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_funding_source_version_returns_412
    """
    ctx = fx.setup_approved_award(api, total_appropriation_cents=10_000_000)
    fs = ctx["funding_source"]
    stale_version = fs["version"]
    fx.allocate(api, ctx["award"]["id"], fs["id"], 2_000_000, 1, stale_version)  # advances version
    resp = api.create_funding_allocation(
        _alloc(ctx["award"]["id"], fs["id"], 2_000_000, 1, stale_version), CASE_MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
