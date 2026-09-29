"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

TONNAGE_TOLERANCE = 1e-9


def assert_identity_and_audit(data: dict, entity_name: str = "resource") -> None:
    """`id` is a UUID with no prefix, `created_at`/`updated_at` are ISO 8601 UTC
    timestamps and `version` starts at 1 and increments on every mutation."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name} id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name} created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name} updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name} version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_identity(data: dict, entity_name: str = "grading") -> None:
    """A grading carries `id` and `created_at` only — no `updated_at`, no `version`."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name} id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name} created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def assert_whole_cents(value, field: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole number of cents as an integer, got {value!r}"
    )


def assert_tons(value, expected: float, field: str = "tons") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert abs(round(float(value), 3) - round(float(expected), 3)) < 5e-4, (
        f"{field} must be {expected:.3f} to 3 decimals, got {value}"
    )


def assert_one_decimal(value, field: str = "percentage") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert abs(round(float(value), 1) - float(value)) < 1e-9, (
        f"{field} must carry at most 1 decimal place, got {value}"
    )


def assert_grower(data: dict) -> None:
    assert_identity_and_audit(data, "grower")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["license_number"], str) and 4 <= len(data["license_number"]) <= 32
    assert isinstance(data["region_code"], str) and 2 <= len(data["region_code"]) <= 16
    assert data["status"] in ("ACTIVE", "SUSPENDED"), f"unexpected grower status {data['status']!r}"
    for counter in (
        "rejected_load_count_vintage",
        "expired_pick_call_count_vintage",
        "no_show_appointment_count_vintage",
        "prior_vintage_penalty_units",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be a non-negative integer"
    assert_whole_cents(data["outstanding_lien_balance_cents"], "outstanding_lien_balance_cents")
    for score in ("reliability_score_vintage", "reliability_score_lifetime"):
        assert 0.0 <= float(data[score]) <= 100.0, f"{score} must sit on the 0-to-100 scale"
        assert_one_decimal(data[score], score)


def assert_vineyard_block(data: dict) -> None:
    assert_identity_and_audit(data, "vineyard block")
    assert is_valid_uuid(data["grower_id"])
    assert isinstance(data["block_code"], str) and data["block_code"]
    assert isinstance(data["varietal"], str) and 3 <= len(data["varietal"]) <= 40
    assert float(data["acres"]) > 0
    assert float(data["expected_yield_tons_per_acre"]) > 0
    assert isinstance(data["ava_code"], str) and 2 <= len(data["ava_code"]) <= 24
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["delivered_net_tons_vintage"] is not None


def assert_quality_spec(data: dict) -> None:
    assert_identity_and_audit(data, "quality specification")
    assert isinstance(data["spec_code"], str) and 3 <= len(data["spec_code"]) <= 32
    assert float(data["brix_bonus_start"]) > float(data["min_brix_accept"])
    assert float(data["min_brix_accept"]) <= float(data["brix_penalty_start"]) <= float(data["brix_bonus_start"])
    assert float(data["rot_rejection_pct"]) > float(data["rot_free_pct"])
    assert float(data["ta_max_gl"]) > float(data["ta_min_gl"])
    assert float(data["max_total_penalty_pct"]) <= 100


def assert_grape_contract(data: dict) -> None:
    assert_identity_and_audit(data, "grape contract")
    assert is_valid_uuid(data["grower_id"])
    assert is_valid_uuid(data["quality_spec_id"])
    assert data["contract_basis"] in ("TONNAGE", "ACREAGE", "BLOCK")
    assert data["over_delivery_policy"] in ("ACCEPT_AT_CONTRACT", "ACCEPT_AT_SPOT", "REJECT")
    assert data["settlement_basis"] in ("LOAD_BY_LOAD", "WEIGHTED_BLEND")
    assert data["lifecycle_status"] in (
        "DRAFT",
        "OFFERED",
        "COUNTERED",
        "ACTIVE",
        "SETTLED",
        "CLOSED",
        "TERMINATION_PENDING",
        "TERMINATED",
        "WITHDRAWN",
    )
    assert data["renewal_status"] in (
        "NOT_DUE",
        "RENEWAL_WINDOW_OPEN",
        "RENEWED",
        "EVERGREEN_ROLLED",
        "NOT_RENEWING",
    )
    assert data["tonnage_status"] in ("OPEN", "CAP_REACHED", "HARD_CAP_REACHED")
    assert isinstance(data["offer_round"], int) and 0 <= data["offer_round"] <= 3
    assert_whole_cents(data["base_price_per_ton_cents"], "base_price_per_ton_cents")
    for money in (
        "provisional_settlement_cents",
        "final_settlement_cents",
        "prompt_pay_credit_cents",
        "lien_holdback_cents",
        "net_payable_cents",
    ):
        assert_whole_cents(data[money], money)
    assert isinstance(data["term_start_vintage"], int) and 2000 <= data["term_start_vintage"] <= 2100
    assert isinstance(data["term_end_vintage"], int) and data["term_end_vintage"] >= data["term_start_vintage"]


def assert_allocation(data: dict) -> None:
    assert_identity_and_audit(data, "allocation")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["block_id"])


def assert_lane(data: dict) -> None:
    assert_identity_and_audit(data, "crush-pad lane")
    assert isinstance(data["lane_code"], str) and 1 <= len(data["lane_code"]) <= 16
    assert float(data["daily_capacity_tons"]) > 0
    assert int(data["turnaround_buffer_minutes"]) >= 0
    assert float(data["max_load_tons"]) > 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["scheduled_appointment_count"], int)


