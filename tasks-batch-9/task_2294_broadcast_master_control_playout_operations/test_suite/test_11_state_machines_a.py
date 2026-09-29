"""State-machine corner tests: transmitter power, channel air status, asset
waivers and the playlist lifecycle up to ON_AIR.

Every test builds its preconditions from scratch through PRD endpoints, starting
from an empty database and the logical clock at its default value.
"""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    assert_bandwidth_conservation,
    assert_regulatory_notification,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Private helpers (this module only)
# ---------------------------------------------------------------------------

def _instant(timestamp: str) -> datetime:
    """Parse an API timestamp at second granularity (PRD §2.10: time is whole seconds)."""
    text = timestamp.replace("Z", "+00:00")
    return (
        datetime.fromisoformat(text)
        .astimezone(timezone.utc)
        .replace(microsecond=0, tzinfo=timezone.utc)
    )


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_instant(actual: str, expected: str, label: str):
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected} at second granularity, got {actual}"
    )


def _notifications(api, plant, params=None):
    """(rows, meta) for the transmitter's regulatory notification catalogue."""
    return validate_paginated(
        api.list_transmitter_notifications(
            plant["transmitter"]["id"], plant["compliance_headers"], params=params
        )
    )


def _commercial_run(asset_id, first_start_utc, durations, first_sequence_number):
    """A contiguous run of COMMERCIAL elements, one per duration."""
    items = []
    cursor = _instant(first_start_utc)
    for offset, duration in enumerate(durations):
        items.append({
            "sequence_number": first_sequence_number + offset,
            "element_kind": "COMMERCIAL",
            "asset_id": asset_id,
            "scheduled_start_utc": _iso(cursor),
            "scheduled_duration_seconds": duration,
        })
        cursor += timedelta(seconds=duration)
    return items


# ===========================================================================
# Transmitter power: the 80-percent filing threshold
# ===========================================================================

def test_reduction_to_exactly_eighty_pct_derates_the_pool_but_files_nothing(api):
    """Exactly 80 percent derates the bit pool and degrades posture yet files no notification.

    PRD §3.1: "The threshold is strict: a reduction to exactly 80 percent creates no
    filing obligation, while 79 percent does."

    PRD §3.1: "publishes a new `derate_factor`, which is 0.75 when `power_pct` is at
    least 50 and 0.50 when it is below 50"

    Design: Corner/state_machines/transmitter_reduction_to_exactly_eighty_pct_creates_no_notification
    """
    plant = fx.setup_base_plant()
    tx_id = plant["transmitter"]["id"]

    reduced = validate_success(api.change_transmitter_power_state(
        tx_id,
        {"target_state": "REDUCED_POWER", "power_pct": 80, "reason": "antenna maintenance"},
        plant["eng_headers"],
    ))
    assert reduced["operational_state"] == "REDUCED_POWER"
    assert reduced["current_power_pct"] == 80
    assert float(reduced["derate_factor"]) == 0.75

    rows, meta = _notifications(api, plant)
    assert meta["total_count"] == 0, "80 percent creates no filing obligation"
    assert rows == []
    assert fx.read_transmitter(tx_id)["notification_pending_count"] == 0

    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 28300
    assert mux["assigned_kbps"] == 22000
    assert mux["available_kbps"] == 6300
    assert mux["starved_channel_count"] == 0
    assert_bandwidth_conservation(mux)

    ch1 = fx.read_channel(plant["ch1"]["id"])
    ch2 = fx.read_channel(plant["ch2"]["id"])
    assert ch1["allocated_bitrate_kbps"] == 16000
    assert ch2["allocated_bitrate_kbps"] == 6000
    assert ch1["posture"] == "DEGRADED"
    assert ch2["posture"] == "DEGRADED"

    restored = validate_success(api.change_transmitter_power_state(
        tx_id, {"target_state": "FULL_POWER"}, plant["eng_headers"],
    ))
    assert restored["operational_state"] == "FULL_POWER"
    assert float(restored["derate_factor"]) == 1.00
    mux_full = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux_full["effective_capacity_kbps"] == 38000
    assert mux_full["available_kbps"] == 16000
    assert fx.read_channel(plant["ch1"]["id"])["posture"] == "NORMAL"
    assert fx.read_channel(plant["ch2"]["id"])["posture"] == "NORMAL"


def test_reduction_to_seventy_nine_pct_files_a_pending_power_reduction(api):
    """One percent below the threshold does raise the filing obligation.

    PRD §3.1: "a reduction to below 80 percent of licensed power creates a
    `POWER_REDUCTION` notification in status `PENDING`, with `triggering_utc` set to
    the logical clock instant of the change, `due_utc` set to 24 hours after that
    instant, and `observed_power_pct` recording the percentage observed at the
    triggering event; the transmitter's `notification_pending_count` rises by one."

    Design: Corner/state_machines/transmitter_reduction_to_exactly_eighty_pct_creates_no_notification
    """
    plant = fx.setup_base_plant()
    tx_id = plant["transmitter"]["id"]

    validate_success(api.change_transmitter_power_state(
        tx_id,
        {"target_state": "REDUCED_POWER", "power_pct": 79, "reason": "antenna maintenance"},
        plant["eng_headers"],
    ))

    rows, meta = _notifications(api, plant, params={"kind": "POWER_REDUCTION"})
    assert meta["total_count"] == 1, "79 percent files exactly one POWER_REDUCTION row"
    row = rows[0]
    assert_regulatory_notification(row)
    assert row["kind"] == "POWER_REDUCTION"
    assert row["status"] == "PENDING"
    assert row["observed_power_pct"] == 79
    _assert_instant(row["triggering_utc"], "2026-08-01T09:00:00Z", "triggering_utc")
    _assert_instant(row["due_utc"], "2026-08-02T09:00:00Z", "due_utc")
    assert fx.read_transmitter(tx_id)["notification_pending_count"] == 1


