"""Certificate issuance, voiding, the reinspect cascade, and OCC on issuance.

Covers Difficulty queue: transitive_cascade (reinspect PASSED head -> cert VOID ->
sticker revoke), compensating_invariant (issue then void conserves active-cert
count), priority_pair_validation_conflict (forbidden beats invalid-state on a void),
cross_entity_state_dependency (certificate issuance requires a PASSED record).
Covers Corner queue: validations (duplicate certificate), cross_cutting (OCC stale
record version on issuance).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Difficulty: transitive_cascade — reinspect PASSED head voids cert + sticker
# ===========================================================================
def test_reinspect_passed_head_voids_certificate(api):
    """PRD §3.9: "First, the passed chain-head record is marked superseded and its
    `version` is incremented (it keeps its `PASSED` status as chain history)."
    PRD §3.9: "Second, caused by that supersession, the chain head's `ACTIVE`
    `Certificate` is driven through the certificate `ACTIVE → VOID` transition."

    Design: Difficulty/transitive_cascade/reinspect_passed_head_voids_certificate_then_revokes_sticker
    """
    station, profile, lane, appt1, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert cert["status"] == "ACTIVE"
    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    new_rec = F.reinspect(api, passed["id"], appt2["id"])
    assert new_rec["status"] == "IN_PROGRESS"
    assert new_rec["reinspection_index"] == 1
    cert_after = get_success_data(api.get_certificate(cert["id"], SM))
    assert cert_after["status"] == "VOID", \
        f"reinspecting a PASSED head must cascade its certificate to VOID, got {cert_after['status']}"


def test_reinspect_passed_head_revokes_sticker_and_bumps_cert_version(api):
    """PRD §3.9: "Third, caused by that void, the certificate's own void effect
    revokes and surrenders its `sticker_number`. As on the failed path, a new
    `IN_PROGRESS` record is created with `original_record_id` at the chain head and
    `reinspection_index` one greater, the void certificate's `version` is
    incremented, and the supplied appointment is consumed `CHECKED_IN → CONSUMED`."

    Design: Difficulty/transitive_cascade/reinspect_passed_head_voids_certificate_then_revokes_sticker
    """
    station, profile, lane, appt1, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    F.reinspect(api, passed["id"], appt2["id"])
    cert_after = get_success_data(api.get_certificate(cert["id"], SM))
    assert cert_after["status"] == "VOID"
    assert cert_after["version"] == cert["version"] + 1, \
        "the void certificate's version must be incremented by the cascade"
    # The consumed reinspection appointment moved CHECKED_IN -> CONSUMED.
    appt2_after = get_success_data(api.get_appointment(appt2["id"], SM))
    assert appt2_after["status"] == "CONSUMED"


# ===========================================================================
# Difficulty: compensating_invariant — issue then void conserves active count
# ===========================================================================
def test_issue_then_void_conserves_active_certificate_count(api):
    """PRD §3.10: "It can also be done deliberately by a `StationManager` as a
    compensating action. Either way, the certificate transitions `ACTIVE → VOID`, the
    issued `sticker_number` is revoked and considered surrendered, and the
    certificate's `version` is incremented."

    Design: Difficulty/compensating_invariant/certificate_issue_then_void_conserves_active_cert_count
    """
    station, profile, lane, appt, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert cert["status"] == "ACTIVE"
    voided = validate_success(api.void_certificate(cert["id"], SM), 200)
    assert voided["status"] == "VOID"
    # Conserved quantity: active certificates for the record return to 0.
    data, _meta = validate_paginated(
        api.list_certificates(SM, params={"record_id": passed["id"]}))
    active = [c for c in data if c["status"] == "ACTIVE"]
    assert len(active) == 0, f"no ACTIVE certificate should remain, found {len(active)}"


def test_void_then_reissue_restores_one_active_certificate(api):
    """PRD §3.10: "At most one `ACTIVE` certificate may exist per record; a second
    issuance against a record that already has an active certificate is rejected with
    `ERR_CERTIFICATE_EXISTS`."

    Design: Difficulty/compensating_invariant/certificate_issue_then_void_conserves_active_cert_count
    """
    station, profile, lane, appt, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    get_success_data(api.void_certificate(cert["id"], SM))
    # After the compensating void, the record has zero ACTIVE certs, so a fresh
    # issuance succeeds — the conserved count is back to its pre-issuance value of 0.
    fresh = get_success_data(api.get_inspection_record(passed["id"], SM))
    reissued = validate_success(
        api.create_certificate(F.create_certificate_payload(passed["id"], fresh["version"]), SM), 201)
    assert reissued["status"] == "ACTIVE"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict — forbidden(2) beats state(5)
# ===========================================================================
def test_inspector_void_of_already_void_cert_returns_forbidden_not_invalid_state(api):
    """PRD §2.9: "Authorization is second: a role not permitted for the operation
    yields `ERR_FORBIDDEN`."
    PRD §2.9: "State legality is fifth: attempting a transition from a state in which
    it is not defined yields `ERR_INVALID_STATE`."
    PRD §3.10: "`VOID` is terminal; voiding a certificate that is not `ACTIVE` is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_certificate_void
    """
    station, profile, lane, appt, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    get_success_data(api.void_certificate(cert["id"], SM))  # now VOID (terminal)
    # An Inspector is not permitted to void (StationManager-only). Auth outranks state.
    validate_error(api.void_certificate(cert["id"], INSP),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_station_manager_void_of_already_void_cert_returns_invalid_state(api):
    """PRD §3.10: "`VOID` is terminal; voiding a certificate that is not `ACTIVE` is
    rejected with `ERR_INVALID_STATE`."
    PRD §2.9: "State legality is fifth: attempting a transition from a state in which
    it is not defined yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_certificate_void
    """
    station, profile, lane, appt, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    get_success_data(api.void_certificate(cert["id"], SM))  # now VOID (terminal)
    # A StationManager IS permitted to void, so auth passes and the state check is the
    # one that fires — confirming ERR_FORBIDDEN above came specifically from the auth
    # gate pre-empting this state gate.
    validate_error(api.void_certificate(cert["id"], SM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Cross-entity / Corner: certificate issuance requires a PASSED record
# ===========================================================================
def test_certificate_issue_on_failed_record_returns_record_not_passed(api):
    """PRD §3.10: "The record must be `PASSED`; issuing against an `IN_PROGRESS`,
    `FAILED`, or `ABORTED` record is rejected with `ERR_RECORD_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_requires_record_passed
    """
    station, profile, lane, appt, failed = F.setup_safety_failed_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert failed["status"] == "FAILED"
    validate_error(
        api.create_certificate(F.create_certificate_payload(failed["id"], failed["version"]), SM),
        ApiErrorId.ERR_RECORD_NOT_PASSED.value)


def test_certificate_issue_on_in_progress_record_returns_record_not_passed(api):
    """PRD §3.10: "The record must be `PASSED`; issuing against an `IN_PROGRESS`,
    `FAILED`, or `ABORTED` record is rejected with `ERR_RECORD_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_requires_record_passed
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    validate_error(
        api.create_certificate(F.create_certificate_payload(record["id"], record["version"]), SM),
        ApiErrorId.ERR_RECORD_NOT_PASSED.value)


