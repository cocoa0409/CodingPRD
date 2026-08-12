"""Corner: compliance-fine branching and performance-review invitation flow."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_review_for_assignment,
    issue_fine,
    make_vendor_headers,
    make_vendor_spec,
    respond_fine,
    setup_finalized_multi,
    setup_reserved_assignment,
    validate_error,
    validate_success,
)

FIN1 = TEST_USERS["finance_headers"]


class TestFineBranches:
    def test_fine_dispute_then_waive_branch(self, api):
        """PRD §3.7: "from `ISSUED` a fine may move to either state, and from
        `DISPUTED` it may later move to `ACKNOWLEDGED`; ownership is checked as
        usual."
        PRD §3.7: "A `FestivalDirector` may waive a fine in `ISSUED`,
        `ACKNOWLEDGED`, or `DISPUTED`, moving it to `WAIVED` and recording
        `waived_by_user_id`".

        Design: Corner/state_machines/fine_dispute_then_waive_branch
        """
        scen = setup_reserved_assignment(name="Branch Fest")
        fine = issue_fine(scen["assignment"]["id"], type="GREASE_DISPOSAL", amount_cents=12000)

        disputed = respond_fine(fine["id"], scen["vendor"], "DISPUTED")
        assert disputed["status"] == "DISPUTED"

        resp = api.waive_fine(fine["id"], TEST_USERS["director_headers"])
        waived = validate_success(resp)
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "dir-1", "waiving director recorded (issuer sus-1 != waver dir-1)"

    def test_fine_markpaid_from_issued_rejected(self, api):
        """PRD §3.7: "A `FinanceLead` marks an `ACKNOWLEDGED` fine `PAID`, which
        increments the vendor's `compliance_strikes` by one."
        PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."

        Design: Corner/state_machines/fine_markpaid_from_issued_rejected
        """
        scen = setup_reserved_assignment(name="SkipAck Fest")
        fine = issue_fine(scen["assignment"]["id"], type="WASTE_SORTING", amount_cents=9000)
        assert fine["status"] == "ISSUED"
        resp = api.mark_paid_fine(fine["id"], FIN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestReviewInvitationFlow:
    def test_review_invitation_accept_and_ineligible_gate(self, api):
        """PRD §3.8: "If the `official_score` is below 70, the review moves
        directly to `INELIGIBLE` rather than `SCORED`."
        PRD §3.8: "From `SCORED` — which implies a score of at least 70 — issuing
        an invitation moves the review to `INVITED`; calling for an invitation on
        an `INELIGIBLE` review is rejected with `ERR_SCORE_THRESHOLD_NOT_MET`."

        Design: Corner/state_machines/review_invitation_accept_and_ineligible_gate
        """
        specs = [
            make_vendor_spec("Invite A", "FOOD_HOT", flat_fee_cents=50000, power_draw_amps=30),
            make_vendor_spec("Invite B", "FOOD_COLD", flat_fee_cents=50000, power_draw_amps=20),
        ]
        sales = [[{"amount_cents": 200000, "key": "ia1"}], [{"amount_cents": 100000, "key": "ib1"}]]
        scen = setup_finalized_multi(specs, sales, name="Invite Fest", zone_power=200)
        rev_a = get_review_for_assignment(scen["assignments"][0]["id"])
        rev_b = get_review_for_assignment(scen["assignments"][1]["id"])

        scored_a = validate_success(api.compute_score(rev_a["id"], TEST_USERS["vendor_manager_headers"]))
        assert scored_a["official_score"] == 80
        assert scored_a["status"] == "SCORED"
        invited = validate_success(api.issue_invitation(rev_a["id"], TEST_USERS["vendor_manager_headers"]))
        assert invited["status"] == "INVITED"
        answered = validate_success(
            api.respond_review(rev_a["id"], {"response": "ACCEPTED"},
                               make_vendor_headers(scen["vendors"][0]["id"]))
        )
        assert answered["status"] == "ACCEPTED"

        scored_b = validate_success(api.compute_score(rev_b["id"], TEST_USERS["vendor_manager_headers"]))
        assert scored_b["official_score"] == 60
        assert scored_b["status"] == "INELIGIBLE", "60 < 70 auto-threshold"
        resp = api.issue_invitation(rev_b["id"], TEST_USERS["vendor_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_SCORE_THRESHOLD_NOT_MET)
