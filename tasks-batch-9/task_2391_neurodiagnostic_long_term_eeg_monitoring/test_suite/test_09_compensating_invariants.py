"""
Compensations that must restore the prior figure exactly.

Two ledgers in this contract are allowed to move only in balanced pairs: the
unit's storage account, which a package build charges and a revocation credits
back, and the authorization's day ledger, whose four buckets must still add up
after a reservation, an extension grant and the settlement at discharge. Each
test below performs the forward move and then the compensation, and pins the
restored figures rather than merely checking that they changed.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_capture_value,
    assert_ids_equal,
    assert_instant_equals,
    assert_ledger,
    assert_storage_value,
    assert_unit_storage,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import COORDINATOR, EPILEPTOLOGIST, TECHNOLOGIST

REVOCATION_REASON = "WRONG_RECIPIENT_CENTER"

# The extension is judged two days into a five-day authorization.
EXTENSION_AT = "2026-08-04T00:00:00Z"
DISCHARGE_AT = "2026-08-05T00:00:00Z"
FIRST_ONSET_AT = "2026-08-02T06:00:00Z"
SECOND_ONSET_AT = "2026-08-02T12:00:00Z"


def _stay_with_built_package(api):
    """A completed 25-channel inpatient study whose package is built but undelivered.

    The single segment runs 2026-08-02T00:00Z to 2026-08-04T12:00Z, that is 3600
    whole minutes at 0.0004 * 25 * 2.5 = 0.025 GB per channel-minute, so the
    study stores 90.00 GB; the video-stripped package therefore allocates
    90.00 / 2.5 = 36.00 GB on top of it.
    """
    stay = fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=5,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        max_concurrent_studies=2,
        channel_count=25,
    )
    fx.start_study(api, stay.study_id, stay.shift_id)
    fx.complete_study(api, stay.study_id, at=c.T_COMPLETE)
    fx.finalized_report(api, stay.study_id)
    package = fx.built_export(api, stay.study_id, include_video=False)
    return stay, package


def _stay_ready_for_extension(api):
    """A two-day inpatient stay carrying two banked clinical events and a taper step.

    One 1440-minute segment closes at 2026-08-03T00:00Z, then two CLINICAL_SEIZURE
    markings inside it are adjudicated at a taper depth of 1, so each keeps its
    undiscounted weight of 1.000 and the admission banks 2.000 weighted events
    against a target of 4.
    """
    stay = fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        max_concurrent_studies=2,
        channel_count=32,
    )
    plan = fx.create_taper_plan(api, stay.admission_id, total_steps=3, steps_advanced=1)
    fx.acquire_segment(
        api,
        stay.study_id,
        from_iso=c.T_ADMIT,
        to_iso=c.T_ADMIT_PLUS_1D,
        shift_id=stay.shift_id,
    )
    for onset in (FIRST_ONSET_AT, SECOND_ONSET_AT):
        fx.create_marking(
            api,
            stay.study_id,
            onset,
            event_class=c.EVENT_CLINICAL_SEIZURE,
            duration_seconds=90,
            adjudicate=True,
        )
    return stay, plan


def _grant_extension(api, admission_id):
    """Record one length-of-stay decision against a freshly observed version."""
    admission = validate_success(api.get_admission(admission_id, EPILEPTOLOGIST))
    return validate_success(
        api.record_extension_decision(
            admission_id, f.extension_payload(admission["version"]), EPILEPTOLOGIST
        )
    )


def _bed_by_id(api, unit_id, bed_id):
    """Read one bed back through the unit's bed listing."""
    beds, _meta = validate_paginated(api.list_unit_beds(unit_id, COORDINATOR))
    matches = [bed for bed in beds if bed["id"] == bed_id]
    assert matches, f"bed {bed_id} is missing from the listing for unit {unit_id}"
    return matches[0]


def _taper_plan_state(plan):
    """The declared lifecycle value of a taper plan, whichever field carries it.

    The contract names the taper states themselves (`ACTIVE`, `HELD`,
    `COMPLETED`, `ABORTED`) but not the field they are written to, so the value
    is located rather than the field name pinned.
    """
    for name in ("status", "state"):
        if plan.get(name) is not None:
            return plan[name]
    raise AssertionError(f"taper plan exposes no lifecycle value: {plan!r}")


# ---------------------------------------------------------------------------
# Revoking a package restores the unit's storage account exactly
# ---------------------------------------------------------------------------


