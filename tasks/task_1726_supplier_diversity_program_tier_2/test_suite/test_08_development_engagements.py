"""Development engagements: activation sweep, completion improvement, the
pre-ACTIVE lockdown, and the half-open window + 30-day buffer overlap rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_engagement_payload,
    create_engagement_payload,
    create_supplier,
    enroll_engagement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST1 = TEST_USERS["analyst_1_headers"]


class TestEngagementLifecycle:
    def test_engagement_improvement_computed_on_complete(self, api):
        """PRD §3.5: "The engagement activation sweep then examines every
        development engagement in `ENROLLED`: any whose `start_date` is on or
        before the new clock date becomes `ACTIVE`."
        PRD §3.8: "Completing an `ACTIVE` engagement takes
        `capacity_score_after`, the exit capability score between 0 and 100
        inclusive; it moves the engagement to `COMPLETED` and sets
        `improvement` to `capacity_score_after` minus
        `capacity_score_before`."

        Design: Corner/entities/engagement_improvement_computed_on_complete
        """
        supplier = create_supplier(legal_name="Mentee Co", tax_id="T-MEN")
        eng = enroll_engagement(supplier["id"], start_date="2026-07-01",
                                end_date="2026-09-30",
                                capacity_score_before=40)
        assert eng["status"] == "ENROLLED", "A new engagement starts ENROLLED"
        set_clock("2026-08-02T00:00:00Z")
        engs, _meta = validate_paginated(
            api.list_engagements(supplier["id"], ANALYST1))
        assert engs[0]["status"] == "ACTIVE", (
            "start_date 2026-07-01 is on or before the new clock date "
            "2026-08-02"
        )
        completed = validate_success(api.complete_engagement(
            eng["id"], complete_engagement_payload(75), ANALYST1))
        assert completed["status"] == "COMPLETED"
        assert completed["improvement"] == 35, "75 - 40"
        assert completed["capacity_score_after"] == 75

    def test_engagement_complete_before_active_rejected(self, api):
        """PRD §3.8: "Completing an `ACTIVE` engagement takes
        `capacity_score_after`, the exit capability score between 0 and 100
        inclusive; it moves the engagement to `COMPLETED`"
        PRD §2.8: "Fourth, whether the target resource is in a state from
        which the requested transition is defined."

        Design: Corner/state_machines/engagement_complete_before_active_rejected
        """
        supplier = create_supplier(legal_name="Mentee Co", tax_id="T-MEN")
        # Starts after the startup clock date 2026-08-01: stays ENROLLED.
        eng = enroll_engagement(supplier["id"], start_date="2027-01-01",
                                end_date="2027-06-30",
                                capacity_score_before=40)
        assert eng["status"] == "ENROLLED"
        resp = api.complete_engagement(
            eng["id"], complete_engagement_payload(75), ANALYST1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEngagementOverlapBuffer:
    def test_engagement_start_inside_30_day_buffer_rejected(self, api):
        """PRD §3.8: "the new engagement's half-open window may not overlap
        such an existing engagement's window, and it may not start less than
        30 days after that engagement's `end_date` — a violation is
        `ERR_ENGAGEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_window_with_buffer
        """
        supplier = create_supplier(legal_name="Mentee Co", tax_id="T-MEN")
        eng1 = enroll_engagement(supplier["id"], start_date="2026-03-01",
                                 end_date="2026-06-30")
        assert eng1["status"] == "ENROLLED"
        # 2026-07-29 is 29 days after the existing window's exclusive end
        # 2026-06-30: inside the 30-day buffer.
        resp = api.create_engagement(
            supplier["id"],
            create_engagement_payload(track="CAPABILITY_BUILDING",
                                      start_date="2026-07-29",
                                      end_date="2026-10-31",
                                      mentor_name="Mentor B",
                                      capacity_score_before=50),
            ANALYST1)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)
        engs, meta = validate_paginated(
            api.list_engagements(supplier["id"], ANALYST1))
        assert meta["total_count"] == 1, (
            "The rejected enrollment creates no engagement"
        )

    def test_engagement_start_exactly_at_buffer_end_accepted(self, api):
        """PRD §3.8: "the new engagement's half-open window may not overlap
        such an existing engagement's window, and it may not start less than
        30 days after that engagement's `end_date` — a violation is
        `ERR_ENGAGEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_window_with_buffer
        """
        supplier = create_supplier(legal_name="Mentee Co", tax_id="T-MEN")
        eng1 = enroll_engagement(supplier["id"], start_date="2026-03-01",
                                 end_date="2026-06-30")
        assert eng1["status"] == "ENROLLED"
        # 2026-07-30 is exactly 30 days after 2026-06-30: not "less than 30
        # days after", so the buffer is satisfied.
        eng2 = validate_success(api.create_engagement(
            supplier["id"],
            create_engagement_payload(track="CAPABILITY_BUILDING",
                                      start_date="2026-07-30",
                                      end_date="2026-10-31",
                                      mentor_name="Mentor B",
                                      capacity_score_before=50),
            ANALYST1), 201)
        assert eng2["status"] == "ENROLLED"
