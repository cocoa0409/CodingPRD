"""Onboarding: Client and Translator creation, validation, defaults.

PRD §3.1 (Onboarding Clients and Translators).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    assert_client,
    assert_translator,
    create_client,
    create_client_payload,
    create_translator,
    create_translator_payload,
    language_pair,
    pass_translator_test,
)


# ===========================================================================
# Client creation
# ===========================================================================
class TestClientCreation:

    def test_create_client_returns_active_status(self):
        """PRD §3.1: "A newly created client's status defaults to ACTIVE."

        Claim: POST /clients yields Client.status == "ACTIVE".
        """
        client = create_client()
        assert client["status"] == "ACTIVE"
        assert_client(client)

    def test_tax_rate_out_of_range_rejected_validation_failed(self):
        """PRD §3.1: "the tax rate that will be applied to every payable
        line item the platform produces for the client (tax_rate_bps, an
        integer in basis points between 0 and 3000 inclusive)."

        Claim: tax_rate_bps == 3001 -> body-schema violation rejected.
        """
        resp = api_client.create_client(
            create_client_payload(tax_rate_bps=3001), PM,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)

    def test_payment_cycle_days_invalid_value_rejected(self):
        """PRD §3.1: "the deferral window that turns a published payout
        into a payable one (payment_cycle_days, restricted to the set 0,
        7, 15, 30, and 45)."

        Claim: payment_cycle_days == 14 -> ERR_VALIDATION_FAILED.
        """
        resp = api_client.create_client(
            create_client_payload(payment_cycle_days=14), PM,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)

    @pytest.mark.parametrize("cycle", [0, 7, 15, 30, 45])
    def test_payment_cycle_days_accepts_allowed_values(self, cycle):
        """PRD §3.1: "the deferral window that turns a published payout
        into a payable one (payment_cycle_days, restricted to the set 0,
        7, 15, 30, and 45)."

        Claim: every allowed value succeeds.
        """
        c = create_client(payment_cycle_days=cycle)
        assert c["payment_cycle_days"] == cycle


# ===========================================================================
# Translator creation and defaults
# ===========================================================================
class TestTranslatorCreation:

    def test_default_grade_is_junior(self):
        """PRD §3.1: "the translator's tier (grade, defaulting to JUNIOR
        and one of JUNIOR, INTERMEDIATE, SENIOR, EXPERT)."

        Claim: Translator created without grade -> grade == "JUNIOR".
        """
        payload = create_translator_payload()
        payload.pop("grade", None)
        resp = api_client.create_translator(payload, PM)
        data = validate_success(resp, 201)
        assert data["grade"] == "JUNIOR"

    def test_default_availability_status_is_available(self):
        """PRD §3.1: "The translator's availability_status ... defaults to
        AVAILABLE."

        Claim: new Translator -> availability_status == "AVAILABLE".
        """
        t = create_translator()
        assert t["availability_status"] == "AVAILABLE"

    def test_default_test_translation_passed_is_false(self):
        """PRD §3.1: "the test-translation gate test_translation_passed
        defaults to false."

        Claim: new Translator -> test_translation_passed == false.
        """
        t = create_translator()
        assert t["test_translation_passed"] is False

    def test_default_workload_segments_open_is_zero(self):
        """PRD §3.1: "the open-workload counter workload_segments_open
        defaults to 0."

        Claim: new Translator -> workload_segments_open == 0.
        """
        t = create_translator()
        assert t["workload_segments_open"] == 0

    def test_default_quality_scores_are_one_hundred(self):
        """PRD §3.1: "Two computed reputational fields are initialised at
        100.00 — rolling_quality_score and latest_quality_score."

        Claim: new Translator -> both reputational fields == 100.00.
        """
        t = create_translator()
        assert float(t["rolling_quality_score"]) == 100.00
        assert float(t["latest_quality_score"]) == 100.00

    def test_language_pair_same_source_and_target_rejected(self):
        """PRD §3.1: "language_pairs, each entry an object with source_lang
        and target_lang ISO 639-1 codes, with the two codes required to
        differ within any single pair."

        Claim: a language_pair with identical source and target -> rejected.
        """
        resp = api_client.create_translator(
            create_translator_payload(
                language_pairs=[language_pair("en", "en")],
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)

    def test_pass_test_sets_test_translation_passed_true(self):
        """PRD §3.1: "A separate operation by the project manager clears
        the test gate by setting test_translation_passed to true."

        Claim: POST /translators/{id}/pass-test toggles flag to true.
        """
        t = create_translator()
        assert t["test_translation_passed"] is False
        t2 = pass_translator_test(t["id"])
        assert t2["test_translation_passed"] is True

    def test_pass_test_bumps_version(self):
        """PRD §2.7: "Every state transition produced by a state machine
        in this document refreshes the updated_at of the transitioning
        entity, increments its version."

        Claim: pass-test mutation increments Translator.version.
        """
        t = create_translator()
        t2 = pass_translator_test(t["id"])
        assert t2["version"] == t["version"] + 1
