"""Tenant households: the three parallel state dimensions, the tiered notice and
relocation computation, the right-of-first-refusal window and the relocation ledger.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_relocation_conserved,
)
from test_helpers.factories import component_payload, roof_standard
from test_helpers.fixtures import (
    certify_plat,
    make_household,
    make_package,
    make_passed_gate,
    make_project,
    make_unit,
    serve_notice,
    set_clock,
)
from test_helpers.test_users import (
    escrow_headers,
    sponsor_headers,
    tenant_headers,
)


def _platted_project(api, unit_number="101", total_unit_count=2):
    """A project whose declaration package is PLAT_CERTIFIED over one included unit."""
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, total_unit_count)
    make_passed_gate(api, project["id"], [roof_standard()])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    unit = make_unit(api, package["id"], unit_number, 10000, 1, 900, "as-built")
    certify_plat(api, package["id"])
    return {"project": project, "package": package, "unit": unit}


def test_relocation_disbursement_syncs_project_relocation_ledger(api):
    """PRD: The payment moves `relocation_status` `ACCRUED → PAID`, writes the
    household's `relocation_paid_cents`, adds the amount to the project's
    `relocation_paid_cents` and subtracts the identical amount from
    `relocation_outstanding_cents`, keeping the delta at 0.

    Design: Corner/state_machines/relocation_disbursement_syncs_project_relocation_ledger
    """
    built = _platted_project(api)
    project_id = built["project"]["id"]
    household = make_household(
        api,
        project_id,
        "HH-1",
        "2026-01-01T00:00:00Z",
        300000,
        "NONE",
        built["unit"]["id"],
    )
    serve_notice(api, household["id"])

    before = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert_cents(before["relocation_assistance_cents"], 900000, "assistance")
    assert before["relocation_status"] == "ACCRUED"
    assert before["notice_period_days"] == 120
    assert_instant(before["vacate_deadline_at"], "2026-11-29T00:00:00Z")
    assert_instant(before["rofr_expires_at"], "2026-10-30T00:00:00Z")

    ledger = validate_success(api.relocation_summary(project_id, sponsor_headers()))
    assert_cents(ledger["relocation_obligation_accrued_cents"], 900000, "accrued")
    assert_cents(ledger["relocation_paid_cents"], 0, "paid")
    assert_cents(ledger["relocation_outstanding_cents"], 900000, "outstanding")

    paid = validate_success(
        api.disburse_relocation(household["id"], 900000, escrow_headers()),
        expected_status=201,
    )
    assert paid is not None

    after = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert after["relocation_status"] == "PAID"
    assert_cents(after["relocation_paid_cents"], 900000, "household paid")

    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["relocation_obligation_accrued_cents"], 900000, "accrued")
    assert_cents(project["relocation_paid_cents"], 900000, "paid")
    assert_cents(project["relocation_reversed_cents"], 0, "reversed")
    assert_cents(project["relocation_outstanding_cents"], 0, "outstanding")
    assert_relocation_conserved(project)


def test_relocation_disbursement_must_equal_accrued_assistance_exactly(api):
    """PRD: The amount must equal the household's `relocation_assistance_cents`
    **exactly**; any other figure, higher or lower, is refused with
    `ERR_RELOCATION_AMOUNT_MISMATCH` (422).

    Design: Corner/validations/relocation_disbursement_must_equal_accrued_assistance_exactly
    """
    built = _platted_project(api)
    project_id = built["project"]["id"]
    household = make_household(
        api,
        project_id,
        "HH-1",
        "2026-01-01T00:00:00Z",
        300000,
        occupied_unit_id=built["unit"]["id"],
    )
    serve_notice(api, household["id"])

    before = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert_cents(before["relocation_assistance_cents"], 900000, "assistance")
    assert before["relocation_status"] == "ACCRUED"
    assert before["notice_period_days"] == 120
    assert_instant(before["vacate_deadline_at"], "2026-11-29T00:00:00Z")

    validate_error(
        api.disburse_relocation(household["id"], 800000, escrow_headers()),
        "ERR_RELOCATION_AMOUNT_MISMATCH",
        expected_status=422,
    )
    unpaid = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert unpaid["relocation_status"] == "ACCRUED"
    assert_cents(unpaid["relocation_paid_cents"], 0, "household paid")
    assert unpaid["version"] == before["version"]
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["relocation_paid_cents"], 0, "project paid")
    assert_cents(project["relocation_outstanding_cents"], 900000, "outstanding")

    validate_success(
        api.disburse_relocation(household["id"], 900000, escrow_headers()),
        expected_status=201,
    )
    paid = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert paid["relocation_status"] == "PAID"
    assert_cents(paid["relocation_paid_cents"], 900000, "household paid")
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["relocation_paid_cents"], 900000, "project paid")
    assert_cents(project["relocation_outstanding_cents"], 0, "outstanding")
    assert_relocation_conserved(project)


def test_occupancy_outcome_before_the_vacate_deadline_is_refused(api):
    """PRD: The sponsor then records how the tenancy actually ended by supplying an
    `outcome`. This is refused with `ERR_NOTICE_PERIOD_NOT_ELAPSED` (409) unless the
    logical clock has reached `vacate_deadline_at`.

    Design: Corner/validations/occupancy_outcome_before_the_vacate_deadline_is_refused
    """
    built = _platted_project(api)
    household = make_household(
        api,
        built["project"]["id"],
        "HH-1",
        "2026-01-01T00:00:00Z",
        300000,
        occupied_unit_id=built["unit"]["id"],
    )
    serve_notice(api, household["id"])

    set_clock(api, "2026-12-01T00:00:00Z")
    validate_success(
        api.recalculate_posture(built["project"]["id"], sponsor_headers())
    )
    set_clock(api, "2026-11-01T00:00:00Z")

    before = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert_instant(before["vacate_deadline_at"], "2026-11-29T00:00:00Z")
    assert before["notice_status"] == "VACATE_DUE"

    validate_error(
        api.occupancy_outcome(household["id"], "HOLDOVER", sponsor_headers()),
        "ERR_NOTICE_PERIOD_NOT_ELAPSED",
        expected_status=409,
    )
    refused = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert refused["notice_status"] == "VACATE_DUE"
    assert refused["version"] == before["version"]

    set_clock(api, "2026-11-29T00:00:00Z")
    validate_success(
        api.occupancy_outcome(household["id"], "HOLDOVER", sponsor_headers()),
        expected_status=201,
    )
    after = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert after["notice_status"] == "HOLDOVER"
    assert_instant(after["vacate_deadline_at"], "2026-11-29T00:00:00Z")


def test_tenant_notice_tier_branch_cap_uplift_cap_floor(api):
    """PRD: Step one multiplies `monthly_rent_cents` by 3 and rounds half up to whole
    cents. Step two caps the running amount at 1500000 cents — fifteen thousand
    dollars. Step three applies an uplift only when `protected_class` is `ELDERLY` or
    `DISABLED`, multiplying the running amount by 3 and dividing by 2 and rounding half
    up. Step four applies the 1500000-cent cap **again**. Step five raises the running
    amount to a floor of 250000 cents — two thousand five hundred dollars — if it sits
    below it.

    Design: Difficulty/combinatorial_formula/tenant_notice_tier_branch_cap_uplift_cap_floor
    """
    project = make_project(api, "12 Merle Lane, Hartford CT", 1969, 3)
    make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        report_label="ER-C",
    )
    package = make_package(
        api, project["id"], "CENTERLINE", "s3://decl/merle.pdf", "s3://bylaws/merle.pdf"
    )
    u1 = make_unit(api, package["id"], "M-1", 3333, 1, 700, "wall centerlines")
    u2 = make_unit(api, package["id"], "M-2", 3333, 2, 700, "wall centerlines")
    u3 = make_unit(api, package["id"], "M-3", 3334, 3, 720, "wall centerlines")
    certify_plat(api, package["id"])

    h1 = make_household(
        api, project["id"], "H-1", "2019-01-01T00:00:00Z", 900000, "ELDERLY", u1["id"]
    )
    h2 = make_household(
        api, project["id"], "H-2", "2019-01-01T00:00:00Z", 60000, "ELDERLY", u2["id"]
    )
    h3 = make_household(
        api, project["id"], "H-3", "2026-06-01T00:00:00Z", 60000, "NONE", u3["id"]
    )

    served = [
        validate_success(api.serve_notice(household["id"], sponsor_headers()), 201)
        for household in (h1, h2, h3)
    ]
    for row in served:
        assert row["notice_status"] == "NOTICE_SERVED"
        assert row["rofr_status"] == "OFFERED"
        assert row["relocation_status"] == "ACCRUED"
        assert_instant(row["notice_served_at"], "2026-08-01T00:00:00Z")
        assert_instant(row["rofr_expires_at"], "2026-10-30T00:00:00Z")

    first, second, third = served
    assert first["notice_period_days"] == 360
    assert_instant(first["vacate_deadline_at"], "2027-07-27T00:00:00Z")
    assert_cents(first["relocation_assistance_cents"], 1500000, "H-1 assistance")

    assert second["notice_period_days"] == 360
    assert_instant(second["vacate_deadline_at"], "2027-07-27T00:00:00Z")
    assert_cents(second["relocation_assistance_cents"], 270000, "H-2 assistance")

    assert third["notice_period_days"] == 120
    assert_instant(third["vacate_deadline_at"], "2026-11-29T00:00:00Z")
    assert_cents(third["relocation_assistance_cents"], 250000, "H-3 assistance")

    ledger = validate_success(api.relocation_summary(project["id"], sponsor_headers()))
    assert_cents(ledger["relocation_obligation_accrued_cents"], 2020000, "accrued")
    assert_cents(ledger["relocation_outstanding_cents"], 2020000, "outstanding")
    assert_cents(ledger["relocation_paid_cents"], 0, "paid")
    assert_cents(ledger["relocation_reversed_cents"], 0, "reversed")
    assert_cents(ledger["relocation_reconciliation_delta_cents"], 0, "delta")

    final = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert final["posture"] == "RESTRICTED"
    assert_relocation_conserved(final)


def test_tenant_household_three_parallel_state_dimensions(api):
    """PRD: `EXERCISE` additionally requires that `occupied_unit_id` be non-null and
    reference an `INCLUDED` unit of the same project, again guarded by
    `ERR_ROFR_UNIT_NOT_LINKED`, and it cancels the eviction outright — `rofr_status`
    moves `OFFERED → EXERCISED`, `notice_status` moves `NOTICE_SERVED →
    NOTICE_WITHDRAWN` with `vacate_deadline_at` cleared to null, and the relocation
    obligation is reversed.

    Design: Difficulty/non_linear_state_machine/tenant_household_three_parallel_state_dimensions
    """
    project = make_project(api, "3 Windlass Alley, Newport RI", 1966, 2)
    make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        report_label="ER-E",
    )
    package = make_package(
        api,
        project["id"],
        "PAINT_TO_PAINT",
        "s3://decl/windlass.pdf",
        "s3://bylaws/windlass.pdf",
    )
    u1 = make_unit(api, package["id"], "W-1", 5000, 1, 760, "interior paint surfaces")
    make_unit(api, package["id"], "W-2", 5000, 2, 760, "interior paint surfaces")
    certify_plat(api, package["id"])
    household = make_household(
        api, project["id"], "H-A", "2019-01-01T00:00:00Z", 400000, "NONE", u1["id"]
    )
    served = validate_success(
        api.serve_notice(household["id"], sponsor_headers()), expected_status=201
    )
    assert served["notice_period_days"] == 270
    assert_instant(served["vacate_deadline_at"], "2027-04-28T00:00:00Z")
    assert_instant(served["rofr_expires_at"], "2026-10-30T00:00:00Z")
    assert_cents(served["relocation_assistance_cents"], 1200000, "assistance")

    validate_success(
        api.disburse_relocation(household["id"], 1200000, escrow_headers()),
        expected_status=201,
    )
    paid = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert paid["notice_status"] == "NOTICE_SERVED"
    assert paid["rofr_status"] == "OFFERED"
    assert paid["relocation_status"] == "PAID"
    assert_cents(paid["relocation_paid_cents"], 1200000, "household paid")
    mid = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert_cents(mid["relocation_paid_cents"], 1200000, "project paid")
    assert_cents(mid["relocation_outstanding_cents"], 0, "outstanding")

    validate_success(
        api.rofr_response(
            household["id"], "EXERCISE", tenant_headers(household["id"])
        ),
        expected_status=201,
    )
    after = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert after["rofr_status"] == "EXERCISED"
    assert after["notice_status"] == "NOTICE_WITHDRAWN"
    assert after["vacate_deadline_at"] is None
    assert after["relocation_status"] == "REVERSED"
    assert_cents(after["relocation_reversed_cents"], 1200000, "household reversed")
    assert_cents(after["relocation_paid_cents"], 0, "household paid")
    assert after["notice_period_days"] == 270
    assert_instant(after["rofr_expires_at"], "2026-10-30T00:00:00Z")

    ledger = validate_success(api.relocation_summary(project["id"], sponsor_headers()))
    assert_cents(ledger["relocation_obligation_accrued_cents"], 1200000, "accrued")
    assert_cents(ledger["relocation_paid_cents"], 0, "paid")
    assert_cents(ledger["relocation_reversed_cents"], 1200000, "reversed")
    assert_cents(ledger["relocation_outstanding_cents"], 0, "outstanding")
    assert_cents(ledger["relocation_reconciliation_delta_cents"], 0, "delta")
    assert_relocation_conserved(
        validate_success(api.get_project(project["id"], sponsor_headers()))
    )

    unit = validate_success(api.get_unit(u1["id"], sponsor_headers()))
    assert unit["declaration_status"] == "INCLUDED"
    assert unit["sale_status"] == "UNSOLD"


def test_rofr_window_expired_beats_rofr_unit_not_linked(api):
    """PRD: The window is inclusive — the answer is admissible while the logical clock
    is **at or before** `rofr_expires_at`, so an answer landing exactly on the expiry
    instant is still inside the window, while one instant later is refused with
    `ERR_ROFR_WINDOW_EXPIRED` (409).

    Design: Difficulty/priority_pair_validation_conflict/rofr_window_expired_beats_rofr_unit_not_linked
    """
    project = make_project(api, "77 Dentil Court, Malden MA", 1959, 2)
    make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        report_label="ER-D",
    )
    package = make_package(
        api,
        project["id"],
        "STUD_TO_STUD",
        "s3://decl/dentil.pdf",
        "s3://bylaws/dentil.pdf",
    )
    u1 = make_unit(api, package["id"], "D-1", 5000, 1, 950, "stud faces")
    u2 = make_unit(api, package["id"], "D-2", 5000, 2, 950, "stud faces")
    certify_plat(api, package["id"])
    household = make_household(
        api, project["id"], "H-D", "2019-01-01T00:00:00Z", 400000, "NONE", u1["id"]
    )
    serve_notice(api, household["id"])
    validate_success(
        api.withdraw_unit(
            u1["id"],
            sponsor_headers(),
            {"withdrawal_reason": "tenant unit retained as a rental"},
        )
    )
    set_clock(api, "2026-10-30T00:00:01Z")

    before = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert_instant(before["rofr_expires_at"], "2026-10-30T00:00:00Z")

    validate_error(
        api.rofr_response(
            household["id"], "EXERCISE", tenant_headers(household["id"])
        ),
        "ERR_ROFR_WINDOW_EXPIRED",
        expected_status=409,
    )
    refused = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert refused["rofr_status"] == "OFFERED"
    assert refused["notice_status"] == "NOTICE_SERVED"
    assert refused["relocation_status"] == "ACCRUED"
    assert_instant(refused["rofr_expires_at"], "2026-10-30T00:00:00Z")
    assert refused["version"] == before["version"]

    project_row = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert_cents(project_row["relocation_reversed_cents"], 0, "reversed")
    assert_cents(project_row["relocation_reconciliation_delta_cents"], 0, "delta")

    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "declaration_status"
    ] == "WITHDRAWN"
    assert validate_success(api.get_unit(u2["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 10000

    # the winner is inclusive: at the exact expiry instant the second-ranked
    # violation surfaces instead.
    set_clock(api, "2026-10-30T00:00:00Z")
    validate_error(
        api.rofr_response(
            household["id"], "EXERCISE", tenant_headers(household["id"])
        ),
        "ERR_ROFR_UNIT_NOT_LINKED",
        expected_status=409,
    )
    still = validate_success(api.get_household(household["id"], sponsor_headers()))
    assert still["rofr_status"] == "OFFERED"
    assert still["version"] == before["version"]
