"""Corner cases in access control: the ordering of authentication before authorisation, a write
two roles genuinely share, a per-user interlock inside one role, and tenancy expressed through the
caller's own identifier."""

from test_helpers import (
    AUDITOR_HEADERS,
    ApiErrorId,
    ComplaintStatus,
    DISPATCH_HEADERS,
    Disposition,
    ReadingSource,
    RecordStatus,
    Role,
    SECOND_AUDITOR_HEADERS,
    SECOND_AUDITOR_USER_ID,
    AUDITOR_USER_ID,
    Symptom,
    assert_instant,
    assert_liters,
    factories,
    fixtures,
    get_success_data,
    headers_without_user_id,
    make_service_technician_headers,
    make_venue_manager_headers,
    validate_error,
    validate_paginated,
)


def test_the_technician_who_logged_a_cycle_may_not_void_it_and_a_nameless_caller_gets_no_further(api):
    """PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not one of the five
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers
    are well formed but the named role is not one of the roles authorised for the endpoint being
    called (see the authorisation column of the endpoint table in §4), the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_void_is_unauthorized_for_the_technician_and_unauthenticated_without_a_user_id
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    lot_id = ground["lot"]["id"]
    cycle = fixtures.log_cleaning_cycle(
        api, ground["visit"]["id"], ground["line"]["id"], lot_id, ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    # A read the auditor is entitled to make, minus the caller's identifier.
    validate_error(
        api.get_cleaning_cycle(cycle["id"], headers_without_user_id(Role.QUALITY_AUDITOR)),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    validate_error(
        api.void_cleaning_cycle(
            cycle["id"], "I keyed the wrong contact time.", ground["tech_headers"]
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    assert fixtures.read_cycle(api, cycle["id"])["record_status"] == RecordStatus.POSTED
    assert_liters(fixtures.read_lot(api, lot_id)["liters_remaining"], 19.690)

    voided = fixtures.void_cycle(api, cycle["id"], "Contact time keyed against the wrong line.")

    assert voided["record_status"] == RecordStatus.VOIDED
    assert_liters(fixtures.read_lot(api, lot_id)["liters_remaining"], 20.0)


def test_a_cooler_reading_labels_itself_from_the_role_that_posted_it(api):
    """PRD §3.9: "The server stamps `reading_at` from the logical clock, records
    `recorded_by_user_id` from `X-User-ID`, and derives `source` from the acting role —
    `TECH_MANUAL` for a technician, `VENUE_MANUAL` for a venue manager."

    Design: Corner/rbac/corner_cooler_readings_are_shared_by_two_roles_and_unauthorized_for_dispatch
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue = fixtures.onboard_venue(
        api, venue_name="Cellar Cooler Pub", glycol_system_present=True, lines=()
    )
    account_id = venue["account"]["id"]
    loop_id = venue["loop"]["id"]
    technician = fixtures.create_technician(api)

    by_tech = get_success_data(
        api.create_cooler_reading(
            factories.cooler_reading_payload(loop_id, cooler_temp_f=36.0, glycol_supply_temp_f=28.5),
            make_service_technician_headers(technician["id"]),
        ),
        expected_status=201,
    )
    by_venue = get_success_data(
        api.create_cooler_reading(
            factories.cooler_reading_payload(loop_id, cooler_temp_f=37.0, glycol_supply_temp_f=29.0),
            make_venue_manager_headers(account_id),
        ),
        expected_status=201,
    )

    assert by_tech["source"] == ReadingSource.TECH_MANUAL
    assert by_tech["recorded_by_user_id"] == technician["id"]
    assert by_venue["source"] == ReadingSource.VENUE_MANUAL
    assert by_venue["recorded_by_user_id"] == account_id
    # reading_at is stamped from the clock, never supplied.
    assert_instant(by_tech["reading_at"], fixtures.CLOCK_EPOCH, label="reading_at")

    validate_error(
        api.create_cooler_reading(
            factories.cooler_reading_payload(loop_id, cooler_temp_f=38.0, glycol_supply_temp_f=29.5),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    listed, meta = validate_paginated(
        api.list_cooler_readings(
            AUDITOR_HEADERS, glycol_loop_id=loop_id, source=ReadingSource.VENUE_MANUAL
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == by_venue["id"]


def test_the_auditor_who_escalated_a_complaint_may_not_sign_it_off(api):
    """PRD §3.8: "Every resolution requires a `measured_waste_liters` figure of zero or more, else
    `ERR_INVALID_REQUEST`; requires that the acting `X-User-ID` differ from the
    `escalated_by_user_id` already on the record, else `ERR_SEGREGATION_OF_DUTIES`, since the auditor
    who escalated a complaint may never be the one who signs it off; and requires the complaint's
    line to be back `IN_SERVICE`, else `ERR_LINE_OUT_OF_SERVICE`, because a line still out of service
    has not been made good."

    Design: Corner/rbac/corner_the_auditor_who_escalated_a_complaint_cannot_resolve_it
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse")
    account_id = venue["account"]["id"]
    fixtures.set_clock(api, "2026-08-05T11:00:00Z")
    complaint = fixtures.file_complaint(
        api, account_id, venue["lines"][0]["id"], symptom=Symptom.FOAMY_POUR
    )
    assert complaint["status"] == ComplaintStatus.OPEN

    diagnosed = fixtures.run_diagnostic_round(api, complaint["id"], headers=AUDITOR_HEADERS)
    assert diagnosed["status"] == ComplaintStatus.DIAGNOSING

    escalated = fixtures.close_complaint(
        api, complaint["id"], disposition=Disposition.ESCALATED, measured_waste_liters=0.0,
        headers=AUDITOR_HEADERS,
    )
    assert escalated["status"] == ComplaintStatus.ESCALATED
    assert escalated["escalated_by_user_id"] == AUDITOR_USER_ID
    # An escalated complaint stays counted against the account.
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 1

    validate_error(
        api.close_quality_complaint(
            complaint["id"],
            factories.closure_payload(
                disposition=Disposition.RESOLVED, measured_waste_liters=4.0
            ),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert fixtures.read_complaint(api, complaint["id"])["status"] == ComplaintStatus.ESCALATED

    # Same role, different X-User-ID.
    resolved = fixtures.close_complaint(
        api, complaint["id"], disposition=Disposition.RESOLVED, measured_waste_liters=4.0,
        headers=SECOND_AUDITOR_HEADERS,
    )

    assert resolved["status"] == ComplaintStatus.RESOLVED
    assert resolved["closed_by_user_id"] == SECOND_AUDITOR_USER_ID
    assert resolved["escalated_by_user_id"] == AUDITOR_USER_ID
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 0


def test_a_venue_manager_cannot_file_a_complaint_about_another_venues_line(api):
    """PRD §3.8: "Intake is screened in this order: the `X-User-ID` must equal the `account_id` in
    the body (`ERR_ACCOUNT_SCOPE_VIOLATION`), the account must be `ACTIVE`
    (`ERR_ACCOUNT_NOT_ACTIVE`), and the line must belong to that account
    (`ERR_LINE_ACCOUNT_MISMATCH`)."

    Design: Corner/rbac/corner_venue_manager_cannot_open_a_complaint_against_another_venue
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue_a = fixtures.onboard_venue(api, venue_name="Anchor Alehouse", lines=())
    venue_b = fixtures.onboard_venue(api, venue_name="Harbor Taproom")
    account_a = venue_a["account"]["id"]
    account_b = venue_b["account"]["id"]
    line_b = venue_b["lines"][0]["id"]

    payload = factories.quality_complaint_payload(account_b, line_b, Symptom.FLAT_POUR)
    validate_error(
        api.create_quality_complaint(payload, make_venue_manager_headers(account_a)),
        ApiErrorId.ACCOUNT_SCOPE_VIOLATION,
        403,
    )
    assert fixtures.read_account(api, account_b)["open_complaint_count"] == 0

    filed = get_success_data(
        api.create_quality_complaint(payload, make_venue_manager_headers(account_b)),
        expected_status=201,
    )

    assert filed["account_id"] == account_b
    assert filed["status"] == ComplaintStatus.OPEN
    assert fixtures.read_account(api, account_b)["open_complaint_count"] == 1
    assert fixtures.read_account(api, account_a)["open_complaint_count"] == 0
