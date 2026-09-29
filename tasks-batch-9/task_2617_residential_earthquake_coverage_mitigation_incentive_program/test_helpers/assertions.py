"""Domain assertion helpers.

Two kinds of helper live here: shape checkers that confirm a returned record
carries every field the PRD says it carries, and invariant checkers for the
conservation identities the PRD states about grant pools, premium ledgers, event
loss layering and post-event assessments.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(record: Dict[str, Any], label: str) -> None:
    """Every mutable record carries an identifier, both timestamps and a version."""
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"{label}.created_at is not an ISO 8601 UTC instant: {record['created_at']}"
    assert is_iso8601_timestamp(
        record["updated_at"]
    ), f"{label}.updated_at is not an ISO 8601 UTC instant: {record['updated_at']}"
    assert isinstance(record["version"], int), f"{label}.version is not an integer"
    assert record["version"] >= 1, f"{label}.version must start at one"


def _assert_fields_present(record: Dict[str, Any], fields: List[str], label: str) -> None:
    missing = [f for f in fields if f not in record]
    assert not missing, f"{label} is missing fields: {missing}"


def assert_policyholder_shape(record: Dict[str, Any]) -> None:
    """A policyholder record carries its contact details, county and standing."""
    _assert_common_fields(record, "Policyholder")
    _assert_fields_present(
        record,
        ["full_name", "email", "county_code", "outreach_campaign_code", "status"],
        "Policyholder",
    )


def assert_insurer_shape(record: Dict[str, Any]) -> None:
    """An insurer record carries its market share and every running counter."""
    _assert_common_fields(record, "ParticipatingInsurer")
    _assert_fields_present(
        record,
        [
            "name",
            "naic_code",
            "market_share_pct",
            "status",
            "compliance_status",
            "offers_recorded_count",
            "undocumented_decline_count",
            "last_take_up_rate_bp",
            "assessment_balance_cents",
            "policies_bound_count",
        ],
        "ParticipatingInsurer",
    )


def assert_dwelling_shape(record: Dict[str, Any]) -> None:
    """A dwelling record carries its rating characteristics and retrofit standing."""
    _assert_common_fields(record, "Dwelling")
    _assert_fields_present(
        record,
        [
            "policyholder_id",
            "street_address",
            "county_hazard_tier",
            "soil_class",
            "structure_type",
            "year_built",
            "dwelling_limit_cents",
            "retrofit_status",
            "verified_retrofit_scope",
            "grant_lifetime_count",
        ],
        "Dwelling",
    )


def assert_mandatory_offer_shape(record: Dict[str, Any]) -> None:
    """An offer record carries its parties, its validity window and its round."""
    _assert_common_fields(record, "MandatoryOffer")
    _assert_fields_present(
        record,
        [
            "insurer_id",
            "policyholder_id",
            "dwelling_id",
            "offered_at",
            "expires_at",
            "status",
            "decline_documented",
            "offer_round",
            "campaign_code",
            "responded_at",
        ],
        "MandatoryOffer",
    )


def assert_policy_shape(record: Dict[str, Any]) -> None:
    """A policy record carries its whole premium ledger and both status tracks."""
    _assert_common_fields(record, "Policy")
    _assert_fields_present(
        record,
        [
            "dwelling_id",
            "insurer_id",
            "policyholder_id",
            "accepted_offer_id",
            "deductible_pct",
            "contents_sublimit_cents",
            "loss_of_use_sublimit_cents",
            "rated_dwelling_limit_cents",
            "base_premium_cents",
            "rating_variant",
            "mitigation_discount_cents",
            "annual_premium_cents",
            "prorated_credit_cents",
            "lifecycle_status",
            "mitigation_status",
            "quote_expires_at",
            "effective_at",
            "expires_at",
            "term_number",
        ],
        "Policy",
    )


def assert_grant_cycle_shape(record: Dict[str, Any]) -> None:
    """A cycle record carries its window and all four pool figures."""
    _assert_common_fields(record, "GrantCycle")
    _assert_fields_present(
        record,
        [
            "program_track",
            "label",
            "opens_at",
            "closes_at",
            "total_pool_cents",
            "reserved_cents",
            "disbursed_cents",
            "uncommitted_cents",
            "status",
        ],
        "GrantCycle",
    )


def assert_retrofit_grant_shape(record: Dict[str, Any]) -> None:
    """A grant record carries its award, its bucket and both acting identities."""
    _assert_common_fields(record, "RetrofitGrant")
    _assert_fields_present(
        record,
        [
            "dwelling_id",
            "policy_id",
            "grant_cycle_id",
            "income_tier",
            "project_cost_estimate_cents",
            "requested_scope",
            "approved_amount_cents",
            "funded_from_bucket",
            "status",
            "review_round",
            "approved_by_user_id",
            "reserved_by_user_id",
            "denial_reason",
        ],
        "RetrofitGrant",
    )


def assert_contractor_shape(record: Dict[str, Any]) -> None:
    """A contractor record carries its scopes, its standing and both counters."""
    _assert_common_fields(record, "Contractor")
    _assert_fields_present(
        record,
        [
            "business_name",
            "license_no",
            "certified_scopes",
            "certification_status",
            "certification_expires_at",
            "open_project_count",
            "failed_inspection_count",
        ],
        "Contractor",
    )
    assert isinstance(record["certified_scopes"], list), "certified_scopes is not a list"


def assert_retrofit_project_shape(record: Dict[str, Any]) -> None:
    """A project record carries its scope, its attempt count and both instants."""
    _assert_common_fields(record, "RetrofitProject")
    _assert_fields_present(
        record,
        [
            "grant_id",
            "contractor_id",
            "scope_code",
            "status",
            "inspection_attempts",
            "started_at",
            "verified_at",
        ],
        "RetrofitProject",
    )


def assert_inspection_shape(record: Dict[str, Any]) -> None:
    """An inspection record carries its window, its outcome and who recorded it."""
    _assert_common_fields(record, "Inspection")
    _assert_fields_present(
        record,
        [
            "project_id",
            "contractor_id",
            "window_start",
            "window_end",
            "result",
            "inspector_user_id",
            "recorded_at",
            "deficiency_note",
        ],
        "Inspection",
    )


def assert_catastrophe_event_shape(record: Dict[str, Any]) -> None:
    """An event record carries every loss and assessment figure."""
    _assert_common_fields(record, "CatastropheEvent")
    _assert_fields_present(
        record,
        [
            "event_code",
            "magnitude",
            "epicenter_county_code",
            "occurred_at",
            "treaty_year",
            "retention_cents",
            "status",
            "aggregate_incurred_cents",
            "retained_cents",
            "ceded_total_cents",
            "uncovered_cents",
            "assessment_shortfall_cents",
            "admin_loading_cents",
            "assessment_total_cents",
            "claim_count",
        ],
        "CatastropheEvent",
    )


def assert_reinsurance_layer_shape(record: Dict[str, Any]) -> None:
    """A layer record carries its attachment, its limit, its share and its cession."""
    _assert_common_fields(record, "ReinsuranceLayer")
    _assert_fields_present(
        record,
        [
            "treaty_year",
            "layer_index",
            "attachment_point_cents",
            "limit_cents",
            "ceded_pct",
            "status",
            "ceded_cents",
        ],
        "ReinsuranceLayer",
    )


def assert_claim_shape(record: Dict[str, Any]) -> None:
    """A claim record carries all four damage inputs and all eight settlement figures."""
    _assert_common_fields(record, "Claim")
    _assert_fields_present(
        record,
        [
            "policy_id",
            "event_id",
            "structural_damage_cents",
            "cosmetic_damage_cents",
            "contents_damage_cents",
            "loss_of_use_cents",
            "deductible_applied_cents",
            "dwelling_part_cents",
            "contents_part_cents",
            "loss_of_use_part_cents",
            "provisional_payable_cents",
            "final_payable_cents",
            "payable_cents",
            "paid_cents",
            "adjustment_status",
            "payment_status",
            "provisional_adjuster_user_id",
            "final_adjuster_user_id",
            "reopen_count",
            "denial_reason",
        ],
        "Claim",
    )


def assert_assessment_allocation_shape(record: Dict[str, Any]) -> None:
    """An allocation row carries an identifier and a creation instant, and no more.

    This is the one record the PRD describes as an immutable ledger row, so it
    must not carry a modification instant or a version counter.
    """
    assert is_valid_uuid(record["id"]), f"allocation.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"allocation.created_at is not an ISO 8601 UTC instant: {record['created_at']}"
    _assert_fields_present(
        record,
        [
            "event_id",
            "insurer_id",
            "market_share_pct_snapshot",
            "assessed_cents",
            "allocation_rank",
            "absorbs_remainder",
        ],
        "AssessmentAllocation",
    )
    assert "updated_at" not in record, "an immutable ledger row must not carry updated_at"
    assert "version" not in record, "an immutable ledger row must not carry version"


# ─── Conservation invariants ──────────────────────────────────────────────────
def assert_grant_pool_conserved(cycle: Dict[str, Any]) -> None:
    """A cycle's reserved, disbursed and uncommitted figures exhaust its pool."""
    total = cycle["total_pool_cents"]
    reserved = cycle["reserved_cents"]
    disbursed = cycle["disbursed_cents"]
    uncommitted = cycle["uncommitted_cents"]
    assert reserved + disbursed + uncommitted == total, (
        "cycle pool is not conserved: reserved "
        f"{reserved} + disbursed {disbursed} + uncommitted {uncommitted} "
        f"!= total {total}"
    )
    assert reserved >= 0, "reserved figure went negative"
    assert disbursed >= 0, "disbursed figure went negative"
    assert uncommitted >= 0, "uncommitted figure went negative"


