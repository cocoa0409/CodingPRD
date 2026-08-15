"""The pre-boarding safety gate, immutable inspection records, and haul-sample
constraints."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_safety_inspection,
    board_deployment,
    create_deployment_for_notice,
    create_haul_sample_payload,
    create_safety_inspection_payload,
    make_observer_headers,
    record_pass_inspection,
    setup_notice_scenario,
    validate_error,
    validate_success,
)


def _scheduled_deployment():
    bundle = setup_notice_scenario()
    deployment = create_deployment_for_notice(
        bundle["notice"]["id"], bundle["observer"]["id"],
        "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
    )
    return bundle, deployment


class TestSafetyGate:
    def test_board_from_scheduled_rejected(self, api, coordinator_headers):
        """PRD §3.4: "Boarding itself is the observer's act, permitted only
        from `READY_TO_DEPLOY` and moving the deployment to `AT_SEA`; a
        boarding attempt from `SCHEDULED` or `SAFETY_HOLD` — that is, without a
        current passing inspection — is rejected with
        `ERR_SAFETY_CHECK_REQUIRED`."

        Design: Corner/state_machines/deployment_board_from_scheduled_rejected_safety_check_required
        """
        bundle, deployment = _scheduled_deployment()
        assert deployment["status"] == "SCHEDULED"
        resp = api.board_deployment(
            deployment["id"], {}, make_observer_headers(bundle["observer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_CHECK_REQUIRED, 409)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "SCHEDULED"

    def test_fail_without_deficiency_notes_rejected(self, api, coordinator_headers):
        """PRD §3.4: "All five must be present; a checklist with missing
        entries is rejected with `ERR_SAFETY_CHECKLIST_INCOMPLETE`." and "A
        fail requires `deficiency_notes` — absent notes on a failing checklist
        again yield `ERR_SAFETY_CHECKLIST_INCOMPLETE` — drops the deployment
        into `SAFETY_HOLD`, and sets `latest_safety_result` to `FAIL`."

        Design: Corner/validations/safety_checklist_incomplete_when_deficiency_notes_missing_on_fail
        """
        bundle, deployment = _scheduled_deployment()
        obs = make_observer_headers(bundle["observer"]["id"])
        fail_payload = create_safety_inspection_payload(comms_equipment_ok=False)
        no_notes = api.create_safety_inspection(deployment["id"], fail_payload, obs)
        validate_error(no_notes, ApiErrorId.ERR_SAFETY_CHECKLIST_INCOMPLETE, 422)

        with_notes = api.create_safety_inspection(
            deployment["id"],
            create_safety_inspection_payload(
                comms_equipment_ok=False, deficiency_notes="VHF radio inoperable"
            ),
            obs,
        )
        inspection = validate_success(with_notes, 201)
        assert inspection["result"] == "FAIL"
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "SAFETY_HOLD"
        assert current["latest_safety_result"] == "FAIL"

    def test_reinspection_requires_supersession(self, api, coordinator_headers):
        """PRD §3.4: "Re-inspection from `SAFETY_HOLD` must reference the
        failed inspection it supersedes via `supersedes_inspection_id`;
        pointing anywhere but the deployment's most recent `FAIL` inspection
        yields `ERR_SAFETY_SUPERSESSION_REQUIRED`, and a passing re-inspection
        lifts the deployment to `READY_TO_DEPLOY`."

        Design: Corner/validations/safety_supersession_required_on_reinspection_from_hold
        """
        bundle, deployment = _scheduled_deployment()
        obs = make_observer_headers(bundle["observer"]["id"])
        fail = api.create_safety_inspection(
            deployment["id"],
            create_safety_inspection_payload(
                comms_equipment_ok=False, deficiency_notes="VHF radio inoperable"
            ),
            obs,
        )
        validate_success(fail, 201)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "SAFETY_HOLD"

        # Re-inspection without supersedes_inspection_id is rejected.
        missing_ref = api.create_safety_inspection(
            deployment["id"], create_safety_inspection_payload(), obs
        )
        validate_error(missing_ref, ApiErrorId.ERR_SAFETY_SUPERSESSION_REQUIRED, 422)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "SAFETY_HOLD"
        assert current["latest_safety_result"] == "FAIL"


class TestSafetyInspectionRecord:
    def test_inspection_is_immutable_append_only(self, api, coordinator_headers):
        """PRD §2.4: "One deliberate exception: a safety-inspection record is
        immutable once filed, so it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it." PRD §3.4: "The `result`
        is computed, never supplied: `PASS` exactly when all five booleans are
        true, otherwise `FAIL`."

        Design: Corner/entities/safety_inspection_immutable_no_version_field
        """
        bundle, deployment = _scheduled_deployment()
        inspection = record_pass_inspection(deployment["id"], bundle["observer"]["id"])
        assert_safety_inspection(inspection)
        assert inspection["result"] == "PASS"
        assert inspection["deployment_id"] == deployment["id"]
        assert inspection["vessel_id"] == bundle["vessel"]["id"]
        assert inspection["observer_id"] == bundle["observer"]["id"]


class TestHaulSampling:
    def test_sampling_ratio_computed_and_bounded(self, api, coordinator_headers):
        """PRD §3.5: "The computed `sampling_ratio` — the sampled weight
        divided by the total haul weight, rounded half-up to four decimals —
        must lie between 0.2000 and 1.0000 inclusive, else
        `ERR_SAMPLE_RATIO_OUT_OF_RANGE`."

        Design: Corner/entities/haul_sample_sampling_ratio_computed_and_bounded
        """
        bundle, deployment = _scheduled_deployment()
        obs_id = bundle["observer"]["id"]
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        obs = make_observer_headers(obs_id)

        ok = api.create_haul_sample(
            deployment["id"],
            create_haul_sample_payload(
                haul_date="2026-09-12T00:00:00Z", haul_number=1,
                sampled_weight_kg=250, total_haul_weight_kg=1000,
            ),
            obs,
        )
        sample = validate_success(ok, 201)
        assert sample["sampling_ratio"] == pytest.approx(0.25, abs=1e-4)
        assert sample["status"] == "RECORDED"

        # 199 / 1000 == 0.1990 < 0.2000: rejected.
        too_thin = api.create_haul_sample(
            deployment["id"],
            create_haul_sample_payload(
                haul_date="2026-09-12T00:00:00Z", haul_number=2,
                sampled_weight_kg=199, total_haul_weight_kg=1000,
            ),
            obs,
        )
        validate_error(too_thin, ApiErrorId.ERR_SAMPLE_RATIO_OUT_OF_RANGE, 422)

    def test_duplicate_haul_number_rejected(self, api, coordinator_headers):
        """PRD §3.5: "a `haul_number` starting at 1 and unique within the
        deployment (`ERR_DUPLICATE_HAUL_NUMBER`)"

        Design: Corner/validations/duplicate_haul_number_within_deployment_rejected
        """
        bundle, deployment = _scheduled_deployment()
        obs_id = bundle["observer"]["id"]
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        obs = make_observer_headers(obs_id)

        first = api.create_haul_sample(
            deployment["id"],
            create_haul_sample_payload(haul_date="2026-09-12T00:00:00Z", haul_number=1),
            obs,
        )
        validate_success(first, 201)
        dup = api.create_haul_sample(
            deployment["id"],
            create_haul_sample_payload(
                haul_date="2026-09-13T00:00:00Z", haul_number=1,
                species_code="PCOD", sampled_weight_kg=50, total_haul_weight_kg=200,
            ),
            obs,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_HAUL_NUMBER, 409)
