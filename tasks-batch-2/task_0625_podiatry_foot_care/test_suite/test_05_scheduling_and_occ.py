"""Provider double-booking (half-open), modality buffered overlap, optimistic
concurrency on PA and modality versions, and imaging lifecycle lockdown.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    assert_encounter, assert_imaging_order,
    ApiErrorId, TEST_USERS, make_podiatrist_headers,
    setup_practice_provider_patient, create_encounter, create_modality,
    create_approved_pa, set_clock, dispense_dme,
    setup_modality_with_scheduled_study,
)
from test_helpers import (
    create_encounter_payload, create_imaging_order_payload, create_dme_dispense_payload,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONTDESK = TEST_USERS["front_desk_headers"]


def _practice_provider_two_patients(clock="2026-06-02T08:00:00Z"):
    set_clock(clock)
    practice, provider, patient1 = setup_practice_provider_patient(
        patient_overrides={"full_name": "Pat A"})
    patient2 = get_success_data(api_client.create_patient(
        {"practice_id": practice["id"], "full_name": "Pat B",
         "date_of_birth": "1966-04-16"}, FRONTDESK))
    return practice, provider, patient1, patient2


# ─── resource_temporal_overlap / provider_half_open_overlap_rejected_back_to_back_allowed ─
class TestProviderHalfOpenScheduling:
    """Genuine overlap is rejected; a boundary-touch back-to-back is allowed."""

    def test_overlapping_encounter_rejected(self, api):
        """PRD §3.3: "the new interval, treated as half-open from start up to but
        not including end, must not overlap any non-`VOIDED` encounter already on
        the same `provider_id`; two appointments that merely touch at the
        boundary are allowed, but a genuine overlap is rejected with
        `ERR_PROVIDER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_rejected_back_to_back_allowed
        """
        practice, provider, pat1, pat2 = _practice_provider_two_patients()
        create_encounter(pat1["id"], provider["id"],
                         scheduled_start="2026-06-02T10:00:00Z",
                         scheduled_end="2026-06-02T10:30:00Z")
        res = api.create_encounter(
            create_encounter_payload(pat2["id"], provider["id"],
                                     scheduled_start="2026-06-02T10:15:00Z",
                                     scheduled_end="2026-06-02T10:45:00Z"),
            FRONTDESK)
        validate_error(res, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED.value)

    def test_back_to_back_boundary_touch_allowed(self, api):
        """PRD §3.3: "two appointments that merely touch at the boundary are
        allowed, but a genuine overlap is rejected with
        `ERR_PROVIDER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_rejected_back_to_back_allowed
        """
        practice, provider, pat1, pat2 = _practice_provider_two_patients()
        create_encounter(pat1["id"], provider["id"],
                         scheduled_start="2026-06-02T10:00:00Z",
                         scheduled_end="2026-06-02T10:30:00Z")
        res = api.create_encounter(
            create_encounter_payload(pat2["id"], provider["id"],
                                     scheduled_start="2026-06-02T10:30:00Z",
                                     scheduled_end="2026-06-02T11:00:00Z"),
            FRONTDESK)
        enc2 = validate_success(res, 201)
        assert enc2["status"] == "OPEN"


# ─── resource_temporal_overlap / modality_buffered_overlap_rejected_within_cleanup ─
class TestModalityBufferedScheduling:
    """A 15-min cleanup buffer extends each study's footprint; a study starting
    within the buffer window of an existing study is rejected."""

    def test_buffered_overlap_within_cleanup_rejected(self, api):
        """PRD §3.9: "the new study's interval, expanded by the modality's
        `cleanup_buffer_minutes` added after its end, must not overlap the
        buffered interval of any non-`CANCELLED` study already on the same
        `modality_id`."
        PRD §3.9: "an overlap of the buffered intervals is rejected with
        `ERR_MODALITY_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/modality_buffered_overlap_rejected_within_cleanup
        """
        # Existing study [10:00,10:30) blocks up to 10:45; new [10:40,11:00) collides.
        (practice, provider, patient, modality, enc, img,
         mod_version) = setup_modality_with_scheduled_study(
            study_start="2026-06-02T10:00:00Z", study_end="2026-06-02T10:30:00Z",
            cleanup_buffer_minutes=15)
        enc2 = create_encounter(patient["id"], provider["id"],
                                scheduled_start="2026-06-02T11:30:00Z",
                                scheduled_end="2026-06-02T11:55:00Z")
        res = api.create_imaging_order(
            create_imaging_order_payload(enc2["id"], modality["id"], mod_version,
                                         study_start="2026-06-02T10:40:00Z",
                                         study_end="2026-06-02T11:00:00Z"),
            make_podiatrist_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_MODALITY_DOUBLE_BOOKED.value)

    def test_study_after_cleanup_buffer_allowed(self, api):
        """PRD §3.9: "Because the buffer extends each study's footprint, two
        studies that would otherwise abut must be separated by at least the
        cleanup buffer"

        Design: Difficulty/resource_temporal_overlap/modality_buffered_overlap_rejected_within_cleanup
        """
        # Existing [10:00,10:30) blocks up to 10:45; new [10:45,11:00) starts at the buffer edge.
        (practice, provider, patient, modality, enc, img,
         mod_version) = setup_modality_with_scheduled_study(
            study_start="2026-06-02T10:00:00Z", study_end="2026-06-02T10:30:00Z",
            cleanup_buffer_minutes=15)
        enc2 = create_encounter(patient["id"], provider["id"],
                                scheduled_start="2026-06-02T11:30:00Z",
                                scheduled_end="2026-06-02T11:55:00Z")
        res = api.create_imaging_order(
            create_imaging_order_payload(enc2["id"], modality["id"], mod_version,
                                         study_start="2026-06-02T10:45:00Z",
                                         study_end="2026-06-02T11:00:00Z"),
            make_podiatrist_headers(provider["id"]))
        img2 = validate_success(res, 201)
        assert img2["status"] == "SCHEDULED"


# ─── validations / provider_double_booked_overlap_full_containment ─────────
def test_provider_double_booked_full_containment(api):
    """PRD §3.3: "the new interval, treated as half-open from start up to but not
    including end, must not overlap any non-`VOIDED` encounter already on the
    same `provider_id`"

    Design: Corner/validations/provider_double_booked_overlap_full_containment
    """
    practice, provider, pat1, pat2 = _practice_provider_two_patients(
        clock="2026-06-03T08:00:00Z")
    create_encounter(pat1["id"], provider["id"],
                     scheduled_start="2026-06-03T10:00:00Z",
                     scheduled_end="2026-06-03T10:30:00Z")
    res = api.create_encounter(
        create_encounter_payload(pat2["id"], provider["id"],
                                 scheduled_start="2026-06-03T10:05:00Z",
                                 scheduled_end="2026-06-03T10:25:00Z"),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED.value)


# ─── validations / provider_back_to_back_boundary_touch_allowed ────────────
def test_provider_back_to_back_boundary_touch_accepted(api):
    """PRD §3.3: "two appointments that merely touch at the boundary are
    allowed"

    Design: Corner/validations/provider_back_to_back_boundary_touch_allowed
    """
    practice, provider, pat1, pat2 = _practice_provider_two_patients(
        clock="2026-06-03T08:00:00Z")
    create_encounter(pat1["id"], provider["id"],
                     scheduled_start="2026-06-03T10:00:00Z",
                     scheduled_end="2026-06-03T10:30:00Z")
    res = api.create_encounter(
        create_encounter_payload(pat2["id"], provider["id"],
                                 scheduled_start="2026-06-03T10:30:00Z",
                                 scheduled_end="2026-06-03T11:00:00Z"),
        FRONTDESK)
    enc2 = validate_success(res, 201)
    assert enc2["status"] == "OPEN"


# ─── cross_cutting / occ_dme_dispense_stale_pa_rejected ────────────────────
def test_dme_dispense_with_stale_pa_version_rejected(api):
    """PRD §2.10: "If that value does not match the authorization's current
    `version` — because an earlier dispense or a compensating return has since
    drawn down or restored `remaining_units` and bumped the authorization's
    `version` — the dispense is rejected with `ERR_PA_VERSION_STALE` (HTTP 412)."

    Design: Corner/cross_cutting/occ_dme_dispense_stale_pa_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    pa = create_approved_pa(patient["id"], service_category="DME", hcpcs_code="L4360",
                            authorized_units=3)
    enc = create_encounter(patient["id"], provider["id"])
    stale_version = pa["version"]
    # First dispense succeeds and bumps PA.version.
    dispense_dme(pa["id"], enc["id"], stale_version,
                 hcpcs_code="L4360", acquisition_mode="PURCHASE", units=1,
                 purchase_price_cents=15000)
    # Second dispense still carries the pre-dispense (stale) version.
    res = api.create_dme_dispense(
        create_dme_dispense_payload(pa["id"], enc["id"], stale_version,
                                    hcpcs_code="L4360", acquisition_mode="PURCHASE",
                                    units=1, purchase_price_cents=15000),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_PA_VERSION_STALE.value)


# ─── cross_cutting / occ_imaging_order_stale_modality_rejected ─────────────
def test_imaging_order_with_stale_modality_version_rejected(api):
    """PRD §2.10: "If it does not match the modality's current `version` —
    because an earlier booking has since occupied an interval and bumped the
    modality's `version` — the order is rejected with
    `ERR_MODALITY_VERSION_STALE` (HTTP 412)"

    Design: Corner/cross_cutting/occ_imaging_order_stale_modality_rejected
    """
    set_clock("2026-06-04T08:00:00Z")
    practice, provider, pat1, pat2 = _practice_provider_two_patients(
        clock="2026-06-04T08:00:00Z")
    modality = create_modality(practice["id"], name="X-Ray 2", modality_type="XRAY",
                               cleanup_buffer_minutes=15)
    stale_version = modality["version"]
    enc1 = create_encounter(pat1["id"], provider["id"],
                            scheduled_start="2026-06-04T09:00:00Z",
                            scheduled_end="2026-06-04T09:30:00Z")
    enc2 = create_encounter(pat2["id"], provider["id"],
                            scheduled_start="2026-06-04T13:00:00Z",
                            scheduled_end="2026-06-04T13:30:00Z")
    # First booking (non-overlapping window) succeeds and bumps Modality.version.
    get_success_data(api.create_imaging_order(
        create_imaging_order_payload(enc1["id"], modality["id"], stale_version,
                                     study_start="2026-06-04T10:00:00Z",
                                     study_end="2026-06-04T10:30:00Z"),
        make_podiatrist_headers(provider["id"])))
    # Second booking (different, non-overlapping window) carries the stale version.
    res = api.create_imaging_order(
        create_imaging_order_payload(enc2["id"], modality["id"], stale_version,
                                     study_start="2026-06-04T14:00:00Z",
                                     study_end="2026-06-04T14:30:00Z"),
        make_podiatrist_headers(provider["id"]))
    validate_error(res, ApiErrorId.ERR_MODALITY_VERSION_STALE.value)


# ─── state_machines / imaging_complete_terminal_then_cancel_rejected ───────
def test_cancel_completed_imaging_order_rejected(api):
    """PRD §3.9: "Completing or cancelling a study not in `SCHEDULED` is rejected
    with `ERR_IMAGING_BAD_STATE`."

    Design: Corner/state_machines/imaging_complete_terminal_then_cancel_rejected
    """
    (practice, provider, patient, modality, enc, img,
     mod_version) = setup_modality_with_scheduled_study(
        study_start="2026-06-02T10:00:00Z", study_end="2026-06-02T10:30:00Z",
        cleanup_buffer_minutes=10, clock_iso="2026-06-02T08:00:00Z")
    get_success_data(api.complete_imaging_order(img["id"], make_podiatrist_headers(provider["id"])))
    res = api.cancel_imaging_order(img["id"], FRONTDESK)
    validate_error(res, ApiErrorId.ERR_IMAGING_BAD_STATE.value)
