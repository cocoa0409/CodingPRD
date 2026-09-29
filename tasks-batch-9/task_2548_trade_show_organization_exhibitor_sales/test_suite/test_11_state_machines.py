"""
Lifecycle edges read one at a time: the promotions, the guarded transitions, the
unreachable targets, the declared birth states, the terminal lock-downs and the
two conditional close sweeps.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    BoothStatus,
    DealStatus,
    ExhibitorStatus,
    FloorPosture,
    FulfillmentStatus,
    ObligationStatus,
    PriorityTier,
    QualificationStatus,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
    ViolationStatus,
    factories as f,
    fixtures as fx,
    make_director_headers,
    make_floor_manager_headers,
    make_sales_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)
D010 = f.inline_booth_payload("D010", 10, 10)

DESK_WINDOW_START = "2027-03-01T09:00:00Z"
DESK_WINDOW_END = "2027-03-01T11:00:00Z"

REPORTER = make_floor_manager_headers("u_fm_1")
ADJUDICATOR = make_director_headers("u_sd_1")


def test_a_director_can_promote_a_waitlisted_badge_without_re_scoring_it(
    client: ApiClient,
):
    """
    A category manager scores exactly into the waitlist band and is then let in by hand.

    "Authority contributes 0 points for `NONE`, 15 for `INFLUENCER`, 25 for
    `RECOMMENDER` and 40 for `DECISION_MAKER`."  "A score of at least 40 but below
    60 transitions it `PENDING → WAITLISTED`."  "The decision is written straight
    into `qualification_status`, moving the row `WAITLISTED → QUALIFIED` or
    `WAITLISTED → REJECTED`, the justification is stored in
    `screening_override_reason`, and the registration's `version` is incremented.
    The previously computed `qualification_score` is deliberately preserved
    untouched"

    Design: Corner/state_machines/waitlisted_registration_is_promoted_by_a_director_override
    """
    fx.set_clock(client, CLOCK)
    env = fx.selling_show(client, [A100])
    waitlisted = fx.registration(
        client, env["show"]["id"], fx.REGISTRANT_HEADERS,
        category="BUYER", company_name="Cavendish Grocers",
        job_title="Category Manager", purchasing_authority="RECOMMENDER",
        annual_spend_band="K250K_1M", email="cm@cavendish.example",
    )
    assert waitlisted["qualification_score"] == 50
    assert waitlisted["qualification_status"] == QualificationStatus.WAITLISTED
    assert waitlisted["screening_override_reason"] is None
    before = waitlisted["version"]

    reason = "Verified buying authority by phone with the retailer's head office"
    promoted = validate_success(
        client.screen_registration(
            waitlisted["id"], f.screen_payload("QUALIFIED", reason),
            fx.DIRECTOR_HEADERS,
        )
    )
    assert promoted["qualification_status"] == QualificationStatus.QUALIFIED
    assert promoted["qualification_score"] == 50
    assert promoted["screening_override_reason"] == reason
    assert promoted["version"] == before + 1


def test_a_floor_plan_with_no_booths_cannot_be_published(client: ApiClient):
    """
    The aisle ratio clears the hall minimum, so emptiness is the only fault left.

    "The operation requires that the show still be `PLANNING`, that its venue
    agreement still be `EXECUTED`, that its `aisle_ratio_pct` be at least the hall's
    `min_aisle_ratio_pct`, that at least one booth of the show be in a status other
    than `MERGED` — a show with nothing but merged shells, or with no booths at all,
    is refused with `ERR_FLOOR_PLAN_EMPTY`"

    Design: Corner/state_machines/publishing_a_show_with_no_booths_is_refused
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    show_id = env["show"]["id"]
    assert env["show"]["aisle_ratio_pct"] == 40
    assert env["venue_contract"]["min_aisle_ratio_pct"] == 30
    pinned = fx.show_version(client, show_id)

    validate_error(
        client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS),
        ApiErrorId.FLOOR_PLAN_EMPTY,
        422,
    )

    show = fx.read_show(client, show_id)
    assert show["status"] == ShowStatus.PLANNING
    assert show["version"] == pinned
    assert show["net_sellable_sqft"] == 0
    assert show["advance_order_deadline"] is None


