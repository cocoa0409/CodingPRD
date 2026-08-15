"""Budget amendments: net-zero drafting, approval floors, segregation of
duties, optimistic concurrency, and the apply/void money-conservation
invariant (PRD §2.7, §2.9, §3.8)."""

from test_helpers import (
    ALLOC_AMOUNTS_VERIFIED,
    PD_MINIMUM_VERIFIED,
    ApiErrorId,
    allow_expenditure,
    amendment_line,
    api_client,
    approve_amendment,
    build_user_headers,
    charge_expenditure,
    create_amendment_payload,
    draft_amendment,
    get_allocation_for,
    get_grant,
    list_allocations_for,
    list_set_asides_for,
    make_director_headers,
    reject_amendment,
    setup_allocated,
    setup_certified_allocation,
    setup_equitable_scenario,
    submit_amendment,
    validate_error,
    validate_success,
    void_amendment,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")


class TestAmendmentDrafting:

    def test_amendment_not_net_zero_rejected(self):
        """PRD §3.8: "Because lines are absolute, the draft must conserve
        money: the sum, over all lines, of each `new_amount_cents` minus the
        target's current value must equal exactly zero, or creation is
        rejected with `ERR_AMENDMENT_NOT_NET_ZERO`."

        Design: Corner/errors/amendment_not_net_zero_rejected
        """
        ctx = setup_allocated(2097, [(100, 100)])
        grant = get_grant(ctx["grant"]["id"])
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        # PD reserved is 500,000; a single line raising it to 600,000 sums
        # to +100,000 with no offsetting line.
        resp = api_client.create_amendment(
            create_amendment_payload(
                grant["id"], grant["version"],
                [amendment_line("SET_ASIDE", pd["id"], 600_000)]),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_NET_ZERO)

    def test_occ_stale_amendment_create_returns_412(self):
        """PRD §2.7: "Creating a budget amendment and certifying a poverty
        snapshot both require a non-optional `expected_grant_version` field in
        the request body, carrying the grant's `version` as the client last
        read it. If the value does not match the grant's current `version` —
        because a prior amendment create, approve, or void, a snapshot
        certification, a ranking lock, a finalization, or any other grant-row
        mutation has advanced it since the client's read — the request is
        rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412), and nothing is
        written."
        PRD §3.8: "A created amendment starts in `DRAFT` and advances the
        grant's `version` by one, which itself invalidates any other draft
        pinned to the older baseline."

        Design: Corner/complexity_layers/occ_stale_amendment_create_returns_412
        """
        ctx = setup_allocated(2058, [(60, 100), (40, 100)])
        grant_id = ctx["grant"]["id"]
        a1 = ctx["allocations"][ctx["schools"][0]["id"]]
        a2 = ctx["allocations"][ctx["schools"][1]["id"]]
        observed = get_grant(grant_id)["version"]
        first = validate_success(api_client.create_amendment(
            create_amendment_payload(
                grant_id, observed,
                [amendment_line("SCHOOL_ALLOCATION", a1["id"], 5_300_000),
                 amendment_line("SCHOOL_ALLOCATION", a2["id"], 3_700_000)]),
            ANALYST), expected_status=201)
        assert first["status"] == "DRAFT"
        after_first = get_grant(grant_id)
        assert after_first["version"] == observed + 1, \
            "the successful create advances the grant version by one"
        # The second create replays the stale observed version: the first
        # create's version bump has invalidated the baseline.
        resp = api_client.create_amendment(
            create_amendment_payload(
                grant_id, observed,
                [amendment_line("SCHOOL_ALLOCATION", a1["id"], 5_200_000),
                 amendment_line("SCHOOL_ALLOCATION", a2["id"], 3_800_000)]),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_GRANT_VERSION)
        assert get_grant(grant_id)["version"] == observed + 1, \
            "only the successful create bumped the version"


class TestAmendmentDecisions:

    def test_amendment_rejected_is_terminal_for_approval(self):
        """PRD §3.8: "The amendment moves to the terminal `REJECTED` state
        with `decided_by_user_id` recorded."
        PRD §3.8: "Submission by the analyst or the director moves a `DRAFT`
        amendment to `SUBMITTED` and records `submitted_by_user_id`; from any
        other state the attempt is rejected with
        `ERR_AMENDMENT_INVALID_STATE`."

        Design: Corner/state_machines/amendment_rejected_is_terminal_for_approval
        """
        ctx = setup_allocated(2056, [(60, 100), (40, 100)])
        a1 = ctx["allocations"][ctx["schools"][0]["id"]]
        a2 = ctx["allocations"][ctx["schools"][1]["id"]]
        assert (a1["allocation_amount_cents"],
                a2["allocation_amount_cents"]) == (5_400_000, 3_600_000)
        amendment = draft_amendment(
            ctx["grant"]["id"],
            [amendment_line("SCHOOL_ALLOCATION", a1["id"], 5_300_000),
             amendment_line("SCHOOL_ALLOCATION", a2["id"], 3_700_000)])
        submit_amendment(amendment["id"])
        reject_amendment(amendment["id"],
                         "rationale insufficient for mid-year move")
        # Even a different director cannot approve a terminal REJECTED row.
        resp = api_client.approve_amendment(
            amendment["id"], {}, make_director_headers("director-2"))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_INVALID_STATE)
        a1_after = get_allocation_for(ctx["grant"]["id"],
                                      ctx["schools"][0]["id"])
        a2_after = get_allocation_for(ctx["grant"]["id"],
                                      ctx["schools"][1]["id"])
        assert a1_after["allocation_amount_cents"] == 5_400_000
        assert a2_after["allocation_amount_cents"] == 3_600_000

    def test_amendment_below_liquidated_rejected_at_approval(self):
        """PRD §3.8: "At approval time every line's floor is re-validated
        against current reality, not against the draft-time baseline: a
        set-aside line must leave `reserved_cents` at or above the row's
        `minimum_cents` (else `ERR_SET_ASIDE_BELOW_MINIMUM`), an allocation
        line must leave `allocation_amount_cents` at or above the sum of that
        allocation's `liquidated_cents` and `pending_cents` (else
        `ERR_AMENDMENT_BELOW_LIQUIDATED`), and a set-aside line must likewise
        leave the reserve at or above the set-aside's own `liquidated_cents`
        (also `ERR_AMENDMENT_BELOW_LIQUIDATED`)."

        Design: Corner/errors/amendment_below_liquidated_rejected
        """
        ctx = setup_certified_allocation(2083, [(60, 100), (40, 100)])
        grant_id = ctx["grant"]["id"]
        a1 = ctx["allocations"][ctx["schools"][0]["id"]]
        a2 = ctx["allocations"][ctx["schools"][1]["id"]]
        assert a1["allocation_amount_cents"] == 5_400_000
        # Liquidate 4,000,000 against the first allocation.
        exp = charge_expenditure(ctx["grant"], 4_000_000,
                                 school_allocation_id=a1["id"],
                                 description="salaries")
        allow_expenditure(exp["id"])
        # Net-zero against current values (5,400,000/3,600,000), but the
        # first line would push the allocation below its liquidated floor.
        amendment = draft_amendment(
            grant_id,
            [amendment_line("SCHOOL_ALLOCATION", a1["id"], 3_500_000),
             amendment_line("SCHOOL_ALLOCATION", a2["id"], 5_500_000)])
        submit_amendment(amendment["id"])
        resp = api_client.approve_amendment(amendment["id"], {}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_BELOW_LIQUIDATED)
        after = validate_success(api_client.get_amendment(amendment["id"],
                                                          DIRECTOR))
        assert after["status"] == "SUBMITTED", \
            "a rejected approval leaves the amendment SUBMITTED"
        assert get_allocation_for(grant_id, ctx["schools"][0]["id"])[
            "allocation_amount_cents"] == 5_400_000

    def test_sod_same_director_submit_and_approve_rejected(self):
        """PRD §2.9: "No operator may adjudicate their own submission. The
        segregation rule binds five decision points, and at each the acting
        user's `X-User-ID` must differ from the recorded submitter's: a budget
        amendment's approve, reject, and void decisions are checked against
        the amendment's `submitted_by_user_id`; an SNS document review is
        checked against its `submitted_by_user_id`; an expenditure's
        allowable-cost review is checked against its `submitted_by_user_id`;
        and a monitoring finding's CAP acceptance or return is checked against
        its `cap_submitted_by_user_id`. A violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule has no override and
        no role exception — a `FederalProgramsDirector` who drafted an
        amendment cannot then approve it."

        Design: Corner/rbac/sod_same_director_submit_and_approve_rejected
        """
        ctx = setup_allocated(2059, [(60, 100), (40, 100)])
        grant_id = ctx["grant"]["id"]
        a1 = ctx["allocations"][ctx["schools"][0]["id"]]
        a2 = ctx["allocations"][ctx["schools"][1]["id"]]
        dir9 = make_director_headers("dir-9")
        grant = get_grant(grant_id)
        amendment = validate_success(api_client.create_amendment(
            create_amendment_payload(
                grant_id, grant["version"],
                [amendment_line("SCHOOL_ALLOCATION", a1["id"], 5_300_000),
                 amendment_line("SCHOOL_ALLOCATION", a2["id"], 3_700_000)]),
            dir9), expected_status=201)
        validate_success(api_client.submit_amendment(amendment["id"], dir9))
        same = api_client.approve_amendment(amendment["id"], {}, dir9)
        validate_error(same, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        still = validate_success(api_client.get_amendment(amendment["id"],
                                                          DIRECTOR))
        assert still["status"] == "SUBMITTED"
        approved = validate_success(api_client.approve_amendment(
            amendment["id"], {}, make_director_headers("dir-10")))
        assert approved["status"] == "APPROVED"
        assert get_allocation_for(grant_id, ctx["schools"][0]["id"])[
            "allocation_amount_cents"] == 5_300_000
        assert get_allocation_for(grant_id, ctx["schools"][1]["id"])[
            "allocation_amount_cents"] == 3_700_000


class TestAmendmentMoneyConservation:

    def test_amendment_apply_void_conserves_money(self):
        """PRD §3.8: "A successful approval captures `prior_amounts` — a
        snapshot of each line's `target_id` with its `prior_amount_cents` —
        writes each line's value onto its target (onto
        `allocation_amount_cents` or `reserved_cents` as the `target_type`
        dictates), recomputes the parent-engagement distribution minimum if
        the `PARENT_ENGAGEMENT` set-aside was touched, and advances the
        grant's `version` by one."
        PRD §3.8: "Voiding moves an `APPROVED` amendment to the terminal
        `VOIDED` state; it requires the grant to be `ALLOCATED`, enforces
        segregation of duties against the original submitter, and restores the
        captured `prior_amounts` verbatim onto their targets — the
        compensating action that keeps the money-conservation invariant intact
        across the amendment's whole life."

        Design: Difficulty/compensating_invariant/amendment_apply_void_conserves_money
        """
        ctx = setup_equitable_scenario(fiscal_year=2027,
                                       equitable_count_method="VERIFIED_COUNT")
        grant_id = ctx["grant"]["id"]
        s1 = ctx["schools"][0]
        a1 = ctx["allocations"][s1["id"]]
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        assert a1["allocation_amount_cents"] == ALLOC_AMOUNTS_VERIFIED[0]
        assert pd["reserved_cents"] == PD_MINIMUM_VERIFIED

        def distributed_total():
            allocs = list_allocations_for(grant_id)
            set_asides = list_set_asides_for(grant_id)
            return (sum(a["allocation_amount_cents"] for a in allocs)
                    + sum(s["reserved_cents"] for s in set_asides))

        net = ctx["grant"]["net_allocable_cents"]  # 95,000,000
        assert distributed_total() == net, "pre-amendment invariant"

        # Move 1,000,000 cents from the rank-1 school to the PD set-aside.
        amendment = draft_amendment(
            grant_id,
            [amendment_line("SCHOOL_ALLOCATION", a1["id"],
                            ALLOC_AMOUNTS_VERIFIED[0] - 1_000_000),
             amendment_line("SET_ASIDE", pd["id"], PD_MINIMUM_VERIFIED
                            + 1_000_000)])
        submit_amendment(amendment["id"])
        approve_amendment(amendment["id"])  # director-1 != analyst-1
        a1_mid = get_allocation_for(grant_id, s1["id"])
        pd_mid = validate_success(api_client.get_set_aside(pd["id"], DIRECTOR))
        assert a1_mid["allocation_amount_cents"] == \
            ALLOC_AMOUNTS_VERIFIED[0] - 1_000_000
        assert pd_mid["reserved_cents"] == PD_MINIMUM_VERIFIED + 1_000_000
        assert distributed_total() == net, "invariant holds post-approval"

        void_amendment(amendment["id"])
        a1_end = get_allocation_for(grant_id, s1["id"])
        pd_end = validate_success(api_client.get_set_aside(pd["id"], DIRECTOR))
        assert a1_end["allocation_amount_cents"] == ALLOC_AMOUNTS_VERIFIED[0]
        assert pd_end["reserved_cents"] == PD_MINIMUM_VERIFIED
        assert distributed_total() == net, \
            "zero drift across the forward+compensating pair"
        after = validate_success(api_client.get_amendment(amendment["id"],
                                                          DIRECTOR))
        assert after["status"] == "VOIDED"

    def test_prior_amounts_captured_and_versions_advance(self):
        """PRD §3.8: "A created amendment starts in `DRAFT` and advances the
        grant's `version` by one, which itself invalidates any other draft
        pinned to the older baseline."
        PRD §3.8: "A successful approval captures `prior_amounts` — a snapshot
        of each line's `target_id` with its `prior_amount_cents` — writes each
        line's value onto its target (onto `allocation_amount_cents` or
        `reserved_cents` as the `target_type` dictates), recomputes the
        parent-engagement distribution minimum if the `PARENT_ENGAGEMENT`
        set-aside was touched, and advances the grant's `version` by one."
        PRD §3.8: "The parent-engagement distribution minimum is recomputed if
        that category was touched, and the grant's `version` advances by one."

        Design: Difficulty/compensating_invariant/amendment_apply_void_conserves_money
        """
        ctx = setup_equitable_scenario(fiscal_year=2027,
                                       equitable_count_method="VERIFIED_COUNT")
        grant_id = ctx["grant"]["id"]
        s2, s3 = ctx["schools"][1], ctx["schools"][2]
        a2 = ctx["allocations"][s2["id"]]  # 21,841,768
        a3 = ctx["allocations"][s3["id"]]  # 14,561,168
        v0 = get_grant(grant_id)["version"]
        amendment = draft_amendment(
            grant_id,
            [amendment_line("SCHOOL_ALLOCATION", a2["id"],
                            a2["allocation_amount_cents"] - 500_000),
             amendment_line("SCHOOL_ALLOCATION", a3["id"],
                            a3["allocation_amount_cents"] + 500_000)])
        assert get_grant(grant_id)["version"] == v0 + 1, "create advances +1"
        submit_amendment(amendment["id"])
        approved = approve_amendment(amendment["id"])
        assert get_grant(grant_id)["version"] == v0 + 2, "approve advances +1"
        priors = {row["target_id"]: row["prior_amount_cents"]
                  for row in approved["prior_amounts"]}
        assert priors == {
            a2["id"]: a2["allocation_amount_cents"],
            a3["id"]: a3["allocation_amount_cents"],
        }, "prior_amounts is a verbatim snapshot of the pre-approval values"
        void_amendment(amendment["id"])
        assert get_grant(grant_id)["version"] == v0 + 3, "void advances +1"
        assert get_allocation_for(grant_id, s2["id"])[
            "allocation_amount_cents"] == a2["allocation_amount_cents"]
        assert get_allocation_for(grant_id, s3["id"])[
            "allocation_amount_cents"] == a3["allocation_amount_cents"]
