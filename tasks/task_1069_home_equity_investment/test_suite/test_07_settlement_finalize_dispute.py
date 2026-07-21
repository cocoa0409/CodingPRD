"""Settlement finalization cascade, the dispute/re-proposal cycle, the
segregation-of-duties barrier, optimistic concurrency, and validation ordering.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_homeowner_headers, make_compliance_headers,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _finalize_ready(api):
    """Active agreement with a recorded lien and a SCHEDULED inspection, exited,
    clock at 2028, and a PROPOSED SALE settlement with non-negative proceeds."""
    ctx = fixtures.setup_active_agreement(api)
    inspector = fixtures.create_inspector(api)
    inspection = fixtures.schedule_inspection(api, ctx["agreement"]["id"], inspector["id"])
    fixtures.initiate_exit(api, ctx["agreement"]["id"], ctx["homeowner"]["id"])
    fixtures.set_clock(api, "2028-07-01T00:00:00Z")
    version = fixtures.agreement_version(api, ctx["agreement"]["id"])
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, version
    )
    ctx["inspection"] = inspection
    ctx["settlement"] = settlement
    return ctx


# --------------------------------------------------------------------------
# transitive_cascade: settlement finalize depth-3
# --------------------------------------------------------------------------
def test_finalize_settles_agreement_and_releases_lien(api):
    """PRD §3.7: "Finalization drives a depth-three cascade: the settlement
    becomes FINALIZED; the agreement moves from SETTLEMENT_PROPOSED to the
    terminal SETTLED; the agreement's lien moves from RECORDED to RELEASED; and
    every inspection of that agreement still in SCHEDULED is moved to
    CANCELLED."

    Design: Difficulty/transitive_cascade/settlement_finalize_depth3
    """
    ctx = _finalize_ready(api)
    finalized = validate_success(api.finalize_settlement(ctx["settlement"]["id"], COMPLIANCE))
    assert finalized["status"] == "FINALIZED"
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], COMPLIANCE))
    assert agreement["status"] == "SETTLED"
    lien = validate_success(api.get_lien(ctx["lien"]["id"], COMPLIANCE))
    assert lien["status"] == "RELEASED"


def test_finalize_cancels_scheduled_inspections(api):
    """PRD §3.7: "Finalization drives a depth-three cascade: the settlement
    becomes FINALIZED; the agreement moves from SETTLEMENT_PROPOSED to the
    terminal SETTLED; the agreement's lien moves from RECORDED to RELEASED; and
    every inspection of that agreement still in SCHEDULED is moved to
    CANCELLED."

    Design: Difficulty/transitive_cascade/settlement_finalize_depth3
    """
    ctx = _finalize_ready(api)
    get_success_data(api.finalize_settlement(ctx["settlement"]["id"], COMPLIANCE))
    inspection = validate_success(api.get_inspection(ctx["inspection"]["id"], COMPLIANCE))
    assert inspection["status"] == "CANCELLED"


# --------------------------------------------------------------------------
# non_linear_state_machine: dispute -> resolve re-proposal cycle
# --------------------------------------------------------------------------
def test_dispute_moves_agreement_to_disputed(api):
    """PRD §3.8: "Disputing moves the settlement from `PROPOSED` to `DISPUTED`
    and the parent agreement from `SETTLEMENT_PROPOSED` to `DISPUTED`, and it
    opens a `Dispute` record."

    Design: Difficulty/non_linear_state_machine/agreement_dispute_reproposal_cycle
    """
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=120000000, mortgage_payoff_cents=40000000, officer_user_id="co-1"
    )
    fixtures.dispute_settlement(api, ctx["settlement"]["id"], ctx["homeowner"]["id"])
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], COMPLIANCE))
    assert agreement["status"] == "DISPUTED"


def test_resolve_dispute_returns_agreement_to_settlement_proposed(api):
    """PRD §3.8: "Resolving the dispute records an adjusted resolved_value_cents
    and the acting officer in resolved_by_user_id, voids the disputed
    settlement, and moves the agreement from DISPUTED back to
    SETTLEMENT_PROPOSED by creating a fresh replacement settlement whose ending
    value is taken from that resolved_value_cents".

    Design: Difficulty/non_linear_state_machine/agreement_dispute_reproposal_cycle
    """
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=120000000, mortgage_payoff_cents=40000000, officer_user_id="co-1"
    )
    dispute = fixtures.dispute_settlement(api, ctx["settlement"]["id"], ctx["homeowner"]["id"])
    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"resolved_value_cents": 125000000}, make_compliance_headers("co-2")
    ))
    assert resolved["status"] == "RESOLVED"
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], COMPLIANCE))
    assert agreement["status"] == "SETTLEMENT_PROPOSED"


# --------------------------------------------------------------------------
# priority_pair: state check (prio 6) beats fiscal (prio 12) on finalize
# --------------------------------------------------------------------------
def _disputed_negative_settlement(api):
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=41000000, mortgage_payoff_cents=41000000, officer_user_id="co-1"
    )
    fixtures.dispute_settlement(api, ctx["settlement"]["id"], ctx["homeowner"]["id"],
                                reason="undervalued", disputed_value_cents=90000000)
    return ctx


def test_finalize_disputed_settlement_is_invalid_state(api):
    """PRD §3.7: "Finalization is only defined while the settlement is PROPOSED
    and its parent agreement is SETTLEMENT_PROPOSED, and it is refused with
    ERR_PROCEEDS_INSUFFICIENT if net_proceeds_cents is negative."

    Design: Difficulty/priority_pair_validation_conflict/finalize_state_beats_fiscal
    """
    ctx = _disputed_negative_settlement(api)
    validate_error(api.finalize_settlement(ctx["settlement"]["id"], COMPLIANCE), "ERR_INVALID_STATE", 409)


def test_finalize_state_error_preempts_fiscal_error(api):
    """PRD §2.8: "(6) whether the target resource is in a state from which the
    requested transition is defined, yielding ERR_INVALID_STATE; ... and last
    (12) the fiscal gates such as loan-to-value ceilings, investment caps, fund
    sufficiency, and non-negative proceeds."

    Design: Difficulty/priority_pair_validation_conflict/finalize_state_beats_fiscal
    """
    ctx = _disputed_negative_settlement(api)
    error = api.finalize_settlement(ctx["settlement"]["id"], COMPLIANCE).json()["data"]["error_id"]
    assert error == "ERR_INVALID_STATE"
    assert error != "ERR_PROCEEDS_INSUFFICIENT"


# --------------------------------------------------------------------------
# Queue-B corner instances
# --------------------------------------------------------------------------
def test_reproposal_with_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the agreement's current version,
    the request is rejected with ERR_STALE_AGREEMENT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/settlement_propose_stale_agreement_version_returns_412
    """
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=120000000, mortgage_payoff_cents=40000000
    )
    # ctx["agreement_version"] is the pre-proposal version; the first proposal
    # already advanced it, so re-using it is now stale.
    resp = api.create_settlement(
        ctx["agreement"]["id"],
        {"settlement_type": "BUYOUT", "current_appraised_value_cents": 120000000,
         "mortgage_payoff_cents": 40000000, "expected_agreement_version": ctx["agreement_version"]},
        COMPLIANCE,
    )
    validate_error(resp, "ERR_STALE_AGREEMENT_VERSION", 412)


def test_dispute_resolved_by_proposing_officer_forbidden(api):
    """PRD §2.8: "When a dispute is resolved or rejected, the acting X-User-ID is
    compared against that stored proposed_by_user_id; if they are equal the
    action is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/cross_cutting/dispute_resolve_same_officer_segregation_of_duties
    """
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=120000000, mortgage_payoff_cents=40000000, officer_user_id="co-1"
    )
    dispute = fixtures.dispute_settlement(api, ctx["settlement"]["id"], ctx["homeowner"]["id"])
    resp = api.resolve_dispute(
        dispute["id"], {"resolved_value_cents": 125000000}, make_compliance_headers("co-1")
    )
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_finalize_negative_proceeds_rejected(api):
    """PRD §3.7: "it is refused with `ERR_PROCEEDS_INSUFFICIENT` if
    `net_proceeds_cents` is negative."

    Design: Corner/cross_cutting/finalize_negative_proceeds_returns_insufficient
    """
    ctx = fixtures.setup_proposed_sale_settlement(
        api, sale_price_cents=41000000, mortgage_payoff_cents=41000000
    )
    validate_error(api.finalize_settlement(ctx["settlement"]["id"], COMPLIANCE),
                   "ERR_PROCEEDS_INSUFFICIENT", 422)
