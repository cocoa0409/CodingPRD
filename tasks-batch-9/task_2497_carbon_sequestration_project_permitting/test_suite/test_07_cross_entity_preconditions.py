"""Regulatory decisions gated by the state of a neighbouring entity.

Two pairings are exercised: an injection well permit's construction step against
the emergency posture its parent storage project happens to be carrying, and a
tax credit claim's submission against the approval state of the one monitoring
plan that claim names.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    DEVELOPER_USER_ID,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
)

# MRV-2 measures the same three domains as MRV-1 with its own techniques.
MRV2_METHODS = [
    dict(spec, technique=technique)
    for spec, technique in zip(
        constants.MRV_METHODS_SCORE_85,
        (
            "DOWNHOLE_PRESSURE_TEMPERATURE",
            "GROUNDWATER_SAMPLING",
            "FIXED_TOWER_CO2_SENSORS",
        ),
    )
]


def test_permit_construction_step_refused_while_project_posture_frozen(api):
    """The project's `open_remediation_count` increments by one.

    When the `severity` is `MAJOR` or `CRITICAL`, the project's `operational_posture` is set to `FROZEN` — which then drives every `ACTIVE` permit of the project to `SUSPENDED` with its `authorized_injection_rate_tpy` zeroed, which in turn reverts every `SUBMITTED` claim of the project to `DRAFT`, which in turn forces a recomputation of the project's `pending_credit_usd`.

    While a project is `FROZEN`, every mutating operation on that project or on any of its children is refused with `ERR_PROJECT_POSTURE_FROZEN` (HTTP 409), with exactly two exceptions: opening a new remediation order is still permitted, and resolving an existing remediation order is still permitted — otherwise the project could never be un-frozen.

    The first step, into `DRILLING`, has two extra preconditions the later steps do not: the permit's `permit_status` must already be `APPROVED`, and the project must not be `FROZEN`.

    Design: Difficulty/cross_entity_state_dependency/permit_advance_construction_blocked_by_project_posture_frozen
    """
    ctx = fixtures.setup_authorized_project(api)
    project = ctx["project"]
    permit = ctx["permit"]
    assert project["status"] == "INJECTION_AUTHORIZED"
    assert project["operational_posture"] == "OPEN"
    assert project["assurance_coverage_status"] == "FUNDED"
    assert permit["permit_status"] == "APPROVED"
    assert permit["construction_status"] == "NOT_STARTED"

    order = fixtures.open_remediation_order(
        api,
        project["id"],
        trigger_type="WELL_INTEGRITY_LOSS",
        severity="MAJOR",
        narrative="annulus pressure anomaly on ALPHA-1 observation string",
    )
    assertions.assert_remediation_order(order)
    assert order["status"] == "OPEN"

    frozen = fixtures.refresh_project(api, project["id"])
    assertions.assert_storage_project(frozen)
    assert frozen["operational_posture"] == "FROZEN"
    assert frozen["open_remediation_count"] == 1

    response = api.advance_construction(
        permit["id"],
        factories.advance_construction_payload("DRILLING"),
        fixtures.DEVELOPER,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_POSTURE_FROZEN.value, 409)

    untouched = fixtures.refresh_permit(api, permit["id"])
    assert untouched["permit_status"] == "APPROVED"
    assert untouched["construction_status"] == "NOT_STARTED"


def test_permit_construction_step_permitted_once_remediation_order_resolved(api):
    """Resolution sets the order's `status` to `RESOLVED`, stamps `resolved_at` with the logical clock, and decrements the project's `open_remediation_count` by one.

    When that decrement brings `open_remediation_count` to 0, the posture is restored — to `OPEN` when the project's `assurance_coverage_status` is `FUNDED`, and to `RESTRICTED` when it is not — and every permit of the project whose `permit_status` is `SUSPENDED` is restored to `ACTIVE` with its `authorized_injection_rate_tpy` set to the governing model's `effective_injection_rate_tpy`.

    The first step, into `DRILLING`, has two extra preconditions the later steps do not: the permit's `permit_status` must already be `APPROVED`, and the project must not be `FROZEN`.

    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    Design: Difficulty/cross_entity_state_dependency/permit_advance_construction_blocked_by_project_posture_frozen
    """
    ctx = fixtures.setup_authorized_project(api)
    project = ctx["project"]
    permit = ctx["permit"]

    order = fixtures.open_remediation_order(
        api,
        project["id"],
        trigger_type="WELL_INTEGRITY_LOSS",
        severity="MAJOR",
        narrative="annulus pressure anomaly on ALPHA-1 observation string",
    )
    assert fixtures.refresh_project(api, project["id"])["operational_posture"] == "FROZEN"

    resolved = fixtures.resolve_remediation_order(
        api,
        order["id"],
        remediation_summary="packer replaced and annulus re-pressurised",
    )
    assertions.assert_remediation_order(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"][:19] == "2026-08-01T00:00:00"

    restored = fixtures.refresh_project(api, project["id"])
    assert restored["operational_posture"] == "OPEN"
    assert restored["open_remediation_count"] == 0

    advanced = validate_success(
        api.advance_construction(
            permit["id"],
            factories.advance_construction_payload("DRILLING"),
            fixtures.DEVELOPER,
        ),
        200,
    )
    assertions.assert_injection_well_permit(advanced)
    assert advanced["permit_status"] == "APPROVED"
    assert advanced["construction_status"] == "DRILLING"

    final = fixtures.refresh_project(api, project["id"])
    assert final["status"] == "INJECTION_AUTHORIZED"
    assert final["required_financial_assurance_usd"] == pytest.approx(
        25487166.94, abs=0.01
    )
    assert final["assurance_coverage_status"] == "FUNDED"


def test_claim_submission_refused_while_named_monitoring_plan_is_draft(api):
    """Authorizing injection requires that some monitoring plan of the project have `status` `APPROVED` or `APPROVED_WITH_CONDITIONS`, and submitting a tax credit claim requires that the specific plan the claim names have one of those two statuses; either failure is refused with `ERR_MRV_PLAN_NOT_APPROVED` (HTTP 422).

    Submitting a claim, optionally with a `submission_note`, is admissible only from `status` `DRAFT`, requires the referenced monitoring plan to have `status` `APPROVED` or `APPROVED_WITH_CONDITIONS`, requires the claim's `reported_tonnes` to be strictly greater than 0, and requires the project not to be `FROZEN`.

    `reported_tonnes` is the sum of `mass_injected_tonnes` over that window, rounded half up to 3 decimal places.

    The rate is tiered on the project's ledger rather than on the claim's own tonnage, and it degrades as the project stores more: `credit_rate_usd_per_tonne` is 85.00 dollars per tonne while the project's `cumulative_stored_tonnes` is at most 500,000 tonnes, 70.00 dollars per tonne while it exceeds 500,000 but is at most 2,000,000 tonnes, and 55.00 dollars per tonne once it exceeds 2,000,000 tonnes.

    `credit_amount_usd` is the basis multiplied by `credit_rate_usd_per_tonne`, rounded half up to 2 decimal places, where the basis is `reported_tonnes` when the claim's `claim_variant` is `REPORTED` and `verified_tonnes` when it is `VERIFIED`.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_approved_monitoring_plan
    """
    ctx = fixtures.setup_project_with_ledger(api)
    project = ctx["project"]

    second_plan, _ = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=MRV2_METHODS, plan_label="MRV-2"
    )
    assert second_plan["status"] == "DRAFT"

    claim = get_success_data(
        api.create_tax_credit_claim(
            factories.create_tax_credit_claim_payload(
                project["id"],
                second_plan["id"],
                tax_year=constants.TAX_YEAR,
                claim_variant="REPORTED",
                lca_upstream_emissions_factor=constants.LCA_UPSTREAM_EMISSIONS_FACTOR,
            ),
            fixtures.DEVELOPER,
        )
    )
    assertions.assert_tax_credit_claim(claim)
    assert claim["reported_tonnes"] == 550000.000
    assert claim["credit_amount_usd"] == 38500000.00

    response = api.submit_tax_credit_claim(
        claim["id"],
        {"submission_note": "2027 secure geologic storage claim"},
        fixtures.DEVELOPER,
    )
    validate_error(response, ApiErrorId.ERR_MRV_PLAN_NOT_APPROVED.value, 422)

    assert fixtures.refresh_project(api, project["id"])["pending_credit_usd"] == 0.00
    assert fixtures.refresh_plan(api, ctx["plan"]["id"])["status"] == "APPROVED"
    assert fixtures.refresh_claim(api, claim["id"])["status"] == "DRAFT"


def test_claim_submission_accepted_once_named_monitoring_plan_is_approved(api):
    """When `coverage_score` is at least 85.00, the plan moves `REVIEW_COMPLETE → APPROVED`.

    Submitting a claim, optionally with a `submission_note`, is admissible only from `status` `DRAFT`, requires the referenced monitoring plan to have `status` `APPROVED` or `APPROVED_WITH_CONDITIONS`, requires the claim's `reported_tonnes` to be strictly greater than 0, and requires the project not to be `FROZEN`.

    Submission recomputes all four derived claim figures on the current ledger, records the developer's `X-User-ID` in `submitted_by_user_id`, moves the claim `DRAFT → SUBMITTED`, recomputes the project's `pending_credit_usd` as the sum of `credit_amount_usd` over the project's claims whose `status` is `SUBMITTED` or `ALLOWED`, and bumps both the claim's `version` and the project's `version`.

    The rate is tiered on the project's ledger rather than on the claim's own tonnage, and it degrades as the project stores more: `credit_rate_usd_per_tonne` is 85.00 dollars per tonne while the project's `cumulative_stored_tonnes` is at most 500,000 tonnes, 70.00 dollars per tonne while it exceeds 500,000 but is at most 2,000,000 tonnes, and 55.00 dollars per tonne once it exceeds 2,000,000 tonnes.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_approved_monitoring_plan
    """
    ctx = fixtures.setup_project_with_ledger(api)
    project = ctx["project"]

    second_plan, _ = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=MRV2_METHODS, plan_label="MRV-2"
    )
    claim = get_success_data(
        api.create_tax_credit_claim(
            factories.create_tax_credit_claim_payload(
                project["id"],
                second_plan["id"],
                tax_year=constants.TAX_YEAR,
                claim_variant="REPORTED",
                lca_upstream_emissions_factor=constants.LCA_UPSTREAM_EMISSIONS_FACTOR,
            ),
            fixtures.DEVELOPER,
        )
    )
    refused = api.submit_tax_credit_claim(
        claim["id"],
        {"submission_note": "2027 secure geologic storage claim"},
        fixtures.DEVELOPER,
    )
    validate_error(refused, ApiErrorId.ERR_MRV_PLAN_NOT_APPROVED.value, 422)

    approved_plan = fixtures.take_plan_through_both_review_tracks(
        api, second_plan["id"]
    )
    assertions.assert_monitoring_plan(approved_plan)
    assert approved_plan["status"] == "APPROVED"
    assert approved_plan["coverage_score"] == 85.00

    submitted = validate_success(
        api.submit_tax_credit_claim(
            claim["id"],
            {"submission_note": "2027 secure geologic storage claim, resubmitted"},
            fixtures.DEVELOPER,
        ),
        200,
    )
    assertions.assert_tax_credit_claim(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["monitoring_plan_id"] == second_plan["id"]
    assert submitted["reported_tonnes"] == 550000.000
    assert submitted["credit_rate_usd_per_tonne"] == 70.00
    assert submitted["credit_amount_usd"] == 38500000.00
    assert submitted["submitted_by_user_id"] == DEVELOPER_USER_ID

    final = fixtures.refresh_project(api, project["id"])
    assert final["cumulative_stored_tonnes"] == 549500.000
    assert final["pending_credit_usd"] == 38500000.00
