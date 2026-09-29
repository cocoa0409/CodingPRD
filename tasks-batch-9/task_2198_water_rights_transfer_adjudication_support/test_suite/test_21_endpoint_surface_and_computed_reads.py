"""The shape of the endpoint surface: narrow updates, compound gates, pure reads.

PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
will return the created or updated resource object in the data field."

PRD §2.11: "The first violated rule wins, its error is returned, and no later rule
is evaluated — so a request that breaks three rules at once produces exactly one,
fully determined error code."
"""
import pytest
from test_helpers import (
    ANALYST_USER_ID,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_request_meta,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    condition_entry,
    create_claimant_payload,
    create_decree_docket_payload,
    create_deposit_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    activate_right,
    add_point_of_diversion,
    add_use_record,
    certify_study,
    conditions_of,
    create_study,
    create_water_right,
    decide,
    examine_claim,
    file_claim,
    open_account,
    open_docket,
    read_account,
    read_application,
    read_claim,
    read_claimant,
    read_condition,
    read_docket,
    read_right,
    reserve_lease,
    set_clock,
    setup_application_ready_for_decision,
    setup_authorized_headgate_account,
    setup_base_right,
    setup_documented_right,
)

CLOCK = "2026-03-01T00:00:00Z"
FILING_DEADLINE = "2026-04-01T00:00:00Z"
DEADLINE_REACHED = "2026-04-02T00:00:00Z"
RECORDED_PRIORITY = "1901-05-01T00:00:00Z"


def _advance(docket_id, target_phase):
    return api_client.advance_docket_phase(docket_id, target_phase, ADJUDICATOR)


def _assessment(right_id):
    return get_success_data(api_client.get_forfeiture_assessment(right_id, ANALYST))


