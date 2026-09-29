"""The credit ledger across a lease's life, and the two settlement valuations.

PRD §3.9: "A water bank account is the second of the two conserved ledgers."
"""
import pytest
from test_helpers import ApiErrorId, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    ANALYST,
    activate_right,
    add_point_of_diversion,
    add_use_record,
    certify_study,
    create_study,
    create_water_right,
    deposit,
    read_account,
    read_lease,
    read_right,
    reserve_lease,
    set_clock,
    setup_authorized_headgate_account,
)


class TestReserveCancelRestoresTheCreditLedger:
    """PRD §3.9 — reservation and cancellation from `RESERVED` are a compensating
    pair.

    An 80.00 AF deposit funds one account; a 25.00 AF lease is reserved over
    `[2026-04-01, 2026-06-30)` under `SEASON_BLOCK` and then cancelled before the
    window ever opens, with the logical clock still at 2026-03-01.
    """

    WINDOW = ("2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z")

    def _reserved(self):
        bundle = setup_authorized_headgate_account(deposit_af=80.00)
        bundle["lease"] = get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pod"]["id"],
                self.WINDOW[0],
                self.WINDOW[1],
                25.00,
                valuation_method="SEASON_BLOCK",
            )
        )
        return bundle

    def test_reservation_repartitions_credit_without_moving_the_right(self):
        """PRD §3.9: "The lease is created in `RESERVED`, `committed_credit_af`
        increases and `available_credit_af` decreases by `requested_af` — the
        credit identity is conserved because the total is merely repartitioned".

        PRD §2.9: "The second conserved quantity lives on each water bank account,
        where the identity `deposited_credit_af` equals `available_credit_af` plus
        `committed_credit_af` plus `leased_out_af` must likewise hold exactly at 2
        decimal places." The deposit had already moved
        80.00 AF out of the right's `transferable_af` and into its
        `encumbered_af`; reserving a lease against that credit moves nothing more
        on the right.

        Design: Difficulty/compensating_invariant/bank_credit_ledger_reserve_cancel
        """
        bundle = self._reserved()

        assert bundle["lease"]["status"] == "RESERVED"
        assert bundle["lease"]["used_af"] == pytest.approx(0.00, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(80.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(25.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(55.00, abs=0.01)
        assert account["posture"] == "OPEN"
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(80.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(115.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"

    def test_cancelling_from_reserved_restores_every_credit_term(self):
        """PRD §3.9: "From `RESERVED` it is the exact compensating action for
        reservation: `used_af` is 0.00 regardless of `valuation_method` because
        delivery never began, `settlement_credit_af` is the whole `requested_af`,
        and the credit moves out of `committed_credit_af` and back into
        `available_credit_af`, restoring every individual term of the credit ledger
        to its precise pre-reservation value."

        The `SEASON_BLOCK` valuation is deliberately irrelevant here. Cancelling a
        lease is not a withdrawal: the 80.00 AF bank hold stays on the right,
        because PRD §3.9 only decreases `deposited_credit_af` by `used_af`, which
        is zero.

        Design: Difficulty/compensating_invariant/bank_credit_ledger_reserve_cancel
        """
        bundle = self._reserved()

        lease = get_success_data(
            api_client.cancel_lease_assignment(
                bundle["lease"]["id"], "Lessee released the water back to the bank.", ANALYST
            )
        )

        assert lease["status"] == "CANCELLED"
        assert lease["valuation_method"] == "SEASON_BLOCK"
        assert lease["used_af"] == pytest.approx(0.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(25.00, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(80.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(80.00, abs=0.01)
        assert account["posture"] == "OPEN"
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(80.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(115.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"


class TestSettlementValuationVariants:
    """PRD §3.9 — "The settlement split is where the two valuation methods
    diverge, and its rounding is pinned in two steps."

    One account is funded with 90.00 AF from each of two bank-enrolled rights,
    each right carrying its own authorized headgate. Two 60.00 AF leases run the
    identical window `[2026-04-01, 2026-07-30)` — a term of 120 whole days — and
    are activated together on 2026-04-05. They differ in one field only:
    `valuation_method`. Both are then terminated at the same instant,
    2026-05-11, which is 40 whole days after the window opened.
    """

    WINDOW = ("2026-04-01T00:00:00Z", "2026-07-30T00:00:00Z")
    TERMINATION = "2026-05-11T00:00:00Z"

    def _second_certified_right(self, claimant_id):
        right = create_water_right(
            claimant_id, right_number="WR-2198-002", bank_enrolled=True
        )
        pod = add_point_of_diversion(
            right["id"],
            legal_description="SW1/4 SEC 18 T3N R4E lower headgate",
            stream_reach_code="SNK-14-B",
        )
        for year in (2023, 2024, 2025):
            add_use_record(
                right["id"],
                year,
                reported_diversion_af=300.000,
                irrigated_acres=100.00,
                verification_source="METER",
            )
        activate_right(right["id"])
        study = get_success_data(create_study(right["id"], 2023, 2025))
        certify_study(study["id"], right["id"])
        return read_right(right["id"]), get_success_data(
            api_client.get_point_of_diversion(pod["id"], ANALYST)
        )

    def _two_active_leases(self):
        bundle = setup_authorized_headgate_account(deposit_af=90.00)
        account_id = bundle["account"]["id"]
        second_right, second_pod = self._second_certified_right(
            bundle["claimant"]["id"]
        )
        deposit(account_id, second_right["id"], 90.00)
        leases = {}
        for method, right, pod in (
            ("PRO_RATA_DAILY", bundle["right"], bundle["pod"]),
            ("SEASON_BLOCK", second_right, second_pod),
        ):
            leases[method] = get_success_data(
                reserve_lease(
                    account_id,
                    right["id"],
                    pod["id"],
                    self.WINDOW[0],
                    self.WINDOW[1],
                    60.00,
                    diversion_rate_cfs=1.000,
                    valuation_method=method,
                )
            )
        set_clock("2026-04-05T00:00:00Z")
        for method in leases:
            leases[method] = get_success_data(
                api_client.activate_lease_assignment(leases[method]["id"], ANALYST)
            )
        set_clock(self.TERMINATION)
        bundle["leases"] = leases
        bundle["second_right"] = second_right
        return bundle

    def _cancel(self, lease_id):
        return get_success_data(
            api_client.cancel_lease_assignment(
                lease_id, "Lessee finished early; settle the balance.", ANALYST
            )
        )

    def test_pro_rata_daily_charges_exactly_the_elapsed_days(self):
        """PRD §3.9: "Under `PRO_RATA_DAILY` the charged days are exactly the
        elapsed days, so an early termination returns the unconsumed fraction of
        the volume down to the day."

        40 elapsed days of a 120-day term charge one third of the 60.00 AF lease:
        `used_af` is 20.00 and `settlement_credit_af` is 40.00. PRD §3.9: "Whenever
        `used_af` is greater than zero the used volume also moves from the source
        right's `encumbered_af` to its `transferred_away_af`."

        Design: Difficulty/dual_variant_calc/lease_settlement_valuation_variant
        """
        bundle = self._two_active_leases()

        lease = self._cancel(bundle["leases"]["PRO_RATA_DAILY"]["id"])

        assert lease["status"] == "CANCELLED"
        assert lease["used_af"] == pytest.approx(20.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(40.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(70.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(20.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(105.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"

    def test_season_block_charges_the_whole_started_block(self):
        """PRD §3.9: "Under `SEASON_BLOCK` any started block is charged in full:
        the elapsed days are divided by 30 and rounded *up* to the next whole
        block, zero elapsed days yielding zero blocks, and the charged days are
        that block count times 30, capped at the term length".

        40 elapsed days round up to 2 blocks, so 60 days are charged against the
        120-day term: `used_af` is 30.00, half again as much as the daily method
        charges for the same instant, and the settlement credit is 30.00.

        Design: Difficulty/dual_variant_calc/lease_settlement_valuation_variant
        """
        bundle = self._two_active_leases()

        lease = self._cancel(bundle["leases"]["SEASON_BLOCK"]["id"])

        assert lease["status"] == "CANCELLED"
        assert lease["used_af"] == pytest.approx(30.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(30.00, abs=0.01)
        right = read_right(bundle["second_right"]["id"])
        assert right["encumbered_af"] == pytest.approx(60.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(30.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(105.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"

    def test_the_two_methods_return_different_credit_for_one_instant(self):
        """PRD §3.9: "Because the block method rounds elapsed days upward first, it
        returns strictly less credit than the daily method for the same termination
        instant whenever the elapsed days are not an exact multiple of 30, and the
        two methods therefore disagree on the acre-feet returned to
        `available_credit_af` for otherwise identical leases."

        40 is not a multiple of 30, so the same 60.00 AF lease terminated at the
        same instant returns 40.00 AF of credit under the daily method and only
        30.00 under the block method. Across both settlements the account gives
        back 70.00 AF of credit and permanently loses the 50.00 AF delivered, and
        PRD §2.9's credit identity holds at every step.

        Design: Difficulty/dual_variant_calc/lease_settlement_valuation_variant
        """
        bundle = self._two_active_leases()
        before = read_account(bundle["account"]["id"])
        assert before["deposited_credit_af"] == pytest.approx(180.00, abs=0.01)
        assert before["leased_out_af"] == pytest.approx(120.00, abs=0.01)
        assert before["available_credit_af"] == pytest.approx(60.00, abs=0.01)

        daily = self._cancel(bundle["leases"]["PRO_RATA_DAILY"]["id"])
        block = self._cancel(bundle["leases"]["SEASON_BLOCK"]["id"])

        assert daily["settlement_credit_af"] > block["settlement_credit_af"]
        assert daily["settlement_credit_af"] == pytest.approx(40.00, abs=0.01)
        assert block["settlement_credit_af"] == pytest.approx(30.00, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(130.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(130.00, abs=0.01)
        assert account["posture"] == "OPEN"
        for right_id in (bundle["right"]["id"], bundle["second_right"]["id"]):
            right = read_right(right_id)
            total = (
                right["transferable_af"]
                + right["encumbered_af"]
                + right["transferred_away_af"]
            )
            assert total == pytest.approx(195.00, abs=0.01)


class TestActivationBlockedByAccountPosture:
    """PRD §3.9 — a lease can be reserved against credit that is too thin to be
    delivered.

    A 44.00 AF deposit funds a 40.00 AF reservation, which leaves 4.00 AF
    available — one cent under the 5.00 acre-foot floor of PRD §2.10 — so the
    account is `RESTRICTED` even though its holder is in good standing and no
    lease is suspended.
    """

    WINDOW = ("2026-04-01T00:00:00Z", "2026-08-01T00:00:00Z")

    def _restricted(self):
        bundle = setup_authorized_headgate_account(deposit_af=44.00)
        bundle["lease"] = get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pod"]["id"],
                self.WINDOW[0],
                self.WINDOW[1],
                40.00,
                diversion_rate_cfs=1.500,
            )
        )
        set_clock("2026-04-05T00:00:00Z")
        return bundle

    def test_thin_credit_restricts_the_account_and_blocks_delivery(self):
        """PRD §2.10: "it reads `RESTRICTED` when the holding claimant's
        `standing_status` is `DELINQUENT` or when `available_credit_af` is strictly
        below 5.00 acre-feet."

        PRD §3.9: "The funding account's `posture` must be `OPEN`, so an account
        that is `RESTRICTED` by a delinquent holder or thin credit, or `FROZEN` by
        a suspended lease, cannot begin new deliveries; the failure is
        `ERR_ACCOUNT_POSTURE_BLOCKED` (409)." The clock is inside the window and
        the headgate is authorized, so posture is the only defect. The lease stays
        `RESERVED` and no credit is repartitioned.

        Design: Difficulty/cross_entity_state_dependency/lease_activation_blocked_by_account_posture
        """
        bundle = self._restricted()
        account = read_account(bundle["account"]["id"])
        assert account["available_credit_af"] == pytest.approx(4.00, abs=0.01)
        assert account["posture"] == "RESTRICTED"

        response = api_client.activate_lease_assignment(
            bundle["lease"]["id"], ANALYST
        )

        validate_error(
            response,
            ApiErrorId.ERR_ACCOUNT_POSTURE_BLOCKED.value,
            expected_status=409,
        )
        assert read_lease(bundle["lease"]["id"])["status"] == "RESERVED"
        unchanged = read_account(bundle["account"]["id"])
        assert unchanged["committed_credit_af"] == pytest.approx(40.00, abs=0.01)
        assert unchanged["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert unchanged["available_credit_af"] == pytest.approx(4.00, abs=0.01)
        assert unchanged["posture"] == "RESTRICTED"

    def test_a_further_deposit_lifts_the_posture_and_unblocks_the_same_lease(self):
        """PRD §3.9: "the posture is recomputed, so a deposit can lift an account
        off the low-credit `RESTRICTED` trigger".

        A further 6.00 AF deposit takes available credit from 4.00 to 10.00, which
        clears the floor, and the identical activation that was refused now
        succeeds. PRD §3.9: "On success `committed_credit_af` decreases and
        `leased_out_af` increases by `requested_af` while `available_credit_af` is
        untouched, so the credit identity is conserved by repartition alone; the posture
        is recomputed."

        Design: Difficulty/cross_entity_state_dependency/lease_activation_blocked_by_account_posture
        """
        bundle = self._restricted()
        api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)

        deposit(bundle["account"]["id"], bundle["right"]["id"], 6.00)

        topped_up = read_account(bundle["account"]["id"])
        assert topped_up["deposited_credit_af"] == pytest.approx(50.00, abs=0.01)
        assert topped_up["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert topped_up["posture"] == "OPEN"
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(50.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(145.00, abs=0.01)

        lease = get_success_data(
            api_client.activate_lease_assignment(bundle["lease"]["id"], ANALYST)
        )

        assert lease["status"] == "ACTIVE"
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(50.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(40.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["posture"] == "OPEN"
