"""Aid-status projection, deadline classification, and the senior's parallel
match/fafsa axes (PRD §2.4, §3.4, §3.5)."""
from test_helpers import (
    ADMIN,
    IMPORTER,
    REVIEWER,
    add_aid_record,
    add_report_senior,
    assert_aid_status_event,
    create_campaign,
    create_matched_senior,
    create_specialist,
    create_status_event_payload,
    fresh_senior,
    setup_campaign_with_school,
    validate_paginated,
    validate_success,
)


class TestAidStatusEventImmutability:
    def test_status_event_is_append_only_without_version(self, api, importer_headers):
        """PRD §2.4: "The single exception is the `AidStatusEvent` resource,
        which is an immutable append-only log entry: it carries `id` and
        `created_at` only, and both `updated_at` and `version` are absent from
        it."
        PRD §3.3: "Import creates the record's first status event from those
        two values, and the projection rules of §3.4 apply from that very first
        event."

        Design: Corner/entities/aid_status_event_immutable_no_version
        """
        campaign = create_campaign()
        aid = add_aid_record(
            campaign,
            external_ref="EXT1",
            full_name="Ana Lee",
            dob="2009-03-04",
            school_code="SC01",
            district_code="D01",
            initial_status="SUBMITTED",
            effective_date="2027-01-10",
        )
        resp = api.list_status_events(aid["id"], importer_headers)
        events, meta = validate_paginated(resp)
        assert meta["total_count"] == 1 and len(events) == 1
        event = events[0]
        assert_aid_status_event(event)  # enforces: no updated_at, no version
        assert event["fafsa_status"] == "SUBMITTED"
        assert str(event["effective_date"]).startswith("2027-01-10")


class TestProjectionOrdering:
    def test_stale_event_stored_without_moving_projection_and_tie_breaks(
        self, api, importer_headers
    ):
        """PRD §3.4: "When a new status event arrives, it is always stored, but
        it moves the projection only when its `effective_date` is on or after
        the record's current `last_effective_date` — an older-dated event is
        retained in the log yet leaves the projection untouched. The winning
        event is the one with the greatest `effective_date`, with ties broken
        in favor of the later `created_at`".

        Design: Corner/calculations/stale_and_tiebreaker_snapshot_projection
        """
        campaign = create_campaign()
        aid = add_aid_record(
            campaign,
            external_ref="EXT1",
            initial_status="SUBMITTED",
            effective_date="2027-01-10",
        )
        api.append_status_event(
            aid["id"],
            create_status_event_payload(
                fafsa_status="COMPLETE", effective_date="2027-02-01"
            ),
            importer_headers,
        )

        # Stale event: effective_date older than the current winner.
        api.append_status_event(
            aid["id"],
            create_status_event_payload(
                fafsa_status="STARTED", effective_date="2027-01-20"
            ),
            importer_headers,
        )
        resp = api.get_aid_record(aid["id"], importer_headers)
        aid = validate_success(resp, 200)
        assert aid["current_status"] == "COMPLETE", (
            f"a stale event must not move the projection, got "
            f"{aid['current_status']}"
        )
        assert str(aid["last_effective_date"]).startswith("2027-02-01")

        # Tie on effective_date: the later-created event wins the projection.
        api.append_status_event(
            aid["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-01"
            ),
            importer_headers,
        )
        resp = api.get_aid_record(aid["id"], importer_headers)
        aid = validate_success(resp, 200)
        assert aid["current_status"] == "VERIFICATION_SELECTED", (
            f"the later-created tie event must win, got {aid['current_status']}"
        )

        # All four events retained in the log.
        resp = api.list_status_events(aid["id"], importer_headers)
        _events, meta = validate_paginated(resp)
        assert meta["total_count"] == 4


class TestDeadlineClassification:
    def test_inclusive_day_granularity_boundaries(self, api, admin_headers):
        """PRD §3.4: "`null` submission means `NOT_SUBMITTED`; a submission on
        or before the campaign's `state_grant_deadline` is `ON_TRACK_STATE`; a
        submission after the state deadline but on or before the
        `federal_deadline` is `STATE_MISSED_FEDERAL_OPEN`; anything later is
        `LATE`."
        PRD §3.4: "The `submitted_at` of a senior is the earliest
        `effective_date` among the linked aid record's events whose status is
        `SUBMITTED`, `VERIFICATION_SELECTED`, or `COMPLETE`; it stays `null`
        when the senior has no confirmed link or no such event."

        Design: Corner/calculations/deadline_classification_inclusive_boundaries
        """
        # state_grant_deadline 2027-04-15, federal_deadline 2028-06-30.
        campaign, school = setup_campaign_with_school()
        specs = [
            ("S1", "A One", "2009-01-01", "SUBMITTED", "2027-04-15", "ON_TRACK_STATE"),
            ("S2", "A Two", "2009-01-02", "SUBMITTED", "2027-04-16", "STATE_MISSED_FEDERAL_OPEN"),
            ("S3", "A Three", "2009-01-03", "SUBMITTED", "2028-07-01", "LATE"),
            ("S4", "A Four", "2009-01-04", "STARTED", "2027-01-10", "NOT_SUBMITTED"),
        ]
        senior_ids = []
        for student_ref, name, dob, status, eff, _expected in specs:
            senior, _aid, _link = add_report_senior(
                campaign,
                school,
                student_ref=student_ref,
                full_name=name,
                dob=dob,
                aid_status=status,
                aid_effective_date=eff,
                scopes=["STATUS_DETAIL"],
            )
            senior_ids.append((senior["id"], student_ref))

        for (senior_id, student_ref), (_r, _n, _d, _s, _e, expected) in zip(
            senior_ids, specs
        ):
            senior = fresh_senior(senior_id)
            assert senior["deadline_classification"] == expected, (
                f"{student_ref}: expected {expected}, got "
                f"{senior['deadline_classification']}"
            )
        s1 = fresh_senior(senior_ids[0][0])
        assert s1["submitted_at"] is not None, (
            "a submission exactly on the state deadline is a real submission "
            "date (inclusive upper bound)"
        )
        s4 = fresh_senior(senior_ids[3][0])
        assert s4["submitted_at"] is None, (
            "a senior whose aid record only ever STARTED has no qualifying "
            "event: submitted_at must be null"
        )


