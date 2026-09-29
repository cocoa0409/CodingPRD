"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID: {data.get('id')!r}"
    assert not str(data.get("id", "")).startswith(
        ("firm_", "rec_", "he_", "con_")
    ), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_firm(data: dict) -> None:
    _assert_common_fields(data, "Firm")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["registration_number"], str) and data["registration_number"]
    assert isinstance(data["policy_deductible_cents"], int)
    assert data["policy_deductible_cents"] >= 0
    assert isinstance(data["policy_aggregate_cents"], int)
    assert data["policy_aggregate_cents"] > 0
    assert isinstance(data["policy_paid_to_date_cents"], int)
    assert data["policy_paid_to_date_cents"] >= 0
    assert isinstance(data["open_recall_count"], int)
    assert data["open_recall_count"] >= 0


def assert_recall(data: dict) -> None:
    _assert_common_fields(data, "Recall")
    assert data["status"] in (
        "DRAFT", "CLASSIFIED", "NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
        "EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED", "TERMINATED",
    ), f"Unexpected Recall.status {data['status']!r}"
    assert data["agency"] in ("FDA", "USDA")
    assert data["initiation_type"] in ("FIRM_INITIATED", "AGENCY_REQUESTED", "MANDATED")
    assert isinstance(data["lot_codes"], list) and len(data["lot_codes"]) >= 1
    assert data["hazard_class"] in (None, "CLASS_I", "CLASS_II", "CLASS_III")
    assert data["compliance_flag"] in ("COMPLIANT", "WATCH", "ESCALATED", "DELINQUENT")
    assert_recall_invariants(data)


def assert_recall_invariants(data: dict) -> None:
    """Invariants that must hold on the recall hub after any operation."""
    for field in (
        "eligible_consignee_count", "required_sample_size", "responded_count",
        "overdue_report_count", "total_shipped_units", "accounted_units",
        "units_awaiting_disposition", "units_pending_verification",
        "units_disposed_verified", "total_loaded_cost_cents",
        "insurable_loaded_cost_cents", "termination_denied_count",
    ):
        assert isinstance(data[field], int), f"Recall.{field} must be an integer"
        assert data[field] >= 0, f"Recall.{field} must not be negative"
    for pct in (
        "contact_effectiveness_pct", "quantity_effectiveness_pct",
        "official_effectiveness_pct",
    ):
        value = data[pct]
        assert 0.0 <= value <= 100.0, f"Recall.{pct} out of range: {value}"
        assert round(value, 2) == value, f"Recall.{pct} carries more than 2 decimals"
    assert data["insurable_loaded_cost_cents"] <= data["total_loaded_cost_cents"]


def assert_hazard_evaluation(data: dict) -> None:
    _assert_common_fields(data, "HazardEvaluation")
    assert data["status"] in ("DRAFT", "SUBMITTED", "RATIFIED", "RETURNED", "SUPERSEDED")
    assert data["variant"] in ("PRELIMINARY", "RATIFIED")
    assert data["probability_of_adverse_health"] in ("HIGH", "MEDIUM", "LOW", "REMOTE")
    assert 1 <= data["severity_tier"] <= 4
    assert data["exposure_population"] >= 0
    assert data["evidence_strength"] in ("CONFIRMED", "PROBABLE", "SUSPECTED")
    assert data["recommended_class"] in (None, "CLASS_I", "CLASS_II", "CLASS_III")
    assert round(data["hazard_score"], 2) == data["hazard_score"]


def assert_consignee(data: dict) -> None:
    _assert_common_fields(data, "Consignee")
    assert data["consignee_type"] in ("DISTRIBUTOR", "RETAILER", "RESTAURANT", "INSTITUTION")
    assert 1 <= data["tier"] <= 3, f"Consignee.tier capped at 3, got {data['tier']}"
    assert data["response_state"] in ("AWAITING", "ACKNOWLEDGED", "REFUSED", "NO_RESPONSE")
    assert isinstance(data["escalation_level"], int) and data["escalation_level"] >= 0
    assert isinstance(data["in_effectiveness_sample"], bool)
    assert isinstance(data["closed_without_response"], bool)


def assert_distribution_record(data: dict) -> None:
    _assert_common_fields(data, "DistributionRecord")
    assert data["status"] in ("DECLARED", "CONFIRMED", "DISPUTED", "CORRECTED", "VOIDED")
    assert data["quantity_shipped"] > 0
    assert data["effective_quantity"] >= 0
    assert isinstance(data["reconcile_round"], int) and data["reconcile_round"] >= 0