def assert_premium_ledger_consistent(policy: Dict[str, Any]) -> None:
    """A policy's annual premium is its base premium less its mitigation discount."""
    assert (
        policy["annual_premium_cents"]
        == policy["base_premium_cents"] - policy["mitigation_discount_cents"]
    ), (
        "premium ledger is inconsistent: base "
        f"{policy['base_premium_cents']} - discount "
        f"{policy['mitigation_discount_cents']} != annual "
        f"{policy['annual_premium_cents']}"
    )
    assert policy["mitigation_discount_cents"] >= 0, "discount went negative"
    assert policy["annual_premium_cents"] >= 0, "annual premium went negative"


def assert_event_loss_conserved(event: Dict[str, Any]) -> None:
    """An event's retained, ceded and uncovered amounts exhaust its incurred loss."""
    incurred = event["aggregate_incurred_cents"]
    retained = event["retained_cents"]
    ceded = event["ceded_total_cents"]
    uncovered = event["uncovered_cents"]
    assert retained + ceded + uncovered == incurred, (
        "event loss is not conserved: retained "
        f"{retained} + ceded {ceded} + uncovered {uncovered} "
        f"!= incurred {incurred}"
    )
    for name in ("retained_cents", "ceded_total_cents", "uncovered_cents"):
        assert event[name] >= 0, f"{name} went negative"


