"""Renewal analysis & contract renewal, list pagination, read-back consistency."""
from test_helpers import (
    ApiErrorId, canonical_two_member_journey, close_year, contract_version,
    create_renewal_analysis_payload, expire_contract, finalize_settlement,
    get_contract, get_settlement, make_claim, make_contract,
    make_renewal_analysis, make_year, mark_year_settled, pay_all_remittances,
    remittance_for_practice, setup_org, single_member_journey, validate_error,
    validate_paginated, validate_success,
)


def _walk_year_to_closed(pipe):
    """Pay all remittances (bubbling the settlement to DISTRIBUTED), then mark
    the year settled, close it, and expire the contract (PRD §3.4, §3.12)."""
    pay_all_remittances(pipe["remittances"])
    settlement_id = pipe["settlement"]["id"]
    year_id = pipe["year"]["id"]
    assert get_settlement(settlement_id)["settlement_status"] == "DISTRIBUTED"
    mark_year_settled(year_id)
    close_year(year_id)
    return expire_contract(pipe["contract"]["id"])


def test_renewal_renegotiate_boundary_and_successor_contract(api, contract_manager_headers):
    """PRD §3.13: "The `realized_savings_rate_bp` is computed across all closed years: the sum of `benchmark_cost_cents` minus the sum of `actual_cost_cents`, multiplied by 10000, divided by the sum of `benchmark_cost_cents`, and truncated toward zero."
    PRD §3.13: "The `recommendation` is then derived: if the realized savings rate is at least 100 basis points **and** the quality trend has not dropped by more than 5 points (that is, `quality_trend_points` is greater than or equal to -5), the recommendation is `RENEW_AS_IS`. Otherwise, if the realized savings rate is at least zero, the recommendation is `RENEW_RENEGOTIATE`. Otherwise the recommendation is `DO_NOT_RENEW`. Both comparisons are pinned as greater-than-or-equal."
    PRD §3.13: "Renewal creates a successor contract in `DRAFT` that copies all terms of the expiring contract, sets its `contract_ref` to the original `contract_ref` with the suffix `-R` appended, and sets `renewed_from_contract_id` to the id of the contract being renewed. The response body is the newly created successor, not the renewed original, and the create returns 201."

    Design: Corner/calculations/renewal_renegotiate_boundary_and_successor_contract
    """
    pipe = canonical_two_member_journey(
        stage="AUTHORIZED",
        claim_amounts=[("2026-03-10", 1082100, 0), ("2026-09-05", 700000, 1)],
    )
    settlement = pipe["settlement"]
    # gross 17,900 -> rate 99 < MSR -> shared 0; pool 89,105 x 5000 bp -> 44,553.
    assert settlement["net_payable_cents"] == 44553
    rem1 = remittance_for_practice(pipe["practices"][0]["id"])
    rem2 = remittance_for_practice(pipe["practices"][1]["id"])
    assert rem1["amount_cents"] == 29702
    assert rem2["amount_cents"] == 14851

    contract = _walk_year_to_closed(pipe)
    assert contract["contract_status"] == "EXPIRED"

    analysis = make_renewal_analysis(contract["id"])
    completed = validate_success(
        api.complete_renewal_analysis(analysis["id"], contract_manager_headers)
    )
    assert completed["analysis_status"] == "COMPLETE"
    # trunc((1,800,000 - 1,782,100) * 10000 / 1,800,000) = 99: below the 100 bp
    # renewal bar but non-negative -> RENEW_RENEGOTIATE.
    assert completed["realized_savings_rate_bp"] == 99
    assert completed["recommendation"] == "RENEW_RENEGOTIATE"

    renewed = api.renew_contract(contract["id"], contract_manager_headers)
    successor = validate_success(renewed, 201)
    assert successor["contract_status"] == "DRAFT"
    assert successor["contract_ref"] == "C-1-R"
    assert successor["renewed_from_contract_id"] == contract["id"]
    assert successor["id"] != contract["id"], "the response body is the successor"
    assert get_contract(contract["id"])["contract_status"] == "RENEWED"


def test_renewal_do_not_renew_blocks_renew(api, contract_manager_headers):
    """PRD §3.13: "The `recommendation` is then derived: if the realized savings rate is at least 100 basis points **and** the quality trend has not dropped by more than 5 points (that is, `quality_trend_points` is greater than or equal to -5), the recommendation is `RENEW_AS_IS`. Otherwise, if the realized savings rate is at least zero, the recommendation is `RENEW_RENEGOTIATE`. Otherwise the recommendation is `DO_NOT_RENEW`. Both comparisons are pinned as greater-than-or-equal."
    PRD §3.13: "A `ContractManager` renews an expired contract (`EXPIRED → RENEWED`) only when a `COMPLETE` analysis exists for that contract whose `recommendation` is not `DO_NOT_RENEW` (`ERR_RENEWAL_NOT_RECOMMENDED` otherwise)."

    Design: Corner/calculations/renewal_do_not_renew_blocks_renew
    """
    pipe = canonical_two_member_journey(
        stage="AUTHORIZED",
        claim_amounts=[("2026-03-10", 1850000, 0)],
    )
    # Loss year: net 26,250 = withhold release 46,250 minus shared losses 20,000.
    assert pipe["settlement"]["net_payable_cents"] == 26250
    contract = _walk_year_to_closed(pipe)
    assert contract["contract_status"] == "EXPIRED"

    analysis = make_renewal_analysis(contract["id"])
    completed = validate_success(
        api.complete_renewal_analysis(analysis["id"], contract_manager_headers)
    )
    # trunc(-50,000 x 10000 / 1,800,000) = -277 < 0 -> DO_NOT_RENEW.
    assert completed["realized_savings_rate_bp"] == -277
    assert completed["recommendation"] == "DO_NOT_RENEW"

    blocked = api.renew_contract(contract["id"], contract_manager_headers)
    validate_error(blocked, ApiErrorId.ERR_RENEWAL_NOT_RECOMMENDED)
    assert get_contract(contract["id"])["contract_status"] == "EXPIRED"