class TestSeniorParallelAxes:
    def _setup(self, api):
        """Senior matched via a SUGGESTED link (score 0.85: school differs);
        aid record initially SUBMITTED; STATUS_DETAIL consent in place so the
        status quartet is readable."""
        campaign, school = setup_campaign_with_school()
        specialist = create_specialist(campaign)
        senior, aid, link, _consent = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_school_code="SC99",
            aid_status="SUBMITTED",
            aid_effective_date="2027-01-10",
            consent_scopes=["STATUS_DETAIL"],
            consent_before_link=True,
        )
        assert link["status"] == "SUGGESTED"
        return campaign, school, specialist, senior, aid, link

    def test_confirm_applies_match_axis_and_initializes_fafsa_axis(self, api):
        """PRD §3.5: "the reviewer may confirm it, moving the link from
        `SUGGESTED` to `CONFIRMED` and firing the identical matched cascade"
        whose effects include "`fafsa_status` initializes from the linked aid
        record's `current_status`".
        PRD §3.4: "Whenever the winning event changes `current_status` on an
        aid record that a `CONFIRMED` or `AUTO_CONFIRMED` match link points at,
        the linked senior's `fafsa_status` follows the same value".

        Design: Difficulty/non_linear_state_machine/senior_record_parallel_match_and_fafsa_axes
        """
        _campaign, _school, _spec, senior, aid, link = self._setup(api)

        resp = api.confirm_match_link(link["id"], REVIEWER)
        confirmed = validate_success(resp, 200)
        assert confirmed["status"] == "CONFIRMED"

        senior = fresh_senior(senior["id"])
        assert senior["match_status"] == "MATCHED"
        assert senior["fafsa_status"] == "SUBMITTED"

        # The fafsa axis moves on its own when the agency stream advances.
        api.append_status_event(
            aid["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-01"
            ),
            IMPORTER,
        )
        senior = fresh_senior(senior["id"])
        assert senior["fafsa_status"] == "VERIFICATION_SELECTED"
        assert senior["match_status"] == "MATCHED", (
            "the fafsa axis moving must not disturb the match axis"
        )

    def test_invalidate_reverts_match_axis_but_retains_fafsa_status(self, api):
        """PRD §3.4: "Once a link is invalidated, the senior's last known
        `fafsa_status` is retained as history, but later agency events no
        longer propagate."
        PRD §3.4: "Whenever a senior's status becomes `VERIFICATION_SELECTED` —
        whether arriving from `NO_RECORD`, `STARTED`, or `SUBMITTED` — the
        verification cascade fires: unless that senior already has a
        non-terminal verification case, the system opens a support case of type
        `VERIFICATION_FOLLOWUP` and runs the specialist selector (§3.8)".

        Design: Difficulty/non_linear_state_machine/senior_record_parallel_match_and_fafsa_axes
        """
        _campaign, _school, specialist, senior, aid, link = self._setup(api)
        api.confirm_match_link(link["id"], REVIEWER)
        api.append_status_event(
            aid["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-01"
            ),
            IMPORTER,
        )

        resp = api.invalidate_match_link(link["id"], REVIEWER)
        invalidated = validate_success(resp, 200)
        assert invalidated["status"] == "INVALIDATED"

        senior = fresh_senior(senior["id"])
        assert senior["match_status"] == "UNMATCHED"
        assert senior["current_match_link_id"] is None
        assert senior["fafsa_status"] == "VERIFICATION_SELECTED", (
            "the match-axis revert must not touch the retained fafsa status"
        )

        # The verification cascade fired when the axis reached
        # VERIFICATION_SELECTED: one auto-created follow-up case exists.
        resp = api.list_support_cases(
            ADMIN, params={"senior_record_id": senior["id"]}
        )
        cases, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert cases[0]["case_type"] == "VERIFICATION_FOLLOWUP"
        assert cases[0]["assigned_specialist_id"] == specialist["id"]
