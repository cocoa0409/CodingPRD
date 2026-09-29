"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountPosture,
    ApprovalConditionStatus,
    ClaimFilingStatus,
    ClaimVerificationStatus,
    DocketPhase,
    ForfeitureRiskBand,
    HcuStudyStatus,
    InjuryAnalysisStatus,
    LeaseStatus,
    PaymentStatus,
    PointOfDiversionStatus,
    ProtestStatus,
    StandingStatus,
    TransferApplicationStatus,
    WaterRightStatus,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]  # noqa: E731


def _parse_instant(value: str):
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    from datetime import datetime, timezone

    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 UTC timestamps as instants rather than as strings.

    PRD §2.5 pins the *width* of `created_at` and `updated_at` at three
    fractional digits, and says nothing at all about the serialised width of the
    domain instants it derives from the logical clock (`protest_deadline`,
    `certified_at`, an echoed `claim_filing_deadline`). What the PRD does pin is
    the instant itself — "`protest_deadline` is stamped from the logical clock at
    thirty days out" (§3.5), "`certified_at` with the logical clock" (§3.3). This
    helper asserts exactly that pinned instant, at full strength, without
    asserting a fractional-digit width the PRD never states.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label} must be the instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    """PRD §2.5 — id, created_at, updated_at and version on every resource
    except the append-only beneficial-use record."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer beginning at 1, got "
        f"{data.get('version')!r}"
    )


def assert_money_precision(value: float, label: str = "amount") -> None:
    """PRD §2.8 — dollar amounts are carried at 2 decimal places."""
    assert value == pytest.approx(round(value + 0.0, 2), abs=1e-9), (
        f"{label} must be carried at 2 decimal places, got {value!r}"
    )


def assert_volume_precision(value: float, label: str = "volume") -> None:
    """PRD §2.8 — acre-foot volumes are carried at 2 decimal places."""
    assert value == pytest.approx(round(value + 0.0, 2), abs=1e-9), (
        f"{label} must be carried at 2 decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_claimant(data: dict) -> None:
    _assert_common_fields(data, "Claimant")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert "@" in data["contact_email"]
    assert data["entity_type"] in [
        "INDIVIDUAL",
        "IRRIGATION_DISTRICT",
        "MUNICIPALITY",
        "TRIBE",
    ]
    assert data["standing_status"] in _MEMBERS(StandingStatus)
    assert data["outstanding_fee_balance_usd"] >= 0
    assert data["open_application_count"] >= 0


def assert_water_right(data: dict) -> None:
    _assert_common_fields(data, "WaterRight")
    assert is_valid_uuid(data["claimant_id"])
    assert isinstance(data["right_number"], str) and 1 <= len(data["right_number"]) <= 40
    assert is_iso8601_timestamp(data["priority_date"])
    assert data["purpose_of_use"] in [
        "IRRIGATION",
        "MUNICIPAL",
        "STOCKWATER",
        "INDUSTRIAL",
        "INSTREAM_FLOW",
    ]
    assert data["place_of_use_acres"] >= 0
    assert data["authorized_diversion_af"] > 0
    assert data["authorized_rate_cfs"] > 0
    assert data["status"] in _MEMBERS(WaterRightStatus)
    assert data["forfeiture_risk_band"] in _MEMBERS(ForfeitureRiskBand)
    assert data["consecutive_nonuse_years"] >= 0
    assert_water_right_ledger_identity(data)


def assert_point_of_diversion(data: dict) -> None:
    _assert_common_fields(data, "PointOfDiversion")
    assert is_valid_uuid(data["water_right_id"])
    assert 1 <= len(data["legal_description"]) <= 120
    assert 1 <= len(data["stream_reach_code"]) <= 24
    assert data["max_rate_cfs"] > 0
    assert data["stream_miles_from_headwater"] >= 0
    assert data["status"] in _MEMBERS(PointOfDiversionStatus)


def assert_beneficial_use_record(data: dict) -> None:
    """PRD §2.5 — a record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), "BeneficialUseRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "BeneficialUseRecord has no updated_at field at all"
    )
    assert "version" not in data, "BeneficialUseRecord has no version field at all"
    assert 1850 <= data["use_year"] <= 2100
    assert data["reported_diversion_af"] >= 0
    assert data["irrigated_acres"] >= 0
    assert data["verification_source"] in ["METER", "AERIAL_IMAGERY", "AFFIDAVIT", "NONE"]


