"""Time windows that may abut but may not collide.

Injection reporting windows are half-open, so a period that begins exactly where
its predecessor ended is a clean hand-off rather than a collision, while any
genuine straddle of an accepted window is refused. Corrective-action windows are
closed instead, and they contend for the project's limited workover rig slots,
so a shared endpoint there does count as a clash.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assertions, constants, factories, fixtures


def _periods_by_id(api, permit_id):
    """Read a permit's reporting history back off the collection endpoint."""
    records, _meta = validate_paginated(
        api.list_injection_periods(permit_id, fixtures.DEVELOPER, {"limit": 100})
    )
    return {record["id"]: record for record in records}


def test_injection_period_abutting_predecessor_accepted_but_straddling_window_rejected(
    api,
):
    """Two periods of the same well may not overlap: a requested half-open interval that overlaps any existing period of that permit whose `status` is `ACCEPTED` is refused with `ERR_INJECTION_PERIOD_OVERLAP` (HTTP 409), while two periods that merely touch at an endpoint — one ending exactly where the next begins — do not overlap and are both accepted.

    Each record's `net_stored_tonnes` is its `mass_injected_tonnes` less its `measured_leakage_tonnes`, rounded half up to 3 decimal places, and the record rests at `status` `ACCEPTED` with `voided_at` null.

    The secure-storage ledger is the project's `cumulative_stored_tonnes`: the sum of `net_stored_tonnes` over every injection period record belonging to any permit of that project whose `status` is `ACCEPTED`, processed in `period_start` ascending order with ties broken by `created_at` ascending, and rounded half up to 3 decimal places.

    Design: Difficulty/resource_temporal_overlap/injection_periods_half_open_adjacency_permitted_overlap_rejected
    """
    ctx = fixtures.setup_project_with_ledger(api)
    permit_id = ctx["permit"]["id"]
    first, second = ctx["periods"]

    assertions.assert_injection_period_record(first)
    assertions.assert_injection_period_record(second)
    assert first["net_stored_tonnes"] == 299500.000
    assert second["net_stored_tonnes"] == 250000.000

    # The second window opens on the very instant the first one closes.
    rows = _periods_by_id(api, permit_id)
    assert rows[first["id"]]["period_end"][:19] == "2027-07-01T00:00:00"
    assert rows[second["id"]]["period_start"][:19] == "2027-07-01T00:00:00"
    assert rows[first["id"]]["status"] == "ACCEPTED"
    assert rows[second["id"]]["status"] == "ACCEPTED"

    straddling = api.report_injection_period(
        permit_id,
        factories.report_injection_period_payload(
            "2027-06-01T00:00:00Z",
            "2027-08-01T00:00:00Z",
            100000,
            measured_leakage_tonnes=0,
        ),
        fixtures.DEVELOPER,
    )
    validate_error(straddling, ApiErrorId.ERR_INJECTION_PERIOD_OVERLAP.value, 409)

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["cumulative_stored_tonnes"] == 549500.000
    assert len(_periods_by_id(api, permit_id)) == 2


