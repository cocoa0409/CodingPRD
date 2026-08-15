"""Impact records, media-consent publish gate, feedback surveys, and the
partner reputation engine (recency weighting, suspend/reinstate hysteresis)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_feedback_survey,
    check_in_registration,
    complete_event,
    create_impact_record,
    create_partner,
    create_project,
    get_event,
    get_partner,
    get_project,
    get_registration,
    make_employee_volunteer_headers,
    make_nonprofit_coordinator_headers,
    set_clock,
    setup_completed_event,
    setup_in_progress_event,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
    verify_impact_record,
    vet_project,
)

CEM = TEST_USERS["cem_headers"]


class TestHoursDualVariant:
    def _setup_checked_in_with_verified_record(self):
        """One adult CHECKED_IN on a 6.0h event with a 2.5h VERIFIED impact record."""
        sc = setup_in_progress_event(event_name="Day B", verify_waivers=True)
        reg = sc["registrations"][0]
        check_in_registration(reg["id"])
        rec = create_impact_record(
            reg["id"], sc["project"]["id"], sc["partner"]["id"], 2.5, photo_count=0
        )
        verify_impact_record(rec["id"])
        return sc

    def test_registration_shows_scheduled_vs_verified_divergence(self, api):
        """PRD §3.9: "The dual hours accounting is deliberate: a checked-in volunteer's `scheduled_hours_credit` reflects the full event window keyed on the check-in flag, while `verified_hours_credit` reflects only what the nonprofit claimed and staff verified."
        PRD §3.9: "the two legitimately diverge: a volunteer checked in for a 6.0-hour day with 2.5 verified hours shows 6.0 scheduled against 2.5 verified."

        Design: Difficulty/dual_variant_calc/volunteer_hours_scheduled_vs_verified_divergence
        """
        sc = self._setup_checked_in_with_verified_record()
        reg = get_registration(sc["registrations"][0]["id"])
        assert reg["scheduled_hours_credit"] == 6.0  # whole-window credit on CHECKED_IN
        assert reg["verified_hours_credit"] == 2.5  # VERIFIED impact only
        assert reg["scheduled_hours_credit"] != reg["verified_hours_credit"]

    def test_event_totals_mirror_both_variants(self, api):
        """PRD §3.9: "The event mirrors both as `total_scheduled_hours` — the sum of scheduled credits over its registrations — and `total_verified_hours`, and the two legitimately diverge: a volunteer checked in for a 6.0-hour day with 2.5 verified hours shows 6.0 scheduled against 2.5 verified."

        Design: Difficulty/dual_variant_calc/volunteer_hours_scheduled_vs_verified_divergence
        """
        sc = self._setup_checked_in_with_verified_record()
        event = get_event(sc["event"]["id"])
        assert event["total_scheduled_hours"] == 6.0
        assert event["total_verified_hours"] == 2.5


class TestImpactEligibility:
    def test_impact_record_blocked_until_registration_checked_in(self, api, any_headers):
        """PRD §3.9: "The named `project_id` must equal the registration's own `project_id` (`ERR_IMPACT_PROJECT_MISMATCH`, HTTP 422), and the registration must be in `CHECKED_IN` — impact cannot be claimed for someone who never arrived — failing as `ERR_REGISTRATION_NOT_CHECKED_IN`."

        Design: Difficulty/cross_entity_state_dependency/impact_record_blocked_until_registration_checked_in
        """
        # Event IN_PROGRESS; the volunteer is CONFIRMED (waiver VERIFIED) but not checked in
        sc = setup_in_progress_event(event_name="Day M", verify_waivers=True)
        reg = sc["registrations"][0]
        assert get_registration(reg["id"])["rsvp_status"] == "CONFIRMED"

        resp = api.create_impact_record(
            {"registration_id": reg["id"], "project_id": sc["project"]["id"], "hours_attended": 1.0},
            make_nonprofit_coordinator_headers(sc["partner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_CHECKED_IN)

    def test_rejected_impact_create_persists_nothing(self, api, any_headers):
        """PRD §3.9: "The named `project_id` must equal the registration's own `project_id` (`ERR_IMPACT_PROJECT_MISMATCH`, HTTP 422), and the registration must be in `CHECKED_IN` — impact cannot be claimed for someone who never arrived — failing as `ERR_REGISTRATION_NOT_CHECKED_IN`."

        Design: Difficulty/cross_entity_state_dependency/impact_record_blocked_until_registration_checked_in
        """
        sc = setup_in_progress_event(event_name="Day M2", verify_waivers=True)
        reg = sc["registrations"][0]

        api.create_impact_record(
            {"registration_id": reg["id"], "project_id": sc["project"]["id"], "hours_attended": 1.0},
            make_nonprofit_coordinator_headers(sc["partner"]["id"]),
        )
        _, meta = validate_paginated(
            api.list_impact_records(any_headers, params={"registration_id": reg["id"]})
        )
        assert meta["total_count"] == 0

    def test_impact_hours_exceeding_schedule_rejected(self, api):
        """PRD §3.9: "The claimed `hours_attended` must be greater than zero and no more than the event's scheduled hours, otherwise `ERR_VALIDATION`."
        PRD §3.4: "Check-in stamps `checked_in_at` with the current logical clock and sets the registration's `scheduled_hours_credit` to the event's scheduled hours — the duration from `event_start_at` to `event_end_at` expressed in hours, such as 6.0 for a six-hour day — while a registration that never checks in keeps zero scheduled credit."

        Design: Corner/validations/impact_hours_exceeding_schedule_rejected
        """
        sc = setup_in_progress_event(event_name="Day 27", verify_waivers=True)
        reg = sc["registrations"][0]
        check_in_registration(reg["id"])
        np_headers = make_nonprofit_coordinator_headers(sc["partner"]["id"])

        too_much = api.create_impact_record(
            {"registration_id": reg["id"], "project_id": sc["project"]["id"], "hours_attended": 7.0},
            np_headers,
        )
        validate_error(too_much, ApiErrorId.ERR_VALIDATION)

        # Exactly the 6.0h ceiling is inclusive
        at_ceiling = api.create_impact_record(
            {"registration_id": reg["id"], "project_id": sc["project"]["id"], "hours_attended": 6.0},
            np_headers,
        )
        assert validate_success(at_ceiling, 201)["hours_attended"] == 6.0

    def test_impact_project_must_match_registration_project(self, api):
        """PRD §3.9: "The named `project_id` must equal the registration's own `project_id` (`ERR_IMPACT_PROJECT_MISMATCH`, HTTP 422), and the registration must be in `CHECKED_IN` — impact cannot be claimed for someone who never arrived — failing as `ERR_REGISTRATION_NOT_CHECKED_IN`."

        Design: Corner/validations/impact_project_must_match_registration_project
        """
        sc = setup_in_progress_event(event_name="Day 28", verify_waivers=True)
        reg = sc["registrations"][0]
        check_in_registration(reg["id"])
        # A second project of the same nonprofit exists but is NOT the registration's
        # project — the record claims hours against it
        other_project = create_project(sc["partner"]["id"], "Fence Paint")
        resp = api.create_impact_record(
            {
                "registration_id": reg["id"],
                "project_id": other_project["id"],
                "hours_attended": 1.0,
            },
            make_nonprofit_coordinator_headers(sc["partner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_IMPACT_PROJECT_MISMATCH)


class TestMediaConsentGate:
    def test_publish_with_media_requires_consent(self, api):
        """PRD §3.9: "Publication moves `VERIFIED` → `PUBLISHED`, the record's terminal state, and carries the media-consent gate: when the record's `photo_count` is greater than zero or its `story_text` is non-empty, the registration's `media_consent` must be true, otherwise the publish is rejected with `ERR_MEDIA_CONSENT_MISSING`."

        Design: Corner/validations/publish_with_media_requires_consent
        """
        # media_consent False at signing
        sc = setup_in_progress_event(event_name="Day 17", verify_waivers=True)
        reg = sc["registrations"][0]
        check_in_registration(reg["id"])
        assert get_registration(reg["id"])["media_consent"] is False
        np_id = sc["partner"]["id"]

        rec_photo = create_impact_record(reg["id"], sc["project"]["id"], np_id, 1.0, photo_count=2)
        rec_clean = create_impact_record(reg["id"], sc["project"]["id"], np_id, 1.0, photo_count=0)
        verify_impact_record(rec_photo["id"])
        verify_impact_record(rec_clean["id"])

        denied = api.publish_impact_record(rec_photo["id"], CEM)
        validate_error(denied, ApiErrorId.ERR_MEDIA_CONSENT_MISSING)

        ok = api.publish_impact_record(rec_clean["id"], CEM)
        assert validate_success(ok, 200)["status"] == "PUBLISHED"

    def test_impact_publish_from_submitted_rejected(self, api):
        """PRD §3.9: "Publication moves `VERIFIED` → `PUBLISHED`, the record's terminal state, and carries the media-consent gate: when the record's `photo_count` is greater than zero or its `story_text` is non-empty, the registration's `media_consent` must be true, otherwise the publish is rejected with `ERR_MEDIA_CONSENT_MISSING`."
        PRD §3.9: "Any other from-state in this lifecycle is rejected with `ERR_INVALID_IMPACT_TRANSITION`."

        Design: Corner/errors/impact_publish_from_submitted_rejected
        """
        sc = setup_in_progress_event(event_name="Day 41", verify_waivers=True)
        reg = sc["registrations"][0]
        check_in_registration(reg["id"])
        rec = create_impact_record(reg["id"], sc["project"]["id"], sc["partner"]["id"], 1.0)

        resp = api.publish_impact_record(rec["id"], CEM)
        validate_error(resp, ApiErrorId.ERR_INVALID_IMPACT_TRANSITION)


class TestFeedbackSurveys:
    def _setup_one_checkedin_one_noshow(self):
        sc = setup_in_progress_event(event_name="Day 26", num_adults=2, verify_waivers=True)
        check_in_registration(sc["registrations"][0]["id"])  # reg1 only
        complete_event(sc["event"]["id"])
        return sc

    def test_survey_requires_checkedin_and_completed_event(self, api):
        """PRD §3.9: "The registration must be the caller's own (`ERR_FORBIDDEN_ROLE`), must be in `CHECKED_IN`, and its event must be `COMPLETED` or `CLOSED`; the eligibility failures are rejected with `ERR_SURVEY_NOT_ELIGIBLE`, and a second survey for the same registration with `ERR_ONE_SURVEY_PER_REGISTRATION`."

        Design: Corner/validations/survey_requires_checkedin_and_completed_event
        """
        sc = self._setup_one_checkedin_one_noshow()
        reg1, reg2 = sc["registrations"]
        vol1, vol2 = sc["volunteers"]
        assert get_registration(reg2["id"])["rsvp_status"] == "NO_SHOW"

        # NO_SHOW registration is not eligible
        denied = api.create_feedback_survey(
            {"registration_id": reg2["id"], "rating": 4, "would_repeat": True},
            make_employee_volunteer_headers(vol2["id"]),
        )
        validate_error(denied, ApiErrorId.ERR_SURVEY_NOT_ELIGIBLE)

        # The checked-in volunteer's survey succeeds
        created = api.create_feedback_survey(
            {"registration_id": reg1["id"], "rating": 5, "would_repeat": True},
            make_employee_volunteer_headers(vol1["id"]),
        )
        validate_success(created, 201)

        # One survey per registration
        dup = api.create_feedback_survey(
            {"registration_id": reg1["id"], "rating": 3, "would_repeat": False},
            make_employee_volunteer_headers(vol1["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_ONE_SURVEY_PER_REGISTRATION)

    def test_feedback_survey_immutable_common_fields(self, api):
        """PRD §2.4: "Feedback surveys are the single exception: a `FeedbackSurvey` is immutable once created and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from it."

        Design: Corner/entities/feedback_survey_immutable_common_fields
        """
        sc = setup_completed_event(event_name="Day 3", budget_cents=500000)
        reg = sc["registrations"][0]
        created = api.create_feedback_survey(
            {"registration_id": reg["id"], "rating": 5, "would_repeat": True},
            make_employee_volunteer_headers(sc["volunteers"][0]["id"]),
        )
        data = validate_success(created, 201)
        assert_feedback_survey(data)  # id + created_at present; version/updated_at absent


class TestPartnerReputation:
    def test_reputation_recency_weight_halves_after_90_days(self, api, any_headers):
        """PRD §3.9: "The partner's `reputation_score` is recency-weighted: over all surveys reachable from the partner through registration to project (only checked-in registrations ever have surveys, per the eligibility rule), a survey's weight is 1.0 when it was created within the 90 days preceding the current logical clock and 0.5 when older; the score is the sum of each rating multiplied by its weight, divided by the sum of the weights, rounded half-up to two decimal places, and null while no surveys exist."
        PRD §2.5: "Every rule phrased as "the current clock" or "now" in this document — the event-start lead time, the meal-order deadline, the manifest departure check, the feedback recency window — reads this logical clock."

        Design: Corner/calculations/reputation_recency_weight_halves_after_90_days
        """
        sc = setup_completed_event(event_name="Day 12", num_adults=3, budget_cents=500000)
        # Two rating-5 surveys while the clock reads 2026-08-01
        submit_survey(sc["registrations"][0]["id"], sc["volunteers"][0], rating=5)
        submit_survey(sc["registrations"][1]["id"], sc["volunteers"][1], rating=5)
        # Advance 100 days so those two surveys are older than the 90-day window
        set_clock("2026-11-09T00:00:00Z")
        submit_survey(sc["registrations"][2]["id"], sc["volunteers"][2], rating=1, would_repeat=False)

        partner = get_partner(sc["partner"]["id"])
        # (5 x 0.5 + 5 x 0.5 + 1 x 1.0) / (0.5 + 0.5 + 1.0) = 6.0 / 2.0 = 3.0
        assert partner["reputation_score"] == 3.0
        assert partner["survey_count"] == 3
        # 3.0 is not below the 2.50 suspend threshold: no transition
        assert partner["status"] == "ACTIVE"

    def test_reputation_suspend_reinstate_hysteresis(self, api, any_headers):
        """PRD §3.9: "Reputation has teeth, applied automatically on survey creation with a hysteresis band so partners do not flap between states: when `survey_count` is at least 3 and `reputation_score` falls below 2.50, the partner moves from `ACTIVE` to `SUSPENDED`, and that suspension cascades — the partner's projects in `PROPOSED` or `VETTED` move to `CANCELLED`, while `MATCHED`, `LOCKED`, and `COMPLETED` projects are untouched; when `reputation_score` is 3.00 or higher, the partner moves from `SUSPENDED` back to `ACTIVE`. Scores in the band between 2.50 and 3.00 trigger no transition."
        PRD §3.1: "A partner in `SUSPENDED` status cannot source new work — proposing, and likewise vetting or matching, is rejected with `ERR_NONPROFIT_SUSPENDED`."

        Design: Corner/calculations/reputation_suspend_reinstate_hysteresis
        """
        sc = setup_completed_event(
            event_name="Day 13", num_adults=6, budget_cents=500000
        )
        np_id = sc["partner"]["id"]
        # A second project left VETTED before the collapse
        future = create_project(np_id, "Future Garden")
        vet_project(future["id"])

        regs, vols = sc["registrations"], sc["volunteers"]
        submit_survey(regs[0]["id"], vols[0], rating=1, would_repeat=False)
        submit_survey(regs[1]["id"], vols[1], rating=2, would_repeat=False)
        submit_survey(regs[2]["id"], vols[2], rating=1, would_repeat=False)

        partner = get_partner(np_id)
        # round_half_up(4/3, 2) = 1.33 < 2.50 with survey_count 3: auto-suspend
        assert partner["reputation_score"] == 1.33
        assert partner["status"] == "SUSPENDED"
        # The suspension cascades VETTED projects to CANCELLED
        assert get_project(future["id"])["status"] == "CANCELLED"

        # While suspended, the partner cannot source new work
        blocked = api.create_service_project(
            {"nonprofit_id": np_id, "title": "Blocked Project", "min_volunteers": 1, "max_volunteers": 5},
            make_nonprofit_coordinator_headers(np_id),
        )
        validate_error(blocked, ApiErrorId.ERR_NONPROFIT_SUSPENDED)

        # Hysteresis: 14/5 = 2.80 sits in the band — no reinstatement yet
        submit_survey(regs[3]["id"], vols[3], rating=5)
        submit_survey(regs[4]["id"], vols[4], rating=5)
        partner = get_partner(np_id)
        assert partner["reputation_score"] == 2.80
        assert partner["status"] == "SUSPENDED"

        # The third 5 lifts the score to round_half_up(19/6, 2) = 3.17 >= 3.00
        submit_survey(regs[5]["id"], vols[5], rating=5)
        partner = get_partner(np_id)
        assert partner["reputation_score"] == 3.17
        assert partner["status"] == "ACTIVE"
