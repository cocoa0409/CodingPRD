"""Cross-entity state dependencies: event scheduling gated on amenity state;
closing escrow gated on agreement and lot state."""
from test_helpers import (
    api_client,
    create_active_community,
    create_amenity_in_state,
    create_closing_payload,
    create_event_payload,
    create_executed_agreement,
    create_offered_lot,
    create_open_phase,
    create_builder,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestEventVenueRequiresAmenityOpen:
    """Scheduling a CLUBHOUSE-venue event is gated on the mapped amenity being
    UNDER_CONSTRUCTION or OPEN; the same request succeeds after the amenity
    advances."""

    def _setup(self):
        community = create_active_community("Amenity Acres", 50)
        amenity = create_amenity_in_state(
            community["id"], "IN_DESIGN", "CLUBHOUSE",
            hard_deadline_date="2027-12-31T00:00:00Z",
        )
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Clubhouse Gala", venue="CLUBHOUSE",
                    start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T12:00:00Z",
                    capacity=20,
                ),
                LIFESTYLE,
            )
        )
        return amenity, event

    def test_in_design_amenity_blocks_scheduling(self):
        """PRD §3.8: "The safety gate runs first: a `CLUBHOUSE`, `POOL_DECK`, or `EVENT_LAWN` venue maps to the amenity type `CLUBHOUSE`, `POOL`, or `EVENT_LAWN` respectively, and that amenity must be `UNDER_CONSTRUCTION` or `OPEN` — a `COMMITTED`, `IN_DESIGN`, or `DELINQUENT` amenity blocks scheduling with `ERR_AMENITY_NOT_OPEN` (residents are never booked into facilities not yet under construction).".

        Design: Difficulty/cross_entity_state_dependency/event_venue_requires_amenity_open
        """
        _, event = self._setup()
        resp = api_client.schedule_event(event["id"], LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_AMENITY_NOT_OPEN)

    def test_under_construction_amenity_allows_scheduling(self):
        """PRD §3.8: "The safety gate runs first: a `CLUBHOUSE`, `POOL_DECK`, or `EVENT_LAWN` venue maps to the amenity type `CLUBHOUSE`, `POOL`, or `EVENT_LAWN` respectively, and that amenity must be `UNDER_CONSTRUCTION` or `OPEN` — a `COMMITTED`, `IN_DESIGN`, or `DELINQUENT` amenity blocks scheduling with `ERR_AMENITY_NOT_OPEN` (residents are never booked into facilities not yet under construction).".
        PRD §3.2: "An amenity progresses from `COMMITTED` to `IN_DESIGN` to `UNDER_CONSTRUCTION` to `OPEN` under the `DeclarantExecutive`'s direction, and `OPEN` is terminal.".

        Design: Difficulty/cross_entity_state_dependency/event_venue_requires_amenity_open
        """
        amenity, event = self._setup()
        resp = api_client.schedule_event(event["id"], LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_AMENITY_NOT_OPEN)
        get_success_data(api_client.start_construction(amenity["id"], EXEC))
        scheduled = get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        assert scheduled["status"] == "SCHEDULED", (
            f"once the amenity is UNDER_CONSTRUCTION the same request must succeed, "
            f"got {scheduled['status']}"
        )


class TestClosingRequiresAgreementActiveAndLotOffered:
    """Escrow creation is rejected while the agreement is EXECUTED (not yet
    ACTIVE); after commence it succeeds; a second escrow on the same
    UNDER_CONTRACT lot is rejected."""

    def _setup(self):
        community = create_active_community("Gated Grove", 10)
        phase = create_open_phase(community["id"], "P1", 1, 5)
        builder = create_builder(community["id"], "Gate Builders", "A")
        agreement, _ = create_executed_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        lot = create_offered_lot(phase["id"], "L1")
        return agreement, lot

    def test_escrow_rejected_until_agreement_active(self):
        """PRD §3.4: "Creation requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the lot to be `OFFERED` (`ERR_LOT_NOT_OFFERED`), and the lot to belong to the agreement's phase (`ERR_LOT_PHASE_MISMATCH`); the closing starts `PENDING`, its `community_id` is denormalized from the agreement, and the lot moves automatically from `OFFERED` to `UNDER_CONTRACT`.".
        PRD §3.3: "A `DeclarantController` then commences the agreement, `EXECUTED` → `ACTIVE`, beginning the takedown obligations. Tranches live on the clock."

        Design: Difficulty/cross_entity_state_dependency/closing_requires_agreement_active_and_lot_offered
        """
        agreement, lot = self._setup()
        resp = api_client.create_closing(
            create_closing_payload(agreement_id=agreement["id"], lot_id=lot["id"]), CTRL
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        get_success_data(api_client.commence_agreement(agreement["id"], CTRL))
        closing = get_success_data(
            api_client.create_closing(
                create_closing_payload(agreement_id=agreement["id"], lot_id=lot["id"]), CTRL
            )
        )
        assert closing["status"] == "PENDING"
        lot_read = get_success_data(api_client.get_lot(lot["id"], EXEC))
        assert lot_read["status"] == "UNDER_CONTRACT", (
            "escrow creation moves the lot from OFFERED to UNDER_CONTRACT"
        )

    def test_second_escrow_on_under_contract_lot_rejected(self):
        """PRD §3.4: "Creation requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the lot to be `OFFERED` (`ERR_LOT_NOT_OFFERED`), and the lot to belong to the agreement's phase (`ERR_LOT_PHASE_MISMATCH`); the closing starts `PENDING`, its `community_id` is denormalized from the agreement, and the lot moves automatically from `OFFERED` to `UNDER_CONTRACT`." and creation requires "the lot to be OFFERED
        (ERR_LOT_NOT_OFFERED)".

        Design: Difficulty/cross_entity_state_dependency/closing_requires_agreement_active_and_lot_offered
        """
        agreement, lot = self._setup()
        get_success_data(api_client.commence_agreement(agreement["id"], CTRL))
        get_success_data(
            api_client.create_closing(
                create_closing_payload(agreement_id=agreement["id"], lot_id=lot["id"]), CTRL
            )
        )
        resp = api_client.create_closing(
            create_closing_payload(agreement_id=agreement["id"], lot_id=lot["id"]), CTRL
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_OFFERED)
