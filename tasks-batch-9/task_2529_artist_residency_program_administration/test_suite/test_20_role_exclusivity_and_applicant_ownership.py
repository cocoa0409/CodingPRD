"""Who may reconfigure the workshops, and whose paperwork an artist may touch."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_UNAUTHORIZED,
    FACILITIES_HEADERS,
    FINANCE_SCHEDULER_HEADERS,
    FUNDER_HEADERS,
    NON_EXISTENT_UUID,
    UNKNOWN_ENTITY_USER_ID,
    VISA_HEADERS,
    add_portfolio_item,
    create_applicant,
    create_application,
    create_residency,
    create_studio,
    get_success_data,
    make_applicant_headers,
    make_lifecycle_payload,
    make_offer_response_payload,
    make_portfolio_item_payload,
    make_studio_assignment_payload,
    make_studio_payload,
    read_application,
    refresh_residency,
    refresh_studio,
    schedule_residency,
    set_clock,
    settle_fee,
    setup_open_cycle,
    validate_error,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
STUDIO_SHAPE = {
    "code": "S-A",
    "capability_tags": ["WELDING"],
    "ventilation_class": "LOCAL",
    "max_concurrent_residents": 1,
}
WIDER_HEADCOUNT = {"max_concurrent_residents": 3}


def _registered_studio(api):
    """A single-occupancy welding studio put on the books by program staff."""
    set_clock(api, CLOCK)
    studio = create_studio(api, **STUDIO_SHAPE)
    assert studio.studio["max_concurrent_residents"] == 1
    return studio


def _reconfigure(api, studio, headers, changes=None):
    """The configuration write, offered by whichever role the caller names."""
    return api.update_studio(
        studio.studio_id, dict(changes or WIDER_HEADCOUNT), headers
    )


def test_the_registrar_of_the_studio_may_not_reconfigure_it(api):
    """Program staff put the studio on the books and cannot change its headcount.

    PRD: "A `FacilitiesManager` may later revise `capability_tags`,
    `ventilation_class`, `max_concurrent_residents` or `status`; each such change
    advances the studio's `version` by 1."

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    studio = _registered_studio(api)
    before = studio.studio

    validate_error(_reconfigure(api, studio, ADMIN_HEADERS), ERR_UNAUTHORIZED)

    held = refresh_studio(api, studio)
    assert held["max_concurrent_residents"] == 1
    assert held["version"] == before["version"]


def test_the_exclusive_holder_makes_the_identical_change_stick(api):
    """The same body from the facilities desk is accepted and moves the version.

    PRD: "A `FacilitiesManager` may later revise `capability_tags`,
    `ventilation_class`, `max_concurrent_residents` or `status`; each such change
    advances the studio's `version` by 1."

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    studio = _registered_studio(api)
    before = studio.studio

    widened = get_success_data(_reconfigure(api, studio, FACILITIES_HEADERS))

    assert widened["max_concurrent_residents"] == 3
    assert widened["version"] == before["version"] + 1


def test_the_registration_leg_really_is_shared(api):
    """The split is drawn per operation, not per entity.

    PRD: "A **studio** is registered by a `FacilitiesManager` or a `ProgramAdmin`
    with a `code` unique across all studios"

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    _registered_studio(api)

    from_facilities = get_success_data(
        api.create_studio(make_studio_payload(code="S-B"), FACILITIES_HEADERS), 201
    )

    assert from_facilities["code"] == "S-B"
    assert from_facilities["max_concurrent_residents"] >= 1


