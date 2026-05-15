"""Concurrency / race-condition and optimistic-concurrency tests.

Only races whose loser error_id is explicitly named by PRD prose
(§3.2, §3.4, §3.6, §3.7, §3.9) are asserted with a specific error_id;
no other race assertions are made.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    approve_risk_decision_payload,
    assert_exactly_one_succeeds,
    create_bulletin_payload,
    create_case_payload,
    create_facility,
    create_isolation_payload,
    create_person,
    create_supply_item,
    create_supply_request_payload,
    drive_region_to_published_tier,
    iso_utc_midnight,
    make_cdc_tracer_headers,
    make_hospital_reporter_headers,
    release_isolation,
    reject_risk_decision_payload,
    run_race,
    setup_district_with_hospital,
    setup_district_with_hospital_and_cdc,
    setup_isolation_releasable_via_home_mode,
    setup_provisional_risk_decision,
    submit_supply_request,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 — case dedup race
# ===========================================================================
class TestConcurrentCaseFiling:

    def test_two_concurrent_case_filings_loser_returns_duplicate_case(self, api):
        """PRD §3.2: "Two reporting institutions racing on the same
        (person_id, case_type) are serialized by ascending reported_at,
        with ties broken by Case.id lexicographic ascending; the winner
        advances normally and the loser receives ERR_DUPLICATE_CASE."

        Claim: in a binary race between TWO DISTINCT reporting
        institutions on the same (person_id, case_type), exactly one
        POST /epi/cases succeeds (2xx) and the loser receives
        ERR_DUPLICATE_CASE.
        """
        region, hospital_a = setup_district_with_hospital(
            district_code="D-RC-CASE-1",
        )
        # Mint a second hospital in the same district so two distinct
        # reporting institutions can race.
        from test_helpers import create_institution
        hospital_b = create_institution(
            institution_type="HOSPITAL", district_code=region["district_code"],
        )
        person = create_person(district_code=region["district_code"])
        payload_a = create_case_payload(
            person_id=person["id"],
            reporting_institution_id=hospital_a["id"],
            case_type="CONFIRMED",
        )
        payload_b = create_case_payload(
            person_id=person["id"],
            reporting_institution_id=hospital_b["id"],
            case_type="CONFIRMED",
        )
        headers_a = make_hospital_reporter_headers(hospital_a["id"])
        headers_b = make_hospital_reporter_headers(hospital_b["id"])

        def op_a():
            return api.create_case(dict(payload_a), headers_a)

        def op_b():
            return api.create_case(dict(payload_b), headers_b)

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_DUPLICATE_CASE.value)


# ===========================================================================
# §3.4 — isolation release race
# ===========================================================================
class TestConcurrentIsolationRelease:

    def test_two_concurrent_releases_loser_returns_invalid_state(self, api):
        """PRD §3.4: "Two tracers racing on release for the same
        isolation serialize on the isolation's status field — the
        first writer wins and the loser receives ERR_INVALID_STATE."

        Claim: in a binary race on POST
        /epi/isolations/{id}/check-release, exactly one transition to
        RELEASED succeeds and the loser receives ERR_INVALID_STATE.
        """
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=11, test1_day=5, test2_day=9,
        )
        iso_id = ctx["isolation"]["id"]
        cdc_id = ctx["cdc"]["id"]
        headers = make_cdc_tracer_headers(cdc_id)

        def op_a():
            return api.check_isolation_release(iso_id, headers)

        def op_b():
            return api.check_isolation_release(iso_id, headers)

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# §3.4 — facility-capacity race
# ===========================================================================
class TestConcurrentFacilityAdmission:

    def test_two_concurrent_admissions_to_last_bed_loser_returns_capacity(self, api):
        """PRD §3.4: "Two simultaneous centralized admissions to the
        same facility holding only one remaining bed serialize on the
        facility's occupied field — the first writer wins and the
        second receives ERR_FACILITY_AT_CAPACITY."

        Claim: with capacity=1 and occupied=0, two concurrent
        centralized admissions result in exactly one success and one
        ERR_FACILITY_AT_CAPACITY.
        """
        region, _hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-RC-FAC-1",
        )
        facility = create_facility(
            district_code=region["district_code"], capacity=1,
        )
        p_a = create_person(district_code=region["district_code"])
        p_b = create_person(district_code=region["district_code"])
        headers = make_cdc_tracer_headers(cdc["id"])

        def op_a():
            return api.create_isolation(
                create_isolation_payload(
                    person_id=p_a["id"], mode="CENTRALIZED",
                    facility_id=facility["id"],
                ),
                headers,
            )

        def op_b():
            return api.create_isolation(
                create_isolation_payload(
                    person_id=p_b["id"], mode="CENTRALIZED",
                    facility_id=facility["id"],
                ),
                headers,
            )

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_FACILITY_AT_CAPACITY.value)


# ===========================================================================
# §3.6 — risk decision approve/reject race
# ===========================================================================
class TestConcurrentRiskDecisionReview:

    def test_concurrent_approve_and_reject_loser_returns_invalid_state(
        self, api, supervisor_headers, risk_expert_headers,
    ):
        """PRD §3.6: "Two simultaneous review actions on the same
        decision (an expert approval racing a supervisor rejection, for
        instance) serialize on the decision's status — exactly one
        terminal action wins and the loser receives ERR_INVALID_STATE."

        Claim: an approve racing a reject on the same UNDER_REVIEW
        decision results in exactly one success; the loser returns
        ERR_INVALID_STATE.
        """
        region, _hospital = setup_district_with_hospital(
            district_code="D-RC-RD-1",
        )
        # Need provisional_tier != current_risk_tier to allow
        # submit-review. We force divergence by publishing region to
        # HIGH first; provisional recompute then yields LOW (no cases),
        # so provisional(LOW) != current(HIGH).
        drive_region_to_published_tier(region, "HIGH")
        api.recompute_region_risk(region["id"], supervisor_headers)
        rd = setup_provisional_risk_decision(region["id"])
        validate_success(api.submit_risk_decision_review(
            rd["id"], supervisor_headers,
        ))

        def op_approve():
            return api.approve_risk_decision(
                rd["id"],
                approve_risk_decision_payload(
                    final_tier="MEDIUM",
                    expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
                ),
                risk_expert_headers,
            )

        def op_reject():
            return api.reject_risk_decision(
                rd["id"],
                reject_risk_decision_payload(
                    expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
                ),
                risk_expert_headers,
            )

        results = run_race(op_approve, op_reject)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# §3.7 — supply allocation race
# ===========================================================================
class TestConcurrentSupplyAllocation:

    def test_concurrent_allocations_loser_returns_supply_insufficient(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "If two allocations race over the same item and
        would jointly drive allocated_quantity past reserve_quantity,
        serialization on the item's allocated_quantity field gives the
        first writer the allocation and the second receives
        ERR_SUPPLY_INSUFFICIENT."

        Claim: two single-request allocates that each demand the full
        reserve (cannot both succeed) result in exactly one success and
        one ERR_SUPPLY_INSUFFICIENT.
        """
        item = create_supply_item(
            sku="SKU-RC-S1", category="PPE", reserve_quantity=10,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-RC-S-1",
        )
        req_a = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=10,
        )
        req_b = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=10,
        )

        def op_a():
            return api.allocate_supply_request(
                req_a["id"], supply_manager_headers,
            )

        def op_b():
            return api.allocate_supply_request(
                req_b["id"], supply_manager_headers,
            )

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_SUPPLY_INSUFFICIENT.value)


