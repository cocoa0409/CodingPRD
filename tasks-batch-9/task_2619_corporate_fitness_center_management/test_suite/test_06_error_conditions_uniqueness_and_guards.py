"""Error conditions: authentication, uniqueness scopes, integrity and state guards.

Every test below builds its own state against an empty database and drives one
request into exactly one violated rule, so no assertion here depends on an
ordering the PRD does not fix.
"""
import pytest

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, factories
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["operator_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# ==========================================================================
# Local composite setups (no shared helper covers these shapes)
# ==========================================================================
def _assert_error_envelope_meta(response):
    """Every error body carries a server-minted api_request_id in its meta."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        f"expected a non-empty meta.api_request_id on the error body, got {meta!r}"
    )


def _setup_lapsed_pending_credential():
    """A DRAFT contract whose site manager filed a CPR_AED card that expired on
    2026-07-31 — one day before the logical clock — and is still awaiting a
    verification decision.

    Returns (contract, manager, credential).
    """
    scenarios.set_clock()
    contract = scenarios.create_draft_contract()
    manager = scenarios.hire_staff(
        contract["id"],
        role_type="SITE_MANAGER",
        full_name="Dana Reed",
        hourly_cost_cents=5200,
    )
    credential = scenarios.file_credential(
        manager["id"],
        credential_type="CPR_AED",
        issuer="American Heart Association",
        credential_number="AHA-770",
        expires_on="2026-07-31",
    )
    return contract, manager, credential


def _setup_program_in_a_five_person_studio():
    """An ACTIVE contract whose only studio holds 5 people, running an ACTIVE
    offering whose per-session roster cap is the looser number 8."""
    scenario = scenarios.setup_active_contract()
    room = scenarios.add_room(scenario, room_name="Studio A", max_occupancy=5)
    scenario["room"] = room
    scenario["room_id"] = room["id"]
    aed = scenarios.add_ready_aed(scenario, room["id"])
    scenario["aed_id"] = aed["id"]
    instructor = scenarios.add_instructor(scenario)
    scenario["instructor"] = instructor["staff"]
    scenario["instructor_id"] = instructor["staff"]["id"]
    scenario["instructor_headers"] = instructor["headers"]
    offering = scenarios.add_offering(
        scenario,
        title="Lunch Circuit",
        participation_target=8,
        max_participants_per_session=8,
    )
    scenarios.activate_offering(scenario, offering["id"])
    scenario["offering"] = scenarios.read_offering(offering["id"])
    scenario["offering_id"] = offering["id"]
    return scenario


def _setup_program_with_a_second_instructor():
    """An ACTIVE programme, one scheduled session already carrying an ASSIGNED
    LEAD, and a second fully credentialed instructor with no bookings at all.

    Returns (scenario, second_instructor, session, lead_assignment).
    """
    scenario = scenarios.setup_active_program()
    second = scenarios.add_instructor(scenario, with_drill=False, full_name="Mia Chen")
    session = scenarios.schedule_session(scenario)
    lead = scenarios.assign_staff(scenario, session["id"], role_on_session="LEAD")
    return scenario, second["staff"], session, lead


def _setup_active_site_with_draft_offering():
    """An ACTIVE contract, an OPEN room, a READY defibrillator, a credentialed
    and drilled instructor, and one offering deliberately left in DRAFT."""
    scenario = scenarios.setup_active_site()
    instructor = scenarios.add_instructor(scenario)
    scenario["instructor"] = instructor["staff"]
    scenario["instructor_id"] = instructor["staff"]["id"]
    scenario["instructor_headers"] = instructor["headers"]
    offering = scenarios.add_offering(scenario, title="Lunch Circuit")
    scenario["offering"] = offering
    scenario["offering_id"] = offering["id"]
    return scenario


def _setup_contract_billed_to_its_annual_ceiling():
    """A COST_PLUS site whose annual ceiling is 6141 cents, with one completed
    55-minute session, the August invoice issued for the whole ceiling, and an
    empty September draft waiting to be issued.

    Returns (scenario, august_invoice, september_invoice).
    """
    scenario = scenarios.setup_active_program(not_to_exceed_cents=6141)
    session = scenarios.schedule_session(scenario)
    scenarios.staff_session(scenario, session["id"])
    scenarios.start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")
    scenarios.complete_session(scenario, session["id"])
    august = scenarios.draft_invoice(scenario, "2026-08")
    august = scenarios.issue_invoice(august["id"])
    scenarios.set_clock("2026-09-01T00:00:00Z")
    september = scenarios.draft_invoice(scenario, "2026-09")
    return scenario, august, september


# ==========================================================================
# Header presence and role recognition
# ==========================================================================
def test_contract_list_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is
    not one of the six role names below spelled exactly, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) — note that an unrecognised role string
    is an authentication failure, not an authorization failure."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    scenarios.set_clock()

    response = api.list_client_contracts(
        {"X-User-ID": "op-admin-1", "Content-Type": "application/json"}
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    _assert_error_envelope_meta(response)


def test_contract_list_without_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is
    not one of the six role names below spelled exactly, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) — note that an unrecognised role string
    is an authentication failure, not an authorization failure."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    scenarios.set_clock()

    response = api.list_client_contracts(
        {"X-User-Role": "OperatorAdmin", "Content-Type": "application/json"}
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    _assert_error_envelope_meta(response)


@pytest.mark.parametrize(
    "role_value",
    ["", "FacilityDirector", "operatoradmin"],
    ids=["empty_role", "undeclared_role_name", "wrong_spelling"],
)
def test_contract_list_with_unrecognised_role_is_unauthenticated(api, role_value):
    """PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is
    not one of the six role names below spelled exactly, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) — note that an unrecognised role string
    is an authentication failure, not an authorization failure."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    scenarios.set_clock()

    response = api.list_client_contracts(build_user_headers("op-admin-1", role_value))

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        "an unrecognised role string is an authentication failure, so the status "
        f"must be 401, got {response.status_code} for role {role_value!r}"
    )


