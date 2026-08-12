"""Error catalog coverage + RBAC denials + cross-cutting OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_education_completion_payload,
    create_lease_payload,
    create_refinance_request_payload,
    create_unit_payload,
    get_success_data,
    make_household_headers,
    setup_active_lease,
    setup_household,
    setup_matched_resale,
    setup_program,
    validate_error,
)


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _insp():
    return TEST_USERS["inspector_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def test_reference_not_found_invalid_course_id():
    """PRD §2.10 step 5: "**Body referential integrity** — every foreign-key
    identifier in the request body (for example `course_id`, `household_id`,
    `lease_id`) must resolve to an existing entity in the same program scope;
    otherwise `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/errors/error_reference_not_found_invalid_course_id
    """
    prog = setup_program(name="P-REF")
    hh = setup_household(prog["id"])
    resp = api_client.create_education_completion(
        prog["id"],
        hh["id"],
        create_education_completion_payload(
            course_id=NON_EXISTENT_UUID,
            completed_at="2026-04-01T00:00:00Z",
            score_pct=0.9,
        ),
        _is(),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_unit_blocked_on_unsafe_maintenance_flag():
    """PRD §3.5: "The create is rejected with `ERR_UNIT_BLOCKED` if the
    unit's `maintenance_flag` is `UNSAFE`, if the unit is not in `OCCUPIED`
    status, or if any `OPEN` `DefaultNotice` exists on the seller's lease."

    Design: Corner/errors/error_unit_blocked_on_unsafe_maintenance_flag
    """
    prog = setup_program(name="P-UB")
    _, unit, _, lease = setup_active_lease(prog["id"])

    # FAILED inspection marks unit UNSAFE.
    inspection = get_success_data(
        api_client.create_inspection(
            prog["id"], unit["id"], {"scheduled_for": "2026-05-15T00:00:00Z"}, _insp()
        )
    )
    get_success_data(
        api_client.record_inspection_result(
            prog["id"], unit["id"], inspection["id"],
            {"result": "FAILED", "findings": "Unsafe wiring"},
            _insp(),
        )
    )

    resp = api_client.create_resale_listing(
        prog["id"],
        unit["id"],
        {"seller_lease_id": lease["id"], "appraisal_at_listing_cents": 25_000_000},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_BLOCKED.value)


def test_compliance_officer_cannot_manage_leases():
    """PRD §2.1: "`LeaseManager` — manages ground leases, defaults, resales,
    and refinances; cannot certify income."
    PRD §2.1: "`ComplianceOfficer` — reviews and decides income
    certifications; is barred from reviewing a certification they themselves
    submitted."
    PRD §2.1: "If the headers are present but the named role is not
    permitted to invoke the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    Lease activation is LeaseManager territory; a ComplianceOfficer is not
    permitted to invoke it.

    Design: Corner/roles/compliance_officer_cannot_manage_leases
    """
    from test_helpers import setup_eligible_household

    prog = setup_program(name="P-RB1")
    unit = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 RB St"), _pga())
    )
    hh, _, _ = setup_eligible_household(prog["id"])
    lease = get_success_data(
        api_client.create_lease(
            prog["id"], unit["id"],
            create_lease_payload(household_id=hh["id"]),
            _lm(),
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    resp = api_client.activate_lease(
        prog["id"],
        unit["id"],
        lease["id"],
        {"expected_unit_version": unit_now["version"]},
        _co(),  # ComplianceOfficer not allowed
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_household_cannot_approve_own_refinance():
    """PRD §3.8: "From `LENDER_REVIEW`, a `LeaseManager` may approve or
    reject."
    PRD §2.1: "If the headers are present but the named role is not
    permitted to invoke the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    Approval is restricted to LeaseManager; a Household caller is not
    permitted to invoke it.

    Design: Corner/roles/household_cannot_approve_own_refinance
    """
    prog = setup_program(name="P-RB2")
    _, unit, hh, lease = setup_active_lease(prog["id"])
    hh_headers = make_household_headers(hh["id"])
    refi = get_success_data(
        api_client.create_refinance_request(
            prog["id"],
            unit["id"],
            lease["id"],
            create_refinance_request_payload(),
            hh_headers,
        )
    )
    get_success_data(
        api_client.submit_refi_to_lender(
            prog["id"], unit["id"], lease["id"], refi["id"], hh_headers
        )
    )
    resp = api_client.approve_refinance(
        prog["id"], unit["id"], lease["id"], refi["id"], hh_headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_inspector_cannot_approve_income_cert():
    """PRD §2.1: "`ComplianceOfficer` — reviews and decides income
    certifications; is barred from reviewing a certification they themselves
    submitted."
    PRD §2.1: "`Inspector` — performs unit inspections and records their
    outcomes."
    PRD §2.1: "If the headers are present but the named role is not
    permitted to invoke the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    Income-cert approval is a ComplianceOfficer decision; an Inspector is
    not permitted to invoke it.

    Design: Corner/roles/inspector_cannot_approve_income_cert
    """
    from test_helpers import create_income_certification_payload

    prog = setup_program(name="P-RB3")
    hh = setup_household(prog["id"])
    cert = get_success_data(
        api_client.create_income_certification(
            prog["id"], hh["id"], create_income_certification_payload(), _is()
        )
    )
    get_success_data(
        api_client.start_review_income_certification(
            prog["id"], hh["id"], cert["id"], _co()
        )
    )
    resp = api_client.approve_income_certification(
        prog["id"], hh["id"], cert["id"], _insp()
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_stale_listing_version_blocks_matching():
    """PRD §2.6: "Running waitlist matching against a resale listing requires
    `expected_listing_version` matching the `ResaleListing.version`. ... If
    the value supplied does not match the parent entity's current `version`
    at the time the write is attempted, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_listing_version_blocks_matching
    """
    from test_helpers import setup_listed_resale, setup_eligible_household, create_waitlist_entry_payload

    prog = setup_program(name="P-OCC2")
    _, unit, _, _, listing = setup_listed_resale(prog["id"])
    # Add an eligible buyer so the only thing that could fail is OCC.
    hh_b, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, legal_name="Buyer"
    )
    get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh_b["id"],
            create_waitlist_entry_payload(),
            _is(),
        )
    )
    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    resp = api_client.run_matching(
        prog["id"],
        unit["id"],
        listing["id"],
        {"expected_listing_version": listing_now["version"] - 1},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
