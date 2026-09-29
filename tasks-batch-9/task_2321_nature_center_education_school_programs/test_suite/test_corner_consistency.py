"""Read-after-write consistency of the Nature Center Education API.

PRD §3.8 makes an aid decision recompute the application row, the booking's money
dimension and the pool's ledger counters in the same write, and PRD §3.9 has the
funder rollup read those counters as they currently stand. These tests read every
one of those paths on the calls immediately following the decision.
"""

from test_helpers import (
    BC,
    GO,
    assert_fund_ledger_conserved,
    assert_outcome_report,
    assert_three_decimal_string_value,
    setup_booking_with_submitted_aid,
    validate_success,
)


class TestApprovalVisibility:
    def test_an_approval_is_visible_to_the_application_booking_fund_and_rollup(self, api):
        """PRD §3.8: "Either approval outcome advances the booking's `funding_status` from `AID_PENDING` to `AID_APPROVED` and recomputes the pool's `pending_cents`, `committed_cents`, `transport_awarded_cents` and `available_cents`."

        Design: Corner/consistency model/an_approval_is_visible_to_every_read_path_on_the_next_call
        """
        scenario = setup_booking_with_submitted_aid(
            requested_scholarship_cents=28000, requested_transport_cents=9000
        )
        application_id = scenario["aid_application"]["id"]
        fund_id = scenario["fund"]["id"]

        decided = validate_success(
            api.review_aid_application(application_id, {"decision": "APPROVE"}, GO)
        )
        assert decided["status"] == "PARTIALLY_APPROVED"

        application = validate_success(api.get_aid_application(application_id, GO))
        assert application["status"] == "PARTIALLY_APPROVED"
        assert application["awarded_scholarship_cents"] == 28000
        assert application["awarded_transport_cents"] == 6500

        booking = validate_success(api.get_booking(scenario["booking"]["id"], BC))
        assert booking["funding_status"] == "AID_APPROVED"
        assert booking["aid_amount_cents"] == 28000
        assert booking["net_due_cents"] == 5300

        fund = validate_success(api.get_scholarship_fund(fund_id, GO))
        assert fund["pending_cents"] == 0
        assert fund["committed_cents"] == 34500
        assert fund["available_cents"] == 4965500
        assert_fund_ledger_conserved(fund)

        rollup = validate_success(api.get_fund_outcome_report(fund_id, GO))
        assert_outcome_report(rollup)
        assert rollup["awarded_application_count"] == 1
        assert rollup["committed_cents"] == 34500
        assert rollup["students_served_count"] == 0
        assert_three_decimal_string_value(
            rollup["weighted_learning_gain_index"], 0.000, "weighted_learning_gain_index"
        )
