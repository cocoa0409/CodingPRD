"""Transitive cascades (program supersession depth-3, RMA escape depth-2), the
RMA state gates, and the lifecycle-state vs referential priority pair
(PRD §3.2, §3.5, §3.9)."""
from test_helpers import (
    assert_lot_tally_invariant,
    create_rma_case_payload,
    create_test_result_payload,
    mint_revision,
    reserve,
    setup_awaiting_disposition_lot,
    setup_reservation_scenario,
    setup_rma_in_fa,
    setup_shipped_lot,
    supersede_program,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS, QE, list_reviews_for_lot


class TestProgramSupersessionCascade:
    def _setup_cascade(self, api):
        """P1 RELEASED with F1 AVAILABLE; lot QUEUED; chamber (4 slots); R1
        RESERVED on F1 for 2 slots; revision 2 minted, fixtured, validated."""
        ctx = setup_reservation_scenario(
            part_number="PN-700", max_retests_per_unit=1,
            bin_map={"1": "PASS", "9": "HARD_FAIL"}, slot_count=4,
        )
        r1 = reserve(ctx, start_at="2026-06-02T10:00:00Z",
                     end_at="2026-06-02T11:00:00Z", slot_count=2)
        chamber_mid = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber_mid["available_slots"] == 2

        rev2 = mint_revision(ctx["program"]["id"])
        fix2 = validate_success(
            api.create_fixture({"program_id": rev2["id"], "serial_number": "FX-2",
                                "site_count": 4}, ENG1),
            201,
        )
        validate_success(api.commission_fixture(fix2["id"], ENG1), 200)
        validate_success(api.validate_program(rev2["id"], ENG1), 200)
        return ctx, r1, rev2

    def test_supersession_retires_program_and_fixture(self, api):
        """PRD §3.2: "The previously `RELEASED` program for the same `customer_id`
        and `part_number`, if one exists, transitions to `OBSOLETE` with its own
        `version` incremented. Every fixture of that superseded program whose
        `status` is `COMMISSIONING`, `AVAILABLE`, or `UNDER_MAINTENANCE` transitions
        to `DECOMMISSIONED`, again incrementing each fixture's `version`."

        Design: Difficulty/transitive_cascade/program_supersession_cascade_depth3
        """
        ctx, _r1, rev2 = self._setup_cascade(api)
        validate_success(api.release_program(rev2["id"], ENG1), 200)
        # Hop 1: the release itself retires the prior released revision.
        p1 = validate_success(api.get_test_program(ctx["program"]["id"], ENG1), 200)
        assert p1["status"] == "OBSOLETE", "superseded by the released revision 2"
        # Hop 2: caused by hop 1's mutation, not by the release request directly.
        f1 = validate_success(api.get_fixture(ctx["fixture"]["id"], ENG1), 200)
        assert f1["status"] == "DECOMMISSIONED"

    def test_supersession_cancels_reservations_and_frees_slots(self, api):
        """PRD §3.2: "Every chamber reservation still in `RESERVED` status that
        references one of those `DECOMMISSIONED` fixtures is cancelled, incrementing
        each reservation's `version`. Finally, each of those cancellations
        recomputes the affected chamber's `available_slots`, freeing the cancelled
        reservations' slots."

        Design: Difficulty/transitive_cascade/program_supersession_cascade_depth3
        """
        ctx, r1, rev2 = self._setup_cascade(api)
        validate_success(api.release_program(rev2["id"], ENG1), 200)
        # Hop 3: caused by hop 2's decommission.
        r1_after = validate_success(api.get_chamber_reservation(r1["id"], OPS), 200)
        assert r1_after["status"] == "CANCELLED"
        # Hop 4 ledger: the 2 slots freed by hop 3's cancellation.
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber["available_slots"] == 4


class TestLotStateBeatsProgramSuperseded:
    def _setup_awaiting_lot_with_superseded_program(self, api):
        """Lot of 2 (pass + hard-fail) driven to AWAITING_DISPOSITION; the pinned
        revision is then superseded by a released revision 2. Returns
        (ctx, failed_unit, new_fixture)."""
        ctx = setup_awaiting_disposition_lot(
            [1, 9], part_number="PN-910", bin_map={"1": "PASS", "9": "HARD_FAIL"},
            max_retests_per_unit=1,
        )
        new_ctx = supersede_program(ctx)
        return ctx, ctx["units"][1], new_ctx["fixture"]

    def test_state_violation_surfaces_invalid_state(self, api):
        """PRD §2.11: "Incoming requests are validated against a fixed priority
        ladder, and the first failing rung determines the error returned — a request
        that would fail several checks surfaces only the earliest rung's error."
        PRD §3.5: "Recording is refused unless the lot is `IN_TEST`, otherwise
        `ERR_INVALID_STATE`." (Rung 4 lifecycle state precedes rung 8 business
        referential, so the superseded pinned revision is never reached.)

        Design: Difficulty/priority_pair_validation_conflict/lot_state_beats_program_superseded
        """
        ctx, failed_unit, new_fixture = (
            self._setup_awaiting_lot_with_superseded_program(api)
        )
        res = api.create_test_result(
            create_test_result_payload(failed_unit["id"], new_fixture["id"], bin_code=1),
            ENG1,
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_state_violation_persists_nothing(self, api):
        """PRD §3.5: "Recording is refused unless the lot is `IN_TEST`, otherwise
        `ERR_INVALID_STATE`."
        PRD §2.11: "Incoming requests are validated against a fixed priority ladder,
        and the first failing rung determines the error returned — a request that
        would fail several checks surfaces only the earliest rung's error."

        Design: Difficulty/priority_pair_validation_conflict/lot_state_beats_program_superseded
        """
        ctx, failed_unit, new_fixture = (
            self._setup_awaiting_lot_with_superseded_program(api)
        )
        res = api.create_test_result(
            create_test_result_payload(failed_unit["id"], new_fixture["id"], bin_code=1),
            ENG1,
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        unit_after = validate_success(api.get_unit(failed_unit["id"], ENG1), 200)
        assert unit_after["test_status"] == "FAILED", "no insertion was persisted"
        lot_after = validate_success(api.get_lot(ctx["lot"]["id"], OPS), 200)
        assert_lot_tally_invariant(lot_after)


class TestRmaStateGates:
    def test_rma_on_non_shipped_lot_rejected(self, api):
        """PRD §3.9: "The case is admissible only for a genuinely shippable lineage:
        the unit must belong to the referenced lot, the lot must be `SHIPPED`, and
        the unit must stand `PASSED` — otherwise the request is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/validations/rma_on_non_shipped_lot_rejected
        """
        ctx = setup_awaiting_disposition_lot(
            [1], part_number="PN-225", bin_map={"1": "PASS"}, max_retests_per_unit=1
        )
        res = api.create_rma_case(
            create_rma_case_payload(ctx["lot"]["id"], ctx["units"][0]["id"],
                                    failure_mode="premature RMA"),
            ctx["rep_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_rma_close_before_fa_complete_returns_invalid_state(self, api):
        """PRD §3.9: "Closing the case moves it from `FA_COMPLETE` to `CLOSED`."
        (A case in `FA_IN_PROGRESS` has no close transition.)
        PRD §2.11: "the target resource's own state permits the operation — a lot
        `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a
        review `PENDING` for a decision, an audit `OPEN` for close, a reservation
        `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED`
        for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/rma_close_before_fa_complete_returns_invalid_state
        """
        ctx = setup_rma_in_fa(
            quantity=1, part_number="PN-210", bin_map={"1": "PASS"},
            max_retests_per_unit=1,
        )
        res = api.close_rma_case(ctx["rma"]["id"], QE)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        rma_after = validate_success(api.get_rma_case(ctx["rma"]["id"], QE), 200)
        assert rma_after["fa_status"] == "FA_IN_PROGRESS", (
            "rejected close must change nothing"
        )


class TestRmaEscapeCascade:
    def _setup_escape(self, api):
        """Lot of 2, both passed first insertion, SHIPPED; RMA on unit 1 carried to
        FA_COMPLETE with conclusion TEST_ESCAPE."""
        ctx = setup_shipped_lot(quantity=2, part_number="PN-800")
        rma = validate_success(
            api.create_rma_case(
                create_rma_case_payload(ctx["lot"]["id"], ctx["units"][0]["id"],
                                        failure_mode="field failure at customer"),
                ctx["rep_headers"],
            ),
            201,
        )
        validate_success(api.start_rma_fa(rma["id"], QE), 200)
        validate_success(
            api.complete_rma_fa(rma["id"], {"fa_conclusion": "TEST_ESCAPE"}, QE), 200
        )
        return ctx, rma

    def test_escape_close_contains_lot_and_reclassifies_unit(self, api):
        """PRD §3.9: "When the recorded conclusion is `TEST_ESCAPE`, closing fires
        the containment cascade on the source lot: the lot's `escape_count`
        increments by one; the escaped unit's `test_status` flips to `FAILED` with
        its `current_bin` nulled; the lot's tallies are recomputed, moving one unit
        from the passed count to the failed count; the lot itself transitions from
        `SHIPPED` to `CONTAINED`; and its `suggested_disposition` is recomputed —
        with an escape count of at least 1, the first branch of the suggestion rule
        forces `SCRAP_REVIEW`."

        Design: Difficulty/transitive_cascade/rma_escape_cascade_creates_review
        """
        ctx, rma = self._setup_escape(api)
        validate_success(api.close_rma_case(rma["id"], QE), 200)
        lot = validate_success(api.get_lot(ctx["lot"]["id"], QE), 200)
        assert lot["status"] == "CONTAINED"
        assert lot["escape_count"] == 1
        assert lot["units_passed"] == 1 and lot["units_failed"] == 1, (
            "the escaped unit moved from the passed count to the failed count"
        )
        assert_lot_tally_invariant(lot)
        unit = validate_success(api.get_unit(ctx["units"][0]["id"], QE), 200)
        assert unit["test_status"] == "FAILED"
        assert unit["current_bin"] is None

    def test_escape_close_auto_creates_scrap_review(self, api):
        """PRD §3.9: "A lot disposition review is then created automatically in
        `PENDING` status carrying that `SCRAP_REVIEW` suggestion, and the MRB
        decides containment per §3.6 — releasing the lot back to `SHIPPED`,
        scrapping it, or looping it through rework."
        PRD §3.6: "When the lot's `escape_count` is at least 1, the suggestion is
        `SCRAP_REVIEW`."

        Design: Difficulty/transitive_cascade/rma_escape_cascade_creates_review
        """
        ctx, rma = self._setup_escape(api)
        validate_success(api.close_rma_case(rma["id"], QE), 200)
        reviews = list_reviews_for_lot(ctx["lot"]["id"])
        assert len(reviews) == 1, "the containment auto-creates exactly one review"
        assert reviews[0]["status"] == "PENDING"
        assert reviews[0]["suggested_disposition"] == "SCRAP_REVIEW"
        lot = validate_success(api.get_lot(ctx["lot"]["id"], QE), 200)
        assert lot["suggested_disposition"] == "SCRAP_REVIEW"
        # The unit census still sums to the lot quantity after the cascade.
        assert_lot_tally_invariant(lot)