def test_revoking_a_built_package_restores_the_pre_build_storage_figure(api):
    """The credit back is the same volume the build charged, to the cent.

    PRD §2.9: "A compensation restores the prior value precisely rather than approximately: revoking an export package subtracts back the same `package_gb` it added."
    PRD §3.9: "It stores the supplied `revocation_reason`, subtracts `package_gb` from the unit's `storage_used_gb` — restoring the pre-build figure exactly, not approximately — re-derives `storage_pressure_pct` and `posture`, and where the posture leaves `STORAGE_LOCKED` returns packages blocked by the storage lock to `QUEUED`."

    Design: Difficulty/compensating_invariant/export_revoke_restores_unit_storage_exactly
    """
    stay, package = _stay_with_built_package(api)

    charged = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # 90.00 GB of study volume plus the 36.00 GB the build allocated, over a 500.00 GB quota.
    assert_unit_storage(
        charged,
        storage_used_gb=126.00,
        storage_pressure_pct=25.20,
        posture=c.POSTURE_OPEN,
    )

    validate_success(
        api.revoke_export(package["id"], f.revoke_payload(REVOCATION_REASON), COORDINATOR)
    )

    credited = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # Back to the study volume alone: 90.00 of 500.00 GB is 18.00 percent.
    assert_unit_storage(
        credited,
        storage_used_gb=90.00,
        storage_pressure_pct=18.00,
        posture=c.POSTURE_OPEN,
    )


def test_revoked_package_retains_the_volume_it_once_allocated(api):
    """The compensation releases the storage but keeps the historical figure.

    PRD §3.9: "`package_gb` itself is retained on the revoked package as the historical record of what was once allocated."
    PRD §3.9: "Revocation is the compensating action and is permitted from `BUILT` and from `DELIVERED` alike; anything else is `ERR_INVALID_EXPORT_STATE`."

    Design: Difficulty/compensating_invariant/export_revoke_restores_unit_storage_exactly
    """
    stay, package = _stay_with_built_package(api)
    assert_storage_value(package["package_gb"], 36.00, "package_gb at build")

    revoked = validate_success(
        api.revoke_export(package["id"], f.revoke_payload(REVOCATION_REASON), COORDINATOR)
    )
    assert revoked["status"] == c.EXPORT_REVOKED, (
        f"the package should read REVOKED, got {revoked['status']!r}"
    )
    assert revoked["revocation_reason"] == REVOCATION_REASON, (
        f"revocation_reason should be {REVOCATION_REASON!r}, got {revoked['revocation_reason']!r}"
    )
    assert_storage_value(revoked["package_gb"], 36.00, "package_gb after revocation")

    # Releasing the package volume leaves the recording itself untouched.
    study = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert_storage_value(study["stored_gb"], 90.00, "study stored_gb")
    assert study["data_state"] == c.DATA_ONLINE, (
        f"the study data should still be ONLINE, got {study['data_state']!r}"
    )


# ---------------------------------------------------------------------------
# The day ledger stays conserved through reservation, grant and settlement
# ---------------------------------------------------------------------------


def test_day_ledger_stays_conserved_from_reservation_through_settlement(api):
    """Reserve, grant and settle each move days between buckets without creating any.

    PRD §3.2: "The four ledger figures obey a conserved equality that must hold after **every** mutation, without exception: `authorized_days` equals `days_consumed` plus `days_reserved` plus `days_available`."
    PRD §3.2: "Discharge settles: the days actually spent are the lesser of `days_reserved` and the elapsed monitored days rounded up to the next whole day; that spent figure is added to `days_consumed`, the remainder of `days_reserved` beyond the spent figure returns to `days_available`, and `days_reserved` is then set to 0."

    Design: Difficulty/compensating_invariant/discharge_settles_authorization_day_ledger
    """
    stay, _plan = _stay_ready_for_extension(api)

    reserved = validate_success(api.get_authorization(stay.authorization_id, COORDINATOR))
    # Admission reserved the two planned days out of five authorized.
    assert_ledger(
        reserved,
        authorized_days=5,
        days_consumed=0,
        days_reserved=2,
        days_available=3,
    )

    fx.set_clock(api, EXTENSION_AT)
    decision = _grant_extension(api, stay.admission_id)
    # A deficit of 2.000 weighted events at a yield of 1.000 per day implies 2 days;
    # a daily risk of 3 + 1.5 permits 24 / 4.5 = 5 days; 3 days remain available.
    assert decision["last_extension_outcome"] == c.EXTENSION_GRANTED, (
        f"the decision should be a grant, got {decision['last_extension_outcome']!r}"
    )
    assert decision["last_extension_granted_days"] == 2, (
        f"the smallest of 2, 5 and 3 days should be granted, got {decision['last_extension_granted_days']!r}"
    )
    assert_instant_equals(
        decision["planned_discharge_at"], "2026-08-06T00:00:00Z", "planned_discharge_at"
    )

    granted = validate_success(api.get_authorization(stay.authorization_id, COORDINATOR))
    assert_ledger(
        granted,
        authorized_days=5,
        days_consumed=0,
        days_reserved=4,
        days_available=1,
    )

    fx.complete_study(api, stay.study_id, at=DISCHARGE_AT)
    fx.discharge(
        api,
        stay.admission_id,
        disposition=c.DISPOSITION_SURGICAL_EVALUATION,
        at=DISCHARGE_AT,
    )

    settled = validate_success(api.get_authorization(stay.authorization_id, COORDINATOR))
    # Three elapsed days is the lesser of 4 reserved and 3.000 rounded up, so one
    # reserved day returns to the available bucket.
    assert_ledger(
        settled,
        authorized_days=5,
        days_consumed=3,
        days_reserved=0,
        days_available=2,
    )


