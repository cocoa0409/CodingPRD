"""What the entities themselves promise: full bodies, defaults and identity."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT_REPLICA_ID = "00000000-0000-4000-8000-000000000000"
NON_EXISTENT_GRANT_ID = "00000000-0000-4000-8000-0000000000ff"
NON_EXISTENT_TALENT_ID = "00000000-0000-4000-8000-0000000000ee"


def test_talent_creation_answers_with_every_field_the_record_declares():
    """A two-field create returns the derived counters and posture as well.

    The PRD states: "At creation `life_status` is always `LIVING` — a caller cannot
    open a record already deceased — `date_of_death` and `postmortem_rights_until`
    are null, `postmortem_registration_number` is null, `rights_posture` is `CLEAR`,
    and `open_removal_obligation_count`, `legal_hold_asset_count` and
    `lifetime_compensation_cents` are all zero." Identity and stamping are uniform:
    "Every resource the API mints carries an `id`, which is a server-generated UUID
    with no type prefix and no client-supplied component. Every resource also carries
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped
    from the logical clock at creation."

    Design: Corner/entities/talent_creation_returns_every_declared_field
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)

    created = validate_success(
        api_client.create_talent(
            {"legal_name": "Ava Reyes", "domicile_state_code": "CA"},
            scenario["admin_headers"],
        ),
        201,
    )

    assertions.assert_subset_equal(
        created,
        {
            "legal_name": "Ava Reyes",
            "domicile_state_code": "CA",
            "union_code": "NONE",
            "life_status": "LIVING",
            "rights_posture": "CLEAR",
            "legal_hold_asset_count": 0,
            "open_removal_obligation_count": 0,
            "lifetime_compensation_cents": 0,
            "version": 1,
        },
    )
    assertions.assert_fields_null(
        created,
        "date_of_death",
        "postmortem_rights_until",
        "postmortem_registration_number",
    )
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])


