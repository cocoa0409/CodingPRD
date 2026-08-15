"""Settlement, payment, void and re-grade cascades on dock tickets, and the
import-document lifecycle gating settlement of imported species."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_kg,
    assert_lot_buckets,
    create_vessel,
    create_catch_area,
    create_species,
    create_and_publish_quote,
    create_dock_ticket,
    land_ticket,
    get_ticket,
    add_landing_line,
    create_assessment,
    finalize_assessment,
    create_and_finalize_assessment,
    get_lot,
    get_vessel,
    create_customer,
    setup_confirmed_order,
    create_allocation,
    create_import_document,
    clear_document,
    setup_graded_lot,
)

OM = TEST_USERS["operations_manager_headers"]
DB = TEST_USERS["dock_buyer_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestRegradeCycle:
    """The GRADED -> LANDED re-grade loop with its hard cap of two."""

    def test_two_regrades_then_cap(self, api):
        """PRD §3.4: "The privilege is capped: when the ticket's `regrade_count` has already reached two, the request is rejected with `ERR_REGRADE_LIMIT_EXCEEDED` (409); otherwise the count increments by one."
        PRD §3.4: "Every `FINAL` assessment of the ticket's lines transitions to `SUPERSEDED` — since superseded assessments no longer count as active, each line may then receive a new assessment. Every inventory lot derived from the ticket's lines transitions to `RECALLED`, with its remaining available, reserved, and committed weight moving into `recalled_weight_kg`."

        Design: Difficulty/non_linear_state_machine/dock_ticket_regrade_cycle
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        ticket_id, line_id = ctx["ticket"]["id"], ctx["line"]["id"]
        ga1_id, lot1_id = ctx["assessment"]["id"], ctx["lot"]["id"]
        assert ctx["ticket"]["status"] == "GRADED"

        first = validate_success(api_client.request_regrade(ticket_id, DB))
        assert first["status"] == "LANDED"
        assert first["regrade_count"] == 1
        assert get_success_data(api_client.get_grade_assessment(ga1_id, OM))["status"] == "SUPERSEDED"
        lot1 = get_lot(lot1_id)
        assert lot1["lifecycle_status"] == "RECALLED"
        assert_lot_buckets(lot1, recalled=50.00, available=0.00)

        ga2 = create_and_finalize_assessment(line_id, assessed_grade="GRADE_A",
                                             yield_pct=1.00)
        assert get_ticket(ticket_id)["status"] == "GRADED"

        second = validate_success(api_client.request_regrade(ticket_id, DB))
        assert second["status"] == "LANDED"
        assert second["regrade_count"] == 2

        ga3 = create_and_finalize_assessment(line_id, assessed_grade="GRADE_A",
                                             yield_pct=1.00)
        assert get_ticket(ticket_id)["status"] == "GRADED"

        resp = api_client.request_regrade(ticket_id, DB)
        validate_error(resp, ApiErrorId.ERR_REGRADE_LIMIT_EXCEEDED)
        assert get_ticket(ticket_id)["status"] == "GRADED", (
            "A rejected third re-grade leaves the ticket untouched")

    def test_regraded_line_accepts_fresh_assessment_and_new_lot(self, api):
        """PRD §3.4: "A `DockBuyer` or `OperationsManager` may request a re-grade of a `GRADED` ticket — a ticket in any other state draws `ERR_TICKET_INVALID_STATE` — returning it to `LANDED` for a fresh round of assessments."
        PRD §3.4: "Finalization also births an **InventoryLot**."

        Design: Difficulty/non_linear_state_machine/dock_ticket_regrade_cycle
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        ticket_id, line_id = ctx["ticket"]["id"], ctx["line"]["id"]
        lot1_id = ctx["lot"]["id"]

        # The fresh assessment grades GRADE_B, and final settlement prices the
        # assessed grade on the landing day (PRD §3.4), so a GRADE_B quote
        # dated on the landing day must exist before the second finalize.
        create_and_publish_quote(ctx["species"]["id"], grade="GRADE_B",
                                 price_per_kg_cents=950)

        validate_success(api_client.request_regrade(ticket_id, DB))
        fresh = create_assessment(line_id, assessed_grade="GRADE_B", yield_pct=0.50)
        assert fresh["status"] == "DRAFT", "A superseded line accepts a new assessment"
        finalize_assessment(fresh["id"])
        assert get_ticket(ticket_id)["status"] == "GRADED"

        # The line now has two lots (the recalled original and the one birthed
        # by the second finalize, PRD §3.4); both share the frozen clock's
        # created_at, so select the new lot explicitly rather than relying on
        # list tie order.
        lots_data, _ = validate_paginated(
            api_client.list_inventory_lots(OM, params={"landing_line_id": line_id}))
        new_lots = [l for l in lots_data if l["id"] != lot1_id]
        assert len(new_lots) == 1, (
            "Finalization births exactly one new InventoryLot for the line")
        new_lot = new_lots[0]
        assert new_lot["lifecycle_status"] == "ACTIVE"
        assert_kg(new_lot["received_weight_kg"], 24.25,
                  "50.00 x 0.50 (yield) x 0.97 (GRADE_B) x 1.00 (WHOLE)")
        assert get_lot(lot1_id)["lifecycle_status"] == "RECALLED"


class TestSettleRequiresClearedImportDocuments:
    """The import-clearance gate in front of settlement."""

    def test_settle_blocked_until_health_certificate_cleared(self, api):
        """PRD §3.5: "First, for every line whose species is flagged `is_import`, the required documents for that ticket and species must all be `CLEARED`: a health certificate always, and a CITES document additionally when the species is flagged `requires_cites`; missing clearances reject the settlement with `ERR_IMPORT_DOCS_NOT_CLEARED` (409)."
        PRD §3.5: "A successful settlement moves the ticket to `SETTLED` and credits the vessel: the ticket's `final_total_cents` is added to the vessel's `payable_balance_cents`."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_cleared_import_documents
        """
        ctx = setup_graded_lot(landed_weight_kg=40.00,
                               species_overrides={"species_code": "SHRIMP",
                                                  "common_name": "White Shrimp",
                                                  "labeling_name": "Shrimp",
                                                  "substitution_group": "CRUSTACEAN",
                                                  "fresh_shelf_life_hours": 48,
                                                  "frozen_shelf_life_days": 60,
                                                  "is_import": True},
                               quote_prices={"GRADE_A": 1500})
        ticket_id = ctx["ticket"]["id"]
        vessel_id = ctx["vessel"]["id"]
        doc = create_import_document(ticket_id, ctx["species"]["id"],
                                     doc_type="HEALTH_CERT", reference_number="HC-001")

        resp = api_client.settle_dock_ticket(ticket_id, OM)
        validate_error(resp, ApiErrorId.ERR_IMPORT_DOCS_NOT_CLEARED)
        assert get_ticket(ticket_id)["status"] == "GRADED"
        assert get_vessel(vessel_id)["payable_balance_cents"] == 0

        clear_document(doc["id"], OFFICER_1_HEADERS, OFFICER_2_HEADERS)
        settled = validate_success(api_client.settle_dock_ticket(ticket_id, OM))
        assert settled["status"] == "SETTLED"
        assert get_vessel(vessel_id)["payable_balance_cents"] == 60000, (
            "40.00 kg x 1500 cents/kg credited at settlement")

    def test_cites_document_required_when_species_flagged(self, api):
        """PRD §3.5: "First, for every line whose species is flagged `is_import`, the required documents for that ticket and species must all be `CLEARED`: a health certificate always, and a CITES document additionally when the species is flagged `requires_cites`; missing clearances reject the settlement with `ERR_IMPORT_DOCS_NOT_CLEARED` (409)."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_cleared_import_documents
        """
        ctx = setup_graded_lot(landed_weight_kg=40.00,
                               species_overrides={"species_code": "SHRIMP",
                                                  "substitution_group": "CRUSTACEAN",
                                                  "fresh_shelf_life_hours": 48,
                                                  "frozen_shelf_life_days": 60,
                                                  "is_import": True,
                                                  "requires_cites": True},
                               quote_prices={"GRADE_A": 1500})
        ticket_id = ctx["ticket"]["id"]
        health = create_import_document(ticket_id, ctx["species"]["id"],
                                        doc_type="HEALTH_CERT",
                                        reference_number="HC-001")
        clear_document(health["id"], OFFICER_1_HEADERS, OFFICER_2_HEADERS)

        resp = api_client.settle_dock_ticket(ticket_id, OM)
        validate_error(resp, ApiErrorId.ERR_IMPORT_DOCS_NOT_CLEARED,)

        cites = create_import_document(ticket_id, ctx["species"]["id"],
                                       doc_type="CITES", reference_number="CT-001")
        clear_document(cites["id"], OFFICER_1_HEADERS, OFFICER_2_HEADERS)
        settled = validate_success(api_client.settle_dock_ticket(ticket_id, OM))
        assert settled["status"] == "SETTLED"
        assert get_vessel(ctx["vessel"]["id"])["payable_balance_cents"] == 60000


class TestTicketVoidCascade:
    """Voiding a ticket recalls its lots and releases their allocations."""

    def test_void_settled_ticket_recalls_lot_releases_allocation_reverses_payable(self, api):
        """PRD §3.5: "Voiding unwinds everything the ticket created. Every landing line's `voided` flag is set to true, removing the line from the provisional-total sum. Every inventory lot derived from the ticket's lines transitions to `RECALLED`, its remaining available, reserved, and committed weight moving into `recalled_weight_kg`. Each `RESERVED` or `COMMITTED` allocation on those lots is released, the affected order lines recompute their allocated and committed quantities, and the affected orders re-evaluate the fulfillment regression. And when the voided ticket had been `SETTLED`, the vessel's ledger is unwound too: the ticket's `final_total_cents` is subtracted from `payable_balance_cents`, the exact reversal of the settlement credit."

        Design: Difficulty/transitive_cascade/ticket_void_recalls_lots_and_releases_allocations
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        ticket_id, line_id, lot_id = (ctx["ticket"]["id"], ctx["line"]["id"],
                                      ctx["lot"]["id"])
        get_success_data(api_client.settle_dock_ticket(ticket_id, OM))
        assert get_vessel(ctx["vessel"]["id"])["payable_balance_cents"] == 60000

        customer = create_customer()
        order_ctx = setup_confirmed_order(
            customer, [{"species_id": ctx["species"]["id"], "requested_qty_kg": 10.00}])
        allocation = create_allocation(order_ctx["order"]["id"],
                                       order_ctx["lines"][0]["id"], lot_id,
                                       qty_kg=10.00)

        validate_success(api_client.void_dock_ticket(ticket_id, OM))
        ticket_after = get_ticket(ticket_id)
        assert ticket_after["status"] == "VOIDED"
        assert get_success_data(api_client.get_landing_line(line_id, OM))["voided"] is True

        lot_after = get_lot(lot_id)
        assert lot_after["lifecycle_status"] == "RECALLED"
        assert_lot_buckets(lot_after, recalled=50.00, available=0.00, reserved=0.00)

        assert get_success_data(
            api_client.get_allocation(allocation["id"], OM))["status"] == "RELEASED"
        line_after = get_success_data(
            api_client.get_order_line(order_ctx["lines"][0]["id"], OM))
        assert_kg(line_after["allocated_qty_kg"], 0.00, "allocated after release")
        assert get_vessel(ctx["vessel"]["id"])["payable_balance_cents"] == 0, (
            "The settle credit of 60000 is exactly reversed")

    def test_void_graded_ticket_recalls_lot_and_zeroes_provisional_total(self, api):
        """PRD §3.5: "A ticket may also be voided by an `OperationsManager` from any of `DRAFT`, `LANDED`, `GRADED`, or `SETTLED` — from `PAID` or an already-`VOIDED` ticket the request draws `ERR_TICKET_INVALID_STATE` — landing it in the terminal `VOIDED` state."
        PRD §3.5: "Every landing line's `voided` flag is set to true, removing the line from the provisional-total sum. Every inventory lot derived from the ticket's lines transitions to `RECALLED`, its remaining available, reserved, and committed weight moving into `recalled_weight_kg`."

        Design: Difficulty/transitive_cascade/ticket_void_recalls_lots_and_releases_allocations
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        ticket_id = ctx["ticket"]["id"]

        validate_success(api_client.void_dock_ticket(ticket_id, OM))
        ticket_after = get_ticket(ticket_id)
        assert ticket_after["status"] == "VOIDED"
        assert ticket_after["provisional_total_cents"] == 0, (
            "Voided lines leave the provisional-total sum")
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["lifecycle_status"] == "RECALLED"
        assert_lot_buckets(lot_after, recalled=50.00)
        assert get_vessel(ctx["vessel"]["id"])["payable_balance_cents"] == 0, (
            "Never settled, so nothing to reverse")


class TestVesselPayableConservation:
    """The vessel ledger: settle credits, pay debits, void reverses."""

    def test_settle_then_void_restores_pre_settle_balance(self, api):
        """PRD §3.1: "A new vessel's `payable_balance_cents` starts at zero — it is the running ledger of what the house owes the vessel, credited at settlement, debited at payment, and reversed on a void."
        PRD §3.5: "And when the voided ticket had been `SETTLED`, the vessel's ledger is unwound too: the ticket's `final_total_cents` is subtracted from `payable_balance_cents`, the exact reversal of the settlement credit."

        Design: Difficulty/compensating_invariant/vessel_payable_conservation_through_settle_void
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        vessel_id = ctx["vessel"]["id"]
        assert get_vessel(vessel_id)["payable_balance_cents"] == 0

        get_success_data(api_client.settle_dock_ticket(ctx["ticket"]["id"], OM))
        assert get_vessel(vessel_id)["payable_balance_cents"] == 60000

        get_success_data(api_client.void_dock_ticket(ctx["ticket"]["id"], OM))
        assert get_vessel(vessel_id)["payable_balance_cents"] == 0, (
            "Settle + void conserves the vessel ledger with no drift")
        assert get_ticket(ctx["ticket"]["id"])["status"] == "VOIDED"

    def test_pay_drains_balance_and_paid_ticket_is_terminal(self, api):
        """PRD §3.5: "An `OperationsManager` pays a `SETTLED` ticket — any other state draws `ERR_TICKET_INVALID_STATE` — moving it to the terminal `PAID` state and subtracting the ticket's `final_total_cents` from the vessel's `payable_balance_cents`."
        PRD §3.5: "A ticket may also be voided by an `OperationsManager` from any of `DRAFT`, `LANDED`, `GRADED`, or `SETTLED` — from `PAID` or an already-`VOIDED` ticket the request draws `ERR_TICKET_INVALID_STATE` — landing it in the terminal `VOIDED` state."

        Design: Difficulty/compensating_invariant/vessel_payable_conservation_through_settle_void
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        vessel_id, ticket_id = ctx["vessel"]["id"], ctx["ticket"]["id"]

        get_success_data(api_client.settle_dock_ticket(ticket_id, OM))
        assert get_vessel(vessel_id)["payable_balance_cents"] == 60000

        paid = validate_success(api_client.pay_dock_ticket(ticket_id, OM))
        assert paid["status"] == "PAID"
        assert get_vessel(vessel_id)["payable_balance_cents"] == 0

        resp = api_client.void_dock_ticket(ticket_id, OM)
        validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE)
        assert get_ticket(ticket_id)["status"] == "PAID"


class TestImportDocumentCycle:
    """Import documents: submit / reject / resubmit with segregation of duties."""

    def test_resubmission_then_clear_with_sod_gate(self, api):
        """PRD §3.5: "A `REJECTED` document may be resubmitted through the same action, returning to `SUBMITTED` with `resubmit_count` incremented by one and the new submitter stamped."
        PRD §3.5: "Clearance moves a `SUBMITTED` document to `CLEARED` and stamps the clearing officer as `reviewed_by_user_id`, but the clearing officer must differ from the submitter — a same-user clearance is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), and a document not in `SUBMITTED` draws `ERR_IMPORT_DOC_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/import_document_resubmission_cycle
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="SHRIMP", substitution_group="CRUSTACEAN",
                                 is_import=True)
        ticket = create_dock_ticket(vessel["id"], area["id"])
        doc = create_import_document(ticket["id"], species["id"],
                                     doc_type="HEALTH_CERT", reference_number="HC-001")

        submitted = validate_success(
            api_client.submit_import_document(doc["id"], OFFICER_1_HEADERS))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "off_1"

        rejected = validate_success(
            api_client.reject_import_document(doc["id"], OFFICER_2_HEADERS))
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(
            api_client.submit_import_document(doc["id"], OFFICER_1_HEADERS))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["resubmit_count"] == 1

        resp = api_client.clear_import_document(doc["id"], OFFICER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert get_success_data(
            api_client.get_import_document(doc["id"], OM))["status"] == "SUBMITTED"

        cleared = validate_success(
            api_client.clear_import_document(doc["id"], OFFICER_2_HEADERS))
        assert cleared["status"] == "CLEARED"
        assert cleared["reviewed_by_user_id"] == "off_2"

    def test_resubmit_count_increments_on_each_rejected_cycle(self, api):
        """PRD §3.5: "A `REJECTED` document may be resubmitted through the same action, returning to `SUBMITTED` with `resubmit_count` incremented by one and the new submitter stamped."
        PRD §3.5: "`CLEARED` is terminal."

        Design: Difficulty/non_linear_state_machine/import_document_resubmission_cycle
        """
        vessel = create_vessel()
        area = create_catch_area()
        species = create_species(species_code="SHRIMP", substitution_group="CRUSTACEAN",
                                 is_import=True)
        ticket = create_dock_ticket(vessel["id"], area["id"])
        doc = create_import_document(ticket["id"], species["id"],
                                     doc_type="HEALTH_CERT", reference_number="HC-001")

        get_success_data(api_client.submit_import_document(doc["id"], OFFICER_1_HEADERS))
        get_success_data(api_client.reject_import_document(doc["id"], OFFICER_2_HEADERS))
        first = get_success_data(
            api_client.submit_import_document(doc["id"], OFFICER_1_HEADERS))
        assert first["resubmit_count"] == 1

        get_success_data(api_client.reject_import_document(doc["id"], OFFICER_2_HEADERS))
        second = get_success_data(
            api_client.submit_import_document(doc["id"], OFFICER_2_HEADERS))
        assert second["resubmit_count"] == 2
        assert second["submitted_by_user_id"] == "off_2", (
            "Each resubmission stamps its own submitter")

        cleared = get_success_data(
            api_client.clear_import_document(doc["id"], OFFICER_1_HEADERS))
        assert cleared["status"] == "CLEARED"
        assert cleared["reviewed_by_user_id"] == "off_1"


def test_land_on_voided_ticket_rejected(api):
    """PRD §3.3: "When the vessel comes alongside, the `DockBuyer` or the vessel's `VesselAgent` marks the ticket landed, transitioning it from `DRAFT` to `LANDED`; a ticket in any other state is rejected with `ERR_TICKET_INVALID_STATE` (409), and the transition increments the ticket's `version` by one."

    Design: Corner/state_machines/sm_terminal_lockdown_voided_ticket_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    ticket = create_dock_ticket(vessel["id"], area["id"])
    get_success_data(api_client.void_dock_ticket(ticket["id"], OM))

    resp = api_client.land_dock_ticket(ticket["id"], DB)
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE)
    assert get_ticket(ticket["id"])["status"] == "VOIDED"


def test_settle_from_landed_rejected(api):
    """PRD §3.5: "With grading complete, an `OperationsManager` settles a `GRADED` ticket — any other state draws `ERR_TICKET_INVALID_STATE`."

    Design: Corner/state_machines/sm_settle_from_landed_rejected
    """
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    add_landing_line(ticket["id"], species["id"], landed_weight_kg=50.00)

    resp = api_client.settle_dock_ticket(ticket["id"], OM)
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE)
    assert get_ticket(ticket["id"])["status"] == "LANDED"
    assert get_vessel(vessel["id"])["payable_balance_cents"] == 0, (
        "A rejected settle never touches the vessel ledger")
