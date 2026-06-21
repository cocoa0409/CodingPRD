"""Remittance lifecycle — ACCRUING → RECONCILED → REMITTED with OCC and
cross-entity precondition (no DRAFT/APPROVED runs in the month)."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    setup_paid_regular_run,
    create_employee,
    create_and_file_w4,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    approve_run,
    pay_run,
    find_remittance,
    get_remittance,
    close_remittance,
    remit_payload,
    TEST_USERS,
)


# =========================================================================
# Queue (A) Difficulty — rule 1 dual_variant_calc (instance 2: remittance accrual)
# =========================================================================

class TestRemittanceAccrualProvisionalVsReconciled:
    """The close-period transition runs the reconciled re-scan; accrued vs
    reconciled both equal 16357 when no voids occurred."""

    def test_close_period_runs_reconciled_rescan_and_status_transitions(self, api):
        """PRD §3.7: "The close-period side effect re-runs the remittance
        aggregation in **reconciled** mode — a full re-scan over every
        `Paycheck` whose `status` is `PAID` and whose parent run's
        `pay_date`-month equals this `period_month`, summing the matching
        bucket field per `(jurisdiction, tax_type)` — and writes the resulting
        authoritative number to `reconciled_cents`."
        PRD §3.7: "The provisional `accrued_cents` and the authoritative
        `reconciled_cents` are equal when no voids occurred during the month"

        Single PAID PaycheckRun in 2025-12 with one $2000 REGULAR paycheck
        produces fed=16357c. Close-period → RECONCILED, accrued=reconciled=16357.

        Design: Difficulty/dual_variant_calc/remittance_accrual_provisional_vs_reconciled
        """
        set_clock("2025-12-15T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-12-15T00:00:00.000Z",
            pay_period_end="2025-12-31T23:59:59.999Z",
            pay_date="2025-12-15T00:00:00.000Z",
        )
        rem = find_remittance(
            period_month="2025-12", jurisdiction="FEDERAL", tax_type="FED_INCOME"
        )
        # accrued_cents after PAID cascade
        assert rem["accrued_cents"] == 16357, \
            f"provisional accrued should be 16357 after PAID, got {rem['accrued_cents']}"
        # Close the period: ACCRUING -> RECONCILED + reconciled_cents written
        closed = close_remittance(rem["id"])
        assert closed["status"] == "RECONCILED"
        assert closed["accrued_cents"] == 16357
        assert closed["reconciled_cents"] == 16357


# =========================================================================
# Queue (A) Difficulty — rule 7 cross_entity_state_dependency (instance 2)
# =========================================================================

class TestCloseRequiresNoOpenPaycheckRuns:
    """PRD §3.7 close-period precondition: no DRAFT/APPROVED runs in the month."""

    def test_close_period_blocked_by_open_run_same_month(self, api):
        """PRD §3.7: "every `PaycheckRun` whose `pay_date`-month equals the
        remittance's `period_month` must be in `PAID` or `VOID` (no `DRAFT` or
        `APPROVED` runs may leak into a closed month)"
        PRD §3.7: "an open paycheck run for the same month yields
        `ERR_OPEN_RUN_BLOCKS_CLOSE` (HTTP 409)"

        Setup: run A PAID in 2025-10 (creates Remittance row), then run B in
        2025-10 left in DRAFT. close-period on the Remittance row must fail
        with ERR_OPEN_RUN_BLOCKS_CLOSE.

        Design: Difficulty/cross_entity_state_dependency/remittance_close_requires_no_open_paycheckruns_pair_remittance_paycheckrun
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, paid_run, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        # Run B in same month, left in DRAFT
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-10-16T00:00:00.000Z",
            pay_period_end="2025-10-31T23:59:59.999Z",
            pay_date="2025-10-31T00:00:00.000Z",
        )
        attach_regular_paycheck(run_b["id"], emp["id"])

        rem = find_remittance(
            period_month="2025-10", jurisdiction="FEDERAL", tax_type="FED_INCOME"
        )
        res = api_client.close_remittance_period(
            rem["id"], TEST_USERS["compliance_officer_headers"]
        )
        validate_error(res, "ERR_OPEN_RUN_BLOCKS_CLOSE", expected_status=409)


