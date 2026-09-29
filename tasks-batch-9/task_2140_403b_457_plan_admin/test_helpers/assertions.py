"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_employer(data: dict) -> None:
    _assert_common_fields(data, "Employer")
    assert data["entity_type"] in (
        "PUBLIC_SCHOOL", "TAX_EXEMPT_501C3", "GOVERNMENTAL_NON_SCHOOL", "CHURCH",
    )
    assert data["organization_subtype"] in (
        "SCHOOL", "HOSPITAL", "HOME_HEALTH_AGENCY",
        "HEALTH_AND_WELFARE_AGENCY", "CHURCH_ORG", "OTHER",
    )
    assert isinstance(data["is_governmental"], bool)
    assert isinstance(data["is_qualified_organization"], bool)
    assert data["total_employee_count"] >= 0


def assert_plan(data: dict) -> None:
    _assert_common_fields(data, "Plan")
    assert data["plan_type"] in ("PLAN_403B", "PLAN_457B")
    assert data["status"] in ("DRAFT", "ACTIVE", "FROZEN", "TERMINATED")
    assert data["nondiscrimination_regime"] in (
        "UA_ONLY", "UA_PLUS_410B_401A4", "GOVERNMENTAL_457_ALL_EMPLOYEES",
        "TOP_HAT_457", "CHURCH_EXEMPT",
    )
    assert data["compliance_posture"] in ("CLEAR", "UNDER_CORRECTION")
    assert data["open_correction_count"] >= 0
    assert 2000 <= data["plan_year"] <= 2100


def assert_vendor(data: dict) -> None:
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]


def assert_agreement(data: dict) -> None:
    _assert_common_fields(data, "InformationSharingAgreement")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["data_stale"], bool)
    assert data["effective_through"] >= data["effective_from"]


def assert_participant(data: dict) -> None:
    _assert_common_fields(data, "Participant")
    assert data["employment_status"] in ("ACTIVE", "TERMINATED")
    assert data["loan_eligibility_flag"] in ("AVAILABLE", "SUSPENDED")
    assert data["scheduled_hours_per_week"] >= 0
    assert data["prior_year_hours_worked"] >= 0
    assert data["includible_compensation_cents"] >= 0


def assert_universal_availability_notice(data: dict) -> None:
    """A notice is immutable: it carries id and created_at and nothing else common."""
    assert is_valid_uuid(data.get("id", "")), "UniversalAvailabilityNotice.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "UniversalAvailabilityNotice.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "A universal availability notice has no updated_at"
    assert "version" not in data, "A universal availability notice has no version"
    assert data["delivery_method"] in (
        "EMAIL", "PAPER_MAIL", "INTRANET_POSTING", "HAND_DELIVERY",
    )
    assert isinstance(data["is_valid"], bool)


def assert_eligibility_determination(data: dict) -> None:
    _assert_common_fields(data, "EligibilityDetermination")
    assert data["status"] in (
        "ELIGIBLE", "EXCLUDED_STUDENT", "EXCLUDED_LESS_THAN_20_HOURS",
        "EXCLUDED_NONRESIDENT_ALIEN", "EXCLUDED_NOT_TOP_HAT_GROUP",
        "INELIGIBLE_PLAN_NOT_ACTIVE",
    )
    assert data["notice_status"] in ("CURRENT", "INVALID", "MISSING")
    assert isinstance(data["universal_availability_applies"], bool)
    assert isinstance(data["superseded"], bool)


def assert_vendor_account(data: dict) -> None:
    _assert_common_fields(data, "VendorAccount")
    assert data["status"] in ("OPEN", "CLOSED")
    assert 0 <= data["vested_percentage_bps"] <= 10_000
    assert_vested_balance_consistent(data)


def assert_vested_balance_consistent(account: dict) -> None:
    """vested_balance_cents is floor(accumulated_benefit_cents * bps / 10000)."""
    expected = (account["accumulated_benefit_cents"] * account["vested_percentage_bps"]) // 10_000
    assert account["vested_balance_cents"] == expected, (
        f"Expected vested_balance_cents {expected}, got {account['vested_balance_cents']} "
        f"for accumulated_benefit_cents {account['accumulated_benefit_cents']} at "
        f"{account['vested_percentage_bps']} bps"
    )