def test_the_booking_and_the_release_legs_stay_shared_too(api):
    """Both roles may fill the studio and both may empty it again.

    PRD: "Releasing an assignment by hand — a `FacilitiesManager` or `ProgramAdmin`
    action carrying an optional `reason` — requires the assignment to be `ACTIVE`"

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    studio = _registered_studio(api)
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)

    def book(headers):
        current = refresh_residency(api, residency)
        return get_success_data(
            api.create_studio_assignment(
                make_studio_assignment_payload(
                    residency.residency_id,
                    SESSION_START,
                    SESSION_END,
                    current["version"],
                    studio.studio_id,
                ),
                headers,
            ),
            201,
        )

    by_admin = book(ADMIN_HEADERS)
    freed = get_success_data(
        api.release_studio_assignment(
            by_admin["id"], {"reason": "swap"}, FACILITIES_HEADERS
        )
    )
    by_facilities = book(FACILITIES_HEADERS)
    freed_again = get_success_data(
        api.release_studio_assignment(
            by_facilities["id"], {"reason": "swap back"}, ADMIN_HEADERS
        )
    )

    assert by_admin["status"] == "ACTIVE" and by_facilities["status"] == "ACTIVE"
    assert freed["status"] == "RELEASED" and freed_again["status"] == "RELEASED"


def test_roles_outside_the_pair_are_refused_on_both_legs(api):
    """Money, visas and funding have no business configuring a workshop.

    PRD: "Only once both headers are well-formed does the service ask whether that
    role is permitted to perform the requested operation at all; when it is not, the
    answer is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    studio = _registered_studio(api)

    for headers in (FINANCE_SCHEDULER_HEADERS, VISA_HEADERS, FUNDER_HEADERS):
        validate_error(_reconfigure(api, studio, headers), ERR_UNAUTHORIZED)
        validate_error(
            api.create_studio(make_studio_payload(), headers), ERR_UNAUTHORIZED
        )

    assert refresh_studio(api, studio)["max_concurrent_residents"] == 1


def test_the_read_side_is_wider_than_the_write_side(api):
    """Three roles may look at the ledger and only one may edit the row.

    PRD: "Studios are readable by `FacilitiesManager`, `ProgramAdmin` and `Funder`."

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    studio = _registered_studio(api)

    seen = [
        get_success_data(api.get_studio(studio.studio_id, headers))
        for headers in (ADMIN_HEADERS, FACILITIES_HEADERS, FUNDER_HEADERS)
    ]

    assert all(row["id"] == studio.studio_id for row in seen)
    validate_error(_reconfigure(api, studio, FUNDER_HEADERS), ERR_UNAUTHORIZED)


def test_the_role_check_answers_before_the_row_is_looked_up(api):
    """A forbidden role hears about the role, even for a studio that does not exist.

    PRD: "the `X-User-ID` header, then the `X-User-Role` header, then role permission
    for the operation, then backing-row resolution for entity-backed roles, then
    chair eligibility"

    Design: Corner/rbac/studio_configuration_is_exclusive_to_facilities_while_creation_is_shared
    """
    _registered_studio(api)

    validate_error(
        api.update_studio(NON_EXISTENT_UUID, dict(WIDER_HEADCOUNT), ADMIN_HEADERS),
        ERR_UNAUTHORIZED,
    )


def _two_artists_and_one_ready_draft(api):
    """Ada holds a fully submittable draft; Kell holds nothing at all."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    ada = create_applicant(api)
    kell = create_applicant(api)
    draft = create_application(api, cycle, ada, fee_waiver_requested=True)
    settle_fee(api, draft, "WAIVE")
    add_portfolio_item(api, draft)
    return cycle, ada, kell, draft


def test_the_wrong_artist_cannot_submit_a_perfectly_ready_application(api):
    """Nothing about the application is wrong except who is asking.

    PRD: "An acting `Applicant` may only operate on an application or residency whose
    `applicant_id` equals their `X-User-ID`; this governs editing an application,
    submitting it, responding to its offer, attaching or deleting a portfolio item on
    it, and withdrawing from a residency."

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, _ada, kell, draft = _two_artists_and_one_ready_draft(api)

    validate_error(
        api.submit_application(draft.application_id, kell.headers), ERR_UNAUTHORIZED
    )

    assert read_application(api, draft.application_id)["status"] == "DRAFT"


def test_the_owner_succeeds_with_the_identical_call(api):
    """The same request from the right identity goes through untouched.

    PRD: "An acting `Applicant` may only operate on an application or residency whose
    `applicant_id` equals their `X-User-ID`"

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, ada, kell, draft = _two_artists_and_one_ready_draft(api)
    validate_error(
        api.submit_application(draft.application_id, kell.headers), ERR_UNAUTHORIZED
    )

    submitted = get_success_data(
        api.submit_application(draft.application_id, ada.headers)
    )

    assert submitted["status"] == "SUBMITTED"


