"""OCC stale-version rejections, RBAC/auth denials, list-filter reachability,
version monotonicity, and immediate-consistency reads.

Translates queue-B errors (OCC), rbac, endpoints, cross_cutting_complexity_layers,
and consistency_model corner instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    setup_booking_ready,
    setup_completed_appointment,
    book_initial_appointment,
    pay_deposit,
    set_clock,
    create_studio_payload,
    create_client_payload,
    create_package_payload,
    create_touch_up_payload,
    create_redo_request_payload,
    schedule_redo_payload,
    create_healing_log_payload,
    deposit_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECH = TEST_USERS["technician_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: errors — OCC stale-version
# ─────────────────────────────────────────────────────────────────────────────
def test_redo_schedule_stale_appointment_version_rejected(api):
    """PRD §2.8: "A redo-scheduling request must carry `expected_appointment_version`
    matching the source appointment's current `version`. If the source
    appointment has been advanced since the client last observed it ... the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/errors/err_stale_version_redo_schedule
    """
    ctx, completed = setup_completed_appointment(
        healing_outcome_flag="POOR",
        healing_day_offset=21,
        scheduled_start="2026-01-06T10:00:00Z",
        complete_clock="2026-02-01T00:00:00Z",
    )
    stale_version = completed["version"]
    redo = get_success_data(api.create_redo_request(create_redo_request_payload(completed["id"]), FRONT))
    get_success_data(api.approve_redo(redo["id"], COMPLIANCE))
    # A later POOR healing log on the COMPLETED appointment bumps its version.
    get_success_data(
        api.create_healing_log(
            create_healing_log_payload(completed["id"], day_offset=30, outcome_flag="POOR"),
            make_technician_headers(ctx["technician"]["id"]),
        )
    )
    res = api.schedule_redo(
        redo["id"],
        schedule_redo_payload(
            ctx["technician"]["id"],
            ctx["formula"]["id"],
            ctx["patch_test"]["id"],
            expected_appointment_version=stale_version,
            scheduled_start="2026-02-10T10:00:00Z",
        ),
        FRONT,
    )
    validate_error(res, "ERR_STALE_VERSION")


def test_touchup_book_stale_package_version_rejected(api):
    """PRD §2.8: "A touch-up booking must carry `expected_package_version`
    matching the package order's current `version`. If another touch-up booking
    has already drawn from the package since the client last read it ... the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_touchup_book
    """
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    # Two extra READ/PASS patch tests for the two touch-up bookings.
    pt2 = get_success_data(api.create_patch_test({"client_id": ctx["client"]["id"]}, TECH))
    pt3 = get_success_data(api.create_patch_test({"client_id": ctx["client"]["id"]}, TECH))
    set_clock("2026-02-03T01:00:00Z")  # >=48h after pt applied_at (2026-02-01T00:00:00Z) to satisfy patch-read minimum
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    get_success_data(api.read_patch_test(pt2["id"], {"reaction_grade": 1}, tech_headers))
    get_success_data(api.read_patch_test(pt3["id"], {"reaction_grade": 1}, tech_headers))
    pkg = get_success_data(
        api.create_package(
            create_package_payload(ctx["client"]["id"], completed["id"], included_sessions=2, pricing_mode="PAYG"),
            FRONT,
        )
    )
    stale_pkg_version = pkg["version"]
    set_clock("2026-03-05T00:00:00Z")
    # First touch-up draws a session and bumps the package version.
    get_success_data(
        api.book_touch_up(
            create_touch_up_payload(
                pkg["id"],
                ctx["technician"]["id"],
                ctx["formula"]["id"],
                pt2["id"],
                scheduled_start="2026-03-10T10:00:00Z",
                expected_package_version=stale_pkg_version,
                procedure_type="BROWS",
            ),
            FRONT,
        )
    )
    # Second touch-up reuses the now-stale package version.
    res = api.book_touch_up(
        create_touch_up_payload(
            pkg["id"],
            ctx["technician"]["id"],
            ctx["formula"]["id"],
            pt3["id"],
            scheduled_start="2026-03-12T10:00:00Z",
            expected_package_version=stale_pkg_version,
            procedure_type="BROWS",
        ),
        FRONT,
    )
    validate_error(res, "ERR_STALE_VERSION")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: rbac
# ─────────────────────────────────────────────────────────────────────────────
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a header the
    server cannot interpret, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/rbac_unauthenticated_missing_headers
    """
    res = api.create_studio(create_studio_payload(sterile_kit_total=1), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_front_desk_cannot_suspend_license_forbidden(api):
    """PRD §2.1: "When the headers are present and valid but the declared role
    is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN`." and "`ComplianceOfficer` ... owns license suspension
    and reinstatement".

    Design: Corner/rbac/rbac_frontdesk_cannot_suspend_license
    """
    studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
    tech = get_success_data(
        api.create_technician(
            {
                "studio_id": studio["id"],
                "full_name": "T",
                "license_number": "L1",
                "bbp_cert_expiry": "2030-01-01T00:00:00Z",
                "license_expiry": "2030-01-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    sver = get_success_data(api.get_studio(studio["id"], ADMIN))["version"]
    res = api.suspend_license(tech["id"], {"expected_studio_version": sver}, FRONT)
    validate_error(res, "ERR_FORBIDDEN")


def test_compliance_officer_cannot_book_appointment_forbidden(api):
    """PRD §2.1: "As a segregation-of-duties measure, a `ComplianceOfficer`
    cannot book appointments or take payments."

    Design: Corner/rbac/rbac_compliance_cannot_book_appointment
    """
    ctx = setup_booking_ready()
    payload = {
        "client_id": ctx["client"]["id"],
        "technician_id": ctx["technician"]["id"],
        "color_formula_id": ctx["formula"]["id"],
        "patch_test_id": ctx["patch_test"]["id"],
        "procedure_type": "BROWS",
        "scheduled_start": "2026-01-06T10:00:00Z",
    }
    res = api.create_appointment(payload, COMPLIANCE)
    validate_error(res, "ERR_FORBIDDEN")


def test_front_desk_cannot_read_patch_test_forbidden(api):
    """PRD §2.1: "`Technician` is the clinical operator — it owns patch-test
    reads and the procedure progression".

    Design: Corner/rbac/rbac_frontdesk_cannot_read_patch_test
    """
    set_clock("2026-01-01T00:00:00Z")
    studio = get_success_data(api.create_studio(create_studio_payload(sterile_kit_total=5), ADMIN))
    client = get_success_data(api.create_client(create_client_payload(studio["id"], full_name="C"), FRONT))
    pt = get_success_data(api.create_patch_test({"client_id": client["id"]}, TECH))
    set_clock("2026-01-03T01:00:00Z")
    res = api.read_patch_test(pt["id"], {"reaction_grade": 1}, FRONT)
    validate_error(res, "ERR_FORBIDDEN")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: endpoints — list filters / reverse-reachability
# ─────────────────────────────────────────────────────────────────────────────
def test_list_appointments_filtered_by_client(api):
    """PRD §2.3: "Every list response includes these four fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/ep_list_appointments_filter_by_client
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    data, meta = validate_paginated(
        api.list_appointments(FRONT, params={"client_id": ctx["client"]["id"]})
    )
    ids = [a["id"] for a in data]
    assert appt["id"] in ids
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_healing_logs_filtered_by_appointment(api):
    """PRD §2.3: "Every list response includes these four fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/ep_healing_log_reverse_reachable
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    appt = pay_deposit(appt)
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    appt = get_success_data(api.start_appointment(appt["id"], tech_headers))
    get_success_data(api.finish_procedure(appt["id"], tech_headers))
    log = get_success_data(
        api.create_healing_log(
            create_healing_log_payload(appt["id"], day_offset=7, outcome_flag="GOOD", notes="ok"),
            tech_headers,
        )
    )
    data, meta = validate_paginated(
        api.list_healing_logs(TECH, params={"appointment_id": appt["id"]})
    )
    ids = [hl["id"] for hl in data]
    assert log["id"] in ids
    assert meta["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: cross_cutting_complexity_layers / consistency_model
# ─────────────────────────────────────────────────────────────────────────────
def test_appointment_version_starts_at_one_and_increments(api):
    """PRD §2.4: "a `version`, an integer that begins at 1 and increases by
    exactly 1 on every mutation — including mutations driven by cascades rather
    than direct client requests."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_version_increments_on_write
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    assert appt["version"] == 1
    after = pay_deposit(appt)
    assert after["version"] > appt["version"], (
        "deposit is a mutation; version must increase from create"
    )


def test_deposit_response_shows_paid_state_immediately(api):
    """PRD §3.6: "A successful collection emits a `CHARGE` deposit transaction
    and recomputes `deposit_paid_cents` to equal the required deposit."

    Design: Corner/consistency_model/cm_immediate_deposit_visible_in_response
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    assert appt["deposit_required_cents"] == 13000
    deposited = validate_success(api.deposit(appt["id"], deposit_payload(13000), FRONT), 200)
    assert deposited["deposit_paid_cents"] == 13000
    assert deposited["payment_status"] == "DEPOSIT_PAID"
