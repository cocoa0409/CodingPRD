"""Validation-priority conflicts and temporal-window boundaries: which error wins
when two checks fail, the closed opposition window, and the premature maintenance
filing.

Sources: Difficulty/priority_pair_validation_conflict,
Difficulty/resource_temporal_overlap.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    setup_examined_application,
    setup_published_application,
    setup_registered_application,
    setup_base_parties,
    create_draft_application,
    add_item,
    set_clock,
    examiner_headers,
)
from test_helpers.factories import create_ttab_proceeding_payload, create_maintenance_filing_payload


class TestStateBeatsBusinessSafetyOnFile:
    """Filing an already-FILED application whose attorney was also suspended
    violates both state (priority 5) and attorney-active (priority 8); the state
    error ERR_INVALID_STATE wins."""

    def _setup(self):
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="DOUBLE", filing_basis="USE", filing_tier="TEAS_STANDARD")
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers)
        validate_success(api_client.file_application(app["id"], att_headers), 200)
        # Suspend the attorney AFTER filing.
        validate_success(api_client.suspend_attorney(
            base["attorney"]["id"], examiner_headers()), 200)
        base["application"] = app
        return base

    def test_refile_filed_app_with_suspended_attorney_returns_invalid_state(self, api):
        """PRD §3.8: "Fifth, state: the target resource must be in a state from
        which the requested transition is permitted, else ERR_INVALID_STATE."
        PRD §3.8: "Only after all of these do the operation-specific business checks
        of §3.2 through §3.7 run."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_file
        """
        base = self._setup()
        res = api.file_application(base["application"]["id"], base["att_headers"])
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_error_preempts_attorney_not_active(self, api):
        """PRD §3.8: "Fifth, state: the target resource must be in a state from
        which the requested transition is permitted, else ERR_INVALID_STATE."
        PRD §3.8: "Only after all of these do the operation-specific business checks
        of §3.2 through §3.7 run."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_file
        """
        base = self._setup()
        res = api.file_application(base["application"]["id"], base["att_headers"])
        # The losing branch (ERR_ATTORNEY_NOT_ACTIVE) must NOT be returned.
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE"


class TestTargetInvalidBeatsWindowClosedOnOpposition:
    """An OPPOSITION whose target is still UNDER_EXAMINATION (never PUBLISHED)
    violates both target-validity (priority 12) and window (priority 13); the
    target-validity error ERR_PROCEEDING_TARGET_INVALID wins."""

    def _setup(self):
        base = setup_examined_application(
            clock="2026-06-01T00:00:00Z", class_numbers=(9,), filing_basis="USE", mark_text="UNPUB")
        att_headers = base["att_headers"]
        rival = validate_success(api_client.create_applicant(
            {"legal_name": "Rival Co", "entity_type": "CORPORATION", "country_code": "US"},
            att_headers), 201)
        base["rival"] = rival
        return base

    def test_opposition_on_unpublished_app_returns_target_invalid(self, api):
        """PRD §3.6: "An opposition requires a non-null target_application_id whose
        application is currently PUBLISHED ... A target of the wrong kind or in a
        non-challengeable state is refused with ERR_PROCEEDING_TARGET_INVALID."

        Design: Difficulty/priority_pair_validation_conflict/target_invalid_beats_window_closed_on_opposition
        """
        base = self._setup()
        res = api.create_ttab_proceeding(
            create_ttab_proceeding_payload(
                "OPPOSITION", base["rival"]["id"],
                target_application_id=base["application"]["id"]),
            base["att_headers"])
        validate_error(res, "ERR_PROCEEDING_TARGET_INVALID")

    def test_target_invalid_preempts_window_closed(self, api):
        """PRD §3.6: "A target of the wrong kind or in a non-challengeable state is
        refused with ERR_PROCEEDING_TARGET_INVALID."

        Design: Difficulty/priority_pair_validation_conflict/target_invalid_beats_window_closed_on_opposition
        """
        base = self._setup()
        res = api.create_ttab_proceeding(
            create_ttab_proceeding_payload(
                "OPPOSITION", base["rival"]["id"],
                target_application_id=base["application"]["id"]),
            base["att_headers"])
        assert res.status_code == 422
        assert res.json()["data"]["error_id"] == "ERR_PROCEEDING_TARGET_INVALID"


class TestOppositionWindowClosed:
    """The opposition interval is [published_at, published_at + 30 days]; filing
    after the window closes is rejected ERR_OPPOSITION_WINDOW_CLOSED."""

    def test_opposition_after_window_closes_rejected(self, api):
        """PRD §3.6: "An opposition additionally must be filed while the current
        instant is on or before the target application's published_at plus the
        30-day opposition window; an opposition filed after that window has closed is
        refused with ERR_OPPOSITION_WINDOW_CLOSED."

        Design: Difficulty/resource_temporal_overlap/opposition_after_publication_window_closed
        """
        base = setup_published_application(
            clock="2026-02-01T00:00:00Z", class_numbers=(9,), filing_basis="USE", mark_text="WINDOW")
        att_headers = base["att_headers"]
        rival = validate_success(api.create_applicant(
            {"legal_name": "Rival Co", "entity_type": "CORPORATION", "country_code": "US"},
            att_headers), 201)
        # Published 2026-02-01, window closes 2026-03-03; file at 2026-03-04.
        set_clock("2026-03-04T00:00:00Z")
        res = api.create_ttab_proceeding(
            create_ttab_proceeding_payload(
                "OPPOSITION", rival["id"], target_application_id=base["application"]["id"]),
            att_headers)
        validate_error(res, "ERR_OPPOSITION_WINDOW_CLOSED")

    def test_opposition_on_window_close_day_accepted(self, api):
        """PRD §3.6: "An opposition additionally must be filed while the current
        instant is on or before the target application's published_at plus the
        30-day opposition window"

        Design: Difficulty/resource_temporal_overlap/opposition_after_publication_window_closed
        """
        base = setup_published_application(
            clock="2026-02-01T00:00:00Z", class_numbers=(9,), filing_basis="USE", mark_text="WINDOW2")
        att_headers = base["att_headers"]
        rival = validate_success(api.create_applicant(
            {"legal_name": "Rival Co", "entity_type": "CORPORATION", "country_code": "US"},
            att_headers), 201)
        # On-or-before the inclusive close (2026-03-03) is still permitted.
        set_clock("2026-03-03T00:00:00Z")
        res = api.create_ttab_proceeding(
            create_ttab_proceeding_payload(
                "OPPOSITION", rival["id"], target_application_id=base["application"]["id"]),
            att_headers)
        proc = validate_success(res, 201)
        assert proc["proceeding_type"] == "OPPOSITION"


class TestMaintenanceFilingPremature:
    """A §8 filing before the maintenance window opens (next_maintenance_due_at -
    1 year) is premature and rejected ERR_MAINTENANCE_WINDOW_NOT_OPEN."""

    def test_maintenance_filing_before_window_opens_rejected(self, api):
        """PRD §3.5: "Every window opens one year before it closes, so a
        registration's current window opens at next_maintenance_due_at minus one
        year. A filing submitted before that opening instant is premature and refused
        with ERR_MAINTENANCE_WINDOW_NOT_OPEN."

        Design: Difficulty/resource_temporal_overlap/maintenance_filing_before_window_opens_premature
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9,), mark_text="PREMATURE")
        reg = base["registration"]
        # Registered 2026-01-01, first window opens 2031-01-01; file at 2026-06-01.
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_maintenance_filing(
            create_maintenance_filing_payload(
                reg["id"], "SECTION_8", reg["version"]),
            base["att_headers"])
        validate_error(res, "ERR_MAINTENANCE_WINDOW_NOT_OPEN")

    def test_premature_maintenance_filing_not_created(self, api):
        """PRD §3.5: "A filing submitted before that opening instant is premature and
        refused with ERR_MAINTENANCE_WINDOW_NOT_OPEN."

        Design: Difficulty/resource_temporal_overlap/maintenance_filing_before_window_opens_premature
        """
        base = setup_registered_application(
            clock="2026-01-01T00:00:00Z", class_numbers=(9,), mark_text="PREMATURE2")
        reg = base["registration"]
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_maintenance_filing(
            create_maintenance_filing_payload(reg["id"], "SECTION_8", reg["version"]),
            base["att_headers"])
        assert res.status_code == 422
        # No filing should be listed for the registration.
        data, meta = validate_paginated(api.list_registration_maintenance_filings(
            reg["id"], examiner_headers()))
        assert meta["total_count"] == 0
