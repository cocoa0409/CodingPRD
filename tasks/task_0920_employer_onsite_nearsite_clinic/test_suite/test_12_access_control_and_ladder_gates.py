"""Authentication, role lists, identity scope and the two high ladder gates."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_member,
    api_client,
    create_employer_payload,
    finalize_period,
    headers_without_identity,
    make_clinician_headers,
    make_employer_admin_headers,
    make_navigator_headers,
    make_participant_headers,
    new_employer,
    read_site,
    read_visit,
    set_clock,
    setup_clinic,
    setup_completed_visit,
    site_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


def test_request_without_identity_headers_is_unauthenticated():
    """PRD §2.1: "Every request to this API carries two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the capacity in which the caller
    is acting. If either header is absent, or if `X-User-Role` is not one of the seven
    role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` and
    HTTP 401. No endpoint is anonymous, including the logical-clock endpoint."

    Design: Corner/errors/request_without_identity_headers_returns_unauthenticated
    """
    response = api_client.get_employer(NON_EXISTENT_UUID, headers_without_identity())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.status_code not in (403, 404), (
        "rung 1 fires before the role list and before existence"
    )


def test_participant_role_cannot_create_an_employer():
    """PRD §2.1: "Each endpoint in §4 lists the roles permitted to invoke it; a caller
    whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §2.6: "The acting role appears in the target endpoint's authorized-role list
    in §4. Otherwise `ERR_FORBIDDEN_ROLE`, HTTP 403. Applies to every endpoint."

    Design: Corner/errors/participant_role_forbidden_from_creating_employers
    """
    payload = create_employer_payload(legal_name="Sneaky Co", employer_code="SNK")
    response = api_client.create_employer(
        payload, make_participant_headers("0a55cbe4-8b0a-4a5f-9c19-2f11d7e64d10")
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    lookup = api_client.list_sites(ADMIN)
    assert lookup.status_code == 200, "the platform must still be usable afterwards"


def test_participant_cannot_book_for_another_participant():
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the
    acting `Participant`. Ownership checks on any resource that references a
    `Participant` compare the resource's `participant_id` to `X-User-ID`, so a member
    may book, reschedule, cancel, self-attest and request alternatives only for itself."
    PRD §2.1: "A caller that presents a recognised role and is routed to an endpoint
    its role may use, but then acts outside the scope its identity grants — a
    `Participant` operating on another participant's record, an
    `EmployerBenefitsAdmin` operating on another employer's record, a `Clinician`
    whose backing `Provider` carries `provider_function` of `NAVIGATOR`, or a
    `CareNavigator` whose backing `Provider` carries `provider_function` of
    `CLINICIAN` — is rejected with `ERR_SCOPE_VIOLATION` and HTTP 403."

    Design: Corner/rbac/participant_cannot_book_an_appointment_for_another_participant
    """
    world = setup_clinic(
        employer={"legal_name": "Scope Co", "employer_code": "SCP"},
        site={"site_name": "SCP Clinic"},
        eligibility={"subscriber_external_id": "S-5101", "member_external_id": "M-5101"},
        participant={"display_name": "Owner One"},
    )
    intruder = add_member(world, "5102", display_name="Intruder Two")
    intruder_headers = make_participant_headers(intruder["id"])

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T09:00:00Z",
            "expected_site_version": site_version(world.site_id, intruder_headers),
        },
        intruder_headers,
    )
    validate_error(response, ApiErrorId.ERR_SCOPE_VIOLATION.value, 403)

    _, meta = validate_paginated(
        api_client.list_appointments(
            world.participant_headers, params={"participant_id": world.participant_id}
        )
    )
    assert meta["total_count"] == 0
    assert read_site(world.site_id)["slots_requested_total"] == 0


def test_employer_side_read_of_unknown_visit_hits_the_wall():
    """PRD §2.7: "An employer-side role reaching any of those eight is refused with
    `ERR_CONFIDENTIALITY_WALL` and HTTP 403. The check runs **before** the path
    identifier is resolved, so a walled read of an identifier that does not exist also
    returns the wall error rather than a not-found error — the whole point of placing
    the rung this high is that the shape of the answer must not vary with whether the
    record exists."

    Design: Difficulty/priority_pair_validation_conflict/confidentiality_wall_preempts_not_found_on_unknown_visit_id
    """
    employer = new_employer(legal_name="Wall Co", employer_code="WAL")
    unknown_visit_id = "1f0f2a4c-8d2b-4c31-9f77-6b3a91d0c5e1"

    response = api_client.get_visit(
        unknown_visit_id, make_employer_admin_headers(employer["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONFIDENTIALITY_WALL.value, 403)

    body = response.json()
    assert "encounter_status" not in body["data"]
    assert "disclosure_status" not in body["data"]


def test_program_admin_read_of_the_same_unknown_visit_is_not_found():
    """PRD §2.7: "It follows that `ERR_VISIT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`
    and `ERR_REFERRAL_NOT_FOUND` are reachable only by callers that are not
    employer-side."
    PRD §2.1: "`ProgramAdmin` belongs to neither group: it is the platform operator,
    it is never subject to the confidentiality wall, and it receives reporting figures
    unsuppressed."

    Design: Difficulty/priority_pair_validation_conflict/confidentiality_wall_preempts_not_found_on_unknown_visit_id
    """
    new_employer(legal_name="Wall Co", employer_code="WAL")
    unknown_visit_id = "1f0f2a4c-8d2b-4c31-9f77-6b3a91d0c5e1"

    response = api_client.get_visit(unknown_visit_id, ADMIN)
    validate_error(response, ApiErrorId.ERR_VISIT_NOT_FOUND.value, 404)

    body = response.json()
    assert "visit_type" not in body["data"]


def test_clinic_side_roles_see_real_not_found_codes_for_clinical_ids():
    """PRD §2.7: "That separation is enforced at rung 3 of the ladder, above existence
    and above scope, and it applies to the two employer-side roles —
    `EmployerBenefitsAdmin` and `PayrollProcessor` — and to no other role."
    PRD §2.6: "Every identifier in the path exists, resolved left to right, and then
    every foreign-key identifier in the body exists. Otherwise the matching 404:
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PERIOD_NOT_FOUND`, or `ERR_RESOURCE_NOT_FOUND` for an `EligibilityRecord`,
    `VendorContract`, `StaffingShift` or `AlternativeStandard` identifier."

    Design: Corner/entities/clinical_ids_not_found_for_clinic_side_roles
    """
    world = setup_clinic(
        employer={"legal_name": "Clinic NF Co", "employer_code": "CNF"},
        site={"site_name": "CNF Clinic"},
        contract=False,
        shift=False,
        with_navigator=True,
        participant=False,
    )
    clinician_headers = make_clinician_headers(world.clinician_id)
    navigator_headers = make_navigator_headers(world.navigator_id)

    validate_error(
        api_client.get_health_assessment(
            "77777777-7777-4777-8777-777777777777", clinician_headers
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_referral(
            "88888888-8888-4888-8888-888888888888", navigator_headers
        ),
        ApiErrorId.ERR_REFERRAL_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_alternative_standard(
            "99999999-9999-4999-8999-999999999999", navigator_headers
        ),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
        404,
    )


def _frozen_visit_world():
    """A COMPLETED visit dated inside a period that is finalized afterwards."""
    world = setup_completed_visit(
        visit_type="PRIMARY_CARE",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T10:00:00Z",
        employer={"legal_name": "Freeze Co", "employer_code": "FRZ"},
        site={"site_name": "FRZ On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1201", "member_external_id": "M-1201"},
        participant={"display_name": "Nia Fox"},
        reporting_period={},
        completion={"clinical_note": "Routine"},
    )
    world.visit_version_at_completion = world.visit["version"]
    set_clock("2026-07-01T00:00:00Z")
    finalize_period(world.period_id)
    return world


def test_period_freeze_preempts_the_invalid_enum_on_amendment():
    """PRD §2.6: "Rung 6, the reporting-period freeze, sits above payload
    well-formedness (rung 7), enum membership (rung 8), optimistic concurrency
    (rung 9), state (rung 10) and every business rung, so a malformed amendment of a
    visit dated inside a finalized period reports the freeze, not the malformed body."
    PRD §2.8: "If any `ReportingPeriod` of the relevant employer whose `status` is
    `FINALIZED` or `CLOSED` contains the governing date within its closed span from
    `period_start` through `period_end`, the write is refused with
    `ERR_PERIOD_FINALIZED` and HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_preempts_invalid_enum_on_visit_amend
    """
    world = _frozen_visit_world()

    response = api_client.amend_visit(
        world.visit_id,
        {
            "expected_visit_version": world.visit_version_at_completion,
            "fitness_conclusion": "TOTALLY_FINE",
        },
        world.clinician_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_PERIOD_FINALIZED.value, 409)
    assert error["error_id"] not in (
        ApiErrorId.ERR_INVALID_ENUM.value,
        ApiErrorId.ERR_STALE_VERSION.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_finalized_period_locks_the_visit_and_amendment_count_stays_zero():
    """PRD §3.5: "**Locking** is the terminal state of the clinical axis and it is
    never requested directly. When a reporting period is finalized, every visit of
    that employer whose `service_date` falls inside the period's closed span and whose
    `encounter_status` is `COMPLETED` or `AMENDED` moves to `LOCKED`; §3.9 describes
    what that locking sets in motion."
    PRD §2.4: "A request that is rejected by any rung of the validation ladder writes
    nothing at all — no counters move, no cascade fires, no `version` advances, and no
    partial state survives the rejection."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_preempts_invalid_enum_on_visit_amend
    """
    world = _frozen_visit_world()

    locked = read_visit(world.visit_id, world.clinician_id)
    assert locked["encounter_status"] == "LOCKED"
    assert locked["amendment_count"] == 0

    api_client.amend_visit(
        world.visit_id,
        {
            "expected_visit_version": world.visit_version_at_completion,
            "fitness_conclusion": "TOTALLY_FINE",
        },
        world.clinician_headers,
    )

    after = read_visit(world.visit_id, world.clinician_id)
    assert after["encounter_status"] == "LOCKED"
    assert after["amendment_count"] == 0
    assert after["version"] == locked["version"], "the refused amendment wrote nothing"

    period = validate_success(
        api_client.get_reporting_period(world.period_id, ADMIN)
    )
    assert period["status"] == "FINALIZED"
