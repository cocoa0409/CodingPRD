"""Validation precedence pairs, numeric/temporal boundaries, and optimistic
concurrency (Difficulty queue: priority_pair_validation_conflict,
boundary_precision_check, optimistic_concurrency)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_estate, create_petition, nominate_representative,
    create_open_estate_with_nominated_pr, create_estate_with_appointed_pr,
    create_independent_estate_with_appointed_pr,
    file_bond, file_claim, allow_claim,
    setup_accounting_estate_with_marshaled_cash,
    setup_distributing_estate_with_cash, propose_distribution, approve_distribution,
    set_clock,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict
# --------------------------------------------------------------------------- #
def test_cross_entity_state_beats_claim_period_closed(api):
    """PRD §2.11: "Only then are the stateful checks applied, in this order:
    optimistic concurrency on `expected_estate_version` (`ERR_STALE_VERSION`), the
    target resource's own from-state (`ERR_INVALID_STATE`), and any cross-entity
    state gate (`ERR_CROSS_ENTITY_STATE`). Domain-specific fiscal and temporal
    checks — the claim period, the payment waterfall, fund sufficiency, residue
    limits, and the two hearing-conflict checks — are applied after those
    foundational gates".

    A claim.allow with BOTH the acting PR not APPOINTED (cross-entity gate) AND
    filed_at past the bar date (claim period) surfaces the earlier-ordered
    ERR_CROSS_ENTITY_STATE.

    Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_claim_period_closed
    """
    est = create_estate(gross_estate_value_cents=300_000)   # INDEPENDENT
    pet = create_petition(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE))
    rep = nominate_representative(est["id"], pet["id"])       # NOT appointed
    set_clock("2026-12-01T00:00:00Z")                        # past bar date
    claim = file_claim(est["id"], "GENERAL", 100_000, "Late")

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.allow_claim(
        claim["id"], {"allowed_amount_cents": 100_000, "expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)


def test_claim_priority_beats_insufficient_funds(api):
    """PRD §3.8: "A claim may be paid only when it is the lowest-ordered claim that
    is `ALLOWED` and not yet `PAID`; if any strictly-higher-ranked allowed claim
    remains unpaid, the payment is rejected with `ERR_CLAIM_PRIORITY_VIOLATION`."

    Paying a GENERAL claim while a senior SECURED claim is unpaid AND the pool is
    0 surfaces the priority violation (evaluated before the funds gate).

    Design: Difficulty/priority_pair_validation_conflict/claim_priority_beats_insufficient_funds
    """
    # ACCOUNTING estate with pool 0: mock via a zero-cash marshaled estate.
    est, rep, asset = setup_accounting_estate_with_marshaled_cash(cash_cents=0, gross=6_000_000)
    claim_sec = file_claim(est["id"], "SECURED", 100_000, "Bank")
    claim_gen = file_claim(est["id"], "GENERAL", 100_000, "Vendor")
    allow_claim(est["id"], claim_sec["id"], 100_000)
    allow_claim(est["id"], claim_gen["id"], 100_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.pay_claim(claim_gen["id"], {"expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_CLAIM_PRIORITY_VIOLATION)


# --------------------------------------------------------------------------- #
# boundary_precision_check
# --------------------------------------------------------------------------- #
def test_claim_bar_date_inclusive_boundary_allows(api):
    """PRD §3.5: "The bar date is a half-open boundary: a claim whose `filed_at` is
    at or before the `claim_bar_date` instant is within the period, while a claim
    whose `filed_at` is strictly after it is out of time."
    PRD §3.2: "its `claim_bar_date` is computed as the opening instant plus 120 days".

    Claim period opens at 2026-05-01; bar date = +120 days = 2026-08-29. A claim
    filed at exactly 2026-08-29T00:00:00Z is inside the period and becomes ALLOWED.

    Design: Difficulty/boundary_precision_check/claim_bar_date_inclusive_boundary
    """
    set_clock("2026-05-01T00:00:00Z")
    est, pet, rep = create_independent_estate_with_appointed_pr()   # granted at 2026-05-01
    set_clock("2026-08-29T00:00:00Z")                              # exactly on the bar date
    claim = file_claim(est["id"], "GENERAL", 100_000, "Edge")

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    allowed = validate_success(api.allow_claim(
        claim["id"], {"allowed_amount_cents": 100_000, "expected_estate_version": v}, REP))
    assert allowed["status"] == "ALLOWED", (
        f"a claim filed exactly on the bar date should be ALLOWED, got {allowed['status']}")
    assert allowed["allowed_amount_cents"] == 100_000


def test_bond_penal_meets_required_ge_boundary_approves(api):
    """PRD §3.3: "A judge approving a bond advances it `FILED → APPROVED`, permitted
    only when the bond's `penal_amount_cents` is greater than or equal to its
    `required_amount_cents`; a shortfall is rejected with `ERR_BOND_INSUFFICIENT`."

    A bond whose penal 3250000 exactly equals required 3250000 is approved (the
    inclusive >= edge).

    Design: Difficulty/boundary_precision_check/bond_penal_meets_required_ge_boundary
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_250_000)
    assert bond["required_amount_cents"] == 3_250_000

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    approved = validate_success(
        api.approve_bond(bond["id"], {"expected_estate_version": v}, JUDGE))
    assert approved["status"] == "APPROVED", (
        f"penal == required should approve, got {approved['status']}")


