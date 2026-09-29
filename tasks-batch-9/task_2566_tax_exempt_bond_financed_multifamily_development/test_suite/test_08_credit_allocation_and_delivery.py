"""Computing the final credit allocation, signing Form 8609 and delivering the credit.

The allocation is the first row in the domain whose derived figures are solved unit by
unit, and the deliveries hanging off it are the only rows that join a development to an
investor. These tests cover the qualified-basis arithmetic, the four ordered gates on
the allocation, the segregation-of-duties comparison at issuance, and the delivery
waterfall with its clamp, its version token and its compensating rescission.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    ALLOCATION_OFFICER_USER_ID,
    COMPLIANCE_OFFICER,
    SECOND_ALLOCATION_OFFICER,
    SECOND_ALLOCATION_OFFICER_USER_ID,
    THIRD_ALLOCATION_OFFICER,
    THIRD_ALLOCATION_OFFICER_USER_ID,
    TRUSTEE,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_pool_ledger,
    assert_unit_counts,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

SIBLING_UNITS = (
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "floor_space_sqft": 800,
        "designation": "RESTRICTED",
        "ami_percent": 60,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    },
    {
        "unit_number": "201",
        "bedroom_count": 1,
        "floor_space_sqft": 800,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    },
)


def _finance_sibling(api, deal, name="Bayside Two", instrument_number="KC-2026-0002"):
    """File a smaller second development under the same sponsor and drive it into service.

    Its filed basis is 100,000,000 and its par is 50,000,000, so its own fifty-percent
    ratio lands on exactly 5,000 basis points and the bonds can close out of the same
    program-year pool.
    """
    project = fixtures.file_second_project(
        api,
        deal,
        name=name,
        total_units=2,
        total_floor_space_sqft=1600,
        land_cost_cents=10000000,
        depreciable_basis_cents=90000000,
    )
    for spec in SIBLING_UNITS:
        validate_success(
            api.create_unit_restriction(
                deal.developer_headers, **dict(spec, project_id=project["id"])
            ),
            201,
        )
    agreement = validate_success(
        api.create_regulatory_agreement(
            deal.developer_headers, **factories.agreement_payload(project["id"])
        ),
        201,
    )
    validate_success(
        api.record_regulatory_agreement(
            agreement["id"], COMPLIANCE_OFFICER, instrument_number=instrument_number
        )
    )
    request = validate_success(
        api.create_volume_cap_allocation(
            deal.developer_headers,
            **factories.cap_request_payload(
                project["id"], deal.pool_id, requested_amount_cents=50000000
            )
        ),
        201,
    )
    fixtures.award_allocation(
        api, deal, request["id"], awarded_amount_cents=50000000
    )
    issue = validate_success(
        api.create_bond_issue(
            deal.developer_headers,
            **factories.bond_issue_payload(
                project["id"], request["id"], eligible_cost_cents=43000000
            )
        ),
        201,
    )
    issue = validate_success(
        api.issue_bond_issue(issue["id"], TRUSTEE, closing_date=constants.CLOSING_DATE)
    )
    draw = validate_success(
        api.create_draw_request(
            deal.developer_headers,
            **factories.draw_payload(
                issue["id"], issue["version"], requested_amount_cents=50000000
            )
        ),
        201,
    )
    validate_success(
        api.decide_draw_request(
            draw["id"], TRUSTEE, decision="APPROVE", approved_amount_cents=50000000
        )
    )
    validate_success(
        api.fund_draw_request(
            draw["id"], TRUSTEE, funding_date=constants.DRAW_PERIOD_START
        )
    )
    validate_success(
        api.record_operating_month(
            issue["id"],
            deal.developer_headers,
            month_index=1,
            noi_cents=18000000,
            debt_service_cents=15000000,
            occupied_units=2,
        )
    )
    return validate_success(api.get_project(project["id"], deal.developer_headers))


class TestSolvingTheAllocation:
    """What the create endpoint computes, and what it refuses to compute at all."""

    def test_qualified_basis_floors_per_unit_then_the_annual_credit_rounds_half_up(
        self, api
    ):
        """The two restricted units against a 3,400 square foot development.

        The audited eligible basis of 355,000,000 is apportioned to unit 101 as
        floor(355,000,000 * 800 / 3400) = 83,529,411 and to unit 102 as
        floor(355,000,000 * 900 / 3400) = 93,970,588, and the qualified basis is the sum
        of those already-floored figures, 177,499,999. Summing the two floor areas first
        and dividing once would give 177,500,000 instead, one cent too high, so the
        pinned rounding order is the only route to the right answer. The annual credit
        exercises the other half of the rule: 177,499,999 * 400 / 10,000 is
        7,099,999.96, which rounds half up to 7,100,000 rather than flooring to
        7,099,999, and the ten-year total is therefore 71,000,000 rather than
        70,999,990. The two market units of 850 square feet each contribute nothing.

        PRD: "The development's `RESTRICTED` unit designations are taken in `unit_number` ascending order — any status counts, and the order is irrelevant to the sum but fixed for reproducibility. For each such unit, the certification's `certified_eligible_basis_cents` is multiplied by that unit's `floor_space_sqft`, divided by the development's `total_floor_space_sqft`, and **floored to whole cents for that unit**; `qualified_basis_cents` is the sum of those already-floored per-unit figures. Summing the floor areas first and performing a single division instead is a different and wrong answer."
        PRD: "The allocation also snapshots the development's current `applicable_fraction_bps` onto itself. The `annual_credit_cents` is the qualified basis multiplied by `credit_percentage_bps`, divided by 10,000, rounded half up to whole cents. The `total_credit_cents` is the annual credit multiplied by the ten-year credit period."
        PRD: "At creation `delivered_credit_cents` is zero and `undelivered_credit_cents` equals the total credit, `recapture_amount_cents` is zero, `form_8609_number` is null, the creating officer's `X-User-ID` is recorded as `issued_by_user_id`, and the allocation opens in `PENDING`."

        Design: Corner/calculations/qualified_basis_floors_per_unit_then_sums_and_the_annual_credit_rounds_half_up
        """
        deal = fixtures.setup_credit_allocation(api)

        allocation = deal.credit_allocation
        assert_fields(
            allocation,
            "credit_allocation",
            status="PENDING",
            qualified_basis_cents=177499999,
            annual_credit_cents=7100000,
            total_credit_cents=71000000,
            undelivered_credit_cents=71000000,
            delivered_credit_cents=0,
            recapture_amount_cents=0,
            applicable_fraction_bps=5000,
            issued_by_user_id=THIRD_ALLOCATION_OFFICER_USER_ID,
        )
        assert_nulls(allocation, ("form_8609_number",), "credit_allocation")

        assert_unit_counts(
            fixtures.read_project(api, deal), restricted=2, market=2, designated=4
        )
        assert_fields(
            deal.project,
            "project",
            total_floor_space_sqft=3400,
            applicable_fraction_bps=5000,
        )
        assert_fields(
            deal.cost_certification,
            "cost_certification",
            certified_eligible_basis_cents=355000000,
            status="ACCEPTED",
        )

    def test_the_gates_run_project_status_then_certification_status_then_ownership(
        self, api
    ):
        """Three probes, each violating a later gate as well as the one under test.

        A bare development in `PLANNING` paired with a certification belonging to
        another development breaks both the first gate and the third, and only the
        declared order reports the placed-in-service failure. A `DRAFT` certification of
        the right development isolates the second gate. Reaching the third gate takes a
        second development that is itself in service, so that the accepted certification
        it names is the only thing left to be wrong — which is why two developments have
        to be financed out of the same pool. None of the three refusals leaves a row
        behind, and none of them moves the pool.

        PRD: "Four gates apply in order: the development must be `PLACED_IN_SERVICE` or `STABILIZED`, or the attempt is `ERR_PROJECT_NOT_PLACED_IN_SERVICE`; the referenced certification's `status` must be `ACCEPTED`, or `ERR_COST_CERT_NOT_ACCEPTED`; that certification's own `project_id` must equal the request's `project_id`, or `ERR_COST_CERT_PROJECT_MISMATCH`; and the development may hold at most one credit allocation whose `status` is `PENDING`, `ISSUED` or `RECAPTURE_PENDING`, a second being `ERR_ALLOCATION_ALREADY_EXISTS`."
        PRD: "Creating a credit allocation requires the development's `development_status` to be either `PLACED_IN_SERVICE` or `STABILIZED`; a development still `UNDER_CONSTRUCTION` cannot receive a final allocation even when its cost certification has been accepted."

        Design: Corner/validations/credit_allocation_gates_run_project_status_then_cert_status_then_cert_ownership
        """
        deal = fixtures.setup_accepted_cost_certification(api)
        draft_certification = validate_success(
            api.create_cost_certification(
                deal.developer_headers,
                **factories.cost_certification_payload(deal.project_id)
            ),
            201,
        )
        assert_fields(draft_certification, "second_certification", status="DRAFT")

        sibling = _finance_sibling(api, deal)
        assert_fields(sibling, "sibling_project", development_status="PLACED_IN_SERVICE")

        bare = fixtures.file_second_project(api, deal, name="Cedar Lot")
        assert_fields(bare, "bare_project", development_status="PLANNING")

        validate_error(
            api.create_credit_allocation(
                THIRD_ALLOCATION_OFFICER,
                **factories.credit_allocation_payload(
                    bare["id"], deal.cost_certification_id
                )
            ),
            ApiErrorId.ERR_PROJECT_NOT_PLACED_IN_SERVICE,
            409,
        )
        validate_error(
            api.create_credit_allocation(
                THIRD_ALLOCATION_OFFICER,
                **factories.credit_allocation_payload(
                    deal.project_id, draft_certification["id"]
                )
            ),
            ApiErrorId.ERR_COST_CERT_NOT_ACCEPTED,
            409,
        )
        validate_error(
            api.create_credit_allocation(
                THIRD_ALLOCATION_OFFICER,
                **factories.credit_allocation_payload(
                    sibling["id"], deal.cost_certification_id
                )
            ),
            ApiErrorId.ERR_COST_CERT_PROJECT_MISMATCH,
            409,
        )

        allocation = validate_success(
            api.create_credit_allocation(
                THIRD_ALLOCATION_OFFICER,
                **factories.credit_allocation_payload(
                    deal.project_id, deal.cost_certification_id
                )
            ),
            201,
        )
        assert_fields(
            allocation,
            "credit_allocation",
            status="PENDING",
            qualified_basis_cents=177499999,
        )

        assert_page(
            api.list_credit_allocations(ALLOCATION_OFFICER), total_count=1
        )
        assert_fields(
            validate_success(api.get_project(bare["id"], deal.developer_headers)),
            "bare_project",
            development_status="PLANNING",
        )
        assert_fields(
            validate_success(api.get_project(sibling["id"], deal.developer_headers)),
            "sibling_project",
            development_status="PLACED_IN_SERVICE",
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=250000000,
            available_cents=350000000,
            awardable_cents=350000000,
        )


class TestDeliveringTheCredit:
    """The one row that joins an allocation to an investor, and the gate above it."""

    def test_delivery_creation_links_an_allocation_to_an_investor_and_both_sides_must_exist(
        self, api
    ):
        """Each side of the join probed alone, then the link that moves both ledgers.

        A delivery names two parents that share nothing else, and each unresolvable
        reference reports its own entity's 404 — resolved before the version token is
        even looked at, which is why both probes carry a perfectly good token. The
        successful link then has to move numbers on both sides at different moments: the
        allocation's undelivered credit falls the instant the strip is created, while the
        investor's running total stays at zero until the investor itself accepts.

        PRD: "Every foreign key in the request body must resolve, returning the referenced entity's own 404."
        PRD: "The `price_per_credit_dollar_bps` is then the `capital_contribution_cents` multiplied by 10,000, divided by the clamped `delivered_credit_cents`, floored — which is precisely why a stale allocation version is refused rather than re-priced. The delivery opens in `DELIVERED` with `accepted_at` and `rescind_reason` null; the allocation's `delivered_credit_cents` rises and `undelivered_credit_cents` falls by the delivered amount, and the allocation's `version` increments by 1."
        PRD: "Acceptance is available only from `DELIVERED`; it moves the delivery `DELIVERED` → `ACCEPTED`, stamps `accepted_at` from the logical clock, raises the investor's `total_credit_accepted_cents` by the delivered amount and increments the investor's `version` by 1."

        Design: Corner/endpoints/delivery_creation_links_an_allocation_to_an_investor_and_both_sides_must_exist
        """
        deal = fixtures.setup_issued_credit_allocation(api)
        token = fixtures.credit_allocation_version(api, deal)

        validate_error(
            api.create_investor_delivery(
                deal.developer_headers,
                credit_allocation_id=constants.MISSING_UUID_E,
                investor_id=deal.investor_id,
                requested_credit_cents=30000000,
                capital_contribution_cents=25500000,
                expected_credit_allocation_version=token,
            ),
            ApiErrorId.ERR_CREDIT_ALLOCATION_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_investor_delivery(
                deal.developer_headers,
                credit_allocation_id=deal.credit_allocation_id,
                investor_id=constants.MISSING_UUID_F,
                requested_credit_cents=30000000,
                capital_contribution_cents=25500000,
                expected_credit_allocation_version=token,
            ),
            ApiErrorId.ERR_INVESTOR_NOT_FOUND,
            404,
        )

        untouched = fixtures.read_credit_allocation(api, deal)
        assert_fields(
            untouched,
            "credit_allocation",
            version=token,
            undelivered_credit_cents=71000000,
            delivered_credit_cents=0,
        )

        delivery = fixtures.deliver_credit(api, deal)
        assert_fields(
            delivery,
            "delivery",
            status="DELIVERED",
            requested_credit_cents=30000000,
            delivered_credit_cents=30000000,
            price_per_credit_dollar_bps=8500,
        )
        assert_nulls(delivery, ("accepted_at", "rescind_reason"), "delivery")
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=30000000,
            undelivered_credit_cents=41000000,
            version=token + 1,
        )
        assert_fields(
            fixtures.read_investor(api, deal),
            "investor",
            total_credit_accepted_cents=0,
        )

        accepted = fixtures.accept_delivery(api, deal)
        assert_fields(accepted, "delivery", status="ACCEPTED")
        assert accepted["accepted_at"].startswith("2026-08-01T00:00:00"), (
            "accepted_at should be stamped from the logical clock, got {0!r}".format(
                accepted["accepted_at"]
            )
        )
        assert_fields(
            fixtures.read_investor(api, deal),
            "investor",
            total_credit_accepted_cents=30000000,
        )

    def test_delivery_is_available_only_while_undelivered_credit_remains(self, api):
        """A strip that consumes everything, a refusal, then a rescission that reopens it.

        The gate is not the allocation's state — the allocation stays `ISSUED` and
        perfectly healthy throughout — but the live remainder, which is why the refusal
        is a 422 on the arithmetic rather than a 409 on the row. Only a remainder of
        exactly zero closes the gate, and rescinding the strip that consumed it puts the
        credit back in the pool, so the very next request succeeds against the same
        allocation.

        PRD: "The undelivered remainder is computed as the allocation's `total_credit_cents` less the summed `delivered_credit_cents` of its deliveries whose `status` is `DELIVERED`, `ACCEPTED` or `RECAPTURE_FLAGGED`; deliveries that reached `RESCINDED` are excluded and their credit is back in the pool. When that remainder is already zero the create is refused with `ERR_NO_UNDELIVERED_CREDIT`."
        PRD: "It is available from `DELIVERED` and from `ACCEPTED`, and both branches behave identically toward the allocation: the delivery moves to `RESCINDED`, which is terminal, the reason is stamped, the allocation's `delivered_credit_cents` falls and its `undelivered_credit_cents` rises by the delivered amount, and the allocation's `version` increments by 1 — so that total credit once again equals delivered plus undelivered."

        Design: Corner/endpoints/conditional_action_credit_delivery_only_while_credit_remains
        """
        deal = fixtures.setup_issued_credit_allocation(api)
        first_version = fixtures.credit_allocation_version(api, deal)

        full = fixtures.deliver_credit(
            api,
            deal,
            requested_credit_cents=71000000,
            capital_contribution_cents=60350000,
        )
        assert_fields(
            full,
            "full_strip",
            status="DELIVERED",
            delivered_credit_cents=71000000,
            price_per_credit_dollar_bps=8500,
        )
        subscribed = deal.credit_allocation
        assert_fields(
            subscribed,
            "credit_allocation",
            status="ISSUED",
            delivered_credit_cents=71000000,
            undelivered_credit_cents=0,
        )
        second_version = subscribed["version"]

        validate_error(
            api.create_investor_delivery(
                deal.developer_headers,
                credit_allocation_id=deal.credit_allocation_id,
                investor_id=deal.investor_id,
                requested_credit_cents=1000000,
                capital_contribution_cents=850000,
                expected_credit_allocation_version=second_version,
            ),
            ApiErrorId.ERR_NO_UNDELIVERED_CREDIT,
            422,
        )
        assert_page(
            api.list_investor_deliveries(
                deal.developer_headers, credit_allocation_id=deal.credit_allocation_id
            ),
            total_count=1,
        )

        rescinded = fixtures.rescind_delivery(
            api, deal, rescind_reason="syndication restructured into two strips"
        )
        assert_fields(
            rescinded,
            "full_strip",
            status="RESCINDED",
            rescind_reason="syndication restructured into two strips",
        )
        reopened = deal.credit_allocation
        assert_fields(
            reopened,
            "credit_allocation",
            status="ISSUED",
            delivered_credit_cents=0,
            undelivered_credit_cents=71000000,
        )
        third_version = reopened["version"]

        partial = fixtures.deliver_credit(api, deal)
        assert_fields(
            partial,
            "partial_strip",
            status="DELIVERED",
            delivered_credit_cents=30000000,
            price_per_credit_dollar_bps=8500,
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=30000000,
            undelivered_credit_cents=41000000,
        )
        assert third_version > second_version > first_version, (
            "each waterfall move should advance the allocation version, got {0}".format(
                (first_version, second_version, third_version)
            )
        )


class TestReplaysAndTheOneLiveAllocationRule:
    """Four refused calls against a healthy, fully-signed allocation."""

    def test_credit_and_delivery_replays_and_the_one_live_allocation_rule(self, api):
        """Two replayed triggers and two second live allocations, each refused in its own code.

        All four refusals share one structural cause — the trigger has no outgoing
        transition, or the slot is already occupied — yet each reports the code of its own
        entity rather than a single generic conflict. The replayed issuance carries a
        different certificate number precisely so that its payload can be shown not to
        leak: the original Form 8609 number survives untouched. The one-live rule is
        probed on both endpoints that carry it, the credit allocation sitting in `ISSUED`
        and the cap allocation sitting in `COMMITTED`.

        PRD: "The state tables in §3 govern: the subject's current state must have an outgoing transition for the trigger being invoked."
        PRD: "There is no idempotent replay anywhere in this domain: repeating a trigger that already fired hits this rule."
        PRD: "Accepting a delivery that has already been rescinded, or accepting twice, is `ERR_DELIVERY_STATE_INVALID`."
        PRD: "A development may hold at most one cap allocation in `PENDING`, `AWARDED` or `COMMITTED` at any one time, and a second live request is `ERR_ALLOCATION_ALREADY_EXISTS`."

        Design: Corner/errors/credit_and_delivery_replays_and_the_one_live_allocation_rule
        """
        deal = fixtures.setup_accepted_delivery(api)
        assert_fields(
            fixtures.read_credit_allocation(api, deal),
            "credit_allocation",
            status="ISSUED",
            form_8609_number=constants.FORM_8609_NUMBER,
        )
        first_accepted_at = deal.delivery["accepted_at"]

        validate_error(
            api.issue_credit_allocation(
                deal.credit_allocation_id,
                THIRD_ALLOCATION_OFFICER,
                form_8609_number="8609-2026-9999",
            ),
            ApiErrorId.ERR_CREDIT_ALLOCATION_STATE_INVALID,
            409,
        )
        assert_fields(
            fixtures.read_credit_allocation(api, deal),
            "credit_allocation",
            form_8609_number=constants.FORM_8609_NUMBER,
        )

        validate_error(
            api.accept_investor_delivery(deal.delivery_id, deal.investor_headers),
            ApiErrorId.ERR_DELIVERY_STATE_INVALID,
            409,
        )
        assert_fields(
            fixtures.read_delivery(api, deal),
            "delivery",
            status="ACCEPTED",
            accepted_at=first_accepted_at,
        )

        validate_error(
            api.create_credit_allocation(
                THIRD_ALLOCATION_OFFICER,
                **factories.credit_allocation_payload(
                    deal.project_id, deal.cost_certification_id
                )
            ),
            ApiErrorId.ERR_ALLOCATION_ALREADY_EXISTS,
            409,
        )
        validate_error(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    deal.project_id,
                    deal.pool_id,
                    requested_amount_cents=50000000,
                    requested_closing_date="2027-01-15T00:00:00Z",
                )
            ),
            ApiErrorId.ERR_ALLOCATION_ALREADY_EXISTS,
            409,
        )

        assert_page(
            api.list_credit_allocations(
                ALLOCATION_OFFICER, project_id=deal.project_id
            ),
            total_count=1,
        )
        assert_page(
            api.list_volume_cap_allocations(
                ALLOCATION_OFFICER, project_id=deal.project_id
            ),
            total_count=1,
        )
        assert_pool_ledger(fixtures.read_pool(api, deal), reserved_cents=0)
        assert_fields(
            fixtures.read_credit_allocation(api, deal),
            "credit_allocation",
            delivered_credit_cents=30000000,
            undelivered_credit_cents=41000000,
        )
        assert_fields(
            fixtures.read_investor(api, deal),
            "investor",
            total_credit_accepted_cents=30000000,
        )


class TestTheAllocationVersionToken:
    """The token that keeps the waterfall clamp from moving under a priced strip."""

    def test_a_stale_allocation_version_refuses_the_second_delivery_and_the_refreshed_token_passes(
        self, api
    ):
        """One token read before the first strip, reused after that strip was accepted.

        The token goes stale because two different actors in two different roles moved the
        allocation: the sponsor created the first strip and the investor accepted it. The
        20,000,000 the second strip asks for still fits inside the 41,000,000 that is left,
        so nothing about the amount is wrong — only the version is — and the refusal has to
        be the precondition failure rather than a silent clamp to a smaller strip than the
        syndication agreement priced. The investor's own running total is the proof that
        nothing leaked through the refusal.

        PRD: "Creating a credit delivery — `POST /investor-deliveries` — must carry `expected_credit_allocation_version` matching the current `version` of the target `CreditAllocation`. A delivery is sized against the undelivered credit the syndicator observed; if another delivery or a rescission has since moved `undelivered_credit_cents`, the allocation's `version` has advanced and the waterfall clamp described in §3.8 would silently deliver a different amount than the syndication agreement priced. Such a request is rejected with `ERR_STALE_CREDIT_ALLOCATION_VERSION` (HTTP 412). The read that supplies this value is the single-credit-allocation fetch."
        PRD: "This is checked *after* existence but *before* any state or business rule, so a stale version wins over a wrong-state parent."

        Design: Corner/cross_cutting_complexity_layers/stale_credit_allocation_version_on_a_second_delivery_is_precondition_failed_after_the_first_is_accepted
        """
        deal = fixtures.setup_issued_credit_allocation(api)
        token = fixtures.credit_allocation_version(api, deal)

        fixtures.deliver_credit(api, deal)
        accepted = fixtures.accept_delivery(api, deal)
        assert_fields(
            accepted,
            "first_strip",
            status="ACCEPTED",
            delivered_credit_cents=30000000,
            price_per_credit_dollar_bps=8500,
        )

        validate_error(
            api.create_investor_delivery(
                deal.developer_headers,
                credit_allocation_id=deal.credit_allocation_id,
                investor_id=deal.investor_id,
                requested_credit_cents=20000000,
                capital_contribution_cents=17000000,
                expected_credit_allocation_version=token,
            ),
            ApiErrorId.ERR_STALE_CREDIT_ALLOCATION_VERSION,
            412,
        )

        refreshed = fixtures.read_credit_allocation(api, deal)
        assert_fields(
            refreshed, "credit_allocation", undelivered_credit_cents=41000000
        )
        assert refreshed["version"] > token, (
            "the first strip should have advanced the allocation past {0}, got {1}".format(
                token, refreshed["version"]
            )
        )
        assert_page(
            api.list_investor_deliveries(
                deal.developer_headers, credit_allocation_id=deal.credit_allocation_id
            ),
            total_count=1,
        )
        assert_fields(
            fixtures.read_investor(api, deal),
            "investor",
            total_credit_accepted_cents=30000000,
        )

        second = fixtures.deliver_credit(
            api,
            deal,
            requested_credit_cents=20000000,
            capital_contribution_cents=17000000,
        )
        assert_fields(
            second,
            "second_strip",
            status="DELIVERED",
            delivered_credit_cents=20000000,
            price_per_credit_dollar_bps=8500,
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=50000000,
            undelivered_credit_cents=21000000,
        )


class TestTheWaterfall:
    """Three strips against one allocation: exact, to the penny, and an over-ask."""

    def test_the_waterfall_fills_exactly_then_to_the_penny_then_clamps_an_over_ask(
        self, api
    ):
        """The ten-unit development's 55,964,710 of credit, subscribed three different ways.

        Its four restricted units of 700, 800, 900 and 950 square feet against 8,500
        total square feet floor to 29,235,294, 33,411,764, 37,588,235 and 39,676,470, a
        qualified basis of 139,911,763, an annual credit of 5,596,471 after the half-up
        rounding, and ten years of 55,964,710. Strip A takes 20,000,000 out of the full
        remainder. Strip B asks for exactly what is left and drives the remainder to zero
        on the penny. Rescinding strip A puts its 20,000,000 back, and strip C then asks
        for 25,000,000 against that 20,000,000 — which is not an error but a clamp, and
        the clamp reprices the same 17,500,000 of equity from 8,500 to 8,750 basis points
        a credit dollar.

        PRD: "For each such unit, the certification's `certified_eligible_basis_cents` is multiplied by that unit's `floor_space_sqft`, divided by the development's `total_floor_space_sqft`, and **floored to whole cents for that unit**; `qualified_basis_cents` is the sum of those already-floored per-unit figures."
        PRD: "A positive but insufficient remainder is emphatically **not** an error: `delivered_credit_cents` is the smaller of the requested credit and the remainder, so an over-ask is clamped down rather than rejected, and the last delivery that fits absorbs whatever is left. The `price_per_credit_dollar_bps` is then the `capital_contribution_cents` multiplied by 10,000, divided by the clamped `delivered_credit_cents`, floored — which is precisely why a stale allocation version is refused rather than re-priced."
        PRD: "The undelivered remainder is computed as the allocation's `total_credit_cents` less the summed `delivered_credit_cents` of its deliveries whose `status` is `DELIVERED`, `ACCEPTED` or `RECAPTURE_FLAGGED`; deliveries that reached `RESCINDED` are excluded and their credit is back in the pool."

        Design: Difficulty/combinatorial_formula/credit_delivery_waterfall_fills_exactly_then_to_the_penny_then_clamps_an_over_ask
        """
        deal = fixtures.ten_unit_deal(
            api, stage=fixtures.setup_issued_credit_allocation
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            status="ISSUED",
            qualified_basis_cents=139911763,
            annual_credit_cents=5596471,
            total_credit_cents=55964710,
            undelivered_credit_cents=55964710,
        )

        strip_a = fixtures.deliver_credit(
            api,
            deal,
            requested_credit_cents=20000000,
            capital_contribution_cents=17000000,
        )
        assert_fields(
            strip_a,
            "strip_a",
            delivered_credit_cents=20000000,
            price_per_credit_dollar_bps=8500,
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=20000000,
            undelivered_credit_cents=35964710,
        )

        strip_b = fixtures.deliver_credit(
            api,
            deal,
            requested_credit_cents=35964710,
            capital_contribution_cents=30570004,
        )
        assert_fields(
            strip_b,
            "strip_b",
            delivered_credit_cents=35964710,
            price_per_credit_dollar_bps=8500,
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=55964710,
            undelivered_credit_cents=0,
        )

        rescinded = fixtures.rescind_delivery(
            api, deal, index=0, rescind_reason="Fund A withdrew from the syndication"
        )
        assert_fields(rescinded, "strip_a", status="RESCINDED")
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=35964710,
            undelivered_credit_cents=20000000,
        )

        strip_c = fixtures.deliver_credit(
            api,
            deal,
            requested_credit_cents=25000000,
            capital_contribution_cents=17500000,
        )
        assert_fields(
            strip_c,
            "strip_c",
            status="DELIVERED",
            requested_credit_cents=25000000,
            delivered_credit_cents=20000000,
            price_per_credit_dollar_bps=8750,
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            delivered_credit_cents=55964710,
            undelivered_credit_cents=0,
        )


class TestSigningFormEightSixZeroNine:
    """One role, three identities, and only one of them may sign."""

    def test_issuance_is_refused_for_the_awarding_officer_and_the_reviewing_officer_but_clears_for_a_third(
        self, api
    ):
        """The same allocation offered to three officers of the same role in turn.

        All three carry `HfaAllocationOfficer`, so the role check passes every time and
        only the acting identity separates a legal signature from an illegal one. Both
        blocked identities have to be probed separately: comparing against the cap award
        alone would let the officer who accepted the cost certification sign, and
        comparing against the certification alone would let the officer who awarded the
        cap sign. Both refusals are the identity failure rather than a state conflict,
        because `PENDING` is exactly the state that admits the trigger.

        PRD: "The allocation officer who decided a development's cap award is recorded on that allocation as `decided_by_user_id`, and the officer who accepted its cost certification is recorded as `reviewed_by_user_id`; the officer who creates the final credit allocation is recorded as `issued_by_user_id`. At the moment the allocation certificate is issued, the acting `X-User-ID` is compared against both recorded reviewers and must differ from each of them."
        PRD: "The `X-User-ID` issuing the allocation certificate must differ from the `decided_by_user_id` recorded on the development's awarded cap allocation, and must also differ from the `reviewed_by_user_id` recorded on the referenced cost certification. Violation on `POST /credit-allocations/{id}/issue` is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "Issuance moves the allocation `PENDING` → `ISSUED`, stamps `form_8609_number`, stamps `issued_by_user_id` from the acting `X-User-ID` and increments the allocation's `version` by 1."

        Design: Corner/rbac/form_8609_issuance_is_refused_for_the_awarding_officer_and_for_the_reviewing_officer_but_clears_for_a_third
        """
        deal = fixtures.setup_credit_allocation(api)
        assert_fields(
            fixtures.read_allocation(api, deal),
            "cap_allocation",
            decided_by_user_id=ALLOCATION_OFFICER_USER_ID,
        )
        assert_fields(
            deal.cost_certification,
            "cost_certification",
            reviewed_by_user_id=SECOND_ALLOCATION_OFFICER_USER_ID,
        )

        validate_error(
            api.issue_credit_allocation(
                deal.credit_allocation_id,
                ALLOCATION_OFFICER,
                form_8609_number=constants.FORM_8609_NUMBER,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.issue_credit_allocation(
                deal.credit_allocation_id,
                SECOND_ALLOCATION_OFFICER,
                form_8609_number=constants.FORM_8609_NUMBER,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        refused = fixtures.read_credit_allocation(api, deal)
        assert_fields(refused, "credit_allocation", status="PENDING")
        assert_nulls(refused, ("form_8609_number",), "credit_allocation")

        issued = validate_success(
            api.issue_credit_allocation(
                deal.credit_allocation_id,
                THIRD_ALLOCATION_OFFICER,
                form_8609_number=constants.FORM_8609_NUMBER,
            )
        )
        assert_fields(
            issued,
            "credit_allocation",
            status="ISSUED",
            form_8609_number=constants.FORM_8609_NUMBER,
            issued_by_user_id=THIRD_ALLOCATION_OFFICER_USER_ID,
            annual_credit_cents=7100000,
            total_credit_cents=71000000,
        )
