"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    LEDGER_ENTRY_TYPES,
    MILESTONE_WEIGHTS_BPS,
    NEGATIVE_LEDGER_ENTRY_TYPES,
    POSITIVE_LEDGER_ENTRY_TYPES,
    RELATED_REF_TYPES,
)

_DATE = "%Y-%m-%d"


# --- Generic shape helpers ---------------------------------------------------


def assert_common_fields(data: dict):
    """PRD §2.4: every entity except LedgerEntry carries id, created_at,
    updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_no_mutation_fields(data: dict):
    """PRD §2.4: an append-only row has no updated_at and no version."""
    assert "updated_at" not in data, "an append-only row must not carry updated_at"
    assert "version" not in data, "an append-only row must not carry version"


def assert_is_date(value, field="date"):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[
        7
    ] == "-", f"{field} must be YYYY-MM-DD, got {value!r}"


def assert_iso_week_key(value):
    assert (
        isinstance(value, str)
        and len(value) == 8
        and value[4] == "-"
        and value[5] == "W"
        and value[:4].isdigit()
        and value[6:].isdigit()
    ), f"iso_week_key must be YYYY-Wnn, got {value!r}"


# --- Entity assertions -------------------------------------------------------


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert "@" in data["primary_contact_email"]
    assert data["region_code"] in ("NY", "CA", "FL", "TX", "MA")
    assert data["status"] in ("PROSPECT", "ONBOARDED", "SUSPENDED")
    assert data["confidentiality_agreement_status"] in (
        "UNSIGNED",
        "SIGNED",
        "COUNTERSIGNED",
    )
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["placement_count"], int)
    assert data["placement_count"] >= 0


def assert_fee_schedule(data: dict):
    assert_common_fields(data)
    assert data["role_type"] in ("ESTATE_MANAGER", "HOUSEKEEPER", "CHEF", "CHAUFFEUR")
    assert isinstance(data["comp_band_floor_cents"], int)
    assert data["comp_band_floor_cents"] >= 0
    assert 1 <= data["fee_percent_bps"] <= 10000
    assert 1 <= data["guarantee_window_days"] <= 365
    assert_is_date(data["effective_from"], "effective_from")
    assert data["status"] in ("ACTIVE", "RETIRED")
    if data["comp_band_ceiling_cents"] is not None:
        assert data["comp_band_ceiling_cents"] > data["comp_band_floor_cents"]


def assert_requisition(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["role_type"] in ("ESTATE_MANAGER", "HOUSEKEEPER", "CHEF", "CHAUFFEUR")
    assert data["first_year_compensation_cents"] >= 100_000
    assert isinstance(data["live_in_required"], bool)
    assert data["schedule_pattern"] in (
        "FIVE_TWO",
        "SIX_ONE",
        "ROTA_TWO_TWO",
        "ON_CALL",
    )
    assert data["status"] in (
        "DRAFT",
        "SCOPING",
        "SOURCING",
        "TRIALING",
        "OFFER_PENDING",
        "PLACED",
        "WITHDRAWN",
    )
    assert 0 <= data["scoping_round"] <= 3
    assert data["active_trial_count"] >= 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_candidate(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert "@" in data["contact_email"]
    assert data["primary_role_type"] in (
        "ESTATE_MANAGER",
        "HOUSEKEEPER",
        "CHEF",
        "CHAUFFEUR",
    )
    assert 0 <= data["years_experience"] <= 60
    assert isinstance(data["live_in_willing"], bool)
    assert data["vetting_status"] in (
        "UNVETTED",
        "SCREENING",
        "REFERENCES_VERIFIED",
        "BACKGROUND_PENDING",
        "CLEARED",
        "REJECTED",
    )
    assert data["availability_status"] in (
        "AVAILABLE",
        "ON_TRIAL",
        "OFFER_HELD",
        "PLACED",
        "COOLING_OFF",
        "INACTIVE",
    )
    assert data["verified_reference_count"] >= 0
    assert data["reference_coverage_months"] >= 0
    assert data["longest_contiguous_months"] >= 0
    assert 0 <= data["screening_score"] <= 100
    assert 0 <= data["placement_ready_score"] <= 100


def assert_reference_check(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["principal_employer_name"], str)
    assert data["relationship_type"] in (
        "PRINCIPAL_EMPLOYER",
        "AGENCY_SUPERVISOR",
        "PEER",
    )
    for key in ("employment_start_month", "employment_end_month"):
        assert (
            isinstance(data[key], str) and len(data[key]) == 7 and data[key][4] == "-"
        ), f"{key} must be YYYY-MM, got {data[key]!r}"
    assert data["employment_start_month"] <= data["employment_end_month"]
    assert data["status"] in ("PENDING", "VERIFIED", "UNREACHABLE", "DISPUTED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_background_verification(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["provider_reference"], str) and data["provider_reference"]
    assert isinstance(data["scope_items"], list) and data["scope_items"]
    for item in data["scope_items"]:
        assert item in ("IDENTITY", "CRIMINAL", "DMV", "CREDENTIAL", "SOCIAL_MEDIA")
    assert data["status"] in (
        "INITIATED",
        "CLEARED",
        "FLAGGED",
        "INCONCLUSIVE",
        "ADJUDICATED_PASS",
        "ADJUDICATED_FAIL",
    )
    assert data["rerun_count"] >= 0


def assert_trial_engagement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["requisition_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["client_id"])
    assert data["engagement_type"] in ("TRIAL_DAY", "WORKING_INTERVIEW")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["end_at"] > data["start_at"]
    assert data["day_rate_cents"] >= 0
    assert_iso_week_key(data["iso_week_key"])
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "PASSED",
        "FAILED",
        "CANCELLED",
    )
    if data["cancel_reason"] is not None:
        assert data["cancel_reason"] in (
            "CLIENT_REQUEST",
            "CANDIDATE_WITHDRAWN",
            "VETTING_FAILED",
            "CLIENT_SUSPENDED",
        )


def assert_accommodation_term(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["requisition_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert data["round_no"] >= 0
    assert isinstance(data["live_in"], bool)
    assert 1 <= data["weekly_hours"] <= 80
    assert 0 <= data["days_off_per_week"] <= 7
    assert isinstance(data["private_quarters"], bool)
    assert data["imputed_accommodation_cents"] >= 0
    assert data["status"] in (
        "PROPOSED",
        "COUNTERED",
        "ACCEPTED",
        "REJECTED",
        "SUPERSEDED",
    )
    if data["last_responder_role"] is not None:
        assert data["last_responder_role"] in ("CLIENT", "CANDIDATE")


def assert_placement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["requisition_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["client_id"])
    assert_is_date(data["start_date"], "start_date")
    for key in (
        "base_salary_cents",
        "guaranteed_bonus_cents",
        "accommodation_imputed_cents",
        "overtime_allowance_cents",
    ):
        assert data[key] >= 0, f"{key} must not be negative"
    assert data["fee_variant"] in ("PROVISIONAL", "FINAL")
    assert data["fee_cents"] >= 0
    assert 1 <= data["fee_percent_bps"] <= 10000
    assert 1 <= data["guarantee_window_days"] <= 365
    assert_is_date(data["guarantee_expires_on"], "guarantee_expires_on")
    assert data["placement_status"] in (
        "PENDING_ACCEPTANCE",
        "ACTIVE",
        "VOIDED",
        "TERMINATED_NO_REMEDY",
        "TERMINATED_REPLACED",
        "TERMINATED_REFUNDED",
        "GUARANTEE_EXPIRED",
    )
    assert data["billing_status"] in (
        "UNBILLED",
        "PARTIALLY_BILLED",
        "FULLY_BILLED",
        "REVERSED",
        "REFUNDED",
    )
    if data["void_reason"] is not None:
        assert data["void_reason"] in ("SUPERSEDED_BY_NEW_OFFER", "CLIENT_WITHDRAWN")
    assert (
        data["actual_first_year_compensation_cents"]
        == data["base_salary_cents"]
        + data["guaranteed_bonus_cents"]
        + data["accommodation_imputed_cents"]
        + data["overtime_allowance_cents"]
    ), "the four package components must sum to the first-year compensation"


def assert_fee_milestone(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert data["milestone_type"] in ("ENGAGEMENT", "TRIAL_CLEARED", "START_DATE")
    assert data["sequence_no"] in (1, 2, 3)
    assert data["weight_bps"] == MILESTONE_WEIGHTS_BPS[data["milestone_type"]]
    assert data["amount_cents"] >= 0
    assert data["invoice_status"] in (
        "PENDING",
        "INVOICED",
        "OVERDUE",
        "PAID",
        "REVERSED",
        "VOIDED",
    )
    if data["invoiced_on"] is not None:
        assert_is_date(data["invoiced_on"], "invoiced_on")
        assert_is_date(data["due_date"], "due_date")


def assert_replacement_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert data["requested_remedy"] in ("REPLACEMENT", "REFUND")
    assert_is_date(data["separation_date"], "separation_date")
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVED_REPLACEMENT",
        "APPROVED_REFUND",
        "DENIED",
        "SUPERSEDED",
    )
    assert data["info_request_round"] >= 0


def assert_payroll_handoff(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["ein_status"] in ("NOT_APPLIED", "APPLIED", "ISSUED")
    assert data["status"] in ("PREPARED", "ATTESTED")
    if data["status"] == "ATTESTED":
        assert data["attested_by_name"]
        assert is_iso8601_timestamp(data["attested_at"])


def assert_non_solicitation_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["respondent_client_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert_is_date(data["discovered_on"], "discovered_on")
    assert data["status"] in (
        "ALLEGED",
        "INVESTIGATING",
        "SUBSTANTIATED",
        "UNSUBSTANTIATED",
        "SETTLED",
    )
    assert data["prior_substantiated_count"] >= 0
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_ledger_entry(data: dict):
    """PRD §2.4: a ledger row carries only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert_no_mutation_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["sequence_no"] >= 1
    assert data["entry_type"] in LEDGER_ENTRY_TYPES
    assert isinstance(data["signed_amount_cents"], int)
    assert data["related_ref_type"] in RELATED_REF_TYPES
    if data["related_ref_type"] == "NONE":
        assert data["related_ref_id"] is None
    assert isinstance(data["balance_after_cents"], int)