# ===========================================================================
# Cascade A: derate, capacity, waterfall, posture
# ===========================================================================

def test_cascade_a_starves_only_the_priority_tail_and_suspends_it(api):
    """One power-state call derates the pool, starves the rank-2 channel and suspends it.

    PRD §3.2: "take `total_capacity_kbps`, multiply by the parent transmitter's current
    `derate_factor`, truncate the product downward to a whole kilobit, subtract
    `pilot_reserved_kbps`, and floor the result at 0"

    PRD §3.2: "If the floor does not fit, the channel's `allocation_state` becomes
    `STARVED`, its `allocated_bitrate_kbps` is set to 0, and it is excluded from steps
    three through five entirely."

    PRD §3.3: "First, `posture` is `SUSPENDED` if the channel's `allocation_state` is
    `STARVED` or its transmitter's `operational_state` is `OFF_AIR`."

    Design: Corner/state_machines/cascade_a_hops_one_to_four_starve_the_priority_tail_and_suspend_it
    """
    plant = fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides={"name": "MUX-B", "total_capacity_kbps": 20000,
                       "pilot_reserved_kbps": 500},
        ch1_overrides={"call_sign": "WABC-DT1", "channel_number": "20.1",
                       "resolution_class": "HD_720P",
                       "requested_bitrate_kbps": 6000, "floor_bitrate_kbps": 5000,
                       "priority_rank": 1},
    )
    mux_id = plant["multiplex"]["id"]
    mux = fx.read_multiplex(mux_id, plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 19500

    tail = fx.create_channel(
        plant["eng_headers"], mux_id, mux["version"],
        call_sign="WABC-DT2", channel_number="20.2", service_class="PRIMARY",
        resolution_class="HD_720P", requested_bitrate_kbps=6000,
        floor_bitrate_kbps=5000, priority_rank=2,
    )
    fx.set_air_status(plant, tail["id"], "ON_AIR")

    derated = validate_success(api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "REDUCED_POWER", "power_pct": 40, "reason": "generator failover"},
        plant["eng_headers"],
    ))
    assert float(derated["derate_factor"]) == 0.50
    assert derated["notification_pending_count"] == 1

    rows, meta = _notifications(api, plant, params={"status": "PENDING"})
    assert meta["total_count"] == 1
    assert rows[0]["kind"] == "POWER_REDUCTION"
    assert rows[0]["observed_power_pct"] == 40
    _assert_instant(rows[0]["due_utc"], "2026-08-02T09:00:00Z", "due_utc")

    mux_after = fx.read_multiplex(mux_id, plant["eng_headers"])
    assert mux_after["effective_capacity_kbps"] == 9500
    assert mux_after["assigned_kbps"] == 6000
    assert mux_after["available_kbps"] == 3500
    assert mux_after["starved_channel_count"] == 1
    assert_bandwidth_conservation(mux_after)

    head = fx.read_channel(plant["ch1"]["id"])
    assert head["allocation_state"] == "ACTIVE"
    assert head["allocated_bitrate_kbps"] == 6000
    assert head["posture"] == "DEGRADED"

    starved = fx.read_channel(tail["id"])
    assert starved["allocation_state"] == "STARVED"
    assert starved["allocated_bitrate_kbps"] == 0
    assert starved["posture"] == "SUSPENDED"


# ===========================================================================
# The outage epoch and its notifications
# ===========================================================================

def test_outage_notification_appears_at_exactly_1800_seconds_of_darkness(api):
    """At 1799 seconds of outage nothing is filed; at exactly 1800 the checkpoint files.

    PRD §3.1: "When the clock advances such that a transmitter still in `OFF_AIR` with a
    non-null `outage_started_utc` has been dark for at least 30 minutes, and no `OUTAGE`
    notification exists whose `triggering_utc` equals that `outage_started_utc`, the
    checkpoint creates one — status `PENDING`, `triggering_utc` equal to
    `outage_started_utc`, `due_utc` 24 hours after the new clock instant, and
    `outage_seconds` equal to the elapsed seconds observed at detection"

    PRD §3.1: "every channel on every one of those multiplexes is driven to
    `allocation_state` `STARVED`; each such channel's `posture` becomes `SUSPENDED` and
    its `air_status` becomes `DARK`"

    Design: Corner/state_machines/outage_epoch_creates_notification_at_exactly_1800_seconds_and_a_resumption
    """
    plant = fx.setup_base_plant()

    dark = validate_success(api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "OFF_AIR", "reason": "transmitter fire alarm"},
        plant["eng_headers"],
    ))
    assert dark["operational_state"] == "OFF_AIR"
    assert dark["current_power_pct"] == 0
    assert float(dark["derate_factor"]) == 0.00
    _assert_instant(dark["outage_started_utc"], "2026-08-01T09:00:00Z", "outage_started_utc")

    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 0
    assert mux["starved_channel_count"] == 2
    for channel_id in (plant["ch1"]["id"], plant["ch2"]["id"]):
        channel = fx.read_channel(channel_id)
        assert channel["allocation_state"] == "STARVED"
        assert channel["allocated_bitrate_kbps"] == 0
        assert channel["posture"] == "SUSPENDED"
        assert channel["air_status"] == "DARK"

    fx.set_clock("2026-08-01T09:29:59Z")
    _, meta_early = _notifications(api, plant, params={"kind": "OUTAGE"})
    assert meta_early["total_count"] == 0, "1799 seconds of darkness files nothing"

    fx.set_clock("2026-08-01T09:30:00Z")
    rows, meta = _notifications(api, plant, params={"kind": "OUTAGE"})
    assert meta["total_count"] == 1, "exactly 1800 seconds files one OUTAGE row"
    row = rows[0]
    assert_regulatory_notification(row)
    assert row["kind"] == "OUTAGE"
    assert row["status"] == "PENDING"
    assert row["outage_seconds"] == 1800
    _assert_instant(row["triggering_utc"], "2026-08-01T09:00:00Z", "triggering_utc")
    _assert_instant(row["due_utc"], "2026-08-02T09:30:00Z", "due_utc")


