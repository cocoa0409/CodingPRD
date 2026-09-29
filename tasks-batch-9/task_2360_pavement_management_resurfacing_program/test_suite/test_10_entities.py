"""Creation, retrieval, listing, defaults, computed fields and system fields."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_common_fields,
    assert_index,
    assert_money,
    assert_pagination_meta,
    assert_project_estimate,
    assert_project_scope,
    assert_segment_condition,
)
from test_helpers.constants import (
    AREA_MAPLE,
    AREA_OAK,
    BAND_GOOD,
    BAND_POOR,
    CLOCK_2027_08_01,
    COLLECTION_AUTOMATED,
    CRACK_SEAL,
    MAPLE_OAK_AREA,
    MAPLE_OAK_BASE,
    MAPLE_OAK_CONTINGENCY,
    MAPLE_OAK_TOTAL,
    MILL_AND_OVERLAY,
    OAK_LINE_COST,
    OBS_MILL,
    OBS_MILL_DEDUCT,
    OBS_MILL_INDEX,
    PCI_BIRCH_MODEL,
    PCI_MAPLE_MODEL,
    PCI_UNTREATED_MODEL,
    SEG_BIRCH,
    SEG_CEDAR,
    SEG_ELM,
    SEG_MAPLE,
    SEG_OAK,
    SOURCE_MODEL_PROJECTED,
    SURVEY_YEAR,
    UNKNOWN_UUID,
)
from test_helpers.factories import OMIT, observation_payload, scenario_payload
from test_helpers.test_users import ENGINEER, OFFICER

# The four-street inventory the filtered listing is drawn from, in creation order.
LISTING_INVENTORY = [SEG_MAPLE, SEG_OAK, SEG_BIRCH, SEG_ELM]

PROJECT_START = "2026-09-01T00:00:00Z"
PROJECT_END = "2026-10-31T00:00:00Z"
MAPLE_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")
OAK_WINDOW = ("2026-09-15T00:00:00Z", "2026-09-30T00:00:00Z")

DEFAULT_DESIGN_THICKNESS_IN = 2.0


def test_creating_a_segment_publishes_area_decay_and_a_projected_index(api):
    """One POST of nine inventory fields returns every computed field populated.

    PRD: "Creation computes the segment's `area_sy`: the length in feet multiplied
    by the width in feet, divided by the nine square feet that make up one square
    yard, rounded to two decimal places. The two decay rates for the segment's class
    are stamped onto `decay_coefficient` and `decay_knee_coefficient`, and the
    deterioration model of §2.7 is evaluated at the current logical clock to seed
    `condition_index`, with `condition_index_source` set to `MODEL_PROJECTED` and
    `condition_band` derived from the result."

    PRD: "An `ARTERIAL` segment loses 2.2 points per year with a further 1.6 after
    the knee; a `COLLECTOR` loses 1.8 with a further 1.3; a `LOCAL` loses 1.4 with a
    further 1.0. The knee falls at 8 years of age."

    PRD: "A newly loaded segment records `last_treatment_type` as `NONE` — the field
    otherwise takes `CRACK_SEAL`, `MILL_AND_OVERLAY` or `RECONSTRUCTION` once a
    treatment has been accepted on it — and starts with `moratorium_until` null,
    `active_project_count` zero and `open_service_request_count` zero."

    A 1000.00 by 30.00 foot street laid in 2016 and read in 2026 is ten whole years
    old, two of them past the knee, so 92.0 decays to 76.0.

    Design: Corner/entities/segment_creation_computes_area_and_seeds_model_projected_index
    """
    fixtures.set_clock(api)

    segment = validate_success(
        api.create_segment(dict(SEG_MAPLE), ENGINEER), 201
    )

    assert_common_fields(segment)
    assert_area(segment["area_sy"], AREA_MAPLE)
    assert segment["decay_coefficient"] == 1.4
    assert segment["decay_knee_coefficient"] == 1.0
    assert_segment_condition(segment, PCI_MAPLE_MODEL, SOURCE_MODEL_PROJECTED, BAND_GOOD)
    assert segment["last_treatment_type"] == "NONE"
    assert segment["moratorium_until"] is None
    assert segment["active_project_count"] == 0
    assert segment["open_service_request_count"] == 0


def test_a_segment_read_a_year_later_still_publishes_the_stored_index(api):
    """The model runs at write time, so a moved clock does not move the index.

    PRD: "The pavement condition index — PCI — is the currency of this system, and a
    segment's `condition_index` is a **stored derived field**, never recomputed on
    read. Exactly three events write it: the segment's own creation, the sealing of a
    condition survey that carries an accepted observation on that segment, and the
    final acceptance of a project line that resurfaced it."

    PRD: "Setting the clock mutates no entity and recomputes no derived field on its
    own — a segment's stored `condition_index` does not move because the clock
    moved."

    PRD: "`updated_at` is refreshed and `version` is incremented on every mutation of
    that resource, including mutations that only change derived fields."

    Design: Corner/entities/segment_retrieval_returns_stored_inventory_and_counters
    """
    fixtures.set_clock(api)
    created = fixtures.create_segment(api, SEG_MAPLE)
    fixtures.set_clock(api, CLOCK_2027_08_01)

    read_back = validate_success(api.get_segment(created["id"], ENGINEER))

    assert_area(read_back["area_sy"], AREA_MAPLE)
    assert_segment_condition(read_back, PCI_MAPLE_MODEL, SOURCE_MODEL_PROJECTED, BAND_GOOD)
    assert read_back["street_name"] == "Maple St"
    assert read_back["geo_zone"] == "Z1"
    assert read_back["functional_class"] == "LOCAL"
    assert read_back["length_ft"] == 1000.00
    assert read_back["width_ft"] == 30.00
    assert read_back["version"] == created["version"], "a read is not a mutation"


def test_the_segment_listing_composes_a_band_filter_with_limit_and_offset(api):
    """Two filters narrow four streets to two, and the window picks the second.

    PRD: "The network can be listed with filters on `geo_zone`, `functional_class`
    and `condition_band`, which is how an engineer assembles the candidate list for a
    geographic bundle, and every role in the system may read the inventory."

    PRD: "`offset` skips rows from the front of the ordered result and defaults to 0;
    it may not be negative."

    PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    in the envelope's `meta` object."

    Birch St bands POOR at 44.0 and Elm St sits in Z3, so neither can appear; of the
    two survivors the offset skips Maple St and leaves Oak St.

    Design: Corner/entities/segment_listing_filters_by_condition_band_with_limit_and_offset
    """
    fixtures.set_clock(api)
    rows = fixtures.create_segments(api, LISTING_INVENTORY)
    assert_index(rows["Birch St"]["condition_index"], PCI_BIRCH_MODEL)
    assert rows["Birch St"]["condition_band"] == BAND_POOR
    assert rows["Elm St"]["geo_zone"] == "Z3"

    listed, meta = validate_paginated(
        api.list_segments(
            ENGINEER, {"geo_zone": "Z1", "condition_band": BAND_GOOD, "limit": 1, "offset": 1}
        )
    )

    assert len(listed) == 1
    assert_pagination_meta(meta, 1, 1, 2, False)
    assert listed[0]["id"] == rows["Oak St"]["id"]
    assert listed[0]["condition_band"] == BAND_GOOD
    assert listed[0]["geo_zone"] == "Z1"
    assert all(row["condition_band"] != BAND_POOR for row in listed)
    assert all(row["geo_zone"] != "Z3" for row in listed)


def test_reading_an_unknown_segment_id_reports_the_inventory_not_found_code(api):
    """A well-formed identifier that names no row gets the collection's own code.

    PRD: "A path `id` that does not resolve to a row of the addressed collection
    yields the not-found code belonging to that collection — `ERR_SEGMENT_NOT_FOUND`,
    `ERR_SURVEY_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`,
    `ERR_SCENARIO_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_PROJECT_SEGMENT_NOT_FOUND`,
    `ERR_COORDINATION_NOT_FOUND`, `ERR_CUT_PERMIT_NOT_FOUND`,
    `ERR_ACCEPTANCE_TEST_NOT_FOUND` or `ERR_SERVICE_REQUEST_NOT_FOUND`."

    Design: Corner/entities/segment_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(api)

    validate_error(
        api.get_segment(UNKNOWN_UUID, ENGINEER), ApiErrorId.SEGMENT_NOT_FOUND, 404
    )