def test_opening_the_general_sale_expires_a_scheduled_slot_for_free(
    client: ApiClient,
):
    """
    A slot whose round never opened is swept aside by the `SELLING` transition.

    "On success, every appointment of the show still in state `SCHEDULED`
    transitions to `EXPIRED` with no penalty, the show's `floor_posture` is
    recomputed, and its `version` is incremented."  "transitions `SCHEDULED →
    EXPIRED` with `rank` and `certified_points_at_rank` left null and **no** penalty
    charged"

    Design: Corner/state_machines/opening_sales_expires_every_scheduled_appointment_without_penalty
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100])
    show_id = env["show"]["id"]
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    slot = fx.scheduled_appointment(client, show_id, harbor["id"], 1,
                                    DESK_WINDOW_START, DESK_WINDOW_END,
                                    fx.SALES_REP_HEADERS)
    assert slot["state"] == AppointmentState.SCHEDULED
    show_before = fx.read_show(client, show_id)

    opened = fx.transition(client, show_id, ShowStatus.SELLING)
    assert opened["status"] == ShowStatus.SELLING
    assert opened["version"] == show_before["version"] + 1

    swept = validate_success(
        client.get_selection_appointment(slot["id"], fx.DIRECTOR_HEADERS)
    )
    assert swept["state"] == AppointmentState.EXPIRED
    assert swept["rank"] is None
    assert swept["certified_points_at_rank"] is None
    assert swept["version"] == slot["version"] + 1

    assert fx.read_exhibitor(client, harbor["id"])["penalty_points"] == 0
    assert opened["selection_round"] == 0
    _, meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS, {"show_id": show_id})
    )
    assert meta["total_count"] == 0


def test_the_general_sale_waits_for_the_desk_to_clear(client: ApiClient):
    """
    Two byte-identical transition requests: the first blocked by another row's state.

    "That transition is refused with `ERR_INVALID_SHOW_TRANSITION` while any
    appointment of the show is still in state `ACTIVE` — the desk must be clear
    before the general sale opens."  "A successful exercise transitions the
    appointment `ACTIVE → EXERCISED` and creates one space contract in `OFFERED`
    status for that show and exhibitor"

    Design: Corner/state_machines/selling_is_blocked_while_a_selection_appointment_is_active
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    slot = fx.scheduled_appointment(client, show_id, harbor["id"], 1,
                                    DESK_WINDOW_START, DESK_WINDOW_END,
                                    fx.SALES_REP_HEADERS)
    fx.set_clock(client, "2027-03-01T09:30:00Z")
    validate_success(client.advance_selection_round(show_id, fx.DIRECTOR_HEADERS))

    at_the_desk = validate_success(
        client.get_selection_appointment(slot["id"], fx.DIRECTOR_HEADERS)
    )
    assert at_the_desk["state"] == AppointmentState.ACTIVE
    assert at_the_desk["rank"] == 1

    body = f.transition_payload(ShowStatus.SELLING)
    validate_error(
        client.transition_show(show_id, body, fx.DIRECTOR_HEADERS),
        ApiErrorId.INVALID_SHOW_TRANSITION,
        409,
    )
    assert fx.read_show(client, show_id)["status"] == ShowStatus.SPACE_SELECTION

    validate_success(
        client.exercise_appointment(
            slot["id"],
            f.exercise_payload(fx.show_version(client, show_id), 400,
                               premium_placement_requested=True),
            fx.make_exhibitor_headers(harbor["id"]),
        ),
        201,
    )
    assert (
        validate_success(
            client.get_selection_appointment(slot["id"], fx.DIRECTOR_HEADERS)
        )["state"]
        == AppointmentState.EXERCISED
    )
    assert (
        fx.read_booth(client, env["booth_by_number"]["A100"]["id"])["status"]
        == BoothStatus.HELD
    )

    opened = validate_success(
        client.transition_show(show_id, body, fx.DIRECTOR_HEADERS)
    )
    assert opened["status"] == ShowStatus.SELLING