# =========================================================================
# Queue (B) Corner — state_machines remittance_remit_from_accruing_invalid
# =========================================================================

class TestRemitFromAccruingInvalid:
    def test_remit_against_accruing_row_rejected_invalid_state(self, api):
        """PRD §3.7: "Remitting transitions `Remittance.status` from
        `RECONCILED` to `REMITTED`."
        PRD §3.7: "The row must currently be in `RECONCILED` (otherwise
        `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/remittance_remit_from_accruing_invalid
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run()
        rem = find_remittance("2025-11", "FEDERAL", "FED_INCOME")
        # Don't close — attempt /remit while still ACCRUING
        res = api_client.remit_remittance(
            rem["id"],
            remit_payload(paid_cents=16357, expected_remittance_version=rem["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =========================================================================
# Queue (B) Corner — errors occ_stale_version_remit
# =========================================================================

class TestRemitStaleVersionOCC:
    def test_remit_with_stale_version_rejected_with_412(self, api):
        """PRD §2.7: "The server compares that value against the target
        remittance's current `version`. If they differ, the remit is rejected
        with `ERR_STALE_VERSION` and HTTP status 412 — even if every other
        precondition would pass."
        PRD §3.7: "A version mismatch is rejected with `ERR_STALE_VERSION` and
        HTTP 412 — even when every other precondition would pass."
        PRD §3.7: "Closing the period also increments the row's `version`."

        Capture version BEFORE close-period; close-period bumps it; remit with
        the stale captured value → ERR_STALE_VERSION.

        Design: Corner/errors/occ_stale_version_remit
        """
        set_clock("2025-09-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-09-01T00:00:00.000Z",
            pay_period_end="2025-09-15T23:59:59.999Z",
            pay_date="2025-09-15T00:00:00.000Z",
        )
        rem = find_remittance("2025-09", "FEDERAL", "FED_INCOME")
        stale_v = rem["version"]
        close_remittance(rem["id"])
        # Now the row's version has advanced; submit the stale version
        res = api_client.remit_remittance(
            rem["id"],
            remit_payload(paid_cents=16357, expected_remittance_version=stale_v),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# =========================================================================
# Queue (B) Corner — cross_cutting occ_version_increments_on_remit
# =========================================================================

class TestRemitVersionIncrementsOnSuccess:
    def test_successful_remit_increments_remittance_version(self, api):
        """PRD §3.7: "The successful remit transitions `Remittance.status` to
        `REMITTED`, sets `paid_cents` to the request's value, and increments
        `Remittance.version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_remit
        """
        set_clock("2025-08-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-08-01T00:00:00.000Z",
            pay_period_end="2025-08-15T23:59:59.999Z",
            pay_date="2025-08-15T00:00:00.000Z",
        )
        rem = find_remittance("2025-08", "FEDERAL", "FED_INCOME")
        closed = close_remittance(rem["id"])
        closed_v = closed["version"]
        # Remit with matching version
        res = api_client.remit_remittance(
            rem["id"],
            remit_payload(paid_cents=16357, expected_remittance_version=closed_v),
            TEST_USERS["compliance_officer_headers"],
        )
        body = validate_success(res, expected_status=200)
        assert body["status"] == "REMITTED"
        assert body["paid_cents"] == 16357
        assert body["version"] > closed_v, \
            f"version must increment after remit; was {closed_v}, now {body['version']}"


# =========================================================================
# Queue (B) Corner — validations remit_amount_mismatch
# =========================================================================

class TestRemitAmountMismatch:
    def test_remit_with_paid_cents_not_matching_reconciled_rejected(self, api):
        """PRD §3.7: "`paid_cents` must equal `reconciled_cents` exactly (a
        partial or excess remittance is rejected with
        `ERR_REMITTANCE_AMOUNT_MISMATCH`)"

        Design: Corner/validations/remit_amount_mismatch
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        rem = find_remittance("2025-10", "FEDERAL", "FED_INCOME")
        closed = close_remittance(rem["id"])
        res = api_client.remit_remittance(
            rem["id"],
            remit_payload(paid_cents=99999, expected_remittance_version=closed["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_REMITTANCE_AMOUNT_MISMATCH", expected_status=422)
