"""Chains where each consequence is caused by the previous one, not by the trigger."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures


def test_a_lost_lease_withdraws_acreage_terminates_the_unit_and_suspends_the_money(api):
    """One expiry sweep travels from the lease all the way down to six payment rows.

    Every acreage allocation of the expiring lease whose `allocation_status` is `COMMITTED` becomes `WITHDRAWN`, with `withdrawn_reason` set to `LEASE_EXPIRED`.
    Caused by hop 3, every owner disbursement belonging to those suspended revenue months whose `disbursement_status` is `ACCRUED` becomes `SUSPENDED` with `suspense_reason` set to `POOLING_TERMINATED`, and each affected owner's `suspense_balance_cents` is recomputed.

    Design: Difficulty/transitive_cascade/lease_expiry_cascades_four_hops_into_suspended_disbursements
    """
    context = fixtures.setup_released_revenue_month(api, clock="2026-08-10T00:00:00Z")
    well_id = context["well_id"]
    revenue_id = context["revenue_id"]

    fixtures.change_status(api, well_id, "SHUT_IN", "2026-07-01")
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    run = fixtures.run_obligation_pass(api)
    assert run["leases_expired"] == 1
    assert run["allocations_withdrawn"] == 1
    assert run["revenues_suspended"] == 1
    assert run["disbursements_suspended"] == 6

    lease = validate_success(
        api.get_lease(context["lease1_id"], fixtures.LAND_ADMIN), 200
    )
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
    assert survivor["allocation_status"] == "COMMITTED"
    assert survivor["allocation_factor"] == 1.000000

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["pooling_status"] == "POOLED_TERMINATED"
    assert well["allocation_factor_total"] == 1.000000

    other_lease = validate_success(
        api.get_lease(context["lease2_id"], fixtures.LAND_ADMIN), 200
    )
    assert other_lease["tenure_status"] == "PRIMARY_TERM"

    revenue = validate_success(
        api.get_production_revenue(revenue_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert revenue["distribution_status"] == "SUSPENDED"
    assert revenue["total_disbursed_cents"] == 2_280_656

    rows = fixtures.disbursements_for(api, revenue_id)
    assert len(rows) == 6
    for row in rows:
        assert row["disbursement_status"] == "SUSPENDED"
        assert row["suspense_reason"] == "POOLING_TERMINATED"

    def suspense(owner_id):
        return validate_success(
            api.get_interest_owner(owner_id, fixtures.LAND_ADMIN), 200
        )["suspense_balance_cents"]

    assert suspense(context["operator_id"]) == 1_172_300
    assert suspense(context["partner_a_id"]) == 682_065
    assert suspense(context["partner_b_id"]) == 426_291


def test_an_adjusted_dispute_de_bills_the_well_and_closes_the_sibling_dispute(api):
    """Resolving one partner's dispute hands the second partner a win it never argued for.

    Hop 1: because `ADJUSTED` leaves the billed set, the well's `billed_to_date_cents` decreases by the statement's `total_billed_cents` and the well's `version` increments by 1.
    Hop 3, caused by that new draft existing: every **other** dispute against the original statement whose `dispute_status` is `OPEN`, `OPERATOR_RESPONDED` or `ESCALATED` is closed with `dispute_status` of `EXPIRED` and `deemed_in_favor_of_partner` of true — the bill those partners contested no longer exists, so they are treated as having prevailed rather than as having abandoned their claims.

    Design: Difficulty/transitive_cascade/dispute_adjustment_cascades_three_hops_into_sibling_dispute_expiry
    """
    context = fixtures.setup_responded_dispute(api, clock="2026-08-10T00:00:00Z")
    statement_id = context["statement_id"]
    partner_b_dispute_id = context["dispute_id"]

    partner_a_dispute = validate_success(
        api.file_dispute(
            statement_id,
            factories.file_dispute_payload(
                owner_id=context["partner_a_id"],
                disputed_amount_cents=50_000,
                dispute_kind="AUDIT_EXCEPTION",
                basis_note="Overhead rate class should be fixed rate for this period",
            ),
            context["partner_a_headers"],
        ),
        201,
    )

    resolved = validate_success(
        api.resolve_dispute(
            partner_b_dispute_id,
            factories.dispute_resolution_payload("ADJUSTED", 100_000),
            fixtures.AUDIT_REVIEWER,
        ),
        200,
    )
    assert resolved["dispute_status"] == "RESOLVED_ADJUSTED"
    assert resolved["adjustment_amount_cents"] == 100_000
    assert resolved["resolved_by_user_id"] == "u-audit-1"

    original = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert original["statement_status"] == "ADJUSTED"

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 0

    statements = validate_success(
        api.list_jib_statements(
            fixtures.JIB_ACCOUNTANT,
            params={"well_id": context["well_id"], "limit": 100},
        ),
        200,
    )
    replacements = [
        row for row in statements if row.get("superseded_statement_id") == statement_id
    ]
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["statement_status"] == "DRAFT"
    assert replacement["billing_period_start"] == "2026-06-01"
    assert replacement["billing_period_end"] == "2026-06-30"
    assert replacement["cost_basis"] == "ACCRUAL"
    assert replacement["activity_class"] == "PRODUCING"
    assert replacement["overhead_rate_class"] == "PERCENTAGE_BASIS"
    assert replacement["prepared_by_user_id"] == "u-audit-1"

    sibling = validate_success(
        api.get_dispute(partner_a_dispute["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert sibling["dispute_status"] == "EXPIRED"
    assert sibling["deemed_in_favor_of_partner"] is True
    assert sibling["adjustment_amount_cents"] == 0


def test_closing_an_election_window_synthesizes_a_refusal_and_suspends_that_owners_money(api):
    """The silent partner's refusal is written for it, and its revenue stops moving the same instant.

    For every non-operator owner holding an `ACTIVE` position on the well that filed no election at all, a synthesized election row is written directly with `election_type` of `NON_CONSENT`, `election_status` of `DEEMED_NON_CONSENT`, a `wi_pct_snapshot` taken from that owner's current `ACTIVE` `working_interest_pct`, a `submitted_at` from the logical clock, and `estimated_penalty_cents` computed by the same rule that governs a filed non-consent row.
    Caused by the same flag writes, every owner disbursement belonging to a newly non-consenting owner on this well whose `disbursement_status` is `ACCRUED` moves to `SUSPENDED` with `suspense_reason` set to `NON_CONSENT_RECOVERY`, and each affected owner's `suspense_balance_cents` is recomputed.

    Design: Difficulty/transitive_cascade/afe_election_closure_cascades_four_hops_into_non_consent_suspense
    """
    context = fixtures.setup_released_revenue_month(api, clock="2026-08-10T00:00:00Z")
    well_id = context["well_id"]
    revenue_id = context["revenue_id"]

    afe = fixtures.raise_afe(
        api,
        well_id,
        afe_number="AFE-002",
        operation_type="WORKOVER",
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-15",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.5,
    )
    consent = fixtures.submit_election(
        api,
        afe["id"],
        context["partner_a_id"],
        "CONSENT",
        headers=context["partner_a_headers"],
    )
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")

    closed = fixtures.close_elections(api, afe["id"])
    assert closed["afe_status"] == "PARTIALLY_CONSENTED"
    assert closed["consent_working_interest_pct"] == 0.800000
    assert closed["non_consent_working_interest_pct"] == 0.200000

    filed = validate_success(
        api.get_afe_election(consent["id"], fixtures.LAND_ADMIN), 200
    )
    assert filed["election_status"] == "SUBMITTED"

    def elections_of(owner_id):
        return validate_success(
            api.list_afe_elections(
                fixtures.LAND_ADMIN,
                params={"afe_id": afe["id"], "owner_id": owner_id, "limit": 100},
            ),
            200,
        )

    synthesized = elections_of(context["partner_b_id"])
    assert len(synthesized) == 1
    assert synthesized[0]["election_status"] == "DEEMED_NON_CONSENT"
    assert synthesized[0]["election_type"] == "NON_CONSENT"
    assert synthesized[0]["wi_pct_snapshot"] == 0.200000
    assert synthesized[0]["estimated_penalty_cents"] == 1_200_000

    assert elections_of(context["operator_id"]) == []

    def flag(interest_id):
        return validate_success(
            api.get_well_interest(interest_id, fixtures.LAND_ADMIN), 200
        )["non_consent_flag"]

    assert flag(context["wi_partner_b_id"]) is True
    assert flag(context["wi_operator_id"]) is False
    assert flag(context["wi_partner_a_id"]) is False

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["consent_working_interest_pct"] == 0.800000

    refusing_rows = fixtures.disbursements_for(
        api, revenue_id, owner_id=context["partner_b_id"]
    )
    assert refusing_rows
    for row in refusing_rows:
        assert row["disbursement_status"] == "SUSPENDED"
        assert row["suspense_reason"] == "NON_CONSENT_RECOVERY"

    for owner_id in (context["operator_id"], context["partner_a_id"]):
        rows = fixtures.disbursements_for(api, revenue_id, owner_id=owner_id)
        assert rows
        for row in rows:
            assert row["disbursement_status"] == "ACCRUED"

    def suspense(owner_id):
        return validate_success(
            api.get_interest_owner(owner_id, fixtures.LAND_ADMIN), 200
        )["suspense_balance_cents"]

    assert suspense(context["partner_b_id"]) == 426_291
    assert suspense(context["operator_id"]) == 0
    assert suspense(context["partner_a_id"]) == 0