def test_restoration_closes_the_epoch_and_never_duplicates_the_outage_row(api):
    """Leaving OFF_AIR closes the epoch, files a resumption and reuses the one outage row.

    PRD §3.1: "`last_outage_seconds` is written as the whole number of seconds between
    `outage_started_utc` and the current logical instant, that figure is added to
    `cumulative_outage_seconds` — which is the running sum over every closed outage epoch
    on the transmitter — and `outage_started_utc` is cleared to null."

    PRD §3.1: "Exactly one `OUTAGE` row is ever created per outage epoch; the epoch is
    keyed on `outage_started_utc` and a second row for the same epoch is never created."

    PRD §3.1: "Independently, every restoration from `OFF_AIR` creates a `RESUMPTION`
    notification in status `PENDING` with `triggering_utc` at the restoration instant and
    `due_utc` 24 hours later."

    Design: Corner/state_machines/outage_epoch_creates_notification_at_exactly_1800_seconds_and_a_resumption
    """
    plant = fx.setup_base_plant()
    fx.change_power_state(plant, "OFF_AIR", reason="transmitter fire alarm")
    fx.set_clock("2026-08-01T09:30:00Z")

    restored = validate_success(api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "REDUCED_POWER", "power_pct": 60, "reason": "partial restore"},
        plant["eng_headers"],
    ))
    assert restored["operational_state"] == "REDUCED_POWER"
    assert float(restored["derate_factor"]) == 0.75
    assert restored["last_outage_seconds"] == 1800
    assert restored["cumulative_outage_seconds"] == 1800
    assert restored["outage_started_utc"] is None

    _, outage_meta = _notifications(api, plant, params={"kind": "OUTAGE"})
    assert outage_meta["total_count"] == 1, "the epoch keeps its single OUTAGE row"

    resumptions, resumption_meta = _notifications(api, plant, params={"kind": "RESUMPTION"})
    assert resumption_meta["total_count"] == 1
    resumption = resumptions[0]
    assert resumption["kind"] == "RESUMPTION"
    assert resumption["status"] == "PENDING"
    _assert_instant(resumption["triggering_utc"], "2026-08-01T09:30:00Z", "triggering_utc")
    _assert_instant(resumption["due_utc"], "2026-08-02T09:30:00Z", "due_utc")


# ===========================================================================
# Undeclared edges are refused, not treated as no-ops
# ===========================================================================

def test_dark_to_bars_and_tone_is_not_a_declared_air_state_move(api):
    """Bars-and-tone is reachable from ON_AIR only, never straight from DARK.

    PRD §3.3: "The reachable moves are exactly these: `DARK` to `ON_AIR`; `ON_AIR` to
    `BARS_AND_TONE`; `BARS_AND_TONE` back to `ON_AIR`; `ON_AIR` to `EAS_OVERRIDE` and
    `EAS_OVERRIDE` back to `ON_AIR`, both of which are reached only by the
    emergency-override cascade; `ON_AIR` to `DARK`; and `BARS_AND_TONE` to `DARK`."

    PRD §3.3: "A `target_air_status` that is not reachable from the channel's present
    `air_status` is refused with `ERR_CHANNEL_INVALID_AIR_STATE`"

    Design: Corner/state_machines/undeclared_transmitter_and_channel_transitions_are_rejected
    """
    plant = fx.setup_base_plant()
    before = fx.read_channel(plant["ch1"]["id"])
    assert before["air_status"] == "DARK"

    validate_error(
        api.change_channel_air_state(
            plant["ch1"]["id"], {"target_air_status": "BARS_AND_TONE"},
            plant["mco_headers"],
        ),
        "ERR_CHANNEL_INVALID_AIR_STATE",
    )

    after = fx.read_channel(plant["ch1"]["id"])
    assert after["air_status"] == "DARK"
    assert after["version"] == before["version"], "a refused move mutates nothing"


def test_eas_override_is_never_reachable_through_the_air_state_endpoint(api):
    """EAS_OVERRIDE belongs to the override cascade, not to the air-state endpoint.

    PRD §3.3: "**`EAS_OVERRIDE` is never reachable through the air-state endpoint at
    all** — asking for it there is refused with the same code even when the channel is
    `ON_AIR`, because that state belongs exclusively to the override cascade of §3.8."

    Design: Corner/state_machines/undeclared_transmitter_and_channel_transitions_are_rejected
    """
    plant = fx.setup_base_plant()
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    before = fx.read_channel(plant["ch1"]["id"])

    validate_error(
        api.change_channel_air_state(
            plant["ch1"]["id"], {"target_air_status": "EAS_OVERRIDE"},
            plant["mco_headers"],
        ),
        "ERR_CHANNEL_INVALID_AIR_STATE",
    )

    after = fx.read_channel(plant["ch1"]["id"])
    assert after["air_status"] == "ON_AIR"
    assert after["version"] == before["version"]


def test_full_power_to_full_power_is_refused_rather_than_idempotent(api):
    """Re-asserting the current transmitter state is not a declared transition.

    PRD §3.1: "Notably, `FULL_POWER` to `FULL_POWER` is not a declared transition and is
    refused."

    Design: Corner/state_machines/undeclared_transmitter_and_channel_transitions_are_rejected
    """
    plant = fx.setup_base_plant()
    before = fx.read_transmitter(plant["transmitter"]["id"])
    assert before["operational_state"] == "FULL_POWER"

    validate_error(
        api.change_transmitter_power_state(
            plant["transmitter"]["id"], {"target_state": "FULL_POWER"},
            plant["eng_headers"],
        ),
        "ERR_TRANSMITTER_INVALID_STATE",
    )

    after = fx.read_transmitter(plant["transmitter"]["id"])
    assert after["operational_state"] == "FULL_POWER"
    assert after["current_power_pct"] == 100
    assert after["version"] == before["version"]


