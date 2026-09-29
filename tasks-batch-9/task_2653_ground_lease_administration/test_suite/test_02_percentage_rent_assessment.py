"""Percentage rent: the sublease inclusion base, the strict breakpoint, the
provisional-versus-audited variants, the reconciliation ledger movement and the
refusal ordering that guards statement filing."""

from test_helpers import (
    ERR_CHRONOLOGY_VIOLATION,
    ERR_LEASE_NOT_OPERATIVE,
    ERR_STALE_LEASE_VERSION,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PERIOD_START = "2025-01-01T00:00:00Z"
PERIOD_END = "2026-01-01T00:00:00Z"
SUBLEASE_TERM = {"term_start": "2025-01-01T00:00:00Z",
                 "term_end": "2030-01-01T00:00:00Z"}


def _lease_with_three_subleases(api, premises_code):
    """Two ACTIVE subleases (4000001 and 2000001) plus one that stops at
    CONSENT_GRANTED (1000001), so the provisional and audited inclusion sets
    differ on identical database rows."""
    env = fx.standard_lease(api, premises_code)
    fx.active_sublease(api, env["lease_id"], env["lessee_id"], "UNIT-A",
                       4000001, **SUBLEASE_TERM)
    fx.active_sublease(api, env["lease_id"], env["lessee_id"], "UNIT-B",
                       2000001, **SUBLEASE_TERM)
    fx.consented_sublease(api, env["lease_id"], env["lessee_id"], "UNIT-C",
                          1000001, **SUBLEASE_TERM)
    return env


def test_provisional_assessment_admits_only_the_active_sublease_rows(api):
    """PRD §3.4: "It uses `reported_gross_sales_cents` as the gross sales figure, and its inclusion set admits only subleases whose status is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/percentage_rent_provisional_then_audited_final_reconciliation
    """
    env = _lease_with_three_subleases(api, "PIER-42")
    stmt = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        PERIOD_START, PERIOD_END, 144999998,
    )
    assert stmt["base_rent_offset_credit_cents"] == 2500000
    assert stmt["included_sublease_rent_cents"] is None
    assert stmt["assessment_variant"] is None

    assessed = validate_success(
        api.assess_statement(stmt["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        assessed,
        status="PROVISIONAL_ASSESSED",
        assessment_variant="PROVISIONAL",
        included_sublease_rent_cents=3000002,
        gross_percentage_rent_cents=2880000,
        base_rent_offset_credit_cents=2500000,
        amount_due_cents=380000,
    )
    assert assessed["underreport_penalty_cents"] is None
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 380000


def test_the_audit_pass_widens_the_inclusion_set_to_consented_subleases(api):
    """PRD §3.4: "It uses that audited figure as the gross sales input, and — this is the substantive difference beyond the sales figure — its inclusion set **widens** to admit subleases whose status is `ACTIVE` or `CONSENT_GRANTED`, so consented-but-not-yet-paid-for subleases enter the base on audit even though they were excluded provisionally."

    Design: Difficulty/dual_variant_calc/percentage_rent_provisional_then_audited_final_reconciliation
    """
    env = _lease_with_three_subleases(api, "PIER-42")
    stmt = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        PERIOD_START, PERIOD_END, 144999998,
    )
    validate_success(
        api.assess_statement(stmt["id"], make_accountant_headers("acct-1"))
    )

    audited = validate_success(
        api.audit_statement(
            stmt["id"], {"audited_gross_sales_cents": 160000000},
            make_accountant_headers("acct-1"),
        )
    )
    assert_fields(
        audited,
        status="FINAL_ASSESSED",
        assessment_variant="AUDITED_FINAL",
        audited_gross_sales_cents=160000000,
        included_sublease_rent_cents=3500003,
        gross_percentage_rent_cents=3810000,
        amount_due_cents=1310000,
        underreport_penalty_cents=900000,
    )


def test_the_audit_ledger_movement_is_a_reconciliation_not_a_second_charge(api):
    """PRD §3.4: "The ledger movement is a reconciliation, not a second charge: add the newly computed `amount_due_cents`, subtract the provisional `amount_due_cents` previously posted, and add `underreport_penalty_cents`, applying the net figure to the lease's `arrears_balance_cents` — so a downward audit genuinely reduces arrears."

    Design: Difficulty/dual_variant_calc/percentage_rent_provisional_then_audited_final_reconciliation
    """
    env = _lease_with_three_subleases(api, "PIER-42")
    stmt = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        PERIOD_START, PERIOD_END, 144999998,
    )
    validate_success(
        api.assess_statement(stmt["id"], make_accountant_headers("acct-1"))
    )
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 380000

    validate_success(
        api.audit_statement(
            stmt["id"], {"audited_gross_sales_cents": 160000000},
            make_accountant_headers("acct-1"),
        )
    )
    # 380000 + (1310000 - 380000) + 900000 rather than 380000 + 1310000 + 900000.
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 2210000


