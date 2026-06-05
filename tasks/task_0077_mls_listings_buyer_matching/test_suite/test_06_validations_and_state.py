"""Entity creation, state-machine preconditions, validations, and priority conflicts."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    setup_active_listing,
    setup_pending_listing,
    setup_participants,
    create_brokerage,
    create_agent,
    create_draft_listing,
    install_lockbox,
    activate_listing,
    submit_offer,
    accept_offer,
    close_listing,
    current_listing_version,
    suspend_agent,
    create_buyer,
    make_listing_agent_headers,
    make_buyer_agent_headers,
    anon_headers,
    create_listing_payload,
    create_offer_payload,
    create_buyer_payload,
    create_agent_payload,
    counter_payload,
)


# --- Priority conflicts (Difficulty rule 5) ---

def test_dual_agency_safety_beats_over_budget(api):
    """PRD §3.5: "an offer whose `buyer_agent_id` equals the target listing's
    `listing_agent_id` is rejected with `ERR_DUAL_AGENCY_FORBIDDEN` (HTTP 422), because
    no agent may represent both sides of one property."

    Design: Difficulty/priority_pair_validation_conflict/dual_agency_safety_beats_budget_constraint
    """
    brk = create_brokerage()
    dual = create_agent(brk["id"], full_name="Dual")
    # Buyer represented by the same agent, budget below the offer price.
    buyer = create_buyer(dual["id"], max_budget_cents=40_000_000)
    listing = create_draft_listing(dual["id"], list_price_cents=50_000_000)
    install_lockbox(listing["id"], dual["id"])
    activate_listing(listing["id"], dual["id"])

    # Offer price 50000000 > budget 40000000 (over-budget) AND buyer agent == listing
    # agent (dual agency). Dual agency (priority 5) must win over over-budget (priority 9).
    resp = api.create_offer(
        listing["id"],
        create_offer_payload(buyer["id"], dual["id"], initial_price_cents=50_000_000),
        headers=make_buyer_agent_headers(dual["id"]))
    validate_error(resp, ApiErrorId.ERR_DUAL_AGENCY_FORBIDDEN.value)


def test_dual_agency_beats_budget_at_larger_overage(api):
    """PRD §3.5: "an offer whose `buyer_agent_id` equals the target listing's
    `listing_agent_id` is rejected with `ERR_DUAL_AGENCY_FORBIDDEN` (HTTP 422), because
    no agent may represent both sides of one property."

    Design: Difficulty/priority_pair_validation_conflict/dual_agency_safety_beats_budget_constraint
    """
    brk = create_brokerage()
    dual = create_agent(brk["id"], full_name="Dual")
    buyer = create_buyer(dual["id"], max_budget_cents=10_000_000)  # far below price
    listing = create_draft_listing(dual["id"], list_price_cents=50_000_000)
    install_lockbox(listing["id"], dual["id"])
    activate_listing(listing["id"], dual["id"])
    # Price 50000000 dwarfs budget 10000000 AND dual agency — still dual agency wins.
    resp = api.create_offer(
        listing["id"],
        create_offer_payload(buyer["id"], dual["id"], initial_price_cents=50_000_000),
        headers=make_buyer_agent_headers(dual["id"]))
    validate_error(resp, ApiErrorId.ERR_DUAL_AGENCY_FORBIDDEN.value)


def test_invalid_state_beats_not_your_turn_on_terminal_offer(api):
    """PRD §3.6: "A counter is permitted only while the parent listing is `ACTIVE`
    (otherwise `ERR_INVALID_STATE`, HTTP 409) and only when the issuing side matches
    whose turn it is (otherwise `ERR_NOT_YOUR_TURN`)".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_turn_on_terminal_offer
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=49_000_000)
    # Reject the offer (terminal). current_party stays SELLER, so a buyer counter is
    # both wrong-turn and invalid-state; ERR_INVALID_STATE must win.
    validate_success(api.reject_offer(off["id"], headers=make_listing_agent_headers(la)), 200)
    resp = api.counter_offer(off["id"], counter_payload(48_000_000, ba),
                             headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_beats_not_your_turn_on_withdrawn_offer(api):
    """PRD §3.6: "A counter is permitted only while the parent listing is `ACTIVE`
    (otherwise `ERR_INVALID_STATE`, HTTP 409) and only when the issuing side matches
    whose turn it is (otherwise `ERR_NOT_YOUR_TURN`)".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_turn_on_terminal_offer
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=49_000_000)
    # Buyer withdraws (terminal WITHDRAWN). current_party is still SELLER, so a buyer
    # counter is both wrong-turn and invalid-state; ERR_INVALID_STATE must win.
    validate_success(api.withdraw_offer(off["id"], headers=make_buyer_agent_headers(ba)), 200)
    resp = api.counter_offer(off["id"], counter_payload(48_000_000, ba),
                             headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Address uniqueness (Difficulty rule 8) ---

def test_address_uniqueness_among_non_terminal_listings(api):
    """PRD §3.2: "The `address` must be unique among all listings whose status is not
    `WITHDRAWN` and not `CLOSED`; a colliding address on a still-live listing is rejected
    with `ERR_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/address_uniqueness_among_non_terminal_listings
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    create_draft_listing(la["id"], list_price_cents=50_000_000, address="20 Pine St")
    resp = api.create_listing(
        create_listing_payload(la["id"], list_price_cents=60_000_000, address="20 Pine St"),
        headers=make_listing_agent_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_address_reuse_blocked_second_attempt(api):
    """PRD §3.2: "The `address` must be unique among all listings whose status is not
    `WITHDRAWN` and not `CLOSED`; a colliding address on a still-live listing is rejected
    with `ERR_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/address_uniqueness_among_non_terminal_listings
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    create_draft_listing(la["id"], list_price_cents=50_000_000, address="21 Pine St")
    # A DRAFT listing is non-terminal, so the address is still occupied.
    resp = api.create_listing(
        create_listing_payload(la["id"], list_price_cents=55_000_000, address="21 Pine St"),
        headers=make_listing_agent_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


# --- Entities: creation, defaults, computed, not-found, duplicates ---

def test_create_listing_returns_201_with_brokerage_defaults(api):
    """PRD §2.8: "When a listing is created without an explicit `total_commission_pct`,
    it inherits the brokerage's `default_total_commission_pct`; when created without an
    explicit `coop_split_pct`, it inherits the brokerage's `default_coop_split_pct`."
    PRD §3.2: "A new listing begins in `DRAFT` status with an `offer_posture` of `NONE`."

    Design: Corner/entities/create_listing_returns_201_with_defaults_from_brokerage
    """
    brk = create_brokerage(total_pct=0.06, coop_pct=0.50)
    la = create_agent(brk["id"], full_name="Lara")
    resp = api.create_listing(
        create_listing_payload(la["id"], list_price_cents=50_000_000),
        headers=make_listing_agent_headers(la["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", data
    assert data["offer_posture"] == "NONE", data
    assert data["total_commission_pct"] == 0.06, data
    assert data["coop_split_pct"] == 0.50, data
    assert data["version"] == 1, data


def test_get_listing_not_found_returns_404(api, anonymous_headers):
    """PRD §2.5: "the server validates the path identifiers from left to right and
    rejects the first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_listing_not_found_returns_404
    """
    resp = api.get_listing(NON_EXISTENT_UUID, headers=anonymous_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_offer_missing_initial_price_rejected(api):
    """PRD §3.5: "the opening `initial_price_cents` (a positive integer), the
    `earnest_money_cents` deposit (a non-negative integer), and an optional
    `requested_contingencies` array — a subset of `INSPECTION`, `APPRAISAL`, and
    `FINANCING` that the buyer wishes to attach."

    Design: Corner/entities/create_offer_missing_required_field_rejected
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    resp = api.create_offer(
        s["listing"]["id"],
        {"buyer_id": s["buyer"]["id"], "buyer_agent_id": ba, "earnest_money_cents": 0},
        headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_buyer_defaults_prequalified_and_debt_zero(api):
    """PRD §3.1: "their `prequalified_amount_cents` (the lender's pre-qualification
    ceiling, a non-negative integer that defaults to 0 when omitted, where 0 signals
    "not prequalified")".
    PRD §3.1: "their `monthly_debt_cents` (existing monthly debt obligations, a
    non-negative integer defaulting to 0 when omitted)."

    Design: Corner/entities/buyer_default_prequalified_and_debt_zero
    """
    brk = create_brokerage()
    ba = create_agent(brk["id"], full_name="Ben")
    resp = api.create_buyer(
        create_buyer_payload(ba["id"]), headers=make_buyer_agent_headers(ba["id"]))
    data = validate_success(resp, 201)
    assert data["prequalified_amount_cents"] == 0, data
    assert data["monthly_debt_cents"] == 0, data


def test_offer_computed_fields_on_creation(api):
    """PRD §3.5: "A new offer begins in `OPEN` status with `current_party` of `SELLER`
    (a fresh buyer offer awaits the seller's response first) and a `round_count` of 0."
    PRD §3.6: "When an offer has no counter rounds at all, its `current_price_cents` is
    its `initial_price_cents`".

    Design: Corner/entities/offer_computed_fields_ignore_client_input
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    data = validate_success(
        api.create_offer(
            s["listing"]["id"],
            create_offer_payload(s["buyer"]["id"], ba, initial_price_cents=49_000_000),
            headers=make_buyer_agent_headers(ba)),
        201)
    assert data["current_price_cents"] == 49_000_000, data
    assert data["current_party"] == "SELLER", data
    assert data["round_count"] == 0, data
    assert data["status"] == "OPEN", data


def test_agent_license_duplicate_rejected(api, anonymous_headers):
    """PRD §3.1: "their `license_no` — the state real-estate license number, which must
    be globally unique across all agents. A registration whose `license_no` collides
    with an existing agent is rejected with `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/entities/agent_license_duplicate_rejected
    """
    brk = create_brokerage()
    create_agent(brk["id"], full_name="A", license_no="DUP-1")
    resp = api.create_agent(
        {"brokerage_id": brk["id"], "full_name": "B", "license_no": "DUP-1"},
        headers=anonymous_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_agent_parent_brokerage_must_exist(api, anonymous_headers):
    """PRD §2.5: "Foreign-key references supplied in a request body are validated after
    the path identifiers, also yielding `ERR_NOT_FOUND` when a referenced record does
    not exist."

    Design: Corner/entities/parent_brokerage_must_exist_for_agent
    """
    resp = api.create_agent(
        {"brokerage_id": NON_EXISTENT_UUID, "full_name": "X", "license_no": "NX-1"},
        headers=anonymous_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# --- State machines ---

def test_new_listing_starts_in_draft(api):
    """PRD §3.2: "A new listing begins in `DRAFT` status with an `offer_posture` of
    `NONE`."

    Design: Corner/state_machines/new_listing_starts_in_draft
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    data = validate_success(
        api.create_listing(create_listing_payload(la["id"], list_price_cents=50_000_000),
                           headers=make_listing_agent_headers(la["id"])),
        201)
    assert data["status"] == "DRAFT", data


def test_activate_without_lockbox_rejected(api):
    """PRD §3.2: "only when the listing already has at least one lockbox in `INSTALLED`
    status; activating a listing with no installed lockbox is rejected with
    `ERR_NO_LOCKBOX` (HTTP 409)."

    Design: Corner/state_machines/activate_without_lockbox_rejected
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    listing = create_draft_listing(la["id"], list_price_cents=50_000_000)
    resp = api.activate_listing(listing["id"], headers=make_listing_agent_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_LOCKBOX.value)


def test_counter_on_withdrawn_listing_offer_invalid_state(api):
    """PRD §3.6: "A counter is permitted only while the parent listing is `ACTIVE`
    (otherwise `ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.2: "From `ACTIVE`, withdrawing transitions the listing to `WITHDRAWN`, and as
    a cascade every offer on the listing currently in `OPEN`, `SELLER_COUNTERED`, or
    `BUYER_COUNTERED` is moved to `REJECTED`".

    Design: Corner/state_machines/counter_on_draft_listing_offer_invalid_state
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    la, ba = s["listing_agent"]["id"], s["buyer_agent"]["id"]
    off = submit_offer(s["listing"]["id"], s["buyer"]["id"], ba,
                       initial_price_cents=49_000_000)
    validate_success(api.withdraw_listing(s["listing"]["id"],
                     headers=make_listing_agent_headers(la)), 200)
    resp = api.counter_offer(off["id"], counter_payload(50_000_000, la),
                             headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_closed_listing_is_terminal(api):
    """PRD §3.2: "A listing's `status` ranges over `DRAFT`, `ACTIVE`, `UNDER_CONTRACT`,
    `PENDING`, `CLOSED`, and `WITHDRAWN`, with `CLOSED` and `WITHDRAWN` being terminal."

    Design: Corner/state_machines/closed_listing_is_terminal
    """
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    close_listing(s["listing"]["id"], la)
    resp = api.withdraw_listing(s["listing"]["id"], headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_second_accept_after_under_contract_invalid_state(api):
    """PRD §3.5: "`ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED` are terminal."
    PRD §3.6: "the listing must be `ACTIVE` (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/second_accept_after_under_contract_invalid_state
    """
    s = setup_pending_listing(sale_price_cents=50_000_000)
    la = s["listing_agent"]["id"]
    v = current_listing_version(s["listing"]["id"], la)
    from test_helpers import accept_payload
    resp = api.accept_offer(s["offer"]["id"], accept_payload(v),
                            headers=make_listing_agent_headers(la))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Validations ---

def test_over_budget_offer_rejected(api):
    """PRD §3.5: "if `initial_price_cents` exceeds the buyer's `max_budget_cents`, the
    offer is rejected with `ERR_OVER_BUDGET` (HTTP 422)."

    Design: Corner/validations/over_budget_offer_rejected
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 40_000_000})
    ba = s["buyer_agent"]["id"]
    resp = api.create_offer(
        s["listing"]["id"],
        create_offer_payload(s["buyer"]["id"], ba, initial_price_cents=50_000_000),
        headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_OVER_BUDGET.value)


def test_earnest_money_exceeds_price_rejected(api):
    """PRD §3.5: "the amounts must be sane — a non-positive price, or `earnest_money_cents`
    greater than `initial_price_cents`, is rejected with `ERR_INVALID_AMOUNT` (HTTP 422)."

    Design: Corner/validations/earnest_money_exceeds_price_rejected
    """
    s = setup_active_listing(buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    resp = api.create_offer(
        s["listing"]["id"],
        create_offer_payload(s["buyer"]["id"], ba,
                             initial_price_cents=49_000_000,
                             earnest_money_cents=50_000_000),
        headers=make_buyer_agent_headers(ba))
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_suspended_agent_cannot_create_listing(api):
    """PRD §3.1: "A suspended agent is barred from the three creation operations that
    bring new commercial commitments into being — creating a listing, submitting an
    offer, and issuing a counter — each of which is rejected with `ERR_AGENT_SUSPENDED`
    (HTTP 403) while the acting agent is suspended."

    Design: Corner/validations/suspended_agent_cannot_create_listing
    """
    brk = create_brokerage()
    la = create_agent(brk["id"], full_name="Lara")
    suspend_agent(la["id"])
    resp = api.create_listing(
        create_listing_payload(la["id"], list_price_cents=50_000_000),
        headers=make_listing_agent_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_AGENT_SUSPENDED.value)
