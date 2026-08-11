"""Reverse-engineering jobs: the fabrication failure cycle, segregation of
duties on validation, and propagation to the parent part line."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    create_fabricate_payload,
    make_engineer_headers,
    make_inspector_headers,
    validate_error,
    validate_success,
)

FABRICATOR = "eng-2"
VALIDATOR = "qi-1"

OBSOLETE_PARTS_SPEC = [
    {"oem_status": "OBSOLETE", "unit_cost_cents": 800_000, "stock_quantity": 0,
     "quantity": 2, "lead_time_days": 60, "description": "NC board"},
]


def _sourced_with_re_job(api):
    """Project in PARTS_SOURCING whose OBSOLETE line spawned a REQUESTED job."""
    ctx = fx.setup_project_approved(parts_spec=OBSOLETE_PARTS_SPEC)
    project = validate_success(api.begin_sourcing(ctx.project["id"], PM), 200)
    assert project["work_status"] == "PARTS_SOURCING"
    jobs = fx.find_re_jobs_for_project(ctx.project["id"])
    assert len(jobs) == 1
    assert jobs[0]["status"] == "REQUESTED"
    ctx.re_job = jobs[0]
    return ctx


class TestReJobFabricationFailureCycle:
    def test_failed_validation_cycles_back_to_spec_captured(self, api):
        """PRD §3.4: "A failed validation — under the same segregation rule — cycles the job back from `PROTOTYPE_FABRICATED` to `SPEC_CAPTURED` and increments its `revision_count` by one."

        Design: Difficulty/non_linear_state_machine/re_job_fabrication_failure_cycle
        """
        ctx = _sourced_with_re_job(api)
        job_id = ctx.re_job["id"]

        job = validate_success(
            api.capture_spec(job_id, make_engineer_headers(FABRICATOR)), 200
        )
        assert job["status"] == "SPEC_CAPTURED"
        job = validate_success(
            api.fabricate(job_id, create_fabricate_payload(re_cost_cents=750_000),
                          make_engineer_headers(FABRICATOR)),
            200,
        )
        assert job["status"] == "PROTOTYPE_FABRICATED"
        assert job["fabricated_by_id"] == FABRICATOR

        failed = validate_success(api.fail_re_job(job_id, make_inspector_headers(VALIDATOR)), 200)
        assert failed["status"] == "SPEC_CAPTURED"
        assert failed["revision_count"] == 1

    def test_second_fabrication_then_validation_fulfills_line(self, api):
        """PRD §3.4: "Fabrication follows: the engineer records the actual `re_cost_cents` (at least zero) and the server pins `fabricated_by_id` to the caller's `X-User-ID` as the job moves to `PROTOTYPE_FABRICATED`."
        PRD §3.4: "A passing validation moves the job to the terminal `VALIDATED`, records `validated_by_id`, and flips the parent part line from `RE_PENDING` to `RE_FULFILLED`."

        Design: Difficulty/non_linear_state_machine/re_job_fabrication_failure_cycle
        """
        ctx = _sourced_with_re_job(api)
        job_id = ctx.re_job["id"]
        line_id = ctx.lines[0]["id"]

        fx.get_success_data(api.capture_spec(job_id, make_engineer_headers(FABRICATOR)))
        fx.get_success_data(
            api.fabricate(job_id, create_fabricate_payload(re_cost_cents=750_000),
                          make_engineer_headers(FABRICATOR))
        )
        fx.get_success_data(api.fail_re_job(job_id, make_inspector_headers(VALIDATOR)))

        refab = validate_success(
            api.fabricate(job_id, create_fabricate_payload(re_cost_cents=780_000),
                          make_engineer_headers(FABRICATOR)),
            200,
        )
        assert refab["status"] == "PROTOTYPE_FABRICATED"
        assert refab["re_cost_cents"] == 780_000
        assert refab["revision_count"] == 1

        validated = validate_success(
            api.validate_re_job(job_id, make_inspector_headers(VALIDATOR)), 200
        )
        assert validated["status"] == "VALIDATED"
        assert validated["validated_by_id"] == VALIDATOR

        line_after = validate_success(api.get_part_line(line_id, PM), 200)
        assert line_after["status"] == "RE_FULFILLED"


def test_rejob_validate_by_fabricator_rejected(api):
    """PRD §3.4: "Validation belongs to a `QualityInspector` and is segregated: the validator's `X-User-ID` must differ from the job's `fabricated_by_id`, and a self-validation attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/rejob_validate_by_fabricator_rejected
    """
    ctx = _sourced_with_re_job(api)
    job_id = ctx.re_job["id"]
    fx.get_success_data(api.capture_spec(job_id, make_engineer_headers(FABRICATOR)))
    fx.get_success_data(
        api.fabricate(job_id, create_fabricate_payload(re_cost_cents=500_000),
                      make_engineer_headers(FABRICATOR))
    )

    # A QualityInspector whose X-User-ID equals the fabricator's identifier.
    res = api.validate_re_job(job_id, make_inspector_headers(FABRICATOR))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    job_after = validate_success(api.get_re_job(job_id, PM), 200)
    assert job_after["status"] == "PROTOTYPE_FABRICATED"
