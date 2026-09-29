"""Reusable assertion helpers for cross-cutting contract rules."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_record_fields(record, expected_version=None):
    """Every stored row carries an id, a version and both timestamps."""
    assert is_valid_uuid(record["id"]), f"id is not a uuid: {record['id']}"
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, f"version must begin at 1, got {record['version']}"
    assert is_iso8601_timestamp(record["created_at"]), f"bad created_at: {record['created_at']}"
    assert is_iso8601_timestamp(record["updated_at"]), f"bad updated_at: {record['updated_at']}"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_version_bumped_by(new_record, old_record, increment=1):
    """A mutation raises version by exactly ``increment``."""
    assert new_record["version"] == old_record["version"] + increment, (
        f"expected version {old_record['version'] + increment}, got {new_record['version']}"
    )


def assert_version_unchanged(new_record, old_version):
    """A rejected call must not bump the row's version."""
    assert new_record["version"] == old_version, (
        f"version moved from {old_version} to {new_record['version']}"
    )


def assert_pagination_meta(meta, limit, offset, total_count, has_more):
    """The meta block of a list response reports the whole window."""
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_no_error_envelope(data):
    """A success envelope carries no error identifier and no message."""
    assert "error_id" not in data or data.get("error_id") is None, (
        f"success payload carried error_id {data.get('error_id')}"
    )
    assert "message" not in data or data.get("message") is None, (
        f"success payload carried message {data.get('message')}"
    )


def assert_provider_posture(provider, membership_status, network_posture):
    """Membership status and derived posture agree with the mapping."""
    assert provider["membership_status"] == membership_status, (
        f"expected membership_status {membership_status}, got {provider['membership_status']}"
    )
    assert provider["network_posture"] == network_posture, (
        f"expected network_posture {network_posture}, got {provider['network_posture']}"
    )


def assert_quality(provider, quality_score, quality_tier, quality_variant_applied):
    """The quality triple is reported consistently."""
    assert float(provider["quality_score"]) == quality_score, (
        f"expected quality_score {quality_score}, got {provider['quality_score']}"
    )
    assert provider["quality_tier"] == quality_tier, (
        f"expected quality_tier {quality_tier}, got {provider['quality_tier']}"
    )
    assert provider["quality_variant_applied"] == quality_variant_applied, (
        f"expected quality_variant_applied {quality_variant_applied}, "
        f"got {provider['quality_variant_applied']}"
    )


def assert_slot_counters(contract, committed_slots, available_slots):
    """Slot conservation: committed plus available equals the contracted count."""
    assert contract["committed_slots"] == committed_slots, (
        f"expected committed_slots {committed_slots}, got {contract['committed_slots']}"
    )
    assert contract["available_slots"] == available_slots, (
        f"expected available_slots {available_slots}, got {contract['available_slots']}"
    )
    assert contract["committed_slots"] + contract["available_slots"] == (
        contract["contracted_slots"]
    ), "committed plus available slots must equal contracted slots"


def assert_remitted_cents_conserved(contract, claims):
    """Remitted cents equal paid cents across claims plus the unallocated credit."""
    paid_total = sum(claim["paid_cents"] for claim in claims)
    assert contract["remitted_cents"] == paid_total + contract["unallocated_credit_cents"], (
        f"remitted_cents {contract['remitted_cents']} != paid total {paid_total} "
        f"+ unallocated credit {contract['unallocated_credit_cents']}"
    )


def assert_allocations(remittance, expected_pairs):
    """The allocations array pairs claim ids with granted cents, in order."""
    actual = [
        (allocation["claim_id"], allocation["allocated_cents"])
        for allocation in remittance["allocations"]
    ]
    assert actual == list(expected_pairs), f"expected allocations {expected_pairs}, got {actual}"


def assert_claim_amounts(claim, **expected):
    """Spot-check any subset of a claim's money fields."""
    for field, value in expected.items():
        assert claim[field] == value, f"expected {field} {value}, got {claim[field]}"


