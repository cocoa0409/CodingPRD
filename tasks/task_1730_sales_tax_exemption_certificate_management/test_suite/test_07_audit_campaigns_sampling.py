"""Audit campaign sample-size calculation variants, open-time configuration
validation, and the sample-failure cascade."""
from test_helpers import (
    ApiErrorId,
    assert_remediation_action,
    create_audit_campaign_payload,
    create_campaign,
    open_campaign_with_samples,
    request_and_receive_docs,
    setup_customer_with_approved_cert,
    setup_population_tenant,
    fail_sample,
    TEST_USERS,
    validate_error,
    validate_success,
)

AUD1 = TEST_USERS["auditor_headers"]


class TestSampleSizeVariants:
    def test_statistical_95pct_ceiling(self, api, auditor_headers):
        """PRD §3.8: "Under `STATISTICAL`, the planned size is the population count multiplied by the confidence multiplier, rounded up to the next whole sample, with a hard minimum of one sample. The confidence multiplier is ten percent (0.10) for a target of 90, fifteen percent (0.15) for 95, and twenty-five percent (0.25) for 99."
        PRD §3.8: "Opening records the acting auditor as `opened_by_user_id`, moves the tenant's `audit_posture` to `UNDER_SAMPLING`, increments the versions of both campaign and tenant, and computes the campaign's `planned_sample_size` against the population — the count of the tenant's `APPROVED` certificates, restricted to certificates whose state appears in `population_state_filter` when the filter is non-empty."

        Design: Difficulty/dual_variant_calc/audit_sample_size_statistical_vs_fixed_floor
        """
        tenant = setup_population_tenant(12, state="CA")  # population == 12
        camp = create_campaign(tenant["id"], name="A-stat", population_state_filter=["CA"],
                               sampling_method="STATISTICAL", target_confidence_pct=95)
        opened = validate_success(api.open_audit_campaign(tenant["id"], camp["id"], auditor_headers), 200)
        # ceil(12 * 0.15) = ceil(1.8) = 2
        assert opened["planned_sample_size"] == 2, (
            f"STATISTICAL at 95% over population 12 must plan ceil(1.8) = 2, "
            f"got {opened['planned_sample_size']}")
        assert opened["status"] == "SAMPLING"

    def test_fixed_floor_floor_wins_over_population(self, api, auditor_headers):
        """PRD §3.8: "Under `FIXED_FLOOR`, the planned size is the larger of the campaign's `floor_sample_size` and the smaller of the population count and five. The floor wins even when it exceeds the population: a population of three certificates with a `floor_sample_size` of ten yields a plan of ten samples."

        Design: Difficulty/dual_variant_calc/audit_sample_size_statistical_vs_fixed_floor
        """
        tenant = setup_population_tenant(12, state="CA")  # population == 12
        camp = create_campaign(tenant["id"], name="B-floor", population_state_filter=["CA"],
                               sampling_method="FIXED_FLOOR", floor_sample_size=10)
        opened = validate_success(api.open_audit_campaign(tenant["id"], camp["id"], auditor_headers), 200)
        # max(10, min(12, 5)) = max(10, 5) = 10
        assert opened["planned_sample_size"] == 10, (
            f"FIXED_FLOOR with floor 10 over population 12 must plan 10, "
            f"got {opened['planned_sample_size']}")


class TestCampaignOpenValidation:
    def test_open_rejects_incoherent_statistical_config(self, api, auditor_headers):
        """PRD §3.8: "The configuration must be coherent at open time: the `sampling_method` must be one of the two supported values, a `STATISTICAL` campaign must carry a `target_confidence_pct` of 90, 95, or 99, and a `FIXED_FLOOR` campaign must carry a `floor_sample_size` of at least 1; an incoherent configuration is rejected as an invalid transition with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/calculations/campaign_open_requires_valid_sampling_method_config
        """
        tenant = setup_population_tenant(0, state="CA")  # no population needed for the gate
        camp = create_campaign(tenant["id"], name="A", population_state_filter=[],
                               sampling_method="STATISTICAL", target_confidence_pct=85)
        res = api.open_audit_campaign(tenant["id"], camp["id"], auditor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


class TestSampleFailCascade:
    def test_sample_fail_drops_customer_to_failed_sampling(self, api, auditor_headers):
        """PRD §3.8: "Failing moves the sample to `FAILED`, requires the auditor to supply a `failure_reason`, drops the customer to `FAILED_SAMPLING`, and automatically creates a `RemediationAction` in `OPEN` status with `action_type` `COLLECT_NEW_CERT`, assigned to the customer's primary compliance officer."
        PRD §3.2: "When any sample for the customer reaches `FAILED` or `EXPIRED_NO_RESPONSE`, standing moves `SAMPLED` → `FAILED_SAMPLING` and the tenant's `audit_posture` is recomputed."

        Design: Difficulty/transitive_cascade/sample_fail_cascade_to_customer_standing
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]
        camp, samples = open_campaign_with_samples(
            tid=tid, population_state_filter=["CA"], floor_sample_size=1)
        pre = validate_success(api.get_customer(tid, cust["id"], auditor_headers), 200)
        assert pre["audit_standing"] == "SAMPLED", (
            "creating a sample row must move the customer to SAMPLED")

        request_and_receive_docs(tid, samples[0]["id"])
        fail_sample(tid, samples[0]["id"], "signature illegible")
        post = validate_success(api.get_customer(tid, cust["id"], auditor_headers), 200)
        assert post["audit_standing"] == "FAILED_SAMPLING"

    def test_sample_fail_auto_creates_collect_new_cert_remediation(self, api, auditor_headers):
        """PRD §3.8: "Failing moves the sample to `FAILED`, requires the auditor to supply a `failure_reason`, drops the customer to `FAILED_SAMPLING`, and automatically creates a `RemediationAction` in `OPEN` status with `action_type` `COLLECT_NEW_CERT`, assigned to the customer's primary compliance officer."

        Design: Difficulty/transitive_cascade/sample_fail_cascade_to_customer_standing
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]
        camp, samples = open_campaign_with_samples(
            tid=tid, population_state_filter=["CA"], floor_sample_size=1)
        request_and_receive_docs(tid, samples[0]["id"])
        failed = fail_sample(tid, samples[0]["id"], "signature illegible")
        assert failed["outcome"] == "FAILED"

        actions = validate_success(
            api.list_remediation_actions(tid, samples[0]["id"], auditor_headers), 200)
        assert len(actions) == 1, f"exactly one auto-created remediation expected, got {len(actions)}"
        assert_remediation_action(actions[0])
        assert actions[0]["status"] == "OPEN"
        assert actions[0]["action_type"] == "COLLECT_NEW_CERT"
