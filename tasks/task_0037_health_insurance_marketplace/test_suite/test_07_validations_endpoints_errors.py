"""Business validations, listing/pagination, computed reads, FK errors (queue B)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    register_benchmark_plan,
    register_plan,
    create_household,
    create_household_with_primary,
    create_application,
    submit_application,
    determine_application,
    household_version,
    setup_reconciliation,
    make_applicant_headers,
    TEST_USERS,
)


# ───────────── validations ─────────────

def test_duplicate_primary_member_rejected(api):
    """PRD §3.1: "a household may contain exactly one `PRIMARY` member — an attempt to add a second `PRIMARY` is rejected with `ERR_DUPLICATE_PRIMARY` (HTTP 409)."

    Design: Corner/validations/duplicate_primary_member_rejected
    """
    hh, _ = create_household_with_primary("c-21", income_cents=100_000, full_name="First P")
    res = api.create_member(hh["id"],
                            {"full_name": "Second P", "relationship": "PRIMARY",
                             "tax_filing_status": "FILER", "annual_income_cents": 200_000},
                            make_applicant_headers("c-21"))
    validate_error(res, "ERR_DUPLICATE_PRIMARY")
    assert res.status_code == 409


def test_plan_area_mismatch_rejected(api):
    """PRD §3.5: "The selected plan's `rating_area` and `coverage_year` must both match the household's; a mismatch is rejected with `ERR_PLAN_AREA_MISMATCH` (HTTP 409)."

    Design: Corner/validations/plan_area_mismatch_rejected
    """
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000)
    wrong = register_plan(rating_area="RA09", coverage_year=2026, metal_tier="SILVER",
                          gross_premium_cents=55_000)
    hh, _ = create_household_with_primary("c-22", rating_area="RA01", income_cents=3_000_000)
    app = create_application(hh["id"], "c-22", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-22")
    determine_application(app["id"])
    v = household_version(hh["id"], "c-22")
    res = api.create_enrollment(
        {"application_id": app["id"], "plan_id": wrong["id"],
         "elected_aptc_monthly_cents": 0, "expected_household_version": v},
        make_applicant_headers("c-22"))
    validate_error(res, "ERR_PLAN_AREA_MISMATCH")
    assert res.status_code == 409


def test_determine_without_benchmark_plan_rejected(api):
    """PRD §3.3: "A determination requires that a benchmark plan exist (see below); if none does, the determination fails with `ERR_NO_BENCHMARK_PLAN` (HTTP 409)."

    Design: Corner/validations/determine_without_benchmark_plan_rejected
    """
    set_clock("2026-01-10T00:00:00Z")
    # No plan registered for RA07/2026.
    hh, _ = create_household_with_primary("c-23", rating_area="RA07", income_cents=3_000_000)
    app = create_application(hh["id"], "c-23", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-23")
    res = api.determine_application(app["id"], TEST_USERS["admin_headers"])
    validate_error(res, "ERR_NO_BENCHMARK_PLAN")
    assert res.status_code == 409


def test_submit_application_with_no_primary_member_rejected(api):
    """PRD §3.2: "Submission is permitted only when the application is currently `DRAFT`, when the referenced household has a `countable_size` of at least 1 (meaning at least one `PRIMARY` member exists), and — for `SEP`-window applications only — when an `APPROVED` `SepRequest` exists for this application; an `OEP` application skips that SEP precondition entirely."
    PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/validations/submit_draft_application_with_no_primary_member
    """
    hh = create_household("c-24")  # zero members -> countable_size 0
    app = create_application(hh["id"], "c-24", enrollment_window="OEP")
    v = household_version(hh["id"], "c-24")
    res = api.submit_application(app["id"], {"expected_household_version": v},
                                make_applicant_headers("c-24"))
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


# ───────────── endpoints ─────────────

def test_list_households_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/endpoints/list_households_pagination_envelope
    """
    create_household("c-25")
    create_household("c-25")
    res = api.list_households(TEST_USERS["admin_headers"],
                              params={"applicant_user_id": "c-25", "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_reconciliation_by_id_returns_computed_settlement(api):
    """PRD §3.7: "a positive settlement is an amount the household must repay, while a negative settlement is an additional credit owed to the household."
    PRD §3.7: "Reconciliation records are listable by `enrollment_id`."

    Design: Corner/endpoints/get_reconciliation_by_id
    """
    ctx = setup_reconciliation("c-26", actual_annual_magi_cents=3_300_000, months_enrolled=12,
                               income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                               benchmark_gross=50_000)
    got = validate_success(api.get_reconciliation(ctx["reconciliation"]["id"],
                                                  make_applicant_headers("c-26")), 200)
    assert got["settlement_cents"] == 32400


# ───────────── errors ─────────────

def test_referenced_not_found_on_enrollment_plan(api):
    """PRD §2.6: "When a body field such as `household_id`, `application_id`, `plan_id`, or `enrollment_id` points to a resource that does not exist, the request is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/error_referenced_not_found_on_enrollment_plan
    """
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(gross_premium_cents=50_000)
    hh, _ = create_household_with_primary("c-27", income_cents=3_000_000)
    app = create_application(hh["id"], "c-27", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-27")
    determine_application(app["id"])
    v = household_version(hh["id"], "c-27")
    res = api.create_enrollment(
        {"application_id": app["id"], "plan_id": "00000000-0000-4000-8000-0000000000ff",
         "elected_aptc_monthly_cents": 0, "expected_household_version": v},
        make_applicant_headers("c-27"))
    validate_error(res, "ERR_REFERENCED_NOT_FOUND")
    assert res.status_code == 404