def test_contract_list_with_declared_but_unlisted_role_is_unauthorized(api):
    """PRD §2.1: "When both headers are well-formed but the named role is not
    permitted to invoke the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §4: "Authorization is checked before anything else, so a caller whose
    role does not appear in the last column receives `ERR_UNAUTHORIZED`
    regardless of whether the record exists or the request body is well-formed."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    scenarios.set_clock()

    response = api.list_client_contracts(TEST_USERS["member_headers"])

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403, (
        "a well-formed Member header on an endpoint that does not list Member is "
        f"an authorization failure at 403, got {response.status_code}"
    )


# ==========================================================================
# Site-code uniqueness and its withdrawal-released scope
# ==========================================================================
def test_duplicate_site_code_on_a_second_contract_rejected(api):
    """PRD §3.1: "The operator's `site_code` must be unique across all contracts
    that have not been withdrawn; a collision is refused with
    `ERR_SITE_CODE_CONFLICT`."

    Design: Corner/errors/site_code_conflict_on_duplicate_contract_rejected
    """
    scenarios.set_clock()
    first = validate_success(
        api.create_client_contract(
            factories.client_contract_payload(
                client_name="Northwind Manufacturing", site_code="NWM-01"
            ),
            ADMIN,
        ),
        201,
    )
    assert first["site_code"] == "NWM-01", (
        f"expected the first contract to hold site_code NWM-01, got {first['site_code']!r}"
    )

    response = api.create_client_contract(
        factories.client_contract_payload(
            client_name="Northwind Logistics",
            site_code="NWM-01",
            not_to_exceed_cents=4000000,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_SITE_CODE_CONFLICT.value)
    items, meta = validate_paginated(api.list_client_contracts(ADMIN))
    assert meta["total_count"] == 1, (
        f"expected 1 contract to survive the refused duplicate, got {meta['total_count']}"
    )
    assert len(items) == 1, f"expected exactly one contract row, got {len(items)}"


def test_site_code_reused_after_the_first_contract_is_withdrawn_accepted(api):
    """PRD §3.1: "A withdrawn contract releases its `site_code` back into
    circulation."

    PRD §3.1: "A `TERMINATE` action requested against a contract still in `DRAFT`
    does not terminate it — it withdraws it, moving the contract `DRAFT →
    WITHDRAWN`."

    Design: Corner/errors/site_code_conflict_on_duplicate_contract_rejected
    """
    scenarios.set_clock()
    first = validate_success(
        api.create_client_contract(
            factories.client_contract_payload(
                client_name="Northwind Manufacturing", site_code="NWM-01"
            ),
            ADMIN,
        ),
        201,
    )
    withdrawn = validate_success(
        api.service_status(
            first["id"],
            {"action": "TERMINATE", "reason": "Replaced by a fresh paper"},
            ADMIN,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"expected TERMINATE on a DRAFT contract to withdraw it, got {withdrawn['status']!r}"
    )

    retry = validate_success(
        api.create_client_contract(
            factories.client_contract_payload(
                client_name="Northwind Logistics",
                site_code="NWM-01",
                not_to_exceed_cents=4000000,
            ),
            ADMIN,
        ),
        201,
    )

    assert retry["site_code"] == "NWM-01", (
        "the withdrawn contract released NWM-01, so the retry must hold it, got "
        f"{retry['site_code']!r}"
    )
    assert retry["status"] == "DRAFT", (
        f"a newly created contract lands in DRAFT, got {retry['status']!r}"
    )
    items, meta = validate_paginated(
        api.list_client_contracts(ADMIN, params={"status": "DRAFT"})
    )
    assert meta["total_count"] == 1, (
        "only the retry should remain in DRAFT after the withdrawal, got "
        f"{meta['total_count']}"
    )


# ==========================================================================
# Asset-tag uniqueness, scoped per contract
# ==========================================================================
def test_duplicate_asset_tag_within_one_contract_rejected(api):
    """PRD §3.3: "Each asset carries an `asset_type` of `AED`, `CARDIO`, or
    `STRENGTH`, an operator `asset_tag` that must be unique within the contract —
    a collision is refused with `ERR_ASSET_TAG_CONFLICT`, and because the scope
    is per-contract, two different sites may both carry a tag of AED-01 — and a
    `service_interval_days` preventive-maintenance interval that defaults to 90
    and must fall between 1 and 365 inclusive."

    Design: Corner/errors/asset_tag_conflict_scoped_to_one_contract_rejected
    """
    site = scenarios.setup_draft_contract()
    room = scenarios.add_room(site, room_name="Studio A")
    first_asset = scenarios.add_ready_aed(site, room["id"], asset_tag="AED-01")

    response = api.create_facility_asset(
        {
            "contract_id": site["contract_id"],
            "room_id": room["id"],
            "asset_type": "STRENGTH",
            "asset_tag": "AED-01",
        },
        site["manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ASSET_TAG_CONFLICT.value)
    items, meta = validate_paginated(
        api.list_facility_assets(ADMIN, params={"contract_id": site["contract_id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected only the original AED-01 on this contract, got {meta['total_count']}"
    )
    assert items[0]["id"] == first_asset["id"], (
        "the surviving asset must be the one registered first, got "
        f"{items[0]['id']!r} instead of {first_asset['id']!r}"
    )


def test_same_asset_tag_on_a_second_contract_accepted(api):
    """PRD §3.3: "Each asset carries an `asset_type` of `AED`, `CARDIO`, or
    `STRENGTH`, an operator `asset_tag` that must be unique within the contract —
    a collision is refused with `ERR_ASSET_TAG_CONFLICT`, and because the scope
    is per-contract, two different sites may both carry a tag of AED-01 — and a
    `service_interval_days` preventive-maintenance interval that defaults to 90
    and must fall between 1 and 365 inclusive."

    Design: Corner/errors/asset_tag_conflict_scoped_to_one_contract_rejected
    """
    first_site = scenarios.setup_draft_contract()
    first_room = scenarios.add_room(first_site, room_name="Studio A")
    scenarios.add_ready_aed(first_site, first_room["id"], asset_tag="AED-01")

    second_site = scenarios.setup_draft_contract("MANAGEMENT_FEE")
    second_room = scenarios.add_room(second_site, room_name="Studio B", max_occupancy=20)

    twin = validate_success(
        api.create_facility_asset(
            factories.aed_asset_payload(
                second_site["contract_id"], second_room["id"], asset_tag="AED-01"
            ),
            second_site["manager_headers"],
        ),
        201,
    )

    assert twin["asset_tag"] == "AED-01", (
        "the tag is unique per contract, so a second site may carry AED-01, got "
        f"{twin['asset_tag']!r}"
    )
    assert twin["contract_id"] == second_site["contract_id"], (
        "the twin asset must belong to the second contract, got "
        f"{twin['contract_id']!r}"
    )
    _, first_meta = validate_paginated(
        api.list_facility_assets(
            ADMIN, params={"contract_id": first_site["contract_id"]}
        )
    )
    assert first_meta["total_count"] == 1, (
        f"the first contract still owns exactly one asset, got {first_meta['total_count']}"
    )


# ==========================================================================
# One live lead per session
# ==========================================================================
def test_second_lead_on_a_session_that_already_has_one_rejected(api):
    """PRD §3.5: "Creating a second lead for a session that already has one in
    `ASSIGNED` or `CONFIRMED` status is refused with
    `ERR_DUPLICATE_LEAD_ASSIGNMENT`; a lead that has been released or vacated
    frees the slot for a replacement."

    Design: Corner/errors/duplicate_lead_assignment_rejected
    """
    scenario, second_instructor, session, first_lead = (
        _setup_program_with_a_second_instructor()
    )
    assert first_lead["status"] == "ASSIGNED", (
        f"the sitting lead must be live for this rule to bite, got {first_lead['status']!r}"
    )

    response = api.create_staff_assignment(
        factories.staff_assignment_payload(
            session["id"], second_instructor["id"], role_on_session="LEAD"
        ),
        scenario["manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_LEAD_ASSIGNMENT.value)
    _, meta = validate_paginated(
        api.list_staff_assignments(
            ADMIN, params={"session_id": session["id"], "role_on_session": "LEAD"}
        )
    )
    assert meta["total_count"] == 1, (
        f"the session must still carry exactly one lead, got {meta['total_count']}"
    )
    bystander = scenarios.read_staff(second_instructor["id"])
    assert bystander["committed_minutes_current_period"] == 0, (
        "a refused assignment books no labor, so the rejected instructor keeps 0 "
        f"committed minutes, got {bystander['committed_minutes_current_period']}"
    )


def test_support_assignment_alongside_a_sitting_lead_accepted(api):
    """PRD §3.5: "The distinction is not cosmetic: only a `LEAD` assignment
    satisfies a session's staffing requirement, and only one live lead may exist
    per session at a time."

    PRD §3.5: "`paid_minutes` is computed as the session's `scheduled_minutes`
    plus a setup allowance of 15 minutes when the `role_on_session` is `LEAD`, and
    simply the session's `scheduled_minutes` when it is `SUPPORT`."

    Design: Corner/errors/duplicate_lead_assignment_rejected
    """
    scenario, second_instructor, session, _first_lead = (
        _setup_program_with_a_second_instructor()
    )

    support = validate_success(
        api.create_staff_assignment(
            factories.staff_assignment_payload(
                session["id"], second_instructor["id"], role_on_session="SUPPORT"
            ),
            scenario["manager_headers"],
        ),
        201,
    )

    assert support["role_on_session"] == "SUPPORT", (
        f"expected a SUPPORT assignment, got {support['role_on_session']!r}"
    )
    assert support["status"] == "ASSIGNED", (
        f"a new assignment starts in ASSIGNED, got {support['status']!r}"
    )
    assert support["paid_minutes"] == 55, (
        "a support worker on a 55-minute session earns no setup allowance, so "
        f"paid_minutes must be 55, got {support['paid_minutes']}"
    )
    _, meta = validate_paginated(
        api.list_staff_assignments(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the session should now carry a lead and a support worker, got {meta['total_count']}"
    )


def test_replacement_lead_after_the_first_is_released_accepted(api):
    """PRD §3.5: "Creating a second lead for a session that already has one in
    `ASSIGNED` or `CONFIRMED` status is refused with
    `ERR_DUPLICATE_LEAD_ASSIGNMENT`; a lead that has been released or vacated
    frees the slot for a replacement."

    Design: Corner/errors/duplicate_lead_assignment_rejected
    """
    scenario, second_instructor, session, first_lead = (
        _setup_program_with_a_second_instructor()
    )
    released = validate_success(
        api.release_assignment(
            first_lead["id"], {"reason": "Instructor reassigned"}, ADMIN
        )
    )
    assert released["status"] == "RELEASED", (
        f"expected the sitting lead to be RELEASED, got {released['status']!r}"
    )

    replacement = validate_success(
        api.create_staff_assignment(
            factories.staff_assignment_payload(
                session["id"], second_instructor["id"], role_on_session="LEAD"
            ),
            scenario["manager_headers"],
        ),
        201,
    )

    assert replacement["role_on_session"] == "LEAD", (
        "the released lead freed the slot, so the replacement must be a LEAD, got "
        f"{replacement['role_on_session']!r}"
    )
    assert replacement["status"] == "ASSIGNED", (
        f"the replacement starts in ASSIGNED, got {replacement['status']!r}"
    )
    assert replacement["paid_minutes"] == 70, (
        "a lead on a 55-minute session carries the 15-minute setup allowance, so "
        f"paid_minutes must be 70, got {replacement['paid_minutes']}"
    )
    _, meta = validate_paginated(
        api.list_staff_assignments(
            ADMIN,
            params={
                "session_id": session["id"],
                "role_on_session": "LEAD",
                "status": "ASSIGNED",
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one live lead may sit on the session, got {meta['total_count']}"
    )


# ==========================================================================
# Physical room capacity at session creation
# ==========================================================================
def test_session_forecast_above_room_max_occupancy_rejected(api):
    """PRD §3.5: "Finally, **physical capacity**: `forecast_attendance` may not
    exceed the target room's `max_occupancy`, and an over-full forecast is refused
    with `ERR_ROOM_OCCUPANCY_EXCEEDED`."

    Design: Corner/errors/room_occupancy_exceeded_on_session_create_rejected
    """
    scenario = _setup_program_in_a_five_person_studio()

    response = api.create_program_session(
        factories.program_session_payload(
            scenario["offering_id"], scenario["room_id"], forecast_attendance=6
        ),
        scenario["manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROOM_OCCUPANCY_EXCEEDED.value)
    assert response.status_code == 422, (
        "an over-full forecast is a business-rule refusal at 422, got "
        f"{response.status_code}"
    )
    _, meta = validate_paginated(
        api.list_program_sessions(ADMIN, params={"offering_id": scenario["offering_id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused session must not be persisted, got {meta['total_count']} sessions"
    )


def test_session_forecast_exactly_at_room_max_occupancy_accepted(api):
    """PRD §3.5: "Finally, **physical capacity**: `forecast_attendance` may not
    exceed the target room's `max_occupancy`, and an over-full forecast is refused
    with `ERR_ROOM_OCCUPANCY_EXCEEDED`."

    PRD §3.4: "Multiply that numerator by 100, divide by `participation_target`,
    round half up, and store the result in `provisional_attainment_pct`."

    Design: Corner/errors/room_occupancy_exceeded_on_session_create_rejected
    """
    scenario = _setup_program_in_a_five_person_studio()

    session = validate_success(
        api.create_program_session(
            factories.program_session_payload(
                scenario["offering_id"], scenario["room_id"], forecast_attendance=5
            ),
            scenario["manager_headers"],
        ),
        201,
    )

    assert session["forecast_attendance"] == 5, (
        "a forecast equal to max_occupancy fits the room, got "
        f"{session['forecast_attendance']}"
    )
    assert session["status"] == "SCHEDULED", (
        f"a new session lands in SCHEDULED, got {session['status']!r}"
    )
    attainment = scenarios.read_attainment(scenario["offering_id"])
    assert attainment["forecast_open"] == 5, (
        "the single open session forecasts 5 attendees, got "
        f"{attainment['forecast_open']}"
    )
    assert attainment["provisional_attainment_pct"] == 63, (
        "5 forecast against a target of 8 is 62.5 percent, which rounds half up to "
        f"63, got {attainment['provisional_attainment_pct']}"
    )


# ==========================================================================
# Badge grant demands verified eligibility
# ==========================================================================
def test_badge_grant_for_a_waivered_but_unverified_member_rejected(api):
    """PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from `REVOKED`
    to `ACTIVE`, and is gated twice: the member's `eligibility_status` must be
    `ELIGIBLE`, failing which the request is refused with
    `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a liability waiver in
    `SIGNED` status whose `expires_on` falls at or after today, failing which the
    request is refused with `ERR_WAIVER_REQUIRED`."

    Design: Corner/errors/eligibility_not_verified_on_badge_grant_rejected
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(scenario, full_name="Ada Kim")
    waiver = scenarios.file_waiver(scenario, member["id"])
    assert waiver["status"] == "SIGNED", (
        "the waiver gate must be satisfied so only the eligibility gate can fail, "
        f"got waiver status {waiver['status']!r}"
    )
    assert scenarios.read_member(member["id"])["eligibility_status"] == (
        "PENDING_VERIFICATION"
    ), "the member must still be unverified for this rule to bite"

    response = api.badge_access(
        member["id"], {"action": "GRANT", "badge_number": "B-1001"},
        scenario["manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ELIGIBILITY_NOT_VERIFIED.value)
    unchanged = scenarios.read_member(member["id"])
    assert unchanged["access_status"] == "NO_BADGE", (
        f"a refused grant hands out no badge, got access_status {unchanged['access_status']!r}"
    )
    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["eligible_member_count"] == 0, (
        "no eligibility was verified, so the contract counter stays 0, got "
        f"{contract['eligible_member_count']}"
    )


def test_badge_grant_after_eligibility_verification_accepted(api):
    """PRD §3.6: "It increments the contract's `eligible_member_count` by 1 and
    leaves `access_status` completely untouched — verifying eligibility does not
    hand out a badge."

    PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from `REVOKED` to
    `ACTIVE`, and is gated twice: the member's `eligibility_status` must be
    `ELIGIBLE`, failing which the request is refused with
    `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a liability waiver in
    `SIGNED` status whose `expires_on` falls at or after today, failing which the
    request is refused with `ERR_WAIVER_REQUIRED`."

    Design: Corner/errors/eligibility_not_verified_on_badge_grant_rejected
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(scenario, full_name="Ada Kim")
    scenarios.file_waiver(scenario, member["id"])
    verified = scenarios.verify_member(scenario, member["id"])
    assert verified["eligibility_status"] == "ELIGIBLE", (
        f"expected VERIFY to make the member ELIGIBLE, got {verified['eligibility_status']!r}"
    )
    assert verified["access_status"] == "NO_BADGE", (
        "verifying eligibility hands out no badge, so access_status stays NO_BADGE, "
        f"got {verified['access_status']!r}"
    )

    granted = validate_success(
        api.badge_access(
            member["id"], {"action": "GRANT", "badge_number": "B-1001"},
            scenario["manager_headers"],
        )
    )

    assert granted["access_status"] == "ACTIVE", (
        f"the grant must activate the badge, got {granted['access_status']!r}"
    )
    assert granted["eligibility_status"] == "ELIGIBLE", (
        f"a grant leaves eligibility_status unchanged, got {granted['eligibility_status']!r}"
    )
    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["eligible_member_count"] == 1, (
        "the single verification incremented the counter to 1, got "
        f"{contract['eligible_member_count']}"
    )


