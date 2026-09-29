"""Request identity, role admission, resource ownership, decision authority,
segregation of duties, and the fixed order of the screening ladder."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    add_order_line,
    attach_document,
    book_appointment,
    build_user_headers,
    create_buyer,
    create_draft_order,
    create_draft_producer,
    create_dock_appointment_payload,
    create_dock_slot,
    create_listed_product,
    create_producer_payload,
    create_rejection_claim_payload,
    create_dock_slot_payload,
    dock_slot_version,
    make_buyer_headers,
    make_compliance_officer_headers,
    make_hub_admin_headers,
    make_board_director_headers,
    make_producer_headers,
    onboard_active_producer,
    propose_cycle,
    publish_offer_payload,
    read_buyer,
    read_cycle,
    read_dock_slot,
    read_order,
    read_producer,
    read_product,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRequestIdentity:
    def test_an_unrecognised_role_value_is_not_authenticated(self, api):
        """PRD 2.1: "The role value must be one of exactly five strings —
        `HubAdmin`, `ComplianceOfficer`, `Producer`, `Buyer`, `BoardDirector` —
        and any other value, however plausible, is likewise rejected with
        `ERR_UNAUTHENTICATED` rather than a permission error, because an
        unrecognised role is not an identity the hub can authenticate at all."

        Design: Corner/rbac/unknown_role_header_returns_unauthenticated
        """
        resp = api.create_producer(
            create_producer_payload(), build_user_headers("aud-1", "Auditor")
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_an_empty_user_id_header_is_not_authenticated(self, api):
        """PRD 2.1: "Every request to the API carries two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the capacity
        that principal is acting in. Both must be present and non-empty; a
        request missing either, or supplying an empty value for either, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
        """
        resp = api.create_producer(
            create_producer_payload(), build_user_headers("", "HubAdmin")
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestRoleAdmission:
    def test_a_producer_may_not_run_the_aggregation_waterfall(self, api):
        """PRD 2.1: "Once the role is recognised, it must appear in the set of
        roles the target operation admits; if it does not, the request fails
        with `ERR_FORBIDDEN_ROLE` (HTTP 403). Section 4 lists the admitted roles
        for every operation."
        PRD 3.5: "A hub administrator runs it against an order that is still
        `DRAFT` and that carries at least one demand line; an order in any later
        fulfillment state, or one with no lines at all, is refused with
        `ERR_INVALID_ORDER_STATE`."

        Design: Corner/rbac/producer_role_cannot_run_order_aggregation
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        create_listed_product(pid, quantity_offered=100)
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=60)

        resp = api.aggregate_order(order["id"], make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        assert read_order(order["id"])["fulfillment_status"] == "DRAFT"
        _, meta = validate_paginated(
            api.list_allocations(HUB, params={"order_line_id": line["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_board_director_may_not_open_a_cross_dock_door(self, api):
        """PRD 2.1: "Once the role is recognised, it must appear in the set of
        roles the target operation admits; if it does not, the request fails
        with `ERR_FORBIDDEN_ROLE` (HTTP 403). Section 4 lists the admitted roles
        for every operation."
        PRD 2.1: "A `BoardDirector` is an elected board member whose sole write
        capability is the vote that ratifies or rejects a proposed patronage
        cycle."

        Design: Corner/rbac/board_director_cannot_create_dock_slots
        """
        payload = create_dock_slot_payload(
            door_code="D9", pallet_capacity=10, temp_setpoint_c=2.0
        )
        payload.pop("sanitation_buffer_minutes")

        resp = api.create_dock_slot(payload, make_board_director_headers("director-7"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


class TestResourceOwnership:
    def test_a_producer_may_not_publish_an_offer_on_another_farms_item(self, api):
        """PRD 2.1: "When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of
        the acting Producer record; ownership checks on any resource that
        references a producer compare that resource's producer foreign key to
        `X-User-ID`, so a `Producer` may submit or resubmit only its own
        application, attach documents only to its own onboarding file, create
        and re-offer only catalog items whose `producer_id` is its own, and book
        dock appointments only under its own `producer_id`."

        Design: Corner/rbac/producer_cannot_publish_offers_on_another_producers_product
        """
        set_clock(CLOCK_BASE)
        first = onboard_active_producer()
        second = onboard_active_producer(
            legal_name="Stony Creek Dairy",
            region_code="ALL",
            contact_email="sc@example.org",
            verifier_user_id="co-verify-2",
            approver_user_id="co-approve-8",
        )
        product = create_listed_product(first["producer_id"], quantity_offered=100)

        resp = api.publish_offer(
            product["id"],
            publish_offer_payload(product["version"], quantity_offered=5),
            make_producer_headers(second["producer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        unchanged = read_product(product["id"])
        assert unchanged["quantity_offered"] == 100
        assert unchanged["status"] == "LISTED"

    def test_ownership_is_screened_before_the_payment_state_rule(self, api):
        """PRD 2.8: "Requests are screened in a fixed order, and the **first**
        check that fails determines the response. This ordering is a contract,
        not an implementation detail: when a request violates two rules at once,
        the earlier rule's error is the one the caller sees."
        PRD 2.8: "7. Resource ownership — for the two entity-backed roles,
        `X-User-ID` equals the owning entity's id, else
        `ERR_NOT_RESOURCE_OWNER`. This applies to submitting an application,
        attaching a document, creating a product, publishing an offer, booking a
        dock appointment, opening an order, adding a line, applying a payment,
        filing a claim, and adjudicating a claim."
        PRD 2.8: "11. Payment admissibility — an instalment is applied only to
        an order whose settlement dimension is `INVOICED` or `PARTIALLY_PAID`,
        else `ERR_ORDER_NOT_INVOICED`."

        Design: Corner/validations/ownership_check_precedes_settlement_state_check_on_foreign_order
        """
        scenario = setup_scenario(stage="delivered")
        stranger = create_buyer(legal_name="Northside Hospital")

        resp = api.create_payment(
            scenario["order_id"],
            {"amount_cents": 1000},
            make_buyer_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        assert read_order(scenario["order_id"])["paid_total_cents"] == 0


class TestDecisionAuthority:
    def test_a_compliance_officer_may_not_issue_a_suspend_decision(self, api):
        """PRD 3.1: "`APPROVE` and `REQUEST_CHANGES` are the compliance
        officer's; `SUSPEND`, `REINSTATE` and `TERMINATE` belong to hub
        operations. A compliance officer attempting to suspend a member, or a
        hub administrator attempting to approve one, is refused with
        `ERR_DECISION_ROLE_MISMATCH` — the caller is permitted at the review
        capability but not for that decision."

        Design: Corner/rbac/compliance_officer_cannot_issue_a_suspend_decision
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        product = create_listed_product(pid, quantity_offered=100)

        resp = api.review_producer(
            pid, {"decision": "SUSPEND"}, make_compliance_officer_headers("co-verify-1")
        )
        validate_error(resp, ApiErrorId.ERR_DECISION_ROLE_MISMATCH.value, 403)

        producer = read_producer(pid)
        assert producer["onboarding_status"] == "ACTIVE"
        assert producer["suspension_count"] == 0
        assert read_product(product["id"])["status"] == "LISTED"

    def test_a_buyer_may_not_approve_a_rejection_claim(self, api):
        """PRD 3.8: "A compliance officer may `APPROVE` or `DENY`; the buyer that
        owns the claim's order may `WITHDRAW` it, and only that buyer, since a
        withdrawal by any other user id is refused with
        `ERR_NOT_RESOURCE_OWNER`. A decision outside the acting role's authority
        is refused with `ERR_DECISION_ROLE_MISMATCH`, and an officer who tries
        to adjudicate a claim they themselves filed is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/buyer_cannot_issue_an_approve_decision_on_a_rejection_claim
        """
        scenario = setup_scenario(stage="invoiced")
        buyer_headers = make_buyer_headers(scenario["buyer_id"])
        claim = validate_success(
            api.create_rejection_claim(
                create_rejection_claim_payload(
                    scenario["allocation_id"],
                    quantity_rejected=5,
                    reason_code="DAMAGE",
                ),
                buyer_headers,
            ),
            201,
        )

        resp = api.adjudicate_rejection_claim(
            claim["id"], {"decision": "APPROVE"}, buyer_headers
        )
        validate_error(resp, ApiErrorId.ERR_DECISION_ROLE_MISMATCH.value, 403)

        claims, _ = validate_paginated(
            api.list_allocation_rejection_claims(scenario["allocation_id"], HUB)
        )
        assert claims[0]["status"] == "FILED"
        assert read_order(scenario["order_id"])["credit_memo_cents"] == 0
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 124200


class TestSegregationOfDuties:
    def test_the_verifying_officer_may_not_admit_the_same_member(self, api):
        """PRD 2.9: "A compliance officer may not approve a membership
        application if that same user id appears as the
        `adjudicated_by_user_id` on any document of that producer that currently
        stands verified — the officer who checked the paperwork is not the
        officer who admits the member."

        Design: Corner/rbac/document_verifier_cannot_approve_the_same_producers_application
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer()
        pid = producer["id"]
        docs = [
            attach_document(pid, "GAP_AUDIT"),
            attach_document(pid, "LIABILITY_INSURANCE"),
            attach_document(pid, "HACCP_PLAN"),
        ]
        validate_success(api.submit_application(pid, make_producer_headers(pid)))
        verifier = make_compliance_officer_headers("co-verify-1")
        for doc in docs:
            validate_success(
                api.adjudicate_document(doc["id"], {"decision": "VERIFY"}, verifier)
            )

        resp = api.review_producer(pid, {"decision": "APPROVE"}, verifier)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        approved = validate_success(
            api.review_producer(
                pid, {"decision": "APPROVE"},
                make_compliance_officer_headers("co-approve-9"),
            )
        )
        assert approved["onboarding_status"] == "ACTIVE"
        assert read_producer(pid)["food_safety_tier"] == "TIER_BASIC"

    def test_the_proposer_of_a_cycle_may_not_ratify_it(self, api):
        """PRD 2.9: "A board director may not ratify or reject a patronage cycle
        whose `proposed_by_user_id` equals their own user id."
        PRD 2.8: "Requests are screened in a fixed order, and the **first**
        check that fails determines the response. This ordering is a contract,
        not an implementation detail: when a request violates two rules at once,
        the earlier rule's error is the one the caller sees."

        Design: Corner/rbac/cycle_proposer_cannot_ratify_their_own_patronage_cycle
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        assert read_producer(onboarded["producer_id"])["patronage_volume_cents"] == 0
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=500000)

        resp = api.ratify_patronage_cycle(
            cycle["id"], {"decision": "RATIFY"},
            make_board_director_headers("hub-admin-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        unchanged = read_cycle(cycle["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["ratified_by_user_id"] is None

    def test_the_filer_of_a_claim_may_not_adjudicate_it(self, api):
        """PRD 2.9: "And a claims adjudicator may not approve or deny a
        rejection claim whose `filed_by_user_id` equals their own user id."
        PRD 3.8: "A filed claim enters `FILED` with `filed_by_user_id` stamped
        from the acting user."

        Design: Corner/rbac/claim_filer_cannot_adjudicate_their_own_rejection_claim
        """
        scenario = setup_scenario(stage="invoiced")
        claim = validate_success(
            api.create_rejection_claim(
                create_rejection_claim_payload(
                    scenario["allocation_id"],
                    quantity_rejected=5,
                    reason_code="DAMAGE",
                ),
                make_hub_admin_headers("ops-user-4"),
            ),
            201,
        )
        assert claim["filed_by_user_id"] == "ops-user-4"

        resp = api.adjudicate_rejection_claim(
            claim["id"], {"decision": "APPROVE"},
            make_compliance_officer_headers("ops-user-4"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        claims, _ = validate_paginated(
            api.list_allocation_rejection_claims(scenario["allocation_id"], HUB)
        )
        assert claims[0]["status"] == "FILED"
        assert read_order(scenario["order_id"])["credit_memo_cents"] == 0
        assert read_producer(scenario["producer_id"])["shrink_charge_cents"] == 0
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 124200


class TestLadderPrecedence:
    def test_the_payment_state_rung_beats_the_overpayment_rung(self, api):
        """PRD 2.8: "Requests are screened in a fixed order, and the **first**
        check that fails determines the response. This ordering is a contract,
        not an implementation detail: when a request violates two rules at once,
        the earlier rule's error is the one the caller sees."
        PRD 2.8: "11. Payment admissibility — an instalment is applied only to
        an order whose settlement dimension is `INVOICED` or `PARTIALLY_PAID`,
        else `ERR_ORDER_NOT_INVOICED`."
        PRD 2.8: "29. Payment headroom against the invoiced balance, else
        `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_check_precedes_fiscal_overpayment_check
        """
        scenario = setup_scenario(stage="delivered")
        order = read_order(scenario["order_id"])
        assert order["settlement_status"] == "UNBILLED"
        assert order["invoiced_total_cents"] == 0

        resp = api.create_payment(
            scenario["order_id"],
            {"amount_cents": 9999999},
            make_buyer_headers(scenario["buyer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_INVOICED.value, 409)

    def test_the_refused_uninvoiced_payment_moves_no_money(self, api):
        """PRD 2.8: "11. Payment admissibility — an instalment is applied only
        to an order whose settlement dimension is `INVOICED` or
        `PARTIALLY_PAID`, else `ERR_ORDER_NOT_INVOICED`."
        PRD 3.4: "The buyer's `outstanding_balance_cents` starts at 0 and
        thereafter tracks, across all of that buyer's orders, the invoiced total
        less the cash applied less the credit memos issued."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_check_precedes_fiscal_overpayment_check
        """
        scenario = setup_scenario(stage="delivered")

        resp = api.create_payment(
            scenario["order_id"],
            {"amount_cents": 9999999},
            make_buyer_headers(scenario["buyer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_INVOICED.value, 409)

        order = read_order(scenario["order_id"])
        assert order["paid_total_cents"] == 0
        assert order["settlement_status"] == "UNBILLED"
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 0

    def _dock_with_a_lapsed_second_producer(self):
        set_clock(CLOCK_BASE)
        first = onboard_active_producer()
        second = onboard_active_producer(
            legal_name="Stony Creek Dairy",
            region_code="ALL",
            contact_email="sc@example.org",
            expiries={"GAP_AUDIT": "2026-09-20T00:00:00Z"},
            verifier_user_id="co-verify-2",
            approver_user_id="co-approve-8",
        )
        slot = create_dock_slot(
            window_start="2026-10-05T06:00:00Z",
            window_end="2026-10-05T18:00:00Z",
            pallet_capacity=10,
            sanitation_buffer_minutes=45,
        )
        book_appointment(
            slot["id"],
            first["producer_id"],
            arrival_start="2026-10-05T08:00:00Z",
            arrival_end="2026-10-05T09:00:00Z",
            pallets=6,
            risk_class="PRODUCE",
        )
        set_clock("2026-09-20T00:00:00Z")
        return first, second, slot

    def test_producer_standing_is_screened_before_dock_capacity(self, api):
        """PRD 2.8: "Requests are screened in a fixed order, and the **first**
        check that fails determines the response. This ordering is a contract,
        not an implementation detail: when a request violates two rules at once,
        the earlier rule's error is the one the caller sees."
        PRD 2.8: "13. Producer standing — the producer whose supply, catalog or
        dock drop is involved is `ACTIVE` with compliance satisfied, else
        `ERR_PRODUCER_NOT_COMPLIANT`."
        PRD 2.8: "20. Aggregate dock capacity, else
        `ERR_DOCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/dock_safety_check_precedes_capacity_constraint_check
        """
        _first, second, slot = self._dock_with_a_lapsed_second_producer()

        payload = create_dock_appointment_payload(
            slot["id"],
            second["producer_id"],
            dock_slot_version(slot["id"]),
            arrival_start="2026-10-05T08:30:00Z",
            arrival_end="2026-10-05T09:30:00Z",
            pallets=5,
            risk_class="PRODUCE",
        )
        resp = api.create_dock_appointment(payload, HUB)
        validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_COMPLIANT.value, 422)

    def test_the_lapsed_producer_is_suspended_and_books_nothing(self, api):
        """PRD 3.6: "Only a producer that is `ACTIVE` with compliance satisfied
        may book at all, and one that is not is refused with
        `ERR_PRODUCER_NOT_COMPLIANT`."
        PRD 3.2: "Advancing the logical clock past a verified document's
        `expires_on` moves that document `VERIFIED → EXPIRED` — again strictly,
        so an expiry instant equal to the new clock instant is expired — and
        then re-evaluates the owning producer. If that producer was `ACTIVE` and
        its compliance has just flipped from satisfied to unsatisfied, it is
        suspended automatically, `ACTIVE → SUSPENDED`, with exactly the same
        consequences as a hand-issued suspension."

        Design: Difficulty/priority_pair_validation_conflict/dock_safety_check_precedes_capacity_constraint_check
        """
        _first, second, slot = self._dock_with_a_lapsed_second_producer()

        payload = create_dock_appointment_payload(
            slot["id"],
            second["producer_id"],
            dock_slot_version(slot["id"]),
            arrival_start="2026-10-05T08:30:00Z",
            arrival_end="2026-10-05T09:30:00Z",
            pallets=5,
            risk_class="PRODUCE",
        )
        resp = api.create_dock_appointment(payload, HUB)
        validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_COMPLIANT.value, 422)

        producer = read_producer(second["producer_id"])
        assert producer["onboarding_status"] == "SUSPENDED"
        assert producer["compliance_ok"] is False
        assert read_dock_slot(slot["id"])["pallets_booked"] == 6
        _, meta = validate_paginated(
            api.list_dock_appointments(
                HUB, params={"producer_id": second["producer_id"]}
            )
        )
        assert meta["total_count"] == 0
