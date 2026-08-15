"""Inspection holds, the condemn cascade, species substitution, and the
compliance gates around them."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    assert_kg,
    assert_lot_buckets,
    assert_instant_equal,
    create_species,
    create_and_publish_quote,
    create_customer,
    create_vessel,
    create_catch_area,
    create_dock_ticket,
    land_ticket,
    create_and_finalize_assessment,
    get_lot_for_line,
    setup_confirmed_order,
    get_order,
    get_order_line,
    get_lot,
    create_allocation,
    commit_allocation,
    create_inspection_hold,
    get_hold,
    create_import_document,
    create_shipment,
    create_substitution_approval_payload,
    setup_graded_lot,
    setup_lot_and_confirmed_order,
    setup_committed_allocation,
    add_landing_line,
    set_clock,
    get_species_version,
)

OM = TEST_USERS["operations_manager_headers"]
IP = TEST_USERS["inventory_planner_headers"]
GI = TEST_USERS["grading_inspector_headers"]


def _list_substitutions_for_line(order_line_id):
    data, _ = validate_paginated(
        api_client.list_substitution_approvals(OM,
                                               params={"order_line_id": order_line_id}))
    return data


class TestLotParallelDimensions:
    """lifecycle_status and hold_status move independently (PRD §2.9)."""

    def test_hold_release_and_freeze_leave_lifecycle_untouched(self, api):
        """PRD §2.9: "A lot is born `ACTIVE` and `CLEAR`, and the two dimensions move independently except where a workflow in §3 ties them together."
        PRD §3.7: "Freezing a lot — again an `InventoryPlanner` act, blocked while the lot is `ON_HOLD` with `ERR_LOT_ON_HOLD` — converts `storage_type` from `FRESH` to `FROZEN`, stamps `frozen_at` with the current time, and resets the clock: `expires_at` becomes the `frozen_at` instant plus the species' `frozen_shelf_life_days`, at day granularity, so a lot frozen for N days expires exactly N days after freezing."

        Design: Difficulty/non_linear_state_machine/inventory_lot_parallel_hold_and_lifecycle
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        lot_id = ctx["lot"]["id"]

        hold = create_inspection_hold(lot_id, reason="suspect temperature abuse",
                                      headers=OFFICER_1_HEADERS)
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "ACTIVE"
        assert lot["hold_status"] == "ON_HOLD"

        get_success_data(api_client.release_inspection_hold(hold["id"],
                                                            OFFICER_2_HEADERS))
        lot = get_lot(lot_id)
        assert lot["hold_status"] == "CLEAR"
        assert lot["lifecycle_status"] == "ACTIVE", "Hold traffic never moved lifecycle"

        set_clock("2026-08-02T00:00:00Z")
        frozen = validate_success(api_client.freeze_inventory_lot(lot_id, IP))
        assert frozen["storage_type"] == "FROZEN"
        assert_instant_equal(frozen["frozen_at"], "2026-08-02T00:00:00Z",
                             "frozen_at")
        assert_instant_equal(frozen["expires_at"], "2026-09-01T00:00:00Z",
                             "expires_at (30 frozen days from 2026-08-02)")
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "ACTIVE"
        assert_lot_buckets(lot, received=50.00, available=50.00)

    def test_frozen_clock_governs_expiry_after_freeze(self, api):
        """PRD §3.7: "Freezing a lot — again an `InventoryPlanner` act, blocked while the lot is `ON_HOLD` with `ERR_LOT_ON_HOLD` — converts `storage_type` from `FRESH` to `FROZEN`, stamps `frozen_at` with the current time, and resets the clock: `expires_at` becomes the `frozen_at` instant plus the species' `frozen_shelf_life_days`, at day granularity, so a lot frozen for N days expires exactly N days after freezing."
        PRD §3.8: "when an `ACTIVE` lot reaches its `expires_at`, its lifecycle transitions to `EXPIRED`, its available and reserved weight move into `spoiled_weight_kg`, but committed weight stays put until its order resolves."

        Design: Difficulty/non_linear_state_machine/inventory_lot_parallel_hold_and_lifecycle
        """
        ctx = setup_graded_lot(landed_weight_kg=50.00)
        lot_id = ctx["lot"]["id"]

        frozen = validate_success(api_client.freeze_inventory_lot(lot_id, IP))
        assert_instant_equal(frozen["frozen_at"], "2026-08-01T00:00:00Z",
                             "frozen_at")
        assert_instant_equal(frozen["expires_at"], "2026-08-31T00:00:00Z",
                             "expires_at")

        # The fresh clock would have expired on 2026-08-04; the frozen clock
        # expires exactly 30 days after freezing.
        set_clock("2026-08-30T00:00:00Z")
        assert get_lot(lot_id)["lifecycle_status"] == "ACTIVE"
        set_clock("2026-08-31T00:00:00Z")
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "EXPIRED"
        assert lot["storage_type"] == "FROZEN"
        assert_lot_buckets(lot, spoiled=50.00, available=0.00)


