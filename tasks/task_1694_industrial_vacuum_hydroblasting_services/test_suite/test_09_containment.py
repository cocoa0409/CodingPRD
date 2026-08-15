"""Containment record branching, sequencing, and the field-completion gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_field_work,
    create_containment_payload,
    create_job_in_progress,
    get_success_data,
    validate_error,
    verify_containment,
)

PM = TEST_USERS["project_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


class TestContainmentVerifyBranch:
    def test_ratio_below_threshold_lands_deficient(self, api):
        """PRD §3.4: "a `capture_ratio` of at least 0.9500 moves the record to
        `VERIFIED` — exactly 0.9500 passes — while anything below lands in
        `DEFICIENT`."

        Design: Corner/state_machines/containment_verify_branches_on_capture_ratio
        """
        ctx = create_job_in_progress()
        rec = get_success_data(
            api.create_containment_record(
                create_containment_payload(
                    ctx["job"]["id"], water_used_gallons=2000,
                    water_captured_gallons=1899,
                ),
                FS,
            )
        )
        assert rec["capture_ratio"] == pytest.approx(0.9495)
        verified = get_success_data(api.verify_containment_record(rec["id"], PM))
        assert verified["status"] == "DEFICIENT"

    def test_ratio_exactly_threshold_lands_verified_and_sequence_monotone(self, api):
        """PRD §3.4: "a `capture_ratio` of at least 0.9500 moves the record to
        `VERIFIED` — exactly 0.9500 passes".
        PRD §3.4: "Each record takes the next per-job `sequence` — the highest
        existing sequence plus one".

        Design: Corner/state_machines/containment_verify_branches_on_capture_ratio
        """
        ctx = create_job_in_progress()
        rec_a = get_success_data(
            api.create_containment_record(
                create_containment_payload(
                    ctx["job"]["id"], water_used_gallons=2000,
                    water_captured_gallons=1899,
                ),
                FS,
            )
        )
        rec_b = get_success_data(
            api.create_containment_record(
                create_containment_payload(
                    ctx["job"]["id"], water_used_gallons=2000,
                    water_captured_gallons=1900,
                ),
                FS,
            )
        )
        assert rec_a["sequence"] == 1
        assert rec_b["sequence"] == 2
        assert rec_b["capture_ratio"] == pytest.approx(0.95)
        verified_b = get_success_data(api.verify_containment_record(rec_b["id"], PM))
        assert verified_b["status"] == "VERIFIED"


class TestContainmentGateOnFieldCompletion:
    def test_deficient_latest_record_blocks_completion(self, api):
        """PRD §3.4: "the job's latest containment record must be `VERIFIED` —
        when no records exist, or the latest is still `LOGGED` or has been found
        `DEFICIENT`, the attempt fails with `ERR_CONTAINMENT_DEFICIENT`."

        Design: Corner/validations/deficient_containment_blocks_field_completion
        """
        ctx = create_job_in_progress()
        rec1 = get_success_data(
            api.create_containment_record(
                create_containment_payload(
                    ctx["job"]["id"], water_used_gallons=1000,
                    water_captured_gallons=900,
                ),
                FS,
            )
        )
        get_success_data(api.verify_containment_record(rec1["id"], PM))
        resp = api.complete_field_work(
            ctx["job"]["id"], {"gallons_removed": 100, "feet_cleaned": 0}, PM
        )
        validate_error(resp, ApiErrorId.ERR_CONTAINMENT_DEFICIENT.value)
        assert resp.status_code == 422

    def test_newer_verified_record_unblocks_completion(self, api):
        """PRD §3.4: "the job's latest containment record must be `VERIFIED`".
        PRD §3.4: "Each record takes the next per-job `sequence` — the highest
        existing sequence plus one, so \"latest\" always means the highest
        `sequence`".

        Design: Corner/validations/deficient_containment_blocks_field_completion
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        bad = get_success_data(
            api.create_containment_record(
                create_containment_payload(job_id, water_used_gallons=1000,
                                           water_captured_gallons=900),
                FS,
            )
        )
        get_success_data(api.verify_containment_record(bad["id"], PM))
        # A later record that verifies VERIFIED supersedes the DEFICIENT one.
        good = get_success_data(
            api.create_containment_record(
                create_containment_payload(job_id, water_used_gallons=500,
                                           water_captured_gallons=500),
                FS,
            )
        )
        get_success_data(api.verify_containment_record(good["id"], PM))
        completed = complete_field_work(job_id, gallons=100, feet=0)
        assert completed["execution_status"] == "FIELD_COMPLETE"