def test_grant_retrieval_echoes_the_drafted_terms_and_the_residual_share():
    """The read carries back the residual share and the union snapshot.

    The PRD states: "The residual, `administrator_share_pct`, is computed as one
    minus `talent_share_pct` minus `agency_share_pct` and is retained by the
    clearance office." It also states: "`union_code_snapshot` is copied from the
    talent's `union_code` at draft time — null when the talent's affiliation is
    `NONE` — so that a later change of affiliation cannot retroactively move the
    floors that govern this grant." Before any signature: "Drafting stamps `status`
    as `PENDING_COUNTERSIGN`, records the drafting administrator as
    `drafted_by_user_id`, leaves `suspension_reason`, `countersigned_at` and
    `effective_end_actual` null, and initialises `initial_compensation_cents`,
    `union_topup_cents` and `total_compensation_cents` to zero."

    Design: Corner/entities/consent_grant_retrieval_returns_stored_representation
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    fixtures.draft_consent_grant(
        scenario,
        dict(fixtures.CAMPAIGN_GRANT, talent_share_pct=0.70, agency_share_pct=0.25),
    )

    read_back = validate_success(
        api_client.get_consent_grant(
            scenario["grant"]["id"], scenario["admin_headers"]
        )
    )

    assertions.assert_subset_equal(
        read_back,
        {
            "id": scenario["grant"]["id"],
            "status": "PENDING_COUNTERSIGN",
            "talent_share_pct": 0.70,
            "agency_share_pct": 0.25,
            "administrator_share_pct": 0.05,
            "union_code_snapshot": "SAG_AFTRA",
            "permitted_media_types": ["ADVERTISING"],
            "territory_codes": ["US", "MX"],
            "drafted_by_user_id": scenario["admin_user_id"],
            "initial_compensation_cents": 0,
            "union_topup_cents": 0,
            "total_compensation_cents": 0,
        },
    )
    assertions.assert_fields_null(
        read_back, "countersigned_at", "effective_end_actual", "suspension_reason"
    )


CASE_ONE = {
    "suspect_url": "https://pirate.example/one",
    "detected_channel": "ADVERTISING",
    "detected_view_count": 100_000,
    "match_confidence": 0.400,
}

CASE_TWO = {
    "suspect_url": "https://pirate.example/two",
    "detected_channel": "ENTERTAINMENT",
    "detected_view_count": 200_000,
    "match_confidence": 0.450,
}

CASE_THREE = {
    "detection_source": "MANUAL_REPORT",
    "suspect_url": "https://pirate.example/three",
    "detected_channel": "ADVERTISING",
    "detected_view_count": 300_000,
    "match_confidence": 0.500,
}


def test_case_listing_pages_in_creation_order_and_narrows_on_its_filter():
    """Two pages, one filter, and the envelope's four counters throughout.

    The PRD states: "Every list response reports `limit`, `offset`, `total_count`
    and `has_more` inside `meta`, where `total_count` counts the rows matching the
    filters before the page window is applied and `has_more` is true when rows
    remain beyond the current window." The order is the default one: "Unless a
    specific collection says otherwise, lists are ordered by `created_at`
    ascending." The window defaults are stated too: "`limit` controls page size: it
    defaults to 10, may not be smaller than 1, and may not be larger than 100.
    `offset` controls the starting position: it defaults to 0 and may not be
    negative." And the filter exists: "Infringement cases filter on `talent_id`,
    `matched_usage_license_id`, `status` and `detection_source`."

    Design: Corner/entities/infringement_case_listing_paginates_in_created_at_order
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    opened = []
    for overrides in (CASE_ONE, CASE_TWO, CASE_THREE):
        fixtures.open_case(scenario, overrides)
        opened.append(scenario["case"])

    first_page, first_meta = validate_paginated(
        api_client.list_infringement_cases(
            scenario["compliance_headers"], params={"limit": 2, "offset": 0}
        )
    )
    assert [row["id"] for row in first_page] == [opened[0]["id"], opened[1]["id"]]
    assertions.assert_pagination(first_meta, 2, 0, 3, True)

    second_page, second_meta = validate_paginated(
        api_client.list_infringement_cases(
            scenario["compliance_headers"], params={"limit": 2, "offset": 2}
        )
    )
    assert [row["id"] for row in second_page] == [opened[2]["id"]]
    assertions.assert_pagination(second_meta, 2, 2, 3, False)

    filtered, filtered_meta = validate_paginated(
        api_client.list_infringement_cases(
            scenario["compliance_headers"], params={"detection_source": "MANUAL_REPORT"}
        )
    )
    assert [row["id"] for row in filtered] == [opened[2]["id"]]
    assertions.assert_pagination(filtered_meta, 10, 0, 1, False)