# ===========================================================================
# The channel air-status cycle and its critical-fault gate
# ===========================================================================

def test_air_status_cycles_dark_on_air_bars_and_back_versioning_each_hop(api):
    """A channel walks DARK to ON_AIR to BARS_AND_TONE to ON_AIR to DARK, one version per hop.

    PRD §3.3: "The reachable moves are exactly these: `DARK` to `ON_AIR`; `ON_AIR` to
    `BARS_AND_TONE`; `BARS_AND_TONE` back to `ON_AIR`; `ON_AIR` to `EAS_OVERRIDE` and
    `EAS_OVERRIDE` back to `ON_AIR`, both of which are reached only by the
    emergency-override cascade; `ON_AIR` to `DARK`; and `BARS_AND_TONE` to `DARK`."

    PRD §3.3: "Every air-state change recomputes `posture` and increments the channel's
    `version` by one."

    Design: Corner/state_machines/channel_air_status_cycle_dark_on_air_bars_and_back_with_a_critical_gate
    """
    plant = fx.setup_base_plant()
    channel_id = plant["ch1"]["id"]

    start = fx.read_channel(channel_id)
    assert start["air_status"] == "DARK"
    expected_version = start["version"]

    for target in ("ON_AIR", "BARS_AND_TONE", "ON_AIR", "DARK"):
        hop = validate_success(api.change_channel_air_state(
            channel_id, {"target_air_status": target}, plant["mco_headers"],
        ))
        expected_version += 1
        assert hop["air_status"] == target
        assert hop["version"] == expected_version, (
            f"the hop to {target} must add exactly one version"
        )
        assert hop["posture"] == "NORMAL", (
            "an undisturbed, fully allocated channel stays NORMAL through the cycle"
        )

    final = fx.read_channel(channel_id)
    assert final["air_status"] == "DARK"
    assert final["version"] == expected_version


def test_an_open_critical_fault_gates_the_channel_off_the_air(api):
    """A critical fault forces DEGRADED_CRITICAL and blocks going to air until it closes.

    PRD §3.3: "Third, `posture` is `DEGRADED_CRITICAL` if the channel has at least one
    open technical fault of severity `CRITICAL`."

    PRD §3.3: "The same four preconditions apply when returning from `BARS_AND_TONE`
    to `ON_AIR`, and that return carries one extra condition the initial lighting does
    not: there must be no technical fault on the channel whose `severity` is `CRITICAL`
    and whose `state` is `DETECTED`, `ACKNOWLEDGED` or `ESCALATED`, otherwise the
    restoration is refused with `ERR_CRITICAL_FAULT_OPEN`. A critical fault therefore
    pins a channel to bars-and-tone until it is mitigated, while it does not by itself
    prevent a dark channel being brought up — the asymmetry between the two ON_AIR-bound
    transitions is deliberate."

    PRD §3.7: "A fault is open while its `state` is `DETECTED`, `ACKNOWLEDGED` or
    `ESCALATED`, and closed once it reaches `MITIGATED`, `RESOLVED` or `AUTO_CLEARED`."

    Design: Corner/state_machines/channel_air_status_cycle_dark_on_air_bars_and_back_with_a_critical_gate
    """
    plant = fx.setup_base_plant()
    channel_id = plant["ch1"]["id"]

    # The gate belongs to the BARS_AND_TONE -> ON_AIR return, not to the initial
    # lighting of a dark channel, so the channel is parked on bars first.
    fx.set_air_status(plant, channel_id, "ON_AIR")
    assert fx.set_air_status(
        plant, channel_id, "BARS_AND_TONE")["air_status"] == "BARS_AND_TONE"

    fault = fx.report_channel_fault(
        plant, "ENCODER_FAILURE", "CRITICAL", "2026-08-01T09:00:00Z",
    )
    assert fault["severity"] == "CRITICAL"
    assert fault["state"] == "DETECTED"

    gated = fx.read_channel(channel_id)
    assert gated["open_fault_count"] == 1
    assert gated["posture"] == "DEGRADED_CRITICAL"

    validate_error(
        api.change_channel_air_state(
            channel_id, {"target_air_status": "ON_AIR"}, plant["mco_headers"],
        ),
        "ERR_CRITICAL_FAULT_OPEN",
    )
    assert fx.read_channel(channel_id)["air_status"] == "BARS_AND_TONE"

    fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    still_open = fx.read_channel(channel_id)
    assert still_open["open_fault_count"] == 1
    assert still_open["posture"] == "DEGRADED_CRITICAL"
    validate_error(
        api.change_channel_air_state(
            channel_id, {"target_air_status": "ON_AIR"}, plant["mco_headers"],
        ),
        "ERR_CRITICAL_FAULT_OPEN",
    )

    mitigated = fx.advance_fault(
        plant, fault["id"], "MITIGATED", mitigation_code="RESTART_ENCODER",
    )
    assert mitigated["state"] == "MITIGATED"
    cleared = fx.read_channel(channel_id)
    assert cleared["open_fault_count"] == 0
    assert cleared["posture"] == "NORMAL"

    lit = validate_success(api.change_channel_air_state(
        channel_id, {"target_air_status": "ON_AIR"}, plant["mco_headers"],
    ))
    assert lit["air_status"] == "ON_AIR"
    assert lit["posture"] == "NORMAL"


# ===========================================================================
# The waiver path back onto the air
# ===========================================================================

