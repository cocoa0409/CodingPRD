"""Entity assertions and domain invariant checkers."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BASE_LIMITATION_DAYS, days_between

PERMIT_NUMBER_RE = re.compile(r"^STP-[0-9]{6}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def assert_integer_cents(value, field="amount"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be transported as an integer number of cents, got {value!r}"
    )


def assert_basis_points(value, field="rate"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of basis points, got {value!r}"
    )


def assert_common_fields(data: dict, entity="record"):
    """id, created_at, updated_at and version — the system-managed property set."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version must start at 1 or above"


def assert_append_only_fields(data: dict, entity="record"):
    """Only id and created_at — no updated_at and no version at all."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} must have no updated_at field at all"
    assert "version" not in data, f"{entity} must have no version field at all"


def assert_envelope_meta(body: dict):
    """meta.api_request_id starts with req_; the timestamp carries 3 fractional digits."""
    meta = body["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert TIMESTAMP_RE.match(str(meta["api_request_timestamp"])), (
        "api_request_timestamp must be ISO 8601 UTC with three fractional digits, "
        f"got {meta['api_request_timestamp']!r}"
    )


def assert_error_envelope(body: dict, expected_error_id=None):
    assert body["response_type"] == "error", "error responses carry response_type error"
    assert_envelope_meta(body)
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only the two fields, got {sorted(body['meta'])}"
    )
    data = body["data"]
    assert "error_id" in data and "message" in data, "error data carries error_id and message"
    if expected_error_id is not None:
        assert data["error_id"] == expected_error_id, (
            f"Expected {expected_error_id}, got {data['error_id']}"
        )


# --- Per-entity assertions ------------------------------------------------

def assert_taxpayer(data: dict):
    assert_common_fields(data, "taxpayer")
    assert 1 <= len(data["legal_name"]) <= 160
    assert PERMIT_NUMBER_RE.match(data["permit_number"]), (
        f"permit_number must be STP- plus exactly six digits, got {data['permit_number']!r}"
    )
    assert re.match(r"^\d{6}$", str(data["industry_naics_code"]))
    assert data["filing_frequency"] in ("MONTHLY", "QUARTERLY", "ANNUAL")
    assert_integer_cents(data["gross_receipts_annual_cents"], "gross_receipts_annual_cents")
    assert data["gross_receipts_annual_cents"] >= 0
    assert 0 <= data["delinquent_period_count"] <= 40
    if data["prior_audit_error_rate_bp"] is not None:
        assert 0 <= data["prior_audit_error_rate_bp"] <= 10_000
    assert data["compliance_status"] in ("COMPLIANT", "DELINQUENT", "REVOKED")
    for field in ("info_variance_bp", "delinquency_bp", "magnitude_bp", "prior_audit_bp"):
        assert_basis_points(data[field], field)
        assert 0 <= data[field] <= 10_000, f"{field} is capped at 10000"
    assert 0 <= data["screening_score"] <= 1_000
    assert data["open_audit_count"] >= 0


def assert_information_return(data: dict):
    assert_append_only_fields(data, "information return")
    assert data["source_type"] in (
        "FEDERAL_1099K",
        "WHOLESALER_REPORT",
        "MARKETPLACE_REPORT",
    )
    assert data["reported_amount_cents"] >= 0
    assert data["matched_return_amount_cents"] >= 0
    assert data["variance_cents"] == (
        data["reported_amount_cents"] - data["matched_return_amount_cents"]
    ), "variance_cents is the reported amount minus the matched amount"
    assert data["match_status"] in ("MATCHED", "UNDER_REPORTED", "OVER_REPORTED")
    assert isinstance(data["in_scoring_window"], bool)


def assert_industry_project(data: dict):
    assert_common_fields(data, "industry project")
    assert 1 <= len(data["project_name"]) <= 120
    assert 0 <= data["industry_error_rate_bp"] <= 10_000
    assert data["selection_mode"] in ("THRESHOLD", "QUOTA", "HYBRID")
    assert 0 <= data["selection_threshold_score"] <= 1_000
    assert data["selection_quota"] >= 1
    assert_quota_identity(data)


def assert_audit_lead(data: dict):
    assert_common_fields(data, "audit lead")
    assert data["status"] in ("SCORED", "SELECTED", "NOT_SELECTED", "CONVERTED", "DECLINED")
    assert 0 <= data["risk_score"] <= 1_000
    assert data["score_variant"] in ("SCREENING", "FULL")
    assert data["rank_position"] >= 1


def assert_audit(data: dict):
    assert_common_fields(data, "audit")
    assert data["status"] in (
        "PLANNED",
        "SCOPED",
        "FIELDWORK",
        "REVIEW_COMPLETE",
        "ASSESSED",
        "CLOSED",
        "ABANDONED",
    )
    assert data["statute_status"] in ("UNSET", "PROTECTED", "EXPIRING_SOON", "EXPIRED")
    assert data["projection_status"] in ("NOT_RUN", "CURRENT", "STALE")
    assert data["projection_method"] in ("NONE", "MEAN_PER_UNIT", "RATIO_ESTIMATION")
    for field in (
        "projected_deficiency_cents",
        "certificate_deficiency_cents",
        "use_tax_deficiency_cents",
    ):
        assert_integer_cents(data[field], field)
        assert data[field] >= 0
    assert isinstance(data["fraud_indicator"], bool)
    assert data["reopen_count"] >= 0


def assert_statute_waiver(data: dict):
    assert_common_fields(data, "statute waiver")
    assert data["status"] in ("DRAFTED", "EXECUTED", "VOIDED")
    assert DATE_RE.match(str(data["extended_to_date"]))
    assert isinstance(data["days_added"], int) and data["days_added"] >= 0


def assert_sampling_agreement(data: dict):
    assert_common_fields(data, "sampling agreement")
    assert data["status"] in ("PROPOSED", "COUNTERED", "AGREED", "SUPERSEDED")
    assert data["methodology"] in ("MEAN_PER_UNIT", "RATIO_ESTIMATION")
    assert data["confidence_level_bp"] in (9_000, 9_500, 9_900)
    assert data["minimum_sample_size"] >= 1
    strata = data["strata"]
    assert 1 <= len(strata) <= 12, "the strata array holds between 1 and 12 definitions"
    assert data["population_base_amount_cents"] == sum(
        s["population_base_amount_cents"] for s in strata
    ), "the agreement's population base is the sum of the strata's population bases"
    assert data["population_unit_count"] == sum(
        s["population_unit_count"] for s in strata
    ), "the agreement's population unit count is the sum of the strata's unit counts"
    assert 1 <= data["round_number"] <= 3


def assert_sample_unit(data: dict):
    assert_common_fields(data, "sample unit")
    assert data["stratum_index"] >= 0
    assert data["invoice_amount_cents"] > 0
    assert 0 <= data["exempt_sale_amount_cents"] <= data["invoice_amount_cents"]
    assert data["error_class"] in (
        "PENDING",
        "NO_ERROR",
        "UNREPORTED_TAXABLE_SALE",
        "CERTIFICATE_DEFECT",
        "RATE_ERROR",
    )
    assert_integer_cents(data["error_amount_cents"], "error_amount_cents")
    if data["error_class"] in ("PENDING", "NO_ERROR"):
        assert data["error_amount_cents"] == 0, (
            "error_amount_cents is 0 for both NO_ERROR and PENDING"
        )
    assert data["redetermination_count"] >= 0


def assert_exemption_certificate(data: dict):
    assert_common_fields(data, "exemption certificate")
    assert data["status"] in ("ON_FILE", "VALIDATED", "REJECTED", "CURED")
    assert data["claimed_exemption_type"] in (
        "RESALE",
        "MANUFACTURING",
        "AGRICULTURAL",
        "NONPROFIT",
        "GOVERNMENT",
    )
    assert data["covered_sale_amount_cents"] > 0
    expected_good_faith = bool(
        data["received_before_sale"]
        and data["form_complete"]
        and data["purchaser_permit_number"] is not None
        and data["claimed_exemption_matches_purchaser_business"]
    )
    assert data["good_faith_accepted"] is expected_good_faith, (
        "good_faith_accepted is true only when all four diligence conditions hold"
    )
    assert data["cure_count"] >= 0


def assert_use_tax_purchase(data: dict):
    assert_common_fields(data, "use-tax purchase")
    assert data["asset_class"] in ("CONSUMABLE", "CAPITAL_ASSET", "EXEMPT_MANUFACTURING")
    assert data["purchase_price_cents"] > 0
    assert 1 <= data["in_state_usage_pct_bp"] <= 10_000
    assert data["credit_applied_cents"] <= data["gross_use_tax_cents"], (
        "the credit is clamped at the gross tax so a purchase never produces a refund"
    )
    assert data["use_tax_due_cents"] == (
        data["gross_use_tax_cents"] - data["credit_applied_cents"]
    ), "use_tax_due_cents is gross_use_tax_cents less credit_applied_cents"
    assert data["reclassification_count"] >= 0


def assert_assessment(data: dict):
    assert_common_fields(data, "assessment")
    assert data["status"] in (
        "DRAFT",
        "DRAFT_STALE",
        "ISSUED",
        "FINAL",
        "WITHDRAWN",
        "SUPERSEDED",
    )
    assert data["collection_status"] in (
        "NOT_DUE",
        "DUE",
        "ARRANGED",
        "REFERRED",
        "SATISFIED",
    )
    for field in (
        "tax_deficiency_cents",
        "penalty_cents",
        "interest_cents",
        "provisional_total_due_cents",
        "total_due_cents",
        "balance_due_cents",
    ):
        assert_integer_cents(data[field], field)
    assert data["interest_days"] >= 0, "interest_days is floored at zero"
    assert isinstance(data["penalty_waived_small_balance"], bool)
    assert_money_identity(data)


def assert_assessment_adjustment(data: dict):
    assert_common_fields(data, "assessment adjustment")
    assert data["kind"] in (
        "PAYMENT",
        "PENALTY_ABATEMENT",
        "APPEAL_REDUCTION",
        "ASSESSMENT_VACATED",
        "COLLECTION_FEE",
        "OIC_WRITEOFF",
    )
    assert data["source"] in ("MANUAL", "SYSTEM")
    assert data["status"] in ("POSTED", "REVERSED")
    assert_integer_cents(data["amount_cents"], "amount_cents")
    if data["kind"] == "COLLECTION_FEE":
        assert data["amount_cents"] < 0, (
            "the collection fee is a charge and is therefore negative"
        )
    if data["kind"] != "PENALTY_ABATEMENT":
        assert data.get("abatement_pct") is None, (
            "abatement_pct is null on every non-abatement kind"
        )


def assert_appeal_proceeding(data: dict):
    assert_common_fields(data, "appeal proceeding")
    assert data["forum"] in (
        "INFORMAL_CONFERENCE",
        "ADMINISTRATIVE_APPEAL",
        "TAX_TRIBUNAL",
    )
    assert data["status"] in ("OPEN", "DECIDED")
    assert data["outcome"] in ("NONE", "SUSTAINED", "REDUCED", "REMANDED")
    assert 1 <= len(data["protest_basis"]) <= 500
    assert DATE_RE.match(str(data["filed_date"]))
    assert data["tolled_days"] >= 0


def assert_payment_arrangement(data: dict):
    assert_common_fields(data, "payment arrangement")
    assert data["arrangement_type"] in ("INSTALLMENT_PLAN", "OFFER_IN_COMPROMISE")
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "COMPLETED",
        "DEFAULTED",
        "CANCELLED",
    )
    assert data["payments_made_count"] >= 0
    assert data["amount_paid_cents"] >= 0
    if data["arrangement_type"] == "INSTALLMENT_PLAN":
        assert data["scheduled_total_cents"] == (
            data["monthly_installment_cents"] * data["term_months"]
        ), "an installment plan's scheduled total is the installment times the term"
    else:
        assert data["scheduled_total_cents"] == data["offer_amount_cents"], (
            "an offer in compromise's scheduled total is the offer amount"
        )


# --- Conserved quantities -------------------------------------------------

def assert_money_identity(assessment: dict):
    """balance_due_cents + total_adjustments_cents + amount_paid_cents == total_due_cents."""
    total = (
        assessment["balance_due_cents"]
        + assessment["total_adjustments_cents"]
        + assessment["amount_paid_cents"]
    )
    assert total == assessment["total_due_cents"], (
        "Assessed-money identity broken: "
        f"{assessment['balance_due_cents']} + {assessment['total_adjustments_cents']} + "
        f"{assessment['amount_paid_cents']} != {assessment['total_due_cents']}"
    )


def assert_quota_identity(project: dict):
    """selection_quota == selections_used + selections_remaining."""
    assert project["selection_quota"] == (
        project["selections_used"] + project["selections_remaining"]
    ), (
        "Selection-quota identity broken: "
        f"{project['selection_quota']} != {project['selections_used']} + "
        f"{project['selections_remaining']}"
    )


def assert_limitation_days_identity(audit: dict):
    """statute_expiry_date - base_statute_expiry_date == waiver_days_added + tolled_days."""
    delta = days_between(audit["base_statute_expiry_date"], audit["statute_expiry_date"])
    assert delta == audit["waiver_days_added"] + audit["tolled_days"], (
        "Limitation-days identity broken: expiry moved "
        f"{delta} days but waiver_days_added={audit['waiver_days_added']} and "
        f"tolled_days={audit['tolled_days']}"
    )


def assert_base_statute_expiry(audit: dict):
    """base_statute_expiry_date is scope_period_end advanced by 1,095 calendar days."""
    assert days_between(audit["scope_period_end"], audit["base_statute_expiry_date"]) == (
        BASE_LIMITATION_DAYS
    ), "base_statute_expiry_date is scope_period_end plus 1,095 calendar days"
