"""Optimistic concurrency and governance checkpoint sweeps."""
from test_helpers import (
    ApiErrorId,
    add_director,
    add_directors,
    add_membership,
    create_corporation,
    create_draft_bylaws,
    get_success_data,
    schedule_meeting,
    schedule_noticed_meeting,
    set_clock,
    setup_active_committee,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    validate_error,
    validate_paginated,
    validate_success,
    SECRETARY,
)
from test_helpers import api_client


class TestStaleCorporationVersionOnAdopt:
    def test_stale_corporation_version_on_adopt_rejected(self, api):
        """PRD §2.7: "Adopting a bylaws supersedes the corporation's currently
        adopted rulebook, so an adoption request must carry
        `expected_corporation_version` equal to the corporation's current
        `version` as the client last observed it. If the corporation's version
        has advanced beyond the supplied value — for example because an
        earlier adoption already repointed the rulebook — the request is
        rejected as stale with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_corporation_version_on_adopt_rejected
        """
        corp = create_corporation(name="Corp OCC1")
        b1 = create_draft_bylaws(corp["id"])
        b2 = create_draft_bylaws(
            corp["id"],
            notice_days_regular=12,
            notice_days_special=4,
            package_lead_days=6,
            quorum_percent=50,
            quorum_fixed_count=2,
            consent_window_days=14,
            consent_unanimity_required=False,
            minute_retention_years=7,
            rotation_max_years=4,
            board_seat_count=9,
        )
        # First adoption succeeds and bumps corporation.version to 2.
        api.adopt_bylaws(b1["id"], {"expected_corporation_version": corp["version"]}, SECRETARY)
        # Second adoption carrying the now-stale version fails.
        resp = api.adopt_bylaws(
            b2["id"], {"expected_corporation_version": corp["version"]}, SECRETARY
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        b1_after = get_success_data(api.get_bylaws(b1["id"], SECRETARY))
        b2_after = get_success_data(api.get_bylaws(b2["id"], SECRETARY))
        corp_after = get_success_data(api.get_corporation(corp["id"], SECRETARY))
        assert b1_after["status"] == "ADOPTED"
        assert b2_after["status"] == "DRAFT"
        assert corp_after["version"] == 2
        assert corp_after["current_bylaws_id"] == b1["id"]


class TestStaleMeetingVersionOnReschedule:
    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp OCC2")
        d1 = directors[0]
        m = schedule_meeting(corp["id"], d1["id"])
        return corp, d1, m

    def test_stale_meeting_version_rejected_on_reschedule(self, api):
        """PRD §2.7: "Rescheduling a meeting rewrites its calendar window and
        deletes notices already issued, so a reschedule request must carry
        `expected_meeting_version` equal to the meeting's current `version`
        as the client last observed it. If the meeting's version has advanced
        beyond the supplied value, the request is rejected as stale with
        `ERR_STALE_MEETING_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_meeting_version_on_reschedule_rejected
        """
        _corp, _d1, m = self._setup(api)
        mv1 = m["version"]
        # send_notices mutates the meeting, bumping its version.
        api.send_notices(m["id"], SECRETARY)
        resp = api.reschedule_meeting(
            m["id"],
            {
                "scheduled_start": "2026-07-01T10:00:00Z",
                "duration_minutes": 90,
                "expected_meeting_version": mv1,
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEETING_VERSION)
        assert resp.status_code == 412

    def test_fresh_version_reschedule_succeeds_and_deletes_notices(self, api):
        """PRD §3.4 (reschedule): "A successful reschedule replaces the
        window, deletes every MeetingNotice already issued for the meeting —
        notice must be sent afresh against the new date — returns the meeting
        to `SCHEDULED`, and increments the meeting's `version`."

        Design: Corner/cross_cutting_layers/stale_meeting_version_on_reschedule_rejected
        """
        _corp, _d1, m = self._setup(api)
        api.send_notices(m["id"], SECRETARY)
        fresh = get_success_data(api.get_meeting(m["id"], SECRETARY))
        resp = api.reschedule_meeting(
            m["id"],
            {
                "scheduled_start": "2026-07-01T10:00:00Z",
                "duration_minutes": 90,
                "expected_meeting_version": fresh["version"],
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_start"].startswith("2026-07-01T10:00:00")
        assert data["duration_minutes"] == 90
        # Issued notices deleted.
        notices = api.list_meeting_notices(SECRETARY, params={"meeting_id": m["id"]})
        _rows, meta = validate_paginated(notices)
        assert meta["total_count"] == 0


class TestCheckpointExpiresDirectorTerms:
    def test_checkpoint_expires_director_terms_cascade(self, api):
        """PRD §3.9: "It expires every `ACTIVE` director whose `term_end` has
        passed, with the full resignation-style cascade of §3.2 recorded as
        `DIRECTOR_TERM_EXPIRED`."

        Design: Corner/cross_cutting_layers/checkpoint_expires_director_terms_cascade
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp OPS1")
        # D1's term ends 2026-06-01; D2's term runs to 2029.
        d1 = add_director(
            corp["id"], "D1", "d1@x.com",
            term_start="2025-01-01T00:00:00Z", term_end="2026-06-01T00:00:00Z",
        )
        d2 = add_director(corp["id"], "D2", "d2@x.com")
        cm = setup_active_committee(corp["id"], name="C", committee_type="SPECIAL", quorum_fixed_count=1)
        mb1 = add_membership(
            cm["id"], d1["id"], committee_role="MEMBER",
            term_start="2025-02-01T00:00:00Z", term_end="2026-06-01T00:00:00Z",
        )
        set_clock("2026-06-02T00:00:00Z")
        resp = api.run_checkpoint(corp["id"], SECRETARY)
        data = validate_success(resp, expected_status=200)
        expired = data.get("expired_director_ids", [])
        assert d1["id"] in expired
        assert d2["id"] not in expired
        d1_after = get_success_data(api.get_director(d1["id"], SECRETARY))
        d2_after = get_success_data(api.get_director(d2["id"], SECRETARY))
        mb1_after = get_success_data(api.get_committee_membership(mb1["id"], SECRETARY))
        corp_after = get_success_data(api.get_corporation(corp["id"], SECRETARY))
        assert d1_after["status"] == "TERM_EXPIRED"
        assert d2_after["status"] == "ACTIVE"
        assert mb1_after["status"] == "ENDED"
        assert mb1_after["ended_reason"] == "DIRECTOR_TERM_EXPIRED"
        assert corp_after["active_director_count"] == 1