# ===========================================================================
# §3.9 — bulletin uniqueness race
# ===========================================================================
class TestConcurrentBulletinDraft:

    def test_two_concurrent_drafts_same_date_loser_returns_duplicate(
        self, api, press_officer_headers,
    ):
        """PRD §3.9: "Each bulletin_date is unique — a second draft for
        the same date is rejected with ERR_DUPLICATE_BULLETIN, and two
        press officers racing on the same date serialize on the
        date-uniqueness check with the loser receiving the same error."

        Claim: two concurrent POST /epi/bulletins with the same
        bulletin_date yield exactly one success and one
        ERR_DUPLICATE_BULLETIN.
        """
        date = iso_utc_midnight(datetime(2026, 2, 1, tzinfo=timezone.utc))
        payload = create_bulletin_payload(
            bulletin_date=date, channels=["WEBSITE"],
        )

        def op_a():
            return api.create_bulletin(dict(payload), press_officer_headers)

        def op_b():
            return api.create_bulletin(dict(payload), press_officer_headers)

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_DUPLICATE_BULLETIN.value)


# NOTE: PRD §2.5 declares ERR_VERSION_CONFLICT for stale-version
# mismatches on mutating endpoints "that expose the version field."
# Per the Silence-pattern audit, the PRD does not enumerate which
# specific endpoints accept the optional `version` body parameter,
# so a faithful PRD-only reader could implement OCC on any subset of
# version-bearing entities. We deliberately do NOT generate a stale-
# version test on a specific endpoint here: doing so would force the
# implementation to wire OCC onto an endpoint the PRD does not pin.
# Silence-pattern category: applies_to-scope.