def assert_settlement_parts_sum(claim: Dict[str, Any], expected_total: int) -> None:
    """A claim's three coverage parts sum to its payable figure."""
    parts = (
        claim["dwelling_part_cents"]
        + claim["contents_part_cents"]
        + claim["loss_of_use_part_cents"]
    )
    assert parts == expected_total, (
        "settlement parts do not sum to the payable figure: "
        f"{claim['dwelling_part_cents']} + {claim['contents_part_cents']} + "
        f"{claim['loss_of_use_part_cents']} = {parts}, expected {expected_total}"
    )


def assert_assessment_allocations_sum(
    allocations: List[Dict[str, Any]],
    expected_total: int,
) -> None:
    """Allocated amounts sum exactly to the levied total, to the cent."""
    total = sum(a["assessed_cents"] for a in allocations)
    assert total == expected_total, (
        f"allocations sum to {total} but the levy total is {expected_total}"
    )
    remainder_holders = [a for a in allocations if a["absorbs_remainder"]]
    assert len(remainder_holders) == 1, (
        f"exactly one allocation must absorb the remainder, found {len(remainder_holders)}"
    )
    ranks = sorted(a["allocation_rank"] for a in allocations)
    assert ranks == list(range(1, len(allocations) + 1)), (
        f"allocation ranks are not a dense sequence from one: {ranks}"
    )
    assert remainder_holders[0]["allocation_rank"] == len(allocations), (
        "the remainder must be absorbed by the last-ranked allocation"
    )


def assert_insurer_assessment_balance(
    insurer: Dict[str, Any],
    expected_cents: int,
) -> None:
    """An insurer's running assessment balance matches what was levied on it."""
    assert insurer["assessment_balance_cents"] == expected_cents, (
        f"insurer assessment balance is {insurer['assessment_balance_cents']}, "
        f"expected {expected_cents}"
    )


def assert_monetary_amount(value: Any, label: str = "amount") -> None:
    """Money is carried as a whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_optional_timestamp(value: Optional[str], label: str) -> None:
    """A nullable instant is either absent or a well-formed UTC instant."""
    if value is None:
        return
    assert is_iso8601_timestamp(value), (
        f"{label} is neither null nor an ISO 8601 UTC instant: {value}"
    )
