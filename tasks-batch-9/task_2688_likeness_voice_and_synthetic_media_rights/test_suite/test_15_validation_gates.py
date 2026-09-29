"""Ranked labels, day-boundary terms, per-state surcharges and stacked source checks."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

INSUFFICIENT_PLACEMENTS = ("METADATA_ONLY", "END_CARD")

SUFFICIENT_PLACEMENTS = (
    ("PRE_ROLL", "Voice generated with Ava Reyes' licensed digital replica"),
    ("PERSISTENT_BUG", "Synthetic voice — licensed"),
)


def _attest(scenario, placement, label_text="AI voice used"):
    """Attest one placement without asserting the outcome."""
    return api_client.attest_disclosure(
        scenario["license"]["id"],
        factories.disclosure_payload(
            disclosure_placement=placement, disclosure_label_text=label_text
        ),
        scenario["licensee_headers"],
    )


def test_a_label_one_rank_short_of_the_state_minimum_is_still_refused():
    """Rank 1 and rank 2 both fail a minimum of 3, and nothing is stored.

    The PRD states: "The attested placement's rank on the four-rung ladder must be
    at least the domicile profile's minimum rank for this license's `channel`, drawn
    from `min_disclosure_rank_advertising` for an `ADVERTISING` license and
    `min_disclosure_rank_entertainment` for an `ENTERTAINMENT` one; a placement below
    that minimum is refused with `ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT`." The ladder
    is ordered by the profile's own description of it: "`min_disclosure_rank_advertising`
    and `min_disclosure_rank_entertainment`, each from 1 through 4, give the minimum
    acceptable disclosure placement for each channel on a fixed four-rung ladder:
    `METADATA_ONLY` is rank 1, `END_CARD` is rank 2, `PRE_ROLL` is rank 3 and
    `PERSISTENT_BUG` is rank 4, so a higher rank is a more prominent disclosure." Only
    a successful attestation
    writes anything: "A successful attestation moves `compliance_status` from
    `PENDING_LABEL → LABELED` or from `NON_COMPLIANT → LABELED`, stores both attested
    fields, resets `disclosure_verified_by_user_id` to null, and advances the
    license's `version` by one." With the compliance dimension where it started, the
    distribution move is unavailable: "Four conditions guard it: the license must be
    `ISSUED`, or `ERR_INVALID_LICENSE_STATE`; `compliance_status` must be `VERIFIED`,
    or `ERR_DISCLOSURE_NOT_VERIFIED`".

    Design: Corner/validations/disclosure_placement_below_the_state_minimum_rank_is_refused
    """
    scenario = fixtures.campaign_issued_license()
    issued_version = scenario["license"]["version"]
    assert scenario["license"]["compliance_status"] == "PENDING_LABEL"

    for placement in INSUFFICIENT_PLACEMENTS:
        validate_error(
            _attest(scenario, placement), "ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT"
        )

    unlabelled = fixtures.refresh_license(scenario)
    assert unlabelled["compliance_status"] == "PENDING_LABEL"
    assertions.assert_fields_null(
        unlabelled, "disclosure_placement", "disclosure_label_text"
    )
    assertions.assert_versioned(unlabelled, issued_version)

    fixtures.move_clock("2026-09-01T00:00:00Z", scenario["admin_headers"])
    refused = api_client.go_live(
        unlabelled["id"], factories.go_live_payload(), scenario["licensee_headers"]
    )
    validate_error(refused, "ERR_DISCLOSURE_NOT_VERIFIED")
    assert fixtures.refresh_license(scenario)["distribution_status"] == "ISSUED"


def test_the_minimum_rank_is_a_floor_that_its_own_value_satisfies():
    """PRE_ROLL meets a minimum of 3; the stricter placement is accepted too.

    The PRD states: "The attested placement's rank on the four-rung ladder must be
    at least the domicile profile's minimum rank for this license's `channel`, drawn
    from `min_disclosure_rank_advertising` for an `ADVERTISING` license and
    `min_disclosure_rank_entertainment` for an `ENTERTAINMENT` one; a placement below
    that minimum is refused with `ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT`." Attesting
    twice is the cycle this dimension allows: "Attestation is admissible when
    `compliance_status` is `PENDING_LABEL` or `NON_COMPLIANT` — re-attestation after
    a rejection is the cycle in this dimension — and is refused with
    `ERR_INVALID_DISCLOSURE_STATE` when the license is already `LABELED` or
    `VERIFIED`." Neither attestation touches the other dimension or the ledger: "A
    usage license carries two status dimensions on one row, and they advance
    independently."

    Design: Corner/validations/disclosure_placement_exactly_at_the_state_minimum_rank_passes
    """
    scenario = fixtures.campaign_issued_license()

    at_the_floor = validate_success(_attest(scenario, *SUFFICIENT_PLACEMENTS[0]), 200)
    assert at_the_floor["compliance_status"] == "LABELED"
    assert at_the_floor["disclosure_placement"] == "PRE_ROLL"
    assert at_the_floor["disclosure_label_text"] == SUFFICIENT_PLACEMENTS[0][1]
    assert at_the_floor["distribution_status"] == "ISSUED"

    fixtures.verify_disclosure(scenario, "REJECT")
    above_the_floor = validate_success(_attest(scenario, *SUFFICIENT_PLACEMENTS[1]), 200)
    assert above_the_floor["compliance_status"] == "LABELED"
    assert above_the_floor["disclosure_placement"] == "PERSISTENT_BUG"
    assertions.assert_fields_null(above_the_floor, "disclosure_verified_by_user_id")
    assert above_the_floor["distribution_status"] == "ISSUED"

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL"]
    )


REFUSED_TERMS = (
    ("29 day term", "2026-08-30T00:00:00Z"),
    ("zero length term", "2026-08-01T00:00:00Z"),
)


def _draft(scenario, expected_talent_version, notes, effective_until):
    """Draft one grant over the standard fees without asserting the outcome."""
    return api_client.create_consent_grant(
        factories.consent_grant_payload(
            scenario["talent"]["id"],
            expected_talent_version,
            permitted_use_notes=notes,
            effective_until=effective_until,
        ),
        scenario["admin_headers"],
    )


def test_the_thirty_day_minimum_is_inclusive_and_the_refusals_cost_no_version():
    """Twenty-nine days and zero days fail; thirty days passes on the same pin.

    The PRD states: "The term runs from `effective_from` inclusive to
    `effective_until` exclusive; `effective_until` must be strictly after
    `effective_from`, and the term must span at least thirty days, or the draft is
    refused with `ERR_CONSENT_TERM_INVALID`." Only the accepted draft moves the
    subject: "Drafting stamps `status` as `PENDING_COUNTERSIGN`, records the drafting
    administrator as `drafted_by_user_id`, leaves `suspension_reason`,
    `countersigned_at` and `effective_end_actual` null, and initialises
    `initial_compensation_cents`, `union_topup_cents` and `total_compensation_cents`
    to zero. The talent's `version` advances by one, which is why a client that
    drafts two grants in sequence must re-read the talent between them."

    Design: Corner/validations/consent_term_shorter_than_the_minimum_is_refused_at_the_day_boundary
    """
    scenario = fixtures.register_state_law_profile()
    fixtures.register_union_minimum(scenario, fixtures.SAG_ADVERTISING_ROW)
    fixtures.create_talent(scenario, fixtures.CAMPAIGN_TALENT)
    pinned = scenario["talent"]["version"]
    assert pinned == 1

    for notes, effective_until in REFUSED_TERMS:
        validate_error(
            _draft(scenario, pinned, notes, effective_until), "ERR_CONSENT_TERM_INVALID"
        )
        assertions.assert_versioned(fixtures.read_talent(scenario), pinned)

    accepted = validate_success(
        _draft(scenario, pinned, "30 day term", "2026-08-31T00:00:00Z"), 201
    )
    assert accepted["status"] == "PENDING_COUNTERSIGN"
    assert accepted["effective_from"] == "2026-08-01T00:00:00Z"
    assert accepted["effective_until"] == "2026-08-31T00:00:00Z"
    assert accepted["total_compensation_cents"] == 0
    assertions.assert_versioned(fixtures.read_talent(scenario), pinned + 1)

    listed, meta = validate_paginated(
        api_client.list_consent_grants(
            scenario["admin_headers"], params={"talent_id": scenario["talent"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [accepted["id"]]


TX_NO_LABELLING = {
    "state_code": "TX",
    "postmortem_rights_years": 0,
    "postmortem_requires_registration": False,
    "biometric_retention_max_days": 3650,
    "deletion_grace_days": 10,
    "removal_window_days": 21,
    "disclosure_required_advertising": False,
    "disclosure_required_entertainment": False,
    "min_disclosure_rank_advertising": 1,
    "min_disclosure_rank_entertainment": 1,
}

EVERY_MEDIA_TYPE = ["ADVERTISING", "FEATURE_FILM", "EPISODIC", "VIDEO_GAME", "SOCIAL"]

FEATURE_GRANT = dict(
    fixtures.CAMPAIGN_GRANT,
    permitted_media_types=EVERY_MEDIA_TYPE,
    territory_codes=["US"],
    permitted_use_notes="Feature background performance",
)

FEATURE_PERFORMANCE = dict(
    fixtures.CAMPAIGN_PERFORMANCE,
    licensee_name="Lone Star Pictures",
    media_type="FEATURE_FILM",
    territory_codes=["US"],
    intended_use_description="crowd scene double",
    projected_impressions=12_000_000,
)

FEATURE_LICENSE = dict(
    fixtures.CAMPAIGN_LICENSE, channel="ENTERTAINMENT", territory_codes=["US"]
)

END_CARD_LABEL = {
    "disclosure_placement": "END_CARD",
    "disclosure_label_text": "Contains a licensed digital double",
}


def _entertainment_licence(scenario, talent_overrides, suffix):
    """Take one non-union talent all the way to an issued ENTERTAINMENT licence."""
    fixtures.create_talent(scenario, talent_overrides)
    fixtures.draft_consent_grant(scenario, FEATURE_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(
        scenario,
        dict(
            fixtures.CAMPAIGN_ASSET,
            asset_kind="FACE_SCAN",
            capture_ref="cap-" + suffix,
            payload_digest="sha256:" + suffix,
        ),
    )
    fixtures.build_replica(
        scenario,
        dict(
            fixtures.CAMPAIGN_REPLICA,
            replica_kind="FULL_PERFORMANCE",
            build_ref="build-" + suffix,
        ),
    )
    fixtures.approve_replica(scenario)
    fixtures.submit_performance(scenario, FEATURE_PERFORMANCE)
    fixtures.review_performance(scenario, "APPROVE")
    fixtures.issue_license(scenario, FEATURE_LICENSE)
    return scenario


def _the_same_licence_in_texas_and_california():
    """Two structurally identical feature licences, differing only in domicile."""
    texas = fixtures.register_state_law_profile(overrides=TX_NO_LABELLING)
    fixtures.register_state_law_profile(texas)
    california = fixtures.new_scenario()
    _entertainment_licence(texas, {"legal_name": "Tex Alvarez", "domicile_state_code": "TX"}, "tx")
    _entertainment_licence(california, {"legal_name": "Cal Osei"}, "ca")
    return texas, california


def test_the_identical_subtotal_carries_a_surcharge_only_in_the_labelling_state():
    """370500 both times; 0 and VERIFIED in Texas, 4632 and PENDING_LABEL in California.

    The PRD states: "It also resolves the disclosure obligation from the talent's
    domicile profile: `disclosure_required` is taken from that profile's
    `disclosure_required_advertising` when `channel` is `ADVERTISING` and from
    `disclosure_required_entertainment` when `channel` is `ENTERTAINMENT`. When
    disclosure is required, `compliance_status` starts at `PENDING_LABEL`; when it is
    not required, `compliance_status` starts directly at `VERIFIED`, since there is
    nothing to label and nothing to check. `disclosure_placement`,
    `disclosure_label_text` and `disclosure_verified_by_user_id` all start null, as do
    `removal_deadline`, `removal_reason` and `removal_confirmed_at`." The same flag
    sets the rate: "The subtotal is `per_use_final_cents` alone. The surcharge rate is
    zero when `disclosure_required` is false; otherwise it is 0.0175 for an
    `ADVERTISING` license and 0.0125 for an `ENTERTAINMENT` one." The direction of that
    rounding is the one exception in the system: "The single exception is the clearance
    office's compliance surcharge, which is rounded up to the next whole cent rather
    than half up, in the compliance fund's favour." Twelve million impressions in one
    territory on a feature compose 150000 by 1.90, 1.30 and 1.00, which is 370500, and
    370500 times 0.0125 is 4631.25, so the surcharge is 4632.

    Design: Corner/validations/disclosure_and_surcharge_apply_only_where_the_state_requires_labelling
    """
    texas, california = _the_same_licence_in_texas_and_california()

    for scenario in (texas, california):
        assert scenario["license"]["per_use_final_cents"] == 370_500
        assert scenario["license"]["distribution_status"] == "ISSUED"

    lone_star = texas["license"]
    assert lone_star["disclosure_required"] is False
    assert lone_star["compliance_surcharge_cents"] == 0
    assert lone_star["license_total_cents"] == 370_500
    assert lone_star["compliance_status"] == "VERIFIED"

    golden_state = california["license"]
    assert golden_state["disclosure_required"] is True
    assert golden_state["compliance_surcharge_cents"] == 4632
    assert golden_state["license_total_cents"] == 375_132
    assert golden_state["compliance_status"] == "PENDING_LABEL"
    assertions.assert_fields_null(
        golden_state,
        "disclosure_placement",
        "disclosure_label_text",
        "disclosure_verified_by_user_id",
    )


def test_only_the_labelling_state_holds_the_launch_and_no_surcharge_is_booked():
    """Texas goes live with no label at all; California must earn its VERIFIED first.

    The PRD states: "Four conditions guard it: the license must be `ISSUED`, or
    `ERR_INVALID_LICENSE_STATE`; `compliance_status` must be `VERIFIED`, or
    `ERR_DISCLOSURE_NOT_VERIFIED`; the current logical instant must lie inside the
    closed window from `distribution_start` through `distribution_end` inclusive, or
    `ERR_OUTSIDE_DISTRIBUTION_WINDOW`; and the governing grant must still be `ACTIVE`,
    or `ERR_CONSENT_NOT_ACTIVE`." The money the licensee pays for labelling never
    reaches the parties, because the ledger's vocabulary has no room for it: "Every
    entry carries an `entry_type`, one of `INITIAL_CREATION`, `UNION_TOPUP`,
    `PER_USE_PROVISIONAL`, `PER_USE_FINAL` or `REVERSAL`; a signed `amount_cents`,
    which is negative only on a `REVERSAL`; a machine-generated `memo` explaining why
    the entry was posted; and `posted_at`, the logical instant at which it was
    appended." What issuance does post is the royalty alone: "The result is written to
    `per_use_final_cents` and posted as a `PER_USE_FINAL` ledger entry split three
    ways."

    Design: Corner/validations/disclosure_and_surcharge_apply_only_where_the_state_requires_labelling
    """
    texas, california = _the_same_licence_in_texas_and_california()
    fixtures.move_clock("2026-09-01T00:00:00Z", texas["admin_headers"])

    unlabelled_launch = fixtures.go_live(texas)
    assert unlabelled_launch["distribution_status"] == "LIVE"
    assertions.assert_fields_null(unlabelled_launch, "disclosure_placement")

    held = api_client.go_live(
        california["license"]["id"],
        factories.go_live_payload(),
        california["licensee_headers"],
    )
    validate_error(held, "ERR_DISCLOSURE_NOT_VERIFIED")
    assert fixtures.refresh_license(california)["distribution_status"] == "ISSUED"

    fixtures.attest_disclosure(california, END_CARD_LABEL)
    fixtures.verify_disclosure(california, "ACCEPT")
    released = fixtures.go_live(california)
    assert released["distribution_status"] == "LIVE"
    assert released["compliance_surcharge_cents"] == 4632

    for scenario in (texas, california):
        entries = fixtures.grant_ledger(scenario)
        assertions.assert_entry_types(
            entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL"]
        )
        assertions.assert_ledger_entry(entries[2], "PER_USE_FINAL", 370_500)


GRANT_ONE = dict(
    fixtures.CAMPAIGN_GRANT, territory_codes=["US"], permitted_use_notes="Grant one"
)

GRANT_TWO = dict(
    fixtures.CAMPAIGN_GRANT, territory_codes=["US"], permitted_use_notes="Grant two"
)


def _two_grants_each_holding_one_sample():
    """One non-union talent, two active grants, and a voice sample under each."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, GRANT_ONE)
    fixtures.countersign_grant(scenario)
    first_grant = scenario["grant"]
    fixtures.register_biometric_asset(
        scenario,
        dict(fixtures.CAMPAIGN_ASSET, capture_ref="cap-g1", payload_digest="sha256:a01"),
    )
    first_sample = scenario["asset"]
    fixtures.draft_consent_grant(scenario, GRANT_TWO)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(
        scenario,
        dict(fixtures.CAMPAIGN_ASSET, capture_ref="cap-g2", payload_digest="sha256:a02"),
    )
    second_sample = scenario["asset"]
    scenario["grant"] = first_grant
    return scenario, first_sample, second_sample


