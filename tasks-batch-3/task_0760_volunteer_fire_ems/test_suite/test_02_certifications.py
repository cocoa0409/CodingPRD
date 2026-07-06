"""Certification issue/renew hours gates, the recertification cycle, expiry
boundary, and certification listing.

Queue A: dual_variant_calc/cert_strict_vs_carryover_hours,
non_linear_state_machine/certification_recert_cycle_revisits_current,
boundary_precision_check/cert_expiry_instant_boundary.
Queue B: corner_insufficient_hours_on_issue, corner_certifications_filtered_by_member.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    CHIEF,
    create_officer,
    create_member,
    set_clock,
)
from test_helpers.factories import (
    create_certification_payload,
    create_training_record_payload,
)


def _issued_ff1_cert(api, off, member_id, issue_hours=24):
    """Create a FIREFIGHTER_1/FIRE cert (cycle_start = default clock 2026-03-01),
    log `issue_hours` FIRE hours, and issue it CURRENT (expires 2027-03-01)."""
    cert = get_success_data(
        api.create_certification(
            member_id, create_certification_payload(cert_type="FIREFIGHTER_1", category="FIRE"), off
        )
    )
    get_success_data(
        api.create_training_record(
            member_id,
            create_training_record_payload(category="FIRE", hours=issue_hours, training_date="2026-03-01T00:00:00Z"),
            off,
        )
    )
    get_success_data(api.issue_certification(cert["id"], off))
    return cert["id"]


def _setup_carryover_cert(api):
    """Cert issued CURRENT then expired via sweep, with 8h pre-cycle + 16h in-cycle
    training available for the pending renewal cycle (cycle resets to 2027-03-01)."""
    off_id, off = create_officer(api)
    m = create_member(api, role_class="FIREFIGHTER")
    cert_id = _issued_ff1_cert(api, off, m["id"], issue_hours=24)
    set_clock("2027-03-01T00:00:00Z")
    get_success_data(api.sweep_certifications(off))
    # 8h in the 90-day pre-cycle window before the renewed cycle_start_at (2027-03-01).
    get_success_data(
        api.create_training_record(
            m["id"],
            create_training_record_payload(category="FIRE", hours=8, training_date="2027-01-15T00:00:00Z"),
            off,
        )
    )
    # 16h in the renewed cycle.
    get_success_data(
        api.create_training_record(
            m["id"],
            create_training_record_payload(category="FIRE", hours=16, training_date="2027-03-01T00:00:00Z"),
            off,
        )
    )
    return off, cert_id


def test_renew_uses_carryover_hours_reaches_current(api):
    """PRD §3.2: "An expired certification is brought back with a **renewal**,
    `EXPIRED → CURRENT`, and an expiring certification may be renewed early,
    `EXPIRING → CURRENT`; both renewals require the certification's carryover
    completed hours to be at least the required hours for its type, failing with
    `ERR_INSUFFICIENT_TRAINING_HOURS` otherwise."

    Design: Difficulty/dual_variant_calc/cert_strict_vs_carryover_hours
    """
    off, cert_id = _setup_carryover_cert(api)
    renewed = validate_success(api.renew_certification(cert_id, off), 200)
    assert renewed["status"] == "CURRENT"


def test_renewed_cert_reports_strict_16_carryover_24(api):
    """PRD §3.2: "The **strict** total is the sum of the hours of those matching
    records whose `training_date` falls on or after the certification's
    `cycle_start_at` and on or before the current clock. The **carryover** total
    takes that same in-cycle sum and adds a capped contribution from the 90 days
    immediately before the cycle began: ... but that pre-cycle contribution is
    added only up to a maximum of 8 hours (if the pre-cycle window holds more than
    8 qualifying hours, exactly 8 are carried)."

    Design: Difficulty/dual_variant_calc/cert_strict_vs_carryover_hours
    """
    off, cert_id = _setup_carryover_cert(api)
    get_success_data(api.renew_certification(cert_id, off))
    cert = validate_success(api.get_certification(cert_id, off), 200)
    assert cert["completed_hours_strict"] == 16.0
    assert cert["completed_hours_carryover"] == 24.0


def _setup_recert_cycle_to_expired(api):
    """A FIREFIGHTER_1 cert taken CURRENT -> EXPIRING -> EXPIRED via sweeps, with
    24h fresh in-cycle training logged so it can renew back to CURRENT."""
    off_id, off = create_officer(api)
    m = create_member(api, role_class="FIREFIGHTER")
    cert_id = _issued_ff1_cert(api, off, m["id"], issue_hours=24)
    set_clock("2027-02-15T00:00:00Z")
    get_success_data(api.sweep_certifications(off))  # CURRENT -> EXPIRING
    set_clock("2027-03-01T00:00:00Z")
    get_success_data(api.sweep_certifications(off))  # EXPIRING -> EXPIRED
    get_success_data(
        api.create_training_record(
            m["id"],
            create_training_record_payload(category="FIRE", hours=24, training_date="2027-03-01T00:00:00Z"),
            off,
        )
    )
    return off, cert_id


def test_recert_cycle_reaches_expired_via_sweep(api):
    """PRD §3.2: "Once the current clock reaches or passes `expires_at`, the
    certification expires: an `EXPIRING` certification moves `EXPIRING → EXPIRED`,
    and a certification that was still `CURRENT` when its expiry passed (the
    expiring window was skipped over) moves `CURRENT → EXPIRED` directly."

    Design: Difficulty/non_linear_state_machine/certification_recert_cycle_revisits_current
    """
    off, cert_id = _setup_recert_cycle_to_expired(api)
    cert = validate_success(api.get_certification(cert_id, off), 200)
    assert cert["status"] == "EXPIRED"


def test_recert_cycle_re_enters_current_on_renew(api):
    """PRD §3.2: "An expired certification is brought back with a **renewal**,
    `EXPIRED → CURRENT`, and an expiring certification may be renewed early,
    `EXPIRING → CURRENT`; both renewals require the certification's carryover
    completed hours to be at least the required hours for its type ..."

    Design: Difficulty/non_linear_state_machine/certification_recert_cycle_revisits_current
    """
    off, cert_id = _setup_recert_cycle_to_expired(api)
    renewed = validate_success(api.renew_certification(cert_id, off), 200)
    assert renewed["status"] == "CURRENT"


def test_cert_expiring_at_one_second_before_expiry(api):
    """PRD §3.2: "a `CURRENT` certification whose expiry is within the coming 30
    days — that is, the current clock is on or after the instant 30 days before
    `expires_at` and still before `expires_at` — moves `CURRENT → EXPIRING`, and a
    member holding an expiring certification remains eligible because `EXPIRING`
    still counts as valid."

    Design: Difficulty/boundary_precision_check/cert_expiry_instant_boundary
    """
    off_id, off = create_officer(api)
    m = create_member(api, role_class="FIREFIGHTER")
    cert_id = _issued_ff1_cert(api, off, m["id"], issue_hours=24)
    set_clock("2027-02-28T23:59:59Z")
    get_success_data(api.sweep_certifications(off))
    cert = validate_success(api.get_certification(cert_id, off), 200)
    assert cert["status"] == "EXPIRING"


def test_cert_expired_exactly_at_expiry_instant(api):
    """PRD §3.2: "Once the current clock reaches or passes `expires_at`, the
    certification expires: an `EXPIRING` certification moves `EXPIRING → EXPIRED`,
    and a certification that was still `CURRENT` when its expiry passed (the
    expiring window was skipped over) moves `CURRENT → EXPIRED` directly."

    Design: Difficulty/boundary_precision_check/cert_expiry_instant_boundary
    """
    off_id, off = create_officer(api)
    m = create_member(api, role_class="FIREFIGHTER")
    cert_id = _issued_ff1_cert(api, off, m["id"], issue_hours=24)
    set_clock("2027-03-01T00:00:00Z")
    get_success_data(api.sweep_certifications(off))
    cert = validate_success(api.get_certification(cert_id, off), 200)
    assert cert["status"] == "EXPIRED"


def test_issue_with_insufficient_strict_hours_rejected(api):
    """PRD §3.2: "An Officer **issues** a pending certification, transitioning
    `PENDING → CURRENT`, only when the certification's strict completed hours are
    at least the required hours for its type; otherwise the issue is rejected with
    `ERR_INSUFFICIENT_TRAINING_HOURS`."

    Design: Corner/validations/corner_insufficient_hours_on_issue
    """
    off_id, off = create_officer(api)
    m = create_member(api, role_class="EMT")
    cert = get_success_data(
        api.create_certification(
            m["id"], create_certification_payload(cert_type="EMT_BASIC", category="EMS"), off
        )
    )
    get_success_data(
        api.create_training_record(
            m["id"],
            create_training_record_payload(category="EMS", hours=10, training_date="2026-03-01T00:00:00Z"),
            off,
        )
    )
    validate_error(
        api.issue_certification(cert["id"], off), ApiErrorId.ERR_INSUFFICIENT_TRAINING_HOURS.value
    )


def test_certifications_filtered_by_member(api):
    """PRD §2.8: "List endpoints support reverse reachability through optional
    filter parameters — for instance, certifications and training records filter
    by `member_id`, apparatus filters by `station_id`, ..."

    Design: Corner/endpoints/corner_certifications_filtered_by_member
    """
    off_id, off = create_officer(api)
    m = create_member(api, role_class="EMT")
    get_success_data(
        api.create_certification(
            m["id"], create_certification_payload(cert_type="EMT_BASIC", category="EMS"), off
        )
    )
    get_success_data(
        api.create_certification(
            m["id"],
            create_certification_payload(cert_type="CPR", category="CPR", is_required=False),
            off,
        )
    )
    data, meta = validate_paginated(api.list_certifications(off, params={"member_id": m["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert all(c["member_id"] == m["id"] for c in data)