class TestTheClaimantSurfaceIsCreateReadAndOneNarrowPatch:
    """PRD §3.1 — the party of record can be registered, read and sanctioned.

    Nothing else: the only mutation the API offers on a claimant is the single
    field the basin adjudicator may set, and the two counters that do move are
    derived rather than written.
    """

    PAYLOAD = create_claimant_payload(
        legal_name="Vega Ditch Company",
        contact_email="ops@vega.example",
        entity_type="IRRIGATION_DISTRICT",
    )

    def test_registration_answers_with_the_whole_row_and_its_defaults(self):
        """PRD §3.1: "A newly registered claimant begins with `standing_status` set to
        `IN_GOOD_STANDING`, an `outstanding_fee_balance_usd` of 0.00 and an
        `open_application_count` of 0."

        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources." PRD §2.5 pins the version: it "begins at 1
        on creation and increments by exactly 1 on each mutation of that row."

        Design: Corner/endpoints/ep_standard_crud_claimant_create_read_and_narrow_update
        """
        set_clock(CLOCK)

        response = api_client.create_claimant(dict(self.PAYLOAD), ANALYST)

        body = response.json()
        assert response.status_code == 201
        assert body["response_type"] == "object"
        assert_request_meta(body)
        claimant = body["data"]
        assert claimant["legal_name"] == "Vega Ditch Company"
        assert claimant["contact_email"] == "ops@vega.example"
        assert claimant["entity_type"] == "IRRIGATION_DISTRICT"
        assert claimant["standing_status"] == "IN_GOOD_STANDING"
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert claimant["open_application_count"] == 0
        assert claimant["version"] == 1
        assert claimant["id"]
        assert claimant["created_at"]
        assert claimant["updated_at"]

    def test_reading_the_row_back_moves_nothing_at_all(self):
        """PRD §2.5: "`version` ... begins at 1 on creation and increments by exactly 1
        on each mutation of that row."

        A read is not a mutation, so the retrieved row is the registration response
        field for field — including the version.

        Design: Corner/endpoints/ep_standard_crud_claimant_create_read_and_narrow_update
        """
        set_clock(CLOCK)
        created = get_success_data(
            api_client.create_claimant(dict(self.PAYLOAD), ANALYST), 201
        )

        response = api_client.get_claimant(created["id"], ADJUDICATOR)

        body = response.json()
        assert response.status_code == 200
        assert body["response_type"] == "object"
        assert_request_meta(body)
        assert body["data"] == created
        assert body["data"]["version"] == 1

    def test_standing_is_the_only_field_a_caller_can_move(self):
        """PRD §3.1: "Only the basin adjudicator may set `standing_status` directly,
        supplying one of `IN_GOOD_STANDING`, `DELINQUENT` or `BARRED`." And: "Setting
        standing bumps the claimant's `version`".

        The patch is narrow in both senses — one field of one row — and an
        identifier that resolves to nothing is PRD §2.6's `ERR_CLAIMANT_NOT_FOUND`
        rather than a permission or validation failure.

        Design: Corner/endpoints/ep_standard_crud_claimant_create_read_and_narrow_update
        """
        set_clock(CLOCK)
        created = get_success_data(
            api_client.create_claimant(dict(self.PAYLOAD), ANALYST), 201
        )

        patched = get_success_data(
            api_client.set_claimant_standing(created["id"], "DELINQUENT", ADJUDICATOR)
        )

        assert patched["standing_status"] == "DELINQUENT"
        assert patched["version"] == 2
        for field in ("id", "legal_name", "contact_email", "entity_type"):
            assert patched[field] == created[field]
        assert patched["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert patched["open_application_count"] == 0
        missing = api_client.get_claimant(NON_EXISTENT_UUID, ANALYST)
        validate_error(missing, ApiErrorId.ERR_CLAIMANT_NOT_FOUND, expected_status=404)
        assert missing.json()["response_type"] == "error"
        assert_request_meta(missing.json())


class TestOneAdvanceEndpointCarriesThreeDifferentChildGates:
    """PRD §3.10 — the same call is gated on a different property of the children
    at every phase, and one reachable phase is a dead end.

    Two dockets share a filing deadline. One took a single claim before the
    deadline and one took none, and the clock is then moved past the deadline so
    the temporal half of the compound gate is satisfied for both.
    """

    EMPTY_DOCKET_NUMBER = "SNK-ADJ-07"

    def _two_dockets(self):
        bundle = setup_documented_right(CLOCK)
        bundle["with_claim"] = open_docket(FILING_DEADLINE, docket_number="SNK-ADJ-06")
        bundle["empty"] = get_success_data(
            api_client.create_decree_docket(
                create_decree_docket_payload(
                    FILING_DEADLINE, docket_number=self.EMPTY_DOCKET_NUMBER
                ),
                ADJUDICATOR,
            ),
            201,
        )
        bundle["claim"] = file_claim(
            bundle["with_claim"]["id"],
            bundle["right"]["id"],
            RECORDED_PRIORITY,
            100.00,
        )
        set_clock(DEADLINE_REACHED)
        return bundle

    def test_a_docket_that_took_no_claims_can_never_leave_the_filing_phase(self):
        """PRD §3.10: "Advancing to `EXAMINATION` requires two things at once: the
        logical clock must have reached `claim_filing_deadline`, a temporal failure
        reported as `ERR_WINDOW_STILL_OPEN` (409), and the docket must hold at least
        one claim, a child-population failure reported as
        `ERR_DOCKET_CHILDREN_NOT_READY` (422)."

        The clock has passed the deadline, so the temporal half is satisfied and the
        child-population half is what fires. PRD §3.10: "A docket with zero claims can
        never leave `OPEN_FOR_CLAIMS` at all." — and filing into it is now closed for
        good, so the phase is terminal in practice.

        Design: Corner/endpoints/ep_action_endpoint_docket_advance_enforces_the_compound_child_gate
        """
        bundle = self._two_dockets()
        before = read_docket(bundle["empty"]["id"])

        response = _advance(bundle["empty"]["id"], "EXAMINATION")

        validate_error(
            response, ApiErrorId.ERR_DOCKET_CHILDREN_NOT_READY, expected_status=422
        )
        empty = read_docket(bundle["empty"]["id"])
        assert empty["phase"] == "OPEN_FOR_CLAIMS"
        assert empty["claim_count"] == 0
        assert empty["version"] == before["version"]

    def test_the_examination_gate_counts_children_and_the_next_gate_reads_them(self):
        """PRD §3.10: "Advancing to `OBJECTION_PERIOD` requires every claim on the
        docket to have left `FILED`, meaning each one reads `EXAMINED`, `OBJECTED` or
        `DECREED`."

        The population gate is satisfied by the one claim, so `EXAMINATION` is
        reached; the very next advance is refused because that claim has not been
        examined yet, and the identical call succeeds once it has. The gate is over
        child state, not over the caller.

        Design: Corner/endpoints/ep_action_endpoint_docket_advance_enforces_the_compound_child_gate
        """
        bundle = self._two_dockets()

        examination = get_success_data(_advance(bundle["with_claim"]["id"], "EXAMINATION"))

        assert examination["phase"] == "EXAMINATION"
        assert examination["claim_count"] == 1
        assert examination["version"] > bundle["with_claim"]["version"]
        assert examination["docket_number"] == "SNK-ADJ-06"
        premature = _advance(bundle["with_claim"]["id"], "OBJECTION_PERIOD")
        validate_error(
            premature, ApiErrorId.ERR_DOCKET_CHILDREN_NOT_READY, expected_status=422
        )
        assert read_docket(bundle["with_claim"]["id"])["phase"] == "EXAMINATION"
        assert read_claim(bundle["claim"]["id"])["filing_status"] == "FILED"
        examine_claim(bundle["claim"]["id"], 100.00)
        advanced = get_success_data(_advance(bundle["with_claim"]["id"], "OBJECTION_PERIOD"))
        assert advanced["phase"] == "OBJECTION_PERIOD"

    def test_skipping_a_phase_is_a_sequencing_failure_not_a_child_failure(self):
        """PRD §3.10: "A `target_phase` that is not the docket's immediate successor is
        `ERR_INVALID_STATE` (409), and `CLOSED` is terminal."

        `CLOSED` sits one phase beyond `DECREE_ENTERED`, so from `OBJECTION_PERIOD` the
        sequencing rule answers first and the child gate — which would also have
        something to say, the claim being merely `EXAMINED` — is never consulted.

        Design: Corner/endpoints/ep_action_endpoint_docket_advance_enforces_the_compound_child_gate
        """
        bundle = self._two_dockets()
        get_success_data(_advance(bundle["with_claim"]["id"], "EXAMINATION"))
        examine_claim(bundle["claim"]["id"], 100.00)
        get_success_data(_advance(bundle["with_claim"]["id"], "OBJECTION_PERIOD"))

        response = _advance(bundle["with_claim"]["id"], "CLOSED")

        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        docket = read_docket(bundle["with_claim"]["id"])
        assert docket["phase"] == "OBJECTION_PERIOD"
        assert docket["claim_count"] == 1
        assert read_claim(bundle["claim"]["id"])["filing_status"] == "EXAMINED"
        assert read_docket(bundle["empty"]["id"])["claim_count"] == 0


class TestTheLeaseJunctionDemandsMutuallyConsistentParents:
    """PRD §3.9 — three foreign keys that all resolve are still not enough.

    One claimant holds two activated rights. The first carries an `AUTHORIZED`
    headgate and funds the bank account; the second carries a headgate registered
    after perfection, so it is still `PROPOSED`. Every parent named below exists.
    """

    WINDOW = ("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z")
    REQUESTED_AF = 20.00

    def _two_rights_and_an_account(self):
        bundle = setup_authorized_headgate_account(deposit_af=90.00, clock=CLOCK)
        second = create_water_right(
            bundle["claimant"]["id"],
            right_number="WR-2198-002",
            bank_enrolled=True,
        )
        add_use_record(
            second["id"],
            2025,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="METER",
        )
        bundle["second_right"] = activate_right(second["id"])
        bundle["proposed_pod"] = add_point_of_diversion(
            second["id"],
            legal_description="SW1/4 NE1/4 Sec 18 T3N R5E",
            stream_reach_code="SNK-14-B",
            stream_miles_from_headwater=18.10,
        )
        return bundle

    def _reserve(self, bundle, right_id, pod_id):
        return reserve_lease(
            bundle["account"]["id"],
            right_id,
            pod_id,
            self.WINDOW[0],
            self.WINDOW[1],
            self.REQUESTED_AF,
        )

    def test_a_headgate_on_another_right_is_caught_before_its_own_status(self):
        """PRD §3.9: "The named headgate must belong to the named right, otherwise
        `ERR_POD_RIGHT_MISMATCH` (422)."

        Naming the funded right together with the other right's headgate fails on the
        relationship, not on the headgate's `PROPOSED` status — which would be the
        later gate. Nothing on the account moves: PRD §3.9 pins the credit movement to
        the successful reservation, where "`committed_credit_af` increases and
        `available_credit_af` decreases by `requested_af`".

        Design: Corner/endpoints/ep_cross_reference_link_lease_binds_account_right_and_headgate
        """
        bundle = self._two_rights_and_an_account()
        assert bundle["pod"]["status"] == "AUTHORIZED"
        assert bundle["proposed_pod"]["status"] == "PROPOSED"

        response = self._reserve(
            bundle, bundle["right"]["id"], bundle["proposed_pod"]["id"]
        )

        validate_error(
            response, ApiErrorId.ERR_POD_RIGHT_MISMATCH, expected_status=422
        )
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["version"] == bundle["account"]["version"]
        leases, meta = validate_paginated(
            api_client.list_lease_assignments(ANALYST, {"water_right_id": bundle["right"]["id"]})
        )
        assert meta["total_count"] == 0
        assert leases == []

    def test_a_related_but_unauthorized_headgate_reaches_the_later_status_gate(self):
        """PRD §3.9: "Finally the headgate's own `status` must be `AUTHORIZED` —
        `PROPOSED` and `RETIRED` headgates take no new leases — otherwise
        `ERR_POD_NOT_AUTHORIZED` (409)".

        Naming the headgate together with the right that actually owns it clears the
        referential rule, so the ladder runs on to the status rule. The right itself
        is in service — PRD §3.9 requires its status to be "`ACTIVE`, `ENCUMBERED` or
        `PARTIALLY_TRANSFERRED`" — so the headgate is the only thing left to object to.

        Design: Corner/endpoints/ep_cross_reference_link_lease_binds_account_right_and_headgate
        """
        bundle = self._two_rights_and_an_account()
        assert bundle["second_right"]["status"] == "ACTIVE"

        response = self._reserve(
            bundle, bundle["second_right"]["id"], bundle["proposed_pod"]["id"]
        )

        validate_error(
            response, ApiErrorId.ERR_POD_NOT_AUTHORIZED, expected_status=409
        )
        account = read_account(bundle["account"]["id"])
        assert account["available_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["version"] == bundle["account"]["version"]

    def test_the_consistent_triple_creates_the_association_and_commits_credit(self):
        """PRD §3.9: "The lease is created in `RESERVED`, `committed_credit_af`
        increases and `available_credit_af` decreases by `requested_af` — the credit
        identity is conserved because the total is merely repartitioned — and the
        posture is recomputed".

        The stored lease echoes all three parents, and PRD §3.9's listing filters find
        it under the right it was written against and nowhere else: "Leases can be
        listed by all five roles with optional filters on `water_bank_account_id`,
        `water_right_id`, `point_of_diversion_id` and `status`, and a single lease can
        be read to inspect its settlement figures and suspension history."

        Design: Corner/endpoints/ep_cross_reference_link_lease_binds_account_right_and_headgate
        """
        bundle = self._two_rights_and_an_account()

        lease = get_success_data(
            self._reserve(bundle, bundle["right"]["id"], bundle["pod"]["id"]), 201
        )

        assert lease["water_bank_account_id"] == bundle["account"]["id"]
        assert lease["water_right_id"] == bundle["right"]["id"]
        assert lease["point_of_diversion_id"] == bundle["pod"]["id"]
        assert lease["status"] == "RESERVED"
        assert lease["requested_af"] == pytest.approx(self.REQUESTED_AF, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["posture"] == "OPEN"
        mine, mine_meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, {"water_right_id": bundle["right"]["id"]}
            )
        )
        assert mine_meta["total_count"] == 1
        assert [row["id"] for row in mine] == [lease["id"]]
        others, others_meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, {"water_right_id": bundle["second_right"]["id"]}
            )
        )
        assert others_meta["total_count"] == 0
        assert others == []