def test_occ_renewal_analysis_stale_version_rejected(api, contract_manager_headers):
    """PRD §2.7: "If the parent's current `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Creating a renewal analysis against a `Contract` requires `expected_contract_version` matching that contract's current `version`. The guarded endpoint is the renewal-analysis create nested under the contract."
    PRD §3.13: "The new analysis's `analysis_status` is created as `DRAFT`, with `analysis_seq` assigned one higher than the previous analysis of the contract (starting at 1); creating a new analysis supersedes any prior `DRAFT` analysis of the same contract (`DRAFT → SUPERSEDED`)."

    Design: Corner/complexity_layers/occ_renewal_analysis_stale_version_rejected
    """
    pipe = canonical_two_member_journey(stage="AUTHORIZED")
    contract = _walk_year_to_closed(pipe)
    contract_id = contract["id"]

    observed = contract_version(contract_id)
    first = api.create_renewal_analysis(
        contract_id, create_renewal_analysis_payload(observed), contract_manager_headers
    )
    analysis1 = validate_success(first, 201)
    assert analysis1["analysis_seq"] == 1
    assert analysis1["analysis_status"] == "DRAFT"

    stale = api.create_renewal_analysis(
        contract_id, create_renewal_analysis_payload(observed), contract_manager_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = contract_version(contract_id)
    second = api.create_renewal_analysis(
        contract_id, create_renewal_analysis_payload(fresh), contract_manager_headers
    )
    analysis2 = validate_success(second, 201)
    assert analysis2["analysis_seq"] == 2

    reread = validate_success(
        api.get_renewal_analysis(analysis1["id"], contract_manager_headers)
    )
    assert reread["analysis_status"] == "SUPERSEDED"


def test_immediate_consistency_readback_after_finalize(api, auditor_headers):
    """PRD §3.10: "Finalization recomputes every computed field from current data using the **final** variant — actuals only, with no completion factor or annualization applied — and stamps `finalized_on` with the logical clock date and `finalized_by_user_id` with the calling officer's `X-User-ID`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_readback_after_finalize
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    settlement_id = pipe["settlement"]["id"]

    finalized = finalize_settlement(settlement_id, officer_user_id="so-1")
    assert finalized["settlement_status"] == "FINALIZED"
    assert finalized["finalized_on"] == "2027-06-01"
    assert finalized["finalized_by_user_id"] == "so-1"
    assert finalized["net_payable_cents"] == 74200

    reread = validate_success(api.get_settlement(settlement_id, auditor_headers))
    assert reread["settlement_status"] == finalized["settlement_status"]
    assert reread["finalized_on"] == finalized["finalized_on"]
    assert reread["finalized_by_user_id"] == finalized["finalized_by_user_id"]
    assert reread["net_payable_cents"] == finalized["net_payable_cents"]


def test_pagination_defaults_on_claims_list(api, claims_processor_headers):
    """PRD §2.3: "List endpoints accept two optional query parameters. `limit` caps the number of items returned; it defaults to 10, has a minimum of 1, and has a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_defaults_on_claims_list
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])
    for i in range(12):
        month = i + 1
        make_claim(
            year["id"], org["members"][0]["id"], f"CL-{i + 1:02d}",
            f"2026-{month:02d}-10", 1000,
        )

    page1, meta1 = validate_paginated(api.list_claims(claims_processor_headers))
    assert len(page1) == 10, "default limit is 10"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_claims(claims_processor_headers, params={"limit": 10, "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_performance_year_list_pagination_and_envelope(api, payer_admin_headers):
    """PRD §2.3: "List endpoints accept two optional query parameters. `limit` caps the number of items returned; it defaults to 10, has a minimum of 1, and has a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/performance_year_list_filter_and_pagination
    """
    org = setup_org(member_specs=[], practice_count=0)
    c1 = make_contract(
        org["program"]["id"], org["group"]["id"], contract_ref="C-1",
        effective_end="2028-01-01",
    )
    make_year(c1["id"], year_label=2026)
    make_year(c1["id"], year_label=2027, period_start="2027-01-01", period_end="2028-01-01")
    c2 = make_contract(org["program"]["id"], org["group"]["id"], contract_ref="C-2")
    make_year(c2["id"], year_label=2026)

    resp = api.list_performance_years(payer_admin_headers, params={"limit": 1, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_performance_years(payer_admin_headers, params={"limit": 1, "offset": 2})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

