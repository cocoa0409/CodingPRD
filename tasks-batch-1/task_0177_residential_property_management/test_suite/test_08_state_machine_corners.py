"""Invalid-transition, precondition, and terminal-lockdown breadth tests."""
import pytest
from test_helpers import get_success_data, validate_error
from test_helpers.fixtures import (
    PM, CO, create_unit, create_screened_applicant, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, setup_active_lease,
    setup_draft_lease_ready_to_sign, serve_eviction, create_work_order,
    create_assigned_work_order, create_completed_work_order, setup_expired_lease,
    create_open_turnover,
)
from test_helpers.api_client import api_client


class TestInvalidTransitions:
    def test_screen_already_screened_returns_invalid_state(self, api):
        """PRD §3.2: "Screening is run by a PropertyManager on an application that
        is still in SUBMITTED, advancing it to SCREENED." PRD §2.6: "the
        optimistic-concurrency version check (ERR_STALE_VERSION) precedes the
        general state-admissibility check (ERR_INVALID_STATE), which precedes the
        domain-specific business guards."

        A second screen on a SCREENED (no longer SUBMITTED) applicant is not
        state-admissible.

        Design: Corner/state_machines/screen_already_screened_applicant_returns_invalid_state
        """
        unit = create_unit()
        app = create_screened_applicant(unit["id"])
        res = api.screen_applicant(app["id"], PM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_terminal_completed_work_order_cannot_be_assigned(self, api):
        """PRD §3.7: "A PropertyManager assigns an open work order to a vendor,
        advancing it from OPEN to ASSIGNED." PRD §3.7: "advances the order to the
        terminal COMPLETED state." PRD §2.6: "the general state-admissibility check
        (ERR_INVALID_STATE)".

        Assign only advances from OPEN; a COMPLETED (terminal) order admits no
        assign, so the state-admissibility check rejects it.

        Design: Corner/state_machines/terminal_state_lockdown_assign_completed_workorder
        """
        unit = create_unit()
        wo = create_completed_work_order(unit["id"], actual_cost_cents=5000,
                                         completed_date="2026-06-15",
                                         charge_to_owner=False, category="HVAC")
        res = api.assign_work_order(wo["id"], PM)
        validate_error(res, "ERR_INVALID_STATE")


class TestSignPreconditions:
    def test_sign_without_approved_applicant_rejected(self, api):
        """PRD §3.3: "For an original lease, the applicant named by applicant_id
        must be in APPROVED, or the sign is refused with
        ERR_APPLICANT_NOT_APPROVED".

        Design: Corner/state_machines/sign_lease_without_approved_applicant_returns_applicant_not_approved
        """
        ready = setup_draft_lease_ready_to_sign(approve=False, with_deposit=True)
        res = api.sign_lease(ready["lease"]["id"], PM)
        validate_error(res, "ERR_APPLICANT_NOT_APPROVED")

    def test_sign_without_deposit_rejected(self, api):
        """PRD §3.3: "A SecurityDeposit in HELD status must exist for the lease, or
        the sign is refused with ERR_DEPOSIT_REQUIRED."

        Design: Corner/state_machines/sign_lease_without_deposit_returns_deposit_required
        """
        ready = setup_draft_lease_ready_to_sign(approve=True, with_deposit=False)
        res = api.sign_lease(ready["lease"]["id"], PM)
        validate_error(res, "ERR_DEPOSIT_REQUIRED")


class TestLeaseExpiry:
    def test_expire_before_end_date_rejected(self, api):
        """PRD §3.4: "expiring before the term has ended — an as_of_date earlier
        than end_date — is refused with ERR_LEASE_NOT_ENDED."

        Design: Corner/state_machines/expire_lease_before_end_date_returns_lease_not_ended
        """
        world = setup_active_lease(state_code="TX",
                                   lease_overrides={"start_date": "2026-06-01",
                                                    "end_date": "2027-06-01"})
        res = api.expire_lease(world["lease"]["id"], {"as_of_date": "2026-09-01"}, PM)
        validate_error(res, "ERR_LEASE_NOT_ENDED")


class TestEvictionPreconditions:
    def test_file_inside_cure_window_rejected(self, api):
        """PRD §3.8: "a ComplianceOfficer may file the case, moving it to FILED, but
        only after the cure window has closed — the supplied as_of_date must be
        strictly after the cure_deadline_date, and attempting to file while the
        window is still open is refused with ERR_CURE_WINDOW_OPEN." PRD §3.8: "for a
        holdover it is ... 15 in Florida".

        FL HOLDOVER notice 2026-06-10 -> deadline 2026-06-25; file as_of 2026-06-20
        is still inside the window.

        Design: Corner/state_machines/enforce_eviction_still_in_cure_window_via_file_returns_cure_window_open
        """
        world = setup_active_lease(state_code="FL")
        eviction = serve_eviction(world["lease"]["id"], reason="HOLDOVER",
                                  notice_date="2026-06-10")
        assert eviction["cure_deadline_date"] == "2026-06-25"
        res = api.file_eviction(eviction["id"], {"as_of_date": "2026-06-20"}, CO)
        validate_error(res, "ERR_CURE_WINDOW_OPEN")

    def test_cure_after_deadline_rejected(self, api):
        """PRD §3.8: "A PropertyManager may mark the case cured, moving it to CURED,
        but only while the cure window is still open — the supplied as_of_date must
        be on or before the cure_deadline_date, otherwise the cure is refused with
        ERR_CURE_WINDOW_CLOSED". PRD §3.8: "for nonpayment the cure window is 3 days
        in California, Texas, and Florida".

        TX NONPAYMENT notice 2026-06-10 -> deadline 2026-06-13; cure as_of
        2026-06-20 is past it.

        Design: Corner/state_machines/cure_eviction_after_deadline_returns_cure_window_closed
        """
        world = setup_active_lease(state_code="TX")
        eviction = serve_eviction(world["lease"]["id"], reason="NONPAYMENT",
                                  notice_date="2026-06-10")
        assert eviction["cure_deadline_date"] == "2026-06-13"
        res = api.cure_eviction(eviction["id"], {"as_of_date": "2026-06-20"}, PM)
        validate_error(res, "ERR_CURE_WINDOW_CLOSED")

    def test_cure_nonpayment_with_arrears_rejected(self, api):
        """PRD §3.8: "when the reason is NONPAYMENT, only once the lease's
        balance_due_cents has been brought to zero, failing which it is refused with
        ERR_ARREARS_NOT_CLEARED."

        NY NONPAYMENT, unpaid 250000 charge, cure as_of 2026-06-15 within the
        14-day window but arrears outstanding.

        Design: Corner/state_machines/cure_nonpayment_eviction_with_arrears_returns_arrears_not_cleared
        """
        world = setup_active_lease(state_code="NY", market_rent_cents=250000,
                                   deposit_cents=250000)
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=250000, period_label="2026-06",
                         due_date="2026-06-01")
        eviction = serve_eviction(lease_id, reason="NONPAYMENT",
                                  notice_date="2026-06-10")
        res = api.cure_eviction(eviction["id"], {"as_of_date": "2026-06-15"}, PM)
        validate_error(res, "ERR_ARREARS_NOT_CLEARED")