class TestCondemnCascade:
    """The depth-4 cascade out of POST /inspection-holds/{id}/condemn."""

    def test_condemn_releases_regresses_and_requests_substitution(self, api):
        """PRD §3.8: "The hold transitions to the terminal `CONDEMNED` state, the lot's `hold_status` becomes `CONDEMNED`, and its available, reserved, and committed weight all move into `condemned_weight_kg`. Every `RESERVED` or `COMMITTED` allocation on the lot is released, the affected order lines recompute their allocated and committed quantities, and any affected order in `FULFILLED` whose lines are no longer fully committed regresses to `CONFIRMED`. Then the substitution cascade runs: for each order line left short whose `allow_substitution` flag is true, the system auto-creates a substitution request through the substitute selector below."
        PRD §3.8: "Candidate species must differ from the line's current species, share its `substitution_group` key, have at least one inventory lot with lifecycle `ACTIVE` and hold `CLEAR`, and have a standing `PUBLISHED` quote for the line's `requested_grade` dated on or before the current logical date."
        PRD §3.8: "An auto-created **SubstitutionApproval** starts in `REQUESTED` with `auto_created` set to true, `requested_by_user_id` left empty, `original_species_id` captured from the shorted line, and `order_line_id` pointing at that line."

        Design: Difficulty/transitive_cascade/condemn_cascade_releases_allocations_and_requests_substitution
        """
        cod = setup_graded_lot(
            landed_weight_kg=100.00, assessed_grade="GRADE_B", yield_pct=0.90,
            quote_prices={"GRADE_A": 1200, "GRADE_B": 950},
            species_overrides={"species_code": "COD"})
        pollock = setup_graded_lot(
            landed_weight_kg=50.00, quote_prices={"GRADE_A": 1000},
            species_overrides={"species_code": "POLLOCK",
                               "common_name": "Pollock", "labeling_name": "Pollock"},
            vessel=cod["vessel"], catch_area=cod["catch_area"],
            landing_start_at="2026-08-01T10:00:00Z",
            landing_end_at="2026-08-01T12:00:00Z")

        customer = create_customer()
        order_ctx = setup_confirmed_order(
            customer, [{"species_id": cod["species"]["id"], "requested_qty_kg": 20.00,
                        "allow_substitution": True}])
        order_id, line_id = order_ctx["order"]["id"], order_ctx["lines"][0]["id"]
        allocation = create_allocation(order_id, line_id, cod["lot"]["id"],
                                       qty_kg=20.00)
        commit_allocation(allocation["id"])
        assert get_order(order_id)["status"] == "FULFILLED"

        hold = create_inspection_hold(cod["lot"]["id"], reason="listeria screen",
                                      headers=OFFICER_1_HEADERS)
        validate_success(api_client.condemn_inspection_hold(hold["id"],
                                                            OFFICER_1_HEADERS))

        lot = get_lot(cod["lot"]["id"])
        assert lot["hold_status"] == "CONDEMNED"
        assert_lot_buckets(lot, condemned=87.30, available=0.00, committed=0.00)

        assert get_success_data(
            api_client.get_allocation(allocation["id"], OM))["status"] == "RELEASED"
        line = get_order_line(line_id)
        assert_kg(line["committed_qty_kg"], 0.00, "committed after condemn")
        assert_kg(line["allocated_qty_kg"], 0.00, "allocated after condemn")
        assert get_order(order_id)["status"] == "CONFIRMED", (
            "The order regresses when its line is no longer fully committed")

        subs = _list_substitutions_for_line(line_id)
        assert len(subs) == 1, "Exactly one auto-created substitution request"
        sub = subs[0]
        assert sub["status"] == "REQUESTED"
        assert sub["auto_created"] is True
        assert sub["substitute_species_id"] == pollock["species"]["id"], (
            "Cheapest eligible in-group species with an ACTIVE, CLEAR lot and a "
            "standing quote")
        assert sub["original_species_id"] == cod["species"]["id"]

    def test_condemn_without_eligible_substitute_creates_no_record(self, api):
        """PRD §3.8: "When no candidate qualifies, no substitution record is created and the cascade continues silently."
        PRD §3.8: "Every `RESERVED` or `COMMITTED` allocation on the lot is released, the affected order lines recompute their allocated and committed quantities, and any affected order in `FULFILLED` whose lines are no longer fully committed regresses to `CONFIRMED`."

        Design: Difficulty/transitive_cascade/condemn_cascade_releases_allocations_and_requests_substitution
        """
        ctx = setup_committed_allocation(line_qty_kg=20.00,
                                         lot_landed_weight_kg=100.00,
                                         allow_substitution=True,
                                         lot_kwargs={
                                             "assessed_grade": "GRADE_B",
                                             "yield_pct": 0.90,
                                             "quote_prices": {"GRADE_A": 1200,
                                                              "GRADE_B": 950}})
        assert get_order(ctx["order"]["id"])["status"] == "FULFILLED"

        hold = create_inspection_hold(ctx["lot"]["id"], reason="listeria screen",
                                      headers=OFFICER_1_HEADERS)
        validate_success(api_client.condemn_inspection_hold(hold["id"],
                                                            OFFICER_1_HEADERS))

        assert get_order(ctx["order"]["id"])["status"] == "CONFIRMED"
        assert _list_substitutions_for_line(ctx["line_o"]["id"]) == [], (
            "No other species exists, so the selector stays silent")