def test_injection_period_window_reusable_after_the_occupying_record_is_voided(api):
    """Voiding sets the record's `status` to `VOIDED`, stamps `voided_at` with the logical clock, recomputes the project's `cumulative_stored_tonnes` over the remaining accepted records, then recomputes `reported_tonnes`, `verified_tonnes`, `credit_rate_usd_per_tonne` and `credit_amount_usd` on every tax credit claim of the project whose `status` is `DRAFT` or `SUBMITTED` and whose `tax_year` covers the voided period, then recomputes the project's `pending_credit_usd`, and bumps the project's `version`.

    Records whose `status` is `VOIDED` are excluded entirely.

    Two periods of the same well may not overlap: a requested half-open interval that overlaps any existing period of that permit whose `status` is `ACCEPTED` is refused with `ERR_INJECTION_PERIOD_OVERLAP` (HTTP 409), while two periods that merely touch at an endpoint — one ending exactly where the next begins — do not overlap and are both accepted.

    Design: Difficulty/resource_temporal_overlap/injection_periods_half_open_adjacency_permitted_overlap_rejected
    """
    ctx = fixtures.setup_project_with_ledger(api)
    permit_id = ctx["permit"]["id"]
    first, second = ctx["periods"]

    voided = fixtures.void_period(
        api,
        second["id"],
        void_reason="flow meter recalibration invalidated the reported mass",
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"][:19] == "2028-02-01T00:00:00"
    assert (
        fixtures.refresh_project(api, ctx["project"]["id"])["cumulative_stored_tonnes"]
        == 299500.000
    )

    # The voided record no longer occupies its window, so a shorter replacement
    # starting on the same instant is admissible.
    replacement = fixtures.report_period(
        api,
        permit_id,
        "2027-07-01T00:00:00Z",
        "2027-10-01T00:00:00Z",
        250000,
        measured_leakage_tonnes=0,
    )
    assertions.assert_injection_period_record(replacement)
    assert replacement["status"] == "ACCEPTED"
    assert replacement["net_stored_tonnes"] == 250000.000
    assert replacement["voided_at"] is None

    rows = _periods_by_id(api, permit_id)
    assert rows[first["id"]]["status"] == "ACCEPTED"
    assert rows[second["id"]]["status"] == "VOIDED"
    assert rows[replacement["id"]]["status"] == "ACCEPTED"

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["cumulative_stored_tonnes"] == 549500.000


def test_corrective_action_windows_sharing_one_endpoint_both_schedule_within_rig_slots(
    api,
):
    """Consider the sibling wellbores of the same project whose `corrective_action_status` is already `CA_SCHEDULED` and whose closed window running from `ca_window_start` through `ca_window_end` intersects the requested closed window — a shared endpoint counts as an intersection, since one rig cannot be in two places on the same day.

    If the count of such siblings is not strictly fewer than the project's `ca_rig_slots`, the request is refused with `ERR_CA_RIG_CAPACITY_EXCEEDED` (HTTP 409).

    On success the supplied window is stored as `ca_window_start` and `ca_window_end`, `corrective_action_status` moves `CA_REQUIRED → CA_SCHEDULED`, and the wellbore's `version` increments.

    Of the remaining in-area-of-review wellbores, those bearing `IDENTIFIED` are counted as in-scope for cost purposes but are not yet obligated; the obligated set is those whose status is `CA_REQUIRED`, `CA_SCHEDULED`, `CA_COMPLETE` or `CA_WAIVED`, and the closed set is the subset of those whose status is `CA_COMPLETE` or `CA_WAIVED`.

    Otherwise it is 100.0 multiplied by the count of closed wellbores divided by the count of obligated wellbores, rounded half up to 2 decimal places.

    Design: Difficulty/resource_temporal_overlap/corrective_action_windows_closed_interval_aggregate_rig_capacity
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    project_id = ctx["project"]["id"]
    assert ctx["project"]["ca_rig_slots"] == 2
    assert ctx["project"]["aor_radius_km"] == constants.EXPECTED_AOR_RADIUS_KM

    near_well = fixtures.register_wellbore(
        api, project_id, "15-001-20001", **constants.WELLBORE_SEAL_OPEN_HOLE_NEAR
    )
    mid_well = fixtures.register_wellbore(
        api, project_id, "15-001-20002", **constants.WELLBORE_PARTIALLY_PLUGGED_MID
    )
    assertions.assert_legacy_wellbore(near_well)
    assertions.assert_legacy_wellbore(mid_well)
    assert near_well["risk_score"] == 90.00
    assert near_well["corrective_action_status"] == "CA_REQUIRED"
    assert mid_well["risk_score"] == 47.60
    assert mid_well["corrective_action_status"] == "CA_REQUIRED"

    first_window = validate_success(
        api.schedule_corrective_action(
            near_well["id"],
            factories.schedule_corrective_action_payload(
                "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z"
            ),
            fixtures.DEVELOPER,
        ),
        200,
    )
    assert first_window["corrective_action_status"] == "CA_SCHEDULED"
    assert first_window["ca_window_start"][:19] == "2026-09-01T00:00:00"
    assert first_window["ca_window_end"][:19] == "2026-09-10T00:00:00"
    assert first_window["version"] > near_well["version"]

    # One rig is already committed on 2026-09-10, but the project owns two slots.
    second_window = validate_success(
        api.schedule_corrective_action(
            mid_well["id"],
            factories.schedule_corrective_action_payload(
                "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z"
            ),
            fixtures.DEVELOPER,
        ),
        200,
    )
    assert second_window["corrective_action_status"] == "CA_SCHEDULED"
    assert second_window["ca_window_start"][:19] == "2026-09-10T00:00:00"
    assert second_window["ca_window_end"][:19] == "2026-09-20T00:00:00"
    assert second_window["version"] > mid_well["version"]

    project = fixtures.refresh_project(api, project_id)
    assert project["corrective_action_completion_pct"] == 0.00


def test_corrective_action_window_refused_when_both_rigs_are_already_committed(api):
    """When the project's `aor_radius_km` is 0, or when the wellbore's `distance_from_injector_km` exceeds the project's `aor_radius_km`, the wellbore begins at `OUT_OF_AOR` and waits for a future delineation to pull it in.

    Immediately afterwards, each wellbore that has just reached `IDENTIFIED` and either has `penetrates_seal` true or carries a `risk_score` of at least 40.00 auto-advances `IDENTIFIED → CA_REQUIRED` in the same request — a wellbore that penetrates the confining zone is always obligated regardless of its score, and a wellbore that does not penetrate the seal is obligated only once its score reaches the 40.00 threshold.

    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.

    Consider the sibling wellbores of the same project whose `corrective_action_status` is already `CA_SCHEDULED` and whose closed window running from `ca_window_start` through `ca_window_end` intersects the requested closed window — a shared endpoint counts as an intersection, since one rig cannot be in two places on the same day.

    If the count of such siblings is not strictly fewer than the project's `ca_rig_slots`, the request is refused with `ERR_CA_RIG_CAPACITY_EXCEEDED` (HTTP 409).

    On success the supplied window is stored as `ca_window_start` and `ca_window_end`, `corrective_action_status` moves `CA_REQUIRED → CA_SCHEDULED`, and the wellbore's `version` increments.

    Design: Difficulty/resource_temporal_overlap/corrective_action_windows_closed_interval_aggregate_rig_capacity
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    project_id = ctx["project"]["id"]

    near_well = fixtures.register_wellbore(
        api, project_id, "15-001-20001", **constants.WELLBORE_SEAL_OPEN_HOLE_NEAR
    )
    mid_well = fixtures.register_wellbore(
        api, project_id, "15-001-20002", **constants.WELLBORE_PARTIALLY_PLUGGED_MID
    )
    far_well = fixtures.register_wellbore(
        api, project_id, "15-001-20005", **constants.WELLBORE_SEAL_CEMENTED_FAR
    )
    assertions.assert_legacy_wellbore(far_well)
    # A low-scoring wellbore still owes corrective action because it crosses the seal.
    assert far_well["risk_score"] == 9.00
    assert far_well["penetrates_seal"] is True
    assert far_well["corrective_action_status"] == "CA_REQUIRED"

    validate_success(
        api.schedule_corrective_action(
            near_well["id"],
            factories.schedule_corrective_action_payload(
                "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z"
            ),
            fixtures.DEVELOPER,
        ),
        200,
    )
    validate_success(
        api.schedule_corrective_action(
            mid_well["id"],
            factories.schedule_corrective_action_payload(
                "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z"
            ),
            fixtures.DEVELOPER,
        ),
        200,
    )

    # 2026-09-10 through 2026-09-15 touches the first window at its endpoint and
    # runs inside the second, so both rigs are already spoken for.
    refused = api.schedule_corrective_action(
        far_well["id"],
        factories.schedule_corrective_action_payload(
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z"
        ),
        fixtures.DEVELOPER,
    )
    validate_error(refused, ApiErrorId.ERR_CA_RIG_CAPACITY_EXCEEDED.value, 409)

    still_unscheduled = fixtures.refresh_wellbore(api, far_well["id"])
    assert still_unscheduled["corrective_action_status"] == "CA_REQUIRED"
    assert still_unscheduled["ca_window_start"] is None
    assert still_unscheduled["ca_window_end"] is None

    # A window clear of both commitments schedules without contention.
    scheduled = validate_success(
        api.schedule_corrective_action(
            far_well["id"],
            factories.schedule_corrective_action_payload(
                "2026-09-21T00:00:00Z", "2026-09-25T00:00:00Z"
            ),
            fixtures.DEVELOPER,
        ),
        200,
    )
    assert scheduled["corrective_action_status"] == "CA_SCHEDULED"
    assert scheduled["ca_window_start"][:19] == "2026-09-21T00:00:00"
    assert scheduled["ca_window_end"][:19] == "2026-09-25T00:00:00"
    assert scheduled["version"] > far_well["version"]
