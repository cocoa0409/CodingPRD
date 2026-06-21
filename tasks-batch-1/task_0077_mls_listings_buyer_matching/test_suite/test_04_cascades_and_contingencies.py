"""Acceptance cascade, close cascade, contingency branches, and compensation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_listing,
    setup_accepted_offer,
    setup_pending_listing,
    submit_offer,
    accept_offer,
    close_listing,
    request_showing,
    current_listing_version,
    get_first_ledger,
    list_contingencies,
    contingency_by_kind,
    create_agent,
    create_buyer,
    make_listing_agent_headers,
    make_buyer_agent_headers,
)


def test_accept_offer_three_hop_cascade(api):
    """PRD §3.6: "The listing advances from `ACTIVE` to `UNDER_CONTRACT`: its
    `accepted_offer_id` is set to the accepted offer's `id`, every sibling offer on the
    listing still in `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED` is cascaded to
    `REJECTED`".
    PRD §3.6: "If `requested_contingencies` is empty, there is nothing to protect, so
    the listing immediately bubbles from `UNDER_CONTRACT` to `PENDING` in the same
    operation."

    Design: Difficulty/transitive_cascade/accept_offer_three_hop_cascade
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la = s["listing_agent"]["id"]
    off1 = submit_offer(s["listing"]["id"], s["buyer"]["id"], s["buyer_agent"]["id"],
                        initial_price_cents=49_000_000, requested_contingencies=[])
    ba2 = create_agent(s["brokerage"]["id"], full_name="Cara")
    buyer2 = create_buyer(ba2["id"], max_budget_cents=60_000_000)
    off2 = submit_offer(s["listing"]["id"], buyer2["id"], ba2["id"],
                        initial_price_cents=50_000_000, requested_contingencies=[])

    accepted = accept_offer(off1["id"], s["listing"]["id"], la)
    assert accepted["status"] == "ACCEPTED", accepted
    assert accepted["effective_price_cents"] == 49_000_000, accepted

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "PENDING", listing  # hop C
    sib = validate_success(api.get_offer(off2["id"], headers=la_h), 200)
    assert sib["status"] == "REJECTED", sib  # hop B cascade


def test_accept_with_contingencies_stops_at_under_contract_not_pending(api):
    """PRD §3.6: "A `Contingency` is then materialized in `PENDING` status for each kind
    named in the offer's `requested_contingencies`. If `requested_contingencies` is
    empty, there is nothing to protect, so the listing immediately bubbles from
    `UNDER_CONTRACT` to `PENDING` in the same operation."

    Design: Difficulty/transitive_cascade/accept_offer_three_hop_cascade
    """
    # With a contingency present the third hop (bubble to PENDING) does NOT fire — the
    # cascade stops at UNDER_CONTRACT, distinguishing the empty-contingency three-hop.
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=50_000_000,
                       requested_contingencies=["INSPECTION"])
    accepted = accept_offer(off["id"], s["listing"]["id"], la)
    assert accepted["status"] == "ACCEPTED", accepted

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "UNDER_CONTRACT", listing  # hop C suppressed
    assert listing["accepted_offer_id"] == off["id"], listing


