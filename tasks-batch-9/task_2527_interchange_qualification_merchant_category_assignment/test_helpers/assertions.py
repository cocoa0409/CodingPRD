"""Shape and invariant assertions.

The per-entity helpers check the field set the PRD declares for a resource,
plus the four common fields of PRD Section 2.4 ("Every resource exposes `id`,
`created_at`, `updated_at` and `version`"). The invariant helpers check the two
conserved quantities of PRD Section 2.10.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data["created_at"]), data.get("created_at")
    assert is_iso8601_timestamp(data["updated_at"]), data.get("updated_at")
    assert isinstance(data["version"], int) and data["version"] >= 1, data.get("version")


def _assert_fields(data: dict, fields) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"response is missing declared fields: {missing}"


def assert_processing_platform(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        ["name", "region_code", "max_concurrent_windows", "blackout_buffer_days"],
    )
    assert data["region_code"] in ("NA", "EU", "AP", "LAC", "CEMEA")
    assert data["max_concurrent_windows"] >= 1
    assert data["blackout_buffer_days"] >= 0


def assert_acquirer(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "name",
            "bin_prefix",
            "platform_id",
            "country_code",
            "settlement_currency",
            "compliance_status",
            "missed_window_count",
        ],
    )
    assert data["compliance_status"] in ("COMPLIANT", "NON_COMPLIANT")
    assert data["missed_window_count"] >= 0


def assert_mcc_definition(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "mcc_code",
            "description",
            "business_type_key",
            "program_eligibility",
            "requires_documentation",
            "high_risk",
        ],
    )
    assert len(data["mcc_code"]) == 4 and data["mcc_code"].isdigit()
    assert isinstance(data["program_eligibility"], list)


def assert_rate_program(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "program_code",
            "name",
            "category",
            "eligible_mcc_codes",
            "base_rate_bps",
            "per_item_fee_cents",
            "requires_data_elements",
            "max_clearing_delay_hours",
        ],
    )
    assert data["category"] in (
        "CPS_RETAIL",
        "SMALL_TICKET",
        "UTILITY",
        "GOVERNMENT",
        "CHARITY",
        "STANDARD",
    )
    assert 0 <= data["base_rate_bps"] <= 1000
    assert 0 <= data["per_item_fee_cents"] <= 500


def assert_rate_program_version(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "rate_program_id",
            "publication_quarter",
            "effective_from",
            "effective_to",
            "base_rate_bps",
            "per_item_fee_cents",
            "implementation_deadline",
            "status",
            "published_at",
        ],
    )
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_implementation_window(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "acquirer_id",
            "rate_program_version_id",
            "platform_id",
            "window_start",
            "window_end",
            "status",
            "started_at",
            "completion_note",
        ],
    )
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "COMPLETED_LATE",
        "MISSED",
    )


def assert_merchant(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "legal_name",
            "business_type_key",
            "acquirer_id",
            "home_country_code",
            "assigned_mcc",
            "mcc_status",
            "mcc_status_before_review",
            "documentation_ref",
            "verified_by_user_id",
            "downgrade_count_current_quarter",
            "lifetime_net_assessed_cents",
        ],
    )
    assert data["mcc_status"] in (
        "PENDING_VERIFICATION",
        "VERIFIED",
        "UNDER_REVIEW",
        "MISREPRESENTED",
    )
    assert len(data["assigned_mcc"]) == 4 and data["assigned_mcc"].isdigit()


def assert_reclassification_request(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "merchant_id",
            "requested_mcc",
            "justification",
            "status",
            "review_round",
            "supporting_doc_ref",
            "reviewer_user_id",
            "info_request_note",
            "decider_user_id",
            "decision_note",
            "decided_mcc",
            "prior_status_before_suspension",
        ],
    )
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVED",
        "DENIED",
        "SUPERSEDED",
        "SUSPENDED_PENDING_AUDIT",
    )
    assert data["review_round"] >= 1


def assert_fx_rate(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        ["base_currency", "quote_currency", "rate", "markup_bps", "effective_from"],
    )
    assert float(data["rate"]) > 0
    assert 0 <= data["markup_bps"] <= 500


def assert_settlement_batch(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "acquirer_id",
            "batch_date",
            "currency_code",
            "status",
            "record_count",
            "total_assessed_cents",
            "finalized_at",
        ],
    )
    assert data["status"] in ("OPEN", "SUBMITTED", "FINALIZED")
    assert data["record_count"] >= 0
    assert data["total_assessed_cents"] >= 0


def assert_transaction_record(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "settlement_batch_id",
            "merchant_id",
            "amount_cents",
            "transaction_currency",
            "auth_code",
            "auth_timestamp",
            "clearing_timestamp",
            "data_elements",
            "clearing_delay_hours",
            "cross_border",
            "authorization_status",
            "qualification_status",
            "provisional_rate_program_id",
            "provisional_assessed_cents",
            "qualified_rate_program_id",
            "mcc_at_qualification",
            "downgrade_reason",
            "assessed_interchange_cents",
            "cross_border_surcharge_cents",
            "fx_markup_cents",
            "reversal_type",
            "reversal_reason",
        ],
    )
    assert data["authorization_status"] in (
        "AUTH_APPROVED",
        "AUTH_REVERSED",
        "AUTH_EXPIRED",
    )
    assert data["qualification_status"] in (
        "PENDING",
        "QUALIFIED",
        "DOWNGRADED",
        "REVERSED",
    )
    assert data["clearing_delay_hours"] >= 0
    assert isinstance(data["cross_border"], bool)


def assert_incentive_program(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "program_name",
            "eligible_mcc_codes",
            "total_capacity_cents",
            "min_commitment_cents",
            "reopen_threshold_cents",
            "performance_threshold_pct",
            "enrollment_state",
            "uncommitted_capacity_cents",
            "enrolled_count",
        ],
    )
    assert data["enrollment_state"] in ("OPEN", "CLOSED_FULL")
    assert data["total_capacity_cents"] > 0
    assert 0 <= data["uncommitted_capacity_cents"] <= data["total_capacity_cents"]
    assert data["enrolled_count"] >= 0


def assert_incentive_enrollment(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "incentive_program_id",
            "merchant_id",
            "committed_volume_cents",
            "waitlist_requested",
            "status",
            "enrolled_at",
            "achieved_volume_cents",
            "performance_score_pct",
            "last_evaluated_basis",
            "probation_count",
            "gross_assessed_volume_cents",
            "tier_code",
            "incentive_credit_cents",
            "net_assessed_volume_cents",
            "withdrawal_reason",
        ],
    )
    assert data["status"] in (
        "PENDING",
        "ENROLLED",
        "WAITLISTED",
        "PROBATION",
        "TERMINATED_SHORTFALL",
        "TERMINATED_INELIGIBLE",
        "WITHDRAWN",
    )
    assert data["status"] != "PENDING", (
        "PRD 3.8: `PENDING` exists only inside the creating request and is never "
        "observable"
    )
    assert data["committed_volume_cents"] > 0


def assert_merchant_category_audit(data: dict) -> None:
    assert_common_fields(data)
    _assert_fields(
        data,
        [
            "merchant_id",
            "trigger_reason",
            "status",
            "auditor_user_id",
            "fieldwork_start",
            "fieldwork_end",
            "correct_mcc",
            "findings_note",
            "mcc_at_audit_open",
            "penalty_assessed_cents",
            "closed_by_user_id",
        ],
    )
    assert data["status"] in (
        "SCHEDULED",
        "FIELDWORK",
        "FINDINGS_SUSTAINED",
        "FINDINGS_CLEARED",
        "CLOSED",
    )
    assert data["trigger_reason"] in (
        "DOWNGRADE_THRESHOLD",
        "RECLASS_SUSPICION",
        "PERIODIC",
        "COMPLAINT",
    )
    assert data["penalty_assessed_cents"] >= 0


# --- Conserved quantities of PRD Section 2.10 ------------------------------

LEDGER_BEARING_STATUSES = ("QUALIFIED", "DOWNGRADED")
COMMITTED_STATUSES = ("ENROLLED", "PROBATION")


def assert_batch_ledger_conserved(batch: dict, records: list) -> None:
    """PRD 2.10: `SettlementBatch.total_assessed_cents` must equal the sum of
    `assessed_interchange_cents` over the batch's `QUALIFIED` or `DOWNGRADED`
    records."""
    expected = sum(
        r["assessed_interchange_cents"]
        for r in records
        if r["qualification_status"] in LEDGER_BEARING_STATUSES
    )
    assert batch["total_assessed_cents"] == expected, (
        f"batch total_assessed_cents {batch['total_assessed_cents']} != "
        f"sum over surviving records {expected}"
    )


def assert_merchant_ledger_conserved(merchant: dict, records: list) -> None:
    """PRD 2.10: `Merchant.lifetime_net_assessed_cents` must equal the sum of
    `assessed_interchange_cents` over that merchant's `QUALIFIED` or
    `DOWNGRADED` records across all batches."""
    expected = sum(
        r["assessed_interchange_cents"]
        for r in records
        if r["merchant_id"] == merchant["id"]
        and r["qualification_status"] in LEDGER_BEARING_STATUSES
    )
    assert merchant["lifetime_net_assessed_cents"] == expected, (
        f"merchant lifetime_net_assessed_cents "
        f"{merchant['lifetime_net_assessed_cents']} != sum over its surviving "
        f"records {expected}"
    )


def assert_capacity_pool_conserved(program: dict, enrollments: list) -> None:
    """PRD 2.10: `total_capacity_cents` must equal `uncommitted_capacity_cents`
    plus the sum of `committed_volume_cents` over the program's `ENROLLED` or
    `PROBATION` enrollments."""
    committed = sum(
        e["committed_volume_cents"]
        for e in enrollments
        if e["incentive_program_id"] == program["id"]
        and e["status"] in COMMITTED_STATUSES
    )
    assert (
        program["total_capacity_cents"]
        == program["uncommitted_capacity_cents"] + committed
    ), (
        f"capacity drift: total {program['total_capacity_cents']} != uncommitted "
        f"{program['uncommitted_capacity_cents']} + committed {committed}"
    )


def assert_enrolled_count_matches(program: dict, enrollments: list) -> None:
    """PRD 3.8 keeps `enrolled_count` in step with the committed set."""
    expected = sum(
        1
        for e in enrollments
        if e["incentive_program_id"] == program["id"]
        and e["status"] in COMMITTED_STATUSES
    )
    assert program["enrolled_count"] == expected, (
        f"enrolled_count {program['enrolled_count']} != committed rows {expected}"
    )


def assert_version_unchanged(before: dict, after: dict) -> None:
    """A refused request must not advance a resource's version."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} on a call "
        f"that should not have written anything"
    )
