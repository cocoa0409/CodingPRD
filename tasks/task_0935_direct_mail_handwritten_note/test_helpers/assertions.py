"""Entity assertions, instant comparison and domain invariant checkers."""

from datetime import date, datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    INK_SAFETY_RESERVE_UL,
    PROOF_APPROVAL_VALID_DAYS,
    TRANSIT_DAYS_BY_MAIL_CLASS,
)


# --------------------------------------------------------------------------
# Instants and calendar dates
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    Tolerates a trailing ``Z`` or an explicit ``+00:00`` offset and any
    fractional-second precision, so ``2026-05-31T00:00:00Z`` and
    ``2026-05-31T00:00:00.000Z`` parse to the same instant.
    """
    assert isinstance(value, str) and value.strip(), f"Not an instant string: {value!r}"
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "instant"):
    """Compare two ISO 8601 instants semantically, never as raw strings."""
    assert actual is not None, f"{label} must not be null"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected!r}, got {actual!r}"


def parse_calendar_date(value: str) -> date:
    assert isinstance(value, str) and value.strip(), f"Not a calendar date: {value!r}"
    return date.fromisoformat(value.strip())


def assert_same_calendar_date(actual, expected, label: str = "date"):
    assert actual is not None, f"{label} must not be null"
    got = parse_calendar_date(actual)
    want = parse_calendar_date(expected)
    assert got == want, f"{label}: expected {expected!r}, got {actual!r}"


def days_between(earlier: str, later: str) -> int:
    return (parse_calendar_date(later) - parse_calendar_date(earlier)).days


def shift_date(value: str, days: int) -> str:
    return (parse_calendar_date(value) + timedelta(days=days)).isoformat()


def expected_expiry(approved_at: str) -> datetime:
    """approved_at plus the thirty-day approval window."""
    return parse_instant(approved_at) + timedelta(days=PROOF_APPROVAL_VALID_DAYS)


def expected_in_home_date(mail_date: str, mail_class: str) -> str:
    """The resolved drop date plus the class's transit days."""
    return shift_date(mail_date, TRANSIT_DAYS_BY_MAIL_CLASS[mail_class])


# --------------------------------------------------------------------------
# Common shape helpers
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "resource"):
    """id + created_at + updated_at + version, per PRD section 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, label: str = "record"):
    """Append-only rows carry only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at"
    assert "version" not in data, f"{label} must not expose a version field"
    assert "updated_at" not in data, f"{label} must not expose an updated_at field"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_account(data: dict):
    assert_common_fields(data, "Account")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for field in (
        "permit_balance_cents",
        "lifetime_topup_cents",
        "lifetime_draw_cents",
        "lifetime_refund_cents",
        "lifetime_forfeit_cents",
    ):
        assert isinstance(data[field], int), f"Account.{field} must be an integer of cents"


def assert_campaign(data: dict):
    assert_common_fields(data, "Campaign")
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "PAUSED", "COMPLETED")
    assert data["compliance_status"] in ("CLEAR", "HOLD")
    assert data["billing_status"] in ("OPEN", "CLOSED")
    assert data["write_gate"] in ("OPEN", "FROZEN")
    assert_write_gate_derivation(data)


def assert_write_gate_derivation(campaign: dict):
    """write_gate reads FROZEN whenever compliance is HOLD or billing is CLOSED."""
    frozen = campaign["compliance_status"] == "HOLD" or campaign["billing_status"] == "CLOSED"
    expected = "FROZEN" if frozen else "OPEN"
    assert campaign["write_gate"] == expected, (
        f"write_gate must be {expected} for compliance_status "
        f"{campaign['compliance_status']} and billing_status {campaign['billing_status']}"
    )


def assert_template(data: dict):
    assert_common_fields(data, "Template")
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["character_count"], int)
    assert data["envelope_style"] in ("STANDARD", "WINDOW", "HAND_ADDRESSED")


