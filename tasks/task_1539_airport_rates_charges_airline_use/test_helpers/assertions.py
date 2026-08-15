"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. ConsultationComment, ActivityRecord, and
MIIVote are immutable event records and must NOT expose updated_at/version
(PRD common-resource-properties section).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def _assert_event_record(data: dict):
    """Immutable event records carry only id + created_at among common fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "event records must not expose updated_at"
    assert "version" not in data, "event records must not expose version"


def assert_fiscal_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year_label"], str) and data["year_label"]
    assert data["methodology"] in ("RESIDUAL", "COMPENSATORY", "HYBRID")
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    for field in ("airfield_opex_cents", "terminal_opex_cents",
                  "nonairline_airfield_revenue_cents",
                  "nonairline_terminal_revenue_cents",
                  "total_projected_landed_weight_kg",
                  "total_signatory_landed_weight_kg",
                  "total_rented_space_sqft"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["terminal_total_space_sqft"], int)
    assert isinstance(data["forecast_landed_weight_kg"], int)
    assert isinstance(data["prior_year_surplus_cents"], int)


def assert_airline(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 2
    assert data["iata_code"].isupper() and data["iata_code"].isalpha()
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["carrier_class"] in ("PASSENGER", "CARGO", "CHARTER")
    assert isinstance(data["pfc_approved"], bool)


def assert_airline_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["airline_id"], str)
    assert isinstance(data["fiscal_year_id"], str)
    assert data["signature_status"] in ("SIGNATORY", "NON_SIGNATORY")
    assert data["credit_standing"] in ("GOOD", "DELINQUENT", "SUSPENDED")
    assert isinstance(data["rented_space_sqft"], int)


def assert_rates_setting(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year_id"], str)
    assert data["status"] in ("DRAFT", "CONSULTATION", "ADOPTED", "SUPERSEDED",
                              "EXPIRED")
    for field in ("airfield_requirement_cents",
                  "signatory_landing_fee_per_1000kg_cents",
                  "non_signatory_landing_fee_per_1000kg_cents",
                  "terminal_rental_rate_per_sqft_year_cents",
                  "consultation_comment_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_consultation_comment(data: dict):
    _assert_event_record(data)
    assert isinstance(data["rates_setting_id"], str)
    assert isinstance(data["airline_id"], str)
    assert isinstance(data["body"], str)
    assert is_iso8601_timestamp(data.get("submitted_at", "")), (
        "submitted_at must be ISO 8601"
    )


def assert_activity_record(data: dict):
    _assert_event_record(data)
    assert isinstance(data["fiscal_year_id"], str)
    assert isinstance(data["airline_id"], str)
    assert isinstance(data["activity_date"], str)
    assert isinstance(data["landed_weight_kg"], int)
    assert data["landed_weight_kg"] > 0
    assert data["signature_status_at_activity"] in ("SIGNATORY", "NON_SIGNATORY")
    assert isinstance(data["billed_landing_fee_cents"], int)


def assert_capital_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year_id"], str)
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["cost_center"] in ("AIRFIELD", "TERMINAL")
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert 50 <= data["mii_threshold_pct"] <= 100
    assert data["status"] in ("PROPOSED", "MII_VOTING", "APPROVED", "REJECTED",
                              "VETOED", "CANCELLED")
    for field in ("votes_for_count", "votes_for_weight_kg",
                  "votes_against_weight_kg"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_mii_vote(data: dict):
    _assert_event_record(data)
    assert isinstance(data["capital_project_id"], str)
    assert isinstance(data["airline_id"], str)
    assert data["ballot"] in ("APPROVE", "REJECT")
    assert is_iso8601_timestamp(data.get("cast_at", "")), (
        "cast_at must be ISO 8601"
    )


def assert_annual_settlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year_id"], str)
    assert data["status"] in ("DRAFT", "COMPUTED", "AIRLINE_REVIEW", "DISPUTED",
                              "RESOLVED", "FINALIZED")
    for field in ("actual_airfield_requirement_cents",
                  "actual_terminal_requirement_cents",
                  "total_billed_landing_cents", "total_billed_terminal_cents",
                  "total_true_up_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_settlement_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["annual_settlement_id"], str)
    assert isinstance(data["airline_id"], str)
    for field in ("actual_airfield_share_cents", "actual_terminal_share_cents",
                  "billed_landing_cents", "billed_terminal_cents",
                  "true_up_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["payment_status"] in ("PENDING", "PAID", "CREDITED",
                                      "WRITTEN_OFF")


def assert_pfc_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year_id"], str)
    assert isinstance(data["airline_id"], str)
    assert isinstance(data["enplaned_passengers"], int)
    assert data["enplaned_passengers"] >= 0
    assert isinstance(data["pfc_amount_cents"], int)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


def assert_settlement_true_up_invariant(data: dict):
    """The PRD settlement invariant: total_true_up_cents equals the sum of the
    actual requirements minus the sum of the billed totals."""
    expected = (
        (data["actual_airfield_requirement_cents"]
         + data["actual_terminal_requirement_cents"])
        - (data["total_billed_landing_cents"] + data["total_billed_terminal_cents"])
    )
    assert data["total_true_up_cents"] == expected, (
        f"Settlement invariant broken: {data['total_true_up_cents']} != "
        f"({data['actual_airfield_requirement_cents']} + "
        f"{data['actual_terminal_requirement_cents']}) - "
        f"({data['total_billed_landing_cents']} + "
        f"{data['total_billed_terminal_cents']})"
    )