def test_a_replica_id_that_resolves_to_nothing_is_a_not_found_of_its_own_kind():
    """The existence rung answers with the replica's own error id.

    The PRD states: "Existence checks follow, in this internal order:
    `ERR_TALENT_NOT_FOUND` (a talent id from the path or body, as used by the talent
    read, the talent's estate-authority list and submission, the death record, and
    consent drafting)"; further along the same ladder sits
    "`ERR_DIGITAL_REPLICA_NOT_FOUND` (the replica read, approval for use, and the
    `digital_replica_id` on a performance submission)", and of that whole rung the
    PRD says: "Each of these rungs governs wherever an identifier of that type is
    accepted, and all of them carry HTTP 404."

    Design: Corner/entities/unknown_digital_replica_id_returns_not_found
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)

    validate_error(
        api_client.get_digital_replica(
            NON_EXISTENT_REPLICA_ID, scenario["admin_headers"]
        ),
        "ERR_DIGITAL_REPLICA_NOT_FOUND",
    )

    data, meta = validate_paginated(
        api_client.list_digital_replicas(
            scenario["admin_headers"], params={"talent_id": scenario["talent"]["id"]}
        )
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_a_missing_money_field_is_answered_before_the_stale_version_is_noticed():
    """The shape rung reports first, and no second grant is written.

    The PRD states: "Payload well-formedness comes next, yielding
    `ERR_INVALID_REQUEST` — every required field present, every enum value inside
    its declared set, integers not negative, monetary amounts sent as JSON numbers
    rather than strings, ISO 8601 datetimes parseable, percentage fields within 0
    through 1, required arrays non-empty, `limit` within 1 through 100 and `offset`
    not negative." The version rung sits far below it: "The two
    optimistic-concurrency rungs come after ownership and before any state check:
    `ERR_TALENT_VERSION_STALE` on consent drafting, then `ERR_REPLICA_VERSION_STALE`
    on license issuance."

    Design: Corner/entities/consent_grant_missing_required_field_is_rejected
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    talent = scenario["talent"]
    assert talent["version"] == 1

    good = factories.consent_grant_payload(talent["id"], 1, **fixtures.CAMPAIGN_GRANT)
    validate_success(
        api_client.create_consent_grant(good, scenario["admin_headers"]), 201
    )
    assert fixtures.read_talent(scenario)["version"] == 2

    incomplete = factories.consent_grant_payload(
        talent["id"], 2, **fixtures.CAMPAIGN_GRANT
    )
    incomplete.pop("per_use_base_fee_cents")
    validate_error(
        api_client.create_consent_grant(incomplete, scenario["admin_headers"]),
        "ERR_INVALID_REQUEST",
    )

    incomplete_and_stale = dict(incomplete, expected_talent_version=1)
    validate_error(
        api_client.create_consent_grant(
            incomplete_and_stale, scenario["admin_headers"]
        ),
        "ERR_INVALID_REQUEST",
    )

    grants, _meta = validate_paginated(
        api_client.list_consent_grants(
            scenario["admin_headers"], params={"talent_id": talent["id"]}
        )
    )
    assert len(grants) == 1


NON_UNION_GRANT = {
    "permitted_media_types": ["SOCIAL"],
    "territory_codes": ["US"],
    "permitted_use_notes": "Non-union social clip",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_until": "2027-08-01T00:00:00Z",
    "initial_creation_fee_cents": 100_000,
    "per_use_base_fee_cents": 50_000,
}


