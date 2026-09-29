"""Programming the repertoire, the cyclic guest-artist negotiation, locking and substitution."""

from test_helpers import (
    ARTISTIC_ADMIN,
    ApiErrorId,
    build_world,
    counter_contract,
    create_contract,
    create_service,
    make_guest_artist_headers,
    program_concert,
    publish_service,
    read_concert,
    read_contract,
    read_season,
    read_service,
    revise_offer,
    set_clock,
    sign_contract_as_artist,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Programming
# --------------------------------------------------------------------------
def test_programming_a_concert_twice_is_refused(api):
    """PRD 3.2: "It is an `ArtisticAdmin` action, it requires the concert to still
    be in `DRAFT` — anything else is `ERR_CONCERT_NOT_DRAFT` — and it requires the
    owning season to still be in `PLANNING`, since programming decisions are
    frozen once the renewal window opens; a season past `PLANNING` yields
    `ERR_INVALID_SEASON_TRANSITION`."
    PRD 3.2: "Success increments the season's `concerts_programmed_count` by one
    and recomputes the concert's `readiness_posture`."

    Design: Corner/state_machines/program_concert_twice_returns_not_draft
    """
    world = build_world(with_union=False)

    response = api.program_concert(world.concert["id"], ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_CONCERT_NOT_DRAFT.value, 409)

    assert read_concert(world.concert["id"])["programming_status"] == "PROGRAMMED"
    assert read_season(world.season["id"])["concerts_programmed_count"] == 1, (
        "the refused second call must not double-count the concert"
    )


# --------------------------------------------------------------------------
# The cyclic negotiation
# --------------------------------------------------------------------------
def test_counter_then_revise_offer_returns_the_contract_to_offered(api):
    """PRD 3.2: "From `OFFERED` the artist may counter, moving the contract to
    `COUNTERED` and storing the demanded `countered_fee_cents` from the request."
    PRD 3.2: "This is an `ArtisticAdmin` action; it replaces `offered_fee_cents`
    with the newly supplied figure and increments `negotiation_round` by one."

    Design: Difficulty/non_linear_state_machine/contract_offer_counter_offer_cycle
    """
    world = build_world(with_union=False)
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)
    assert contract["status"] == "OFFERED"
    assert contract["negotiation_round"] == 1
    assert contract["countered_fee_cents"] is None
    assert contract["agreed_fee_cents"] is None

    countered = validate_success(
        api.counter_guest_contract(contract["id"], 1200000,
                                   make_guest_artist_headers(contract["id"]))
    )
    assert countered["status"] == "COUNTERED"
    assert countered["countered_fee_cents"] == 1200000
    assert countered["negotiation_round"] == 1, (
        "countering is the artist's move and does not advance the orchestra's round"
    )

    revised = validate_success(
        api.revise_guest_contract_offer(contract["id"], 950000, ARTISTIC_ADMIN)
    )
    assert revised["status"] == "OFFERED", "the cycle returns to a state it already held"
    assert revised["offered_fee_cents"] == 950000
    assert revised["negotiation_round"] == 2


def test_signing_from_countered_binds_the_artists_counter_fee(api):
    """PRD 3.2: "Signing **from `COUNTERED`** is the orchestra accepting the
    artist's demand: it is performed by an `ArtisticAdmin`, and
    `agreed_fee_cents` is set to the current `countered_fee_cents`."
    PRD 3.2: "A concert locks when three things are true at once: it is currently
    `PROGRAMMED`; it has at least one guest artist contract, every one of its
    contracts is either `SIGNED` or `WITHDRAWN`, and at least one of them is
    `SIGNED`; and at least one of its rehearsal services has reached `PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/contract_offer_counter_offer_cycle
    """
    world = build_world(with_union=False)
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)

    counter_contract(contract["id"], 1200000)
    revise_offer(contract["id"], 950000)
    counter_contract(contract["id"], 1100000)

    signed = validate_success(api.sign_guest_contract(contract["id"], ARTISTIC_ADMIN))

    assert signed["status"] == "SIGNED"
    assert signed["negotiation_round"] == 2
    assert signed["offered_fee_cents"] == 950000
    assert signed["countered_fee_cents"] == 1100000
    assert signed["agreed_fee_cents"] == 1100000, (
        "the COUNTERED branch binds the artist's counter, not the standing offer"
    )
    assert read_concert(world.concert["id"])["programming_status"] == "PROGRAMMED", (
        "no service has been published, so the concert cannot lock"
    )