def test_second_hold_on_same_lot_rejected(api):
    """PRD §3.8: "A `ComplianceOfficer` may place an **InspectionHold** on a lot whose lifecycle is `ACTIVE` and whose hold dimension is `CLEAR` — anything else draws `ERR_LOT_INVALID_STATE` (409) — and only when no other `PLACED` hold exists on that lot, else `ERR_HOLD_ALREADY_ACTIVE` (409)."

    Design: Corner/validations/val_second_hold_on_same_lot_rejected
    """
    ctx = setup_graded_lot(landed_weight_kg=50.00)
    create_inspection_hold(ctx["lot"]["id"], reason="first", headers=OFFICER_1_HEADERS)

    resp = api_client.create_inspection_hold(
        {"inventory_lot_id": ctx["lot"]["id"], "reason": "second"},
        OFFICER_2_HEADERS)
    # PRD §3.8 names ERR_HOLD_ALREADY_ACTIVE for a second PLACED hold, but a
    # PLACED hold implies hold_status=ON_HOLD, and §2.8's pinned ordering puts
    # the from-state gate (ERR_LOT_INVALID_STATE, priority 6) ahead of the
    # one-active-hold constraint (priority 9) — both error ids are faithful.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_HOLD_ALREADY_ACTIVE,
                                    ApiErrorId.ERR_LOT_INVALID_STATE])

    _, meta = validate_paginated(api_client.list_inspection_holds(
        OM, params={"inventory_lot_id": ctx["lot"]["id"], "status": "PLACED"}))
    assert meta["total_count"] == 1


