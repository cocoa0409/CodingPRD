"""State-machine breadth: declared initial states, the valid transitions and
their side effects, terminal lockdowns, refused transitions, idempotency and
the cascades that fire off a single move."""

from test_helpers import (
    ERR_APPRAISALS_INCOMPLETE,
    ERR_DIVERGENCE_BELOW_THRESHOLD,
    ERR_ELECTION_NOT_AVAILABLE,
    ERR_INVALID_STATE,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_exchange_copies_both_opinions_and_records_the_divergence(api):
    """PRD §3.3: "The two figures are copied onto the revaluation as `lessor_appraised_rent_cents` and `lessee_appraised_rent_cents`, and the spread between them is recorded in `divergence_bps`: take the larger of the two appraisals, subtract the smaller, multiply the difference by 10,000, divide by the **smaller** of the two appraisals, and round the result half up to a whole basis point."

    Design: Corner/state_machines/exchange_moves_revaluation_to_proposals_and_computes_divergence
    """
    env = fx.standard_lease(api, "PIER-82")
    reval = fx.open_revaluation(api, env["lease_id"])
    fx.lodge_both_appraisals(
        api, reval["id"], env["lessee_id"],
        lessor_cents=14000000, lessee_cents=10000000,
    )

    exchanged = validate_success(
        api.exchange_proposals(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(
        exchanged,
        status="PROPOSALS_EXCHANGED",
        lessor_appraised_rent_cents=14000000,
        lessee_appraised_rent_cents=10000000,
        divergence_bps=4000,
        round_number=1,
        prior_annual_base_rent_cents=10000000,
    )
    assert exchanged["resolved_annual_base_rent_cents"] is None
    assert exchanged["resolution_method"] is None

    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        rent_status="REVALUATION_OPEN",
        current_annual_base_rent_cents=10000000,
    )


def test_every_dependent_entity_opens_in_its_declared_initial_state(api):
    """PRD §3.8: "The event opens in `REPORTED`, with `distributable_pool_cents`, `allocation_method`, `rent_abatement_bps` and `lessee_share_bps` all null, all four allocated buckets at 0 and `allocation_detail` an empty list."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    env = fx.standard_lease(api, "PIER-83")
    admin = make_lessor_admin_headers()
    assert_fields(env["lease"], lease_status="ACTIVE", rent_status="BASE_ONLY")

    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    assert_fields(mortgage, status="RECORDED", outstanding_principal_cents=3000000)
    assert mortgage["mortgagee_notified_at"] is None
    assert mortgage["new_lease_election_deadline"] is None

    reval = fx.open_revaluation(api, env["lease_id"])
    assert_fields(reval, status="OPEN_FOR_APPRAISALS", round_number=1,
                  prior_annual_base_rent_cents=10000000)
    assert reval["divergence_bps"] is None
    assert fx.read_lease(api, env["lease_id"])["rent_status"] == "REVALUATION_OPEN"

    alteration = fx.submitted_alteration(
        api, env["lease_id"], env["lessee_id"],
        requested_gfa_sqft=1000, estimated_cost_cents=100000,
        construction_window_end="2027-02-01T00:00:00Z",
    )
    assert alteration["status"] == "SUBMITTED"
    assert alteration["decided_by_user_id"] is None

    loss = fx.reported_loss_event(
        api, env["lease_id"], headers=env["tenant"],
        damage_estimate_cents=1000000, damaged_area_sqft=500,
    )
    assert_fields(
        loss,
        status="REPORTED",
        allocated_arrears_cents=0,
        allocated_mortgagee_cents=0,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
        allocation_detail=[],
    )
    assert loss["distributable_pool_cents"] is None
    assert loss["allocation_method"] is None

    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"], f.default_notice_payload("UNPERMITTED_USE"),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    assert notice["status"] == "SERVED"
    assert notice["cured_by"] is None
    assert notice["terminated_by_user_id"] is None
    assert fx.read_lease(api, env["lease_id"], admin)["lease_status"] == "IN_DEFAULT"


def test_a_resolved_revaluation_refuses_both_a_second_settle_and_a_new_round(api):
    """PRD §2.8: "The source entity must sit in a state for which the operation is declared."

    Design: Corner/state_machines/resolved_revaluation_cannot_be_settled_or_reopened
    """
    env = fx.standard_lease(api, "PIER-84")
    admin = make_lessor_admin_headers()
    reval = fx.exchanged_revaluation(
        api, env["lease_id"], env["lessee_id"],
        lessor_cents=11000000, lessee_cents=10000000,
    )

    settled = validate_success(api.settle_revaluation(reval["id"], admin))
    assert_fields(
        settled,
        status="RESOLVED",
        resolution_method="MIDPOINT_SETTLEMENT",
        resolved_annual_base_rent_cents=11000000,
    )
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        current_annual_base_rent_cents=11000000,
        rent_status="RESET_APPLIED",
        next_revaluation_date="2030-01-01T00:00:00Z",
    )

    validate_error(
        api.settle_revaluation(reval["id"], admin),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    assert fx.read_lease(api, env["lease_id"])[
        "current_annual_base_rent_cents"] == 11000000

    validate_error(
        api.open_next_round(reval["id"], admin),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    still = validate_success(api.get_revaluation(reval["id"], admin))
    assert_fields(still, status="RESOLVED", round_number=1)


def test_a_one_sided_revaluation_refuses_exchange_rounds_and_settlement(api):
    """PRD §3.3: "The exchange demands exactly one `LESSOR` submission and one `LESSEE` submission whose `round_number` equals the revaluation's current `round_number`; an exchange attempted without both is refused with `ERR_APPRAISALS_INCOMPLETE`."

    Design: Corner/state_machines/exchange_without_both_sides_and_rounds_before_exchange_rejected
    """
    env = fx.standard_lease(api, "PIER-85")
    admin = make_lessor_admin_headers()
    reval = fx.open_revaluation(api, env["lease_id"])
    validate_success(
        api.lodge_appraisal(
            reval["id"],
            f.appraisal_payload("LESSOR", 14000000, "COMPARABLE_LAND"),
            make_lessor_admin_headers("appraiser-lessor-1"),
        ),
        expected_status=201,
    )

    validate_error(
        api.exchange_proposals(reval["id"], admin),
        ERR_APPRAISALS_INCOMPLETE,
        expected_status=409,
    )
    after = validate_success(api.get_revaluation(reval["id"], admin))
    assert after["status"] == "OPEN_FOR_APPRAISALS"
    assert after["lessor_appraised_rent_cents"] is None

    validate_error(
        api.open_next_round(reval["id"], admin),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    assert validate_success(
        api.get_revaluation(reval["id"], admin)
    )["round_number"] == 1

    validate_error(
        api.settle_revaluation(reval["id"], admin),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    assert fx.read_lease(api, env["lease_id"])[
        "current_annual_base_rent_cents"] == 10000000


def test_a_second_assess_on_the_same_statement_posts_nothing_twice(api):
    """PRD §3.4: "The assessed `amount_due_cents` is added to the lease's `arrears_balance_cents` and the lease `version` is incremented by one."

    Design: Corner/state_machines/repeat_assess_on_an_already_assessed_statement_rejected
    """
    env = fx.standard_lease(api, "PIER-86")
    statement = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", 200000000,
    )
    acct = make_accountant_headers("acct-1")

    assessed = validate_success(api.assess_statement(statement["id"], acct))
    assert_fields(
        assessed,
        status="PROVISIONAL_ASSESSED",
        assessment_variant="PROVISIONAL",
        included_sublease_rent_cents=0,
        gross_percentage_rent_cents=6000000,
        base_rent_offset_credit_cents=2500000,
        amount_due_cents=3500000,
    )
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 3500000

    validate_error(
        api.assess_statement(statement["id"], acct),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    unchanged = validate_success(api.get_statement(statement["id"], acct))
    assert_fields(unchanged, status="PROVISIONAL_ASSESSED", amount_due_cents=3500000)
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 3500000


def test_a_referral_at_exactly_the_threshold_is_refused_then_settlement_runs(api):
    """PRD §3.3: "A referral is only available where the parties are genuinely far apart: `divergence_bps` must **exceed** 1,000 basis points, and a referral attempted when the divergence is at or below that threshold is refused with `ERR_DIVERGENCE_BELOW_THRESHOLD`."

    Design: Corner/state_machines/referral_at_exactly_the_divergence_threshold_rejected_then_settles
    """
    env = fx.standard_lease(api, "PIER-87")
    admin = make_lessor_admin_headers()
    reval = fx.exchanged_revaluation(
        api, env["lease_id"], env["lessee_id"],
        lessor_cents=11000000, lessee_cents=10000000,
    )
    assert reval["divergence_bps"] == 1000

    validate_error(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), admin
        ),
        ERR_DIVERGENCE_BELOW_THRESHOLD,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        api.list_arbitrations(admin, {"revaluation_id": reval["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fx.read_lease(api, env["lease_id"])["rent_status"] == "REVALUATION_OPEN"

    settled = validate_success(api.settle_revaluation(reval["id"], admin))
    assert_fields(
        settled,
        status="RESOLVED",
        resolution_method="MIDPOINT_SETTLEMENT",
        resolved_annual_base_rent_cents=11000000,
    )
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        rent_status="RESET_APPLIED",
        current_annual_base_rent_cents=11000000,
    )


def test_a_condemnation_offers_no_election_but_still_allocates(api):
    """PRD §3.8: "The `GroundTenant` supplies an `election` of `RESTORE` or `TERMINATE` on an event in `ADJUSTED`; the same request against a `CONDEMNATION` event is refused with `ERR_ELECTION_NOT_AVAILABLE`."

    Design: Corner/state_machines/restoration_election_on_a_condemnation_rejected
    """
    env = fx.standard_lease(api, "PIER-88")
    admin = make_lessor_admin_headers()
    event = fx.adjusted_loss_event(
        api, env["lease_id"], 4000000, "BONUS_VALUE",
        event_type="CONDEMNATION", damage_estimate_cents=4000000,
        damaged_area_sqft=10000,
    )
    assert event["status"] == "ADJUSTED"

    for election in ("RESTORE", "TERMINATE"):
        validate_error(
            api.elect_loss_outcome(
                event["id"], f.election_payload(election), env["tenant"]
            ),
            ERR_ELECTION_NOT_AVAILABLE,
            expected_status=409,
        )
        assert validate_success(
            api.get_loss_event(event["id"], admin)
        )["status"] == "ADJUSTED"
    assert fx.read_lease(api, env["lease_id"])["lease_status"] == "ACTIVE"

    allocated = validate_success(
        api.allocate_proceeds(event["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        allocated,
        status="ALLOCATED",
        allocated_arrears_cents=0,
        allocated_mortgagee_cents=0,
        lessee_share_bps=6000,
        allocated_lessee_cents=2400000,
        allocated_lessor_cents=1600000,
    )
    assert (
        allocated["allocated_arrears_cents"]
        + allocated["allocated_mortgagee_cents"]
        + allocated["allocated_lessee_cents"]
        + allocated["allocated_lessor_cents"]
    ) == 4000000


def test_service_notifies_every_recorded_mortgage_at_the_same_instant(api):
    """PRD §3.7: "It also stamps `mortgagee_notified_at` on the notice with the service instant, and moves every mortgage on the lease from `RECORDED → NOTICE_SERVED`, each with its own `mortgagee_notified_at` set to the same instant."

    Design: Corner/state_machines/default_notice_service_notifies_every_recorded_mortgage
    """
    env = fx.standard_lease(api, "PIER-89")
    admin = make_lessor_admin_headers()
    senior = fx.record_senior_mortgage(api, env["lease_id"])
    mezz = fx.record_mezz_mortgage(api, env["lease_id"])
    fx.add_arrears(api, env["lease_id"], 4000000)

    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"],
            f.default_notice_payload("MONETARY_RENT_ARREARS", 4000000),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    assert_fields(
        notice,
        status="SERVED",
        served_at="2026-08-01T00:00:00Z",
        served_by_user_id="am-1",
        lessee_cure_deadline="2026-08-11T00:00:00Z",
        mortgagee_cure_deadline="2026-09-10T00:00:00Z",
        mortgagee_notified_at="2026-08-01T00:00:00Z",
    )

    for mortgage_id in (senior["id"], mezz["id"]):
        row = validate_success(api.get_mortgage(mortgage_id, admin))
        assert_fields(row, status="NOTICE_SERVED",
                      mortgagee_notified_at="2026-08-01T00:00:00Z")
        assert row["new_lease_election_deadline"] is None

    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        lease_status="IN_DEFAULT",
        rent_status="BASE_ONLY",
        arrears_balance_cents=4000000,
    )


def test_the_expiry_sweep_cascades_down_to_every_dependent_row(api):
    """PRD §3.9: "Every transfer request on the lease in `ACTIVE` becomes `TERMINATED_BY_REVERSION` and the lease's `percentage_rent_sublease_base_cents` is recomputed over the emptied active set."

    Design: Corner/state_machines/expiry_sweep_cascades_to_subleases_mortgages_and_opens_the_reversion
    """
    env = fx.standard_lease(api, "PIER-90", expiration_date="2026-09-01T00:00:00Z")
    admin = make_lessor_admin_headers()
    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    sublease = fx.active_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-A", 12000000,
        sublet_area_sqft=100000,
        term_start="2026-08-05T00:00:00Z",
        term_end="2026-08-25T00:00:00Z",
    )
    assert_fields(
        sublease,
        status="ACTIVE",
        allocable_base_rent_cents=5000000,
        transfer_fee_gross_cents=3500000,
        admin_charge_cents=87500,
        late_surcharge_cents=0,
        total_transfer_fee_cents=3587500,
    )
    assert fx.read_lease(api, env["lease_id"])[
        "percentage_rent_sublease_base_cents"] == 6000000

    report, assessment = fx.expire_lease_via_sweep(api, env["lease_id"])
    assert report["leases_expired"] == 1
    assert env["lease_id"] in report["affected_lease_ids"]

    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        lease_status="EXPIRED",
        rent_status="FROZEN",
        percentage_rent_sublease_base_cents=0,
    )
    assert validate_success(
        api.get_transfer(sublease["id"], admin)
    )["status"] == "TERMINATED_BY_REVERSION"
    assert validate_success(
        api.get_mortgage(mortgage["id"], admin)
    )["status"] == "EXTINGUISHED"

    rows, meta = validate_paginated(
        api.list_reversion_assessments(admin, {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 1
    assert_fields(rows[0], id=assessment["id"], status="PENDING_INSPECTION",
                  required_standard_code="SHELL_CONDITION")

    summary = validate_success(api.get_rent_summary(env["lease_id"], admin))
    assert_fields(summary, active_sublease_count=0, open_mortgage_principal_cents=0)


def test_the_ledger_reconciles_across_a_charge_and_a_proceeds_allocation(api):
    """PRD §3.1: "Arrears are debited by charges and by percentage-rent assessments, and credited by cure payments and by the arrears bucket of a proceeds allocation; the balance is the single figure a monetary default is measured against."

    Design: Corner/state_machines/arrears_ledger_reconciles_after_a_charge_and_an_award_allocation
    """
    env = fx.standard_lease(api, "PIER-92")
    mortgage = fx.record_senior_mortgage(
        api, env["lease_id"], original_principal_cents=2000000
    )
    fx.add_arrears(api, env["lease_id"], 5000000)
    event = fx.adjusted_loss_event(
        api, env["lease_id"], 6000000, "BONUS_VALUE",
        event_type="CONDEMNATION", damage_estimate_cents=6000000,
        damaged_area_sqft=20000,
    )
    agent = make_mortgagee_agent_headers(mortgage["id"])

    before = validate_success(api.get_rent_summary(env["lease_id"], agent))
    assert_fields(before, arrears_balance_cents=5000000,
                  open_mortgage_principal_cents=2000000)

    allocated = validate_success(
        api.allocate_proceeds(event["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        allocated,
        allocated_arrears_cents=5000000,
        allocated_mortgagee_cents=1000000,
        lessee_share_bps=6000,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
        allocation_detail=[{"mortgage_id": mortgage["id"], "amount_cents": 1000000}],
    )
    assert (
        allocated["allocated_arrears_cents"]
        + allocated["allocated_mortgagee_cents"]
        + allocated["allocated_lessee_cents"]
        + allocated["allocated_lessor_cents"]
    ) == 6000000

    after = validate_success(api.get_rent_summary(env["lease_id"], agent))
    assert_fields(after, arrears_balance_cents=0,
                  open_mortgage_principal_cents=1000000)
    assert_fields(
        validate_success(api.get_mortgage(mortgage["id"], make_lessor_admin_headers())),
        status="RECORDED",
        outstanding_principal_cents=1000000,
    )


def test_the_lessee_cure_returns_every_noticed_mortgage_to_recorded(api):
    """PRD §3.7: "An accepted cure moves the notice `SERVED → LESSEE_CURED` with `cured_by` recorded as `LESSEE`, subtracts `cure_amount_cents` from the lease's `arrears_balance_cents` on a monetary ground with the result floored at 0, returns the lease's tenancy axis `IN_DEFAULT → ACTIVE`, increments the lease `version` by one, and returns every mortgage on the lease in `NOTICE_SERVED` or `CURING` to `RECORDED` with `mortgagee_notified_at` cleared."

    Design: Corner/state_machines/lessee_cure_reverses_the_mortgage_notice_cascade
    """
    env = fx.standard_lease(api, "PIER-93")
    admin = make_lessor_admin_headers()
    senior = fx.record_senior_mortgage(api, env["lease_id"])
    mezz = fx.record_mezz_mortgage(api, env["lease_id"])
    fx.add_arrears(api, env["lease_id"], 4000000)
    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"],
            f.default_notice_payload("MONETARY_RENT_ARREARS", 4000000),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    assert notice["status"] == "SERVED"

    cured = validate_success(
        api.lessee_cure(
            notice["id"],
            f.lessee_cure_payload("2026-08-05T00:00:00Z", 4000000),
            make_ground_tenant_headers(env["lessee_id"]),
        )
    )
    assert_fields(cured, status="LESSEE_CURED", cured_by="LESSEE")

    for mortgage_id, principal in (
        (senior["id"], 3000000), (mezz["id"], 2000000)
    ):
        row = validate_success(api.get_mortgage(mortgage_id, admin))
        assert_fields(row, status="RECORDED", outstanding_principal_cents=principal)
        assert row["mortgagee_notified_at"] is None

    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        lease_status="ACTIVE",
        arrears_balance_cents=0,
    )


def test_termination_voids_the_open_statement_and_spares_the_final_one(api):
    """PRD §3.4: "A statement in `SUBMITTED` when the lease is terminated moves `SUBMITTED → VOID` with no ledger movement, because nothing had been posted for it."

    Design: Corner/state_machines/termination_voids_open_statements_but_spares_final_assessed_ones
    """
    env = fx.standard_lease(api, "PIER-94")
    admin = make_lessor_admin_headers()
    acct = make_accountant_headers("acct-1")

    statement_a = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", 200000000,
    )
    statement_b = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        "2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z", 100000000,
    )
    validate_success(api.assess_statement(statement_a["id"], acct))
    finalised = validate_success(
        api.audit_statement(
            statement_a["id"], {"audited_gross_sales_cents": 200000000}, acct
        )
    )
    assert_fields(
        finalised,
        status="FINAL_ASSESSED",
        assessment_variant="AUDITED_FINAL",
        amount_due_cents=3500000,
        underreport_penalty_cents=0,
    )
    assert validate_success(
        api.get_statement(statement_b["id"], acct)
    )["status"] == "SUBMITTED"
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 3500000

    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"],
            f.default_notice_payload("MONETARY_RENT_ARREARS", 3500000),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    fx.set_clock(api, "2026-08-12T00:00:00Z")
    fx.run_sweep(api)
    assert validate_success(
        api.get_default_notice(notice["id"], admin)
    )["status"] == "LESSEE_CURE_LAPSED"

    terminated = validate_success(api.terminate_lease(notice["id"], acct))
    assert_fields(terminated, status="TERMINATION_EFFECTED",
                  terminated_by_user_id="acct-1")

    assert validate_success(
        api.get_statement(statement_b["id"], acct)
    )["status"] == "VOID"
    assert_fields(
        validate_success(api.get_statement(statement_a["id"], acct)),
        status="FINAL_ASSESSED",
        amount_due_cents=3500000,
    )
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        lease_status="TERMINATED",
        rent_status="FROZEN",
        arrears_balance_cents=3500000,
    )
