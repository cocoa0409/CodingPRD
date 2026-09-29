"""Endpoint breadth: the partial terms amendment, the five-phase sweep's report
and its idempotency, estoppel supersession and the version it certifies, the
computed rent-summary read, and the new-lease election at its deadline."""

from test_helpers import (
    assert_deposit_conserved,
    assert_envelope_conserved,
    assert_fields,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_paginated,
    validate_success,
)


def test_a_terms_amendment_overwrites_only_the_fields_it_supplies(api):
    """PRD §3.1: "Only the fields actually supplied are overwritten; the rest are left exactly as they were."

    Design: Corner/endpoints/terms_amendment_overwrites_only_the_supplied_fields
    """
    env = fx.standard_lease(api, "PIER-116")
    admin = make_lessor_admin_headers()
    assert env["lease"]["version"] == 1

    first = validate_success(
        api.amend_terms(
            env["lease_id"],
            {"percentage_rent_rate_bps": 800, "total_permitted_gfa_sqft": 250000},
            admin,
        )
    )
    assert_fields(
        first,
        percentage_rent_rate_bps=800,
        total_permitted_gfa_sqft=250000,
        gfa_allocated_sqft=0,
        gfa_unallocated_sqft=250000,
        version=2,
        percentage_rent_breakpoint_cents=100000000,
        permitted_use_code="RETAIL_MIXED",
        reversion_standard_code="SHELL_CONDITION",
        current_annual_base_rent_cents=10000000,
        security_deposit_cents=5000000,
        lease_status="ACTIVE",
        rent_status="BASE_ONLY",
    )
    assert_envelope_conserved(first)

    second = validate_success(
        api.amend_terms(
            env["lease_id"], {"reversion_standard_code": "FULLY_FITTED"}, admin
        )
    )
    assert_fields(
        second,
        reversion_standard_code="FULLY_FITTED",
        version=3,
        percentage_rent_rate_bps=800,
        total_permitted_gfa_sqft=250000,
        lease_status="ACTIVE",
        rent_status="BASE_ONLY",
    )


def _three_leases_due_for_the_sweep(api):
    """X expires 2026-09-01, Y is insured only to 2026-08-15, Z falls due for
    revaluation on 2026-09-01; the clock then sits at 2026-09-02."""
    lessee = fx.create_lessee(api)
    lease_x = fx.create_lease(
        api, lessee["id"], "PIER-117X",
        expiration_date="2026-09-01T00:00:00Z", revaluation_interval_years=20,
    )
    lease_y = fx.create_lease(
        api, lessee["id"], "PIER-117Y", revaluation_interval_years=20
    )
    lease_z = fx.create_lease(
        api, lessee["id"], "PIER-117Z", commencement_date="2021-09-01T00:00:00Z"
    )
    fx.file_insurance(
        api, lease_y["id"], property_all_risk_limit_cents=100000000,
        builders_risk_limit_cents=10000000, expires_at="2026-08-15T00:00:00Z",
    )
    assert_instant(lease_z["next_revaluation_date"], "2026-09-01T00:00:00Z")
    fx.set_clock(api, "2026-09-02T00:00:00Z")
    return lessee, lease_x, lease_y, lease_z


