"""Lab reports, sample lifecycle, and abnormal flags (PRD §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_lab_report,
    collect_sample,
    create_lab_report,
    create_lab_report_payload,
    external_lab_result_payload,
    finalize_lab_report,
    get_success_data,
    lab_report_through_result_received,
    now_iso,
    post_lab_result,
    send_to_lab,
    setup_visit_in_consult,
    unique_external_lab_ref,
    unique_event_id,
    validate_error,
    validate_success,
    vet_headers_for_visit,
)


class TestLabReportCreation:
    def test_create_lab_report(self, api):
        """PRD §3.6: 'A drafting vet orders tests by creating a lab
        report under a visit. The body carries the visit_id and the
        test_items array.'"""
        owner, pet, visit = setup_visit_in_consult()
        headers = vet_headers_for_visit(visit["id"])
        res = api.create_lab_report(
            create_lab_report_payload(visit_id=visit["id"]),
            headers,
        )
        data = validate_success(res, expected_status=201)
        assert_lab_report(data)
        assert data["status"] == "ORDERED"

    @pytest.mark.parametrize(
        "items",
        [
            [],  # empty
            [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0},
             {"code": "GLU", "name": "Glucose-dup", "ref_low": 5.0, "ref_high": 10.0}],  # dup code
            [{"code": "BAD", "name": "Bad", "ref_low": 10.0, "ref_high": 5.0}],  # ref_low > ref_high
        ],
        ids=["empty", "duplicate_code", "ref_low_ge_ref_high"],
    )
    def test_invalid_test_items_rejected(self, api, items):
        """PRD §3.6: 'A non-empty array with all unique codes and
        well-ordered ranges is required (otherwise ERR_LAB_ITEMS_INVALID).'"""
        owner, pet, visit = setup_visit_in_consult()
        headers = vet_headers_for_visit(visit["id"])
        res = api.create_lab_report(
            {"visit_id": visit["id"], "test_items": items},
            headers,
        )
        validate_error(res, "ERR_LAB_ITEMS_INVALID")


class TestLabReportLifecycle:
    def test_lifecycle_to_result_received(self, api):
        """PRD §3.6: 'The external lab returns results through the
        dedicated event endpoint, posting an external_lab_ref, the
        results array, and an event_id ... sets results, recomputes
        abnormal_codes, and transitions the report to RESULT_RECEIVED.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 7.0}]
        lr, _ref = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert lr["status"] == "RESULT_RECEIVED"


class TestAbnormalCodesExclusiveBoundary:
    """PRD §3.6: 'The abnormal_codes array is computed with exclusive
    boundary semantics on both ends.'"""

    def test_value_strictly_below_ref_low_is_abnormal(self, api):
        """PRD §3.6: 'a value strictly less than its item's ref_low or
        strictly greater than ref_high flags the code as abnormal.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 4.999}]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert "GLU" in lr["abnormal_codes"]

    def test_value_at_ref_low_is_normal(self, api):
        """PRD §3.6: 'a value exactly equal to either reference bound
        is normal.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 5.0}]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert "GLU" not in lr["abnormal_codes"]

    def test_value_at_ref_high_is_normal(self, api):
        """PRD §3.6: 'a value exactly equal to either reference bound
        is normal.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 10.0}]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert "GLU" not in lr["abnormal_codes"]

    def test_value_strictly_above_ref_high_is_abnormal(self, api):
        """PRD §3.6: 'a value strictly less than its item's ref_low or
        strictly greater than ref_high flags the code as abnormal.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 10.0001}]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert "GLU" in lr["abnormal_codes"]

    def test_abnormal_codes_sorted_ascending_lex(self, api):
        """PRD §3.6: 'The resulting list of abnormal codes is sorted in
        ascending lexicographic order for determinism.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [
            {"code": "ZZZ", "name": "z", "ref_low": 0.0, "ref_high": 1.0},
            {"code": "AAA", "name": "a", "ref_low": 0.0, "ref_high": 1.0},
            {"code": "MMM", "name": "m", "ref_low": 0.0, "ref_high": 1.0},
        ]
        # All three values strictly above ref_high → abnormal.
        results = [
            {"code": "ZZZ", "value": 5.0},
            {"code": "AAA", "value": 5.0},
            {"code": "MMM", "value": 5.0},
        ]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        assert lr["abnormal_codes"] == ["AAA", "MMM", "ZZZ"]


class TestExternalLabIdempotency:
    def test_duplicate_external_lab_ref_is_noop(self, api, platform_admin_headers):
        """PRD §3.6: 'The event endpoint is idempotent on
        external_lab_ref — when a duplicate event with the same
        external_lab_ref arrives, the response is 200 with the same
        body and no double-write.'"""
        owner, pet, visit = setup_visit_in_consult()
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 7.0}]
        lr, ref = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        # First-arrival lab is in RESULT_RECEIVED.
        assert lr["status"] == "RESULT_RECEIVED"
        # Second arrival with same external_lab_ref must return 200
        # and not change state again.
        res2 = api.external_lab_result(
            external_lab_result_payload(
                external_lab_ref=ref,
                results=results,
                event_id=unique_event_id("evt-dup"),
            ),
            platform_admin_headers,
        )
        # PRD §3.6 prescribes 200 with the same body — accept either
        # validate_success (200) or a successful 200 with same status.
        data2 = validate_success(res2)
        assert data2["status"] == "RESULT_RECEIVED"


class TestLabReportFinalize:
    def test_finalize_appends_lab_line_to_bill(self, api, cashier_headers):
        """PRD §3.6: 'Finalization appends a LAB line item to the visit's
        bill and recomputes provisional_total_cents.'"""
        from test_helpers import create_bill, recompute_bill
        owner, pet, visit = setup_visit_in_consult()
        bill = create_bill(visit_id=visit["id"])
        items = [{"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0}]
        results = [{"code": "GLU", "value": 7.0}]
        lr, _ = lab_report_through_result_received(
            visit_id=visit["id"], test_items=items, results=results,
        )
        finalize_lab_report(visit_id=visit["id"], lr_id=lr["id"])
        bill_after = get_success_data(
            api.recompute_bill(bill["id"], cashier_headers)
        )
        lab_lines = [li for li in bill_after["line_items"]
                     if li.get("kind") == "LAB"]
        assert len(lab_lines) >= 1, (
            f"Expected at least one LAB line after lab finalize, "
            f"got {bill_after['line_items']}"
        )