def test_hold_release_requires_a_different_officer(api):
    """PRD §3.8: "Release returns the lot's `hold_status` to `CLEAR` and stamps the releasing officer as `resolved_by_user_id` with `resolved_at` set, but the releasing officer must differ from the officer who placed the hold; a same-user release is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403)."
    PRD §2.10: "An inspection hold must be released by a `ComplianceOfficer` other than the user who placed it, as recorded in its `placed_by_user_id`."

    Design: Corner/rbac/rbac_sod_hold_release_same_officer_rejected
    """
    ctx = setup_graded_lot(landed_weight_kg=50.00)
    hold = create_inspection_hold(ctx["lot"]["id"], reason="audit",
                                  headers=OFFICER_1_HEADERS)

    resp = api_client.release_inspection_hold(hold["id"], OFFICER_1_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    assert get_hold(hold["id"])["status"] == "PLACED"
    assert get_lot(ctx["lot"]["id"])["hold_status"] == "ON_HOLD"

    released = validate_success(
        api_client.release_inspection_hold(hold["id"], OFFICER_2_HEADERS))
    assert released["status"] == "RELEASED"
    assert released["resolved_by_user_id"] == "off_2"
    assert get_lot(ctx["lot"]["id"])["hold_status"] == "CLEAR"


class TestSubstitutionDecisions:
    """Request, approval gates, and application of species substitution."""

    def _confirmed_line_with_substitution(self, substitute_price,
                                          substitute_overrides=None,
                                          allow_substitution=True):
        """COD line (locked 1200) plus an in-group substitute species."""
        cod = create_species(species_code="COD")
        create_and_publish_quote(cod["id"], grade="GRADE_A", price_per_kg_cents=1200)
        substitute = create_species(**(substitute_overrides or
                                       {"species_code": "POLLOCK",
                                        "common_name": "Pollock",
                                        "labeling_name": "Pollock"}))
        if substitute_price is not None:
            create_and_publish_quote(substitute["id"], grade="GRADE_A",
                                     price_per_kg_cents=substitute_price)
        customer = create_customer()
        line_spec = {"species_id": cod["id"], "requested_qty_kg": 20.00}
        if allow_substitution:
            line_spec["allow_substitution"] = True
        order_ctx = setup_confirmed_order(customer, [line_spec])
        return cod, substitute, order_ctx

    def test_apply_reprices_line_and_credits_order(self, api):
        """PRD §3.8: "Application rewrites the line: its `species_id` becomes the substitute species, and its `unit_price_cents` is replaced by the substitute's standing quote price selected per §3.2 as of the application date. The customer is credited for the difference: `price_credit_cents` is the old locked unit price less the new unit price, multiplied by the line's `requested_qty_kg`, rounded half up to whole cents. The line's `line_total_cents` is then recomputed under the per-line rounding rule — requested quantity times the new unit price times one minus the customer's `discount_pct`, rounded half up — and the order's `total_cents` is reduced by the credit, equivalently restated as the sum of the repriced line totals."
        PRD §3.8: "The record lands in the terminal `APPLIED` state."

        Design: Corner/endpoints/ep_apply_substitution_reprices_order
        """
        cod, substitute, order_ctx = self._confirmed_line_with_substitution(1000)
        order_id, line_id = order_ctx["order"]["id"], order_ctx["lines"][0]["id"]
        assert get_order(order_id)["total_cents"] == 24000

        sub = get_success_data(api_client.create_substitution_approval(
            create_substitution_approval_payload(
                order_line_id=line_id, substitute_species_id=substitute["id"]), IP))
        get_success_data(api_client.approve_substitution(sub["id"],
                                                         OFFICER_1_HEADERS))
        applied = validate_success(api_client.apply_substitution(sub["id"], IP))
        assert applied["status"] == "APPLIED"
        assert applied["price_credit_cents"] == 4000, "(1200 - 1000) x 20.00"

        line = get_order_line(line_id)
        assert line["species_id"] == substitute["id"]
        assert line["unit_price_cents"] == 1000
        assert line["line_total_cents"] == 20000
        assert get_order(order_id)["total_cents"] == 20000, "24000 - 4000"

    def test_substitution_request_requires_line_permission(self, api):
        """PRD §3.8: "Substitution may also be requested manually: an `InventoryPlanner` requests one with the `order_line_id` and the proposed `substitute_species_id`, provided the line's `allow_substitution` flag is true — a line without that permission rejects the request with `ERR_SUBSTITUTION_NOT_ALLOWED` (422)."
        PRD §3.6: "and an `allow_substitution` flag, defaulting to false, that licenses species substitution on the line."

        Design: Corner/validations/val_substitution_not_allowed_rejected
        """
        _, substitute, order_ctx = self._confirmed_line_with_substitution(
            None, allow_substitution=False)
        resp = api_client.create_substitution_approval(
            create_substitution_approval_payload(
                order_line_id=order_ctx["lines"][0]["id"],
                substitute_species_id=substitute["id"]), IP)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED)
        assert _list_substitutions_for_line(order_ctx["lines"][0]["id"]) == []

    def test_substitute_from_another_group_rejected(self, api):
        """PRD §3.8: "The proposed substitute must share the original species' `substitution_group`, else `ERR_SUBSTITUTION_GROUP_MISMATCH` (422)."

        Design: Corner/validations/val_substitution_group_mismatch_rejected
        """
        _, shrimp, order_ctx = self._confirmed_line_with_substitution(
            800, substitute_overrides={"species_code": "SHRIMP",
                                       "common_name": "White Shrimp",
                                       "labeling_name": "Shrimp",
                                       "substitution_group": "CRUSTACEAN"})
        sub = get_success_data(api_client.create_substitution_approval(
            create_substitution_approval_payload(
                order_line_id=order_ctx["lines"][0]["id"],
                substitute_species_id=shrimp["id"]), IP))

        resp = api_client.approve_substitution(sub["id"], OFFICER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_GROUP_MISMATCH)
        assert get_success_data(
            api_client.get_substitution_approval(sub["id"], OM))["status"] == "REQUESTED"

    def test_cites_substitute_without_cleared_document_rejected(self, api):
        """PRD §3.8: "And when the substitute species is flagged `requires_cites`, a `CLEARED` CITES import document for that species must already exist, else `ERR_LABELING_NONCOMPLIANT` (422), because the market `labeling_name` on the substitute is only lawful with its paperwork in place."

        Design: Corner/errors/err_labeling_noncompliant_on_cites_substitute
        """
        _, tuna, order_ctx = self._confirmed_line_with_substitution(
            1000, substitute_overrides={"species_code": "TUNA",
                                        "common_name": "Bluefin Tuna",
                                        "labeling_name": "Bluefin Tuna",
                                        "requires_cites": True})
        sub = get_success_data(api_client.create_substitution_approval(
            create_substitution_approval_payload(
                order_line_id=order_ctx["lines"][0]["id"],
                substitute_species_id=tuna["id"]), IP))

        resp = api_client.approve_substitution(sub["id"], OFFICER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_LABELING_NONCOMPLIANT)
        assert get_success_data(
            api_client.get_substitution_approval(sub["id"], OM))["status"] == "REQUESTED"

    def test_substitute_priced_above_locked_price_rejected(self, api):
        """PRD §3.8: "The substitute's standing price for the line's requested grade must not exceed the line's locked `unit_price_cents`, else `ERR_SUBSTITUTION_PRICE_INCREASE` (422) — a substitution may save the house money, never cost it."

        Design: Corner/errors/err_substitution_price_increase_rejected
        """
        _, substitute, order_ctx = self._confirmed_line_with_substitution(1300)
        sub = get_success_data(api_client.create_substitution_approval(
            create_substitution_approval_payload(
                order_line_id=order_ctx["lines"][0]["id"],
                substitute_species_id=substitute["id"]), IP))

        resp = api_client.approve_substitution(sub["id"], OFFICER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_PRICE_INCREASE)
        assert get_success_data(
            api_client.get_substitution_approval(sub["id"], OM))["status"] == "REQUESTED"


