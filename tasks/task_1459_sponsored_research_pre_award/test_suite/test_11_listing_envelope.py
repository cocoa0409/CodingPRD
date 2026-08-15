"""Listing, pagination, filtering, and the response envelope (PRD §2.2, §2.3, §3.3)."""
from test_helpers import (
    add_budget_line,
    assert_proposal,
    create_budget_line_payload,
    get_success_data,
    make_context,
    make_opportunity,
    make_pi,
    make_pi_headers,
    make_proposal,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestProposalListing:
    def _setup(self, api):
        """PI-A with 3 proposals, PI-B with 1, on one opportunity."""
        opp = make_opportunity()
        pi_a = make_pi(full_name="PA")
        pi_b = make_pi(full_name="PB", department_code="CHEM")
        for title in ("A1", "A2", "A3"):
            make_proposal(opp["id"], pi_a["id"], title=title, pi_effort_pct=10.00)
        make_proposal(opp["id"], pi_b["id"], title="B1", pi_effort_pct=10.00)
        return opp, pi_a, pi_b

    def test_pagination_pages(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults to
        0. ... Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_proposals_pagination_and_filter
        """
        _opp, pi_a, _pi_b = self._setup(api)
        page1, meta1 = validate_paginated(
            api.list_proposals(DIRECTOR, params={"pi_id": pi_a["id"], "limit": 2,
                                                 "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_proposals(DIRECTOR, params={"pi_id": pi_a["id"], "limit": 2,
                                                 "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        page1_ids = {row["id"] for row in page1}
        assert page2[0]["id"] not in page1_ids

    def test_filter_by_pi_and_status(self, api):
        """PRD §3.3: "The proposal listing supports filters on `opportunity_id`,
        `pi_id`, `status`, `current_snapshot_id`, and
        `pinned_budget_snapshot_id`, alongside the standard `limit` and
        `offset`."

        Design: Corner/endpoints/list_proposals_pagination_and_filter
        """
        _opp, _pi_a, pi_b = self._setup(api)
        rows, meta = validate_paginated(
            api.list_proposals(DIRECTOR, params={"pi_id": pi_b["id"],
                                                 "status": "DRAFT"})
        )
        assert len(rows) == 1
        for row in rows:
            assert row["pi_id"] == pi_b["id"]
            assert_proposal(row)


class TestBudgetLineListing:
    def test_fk_filter_isolation(self, api):
        """PRD §3.3: "Budget lines can be listed per proposal, or across the
        system filtered by `proposal_id`, `subrecipient_commitment_id`, or
        `category`."

        Design: Corner/endpoints/budget_lines_filtered_list_isolation
        """
        ctx = make_context()
        p1 = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="P1",
                           pi_effort_pct=10.00)
        p2 = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="P2",
                           pi_effort_pct=10.00)
        add_budget_line(p1["id"], description="a", amount_cents=100)
        add_budget_line(p1["id"], category="TRAVEL", description="b",
                        amount_cents=200)
        add_budget_line(p2["id"], description="c", amount_cents=300)
        filtered, _meta = validate_paginated(
            api.list_budget_lines(DIRECTOR, params={"proposal_id": p1["id"]})
        )
        assert len(filtered) == 2
        assert all(row["proposal_id"] == p1["id"] for row in filtered)
        sub = get_success_data(api.list_proposal_budget_lines(p2["id"], DIRECTOR))
        assert len(sub) == 1
        assert sub[0]["proposal_id"] == p2["id"]


class TestResponseEnvelope:
    def test_object_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."

        Design: Corner/endpoints/response_envelope_shape
        """
        pi = make_pi()
        resp = api.get_principal_investigator(pi["id"], DIRECTOR)
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["id"] == pi["id"]

    def test_list_envelope_pagination_defaults(self, api, admin_headers):
        """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints." PRD §2.3:
        "The `limit` parameter ... defaults to 10 ... The `offset` parameter
        sets the number of items skipped and defaults to 0."

        Design: Corner/endpoints/response_envelope_shape
        """
        resp = api.list_proposals(DIRECTOR)
        body = resp.json()
        assert body["response_type"] == "array"
        meta = body["meta"]
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing pagination field {field}"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
