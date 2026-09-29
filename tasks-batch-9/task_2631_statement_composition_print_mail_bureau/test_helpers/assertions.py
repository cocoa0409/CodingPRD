"""Per-entity shape assertions and domain invariant checkers.

The shape helpers assert the identity, timestamp and version conventions the
contract guarantees for every entity, then the entity's own required keys. The
invariant helpers assert the three conservation ledgers and the derived
quantities that several rules share.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASIS_POINTS_WHOLE,
    MIN_RUN_MINUTES,
    PIECES_PER_TRAY,
    POSTAGE_SURCHARGE_CENTS_PER_SHEET,
    POSTAGE_SURCHARGE_FREE_SHEETS,
    POSTAGE_BASE_RATE_CENTS,
)

#: Timestamps are ISO 8601 UTC with exactly three fractional-second digits.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

#: Every success envelope's request identifier is prefixed this way.
REQUEST_ID_PREFIX = "req_"


# --------------------------------------------------------------------------
# Rounding helpers
# --------------------------------------------------------------------------


def round_half_up(value: float, places: int = 0) -> float:
    """Round half away from zero, the contract's rounding convention."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(result) if places > 0 else int(result)


def round_half_up_int(value: float) -> int:
    """Round half up to a whole number."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_div(numerator: int, denominator: int) -> int:
    """Integer division that rounds up, for tray counts and run minutes."""
    return -(-numerator // denominator)


# --------------------------------------------------------------------------
# Envelope and common field conventions
# --------------------------------------------------------------------------


def assert_timestamp(value: Any, field: str = "timestamp") -> None:
    """A stored timestamp is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _TIMESTAMP_RE.match(value), (
        f"{field} must be ISO 8601 UTC with exactly three fractional-second "
        f"digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{field} is not a valid ISO 8601 instant"


def assert_common_fields(entity: Dict[str, Any], name: str = "entity") -> None:
    """Identity, both timestamps and the version counter."""
    assert is_valid_uuid(entity.get("id")), (
        f"{name}.id must be a UUID, got {entity.get('id')!r}"
    )
    assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    assert_timestamp(entity.get("updated_at"), f"{name}.updated_at")
    assert isinstance(entity.get("version"), int), f"{name}.version must be an integer"
    assert entity["version"] >= 1, f"{name}.version starts at 1"


def assert_append_only_fields(entity: Dict[str, Any], name: str = "entity") -> None:
    """An append-only audit row carries identity and creation time only."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID"
    assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    assert "updated_at" not in entity, (
        f"{name} is append-only and must not carry updated_at"
    )
    assert "version" not in entity, (
        f"{name} is append-only and must not carry version"
    )


def assert_meta_envelope(meta: Dict[str, Any]) -> None:
    """The success envelope's request identifier and timestamp."""
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"meta.api_request_id must start with {REQUEST_ID_PREFIX!r}, "
        f"got {meta['api_request_id']!r}"
    )
    assert_timestamp(meta.get("api_request_timestamp"), "meta.api_request_timestamp")


def assert_single_resource_meta(body: Dict[str, Any]) -> None:
    """A single-resource response omits all four pagination fields."""
    meta = body["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"single-resource meta must omit {field}, got {meta.get(field)!r}"
        )


def assert_required_keys(
    entity: Dict[str, Any], keys: Iterable[str], name: str
) -> None:
    missing = [k for k in keys if k not in entity]
    assert not missing, f"{name} is missing declared fields: {missing}"


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------

CLIENT_FIELDS = [
    "client_code",
    "name",
    "status",
    "sla_turnaround_hours",
    "sla_penalty_rate_cents_per_hour",
    "sla_penalty_cap_cents",
    "control_total_tolerance_bp",
    "dr_readiness_required",
    "postage_deposited_cents",
    "postage_committed_cents",
    "postage_escrow_available_cents",
    "paperless_sync_epoch",
    "pending_address_feedback_count",
    "address_feedback_batch_count",
]


def assert_client(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "Client")
    assert_required_keys(entity, CLIENT_FIELDS, "Client")
    assert entity["status"] in ("ACTIVE", "SUSPENDED")
    assert_escrow_ledger(entity)


