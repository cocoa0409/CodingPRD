"""Domain assertions for the invariants and rounding conventions the PRD pins.

Hour figures are compared through ``Decimal(str(value))`` rather than as floats,
because PRD 2.7 gives them "two decimal places, rounded half up" and a binary
float comparison of 28.26 would be a comparison of neither figure.
"""

from datetime import datetime, timezone
from decimal import Decimal

from .constants import (
    ANCILLARY_UNIT_CHARGE_CENTS,
    DEFECT_COUNTED_EVENT_TYPES,
    RESTRICTED_CODES_WHEN_OPEN,
    RESTRICTED_CODES_WHEN_RESTRICTED,
    RESTRICTED_CODES_WHEN_SUSPENDED,
)


# ------------------------------------------------------------ instants -------
def as_instant(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware ``datetime``.

    PRD 2.4 renders stamped timestamps "as ISO 8601 UTC timestamps with three
    fractional digits" while the logical clock is set from an instant written
    without them, so ``2026-08-01T08:00:00Z`` and ``2026-08-01T08:00:00.000Z``
    name the same moment and must compare equal.
    """
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected, label: str = "instant") -> None:
    """Compare two timestamps as instants rather than as strings."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert as_instant(actual) == as_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------------- hours -------
def as_hours(value) -> Decimal:
    """Normalise an hour figure to a two-decimal Decimal.

    PRD 2.7: "Hour figures ... are decimal numbers carrying two decimal places,
    rounded half up."  The server may render 84 as ``84``, ``84.0`` or
    ``"84.00"``; all three are the same two-decimal quantity.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"))


def assert_hours_equal(actual, expected, label: str = "hours") -> None:
    """Compare two hour figures at the two-decimal precision PRD 2.7 pins."""
    assert as_hours(actual) == as_hours(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimal_hours(value, label: str = "hours") -> None:
    """Assert an hour figure carries no more than two decimal places."""
    quantised = Decimal(str(value))
    assert -quantised.as_tuple().exponent <= 2, (
        f"{label} carries more than two decimal places: {value}"
    )


# ---------------------------------------------------------------- money ------
def assert_whole_cents(value, label: str = "amount") -> None:
    """PRD 2.7: every monetary field is an integer number of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of whole cents, got {value!r}"
    )


def assert_money_conservation(claim: dict) -> None:
    """PRD 2.10: billed_total equals plan_paid plus patient responsibility plus write-off.

    The invariant is asserted "at every moment after adjudication — including
    after an award is applied and again after an award is withdrawn".
    """
    for field in (
        "billed_total_cents",
        "plan_paid_cents",
        "patient_responsibility_cents",
        "written_off_cents",
    ):
        assert_whole_cents(claim[field], field)
    total = (
        claim["plan_paid_cents"]
        + claim["patient_responsibility_cents"]
        + claim["written_off_cents"]
    )
    assert claim["billed_total_cents"] == total, (
        "money conservation broken: billed_total_cents "
        f"{claim['billed_total_cents']} != plan_paid {claim['plan_paid_cents']} + "
        f"patient_responsibility {claim['patient_responsibility_cents']} + "
        f"written_off {claim['written_off_cents']} = {total}"
    )


def assert_line_total(order: dict) -> None:
    """PRD 3.7: line_total_cents is unit_charge_cents times quantity, exactly.

    "an exact integer product with no rounding — and that relationship holds for
    every order in every status, for the life of the row."
    """
    expected_unit = ANCILLARY_UNIT_CHARGE_CENTS[order["code"]]
    assert order["unit_charge_cents"] == expected_unit, (
        f"{order['code']}: expected unit_charge_cents {expected_unit}, "
        f"got {order['unit_charge_cents']}"
    )
    assert order["line_total_cents"] == expected_unit * order["quantity"], (
        f"{order['code']}: expected line_total_cents "
        f"{expected_unit * order['quantity']}, got {order['line_total_cents']}"
    )


def assert_pre_award_snapshots_null(claim: dict) -> None:
    """PRD 3.9: all four pre_award_* snapshots are null outside an applied award."""
    for field in (
        "pre_award_allowed_cents",
        "pre_award_plan_paid_cents",
        "pre_award_patient_responsibility_cents",
        "pre_award_written_off_cents",
    ):
        assert claim[field] is None, f"{field} should be null, got {claim[field]!r}"


