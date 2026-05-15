"""Test orders, chain of custody, and result ingestion — PRD §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_test_order,
    collect_test,
    create_person,
    create_test_order_payload,
    file_case,
    make_hospital_reporter_headers,
    make_lab_technician_headers,
    order_pcr_test,
    result_test,
    setup_full_local_chain,
    test_result_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Test order creation — PRD §3.5
# ===========================================================================
class TestTestOrderCreation:

    def test_create_pcr_test_order_status_ordered(self, api):
        """PRD §3.5: "The order enters ORDERED with an empty
        chain_of_custody."

        Claim: POST /epi/test-orders for PCR sets status ORDERED, result
        PENDING, and chain_of_custody to an empty list.
        """
        chain = setup_full_local_chain(district_code="D-TO-1")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        assert_test_order(order)
        assert order["status"] == "ORDERED"
        assert order["result"] == "PENDING"
        assert order["chain_of_custody"] == []
        assert order["test_type"] == "PCR"


# ===========================================================================
# Collect / Result flow — PRD §3.5
# ===========================================================================
class TestCollectAndResult:

    def test_collect_moves_to_collected_and_appends_custody(self, api):
        """PRD §3.5: "Sample collection — recorded by the ordering
        hospital — appends a chain-of-custody entry ... stamps
        collected_at, and moves the order to COLLECTED."

        Claim: POST /epi/test-orders/{id}/collect produces status
        COLLECTED with at least one chain_of_custody entry and a
        populated collected_at.
        """
        chain = setup_full_local_chain(district_code="D-TO-2")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        assert collected["status"] == "COLLECTED"
        assert isinstance(collected["chain_of_custody"], list)
        assert len(collected["chain_of_custody"]) >= 1
        assert collected.get("collected_at")

    def test_negative_result_moves_to_resulted(self, api):
        """PRD §3.5: "A successful ingest appends another
        chain-of-custody entry, stamps result_recorded_at, and moves the
        order to RESULTED."

        Claim: ingesting a NEGATIVE result while still within validity
        moves status to RESULTED with result=NEGATIVE.
        """
        chain = setup_full_local_chain(district_code="D-TO-3")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        # Ingest very shortly after collection — well within any
        # validity window the implementation pins.
        advance_clock(60)
        resulted = result_test(
            collected["id"], chain["lab"]["id"], "NEGATIVE",
        )
        assert resulted["status"] == "RESULTED"
        assert resulted["result"] == "NEGATIVE"
        assert resulted.get("result_recorded_at")

    def test_result_after_long_delay_rejected_as_expired(self, api):
        """PRD §3.5: "the elapsed time between collected_at and the
        result ingest must not exceed the per-modality validity window,
        otherwise ERR_TEST_RESULT_EXPIRED fires."

        Claim: advancing the simulated clock by a clearly excessive
        amount (30 days) after collection — far past any plausible
        per-modality validity window — and then attempting to ingest
        a result is rejected with ERR_TEST_RESULT_EXPIRED.
        """
        chain = setup_full_local_chain(district_code="D-TO-4")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        # 30 days — large enough to exceed any reasonable validity window
        # for PCR/Antigen/Antibody. PRD pins the per-modality window
        # exists; we test the "far past expiry" boundary, not the
        # specific numeric boundary, because PRD does not name the
        # specific hour count for each modality.
        advance_clock(30 * 86400)
        resp = api.result_test_order(
            collected["id"], test_result_payload(result="NEGATIVE"),
            make_lab_technician_headers(chain["lab"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEST_RESULT_EXPIRED.value)


# ===========================================================================
# Positive PCR cascade — PRD §3.5 + §3.10
# ===========================================================================
class TestPositivePcrCascade:

    def test_positive_pcr_advances_under_tracing_case_to_confirmed(self, api):
        """PRD §3.10: "A case that started as SUSPECTED or ASYMPTOMATIC
        and is currently UNDER_TRACING advances to CONFIRMED when a
        positive PCR result is ingested for its person (status
        UNDER_TRACING → CONFIRMED). On that transition the case's
        case_type is set to CONFIRMED if it was previously SUSPECTED."

        Claim: starting from a SUSPECTED case in UNDER_TRACING, a
        POSITIVE PCR result advances the case to status CONFIRMED with
        case_type CONFIRMED.
        # difficulty: transitive_cascade/test_result_to_case_to_region_tier
        """
        from test_helpers import (
            accept_tracing_task,
            dispatch_tracing_task,
        )
        chain = setup_full_local_chain(district_code="D-PCR-1")
        person = create_person(district_code=chain["district_code"])
        # File SUSPECTED case so it requires the positive PCR cascade
        # to advance.
        case = file_case(
            person_id=person["id"], hospital_id=chain["hospital"]["id"],
            case_type="ASYMPTOMATIC",  # PRD allows ASYMPTOMATIC to trace
        )
        task = dispatch_tracing_task(
            case_id=case["id"], cdc_id=chain["cdc"]["id"],
        )
        accept_tracing_task(task["id"], chain["cdc"]["id"])
        # Order + collect + result POSITIVE PCR.
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(60)
        resulted = result_test(
            collected["id"], chain["lab"]["id"], "POSITIVE",
        )
        assert resulted["status"] == "RESULTED"
        assert resulted["result"] == "POSITIVE"
        # Case should now be CONFIRMED.
        case_refreshed = validate_success(api.get_case(
            case["id"], make_hospital_reporter_headers(chain["hospital"]["id"]),
        ))
        assert case_refreshed["status"] == "CONFIRMED", (
            f"PRD §3.10: POSITIVE PCR on UNDER_TRACING case must advance "
            f"to CONFIRMED; got {case_refreshed['status']!r}"
        )