def test_close_listing_two_hop_cascade(api):
    """PRD §3.8: "On a successful close, the listing moves from `PENDING` to `CLOSED`,
    its `final_sale_price_cents` is set to the accepted offer's `effective_price_cents`,
    every showing appointment on the listing's lockbox still in `REQUESTED` or
    `CONFIRMED` is cascaded to `CANCELLED`, the listing's `version` increments, and a
    `CommissionLedger` is created for the listing by running the commission split."

    Design: Difficulty/transitive_cascade/close_listing_two_hop_cascade
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    # A residual REQUESTED showing on the lockbox.
    showing = request_showing(s["lockbox"]["id"], ba, s["buyer"]["id"],
                              "2026-07-01T15:00:00Z", "2026-07-01T15:30:00Z")
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=50_000_000, requested_contingencies=[])
    accept_offer(off["id"], s["listing"]["id"], la)

    closed = close_listing(s["listing"]["id"], la)
    assert closed["status"] == "CLOSED", closed
    assert closed["final_sale_price_cents"] == 50_000_000, closed

    ledger = get_first_ledger(s["listing"]["id"], la)
    assert ledger["total_commission_cents"] == 3_000_000, ledger  # hop B

    la_h = make_listing_agent_headers(la)
    sh = validate_success(api.get_showing(showing["id"], headers=la_h), 200)
    assert sh["status"] == "CANCELLED", sh  # hop B'


def test_close_cascade_creates_exactly_one_ledger_and_bumps_version(api):
    """PRD §3.8: "a `CommissionLedger` is created for the listing by running the
    commission split."
    PRD §3.8: "Exactly one ledger exists per closed listing, retrievable through the
    listing's commission-ledger lookup."

    Design: Difficulty/transitive_cascade/close_listing_two_hop_cascade
    """
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    la_h = make_listing_agent_headers(la)
    pre_version = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)["version"]
    closed = close_listing(s["listing"]["id"], la)
    assert closed["status"] == "CLOSED", closed
    assert closed["version"] == pre_version + 1, closed

    rows = validate_success(api.get_commission_ledger(s["listing"]["id"], headers=la_h), 200)
    assert len(rows) == 1, rows
    assert rows[0]["sale_price_cents"] == 50_000_000, rows[0]


def test_failed_contingency_compensation_reverts_listing_and_withdraws_offer(api):
    """PRD §3.7: "A failure, by contrast, unwinds the deal: when any contingency on the
    accepted offer transitions to `FAILED`, the accepted offer is moved to `WITHDRAWN`,
    the listing reverts from `UNDER_CONTRACT` to `ACTIVE`, its `accepted_offer_id` is
    cleared to null, the offer's remaining `PENDING` contingencies are cascaded to
    `WAIVED`, the `offer_posture` is recomputed from whatever live offers remain, and
    the listing's `version` increments."

    Design: Difficulty/non_linear_state_machine/contingency_branch_satisfied_vs_failed_divergent_effects
    """
    s = setup_accepted_offer(
        initial_price_cents=50_000_000, requested_contingencies=["INSPECTION"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    ins = contingency_by_kind(s["contingencies"], "INSPECTION")

    fail = validate_success(
        api.fail_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)
    assert fail["status"] == "FAILED", fail

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "ACTIVE", listing
    assert listing["accepted_offer_id"] is None, listing
    offer = validate_success(api.get_offer(s["offer"]["id"], headers=la_h), 200)
    assert offer["status"] == "WITHDRAWN", offer


def test_satisfied_contingency_bubbles_listing_to_pending(api):
    """PRD §3.7: "Whenever a contingency leaves `PENDING` by being satisfied or waived,
    the system checks whether it was the last `PENDING` contingency on the offer; if so
    — meaning every contingency on the accepted offer is now in `WAIVED` or `SATISFIED`,
    with none `PENDING` and none `FAILED` — the listing bubbles from `UNDER_CONTRACT` to
    `PENDING`, incrementing its `version`."

    Design: Difficulty/non_linear_state_machine/contingency_branch_satisfied_vs_failed_divergent_effects
    """
    s = setup_accepted_offer(
        initial_price_cents=50_000_000, requested_contingencies=["INSPECTION"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    ins = contingency_by_kind(s["contingencies"], "INSPECTION")

    res = validate_success(
        api.resolve_contingency(ins["id"], {}, headers=make_buyer_agent_headers(ba)), 200)
    assert res["status"] == "SATISFIED", res

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "PENDING", listing


def test_failed_contingency_restores_live_offer_count_to_zero(api):
    """PRD §3.7: "when any contingency on the accepted offer transitions to `FAILED`,
    the accepted offer is moved to `WITHDRAWN`, the listing reverts from
    `UNDER_CONTRACT` to `ACTIVE`, its `accepted_offer_id` is cleared to null, the
    offer's remaining `PENDING` contingencies are cascaded to `WAIVED`, the
    `offer_posture` is recomputed from whatever live offers remain".
    PRD §3.5: "if there are no live offers the posture is `NONE`"

    Design: Difficulty/compensating_invariant/failed_contingency_restores_listing_live_offer_count
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    offA = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                        initial_price_cents=50_000_000,
                        requested_contingencies=["INSPECTION"])
    ba2 = create_agent(s["brokerage"]["id"], full_name="Cara")
    buyer2 = create_buyer(ba2["id"], max_budget_cents=60_000_000)
    submit_offer(s["listing"]["id"], buyer2["id"], ba2["id"],
                 initial_price_cents=49_000_000, requested_contingencies=[])

    accept_offer(offA["id"], s["listing"]["id"], la)
    conts = list_contingencies(offA["id"], ba)
    ins = contingency_by_kind(conts, "INSPECTION")
    validate_success(
        api.fail_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "ACTIVE", listing
    assert listing["offer_posture"] == "NONE", listing
    # offA withdrawn (not resurrected to OPEN); sibling stays REJECTED -> zero live.
    open_offers, _ = _live_offers(api, s["listing"]["id"], la_h)
    assert open_offers == 0, "expected zero live offers after compensation"


def test_failed_contingency_does_not_resurrect_rejected_sibling(api):
    """PRD §3.7: "when any contingency on the accepted offer transitions to `FAILED`,
    the accepted offer is moved to `WITHDRAWN`, the listing reverts from
    `UNDER_CONTRACT` to `ACTIVE`, its `accepted_offer_id` is cleared to null, the
    offer's remaining `PENDING` contingencies are cascaded to `WAIVED`, the
    `offer_posture` is recomputed from whatever live offers remain".

    Design: Difficulty/compensating_invariant/failed_contingency_restores_listing_live_offer_count
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    offA = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                        initial_price_cents=50_000_000,
                        requested_contingencies=["INSPECTION"])
    ba2 = create_agent(s["brokerage"]["id"], full_name="Cara")
    buyer2 = create_buyer(ba2["id"], max_budget_cents=60_000_000)
    offB = submit_offer(s["listing"]["id"], buyer2["id"], ba2["id"],
                        initial_price_cents=49_000_000, requested_contingencies=[])
    accept_offer(offA["id"], s["listing"]["id"], la)
    conts = list_contingencies(offA["id"], ba)
    ins = contingency_by_kind(conts, "INSPECTION")
    validate_success(
        api.fail_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)

    la_h = make_listing_agent_headers(la)
    a_after = validate_success(api.get_offer(offA["id"], headers=la_h), 200)
    b_after = validate_success(api.get_offer(offB["id"], headers=la_h), 200)
    # Accepted offer A became WITHDRAWN (not resurrected to OPEN); sibling B stays
    # REJECTED — neither is live, so the conserved live count stays at zero.
    assert a_after["status"] == "WITHDRAWN", a_after
    assert b_after["status"] == "REJECTED", b_after


def _live_offers(api, listing_id, headers):
    resp = api.list_listing_offers(listing_id, headers=headers, params={"status": "OPEN"})
    body = resp.json()
    data = body["data"]
    return len(data), data


def test_contingency_resolve_requires_listing_under_contract(api):
    """PRD §3.7: "All contingency work is performed by the offer's buyer agent (under
    `ERR_NOT_BUYER_AGENT`) and is permitted only while the parent listing is
    `UNDER_CONTRACT` (otherwise `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/contingency_resolve_requires_listing_under_contract
    """
    # Offer requests INSPECTION + APPRAISAL; INSPECTION fails -> listing reverts ACTIVE
    # and the APPRAISAL contingency is auto-WAIVED. Resolving it now is invalid state.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["INSPECTION", "APPRAISAL"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    ins = contingency_by_kind(s["contingencies"], "INSPECTION")
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    validate_success(
        api.fail_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)

    resp = api.resolve_contingency(
        appr["id"], {"appraised_value_cents": 50_000_000},
        headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_contingency_waive_requires_listing_under_contract(api):
    """PRD §3.7: "All contingency work is performed by the offer's buyer agent (under
    `ERR_NOT_BUYER_AGENT`) and is permitted only while the parent listing is
    `UNDER_CONTRACT` (otherwise `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/contingency_resolve_requires_listing_under_contract
    """
    # INSPECTION fails -> listing reverts to ACTIVE; the sibling APPRAISAL contingency
    # was auto-WAIVED. Attempting to waive it again while the listing is ACTIVE (not
    # UNDER_CONTRACT) is rejected with ERR_INVALID_STATE.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["INSPECTION", "APPRAISAL"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    ins = contingency_by_kind(s["contingencies"], "INSPECTION")
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    validate_success(
        api.fail_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)
    resp = api.waive_contingency(appr["id"], headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_accept_with_contingencies_materializes_them(api):
    """PRD §3.6: "A `Contingency` is then materialized in `PENDING` status for each kind
    named in the offer's `requested_contingencies`."
    PRD §3.6: "The listing advances from `ACTIVE` to `UNDER_CONTRACT`"

    Design: Corner/cross_cutting_complexity_layers/accept_with_contingencies_materializes_them
    """
    s = setup_active_listing(
        buyer_overrides={"max_budget_cents": 60_000_000,
                         "prequalified_amount_cents": 50_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=50_000_000,
                       requested_contingencies=["INSPECTION", "FINANCING"])
    accept_offer(off["id"], s["listing"]["id"], la)

    conts = list_contingencies(off["id"], ba)
    kinds = {c["kind"] for c in conts}
    assert kinds == {"INSPECTION", "FINANCING"}, conts
    assert all(c["status"] == "PENDING" for c in conts), conts

    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "UNDER_CONTRACT", listing


def test_accept_cascade_visible_in_same_request(api):
    """PRD §2.5: "When a child changes in a way that satisfies or violates a parent's
    state criteria, the server transitions the parent automatically — no separate client
    request is required on the parent."
    PRD §3.6: "If `requested_contingencies` is empty, there is nothing to protect, so the
    listing immediately bubbles from `UNDER_CONTRACT` to `PENDING` in the same operation."

    Design: Corner/consistency_model/accept_cascade_visible_in_same_request
    """
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    la_h = make_listing_agent_headers(la)
    listing = validate_success(api.get_listing(s["listing"]["id"], headers=la_h), 200)
    assert listing["status"] == "PENDING", listing
    assert listing["accepted_offer_id"] == s["offer"]["id"], listing