def _three_closed_periods(api, premises_code):
    """Three non-overlapping closed periods on an unsublet lease, reported at the
    breakpoint and one and two cents above it."""
    env = fx.standard_lease(api, premises_code)
    filings = []
    for start, end, reported in (
        ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 100000000),
        ("2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z", 100000008),
        ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 100000009),
    ):
        filings.append(
            fx.file_statement(api, env["lease_id"], env["lessee_id"],
                              start, end, reported)
        )
    return env, filings


def test_adjusted_sales_exactly_on_the_breakpoint_produce_no_percentage_rent(api):
    """PRD §3.4: "The breakpoint is **strict**: adjusted sales landing exactly on the breakpoint produce no excess and therefore no percentage rent."

    Design: Difficulty/boundary_precision_check/percentage_rent_at_breakpoint_with_empty_sublease_set_and_rounding_floor
    """
    env, filings = _three_closed_periods(api, "PIER-56")

    at_breakpoint = validate_success(
        api.assess_statement(filings[0]["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        at_breakpoint,
        included_sublease_rent_cents=0,
        gross_percentage_rent_cents=0,
        base_rent_offset_credit_cents=2500000,
        amount_due_cents=0,
        assessment_variant="PROVISIONAL",
        status="PROVISIONAL_ASSESSED",
    )


def test_the_rate_application_rounds_half_up_at_the_half_cent(api):
    """PRD §3.4: "Multiply the excess by the lease's `percentage_rent_rate_bps`, divide by 10,000, and round half up to whole cents."

    Design: Difficulty/boundary_precision_check/percentage_rent_at_breakpoint_with_empty_sublease_set_and_rounding_floor
    """
    env, filings = _three_closed_periods(api, "PIER-56")

    # excess 8 -> 8 * 600 / 10000 = 0.48 -> 0
    below_half = validate_success(
        api.assess_statement(filings[1]["id"], make_accountant_headers("acct-1"))
    )
    assert below_half["gross_percentage_rent_cents"] == 0

    # excess 9 -> 9 * 600 / 10000 = 0.54 -> 1
    above_half = validate_success(
        api.assess_statement(filings[2]["id"], make_accountant_headers("acct-1"))
    )
    assert above_half["gross_percentage_rent_cents"] == 1


def test_the_offset_credit_never_produces_a_refund_and_arrears_stay_flat(api):
    """PRD §3.4: "Subtract `base_rent_offset_credit_cents` from `gross_percentage_rent_cents`; if the result is negative, `amount_due_cents` is 0."

    Design: Difficulty/boundary_precision_check/percentage_rent_at_breakpoint_with_empty_sublease_set_and_rounding_floor
    """
    env, filings = _three_closed_periods(api, "PIER-56")
    for row in filings:
        assessed = validate_success(
            api.assess_statement(row["id"], make_accountant_headers("acct-1"))
        )
        assert assessed["amount_due_cents"] == 0
        assert assessed["base_rent_offset_credit_cents"] == 2500000
        assert assessed["status"] == "PROVISIONAL_ASSESSED"

    lease = fx.read_lease(api, env["lease_id"])
    assert lease["arrears_balance_cents"] == 0
    assert lease["percentage_rent_sublease_base_cents"] == 0


ODD_SUBLEASE_RENTS = (
    ("UNIT-1", 4000001),
    ("UNIT-2", 2000001),
    ("UNIT-3", 6000001),
    ("UNIT-4", 8000001),
)


def _four_consented_subleases(api, premises_code):
    env = fx.standard_lease(api, premises_code)
    granted = [
        fx.consented_sublease(api, env["lease_id"], env["lessee_id"], unit,
                              rent, **SUBLEASE_TERM)
        for unit, rent in ODD_SUBLEASE_RENTS
    ]
    return env, granted


def test_consent_granted_subleases_are_outside_the_inclusion_base(api):
    """PRD §3.6: "Rows in `SUBMITTED`, `CONSENT_GRANTED`, `CONSENT_DENIED` or `TERMINATED_BY_REVERSION` are excluded, and an empty set yields 0."

    Design: Difficulty/combinatorial_formula/sublease_inclusion_base_per_line_rounding_beats_sum_first
    """
    env, granted = _four_consented_subleases(api, "PIER-43")
    assert [row["status"] for row in granted] == ["CONSENT_GRANTED"] * 4

    lease = fx.read_lease(api, env["lease_id"])
    assert lease["percentage_rent_sublease_base_cents"] == 0


def test_per_line_rounding_before_addition_beats_summing_the_raw_rents(api):
    """PRD §3.6: "The per-row rounding happens before the addition, never after."

    Design: Difficulty/combinatorial_formula/sublease_inclusion_base_per_line_rounding_beats_sum_first
    """
    env, granted = _four_consented_subleases(api, "PIER-43")
    tenant = make_ground_tenant_headers(env["lessee_id"])

    running = []
    for row in granted:
        outstanding = row["total_transfer_fee_cents"] - row["transfer_fee_paid_cents"]
        activated = validate_success(
            api.pay_transfer_fee(row["id"], f.fee_payment_payload(outstanding), tenant)
        )
        assert activated["status"] == "ACTIVE"
        running.append(
            fx.read_lease(api, env["lease_id"])["percentage_rent_sublease_base_cents"]
        )

    assert running == [2000001, 3000002, 6000003, 10000004]
    # Summing the raw rents (20000004) and halving once would give 10000002:
    # one cent is lost for each pair of odd rents.
    assert running[-1] != 10000002


def _open_statement_and_exchanged_revaluation(api, premises_code):
    """A statement still in SUBMITTED reporting 160000000, with a revaluation
    already exchanged at 14000000 / 10000000 waiting to be settled."""
    env = fx.standard_lease(api, premises_code)
    reval = fx.exchanged_revaluation(api, env["lease_id"], env["lessee_id"])
    stmt = fx.file_statement(
        api, env["lease_id"], env["lessee_id"], PERIOD_START, PERIOD_END, 160000000
    )
    assert stmt["status"] == "SUBMITTED"
    assert stmt["base_rent_offset_credit_cents"] == 2500000
    return env, reval, stmt


def test_a_settlement_reprices_the_offset_credit_of_a_submitted_statement(api):
    """PRD §3.3: "And because the base rent in force has changed, every percentage-rent statement on that lease still sitting in `SUBMITTED` has its `base_rent_offset_credit_cents` recomputed against the new base rent — a statement filed before the reset lands must not be assessed against the superseded figure."

    Design: Difficulty/transitive_cascade/settlement_reprices_open_statement_credit_then_changes_the_assessment
    """
    env, reval, stmt = _open_statement_and_exchanged_revaluation(api, "PIER-50")

    settled = validate_success(
        api.settle_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(settled, status="RESOLVED",
                  resolved_annual_base_rent_cents=12000000)
    assert_fields(fx.read_lease(api, env["lease_id"]),
                  current_annual_base_rent_cents=12000000,
                  rent_status="RESET_APPLIED")

    repriced = validate_success(
        api.get_statement(stmt["id"], make_ground_tenant_headers(env["lessee_id"]))
    )
    assert repriced["status"] == "SUBMITTED"
    assert repriced["base_rent_offset_credit_cents"] == 3000000


def test_the_repriced_credit_changes_the_amount_due_and_the_arrears_posted(api):
    """PRD §3.4: "That figure is `base_rent_offset_credit_cents`, and it is taken from the base rent **in force at assessment time**, which is why a revaluation reset that lands while a statement is still in `SUBMITTED` forces the credit to be recomputed."

    Design: Difficulty/transitive_cascade/settlement_reprices_open_statement_credit_then_changes_the_assessment
    """
    env, reval, stmt = _open_statement_and_exchanged_revaluation(api, "PIER-50")
    validate_success(api.settle_revaluation(reval["id"], make_lessor_admin_headers()))

    assessed = validate_success(
        api.assess_statement(stmt["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        assessed,
        included_sublease_rent_cents=0,
        gross_percentage_rent_cents=3600000,
        base_rent_offset_credit_cents=3000000,
        amount_due_cents=600000,
    )
    # The pre-settlement credit of 2500000 would have produced 1100000.
    assert assessed["amount_due_cents"] != 1100000
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 600000


def _stale_and_fresh_versions(api, premises_code):
    """The tenant reads the version, the accountant posts a rent charge, and the
    tenant's view goes stale by exactly one."""
    env = fx.standard_lease(api, premises_code)
    stale = fx.lease_version(api, env["lease_id"])
    validate_success(
        api.post_rent_charge(
            env["lease_id"], f.rent_charge_payload(1000000),
            make_accountant_headers("acct-1"),
        )
    )
    fresh = fx.lease_version(api, env["lease_id"])
    assert fresh == stale + 1
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 1000000
    return env, stale, fresh


def test_a_stale_pin_is_reported_before_the_premature_period(api):
    """PRD §2.7: "If that value does not equal the target lease's current `version`, the filing is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/statement_stale_version_beats_chronology_then_chronology_surfaces
    """
    env, stale, _fresh = _stale_and_fresh_versions(api, "PIER-54")
    tenant = make_ground_tenant_headers(env["lessee_id"])

    # Priority 4 and priority 11 are both live on this request.
    validate_error(
        api.file_statement(
            f.statement_payload(env["lease_id"], stale,
                                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_STALE_LEASE_VERSION,
        expected_status=412,
    )

    # Priority 4 alone is live; the answer does not change.
    validate_error(
        api.file_statement(
            f.statement_payload(env["lease_id"], stale,
                                "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_STALE_LEASE_VERSION,
        expected_status=412,
    )


def test_with_the_pin_refreshed_the_chronology_violation_surfaces(api):
    """PRD §2.9: "A statement's `period_end` must not be after the logical clock's current instant — a tenant cannot file for a period that has not closed."

    Design: Difficulty/priority_pair_validation_conflict/statement_stale_version_beats_chronology_then_chronology_surfaces
    """
    env, _stale, fresh = _stale_and_fresh_versions(api, "PIER-54")
    tenant = make_ground_tenant_headers(env["lessee_id"])

    validate_error(
        api.file_statement(
            f.statement_payload(env["lease_id"], fresh,
                                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )

    accepted = validate_success(
        api.file_statement(
            f.statement_payload(env["lease_id"], fresh,
                                "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["base_rent_offset_credit_cents"] == 2500000


def test_only_the_accepted_filing_advances_the_lease_version(api):
    """PRD §3.4: "The filing increments the lease `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/statement_stale_version_beats_chronology_then_chronology_surfaces
    """
    env, stale, fresh = _stale_and_fresh_versions(api, "PIER-54")
    tenant = make_ground_tenant_headers(env["lessee_id"])
    premature = ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    closed = ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")

    for version, (start, end) in (
        (stale, premature), (stale, closed), (fresh, premature),
    ):
        response = api.file_statement(
            f.statement_payload(env["lease_id"], version, start, end, 120000000),
            tenant,
        )
        assert response.status_code >= 400

    validate_success(
        api.file_statement(
            f.statement_payload(env["lease_id"], fresh, closed[0], closed[1],
                                120000000),
            tenant,
        ),
        expected_status=201,
    )
    assert fx.lease_version(api, env["lease_id"]) == fresh + 1


def _terminated_lease_and_control(api):
    """Lease A is terminated by a casualty termination election (damage 40000000
    against improvements 60000000 clears the half-of-improvements threshold);
    lease B is left untouched as the control."""
    lessee = fx.create_lessee(api)
    lease_a = fx.create_lease(api, lessee["id"], "PIER-52-A")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-52-B")
    fx.file_insurance(api, lease_a["id"])
    event = fx.adjusted_loss_event(
        api, lease_a["id"], 40000000, "BONUS_VALUE", 0,
        event_type="CASUALTY", scope_code="PARTIAL",
        occurred_at="2026-07-01T00:00:00Z",
        damage_estimate_cents=40000000, damaged_area_sqft=20000,
    )
    validate_success(
        api.elect_loss_outcome(
            event["id"], f.election_payload("TERMINATE"),
            make_ground_tenant_headers(lessee["id"]),
        )
    )
    assert_fields(fx.read_lease(api, lease_a["id"]),
                  lease_status="TERMINATED", rent_status="FROZEN")
    assert fx.read_lease(api, lease_b["id"])["lease_status"] == "ACTIVE"
    return lessee, lease_a, lease_b


def test_a_non_operative_lease_answers_not_operative_not_chronology(api):
    """PRD §2.8: "A lease whose `lease_status` is `TERMINATED`, `EXPIRED` or `REVERTED` accepts no new revaluations, statements, alteration requests, transfer requests, mortgages or default notices; those six creates are refused with `ERR_LEASE_NOT_OPERATIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/terminated_lease_statement_rejected_by_priority_7_not_priority_11
    """
    lessee, lease_a, _lease_b = _terminated_lease_and_control(api)
    tenant = make_ground_tenant_headers(lessee["id"])
    version = fx.lease_version(api, lease_a["id"])

    # Priority 7 and priority 11 are both live.
    validate_error(
        api.file_statement(
            f.statement_payload(lease_a["id"], version,
                                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_LEASE_NOT_OPERATIVE,
        expected_status=409,
    )

    # Priority 7 alone is live; the answer is unchanged.
    validate_error(
        api.file_statement(
            f.statement_payload(lease_a["id"], version,
                                "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_LEASE_NOT_OPERATIVE,
        expected_status=409,
    )
    assert fx.lease_version(api, lease_a["id"]) == version


def test_the_control_lease_shows_the_chronology_rule_is_still_live(api):
    """PRD §2.8: "Checks are evaluated in the following fixed priority order, and the **first** rule that fails determines the response; later rules are not consulted."

    Design: Difficulty/priority_pair_validation_conflict/terminated_lease_statement_rejected_by_priority_7_not_priority_11
    """
    lessee, _lease_a, lease_b = _terminated_lease_and_control(api)
    tenant = make_ground_tenant_headers(lessee["id"])
    version = fx.lease_version(api, lease_b["id"])

    validate_error(
        api.file_statement(
            f.statement_payload(lease_b["id"], version,
                                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                                120000000),
            tenant,
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )
    assert fx.lease_version(api, lease_b["id"]) == version

    rows, meta = validate_paginated(api.list_statements(tenant))
    assert rows == []
    assert meta["total_count"] == 0