def assert_contribution_election(data: dict) -> None:
    _assert_common_fields(data, "ContributionElection")
    assert data["state"] in ("SUBMITTED", "EFFECTIVE", "REJECTED", "SUPERSEDED", "REVOKED")
    assert data["catchup_election"] in (
        "NONE", "AGE_50", "SERVICE_15_YEAR", "FINAL_3_YEAR", "AGE_50_AND_SERVICE_15_YEAR",
    )
    assert data["annual_deferral_amount_cents"] > 0
    for field in (
        "basic_deferral_attributed_cents",
        "service_catchup_attributed_cents",
        "age50_catchup_attributed_cents",
        "final3yr_catchup_attributed_cents",
    ):
        assert data[field] >= 0, f"{field} may never be negative"


def assert_attribution_sums_to_elected_amount(election: dict) -> None:
    """The four attributed figures sum to exactly annual_deferral_amount_cents."""
    total = (
        election["basic_deferral_attributed_cents"]
        + election["service_catchup_attributed_cents"]
        + election["age50_catchup_attributed_cents"]
        + election["final3yr_catchup_attributed_cents"]
    )
    assert total == election["annual_deferral_amount_cents"], (
        f"Attribution buckets sum to {total}, expected "
        f"{election['annual_deferral_amount_cents']}"
    )


def assert_remittance_batch(data: dict) -> None:
    _assert_common_fields(data, "RemittanceBatch")
    assert data["deposit_state"] in ("WITHHELD", "DEPOSITED", "REVERSED")
    assert data["compliance_state"] in (
        "UNDETERMINED", "TIMELY", "LATE", "CORRECTION_PENDING", "CORRECTED",
    )
    assert data["calendar_days_late"] >= 0
    assert data["business_days_late"] >= 0
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1


def assert_remittance_correction(data: dict) -> None:
    _assert_common_fields(data, "RemittanceCorrection")
    assert data["state"] in ("OPEN", "SETTLED", "VOIDED")
    assert data["lost_earnings_total_cents"] >= 0
    assert data["excise_tax_cents"] >= 0
    assert isinstance(data["line_breakdown"], list)


def assert_line_breakdown_sums_to_total(correction: dict) -> None:
    """lost_earnings_total_cents is the sum of the already-rounded per-line figures."""
    total = sum(line["lost_earnings_cents"] for line in correction["line_breakdown"])
    assert total == correction["lost_earnings_total_cents"], (
        f"line_breakdown sums to {total}, but lost_earnings_total_cents is "
        f"{correction['lost_earnings_total_cents']}"
    )


def assert_participant_request(data: dict) -> None:
    _assert_common_fields(data, "ParticipantRequest")
    assert data["request_type"] in ("LOAN", "HARDSHIP", "UNFORESEEABLE_EMERGENCY")
    assert data["state"] in (
        "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO", "APPROVED",
        "DENIED", "DISBURSED", "PAID",
    )
    assert data["requested_amount_cents"] > 0
    assert data["resubmission_count"] >= 0


def assert_movement_request(data: dict) -> None:
    _assert_common_fields(data, "TransferExchangeRequest")
    assert data["request_kind"] in ("CONTRACT_EXCHANGE", "PLAN_TO_PLAN_TRANSFER")
    assert data["state"] in (
        "SUBMITTED", "ACCEPTED_BY_VENDOR", "REJECTED_BY_VENDOR", "APPROVED",
        "DENIED", "EXECUTED", "REVERSED",
    )
    assert data["amount_cents"] > 0
    assert data["resubmit_count"] >= 0


def assert_plan_compliance_posture_follows_count(plan: dict) -> None:
    """compliance_posture is UNDER_CORRECTION while open_correction_count > 0."""
    expected = "UNDER_CORRECTION" if plan["open_correction_count"] > 0 else "CLEAR"
    assert plan["compliance_posture"] == expected, (
        f"open_correction_count {plan['open_correction_count']} implies "
        f"compliance_posture {expected}, got {plan['compliance_posture']}"
    )


def assert_limit_summary_reconciles(summary: dict) -> None:
    """total_limit_cents = basic + usable catch-up; rooms are the limit less YTD, floored at 0."""
    assert summary["total_limit_cents"] == (
        summary["basic_limit_cents"] + summary["usable_catchup_capacity_cents"]
    ), "total_limit_cents must equal basic_limit_cents plus usable_catchup_capacity_cents"
    assert summary["room_gross_cents"] == max(
        0, summary["total_limit_cents"] - summary["ytd_gross_cents"]
    ), "room_gross_cents must be total_limit_cents less ytd_gross_cents, floored at zero"
    assert summary["room_verified_cents"] == max(
        0, summary["total_limit_cents"] - summary["ytd_verified_cents"]
    ), "room_verified_cents must be total_limit_cents less ytd_verified_cents, floored at zero"
