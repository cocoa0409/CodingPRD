"""RBAC, ownership, optimistic concurrency control, and list endpoints."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_active_listing,
    setup_accepted_offer,
    setup_active_listing_with_open_offer,
    create_brokerage,
    create_agent,
    create_draft_listing,
    install_lockbox,
    submit_offer,
    accept_offer,
    contingency_by_kind,
    current_listing_version,
    make_listing_agent_headers,
    make_buyer_agent_headers,
    create_listing_payload,
    accept_payload,
    close_payload,
)


# --- RBAC / ownership ---

def test_buyer_agent_cannot_create_listing(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is
    not permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/buyer_agent_cannot_create_listing
    """
    brk = create_brokerage()
    ba = create_agent(brk["id"], full_name="Ben")
    resp = api.create_listing(
        create_listing_payload(ba["id"], list_price_cents=50_000_000),
        headers=make_buyer_agent_headers(ba["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_foreign_listing_agent_cannot_activate(api):
    """PRD §3.2: "Activation moves a listing from `DRAFT` to `ACTIVE`. It may be performed
    only by the listing's own listing agent — a mismatch yields `ERR_NOT_LISTING_AGENT`
    (HTTP 403)".

    Design: Corner/rbac/foreign_listing_agent_cannot_activate
    """
    brk = create_brokerage()
    a = create_agent(brk["id"], full_name="AgentA")
    b = create_agent(brk["id"], full_name="AgentB")
    listing = create_draft_listing(a["id"], list_price_cents=50_000_000)
    install_lockbox(listing["id"], a["id"])
    # Agent B (a different ListingAgent) attempts activation.
    resp = api.activate_listing(listing["id"], headers=make_listing_agent_headers(b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_LISTING_AGENT.value)


def test_foreign_buyer_agent_cannot_withdraw_offer(api):
    """PRD §3.6: "Withdrawal is the buyer's prerogative and is available from `OPEN`,
    `SELLER_COUNTERED`, or `BUYER_COUNTERED`: the offer's buyer agent (under
    `ERR_NOT_BUYER_AGENT`) moves the offer to `WITHDRAWN`".

    Design: Corner/rbac/foreign_buyer_agent_cannot_withdraw_offer
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    # A different buyer agent attempts to withdraw the offer.
    other = create_agent(s["brokerage"]["id"], full_name="Carl")
    resp = api.withdraw_offer(s["offer"]["id"],
                              headers=make_buyer_agent_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_BUYER_AGENT.value)


# --- Optimistic concurrency control ---

def test_listing_version_increments_on_activate(api):
    """PRD §2.4: "The `version` field is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource".
    PRD §3.2: "On activation the `offer_posture` is set to `NONE` and the listing's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_listing_write
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    listing = validate_success(
        api.create_listing(create_listing_payload(la["id"], list_price_cents=50_000_000),
                           headers=make_listing_agent_headers(la["id"])),
        201)
    assert listing["version"] == 1, listing
    install_lockbox(listing["id"], la["id"])
    activated = validate_success(
        api.activate_listing(listing["id"], headers=make_listing_agent_headers(la["id"])),
        200)
    assert activated["version"] == 2, activated


def test_stale_close_after_contingency_bubble_rejected(api):
    """PRD §2.6: "Because a contingency resolution that bubbles the listing to `PENDING`,
    or a contingency failure that reverts it to `ACTIVE`, advances the listing's
    `version` between the agent's read and the close, a close carrying a now-superseded
    version is correctly rejected as stale."

    Design: Corner/cross_cutting_complexity_layers/stale_close_after_contingency_bubble_rejected
    """
    s = setup_accepted_offer(
        initial_price_cents=50_000_000, requested_contingencies=["INSPECTION"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    observed = current_listing_version(s["listing"]["id"], la)
    ins = contingency_by_kind(s["contingencies"], "INSPECTION")
    # Waive bubbles the listing to PENDING and bumps its version past `observed`.
    validate_success(api.waive_contingency(ins["id"], headers=make_buyer_agent_headers(ba)), 200)
    resp = api.close_listing(s["listing"]["id"], close_payload(observed),
                             headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --- Endpoints / pagination ---

def test_list_offers_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of matching records across the whole collection and `has_more` indicates
    whether records remain beyond the current page."
    PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The
    `offset` parameter is the number of items to skip from the front of the result set
    and defaults to 0."

    Design: Corner/endpoints/list_offers_paginated_envelope
    """
    s = setup_active_listing_with_open_offer(initial_price_cents=49_000_000)
    la = s["listing_agent"]["id"]
    resp = api.list_listing_offers(s["listing"]["id"],
                                   headers=make_listing_agent_headers(la))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
    assert meta["limit"] == 10, meta
    assert meta["offset"] == 0, meta
