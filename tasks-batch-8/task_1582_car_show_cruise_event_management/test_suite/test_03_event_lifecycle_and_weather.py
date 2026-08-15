"""Event lifecycle transitions, weather posture axis, and publish gating."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_event_payload, create_class_payload, create_zone_payload,
    create_event, create_event_with_class_and_zone, create_published_event,
    create_open_event, create_registrant_with_vehicle, create_registration,
    assert_event,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestPublishGate:
    def test_event_publish_twice_returns_409(self, api):
        """PRD §3.1: "Publishing is the show's first real gate, moving the event
        `DRAFT` → `PUBLISHED`, and it enforces four preconditions: the event is in
        `DRAFT`".

        Design: Corner/state_machines/event_publish_twice_returns_409
        """
        ev, cls, zone = create_published_event()
        resp = api.publish_event(ev["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE)
        after = validate_success(api.get_event(ev["id"], ORG))
        assert after["lifecycle_status"] == "PUBLISHED"

    def test_publish_without_insurance_rejected(self, api):
        """PRD §3.1: "`liability_policy_number` is non-empty, else
        `ERR_INSURANCE_POLICY_MISSING`".

        Design: Corner/validations/publish_without_insurance_rejected
        """
        payload = create_event_payload()
        del payload["liability_policy_number"]
        ev = get_success_data(api.create_event(payload, ORG))
        get_success_data(api.create_class(ev["id"], create_class_payload(), ORG))
        get_success_data(api.create_zone(ev["id"], create_zone_payload(), ORG))
        resp = api.publish_event(ev["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_POLICY_MISSING)
        # Patching the policy in then allows publish.
        get_success_data(api.update_event(ev["id"], {"liability_policy_number": "POL-99"}, ORG))
        published = validate_success(api.publish_event(ev["id"], ORG))
        assert published["lifecycle_status"] == "PUBLISHED"


class TestWeatherAxis:
    def test_weather_cycle_leaves_lifecycle_untouched(self, api):
        """PRD §2.4: "Its `weather_posture` moves independently among `NORMAL`,
        `WATCH`, `POSTPONED`, and `CANCELLED`." PRD §2.4: "The three dimensions
        are independent: locking registration does not touch the weather posture,
        and suspending the sound permit does not advance the lifecycle."

        Design: Difficulty/non_linear_state_machine/event_parallel_lifecycle_weather_axes
        """
        ev, cls, zone = create_open_event()
        w1 = validate_success(api.weather_decision(ev["id"], {"posture": "WATCH", "reason": "radar cell"}, ORG))
        assert w1["weather_posture"] == "WATCH"
        w2 = validate_success(api.weather_decision(ev["id"], {"posture": "POSTPONED", "reason": "hail"}, ORG))
        assert w2["weather_posture"] == "POSTPONED"
        w3 = validate_success(api.weather_decision(ev["id"], {"posture": "NORMAL", "reason": "all clear"}, ORG))
        assert w3["weather_posture"] == "NORMAL"
        after = validate_success(api.get_event(ev["id"], ORG))
        assert after["lifecycle_status"] == "REGISTRATION_OPEN", (
            "the weather cycle must not disturb the lifecycle axis")

    def test_weather_posture_revert_cycle_succeeds(self, api):
        """PRD §3.7: "The allowed posture moves are: `NORMAL` → `WATCH` to raise
        caution; `WATCH` → `NORMAL` to stand back down; `NORMAL` or `WATCH` →
        `POSTPONED` when the show is delayed; `POSTPONED` → `NORMAL` on the
        all-clear".

        Design: Difficulty/non_linear_state_machine/event_parallel_lifecycle_weather_axes
        """
        ev, cls, zone = create_open_event()
        for posture in ["WATCH", "POSTPONED", "NORMAL"]:
            out = validate_success(api.weather_decision(ev["id"], {"posture": posture}, ORG))
            assert out["weather_posture"] == posture
        final = validate_success(api.get_event(ev["id"], ORG))
        assert final["weather_posture"] == "NORMAL"
        assert final["lifecycle_status"] == "REGISTRATION_OPEN"

    def test_weather_cancelled_terminal_lockdown(self, api):
        """PRD §3.7: "A decision that does not correspond to an allowed move from
        the current posture — a second `WATCH`, or any move once `CANCELLED` — is
        rejected with `ERR_INVALID_EVENT_STATE`."

        Design: Corner/state_machines/weather_cancelled_terminal_lockdown
        """
        ev, cls, zone = create_open_event()
        get_success_data(api.weather_decision(ev["id"], {"posture": "CANCELLED", "reason": "flooding"}, ORG))
        resp = api.weather_decision(ev["id"], {"posture": "WATCH", "reason": "maybe clearing"}, ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE)
        after = validate_success(api.get_event(ev["id"], ORG))
        assert after["weather_posture"] == "CANCELLED"


