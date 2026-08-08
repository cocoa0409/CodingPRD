"""Difficulty queue A — validation-priority conflicts across distinct error pairs.

Each test drives a single request that violates two rules at once and asserts the
earlier rule in the §2.5 precedence chain wins.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    base_portfolio, new_room, new_member, new_application, screen, decide,
    resubmit, new_membership, do_move_in, set_clock,
    read_application, read_room, read_house,
    create_membership_payload, manager_headers, compliance_headers,
)


# ==========================================================================
# priority_pair_validation_conflict / application_state_error_outranks_income_fiscal_error
# ==========================================================================
class TestApplicationStateOutranksIncome:
    def _setup_denied_after_cosigner(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        room = new_room(api, base["house"]["id"], base["host"]["id"], "101",
                        weekly_rate_cents=25000, monthly_rate_cents=100000)
        member = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                            declared_monthly_income_cents=100000)
        app = new_application(api, member["id"], room["id"],
                              requested_move_in_date="2026-06-10", billing_cycle="WEEKLY")
        screen(api, app["id"], verified_monthly_income_cents=100000, report_reference="SCR-B1")
        decide(api, app["id"], decision="APPROVE")           # -> CONDITIONAL
        resubmit(api, app["id"], member["id"], cosigner_monthly_income_cents=50000)
        screen(api, app["id"], verified_monthly_income_cents=100000, report_reference="SCR-B2")
        decide(api, app["id"], decision="DENY",
               decision_note="income still short with cosigner")  # -> DENIED
        return base, room, app

    def test_approve_on_denied_reports_state_error_not_income(self, api):
        """PRD §3.3: "A decision may only be rendered while the application is
        SCREENED; any other status yields ERR_APPLICATION_NOT_PENDING." PRD §2.5:
        "a request that violates two rules always reports the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/application_state_error_outranks_income_fiscal_error
        """
        base, room, app = self._setup_denied_after_cosigner(api)
        resp = api.decide_application(app["id"], {"decision": "APPROVE"},
                                      compliance_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_PENDING.value)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INCOME_INSUFFICIENT.value

    def test_denied_application_state_unchanged_after_conflict(self, api):
        """PRD §3.3: "insufficient income after the cosigner round has been
        consumed is a hard failure." PRD §3.3: "A DENY decision always lands the
        application in DENIED, sets required_deposit_cents to 0, and records the
        note."

        Design: Difficulty/priority_pair_validation_conflict/application_state_error_outranks_income_fiscal_error
        """
        base, room, app = self._setup_denied_after_cosigner(api)
        api.decide_application(app["id"], {"decision": "APPROVE"}, compliance_headers("co-1"))
        stored = read_application(api, app["id"])
        assert stored["status"] == "DENIED"
        assert stored["required_income_cents"] == 324999
        assert stored["screening_round"] == 2
        assert stored["required_deposit_cents"] == 0


# ==========================================================================
# priority_pair_validation_conflict / member_already_housed_referential_outranks_move_in_date_temporal
# ==========================================================================
class TestMemberAlreadyHousedOutranksMoveInDate:
    def _setup_second_approved_application(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        host_id, house_id = base["host"]["id"], base["house"]["id"]
        room1 = new_room(api, house_id, host_id, "101",
                         weekly_rate_cents=25000, monthly_rate_cents=100000)
        room2 = new_room(api, house_id, host_id, "102",
                         weekly_rate_cents=20000, monthly_rate_cents=80000, private_bath=False)
        member = new_member(api, full_name="Ada Reyes", email="ada@resident.example",
                            declared_monthly_income_cents=400000)
        app1 = new_application(api, member["id"], room1["id"],
                               requested_move_in_date="2026-06-01", billing_cycle="WEEKLY")
        screen(api, app1["id"], verified_monthly_income_cents=400000, report_reference="SCR-A1")
        decide(api, app1["id"], decision="APPROVE")
        mem1 = new_membership(api, app1["id"], "2026-06-01")
        do_move_in(api, mem1["id"])
        app3 = new_application(api, member["id"], room2["id"],
                               requested_move_in_date="2026-06-12", billing_cycle="WEEKLY")
        screen(api, app3["id"], verified_monthly_income_cents=400000, report_reference="SCR-A2")
        decide(api, app3["id"], decision="APPROVE")
        set_clock(api, "2026-06-10T00:00:00Z")
        return base, room2, app3

    def test_membership_create_reports_referential_error_not_temporal(self, api):
        """PRD §3.4: "if any other Membership of that member is in PENDING_MOVE_IN,
        ACTIVE, or NOTICE_GIVEN, conversion is rejected with
        ERR_MEMBER_ALREADY_HOUSED." PRD §2.5: "a request that violates two rules
        always reports the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/member_already_housed_referential_outranks_move_in_date_temporal
        """
        base, room2, app3 = self._setup_second_approved_application(api)
        resp = api.create_membership(
            create_membership_payload(app3["id"], "2026-06-05"), manager_headers())
        validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_HOUSED.value)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_MOVE_IN_DATE_IN_PAST.value

    def test_room_and_house_state_untouched_after_conflict(self, api):
        """PRD §3.4: "the requested move_in_date may not be strictly earlier than
        the current logical clock date (ERR_MOVE_IN_DATE_IN_PAST)." PRD §3.4: "It
        advances the application to CONVERTED (terminal) ... it drives the room from
        VACANT to RESERVED".

        Design: Difficulty/priority_pair_validation_conflict/member_already_housed_referential_outranks_move_in_date_temporal
        """
        base, room2, app3 = self._setup_second_approved_application(api)
        api.create_membership(create_membership_payload(app3["id"], "2026-06-05"),
                              manager_headers())
        assert read_application(api, app3["id"])["status"] == "APPROVED"
        assert read_application(api, app3["id"])["required_income_cents"] == 260001
        assert read_room(api, room2["id"])["occupancy_state"] == "VACANT"
        house = read_house(api, base["house"]["id"])
        assert house["reserved_room_count"] == 0
        assert house["occupied_room_count"] == 1
