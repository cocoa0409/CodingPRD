"""Serialize internal records to API output shape.

Strips internal bookkeeping (_seq). WalletTxn and GateEvent are append-only
event logs with a reduced field set: only id + created_at among system fields
(PRD §2.4) — they carry no updated_at and no version.
"""

# Public field order per entity. System fields appended by the helpers.
_FESTIVAL_FIELDS = [
    "name", "start_date", "end_date", "total_days", "operational_posture",
    "current_festival_day", "max_reentries", "wristband_cashout_pct",
    "vendor_commission_pct", "total_wallet_liability", "total_refund_liability",
]
_ZONE_FIELDS = ["festival_id", "code", "slot_capacity", "allocated_count"]
_STAGE_FIELDS = ["festival_id", "name", "changeover_minutes"]
_PARKING_FIELDS = ["festival_id", "name", "capacity", "sold_count", "price_per_pass"]
_CAMPING_FIELDS = ["festival_id", "name", "capacity", "sold_count", "price_per_night"]
_TICKET_FIELDS = [
    "festival_id", "wristband_id", "ticket_type", "day_count", "face_value",
    "status", "purchaser_email",
]
_WRISTBAND_FIELDS = [
    "festival_id", "rfid_uid", "lifecycle_status", "presence_status", "balance",
    "entry_count", "reentry_used",
]
_WALLET_TXN_FIELDS = [
    "wristband_id", "festival_id", "kind", "amount", "booth_zone_id",
    "vendor_application_id",
]
_VENDOR_APP_FIELDS = [
    "festival_id", "vendor_id", "booth_zone_id", "booth_tier", "day_count",
    "power_addon", "status", "booth_fee", "fee_paid",
]
_VENDOR_FIELDS = ["company_name", "contact_email", "payout_total"]
_PERFORMANCE_FIELDS = [
    "stage_id", "festival_id", "artist_name", "starts_at", "ends_at", "status",
]
_ADDON_FIELDS = [
    "festival_id", "ticket_id", "kind", "parking_lot_id", "camping_area_id",
    "nights", "price", "status",
]
_GATE_EVENT_FIELDS = [
    "festival_id", "wristband_id", "direction", "outcome", "deny_reason",
]
_REFUND_FIELDS = [
    "festival_id", "ticket_id", "refund_kind", "amount", "fee_withheld", "status",
]
_INCIDENT_FIELDS = [
    "festival_id", "incident_type", "linked_wristband_id", "severity", "status",
    "notes",
]


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _log_common(rec):
    return {"id": rec["id"], "created_at": rec["created_at"]}


def _pick(rec, fields):
    return {f: rec.get(f) for f in fields}


def festival(rec):
    return {**_pick(rec, _FESTIVAL_FIELDS), **_common(rec)}


def zone(rec):
    return {**_pick(rec, _ZONE_FIELDS), **_common(rec)}


def stage(rec):
    return {**_pick(rec, _STAGE_FIELDS), **_common(rec)}


def parking_lot(rec):
    return {**_pick(rec, _PARKING_FIELDS), **_common(rec)}


def camping_area(rec):
    return {**_pick(rec, _CAMPING_FIELDS), **_common(rec)}


def ticket(rec):
    return {**_pick(rec, _TICKET_FIELDS), **_common(rec)}


def wristband(rec):
    return {**_pick(rec, _WRISTBAND_FIELDS), **_common(rec)}


def wallet_txn(rec):
    return {**_pick(rec, _WALLET_TXN_FIELDS), **_log_common(rec)}


def vendor_application(rec):
    return {**_pick(rec, _VENDOR_APP_FIELDS), **_common(rec)}


def vendor(rec):
    return {**_pick(rec, _VENDOR_FIELDS), **_common(rec)}


def performance(rec):
    return {**_pick(rec, _PERFORMANCE_FIELDS), **_common(rec)}


def addon(rec):
    return {**_pick(rec, _ADDON_FIELDS), **_common(rec)}


def gate_event(rec):
    return {**_pick(rec, _GATE_EVENT_FIELDS), **_log_common(rec)}


def refund(rec):
    return {**_pick(rec, _REFUND_FIELDS), **_common(rec)}


def incident(rec):
    return {**_pick(rec, _INCIDENT_FIELDS), **_common(rec)}
