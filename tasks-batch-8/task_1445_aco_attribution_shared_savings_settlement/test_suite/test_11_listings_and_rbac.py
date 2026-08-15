"""List-endpoint envelope/pagination behavior and coarse role authorization."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    create_agreement_period_payload,
    create_claim_payload,
    create_period,
    ingest_claim,
    open_period,
    validate_error,
    validate_paginated,
)


class TestListPaginationDefaults:
    def test_list_endpoints_paginate_with_defaults(self, api, claims_headers):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0. Every list response carries `limit`,
        `offset`, `total_count`, and `has_more` inside `meta`. Unless a list
        states otherwise, results are sorted by `created_at` ascending."

        Design: Corner/endpoints/list_endpoints_paginate_with_defaults
        """
        period = create_period(tax_id="ACO-N1")
        beneficiary = add_beneficiary("MBI-N1", 1980)
        open_period(period["id"])
        for i, amount in enumerate((100, 200, 300)):
            api.create_claim(
                create_claim_payload(period["id"], beneficiary["id"],
                                     service_date=f"2026-02-0{i + 1}",
                                     allowed_amount_cents=amount,
                                     claim_type="PART_A"),
                claims_headers,
            )
        res = api.list_claims(claims_headers,
                              params={"agreement_period_id": period["id"]})
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        created = [item["created_at"] for item in data]
        assert created == sorted(created), "default sort is created_at ascending"


class TestCoarseRbac:
    def test_claims_processor_cannot_create_period(self, api, claims_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list — or whose user attempts to act outside their permitted ownership
        scope — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`AcoAdministrator` — ACO operations administrator: agreement
        periods, participants, beneficiaries, data-sharing elections, alignment
        runs, and benchmarks."

        Design: Corner/rbac/claims_processor_cannot_create_period
        """
        res = api.create_agreement_period(
            create_agreement_period_payload(aco_tax_id="ACO-R1", aco_name="R1"),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
