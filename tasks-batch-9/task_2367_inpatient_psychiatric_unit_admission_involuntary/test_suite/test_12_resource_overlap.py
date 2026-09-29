"""Two contested resources: one advocate's calendar and one unit's seclusion room.

The docket is guarded by a padded interval, so a 29-minute gap collides and a
30-minute gap does not. The seclusion room is guarded by a right-open interval, so
it frees itself by clock arithmetic while the episode is still open.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    HearingStatus,
    InterventionType,
    MONITORING_INTERVAL_MINUTES,
    PetitionStatus,
    RestraintStatus,
    active_hold_case,
    assert_created,
    assert_docket_minutes,
    assert_error,
    assert_page,
    build_ward,
    create_petition,
    hearing_payload,
    order_restraint,
    read_clinician,
    read_petition,
    read_restraint,
    read_unit,
    restraint_payload,
    scheduled_hearing,
    set_clock,
    voluntary_placed_admission,
)

FIRST_HEARING_START = "2026-09-04T10:00:00Z"
FIRST_HEARING_MINUTES = 60
FIRST_HEARING_END = "2026-09-04T11:00:00.000Z"
TWENTY_NINE_MINUTE_GAP = "2026-09-04T11:29:00Z"
THIRTY_MINUTE_GAP = "2026-09-04T11:30:00Z"
SECOND_HEARING_MINUTES = 30
SECOND_HEARING_START = "2026-09-04T11:30:00.000Z"
SECOND_HEARING_END = "2026-09-04T12:00:00.000Z"

SECLUSION_BEDS = (
    {"room_number": "411", "wing_code": "A", "bed_label": "A"},
    {"room_number": "412", "wing_code": "A", "bed_label": "A"},
    {"room_number": "413", "wing_code": "B", "bed_label": "A"},
)
SECLUSION_MINUTES = 30
FIRST_AUTHORIZED_UNTIL = "2026-09-03T08:30:00.000Z"
RELEASE_INSTANT = "2026-09-03T08:30:00Z"
SECOND_AUTHORIZED_UNTIL = "2026-09-03T09:00:00.000Z"
SECOND_FACE_TO_FACE_DEADLINE = "2026-09-03T09:30:00.000Z"


def _two_petitions_and_one_booked_advocate(api, roster):
    """One advocate holding a 10:00-11:00 listing, and a second petition awaiting one."""
    first = active_hold_case(
        api,
        roster,
        mrn="MRN-2367-DK1",
        legal_name="Dara Kesswood",
        age_years=44,
        gender_care_category="FEMALE",
    )
    second = active_hold_case(
        api,
        roster,
        mrn="MRN-2367-DK2",
        legal_name="Devon Kruse",
        age_years=37,
        gender_care_category="MALE",
    )
    first["petition"] = create_petition(
        api, roster.psychiatrist_headers, first["hold"]["id"]
    )
    second["petition"] = create_petition(
        api, roster.psychiatrist_headers, second["hold"]["id"]
    )
    first["hearing"] = scheduled_hearing(
        api,
        roster.advocate_headers,
        first["petition"]["id"],
        roster.advocate["id"],
        FIRST_HEARING_START,
        FIRST_HEARING_MINUTES,
    )
    return first, second


def _book(api, roster, petition_id, start_at):
    """Attempt one thirty-minute listing on the advocate's docket."""
    return api.create_hearing(
        roster.advocate_headers,
        hearing_payload(
            petition_id=petition_id,
            advocate_clinician_id=roster.advocate["id"],
            scheduled_start_at=start_at,
            duration_minutes=SECOND_HEARING_MINUTES,
        ),
    )


def _seclusion_bay_with_one_live_episode(api, roster):
    """A one-room seclusion bay whose room is held by an ORDERED episode until 08:30."""
    ward = build_ward(
        api,
        name="Ward 10 Seclusion Bay",
        gender_mixing_policy="MIXED_ALLOWED",
        seclusion_room_count=1,
        bed_specs=SECLUSION_BEDS,
    )
    first = voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-S1",
        legal_name="Silas Nair",
        age_years=41,
        gender_care_category="MALE",
        bed_id=ward.beds[0]["id"],
    )
    second = voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-S2",
        legal_name="Solomon Ives",
        age_years=52,
        gender_care_category="MALE",
        bed_id=ward.beds[1]["id"],
    )
    episode = order_restraint(
        api,
        roster,
        first["admission"]["id"],
        InterventionType.SECLUSION.value,
        SECLUSION_MINUTES,
    )
    return ward, second, episode


