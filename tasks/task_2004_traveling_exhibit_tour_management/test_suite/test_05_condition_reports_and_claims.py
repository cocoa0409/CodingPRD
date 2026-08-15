"""Condition scoring, damage holds, and claim adjudication (PRD §3.6, §3.7)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    plan_first_leg,
    setup_received_shipment,
    file_report,
    file_and_submit_report,
    transition_report,
    create_claim_payload,
)

TM = TEST_USERS["tour_manager_headers"]
REG = TEST_USERS["registrar_headers"]
INS = TEST_USERS["insurer_headers"]


class TestCompositeScoreVariants:
    def _setup_two_crate_shipment(self, api):
        return setup_received_shipment(
            crate_values=[4000000, 5000000],
            crate_count=2,
            declared_value_cents=9000000,
            venue_overrides={"name": "Hall A", "city": "Portland"},
            stop_overrides={
                "install_start": "2026-09-10T00:00:00Z",
                "open_date": "2026-09-15T00:00:00Z",
                "close_date": "2026-10-15T00:00:00Z",
                "teardown_end": "2026-10-20T00:00:00Z",
                "projected_attendance": 5000,
            },
            title="Gems",
            exhibit_code="GEMS-2026",
            refurbishment_gap_days=5,
        )

    def test_intact_seal_weighted_blend(self, api):
        """PRD §3.7: "The composite is a weighted blend — forty percent of the
        `surface_score` plus sixty percent of the `structural_score`, rounded
        half-up to a whole number — with one override: when `seal_intact` is
        false, the composite is capped at forty no matter how high the weighted
        blend ran."

        Design: Difficulty/dual_variant_calc/condition_score_seal_breach_vs_intact_diverge
        """
        tour, crates, venue, stop, contract, shipment = self._setup_two_crate_shipment(api)
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=90,
            structural_score=80,
            seal_intact=True,
        )
        # round_half_up(90*0.4 + 80*0.6) = round(36+48) = 84.
        assert report["composite_score"] == 84

    def test_breached_seal_caps_at_forty_and_holds_shipment(self, api):
        """PRD §3.7: "when `seal_intact` is false, the composite is capped at
        forty no matter how high the weighted blend ran."
        PRD §3.6: "the moment an `UNPACK` report on the shipment is submitted
        with a composite score below seventy, the shipment drops `RECEIVED` →
        `DAMAGE_HOLD`."

        Design: Difficulty/dual_variant_calc/condition_score_seal_breach_vs_intact_diverge
        """
        tour, crates, venue, stop, contract, shipment = self._setup_two_crate_shipment(api)
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[1]["id"],
            surface_score=90,
            structural_score=80,
            seal_intact=False,
        )
        assert report["composite_score"] == 40
        shipment_after = validate_success(
            api.get_shipment(tour["id"], shipment["id"], TM), 200
        )
        assert shipment_after["status"] == "DAMAGE_HOLD"


class TestDamageHoldBlocksInstall:
    def _setup_damage_hold(self, api):
        """Stop CONTRACTED, shipment RECEIVED, low-scoring UNPACK report filed."""
        return setup_received_shipment(
            venue_overrides={"name": "Clay Center", "city": "Asheville"},
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-04T00:00:00Z",
                "close_date": "2026-10-04T00:00:00Z",
                "teardown_end": "2026-10-07T00:00:00Z",
                "projected_attendance": 6000,
            },
            contract_overrides={"base_fee_cents": 400000, "sponsorship_credit_cents": 0},
            title="Pottery",
            exhibit_code="POTT-2026",
            declared_value_cents=3000000,
            refurbishment_gap_days=2,
        )

    def test_submit_low_score_computes_composite_and_holds_shipment(self, api):
        """PRD §3.7: "Submission computes the report's `composite_score` and moves
        it `DRAFT` → `SUBMITTED`."
        PRD §3.6: "the moment an `UNPACK` report on the shipment is submitted
        with a composite score below seventy, the shipment drops `RECEIVED` →
        `DAMAGE_HOLD`."

        Design: Difficulty/transitive_cascade/report_submit_cascades_to_shipment_and_blocks_install
        """
        tour, crates, venue, stop, contract, shipment = self._setup_damage_hold(api)
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=60,
            structural_score=50,
            seal_intact=True,
        )
        # round_half_up(60*0.4 + 50*0.6) = round(24+30) = 54.
        assert report["composite_score"] == 54
        shipment_after = validate_success(
            api.get_shipment(tour["id"], shipment["id"], TM), 200
        )
        assert shipment_after["status"] == "DAMAGE_HOLD"

    def test_begin_install_rejected_while_damage_hold(self, api):
        """PRD §3.8: "the inbound shipment bound for this stop must be `RECEIVED`
        or `CLEARED`, so a shipment sitting in `DAMAGE_HOLD` stalls installation
        until its claims resolve; any failed precondition rejects the move with
        `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/report_submit_cascades_to_shipment_and_blocks_install
        """
        tour, crates, venue, stop, contract, shipment = self._setup_damage_hold(api)
        file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=60,
            structural_score=50,
            seal_intact=True,
        )
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "CONTRACTED"


class TestDamageHoldCycle:
    def _setup_hold_with_claim(self, api):
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            venue_overrides={"name": "Tribal Arts Hall", "city": "Chicago"},
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-04T00:00:00Z",
                "close_date": "2026-10-04T00:00:00Z",
                "teardown_end": "2026-10-07T00:00:00Z",
                "projected_attendance": 4000,
            },
            title="Masks",
            exhibit_code="MASK-2026",
            declared_value_cents=2000000,
            refurbishment_gap_days=2,
        )
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=90,
            structural_score=80,
            seal_intact=False,
        )
        claim = get_success_data(
            api.create_claim(
                tour["id"],
                shipment["id"],
                create_claim_payload(
                    report["id"],
                    100000,
                    [{"description": "seal breach handling", "amount_cents": 100000}],
                ),
                REG,
            )
        )
        validate_success(
            api.transition_claim(
                tour["id"], shipment["id"], claim["id"], {"action": "REVIEW"}, TM
            ),
            200,
        )
        return tour, shipment, claim

    def test_deny_releases_hold_and_zeroes_payout(self, api):
        """PRD §3.7: "Denial (`DENY`) instead sets `assessed_payout_cents` to
        zero."
        PRD §3.7: "Both denial and payment re-examine the shipment's damage hold
        with the same rule: once no claim on the shipment remains in `FILED`,
        `UNDER_REVIEW`, or `APPROVED`, a held shipment returns from
        `DAMAGE_HOLD` to `RECEIVED`."

        Design: Difficulty/non_linear_state_machine/shipment_received_damage_hold_cycle
        """
        tour, shipment, claim = self._setup_hold_with_claim(api)
        res = api.transition_claim(
            tour["id"], shipment["id"], claim["id"], {"action": "DENY"}, INS
        )
        denied = validate_success(res, 200)
        assert denied["status"] == "DENIED"
        assert denied["assessed_payout_cents"] == 0
        shipment_after = validate_success(
            api.get_shipment(tour["id"], shipment["id"], TM), 200
        )
        assert shipment_after["status"] == "RECEIVED"

    def test_hold_releases_to_received_not_cleared(self, api):
        """PRD §3.6: "The hold releases — `DAMAGE_HOLD` → `RECEIVED` — only once
        every damage claim on the shipment has reached `PAID` or `DENIED`, and a
        shipment may cycle through the loop more than once."

        Design: Difficulty/non_linear_state_machine/shipment_received_damage_hold_cycle
        """
        tour, shipment, claim = self._setup_hold_with_claim(api)
        # Confirm the hold is standing before denial.
        held = validate_success(api.get_shipment(tour["id"], shipment["id"], TM), 200)
        assert held["status"] == "DAMAGE_HOLD"
        validate_success(
            api.transition_claim(
                tour["id"], shipment["id"], claim["id"], {"action": "DENY"}, INS
            ),
            200,
        )
        after = validate_success(api.get_shipment(tour["id"], shipment["id"], TM), 200)
        assert after["status"] == "RECEIVED"


class TestClaimPayoutRoundingOrder:
    def _setup_under_review_claim(self, api, line_items, claimed_amount):
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            venue_overrides={"name": "Chapel Gallery", "city": "Santa Fe"},
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-03T00:00:00Z",
                "close_date": "2026-10-03T00:00:00Z",
                "teardown_end": "2026-10-06T00:00:00Z",
                "projected_attendance": 3000,
            },
            title="Icons",
            exhibit_code="ICON-2026",
            declared_value_cents=8000000,
            refurbishment_gap_days=2,
        )
        # Certificate above declared value so coverage is not binding.
        get_success_data(
            api.create_certificate(
                tour["id"],
                {
                    "tour_stop_id": stop["id"],
                    "insurer_name": "Axis",
                    "coverage_cents": 9000000,
                    "effective_from": "2026-08-01T00:00:00Z",
                    "effective_to": "2026-11-01T00:00:00Z",
                },
                INS,
            )
        )
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=60,
            structural_score=50,
            seal_intact=True,
        )
        claim = get_success_data(
            api.create_claim(
                tour["id"],
                shipment["id"],
                create_claim_payload(report["id"], claimed_amount, line_items),
                REG,
            )
        )
        validate_success(
            api.transition_claim(
                tour["id"], shipment["id"], claim["id"], {"action": "REVIEW"}, TM
            ),
            200,
        )
        return tour, shipment, claim

    def test_per_line_rounding_before_sum(self, api):
        """PRD §3.7: "An approved claim gets its `assessed_payout_cents`: each
        line item's `amount_cents` is multiplied by eighty percent and rounded
        half-up to whole cents, those per-line figures are summed into a
        subtotal, and the payout is the lesser of that subtotal and ninety
        percent of the `claimed_amount_cents` — the cap itself rounded half-up
        to whole cents."

        Design: Difficulty/combinatorial_formula/damage_claim_payout_rounding_order
        """
        lines = [
            {"description": "corner chip", "amount_cents": 13},
            {"description": "frame scratch", "amount_cents": 13},
            {"description": "glass scuff", "amount_cents": 13},
        ]
        tour, shipment, claim = self._setup_under_review_claim(api, lines, 39)
        res = api.transition_claim(
            tour["id"], shipment["id"], claim["id"], {"action": "APPROVE"}, INS
        )
        approved = validate_success(res, 200)
        # per-line round_half_up(13*0.8)=10; subtotal 30; cap round(39*0.9)=35.
        assert approved["assessed_payout_cents"] == 30

    def test_cap_binds_when_subtotal_exceeds_ninety_percent(self, api):
        """PRD §3.7: "the payout is the lesser of that subtotal and ninety
        percent of the `claimed_amount_cents` — the cap itself rounded half-up
        to whole cents."

        Design: Difficulty/combinatorial_formula/damage_claim_payout_rounding_order
        """
        # One line of 1000 cents: per-line round(800)=800; subtotal 800;
        # cap round(1000*0.9)=900 -> payout 800. Use two lines so per-line sum
        # exceeds the cap: 2 x 600 -> per-line 480 each, subtotal 960; claim
        # total 1050 -> cap round(945)=945 -> payout 945 < 960.
        lines = [
            {"description": "panel crack", "amount_cents": 600},
            {"description": "hinge bend", "amount_cents": 450},
        ]
        tour, shipment, claim = self._setup_under_review_claim(api, lines, 1050)
        res = api.transition_claim(
            tour["id"], shipment["id"], claim["id"], {"action": "APPROVE"}, INS
        )
        approved = validate_success(res, 200)
        # per-line: round(480)=480, round(360)=360 -> subtotal 840;
        # cap round(1050*0.9)=945 -> payout = min(840, 945) = 840.
        assert approved["assessed_payout_cents"] == 840


class TestClaimAmountMismatch:
    def test_claimed_total_not_matching_lines_rejected(self, api):
        """PRD §3.7: "The filing is refused with `ERR_CLAIM_AMOUNT_MISMATCH`
        (HTTP 422) when the itemization is empty or when the claimed total does
        not equal the sum of its line amounts."

        Design: Corner/validations/claim_amount_mismatch_rejected
        """
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            title="Silver", exhibit_code="SLVR-2026", declared_value_cents=2000000
        )
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=50,
            structural_score=40,
            seal_intact=True,
        )
        res = api.create_claim(
            tour["id"],
            shipment["id"],
            create_claim_payload(
                report["id"],
                100000,
                [{"description": "scratch", "amount_cents": 60000}],
            ),
            REG,
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_AMOUNT_MISMATCH)


class TestCrateNotOnShipment:
    def test_report_for_crate_off_manifest_rejected(self, api):
        """PRD §3.7: "A report naming a `crate_id` that is not on the shipment's
        manifest is refused with `ERR_CRATE_NOT_ON_SHIPMENT`."

        Design: Corner/validations/report_for_crate_not_on_shipment_rejected
        """
        # Two crates in inventory; the shipment manifest carries only the first.
        tour, crates = create_and_open_booking(
            crate_values=[100000, 100000], crate_count=2, declared_value_cents=200000
        )
        venue = create_venue(name="Auto Hall")
        stop = book_stop(tour["id"], venue["id"])
        shipment = plan_first_leg(tour["id"], stop["id"], [crates[0]["id"]])
        res = api.create_report(
            tour["id"],
            shipment["id"],
            {
                "crate_id": crates[1]["id"],
                "inspector_name": "Reg",
                "phase": "UNPACK",
                "surface_score": 90,
                "structural_score": 90,
                "seal_intact": True,
            },
            REG,
        )
        validate_error(res, ApiErrorId.ERR_CRATE_NOT_ON_SHIPMENT)


class TestStateBeatsFiscalOnClaimApprove:
    def test_approve_from_filed_returns_invalid_state(self, api):
        """PRD §2.8: "Where several checks guard a single request, they fire in a
        fixed order rather than text order: authentication, then authorization,
        then left-to-right path existence, then the stale-version rejection on
        the one OCC-guarded write, then transition state validity — a transition
        attempted from a state that does not permit it fails with
        `ERR_INVALID_STATE` (HTTP 409) — and finally the business rules."
        PRD §3.7: "Adjudication runs `FILED` → `UNDER_REVIEW` → `APPROVED` →
        `PAID`, with a denial exit off review."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_claim_approve
        """
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            venue_overrides={"name": "Gem Hall", "city": "Tucson"},
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-03T00:00:00Z",
                "close_date": "2026-10-03T00:00:00Z",
                "teardown_end": "2026-10-06T00:00:00Z",
                "projected_attendance": 1000,
            },
            title="Jewels",
            exhibit_code="JEWL-2026",
            declared_value_cents=2000000,
            refurbishment_gap_days=0,
        )
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=50,
            structural_score=40,
            seal_intact=True,
        )
        claim = get_success_data(
            api.create_claim(
                tour["id"],
                shipment["id"],
                create_claim_payload(
                    report["id"],
                    99999999,
                    [{"description": "total loss", "amount_cents": 99999999}],
                ),
                REG,
            )
        )
        # Claim is FILED (not UNDER_REVIEW) AND exceeds certificate coverage.
        res = api.transition_claim(
            tour["id"], shipment["id"], claim["id"], {"action": "APPROVE"}, INS
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_from_under_review_with_excess_amount_returns_fiscal_error(self, api):
        """PRD §3.7: "Approval (`APPROVE`) is capped by coverage: the
        `claimed_amount_cents` must not exceed the `coverage_cents` of an
        `ISSUED` or `ACTIVE` certificate covering the destination stop, or the
        claim is refused with `ERR_CLAIM_EXCEEDS_COVERAGE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_claim_approve
        """
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            title="Jewels",
            exhibit_code="JEWL-2026",
            declared_value_cents=2000000,
        )
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=50,
            structural_score=40,
            seal_intact=True,
        )
        claim = get_success_data(
            api.create_claim(
                tour["id"],
                shipment["id"],
                create_claim_payload(
                    report["id"],
                    99999999,
                    [{"description": "total loss", "amount_cents": 99999999}],
                ),
                REG,
            )
        )
        validate_success(
            api.transition_claim(
                tour["id"], shipment["id"], claim["id"], {"action": "REVIEW"}, TM
            ),
            200,
        )
        # Now UNDER_REVIEW; only the fiscal coverage rule can fail.
        res = api.transition_claim(
            tour["id"], shipment["id"], claim["id"], {"action": "APPROVE"}, INS
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_EXCEEDS_COVERAGE)


class TestDerivedCrateConditionScore:
    def test_condition_score_null_until_report_accepted(self, api):
        """PRD §3.1: "A crate is born with `location_status` `AT_ORIGIN`, a null
        `condition_score`, and an empty `current_stop_id`."
        PRD §3.7: "From `SUBMITTED`, acceptance (`ACCEPT`, by the `TourManager`)
        moves the report to terminal `ACCEPTED` and writes its `composite_score`
        onto the crate as the crate's new `condition_score`."

        Design: Corner/cross_cutting_layers/derived_field_crate_condition_score_reconciles_on_accept
        """
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            title="Score", exhibit_code="SCOR-2026", declared_value_cents=100000
        )
        crate_before = validate_success(
            api.get_crate(tour["id"], crates[0]["id"], TM), 200
        )
        assert crate_before["condition_score"] is None
        report = file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=90,
            structural_score=80,
            seal_intact=True,
        )
        assert report["composite_score"] == 84
        validate_success(
            api.transition_report(
                tour["id"], shipment["id"], report["id"], {"action": "ACCEPT"}, TM
            ),
            200,
        )
        crate_after = validate_success(
            api.get_crate(tour["id"], crates[0]["id"], TM), 200
        )
        assert crate_after["condition_score"] == 84

    def test_condition_score_not_written_on_submit_alone(self, api):
        """PRD §3.7: "From `SUBMITTED`, acceptance (`ACCEPT`, by the
        `TourManager`) moves the report to terminal `ACCEPTED` and writes its
        `composite_score` onto the crate as the crate's new `condition_score`."

        Design: Corner/cross_cutting_layers/derived_field_crate_condition_score_reconciles_on_accept
        """
        tour, crates, venue, stop, contract, shipment = setup_received_shipment(
            title="Score", exhibit_code="SCOR-2026", declared_value_cents=100000
        )
        file_and_submit_report(
            tour["id"],
            shipment["id"],
            crates[0]["id"],
            surface_score=90,
            structural_score=80,
            seal_intact=True,
        )
        crate_mid = validate_success(
            api.get_crate(tour["id"], crates[0]["id"], TM), 200
        )
        assert crate_mid["condition_score"] is None