def assert_pre_award_snapshots_equal(
    claim: dict, allowed: int, plan_paid: int, patient_responsibility: int, written_off: int
) -> None:
    """PRD 3.9: the four figures captured before the awarded figure was applied."""
    assert claim["pre_award_allowed_cents"] == allowed, (
        f"pre_award_allowed_cents: expected {allowed}, "
        f"got {claim['pre_award_allowed_cents']}"
    )
    assert claim["pre_award_plan_paid_cents"] == plan_paid, (
        f"pre_award_plan_paid_cents: expected {plan_paid}, "
        f"got {claim['pre_award_plan_paid_cents']}"
    )
    assert claim["pre_award_patient_responsibility_cents"] == patient_responsibility, (
        "pre_award_patient_responsibility_cents: expected "
        f"{patient_responsibility}, got "
        f"{claim['pre_award_patient_responsibility_cents']}"
    )
    assert claim["pre_award_written_off_cents"] == written_off, (
        f"pre_award_written_off_cents: expected {written_off}, "
        f"got {claim['pre_award_written_off_cents']}"
    )


def assert_settlement(
    claim: dict,
    *,
    allowed: int | None = None,
    plan_paid: int | None = None,
    patient_responsibility: int | None = None,
    balance_bill: int | None = None,
    written_off: int | None = None,
) -> None:
    """Assert the settlement figures a caller pins, then the conservation invariant."""
    pinned = {
        "allowed_amount_cents": allowed,
        "plan_paid_cents": plan_paid,
        "patient_responsibility_cents": patient_responsibility,
        "balance_bill_amount_cents": balance_bill,
        "written_off_cents": written_off,
    }
    for field, expected in pinned.items():
        if expected is not None:
            assert claim[field] == expected, (
                f"{field}: expected {expected}, got {claim[field]}"
            )
    assert_money_conservation(claim)


# ------------------------------------------------------- ambulance units -----
def assert_mou_unit_ledger(mou: dict, reserved: int, available: int) -> None:
    """PRD 2.10: units_available equals units_committed minus units_reserved.

    ``saturation_state`` is "SATURATED when units_available is 0 and AVAILABLE
    otherwise", so it is derived from the same two figures and checked with them.
    """
    assert mou["units_reserved"] == reserved, (
        f"units_reserved: expected {reserved}, got {mou['units_reserved']}"
    )
    assert mou["units_available"] == available, (
        f"units_available: expected {available}, got {mou['units_available']}"
    )
    assert mou["units_available"] == mou["units_committed"] - mou["units_reserved"], (
        f"units_available {mou['units_available']} != units_committed "
        f"{mou['units_committed']} - units_reserved {mou['units_reserved']}"
    )
    expected_state = "SATURATED" if mou["units_available"] == 0 else "AVAILABLE"
    assert mou["saturation_state"] == expected_state, (
        f"saturation_state: expected {expected_state} for units_available "
        f"{mou['units_available']}, got {mou['saturation_state']}"
    )


def assert_facility_unit_totals(facility: dict, committed: int, reserved: int) -> None:
    """PRD 2.10: the facility-level unit totals and the capacity state they imply.

    "transfer_capacity_state is AVAILABLE when committed total minus reserved
    total is greater than 0 and SATURATED otherwise."
    """
    assert facility["ambulance_units_committed_total"] == committed, (
        f"ambulance_units_committed_total: expected {committed}, "
        f"got {facility['ambulance_units_committed_total']}"
    )
    assert facility["ambulance_units_reserved_total"] == reserved, (
        f"ambulance_units_reserved_total: expected {reserved}, "
        f"got {facility['ambulance_units_reserved_total']}"
    )
    expected_state = "AVAILABLE" if committed - reserved > 0 else "SATURATED"
    assert facility["transfer_capacity_state"] == expected_state, (
        f"transfer_capacity_state: expected {expected_state}, "
        f"got {facility['transfer_capacity_state']}"
    )


def assert_unit_conservation(mous: list) -> None:
    """PRD 2.10: across ACTIVE memoranda, committed equals reserved plus available."""
    active = [mou for mou in mous if mou["status"] == "ACTIVE"]
    committed = sum(mou["units_committed"] for mou in active)
    reserved = sum(mou["units_reserved"] for mou in active)
    available = sum(mou["units_available"] for mou in active)
    assert committed == reserved + available, (
        f"unit conservation broken: committed {committed} != reserved {reserved} "
        f"+ available {available}"
    )


# ------------------------------------------------------- observation beds ----
def assert_bed_conservation(facility: dict, holders: list) -> None:
    """PRD 2.10: observation_beds_occupied equals the encounters holding a bed.

    The count is "counted regardless of clinical_state — an encounter that
    entered observation and is now TRANSFER_PENDING still holds its bed", and it
    "always satisfies the bounds of at least 0 and at most
    observation_bed_count".
    """
    expected = sum(1 for encounter in holders if encounter["observation_bed_held"])
    assert facility["observation_beds_occupied"] == expected, (
        f"observation_beds_occupied: expected {expected} (the encounters whose "
        f"observation_bed_held is true), got {facility['observation_beds_occupied']}"
    )
    assert 0 <= facility["observation_beds_occupied"] <= facility["observation_bed_count"], (
        f"observation_beds_occupied {facility['observation_beds_occupied']} is "
        f"outside the bounds 0 .. {facility['observation_bed_count']}"
    )


