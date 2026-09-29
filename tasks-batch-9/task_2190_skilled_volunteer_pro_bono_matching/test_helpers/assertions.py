"""Entity assertions and domain invariant checkers for the Pro Bono Matching API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    PartnerOrgStatus, CapacityClass, CyclePosture, ProjectRequestStatus,
    ScopeDefinitionStatus, VolunteerStatus, MatchOfferStatus, WorkStatus,
    ValuationStatus, QualityGate, CreepEscalationLevel, AgreementStatus,
    CheckinStatus, ScopeChangeStatus, DecisionTier, QualityReviewStatus,
    ReviewOutcome, ValuationMethod, AvailabilityWindowStatus,
    DeliverableReviewStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_identity_and_stamps(data: dict, versioned: bool = True):
    """Every persisted row carries a server-minted UUID `id` and a `created_at`
    ISO 8601 UTC timestamp; versioned rows additionally carry `updated_at` and
    an integer `version` starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )


def assert_light_row(data: dict):
    """Lighter resource kinds carry only `id` and `created_at` — no `updated_at`
    field and no `version` field at all."""
    assert_identity_and_stamps(data, versioned=False)
    assert "updated_at" not in data, "light rows must not carry updated_at"
    assert "version" not in data, "light rows must not carry version"


# ---------------------------------------------------------------- entities
def assert_partner_org(data: dict):
    assert_identity_and_stamps(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["capacity_class"] in _values(CapacityClass)
    assert data["max_concurrent_engagements"] in (1, 2, 4, 6)
    assert isinstance(data["open_engagement_count"], int)
    assert data["open_engagement_count"] >= 0
    assert data["status"] in _values(PartnerOrgStatus)
    assert isinstance(data["satisfaction_sample_size"], int)
    assert 0 <= data["satisfaction_sample_size"] <= 5


def assert_program_cycle(data: dict):
    assert_identity_and_stamps(data)
    assert isinstance(data["capacity_slot_total"], int) and data["capacity_slot_total"] >= 1
    assert data["posture"] in _values(CyclePosture)
    assert_cycle_slot_conservation(data)


def assert_cycle_slot_conservation(cycle: dict):
    """slots_committed plus slots_reserved plus slots_available always equals
    capacity_slot_total, and slots_available never reads negative."""
    total = cycle["capacity_slot_total"]
    committed = cycle["slots_committed"]
    reserved = cycle["slots_reserved"]
    available = cycle["slots_available"]
    assert committed >= 0 and reserved >= 0 and available >= 0, (
        f"slot counters must be non-negative, got {cycle}"
    )
    assert committed + reserved + available == total, (
        f"slots_committed({committed}) + slots_reserved({reserved}) + "
        f"slots_available({available}) must equal capacity_slot_total({total})"
    )


def assert_project_request(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(ProjectRequestStatus)
    assert isinstance(data["active_scope_revision_no"], int)
    assert data["active_scope_revision_no"] >= 0
    assert 0 <= data["rescope_count"] <= 3
    assert data["failed_match_rounds"] >= 0


def assert_scope_definition(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(ScopeDefinitionStatus)
    assert data["revision_no"] >= 1
    assert data["deliverable_count"] >= 0


def assert_deliverable(data: dict):
    assert_light_row(data)
    assert data["review_status"] in _values(DeliverableReviewStatus)
    assert 0.01 <= data["weight_pct"] <= 100.00
    assert data["sequence_no"] >= 1


def assert_volunteer(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(VolunteerStatus)
    assert 0.0 <= data["reliability_score"] <= 1.0
    assert 0.0 <= data["reliability_score_lifetime"] <= 1.0
    assert data["terminal_engagement_count"] >= 0
    assert data["open_engagement_count"] >= 0
    assert data["lifetime_valued_usd"] >= 0


def assert_skill_profile(data: dict):
    assert_light_row(data)
    assert 1 <= data["proficiency"] <= 5
    assert isinstance(data["verified"], bool)


def assert_availability_window(data: dict):
    assert_light_row(data)
    assert data["status"] in _values(AvailabilityWindowStatus)
    assert_window_hour_conservation(data)


def assert_window_hour_conservation(window: dict):
    """hours_remaining equals hours_offered less hours_committed, to two
    decimals, and neither figure reads negative."""
    offered = window["hours_offered"]
    committed = window["hours_committed"]
    remaining = window["hours_remaining"]
    assert committed >= 0, f"hours_committed must be >= 0, got {committed}"
    assert abs((offered - committed) - remaining) < 0.005, (
        f"hours_remaining({remaining}) must equal hours_offered({offered}) - "
        f"hours_committed({committed})"
    )


def assert_match_offer(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(MatchOfferStatus)
    assert data["round_no"] >= 1
    assert 0.0 <= data["match_score"] <= 1.2
    assert data["reserved_hours"] > 0


def assert_engagement(data: dict):
    assert_identity_and_stamps(data)
    assert data["work_status"] in _values(WorkStatus)
    assert data["valuation_status"] in _values(ValuationStatus)
    assert data["quality_gate"] in _values(QualityGate)
    assert data["creep_escalation_level"] in _values(CreepEscalationLevel)
    assert data["committed_hours"] > 0
    assert data["approved_hours"] >= 0
    assert data["missed_checkin_count"] >= 0


def assert_agreement(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(AgreementStatus)
    assert 0 <= data["counter_round"] <= 3
    assert data["terms_revision_no"] == data["counter_round"] + 1, (
        "terms_revision_no must equal counter_round + 1"
    )


def assert_milestone(data: dict):
    assert_identity_and_stamps(data)
    assert data["checkin_status"] in _values(CheckinStatus)
    assert data["sequence_no"] >= 1
    assert isinstance(data["escalation_raised"], bool)


def assert_time_log(data: dict):
    assert_light_row(data)
    assert 0 < data["hours"] <= 12.00
    assert data["activity_class"] in ("DELIVERY", "ADMIN", "TRAVEL")
    assert data["rate_basis_usd"] > 0
    assert isinstance(data["approved"], bool)


def assert_scope_change_request(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(ScopeChangeStatus)
    assert data["decision_tier"] in _values(DecisionTier)
    assert 0 <= data["additional_hours"] <= 200.00
    assert 0 <= data["additional_deliverable_count"] <= 10


def assert_quality_review(data: dict):
    assert_identity_and_stamps(data)
    assert data["status"] in _values(QualityReviewStatus)
    assert data["outcome"] in _values(ReviewOutcome)
    assert data["round_no"] >= 1
    assert data["scored_deliverable_count"] >= 0


def assert_valuation_record(data: dict):
    assert_identity_and_stamps(data)
    assert data["method"] in _values(ValuationMethod)
    assert data["sequence_no"] >= 1
    assert data["hours_included"] >= 0
    assert data["base_amount_usd"] >= 0
    assert data["admin_overhead_usd"] >= 0
    assert abs(
        data["total_amount_usd"] - (data["base_amount_usd"] + data["admin_overhead_usd"])
    ) < 0.005, "total_amount_usd must be base_amount_usd plus admin_overhead_usd"


def assert_satisfaction_survey(data: dict):
    assert_light_row(data)
    for field in ("score_expertise", "score_responsiveness", "score_deliverable_fit"):
        assert 1 <= data[field] <= 5
    assert isinstance(data["would_recommend"], bool)
    assert isinstance(data["counted_in_index"], bool)
    assert 0.00 <= data["composite_score"] <= 100.00


def assert_decimals(value: float, places: int, label: str = "value"):
    """Assert a numeric field carries no more than `places` decimal places."""
    assert value is not None, f"{label} must not be null"
    scaled = round(float(value), places)
    assert abs(float(value) - scaled) < 10 ** -(places + 4), (
        f"{label} must carry {places} decimals, got {value}"
    )
