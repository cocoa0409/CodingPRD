"""Entity assertions and domain invariant checkers.

Monetary comparisons go through :func:`assert_money`, which tolerates the cent
that a JSON number round-trip may cost.  Timestamps go through
:func:`assert_instant_equals`, which compares the *instant* rather than the
string, because the PRD pins the reading of the logical clock without pinning
whether a zero fractional part is rendered.
"""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ─── Primitive comparisons ───────────────────────────────────────────────────


def assert_money(actual, expected, label: str = "amount"):
    """Assert a monetary field equals the expected value to the cent."""
    assert actual is not None, f"{label} must be present"
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {label} of {expected}, got {actual}"
    )
    assert_cost_precision(float(actual))


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime."""
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equals(actual, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 readings denote the same instant."""
    assert actual is not None, f"{label} must be present"
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} at {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "resource"):
    """Every resource carries a server-minted UUID id and a created_at; most also
    carry updated_at and a version that begins at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{label} id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label} created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label} updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label} version must be an integer starting at 1"
    )


# ─── Entity assertions ───────────────────────────────────────────────────────


def assert_insured(data: dict):
    assert_common_fields(data, "insured")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["sector_code"] in [
        "TECH", "BIOTECH", "FINANCIAL", "ENERGY", "INDUSTRIAL", "CONSUMER",
    ]
    assert data["exchange_listing"] in ["LISTED", "PRIVATE", "NONE"]
    assert data["market_cap_usd"] >= 0
    assert data["entity_capacity_cap_usd"] > 0
    assert data["control_status"] in [
        "INDEPENDENT", "CHANGE_OF_CONTROL_ANNOUNCED", "ACQUIRED",
    ]
    assert data["capacity_posture"] in ["OPEN", "RESTRICTED", "EXHAUSTED"]
    assert data["open_policy_count"] >= 0
    assert data["aggregate_bound_side_c_usd"] >= 0
    assert data["available_side_c_capacity_usd"] >= 0
    if data["control_status"] != "INDEPENDENT":
        assert data["change_of_control_date"] is not None, (
            "a non-INDEPENDENT control_status must carry a change_of_control_date"
        )


def assert_capacity_derivation(insured: dict):
    """available_side_c_capacity_usd is entity_capacity_cap_usd less
    aggregate_bound_side_c_usd, floored at 0, and capacity_posture follows the
    unrounded utilisation ratio."""
    expected_available = max(
        0.0, insured["entity_capacity_cap_usd"] - insured["aggregate_bound_side_c_usd"]
    )
    assert_money(insured["available_side_c_capacity_usd"], expected_available,
                 "available_side_c_capacity_usd")
    cap = insured["entity_capacity_cap_usd"]
    utilisation = 0 if cap == 0 else insured["aggregate_bound_side_c_usd"] / cap
    if utilisation >= 1.00:
        expected_posture = "EXHAUSTED"
    elif utilisation >= 0.80:
        expected_posture = "RESTRICTED"
    else:
        expected_posture = "OPEN"
    assert insured["capacity_posture"] == expected_posture, (
        f"Expected capacity_posture {expected_posture} at utilisation "
        f"{utilisation}, got {insured['capacity_posture']}"
    )


def assert_disclosure_package(data: dict):
    assert_common_fields(data, "disclosure package")
    assert data["fiscal_year"] >= 2000
    assert is_iso8601_timestamp(data["filed_date"])
    assert isinstance(data["restatement_flag"], bool)
    assert data["material_weakness_count"] >= 0
    assert isinstance(data["going_concern_flag"], bool)
    assert isinstance(data["negative_operating_cash_flow_flag"], bool)
    assert data["debt_to_equity"] >= 0
    assert 0 <= data["independent_director_ratio"] <= 1
    assert isinstance(data["dual_class_shares_flag"], bool)
    assert isinstance(data["staggered_board_flag"], bool)
    assert isinstance(data["combined_ceo_chair_flag"], bool)
    assert isinstance(data["auditor_change_flag"], bool)
    assert 0 <= data["financial_subscore"] <= 60
    assert 0 <= data["governance_subscore"] <= 50


def assert_litigation_event(data: dict):
    """A litigation event is write-once at creation: it carries only ``id`` and
    ``created_at``.  It has neither ``updated_at`` nor ``version``."""
    assert is_valid_uuid(data.get("id", "")), "litigation event id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "litigation event created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        "a litigation event has no updated_at"
    )
    assert "version" not in data, (
        "a litigation event has no version and takes no concurrency token"
    )
    assert data["case_type"] in [
        "SECURITIES_CLASS_ACTION", "DERIVATIVE", "REGULATORY_ENFORCEMENT",
        "MERGER_OBJECTION", "EMPLOYMENT_PRACTICES", "FIDUCIARY",
    ]
    assert is_iso8601_timestamp(data["filed_date"])
    assert data["indemnity_paid_usd"] >= 0
    assert data["outcome"] in [None, "DISMISSED", "SETTLED", "JUDGMENT", "PENDING"]
    assert data["weight_units"] >= 0


def assert_submission(data: dict):
    assert_common_fields(data, "submission")
    assert data["status"] in ["DRAFT", "SCORED", "QUOTED", "BOUND", "EXPIRED"]
    assert data["requested_limit_usd"] > 0
    assert data["requested_retention_usd"] >= 0
    assert data["requested_side_c_sublimit_usd"] >= 0
    assert data["requested_program_target_limit_usd"] >= data["requested_limit_usd"]
    assert parse_instant(data["requested_period_end"]) > parse_instant(
        data["requested_period_start"]
    ), "requested_period_end must be strictly later than requested_period_start"
    assert data["erp_days"] >= 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["risk_band"] in [None, "LOW", "MODERATE", "ELEVATED", "SEVERE"]
    assert data["score_variant"] in [None, "INDICATIVE", "UNDERWRITTEN"]


def assert_risk_band_matches_score(submission: dict):
    """risk_band is LOW below 40, MODERATE from 40, ELEVATED from 70 and SEVERE at
    100 or above."""
    score = submission["risk_score"]
    assert score is not None, "a scored submission carries a risk_score"
    if score < 40:
        expected = "LOW"
    elif score < 70:
        expected = "MODERATE"
    elif score < 100:
        expected = "ELEVATED"
    else:
        expected = "SEVERE"
    assert submission["risk_band"] == expected, (
        f"Expected risk_band {expected} at risk_score {score}, "
        f"got {submission['risk_band']}"
    )


def assert_quote(data: dict):
    assert_common_fields(data, "quote")
    assert data["status"] in ["OFFERED", "ACCEPTED", "SUPERSEDED", "LAPSED"]
    assert data["offered_limit_usd"] > 0
    assert data["offered_retention_usd"] >= 0
    assert data["offered_side_c_sublimit_usd"] >= 0
    assert data["offered_side_c_sublimit_usd"] <= data["offered_limit_usd"]
    assert data["risk_band_at_quote"] in ["LOW", "MODERATE", "ELEVATED", "SEVERE"]
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data["quote_valid_until"])


def assert_premium_stack(quote: dict):
    """broker_commission_usd is the residual so that net and commission add back
    to gross exactly, and total_payable_usd is gross plus tax."""
    assert_money(quote["broker_commission_usd"],
                 quote["gross_premium_usd"] - quote["net_premium_usd"],
                 "broker_commission_usd")
    assert_money(quote["total_payable_usd"],
                 quote["gross_premium_usd"] + quote["premium_tax_usd"],
                 "total_payable_usd")
    assert 25_000.00 <= quote["net_premium_usd"] <= 2_500_000.00, (
        "net_premium_usd is clamped to a floor of 25,000 and a ceiling of 2,500,000"
    )


def assert_exclusion_term(data: dict):
    assert_common_fields(data, "exclusion term")
    assert data["exclusion_type"] in [
        "CONDUCT", "PRIOR_ACTS", "INSURED_VS_INSURED", "BODILY_INJURY", "REGULATORY",
    ]
    assert data["wording_variant"] in [
        "BROAD", "FINAL_ADJUDICATION", "NON_APPEALABLE_ADJUDICATION",
        "DERIVATIVE_CARVEBACK", "BANKRUPTCY_CARVEBACK",
        "RETRO_DATE_FULL_PRIOR_ACTS", "NONE",
    ]
    assert -0.25 <= data["premium_impact_pct"] <= 0.25
    assert data["status"] in ["PROPOSED", "COUNTERED", "AGREED", "REJECTED", "IMPASSE"]
    assert 1 <= data["round_count"] <= 4
    assert data["proposed_by_role"] in ["Underwriter", "RiskManager"]
    assert data["last_actor_role"] in ["Underwriter", "RiskManager"]
    if data["status"] != "AGREED":
        assert data["agreed_variant"] is None, (
            "agreed_variant is frozen only when a term is AGREED"
        )


def assert_policy(data: dict):
    assert_common_fields(data, "policy")
    assert data["policy_number"].startswith("DO-"), (
        "policy_number takes the form DO-NNNNNN"
    )
    assert len(data["policy_number"]) == 9, (
        "policy_number takes the form DO-NNNNNN with six zero-padded digits"
    )
    assert data["policy_number"][3:].isdigit()
    assert data["coverage_status"] in [
        "INCEPTED", "ACTIVE", "EXPIRED", "CANCELLED", "RUNOFF",
    ]
    assert data["premium_status"] in ["INVOICED", "PAID", "DELINQUENT"]
    assert data["tower_posture"] in [
        "INCOMPLETE", "CONTIGUOUS", "SEALED", "ERODED", "RELEASED",
    ]
    assert isinstance(data["tower_sealed"], bool)
    assert data["open_claim_count"] >= 0
    assert data["total_eroded_usd"] >= 0
    assert data["aggregate_remaining_usd"] >= 0
    assert data["placed_limit_usd"] >= 0
    assert_limit_conservation(data)


def assert_limit_conservation(policy: dict):
    """A policy's shared_aggregate_limit_usd equals its aggregate_remaining_usd
    plus its total_eroded_usd."""
    assert_money(
        policy["aggregate_remaining_usd"] + policy["total_eroded_usd"],
        policy["shared_aggregate_limit_usd"],
        "aggregate_remaining_usd + total_eroded_usd",
    )


def assert_coverage_part(data: dict):
    assert_common_fields(data, "coverage part")
    assert data["part"] in ["SIDE_A", "SIDE_B", "SIDE_C"]
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "RELEASED"]
    assert data["limit_usd"] > 0
    assert data["retention_usd"] >= 0
    assert data["eroded_usd"] >= 0
    if data["status"] == "EXHAUSTED":
        assert_money(data["remaining_limit_usd"], 0.0, "remaining_limit_usd")
    else:
        assert_money(data["remaining_limit_usd"],
                     max(0.0, data["limit_usd"] - data["eroded_usd"]),
                     "remaining_limit_usd")


def assert_coverage_part_creation_order(parts: list):
    """Coverage parts are created in a fixed order that later rounding rules
    depend on: SIDE_A first, then SIDE_B, then SIDE_C."""
    order = [p["part"] for p in parts]
    expected = [p for p in ["SIDE_A", "SIDE_B", "SIDE_C"] if p in order]
    assert order == expected, f"Expected coverage parts in order {expected}, got {order}"


def assert_layer(data: dict):
    assert_common_fields(data, "layer")
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert data["attachment_point_usd"] >= 0
    assert data["limit_usd"] > 0
    assert 0 < data["participation_pct"] <= 1
    assert data["form_type"] in ["FOLLOWING_FORM", "DIFFERENCE_IN_CONDITIONS"]
    assert data["status"] in ["ATTACHED", "EXHAUSTED", "RELEASED"]
    assert data["is_primary"] == (data["attachment_point_usd"] == 0), (
        "is_primary is true exactly when attachment_point_usd is 0"
    )
    if data["form_type"] == "DIFFERENCE_IN_CONDITIONS":
        assert data["dic_deviation_notes"], (
            "a DIFFERENCE_IN_CONDITIONS layer must carry dic_deviation_notes"
        )


def assert_runoff_endorsement(data: dict):
    assert_common_fields(data, "run-off endorsement")
    assert data["tail_years"] in [1, 2, 3, 6]
    assert data["tail_factor_applied"] in [0.75, 1.10, 1.45, 2.25]
    assert data["severity_load_applied"] in [0.00, 0.20]
    assert data["status"] in ["ENDORSED", "EXPIRED"]
    assert data["unexpired_premium_credit_usd"] >= 0
    assert data["runoff_premium_usd"] >= 0
    assert is_iso8601_timestamp(data["runoff_start_date"])
    assert is_iso8601_timestamp(data["runoff_end_date"])


def assert_circumstance_report(data: dict):
    assert_common_fields(data, "circumstance report")
    assert data["status"] in ["REPORTED", "MATURED", "LAPSED"]
    assert data["estimated_exposure_usd"] > 0
    assert is_iso8601_timestamp(data["notice_date"])
    assert is_iso8601_timestamp(data["reporting_deadline"])


def assert_claim(data: dict):
    assert_common_fields(data, "claim")
    assert data["status"] in [
        "NOTICED", "COVERAGE_ACCEPTED", "DEFENSE_ADVANCING",
        "SETTLEMENT_PENDING", "SETTLED", "DENIED",
    ]
    assert data["claim_type"] in [
        "SECURITIES_CLASS_ACTION", "DERIVATIVE", "REGULATORY_ENFORCEMENT",
        "EMPLOYMENT_PRACTICES", "INSURED_VS_INSURED", "FIDUCIARY",
    ]
    assert data["claimant_capacity"] in [
        "THIRD_PARTY", "SHAREHOLDER_DERIVATIVE", "FORMER_OFFICER",
        "BANKRUPTCY_TRUSTEE", "COMPANY",
    ]
    assert data["alleged_damages_usd"] > 0
    assert is_iso8601_timestamp(data["notice_date"])
    assert data["allocation_method"] in [None, "RELATIVE_EXPOSURE", "LARGER_SETTLEMENT"]
    assert data["denial_reason"] in [
        None, "CONDUCT_EXCLUSION", "PRIOR_ACTS", "INSURED_VS_INSURED",
        "LATE_NOTICE", "MISREPRESENTATION",
    ]
    assert isinstance(data["hammer_applied"], bool)
    for field in ("retention_applied_usd", "retention_remaining_usd",
                  "advanced_defense_usd", "indemnity_paid_usd",
                  "insurer_share_usd", "insured_retained_usd",
                  "unfunded_excess_usd"):
        assert data[field] >= 0, f"{field} must not be negative"


def assert_claim_at_notice(claim: dict, policy: dict):
    """A claim that clears all five gates is created in NOTICED with
    retention_remaining_usd initialised from the policy's retention_usd and every
    money field at 0."""
    assert claim["status"] == "NOTICED"
    assert_money(claim["retention_remaining_usd"], policy["retention_usd"],
                 "retention_remaining_usd")
    for field in ("retention_applied_usd", "advanced_defense_usd",
                  "indemnity_paid_usd", "insurer_share_usd",
                  "insured_retained_usd", "unfunded_excess_usd"):
        assert_money(claim[field], 0.0, field)
    assert claim["hammer_applied"] is False
    for field in ("allocation_method", "denial_reason", "decided_by_user_id"):
        assert claim[field] is None, f"{field} is null on a freshly noticed claim"


def assert_defense_invoice(data: dict):
    assert_common_fields(data, "defense invoice")
    assert data["status"] in ["SUBMITTED", "ADVANCED", "CLAWED_BACK", "VOIDED"]
    assert data["billed_amount_usd"] > 0
    assert_money(
        data["covered_matter_amount_usd"] + data["uncovered_matter_amount_usd"]
        + data["mixed_matter_amount_usd"],
        data["billed_amount_usd"],
        "covered + uncovered + mixed",
    )
    assert data["insured_person_defendant_count"] >= 0
    assert data["entity_defendant_count"] >= 0
    assert data["allocation_method_applied"] in [
        None, "RELATIVE_EXPOSURE", "LARGER_SETTLEMENT",
    ]


def assert_settlement_proposal(data: dict):
    assert_common_fields(data, "settlement proposal")
    assert data["status"] in [
        "RECOMMENDED", "CONSENTED", "REFUSED", "FUNDED", "HAMMER_APPLIED", "SUPERSEDED",
    ]
    assert data["recommended_amount_usd"] > 0
    assert isinstance(data["recommended_by_user_id"], str)
    assert data["insured_response"] in [None, "CONSENT", "REFUSE"]
    if data["insured_response"] == "CONSENT":
        assert data["hammer_pct_applied"] == pytest.approx(1.00)
    elif data["insured_response"] == "REFUSE":
        assert data["hammer_pct_applied"] == pytest.approx(0.70)
        assert data["refusal_reason"], "a refusal must state a refusal_reason"


# ─── Cross-entity invariants ─────────────────────────────────────────────────


def assert_parts_sum_to_share(parts: list, insurer_share_usd: float,
                              eroded_before: dict = None):
    """The parts must sum to insurer_share_usd exactly."""
    eroded_before = eroded_before or {}
    total = sum(p["eroded_usd"] - eroded_before.get(p["id"], 0.0) for p in parts)
    assert_money(total, insurer_share_usd, "sum of the per-part indemnity shares")


def assert_ops_run_counters(data: dict, **expected):
    """The epoch advance reports the new epoch counter, the clock reading it used
    and eight counters."""
    assert isinstance(data.get("epoch"), int), "the sweep reports an epoch counter"
    assert is_iso8601_timestamp(data.get("current_utc", "")), (
        "the sweep reports the clock reading it used"
    )
    counters = [
        "activated_policy_count", "expired_policy_count", "delinquent_policy_count",
        "lapsed_quote_count", "expired_submission_count", "reverted_submission_count",
        "lapsed_circumstance_report_count", "expired_runoff_count",
    ]
    for name in counters:
        assert name in data, f"the sweep must report {name}"
        assert isinstance(data[name], int), f"{name} must be an integer"
    for name, value in expected.items():
        assert name in counters, f"{name} is not one of the sweep's eight counters"
        assert data[name] == value, (
            f"Expected {name} of {value}, got {data[name]}"
        )


def find_part(parts: list, part_name: str) -> dict:
    matches = [p for p in parts if p["part"] == part_name]
    assert len(matches) == 1, f"Expected exactly one {part_name} part, got {len(matches)}"
    return matches[0]


def find_term(terms: list, exclusion_type: str) -> dict:
    matches = [t for t in terms if t["exclusion_type"] == exclusion_type]
    assert matches, f"Expected an exclusion term of type {exclusion_type}"
    return matches[0]


__all__ = [
    "assert_money", "parse_instant", "assert_instant_equals", "assert_common_fields",
    "assert_insured", "assert_capacity_derivation", "assert_disclosure_package",
    "assert_litigation_event", "assert_submission", "assert_risk_band_matches_score",
    "assert_quote", "assert_premium_stack", "assert_exclusion_term", "assert_policy",
    "assert_limit_conservation", "assert_coverage_part",
    "assert_coverage_part_creation_order", "assert_layer",
    "assert_runoff_endorsement", "assert_circumstance_report", "assert_claim",
    "assert_claim_at_notice", "assert_defense_invoice", "assert_settlement_proposal",
    "assert_parts_sum_to_share", "assert_ops_run_counters", "find_part", "find_term",
]