def assert_sampling_crew(data: dict) -> None:
    assert_identity_and_audit(data, "sampling crew")
    assert isinstance(data["crew_code"], str) and 1 <= len(data["crew_code"]) <= 16
    assert isinstance(data["region_code"], str)
    assert int(data["max_concurrent_visits"]) >= 1
    assert isinstance(data["scheduled_visit_count"], int)


def assert_sampling_visit(data: dict) -> None:
    assert_identity_and_audit(data, "sampling visit")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["maturity_flag"] in (None, "PICK_READY", "IMMATURE")
    assert data["window_end"] > data["window_start"]


def assert_pick_call(data: dict) -> None:
    assert_identity_and_audit(data, "pick call")
    assert data["status"] in (
        "ISSUED",
        "ACKNOWLEDGED",
        "SUSPENDED_CAP",
        "FULFILLED",
        "EXPIRED",
        "WITHDRAWN",
    )
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 2
    assert float(data["estimated_tons"]) > 0


def assert_delivery_appointment(data: dict) -> None:
    assert_identity_and_audit(data, "delivery appointment")
    assert data["status"] in ("SCHEDULED", "ARRIVED", "CLOSED", "CANCELLED", "NO_SHOW")
    assert float(data["planned_tons"]) > 0
    assert isinstance(data["weigh_tag_count"], int) and data["weigh_tag_count"] >= 0
    assert data["window_end"] > data["window_start"]


def assert_weigh_tag(data: dict) -> None:
    assert_identity_and_audit(data, "weigh tag")
    assert data["weigh_status"] in ("GROSS_CAPTURED", "NET_FINAL")
    assert data["disposition"] in (
        "PENDING",
        "ACCEPTED",
        "PARTIALLY_ACCEPTED",
        "REJECTED_QUALITY",
        "REJECTED_OVER_CAP",
        "DISPUTED",
    )
    assert isinstance(data["gross_weight_lbs"], int) and 0 < data["gross_weight_lbs"] <= 200000
    assert isinstance(data["grade_count"], int) and data["grade_count"] >= 0
    assert isinstance(data["captured_by_user_id"], str) and data["captured_by_user_id"]
    for slice_field in (
        "contract_slice_tons",
        "over_slice_tons",
        "over_rejected_tons",
        "excess_rejected_tons",
    ):
        assert float(data[slice_field]) >= 0.0, f"{slice_field} may not be negative"


def assert_quality_grade(data: dict) -> None:
    assert_append_only_identity(data, "grading")
    assert is_valid_uuid(data["weigh_tag_id"])
    assert data["recommended_disposition"] in ("ACCEPT", "REJECT_QUALITY")
    for component in (
        "brix_component_pct",
        "acid_component_pct",
        "rot_component_pct",
        "mog_component_pct",
        "raw_adjustment_pct",
        "adjustment_pct",
    ):
        assert_one_decimal(data[component], component)
    assert isinstance(data["graded_by_user_id"], str) and data["graded_by_user_id"]


def assert_settlement_line(data: dict) -> None:
    assert_identity_and_audit(data, "settlement line")
    assert data["bucket"] in ("CONTRACT", "OVER_DELIVERY")
    assert data["status"] in ("PROVISIONAL", "FINAL", "VOID")
    assert_whole_cents(data["price_per_ton_cents"], "price_per_ton_cents")
    assert_whole_cents(data["gross_amount_cents"], "gross_amount_cents")
    assert_whole_cents(data["provisional_amount_cents"], "provisional_amount_cents")
    if data["final_amount_cents"] is not None:
        assert_whole_cents(data["final_amount_cents"], "final_amount_cents")


def assert_installment(data: dict) -> None:
    assert_identity_and_audit(data, "payment installment")
    assert data["status"] in (
        "PENDING_SETTLEMENT",
        "SCHEDULED",
        "PARTIALLY_PAID",
        "PAID",
        "DELINQUENT",
    )
    assert isinstance(data["installment_no"], int) and data["installment_no"] >= 1
    assert float(data["pct_of_settlement"]) > 0
    assert isinstance(data["lien_protected"], bool)
    assert_whole_cents(data["planned_amount_cents"], "planned_amount_cents")
    assert_whole_cents(data["paid_amount_cents"], "paid_amount_cents")


# --- Domain invariants ---------------------------------------------------------


def assert_slices_sum_to_net_tons(tag: dict) -> None:
    """The four slices always sum to exactly the load's `net_tons`."""
    total = (
        float(tag["contract_slice_tons"])
        + float(tag["over_slice_tons"])
        + float(tag["over_rejected_tons"])
        + float(tag["excess_rejected_tons"])
    )
    expected = float(tag["net_tons"] or 0.0)
    assert abs(round(total, 3) - round(expected, 3)) < 5e-4, (
        f"tonnage slices {total:.3f} must sum to net_tons {expected:.3f}"
    )


def assert_installments_sum_to_net_payable(installments: list, net_payable_cents: int) -> None:
    """After every close, the planned amounts sum to `net_payable_cents` exactly."""
    total = sum(int(row["planned_amount_cents"]) for row in installments)
    assert total == net_payable_cents, (
        f"installment planned amounts sum to {total}, expected net_payable_cents {net_payable_cents}"
    )


def assert_no_version_field(payload_echo: dict, field: str) -> None:
    assert field not in payload_echo, f"{field} must not be echoed onto the resource"
