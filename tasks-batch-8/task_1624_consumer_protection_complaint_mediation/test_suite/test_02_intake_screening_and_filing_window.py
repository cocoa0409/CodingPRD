"""Complaint intake: initial state, filing window boundary, duplicates, screening, appeal."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_complaint,
    assert_iso_instant,
    create_complaint_payload,
    file_complaint,
    make_consumer_headers,
    register_business,
    register_consumer,
    screen_accept,
    set_clock,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]


class TestComplaintInitialState:
    def test_complaint_creation_initial_state(self, api):
        """PRD §3.2: "The complaint is stamped with `filed_at`, opens with a `case_status` of `RECEIVED` and a `publication_status` of `UNPUBLISHED`"
        PRD §3.2: "A `CREATED` event opens the case's audit trail, and `appeal_used`, `response_attempts`, and `ever_response_overdue` all start from their zero values."
        PRD §3.2: "On acceptance of the filing, the complaint draws the business's next filing sequence number: `filing_seq` is copied from the business's `next_filing_seq`, which then advances by one"

        Design: Corner/state_machines/c_sm_complaint_initial_states
        """
        consumer = register_consumer(full_name="Init", email="init@x.com", state_code="OR")
        business = register_business(legal_name="InitCo", home_state="OR", operates_in_states=["OR"])
        complaint = file_complaint(
            consumer, business, category="OTHER", description="init", amount_in_dispute_cents=5
        )
        assert_complaint(complaint)
        assert complaint["case_status"] == "RECEIVED"
        assert complaint["publication_status"] == "UNPUBLISHED"
        assert complaint["appeal_used"] is False
        assert complaint["response_attempts"] == 0
        assert complaint["ever_response_overdue"] is False
        assert complaint["filing_seq"] == 1, "first complaint draws next_filing_seq 1"

    def test_creation_response_carries_computed_fields_immediately(self, api):
        """PRD §3.2: "records its jurisdiction worksheet in `jurisdiction_factors` — three booleans evaluated at creation: `incident_in_state` (the `incident_state` is Oregon, code `OR`), `business_operates_in_state` (Oregon appears in the business's `operates_in_states`), and `within_filing_window`."
        PRD §3.2: "opens with a `case_status` of `RECEIVED` and a `publication_status` of `UNPUBLISHED`"

        Design: Corner/consistency_model/c_cons_immediate_create_computed
        """
        consumer = register_consumer(full_name="IM", email="im@x.com", state_code="OR")
        business = register_business(legal_name="ImCo", home_state="OR", operates_in_states=["OR"])
        complaint = file_complaint(
            consumer, business, category="OTHER", description="im", amount_in_dispute_cents=5
        )
        assert complaint["filing_seq"] == 1
        assert complaint["case_status"] == "RECEIVED"
        assert complaint["jurisdiction_factors"] == {
            "incident_in_state": True,
            "business_operates_in_state": True,
            "within_filing_window": True,
        }, "jurisdiction worksheet is computed in the creation response itself"

    def test_filed_at_uses_default_logical_clock(self, api):
        """PRD §2.6: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."
        PRD §3.2: "The complaint is stamped with `filed_at`"

        Design: Corner/complexity_layers/c_layer_clock_default_filed_at
        """
        consumer = register_consumer(full_name="CK", email="ck@x.com", state_code="OR")
        business = register_business(legal_name="CkCo", home_state="OR", operates_in_states=["OR"])
        # No set_current_utc call: the startup clock must drive filed_at.
        complaint = file_complaint(
            consumer, business, incident_date="2025-09-01",
            category="OTHER", description="ck", amount_in_dispute_cents=5,
        )
        assert_iso_instant(complaint["filed_at"], "2026-08-01T00:00:00Z", "filed_at")


class TestFilingWindowBoundary:
    def test_filing_exactly_365_days_after_incident_is_eligible(self, api):
        """PRD §3.2: "A complaint filed at most 365 days after the incident is eligible, and an elapsed span of exactly 365 days still qualifies; at 366 days the filing is refused with `ERR_FILING_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/d_boundary_filing_window_365
        """
        consumer = register_consumer(full_name="C W", email="cw@x.com", state_code="OR")
        business = register_business(legal_name="WinCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        # 2025-08-01 -> 2026-08-01 is exactly 365 days: eligible (boundary on the allowed side).
        complaint = file_complaint(
            consumer, business, incident_date="2025-08-01",
            category="DECEPTIVE_PRACTICE", description="exactly 365 days",
            amount_in_dispute_cents=100,
        )
        assert complaint["jurisdiction_factors"]["within_filing_window"] is True

    def test_filing_366_days_after_incident_is_rejected(self, api):
        """PRD §3.2: "A complaint filed at most 365 days after the incident is eligible, and an elapsed span of exactly 365 days still qualifies; at 366 days the filing is refused with `ERR_FILING_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/d_boundary_filing_window_365
        """
        consumer = register_consumer(full_name="C W", email="cw2@x.com", state_code="OR")
        business = register_business(legal_name="WinCo2", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-02T00:00:00Z")
        # 2025-08-01 -> 2026-08-02 is 366 days: refused.
        payload = create_complaint_payload(
            consumer["id"], business["id"], incident_date="2025-08-01",
            category="REFUND_REFUSAL", description="366 days", amount_in_dispute_cents=100,
        )
        resp = api.create_complaint(payload, make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_FILING_WINDOW_EXPIRED)


class TestDuplicateAndScreening:
    def test_duplicate_complaint_tuple_rejected_until_original_declined(self, api):
        """PRD §3.2: "a new complaint matching an existing complaint's `consumer_id`, `business_id`, `incident_date`, and `category` is refused with `ERR_DUPLICATE_COMPLAINT` — unless the earlier complaint sits in `DECLINED`, in which case it no longer blocks refiling."
        PRD §3.2: "Before screening, the filing consumer may simply withdraw: the complaint becomes `DECLINED` with `decline_reason` set to `WITHDRAWN` and `closed_at` stamped."

        Design: Corner/validations/c_val_duplicate_complaint_rejected
        """
        consumer = register_consumer(full_name="DP", email="dp@x.com", state_code="OR")
        business = register_business(legal_name="DupCo", home_state="OR", operates_in_states=["OR"])
        first = file_complaint(consumer, business, description="first")

        dup = api.create_complaint(
            create_complaint_payload(consumer["id"], business["id"], description="dup"),
            make_consumer_headers(consumer["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_COMPLAINT)

        withdrawn = validate_success(
            api.withdraw_complaint(first["id"], make_consumer_headers(consumer["id"]))
        )
        assert withdrawn["case_status"] == "DECLINED"
        assert withdrawn["decline_reason"] == "WITHDRAWN"

        refiled = file_complaint(consumer, business, description="refile after withdraw")
        assert refiled["filing_seq"] == 2, "filing_seq keeps climbing on the business"

    def test_screen_accept_twice_rejected(self, api):
        """PRD §3.2: "An `IntakeOfficer` screens each `RECEIVED` complaint with a `decision`."
        PRD §2.12: "6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/c_sm_screen_twice_returns_invalid_state
        """
        consumer = register_consumer(full_name="Twice", email="twice@x.com", state_code="OR")
        business = register_business(legal_name="TwiceCo", home_state="OR", operates_in_states=["OR"])
        complaint = file_complaint(consumer, business, category="OTHER", description="t")
        accepted = screen_accept(complaint["id"])
        assert accepted["case_status"] == "ACCEPTED"

        resp = api.screen_complaint(complaint["id"], {"decision": "ACCEPT"}, OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdrawn_complaint_cannot_be_appealed(self, api):
        """PRD §3.2: "A second appeal is refused with `ERR_APPEAL_ALREADY_USED`, and a withdrawn complaint can never be appealed."
        PRD §2.12: "6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/c_sm_appeal_after_withdrawn_rejected
        """
        consumer = register_consumer(full_name="WD", email="wd@x.com", state_code="OR")
        business = register_business(legal_name="WdCo", home_state="OR", operates_in_states=["OR"])
        complaint = file_complaint(consumer, business, category="OTHER", description="w")
        withdrawn = validate_success(
            api.withdraw_complaint(complaint["id"], make_consumer_headers(consumer["id"]))
        )
        assert withdrawn["decline_reason"] == "WITHDRAWN"

        resp = api.appeal_complaint(complaint["id"], make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        complaint_after = validate_success(api.get_complaint(complaint["id"], OFFICER_1))
        assert complaint_after["case_status"] == "DECLINED", "withdrawn complaints stay DECLINED"
