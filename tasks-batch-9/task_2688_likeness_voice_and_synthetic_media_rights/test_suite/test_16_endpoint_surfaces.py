"""Reference data, the nested estate route, and the reads that must agree."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_timestamp_format,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_PROFILE = {
    "state_code": "CA",
    "postmortem_rights_years": 70,
    "postmortem_requires_registration": True,
    "biometric_retention_max_days": 365,
    "deletion_grace_days": 30,
    "removal_window_days": 14,
    "disclosure_required_advertising": True,
    "disclosure_required_entertainment": True,
    "min_disclosure_rank_advertising": 3,
    "min_disclosure_rank_entertainment": 2,
}

NY_PROFILE = {
    "state_code": "NY",
    "postmortem_rights_years": 40,
    "postmortem_requires_registration": False,
    "biometric_retention_max_days": 180,
    "deletion_grace_days": 15,
    "removal_window_days": 7,
    "disclosure_required_advertising": True,
    "disclosure_required_entertainment": False,
    "min_disclosure_rank_advertising": 4,
    "min_disclosure_rank_entertainment": 1,
}


def _register(scenario, profile):
    """Register one law profile without asserting the outcome."""
    return api_client.create_state_law_profile(
        factories.state_law_profile_payload(**profile), scenario["admin_headers"]
    )


def _two_profiles_on_the_books():
    """California first, then New York a day later, so newest-first is observable.

    The clock moves between the two registrations because `created_at` is "stamped
    from the logical clock at creation": registering both at the same logical instant
    would tie the sort key the PRD orders on and leave the outcome to the `id`
    tiebreak, whose direction the PRD does not state.
    """
    scenario = fixtures.new_scenario()
    california = validate_success(_register(scenario, CA_PROFILE), 201)
    fixtures.move_clock("2026-08-02T00:00:00Z", scenario["admin_headers"])
    new_york = validate_success(_register(scenario, NY_PROFILE), 201)
    return scenario, california, new_york


def test_the_law_profile_is_created_filtered_and_paged_without_a_version():
    """All ten declared fields come back, with no version, and the window honours offset.

    The PRD states: "Three record types are immutable once written and therefore
    carry neither `updated_at` nor `version`; both fields are absent from their
    representations entirely. A `StateLawProfile` is a statement of one state's law and
    is never edited." The list is filterable and ordered against the insertion order:
    "Collections also accept equality filters, and each filter narrows the result set
    before pagination. State law profiles filter on `state_code`." and "Three
    collections order differently and do so deliberately: state law profiles are
    returned newest first, by `created_at` descending and then by `id`". The window
    one: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` counts the rows matching the filters before the
    page window is applied and `has_more` is true when rows remain beyond the current
    window."

    Design: Corner/endpoints/state_law_profile_create_read_and_filtered_list
    """
    scenario, california, new_york = _two_profiles_on_the_books()

    assertions.assert_subset_equal(new_york, NY_PROFILE)
    assertions.assert_fields_absent(new_york, "version", "updated_at")
    assert_timestamp_format(new_york["created_at"])

    filtered, filtered_meta = validate_paginated(
        api_client.list_state_law_profiles(
            scenario["licensee_headers"], params={"state_code": "NY"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [new_york["id"]]

    windowed, window_meta = validate_paginated(
        api_client.list_state_law_profiles(
            scenario["admin_headers"], params={"limit": 1, "offset": 1}
        )
    )
    assertions.assert_pagination(
        window_meta, limit=1, offset=1, total_count=2, has_more=False
    )
    assert [row["id"] for row in windowed] == [california["id"]]


def test_a_second_profile_for_the_same_state_is_refused_and_the_first_stands():
    """The unique state code holds, and the stored forty-year term is untouched.

    The PRD states: "Its `state_code` is exactly two uppercase letters and is unique
    across profiles — a second registration for a `state_code` that already exists is
    rejected with `ERR_INVALID_REQUEST`." The field the duplicate tried to move is the
    one the PRD describes here: "`postmortem_rights_years` is a whole number from 0
    through 100 giving the years of post-mortem likeness rights the state recognises,
    where 0 means the state recognises none at all."

    Design: Corner/endpoints/state_law_profile_create_read_and_filtered_list
    """
    scenario, _california, new_york = _two_profiles_on_the_books()

    validate_error(
        _register(scenario, dict(NY_PROFILE, postmortem_rights_years=41)),
        "ERR_INVALID_REQUEST",
    )

    stored = validate_success(
        api_client.get_state_law_profile(new_york["id"], scenario["admin_headers"]), 200
    )
    assert stored["postmortem_rights_years"] == 40

    _rows, meta = validate_paginated(
        api_client.list_state_law_profiles(
            scenario["admin_headers"], params={"state_code": "NY"}
        )
    )
    assert meta["total_count"] == 1


REYES_ESTATE = {
    "executor_name": "Reyes Family Trust",
    "court_document_ref": "LA-PROB-2026-1187",
    "registration_number": "CA-POSTMORTEM-9931",
}

HADDAD_ESTATE = {
    "executor_name": "Haddad Estate LLC",
    "court_document_ref": "NY-SURR-2026-0442",
}


def _a_claim_awaiting_verification():
    """A CA talent who died at the startup instant, with one filed claim."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.record_death(scenario, {"date_of_death": "2026-08-01T00:00:00Z"})
    fixtures.submit_estate_authority(scenario, REYES_ESTATE)
    return scenario


def test_verification_is_a_one_way_door_stamped_by_the_second_administrator():
    """SUBMITTED to VERIFIED once; the repeat is a 409 that changes nothing.

    The PRD states: "Verification is a second `RightsAdministrator`'s act. It is
    refused with `ERR_INVALID_ESTATE_AUTHORITY_STATE` unless the claim's `status` is
    `SUBMITTED`, so an already `VERIFIED` or `REJECTED` claim cannot be verified again,
    and it is refused with `ERR_SEGREGATION_OF_DUTIES` when the verifying user is the
    same user recorded as `submitted_by_user_id`. On success the claim's `status`
    becomes `VERIFIED`, `verified_by_user_id` records the verifier and `verified_at`
    records the logical instant." The filed claim starts where the PRD puts it: "The
    claim is created with `status` of `SUBMITTED`, and the filer's identifier is
    recorded as `submitted_by_user_id` for later duty-separation enforcement." The
    talent's own term is settled at the death record and never revisited: "Otherwise
    `postmortem_rights_until` is the date of death advanced by that number of whole
    years, landing on the same month and day, stored as an instant at `00:00:00Z`."

    Design: Corner/endpoints/estate_authority_verification_is_a_one_way_action
    """
    scenario = _a_claim_awaiting_verification()
    filed = scenario["estate_authority"]
    assert filed["status"] == "SUBMITTED"
    assert filed["submitted_by_user_id"] == scenario["admin_user_id"]
    assertions.assert_fields_null(filed, "verified_by_user_id", "verified_at")
    assertions.assert_versioned(filed, 1)

    fixtures.verify_estate_authority(scenario)
    verified = scenario["estate_authority"]
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == scenario["second_admin_user_id"]
    assert verified["verified_at"] == "2026-08-01T00:00:00Z"
    assertions.assert_versioned(verified, 2)

    repeat = api_client.verify_estate_authority(
        verified["id"], {}, scenario["second_admin_headers"]
    )
    validate_error(repeat, "ERR_INVALID_ESTATE_AUTHORITY_STATE")

    unchanged = validate_success(
        api_client.get_estate_authority(verified["id"], scenario["admin_headers"]), 200
    )
    assertions.assert_subset_equal(
        unchanged,
        {
            "status": "VERIFIED",
            "verified_by_user_id": scenario["second_admin_user_id"],
            "verified_at": "2026-08-01T00:00:00Z",
            "version": 2,
        },
    )

    talent = fixtures.read_talent(scenario)
    assert talent["life_status"] == "DECEASED"
    assert talent["postmortem_rights_until"] == "2096-08-01T00:00:00Z"


def _two_estates_only_one_of_them_verified():
    """Two deceased CA talents, one claim each, the second talent's claim verified."""
    home = fixtures.register_state_law_profile()
    fixtures.create_talent(home)
    fixtures.record_death(home, {"date_of_death": "2026-07-01T00:00:00Z"})
    fixtures.submit_estate_authority(home, REYES_ESTATE)

    away = fixtures.new_scenario()
    fixtures.create_talent(away, {"legal_name": "Noor Haddad"})
    fixtures.record_death(away, {"date_of_death": "2026-07-15T00:00:00Z"})
    fixtures.submit_estate_authority(away, HADDAD_ESTATE)
    fixtures.verify_estate_authority(away)
    return home, away


def test_the_nested_estate_list_answers_only_for_the_talent_in_its_path():
    """One claim each, and the status filter narrows inside the parent scope.

    The PRD states: "Claims for a talent are listed in `created_at` ascending order and
    are filterable by `status`, and a single claim can be read on its own." The filter
    composes with that scope rather than replacing it: "Collections also accept equality
    filters, and each filter narrows the result set before pagination." The claim that
    the scoped list must not leak is the one the PRD moves on verification: "On success
    the claim's `status` becomes `VERIFIED`, `verified_by_user_id` records the verifier
    and `verified_at` records the logical instant."

    Design: Corner/endpoints/estate_authorities_are_scoped_to_their_parent_talent
    """
    home, away = _two_estates_only_one_of_them_verified()

    mine, mine_meta = validate_paginated(
        api_client.list_estate_authorities(home["talent"]["id"], home["admin_headers"])
    )
    assert mine_meta["total_count"] == 1
    assert [row["id"] for row in mine] == [home["estate_authority"]["id"]]
    assert mine[0]["status"] == "SUBMITTED"

    _none, verified_meta = validate_paginated(
        api_client.list_estate_authorities(
            home["talent"]["id"], home["admin_headers"], params={"status": "VERIFIED"}
        )
    )
    assert verified_meta["total_count"] == 0

    theirs, theirs_meta = validate_paginated(
        api_client.list_estate_authorities(away["talent"]["id"], away["admin_headers"])
    )
    assert theirs_meta["total_count"] == 1
    assert [row["id"] for row in theirs] == [away["estate_authority"]["id"]]
    assert theirs[0]["status"] == "VERIFIED"


def test_a_claim_against_no_talent_is_a_parent_not_found_and_writes_no_orphan():
    """The parent is resolved first, and the verified claim reads its own record.

    The PRD states: "Existence checks follow, in this internal order:
    `ERR_TALENT_NOT_FOUND` (a talent id from the path or body, as used by the talent
    read, the talent's estate-authority list and submission, the death record, and
    consent drafting)". The identity that reads the verified claim is defined by its
    own id: "When `X-User-Role` is `EstateRepresentative`, `X-User-ID` is the `id` of
    the acting `EstateAuthority`; ownership checks require that authority to be
    `VERIFIED` and to name, through its own `talent_id`, the talent behind the target
    resource."

    Design: Corner/endpoints/estate_authorities_are_scoped_to_their_parent_talent
    """
    home, away = _two_estates_only_one_of_them_verified()

    refused = api_client.submit_estate_authority(
        NON_EXISTENT_UUID,
        factories.estate_authority_payload(
            executor_name="Ghost Estate", court_document_ref="NONE-0000"
        ),
        home["admin_headers"],
    )
    validate_error(refused, "ERR_TALENT_NOT_FOUND")

    _rows, meta = validate_paginated(
        api_client.list_estate_authorities(home["talent"]["id"], home["admin_headers"])
    )
    assert meta["total_count"] == 1

    own_record = validate_success(
        api_client.get_estate_authority(
            away["estate_authority"]["id"], away["estate_rep_headers"]
        ),
        200,
    )
    assert own_record["id"] == away["estate_authority"]["id"]
    assert own_record["talent_id"] == away["talent"]["id"]


PLAIN_GRANT = dict(
    fixtures.CAMPAIGN_GRANT, territory_codes=["US"], permitted_use_notes="Campaign"
)


def test_the_grant_the_ledger_and_the_talent_all_report_the_same_three_hundred_thousand():
    """One movement, read three ways, agreeing to the cent and to the split.

    The PRD states: "The floor is the `minimum_initial_cents` of the union row selected
    for the grant's affiliation, the governing media type and the grant's
    `effective_from`; when the grant carries no union affiliation the floor is zero and
    no lookup happens." The talent's affiliation is pinned at draft time:
    "`union_code_snapshot` is copied from the talent's `union_code` at draft time — null
    when the talent's affiliation is `NONE` — so that a later change of affiliation
    cannot retroactively move the floors that govern this grant." The entry is the
    authority for the figure the grant reports: "Each entry names the talent it belongs
    to through `talent_id` and the grant the money moves under through
    `consent_grant_id`; both are copied from the governing grant rather than supplied by
    a caller, so the ledger is filterable by talent without a join." Its slices come
    from the grant's declared percentages: "The three-way split is declared here as
    well: `talent_share_pct` defaults to 0.75 and must be greater than zero and at most
    1 with at most four decimals; `agency_share_pct` defaults to 0.20 and must be at
    least zero and strictly below 1 with at most four decimals; and the two together may
    not exceed 1." And the ledger row itself carries no counters: "These three carry
    only `id` and `created_at` alongside their own fields."

    Design: Corner/endpoints/grant_read_reconciles_with_the_compensation_ledger
    """
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, PLAIN_GRANT)
    fixtures.countersign_grant(scenario)

    grant = validate_success(
        api_client.get_consent_grant(scenario["grant"]["id"], scenario["admin_headers"]),
        200,
    )
    assertions.assert_subset_equal(
        grant,
        {
            "status": "ACTIVE",
            "union_code_snapshot": None,
            "initial_compensation_cents": 300_000,
            "union_topup_cents": 0,
            "total_compensation_cents": 300_000,
        },
    )

    listed, meta = validate_paginated(
        api_client.list_compensation_entries(
            scenario["admin_headers"], params={"consent_grant_id": grant["id"]}
        )
    )
    assert meta["total_count"] == 1
    assertions.assert_ledger_entry(
        listed[0], "INITIAL_CREATION", 300_000, 225_000, 60_000, 15_000
    )
    assert listed[0]["reverses_entry_id"] is None

    entry = validate_success(
        api_client.get_compensation_entry(
            listed[0]["id"], scenario["talent_rep_headers"]
        ),
        200,
    )
    assertions.assert_split_reconstructs_amount(entry)
    assert entry["posted_at"] == "2026-08-01T00:00:00Z"
    assertions.assert_fields_absent(entry, "version", "updated_at")

    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )


LOCKED_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    territory_codes=["US"],
    permitted_use_notes="Locked buyout",
    revocable=False,
)

OPEN_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    territory_codes=["US"],
    permitted_use_notes="Ordinary licence",
)


def _one_locked_grant_and_one_ordinary_one():
    """Two ACTIVE grants for one talent, differing only in the revocable flag."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, LOCKED_GRANT)
    fixtures.countersign_grant(scenario)
    locked = scenario["grant"]
    fixtures.draft_consent_grant(scenario, OPEN_GRANT)
    fixtures.countersign_grant(scenario)
    return scenario, locked, scenario["grant"]


def test_the_same_revoke_is_refused_on_the_locked_grant_and_honoured_on_the_other():
    """The flag alone decides, and the refusal leaves no obligation behind.

    The PRD states: "A grant whose `revocable` flag is false may never be revoked, and
    the attempt is refused with `ERR_CONSENT_NOT_REVOCABLE`." The other grant took the
    default: "Two booleans complete the draft: `approval_required`, defaulting to true,
    meaning every generated performance needs an explicit approval decision from the
    talent or estate representative; and `revocable`, defaulting to true, meaning the
    grant may later be revoked." Nothing was ever built under either grant, so the
    honoured revocation is the short path: "Revoking a grant that never left
    `PENDING_COUNTERSIGN` is simple, because nothing was ever built under it: `status`
    becomes `REVOKED`, `effective_end_actual` is stamped with the current logical
    instant, the talent's `rights_posture` is recomputed, and the two versions advance."

    Design: Corner/endpoints/revocation_is_permitted_only_on_a_revocable_grant
    """
    scenario, locked, ordinary = _one_locked_grant_and_one_ordinary_one()
    assert locked["revocable"] is False
    assert ordinary["revocable"] is True

    refused = api_client.revoke_consent_grant(
        locked["id"], factories.revoke_payload(), scenario["talent_rep_headers"]
    )
    validate_error(refused, "ERR_CONSENT_NOT_REVOCABLE")

    still_active = fixtures.refresh_grant(scenario, locked)
    assert still_active["status"] == "ACTIVE"
    assert still_active["effective_end_actual"] is None
    assertions.assert_versioned(still_active, locked["version"])

    revoked = fixtures.revoke_grant(scenario, ordinary)
    assert revoked["status"] == "REVOKED"
    assert revoked["effective_end_actual"] == "2026-08-01T00:00:00Z"

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(talent, open_removal_obligation_count=0)
    assertions.assert_posture(talent, "CLEAR")

    active, meta = validate_paginated(
        api_client.list_consent_grants(
            scenario["admin_headers"],
            params={"talent_id": scenario["talent"]["id"], "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in active] == [locked["id"]]
