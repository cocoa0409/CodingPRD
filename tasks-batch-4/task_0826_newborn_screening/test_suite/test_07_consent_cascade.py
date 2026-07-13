"""Parental refusal cascade and specimen-create validation precedence (Newborn Screening PRD)."""
from test_helpers import (
    validate_error,
    get_success_data,
    create_case_via_cchd_fail,
    create_hospital_and_infant,
    create_specimen_payload,
    create_consent_payload,
    infant_version,
    make_birth_facility_user_headers,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]
COORD = TEST_USERS["follow_up_coordinator_headers"]


# ─── Difficulty: depth-4 refusal cascade ──────────────────────────────
def test_refusal_cascade_voids_specimen_cancels_screen_closes_case(api):
    """PRD §3.8: "When an `IN_TESTING` specimen is voided, its screen's `metabolic_status` is
    set to `CANCELLED`, which drives that screen's `overall_disposition` to `CANCELLED`; and
    any follow-up case for that screen still in `OPEN` or `REPEAT_REQUESTED` state is
    `CLOSED`, each such closure decrementing the infant's `open_case_count` by one and, if
    the count reaches zero, resetting `followup_status` to `CLEAR`."

    Design: Difficulty/transitive_cascade/consent_refusal_voids_specimen_cancels_screen_closes_case
    """
    facility, infant, specimen, screen, case = create_case_via_cchd_fail()
    hdr = make_birth_facility_user_headers(facility["id"])
    api.record_consent(infant["id"], create_consent_payload("REFUSAL"), hdr)

    reloaded_specimen = get_success_data(api.get_specimen(specimen["id"], LAB))
    reloaded_screen = get_success_data(api.get_screen(screen["id"], LAB))
    reloaded_case = get_success_data(api.get_follow_up_case(case["id"], COORD))
    assert reloaded_specimen["status"] == "VOIDED"
    assert reloaded_screen["metabolic_status"] == "CANCELLED"
    assert reloaded_case["status"] == "CLOSED"


def test_refusal_cascade_clears_infant_open_case_count(api):
    """PRD §3.8: "Recording a `REFUSAL` decision against an infant moves its `consent_status`
    to `REFUSED` and unwinds that infant's in-flight screening work in a single cascade."
    PRD §3.8: "each such closure decrementing the infant's `open_case_count` by one and, if
    the count reaches zero, resetting `followup_status` to `CLEAR`."

    Design: Difficulty/transitive_cascade/consent_refusal_voids_specimen_cancels_screen_closes_case
    """
    facility, infant, _specimen, _screen, _case = create_case_via_cchd_fail()
    hdr = make_birth_facility_user_headers(facility["id"])
    api.record_consent(infant["id"], create_consent_payload("REFUSAL"), hdr)

    reloaded = get_success_data(api.get_infant(infant["id"], LAB))
    assert reloaded["consent_status"] == "REFUSED"
    assert reloaded["open_case_count"] == 0


# ─── Difficulty: consent-safety precedence beats temporal chronology ──
def test_specimen_create_consent_refused_beats_collection_before_birth(api):
    """PRD §2.10: "**Consent safety** — an operation on an infant whose consent is refused is
    blocked with `ERR_CONSENT_REFUSED` (409)."
    PRD §2.10: "which precedes the consent-refused guard, which precedes the
    collection-before-birth chronology check, which precedes the stale-version check."

    Design: Difficulty/priority_pair_validation_conflict/specimen_create_safety_beats_temporal
    """
    facility, infant = create_hospital_and_infant()
    hdr = make_birth_facility_user_headers(facility["id"])
    api.record_consent(infant["id"], create_consent_payload("REFUSAL"), hdr)
    version = infant_version(infant["id"])
    # collection_datetime before birth (temporal, P10) AND consent refused (safety, P7).
    res = api.create_specimen(
        create_specimen_payload(
            infant["id"], version, collection_datetime="2026-02-26T00:00:00Z"
        ),
        hdr,
    )
    validate_error(res, "ERR_CONSENT_REFUSED", expected_status=409)


def test_specimen_create_collection_before_birth_when_consent_ok(api):
    """PRD §3.3: "The `collection_datetime` must be at or after the infant's `birth_datetime`;
    an earlier collection is rejected with `ERR_COLLECTION_BEFORE_BIRTH`."

    Design: Difficulty/priority_pair_validation_conflict/specimen_create_safety_beats_temporal
    """
    facility, infant = create_hospital_and_infant()  # consent PENDING, not refused
    hdr = make_birth_facility_user_headers(facility["id"])
    version = infant_version(infant["id"])
    res = api.create_specimen(
        create_specimen_payload(
            infant["id"], version, collection_datetime="2026-02-26T00:00:00Z"
        ),
        hdr,
    )
    validate_error(res, "ERR_COLLECTION_BEFORE_BIRTH", expected_status=422)
