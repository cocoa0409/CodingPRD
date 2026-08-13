"""Loss reports: verification cascade, invalid transitions, headcount ledger."""
from test_helpers import (
    ApiErrorId,
    create_flock,
    create_loss_report,
    create_move,
    create_pasture,
    create_sale,
    log_birth,
    pay_sale,
    set_clock,
    setup_active_contract,
    transition_loss_report,
    validate_error,
    validate_success,
)
from test_helpers import create_season_in_state


class TestLossVerificationCascade:

    def test_loss_verify_cascade_headcount_breach_moves(self, api, ranch_manager_headers, grazing_client_headers, range_hand_headers):
        """PRD §3.7: "Verification fires the heaviest cascade in the system,
        three links deep. Link one writes the loss into the flock ledger:
        `current_headcount` drops by `head_lost` and the flock's `version`
        increments. Link two sweeps the flock's grazing contracts: every
        contract in `ACTIVE` status whose `min_head` now exceeds the reduced
        headcount has its `breach_flag` set to true and its `version`
        incremented. Link three cleans up the breached contracts' books: every
        grazing move whose `contract_id` is one of the newly breached contracts
        and whose `move_status` is still `PLANNED` is moved to `CANCELLED`".

        Design: Difficulty/transitive_cascade/loss_verify_cascade_headcount_breach_moves
        """
        flock = create_flock(flock_name="Cascade Ranch", species="SHEEP",
                             baseline_headcount=200, guardian_dog_count=3)
        contract = setup_active_contract(
            flock["id"], client_org_name="Fire District", parcel_name="Fuel Break 7",
            rate_per_head_day_cents=100, min_head=150, max_head=600,
            target_cover_reduction_pct=70.0, clock_in_window="2026-09-10T00:00:00Z")
        pasture = create_pasture(pasture_name="Home Pivot", acres=640.0, carrying_capacity_head=500)
        mv_home = create_move(flock["id"], pasture_id=pasture["id"],
                              move_start="2026-09-12T00:00:00Z", move_end="2026-09-20T00:00:00Z",
                              head_count=100)
        mv_contract = create_move(flock["id"], contract_id=contract["id"],
                                  move_start="2026-09-12T00:00:00Z", move_end="2026-09-25T00:00:00Z",
                                  head_count=180)

        report = create_loss_report(flock["id"], loss_date="2026-09-09T00:00:00Z",
                                    head_lost=60, predator_type="COYOTE", guardian_on_duty=True)
        transition_loss_report(report["id"], "UNDER_REVIEW")
        report = transition_loss_report(report["id"], "VERIFIED")
        assert report["report_status"] == "VERIFIED"

        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 140, "200 - 60 verified loss"

        contract = validate_success(api.get_grazing_contract(contract["id"], ranch_manager_headers))
        assert contract["breach_flag"] is True, "140 < min_head 150 -> breach"
        assert contract["contract_status"] == "ACTIVE", "breach does not move the machine"

        mv_contract = validate_success(api.get_grazing_move(mv_contract["id"], range_hand_headers))
        assert mv_contract["move_status"] == "CANCELLED", "breach cascade cancels PLANNED contract moves"
        mv_home = validate_success(api.get_grazing_move(mv_home["id"], range_hand_headers))
        assert mv_home["move_status"] == "PLANNED", (
            "own-ranch move not linked to the breached contract is untouched"
        )

    def test_loss_verify_below_breach_threshold_no_breach(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.7: "every contract in `ACTIVE` status whose `min_head` now
        exceeds the reduced headcount has its `breach_flag` set to true" — a
        contract whose min_head still fits is not breached.

        Design: Difficulty/transitive_cascade/loss_verify_cascade_headcount_breach_moves
        """
        flock = create_flock(flock_name="Cascade2 Ranch", species="SHEEP", baseline_headcount=200)
        contract = setup_active_contract(
            flock["id"], client_org_name="Fire District", parcel_name="Fuel Break 8",
            rate_per_head_day_cents=100, min_head=100, max_head=600,
            target_cover_reduction_pct=70.0, clock_in_window="2026-09-10T00:00:00Z")
        mv_contract = create_move(flock["id"], contract_id=contract["id"],
                                  move_start="2026-09-12T00:00:00Z", move_end="2026-09-25T00:00:00Z",
                                  head_count=120)
        report = create_loss_report(flock["id"], loss_date="2026-09-09T00:00:00Z",
                                    head_lost=60, predator_type="COYOTE", guardian_on_duty=True)
        transition_loss_report(report["id"], "UNDER_REVIEW")
        transition_loss_report(report["id"], "VERIFIED")

        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 140
        contract = validate_success(api.get_grazing_contract(contract["id"], ranch_manager_headers))
        assert contract["breach_flag"] is False, "140 >= min_head 100 -> no breach"
        mv_contract = validate_success(api.get_grazing_move(mv_contract["id"], range_hand_headers))
        assert mv_contract["move_status"] == "PLANNED", "no breach -> no move cascade"


class TestLossReportMachine:

    def test_loss_report_verify_from_reported_rejected(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.7: "From `UNDER_REVIEW` the manager either verifies
        (`UNDER_REVIEW -> VERIFIED`) or dismisses (`UNDER_REVIEW ->
        DISMISSED`); dismissal is also available directly from `REPORTED`. Any
        other transition is rejected with `ERR_REPORT_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/loss_report_verify_from_reported_rejected
        """
        flock = create_flock(flock_name="Report Ranch", species="SHEEP", baseline_headcount=500)
        report = create_loss_report(flock["id"], loss_date="2026-08-10T00:00:00Z",
                                    head_lost=6, predator_type="MOUNTAIN_LION",
                                    guardian_on_duty=False)
        assert report["report_status"] == "REPORTED"
        resp = api.transition_loss_report(report["id"], {"to": "VERIFIED"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE.value, expected_status=409)
        report = validate_success(api.get_loss_report(report["id"], ranch_manager_headers))
        assert report["report_status"] == "REPORTED"
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 500, "no cascade fired"

    def test_headcount_reconciliation_chronological(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §2.10: "It is derived as the flock's `baseline_headcount`, plus
        the sum of `born_alive` over every birth record logged against any of
        the flock's seasons (regardless of season status), minus the sum of
        `head_lost` over the flock's loss reports in `VERIFIED` status, minus
        the sum of `head_count` over the flock's delivered `MEAT` sales, minus
        the sum of `actual_head_delivered` over the flock's delivered
        `BREEDING` sales."
        PRD §3.7: "A report that is dismissed touches nothing."

        Design: Corner/calculations/headcount_reconciliation_chronological
        """
        flock = create_flock(flock_name="Ledger Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season_in_state(flock["id"], "LAMBING")
        log_birth(season["id"], birth_date="2026-12-30T06:00:00Z",
                  births_reported=100, born_alive=90, born_dead=10)
        log_birth(season["id"], birth_date="2027-01-05T06:00:00Z",
                  births_reported=50, born_alive=48, born_dead=2)
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 638, "500 + 138 live births"

        report = create_loss_report(flock["id"], loss_date="2027-01-10T00:00:00Z",
                                    head_lost=6, predator_type="EAGLE", guardian_on_duty=True)
        transition_loss_report(report["id"], "UNDER_REVIEW")
        transition_loss_report(report["id"], "VERIFIED")
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 632, "638 - 6 verified loss"

        # A dismissed report is not a headcount event.
        report2 = create_loss_report(flock["id"], loss_date="2027-01-12T00:00:00Z",
                                     head_lost=4, predator_type="DOG", guardian_on_duty=True)
        transition_loss_report(report2["id"], "DISMISSED")
        report2 = validate_success(api.get_loss_report(report2["id"], ranch_manager_headers))
        assert report2["report_status"] == "DISMISSED"

        sale = create_sale(flock["id"], sale_type="MEAT", channel="DIRECT", head_count=40,
                           avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
                           scheduled_date="2027-01-15T00:00:00Z")
        pay_sale(sale["id"], sale["booked_price_cents"])
        validate_success(api.load_sale(sale["id"], range_hand_headers))
        sale = validate_success(api.deliver_sale(
            sale["id"], {"actual_total_weight_lbs": 3900.0}, range_hand_headers))
        assert sale["settled_price_cents"] == 780000, (
            "3900 lbs * 20000/100; DIRECT with default shrink 0"
        )
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 592, "632 - 0 (dismissed) - 40 delivered"


class TestFlockRetireGuard:

    def test_flock_retire_while_busy_rejected(self, api, ranch_manager_headers):
        """PRD §3.1: "Retirement is the flock's only transition, `ACTIVE ->
        RETIRED`, and it is guarded by a busy-children sweep: the flock must
        have no breeding season in `PLANNED`, `BREEDING`, `GESTATION`,
        `LAMBING`, or `WEANING`; no grazing move in `PLANNED` or `ACTIVE`; no
        shearing event in `SCHEDULED` or `IN_PROGRESS`; no livestock sale whose
        `delivery_status` is `PENDING` or `LOADED`; and no grazing contract in
        `DRAFT`, `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `ACTIVE`. Any
        violation is rejected with `ERR_FLOCK_BUSY` (HTTP 409)."

        Design: Corner/state_machines/flock_retire_while_busy_rejected
        """
        from test_helpers import create_season
        flock = create_flock(flock_name="Busy Ranch", species="SHEEP", baseline_headcount=500)
        create_season(flock["id"], season_label="2026-fall", ewes_bred=200,
                      breeding_start_date="2026-08-05T00:00:00Z",
                      breeding_end_date="2026-09-19T00:00:00Z")
        resp = api.retire_flock(flock["id"], ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCK_BUSY.value, expected_status=409)
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["flock_status"] == "ACTIVE"