# --- Domain invariants -------------------------------------------------------


def assert_ledger_sign_convention(entry: dict):
    """PRD §2.12: the sign is fixed per entry_type."""
    entry_type = entry["entry_type"]
    amount = entry["signed_amount_cents"]
    if entry_type in POSITIVE_LEDGER_ENTRY_TYPES:
        assert amount > 0, f"{entry_type} must be positive, got {amount}"
    elif entry_type in NEGATIVE_LEDGER_ENTRY_TYPES:
        assert amount < 0, f"{entry_type} must be negative, got {amount}"
    else:
        assert amount != 0, "MANUAL_ADJUSTMENT must never be zero"


def assert_ledger_fold(entries: list):
    """PRD §2.12: balance_after_cents on each row is the running sum, and the
    rows are returned in ascending sequence_no order."""
    running = 0
    previous_sequence = 0
    for entry in entries:
        assert (
            entry["sequence_no"] > previous_sequence
        ), "ledger rows must ascend by sequence_no"
        previous_sequence = entry["sequence_no"]
        assert_ledger_sign_convention(entry)
        running += entry["signed_amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"balance_after_cents at sequence {entry['sequence_no']} should be "
            f"{running}, got {entry['balance_after_cents']}"
        )
    return running


def assert_milestone_allocation(milestones: list, fee_cents: int):
    """PRD §3.7: the three milestone amounts always sum to the placement fee, and
    they are returned in ascending sequence_no order."""
    ordered = sorted(milestones, key=lambda m: m["sequence_no"])
    assert [m["sequence_no"] for m in ordered] == [1, 2, 3]
    assert [m["milestone_type"] for m in ordered] == [
        "ENGAGEMENT",
        "TRIAL_CLEARED",
        "START_DATE",
    ]
    total = sum(m["amount_cents"] for m in ordered)
    assert total == fee_cents, (
        f"milestone amounts must sum to fee_cents {fee_cents}, got {total}"
    )
    return ordered


