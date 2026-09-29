"""Audit hold, the compensating void, and corrections against single allocations."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_row,
    assert_batch_net_identity,
    assert_cents,
    assert_correction_adjustment_shape,
)
from test_helpers.constants import ACCEPTING_ADMIN_USER_ID, INDEPENDENT_AUDITOR_USER_ID
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS
from test_helpers.test_users import make_auditor_headers


def _accepted_claim_with_pre_submission_space(client):
    """Accept a claim after recording the participant's pre-submission statutory space."""
    scenario = fx.build_claim_scenario(client)
    before = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(before["remaining_qslp_space_cents"], 2_280_000, "space before submit")

    batch = fx.create_funding_batch(
        client, scenario["plan_year_id"], scenario["payroll_period_id"]
    )
    scenario["funding_batch"] = batch
    scenario["funding_batch_id"] = batch["id"]

    fx.submit_certification(client, scenario["certification_id"], scenario["employee"])
    scenario["certification"] = fx.accept_certification(
        client, scenario["certification_id"], ACCEPTING_ADMIN_USER_ID
    )
    scenario["allocations"] = fx.allocations_of_certification(
        client, scenario["certification_id"]
    )
    scenario["allocation"] = scenario["allocations"][0]
    scenario["allocation_id"] = scenario["allocations"][0]["id"]
    scenario["space_pre_submit"] = before["remaining_qslp_space_cents"]
    return scenario


# ---------------------------------------------------------------------------
# The void unwinds the acceptance exactly
# ---------------------------------------------------------------------------


def test_void_after_accept_restores_plan_year_funded_total(client):
    """
    Voiding an accepted claim returns the plan year's funded total to its prior value.

    PRD: "The plan year's `total_qslp_match_funded_cents` must return to its exact
    pre-acceptance value once a claim's acceptance is fully unwound by a void."

    PRD: "every match allocation of the claim whose `funding_status` is `SCHEDULED` or
    `FUNDED` moves to `REVERSED` and detaches from the batch's arithmetic while
    retaining its `funding_batch_id` for audit; one correction adjustment is written per
    reversed allocation with `reason_code` `CERTIFICATION_VOID` and `amount_cents` equal
    to the negative of that allocation's `amount_cents`"

    Design: Difficulty/compensating_invariant/void_after_accept_restores_plan_year_funded_total
    """
    scenario = _accepted_claim_with_pre_submission_space(client)
    assert_cents(scenario["allocation"]["amount_cents"], 20_000, "allocation amount")

    after_accept = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(after_accept["total_qslp_match_funded_cents"], 20_000, "Q1 after accept")

    fx.place_audit_hold(client, scenario["certification_id"])
    voided = fx.release_audit_hold(
        client, scenario["certification_id"], "VOID", "no supporting statement"
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "no supporting statement"

    after_void = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(after_void["total_qslp_match_funded_cents"], 0, "Q1 after void")

    allocation = fx.refresh_allocation(client, scenario["allocation_id"])
    assert allocation["funding_status"] == "REVERSED"
    assert allocation["funding_batch_id"] == scenario["funding_batch_id"]

    adjustments = fx.corrections_of_plan_year(client, scenario["plan_year_id"])
    assert len(adjustments) == 1
    adjustment = adjustments[0]
    assert_correction_adjustment_shape(adjustment)
    assert_append_only_row(adjustment, "CorrectionAdjustment")
    assert adjustment["reason_code"] == "CERTIFICATION_VOID"
    assert_cents(adjustment["amount_cents"], -20_000, "adjustment amount_cents")
    assert adjustment["match_allocation_id"] == scenario["allocation_id"]


def test_void_after_accept_restores_batch_totals_and_statutory_space(client):
    """
    The same void empties the batch's arithmetic and restores the participant's space.

    PRD: "the batch's `total_allocated_cents`, `allocation_count`, and
    `net_funding_cents` are recomputed; the plan year's
    `total_qslp_match_funded_cents` returns to exactly its pre-acceptance value; and the
    employee's `remaining_qslp_space_cents` returns to exactly its pre-submission value."

    PRD: "reversed allocations retain their `funding_batch_id` for audit purposes but
    are excluded from both figures."

    Design: Difficulty/compensating_invariant/void_after_accept_restores_plan_year_funded_total
    """
    scenario = _accepted_claim_with_pre_submission_space(client)

    batch_after_accept = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch_after_accept["total_allocated_cents"], 20_000, "batch total after accept")
    assert batch_after_accept["allocation_count"] == 1

    fx.place_audit_hold(client, scenario["certification_id"])
    fx.release_audit_hold(
        client, scenario["certification_id"], "VOID", "no supporting statement"
    )

    batch_after_void = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch_after_void["total_allocated_cents"], 0, "batch total after void")
    assert batch_after_void["allocation_count"] == 0
    assert_cents(batch_after_void["net_funding_cents"], 0, "batch net after void")
    assert_batch_net_identity(batch_after_void)

    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(
        employee["remaining_qslp_space_cents"], 2_280_000, "space after void"
    )
    assert employee["remaining_qslp_space_cents"] == scenario["space_pre_submit"]


