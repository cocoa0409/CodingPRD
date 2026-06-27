"""Entity assertions and domain invariant checkers for the Federal Acquisition API.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp) internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every full entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["uei"], str)
    assert isinstance(data["employee_count"], int)
    assert isinstance(data["set_aside_certifications"], list)
    assert data["sam_status"] in ["DRAFT", "ACTIVE", "EXPIRED", "EXCLUDED"]
    pi = data.get("performance_index")
    assert pi is None or isinstance(pi, (int, float))


def assert_solicitation(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert data["vehicle_type"] in ["RFP", "RFQ", "IFB"]
    assert data["set_aside_type"] in [
        "NONE", "SMALL_BUSINESS", "EIGHT_A", "SDVOSB", "WOSB", "HUBZONE",
    ]
    assert isinstance(data["naics_size_threshold"], int)
    assert data["status"] in [
        "DRAFT", "OPEN", "AMENDED", "CLOSED", "EVALUATED", "AWARDED", "CANCELLED",
    ]
    assert isinstance(data["amendment_count"], int)
    em = data.get("evaluation_method")
    assert em is None or em in ["TRADEOFF", "LPTA"]


def assert_evaluation_factor(data: dict):
    # EvaluationFactor carries ONLY id + created_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["TECHNICAL", "PAST_PERFORMANCE", "PRICE"]
    assert 0 <= data["weight"] <= 1


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data["solicitation_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["total_price_cents"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_EVALUATION", "ACCEPTABLE",
        "UNACCEPTABLE", "AWARDED", "REJECTED", "WITHDRAWN",
    ]
    ms = data.get("merit_score")
    assert ms is None or isinstance(ms, (int, float))
    vs = data.get("value_score")
    assert vs is None or isinstance(vs, (int, float))


def assert_factor_score(data: dict):
    _assert_common(data)
    assert isinstance(data["proposal_id"], str)
    assert isinstance(data["factor_id"], str)
    assert 0 <= data["raw_score"] <= 100


def assert_award(data: dict):
    _assert_common(data)
    assert isinstance(data["solicitation_id"], str)
    assert isinstance(data["proposal_id"], str)
    assert data["status"] in ["AWARDED", "PROTESTED", "VACATED"]


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["award_id"], str)
    assert data["contract_type"] in ["FFP", "CPFF"]
    assert isinstance(data["base_value_cents"], int)
    assert isinstance(data["obligated_amount_cents"], int)
    assert data["lifecycle_status"] in ["ACTIVE", "COMPLETE", "CLOSED", "TERMINATED"]
    assert data["funding_posture"] in ["WITHIN_CEILING", "CEILING_REACHED"]
    assert isinstance(data["cumulative_invoiced_cents"], int)


def assert_clin(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["clin_number"], str)
    assert isinstance(data["funded_qty"], int)
    assert isinstance(data["delivered_qty"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["fee_portion_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED"]


def assert_modification(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["mod_type"] in ["FUNDING", "OPTION_EXERCISE", "ADMINISTRATIVE"]
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED"]


def assert_protest(data: dict):
    _assert_common(data)
    assert isinstance(data["award_id"], str)
    assert isinstance(data["protester_vendor_id"], str)
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "SUSTAINED", "DENIED", "WITHDRAWN",
    ]


def assert_cpars(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["rating"] in [
        "EXCEPTIONAL", "VERY_GOOD", "SATISFACTORY", "MARGINAL", "UNSATISFACTORY",
    ]


def assert_contract_fiscal_invariants(data: dict):
    """Fiscal invariants that must hold after any contract operation (PRD §2.10, §3.5)."""
    assert data["cumulative_invoiced_cents"] >= 0
    assert data["obligated_amount_cents"] >= 0
    assert data["cumulative_invoiced_cents"] <= data["obligated_amount_cents"], (
        "cumulative invoiced must never exceed the obligation ceiling"
    )
    if data["cumulative_invoiced_cents"] == data["obligated_amount_cents"] \
            and data["obligated_amount_cents"] > 0:
        assert data["funding_posture"] == "CEILING_REACHED"
