"""Transitions that a child resource allows but a parent resource forbids.

Releasing a unit to the floor reads its machine model's certification state, and
submitting a package quote reads its distributor's channel standing.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
)


class TestReleaseToFloorReadsTheModelCertificationState:
    """A PLANNED unit may only reach the floor behind a certified model."""

    def test_01_release_is_refused_while_the_model_is_still_draft(self, api):
        """A unit whose own state machine permits PLANNED to ON_FLOOR is still
        refused because its machine model has never been certified.

        PRD: "The build order's model has `certification_state` of `CERTIFIED` or `RELEASED` — otherwise `ERR_MODEL_NOT_CERTIFIED`, HTTP 409, on release to floor."
        Design: Difficulty/cross_entity_state_dependency/release_to_floor_requires_model_certified
        """
        model = fx.make_model(api)
        build = fx.make_build_order(api, model["id"])

        response = api.release_to_floor(build["id"], PLANT_MANAGER)
        validate_error(response, E.ERR_MODEL_NOT_CERTIFIED, expected_status=409)

        after = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(after, "PLANNED")

    def test_02_release_succeeds_once_the_dossier_certifies_the_model(self, api):
        """Approving both review dimensions of the model's dossier moves the model
        to CERTIFIED, and the byte-identical release then succeeds.

        PRD: "Only the second approval, the one that makes both dimensions `APPROVED`, advances the dossier from `IN_REVIEW` to `CERTIFIED`."
        Design: Difficulty/cross_entity_state_dependency/release_to_floor_requires_model_certified
        """
        model = fx.make_model(api)
        build = fx.make_build_order(api, model["id"])

        refused = api.release_to_floor(build["id"], PLANT_MANAGER)
        validate_error(refused, E.ERR_MODEL_NOT_CERTIFIED, expected_status=409)

        dossier = fx.make_dossier(api, model["id"])
        fx.approve_both_dimensions(api, dossier["id"])

        dossier_after = validate_success(
            api.get_certification_dossier(dossier["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert dossier_after["dossier_state"] == "CERTIFIED"

        model_after = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert model_after["certification_state"] == "CERTIFIED"

        released = validate_success(
            api.release_to_floor(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(released, "ON_FLOOR")
        assert released["rework_count"] == 0


class TestQuoteSubmissionReadsTheDistributorStanding:
    """A DRAFT quote with a line may only be submitted by an authorised channel."""

    def test_01_submission_is_refused_while_the_distributor_is_pending_training(
        self, api
    ):
        """The quote's own state machine allows DRAFT to SUBMITTED, but the parent
        distributor has not finished its installation training.

        PRD: "The acting or referenced distributor's standing permits the fiscal operation: quote submission requires `distributor_state` of `AUTHORIZED`, and a certification grant for a distributor-employed technician requires `distributor_state` of `AUTHORIZED` or `PROBATION`."
        Design: Difficulty/cross_entity_state_dependency/quote_submit_requires_distributor_authorized
        """
        env = fx.make_pending_distributor(api)
        model = fx.make_model(api)
        quote = fx.make_quote(
            api,
            env,
            financing_program="NONE",
            package_discount_pct=0.00,
            freight_cents=0,
        )
        fx.add_quote_line(api, quote["id"], env, model["id"], quantity=1)

        response = api.submit_quote(quote["id"], env["headers"])
        validate_error(response, E.ERR_DISTRIBUTOR_NOT_AUTHORIZED, expected_status=409)

        after = validate_success(
            api.get_quote(quote["id"], env["headers"]), expected_status=200
        )
        a.assert_quote_state(after, "DRAFT")
        assert after["line_count"] == 1

    def test_02_submission_succeeds_once_training_authorizes_the_distributor(
        self, api
    ):
        """Recording installation and payment-systems training for two distinct
        technicians authorises the channel, and the identical submission passes.

        PRD: "The record that satisfies both conditions moves the distributor from `PENDING_TRAINING` to `AUTHORIZED`, sets `installation_training_state` to `COMPLETE`, and advances the `version` by 1."
        Design: Difficulty/cross_entity_state_dependency/quote_submit_requires_distributor_authorized
        """
        env = fx.make_pending_distributor(api)
        model = fx.make_model(api)
        quote = fx.make_quote(
            api,
            env,
            financing_program="NONE",
            package_discount_pct=0.00,
            freight_cents=0,
        )
        line = fx.add_quote_line(api, quote["id"], env, model["id"], quantity=1)

        refused = api.submit_quote(quote["id"], env["headers"])
        validate_error(refused, E.ERR_DISTRIBUTOR_NOT_AUTHORIZED, expected_status=409)

        fx.record_training(
            api,
            env["distributor"]["id"],
            env["technicians"][0]["id"],
            "INSTALLATION",
            "2026-07-20",
        )
        fx.record_training(
            api,
            env["distributor"]["id"],
            env["technicians"][1]["id"],
            "PAYMENT_SYSTEMS",
            "2026-07-21",
        )

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert distributor["distributor_state"] == "AUTHORIZED"
        assert distributor["trained_technician_count"] == 2
        assert distributor["installation_training_state"] == "COMPLETE"

        submitted = validate_success(
            api.submit_quote(quote["id"], env["headers"]), expected_status=200
        )
        a.assert_quote_state(submitted, "SUBMITTED")
        assert submitted["line_count"] == 1
        a.assert_cents(submitted["total_cents"], 1250000)
        a.assert_cents(submitted["origination_fee_cents"], 0)
        a.assert_cents(submitted["financed_principal_cents"], 0)
        assert submitted["provisional_apr_bp"] is None

        line_after = validate_success(
            api.get_quote_line(line["id"], env["headers"]), expected_status=200
        )
        a.assert_cents(line_after["line_total_cents"], 1250000)
