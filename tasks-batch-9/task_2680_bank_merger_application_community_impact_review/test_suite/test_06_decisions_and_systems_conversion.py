"""Customer disclosure lead time and the conversion's dependency on the order."""
from test_helpers import ApiErrorId, api_client, make_filer_headers
from test_helpers.assertions import (
    assert_approval_decision,
    assert_conversion_plan,
    assert_same_instant,
)
from test_helpers.fixtures import (
    application_decided,
    disclose_conversion,
    read_application,
    read_conversion_plan,
    read_decision,
    register_conversion_plan,
    set_clock,
    two_bank_world,
)
from prd_bench_local_runner.testing import validate_error


class TestDisclosureLeadTimeBoundary:
    """Thirty whole days of lead is the minimum, and it is inclusive."""

    def test_a_lead_of_exactly_thirty_days_is_accepted(self):
        """PRD §3.11: "The service stamps `customer_disclosure_sent_at` from the logical clock and
        computes `disclosure_lead_days` as the number of whole UTC days from
        `customer_disclosure_sent_at` to `conversion_start_date`, discarding any partial day."
        PRD §3.11: "That instant must be strictly before `conversion_start_date` and the lead time
        must be at least 30 days; either failure is refused with
        `ERR_DISCLOSURE_LEAD_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/disclosure_lead_exactly_at_minimum_is_accepted
        """
        world = two_bank_world()
        plan = register_conversion_plan(world["application"]["id"], world["acquirer"]["id"])
        set_clock("2027-05-16T00:00:00Z")

        disclosed = disclose_conversion(plan["id"], world["acquirer"]["id"])

        assert_conversion_plan(disclosed)
        assert disclosed["status"] == "DISCLOSED"
        assert_same_instant(disclosed["customer_disclosure_sent_at"], "2027-05-16T00:00:00Z",
                            "customer_disclosure_sent_at")
        assert disclosed["disclosure_lead_days"] == 30, (
            f"2027-05-16 to 2027-06-15 is exactly 30 whole days, "
            f"got {disclosed['disclosure_lead_days']}"
        )

    def test_a_lead_of_twenty_nine_days_is_refused_and_leaves_the_plan_draft(self):
        """PRD §3.11: "That instant must be strictly before `conversion_start_date` and the lead time
        must be at least 30 days; either failure is refused with
        `ERR_DISCLOSURE_LEAD_INSUFFICIENT`."
        PRD §3.11: "The plan is created with `status` `DRAFT` and with
        `customer_disclosure_sent_at` and `disclosure_lead_days` null."

        Design: Difficulty/boundary_precision_check/disclosure_lead_exactly_at_minimum_is_accepted
        """
        world = two_bank_world()
        plan = register_conversion_plan(world["application"]["id"], world["acquirer"]["id"])
        set_clock("2027-05-17T00:00:00Z")

        response = api_client.disclose_conversion_plan(
            plan["id"], {"disclosure_channels": ["MAIL", "ONLINE_BANKING"]},
            make_filer_headers(world["acquirer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DISCLOSURE_LEAD_INSUFFICIENT.value, 422)
        unchanged = read_conversion_plan(plan["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["customer_disclosure_sent_at"] is None
        assert unchanged["disclosure_lead_days"] is None


class TestConversionWaitsForTheConsummatedOrder:
    """A disclosed plan still cannot convert until the order is consummated."""

    def test_converting_before_consummation_reports_the_decision_state_error(self):
        """PRD §3.11: "Completing the conversion drives `DISCLOSED → CONVERTED` and is guarded by
        another entity's state: the application's approval order must already have `status`
        `CONSUMMATED`, and a plan that tries to convert earlier is refused with
        `ERR_INVALID_DECISION_STATE`."

        Design: Difficulty/cross_entity_state_dependency/systems_conversion_blocked_until_decision_is_consummated
        """
        world = application_decided()
        acquirer_id = world["acquirer"]["id"]
        plan = register_conversion_plan(
            world["application"]["id"], acquirer_id,
            conversion_start_date="2027-01-15", conversion_end_date="2027-01-20",
        )
        set_clock("2026-12-01T00:00:00Z")
        disclose_conversion(plan["id"], acquirer_id)

        response = api_client.convert_conversion_plan(
            plan["id"], make_filer_headers(acquirer_id)
        )

        validate_error(response, ApiErrorId.ERR_INVALID_DECISION_STATE.value, 409)

    def test_the_refused_conversion_leaves_the_plan_disclosed_with_its_lead_recorded(self):
        """PRD §3.11: "Sending the customer disclosure drives `DRAFT → DISCLOSED` and carries
        `disclosure_channels`, a non-empty array whose members are drawn from `MAIL`, `EMAIL`,
        `IN_BRANCH_NOTICE` and `ONLINE_BANKING`."
        PRD §3.11: "A plan that is not `DRAFT` when a disclosure is attempted, or not `DISCLOSED`
        when a conversion is attempted, is refused with `ERR_INVALID_CONVERSION_PLAN_STATE`."

        Design: Difficulty/cross_entity_state_dependency/systems_conversion_blocked_until_decision_is_consummated
        """
        world = application_decided()
        acquirer_id = world["acquirer"]["id"]
        plan = register_conversion_plan(
            world["application"]["id"], acquirer_id,
            conversion_start_date="2027-01-15", conversion_end_date="2027-01-20",
        )
        set_clock("2026-12-01T00:00:00Z")
        disclose_conversion(plan["id"], acquirer_id)
        api_client.convert_conversion_plan(plan["id"], make_filer_headers(acquirer_id))

        after = read_conversion_plan(plan["id"])
        assert after["status"] == "DISCLOSED"
        assert_same_instant(after["customer_disclosure_sent_at"], "2026-12-01T00:00:00Z",
                            "customer_disclosure_sent_at")
        assert after["disclosure_lead_days"] == 45

    def test_the_order_is_still_issued_and_the_application_still_decided(self):
        """PRD §3.10: "An approving order takes the application `RECOMMENDED → DECIDED`, is created
        with `status` `ISSUED`, and increments the application's `version` by 1."
        PRD §3.10: "`consummation_window_open_at` is `decided_at` advanced by
        `waiting_period_days` whole days, and consummation is permitted at that instant inclusive."

        Design: Difficulty/cross_entity_state_dependency/systems_conversion_blocked_until_decision_is_consummated
        """
        world = application_decided()
        acquirer_id = world["acquirer"]["id"]
        plan = register_conversion_plan(
            world["application"]["id"], acquirer_id,
            conversion_start_date="2027-01-15", conversion_end_date="2027-01-20",
        )
        set_clock("2026-12-01T00:00:00Z")
        disclose_conversion(plan["id"], acquirer_id)
        api_client.convert_conversion_plan(plan["id"], make_filer_headers(acquirer_id))

        decision = read_decision(world["decision"]["id"])
        application = read_application(world["application"]["id"], acquirer_id)

        assert_approval_decision(decision)
        assert decision["status"] == "ISSUED"
        assert_same_instant(decision["consummation_window_open_at"], "2026-09-20T00:00:00Z",
                            "consummation_window_open_at")
        assert application["filing_status"] == "DECIDED"
