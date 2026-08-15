"""Disputes: negotiation cycle, offer supersession, OCC, terminal lockdown,
resolution gating, counterparty acceptance, RBAC on ratify, and SoD
(PRD sections 2.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    get_finding,
    get_licensee,
    make_counsel_headers,
    make_licensee_headers,
    setup_dispute_in_negotiation,
    setup_open_dispute,
    setup_ratification_pending,
    setup_settled_dispute,
    validate_error,
    validate_success,
)


def test_dispute_negotiation_counter_cycle(api, counsel_headers):
    """PRD section 3.8: "From `NEGOTIATION`, a licensee counter-offer moves
    the dispute to `COUNTERED` ... From `COUNTERED`, a counsel counter-offer
    moves the dispute back to `NEGOTIATION` ... In every case the previously
    pending offer becomes `SUPERSEDED`, the new offer is appended as
    `PENDING`, and the dispute's `version` increments."

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_counter_cycle
    """
    ctx = setup_open_dispute(patent_reference="US-50500-D1")
    dispute = ctx["dispute"]
    licensee = ctx["licensee"]
    assert ctx["finding"]["shortfall_cents"] == 9000
    assert dispute["version"] == 1

    # Counsel offer -> NEGOTIATION, version 2.
    resp = api.submit_offer(
        dispute["id"],
        {"amount_cents": 40_000, "expected_dispute_version": 1},
        counsel_headers,
    )
    d2 = validate_success(resp, expected_status=201)
    assert d2["status"] == "NEGOTIATION"
    assert d2["version"] == 2

    # Licensee counter-offer -> COUNTERED, version 3.
    resp = api.submit_offer(
        dispute["id"],
        {"amount_cents": 25_000, "expected_dispute_version": 2},
        make_licensee_headers(licensee["id"]),
    )
    d3 = validate_success(resp, expected_status=201)
    assert d3["status"] == "COUNTERED"
    assert d3["version"] == 3

    # Counsel counter-offer -> NEGOTIATION, version 4.
    resp = api.submit_offer(
        dispute["id"],
        {"amount_cents": 30_000, "expected_dispute_version": 3},
        counsel_headers,
    )
    d4 = validate_success(resp, expected_status=201)
    assert d4["status"] == "NEGOTIATION"
    assert d4["version"] == 4

    resp = api.get_dispute(dispute["id"], counsel_headers)
    final = validate_success(resp)
    offers = final["offers"]
    assert len(offers) == 3
    assert offers[0]["status"] == "SUPERSEDED"
    assert offers[1]["status"] == "SUPERSEDED"
    assert offers[2]["status"] == "PENDING"
    assert offers[2]["amount_cents"] == 30_000


def test_dispute_open_first_offer_by_licensee_moves_to_countered(api, counsel_headers):
    """PRD section 3.8: "From `OPEN`, an offer by `LegalCounsel` moves the
    dispute to `NEGOTIATION`; an offer by the owning `Licensee` moves it to
    `COUNTERED`."

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_counter_cycle
    """
    ctx = setup_open_dispute(patent_reference="US-50501-D2")
    dispute = ctx["dispute"]
    licensee = ctx["licensee"]

    resp = api.submit_offer(
        dispute["id"],
        {"amount_cents": 20_000, "expected_dispute_version": dispute["version"]},
        make_licensee_headers(licensee["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "COUNTERED"
    assert data["version"] == dispute["version"] + 1
    offers = data["offers"]
    assert len(offers) == 1
    assert offers[0]["status"] == "PENDING"
    assert offers[0]["offered_by_role"] == "Licensee"


def test_occ_stale_version_on_dispute_offer(api, counsel_headers):
    """PRD section 2.7: "Submitting a settlement offer on a dispute requires
    the request to carry `expected_dispute_version`, holding the dispute
    `version` the client last observed. If the dispute's current `version`
    has advanced — because a prior offer legitimately superseded the pending
    round — the offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_dispute_offer
    """
    ctx = setup_open_dispute(patent_reference="US-33342-W2")
    dispute = ctx["dispute"]
    v1 = dispute["version"]

    resp = api.submit_offer(
        dispute["id"],
        {"amount_cents": 40_000, "expected_dispute_version": v1},
        counsel_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["version"] == v1 + 1

    # Replay the stale version.
    resp2 = api.submit_offer(
        dispute["id"],
        {"amount_cents": 41_000, "expected_dispute_version": v1},
        counsel_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)


def test_terminal_dispute_lockdown(api, counsel_headers):
    """PRD section 3.8: "Both `SETTLED` and `ARBITRATED` are terminal." and
    "An offer attempted from any other dispute status is rejected with
    `ERR_DISPUTE_INVALID_STATE` (HTTP 409)." — the same state-gate applies to
    arbitrate, which is only legal "From `NEGOTIATION` or `COUNTERED`".

    Design: Corner/state_machines/terminal_dispute_lockdown
    """
    ctx = setup_settled_dispute(patent_reference="US-45454-W1")
    dispute = ctx["dispute"]
    assert dispute["status"] == "SETTLED"

    resp = api.arbitrate_dispute(
        dispute["id"], {"awarded_amount_cents": 50_000}, counsel_headers
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_INVALID_STATE)


def test_resolution_on_disputed_finding(api):
    """PRD section 3.7: "a finding in any status other than `OPEN` rejects
    both resolution and dispute attempts with `ERR_FINDING_NOT_OPEN` (HTTP
    409)."

    Design: Corner/errors/resolution_on_disputed_finding
    """
    ctx = setup_open_dispute(patent_reference="US-56575-P2")
    finding = get_finding(ctx["finding"]["id"])
    assert finding["status"] == "DISPUTED"

    resp = api.resolve_finding(
        ctx["finding"]["id"], {"resolution": "ACCEPTED"},
        make_licensee_headers(ctx["licensee"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FINDING_NOT_OPEN)


def test_accept_own_offer_rejected(api, counsel_headers):
    """PRD section 3.8: "An acceptance attempted by the same role that made
    the pending offer is rejected with `ERR_CANNOT_ACCEPT_OWN_OFFER` (HTTP
    422)".

    Design: Corner/errors/accept_own_offer_rejected
    """
    ctx = setup_dispute_in_negotiation(
        offer_amount_cents=30_000, patent_reference="US-78797-R2"
    )
    # NEGOTIATION: the pending offer is counsel's; counsel cannot accept it.
    resp = api.accept_offer(ctx["dispute"]["id"], counsel_headers)
    validate_error(resp, ApiErrorId.ERR_CANNOT_ACCEPT_OWN_OFFER)


def test_analyst_cannot_ratify_settlement(api, analyst_headers):
    """PRD section 2.1: "A request whose role is well-formed but not
    permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." PRD section 3.8: "From `RATIFICATION_PENDING`, a
    `LegalCounsel` ratifies" — ratify is exclusive to LegalCounsel.

    Design: Corner/rbac/analyst_cannot_ratify_settlement
    """
    ctx = setup_ratification_pending(patent_reference="US-89808-S2")
    assert ctx["dispute"]["status"] == "RATIFICATION_PENDING"
    resp = api.ratify_dispute(ctx["dispute"]["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_sod_ratifier_is_audit_opener(api):
    """PRD section 3.8: "the ratifying counsel's identity must differ from
    the `opened_by_user_id` of the audit that produced the finding, and a
    conflict is rejected with `ERR_SOD_CONFLICT` (HTTP 409). Ratification
    stamps `ratified_by_user_id`, moves the dispute to `SETTLED`, resolves the
    underlying finding from `DISPUTED` to `RESOLVED`, and posts
    `settlement_amount_cents` to all three ledger positions: the licensee's
    `outstanding_balance_cents`, and the agreement's
    `cumulative_recognized_revenue_cents` and `undistributed_pool_cents`."

    Design: Corner/rbac/sod_ratifier_is_audit_opener
    """
    from test_helpers import make_analyst_headers
    # Audit opened by "ana-1" (the fixture default ANALYST header).
    ctx = setup_ratification_pending(
        offer_amount_cents=30_000, patent_reference="US-90919-T2"
    )
    dispute = ctx["dispute"]

    # A LegalCounsel whose identity equals the audit opener conflicts.
    resp = api.ratify_dispute(dispute["id"], make_counsel_headers("ana-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)

    # A different counsel ratifies successfully.
    resp2 = api.ratify_dispute(dispute["id"], make_counsel_headers("counsel-2"))
    settled = validate_success(resp2)
    assert settled["status"] == "SETTLED"
    assert settled["settlement_amount_cents"] == 30_000

    finding = get_finding(ctx["finding"]["id"])
    assert finding["status"] == "RESOLVED"

    licensee_after = get_licensee(ctx["licensee"]["id"])
    assert licensee_after["outstanding_balance_cents"] == 30_000


def test_settlement_posts_to_recognized_revenue_and_pool(api):
    """PRD section 3.8: "posts `settlement_amount_cents` to all three ledger
    positions: the licensee's `outstanding_balance_cents`, and the agreement's
    `cumulative_recognized_revenue_cents` and `undistributed_pool_cents`."

    Design: Corner/rbac/sod_ratifier_is_audit_opener
    """
    from test_helpers import get_agreement
    ctx = setup_settled_dispute(
        offer_amount_cents=30_000, patent_reference="US-90920-T3"
    )
    agreement_after = get_agreement(ctx["agreement"]["id"])
    assert agreement_after["cumulative_recognized_revenue_cents"] == 30_000
    assert agreement_after["undistributed_pool_cents"] == 30_000
    assert get_licensee(ctx["licensee"]["id"])["outstanding_balance_cents"] == 30_000