def assert_hcu_study(data: dict) -> None:
    _assert_common_fields(data, "HcuStudy")
    assert data["method"] in ["DIVERSION_BASED", "CIR_BASED"]
    assert data["study_period_end_year"] >= data["study_period_start_year"]
    assert data["qualifying_year_count"] >= 0
    assert isinstance(data["short_history_haircut_applied"], bool)
    assert data["status"] in _MEMBERS(HcuStudyStatus)
    assert_volume_precision(data["transferable_cu_af"], "HcuStudy.transferable_cu_af")


def assert_transfer_application(data: dict) -> None:
    _assert_common_fields(data, "TransferApplication")
    assert data["application_type"] in [
        "CHANGE_OF_USE",
        "POINT_OF_DIVERSION_CHANGE",
        "PLACE_OF_USE_CHANGE",
        "COMBINED",
    ]
    assert data["requested_af"] > 0
    assert data["status"] in _MEMBERS(TransferApplicationStatus)
    assert 0 <= data["revision_round"] <= 2
    assert data["unresolved_protest_count"] >= 0
    assert data["escrowed_af"] >= 0
    assert data["mitigation_fee_total_usd"] >= 0
    assert_escrow_matches_status(data)


def assert_injury_analysis(data: dict) -> None:
    _assert_common_fields(data, "InjuryAnalysis")
    assert data["method"] in ["INSTANTANEOUS_DEPLETION", "SEASONAL_AVERAGE"]
    assert data["pod_move_miles"] >= 0
    assert data["return_flow_credit_af"] >= 0
    assert data["offset_af"] >= 0
    assert data["gross_depletion_af"] >= 0
    assert data["net_injury_af"] >= 0, (
        "PRD §3.5 floors net_injury_af at 0.00, so it can never be negative"
    )
    assert data["status"] in _MEMBERS(InjuryAnalysisStatus)


def assert_protest(data: dict) -> None:
    _assert_common_fields(data, "Protest")
    assert data["claimed_injury_af"] > 0
    assert data["basis"] in [
        "INJURY_TO_SENIOR_RIGHT",
        "PUBLIC_INTEREST",
        "ENLARGEMENT",
        "NO_BENEFICIAL_USE",
    ]
    assert data["track"] in [None, "NEGOTIATION", "HEARING"]
    assert data["status"] in _MEMBERS(ProtestStatus)
    assert data["stipulated_offset_af"] >= 0


def assert_approval_condition(data: dict) -> None:
    _assert_common_fields(data, "ApprovalCondition")
    assert data["condition_type"] in [
        "DRY_YEAR_FORBEARANCE",
        "MEASUREMENT_DEVICE",
        "RETURN_FLOW_MAINTENANCE",
        "MITIGATION_PAYMENT",
    ]
    assert data["required_af"] >= 0
    assert data["source"] in ["DECISION", "HEARING_RESOLUTION"]
    assert data["status"] in _MEMBERS(ApprovalConditionStatus)
    assert data["payment_status"] in _MEMBERS(PaymentStatus)
    assert_money_precision(data["base_fee_usd"], "ApprovalCondition.base_fee_usd")
    assert_money_precision(
        data["admin_surcharge_usd"], "ApprovalCondition.admin_surcharge_usd"
    )
    assert_money_precision(data["total_fee_usd"], "ApprovalCondition.total_fee_usd")


def assert_water_bank_account(data: dict) -> None:
    _assert_common_fields(data, "WaterBankAccount")
    assert 1 <= len(data["basin_code"]) <= 24
    assert data["posture"] in _MEMBERS(AccountPosture)
    assert data["suspended_lease_count"] >= 0
    assert_bank_credit_identity(data)


def assert_lease_assignment(data: dict) -> None:
    _assert_common_fields(data, "LeaseAssignment")
    assert 1 <= len(data["lessee_name"]) <= 160
    assert data["lease_end_date"] > data["lease_start_date"]
    assert data["requested_af"] > 0
    assert data["diversion_rate_cfs"] > 0
    assert data["rental_rate_usd_per_af"] >= 0
    assert data["valuation_method"] in ["PRO_RATA_DAILY", "SEASON_BLOCK"]
    assert data["status"] in _MEMBERS(LeaseStatus)
    assert data["used_af"] >= 0
    assert data["settlement_credit_af"] >= 0
    assert data["suspension_count"] >= 0


def assert_decree_docket(data: dict) -> None:
    _assert_common_fields(data, "DecreeDocket")
    assert 1 <= len(data["basin_code"]) <= 24
    assert data["phase"] in _MEMBERS(DocketPhase)
    assert data["claim_count"] >= 0
    assert data["decreed_claim_count"] >= 0
    assert data["decreed_claim_count"] <= data["claim_count"]
    assert data["total_decreed_af"] >= 0


