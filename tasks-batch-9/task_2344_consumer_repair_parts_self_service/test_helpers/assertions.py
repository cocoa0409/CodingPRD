"""Domain assertion helpers.

Shape checks per entity, plus checkers for the two conservation identities the PRD
declares in §2.10.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data):
    """Every stored resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int), data["version"]
    assert data["version"] >= 1, data["version"]


def assert_append_only_fields(data):
    """An append-only record carries only id and created_at, with no updated_at or version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def _assert_fields_present(data, fields):
    missing = [field for field in fields if field not in data]
    assert not missing, f"missing fields: {missing}"


# --------------------------------------------------------------------------- #
# ProductModel
# --------------------------------------------------------------------------- #
PRODUCT_MODEL_FIELDS = (
    "model_code",
    "product_family",
    "market_release_date",
    "end_of_production_date",
    "last_hardware_change_date",
    "repairability_tier",
    "support_state",
    "support_end_date",
    "documentation_posture",
    "published_disassembly_revision_number",
    "published_safety_sheet_revision_number",
    "compliance_posture",
    "open_obligation_count",
)


def assert_product_model(data):
    assert_common_fields(data)
    _assert_fields_present(data, PRODUCT_MODEL_FIELDS)
    assert data["support_state"] in (
        "ACTIVE_PRODUCTION",
        "LEGACY_SUPPORT",
        "SUPPORT_ENDED",
    ), data["support_state"]
    assert data["documentation_posture"] in ("MISSING", "STALE", "CURRENT"), data[
        "documentation_posture"
    ]
    assert data["compliance_posture"] in ("OPEN", "WATCH", "ORDER_RESTRICTED"), data[
        "compliance_posture"
    ]
    assert isinstance(data["open_obligation_count"], int)


# --------------------------------------------------------------------------- #
# RegionalComplianceProfile
# --------------------------------------------------------------------------- #
COMPLIANCE_PROFILE_FIELDS = (
    "region_code",
    "min_parts_availability_years",
    "min_documentation_years",
    "requires_public_manual",
    "max_documentation_fee_cents",
    "allows_pairing_restriction",
    "self_service_mandate_tier",
)


def assert_compliance_profile(data):
    assert_common_fields(data)
    _assert_fields_present(data, COMPLIANCE_PROFILE_FIELDS)
    assert data["self_service_mandate_tier"] in (
        "MANDATE_NONE",
        "MANDATE_BASIC",
        "MANDATE_FULL",
    ), data["self_service_mandate_tier"]


# --------------------------------------------------------------------------- #
# ComplianceObligation
# --------------------------------------------------------------------------- #
COMPLIANCE_OBLIGATION_FIELDS = (
    "model_id",
    "region_code",
    "parts_available_until",
    "documentation_available_until",
    "deadline_basis",
    "status",
    "documentation_verified",
    "last_attested_at",
    "last_attested_by_user_id",
    "breach_count",
)


def assert_compliance_obligation(data):
    assert_common_fields(data)
    _assert_fields_present(data, COMPLIANCE_OBLIGATION_FIELDS)
    assert data["deadline_basis"] in ("PRODUCTION_ACTIVE", "END_OF_PRODUCTION"), data[
        "deadline_basis"
    ]
    assert data["status"] in (
        "OPEN",
        "AT_RISK",
        "BREACHED_PARTS",
        "BREACHED_DOCUMENTATION",
        "ATTESTED",
        "CLOSED",
    ), data["status"]
    assert isinstance(data["breach_count"], int)


# --------------------------------------------------------------------------- #
# PartCatalogItem
# --------------------------------------------------------------------------- #
PART_CATALOG_ITEM_FIELDS = (
    "sku",
    "part_class",
    "safety_class",
    "list_price_cents",
    "core_return_required",
    "core_credit_cents",
    "rental_deposit_cents",
    "concurrent_rental_capacity",
    "requires_authentication",
    "requires_calibration",
    "supersedes_part_id",
    "status",
    "restriction_reason",
    "core_face_value_committed_cents",
    "core_liability_outstanding_cents",
    "core_credit_settled_cents",
    "core_credit_forfeited_cents",
)


def assert_part_catalog_item(data):
    assert_common_fields(data)
    _assert_fields_present(data, PART_CATALOG_ITEM_FIELDS)
    assert data["part_class"] in ("COMPONENT", "TOOL", "RENTAL_KIT", "CONSUMABLE"), data[
        "part_class"
    ]
    assert data["safety_class"] in (
        "UNRESTRICTED",
        "SAFETY_RESTRICTED_BATTERY",
        "SAFETY_RESTRICTED_HIGH_VOLTAGE",
        "PAIRED_SECURITY",
    ), data["safety_class"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "RESTRICTED", "SUPERSEDED"), data["status"]
    assert_core_ledger_balanced(data)


# --------------------------------------------------------------------------- #
# PartModelCompatibility
# --------------------------------------------------------------------------- #
PART_COMPATIBILITY_FIELDS = (
    "part_id",
    "model_id",
    "required_tool_part_id",
    "self_service_eligible",
    "install_minutes",
    "effective_from",
    "effective_until",
    "superseded_by_safety_restriction",
)


def assert_part_compatibility(data):
    assert_common_fields(data)
    _assert_fields_present(data, PART_COMPATIBILITY_FIELDS)
    assert isinstance(data["self_service_eligible"], bool)
    assert isinstance(data["superseded_by_safety_restriction"], bool)


# --------------------------------------------------------------------------- #
# ManualRevision
# --------------------------------------------------------------------------- #
MANUAL_REVISION_FIELDS = (
    "model_id",
    "doc_type",
    "revision_number",
    "covered_part_skus",
    "safety_warning_count",
    "status",
    "authored_by_user_id",
    "reviewed_by_user_id",
    "rejection_cycle_count",
    "effective_from",
    "published_at",
    "coverage_gap_sku_count",
)


def assert_manual_revision(data):
    assert_common_fields(data)
    _assert_fields_present(data, MANUAL_REVISION_FIELDS)
    assert data["doc_type"] in (
        "DISASSEMBLY_GUIDE",
        "SAFETY_SHEET",
        "CALIBRATION_PROCEDURE",
        "PARTS_LIST",
    ), data["doc_type"]
    assert data["status"] in (
        "DRAFT",
        "IN_REVIEW",
        "APPROVED",
        "PUBLISHED",
        "SUPERSEDED",
    ), data["status"]
    assert isinstance(data["covered_part_skus"], list)
    assert isinstance(data["revision_number"], int)


# --------------------------------------------------------------------------- #
# EligibilityAssessment
# --------------------------------------------------------------------------- #
ELIGIBILITY_ASSESSMENT_FIELDS = (
    "model_id",
    "part_id",
    "provider_id",
    "pinned_manual_revision_id",
    "region_code",
    "requester_class",
    "requester_user_id",
    "decision",
    "warranty_impact_class",
    "self_repair_risk_index",
    "liability_warning_version",
    "tool_rental_part_id",
    "status",
    "expires_at",
)


def assert_eligibility_assessment(data):
    assert_common_fields(data)
    _assert_fields_present(data, ELIGIBILITY_ASSESSMENT_FIELDS)
    assert data["decision"] in (
        "ELIGIBLE",
        "ELIGIBLE_WITH_TOOL_RENTAL",
        "BLOCKED_NO_COMPATIBILITY",
        "BLOCKED_PART_UNAVAILABLE",
        "BLOCKED_TIER",
        "BLOCKED_SAFETY",
        "BLOCKED_NO_MANUAL",
    ), data["decision"]
    assert data["warranty_impact_class"] in (
        "WARRANTY_PRESERVED",
        "WARRANTY_PRESERVED_WITH_LOG",
        "WARRANTY_LIMITED_COMPONENT_EXCLUSION",
        "WARRANTY_VOID_AFFECTED_SUBSYSTEM",
    ), data["warranty_impact_class"]
    assert data["status"] in ("VALID", "REVOKED_BY_SAFETY", "EXPIRED", "CONSUMED"), data[
        "status"
    ]
    assert 0 <= data["self_repair_risk_index"] <= 100, data["self_repair_risk_index"]


# --------------------------------------------------------------------------- #
# PartsOrder
# --------------------------------------------------------------------------- #
PARTS_ORDER_FIELDS = (
    "assessment_id",
    "model_id",
    "provider_id",
    "pinned_manual_revision_id",
    "region_code",
    "buyer_class",
    "customer_user_id",
    "rental_window_start",
    "rental_window_end",
    "fulfillment_status",
    "core_return_status",
    "pinned_manual_revision_number",
    "warranty_impact_class",
    "parts_subtotal_cents",
    "tool_purchase_cents",
    "rental_deposit_cents",
    "documentation_fee_cents",
    "core_deposit_cents",
    "total_due_cents",
    "core_credit_provisional_cents",
    "core_credit_final_cents",
    "core_return_due_at",
    "core_days_late",
    "disclosure_acknowledged_at",
    "confirmed_at",
    "delivered_at",
    "blocked_reason",
    "cancellation_reason",
)


def assert_parts_order(data):
    assert_common_fields(data)
    _assert_fields_present(data, PARTS_ORDER_FIELDS)
    assert data["fulfillment_status"] in (
        "DRAFT",
        "PENDING_DISCLOSURE",
        "CONFIRMED",
        "DELIVERED",
        "CLOSED",
        "BLOCKED_SAFETY_HOLD",
        "CANCELLED",
    ), data["fulfillment_status"]
    assert data["core_return_status"] in (
        "NOT_REQUIRED",
        "PENDING_CORE",
        "CORE_RECEIVED",
        "CORE_CREDIT_ISSUED",
        "CORE_FORFEITED",
        "CORE_RELEASED",
    ), data["core_return_status"]
    assert_order_total_is_sum_of_buckets(data)


def assert_order_total_is_sum_of_buckets(order):
    """total_due_cents is the sum of the five order-level money buckets."""
    expected = (
        order["parts_subtotal_cents"]
        + order["tool_purchase_cents"]
        + order["rental_deposit_cents"]
        + order["documentation_fee_cents"]
        + order["core_deposit_cents"]
    )
    assert order["total_due_cents"] == expected, (
        f"total_due_cents {order['total_due_cents']} does not equal the sum of the "
        f"five buckets {expected}"
    )


# --------------------------------------------------------------------------- #
# PartsOrderLine
# --------------------------------------------------------------------------- #
PARTS_ORDER_LINE_FIELDS = (
    "order_id",
    "part_id",
    "quantity",
    "buyer_multiplier",
    "volume_multiplier",
    "tier_surcharge_multiplier",
    "unit_price_cents",
    "line_total_cents",
    "authentication_status",
    "calibration_status",
    "calibration_attempt_count",
    "last_measured_offset_ppm",
    "pairing_token",
)


def assert_parts_order_line(data):
    assert_common_fields(data)
    _assert_fields_present(data, PARTS_ORDER_LINE_FIELDS)
    assert data["authentication_status"] in (
        "NOT_REQUIRED",
        "PENDING_AUTHENTICATION",
        "AUTHENTIC",
        "COUNTERFEIT_SUSPECT",
    ), data["authentication_status"]
    assert data["calibration_status"] in (
        "NOT_REQUIRED",
        "CALIBRATION_REQUIRED",
        "CALIBRATION_IN_PROGRESS",
        "CALIBRATION_PASSED",
        "CALIBRATION_FAILED",
        "CALIBRATION_ESCALATED",
    ), data["calibration_status"]
    assert isinstance(data["calibration_attempt_count"], int)


# --------------------------------------------------------------------------- #
# DisclosureAcknowledgment
# --------------------------------------------------------------------------- #
DISCLOSURE_ACKNOWLEDGMENT_FIELDS = (
    "order_id",
    "warranty_impact_class_ack",
    "liability_warning_version",
    "acknowledged_scope",
    "acknowledged_by_user_id",
    "manual_revision_number",
    "acknowledged_at",
)


def assert_disclosure_acknowledgment(data):
    assert_append_only_fields(data)
    _assert_fields_present(data, DISCLOSURE_ACKNOWLEDGMENT_FIELDS)
    assert data["acknowledged_scope"] in (
        "FULL_SELF_REPAIR",
        "TOOL_RENTAL_ONLY",
        "PROVIDER_MANAGED",
    ), data["acknowledged_scope"]


# --------------------------------------------------------------------------- #
# RepairProvider
# --------------------------------------------------------------------------- #
REPAIR_PROVIDER_FIELDS = (
    "legal_name",
    "region_code",
    "requested_access_tier",
    "technician_count",
    "authorization_status",
    "parts_access_tier",
    "training_credit_granted_total",
    "training_credit_balance",
    "training_credit_forfeited_total",
    "required_cert_count",
    "active_cert_count",
    "attested_compliance_score",
    "suspension_reason",
)


def assert_repair_provider(data):
    assert_common_fields(data)
    _assert_fields_present(data, REPAIR_PROVIDER_FIELDS)
    assert data["authorization_status"] in (
        "APPLIED",
        "TRAINING_IN_PROGRESS",
        "AUTHORIZED",
        "SUSPENDED",
        "REVOKED",
    ), data["authorization_status"]
    assert data["parts_access_tier"] in (
        None,
        "TIER_1_UNRESTRICTED",
        "TIER_2_SAFETY",
        "TIER_3_STANDARD",
    ), data["parts_access_tier"]


# --------------------------------------------------------------------------- #
# TrainingCertification
# --------------------------------------------------------------------------- #
TRAINING_CERTIFICATION_FIELDS = (
    "provider_id",
    "technician_user_id",
    "course_code",
    "valid_from",
    "valid_until",
    "exam_score",
    "status",
    "credits_consumed",
    "void_reason",
)


def assert_training_certification(data):
    assert_common_fields(data)
    _assert_fields_present(data, TRAINING_CERTIFICATION_FIELDS)
    assert data["status"] in ("ACTIVE", "EXPIRED", "VOIDED"), data["status"]
    assert data["course_code"] in (
        "CRS_BATTERY_SAFETY",
        "CRS_HIGH_VOLTAGE",
        "CRS_PAIRING_CALIBRATION",
        "CRS_GENERAL_REPAIR",
    ), data["course_code"]


# --------------------------------------------------------------------------- #
# DefectiveReturnCase
# --------------------------------------------------------------------------- #
DEFECTIVE_RETURN_FIELDS = (
    "order_line_id",
    "part_id",
    "quantity",
    "reported_failure_code",
    "status",
    "root_cause_code",
    "defect_confirmed",
    "analyzed_by_user_id",
    "decided_by_user_id",
    "provisional_credit_cents",
    "final_credit_cents",
    "received_at",
)


def assert_defective_return(data):
    assert_common_fields(data)
    _assert_fields_present(data, DEFECTIVE_RETURN_FIELDS)
    assert data["status"] in (
        "REQUESTED",
        "RECEIVED",
        "ANALYSIS_COMPLETE",
        "CREDIT_ISSUED",
        "REJECTED",
    ), data["status"]


# --------------------------------------------------------------------------- #
# Computed reads
# --------------------------------------------------------------------------- #
COMPLIANCE_SCORE_FIELDS = (
    "variant",
    "cert_coverage_ratio",
    "breach_count",
    "calibration_failure_ratio",
    "score",
    "access_tier_band",
)


def assert_compliance_score_shape(data):
    _assert_fields_present(data, COMPLIANCE_SCORE_FIELDS)
    assert data["variant"] in ("ROLLING_ATTESTED", "LIVE_RECOMPUTE"), data["variant"]
    assert isinstance(data["score"], int)
    assert 0 <= data["score"] <= 100, data["score"]
    assert data["access_tier_band"] in (
        "TIER_1_UNRESTRICTED",
        "TIER_2_SAFETY",
        "TIER_3_STANDARD",
    ), data["access_tier_band"]


DEMAND_FORECAST_FIELDS = (
    "variant",
    "trailing_units",
    "pipeline_units",
    "base_monthly_units",
    "obsolescence_band",
    "band_multiplier",
    "projected_units",
    "safety_stock_pct",
    "mandated_buffer_units",
    "recommended_stock_units",
)


def assert_demand_forecast_shape(data):
    _assert_fields_present(data, DEMAND_FORECAST_FIELDS)
    assert data["obsolescence_band"] in ("CURRENT", "LEGACY", "LONG_TAIL"), data[
        "obsolescence_band"
    ]
    assert isinstance(data["mandated_buffer_units"], int)
    assert isinstance(data["recommended_stock_units"], int)


COMPLIANCE_SWEEP_FIELDS = (
    "swept_obligation_count",
    "breached_obligation_ids",
    "expired_assessment_ids",
    "restricted_model_ids",
)


def assert_compliance_sweep_shape(data):
    _assert_fields_present(data, COMPLIANCE_SWEEP_FIELDS)
    assert isinstance(data["swept_obligation_count"], int)
    assert isinstance(data["breached_obligation_ids"], list)
    assert isinstance(data["expired_assessment_ids"], list)
    assert isinstance(data["restricted_model_ids"], list)


# --------------------------------------------------------------------------- #
# The two conservation identities (PRD §2.10)
# --------------------------------------------------------------------------- #
def assert_core_ledger_balanced(part):
    """outstanding + settled + forfeited must equal committed on a catalog part."""
    total = (
        part["core_liability_outstanding_cents"]
        + part["core_credit_settled_cents"]
        + part["core_credit_forfeited_cents"]
    )
    assert total == part["core_face_value_committed_cents"], (
        "core ledger identity broken: outstanding "
        f"{part['core_liability_outstanding_cents']} + settled "
        f"{part['core_credit_settled_cents']} + forfeited "
        f"{part['core_credit_forfeited_cents']} != committed "
        f"{part['core_face_value_committed_cents']}"
    )
    assert part["core_liability_outstanding_cents"] >= 0, "outstanding total went negative"


def assert_core_ledger_aggregates(part, committed, outstanding, settled, forfeited):
    """The four core-ledger aggregates hold exactly the expected integer cent values."""
    assert part["core_face_value_committed_cents"] == committed
    assert part["core_liability_outstanding_cents"] == outstanding
    assert part["core_credit_settled_cents"] == settled
    assert part["core_credit_forfeited_cents"] == forfeited
    assert_core_ledger_balanced(part)


def assert_training_credit_balanced(provider, certifications):
    """balance + consumed by ACTIVE/EXPIRED certifications + forfeited == granted."""
    consumed = sum(
        cert["credits_consumed"]
        for cert in certifications
        if cert["status"] in ("ACTIVE", "EXPIRED")
    )
    total = (
        provider["training_credit_balance"] + consumed + provider["training_credit_forfeited_total"]
    )
    assert total == provider["training_credit_granted_total"], (
        "training credit identity broken: balance "
        f"{provider['training_credit_balance']} + consumed {consumed} + forfeited "
        f"{provider['training_credit_forfeited_total']} != granted "
        f"{provider['training_credit_granted_total']}"
    )
    assert provider["training_credit_balance"] >= 0, "credit balance went negative"
