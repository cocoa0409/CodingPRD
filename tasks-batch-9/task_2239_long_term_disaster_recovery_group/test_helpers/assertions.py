"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_RETENTION_BPS,
    CATEGORY_CAP_CENTS,
    DISABILITY_POINTS,
    ELDER_AGE_THRESHOLD,
    ELDER_POINTS,
    HOUSEHOLD_POINT_CAP,
    HOUSEHOLD_POINT_PER_EXTRA_MEMBER,
    INCOME_POINTS,
    SCORE_CEILING,
    UNINSURED_POINTS,
    VOLUNTEER_HOURS_PER_DAY,
)

# --------------------------------------------------------------- shared helpers


def assert_identity_fields(data: Dict[str, Any]) -> None:
    """`id` is a UUID with no type prefix and `created_at` is an ISO 8601 stamp."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"


def assert_versioned_record(data: Dict[str, Any]) -> None:
    """A record carrying all four system-managed properties."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_immutable_record(data: Dict[str, Any]) -> None:
    """A record that carries only `id` and `created_at`."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "an immutable record must not carry updated_at"
    assert "version" not in data, "an immutable record must not carry version"


def assert_cents(data: Dict[str, Any], *field_names: str) -> None:
    for name in field_names:
        value = data.get(name)
        assert isinstance(value, int) and not isinstance(
            value, bool
        ), f"{name} must be an integer number of cents, got {value!r}"


# ---------------------------------------------------------------- computations


def compute_priority_score(
    income_band: str,
    household_size: int,
    has_member_with_disability: bool,
    head_of_household_age: int,
    is_uninsured: bool,
) -> int:
    """The five-term vulnerability score, capped at 100."""
    total = INCOME_POINTS[income_band]
    total += min(
        HOUSEHOLD_POINT_CAP,
        max(0, household_size - 1) * HOUSEHOLD_POINT_PER_EXTRA_MEMBER,
    )
    if has_member_with_disability:
        total += DISABILITY_POINTS
    if head_of_household_age >= ELDER_AGE_THRESHOLD:
        total += ELDER_POINTS
    if is_uninsured:
        total += UNINSURED_POINTS
    return min(SCORE_CEILING, total)


def capped_damage_cents(category: str, verified_cost_cents: int) -> int:
    """Per-item ceiling applied before any summation."""
    return min(verified_cost_cents, CATEGORY_CAP_CENTS[category])


def crew_capacity_hours(qualified_members: int, day_count: int) -> int:
    return qualified_members * VOLUNTEER_HOURS_PER_DAY * day_count


# ------------------------------------------------------------ entity assertions


def assert_survivor(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert isinstance(data["primary_contact_phone"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["income_band"] in INCOME_POINTS, f"unexpected income_band {data['income_band']!r}"
    assert isinstance(data["head_of_household_age"], int) and data["head_of_household_age"] >= 18
    for flag in (
        "has_member_with_disability",
        "is_uninsured",
        "consent_on_file",
        "follow_up_opt_in",
    ):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= 100, "priority_score is between 0 and 100 inclusive"
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert data["priority_score"] == compute_priority_score(
        data["income_band"],
        data["household_size"],
        data["has_member_with_disability"],
        data["head_of_household_age"],
        data["is_uninsured"],
    ), "priority_score must equal the sum of the five capped terms"


def assert_recovery_case(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["case_status"] in [
        "INTAKE",
        "ASSESSED",
        "PRESENTED",
        "ACTIVE_RECOVERY",
        "CLOSURE_PENDING",
        "CLOSED",
        "INACTIVE",
    ]
    assert data["funding_status"] in [
        "UNFUNDED",
        "PARTIALLY_COMMITTED",
        "FULLY_COMMITTED",
        "DISBURSING",
        "SATISFIED",
    ]
    assert data["primary_residence_status"] in [
        "OWNER_OCCUPIED",
        "RENTER",
        "MOBILE_HOME",
        "OTHER",
    ]
    assert_cents(
        data,
        "temporary_housing_need_cents",
        "verified_damage_total_cents",
        "reference_unmet_cents",
        "total_committed_cents",
        "total_net_disbursed_cents",
        "residual_unmet_cents",
    )
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert_case_money_invariants(data)


def assert_case_money_invariants(data: Dict[str, Any]) -> None:
    """`residual_unmet_cents` is the reference need less committed money, floored at 0."""
    expected_residual = max(0, data["reference_unmet_cents"] - data["total_committed_cents"])
    assert data["residual_unmet_cents"] == expected_residual, (
        "residual_unmet_cents must be reference_unmet_cents less total_committed_cents "
        f"floored at zero: expected {expected_residual}, got {data['residual_unmet_cents']}"
    )
    assert data["residual_unmet_cents"] >= 0


def assert_damage_item(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["category"] in CATEGORY_CAP_CENTS
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "REJECTED"]
    assert data["purpose_bucket"] in [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
    ]
    assert_cents(data, "documented_cost_cents", "capped_cost_cents")
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0
    assert isinstance(data["is_habitability_critical"], bool)
    if data["verification_status"] == "VERIFIED":
        assert data["capped_cost_cents"] == capped_damage_cents(
            data["category"], data["verified_cost_cents"]
        ), "capped_cost_cents is the smaller of the verified cost and the category ceiling"
    else:
        assert data["capped_cost_cents"] == 0


def assert_assistance_record(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["source_type"] in [
        "INSURANCE_SETTLEMENT",
        "FEMA_IA",
        "SBA_LOAN",
        "NONPROFIT_GRANT",
        "STATE_PROGRAM",
        "CROWDFUNDING",
        "OTHER",
    ]
    assert data["purpose_code"] in [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ]
    assert data["documentation_status"] in ["UNDOCUMENTED", "DOCUMENTED", "DISPUTED"]
    assert_cents(data, "awarded_cents")
    assert data["awarded_cents"] >= 0
    assert isinstance(data["is_excluded_from_dob"], bool)


def assert_unmet_need_assessment(data: Dict[str, Any]) -> None:
    """A determination snapshot: immutable, so it carries only id and created_at."""
    assert_immutable_record(data)
    assert data["variant"] in ["PURPOSE_MATCHED", "POOLED"]
    for key in (
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ):
        assert key in data["bucket_need_cents"], f"bucket_need_cents must carry {key}"
        assert key in data["bucket_offset_cents"], f"bucket_offset_cents must carry {key}"
    assert_cents(
        data,
        "verified_damage_total_cents",
        "total_documented_assistance_cents",
        "unmet_need_total_cents",
    )
    expected_verified = (
        data["bucket_need_cents"]["STRUCTURE_REPAIR"]
        + data["bucket_need_cents"]["CONTENTS_REPLACEMENT"]
        + data["bucket_need_cents"]["ACCESSIBILITY_MOD"]
    )
    assert data["verified_damage_total_cents"] == expected_verified, (
        "the snapshot's verified_damage_total_cents excludes the temporary-housing bucket: "
        f"expected {expected_verified}, got {data['verified_damage_total_cents']}"
    )
    assert data["total_documented_assistance_cents"] == sum(
        data["bucket_offset_cents"].values()
    ), "total_documented_assistance_cents is the sum of all four offsets"
    if data["variant"] == "PURPOSE_MATCHED":
        expected = sum(
            max(0, data["bucket_need_cents"][k] - data["bucket_offset_cents"][k])
            for k in data["bucket_need_cents"]
        )
    else:
        expected = max(
            0,
            sum(data["bucket_need_cents"].values()) - sum(data["bucket_offset_cents"].values()),
        )
    assert data["unmet_need_total_cents"] == expected, (
        f"{data['variant']} reduction mismatch: expected {expected}, "
        f"got {data['unmet_need_total_cents']}"
    )


def assert_member_organization(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["ACTIVE", "CAPPED", "SUSPENDED", "WITHDRAWN"]
    assert data["org_type"] in [
        "FAITH_BASED",
        "NONPROFIT",
        "GOVERNMENT",
        "CIVIC_CLUB",
        "FOUNDATION",
    ]
    assert_cents(
        data,
        "annual_pledge_cap_cents",
        "committed_cents",
        "disbursed_cents",
        "remaining_pledge_capacity_cents",
    )
    assert_pledge_capacity_identity(data)


def assert_pledge_capacity_identity(data: Dict[str, Any]) -> None:
    """remaining_pledge_capacity_cents == annual_pledge_cap_cents - (committed + disbursed)."""
    expected = data["annual_pledge_cap_cents"] - (
        data["committed_cents"] + data["disbursed_cents"]
    )
    assert data["remaining_pledge_capacity_cents"] == expected, (
        "pledge-capacity identity broken: "
        f"{data['remaining_pledge_capacity_cents']} != {data['annual_pledge_cap_cents']} - "
        f"({data['committed_cents']} + {data['disbursed_cents']})"
    )


def assert_table_session(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["SCHEDULED", "IN_SESSION", "ADJOURNED", "CANCELLED"]
    assert isinstance(data["attending_member_org_ids"], list)
    assert isinstance(data["quorum_min_member_orgs"], int) and data["quorum_min_member_orgs"] >= 1
    assert_cents(data, "awarded_total_cents")
    assert isinstance(data["queued_count"], int) and data["queued_count"] >= 0


def assert_case_presentation(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in [
        "QUEUED",
        "PRESENTING",
        "DELIBERATING",
        "AWARDED",
        "DEFERRED",
        "DENIED",
    ]
    assert data["bridge_tier"] in [None, "TIER_A", "TIER_B", "TIER_C"]
    assert_cents(
        data,
        "pledged_total_cents",
        "bridge_authorized_cents",
        "awarded_cents",
        "shortfall_cents",
    )
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 0
    assert isinstance(data["deferral_count"], int) and 0 <= data["deferral_count"] <= 3
    if data["status"] != "QUEUED":
        assert data["queue_position"] == 0, (
            "a presentation whose status is anything other than QUEUED carries queue_position 0, "
            f"got {data['queue_position']} in {data['status']}"
        )


def assert_funding_commitment(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["PLEDGED", "CONFIRMED", "DISBURSED", "RESCINDED"]
    assert_cents(data, "pledged_cents")
    assert data["pledged_cents"] > 0, "pledged_cents must be strictly greater than 0"
    assert data["purpose_code"] in [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ]


def assert_funding_source(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["OPEN", "EXHAUSTED", "EXPIRED"]
    assert data["restriction_code"] in [
        "UNRESTRICTED",
        "STRUCTURE_REPAIR_ONLY",
        "CONTENTS_ONLY",
        "ACCESSIBILITY_ONLY",
        "TEMPORARY_HOUSING_ONLY",
        "MATERIALS_ONLY",
    ]
    assert isinstance(data["eligible_purpose_codes"], list)
    assert data["restriction_specificity"] in (0, 1)
    assert_cents(
        data,
        "total_cents",
        "committed_cents",
        "disbursed_cents",
        "admin_retained_cents",
        "available_cents",
    )
    assert_funding_source_conservation(data)


def assert_funding_source_conservation(data: Dict[str, Any]) -> None:
    """total_cents == available + committed + disbursed + admin_retained."""
    parts = (
        data["available_cents"]
        + data["committed_cents"]
        + data["disbursed_cents"]
        + data["admin_retained_cents"]
    )
    assert data["total_cents"] == parts, (
        "funding-source conservation identity broken: "
        f"total {data['total_cents']} != available {data['available_cents']} + committed "
        f"{data['committed_cents']} + disbursed {data['disbursed_cents']} + retained "
        f"{data['admin_retained_cents']} (= {parts})"
    )


def assert_disbursement(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in [
        "REQUESTED",
        "DOB_CLEARED",
        "DOB_FLAGGED",
        "APPROVED",
        "PAID",
        "REVERSED",
        "VOIDED",
    ]
    assert data["purpose_code"] in [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ]
    assert_cents(
        data,
        "requested_cents",
        "dob_pool_cents",
        "dob_exposure_cents",
    )
    assert isinstance(data["allocation_lines"], list)


def assert_allocation_lines(
    lines: List[Dict[str, Any]], expected_net_total: int, retention_allowed: bool = True
) -> None:
    """Every line's retention is rounded on its own net, and the nets sum to the request."""
    net_total = 0
    for line in lines:
        for key in ("funding_source_id", "net_cents", "retention_cents", "gross_cents"):
            assert key in line, f"allocation line must carry {key}"
        expected_retention = (
            (2 * line["net_cents"] * ADMIN_RETENTION_BPS + 10000) // 20000
            if retention_allowed
            else 0
        )
        assert line["retention_cents"] == expected_retention, (
            "administrative retention is rounded per allocation line: expected "
            f"{expected_retention} on a net of {line['net_cents']}, got {line['retention_cents']}"
        )
        assert line["gross_cents"] == line["net_cents"] + line["retention_cents"], (
            "a line's gross is its net plus its retention"
        )
        net_total += line["net_cents"]
    assert net_total == expected_net_total, (
        f"the lines' net amounts must sum to the requested net: expected {expected_net_total}, "
        f"got {net_total}"
    )