# ===========================================================================
# Corner: validations — duplicate certificate
# ===========================================================================
def test_duplicate_certificate_returns_certificate_exists(api):
    """PRD §3.10: "At most one `ACTIVE` certificate may exist per record; a second
    issuance against a record that already has an active certificate is rejected with
    `ERR_CERTIFICATE_EXISTS`."

    Design: Corner/validations/duplicate_certificate_returns_certificate_exists
    """
    station, profile, lane, appt, passed, cert = F.setup_passed_record_with_certificate(
        api, clock_iso="2026-06-10T09:00:00Z")
    # Issuance bumped the record version; re-read it so OCC passes and the duplicate
    # rule (not the stale-version rule) is what fires.
    fresh = get_success_data(api.get_inspection_record(passed["id"], SM))
    validate_error(
        api.create_certificate(F.create_certificate_payload(passed["id"], fresh["version"]), SM),
        ApiErrorId.ERR_CERTIFICATE_EXISTS.value)


# ===========================================================================
# Cross-cutting: OCC — stale record version on certificate issuance
# ===========================================================================
def test_issue_certificate_with_stale_record_version_returns_stale_version(api):
    """PRD §2.8: "If that value does not equal the record's current `version` — for
    example because the record was reinspected and superseded after the client read
    its `PASSED` state, advancing its `version` — the issuance is refused with
    `ERR_STALE_VERSION` and HTTP 412, so the station cannot certify a result that has
    since been superseded."

    Design: Corner/cross_cutting_complexity_layers/occ_cert_issue_stale_record_version_returns_412
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T08:00:00Z")
    appt1 = F.book_and_check_in(api, lane["id"],
                                scheduled_start="2026-06-10T09:00:00Z",
                                scheduled_end="2026-06-10T09:30:00Z")
    rec = F.open_record(api, appt1["id"])
    F.add_checklist(api, rec["id"], item_code="BRAKES", outcome="PASS")
    F.add_checklist(api, rec["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, rec["id"], mil_on=False, dtc_count=0)
    passed = F.decide_record(api, rec["id"])
    stale_version = passed["version"]  # client's last-observed PASSED version

    # Reinspect, which supersedes the head and advances its version.
    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    F.reinspect(api, passed["id"], appt2["id"])

    validate_error(
        api.create_certificate(F.create_certificate_payload(passed["id"], stale_version), SM),
        ApiErrorId.ERR_STALE_VERSION.value)
