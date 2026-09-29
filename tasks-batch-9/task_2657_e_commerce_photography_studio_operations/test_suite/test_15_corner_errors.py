"""Error-surface corners: which code comes out, and what stays untouched.

Path-identifier misses resolving to their own entity codes, the two branches of
the uniqueness family, the resolution-bearing sample match, the physical
station-to-asset-kind gate, rights scope at confirmation, the naming pattern,
the two colour refusals, the shooting and call-sheet preconditions, and the
retouch queue's own state edges.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSET_NAMING_VIOLATION,
    ERR_ASSET_NOT_APPROVED,
    ERR_ASSET_NOT_FOUND,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_COLOR_ALREADY_MEASURED,
    ERR_COLOR_CHECK_FAILED,
    ERR_COLOR_CONSISTENCY_DRIFT,
    ERR_DUPLICATE_CODE,
    ERR_DUPLICATE_SHOT_ITEM,
    ERR_DUPLICATE_STYLE_NUMBER,
    ERR_NO_CLAIMABLE_TASK,
    ERR_RELEASE_SCOPE_INSUFFICIENT,
    ERR_RETOUCH_TASK_INVALID_STATE,
    ERR_RETOUCH_TASK_NOT_FOUND,
    ERR_SAMPLE_NOT_FOUND,
    ERR_SESSION_NOT_SHOOTING,
    ERR_SHOT_ITEM_NOT_ASSIGNABLE,
    ERR_SHOT_ITEM_NOT_FOUND,
    ERR_SHOT_LIST_EMPTY,
    ERR_STATION_TYPE_MISMATCH,
    ERR_STYLE_NUMBER_MISMATCH,
)
from test_helpers.test_users import (
    ADMIN,
    CONTENT_OPS,
    COORDINATOR,
    PRODUCER,
    QC_REVIEWER,
    make_photographer_headers,
    make_retoucher_headers,
)

UNKNOWN_SAMPLE_UUID = "00000000-0000-4000-8000-0000000000a1"
UNKNOWN_BOOKING_UUID = "00000000-0000-4000-8000-0000000000a2"
UNKNOWN_ITEM_UUID = "00000000-0000-4000-8000-0000000000a3"
UNKNOWN_ASSET_UUID = "00000000-0000-4000-8000-0000000000a4"
UNKNOWN_TASK_UUID = "00000000-0000-4000-8000-0000000000a5"


def test_each_path_identifier_miss_returns_its_own_not_found_code(api):
    """Five reads on an empty database, five different 404 codes.

    PRD: "A miss returns the code belonging to the resource that failed to resolve: `ERR_STYLE_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SHOT_ITEM_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_RETOUCH_TASK_NOT_FOUND`, or `ERR_REFERENCE_NOT_FOUND` for the configuration resources."

    Design: Corner/errors/every_path_id_miss_raises_its_own_entity_not_found_code
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.get_sample(UNKNOWN_SAMPLE_UUID, COORDINATOR), ERR_SAMPLE_NOT_FOUND, 404
    )
    validate_error(
        api.get_talent_booking(UNKNOWN_BOOKING_UUID, PRODUCER),
        ERR_BOOKING_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_shot_list_item(UNKNOWN_ITEM_UUID, PRODUCER),
        ERR_SHOT_ITEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_asset(UNKNOWN_ASSET_UUID, CONTENT_OPS), ERR_ASSET_NOT_FOUND, 404
    )
    validate_error(
        api.get_retouch_task(UNKNOWN_TASK_UUID, CONTENT_OPS),
        ERR_RETOUCH_TASK_NOT_FOUND,
        404,
    )


