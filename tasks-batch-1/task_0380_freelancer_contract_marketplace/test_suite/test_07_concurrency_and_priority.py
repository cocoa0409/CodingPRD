"""Validation precedence (existence-before-state) and optimistic concurrency on funding.

Queue A: priority_pair_validation_conflict / priority_existence_before_state_on_release.
Queue B: cross_cutting_complexity_layers / occ_stale_version_on_fund.

SKIPPED — priority_pair_validation_conflict / priority_state_before_fiscal_on_fund:
PRD §2.6 fixes the precedence of the first four checks (auth, authz, existence, structural)
but explicitly defers the relative ordering of the domain-specific checks to §3 ("whose
relative ordering is noted there"). §3.5 lists milestone state and wallet sufficiency among
the fund preconditions but does not commit to the milestone-state check pre-empting the
wallet check. Two PRD-faithful implementers could legitimately report either
ERR_INVALID_MILESTONE_STATE or ERR_INSUFFICIENT_WALLET when both hold, so the asserted
ERR_INVALID_MILESTONE_STATE is not uniquely derivable. This is the `validation-priority`
silence pattern — the instance is not translated.

SKIPPED — cross_cutting_complexity_layers / occ_correct_version_on_release: an
excluded_because stub whose happy-path release is already covered by the
dual_variant_milestone_release_standard_vs_split difficulty instance; not translated.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_milestone_payload, fund_payload, release_payload,
    make_client_headers, make_freelancer_headers,
    create_client, create_freelancer,
    create_active_contract, add_milestone,
)


# ─── Existence precedence (priority 3) over state (priority 6) ────────
def test_release_nonexistent_milestone_returns_not_found(api):
    """PRD §2.5: "the system validates the identifiers strictly left to right and rejects on
    the first one that does not resolve to an existing resource ... only once the contract
    resolves does a bad milestone identifier surface as ERR_MILESTONE_NOT_FOUND."
    PRD §2.6: "third, existence of every path and body identifier, resolved left to right ...
    Only after all four of these pass does the system reach the domain-specific checks ...
    resource state".

    Releasing a non-existent milestone id on an existing ACTIVE contract returns
    ERR_MILESTONE_NOT_FOUND (existence precedes the state check).

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_before_state_on_release
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=0, tax_id_on_file=True)
    cv = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    res = api.release_milestone(
        ctx["contract"]["id"], "00000000-0000-4000-8000-000000000000",
        release_payload(cv), ctx["client_headers"])
    validate_error(res, "ERR_MILESTONE_NOT_FOUND", expected_status=404)


def test_fund_nonexistent_milestone_returns_not_found(api):
    """PRD §2.5: "only once the contract resolves does a bad milestone identifier surface as
    ERR_MILESTONE_NOT_FOUND."
    PRD §2.6: existence is resolved before "the domain-specific checks ... resource state".

    On an ACTIVE contract, funding a non-existent milestone id returns ERR_MILESTONE_NOT_FOUND
    rather than any state error — existence is checked first.

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_before_state_on_release
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=20000, tax_id_on_file=True)
    cv = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    res = api.fund_milestone(
        ctx["contract"]["id"], "00000000-0000-4000-8000-000000000000",
        fund_payload(cv), ctx["client_headers"])
    validate_error(res, "ERR_MILESTONE_NOT_FOUND", expected_status=404)


# ─── OCC: stale contract version on fund ──────────────────────────────
def test_stale_contract_version_on_second_fund_rejected(api):
    """PRD §2.8: "A fund request must carry expected_contract_version and that value must
    equal the target contract's current version; if another writer has advanced the
    contract's version since the client last read it — because some earlier fund or release
    already moved escrow — the fund is rejected with ERR_STALE_CONTRACT_VERSION (HTTP 412)".

    Funding M1 advances the version; funding M2 with the pre-advance version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_fund
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=40000,
                                 budget_cents=50000, deposit_cents=40000, tax_id_on_file=True)
    m1 = add_milestone(ctx, 20000, ordinal=1, title="M1")
    m2 = add_milestone(ctx, 20000, ordinal=2, title="M2")
    cv0 = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    # First fund succeeds and advances the contract version past cv0.
    validate_success(api.fund_milestone(
        ctx["contract"]["id"], m1["id"], fund_payload(cv0), ctx["client_headers"]), 200)
    # Second fund carries the now-stale cv0.
    res = api.fund_milestone(
        ctx["contract"]["id"], m2["id"], fund_payload(cv0), ctx["client_headers"])
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", expected_status=412)
    m2_after = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m2["id"], ctx["client_headers"]), 200)
    assert m2_after["status"] == "DRAFT"