def assert_mailing_list(data: dict):
    assert_common_fields(data, "MailingList")
    assert data["import_status"] in ("UPLOADED", "CASS_RUN", "DEDUPED", "LOCKED")
    assert data["dedupe_mode"] in (None, "EXACT", "HOUSEHOLD")
    for field in (
        "record_count",
        "automation_count",
        "retail_count",
        "unmailable_count",
        "duplicate_count",
        "mailable_count",
    ):
        assert isinstance(data[field], int), f"MailingList.{field} must be an integer"
    assert data["mailable_count"] == data["automation_count"] + data["retail_count"], (
        "mailable_count is automation_count plus retail_count"
    )


def assert_list_record(data: dict):
    assert_common_fields(data, "ListRecord")
    assert data["cass_status"] in ("PENDING", "STANDARDIZED", "UNMAILABLE")
    assert data["deliverability_tier"] in ("UNASSIGNED", "AUTOMATION", "RETAIL", "UNMAILABLE")
    assert data["dedupe_status"] in (
        "UNSCREENED",
        "UNIQUE",
        "HOUSEHOLD_HEAD",
        "DUP_EXACT",
        "DUP_HOUSEHOLD",
    )
    assert data["mail_status"] in (
        "NOT_MAILED",
        "QUEUED",
        "MAILED",
        "DELIVERED_ASSUMED",
        "RETURNED",
    )
    assert data["move_status"] in ("NONE", "MOVE_APPLIED", "MOVE_NO_FORWARD")
    assert data["dpv_confirmation_code"] in ("Y", "D", "S", "N", "U")
    assert isinstance(data["insertion_seq"], int) and data["insertion_seq"] >= 1


def assert_mail_job(data: dict):
    assert_common_fields(data, "MailJob")
    assert data["job_kind"] in ("ADDRESSED", "EDDM")
    assert data["mail_class"] in ("FIRST_CLASS", "MARKETING_MAIL", "EDDM")
    assert data["status"] in (
        "DRAFT",
        "PROOFED",
        "SCHEDULED",
        "COMMITTED",
        "IN_PRODUCTION",
        "MAILED",
        "CLOSED",
    )
    assert data["presort_tier"] in (
        "UNASSIGNED",
        "PRESORT_5D",
        "PRESORT_AADC",
        "PRESORT_MIXED_AADC",
        "NO_PRESORT",
        "EDDM_ROUTE",
    )
    assert data["billable_piece_count"] == (
        data["eddm_piece_count"]
        if data["job_kind"] == "EDDM"
        else data["automation_piece_count"] + data["retail_piece_count"]
    ), "billable_piece_count follows the job kind"


def assert_proof(data: dict):
    assert_common_fields(data, "Proof")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
        "EXPIRED",
    )


def assert_ink_lot(data: dict):
    assert_common_fields(data, "InkLot")
    assert data["status"] in ("SEALED", "OPEN", "DEPLETED", "QUARANTINED")
    assert data["ink_type"] in ("INK_BLUE_A", "INK_BLACK_B", "INK_NAVY_C")
    assert isinstance(data["remaining_ul"], int)
    assert data["remaining_ul"] >= 0, "remaining_ul must never go negative"


def assert_production_run(data: dict):
    assert_common_fields(data, "ProductionRun")
    assert data["status"] in ("RESERVED", "RUNNING", "COMPLETED", "FAILED", "VOIDED")
    assert data["capacity_variant"] in ("SINGLE_PASS", "SPLIT_RUN")
    for field in ("planned_write_minutes", "planned_slot_minutes", "planned_ink_ul"):
        assert isinstance(data[field], int), f"ProductionRun.{field} must be an integer"


def assert_drip_schedule(data: dict):
    assert_common_fields(data, "DripSchedule")
    assert data["status"] in ("DRAFT", "ACTIVE", "CANCELLED")
    assert data["anchor_variant"] in ("ANCHOR_IN_HOME", "ANCHOR_MAIL_DATE")


def assert_drip_step(data: dict):
    assert_common_fields(data, "DripStep")
    assert data["status"] in ("PENDING", "SCHEDULED", "RELEASED", "MAILED", "CANCELLED")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_eddm_route_selection(data: dict):
    assert_common_fields(data, "EddmRouteSelection")
    assert data["selected_piece_count"] == (
        data["residential_piece_count"] + data["business_piece_count"]
    ), "selected_piece_count is residential plus business"


