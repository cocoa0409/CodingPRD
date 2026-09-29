"""Shape checks and domain-invariant checks.

The shape helpers verify what PRD 2.4 promises about every stored resource — a
server-minted identifier, an ISO-8601 UTC `created_at` carrying exactly three
fractional-second digits, and, for the fourteen resource types that are not the
Qualified-Person release decision, an `updated_at` and an integer `version`.

The invariant helpers restate the arithmetic the PRD works through by hand — the
per-line component demand of section 3.5, the environmental risk index and the
deviation risk score of section 3.7, and the releasable-unit and fee chains of
section 3.8 — so a test can assert both the literal worked number and the
formula that produced it.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .constants import (
    BATCH_EXPOSURE_POINTS,
    COMPONENT_LINES,
    DEVIATION_BASE_POINTS,
    DEVIATION_LINKAGE_BONUS,
    DEVIATION_RISK_CAP,
    EM_LIMITS,
    FEE_BASE_CENTS,
    FEE_DISCOUNT_TIERS,
    FEE_PER_UNIT_CENTS,
    GRADE_WEIGHT,
    RISK_INDEX_CAP,
    RISK_INDEX_CORE_CEILING,
    RISK_INDEX_SCALE,
    SAMPLE_TYPE_SURCHARGE,
)

Json = Dict[str, Any]

# PRD 2.4: an ISO-8601 UTC instant with exactly three fractional-second digits.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ---------------------------------------------------------------------------
# Arithmetic primitives (PRD 2.9)
# ---------------------------------------------------------------------------
def round_half_up(value: Any, places: int = 0) -> Decimal:
    """Round a value half away from zero at `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_int(value: Any) -> int:
    """Round a value half up to a whole number."""
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# Shape checks (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_timestamp(value: Any, field: str = "timestamp") -> None:
    """A stored instant is ISO-8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} should be a string, got {value!r}"
    assert TIMESTAMP_RE.match(value), (
        f"{field} should be an ISO-8601 UTC instant with exactly three "
        f"fractional-second digits, got {value!r}"
    )


def normalize_instant(value: str) -> str:
    """The same instant spelled two ways compares equal.

    PRD 2.4 pins exactly three fractional digits on `created_at` and
    `updated_at`, but says nothing about how a derived validity instant such as
    a suite's `media_fill_valid_until` must be spelled, so instants that are not
    audit stamps are compared by value rather than by text.
    """
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()


def assert_same_instant(actual: Any, expected: str, field: str = "instant") -> None:
    """`actual` denotes the same UTC instant as `expected`."""
    assert actual is not None, f"{field} should be present"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{field} should be the instant {expected}, got {actual}"
    )


def assert_uuid(value: Any, field: str = "id") -> None:
    """A stored identifier is a server-minted UUID."""
    assert isinstance(value, str), f"{field} should be a string, got {value!r}"
    assert UUID_RE.match(value), f"{field} should be a UUID, got {value!r}"


def assert_common_fields(entity: Json, expected_version: Optional[int] = None) -> None:
    """The four common audit fields every versioned resource carries."""
    assert_uuid(entity.get("id"))
    assert_timestamp(entity.get("created_at"), "created_at")
    assert_timestamp(entity.get("updated_at"), "updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version should be an integer, got {version!r}"
    )
    assert version >= 1, f"version starts at 1, got {version!r}"
    if expected_version is not None:
        assert version == expected_version, (
            f"expected version {expected_version}, got {version}"
        )


def assert_append_only_fields(entity: Json) -> None:
    """The release decision carries an id and a created_at and nothing else."""
    assert_uuid(entity.get("id"))
    assert_timestamp(entity.get("created_at"), "created_at")
    assert "updated_at" not in entity, (
        "the Qualified-Person release decision is append-only and carries no "
        f"updated_at, got {entity.get('updated_at')!r}"
    )
    assert "version" not in entity, (
        "the Qualified-Person release decision is append-only and carries no "
        f"version, got {entity.get('version')!r}"
    )


def assert_fields_present(entity: Json, fields: Iterable[str]) -> None:
    """Every named field is present in the response body."""
    missing = [field for field in fields if field not in entity]
    assert not missing, f"response is missing {missing}: {sorted(entity)}"


# ---------------------------------------------------------------------------
# Per-resource shape checks
# ---------------------------------------------------------------------------
def assert_client_project(project: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(project, expected_version)
    assert_fields_present(
        project,
        (
            "client_name",
            "molecule_name",
            "dosage_form",
            "primary_suite_id",
            "target_fill_weight_mg",
            "historical_reject_rate_ppm",
            "reserved_unit_budget",
            "status",
            "tech_transfer_stage",
            "analytical_method_transfer_status",
            "committed_demand_units",
            "open_deviation_risk_total",
            "last_client_audit_finding_count",
        ),
    )


def assert_filling_suite(suite: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(suite, expected_version)
    assert_fields_present(
        suite,
        (
            "suite_code",
            "grade",
            "changeover_minutes_same_product",
            "changeover_minutes_product_change",
            "max_committed_minutes",
            "aseptic_qualification_status",
            "cleaning_validation_status",
            "media_fill_valid_until",
            "last_cleaned_molecule",
            "committed_minutes",
            "open_action_excursion_count",
            "qualified_operator_count",
            "posture",
        ),
    )


def assert_media_fill(media_fill: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(media_fill, expected_version)
    assert_fields_present(
        media_fill,
        (
            "suite_id",
            "scheduled_run_date",
            "status",
            "units_filled",
            "contaminated_units",
            "participating_operator_names",
            "outcome_reason",
            "read_at",
        ),
    )


def assert_qualification(
    qualification: Json, expected_version: Optional[int] = None
) -> None:
    assert_common_fields(qualification, expected_version)
    assert_fields_present(
        qualification,
        (
            "operator_name",
            "suite_id",
            "qualification_type",
            "expires_on",
            "media_fill_id",
            "status",
            "qualified_at",
        ),
    )


def assert_component_lot(lot: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(lot, expected_version)
    assert_fields_present(
        lot,
        (
            "client_project_id",
            "component_type",
            "lot_code",
            "quantity_received",
            "quantity_available",
            "sterilization_expiry",
            "status",
            "sterilization_validation_status",
        ),
    )


def assert_batch_order(batch: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(batch, expected_version)
    assert_fields_present(
        batch,
        (
            "client_project_id",
            "suite_id",
            "lead_operator_qualification_id",
            "batch_number",
            "planned_start",
            "planned_end",
            "target_fill_units",
            "production_status",
            "quality_status",
            "changeover_minutes_applied",
            "component_demand_units",
            "filled_unit_count",
            "quarantined_unit_count",
            "provisional_releasable_units",
            "final_releasable_units",
        ),
    )


def assert_component_reservation(
    reservation: Json, expected_version: Optional[int] = None
) -> None:
    assert_common_fields(reservation, expected_version)
    assert_fields_present(
        reservation,
        (
            "batch_order_id",
            "component_lot_id",
            "quantity_reserved",
            "status",
            "released_reason",
        ),
    )


def assert_in_process_check(check: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(check, expected_version)
    assert_fields_present(
        check,
        (
            "batch_order_id",
            "check_type",
            "sample_size",
            "reject_unit_count",
            "destructive_sample_units",
            "result",
            "max_absolute_deviation_pct",
        ),
    )


def assert_em_sample(sample: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(sample, expected_version)
    assert_fields_present(
        sample,
        (
            "suite_id",
            "batch_order_id",
            "sample_type",
            "cfu_count",
            "alert_limit",
            "action_limit",
            "classification",
            "investigation_status",
            "risk_index",
        ),
    )


def assert_deviation(deviation: Json, expected_version: Optional[int] = None) -> None:
    assert_common_fields(deviation, expected_version)
    assert_fields_present(
        deviation,
        (
            "batch_order_id",
            "em_sample_id",
            "summary",
            "status",
            "classification",
            "risk_score",
            "capa_rejection_count",
            "capa_summary",
            "opened_by_user_id",
        ),
    )


def assert_batch_record_review(
    review: Json, expected_version: Optional[int] = None
) -> None:
    assert_common_fields(review, expected_version)
    assert_fields_present(
        review,
        (
            "batch_order_id",
            "status",
            "reviewer_user_id",
            "open_findings_count",
            "closed_at",
        ),
    )


def assert_audit_engagement(
    engagement: Json, expected_version: Optional[int] = None
) -> None:
    assert_common_fields(engagement, expected_version)
    assert_fields_present(
        engagement,
        (
            "client_project_id",
            "audit_kind",
            "requested_window_start",
            "status",
            "finding_count",
            "hosted_at",
        ),
    )


def assert_qp_release_decision(decision: Json) -> None:
    """PRD 2.4: the one resource with no `updated_at` and no `version`."""
    assert_append_only_fields(decision)
    assert_fields_present(
        decision,
        (
            "batch_order_id",
            "qp_user_id",
            "decision",
            "rationale",
            "released_unit_count",
            "fee_cents",
        ),
    )


# ---------------------------------------------------------------------------
# Component demand (PRD 3.5)
# ---------------------------------------------------------------------------
def expected_line_demand(target_fill_units: int, overage: float, pack_size: int) -> int:
    """One component line: apply the overage, then round up to a whole pack."""
    with_overage = Decimal(str(target_fill_units)) * (Decimal(1) + Decimal(str(overage)))
    packs = math.ceil(with_overage / Decimal(pack_size))
    return packs * pack_size


def expected_component_demand(dosage_form: str, target_fill_units: int) -> int:
    """PRD 3.5: round each line up to its own pack size, and only then sum."""
    return sum(
        expected_line_demand(target_fill_units, overage, pack_size)
        for _component_type, overage, pack_size in COMPONENT_LINES[dosage_form]
    )


def assert_component_demand(batch: Json, dosage_form: str) -> None:
    """The stored demand equals the per-line rounding of PRD 3.5."""
    expected = expected_component_demand(dosage_form, batch["target_fill_units"])
    assert batch["component_demand_units"] == expected, (
        f"component_demand_units should be {expected} (each line rounded up to "
        f"its own pack size before summing), got {batch['component_demand_units']}"
    )


def window_minutes(planned_start_minutes: int, planned_end_minutes: int) -> int:
    """Length of a planned fill window, in whole minutes."""
    return planned_end_minutes - planned_start_minutes


def expected_occupancy_minutes(window_length_minutes: int, changeover_applied: int) -> int:
    """PRD 3.5: a batch occupies its window plus its changeover buffer."""
    return window_length_minutes + changeover_applied


# ---------------------------------------------------------------------------
# Environmental monitoring (PRD 3.7)
# ---------------------------------------------------------------------------
def expected_em_limits(grade: str, sample_type: str) -> Sequence[int]:
    """The (alert, action) pair the grade and sample type select."""
    return EM_LIMITS[grade][sample_type]


def expected_em_classification(cfu_count: int, alert_limit: int, action_limit: int) -> str:
    """PRD 3.7: the action test runs first and both boundaries are inclusive."""
    if cfu_count >= action_limit:
        return "ACTION"
    if cfu_count >= alert_limit:
        return "ALERT"
    return "WITHIN_LIMIT"


def expected_risk_index(
    grade: str,
    sample_type: str,
    cfu_count: int,
    batch_was_filling: bool = False,
) -> int:
    """PRD 3.7: clamp the scaled ratio, then add the surcharges, then cap."""
    _alert_limit, action_limit = expected_em_limits(grade, sample_type)
    ratio = Decimal(str(cfu_count)) / Decimal(str(action_limit))
    core = round_half_up_int(ratio * RISK_INDEX_SCALE * GRADE_WEIGHT[grade])
    core = min(max(core, 0), RISK_INDEX_CORE_CEILING)
    total = core + SAMPLE_TYPE_SURCHARGE[sample_type]
    if batch_was_filling:
        total += BATCH_EXPOSURE_POINTS
    return min(total, RISK_INDEX_CAP)


def assert_em_sample_classification(
    sample: Json,
    grade: str,
    batch_was_filling: bool = False,
) -> None:
    """Limits, classification and risk index all agree with PRD 3.7."""
    alert_limit, action_limit = expected_em_limits(grade, sample["sample_type"])
    assert sample["alert_limit"] == alert_limit, (
        f"alert_limit for a grade {grade} {sample['sample_type']} sample should "
        f"be {alert_limit}, got {sample['alert_limit']}"
    )
    assert sample["action_limit"] == action_limit, (
        f"action_limit for a grade {grade} {sample['sample_type']} sample should "
        f"be {action_limit}, got {sample['action_limit']}"
    )
    expected_class = expected_em_classification(
        sample["cfu_count"], alert_limit, action_limit
    )
    assert sample["classification"] == expected_class, (
        f"{sample['cfu_count']} cfu against limits {alert_limit}/{action_limit} "
        f"should classify as {expected_class}, got {sample['classification']}"
    )
    expected_index = expected_risk_index(
        grade, sample["sample_type"], sample["cfu_count"], batch_was_filling
    )
    assert sample["risk_index"] == expected_index, (
        f"risk_index should be {expected_index}, got {sample['risk_index']}"
    )


# ---------------------------------------------------------------------------
# Deviation risk (PRD 3.7)
# ---------------------------------------------------------------------------
def expected_deviation_risk(
    classification: str,
    capa_rejection_count: int = 0,
    linked_to_action_sample: bool = False,
) -> int:
    """PRD 3.7: escalate, round half up, then add the linkage bonus, then cap."""
    base = Decimal(DEVIATION_BASE_POINTS[classification])
    multiplier = Decimal(1) + Decimal("0.5") * Decimal(capa_rejection_count)
    score = round_half_up_int(base * multiplier)
    if linked_to_action_sample:
        score += DEVIATION_LINKAGE_BONUS
    return min(score, DEVIATION_RISK_CAP)


def assert_deviation_risk(
    deviation: Json, linked_to_action_sample: bool = False
) -> None:
    """The stored risk score equals the escalation chain of PRD 3.7."""
    expected = expected_deviation_risk(
        deviation["classification"],
        deviation.get("capa_rejection_count", 0),
        linked_to_action_sample,
    )
    assert deviation["risk_score"] == expected, (
        f"risk_score should be {expected}, got {deviation['risk_score']}"
    )


# ---------------------------------------------------------------------------
# Releasable units and the release fee (PRD 3.8)
# ---------------------------------------------------------------------------
def expected_provisional_releasable_units(
    filled_unit_count: int,
    historical_reject_rate_ppm: int,
    destructive_total_units: int,
) -> int:
    """PRD 3.8: a ceiling on the projected rejects, never a half-up rounding."""
    expected_rejects = math.ceil(
        Decimal(filled_unit_count)
        * Decimal(historical_reject_rate_ppm)
        / Decimal(1000000)
    )
    return filled_unit_count - expected_rejects - destructive_total_units


def expected_final_releasable_units(
    filled_unit_count: int,
    actual_visual_reject_units: int,
    destructive_total_units: int,
    quarantined_unit_count: int = 0,
) -> int:
    """PRD 3.8: replay what happened, and subtract the quarantined units."""
    return (
        filled_unit_count
        - actual_visual_reject_units
        - destructive_total_units
        - quarantined_unit_count
    )


def expected_release_fee_cents(
    final_releasable_units: int, open_deviation_class: str = "NONE"
) -> int:
    """PRD 3.8: five pinned steps, with the tier selected once from step three."""
    from .constants import DEVIATION_SURCHARGE_PCT

    subtotal = Decimal(FEE_BASE_CENTS) + Decimal(FEE_PER_UNIT_CENTS) * Decimal(
        final_releasable_units
    )
    surcharge_pct = Decimal(DEVIATION_SURCHARGE_PCT[open_deviation_class])
    surcharge = round_half_up(subtotal * surcharge_pct / Decimal(100), 0)
    pre_discount = subtotal + surcharge
    discount_pct = Decimal(0)
    for threshold, pct in FEE_DISCOUNT_TIERS:
        if pre_discount >= Decimal(threshold):
            discount_pct = Decimal(pct)
            break
    discount = round_half_up(pre_discount * discount_pct / Decimal(100), 0)
    return int(pre_discount - discount)


def assert_release_fee(
    fee_cents: int, final_releasable_units: int, open_deviation_class: str = "NONE"
) -> None:
    """The stored fee equals the five-step chain of PRD 3.8."""
    expected = expected_release_fee_cents(final_releasable_units, open_deviation_class)
    assert fee_cents == expected, (
        f"release fee for {final_releasable_units} units with an open "
        f"{open_deviation_class} deviation class should be {expected} cents, "
        f"got {fee_cents}"
    )


# ---------------------------------------------------------------------------
# Ledger invariants (PRD 2.6)
# ---------------------------------------------------------------------------
def assert_lot_unit_ledger(lot: Json, reservations: Iterable[Json]) -> None:
    """PRD 2.6: available units are those no live reservation is holding."""
    held = sum(
        reservation["quantity_reserved"]
        for reservation in reservations
        if reservation["component_lot_id"] == lot["id"]
        and reservation["status"] in ("RESERVED", "CONSUMED")
    )
    assert lot["quantity_available"] + held == lot["quantity_received"], (
        f"lot {lot.get('lot_code')} should satisfy quantity_received == "
        f"quantity_available + held units: {lot['quantity_received']} != "
        f"{lot['quantity_available']} + {held}"
    )


def assert_project_committed_demand(project: Json, live_batches: Iterable[Json]) -> None:
    """PRD 2.6: the project ledger is the demand of its live batches."""
    expected = sum(
        batch["component_demand_units"]
        for batch in live_batches
        if batch["production_status"] in ("SCHEDULED", "SETUP", "FILLING", "FILLED")
    )
    assert project["committed_demand_units"] == expected, (
        f"committed_demand_units should be {expected}, got "
        f"{project['committed_demand_units']}"
    )


def assert_open_deviation_risk_total(project: Json, deviations: Iterable[Json]) -> None:
    """PRD 2.6: the risk ledger sums the not-closed deviations."""
    expected = sum(
        deviation["risk_score"]
        for deviation in deviations
        if deviation["status"] != "CLOSED"
    )
    assert project["open_deviation_risk_total"] == expected, (
        f"open_deviation_risk_total should be {expected}, got "
        f"{project['open_deviation_risk_total']}"
    )


# ---------------------------------------------------------------------------
# Suite posture (PRD 2.5)
# ---------------------------------------------------------------------------
def expected_posture(
    aseptic_qualification_status: str,
    cleaning_validation_status: str,
    open_action_excursion_count: int,
    media_fill_valid_until: Optional[str],
    qualified_operator_count: int,
    now_iso: str,
) -> str:
    """PRD 2.5: first match wins, frozen before restricted before open."""
    if (
        aseptic_qualification_status == "INVALIDATED"
        or cleaning_validation_status == "FAILED"
    ):
        return "FROZEN"
    if (
        open_action_excursion_count >= 1
        or media_fill_valid_until is None
        or media_fill_valid_until < now_iso
        or qualified_operator_count < 2
    ):
        return "RESTRICTED"
    return "OPEN"


def assert_posture(suite: Json, expected: str) -> None:
    """The suite reports the posture its own inputs derive."""
    assert suite["posture"] == expected, (
        f"suite {suite.get('suite_code')} should be {expected} given "
        f"aseptic={suite.get('aseptic_qualification_status')}, "
        f"cleaning={suite.get('cleaning_validation_status')}, "
        f"excursions={suite.get('open_action_excursion_count')}, "
        f"valid_until={suite.get('media_fill_valid_until')}, "
        f"operators={suite.get('qualified_operator_count')}; got {suite['posture']}"
    )


def assert_created_at_ascending(rows: List[Json]) -> None:
    """PRD 2.3: every collection is ordered by `created_at` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows should be ascending by created_at: {stamps}"