def assert_notification(data: dict) -> None:
    _assert_common_fields(data, "ConsigneeNotification")
    assert data["delivery_state"] in ("SENT", "DELIVERED", "UNDELIVERABLE")
    assert data["response_state"] in ("AWAITING", "ACKNOWLEDGED", "REFUSED", "NO_RESPONSE")
    assert data["method"] in ("EMAIL", "PHONE", "CERTIFIED_MAIL")
    assert data["attempt_no"] >= 1
    assert is_iso8601_timestamp(data["sent_at"])
    expected = (
        data["delivery_state"] == "DELIVERED"
        and data["response_state"] in ("ACKNOWLEDGED", "REFUSED")
    )
    assert data["counts_toward_effectiveness"] is expected, (
        "counts_toward_effectiveness is true only when delivery_state is DELIVERED "
        "and response_state is ACKNOWLEDGED or REFUSED"
    )


def assert_retrieval_receipt(data: dict) -> None:
    _assert_common_fields(data, "RetrievalReceipt")
    assert data["status"] in ("REPORTED", "VERIFIED", "DISPUTED")
    for field in (
        "quantity_returned", "quantity_destroyed_onsite",
        "quantity_held_segregated", "quantity_unrecoverable",
    ):
        assert data[field] >= 0, f"RetrievalReceipt.{field} must not be negative"
    assert data["accounted_units"] == (
        data["quantity_returned"]
        + data["quantity_destroyed_onsite"]
        + data["quantity_held_segregated"]
    ), "accounted_units is the sum of returned + destroyed onsite + held segregated"


def assert_public_warning(data: dict) -> None:
    _assert_common_fields(data, "PublicWarning")
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED")
    assert data["warning_type"] in ("PRESS_RELEASE", "PUBLIC_WARNING", "SOCIAL_MEDIA_ONLY")
    assert isinstance(data["reject_count"], int) and data["reject_count"] >= 0


def assert_disposition_order(data: dict) -> None:
    _assert_common_fields(data, "DispositionOrder")
    assert data["status"] in ("PROPOSED", "AUTHORIZED", "EXECUTED", "VERIFIED")
    assert data["method"] in ("DESTROY", "REWORK", "RELABEL", "RETURN_TO_FIRM")
    assert data["quantity"] > 0
    assert isinstance(data["reject_count"], int) and data["reject_count"] >= 0


def assert_status_report(data: dict) -> None:
    _assert_common_fields(data, "StatusReport")
    assert data["status"] in ("PENDING", "SUBMITTED", "ACCEPTED", "OVERDUE")
    assert data["report_kind"] in ("PERIODIC", "INTERIM", "FINAL_EFFECTIVENESS")
    assert data["period_index"] >= 1
    assert data["due_at"] == data["period_end"], (
        "due_at is always equal to period_end for every report kind"
    )
    assert data["period_start"] < data["period_end"], (
        "period_start must be strictly earlier than period_end"
    )


def assert_cost_entry(data: dict) -> None:
    _assert_common_fields(data, "CostEntry")
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED")
    assert data["category"] in (
        "NOTIFICATION", "LOGISTICS", "DESTRUCTION", "LEGAL",
        "PRODUCT_VALUE", "LAB_TESTING",
    )
    assert data["amount_cents"] > 0
    assert isinstance(data["insurable"], bool)
    assert isinstance(data["line_loaded_cost_cents"], int), (
        "money is an integer number of cents"
    )
    assert data["line_loaded_cost_cents"] >= data["amount_cents"]


def assert_insurance_claim(data: dict) -> None:
    _assert_common_fields(data, "InsuranceClaim")
    assert data["status"] in ("DRAFT", "SUBMITTED", "PARTIALLY_PAID", "PAID", "DENIED")
    for field in (
        "claimed_cents", "capped_total_cents", "settlement_payable_cents",
        "handling_fee_cents", "total_claim_value_cents", "paid_cents",
    ):
        assert isinstance(data[field], int), f"InsuranceClaim.{field} must be integer cents"
        assert data[field] >= 0
    assert data["total_claim_value_cents"] == (
        data["settlement_payable_cents"] + data["handling_fee_cents"]
    )


def assert_effectiveness_payload(data: dict) -> None:
    """The computed effectiveness read exposes both bases side by side."""
    for field in (
        "recall_id", "agency", "effectiveness_check_level", "sample_tier_scope",
        "eligible_consignee_count", "required_sample_size", "responded_count",
        "contact_effectiveness_pct", "shipped_units", "accounted_units",
        "quantity_effectiveness_pct", "official_basis", "official_effectiveness_pct",
    ):
        assert field in data, f"effectiveness payload is missing {field}"
    assert data["official_basis"] in ("CONTACT", "QUANTITY")
    if data["official_basis"] == "CONTACT":
        assert data["official_effectiveness_pct"] == data["contact_effectiveness_pct"]
    else:
        assert data["official_effectiveness_pct"] == data["quantity_effectiveness_pct"]