def test_an_edition_cannot_skip_a_rung_of_its_own_ladder(client: ApiClient):
    """
    Three unreachable targets refused, with the one legal step in between.

    "Any target status that is not reachable from the show's current status by one of
    the transitions above is refused with `ERR_INVALID_SHOW_TRANSITION`."
    "Publishing the floor plan closes the design phase and opens selection, moving
    the edition `PLANNING → SPACE_SELECTION`."

    Design: Corner/state_machines/planning_cannot_jump_straight_to_on_site
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100])
    show_id = env["show"]["id"]
    booth_id = env["booth_by_number"]["A100"]["id"]
    pinned = fx.show_version(client, show_id)

    for target in (ShowStatus.ON_SITE, ShowStatus.SELLING):
        validate_error(
            client.transition_show(show_id, f.transition_payload(target),
                                   fx.DIRECTOR_HEADERS),
            ApiErrorId.INVALID_SHOW_TRANSITION,
            409,
        )

    published = validate_success(
        client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS)
    )
    assert published["status"] == ShowStatus.SPACE_SELECTION

    validate_error(
        client.transition_show(show_id, f.transition_payload(ShowStatus.CLOSED),
                              fx.DIRECTOR_HEADERS),
        ApiErrorId.INVALID_SHOW_TRANSITION,
        409,
    )

    show = fx.read_show(client, show_id)
    assert show["status"] == ShowStatus.SPACE_SELECTION
    assert show["version"] == pinned + 1
    assert fx.read_booth(client, booth_id)["status"] == BoothStatus.AVAILABLE


def test_every_row_is_born_in_the_state_the_contract_declares(client: ApiClient):
    """
    One chain from agreement to hold, with no endpoint ever accepting a status input.

    "A newly registered agreement has a `status` of `DRAFT`, a null `executed_at`, a
    null `terminated_effective_date`, and a `show_count` of zero."  "A newly created
    edition starts with a `status` of `PLANNING`, a `selection_round` of 0, a
    `floor_posture` of `OPEN`"  "A new booth's `status` is `AVAILABLE`, with a null
    `space_contract_id` and a null `combined_parent_booth_id`."  "A booked
    appointment starts in state `SCHEDULED`, with `rank` and
    `certified_points_at_rank` both null until its round opens."  "A new contract
    opens in `OFFERED` status with `negotiation_round` at 0 ... a null `signed_at`"

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    fx.set_clock(client, CLOCK)

    agreement = fx.draft_venue_contract(client)
    assert agreement["status"] == VenueContractStatus.DRAFT
    assert agreement["executed_at"] is None
    assert agreement["show_count"] == 0

    validate_success(
        client.execute_venue_contract(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    show = validate_success(
        client.create_show(f.show_payload(agreement["id"]), fx.DIRECTOR_HEADERS), 201
    )
    assert show["status"] == ShowStatus.PLANNING
    assert show["selection_round"] == 0
    assert show["floor_posture"] == FloorPosture.OPEN

    booth = validate_success(
        client.create_booth(show["id"], A100, fx.FLOOR_MANAGER_HEADERS), 201
    )
    assert booth["status"] == BoothStatus.AVAILABLE
    assert booth["space_contract_id"] is None
    assert booth["combined_parent_booth_id"] is None

    validate_success(client.publish_floor_plan(show["id"], fx.DIRECTOR_HEADERS))
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)

    slot = validate_success(
        client.create_selection_appointment(
            show["id"],
            f.appointment_payload(harbor["id"], 1, DESK_WINDOW_START,
                                  DESK_WINDOW_END),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert slot["state"] == AppointmentState.SCHEDULED
    assert slot["rank"] is None
    assert slot["certified_points_at_rank"] is None

    hold = validate_success(
        client.create_space_contract(
            f.space_contract_payload(
                show["id"], harbor["id"], fx.show_version(client, show["id"]), 400,
                premium_placement_requested=True, booth_ids=[booth["id"]],
            ),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert hold["status"] == SpaceContractStatus.OFFERED
    assert hold["negotiation_round"] == 0
    assert hold["signed_at"] is None
    assert hold["deposit_paid_cents"] == 0
    assert hold["points_awarded"] == 0
    assert hold["assigned_net_sqft"] == 0


def test_a_merged_shell_and_a_dead_edition_are_both_shut_for_good(client: ApiClient):
    """
    One booth absorbed into its neighbour, then the whole edition killed off.

    "`MERGED` is terminal: a merged booth can never again be held, assigned, or
    un-merged, and its area now lives permanently inside the survivor."  "each
    child's `area_sqft` is added to the survivor's `area_sqft`"  "Any target status
    that is not reachable from the show's current status by one of the transitions
    above is refused with `ERR_INVALID_SHOW_TRANSITION`."

    Design: Corner/state_machines/merged_booths_and_cancelled_shows_are_locked_down
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100, C050, D010])
    show_id = env["show"]["id"]
    survivor_id = env["booth_by_number"]["C050"]["id"]
    child_id = env["booth_by_number"]["D010"]["id"]

    validate_success(
        client.combine_booths(
            survivor_id,
            f.combine_payload(fx.show_version(client, show_id), [child_id]),
            fx.FLOOR_MANAGER_HEADERS,
        )
    )
    child = fx.read_booth(client, child_id)
    assert child["status"] == BoothStatus.MERGED
    assert child["combined_parent_booth_id"] == survivor_id
    assert fx.read_booth(client, survivor_id)["area_sqft"] == 300

    validate_success(client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS))
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(
                show_id, alder["id"], fx.show_version(client, show_id), 100,
                booth_ids=[child_id],
            ),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.BOOTH_MERGED,
        409,
    )
    assert fx.read_booth(client, child_id)["status"] == BoothStatus.MERGED
    assert fx.read_show(client, show_id)["sellable_booth_sqft"] == 700

    killed = fx.transition(client, show_id, ShowStatus.CANCELLED,
                           cancellation_reason="Anchor sponsor withdrew")
    assert killed["status"] == ShowStatus.CANCELLED
    assert killed["cancellation_reason"] == "Anchor sponsor withdrew"

    for target in (ShowStatus.CLOSED, ShowStatus.SELLING):
        validate_error(
            client.transition_show(show_id, f.transition_payload(target),
                                   fx.DIRECTOR_HEADERS),
            ApiErrorId.INVALID_SHOW_TRANSITION,
            409,
        )
    assert fx.read_show(client, show_id)["version"] == killed["version"]


def _cited_on_site_env(client: ApiClient) -> dict:
    """An ON_SITE edition with one signed hold on A100 and citations available."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    basalt = fx.exhibitor(client, "Basalt Cookware",
                          contact_email="space@basalt.example",
                          consecutive_years=4, headers=fx.SALES_REP_HEADERS)
    contract = fx.signed_contract(client, show_id, basalt["id"], 400,
                                  [env["booth_by_number"]["A100"]["id"]], 389070,
                                  premium_placement_requested=True)
    assert contract["min_deposit_cents"] == 389070
    fx.transition(client, show_id, ShowStatus.SELLING)
    env["show"] = fx.transition(client, show_id, ShowStatus.ON_SITE)
    env.update({"exhibitor": basalt, "contract": contract})
    return env


def test_neither_a_countersignature_nor_a_ruling_can_be_replayed(client: ApiClient):
    """
    Two replays, each refused, and the second one charges no second penalty.

    "The operation requires that the agreement currently be `DRAFT` — a replayed
    countersignature on an already-executed or already-terminated agreement is
    answered with `ERR_VENUE_CONTRACT_NOT_DRAFT`"  "only a citation still `OPEN` can
    be adjudicated — a second ruling on the same row is refused with
    `ERR_VIOLATION_ALREADY_ADJUDICATED`"  "sets the citation's `penalty_points` from
    the penalty schedule: ten for `BOOTH_HEIGHT`, five for `NOISE`"

    Design: Corner/state_machines/replayed_execute_and_replayed_adjudication_are_both_refused
    """
    env = _cited_on_site_env(client)
    agreement_id = env["venue_contract"]["id"]
    executed = validate_success(
        client.get_venue_contract(agreement_id, fx.DIRECTOR_HEADERS)
    )

    citation = fx.open_citation(client, env["contract"]["id"], REPORTER,
                               violation_type="NOISE",
                               notes="Live demo above 85 dBA during keynote")
    ruled = validate_success(
        client.adjudicate(citation["id"], f.adjudicate_payload("UPHELD"),
                          ADJUDICATOR)
    )
    assert ruled["status"] == ViolationStatus.UPHELD
    assert ruled["penalty_points"] == 5

    validate_error(
        client.execute_venue_contract(agreement_id, fx.DIRECTOR_HEADERS),
        ApiErrorId.VENUE_CONTRACT_NOT_DRAFT,
        409,
    )
    after = validate_success(
        client.get_venue_contract(agreement_id, fx.DIRECTOR_HEADERS)
    )
    assert after["status"] == VenueContractStatus.EXECUTED
    assert after["executed_at"] == executed["executed_at"]
    assert after["version"] == executed["version"]

    validate_error(
        client.adjudicate(citation["id"], f.adjudicate_payload("UPHELD"),
                          ADJUDICATOR),
        ApiErrorId.VIOLATION_ALREADY_ADJUDICATED,
        409,
    )
    rows, _ = validate_paginated(
        client.list_rule_violations(env["contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    replayed = next(row for row in rows if row["id"] == citation["id"])
    assert replayed["status"] == ViolationStatus.UPHELD
    assert replayed["penalty_points"] == 5
    assert replayed["version"] == ruled["version"]

    assert fx.read_exhibitor(client, env["exhibitor"]["id"])["penalty_points"] == 5
    show = fx.read_show(client, env["show"]["id"])
    assert show["upheld_violation_count"] == 1
    assert show["floor_posture"] == FloorPosture.OPEN


def test_the_third_upheld_citation_freezes_a_two_thirds_empty_floor(
    client: ApiClient,
):
    """
    The freeze arrives from the enforcement branch, not the commitment branch.

    "The posture is then `FROZEN` when `committed_ratio_pct` is at least 100, and
    also when the show is `ON_SITE` and its `upheld_violation_count` has reached
    three"  "Finally the show's `upheld_violation_count` is recomputed and its
    `floor_posture` re-derived, which is how a third upheld citation freezes an
    `ON_SITE` floor."

    Design: Corner/state_machines/three_upheld_citations_freeze_the_on_site_floor
    """
    env = _cited_on_site_env(client)
    show_id = env["show"]["id"]
    contract_id = env["contract"]["id"]
    citations = [
        fx.open_citation(client, contract_id, REPORTER, violation_type="NOISE",
                        notes=f"Amplified demo, warning number {n}")
        for n in (1, 2, 3)
    ]

    expected_posture = (FloorPosture.OPEN, FloorPosture.OPEN, FloorPosture.FROZEN)
    for index, citation in enumerate(citations, start=1):
        before = fx.read_show(client, show_id)["version"]
        validate_success(
            client.adjudicate(citation["id"], f.adjudicate_payload("UPHELD"),
                              ADJUDICATOR)
        )
        show = fx.read_show(client, show_id)
        assert show["upheld_violation_count"] == index
        assert show["floor_posture"] == expected_posture[index - 1]
        assert show["committed_ratio_pct"] == 67
        assert show["version"] == before + 1

    cited = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert cited["penalty_points"] == 15
    assert cited["status"] == ExhibitorStatus.ACTIVE
    assert cited["provisional_priority_points"] == 0
    assert cited["priority_tier"] == PriorityTier.BRONZE


KEYNOTE_OBLIGATIONS = ["LOGO_PLACEMENT", "STAGE_BANNER"]


def _by_code(client: ApiClient, deal_id: str) -> dict:
    return {row["obligation_code"]: row
            for row in fx.read_obligations(client, deal_id)}


def test_the_close_sweep_walks_past_the_obligations_of_a_cancelled_deal(
    client: ApiClient,
):
    """
    Two deals, one leftover obligation each: only the live deal's is marked missed.

    "Then every `FulfillmentObligation` still `PENDING` whose deal is `SIGNED`
    transitions `PENDING → MISSED`, processed in `created_at` ascending order, and
    each of those transitions bubbles its deal to `BREACHED` and charges the sponsor
    as §3.7 describes."  "Obligations still `PENDING` stay `PENDING`, and because
    their deal is no longer `SIGNED` they are excluded from the missed-obligation
    sweep that runs at show close."  "Breach costs the sponsor twenty penalty
    points, added to its `penalty_points`"

    Design: Corner/state_machines/show_close_misses_only_the_obligations_of_a_still_signed_deal
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100])
    show_id = env["show"]["id"]
    keynote = fx.sponsorship_package(
        client, show_id, package_code="PKG_KEYNOTE", list_price_cents=4000000,
        price_floor_cents=3200000, inventory_total=2,
        obligation_codes=KEYNOTE_OBLIGATIONS, priority_point_value=50,
    )
    lanyard = fx.sponsorship_package(
        client, show_id, package_code="PKG_LANYARD", list_price_cents=4000000,
        price_floor_cents=3200000, inventory_total=2,
        obligation_codes=["LANYARD_PRINT"], priority_point_value=30,
    )
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example",
                          consecutive_years=2, headers=fx.SALES_REP_HEADERS)
    proposer = make_sales_rep_headers("u_sr_1")
    signer = make_director_headers("u_sd_1")
    live = fx.signed_deal(client, keynote["id"], nordic["id"], 4000000,
                          proposer_headers=proposer, signer_headers=signer)
    doomed = fx.signed_deal(client, lanyard["id"], harbor["id"], 4000000,
                            proposer_headers=proposer, signer_headers=signer)

    live_obligations = _by_code(client, live["id"])
    doomed_obligations = _by_code(client, doomed["id"])
    for row in list(live_obligations.values()) + list(doomed_obligations.values()):
        assert row["due_date"] == "2027-02-19"

    validate_success(
        client.resolve_obligation(
            live["id"], live_obligations["LOGO_PLACEMENT"]["id"],
            f.resolve_obligation_payload("DELIVERED",
                                         note="Logo on all keynote screens"),
            REPORTER,
        )
    )
    validate_success(
        client.cancel_sponsorship_deal(
            doomed["id"], f.cancel_payload("Sponsor pulled the lanyard buy"), signer
        )
    )
    assert (
        fx.read_deal(client, live["id"])["fulfillment_status"]
        == FulfillmentStatus.PARTIAL
    )
    cancelled_before = fx.read_deal(client, doomed["id"])
    assert cancelled_before["deal_status"] == DealStatus.CANCELLED
    assert cancelled_before["fulfillment_status"] == FulfillmentStatus.NOT_STARTED
    skipped_before = _by_code(client, doomed["id"])["LANYARD_PRINT"]

    validate_success(client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS))
    fx.transition(client, show_id, ShowStatus.SELLING)
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    closed = fx.transition(client, show_id, ShowStatus.CLOSED)
    assert closed["status"] == ShowStatus.CLOSED

    assert (
        _by_code(client, live["id"])["STAGE_BANNER"]["status"]
        == ObligationStatus.MISSED
    )
    skipped_after = _by_code(client, doomed["id"])["LANYARD_PRINT"]
    assert skipped_after["status"] == ObligationStatus.PENDING
    assert skipped_after["version"] == skipped_before["version"]

    assert (
        fx.read_deal(client, live["id"])["fulfillment_status"]
        == FulfillmentStatus.BREACHED
    )
    assert (
        fx.read_deal(client, doomed["id"])["fulfillment_status"]
        == FulfillmentStatus.NOT_STARTED
    )
    breached_sponsor = fx.read_exhibitor(client, nordic["id"])
    assert breached_sponsor["penalty_points"] == 20
    assert breached_sponsor["status"] == ExhibitorStatus.ACTIVE
    assert fx.read_exhibitor(client, harbor["id"])["penalty_points"] == 0