class TestAdvocateDocketBuffer:
    """The travel buffer is part of the interval, and its boundary is exact."""

    def test_a_twenty_nine_minute_gap_collides_with_the_existing_listing(
        self, api, clock, roster
    ):
        """The refused listing leaves the petition filed and the docket at sixty minutes.

        PRD 3.4: "Concretely, a conflict exists when the new start minus 30 minutes
        falls before the existing end **and** the existing start falls before the
        new end plus 30 minutes; a conflict is reported as
        `ERR_ADVOCATE_DOCKET_CONFLICT`. The buffer boundary is exact: a gap of
        exactly 30 minutes between two hearings is permitted, while a gap of 29
        minutes is not."

        Design: Difficulty/resource_temporal_overlap/advocate_docket_thirty_minute_buffer_boundary
        """
        first, second = _two_petitions_and_one_booked_advocate(api, roster)
        assert first["hearing"]["scheduled_end_at"] == FIRST_HEARING_END
        assert first["hearing"]["status"] == HearingStatus.SCHEDULED.value

        refusal = _book(api, roster, second["petition"]["id"], TWENTY_NINE_MINUTE_GAP)

        assert_error(refusal, ApiErrorId.ADVOCATE_DOCKET_CONFLICT)
        assert (
            read_petition(api, second["petition"]["id"])["status"]
            == PetitionStatus.FILED.value
        )
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), FIRST_HEARING_MINUTES
        )

    def test_a_gap_of_exactly_thirty_minutes_is_permitted_and_books_the_docket(
        self, api, clock, roster
    ):
        """The accepted listing lifts the advocate's booked minutes to ninety.

        PRD 3.4: "A successful scheduling recomputes that advocate's
        `booked_docket_minutes`, which rises by the new hearing's
        `duration_minutes`, and increments `Clinician.version` by one."

        Design: Difficulty/resource_temporal_overlap/advocate_docket_thirty_minute_buffer_boundary
        """
        _, second = _two_petitions_and_one_booked_advocate(api, roster)

        booked = assert_created(
            _book(api, roster, second["petition"]["id"], THIRTY_MINUTE_GAP)
        )

        assert booked["scheduled_start_at"] == SECOND_HEARING_START
        assert booked["scheduled_end_at"] == SECOND_HEARING_END
        assert booked["status"] == HearingStatus.SCHEDULED.value
        assert (
            read_petition(api, second["petition"]["id"])["status"]
            == PetitionStatus.HEARING_SCHEDULED.value
        )
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]),
            FIRST_HEARING_MINUTES + SECOND_HEARING_MINUTES,
        )
        assert_page(
            api.list_hearings(
                COMPLIANCE_OFFICER_HEADERS,
                advocate_clinician_id=roster.advocate["id"],
                status=HearingStatus.SCHEDULED.value,
            ),
            2,
        )


class TestSeclusionCapacityInterval:
    """The single seclusion room is occupied up to, but not including, its authorized end."""

    def test_the_only_seclusion_room_is_held_while_the_episode_is_still_authorized(
        self, api, clock, roster
    ):
        """A second order at 08:00 is refused and creates no episode at all.

        PRD 3.6: "Before a `SECLUSION` episode is created, the system counts the
        live seclusion load on the admission's unit: episodes whose
        `intervention_type` is `SECLUSION`, whose `status` is `ORDERED` or `ACTIVE`,
        whose `authorized_until_at` is strictly after the current clock, and whose
        admission sits on that unit. That count must be strictly below the unit's
        `seclusion_room_count`; otherwise the order is refused with
        `ERR_SECLUSION_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/unit_seclusion_capacity_half_open_interval
        """
        ward, second, episode = _seclusion_bay_with_one_live_episode(api, roster)
        assert episode["authorized_until_at"] == FIRST_AUTHORIZED_UNTIL
        assert (
            episode["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.SECLUSION.value]
        )
        assert episode["status"] == RestraintStatus.ORDERED.value
        assert read_unit(api, ward.id)["active_seclusion_count"] == 1

        refusal = api.create_restraint(
            roster.psychiatrist_headers,
            restraint_payload(
                admission_id=second["admission"]["id"],
                intervention_type=InterventionType.SECLUSION.value,
                ordered_duration_minutes=SECLUSION_MINUTES,
            ),
        )

        assert_error(refusal, ApiErrorId.SECLUSION_CAPACITY_EXCEEDED)
        assert_page(
            api.list_restraints(
                COMPLIANCE_OFFICER_HEADERS, admission_id=second["admission"]["id"]
            ),
            0,
        )

    def test_the_room_frees_at_exactly_the_authorized_end_without_any_release(
        self, api, clock, roster
    ):
        """At 08:30 the same order is accepted while the first episode is still ORDERED.

        PRD 3.6: "`authorized_until_at` is `started_at` plus
        `ordered_duration_minutes`, and it is the right-open end of the episode's
        occupancy interval."

        PRD 3.6: "The same query defines the unit's `active_seclusion_count`, which
        is recomputed with `Unit.version` incremented by one whenever a seclusion
        episode is created, released or expired."

        Design: Difficulty/resource_temporal_overlap/unit_seclusion_capacity_half_open_interval
        """
        ward, second, episode = _seclusion_bay_with_one_live_episode(api, roster)
        set_clock(api, RELEASE_INSTANT)

        accepted = assert_created(
            api.create_restraint(
                roster.psychiatrist_headers,
                restraint_payload(
                    admission_id=second["admission"]["id"],
                    intervention_type=InterventionType.SECLUSION.value,
                    ordered_duration_minutes=SECLUSION_MINUTES,
                ),
            )
        )

        assert accepted["started_at"] == FIRST_AUTHORIZED_UNTIL
        assert accepted["authorized_until_at"] == SECOND_AUTHORIZED_UNTIL
        assert accepted["face_to_face_deadline_at"] == SECOND_FACE_TO_FACE_DEADLINE

        lapsed = read_restraint(api, episode["id"])
        assert lapsed["status"] == RestraintStatus.ORDERED.value
        assert lapsed["released_at"] is None
        assert read_unit(api, ward.id)["active_seclusion_count"] == 1