def assert_fee_snapshot_matches(placement: dict, requisition: dict):
    """PRD §3.6: the offer copies the requisition's resolved fee snapshot."""
    assert placement["snapshot_fee_schedule_id"] == requisition["resolved_fee_schedule_id"]
    assert placement["fee_percent_bps"] == requisition["fee_percent_bps"]
    assert placement["guarantee_window_days"] == requisition["guarantee_window_days"]


def assert_score_variants(candidate: dict, screening: int, placement_ready: int):
    """PRD §3.3: the two score variants are read from the same candidate row."""
    assert candidate["screening_score"] == screening, (
        f"screening_score should be {screening}, got {candidate['screening_score']}"
    )
    assert candidate["placement_ready_score"] == placement_ready, (
        f"placement_ready_score should be {placement_ready}, "
        f"got {candidate['placement_ready_score']}"
    )


def assert_state(data: dict, field: str, expected: str):
    assert data[field] == expected, (
        f"{field} should be {expected}, got {data[field]}"
    )


def find_milestone(milestones: list, milestone_type: str) -> dict:
    for milestone in milestones:
        if milestone["milestone_type"] == milestone_type:
            return milestone
    raise AssertionError(f"no {milestone_type} milestone in {milestones!r}")


def find_ledger_entries(entries: list, entry_type: str) -> list:
    return [entry for entry in entries if entry["entry_type"] == entry_type]
