"""The program-year volume cap pool: reservation, decision, deferral and recycling.

Every figure the pool publishes is re-derived from the set of allocations that
draw on it, so these tests always read the pool back after each write rather than
tracking a running total of their own. The conservation identity of PRD §2.9 is
checked on every observation through ``assert_pool_ledger``.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_pool_ledger,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestDecidingAPendingRequest:
    """The two decision branches and what the pool does about each of them."""

    def test_denying_a_pending_request_stamps_the_reason_and_gives_the_reservation_back(
        self, api
    ):
        """A denial records who denied it and why, and un-reserves the cap.

        The request is the only claim on a 600,000,000 pool, so the pool's own
        version is the cleanest witness of the two writes that touched it: the
        creation reserved the request and the denial released it, leaving the pool
        exactly as it opened while the allocation keeps its audit trail.

        PRD: "The request opens in `PENDING` with `decision_round` at 1, and it immediately reserves its requested amount against the pool: the pool's `reserved_cents` rises by that amount, `available_cents` falls by the same amount and may go negative, `pool_status` may therefore flip to `OVERSUBSCRIBED`, and the pool's `version` increments by 1."
        PRD: "Denial moves the request `PENDING` → `DENIED`, stamps `denial_reason` and `decided_by_user_id`, and re-derives the pool with `reserved_cents` dropping by the requested amount and no corresponding rise in `committed_cents`; the pool's `version` still increments by 1."
        PRD: "`version` starts at 1 when the row is created and increments by exactly 1 on every mutation of that row"

        Design: Corner/state_machines/denying_a_pending_allocation_stamps_the_reason_and_releases_the_reservation
        """
        deal = fixtures.setup_project(api)
        allocation = fixtures.request_cap(api, deal)

        pool_before = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_before,
            reserved_cents=constants.REQUESTED_AMOUNT_CENTS,
            committed_cents=0,
            label="pool before the decision",
        )
        assert pool_before["version"] == 2, (
            "creation is version 1 and the reservation is the only mutation so far, "
            "so the pool the officer observes must be at version 2, not {0}".format(
                pool_before["version"]
            )
        )

        denied = validate_success(
            api.decide_volume_cap_allocation(
                allocation["id"],
                ALLOCATION_OFFICER,
                decision="DENY",
                denial_reason="scoring below the funding line",
                expected_cap_pool_version=pool_before["version"],
            )
        )
        assert_fields(
            denied,
            "denied allocation",
            status="DENIED",
            denial_reason="scoring below the funding line",
            decided_by_user_id="hfa-alloc-1",
            decision_round=1,
        )
        assert_nulls(
            denied, ["awarded_amount_cents", "expiry_date"], "denied allocation"
        )

        pool_after = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_after,
            reserved_cents=0,
            committed_cents=0,
            available_cents=constants.POOL_TOTAL_CAP_CENTS,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool after the denial",
        )
        assert pool_after["version"] == 3, (
            "the denial is the pool's third state: created, reserved, released — "
            "got version {0}".format(pool_after["version"])
        )

        project = fixtures.read_project(api, deal)
        assert_fields(
            project,
            "development after the denial",
            financing_stalled=False,
            volume_cap_deferral_count=0,
        )

    def test_a_pending_request_can_be_neither_returned_nor_revised(self, api):
        """Neither sponsor-driven trigger has an outgoing edge from PENDING.

        Returning is only available from `AWARDED` and revision only from the three
        re-fileable states, so both calls are refused on the allocation's own state
        error and neither of them may edit the row on the way out — the reservation
        against the pool has to survive both attempts intact.

        PRD: "It is permitted only from `AWARDED`, and only when no bond issue references the allocation with a `status` of `ISSUED`, `CONVERTED` or `MANDATORY_REDEEMED`."
        PRD: "Three states — `DEFERRED`, `DENIED` and `RETURNED` — are all re-fileable."
        PRD: "the subject's current state must have an outgoing transition for the trigger being invoked"

        Design: Corner/state_machines/returning_or_revising_a_pending_allocation_has_no_outgoing_transition
        """
        deal = fixtures.setup_project(api)
        allocation = fixtures.request_cap(api, deal)

        validate_error(
            api.return_volume_cap_allocation(
                allocation["id"], deal.developer_headers, return_reason="sponsor withdrew"
            ),
            ApiErrorId.ERR_ALLOCATION_STATE_INVALID,
            409,
        )
        validate_error(
            api.revise_volume_cap_allocation(
                allocation["id"],
                deal.developer_headers,
                requested_amount_cents=150000000,
                requested_closing_date="2026-10-15T00:00:00Z",
            ),
            ApiErrorId.ERR_ALLOCATION_STATE_INVALID,
            409,
        )

        unchanged = validate_success(
            api.get_volume_cap_allocation(allocation["id"], ALLOCATION_OFFICER)
        )
        assert_fields(
            unchanged,
            "allocation after both refusals",
            status="PENDING",
            requested_amount_cents=constants.REQUESTED_AMOUNT_CENTS,
            decision_round=1,
        )
        assert_nulls(unchanged, ["return_reason"], "allocation after both refusals")

        pool = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool,
            reserved_cents=constants.REQUESTED_AMOUNT_CENTS,
            committed_cents=0,
            label="pool after both refusals",
        )
        assert pool["version"] == 2, (
            "a refused trigger is not a mutation, so the pool must still be at the "
            "version the reservation left it on — got {0}".format(pool["version"])
        )


class TestAwardExpiry:
    """The award deadline is exclusive for the gate and strict for the transition."""

    def test_an_award_expiring_exactly_at_the_clock_instant_is_already_unusable(self, api):
        """At the expiry instant the award is unusable but not yet expired.

        The two rules that read `expiry_date` disagree by one instant. The gate on
        sizing a bond issue treats the deadline as exclusive, so equality already
        refuses the filing; the state transition needs the clock strictly past the
        deadline, so at equality the award is still `AWARDED` and the pool still
        counts it. One second later the transition fires, the cap comes back, and
        the very same filing is refused again for the opposite reason.

        PRD: "Sizing a bond issue and closing it both require the referenced `VolumeCapAllocation` to be `AWARDED` with its `expiry_date` strictly after the current logical clock. An `expiry_date` exactly equal to the clock instant counts as expired, because the deadline is exclusive."
        PRD: "An award whose `expiry_date` the logical clock passes strictly moves `AWARDED` → `EXPIRED`, and the pool is re-derived so that `committed_cents` drops by the lapsed `awarded_amount_cents` and `pool_status` is re-derived; `EXPIRED` is terminal."
        PRD: "For a program-year cap pool, the total cap always equals the sum of the available, reserved and committed amounts."

        Design: Corner/validations/an_award_expiring_exactly_at_the_clock_instant_is_already_unusable
        """
        deal = fixtures.setup_project(api)
        allocation = fixtures.request_cap(api, deal)
        awarded = fixtures.award_allocation(api, deal, allocation["id"])
        assert_fields(
            awarded,
            "awarded allocation",
            status="AWARDED",
            expiry_date=constants.AWARD_EXPIRY_DATE,
        )

        fixtures.set_clock(api, constants.AWARD_EXPIRY_DATE)

        at_equality = validate_success(
            api.get_volume_cap_allocation(allocation["id"], ALLOCATION_OFFICER)
        )
        assert at_equality["status"] == "AWARDED", (
            "equality with expiry_date must not fire AWARDED -> EXPIRED, which needs "
            "the clock strictly past the deadline — got {0}".format(
                at_equality["status"]
            )
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=constants.AWARDED_AMOUNT_CENTS,
            awardable_cents=(
                constants.POOL_TOTAL_CAP_CENTS - constants.AWARDED_AMOUNT_CENTS
            ),
            pool_status="OPEN",
            label="pool at the expiry instant",
        )

        sizing_payload = factories.bond_issue_payload(deal.project_id, allocation["id"])
        validate_error(
            api.create_bond_issue(deal.developer_headers, **sizing_payload),
            ApiErrorId.ERR_ALLOCATION_EXPIRED,
            409,
        )

        fixtures.set_clock(api, "2027-06-30T00:00:01Z")

        past = validate_success(
            api.get_volume_cap_allocation(allocation["id"], ALLOCATION_OFFICER)
        )
        assert_fields(
            past,
            "allocation one second later",
            status="EXPIRED",
            awarded_amount_cents=constants.AWARDED_AMOUNT_CENTS,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=0,
            available_cents=constants.POOL_TOTAL_CAP_CENTS,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool after the award lapsed",
        )

        validate_error(
            api.create_bond_issue(deal.developer_headers, **sizing_payload),
            ApiErrorId.ERR_ALLOCATION_EXPIRED,
            409,
        )
        assert_page(
            api.list_bond_issues(ALLOCATION_OFFICER, project_id=deal.project_id),
            total_count=0,
        )


class TestPoolThresholdsAndCascades:
    """Two thresholds hang off the same aggregates and fire at different moments."""

    def test_the_pool_walks_open_to_oversubscribed_to_exhausted_and_resets_on_a_return(
        self, api
    ):
        """The two derived thresholds, the deferral cascade and the reverse cascade.

        `OVERSUBSCRIBED` keys on `available_cents` going negative from pending
        requests alone, while `EXHAUSTED` keys on `awardable_cents` reaching zero
        from actual awards, and exhaustion wins the derivation when both hold. The
        walk pins the inclusive award ceiling, the automatic deferral the
        zero-crossing fires on every other pending request, the priority inversion
        that follows — the deferred request is now refused on state rather than on
        cap — and the reset, where returning the first award reopens the pool and
        pulls the deferred request back into contention.

        PRD: "The derived `pool_status` is `EXHAUSTED` when `awardable_cents` is less than or equal to zero; otherwise `OVERSUBSCRIBED` when `available_cents` is less than zero; otherwise `OPEN`."
        PRD: "An awarded amount above the awardable ceiling is `ERR_INSUFFICIENT_VOLUME_CAP`; equality is explicitly allowed and drives the pool straight to `EXHAUSTED`."
        PRD: "If the re-derivation leaves the pool at `pool_status` `EXHAUSTED`, then every *other* allocation of the same pool that is still `PENDING` and whose `requested_amount_cents` exceeds the new `awardable_cents` is moved `PENDING` → `DEFERRED`."
        PRD: "Each of those deferrals in turn increments its own development's `volume_cap_deferral_count` by 1 and sets that development's `financing_stalled` to true; and because the pool counts a request in `reserved_cents` only while it is `PENDING`, the pool's reserved figure drops by each deferred request's requested amount as well."
        PRD: "if the re-derivation leaves `pool_status` at anything other than `EXHAUSTED`, every `DEFERRED` allocation of that pool returns to `PENDING`, and each of those reinstatements sets its own development's `financing_stalled` back to false."

        Design: Corner/cross_cutting_complexity_layers/the_pool_walks_open_to_oversubscribed_to_exhausted_at_the_awardable_boundary_and_resets_on_a_return
        """
        deal = fixtures.setup_project(api)
        project_b = fixtures.file_second_project(
            api,
            deal,
            name="Bayside Two",
            land_cost_cents=30000000,
            depreciable_basis_cents=280000000,
        )
        project_c = fixtures.file_second_project(
            api,
            deal,
            name="Cedar Court",
            land_cost_cents=20000000,
            depreciable_basis_cents=150000000,
        )

        alloc_a = fixtures.request_cap(api, deal, requested_amount_cents=400000000)
        alloc_b = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    project_b["id"],
                    deal.pool_id,
                    requested_amount_cents=300000000,
                    requested_closing_date="2026-09-20T00:00:00Z",
                )
            ),
            201,
        )
        alloc_c = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    project_c["id"],
                    deal.pool_id,
                    requested_amount_cents=100000000,
                    requested_closing_date="2026-09-25T00:00:00Z",
                )
            ),
            201,
        )

        # Three pending requests totalling 800,000,000 oversubscribe the pool
        # without exhausting it: nothing has been awarded, so awardable is untouched.
        pool_1 = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_1,
            reserved_cents=800000000,
            committed_cents=0,
            available_cents=-200000000,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OVERSUBSCRIBED",
            label="pool with three pending requests",
        )

        awarded_a = validate_success(
            api.decide_volume_cap_allocation(
                alloc_a["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    pool_1["version"], awarded_amount_cents=400000000
                )
            )
        )
        assert awarded_a["status"] == "AWARDED"

        pool_2 = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_2,
            reserved_cents=400000000,
            committed_cents=400000000,
            available_cents=-200000000,
            awardable_cents=200000000,
            pool_status="OVERSUBSCRIBED",
            label="pool after the first award",
        )
        still_pending = validate_success(
            api.get_volume_cap_allocation(alloc_c["id"], ALLOCATION_OFFICER)
        )
        assert still_pending["status"] == "PENDING", (
            "awardable_cents was still positive after the first award, so no deferral "
            "may have fired — allocation C is {0}".format(still_pending["status"])
        )
        assert_fields(
            validate_success(api.get_project(project_c["id"], ALLOCATION_OFFICER)),
            "Cedar Court before exhaustion",
            financing_stalled=False,
            volume_cap_deferral_count=0,
        )

        # 300,000,000 overshoots the 200,000,000 ceiling. The refusal is not a
        # mutation, so the same version token is still current for the retry.
        validate_error(
            api.decide_volume_cap_allocation(
                alloc_b["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    pool_2["version"], awarded_amount_cents=300000000
                )
            ),
            ApiErrorId.ERR_INSUFFICIENT_VOLUME_CAP,
            422,
        )
        assert (
            validate_success(
                api.get_volume_cap_allocation(alloc_b["id"], ALLOCATION_OFFICER)
            )["status"]
            == "PENDING"
        )
        assert fixtures.read_pool(api, deal)["version"] == pool_2["version"], (
            "a refused award must leave the pool version alone, which is what makes "
            "the observed ceiling still admissible on the retry"
        )

        awarded_b = validate_success(
            api.decide_volume_cap_allocation(
                alloc_b["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    pool_2["version"], awarded_amount_cents=200000000
                )
            )
        )
        assert awarded_b["status"] == "AWARDED", (
            "an award exactly equal to awardable_cents is admissible and is what "
            "drives the pool to zero"
        )

        pool_3 = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_3,
            reserved_cents=0,
            committed_cents=600000000,
            available_cents=0,
            awardable_cents=0,
            pool_status="EXHAUSTED",
            label="pool at the awardable boundary",
        )
        assert_fields(
            validate_success(
                api.get_volume_cap_allocation(alloc_c["id"], ALLOCATION_OFFICER)
            ),
            "allocation C after the zero-crossing",
            status="DEFERRED",
        )
        assert_fields(
            validate_success(api.get_project(project_c["id"], ALLOCATION_OFFICER)),
            "Cedar Court after the zero-crossing",
            financing_stalled=True,
            volume_cap_deferral_count=1,
        )

        # Priority inversion: the deferral moved C out of PENDING, so the state rule
        # at band six answers before the fiscal cap rule further down the ladder.
        validate_error(
            api.decide_volume_cap_allocation(
                alloc_c["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    pool_3["version"], awarded_amount_cents=100000000
                )
            ),
            ApiErrorId.ERR_ALLOCATION_STATE_INVALID,
            409,
        )

        returned = fixtures.return_allocation(
            api, deal, alloc_a["id"], return_reason="closing slipped past the program year"
        )
        assert returned["status"] == "RETURNED"
        assert_nulls(returned, ["awarded_amount_cents", "expiry_date"], "returned award")

        pool_4 = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            pool_4,
            reserved_cents=100000000,
            committed_cents=200000000,
            available_cents=300000000,
            awardable_cents=400000000,
            pool_status="OPEN",
            label="pool after the return",
        )
        assert_fields(
            validate_success(api.get_project(project_c["id"], ALLOCATION_OFFICER)),
            "Cedar Court after the reverse cascade",
            financing_stalled=False,
            volume_cap_deferral_count=1,
        )

        reinstated = validate_success(
            api.decide_volume_cap_allocation(
                alloc_c["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    pool_4["version"], awarded_amount_cents=100000000
                )
            )
        )
        assert reinstated["status"] == "AWARDED", (
            "the request refused twice — once on cap, once on state — is awardable "
            "once the return has reopened the pool"
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=300000000,
            available_cents=300000000,
            awardable_cents=300000000,
            pool_status="OPEN",
            label="pool after the reset award",
        )

    def test_sponsor_project_count_and_pool_aggregates_reconcile_after_a_withdrawal(
        self, api
    ):
        """Two denormalized counters two entities apart settle from one trigger.

        `active_project_count` is defined by exclusion — every development of the
        sponsor that is not `WITHDRAWN` — so it is easy to maintain on the create
        path and easy to get wrong afterwards: nothing ever writes to the sponsor
        row when a bond issue is redeemed, yet the redemption withdraws the
        development and the counter has to notice. The same redemption releases the
        committed cap, so the sponsor counter and the pool aggregates must reconcile
        together. A count materialized at creation and never revisited passes the
        first two observations and fails the third.

        PRD: "an `active_project_count` that counts the sponsor's developments whose `development_status` is anything other than `WITHDRAWN`"
        PRD: "raises the sponsor's `active_project_count` by 1 and increments the sponsor's `version` by 1"
        PRD: "The development moves to `WITHDRAWN` — from `FINANCED`, from `UNDER_CONSTRUCTION` or from `PLACED_IN_SERVICE`, with the identical effect set in each case — its `automatic_credit_triggered` is set back to false and its `provisional_fifty_percent_ratio_bps` is cleared to null."
        PRD: "The referenced allocation moves `COMMITTED` → `RELEASED`, the pool is re-derived so that `committed_cents` falls by the `awarded_amount_cents`"

        Design: Corner/cross_cutting_complexity_layers/sponsor_project_count_and_pool_aggregates_reconcile_after_creates_and_after_the_source_project_is_withdrawn
        """
        deal = fixtures.setup_issued_bond(api)

        sponsor_1 = fixtures.read_developer(api, deal)
        assert sponsor_1["active_project_count"] == 1, (
            "the financed development is not withdrawn, so it counts — got {0}".format(
                sponsor_1["active_project_count"]
            )
        )

        project_b = fixtures.file_second_project(
            api,
            deal,
            name="Bayside Two",
            land_cost_cents=30000000,
            depreciable_basis_cents=280000000,
        )
        project_c = fixtures.file_second_project(
            api,
            deal,
            name="Cedar Court",
            land_cost_cents=20000000,
            depreciable_basis_cents=150000000,
        )

        sponsor_2 = fixtures.read_developer(api, deal)
        assert sponsor_2["active_project_count"] == 3, (
            "two filings raise the counter to three, got {0}".format(
                sponsor_2["active_project_count"]
            )
        )
        assert sponsor_2["version"] > sponsor_1["version"], (
            "each filing increments the sponsor's version as well as its count"
        )

        redeemed = fixtures.redeem_bond(
            api,
            deal,
            redemption_date="2026-10-01T00:00:00Z",
            reason="construction contract terminated",
        )
        assert redeemed["status"] == "MANDATORY_REDEEMED"

        withdrawn = fixtures.read_project(api, deal)
        assert_fields(
            withdrawn,
            "the redeemed development",
            development_status="WITHDRAWN",
            automatic_credit_triggered=False,
        )
        assert_nulls(
            withdrawn, ["provisional_fifty_percent_ratio_bps"], "the redeemed development"
        )

        sponsor_3 = fixtures.read_developer(api, deal)
        assert sponsor_3["active_project_count"] == 2, (
            "the withdrawn development drops out of a count that no write in this "
            "request ever named — got {0}".format(sponsor_3["active_project_count"])
        )
        for sibling in (project_b, project_c):
            assert_fields(
                validate_success(api.get_project(sibling["id"], ALLOCATION_OFFICER)),
                "untouched sibling development",
                development_status="PLANNING",
            )

        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=0,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool after the release",
        )
        assert (
            fixtures.read_allocation(api, deal)["status"] == "RELEASED"
        ), "the same redemption released the committed cap"

        assert_page(
            api.list_projects(ALLOCATION_OFFICER, developer_id=deal.developer_id),
            total_count=3,
        )


class TestReenteringPending:
    """PENDING is re-entered along two different back-edges, one of them indirect."""

    def test_an_allocation_reenters_pending_from_denied_and_from_deferred(self, api):
        """A revision and a cascade both lead back to PENDING with a rising round.

        The state graph has cycles: a denied request comes back after the sponsor
        revises it, and a deferred request comes back the same way — except that the
        second request's deferral was never asked for by anybody. It is a side
        effect of a *different* allocation's award exhausting the pool, which no
        forward-only reading of the machine predicts.

        PRD: "From any of those three states the allocation returns to `PENDING`, `decision_round` increments by 1, and `awarded_amount_cents`, `expiry_date`, `denial_reason`, `return_reason` and `decided_by_user_id` are all cleared to null."
        PRD: "The `PENDING` → `DENIED` → `PENDING` path is the negotiation loop with the agency and may repeat; `decision_round` records how many rounds have occurred."
        PRD: "Coming back from `DEFERRED` additionally sets the development's `financing_stalled` to false."
        PRD: "In every case the pool is re-derived so that `reserved_cents` rises by the **new** requested amount, and the pool's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/volume_cap_allocation_reenters_pending_from_denied_and_from_deferred_with_a_rising_round
        """
        deal = fixtures.setup_project(
            api, project_kind="ten_unit", pool_overrides={"carryforward_cents": 0}
        )
        project_b = fixtures.file_second_project(
            api,
            deal,
            name="Cedar Yard",
            total_units=8,
            total_floor_space_sqft=6400,
            land_cost_cents=20000000,
            depreciable_basis_cents=180000000,
            set_aside_election="MIN_20_50",
        )

        alloc_a = fixtures.request_cap(
            api,
            deal,
            requested_amount_cents=400000000,
            requested_closing_date="2026-09-01T00:00:00Z",
        )
        denied = validate_success(
            api.decide_volume_cap_allocation(
                alloc_a["id"],
                ALLOCATION_OFFICER,
                **factories.denial_payload(
                    fixtures.pool_version(api, deal),
                    denial_reason="Scoring below the competitive threshold for round one",
                )
            )
        )
        assert_fields(
            denied, "allocation A after the denial", status="DENIED", decision_round=1
        )

        revised = validate_success(
            api.revise_volume_cap_allocation(
                alloc_a["id"],
                deal.developer_headers,
                requested_amount_cents=500000000,
                requested_closing_date="2026-10-01T00:00:00Z",
            )
        )
        assert_fields(
            revised,
            "allocation A back from DENIED",
            status="PENDING",
            decision_round=2,
            requested_amount_cents=500000000,
        )
        assert_nulls(revised, ["denial_reason"], "allocation A back from DENIED")

        alloc_b = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    project_b["id"],
                    deal.pool_id,
                    requested_amount_cents=100000000,
                    requested_closing_date="2026-10-15T00:00:00Z",
                )
            ),
            201,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=600000000,
            committed_cents=0,
            available_cents=-100000000,
            awardable_cents=500000000,
            pool_status="OVERSUBSCRIBED",
            label="pool with both requests pending",
        )

        awarded = validate_success(
            api.decide_volume_cap_allocation(
                alloc_a["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    fixtures.pool_version(api, deal), awarded_amount_cents=500000000
                )
            )
        )
        assert_fields(
            awarded,
            "allocation A after the award",
            status="AWARDED",
            awarded_amount_cents=500000000,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=500000000,
            available_cents=0,
            awardable_cents=0,
            pool_status="EXHAUSTED",
            label="pool exhausted by the award",
        )
        assert (
            validate_success(
                api.get_volume_cap_allocation(alloc_b["id"], ALLOCATION_OFFICER)
            )["status"]
            == "DEFERRED"
        ), "no call named allocation B, yet the award moved it"
        assert_fields(
            validate_success(api.get_project(project_b["id"], ALLOCATION_OFFICER)),
            "Cedar Yard after the cascade",
            volume_cap_deferral_count=1,
            financing_stalled=True,
        )

        reinstated = validate_success(
            api.revise_volume_cap_allocation(
                alloc_b["id"],
                deal.developer_headers,
                requested_amount_cents=100000000,
                requested_closing_date="2027-01-15T00:00:00Z",
            )
        )
        assert_fields(
            reinstated,
            "allocation B back from DEFERRED",
            status="PENDING",
            decision_round=2,
        )
        assert_fields(
            validate_success(api.get_project(project_b["id"], ALLOCATION_OFFICER)),
            "Cedar Yard after the revision",
            financing_stalled=False,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=100000000,
            committed_cents=500000000,
            available_cents=-100000000,
            awardable_cents=0,
            pool_status="EXHAUSTED",
            label="pool after the second revision",
        )


class TestDecisionLadderPairs:
    """Two decisions that violate two rules at once, answered from the top down."""

    def test_wrong_role_on_a_missing_allocation_is_refused_on_role_not_existence(
        self, api
    ):
        """Authorization outranks existence, so the 404 is never reached.

        The compliance officer aims a decision at an allocation identifier that was
        never created, so the request violates both the endpoint's role list and the
        path-entity rule. Authorization sits in the first band of the ladder and
        existence in the third, so the answer is the 403 — and the response
        therefore leaks nothing about which allocation identifiers exist.

        PRD: "The `X-User-Role` value must appear in that endpoint's authorized-role list, and this is checked before existence — so an `HfaComplianceOfficer` deciding a cap allocation whose id does not exist receives `ERR_FORBIDDEN_ROLE`, not a 404."
        PRD: "Every request walks the ladder from the top and returns the first violated rule's error."

        Design: Difficulty/priority_pair_validation_conflict/wrong_role_on_a_missing_allocation_is_rejected_on_role_before_existence
        """
        pool = validate_success(
            api.create_cap_pool(ALLOCATION_OFFICER, **factories.cap_pool_payload()), 201
        )
        observed = validate_success(api.get_cap_pool(pool["id"], ALLOCATION_OFFICER))

        validate_error(
            api.decide_volume_cap_allocation(
                constants.MISSING_UUID_E,
                COMPLIANCE_OFFICER,
                **factories.award_payload(observed["version"])
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

        after = validate_success(api.get_cap_pool(pool["id"], ALLOCATION_OFFICER))
        assert_pool_ledger(
            after,
            reserved_cents=0,
            committed_cents=0,
            available_cents=constants.POOL_TOTAL_CAP_CENTS,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool after the refused decision",
        )
        assert after["version"] == observed["version"], (
            "a refused request writes nothing, so the pool version is unchanged"
        )

    def test_a_stale_pool_version_outranks_the_already_awarded_allocation_state(self, api):
        """The concurrency check answers before the state machine does.

        A second award aimed at an allocation that is already `AWARDED`, carrying the
        pool version read before the first award, violates both the version rule and
        the state rule. The version check sits one band higher, so the caller is told
        to re-read the pool before being told the transition is impossible — and
        neither the allocation nor the pool moves.

        PRD: "This is checked *after* existence but *before* any state or business rule, so a stale version wins over a wrong-state parent: a client that pins an old pool version *and* targets an already-awarded allocation gets `ERR_STALE_CAP_POOL_VERSION`, not the state error."
        PRD: "Such a request is rejected with `ERR_STALE_CAP_POOL_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/stale_cap_pool_version_outranks_the_already_awarded_allocation_state
        """
        deal = fixtures.setup_project(api, project_kind="ten_unit")
        allocation = fixtures.request_cap(
            api, deal, requested_closing_date="2026-09-01T00:00:00Z"
        )
        observed_version = fixtures.pool_version(api, deal)

        validate_success(
            api.decide_volume_cap_allocation(
                allocation["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(observed_version)
            )
        )

        validate_error(
            api.decide_volume_cap_allocation(
                allocation["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(
                    observed_version, awarded_amount_cents=150000000
                )
            ),
            ApiErrorId.ERR_STALE_CAP_POOL_VERSION,
            412,
        )

        assert_fields(
            validate_success(
                api.get_volume_cap_allocation(allocation["id"], ALLOCATION_OFFICER)
            ),
            "allocation after the stale retry",
            status="AWARDED",
            awarded_amount_cents=constants.AWARDED_AMOUNT_CENTS,
            decision_round=1,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            committed_cents=constants.AWARDED_AMOUNT_CENTS,
            available_cents=(
                constants.POOL_TOTAL_CAP_CENTS - constants.AWARDED_AMOUNT_CENTS
            ),
            label="pool after the stale retry",
        )


class TestReturnConservation:
    """Returning an award has to put the cap back without disturbing a reservation."""

    def test_returning_an_award_restores_the_conservation_identity_with_a_live_reservation(
        self, api
    ):
        """The conserved quantity is volume cap cents, and a return is exact.

        The award moves 200,000,000 out of available and into committed and the
        return moves it back, while a second development's pending request keeps
        `reserved_cents` pinned at a nonzero 150,000,000 throughout. An
        implementation that rebuilt the pool by applying deltas rather than
        re-deriving from the allocation set would leak that reservation into the
        available balance, so the identity is checked at all three observations and
        `awardable_cents` and `pool_status` must come back to their pre-award values.

        PRD: "For a program-year cap pool, the total cap always equals the sum of the available, reserved and committed amounts."
        PRD: "`reserved_cents` is the sum of `requested_amount_cents` over the pool's allocations that are still `PENDING`; `committed_cents` is the sum of `awarded_amount_cents` over the pool's allocations that are `AWARDED` or `COMMITTED`"
        PRD: "The return records the reason, clears `awarded_amount_cents` and `expiry_date` to null, and re-derives the pool: `committed_cents` falls by the returned award, `awardable_cents` and `available_cents` rise, `pool_status` is re-derived and the pool's `version` increments by 1."
        PRD: "Every allocation create, decision, revision, return, expiry and release re-derives all six of those figures from scratch."

        Design: Difficulty/compensating_invariant/returning_an_award_restores_the_cap_pool_conservation_identity_with_a_live_reservation_present
        """
        deal = fixtures.setup_project(api, project_kind="ten_unit")
        project_b = fixtures.file_second_project(
            api,
            deal,
            land_cost_cents=30000000,
            depreciable_basis_cents=270000000,
        )

        alloc_a = fixtures.request_cap(
            api, deal, requested_closing_date="2026-09-01T00:00:00Z"
        )
        alloc_b = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    project_b["id"],
                    deal.pool_id,
                    requested_amount_cents=150000000,
                    requested_closing_date="2026-10-01T00:00:00Z",
                )
            ),
            201,
        )

        before_award = fixtures.read_pool(api, deal)
        assert_pool_ledger(
            before_award,
            reserved_cents=350000000,
            committed_cents=0,
            available_cents=250000000,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool before the award",
        )

        validate_success(
            api.decide_volume_cap_allocation(
                alloc_a["id"],
                ALLOCATION_OFFICER,
                **factories.award_payload(before_award["version"])
            )
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=150000000,
            committed_cents=200000000,
            available_cents=250000000,
            awardable_cents=400000000,
            pool_status="OPEN",
            label="pool with the award outstanding",
        )

        returned = validate_success(
            api.return_volume_cap_allocation(
                alloc_a["id"],
                deal.developer_headers,
                return_reason="sponsor deferred the closing to the 2027 program year",
            )
        )
        assert_fields(
            returned,
            "returned award",
            status="RETURNED",
            return_reason="sponsor deferred the closing to the 2027 program year",
            decision_round=1,
            decided_by_user_id="hfa-alloc-1",
        )
        assert_nulls(
            returned, ["awarded_amount_cents", "expiry_date"], "returned award"
        )

        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=150000000,
            committed_cents=0,
            available_cents=450000000,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
            label="pool after the return",
        )
        assert_fields(
            validate_success(
                api.get_volume_cap_allocation(alloc_b["id"], ALLOCATION_OFFICER)
            ),
            "the untouched sibling request",
            status="PENDING",
            requested_amount_cents=150000000,
            decision_round=1,
        )
