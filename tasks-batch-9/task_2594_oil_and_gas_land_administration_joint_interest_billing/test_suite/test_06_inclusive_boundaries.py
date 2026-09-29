"""Deadlines, coverage tests, cardinalities and thresholds evaluated on their exact edge."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures


def test_the_primary_term_survives_its_last_day_and_fails_the_next_morning(api):
    """The same well and the same leases, evaluated one day apart, give opposite answers.

    Every survival comparison against the logical clock date is inclusive: the primary term survives while the clock date is on or before `primary_term_end_date`; a shut-in holding survives while at least one payment has been made and the clock date is on or before `shut_in_next_due_date`; a continuous-development holding survives while the clock date is on or before `continuous_dev_deadline`.
    A lease whose deadline falls exactly on the clock date is still held, and fails only on the following day.

    Design: Difficulty/boundary_precision_check/primary_term_expiry_is_inclusive_on_the_deadline_day
    """
    context = fixtures.setup_pooled_producing_well(
        api, clock="2026-09-30T00:00:00Z", produce=False
    )
    lease1_id = context["lease1_id"]

    deadline_day = fixtures.run_obligation_pass(api)
    assert deadline_day["leases_expired"] == 0
    assert deadline_day["allocations_withdrawn"] == 0
    assert deadline_day["leases_flagged_obligation_due"] == 0

    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["tenure_status"] == "PRIMARY_TERM"
    assert lease["obligation_status"] == "COMPLIANT"
    assert lease["held_acres"] == 480.00
    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["pooling_status"] == "POOLED_EFFECTIVE"

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    next_day = fixtures.run_obligation_pass(api)
    assert next_day["leases_expired"] == 1
    assert next_day["allocations_withdrawn"] == 1
    assert next_day["revenues_suspended"] == 0
    assert next_day["disbursements_suspended"] == 0

    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["tenure_status"] == "EXPIRED"
    assert lease["obligation_status"] == "IN_BREACH"
    assert lease["held_acres"] == 0

    withdrawn = validate_success(
        api.get_lease_allocation(context["alloc1_id"], fixtures.LAND_ADMIN), 200
    )
    assert withdrawn["allocation_status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "LEASE_EXPIRED"
    survivor = validate_success(
        api.get_lease_allocation(context["alloc2_id"], fixtures.LAND_ADMIN), 200
    )
    assert survivor["allocation_factor"] == 1.000000

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["pooling_status"] == "POOLED_TERMINATED"

    other = validate_success(api.get_lease(context["lease2_id"], fixtures.LAND_ADMIN), 200)
    assert other["tenure_status"] == "PRIMARY_TERM"


def test_a_grantee_posted_at_exactly_the_required_bond_closes(api):
    """One cent short is refused; the exact figure conveys the interest.

    Those rounded per-well amounts are then summed, the sum is multiplied by a coverage factor of 1.25 — the joint operating agreement requires 125% of estimated exposure, not merely 100% — and that product is rounded half up once more to produce `required_bond_cents`.
    And last of all, the grantee's `bond_posted_cents` must be at least its `bond_check_required_cents`, else `ERR_INSUFFICIENT_BOND` with status 402; the coverage test is inclusive, so a grantee posted at exactly the required figure closes.

    Design: Difficulty/boundary_precision_check/bond_coverage_equality_closes_the_assignment
    """
    context = fixtures.setup_assignment_notice(
        api,
        clock="2026-08-05T00:00:00Z",
        assignor="operator_id",
        assignee="partner_c_id",
        transfer_wi_pct=0.1,
        transfer_nri_pct=0.08,
        sale_price_cents=4_000_000,
        notice_date="2026-08-01",
        effective_date="2026-08-05",
    )
    transfer_id = context["transfer_id"]
    grantee_id = context["partner_c_id"]

    fixtures.submit_ppr(api, transfer_id, context["partner_a_headers"], "WAIVE")

    validate_success(
        api.update_owner_compliance(
            grantee_id,
            factories.compliance_update_payload(bond_posted_cents=1_862_499),
            fixtures.COMPLIANCE_OFFICER,
        ),
        200,
    )

    before = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert before["bond_check_required_cents"] == 1_862_500

    validate_error(
        api.close_assignment_transfer(
            transfer_id,
            factories.transfer_closing_payload("2026-08-05"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_INSUFFICIENT_BOND",
        402,
    )
    unchanged = validate_success(
        api.get_assignment_transfer(transfer_id, fixtures.LAND_ADMIN), 200
    )
    assert unchanged["transfer_status"] == "PPR_WAIVED"

    validate_success(
        api.update_owner_compliance(
            grantee_id,
            factories.compliance_update_payload(bond_posted_cents=1_862_500),
            fixtures.COMPLIANCE_OFFICER,
        ),
        200,
    )
    closed = validate_success(
        api.close_assignment_transfer(
            transfer_id,
            factories.transfer_closing_payload("2026-08-05"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    assert closed["transfer_status"] == "CLOSED"
    assert closed["effective_date"] == "2026-08-05"

    rows = fixtures.active_interests(api, context["well_id"])
    grantee_rows = [r for r in rows if r["owner_id"] == grantee_id]
    assert len(grantee_rows) == 1
    assert grantee_rows[0]["working_interest_pct"] == 0.100000
    assert grantee_rows[0]["net_revenue_interest_pct"] == 0.080000
    assignor_rows = [r for r in rows if r["owner_id"] == context["operator_id"]]
    assert len(assignor_rows) == 1
    assert assignor_rows[0]["working_interest_pct"] == 0.400000
    assert assignor_rows[0]["net_revenue_interest_pct"] == 0.332500

    assert (
        validate_success(api.get_interest_owner(grantee_id, fixtures.LAND_ADMIN), 200)[
            "required_bond_cents"
        ]
        == 1_862_500
    )
    assert (
        validate_success(
            api.get_interest_owner(context["operator_id"], fixtures.LAND_ADMIN), 200
        )["required_bond_cents"]
        == 7_450_000
    )


def test_a_notice_with_nobody_to_pre_empt_is_waived_at_creation(api):
    """An empty candidate pool short-circuits the election window instead of stalling the notice.

    `ppr_eligible_count` is snapshotted as the number of `ACTIVE` positions on the well whose `preferential_right` is true and whose owner is neither `assignor_owner_id` nor `assignee_owner_id`: the seller obviously does not get to pre-empt itself, and a named assignee that already holds a preferential right is buying anyway.
    `transfer_status` is `NOTICED` — except in the empty-candidate-pool case: when `ppr_eligible_count` is 0 there is nobody to elect, and the transfer is created directly in `PPR_WAIVED`, ready to close.

    Design: Difficulty/boundary_precision_check/zero_eligible_preferential_holders_waives_the_notice_immediately
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-05T00:00:00Z")
    well_id = context["well_id"]

    empty = validate_success(
        api.create_assignment_transfer(
            well_id,
            factories.create_assignment_transfer_payload(
                assignor_owner_id=context["operator_id"],
                assignee_owner_id=context["partner_a_id"],
                transfer_wi_pct=0.1,
                transfer_nri_pct=0.08,
                sale_price_cents=4_000_000,
                notice_date="2026-08-01",
                effective_date="2026-08-05",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    assert empty["ppr_eligible_count"] == 0
    assert empty["transfer_status"] == "PPR_WAIVED"
    assert empty["ppr_waiver_count"] == 0
    assert empty["ppr_holder_owner_id"] is None
    assert empty["ppr_deadline_date"] == "2026-08-31"
    assert empty["bond_check_required_cents"] == 7_450_000

    contested = validate_success(
        api.create_assignment_transfer(
            well_id,
            factories.create_assignment_transfer_payload(
                assignor_owner_id=context["partner_b_id"],
                assignee_owner_id=context["partner_c_id"],
                transfer_wi_pct=0.1,
                transfer_nri_pct=0.08,
                sale_price_cents=3_000_000,
                notice_date="2026-08-01",
                effective_date="2026-08-05",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    assert contested["ppr_eligible_count"] == 2
    assert contested["transfer_status"] == "NOTICED"
    assert contested["bond_check_required_cents"] == 1_862_500

    closed = validate_success(
        api.close_assignment_transfer(
            empty["id"],
            factories.transfer_closing_payload("2026-08-05"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    assert closed["transfer_status"] == "CLOSED"

    rows = fixtures.active_interests(api, well_id)
    grantee_rows = [r for r in rows if r["owner_id"] == context["partner_a_id"]]
    assert len(grantee_rows) == 1
    assert grantee_rows[0]["working_interest_pct"] == 0.400000
    assignor_rows = [r for r in rows if r["owner_id"] == context["operator_id"]]
    assert len(assignor_rows) == 1
    assert assignor_rows[0]["working_interest_pct"] == 0.400000


def test_a_tally_equal_to_the_threshold_proceeds_while_one_notch_higher_fails(api):
    """Two authorizations get identical elections; only the threshold differs, and the side effects diverge completely.

    A tally that is at least `minimum_consent_pct` but strictly below 1.000000 closes it as `PARTIALLY_CONSENTED` — the threshold comparison is inclusive, so a tally exactly equal to `minimum_consent_pct` is a partial consent and not a failure.
    A tally strictly below `minimum_consent_pct` closes it as `FAILED`.

    Design: Difficulty/boundary_precision_check/minimum_consent_threshold_is_inclusive_at_closure
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-10T00:00:00Z")
    well_id = context["well_id"]

    afe_a = fixtures.raise_afe(
        api,
        well_id,
        afe_number="AFE-2026-A",
        operation_type="RECOMPLETION",
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.8,
    )
    afe_b = fixtures.raise_afe(
        api,
        well_id,
        afe_number="AFE-2026-B",
        operation_type="RECOMPLETION",
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.800001,
    )

    fixtures.submit_election(
        api, afe_a["id"], context["partner_a_id"], "CONSENT",
        headers=context["partner_a_headers"],
    )
    refusal_on_a = fixtures.submit_election(
        api, afe_a["id"], context["partner_b_id"], "NON_CONSENT",
        headers=context["partner_b_headers"],
    )
    consent_on_b = fixtures.submit_election(
        api, afe_b["id"], context["partner_a_id"], "CONSENT",
        headers=context["partner_a_headers"],
    )
    refusal_on_b = fixtures.submit_election(
        api, afe_b["id"], context["partner_b_id"], "NON_CONSENT",
        headers=context["partner_b_headers"],
    )

    closed_a = fixtures.close_elections(api, afe_a["id"])
    closed_b = fixtures.close_elections(api, afe_b["id"])

    assert closed_a["consent_working_interest_pct"] == 0.800000
    assert closed_b["consent_working_interest_pct"] == 0.800000
    assert closed_a["non_consent_working_interest_pct"] == 0.200000
    assert closed_b["non_consent_working_interest_pct"] == 0.200000
    assert closed_a["afe_status"] == "PARTIALLY_CONSENTED"
    assert closed_b["afe_status"] == "FAILED"

    kept = validate_success(
        api.get_afe_election(refusal_on_a["id"], fixtures.LAND_ADMIN), 200
    )
    assert kept["election_status"] == "SUBMITTED"
    assert kept["wi_pct_snapshot"] == 0.200000
    assert kept["estimated_penalty_cents"] == 1_200_000

    for voided_id in (consent_on_b["id"], refusal_on_b["id"]):
        voided = validate_success(
            api.get_afe_election(voided_id, fixtures.LAND_ADMIN), 200
        )
        assert voided["election_status"] == "VOIDED"

    elections_on_a = validate_success(
        api.list_afe_elections(
            fixtures.LAND_ADMIN, params={"afe_id": afe_a["id"], "limit": 100}
        ),
        200,
    )
    assert all(
        row["election_status"] != "DEEMED_NON_CONSENT" for row in elections_on_a
    )

    def position(interest_id):
        return validate_success(
            api.get_well_interest(interest_id, fixtures.LAND_ADMIN), 200
        )

    refusing = position(context["wi_partner_b_id"])
    assert refusing["non_consent_flag"] is True
    assert refusing["non_consent_recoverable_balance_cents"] == 0
    assert position(context["wi_partner_a_id"])["non_consent_flag"] is False
    assert position(context["wi_operator_id"])["non_consent_flag"] is False

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["consent_working_interest_pct"] == 0.800000
