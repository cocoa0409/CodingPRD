"""Participant muster (VETTED -> CHECKED_IN): event posture gate, uninspected
equipment gate, and the minor supervision gates including the inclusive
supervision-ratio boundary."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_signed_agreement,
    check_in_participant,
    create_event,
    declare_equipment,
    get_event,
    open_gates,
    open_registration,
    publish_event,
    record_inspection,
    schedule_inspection,
    setup_approved_unit,
    setup_vetted_participant,
)

ORG = TEST_USERS["organizer_headers"]


def _setup_vetted_before_publish():
    """Event with signed obligations; roster built while REGISTRATION_OPEN;
    event then published. Returns (event, unit, participant) with the
    participant VETTED and the gates still closed."""
    event = create_event()
    add_signed_agreement(event["id"], "LANDOWNER_USE")
    add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
    open_registration(event["id"])
    unit = setup_approved_unit(event["id"])
    participant = setup_vetted_participant(event["id"], unit_id=unit["id"])
    publish_event(event["id"])
    return event, unit, participant


class TestEventPostureGate:
    def test_participant_checkin_requires_event_open(self, api):
        """PRD §3.3: "The event must be in `EVENT_OPEN` posture
        (`ERR_INVALID_EVENT_POSTURE`)"

        Design: Difficulty/cross_entity_state_dependency/participant_checkin_requires_event_open
        """
        event, unit, participant = _setup_vetted_before_publish()
        assert get_event(event["id"])["event_posture"] == "PUBLISHED"

        blocked = api_client.check_in_participant(participant["id"], ORG)
        validate_error(blocked, ApiErrorId.ERR_INVALID_EVENT_POSTURE, 409)

        open_gates(event["id"])
        checked = validate_success(api_client.check_in_participant(participant["id"], ORG), 200)
        assert checked["status"] == "CHECKED_IN", (
            "the same check-in succeeds once the event reaches EVENT_OPEN"
        )
        assert checked["checked_in_at"] is not None

    def test_participant_checkin_rejected_while_restricted(self, api):
        """PRD §3.3: "The event must be in `EVENT_OPEN` posture
        (`ERR_INVALID_EVENT_POSTURE`)"
        PRD §3.9: "The same transition and the same open-flame cascade are
        available manually: the organizer or a safety officer may restrict the
        event from `EVENT_OPEN`, with an optional `reason`."

        Design: Difficulty/cross_entity_state_dependency/participant_checkin_requires_event_open
        """
        event, unit, participant = _setup_vetted_before_publish()
        open_gates(event["id"])
        validate_success(
            api_client.restrict_event(event["id"], ORG, {"reason": "storm front approaching"}),
            200,
        )
        assert get_event(event["id"])["event_posture"] == "RESTRICTED"

        blocked = api_client.check_in_participant(participant["id"], ORG)
        validate_error(blocked, ApiErrorId.ERR_INVALID_EVENT_POSTURE, 409)
        reread = validate_success(api_client.get_participant(participant["id"], ORG), 200)
        assert reread["status"] == "VETTED", "rejected check-in leaves the participant VETTED"


class TestUninspectedEquipmentGate:
    def test_checkin_blocked_by_uninspected_equipment(self, api):
        """PRD §3.3: "no equipment item of the participant with `item_type`
        `FIREARM`, `EDGED`, `CANNON`, or `CAMP_FLAME` may sit in `DECLARED`,
        `INSPECTION_DUE`, or `FAILED` — such an item blocks check-in with
        `ERR_UNINSPECTED_EQUIPMENT`, while `TENTAGE` and `OTHER` items never do"

        Design: Corner/validations/checkin_blocked_by_uninspected_equipment
        """
        event, unit, participant = _setup_vetted_before_publish()
        item = declare_equipment(participant["id"], unit_id=unit["id"], item_type="FIREARM")
        open_gates(event["id"])

        blocked = api_client.check_in_participant(participant["id"], ORG)
        validate_error(blocked, ApiErrorId.ERR_UNINSPECTED_EQUIPMENT, 409)

        inspection = schedule_inspection(item["id"], officer="so-1",
                                         scheduled_for="2026-07-10T09:00:00Z")
        record_inspection(inspection["id"], officer="so-1", outcome="PASS")
        checked = validate_success(api_client.check_in_participant(participant["id"], ORG), 200)
        assert checked["status"] == "CHECKED_IN", (
            "once the FIREARM passes inspection the same check-in succeeds"
        )


class TestMinorSupervisionGates:
    def _setup_minor_scenario(self, with_supervisor=True, supervisor_checked_in=True,
                              extra_minors=0, extra_adults=0):
        """EVENT_OPEN event; CIVILIAN unit APPROVED; one adult (VETTED, maybe
        CHECKED_IN); 1 + extra_minors minors (age 12, VETTED) optionally naming
        the adult as supervisor; extra_adults additional checked-in adults.
        Returns (event, unit, adult, minors)."""
        event = create_event()
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])
        unit = setup_approved_unit(event["id"], name="Civilians of the Valley",
                                   unit_type="CIVILIAN", portrayal_name="Townsfolk")
        adult = setup_vetted_participant(event["id"], unit_id=unit["id"],
                                         full_name="Adult Ann", age_at_event=30,
                                         impression_class="CIVILIAN")
        minors = []
        # Minors are created after the adult so the supervisor reference resolves.
        for i in range(1 + extra_minors):
            overrides = dict(full_name=f"Minor {i}", age_at_event=12,
                             impression_class="CIVILIAN")
            if with_supervisor:
                overrides["supervisor_participant_id"] = adult["id"]
            minors.append(setup_vetted_participant(event["id"], unit_id=unit["id"], **overrides))
        extra = []
        for i in range(extra_adults):
            extra.append(setup_vetted_participant(
                event["id"], unit_id=unit["id"], full_name=f"Adult Ben {i}",
                age_at_event=41, impression_class="CIVILIAN",
            ))
        publish_event(event["id"])
        open_gates(event["id"])
        if supervisor_checked_in:
            check_in_participant(adult["id"])
        for other in extra:
            check_in_participant(other["id"])
        return event, unit, adult, minors

    def test_minor_checkin_without_supervisor_rejected(self, api):
        """PRD §3.3: "For a minor, three further gates apply in sequence:
        `supervisor_participant_id` must be set, else `ERR_SUPERVISOR_REQUIRED`"

        Design: Corner/validations/minor_checkin_without_supervisor_rejected
        """
        event, unit, adult, minors = self._setup_minor_scenario(with_supervisor=False)
        minor = minors[0]
        resp = api_client.check_in_participant(minor["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_REQUIRED, 422)
        reread = validate_success(api_client.get_participant(minor["id"], ORG), 200)
        assert reread["status"] == "VETTED"

    def test_minor_checkin_supervisor_not_checked_in_rejected(self, api):
        """PRD §3.3: "the named supervisor must be an adult (`age_at_event` at
        least 18), must belong to the same unit as the minor, and must already
        be `CHECKED_IN`, else `ERR_SUPERVISOR_INELIGIBLE`"

        Design: Corner/validations/minor_checkin_supervisor_not_checked_in_rejected
        """
        event, unit, adult, minors = self._setup_minor_scenario(
            with_supervisor=True, supervisor_checked_in=False
        )
        minor = minors[0]
        resp = api_client.check_in_participant(minor["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_INELIGIBLE, 422)
        reread = validate_success(api_client.get_participant(minor["id"], ORG), 200)
        assert reread["status"] == "VETTED"

    def test_supervision_ratio_inclusive_boundary(self, api):
        """PRD §3.3: "the unit's supervision ratio must admit one more minor —
        the number of the unit's already checked-in minors plus one must be at
        most the event's `max_minor_per_adult` multiplied by the number of the
        unit's already checked-in adults, an inclusive boundary — else
        `ERR_SUPERVISION_RATIO_EXCEEDED`."
        PRD §3.3: "Both ratio counts are taken at check-in time, after the
        supervisor's own check-in, and span the same unit only"

        Design: Difficulty/boundary_precision_check/supervision_ratio_inclusive_boundary
        """
        event, unit, adult, minors = self._setup_minor_scenario(extra_minors=4)
        assert len(minors) == 5
        # max_minor_per_adult = 4 with one checked-in adult: minors 1..4 satisfy
        # (minors_checked_in + 1) <= 4 * 1, the 4th exactly at the boundary.
        for minor in minors[:4]:
            checked = validate_success(api_client.check_in_participant(minor["id"], ORG), 200)
            assert checked["status"] == "CHECKED_IN"

        fifth = api_client.check_in_participant(minors[4]["id"], ORG)
        validate_error(fifth, ApiErrorId.ERR_SUPERVISION_RATIO_EXCEEDED, 409)
        reread = validate_success(api_client.get_participant(minors[4]["id"], ORG), 200)
        assert reread["status"] == "VETTED", "the 5th minor exceeds 4 * 1 and stays VETTED"

    def test_supervision_ratio_admits_after_second_adult(self, api):
        """PRD §3.3: "the unit's supervision ratio must admit one more minor —
        the number of the unit's already checked-in minors plus one must be at
        most the event's `max_minor_per_adult` multiplied by the number of the
        unit's already checked-in adults, an inclusive boundary — else
        `ERR_SUPERVISION_RATIO_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/supervision_ratio_inclusive_boundary
        """
        event, unit, adult, minors = self._setup_minor_scenario(
            extra_minors=4, extra_adults=1
        )
        # Two checked-in adults: 5 <= 4 * 2, so all five minors muster in.
        for minor in minors:
            checked = validate_success(api_client.check_in_participant(minor["id"], ORG), 200)
            assert checked["status"] == "CHECKED_IN"
