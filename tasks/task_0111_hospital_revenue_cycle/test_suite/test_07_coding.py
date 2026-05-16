"""Coding record: ICD-10 / CPT validation, cpt-codes match, finalize.

Covers PRD §3.6 (coding submission and finalize).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_coding_record,
    finalize_coding,
    re_get_encounter,
    setup_charges_captured_encounter,
    setup_eligibility_verified_encounter,
    submit_coding_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Coding finalize happy path
# ===========================================================================
class TestCodingFinalize:
    """PRD §3.6: finalize advances CodingRecord to FINALIZED and the
    Encounter from CHARGES_CAPTURED to CODED."""

    def test_finalize_advances_encounter_to_coded(self, api):
        """PRD §3.6: "finalizing it transitions it to `FINALIZED`, the terminal status, and as a side effect transitions the encounter from `CHARGES_CAPTURED` to `CODED`"

        Claim: a successful finalize sets CodingRecord.status to
        FINALIZED and Encounter.status to CODED.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted]
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_coding_record(data)
        assert data["status"] == "FINALIZED"
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CODED"

    def test_finalize_initialises_version_to_one(self, api):
        """PRD §2.5: "an integer `version` that begins at 1 on creation".

        Claim: a created CodingRecord starts at version=1.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted]
        data = validate_success(
            api.submit_coding(
                encounter["id"],
                submit_coding_payload(
                    primary_icd10="J18.9", cpt_codes=cpts, finalize=True,
                ),
                TEST_USERS["coder_headers"],
            ),
            expected_status=201,
        )
        assert data["version"] == 1


# ===========================================================================
# §3.6 — ICD-10 format validation
# ===========================================================================
class TestICD10Pattern:
    """PRD §3.6: "The `primary_icd10` value must match the ICD-10-CM format — a single uppercase letter, two digits, and optionally a period followed by up to four alphanumeric characters — otherwise the submission is rejected with `ERR_INVALID_ICD10`."""

    @pytest.mark.parametrize("bad_code", [
        "j18.9",       # lowercase letter
        "999.99",      # missing letter
        "J1.9",        # only one digit
        "JJ8.9",       # two letters
        "J18.99999",   # too many post-period chars
        "",            # empty
    ])
    def test_invalid_icd10_rejected(self, api, bad_code):
        """PRD §3.6: "otherwise the submission is rejected with `ERR_INVALID_ICD10`."

        Claim: a primary_icd10 that violates the ICD-10-CM pattern
        returns ERR_INVALID_ICD10.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted]
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10=bad_code, cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_INVALID_ICD10")

    @pytest.mark.parametrize("good_code", [
        "J18",       # letter + 2 digits (no period)
        "J18.9",     # letter + 2 digits + . + 1 alphanum
        "A00.1A2B",  # letter + 2 digits + . + 4 alphanum
    ])
    def test_valid_icd10_accepted(self, api, good_code):
        """PRD §3.6: "a single uppercase letter, two digits, and
        optionally a period followed by up to four alphanumeric
        characters".

        Claim: a primary_icd10 matching the pattern is accepted.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted]
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10=good_code, cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.6 — CPT format validation
# ===========================================================================
class TestCPTPattern:
    """PRD §3.6: "Every CPT entry in `cpt_codes` must be exactly five digits long or the submission is rejected with `ERR_INVALID_CPT`."""

    def test_short_cpt_in_coding_payload_rejected(self, api):
        """PRD §3.6: "Every CPT entry in `cpt_codes` must be exactly five digits long or the submission is rejected with `ERR_INVALID_CPT`."

        Claim: cpt_codes=['9921'] (4 digits) returns ERR_INVALID_CPT.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=["9921"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_INVALID_CPT")

    def test_alpha_cpt_in_coding_payload_rejected(self, api):
        """PRD §3.6: "Every CPT entry in `cpt_codes` must be exactly five digits long or the submission is rejected with `ERR_INVALID_CPT`."

        Claim: cpt_codes=['9921A'] (non-digit) returns ERR_INVALID_CPT.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=["9921A"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_INVALID_CPT")


# ===========================================================================
# §3.6 — cpt_codes match the non-VOIDED ChargeItem multiset
# ===========================================================================
class TestCPTSetMatch:
    """PRD §3.6: "On finalize, the multiset of `cpt_codes` on the coding record must be exactly the multiset of `cpt_code` values across all non-`VOIDED` charge lines for this encounter"""

    def test_cpt_codes_subset_rejected(self, api):
        """PRD §3.6: "the codes may be in any order, but every CPT on the encounter must appear on the coding record with the correct multiplicity and vice versa. A mismatch produces `ERR_CODING_CPT_MISMATCH`."

        Claim: cpt_codes missing one of the encounter's POSTED CPTs
        returns ERR_CODING_CPT_MISMATCH.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter(
                charges=[
                    {"cpt_code": "99213", "unit_price_cents": 10_000},
                    {"cpt_code": "99214", "unit_price_cents": 12_000},
                ],
            )
        )
        # Submit only one of the two CPTs.
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9",
                cpt_codes=["99213"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_CODING_CPT_MISMATCH")

    def test_cpt_codes_superset_rejected(self, api):
        """PRD §3.6: "every CPT on the encounter must appear on the coding record with the correct multiplicity and vice versa. A mismatch produces `ERR_CODING_CPT_MISMATCH`."

        Claim: cpt_codes containing an extra CPT not on any
        non-VOIDED charge returns ERR_CODING_CPT_MISMATCH.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        cpts = [c["cpt_code"] for c in posted] + ["99888"]
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9", cpt_codes=cpts, finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_CODING_CPT_MISMATCH")

    def test_cpt_codes_match_in_arbitrary_order_accepted(self, api):
        """PRD §3.6: "the codes may be in any order, but every CPT on the encounter must appear on the coding record with the correct multiplicity and vice versa"

        Claim: cpt_codes in a permuted order, with the same multiset
        as the non-VOIDED charges, is accepted.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter(
                charges=[
                    {"cpt_code": "99213", "unit_price_cents": 10_000},
                    {"cpt_code": "99214", "unit_price_cents": 12_000},
                ],
            )
        )
        # Provide CPTs in reverse order vs how they were posted.
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9",
                cpt_codes=["99214", "99213"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_success(res, expected_status=201)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CODED"
