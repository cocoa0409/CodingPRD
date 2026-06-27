"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"setup failed" errors rather than confusing assertion failures.

Identity threading: a Vendor is entity-backed on VendorRegistration. Every ownership-gated
vendor call (creating/scoring/submitting that vendor's proposals, its invoices, its protests)
uses make_vendor_headers(vendor_id) with the real registration id — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_vendor_payload,
    create_solicitation_payload,
    create_factor_payload,
    create_proposal_payload,
    create_score_payload,
    create_award_payload,
    create_contract_payload,
    create_clin_payload,
    create_ffp_invoice_payload,
    create_modification_payload,
)
from .test_users import TEST_USERS, make_co_headers, make_vendor_headers

CO = TEST_USERS["co_headers"]

# Default operator ids used to keep the segregation-of-duties chair/award distinction
# satisfied (PRD §3.4: the award maker must not equal the evaluation chair).
DEFAULT_CHAIR_ID = "co_chair"
DEFAULT_AWARD_ID = "co_award"


# ─── Logical clock ─────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, CO))


# ─── Tier 1: Vendor state progression ──────────────────────────────
def create_draft_vendor(uei: str, **overrides):
    """Create a DRAFT vendor registration. Returns the vendor dict."""
    payload = create_vendor_payload(uei=uei, **overrides)
    return get_success_data(api_client.create_vendor(payload, TEST_USERS["vendor_headers"]))


def create_active_vendor(uei: str, **overrides):
    """Create + activate a vendor (DRAFT -> ACTIVE). Returns the activated vendor dict.

    Activation is ownership-gated, so it is called with the vendor's own id.
    Assumes the clock has been set to before registration_expires_at by the caller.
    """
    vendor = create_draft_vendor(uei, **overrides)
    vh = make_vendor_headers(vendor["id"])
    activated = get_success_data(api_client.activate_vendor(vendor["id"], vh))
    return activated


# ─── Tier 2: Solicitation state progression ────────────────────────
def create_draft_solicitation_with_factors(factors=None, **sol_overrides):
    """Create a DRAFT solicitation and attach evaluation factors.

    `factors` is a list of (name, kind, weight) tuples. Defaults to a single
    TECHNICAL(1.0) plus the mandatory PRICE(0.0) factor — a valid weight set.
    Returns (solicitation_dict, {factor_label_or_kind: factor_dict}).
    """
    if factors is None:
        factors = [("Technical", "TECHNICAL", 1.0), ("Price", "PRICE", 0.0)]
    sol = get_success_data(
        api_client.create_solicitation(create_solicitation_payload(**sol_overrides), CO)
    )
    factor_map = {}
    for name, kind, weight in factors:
        fs = get_success_data(
            api_client.add_factor(sol["id"], create_factor_payload(name, kind, weight), CO)
        )
        factor_map[kind] = fs
    return sol, factor_map


def open_solicitation(sol_id: str):
    """Open a solicitation (requires clock >= open_at and valid factor weights)."""
    return get_success_data(api_client.open_solicitation(sol_id, CO))


# ─── Tier 3: Proposal lifecycle ────────────────────────────────────
def create_scored_draft_proposal(sol_id, vendor_id, total_price_cents, scores):
    """Create a DRAFT proposal and attach one FactorScore per (factor_id, raw_score).

    `scores` is a list of (factor_id, raw_score) tuples. Vendor-owned, so uses the
    vendor's own headers. Returns the proposal dict.
    """
    vh = make_vendor_headers(vendor_id)
    prop = get_success_data(
        api_client.create_proposal(
            create_proposal_payload(sol_id, vendor_id, total_price_cents), vh
        )
    )
    for factor_id, raw in scores:
        get_success_data(
            api_client.add_score(prop["id"], create_score_payload(factor_id, raw), vh)
        )
    return prop


def submit_proposal(proposal_id, vendor_id):
    """Submit a DRAFT proposal (vendor-owned)."""
    vh = make_vendor_headers(vendor_id)
    return get_success_data(api_client.submit_proposal(proposal_id, vh))


def evaluate_proposal(proposal_id):
    """Drive a SUBMITTED proposal through begin-evaluation + score (CO)."""
    get_success_data(api_client.begin_evaluation(proposal_id, CO))
    return get_success_data(api_client.score_proposal(proposal_id, CO))


# ─── Tier 4: Full procurement to EVALUATED / AWARDED / CONTRACT ─────
def setup_evaluated_single_proposal(
    *,
    open_at="2026-02-01T00:00:00Z",
    close_at="2026-02-05T00:00:00Z",
    set_aside_type=None,
    naics_size_threshold=500,
    vendor_uei="SETU00000001",
    employee_count=5,
    total_price_cents=50000000,
    tech_score=90,
    chair_id=DEFAULT_CHAIR_ID,
):
    """Drive one vendor's single proposal all the way to an EVALUATED solicitation
    with one ACCEPTABLE proposal. Records `chair_id` as the evaluation chair.

    Returns a dict with: sol, vendor, proposal, factors, sol_version (post-finalize).
    """
    set_clock(open_at)
    vendor = create_active_vendor(vendor_uei, employee_count=employee_count)

    sol_overrides = dict(open_at=open_at, close_at=close_at,
                         naics_size_threshold=naics_size_threshold)
    if set_aside_type is not None:
        sol_overrides["set_aside_type"] = set_aside_type
    sol, factors = create_draft_solicitation_with_factors(**sol_overrides)
    open_solicitation(sol["id"])

    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], total_price_cents,
        [(factors["TECHNICAL"]["id"], tech_score), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])

    set_clock(close_at)
    get_success_data(api_client.close_solicitation(sol["id"], CO))
    evaluate_proposal(prop["id"])

    finalized = get_success_data(
        api_client.finalize_evaluation(sol["id"], make_co_headers(chair_id))
    )
    return {
        "sol": sol,
        "vendor": vendor,
        "proposal": prop,
        "factors": factors,
        "sol_version": finalized["version"],
    }


