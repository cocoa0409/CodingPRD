"""Venues, emergency action plan lifecycle, and venue-level OCC (PRD §2.7,
§3.2)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_eap_for,
    create_venue,
    director_headers,
    drive_eap_to_approved,
    make_director,
    make_trainer,
    trainer_headers,
    validate_error,
    validate_success,
)


class TestEventSchedulingGuards:

    def test_event_at_inactive_venue_rejected(self):
        """PRD §3.2: "`is_active` defaults to true; an inactive venue rejects
        new events with `ERR_VENUE_INACTIVE`."

        Design: Corner/errors/event_at_inactive_venue_rejected
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Closed Pool", venue_type="INDOOR",
                             surface="POOL", is_active=False)
        resp = api_client.create_event(
            {
                "event_name": "Swim Practice",
                "sport": "SWIMMING",
                "team_level": "VARSITY",
                "event_type": "PRACTICE",
                "venue_id": venue["id"],
                "scheduled_start": "2026-08-02T14:00:00Z",
                "scheduled_end": "2026-08-02T15:00:00Z",
                "expected_attendance": 0,
            },
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_VENUE_INACTIVE)

    def test_event_end_must_be_strictly_after_start(self):
        """PRD §3.3: "The end must be strictly after the start — a non-later
        end is rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/event_invalid_date_range_rejected
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Gym", venue_type="INDOOR",
                             surface="COURT")
        resp = api_client.create_event(
            {
                "event_name": "Zero-Length",
                "sport": "VOLLEYBALL",
                "team_level": "JV",
                "event_type": "PRACTICE",
                "venue_id": venue["id"],
                "scheduled_start": "2026-08-02T14:00:00Z",
                "scheduled_end": "2026-08-02T14:00:00Z",
                "expected_attendance": 0,
            },
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_venue_activity_status_empty_set_defaults(self):
        """PRD §3.4: "a venue with no heat readings at all is treated as
        `NORMAL`".
        PRD §3.4: "Anyone with read access can check a venue's environmental
        gate view, which reports the `venue_id`, the `current_heat_tier`
        (computed on the district table at venue level), whether a
        `lightning_hold_active` flag is set, and the `lightning_hold_until`
        instant."

        Design: Corner/endpoints/venue_activity_status_defaults
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Empty Field")
        data = validate_success(api_client.get_venue_activity_status(
            venue["id"], trainer_headers(tr1)))
        assert data["current_heat_tier"] == "NORMAL"
        assert data["lightning_hold_active"] is False


class TestEapRevisionLoop:
    """Difficulty instance eap_revision_loop_draft_pending (two tests)."""

    def _setup_pending_eap(self):
        tr1 = make_trainer()
        ad = make_director()
        venue = create_venue(venue_name="Fieldhouse", venue_type="INDOOR",
                             surface="COURT")
        eap = create_eap_for(venue["id"], tr1, version_label="v1")
        return tr1, ad, venue, eap

    def test_reject_loops_pending_back_to_draft(self):
        """PRD §3.2: "a rejection sends it back from `PENDING_APPROVAL` to
        `DRAFT` for revision — a loop that may repeat as many times as review
        requires."

        Design: Difficulty/non_linear_state_machine/eap_revision_loop_draft_pending
        """
        tr1, ad, venue, eap = self._setup_pending_eap()
        assert eap["status"] == "DRAFT"

        submitted = validate_success(api_client.submit_eap(
            eap["id"], trainer_headers(tr1)))
        assert submitted["status"] == "PENDING_APPROVAL"

        rejected = validate_success(api_client.reject_eap(
            eap["id"], director_headers(ad)))
        assert rejected["status"] == "DRAFT", \
            "reject is the cycle edge back to DRAFT"

        resubmitted = validate_success(api_client.submit_eap(
            eap["id"], trainer_headers(tr1)))
        assert resubmitted["status"] == "PENDING_APPROVAL"

    def test_full_loop_to_active_bumps_venue_version_once(self):
        """PRD §3.2: "On success the plan becomes `ACTIVE`, the venue's
        previously `ACTIVE` plan (if any) is moved to `SUPERSEDED` as a
        direct consequence of the activation, the venue's `active_eap_id` is
        re-pointed at the newly active plan, and `Venue.version` increments
        by one."

        Design: Difficulty/non_linear_state_machine/eap_revision_loop_draft_pending
        """
        tr1, ad, venue, eap = self._setup_pending_eap()
        created_version = venue["version"]
        validate_success(api_client.submit_eap(eap["id"],
                                               trainer_headers(tr1)))
        validate_success(api_client.reject_eap(eap["id"],
                                               director_headers(ad)))
        validate_success(api_client.submit_eap(eap["id"],
                                               trainer_headers(tr1)))
        approved = validate_success(api_client.approve_eap(
            eap["id"], director_headers(ad)))
        assert approved["status"] == "APPROVED"

        activated = validate_success(api_client.activate_eap(
            eap["id"], {"expected_venue_version": created_version},
            director_headers(ad)))
        assert activated["status"] == "ACTIVE"

        venue_after = validate_success(api_client.get_venue(venue["id"],
                                                            ADMIN))
        assert venue_after["active_eap_id"] == eap["id"]
        assert venue_after["version"] == created_version + 1, (
            f"activation bumps Venue.version exactly once: "
            f"{created_version} -> {venue_after['version']}")


