"""Cross-entity state dependencies and the estimate/claim settlement aggregate:
complete gated on chamber dryness, approve gated on claim OPEN, OCC on estimate
create, and supersede of the prior draft.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_claim,
    create_job,
    create_estimate_payload,
    setup_monitoring_job,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ESTIMATOR,
    ADJUSTER,
    create_and_approve_estimate,
)


# ===========================================================================
# Cross-entity state dependency (Difficulty/cross_entity_state_dependency)
# ===========================================================================
class TestCompleteRequiresDriedChambers:
    def test_complete_blocked_by_wet_chamber(self):
        """PRD §3.7: "The job's `drying_status` must be `DRY_STANDARD_MET` —
        equivalently, every non-`DECOMMISSIONED` chamber must be `DRIED` — else the
        completion is rejected with `ERR_DRY_STANDARD_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/job_complete_requires_all_chambers_dried
        """
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # Approve an estimate and remove all equipment, but leave the chamber WET.
        create_and_approve_estimate(job_id, line_items=[{"qty": 1, "unit_price_cents": 5000}],
                                    estimated_drying_days=2)
        get_success_data(api.remove_placement(ctx["air_placement"]["id"], tech_hdr))
        get_success_data(api.remove_placement(ctx["dehu_placement"]["id"], tech_hdr))
        assert get_success_data(api.get_chamber(ch_id, tech_hdr))["status"] == "OPEN"
        resp = api.complete_job(job_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_DRY_STANDARD_NOT_MET.value)

    def test_complete_succeeds_once_chamber_dried(self):
        """PRD §3.7: "On successful completion the job's `status` becomes
        `COMPLETED`".
        PRD §3.7: "The job's `drying_status` must be `DRY_STANDARD_MET` —
        equivalently, every non-`DECOMMISSIONED` chamber must be `DRIED`".

        Design: Difficulty/cross_entity_state_dependency/job_complete_requires_all_chambers_dried
        """
        from test_helpers import create_reading_payload
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        create_and_approve_estimate(job_id)
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        get_success_data(api.remove_placement(ctx["air_placement"]["id"], tech_hdr))
        get_success_data(api.remove_placement(ctx["dehu_placement"]["id"], tech_hdr))
        data = validate_success(api.complete_job(job_id, tech_hdr), 200)
        assert data["status"] == "COMPLETED"


class TestApproveRequiresClaimOpen:
    def _two_jobs_one_claim(self):
        claim = create_claim(coverage_limit_cents=9_000_000)
        j1 = create_job(claim["id"], loss_type="WATER",
                        water_category=1, water_class=1, property_address="14a")
        j2 = create_job(claim["id"], loss_type="WATER",
                        water_category=1, water_class=1, property_address="14b")
        v1 = get_success_data(api.get_job(j1["id"], DISPATCHER))["version"]
        e1 = get_success_data(
            api.create_estimate(
                create_estimate_payload(j1["id"], v1, estimated_drying_days=1,
                                        line_items=[{"qty": 1, "unit_price_cents": 5000}]),
                ESTIMATOR,
            )
        )
        v2 = get_success_data(api.get_job(j2["id"], DISPATCHER))["version"]
        e2 = get_success_data(
            api.create_estimate(
                create_estimate_payload(j2["id"], v2, estimated_drying_days=1,
                                        line_items=[{"qty": 1, "unit_price_cents": 5000}]),
                ESTIMATOR,
            )
        )
        return claim, j1, j2, e1, e2

    def test_first_approval_settles_claim(self):
        """PRD §3.5: "On a successful approval the estimate becomes `APPROVED`, and
        across the aggregate boundary the parent claim transitions to `SETTLED`
        with its `settled_estimate_id` set to this estimate's id."

        Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_claim_open
        """
        claim, j1, j2, e1, e2 = self._two_jobs_one_claim()
        get_success_data(api.approve_estimate(e1["id"], ADJUSTER))
        settled = get_success_data(api.get_claim(claim["id"], ADJUSTER))
        assert settled["status"] == "SETTLED"
        assert settled["settled_estimate_id"] == e1["id"]

    def test_second_approval_on_settled_claim_rejected(self):
        """PRD §3.5: "The parent claim's `status` must still be `OPEN`; approving
        against a claim already `SETTLED` is rejected with
        `ERR_CLAIM_ALREADY_SETTLED`."

        Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_claim_open
        """
        claim, j1, j2, e1, e2 = self._two_jobs_one_claim()
        get_success_data(api.approve_estimate(e1["id"], ADJUSTER))
        resp = api.approve_estimate(e2["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_SETTLED.value)


# ===========================================================================
# OCC on estimate create (Corner/cross_cutting_complexity_layers)
# ===========================================================================
class TestEstimateOcc:
    def test_stale_job_version_rejected(self):
        """PRD §2.7: "The server compares `expected_job_version` against the job's
        current `version`. If they do not match — because another writer has
        advanced the job's version since the client last read it — the create is
        rejected with `ERR_STALE_JOB_VERSION` at HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_job_version_on_estimate_create
        """
        claim = create_claim(coverage_limit_cents=9_000_000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        v1 = job["version"]
        # First create succeeds and bumps the job version.
        get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], v1, estimated_drying_days=1,
                                        line_items=[{"qty": 1, "unit_price_cents": 5000}]),
                ESTIMATOR,
            )
        )
        # Second create still carries the stale pre-E1 version.
        resp = api.create_estimate(
            create_estimate_payload(job["id"], v1, estimated_drying_days=1,
                                    line_items=[{"qty": 1, "unit_price_cents": 5000}]),
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_VERSION.value)

    def test_current_version_supersedes_prior_draft(self):
        """PRD §3.5: "A successful create starts the estimate in `DRAFT` status,
        increments the job's `version` by 1, and — because only one draft may be
        live at a time — automatically supersedes any prior `DRAFT` estimate on the
        same job, moving that prior draft `DRAFT → SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_supersedes_prior_draft
        """
        claim = create_claim(coverage_limit_cents=9_000_000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        e1 = get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], job["version"], estimated_drying_days=1,
                                        line_items=[{"qty": 1, "unit_price_cents": 5000}]),
                ESTIMATOR,
            )
        )
        v_now = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        resp = api.create_estimate(
            create_estimate_payload(job["id"], v_now, estimated_drying_days=2,
                                    line_items=[{"qty": 1, "unit_price_cents": 6000}]),
            ESTIMATOR,
        )
        e2 = validate_success(resp, 201)
        assert e2["status"] == "DRAFT"
        assert get_success_data(api.get_estimate(e1["id"], ESTIMATOR))["status"] == "SUPERSEDED"
