"""Finish samples: reject/resubmit cycle, complete-build gate."""
import pytest

from test_helpers import (
    ENGINEER,
    EST,
    FOREMAN,
    PAINT,
    ApiErrorId,
    assert_instant_equals,
    create_finish_sample_payload,
    get_success_data,
    make_client_pm_headers,
    setup_accepted_production,
    setup_in_build_production,
    validate_error,
    validate_success,
)


class TestFinishSampleCycle:
    def test_reject_then_resubmit_then_approve(self, api):
        """PRD §3.4: "A `ClientPM` acting for the production's client approves
        it (`SUBMITTED → APPROVED`) or rejects it with a `rejection_note`
        (`SUBMITTED → REJECTED`); the note is recorded on the sample. A
        `PaintCharge` resubmits a `REJECTED` sample with a new `texture_ref`,
        returning it to `SUBMITTED` and incrementing `round_no`."

        Design: Difficulty/non_linear_state_machine/finish_sample_reject_resubmit_cycle_rounds
        """
        _, client, _, _, production = setup_accepted_production()
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        # Reject round 1
        rej = validate_success(api.reject_finish_sample(
            sample["id"], {"rejection_note": "Too glossy"},
            make_client_pm_headers(client["id"]),
        ))
        assert rej["status"] == "REJECTED"
        assert rej["rejection_note"] == "Too glossy"
        # Resubmit round 2
        res = validate_success(api.resubmit_finish_sample(
            sample["id"], {"texture_ref": "tex_v2_matte"}, PAINT,
        ))
        assert res["status"] == "SUBMITTED"
        assert res["round_no"] == 2
        assert res["texture_ref"] == "tex_v2_matte"
        # Approve round 2
        app = validate_success(api.approve_finish_sample(
            sample["id"], make_client_pm_headers(client["id"]),
        ))
        assert app["status"] == "APPROVED"
        assert app["round_no"] == 2

    def test_rejection_note_persists_after_loop(self, api):
        """PRD §3.4: "the note is recorded on the sample."

        Design: Difficulty/non_linear_state_machine/finish_sample_reject_resubmit_cycle_rounds
        """
        _, client, _, _, production = setup_accepted_production()
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        api.reject_finish_sample(sample["id"], {"rejection_note": "Too glossy"},
                                 make_client_pm_headers(client["id"]))
        api.resubmit_finish_sample(sample["id"], {"texture_ref": "tex_v2"}, PAINT)
        api.approve_finish_sample(sample["id"], make_client_pm_headers(client["id"]))
        final = get_success_data(api.get_finish_sample(sample["id"], EST))
        assert final["status"] == "APPROVED"
        assert final["round_no"] == 2
        assert final["rejection_note"] == "Too glossy"


class TestCompleteBuildGateOnSamples:
    def test_complete_build_fails_with_submitted_sample(self, api):
        """PRD §3.4: "every finish sample of the production is `APPROVED`
        (else `ERR_FINISH_NOT_APPROVED`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/complete_build_requires_finish_samples_approved
        """
        _, client, _, _, production, _rev, _res = setup_in_build_production()
        # Sample still SUBMITTED
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        resp = api.complete_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_FINISH_NOT_APPROVED, 409)

    def test_complete_build_succeeds_after_sample_approved(self, api):
        """PRD §3.4: "On success the production moves `IN_BUILD → BUILT` and
        the system records the logical clock reading in `built_at`."  PRD
        §2.4: "Before any operator has set it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/cross_entity_state_dependency/complete_build_requires_finish_samples_approved
        """
        _, client, _, _, production, _rev, _res = setup_in_build_production()
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        api.approve_finish_sample(sample["id"], make_client_pm_headers(client["id"]))
        resp = api.complete_build(production["id"], FOREMAN)
        built = validate_success(resp)
        assert built["status"] == "BUILT"
        assert_instant_equals(built["built_at"], "2026-08-01T00:00:00Z")

    def test_complete_build_with_zero_samples_passes(self, api):
        """PRD §3.4: "every finish sample of the production is `APPROVED`
        (else `ERR_FINISH_NOT_APPROVED`, HTTP 409)." — with zero samples the
        universal holds vacuously.

        Design: Corner/cross_cutting_layers/complete_build_with_zero_finish_samples_passes
        """
        _, _, _, _, production, _rev, _res = setup_in_build_production()
        # No samples at all
        resp = api.complete_build(production["id"], FOREMAN)
        assert validate_success(resp)["status"] == "BUILT"


class TestRBACFinishSample:
    def test_paint_charge_cannot_approve_sample(self, api):
        """PRD §4 endpoint table: "Client approves the sample | ClientPM"
        (the role list is exclusive). PRD §2.1: "A request whose role is not
        listed for the endpoint it targets is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/paint_charge_cannot_approve_finish_sample
        """
        _, client, _, _, production = setup_accepted_production()
        sample = get_success_data(api.create_finish_sample(
            {"production_id": production["id"],
             "finish_code": "SCUFF_BRICK_RED", "texture_ref": "tex_v1"},
            PAINT,
        ))
        resp = api.approve_finish_sample(sample["id"], PAINT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_finish_sample(sample["id"], EST))
        assert after["status"] == "SUBMITTED"