# ---------------------------------------------------------------------------
# Audit hold state guards
# ---------------------------------------------------------------------------


def test_audit_hold_twice_rejected(client):
    """
    A claim already on hold cannot be placed on hold again, and the reason survives.

    PRD: "A `ComplianceAuditor` may place an `ACCEPTED` claim on hold, supplying a
    `reason` that is stored as `audit_hold_reason`; a claim that is not `ACCEPTED` is
    refused with `ERR_CERTIFICATION_STATE_INVALID`."

    PRD: "Moving `ACCEPTED` → `AUDIT_HOLD` deliberately touches no money: the claim's
    allocations stay `SCHEDULED` or `FUNDED` and every funded total is unchanged."

    Design: Corner/state_machines/corner_audit_hold_twice_rejected
    """
    scenario = fx.setup_accepted_claim(client)

    held = fx.place_audit_hold(client, scenario["certification_id"], "first review")
    assert held["status"] == "AUDIT_HOLD"
    assert held["audit_hold_reason"] == "first review"

    response = client.audit_hold_certification(
        scenario["certification_id"], f.audit_hold_payload("second review"), AUDITOR_HEADERS
    )
    validate_error(response, ApiErrorId.CERTIFICATION_STATE_INVALID.value, 409)

    after = fx.refresh_certification(client, scenario["certification_id"])
    assert after["status"] == "AUDIT_HOLD"
    assert after["audit_hold_reason"] == "first review"


def test_voided_certification_admits_no_further_operation(client):
    """
    A voided claim is terminal: even a resubmission is refused.

    PRD: "the last two are terminal, and any operation against a claim already in
    `VOIDED` or `SUPERSEDED` is refused with `ERR_CERTIFICATION_TERMINAL`."

    Design: Corner/state_machines/corner_voided_certification_admits_no_further_operation
    """
    scenario = fx.setup_accepted_claim(client)

    fx.place_audit_hold(client, scenario["certification_id"], "documentation missing")
    voided = fx.release_audit_hold(
        client, scenario["certification_id"], "VOID", "no supporting statement"
    )
    assert voided["status"] == "VOIDED"

    response = client.submit_certification(
        scenario["certification_id"], None, scenario["employee_headers"]
    )
    validate_error(response, ApiErrorId.CERTIFICATION_TERMINAL.value, 409)

    after = fx.refresh_certification(client, scenario["certification_id"])
    assert after["status"] == "VOIDED"

    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee["remaining_qslp_space_cents"], 2_280_000, "remaining space")


