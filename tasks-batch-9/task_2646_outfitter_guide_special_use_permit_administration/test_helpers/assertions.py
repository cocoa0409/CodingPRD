"""Record assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_identity_fields(data: dict, *, versioned: bool = True):
    """Every record carries an unprefixed UUID `id` and an ISO 8601 `created_at`.

    Records that are not append-only additionally carry `updated_at` and an
    integer `version` that starts at 1.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )


def assert_three_fractional_digits(timestamp: str):
    """Timestamps render in UTC with exactly three fractional-second digits."""
    assert timestamp.endswith("Z"), f"timestamp must be UTC, got {timestamp!r}"
    assert "." in timestamp, f"timestamp must carry fractional seconds, got {timestamp!r}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits, got {timestamp!r}"
    )


def assert_use_area(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert isinstance(data["total_allocated_service_days"], int)
    assert data["total_allocated_service_days"] >= 1
    assert isinstance(data["reserved_admin_service_days"], int)
    assert data["reserved_admin_service_days"] >= 0
    assert data["reserved_admin_service_days"] < data["total_allocated_service_days"]
    assert data["allocation_posture"] in ("OPEN", "CONSTRAINED", "EXHAUSTED")
    assert_allocation_identity(data)


def assert_allocation_identity(data: dict):
    """available = allocatable - committed - pending, and the posture follows
    from availability and the demand ratio."""
    allocatable = data["allocatable_service_days"]
    committed = data["committed_service_days"]
    pending = data["pending_service_days"]
    available = data["available_service_days"]
    assert available == allocatable - committed - pending, (
        "available_service_days must equal allocatable minus committed minus pending; "
        f"got {available} against {allocatable} - {committed} - {pending}"
    )
    if available <= 0:
        assert data["allocation_posture"] == "EXHAUSTED", (
            f"posture must be EXHAUSTED when available is {available}"
        )
    elif data["demand_ratio"] >= 0.8:
        assert data["allocation_posture"] == "CONSTRAINED", (
            f"posture must be CONSTRAINED at ratio {data['demand_ratio']}"
        )
    else:
        assert data["allocation_posture"] == "OPEN", (
            f"posture must be OPEN at ratio {data['demand_ratio']} with "
            f"{available} available"
        )


def assert_needs_assessment(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert data["public_need_finding"] in ("NEED_EXISTS", "NO_NEED")
    assert isinstance(data["prospectus_required"], bool)
    assert data["unallocated_service_days"] >= 0, (
        "unallocated_service_days is never reported below zero, got "
        f"{data['unallocated_service_days']}"
    )


def assert_outfitter(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("APPLICANT", "PERMITTED", "SUSPENDED")
    assert isinstance(data["ein"], str) and len(data["ein"]) == 9 and data["ein"].isdigit()
    assert isinstance(data["prequalification_insurance_verified"], bool)
    assert isinstance(data["active_permit_count"], int)
    assert isinstance(data["prior_permit_count"], int)
    assert data["active_permit_count"] >= 0
    assert data["prior_permit_count"] >= 0


def assert_guide(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("PENDING_QUALIFICATION", "QUALIFIED", "LAPSED")
    assert data["qualification_level"] in ("TRAINEE", "ASSISTANT", "LEAD")
    assert data["first_aid_cert_type"] in ("NONE", "BASIC_FIRST_AID", "WFR", "WEMT")
    assert isinstance(data["base_client_capacity"], int)
    assert data["base_client_capacity"] >= 0


def assert_permit_application(data: dict):
    assert_identity_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CAPACITY_SCREENED", "DIRECT_AWARD_PENDING",
        "PROSPECTUS_QUEUED", "PROSPECTUS_RESPONDED", "AWARDED", "PERMIT_ISSUED",
        "DENIED", "WITHDRAWN",
    )
    assert data["application_type"] in ("NEW", "RENEWAL")
    assert data["requested_service_days"] >= 1
    if data.get("routing_decision") is not None:
        assert data["routing_decision"] in ("DIRECT", "PROSPECTUS")


def assert_prospectus(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("OPEN", "EVALUATING", "AWARDED", "CANCELLED")
    assert data["offered_service_days"] >= 1
    assert isinstance(data["responsive_application_count"], int)


def assert_permit(data: dict):
    assert_identity_fields(data)
    assert data["administrative_status"] in (
        "ISSUED", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED", "CLOSED"
    )
    assert data["compliance_status"] in ("COMPLIANT", "PROBATION", "NONCOMPLIANT")
    assert isinstance(data["insurance_current"], bool)
    assert isinstance(data["bond_current"], bool)
    assert isinstance(data["fee_delinquent"], bool)
    assert isinstance(data["open_noncompliance_points"], int)
    assert isinstance(data["authorized_client_capacity_total"], int)
    assert isinstance(data["service_days_used_ytd"], int)
    assert isinstance(data["suspension_count"], int)
    assert data["term_end_date"] > data["term_start_date"], (
        "the closing date must be strictly after the opening date"
    )
    assert_compliance_derivation(data)


def assert_compliance_derivation(data: dict):
    """The compliance dimension is derived, first match winning: twelve or more
    open points is NONCOMPLIANT; five or more, or lapsed insurance, or a
    delinquent fee balance is PROBATION; otherwise COMPLIANT."""
    points = data["open_noncompliance_points"]
    if points >= 12:
        expected = "NONCOMPLIANT"
    elif points >= 5 or not data["insurance_current"] or data["fee_delinquent"]:
        expected = "PROBATION"
    else:
        expected = "COMPLIANT"
    assert data["compliance_status"] == expected, (
        f"compliance_status must derive to {expected} with points={points}, "
        f"insurance_current={data['insurance_current']}, "
        f"fee_delinquent={data['fee_delinquent']}; got {data['compliance_status']}"
    )


def assert_operating_plan(data: dict):
    assert_identity_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "APPROVED", "REJECTED",
    )
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 2
    assert isinstance(data["deficiency_sections"], list)
    assert data["completeness_score"] in (0.0, 25.0, 50.0, 75.0, 100.0), (
        f"completeness_score is a sum of 25.0-point awards, got {data['completeness_score']}"
    )


def assert_insurance_certificate(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED")
    assert data["coverage_type"] in (
        "GENERAL_LIABILITY", "AUTO_LIABILITY", "WATERCRAFT_LIABILITY"
    )
    assert isinstance(data["coverage_amount_cents"], int)
    assert isinstance(data["additional_insured_endorsed"], bool)
    assert data["expiration_date"] > data["effective_date"]


def assert_bond(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED")
    assert isinstance(data["bond_amount_cents"], int)
    assert isinstance(data["required_amount_cents"], int)
    assert 250_000 <= data["required_amount_cents"] <= 5_000_000, (
        "required_amount_cents is clamped to the floor and ceiling constants, got "
        f"{data['required_amount_cents']}"
    )
    assert data["expiration_date"] > data["effective_date"]


def assert_guide_authorization(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("AUTHORIZED", "REVOKED")
    assert isinstance(data["authorized_client_capacity"], int)
    assert data["authorized_client_capacity"] >= 0


def assert_trip_use_report(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "SUPERSEDED")
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["allowable_deductions_cents"], int)
    assert isinstance(data["adjusted_gross_revenue_cents"], int)
    assert data["adjusted_gross_revenue_cents"] == (
        data["gross_revenue_cents"] - data["allowable_deductions_cents"]
    ), "adjusted_gross_revenue_cents is gross revenue less allowable deductions"
    assert data["period_end_date"] > data["period_start_date"]


def assert_fee_assessment(data: dict):
    assert_identity_fields(data)
    assert data["status"] in ("PROVISIONAL", "FINAL", "PAID", "CLOSED")
    assert data["variant_applied"] in ("PROVISIONAL_PER_REPORT", "FINAL_AGGREGATE")
    for field in (
        "reported_agr_cents", "assessed_fee_cents", "paid_to_date_cents",
        "balance_due_cents", "credit_balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"
    assert isinstance(data["minimum_fee_applied"], bool)
    assert_money_identity(data)


def assert_money_identity(data: dict):
    """The assessed fee plus any credit balance always equals the amount paid to
    date plus the balance due."""
    left = data["assessed_fee_cents"] + data["credit_balance_cents"]
    right = data["paid_to_date_cents"] + data["balance_due_cents"]
    assert left == right, (
        "assessed_fee_cents + credit_balance_cents must equal "
        f"paid_to_date_cents + balance_due_cents; got {left} != {right}"
    )
    assert data["balance_due_cents"] >= 0
    assert data["credit_balance_cents"] >= 0


def assert_performance_evaluation(data: dict):
    """The evaluation record is append-only: it carries only `id` and
    `created_at` as common fields — no `updated_at` and no `version`."""
    assert_identity_fields(data, versioned=False)
    assert "version" not in data, (
        "the evaluation record carries no version field"
    )
    assert "updated_at" not in data, (
        "the evaluation record carries no updated_at field"
    )
    for band_field in ("provisional_band", "rating"):
        assert data[band_field] in (
            "SUPERIOR", "SATISFACTORY", "MARGINAL", "UNSATISFACTORY"
        )
    for score_field in (
        "resource_protection_score", "client_safety_score",
        "reporting_timeliness_score", "fee_compliance_score",
    ):
        assert isinstance(data[score_field], int) and 0 <= data[score_field] <= 100
    assert 0.0 <= data["penalty_points_applied"] <= 30.0, (
        "penalty_points_applied is capped at 30.0, got "
        f"{data['penalty_points_applied']}"
    )
    assert data["weighted_score"] >= 0.0, "weighted_score floors at 0.0"
    assert isinstance(data["evaluator_user_id"], str) and data["evaluator_user_id"]


def assert_noncompliance_action(data: dict):
    assert_identity_fields(data)
    assert data["severity"] in ("MINOR", "MODERATE", "MAJOR")
    assert data["action_type"] in ("WARNING", "SUSPENSION", "REVOCATION")
    assert data["status"] in ("ISSUED", "CURED", "APPEALED", "UPHELD", "RESCINDED")
    expected_points = {"MINOR": 2, "MODERATE": 5, "MAJOR": 10}[data["severity"]]
    assert data["points"] == expected_points, (
        f"{data['severity']} carries {expected_points} points, got {data['points']}"
    )
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_band(score: float, band: str):
    """A score of 90.0 or above is SUPERIOR, 75.0 or above SATISFACTORY, 60.0 or
    above MARGINAL, and anything lower UNSATISFACTORY."""
    if score >= 90.0:
        expected = "SUPERIOR"
    elif score >= 75.0:
        expected = "SATISFACTORY"
    elif score >= 60.0:
        expected = "MARGINAL"
    else:
        expected = "UNSATISFACTORY"
    assert band == expected, f"score {score} bands to {expected}, got {band}"


def assert_meta_envelope(meta: dict):
    """Every response's meta block carries a request identifier prefixed `req_`
    and an ISO 8601 timestamp."""
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must begin with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )


def assert_capacity_total_is_fresh_sum(permit: dict, authorizations: list):
    """The permit's capacity total is a fresh sum of the frozen capacities on
    its rows that are still authorized."""
    expected = sum(
        row["authorized_client_capacity"]
        for row in authorizations
        if row["status"] == "AUTHORIZED"
    )
    assert permit["authorized_client_capacity_total"] == expected, (
        "authorized_client_capacity_total must be the sum over authorized rows; "
        f"expected {expected}, got {permit['authorized_client_capacity_total']}"
    )