def _the_first_of_every_coded_record(api):
    """Vendor NRTH, profile APPAREL_TOP, style TOP1001 and sample SMP-1001."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    style = fx.create_style(api, vendor["id"], profile["id"])
    sample = fx.create_sample(api, vendor["id"])
    return vendor, profile, style, sample


def test_a_repeated_vendor_code_is_a_duplicate_code(api):
    """A second registration under NRTH is refused however different the name.

    PRD: "Registration takes a `name` of between 1 and 120 characters that must still be non-empty after surrounding whitespace is trimmed, and a `vendor_code` of between 2 and 12 characters drawn only from uppercase letters and digits, which must be unique across all vendors — a repeat raises `ERR_DUPLICATE_CODE`."

    Design: Corner/errors/uniqueness_collisions_split_between_the_code_and_style_number_errors
    """
    _the_first_of_every_coded_record(api)

    validate_error(
        api.create_vendor(
            {"name": "Northline Trading", "vendor_code": "NRTH"}, ADMIN
        ),
        ERR_DUPLICATE_CODE,
        409,
    )


def test_a_second_profile_for_the_same_category_is_a_duplicate_code(api):
    """The category is the profile's code, so APPAREL_TOP admits exactly one contract.

    PRD: "Its `category` is one of the five merchandise categories and must be unique across all asset profiles, so a second profile for the same category is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/errors/uniqueness_collisions_split_between_the_code_and_style_number_errors
    """
    _the_first_of_every_coded_record(api)

    validate_error(
        api.create_asset_profile(
            f.asset_profile_payload(
                required_angles=["SIDE"],
                required_detail_shots=1,
                min_on_model_shots=2,
                video_required=True,
            ),
            ADMIN,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )


def test_a_repeated_barcode_is_a_duplicate_code(api):
    """The same barcode cannot be pre-advised twice, even for a different style.

    PRD: "A `SampleCoordinator` pre-advises an inbound box from the vendor's packing slip, supplying a `barcode` of 4 to 24 characters drawn from uppercase letters, digits and hyphens, which must be unique across all samples — a collision is `ERR_DUPLICATE_CODE` — plus the shipping `vendor_id` and the `declared_style_number` printed on the slip, itself 4 to 16 uppercase alphanumeric characters."

    Design: Corner/errors/uniqueness_collisions_split_between_the_code_and_style_number_errors
    """
    vendor, _profile, _style, _sample = _the_first_of_every_coded_record(api)

    validate_error(
        api.create_sample(
            f.sample_payload(vendor["id"], declared_style_number="TOP1002"),
            COORDINATOR,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )


def test_a_repeated_style_number_has_its_own_dedicated_code(api):
    """The style-number collision leaves the generic code family behind.

    PRD: "A `StudioAdmin` registers it with a `style_number` of 4 to 16 uppercase alphanumeric characters, which must be unique across every style — case-sensitively and after trimming — with a collision refused as `ERR_DUPLICATE_STYLE_NUMBER`."

    Design: Corner/errors/uniqueness_collisions_split_between_the_code_and_style_number_errors
    """
    vendor, profile, _style, _sample = _the_first_of_every_coded_record(api)

    validate_error(
        api.create_style(f.style_payload(vendor["id"], profile["id"]), ADMIN),
        ERR_DUPLICATE_STYLE_NUMBER,
        409,
    )

    _, meta = validate_paginated(
        api.list_styles(CONTENT_OPS, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1


def _a_style_owing_one_planned_front_shot(api):
    """Style TOP1001 with a single PLANNED required ON_MODEL/FRONT item."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    style = fx.create_style(api, vendor["id"], profile["id"])
    item = fx.create_shot_item(api, style["id"])
    return style, item


def test_the_same_triple_collides_while_the_original_is_still_planned(api):
    """Style, kind and angle already exist unwaived, so the second definition fails.

    PRD: "Within one style, the combination of style, `asset_kind` and `angle_code` must be unique among items that have not been waived; a duplicate is refused with `ERR_DUPLICATE_SHOT_ITEM`, while waived items are ignored by that uniqueness test so a waived shot can be re-created."

    Design: Corner/errors/duplicate_shot_item_triple_is_refused_until_the_first_one_is_waived
    """
    style, _item = _a_style_owing_one_planned_front_shot(api)

    validate_error(
        api.create_shot_list_item(
            f.shot_item_payload(
                style["id"],
                fx.style_version(api, style["id"]),
                estimated_minutes=45,
            ),
            PRODUCER,
        ),
        ERR_DUPLICATE_SHOT_ITEM,
        409,
    )


