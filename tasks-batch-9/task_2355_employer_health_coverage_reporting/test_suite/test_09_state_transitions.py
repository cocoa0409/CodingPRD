"""State transitions: season closure, agency-error resolution, employment events,
transmittal initial state and consent grant replay.

Every test rebuilds its own world through the PRD's own endpoints, because the
harness empties the database before each test.
"""

from test_helpers import (
    BENEFITS_ADMIN_USER_ID,
    PREPARER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assert_controlled_group,
    assert_employee,
    assert_employment_event,
    assert_fields,
    assert_filing_season,
    assert_form_1095c,
    assert_furnishing_consent,
    assert_group_member,
    assert_transmittal,
    assert_transmittal_error,
    factories,
    fixtures,
    get_success_data,
    make_employee_self_service_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["compliance_officer"]
BA = TEST_USERS["benefits_admin"]
PREPARER = TEST_USERS["preparer"]


# ---------------------------------------------------------------------------
# Composite worlds built from test_helpers.fixtures
# ---------------------------------------------------------------------------
def _determined_member_with_employee(api, full_name="Lena Ortiz"):
    """Season -> controlled group -> one MONTHLY member with twelve prior-year
    headcounts -> aggregated determination -> one employee hired before the
    reporting year."""
    return fixtures.determined_ale_group_with_employee(
        api, employee_overrides={"full_name": full_name}
    )


def _member_with_accepted_original(api, receipt_id="AIR-2026-1001"):
    """The determined member's only statement carried all the way to a clean
    agency acceptance: generate -> open -> attach -> build -> transmit ->
    ``ACCEPTED`` response, so nothing is outstanding."""
    ctx = _determined_member_with_employee(api)
    ctx["form"] = fixtures.generate_form(api, ctx["employee"]["id"])
    ctx["transmittal"] = fixtures.accepted_transmittal_with_forms(
        api,
        ctx["member"]["id"],
        [ctx["form"]["id"]],
        channel="ELECTRONIC",
        receipt_id=receipt_id,
    )
    return ctx


def _member_with_errored_original(api, receipt_id="AIR-2026-1003"):
    """The determined member's only statement filed and answered with one
    ``ERROR``-severity agency error naming it. The statement is deliberately left
    undelivered, so no redelivery flag is raised."""
    ctx = _determined_member_with_employee(api)
    ctx["form"] = fixtures.generate_form(api, ctx["employee"]["id"])
    built = fixtures.built_transmittal_with_forms(
        api, ctx["member"]["id"], [ctx["form"]["id"]]
    )
    fixtures.transmit_transmittal(api, built["id"], "ELECTRONIC")
    ctx["transmittal"] = fixtures.record_agency_response(
        api,
        built["id"],
        "ACCEPTED_WITH_ERRORS",
        receipt_id,
        errors=[factories.agency_error_row(ctx["form"]["id"])],
    )
    rows, _ = validate_paginated(
        api.list_transmittal_errors(PREPARER, params={"transmittal_id": built["id"]})
    )
    assert len(rows) == 1, f"expected one agency error row, got {len(rows)}"
    ctx["error"] = rows[0]
    return ctx


# ---------------------------------------------------------------------------
# Closing the season
# ---------------------------------------------------------------------------
def test_lock_moves_season_open_to_locked_and_cascades_group(api, compliance_officer_headers):
    """PRD §2.10: "Locking sets `locked_at` from the logical clock and cascades:
    every controlled group of the season sitting in `DETERMINED_ALE` or
    `DETERMINED_NON_ALE` moves to `LOCKED`, after which no further determination,
    form generation or transmission is accepted for that group."

    Design: Corner/State Machines/season_lock_transitions_open_to_locked
    """
    ctx = _member_with_accepted_original(api)

    response = api.lock_filing_season(ctx["season"]["id"], compliance_officer_headers)
    validate_success(response, 200)

    season = fixtures.read_season(api, ctx["season"]["id"])
    assert_filing_season(season, status="LOCKED")
    assert season["locked_at"] is not None, (
        "locking must stamp locked_at from the logical clock, got null"
    )

    group = fixtures.read_group(api, ctx["group"]["id"])
    assert_controlled_group(group, determination_state="LOCKED")


def test_lock_succeeds_once_the_only_transmittal_has_settled_accepted(api, compliance_officer_headers):
    """PRD §3.8: "The season must still be `OPEN`, its `open_correction_count`
    must be zero — meaning no group of the season sits in `CORRECTION_OPEN` — and
    every transmittal of every `ACTIVE` member of every group of the season must
    have settled into `ACCEPTED` or `SUPERSEDED`."
    PRD §3.8: "A clean acceptance requires the `errors` array to be empty; it
    records the receipt identifier, moves every attached statement
    `PENDING_FILING` → `FILED_ACCEPTED`, and clears the member's
    `open_transmittal_id`."

    Design: Corner/State Machines/season_lock_transitions_open_to_locked
    """
    ctx = _member_with_accepted_original(api)

    transmittal = fixtures.read_transmittal(api, ctx["transmittal"]["id"])
    assert_transmittal(transmittal, status="ACCEPTED")

    member = fixtures.read_member(api, ctx["member"]["id"])
    assert_group_member(member, open_transmittal_id=None)

    form = fixtures.read_form(api, ctx["form"]["id"])
    assert_form_1095c(form, filing_status="FILED_ACCEPTED")

    validate_success(
        api.lock_filing_season(ctx["season"]["id"], compliance_officer_headers), 200
    )


def test_lock_rejected_while_a_second_transmittal_is_still_draft(api, compliance_officer_headers):
    """PRD §3.8: "The season must still be `OPEN`, its `open_correction_count`
    must be zero — meaning no group of the season sits in `CORRECTION_OPEN` — and
    every transmittal of every `ACTIVE` member of every group of the season must
    have settled into `ACCEPTED` or `SUPERSEDED`. A season failing either of the
    latter two conditions answers `ERR_SEASON_NOT_LOCKABLE`."

    Design: Corner/State Machines/season_lock_blocked_by_draft_transmittal
    """
    ctx = _member_with_accepted_original(api, receipt_id="AIR-2026-1002")

    second_employee = fixtures.create_employee(api, ctx["member"]["id"], "Marco Diaz")
    second_form = fixtures.generate_form(api, second_employee["id"])
    draft = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(api, draft["id"], [second_form["id"]])
    assert_transmittal(
        fixtures.read_transmittal(api, draft["id"]), status="DRAFT"
    )

    response = api.lock_filing_season(ctx["season"]["id"], compliance_officer_headers)
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_LOCKABLE, 409)

    season = fixtures.read_season(api, ctx["season"]["id"])
    assert_filing_season(season, status="OPEN", locked_at=None, open_correction_count=0)