def setup_award(award_user_id=DEFAULT_AWARD_ID, **kwargs):
    """setup_evaluated_single_proposal + make the award.

    Returns the setup dict augmented with `award`. The award maker id defaults to a
    distinct operator from the chair so segregation-of-duties passes (PRD §3.4).
    """
    ctx = setup_evaluated_single_proposal(**kwargs)
    award = get_success_data(
        api_client.create_award(
            create_award_payload(ctx["sol"]["id"], ctx["proposal"]["id"], ctx["sol_version"]),
            make_co_headers(award_user_id),
        )
    )
    ctx["award"] = award
    return ctx


def setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                              clin_unit_price=50000, clin_funded_qty=100, **kwargs):
    """setup_award + create an ACTIVE FFP contract, optionally with one CLIN 0001.

    Returns the setup dict augmented with `contract` and (if with_clin) `clin`.
    """
    ctx = setup_award(**kwargs)
    contract = get_success_data(
        api_client.create_contract(
            create_contract_payload(ctx["award"]["id"], "FFP", base_value_cents), CO
        )
    )
    ctx["contract"] = contract
    if with_clin:
        clin = get_success_data(
            api_client.add_clin(
                contract["id"],
                create_clin_payload("0001", clin_unit_price, clin_funded_qty),
                CO,
            )
        )
        ctx["clin"] = clin
    return ctx


def setup_active_cpff_contract(base_value_cents, total_estimated_cost_cents,
                               fixed_fee_cents, **kwargs):
    """setup_award + create an ACTIVE CPFF contract with TEC and fixed fee.

    Returns the setup dict augmented with `contract`.
    """
    ctx = setup_award(**kwargs)
    contract = get_success_data(
        api_client.create_contract(
            create_contract_payload(
                ctx["award"]["id"], "CPFF", base_value_cents,
                total_estimated_cost_cents=total_estimated_cost_cents,
                fixed_fee_cents=fixed_fee_cents,
            ),
            CO,
        )
    )
    ctx["contract"] = contract
    return ctx


def fresh_contract_version(contract_id):
    """Re-read a contract and return its current version (for OCC expected_contract_version)."""
    return get_success_data(api_client.get_contract(contract_id, CO))["version"]


# ─── Tier 5: Two-proposal procurements (cascade / protest scenarios) ─
def setup_evaluated_two_proposals(
    *,
    open_at="2026-02-01T00:00:00Z",
    close_at="2026-02-05T00:00:00Z",
    winner_uei="WINN00000001",
    loser_uei="LOSE00000001",
    winner_price=50000000,
    loser_price=60000000,
    winner_tech=95,
    loser_tech=80,
    chair_id=DEFAULT_CHAIR_ID,
):
    """Two ACTIVE vendors each submit one ACCEPTABLE proposal; solicitation EVALUATED.

    Returns dict with: sol, winner_vendor, loser_vendor, winner_proposal,
    loser_proposal, factors, sol_version.
    """
    set_clock(open_at)
    winner = create_active_vendor(winner_uei, employee_count=40)
    loser = create_active_vendor(loser_uei, employee_count=40)

    sol, factors = create_draft_solicitation_with_factors(open_at=open_at, close_at=close_at)
    open_solicitation(sol["id"])

    pw = create_scored_draft_proposal(
        sol["id"], winner["id"], winner_price,
        [(factors["TECHNICAL"]["id"], winner_tech), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(pw["id"], winner["id"])
    pl = create_scored_draft_proposal(
        sol["id"], loser["id"], loser_price,
        [(factors["TECHNICAL"]["id"], loser_tech), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(pl["id"], loser["id"])

    set_clock(close_at)
    get_success_data(api_client.close_solicitation(sol["id"], CO))
    evaluate_proposal(pw["id"])
    evaluate_proposal(pl["id"])

    finalized = get_success_data(
        api_client.finalize_evaluation(sol["id"], make_co_headers(chair_id))
    )
    return {
        "sol": sol,
        "winner_vendor": winner,
        "loser_vendor": loser,
        "winner_proposal": pw,
        "loser_proposal": pl,
        "factors": factors,
        "sol_version": finalized["version"],
    }


def setup_protested_award_under_review(
    *, with_contract=True, award_user_id=DEFAULT_AWARD_ID, **kwargs
):
    """Two-proposal procurement -> award winner -> (optional FFP contract) ->
    loser files a protest -> CO begins review (Award PROTESTED, protest UNDER_REVIEW).

    Returns dict with: sol, winner_vendor, loser_vendor, winner_proposal,
    loser_proposal, award, protest, and (if with_contract) contract.
    """
    ctx = setup_evaluated_two_proposals(**kwargs)
    award = get_success_data(
        api_client.create_award(
            create_award_payload(ctx["sol"]["id"], ctx["winner_proposal"]["id"],
                                 ctx["sol_version"]),
            make_co_headers(award_user_id),
        )
    )
    ctx["award"] = award
    if with_contract:
        contract = get_success_data(
            api_client.create_contract(
                create_contract_payload(award["id"], "FFP", ctx["winner_proposal"]["total_price_cents"]),
                CO,
            )
        )
        ctx["contract"] = contract
    loser_id = ctx["loser_vendor"]["id"]
    from .factories import create_protest_payload
    protest = get_success_data(
        api_client.create_protest(
            create_protest_payload(award["id"], loser_id, "improper evaluation"),
            make_vendor_headers(loser_id),
        )
    )
    ctx["protest"] = protest
    get_success_data(api_client.begin_review(protest["id"], CO))
    return ctx
