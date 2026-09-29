"""Authorisation breadth: peer segregation between the seven roles, the shared
operations that admit two callers, universal read access, per-row ownership for
the entity-backed roles, and the two-sided segregation of duties on records."""
from test_helpers import (
    ApiErrorId,
    REGISTRATION_OFFICER_USER_ID,
    TEST_USERS,
    api_client,
    create_athlete,
    create_edition,
    create_sport,
    create_sport_event,
    get_athlete,
    get_entry,
    get_event,
    get_record,
    make_athlete_headers,
    make_records_ratifier_headers,
    make_sport_official_headers,
    setup_open_edition,
    setup_pending_record_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
MEDICAL = TEST_USERS["medical_director_headers"]
RATIFIER = TEST_USERS["records_ratifier_headers"]
SPONSOR = TEST_USERS["sponsor_liaison_headers"]

GHOST_ENTRY = "dddddddd-0001-4000-8000-000000000000"
GHOST_ENTRY_TWO = "dddddddd-0002-4000-8000-000000000000"
GHOST_SLOT = "dddddddd-0003-4000-8000-000000000000"
GHOST_PERSON = "dddddddd-0004-4000-8000-000000000000"
GHOST_ATHLETE = "dddddddd-0005-4000-8000-000000000000"
GHOST_RESULT = "dddddddd-0006-4000-8000-000000000000"
GHOST_OFFICIAL = "dddddddd-0007-4000-8000-000000000000"


def test_no_role_can_reach_an_operation_another_role_owns_exclusively(clock_at_epoch):
    """PRD §2.1: "Every single-resource read and every list read is available to all seven
    roles; write access is per-endpoint, and a role that is not listed for the endpoint
    it calls is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.10: "The acting role is authorised for the endpoint called — otherwise
    `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.1: "`GamesAdmin` is organizing-committee operations staff: it builds the
    edition, the sport catalogue, venues and the schedule, recruits personnel, runs the
    operations checkpoint, and drives the logical clock in test harnesses."
    PRD §2.1: "`RegistrationOfficer` staffs the entry desk and the results desk: it
    reviews entries against qualification and age-group rules, seeds events, and
    verifies, publishes and adjudicates marks produced by officials."
    PRD §2.1: "`MedicalDirector` records screening recommendations from the risk model
    and hears appeals against a screening hold."
    PRD §2.1: "`SportOfficial` is a certified official or volunteer acting as
    themselves: confirming their own assignment and submitting marks for the sessions
    they officiate."
    PRD §2.1: "`RecordsRatifier` is the national-body records officer who files
    age-group record claims and ratifies or rejects them."
    PRD §2.1: "`SponsorLiaison` books sponsorship pledges, allocates recognition across
    buckets, and finalizes the edition's economic-impact report."

    Eight refusals, one per exclusive operation, including the two that show the
    widest role is still not a superuser — and none of them wrote a row.

    Design: Corner/rbac/corner_rbac_peer_roles_cannot_reach_each_others_exclusive_operations
    """
    edition = create_edition()
    sport = create_sport(sport_code="TRACK", name="Track and Field")
    event = create_sport_event(sport["id"], edition["id"], min_entries_to_stage=1)

    refusals = (
        # Venue creation belongs to GamesAdmin alone.
        api_client.create_venue(
            {
                "games_edition_id": edition["id"],
                "name": "North Oval",
                "competition_area_count": 4,
                "spectator_capacity": 500,
                "emergency_protocol_code": "EP_ADVANCED",
                "has_onsite_medical_bay": True,
            },
            OFFICER,
        ),
        # Entry review belongs to the RegistrationOfficer, and the unknown entry id
        # never surfaces because the role gate answers first.
        api_client.review_sport_entry(GHOST_ENTRY, {"decision": "TAKE_UP"}, ADMIN),
        # Seeding belongs to the RegistrationOfficer.
        api_client.seed_sport_event(event["id"], MEDICAL),
        # Recruiting personnel belongs to GamesAdmin.
        api_client.create_personnel(
            {
                "games_edition_id": edition["id"],
                "full_name": "Dana Reyes",
                "personnel_type": "OFFICIAL",
                "certification_level": 3,
                "certified_sport_codes": ["TRACK"],
            },
            SPONSOR,
        ),
        # Filing a mark belongs to the SportOfficial; all three cited ids are
        # unknown and still the role gate answers first.
        api_client.create_competition_result(
            {
                "sport_entry_id": GHOST_ENTRY_TWO,
                "session_slot_id": GHOST_SLOT,
                "submitted_by_personnel_id": GHOST_PERSON,
                "mark_value": 13.42,
                "placement": 1,
            },
            RATIFIER,
        ),
        # Screening belongs to the MedicalDirector, not to the athlete screened.
        api_client.create_medical_screening(
            {
                "athlete_id": GHOST_ATHLETE,
                "screened_by_user_id": "md-shah",
                "systolic_bp": 128,
                "resting_hr": 70,
                "prior_cardiac_event": False,
            },
            make_athlete_headers(GHOST_ATHLETE),
        ),
        # Record claims belong to the RecordsRatifier.
        api_client.create_age_group_record(
            {
                "sport_event_id": event["id"],
                "competition_result_id": GHOST_RESULT,
                "claimed_by_user_id": "so-reyes",
                "expected_sport_event_version": event["version"],
            },
            make_sport_official_headers(GHOST_OFFICIAL),
        ),
        # Impact finalization belongs to the SponsorLiaison, so the breadth of
        # GamesAdmin stops here as well.
        api_client.finalize_impact(edition["id"], ADMIN),
    )

    for response in refusals:
        validate_error(
            response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )

    _venues, venue_meta = validate_paginated(api_client.list_venues(ADMIN))
    assert venue_meta["total_count"] == 0
    _people, personnel_meta = validate_paginated(api_client.list_personnel(ADMIN))
    assert personnel_meta["total_count"] == 0
    # The MedicalDirector's seed attempt changed nothing.
    assert get_event(event["id"])["status"] == "OPEN"
    assert get_event(event["id"])["version"] == event["version"]


def test_every_shared_operation_works_from_both_of_its_declared_roles(clock_at_epoch):
    """PRD §3.2: "A `GamesAdmin` or a `RegistrationOfficer` registers an **athlete** into
    an edition by supplying the `games_edition_id`, the athlete's `full_name`, a contact
    `email`, a `date_of_birth` in `YYYY-MM-DD` form, and a `residency_state_code` of
    exactly two uppercase letters."
    PRD §3.3: "It is filed by the `Athlete` themselves or by a `RegistrationOfficer` and
    names the `athlete_id`, the `sport_event_id`, and a `qualification_source` of
    `STATE_QUALIFIER`, `LOCAL_QUALIFIER`, `AGE_EXEMPT` or `ORGANIZER_INVITE`, with
    `qualifying_result_id` supplied only when a qualifying mark is being cited."
    PRD §3.2: "An `Athlete` acting on their own registration, or a `GamesAdmin` acting
    for them, submits `amount_cents`, and the settlement is run; if the tendered
    `amount_cents` differs by even one cent from the `fee_total_cents` the settlement
    produces, the request is refused with `ERR_FEE_AMOUNT_MISMATCH` and nothing is
    written."
    PRD §3.3: "Withdrawal of a single entry is available to the `Athlete` or to a
    `RegistrationOfficer`, takes an optional `reason`, and is admissible from
    `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED`, `ACCEPTED` and
    `MEDICAL_HOLD`."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."
    PRD §3.3: "Entries begin `SUBMITTED` with `revision_round` at 0 and `review_note`
    null, and two fields are derived on the spot."

    Athlete creation, entry filing, fee payment and entry withdrawal each run twice,
    once from each declared caller, and land in identical states.

    Design: Corner/rbac/corner_rbac_shared_operations_admit_both_declared_roles
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition, event = base["edition"], base["event"]

    # Athlete creation is shared between GamesAdmin and RegistrationOfficer.
    by_admin = validate_success(
        api_client.create_athlete(
            {
                "games_edition_id": edition["id"],
                "full_name": "Ada Fenn",
                "email": "ada.fenn@example.org",
                "date_of_birth": "1966-03-02",
                "residency_state_code": "IL",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    by_officer = validate_success(
        api_client.create_athlete(
            {
                "games_edition_id": edition["id"],
                "full_name": "Bo Marsh",
                "email": "bo.marsh@example.org",
                "date_of_birth": "1966-03-02",
                "residency_state_code": "IL",
            },
            OFFICER,
        ),
        expected_status=201,
    )
    assert by_admin["registration_status"] == by_officer["registration_status"] == "PENDING_PAYMENT"

    # Entry filing is shared between the athlete themselves and the entry desk.
    own_entry = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": by_admin["id"],
                "sport_event_id": event["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            make_athlete_headers(by_admin["id"]),
        ),
        expected_status=201,
    )
    desk_entry = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": by_officer["id"],
                "sport_event_id": event["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            OFFICER,
        ),
        expected_status=201,
    )
    assert own_entry["status"] == desk_entry["status"] == "SUBMITTED"

    # Fee payment is shared between the athlete and GamesAdmin: 9500 base plus one
    # 6000 entry fee, no discount tier and no surcharge tier.
    paid_by_self = validate_success(
        api_client.pay_fees(
            by_admin["id"], {"amount_cents": 15500}, make_athlete_headers(by_admin["id"])
        )
    )
    paid_by_admin = validate_success(
        api_client.pay_fees(by_officer["id"], {"amount_cents": 15500}, ADMIN)
    )
    assert paid_by_self["registration_status"] == paid_by_admin["registration_status"] == "REGISTERED"
    assert paid_by_self["fee_total_cents"] == paid_by_admin["fee_total_cents"] == 15500

    # Entry withdrawal is shared the same way.
    pulled_by_self = validate_success(
        api_client.withdraw_sport_entry(
            own_entry["id"], make_athlete_headers(by_admin["id"]),
            {"reason": "travel plans changed"},
        )
    )
    pulled_by_desk = validate_success(
        api_client.withdraw_sport_entry(
            desk_entry["id"], OFFICER, {"reason": "withdrawn at the entry desk"}
        )
    )
    assert pulled_by_self["status"] == pulled_by_desk["status"] == "WITHDRAWN"

    _rows, meta = validate_paginated(
        api_client.list_sport_entries(ADMIN, {"sport_event_id": event["id"]})
    )
    assert meta["total_count"] == 2
    assert get_event(event["id"])["accepted_entry_count"] == 0


def test_all_seven_roles_read_the_same_row_and_the_same_list(clock_at_epoch):
    """PRD §2.1: "The seven roles are `GamesAdmin`, `RegistrationOfficer`, `Athlete`,
    `MedicalDirector`, `SportOfficial`, `RecordsRatifier` and `SponsorLiaison`."
    PRD §2.1: "Every single-resource read and every list read is available to all seven
    roles; write access is per-endpoint, and a role that is not listed for the endpoint
    it calls is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.2: "Otherwise the band floor is 50 plus five years for each complete
    five-year step the basis age sits above 50, and the code is that floor joined by a
    hyphen to the floor plus four — so a basis age of 67 gives the floor 65 and the code
    `65-69`."
    PRD §2.3: "`total_count` reports the number of rows matching the filters before
    pagination is applied, and `has_more` is true when rows remain beyond the returned
    page."

    Reads are role-gated only: every declared role receives an identical athlete
    row, including an athlete asking about somebody else.

    Design: Corner/rbac/corner_rbac_every_role_may_read_every_list_and_row
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition = base["edition"]
    subject = create_athlete(
        edition["id"], full_name="Ada Fenn", email="ada.fenn@example.org"
    )
    other = create_athlete(
        edition["id"], full_name="Bo Marsh", email="bo.marsh@example.org",
        date_of_birth="1961-04-10",
    )

    readers = (
        ADMIN,
        OFFICER,
        # An athlete reading a different athlete's row.
        make_athlete_headers(other["id"]),
        MEDICAL,
        # A SportOfficial header whose id matches no personnel row at all.
        make_sport_official_headers("eeeeeeee-0001-4000-8000-000000000000"),
        RATIFIER,
        SPONSOR,
    )

    for headers in readers:
        row = validate_success(api_client.get_athlete(subject["id"], headers))
        assert row["id"] == subject["id"]
        assert row["age_group_code"] == "60-64"
        _rows, meta = validate_paginated(
            api_client.list_athletes(headers, {"games_edition_id": edition["id"]})
        )
        assert meta["total_count"] == 2

    # The neighbouring athlete really is a different row in a different band, so
    # the read above was not narrowed to the caller's own registration.
    assert get_athlete(other["id"])["age_group_code"] == "65-69"


def test_an_athlete_holds_authority_over_their_own_row_and_no_other(clock_at_epoch):
    """PRD §2.1: "When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting
    `Athlete` row; ownership checks on any resource that references an `Athlete` compare
    the resource's athlete foreign-key field to `X-User-ID`, and on athlete-scoped
    action paths the athlete identifier in the path must itself equal `X-User-ID`."
    PRD §2.10: "For an entity-backed role, `X-User-ID` matches the owning identifier of
    the target — otherwise `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.3: "An `Athlete` may only file for themselves."
    PRD §3.2: "An `Athlete` acting on their own registration, or a `GamesAdmin` acting
    for them, submits `amount_cents`, and the settlement is run; if the tendered
    `amount_cents` differs by even one cent from the `fee_total_cents` the settlement
    produces, the request is refused with `ERR_FEE_AMOUNT_MISMATCH` and nothing is
    written."
    PRD §2.10: "The tendered payment equals the settled fee — otherwise
    `ERR_FEE_AMOUNT_MISMATCH` (HTTP 422)."

    Filing an entry for a neighbour and paying a neighbour's fees are both refused on
    ownership — ahead of the fee arithmetic — while the same calls on the caller's
    own identifier succeed.

    Design: Corner/rbac/corner_rbac_athlete_cannot_act_on_another_athletes_registration
    """
    base = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    edition, event = base["edition"], base["event"]
    caller = create_athlete(
        edition["id"], full_name="Ada Fenn", email="ada.fenn@example.org"
    )
    neighbour = create_athlete(
        edition["id"], full_name="Bo Marsh", email="bo.marsh@example.org"
    )
    caller_headers = make_athlete_headers(caller["id"])

    foreign_entry = api_client.create_sport_entry(
        {
            "athlete_id": neighbour["id"],
            "sport_event_id": event["id"],
            "qualification_source": "ORGANIZER_INVITE",
        },
        caller_headers,
    )
    validate_error(
        foreign_entry, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
    )

    # 9500 is not the neighbour's settled fee either, but ownership is decided
    # long before the tendered amount is compared.
    foreign_payment = api_client.pay_fees(
        neighbour["id"], {"amount_cents": 9500}, caller_headers
    )
    validate_error(
        foreign_payment, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
    )

    own_entry = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": caller["id"],
                "sport_event_id": event["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            caller_headers,
        ),
        expected_status=201,
    )
    assert own_entry["status"] == "SUBMITTED"
    own_payment = validate_success(
        api_client.pay_fees(caller["id"], {"amount_cents": 15500}, caller_headers)
    )
    assert own_payment["registration_status"] == "REGISTERED"

    untouched = get_athlete(neighbour["id"])
    assert untouched["registration_status"] == "PENDING_PAYMENT"
    assert untouched["fee_paid_cents"] == 0
    _rows, meta = validate_paginated(
        api_client.list_sport_entries(ADMIN, {"athlete_id": neighbour["id"]})
    )
    assert meta["total_count"] == 0
    assert get_entry(own_entry["id"])["athlete_id"] == caller["id"]