def test_an_unaffiliated_talent_needs_no_schedule_row_at_all():
    """union_code defaults to NONE, the floor is zero and the fee stands.

    The PRD states: "A `RightsAdministrator` creates one by supplying the
    performer's `legal_name` (1 to 200 characters, not blank), the
    `domicile_state_code` of legal domicile (exactly two uppercase letters), and
    optionally a `union_code`, which is `NONE`, `SAG_AFTRA` or `AFM` and defaults to
    `NONE`." The floor branch follows from that: "The floor is the
    `minimum_initial_cents` of the union row selected for the grant's affiliation,
    the governing media type and the grant's `effective_from`; when the grant carries
    no union affiliation the floor is zero and no lookup happens." The snapshot is
    null for such a talent: "`union_code_snapshot` is copied from the talent's
    `union_code` at draft time — null when the talent's affiliation is `NONE` — so
    that a later change of affiliation cannot retroactively move the floors that
    govern this grant."

    Design: Corner/entities/talent_union_code_defaults_to_none_and_skips_the_union_floor
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    talent = validate_success(
        api_client.create_talent(
            {"legal_name": "Nia Okafor", "domicile_state_code": "CA"},
            scenario["admin_headers"],
        ),
        201,
    )
    assert talent["union_code"] == "NONE"
    scenario["talent"] = talent
    scenario["talent_rep_headers"] = fixtures.make_talent_representative_headers(
        talent["id"]
    )

    fixtures.draft_consent_grant(scenario, NON_UNION_GRANT)
    assert scenario["grant"]["union_code_snapshot"] is None

    countersigned = fixtures.countersign_grant(scenario)["grant"]
    assertions.assert_subset_equal(
        countersigned,
        {
            "status": "ACTIVE",
            "initial_compensation_cents": 100_000,
            "union_topup_cents": 0,
            "total_compensation_cents": 100_000,
        },
    )

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(
        entries[0], "INITIAL_CREATION", 100_000, 75_000, 20_000, 5_000
    )


def test_the_retention_deadline_is_derived_at_registration_not_supplied():
    """The statute's 365 days bind ahead of the contract's grace period.

    The PRD states: "The statutory deadline is the asset's `created_at` advanced by
    the domicile profile's `biometric_retention_max_days`. The contractual deadline
    is the end of the consent term — `effective_end_actual` when the grant has ended,
    otherwise `effective_until` — advanced by that profile's `deletion_grace_days`.
    `retention_until` is whichever of the two comes first, and when the two coincide
    that shared instant is the answer." The worked case is this one: "An asset created
    on 1 August 2026 under a profile allowing 365 statutory days and 30 grace days, on
    a grant whose `effective_until` is 1 August 2027, has a statutory deadline of 1
    August 2027 and a contractual deadline of 31 August 2027, so `retention_until` is
    `2027-08-01T00:00:00Z` and the statute binds." The rest of the row starts empty:
    "A new asset is `STORED`, with `purge_due_at`, `purged_at` and `held_from_status`
    all null."

    Design: Corner/entities/biometric_asset_retention_until_is_computed_not_supplied
    """
    scenario = fixtures.campaign_stored_asset()

    asset = scenario["asset"]
    assertions.assert_subset_equal(
        asset,
        {
            "status": "STORED",
            "retention_until": "2027-08-01T00:00:00Z",
            "payload_digest": "sha256:aaa",
            "storage_class": "ENCRYPTED_VAULT",
        },
    )
    assertions.assert_fields_null(
        asset, "purge_due_at", "purged_at", "held_from_status"
    )


def test_version_starts_at_one_and_steps_when_a_draft_touches_the_talent():
    """Drafting a grant is a mutation of the talent, and the row says so.

    The PRD states: "Most resources additionally carry `updated_at`, of the same
    format, refreshed on every mutation, and `version`, an integer that starts at 1
    on creation and increases by exactly one on every mutation of that row —
    including mutations the row suffers as a side effect of an operation aimed at
    some other resource." Drafting is exactly such an operation: "The talent's
    `version` advances by one, which is why a client that drafts two grants in
    sequence must re-read the talent between them."

    Design: Corner/entities/system_fields_are_server_minted_on_talent_create
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    minted = scenario["talent"]
    assert minted["version"] == 1

    fixtures.move_clock("2026-08-02T00:00:00Z", scenario["admin_headers"])
    fixtures.draft_consent_grant(scenario, fixtures.CAMPAIGN_GRANT)

    mutated = fixtures.read_talent(scenario)
    assert mutated["version"] == 2
    assert mutated["created_at"] == minted["created_at"]
    assert mutated["updated_at"] > mutated["created_at"]

    grant = scenario["grant"]
    assert is_valid_uuid(grant["id"])
    assert grant["id"] != minted["id"]
    assert grant["version"] == 1


def test_an_asset_kind_outside_the_declared_set_stores_nothing():
    """TATTOO_SCAN fails the shape rung; VOICE_SAMPLE on the same body passes.

    The PRD states: "The payload record names its subject through `talent_id` and
    its authority through `consent_grant_id`, declares `asset_kind` as `FACE_SCAN`,
    `VOICE_SAMPLE` or `MOTION_CAPTURE`, carries a `capture_ref` pointing at the
    capture session record (1 to 120 characters, not blank), declares `storage_class`
    as either `ENCRYPTED_VAULT` (the default) or `COLD_ARCHIVE`, and carries a
    `payload_digest` of the stored payload (1 to 128 characters, non-blank at
    creation)." An out-of-set value is a shape failure: "Payload well-formedness
    comes next, yielding `ERR_INVALID_REQUEST` — every required field present, every
    enum value inside its declared set, integers not negative, monetary amounts sent
    as JSON numbers rather than strings, ISO 8601 datetimes parseable, percentage
    fields within 0 through 1, required arrays non-empty, `limit` within 1 through
    100 and `offset` not negative."

    Design: Corner/entities/invalid_asset_kind_enum_value_is_rejected
    """
    scenario = fixtures.campaign_active_grant()
    payload = factories.biometric_asset_payload(
        scenario["talent"]["id"],
        scenario["grant"]["id"],
        asset_kind="TATTOO_SCAN",
        capture_ref="cap-bad",
        payload_digest="sha256:zzz",
    )

    validate_error(
        api_client.create_biometric_asset(payload, scenario["admin_headers"]),
        "ERR_INVALID_REQUEST",
    )

    stored, meta = validate_paginated(
        api_client.list_biometric_assets(
            scenario["admin_headers"],
            params={"talent_id": scenario["talent"]["id"]},
        )
    )
    assert stored == []
    assert meta["total_count"] == 0

    accepted = validate_success(
        api_client.create_biometric_asset(
            dict(payload, asset_kind="VOICE_SAMPLE"), scenario["admin_headers"]
        ),
        201,
    )
    assert accepted["asset_kind"] == "VOICE_SAMPLE"