# ==========================================================================
# Certification decision integrity
# ==========================================================================
def test_accepting_an_already_lapsed_credential_rejected(api):
    """PRD §3.2: "Acceptance requires the record's `expires_on` to be strictly
    later than today; accepting a card that has already lapsed is refused with
    `ERR_CREDENTIAL_EXPIRED_ON_FILE`."

    Design: Corner/errors/credential_decision_integrity_rejected
    """
    _contract, manager, credential = _setup_lapsed_pending_credential()

    response = api.verify_credential(credential["id"], {"decision": "ACCEPT"}, ADMIN)

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_EXPIRED_ON_FILE.value)
    unchanged = scenarios.read_credential(credential["id"])
    assert unchanged["status"] == "PENDING_VERIFICATION", (
        "a refused acceptance leaves the record awaiting a decision, got "
        f"{unchanged['status']!r}"
    )
    assert unchanged["verified_at"] is None, (
        f"a refused acceptance stamps nothing, got verified_at {unchanged['verified_at']!r}"
    )
    assert unchanged["verified_by_user_id"] is None, (
        "a refused acceptance names no decider, got "
        f"{unchanged['verified_by_user_id']!r}"
    )
    holder = scenarios.read_staff(manager["id"])
    assert holder["duty_status"] == "ACTIVE_DUTY", (
        f"the refused decision moves nobody off duty, got {holder['duty_status']!r}"
    )


