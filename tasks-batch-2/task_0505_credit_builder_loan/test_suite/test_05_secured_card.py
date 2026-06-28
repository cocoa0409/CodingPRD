"""Secured-card lifecycle: deposits, activation, spend, suspend/resume, OCC,
freeze cascade, and deposit release (SoD, conservation, multi-hop cascade)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_secured_card, assert_card_deposit,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    create_verified_account, issue_disclosure, acknowledge_disclosure,
    setup_eligible_account_with_card_disclosure, setup_eligible_account_with_active_card,
    setup_active_card, create_card, post_deposit, card_version,
    setup_graduated_loan_with_active_card,
)


# =========================================================================
# Corner / validations: deposit minimum, cap, credit limit
# =========================================================================

def test_deposit_below_minimum_rejected(api):
    """PRD §3.9: "each deposit increment must be at least 20000 cents"

    Design: Corner/validations/deposit_below_minimum_rejected
    """
    acct, cdisc = setup_eligible_account_with_card_disclosure(state_code="CA")
    card = create_card(acct["id"], cdisc["id"])
    resp = api.create_deposit(
        card["id"], {"amount_cents": 10000, "expected_card_version": card["version"]},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_credit_limit_exceeded_on_charge(api):
    """PRD §3.9: "a charge increases `balance_cents` by `amount_cents` but must not push `balance_cents` above `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/credit_limit_exceeded_on_charge
    """
    acct, _cdisc, card = setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000)
    resp = api.charge_card(card["id"], {"amount_cents": 50001}, make_borrower_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# =========================================================================
# Difficulty / boundary_precision_check: deposit cap edge
# =========================================================================

def test_deposit_cap_exact_vs_over(api):
    """PRD §3.9: "the total of posted deposits on a card must not exceed 250000 cents, which if breached yields `ERR_DEPOSIT_CAP_EXCEEDED` (HTTP 422)."
    PRD §3.9: "Posting recomputes `deposit_cents` as the sum of all `POSTED` deposit amounts"

    Design: Difficulty/boundary_precision_check/deposit_cap_exact_vs_over
    """
    acct, cdisc = setup_eligible_account_with_card_disclosure(state_code="CA")
    card = create_card(acct["id"], cdisc["id"])
    post_deposit(card["id"], acct["id"], 200000, card["version"])  # FUNDED, total 200000
    v2 = card_version(card["id"], acct["id"])

    # total -> exactly 250000: accepted at the inclusive boundary.
    ok = validate_success(
        api.create_deposit(
            card["id"], {"amount_cents": 50000, "expected_card_version": v2},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    assert_card_deposit(ok)
    refetched = validate_success(api.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    assert refetched["deposit_cents"] == 250000

    # total would -> 250001: rejected.
    v3 = refetched["version"]
    resp = api.create_deposit(
        card["id"], {"amount_cents": 1, "expected_card_version": v3},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_CAP_EXCEEDED)


# =========================================================================
# Corner / validations + endpoints: product-kind mismatch, charge
# =========================================================================

def test_wrong_product_kind_disclosure_blocks_card(api):
    """PRD §3.9: "Creation requires the account posture to be `ELIGIBLE` (otherwise `ERR_ACCOUNT_NOT_ELIGIBLE`) and the pinned disclosure to be `ACKNOWLEDGED` with `product_kind` of `SECURED_CARD` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`)."

    Design: Corner/validations/wrong_product_kind_disclosure_blocks_card
    """
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])  # account now ELIGIBLE, but disclosure is LOAN
    resp = api.create_secured_card(
        {"account_id": acct["id"], "disclosure_id": ldisc["id"]},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)


def test_charge_increments_balance(api):
    """PRD §3.9: "Spend is recorded as a charge of `amount_cents` against the line by a `Borrower` or `LoanServicer`; a charge increases `balance_cents` by `amount_cents`"
    PRD §3.9: "sets `credit_limit_cents` equal to `deposit_cents` (the line is one-to-one secured)."

    Design: Corner/endpoints/charge_increments_balance_computed_read
    """
    acct, _cdisc, card = setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000)
    data = validate_success(
        api.charge_card(card["id"], {"amount_cents": 20000}, make_borrower_headers(acct["id"]))
    )
    assert data["balance_cents"] == 20000
    assert data["credit_limit_cents"] == 50000


# =========================================================================
# Difficulty / non_linear_state_machine: suspend/resume revert cycle
# =========================================================================

def test_card_suspend_resume_revert_cycle(api):
    """PRD §3.9: "A `LoanServicer` can suspend an `ACTIVE` card (`ACTIVE → SUSPENDED`), blocking spend while freezing the existing balance"
    PRD §3.9: "A `LoanServicer` can resume a `SUSPENDED` card (`SUSPENDED → ACTIVE`), provided the account posture is `ELIGIBLE`, making it spendable again."

    Design: Difficulty/non_linear_state_machine/card_suspend_resume_revert_cycle
    """
    acct, _cdisc, card = setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000)
    suspended = validate_success(
        api.suspend_card(card["id"], {"reason": "review"}, make_loan_servicer_headers())
    )
    assert suspended["status"] == "SUSPENDED"
    resumed = validate_success(api.resume_card(card["id"], {}, make_loan_servicer_headers()))
    assert resumed["status"] == "ACTIVE"


# =========================================================================
# Cross-cutting / OCC on deposit posting
# =========================================================================

def test_occ_stale_card_version_on_deposit(api):
    """PRD §2.8: "If `expected_card_version` does not match the target card's current `version` — because a prior deposit advanced it since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a writer working from a stale credit-limit view does not corrupt the line."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_card_version_on_deposit
    """
    acct, cdisc = setup_eligible_account_with_card_disclosure(state_code="CA")
    card = create_card(acct["id"], cdisc["id"])
    stale_version = card["version"]
    post_deposit(card["id"], acct["id"], 30000, stale_version)  # bumps card version
    resp = api.create_deposit(
        card["id"], {"amount_cents": 20000, "expected_card_version": stale_version},
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# =========================================================================
# Corner / state_machines: freeze cascade
# =========================================================================

def test_account_freeze_suspends_active_card(api):
    """PRD §3.2: "Freezing is permitted only when the account `status` is `OPEN`; it sets `status` to `FROZEN`, drives the derived `posture` to `FROZEN`, and **cascades**: every secured card of the account currently in `ACTIVE` status is moved to `SUSPENDED`, blocking card spend."
    PRD §3.2: "Unfreezing is permitted only when the account `status` is `FROZEN`; it returns the account toward `OPEN`, recomputes the posture, and **reverts the cascade**: any secured card that was suspended purely as a consequence of the freeze is restored to `ACTIVE`."

    Design: Corner/state_machines/account_freeze_suspends_active_card_cross_entity
    """
    acct, _cdisc, card = setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000)
    validate_success(
        api.freeze_account(acct["id"], {"reason": "fraud-review"}, make_compliance_officer_headers())
    )
    frozen_card = validate_success(api.get_secured_card(card["id"], make_compliance_officer_headers()))
    frozen_acct = validate_success(api.get_account(acct["id"], make_compliance_officer_headers()))
    assert frozen_card["status"] == "SUSPENDED"
    assert frozen_acct["posture"] == "FROZEN"

    validate_success(api.unfreeze_account(acct["id"], {}, make_compliance_officer_headers()))
    after_card = validate_success(api.get_secured_card(card["id"], make_compliance_officer_headers()))
    after_acct = validate_success(api.get_account(acct["id"], make_compliance_officer_headers()))
    assert after_card["status"] == "ACTIVE"
    assert after_acct["posture"] == "ELIGIBLE"


# =========================================================================
# Difficulty / cross_entity_state_dependency: release requires graduated loan
# =========================================================================

def test_deposit_release_requires_loan_graduated(api):
    """PRD §3.10: "In both cases the same conditions hold: the card's `graduation_eligible` must be true and the card's `balance_cents` must be 0, otherwise the release is rejected with `ERR_DEPOSIT_NOT_RELEASABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deposit_release_requires_loan_graduated
    """
    # ELIGIBLE account; loan funded ACTIVE (not graduated) by 'srv-A'; card ACTIVE -> not eligible.
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])
    loan = validate_success(
        api.create_loan(
            {"account_id": acct["id"], "disclosure_id": ldisc["id"],
             "principal_cents": 60000, "term_months": 12},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers("srv-A")))
    card = setup_active_card(acct["id"], cdisc["id"], deposit_cents=50000)

    # Release attempt by a DIFFERENT compliance user (SoD satisfied) still fails: not eligible.
    resp = api.release_deposit(card["id"], {}, make_compliance_officer_headers("cmp-Z"))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_RELEASABLE)
    refetched = validate_success(api.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    assert refetched["graduation_eligible"] is False


# =========================================================================
# Difficulty / priority_pair_validation_conflict: SoD beats releasability
# =========================================================================

def test_sod_conflict_beats_deposit_not_releasable(api):
    """PRD §3.10: "the acting compliance officer's `X-User-ID` must differ from the `funded_by_servicer_user_id` recorded on the linked loan. If the same person who funded the loan attempts to release the card's deposit, the request is rejected with `ERR_SOD_CONFLICT` (HTTP 409). This check is evaluated ahead of the releasability check in the priority order of §2.5."

    Design: Difficulty/priority_pair_validation_conflict/sod_conflict_beats_deposit_not_releasable
    """
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])
    loan = validate_success(
        api.create_loan(
            {"account_id": acct["id"], "disclosure_id": ldisc["id"],
             "principal_cents": 60000, "term_months": 12},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.fund_loan(loan["id"], {}, make_loan_servicer_headers("dual-1")))
    card = setup_active_card(acct["id"], cdisc["id"], deposit_cents=50000)

    # Card not graduation_eligible AND actor == funding servicer -> SoD must surface first.
    resp = api.release_deposit(card["id"], {}, make_compliance_officer_headers("dual-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)


# =========================================================================
# Difficulty / transitive_cascade + compensating_invariant: deposit release
# =========================================================================

def test_release_deposit_wallet_cascade_depth3(api):
    """PRD §3.10: "A valid release cascades in two further hops: every `POSTED` deposit on the card is moved to `RELEASED` and stamped with `released_at`, and the full `deposit_cents` is credited to the account's `wallet_cents` while `credit_limit_cents` and `deposit_cents` are both zeroed. The card ends in `CLOSED`."

    Design: Difficulty/transitive_cascade/release_deposit_wallet_cascade_depth3
    """
    acct, loan, card, _total = setup_graduated_loan_with_active_card(
        state_code="CA", principal_cents=60000, deposit_amounts=(50000,),
        servicer_user_id="servicer-S1",
    )
    # Release by a different compliance officer (SoD ok); wallet already holds 60000 savings.
    closed = validate_success(api.release_deposit(card["id"], {}, make_compliance_officer_headers("compliance-C1")))
    assert closed["status"] == "CLOSED"
    assert closed["credit_limit_cents"] == 0
    assert closed["deposit_cents"] == 0

    deposits, _meta = _list_deposits(api, card["id"], acct["id"])
    for dep in deposits:
        assert dep["status"] == "RELEASED"

    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched_acct["wallet_cents"] == 110000  # 60000 savings + 50000 released deposit


def test_card_deposit_conserved_on_release(api):
    """PRD §3.10: "the full `deposit_cents` is credited to the account's `wallet_cents` while `credit_limit_cents` and `deposit_cents` are both zeroed."
    PRD §3.9: "Posting recomputes `deposit_cents` as the sum of all `POSTED` deposit amounts"

    Design: Difficulty/compensating_invariant/card_deposit_conserved_on_release
    """
    acct, loan, card, total_deposit = setup_graduated_loan_with_active_card(
        state_code="CA", principal_cents=60000, deposit_amounts=(40000, 30000),
        servicer_user_id="srv-Q",
    )
    assert total_deposit == 70000
    closed = validate_success(api.release_deposit(card["id"], {}, make_compliance_officer_headers("cmp-R")))
    assert closed["deposit_cents"] == 0
    assert closed["credit_limit_cents"] == 0

    deposits, _meta = _list_deposits(api, card["id"], acct["id"])
    for dep in deposits:
        assert dep["status"] == "RELEASED"

    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched_acct["wallet_cents"] == 130000  # 60000 savings + 70000 released deposit


def _list_deposits(api, card_id, account_id):
    from test_helpers import validate_paginated
    resp = api.list_deposits(card_id, make_borrower_headers(account_id), params={"limit": 100})
    return validate_paginated(resp)