class TestTheForfeitureReadIsAPureFunctionOfTheClock:
    """PRD §3.2 — the record set is frozen and only the clock moves.

    A right authorized at 400.00 AF reported beneficial use in 2017 and 2018 and
    nothing since. Advancing the clock slides the ten-year window forward, which
    lengthens the trailing non-use run and eventually drops the older record out
    of the input set altogether.
    """

    SECOND_CLOCK = "2027-01-01T00:00:00Z"
    THIRD_CLOCK = "2028-01-01T00:00:00Z"

    def _frozen_record_set(self):
        return setup_base_right(clock=CLOCK, use_years=(2017, 2018), activate=False)

    def test_the_first_reading_prices_seven_trailing_years_of_non_use(self):
        """PRD §3.2: "The scoring window is a closed ten-year band ending with the year
        *before* the calendar year of the logical clock, taken in UTC".

        At the 2026 clock the window is 2016 through 2025; 2019 through 2025 is an
        unbroken run of seven non-use years worth 63 points, the two metered records
        keep the unverified ratio at zero and earn the whole credit, and 300.000
        against 400.00 leaves a 7.50 underuse term: 63.00 + 0.00 + 7.50 - 10 = 60.50.

        Design: Corner/endpoints/ep_computed_read_forfeiture_assessment_tracks_the_logical_clock
        """
        bundle = self._frozen_record_set()

        assessment = _assessment(bundle["right"]["id"])

        assert assessment["lookback_start_year"] == 2016
        assert assessment["lookback_end_year"] == 2025
        assert assessment["consecutive_nonuse_years"] == 7
        assert assessment["nonuse_component"] == pytest.approx(63, abs=0.01)
        assert assessment["unverified_component"] == pytest.approx(0.00, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(60.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "ELEVATED"
        assert assessment["forfeiture_eligible"] is True

    def test_two_years_of_clock_carry_the_same_records_into_the_high_band(self):
        """PRD §3.2: "`consecutive_nonuse_years` is the length of the longest unbroken
        run of non-use years inside the window."

        One year of clock adds one non-use year and nine points, taking 60.50 to 69.50
        — half a point short of PRD §3.2's threshold, "a score of 70.00 or above reads
        `HIGH`". A second year adds another nine and pushes 78.50 over it, and it also
        slides the 2017 record out of the window; the mean of the surviving 300.000 AF
        record is unchanged, so the underuse term holds at 7.50 and the surviving
        record still carries the meter credit.

        Design: Corner/endpoints/ep_computed_read_forfeiture_assessment_tracks_the_logical_clock
        """
        bundle = self._frozen_record_set()

        set_clock(self.SECOND_CLOCK)
        second = _assessment(bundle["right"]["id"])
        set_clock(self.THIRD_CLOCK)
        third = _assessment(bundle["right"]["id"])

        assert second["lookback_start_year"] == 2017
        assert second["lookback_end_year"] == 2026
        assert second["consecutive_nonuse_years"] == 8
        assert second["nonuse_component"] == pytest.approx(72, abs=0.01)
        assert second["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert second["forfeiture_risk_score"] == pytest.approx(69.50, abs=0.01)
        assert second["forfeiture_risk_band"] == "ELEVATED"
        assert third["lookback_start_year"] == 2018
        assert third["lookback_end_year"] == 2027
        assert third["consecutive_nonuse_years"] == 9
        assert third["nonuse_component"] == pytest.approx(81, abs=0.01)
        assert third["unverified_component"] == pytest.approx(0.00, abs=0.01)
        assert third["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert third["meter_credit"] == pytest.approx(10, abs=0.01)
        assert third["forfeiture_risk_score"] == pytest.approx(78.50, abs=0.01)
        assert third["forfeiture_risk_band"] == "HIGH"

    def test_the_read_never_writes_the_projection_it_computes(self):
        """PRD §3.2: the assessment endpoint "Returns the recomputed forfeiture score,
        its risk band, the consecutive non-use year count and the statutory eligibility
        flag without persisting anything."

        The right's stored projection is the value stamped when the last record was
        appended — PRD §3.2: "Abandonment risk is scored on demand and after every
        event that could move it — appending a beneficial-use record, perfecting a
        right, reinstating a right, and any movement of the right into or out of
        `SUSPENDED`" — so three reads at three clocks leave both the stored score and
        the row's `version` exactly where the second record left them.

        Design: Corner/endpoints/ep_computed_read_forfeiture_assessment_tracks_the_logical_clock
        """
        bundle = self._frozen_record_set()
        stored_before = read_right(bundle["right"]["id"])

        _assessment(bundle["right"]["id"])
        set_clock(self.SECOND_CLOCK)
        _assessment(bundle["right"]["id"])
        set_clock(self.THIRD_CLOCK)
        _assessment(bundle["right"]["id"])

        stored_after = read_right(bundle["right"]["id"])
        assert stored_before["forfeiture_risk_score"] == pytest.approx(60.50, abs=0.01)
        assert stored_after["forfeiture_risk_score"] == pytest.approx(60.50, abs=0.01)
        assert stored_after["forfeiture_risk_band"] == "ELEVATED"
        assert stored_after["consecutive_nonuse_years"] == 7
        assert stored_after["version"] == stored_before["version"]
        assert stored_after["status"] == "UNADJUDICATED"


class TestPayingIsAdmissibleOnlyWhereAFeeIsActuallyOwed:
    """PRD §3.8 — one decision, two conditions, one of them priced.

    An application for 100.00 AF carries a finalized injury of 20.00 AF, and the
    decision imposes a 20.00 AF mitigation payment alongside a 20.00 AF
    measurement device. Only the first has a fiscal dimension to settle.
    """

    DEADLINE_REACHED = "2026-04-01T00:00:00Z"
    MITIGATION_AF = 20.00

    def _two_conditions(self):
        bundle = setup_application_ready_for_decision(
            requested_af=100.00,
            clock=CLOCK,
            deadline_reached_at=self.DEADLINE_REACHED,
            analysis_overrides={"return_flow_credit_af": 58.00},
        )
        assert bundle["analysis"]["net_injury_af"] == pytest.approx(20.00, abs=0.01)
        bundle["application"] = decide(
            bundle["application"]["id"],
            "APPROVE_WITH_CONDITIONS",
            decision_note="Approved subject to mitigation and measurement.",
            conditions=[
                condition_entry("MITIGATION_PAYMENT", self.MITIGATION_AF),
                condition_entry("MEASUREMENT_DEVICE", self.MITIGATION_AF),
            ],
        )
        rows = conditions_of(bundle["application"]["id"])
        bundle["fee"] = next(
            row for row in rows if row["condition_type"] == "MITIGATION_PAYMENT"
        )
        bundle["device"] = next(
            row for row in rows if row["condition_type"] == "MEASUREMENT_DEVICE"
        )
        bundle["claimant"] = read_claimant(bundle["claimant"]["id"])
        return bundle

    def test_only_the_mitigation_payment_is_priced_and_only_it_is_owed(self):
        """PRD §3.8: "First, `base_fee_usd` is `required_af` multiplied by a base rate
        of 125.00 dollars per acre-foot, rounded to 2 decimal places. Second, the tier
        is selected from that pre-surcharge subtotal and never from the final total: a
        `base_fee_usd` strictly below 5,000.00 dollars takes a `surcharge_pct` of
        0.040".

        20.00 AF prices at 2500.00, which sits in the bottom tier, so the surcharge is
        100.00 and the total 2600.00. PRD §3.8: "it moves to `OUTSTANDING` at the
        moment of creation only when its `condition_type` is `MITIGATION_PAYMENT` and
        its `required_af` is strictly greater than zero." The device condition is
        identical in volume and carries no fee at all.

        Design: Corner/endpoints/ep_conditional_action_fee_payment_only_on_an_outstanding_condition
        """
        bundle = self._two_conditions()

        fee = bundle["fee"]
        assert fee["base_fee_usd"] == pytest.approx(2500.00, abs=0.01)
        assert fee["surcharge_pct"] == pytest.approx(0.040, abs=0.0005)
        assert fee["admin_surcharge_usd"] == pytest.approx(100.00, abs=0.01)
        assert fee["total_fee_usd"] == pytest.approx(2600.00, abs=0.01)
        assert fee["payment_status"] == "OUTSTANDING"
        assert fee["status"] == "IMPOSED"
        device = bundle["device"]
        assert device["payment_status"] == "NOT_APPLICABLE"
        assert device["base_fee_usd"] == pytest.approx(0.00, abs=0.01)
        assert device["admin_surcharge_usd"] == pytest.approx(0.00, abs=0.01)
        assert device["total_fee_usd"] == pytest.approx(0.00, abs=0.01)
        assert bundle["application"]["mitigation_fee_total_usd"] == pytest.approx(
            2600.00, abs=0.01
        )
        assert bundle["claimant"]["standing_status"] == "DELINQUENT"
        assert bundle["claimant"]["outstanding_fee_balance_usd"] == pytest.approx(
            2600.00, abs=0.01
        )

    def test_the_unpriced_condition_refuses_the_identical_payment_call(self):
        """PRD §3.8 — the pay endpoint "Pays a mitigation fee in full, moving the fiscal
        dimension `OUTSTANDING → PAID` and running the four-link fee-payment cascade to
        the claimant's standing and bank postures." `NOT_APPLICABLE` is not
        `OUTSTANDING`, so there is nothing here for that transition to move.

        PRD §2.11 places this in the state family: "the domain-specific referential,
        uniqueness, concurrency, state, safety, temporal, constraint and fiscal
        families in that sequence." The rejected call leaves both dimensions of the
        condition exactly as the decision wrote them.

        Design: Corner/endpoints/ep_conditional_action_fee_payment_only_on_an_outstanding_condition
        """
        bundle = self._two_conditions()

        response = api_client.pay_approval_condition(
            bundle["device"]["id"], ADJUDICATOR
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        device = read_condition(bundle["device"]["id"])
        assert device["payment_status"] == "NOT_APPLICABLE"
        assert device["status"] == "IMPOSED"
        assert device["version"] == bundle["device"]["version"]
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(2600.00, abs=0.01)
        assert claimant["standing_status"] == "DELINQUENT"

    def test_paying_settles_the_fiscal_axis_and_leaves_compliance_untouched(self):
        """PRD §3.8: "The condition's `payment_status` moves `OUTSTANDING → PAID` and
        its `version` is bumped, while `status` stays exactly where it was, because
        paying does not satisfy a condition. The claimant's
        `outstanding_fee_balance_usd` decreases by `total_fee_usd` and the claimant's
        `version` is bumped. When that balance reaches precisely 0.00 and
        `standing_status` reads `DELINQUENT`, standing returns to `IN_GOOD_STANDING`".

        The 2600.00 owed is the whole balance, so the sanction lifts — while the
        measurement device the same decision imposed is still owed on the compliance
        axis.

        Design: Corner/endpoints/ep_conditional_action_fee_payment_only_on_an_outstanding_condition
        """
        bundle = self._two_conditions()

        paid = get_success_data(
            api_client.pay_approval_condition(bundle["fee"]["id"], ADJUDICATOR)
        )

        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "IMPOSED"
        assert paid["total_fee_usd"] == pytest.approx(2600.00, abs=0.01)
        assert paid["version"] == bundle["fee"]["version"] + 1
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert claimant["standing_status"] == "IN_GOOD_STANDING"
        assert claimant["version"] > bundle["claimant"]["version"]
        assert read_condition(bundle["device"]["id"])["status"] == "IMPOSED"
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "APPROVED_WITH_CONDITIONS"
        assert application["mitigation_fee_total_usd"] == pytest.approx(2600.00, abs=0.01)


class TestActionEndpointsAnswerWithTheWholeMutatedRow:
    """PRD §2.2 — no action in this service answers with a bare acknowledgement.

    A bank-enrolled right with three metered years and one registered headgate is
    perfected, quantified, certified and then banked, and every step is read off
    the response body alone.
    """

    DEPOSIT_AF = 90.00

    def _documented_and_banked(self):
        bundle = setup_base_right(
            clock=CLOCK,
            use_years=(2023, 2024, 2025),
            activate=False,
            pod_specs=({},),
            bank_enrolled=True,
        )
        bundle["account"] = open_account(bundle["claimant"]["id"])
        return bundle

    def test_perfecting_a_right_returns_the_recomputed_right_itself(self):
        """PRD §3.2: "Perfecting the right also authorizes its infrastructure: every
        point of diversion on the right still in `PROPOSED` moves to `AUTHORIZED`, each
        such headgate's `version` bumped. The forfeiture assessment is re-run,
        refreshing `forfeiture_risk_score`, `forfeiture_risk_band` and
        `consecutive_nonuse_years`, and the right's own `version` is bumped."

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field." The body
        is a whole `WaterRight` — the recomputed risk figures, the four-bucket ledger
        and the bumped version — not a patch document naming only the new status.

        Design: Corner/endpoints/ep_action_endpoints_return_the_full_mutated_entity_not_a_bare_ack
        """
        bundle = self._documented_and_banked()
        before = read_right(bundle["right"]["id"])

        response = api_client.activate_water_right(bundle["right"]["id"], ANALYST)

        body = response.json()
        assert response.status_code == 200
        assert body["response_type"] == "object"
        assert_request_meta(body)
        right = body["data"]
        assert right["id"] == bundle["right"]["id"]
        assert right["status"] == "ACTIVE"
        assert right["version"] > before["version"]
        assert right["forfeiture_risk_band"] in ("LOW", "ELEVATED", "HIGH")
        assert isinstance(right["forfeiture_risk_score"], (int, float))
        assert right["consecutive_nonuse_years"] == 7
        assert right["certified_hcu_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(0.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)

    def test_quantifying_creates_a_row_and_certifying_returns_that_row_complete(self):
        """PRD §3.3: "On success the study moves `DRAFT → CERTIFIED`,
        `certified_by_user_id` is stamped with the calling operator identifier and
        `certified_at` with the logical clock, and the study's `version` is bumped."

        The study creation is a new resource and answers 201; the certification mutates
        that resource and answers 200 with the whole study, including the certifier
        identity that PRD §2.12 later reads back. PRD §3.3: "The right's
        `certified_hcu_af` is overwritten with the newly certified study's
        `transferable_cu_af`".

        Design: Corner/endpoints/ep_action_endpoints_return_the_full_mutated_entity_not_a_bare_ack
        """
        bundle = self._documented_and_banked()
        activate_right(bundle["right"]["id"])

        created = create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED")

        assert created.status_code == 201
        study = created.json()["data"]
        assert study["status"] == "DRAFT"
        assert study["transferable_cu_af"] == pytest.approx(195.00, abs=0.01)
        response = api_client.certify_hcu_study(
            study["id"], read_right(bundle["right"]["id"])["version"], ANALYST
        )
        body = response.json()
        assert response.status_code == 200
        assert body["response_type"] == "object"
        assert_request_meta(body)
        certified = body["data"]
        assert certified["id"] == study["id"]
        assert certified["status"] == "CERTIFIED"
        assert certified["method"] == "DIVERSION_BASED"
        assert certified["transferable_cu_af"] == pytest.approx(195.00, abs=0.01)
        assert certified["certified_by_user_id"] == ANALYST_USER_ID
        assert certified["certified_at"]
        assert certified["version"] > study["version"]
        assert read_right(bundle["right"]["id"])["certified_hcu_af"] == pytest.approx(
            195.00, abs=0.01
        )

    def test_the_deposit_answers_with_the_account_it_credited(self):
        """PRD §3.9: "On success `deposited_credit_af` and `available_credit_af` both
        increase by `deposit_af`, which conserves the credit identity because the
        deposit lands in the unencumbered bucket".

        The credited resource is the account, and that is what comes back, because PRD
        §3.9 is explicit that "There is no standalone deposit entity — the volume is
        recorded directly on both ledgers" — so PRD §2.2's "operations that create or
        modify a resource will return the created or updated resource object in the
        data field" can only resolve to the `WaterBankAccount`.

        Design: Corner/endpoints/ep_action_endpoints_return_the_full_mutated_entity_not_a_bare_ack
        """
        bundle = self._documented_and_banked()
        activate_right(bundle["right"]["id"])
        study = get_success_data(
            create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED"), 201
        )
        certify_study(study["id"], bundle["right"]["id"])

        response = api_client.create_deposit(
            bundle["account"]["id"],
            create_deposit_payload(
                bundle["right"]["id"],
                self.DEPOSIT_AF,
                read_account(bundle["account"]["id"])["version"],
            ),
            ANALYST,
        )

        body = response.json()
        assert response.status_code == 200
        assert body["response_type"] == "object"
        assert_request_meta(body)
        account = body["data"]
        assert account["id"] == bundle["account"]["id"]
        assert account["claimant_id"] == bundle["claimant"]["id"]
        assert account["deposited_credit_af"] == pytest.approx(self.DEPOSIT_AF, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(self.DEPOSIT_AF, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["posture"] == "OPEN"
        assert account["version"] > bundle["account"]["version"]
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(105.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(self.DEPOSIT_AF, abs=0.01)