@pytest.mark.parametrize(
    "decision_payload",
    [{"decision": "REJECT"}, {"decision": "REJECT", "rejection_reason": ""}],
    ids=["reason_omitted", "reason_empty_string"],
)
def test_rejecting_a_credential_without_a_reason_rejected(api, decision_payload):
    """PRD §3.2: "A `REJECT` moves the record `PENDING_VERIFICATION → REJECTED`
    and requires a non-empty `rejection_reason` in the payload; omitting it or
    supplying an empty string is refused with `ERR_REJECTION_REASON_REQUIRED`."

    Design: Corner/errors/credential_decision_integrity_rejected
    """
    _contract, _manager, credential = _setup_lapsed_pending_credential()

    response = api.verify_credential(credential["id"], decision_payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_REJECTION_REASON_REQUIRED.value)
    unchanged = scenarios.read_credential(credential["id"])
    assert unchanged["status"] == "PENDING_VERIFICATION", (
        "a reasonless rejection is refused, so the record stays pending, got "
        f"{unchanged['status']!r}"
    )
    assert unchanged["rejection_reason"] is None, (
        f"nothing was recorded as a reason, got {unchanged['rejection_reason']!r}"
    )


def test_renewing_a_credential_to_an_already_lapsed_date_rejected(api):
    """PRD §3.2: "The supplied `expires_on` must be strictly later than today; an
    already-lapsed renewal date is refused with `ERR_RENEWAL_DATE_INVALID`."

    Design: Corner/errors/credential_decision_integrity_rejected
    """
    _contract, _manager, credential = _setup_lapsed_pending_credential()
    rejected = validate_success(
        api.verify_credential(
            credential["id"],
            {"decision": "REJECT", "rejection_reason": "Card photocopy illegible"},
            ADMIN,
        )
    )
    assert rejected["status"] == "REJECTED", (
        f"the renewal path starts from REJECTED, got {rejected['status']!r}"
    )

    response = api.renew_credential(
        credential["id"],
        {"credential_number": "AHA-771", "expires_on": "2026-07-01"},
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_RENEWAL_DATE_INVALID.value)
    unchanged = scenarios.read_credential(credential["id"])
    assert unchanged["status"] == "REJECTED", (
        f"a refused renewal leaves the record REJECTED, got {unchanged['status']!r}"
    )
    assert unchanged["credential_number"] == "AHA-770", (
        "a refused renewal overwrites nothing, so the old number survives, got "
        f"{unchanged['credential_number']!r}"
    )
    assert unchanged["expires_on"] == "2026-07-31", (
        f"a refused renewal leaves expires_on alone, got {unchanged['expires_on']!r}"
    )
    assert unchanged["renewal_count"] == 0, (
        f"a refused renewal counts no lap, got renewal_count {unchanged['renewal_count']}"
    )