def _build(scenario, source_asset_ids, build_ref, omit_sources=False):
    """Ask for a voice replica under the first grant without asserting the outcome."""
    payload = factories.digital_replica_payload(
        scenario["talent"]["id"],
        scenario["grant"]["id"],
        source_asset_ids,
        replica_kind="VOICE",
        build_ref=build_ref,
    )
    if omit_sources:
        payload.pop("source_asset_ids")
    return api_client.create_digital_replica(payload, scenario["admin_headers"])


def _talent_replicas(scenario):
    """Every replica standing against the scenario's talent."""
    return validate_paginated(
        api_client.list_digital_replicas(
            scenario["admin_headers"], params={"talent_id": scenario["talent"]["id"]}
        )
    )


def test_an_unknown_source_is_a_not_found_and_the_lower_rungs_wait_their_turn():
    """404, then the duplicate, then the cross-grant member, then the clean build.

    The PRD states: "Next, if any member belongs to a different `consent_grant_id` or
    a different `talent_id` than the replica being built, the build is refused with
    `ERR_ASSET_CONSENT_MISMATCH`, because material captured under one grant may not be
    reused under another. Finally, an empty `source_asset_ids` or one containing
    duplicate identifiers is refused with `ERR_NO_SOURCE_ASSETS`. A member naming no
    asset at all is a not-found failure and is reported earlier still." That earlier
    rung is named with the list it guards: "`ERR_BIOMETRIC_ASSET_NOT_FOUND` (the asset
    read, the manual purge, and every member of `source_asset_ids` on a replica
    build)". A build that clears all three rungs lands where the PRD says it does: "A
    new replica is `BUILT` with `open_license_count` at zero and `approved_at`,
    `approved_by_user_id`, `quarantine_reason` and `held_from_status` all null."

    Design: Corner/validations/source_asset_checks_run_existence_then_shape_then_ownership
    """
    scenario, first_sample, second_sample = _two_grants_each_holding_one_sample()

    validate_error(
        _build(scenario, [NON_EXISTENT_UUID], "build-unknown"),
        "ERR_BIOMETRIC_ASSET_NOT_FOUND",
    )
    validate_error(
        _build(scenario, [first_sample["id"], first_sample["id"]], "build-dupe"),
        "ERR_NO_SOURCE_ASSETS",
    )
    validate_error(
        _build(scenario, [first_sample["id"], second_sample["id"]], "build-mixed"),
        "ERR_ASSET_CONSENT_MISMATCH",
    )

    built = validate_success(_build(scenario, [first_sample["id"]], "build-good"), 201)
    assert built["status"] == "BUILT"
    assert built["source_asset_ids"] == [first_sample["id"]]
    assert built["consent_grant_id"] == scenario["grant"]["id"]
    assertions.assert_versioned(built, 1)


