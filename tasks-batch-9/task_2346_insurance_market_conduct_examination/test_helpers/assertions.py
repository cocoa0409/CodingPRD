"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PERCENT_FIELDS = (
    "complaint_ratio_per_1k",
    "complaint_component",
    "financial_component",
    "trend_component",
    "volume_multiplier",
    "composite_score",
    "error_tolerance_pct",
    "error_rate_pct",
    "material_error_rate_pct",
    "completeness_pct",
    "effective_completeness_pct",
    "cooperation_credit_pct",
)


def assert_two_decimal_places(value, field_name="value"):
    """Percentages and scores are carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"{field_name} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{field_name} must carry at most two decimal places, got {value!r}"
    )


def assert_whole_cents(value, field_name="value"):
    """Money is carried in whole cents as integers, never as fractional currency."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


def assert_versioned_record(data: dict, label="record"):
    """A record type that carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC instant"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_append_only_record(data: dict, label="record"):
    """An append-only workpaper: only id and created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant"
    )
    assert "updated_at" not in data, (
        f"{label} is append-only: the updated_at key must be absent entirely"
    )
    assert "version" not in data, (
        f"{label} is append-only: the version key must be absent entirely"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────


def assert_insurer(data: dict):
    assert_versioned_record(data, "Insurer")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["naic_code"], str) and data["naic_code"].isdigit()
    assert len(data["naic_code"]) == 5, "naic_code is exactly five digits"
    assert data["license_status"] in ("LICENSED", "SUSPENDED", "WITHDRAWN")
    assert_whole_cents(data["annual_premium_written_cents"], "annual_premium_written_cents")
    assert isinstance(data["policy_count_in_force"], int)
    assert isinstance(data["confirmed_complaints_12mo"], int)
    assert 0 <= data["financial_stress_score"] <= 100
    assert 0 <= data["consumer_trend_score"] <= 100
    assert_two_decimal_places(data["complaint_ratio_per_1k"], "complaint_ratio_per_1k")
    assert data["risk_tier"] in ("UNRATED", "LOW", "MODERATE", "ELEVATED", "HIGH")
    assert isinstance(data["open_exam_count"], int)
    assert isinstance(data["pending_enforcement_exam_count"], int)
    assert_whole_cents(
        data["lifetime_restitution_ordered_cents"], "lifetime_restitution_ordered_cents"
    )


def assert_analysis_cycle(data: dict):
    assert_versioned_record(data, "MarketAnalysisCycle")
    assert isinstance(data["cycle_label"], str) and 1 <= len(data["cycle_label"]) <= 40
    assert data["status"] in ("DRAFT", "SCORED", "TARGETS_SELECTED", "CLOSED")
    assert data["default_exam_mode"] in ("ON_SITE", "DESK")
    assert data["target_slot_capacity"] >= 1
    assert data["slots_committed"] >= 0
    assert (
        data["slots_available"] == data["target_slot_capacity"] - data["slots_committed"]
    ), "slots_available is target_slot_capacity less slots_committed"


def assert_analysis_score(data: dict):
    assert_versioned_record(data, "AnalysisScore")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["insurer_id"])
    for field in (
        "complaint_ratio_at_scoring",
        "complaint_component",
        "financial_component",
        "trend_component",
        "volume_multiplier",
        "composite_score",
    ):
        assert_two_decimal_places(data[field], field)
    assert data["composite_score"] <= 100.00, "composite_score is held to a ceiling of 100.00"
    assert data["rank_position"] >= 1
    assert isinstance(data["selected"], bool)
    assert data["selection_reason"] in (
        None,
        "SELECTED",
        "BELOW_THRESHOLD",
        "CAPACITY_EXHAUSTED",
        "WINDOW_CONFLICT_DEFERRED",
        "LICENSE_INELIGIBLE",
    )