def test_initial_states_on_create(api):
    """PRD §3.3: "A new ticket starts in `DRAFT` with `regrade_count` at zero and both `provisional_total_cents` and `final_total_cents` at zero."
    PRD §3.6: "The order starts in `DRAFT` with `total_cents` at zero and `confirmed_at` unset."
    PRD §3.5: "A new document starts in `DRAFT` with `submitted_by_user_id` and `reviewed_by_user_id` empty and `resubmit_count` at zero."
    PRD §3.8: "The request names the `inventory_lot_id` and a `reason`; the hold starts in `PLACED`, stamps `placed_by_user_id` with the officer's `X-User-ID` and `placed_at` with the current time, leaves `resolved_by_user_id` empty and `resolved_at` unset, and flips the lot's `hold_status` to `ON_HOLD`."
    PRD §3.7: "A new shipment starts in `QUOTED` with `actual_weight_kg`, `volume_m3`, `chargeable_weight_kg`, `provisional_freight_cents`, and `final_freight_cents` all at zero."
    PRD §3.8: "The record starts in `REQUESTED`, captures the line's current species as `original_species_id`, stamps the requester as `requested_by_user_id`, sets `auto_created` to false, and starts with `price_credit_cents` at zero and `decided_by_user_id` empty."

    Design: Corner/state_machines/sm_initial_states_on_create
    """
    ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00, allow_substitution=True,
                                        lot_kwargs={
                                            "assessed_grade": "GRADE_B",
                                            "yield_pct": 0.90,
                                            "quote_prices": {"GRADE_A": 1200,
                                                             "GRADE_B": 950}})
    pollock = create_species(species_code="POLLOCK")

    shipment = get_success_data(api_client.create_shipment(
        {"sales_order_id": ctx["order"]["id"], "mode": "TRUCK",
         "booked_weight_kg": 10.00, "temp_zone": "CHILLED"},
        TEST_USERS["logistics_coordinator_headers"]))
    assert shipment["status"] == "QUOTED"
    assert_kg(shipment["actual_weight_kg"], 0.00, "actual at create")
    assert_kg(shipment["volume_m3"], 0.00, "volume at create")
    assert shipment["provisional_freight_cents"] == 0
    assert shipment["final_freight_cents"] == 0

    sub = get_success_data(api_client.create_substitution_approval(
        create_substitution_approval_payload(
            order_line_id=ctx["line_o"]["id"],
            substitute_species_id=pollock["id"]), IP))
    assert sub["status"] == "REQUESTED"
    assert sub["auto_created"] is False
    assert sub["price_credit_cents"] == 0
    assert sub["requested_by_user_id"] == "ip_0"
    assert sub["original_species_id"] == ctx["species"]["id"]

    doc = create_import_document(ctx["ticket"]["id"], ctx["species"]["id"],
                                 doc_type="HEALTH_CERT", reference_number="HC-001")
    assert doc["status"] == "DRAFT"
    assert doc["resubmit_count"] == 0
    assert doc["submitted_by_user_id"] == ""

    hold = create_inspection_hold(ctx["lot"]["id"], reason="spot check",
                                  headers=OFFICER_1_HEADERS)
    assert hold["status"] == "PLACED"
    assert hold["placed_by_user_id"] == "off_1"
    assert hold["resolved_by_user_id"] == ""