def test_discharge_freezes_elapsed_days_closes_funding_and_releases_the_bed(api):
    """The settlement is one atomic close across admission, taper, bed and funding.

    PRD §3.3: "On success it stamps `discharged_at` from the clock and freezes `elapsed_monitored_days` at that instant, so the figure stops moving thereafter."
    PRD §3.3: "It moves `authorization_state` to `AUTH_CLOSED`, whether that dimension was standing at `AUTH_ACTIVE` or had already fallen to `AUTH_EXHAUSTED`."
    PRD §3.3: "Every taper plan of the admission still in `ACTIVE` or `HELD` is driven to `ABORTED`."

    Design: Difficulty/compensating_invariant/discharge_settles_authorization_day_ledger
    """
    stay, plan = _stay_ready_for_extension(api)

    banked = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    # Two undiscounted clinical events against a target of four.
    assert_capture_value(banked["weighted_event_count"], 2.000, "weighted_event_count")
    assert_capture_value(banked["capture_adequacy_index"], 0.500, "capture_adequacy_index")

    fx.set_clock(api, EXTENSION_AT)
    _grant_extension(api, stay.admission_id)
    fx.complete_study(api, stay.study_id, at=DISCHARGE_AT)
    discharged = fx.discharge(
        api,
        stay.admission_id,
        disposition=c.DISPOSITION_SURGICAL_EVALUATION,
        at=DISCHARGE_AT,
    )

    assert_admission_dimensions(
        discharged, c.CLINICAL_DISCHARGED, c.AUTH_STATE_CLOSED
    )
    assert_instant_equals(discharged["discharged_at"], DISCHARGE_AT, "discharged_at")
    # Frozen at exactly three days from 2026-08-02T00:00Z.
    assert_capture_value(
        discharged["elapsed_monitored_days"], 3.000, "elapsed_monitored_days"
    )
    assert discharged["disposition"] == c.DISPOSITION_SURGICAL_EVALUATION, (
        f"the supplied disposition should be stored, got {discharged['disposition']!r}"
    )
    assert discharged["bed_id"] is None, (
        f"a discharged admission holds no bed, got {discharged['bed_id']!r}"
    )

    aborted = validate_success(api.get_taper_plan(plan["id"], EPILEPTOLOGIST))
    assert _taper_plan_state(aborted) == c.TAPER_ABORTED, (
        f"an unfinished plan is driven to ABORTED by discharge, got {_taper_plan_state(aborted)!r}"
    )

    bed = _bed_by_id(api, stay.unit_id, stay.bed_id)
    assert bed["status"] == c.BED_TURNOVER, (
        f"the released bed should read TURNOVER, got {bed['status']!r}"
    )
    assert bed["current_admission_id"] is None, (
        f"the released bed should hold no admission, got {bed['current_admission_id']!r}"
    )
    assert_instant_equals(bed["released_at"], DISCHARGE_AT, "released_at")
    # 90 minutes after the release instant.
    assert_instant_equals(
        bed["turnover_clear_at"], "2026-08-05T01:30:00Z", "turnover_clear_at"
    )
    assert_ids_equal(discharged["id"], stay.admission_id, "admission id")
