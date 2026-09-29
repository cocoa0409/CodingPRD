"""Cross-cutting layers: the two optimistic-concurrency guards of PRD §2.7 and
the coverage-shortfall penalty of PRD §3.5 as it lands on a management-fee
invoice.

The two guarded writes — filing a liability waiver and drafting a monthly
invoice — each carry a mandatory expected-version field on their parent record,
and each rejects a stale read with its own error identity at HTTP 412 while
leaving the parent and its children exactly as they were. The penalty tests
walk a single management-fee contract across both edges of the penalty rate:
the free one-session allowance at the bottom and the five-percent ceiling at
the top.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client, factories
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_liability_waiver, assert_monthly_invoice

ADMIN = TEST_USERS["operator_admin_headers"]


# ==========================================================================
# Private composite setups
# ==========================================================================
def _setup_member_with_first_waiver() -> tuple:
    """An ACTIVE contract with one EMPLOYEE member, that member's `version`
    read exactly once, and one waiver filed against that single read.

    Returns (scenario, member_id, version_at_first_read, first_waiver).
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    version_at_first_read = scenarios.member_version(member["id"])
    first_waiver = validate_success(
        api_client.create_waiver(
            member["id"],
            factories.waiver_payload(
                version_at_first_read,
                waiver_version_code="WVR-2026A",
                expires_on="2027-06-30",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    return scenario, member["id"], version_at_first_read, first_waiver


def _setup_management_fee_program_with_sessions(count: int) -> tuple:
    """A MANAGEMENT_FEE contract (management_fee_cents 40000) taken ACTIVE with
    a studio, a READY defibrillator, a credentialed and drilled instructor and
    one ACTIVE offering, plus `count` sessions one per day from 2026-08-05 at
    12:00-12:55Z, each left with no staffing assignment at all.

    Returns (scenario, sessions).
    """
    scenario = scenarios.setup_active_program("MANAGEMENT_FEE")
    sessions = []
    for index in range(count):
        day = 5 + index
        sessions.append(
            scenarios.schedule_session(
                scenario,
                scheduled_start_utc=f"2026-08-{day:02d}T12:00:00Z",
                scheduled_end_utc=f"2026-08-{day:02d}T12:55:00Z",
                forecast_attendance=3,
                direct_supply_cost_cents=0,
            )
        )
    return scenario, sessions


# ==========================================================================
# Waiver filing under the member-version guard
# ==========================================================================
def test_waiver_filing_with_stale_member_version_rejected(api):
    """PRD §2.7: "Filing a liability waiver for a member requires the request to
    carry `expected_member_version`, a non-optional field holding the `version`
    of that member as the client last read it."

    PRD §2.7: "If `expected_member_version` does not equal the member's current
    `version`, the write is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP
    412)."

    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied, and `has_more` is true exactly when rows remain
    beyond the current page."

    Design: Corner/cross_cutting_complexity_layers/waiver_create_with_stale_member_version_returns_412
    """
    scenario, member_id, stale_version, first_waiver = _setup_member_with_first_waiver()
    version_before_retry = scenarios.member_version(member_id)

    rejected = api.create_waiver(
        member_id,
        factories.waiver_payload(
            stale_version,
            waiver_version_code="WVR-2026B",
            expires_on="2027-12-31",
        ),
        scenario["manager_headers"],
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)

    member = scenarios.read_member(member_id)
    assert member["version"] == version_before_retry, (
        f"expected the member's version to stay at {version_before_retry} after the "
        f"rejected waiver filing, got {member['version']}"
    )
    assert member["current_waiver_id"] == first_waiver["id"], (
        f"expected current_waiver_id to still point at {first_waiver['id']} after the "
        f"rejected waiver filing, got {member['current_waiver_id']}"
    )

    surviving = scenarios.read_waiver(first_waiver["id"])
    assert surviving["status"] == "SIGNED", (
        f"expected the first waiver to stay SIGNED after the rejected filing, got "
        f"{surviving['status']}"
    )
    assert surviving["version"] == first_waiver["version"], (
        f"expected the first waiver's version to stay at {first_waiver['version']} "
        f"after the rejected filing, got {surviving['version']}"
    )

    _, meta = validate_paginated(api.list_member_waivers(member_id, ADMIN))
    assert meta["total_count"] == 1, (
        f"expected 1 waiver row for the member after the rejected filing, got "
        f"{meta['total_count']}"
    )


def test_waiver_filing_with_re_read_member_version_accepted(api):
    """PRD §2.7: "If `expected_member_version` does not equal the member's
    current `version`, the write is rejected with `ERR_STALE_MEMBER_VERSION`
    (HTTP 412)."

    PRD §3.6: "On success the new waiver is written in `SIGNED` status with
    `signed_at` stamped from the logical clock, the member's previously `SIGNED`
    waiver — if there was one — moves to `SUPERSEDED`, and the member's
    `current_waiver_id` is repointed at the new waiver while the member's own
    `version` advances."

    Design: Corner/cross_cutting_complexity_layers/waiver_create_with_stale_member_version_returns_412
    """
    scenario, member_id, version_at_first_read, first_waiver = (
        _setup_member_with_first_waiver()
    )

    re_read_version = scenarios.member_version(member_id)
    assert re_read_version != version_at_first_read, (
        f"expected filing the first waiver to advance the member's version away from "
        f"{version_at_first_read}, got {re_read_version}"
    )

    second_waiver = validate_success(
        api.create_waiver(
            member_id,
            factories.waiver_payload(
                re_read_version,
                waiver_version_code="WVR-2026B",
                expires_on="2027-12-31",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert_liability_waiver(second_waiver)
    assert second_waiver["status"] == "SIGNED", (
        f"expected the retried waiver to be SIGNED, got {second_waiver['status']}"
    )
    assert second_waiver["waiver_version_code"] == "WVR-2026B", (
        f"expected waiver_version_code WVR-2026B on the retried filing, got "
        f"{second_waiver['waiver_version_code']}"
    )

    superseded = scenarios.read_waiver(first_waiver["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"expected the first waiver to move to SUPERSEDED once the second was filed, "
        f"got {superseded['status']}"
    )
    member = scenarios.read_member(member_id)
    assert member["current_waiver_id"] == second_waiver["id"], (
        f"expected current_waiver_id to be repointed at {second_waiver['id']}, got "
        f"{member['current_waiver_id']}"
    )

    _, meta = validate_paginated(api.list_member_waivers(member_id, ADMIN))
    assert meta["total_count"] == 2, (
        f"expected 2 waiver rows for the member after the accepted retry, got "
        f"{meta['total_count']}"
    )


def test_waiver_filing_stale_after_eligibility_verification_advanced_member_version(api):
    """PRD §2.4: "Most records additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the record — and `version`, an
    integer that starts at 1 when the record is created and increments by
    exactly 1 on every mutation of that record, including mutations caused by a
    cascade originating elsewhere."

    PRD §2.7: "If `expected_member_version` does not equal the member's current
    `version`, the write is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/waiver_create_with_stale_member_version_returns_412
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    version_before_verification = scenarios.member_version(member["id"])

    scenarios.verify_member(scenario, member["id"])
    version_after_verification = scenarios.member_version(member["id"])
    assert version_after_verification == version_before_verification + 1, (
        f"expected the eligibility verification to increment the member's version to "
        f"{version_before_verification + 1}, got {version_after_verification}"
    )

    rejected = api.create_waiver(
        member["id"],
        factories.waiver_payload(
            version_before_verification,
            waiver_version_code="WVR-2026A",
            expires_on="2027-06-30",
        ),
        scenario["manager_headers"],
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)

    _, meta = validate_paginated(api.list_member_waivers(member["id"], ADMIN))
    assert meta["total_count"] == 0, (
        f"expected no waiver row to be written by the rejected filing, got "
        f"{meta['total_count']}"
    )

    filed = validate_success(
        api.create_waiver(
            member["id"],
            factories.waiver_payload(
                version_after_verification,
                waiver_version_code="WVR-2026A",
                expires_on="2027-06-30",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert filed["status"] == "SIGNED", (
        f"expected the waiver filed with the re-read member version to be SIGNED, got "
        f"{filed['status']}"
    )


# ==========================================================================
# Invoice drafting under the contract-version guard
# ==========================================================================
def test_invoice_draft_with_stale_contract_version_rejected(api):
    """PRD §2.7: "Drafting a monthly invoice requires the request to carry
    `expected_contract_version`, a non-optional field holding the `version` of
    the target client contract as the client last read it."

    PRD §2.7: "If `expected_contract_version` does not equal the contract's
    current `version`, the draft is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)."

    PRD §2.7: "A fresh draft supersedes any existing draft for the same period,
    and contract-level cascades — suspension, penalty accrual,
    eligibility-count movement — advance the contract's `version` between the
    client's read and its write."

    PRD §3.6: "It increments the contract's `eligible_member_count` by 1 and
    leaves `access_status` completely untouched — verifying eligibility does not
    hand out a badge."

    Design: Corner/cross_cutting_complexity_layers/invoice_draft_with_stale_contract_version_returns_412
    """
    scenario = scenarios.setup_active_contract()
    contract_id = scenario["contract_id"]
    member = scenarios.enrol_member(scenario)

    version_at_first_read = scenarios.contract_version(contract_id)
    scenarios.verify_member(scenario, member["id"])
    version_after_movement = scenarios.contract_version(contract_id)
    assert version_after_movement != version_at_first_read, (
        f"expected the eligible-member-count movement to advance the contract's "
        f"version away from {version_at_first_read}, got {version_after_movement}"
    )

    rejected = api.create_monthly_invoice(
        factories.invoice_payload(
            contract_id, version_at_first_read, period_month="2026-08"
        ),
        ADMIN,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

    contract = scenarios.read_contract(contract_id)
    assert contract["version"] == version_after_movement, (
        f"expected the contract's version to stay at {version_after_movement} after "
        f"the rejected draft, got {contract['version']}"
    )
    assert contract["ytd_billed_cents"] == 0, (
        f"expected the rejected draft to bill nothing, got ytd_billed_cents "
        f"{contract['ytd_billed_cents']}"
    )

    _, meta = validate_paginated(
        api.list_monthly_invoices(ADMIN, {"contract_id": contract_id})
    )
    assert meta["total_count"] == 0, (
        f"expected no invoice row to be written by the rejected draft, got "
        f"{meta['total_count']}"
    )


def test_invoice_draft_with_re_read_contract_version_accepted(api):
    """PRD §2.7: "If `expected_contract_version` does not equal the contract's
    current `version`, the draft is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)."

    PRD §3.9: "The draft **pins** the contract's current `fee_structure` into
    `fee_structure_snapshot`, so that a contract amended mid-dispute is still
    rebilled under the terms that were in force when the period was first
    invoiced; every subsequent recomputation of that invoice reads the snapshot
    rather than the live contract."

    PRD §3.9: "A new invoice lands in `DRAFT` with `rebill_count` at 0 and
    `issued_at`, `disputed_at`, `paid_at`, and `dispute_reason` all null."

    Design: Corner/cross_cutting_complexity_layers/invoice_draft_with_stale_contract_version_returns_412
    """
    scenario = scenarios.setup_active_contract()
    contract_id = scenario["contract_id"]
    member = scenarios.enrol_member(scenario)

    version_at_first_read = scenarios.contract_version(contract_id)
    scenarios.verify_member(scenario, member["id"])

    re_read_version = scenarios.contract_version(contract_id)
    assert re_read_version != version_at_first_read, (
        f"expected the re-read contract version to differ from the stale "
        f"{version_at_first_read}, got {re_read_version}"
    )

    invoice = validate_success(
        api.create_monthly_invoice(
            factories.invoice_payload(
                contract_id, re_read_version, period_month="2026-09"
            ),
            ADMIN,
        ),
        201,
    )
    assert_monthly_invoice(invoice)
    assert invoice["period_month"] == "2026-09", (
        f"expected period_month 2026-09 on the retried draft, got "
        f"{invoice['period_month']}"
    )
    assert invoice["fee_structure_snapshot"] == "COST_PLUS", (
        f"expected the draft to pin fee_structure_snapshot COST_PLUS, got "
        f"{invoice['fee_structure_snapshot']}"
    )
    assert invoice["status"] == "DRAFT", (
        f"expected the retried draft to land in DRAFT, got {invoice['status']}"
    )
    assert invoice["rebill_count"] == 0, (
        f"expected rebill_count 0 on a fresh draft, got {invoice['rebill_count']}"
    )

    _, meta = validate_paginated(
        api.list_monthly_invoices(ADMIN, {"contract_id": contract_id})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly 1 invoice row after the accepted retry, got "
        f"{meta['total_count']}"
    )


def test_invoice_draft_stale_after_uncovered_cancellation_advanced_contract_version(api):
    """PRD §3.5: "Its side effects are: assignments in `ASSIGNED`, `CONFIRMED`,
    **or** `VACANT_NEEDS_COVER` status move to `RELEASED` with the same
    committed-minutes compensation (and, as always, no double subtraction for
    one already vacated); the contract's `uncovered_session_count` increments by
    1; the contract's `pending_penalty_cents` is recomputed; and the offering's
    `provisional_attainment_pct` is recomputed."

    PRD §2.4: "Most records additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the record — and `version`, an
    integer that starts at 1 when the record is created and increments by
    exactly 1 on every mutation of that record, including mutations caused by a
    cascade originating elsewhere."

    PRD §2.7: "If `expected_contract_version` does not equal the contract's
    current `version`, the draft is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/invoice_draft_with_stale_contract_version_returns_412
    """
    scenario = scenarios.setup_active_program()
    contract_id = scenario["contract_id"]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )

    version_at_first_read = scenarios.contract_version(contract_id)
    scenarios.cancel_session(scenario, session["id"], "NO_COVER")
    version_after_accrual = scenarios.contract_version(contract_id)
    assert version_after_accrual > version_at_first_read, (
        f"expected the uncovered cancellation to advance the contract's version past "
        f"{version_at_first_read}, got {version_after_accrual}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["uncovered_session_count"] == 1, (
        f"expected uncovered_session_count 1 after one NO_COVER cancellation, got "
        f"{contract['uncovered_session_count']}"
    )

    rejected = api.create_monthly_invoice(
        factories.invoice_payload(
            contract_id, version_at_first_read, period_month="2026-08"
        ),
        ADMIN,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

    _, meta = validate_paginated(
        api.list_monthly_invoices(ADMIN, {"contract_id": contract_id})
    )
    assert meta["total_count"] == 0, (
        f"expected no invoice row to be written by the draft that read the contract "
        f"before the cancellation, got {meta['total_count']}"
    )

    invoice = validate_success(
        api.create_monthly_invoice(
            factories.invoice_payload(
                contract_id, version_after_accrual, period_month="2026-08"
            ),
            ADMIN,
        ),
        201,
    )
    assert invoice["period_month"] == "2026-08", (
        f"expected period_month 2026-08 on the draft written with the re-read "
        f"contract version, got {invoice['period_month']}"
    )


# ==========================================================================
# The coverage shortfall penalty: free allowance, accrual, ceiling
# ==========================================================================
def test_coverage_penalty_free_allowance_then_accrues_below_its_cap(api):
    """PRD §3.5: "A `cancel_reason` of `NO_COVER` moves the session from
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` to `CANCELLED_NO_COVER`, and
    additionally requires that the session genuinely has no cover: no assignment
    of it may have `role_on_session` of `LEAD` in `ASSIGNED` or `CONFIRMED`
    status."

    PRD §3.5: "On a `MANAGEMENT_FEE` contract, first take the contract's
    `uncovered_session_count`, subtract a one-session allowance, and floor the
    result at 0 to obtain the chargeable count."

    PRD §3.5: "Then compute the per-session amount as 1.5 percent of
    `management_fee_cents`, rounded half up to whole cents, and the ceiling as 5
    percent of `management_fee_cents`, likewise rounded half up to whole cents —
    the two roundings are independent of one another."

    PRD §3.5: "On a monthly fee of 40000 cents that yields a per-session amount
    of 600 and a ceiling of 2000, so four uncovered sessions cost three
    chargeable sessions at 600 each, or 1800; six uncovered sessions would
    compute to 3000 and are therefore clipped to the ceiling of 2000."

    Design: Corner/cross_cutting_complexity_layers/coverage_penalty_accrues_per_session_then_hits_its_cap
    """
    scenario, sessions = _setup_management_fee_program_with_sessions(4)
    contract_id = scenario["contract_id"]
    observed = []

    for index, session in enumerate(sessions, start=1):
        cancelled = scenarios.cancel_session(scenario, session["id"], "NO_COVER")
        assert cancelled["status"] == "CANCELLED_NO_COVER", (
            f"expected session {index} to move to CANCELLED_NO_COVER, got "
            f"{cancelled['status']}"
        )
        assert cancelled["cancel_reason"] == "NO_COVER", (
            f"expected cancel_reason NO_COVER on session {index}, got "
            f"{cancelled['cancel_reason']}"
        )
        contract = scenarios.read_contract(contract_id)
        observed.append(
            (contract["uncovered_session_count"], contract["pending_penalty_cents"])
        )

    assert observed[0] == (1, 0), (
        f"expected uncovered_session_count 1 and pending_penalty_cents 0 after the "
        f"first uncovered cancellation, which the one-session allowance makes free; "
        f"got {observed[0]}"
    )
    assert observed[3] == (4, 1800), (
        f"expected uncovered_session_count 4 and pending_penalty_cents 1800 after the "
        f"fourth uncovered cancellation (3 chargeable sessions at 600, under the 2000 "
        f"ceiling); got {observed[3]}"
    )


def test_coverage_penalty_pinned_at_its_ceiling_once_the_rate_would_exceed_it(api):
    """PRD §3.5: "The penalty is the chargeable count multiplied by the
    per-session amount, or the ceiling, whichever is smaller."

    PRD §3.5: "On a monthly fee of 40000 cents that yields a per-session amount
    of 600 and a ceiling of 2000, so four uncovered sessions cost three
    chargeable sessions at 600 each, or 1800; six uncovered sessions would
    compute to 3000 and are therefore clipped to the ceiling of 2000."

    PRD §3.5: "Its side effects are: assignments in `ASSIGNED`, `CONFIRMED`,
    **or** `VACANT_NEEDS_COVER` status move to `RELEASED` with the same
    committed-minutes compensation (and, as always, no double subtraction for
    one already vacated); the contract's `uncovered_session_count` increments by
    1; the contract's `pending_penalty_cents` is recomputed; and the offering's
    `provisional_attainment_pct` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/coverage_penalty_accrues_per_session_then_hits_its_cap
    """
    scenario, sessions = _setup_management_fee_program_with_sessions(6)
    contract_id = scenario["contract_id"]
    observed = []

    for session in sessions:
        scenarios.cancel_session(scenario, session["id"], "NO_COVER")
        contract = scenarios.read_contract(contract_id)
        observed.append(
            (contract["uncovered_session_count"], contract["pending_penalty_cents"])
        )

    assert observed[3] == (4, 1800), (
        f"expected uncovered_session_count 4 and pending_penalty_cents 1800 after the "
        f"fourth uncovered cancellation, still under the ceiling; got {observed[3]}"
    )
    assert observed[4] == (5, 2000), (
        f"expected uncovered_session_count 5 and pending_penalty_cents 2000 after the "
        f"fifth uncovered cancellation (4 chargeable sessions at 600 is 2400, clamped "
        f"to the 2000 ceiling); got {observed[4]}"
    )
    assert observed[5] == (6, 2000), (
        f"expected uncovered_session_count 6 and pending_penalty_cents 2000 after the "
        f"sixth uncovered cancellation (5 chargeable sessions at 600 is 3000, still "
        f"clamped to the 2000 ceiling); got {observed[5]}"
    )


def test_management_fee_invoice_bills_gross_less_the_capped_coverage_penalty(api):
    """PRD §3.9: "`admin_markup_cents` is 0 and `volume_credit_cents` is 0 —
    neither concept applies."

    PRD §3.9: "`coverage_penalty_cents` is the coverage shortfall penalty from
    §3.5, computed from the contract's `uncovered_session_count` against its
    `management_fee_cents`."

    PRD §3.9: "`gross_amount_cents` is simply the contract's
    `management_fee_cents`."

    PRD §3.9: "`net_amount_cents` is that gross less `coverage_penalty_cents`
    less `downtime_credit_cents`."

    PRD §3.9: "And `nte_capped` is always false, because a management-fee
    contract carries no `not_to_exceed_cents`."

    PRD §3.9: "`labor_subtotal_cents` is the sum of `labor_cost_cents` over
    every staffing assignment in `COMPLETED` status whose session's
    `completed_at` falls inside the billed `period_month` — assignments that
    were released, vacated, or are merely confirmed contribute nothing, and the
    session's completion date rather than its scheduled date decides which month
    it lands in."

    Design: Corner/cross_cutting_complexity_layers/coverage_penalty_accrues_per_session_then_hits_its_cap
    """
    scenario, sessions = _setup_management_fee_program_with_sessions(6)
    contract_id = scenario["contract_id"]
    for session in sessions:
        scenarios.cancel_session(scenario, session["id"], "NO_COVER")

    contract = scenarios.read_contract(contract_id)
    assert contract["uncovered_session_count"] == 6, (
        f"expected uncovered_session_count 6 before drafting, got "
        f"{contract['uncovered_session_count']}"
    )
    assert contract["pending_penalty_cents"] == 2000, (
        f"expected pending_penalty_cents 2000 before drafting, got "
        f"{contract['pending_penalty_cents']}"
    )

    invoice = scenarios.draft_invoice(scenario, "2026-08")
    assert_monthly_invoice(invoice)
    assert invoice["fee_structure_snapshot"] == "MANAGEMENT_FEE", (
        f"expected fee_structure_snapshot MANAGEMENT_FEE, got "
        f"{invoice['fee_structure_snapshot']}"
    )
    assert invoice["gross_amount_cents"] == 40000, (
        f"expected gross_amount_cents 40000 (the contract's flat management fee), got "
        f"{invoice['gross_amount_cents']}"
    )
    assert invoice["coverage_penalty_cents"] == 2000, (
        f"expected coverage_penalty_cents 2000 (the ceiling), got "
        f"{invoice['coverage_penalty_cents']}"
    )
    assert invoice["admin_markup_cents"] == 0, (
        f"expected admin_markup_cents 0 on a management-fee invoice, got "
        f"{invoice['admin_markup_cents']}"
    )
    assert invoice["volume_credit_cents"] == 0, (
        f"expected volume_credit_cents 0 on a management-fee invoice, got "
        f"{invoice['volume_credit_cents']}"
    )
    assert invoice["downtime_credit_cents"] == 0, (
        f"expected downtime_credit_cents 0 with no asset outage in the period, got "
        f"{invoice['downtime_credit_cents']}"
    )
    assert invoice["labor_subtotal_cents"] == 0, (
        f"expected labor_subtotal_cents 0 with every session cancelled and no "
        f"assignment completed, got {invoice['labor_subtotal_cents']}"
    )
    assert invoice["net_amount_cents"] == 38000, (
        f"expected net_amount_cents 38000 (40000 gross less the 2000 penalty), got "
        f"{invoice['net_amount_cents']}"
    )
    assert invoice["nte_capped"] is False, (
        f"expected nte_capped false on a management-fee invoice, got "
        f"{invoice['nte_capped']}"
    )