def assert_adjudication_claim(data: dict) -> None:
    _assert_common_fields(data, "AdjudicationClaim")
    assert data["claimed_af"] > 0
    assert data["filing_status"] in _MEMBERS(ClaimFilingStatus)
    assert data["verification_status"] in _MEMBERS(ClaimVerificationStatus)
    assert data["objection_count"] >= 0
    if data.get("examiner_recommended_af") is not None:
        assert 0 < data["examiner_recommended_af"] <= data["claimed_af"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_water_right_ledger_identity(right: dict) -> None:
    """PRD §2.9 — `certified_hcu_af` equals `transferable_af` plus
    `encumbered_af` plus `transferred_away_af`, exactly at 2 decimal places."""
    total = (
        right["transferable_af"] + right["encumbered_af"] + right["transferred_away_af"]
    )
    assert right["certified_hcu_af"] == pytest.approx(total, abs=0.01), (
        "PRD §2.9 identity violated: certified_hcu_af "
        f"{right['certified_hcu_af']} != transferable_af {right['transferable_af']} + "
        f"encumbered_af {right['encumbered_af']} + transferred_away_af "
        f"{right['transferred_away_af']}"
    )
    assert right["transferable_af"] >= 0, "transferable_af may never be negative"
    if right["status"] == WaterRightStatus.FORFEITED.value:
        for bucket in (
            "certified_hcu_af",
            "encumbered_af",
            "transferred_away_af",
            "transferable_af",
        ):
            assert right[bucket] == pytest.approx(0.00, abs=0.01), (
                f"a FORFEITED right pins {bucket} to 0.00"
            )


def assert_bank_credit_identity(account: dict) -> None:
    """PRD §2.9 — `deposited_credit_af` equals `available_credit_af` plus
    `committed_credit_af` plus `leased_out_af`, exactly at 2 decimal places."""
    total = (
        account["available_credit_af"]
        + account["committed_credit_af"]
        + account["leased_out_af"]
    )
    assert account["deposited_credit_af"] == pytest.approx(total, abs=0.01), (
        "PRD §2.9 credit identity violated: deposited_credit_af "
        f"{account['deposited_credit_af']} != available {account['available_credit_af']}"
        f" + committed {account['committed_credit_af']} + leased_out "
        f"{account['leased_out_af']}"
    )
    assert account["available_credit_af"] >= 0


def assert_right_status_derivation(right: dict) -> None:
    """PRD §2.10 — the derived-status precedence, first match winning."""
    status = right["status"]
    if status in (
        WaterRightStatus.FORFEITED.value,
        WaterRightStatus.SUSPENDED.value,
        WaterRightStatus.UNADJUDICATED.value,
    ):
        return
    if right["transferred_away_af"] > 0.00:
        assert status == WaterRightStatus.PARTIALLY_TRANSFERRED.value, (
            "transferred_away_af above 0.00 outranks encumbered_af"
        )
    elif right["encumbered_af"] > 0.00:
        assert status == WaterRightStatus.ENCUMBERED.value
    else:
        assert status == WaterRightStatus.ACTIVE.value


def assert_account_posture_derivation(account: dict) -> None:
    """PRD §2.10 — the credit floor is strict: exactly 5.00 is not RESTRICTED."""
    if account["suspended_lease_count"] >= 1:
        assert account["posture"] == AccountPosture.FROZEN.value, (
            "a single suspended lease is already enough for FROZEN"
        )
    elif account["available_credit_af"] < 5.00:
        assert account["posture"] in (
            AccountPosture.RESTRICTED.value,
            AccountPosture.FROZEN.value,
        )


def assert_escrow_matches_status(application: dict) -> None:
    """PRD §3.4 — `escrowed_af` equals `requested_af` for exactly as long as the
    status is one of the five pending states and reads 0.00 otherwise."""
    pending = {
        TransferApplicationStatus.SUBMITTED.value,
        TransferApplicationStatus.PROTEST_PERIOD.value,
        TransferApplicationStatus.UNDER_PROTEST.value,
        TransferApplicationStatus.REVISION_REQUESTED.value,
        TransferApplicationStatus.READY_FOR_DECISION.value,
    }
    if application["status"] in pending:
        assert application["escrowed_af"] == pytest.approx(
            application["requested_af"], abs=0.01
        ), "a pending application escrows exactly its requested_af"
    else:
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01), (
            f"escrowed_af must read 0.00 in status {application['status']}"
        )


def assert_error_envelope(error_data: dict) -> None:
    """PRD §2.2 — every error body carries an `error_id` and a `message`."""
    assert isinstance(error_data.get("error_id"), str) and error_data["error_id"]
    assert isinstance(error_data.get("message"), str) and error_data["message"].strip()


def assert_request_meta(body: dict) -> None:
    """PRD §2.2 — `api_request_id` starts with `req_` and the timestamp is ISO."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
