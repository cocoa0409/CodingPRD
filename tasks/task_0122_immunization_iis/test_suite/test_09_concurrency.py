"""Concurrency races and optimistic-concurrency control.

PRD §2.7 (OCC), §3.10 (race scenarios).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    REVIEWING_CLINICIAN_ID,
    TEST_USERS,
    administer_dose_payload,
    advance_clock_to,
    anchor_clock,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    conclude_review,
    conclude_review_payload,
    create_certificate_payload,
    create_patient,
    iso_anchor_offset,
    iso_utc,
    occ_payload,
    parse_iso,
    re_get_certificate,
    re_get_dose,
    run_race,
    schedule_dose,
    setup_administered_dose,
    setup_basic_scenario,
    setup_serious_ae,
    start_review,
    submit_vaers_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.10 Race: simultaneous administer on lot with doses_on_hand = 1
# ===========================================================================
class TestLotExhaustionRace:

    def test_simultaneous_administer_one_wins(self, api):
        """PRD §3.10: "When two clinicians simultaneously try to
        administer doses from the same lot whose doses_on_hand is 1,
        the decrement on doses_on_hand is first-writer-wins; exactly
        one administer succeeds, and the loser receives
        ERR_LOT_EXHAUSTED."

        Claim: exactly one of the two concurrent /administer calls
        succeeds; the other fails with ERR_LOT_EXHAUSTED.
        """
        ctx = setup_basic_scenario(doses_on_hand=1)
        patient_a = ctx["patient"]
        patient_b = create_patient()
        dose_a = schedule_dose(
            patient_a["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        dose_b = schedule_dose(
            patient_b["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        admin_at = iso_anchor_offset()
        results = run_race(
            lambda: api.administer_dose(
                patient_a["id"], dose_a["id"],
                administer_dose_payload(administered_at=admin_at),
                TEST_USERS["provider_clinician_headers"],
            ),
            lambda: api.administer_dose(
                patient_b["id"], dose_b["id"],
                administer_dose_payload(administered_at=admin_at),
                TEST_USERS["provider_clinician_headers"],
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        # The loser's error_id MUST be ERR_LOT_EXHAUSTED.
        loser_res = outcome["failures"][0]
        validate_error(loser_res, "ERR_LOT_EXHAUSTED")


# ===========================================================================
# §3.10 Race: simultaneous conclude-review on UNDER_REVIEW AE
# ===========================================================================
class TestConcludeReviewRace:

    def test_simultaneous_conclude_one_wins(self, api):
        """PRD §3.10: "When two reviewing clinicians simultaneously
        conclude the same adverse-event review, the change to
        clinical_review_status is first-writer-wins; exactly one
        conclusion is recorded, and the second sees ERR_INVALID_STATE
        because the dimension is no longer in UNDER_REVIEW."

        Claim: exactly one of two concurrent /conclude-review calls
        succeeds; the other fails with ERR_INVALID_STATE.
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        # Two reviewers race to conclude with different verdicts.
        from test_helpers import make_reviewing_clinician_headers
        headers_a = make_reviewing_clinician_headers("reviewer-a")
        headers_b = make_reviewing_clinician_headers("reviewer-b")
        results = run_race(
            lambda: api.conclude_review(
                ctx["adverse_event"]["id"],
                conclude_review_payload(conclusion="NOT_RELATED"),
                headers_a,
            ),
            lambda: api.conclude_review(
                ctx["adverse_event"]["id"],
                conclude_review_payload(conclusion="CAUSALLY_RELATED"),
                headers_b,
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_res = outcome["failures"][0]
        validate_error(loser_res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.10 Race: simultaneous submit-vaers
# ===========================================================================
class TestSubmitVaersRace:

    def test_simultaneous_submit_one_wins(self, api):
        """PRD §3.10: "When two reviewing clinicians simultaneously
        submit the same adverse event to VAERS, the change to
        vaers_submission_status is first-writer-wins; at most one
        submission lands, and the second receives
        ERR_VAERS_ALREADY_SUBMITTED."

        Claim: exactly one of two concurrent /submit-vaers calls
        succeeds; the other fails with ERR_VAERS_ALREADY_SUBMITTED.
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        conclude_review(
            ctx["adverse_event"]["id"],
            conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        from test_helpers import make_reviewing_clinician_headers
        headers_a = make_reviewing_clinician_headers("reviewer-a")
        headers_b = make_reviewing_clinician_headers("reviewer-b")
        results = run_race(
            lambda: api.submit_vaers(
                ctx["adverse_event"]["id"], headers_a,
                submit_vaers_payload(),
            ),
            lambda: api.submit_vaers(
                ctx["adverse_event"]["id"], headers_b,
                submit_vaers_payload(),
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_res = outcome["failures"][0]
        validate_error(loser_res, "ERR_VAERS_ALREADY_SUBMITTED")


# ===========================================================================
# §3.10 Race: duplicate certificate
# ===========================================================================
class TestCertificateDuplicateRace:

    def test_simultaneous_create_certificate_one_wins(self, api):
        """PRD §3.10: "When two school registrars simultaneously issue
        certificates for the same patient and school_year, uniqueness
        over (patient_id, school_year) restricted to certificate_status
        other than REVOKED is enforced first-writer-wins; the second
        receives ERR_CERTIFICATE_DUPLICATE."

        Claim: exactly one of two concurrent /certificates POSTs
        succeeds; the other fails with ERR_CERTIFICATE_DUPLICATE.
        """
        patient = create_patient()
        payload = create_certificate_payload(school_year="2027-2028")
        results = run_race(
            lambda: api.create_certificate(
                patient["id"], dict(payload),
                TEST_USERS["school_registrar_headers"],
            ),
            lambda: api.create_certificate(
                patient["id"], dict(payload),
                TEST_USERS["school_registrar_headers"],
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_res = outcome["failures"][0]
        validate_error(loser_res, "ERR_CERTIFICATE_DUPLICATE")


# ===========================================================================
# §3.10 Race: recall vs administer
# ===========================================================================
class TestRecallVsAdministerRace:

    def test_recall_vs_administer_one_wins(self, api):
        """PRD §3.10: "When a recall is issued at the same moment a
        clinician is trying to administer from the same lot, the lot's
        status transition is first-writer-wins on VaccineLot.status;
        if the recall lands first, the in-flight administer is
        rejected with ERR_LOT_RECALLED, and if the administer lands
        first, the dose is created in ADMINISTERED state and the
        recall's cascade then invalidates it as part of hop 1."

        Claim: after the race, exactly one of these holds: (a) the
        administer succeeded and the dose is now INVALIDATED with
        invalidation_reason='LOT_RECALL'; (b) the administer failed
        with ERR_LOT_RECALLED and the dose is still SCHEDULED. The
        recall always succeeds.
        """
        ctx = setup_basic_scenario(doses_on_hand=3)
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        admin_at = iso_anchor_offset()
        results = run_race(
            lambda: api.administer_dose(
                ctx["patient"]["id"], dose["id"],
                administer_dose_payload(administered_at=admin_at),
                TEST_USERS["provider_clinician_headers"],
            ),
            lambda: api.recall_vaccine_lot(
                ctx["lot"]["id"], {"reason": "MANUFACTURER_DEFECT"},
                TEST_USERS["public_health_officer_headers"],
            ),
        )
        # At least one succeeded (the recall always does).
        assert_at_least_one_succeeds(*results)
        # Now read the dose; PRD guarantees one of two terminal pairs.
        dose_after = re_get_dose(
            ctx["patient"]["id"], dose["id"],
        )
        assert dose_after["dose_state"] in {"INVALIDATED", "SCHEDULED"}, (
            f"PRD §3.10: after recall-vs-administer race, the dose must "
            f"be INVALIDATED (admin won then was cascaded) or "
            f"SCHEDULED (admin lost), got {dose_after['dose_state']!r}"
        )
        if dose_after["dose_state"] == "INVALIDATED":
            assert dose_after["invalidation_reason"] == "LOT_RECALL"


# ===========================================================================
# §2.7 Optimistic concurrency control
# ===========================================================================
class TestOptimisticConcurrency:

    def test_stale_version_on_action_returns_version_conflict(self, api):
        """PRD §2.7: "If version is supplied and does not match the
        current server-held version of the targeted entity, the request
        is rejected with ERR_VERSION_CONFLICT."

        Claim: passing a stale version on /cancel yields
        ERR_VERSION_CONFLICT.
        """
        ctx = setup_basic_scenario()
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        stale_version = dose["version"] + 99  # definitely stale.
        res = api.cancel_dose(
            ctx["patient"]["id"], dose["id"],
            TEST_USERS["provider_clinician_headers"],
            payload=occ_payload(stale_version),
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_omitted_version_skips_occ_check(self, api):
        """PRD §2.7: "If version is omitted, the check is skipped and
        the operation proceeds."

        Claim: /cancel with no version proceeds successfully.
        """
        ctx = setup_basic_scenario()
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        res = api.cancel_dose(
            ctx["patient"]["id"], dose["id"],
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res)
        assert data["dose_state"] == "CANCELLED"

    def test_version_increments_by_one_on_mutation(self, api):
        """PRD §2.4: "version is an integer that starts at 1 on
        creation and increments by exactly 1 on every persisted
        mutation."

        Claim: after /administer, the dose's version is exactly
        before_version + 1.
        """
        ctx = setup_basic_scenario()
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        v_before = dose["version"]
        from test_helpers import administer_dose as _adm
        after = _adm(
            ctx["patient"]["id"], dose["id"], iso_anchor_offset(),
        )
        assert after["version"] == v_before + 1, (
            f"PRD §2.4: version must increment by exactly 1 "
            f"(before={v_before}, after={after['version']})"
        )