# --------------------------------------------------------------------------- #
# optimistic_concurrency
# --------------------------------------------------------------------------- #
def test_appoint_stale_estate_version_rejected(api):
    """PRD §2.5: "appointing a personal representative must carry an
    `expected_estate_version` matching the target estate's current `version`; if
    another writer has advanced the estate's version since the client last read it
    — for example, by appointing a competing nominee that legitimately supersedes
    earlier attempts — the appointment is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    The bond approval bumps the estate version; an appoint still carrying the
    pre-approval version is rejected 412.

    Design: Difficulty/optimistic_concurrency/appoint_stale_estate_version_rejected
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_250_000)
    v_pre_approve = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(
        api.approve_bond(bond["id"], {"expected_estate_version": v_pre_approve}, JUDGE))

    resp = api.appoint_representative(
        rep["id"], {"expected_estate_version": v_pre_approve}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "NOMINATED", (
        f"PR should remain NOMINATED after a stale appoint, got {rep_after['status']}")


def test_distribution_approve_stale_estate_version_rejected(api):
    """PRD §2.5: "approving a distribution must carry an `expected_estate_version`
    matching the target estate's current `version`; if a prior distribution
    approval or claim payment has consumed residue and advanced the estate's
    `version` since the client last read it, the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    A first distribution approval bumps the version; a second approve carrying the
    pre-first-approval version is rejected 412.

    Design: Difficulty/optimistic_concurrency/distribution_approve_stale_estate_version_rejected
    """
    est, rep, ben = setup_distributing_estate_with_cash(cash_cents=1_000_000)
    dist_a = propose_distribution(est["id"], ben["id"], 300_000)
    dist_b = propose_distribution(est["id"], ben["id"], 200_000)

    v_pre_first = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.approve_distribution(
        dist_a["id"], {"expected_estate_version": v_pre_first}, JUDGE))

    resp = api.approve_distribution(
        dist_b["id"], {"expected_estate_version": v_pre_first}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    dist_b_after = get_success_data(api.get_distribution(dist_b["id"], CLERK))
    assert dist_b_after["status"] == "PROPOSED", (
        f"second distribution should remain PROPOSED, got {dist_b_after['status']}")


# --------------------------------------------------------------------------- #
# Second tests (≥2 per instance)
# --------------------------------------------------------------------------- #
def test_cross_entity_state_gate_alone_rejects_unappointed_allow(api):
    """PRD §3.5: "the acting `PersonalRepresentative` must be `APPOINTED` and own
    this estate, since the representative's state gates claim allowance
    (`ERR_CROSS_ENTITY_STATE`)".

    Isolating the cross-entity gate: a NOMINATED (not APPOINTED) PR allowing an
    in-period claim is rejected ERR_CROSS_ENTITY_STATE (clock left at default so
    the claim is well within the period — only the PR-state gate can fire).

    Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_claim_period_closed
    """
    est = create_estate(gross_estate_value_cents=300_000)
    pet = create_petition(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE))
    rep = nominate_representative(est["id"], pet["id"])   # NOMINATED, not appointed
    claim = file_claim(est["id"], "GENERAL", 100_000, "InPeriod")

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.allow_claim(
        claim["id"], {"allowed_amount_cents": 100_000, "expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)


def test_claim_priority_violation_fires_even_with_funds(api):
    """PRD §3.8: "A claim may be paid only when it is the lowest-ordered claim that
    is `ALLOWED` and not yet `PAID`; if any strictly-higher-ranked allowed claim
    remains unpaid, the payment is rejected with `ERR_CLAIM_PRIORITY_VIOLATION`."

    Isolating the priority rule: even with ample funds (pool 500000), paying the
    junior GENERAL claim before the senior SECURED claim is rejected.

    Design: Difficulty/priority_pair_validation_conflict/claim_priority_beats_insufficient_funds
    """
    est, rep, asset = setup_accounting_estate_with_marshaled_cash(cash_cents=500_000, gross=6_000_000)
    claim_sec = file_claim(est["id"], "SECURED", 100_000, "Bank")
    claim_gen = file_claim(est["id"], "GENERAL", 100_000, "Vendor")
    allow_claim(est["id"], claim_sec["id"], 100_000)
    allow_claim(est["id"], claim_gen["id"], 100_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.pay_claim(claim_gen["id"], {"expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_CLAIM_PRIORITY_VIOLATION)


def test_bond_penal_below_required_rejected(api):
    """PRD §3.3: "A judge approving a bond advances it `FILED → APPROVED`, permitted
    only when the bond's `penal_amount_cents` is greater than or equal to its
    `required_amount_cents`; a shortfall is rejected with `ERR_BOND_INSUFFICIENT`."

    The X-1 side of the >= boundary: penal 3249999 (one cent below required
    3250000) is rejected.

    Design: Difficulty/boundary_precision_check/bond_penal_meets_required_ge_boundary
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_249_999)
    assert bond["required_amount_cents"] == 3_250_000

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.approve_bond(bond["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT)
    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "FILED", (
        f"a shortfall bond should stay FILED, got {bond_after['status']}")


def test_appoint_with_current_version_succeeds(api):
    """PRD §2.5: "Every state-transition operation in the system carries a mandatory
    `expected_estate_version` field in its request body. This value must equal the
    current `version` of the governing `Estate`; if it does not, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412) before any state change is applied."

    The positive control for the OCC gate: carrying the CURRENT estate version
    (re-read after the bond approval) lets the appoint succeed.

    Design: Difficulty/optimistic_concurrency/appoint_stale_estate_version_rejected
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_250_000)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.approve_bond(bond["id"], {"expected_estate_version": v}, JUDGE))

    v_current = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    appointed = validate_success(api.appoint_representative(
        rep["id"], {"expected_estate_version": v_current}, JUDGE))
    assert appointed["status"] == "APPOINTED", (
        f"appoint with the current version should succeed, got {appointed['status']}")


def test_distribution_approve_with_current_version_succeeds(api):
    """PRD §2.5: "Every successful transition increments `Estate.version` by one".
    PRD §3.9: "A judge approves a proposed distribution, advancing it
    `PROPOSED → APPROVED`. Approval ... carries `expected_estate_version` matching
    the estate's `version`".

    The positive control: after the first approval bumps the version, re-reading
    the current version lets the second distribution approve succeed.

    Design: Difficulty/optimistic_concurrency/distribution_approve_stale_estate_version_rejected
    """
    est, rep, ben = setup_distributing_estate_with_cash(cash_cents=1_000_000)
    dist_a = propose_distribution(est["id"], ben["id"], 300_000)
    dist_b = propose_distribution(est["id"], ben["id"], 200_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.approve_distribution(dist_a["id"], {"expected_estate_version": v}, JUDGE))

    v_current = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    approved_b = validate_success(api.approve_distribution(
        dist_b["id"], {"expected_estate_version": v_current}, JUDGE))
    assert approved_b["status"] == "APPROVED", (
        f"second approve with the current version should succeed, got {approved_b['status']}")
