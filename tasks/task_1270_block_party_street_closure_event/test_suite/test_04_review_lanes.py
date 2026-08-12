"""Review lanes: traffic control safety gates, sound rules, insurance review and
supersede, and singleton children (PRD §3.4)."""
import pytest

from test_helpers import (
    SAFETY,
    api_client,
    assert_insurance_certificate,
    assert_sound_plan,
    assert_traffic_control_plan,
    create_application_record,
    create_insurance_record,
    create_sound_plan_record,
    create_tcp_record,
    get_application_record,
    make_organizer_headers,
    review_tcp_record,
    setup_draft_application,
    setup_under_review_application,
    submit_application_record,
    submit_tcp_record,
    validate_error,
    validate_success,
)


class TestTrafficControlPlanLoop:
    def test_changes_requested_loop_records_reviewer_and_versions(self, api):
        """PRD §3.4: "`APPROVE` moves the plan to `TCP_APPROVED`, `REQUEST_CHANGES` returns
        it to `CHANGES_REQUESTED`, and either way the reviewer is recorded as `reviewed_by`
        with the supplied `note` stored in `review_note` (both fields remain empty until the
        first review)."
        PRD §3.4: "While the plan is `DRAFT` or `CHANGES_REQUESTED` the organizer may revise
        any of those six fields, each revision incrementing the plan's `version`."
        PRD §2.4: "`version` (integer): a server-managed integer that increments by one on
        every mutation of the resource, again including cascade-driven mutations."

        Design: Corner/state_machines/tcp_changes_requested_loop
        """
        ctx = setup_under_review_application(segment_overrides={"length_m": 48})
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        tcp = create_tcp_record(app, organizer, barricade_count=4)
        created_version = tcp["version"]
        submit_tcp_record(tcp["id"], organizer)

        # REQUEST_CHANGES -> CHANGES_REQUESTED with reviewer attribution.
        res = api.review_traffic_control_plan(
            tcp["id"], {"decision": "REQUEST_CHANGES", "note": "add midblock cones"},
            {"X-User-ID": "tr-1", "X-User-Role": "TrafficReviewer", "Content-Type": "application/json"},
        )
        tcp_now = validate_success(res, 200)
        assert tcp_now["status"] == "CHANGES_REQUESTED"
        assert tcp_now["review_note"] == "add midblock cones"
        assert tcp_now["reviewed_by"] == "tr-1"

        # PATCH is a revision: version increments by exactly one.
        patched = validate_success(
            api.patch_traffic_control_plan(tcp["id"], {"cone_count": 6}, headers), 200
        )
        assert patched["version"] == tcp_now["version"] + 1
        assert patched["cone_count"] == 6

        # Resubmit from CHANGES_REQUESTED re-runs validations; approve closes the loop.
        resubmitted = submit_tcp_record(tcp["id"], organizer)
        assert resubmitted["status"] == "SUBMITTED"
        approved = review_tcp_record(tcp["id"], "APPROVE")
        assert approved["status"] == "TCP_APPROVED"
        assert approved["version"] == created_version + 5, (
            "five mutations after create: patch, submit, review, submit, review"
        )