def assert_examination(data: dict):
    assert_versioned_record(data, "Examination")
    assert is_valid_uuid(data["insurer_id"])
    assert data["exam_type"] in ("MARKET_CONDUCT_EXAM", "TARGETED_EXAM")
    assert data["mode"] in ("ON_SITE", "DESK")
    assert isinstance(data["lead_state_code"], str) and len(data["lead_state_code"]) == 2
    assert data["lead_state_code"].isupper()
    assert data["status"] in (
        "SCOPING",
        "DATA_CALL",
        "FIELDWORK",
        "CRITICISM",
        "NEGOTIATION",
        "ORDER_PENDING",
        "PUBLISHED",
        "ABORTED",
    )
    assert isinstance(data["scope_locked"], bool)
    for field in (
        "scope_area_count",
        "rejected_data_call_count",
        "open_criticism_count",
        "sustained_criticism_count",
        "penalty_units_total",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_whole_cents(data["pending_restitution_cents"], "pending_restitution_cents")
    assert_whole_cents(data["aggregate_restitution_cents"], "aggregate_restitution_cents")
    assert isinstance(data["followup_required"], bool)


def assert_scope_area(data: dict):
    assert_versioned_record(data, "ExamScopeArea")
    assert is_valid_uuid(data["exam_id"])
    assert data["area"] in ("UNDERWRITING", "RATING", "CLAIMS", "PRODUCER")
    assert data["population_size"] >= 1
    assert data["sample_size"] >= 1
    assert data["sample_size"] <= data["population_size"]
    assert_two_decimal_places(data["error_tolerance_pct"], "error_tolerance_pct")
    assert 0.00 <= data["error_tolerance_pct"] <= 100.00
    assert data["status"] in ("PLANNED", "FIELDWORK", "TESTED", "CLOSED")
    assert_two_decimal_places(data["error_rate_pct"], "error_rate_pct")
    assert_two_decimal_places(data["material_error_rate_pct"], "material_error_rate_pct")
    assert isinstance(data["tolerance_breached"], bool)
    assert isinstance(data["escalation_required"], bool)
    assert data["material_error_count"] <= data["error_count"]
    assert data["error_count"] <= data["reviewed_sample_count"]


def assert_data_call(data: dict):
    assert_versioned_record(data, "DataCall")
    assert is_valid_uuid(data["scope_area_id"])
    assert data["records_requested"] >= 1
    assert data["sampling_method"] == "SYSTEMATIC_INTERVAL"
    assert data["status"] in (
        "ISSUED",
        "OVERDUE",
        "RESPONDED",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
    )
    assert isinstance(data["is_late"], bool)
    assert data["days_late"] >= 0
    assert_two_decimal_places(data["completeness_pct"], "completeness_pct")
    assert_two_decimal_places(
        data["effective_completeness_pct"], "effective_completeness_pct"
    )
    assert data["effective_completeness_pct"] >= 0.00, (
        "effective_completeness_pct is floored at 0.00"
    )
    assert data["records_received"] <= data["records_requested"]


def assert_file_sample(data: dict):
    assert_versioned_record(data, "FileSample")
    assert is_valid_uuid(data["data_call_id"])
    assert data["population_index"] >= 1
    assert data["review_status"] in ("UNREVIEWED", "COMPLIANT", "ERROR")
    assert data["error_severity"] in ("NONE", "MINOR", "MATERIAL")
    assert_whole_cents(data["underpaid_amount_cents"], "underpaid_amount_cents")
    assert data["underpaid_amount_cents"] >= 0
    prefix, _, digits = data["file_reference"].partition("-")
    assert prefix in ("UW", "RT", "CLM", "PRD"), (
        f"file_reference prefix must be a statutory area prefix, got {prefix!r}"
    )
    assert len(digits) == 6 and digits.isdigit(), (
        "file_reference carries the population index zero-padded to six digits"
    )
    assert int(digits) == data["population_index"]


def assert_criticism(data: dict):
    assert_versioned_record(data, "Criticism")
    assert is_valid_uuid(data["exam_id"])
    assert is_valid_uuid(data["scope_area_id"])
    assert isinstance(data["statute_citation"], str) and data["statute_citation"]
    assert data["severity"] in ("MINOR", "MATERIAL", "EGREGIOUS")
    assert data["affected_file_count"] >= 1
    assert data["status"] in ("ISSUED", "RESPONDED", "SUSTAINED", "WITHDRAWN")
    assert 0 <= data["response_round"] <= 3
    assert 0 <= data["rebuttal_count"] <= 2
    assert data["restitution_method"] in ("SAMPLE_ACTUAL", "POPULATION_EXTRAPOLATED")
    assert_whole_cents(data["restitution_exposure_cents"], "restitution_exposure_cents")
    assert is_valid_uuid(data["issued_by_user_id"])


def assert_company_response(data: dict):
    assert_append_only_record(data, "CompanyResponse")
    assert is_valid_uuid(data["criticism_id"])
    assert data["round_number"] >= 1
    assert data["position"] in ("CONCUR", "PARTIAL_CONCUR", "DISPUTE")
    assert isinstance(data["narrative"], str) and len(data["narrative"]) >= 20
    assert_whole_cents(data["remediation_offer_cents"], "remediation_offer_cents")
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_fieldwork_activity(data: dict):
    assert_append_only_record(data, "FieldworkActivity")
    assert is_valid_uuid(data["exam_id"])
    assert data["activity_type"] in ("INTERVIEW", "SYSTEM_WALKTHROUGH")
    assert data["area"] in ("UNDERWRITING", "RATING", "CLAIMS", "PRODUCER")
    assert isinstance(data["participant_name"], str) and data["participant_name"]
    assert isinstance(data["participant_title"], str) and data["participant_title"]
    assert isinstance(data["summary"], str)
    assert isinstance(data["documented"], bool)
    assert is_iso8601_timestamp(data["conducted_at"])


def assert_corrective_action_plan(data: dict):
    assert_versioned_record(data, "CorrectiveActionPlan")
    assert is_valid_uuid(data["exam_id"])
    assert data["status"] in (
        "PROPOSED",
        "REVISION_REQUESTED",
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
    )
    assert data["revision_round"] >= 1
    assert data["milestone_count"] >= 1
    assert isinstance(data["narrative"], str) and len(data["narrative"]) >= 20


def assert_consent_order(data: dict):
    assert_versioned_record(data, "ConsentOrder")
    assert is_valid_uuid(data["exam_id"])
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert data["status"] in ("DRAFT", "EXECUTED", "VOIDED")
    assert data["penalty_variant"] in ("PER_VIOLATION", "TIERED_AGGREGATE")
    for field in (
        "restitution_cents",
        "penalty_gross_cents",
        "penalty_net_cents",
        "order_total_cents",
    ):
        assert_whole_cents(data[field], field)
    assert_two_decimal_places(data["cooperation_credit_pct"], "cooperation_credit_pct")
    assert is_valid_uuid(data["drafted_by_user_id"])
    assert data["order_total_cents"] == data["restitution_cents"] + data["penalty_net_cents"], (
        "order_total_cents is the restitution aggregate plus the net penalty"
    )


def assert_collaboration(data: dict):
    assert_versioned_record(data, "MultistateCollaboration")
    assert is_valid_uuid(data["exam_id"])
    assert data["status"] in ("LEAD_ASSIGNED", "ACTIVE", "SETTLED", "DISSOLVED")
    states = data["participating_states"]
    assert isinstance(states, list) and 1 <= len(states) <= 12
    assert data["participant_count"] == len(states)
    codes = [s["state_code"] for s in states]
    assert len(set(codes)) == len(codes), "state_code is unique within the roster"
    for state in states:
        assert len(state["state_code"]) == 2 and state["state_code"].isupper()
        assert state["policy_count_in_state"] >= 1
        assert isinstance(state["has_examiner_resources"], bool)
        assert_whole_cents(state["allocated_cents"], "allocated_cents")
    assert data["lead_state_code"] in codes
    assert_whole_cents(data["allocated_total_cents"], "allocated_total_cents")


# ─── Domain invariants ────────────────────────────────────────────────────


def assert_slot_ledger_conserved(cycle: dict):
    """The examiner slot ledger on a cycle balances exactly."""
    assert (
        cycle["slots_available"] == cycle["target_slot_capacity"] - cycle["slots_committed"]
    ), (
        "slots_available must equal target_slot_capacity less slots_committed, got "
        f"{cycle['slots_available']} against {cycle['target_slot_capacity']} - "
        f"{cycle['slots_committed']}"
    )
    assert cycle["slots_committed"] >= 0
    assert cycle["slots_available"] >= 0


def assert_allocation_conserved(collaboration: dict, aggregate_restitution_cents: int):
    """The multistate restitution ledger balances to the cent with no drift."""
    per_state = sum(s["allocated_cents"] for s in collaboration["participating_states"])
    assert per_state == collaboration["allocated_total_cents"], (
        "allocated_total_cents must equal the sum of every participant's "
        f"allocated_cents, got {collaboration['allocated_total_cents']} against {per_state}"
    )
    assert collaboration["allocated_total_cents"] == aggregate_restitution_cents, (
        "allocated_total_cents must equal the examination's sustained restitution "
        f"aggregate, got {collaboration['allocated_total_cents']} against "
        f"{aggregate_restitution_cents}"
    )


def assert_restitution_ledgers_balance(examination: dict, total_exposure_cents: int):
    """Pending plus accrued restitution is conserved across a finalization."""
    actual = (
        examination["pending_restitution_cents"]
        + examination["aggregate_restitution_cents"]
    )
    assert actual == total_exposure_cents, (
        "pending_restitution_cents plus aggregate_restitution_cents must equal the "
        f"issued exposure, got {actual} against {total_exposure_cents}"
    )


def assert_error_envelope_meta(body: dict):
    """The meta object for error responses contains only the two request keys."""
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, got "
        f"{sorted(body['meta'].keys())}"
    )