def test_waiving_the_original_frees_the_triple_for_re_creation(api):
    """The uniqueness scope skips WAIVED rows, so the identical shot is definable again.

    PRD: "Within one style, the combination of style, `asset_kind` and `angle_code` must be unique among items that have not been waived; a duplicate is refused with `ERR_DUPLICATE_SHOT_ITEM`, while waived items are ignored by that uniqueness test so a waived shot can be re-created."

    Design: Corner/errors/duplicate_shot_item_triple_is_refused_until_the_first_one_is_waived
    """
    style, item = _a_style_owing_one_planned_front_shot(api)

    waived = fx.waive_item(api, item["id"], reason="reshoot planned with a different crop")
    replacement = validate_success(
        api.create_shot_list_item(
            f.shot_item_payload(
                style["id"],
                fx.style_version(api, style["id"]),
                estimated_minutes=45,
            ),
            PRODUCER,
        ),
        201,
    )

    assert waived["item_state"] == "WAIVED"
    assert replacement["asset_kind"] == "ON_MODEL"
    assert replacement["angle_code"] == "FRONT"


def test_the_replacement_shot_starts_clean_and_restores_the_required_count(api):
    """The re-created row is a brand-new item, and it puts the requirement back.

    PRD: "A new item lands in `item_state` `PLANNED` with `session_id` null, `live_asset_count` 0 and `allocated_cost_cents` 0, and if its `required` flag is true the parent style's `required_item_count` rises by one; either way the style's `version` increments by one."

    Design: Corner/errors/duplicate_shot_item_triple_is_refused_until_the_first_one_is_waived
    """
    style, item = _a_style_owing_one_planned_front_shot(api)

    fx.waive_item(api, item["id"], reason="reshoot planned with a different crop")
    replacement = fx.create_shot_item(api, style["id"], estimated_minutes=45)

    assert replacement["id"] != item["id"]
    assert replacement["item_state"] == "PLANNED"
    assert replacement["session_id"] is None
    assert replacement["live_asset_count"] == 0
    assert replacement["allocated_cost_cents"] == 0
    assert validate_success(api.get_style(style["id"], PRODUCER))[
        "required_item_count"
    ] == 1


