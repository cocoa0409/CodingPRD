"""Reading the policy and its tower back.

Acceptance carries no body, so every field on the policy it creates is either
system-minted or copied from the submission and the quote. The tower is then read
back through a filtered list, where the filter and the pagination envelope have to
compose.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADJUSTER,
    ApiErrorId,
    COMPLIANCE,
    UNDERWRITER,
    assert_coverage_part,
    assert_coverage_part_creation_order,
    assert_instant_equals,
    assert_layer,
    assert_money,
    assert_policy,
    find_part,
    make_risk_manager_headers,
    read_layer,
    register_insured,
    resolve_term_as_insured,
    setup_bound_policy,
    setup_offered_quote,
    subscribe_layer,
)


def test_binding_mints_the_policy_number_and_copies_the_agreed_terms(api):
    """PRD 3.4: the policy carries "a human-readable `policy_number` of the form
    `DO-NNNNNN`, where the six digits are a zero-padded monotonic counter that starts
    at `000001` and advances by one on each bind. The policy copies `submission_id`,
    `insured_id` and `quote_id` for addressability ... and copies `period_start`,
    `period_end`, `retroactive_date` and `erp_days` from the submission,
    `shared_aggregate_limit_usd` from the quote's `offered_limit_usd`,
    `retention_usd` from the quote's `offered_retention_usd`, and
    `program_target_limit_usd` from the submission's
    `requested_program_target_limit_usd`." PRD 3.4: "`premium_due_date` is set to the
    binding instant plus 30 days." PRD 3.4: "the accepted quote creates the policy
    with `coverage_status` `INCEPTED` and `premium_status` `INVOICED`".

    Design: Corner/entities/policy_bind_assigns_system_fields_from_quote
    """
    scenario = setup_offered_quote()
    insured_id = scenario["insured"]["id"]
    quote = scenario["quote"]
    resolve_term_as_insured(scenario["conduct_term"]["id"], insured_id, "AGREE")

    data = validate_success(
        api.accept_quote(quote["id"], make_risk_manager_headers(insured_id)), 201
    )

    assert_policy(data)
    assert data["policy_number"] == "DO-000001", "the first bind of the counter"
    assert data["submission_id"] == scenario["submission"]["id"]
    assert data["insured_id"] == insured_id
    assert data["quote_id"] == quote["id"]

    assert_instant_equals(data["period_start"], "2026-09-01T00:00:00Z", "period_start")
    assert_instant_equals(data["period_end"], "2027-09-01T00:00:00Z", "period_end")
    assert_instant_equals(data["retroactive_date"], "2024-01-01T00:00:00Z",
                          "retroactive_date")
    assert data["erp_days"] == 90

    assert_money(data["shared_aggregate_limit_usd"], 10_000_000,
                 "shared_aggregate_limit_usd")
    assert_money(data["retention_usd"], 250_000, "retention_usd")
    assert_money(data["program_target_limit_usd"], 20_000_000,
                 "program_target_limit_usd")
    assert_money(data["aggregate_remaining_usd"], 10_000_000, "aggregate_remaining_usd")
    assert_money(data["total_eroded_usd"], 0, "total_eroded_usd")

    # The only AGREED term is the automatic CONDUCT term at premium_impact_pct 0.00,
    # so the quoted gross passes through untouched.
    assert_money(data["gross_premium_usd"], 236_468.57, "gross_premium_usd")
    assert_money(data["gross_premium_usd"], quote["gross_premium_usd"],
                 "the quoted gross premium")
    assert_instant_equals(data["premium_due_date"], "2026-08-31T00:00:00Z",
                          "premium_due_date")

    assert data["coverage_status"] == "INCEPTED"
    assert data["premium_status"] == "INVOICED"
    assert data["tower_sealed"] is False
    assert data["tower_posture"] == "INCOMPLETE", "a fresh policy carries no layer"
    assert_money(data["placed_limit_usd"], 0, "placed_limit_usd")
    assert data["open_claim_count"] == 0
    assert data["version"] == 1

    parts, meta = validate_paginated(
        api.list_coverage_parts(data["id"], UNDERWRITER,
                                params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 3
    assert_coverage_part_creation_order(parts)
    for part in parts:
        assert_coverage_part(part)
        assert part["status"] == "ACTIVE"
        assert_money(part["eroded_usd"], 0, f"{part['part']} eroded_usd")
        assert_money(part["remaining_limit_usd"], part["limit_usd"],
                     f"{part['part']} remaining_limit_usd")
    assert_money(find_part(parts, "SIDE_A")["limit_usd"], 10_000_000, "SIDE_A limit")
    assert_money(find_part(parts, "SIDE_A")["retention_usd"], 0, "SIDE_A retention")
    assert_money(find_part(parts, "SIDE_B")["limit_usd"], 10_000_000, "SIDE_B limit")
    assert_money(find_part(parts, "SIDE_B")["retention_usd"], 250_000, "SIDE_B retention")
    assert_money(find_part(parts, "SIDE_C")["limit_usd"], 5_000_000, "SIDE_C limit")
    assert_money(find_part(parts, "SIDE_C")["retention_usd"], 250_000, "SIDE_C retention")


def test_an_unknown_identifier_answers_for_the_resource_its_path_names(api):
    """PRD 2.8: "The first identifier that matches no stored record ends the request
    immediately with that resource's own not-found error and HTTP 404 ...
    `ERR_POLICY_NOT_FOUND` for a policy-scoped path ... `ERR_CLAIM_NOT_FOUND` for a
    claim-scoped path". PRD 2.7 ranks "Path resource existence, left to right" third,
    "on every endpoint carrying a path parameter".

    Design: Corner/entities/unknown_policy_id_returns_policy_not_found
    """
    register_insured()

    validate_error(
        api.get_policy(NON_EXISTENT_UUID, UNDERWRITER),
        ApiErrorId.ERR_POLICY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_claim(NON_EXISTENT_UUID, ADJUSTER),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
        404,
    )


def test_the_layer_list_pages_the_filtered_set_rather_than_the_table(api):
    """PRD 2.3: "Layers may be filtered by `policy_id`, `underlying_layer_id` and
    `status`." PRD 2.3: "The response envelope's `meta` object carries `limit`,
    `offset`, `total_count` and `has_more` on every list response", and "every list
    endpoint returns its records sorted by `created_at` in ascending order." PRD 3.5:
    "A new layer is created in `ATTACHED`, and its `is_primary` flag is true exactly
    when its `attachment_point_usd` is 0."

    Design: Corner/entities/layer_listing_filters_by_policy_with_pagination
    """
    scenario = setup_bound_policy()
    policy_id = scenario["policy"]["id"]
    primary = subscribe_layer(
        policy_id, carrier_name="Meridian Primary", attachment_point_usd=0,
        limit_usd=10_000_000, participation_pct=1.00, form_type="FOLLOWING_FORM",
    )
    excess = subscribe_layer(
        policy_id, carrier_name="Northgate Excess", attachment_point_usd=10_000_000,
        limit_usd=10_000_000, participation_pct=1.00, form_type="FOLLOWING_FORM",
        underlying_layer_id=primary["id"],
    )

    # A second placement, so the filtered count cannot be the table's count.
    other = setup_bound_policy()
    other_layer = subscribe_layer(
        other["policy"]["id"], carrier_name="Calder Primary", attachment_point_usd=0,
        limit_usd=10_000_000, participation_pct=1.00,
    )

    first_page, first_meta = validate_paginated(
        api.list_layers(COMPLIANCE,
                        params={"policy_id": policy_id, "limit": 1, "offset": 0})
    )
    assert first_meta["total_count"] == 2
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert len(first_page) == 1
    assert first_page[0]["policy_id"] == policy_id

    second_page, second_meta = validate_paginated(
        api.list_layers(COMPLIANCE,
                        params={"policy_id": policy_id, "limit": 1, "offset": 1})
    )
    assert second_meta["total_count"] == 2
    assert second_meta["offset"] == 1
    assert second_meta["has_more"] is False
    assert len(second_page) == 1
    assert [layer["id"] for layer in first_page + second_page] == [
        primary["id"], excess["id"]
    ], "the two pages together carry both bands once, in created_at order"

    _, exhausted_meta = validate_paginated(
        api.list_layers(COMPLIANCE, params={"policy_id": policy_id,
                                            "status": "EXHAUSTED",
                                            "limit": 10, "offset": 0})
    )
    assert exhausted_meta["total_count"] == 0, (
        "both bands are ATTACHED, so the status filter narrows rather than being ignored"
    )

    _, other_meta = validate_paginated(
        api.list_layers(COMPLIANCE, params={"policy_id": other["policy"]["id"],
                                            "limit": 10, "offset": 0})
    )
    assert other_meta["total_count"] == 1, "the filter counts one policy's bands only"
    assert other_layer["policy_id"] == other["policy"]["id"]

    read_primary = read_layer(primary["id"])
    assert_layer(read_primary)
    assert read_primary["is_primary"] is True
    assert read_primary["underlying_layer_id"] is None
    assert read_primary["status"] == "ATTACHED"
    read_excess = read_layer(excess["id"])
    assert read_excess["is_primary"] is False
    assert read_excess["underlying_layer_id"] == primary["id"]
    assert read_excess["attachment_point_usd"] == pytest.approx(10_000_000, abs=0.01)