def test_void_by_the_accepting_user_id_rejected(client):
    """
    The reviewer who voids a claim may not be the administrator who accepted it.

    PRD: "An audit release that voids the claim must be issued under a different
    `X-User-ID`; if the voiding caller matches the stored `accepted_by_user_id`, the
    release is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "`VOID` is the compensating branch and is the operation the
    segregation-of-duties rule of §2.11 guards: it must be issued by a different
    `X-User-ID` than the stored `accepted_by_user_id`, or it is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_void_by_the_accepting_user_id_rejected
    """
    scenario = fx.setup_accepted_claim(client, accepting_user_id=ACCEPTING_ADMIN_USER_ID)
    assert scenario["certification"]["accepted_by_user_id"] == ACCEPTING_ADMIN_USER_ID

    held = fx.place_audit_hold(client, scenario["certification_id"])
    assert held["status"] == "AUDIT_HOLD"

    same_user = client.audit_release_certification(
        scenario["certification_id"],
        f.audit_release_payload("VOID", "same-user void attempt"),
        make_auditor_headers(ACCEPTING_ADMIN_USER_ID),
    )
    validate_error(same_user, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

    still_held = fx.refresh_certification(client, scenario["certification_id"])
    assert still_held["status"] == "AUDIT_HOLD"

    independent = fx.release_audit_hold(
        client,
        scenario["certification_id"],
        "VOID",
        "independent reviewer void",
        INDEPENDENT_AUDITOR_USER_ID,
    )
    assert independent["status"] == "VOIDED"


# ---------------------------------------------------------------------------
# Corrections against a single allocation
# ---------------------------------------------------------------------------


def test_correction_on_unfunded_allocation_rejected(client):
    """
    An allocation that never reached a batch cannot be corrected.

    PRD: "The allocation's `funding_status` must be `SCHEDULED` or `FUNDED`; an
    allocation that is still `UNFUNDED` or already `REVERSED` is refused with
    `ERR_CORRECTION_NOT_ALLOWED`."

    PRD: "Where no `PENDING` batch exists for that period, the allocation simply stays
    `UNFUNDED` with `funding_batch_id` null."

    Design: Corner/endpoints/corner_correction_on_unfunded_allocation_rejected
    """
    scenario = fx.setup_accepted_claim_without_batch(client)
    allocation = scenario["allocation"]

    assert allocation["funding_status"] == "UNFUNDED"
    assert_cents(allocation["amount_cents"], 20_000, "allocation amount")
    assert allocation["funding_batch_id"] is None

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 0, "plan year qslp total")

    response = client.create_allocation_correction(
        scenario["allocation_id"],
        f.allocation_correction_payload(plan_year["version"]),
        ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.CORRECTION_NOT_ALLOWED.value, 409)

    adjustments = fx.corrections_of_plan_year(client, scenario["plan_year_id"])
    assert len(adjustments) == 0

    after = fx.refresh_allocation(client, scenario["allocation_id"])
    assert after["funding_status"] == "UNFUNDED"


def test_stale_plan_year_version_on_allocation_correction(client):
    """
    A correction carrying a stale ledger version is refused until the client re-reads.

    PRD: "If it does not equal that plan year's current `version`, the correction is
    rejected with `ERR_STALE_PLAN_YEAR_VERSION` (HTTP 412)."

    PRD: "The operation moves the allocation `SCHEDULED` → `REVERSED` or `FUNDED` →
    `REVERSED` as the case may be, writes a correction adjustment whose `amount_cents`
    is the negative of the allocation's `amount_cents` and whose `created_by_user_id` is
    the acting `X-User-ID`, recomputes the funding batch's totals and the plan year's
    `total_qslp_match_funded_cents`".

    Design: Corner/cross-cutting complexity layers/corner_occ_stale_plan_year_version_on_allocation_correction
    """
    scenario = fx.setup_accepted_claim(client, period_numbers=(1,))
    allocation = scenario["allocation"]
    assert allocation["funding_status"] == "SCHEDULED"

    stale_plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(
        stale_plan_year["total_qslp_match_funded_cents"], 20_000, "plan year qslp total"
    )
    stale_version = stale_plan_year["version"]

    second_period = fx.create_payroll_period(client, scenario["plan_year_id"], 2)
    fx.post_contribution_record(
        client, scenario["employee_id"], second_period["id"], 1_000_000, 15_000
    )

    rejected = client.create_allocation_correction(
        scenario["allocation_id"],
        f.allocation_correction_payload(stale_version, note="stale ledger snapshot"),
        ADMIN_HEADERS,
    )
    validate_error(rejected, ApiErrorId.STALE_PLAN_YEAR_VERSION.value, 412)

    fresh_plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert fresh_plan_year["version"] > stale_version

    adjustment = validate_success(
        client.create_allocation_correction(
            scenario["allocation_id"],
            f.allocation_correction_payload(
                fresh_plan_year["version"], note="reconciled ledger snapshot"
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert adjustment["reason_code"] == "ERRONEOUS_MATCH"
    assert_cents(adjustment["amount_cents"], -20_000, "adjustment amount_cents")

    after = fx.refresh_allocation(client, scenario["allocation_id"])
    assert after["funding_status"] == "REVERSED"

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year_after["total_qslp_match_funded_cents"], 0, "plan year qslp total")

    listing = client.list_correction_adjustments(
        ADMIN_HEADERS, {"match_allocation_id": scenario["allocation_id"]}
    )
    adjustments, meta = validate_paginated(listing)
    assert len(adjustments) == 1
    assert meta["total_count"] == 1
