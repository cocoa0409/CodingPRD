"""Cost projections: the PROVISIONAL/ACTUALIZED variant split,
create-with-supersede, and the optimistic concurrency guard (PRD §2.7, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL,
    TEST_USERS,
    create_and_post_record,
    create_projection_payload,
    get_assignment_version,
    setup_active_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_projection_provisional_before_any_posted_record(api, finance_headers):
    """PRD §3.6: "When the assignment has no `POSTED` shadow payroll record, the
    projection is `PROVISIONAL`: `total_projected_cents` is `projected_months`
    multiplied by `monthly_cost_cents`, a pure plan-based forward estimate."
    PRD §3.6: "`projected_months` is the number of calendar months touched by the
    closed window from `start_date` to `planned_end_date`, counting both the starting
    and the ending month."

    Design: Difficulty/dual_variant_calc/cost_projection_provisional_vs_actualized_divergence
    """
    ctx = setup_active_assignment(totalization=True)
    version = get_assignment_version(ctx["assignment"]["id"])
    projection = validate_success(api.create_projection(
        create_projection_payload(ctx["assignment"]["id"], version), finance_headers), 201)

    # coc_exempt holds, so the monthly cost carries no social security:
    # 360000 host share + 240000 gross-up + 0 + 8625 x 30 per-diem + 300000 cap.
    assert projection["variant"] == "PROVISIONAL"
    assert projection["projected_months"] == CANONICAL["PROJ_MONTHS"]
    assert projection["monthly_cost_cents"] == CANONICAL["PROJ_MONTHLY_EXEMPT"]
    assert projection["total_projected_cents"] == CANONICAL["PROJ_PROVISIONAL_TOTAL_EXEMPT"]
    assert projection["status"] == "CURRENT"


def test_projection_actualized_after_posting_and_supersedes_prior(api, finance_headers, admin_headers):
    """PRD §3.6: "Once at least one record has posted, the projection is `ACTUALIZED`:
    posted actuals replace the plan for elapsed months, so the total is the sum of
    `amount_cents` over the assignment's `PERIOD_COST` chargeback entries in `ACCRUED`
    or `POSTED` status (`VOIDED` entries excluded), plus `monthly_cost_cents`
    multiplied by the remaining months — the projected month count minus the number of
    `POSTED` records."
    PRD §3.6: "On success, any prior `CURRENT` projection for the assignment becomes
    `SUPERSEDED`, the new projection is stored as `CURRENT`, and the assignment's
    `version` increments by one."

    Design: Difficulty/dual_variant_calc/cost_projection_provisional_vs_actualized_divergence
    """
    ctx = setup_active_assignment(totalization=True)
    asg_id = ctx["assignment"]["id"]

    first = validate_success(api.create_projection(
        create_projection_payload(asg_id, get_assignment_version(asg_id)),
        finance_headers), 201)
    assert first["variant"] == "PROVISIONAL"
    assert first["total_projected_cents"] == 13905000

    # Post September: the PERIOD_COST actual is 1072500.
    create_and_post_record(asg_id, tax_year=2026, period_month=9,
                           total_gross_cents=900000, per_diem_days=20,
                           housing_receipts_cents=310000)

    second = validate_success(api.create_projection(
        create_projection_payload(asg_id, get_assignment_version(asg_id)),
        finance_headers), 201)
    assert second["variant"] == "ACTUALIZED"
    # 1072500 posted + 11 remaining months x 1158750 = 13818750.
    assert second["total_projected_cents"] == 13818750
    assert second["total_projected_cents"] != first["total_projected_cents"], (
        "the two variants price the same 12-month assignment differently"
    )

    first_after = validate_success(api.get_projection(first["id"], admin_headers), 200)
    assert first_after["status"] == "SUPERSEDED"
    assert second["status"] == "CURRENT"


def test_occ_stale_version_rejected_on_projection_create(api, finance_headers, admin_headers):
    """PRD §2.7: "If that value does not match the Assignment's current `version` —
    because an extension approval, a cost-projection creation, an extension-request
    creation, or a repatriation initiation has advanced it since the client's last
    read — the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412),
    preventing the client from acting on terms it has not observed."
    PRD §3.6: "On success, any prior `CURRENT` projection for the assignment becomes
    `SUPERSEDED`, the new projection is stored as `CURRENT`, and the assignment's
    `version` increments by one."

    Design: Corner/validations/occ_stale_version_rejected_on_projection_create
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    version = get_assignment_version(asg_id)

    first = validate_success(api.create_projection(
        create_projection_payload(asg_id, version), finance_headers), 201)
    assert get_assignment_version(asg_id) == version + 1, (
        "the create bumped the parent version exactly once"
    )

    res = api.create_projection(create_projection_payload(asg_id, version), finance_headers)
    validate_error(res, ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION)

    first_after = validate_success(api.get_projection(first["id"], admin_headers), 200)
    assert first_after["status"] == "CURRENT", "the failed create superseded nothing"
