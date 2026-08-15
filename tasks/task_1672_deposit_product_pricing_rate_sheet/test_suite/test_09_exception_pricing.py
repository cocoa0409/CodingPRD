"""Exception pricing: creation gates, authority ladder, segregation of
duties, return/resubmit and rebase cycles, apply/revoke compensation, and
expiry (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_exception_pricing_request,
    create_draft_sheet,
    deploy_all,
    promote_sheet_to_scheduled,
    send_all_notices,
    create_effective_sheet,
    create_exception,
    create_product,
    decide_exception,
    make_banker_headers,
    make_committee_headers,
    open_account,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BANKER = TEST_USERS["banker_headers"]
ANALYST = TEST_USERS["analyst_headers"]

CD_TIERS_480 = [tier(0, 0, 500_000, 350), tier(1, 500_000, 5_000_000, 425),
                tier(2, 5_000_000, -1, 480)]
# Contiguous two-tier variant: a 5,000,000-cent balance lands exactly on the
# 480 bp tier's lower bound (lower-inclusive).
CDA_TIERS = [tier(0, 0, 5_000_000, 400), tier(1, 5_000_000, -1, 480)]


def _cd_account(api, code, tiers, balance, market="US-WEST", effective="2026-08-15"):
    """CD product (allows exceptions) with an EFFECTIVE sheet; one account."""
    product = create_product(product_code=code, product_class="CD", term_months=12,
                             tier_application="WHOLE_BALANCE", rate_cap_bp=900,
                             allows_promos=False, allows_exceptions=True)
    setup = create_effective_sheet(product_id=product["id"], market_code=market,
                                   effective_date=effective, tiers=tiers)
    account = open_account(product["id"], market_code=market,
                           opening_balance_cents=balance, customer_ref="CX-" + code,
                           channel="BRANCH")
    return product, setup["sheet"], account


def test_exception_delta_max_and_docs_rules(api, banker_headers):
    """PRD §3.6: "At creation the server snapshots `baseline_rate_bp` — the
    tiered rate for the account's balance on the named sheet at that moment —
    computes `delta_bp` as the requested rate minus the baseline, and derives
    the `authority_tier`: `BRANCH` when the delta is at most twenty-five
    basis points, `COMMITTEE` when the delta lies between twenty-six and
    seventy-five inclusive; a delta above seventy-five basis points is
    rejected at creation with `ERR_EXCEPTION_DELTA_EXCEEDS_MAX`."
    PRD §3.6: "Creation enforces, in the order of §2.10: the product must
    allow exceptions (else `ERR_INVALID_REQUEST`); a `justification_doc_ref`
    is mandatory whenever the computed tier is `COMMITTEE` (else
    `ERR_EXCEPTION_DOCS_MISSING`); the baseline sheet must be `EFFECTIVE`
    (else `ERR_BASELINE_SHEET_NOT_EFFECTIVE`); and the delta ceiling."

    Design: Corner/validations/exception_delta_max_and_docs_rules
    """
    _, sheet, account = _cd_account(api, "CDD", single_tier(400), 1_000_000)

    # Delta exactly 75: the inclusive maximum, COMMITTEE tier, docs supplied.
    resp = api.create_exception_pricing_request(
        {"account_id": account["id"], "sheet_id": sheet["id"],
         "requested_rate_bp": 475, "term_days": 60,
         "justification_doc_ref": "DOC-75"},
        make_banker_headers("banker-1"))
    at_max = validate_success(resp, 201)
    assert_exception_pricing_request(at_max)
    assert at_max["baseline_rate_bp"] == 400
    assert at_max["delta_bp"] == 75
    assert at_max["authority_tier"] == "COMMITTEE"
    assert at_max["status"] == "UNDER_REVIEW"

    # Delta 76: one basis point over the ceiling.
    resp = api.create_exception_pricing_request(
        {"account_id": account["id"], "sheet_id": sheet["id"],
         "requested_rate_bp": 476, "term_days": 60,
         "justification_doc_ref": "DOC-76"},
        make_banker_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_DELTA_EXCEEDS_MAX, 422)

    # Delta 50 (COMMITTEE tier) without the documentation reference.
    resp = api.create_exception_pricing_request(
        {"account_id": account["id"], "sheet_id": sheet["id"],
         "requested_rate_bp": 450, "term_days": 60},
        make_banker_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_DOCS_MISSING, 422)


def test_authority_boundary_delta_25_is_branch_approvable(api):
    """PRD §3.6: "`BRANCH` when the delta is at most twenty-five basis points"
    — the boundary is inclusive.
    PRD §3.6: "`BRANCH`-tier requests may be approved by a `BranchBanker` or
    the `PricingCommittee`, while `COMMITTEE`-tier requests are the
    committee's alone, with violations rejected as
    `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/exception_authority_boundary_25_vs_26
    """
    _, sheet, account = _cd_account(api, "CDA", CDA_TIERS, 5_000_000)
    # Balance exactly 5,000,000 lands in the 480 tier (lower-inclusive).
    x25 = create_exception(account["id"], sheet["id"], requested_rate_bp=505,
                           term_days=60, submitter_user_id="banker-1")
    assert x25["baseline_rate_bp"] == 480
    assert x25["delta_bp"] == 25
    assert x25["authority_tier"] == "BRANCH"

    decided = decide_exception(x25["id"], "APPROVE", role="BranchBanker",
                               user_id="banker-2")
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "banker-2"


def test_authority_boundary_delta_26_requires_committee(api):
    """PRD §3.6: "At creation the server snapshots `baseline_rate_bp` — the
    tiered rate for the account's balance on the named sheet at that moment —
    computes `delta_bp` as the requested rate minus the baseline, and derives
    the `authority_tier`: `BRANCH` when the delta is at most twenty-five basis
    points, `COMMITTEE` when the delta lies between twenty-six and
    seventy-five inclusive; a delta above seventy-five basis points is
    rejected at creation with `ERR_EXCEPTION_DELTA_EXCEEDS_MAX`."
    PRD §3.6: "while `COMMITTEE`-tier requests are the committee's alone, with
    violations rejected as `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/exception_authority_boundary_25_vs_26
    """
    _, sheet, account = _cd_account(api, "CDA", CDA_TIERS, 5_000_000)
    x26 = create_exception(account["id"], sheet["id"], requested_rate_bp=506,
                           term_days=60, justification_doc_ref="DOC-26",
                           submitter_user_id="banker-1")
    assert x26["delta_bp"] == 26
    assert x26["authority_tier"] == "COMMITTEE"

    resp = api.decide_exception_pricing_request(
        x26["id"], {"decision": "APPROVE"}, make_banker_headers("banker-2"))
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_AUTHORITY_INSUFFICIENT, 403)

    # The failed attempt leaves the request decidable by the committee.
    decided = decide_exception(x26["id"], "APPROVE", role="PricingCommittee",
                               user_id="committee-1")
    assert decided["status"] == "APPROVED"


def test_segregation_of_duties_on_exception_decision(api):
    """PRD §3.6: "Decisions are expressed through a `decision` value and are
    segregated: the deciding operator's `X-User-ID` must differ from
    `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.6: "Approval records `decided_by_user_id`."

    Design: Corner/validations/segregation_of_duties_on_exception_decision
    """
    _, sheet, account = _cd_account(api, "CDS", single_tier(400), 1_000_000)
    req = create_exception(account["id"], sheet["id"], requested_rate_bp=450,
                           term_days=60, justification_doc_ref="DOC-S",
                           submitter_user_id="banker-1")
    assert req["submitted_by_user_id"] == "banker-1"

    # The submitter's own id is barred even when the role would qualify.
    resp = api.decide_exception_pricing_request(
        req["id"], {"decision": "APPROVE"}, make_committee_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    decided = decide_exception(req["id"], "APPROVE", role="PricingCommittee",
                               user_id="committee-1")
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "committee-1"


def test_exception_return_resubmit_recomputes_delta(api):
    """PRD §3.6: "Resubmission belongs to the original submitting banker
    alone, and is available from both `RETURNED` and `REBASE_REQUIRED`, moving
    the request back to `UNDER_REVIEW`."
    PRD §3.6: "In both cases the server re-snapshots `baseline_rate_bp` from
    the pair's current `EFFECTIVE` sheet and recomputes `delta_bp` and
    `authority_tier`; for a `RETURNED` request the `sheet_id` is additionally
    re-pointed to that current effective sheet."
    PRD §3.6: "A `DECLINE` decision moves `UNDER_REVIEW → DECLINED`, and a
    `RETURN` decision moves `UNDER_REVIEW → RETURNED`; both enforce
    segregation alone, and both record the decider."

    Design: Difficulty/non_linear_state_machine/exception_return_resubmit_cycle
    """
    _, sheet, account = _cd_account(api, "CD8", CD_TIERS_480, 5_000_000)
    req = create_exception(account["id"], sheet["id"], requested_rate_bp=500,
                           term_days=90, submitter_user_id="banker-1")
    assert req["baseline_rate_bp"] == 480  # 5,000,000 lands in the 480 tier
    assert req["delta_bp"] == 20
    assert req["authority_tier"] == "BRANCH"
    assert req["status"] == "UNDER_REVIEW"

    returned = decide_exception(req["id"], "RETURN", role="PricingCommittee",
                                user_id="committee-1")
    assert returned["status"] == "RETURNED"

    resp = api.resubmit_exception_pricing_request(
        req["id"], {"requested_rate_bp": 505}, make_banker_headers("banker-1"))
    resubmitted = validate_success(resp, 200)
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["baseline_rate_bp"] == 480
    assert resubmitted["delta_bp"] == 25
    assert resubmitted["authority_tier"] == "BRANCH"


def test_exception_cycle_completes_with_approve(api):
    """PRD §3.6: "Resubmission belongs to the original submitting banker
    alone, and is available from both `RETURNED` and `REBASE_REQUIRED`, moving
    the request back to `UNDER_REVIEW`."
    PRD §3.6: "An `APPROVE` decision moves `UNDER_REVIEW → APPROVED` and adds
    two further gates — the baseline sheet must still be `EFFECTIVE` (else
    `ERR_BASELINE_SHEET_NOT_EFFECTIVE`), and the actor must hold the tier's
    authority: `BRANCH`-tier requests may be approved by a `BranchBanker` or
    the `PricingCommittee`, while `COMMITTEE`-tier requests are the
    committee's alone, with violations rejected as
    `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`."

    Design: Difficulty/non_linear_state_machine/exception_return_resubmit_cycle
    """
    _, sheet, account = _cd_account(api, "CD8", CD_TIERS_480, 5_000_000)
    req = create_exception(account["id"], sheet["id"], requested_rate_bp=500,
                           term_days=90, submitter_user_id="banker-1")
    decide_exception(req["id"], "RETURN", role="PricingCommittee",
                     user_id="committee-1")
    validate_success(api.resubmit_exception_pricing_request(
        req["id"], {"requested_rate_bp": 505}, make_banker_headers("banker-1")))
    # The loop closes: a decision by a different banker now succeeds.
    decided = decide_exception(req["id"], "APPROVE", role="BranchBanker",
                               user_id="banker-2")
    assert decided["status"] == "APPROVED"


def _apply_revoke_scenario(api):
    """SAVINGS product (cap 500) with an EFFECTIVE 150 bp sheet; account
    1,000,000; BRANCH-tier exception at 175 approved by a second banker."""
    product = create_product(product_code="CCI", product_class="SAVINGS", term_months=0,
                             tier_application="WHOLE_BALANCE", rate_cap_bp=500)
    sheet = create_effective_sheet(product_id=product["id"],
                                   effective_date="2026-08-15",
                                   tiers=single_tier(150))["sheet"]
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="CCI1", channel="BRANCH")
    req = create_exception(account["id"], sheet["id"], requested_rate_bp=175,
                           term_days=60, submitter_user_id="banker-1")
    decide_exception(req["id"], "APPROVE", role="BranchBanker", user_id="banker-2")
    return product, sheet, account, req


def test_exception_apply_moves_account_to_exception_rate(api, banker_headers):
    """PRD §3.6: "Applying stamps the account: `rate_source` becomes
    `EXCEPTION`, `exception_request_id` is set, `exception_end_date` becomes
    the application date plus `term_days`, `exception_rate_bp` takes the
    `requested_rate_bp`, the current rate is recomputed, and the account's
    version bumps."
    PRD §3.6: "Application, by a `BranchBanker`, moves `APPROVED → APPLIED`
    under three preconditions: the baseline sheet is still `EFFECTIVE` (else
    `ERR_BASELINE_SHEET_NOT_EFFECTIVE`); the account's lifecycle is `OPEN` and
    its `rate_source` is `SHEET` (else `ERR_ACCOUNT_INVALID_STATE`); and the
    product allows exceptions (else `ERR_INVALID_REQUEST`)."

    Design: Difficulty/compensating_invariant/exception_apply_revoke_restores_sheet_rate
    """
    _, _, account, req = _apply_revoke_scenario(api)
    quote0 = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote0["current_rate_bp"] == 150

    applied = validate_success(api.apply_exception_pricing_request(
        req["id"], make_banker_headers("banker-1")))
    assert applied["status"] == "APPLIED"

    quote = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote["rate_source"] == "EXCEPTION"
    assert quote["current_rate_bp"] == 175
    assert quote["exception_rate_bp"] == 175


def test_exception_revoke_restores_sheet_rate(api, banker_headers):
    """PRD §3.6: "a `REVOKE` decision moves `APPLIED → REVOKED` and restores
    the account to sheet-derived pricing — `rate_source` back to `SHEET`;
    `exception_request_id`, `exception_end_date`, and `exception_rate_bp`
    cleared to null; the current rate recomputed from the sheet's tiers plus
    any bundle bonus; the account version bumped."

    Design: Difficulty/compensating_invariant/exception_apply_revoke_restores_sheet_rate
    """
    _, _, account, req = _apply_revoke_scenario(api)
    validate_success(api.apply_exception_pricing_request(
        req["id"], make_banker_headers("banker-1")))

    revoked = decide_exception(req["id"], "REVOKE", role="PricingCommittee",
                               user_id="committee-9")
    assert revoked["status"] == "REVOKED"

    # The apply+revoke round-trip conserves the sheet-derived rate: no drift.
    quote = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote["rate_source"] == "SHEET"
    assert quote["exception_rate_bp"] is None
    assert quote["current_rate_bp"] == 150
    restored = validate_success(api.get_deposit_account(account["id"], banker_headers))
    assert restored["exception_request_id"] is None
    assert restored["exception_end_date"] is None


def _baseline_priority_scenario(api):
    """P-CDP: S1 EFFECTIVE (480 bp at the account's tier); S2 still DRAFT for
    the same pair; one account holding 5,000,000."""
    product = create_product(product_code="CDP", product_class="CD", term_months=12,
                             tier_application="WHOLE_BALANCE", rate_cap_bp=900,
                             allows_promos=False, allows_exceptions=True)
    s1 = create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                                tiers=CD_TIERS_480)["sheet"]
    s2 = create_draft_sheet(product["id"], effective_date="2026-09-01",
                            tiers=CD_TIERS_480)
    account = open_account(product["id"], opening_balance_cents=5_000_000,
                           customer_ref="CPX", channel="BRANCH")
    return s1, s2, account


def test_exception_baseline_check_beats_delta_ceiling(api):
    """PRD §2.10: "Exception creation: the product's exception permission
    (`ERR_INVALID_REQUEST`) first, then documentation completeness
    (`ERR_EXCEPTION_DOCS_MISSING`), then baseline-sheet effectiveness
    (`ERR_BASELINE_SHEET_NOT_EFFECTIVE`), then the delta ceiling
    (`ERR_EXCEPTION_DELTA_EXCEEDS_MAX`)."

    Design: Difficulty/priority_pair_validation_conflict/exception_baseline_referential_beats_delta_fiscal
    """
    _, s2_draft, account = _baseline_priority_scenario(api)
    # Delta would be 560 - 480 = 80 > 75 AND the baseline sheet is DRAFT; the
    # earlier referential check surfaces.
    resp = api.create_exception_pricing_request(
        {"account_id": account["id"], "sheet_id": s2_draft["id"],
         "requested_rate_bp": 560, "term_days": 60,
         "justification_doc_ref": "DOC-1"},
        make_banker_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422)


def test_exception_delta_ceiling_fires_on_effective_baseline(api):
    """PRD §3.6: "a delta above seventy-five basis points is rejected at
    creation with `ERR_EXCEPTION_DELTA_EXCEEDS_MAX`."

    Design: Difficulty/priority_pair_validation_conflict/exception_baseline_referential_beats_delta_fiscal
    """
    s1, _, account = _baseline_priority_scenario(api)
    resp = api.create_exception_pricing_request(
        {"account_id": account["id"], "sheet_id": s1["id"],
         "requested_rate_bp": 560, "term_days": 60,
         "justification_doc_ref": "DOC-1"},
        make_banker_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_DELTA_EXCEEDS_MAX, 422)


def test_exception_rebase_resubmit_snapshots_new_baseline(api, banker_headers):
    """PRD §3.2: "Exception requests priced against the superseded sheet that
    sit in `UNDER_REVIEW` or `RETURNED` move to `REBASE_REQUIRED`."
    PRD §3.6: "Resubmission belongs to the original submitting banker alone,
    and is available from both `RETURNED` and `REBASE_REQUIRED`, moving the
    request back to `UNDER_REVIEW`."
    PRD §3.6: "In both cases the server re-snapshots `baseline_rate_bp` from
    the pair's current `EFFECTIVE` sheet and recomputes `delta_bp` and
    `authority_tier`; for a `RETURNED` request the `sheet_id` is additionally
    re-pointed to that current effective sheet."

    Design: Corner/state_machines/exception_rebase_resubmit_snapshots_new_baseline
    """
    _, s1, account = _cd_account(api, "CDR", single_tier(480), 5_000_000)
    req = create_exception(account["id"], s1["id"], requested_rate_bp=500,
                           term_days=60, submitter_user_id="banker-1")
    assert req["authority_tier"] == "BRANCH"  # delta 20 against the 480 sheet

    # A cheaper successor sheet activates, superseding the baseline beneath
    # the pending request.
    s2 = create_draft_sheet(s1["product_id"], effective_date="2026-09-01",
                            tiers=single_tier(460))
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-01")
    validate_success(api.activate_rate_sheet(s2["id"], ANALYST))

    rebased = validate_success(api.get_exception_pricing_request(req["id"], banker_headers))
    assert rebased["status"] == "REBASE_REQUIRED"

    resp = api.resubmit_exception_pricing_request(
        req["id"], {"justification_doc_ref": "DOC-REBASE"},
        make_banker_headers("banker-1"))
    resubmitted = validate_success(resp, 200)
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["baseline_rate_bp"] == 460  # re-snapshotted from S2
    assert resubmitted["delta_bp"] == 40
    assert resubmitted["authority_tier"] == "COMMITTEE"


def test_exception_apply_blocked_after_baseline_superseded(api, banker_headers):
    """PRD §3.6: "Application, by a `BranchBanker`, moves `APPROVED → APPLIED`
    under three preconditions: the baseline sheet is still `EFFECTIVE` (else
    `ERR_BASELINE_SHEET_NOT_EFFECTIVE`); the account's lifecycle is `OPEN` and
    its `rate_source` is `SHEET` (else `ERR_ACCOUNT_INVALID_STATE`); and the
    product allows exceptions (else `ERR_INVALID_REQUEST`)."
    PRD §3.6: "Separately, an `APPROVED` request that is never applied expires
    — `APPROVED → EXPIRED` — once logical today is more than thirty days past
    the decision date."

    Design: Corner/validations/exception_apply_blocked_after_baseline_superseded
    """
    _, s1, account = _cd_account(api, "CDB", single_tier(400), 1_000_000)
    req = create_exception(account["id"], s1["id"], requested_rate_bp=430,
                           term_days=60, justification_doc_ref="DOC-B",
                           submitter_user_id="banker-1")
    decide_exception(req["id"], "APPROVE", role="PricingCommittee",
                     user_id="committee-1")  # decision date 2026-08-15

    # APPROVED requests are not rebased; the baseline just goes stale.
    s2 = create_draft_sheet(s1["product_id"], effective_date="2026-09-01",
                            tiers=single_tier(420))
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-01")
    validate_success(api.activate_rate_sheet(s2["id"], ANALYST))

    resp = api.apply_exception_pricing_request(req["id"], make_banker_headers("banker-1"))
    validate_error(resp, ApiErrorId.ERR_BASELINE_SHEET_NOT_EFFECTIVE, 422)
    still = validate_success(api.get_exception_pricing_request(req["id"], banker_headers))
    assert still["status"] == "APPROVED"

    # 2026-10-01 is more than thirty days past the 2026-08-15 decision date.
    set_clock("2026-10-01")
    expired = validate_success(api.get_exception_pricing_request(req["id"], banker_headers))
    assert expired["status"] == "EXPIRED"


def test_decision_on_declined_exception_returns_invalid_state(api):
    """PRD §3.6: "Any decision attempted from a state other than
    `UNDER_REVIEW` — other than revocation, below — is rejected with
    `ERR_EXCEPTION_INVALID_STATE`."
    PRD §3.6: "`DECLINED`, `REVOKED`, and `EXPIRED` are terminal."

    Design: Corner/state_machines/decision_on_declined_exception_returns_invalid_state
    """
    _, sheet, account = _cd_account(api, "IV5", single_tier(480), 1_000_000)
    req = create_exception(account["id"], sheet["id"], requested_rate_bp=500,
                           term_days=30, submitter_user_id="banker-1")
    declined = decide_exception(req["id"], "DECLINE", role="PricingCommittee",
                                user_id="committee-1")
    assert declined["status"] == "DECLINED"

    resp = api.decide_exception_pricing_request(
        req["id"], {"decision": "APPROVE"}, make_committee_headers("committee-2"))
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_INVALID_STATE, 409)

