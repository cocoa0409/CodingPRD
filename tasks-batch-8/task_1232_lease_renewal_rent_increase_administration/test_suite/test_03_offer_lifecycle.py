"""Offer issuance, resident response, expiry, withdrawal, and cycles (PRD §3.3–§3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_lease,
    create_offer_for_lease,
    create_offer_payload,
    create_policy,
    create_property,
    create_resident,
    create_unit,
    get_lease,
    get_offer,
    issue_offer,
    make_resident_headers,
    resident_accept,
    resident_counter,
    respond_accept_payload,
    respond_counter_payload,
    set_clock,
    setup_countered_offer_scenario,
    setup_executed_renewal_scenario,
    setup_issued_offer_scenario,
    setup_lease_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestIssueAndRespondGates:
    def test_respond_on_draft_offer_rejected(self, api):
        """PRD §3.4: "The resident answers an `ISSUED` offer — and only an `ISSUED`
        one, else `ERR_OFFER_NOT_ISSUED` — by submitting a `response_type` of
        `ACCEPT`, `DECLINE`, or `COUNTER`."

        Design: Corner/state_machines/respond_on_draft_offer_rejected
        """
        sc = setup_lease_scenario(property_name="Draft Gate", unit_number="202")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        resp = api.respond_to_offer(
            offer["id"], respond_accept_payload(),
            make_resident_headers(sc["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ISSUED)
        assert get_offer(offer["id"])["status"] == "DRAFT"

    def test_issue_twice_rejected(self, api):
        """PRD §3.4: "A staff member — `LeasingAgent`, `PropertyManager`, or
        `RegionalDirector` — issues a `DRAFT` offer to the resident; issuing an offer
        in any other state is rejected with `ERR_OFFER_NOT_DRAFT`."

        Design: Corner/state_machines/issue_twice_rejected
        """
        sc = setup_lease_scenario(property_name="Twice Court", unit_number="203")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        issue_offer(offer["id"])
        resp = api.issue_renewal_offer(offer["id"], LA1)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_DRAFT)
        after = get_offer(offer["id"])
        assert after["status"] == "ISSUED"
        assert after["issued_on_date"] == "2026-05-01"


class TestClockDrivenOfferOutcomes:
    def test_offer_expires_after_response_deadline(self, api):
        """PRD §3.4: "Two terminal outcomes belong to the clock sweep instead: an
        offer in `ISSUED` or `COUNTERED` whose `response_deadline_date` has passed
        becomes `EXPIRED`, and an offer in `ACCEPTED` whose `execution_deadline_date`
        has passed becomes `VOIDED` — which also voids its renewal document if that
        document is still unsigned or resident-signed. Both sweep outcomes void
        pending concessions and run the lease revert check."
        PRD §2.10: "First, any event that removes the last open offer from a lease in
        `RENEWAL_PENDING` — whether the offer was declined, expired, withdrawn, or
        superseded — reverts the lease to the status it held when the offer cycle
        began, recorded on the lease as `status_before_offer`, and clears that field."

        Design: Corner/state_machines/offer_expires_after_response_deadline
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Expiry Court", unit_number="208")
        offer = sc["offer"]
        # issued 2026-05-01 -> min(2026-05-15, term end 2027-06-01).
        assert offer["response_deadline_date"] == "2026-05-15"
        set_clock("2026-05-16T00:00:00Z")
        assert get_offer(offer["id"])["status"] == "EXPIRED"
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["monthly_rent_cents"] == 200000

    def test_respond_at_response_deadline_succeeds(self, api):
        """PRD §2.4: "third, open offers are expired or voided — offers in `ISSUED`
        or `COUNTERED` past their `response_deadline_date` expire, and offers in
        `ACCEPTED` past their `execution_deadline_date` are voided; fourth and last,
        leases whose term end has been reached convert to month-to-month."

        Design: Corner/state_machines/respond_at_response_deadline_succeeds
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Deadline Court", unit_number="209")
        assert sc["offer"]["response_deadline_date"] == "2026-05-15"
        set_clock("2026-05-15T00:00:00Z")  # the deadline date itself is not "past"
        resp = api.respond_to_offer(
            sc["offer"]["id"], respond_accept_payload(),
            make_resident_headers(sc["resident"]["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "ACCEPTED"

    def test_draft_offer_persists_but_late_issue_rejected(self, api):
        """PRD §2.4: "Offers still in `DRAFT` are never auto-expired by the sweep;
        they remain `DRAFT` until issued, withdrawn, or superseded, and an issue
        attempt that arrives after the statutory window has closed is rejected
        outright rather than silently expiring."
        PRD §3.4: "And the statutory window must still be open: for a fixed-term
        lease the clock date must be on or before the offer's `latest_issue_date`,
        while for an `MTM` lease the null `latest_issue_date` means no window
        applies; a late issue is rejected with `ERR_NOTICE_WINDOW_MISSED`."

        Design: Corner/state_machines/draft_offer_persists_but_late_issue_rejected
        """
        sc = setup_lease_scenario(property_name="Stale Draft Court", unit_number="211")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        # CONSERVATIVE: 150 bps <= 500 -> low tier 60 days -> 2027-06-01 - 60d.
        assert offer["latest_issue_date"] == "2027-04-02"
        set_clock("2027-04-03T00:00:00Z")  # past latest_issue; DRAFT never expires
        resp = api.issue_renewal_offer(offer["id"], LA1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_MISSED)
        assert get_offer(offer["id"])["status"] == "DRAFT"
        withdrawn = validate_success(api.withdraw_offer(offer["id"], LA1), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        # The lease never entered RENEWAL_PENDING (the offer never issued).
        assert get_lease(sc["lease"]["id"])["status"] == "ACTIVE"

    def test_clock_default_fixed_at_20260501(self, api):
        """PRD §2.4: "Before any administrative action advances it, the logical clock
        reads exactly `2026-05-01T00:00:00Z`."
        PRD §3.4: "A successful issue stamps `issued_on_date` with the clock date and
        `issued_by_user_id` with the acting operator, sets the
        `response_deadline_date` to the earlier of fourteen days from the clock date
        and the lease's `term_end_date` (for an `MTM` lease, simply fourteen days
        out), and moves the offer to `ISSUED`."

        Design: Corner/cross_cutting_layers/clock_default_fixed_at_20260501
        """
        sc = setup_lease_scenario(property_name="Default Clock Court", unit_number="DC1")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        issued = issue_offer(offer["id"])
        # No set_current_utc call was ever made in this test.
        assert issued["issued_on_date"] == "2026-05-01"
        # min(2026-05-01 + 14 days, term_end 2027-06-01).
        assert issued["response_deadline_date"] == "2026-05-15"


class TestNegotiationRounds:
    def _cycle_to_round3(self, api):
        sc = setup_lease_scenario(
            band_min=18, band_max=18, market_rent_cents=220000,
            monthly_rent_cents=200000, property_name="Cycle Court", unit_number="501")
        offer = create_offer_for_lease(sc["lease"], rate_strategy="BALANCED")
        assert offer["offer_round"] == 1
        offer = issue_offer(offer["id"])
        # Counters of 211000 keep the revised rent >= proposed (210800) so no
        # concession gate fires; 550 bps <= cap 550; window open at 2026-05-01.
        offer = resident_counter(offer["id"], sc["resident"]["id"], 211000)
        assert offer["status"] == "COUNTERED"
        offer = validate_success(api.revise_offer(offer["id"], {}, LA1), 200)
        assert offer["status"] == "ISSUED" and offer["offer_round"] == 2
        offer = resident_counter(offer["id"], sc["resident"]["id"], 211000)
        offer = validate_success(api.revise_offer(offer["id"], {}, LA1), 200)
        assert offer["status"] == "ISSUED" and offer["offer_round"] == 3
        return sc, offer

    def test_offer_negotiation_cycle_rounds_increment(self, api):
        """PRD §3.4: "A successful revise increments `offer_round` by one, overwrites
        `proposed_rent_cents` with the revised rent, recomputes
        `proposed_increase_bps`, `notice_days_required`, and `latest_issue_date`,
        adopts the revised term as `offered_term_months`, restamps `issued_on_date`
        with the clock date, resets the `response_deadline_date` to the earlier of
        fourteen days out and the term end, returns the offer to `ISSUED`, and marks
        the consumed concession approval `APPLIED`."
        PRD §3.4: "The revision takes optional `revised_rent_cents` and
        `revised_term_months`: the rent defaults to the resident's
        `counter_rent_cents` and the term defaults to the current
        `offered_term_months` when omitted."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_rounds
        """
        _sc, offer = self._cycle_to_round3(api)
        # The same offer looped ISSUED -> COUNTERED -> ISSUED twice.
        assert offer["offer_round"] == 3
        assert offer["proposed_rent_cents"] == 211000

    def test_offer_negotiation_round_cap_rejected(self, api):
        """PRD §3.4: "Negotiation is bounded at three rounds: when the offer's
        `offer_round` has already reached 3, a further counter is rejected with
        `ERR_MAX_NEGOTIATION_ROUNDS`."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_rounds
        """
        sc, offer = self._cycle_to_round3(api)
        resp = api.respond_to_offer(
            offer["id"], respond_counter_payload(211000),
            make_resident_headers(sc["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MAX_NEGOTIATION_ROUNDS)
        after = get_offer(offer["id"])
        assert after["status"] == "ISSUED"
        assert after["offer_round"] == 3


class TestLeaseStatusCycles:
    def _cycle_fixture(self, api):
        return setup_lease_scenario(
            band_min=12, band_max=12, market_rent_cents=210000,
            monthly_rent_cents=200000, property_name="Loop Manor", unit_number="601")

    def test_lease_cycle_decline_revert_then_execution_return(self, api):
        """PRD §3.4: "Issuing also moves the lease from `ACTIVE` or `MTM` into
        `RENEWAL_PENDING`, capturing the prior status in `status_before_offer` on
        this first entry into the cycle."
        PRD §3.4: "Declining moves the offer to `DECLINED` and triggers the lease
        revert check of §2.10: if no other offer remains open for the lease, a lease
        sitting in `RENEWAL_PENDING` returns to the status captured in
        `status_before_offer` (`ACTIVE` or `MTM`) and the field clears."
        PRD §3.7: "The lease is renewed: its `monthly_rent_cents` becomes the
        executed rent, its new `term_start_date` is the later of the old
        `term_end_date` and the current clock date, `term_months` becomes the offer's
        `offered_term_months`, `term_end_date` is recomputed from those values,
        status returns to `ACTIVE`, `status_before_offer` clears, and the lease's
        `version` increments by one."

        Design: Difficulty/non_linear_state_machine/lease_renewal_cycle_status_loops
        """
        sc = self._cycle_fixture(api)
        res_headers = make_resident_headers(sc["resident"]["id"])

        # Arc 1: ACTIVE -> RENEWAL_PENDING -> ACTIVE (decline revert).
        o1 = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        issue_offer(o1["id"])
        assert get_lease(sc["lease"]["id"])["status"] == "RENEWAL_PENDING"
        resp = api.respond_to_offer(o1["id"], {"response_type": "DECLINE"}, res_headers)
        validate_success(resp, 200)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["status_before_offer"] is None

        # Arc 2: full execution returns the lease to ACTIVE with new economics.
        o2 = create_offer_for_lease(lease, rate_strategy="CONSERVATIVE")
        issue_offer(o2["id"])
        resident_accept(o2["id"], sc["resident"]["id"])
        from test_helpers import get_document_for_offer
        doc = get_document_for_offer(o2["id"])
        validate_success(api.sign_document_resident(doc["id"], res_headers), 200)
        validate_success(api.countersign_document(doc["id"], PM1), 200)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["monthly_rent_cents"] == 203000  # CONSERVATIVE 150 bps on 200000
        assert lease["term_end_date"] == "2028-06-01"  # 2027-06-01 + 12 months

    def test_lease_cycle_mtm_conversion_and_withdraw_revert(self, api):
        """PRD §3.2: "The premium base is the `proposed_rent_cents` of the most
        recently created offer for the lease that was actually issued (an offer whose
        `issued_on_date` is set, breaking ties by latest creation); if no issued
        offer exists, the base is the lease's `monthly_rent_cents` grown by the
        policy's `effective_cap_bps` and rounded half-up to whole cents. The
        conversion rent is then the base grown by a premium of 1,500 basis points —
        fifteen percent — rounded half-up to whole cents."
        PRD §3.4: "Any open offer in `DRAFT`, `ISSUED`, or `COUNTERED` may be
        withdrawn by staff; offers already in a terminal state reject the withdrawal
        with `ERR_OFFER_NOT_WITHDRAWABLE`. Withdrawal moves the offer to `WITHDRAWN`,
        voids its pending concession approvals, and runs the lease revert check."

        Design: Difficulty/non_linear_state_machine/lease_renewal_cycle_status_loops
        """
        sc = self._cycle_fixture(api)
        res_headers = make_resident_headers(sc["resident"]["id"])
        from test_helpers import get_document_for_offer

        # Execute one renewal so the lease carries an issued offer (base 203000).
        o1 = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        issue_offer(o1["id"])
        resident_accept(o1["id"], sc["resident"]["id"])
        doc = get_document_for_offer(o1["id"])
        validate_success(api.sign_document_resident(doc["id"], res_headers), 200)
        validate_success(api.countersign_document(doc["id"], PM1), 200)

        # Clock to the new term end -> MTM on the 203000 issued base.
        set_clock("2028-06-01T00:00:00Z")
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "MTM"
        assert lease["monthly_rent_cents"] == 233450  # round(203000 * 1.15)
        assert lease["mtm_converted_on"] == "2028-06-01"

        # MTM -> RENEWAL_PENDING on the third issue, then withdraw -> MTM.
        o3 = create_offer_for_lease(lease, rate_strategy="CONSERVATIVE")
        issue_offer(o3["id"])  # MTM lease: null latest_issue_date, no window
        assert get_lease(sc["lease"]["id"])["status"] == "RENEWAL_PENDING"
        validate_success(api.withdraw_offer(o3["id"], LA1), 200)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "MTM"
        assert lease["monthly_rent_cents"] == 233450


class TestOfferSupersedeCascade:
    def _supersede_fixture(self, api):
        sc = setup_countered_offer_scenario(
            counter_rent_cents=205000, property_name="Supersede Court", unit_number="703")
        resp = api.create_concession_approval(
            sc["offer"]["id"], {"requested_rent_cents": 205000, "reason": "retention"}, LA1)
        sc["concession"] = validate_success(resp, 201)
        return sc

    def test_offer_create_supersede_cascade_marks_and_links(self, api):
        """PRD §3.3: "Creating an offer is deliberately destructive to its
        predecessors: any still-open sibling offers for the same lease — those in
        `DRAFT`, `ISSUED`, or `COUNTERED` — are immediately moved to `SUPERSEDED`,
        their pending concession approvals are voided per §2.10, and the new offer's
        `supersedes_offer_id` records the most recently created of the superseded
        offers (null when none existed). The lease's `version` increments by one as
        part of the creation."

        Design: Difficulty/transitive_cascade/offer_create_supersede_cascade
        """
        sc = self._supersede_fixture(api)
        offer_a = sc["offer"]
        offer_b = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        assert offer_b["supersedes_offer_id"] == offer_a["id"]
        assert get_offer(offer_a["id"])["status"] == "SUPERSEDED"
        # Link 2: A's supersession voids A's SUBMITTED concession (an effect of
        # A's transition, not of the create directly).
        from test_helpers import get_concession
        assert get_concession(sc["concession"]["id"])["status"] == "VOIDED"

    def test_offer_create_supersede_keeps_lease_pending(self, api):
        """PRD §2.10: "First, any event that removes the last open offer from a lease
        in `RENEWAL_PENDING` — whether the offer was declined, expired, withdrawn, or
        superseded — reverts the lease to the status it held when the offer cycle
        began, recorded on the lease as `status_before_offer`, and clears that
        field."

        Design: Difficulty/transitive_cascade/offer_create_supersede_cascade
        """
        sc = self._supersede_fixture(api)
        offer_b = create_offer_for_lease(sc["lease"], rate_strategy="CONSERVATIVE")
        assert offer_b["status"] == "DRAFT"
        assert offer_b["offer_round"] == 1
        # No revert fires: the new offer B is itself an open offer for the lease.
        assert get_lease(sc["lease"]["id"])["status"] == "RENEWAL_PENDING"


class TestOptimisticConcurrencyOfferCreate:
    def test_occ_offer_create_stale_version(self, api):
        """PRD §2.7: "Creating a renewal offer against a lease requires the request
        to carry `expected_lease_version`, holding the lease `version` the client
        last read. Offer creation supersedes any open offer on the lease, so a writer
        holding a stale version would wipe out offers it never saw; when the supplied
        value does not match the lease's current `version`, the creation is rejected
        with `ERR_STALE_LEASE_VERSION` (HTTP 412), and the client must re-read the
        lease before resubmitting."

        Design: Corner/cross_cutting_layers/occ_offer_create_stale_version
        """
        sc = setup_lease_scenario(property_name="OCC Court", unit_number="OC1")
        lease = sc["lease"]
        stale_version = lease["version"]
        offer_a = create_offer_for_lease(lease, rate_strategy="CONSERVATIVE")
        # The create advanced the lease version; replaying the stale one fails.
        resp = api.create_renewal_offer(
            lease["id"],
            create_offer_payload(stale_version, rate_strategy="BALANCED"),
            LA1)
        validate_error(resp, ApiErrorId.ERR_STALE_LEASE_VERSION)
        # Re-reading and resubmitting with the observed version succeeds.
        fresh = get_lease(lease["id"])
        resp = api.create_renewal_offer(
            lease["id"],
            create_offer_payload(fresh["version"], rate_strategy="BALANCED"),
            LA1)
        offer_b = validate_success(resp, 201)
        assert offer_b["supersedes_offer_id"] == offer_a["id"]
        assert get_offer(offer_a["id"])["status"] == "SUPERSEDED"


class TestHierarchicalRoles:
    def test_manager_inherits_leasing_offer_ops(self, api):
        """PRD §2.1: "`PropertyManager` manages a property's day-to-day renewal
        program: serving and rescinding non-renewal notices, countersigning renewal
        documents, and all leasing-agent capabilities."

        Design: Corner/rbac/manager_inherits_leasing_offer_ops
        """
        sc = setup_lease_scenario(property_name="Override Court", unit_number="OV1")
        lease = sc["lease"]
        resp = api.create_renewal_offer(
            lease["id"],
            create_offer_payload(lease["version"], rate_strategy="CONSERVATIVE"),
            PM1)
        offer = validate_success(resp, 201)
        assert offer["status"] == "DRAFT"
        issued = validate_success(api.issue_renewal_offer(offer["id"], PM1), 200)
        assert issued["status"] == "ISSUED"
