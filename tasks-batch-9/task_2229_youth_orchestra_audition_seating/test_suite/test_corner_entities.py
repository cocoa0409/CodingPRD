"""Entity-level PRD compliance: creation defaults, derived fields, reads,
listing envelopes, schema rejection and foreign-key resolution."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    REGISTRAR_HEADERS,
    guardian_headers,
    panelist_headers,
)


# ---------------------------------------------------------------------------
# Season creation and retrieval
# ---------------------------------------------------------------------------

def test_season_creation_seeds_planning_status_aid_pool_and_counters(api):
    """A brand-new season is born in PLANNING with its aid halves and ensemble counters seeded.

    PRD §3.1: "The season is born in `PLANNING`, with `aid_committed_cents` at 0, `aid_available_cents` equal to `aid_budget_cents`, `ensemble_count` and `seated_ensemble_count` both 0, and `version` 1."

    Design: Corner/entities/season_creation_returns_planning_state_and_derived_counters
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_season(
        F.season_payload(
            name="2026-2027 Season",
            year_label="2026-27",
            tuition_base_cents=123223,
            aid_budget_cents=100000,
        ),
        DIRECTOR_HEADERS,
    )
    season = validate_success(response, 201)

    assert season["status"] == "PLANNING"
    assert season["aid_budget_cents"] == 100000
    assert season["aid_committed_cents"] == 0
    assert season["aid_available_cents"] == 100000
    assert season["ensemble_count"] == 0
    assert season["seated_ensemble_count"] == 0
    A.assert_aid_pool_conserved(season)
    A.assert_common_fields(season, expected_version=1)