def test_countering_a_signed_contract_is_refused(api):
    """PRD 3.2: "Only a `GuestArtist` whose `X-User-ID` equals the contract's own
    `id` may do this — anyone else is refused with `ERR_NOT_RESOURCE_OWNER` — and
    a contract that is not in `OFFERED` is refused with
    `ERR_CONTRACT_NOT_NEGOTIABLE`."
    PRD 3.2: "Signing **from `OFFERED`** is the artist accepting the orchestra's
    standing offer: it is performed by the `GuestArtist` whose `X-User-ID` equals
    the contract's own `id`, and `agreed_fee_cents` is set to the current
    `offered_fee_cents`."

    Design: Corner/state_machines/counter_signed_contract_returns_not_negotiable
    """
    world = build_world(with_union=False)
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)
    sign_contract_as_artist(contract["id"])

    response = api.counter_guest_contract(
        contract["id"], 1500000, make_guest_artist_headers(contract["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_NEGOTIABLE.value, 409)

    frozen = read_contract(contract["id"])
    assert frozen["status"] == "SIGNED"
    assert frozen["agreed_fee_cents"] == 800000
    assert frozen["countered_fee_cents"] is None


def test_revising_an_offer_at_round_three_hits_the_negotiation_cap(api):
    """PRD 3.2: "A contract not in `COUNTERED` is refused with
    `ERR_CONTRACT_NOT_NEGOTIABLE`, and the orchestra is capped at three rounds:
    once `negotiation_round` has reached 3 the revision is refused with
    `ERR_NEGOTIATION_ROUND_LIMIT`."
    PRD 2.6: "An orchestra offer may not be revised once `negotiation_round` has
    reached 3, else `ERR_NEGOTIATION_ROUND_LIMIT` with HTTP 422."

    Design: Corner/state_machines/revise_offer_at_round_three_returns_negotiation_round_limit
    """
    world = build_world(with_union=False)
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)

    counter_contract(contract["id"], 1200000)
    revise_offer(contract["id"], 900000)
    counter_contract(contract["id"], 1150000)
    revise_offer(contract["id"], 1000000)
    counter_contract(contract["id"], 1100000)

    assert read_contract(contract["id"])["negotiation_round"] == 3

    response = api.revise_guest_contract_offer(contract["id"], 1050000, ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value, 422)

    frozen = read_contract(contract["id"])
    assert frozen["negotiation_round"] == 3
    assert frozen["status"] == "COUNTERED"
    assert frozen["offered_fee_cents"] == 1000000


# --------------------------------------------------------------------------
# Cross-entity gate: signing needs a programmed concert
# --------------------------------------------------------------------------
def test_signing_a_contract_on_a_draft_concert_is_refused(api):
    """PRD 3.2: "Both branches require the parent concert's `programming_status` to
    be `PROGRAMMED` or `LOCKED`, refusing a still-`DRAFT` concert with
    `ERR_CONCERT_NOT_PROGRAMMED`, and both refuse a contract whose status does not
    permit signing with `ERR_CONTRACT_NOT_NEGOTIABLE`."

    Design: Difficulty/cross_entity_state_dependency/contract_sign_requires_concert_programmed
    """
    world = build_world(with_union=False, program_indexes=[])
    assert world.concert["programming_status"] == "DRAFT"
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)

    response = api.sign_guest_contract(
        contract["id"], make_guest_artist_headers(contract["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONCERT_NOT_PROGRAMMED.value, 409)

    unchanged = read_contract(contract["id"])
    assert unchanged["status"] == "OFFERED", (
        "the contract's own status is legal; only the parent concert blocks the signature"
    )
    assert unchanged["agreed_fee_cents"] is None


def test_signature_succeeds_once_the_parent_concert_is_programmed(api):
    """PRD 3.2: "Both branches require the parent concert's `programming_status` to
    be `PROGRAMMED` or `LOCKED`, refusing a still-`DRAFT` concert with
    `ERR_CONCERT_NOT_PROGRAMMED`, and both refuse a contract whose status does not
    permit signing with `ERR_CONTRACT_NOT_NEGOTIABLE`."
    PRD 3.2: "Signing **from `OFFERED`** is the artist accepting the orchestra's
    standing offer: it is performed by the `GuestArtist` whose `X-User-ID` equals
    the contract's own `id`, and `agreed_fee_cents` is set to the current
    `offered_fee_cents`."

    Design: Difficulty/cross_entity_state_dependency/contract_sign_requires_concert_programmed
    """
    world = build_world(with_union=False, program_indexes=[])
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)
    validate_error(
        api.sign_guest_contract(contract["id"],
                                make_guest_artist_headers(contract["id"])),
        ApiErrorId.ERR_CONCERT_NOT_PROGRAMMED.value,
        409,
    )

    program_concert(world.concert["id"])
    signed = validate_success(
        api.sign_guest_contract(contract["id"],
                                make_guest_artist_headers(contract["id"]))
    )

    assert signed["status"] == "SIGNED"
    assert signed["agreed_fee_cents"] == 800000
    assert read_concert(world.concert["id"])["programming_status"] == "PROGRAMMED"


# --------------------------------------------------------------------------
# Locking, substitution and readiness posture
# --------------------------------------------------------------------------
def test_a_concert_locks_only_after_both_signature_and_publication(api):
    """PRD 3.2: "A concert locks when three things are true at once: it is currently
    `PROGRAMMED`; it has at least one guest artist contract, every one of its
    contracts is either `SIGNED` or `WITHDRAWN`, and at least one of them is
    `SIGNED`; and at least one of its rehearsal services has reached `PUBLISHED`."
    PRD 3.2: "The promotion condition itself — the system-driven move of
    `programming_status` from `PROGRAMMED` to `LOCKED` — is evaluated at the close
    of every signature and at the close of every service publication, never on its
    own request."

    Design: Corner/state_machines/concert_locks_only_when_signature_and_publication_both_land
    """
    world = build_world()
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="CONDUCTOR", offered_fee_cents=800000)
    service = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T15:00:00Z",
        minimum_complement=0, break_minutes=0,
    )

    publish_service(service["id"])
    assert read_concert(world.concert["id"])["programming_status"] == "PROGRAMMED", (
        "publication alone does not lock the concert while a contract is still OFFERED"
    )

    signed = sign_contract_as_artist(contract["id"])
    assert signed["agreed_fee_cents"] == 800000
    assert read_concert(world.concert["id"])["programming_status"] == "LOCKED"
    assert read_service(service["id"])["status"] == "PUBLISHED"


def test_substitution_withdraws_the_contract_opens_a_replacement_and_unlocks(api):
    """PRD 3.9: "That contract moves to `WITHDRAWN`, and a fresh contract is created
    on the same concert in `OFFERED` with `negotiation_round` at 1, the same
    `role_type` as the contract it replaces, the `replacement_artist_name` as its
    `artist_name` and the `replacement_fee_cents` as its `offered_fee_cents` — the
    new offer is itself fully negotiable, so the replacement artist may counter it
    in turn."
    PRD 3.9: "The concert's `substitution_count` increments by one, and if the
    concert was `LOCKED` it reverts to `PROGRAMMED`, because a contract that had
    been signed no longer is."

    Design: Corner/state_machines/substitution_withdraws_contract_opens_new_offer_and_unlocks_concert
    """
    world = build_world()
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="CONDUCTOR", offered_fee_cents=800000)
    sign_contract_as_artist(contract["id"])
    service = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T15:00:00Z",
        minimum_complement=0, break_minutes=0,
    )
    publish_service(service["id"])
    assert read_concert(world.concert["id"])["programming_status"] == "LOCKED"

    replacement = validate_success(
        api.substitute_guest_artist(
            world.concert["id"],
            {
                "contract_id": contract["id"],
                "replacement_artist_name": "Yuri Panek",
                "replacement_fee_cents": 700000,
            },
            ARTISTIC_ADMIN,
        ),
        201,
    )

    assert read_contract(contract["id"])["status"] == "WITHDRAWN"
    assert replacement["status"] == "OFFERED"
    assert replacement["negotiation_round"] == 1
    assert replacement["role_type"] == "CONDUCTOR"
    assert replacement["artist_name"] == "Yuri Panek"
    assert replacement["offered_fee_cents"] == 700000

    concert = read_concert(world.concert["id"])
    assert concert["substitution_count"] == 1
    assert concert["programming_status"] == "PROGRAMMED"

    _, meta = validate_paginated(
        api.list_guest_contracts(ARTISTIC_ADMIN,
                                 params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 2


def test_open_contract_blocks_the_concert_once_the_season_goes_on_sale(api):
    """PRD 2.7: "The posture is `BLOCKED` when at least one guest artist contract on
    the concert is still in `OFFERED` or `COUNTERED` **and** the concert's season
    has reached `SINGLE_ON_SALE` or `IN_PROGRESS` — that is, the orchestra is
    selling tickets to a concert whose soloist has not signed."
    PRD 3.7: "Finally, every concert of the season recomputes its
    `readiness_posture`, which is where a concert still carrying an `OFFERED` or
    `COUNTERED` contract turns `BLOCKED` — the orchestra is now selling seats to a
    programme whose soloist has not signed."

    Design: Corner/calculations/readiness_posture_blocks_concert_with_open_contract_after_onsale
    """
    world = build_world()
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="SOLOIST", offered_fee_cents=800000)
    validate_success(api.advance_season(world.season["id"], "RENEWAL_WINDOW",
                                        ARTISTIC_ADMIN))
    set_clock("2026-10-01T00:00:00Z")

    validate_success(api.advance_season(world.season["id"], "SINGLE_ON_SALE",
                                        ARTISTIC_ADMIN))

    concert = read_concert(world.concert["id"])
    assert concert["readiness_posture"] == "BLOCKED"
    assert concert["sale_status"] == "PUBLIC_ONSALE"
    assert concert["programming_status"] == "PROGRAMMED"
    assert read_contract(contract["id"])["status"] == "OFFERED"