class TestWorkOrderAndTurnover:
    def test_complete_without_actual_cost_rejected(self, api):
        """PRD §3.7: "Completion, also by a PropertyManager, requires the work order
        to be ASSIGNED and requires the request to supply actual_cost_cents —
        completion without it is refused with ERR_ACTUAL_COST_REQUIRED."

        Design: Corner/state_machines/complete_workorder_without_actual_cost_returns_actual_cost_required
        """
        unit = create_unit()
        wo = create_assigned_work_order(unit["id"], charge_to_owner=False,
                                        category="PLUMBING")
        res = api.complete_work_order(wo["id"], {}, PM)
        validate_error(res, "ERR_ACTUAL_COST_REQUIRED")

    def test_waive_rent_charge_rejected(self, api):
        """PRD §3.5: "Waiving is permitted only while the charge is OPEN or PARTIAL,
        and only on a charge whose charge_type is LATE_FEE; attempting to waive a
        RENT charge is refused with ERR_CANNOT_WAIVE_RENT."

        Design: Corner/state_machines/waive_rent_charge_returns_cannot_waive_rent
        """
        world = setup_active_lease(state_code="TX")
        charge = post_rent_charge(world["lease"]["id"], amount_cents=200000,
                                  period_label="2026-06", due_date="2026-06-01")
        res = api.waive_rent_charge(charge["id"], PM)
        validate_error(res, "ERR_CANNOT_WAIVE_RENT")

    def test_complete_turnover_with_open_work_orders_rejected(self, api):
        """PRD §3.9: "Completion is blocked while the unit still has any work order
        in OPEN or ASSIGNED status; such open maintenance refuses the completion
        with ERR_OPEN_WORK_ORDERS."

        Design: Corner/state_machines/complete_turnover_with_open_work_orders_returns_open_work_orders
        """
        world = setup_expired_lease(state_code="TX", start_date="2026-06-01",
                                    end_date="2026-07-01", expire_as_of="2026-07-01")
        unit_id = world["unit"]["id"]
        create_work_order(unit_id, charge_to_owner=False, category="STRUCTURAL",
                          description="Patch")
        turnover = create_open_turnover(unit_id, opened_date="2026-07-02",
                                        target_ready_date="2026-07-20")
        get_success_data(api.start_turnover(turnover["id"], PM))
        res = api.complete_turnover(turnover["id"], PM)
        validate_error(res, "ERR_OPEN_WORK_ORDERS")
