"""RBAC, optimistic-concurrency, derived-field reconciliation, immediate consistency (queue B)."""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_benchmark_plan,
    create_household,
    create_household_with_primary,
    create_application,
    submit_application,
    determine_application,
    household_version,
    make_applicant_headers,
    make_navigator_headers,
    TEST_USERS,
)


# ───────────── RBAC ─────────────

def test_applicant_cannot_run_determination(api):
    """PRD §2.1: "When a request is authenticated but the acting role is not permitted to perform the requested operation, it is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "a `MarketplaceAdmin` runs the eligibility determination, which advances the application from `SUBMITTED` to `DETERMINED` and creates an **EligibilityDetermination** linked to the `application_id` (one active determination per application)."

    Design: Corner/rbac/applicant_cannot_run_determination
    """
    set_clock("2026-01-10T00:00:00Z")
    register_benchmark_plan(gross_premium_cents=50_000)
    hh, _ = create_household_with_primary("c-28", income_cents=3_000_000)
    app = create_application(hh["id"], "c-28", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-28")
    res = api.determine_application(app["id"], make_applicant_headers("c-28"))
    validate_error(res, "ERR_FORBIDDEN")
    assert res.status_code == 403


def test_applicant_cannot_act_on_other_household(api):
    """PRD §2.1: "An `Applicant` who attempts a mutation on a household, application, or enrollment subtree they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_act_on_other_household
    """
    hh = create_household("c-29")
    res = api.create_member(hh["id"],
                            {"full_name": "Intruder", "relationship": "PRIMARY",
                             "tax_filing_status": "FILER", "annual_income_cents": 100},
                            make_applicant_headers("c-30"))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    assert res.status_code == 403


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of these three declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.get_household("00000000-0000-4000-8000-000000000000", headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
    assert res.status_code == 401


def test_navigator_bypasses_ownership_can_add_member(api):
    """PRD §2.1: "a `Navigator` is a certified assister who may exercise the full applicant write surface and read everything, and who is explicitly exempt from the `applicant_user_id` ownership comparison — a Navigator may assist any household."

    Design: Corner/rbac/navigator_bypasses_ownership_can_add_member
    """
    hh = create_household("c-31")
    res = api.create_member(hh["id"],
                            {"full_name": "Nav Added", "relationship": "PRIMARY",
                             "tax_filing_status": "FILER", "annual_income_cents": 100_000},
                            make_navigator_headers("nav-1"))
    validate_success(res, 201)
    got = validate_success(api.get_household(hh["id"], make_navigator_headers("nav-1")), 200)
    assert got["countable_size"] == 1


# ───────────── optimistic concurrency ─────────────

def test_enrollment_create_with_stale_household_version_rejected(api):
    """PRD §2.7: "If the household `version` has advanced since then — for instance, because
    a member income edit triggered a MAGI and FPL recompute that would change the qualified
    APTC — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/enrollment_create_stale_household_version
    """
    set_clock("2026-01-10T00:00:00Z")
    plan = register_benchmark_plan(gross_premium_cents=50_000)
    hh, mem = create_household_with_primary("c-32", income_cents=3_000_000)
    app = create_application(hh["id"], "c-32", enrollment_window="OEP")
    submit_application(app["id"], hh["id"], "c-32")
    determine_application(app["id"])
    h = make_applicant_headers("c-32")
    stale = household_version(hh["id"], "c-32")
    # advance Household.version via a member edit
    validate_success(api.update_member(hh["id"], mem["id"],
                                       {"annual_income_cents": 3_100_000}, h), 200)
    res = api.create_enrollment(
        {"application_id": app["id"], "plan_id": plan["id"],
         "elected_aptc_monthly_cents": 0, "expected_household_version": stale},
        h)
    validate_error(res, "ERR_STALE_VERSION")
    assert res.status_code == 412


def test_submit_with_stale_household_version_rejected(api):
    """PRD §2.7: "If a member edit has advanced the household's `version` since the applicant read it, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so that a determination is never run on an income snapshot the applicant never saw."

    Design: Corner/cross_cutting_complexity_layers/submit_stale_household_version
    """
    hh, mem = create_household_with_primary("c-33", income_cents=3_000_000)
    app = create_application(hh["id"], "c-33", enrollment_window="OEP")
    h = make_applicant_headers("c-33")
    stale = household_version(hh["id"], "c-33")
    validate_success(api.update_member(hh["id"], mem["id"],
                                       {"annual_income_cents": 3_100_000}, h), 200)
    res = api.submit_application(app["id"], {"expected_household_version": stale}, h)
    validate_error(res, "ERR_STALE_VERSION")
    assert res.status_code == 412


# ───────────── derived-field reconciliation & consistency ─────────────

def test_household_version_increments_on_member_add_with_magi_recompute(api):
    """PRD §2.5: "Whenever such a recompute occurs, it is a genuine mutation of the household: `updated_at` is refreshed and `version` increments by 1."
    PRD §3.1: "The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs."

    Design: Corner/cross_cutting_complexity_layers/household_version_increments_on_member_add
    """
    hh = create_household("c-34")
    v0 = hh["version"]
    h = make_applicant_headers("c-34")
    validate_success(api.create_member(hh["id"],
                                       {"full_name": "Recon P", "relationship": "PRIMARY",
                                        "tax_filing_status": "FILER",
                                        "annual_income_cents": 1_234_500}, h), 201)
    got = validate_success(api.get_household(hh["id"], h), 200)
    assert got["version"] == v0 + 1
    assert got["household_magi_cents"] == 1234500


def test_magi_recompute_visible_immediately(api):
    """PRD §2.5: "The system performs these reconciliations immediately and synchronously
    within the triggering request; there is no eventual-consistency lag."
    PRD §3.1: "The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs."

    Design: Corner/consistency_model/magi_recompute_visible_in_same_response
    """
    hh = create_household("c-35")
    h = make_applicant_headers("c-35")
    validate_success(api.create_member(hh["id"],
                                       {"full_name": "Imm P", "relationship": "PRIMARY",
                                        "tax_filing_status": "FILER",
                                        "annual_income_cents": 2_000_000}, h), 201)
    got = validate_success(api.get_household(hh["id"], h), 200)
    assert got["household_magi_cents"] == 2000000
    assert got["countable_size"] == 1