def test_a_missing_source_list_is_malformed_and_the_refusals_leave_no_replica():
    """Dropping the key is a 400, and only the one good build survives.

    The PRD states: "Payload well-formedness comes next, yielding `ERR_INVALID_REQUEST`
    — every required field present, every enum value inside its declared set, integers
    not negative, monetary amounts sent as JSON numbers rather than strings, ISO 8601
    datetimes parseable, percentage fields within 0 through 1, required arrays
    non-empty, `limit` within 1 through 100 and `offset` not negative." The list is a
    required field of the build: "The build names its subject through `talent_id` and
    its authority through `consent_grant_id`, declares `replica_kind` as `FACE`,
    `VOICE` or `FULL_PERFORMANCE`, carries a `build_ref` pointing at the model build
    artifact (1 to 120 characters, not blank), and lists the material it was trained
    from in `source_asset_ids`, from 1 through 10 distinct biometric asset
    identifiers."

    Design: Corner/validations/source_asset_checks_run_existence_then_shape_then_ownership
    """
    scenario, first_sample, second_sample = _two_grants_each_holding_one_sample()
    built = validate_success(_build(scenario, [first_sample["id"]], "build-good"), 201)

    validate_error(
        _build(scenario, [first_sample["id"]], "build-no-key", omit_sources=True),
        "ERR_INVALID_REQUEST",
    )
    validate_error(
        _build(scenario, [first_sample["id"], first_sample["id"]], "build-dupe"),
        "ERR_NO_SOURCE_ASSETS",
    )

    listed, meta = _talent_replicas(scenario)
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [built["id"]]
