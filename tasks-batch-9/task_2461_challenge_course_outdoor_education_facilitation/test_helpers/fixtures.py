"""Composite setup builders.

Every builder drives the real API with the real role headers, uses
``get_success_data`` so a broken setup step fails loudly, and returns the
identifiers a test needs. Entity-backed roles are always addressed through the
identifier of the row that backs them, never through a shared constant.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .test_users import (
    PROGRAM_DIRECTOR,
    make_facilitator_headers,
    make_group_coordinator_headers,
    make_professional_inspector_headers,
    make_safety_officer_headers,
)

# --- Clock -------------------------------------------------------------------


def set_clock(api, current_utc=C.CLOCK_TEST_UTC, headers=PROGRAM_DIRECTOR):
    """Move the logical clock; recomputes nothing on its own."""
    return get_success_data(api.set_clock(current_utc, headers))


# --- Courses, staff and elements ---------------------------------------------


def create_course(api, **overrides):
    data = get_success_data(api.create_course(F.course_payload(**overrides), PROGRAM_DIRECTOR))
    return data["id"]


def add_training(api, facilitator_id, kind="RESCUE_DRILL", **overrides):
    return get_success_data(
        api.create_training_record(
            F.training_record_payload(facilitator_id, kind, **overrides), PROGRAM_DIRECTOR
        )
    )


def make_current(api, facilitator_id):
    """Give a facilitator a fresh rescue drill and a full refresher block."""
    add_training(api, facilitator_id, "RESCUE_DRILL")
    add_training(api, facilitator_id, "REFRESHER")


def create_safety_officer(api, course_id, trained=True, **overrides):
    data = get_success_data(
        api.create_facilitator(
            F.facilitator_payload(course_id, "SAFETY_OFFICER", **overrides), PROGRAM_DIRECTOR
        )
    )
    if trained:
        make_current(api, data["id"])
    return data["id"]


def create_staff_facilitator(api, course_id, trained=True, **overrides):
    data = get_success_data(
        api.create_facilitator(
            F.facilitator_payload(course_id, "STAFF_FACILITATOR", **overrides), PROGRAM_DIRECTOR
        )
    )
    if trained:
        make_current(api, data["id"])
    return data["id"]


def create_contract_inspector(api, course_id, trained=True, **overrides):
    data = get_success_data(
        api.create_facilitator(
            F.facilitator_payload(course_id, "CONTRACT_INSPECTOR", **overrides), PROGRAM_DIRECTOR
        )
    )
    if trained:
        make_current(api, data["id"])
    return data["id"]


def create_element(api, course_id, element_type="GROUND_INITIATIVE", **overrides):
    data = get_success_data(
        api.create_element(F.element_payload(course_id, element_type, **overrides), PROGRAM_DIRECTOR)
    )
    return data["id"]


def staffed_course(api, course_name=C.COURSE_NAME_PRIMARY, ems_access_note=C.COURSE_NOTE_PRIMARY):
    """A course with two current facilitators, which is what rescue readiness needs.

    Returns the course identifier plus the safety officer and staff facilitator
    identifiers and their headers.
    """
    course_id = create_course(api, course_name=course_name, ems_access_note=ems_access_note)
    so_id = create_safety_officer(api, course_id)
    f1_id = create_staff_facilitator(api, course_id)
    return {
        "course_id": course_id,
        "so_id": so_id,
        "so_headers": make_safety_officer_headers(so_id),
        "f1_id": f1_id,
        "f1_headers": make_facilitator_headers(f1_id),
    }


def with_inspector(api, world, **overrides):
    """Add an independent contract inspector to an existing staffed course."""
    insp_id = create_contract_inspector(api, world["course_id"], **overrides)
    world["insp_id"] = insp_id
    world["insp_headers"] = make_professional_inspector_headers(insp_id)
    return world


# --- Clients and bookings ----------------------------------------------------


def create_funded_client(api, amount_cents=C.CLIENT_PAYMENT_CENTS, **overrides):
    data = get_success_data(
        api.create_group_client(F.group_client_payload(**overrides), PROGRAM_DIRECTOR)
    )
    gc_id = data["id"]
    if amount_cents:
        get_success_data(
            api.create_payment(gc_id, F.payment_payload(amount_cents=amount_cents), PROGRAM_DIRECTOR)
        )
    return gc_id


def create_booking(api, course_id, group_client_id, expected_participant_count=1, **overrides):
    data = get_success_data(
        api.create_booking(
            F.booking_payload(course_id, group_client_id, expected_participant_count, **overrides),
            PROGRAM_DIRECTOR,
        )
    )
    return data["id"], data["version"]


def booking_version(api, booking_id, headers=PROGRAM_DIRECTOR):
    """Re-read the booking to obtain the version the next write must carry."""
    return get_success_data(api.get_booking(booking_id, headers))["version"]


def add_participant(api, group_client_id, booking_id, kind="ADULT", screen=True, **overrides):
    """Add one participant, re-reading the booking version first."""
    gc_headers = make_group_coordinator_headers(group_client_id)
    version = booking_version(api, booking_id)
    data = get_success_data(
        api.create_participant(
            F.participant_payload(booking_id, version, kind, **overrides), gc_headers
        )
    )
    participant_id = data["id"]
    if screen:
        submit_packet(api, group_client_id, participant_id)
    return participant_id


def submit_packet(api, group_client_id, participant_id, **overrides):
    gc_headers = make_group_coordinator_headers(group_client_id)
    return get_success_data(
        api.submit_screening_packet(
            participant_id, F.screening_packet_payload(**overrides), gc_headers
        )
    )


def add_blocks(api, booking_id, specs):
    """Create program blocks from (sequence_index, phase, start, end[, element_id]) tuples."""
    ids = []
    for spec in specs:
        sequence_index, phase, start_at, end_at = spec[:4]
        overrides = {}
        if len(spec) > 4 and spec[4] is not None:
            overrides["element_id"] = spec[4]
        data = get_success_data(
            api.create_program_block(
                F.program_block_payload(
                    booking_id, sequence_index, phase, start_at, end_at, **overrides
                ),
                PROGRAM_DIRECTOR,
            )
        )
        ids.append(data["id"])
    return ids


def canonical_blocks(element_ids=None):
    """The five-phase program used across the pricing and start scenarios.

    ``element_ids`` optionally maps a phase name to the element the block is
    rigged to.
    """
    element_ids = element_ids or {}
    specs = []
    for index, (phase, start_at, end_at) in enumerate(C.CANONICAL_BLOCKS, start=1):
        specs.append((index, phase, start_at, end_at, element_ids.get(phase)))
    return specs


def quote_booking(api, booking_id):
    version = booking_version(api, booking_id)
    return get_success_data(
        api.quote_booking(booking_id, {"expected_booking_version": version}, PROGRAM_DIRECTOR)
    )


def confirm_booking(api, group_client_id, booking_id):
    return get_success_data(
        api.confirm_booking(booking_id, make_group_coordinator_headers(group_client_id))
    )


# --- Operational artefacts ---------------------------------------------------


def clear_log(api, element_id, facilitator_id, headers, **overrides):
    """File a CLEAR pre-use log, which is what clears the daily-inspection gate."""
    return get_success_data(
        api.create_operational_log(
            F.operational_log_payload(element_id, facilitator_id, "CLEAR", **overrides), headers
        )
    )


def defect_major_log(api, element_id, facilitator_id, headers, **overrides):
    return get_success_data(
        api.create_operational_log(
            F.operational_log_payload(element_id, facilitator_id, "DEFECT_MAJOR", **overrides),
            headers,
        )
    )


def assign_facilitator(api, program_block_id, facilitator_id, **overrides):
    payload = {"facilitator_id": facilitator_id}
    payload.update(overrides)
    return get_success_data(
        api.create_block_assignment(program_block_id, payload, PROGRAM_DIRECTOR)
    )


def rig_equipment(api, course_id, element_id, equipment_kind="ROPE", **overrides):
    payload = F.belay_equipment_payload(
        course_id, equipment_kind, assigned_element_id=element_id, **overrides
    )
    return get_success_data(api.create_belay_equipment(payload, PROGRAM_DIRECTOR))["id"]


def observe_weather(api, course_id, headers, **overrides):
    return get_success_data(
        api.create_weather_observation(F.weather_observation_payload(course_id, **overrides), headers)
    )
