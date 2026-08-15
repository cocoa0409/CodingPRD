"""Cost estimates, public hearings, statutory notice, and venue exclusion
(PRD §3.3, §3.4, §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_estimate,
    create_district,
    create_hearing_payload,
    create_owner,
    create_parcel,
    district_version,
    drive_to_hearing_scheduled,
    drive_to_objection_window,
    drive_to_scoping,
    open_petition,
    schedule_hearing,
    set_clock,
    sign_and_verify,
    submit_and_approve_estimate,
    submit_estimate,
    api_client,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["clerk_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
ENGINEER2 = TEST_USERS["engineer2_headers"]


class TestEstimateSupersede:
    def test_estimate_supersede_and_stale_approve_rejected(self, api):
        """PRD §3.3: "a `SUBMITTED` estimate is superseded when a newer
        estimate is created". PRD §3.3: "An engineer approves an estimate only
        while it is `SUBMITTED` (`ERR_ESTIMATE_NOT_SUBMITTED`)".

        Design: Corner/state_machines/sm_estimate_supersede_and_stale_approve_rejected
        """
        ctx = drive_to_scoping("SES", prefix="ses")
        district_id = ctx["district"]["id"]
        submit_and_approve_estimate(district_id, 100000, 0)
        e1 = submit_estimate(district_id, 100000, 0)
        e2 = submit_estimate(district_id, 110000, 0)

        # The first SUBMITTED estimate was superseded by the newer create.
        validate_error(
            api_client.approve_cost_estimate(e1["id"], ENGINEER),
            ApiErrorId.ERR_ESTIMATE_NOT_SUBMITTED,
        )
        stale = validate_success(api_client.get_cost_estimate(e1["id"], ENGINEER))
        assert stale["status"] == "SUPERSEDED"

        approved = approve_estimate(e2["id"])
        assert approved["status"] == "APPROVED"

    def test_estimate_create_stale_district_version_rejected(self, api):
        """PRD §2.7: "Submitting a cost estimate requires
        `expected_district_version` equal to the district's current `version`."
        and "a mismatch with the parent's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD §3.3: "Because a fresh submission
        legitimately supersedes any estimate of the district still `SUBMITTED`,
        the create must carry `expected_district_version` matching the
        district's current `version`; a writer holding a stale district view is
        refused with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/x_occ_estimate_create_stale_district_version
        """
        ctx = drive_to_scoping("XOC1", prefix="xoc1")
        district_id = ctx["district"]["id"]
        submit_and_approve_estimate(district_id, 100000, 0)
        stale_version = district_version(district_id)

        first = validate_success(
            api_client.create_cost_estimate(
                {
                    "district_id": district_id,
                    "expected_district_version": stale_version,
                    "contract_price_cents": 100000,
                    "contingency_cents": 0,
                },
                ENGINEER,
            ),
            expected_status=201,
        )
        # The first create advanced the district version; the second writer
        # holding the pre-create view must be refused.
        validate_error(
            api_client.create_cost_estimate(
                {
                    "district_id": district_id,
                    "expected_district_version": stale_version,
                    "contract_price_cents": 101000,
                    "contingency_cents": 0,
                },
                ENGINEER2,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        still_submitted = validate_success(
            api_client.get_cost_estimate(first["id"], ENGINEER)
        )
        assert still_submitted["status"] == "SUBMITTED", (
            "the rejected stale write must not supersede the live estimate"
        )


class TestEstimateStateGates:
    def test_estimate_create_requires_scoping(self, api):
        """PRD §3.3: "Submitting in a district that is not in `SCOPING` fails
        with `ERR_DISTRICT_NOT_IN_SCOPING`."

        Design: Corner/errors/err_estimate_create_requires_scoping
        """
        district = create_district(name="EES")
        owner = create_owner(full_name="Owner ees1", email="ees-o1@x.test")
        parcel = create_parcel(district["id"], owner["id"])
        petition = open_petition(district["id"])
        sign_and_verify(petition["id"], parcel["id"], owner["id"])
        # District is PETITIONING (petition open, not yet closed).
        version = district_version(district["id"])
        validate_error(
            api_client.create_cost_estimate(
                {
                    "district_id": district["id"],
                    "expected_district_version": version,
                    "contract_price_cents": 100000,
                    "contingency_cents": 0,
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_DISTRICT_NOT_IN_SCOPING,
        )

    def test_clerk_cannot_approve_estimate(self, api):
        """PRD §2.1: "When the supplied role is not among the roles an endpoint
        admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4: "POST `/cost-estimates/{id}/approve` | Engineer
        approves a SUBMITTED estimate | CityEngineer".

        Design: Corner/rbac/r_clerk_cannot_approve_estimate
        """
        ctx = drive_to_scoping("RCA", prefix="rca")
        submit_and_approve_estimate(ctx["district"]["id"], 100000, 0)
        e2 = submit_estimate(ctx["district"]["id"], 100000, 0)
        validate_error(
            api_client.approve_cost_estimate(e2["id"], CLERK),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )


class TestHearingScheduling:
    def test_record_held_twice_rejected(self, api):
        """PRD §3.4: "Only a `SCHEDULED` hearing can be recorded
        (`ERR_HEARING_NOT_SCHEDULED`)".

        Design: Corner/state_machines/sm_record_held_twice_rejected
        """
        ctx = drive_to_objection_window("SRH", prefix="srh", venue="SRH Room")
        validate_error(
            api_client.record_hearing_held(ctx["hearing"]["id"], CLERK),
            ApiErrorId.ERR_HEARING_NOT_SCHEDULED,
        )

    def test_hearing_notice_exactly_ten_days(self, api):
        """PRD §3.3: "Statutory notice requires `hearing_date` to fall at least
        ten days after the scheduling instant (`ERR_HEARING_NOTICE_TOO_SHORT`)."

        Design: Corner/validations/v_hearing_notice_exactly_ten_days
        """
        # Logical clock starts at 2026-08-01T00:00:00Z.
        ctx1 = drive_to_scoping("HN1", prefix="hn1")
        submit_and_approve_estimate(ctx1["district"]["id"], 100000, 0)
        ok = validate_success(
            api_client.create_hearing(
                create_hearing_payload(district_id=ctx1["district"]["id"],
                                       hearing_date="2026-08-11T00:00:00Z",
                                       venue="HN Room"),
                CLERK,
            ),
            expected_status=201,
        )
        assert ok["status"] == "SCHEDULED", "exactly now + 10 days is legal (>=)"

        ctx2 = drive_to_scoping("HN2", prefix="hn2")
        submit_and_approve_estimate(ctx2["district"]["id"], 100000, 0)
        validate_error(
            api_client.create_hearing(
                create_hearing_payload(district_id=ctx2["district"]["id"],
                                       hearing_date="2026-08-10T23:59:59Z",
                                       venue="HN Room"),
                CLERK,
            ),
            ApiErrorId.ERR_HEARING_NOTICE_TOO_SHORT,
        )

    def test_record_held_before_hearing_date_rejected(self, api):
        """PRD §3.4: "recording before `hearing_date` fails with
        `ERR_HEARING_DATE_NOT_REACHED`."

        Design: Corner/errors/err_hearing_date_not_reached_triggered
        """
        ctx = drive_to_hearing_scheduled("EHR", prefix="ehr", venue="EHR Room")
        set_clock("2026-08-14T23:59:59Z")  # one second before the hearing
        validate_error(
            api_client.record_hearing_held(ctx["hearing"]["id"], CLERK),
            ApiErrorId.ERR_HEARING_DATE_NOT_REACHED,
        )


class TestVenueDateExclusion:
    def test_same_venue_same_date_rejected(self, api):
        """PRD §3.3: "The calendar is venue-exclusive at whole-day granularity:
        if any hearing still `SCHEDULED` or `HELD` — in any district, not only
        this one — already occupies the same `venue` string on the same UTC
        calendar date, the request is rejected with `ERR_VENUE_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/venue_same_day_exclusion_semantics
        """
        ctx_a = drive_to_scoping("OV2-A", prefix="ov2a")
        submit_and_approve_estimate(ctx_a["district"]["id"], 100000, 0)
        schedule_hearing(ctx_a["district"]["id"], "2026-08-15T00:00:00Z", "Civic Hall")

        ctx_b = drive_to_scoping("OV2-B", prefix="ov2b")
        submit_and_approve_estimate(ctx_b["district"]["id"], 100000, 0)
        validate_error(
            api_client.create_hearing(
                create_hearing_payload(district_id=ctx_b["district"]["id"],
                                       hearing_date="2026-08-15T00:00:00Z",
                                       venue="Civic Hall"),
                CLERK,
            ),
            ApiErrorId.ERR_VENUE_DATE_CONFLICT,
        )

    def test_same_venue_adjacent_date_accepted(self, api):
        """PRD §3.3: "adjacent dates need no buffer." PRD §3.3: "A scheduled
        hearing opens in `SCHEDULED` with `objection_window_end` fixed at
        fifteen days after `hearing_date`."

        Design: Difficulty/resource_temporal_overlap/venue_same_day_exclusion_semantics
        """
        ctx_a = drive_to_scoping("OV2-A", prefix="ov2a")
        submit_and_approve_estimate(ctx_a["district"]["id"], 100000, 0)
        schedule_hearing(ctx_a["district"]["id"], "2026-08-15T00:00:00Z", "Civic Hall")

        ctx_b = drive_to_scoping("OV2-B", prefix="ov2b")
        submit_and_approve_estimate(ctx_b["district"]["id"], 100000, 0)
        created = validate_success(
            api_client.create_hearing(
                create_hearing_payload(district_id=ctx_b["district"]["id"],
                                       hearing_date="2026-08-16T00:00:00Z",
                                       venue="Civic Hall"),
                CLERK,
            ),
            expected_status=201,
        )
        assert created["status"] == "SCHEDULED", (
            "whole-day exclusion applies no buffer to adjacent dates"
        )