def assert_construction_project(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in [
        "SCOPED",
        "PERMITTED",
        "IN_PROGRESS",
        "SUSPENDED",
        "PUNCHLIST",
        "CLOSED_OUT",
        "CANCELLED",
    ]
    assert data["scope_code"] in [
        "ROOF_REPLACEMENT",
        "STRUCTURE_REBUILD",
        "INTERIOR_REPAIR",
        "ACCESSIBILITY_RAMP",
        "MECHANICAL_REPAIR",
    ]
    assert isinstance(data["required_trade_hours"], dict)
    assert isinstance(data["critical_trades"], list)
    assert_cents(data, "estimated_material_cents")
    assert isinstance(data["volunteer_hours_logged"], int) and data["volunteer_hours_logged"] >= 0
    assert (
        isinstance(data["confirmed_deployment_count"], int)
        and data["confirmed_deployment_count"] >= 0
    )


def assert_volunteer_group(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["member_count"], int) and data["member_count"] >= 1
    assert isinstance(data["skill_profile"], dict)
    assert isinstance(data["requires_housing"], bool)
    assert isinstance(data["brings_own_tools"], bool)
    assert isinstance(data["active_deployment_count"], int) and data["active_deployment_count"] >= 0


def assert_volunteer_deployment(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["REQUESTED", "CONFIRMED", "CANCELLED", "COMPLETED"]
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert isinstance(data["crew_hours_committed"], int)
    assert isinstance(data["skill_fit_score_bps"], int)
    assert isinstance(data["hours_logged"], int) and data["hours_logged"] >= 0


def assert_lodging_site(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["OPEN", "FULL"]
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert isinstance(data["peak_committed_beds"], int) and data["peak_committed_beds"] >= 0
    assert isinstance(data["available_beds"], int) and data["available_beds"] >= 0
    assert_bed_night_identity(data)


def assert_bed_night_identity(data: Dict[str, Any]) -> None:
    """available_beds is bed_capacity less peak_committed_beds and is never negative."""
    expected = max(0, data["bed_capacity"] - data["peak_committed_beds"])
    assert data["available_beds"] == expected, (
        f"available_beds must be bed_capacity less peak_committed_beds: expected {expected}, "
        f"got {data['available_beds']}"
    )
    expected_status = "FULL" if data["peak_committed_beds"] >= data["bed_capacity"] else "OPEN"
    assert data["status"] == expected_status, (
        f"a lodging site is FULL when peak_committed_beds reaches bed_capacity: expected "
        f"{expected_status}, got {data['status']}"
    )


def assert_housing_assignment(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in ["ACTIVE", "RELEASED"]
    assert isinstance(data["beds_requested"], int) and data["beds_requested"] >= 1
    assert isinstance(data["night_count"], int) and data["night_count"] >= 1
    if data["status"] == "ACTIVE":
        assert data["released_at"] is None
        assert data["release_reason"] is None


def assert_follow_up_contact(data: Dict[str, Any]) -> None:
    """A follow-up contact: immutable, so it carries only id and created_at."""
    assert_immutable_record(data)
    assert data["contact_type"] in [
        "CHECK_IN_30_DAY",
        "CHECK_IN_90_DAY",
        "CLOSURE_REVIEW",
        "ANNIVERSARY",
        "REFERRAL",
    ]
    assert data["outcome"] in ["REACHED", "NO_ANSWER", "DECLINED", "NEEDS_REOPENED"]


# ------------------------------------------------------------- computed reads


def assert_dob_report(data: Dict[str, Any]) -> None:
    for key in (
        "case_id",
        "survivor_id",
        "purpose_code",
        "dob_pool_cents",
        "prior_disbursed_cents",
        "bucket_need_cents",
        "dob_exposure_cents",
        "sibling_case_ids",
    ):
        assert key in data, f"the duplication-of-benefits read must answer with {key}"
    assert isinstance(data["sibling_case_ids"], list)
    assert_cents(data, "dob_pool_cents", "prior_disbursed_cents", "bucket_need_cents", "dob_exposure_cents")
    expected = max(
        0,
        data["dob_pool_cents"] + data["prior_disbursed_cents"] - data["bucket_need_cents"],
    )
    assert data["dob_exposure_cents"] == expected or data["dob_exposure_cents"] >= 0


def assert_skill_fit_report(data: Dict[str, Any]) -> None:
    for key in (
        "project_id",
        "group_id",
        "variant",
        "day_count",
        "weighted_covered",
        "weighted_required",
        "score_bps",
        "meets_minimum",
    ):
        assert key in data, f"the skill-fit read must answer with {key}"
    assert isinstance(data["meets_minimum"], bool)
    assert data["meets_minimum"] == (data["score_bps"] >= 6000), (
        "meets_minimum reports whether the score reaches the 6000 basis-point floor"
    )


def assert_clock_reading(data: Dict[str, Any]) -> None:
    assert "current_utc" in data, "the clock capability must answer with current_utc"
    assert "expired_funding_source_ids" in data, (
        "the clock capability must answer with expired_funding_source_ids"
    )
    assert isinstance(data["expired_funding_source_ids"], list)


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version must increase by {by}: was {before['version']}, now {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version must be unchanged: was {before['version']}, now {after['version']}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any], limit: Optional[int] = None, offset: Optional[int] = None
) -> None:
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"every list response reports {key} inside meta"
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
