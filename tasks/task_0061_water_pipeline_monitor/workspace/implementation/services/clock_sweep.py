"""Clock-advance sweeps (PRD §2.5, §3.1, §3.4): device-offline detection,
reading archive-tier re-evaluation, alert suppression on device offline.
"""
from clock import iso_to_epoch_ms
from db import alerts, devices, readings, stamp_update
from services.audit import write_audit
from services.dma_posture import recompute_dma_posture


HOT_RETENTION_S = 86400
WARM_RETENTION_S = 2592000
OFFLINE_THRESHOLD = 3


def _expected_next_poll_ms(device: dict) -> int:
    """Compute expected next poll epoch ms per PRD §3.4."""
    poll_s = int(device.get("polling_interval_s") or 0)
    if device.get("last_reading_at"):
        baseline = iso_to_epoch_ms(device["last_reading_at"])
    else:
        baseline = iso_to_epoch_ms(device["created_at"])
    return baseline + poll_s * 1000


def _missed_polls(device: dict, clock_now_ms: int) -> int:
    poll_s = int(device.get("polling_interval_s") or 0)
    if poll_s <= 0:
        return 0
    expected_ms = _expected_next_poll_ms(device)
    if clock_now_ms < expected_ms:
        return 0
    # `clock_now >= expected_next_poll`: floor((clock_now - expected)/interval) + 1
    diff_ms = clock_now_ms - expected_ms
    return (diff_ms // (poll_s * 1000)) + 1


def _recompute_archive_tier(reading: dict, clock_now_ms: int) -> None:
    """Monotonically advance reading.archive_tier."""
    cur = reading.get("archive_tier", "HOT")
    if cur == "COLD":
        return
    ingested_ms = iso_to_epoch_ms(reading["ingested_at"])
    age_s = max(0, (clock_now_ms - ingested_ms) // 1000)
    if age_s < HOT_RETENTION_S:
        new_tier = "HOT"
    elif age_s < WARM_RETENTION_S:
        new_tier = "WARM"
    else:
        new_tier = "COLD"
    # Monotonic: HOT -> WARM -> COLD only.
    order = {"HOT": 0, "WARM": 1, "COLD": 2}
    if order[new_tier] > order[cur]:
        reading["archive_tier"] = new_tier


def compute_archive_tier_for(ingested_at_iso: str, clock_now_ms: int) -> str:
    """Compute initial archive tier at ingest time."""
    ingested_ms = iso_to_epoch_ms(ingested_at_iso)
    age_s = max(0, (clock_now_ms - ingested_ms) // 1000)
    if age_s < HOT_RETENTION_S:
        return "HOT"
    if age_s < WARM_RETENTION_S:
        return "WARM"
    return "COLD"


def run_clock_advance_sweeps(network: dict, *, actor_role: str, actor_id: str) -> None:
    """Run device-offline detection, archive tier re-eval, alert suppression."""
    network_id = network["id"]
    clock_now_ms = int(network["clock_epoch_ms"])

    # --- Sweep 1: device-offline detection ---
    devices_to_offline = []
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("status") == "ACTIVE":
            missed = _missed_polls(d, clock_now_ms)
            d["missed_polls_consecutive"] = missed
            if missed >= OFFLINE_THRESHOLD:
                devices_to_offline.append(d)

    for d in devices_to_offline:
        d["status"] = "OFFLINE"
        stamp_update(d)

    # --- Sweep 2: reading archive tier re-evaluation ---
    for r in readings.values():
        # Only readings whose device is in this network.
        dev = devices.get(r.get("device_id"))
        if not dev or dev.get("network_id") != network_id:
            continue
        _recompute_archive_tier(r, clock_now_ms)

    # --- Sweep 3: alert suppression on devices that just went offline ---
    affected_dma_ids = set()
    suppressible_kinds = {"PRESSURE_LOW", "PRESSURE_HIGH", "FLOW_SPIKE"}
    open_statuses = {"OPEN", "ACKNOWLEDGED", "INVESTIGATING"}
    for d in devices_to_offline:
        for a in alerts.values():
            if (
                a.get("trigger_device_id") == d["id"]
                and a.get("status") in open_statuses
                and a.get("alert_kind") in suppressible_kinds
            ):
                a["status"] = "SUPPRESSED"
                a["resolution_note"] = "DEVICE_OFFLINE"
                stamp_update(a)
                write_audit(
                    network_id=network_id,
                    actor_role=actor_role,
                    actor_id=actor_id,
                    action="ALERT_SUPPRESSED",
                    resource_kind="Alert",
                    resource_id=a["id"],
                    detail={"reason": "DEVICE_OFFLINE", "device_id": d["id"]},
                )
                if a.get("dma_id"):
                    affected_dma_ids.add(a["dma_id"])

    # Recompute DMA postures for any DMAs affected by suppression.
    for dma_id in affected_dma_ids:
        recompute_dma_posture(
            dma_id, network_id=network_id, actor_role=actor_role, actor_id=actor_id
        )
