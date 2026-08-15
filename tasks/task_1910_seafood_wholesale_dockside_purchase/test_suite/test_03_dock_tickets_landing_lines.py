"""Dock tickets and landing lines: landing windows, provisional settlement,
optimistic concurrency on the ticket, ownership, and traceability references."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_kg,
    is_valid_uuid,
    make_vessel_agent_headers,
    create_dock_ticket_payload,
    create_landing_line_payload,
    create_vessel,
    create_catch_area,
    create_species,
    create_draft_quote,
    publish_quote,
    create_and_publish_quote,
    create_dock_ticket,
    land_ticket,
    get_ticket,
    add_landing_line,
    create_and_finalize_assessment,
)

OM = TEST_USERS["operations_manager_headers"]
DB = TEST_USERS["dock_buyer_headers"]


class TestDockLineSettlementDualVariant:
    """Provisional (declared grade, raw weight) vs final (assessed grade,
    yield-adjusted weight) settlement of the same landed line."""

    def test_provisional_and_final_amounts_differ_for_identical_weight(self, api):
        """PRD §3.3: "the line's `provisional_amount_cents` is its `landed_weight_kg` multiplied by the quote's `price_per_kg_cents`, rounded half up to whole cents."
        PRD §3.4: "On finalize, the line's `processed_weight_kg` is computed as the smaller of the raw `landed_weight_kg` and the product of `landed_weight_kg` multiplied by the assessment's `yield_pct`, by a condition factor, and by a processing factor, the result rounded half up to two decimal places."
        PRD §3.4: "the final amount is the `processed_weight_kg` multiplied by that quote's `price_per_kg_cents`, rounded half up to whole cents."
        PRD §3.3: "The ticket's `provisional_total_cents` is the sum of `provisional_amount_cents` over its non-voided lines, recomputed as lines are added or voided."
        PRD §3.4: "Back on the ticket, `final_total_cents` — the sum of `final_amount_cents` over lines with a `FINAL` assessment — is recomputed"

        Design: Difficulty/dual_variant_calc/dock_settlement_provisional_vs_final
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
        create_and_publish_quote(species["id"], grade="GRADE_B", price_per_kg_cents=950)

        ticket = create_dock_ticket(vessel["id"], area["id"])
        land_ticket(ticket["id"])
        line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                                landed_weight_kg=100.00)
        assert line["provisional_amount_cents"] == 120000, (
            "Provisional: 100.00 kg x 1200 cents/kg")

        assessment = create_and_finalize_assessment(line["id"], assessed_grade="GRADE_B",
                                                    yield_pct=0.90)
        line_after = get_success_data(api_client.get_landing_line(line["id"], OM))
        assert_kg(line_after["processed_weight_kg"], 87.30,
                  "processed (100.00 x 0.90 x 0.97 x 1.00)")
        assert line_after["final_amount_cents"] == 82935, (
            "Final: 87.30 kg x 950 cents/kg")
        assert line_after["provisional_amount_cents"] != line_after["final_amount_cents"]

        ticket_after = get_ticket(ticket["id"])
        assert ticket_after["provisional_total_cents"] == 120000
        assert ticket_after["final_total_cents"] == 82935

    def test_provisional_and_final_amounts_when_grade_upgraded(self, api):
        """PRD §3.4: "Because the final variant prices the assessed grade against the yield-adjusted weight while the provisional variant priced the declared grade against the raw landed weight, an unchanged landing can still settle for a different amount."
        PRD §3.4: "The condition factor is 1.00 for an assessed `GRADE_A`, 0.97 for `GRADE_B`, and 0.92 for `GRADE_C`; the processing factor is 1.00 when the line's `processing_type` is `WHOLE` and 0.85 when it is `FILLETED`."

        Design: Difficulty/dual_variant_calc/dock_settlement_provisional_vs_final
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
        create_and_publish_quote(species["id"], grade="GRADE_B", price_per_kg_cents=950)

        ticket = create_dock_ticket(vessel["id"], area["id"])
        land_ticket(ticket["id"])
        line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_B",
                                landed_weight_kg=40.00)
        assert line["provisional_amount_cents"] == 38000, (
            "Provisional prices the declared GRADE_B quote: 40.00 x 950")

        create_and_finalize_assessment(line["id"], assessed_grade="GRADE_A",
                                       yield_pct=1.00)
        line_after = get_success_data(api_client.get_landing_line(line["id"], OM))
        assert_kg(line_after["processed_weight_kg"], 40.00,
                  "GRADE_A condition factor 1.00 at yield 1.00 keeps full weight")
        assert line_after["final_amount_cents"] == 48000, (
            "Final prices the assessed GRADE_A quote: 40.00 x 1200")
        ticket_after = get_ticket(ticket["id"])
        assert ticket_after["provisional_total_cents"] == 38000
        assert ticket_after["final_total_cents"] == 48000


class TestVesselLandingWindow:
    """Half-open landing-window overlap semantics per vessel."""

    def test_adjacency_allowed_overlap_rejected_void_frees_window(self, api):
        """PRD §3.3: "One vessel cannot be in two places at once: the new window must not overlap the window of any other non-`VOIDED` ticket of the same vessel, where overlap is judged on half-open intervals — the start inclusive, the end exclusive — so that a window beginning exactly when another ends is adjacency, not overlap. A genuine overlap is rejected with `ERR_VESSEL_LANDING_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/vessel_landing_window_half_open_adjacency
        """
        vessel = create_vessel()
        area = create_catch_area()
        t1 = create_dock_ticket(vessel["id"], area["id"],
                                landing_start_at="2026-08-01T06:00:00Z",
                                landing_end_at="2026-08-01T10:00:00Z")

        adjacent = api_client.create_dock_ticket(
            create_dock_ticket_payload(
                vessel_id=vessel["id"], catch_area_id=area["id"],
                landing_start_at="2026-08-01T10:00:00Z",
                landing_end_at="2026-08-01T12:00:00Z"), DB)
        validate_success(adjacent, expected_status=201)

        overlapping = api_client.create_dock_ticket(
            create_dock_ticket_payload(
                vessel_id=vessel["id"], catch_area_id=area["id"],
                landing_start_at="2026-08-01T09:59:00Z",
                landing_end_at="2026-08-01T11:00:00Z"), DB)
        validate_error(overlapping, ApiErrorId.ERR_VESSEL_LANDING_OVERLAP)

        get_success_data(api_client.void_dock_ticket(t1["id"], OM))
        reissued = api_client.create_dock_ticket(
            create_dock_ticket_payload(
                vessel_id=vessel["id"], catch_area_id=area["id"],
                landing_start_at="2026-08-01T06:00:00Z",
                landing_end_at="2026-08-01T10:00:00Z"), DB)
        data = validate_success(reissued, expected_status=201)
        assert data["status"] == "DRAFT", (
            "A VOIDED ticket releases its window for the same vessel")

    def test_contained_window_rejected_other_vessel_unaffected(self, api):
        """PRD §3.3: "One vessel cannot be in two places at once: the new window must not overlap the window of any other non-`VOIDED` ticket of the same vessel, where overlap is judged on half-open intervals — the start inclusive, the end exclusive — so that a window beginning exactly when another ends is adjacency, not overlap. A genuine overlap is rejected with `ERR_VESSEL_LANDING_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/vessel_landing_window_half_open_adjacency
        """
        vessel_a = create_vessel()
        vessel_b = create_vessel()
        area = create_catch_area()
        create_dock_ticket(vessel_a["id"], area["id"],
                           landing_start_at="2026-08-01T06:00:00Z",
                           landing_end_at="2026-08-01T10:00:00Z")

        contained = api_client.create_dock_ticket(
            create_dock_ticket_payload(
                vessel_id=vessel_a["id"], catch_area_id=area["id"],
                landing_start_at="2026-08-01T07:00:00Z",
                landing_end_at="2026-08-01T08:00:00Z"), DB)
        validate_error(contained, ApiErrorId.ERR_VESSEL_LANDING_OVERLAP)

        other_vessel = api_client.create_dock_ticket(
            create_dock_ticket_payload(
                vessel_id=vessel_b["id"], catch_area_id=area["id"],
                landing_start_at="2026-08-01T06:00:00Z",
                landing_end_at="2026-08-01T10:00:00Z"), DB)
        validate_success(other_vessel, expected_status=201)


def test_ticket_create_ignores_client_supplied_system_fields(api):
    """PRD §3.3: "A new ticket starts in `DRAFT` with `regrade_count` at zero and both `provisional_total_cents` and `final_total_cents` at zero."
    PRD §2.4: "**`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix."

    Design: Corner/entities/entity_computed_and_system_field_input_ignored
    """
    vessel = create_vessel()
    area = create_catch_area()
    injected_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    payload = create_dock_ticket_payload(vessel_id=vessel["id"], catch_area_id=area["id"])
    payload.update({"status": "PAID", "provisional_total_cents": 999999,
                    "final_total_cents": 999999, "id": injected_id})
    data = validate_success(api_client.create_dock_ticket(payload, DB),
                            expected_status=201)
    assert data["status"] == "DRAFT", "Client-injected status must be ignored"
    assert data["regrade_count"] == 0
    assert data["provisional_total_cents"] == 0
    assert data["final_total_cents"] == 0
    assert is_valid_uuid(data["id"]) and data["id"] != injected_id, (
        "The server mints the id")


def test_landing_line_with_unknown_species_rejected(api):
    """PRD §2.8: "Only then are identifiers resolved: identifiers appearing in the URL path are validated in left-to-right order, followed by foreign-key references in the request body (`species_id`, `vessel_id`, `catch_area_id`, `dock_ticket_id`, `landing_line_id`, `customer_id`, `sales_order_id`, `order_line_id`, `inventory_lot_id`, `substitute_species_id`). An unknown identifier yields the corresponding 404: `ERR_VESSEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATCH_AREA_NOT_FOUND`, `ERR_SPECIES_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_IMPORT_DOC_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_SUBSTITUTION_NOT_FOUND`."

    Design: Corner/entities/entity_body_fk_unknown_species_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    ticket = create_dock_ticket(vessel["id"], area["id"])
    landed = land_ticket(ticket["id"])

    resp = api_client.create_landing_line(
        create_landing_line_payload(
            dock_ticket_id=ticket["id"], species_id=NON_EXISTENT_UUID,
            declared_grade="GRADE_A", landed_weight_kg=10.00,
            expected_dock_ticket_version=landed["version"]), DB)
    validate_error(resp, ApiErrorId.ERR_SPECIES_NOT_FOUND)
    assert get_ticket(ticket["id"])["version"] == landed["version"], (
        "A rejected line add must not advance the ticket version")


