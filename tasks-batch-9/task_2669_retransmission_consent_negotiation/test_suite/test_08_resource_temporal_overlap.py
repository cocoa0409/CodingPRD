"""Half-open carriage terms versus closed-at-both-ends extension windows."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_offer_payload,
    agreement_version,
    assert_interim_extension,
    create_election,
    create_interim_extension,
    create_interim_extension_payload,
    file_election,
    negotiation_of_election,
    negotiation_version,
    read_agreement,
    read_election,
    read_extensions,
    read_negotiation,
    read_offer,
    setup_executed_agreement,
    submit_station_offer,
    validate_error,
    validate_success,
)

SUCCESSOR_ELECTION = {
    "cycle_label": "2030-2032",
    "incumbent_expiry_utc": "2030-01-01T00:00:00Z",
    "incumbent_rate_per_sub_cents": 250,
}
SUCCESSOR_OFFER = {
    "base_rate_per_sub_cents": 300,
    "escalator_bp_per_year": 500,
    "term_months": 36,
}


def _successor_negotiation_on_the_same_slot():
    """An executed 2027-2030 agreement plus a second cycle awaiting acceptance."""
    ctx = setup_executed_agreement()
    successor_election = create_election(
        ctx["station"]["id"], ctx["distributor"]["id"], **SUCCESSOR_ELECTION
    )
    ctx["successor_election"] = file_election(
        successor_election["id"], ctx["station"]["id"]
    )
    ctx["successor_negotiation"] = negotiation_of_election(successor_election["id"])
    ctx["successor_offer"] = submit_station_offer(
        ctx["successor_negotiation"]["id"],
        ctx["station"]["id"],
        ctx["report"]["id"],
        **SUCCESSOR_OFFER,
    )
    return ctx


def test_overlapping_carriage_term_on_the_same_slot_is_refused(api):
    """A successor term reaching back into the incumbent term is an overlap.

    PRD §3.7: "The requested term is treated as half-open - inclusive of
    `effective_start_utc`, exclusive of `effective_end_utc` - and is compared against
    every existing carriage agreement on that same slot whose `execution_status` is
    `PENDING_EXECUTION` or `EXECUTED`."

    Design: Difficulty/resource_temporal_overlap/carriage_term_half_open_overlap_on_station_distributor_slot
    """
    ctx = _successor_negotiation_on_the_same_slot()
    version_before = negotiation_version(ctx["successor_negotiation"]["id"])

    response = api.accept_offer(
        ctx["successor_offer"]["id"],
        accept_offer_payload(
            version_before,
            effective_start_utc="2029-06-01T00:00:00Z",
            effective_end_utc="2032-06-01T00:00:00Z",
        ),
        TEST_USERS["group_counsel_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CARRIAGE_TERM_OVERLAP.value, 422)

    assert read_offer(ctx["successor_offer"]["id"])["status"] == "SUBMITTED"
    negotiation = read_negotiation(ctx["successor_negotiation"]["id"])
    assert negotiation["version"] == version_before
    assert negotiation["status"] == "AWAITING_DISTRIBUTOR_RESPONSE"
    assert read_election(ctx["successor_election"]["id"])["status"] == "NEGOTIATING"


def test_a_term_starting_when_the_prior_term_ends_is_adjacent_and_allowed(api):
    """Half-open intervals make a same-instant handover legal.

    PRD §3.7: "Because the interval is half-open, a term that starts at precisely the
    instant another one ends is adjacent rather than overlapping, and is allowed."

    Design: Difficulty/resource_temporal_overlap/carriage_term_half_open_overlap_on_station_distributor_slot
    """
    ctx = _successor_negotiation_on_the_same_slot()

    response = api.accept_offer(
        ctx["successor_offer"]["id"],
        accept_offer_payload(
            negotiation_version(ctx["successor_negotiation"]["id"]),
            effective_start_utc="2030-01-01T00:00:00Z",
            effective_end_utc="2033-01-01T00:00:00Z",
        ),
        TEST_USERS["group_counsel_headers"],
    )
    successor_agreement = validate_success(response, 201)

    assert successor_agreement["effective_start_utc"] == "2030-01-01T00:00:00Z"
    assert successor_agreement["execution_status"] == "PENDING_EXECUTION"
    assert read_agreement(ctx["agreement"]["id"])["effective_end_utc"] == (
        "2030-01-01T00:00:00Z"
    )
    assert read_offer(ctx["successor_offer"]["id"])["status"] == "ACCEPTED"
    assert read_negotiation(ctx["successor_negotiation"]["id"])["status"] == "CONSENTED"


def _executed_agreement_with_a_sixty_day_extension():
    ctx = setup_executed_agreement()
    ctx["extension"] = create_interim_extension(
        ctx["agreement"]["id"],
        ctx["station"]["id"],
        extension_days=60,
        extension_start_utc="2030-01-01T00:00:00Z",
        extension_rate_basis="PRIOR_RATE",
    )
    assert ctx["extension"]["extension_end_utc"] == "2030-03-02T00:00:00Z"
    assert ctx["extension"]["effective_rate_per_sub_cents"] == 220
    return ctx


def test_an_extension_window_sharing_only_its_boundary_day_is_refused(api):
    """Extension windows are closed at both endpoints, so the boundary day collides.

    PRD §3.8: "A requested window that shares even a single instant - including just
    its boundary day - with an existing extension on the same agreement in status
    `ACTIVE` or `LAPSED` is refused with `ERR_EXTENSION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interim_extension_closed_window_overlap_and_ninety_day_budget
    """
    ctx = _executed_agreement_with_a_sixty_day_extension()

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            agreement_version(ctx["agreement"]["id"]),
            extension_days=30,
            extension_start_utc="2030-03-02T00:00:00Z",
            extension_rate_basis="PRIOR_RATE",
        ),
        ctx["negotiator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EXTENSION_WINDOW_OVERLAP.value, 422)

    assert len(read_extensions(ctx["agreement"]["id"])) == 1
    assert read_agreement(ctx["agreement"]["id"])["consumed_extension_days"] == 60


def test_a_second_extension_may_land_exactly_on_the_ninety_day_budget(api):
    """Thirty more days one day clear of the prior window reaches the cap exactly.

    PRD §3.8: "Landing exactly on 90 is permitted; going past it is refused with
    `ERR_EXTENSION_BUDGET_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/interim_extension_closed_window_overlap_and_ninety_day_budget
    """
    ctx = _executed_agreement_with_a_sixty_day_extension()

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            agreement_version(ctx["agreement"]["id"]),
            extension_days=30,
            extension_start_utc="2030-03-03T00:00:00Z",
            extension_rate_basis="LAST_STATION_OFFER",
        ),
        ctx["negotiator_headers"],
    )
    extension = validate_success(response, 201)

    assert_interim_extension(extension)
    assert extension["extension_end_utc"] == "2030-04-02T00:00:00Z"
    assert extension["effective_rate_per_sub_cents"] == 250
    assert extension["status"] == "ACTIVE"
    assert read_agreement(ctx["agreement"]["id"])["consumed_extension_days"] == 90


def test_a_further_extension_past_the_ninety_day_budget_is_refused(api):
    """With the budget exhausted even a single further day is refused.

    PRD §2.8: "The extension-day budget is not exceeded -
    `ERR_EXTENSION_BUDGET_EXCEEDED`. Applies to creating an interim extension."

    Design: Difficulty/resource_temporal_overlap/interim_extension_closed_window_overlap_and_ninety_day_budget
    """
    ctx = _executed_agreement_with_a_sixty_day_extension()
    create_interim_extension(
        ctx["agreement"]["id"],
        ctx["station"]["id"],
        extension_days=30,
        extension_start_utc="2030-03-03T00:00:00Z",
        extension_rate_basis="LAST_STATION_OFFER",
    )
    version_before = agreement_version(ctx["agreement"]["id"])

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            version_before,
            extension_days=1,
            extension_start_utc="2030-04-03T00:00:00Z",
            extension_rate_basis="PRIOR_RATE",
        ),
        ctx["negotiator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EXTENSION_BUDGET_EXCEEDED.value, 422)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 90
    assert agreement["version"] == version_before
    assert len(read_extensions(ctx["agreement"]["id"])) == 2