def _failed_waiver_asset(plant):
    """A QC_FAILED asset whose governing ingest score is exactly 40.

    Three distinct defect codes cost 12 + 10 + 8 = 30 points and a 20-second duration
    discrepancy costs the capped 30, so the ingest score is 100 - 30 - 30 = 40, which is
    below 70 and therefore a FAIL. None of the codes is a non-negotiable defect, the
    loudness reading sits exactly on target and the delivered resolution matches the
    requirement, so the score alone drives the verdict.
    """
    return fx.setup_qc_failed_asset(
        plant, 1800,
        defect_codes=["LOUDNESS_OUT_OF_SPEC", "VIDEO_ARTIFACT", "CAPTION_MISTIMED"],
        delivery_overrides={"measured_duration_seconds": 1780,
                            "audio_loudness_lkfs": -24.0},
        qc_overrides={"measured_duration_seconds": 1780},
    )


def test_a_nineteen_character_justification_cannot_waive_the_failure(api):
    """One character short of the floor is refused and the asset stays failed.

    PRD §3.4: "The `waiver_justification` must be at least 20 characters — **exactly 20
    is accepted, 19 is not** — otherwise `ERR_WAIVER_JUSTIFICATION_REQUIRED`."

    Design: Corner/state_machines/asset_waiver_cycle_at_exactly_score_forty_reopens_the_air_path
    """
    plant = fx.bootstrap_operators()
    asset = _failed_waiver_asset(plant)
    assert asset["status"] == "QC_FAILED"
    assert asset["technical_score_ingest"] == 40
    assert asset["qc_verdict"] == "FAIL"

    justification = "Cleared for air OK."
    assert len(justification) == 19

    validate_error(
        api.sign_qc_waiver(
            asset["id"],
            {"waived_by_operator_id": plant["pd"]["id"],
             "waiver_justification": justification},
            plant["pd_headers"],
        ),
        "ERR_WAIVER_JUSTIFICATION_REQUIRED",
    )

    unchanged = fx.read_asset(asset["id"], plant["qc_headers"])
    assert unchanged["status"] == "QC_FAILED"
    assert unchanged.get("waiver_justification") is None
    assert unchanged.get("waived_by_operator_id") is None
    assert unchanged["version"] == asset["version"]


def test_a_twenty_character_justification_waives_a_score_of_exactly_forty(api):
    """At the two floors exactly — 20 characters and a score of 40 — the waiver is granted.

    PRD §3.4: "The governing non-superseded ingest score in `technical_score_ingest` must
    be at least 40 — **exactly 40 is waivable, 39 is not** — otherwise
    `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    PRD §3.4: "A granted waiver writes `waived_by_operator_id` and
    `waiver_justification`, moves the asset to `QC_WAIVED`"

    Design: Corner/state_machines/asset_waiver_cycle_at_exactly_score_forty_reopens_the_air_path
    """
    plant = fx.bootstrap_operators()
    asset = _failed_waiver_asset(plant)
    assert asset["technical_score_ingest"] == 40

    justification = "Cleared for air: OK."
    assert len(justification) == 20

    waived = validate_success(api.sign_qc_waiver(
        asset["id"],
        {"waived_by_operator_id": plant["pd"]["id"],
         "waiver_justification": justification},
        plant["pd_headers"],
    ))
    assert waived["status"] == "QC_WAIVED"
    assert waived["waived_by_operator_id"] == plant["pd"]["id"]
    assert waived["waiver_justification"] == justification
    assert waived["technical_score_ingest"] == 40, "the waiver does not rescore the media"


def test_an_air_check_report_on_a_waived_asset_leaves_its_status_alone(api):
    """The air-check basis is admitted from QC_WAIVED and never rewrites the status.

    PRD §3.4: "an air-check-basis report requires the asset to be in `QC_PASSED` or
    `QC_WAIVED`"

    PRD §3.4: "its score is written to `technical_score_aircheck` and it never changes the
    asset's `status`"

    PRD §3.4: "Submitting a report supersedes any earlier report of the same `basis` on
    that asset by setting the earlier report's `superseded` to true."

    Design: Corner/state_machines/asset_waiver_cycle_at_exactly_score_forty_reopens_the_air_path
    """
    plant = fx.bootstrap_operators()
    asset = _failed_waiver_asset(plant)
    waived = fx.sign_waiver(plant, asset["id"],
                            waiver_justification="Cleared for air: OK.")
    assert waived["status"] == "QC_WAIVED"

    air_check = fx.submit_qc(
        plant, asset["id"], waived["version"],
        basis="AIR_CHECK", defect_codes=[], measured_duration_seconds=1800,
    )
    assert air_check["basis"] == "AIR_CHECK"
    assert air_check["fault_penalty_points"] == 0
    assert air_check["defect_penalty_points"] == 0
    assert air_check["duration_penalty_points"] == 0
    assert air_check["technical_score"] == 100
    assert air_check["verdict"] == "PASS"
    assert air_check["superseded"] is False

    after = fx.read_asset(asset["id"], plant["qc_headers"])
    assert after["status"] == "QC_WAIVED", "an air-check report never moves the status"
    assert after["technical_score_aircheck"] == 100
    assert after["technical_score_ingest"] == 40

    reports, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"], params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 2, "the ingest report survives alongside the air check"
    by_basis = {report["basis"]: report for report in reports}
    assert set(by_basis) == {"INGEST", "AIR_CHECK"}
    assert by_basis["INGEST"]["superseded"] is False, (
        "a report of a different basis is not superseded"
    )
    assert by_basis["INGEST"]["technical_score"] == 40


# ===========================================================================
# The four gates that stand between IMPORTED and VALIDATED
# ===========================================================================

def _day_payload(plant, items, **overrides):
    """An ingest body for the pinned one-hour window booked at noon."""
    payload = {
        "channel_id": plant["ch1"]["id"],
        "broadcast_day": "2026-08-01",
        "schedule_start_utc": "2026-08-01T12:00:00Z",
        "window_duration_seconds": 3600,
        "items": items,
    }
    payload.update(overrides)
    return payload