def test_lock_rejection_leaves_no_partial_group_cascade(api, compliance_officer_headers):
    """PRD §2.10: "Locking sets `locked_at` from the logical clock and cascades:
    every controlled group of the season sitting in `DETERMINED_ALE` or
    `DETERMINED_NON_ALE` moves to `LOCKED`, after which no further determination,
    form generation or transmission is accepted for that group."
    PRD §3.8: "A season failing either of the latter two conditions answers
    `ERR_SEASON_NOT_LOCKABLE`."

    Design: Corner/State Machines/season_lock_blocked_by_draft_transmittal
    """
    ctx = _member_with_accepted_original(api, receipt_id="AIR-2026-1002")

    second_employee = fixtures.create_employee(api, ctx["member"]["id"], "Marco Diaz")
    second_form = fixtures.generate_form(api, second_employee["id"])
    draft = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(api, draft["id"], [second_form["id"]])

    validate_error(
        api.lock_filing_season(ctx["season"]["id"], compliance_officer_headers),
        ApiErrorId.ERR_SEASON_NOT_LOCKABLE,
        409,
    )

    group = fixtures.read_group(api, ctx["group"]["id"])
    assert_controlled_group(group, determination_state="DETERMINED_ALE")


def test_locked_season_refuses_form_generation_for_a_later_employee(api, preparer_headers):
    """PRD §2.6: "The governing filing season is `OPEN` — `ERR_SEASON_LOCKED`
    (409), on ale-determination, reopen, form generation, regenerate, furnish,
    transmittal creation, attach-forms, detach-form, build and transmit."
    PRD §2.10: "once its `status` is `LOCKED` no filing or furnishing write is
    accepted anywhere beneath it, and there is no unlock — `LOCKED` is terminal."

    Design: Corner/State Machines/locked_season_blocks_form_generation
    """
    ctx = _member_with_accepted_original(api, receipt_id="AIR-2026-1004")
    second_employee = fixtures.create_employee(api, ctx["member"]["id"], "Marco Diaz")
    validate_success(api.lock_filing_season(ctx["season"]["id"], CO), 200)

    response = api.create_form_1095c(
        factories.form_1095c_payload(second_employee["id"]), preparer_headers
    )
    validate_error(response, ApiErrorId.ERR_SEASON_LOCKED, 409)

    rows, meta = validate_paginated(
        api.list_forms_1095c(PREPARER, params={"employee_id": second_employee["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no statement may exist for the employee, got {meta['total_count']}"
    )
    assert rows == [], "the refused generation must create no statement"


def test_locked_season_stays_locked_and_form_counters_untouched(api, preparer_headers):
    """PRD §2.10: "once its `status` is `LOCKED` no filing or furnishing write is
    accepted anywhere beneath it, and there is no unlock — `LOCKED` is terminal."
    PRD §3.6: "Generation also requires the employee's controlled group to be in
    `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
    `generated_form_count` and `unattached_form_count`."

    Design: Corner/State Machines/locked_season_blocks_form_generation
    """
    ctx = _member_with_accepted_original(api, receipt_id="AIR-2026-1004")
    second_employee = fixtures.create_employee(api, ctx["member"]["id"], "Marco Diaz")
    validate_success(api.lock_filing_season(ctx["season"]["id"], CO), 200)

    validate_error(
        api.create_form_1095c(
            factories.form_1095c_payload(second_employee["id"]), preparer_headers
        ),
        ApiErrorId.ERR_SEASON_LOCKED,
        409,
    )

    season = fixtures.read_season(api, ctx["season"]["id"])
    assert_filing_season(season, status="LOCKED")

    member = fixtures.read_member(api, ctx["member"]["id"])
    assert_group_member(member, generated_form_count=1)


# ---------------------------------------------------------------------------
# Resolving an agency error by correcting the statement
# ---------------------------------------------------------------------------
def test_resolve_correct_form_moves_error_open_to_corrected(api, preparer_headers):
    """PRD §3.8: "`CORRECT_FORM` requires the error row to be `OPEN`, to name a
    form through `form_1095c_id`, and to belong to a transmittal in
    `ACCEPTED_WITH_ERRORS`, `PARTIALLY_ACCEPTED` or `CORRECTION_REQUIRED`; it
    moves the error `OPEN` → `CORRECTED`, creates a statement with `form_type`
    of `CORRECTED` whose `corrected_from_form_id` is the named form, records that
    new statement in the error's `corrected_form_id`, stamps
    `resolved_by_user_id` and `resolution_note`, moves the named statement
    `FILED_WITH_ERRORS` → `CORRECTION_DRAFTED`, decrements the transmittal's
    `open_error_count`, and increments the group's `open_correction_count`,
    moving a `DETERMINED_ALE` group to `CORRECTION_OPEN`."

    Design: Corner/State Machines/resolve_correct_form_drafts_correction_and_closes_error
    """
    ctx = _member_with_errored_original(api)

    response = api.resolve_transmittal_error(
        ctx["error"]["id"],
        factories.resolve_error_payload(
            "CORRECT_FORM", resolution_note="SSN corrected from payroll record"
        ),
        preparer_headers,
    )
    validate_success(response, 200)

    error_row = get_success_data(
        api.get_transmittal_error(ctx["error"]["id"], PREPARER)
    )
    assert_transmittal_error(
        error_row,
        resolution_status="CORRECTED",
        resolution_note="SSN corrected from payroll record",
        resolved_by_user_id=PREPARER_USER_ID,
    )
    assert error_row["corrected_form_id"] is not None, (
        "resolving by correction must record the new statement in corrected_form_id"
    )


def test_resolve_correct_form_creates_one_corrected_statement(api, preparer_headers):
    """PRD §3.8: "it moves the error `OPEN` → `CORRECTED`, creates a statement
    with `form_type` of `CORRECTED` whose `corrected_from_form_id` is the named
    form, records that new statement in the error's `corrected_form_id`, stamps
    `resolved_by_user_id` and `resolution_note`, moves the named statement
    `FILED_WITH_ERRORS` → `CORRECTION_DRAFTED`, decrements the transmittal's
    `open_error_count`, and increments the group's `open_correction_count`,
    moving a `DETERMINED_ALE` group to `CORRECTION_OPEN`."
    PRD §2.5: "a correction form is only discoverable by filtering forms on
    `corrected_from_form_id`."

    Design: Corner/State Machines/resolve_correct_form_drafts_correction_and_closes_error
    """
    ctx = _member_with_errored_original(api)

    validate_success(
        api.resolve_transmittal_error(
            ctx["error"]["id"],
            factories.resolve_error_payload(
                "CORRECT_FORM", resolution_note="SSN corrected from payroll record"
            ),
            preparer_headers,
        ),
        200,
    )

    rows, meta = validate_paginated(
        api.list_forms_1095c(
            PREPARER, params={"corrected_from_form_id": ctx["form"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one correction must exist, got {meta['total_count']}"
    )
    correction = rows[0]
    assert_form_1095c(
        correction,
        form_type="CORRECTED",
        filing_status="NOT_FILED",
        corrected_from_form_id=ctx["form"]["id"],
    )

    error_row = get_success_data(
        api.get_transmittal_error(ctx["error"]["id"], PREPARER)
    )
    assert error_row["corrected_form_id"] == correction["id"], (
        f"error corrected_form_id {error_row['corrected_form_id']!r} must name the "
        f"created correction {correction['id']!r}"
    )


def test_resolve_correct_form_drafts_correction_on_the_errored_statement(api, preparer_headers):
    """PRD §3.8: "it moves the error `OPEN` → `CORRECTED`, creates a statement
    with `form_type` of `CORRECTED` whose `corrected_from_form_id` is the named
    form, records that new statement in the error's `corrected_form_id`, stamps
    `resolved_by_user_id` and `resolution_note`, moves the named statement
    `FILED_WITH_ERRORS` → `CORRECTION_DRAFTED`, decrements the transmittal's
    `open_error_count`, and increments the group's `open_correction_count`,
    moving a `DETERMINED_ALE` group to `CORRECTION_OPEN`."
    PRD §3.8: "`error_count` and `open_error_count` are set from those rows."

    Design: Corner/State Machines/resolve_correct_form_drafts_correction_and_closes_error
    """
    ctx = _member_with_errored_original(api)
    assert_form_1095c(
        fixtures.read_form(api, ctx["form"]["id"]), filing_status="FILED_WITH_ERRORS"
    )

    validate_success(
        api.resolve_transmittal_error(
            ctx["error"]["id"],
            factories.resolve_error_payload(
                "CORRECT_FORM", resolution_note="SSN corrected from payroll record"
            ),
            preparer_headers,
        ),
        200,
    )

    assert_form_1095c(
        fixtures.read_form(api, ctx["form"]["id"]), filing_status="CORRECTION_DRAFTED"
    )
    assert_transmittal(
        fixtures.read_transmittal(api, ctx["transmittal"]["id"]),
        error_count=1,
        open_error_count=0,
    )


def test_resolve_correct_form_opens_the_correction_chain_on_group_and_season(api, preparer_headers):
    """PRD §3.8: "it moves the error `OPEN` → `CORRECTED`, creates a statement
    with `form_type` of `CORRECTED` whose `corrected_from_form_id` is the named
    form, records that new statement in the error's `corrected_form_id`, stamps
    `resolved_by_user_id` and `resolution_note`, moves the named statement
    `FILED_WITH_ERRORS` → `CORRECTION_DRAFTED`, decrements the transmittal's
    `open_error_count`, and increments the group's `open_correction_count`,
    moving a `DETERMINED_ALE` group to `CORRECTION_OPEN`."
    PRD §2.10: "When a statement of a group enters `REDELIVERY_REQUIRED` on its
    furnishing dimension or `CORRECTION_DRAFTED` on its filing dimension, that
    group's `open_correction_count` increments; if the group was `DETERMINED_ALE`
    and the count moves from zero to a positive value, the group itself moves to
    `CORRECTION_OPEN`, and that move increments the season's
    `open_correction_count`."

    Design: Corner/State Machines/resolve_correct_form_drafts_correction_and_closes_error
    """
    ctx = _member_with_errored_original(api)

    validate_success(
        api.resolve_transmittal_error(
            ctx["error"]["id"],
            factories.resolve_error_payload(
                "CORRECT_FORM", resolution_note="SSN corrected from payroll record"
            ),
            preparer_headers,
        ),
        200,
    )

    group = fixtures.read_group(api, ctx["group"]["id"])
    assert_controlled_group(
        group, determination_state="CORRECTION_OPEN", open_correction_count=1
    )

    season = fixtures.read_season(api, ctx["season"]["id"])
    assert_filing_season(season, open_correction_count=1)


# ---------------------------------------------------------------------------
# Employment events that are not declared transitions
# ---------------------------------------------------------------------------
def test_leave_end_while_active_is_not_applicable(api, benefits_admin_headers):
    """PRD §3.4: "An event type that is not a declared transition out of the
    employee's current status — a leave start while already `ON_LEAVE`, a leave
    end while `ACTIVE`, a transfer or termination while `TERMINATED`, a rehire
    while not `TERMINATED` — is refused with
    `ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE`."

    Design: Corner/State Machines/leave_end_while_active_employment_event_not_applicable
    """
    ctx = _determined_member_with_employee(api)
    employee_id = ctx["employee"]["id"]
    assert_employee(fixtures.read_employee(api, employee_id), employment_status="ACTIVE")

    response = api.create_employment_event(
        factories.employment_event_payload(employee_id, "LEAVE_END", "2026-04-01"),
        benefits_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE, 409)

    assert_employee(fixtures.read_employee(api, employee_id), employment_status="ACTIVE")
    _, meta = validate_paginated(
        api.list_employment_events(BA, params={"employee_id": employee_id})
    )
    assert meta["total_count"] == 0, (
        f"the refused event must not be appended, got {meta['total_count']} events"
    )


def test_leave_start_from_active_records_on_leave(api, benefits_admin_headers):
    """PRD §3.4: "A leave start moves the employee `ACTIVE` → `ON_LEAVE`,
    requires an effective date on or after the `hire_date`, and copies the event's
    leave type into `open_leave_type`."
    PRD §3.4: "Each event records the `resulting_status` it produced and the
    `recorded_by_user_id` who filed it."

    Design: Corner/State Machines/leave_end_while_active_employment_event_not_applicable
    """
    ctx = _determined_member_with_employee(api)
    employee_id = ctx["employee"]["id"]

    response = api.create_employment_event(
        factories.employment_event_payload(
            employee_id, "LEAVE_START", "2026-04-01", leave_type="FMLA"
        ),
        benefits_admin_headers,
    )
    event = validate_success(response, 201)
    assert_employment_event(
        event,
        employee_id=employee_id,
        event_type="LEAVE_START",
        effective_date="2026-04-01",
        resulting_status="ON_LEAVE",
        recorded_by_user_id=BENEFITS_ADMIN_USER_ID,
    )

    employee = fixtures.read_employee(api, employee_id)
    assert_employee(employee, employment_status="ON_LEAVE")
    assert_fields(employee, open_leave_type="FMLA")


def test_rehire_while_on_leave_is_not_applicable(api, benefits_admin_headers):
    """PRD §3.4: "An event type that is not a declared transition out of the
    employee's current status — a leave start while already `ON_LEAVE`, a leave
    end while `ACTIVE`, a transfer or termination while `TERMINATED`, a rehire
    while not `TERMINATED` — is refused with
    `ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE`."
    PRD §3.4: "A rehire moves `TERMINATED` → `ACTIVE` and requires an effective
    date strictly after the `termination_date`."

    Design: Corner/State Machines/leave_end_while_active_employment_event_not_applicable
    """
    ctx = _determined_member_with_employee(api)
    employee_id = ctx["employee"]["id"]
    fixtures.create_employment_event(
        api, employee_id, "LEAVE_START", "2026-04-01", leave_type="FMLA"
    )

    response = api.create_employment_event(
        factories.employment_event_payload(employee_id, "REHIRE", "2026-05-01"),
        benefits_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE, 409)

    assert_employee(
        fixtures.read_employee(api, employee_id), employment_status="ON_LEAVE"
    )
    _, meta = validate_paginated(
        api.list_employment_events(BA, params={"employee_id": employee_id})
    )
    assert meta["total_count"] == 1, (
        f"only the accepted leave start belongs in the log, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# A freshly opened transmittal
# ---------------------------------------------------------------------------
def test_new_transmittal_starts_draft_with_cycle_number_one(api, preparer_headers):
    """PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1,
    every counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."

    Design: Corner/State Machines/transmittal_initial_state_draft_cycle_one
    """
    ctx = _determined_member_with_employee(api)
    fixtures.generate_form(api, ctx["employee"]["id"])
    member_version = fixtures.current_member_version(api, ctx["member"]["id"], PREPARER)

    response = api.create_transmittal(
        factories.transmittal_payload(ctx["member"]["id"], member_version),
        preparer_headers,
    )
    transmittal = validate_success(response, 201)

    assert_transmittal(
        transmittal,
        status="DRAFT",
        cycle_number=1,
        form_count=0,
        aggregate_return_count=0,
        error_count=0,
        open_error_count=0,
    )
    assert_fields(
        transmittal,
        channel=None,
        receipt_id=None,
        built_at=None,
        transmitted_at=None,
    )


def test_new_transmittal_defaults_authoritative_and_required_channel_any(api, preparer_headers):
    """PRD §3.8: "A `Preparer` opens a **Transmittal**, the 1094-C for one
    member, naming the `group_member_id`, a `transmission_type` of `ORIGINAL`,
    `CORRECTION` or `REPLACEMENT`, the mandatory `expected_group_member_version`
    of §2.8, and optionally `authoritative_indicator`, which defaults to true and
    marks this as the member's authoritative transmittal carrying Part III."
    PRD §3.8: "Detaching is permitted while the transmittal is `DRAFT` or
    `BUILT`, and detaching from a built transmittal reverts it `BUILT` → `DRAFT`
    and drops the build outputs it can no longer vouch for:
    `aggregate_return_count` back to 0, `required_channel` back to `ANY`,
    `monthly_ft_counts` back to an empty list and `built_at` cleared."

    Design: Corner/State Machines/transmittal_initial_state_draft_cycle_one
    """
    ctx = _determined_member_with_employee(api)
    member_version = fixtures.current_member_version(api, ctx["member"]["id"], PREPARER)

    transmittal = validate_success(
        api.create_transmittal(
            factories.transmittal_payload(ctx["member"]["id"], member_version),
            preparer_headers,
        ),
        201,
    )

    assert_transmittal(transmittal, authoritative_indicator=True, required_channel="ANY")


def test_new_transmittal_becomes_the_members_open_transmittal(api, preparer_headers):
    """PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1,
    every counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."

    Design: Corner/State Machines/transmittal_initial_state_draft_cycle_one
    """
    ctx = _determined_member_with_employee(api)
    member_version = fixtures.current_member_version(api, ctx["member"]["id"], PREPARER)

    transmittal = validate_success(
        api.create_transmittal(
            factories.transmittal_payload(ctx["member"]["id"], member_version),
            preparer_headers,
        ),
        201,
    )

    member = fixtures.read_member(api, ctx["member"]["id"])
    assert_group_member(member, open_transmittal_id=transmittal["id"])


# ---------------------------------------------------------------------------
# Replaying a grant on an already granted consent
# ---------------------------------------------------------------------------
def test_grant_on_already_granted_consent_rejected(api):
    """PRD §3.7: "Granting a consent that is already `GRANTED` is refused with
    `ERR_CONSENT_ALREADY_GRANTED`."

    Design: Corner/State Machines/duplicate_grant_on_granted_consent_rejected
    """
    ctx = _determined_member_with_employee(api)
    employee_id = ctx["employee"]["id"]
    consent = fixtures.granted_consent(
        api, employee_id, electronic_address="lena.ortiz@example.com"
    )
    assert_furnishing_consent(consent, consent_status="GRANTED")

    employee_headers = make_employee_self_service_headers(employee_id)
    response = api.grant_furnishing_consent(consent["id"], employee_headers)
    validate_error(response, ApiErrorId.ERR_CONSENT_ALREADY_GRANTED, 409)

    assert_furnishing_consent(
        fixtures.read_consent(api, consent["id"]), consent_status="GRANTED"
    )


def test_rejected_grant_replay_does_not_touch_grant_count_or_timestamps(api):
    """PRD §3.7: "Granting takes the consent from `PENDING` to `GRANTED`, or from
    `WITHDRAWN` back to `GRANTED`; either way it stamps `granted_at` from the
    logical clock and increments `grant_count`, so the counter records how many
    rounds the consent has been through. Granting a consent that is already
    `GRANTED` is refused with `ERR_CONSENT_ALREADY_GRANTED`."
    PRD §3.7: "A new consent starts with `consent_status` of `PENDING`,
    `grant_count` of 0, and null `granted_at` and `withdrawn_at`."

    Design: Corner/State Machines/duplicate_grant_on_granted_consent_rejected
    """
    ctx = _determined_member_with_employee(api)
    employee_id = ctx["employee"]["id"]
    consent = fixtures.granted_consent(
        api, employee_id, electronic_address="lena.ortiz@example.com"
    )
    assert_furnishing_consent(consent, grant_count=1)
    granted_at = consent["granted_at"]
    assert granted_at is not None, "the first grant must stamp granted_at"

    validate_error(
        api.grant_furnishing_consent(
            consent["id"], make_employee_self_service_headers(employee_id)
        ),
        ApiErrorId.ERR_CONSENT_ALREADY_GRANTED,
        409,
    )

    replayed = fixtures.read_consent(api, consent["id"])
    assert_furnishing_consent(replayed, grant_count=1, withdrawn_at=None)
    assert replayed["granted_at"] == granted_at, (
        f"granted_at must be unchanged by the refused replay: was {granted_at!r}, "
        f"now {replayed['granted_at']!r}"
    )