def _a_received_box_offered_against_the_wrong_style(api):
    """SMP-1001 declares TOP1001 and is RECEIVED; TOP2002 also exists."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    fx.create_style(api, vendor["id"], profile["id"])
    other = fx.create_style(
        api, vendor["id"], profile["id"], style_number="TOP2002"
    )
    sample = fx.create_sample(api, vendor["id"])
    fx.receive_sample(api, sample["id"])
    return other, sample


def test_a_bare_match_against_a_different_style_number_is_refused(api):
    """Strict reconciliation compares the two numbers and leaves the box alone.

    PRD: "When `mismatch_resolution` is omitted, the reconciliation is strict: the referenced style's `style_number` must equal the sample's `declared_style_number`, and any disagreement is refused with `ERR_STYLE_NUMBER_MISMATCH`, leaving the sample untouched."

    Design: Corner/errors/matching_a_box_to_the_wrong_style_number_needs_an_explicit_resolution
    """
    other, sample = _a_received_box_offered_against_the_wrong_style(api)

    validate_error(
        api.match_sample(sample["id"], {"style_id": other["id"]}, COORDINATOR),
        ERR_STYLE_NUMBER_MISMATCH,
        409,
    )

    after = validate_success(api.get_sample(sample["id"], COORDINATOR))
    assert after["match_state"] == "UNMATCHED"
    assert after["matched_style_id"] is None
    assert after["custody_state"] == "RECEIVED"


def test_the_same_match_carrying_hold_quarantines_the_box(api):
    """An explicit resolution turns the refusal into a deliberate quarantine.

    PRD: "When the numbers disagree and the coordinator passes `HOLD`, the box is quarantined instead: the match axis moves `UNMATCHED → MISMATCH_HOLD` and `matched_style_id` deliberately stays null while the vendor is chased."

    Design: Corner/errors/matching_a_box_to_the_wrong_style_number_needs_an_explicit_resolution
    """
    other, sample = _a_received_box_offered_against_the_wrong_style(api)

    held = validate_success(
        api.match_sample(
            sample["id"],
            {"style_id": other["id"], "mismatch_resolution": "HOLD"},
            COORDINATOR,
        )
    )

    assert held["match_state"] == "MISMATCH_HOLD"
    assert held["matched_style_id"] is None
    assert held["custody_state"] == "RECEIVED"


def test_an_on_model_shot_cannot_be_assigned_to_a_still_life_bench(api):
    """The physical instrument is wrong, so the assignment is refused on the pairing.

    PRD: "An `ON_MODEL` item requires a station whose `station_type` is `MODEL`. A `STILL_ANGLE` or `DETAIL` item requires a station whose `station_type` is either `MANNEQUIN` or `STILL_LIFE` — a model bay is the wrong instrument for a flat lay. A `VIDEO` item requires a station whose `station_type` is either `MODEL` or `STILL_LIFE`, which means a mannequin position cannot carry video at all. Any other pairing is refused with `ERR_STATION_TYPE_MISMATCH`."

    Design: Corner/errors/an_on_model_item_cannot_be_assigned_to_a_still_life_station
    """
    world = fx.build_reference_data(
        api,
        station_type="STILL_LIFE",
        station_code="STILL-1",
        profile_kw={"required_angles": ["FRONT"]},
    )
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    item = fx.create_shot_item(api, world.style_id)
    session = fx.create_session(api, world.station_id, world.provider_id)

    validate_error(
        api.assign_shot_list_item(
            item["id"], {"session_id": session["id"]}, PRODUCER
        ),
        ERR_STATION_TYPE_MISMATCH,
        422,
    )

    after = validate_success(api.get_shot_list_item(item["id"], PRODUCER))
    assert after["item_state"] == "PLANNED"
    assert after["session_id"] is None


def test_an_ecom_only_grant_cannot_confirm_a_full_buyout_booking(api):
    """The document is signed and spans the window, but the grant is too narrow.

    PRD: "The selected document's `scope` must then be at least as broad as the session's `required_usage_scope` under that same ordering; a narrower grant is refused with `ERR_RELEASE_SCOPE_INSUFFICIENT`, so a model holding only `ECOM_ONLY` rights cannot be confirmed onto a session that requires `ECOM_PLUS_SOCIAL`."

    Design: Corner/errors/a_signed_ecom_only_release_cannot_cover_a_full_buyout_session
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=600)
    release = fx.create_release(
        api,
        model["id"],
        scope="ECOM_ONLY",
        territory="GLOBAL",
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    fx.sign_release(api, release["id"])
    session = fx.create_session(
        api, station["id"], provider["id"], required_usage_scope="FULL_BUYOUT"
    )
    booking = fx.create_booking(
        api, session["id"], model["id"], role_on_set="MODEL"
    )

    validate_error(
        api.confirm_booking(booking["id"], PRODUCER),
        ERR_RELEASE_SCOPE_INSUFFICIENT,
        422,
    )

    after = validate_success(api.get_talent_booking(booking["id"], PRODUCER))
    assert after["booking_state"] == "HELD"
    assert after["release_document_id"] is None
    assert validate_success(api.get_shoot_session(session["id"], PRODUCER))[
        "committed_talent_cost_cents"
    ] == 0


def _a_session_on_the_floor(api, session_kw=None):
    """A SHOOTING 09:00-13:00 MODEL session with one ASSIGNED ON_MODEL/FRONT item."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api,
        world,
        item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}],
        session_kw=session_kw,
    )
    fx.build_shooting_session(api, world)
    return world


def test_a_file_name_off_the_pattern_is_refused_at_ingest(api):
    """An unpadded sequence number is not the pattern's expansion.

    PRD: "The `file_name` must then equal the expansion of the naming pattern belonging to the style's asset profile: the style's `style_number`, an underscore, the item's `angle_code`, an underscore, and the `sequence_number` written with leading zeros to three digits — so frame 7 of the front angle of style `TS10442` is `TS10442_FRONT_007`. Anything else is `ERR_ASSET_NAMING_VIOLATION`."

    Design: Corner/errors/file_name_off_the_naming_pattern_is_refused_at_ingest
    """
    world = _a_session_on_the_floor(api)

    validate_error(
        api.create_asset(
            f.asset_payload(world.item_id, "TOP1001_FRONT_1"),
            make_photographer_headers(world.photographer_id),
        ),
        ERR_ASSET_NAMING_VIOLATION,
        422,
    )

    assert world.read_item()["item_state"] == "ASSIGNED"
    assert world.read_item()["live_asset_count"] == 0


def test_the_padded_file_name_is_accepted_and_captures_the_item(api):
    """The same frame under the expanded name lands and moves the shot to CAPTURED.

    PRD: "The item's `live_asset_count` rises by one and, when it rises from 0 to 1, the item advances `ASSIGNED → CAPTURED`; if that capture completes the style's required non-waived set, the style advances to `SHOT` and its `version` increments by one."

    Design: Corner/errors/file_name_off_the_naming_pattern_is_refused_at_ingest
    """
    world = _a_session_on_the_floor(api)

    asset = validate_success(
        api.create_asset(
            f.asset_payload(world.item_id, "TOP1001_FRONT_001"),
            make_photographer_headers(world.photographer_id),
        ),
        201,
    )

    assert asset["asset_state"] == "INGESTED"
    assert world.read_item()["item_state"] == "CAPTURED"
    assert world.read_item()["live_asset_count"] == 1


def _a_session_whose_colour_reading_failed(api):
    """Patches [3.0, 3.0, 3.0] on a MODEL bay tolerating 2.00 delta-E."""
    world = _a_session_on_the_floor(
        api,
        session_kw={"color_chart_code": "CC24", "color_tolerance_delta_e": 2.00},
    )
    fx.measure_colour(api, world.session_id, world.photographer_id, [3.0, 3.0, 3.0])
    return world


def test_the_model_bay_composite_fails_the_session_tolerance(api):
    """Three tenths of the mean plus seven tenths of the worst patch is 3.00.

    PRD: "On a station whose `station_type` is `MODEL`, the composite is three tenths of the mean plus seven tenths of the largest, rounded half up to two decimals — skin-tone accuracy is punished far more by one badly-off patch than by a mildly-off average. On a `MANNEQUIN` or `STILL_LIFE` station the two contributions are weighted equally, one half each, likewise rounded half up to two decimals. The verdict is then inclusive: `color_check_state` becomes `PASS` when the composite is less than or equal to the session's `color_tolerance_delta_e`, and `FAIL` only when it is strictly greater."

    Design: Corner/errors/a_failed_colour_reading_stops_ingest_and_cannot_be_remeasured
    """
    world = _a_session_whose_colour_reading_failed(api)

    session = world.read_session()
    assert float(session["color_composite_delta_e"]) == 3.00
    assert session["color_check_state"] == "FAIL"


def test_a_failed_colour_check_bars_every_ingest_on_the_session(api):
    """The file is named correctly and the item is assigned, yet ingest is barred.

    PRD: "The session's `color_check_state` must not be `FAIL`; a failed colour check bars all ingest with `ERR_COLOR_CHECK_FAILED`, while a session still `NOT_MEASURED` is permitted to ingest."

    Design: Corner/errors/a_failed_colour_reading_stops_ingest_and_cannot_be_remeasured
    """
    world = _a_session_whose_colour_reading_failed(api)

    validate_error(
        api.create_asset(
            f.asset_payload(world.item_id, "TOP1001_FRONT_001"),
            make_photographer_headers(world.photographer_id),
        ),
        ERR_COLOR_CHECK_FAILED,
        409,
    )

    assert world.read_item()["item_state"] == "ASSIGNED"


def test_a_failed_session_cannot_be_measured_a_second_time(api):
    """One reading per session: the verdict has moved off NOT_MEASURED and stays put.

    PRD: "A session that is not `SHOOTING` refuses with `ERR_SESSION_NOT_SHOOTING`, and a session whose `color_check_state` has already moved off `NOT_MEASURED` to either `PASS` or `FAIL` refuses a second reading with `ERR_COLOR_ALREADY_MEASURED`."

    Design: Corner/errors/a_failed_colour_reading_stops_ingest_and_cannot_be_remeasured
    """
    world = _a_session_whose_colour_reading_failed(api)

    validate_error(
        api.submit_color_measurement(
            world.session_id,
            f.color_measurement_payload([1.0, 1.0, 1.0]),
            make_photographer_headers(world.photographer_id),
        ),
        ERR_COLOR_ALREADY_MEASURED,
        409,
    )

    session = world.read_session()
    assert float(session["color_composite_delta_e"]) == 3.00
    assert session["color_check_state"] == "FAIL"


def _two_sessions_on_one_bay_with_the_earlier_reading_recorded(api):
    """MODEL-1 hosts S1 09:00-11:00 (composite 1.00 PASS) and S2 12:00-14:00 SHOOTING."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT", "BACK"])
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api, minimum_call_hours=0)
    style = fx.create_style(api, vendor["id"], profile["id"])
    sample = fx.create_sample(api, vendor["id"])
    fx.receive_sample(api, sample["id"])
    fx.match_sample(api, sample["id"], style["id"])
    fx.custody_move(api, sample["id"], "IN_STUDIO")
    front = fx.create_shot_item(api, style["id"], angle_code="FRONT")
    back = fx.create_shot_item(api, style["id"], angle_code="BACK")
    colour = {"color_chart_code": "CC24", "color_tolerance_delta_e": 2.00}
    first = fx.create_session(
        api,
        station["id"],
        provider["id"],
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T11:00:00Z",
        **colour,
    )
    second = fx.create_session(
        api,
        station["id"],
        provider["id"],
        scheduled_start="2026-08-03T12:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        **colour,
    )
    fx.assign_item(api, front["id"], first["id"])
    fx.assign_item(api, back["id"], second["id"])
    early = fx.create_booking(
        api,
        first["id"],
        photographer["id"],
        call_time="2026-08-03T09:00:00Z",
        wrap_time="2026-08-03T11:00:00Z",
    )
    fx.confirm_booking(api, early["id"])
    late = fx.create_booking(
        api,
        second["id"],
        photographer["id"],
        call_time="2026-08-03T12:00:00Z",
        wrap_time="2026-08-03T14:00:00Z",
    )
    fx.confirm_booking(api, late["id"])
    fx.lock_session(api, first["id"])
    fx.lock_session(api, second["id"])
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    fx.start_session(api, first["id"], photographer["id"])
    fx.measure_colour(api, first["id"], photographer["id"], [1.0, 1.0, 1.0])
    fx.set_clock(api, "2026-08-03T12:00:00Z")
    fx.start_session(api, second["id"], photographer["id"])
    return photographer, first, second


