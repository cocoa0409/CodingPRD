"""Deaccession governance: board segregation of duties, the cooling-off sweep,
in-treatment blocking, SALE hammer prices and proceeds rounding, and the
finalization cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_proposal,
    catalog_item,
    create_accessioned,
    create_collection,
    create_item,
    create_order,
    create_published_finding_aid,
    create_proposal,
    create_zone,
    get_collection,
    get_item,
    get_proposal,
    make_board_officer_headers,
    make_item_available,
    make_registrar_headers,
    proposal_to_board_review,
    set_clock,
    setup_approved_proposal,
    setup_approved_request,
    setup_cooled_off_proposal,
    setup_in_treatment_item,
    setup_project_with_ticket,
    setup_confirmed_appointment,
    get_appointment,
    get_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = {"X-User-ID": "reg_1", "X-User-Role": "Registrar", "Content-Type": "application/json"}
RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}


def _three_pending_items():
    """Zone + collection + ACCESSIONED accession + three PENDING_CATALOG items.
    Returns (collection, [i1, i2, i3])."""
    zone = create_zone()
    collection = create_collection(zone["id"])
    accession, _deed = create_accessioned(lot_appraised_value_cents=3000)
    items = [create_item(accession["id"], collection["id"], title=f"Dup {k}")
             for k in (1, 2, 3)]
    return collection, items


class TestSegregationOfDuties:

    def test_segregation_of_duties_on_deaccession_approve(self):
        """PRD §3.8: "Approval enforces segregation of duties — the approving
        officer's `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` — and refuses to approve while any proposed
        item is `IN_TREATMENT` (`ERR_ITEMS_IN_TREATMENT`). Approval stamps
        `approved_by_user_id` and `approved_at` (the logical timestamp) and
        computes `finalize_not_before` as `approved_at` plus a 30-day
        cooling-off period."

        Design: Corner/errors/segregation_of_duties_on_deaccession_approve
        """
        _collection, items = _three_pending_items()
        proposal = create_proposal([items[0]["id"]],
                                   disposal_method="DESTRUCTION",
                                   justification="mold", proposer_id="reg_1")
        proposal_to_board_review(proposal["id"], "reg_1")

        # The proposer cannot approve their own proposal.
        resp = api_client.approve_proposal(
            proposal["id"], make_board_officer_headers("reg_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_proposal(proposal["id"])["status"] == "BOARD_REVIEW"

        approved = approve_proposal(proposal["id"], "board_1")
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "board_1"
        # approved_at is the 2026-08-01T00:00:00Z startup clock; +30 days.
        assert str(approved["finalize_not_before"]).startswith(
            "2026-08-31T00:00:00"), (
            f"finalize_not_before must be approved_at + 30 days; got "
            f"{approved['finalize_not_before']}")


class TestItemsInTreatmentGate:

    def test_items_in_treatment_block_board_approve(self):
        """PRD §3.8: "Approval enforces segregation of duties — the approving
        officer's `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` — and refuses to approve while any proposed
        item is `IN_TREATMENT` (`ERR_ITEMS_IN_TREATMENT`)."
        PRD §3.2: "an item in `IN_TREATMENT` cannot be deaccessioned at all,
        because approval and finalization are both blocked while any proposed
        item is in treatment."

        Design: Corner/errors/items_in_treatment_block_board_approve
        """
        ctx = setup_in_treatment_item()
        assert get_item(ctx["item"]["id"])["status"] == "IN_TREATMENT"

        proposal = create_proposal([ctx["item"]["id"]],
                                   disposal_method="DESTRUCTION",
                                   justification="mold", proposer_id="reg_1")
        proposal_to_board_review(proposal["id"], "reg_1")

        resp = api_client.approve_proposal(
            proposal["id"], make_board_officer_headers("board_1"))
        validate_error(resp, ApiErrorId.ERR_ITEMS_IN_TREATMENT)
        assert get_proposal(proposal["id"])["status"] == "BOARD_REVIEW"


class TestCoolingOffSweep:

    def test_scheduled_cooling_off_sweep(self):
        """PRD §3.8: "Calling finalize while the proposal is still `APPROVED` —
        that is, while the logical now has not yet reached
        `finalize_not_before` — fails with `ERR_COOLING_OFF_NOT_ELAPSED`."
        PRD §2.5: "Setting the clock also performs a scheduled sweep: every
        deaccession proposal in `APPROVED` status whose `finalize_not_before`
        instant has been reached or passed by the new logical time transitions
        to `COOLED_OFF`. The sweep performs no other transitions, and moving the
        clock backward never reverses a transition that has already occurred."

        Design: Corner/complexity_layers/scheduled_cooling_off_sweep
        """
        _collection, items = _three_pending_items()
        proposal = setup_approved_proposal([items[0]["id"]],
                                           disposal_method="TRANSFER",
                                           proposer_id="reg_1",
                                           officer_id="board_1")
        assert proposal["status"] == "APPROVED"

        # Immediately after approval the cooling-off has not elapsed.
        resp1 = api_client.finalize_proposal(proposal["id"], {}, REG)
        validate_error(resp1, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED)

        # One day before the instant: still APPROVED, finalize still refused.
        set_clock("2026-08-30T00:00:00Z")
        assert get_proposal(proposal["id"])["status"] == "APPROVED"
        resp2 = api_client.finalize_proposal(proposal["id"], {}, REG)
        validate_error(resp2, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED)

        # At exactly finalize_not_before the sweep moves it to COOLED_OFF.
        set_clock("2026-08-31T00:00:00Z")
        assert get_proposal(proposal["id"])["status"] == "COOLED_OFF"

        finalized = validate_success(
            api_client.finalize_proposal(proposal["id"], {}, REG))
        assert finalized["status"] == "FINALIZED"
        assert get_item(items[0]["id"])["status"] == "DEACCESSIONED"


class TestSaleProceeds:

    def test_sale_proceeds_round_per_item_then_sum(self):
        """PRD §3.8: "For a sale, `proceeds_cents` is computed by rounding each
        line separately — each hammer price less the ten percent commission,
        rounded half up to whole cents per item — and then summing the rounded
        lines. The per-item-round-then-sum order is pinned: hammer prices of
        999, 555, and 333 cents yield 1699 cents of proceeds under the pinned
        order, whereas summing first and rounding once would yield 1698; the
        latter is forbidden."
        PRD §3.8: "**Bubble-up:** a collection whose `item_count` reaches zero
        through link 1 deaccessions itself (`ACTIVE → DEACCESSIONED`), and each
        of its `PUBLISHED` finding aids becomes `RETIRED`, with
        `published_finding_aid_present` recomputed."

        Design: Difficulty/combinatorial_formula/deaccession_proceeds_per_item_rounding
        """
        collection, items = _three_pending_items()
        proposal = setup_cooled_off_proposal(
            [it["id"] for it in items], disposal_method="SALE")

        finalized = validate_success(api_client.finalize_proposal(
            proposal["id"],
            {"hammer_prices": [
                {"item_id": items[0]["id"], "price_cents": 999},
                {"item_id": items[1]["id"], "price_cents": 555},
                {"item_id": items[2]["id"], "price_cents": 333}]},
            REG))
        # round_half_up(999*0.9)=899, round_half_up(555*0.9)=500,
        # round_half_up(333*0.9)=300; 899 + 500 + 300 = 1699.
        assert finalized["proceeds_cents"] == 1699, (
            f"per-item rounding then sum must give 1699; got "
            f"{finalized['proceeds_cents']}")
        assert finalized["proceeds_cents"] != 1698, (
            "1698 is the forbidden sum-then-round value")
        assert finalized["status"] == "FINALIZED"

        for it in items:
            assert get_item(it["id"])["status"] == "DEACCESSIONED"
        # The collection's last item left: bubble-up deaccessions it.
        assert get_collection(collection["id"])["status"] == "DEACCESSIONED"

    def test_sale_half_cent_rounds_half_up(self):
        """PRD §3.8: "For a sale, `proceeds_cents` is computed by rounding each
        line separately — each hammer price less the ten percent commission,
        rounded half up to whole cents per item — and then summing the rounded
        lines."
        PRD §2.9: "Every fee and proceeds computation rounds **half up** to
        whole cents, and rounding steps are pinned per calculation in §3"

        Design: Difficulty/combinatorial_formula/deaccession_proceeds_per_item_rounding
        """
        _collection, items = _three_pending_items()
        proposal = setup_cooled_off_proposal([items[0]["id"]],
                                             disposal_method="SALE")
        finalized = validate_success(api_client.finalize_proposal(
            proposal["id"],
            {"hammer_prices": [{"item_id": items[0]["id"],
                                "price_cents": 555}]},
            REG))
        # 555 * 0.90 = 499.5 -> 500 (half up, not to-even).
        assert finalized["proceeds_cents"] == 500, (
            f"499.5 must round half up to 500; got "
            f"{finalized['proceeds_cents']}")


class TestHammerPrices:

    def test_sale_finalize_requires_complete_hammer_prices(self):
        """PRD §3.8: "From `COOLED_OFF`, the registrar finalizes the proposal
        into the terminal `FINALIZED` state; finalization re-checks that no
        proposed item is `IN_TREATMENT` (`ERR_ITEMS_IN_TREATMENT`) and, for a
        `SALE` proposal, requires `hammer_prices` — an array pairing each
        proposed `item_id` with its `price_cents`, covering every proposed item
        exactly once, else `ERR_HAMMER_PRICE_MISSING`."

        Design: Corner/errors/sale_finalize_requires_complete_hammer_prices
        """
        _collection, items = _three_pending_items()
        proposal = setup_cooled_off_proposal(
            [items[0]["id"], items[1]["id"]], disposal_method="SALE")

        # Only one of the two proposed items priced: nothing finalizes.
        resp = api_client.finalize_proposal(
            proposal["id"],
            {"hammer_prices": [{"item_id": items[0]["id"],
                                "price_cents": 999}]},
            REG)
        validate_error(resp, ApiErrorId.ERR_HAMMER_PRICE_MISSING)
        assert resp.status_code == 422
        assert get_proposal(proposal["id"])["status"] == "COOLED_OFF"
        assert get_item(items[0]["id"])["status"] == "PENDING_CATALOG"

        finalized = validate_success(api_client.finalize_proposal(
            proposal["id"],
            {"hammer_prices": [
                {"item_id": items[0]["id"], "price_cents": 999},
                {"item_id": items[1]["id"], "price_cents": 555}]},
            REG))
        assert finalized["status"] == "FINALIZED"
        # round_half_up(999*0.9)=899 + round_half_up(555*0.9)=500.
        assert finalized["proceeds_cents"] == 1399


class TestFinalizeCascade:

    def _setup_cascade_scenario(self):
        """Single-item collection with a PUBLISHED aid, an APPROVED request +
        CONFIRMED appointment, a QUEUED ticket, and a QUOTED order — then a
        COOLED_OFF TRANSFER proposal over the item."""
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned(lot_appraised_value_cents=9000)
        aid = create_published_finding_aid(collection["id"])
        item = create_item(accession["id"], collection["id"], title="Banner")
        catalog_item(item["id"], condition_grade="FAIR",
                     appraised_value_cents=12000, format="ARTIFACT")
        make_item_available(item["id"])
        researcher, request, appointment = setup_confirmed_appointment(
            item["id"], scheduled_date="2026-08-10", start_time="10:00",
            end_time="12:00", seats=1)
        _project, ticket = setup_project_with_ticket(item["id"],
                                                     project_name="Digitize")
        order = create_order(request["id"], researcher["id"], [item["id"]],
                             page_estimate=10)
        proposal = setup_cooled_off_proposal(
            [item["id"]], disposal_method="TRANSFER",
            justification="Returns to donor institution")
        return {
            "collection": collection, "aid": aid, "item": item,
            "researcher": researcher, "request": request,
            "appointment": appointment, "ticket": ticket, "order": order,
            "proposal": proposal,
        }

    def test_finalize_cascades_items_requests_appointments(self):
        """PRD §3.8: "**Link 1 — items:** every proposed item in
        `PENDING_CATALOG`, `CATALOGED`, `AVAILABLE`, `FLAGGED_CONSERVATION`, or
        `ZONE_HOLD` becomes `DEACCESSIONED`, and each affected collection's
        `item_count` decreases accordingly. **Link 2 — requests:** every
        research request in `SUBMITTED`, `IN_REVIEW`, or `APPROVED` whose
        `item_ids` intersect the deaccessioned set becomes `DENIED`, with
        `decision_reason` recorded as `AUTO_DEACCESSION`. **Link 3 —
        appointments:** every appointment in `CONFIRMED` or `NEEDS_RESCHEDULE`
        whose research request was denied in link 2 becomes `CANCELLED`."

        Design: Difficulty/transitive_cascade/deaccession_finalize_cascade
        """
        ctx = self._setup_cascade_scenario()
        finalized = validate_success(api_client.finalize_proposal(
            ctx["proposal"]["id"], {}, REG))
        assert finalized["status"] == "FINALIZED"

        assert get_item(ctx["item"]["id"])["status"] == "DEACCESSIONED"

        request = validate_success(
            api_client.get_research_request(ctx["request"]["id"], RRS))
        assert request["status"] == "DENIED"
        assert request["decision_reason"] == "AUTO_DEACCESSION"

        assert get_appointment(ctx["appointment"]["id"])["status"] == "CANCELLED"

    def test_finalize_fans_out_to_tickets_orders_and_bubbles_up(self):
        """PRD §3.8: "**Ticket fan-out:** every digitization ticket in
        `QUEUED`, `CLAIMED`, `IN_CAPTURE`, or `QC_REVIEW` whose item was
        deaccessioned becomes `CANCELLED`, with each project's
        `active_ticket_count` adjusted for the tickets that were active.
        **Order fan-out:** every reproduction order in `QUOTED` or `APPROVED`
        whose `item_ids` intersect the deaccessioned set becomes `CANCELLED`;
        orders in `INVOICED`, `PAID`, or `DELIVERED` are untouched — pinned.
        **Bubble-up:** a collection whose `item_count` reaches zero through
        link 1 deaccessions itself (`ACTIVE → DEACCESSIONED`), and each of its
        `PUBLISHED` finding aids becomes `RETIRED`, with
        `published_finding_aid_present` recomputed."
        PRD §3.8: "For the other three disposal methods `hammer_prices` is not
        required and `proceeds_cents` stays null."

        Design: Difficulty/transitive_cascade/deaccession_finalize_cascade
        """
        ctx = self._setup_cascade_scenario()
        finalized = validate_success(api_client.finalize_proposal(
            ctx["proposal"]["id"], {}, REG))
        assert finalized["status"] == "FINALIZED"
        assert finalized["proceeds_cents"] is None, (
            "TRANSFER disposal computes no proceeds")

        assert get_ticket(ctx["ticket"]["id"])["status"] == "CANCELLED"
        order = validate_success(
            api_client.get_reproduction_order(ctx["order"]["id"], RRS))
        assert order["status"] == "CANCELLED"

        collection = get_collection(ctx["collection"]["id"])
        assert collection["item_count"] == 0
        assert collection["status"] == "DEACCESSIONED"

        aids, _meta = validate_paginated(
            api_client.list_finding_aids(
                RRS, params={"collection_id": ctx["collection"]["id"]}))
        by_id = {a["id"]: a for a in aids}
        assert by_id[ctx["aid"]["id"]]["status"] == "RETIRED"
