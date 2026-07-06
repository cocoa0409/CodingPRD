"""Occasion report prize-allowance caps: nested-min annual arm, per-occasion cap, precedence."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_orgofficer_headers,
    create_active_license, schedule_occasion, create_held_occasion,
    create_reported_occasion, report_occasion_payload,
)

REGULATOR = TEST_USERS["regulator_headers"]


def _setup_annual_arm_binds(api):
    """occ1 REPORTED with prizes 700000 (settled 700000); occ2 HELD planned 300000.

    For occ2 the annual arm binds: allowance = min(800000, 1000000 - 700000 - 0) = 300000.
    Returns (org, license, occ2).
    """
    org, lic = create_active_license(license_type="BINGO")
    create_reported_occasion(
        org["id"], lic["id"],
        occasion_overrides={"scheduled_start": "2026-06-01T18:00:00Z",
                            "scheduled_end": "2026-06-01T22:00:00Z",
                            "planned_gross_cents": 1_000_000,
                            "planned_prize_pool_cents": 700_000,
                            "planned_expenses_cents": 50_000},
        report_overrides={"gross_receipts_cents": 1_000_000, "prizes_paid_cents": 700_000,
                          "expenses_cents": 50_000},
    )
    occ2 = create_held_occasion(org["id"], lic["id"], scheduled_start="2026-06-08T18:00:00Z",
                                scheduled_end="2026-06-08T22:00:00Z",
                                planned_gross_cents=500_000, planned_prize_pool_cents=300_000,
                                planned_expenses_cents=20_000)
    return org, lic, occ2


def test_report_over_annual_arm_rejected(api):
    """PRD §3.4: "Second, the annual allowance still available to this specific occasion,
    computed as the license's `annual_prize_limit_cents`, minus its `prize_settled_cents`,
    minus the committed prizes of all *other* occasions (that is, the license's current
    `prize_committed_cents` minus this occasion's own `planned_prize_pool_cents`)."
    PRD §3.4: "The boundary is inclusive: `prizes_paid_cents` equal to the allowance is
    accepted, and one cent above it is rejected with `ERR_PRIZE_LIMIT_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/prize_allowance_nested_min_annual_arm_binds
    """
    org, lic, occ2 = _setup_annual_arm_binds(api)
    officer = make_orgofficer_headers(org["id"])
    res = api.report_occasion(
        occ2["id"],
        report_occasion_payload(gross_receipts_cents=400_000, prizes_paid_cents=300_001,
                                expenses_cents=10_000),
        officer,
    )
    validate_error(res, "ERR_PRIZE_LIMIT_EXCEEDED")
    fetched = validate_success(api.get_occasion(occ2["id"], officer), 200)
    assert fetched["status"] == "HELD"


def test_report_at_annual_arm_allowed(api):
    """PRD §3.4: "The allowance is the minimum of those two figures."
    PRD §3.4: "The boundary is inclusive: `prizes_paid_cents` equal to the allowance is
    accepted, and one cent above it is rejected with `ERR_PRIZE_LIMIT_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/prize_allowance_nested_min_annual_arm_binds
    """
    org, lic, occ2 = _setup_annual_arm_binds(api)
    officer = make_orgofficer_headers(org["id"])
    reported = validate_success(
        api.report_occasion(
            occ2["id"],
            report_occasion_payload(gross_receipts_cents=400_000, prizes_paid_cents=300_000,
                                    expenses_cents=10_000),
            officer),
        200,
    )
    assert reported["status"] == "REPORTED"
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_settled_cents"] == 1_000_000
    assert read["prize_allowance_remaining_cents"] == 0


# ─── Difficulty: per-occasion cap inclusive boundary (BINGO 800000) ──
def test_report_at_per_occasion_cap_succeeds(api):
    """PRD §3.4: "First, a per-occasion cap selected by `occasion_type` — 800,000 cents for
    a `BINGO` occasion, 1,500,000 cents for a `RAFFLE` occasion."
    PRD §3.4: "The boundary is inclusive: `prizes_paid_cents` equal to the allowance is
    accepted, and one cent above it is rejected with `ERR_PRIZE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/prize_at_per_occasion_cap_inclusive
    """
    org, lic = create_active_license(license_type="BINGO")
    officer = make_orgofficer_headers(org["id"])
    occ = create_held_occasion(org["id"], lic["id"], planned_gross_cents=1_000_000,
                               planned_prize_pool_cents=800_000, planned_expenses_cents=50_000)
    reported = validate_success(
        api.report_occasion(occ["id"],
                            report_occasion_payload(gross_receipts_cents=1_000_000,
                                                    prizes_paid_cents=800_000,
                                                    expenses_cents=50_000),
                            officer),
        200,
    )
    assert reported["status"] == "REPORTED"
    assert reported["prizes_paid_cents"] == 800_000
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_settled_cents"] == 800_000
    assert read["prize_allowance_remaining_cents"] == 200_000


def test_report_one_over_per_occasion_cap_rejected(api):
    """PRD §3.4: "The boundary is inclusive: `prizes_paid_cents` equal to the allowance is
    accepted, and one cent above it is rejected with `ERR_PRIZE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/prize_at_per_occasion_cap_inclusive
    """
    org, lic = create_active_license(license_type="BINGO")
    officer = make_orgofficer_headers(org["id"])
    occ = create_held_occasion(org["id"], lic["id"], planned_gross_cents=1_000_000,
                               planned_prize_pool_cents=800_000, planned_expenses_cents=50_000)
    res = api.report_occasion(
        occ["id"],
        report_occasion_payload(gross_receipts_cents=1_000_000, prizes_paid_cents=800_001,
                                expenses_cents=50_000),
        officer,
    )
    validate_error(res, "ERR_PRIZE_LIMIT_EXCEEDED")


# ─── Difficulty: state legality (7) outranks fiscal caps (11) ────────
def test_report_scheduled_occasion_returns_state_error(api):
    """PRD §3.4: "Reporting is permitted only when the occasion is `HELD` (else
    `ERR_INVALID_STATE`), only while the license is `ACTIVE` (else `ERR_LICENSE_NOT_ACTIVE`),
    and only when the reported `prizes_paid_cents` does not exceed the occasion's prize
    allowance (else `ERR_PRIZE_LIMIT_EXCEEDED`, described below)."
    PRD §2.10: "A lower-numbered check that fails masks every higher-numbered one, so a
    request that both lacks permission and targets a missing resource is rejected as
    `ERR_FORBIDDEN`, not `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/report_state_beats_fiscal
    """
    org, lic = create_active_license(license_type="BINGO")
    officer = make_orgofficer_headers(org["id"])
    occ = schedule_occasion(org["id"], lic["id"], planned_prize_pool_cents=50_000)
    res = api.report_occasion(
        occ["id"],
        report_occasion_payload(gross_receipts_cents=1_000_000, prizes_paid_cents=900_000,
                                expenses_cents=10_000),
        officer,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_report_scheduled_occasion_leaves_state_unchanged(api):
    """PRD §3.4: "Reporting closes the occasion out. The `OrgOfficer` supplies the actuals
    `gross_receipts_cents`, `prizes_paid_cents`, and `expenses_cents`, advancing the
    occasion from `HELD` to `REPORTED`."

    Design: Difficulty/priority_pair_validation_conflict/report_state_beats_fiscal
    """
    org, lic = create_active_license(license_type="BINGO")
    officer = make_orgofficer_headers(org["id"])
    occ = schedule_occasion(org["id"], lic["id"], planned_prize_pool_cents=50_000)
    api.report_occasion(
        occ["id"],
        report_occasion_payload(gross_receipts_cents=1_000_000, prizes_paid_cents=900_000,
                                expenses_cents=10_000),
        officer,
    )
    fetched = validate_success(api.get_occasion(occ["id"], officer), 200)
    assert fetched["status"] == "SCHEDULED"