def test_a_reading_a_whole_unit_off_the_stations_last_pass_is_rejected(api):
    """Composite 2.00 is inside its own tolerance but 1.00 from the baseline.

    PRD: "If a baseline does exist and the absolute difference between the new composite and that baseline's `color_composite_delta_e` is strictly greater than three quarters of a delta-E unit, the measurement is rejected with `ERR_COLOR_CONSISTENCY_DRIFT` and **nothing at all is persisted** — no composite, no verdict, no timestamp — so the session remains `NOT_MEASURED` and may be measured again."

    Design: Corner/errors/a_reading_that_drifts_too_far_from_the_previous_pass_is_refused
    """
    photographer, _first, second = _two_sessions_on_one_bay_with_the_earlier_reading_recorded(api)

    validate_error(
        api.submit_color_measurement(
            second["id"],
            f.color_measurement_payload([2.0, 2.0, 2.0]),
            make_photographer_headers(photographer["id"]),
        ),
        ERR_COLOR_CONSISTENCY_DRIFT,
        422,
    )

    after = validate_success(api.get_shoot_session(second["id"], PRODUCER))
    assert after["color_check_state"] == "NOT_MEASURED"
    assert after["color_composite_delta_e"] is None
    # PRD 3.4: the field is born as "an empty array" (only the composite, the
    # verdict and the timestamps are null at birth), and a rejected reading
    # persists "nothing at all" — so it is still that empty array here.
    assert after["color_patch_deltas"] == []