def test_a_day_without_a_single_program_element_never_validates(api):
    """Commercials alone are not a broadcast day, however tidy the timeline.

    PRD §3.5: "There must be at least one item and at least one item whose
    `element_kind` is `PROGRAM`, otherwise `ERR_PLAYLIST_NO_PROGRAM_CONTENT` — a list made
    entirely of commercials, promos and filler is not a broadcast day."

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    spot = fx.setup_qc_passed_asset(plant, 120)

    playlist = validate_success(api.ingest_playlist(
        _day_payload(plant, _commercial_run(
            spot["id"], "2026-08-01T12:00:00Z", [120, 120], 1)),
        plant["traffic_headers"],
    ), 201)
    assert playlist["status"] == "IMPORTED"
    assert playlist["item_count"] == 2
    assert playlist["blocked_item_count"] == 0

    validate_error(
        api.change_playlist_state(
            playlist["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
        ),
        "ERR_PLAYLIST_NO_PROGRAM_CONTENT",
    )
    assert fx.read_playlist(playlist["id"])["status"] == "IMPORTED"


def test_a_blocked_element_keeps_the_day_out_of_validated(api):
    """A single uncleared element holds the whole day back.

    PRD §3.5: "And `blocked_item_count` must be exactly 0, otherwise
    `ERR_UNCLEARED_CONTENT_ON_AIR`."

    PRD §3.5: "it is created `BLOCKED` when its asset is `RETRACTED`, `EXPIRED` or
    `QC_FAILED`"

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 1800)
    failed = fx.setup_qc_failed_asset(plant, 1800)
    assert failed["status"] == "QC_FAILED"

    playlist = validate_success(api.ingest_playlist(
        _day_payload(plant, [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": programme["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 1800},
            {"sequence_number": 2, "element_kind": "PROGRAM",
             "asset_id": failed["id"],
             "scheduled_start_utc": "2026-08-01T12:30:00Z",
             "scheduled_duration_seconds": 1800},
        ]),
        plant["traffic_headers"],
    ), 201)
    assert playlist["blocked_item_count"] == 1

    validate_error(
        api.change_playlist_state(
            playlist["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
        ),
        "ERR_UNCLEARED_CONTENT_ON_AIR",
    )
    assert fx.read_playlist(playlist["id"])["status"] == "IMPORTED"


def test_element_one_must_begin_exactly_at_the_booked_schedule_start(api):
    """A day that starts one second late is a gap, not a rounding detail.

    PRD §3.5: "If the first item's `scheduled_start_utc` is not exactly the playlist's
    `schedule_start_utc`, the pass fails with `ERR_SCHEDULE_GAP_DETECTED`."

    PRD §3.5: "The integrity pass is run on ingest, on every traffic revision, on every
    makegood placement, on every substitution, and again when the playlist is driven to
    `VALIDATED`."

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 3600)

    validate_error(
        api.ingest_playlist(
            _day_payload(plant, [
                {"sequence_number": 1, "element_kind": "PROGRAM",
                 "asset_id": programme["id"],
                 "scheduled_start_utc": "2026-08-01T12:00:01Z",
                 "scheduled_duration_seconds": 3600},
            ]),
            plant["traffic_headers"],
        ),
        "ERR_SCHEDULE_GAP_DETECTED",
    )

    _, meta = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["traffic_headers"])
    )
    assert meta["total_count"] == 0, "a refused ingest leaves no playlist behind"


def test_a_five_second_hole_between_two_elements_is_a_gap(api):
    """Adjacency is mandatory, so a five-second hole is refused as a gap.

    PRD §3.5: "if the next element's `scheduled_start_utc` is *after* that end there is a
    hole and the pass fails with `ERR_SCHEDULE_GAP_DETECTED` — **a one-second hole is a
    gap**"

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 1800)

    validate_error(
        api.ingest_playlist(
            _day_payload(plant, [
                {"sequence_number": 1, "element_kind": "PROGRAM",
                 "asset_id": programme["id"],
                 "scheduled_start_utc": "2026-08-01T12:00:00Z",
                 "scheduled_duration_seconds": 1800},
                {"sequence_number": 2, "element_kind": "PROGRAM",
                 "asset_id": programme["id"],
                 "scheduled_start_utc": "2026-08-01T12:30:05Z",
                 "scheduled_duration_seconds": 1795},
            ]),
            plant["traffic_headers"],
        ),
        "ERR_SCHEDULE_GAP_DETECTED",
    )