def test_season_read_returns_created_row_with_version_still_one(api):
    """Reading a season is not a mutation, so the stored row comes back untouched at version 1.

    PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO 8601 UTC timestamp of the same shape refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and increments by one on every mutation of that row — including mutations the server performs on its own initiative, such as a derived counter changing because a child row was created."

    Design: Corner/entities/season_retrieval_returns_stored_row_unchanged
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    created = X.create_season(api, name="2026-2027 Season", year_label="2026-27")

    season = validate_success(api.get_season(created["id"], REGISTRAR_HEADERS))

    assert season["id"] == created["id"]
    assert season["name"] == "2026-2027 Season"
    assert season["status"] == "PLANNING"
    assert season["version"] == 1
    assert season["updated_at"] == created["updated_at"]
    A.assert_instants_equal(
        season["audition_window_start"], C.SEASON_AUDITION_WINDOW_START
    )
    A.assert_instants_equal(season["audition_window_end"], C.SEASON_AUDITION_WINDOW_END)
    A.assert_instants_equal(season["tuition_due_at"], C.SEASON_TUITION_DUE_AT)
    assert season["aid_available_cents"] == C.SEASON_AID_BUDGET_CENTS


# ---------------------------------------------------------------------------
# List envelope
# ---------------------------------------------------------------------------

def test_panelist_list_meta_carries_limit_offset_total_and_has_more(api):
    """Paging three adjudicators two at a time exposes all four pagination fields consistently.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/panelist_listing_paginates_with_total_count_and_has_more
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    X.create_panelists(api, count=3, instrument_expertise="VIOLIN")

    first_rows, first_meta = validate_paginated(
        api.list_panelists(REGISTRAR_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    A.assert_pagination_meta(first_meta, 2, 0, 3, True)

    second_rows, second_meta = validate_paginated(
        api.list_panelists(REGISTRAR_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    A.assert_pagination_meta(second_meta, 2, 2, 3, False)

    assert {row["id"] for row in first_rows}.isdisjoint(
        {row["id"] for row in second_rows}
    )


def test_panelist_list_without_pagination_arguments_uses_default_limit(api):
    """A list call that supplies no pagination arguments reports the declared default limit of 10.

    PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100."

    Design: Corner/entities/panelist_listing_paginates_with_total_count_and_has_more
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    X.create_panelists(api, count=3, instrument_expertise="VIOLIN")

    rows, meta = validate_paginated(api.list_panelists(REGISTRAR_HEADERS))

    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_panelist_optional_inputs_take_declared_defaults(api):
    """An adjudicator registered with only the two mandatory inputs defaults its three optional ones.

    PRD §3.2: "Each **Panelist** is registered with a `display_name` and an `instrument_expertise` drawn from the instrument enumeration, plus three optional inputs: a `panel_role` of `ADJUDICATOR` (the default) or `CHAIR`, where a chair scores blind like everyone else and may additionally sign the panel sheet; `conflict_member_ids`, an array of musician identifiers the adjudicator privately teaches, defaulting to empty; and `available_for_panels`, defaulting to true, which controls whether the adjudicator may be seated on new panels."

    Design: Corner/entities/panelist_listing_paginates_with_total_count_and_has_more
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_panelist(
        F.panelist_payload(display_name="Panel One", instrument_expertise="VIOLIN"),
        DIRECTOR_HEADERS,
    )
    panelist = validate_success(response, 201)

    assert panelist["display_name"] == "Panel One"
    assert panelist["instrument_expertise"] == "VIOLIN"
    assert panelist["panel_role"] == "ADJUDICATOR"
    assert panelist["conflict_member_ids"] == []
    assert panelist["available_for_panels"] is True

    rows, _ = validate_paginated(api.list_panelists(REGISTRAR_HEADERS))
    assert len(rows) == 1
    assert rows[0]["panel_role"] == "ADJUDICATOR"
    assert rows[0]["conflict_member_ids"] == []
    assert rows[0]["available_for_panels"] is True


# ---------------------------------------------------------------------------
# Path identifier resolution
# ---------------------------------------------------------------------------

def test_unknown_member_path_id_reports_member_not_found(api):
    """Reading a musician by an unknown identifier returns the Member family's own not-found code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/member_and_placement_reads_with_unknown_id_return_not_found
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    body = validate_error(
        api.get_member(NON_EXISTENT_UUID, REGISTRAR_HEADERS),
        ApiErrorId.ERR_MEMBER_NOT_FOUND.value,
    )
    assert body["message"]


def test_unknown_placement_path_id_reports_placement_not_found(api):
    """Reading a placement by an unknown identifier returns the Placement family's own not-found code.

    PRD §2.9: "Each resource family has exactly one not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_ENSEMBLE_NOT_FOUND`, `ERR_SECTION_QUOTA_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_AUDITION_SLOT_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`, `ERR_PANEL_SCORE_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_TUITION_ACCOUNT_NOT_FOUND`, `ERR_ENSEMBLE_EVENT_NOT_FOUND`, and `ERR_PARTICIPATION_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/member_and_placement_reads_with_unknown_id_return_not_found
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    body = validate_error(
        api.get_placement(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value,
    )
    assert body["message"]


# ---------------------------------------------------------------------------
# Body schema validation
# ---------------------------------------------------------------------------

def test_ensemble_creation_without_tier_is_rejected_and_persists_nothing(api):
    """Omitting the mandatory ensemble tier is a body-schema failure and no ensemble row survives.

    PRD §2.10: "Body schema validation covers missing required fields, enum values that are not declared members, integers outside the ranges stated in §3, datetimes that do not parse as ISO 8601 UTC, an `end_at` that is not strictly later than its `start_at`, array cardinality violations on `panelist_ids` and `excerpt_ids`, and a `quorum_required` larger than the number of entries in `panelist_ids`."

    Design: Corner/entities/ensemble_and_quota_creation_missing_required_fields_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    X.create_ensemble(api, season["id"], name="Philharmonic")

    response = api.create_ensemble(
        F.ensemble_payload(season["id"], name="No Tier", tier=None), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_ensembles(DIRECTOR_HEADERS, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["name"] == "Philharmonic"


def test_section_quota_creation_without_max_count_is_rejected(api):
    """Omitting the mandatory section max_count is a body-schema failure and no section row survives.

    PRD §2.10: "Body schema validation covers missing required fields, enum values that are not declared members, integers outside the ranges stated in §3, datetimes that do not parse as ISO 8601 UTC, an `end_at` that is not strictly later than its `start_at`, array cardinality violations on `panelist_ids` and `excerpt_ids`, and a `quorum_required` larger than the number of entries in `panelist_ids`."

    Design: Corner/entities/ensemble_and_quota_creation_missing_required_fields_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    response = api.create_section_quota(
        F.section_quota_payload(
            ensemble["id"], instrument="VIOLIN", min_count=1, target_count=1, max_count=None
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_section_quotas(DIRECTOR_HEADERS, params={"ensemble_id": ensemble["id"]})
    )
    assert meta["total_count"] == 0


def test_member_grade_level_above_declared_range_is_rejected(api):
    """A grade_level of 13 falls outside the declared 4-to-12 range and no musician is persisted.

    PRD §2.10: "Body schema validation covers missing required fields, enum values that are not declared members, integers outside the ranges stated in §3, datetimes that do not parse as ISO 8601 UTC, an `end_at` that is not strictly later than its `start_at`, array cardinality violations on `panelist_ids` and `excerpt_ids`, and a `quorum_required` larger than the number of entries in `panelist_ids`."

    Design: Corner/entities/out_of_range_enum_and_interval_inputs_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_member(
        F.member_payload(
            legal_name="Too Senior",
            primary_instrument="VIOLIN",
            grade_level=13,
            graduation_year=2028,
            household_income_band="BAND_B",
        ),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_members(REGISTRAR_HEADERS))
    assert meta["total_count"] == 0


def test_member_primary_instrument_outside_enumeration_is_rejected(api):
    """A primary_instrument that is not a declared enum member is a body-schema failure.

    PRD §2.10: "Body schema validation covers missing required fields, enum values that are not declared members, integers outside the ranges stated in §3, datetimes that do not parse as ISO 8601 UTC, an `end_at` that is not strictly later than its `start_at`, array cardinality violations on `panelist_ids` and `excerpt_ids`, and a `quorum_required` larger than the number of entries in `panelist_ids`."

    Design: Corner/entities/out_of_range_enum_and_interval_inputs_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_member(
        F.member_payload(
            legal_name="Bad Enum",
            primary_instrument="GUITAR",
            grade_level=10,
            graduation_year=2028,
            household_income_band="BAND_B",
        ),
        REGISTRAR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_members(REGISTRAR_HEADERS))
    assert meta["total_count"] == 0


def test_event_with_end_at_equal_to_start_at_is_rejected(api):
    """An event interval that is not strictly positive is a body-schema failure.

    PRD §2.10: "Body schema validation covers missing required fields, enum values that are not declared members, integers outside the ranges stated in §3, datetimes that do not parse as ISO 8601 UTC, an `end_at` that is not strictly later than its `start_at`, array cardinality violations on `panelist_ids` and `excerpt_ids`, and a `quorum_required` larger than the number of entries in `panelist_ids`."

    Design: Corner/entities/out_of_range_enum_and_interval_inputs_rejected
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    response = api.create_ensemble_event(
        F.ensemble_event_payload(
            ensemble["id"],
            kind="REHEARSAL",
            start_at="2026-09-05T18:00:00Z",
            end_at="2026-09-05T18:00:00Z",
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_ensemble_events(DIRECTOR_HEADERS, params={"ensemble_id": ensemble["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Declared defaults on omitted optional inputs
# ---------------------------------------------------------------------------

def test_section_quota_chair_policy_flags_take_declared_defaults(api):
    """A section created without its two optional chair-policy flags defaults them.

    PRD §3.1: "Two optional flags shape the chair policy: `principal_required`, which defaults to true and decides whether chair one of the section carries the principal designation, and `rotation_policy`, which defaults to `ROTATING` and may instead be `FIXED`."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    response = api.create_section_quota(
        F.section_quota_payload(
            ensemble["id"], instrument="CELLO", min_count=1, target_count=2, max_count=3
        ),
        DIRECTOR_HEADERS,
    )
    quota = validate_success(response, 201)

    assert quota["principal_required"] is True
    assert quota["rotation_policy"] == "ROTATING"


def test_fresh_section_starts_with_zero_counters_and_min_count_driven_balance(api):
    """A fresh section starts empty, and its opening balance posture follows its min_count.

    PRD §3.1: "A fresh section starts with `filled_count` 0, `rotation_cycle_index` 0, and a `balance_state` of `UNDERFILLED` when `min_count` is greater than 0 and `BALANCED` when `min_count` is 0."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])

    with_minimum = X.create_section_quota(
        api, ensemble["id"], instrument="VIOLIN", min_count=1, target_count=2, max_count=3
    )
    assert with_minimum["filled_count"] == 0
    assert with_minimum["rotation_cycle_index"] == 0
    assert with_minimum["balance_state"] == "UNDERFILLED"

    without_minimum = X.create_section_quota(
        api, ensemble["id"], instrument="CELLO", min_count=0, target_count=2, max_count=3
    )
    assert without_minimum["filled_count"] == 0
    assert without_minimum["rotation_cycle_index"] == 0
    assert without_minimum["balance_state"] == "BALANCED"


def test_member_optional_inputs_take_declared_defaults(api):
    """A musician registered with only the mandatory inputs defaults its three optional ones.

    PRD §3.2: "Three inputs are optional: `years_in_org`, the count of completed prior seasons, between 0 and 12 and defaulting to 0; `sibling_enrolled`, defaulting to false; and `alumni_engagement_opt_in`, defaulting to false."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_member(
        F.member_payload(
            legal_name="Default Dana",
            primary_instrument="CELLO",
            grade_level=9,
            graduation_year=2029,
            household_income_band="BAND_C",
        ),
        REGISTRAR_HEADERS,
    )
    member = validate_success(response, 201)

    assert member["years_in_org"] == 0
    assert member["sibling_enrolled"] is False
    assert member["alumni_engagement_opt_in"] is False


def test_audition_slot_optional_inputs_take_declared_defaults(api):
    """A slot opened with only its mandatory inputs defaults excerpt codes, quorum and capacity.

    PRD §3.3: "Three inputs are optional: `required_excerpt_codes`, an array of excerpt code strings that every audition booked into the slot must have prepared, defaulting to empty; `quorum_required`, the number of submitted sheets that flips an audition to scored, defaulting to 3, constrained to between two and five, and never larger than the number of entries in `panelist_ids`; and `capacity`, the number of auditions the slot may hold, defaulting to 1 and constrained to between one and eight."

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")

    response = api.create_audition_slot(
        F.audition_slot_payload(
            ctx["season"]["id"],
            [p["id"] for p in panelists],
            room_code="R7",
            instrument_focus="CELLO",
        ),
        REGISTRAR_HEADERS,
    )
    slot = validate_success(response, 201)

    assert slot["required_excerpt_codes"] == []
    assert slot["quorum_required"] == 3
    assert slot["capacity"] == 1
    assert slot["booked_count"] == 0
    assert slot["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Server-derived member fields
# ---------------------------------------------------------------------------

def test_member_instrument_class_is_derived_from_primary_instrument(api):
    """The server classifies each musician's instrument without the caller supplying the class.

    PRD §3.2: "The server derives `instrument_class` from the instrument — `STRING` for `VIOLIN`, `VIOLA`, `CELLO` and `BASS`, `PERCUSSION` for `PERCUSSION`, and `WIND` for every other instrument — and that class later selects the loan fee."

    Design: Corner/entities/member_instrument_class_computed_from_primary_instrument
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    bass = X.create_member(
        api,
        legal_name="Bass Bo",
        primary_instrument="BASS",
        grade_level=11,
        graduation_year=2027,
        household_income_band="BAND_A",
        years_in_org=3,
    )
    flute = X.create_member(
        api,
        legal_name="Flute Fay",
        primary_instrument="FLUTE",
        grade_level=8,
        graduation_year=2030,
        household_income_band="BAND_B",
    )
    percussion = X.create_member(
        api,
        legal_name="Perc Pia",
        primary_instrument="PERCUSSION",
        grade_level=12,
        graduation_year=2026,
        household_income_band="BAND_C",
    )

    assert bass["instrument_class"] == "STRING"
    assert flute["instrument_class"] == "WIND"
    assert percussion["instrument_class"] == "PERCUSSION"


def test_fresh_member_starts_as_prospect_with_zeroed_attendance_counters(api):
    """A newly registered musician opens on both dimensions with every absence counter at zero.

    PRD §3.2: "A new musician starts with `enrollment_status` `PROSPECT`, `standing_status` `CLEAR`, and `unexcused_absence_count`, `tardy_count`, `effective_unexcused_count` and `probation_baseline_count` all 0."

    Design: Corner/entities/member_instrument_class_computed_from_primary_instrument
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    response = api.create_member(
        F.member_payload(legal_name="Fresh Fern", primary_instrument="BASS"),
        REGISTRAR_HEADERS,
    )
    member = validate_success(response, 201)

    assert member["enrollment_status"] == "PROSPECT"
    assert member["standing_status"] == "CLEAR"
    assert member["unexcused_absence_count"] == 0
    assert member["tardy_count"] == 0
    assert member["effective_unexcused_count"] == 0
    assert member["probation_baseline_count"] == 0
    A.assert_common_fields(member, expected_version=1)


# ---------------------------------------------------------------------------
# Audition registration
# ---------------------------------------------------------------------------

def test_audition_registration_stamps_requested_state_and_blind_code(api):
    """Registering an audition system-stamps its state, round, empty slot link and blind label.

    PRD §3.4: "The new row is created in `REQUESTED` with `revision_round` 0 and `slot_id` null, and the server mints a `blind_code` — an opaque panel-facing label such as "CELLO-014", built from the musician's `primary_instrument` plus a per-instrument sequence number — which is the only identity the panel ever sees."

    Design: Corner/entities/audition_system_fields_stamped_at_registration
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    member = X.create_member(
        api,
        legal_name="Ada Strings",
        primary_instrument="VIOLIN",
        grade_level=10,
        graduation_year=2028,
        household_income_band="BAND_B",
        years_in_org=1,
    )

    response = api.create_audition(
        F.audition_payload(
            member["id"],
            season["id"],
            declared_program="Bruch Concerto mvt I",
            excerpt_ids=["EX1"],
            scale_attested=True,
        ),
        guardian_headers(member["id"]),
    )
    audition = validate_success(response, 201)

    assert audition["status"] == "REQUESTED"
    assert audition["revision_round"] == 0
    assert audition["slot_id"] is None
    assert isinstance(audition["blind_code"], str) and audition["blind_code"]
    assert audition["blind_code"].startswith("VIOLIN")
    assert "Ada Strings" not in audition["blind_code"]
    assert audition["member_id"] == member["id"]
    A.assert_common_fields(audition, expected_version=1)


def test_fresh_audition_reports_no_submitted_sheets(api):
    """An audition that no adjudicator has scored yet counts zero sheets for its current round.

    PRD §3.4: "The audition's `submitted_score_count` counts the sheets belonging to its *current* `revision_round`."

    Design: Corner/entities/audition_system_fields_stamped_at_registration
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    member = X.create_member(api, primary_instrument="VIOLIN")

    audition = X.create_audition(api, member["id"], season["id"])

    assert audition["revision_round"] == 0
    assert audition["submitted_score_count"] == 0
    assert X.list_sheets(api, audition_id=audition["id"]) == []


# ---------------------------------------------------------------------------
# Rubric sheets
# ---------------------------------------------------------------------------

def _scheduled_cello_audition(api):
    """A CELLO audition sitting in SCHEDULED inside a three-adjudicator slot."""
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api, legal_name="Base Case", primary_instrument="CELLO")
    panelists = X.create_panelists(api, count=3, instrument_expertise="CELLO")
    slot = X.create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in panelists],
        room_code="R1",
        instrument_focus="CELLO",
        quorum_required=3,
        capacity=4,
    )
    audition = X.create_audition(api, member["id"], ctx["season"]["id"])
    X.schedule_audition(api, audition["id"], slot["id"])
    ctx.update({"member": member, "panelists": panelists, "slot": slot, "audition": audition})
    return ctx


def test_rubric_sheet_weighted_total_uses_the_declared_weights(api):
    """The four rubric integers are weighted 1.2/1.0/1.0/0.8 into a two-decimal weighted total.

    PRD §3.4: "Each sheet's `weighted_total` is computed before the row is persisted, by weighting the four raw rubric integers and rounding the sum half up to two decimal places: tone counts 1.2 times its raw score, rhythm 1.0 times, intonation 1.0 times, and sight-reading 0.8 times."

    Design: Corner/entities/panel_score_row_is_immutable_and_carries_no_version
    """
    ctx = _scheduled_cello_audition(api)
    panelist = ctx["panelists"][0]

    response = api.submit_panel_score(
        ctx["audition"]["id"],
        F.panel_score_payload(
            panelist["id"],
            tone_score=22,
            rhythm_score=20,
            intonation_score=21,
            sight_reading_score=18,
        ),
        panelist_headers(panelist["id"]),
    )
    sheet = validate_success(response, 201)

    # 22 * 1.2 + 20 * 1.0 + 21 * 1.0 + 18 * 0.8 = 26.4 + 20 + 21 + 14.4 = 81.80
    assert sheet["weighted_total"] == 81.80
    A.assert_two_decimal_places(sheet["weighted_total"])

    reread = validate_success(api.get_panel_score(sheet["id"], DIRECTOR_HEADERS))
    assert reread["weighted_total"] == 81.80


def test_rubric_sheet_carries_no_updated_at_and_no_version(api):
    """A submitted rubric sheet exposes only id and created_at, on create and on re-read.

    PRD §2.4: "It has no `updated_at` field and no `version` field at all, and nothing in the system ever mutates a sheet after it lands."

    Design: Corner/entities/panel_score_row_is_immutable_and_carries_no_version
    """
    ctx = _scheduled_cello_audition(api)
    panelist = ctx["panelists"][0]

    response = api.submit_panel_score(
        ctx["audition"]["id"],
        F.panel_score_payload(panelist["id"]),
        panelist_headers(panelist["id"]),
    )
    sheet = validate_success(response, 201)
    A.assert_immutable_sheet_shape(sheet)

    reread = validate_success(api.get_panel_score(sheet["id"], DIRECTOR_HEADERS))
    A.assert_immutable_sheet_shape(reread)
    assert reread["id"] == sheet["id"]


def test_rubric_sheet_snapshots_revision_round_and_is_always_blind(api):
    """A sheet records the round it belongs to and always reports that the panel judged blind.

    PRD §3.4: "The sheet snapshots the audition's current `revision_round` so that sheets from superseded rounds can be excluded from later arithmetic, and its `blind` flag is always true, recording that the adjudicator saw only the `blind_code` and never the musician's `legal_name`."

    Design: Corner/entities/panel_score_row_is_immutable_and_carries_no_version
    """
    ctx = _scheduled_cello_audition(api)
    panelist = ctx["panelists"][0]

    response = api.submit_panel_score(
        ctx["audition"]["id"],
        F.panel_score_payload(panelist["id"]),
        panelist_headers(panelist["id"]),
    )
    sheet = validate_success(response, 201)

    assert sheet["audition_id"] == ctx["audition"]["id"]
    assert sheet["panelist_id"] == panelist["id"]
    assert sheet["revision_round"] == 0
    assert sheet["blind"] is True


# ---------------------------------------------------------------------------
# Body foreign-key resolution
# ---------------------------------------------------------------------------

def test_unknown_ensemble_id_in_placement_body_outranks_state_gates(api):
    """An unresolvable ensemble_id in a placement body is reported before any state gate.

    PRD §2.10: "The protocol band runs first, in this internal order: header presence and role validity (`ERR_MISSING_AUTH_HEADERS`), role authorization for the endpoint (`ERR_UNAUTHORIZED`), ownership for the two entity-backed roles (`ERR_NOT_RESOURCE_OWNER`), path identifier existence left to right (the family not-found codes), request body schema (`ERR_INVALID_REQUEST`), foreign keys supplied in the body (the family not-found codes again), and finally pagination arguments on list endpoints (`ERR_INVALID_PAGINATION`)."

    Design: Corner/entities/body_foreign_keys_resolved_before_state_checks_not_found
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"])
    X.create_section_quota(api, ensemble["id"], instrument="VIOLIN")
    member = X.create_member(api, legal_name="Ada Strings", primary_instrument="VIOLIN")
    audition = X.create_audition(api, member["id"], season["id"])
    ensemble_version = X.ensemble_version(api, ensemble["id"])

    response = api.create_placement(
        F.placement_payload(audition["id"], NON_EXISTENT_UUID, ensemble_version),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ENSEMBLE_NOT_FOUND.value)

    assert X.ensemble_version(api, ensemble["id"]) == ensemble_version


def test_unknown_season_id_in_audition_body_reports_season_not_found(api):
    """An unresolvable season_id supplied in an audition body reports the Season family code.

    PRD §2.9: "The same family codes report unresolvable foreign keys supplied in a request *body* — `season_id`, `ensemble_id`, `member_id`, `slot_id`, `audition_id`, `panelist_id`, any element of `panelist_ids`, `event_id`, or `soloist_member_id` — although body resolution happens after body schema validation, as §2.10 sets out."

    Design: Corner/entities/body_foreign_keys_resolved_before_state_checks_not_found
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    X.create_season(api)
    member = X.create_member(api, legal_name="Ada Strings", primary_instrument="VIOLIN")

    response = api.create_audition(
        F.audition_payload(
            member["id"], NON_EXISTENT_UUID, declared_program="Bruch Concerto mvt I"
        ),
        guardian_headers(member["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_FOUND.value)


def test_unknown_event_id_in_participation_body_reports_event_not_found(api):
    """An unresolvable event_id supplied in a participation body reports the event family code.

    PRD §2.9: "The same family codes report unresolvable foreign keys supplied in a request *body* — `season_id`, `ensemble_id`, `member_id`, `slot_id`, `audition_id`, `panelist_id`, any element of `panelist_ids`, `event_id`, or `soloist_member_id` — although body resolution happens after body schema validation, as §2.10 sets out."

    Design: Corner/entities/body_foreign_keys_resolved_before_state_checks_not_found
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    member = X.create_member(api, legal_name="Ada Strings", primary_instrument="VIOLIN")

    response = api.create_event_participation(
        F.participation_payload(NON_EXISTENT_UUID, member["id"]), REGISTRAR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ENSEMBLE_EVENT_NOT_FOUND.value)
