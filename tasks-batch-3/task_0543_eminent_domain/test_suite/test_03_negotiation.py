"""Negotiation rounds: offer/counter cycle, turn discipline, prompt bonus,
readiness preconditions, ownership gating, and the AGREED cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, assert_offer_round,
    make_property_owner_headers,
    open_negotiation, finalize_appraisal, clear_ownership,
    create_parcel, add_fee_owner,
    setup_cleared_appraised_parcel, setup_open_negotiation,
    setup_agreed_negotiation, setup_parcel_with_owner,
    TEST_USERS,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]


# ---- combinatorial_formula / prompt_bonus_base_keyed_mode_c ----------------

def test_prompt_bonus_uses_low_tier_keyed_on_base_amount(api):
    """PRD §3.4: "if `agreed_amount_cents` is at most 25,000,000 cents (a
    threshold of \\$250,000), the low rate of 3 percent applies ... The
    `prompt_bonus_cents` is the `agreed_amount_cents` multiplied by the selected
    rate, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/prompt_bonus_base_keyed_mode_c
    """
    ctx = setup_cleared_appraised_parcel(severance=0, special=0, api=api)  # offer basis 25,000,000
    neg = open_negotiation(ctx["parcel"]["id"], offer=25_000_000, api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(neg["id"], {"action": "ACCEPT"}, owner), 201)
    data = validate_success(api.get_negotiation(neg["id"], AGENT))
    assert data["agreed_amount_cents"] == 25_000_000
    assert data["prompt_bonus_cents"] == 750_000


def test_settlement_total_is_agreed_plus_prompt_bonus(api):
    """PRD §3.4: "The negotiation's `settlement_total_cents` is then the
    `agreed_amount_cents` plus the `prompt_bonus_cents`; the tier is always
    determined from the base agreed amount, never from the settlement total."

    Design: Difficulty/combinatorial_formula/prompt_bonus_base_keyed_mode_c
    """
    ctx = setup_cleared_appraised_parcel(severance=0, special=0, api=api)
    neg = open_negotiation(ctx["parcel"]["id"], offer=25_000_000, api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(neg["id"], {"action": "ACCEPT"}, owner), 201)
    data = validate_success(api.get_negotiation(neg["id"], AGENT))
    assert data["settlement_total_cents"] == 25_750_000


# ---- non_linear_state_machine / negotiation_offer_counter_cycle ------------

def test_owner_counter_flips_negotiation_to_owner_countered(api):
    """PRD §3.4: "A counter from either side appends a new round ... flips the
    negotiation to the other party's turn (`AGENCY_OFFERED` becomes
    `OWNER_COUNTERED` when the owner counters ...".

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle
    """
    ctx = setup_open_negotiation(api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(
        ctx["negotiation"]["id"], {"action": "COUNTER", "amount_cents": 30_000_000},
        owner), 201)
    data = validate_success(api.get_negotiation(ctx["negotiation"]["id"], AGENT))
    assert data["status"] == "OWNER_COUNTERED"


def test_agency_counter_returns_negotiation_to_agency_offered(api):
    """PRD §3.4: "`OWNER_COUNTERED` returns to `AGENCY_OFFERED` when the agency
    counters or re-offers), and sets `current_amount_cents` to the countered
    amount."

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle
    """
    ctx = setup_open_negotiation(api=api)
    neg_id = ctx["negotiation"]["id"]
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(
        neg_id, {"action": "COUNTER", "amount_cents": 30_000_000}, owner), 201)
    validate_success(api.create_round(
        neg_id, {"action": "COUNTER", "amount_cents": 28_000_000}, AGENT), 201)
    data = validate_success(api.get_negotiation(neg_id, AGENT))
    assert data["status"] == "AGENCY_OFFERED"
    assert data["round_count"] == 3
    assert data["current_amount_cents"] == 28_000_000


# ---- boundary_precision_check / negotiation_requires_finalized_appraisal ----

def test_open_negotiation_with_only_draft_appraisal_rejected(api):
    """PRD §3.4: "Opening requires that the parcel's `research_status` be
    `OWNERSHIP_CLEARED` — otherwise `ERR_OWNERSHIP_NOT_CLEARED` — and that the
    parcel have a `FINALIZED` appraisal — otherwise `ERR_APPRAISAL_NOT_FINALIZED`."

    Design: Difficulty/boundary_precision_check/negotiation_requires_finalized_appraisal_empty_set
    """
    ctx = setup_cleared_appraised_parcel(clear=True, finalize=False, api=api)
    resp = api.create_negotiation(
        ctx["parcel"]["id"], {"initial_offer_cents": 27_000_000}, AGENT)
    validate_error(resp, ApiErrorId.ERR_APPRAISAL_NOT_FINALIZED)


def test_open_negotiation_succeeds_once_appraisal_finalized(api):
    """PRD §3.4: "Once a parcel's title is cleared and it carries a finalized
    valuation, a `RightOfWayAgent` opens a **Negotiation** against the parcel with
    an `initial_offer_cents`."

    Design: Difficulty/boundary_precision_check/negotiation_requires_finalized_appraisal_empty_set
    """
    ctx = setup_cleared_appraised_parcel(clear=True, finalize=False, api=api)
    finalize_appraisal(ctx["appraisal"]["id"], api=api)
    resp = api.create_negotiation(
        ctx["parcel"]["id"], {"initial_offer_cents": 27_000_000}, AGENT)
    data = validate_success(resp, 201)
    assert data["status"] == "AGENCY_OFFERED"


# ---- cross_entity_state_dependency / negotiation_open_requires_parcel_cleared

def test_open_negotiation_on_uncleared_parcel_rejected(api):
    """PRD §3.4: "Opening requires that the parcel's `research_status` be
    `OWNERSHIP_CLEARED` — otherwise `ERR_OWNERSHIP_NOT_CLEARED`".

    Design: Difficulty/cross_entity_state_dependency/negotiation_open_requires_parcel_cleared
    """
    ctx = setup_cleared_appraised_parcel(clear=False, finalize=True, api=api)
    resp = api.create_negotiation(
        ctx["parcel"]["id"], {"initial_offer_cents": 27_000_000}, AGENT)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_NOT_CLEARED)


def test_open_negotiation_succeeds_once_ownership_cleared(api):
    """PRD §3.2: "Clearing ownership research is a `RightOfWayAgent` action that
    advances the parcel's `research_status` from `RESEARCHING` to
    `OWNERSHIP_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/negotiation_open_requires_parcel_cleared
    """
    ctx = setup_cleared_appraised_parcel(clear=False, finalize=True, api=api)
    clear_ownership(ctx["parcel"]["id"], api=api)
    resp = api.create_negotiation(
        ctx["parcel"]["id"], {"initial_offer_cents": 27_000_000}, AGENT)
    data = validate_success(resp, 201)
    assert data["status"] == "AGENCY_OFFERED"


# ---- Corner: round on an AGREED negotiation --------------------------------

def test_round_on_agreed_negotiation_returns_invalid_state(api):
    """PRD §3.4: "a round submitted against a negotiation that has already reached
    a terminal outcome is rejected with `ERR_INVALID_NEGOTIATION_STATE`."

    Design: Corner/state_machines/round_on_agreed_negotiation_returns_invalid_state
    """
    ctx = setup_agreed_negotiation(api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    resp = api.create_round(
        ctx["negotiation"]["id"], {"action": "COUNTER", "amount_cents": 29_000_000},
        owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_NEGOTIATION_STATE)


# ---- Corner: owner acts out of turn ----------------------------------------

def test_owner_counter_out_of_turn_returns_not_your_turn(api):
    """PRD §3.4: "A round submitted by the party whose turn it is *not* is
    rejected with `ERR_NOT_YOUR_TURN`".

    Design: Corner/state_machines/owner_acts_out_of_turn_returns_not_your_turn
    """
    ctx = setup_open_negotiation(api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(
        ctx["negotiation"]["id"], {"action": "COUNTER", "amount_cents": 30_000_000},
        owner), 201)
    resp = api.create_round(
        ctx["negotiation"]["id"], {"action": "COUNTER", "amount_cents": 31_000_000},
        owner)
    validate_error(resp, ApiErrorId.ERR_NOT_YOUR_TURN)


# ---- Corner: offer round is append-only ------------------------------------

def test_opening_offer_round_is_append_only_event(api):
    """PRD §2.4: "An offer round is an append-only event in a negotiation ledger:
    it carries only `id` and `created_at`. It has no `updated_at` and no
    `version`, because it is never modified after creation."
    PRD §3.4: "its ledger seeded with a first offer round numbered 1, whose
    `party` is `AGENCY` and whose `action` is `OFFER` at the opening amount."

    Design: Corner/entities/offer_round_is_immutable_no_version_field
    """
    ctx = setup_open_negotiation(api=api)
    data, _ = _list_rounds(api, ctx["negotiation"]["id"])
    first = data[0]
    assert_offer_round(first)
    assert first["action"] == "OFFER"
    assert first["party"] == "AGENCY"
    assert first["round_no"] == 1
    assert first["amount_cents"] == 27_000_000


def _list_rounds(api, negotiation_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_rounds(negotiation_id, AGENT))


# ---- Corner: offer floor ---------------------------------------------------

def test_initial_offer_below_appraised_returns_offer_below(api):
    """PRD §3.4: "the `initial_offer_cents` may not fall below the parcel's
    `appraised_value_cents`; an under-floor opening is rejected with
    `ERR_OFFER_BELOW_APPRAISED`."

    Design: Corner/validations/initial_offer_below_appraised_returns_offer_below
    """
    ctx = setup_cleared_appraised_parcel(api=api)  # appraised 27,000,000
    resp = api.create_negotiation(
        ctx["parcel"]["id"], {"initial_offer_cents": 26_000_000}, AGENT)
    validate_error(resp, ApiErrorId.ERR_OFFER_BELOW_APPRAISED)


# ---- Corner: ownership completeness on clear -------------------------------

def test_clear_ownership_with_incomplete_pct_returns_incomplete(api):
    """PRD §3.2: "It succeeds only when fee ownership is fully accounted for: the
    sum of `ownership_pct` across the parcel's `FEE_OWNER` interests must equal
    exactly 100. If it does not, the clear is rejected with
    `ERR_OWNERSHIP_INCOMPLETE`."

    Design: Corner/validations/clear_ownership_incomplete_pct_returns_incomplete
    """
    ctx = setup_parcel_with_owner(pct=80, clear=False, api=api)
    resp = api.clear_ownership(ctx["parcel"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_INCOMPLETE)


# ---- Corner: non-owner PropertyOwner cannot counter ------------------------

def test_non_owner_property_owner_cannot_counter(api):
    """PRD §2.1: "A `PropertyOwner` whose `X-User-ID` is not an `OwnershipInterest`
    of the target parcel is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
    This ownership check applies to owner-party negotiation rounds and to
    relocation-benefit submission."

    Design: Corner/rbac/non_owner_property_owner_cannot_counter
    """
    ctx = setup_open_negotiation(api=api)
    parcel_b = create_parcel(ctx["project"]["id"], apn="APN-B", api=api)
    oi_b = add_fee_owner(parcel_b["id"], holder="OB", api=api)
    resp = api.create_round(
        ctx["negotiation"]["id"], {"action": "COUNTER", "amount_cents": 30_000_000},
        make_property_owner_headers(oi_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---- Corner: AGREED cascade is immediately visible -------------------------

def test_accept_cascades_parcel_to_agreed_immediately(api):
    """PRD §3.4: "moves the negotiation to `AGREED`, and cascades the parcel's
    `acquisition_status` from `IN_NEGOTIATION` to `AGREED`."

    Design: Corner/consistency_model/negotiation_agreed_cascade_visible_same_request
    """
    ctx = setup_open_negotiation(api=api)
    owner = make_property_owner_headers(ctx["owner"]["id"])
    validate_success(api.create_round(
        ctx["negotiation"]["id"], {"action": "ACCEPT"}, owner), 201)
    parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], AGENT))
    assert parcel["acquisition_status"] == "AGREED"
