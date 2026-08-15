"""Branch lifecycle, closure notice, the access-analysis score, and the branch
cascades into the public file's posture."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_demographic_profile,
    assert_posture_invariants,
    create_active_area,
    create_area,
    create_complete_public_file,
    create_open_branch,
    create_proposed_branch,
    create_submitted_branch_opening,
    get_branch,
    get_public_file,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue B — Corner/calculations
# ---------------------------------------------------------------------------

def test_access_score_zero_open_branches_yields_zero(api, bank_examiner_headers):
    """PRD §3.9: "It reports `open_branch_count`, the number of the area's
    branches in `OPEN`; with no open branches, `access_score` and
    `lmi_branch_pct` are both 0."
    PRD §3.9: "The benchmark, `benchmark_lmi_tract_pct`, is the `lmi_tract_pct`
    of the area's `CURRENT` demographic profile with the latest `data_year`, or
    0 when the area has no profile."

    Design: Corner/calculations/access_score_zero_open_branches_yields_zero
    """
    area = create_area(
        area_code="AA-C1", msa_code="19100", state_code="TX", census_tracts=["T1"],
    )
    add_demographic_profile(area, data_year=2020)
    data = validate_success(api.get_access_analysis(area["id"], bank_examiner_headers))
    assert data["open_branch_count"] == 0
    assert data["lmi_branch_pct"] == 0
    assert data["benchmark_lmi_tract_pct"] == pytest.approx(0.4, abs=1e-9)
    assert data["access_score"] == 0


def test_access_score_lmi_closure_penalty_applied(
    api, cra_officer_headers, bank_executive_headers,
):
    """PRD §3.9: "The raw score starts from a base of 50, adds 100 times the
    difference between `lmi_branch_pct` and the benchmark, and subtracts 5
    points per closure counted in `lmi_closures_12m`; `access_score` is that raw
    value rounded half up to two decimal places and then clamped to a floor of 0
    and a ceiling of 100."
    PRD §3.9: "`lmi_closures_12m` counts the area's branches that are `CLOSED`,
    sit in `LOW` or `MODERATE` tracts, and whose `closed_date` falls later than
    the date 365 days before the logical-clock date and on or before the
    logical-clock date."

    Design: Corner/calculations/access_score_lmi_closure_penalty_applied
    """
    area = create_area(
        area_code="AA-C2", msa_code="16980", state_code="IL",
        census_tracts=["T1", "T2", "T3"],
    )
    add_demographic_profile(area, data_year=2020)  # benchmark lmi_tract_pct 0.4

    create_open_branch(area["id"], branch_code="BR-P1", census_tract="T1",
                       tract_income_level="MODERATE")
    create_open_branch(area["id"], branch_code="BR-P2", census_tract="T2",
                       tract_income_level="UPPER")
    p3 = create_open_branch(area["id"], branch_code="BR-P3", census_tract="T3",
                            tract_income_level="LOW")
    # Notice 2026-04-01 is 122 days before the 2026-08-01 logical-clock date.
    closed = validate_success(
        api.close_branch(p3["id"], {"notice_posted_date": "2026-04-01"},
                         bank_executive_headers)
    )
    assert closed["status"] == "CLOSED"

    data = validate_success(api.get_access_analysis(area["id"], cra_officer_headers))
    assert data["open_branch_count"] == 2
    assert data["lmi_branch_pct"] == pytest.approx(0.5, abs=1e-9)
    assert data["lmi_closures_12m"] == 1
    # 50 + 100 * (0.5 - 0.4) - 5 * 1 = 55.00
    assert data["access_score"] == pytest.approx(55.00, abs=1e-9)


# ---------------------------------------------------------------------------
# Queue B — Corner/state_machines
# ---------------------------------------------------------------------------

def test_staged_branch_open_blocked_until_application_approved(
    api, bank_executive_headers, bank_examiner_headers,
):
    """PRD §3.5: "When the branch carries a non-null `expansion_application_id`,
    the referenced application must already be `APPROVED` — opening against an
    undecided or denied application is rejected with
    `ERR_APPLICATION_NOT_APPROVED` — while a directly created branch faces no
    such check. Opening stamps `opened_date` with the logical-clock date".

    Design: Corner/state_machines/staged_branch_open_blocked_until_application_approved
    """
    area = create_active_area(
        area_code="AA-SM8", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    app, branch_id = create_submitted_branch_opening(
        area["id"], branch_code="BR-S", branch_census_tract="T1",
        branch_tract_income_level="MODERATE",
    )

    blocked = api.open_branch(branch_id, bank_executive_headers)
    validate_error(blocked, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)
    assert get_branch(branch_id)["status"] == "PROPOSED"

    validate_success(
        api.decide_expansion_application(
            app["id"], {"decision": "APPROVE", "decision_reason": "meets credit needs"},
            bank_examiner_headers,
        )
    )
    opened = validate_success(api.open_branch(branch_id, bank_executive_headers))
    assert opened["status"] == "OPEN"
    assert opened["opened_date"] == "2026-08-01"


def test_closed_branch_is_terminal(api, bank_executive_headers):
    """PRD §3.5: "A valid close stamps both `closed_date` and
    `notice_posted_date`, flips the public file's `branch_list_current` to false
    with the usual posture recompute, and increments `version`. `CLOSED` is
    terminal."
    PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/closed_branch_is_terminal
    """
    area = create_active_area(
        area_code="AA-SM6", msa_code="16980", state_code="IL", census_tracts=["T1"],
    )
    branch = create_open_branch(area["id"], branch_code="BR-T", tract_income_level="LOW")
    closed = validate_success(
        api.close_branch(branch["id"], {"notice_posted_date": "2026-04-01"},
                         bank_executive_headers)
    )
    assert closed["status"] == "CLOSED"

    resp = api.open_branch(branch["id"], bank_executive_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_branch(branch["id"])["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_branch_close_notice_under_90_days_rejected(api, bank_executive_headers):
    """PRD §3.5: "The close request carries the `notice_posted_date` on which
    the bank posted its public closure notice, and at least 90 days must
    separate that date from the logical-clock date — fewer is rejected with
    `ERR_CLOSURE_NOTICE_SHORT`."

    Design: Corner/validations/branch_close_notice_under_90_days_rejected
    """
    area = create_active_area(
        area_code="AA-V6", msa_code="16980", state_code="IL", census_tracts=["T1"],
    )
    # 2026-05-04 -> 2026-08-01 is 89 days: one day short, rejected.
    branch_short = create_open_branch(
        area["id"], branch_code="BR-N1", tract_income_level="MIDDLE"
    )
    short_resp = api.close_branch(
        branch_short["id"], {"notice_posted_date": "2026-05-04"}, bank_executive_headers
    )
    validate_error(short_resp, ApiErrorId.ERR_CLOSURE_NOTICE_SHORT)
    assert get_branch(branch_short["id"])["status"] == "OPEN"

    # 2026-05-03 -> 2026-08-01 is exactly 90 days: "at least 90 days" passes.
    branch_ok = create_open_branch(
        area["id"], branch_code="BR-N2", tract_income_level="MIDDLE"
    )
    ok_resp = api.close_branch(
        branch_ok["id"], {"notice_posted_date": "2026-05-03"}, bank_executive_headers
    )
    closed = validate_success(ok_resp)
    assert closed["status"] == "CLOSED"
    assert closed["closed_date"] == "2026-08-01"
    assert closed["notice_posted_date"] == "2026-05-03"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/combinatorial_formula/branch_access_score_multi_input_threshold
# ---------------------------------------------------------------------------

def test_branch_access_score_multi_input_threshold(api, cra_officer_headers):
    """PRD §3.9: "Otherwise `lmi_branch_pct` is the share of open branches whose
    `tract_income_level` is `LOW` or `MODERATE`, rounded half up to four decimal
    places."
    PRD §3.9: "The raw score starts from a base of 50, adds 100 times the
    difference between `lmi_branch_pct` and the benchmark, and subtracts 5
    points per closure counted in `lmi_closures_12m`; `access_score` is that raw
    value rounded half up to two decimal places and then clamped to a floor of 0
    and a ceiling of 100."

    Design: Difficulty/combinatorial_formula/branch_access_score_multi_input_threshold
    """
    area = create_active_area(
        area_code="AA-CF1", msa_code="16980", state_code="IL",
        census_tracts=["T1", "T2", "T3", "T4"],
    )
    _, area = add_demographic_profile(area, data_year=2020)  # benchmark 0.4

    create_open_branch(area["id"], branch_code="BR-1", census_tract="T1",
                       tract_income_level="MODERATE")
    for i, tract in enumerate(("T2", "T3", "T4"), start=2):
        create_open_branch(area["id"], branch_code=f"BR-{i}", census_tract=tract,
                           tract_income_level="UPPER")

    data = validate_success(api.get_access_analysis(area["id"], cra_officer_headers))
    assert data["open_branch_count"] == 4
    assert data["lmi_branch_pct"] == pytest.approx(0.25, abs=1e-9)
    assert data["benchmark_lmi_tract_pct"] == pytest.approx(0.4, abs=1e-9)
    assert data["lmi_closures_12m"] == 0
    # 50 + 100 * (0.25 - 0.40) - 0 = 35.00
    assert data["access_score"] == pytest.approx(35.00, abs=1e-9)


def test_branch_access_score_clamped_at_ceiling(api, cra_officer_headers):
    """PRD §3.9: "`access_score` is that raw value rounded half up to two
    decimal places and then clamped to a floor of 0 and a ceiling of 100."

    Design: Difficulty/combinatorial_formula/branch_access_score_multi_input_threshold
    """
    area = create_active_area(
        area_code="AA-CF1B", msa_code="16980", state_code="IL",
        census_tracts=["T1", "T2", "T3", "T4"],
    )
    _, area = add_demographic_profile(area, data_year=2020)  # benchmark 0.4

    for i, tract in enumerate(("T1", "T2", "T3", "T4"), start=1):
        create_open_branch(area["id"], branch_code=f"BR-C{i}", census_tract=tract,
                           tract_income_level="LOW")

    data = validate_success(api.get_access_analysis(area["id"], cra_officer_headers))
    assert data["open_branch_count"] == 4
    assert data["lmi_branch_pct"] == pytest.approx(1.0, abs=1e-9)
    # Raw 50 + 100 * (1.0 - 0.4) = 110 -> clamped to the ceiling of 100.
    assert data["access_score"] == pytest.approx(100.00, abs=1e-9)


# ---------------------------------------------------------------------------
# Queue A — Difficulty/transitive_cascade/branch_close_cascade_flips_public_file_posture
# ---------------------------------------------------------------------------

def test_branch_close_cascade_flips_public_file_posture(
    api, bank_executive_headers, cra_officer_headers,
):
    """PRD §2.10: "Opening or closing a branch sets `branch_list_current` to
    false."
    PRD §2.10: "Every one of these cascades recomputes the posture immediately."
    PRD §3.5: "A valid close stamps both `closed_date` and `notice_posted_date`,
    flips the public file's `branch_list_current` to false with the usual
    posture recompute, and increments `version`."

    Design: Difficulty/transitive_cascade/branch_close_cascade_flips_public_file_posture
    """
    area = create_active_area(
        area_code="AA-TC2", msa_code="16980", state_code="IL", census_tracts=["T1"],
        annual_cd_budget_cents=1000000,
    )
    branch = create_open_branch(area["id"], branch_code="BR-C", tract_income_level="LOW")
    public_file = create_complete_public_file("Second Test Bank")
    assert public_file["posture"] == "COMPLETE"

    closed = validate_success(
        api.close_branch(branch["id"], {"notice_posted_date": "2026-04-01"},
                         bank_executive_headers)
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_date"] == "2026-08-01"

    file_after = get_public_file(public_file["id"])
    assert file_after["branch_list_current"] is False
    assert file_after["posture"] == "INCOMPLETE"
    assert_posture_invariants(file_after)


def test_branch_open_cascade_flips_public_file_posture(
    api, bank_executive_headers,
):
    """PRD §2.10: "Opening or closing a branch sets `branch_list_current` to
    false."
    PRD §2.10: "Every one of these cascades recomputes the posture immediately."

    Design: Difficulty/transitive_cascade/branch_close_cascade_flips_public_file_posture
    """
    area = create_active_area(
        area_code="AA-TC2B", msa_code="16980", state_code="IL", census_tracts=["T1"],
    )
    branch = create_proposed_branch(
        area["id"], branch_code="BR-O", tract_income_level="LOW"
    )
    public_file = create_complete_public_file("Third Test Bank")
    assert public_file["posture"] == "COMPLETE"

    opened = validate_success(api.open_branch(branch["id"], bank_executive_headers))
    assert opened["status"] == "OPEN"

    file_after = get_public_file(public_file["id"])
    assert file_after["branch_list_current"] is False
    assert file_after["posture"] == "INCOMPLETE"
    assert_posture_invariants(file_after)