def test_a_ledger_row_carries_no_version_and_no_write_endpoint():
    """The entry read exposes id and created_at and nothing mutable.

    The PRD states: "A `CompensationEntry` is a ledger movement: once appended it is
    never modified, and a movement that stops being correct is undone by appending an
    opposing entry. These three carry only `id` and `created_at` alongside their own
    fields." The collection is reachable only as a consequence: "Ledger entries have
    no write endpoint of their own; they exist only as consequences of workflow
    operations, and the collection read is the only channel through which a
    cascade-created reversal can be discovered."

    Design: Corner/entities/compensation_entry_is_append_only_with_no_version_field
    """
    scenario = fixtures.campaign_active_grant()
    listed = fixtures.grant_ledger(scenario)
    assert len(listed) == 1

    entry = validate_success(
        api_client.get_compensation_entry(listed[0]["id"], scenario["admin_headers"])
    )

    assertions.assert_immutable_record(entry)
    assertions.assert_fields_absent(entry, "version", "updated_at")
    assertions.assert_ledger_entry(entry, "INITIAL_CREATION", 300_000)
    assert entry["reverses_entry_id"] is None


def test_a_dangling_grant_reference_is_reported_by_its_own_existence_rung():
    """The valid talent does not save a body naming a grant that is not there.

    The PRD states: "Existence checks follow, in this internal order:
    `ERR_TALENT_NOT_FOUND` (a talent id from the path or body, as used by the talent
    read, the talent's estate-authority list and submission, the death record, and
    consent drafting); `ERR_ESTATE_AUTHORITY_NOT_FOUND` (estate-authority
    verification, and the `estate_authority_id` supplied on a consent draft);
    `ERR_CONSENT_GRANT_NOT_FOUND` (the grant read, countersign, suspension and
    revoke, plus the `consent_grant_id` supplied when registering a biometric asset
    or building a replica)". Of that whole rung it says: "Each of these rungs governs
    wherever an identifier of that type is accepted, and all of them carry HTTP 404."

    Design: Corner/entities/biometric_asset_rejects_unknown_consent_grant_foreign_key
    """
    scenario = fixtures.register_state_law_profile(overrides=fixtures.CAMPAIGN_PROFILE)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    talent_id = scenario["talent"]["id"]

    validate_error(
        api_client.create_biometric_asset(
            factories.biometric_asset_payload(
                talent_id, NON_EXISTENT_GRANT_ID, asset_kind="VOICE_SAMPLE"
            ),
            scenario["admin_headers"],
        ),
        "ERR_CONSENT_GRANT_NOT_FOUND",
    )

    _stored, meta = validate_paginated(
        api_client.list_biometric_assets(
            scenario["admin_headers"], params={"talent_id": talent_id}
        )
    )
    assert meta["total_count"] == 0

    validate_error(
        api_client.create_biometric_asset(
            factories.biometric_asset_payload(
                NON_EXISTENT_TALENT_ID, NON_EXISTENT_GRANT_ID, asset_kind="VOICE_SAMPLE"
            ),
            scenario["admin_headers"],
        ),
        "ERR_TALENT_NOT_FOUND",
    )