class TestEapActivationSupersede:

    def _setup_two_approved_plans(self):
        tr1 = make_trainer()
        ad = make_director()
        venue = create_venue()
        eap1 = create_eap_for(venue["id"], tr1, version_label="v1")
        drive_eap_to_approved(eap1["id"], tr1, ad)
        venue_v1 = validate_success(api_client.get_venue(venue["id"], ADMIN))
        activated = validate_success(api_client.activate_eap(
            eap1["id"], {"expected_venue_version": venue_v1["version"]},
            director_headers(ad)))
        assert activated["status"] == "ACTIVE"
        eap2 = create_eap_for(venue["id"], tr1, version_label="v2",
                              supersedes_eap_id=eap1["id"],
                              evacuation_route="Gate B")
        drive_eap_to_approved(eap2["id"], tr1, ad)
        venue_now = validate_success(api_client.get_venue(venue["id"], ADMIN))
        return tr1, ad, venue, eap1, eap2, venue_now

    def test_second_activation_supersedes_prior_plan(self):
        """PRD §3.2: "On success the plan becomes `ACTIVE`, the venue's
        previously `ACTIVE` plan (if any) is moved to `SUPERSEDED` as a
        direct consequence of the activation, the venue's `active_eap_id` is
        re-pointed at the newly active plan, and `Venue.version` increments
        by one."
        PRD §3.2: "`SUPERSEDED` is terminal; supersession is otherwise
        automatic — a plan never leaves `ACTIVE` except by being superseded."

        Design: Corner/state_machines/eap_activation_supersedes_prior_version
        """
        tr1, ad, venue, eap1, eap2, venue_now = \
            self._setup_two_approved_plans()
        activated = validate_success(api_client.activate_eap(
            eap2["id"], {"expected_venue_version": venue_now["version"]},
            director_headers(ad)))
        assert activated["status"] == "ACTIVE"

        eap1_after = validate_success(api_client.get_eap(eap1["id"], ADMIN))
        assert eap1_after["status"] == "SUPERSEDED"

        venue_after = validate_success(api_client.get_venue(venue["id"],
                                                            ADMIN))
        assert venue_after["active_eap_id"] == eap2["id"]
        assert venue_after["version"] == venue_now["version"] + 1

        # SUPERSEDED is terminal: submit on it is a state rejection.
        resp = api_client.submit_eap(eap1["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_stale_venue_version_rejected_then_retry_succeeds(self):
        """PRD §2.7: "the request must carry `expected_venue_version`
        matching the venue's current `version`, and a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_eap_activate
        """
        tr1, ad, venue, eap1, eap2, venue_now = \
            self._setup_two_approved_plans()
        stale_version = venue_now["version"] - 1  # pre-EAP1-activation value
        resp = api_client.activate_eap(
            eap2["id"], {"expected_venue_version": stale_version},
            director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        reread = validate_success(api_client.get_venue(venue["id"], ADMIN))
        assert reread["version"] == venue_now["version"]

        data = validate_success(api_client.activate_eap(
            eap2["id"], {"expected_venue_version": reread["version"]},
            director_headers(ad)))
        assert data["status"] == "ACTIVE"