def test_vessel_agent_cannot_land_another_vessels_ticket(api):
    """PRD §2.1: "When `X-User-Role` is `VesselAgent`, `X-User-ID` is the `id` of the acting `Vessel`; ownership checks on any resource that references a vessel compare the resource's `vessel_id` foreign-key field to `X-User-ID`."
    PRD §2.1: "The ownership guard covers six operations — creating a dock ticket, marking a ticket landed, creating a sales order, submitting an order, cancelling an order, and adding an order line — and a breach is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/val_vessel_agent_cannot_land_others_ticket
    """
    vessel_a = create_vessel(vessel_name="FV Aurora", registration_number="REG-A")
    vessel_b = create_vessel(vessel_name="FV Borealis", registration_number="REG-B")
    area = create_catch_area()
    ticket = create_dock_ticket(vessel_b["id"], area["id"])

    resp = api_client.land_dock_ticket(
        ticket["id"], make_vessel_agent_headers(vessel_a["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert get_ticket(ticket["id"])["status"] == "DRAFT"

    landed = validate_success(api_client.land_dock_ticket(
        ticket["id"], make_vessel_agent_headers(vessel_b["id"])))
    assert landed["status"] == "LANDED"


def test_landing_window_end_equal_start_rejected(api):
    """PRD §3.3: "The end of the window must be strictly after its start, else `ERR_INVALID_LANDING_WINDOW` (400)."

    Design: Corner/validations/val_landing_window_inverted_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    resp = api_client.create_dock_ticket(
        create_dock_ticket_payload(
            vessel_id=vessel["id"], catch_area_id=area["id"],
            landing_start_at="2026-08-01T10:00:00Z",
            landing_end_at="2026-08-01T10:00:00Z"), DB)
    validate_error(resp, ApiErrorId.ERR_INVALID_LANDING_WINDOW)
    _, meta = validate_paginated(api_client.list_dock_tickets(OM))
    assert meta["total_count"] == 0


def test_settlement_uses_landing_date_quote_after_supersession(api):
    """PRD §3.2: "The **settlement price** selector — used for provisional and final settlement of landing lines — is deliberately historical: it matches the species, the applicable grade, and a `quote_date` equal to the calendar date of the ticket's landing start, and it accepts quotes in `PUBLISHED`, `SUPERSEDED`, or `EXPIRED` status, because any quote that once reached publication remains valid pricing for landings that occurred on its date."
    PRD §3.2: "Whenever a quote reaches `PUBLISHED`, the prior `PUBLISHED` quote for the same species and grade is automatically superseded to `SUPERSEDED`."

    Design: Corner/calculations/calc_settlement_uses_landing_date_quote_after_supersession
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    q1 = create_and_publish_quote(species["id"], quote_date="2026-08-01",
                                  price_per_kg_cents=1200)
    q2 = create_and_publish_quote(species["id"], quote_date="2026-08-02",
                                  price_per_kg_cents=1300)  # +8.33%: below the guard
    assert get_success_data(api_client.get_market_quote(q1["id"], OM))["status"] == "SUPERSEDED"

    ticket = create_dock_ticket(vessel["id"], area["id"],
                                landing_start_at="2026-08-01T06:00:00Z",
                                landing_end_at="2026-08-01T10:00:00Z")
    land_ticket(ticket["id"])
    line = add_landing_line(ticket["id"], species["id"], declared_grade="GRADE_A",
                            landed_weight_kg=100.00)
    assert line["provisional_amount_cents"] == 120000, (
        "The landing-date quote (1200, now SUPERSEDED) prices the line, "
        "not the currently published 1300")


def test_add_line_with_stale_ticket_version_rejected(api):
    """PRD §2.7: "Adding a landing line to a dock ticket requires `expected_dock_ticket_version` matching the target dock ticket's current `version`. Because successfully adding a line itself advances the ticket's `version`, a second writer holding an older reading is rejected with `ERR_STALE_VERSION`."
    PRD §3.3: "adding a line recomputes the ticket's provisional total and increments the ticket's `version` by one, so a stale reading is rejected with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting/occ_stale_ticket_version_on_line_add
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    landed = land_ticket(ticket["id"])
    stale_version = landed["version"]

    first = api_client.create_landing_line(
        create_landing_line_payload(
            dock_ticket_id=ticket["id"], species_id=species["id"],
            declared_grade="GRADE_A", landed_weight_kg=10.00,
            expected_dock_ticket_version=stale_version), DB)
    validate_success(first, expected_status=201)

    stale = api_client.create_landing_line(
        create_landing_line_payload(
            dock_ticket_id=ticket["id"], species_id=species["id"],
            declared_grade="GRADE_A", landed_weight_kg=5.00,
            expected_dock_ticket_version=stale_version), DB)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    lines, meta = validate_paginated(
        api_client.list_landing_lines(OM, params={"dock_ticket_id": ticket["id"]}))
    assert meta["total_count"] == 1, "The stale line add must not persist"

    replay = api_client.create_landing_line(
        create_landing_line_payload(
            dock_ticket_id=ticket["id"], species_id=species["id"],
            declared_grade="GRADE_A", landed_weight_kg=5.00,
            expected_dock_ticket_version=get_ticket(ticket["id"])["version"]), DB)
    validate_success(replay, expected_status=201)


def test_line_create_response_carries_computed_values_immediately(api):
    """PRD §3.3: "Each new line is provisionally settled on the spot."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.3: "The ticket's `provisional_total_cents` is the sum of `provisional_amount_cents` over its non-voided lines, recomputed as lines are added or voided."

    Design: Corner/consistency_model/consistency_immediate_mutation_visible_in_response
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])

    created = validate_success(api_client.create_landing_line(
        create_landing_line_payload(
            dock_ticket_id=ticket["id"], species_id=species["id"],
            declared_grade="GRADE_A", landed_weight_kg=100.00,
            expected_dock_ticket_version=get_ticket(ticket["id"])["version"]), DB),
        expected_status=201)
    assert created["provisional_amount_cents"] == 120000, (
        "The create response itself carries the computed provisional amount")

    ticket_after = get_ticket(ticket["id"])
    assert ticket_after["provisional_total_cents"] == 120000, (
        "The recomputed ticket total is visible on the very next read")
