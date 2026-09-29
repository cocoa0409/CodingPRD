"""Per-entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shared column helpers
# ---------------------------------------------------------------------------


def assert_audit_columns(entity: Dict[str, Any], label: str = "entity") -> None:
    """id is a UUID with no type prefix; created_at, updated_at and version present."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a bare UUID, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"{label}.version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{label}.version starts at 1, got {entity['version']}"


def assert_append_only_columns(entity: Dict[str, Any], label: str = "entity") -> None:
    """Append-only rows carry only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a bare UUID, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {entity.get('created_at')!r}"
    )
    assert "updated_at" not in entity, f"{label} must carry no updated_at at all"
    assert "version" not in entity, f"{label} must carry no version at all"


def assert_calendar_date(value: Any, label: str) -> None:
    """Date-typed fields are ISO 8601 calendar dates with no time component."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a YYYY-MM-DD calendar date with no time component, got {value!r}"
    )


def assert_fields_present(entity: Dict[str, Any], fields: List[str], label: str) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"{label} is missing declared fields: {missing}"


def assert_score_two_dp(value: Any, label: str) -> None:
    """Scores are carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must be carried to exactly two decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

MEMBERSHIP_TIER_FIELDS = [
    "code",
    "name",
    "tier_rank",
    "upfront_cost_cents",
    "annual_dues_cents",
    "entitlement_nights_class_a",
    "entitlement_nights_class_b",
    "entitlement_nights_class_c",
    "annual_total_night_cap",
    "advance_window_days",
    "max_consecutive_stay_nights",
    "min_out_nights_between_stays",
    "affiliate_access_enabled",
    "resale_allowed",
    "transfer_fee_cents",
]


def assert_membership_tier(tier: Dict[str, Any]) -> None:
    assert_audit_columns(tier, "MembershipTier")
    assert_fields_present(tier, MEMBERSHIP_TIER_FIELDS, "MembershipTier")
    assert isinstance(tier["affiliate_access_enabled"], bool), (
        "MembershipTier.affiliate_access_enabled must be a boolean"
    )
    assert isinstance(tier["resale_allowed"], bool), (
        "MembershipTier.resale_allowed must be a boolean"
    )
    assert 1 <= tier["tier_rank"] <= 5, "MembershipTier.tier_rank must be between 1 and 5"


def assert_member(member: Dict[str, Any]) -> None:
    assert_audit_columns(member, "Member")
    assert_fields_present(member, ["full_name", "email", "home_region", "status"], "Member")
    assert member["status"] in ("ACTIVE", "CLOSED"), (
        f"Member.status must be ACTIVE or CLOSED, got {member['status']!r}"
    )


MEMBERSHIP_FIELDS = [
    "member_id",
    "tier_id",
    "transferred_from_membership_id",
    "membership_status",
    "dues_status",
    "suspension_reason",
    "purchased_at",
    "tenure_origin_at",
    "upfront_paid_cents",
    "entitlement_year_start",
    "nights_used_class_a",
    "nights_used_class_b",
    "nights_used_class_c",
    "annual_nights_used",
    "dues_balance_cents",
    "dues_paid_through",
    "transfer_count",
    "resale_eligible_at",
    "tenure_years",
]


def assert_membership(membership: Dict[str, Any]) -> None:
    assert_audit_columns(membership, "Membership")
    assert_fields_present(membership, MEMBERSHIP_FIELDS, "Membership")
    assert membership["membership_status"] in (
        "ACTIVE",
        "SUSPENDED",
        "TRANSFER_PENDING",
        "TERMINATED",
    ), f"Membership.membership_status out of range: {membership['membership_status']!r}"
    assert membership["dues_status"] in ("CURRENT", "GRACE", "DELINQUENT", "WRITTEN_OFF"), (
        f"Membership.dues_status out of range: {membership['dues_status']!r}"
    )
    assert_calendar_date(membership["entitlement_year_start"], "Membership.entitlement_year_start")
    assert_entitlement_sum_consistent(membership)


def assert_entitlement_sum_consistent(membership: Dict[str, Any]) -> None:
    """annual_nights_used is the sum of the three class buckets."""
    total = (
        membership["nights_used_class_a"]
        + membership["nights_used_class_b"]
        + membership["nights_used_class_c"]
    )
    assert membership["annual_nights_used"] == total, (
        "annual_nights_used must equal the sum of the three class buckets: "
        f"{membership['annual_nights_used']} != {total}"
    )


PARK_FIELDS = [
    "name",
    "park_class",
    "affiliate_agreement_id",
    "network_type",
    "total_sites",
    "member_allocation_pct",
    "member_pool_sites",
    "transient_pool_sites",
    "season_open_date",
    "season_close_date",
    "park_status",
    "amenity_compliance_status",
    "rating_score",
    "forced_cancellation_count",
    "funded_capital_cents_ytd",
    "last_inspection_at",
]


def assert_park(park: Dict[str, Any]) -> None:
    assert_audit_columns(park, "Park")
    assert_fields_present(park, PARK_FIELDS, "Park")
    assert park["park_class"] in ("CLASS_A", "CLASS_B", "CLASS_C"), (
        f"Park.park_class out of range: {park['park_class']!r}"
    )
    assert park["park_status"] in ("SEASONAL_CLOSED", "OPEN", "MAINTENANCE_HOLD"), (
        f"Park.park_status out of range: {park['park_status']!r}"
    )
    assert park["network_type"] in ("CLUB_OWNED", "AFFILIATE"), (
        f"Park.network_type out of range: {park['network_type']!r}"
    )
    assert_pool_split_conserved(park)
    assert_score_two_dp(park["rating_score"], "Park.rating_score")


def assert_pool_split_conserved(park: Dict[str, Any]) -> None:
    """The two pools always sum exactly to the physical pad count."""
    assert park["member_pool_sites"] + park["transient_pool_sites"] == park["total_sites"], (
        "member_pool_sites plus transient_pool_sites must equal total_sites: "
        f"{park['member_pool_sites']} + {park['transient_pool_sites']} != {park['total_sites']}"
    )


def assert_pool_split(park: Dict[str, Any], member_sites: int, transient_sites: int) -> None:
    assert park["member_pool_sites"] == member_sites, (
        f"member_pool_sites expected {member_sites}, got {park['member_pool_sites']}"
    )
    assert park["transient_pool_sites"] == transient_sites, (
        f"transient_pool_sites expected {transient_sites}, got {park['transient_pool_sites']}"
    )
    assert_pool_split_conserved(park)


RESERVATION_FIELDS = [
    "park_id",
    "membership_id",
    "booker_type",
    "guest_name",
    "arrival_date",
    "departure_date",
    "scheduled_departure_date",
    "nights",
    "status",
    "pool_charged",
    "entitlement_nights_charged",
    "affiliate_nights_charged",
    "total_charge_cents",
    "extension_count",
    "extension_denied_count",
    "cancellation_reason",
    "checked_in_at",
    "checked_out_at",
    "consecutive_run_nights",
]


def assert_reservation(reservation: Dict[str, Any]) -> None:
    assert_audit_columns(reservation, "Reservation")
    assert_fields_present(reservation, RESERVATION_FIELDS, "Reservation")
    assert reservation["booker_type"] in ("MEMBER", "TRANSIENT"), (
        f"Reservation.booker_type out of range: {reservation['booker_type']!r}"
    )
    assert reservation["pool_charged"] in (
        "NONE",
        "MEMBER_POOL",
        "BORROWED_TRANSIENT",
        "TRANSIENT_POOL",
    ), f"Reservation.pool_charged out of range: {reservation['pool_charged']!r}"
    assert_half_open_night_count(reservation)


def assert_half_open_night_count(reservation: Dict[str, Any]) -> None:
    """nights is departure_date minus arrival_date in whole days."""
    from .constants import days_between

    expected = days_between(reservation["arrival_date"], reservation["departure_date"])
    assert reservation["nights"] == expected, (
        "nights must be departure_date minus arrival_date in whole days: "
        f"expected {expected}, got {reservation['nights']}"
    )


def assert_reservation_state(
    reservation: Dict[str, Any],
    status: str,
    pool_charged: Optional[str] = None,
    entitlement_nights_charged: Optional[int] = None,
) -> None:
    assert reservation["status"] == status, (
        f"Reservation.status expected {status}, got {reservation['status']}"
    )
    if pool_charged is not None:
        assert reservation["pool_charged"] == pool_charged, (
            f"Reservation.pool_charged expected {pool_charged}, got {reservation['pool_charged']}"
        )
    if entitlement_nights_charged is not None:
        assert reservation["entitlement_nights_charged"] == entitlement_nights_charged, (
            "Reservation.entitlement_nights_charged expected "
            f"{entitlement_nights_charged}, got {reservation['entitlement_nights_charged']}"
        )


def assert_waitlisted_debits_nothing(reservation: Dict[str, Any]) -> None:
    """A waitlisted stay debits absolutely nothing."""
    assert reservation["status"] == "WAITLISTED", (
        f"expected a WAITLISTED reservation, got {reservation['status']}"
    )
    assert reservation["pool_charged"] == "NONE", "a waitlisted stay holds no pool seat"
    assert reservation["entitlement_nights_charged"] == 0, (
        "a waitlisted stay charges no entitlement nights"
    )
    assert reservation["affiliate_nights_charged"] == 0, (
        "a waitlisted stay charges no partner quota nights"
    )
    assert reservation["departure_date"] == reservation["scheduled_departure_date"], (
        "a waitlisted stay still records the desired night set"
    )


AGREEMENT_FIELDS = [
    "partner_name",
    "status",
    "effective_from",
    "effective_to",
    "annual_member_night_quota",
    "reciprocity_ratio",
    "min_tier_rank",
    "advance_window_cap_days",
    "per_stay_night_cap",
    "settlement_rate_cents_per_night",
    "nights_consumed_ytd",
    "settlement_owed_cents",
]


def assert_affiliate_agreement(agreement: Dict[str, Any]) -> None:
    assert_audit_columns(agreement, "AffiliateAgreement")
    assert_fields_present(agreement, AGREEMENT_FIELDS, "AffiliateAgreement")
    assert agreement["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED"), (
        f"AffiliateAgreement.status out of range: {agreement['status']!r}"
    )
    assert_settlement_derived_from_quota(agreement)


def assert_settlement_derived_from_quota(agreement: Dict[str, Any]) -> None:
    """settlement_owed_cents is nights_consumed_ytd times the settlement rate."""
    expected = agreement["nights_consumed_ytd"] * agreement["settlement_rate_cents_per_night"]
    assert agreement["settlement_owed_cents"] == expected, (
        "settlement_owed_cents must be nights_consumed_ytd multiplied by "
        f"settlement_rate_cents_per_night: expected {expected}, "
        f"got {agreement['settlement_owed_cents']}"
    )


DUES_INVOICE_FIELDS = [
    "membership_id",
    "cycle_year",
    "amount_cents",
    "base_dues_cents",
    "capital_assessment_cents",
    "loyalty_credit_cents",
    "late_fee_cents",
    "paid_amount_cents",
    "due_date",
    "paid_at",
    "status",
    "days_past_due",
]


def assert_dues_invoice(invoice: Dict[str, Any]) -> None:
    assert_audit_columns(invoice, "DuesInvoice")
    assert_fields_present(invoice, DUES_INVOICE_FIELDS, "DuesInvoice")
    assert invoice["status"] in ("OPEN", "PAST_DUE", "PAID", "WRITTEN_OFF"), (
        f"DuesInvoice.status out of range: {invoice['status']!r}"
    )
    assert_calendar_date(invoice["due_date"], "DuesInvoice.due_date")
    assert_dues_waterfall_consistent(invoice)


def assert_dues_waterfall_consistent(invoice: Dict[str, Any]) -> None:
    """amount_cents is the subtotal less the loyalty credit."""
    subtotal = invoice["base_dues_cents"] + invoice["capital_assessment_cents"]
    assert invoice["amount_cents"] == subtotal - invoice["loyalty_credit_cents"], (
        "amount_cents must be base plus capital assessment less the loyalty credit: "
        f"{invoice['base_dues_cents']} + {invoice['capital_assessment_cents']} - "
        f"{invoice['loyalty_credit_cents']} != {invoice['amount_cents']}"
    )


def assert_invoice_components(
    invoice: Dict[str, Any],
    base_dues_cents: int,
    capital_assessment_cents: int,
    loyalty_credit_cents: int,
    amount_cents: int,
) -> None:
    assert invoice["base_dues_cents"] == base_dues_cents, (
        f"base_dues_cents expected {base_dues_cents}, got {invoice['base_dues_cents']}"
    )
    assert invoice["capital_assessment_cents"] == capital_assessment_cents, (
        "capital_assessment_cents expected "
        f"{capital_assessment_cents}, got {invoice['capital_assessment_cents']}"
    )
    assert invoice["loyalty_credit_cents"] == loyalty_credit_cents, (
        f"loyalty_credit_cents expected {loyalty_credit_cents}, "
        f"got {invoice['loyalty_credit_cents']}"
    )
    assert invoice["amount_cents"] == amount_cents, (
        f"amount_cents expected {amount_cents}, got {invoice['amount_cents']}"
    )
    assert_dues_waterfall_consistent(invoice)


TRANSFER_REQUEST_FIELDS = [
    "membership_id",
    "from_member_id",
    "to_member_id",
    "transfer_type",
    "sale_price_cents",
    "status",
    "transfer_fee_cents",
    "successor_membership_id",
    "decided_by_user_id",
    "decided_at",
    "rejection_reason",
]


def assert_transfer_request(request: Dict[str, Any]) -> None:
    assert_audit_columns(request, "TransferRequest")
    assert_fields_present(request, TRANSFER_REQUEST_FIELDS, "TransferRequest")
    assert request["transfer_type"] in ("GIFT", "RESALE", "ESTATE"), (
        f"TransferRequest.transfer_type out of range: {request['transfer_type']!r}"
    )
    assert request["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "VOIDED"), (
        f"TransferRequest.status out of range: {request['status']!r}"
    )


AMENITY_INSPECTION_FIELDS = [
    "park_id",
    "inspected_at",
    "inspector_user_id",
    "restroom_score",
    "hookup_score",
    "utility_score",
    "road_score",
    "composite_score",
    "result",
]


def assert_amenity_inspection(inspection: Dict[str, Any]) -> None:
    assert_append_only_columns(inspection, "AmenityInspection")
    assert_fields_present(inspection, AMENITY_INSPECTION_FIELDS, "AmenityInspection")
    assert inspection["result"] in ("PASS", "PROBATION", "FAIL"), (
        f"AmenityInspection.result out of range: {inspection['result']!r}"
    )
    assert_score_two_dp(inspection["composite_score"], "AmenityInspection.composite_score")


SURVEY_FIELDS = [
    "reservation_id",
    "park_id",
    "membership_id",
    "overall_rating",
    "cleanliness_rating",
    "staff_rating",
    "value_rating",
    "weighted_score",
    "submitted_at",
]


def assert_satisfaction_survey(survey: Dict[str, Any]) -> None:
    assert_append_only_columns(survey, "SatisfactionSurvey")
    assert_fields_present(survey, SURVEY_FIELDS, "SatisfactionSurvey")
    for field in ("overall_rating", "cleanliness_rating", "staff_rating", "value_rating"):
        assert 1 <= survey[field] <= 5, f"SatisfactionSurvey.{field} must be an integer 1 through 5"
    assert_score_two_dp(survey["weighted_score"], "SatisfactionSurvey.weighted_score")


CAPITAL_PROJECT_FIELDS = [
    "park_id",
    "title",
    "category",
    "requested_cost_cents",
    "fiscal_year",
    "status",
    "priority_score",
    "funded_amount_cents",
    "requested_by_user_id",
    "decided_by_user_id",
]


def assert_capital_project(project: Dict[str, Any]) -> None:
    assert_audit_columns(project, "CapitalProject")
    assert_fields_present(project, CAPITAL_PROJECT_FIELDS, "CapitalProject")
    assert project["category"] in ("SAFETY", "UTILITY", "AMENITY", "EXPANSION"), (
        f"CapitalProject.category out of range: {project['category']!r}"
    )
    assert project["status"] in ("PROPOSED", "APPROVED", "REJECTED", "FUNDED", "DEFERRED"), (
        f"CapitalProject.status out of range: {project['status']!r}"
    )
    assert isinstance(project["priority_score"], int), (
        f"priority_score must be an integer, got {project['priority_score']!r}"
    )


OCCUPANCY_EXCEPTION_FIELDS = [
    "reservation_id",
    "requested_run_nights",
    "tier_limit_nights",
    "reason",
    "status",
    "granted_run_nights",
    "requested_by_user_id",
    "decided_by_user_id",
    "decision_note",
]


def assert_occupancy_exception(exception: Dict[str, Any]) -> None:
    assert_audit_columns(exception, "OccupancyException")
    assert_fields_present(exception, OCCUPANCY_EXCEPTION_FIELDS, "OccupancyException")
    assert exception["reason"] in ("MEDICAL", "EMPLOYMENT", "WEATHER", "RIG_REPAIR"), (
        f"OccupancyException.reason out of range: {exception['reason']!r}"
    )
    assert exception["status"] in ("REQUESTED", "GRANTED", "DENIED"), (
        f"OccupancyException.status out of range: {exception['status']!r}"
    )


MAINTENANCE_WINDOW_FIELDS = [
    "park_id",
    "start_date",
    "end_date",
    "work_type",
    "status",
    "cancelled_reservation_count",
]


def assert_maintenance_window(window: Dict[str, Any]) -> None:
    assert_audit_columns(window, "MaintenanceWindow")
    assert_fields_present(window, MAINTENANCE_WINDOW_FIELDS, "MaintenanceWindow")
    assert window["work_type"] in ("ROUTINE", "CAPITAL", "EMERGENCY"), (
        f"MaintenanceWindow.work_type out of range: {window['work_type']!r}"
    )
    assert window["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED"), (
        f"MaintenanceWindow.status out of range: {window['status']!r}"
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_entitlement_counters(
    membership: Dict[str, Any],
    class_a: Optional[int] = None,
    class_b: Optional[int] = None,
    class_c: Optional[int] = None,
    annual: Optional[int] = None,
) -> None:
    if class_a is not None:
        assert membership["nights_used_class_a"] == class_a, (
            f"nights_used_class_a expected {class_a}, got {membership['nights_used_class_a']}"
        )
    if class_b is not None:
        assert membership["nights_used_class_b"] == class_b, (
            f"nights_used_class_b expected {class_b}, got {membership['nights_used_class_b']}"
        )
    if class_c is not None:
        assert membership["nights_used_class_c"] == class_c, (
            f"nights_used_class_c expected {class_c}, got {membership['nights_used_class_c']}"
        )
    if annual is not None:
        assert membership["annual_nights_used"] == annual, (
            f"annual_nights_used expected {annual}, got {membership['annual_nights_used']}"
        )
    assert_entitlement_sum_consistent(membership)


def assert_membership_axes(
    membership: Dict[str, Any],
    membership_status: str,
    dues_status: str,
    suspension_reason: Any = "__unchecked__",
) -> None:
    """The contract axis and the billing axis are independent; check both."""
    assert membership["membership_status"] == membership_status, (
        f"membership_status expected {membership_status}, got {membership['membership_status']}"
    )
    assert membership["dues_status"] == dues_status, (
        f"dues_status expected {dues_status}, got {membership['dues_status']}"
    )
    if suspension_reason != "__unchecked__":
        assert membership["suspension_reason"] == suspension_reason, (
            f"suspension_reason expected {suspension_reason!r}, "
            f"got {membership['suspension_reason']!r}"
        )


def assert_budget_conserved(result: Dict[str, Any]) -> None:
    """allocated_cents and unallocated_cents always sum to budget_cents."""
    assert result["allocated_cents"] + result["unallocated_cents"] == result["budget_cents"], (
        "allocated and unallocated must sum to the supplied budget: "
        f"{result['allocated_cents']} + {result['unallocated_cents']} != {result['budget_cents']}"
    )


def assert_version_bumped_by(before: int, after: int, expected_delta: int, label: str) -> None:
    assert after - before == expected_delta, (
        f"{label} version should move by exactly {expected_delta}: {before} -> {after}"
    )


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending, got {stamps}"


def assert_inspected_at_descending(rows: List[Dict[str, Any]]) -> None:
    """The per-park amenity-inspection list returns its rows newest first."""
    stamps = [row["inspected_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"inspections must be ordered by inspected_at descending, got {stamps}"
    )