def assert_enrollment(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "PaperlessEnrollment")
    assert_required_keys(
        entity,
        [
            "client_id",
            "account_ref",
            "channel",
            "status",
            "enrolled_epoch",
            "revoked_epoch",
            "confirmed_at",
            "suppression_effective",
        ],
        "PaperlessEnrollment",
    )
    assert entity["status"] in ("PENDING", "ENROLLED", "REVOKED")
    assert entity["channel"] in ("EMAIL", "PORTAL")


def assert_insert_stock(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "InsertStock")
    assert_required_keys(
        entity,
        [
            "insert_code",
            "description",
            "jurisdiction_code",
            "effective_from",
            "effective_to",
            "sheets_per_insert",
            "received_count",
            "on_hand_count",
            "reserved_count",
            "consumed_count",
            "status",
        ],
        "InsertStock",
    )
    assert_insert_stock_ledger(entity)


def assert_template(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "CompositionTemplate")
    assert_required_keys(
        entity,
        [
            "client_id",
            "template_code",
            "version_no",
            "status",
            "duplex_required",
            "sheets_per_document",
            "color_pages_per_document",
            "mail_class_preference",
            "required_insert_codes",
            "variable_content_rules",
        ],
        "CompositionTemplate",
    )
    assert entity["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert entity["mail_class_preference"] in ("FIRST_CLASS", "MARKETING")


def assert_data_file(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "DataFile")
    assert_required_keys(
        entity,
        [
            "client_id",
            "file_name",
            "format_spec_code",
            "status",
            "declared_record_count",
            "declared_control_total_cents",
            "actual_record_count",
            "actual_control_total_cents",
            "record_count_variance",
            "control_total_variance_bp",
            "format_error_count",
            "amendment_count",
        ],
        "DataFile",
    )
    assert entity["status"] in (
        "RECEIVED",
        "FORMAT_VALIDATED",
        "HELD_VARIANCE",
        "ACCEPTED",
        "CONSUMED",
    )
    assert entity["format_spec_code"] in ("FIXED_WIDTH", "DELIMITED", "XML")


def assert_statement_record(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "StatementRecord")
    assert_required_keys(
        entity,
        [
            "data_file_id",
            "account_ref",
            "sequence_no",
            "statement_amount_cents",
            "address_line1",
            "city",
            "region_code",
            "postal_code",
            "format_valid",
        ],
        "StatementRecord",
    )


def assert_composition_job(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "CompositionJob")
    assert_required_keys(
        entity,
        [
            "client_id",
            "data_file_id",
            "template_id",
            "status",
            "integrity_status",
            "composition_epoch",
            "composed_by_user_id",
            "expected_piece_count",
            "print_piece_count",
            "electronic_piece_count",
            "accountable_piece_count",
            "total_sheet_count",
            "print_sheet_count",
            "insert_sheet_total",
            "color_page_count",
            "sla_due_at",
        ],
        "CompositionJob",
    )
    assert entity["status"] in (
        "COMPOSED",
        "PRESORTED",
        "SCHEDULED",
        "PRINTING",
        "PRINTED",
        "INTEGRITY_HELD",
        "VERIFIED",
        "MANIFESTED",
        "CLOSED",
    )
    assert entity["integrity_status"] in ("PENDING", "MATCHED", "BREACHED")


def assert_mail_piece(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "MailPiece")
    assert_required_keys(
        entity,
        [
            "composition_job_id",
            "statement_record_id",
            "piece_seq",
            "imb_barcode",
            "piece_status",
            "integrity_status",
            "last_scan_stage",
            "accepted_scan_count",
            "sheet_count",
            "mail_class",
            "billable",
        ],
        "MailPiece",
    )
    assert entity["piece_status"] in (
        "COMPOSED",
        "SUPPRESSED",
        "PRINTED",
        "INSERTED",
        "INDUCTED",
        "VOID",
    )
    assert entity["integrity_status"] in (
        "UNVERIFIED",
        "SCAN_MATCHED",
        "RECONCILED",
        "SCAN_MISSING",
        "DUPLICATE_SCAN",
    )
    assert entity["last_scan_stage"] in ("NONE", "PRINT", "INSERT", "INDUCT")


def assert_scan_event(entity: Dict[str, Any]) -> None:
    """The scan log is immutable, so the row carries no version and no
    ``updated_at``."""
    assert_append_only_fields(entity, "ScanEvent")
    assert_required_keys(
        entity,
        [
            "mail_piece_id",
            "stage",
            "scanned_barcode",
            "device_code",
            "scanned_at",
            "accepted",
        ],
        "ScanEvent",
    )
    assert entity["stage"] in ("PRINT", "INSERT", "INDUCT")
    assert isinstance(entity["accepted"], bool)
    if entity["accepted"]:
        assert entity["rejection_reason"] == "NONE", (
            "an accepted scan carries the NONE reason sentinel"
        )
    else:
        assert entity["rejection_reason"] in (
            "UNKNOWN_BARCODE",
            "DUPLICATE_STAGE",
            "OUT_OF_SEQUENCE",
        )


def assert_press_line(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "PressLine")
    assert_required_keys(
        entity,
        [
            "line_code",
            "capabilities",
            "sheets_per_hour",
            "daily_sheet_capacity",
            "changeover_buffer_minutes",
            "status",
            "committed_sheet_count",
            "utilization_bp",
        ],
        "PressLine",
    )
    assert entity["status"] in ("AVAILABLE", "MAINTENANCE", "RETIRED")
    assert_press_ledger(entity)


def assert_print_run(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "PrintRun")
    assert_required_keys(
        entity,
        [
            "composition_job_id",
            "press_line_id",
            "status",
            "selection_mode",
            "window_start",
            "window_end",
            "run_minutes",
            "planned_sheet_count",
        ],
        "PrintRun",
    )
    assert entity["status"] in ("PLANNED", "RUNNING", "COMPLETED", "ABORTED")
    assert entity["selection_mode"] in ("EXPLICIT", "SELECTED")
    assert entity["run_minutes"] >= MIN_RUN_MINUTES, (
        "a run never occupies fewer than the floor number of minutes"
    )


def assert_entry_facility(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "EntryFacility")
    assert_required_keys(
        entity,
        [
            "facility_code",
            "facility_type",
            "tray_capacity_per_window",
            "discount_bp_first_class",
            "discount_bp_marketing",
            "status",
            "committed_tray_count",
        ],
        "EntryFacility",
    )
    assert entity["status"] in ("OPEN", "CLOSED")


def assert_presort_batch(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "PresortBatch")
    assert_required_keys(
        entity,
        [
            "composition_job_id",
            "mail_class",
            "presort_bucket",
            "status",
            "piece_count",
            "tray_count",
        ],
        "PresortBatch",
    )
    assert entity["status"] in ("OPEN", "SEALED", "MANIFESTED")
    assert entity["tray_count"] == ceil_div(entity["piece_count"], PIECES_PER_TRAY), (
        "tray count is the piece count divided by the tray size, rounded up"
    )


def assert_undeliverable_return(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "UndeliverableReturn")
    assert_required_keys(
        entity, ["mail_piece_id", "reason_code", "disposition"], "UndeliverableReturn"
    )
    assert entity["reason_code"] in (
        "MOVED_NO_FORWARD",
        "INSUFFICIENT_ADDRESS",
        "VACANT",
        "REFUSED",
        "DECEASED",
    )
    assert entity["disposition"] in (
        "SCANNED",
        "ADDRESS_UPDATED",
        "UNRESOLVED",
        "FEEDBACK_SENT",
    )


def assert_dr_site(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity, "DrSite")
    assert_required_keys(
        entity,
        [
            "site_code",
            "replication_lag_minutes",
            "readiness_status",
            "readiness_valid_until",
        ],
        "DrSite",
    )
    assert entity["readiness_status"] in ("UNTESTED", "READY", "STALE", "FAILED")


# --------------------------------------------------------------------------
# Conservation invariants across the three ledgers
# --------------------------------------------------------------------------


def assert_escrow_ledger(client: Dict[str, Any]) -> None:
    """Available escrow is deposited minus committed, at every observable
    moment."""
    deposited = client["postage_deposited_cents"]
    committed = client["postage_committed_cents"]
    available = client["postage_escrow_available_cents"]
    assert available == deposited - committed, (
        f"escrow ledger broken: available {available} != deposited {deposited} "
        f"- committed {committed}"
    )
    assert committed >= 0, "committed escrow is never negative"
    assert available >= 0, "available escrow is never negative"


def assert_insert_stock_ledger(stock: Dict[str, Any]) -> None:
    """Received stock is always on hand plus reserved plus consumed."""
    received = stock["received_count"]
    on_hand = stock["on_hand_count"]
    reserved = stock["reserved_count"]
    consumed = stock["consumed_count"]
    assert received == on_hand + reserved + consumed, (
        f"insert stock ledger broken: received {received} != on_hand {on_hand} "
        f"+ reserved {reserved} + consumed {consumed}"
    )
    assert on_hand >= 0 and reserved >= 0 and consumed >= 0


def assert_press_ledger(line: Dict[str, Any]) -> None:
    """Utilization is the committed sheet count against daily capacity, in
    basis points."""
    committed = line["committed_sheet_count"]
    capacity = line["daily_sheet_capacity"]
    expected_bp = committed * BASIS_POINTS_WHOLE // capacity
    assert line["utilization_bp"] == expected_bp, (
        f"utilization {line['utilization_bp']} bp does not match committed "
        f"{committed} of capacity {capacity} (expected {expected_bp} bp)"
    )
    assert committed >= 0, "committed sheets are never negative"


def assert_escrow_conserved(
    before: Dict[str, Any], after: Dict[str, Any], expected_delta_committed: int
) -> None:
    """Deposited escrow never moves on a commitment change; only the committed
    and available legs do."""
    assert after["postage_deposited_cents"] == before["postage_deposited_cents"], (
        "deposited escrow must not move when a commitment is taken or released"
    )
    actual_delta = (
        after["postage_committed_cents"] - before["postage_committed_cents"]
    )
    assert actual_delta == expected_delta_committed, (
        f"committed escrow moved by {actual_delta}, expected "
        f"{expected_delta_committed}"
    )
    assert_escrow_ledger(after)


def assert_insert_stock_conserved(
    before: Dict[str, Any], after: Dict[str, Any]
) -> None:
    """A movement between the three legs never changes the received total."""
    assert after["received_count"] == before["received_count"], (
        "received count only moves when new stock is booked in"
    )
    assert_insert_stock_ledger(before)
    assert_insert_stock_ledger(after)


# --------------------------------------------------------------------------
# Derived quantity checkers
# --------------------------------------------------------------------------


def expected_tray_count(piece_count: int) -> int:
    """Trays needed for a piece count; tray counts round up."""
    return ceil_div(piece_count, PIECES_PER_TRAY)


def expected_run_minutes(planned_sheets: int, sheets_per_hour: int) -> int:
    """Run minutes: the sheet time rounded up, floored at the minimum run."""
    return max(MIN_RUN_MINUTES, ceil_div(planned_sheets * 60, sheets_per_hour))


def expected_gross_postage_cents(
    mail_class: str, bucket: str, sheet_count: int
) -> int:
    """Gross postage for one piece: base rate plus the per-sheet surcharge."""
    base = POSTAGE_BASE_RATE_CENTS[mail_class][bucket]
    surcharge = (
        max(0, sheet_count - POSTAGE_SURCHARGE_FREE_SHEETS)
        * POSTAGE_SURCHARGE_CENTS_PER_SHEET
    )
    return base + surcharge


def expected_net_postage_cents(gross_cents: int, discount_bp: int) -> int:
    """Net postage for one piece: the gross discounted, rounded half up before
    it is summed."""
    return round_half_up_int(
        gross_cents * (BASIS_POINTS_WHOLE - discount_bp) / BASIS_POINTS_WHOLE
    )


def expected_variance_bp(declared: int, actual: int) -> int:
    """Control total variance in basis points, rounded half up; a zero declared
    total with any actual difference saturates."""
    if declared == 0:
        return 0 if actual == 0 else BASIS_POINTS_WHOLE
    return round_half_up_int(abs(actual - declared) * BASIS_POINTS_WHOLE / declared)


def expected_selection_score(
    headroom: int, sheets_per_hour: int, capability_surplus: int
) -> float:
    """The press line selector's score, to two decimal places."""
    from .constants import (
        SELECTOR_CAPABILITY_SURPLUS_PENALTY,
        SELECTOR_HEADROOM_WEIGHT_BP,
        SELECTOR_SPEED_WEIGHT_BP,
    )

    raw = (
        headroom * SELECTOR_HEADROOM_WEIGHT_BP / BASIS_POINTS_WHOLE
        + sheets_per_hour * SELECTOR_SPEED_WEIGHT_BP / BASIS_POINTS_WHOLE
        - capability_surplus * SELECTOR_CAPABILITY_SURPLUS_PENALTY
    )
    return round_half_up(raw, 2)


def expected_imb_barcode(
    client_code: str, received_at_compact: str, piece_seq: int
) -> str:
    """The barcode is the client code, the file receipt instant and the piece
    sequence, zero-padded to six digits."""
    return f"{client_code}-{received_at_compact}-{piece_seq:06d}"


# --------------------------------------------------------------------------
# Cross-entity consistency checkers
# --------------------------------------------------------------------------


def assert_integrity_counters(
    job: Dict[str, Any],
    matched: int,
    missing: int,
    duplicate: int,
    integrity_status: Optional[str] = None,
) -> None:
    """The reconciliation counters as last written."""
    assert job["matched_piece_count"] == matched, (
        f"matched_piece_count {job['matched_piece_count']} != {matched}"
    )
    assert job["missing_scan_count"] == missing, (
        f"missing_scan_count {job['missing_scan_count']} != {missing}"
    )
    assert job["duplicate_scan_count"] == duplicate, (
        f"duplicate_scan_count {job['duplicate_scan_count']} != {duplicate}"
    )
    if integrity_status is not None:
        assert job["integrity_status"] == integrity_status


def assert_piece_counters(
    job: Dict[str, Any],
    expected: int,
    print_pieces: int,
    electronic: int,
    accountable: int,
) -> None:
    """The composition roll-up over the job's pieces."""
    assert job["expected_piece_count"] == expected
    assert job["print_piece_count"] == print_pieces
    assert job["electronic_piece_count"] == electronic
    assert job["accountable_piece_count"] == accountable


def assert_sheet_counters(
    job: Dict[str, Any],
    total_sheets: int,
    print_sheets: int,
    insert_sheets: int,
    color_pages: int,
) -> None:
    """The two divergent sheet bases plus the insert and colour roll-ups."""
    assert job["total_sheet_count"] == total_sheets, (
        f"total_sheet_count {job['total_sheet_count']} != {total_sheets}"
    )
    assert job["print_sheet_count"] == print_sheets, (
        f"print_sheet_count {job['print_sheet_count']} != {print_sheets}"
    )
    assert job["insert_sheet_total"] == insert_sheets
    assert job["color_page_count"] == color_pages


def assert_batch_creation_order(batches: List[Dict[str, Any]]) -> None:
    """Batches materialise first class before marketing, then in bucket order."""
    from .constants import MAIL_CLASS_CREATION_ORDER, PRESORT_BUCKET_CREATION_ORDER

    keys = [
        (
            MAIL_CLASS_CREATION_ORDER.index(b["mail_class"]),
            PRESORT_BUCKET_CREATION_ORDER.index(b["presort_bucket"]),
        )
        for b in batches
    ]
    assert keys == sorted(keys), (
        f"batches are not in creation order: "
        f"{[(b['mail_class'], b['presort_bucket']) for b in batches]}"
    )


def assert_ordered_by(
    rows: List[Dict[str, Any]], *fields: str
) -> None:
    """A listing is ordered ascending by the named fields, in order."""
    keys = [tuple(r[f] for f in fields) for r in rows]
    assert keys == sorted(keys), f"rows are not ordered by {fields}: {keys}"


def assert_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], *fields: str
) -> None:
    """The named fields, and the version counter, did not move."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} moved from {before[field]!r} to {after[field]!r}"
        )
    if "version" in before and "version" in after:
        assert before["version"] == after["version"], (
            f"version moved from {before['version']} to {after['version']}"
        )


# --------------------------------------------------------------------------
# Instant comparison
# --------------------------------------------------------------------------


def normalise_instant(value: str) -> str:
    """One canonical spelling for a UTC instant, so a stored timestamp rendered
    with three fractional digits compares equal to the same instant written
    without them."""
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"instant must be UTC and end in Z, got {value!r}"
    text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = f"{head}.{frac}" if frac else head
    return f"{text}Z"


def assert_instant(actual: Any, expected: str, field: str = "timestamp") -> None:
    """A stored instant equals the expected one, whatever fractional rendering
    the server used."""
    assert_timestamp(actual, field)
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"{field} is {actual!r}, expected the instant {expected!r}"
    )