def test_the_refused_reading_leaves_the_baseline_session_untouched(api):
    """The earlier pass on the same bay is the baseline, and it keeps its verdict.

    PRD: "The system looks for a baseline: among sessions on the **same** station whose `color_check_state` is `PASS` and whose `scheduled_start` falls strictly earlier than this session's `scheduled_start`, it ranks by the later `scheduled_start` first and then by the earlier `created_at` first, and takes the first row."

    Design: Corner/errors/a_reading_that_drifts_too_far_from_the_previous_pass_is_refused
    """
    photographer, first, second = _two_sessions_on_one_bay_with_the_earlier_reading_recorded(api)

    validate_error(
        api.submit_color_measurement(
            second["id"],
            f.color_measurement_payload([2.0, 2.0, 2.0]),
            make_photographer_headers(photographer["id"]),
        ),
        ERR_COLOR_CONSISTENCY_DRIFT,
        422,
    )

    baseline = validate_success(api.get_shoot_session(first["id"], PRODUCER))
    assert float(baseline["color_composite_delta_e"]) == 1.00
    assert baseline["color_check_state"] == "PASS"


def _a_frozen_call_sheet_and_an_empty_second_session(api):
    """Session A is LOCKED at the call time; session B 14:00-16:00 owns no shots."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    empty = fx.create_session(
        api,
        world.station_id,
        world.provider_id,
        scheduled_start="2026-08-03T14:00:00Z",
        scheduled_end="2026-08-03T16:00:00Z",
    )
    fx.lock_session(api, world.session_id)
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    return world, empty


def test_ingest_into_a_locked_session_that_never_started_is_refused(api):
    """The clock has reached the call time, but nobody called the session to order.

    PRD: "The item's session must be `SHOOTING` (`ERR_SESSION_NOT_SHOOTING`) and the item itself must be `ASSIGNED` or `CAPTURED` (`ERR_SHOT_ITEM_NOT_ASSIGNABLE`)."

    Design: Corner/errors/ingest_needs_a_shooting_session_and_locking_needs_a_shot_list
    """
    world, _empty = _a_frozen_call_sheet_and_an_empty_second_session(api)

    validate_error(
        api.create_asset(
            f.asset_payload(world.item_id, "TOP1001_FRONT_001"),
            make_photographer_headers(world.photographer_id),
        ),
        ERR_SESSION_NOT_SHOOTING,
        409,
    )

    assert world.read_session()["session_state"] == "LOCKED"
    assert world.read_item()["item_state"] == "ASSIGNED"


def test_freezing_a_call_sheet_with_no_required_assigned_shot_is_refused(api):
    """The sample check ranges vacuously, so the empty call sheet surfaces instead.

    PRD: "Second, the call sheet must not be empty: at least one shot-list item whose `required` flag is true and whose `item_state` is `ASSIGNED` must reference the session, failing which the freeze is refused with `ERR_SHOT_LIST_EMPTY`."

    Design: Corner/errors/ingest_needs_a_shooting_session_and_locking_needs_a_shot_list
    """
    _world, empty = _a_frozen_call_sheet_and_an_empty_second_session(api)

    validate_error(
        api.lock_session(empty["id"], PRODUCER), ERR_SHOT_LIST_EMPTY, 409
    )

    assert validate_success(api.get_shoot_session(empty["id"], PRODUCER))[
        "session_state"
    ] == "BOOKED"


def _a_booked_session_holding_a_cancelled_hold(api):
    """One ASSIGNED ON_MODEL item and a photographer hold that was cancelled."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    fx.build_planned_session(
        api,
        world,
        item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}],
        with_photographer_booking=False,
    )
    booking = fx.create_booking(api, world.session_id, world.photographer_id)
    world.bookings.append(booking)
    validate_success(
        api.cancel_booking(booking["id"], PRODUCER, {"reason": "double booked"})
    )
    return world