def test_program_staff_are_not_bound_by_the_ownership_rule(api):
    """The scoping constrains an acting artist, not every caller of a shared route.

    PRD: "When `X-User-Role` is `ProgramAdmin`, `FinanceOfficer`, `VisaCoordinator`,
    `FacilitiesManager` or `Funder`, `X-User-ID` is an opaque operator identifier not
    tied to any persisted entity."

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, _ada, _kell, draft = _two_artists_and_one_ready_draft(api)

    submitted = get_success_data(
        api.submit_application(draft.application_id, ADMIN_HEADERS)
    )

    assert submitted["status"] == "SUBMITTED"


def test_every_artist_facing_write_is_scoped_the_same_way(api):
    """Four different routes onto one application, all closed to the stranger.

    PRD: "this governs editing an application, submitting it, responding to its offer,
    attaching or deleting a portfolio item on it, and withdrawing from a residency"

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, _ada, kell, draft = _two_artists_and_one_ready_draft(api)
    before = read_application(api, draft.application_id)

    validate_error(
        api.create_portfolio_item(
            make_portfolio_item_payload(draft.application_id, title="Intruder"),
            kell.headers,
        ),
        ERR_UNAUTHORIZED,
    )
    validate_error(
        api.delete_portfolio_item(draft.portfolio_item_ids[0], kell.headers),
        ERR_UNAUTHORIZED,
    )
    validate_error(
        api.update_application(
            draft.application_id, {"project_statement": "Rewritten"}, kell.headers
        ),
        ERR_UNAUTHORIZED,
    )
    validate_error(
        api.respond_to_offer(
            draft.application_id, make_offer_response_payload("ACCEPT"), kell.headers
        ),
        ERR_UNAUTHORIZED,
    )

    after = read_application(api, draft.application_id)
    assert after["version"] == before["version"]
    assert after["portfolio_item_count"] == before["portfolio_item_count"]


def test_profile_writes_are_scoped_the_same_way(api):
    """An artist revising their own declared income touches nobody else's row.

    PRD: "Profile edits may change `full_name`, `affiliation_org`,
    `citizenship_country`, `treaty_country` or `declared_annual_income_cents`;
    such an edit re-derives `is_international` and advances the applicant's
    `version` by 1"

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, ada, kell, _draft = _two_artists_and_one_ready_draft(api)
    edit = {"declared_annual_income_cents": 1234500}

    own = get_success_data(
        api.update_applicant(kell.applicant_id, dict(edit), kell.headers)
    )
    assert own["declared_annual_income_cents"] == 1234500
    assert get_success_data(api.get_applicant(ada.applicant_id, ADMIN_HEADERS))[
        "declared_annual_income_cents"
    ] != 1234500


def test_the_residency_leg_is_scoped_by_the_artist_too(api):
    """Withdrawal belongs to the resident, and only to the resident.

    PRD: "`WITHDRAW` drives `SCHEDULED → WITHDRAWN` and is the artist's own action:
    the acting `Applicant`'s `X-User-ID` must equal the residency's `applicant_id`"

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    cycle, ada, kell, _draft = _two_artists_and_one_ready_draft(api)
    residency = create_residency(api, cycle, ada)
    schedule_residency(api, residency, SESSION_START, 8)

    validate_error(
        api.residency_lifecycle(
            residency.residency_id, make_lifecycle_payload("WITHDRAW"), kell.headers
        ),
        ERR_UNAUTHORIZED,
    )

    assert refresh_residency(api, residency)["status"] == "SCHEDULED"
    gone = get_success_data(
        api.residency_lifecycle(
            residency.residency_id, make_lifecycle_payload("WITHDRAW"), ada.headers
        )
    )
    assert gone["status"] == "WITHDRAWN"


def test_an_unresolvable_identity_fails_before_ownership_is_reached(api):
    """A caller claiming to be an artist who is not on file gets no further.

    PRD: "For the three entity-backed roles (`Applicant`, `Panelist`, `PanelChair`),
    the supplied `X-User-ID` must resolve to an existing row of the backing entity"

    Design: Corner/rbac/applicant_shared_operations_are_scoped_to_the_artists_own_rows
    """
    _cycle, _ada, _kell, draft = _two_artists_and_one_ready_draft(api)
    ghost = make_applicant_headers(UNKNOWN_ENTITY_USER_ID)

    validate_error(api.submit_application(draft.application_id, ghost), ERR_UNAUTHORIZED)

    assert read_application(api, draft.application_id)["status"] == "DRAFT"
