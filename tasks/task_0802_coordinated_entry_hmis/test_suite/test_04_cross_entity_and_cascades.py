"""Cross-entity and cascade depth tests: check-in gated on ACTIVE consent, the depth-3
merge→cancel→free→promote cascade, and the bed-night length-of-stay variant on exit.

Every test translates exactly one instance from the difficulty design index (queue A).
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, new_client, new_active_client, new_active_consent,
    new_shelter_with_beds, new_reservation, new_waitlist_entry, new_exit_record,
    setup_reserved_client, setup_completed_shelter_stay,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
SHELTER = TEST_USERS["shelter_manager_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


# ─── cross_entity_state_dependency / xdep_checkin_requires_active_consent ──────
def test_checkin_without_active_consent_rejected(api):
    """PRD §3.4: "Checking a client in advances a `RESERVED` reservation to `CHECKED_IN`, but
    only if the reserving client holds an `ACTIVE` `ROIConsent`; without it the check-in is
    rejected with `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/xdep_checkin_requires_active_consent
    """
    ctx = setup_reserved_client(active_consent=False, shelter_name="Birch ES")
    res = api.check_in_reservation(ctx["reservation"]["id"], SHELTER)
    validate_error(res, "ERR_CONSENT_REQUIRED", expected_status=409)


def test_checkin_rejected_reservation_stays_reserved(api):
    """PRD §3.4: "On check-in the assigned bed's `current_reservation_id` is set to this
    reservation, marking the bed occupied."

    Design: Difficulty/cross_entity_state_dependency/xdep_checkin_requires_active_consent
    """
    ctx = setup_reserved_client(active_consent=False, shelter_name="Birch ES")
    api.check_in_reservation(ctx["reservation"]["id"], SHELTER)

    after = validate_success(api.get_bed_reservation(ctx["reservation"]["id"], SHELTER), 200)
    assert after["status"] == "RESERVED", "a consent-blocked check-in must leave the reservation RESERVED"


# ─── transitive_cascade / casc_merge_cancel_free_promote_depth3 ────────────────
def _merge_cascade_setup(api):
    set_clock("2026-03-07T00:00:00Z")
    master = new_client(full_name="Master M", dob="1970-01-01")
    dup, _ = new_active_client(self_report_points=6, full_name="Dupe D", dob="1970-01-01",
                              ssn_last4="1234")
    new_active_consent(dup["id"])
    cc = new_client(full_name="Cee C", dob="1993-09-09")
    shelter, _ = new_shelter_with_beds(("B1",), name="Pine ES")
    reservation = new_reservation(dup["id"], shelter["id"], "2026-03-05", "2026-03-20")
    validate_success(api.check_in_reservation(reservation["id"], SHELTER), 200)
    wlc = new_waitlist_entry(shelter["id"], cc["id"], "2026-03-06", "2026-03-19")
    return master, dup, reservation, wlc


def test_merge_cancels_duplicate_checked_in_reservation(api):
    """PRD §3.7: "When the duplicate was `ACTIVE`, the merge additionally cascades to unwind
    the duplicate's live commitments: any `RESERVED` or `CHECKED_IN` reservation held by the
    duplicate is cancelled — which in turn frees the bed and triggers waitlist promotion
    following the pinned capacity order — and the duplicate's `ACTIVE` `PrioritizationEntry`,
    if any, is driven to `REMOVED`."
    PRD §3.7: "On a successful merge the duplicate moves to the terminal `MERGED` state and
    its `master_client_id` is set to the master's `id`."

    Design: Difficulty/transitive_cascade/casc_merge_cancel_free_promote_depth3
    """
    master, dup, reservation, _ = _merge_cascade_setup(api)
    validate_success(api.merge_client(master["id"], {"duplicate_client_id": dup["id"]}, ADMIN), 200)

    dup_after = validate_success(api.get_client(dup["id"], ADMIN), 200)
    assert dup_after["status"] == "MERGED"
    assert dup_after["master_client_id"] == master["id"]

    res_after = validate_success(api.get_bed_reservation(reservation["id"], SHELTER), 200)
    assert res_after["status"] == "CANCELLED"


def test_merge_cascade_promotes_top_waitlist_entry(api):
    """PRD §3.5: "The chosen entry moves `WAITING → PROMOTED`, and a fresh `RESERVED`
    reservation is minted for it with a server-assigned bed; the entry's
    `promoted_reservation_id` records that new reservation's `id`."

    Design: Difficulty/transitive_cascade/casc_merge_cancel_free_promote_depth3
    """
    master, dup, _, wlc = _merge_cascade_setup(api)
    validate_success(api.merge_client(master["id"], {"duplicate_client_id": dup["id"]}, ADMIN), 200)

    wl_after = validate_success(api.get_waitlist_entry(wlc["id"], SHELTER), 200)
    assert wl_after["status"] == "PROMOTED"
    assert wl_after["promoted_reservation_id"] is not None


# ─── dual_variant_calc / dv_apr_bed_night_vs_duration_los ──────────────────────
def test_shelter_exit_bed_nights_excludes_exit_day(api):
    """PRD §3.8: "For a shelter exit, `bed_nights` is the number of nights between the
    reservation's `entry_date` and its `exit_date` counting the entry day but excluding the
    exit day (the half-open bed-night count used for HUD point-in-time counting)."
    PRD §3.8: "A parallel enrollment-duration measure, which includes both endpoints and
    therefore equals the bed-night count plus one, exists for case-management duration
    reporting but is not what `bed_nights` stores."

    Design: Difficulty/dual_variant_calc/dv_apr_bed_night_vs_duration_los
    """
    ctx = setup_completed_shelter_stay(
        entry_date="2026-03-05", start_iso="2026-03-05T00:00:00Z",
        checkout_iso="2026-03-10T00:00:00Z", expected_exit_date="2026-03-20",
        shelter_name="Elm ES")
    exit_rec = new_exit_record(ctx["client"]["id"], "PERMANENT_HOUSING",
                               reservation_id=ctx["reservation"]["id"])
    assert exit_rec["bed_nights"] == 5, "03-05..03-10 half-open bed-nights == 5"


def test_shelter_exit_to_permanent_housing_is_positive(api):
    """PRD §3.8: "An exit to `PERMANENT_HOUSING` or `RRH` is `POSITIVE`."

    Design: Difficulty/dual_variant_calc/dv_apr_bed_night_vs_duration_los
    """
    ctx = setup_completed_shelter_stay(
        entry_date="2026-03-05", start_iso="2026-03-05T00:00:00Z",
        checkout_iso="2026-03-10T00:00:00Z", expected_exit_date="2026-03-20",
        shelter_name="Elm ES")
    exit_rec = new_exit_record(ctx["client"]["id"], "PERMANENT_HOUSING",
                               reservation_id=ctx["reservation"]["id"])
    assert exit_rec["outcome"] == "POSITIVE"