def test_a_cancelled_hold_cannot_be_confirmed(api):
    """Confirmation demands HELD, and cancellation is not a state to return from.

    PRD: "The booking itself must be `HELD` — confirming something already confirmed, released or cancelled is `ERR_BOOKING_INVALID_STATE`."

    Design: Corner/errors/cancelled_bookings_and_assigned_items_refuse_their_own_actions
    """
    world = _a_booked_session_holding_a_cancelled_hold(api)

    validate_error(
        api.confirm_booking(world.booking_id, PRODUCER),
        ERR_BOOKING_INVALID_STATE,
        409,
    )

    assert world.read_booking()["booking_state"] == "CANCELLED"


def test_an_assigned_shot_cannot_be_waived(api):
    """The escape hatch is open from PLANNED and BLOCKED only.

    PRD: "An item that is `PLANNED` or `BLOCKED` may be waived, optionally with a `reason`, moving it to the terminal `WAIVED` state so that it no longer holds up the style's content completion; an item that is `ASSIGNED`, `CAPTURED` or already `WAIVED` cannot be waived and the attempt is refused with `ERR_SHOT_ITEM_NOT_ASSIGNABLE`."

    Design: Corner/errors/cancelled_bookings_and_assigned_items_refuse_their_own_actions
    """
    world = _a_booked_session_holding_a_cancelled_hold(api)

    validate_error(
        api.waive_shot_list_item(
            world.item_id, PRODUCER, {"reason": "drop the angle"}
        ),
        ERR_SHOT_ITEM_NOT_ASSIGNABLE,
        409,
    )

    assert world.read_item()["item_state"] == "ASSIGNED"
    assert world.read_style()["required_item_count"] == 1