# --------------------------------------------------------------- posture -----
def assert_posture(facility: dict, expected_posture: str) -> None:
    """PRD 2.8: the posture and the restricted_service_codes derived with it."""
    assert facility["compliance_posture"] == expected_posture, (
        f"compliance_posture: expected {expected_posture}, "
        f"got {facility['compliance_posture']}"
    )
    expected_codes = {
        "OPEN": RESTRICTED_CODES_WHEN_OPEN,
        "RESTRICTED": RESTRICTED_CODES_WHEN_RESTRICTED,
        "SUSPENDED": RESTRICTED_CODES_WHEN_SUSPENDED,
    }[expected_posture]
    assert sorted(facility["restricted_service_codes"]) == sorted(expected_codes), (
        f"restricted_service_codes for a {expected_posture} posture: expected "
        f"{expected_codes}, got {facility['restricted_service_codes']}"
    )


def assert_defect_count(facility: dict, expected: int) -> None:
    assert facility["open_compliance_defect_count"] == expected, (
        f"open_compliance_defect_count: expected {expected}, "
        f"got {facility['open_compliance_defect_count']}"
    )


# ---------------------------------------------------------------- ledger -----
def find_ledger_entries(entries: list, event_type: str) -> list:
    """The ledger rows of one event type, in the order the ledger returned them."""
    return [entry for entry in entries if entry["event_type"] == event_type]


def assert_ledger_entry(
    entries: list,
    event_type: str,
    *,
    severity: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    defect_counted: bool | None = None,
    count: int | None = None,
) -> dict:
    """Assert one ledger entry of ``event_type`` exists with the pinned attributes.

    Returns the matched entry (the last one, when several share the event type)
    so a caller can assert further fields on it.
    """
    matches = find_ledger_entries(entries, event_type)
    if count is not None:
        assert len(matches) == count, (
            f"expected {count} {event_type} ledger entries, got {len(matches)}"
        )
    else:
        assert matches, (
            f"expected a {event_type} ledger entry; the ledger holds "
            f"{[entry['event_type'] for entry in entries]}"
        )
    entry = matches[-1]
    if severity is not None:
        assert entry["severity"] == severity, (
            f"{event_type} severity: expected {severity}, got {entry['severity']}"
        )
    if subject_type is not None:
        assert entry["subject_type"] == subject_type, (
            f"{event_type} subject_type: expected {subject_type}, "
            f"got {entry['subject_type']}"
        )
    if subject_id is not None:
        assert entry["subject_id"] == subject_id, (
            f"{event_type} subject_id: expected {subject_id}, got {entry['subject_id']}"
        )
    if defect_counted is not None:
        assert entry["defect_counted"] is defect_counted, (
            f"{event_type} defect_counted: expected {defect_counted}, "
            f"got {entry['defect_counted']}"
        )
    return entry


def assert_no_ledger_entry(entries: list, event_type: str) -> None:
    matches = find_ledger_entries(entries, event_type)
    assert not matches, f"expected no {event_type} ledger entry, found {len(matches)}"


def assert_defect_counted_vocabulary(entries: list) -> None:
    """PRD 2.8: exactly four kinds of finding are defect-counted.

    "Every other event type is informational and leaves
    open_compliance_defect_count alone."
    """
    for entry in entries:
        if entry["event_type"] not in DEFECT_COUNTED_EVENT_TYPES:
            assert entry["defect_counted"] is False, (
                f"{entry['event_type']} is informational and must carry "
                f"defect_counted false, got {entry['defect_counted']}"
            )


def assert_ledger_ordered_oldest_first(entries: list) -> None:
    """PRD 2.3: the append-only compliance ledger is returned oldest entry first."""
    stamps = [entry["created_at"] for entry in entries]
    assert stamps == sorted(stamps), (
        f"ledger entries are not ordered by created_at ascending: {stamps}"
    )


# ------------------------------------------------------------- pagination ----
def assert_meta(meta: dict, *, limit: int, offset: int, total_count: int, has_more: bool) -> None:
    """PRD 2.3: the meta block carries limit, offset, total_count and has_more."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_total_count(meta: dict, expected: int) -> None:
    """PRD 2.3: total_count is the rows matching the filters before windowing."""
    assert meta["total_count"] == expected, (
        f"meta.total_count: expected {expected}, got {meta['total_count']}"
    )