def test_an_observation_missing_its_roughness_reading_is_rejected_outright(api):
    """The absent input is not quietly defaulted to zero and no partial row lands.

    PRD: "Required body fields present, JSON types correct, enum values in range,
    numeric fields within their declared bounds, pagination parameters legal,
    timestamps ISO 8601 UTC, and every window's end strictly after its start — else
    `ERR_INVALID_REQUEST`."

    PRD: "Each accepted filing increments the survey's `observation_count`."

    Both parents in the payload resolve, so nothing but the missing roughness reading
    can be at fault.

    Design: Corner/entities/observation_create_without_iri_returns_invalid_request
    """
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api, SEG_MAPLE)
    survey = fixtures.open_survey(api)

    validate_error(
        api.create_observation(
            observation_payload(survey["id"], segment["id"], OBS_MILL, iri_in_per_mi=OMIT),
            ENGINEER,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(api.list_observations(ENGINEER, {"limit": 100}))
    reread = validate_success(api.get_survey(survey["id"], ENGINEER))
    assert meta["total_count"] == 0
    assert reread["observation_count"] == 0
    assert reread["accepted_observation_count"] == 0


def test_a_segment_with_no_treatment_history_ages_from_its_own_creation(api):
    """Omitting the treatment date leaves the baseline standing at full value.

    PRD: "The anchor date is the segment's `last_treatment_date` when that field is
    populated, and the segment's `created_at` when it is null — a segment that has
    never been treated ages from the moment it entered the inventory."

    PRD: "Age in whole years is the number of whole days from the anchor date to the
    evaluation instant, divided by 365, with any fraction discarded."

    Cedar St is geometrically identical to Maple St and carries the same 92.0
    baseline, so the whole 16.0-point spread between 92.0 and 76.0 comes from the one
    optional field Cedar St left out.

    Design: Corner/entities/segment_create_omitting_last_treatment_date_anchors_the_decay_on_created_at
    """
    fixtures.set_clock(api)
    aged = fixtures.create_segment(api, SEG_MAPLE)
    assert_index(aged["condition_index"], PCI_MAPLE_MODEL)

    fresh = fixtures.create_segment(api, SEG_CEDAR, last_treatment_date=OMIT)

    assert fresh["last_treatment_date"] is None
    assert fresh["last_treatment_type"] == "NONE"
    assert_segment_condition(fresh, PCI_UNTREATED_MODEL, SOURCE_MODEL_PROJECTED, BAND_GOOD)
    assert fresh["condition_index"] - aged["condition_index"] == 16.0


def test_a_client_supplied_condition_index_on_an_observation_is_ignored(api):
    """The posted 99.9 appears nowhere; the five measurements decide the index.

    PRD: "The raw deduct is then the sum of five weighted terms — 0.45 times the
    alligator percentage, 0.18 times the crack density, 40.0 times the rut excess in
    inches, 0.12 times the patching percentage, and 0.08 times the roughness excess —
    and that raw sum is *not* rounded."

    PRD: "Finally `measured_condition_index` is 100 less the `deduct_total`, clamped
    into the range 0.0 through 100.0 and rounded to one decimal place."

    PRD: "Every observation starts with `qc_status` `PENDING` and a null `qc_note`."

    PRD: "Exactly three events write it: the segment's own creation, the sealing of a
    condition survey that carries an accepted observation on that segment, and the
    final acceptance of a project line that resurfaced it."

    Design: Corner/entities/observation_computed_fields_ignore_client_supplied_extra_field
    """
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api, SEG_MAPLE)
    survey = fixtures.open_survey(api)

    observation = validate_success(
        api.create_observation(
            observation_payload(
                survey["id"],
                segment["id"],
                OBS_MILL,
                measured_condition_index=99.9,
                deduct_total=0.0,
            ),
            ENGINEER,
        ),
        201,
    )

    assert observation["deduct_total"] == OBS_MILL_DEDUCT
    assert_index(observation["measured_condition_index"], OBS_MILL_INDEX)
    assert observation["measured_condition_index"] != 99.9
    assert observation["qc_status"] == "PENDING"
    assert_segment_condition(
        fixtures.read_segment(api, segment["id"]),
        PCI_MAPLE_MODEL,
        SOURCE_MODEL_PROJECTED,
        BAND_GOOD,
    )


def test_a_new_survey_publishes_its_whole_system_field_set_from_two_inputs(api):
    """Two client values in, and a fully seeded campaign row back out.

    PRD: "A new campaign has `survey_status` `OPEN`, both observation counters at
    zero, `network_condition_index` null and `sealed_at` null."

    PRD: "`OPEN` and `SEALED` are the only two states a survey ever holds; sealing is
    the sole exit and there is no un-seal."

    Design: Corner/entities/survey_system_fields_are_generated_not_accepted_from_the_client
    """
    fixtures.set_clock(api)

    survey = validate_success(
        api.create_survey(
            {"survey_year": SURVEY_YEAR, "collection_method": COLLECTION_AUTOMATED}, ENGINEER
        ),
        201,
    )

    assert_common_fields(survey)
    assert survey["survey_status"] == "OPEN"
    assert survey["observation_count"] == 0
    assert survey["accepted_observation_count"] == 0
    assert survey["network_condition_index"] is None
    assert survey["sealed_at"] is None
    assert survey["survey_year"] == SURVEY_YEAR
    assert survey["collection_method"] == COLLECTION_AUTOMATED


def test_a_twenty_one_year_horizon_is_refused_while_twenty_is_accepted(api):
    """One step outside the declared bound is a shape error, not a projection.

    PRD: "the `funding_cents` available to allocate (which must not be negative), the
    ranking `strategy`, and the `horizon_years` over which network condition should be
    projected (between 1 and 20 inclusive)."

    PRD: "Required body fields present, JSON types correct, enum values in range,
    numeric fields within their declared bounds, pagination parameters legal,
    timestamps ISO 8601 UTC, and every window's end strictly after its start — else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/scenario_create_with_horizon_years_twenty_one_returns_invalid_request
    """
    ctx = fixtures.sealed_survey(api)

    validate_error(
        api.create_scenario(scenario_payload(ctx["survey"]["id"], horizon_years=21), OFFICER),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(api.list_scenarios(OFFICER, {"limit": 100}))
    assert meta["total_count"] == 0

    inside = validate_success(
        api.create_scenario(scenario_payload(ctx["survey"]["id"], horizon_years=20), OFFICER),
        201,
    )
    assert inside["horizon_years"] == 20
    assert inside["scenario_status"] == "DRAFT"


def test_an_observation_naming_an_unknown_segment_reports_the_segment_code(api):
    """Of two parents, the unresolvable one names the error, in body order.

    PRD: "Foreign keys supplied in a request body are resolved next, in the order the
    body declares them, which for the whole API is: `survey_id`, then `segment_id`,
    then `candidate_id`, then `project_id`, then `contractor_id`, then
    `capital_project_id`."

    PRD: "The first unresolvable reference wins and reports the not-found code of its
    own collection, so a request naming both a bad survey and a bad segment reports
    `ERR_SURVEY_NOT_FOUND`."

    The survey resolves and every measurement is in range, so the segment is the sole
    defect and the shape check of priority 6 has nothing to complain about.

    Design: Corner/entities/observation_create_with_unknown_segment_returns_segment_not_found
    """
    fixtures.set_clock(api)
    survey = fixtures.open_survey(api)

    validate_error(
        api.create_observation(
            observation_payload(survey["id"], UNKNOWN_UUID, OBS_MILL), ENGINEER
        ),
        ApiErrorId.SEGMENT_NOT_FOUND,
        404,
    )

    assert validate_success(api.get_survey(survey["id"], ENGINEER))["observation_count"] == 0


def _one_bundle_binding_two_segments_and_two_candidates(api):
    """A DRAFT Z1 project carrying a mill-and-overlay line and a crack-seal line."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx["project"] = fixtures.create_project(
        api,
        ctx["scenario"]["id"],
        "Z1",
        planned_start_date=PROJECT_START,
        planned_end_date=PROJECT_END,
    )
    ctx["lines"]["Maple St"] = fixtures.add_line(
        api,
        ctx["project"]["id"],
        fixtures.segment_for(ctx, "Maple St")["id"],
        fixtures.candidate_for(ctx, "Maple St")["id"],
        *MAPLE_WINDOW,
    )
    ctx["lines"]["Oak St"] = fixtures.add_line(
        api,
        ctx["project"]["id"],
        fixtures.segment_for(ctx, "Oak St")["id"],
        fixtures.candidate_for(ctx, "Oak St")["id"],
        *OAK_WINDOW,
        design_thickness_in=OMIT,
    )
    return ctx


def test_one_bundle_binds_two_segments_to_two_candidates_of_two_treatments(api):
    """The junction row copies its treatment and area from the pair it joins.

    PRD: "Creation copies `treatment_type` from the candidate and `line_area_sy` from
    the segment's `area_sy`, computes the line's `line_cost_cents`, and starts the
    line at `work_state` `PLANNED`, `notice_state` `PENDING` and `notice_round` 1,
    with `parking_restriction_start`, `parking_restriction_end`,
    `driveway_access_plan`, `notice_delivered_at` and `pay_factor` all null and
    `test_count` zero."

    PRD: "optionally it supplies `design_thickness_in`, the design lift thickness
    that the thickness pay factor is measured against, which defaults to 2.0 inches
    and must lie between 0.5 and 12.0."

    The Oak St crack-seal line prices at 4349975 cents on 11725.00 square yards while
    its sibling on the same project carries a mill-and-overlay.

    Design: Corner/entities/project_segment_junction_binds_project_segment_and_candidate_in_one_row
    """
    ctx = _one_bundle_binding_two_segments_and_two_candidates(api)

    maple_line = ctx["lines"]["Maple St"]
    oak_line = ctx["lines"]["Oak St"]

    assert maple_line["treatment_type"] == MILL_AND_OVERLAY
    assert oak_line["treatment_type"] == CRACK_SEAL
    assert_area(oak_line["line_area_sy"], AREA_OAK)
    assert_money(oak_line["line_cost_cents"], OAK_LINE_COST)
    assert oak_line["design_thickness_in"] == DEFAULT_DESIGN_THICKNESS_IN
    assert oak_line["work_state"] == "PLANNED"
    assert oak_line["notice_state"] == "PENDING"
    assert oak_line["test_count"] == 0


def test_the_junction_rolls_two_lines_up_into_one_scope_and_one_price(api):
    """Two rows on one project aggregate into one area and one mixed-treatment price.

    PRD: "One mobilisation charge is then added for the whole bundle: 250,000 cents
    when *every* non-removed line is a `CRACK_SEAL` line, and 850,000 cents
    otherwise."

    PRD: "The candidate moves from `RECOMMENDED` or `OVERRIDDEN` to `CONSUMED` and is
    locked against override while consumed. The parent project increments
    `segment_count`, adds the line's `line_area_sy` to `planned_area_sy`, recomputes
    its estimate and increments its `version`; the referenced segment increments
    `active_project_count`."

    One line is a crack seal and one is not, so the bundle pays the 850000-cent
    mobilisation and lands on 15093298 before its 10% contingency.

    Design: Corner/entities/project_segment_junction_binds_project_segment_and_candidate_in_one_row
    """
    ctx = _one_bundle_binding_two_segments_and_two_candidates(api)

    project = fixtures.read_project(api, ctx["project"]["id"])

    assert_project_scope(project, 2, MAPLE_OAK_AREA)
    assert_project_estimate(
        project, MAPLE_OAK_BASE, MAPLE_OAK_CONTINGENCY, 0, MAPLE_OAK_TOTAL
    )
    for street in ("Maple St", "Oak St"):
        candidate = fixtures.read_candidate(api, fixtures.candidate_for(ctx, street)["id"])
        segment = fixtures.read_segment(api, fixtures.segment_for(ctx, street)["id"])
        assert candidate["candidate_status"] == "CONSUMED"
        assert segment["active_project_count"] == 1
    assert_area(
        round(
            ctx["lines"]["Maple St"]["line_area_sy"] + ctx["lines"]["Oak St"]["line_area_sy"], 2
        ),
        project["planned_area_sy"],
    )