def _one_queued_task_over_an_ingested_frame(api):
    """TOP1001_FRONT_001 is INGESTED at 10:00 and one QUEUED task points at it."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    fx.build_shooting_session(api, world)
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.build_ingested_asset(api, world)
    fx.build_queued_task(api, world)
    return world


def test_a_second_task_over_the_same_asset_is_refused(api):
    """The live task already on the file blocks another one.

    PRD: "The asset must be `INGESTED` — a file already in retouch, awaiting quality control, approved, rejected or delivered is refused with `ERR_ASSET_NOT_APPROVED` — and the asset must not already carry a live task, meaning no existing task for it whose `task_state` is `QUEUED`, `IN_PROGRESS`, `SUBMITTED`, `REWORK` or `APPROVED`; a duplicate is refused with `ERR_RETOUCH_TASK_EXISTS`."

    The queued first task already moved the file `INGESTED -> IN_RETOUCH`, and
    the cited sentence runs the `INGESTED` requirement *before* the live-task
    requirement — as does the global ladder, which places "asset state legality
    (`ERR_ASSET_NOT_APPROVED`)" at the state-precondition tier and "no live
    retouch task already on the asset (`ERR_RETOUCH_TASK_EXISTS`)" one tier
    lower among the business rules.  So the refusal a PRD-faithful server owes
    here is `ERR_ASSET_NOT_APPROVED`, 409.

    Design: Corner/errors/retouch_queue_edges_cover_a_second_task_a_queued_review_and_an_empty_pool
    """
    world = _one_queued_task_over_an_ingested_frame(api)

    validate_error(
        api.create_retouch_task(
            f.retouch_task_payload(world.asset_id, world.provider_id), CONTENT_OPS
        ),
        ERR_ASSET_NOT_APPROVED,
        409,
    )


def test_a_queued_task_cannot_be_ruled_on_by_quality_control(api):
    """Nothing has been submitted yet, so there is nothing to approve.

    PRD: "Only a `SUBMITTED` task can be ruled on; anything else is `ERR_RETOUCH_TASK_INVALID_STATE`."

    Design: Corner/errors/retouch_queue_edges_cover_a_second_task_a_queued_review_and_an_empty_pool
    """
    world = _one_queued_task_over_an_ingested_frame(api)

    validate_error(
        api.qc_decision(
            world.task_id, f.qc_decision_payload("APPROVE"), QC_REVIEWER
        ),
        ERR_RETOUCH_TASK_INVALID_STATE,
        409,
    )

    assert world.read_task()["task_state"] == "QUEUED"


def test_the_only_queued_task_is_the_one_the_claim_hands_over(api):
    """The server picks it: the task moves to IN_PROGRESS in the claimant's name.

    PRD: "The winning task moves `QUEUED → IN_PROGRESS`, its `assigned_retoucher_id` is set to the claiming `X-User-ID`, and `claimed_at` is stamped from the logical clock."

    Design: Corner/errors/retouch_queue_edges_cover_a_second_task_a_queued_review_and_an_empty_pool
    """
    world = _one_queued_task_over_an_ingested_frame(api)

    claimed = validate_success(
        api.claim_next_retouch_task(make_retoucher_headers(world.retoucher_id))
    )

    assert claimed["id"] == world.task_id
    assert claimed["task_state"] == "IN_PROGRESS"
    assert claimed["assigned_retoucher_id"] == world.retoucher_id


def test_a_second_claim_against_a_drained_pool_is_refused(api):
    """Once the single task is in progress the candidate pool is empty.

    PRD: "If the pool is empty — nothing queued at all, or every queued task's provider is at capacity — the request is refused with `ERR_NO_CLAIMABLE_TASK`."

    Design: Corner/errors/retouch_queue_edges_cover_a_second_task_a_queued_review_and_an_empty_pool
    """
    world = _one_queued_task_over_an_ingested_frame(api)
    fx.claim_next(api, world.retoucher_id)

    validate_error(
        api.claim_next_retouch_task(make_retoucher_headers(world.retoucher_id)),
        ERR_NO_CLAIMABLE_TASK,
        409,
    )

    _, meta = validate_paginated(
        api.list_retouch_tasks(
            CONTENT_OPS, {"task_state": "QUEUED", "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