class TestTrafficSafetyGates:
    def _two_apps_with_plans(self, api):
        ctx = setup_under_review_application(segment_overrides={"length_m": 48})
        petition, organizer = ctx["petition"], ctx["organizer"]
        app_2 = create_application_record(
            petition, organizer,
            event_start_at="2026-06-27T14:00:00Z", event_end_at="2026-06-27T22:00:00Z",
        )
        ctx["application"] = submit_application_record(ctx["application"], organizer) \
            if ctx["application"]["status"] == "DRAFT" else ctx["application"]
        submit_application_record(app_2, organizer)
        tcp_1 = create_tcp_record(
            ctx["application"], organizer,
            barricade_count=4, emergency_lane_width_m=5.9, emergency_lane_continuous=True,
            placement_notes="narrow lane",
        )
        tcp_2 = create_tcp_record(
            app_2, organizer,
            barricade_count=3, emergency_lane_width_m=6.5, emergency_lane_continuous=True,
            placement_notes="too few barricades",
        )
        return ctx, tcp_1, tcp_2

    def test_lane_and_barricade_violations_rejected(self, api):
        """PRD §3.4: "the emergency lane must be continuous end-to-end for the full closure
        with `emergency_lane_width_m` of at least 6.0 metres (exactly 6.0 passes; violations
        raise `ERR_EMERGENCY_LANE_VIOLATION`), and `barricade_count` must reach the segment
        minimum — the segment's `length_m` divided by 12 and rounded up to a whole number,
        plus 4 additional barricades when the segment `intersects_arterial` (shortfalls
        raise `ERR_BARRICADE_PLAN_INSUFFICIENT`)."

        Design: Corner/validations/tcp_safety_violations_lane_and_barricade
        """
        ctx, tcp_1, tcp_2 = self._two_apps_with_plans(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # Lane 5.9m < 6.0m.
        res = api.submit_traffic_control_plan(tcp_1["id"], headers)
        validate_error(res, "ERR_EMERGENCY_LANE_VIOLATION")
        plan = validate_success(api.get_traffic_control_plan(tcp_1["id"], headers), 200)
        assert plan["status"] == "DRAFT"
        # ceil(48/12) = 4 required; plan has 3.
        res = api.submit_traffic_control_plan(tcp_2["id"], headers)
        validate_error(res, "ERR_BARRICADE_PLAN_INSUFFICIENT")
        plan = validate_success(api.get_traffic_control_plan(tcp_2["id"], headers), 200)
        assert plan["status"] == "DRAFT"


class TestSoundPlanRules:
    def test_sound_plan_without_amplified_rejected(self, api):
        """PRD §3.4: "A SoundPlan may be created only when the application's
        `amplified_sound` is true — creating one for a quiet event is rejected with
        `ERR_SOUND_NOT_REQUESTED`".

        Design: Corner/validations/sound_plan_without_amplified_returns_409
        """
        ctx = setup_under_review_application(
            application_overrides={"amplified_sound": False}
        )
        app, organizer = ctx["application"], ctx["organizer"]
        res = api.create_sound_plan(
            app["id"],
            {"speaker_count": 2, "max_db_at_property_line": 60, "planned_sound_end": "20:00"},
            make_organizer_headers(organizer["id"]),
        )
        validate_error(res, "ERR_SOUND_NOT_REQUESTED")

    def test_db_cap_beats_cutoff_when_both_violated(self, api):
        """PRD §2.6: "the platform evaluates validation classes in a fixed priority order,
        and the earliest failing class determines the error returned."
        PRD §3.4: "enforces, in this order: first the decibel cap, where a declared level
        above 70 dB at the nearest property line is rejected with `ERR_SOUND_DB_EXCEEDED`
        (exactly 70 passes); then the day-of-week cutoff, where amplified sound must end by
        22:00 when the day of `event_start_at` falls on a Friday or Saturday and by 21:00 on
        any other day, with a planned end exactly at the cutoff passing and anything later
        rejected with `ERR_SOUND_CUTOFF_VIOLATION`."

        Design: Corner/validations/safety_beats_temporal_on_sound_submit
        """
        ctx = setup_under_review_application(
            application_overrides={
                "amplified_sound": True,
                "event_start_at": "2026-06-22T14:00:00Z",  # Monday
                "event_end_at": "2026-06-22T22:00:00Z",
            }
        )
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        sound = create_sound_plan_record(
            app, organizer, speaker_count=6, max_db_at_property_line=80,
            planned_sound_end="22:30",
        )
        res = api.submit_sound_plan(sound["id"], headers)
        validate_error(res, "ERR_SOUND_DB_EXCEEDED")

    def test_sound_cutoff_weekday_vs_weekend(self, api):
        """PRD §3.4: "then the day-of-week cutoff, where amplified sound must end by 22:00
        when the day of `event_start_at` falls on a Friday or Saturday and by 21:00 on any
        other day, with a planned end exactly at the cutoff passing and anything later
        rejected with `ERR_SOUND_CUTOFF_VIOLATION`."

        Design: Corner/validations/sound_cutoff_weekday_vs_weekend
        """
        ctx = setup_under_review_application(
            application_overrides={
                "amplified_sound": True,
                "event_start_at": "2026-06-19T14:00:00Z",  # Friday
                "event_end_at": "2026-06-19T22:00:00Z",
            }
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        app_m = create_application_record(
            petition, organizer,
            event_start_at="2026-06-22T14:00:00Z", event_end_at="2026-06-22T22:00:00Z",
            amplified_sound=True,
        )
        submit_application_record(app_m, organizer)
        sp_f = create_sound_plan_record(
            ctx["application"], organizer, speaker_count=2,
            max_db_at_property_line=65, planned_sound_end="21:30",
        )
        sp_m = create_sound_plan_record(
            app_m, organizer, speaker_count=2,
            max_db_at_property_line=65, planned_sound_end="21:30",
        )
        friday = validate_success(api.submit_sound_plan(sp_f["id"], headers), 200)
        assert friday["status"] == "SUBMITTED", "21:30 <= 22:00 Friday cutoff passes"
        res = api.submit_sound_plan(sp_m["id"], headers)
        validate_error(res, "ERR_SOUND_CUTOFF_VIOLATION")


class TestInsuranceLane:
    def test_create_supersedes_prior_submitted_record(self, api):
        """PRD §3.4: "A successful create starts the new record at `SUBMITTED`, supersedes
        every prior record still sitting in `SUBMITTED`, `REJECTED`, or `WAIVER_DENIED` —
        each such record moves to `SUPERSEDED` with `superseded_by_id` pointing at the newer
        record (the pointer stays empty on any record that was never superseded) — and
        increments the application's `version` by one, which is exactly why a stale read of
        the application is dangerous here."

        Design: Corner/validations/insurance_create_supersedes_prior_records
        """
        ctx = setup_under_review_application()
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        first = create_insurance_record(app["id"], organizer, app["version"],
                                        insurer_name="Acme Mutual", policy_number="P-140")
        assert first["status"] == "SUBMITTED"

        current = get_application_record(app["id"], organizer)
        assert current["version"] == app["version"] + 1, "insurance create bumps the version"
        second = create_insurance_record(
            app["id"], organizer, current["version"],
            insurer_name="Beta Assurance", policy_number="P-141",
            coverage_amount_cents=200000000, expires_on="2027-06-30",
        )
        assert second["status"] == "SUBMITTED"
        stale_first = validate_success(api.get_insurance_certificate(first["id"], headers), 200)
        assert_insurance_certificate(stale_first)
        assert stale_first["status"] == "SUPERSEDED"
        assert stale_first["superseded_by_id"] == second["id"]

    def test_coverage_and_expiry_boundaries(self, api):
        """PRD §3.4: "Approving a `CERTIFICATE` demands `coverage_amount_cents` of at least
        100000000 cents — one million dollars of liability coverage, with shortfalls rejected
        as `ERR_INSURANCE_COVERAGE_INSUFFICIENT` — and an `expires_on` on or after the
        event's calendar date, with an earlier expiry rejected as `ERR_INSURANCE_EXPIRED`;
        success marks the record `VERIFIED`."

        Design: Corner/validations/insurance_review_boundary_and_expiry
        """
        ctx = setup_under_review_application()
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])

        # Coverage one cent short of the $1M floor.
        low = create_insurance_record(app["id"], organizer, app["version"],
                                      coverage_amount_cents=99999999)
        res = api.review_insurance_certificate(low["id"], {"decision": "APPROVE"}, SAFETY)
        validate_error(res, "ERR_INSURANCE_COVERAGE_INSUFFICIENT")

        # Expiry one day before the event date (event is 2026-06-20).
        current = get_application_record(app["id"], organizer)
        expired = create_insurance_record(app["id"], organizer, current["version"],
                                          expires_on="2026-06-19")
        res = api.review_insurance_certificate(expired["id"], {"decision": "APPROVE"}, SAFETY)
        validate_error(res, "ERR_INSURANCE_EXPIRED")

        # Exact coverage floor with expiry on the event date: both boundaries inclusive.
        current = get_application_record(app["id"], organizer)
        good = create_insurance_record(app["id"], organizer, current["version"],
                                       coverage_amount_cents=100000000, expires_on="2026-06-20")
        verified = validate_success(
            api.review_insurance_certificate(good["id"], {"decision": "APPROVE"}, SAFETY), 200
        )
        assert verified["status"] == "VERIFIED"

    def test_waiver_eligibility_boundary_75_vs_76(self, api):
        """PRD §3.4: "Approving a `WAIVER_REQUEST` demands waiver eligibility —
        `expected_attendance` of at most 75, no alcohol service, and a `RESIDENTIAL` segment
        — with anything less qualifying rejected as `ERR_WAIVER_INELIGIBLE`; success marks
        the record `WAIVER_GRANTED`."

        Design: Corner/calculations/waiver_eligibility_boundary_75_vs_76
        """
        ctx = setup_under_review_application(application_overrides={"expected_attendance": 75})
        petition, organizer = ctx["petition"], ctx["organizer"]
        app_b = create_application_record(
            petition, organizer,
            event_start_at="2026-06-27T14:00:00Z", event_end_at="2026-06-27T22:00:00Z",
            expected_attendance=76,
        )
        app_b = submit_application_record(app_b, organizer)
        waiver_a = create_insurance_record(
            ctx["application"]["id"], organizer, ctx["application"]["version"],
            kind="WAIVER_REQUEST",
        )
        waiver_b = create_insurance_record(app_b["id"], organizer, app_b["version"],
                                           kind="WAIVER_REQUEST")
        granted = validate_success(
            api.review_insurance_certificate(waiver_a["id"], {"decision": "APPROVE"}, SAFETY), 200
        )
        assert granted["status"] == "WAIVER_GRANTED"
        res = api.review_insurance_certificate(waiver_b["id"], {"decision": "APPROVE"}, SAFETY)
        validate_error(res, "ERR_WAIVER_INELIGIBLE")


class TestSingletonChildren:
    def test_second_traffic_control_plan_rejected(self, api):
        """PRD §3.4: "Three singleton children carry the application's compliance burden,
        each created at most once per application — a second create is refused with
        `ERR_DUPLICATE_RESOURCE`".

        Design: Corner/endpoints/duplicate_tcp_singleton_returns_409
        """
        ctx = setup_draft_application()
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        first = create_tcp_record(app, organizer, barricade_count=1)
        assert_traffic_control_plan(first)
        res = api.create_traffic_control_plan(
            app["id"],
            {
                "barricade_count": 2, "cone_count": 2, "sign_count": 1,
                "emergency_lane_width_m": 7.0, "emergency_lane_continuous": True,
                "placement_notes": "revised",
            },
            headers,
        )
        validate_error(res, "ERR_DUPLICATE_RESOURCE")