def assert_assignment_cost(
    assignment, billable_hours, pre_fee_subtotal_cents, network_admin_fee_cents, total_cost_cents
):
    """The coverage cost breakdown matches the pinned costing order."""
    assert assignment["billable_hours"] == billable_hours, (
        f"expected billable_hours {billable_hours}, got {assignment['billable_hours']}"
    )
    assert assignment["pre_fee_subtotal_cents"] == pre_fee_subtotal_cents, (
        f"expected pre_fee_subtotal_cents {pre_fee_subtotal_cents}, "
        f"got {assignment['pre_fee_subtotal_cents']}"
    )
    assert assignment["network_admin_fee_cents"] == network_admin_fee_cents, (
        f"expected network_admin_fee_cents {network_admin_fee_cents}, "
        f"got {assignment['network_admin_fee_cents']}"
    )
    assert assignment["total_cost_cents"] == total_cost_cents, (
        f"expected total_cost_cents {total_cost_cents}, got {assignment['total_cost_cents']}"
    )
    assert (
        assignment["pre_fee_subtotal_cents"] + assignment["network_admin_fee_cents"]
        == assignment["total_cost_cents"]
    ), "total cost must be the pre-fee subtotal plus the network admin fee"


def assert_assignment_statuses(assignment, staffing_status, billing_status):
    """The two independent status dimensions of an assignment."""
    assert assignment["staffing_status"] == staffing_status, (
        f"expected staffing_status {staffing_status}, got {assignment['staffing_status']}"
    )
    assert assignment["billing_status"] == billing_status, (
        f"expected billing_status {billing_status}, got {assignment['billing_status']}"
    )


def assert_order_pricing(
    order, total_quantity, discount_pct, subtotal_cents, insurance_admin_fee_cents, total_cents
):
    """The priced totals of a committed group purchase order."""
    assert order["total_quantity"] == total_quantity, (
        f"expected total_quantity {total_quantity}, got {order['total_quantity']}"
    )
    assert float(order["discount_pct"]) == discount_pct, (
        f"expected discount_pct {discount_pct}, got {order['discount_pct']}"
    )
    assert order["subtotal_cents"] == subtotal_cents, (
        f"expected subtotal_cents {subtotal_cents}, got {order['subtotal_cents']}"
    )
    assert order["insurance_admin_fee_cents"] == insurance_admin_fee_cents, (
        f"expected insurance_admin_fee_cents {insurance_admin_fee_cents}, "
        f"got {order['insurance_admin_fee_cents']}"
    )
    assert order["total_cents"] == total_cents, (
        f"expected total_cents {total_cents}, got {order['total_cents']}"
    )


def assert_revenue_components(
    model, subsidy_component_cents, private_component_cents, food_component_cents,
    monthly_revenue_cents,
):
    """The three revenue components and their sum."""
    assert model["subsidy_component_cents"] == subsidy_component_cents, (
        f"expected subsidy_component_cents {subsidy_component_cents}, "
        f"got {model['subsidy_component_cents']}"
    )
    assert model["private_component_cents"] == private_component_cents, (
        f"expected private_component_cents {private_component_cents}, "
        f"got {model['private_component_cents']}"
    )
    assert model["food_component_cents"] == food_component_cents, (
        f"expected food_component_cents {food_component_cents}, "
        f"got {model['food_component_cents']}"
    )
    assert model["monthly_revenue_cents"] == monthly_revenue_cents, (
        f"expected monthly_revenue_cents {monthly_revenue_cents}, "
        f"got {model['monthly_revenue_cents']}"
    )
    assert (
        model["subsidy_component_cents"]
        + model["private_component_cents"]
        + model["food_component_cents"]
        == model["monthly_revenue_cents"]
    ), "monthly revenue must be the sum of the three components"


def assert_margin_band(model, margin_pct, sustainability):
    """The margin and the band it falls into."""
    assert float(model["margin_pct"]) == margin_pct, (
        f"expected margin_pct {margin_pct}, got {model['margin_pct']}"
    )
    assert model["sustainability"] == sustainability, (
        f"expected sustainability {sustainability}, got {model['sustainability']}"
    )


def assert_four_decimal_places(value):
    """A ratio carried to four decimal places."""
    text = f"{value}"
    assert "." in text, f"expected a fractional value, got {text}"
    assert len(text.split(".")[1]) <= 4, f"expected at most four decimals, got {text}"
