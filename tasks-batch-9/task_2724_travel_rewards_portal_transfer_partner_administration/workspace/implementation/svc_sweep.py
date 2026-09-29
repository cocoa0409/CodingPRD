"""The deterministic sweep: eight ordered clock-driven steps (PRD 2.10)."""

from core import DB, add_hours, clock_dt, clock_iso, find, ordered, parse_dt, touch
from svc_ledger import refresh_account
from svc_notice import make_effective, promote_matured
from svc_transfer import complete_units


def _rows(kind, statuses):
    return ordered(kind, [r for r in DB[kind].values() if r["status"] in statuses])


def run_sweep():
    now = clock_dt()
    counts = {
        "rotations_activated": 0,
        "rotations_expired": 0,
        "bonus_events_opened": 0,
        "bonus_events_closed": 0,
        "notices_made_effective": 0,
        "grandfather_windows_matured": 0,
        "transfers_completed": 0,
        "entitlements_expired": 0,
    }

    # 1. rotations SCHEDULED -> ACTIVE once the clock reaches window_start
    for rotation in _rows("rotations", ("SCHEDULED",)):
        if parse_dt(rotation["window_start"]) <= now:
            rotation["status"] = "ACTIVE"
            rotation["activated_at"] = clock_iso()
            touch(rotation)
            counts["rotations_activated"] += 1

    # 2. rotations ACTIVE -> EXPIRED once the clock reaches window_end
    for rotation in _rows("rotations", ("ACTIVE",)):
        if parse_dt(rotation["window_end"]) <= now:
            rotation["status"] = "EXPIRED"
            rotation["expired_at"] = clock_iso()
            touch(rotation)
            counts["rotations_expired"] += 1

    # 3. bonus events SCHEDULED -> RUNNING, provided the agreement is still ACTIVE
    for event in _rows("bonus_events", ("SCHEDULED",)):
        if parse_dt(event["window_start"]) > now:
            continue
        agreement = find("agreements", event["partner_agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            continue
        event["status"] = "RUNNING"
        event["opened_at"] = clock_iso()
        touch(event)
        counts["bonus_events_opened"] += 1

    # 4. bonus events RUNNING -> CLOSED once the clock is strictly past window_end
    for event in _rows("bonus_events", ("RUNNING",)):
        if parse_dt(event["window_end"]) < now:
            event["status"] = "CLOSED"
            event["closed_at"] = clock_iso()
            touch(event)
            counts["bonus_events_closed"] += 1

    # 5. notices ANNOUNCED -> EFFECTIVE, with the grandfathering re-point
    for notice in _rows("notices", ("ANNOUNCED",)):
        if parse_dt(notice["effective_at"]) <= now:
            make_effective(notice)
            counts["notices_made_effective"] += 1

    # 6. matured grandfather windows promoted
    counts["grandfather_windows_matured"] = promote_matured(now)

    # 7. queued transfers QUEUED -> COMPLETED once the posting instant arrives
    for transfer in _rows("transfer_requests", ("QUEUED",)):
        scheduled = transfer.get("scheduled_post_at")
        if not scheduled or parse_dt(scheduled) > now:
            continue
        agreement = find("agreements", transfer["partner_agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            continue
        account = find("accounts", transfer["account_id"])
        if account is None or account["fraud_posture"] == "LOCKED":
            continue
        transfer["status"] = "COMPLETED"
        transfer["completed_at"] = clock_iso()
        complete_units(transfer, agreement, account)
        touch(transfer)
        refresh_account(account)
        counts["transfers_completed"] += 1

    # 8. entitlements ACTIVE/SUSPENDED -> EXPIRED once expires_at arrives
    for entitlement in _rows("entitlements", ("ACTIVE", "SUSPENDED")):
        if parse_dt(entitlement["expires_at"]) <= now:
            entitlement["status"] = "EXPIRED"
            touch(entitlement)
            counts["entitlements_expired"] += 1

    counts["clock_utc"] = clock_iso()
    return counts
