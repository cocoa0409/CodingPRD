"""Event registrations: event-state gating, capacity boundary, consent gate,
and duplicate/cancel rules (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_senior,
    coord,
    create_event,
    create_event_registration_payload,
    grant_consent,
    publish_event,
    register_senior,
    setup_campaign_with_school,
    validate_error,
    validate_paginated,
    validate_success,
)


def _senior_with_outreach(school, student_ref, full_name, dob):
    senior = add_senior(
        school, student_ref=student_ref, full_name=full_name, dob=dob
    )
    grant_consent(school, senior["id"], ["OUTREACH"])
    return senior


class TestRegistrationRequiresPublishedEvent:
    def test_registration_rejected_while_event_is_draft(self, api):
        """PRD §3.8: "Registration requires the event to be `PUBLISHED`" — a
        registration against a DRAFT event is refused with
        `ERR_EVENT_NOT_PUBLISHED`.

        Design: Difficulty/cross_entity_state_dependency/registration_requires_event_published
        """
        _campaign, school = setup_campaign_with_school()
        senior = _senior_with_outreach(school, "S1", "Ana Lee", "2009-03-04")
        event = create_event(school, title="E1")

        resp = api.create_event_registration(
            create_event_registration_payload(event["id"], senior["id"]),
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED)

    def test_registration_succeeds_after_publish(self, api):
        """PRD §3.8: "Registration requires the event to be `PUBLISHED`" — the
        same request succeeds once the event is published, and "A registration
        lives as `REGISTERED` until the coordinator cancels it".

        Design: Difficulty/cross_entity_state_dependency/registration_requires_event_published
        """
        _campaign, school = setup_campaign_with_school()
        senior = _senior_with_outreach(school, "S1", "Ana Lee", "2009-03-04")
        event = create_event(school, title="E1")
        publish_event(school, event["id"])

        registration = register_senior(school, event["id"], senior["id"])
        assert registration["status"] == "REGISTERED"
        assert registration["event_id"] == event["id"]
        assert registration["senior_record_id"] == senior["id"]


class TestRegistrationCapacityBoundary:
    def _setup(self, api):
        """PUBLISHED event with capacity 2 and three OUTREACH-consented
        seniors."""
        _campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1", capacity=2)
        publish_event(school, event["id"])
        seniors = [
            _senior_with_outreach(school, "S1", "A One", "2009-01-01"),
            _senior_with_outreach(school, "S2", "A Two", "2009-01-02"),
            _senior_with_outreach(school, "S3", "A Three", "2009-01-03"),
        ]
        return school, event, seniors

    def test_registration_filling_the_last_seat_succeeds(self, api):
        """PRD §3.8: "a registration arriving when the event's count of
        `REGISTERED` registrations already equals or exceeds `capacity` is
        refused with `ERR_EVENT_FULL` (a registration that takes the final open
        seat succeeds)."

        Design: Difficulty/boundary_precision_check/event_registration_exact_capacity_full
        """
        school, event, seniors = self._setup(api)
        reg1 = register_senior(school, event["id"], seniors[0]["id"])
        reg2 = register_senior(school, event["id"], seniors[1]["id"])
        assert reg1["status"] == "REGISTERED"
        assert reg2["status"] == "REGISTERED", (
            "count 1 < capacity 2 at arrival: the final seat must succeed"
        )

    def test_registration_beyond_capacity_rejected(self, api):
        """PRD §3.8: "a registration arriving when the event's count of
        `REGISTERED` registrations already equals or exceeds `capacity` is
        refused with `ERR_EVENT_FULL` (a registration that takes the final open
        seat succeeds)."

        Design: Difficulty/boundary_precision_check/event_registration_exact_capacity_full
        """
        school, event, seniors = self._setup(api)
        register_senior(school, event["id"], seniors[0]["id"])
        register_senior(school, event["id"], seniors[1]["id"])

        resp = api.create_event_registration(
            create_event_registration_payload(event["id"], seniors[2]["id"]),
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_FULL)

        resp = api.list_event_registrations(
            coord(school), params={"event_id": event["id"], "status": "REGISTERED"}
        )
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, "the rejected registration must not persist"


class TestRegistrationConsentGate:
    def test_registration_without_outreach_consent_rejected(self, api):
        """PRD §3.8: registration requires "a `GRANTED` consent carrying the
        `OUTREACH` scope for that senior (`ERR_CONSENT_REQUIRED`)".
        PRD §2.6: "Lacking the required scope is a business refusal surfaced as
        `ERR_CONSENT_REQUIRED`, not an authentication failure."

        Design: Corner/validations/registration_requires_outreach_consent
        """
        _campaign, school = setup_campaign_with_school()
        senior = add_senior(school)  # no consent at all
        event = create_event(school, title="E1")
        publish_event(school, event["id"])

        resp = api.create_event_registration(
            create_event_registration_payload(event["id"], senior["id"]),
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)
        assert resp.status_code == 403

        resp = api.list_event_registrations(
            coord(school), params={"event_id": event["id"]}
        )
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, "no registration may persist"


class TestRegistrationDuplicateAndCancel:
    def test_duplicate_double_cancel_and_reregister(self, api):
        """PRD §3.8: registration requires "no existing `REGISTERED`
        registration for the same event and senior (`ERR_DUPLICATE_REGISTRATION`)".
        PRD §3.8: "A registration lives as `REGISTERED` until the coordinator
        cancels it (any other state: `ERR_REGISTRATION_NOT_ACTIVE`) or a
        cascade — event cancel, unpublish, consent loss, or campaign close —
        cancels it first; `CANCELLED` is terminal."

        Design: Corner/state_machines/registration_constraints_duplicate_and_double_cancel
        """
        _campaign, school = setup_campaign_with_school()
        senior = _senior_with_outreach(school, "S1", "A One", "2009-01-01")
        event = create_event(school, title="E1")
        publish_event(school, event["id"])

        registration = register_senior(school, event["id"], senior["id"])

        # A second REGISTERED registration for the same (event, senior).
        resp = api.create_event_registration(
            create_event_registration_payload(event["id"], senior["id"]),
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

        resp = api.cancel_event_registration(registration["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CANCELLED"

        # Cancelling a CANCELLED registration is rejected.
        resp = api.cancel_event_registration(registration["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)

        # Only REGISTERED rows block: re-registration after cancel succeeds.
        resp = api.create_event_registration(
            create_event_registration_payload(event["id"], senior["id"]),
            coord(school),
        )
        assert validate_success(resp, 201)["status"] == "REGISTERED"
