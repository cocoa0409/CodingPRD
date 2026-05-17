"""Optimistic concurrency control + PRD-specified race outcomes.

PRD §2.5 OCC, §3.1 PCP-bind race, §3.4 prescription-dispense race,
§3.5 referral-accept race.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_referral,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    bind_patient_to_pcp,
    bind_pcp_payload,
    create_patient,
    create_pcp_provider,
    create_specialist_provider,
    create_both_role_provider,
    make_pharmacist_headers,
    make_provider_headers,
    occ_payload,
    patch_patient_payload,
    run_race,
    setup_patient_with_pcp,
    setup_referral_for_cycle,
    setup_signed_then_transmitted_prescription_for_dispense_invariant,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.5 OCC version conflict
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patch_patient_with_stale_version_rejected(self, api):
        """PRD §2.5: "Every PATCH endpoint and every action endpoint
        on a versioned resource accepts an optional version field in
        the request body. When supplied, the server compares it
        against the persisted version on the target resource: if the
        two do not match, the request is rejected with
        ERR_VERSION_CONFLICT."

        Claim: PATCH /patients/{id} with version one behind current
        returns ERR_VERSION_CONFLICT.
        """
        patient = create_patient(smoking_status="UNKNOWN")
        stale_version = patient["version"]
        # First mutation: bump version.
        ok_res = api.patch_patient(
            patient["id"],
            patch_patient_payload(smoking_status="NEVER"),
            TEST_USERS["nurse_headers"],
        )
        updated = validate_success(ok_res)
        assert updated["version"] > stale_version
        # Second mutation with stale version.
        bad_res = api.patch_patient(
            patient["id"],
            patch_patient_payload(
                smoking_status="FORMER", version=stale_version,
            ),
            TEST_USERS["nurse_headers"],
        )
        validate_error(bad_res, "ERR_VERSION_CONFLICT")

    def test_patch_patient_without_version_succeeds(self, api):
        """PRD §2.5: "When version is omitted, the server proceeds
        without an OCC check."

        Claim: PATCH /patients/{id} without version succeeds even
        when the version has previously advanced.
        """
        patient = create_patient(smoking_status="UNKNOWN")
        ok_res = api.patch_patient(
            patient["id"],
            patch_patient_payload(smoking_status="NEVER"),
            TEST_USERS["nurse_headers"],
        )
        validate_success(ok_res)
        # Second PATCH with no version supplied.
        ok2 = api.patch_patient(
            patient["id"],
            patch_patient_payload(smoking_status="CURRENT"),
            TEST_USERS["nurse_headers"],
        )
        result = validate_success(ok2)
        assert result["smoking_status"] == "CURRENT"


# ===========================================================================
# §3.1 PCP-bind race
# ===========================================================================
class TestPcpBindRace:

    def test_two_pcps_race_to_bind_same_patient(self, api):
        """PRD §3.1: "The patient must not already have a non-null
        pcp_provider_id. If they do, the request is rejected with
        ERR_PCP_ALREADY_BOUND. This is the serialization point for
        two providers attempting to claim the same patient
        simultaneously: at most one binding succeeds, and any later
        attempt — whether from a racing concurrent caller or from a
        fresh request after the binding was committed — sees
        ERR_PCP_ALREADY_BOUND."

        Claim: two concurrent bind-pcp calls on the same patient,
        each naming a different valid PCP, end with at most one
        success and at least one ERR_PCP_ALREADY_BOUND.
        """
        pcp_a = create_pcp_provider()
        pcp_b = create_pcp_provider()
        patient = create_patient()
        results = run_race(
            lambda: api.bind_pcp(
                patient["id"],
                bind_pcp_payload(provider_id=pcp_a["id"]),
                TEST_USERS["receptionist_headers"],
            ),
            lambda: api.bind_pcp(
                patient["id"],
                bind_pcp_payload(provider_id=pcp_b["id"]),
                TEST_USERS["receptionist_headers"],
            ),
        )
        outcomes = assert_exactly_one_succeeds(*results)
        # The single failure must be ERR_PCP_ALREADY_BOUND per
        # PRD's verbatim sentence above.
        failure = outcomes["failures"][0]
        body = failure.json() if hasattr(failure, "json") else {}
        assert body.get("data", {}).get("error_id") == \
            "ERR_PCP_ALREADY_BOUND", (
            "PRD §3.1 commits to ERR_PCP_ALREADY_BOUND on the "
            f"loser; got {body}"
        )


# ===========================================================================
# §3.4 Two pharmacists racing to dispense the same prescription
# ===========================================================================
class TestPharmacistDispenseRace:

    def test_two_pharmacists_racing_to_dispense_serialize_on_version(
        self, api,
    ):
        """PRD §3.4: "Two pharmacists racing to dispense the same
        prescription must serialize through the prescription's
        version: exactly one dispense commits and the other receives
        ERR_VERSION_CONFLICT."

        Claim: a race between two concurrent dispense calls (each
        supplying the SAME version=N) ends with exactly one success
        and the loser receiving ERR_VERSION_CONFLICT.
        """
        setup = setup_signed_then_transmitted_prescription_for_dispense_invariant()
        rx = setup["rx"]
        # Use the standard pharmacist constants — both distinct from
        # the signer (so SoD passes) but they share the rx version.
        v = rx["version"]
        results = run_race(
            lambda: api.dispense_prescription(
                rx["id"], TEST_USERS["pharmacist_headers"],
                occ_payload(version=v),
            ),
            lambda: api.dispense_prescription(
                rx["id"], TEST_USERS["pharmacist_headers_alt"],
                occ_payload(version=v),
            ),
        )
        outcomes = assert_exactly_one_succeeds(*results)
        failure = outcomes["failures"][0]
        body = failure.json() if hasattr(failure, "json") else {}
        # PRD §3.4 verbatim commits to ERR_VERSION_CONFLICT for the
        # loser.
        assert body.get("data", {}).get("error_id") == \
            "ERR_VERSION_CONFLICT", (
            "Loser must receive ERR_VERSION_CONFLICT per §3.4 race "
            f"contract; got {body}"
        )


# ===========================================================================
# §3.4 Sign / cancel race on a single prescription
# ===========================================================================
class TestSignCancelRace:

    def test_sign_and_cancel_serialize_one_wins(self, api):
        """PRD §3.4: "Two clients racing to sign and to cancel the
        same draft prescription serialize first-writer-wins on the
        prescription's status: exactly one operation commits and
        the other receives ERR_INVALID_PRESCRIPTION_STATE."

        Claim: a race between sign and cancel on a DRAFT
        prescription ends with exactly one success; the loser
        receives ERR_INVALID_PRESCRIPTION_STATE.
        """
        from test_helpers import (
            setup_checked_in_encounter, create_prescription,
            sign_prescription_payload,
        )
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            is_controlled=False, refills_authorized=0,
        )
        results = run_race(
            lambda: api.sign_prescription(
                rx["id"], make_provider_headers(provider["id"]),
                sign_prescription_payload(),
            ),
            lambda: api.cancel_prescription(
                rx["id"], make_provider_headers(provider["id"]),
            ),
        )
        outcomes = assert_exactly_one_succeeds(*results)
        failure = outcomes["failures"][0]
        body = failure.json() if hasattr(failure, "json") else {}
        assert body.get("data", {}).get("error_id") == \
            "ERR_INVALID_PRESCRIPTION_STATE", (
            "Loser must receive ERR_INVALID_PRESCRIPTION_STATE per "
            f"§3.4 race contract; got {body}"
        )


# ===========================================================================
# §3.5 Two specialists racing to accept the same referral
# ===========================================================================
class TestReferralAcceptRace:

    def test_two_specialists_racing_to_accept(self, api):
        """PRD §3.5: "Two specialists racing to accept the same
        PENDING referral serialize first-writer-wins: exactly one
        accept commits and the loser receives
        ERR_REFERRAL_NOT_PENDING."

        Claim: two concurrent accept calls on the same PENDING
        referral end with exactly one success and the loser
        receiving ERR_REFERRAL_NOT_PENDING.

        Note: PRD §3.5 also requires that the accepting Provider's
        identity equals referred_to_provider_id. We therefore mint
        the specialist's own Provider headers for both racing calls
        — modeling the realistic case where the SAME specialist
        receives two concurrent accept requests (e.g., from two
        browser tabs).
        """
        setup = setup_referral_for_cycle()
        referral = setup["referral"]
        specialist = setup["specialist"]
        headers = make_provider_headers(specialist["id"])
        results = run_race(
            lambda: api.accept_referral(referral["id"], headers),
            lambda: api.accept_referral(referral["id"], headers),
        )
        outcomes = assert_exactly_one_succeeds(*results)
        failure = outcomes["failures"][0]
        body = failure.json() if hasattr(failure, "json") else {}
        assert body.get("data", {}).get("error_id") == \
            "ERR_REFERRAL_NOT_PENDING", (
            "Loser must receive ERR_REFERRAL_NOT_PENDING per §3.5 "
            f"race contract; got {body}"
        )
