"""Business notification deadlines, the response cycle, and the SUFFICIENT gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_business_response,
    assert_iso_instant,
    file_complaint,
    get_complaint,
    make_business_headers,
    notify_business,
    offer_mediation,
    register_business,
    register_consumer,
    review_response,
    screen_accept,
    set_clock,
    submit_response,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]


class TestResponseDeadlineCalc:
    def test_out_of_state_business_gets_extended_deadline(self, api):
        """PRD §3.3: "A business whose `home_state` matches the complaint's `incident_state` receives thirty days from the moment of notification; an out-of-state business receives a fifteen-day extension on top, forty-five days in total."
        PRD §3.2: "A decision of `ACCEPT` requires jurisdiction: either the incident took place in Oregon or the respondent's operating states include Oregon"

        Design: Corner/calculations/c_calc_out_of_state_deadline
        """
        consumer = register_consumer(full_name="OS", email="os@x.com", state_code="OR")
        business = register_business(
            legal_name="OutCo", home_state="CA", operates_in_states=["OR", "CA"]
        )
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, description="os")
        screen_accept(complaint["id"])
        notified = notify_business(complaint["id"])
        assert_iso_instant(
            notified["response_deadline"], "2026-09-15T00:00:00Z", "response_deadline"
        )


class TestDeadlineInstantBoundary:
    def test_response_at_exact_deadline_instant_is_timely(self, api):
        """PRD §3.3: "A response arriving at the exact deadline instant is timely — the clock sweep flips a case to overdue only when the current time has passed the deadline strictly."
        PRD §2.6: "First, complaints still in `BUSINESS_NOTIFIED` whose `response_deadline` has strictly passed flip to `RESPONSE_OVERDUE`."

        Design: Difficulty/boundary_precision_check/d_boundary_response_deadline_instant
        """
        consumer = register_consumer(full_name="C T", email="ct@x.com", state_code="OR")
        business = register_business(legal_name="TimeCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, description="k1")
        screen_accept(complaint["id"])
        notified = notify_business(complaint["id"])
        assert_iso_instant(
            notified["response_deadline"], "2026-08-31T00:00:00Z", "response_deadline"
        )

        set_clock("2026-08-31T00:00:00Z")  # equality: the sweep must not flip
        response = submit_response(complaint["id"], business, response_text="on the dot")
        assert_business_response(response)
        assert response["is_late"] is False, "submitted_at == deadline is timely"
        after = get_complaint(complaint["id"])
        assert after["case_status"] == "RESPONSE_RECEIVED"
        assert after["ever_response_overdue"] is False

    def test_response_one_second_past_deadline_is_late(self, api):
        """PRD §3.3: "A response arriving at the exact deadline instant is timely — the clock sweep flips a case to overdue only when the current time has passed the deadline strictly."
        PRD §3.3: "a late answer submitted from `RESPONSE_OVERDUE` is always late"
        PRD §3.3: "moves the complaint to `RESPONSE_RECEIVED` from either `BUSINESS_NOTIFIED` or `RESPONSE_OVERDUE`"

        Design: Difficulty/boundary_precision_check/d_boundary_response_deadline_instant
        """
        consumer = register_consumer(full_name="C T2", email="ct2@x.com", state_code="OR")
        business = register_business(legal_name="TimeCo2", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, description="k2")
        screen_accept(complaint["id"])
        notify_business(complaint["id"])  # deadline 2026-08-31T00:00:00Z

        set_clock("2026-08-31T00:00:01Z")  # one second past: sweep flips the case
        flipped = get_complaint(complaint["id"])
        assert flipped["case_status"] == "RESPONSE_OVERDUE"
        assert flipped["ever_response_overdue"] is True

        response = submit_response(complaint["id"], business, response_text="one second late")
        assert response["is_late"] is True
        after = get_complaint(complaint["id"])
        assert after["case_status"] == "RESPONSE_RECEIVED", "late response is still accepted"
        assert after["ever_response_overdue"] is True


class TestResubmissionCycle:
    def test_insufficient_review_reverts_complaint_for_resubmission(self, api):
        """PRD §3.3: "A `verdict` of `INSUFFICIENT` moves `response_status` to `INSUFFICIENT_RETURNED` and sends the complaint back to `BUSINESS_NOTIFIED` to await resubmission: the original deadline does not move, the spent attempt still counts, and the three-attempt cap will apply to the next submission."
        PRD §3.3: "A `verdict` of `SUFFICIENT` moves `response_status` to `SUFFICIENT` and leaves the complaint in `RESPONSE_RECEIVED`, where mediation may now be offered."

        Design: Corner/state_machines/c_sm_response_resubmission_cycle
        """
        consumer = register_consumer(full_name="Re", email="re@x.com", state_code="OR")
        business = register_business(legal_name="ReCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, category="BILLING_DISPUTE", description="re")
        screen_accept(complaint["id"])
        notify_business(complaint["id"])

        r1 = submit_response(complaint["id"], business, response_text="thin")
        assert r1["attempt_number"] == 1
        v1 = review_response(r1["id"], "INSUFFICIENT")
        assert v1["response_status"] == "INSUFFICIENT_RETURNED"
        mid = get_complaint(complaint["id"])
        assert mid["case_status"] == "BUSINESS_NOTIFIED", "insufficient review reverts the case"

        r2 = submit_response(complaint["id"], business, response_text="complete answer")
        assert r2["attempt_number"] == 2, "the spent attempt still counts"
        v2 = review_response(r2["id"], "SUFFICIENT")
        assert v2["response_status"] == "SUFFICIENT"
        fin = get_complaint(complaint["id"])
        assert fin["case_status"] == "RESPONSE_RECEIVED"
        assert fin["response_attempts"] == 2

    def test_fourth_response_exceeds_resubmission_cap(self, api):
        """PRD §3.3: "A complaint accepts at most three responses in its life; once `response_attempts` has reached three, further submissions are refused with `ERR_RESUBMISSION_CAP_REACHED`."

        Design: Corner/state_machines/c_sm_resubmission_cap_rejected
        """
        consumer = register_consumer(full_name="Cap", email="cap@x.com", state_code="OR")
        business = register_business(legal_name="CapCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, category="BILLING_DISPUTE", description="cap")
        screen_accept(complaint["id"])
        notify_business(complaint["id"])

        for i in (1, 2, 3):
            response = submit_response(complaint["id"], business, response_text=f"r{i}")
            assert response["attempt_number"] == i
            review_response(response["id"], "INSUFFICIENT")

        resp = api.submit_business_response(
            complaint["id"], {"response_text": "r4"}, make_business_headers(business["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESUBMISSION_CAP_REACHED)
        after = get_complaint(complaint["id"])
        assert after["response_attempts"] == 3, "cap rejection does not consume an attempt"
        assert after["case_status"] == "BUSINESS_NOTIFIED"


class TestSufficientResponseGate:
    def test_offer_mediation_blocked_until_response_sufficient(self, api):
        """PRD §3.3: "From `RESPONSE_RECEIVED` it requires the latest response to be `SUFFICIENT`, and from `RESPONSE_OVERDUE` it may proceed with no adequate response at all"
        PRD §3.3: "A `verdict` of `INSUFFICIENT` moves `response_status` to `INSUFFICIENT_RETURNED` and sends the complaint back to `BUSINESS_NOTIFIED` to await resubmission"
        PRD §2.12: "6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/d_xstate_complaint_needs_sufficient_response
        """
        consumer = register_consumer(full_name="C G", email="cg@x.com", state_code="OR")
        business = register_business(legal_name="GateCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(
            consumer, business, category="DEFECTIVE_PRODUCT", description="gate"
        )
        screen_accept(complaint["id"])
        notify_business(complaint["id"])
        r1 = submit_response(complaint["id"], business, response_text="deny everything")
        review_response(r1["id"], "INSUFFICIENT")

        resp = api.offer_mediation(complaint["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_offer_mediation_opens_after_sufficient_resubmission(self, api):
        """PRD §3.3: "From `RESPONSE_RECEIVED` it requires the latest response to be `SUFFICIENT`, and from `RESPONSE_OVERDUE` it may proceed with no adequate response at all; either path lands the complaint in `MEDIATION_OFFERED`."
        PRD §3.3: "the original deadline does not move, the spent attempt still counts, and the three-attempt cap will apply to the next submission"

        Design: Difficulty/cross_entity_state_dependency/d_xstate_complaint_needs_sufficient_response
        """
        consumer = register_consumer(full_name="C G2", email="cg2@x.com", state_code="OR")
        business = register_business(legal_name="GateCo2", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(
            consumer, business, category="DEFECTIVE_PRODUCT", description="gate"
        )
        screen_accept(complaint["id"])
        notify_business(complaint["id"])
        r1 = submit_response(complaint["id"], business, response_text="deny everything")
        review_response(r1["id"], "INSUFFICIENT")

        r2 = submit_response(complaint["id"], business, response_text="full answer with remedy")
        assert r2["attempt_number"] == 2, "resubmission counted on the complaint"
        review_response(r2["id"], "SUFFICIENT")

        offered = offer_mediation(complaint["id"])
        assert offered["case_status"] == "MEDIATION_OFFERED"
