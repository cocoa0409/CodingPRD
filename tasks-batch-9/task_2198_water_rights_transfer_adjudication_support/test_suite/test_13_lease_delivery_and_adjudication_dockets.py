"""Lease delivery from reservation to completion, and the docket/claim machines.

PRD §3.9: "Reserving a lease commits credit to a named lessee at a named headgate
over a named window."
"""
import pytest
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_adjudication_claim_payload
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    activate_right,
    add_use_record,
    create_claimant,
    create_water_right,
    examine_claim,
    file_claim,
    open_docket,
    read_account,
    read_claim,
    read_docket,
    read_lease,
    read_right,
    set_clock,
    setup_base_right,
    setup_docket_in_objection_period,
    setup_docket_with_claim,
    setup_reserved_lease,
    verify_claim,
)

CLOCK = "2026-03-01T00:00:00Z"
LEASE_START = "2026-04-01T00:00:00Z"
LEASE_END = "2026-07-01T00:00:00Z"
FILING_DEADLINE = "2026-06-01T00:00:00Z"


class TestTheFullTermLeaseWalk:
    """PRD §3.9 — credit crosses three buckets in order and then leaves the bank.

    A bank-enrolled certified right of 195.00 AF carries one `AUTHORIZED`
    headgate at 5.000 CFS and funds its account with a 90.00 AF deposit. A
    20.00 AF lease runs the whole of `[2026-04-01, 2026-07-01)`: it is started at
    exactly the opening instant and closed out at exactly the closing instant, so
    the delivery is never settled early.
    """

    def _reserved(self):
        return setup_reserved_lease(
            requested_af=20.00,
            lease_start_date=LEASE_START,
            lease_end_date=LEASE_END,
            clock=CLOCK,
            deposit_af=90.00,
        )

    def test_activation_at_the_opening_instant_repartitions_credit(self):
        """PRD §3.9: "the logical clock must be at or after `lease_start_date` and
        strictly before `lease_end_date`, otherwise `ERR_LEASE_WINDOW_TIMING`
        (422)."

        The clock sits on `lease_start_date` itself, which the at-or-after half of
        that test admits. PRD §3.9: "On success `committed_credit_af` decreases and
        `leased_out_af` increases by `requested_af` while `available_credit_af` is
        untouched, so the credit identity is conserved by repartition alone; the
        posture is recomputed." PRD §2.9's identity therefore still reads
        90.00 = 70.00 + 0.00 + 20.00.

        Design: Corner/state_machines/sm_lease_reserved_to_active_to_completed_full_term
        """
        bundle = self._reserved()
        set_clock(LEASE_START)

        lease = get_success_data(
            api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        )

        assert lease["status"] == "ACTIVE"
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["posture"] == "OPEN"

    def test_completion_at_the_closing_instant_delivers_the_whole_volume(self):
        """PRD §3.9: "The lease moves `ACTIVE → COMPLETED`, which is terminal, with
        `used_af` set to the whole `requested_af` and `settlement_credit_af` set to
        0.00 by definition."

        Completion needs the clock to have reached `lease_end_date`, and the clock
        is set to exactly that instant. Because the whole term was delivered there
        is nothing to settle, so the run-to-term path is the one place where the
        valuation method never enters the arithmetic.

        Design: Corner/state_machines/sm_lease_reserved_to_active_to_completed_full_term
        """
        bundle = self._reserved()
        set_clock(LEASE_START)
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        set_clock(LEASE_END)

        lease = get_success_data(
            api_client.complete_lease_assignment(bundle["lease"]["id"], ANALYST)
        )

        assert lease["status"] == "COMPLETED"
        assert lease["used_af"] == pytest.approx(20.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(0.00, abs=0.01)

    def test_the_delivered_volume_leaves_the_bank_and_books_onto_the_right(self):
        """PRD §3.9: "On the account both `leased_out_af` and `deposited_credit_af`
        decrease by `requested_af`, because the water was actually delivered and
        permanently leaves the bank, and the identity is conserved because both
        sides of it shrink together."

        PRD §3.9: "On the source right the used volume moves out of `encumbered_af`
        and into `transferred_away_af`." The 90.00 AF bank hold is reduced to 70.00
        and 20.00 AF is now permanently transferred away, so PRD §2.9's
        195.00 = 105.00 + 70.00 + 20.00 still holds and PRD §2.10 re-derives the
        right as `PARTIALLY_TRANSFERRED` because transferred-away volume outranks
        an encumbrance.

        Design: Corner/state_machines/sm_lease_reserved_to_active_to_completed_full_term
        """
        bundle = self._reserved()
        set_clock(LEASE_START)
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        set_clock(LEASE_END)

        api_client.complete_lease_assignment(bundle["lease"]["id"], ANALYST)

        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(70.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(20.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(105.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"


class TestBothEndsOfTheDeliveryWindow:
    """PRD §3.9 — one error identity guards both ends of the window with opposite
    strictness.

    The same 20.00 AF lease over `[2026-04-01, 2026-07-01)` is pushed at the
    window from three different instants: a month early, at the closing instant
    itself, and mid-window on 2026-04-15. Completion is then attempted from that
    same mid-window instant.
    """

    def _reserved(self):
        return setup_reserved_lease(
            requested_af=20.00,
            lease_start_date=LEASE_START,
            lease_end_date=LEASE_END,
            clock=CLOCK,
            deposit_af=90.00,
        )

    def test_activation_before_the_window_opens_is_refused(self):
        """PRD §3.9: "the logical clock must be at or after `lease_start_date` and
        strictly before `lease_end_date`, otherwise `ERR_LEASE_WINDOW_TIMING`
        (422)."

        At a clock of 2026-03-01 against an 2026-04-01 opening the lease is simply
        early. Nothing is repartitioned: the credit stays committed and none of it
        is leased out.

        Design: Corner/state_machines/sm_lease_timing_gates_outside_the_window_rejected
        """
        bundle = self._reserved()

        response = api_client.activate_lease_assignment(
            bundle["lease"]["id"], ANALYST
        )

        validate_error(
            response, ApiErrorId.ERR_LEASE_WINDOW_TIMING.value, expected_status=422
        )
        assert read_lease(bundle["lease"]["id"])["status"] == "RESERVED"
        account = read_account(bundle["account"]["id"])
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)

    def test_activation_at_the_closing_instant_is_refused_but_mid_window_works(self):
        """PRD §3.9: "the logical clock must be at or after `lease_start_date` and
        strictly before `lease_end_date`".

        `lease_end_date` is excluded by the strictly-before half of the test, so
        2026-07-01 is one instant too late even though it is the boundary the
        window is named for. Rolling the clock back to 2026-04-15, genuinely inside
        the window, admits the identical request.

        Design: Corner/state_machines/sm_lease_timing_gates_outside_the_window_rejected
        """
        bundle = self._reserved()
        set_clock(LEASE_END)

        too_late = api_client.activate_lease_assignment(
            bundle["lease"]["id"], ANALYST
        )
        set_clock("2026-04-15T00:00:00Z")
        inside = get_success_data(
            api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        )

        validate_error(
            too_late, ApiErrorId.ERR_LEASE_WINDOW_TIMING.value, expected_status=422
        )
        assert inside["status"] == "ACTIVE"

    def test_completion_before_the_closing_instant_is_refused(self):
        """PRD §3.9: "Closing out a lease that ran to term is analyst or
        adjudicator work and requires the logical clock to have reached
        `lease_end_date`, otherwise `ERR_LEASE_WINDOW_TIMING`."

        The clock stands mid-window at 2026-04-15, which is exactly where
        activation was legal, so no single instant admits both edges. The lease
        stays `ACTIVE` with its credit still leased out and no settlement is
        computed.

        Design: Corner/state_machines/sm_lease_timing_gates_outside_the_window_rejected
        """
        bundle = self._reserved()
        set_clock("2026-04-15T00:00:00Z")
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)

        response = api_client.complete_lease_assignment(
            bundle["lease"]["id"], ANALYST
        )

        validate_error(
            response, ApiErrorId.ERR_LEASE_WINDOW_TIMING.value, expected_status=422
        )
        lease = read_lease(bundle["lease"]["id"])
        assert lease["status"] == "ACTIVE"
        assert lease["used_af"] == pytest.approx(0.00, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["leased_out_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)


class TestTheClaimsTwoAxesAdvanceIndependently:
    """PRD §3.10 — "A claim carries two independent status dimensions from birth
    and they advance through separate operations in either order."

    One `ACTIVE` right carrying a single 2024 metered record is claimed for
    100.00 AF on docket `DKT-2198-A`, whose filing deadline is 2026-06-01. The
    evidentiary axis is walked first, all the way around its cycle, while the
    docket is still taking claims; only then does the procedural axis move.
    """

    def _docket_with_claim(self):
        return setup_docket_with_claim(
            clock=CLOCK,
            claim_filing_deadline=FILING_DEADLINE,
            claimed_af=100.00,
            use_years=(2024,),
        )

    def test_the_evidentiary_axis_cycles_without_moving_the_other_axis(self):
        """PRD §3.10: "Both `UNVERIFIED → FIELD_VERIFIED` and `UNVERIFIED →
        DISPUTED` are available, and `DISPUTED → FIELD_VERIFIED` is the cycle on
        this axis, so a disputed claim can later be re-verified once the evidence
        arrives."

        PRD §3.10: "Verification is field work performed by the analyst or the
        adjudicator, in any docket phase whatsoever". The docket is still
        `OPEN_FOR_CLAIMS` for both calls, and PRD §3.10 confirms the isolation:
        "Neither operation on one axis ever touches the other axis, and no docket
        counter moves on a verification." The 2024 metered record is what makes
        `FIELD_VERIFIED` admissible at all.

        Design: Corner/state_machines/sm_adjudication_claim_dimensions_advance_on_independent_axes
        """
        bundle = self._docket_with_claim()
        assert bundle["claim"]["verification_status"] == "UNVERIFIED"

        disputed = verify_claim(bundle["claim"]["id"], "DISPUTED")
        interim_docket = read_docket(bundle["docket"]["id"])
        verified = verify_claim(bundle["claim"]["id"], "FIELD_VERIFIED")

        assert disputed["verification_status"] == "DISPUTED"
        assert disputed["filing_status"] == "FILED"
        assert interim_docket["phase"] == "OPEN_FOR_CLAIMS"
        assert interim_docket["claim_count"] == 1
        assert verified["verification_status"] == "FIELD_VERIFIED"
        assert verified["filing_status"] == "FILED"
        final_docket = read_docket(bundle["docket"]["id"])
        assert final_docket["phase"] == "OPEN_FOR_CLAIMS"
        assert final_docket["claim_count"] == 1
        assert final_docket["decreed_claim_count"] == 0

    def test_the_procedural_axis_needs_the_docket_and_leaves_verification_alone(self):
        """PRD §3.10: "Examination is adjudicator-only and valid only while the
        docket reads `EXAMINATION`."

        The docket advances at exactly its 2026-06-01 filing deadline, which PRD
        §3.10 treats as reached, carrying its one claim with it. PRD §3.10: "The
        claim moves `FILED → EXAMINED` and `verification_status` is left
        untouched." The recommendation of 90.00 is within the 100.00 claimed, which
        PRD §3.10 requires: "the recommendation must be strictly greater than zero
        and no greater than `claimed_af`".

        Design: Corner/state_machines/sm_adjudication_claim_dimensions_advance_on_independent_axes
        """
        bundle = self._docket_with_claim()
        verify_claim(bundle["claim"]["id"], "DISPUTED")
        verify_claim(bundle["claim"]["id"], "FIELD_VERIFIED")
        set_clock(FILING_DEADLINE)

        docket = get_success_data(
            api_client.advance_docket_phase(
                bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
            )
        )
        claim = examine_claim(bundle["claim"]["id"], 90.00)

        assert docket["phase"] == "EXAMINATION"
        assert docket["claim_count"] == 1
        assert claim["filing_status"] == "EXAMINED"
        assert claim["examiner_recommended_af"] == pytest.approx(90.00, abs=0.01)
        assert claim["verification_status"] == "FIELD_VERIFIED"
        assert claim["claimed_af"] == pytest.approx(100.00, abs=0.01)


class TestTheDecreeIsGuardedByTheOtherDimension:
    """PRD §3.10 — "Its distinguishing feature is a guard on the *other* dimension:
    `verification_status` must read `FIELD_VERIFIED`, otherwise `ERR_CLAIM_NOT_VERIFIED`
    (409)."

    A docket sits in `OBJECTION_PERIOD` holding one `EXAMINED` claim that asserts
    100.00 AF against a 90.00 AF recommendation and has never been to the field.
    The decree is attempted from `UNVERIFIED`, then from `DISPUTED`, and only then
    from `FIELD_VERIFIED`.
    """

    def _examined_but_unverified(self):
        return setup_docket_in_objection_period(
            clock=CLOCK,
            examiner_recommended_af=90.00,
            verify=False,
            claim_filing_deadline=FILING_DEADLINE,
            claimed_af=100.00,
            use_years=(2024,),
        )

    def _decree(self, claim_id, note):
        return api_client.decree_adjudication_claim(claim_id, note, ADJUDICATOR)

    def test_neither_unverified_nor_disputed_opens_the_decree(self):
        """PRD §3.10: "`verification_status` must read `FIELD_VERIFIED`, otherwise
        `ERR_CLAIM_NOT_VERIFIED` (409)."

        PRD §3.10: "An examined but unverified claim, and a disputed one, are both
        undecreeable, which is exactly why the two axes must be advanced
        independently before a decree can be entered." Two different evidentiary
        states therefore report the same identity, and neither attempt moves the
        procedural axis or any docket counter.

        Design: Corner/state_machines/sm_adjudication_claim_decree_gated_on_field_verification
        """
        bundle = self._examined_but_unverified()
        assert bundle["claim"]["verification_status"] == "UNVERIFIED"

        unverified = self._decree(
            bundle["claim"]["id"], "decree attempted on an unverified claim"
        )
        verify_claim(bundle["claim"]["id"], "DISPUTED")
        disputed = self._decree(
            bundle["claim"]["id"], "decree attempted on a disputed claim"
        )

        for response in (unverified, disputed):
            validate_error(
                response, ApiErrorId.ERR_CLAIM_NOT_VERIFIED.value, expected_status=409
            )
        claim = read_claim(bundle["claim"]["id"])
        assert claim["filing_status"] == "EXAMINED"
        assert claim["verification_status"] == "DISPUTED"
        assert claim["priority_rank"] is None
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "OBJECTION_PERIOD"
        assert docket["decreed_claim_count"] == 0
        assert docket["total_decreed_af"] == pytest.approx(0.00, abs=0.01)

    def test_field_verification_opens_the_terminal_decree(self):
        """PRD §3.10: "First the volume is floored at the lesser of `claimed_af`
        and `examiner_recommended_af`."

        No objection was lodged and the claimed priority date is the right's own,
        so neither of the two 0.90 haircuts of PRD §3.10 applies and the decree is
        the bare floor of 90.00. PRD §3.10: "when `decreed_claim_count` becomes
        equal to `claim_count`, the docket auto-advances `OBJECTION_PERIOD →
        DECREE_ENTERED` and `total_decreed_af` is frozen, without any separate
        phase-advance request."

        Design: Corner/state_machines/sm_adjudication_claim_decree_gated_on_field_verification
        """
        bundle = self._examined_but_unverified()
        self._decree(bundle["claim"]["id"], "decree attempted too early")
        verify_claim(bundle["claim"]["id"], "DISPUTED")
        verify_claim(bundle["claim"]["id"], "FIELD_VERIFIED")

        claim = get_success_data(
            self._decree(bundle["claim"]["id"], "decree entered on the verified record")
        )

        assert claim["filing_status"] == "DECREED"
        assert claim["verification_status"] == "FIELD_VERIFIED"
        assert claim["decreed_af"] == pytest.approx(90.00, abs=0.01)
        assert claim["priority_rank"] == 1
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "DECREE_ENTERED"
        assert docket["decreed_claim_count"] == 1
        assert docket["claim_count"] == 1
        assert docket["total_decreed_af"] == pytest.approx(90.00, abs=0.01)


class TestCompletedIsTerminalAndTheLedgerStandsStill:
    """PRD §3.9 — nothing may re-open a delivery that has already been paid out.

    The full-term walk is taken to `COMPLETED`: a 20.00 AF lease over
    `[2026-04-01, 2026-07-01)` started at the opening instant and closed out at
    the closing instant, leaving the account at 70.00 AF deposited and 70.00 AF
    available. Four different edges are then pushed at the terminal row.
    """

    def _completed(self):
        bundle = setup_reserved_lease(
            requested_af=20.00,
            lease_start_date=LEASE_START,
            lease_end_date=LEASE_END,
            clock=CLOCK,
            deposit_af=90.00,
        )
        set_clock(LEASE_START)
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        set_clock(LEASE_END)
        bundle["lease"] = get_success_data(
            api_client.complete_lease_assignment(bundle["lease"]["id"], ANALYST)
        )
        bundle["account"] = read_account(bundle["account"]["id"])
        return bundle

    def _refusals(self, lease_id):
        return {
            "activate": api_client.activate_lease_assignment(lease_id, ANALYST),
            "resume": api_client.resume_lease_assignment(lease_id, ANALYST),
            "cancel": api_client.cancel_lease_assignment(
                lease_id,
                "attempt to claw back settlement credit after completion",
                ANALYST,
            ),
            "complete": api_client.complete_lease_assignment(lease_id, ANALYST),
        }

    def test_completed_admits_no_further_edge(self):
        """PRD §3.9: "The lease moves `ACTIVE → COMPLETED`, which is terminal".

        Every edge that could reach `ACTIVE` again names a different origin state:
        activation "starts a `RESERVED` lease", resumption "moves the lease
        `SUSPENDED → ACTIVE`", early termination "is reachable from `RESERVED`,
        `ACTIVE` or `SUSPENDED`", and completion itself requires an `ACTIVE` lease.
        A completed lease satisfies none of them, so all four are refused on state.

        Design: Corner/state_machines/sm_lease_completed_state_is_terminal_and_locked
        """
        bundle = self._completed()
        assert bundle["lease"]["status"] == "COMPLETED"

        refusals = self._refusals(bundle["lease"]["id"])

        for edge, response in refusals.items():
            assert response.status_code == 409, f"{edge} must be refused on state"
            validate_error(
                response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
            )
        assert read_lease(bundle["lease"]["id"])["status"] == "COMPLETED"

    def test_the_credit_ledger_stands_still_across_all_four_refusals(self):
        """PRD §2.10: "On every row a cascade touches, `updated_at` is refreshed and
        `version` is incremented by 1".

        Because nothing succeeded, no row was touched: the account keeps the
        `version` it carried when the delivery closed out, so there is neither a
        second debit of `deposited_credit_af` nor a phantom return of settlement
        credit to `available_credit_af`. The lease also keeps the two figures PRD
        §3.9 pinned at completion, `used_af` at the whole 20.00 and
        `settlement_credit_af` at 0.00.

        Design: Corner/state_machines/sm_lease_completed_state_is_terminal_and_locked
        """
        bundle = self._completed()
        before = bundle["account"]["version"]

        self._refusals(bundle["lease"]["id"])

        account = read_account(bundle["account"]["id"])
        assert account["version"] == before
        assert account["deposited_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        lease = read_lease(bundle["lease"]["id"])
        assert lease["used_af"] == pytest.approx(20.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert lease["version"] == bundle["lease"]["version"]


SENIOR_PRIORITY = "1901-05-01T00:00:00Z"
JUNIOR_PRIORITY = "1912-06-01T00:00:00Z"


def _junior_stockwater_right(claimant_id):
    """A second `ACTIVE` right, junior by eleven years, with metered evidence."""
    right = create_water_right(
        claimant_id,
        right_number="WR-2198-002",
        priority_date=JUNIOR_PRIORITY,
        purpose_of_use="STOCKWATER",
        place_of_use_acres=40.00,
        authorized_diversion_af=100.00,
        authorized_rate_cfs=1.500,
    )
    add_use_record(
        right["id"],
        2024,
        reported_diversion_af=60.000,
        irrigated_acres=40.00,
        verification_source="METER",
    )
    return activate_right(right["id"])


class TestSeniorityIsRecomputedAcrossTheWholeDocket:
    """PRD §3.10 — "a late-filed but senior claim can push every junior claim's
    rank down when it is finally decreed."

    Docket `DKT-2198-A` holds two claims filed in the wrong order on purpose: the
    junior 1912 stockwater claim for 50.00 AF is filed first, the senior 1901
    irrigation claim for 100.00 AF second. Both are field-verified and examined —
    the senior at 90.00, the junior at its full 50.00 — and the docket is advanced
    to `OBJECTION_PERIOD`. The junior claim is then decreed first.
    """

    def _two_decreeable_claims(self):
        bundle = setup_base_right(clock=CLOCK, use_years=(2024,))
        bundle["junior_claimant"] = create_claimant(
            "Cottonwood Cattle Co",
            contact_email="b@cotton.example",
            entity_type="INDIVIDUAL",
        )
        bundle["junior_right"] = _junior_stockwater_right(
            bundle["junior_claimant"]["id"]
        )
        bundle["docket"] = open_docket(FILING_DEADLINE)
        bundle["junior"] = file_claim(
            bundle["docket"]["id"], bundle["junior_right"]["id"], JUNIOR_PRIORITY, 50.00
        )
        bundle["senior"] = file_claim(
            bundle["docket"]["id"], bundle["right"]["id"], SENIOR_PRIORITY, 100.00
        )
        for claim in (bundle["junior"], bundle["senior"]):
            verify_claim(claim["id"], "FIELD_VERIFIED")
        set_clock(FILING_DEADLINE)
        api_client.advance_docket_phase(
            bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
        )
        bundle["senior"] = examine_claim(bundle["senior"]["id"], 90.00)
        bundle["junior"] = examine_claim(bundle["junior"]["id"], 50.00)
        bundle["docket"] = get_success_data(
            api_client.advance_docket_phase(
                bundle["docket"]["id"], "OBJECTION_PERIOD", ADJUDICATOR
            )
        )
        return bundle

    def _decree(self, claim_id, note):
        return get_success_data(
            api_client.decree_adjudication_claim(claim_id, note, ADJUDICATOR)
        )

    def test_the_first_decree_ranks_the_only_decreed_claim_first(self):
        """PRD §3.10: "`priority_rank` is recomputed for *every* decreed claim on
        the docket, not merely the new one, as a 1-based rank ordered by
        `claimed_priority_date` ascending".

        The junior claim is for the moment the only decreed row on the docket, so
        it ranks 1 despite being the junior of the two. Its decree is the bare
        floor of 50.00 because the claim and the recommendation agree. The docket's
        counters move but PRD §3.10's bubble-up does not fire, because
        `decreed_claim_count` is 1 against a `claim_count` of 2.

        Design: Corner/state_machines/sm_decree_docket_reranks_seniority_and_bubbles_up_on_last_decree
        """
        bundle = self._two_decreeable_claims()

        junior = self._decree(bundle["junior"]["id"], "junior claim decreed first")

        assert junior["filing_status"] == "DECREED"
        assert junior["decreed_af"] == pytest.approx(50.00, abs=0.01)
        assert junior["priority_rank"] == 1
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "OBJECTION_PERIOD"
        assert docket["claim_count"] == 2
        assert docket["decreed_claim_count"] == 1
        assert docket["total_decreed_af"] == pytest.approx(50.00, abs=0.01)

    def test_the_senior_decree_reranks_an_already_terminal_row(self):
        """PRD §3.10: "each re-ranked claim bumps its own `version`."

        The senior claim decrees at 90.00 and takes rank 1, which pushes the
        already-`DECREED` junior claim down to rank 2 — a row that is terminal on
        the procedural axis still has its rank and its `version` moved by a
        stranger's decree. PRD §3.10: "when `decreed_claim_count` becomes equal to
        `claim_count`, the docket auto-advances `OBJECTION_PERIOD → DECREE_ENTERED`
        and `total_decreed_af` is frozen, without any separate phase-advance
        request." The frozen total is 50.00 + 90.00.

        Design: Corner/state_machines/sm_decree_docket_reranks_seniority_and_bubbles_up_on_last_decree
        """
        bundle = self._two_decreeable_claims()
        junior_first = self._decree(
            bundle["junior"]["id"], "junior claim decreed first"
        )

        senior = self._decree(bundle["senior"]["id"], "senior claim decreed second")

        assert senior["decreed_af"] == pytest.approx(90.00, abs=0.01)
        assert senior["priority_rank"] == 1
        junior = read_claim(bundle["junior"]["id"])
        assert junior["priority_rank"] == 2
        assert junior["version"] > junior_first["version"]
        assert junior["decreed_af"] == pytest.approx(50.00, abs=0.01)
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "DECREE_ENTERED"
        assert docket["decreed_claim_count"] == 2
        assert docket["total_decreed_af"] == pytest.approx(140.00, abs=0.01)

    def test_the_claim_listing_is_ordered_by_seniority_not_by_insertion(self):
        """PRD §2.3: "adjudication claims are ordered by `claimed_priority_date`
        ascending then `created_at` ascending, which is the same seniority ordering
        used to assign rank inside a decree."

        The junior claim was created first and decreed first, yet the senior 1901
        claim reads first, and PRD §2.3 is explicit that "No listing in this
        service ever orders by `id`."

        Design: Corner/state_machines/sm_decree_docket_reranks_seniority_and_bubbles_up_on_last_decree
        """
        bundle = self._two_decreeable_claims()
        self._decree(bundle["junior"]["id"], "junior claim decreed first")
        self._decree(bundle["senior"]["id"], "senior claim decreed second")

        claims, meta = validate_paginated(
            api_client.list_adjudication_claims(
                ADJUDICATOR, {"decree_docket_id": bundle["docket"]["id"]}
            )
        )

        assert meta["total_count"] == 2
        assert [claim["id"] for claim in claims] == [
            bundle["senior"]["id"],
            bundle["junior"]["id"],
        ]
        assert [claim["priority_rank"] for claim in claims] == [1, 2]


class TestClosedRefusesTwoDifferentVocabularies:
    """PRD §3.10 — "reaching `CLOSED` makes the docket read-only."

    Docket `DKT-2198-A` is taken the whole way: its single field-verified claim is
    examined at 90.00, the docket advances to `OBJECTION_PERIOD`, the decree
    bubbles it to `DECREE_ENTERED`, and the adjudicator then closes it. A second
    `ACTIVE` right belonging to the same claimant stands ready to attempt a late
    filing.
    """

    def _closed_docket(self):
        bundle = setup_docket_in_objection_period(
            clock=CLOCK,
            examiner_recommended_af=90.00,
            claim_filing_deadline=FILING_DEADLINE,
            claimed_af=100.00,
            use_years=(2024,),
        )
        api_client.decree_adjudication_claim(
            bundle["claim"]["id"], "decree entered on the verified record", ADJUDICATOR
        )
        bundle["docket"] = get_success_data(
            api_client.advance_docket_phase(
                bundle["docket"]["id"], "CLOSED", ADJUDICATOR
            )
        )
        bundle["second_right"] = _junior_stockwater_right(bundle["claimant"]["id"])
        return bundle

    def test_no_phase_advance_leaves_closed(self):
        """PRD §3.10: "A `target_phase` that is not the docket's immediate successor
        is `ERR_INVALID_STATE` (409), and `CLOSED` is terminal."

        `CLOSED` has no successor at all, so neither re-entering the examination
        phase nor re-closing the docket is a declared edge, and both report the
        state failure. The docket keeps the `version` it carried when it closed, so
        PRD §3.10's "reaching `DECREE_ENTERED` freezes `total_decreed_af`" still
        reads 90.00.

        Design: Corner/state_machines/sm_decree_docket_closed_is_terminal_and_read_only
        """
        bundle = self._closed_docket()
        assert bundle["docket"]["phase"] == "CLOSED"
        before = bundle["docket"]["version"]

        backwards = api_client.advance_docket_phase(
            bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
        )
        again = api_client.advance_docket_phase(
            bundle["docket"]["id"], "CLOSED", ADJUDICATOR
        )

        for response in (backwards, again):
            validate_error(
                response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
            )
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "CLOSED"
        assert docket["claim_count"] == 1
        assert docket["decreed_claim_count"] == 1
        assert docket["total_decreed_af"] == pytest.approx(90.00, abs=0.01)
        assert docket["version"] == before

    def test_a_late_filing_reports_the_phase_rather_than_the_state(self):
        """PRD §3.10: "Second, the docket must be in `OPEN_FOR_CLAIMS`, otherwise
        `ERR_DOCKET_PHASE_INVALID` (409)."

        The same closed docket answers a filing attempt in a different vocabulary
        from a phase-advance attempt, because filing is refused by the cross-entity
        phase gate rather than by the docket's own machine. The clock also stands at
        the filing deadline, but PRD §3.10 fixes the order — "filing a fresh claim
        into an advanced docket reports the phase rather than the lateness" — and no
        claim row is created.

        Design: Corner/state_machines/sm_decree_docket_closed_is_terminal_and_read_only
        """
        bundle = self._closed_docket()

        response = api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                bundle["docket"]["id"],
                bundle["second_right"]["id"],
                JUNIOR_PRIORITY,
                50.00,
            ),
            ADJUDICATOR,
        )

        validate_error(
            response, ApiErrorId.ERR_DOCKET_PHASE_INVALID.value, expected_status=409
        )
        claims, meta = validate_paginated(
            api_client.list_adjudication_claims(
                ADJUDICATOR, {"decree_docket_id": bundle["docket"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [claim["id"] for claim in claims] == [bundle["claim"]["id"]]
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "CLOSED"
        assert docket["claim_count"] == 1
