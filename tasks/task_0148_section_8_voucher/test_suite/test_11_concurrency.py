"""Concurrent-write scenarios. PRD §2.12 explicitly enumerates the
serialization point and loser error_id for each engineered race.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    complete_inspection_payload,
    create_pending_tenancy,
    create_tenancy_payload,
    current_clock,
    iso_utc,
    make_applicant_headers,
    make_case_worker_headers,
    make_inspector_headers,
    new_case_worker_id,
    new_inspector_id,
    parse_iso,
    run_race,
    setup_active_tenancy,
    setup_eligible_applicant_with_voucher,
    setup_tenancy_pending_rent_reasonable,
    setup_unit_with_payment_standard,
    submit_annual_review_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestConcurrentFinalize:

    def test_two_caseworker_finalizes_serialize(self, api):
        """PRD §2.12: "Two CaseWorker operators finalizing the same
        Tenancy at the same instant: serialization is first-writer-wins
        on Tenancy.status; exactly one finalize advances
        PENDING_RENT_REASONABLE → ACTIVE, the loser receives
        ERR_INVALID_STATE because the tenancy is no longer in
        PENDING_RENT_REASONABLE."
        """
        state = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        cw1 = make_case_worker_headers(new_case_worker_id())
        cw2 = make_case_worker_headers(new_case_worker_id())
        results = run_race(
            lambda: api.finalize_tenancy(state["tenancy"]["id"], {}, cw1),
            lambda: api.finalize_tenancy(state["tenancy"]["id"], {}, cw2),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        # PRD §2.12 explicitly pins the loser error_id.
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestConcurrentTenancyOnVacantUnit:

    def test_two_tenancies_on_same_vacant_unit(self, api):
        """PRD §2.12: "Two Tenancies submitted on the same VACANT Unit
        at the same instant: serialization is first-writer-wins on
        Unit.occupancy_status; one tenancy is accepted and flips
        occupancy to OCCUPIED_PENDING, the loser receives
        ERR_UNIT_NOT_VACANT."
        """
        # Build two distinct vouchers (different applicants) and one
        # shared Unit.
        a1, v1 = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        a2, v2 = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        from test_helpers import setup_unit_with_payment_standard
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(v1["bedroom_size"], 1),
        )
        cw1 = make_case_worker_headers(new_case_worker_id())
        cw2 = make_case_worker_headers(new_case_worker_id())
        lease_start = iso_utc(add_days(current_clock(), 30))
        results = run_race(
            lambda: api.create_tenancy(
                create_tenancy_payload(v1["id"], unit["id"], lease_start),
                cw1,
            ),
            lambda: api.create_tenancy(
                create_tenancy_payload(v2["id"], unit["id"], lease_start),
                cw2,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_UNIT_NOT_VACANT.value)


class TestConcurrentInspectionComplete:

    def test_two_inspectors_completing_same_inspection(self, api):
        """PRD §2.12: "Two Inspectors marking complete on the same
        SCHEDULED Inspection: serialization is first-writer-wins on
        Inspection.status; the loser receives
        ERR_INSPECTION_ALREADY_COMPLETED."
        """
        from test_helpers import (
            create_pending_tenancy, schedule_inspection,
        )
        a, v = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(v["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=v["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id=v["administering_pha_id"],
        )
        ins_id = inspection["id"]
        pha = v["administering_pha_id"]
        h1 = make_inspector_headers(f"inspector-{pha}-c1")
        h2 = make_inspector_headers(f"inspector-{pha}-c2")
        results = run_race(
            lambda: api.complete_inspection(
                ins_id, complete_inspection_payload("PASS", []), h1,
            ),
            lambda: api.complete_inspection(
                ins_id, complete_inspection_payload("PASS", []), h2,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_INSPECTION_ALREADY_COMPLETED.value,
        )


class TestConcurrentApproveDeny:

    def test_approve_and_deny_same_annual_review(self, api):
        """PRD §2.12: "Two CaseWorkers, one approving and one denying
        the same AnnualReview at the same instant: serialization is
        first-writer-wins on AnnualReview.status; the loser receives
        ERR_INVALID_STATE because the review has already left
        SUBMITTED."
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id, add_days,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        applicant_id = state["applicant"]["id"]
        ap = make_applicant_headers(applicant_id)
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3), ap,
            ),
        )
        cw1 = make_case_worker_headers(new_case_worker_id())
        cw2 = make_case_worker_headers(new_case_worker_id())
        results = run_race(
            lambda: api.approve_annual_review(ar_id, {}, cw1),
            lambda: api.deny_annual_review(ar_id, {}, cw2),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)
