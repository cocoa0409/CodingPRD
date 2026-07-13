"""Permit lifecycle: the ACTIVE<->SUSPENDED pump-out cycle, cross-entity
dependencies on vessel/berth state, transfer propagation, and the
occupancy/money conservation invariants around activate+revoke."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_boater,
    create_vessel,
    apply_permit,
    setup_active_permit,
    setup_offered_permit,
    get_permit,
    get_berth,
    get_marina,
    get_invoice,
    get_vessel,
)

HARBOR = TEST_USERS["harbormaster_headers"]


class TestPumpOutSuspensionCycle:
    def _suspend(self, api):
        b = setup_active_permit(
            api,
            clock="2026-04-01T00:00:00Z",
            activate_clock="2026-05-15T00:00:00Z",
            marina_overrides={"pumpout_interval_days": 30},
            vessel_overrides={"has_holding_tank": True, "length_ft": 30},
        )
        set_clock(api, "2026-06-16T00:00:00Z")  # 32 days since activation
        validate_success(api.run_maintenance(b["marina"]["id"], HARBOR))
        return b

    def test_overdue_pumpout_suspends_active_permit(self, api):
        """PRD §3.7: "When the maintenance sweep finds an `ACTIVE` permit whose
        vessel has a holding tank and whose days since last pump-out have crossed
        strictly beyond the interval, it moves the permit from `ACTIVE` to
        `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/permit_active_suspended_active_cycle
        """
        b = self._suspend(api)
        assert get_permit(api, b["permit"]["id"])["status"] == "SUSPENDED"

    def test_pumpout_record_restores_active_from_suspended(self, api):
        """PRD §3.7: "When a later pump-out is logged that restores compliance —
        after which the days since last pump-out are at or below the interval —
        the vessel's `pumpout_status` returns to `COMPLIANT` and the permit moves
        from `SUSPENDED` back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/permit_active_suspended_active_cycle
        """
        b = self._suspend(api)
        validate_success(
            api.create_pumpout_record(b["vessel"]["id"], {"pumpout_date": "2026-06-16"}, HARBOR),
            expected_status=201,
        )
        assert get_permit(api, b["permit"]["id"])["status"] == "ACTIVE"
        assert get_vessel(api, b["vessel"]["id"])["pumpout_status"] == "COMPLIANT"


class TestActivationDependsOnVesselRegistration:
    def _offer_then_expire(self, api):
        b = setup_offered_permit(
            api,
            clock="2026-05-01T00:00:00Z",
            vessel_overrides={"registration_expiry_date": "2026-05-10", "length_ft": 30},
        )
        set_clock(api, "2026-05-15T00:00:00Z")  # vessel now EXPIRED
        return b

    def test_activation_rejected_when_vessel_registration_lapsed(self, api):
        """PRD §3.4: "Before an offered permit becomes `ACTIVE`, its berth must
        still be `RESERVED` for it, its vessel must still be `REGISTERED`, and
        there must be no season overlap on that berth"
        PRD §3.3: "an application on an `EXPIRED` or `REVOKED` vessel is rejected
        with `ERR_VESSEL_REGISTRATION_EXPIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/permit_activation_requires_vessel_registered
        """
        b = self._offer_then_expire(api)
        validate_error(
            api.pay_invoice(b["invoice_id"], {"amount_cents": 120000}, HARBOR),
            ApiErrorId.ERR_VESSEL_REGISTRATION_EXPIRED,
        )

    def test_permit_stays_offered_after_failed_activation(self, api):
        """PRD §3.4: "When the paid invoice is a `PERMIT` invoice, its permit
        transitions from `OFFERED` to `ACTIVE`."
        PRD §3.4: "Before an offered permit becomes `ACTIVE`, its berth must still
        be `RESERVED` for it, its vessel must still be `REGISTERED`, and there must
        be no season overlap on that berth"

        Design: Difficulty/cross_entity_state_dependency/permit_activation_requires_vessel_registered
        """
        b = self._offer_then_expire(api)
        api.pay_invoice(b["invoice_id"], {"amount_cents": 120000}, HARBOR)
        assert get_permit(api, b["permit"]["id"])["status"] == "OFFERED"


class TestOfferVersusWaitlist:
    def _first_offered_second_applies(self, api):
        b1 = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
        marina_id = b1["marina"]["id"]
        boater2 = create_boater(api, full_name="Second S", email="second@example.com")
        vessel2 = create_vessel(api, boater2["id"], length_ft=28)
        permit2 = apply_permit(api, marina_id, boater2["id"], vessel2["id"])
        return b1, permit2

    def test_second_applicant_waitlisted_when_only_berth_reserved(self, api):
        """PRD §3.3: "If no such berth is free at creation, the permit is instead
        created `WAITLISTED` with a null `berth_id`, and the marina's
        `waitlist_length` rises by one."

        Design: Difficulty/cross_entity_state_dependency/permit_offer_vs_waitlist_depends_on_berth_availability
        """
        _, permit2 = self._first_offered_second_applies(api)
        assert permit2["status"] == "WAITLISTED"
        assert permit2["berth_id"] is None

    def test_first_applicant_offered_the_available_berth(self, api):
        """PRD §3.3: "If a berth exists in the marina whose `berth_type` equals the
        `requested_berth_type`, whose `size_class` equals the `requested_size_class`,
        whose `status` is `AVAILABLE`, whose `max_length_ft` is at least the
        vessel's `length_ft`, and which is either not `resident_only` or is being
        taken by a resident, the applicant is immediately assignable and the permit
        is created `OFFERED`."

        Design: Difficulty/cross_entity_state_dependency/permit_offer_vs_waitlist_depends_on_berth_availability
        """
        b1, _ = self._first_offered_second_applies(api)
        assert b1["permit"]["status"] == "OFFERED"


class TestTransferPropagation:
    def _transfer(self, api):
        b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
        boater2 = create_boater(api, full_name="Holder Two", email="t2@example.com")
        new = validate_success(
            api.transfer_permit(b["permit"]["id"], {"to_boater_id": boater2["id"]}, HARBOR)
        )
        return b, boater2, new

    def test_transfer_moves_old_and_creates_new_active_permit(self, api):
        """PRD §3.5: "Transfer moves the original permit to the terminal
        `TRANSFERRED` state and creates a new `ACTIVE` permit for the target boater
        on the same `berth_id`, same vessel, and same season dates, with `source`
        `TRANSFER`."

        Design: Difficulty/transitive_cascade/transfer_old_permit_new_permit_new_invoice_depth2
        """
        b, boater2, new = self._transfer(api)
        assert get_permit(api, b["permit"]["id"])["status"] == "TRANSFERRED"
        assert new["status"] == "ACTIVE"
        assert new["source"] == "TRANSFER"
        assert new["boater_id"] == boater2["id"]

    def test_transfer_issues_new_transfer_invoice_for_flat_fee(self, api):
        """PRD §3.5: "A new `TRANSFER` invoice for a flat 5,000 cents is issued to
        the target boater, the berth's `current_permit_id` is repointed to the new
        permit, and because the boat has not moved the occupancy and liveaboard
        counts are unchanged."

        Design: Difficulty/transitive_cascade/transfer_old_permit_new_permit_new_invoice_depth2
        """
        _, _, new = self._transfer(api)
        invoice = get_invoice(api, new["invoice_id"])
        assert invoice["invoice_type"] == "TRANSFER"
        assert invoice["amount_due_cents"] == 5000


class TestOccupancyConservation:
    def _activate_then_revoke(self, api):
        b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
        validate_success(api.revoke_permit(b["permit"]["id"], HARBOR, {"reason": "owner request"}))
        return b

    def test_revoke_returns_occupancy_counters_to_zero(self, api):
        """PRD §2.7: "The `available_slip_count` is the number of berths whose
        `berth_type` is `SLIP` and whose `status` is `AVAILABLE`; the
        `occupied_slip_count` is the number of `SLIP` berths whose `status` is
        `OCCUPIED`."
        PRD §3.5: "revocation moves the permit to `REVOKED`, computes a refund,
        releases the berth, and decrements occupancy and any liveaboard count."

        Design: Difficulty/compensating_invariant/berth_occupancy_conserved_activate_then_revoke
        """
        b = self._activate_then_revoke(api)
        marina = get_marina(api, b["marina"]["id"])
        assert marina["occupied_slip_count"] == 0
        assert marina["available_slip_count"] == 1

    def test_revoke_frees_berth_and_ends_permit(self, api):
        """PRD §3.5: "A harbormaster may revoke an `ACTIVE` or `SUSPENDED` permit
        outright, optionally recording a `reason`; revocation moves the permit to
        `REVOKED`, computes a refund, releases the berth, and decrements occupancy
        and any liveaboard count."

        Design: Difficulty/compensating_invariant/berth_occupancy_conserved_activate_then_revoke
        """
        b = self._activate_then_revoke(api)
        assert get_permit(api, b["permit"]["id"])["status"] == "REVOKED"
        assert get_berth(api, b["berth"]["id"])["status"] == "AVAILABLE"


class TestMoneyConservation:
    def _pay_then_revoke(self, api):
        b = setup_active_permit(
            api,
            clock="2026-05-01T00:00:00Z",
            berth_overrides={"berth_type": "SLIP", "size_class": "LARGE", "max_length_ft": 45},
            vessel_overrides={"length_ft": 40},
            permit_overrides={"requested_size_class": "LARGE"},
        )
        set_clock(api, "2026-07-01T00:00:00Z")
        validate_success(api.revoke_permit(b["permit"]["id"], HARBOR, {"reason": "left the marina"}))
        return b

    def test_revoke_refund_prorates_remaining_season(self, api):
        """PRD §3.5: "The net amount paid is `amount_paid_cents` minus
        `amount_refunded_cents`, and the refund is that net amount multiplied by
        remaining days divided by season days, rounded half up to whole cents. The
        refund is added to the invoice's `amount_refunded_cents`, moving it to
        `PARTIALLY_REFUNDED` when the refund is greater than zero and less than the
        net paid, or to `REFUNDED` when the refund equals the net paid."

        Design: Difficulty/compensating_invariant/money_conserved_pay_then_revoke_refund
        """
        b = self._pay_then_revoke(api)
        invoice = get_invoice(api, b["invoice"]["id"])
        # net paid 160000, remaining 123/184 -> round(106956.52) = 106957
        assert invoice["amount_refunded_cents"] == 106957
        assert invoice["status"] == "PARTIALLY_REFUNDED"

    def test_amount_paid_unchanged_by_refund(self, api):
        """PRD §3.4: "A successful payment sets `amount_paid_cents` equal to
        `amount_due_cents` and moves the invoice to `PAID`."

        Design: Difficulty/compensating_invariant/money_conserved_pay_then_revoke_refund
        """
        b = self._pay_then_revoke(api)
        invoice = get_invoice(api, b["invoice"]["id"])
        assert invoice["amount_paid_cents"] == 160000


class TestCancelOffered:
    def test_cancel_offered_frees_berth_and_voids_invoice(self, api):
        """PRD §3.5: "When a boater declines an `OFFERED` permit, the permit moves
        to the terminal `DECLINED` state, its reserved berth returns from
        `RESERVED` to `AVAILABLE` with `current_permit_id` cleared, and its
        `PERMIT` invoice is voided."

        Design: Corner/state_machines/cancel_offered_permit_frees_berth_and_voids_invoice
        """
        b = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
        validate_success(api.cancel_permit(b["permit"]["id"], HARBOR))
        assert get_permit(api, b["permit"]["id"])["status"] == "DECLINED"
        assert get_berth(api, b["berth"]["id"])["status"] == "AVAILABLE"
        assert get_invoice(api, b["invoice_id"])["status"] == "VOID"