def test_the_sweep_reports_one_counter_for_each_phase_that_moved_a_row(api):
    """PRD §3.9: "`run_at` echoes the logical instant of the run, `insurance_lapses_raised` counts the phase-one lapses, `cure_windows_lapsed` counts the phase-two lapses, `revaluations_flagged` counts the phase-three flags, `mortgages_extinguished` counts the phase-four extinguishments, `leases_expired` counts the phase-five expiries, and `affected_lease_ids` lists the identifiers of every lease any phase touched."

    Design: Corner/endpoints/administration_run_reports_per_phase_counters_and_is_idempotent_at_one_instant
    """
    _lessee, lease_x, lease_y, lease_z = _three_leases_due_for_the_sweep(api)
    admin = make_lessor_admin_headers()

    report = fx.run_sweep(api)
    assert_fields(
        report,
        run_at="2026-09-02T00:00:00Z",
        insurance_lapses_raised=1,
        cure_windows_lapsed=0,
        revaluations_flagged=1,
        mortgages_extinguished=0,
        leases_expired=1,
    )
    assert set(report["affected_lease_ids"]) == {
        lease_x["id"], lease_y["id"], lease_z["id"]
    }

    assert_fields(
        fx.read_lease(api, lease_x["id"]),
        lease_status="EXPIRED", rent_status="FROZEN",
    )
    rows, meta = validate_paginated(
        api.list_reversion_assessments(admin, {"lease_id": lease_x["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING_INSPECTION"

    assert_fields(
        fx.read_lease(api, lease_y["id"]),
        insurance_status="LAPSED", lease_status="IN_DEFAULT",
    )
    notices, notice_meta = validate_paginated(
        api.list_default_notices(admin, {"lease_id": lease_y["id"]})
    )
    assert notice_meta["total_count"] == 1
    assert_fields(
        notices[0],
        status="SERVED",
        default_type="INSURANCE_LAPSE",
        served_by_user_id="SYSTEM",
        lessee_cure_deadline="2026-09-17T00:00:00Z",
    )

    assert_fields(
        fx.read_lease(api, lease_z["id"]),
        rent_status="REVALUATION_DUE", lease_status="ACTIVE",
    )


def test_a_second_sweep_at_the_same_instant_moves_nothing(api):
    """PRD §3.9: "The sweep is idempotent within one logical instant: a second run at the same clock value moves nothing and returns zero counts."

    Design: Corner/endpoints/administration_run_reports_per_phase_counters_and_is_idempotent_at_one_instant
    """
    _lessee, lease_x, lease_y, lease_z = _three_leases_due_for_the_sweep(api)
    fx.run_sweep(api)
    before = {
        lease["id"]: fx.read_lease(api, lease["id"])
        for lease in (lease_x, lease_y, lease_z)
    }

    again = fx.run_sweep(api)
    assert_fields(
        again,
        run_at="2026-09-02T00:00:00Z",
        insurance_lapses_raised=0,
        cure_windows_lapsed=0,
        revaluations_flagged=0,
        mortgages_extinguished=0,
        leases_expired=0,
    )
    assert again["affected_lease_ids"] == []

    for lease_id, snapshot in before.items():
        after = fx.read_lease(api, lease_id)
        assert_fields(
            after,
            version=snapshot["version"],
            lease_status=snapshot["lease_status"],
            rent_status=snapshot["rent_status"],
            insurance_status=snapshot["insurance_status"],
        )


def _insured_and_mortgaged(api, premises_code):
    """One insured lease carrying a single recorded mortgage."""
    env = fx.standard_lease(api, premises_code)
    fx.file_insurance(
        api, env["lease_id"], property_all_risk_limit_cents=100000000,
        builders_risk_limit_cents=10000000, expires_at="2028-01-01T00:00:00Z",
    )
    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    return env, mortgage


def test_a_certificate_records_the_version_after_its_own_increment(api):
    """PRD §3.2: "`certified_annual_base_rent_cents` snapshots the lease's `current_annual_base_rent_cents`, `certified_arrears_cents` snapshots its `arrears_balance_cents`, `certified_rent_status` snapshots its `rent_status`, and `certified_lease_version` records the lease's `version` as it stands *after* the issuance's own increment — a certificate pinned against version 5 therefore certifies a `certified_lease_version` of 6."

    Design: Corner/endpoints/estoppel_certificate_for_the_same_financing_supersedes_the_earlier_one
    """
    env, mortgage = _insured_and_mortgaged(api, "PIER-118")
    agent = make_mortgagee_agent_headers(mortgage["id"])
    pinned = fx.lease_version(api, env["lease_id"], agent)

    certificate = validate_success(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], pinned), agent
        ),
        expected_status=201,
    )
    assert_fields(
        certificate,
        status="ISSUED",
        issued_at="2026-08-01T00:00:00Z",
        issued_by_user_id=mortgage["id"],
        certified_annual_base_rent_cents=10000000,
        certified_arrears_cents=0,
        certified_rent_status="BASE_ONLY",
        certified_lease_version=pinned + 1,
    )
    assert fx.lease_version(api, env["lease_id"], agent) == pinned + 1


def test_a_later_certificate_for_the_same_financing_supersedes_the_earlier(api):
    """PRD §3.2: "Any certificate for the same lease-and-mortgage pair that was still in `ISSUED` moves `ISSUED → SUPERSEDED`, so at most one live certificate exists per financing."

    Design: Corner/endpoints/estoppel_certificate_for_the_same_financing_supersedes_the_earlier_one
    """
    env, mortgage = _insured_and_mortgaged(api, "PIER-118")
    admin = make_lessor_admin_headers()
    agent = make_mortgagee_agent_headers(mortgage["id"])

    first = validate_success(
        api.issue_estoppel(
            f.estoppel_payload(
                env["lease_id"], mortgage["id"],
                fx.lease_version(api, env["lease_id"], agent),
            ),
            agent,
        ),
        expected_status=201,
    )
    reread = fx.lease_version(api, env["lease_id"], agent)
    second = validate_success(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], reread), admin
        ),
        expected_status=201,
    )
    assert_fields(
        second, status="ISSUED", certified_lease_version=reread + 1
    )

    assert validate_success(
        api.get_estoppel(first["id"], admin)
    )["status"] == "SUPERSEDED"
    assert validate_success(
        api.get_estoppel(second["id"], admin)
    )["status"] == "ISSUED"

    rows, meta = validate_paginated(
        api.list_estoppels(admin, {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_the_rent_summary_agrees_with_every_underlying_row(api):
    """PRD §3.1: "A computed rent-summary read exists for lenders and for internal diligence: it reports `current_annual_base_rent_cents`, `percentage_rent_sublease_base_cents`, `arrears_balance_cents`, `gfa_allocated_sqft`, `gfa_unallocated_sqft`, `deposit_held_cents`, `deposit_applied_cents`, `deposit_refunded_cents`, an `active_sublease_count` giving the number of subleases on the lease currently in status `ACTIVE`, and an `open_mortgage_principal_cents` giving the summed `outstanding_principal_cents` of the lease's mortgages that have not been extinguished or replaced by a new lease."

    Design: Corner/endpoints/rent_summary_computed_read_matches_every_underlying_row
    """
    env = fx.standard_lease(api, "PIER-119")
    mortgage = fx.record_senior_mortgage(
        api, env["lease_id"], original_principal_cents=3000000
    )
    fx.add_arrears(api, env["lease_id"], 1000000)
    fx.approved_alteration(
        api, env["lease_id"], env["lessee_id"],
        requested_gfa_sqft=40000,
        construction_window_start="2027-01-01T00:00:00Z",
        construction_window_end="2027-03-01T00:00:00Z",
        estimated_cost_cents=100000,
    )
    sublease = fx.active_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-A", 12000000,
        sublet_area_sqft=50000, transferee_legal_name="Pier Market Grocers LLC",
        term_start="2027-01-01T00:00:00Z", term_end="2030-01-01T00:00:00Z",
    )
    assert sublease["status"] == "ACTIVE"

    summary = validate_success(
        api.get_rent_summary(
            env["lease_id"], make_mortgagee_agent_headers(mortgage["id"])
        )
    )
    assert_fields(
        summary,
        current_annual_base_rent_cents=10000000,
        percentage_rent_sublease_base_cents=6000000,
        arrears_balance_cents=1000000,
        gfa_allocated_sqft=40000,
        gfa_unallocated_sqft=160000,
        deposit_held_cents=5000000,
        deposit_applied_cents=0,
        deposit_refunded_cents=0,
        active_sublease_count=1,
        open_mortgage_principal_cents=3000000,
    )

    lease = fx.read_lease(api, env["lease_id"])
    for field in (
        "current_annual_base_rent_cents", "percentage_rent_sublease_base_cents",
        "arrears_balance_cents", "gfa_allocated_sqft", "gfa_unallocated_sqft",
        "deposit_held_cents", "deposit_applied_cents", "deposit_refunded_cents",
    ):
        assert lease[field] == summary[field], field
    assert lease["total_permitted_gfa_sqft"] == 200000
    assert_envelope_conserved(lease)
    assert_deposit_conserved(lease)


SUCCESSOR = {
    "legal_name": "Keystone Successor Tenant LLC",
    "notice_email": "reo@keystone.example",
    "credit_rating_code": "BBB",
}


def test_the_new_lease_election_still_succeeds_at_exactly_its_deadline(api):
    """PRD §2.5: "Cure deadlines and the new-lease election deadline are **inclusive**: an action attempted at exactly the deadline instant still succeeds, and only an action attempted strictly after the deadline is refused."

    Design: Corner/endpoints/new_lease_election_is_available_only_up_to_its_deadline
    """
    env = fx.standard_lease(api, "PIER-120", revaluation_interval_years=20)
    admin = make_lessor_admin_headers()
    successor = fx.create_lessee(api, **SUCCESSOR)
    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"], f.default_notice_payload("UNPERMITTED_USE"),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    assert_fields(
        notice,
        lessee_cure_deadline="2026-08-31T00:00:00Z",
        mortgagee_cure_deadline="2026-09-30T00:00:00Z",
    )

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_sweep(api)
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    fx.run_sweep(api)
    assert validate_success(
        api.get_default_notice(notice["id"], admin)
    )["status"] == "MORTGAGEE_CURE_LAPSED"

    terminated = validate_success(
        api.terminate_lease(notice["id"], make_accountant_headers("acct-1"))
    )
    assert terminated["status"] == "TERMINATION_EFFECTED"
    assert_fields(
        validate_success(api.get_mortgage(mortgage["id"], admin)),
        status="NEW_LEASE_ELIGIBLE",
        new_lease_election_deadline="2026-10-31T00:00:00Z",
    )

    fx.set_clock(api, "2026-10-31T00:00:00Z")
    minted = validate_success(
        api.elect_new_lease(
            mortgage["id"], f.new_lease_election_payload(successor["id"]),
            make_mortgagee_agent_headers(mortgage["id"]),
        ),
        expected_status=201,
    )
    assert_fields(
        minted,
        predecessor_lease_id=env["lease_id"],
        origin_mortgage_id=mortgage["id"],
        lessee_id=successor["id"],
        premises_code="PIER-120",
        current_annual_base_rent_cents=10000000,
        expiration_date="2070-01-01T00:00:00Z",
        commencement_date="2026-10-31T00:00:00Z",
        lease_status="ACTIVE",
        rent_status="BASE_ONLY",
        insurance_status="LAPSED",
        arrears_balance_cents=0,
        deposit_held_cents=0,
        gfa_allocated_sqft=0,
    )
    assert validate_success(
        api.get_mortgage(mortgage["id"], admin)
    )["status"] == "NEW_LEASE_ELECTED"
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        lease_status="TERMINATED", rent_status="FROZEN",
    )