def assert_reprint_request(data: dict):
    assert_common_fields(data, "ReprintRequest")
    assert data["status"] in ("REQUESTED", "FULFILLED", "DENIED")


def assert_ledger_entry(data: dict):
    assert_append_only_fields(data, "PostageLedgerEntry")
    assert data["entry_type"] in ("TOPUP", "DRAW", "REFUND", "FORFEIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    sign = 1 if data["entry_type"] in ("TOPUP", "REFUND") else -1
    assert data["signed_amount_cents"] == sign * data["amount_cents"], (
        "signed_amount_cents is positive for TOPUP and REFUND, negative for DRAW and FORFEIT"
    )


def assert_return_event(data: dict):
    assert_append_only_fields(data, "ReturnEvent")
    assert data["entitlement"] in ("REPRINT", "REFUND")
    assert data["return_reason"] in (
        "MOVED_NO_FORWARD",
        "VACANT",
        "REFUSED",
        "INSUFFICIENT_ADDRESS",
    )


# --------------------------------------------------------------------------
# Conservation invariants (PRD section 2.10)
# --------------------------------------------------------------------------
def assert_postage_money_conservation(account: dict, ledger_rows: list):
    """permit_balance_cents is exactly the signed sum of the account's rows."""
    signed_total = 0
    topups = draws = refunds = forfeits = 0
    for row in ledger_rows:
        amount = row["amount_cents"]
        if row["entry_type"] == "TOPUP":
            signed_total += amount
            topups += amount
        elif row["entry_type"] == "REFUND":
            signed_total += amount
            refunds += amount
        elif row["entry_type"] == "DRAW":
            signed_total -= amount
            draws += amount
        else:
            signed_total -= amount
            forfeits += amount
    assert account["permit_balance_cents"] == signed_total, (
        "permit_balance_cents must equal topups plus refunds less draws and forfeits"
    )
    assert account["lifetime_topup_cents"] == topups
    assert account["lifetime_draw_cents"] == draws
    assert account["lifetime_refund_cents"] == refunds
    assert account["lifetime_forfeit_cents"] == forfeits


def assert_ink_volume_conservation(ink_lot: dict, runs: list):
    """remaining_ul equals initial_volume_ul less every non-voided run's draw."""
    committed = sum(
        run["planned_ink_ul"]
        for run in runs
        if run["status"] in ("RESERVED", "RUNNING", "COMPLETED", "FAILED")
    )
    assert ink_lot["remaining_ul"] == ink_lot["initial_volume_ul"] - committed, (
        "remaining_ul must equal initial_volume_ul minus the non-voided draws"
    )


def assert_machine_day_conservation(machine: dict, runs: list, run_date: str):
    """Committed slot-minutes on one machine-day never exceed the daily capacity."""
    committed = sum(
        run["planned_slot_minutes"]
        for run in runs
        if run["run_date"] == run_date
        and run["status"] in ("RESERVED", "RUNNING", "COMPLETED", "FAILED")
    )
    assert committed <= machine["daily_capacity_minutes"], (
        f"committed minutes {committed} on {run_date} exceed the machine's "
        f"daily_capacity_minutes {machine['daily_capacity_minutes']}"
    )
    return committed


def assert_ink_reserve_respected(ink_lot: dict):
    assert ink_lot["remaining_ul"] >= INK_SAFETY_RESERVE_UL or ink_lot["status"] in (
        "DEPLETED",
        "QUARANTINED",
    ), "a reservable lot must keep the safety reserve in the bottle"


def assert_list_partition_sums_to_record_count(mailing_list: dict):
    """The four buckets exhaust the list.

    Only call this on lists where no record is simultaneously UNMAILABLE-tier
    and a screening duplicate; where those two memberships can overlap the PRD
    deliberately leaves the per-list counters unadjudicated.
    """
    total = (
        mailing_list["automation_count"]
        + mailing_list["retail_count"]
        + mailing_list["unmailable_count"]
        + mailing_list["duplicate_count"]
    )
    assert total == mailing_list["record_count"], (
        f"partition {total} must equal record_count {mailing_list['record_count']}"
    )