def test_a_one_second_collision_between_two_elements_is_an_overlap(api):
    """An element that starts one second before its predecessor ends collides.

    PRD §3.5: "and if it is *before* that end the elements collide and the pass fails with
    `ERR_SCHEDULE_OVERLAP_DETECTED`"

    PRD §3.5: "**A difference of exactly zero seconds is contiguous and legal**; touching
    elements are the normal case."

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 1800)

    validate_error(
        api.ingest_playlist(
            _day_payload(plant, [
                {"sequence_number": 1, "element_kind": "PROGRAM",
                 "asset_id": programme["id"],
                 "scheduled_start_utc": "2026-08-01T12:00:00Z",
                 "scheduled_duration_seconds": 1800},
                {"sequence_number": 2, "element_kind": "PROGRAM",
                 "asset_id": programme["id"],
                 "scheduled_start_utc": "2026-08-01T12:29:59Z",
                 "scheduled_duration_seconds": 1801},
            ]),
            plant["traffic_headers"],
        ),
        "ERR_SCHEDULE_OVERLAP_DETECTED",
    )

    contiguous = validate_success(api.ingest_playlist(
        _day_payload(plant, [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": programme["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 1800},
            {"sequence_number": 2, "element_kind": "PROGRAM",
             "asset_id": programme["id"],
             "scheduled_start_utc": "2026-08-01T12:30:00Z",
             "scheduled_duration_seconds": 1800},
        ]),
        plant["traffic_headers"],
    ), 201)
    assert contiguous["status"] == "IMPORTED"
    assert contiguous["scheduled_total_seconds"] == 3600
    validated = validate_success(api.change_playlist_state(
        contiguous["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
    ))
    assert validated["status"] == "VALIDATED"


def test_nine_hundred_sixty_seconds_of_spots_in_one_hour_is_the_last_legal_load(api):
    """Exactly 960 commercial seconds in hour zero validates; 961 is refused.

    PRD §3.5: "No hour may carry **more than 960 seconds — sixteen minutes — of
    commercial elements; exactly 960 is accepted and 961 is refused** with
    `ERR_COMMERCIAL_INVENTORY_EXCEEDED`."

    PRD §3.5: "Each qualifying element is attributed to **exactly one hour, chosen by its
    `scheduled_start_utc`, even when the element straddles the hour boundary**"

    Design: Corner/state_machines/playlist_validation_preconditions_are_all_enforced_before_validated
    """
    plant = fx.setup_base_plant()
    spot = fx.setup_qc_passed_asset(plant, 120)
    tail = fx.setup_qc_passed_asset(plant, 2640)

    at_ceiling = validate_success(api.ingest_playlist(
        _day_payload(plant, _commercial_run(
            spot["id"], "2026-08-01T12:00:00Z", [120] * 8, 1) + [
            {"sequence_number": 9, "element_kind": "PROGRAM",
             "asset_id": tail["id"],
             "scheduled_start_utc": "2026-08-01T12:16:00Z",
             "scheduled_duration_seconds": 2640},
        ]),
        plant["traffic_headers"],
    ), 201)
    assert at_ceiling["commercial_seconds_by_hour"] == {"0": 960}
    assert at_ceiling["scheduled_total_seconds"] == 3600

    validated = validate_success(api.change_playlist_state(
        at_ceiling["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
    ))
    assert validated["status"] == "VALIDATED"
    assert validated["commercial_seconds_by_hour"] == {"0": 960}

    over_ceiling_items = _commercial_run(
        spot["id"], "2026-08-01T13:00:00Z", [120] * 7 + [121], 1) + [
        {"sequence_number": 9, "element_kind": "PROGRAM",
         "asset_id": tail["id"],
         "scheduled_start_utc": "2026-08-01T13:16:01Z",
         "scheduled_duration_seconds": 2639},
    ]
    ingest_response = api.ingest_playlist(
        _day_payload(plant, over_ceiling_items,
                     broadcast_day="2026-08-02",
                     schedule_start_utc="2026-08-01T13:00:00Z"),
        plant["traffic_headers"],
    )
    if ingest_response.status_code >= 400:
        validate_error(ingest_response, "ERR_COMMERCIAL_INVENTORY_EXCEEDED")
    else:
        over = validate_success(ingest_response, 201)
        assert over["commercial_seconds_by_hour"] == {"0": 961}
        validate_error(
            api.change_playlist_state(
                over["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
            ),
            "ERR_COMMERCIAL_INVENTORY_EXCEEDED",
        )
        assert fx.read_playlist(over["id"])["status"] == "IMPORTED"


# ===========================================================================
# Arming: the projected variance band
# ===========================================================================

def _variance_day(plant, promo_asset_id, programme_asset_id, promo_seconds):
    """A two-element day of 1800 + promo_seconds against an 1800-second window."""
    return _day_payload(
        plant,
        [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": programme_asset_id,
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 1800},
            {"sequence_number": 2, "element_kind": "PROMO",
             "asset_id": promo_asset_id,
             "scheduled_start_utc": "2026-08-01T12:30:00Z",
             "scheduled_duration_seconds": promo_seconds},
        ],
        window_duration_seconds=1800,
    )


def test_a_projected_overrun_of_exactly_thirty_seconds_still_arms(api):
    """Thirty seconds long is inside the arming band.

    PRD §3.5: "the absolute value of `projected_end_variance_seconds` must not exceed 30
    seconds — **exactly plus or minus 30 seconds arms successfully and 31 does not** —
    otherwise `ERR_ARM_VARIANCE_EXCEEDED`"

    PRD §3.5: "A successful arm writes `armed_at_utc` at the current logical time and
    increments `version`."

    Design: Corner/state_machines/arm_variance_is_permitted_at_exactly_thirty_seconds_and_refused_at_thirty_one
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 1800)
    promo = fx.setup_qc_passed_asset(plant, 30)

    playlist = validate_success(api.ingest_playlist(
        _variance_day(plant, promo["id"], programme["id"], 30),
        plant["traffic_headers"],
    ), 201)
    assert playlist["scheduled_total_seconds"] == 1830
    assert playlist["projected_end_variance_seconds"] == 30

    validated = validate_success(api.change_playlist_state(
        playlist["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
    ))
    assert validated["status"] == "VALIDATED"
    assert validated["projected_end_variance_seconds"] == 30

    armed = validate_success(api.change_playlist_state(
        playlist["id"], {"target_status": "ARMED"}, plant["pd_headers"],
    ))
    assert armed["status"] == "ARMED"
    assert armed["projected_end_variance_seconds"] == 30
    assert armed["version"] == validated["version"] + 1
    _assert_instant(armed["armed_at_utc"], "2026-08-01T09:00:00Z", "armed_at_utc")


def test_a_projected_overrun_of_thirty_one_seconds_refuses_the_arm(api):
    """One second outside the band leaves the day validated but unarmed.

    PRD §3.5: "the absolute value of `projected_end_variance_seconds` must not exceed 30
    seconds — **exactly plus or minus 30 seconds arms successfully and 31 does not** —
    otherwise `ERR_ARM_VARIANCE_EXCEEDED`"

    PRD §3.5: "Note that arming is gated on the *projected* figure, never the as-run one."

    Design: Corner/state_machines/arm_variance_is_permitted_at_exactly_thirty_seconds_and_refused_at_thirty_one
    """
    plant = fx.setup_base_plant()
    programme = fx.setup_qc_passed_asset(plant, 1800)
    promo = fx.setup_qc_passed_asset(plant, 31)

    playlist = validate_success(api.ingest_playlist(
        _variance_day(plant, promo["id"], programme["id"], 31),
        plant["traffic_headers"],
    ), 201)
    assert playlist["projected_end_variance_seconds"] == 31

    validated = validate_success(api.change_playlist_state(
        playlist["id"], {"target_status": "VALIDATED"}, plant["pd_headers"],
    ))
    assert validated["status"] == "VALIDATED"

    validate_error(
        api.change_playlist_state(
            playlist["id"], {"target_status": "ARMED"}, plant["pd_headers"],
        ),
        "ERR_ARM_VARIANCE_EXCEEDED",
    )

    after = fx.read_playlist(playlist["id"])
    assert after["status"] == "VALIDATED", "a refused arm leaves the day validated"
    assert after.get("armed_at_utc") is None
    assert after["version"] == validated["version"]


# ===========================================================================
# Taking a day to air: a lit channel, the preroll window, one day at a time
# ===========================================================================

def test_an_armed_day_cannot_go_to_air_over_a_dark_channel(api):
    """Automation never takes a day over a channel that is not itself on the air.

    PRD §3.5: "the channel's own `air_status` must already be `ON_AIR`, otherwise
    `ERR_CHANNEL_NOT_ON_AIR`"

    Design: Corner/state_machines/on_air_requires_the_preroll_window_and_channel_exclusivity
    """
    scn = fx.setup_playlist_scenario()
    playlist_id = scn["playlist"]["id"]
    fx.validate_playlist(scn)
    armed = fx.arm_playlist(scn)
    assert armed["status"] == "ARMED"
    assert fx.read_channel(scn["ch1"]["id"])["air_status"] == "DARK"

    fx.set_clock("2026-08-01T11:55:00Z")
    validate_error(
        api.change_playlist_state(
            playlist_id, {"target_status": "ON_AIR"}, scn["pd_headers"],
        ),
        "ERR_CHANNEL_NOT_ON_AIR",
    )
    assert fx.read_playlist(playlist_id)["status"] == "ARMED"


def test_the_preroll_window_opens_at_exactly_five_minutes_before_the_booked_start(api):
    """One second before the preroll window the take is refused; on the boundary it lands.

    PRD §3.5: "the logical clock must have reached at least the playlist's
    `schedule_start_utc` less a 300-second preroll tolerance, so **at exactly five minutes
    before the booked start the transition is permitted** and any earlier attempt is
    refused with `ERR_PLAYLIST_AIR_TOO_EARLY`"

    Design: Corner/state_machines/on_air_requires_the_preroll_window_and_channel_exclusivity
    """
    scn = fx.setup_playlist_scenario()
    playlist_id = scn["playlist"]["id"]
    fx.validate_playlist(scn)
    fx.set_air_status(scn, scn["ch1"]["id"], "ON_AIR")
    fx.arm_playlist(scn)

    fx.set_clock("2026-08-01T11:54:59Z")
    validate_error(
        api.change_playlist_state(
            playlist_id, {"target_status": "ON_AIR"}, scn["pd_headers"],
        ),
        "ERR_PLAYLIST_AIR_TOO_EARLY",
    )
    assert fx.read_playlist(playlist_id)["status"] == "ARMED"

    fx.set_clock("2026-08-01T11:55:00Z")
    on_air = validate_success(api.change_playlist_state(
        playlist_id, {"target_status": "ON_AIR"}, scn["pd_headers"],
    ))
    assert on_air["status"] == "ON_AIR"


def test_a_channel_carries_only_one_on_air_playlist_at_a_time(api):
    """A second armed day is refused while the first is still carrying the channel.

    PRD §3.5: "and no other playlist on the same channel may already be `ON_AIR`,
    otherwise `ERR_CHANNEL_PLAYLIST_ALREADY_ON_AIR`"

    Design: Corner/state_machines/on_air_requires_the_preroll_window_and_channel_exclusivity
    """
    scn = fx.setup_on_air_playlist()
    first_id = scn["playlist"]["id"]
    assert fx.read_playlist(first_id)["status"] == "ON_AIR"

    second = validate_success(api.ingest_playlist(
        {
            "channel_id": scn["ch1"]["id"],
            "broadcast_day": "2026-08-02",
            "schedule_start_utc": "2026-08-01T13:00:00Z",
            "window_duration_seconds": 3600,
            "items": [
                {"sequence_number": 1, "element_kind": "PROGRAM",
                 "asset_id": scn["assets"]["prog1"]["id"],
                 "scheduled_start_utc": "2026-08-01T13:00:00Z",
                 "scheduled_duration_seconds": 3600},
            ],
        },
        scn["traffic_headers"],
    ), 201)
    fx.drive_playlist(scn, second["id"], "VALIDATED")
    armed = fx.drive_playlist(scn, second["id"], "ARMED")
    assert armed["status"] == "ARMED"

    fx.set_clock("2026-08-01T12:55:00Z")
    validate_error(
        api.change_playlist_state(
            second["id"], {"target_status": "ON_AIR"}, scn["pd_headers"],
        ),
        "ERR_CHANNEL_PLAYLIST_ALREADY_ON_AIR",
    )

    assert fx.read_playlist(second["id"])["status"] == "ARMED"
    assert fx.read_playlist(first_id)["status"] == "ON_AIR"
    on_air_rows, on_air_meta = validate_paginated(
        api.list_channel_playlists(
            scn["ch1"]["id"], scn["traffic_headers"], params={"status": "ON_AIR"}
        )
    )
    assert on_air_meta["total_count"] == 1
    assert on_air_rows[0]["id"] == first_id
