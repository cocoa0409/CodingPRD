"""Breadth tests for telehealth referrals (consent gating, scheduling, silent
skip) and paginated listing envelopes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]


# ---------------------------------------------------------------------------
# Corner/endpoints/list_offerings_paginated_envelope
# ---------------------------------------------------------------------------
def test_list_offerings_paginated_envelope(api):
    """PRD 2.3: "The limit parameter caps the number of items returned; when omitted
    it defaults to 10, and a supplied value is constrained to a minimum of 1 and a
    maximum of 100."
    PRD 2.3: "Every list response includes the following four fields in the meta
    object of the envelope: limit, offset, total_count, and has_more."

    Two offerings, limit=1: total_count 2 and has_more true.

    Design: Corner/endpoints/list_offerings_paginated_envelope
    """
    fx.create_offering(api=api, test_code="PG1", display_name="Page One", list_price_cents=1000, specimen_type="BLOOD")
    fx.create_offering(api=api, test_code="PG2", display_name="Page Two", list_price_cents=2000, specimen_type="BLOOD")
    data, meta = validate_paginated(api.list_test_offerings(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Corner/endpoints/schedule_referral_open_to_scheduled
# ---------------------------------------------------------------------------
def test_schedule_referral_open_to_scheduled(api):
    """PRD 3.8: "A telehealth referral carries the lab_result_id that drives it,
    the patient_id carried from that result, and a referral_reason that mirrors the
    result's final_flag as either ABNORMAL or CRITICAL."
    PRD 3.8: "A referral begins OPEN and may be moved to SCHEDULED; its terminal
    state is CLOSED."

    Abnormal release (value 150, ref 70-100, consent true) mints an OPEN referral
    with reason ABNORMAL; schedule moves it to SCHEDULED.

    Design: Corner/endpoints/schedule_referral_open_to_scheduled
    """
    ctx = fx.setup_released_result(
        analyzer_value=150,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "RF", "display_name": "Referral Test", "list_price_cents": 4000, "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100},
        patient_overrides={"state_code": "CA", "consent_share_results": True},
        api=api,
    )
    patient, res = ctx["patient"], ctx["lab_result"]
    referrals, _meta = fx._list(api.list_telehealth_referrals(LAB2, params={"lab_result_id": res["id"]}))
    referral = referrals[0]
    assert referral["referral_reason"] == "ABNORMAL"
    scheduled = validate_success(api.schedule_telehealth_referral(referral["id"], make_patient_headers(patient["id"])))
    assert scheduled["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/endpoints/abnormal_release_no_consent_skips_referral_silently
# ---------------------------------------------------------------------------
def test_abnormal_release_no_consent_skips_referral_silently(api):
    """PRD 2.9: "the automatic referral that a result release would otherwise spawn
    is simply skipped — silently, with no error — when consent is absent."
    PRD 3.8: "and if the final_flag is ABNORMAL or CRITICAL and the patient's
    consent_share_results is true, a TelehealthReferral is minted OPEN (hop 3).
    When consent is absent, hop 3 is skipped silently with no error."

    Design: Corner/endpoints/abnormal_release_no_consent_skips_referral_silently
    """
    ctx = fx.setup_processed_result(
        analyzer_value=150,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "NC", "display_name": "No Consent", "list_price_cents": 4000, "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100},
        patient_overrides={"state_code": "CA", "consent_share_results": False},
        api=api,
    )
    res = ctx["lab_result"]
    released = validate_success(api.release_lab_result(res["id"], LAB2))
    assert released["status"] == "RELEASED"
    assert released["final_flag"] == "ABNORMAL"
    _data, meta = validate_paginated(api.list_telehealth_referrals(LAB2, params={"lab_result_id": res["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Corner/errors/manual_referral_no_consent_returns_403
# ---------------------------------------------------------------------------
def test_manual_referral_no_consent_returns_403(api):
    """PRD 2.9: "A manual referral creation against a patient who has not consented
    is rejected with ERR_CONSENT_REQUIRED".
    PRD 3.8: "a manual creation against a patient lacking consent is rejected with
    ERR_CONSENT_REQUIRED."

    Design: Corner/errors/manual_referral_no_consent_returns_403
    """
    ctx = fx.setup_released_result(
        analyzer_value=150,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "MC", "display_name": "Manual No Consent", "list_price_cents": 4000, "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100},
        patient_overrides={"state_code": "CA", "consent_share_results": False},
        api=api,
    )
    res = ctx["lab_result"]
    resp = api.create_telehealth_referral(F.create_telehealth_referral_payload(res["id"]), LAB2)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value)


# ---------------------------------------------------------------------------
# Corner/errors/specimen_reject_when_resulted_returns_409
# ---------------------------------------------------------------------------
def test_specimen_reject_when_resulted_returns_409(api):
    """PRD 3.8: "Rejection is permitted only when the order line is COLLECTED and
    its specimen is in COLLECTED or IN_ANALYSIS; otherwise it is rejected with
    ERR_SPECIMEN_NOT_REJECTABLE."

    A specimen already RESULTED cannot be rejected.

    Design: Corner/errors/specimen_reject_when_resulted_returns_409
    """
    ctx = fx.setup_released_result(
        analyzer_value=5,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "SR", "display_name": "Spec Reject", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    spec = ctx["specimen"]
    resp = api.reject_specimen(spec["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_REJECTABLE.value)