def test_renewing_a_credential_to_a_future_date_accepted(api):
    """PRD §3.2: "Renewal overwrites `expires_on` and `credential_number` with the
    supplied values, clears `verified_at` and `verified_by_user_id` back to null,
    and — when the record was coming out of `REJECTED` — clears `rejection_reason`
    back to null as well."

    Design: Corner/errors/credential_decision_integrity_rejected
    """
    _contract, _manager, credential = _setup_lapsed_pending_credential()
    validate_success(
        api.verify_credential(
            credential["id"],
            {"decision": "REJECT", "rejection_reason": "Card photocopy illegible"},
            ADMIN,
        )
    )

    renewed = validate_success(
        api.renew_credential(
            credential["id"],
            {"credential_number": "AHA-771", "expires_on": "2028-06-30"},
            ADMIN,
        )
    )

    assert renewed["status"] == "PENDING_VERIFICATION", (
        f"renewal sends the card back around the loop, got {renewed['status']!r}"
    )
    assert renewed["credential_number"] == "AHA-771", (
        f"renewal overwrites the certificate number, got {renewed['credential_number']!r}"
    )
    assert renewed["expires_on"] == "2028-06-30", (
        f"renewal overwrites the expiry date, got {renewed['expires_on']!r}"
    )
    assert renewed["renewal_count"] == 1, (
        f"renewal counts one lap around the loop, got {renewed['renewal_count']}"
    )
    assert renewed["rejection_reason"] is None, (
        "coming out of REJECTED clears the reason, got "
        f"{renewed['rejection_reason']!r}"
    )
    assert renewed["verified_at"] is None, (
        f"renewal clears verified_at, got {renewed['verified_at']!r}"
    )


