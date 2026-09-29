"""Cross-cutting layers: the estoppel version guard on both a stale pin and an
exact replay, the scheduled insurance lapse's selectivity and the strictness of
the window it opens, and the immediacy of every derived field."""

from test_helpers import (
    ERR_STALE_LEASE_VERSION,
    assert_envelope_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_accountant_headers,
    make_asset_manager_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_estoppel_version_guard_refuses_a_stale_pin_and_an_exact_replay(api):
    """PRD §2.7: "Issuing an estoppel certificate carries the identical guard: `expected_lease_version` is a non-optional field of the request body, and a value that does not equal the lease's current `version` is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/estoppel_issuance_with_a_stale_lease_version_rejected
    """
    env = fx.standard_lease(api, "PIER-126", revaluation_interval_years=20)
    admin = make_lessor_admin_headers()
    mortgage = fx.record_senior_mortgage(
        api, env["lease_id"], original_principal_cents=30000000
    )
    stale_version = env["lease"]["version"]
    assert fx.lease_version(api, env["lease_id"]) == stale_version

    fx.file_insurance(
        api, env["lease_id"], property_all_risk_limit_cents=80000000,
        builders_risk_limit_cents=3000000, expires_at="2027-08-01T00:00:00Z",
    )
    fx.add_arrears(api, env["lease_id"], 3000000)
    fresh_version = fx.lease_version(api, env["lease_id"])
    assert stale_version == 1
    assert fresh_version == 3

    agent = make_mortgagee_agent_headers(mortgage["id"])
    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], stale_version),
            agent,
        ),
        ERR_STALE_LEASE_VERSION,
        expected_status=412,
    )
    _rows, empty = validate_paginated(
        api.list_estoppels(admin, {"lease_id": env["lease_id"]})
    )
    assert empty["total_count"] == 0

    certificate = validate_success(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], fresh_version),
            agent,
        ),
        expected_status=201,
    )
    assert_fields(
        certificate,
        status="ISSUED",
        certified_annual_base_rent_cents=10000000,
        certified_arrears_cents=3000000,
        certified_rent_status="BASE_ONLY",
        certified_lease_version=fresh_version + 1,
    )
    assert fx.lease_version(api, env["lease_id"]) == 4

    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], fresh_version),
            agent,
        ),
        ERR_STALE_LEASE_VERSION,
        expected_status=412,
    )
    rows, meta = validate_paginated(
        api.list_estoppels(admin, {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == certificate["id"]
    assert rows[0]["status"] == "ISSUED"


def _three_leases_one_renewal(api):
    """P and Q both insured to 2026-09-01, R never insured; P then renews to
    2027-09-01 at a clock of 2026-08-15."""
    lessee = fx.create_lessee(api)
    leases = {}
    for label, premises_code in (
        ("p", "PIER-127"), ("q", "PIER-128"), ("r", "PIER-129")
    ):
        leases[label] = fx.create_lease(
            api, lessee["id"], premises_code, revaluation_interval_years=20
        )
    for label in ("p", "q"):
        fx.file_insurance(
            api, leases[label]["id"],
            property_all_risk_limit_cents=80000000,
            builders_risk_limit_cents=3000000,
            expires_at="2026-09-01T00:00:00Z",
        )
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    fx.file_insurance(
        api, leases["p"]["id"],
        property_all_risk_limit_cents=80000000,
        builders_risk_limit_cents=3000000,
        expires_at="2027-09-01T00:00:00Z",
    )
    return lessee, leases


def test_the_lapse_phase_skips_the_renewed_lease_and_the_never_insured_one(api):
    """PRD §3.9: "A lease whose `insurance_expires_at` is still null has never filed an endorsement and is **not** lapsed by this phase."

    Design: Corner/cross_cutting_complexity_layers/scheduled_insurance_lapse_skips_the_renewed_and_the_never_insured_lease
    """
    _lessee, leases = _three_leases_one_renewal(api)
    admin = make_lessor_admin_headers()

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    report = fx.run_sweep(api)
    assert_fields(
        report,
        insurance_lapses_raised=1,
        cure_windows_lapsed=0,
        revaluations_flagged=0,
        mortgages_extinguished=0,
        leases_expired=0,
    )
    assert report["affected_lease_ids"] == [leases["q"]["id"]]

    assert_fields(
        fx.read_lease(api, leases["q"]["id"]),
        insurance_status="LAPSED", lease_status="IN_DEFAULT",
    )
    assert_fields(
        fx.read_lease(api, leases["p"]["id"]),
        insurance_status="ACTIVE",
        insurance_expires_at="2027-09-01T00:00:00Z",
        lease_status="ACTIVE",
    )
    lease_r = fx.read_lease(api, leases["r"]["id"])
    assert_fields(lease_r, insurance_status="LAPSED", lease_status="ACTIVE")
    assert lease_r["insurance_expires_at"] is None

    _rows, none_on_r = validate_paginated(
        api.list_default_notices(admin, {"lease_id": leases["r"]["id"]})
    )
    assert none_on_r["total_count"] == 0

    rows, meta = validate_paginated(
        api.list_default_notices(admin, {"lease_id": leases["q"]["id"]})
    )
    assert meta["total_count"] == 1
    assert_fields(
        rows[0],
        default_type="INSURANCE_LAPSE",
        status="SERVED",
        served_by_user_id="SYSTEM",
        served_at="2026-09-01T00:00:00Z",
        lessee_cure_deadline="2026-09-16T00:00:00Z",
    )
    assert rows[0]["mortgagee_cure_deadline"] is None

    again = fx.run_sweep(api)
    assert_fields(
        again,
        insurance_lapses_raised=0,
        cure_windows_lapsed=0,
        revaluations_flagged=0,
        mortgages_extinguished=0,
        leases_expired=0,
    )
    assert again["affected_lease_ids"] == []


def test_the_window_the_lapse_opened_closes_strictly_and_is_never_reopened(api):
    """PRD §3.9: "Notices in `SERVED` whose `lessee_cure_deadline` the clock has passed strictly move to `LESSEE_CURE_LAPSED`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_insurance_lapse_skips_the_renewed_and_the_never_insured_lease
    """
    _lessee, leases = _three_leases_one_renewal(api)
    admin = make_lessor_admin_headers()
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_sweep(api)
    rows, _meta = validate_paginated(
        api.list_default_notices(admin, {"lease_id": leases["q"]["id"]})
    )
    notice_id = rows[0]["id"]

    fx.set_clock(api, "2026-09-16T00:00:00Z")
    at_deadline = fx.run_sweep(api)
    assert at_deadline["cure_windows_lapsed"] == 0
    assert at_deadline["insurance_lapses_raised"] == 0
    assert validate_success(
        api.get_default_notice(notice_id, admin)
    )["status"] == "SERVED"

    fx.set_clock(api, "2026-09-16T00:00:01Z")
    past_deadline = fx.run_sweep(api)
    assert past_deadline["cure_windows_lapsed"] == 1
    assert past_deadline["insurance_lapses_raised"] == 0
    assert validate_success(
        api.get_default_notice(notice_id, admin)
    )["status"] == "LESSEE_CURE_LAPSED"

    _rows, meta = validate_paginated(
        api.list_default_notices(admin, {"lease_id": leases["q"]["id"]})
    )
    assert meta["total_count"] == 1


def test_every_derived_figure_is_final_in_the_first_response_that_carries_it(api):
    """PRD §4: "Unless a section above says otherwise, the `data` member of a successful response carries the created or updated resource in full — for actions that move a child resource and also mutate the lease, the child resource is what comes back, and the caller re-reads the lease to see the ledger and axis consequences."

    Design: Corner/consistency_model/every_write_response_already_carries_its_derived_fields
    """
    env = fx.standard_lease(api, "PIER-130", revaluation_interval_years=20)
    admin = make_lessor_admin_headers()
    accountant = make_accountant_headers("acct-1")

    get_success_data(
        api.post_rent_charge(
            env["lease_id"], f.rent_charge_payload(5000000, "Q3 2026 base rent"),
            accountant,
        )
    )
    charged = fx.read_lease(api, env["lease_id"])
    assert_fields(
        charged,
        arrears_balance_cents=5000000,
        gfa_allocated_sqft=0,
        gfa_unallocated_sqft=200000,
    )

    statement = validate_success(
        api.file_statement(
            f.statement_payload(
                env["lease_id"], charged["version"],
                "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", 200000000,
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    assert statement["status"] == "SUBMITTED"
    assert statement["amount_due_cents"] is None
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 5000000

    assessed = validate_success(api.assess_statement(statement["id"], accountant))
    assert_fields(
        assessed,
        assessment_variant="PROVISIONAL",
        # §3.4 step three names "the excess" only as an intermediate of the
        # computation, never as a response-visible statement attribute.
        gross_percentage_rent_cents=6000000,
        base_rent_offset_credit_cents=2500000,
        amount_due_cents=3500000,
    )

    summary = validate_success(api.get_rent_summary(env["lease_id"], accountant))
    assert summary["arrears_balance_cents"] == 8500000

    request = validate_success(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(
                requested_gfa_sqft=40000,
                construction_window_start="2026-09-01T00:00:00Z",
                construction_window_end="2026-10-01T00:00:00Z",
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    decided = validate_success(
        api.decide_alteration(
            request["id"], f.decision_payload("APPROVE"),
            make_asset_manager_headers("am-1"),
        )
    )
    assert decided["status"] == "APPROVED"

    final = validate_success(api.get_lease(env["lease_id"], admin))
    assert_fields(
        final,
        gfa_allocated_sqft=40000,
        gfa_unallocated_sqft=160000,
        arrears_balance_cents=8500000,
    )
    assert_envelope_conserved(final)
