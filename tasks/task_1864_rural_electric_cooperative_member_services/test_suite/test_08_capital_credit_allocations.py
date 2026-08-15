"""Capital-credit allocations: method divergence, pool match, posting,
conservation invariants (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_allocation_payload,
    get_success_data,
    setup_cooperative,
    setup_finalized_invoice,
    setup_member,
    setup_published_schedule,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
DIRECTOR = TEST_USERS["board_director"]


def _three_member_weighted_scenario(api, pool=100001):
    """Cooperative with pool `pool` for FY2025 and three ACTIVE members whose
    finalized December 2025 usage is 100 / 300 / 600 kWh respectively."""
    coop = setup_cooperative()
    get_success_data(api.post_margin(
        coop["id"], {"fiscal_year": 2025, "margin_cents": pool}, REP), 200)
    setup_published_schedule(rate_class="RESIDENTIAL")
    members = []
    for i, (name, kwh) in enumerate((("A", 100), ("B", 300), ("C", 600)), start=1):
        member, location = setup_member(
            status="ACTIVE", address=f"{i} Rd",
            member_overrides={"legal_name": name, "district_id": i})
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, kwh)
        members.append(member)
    return coop, members


def _lines_by_member(api, allocation_id):
    lines = validate_success(api.list_allocation_lines(allocation_id, REP), 200)
    return {line["member_id"]: line for line in lines}


class TestMethodDivergence:
    def test_patronage_weighted_shares(self, api):
        """PRD §3.7: "Under `PATRONAGE_WEIGHTED`, each member's raw share is the
        pool multiplied by the member's effective weight and divided by the
        total effective weight summed over members who were `ACTIVE` at any
        point during the fiscal year; each raw share is floored to whole cents,
        and the leftover cents are dealt out one at a time to members in
        descending order of their raw share's fractional part — ties broken by
        the earliest member `created_at` — until the remainder is exhausted."

        Design: Difficulty/dual_variant_calc/allocation_weighted_vs_flat_divergence
        """
        coop, (m_a, m_b, m_c) = _three_member_weighted_scenario(api, pool=100001)
        alloc = validate_success(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025,
                method="PATRONAGE_WEIGHTED"),
            REP), expected_status=201)
        lines = _lines_by_member(api, alloc["id"])
        # raw shares: 10000.1 / 30000.3 / 60000.6 -> floored 10000/30000/60000,
        # remainder 2 dealt by fractional part DESC to C (0.6) then B (0.3).
        assert lines[m_a["id"]]["allocated_cents"] == 10000
        assert lines[m_b["id"]]["allocated_cents"] == 30000
        assert lines[m_c["id"]]["allocated_cents"] == 60001

    def test_flat_per_member_shares_diverge_from_weighted(self, api):
        """PRD §3.7: "Under `FLAT_PER_MEMBER`, every eligible member receives
        the floored equal division of the pool, with remainder cents again
        distributed one at a time in ascending member `created_at` order."

        Design: Difficulty/dual_variant_calc/allocation_weighted_vs_flat_divergence
        """
        coop, (m_a, m_b, m_c) = _three_member_weighted_scenario(api, pool=100001)
        alloc = validate_success(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), expected_status=201)
        lines = _lines_by_member(api, alloc["id"])
        # floor(100001 / 3) = 33333 each; remainder 2 dealt by created_at ASC to
        # A then B.
        assert lines[m_a["id"]]["allocated_cents"] == 33334
        assert lines[m_b["id"]]["allocated_cents"] == 33334
        assert lines[m_c["id"]]["allocated_cents"] == 33333
        # The two methods disagree with the weighted split on every member.
        weighted = {m_a["id"]: 10000, m_b["id"]: 30000, m_c["id"]: 60001}
        for mid, cents in weighted.items():
            assert lines[mid]["allocated_cents"] != cents


class TestAllocationLinesRead:
    def test_allocation_lines_subresource_list(self, api):
        """PRD §3.7: "Each line ties an `allocation_id` to a `member_id` and
        records this member's `allocated_cents` share for the year along with
        the `weight_kwh_effective` that produced it — the member's
        `patronage_base_kwh` plus one-half of their
        `patronage_base_irrigation_kwh`."

        Design: Corner/endpoints/allocation_lines_subresource_list
        """
        coop = setup_cooperative()
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        setup_published_schedule(rate_class="RESIDENTIAL")
        member, location = setup_member(status="ACTIVE")
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, 100)
        alloc = validate_success(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025,
                method="PATRONAGE_WEIGHTED"),
            REP), expected_status=201)
        lines = validate_success(api.list_allocation_lines(alloc["id"], REP), 200)
        assert len(lines) == 1
        line = lines[0]
        assert line["member_id"] == member["id"]
        assert line["allocated_cents"] == 10000
        assert line["weight_kwh_effective"] == 100.0


class TestPoolMatch:
    def test_allocation_pool_mismatch_rejected(self, api):
        """PRD §3.7: "the run's `total_allocated_cents` must exactly equal the
        cooperative's current `capital_credits_pool_cents`, else
        `ERR_ALLOCATION_POOL_MISMATCH`."

        Design: Corner/errors/allocation_pool_mismatch_rejected
        """
        coop = setup_cooperative()
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        # No eligible members, so the draft total is 0; topping the pool up to
        # 20000 before approval leaves total_allocated != pool.
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        resp = api.approve_allocation(alloc["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_POOL_MISMATCH)

    def test_state_error_beats_pool_mismatch_on_approve(self, api):
        """PRD §2.8: "Fifth, state validity: the target resource must be in a
        legitimate from-state for the requested transition, else
        `ERR_INVALID_STATE`." and "Ninth and last, fiscal arithmetic:
        allocation-pool match, retirement-budget sufficiency, and
        cooperative-version freshness."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_allocation_approve
        """
        coop = setup_cooperative()
        setup_published_schedule(rate_class="RESIDENTIAL")
        member, location = setup_member(status="ACTIVE")
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, 100)
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 100001}, REP), 200)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        approved = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        assert approved["status"] == "APPROVED"
        # Move the pool out from under the approved total, then re-approve:
        # the state check (priority 5) surfaces before the fiscal check (9).
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 1}, REP), 200)
        resp = api.approve_allocation(alloc["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pool_mismatch_alone_surfaces_fiscal_error(self, api):
        """PRD §2.8: "Fifth, state validity: the target resource must be in a
        legitimate from-state for the requested transition, else
        `ERR_INVALID_STATE`." and "Ninth and last, fiscal arithmetic:
        allocation-pool match, retirement-budget sufficiency, and
        cooperative-version freshness." With the allocation still in DRAFT the
        state check passes, so the fiscal check (priority 9) is the one that
        surfaces.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_allocation_approve
        """
        coop = setup_cooperative()
        setup_published_schedule(rate_class="RESIDENTIAL")
        member, location = setup_member(status="ACTIVE")
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, 100)
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 100001}, REP), 200)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        # DRAFT allocation, but the pool moved after creation: with the state
        # check satisfied, the fiscal mismatch is surfaced.
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 1}, REP), 200)
        resp = api.approve_allocation(alloc["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_POOL_MISMATCH)


class TestPosting:
    def test_post_conserves_pool_plus_balances(self, api):
        """PRD §3.7: "Posting credits every line's `allocated_cents` to its
        member's `capital_credit_balance_cents`, debits the pool to zero for
        that fiscal year, increments the `version` of every affected member, and
        increments the cooperative's `version`."

        Design: Difficulty/compensating_invariant/allocation_post_conserves_pool_plus_balances
        """
        coop, (m_a, m_b, m_c) = _three_member_weighted_scenario(api, pool=100001)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025,
                method="PATRONAGE_WEIGHTED"),
            REP), 201)
        alloc = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        before = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        assert before["capital_credits_pool_cents"] == 100001
        posted = validate_success(api.post_allocation(
            alloc["id"], {"expected_cooperative_version": before["version"]}, REP), 200)
        assert posted["status"] == "POSTED"
        after = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        assert after["capital_credits_pool_cents"] == 0
        bal_a = get_success_data(api.get_member(m_a["id"], REP), 200)["capital_credit_balance_cents"]
        bal_b = get_success_data(api.get_member(m_b["id"], REP), 200)["capital_credit_balance_cents"]
        bal_c = get_success_data(api.get_member(m_c["id"], REP), 200)["capital_credit_balance_cents"]
        assert (bal_a, bal_b, bal_c) == (10000, 30000, 60001)
        # Conservation: pool + balances unchanged across the post.
        assert after["capital_credits_pool_cents"] + bal_a + bal_b + bal_c == 100001

    def test_post_zeroes_pool_and_increments_versions(self, api):
        """PRD §3.7: "Posting credits every line's `allocated_cents` to its
        member's `capital_credit_balance_cents`, debits the pool to zero for
        that fiscal year, increments the `version` of every affected member, and
        increments the cooperative's `version`."

        Design: Difficulty/compensating_invariant/allocation_post_conserves_pool_plus_balances
        """
        coop, (m_a, m_b, m_c) = _three_member_weighted_scenario(api, pool=100001)
        member_versions_before = {
            m["id"]: get_success_data(api.get_member(m["id"], REP), 200)["version"]
            for m in (m_a, m_b, m_c)}
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025,
                method="PATRONAGE_WEIGHTED"),
            REP), 201)
        alloc = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        before = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        pool_before = before["capital_credits_pool_cents"]
        posted = validate_success(api.post_allocation(
            alloc["id"], {"expected_cooperative_version": before["version"]}, REP), 200)
        assert posted["status"] == "POSTED"
        after = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        assert after["capital_credits_pool_cents"] == 0
        assert after["version"] == before["version"] + 1
        increments = 0
        for m in (m_a, m_b, m_c):
            now = get_success_data(api.get_member(m["id"], REP), 200)
            assert now["version"] == member_versions_before[m["id"]] + 1
            increments += now["capital_credit_balance_cents"]
        # Pool debit equals the sum of member balance increments.
        assert pool_before == increments

    def test_post_allocation_immediate_consistency(self, api):
        """PRD §3.7: "Posting credits every line's `allocated_cents` to its
        member's `capital_credit_balance_cents`, debits the pool to zero for
        that fiscal year" — the effect is visible on the very next read, with no
        reconciliation lag.

        Design: Corner/consistency_model/immediate_consistency_on_post_allocation
        """
        coop = setup_cooperative()
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, REP), 200)
        setup_published_schedule(rate_class="RESIDENTIAL")
        member, location = setup_member(status="ACTIVE")
        setup_finalized_invoice(
            location["id"], "2025-12-01T00:00:00Z", "2025-12-31T00:00:00Z", 0, 100)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            REP), 201)
        alloc = get_success_data(api.approve_allocation(alloc["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        posted = validate_success(api.post_allocation(
            alloc["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)
        assert posted["status"] == "POSTED"
        member_after = get_success_data(api.get_member(member["id"], REP), 200)
        assert member_after["capital_credit_balance_cents"] == 10000


class TestSegregationOfDuties:
    def test_sod_allocation_approve_by_proposer_rejected(self, api):
        """PRD §3.7: "the `BoardDirector` approving must not be the same
        `X-User-ID` as the `MemberServicesRep` who created the draft — a
        violation is `ERR_SOD_VIOLATION`".

        Design: Corner/validations/sod_allocation_approve_by_proposer_rejected
        """
        from test_helpers import make_director_headers, make_rep_headers
        coop = setup_cooperative()
        rep_headers = make_rep_headers("rep-1")
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 10000}, rep_headers), 200)
        alloc = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025, method="FLAT_PER_MEMBER"),
            rep_headers), 201)
        # Approver presents the same X-User-ID as the proposer.
        resp = api.approve_allocation(alloc["id"], make_director_headers("rep-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