# ==========================================================================
# Contract and offering state guards
# ==========================================================================
def test_client_decision_on_an_already_active_contract_rejected(api):
    """PRD §3.1: "A decision rendered against a contract that is not in
    `PENDING_CLIENT_APPROVAL` is refused with `ERR_CONTRACT_NOT_PENDING`, and only
    the sponsor of that very contract may render it."

    Design: Corner/errors/contract_and_offering_state_guards_rejected
    """
    scenario = scenarios.setup_active_contract()
    assert scenario["contract"]["status"] == "ACTIVE", (
        f"the guard needs a contract past approval, got {scenario['contract']['status']!r}"
    )
    approved_at = scenario["contract"]["approved_at"]

    response = api.client_decision(
        scenario["contract_id"],
        {"decision": "APPROVE", "comment": "Approving again"},
        scenario["sponsor_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_PENDING.value)
    unchanged = scenarios.read_contract(scenario["contract_id"])
    assert unchanged["status"] == "ACTIVE", (
        f"a refused decision moves nothing, got status {unchanged['status']!r}"
    )
    assert unchanged["approved_at"] == approved_at, (
        "a refused decision re-stamps no approval instant, got "
        f"{unchanged['approved_at']!r} instead of {approved_at!r}"
    )
    assert unchanged["revision_round"] == 0, (
        f"a refused decision counts no revision, got {unchanged['revision_round']}"
    )


def test_session_scheduled_against_a_draft_offering_rejected(api):
    """PRD §3.5: "The owning contract must be `ACTIVE` and the offering must be in
    a status that accepts new bookings, failing which the caller sees
    `ERR_CONTRACT_NOT_ACTIVE` or `ERR_OFFERING_NOT_ACTIVE`."

    PRD §3.4: "A pause requested on an offering that is not `ACTIVE`, or a resume
    requested on one that is not `PAUSED`, is refused with
    `ERR_OFFERING_NOT_ACTIVE` — the same error a caller receives when trying to
    schedule a session against an offering that is not in a status permitting new
    bookings."

    Design: Corner/errors/contract_and_offering_state_guards_rejected
    """
    scenario = _setup_active_site_with_draft_offering()
    assert scenario["offering"]["status"] == "DRAFT", (
        f"the offering must still be a draft, got {scenario['offering']['status']!r}"
    )

    response = api.create_program_session(
        factories.program_session_payload(
            scenario["offering_id"], scenario["room_id"], forecast_attendance=3
        ),
        scenario["manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_OFFERING_NOT_ACTIVE.value)
    _, meta = validate_paginated(
        api.list_program_sessions(ADMIN, params={"offering_id": scenario["offering_id"]})
    )
    assert meta["total_count"] == 0, (
        f"a draft offering holds no sessions, got {meta['total_count']}"
    )


def test_offering_activation_while_the_contract_is_suspended_rejected(api):
    """PRD §3.4: "Five conditions must all hold: the owning contract must be
    `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`); the lead's `duty_status` must
    be `ACTIVE_DUTY`; the lead must hold a certification record of the offering's
    `required_credential_type` in either `VERIFIED` or `EXPIRING_SOON` status
    (otherwise `ERR_CREDENTIAL_NOT_VERIFIED`); the lead's `readiness_index` must be
    at least 70 (otherwise `ERR_READINESS_BELOW_THRESHOLD`); and the site must have
    at least one `READY` defibrillator (otherwise `ERR_AED_NOT_READY`)."

    Design: Corner/errors/contract_and_offering_state_guards_rejected
    """
    scenario = _setup_active_site_with_draft_offering()
    suspended = validate_success(
        api.service_status(
            scenario["contract_id"],
            {"action": "SUSPEND", "reason": "Client paused the site"},
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        f"expected the contract to be SUSPENDED, got {suspended['status']!r}"
    )
    lead = scenarios.read_staff(scenario["instructor_id"])
    assert lead["duty_status"] == "ACTIVE_DUTY", (
        "only the contract condition may fail here, so the lead must stay on duty, "
        f"got {lead['duty_status']!r}"
    )
    assert lead["readiness_index"] >= 70, (
        "only the contract condition may fail here, so readiness must clear the "
        f"threshold, got {lead['readiness_index']}"
    )

    response = api.offering_status_change(
        scenario["offering_id"], {"action": "ACTIVATE"}, scenario["manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    unchanged = scenarios.read_offering(scenario["offering_id"])
    assert unchanged["status"] == "DRAFT", (
        f"the refused activation leaves the offering in DRAFT, got {unchanged['status']!r}"
    )


# ==========================================================================
# Invoice and incident state guards
# ==========================================================================
def test_issuing_an_invoice_that_is_already_issued_rejected(api):
    """PRD §3.9: "Issuing anything that is not in `DRAFT` is refused with
    `ERR_INVOICE_NOT_DRAFT`."

    PRD §3.9: "**Issuing** moves the invoice `DRAFT → ISSUED`, stamps `issued_at`,
    and adds `net_amount_cents` to the contract's `ytd_billed_cents`."

    Design: Corner/errors/invoice_and_incident_state_guards_rejected
    """
    scenario = scenarios.setup_active_contract("MANAGEMENT_FEE")
    invoice = scenarios.draft_invoice(scenario, "2026-08")
    issued = scenarios.issue_invoice(invoice["id"])
    assert issued["status"] == "ISSUED", (
        f"the first issue must succeed, got {issued['status']!r}"
    )
    stamped_at = issued["issued_at"]
    ytd_after_first_issue = scenarios.read_contract(scenario["contract_id"])[
        "ytd_billed_cents"
    ]

    response = api.issue_invoice(invoice["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_INVOICE_NOT_DRAFT.value)
    unchanged = scenarios.read_invoice(invoice["id"])
    assert unchanged["status"] == "ISSUED", (
        f"the refused replay leaves the invoice ISSUED, got {unchanged['status']!r}"
    )
    assert unchanged["issued_at"] == stamped_at, (
        "the refused replay must not re-stamp issued_at, got "
        f"{unchanged['issued_at']!r} instead of {stamped_at!r}"
    )
    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["ytd_billed_cents"] == ytd_after_first_issue, (
        "the refused replay must not bill the net twice, got "
        f"{contract['ytd_billed_cents']} instead of {ytd_after_first_issue}"
    )


def test_filing_a_claim_on_an_unreviewed_incident_rejected(api):
    """PRD §3.8: "Attempting to return, to file a claim, or to close-without-claim
    on a report that is not in `UNDER_REVIEW` is refused with
    `ERR_INCIDENT_NOT_UNDER_REVIEW`; note that both the state check and the
    terminal check outrank the claim-subject check, so a closed report on which
    somebody tries to file a claim reports its state problem rather than its
    missing subject."

    Design: Corner/errors/invoice_and_incident_state_guards_rejected
    """
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(scenario, full_name="Ada Kim")
    scenarios.file_waiver(scenario, member["id"])
    incident = scenarios.file_incident(
        scenario,
        reported_by_staff_id=scenario["manager_id"],
        member_id=member["id"],
        severity="MODERATE",
        cause_category="SLIP_FALL",
    )
    assert incident["status"] == "REPORTED", (
        f"a fresh report lands in REPORTED, got {incident['status']!r}"
    )

    response = api.file_claim(
        incident["id"], {"claim_reference": "CLM-2026-0001"}, AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_INCIDENT_NOT_UNDER_REVIEW.value)
    unchanged = scenarios.read_incident(incident["id"])
    assert unchanged["status"] == "REPORTED", (
        f"the refused claim moves nothing, got {unchanged['status']!r}"
    )
    assert unchanged["claim_reference"] is None, (
        f"the refused claim stores no reference, got {unchanged['claim_reference']!r}"
    )
    assert unchanged["reviewed_by_user_id"] is None, (
        "the report was never reviewed, so no reviewer is recorded, got "
        f"{unchanged['reviewed_by_user_id']!r}"
    )


# ==========================================================================
# The annual ceiling at issue time
# ==========================================================================
def test_issuing_against_an_exhausted_annual_ceiling_rejected(api):
    """PRD §3.9: "For a cost-plus contract it also refuses outright when the
    annual ceiling is already exhausted: if `not_to_exceed_cents` less
    `ytd_billed_cents` leaves no positive headroom, the net would clip to zero and
    the request is refused with `ERR_NTE_EXHAUSTED` rather than issuing a
    zero-value invoice."

    Design: Corner/errors/nte_exhausted_at_issue_rejected
    """
    scenario, _august, september = _setup_contract_billed_to_its_annual_ceiling()
    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["ytd_billed_cents"] == 6141, (
        "the August issue consumed the whole 6141-cent ceiling, got "
        f"{contract['ytd_billed_cents']}"
    )

    response = api.issue_invoice(september["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_NTE_EXHAUSTED.value)
    unchanged = scenarios.read_invoice(september["id"])
    assert unchanged["status"] == "DRAFT", (
        f"the refused issue leaves September in DRAFT, got {unchanged['status']!r}"
    )
    assert unchanged["issued_at"] is None, (
        f"the refused issue stamps nothing, got issued_at {unchanged['issued_at']!r}"
    )
    after = scenarios.read_contract(scenario["contract_id"])
    assert after["ytd_billed_cents"] == 6141, (
        "the refused issue bills nothing further, got "
        f"{after['ytd_billed_cents']}"
    )


def test_invoice_issued_exactly_at_the_annual_ceiling_is_not_capped(api):
    """PRD §3.9: "If the provisional net exceeds that headroom,
    `net_amount_cents` is set to the headroom and `nte_capped` is set to true;
    otherwise `net_amount_cents` is the provisional net and `nte_capped` is false."

    Design: Corner/errors/nte_exhausted_at_issue_rejected
    """
    scenario, august, _september = _setup_contract_billed_to_its_annual_ceiling()

    assert august["status"] == "ISSUED", (
        f"the August invoice must have issued cleanly, got {august['status']!r}"
    )
    assert august["net_amount_cents"] == 6141, (
        "the period's provisional net of 6141 exactly equals the headroom, got "
        f"{august['net_amount_cents']}"
    )
    assert august["nte_capped"] is False, (
        "a net equal to — not above — the headroom is not a capped net, got "
        f"nte_capped {august['nte_capped']!r}"
    )
    assert august["issued_at"] is not None, (
        "issuing stamps issued_at, got null"
    )
    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["ytd_billed_cents"] == 6141, (
        "issuing adds the net to the year-to-date total, got "
        f"{contract['ytd_billed_cents']}"
    )
