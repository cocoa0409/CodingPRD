"""Entity assertions and domain invariant checkers.

The helpers here check only what the PRD states: identifier shape, timestamp
shape, the common fields every entity carries, the enumerated status domains and
the arithmetic invariants the PRD spells out (the hundred-point mix total, the
two-decimal money discipline, the four-decimal ratio discipline).
"""

from typing import Iterable, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY_TOLERANCE = 0.01
RATIO_TOLERANCE = 0.00005


# ---------------------------------------------------------------------------
# Generic value helpers
# ---------------------------------------------------------------------------
def assert_money(actual, expected, label: str = "amount") -> None:
    """Money and percentage fields carry two decimal places."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_ratio(actual, expected, label: str = "ratio") -> None:
    """Ratio fields carry four decimal places."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_two_decimal_money(value, label: str = "amount") -> None:
    if value is not None:
        assert_cost_precision(value)


def assert_common_fields(data: dict, entity: str = "entity") -> None:
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_status(data: dict, field: str, allowed: Iterable[str], entity: str = "entity") -> None:
    allowed = list(allowed)
    assert data.get(field) in allowed, (
        f"{entity}.{field} must be one of {allowed}, got {data.get(field)}"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_company(data: dict) -> None:
    assert_common_fields(data, "Company")
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert isinstance(data["ticker"], str) and data["ticker"].isupper()
    assert isinstance(data["is_issuer"], bool)
    assert data["gics_sector"] in [
        "TECH",
        "INDUSTRIALS",
        "HEALTHCARE",
        "FINANCIALS",
        "CONSUMER",
        "ENERGY",
    ]
    assert data["revenue_usd"] > 0, "revenue_usd must be positive"
    assert data["market_cap_usd"] > 0, "market_cap_usd must be positive"
    assert data["share_price_usd"] > 0, "share_price_usd must be positive"
    assert data["ceo_tdc_usd"] >= 0, "ceo_tdc_usd must be non-negative"
    assert_status(data, "listing_status", ["ACTIVE", "DELISTED"], "Company")


def assert_executive(data: dict) -> None:
    assert_common_fields(data, "Executive")
    assert is_valid_uuid(data["company_id"])
    assert isinstance(data["full_name"], str) and data["full_name"].strip()
    assert data["role_title"] in ["CEO", "CFO", "COO", "CHRO", "GC"]
    assert isinstance(data["is_neo"], bool)
    assert data["base_salary_usd"] > 0
    assert data["sti_target_pct"] >= 0


def assert_peer_group(data: dict) -> None:
    assert_common_fields(data, "PeerGroup")
    assert is_valid_uuid(data["issuer_company_id"])
    assert 2020 <= data["fiscal_year"] <= 2035
    assert data["benchmark_basis"] in ["RAW_MEDIAN", "SIZE_ADJUSTED"]
    assert_status(data, "status", ["DRAFT", "SCREENED", "APPROVED"], "PeerGroup")
    assert isinstance(data["accepted_member_count"], int)
    assert data["accepted_member_count"] >= 0


def assert_peer_group_member(data: dict) -> None:
    assert_common_fields(data, "PeerGroupMember")
    assert is_valid_uuid(data["peer_group_id"])
    assert is_valid_uuid(data["peer_company_id"])
    assert data["inclusion_reason"] in [
        "SIZE_MATCH",
        "INDUSTRY_MATCH",
        "BUSINESS_MODEL_ANALOG",
        "TALENT_COMPETITOR",
    ]
    assert_status(data, "status", ["ACCEPTED", "EXCLUDED"], "PeerGroupMember")
    assert isinstance(data["in_size_band"], bool)


def assert_pay_program(data: dict) -> None:
    assert_common_fields(data, "PayProgram")
    assert is_valid_uuid(data["issuer_company_id"])
    assert is_valid_uuid(data["peer_group_id"])
    assert is_valid_uuid(data["ceo_executive_id"])
    assert 2020 <= data["fiscal_year"] <= 2035
    assert_status(
        data,
        "design_status",
        ["DRAFT", "COMMITTEE_APPROVED", "DISCLOSED", "CLOSED"],
        "PayProgram",
    )
    assert_status(
        data, "vote_status", ["NOT_VOTED", "PASSED", "FAILED", "REMEDIATED"], "PayProgram"
    )
    assert_status(
        data,
        "benchmark_posture",
        ["UNBENCHMARKED", "BELOW_MARKET", "ALIGNED", "ABOVE_MARKET"],
        "PayProgram",
    )
    assert_status(
        data, "alignment_status", ["UNRATED", "ALIGNED", "WATCH", "MISALIGNED"], "PayProgram"
    )
    assert_pay_mix_totals_one_hundred(data)


def assert_pay_mix_totals_one_hundred(data: dict) -> None:
    """The hundred-point mix total is a conserved quantity."""
    total = data["salary_pct"] + data["sti_pct"] + data["lti_pct"]
    assert total == pytest.approx(100.00, abs=MONEY_TOLERANCE), (
        "salary_pct + sti_pct + lti_pct must equal exactly 100.00, got "
        f"{data['salary_pct']} + {data['sti_pct']} + {data['lti_pct']} = {total}"
    )


def assert_mix_components_in_bounds(data: dict) -> None:
    """No mix component may fall below 5.00 or rise above 80.00."""
    for field in ("salary_pct", "sti_pct", "lti_pct"):
        assert 5.00 <= data[field] <= 80.00, (
            f"{field} must stay within [5.00, 80.00], got {data[field]}"
        )


def assert_incentive_metric(data: dict) -> None:
    assert_common_fields(data, "IncentiveMetric")
    assert is_valid_uuid(data["pay_program_id"])
    assert data["metric_code"] in [
        "ADJ_EPS",
        "REVENUE_GROWTH",
        "FCF",
        "ROIC",
        "RTSR",
        "COST_RATIO",
    ]
    assert data["vehicle"] in ["ANNUAL_INCENTIVE", "LONG_TERM_PSU"]
    assert data["direction"] in ["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]
    assert data["interpolation"] in ["LINEAR", "STEP"]
    assert_status(
        data,
        "status",
        ["DRAFT", "LOCKED", "ADJUSTED", "RESULT_SUBMITTED", "CERTIFIED", "RESTATED"],
        "IncentiveMetric",
    )
    assert_goal_curve_monotonic(data)


def assert_goal_curve_monotonic(data: dict) -> None:
    """The curve must run strictly in the metric's declared direction."""
    threshold, target, maximum = (
        data["threshold_value"],
        data["target_value"],
        data["maximum_value"],
    )
    if data["direction"] == "HIGHER_IS_BETTER":
        assert threshold < target < maximum, (
            "HIGHER_IS_BETTER requires threshold_value < target_value < maximum_value, got "
            f"{threshold} / {target} / {maximum}"
        )
    else:
        assert threshold > target > maximum, (
            "LOWER_IS_BETTER requires threshold_value > target_value > maximum_value, got "
            f"{threshold} / {target} / {maximum}"
        )


def assert_payout_award(data: dict) -> None:
    assert_common_fields(data, "PayoutAward")
    assert is_valid_uuid(data["pay_program_id"])
    assert is_valid_uuid(data["executive_id"])
    assert data["vehicle"] in ["ANNUAL_INCENTIVE", "LONG_TERM_PSU", "RSU"]
    assert_status(
        data, "status", ["GRANTED", "VESTED", "FORFEITED", "CLAWED_BACK"], "PayoutAward"
    )
    assert_two_decimal_money(data.get("realized_value_usd"), "realized_value_usd")
    assert_two_decimal_money(data.get("realizable_value_usd"), "realizable_value_usd")


def assert_cda_draft(data: dict) -> None:
    assert_common_fields(data, "CdaDraft")
    assert is_valid_uuid(data["pay_program_id"])
    assert data["section_code"] in [
        "CD_AND_A",
        "SUMMARY_COMP_TABLE",
        "PAY_RATIO",
        "PVP_TABLE",
    ]
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert isinstance(data["required_tables_included"], bool)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert_status(
        data, "status", ["DRAFTING", "IN_REVIEW", "LEGAL_CLEARED", "FILED"], "CdaDraft"
    )


def assert_proxy_advisor_screen(data: dict) -> None:
    assert_common_fields(data, "ProxyAdvisorScreen")
    assert is_valid_uuid(data["pay_program_id"])
    assert data["advisor"] in ["ISS", "GLASS_LEWIS"]
    assert_status(data, "status", ["SCREENED", "STALE"], "ProxyAdvisorScreen")
    if data.get("concern_level") is not None:
        assert data["concern_level"] in ["LOW", "MEDIUM", "HIGH"]
    if data.get("recommendation") is not None:
        assert data["recommendation"] in ["FOR", "AGAINST"]


def assert_outreach_engagement(data: dict) -> None:
    assert_common_fields(data, "OutreachEngagement")
    assert is_valid_uuid(data["pay_program_id"])
    assert isinstance(data["investor_name"], str) and data["investor_name"].strip()
    assert data["investor_key"] == data["investor_key"].strip().upper(), (
        "investor_key is the investor_name trimmed and upper-cased, got "
        f"{data['investor_key']}"
    )
    assert 0.01 <= data["ownership_pct"] <= 100.00
    assert data["channel"] in ["CALL", "MEETING", "LETTER"]
    assert_status(
        data, "engagement_status", ["REQUESTED", "SCHEDULED", "HELD"], "OutreachEngagement"
    )
    if data.get("feedback_position") is not None:
        assert data["feedback_position"] in ["SUPPORTIVE", "CONCERNED", "OPPOSED"]


def assert_restatement_event(data: dict) -> None:
    assert_common_fields(data, "RestatementEvent")
    assert is_valid_uuid(data["company_id"])
    assert is_iso8601_timestamp(data["restatement_date"])
    assert is_iso8601_timestamp(data["lookback_start"])
    assert is_iso8601_timestamp(data["lookback_end"])
    assert data["lookback_start"] < data["lookback_end"], (
        "lookback_start must be strictly before lookback_end"
    )
    assert_status(
        data,
        "status",
        ["DECLARED", "ANALYZED", "RECOVERY_ORDERED", "CLOSED"],
        "RestatementEvent",
    )
    assert isinstance(data["determination_count"], int)
    assert data["recoverable_total_usd"] >= 0
    assert data["recovered_total_usd"] >= 0


def assert_clawback_determination(data: dict) -> None:
    assert_common_fields(data, "ClawbackDetermination")
    assert is_valid_uuid(data["restatement_event_id"])
    assert is_valid_uuid(data["payout_award_id"])
    assert_status(
        data, "status", ["CALCULATED", "NOTICED", "RECOVERED"], "ClawbackDetermination"
    )
    assert data["recoverable_amount_usd"] > 0, (
        "a determination is only written when the recoverable amount is above zero"
    )


# ---------------------------------------------------------------------------
# Cross-entity invariants stated by the PRD
# ---------------------------------------------------------------------------
def assert_program_pay_totals(program: dict, realized: float, realizable: float) -> None:
    assert_money(program["realized_pay_total_usd"], realized, "realized_pay_total_usd")
    assert_money(program["realizable_pay_total_usd"], realizable, "realizable_pay_total_usd")


def assert_alignment_band(program: dict) -> None:
    """The verdict bands the alignment gap on inclusive floors."""
    gap = program.get("degree_of_alignment")
    if gap is None:
        assert program["alignment_status"] == "UNRATED", (
            "a program with no alignment gap must report UNRATED"
        )
        return
    if gap >= -10.00:
        expected = "ALIGNED"
    elif gap >= -30.00:
        expected = "WATCH"
    else:
        expected = "MISALIGNED"
    assert program["alignment_status"] == expected, (
        f"degree_of_alignment {gap} must band to {expected}, got {program['alignment_status']}"
    )


def assert_screen_stale_keeps_last_scores(before: dict, after: dict) -> None:
    """Going STALE preserves the last computed score, level and recommendation."""
    assert after["status"] == "STALE", f"expected STALE, got {after['status']}"
    for field in ("concern_score", "concern_level", "recommendation"):
        assert after.get(field) == before.get(field), (
            f"a STALE screen keeps its last {field}: expected {before.get(field)}, "
            f"got {after.get(field)}"
        )


def assert_recovery_conserves_realized_dollars(
    award: dict, event: dict, expected_total: float
) -> None:
    """Award realized dollars plus the event's recovered dollars is conserved."""
    total = award["realized_value_usd"] + event["recovered_total_usd"]
    assert total == pytest.approx(expected_total, abs=MONEY_TOLERANCE), (
        "realized_value_usd + recovered_total_usd must be conserved: expected "
        f"{expected_total}, got {award['realized_value_usd']} + "
        f"{event['recovered_total_usd']} = {total}"
    )


def assert_metric_weights_total(metrics: Iterable[dict], expected: float = 100.00) -> None:
    total = sum(m["weight_pct"] for m in metrics)
    assert total == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"metric weight_pct values must total {expected}, got {total}"
    )


def find_by_id(rows: Iterable[dict], row_id: str) -> Optional[dict]:
    """Locate one row in a listing payload by id."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
