"""Version preconditions on the two binding writes, and read-after-write visibility."""

from test_helpers import (
    ApiErrorId,
    accept_offer_payload,
    agreement_version,
    create_interim_extension,
    create_interim_extension_payload,
    make_group_counsel_headers,
    negotiation_version,
    read_agreement,
    read_election,
    read_extensions,
    read_negotiation,
    read_offer,
    read_station,
    setup_executed_agreement,
    setup_submitted_station_offer,
    submit_distributor_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSEL = make_group_counsel_headers("counsel-1")


def _station_offer_then_distributor_counter():
    """One SUBMITTED station offer at 250 cents, then a 200-cent counter."""
    ctx = setup_submitted_station_offer()
    ctx["counter"] = submit_distributor_offer(
        ctx["negotiation"]["id"],
        ctx["distributor"]["id"],
        ctx["report"]["id"],
        base_rate_per_sub_cents=200,
    )
    return ctx


def test_a_counter_offer_makes_the_earlier_negotiation_version_stale(api):
    """The station's offer is still live, yet the older version is refused with 412.

    PRD §2.7: "If that value does not equal the negotiation's current `version` at the
    moment of the write, the acceptance is rejected with
    `ERR_STALE_NEGOTIATION_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_negotiation_version_returns_412
    """
    ctx = _station_offer_then_distributor_counter()
    negotiation_id = ctx["negotiation"]["id"]

    assert read_offer(ctx["offer"]["id"])["status"] == "SUBMITTED"

    response = api.accept_offer(
        ctx["offer"]["id"], accept_offer_payload(2), COUNSEL
    )
    validate_error(response, ApiErrorId.ERR_STALE_NEGOTIATION_VERSION.value, 412)

    agreements, meta = validate_paginated(
        api.list_agreements(COUNSEL, params={"negotiation_id": negotiation_id})
    )
    assert agreements == []
    assert meta["total_count"] == 0

    negotiation = read_negotiation(negotiation_id)
    assert negotiation["status"] == "AWAITING_STATION_OFFER"
    assert negotiation["version"] == 3
    assert read_offer(ctx["offer"]["id"])["status"] == "SUBMITTED"


def test_the_same_acceptance_body_succeeds_on_the_refreshed_version(api):
    """Only the version differs on the retry, and the negotiation reaches CONSENTED.

    PRD §2.7: "Accepting an outstanding offer requires `expected_negotiation_version`,
    carrying the `version` of the parent `Negotiation` the client last observed."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_negotiation_version_returns_412
    """
    ctx = _station_offer_then_distributor_counter()
    negotiation_id = ctx["negotiation"]["id"]
    assert negotiation_version(negotiation_id) == 3

    validate_error(
        api.accept_offer(ctx["offer"]["id"], accept_offer_payload(2), COUNSEL),
        ApiErrorId.ERR_STALE_NEGOTIATION_VERSION.value,
        412,
    )

    agreement = validate_success(
        api.accept_offer(ctx["offer"]["id"], accept_offer_payload(3), COUNSEL), 201
    )
    assert agreement["negotiation_id"] == negotiation_id
    assert agreement["accepted_offer_id"] == ctx["offer"]["id"]

    negotiation = read_negotiation(negotiation_id)
    assert negotiation["status"] == "CONSENTED"
    assert negotiation["version"] == 4


def _executed_agreement_with_a_thirty_day_extension():
    """An EXECUTED agreement at version 3 plus one 30-day PRIOR_RATE extension."""
    ctx = setup_executed_agreement()
    assert agreement_version(ctx["agreement"]["id"]) == 3
    ctx["extension"] = create_interim_extension(
        ctx["agreement"]["id"],
        ctx["station"]["id"],
        extension_days=30,
        extension_start_utc="2030-01-01T00:00:00Z",
        extension_rate_basis="PRIOR_RATE",
    )
    assert ctx["extension"]["extension_end_utc"] == "2030-01-31T00:00:00Z"
    assert ctx["extension"]["effective_rate_per_sub_cents"] == 220
    return ctx


def test_the_first_extension_makes_the_earlier_agreement_version_stale(api):
    """A window and budget that are both fine still fail on the pre-extension version.

    PRD §2.7: "If that value does not equal the agreement's current `version` at the
    moment of the write, the creation is rejected with `ERR_STALE_AGREEMENT_VERSION`
    and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_agreement_version_returns_412
    """
    ctx = _executed_agreement_with_a_thirty_day_extension()

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            3,
            extension_days=20,
            extension_start_utc="2030-02-01T00:00:00Z",
            extension_rate_basis="PRIOR_RATE",
        ),
        ctx["negotiator_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value, 412)
    assert error["error_id"] != ApiErrorId.ERR_EXTENSION_WINDOW_OVERLAP.value
    assert error["error_id"] != ApiErrorId.ERR_EXTENSION_BUDGET_EXCEEDED.value

    assert len(read_extensions(ctx["agreement"]["id"])) == 1
    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 30
    assert agreement["version"] == 4


def test_the_second_extension_lands_once_the_fresh_agreement_version_is_supplied(api):
    """The retry draws the cumulative budget to 50 days and bumps the version again.

    PRD §3.8: "`consumed_extension_days` on the agreement is the sum of
    `extension_days` over that agreement's extensions in status `ACTIVE` or `LAPSED`,
    and the sum of that figure plus the newly requested `extension_days` may not
    exceed 90 days - a full quarter of interim carriage across the life of the
    agreement."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_agreement_version_returns_412
    """
    ctx = _executed_agreement_with_a_thirty_day_extension()

    validate_error(
        api.create_interim_extension(
            ctx["agreement"]["id"],
            create_interim_extension_payload(
                3,
                extension_days=20,
                extension_start_utc="2030-02-01T00:00:00Z",
                extension_rate_basis="PRIOR_RATE",
            ),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
        412,
    )

    second = validate_success(
        api.create_interim_extension(
            ctx["agreement"]["id"],
            create_interim_extension_payload(
                4,
                extension_days=20,
                extension_start_utc="2030-02-01T00:00:00Z",
                extension_rate_basis="PRIOR_RATE",
            ),
            ctx["negotiator_headers"],
        ),
        201,
    )
    assert second["extension_end_utc"] == "2030-02-21T00:00:00Z"
    assert second["status"] == "ACTIVE"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 50
    assert agreement["version"] == 5


def test_the_acceptance_response_already_carries_every_value_it_derives(api):
    """One write returns both status dimensions, the rights scope and the billed ladder.

    PRD §3.7: "The contrast with the negotiation ladder is concrete: for a base rate of
    250 cents and an escalator of 700 basis points over a three-year term, the
    compound-annual ladder quoted during negotiation runs 250, 268, 287, while the
    simple-annual ladder the executed contract bills on runs 250, 268, 285."

    Design: Corner/consistency_model/corner_consent_cascade_is_visible_in_the_same_response
    """
    ctx = _station_offer_then_distributor_counter()
    assert ctx["election"]["status"] == "NEGOTIATING"

    agreement = validate_success(
        api.accept_offer(
            ctx["offer"]["id"],
            accept_offer_payload(negotiation_version(ctx["negotiation"]["id"])),
            COUNSEL,
        ),
        201,
    )

    assert agreement["execution_status"] == "PENDING_EXECUTION"
    assert agreement["network_approval_status"] == "PENDING_NETWORK"
    assert agreement["granted_rights_scope"] == ["DIGITAL", "STREAMING"]
    assert agreement["contract_year_rate_schedule_cents"] == [250, 268, 285]
    assert agreement["consumed_extension_days"] == 0
    assert agreement["rights_credit_bp_total"] == 0
    assert agreement["lifetime_gross_fee_cents"] == 0
    assert agreement["lifetime_net_retained_cents"] == 0


def test_the_consent_cascade_is_complete_on_the_reads_that_follow_immediately(api):
    """No sweep runs, yet the negotiation, election, offers and counter are all settled.

    PRD §3.7: "The negotiation moves to `CONSENTED` from whichever of `OPEN`,
    `AWAITING_DISTRIBUTOR_RESPONSE`, `AWAITING_STATION_OFFER` or `IMPASSE` it was in,
    and its `version` increments by one."

    Design: Corner/consistency_model/corner_consent_cascade_is_visible_in_the_same_response
    """
    ctx = _station_offer_then_distributor_counter()
    validate_success(
        api.accept_offer(
            ctx["offer"]["id"],
            accept_offer_payload(negotiation_version(ctx["negotiation"]["id"])),
            COUNSEL,
        ),
        201,
    )

    assert read_negotiation(ctx["negotiation"]["id"])["status"] == "CONSENTED"
    assert read_election(ctx["election"]["id"])["status"] == "CONSENT_GRANTED"
    assert read_offer(ctx["offer"]["id"])["status"] == "ACCEPTED"
    assert read_offer(ctx["counter"]["id"])["status"] == "EXPIRED"
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 1
