"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CORN_GRADE_TABLE,
    SOYBEANS_GRADE_TABLE,
    THRESHOLDS,
)


# --------------------------------------------------------------------------- #
# Common record properties
# --------------------------------------------------------------------------- #

def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every persisted resource carries a server-minted `id` (a UUID string with
    no type prefix), a `created_at`, an `updated_at` and a `version` that begins
    at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """An appeal vote carries only `id` and `created_at` — it has no
    `updated_at` and no `version` field at all."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "an appeal vote must carry no updated_at field"
    assert "version" not in data, "an appeal vote must carry no version field"


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{label} must be UTC and end with Z, got {value!r}"
    assert len(value) >= 24 and value[-5] == ".", (
        f"{label} must carry three fractional digits, got {value!r}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """`api_request_id` starts with `req_` and `api_request_timestamp` is an
    ISO 8601 UTC timestamp with three fractional digits."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_millisecond_timestamp(meta["api_request_timestamp"], "api_request_timestamp")


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #

def assert_service_area(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 1 <= len(data["name"]) <= 120
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert data["authority_type"] in ("DELEGATED", "DESIGNATED")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert 10000 <= data["fee_multiplier_bp"] <= 15000
    assert isinstance(data["supervision_required"], bool)
    assert data["concurrent_watch_capacity"] >= 1
    assert data["open_watch_count"] >= 0


def assert_fee_schedule(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["service_class"] in (
        "GRADING",
        "WEIGHING",
        "PROTEIN",
        "EXPORT_SUPERVISION",
        "APPEAL",
    )
    assert data["base_fee_cents"] >= 0
    assert data["per_thousand_bushel_rate_cents"] >= 0
    assert 0 <= data["overtime_multiplier_bp"] <= 10000
    assert data["minimum_fee_cents"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_applicant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert 3 <= len(data["account_code"]) <= 20
    assert data["credit_limit_cents"] >= 0
    assert_ledger_conserved(data)


def assert_ledger_conserved(applicant: Dict[str, Any]) -> None:
    """`open_balance_cents` is always `charges_total_cents` minus
    `credits_total_cents`."""
    charges = applicant["charges_total_cents"]
    credits = applicant["credits_total_cents"]
    open_balance = applicant["open_balance_cents"]
    assert isinstance(charges, int) and isinstance(credits, int), "money is integer cents"
    assert isinstance(open_balance, int), "money is integer cents"
    assert open_balance == charges - credits, (
        f"open_balance_cents must equal {charges} - {credits} = {charges - credits}, "
        f"got {open_balance}"
    )


def assert_ledger(
    applicant: Dict[str, Any], charges: int, credits: int, open_balance: int
) -> None:
    assert applicant["charges_total_cents"] == charges, (
        f"charges_total_cents expected {charges}, got {applicant['charges_total_cents']}"
    )
    assert applicant["credits_total_cents"] == credits, (
        f"credits_total_cents expected {credits}, got {applicant['credits_total_cents']}"
    )
    assert applicant["open_balance_cents"] == open_balance, (
        f"open_balance_cents expected {open_balance}, got {applicant['open_balance_cents']}"
    )
    assert_ledger_conserved(applicant)


def assert_inspector(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["license_status"] in (
        "PROBATIONARY",
        "ACTIVE",
        "SUSPENDED",
        "REVOKED",
        "EXPIRED",
    )
    assert len(data["endorsements"]) >= 1
    for endorsement in data["endorsements"]:
        assert endorsement in ("SAMPLING", "GRADING", "PROTEIN", "WEIGHING", "SUPERVISION")
    assert isinstance(data["performance_score"], int)
    assert 0 <= data["performance_score"] <= 100, (
        f"performance_score must be clamped into 0..100, got {data['performance_score']}"
    )
    assert data["training_hours_completed"] >= 0
    assert data["appeal_reversal_count"] >= 0
    assert data["check_sample_deviation_count"] >= 0
    assert data["late_certificate_count"] >= 0


def assert_performance_score(inspector: Dict[str, Any]) -> None:
    """The score is a weighted deduction from a perfect 100: 18 per appeal
    reversal, 10 per proficiency deviation, 3 per late certificate, plus a
    training credit of whole ten-hour blocks capped at 12, clamped to 0..100."""
    raw = (
        100
        - THRESHOLDS["APPEAL_REVERSAL_PENALTY"] * inspector["appeal_reversal_count"]
        - THRESHOLDS["CHECK_DEVIATION_PENALTY"] * inspector["check_sample_deviation_count"]
        - THRESHOLDS["LATE_CERTIFICATE_PENALTY"] * inspector["late_certificate_count"]
        + min(
            THRESHOLDS["TRAINING_CREDIT_CAP"],
            inspector["training_hours_completed"] // THRESHOLDS["TRAINING_CREDIT_BLOCK_HOURS"],
        )
    )
    expected = max(0, min(100, raw))
    assert inspector["performance_score"] == expected, (
        f"performance_score expected {expected}, got {inspector['performance_score']}"
    )


def assert_equipment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["equipment_kind"] in ("SAMPLING_DEVICE", "SCALE", "PROTEIN_INSTRUMENT")
    assert data["approval_status"] in (
        "PENDING_APPROVAL",
        "APPROVED",
        "DRIFT_WATCH",
        "OUT_OF_TOLERANCE",
        "WITHDRAWN",
        "EXPIRED",
    )
    assert 1 <= len(data["asset_code"]) <= 40
    assert isinstance(data["recent_deviations_pct"], list)
    assert len(data["recent_deviations_pct"]) <= THRESHOLDS["ROLLING_WINDOW_SIZE"], (
        "recent_deviations_pct keeps at most the three most recent deviations"
    )
    assert data["comparison_check_count"] >= 0
    assert data["consecutive_out_of_tolerance_checks"] >= 0
    if data["equipment_kind"] == "SCALE":
        assert data["capacity_lbs"] is not None
        assert data["tolerance_lbs"] is not None
    else:
        assert data["capacity_lbs"] is None
        assert data["tolerance_lbs"] is None


def assert_inspection_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["commodity"] in ("CORN", "SOYBEANS")
    assert data["point_of_service"] in ("LOADING", "UNLOADING")
    assert data["declared_quantity_bushels"] > 0
    assert "GRADING" in data["requested_services"], (
        "requested_services must include GRADING"
    )
    assert data["grading_status"] in (
        "OPEN",
        "SAMPLED",
        "GRADED",
        "GRADE_CERTIFIED",
        "UNDER_APPEAL",
    )
    assert data["weighing_status"] in (
        "NOT_REQUIRED",
        "PENDING",
        "WEIGHED",
        "SUPERVISED",
        "WEIGHT_CERTIFIED",
    )
    assert data["grade_revision_count"] >= 0


def assert_sample(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["sample_type"] in ("ORIGINAL", "FILE", "APPEAL")
    assert data["integrity_status"] in ("SEALED", "CONSUMED", "BROKEN", "EXPIRED")
    assert 1 <= data["portions_count"] <= 10
    assert_portion_accounting(data)
    assert_millisecond_timestamp(data["collected_at"], "collected_at")
    assert_millisecond_timestamp(data["file_retention_until"], "file_retention_until")


def assert_portion_accounting(sample: Dict[str, Any]) -> None:
    """`portions_available` is always `portions_count` less `portions_consumed`
    less `portions_retained`."""
    expected = (
        sample["portions_count"] - sample["portions_consumed"] - sample["portions_retained"]
    )
    assert sample["portions_available"] == expected, (
        f"portions_available must equal {sample['portions_count']} - "
        f"{sample['portions_consumed']} - {sample['portions_retained']} = {expected}, "
        f"got {sample['portions_available']}"
    )


def assert_grading_result(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in ("FINAL", "SUPERSEDED")
    assert data["assigned_grade"] in (
        "US_NO_1",
        "US_NO_2",
        "US_NO_3",
        "US_NO_4",
        "US_NO_5",
        "SAMPLE_GRADE",
    )
    assert data["limiting_factor"] in (
        "NONE",
        "TEST_WEIGHT",
        "MOISTURE",
        "DAMAGED_TOTAL",
        "HEAT_DAMAGED",
        "FOREIGN_MATERIAL",
    )
    assert_rounded_factors(data)


def assert_rounded_factors(grading: Dict[str, Any]) -> None:
    """Each of the five observed factors is rounded to one decimal place, half
    up, and stored under `rounded_factors`."""
    rounded = grading["rounded_factors"]
    for key in (
        "test_weight_lbs_per_bushel",
        "moisture_pct",
        "damaged_total_pct",
        "heat_damaged_pct",
        "foreign_material_pct",
    ):
        assert key in rounded, f"rounded_factors must carry {key}"
        assert round(rounded[key], 1) == rounded[key], (
            f"rounded_factors[{key}] must carry one decimal place, got {rounded[key]}"
        )


def assert_protein_analysis(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["basis_source"] in ("INSTRUMENT_MOISTURE", "OFFICIAL_MOISTURE")
    assert data["status"] in ("ACCEPTED", "RECOMPUTED", "REJECTED_CALIBRATION")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_weighing_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in ("WEIGHED", "SUPERVISED", "VOIDED")
    assert 1 <= len(data["drafts"]) <= 20
    assert isinstance(data["dockage_lbs"], int), "dockage is whole pounds"
    assert isinstance(data["net_lbs"], int), "net weights are whole pounds"
    assert isinstance(data["provisional_net_lbs"], int), "net weights are whole pounds"
    assert data["rounding_variance_lbs"] == data["provisional_net_lbs"] - data["net_lbs"], (
        "rounding_variance_lbs is provisional_net_lbs less net_lbs"
    )


def assert_certificate(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["certificate_type"] in (
        "GRADE",
        "WEIGHT",
        "COMBINED",
        "EXPORT_CARGO",
        "APPEAL_GRADE",
    )
    assert data["status"] in ("ISSUED", "UNDER_APPEAL", "VOIDED", "SUPERSEDED")
    assert data["fee_settlement_status"] in ("UNPAID", "PAID", "REVERSED")
    assert isinstance(data["fee_total_cents"], int), "money is integer cents"
    assert isinstance(data["fee_paid_cents"], int), "money is integer cents"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert_millisecond_timestamp(data["issued_at"], "issued_at")
    assert_millisecond_timestamp(
        data["reinspection_deadline_at"], "reinspection_deadline_at"
    )
    assert_millisecond_timestamp(data["appeal_deadline_at"], "appeal_deadline_at")


def assert_appeal(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["appeal_type"] in ("REINSPECTION", "APPEAL", "BOARD_APPEAL")
    assert data["status"] in (
        "FILED",
        "SAMPLE_ASSIGNED",
        "UNDER_REVIEW",
        "DECIDED_UPHELD",
        "DECIDED_REVISED",
        "DISMISSED",
    )
    expected_round, expected_panel = {
        "REINSPECTION": (1, 1),
        "APPEAL": (2, 3),
        "BOARD_APPEAL": (3, 5),
    }[data["appeal_type"]]
    assert data["round_number"] == expected_round
    assert data["required_panel_size"] == expected_panel
    assert_vote_tally(data)


def assert_vote_tally(appeal: Dict[str, Any]) -> None:
    """`effective_votes_count` is `revise_votes_count` plus
    `uphold_votes_count`; abstentions count toward neither side."""
    assert appeal["effective_votes_count"] == (
        appeal["revise_votes_count"] + appeal["uphold_votes_count"]
    ), (
        "effective_votes_count must be revise_votes_count plus uphold_votes_count, "
        f"got {appeal['effective_votes_count']}"
    )
    assert appeal["votes_cast_count"] == (
        appeal["revise_votes_count"]
        + appeal["uphold_votes_count"]
        + appeal["abstain_votes_count"]
    ), "votes_cast_count must be the sum of the three per-value counters"


def assert_appeal_vote(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data["vote"] in ("UPHOLD", "REVISE", "ABSTAIN")


def assert_vessel_watch(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED", "ABORTED")
    assert data["holds_declared"] >= 1
    assert isinstance(data["stowage_certified"], bool)


# --------------------------------------------------------------------------- #
# Grade table helper
# --------------------------------------------------------------------------- #

def expected_grade_and_limiting_factor(commodity: str, rounded: Dict[str, float]):
    """Walk the official table from the best grade downwards and return the
    (assigned_grade, limiting_factor) pair the PRD's rules produce."""
    table = CORN_GRADE_TABLE if commodity == "CORN" else SOYBEANS_GRADE_TABLE
    values = [
        rounded["test_weight_lbs_per_bushel"],
        rounded["moisture_pct"],
        rounded["damaged_total_pct"],
        rounded["heat_damaged_pct"],
        rounded["foreign_material_pct"],
    ]

    def satisfies(row):
        _, min_tw, max_moist, max_dmg, max_heat, max_fm = row
        return (
            values[0] >= min_tw
            and values[1] <= max_moist
            and values[2] <= max_dmg
            and values[3] <= max_heat
            and values[4] <= max_fm
        )

    assigned_index: Optional[int] = None
    for index, row in enumerate(table):
        if satisfies(row):
            assigned_index = index
            break

    if assigned_index == 0:
        return table[0][0], "NONE"

    better = table[assigned_index - 1] if assigned_index is not None else table[-1]
    grade = table[assigned_index][0] if assigned_index is not None else "SAMPLE_GRADE"
    _, min_tw, max_moist, max_dmg, max_heat, max_fm = better
    if values[0] < min_tw:
        return grade, "TEST_WEIGHT"
    if values[1] > max_moist:
        return grade, "MOISTURE"
    if values[2] > max_dmg:
        return grade, "DAMAGED_TOTAL"
    if values[3] > max_heat:
        return grade, "HEAT_DAMAGED"
    return grade, "FOREIGN_MATERIAL"
