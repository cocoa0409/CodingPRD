"""Representative lifecycle cycles/branches, ledger cascades, and cross-entity
state gates (Difficulty queue: non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_estate, create_petition, nominate_representative,
    create_estate_with_appointed_pr, create_independent_estate_with_appointed_pr,
    create_open_estate_with_nominated_pr,
    list_asset, appraise_asset, marshal_asset,
    advance_open_to_accounting, add_beneficiary, file_final_accounting,
    propose_distribution, approve_distribution,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


# --------------------------------------------------------------------------- #
# non_linear_state_machine
# --------------------------------------------------------------------------- #
def test_representative_suspend_reinstate_cycle(api):
    """PRD §3.4: "A judge may `suspend` an `APPOINTED` representative, advancing it
    `APPOINTED → SUSPENDED`, and later `reinstate` a suspended one, advancing it
    `SUSPENDED → APPOINTED`; each requires a matching `expected_estate_version`
    (`ERR_STALE_VERSION`) and bumps `Estate.version`."

    After the APPOINTED -> SUSPENDED -> APPOINTED loop the PR is back to APPOINTED.

    Design: Difficulty/non_linear_state_machine/representative_suspend_reinstate_cycle
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    suspended = validate_success(
        api.suspend_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert suspended["status"] == "SUSPENDED"

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    reinstated = validate_success(
        api.reinstate_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert reinstated["status"] == "APPOINTED", (
        f"PR should return to APPOINTED after suspend/reinstate, got {reinstated['status']}")


def test_distribution_approve_branches_pay_or_return(api):
    """PRD §3.9: "Paying an approved distribution advances it `APPROVED → PAID` and
    is the only distribution step that moves cash." PRD §3.9: "an approved
    distribution that could not be delivered may be returned, advancing it
    `APPROVED → RETURNED`; return carries `expected_estate_version`
    (`ERR_STALE_VERSION`), moves no cash, and increments `Estate.version`."

    Two APPROVED distributions from a 1,000,000 pool: paying 400000 debits the
    pool to 600000; returning 300000 moves no cash, so the pool stays at 600000.

    Design: Difficulty/non_linear_state_machine/distribution_approve_branches_pay_or_return
    """
    est, rep, ben = _distributing_estate_with_cash(api, 1_000_000)
    dist_pay = propose_distribution(est["id"], ben["id"], 400_000)
    dist_ret = propose_distribution(est["id"], ben["id"], 300_000)
    approve_distribution(est["id"], dist_pay["id"])
    approve_distribution(est["id"], dist_ret["id"])

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    paid = validate_success(api.pay_distribution(
        dist_pay["id"], {"receipt_reference": "RCPT-1", "expected_estate_version": v}, REP))
    assert paid["status"] == "PAID"

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    returned = validate_success(api.return_distribution(
        dist_ret["id"], {"expected_estate_version": v}, REP))
    assert returned["status"] == "RETURNED"

    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 600_000, (
        f"only the PAID branch should debit 400000, leaving 600000; got "
        f"{est_after['marshaled_cash_cents']}")


# --------------------------------------------------------------------------- #
# transitive_cascade
# --------------------------------------------------------------------------- #
def test_liquidate_cascade_marshaled_then_residue(api):
    """PRD §3.7: "on success the reported `liquidation_proceeds_cents` are added to
    the estate's `marshaled_cash_cents`, the residue is recomputed".
    PRD §2.7: "The estate's `residue_cents` — the amount available to distribute —
    is defined to equal `marshaled_cash_cents` at every point".

    Liquidating a MARSHALED SECURITY asset for 700000 raises marshaled_cash_cents
    from 0 to 700000 and residue_cents to 700000 (a depth-3 cascade).

    Design: Difficulty/transitive_cascade/liquidate_cascade_marshaled_then_residue
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    asset = list_asset(est["id"], "SECURITY", declared_value_cents=700_000,
                       description="Shares")
    appraise_asset(est["id"], asset["id"], 700_000)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    liq = validate_success(api.liquidate_asset(
        asset["id"], {"liquidation_proceeds_cents": 700_000, "expected_estate_version": v}, REP))
    assert liq["status"] == "LIQUIDATED"

    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 700_000, (
        f"liquidation proceeds should credit the ledger to 700000, got "
        f"{est_after['marshaled_cash_cents']}")
    assert est_after["residue_cents"] == 700_000, (
        f"residue should equal the pool 700000, got {est_after['residue_cents']}")


def test_remove_representative_forfeits_bond(api):
    """PRD §3.4: "Removal is available from either the `APPOINTED` or the
    `SUSPENDED` state, advancing the representative to `REMOVED`; in both cases, if
    the representative holds a `bond_id`, that bond is cascaded to `FORFEITED`".

    Removing an APPOINTED PR whose bond is APPROVED cascades the bond to FORFEITED.

    Design: Difficulty/transitive_cascade/remove_representative_forfeits_bond
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    removed = validate_success(
        api.remove_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert removed["status"] == "REMOVED"

    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "FORFEITED", (
        f"the backing bond should be FORFEITED on removal, got {bond_after['status']}")


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency
# --------------------------------------------------------------------------- #
def test_appoint_requires_petition_granted(api):
    """PRD §3.3: "The petition named by the representative's `petition_id` must be
    in `GRANTED` status — the petition state gates appointment — and if it is not,
    the request is rejected with `ERR_CROSS_ENTITY_STATE`."

    A NOMINATED PR referencing a still-PENDING petition cannot be appointed.

    Design: Difficulty/cross_entity_state_dependency/appoint_requires_petition_granted
    """
    est = create_estate(gross_estate_value_cents=300_000)      # INDEPENDENT, no bond
    pet = create_petition(est["id"])                            # PENDING (not granted)
    rep = nominate_representative(est["id"], pet["id"])

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.appoint_representative(rep["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)

    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "NOMINATED", (
        f"PR should remain NOMINATED after a rejected appoint, got {rep_after['status']}")


def test_discharge_requires_estate_closed(api):
    """PRD §3.4: "Because a representative may be discharged only after the estate's
    affairs are wound up, the estate must be in `CLOSED` status — the estate closure
    gates discharge — and an attempt before closure is rejected with
    `ERR_CROSS_ENTITY_STATE`."

    Discharging an APPOINTED PR on an OPEN (not CLOSED) estate is rejected.

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_estate_closed
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()   # estate OPEN

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.discharge_representative(rep["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)

    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "APPOINTED", (
        f"PR should remain APPOINTED after a rejected discharge, got {rep_after['status']}")


# --------------------------------------------------------------------------- #
# Second tests (≥2 per instance) — distinct facets of the same rule
# --------------------------------------------------------------------------- #
def test_representative_suspend_sets_suspended_state(api):
    """PRD §3.4: "A judge may `suspend` an `APPOINTED` representative, advancing it
    `APPOINTED → SUSPENDED`".

    The first leg of the cycle: an APPOINTED PR moves to SUSPENDED on suspend.

    Design: Difficulty/non_linear_state_machine/representative_suspend_reinstate_cycle
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    suspended = validate_success(
        api.suspend_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert suspended["status"] == "SUSPENDED", (
        f"suspend should move APPOINTED PR to SUSPENDED, got {suspended['status']}")


def test_distribution_return_leaves_pool_unchanged(api):
    """PRD §3.9: "an approved distribution that could not be delivered may be
    returned, advancing it `APPROVED → RETURNED`; return carries
    `expected_estate_version` (`ERR_STALE_VERSION`), moves no cash, and increments
    `Estate.version`."

    The RETURNED branch specifically moves no cash: returning a 300000 approved
    distribution leaves the 1,000,000 pool untouched.

    Design: Difficulty/non_linear_state_machine/distribution_approve_branches_pay_or_return
    """
    est, rep, ben = _distributing_estate_with_cash(api, 1_000_000)
    dist = propose_distribution(est["id"], ben["id"], 300_000)
    approve_distribution(est["id"], dist["id"])

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    returned = validate_success(
        api.return_distribution(dist["id"], {"expected_estate_version": v}, REP))
    assert returned["status"] == "RETURNED"
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 1_000_000, (
        f"RETURN must not debit the pool, got {est_after['marshaled_cash_cents']}")


def test_marshal_cash_cascade_credits_ledger_and_residue(api):
    """PRD §3.6: "if and only if the asset's `asset_class` is `CASH`, its
    `appraised_value_cents` is added to the estate's `marshaled_cash_cents`, the
    residue is recomputed".

    Marshaling an APPRAISED CASH asset (600000) credits the ledger and residue by
    600000 — the credit counterpart to the liquidate cascade.

    Design: Difficulty/transitive_cascade/liquidate_cascade_marshaled_then_residue
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    asset = list_asset(est["id"], "CASH", 600_000, "Cash")
    appraise_asset(est["id"], asset["id"], 600_000)
    advance_open_to_accounting(est["id"])
    marshaled = marshal_asset(est["id"], asset["id"])
    assert marshaled["status"] == "MARSHALED"
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 600_000, (
        f"marshaling CASH should credit the ledger to 600000, got "
        f"{est_after['marshaled_cash_cents']}")
    assert est_after["residue_cents"] == 600_000, (
        f"residue should equal the pool 600000, got {est_after['residue_cents']}")


def test_remove_suspended_representative_forfeits_bond(api):
    """PRD §3.4: "Removal is available from either the `APPOINTED` or the
    `SUSPENDED` state, advancing the representative to `REMOVED`; in both cases, if
    the representative holds a `bond_id`, that bond is cascaded to `FORFEITED`".

    The SUSPENDED -> REMOVED branch fires the same bond-forfeiture cascade.

    Design: Difficulty/transitive_cascade/remove_representative_forfeits_bond
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(
        api.suspend_representative(rep["id"], {"expected_estate_version": v}, JUDGE))

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    removed = validate_success(
        api.remove_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert removed["status"] == "REMOVED"
    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "FORFEITED", (
        f"bond should be FORFEITED on removal from SUSPENDED, got {bond_after['status']}")


def test_appoint_succeeds_once_petition_granted(api):
    """PRD §3.3: "The petition named by the representative's `petition_id` must be
    in `GRANTED` status — the petition state gates appointment". PRD §3.3: "On
    success, the representative's `letters_issued_at` is stamped from the logical
    clock ... and `Estate.version` increments. With letters issued, the
    representative may now marshal assets and adjudicate claims."

    The positive side of the gate: with the petition GRANTED (and no bond required
    on an INDEPENDENT estate), appoint advances the PR to APPOINTED.

    Design: Difficulty/cross_entity_state_dependency/appoint_requires_petition_granted
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "APPOINTED", (
        f"appoint should succeed once petition is GRANTED, got {rep_after['status']}")


def test_discharge_succeeds_once_estate_closed(api):
    """PRD §3.4: "Discharge is the honorable exit and is available only from
    `APPOINTED`, advancing the representative `APPOINTED → DISCHARGED`. Because a
    representative may be discharged only after the estate's affairs are wound up,
    the estate must be in `CLOSED` status — the estate closure gates discharge".

    The positive side of the gate: once the estate is CLOSED, discharge succeeds.

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_estate_closed
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    advance_open_to_accounting(est["id"])
    final = file_final_accounting(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.approve_accounting(final["id"], {"expected_estate_version": v}, JUDGE))
    est_closed = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_closed["status"] == "CLOSED"

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    discharged = validate_success(
        api.discharge_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert discharged["status"] == "DISCHARGED", (
        f"discharge should succeed once estate CLOSED, got {discharged['status']}")


# --------------------------------------------------------------------------- #
# helper local to this file (distributing estate with cash)
# --------------------------------------------------------------------------- #
def _distributing_estate_with_cash(api, cash_cents):
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    ben = add_beneficiary(est["id"], share_bps=10_000)
    asset = list_asset(est["id"], "CASH", cash_cents, "Cash")
    appraise_asset(est["id"], asset["id"], cash_cents)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    file_final_accounting(est["id"])   # -> DISTRIBUTING
    return est, rep, ben
