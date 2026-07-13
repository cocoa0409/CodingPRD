"""Staff-shift handover buffer and shelter staff-shift listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_incident, create_shelter, create_staff_shift, TEST_USERS,
)

SHELTER = TEST_USERS["shelter_headers"]


def test_staff_shift_within_buffer_rejected(api):
    """PRD 3.4: "Two `SCHEDULED` shifts on the same shelter must be separated by at least a 30-minute handover buffer — the later shift's `start_utc` must be at least 30 minutes after the earlier shift's `end_utc` — otherwise the schedule request is rejected with `ERR_STAFF_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/staff_shift_handover_buffer_violation
    """
    inc = create_incident()
    shelter = create_shelter(inc["id"], physical_capacity=50)
    create_staff_shift(shelter["id"], staffed_beds=20,
                       start_utc="2026-03-01T00:00:00Z", end_utc="2026-03-01T08:00:00Z")

    # Second shift starts 20 minutes after the first ends -> inside the 30-minute buffer.
    resp = api.create_staff_shift(
        {"shelter_id": shelter["id"], "role_label": "GENERAL", "staffed_beds": 20,
         "start_utc": "2026-03-01T08:20:00Z", "end_utc": "2026-03-01T16:00:00Z"},
        SHELTER,
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_SHIFT_OVERLAP)


def test_staff_shift_at_buffer_boundary_allowed(api):
    """PRD 3.4: "the later shift's `start_utc` must be at least 30 minutes after the earlier shift's `end_utc`"

    Design: Difficulty/resource_temporal_overlap/staff_shift_handover_buffer_violation
    """
    inc = create_incident()
    shelter = create_shelter(inc["id"], physical_capacity=50)
    create_staff_shift(shelter["id"], staffed_beds=20,
                       start_utc="2026-03-01T00:00:00Z", end_utc="2026-03-01T08:00:00Z")

    # Second shift starts exactly 30 minutes after the first ends -> at the buffer boundary.
    data = validate_success(
        api.create_staff_shift(
            {"shelter_id": shelter["id"], "role_label": "GENERAL", "staffed_beds": 20,
             "start_utc": "2026-03-01T08:30:00Z", "end_utc": "2026-03-01T16:00:00Z"},
            SHELTER,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_shelter_staff_shifts_listed_under_shelter(api):
    """PRD 3.4: "A shelter's staff shifts may be listed under the shelter."

    Design: Corner/endpoints/staff_shifts_reverse_reachability_subresource
    """
    inc = create_incident()
    shelter = create_shelter(inc["id"], physical_capacity=50)
    shift = create_staff_shift(shelter["id"], staffed_beds=20,
                               start_utc="2026-03-01T00:00:00Z", end_utc="2026-03-01T08:00:00Z")

    shifts, _meta = validate_paginated(api.list_shelter_staff_shifts(shelter["id"], SHELTER))
    ids = [s["id"] for s in shifts]
    assert shift["id"] in ids
    assert len(ids) == 1
