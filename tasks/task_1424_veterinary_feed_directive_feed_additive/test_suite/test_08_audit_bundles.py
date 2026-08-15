"""Audit bundles: required-record window semantics, empty-window boundary,
close guard, and the DEFICIENT producer-suspension cascade
(PRD §2.10, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_audit_bundle_payload, create_producer_payload,
    setup_producer_with_group, setup_clinic_with_vet, setup_drug,
    setup_audit_bundle, setup_vfd_chain, record_vcpr, issue_vfd,
    fresh_vfd, set_clock, parse_timestamp,
    make_veterinarian_headers,
)

INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty: audit_required_record_count_zero_empty ───

def test_empty_producer_audit_requires_zero_records(api):
    """PRD §3.9: "The bundle starts in `OPEN` status with `opened_at` set to the
    current logical time, `produced_record_count` initialized to zero, and
    `required_record_count` computed from the producer's records that intersect
    the window under the semantics defined in §2.10." A producer with no records
    intersects nothing, so both counts are zero.

    Design: Difficulty/boundary_precision_check/audit_required_record_count_zero_empty
    """
    producer = validate_success(api.create_producer(
        create_producer_payload(), INSPECTOR), 201)
    audit = validate_success(api.create_audit_bundle(
        producer["id"],
        create_audit_bundle_payload(
            window_start="2026-01-01T00:00:00Z", window_end="2026-02-01T00:00:00Z"),
        INSPECTOR,
    ), 201)
    assert audit["status"] == "OPEN"
    assert audit["required_record_count"] == 0
    assert audit["produced_record_count"] == 0


def test_empty_audit_closes_complete_at_zero_equals_zero(api):
    """PRD §3.9: "Closing requires the bundle to be `OPEN` and requires
    `produced_record_count` to equal `required_record_count` exactly; a shortfall
    is rejected with `ERR_AUDIT_INCOMPLETE` (HTTP 409). On success the bundle
    transitions to `COMPLETE`."

    Design: Difficulty/boundary_precision_check/audit_required_record_count_zero_empty
    """
    producer = validate_success(api.create_producer(
        create_producer_payload(), INSPECTOR), 201)
    audit = validate_success(api.create_audit_bundle(
        producer["id"],
        create_audit_bundle_payload(
            window_start="2026-01-01T00:00:00Z", window_end="2026-02-01T00:00:00Z"),
        INSPECTOR,
    ), 201)
    closed = validate_success(api.close_audit_bundle(audit["id"], INSPECTOR), 200)
    assert closed["status"] == "COMPLETE", (
        "0 produced == 0 required satisfies the close guard"
    )


# ─── Difficulty: audit_window_intersection_with_record_lifetime ───

def test_record_created_exactly_at_window_end_does_not_count(api):
    """PRD §2.10: "An `AuditBundle` defines a lookback window from `window_start`
    to `window_end` using half-open semantics on the window: a record contributes
    to `required_record_count` only if its `created_at` is strictly before
    `window_end` and either it has never reached a terminal state or its terminal
    timestamp is greater than or equal to `window_start`."
    PRD §2.10: "A record created exactly at `window_end` does not count toward
    the audit; a record that terminated exactly at `window_start` does count."

    Setup uses forward-only clock moves: VFD-A is created at the 2026-08-01
    startup clock, the clock then advances to 2026-08-10 and VFD-B is created
    exactly at the audit's window_end.

    Design: Difficulty/resource_temporal_overlap/audit_window_intersection_with_record_lifetime
    """
    chain = setup_vfd_chain(
        vfd_overrides={"authorized_animal_count": 5, "expiration_date": "2026-12-01T00:00:00Z"},
    )
    vfd_a = chain["vfd"]  # created_at == 2026-08-01T00:00:00Z (startup default)

    set_clock("2026-08-10T00:00:00Z")
    vfd_b = issue_vfd(
        chain["vet"], chain["producer"], chain["group"], chain["drug"],
        authorized_animal_count=5, expiration_date="2026-12-01T00:00:00Z",
    )
    b_dt = parse_timestamp(vfd_b["created_at"])
    assert (b_dt.year, b_dt.month, b_dt.day, b_dt.hour, b_dt.minute) == (2026, 8, 10, 0, 0), (
        f"VFD-B must be created exactly at the window end, got {vfd_b['created_at']!r}"
    )

    audit = validate_success(api.create_audit_bundle(
        chain["producer"]["id"],
        create_audit_bundle_payload(
            window_start="2026-08-01T00:00:00Z", window_end="2026-08-10T00:00:00Z"),
        INSPECTOR,
    ), 201)
    assert audit["required_record_count"] == 1, (
        f"Only VFD-A (created before window_end) counts; VFD-B created exactly at "
        f"window_end is excluded. Got {audit['required_record_count']}"
    )


def test_record_terminated_exactly_at_window_start_counts(api):
    """PRD §2.10: "a record contributes to `required_record_count` only if its
    `created_at` is strictly before `window_end` and either it has never reached
    a terminal state or its terminal timestamp is greater than or equal to
    `window_start`. ... a record that terminated exactly at `window_start` does
    count."

    Setup: VFD-A revoked exactly at window_start (counts); VFD-B revoked before
    window_start (does not count).

    Design: Difficulty/resource_temporal_overlap/audit_window_intersection_with_record_lifetime
    """
    chain = setup_vfd_chain(
        vfd_overrides={"authorized_animal_count": 5, "expiration_date": "2026-12-01T00:00:00Z"},
    )
    vfd_a = chain["vfd"]
    vfd_b = issue_vfd(
        chain["vet"], chain["producer"], chain["group"], chain["drug"],
        authorized_animal_count=5, expiration_date="2026-12-01T00:00:00Z",
    )
    vet_headers = make_veterinarian_headers(chain["vet"]["id"])

    # VFD-B terminates before the window opens: excluded.
    set_clock("2026-08-03T00:00:00Z")
    validate_success(api.revoke_vfd_authorization(vfd_b["id"], vet_headers), 200)
    # VFD-A terminates exactly at window_start: included (>= semantics).
    set_clock("2026-08-05T00:00:00Z")
    validate_success(api.revoke_vfd_authorization(vfd_a["id"], vet_headers), 200)

    set_clock("2026-08-10T00:00:00Z")
    audit = validate_success(api.create_audit_bundle(
        chain["producer"]["id"],
        create_audit_bundle_payload(
            window_start="2026-08-05T00:00:00Z", window_end="2026-08-10T00:00:00Z"),
        INSPECTOR,
    ), 201)
    assert audit["required_record_count"] == 1, (
        f"VFD-A (terminated exactly at window_start) counts; VFD-B (terminated "
        f"before window_start) does not. Got {audit['required_record_count']}"
    )


# ─── Difficulty: audit_deficient_cascades_producer_suspension_to_vfd_expiry ───

def _setup_producer_with_two_vfds_and_audit():
    """Producer holding two ISSUED VFDs plus one OPEN audit bundle."""
    chain = setup_vfd_chain(
        vfd_overrides={"authorized_animal_count": 10, "expiration_date": "2026-10-01T00:00:00Z"},
    )
    vfd_b = issue_vfd(
        chain["vet"], chain["producer"], chain["group"], chain["drug"],
        authorized_animal_count=20, expiration_date="2026-10-15T00:00:00Z",
    )
    audit = setup_audit_bundle(chain["producer"]["id"])
    return chain, vfd_b, audit


def test_mark_deficient_suspends_producer(api):
    """PRD §3.9: "an inspector may mark an `OPEN` bundle as `DEFICIENT`; this
    transitions the bundle to `DEFICIENT`, flips the producer's `status` to
    `SUSPENDED`"

    Design: Difficulty/transitive_cascade/audit_deficient_cascades_producer_suspension_to_vfd_expiry
    """
    chain, _, audit = _setup_producer_with_two_vfds_and_audit()
    deficient = validate_success(api.mark_audit_deficient(audit["id"], INSPECTOR), 200)
    assert deficient["status"] == "DEFICIENT"

    producer_after = validate_success(
        api.get_producer(chain["producer"]["id"], INSPECTOR), 200)
    assert producer_after["status"] == "SUSPENDED"


def test_mark_deficient_cascades_vfds_to_expired(api):
    """PRD §3.9: "cascades every `VfdAuthorization` the producer holds in a
    non-terminal state into `EXPIRED`, firing the per-VFD feed-order cancellation
    cascade described in §3.4."

    Design: Difficulty/transitive_cascade/audit_deficient_cascades_producer_suspension_to_vfd_expiry
    """
    chain, vfd_b, audit = _setup_producer_with_two_vfds_and_audit()
    validate_success(api.mark_audit_deficient(audit["id"], INSPECTOR), 200)

    for vfd_id, label in ((chain["vfd"]["id"], "VFD-A"), (vfd_b["id"], "VFD-B")):
        vfd_after = fresh_vfd(vfd_id)
        assert vfd_after["status"] == "EXPIRED", (
            f"{label} must cascade to EXPIRED, got {vfd_after['status']}"
        )


# ─── Corner: audit_close_incomplete_returns_error ───

def test_close_audit_with_unproduced_records_rejected(api):
    """PRD §3.9: "Closing requires the bundle to be `OPEN` and requires
    `produced_record_count` to equal `required_record_count` exactly; a shortfall
    is rejected with `ERR_AUDIT_INCOMPLETE` (HTTP 409)."

    Design: Corner/endpoints/audit_close_incomplete_returns_error
    """
    chain = setup_vfd_chain(
        vfd_overrides={"authorized_animal_count": 5, "expiration_date": "2026-10-01T00:00:00Z"},
    )
    # The VFD was created at the 2026-08-01 startup clock, inside this window.
    audit = setup_audit_bundle(
        chain["producer"]["id"],
        window_start="2026-07-01T00:00:00Z", window_end="2026-08-02T00:00:00Z",
    )
    assert audit["required_record_count"] >= 1, "Setup anchor: the VFD must intersect the window"
    assert audit["produced_record_count"] == 0

    res = api.close_audit_bundle(audit["id"], INSPECTOR)
    validate_error(res, ApiErrorId.ERR_AUDIT_INCOMPLETE, expected_status=409)

    audit_after = validate_success(api.get_audit_bundle(audit["id"], INSPECTOR), 200)
    assert audit_after["status"] == "OPEN"
