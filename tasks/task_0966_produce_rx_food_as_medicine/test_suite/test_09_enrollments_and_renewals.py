"""Enrollment lifecycle, renewal OCC, supersession, and the renewal window
(PRD §2.7, §3.3, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_clinic_staff_headers,
    create_renewal_payload,
    setup_enrollment, setup_lapsed_enrollment, create_renewal,
    get_enrollment, set_clock,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_enrollment_suspend_reinstate_round_trip(api):
    """PRD §3.3: "From ACTIVE, an enrollment can be suspended by a
    `ProgramAdmin` — or automatically when its program freezes — landing in
    SUSPENDED. Reinstatement returns SUSPENDED to ACTIVE but is refused while
    the program is FROZEN (`ERR_PROGRAM_FROZEN`) or CLOSED
    (`ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Corner/state_machines/c_enrollment_suspend_reinstate_round_trip
    """
    ctx = setup_enrollment()
    enrollment_id = ctx["enrollment_id"]
    before = get_enrollment(enrollment_id)

    suspended = validate_success(
        api.suspend_enrollment(enrollment_id, ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == before["version"] + 1

    reinstated = validate_success(
        api.reinstate_enrollment(enrollment_id, ADMIN), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == suspended["version"] + 1


def test_occ_stale_enrollment_version_rejected(api):
    """PRD §2.7: "Creating a renewal against an enrollment requires the
    request to carry `expected_enrollment_version`, holding the enrollment's
    `version` as the client last observed it; if another writer has advanced
    the enrollment's version since then — which happens precisely when a
    renewal creation supersedes a prior draft renewal — the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/c_occ_stale_enrollment_version_rejected
    """
    ctx = setup_enrollment()
    enrollment = get_enrollment(ctx["enrollment_id"])
    stale_version = enrollment["version"]

    first = create_renewal(ctx, reason="first")
    assert first["status"] == "DRAFT"

    res = api.create_renewal(
        ctx["enrollment_id"],
        create_renewal_payload(stale_version, reason="stale second"),
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    validate_error(res, "ERR_STALE_VERSION")


def test_occ_success_increments_version_and_supersedes(api):
    """PRD §2.7: "Each successful creation of either kind increments the
    parent entity's `version` by one."
    PRD §3.8: "A successful creation increments the enrollment's `version` by
    one and supersedes any prior DRAFT renewal of the same enrollment, moving
    it to SUPERSEDED."

    Design: Corner/cross_cutting_complexity_layers/c_occ_success_increments_version_and_supersedes
    """
    ctx = setup_enrollment()
    v0 = get_enrollment(ctx["enrollment_id"])["version"]

    renewal1 = create_renewal(ctx, reason="first")
    v1 = get_enrollment(ctx["enrollment_id"])["version"]
    assert v1 == v0 + 1

    renewal2 = create_renewal(ctx, reason="second")
    v2 = get_enrollment(ctx["enrollment_id"])["version"]
    assert v2 == v0 + 2

    r1 = validate_success(api.get_renewal(renewal1["id"], ADMIN), 200)
    r2 = validate_success(api.get_renewal(renewal2["id"], ADMIN), 200)
    assert r1["status"] == "SUPERSEDED"
    assert r2["status"] == "DRAFT"


def test_outside_renewal_window_rejected(api):
    """PRD §3.8: "For a LAPSED enrollment there is a clock on the wall:
    creation must happen within the program's `renewal_window_days` after
    `lapsed_at`, and a later attempt is `ERR_OUTSIDE_RENEWAL_WINDOW`."
    PRD §3.9: "Enrollment lapse applies the zero-redemption rule of §3.8
    against the program's latest CLOSED cycle."

    Design: Corner/errors/c_outside_renewal_window_rejected
    """
    # Enrollment lapses at the default logical clock 2026-05-01 (run-ops after
    # a zero-redemption closed cycle); the renewal window is 30 days.
    ctx = setup_lapsed_enrollment()
    assert ctx["ops_result"]["lapsed_enrollment_count"] == 1
    assert ctx["enrollment"]["status"] == "LAPSED"

    set_clock("2026-06-15T00:00:00Z")  # 45 days after lapse: outside 30 days.
    current = get_enrollment(ctx["enrollment_id"])
    res = api.create_renewal(
        ctx["enrollment_id"],
        create_renewal_payload(current["version"], reason="late renewal"),
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    validate_error(res, "ERR_OUTSIDE_RENEWAL_WINDOW")
