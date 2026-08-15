"""Interval overlap semantics: half-open enrollment intervals vs closed
agreement intervals (PRD §2.7)."""
from test_helpers import (
    ApiErrorId,
    assert_delegation_agreement,
    create_active_agreement,
    create_approved_application,
    create_draft_application,
    create_payer_config,
    create_practice_group,
    create_provider,
    create_submitted_application,
    find_record,
    get_agreement,
    get_roster_line,
    roster_add_line,
    set_clock,
    setup_group_provider_payer,
    submit_roster_file,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestEnrollmentHalfOpenIntervals:
    def test_touching_at_termination_date_allowed_one_day_earlier_rejected(self, api):
        """PRD §2.7: "Enrollment records occupy **half-open** intervals: a
        record covers service dates from its `effective_date` up to but not
        including its `termination_date`. Two records for the same provider and
        payer may never overlap, but touching is allowed — a new record whose
        effective date equals a prior terminated record's termination date is
        a legal back-to-back enrollment."
        PRD §3.3: "no record for the pair may be `ACTIVE` or
        `PENDING_REVALIDATION`, and the computed effective date must not fall
        inside any `TERMINATED` record's half-open interval for the pair,
        although an effective date exactly equal to a prior record's
        termination date is permitted; either violation is
        `ERR_ENROLLMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/enrollment_interval_half_open_touch
        """
        _, provider, _, payer = setup_group_provider_payer(
            payer_overrides={"effective_date_policy": "RETRO_90"},
        )
        # Record A effective 2026-08-01 (approved at the startup clock).
        _, record_a = create_approved_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-01",
        )
        assert record_a["effective_date"] == "2026-08-01"

        set_clock("2026-09-10T00:00:00Z")
        validate_success(
            api.terminate_enrollment_record(
                record_a["id"], {"termination_effective_date": "2026-09-01"}, OFFICER,
            ),
            200,
        )

        # One day before the prior termination date: computed effective
        # max(2026-08-31, 2026-09-10 - 90d) = 2026-08-31, inside
        # [2026-08-01, 2026-09-01) -> overlap.
        app1 = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-31",
        )
        res = api.approve_application(app1["id"], PAYER_REP)
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_OVERLAP)
        validate_success(api.withdraw_application(app1["id"], SPECIALIST), 200)

        # Exactly at the prior termination date: touching is allowed.
        app2 = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-09-01",
        )
        approved = validate_success(api.approve_application(app2["id"], PAYER_REP), 200)
        assert approved["status"] == "APPROVED"
        record_b = find_record(
            provider_id=provider["id"], payer_id=payer["id"], status="ACTIVE",
        )
        assert record_b["effective_date"] == "2026-09-01"

    def test_roster_add_confirm_rejects_overlap_with_terminated_interval(self, api):
        """PRD §3.5: "For an `ADD` line, the confirm-time exclusivity check
        mirrors the application path: no record for the provider and the
        agreement's payer may be `ACTIVE` or `PENDING_REVALIDATION`, and the
        confirmed date must not fall inside a `TERMINATED` record's half-open
        interval — equality with a prior termination date permitted — else
        `ERR_ENROLLMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/enrollment_interval_half_open_touch
        """
        group, provider, _, payer = setup_group_provider_payer()
        _, record_a = create_approved_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-01",
        )
        set_clock("2026-09-10T00:00:00Z")
        validate_success(
            api.terminate_enrollment_record(
                record_a["id"], {"termination_effective_date": "2026-09-01"}, OFFICER,
            ),
            200,
        )

        agreement = create_active_agreement(group["id"], payer["id"])
        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-15")],
        )
        line = get_roster_line(roster["id"], 0)
        # 2026-08-15 falls inside the terminated interval [2026-08-01, 2026-09-01).
        res = api.confirm_roster_line(
            roster["id"], line["id"],
            {"confirmed_effective_date": "2026-08-15"}, PAYER_REP,
        )
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_OVERLAP)
        assert get_roster_line(roster["id"], 0)["status"] == "PENDING"


class TestAgreementClosedIntervals:
    def test_shared_boundary_date_counts_as_overlap(self, api):
        """PRD §2.7: "Delegated credentialing agreements, by contrast, occupy
        **closed** intervals from `effective_date` through `expiry_date`, both
        endpoints inclusive. Two agreements for the same practice group and
        payer whose status is anything other than `TERMINATED` may not
        intersect at all; sharing even a single boundary date already counts as
        overlap and is rejected."

        Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_touch_rejected
        """
        group = create_practice_group()
        payer = create_payer_config()
        a1 = create_active_agreement(
            group["id"], payer["id"],
            effective_date="2026-01-01", expiry_date="2026-12-31",
        )
        assert a1["status"] == "ACTIVE"

        # Touching at the shared boundary date 2026-12-31 is already overlap.
        res = api.create_delegation_agreement(
            {
                "practice_group_id": group["id"],
                "payer_id": payer["id"],
                "effective_date": "2026-12-31",
                "expiry_date": "2027-06-30",
            },
            OFFICER,
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_OVERLAP)

        # The day after expiry is free.
        a2 = validate_success(
            api.create_delegation_agreement(
                {
                    "practice_group_id": group["id"],
                    "payer_id": payer["id"],
                    "effective_date": "2027-01-01",
                    "expiry_date": "2027-06-30",
                },
                OFFICER,
            ),
            201,
        )
        assert_delegation_agreement(a2)
        assert a2["status"] == "ACTIVE"

    def test_terminated_agreement_frees_its_interval(self, api):
        """PRD §2.7: "Two agreements for the same practice group and payer
        whose status is anything other than `TERMINATED` may not intersect at
        all; sharing even a single boundary date already counts as overlap and
        is rejected."

        Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_touch_rejected
        """
        group = create_practice_group()
        payer = create_payer_config()
        a1 = create_active_agreement(
            group["id"], payer["id"],
            effective_date="2026-01-01", expiry_date="2026-12-31",
        )
        validate_success(api.terminate_delegation_agreement(a1["id"], OFFICER), 200)
        assert get_agreement(a1["id"])["status"] == "TERMINATED"

        # A fully intersecting successor is allowed once the incumbent is
        # TERMINATED.
        a2 = validate_success(
            api.create_delegation_agreement(
                {
                    "practice_group_id": group["id"],
                    "payer_id": payer["id"],
                    "effective_date": "2026-06-01",
                    "expiry_date": "2027-06-30",
                },
                OFFICER,
            ),
            201,
        )
        assert a2["status"] == "ACTIVE"