def test_neither_the_claimer_nor_the_verifier_may_ratify_the_claim(clock_at_epoch):
    """PRD §2.1: "Those recorded operator strings are the basis of the
    segregation-of-duties rule: ratification compares the acting `X-User-ID` against
    both `claimed_by_user_id` and the cited result's `verified_by_user_id`, and a match
    on either side is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "Under `RATIFY` the cited mark must still be `RECORD_PENDING` or
    `PUBLISHED`, and the acting `X-User-ID` must be neither the claim's own
    `claimed_by_user_id` nor the `verified_by_user_id` of the cited mark; either
    coincidence is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "Ratification is separated from both claiming and verifying, because no
    single person should be able to manufacture a record end to end."
    PRD §3.7: "On success the claim moves `PENDING_RATIFICATION` → `RATIFIED`,
    `ratified_by_user_id` is stamped with the acting caller, the event's
    `current_record_id` is repointed at this claim, and the prior record named by this
    claim's `superseded_record_id`, where that pointer is not null, moves `RATIFIED` →
    `SUPERSEDED`."
    PRD §3.7: "The service derives the rest of the row rather than trusting the client:
    `holder_athlete_id` from the athlete behind the cited mark's entry, `age_group_code`
    copied from the event, `mark_value` copied from the cited mark, and
    `superseded_record_id` set to whatever record the event's `current_record_id`
    currently names — the record this claim would displace — or null when no record yet
    stands."

    Two independent identities are barred from ratification, and only a third one
    moves the event's record pointer.

    Design: Corner/rbac/corner_rbac_claimer_and_verifier_cannot_ratify_the_same_record
    """
    ctx = setup_pending_record_claim(claimed_by_user_id="rr-nolan")
    record_id = ctx["record"]["id"]
    event_id = ctx["event"]["id"]

    assert ctx["result"]["verified_by_user_id"] == REGISTRATION_OFFICER_USER_ID
    assert ctx["record"]["status"] == "PENDING_RATIFICATION"
    assert ctx["record"]["claimed_by_user_id"] == "rr-nolan"
    # Nothing stood before, so this claim would displace nothing.
    assert ctx["record"]["superseded_record_id"] is None
    assert get_event(event_id)["current_record_id"] is None

    by_claimer = api_client.ratify_age_group_record(
        record_id, {"decision": "RATIFY"}, make_records_ratifier_headers("rr-nolan")
    )
    validate_error(
        by_claimer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )

    # The officer who verified the cited mark is barred too, even carrying the
    # correct RecordsRatifier role.
    by_verifier = api_client.ratify_age_group_record(
        record_id, {"decision": "RATIFY"},
        make_records_ratifier_headers(REGISTRATION_OFFICER_USER_ID),
    )
    validate_error(
        by_verifier, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )

    # Both refusals left the claim and the record book alone.
    assert get_record(record_id)["status"] == "PENDING_RATIFICATION"
    assert get_event(event_id)["current_record_id"] is None

    ratified = validate_success(
        api_client.ratify_age_group_record(
            record_id, {"decision": "RATIFY"}, make_records_ratifier_headers("rr-okoye")
        )
    )
    assert ratified["status"] == "RATIFIED"
    assert ratified["ratified_by_user_id"] == "rr-okoye"
    assert get_event(event_id)["current_record_id"] == record_id
