"""Optimistic concurrency on the study version, the clock-gated visit start,
the expiry-sweep ops checkpoint, and create/read consistency
(PRD §2.7, §3.1, §3.2, §3.5, §3.9)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    create_study, create_site, create_fee_schedule, create_staff_member,
    approve_fee_schedule, setup_active_study, setup_pharmacy,
    create_monitor_visit, start_visit, set_clock, get_kit, get_lot,
    upload_slots, slot_spec, create_monitor_visit_payload,
)
from test_helpers import TEST_USERS, make_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]
MONITOR = TEST_USERS["monitor_headers"]


def test_fee_schedule_approve_stale_version_returns_412():
    """PRD §2.7: "`POST /api/fee-schedules/{id}/approve` requires the request to
    carry `expected_study_version` holding the client's last-observed `version`
    of the study. Approving a fee schedule supersedes the study's currently
    approved schedule — a legitimate create-with-supersede — so if the study's
    version has advanced since the client last read it (for example because
    another schedule was approved or the study transitioned), the approval is
    rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.1: "A successful
    approval moves the schedule from `DRAFT` to `APPROVED`, pushes any other
    `APPROVED` schedule of the same study into `SUPERSEDED`, and increments both
    the fee schedule's `version` and the study's `version`."

    Design: Corner/cross_cutting_layers/fee_schedule_approve_stale_version_returns_412
    """
    study = create_study(protocol_number="P-CC-1")
    fs1 = create_fee_schedule(study["id"], setup_fee_cents=100)
    fs2 = create_fee_schedule(study["id"], setup_fee_cents=200, dispensing_fee_cents=6000)
    first = get_success_data(api_client.approve_fee_schedule(
        fs1["id"], {"expected_study_version": study["version"]}, SPONSOR))
    assert first["status"] == "APPROVED"
    # The first approval advanced the study version; fs2's carried version is stale.
    resp = api_client.approve_fee_schedule(
        fs2["id"], {"expected_study_version": study["version"]}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    fresh = get_success_data(api_client.get_study(study["id"], SPONSOR))["version"]
    assert fresh != study["version"]
    second = get_success_data(api_client.approve_fee_schedule(
        fs2["id"], {"expected_study_version": fresh}, SPONSOR))
    assert second["status"] == "APPROVED"
    assert get_success_data(api_client.get_fee_schedule(fs1["id"], SPONSOR))["status"] == "SUPERSEDED"


def test_slot_list_replace_stale_version_and_retires_unassigned():
    """PRD §2.7: "`POST /api/studies/{id}/randomization-slots/replace` likewise
    requires `expected_study_version`. Replacing a study's randomization list
    retires every unassigned slot and installs a new list — a legitimate
    supersede of the prior list — and the same rule applies: a value that no
    longer matches the study's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)." PRD §3.5: "A successful replacement retires
    every `UNASSIGNED` slot to `RELEASED`, installs the payload slots as fresh
    `UNASSIGNED` entries, leaves `ASSIGNED` slots untouched, and increments the
    study's `version` by one."

    Design: Corner/cross_cutting_layers/slot_list_replace_stale_version_and_retires_unassigned
    """
    ctx = setup_active_study(protocol_number="P-CC-2")
    study_id = ctx["study"]["id"]
    old_slots = upload_slots(study_id, ctx["study_version"],
                             [slot_spec(1, "K-OLD", arm_code="TRT-A")])
    # The first replace advanced the study version, so the carried one is stale.
    resp = api_client.replace_randomization_slots(
        study_id, {"slots": [slot_spec(1, "K-NEW", arm_code="PBO")],
                   "expected_study_version": ctx["study_version"]}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    fresh = get_success_data(api_client.get_study(study_id, SPONSOR))["version"]
    get_success_data(api_client.replace_randomization_slots(
        study_id, {"slots": [slot_spec(1, "K-NEW", arm_code="PBO")],
                   "expected_study_version": fresh}, SPONSOR))
    old = get_success_data(api_client.get_randomization_slot(old_slots[0]["id"], SPONSOR))
    assert old["status"] == "RELEASED", "the prior UNASSIGNED slot is retired"


def test_monitor_start_outside_window_rejected_until_clock_enters():
    """PRD §3.9: "Starting a visit is gated on the clock: the `Monitor` may
    start only while the logical clock lies within the scheduled window, both
    bounds inclusive, otherwise the start is rejected with
    `ERR_OUTSIDE_VISIT_WINDOW`; starting stamps `started_at` and moves the visit
    `SCHEDULED` → `IN_PROGRESS`."

    Design: Corner/cross_cutting_layers/monitor_start_outside_window_rejected_until_clock_enters
    """
    study = create_study(protocol_number="P-CC-3")
    site = create_site(study["id"])
    visit = create_monitor_visit(site["id"], "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z")
    # The default clock 2026-08-01 is before the window.
    resp = api_client.start_monitor_visit(visit["id"], MONITOR)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_VISIT_WINDOW.value, expected_status=422)
    set_clock("2026-08-10T10:00:00Z")
    started = get_success_data(api_client.start_monitor_visit(visit["id"], MONITOR))
    assert started["status"] == "IN_PROGRESS"
    assert started["started_at"] is not None


def test_expiry_sweep_expires_kits_and_lot_then_resupplies():
    """PRD §3.2: "an ops checkpoint — the sponsor-invoked expiry sweep —
    advances expiry in three phases: every kit in `QUARANTINED_RECEIPT`,
    `AVAILABLE`, `QUARANTINED_EXCURSION`, or `ALLOCATED` whose lot's
    `expiry_date` has been reached by the logical clock moves to `EXPIRED`; then
    each lot whose `expiry_date` has been reached transitions from `ACTIVE` to
    `EXPIRED`, while a `DEPLETED` lot past expiry transitions to `CLOSED`; and
    finally any lot left with zero usable kits receives the same automatic
    resupply, this time sized to the number of that lot's kits at the site
    expired by the sweep and continuing the lot's `RS-` sequence. The sweep's
    response reports `kits_expired`, `lots_expired`, and
    `resupply_kits_created`."

    Design: Corner/cross_cutting_layers/expiry_sweep_expires_kits_and_lot_then_resupplies
    """
    world = setup_pharmacy(protocol_number="P-CC-4", kit_numbers=("K-EXP",),
                           pharmacist_license="L-CC-4",
                           lot_overrides={"lot_number": "LOT-EXP-1",
                                          "expiry_date": "2026-09-01T00:00:00Z"})
    set_clock("2026-09-02T00:00:00Z")
    result = get_success_data(api_client.run_expiry_sweep(SPONSOR))
    assert result["kits_expired"] == 1
    assert result["lots_expired"] == 1
    assert result["resupply_kits_created"] == 1
    assert get_kit(world["kits"][0]["id"])["status"] == "EXPIRED"
    assert get_lot(world["lot"]["id"])["status"] == "EXPIRED"
    data, meta = validate_paginated(api_client.list_kits(
        SPONSOR, params={"lot_id": world["lot"]["id"], "status": "IN_TRANSIT"}))
    assert meta["total_count"] == 1
    assert data[0]["kit_number"] == "RS-LOT-EXP-1-1"


def test_study_create_then_get_immediately_consistent():
    """PRD §3.1: "A new study begins in `DRAFT` status with `version` 1, and its
    two integrity counters — `randomized_subject_count` and
    `unblinded_subject_count` — start at zero." PRD §2.2: "The `data` field
    contains the resource object or an array of resource objects."

    Design: Corner/consistency_model/study_create_then_get_immediately_consistent
    """
    study = create_study(protocol_number="P-CM-1", title="Cons", phase="PHASE_IV",
                         blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    data = validate_success(api_client.get_study(study["id"], SPONSOR))
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["randomized_subject_count"] == 0
    assert data["unblinded_subject_count"] == 0