def test_invalid_from_state_sweep_remaining_machines(api):
    """PRD §3.2: "When an `OperationsManager` publishes a quote that is no longer in `DRAFT`, the request is rejected with `ERR_QUOTE_INVALID_STATE` (409)."
    PRD §3.4: "It requires the assessment to be in `DRAFT` — else `ERR_ASSESSMENT_INVALID_STATE` (409) — and the owning ticket to be in `LANDED` — else `ERR_TICKET_INVALID_STATE`."
    PRD §3.5: "a document not in `SUBMITTED` draws `ERR_IMPORT_DOC_INVALID_STATE`"
    PRD §3.8: "Resolution comes in two forms, both by a `ComplianceOfficer` acting on a `PLACED` hold — anything else draws `ERR_HOLD_INVALID_STATE` (409)."
    PRD §3.8: "Decision belongs to a `ComplianceOfficer` acting on a `REQUESTED` record — any other state draws `ERR_SUBSTITUTION_INVALID_STATE` (409)."

    Design: Corner/errors/err_invalid_from_state_sweep_remaining_machines
    """
    # Landing chain with a second, never-assessed line so the ticket stays
    # LANDED after the first assessment finalizes (isolating the assessment
    # state check below).
    vessel = create_vessel()
    area = create_catch_area()
    species = create_species(species_code="COD")
    published_quote = create_and_publish_quote(species["id"], grade="GRADE_A",
                                               price_per_kg_cents=1200)
    ticket = create_dock_ticket(vessel["id"], area["id"])
    land_ticket(ticket["id"])
    line1 = add_landing_line(ticket["id"], species["id"], landed_weight_kg=50.00)
    add_landing_line(ticket["id"], species["id"], landed_weight_kg=5.00)
    assessment = create_and_finalize_assessment(line1["id"],
                                                assessed_grade="GRADE_A",
                                                yield_pct=1.00)
    ticket_now = get_success_data(api_client.get_dock_ticket(ticket["id"], OM))
    assert ticket_now["status"] == "LANDED", (
        "Line 2 has no assessment, so the ticket must not have graded")
    lot = get_lot_for_line(line1["id"])

    # A substitution carried all the way to APPLIED.
    pollock = create_species(species_code="POLLOCK")
    create_and_publish_quote(pollock["id"], grade="GRADE_A",
                             price_per_kg_cents=1000)
    customer = create_customer()
    order_ctx = setup_confirmed_order(
        customer, [{"species_id": species["id"], "requested_qty_kg": 20.00,
                    "allow_substitution": True}])
    sub = get_success_data(api_client.create_substitution_approval(
        create_substitution_approval_payload(
            order_line_id=order_ctx["lines"][0]["id"],
            substitute_species_id=pollock["id"]), IP))
    get_success_data(api_client.approve_substitution(sub["id"], OFFICER_1_HEADERS))
    get_success_data(api_client.apply_substitution(sub["id"], IP))

    doc = create_import_document(ticket["id"], species["id"],
                                 doc_type="HEALTH_CERT", reference_number="HC-001")
    hold = create_inspection_hold(lot["id"], reason="audit",
                                  headers=OFFICER_1_HEADERS)
    get_success_data(api_client.release_inspection_hold(hold["id"],
                                                        OFFICER_2_HEADERS))

    # 1. Publish an already-PUBLISHED quote.
    resp = api_client.publish_market_quote(
        published_quote["id"],
        {"expected_species_version": get_species_version(species["id"])}, OM)
    validate_error(resp, ApiErrorId.ERR_QUOTE_INVALID_STATE)

    # 2. Finalize an already-FINAL assessment (ticket still LANDED via line 2).
    resp = api_client.finalize_grade_assessment(assessment["id"], GI)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE)

    # 3. Clear a DRAFT document.
    resp = api_client.clear_import_document(doc["id"], OFFICER_1_HEADERS)
    validate_error(resp, ApiErrorId.ERR_IMPORT_DOC_INVALID_STATE)

    # 4. Release an already-RELEASED hold.
    resp = api_client.release_inspection_hold(hold["id"], OFFICER_2_HEADERS)
    validate_error(resp, ApiErrorId.ERR_HOLD_INVALID_STATE)

    # 5. Approve an already-APPLIED substitution.
    resp = api_client.approve_substitution(sub["id"], OFFICER_1_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_INVALID_STATE)
