"""Rate schedule lifecycle, schedule pinning at entry, and the two
version-guarded writes (PRD optimistic concurrency control)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_draft_schedule,
    create_facility,
    create_parker,
    enter_vehicle_at,
    get_facility,
    get_success_data,
    make_gate_device_headers,
    publish_schedule,
    register_online_gate,
    setup_entry_ready_facility,
    setup_facility_with_published_rate,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]


def test_rate_schedule_supersede_self_reference(api):
    """PRD: "A successful publish moves the schedule from `DRAFT` to
    `PUBLISHED`, flips any other `PUBLISHED` schedule of the same facility to
    `SUPERSEDED`, stamps `published_at` with the logical now, and advances the
    facility's `version` by one — a facility therefore has at most one
    `PUBLISHED` schedule at a time."
    PRD: "The schedule list filters by `facility_id`, `schedule_status`, or
    `supersedes_schedule_id`."

    Design: Corner/entities/rate_schedule_supersede_self_reference
    """
    facility, old = setup_facility_with_published_rate(name="Sup Fac", label="Old")
    fresh = get_facility(facility["id"])
    from test_helpers import create_rate_schedule_payload
    payload = create_rate_schedule_payload(
        facility["id"], label="New", grace_minutes=20, first_hour_cents=600,
        daily_max_cents=2600, event_flat_cents=1600, lost_ticket_daily_cents=2600,
        supersedes_schedule_id=old["id"])
    new = get_success_data(api.create_rate_schedule(payload, FM))

    published = validate_success(
        api.publish_rate_schedule(new["id"], fresh["version"], FM), 200)
    assert published["schedule_status"] == "PUBLISHED"
    old_after = validate_success(api.get_rate_schedule(old["id"], FM), 200)
    assert old_after["schedule_status"] == "SUPERSEDED"

    data, meta = validate_paginated(api.list_rate_schedules(
        FM, params={"supersedes_schedule_id": old["id"]}))
    ids = [row["id"] for row in data]
    assert ids == [new["id"]], "reverse filter resolves the supersession chain"
    assert meta["total_count"] == 1


def test_occ_stale_facility_version_publish(api):
    """PRD: "Publishing a rate schedule requires the request to carry
    `expected_facility_version`, the `version` of the owning Facility the
    client last observed. If that value does not match the facility's current
    `version` — because a prior publish, a posture transition, a
    close-of-business run, or a cascade has advanced the facility since the
    client's read — the publish is rejected with `ERR_STALE_FACILITY_VERSION`
    (HTTP 412)"

    Design: Corner/complexity_layers/occ_stale_facility_version_publish
    """
    facility, rs1 = setup_facility_with_published_rate(name="OCC1 Fac")
    rs2 = create_draft_schedule(facility["id"], label="R2", grace_minutes=20,
                                first_hour_cents=600, daily_max_cents=2600)

    # Replay the pre-publish facility version: stale by one.
    stale = validate_error(
        api.publish_rate_schedule(rs2["id"], facility["version"] - 1, FM),
        ApiErrorId.ERR_STALE_FACILITY_VERSION)
    rs2_after = get_success_data(api.get_rate_schedule(rs2["id"], FM))
    assert rs2_after["schedule_status"] == "DRAFT"

    published = validate_success(
        api.publish_rate_schedule(rs2["id"], facility["version"], FM), 200)
    assert published["schedule_status"] == "PUBLISHED"
    rs1_after = get_success_data(api.get_rate_schedule(rs1["id"], FM))
    assert rs1_after["schedule_status"] == "SUPERSEDED"


def test_occ_stale_agreement_version_amend(api):
    """PRD: "Amending a monthly agreement likewise requires
    `expected_agreement_version` matching the agreement's current `version`;
    a stale value is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."
    PRD: "a successful amend advances the agreement's `version` by one."

    Design: Corner/complexity_layers/occ_stale_agreement_version_amend
    """
    facility = create_facility(name="OCC2 Fac")
    parker = create_parker(full_name="Occ Two", email="occ2@x.com")
    agreement = submit_agreement(facility["id"], parker["id"],
                                 monthly_rate_cents=20000)
    v1 = agreement["version"]

    amended = validate_success(api.amend_agreement(
        agreement["id"],
        {"expected_agreement_version": v1, "monthly_rate_cents": 21000}, FM), 200)
    assert amended["monthly_rate_cents"] == 21000
    assert amended["version"] == v1 + 1

    res = api.amend_agreement(
        agreement["id"],
        {"expected_agreement_version": v1, "monthly_rate_cents": 22000}, FM)
    validate_error(res, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

    after = get_success_data(api.get_monthly_agreement(agreement["id"], FM))
    assert after["monthly_rate_cents"] == 21000, "rejected amend leaves the field alone"
    assert after["version"] == v1 + 1


def test_parking_session_initial_state(api):
    """PRD: "A recorded entry stands `PARKED` with billing `OPEN`, `entry_at`
    read from the logical clock, the facility's effective `PUBLISHED` schedule
    pinned into `rate_schedule_id`, and `fee_mode` pinned by precedence —
    `MONTHLY` when a credential was presented, else `EVENT_FLAT` when the entry
    device stands in `EVENT` mode, else `STANDARD`."

    Design: Corner/state_machines/parking_session_initial_state
    """
    facility, schedule, gate = setup_entry_ready_facility(name="Init Fac")
    session = enter_vehicle_at(facility["id"], gate, "IN-1", "2026-08-01T10:00:00Z")
    assert session["occupancy_state"] == "PARKED"
    assert session["billing_state"] == "OPEN"
    assert session["fee_mode"] == "STANDARD"
    assert session["rate_schedule_id"] == schedule["id"], "schedule pinned at entry"
    assert session["entry_at"].startswith("2026-08-01T10:00:00"), (
        f"entry_at reads the logical clock, got {session['entry_at']!r}")


def test_no_published_rate_blocks_entry(api):
    """PRD: "Entry to the facility requires that some `PUBLISHED` schedule have
    `effective_from` at or before the logical now — otherwise the entry fails
    with `ERR_NO_PUBLISHED_RATE`."

    Design: Corner/validations/no_published_rate_blocks_entry
    """
    facility = create_facility(name="NP Fac")
    create_draft_schedule(facility["id"], label="Draft")  # never published
    gate = register_online_gate(facility["id"])
    res = api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate["id"],
         "ticket_barcode": "NP-1"},
        make_gate_device_headers(gate["id"]))
    validate_error(res, ApiErrorId.ERR_NO_PUBLISHED_RATE)
