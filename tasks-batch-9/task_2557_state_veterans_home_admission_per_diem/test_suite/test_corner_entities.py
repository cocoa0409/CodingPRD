"""Entity-shape corners: creation defaults, derived fields, listings and rejections.

These tests probe the record contract itself rather than any workflow. They pin
what a freshly created record must carry when only the required inputs are sent,
which fields the server derives and therefore refuses to take from a client,
what a collection read must report in its pagination meta once a filter narrows
the candidate set, and which identifier a malformed or unresolvable request is
answered with. Every expectation is read off the PRD's common record properties,
its bed arithmetic, its federal rate schedule, its validation ladder and its
path- and body-resolution order.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_bed_counts,
    assert_fields,
    assert_immutable_record_fields,
    assert_page_meta,
)
from test_helpers.constants import CLOCK_EPOCH


def test_home_creation_populates_every_declared_field(api, admin_headers):
    """Registering a home with only the three required inputs returns every declared field.

    Per the PRD: "A newly registered home starts with `active_resident_count` at 0, `decertified_unit_count` at 0, `recognition_suspended_reason` null, `last_survey_date` null and `version` at 1."
    The derived counters and the suspension reason must therefore be present and
    initialised in the created resource, not merely absent from the payload.

    Design: Corner/entities/entity_veterans_home_creation_returns_declared_fields
    """
    fx.set_clock(api, CLOCK_EPOCH)

    response = api.create_veterans_home(
        f.veterans_home_payload(
            name="Alpine State Veterans Home",
            state_code="CO",
            recognition_effective_date="2026-07-01",
        ),
        admin_headers,
    )

    home = validate_success(response, expected_status=201)
    assert response.json()["response_type"] == "object"
    assert_fields(
        home,
        name="Alpine State Veterans Home",
        state_code="CO",
        recognition_effective_date="2026-07-01",
        recognition_status="RECOGNIZED",
        recognition_suspended_reason=None,
        active_resident_count=0,
        decertified_unit_count=0,
        last_survey_date=None,
        version=1,
    )


def test_care_unit_read_returns_the_stored_derived_row(api, admin_headers):
    """A read of a fresh unit returns the stored row with its derived counts already set.

    Per the PRD: "On creation the unit's `certification_status` is `CERTIFIED`, its `occupied_bed_count`, `held_bed_count` and `waitlist_active_count` are all 0, its `last_survey_compliance_score` is 0, its `last_survey_date` is null, its `per_diem_rate_cents` is set from the federal rate schedule for its own `care_level`, and its `available_bed_count` and `operational_posture` are computed from the bed arithmetic of §2.9."
    With five licensed beds and one out of service, the bed arithmetic leaves four
    free, so the read must report an OPEN posture rather than a stale zero.

    Design: Corner/entities/entity_care_unit_retrieval_matches_stored_row
    """
    fx.set_clock(api, CLOCK_EPOCH)
    home = fx.create_home(api, name="Bluff View State Veterans Home", state_code="IA")
    created = fx.create_unit(
        api,
        home["id"],
        unit_name="Nursing One",
        care_level="NURSING",
        licensed_bed_count=5,
        out_of_service_bed_count=1,
    )

    unit = validate_success(api.get_care_unit(created["id"], admin_headers), expected_status=200)

    assert_fields(
        unit,
        unit_name="Nursing One",
        veterans_home_id=home["id"],
        available_bed_count=4,
        operational_posture="OPEN",
        per_diem_rate_cents=11857,
        occupied_bed_count=0,
        held_bed_count=0,
        certification_status="CERTIFIED",
        waitlist_active_count=0,
    )
    assert_bed_counts(unit, occupied=0, held=0, available=4, posture="OPEN")


def test_home_listing_applies_the_filter_before_the_page_window(api, admin_headers):
    """A filtered home listing counts and windows only the rows the filter matched.

    Per the PRD: "`total_count` is the number of rows matching the request's filters across the whole collection, not the number of rows on the returned page, and `has_more` is true exactly when rows matching the filters remain beyond the returned page."
    Two of the three homes are in Minnesota, so a Minnesota page of two rows is
    complete, and the same filter read at offset two is empty while still counting two.

    Design: Corner/entities/entity_veterans_homes_listing_paginates_and_filters
    """
    fx.set_clock(api, CLOCK_EPOCH)
    fx.create_home(
        api,
        name="Cascade State Veterans Home",
        state_code="MN",
        recognition_effective_date="2026-07-01",
    )
    fx.create_home(
        api,
        name="Dovetail State Veterans Home",
        state_code="MN",
        recognition_effective_date="2026-07-02",
    )
    fx.create_home(
        api,
        name="Evergreen State Veterans Home",
        state_code="WI",
        recognition_effective_date="2026-07-03",
    )

    first_page, first_meta = validate_paginated(
        api.list_veterans_homes(admin_headers, {"state_code": "MN", "limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_veterans_homes(admin_headers, {"state_code": "MN", "limit": 2, "offset": 2})
    )

    assert len(first_page) == 2, f"expected 2 Minnesota homes on the first page, got {len(first_page)}"
    assert_page_meta(first_meta, limit=2, offset=0, total_count=2, has_more=False)
    assert [row["state_code"] for row in first_page] == ["MN", "MN"]
    assert len(second_page) == 0, f"expected an empty second page, got {len(second_page)}"
    assert_page_meta(second_meta, limit=2, offset=2, total_count=2, has_more=False)


def test_unknown_resident_id_is_a_not_found_rejection(api, bom_headers):
    """A well-formed but unknown resident identifier is answered with a 404, not an empty success.

    Per the PRD: "The identifier segments the system resolves are those addressing a veterans home, a care unit, an applicant, a clinical assessment, a resident, an income record, a care plan, a census day, a per diem claim and a trust fund transaction; the corresponding rejections are `ERR_HOME_NOT_FOUND`, `ERR_CARE_UNIT_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_INCOME_RECORD_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_CENSUS_DAY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_TRANSACTION_NOT_FOUND`, each HTTP 404."
    The identifier is syntactically fine, so the request-shape rung has nothing to
    say about it and the read must fall through to the existence rung.

    Design: Corner/entities/entity_resident_not_found_returns_404
    """
    fx.set_clock(api, CLOCK_EPOCH)

    response = api.get_resident(NON_EXISTENT_UUID, bom_headers)

    validate_error(response, "ERR_RESIDENT_NOT_FOUND", expected_status=404)
    assert response.json()["response_type"] == "error"


def test_applicant_filing_without_discharge_character_is_rejected(api, coordinator_headers):
    """Filing an applicant without the discharge character is a request-shape rejection.

    Per the PRD: "Every required field present, every enum value inside its declared set, every numeric field inside its declared range, dates in `YYYY-MM-DD` form and months in `YYYY-MM` form, `licensed_bed_count` at least 1, `out_of_service_bed_count` no greater than `licensed_bed_count`, `amount_cents` strictly greater than zero, `adl_dependency_count` between 0 and 6 inclusive, `service_connected_disability_pct` between 0 and 100 inclusive, and pagination `limit` between 1 and 100 inclusive with `offset` at least zero. Any violation is `ERR_INVALID_REQUEST`."
    The discharge character carries no default, so its absence must be caught
    before anything is persisted and the home's applicant list must stay empty.

    Design: Corner/entities/entity_applicant_missing_required_field_rejected
    """
    fx.set_clock(api, CLOCK_EPOCH)
    home = fx.create_home(api, name="Foxglove State Veterans Home", state_code="MN")
    payload = f.applicant_payload(home["id"], full_name="No Discharge Field")
    payload.pop("discharge_character")

    response = api.create_applicant(payload, coordinator_headers)

    validate_error(response, "ERR_INVALID_REQUEST", expected_status=422)
    rows, meta = validate_paginated(api.list_home_applicants(home["id"], coordinator_headers))
    assert len(rows) == 0, f"no applicant may have been filed, got {len(rows)}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


def test_home_optional_inputs_default_only_when_omitted(api, admin_headers):
    """The optional home inputs fall back to their declared defaults but never override a supplied value.

    Per the PRD: "`recognition_status` declares the federal standing itself and may be `RECOGNIZED`, `PROVISIONAL` or `SUSPENDED`; when omitted it defaults to `RECOGNIZED`, and `PROVISIONAL` is supplied only for a home still awaiting federal recognition."
    Per the PRD: "`personal_needs_allowance_monthly_cents` sets the monthly personal needs allowance the home credits each resident and reserves from cost-share debits; it must not be negative and defaults to 9,000 cents, that is ninety dollars a month."

    Design: Corner/entities/entity_veterans_home_optional_inputs_take_declared_defaults
    """
    fx.set_clock(api, CLOCK_EPOCH)

    defaulted = validate_success(
        api.create_veterans_home(
            f.veterans_home_payload(name="Gladstone State Veterans Home", state_code="MN"),
            admin_headers,
        ),
        expected_status=201,
    )
    explicit = validate_success(
        api.create_veterans_home(
            f.veterans_home_payload(
                name="Harborview State Veterans Home",
                state_code="MN",
                recognition_status="PROVISIONAL",
                personal_needs_allowance_monthly_cents=12500,
            ),
            admin_headers,
        ),
        expected_status=201,
    )

    assert_fields(
        defaulted,
        personal_needs_allowance_monthly_cents=9000,
        recognition_status="RECOGNIZED",
    )
    assert_fields(
        explicit,
        personal_needs_allowance_monthly_cents=12500,
        recognition_status="PROVISIONAL",
    )
    assert_fields(
        fx.read_home(api, defaulted["id"]),
        personal_needs_allowance_monthly_cents=9000,
        recognition_status="RECOGNIZED",
    )
    assert_fields(
        fx.read_home(api, explicit["id"]),
        personal_needs_allowance_monthly_cents=12500,
        recognition_status="PROVISIONAL",
    )


def test_unit_per_diem_rate_is_derived_from_its_care_level(api, admin_headers):
    """Each new unit prices itself from the federal schedule for its own care level.

    Per the PRD: "The federal daily per diem rate is fixed by care level: 11,857 cents for `NURSING`, 5,502 cents for `DOMICILIARY` and 4,230 cents for `ADULT_DAY_HEALTH`."
    Per the PRD: "A care unit's `per_diem_rate_cents` is the rate for its own `care_level`, set at unit creation and never supplied by a client."
    Per the PRD: "`available_bed_count` is the unit's `licensed_bed_count` less its `out_of_service_bed_count`, less `occupied_bed_count`, less `held_bed_count`."

    Design: Corner/entities/entity_care_unit_per_diem_rate_computed_from_care_level
    """
    fx.set_clock(api, CLOCK_EPOCH)
    home = fx.create_home(api, name="Ironwood State Veterans Home", state_code="MN")

    nursing = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(
                unit_name="Nursing N",
                care_level="NURSING",
                licensed_bed_count=6,
                out_of_service_bed_count=2,
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    domiciliary = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(
                unit_name="Domiciliary D",
                care_level="DOMICILIARY",
                licensed_bed_count=4,
                out_of_service_bed_count=0,
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    adult_day = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(
                unit_name="Adult Day A",
                care_level="ADULT_DAY_HEALTH",
                licensed_bed_count=3,
                out_of_service_bed_count=1,
            ),
            admin_headers,
        ),
        expected_status=201,
    )

    assert_fields(nursing, per_diem_rate_cents=11857, available_bed_count=4, certification_status="CERTIFIED")
    assert_fields(domiciliary, per_diem_rate_cents=5502, available_bed_count=4, operational_posture="OPEN")
    assert_fields(adult_day, per_diem_rate_cents=4230, available_bed_count=2, veterans_home_id=home["id"])


def test_client_supplied_system_fields_are_ignored_on_create(api, admin_headers):
    """A create that also sends id, version and created_at is answered with server-minted values.

    Per the PRD: "Every persisted record carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp: an ISO 8601 UTC instant with exactly three fractional digits, taken from the logical clock described in §2.5."
    Per the PRD: "Most records additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record — and `version`, an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation."
    The clock stands at the starting instant, so both timestamps are that instant
    rather than the client's 1999 value, and the version is 1 rather than 99.

    Design: Corner/entities/entity_system_fields_supplied_on_create_input_ignored
    """
    fx.set_clock(api, CLOCK_EPOCH)
    claimed_id = "00000000-0000-4000-8000-00000000dead"

    home = validate_success(
        api.create_veterans_home(
            f.veterans_home_payload(
                name="Juniper State Veterans Home",
                state_code="MN",
                id=claimed_id,
                version=99,
                created_at="1999-01-01T00:00:00Z",
            ),
            admin_headers,
        ),
        expected_status=201,
    )

    assert home["version"] == 1, f"a created record starts at version 1, got {home['version']}"
    assert home["id"] != claimed_id, "the id must be server-minted, not taken from the request"
    assert home["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"created_at must come from the logical clock, got {home['created_at']!r}"
    )
    assert home["updated_at"] == "2026-08-01T00:00:00.000Z", (
        f"updated_at must come from the logical clock, got {home['updated_at']!r}"
    )


def test_unit_creation_rejects_an_unknown_care_level_and_a_negative_bed_count(api, admin_headers):
    """A care level outside the closed enum and a bed count below one are both shape violations.

    Per the PRD: "Every required field present, every enum value inside its declared set, every numeric field inside its declared range, dates in `YYYY-MM-DD` form and months in `YYYY-MM` form, `licensed_bed_count` at least 1, `out_of_service_bed_count` no greater than `licensed_bed_count`, `amount_cents` strictly greater than zero, `adl_dependency_count` between 0 and 6 inclusive, `service_connected_disability_pct` between 0 and 100 inclusive, and pagination `limit` between 1 and 100 inclusive with `offset` at least zero. Any violation is `ERR_INVALID_REQUEST`."
    Neither attempt may leave a unit behind, so the home's unit list stays empty.

    Design: Corner/entities/entity_care_unit_invalid_care_level_enum_rejected
    """
    fx.set_clock(api, CLOCK_EPOCH)
    home = fx.create_home(api, name="Kestrel State Veterans Home", state_code="MN")

    bad_level = api.create_care_unit(
        home["id"],
        f.care_unit_payload(unit_name="Bad Level", care_level="SKILLED_NURSING", licensed_bed_count=4),
        admin_headers,
    )
    bad_beds = api.create_care_unit(
        home["id"],
        f.care_unit_payload(unit_name="Bad Beds", care_level="NURSING", licensed_bed_count=-3),
        admin_headers,
    )

    validate_error(bad_level, "ERR_INVALID_REQUEST", expected_status=422)
    validate_error(bad_beds, "ERR_INVALID_REQUEST", expected_status=422)
    rows, meta = validate_paginated(api.list_home_care_units(home["id"], admin_headers))
    assert len(rows) == 0, f"no unit may have been created, got {len(rows)}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


def test_second_determination_for_a_month_is_a_new_immutable_row(api, bom_headers):
    """A repeat determination for the same month adds a row instead of editing the first one.

    Per the PRD: "A determination is immutable once computed — a revision is expressed by creating a superseding row rather than by editing the old one — so a `CostShareDetermination` carries only `id` and `created_at`."
    Per the PRD: "It has no `updated_at` field and no `version` field at all."
    Per the PRD: "For `PROVISIONAL`, `monthly_cost_share_cents` is `tiered_share_cents` less `federal_per_diem_offset_cents` (which is zero), multiplied by `resident_day_count`, divided by the number of calendar days in `effective_month`, rounded half up, and finally floored at zero."
    Per the PRD: "`delta_from_prior_cents` records the change this determination introduces: this determination's `monthly_cost_share_cents` less the `monthly_cost_share_cents` of the prior governing determination for the same resident and the same `effective_month`, or 0 when this is the first determination for that resident-month."
    A single verified stream of 114,000 cents less the 9,000-cent allowance nets
    105,000 cents, which selects the second tier and yields 40,000 plus 2,750 cents
    over a full thirty-one-day month, so the recomputation reproduces the first row
    exactly and the delta is zero.

    Design: Corner/entities/entity_cost_share_determination_is_immutable
    """
    scenario = fx.admitted_resident(api, admission_date="2026-08-01", care_level="NURSING")
    fx.declare_income(api, scenario.resident_id, "SSA", 114000, "2026-08", verify=True)
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)

    first = validate_success(
        fx.determine_cost_share(api, scenario.resident_id, variant="PROVISIONAL", effective_month="2026-08"),
        expected_status=201,
    )
    second = validate_success(
        fx.determine_cost_share(api, scenario.resident_id, variant="PROVISIONAL", effective_month="2026-08"),
        expected_status=201,
    )

    assert_fields(
        first,
        variant="PROVISIONAL",
        effective_month="2026-08",
        gross_countable_income_cents=114000,
        pna_deduction_cents=9000,
        income_tier="TIER_2",
        allowed_medical_deduction_cents=0,
        tiered_share_cents=42750,
        resident_day_count=31,
        federal_per_diem_offset_cents=0,
        monthly_cost_share_cents=42750,
        delta_from_prior_cents=0,
    )
    assert_fields(second, monthly_cost_share_cents=42750, delta_from_prior_cents=0)
    assert first["id"] != second["id"], "a revision must be a distinct row"
    assert_immutable_record_fields(first)
    assert_immutable_record_fields(second)

    rows, meta = validate_paginated(
        api.list_cost_share_determinations(scenario.resident_id, bom_headers, {"limit": 100})
    )
    assert meta["total_count"] == 2, f"expected two determinations on record, got {meta['total_count']}"
    assert len(rows) == 2, f"expected two determinations in the page, got {len(rows)}"
    assert rows[0]["variant"] == "PROVISIONAL"


def test_care_unit_creation_under_an_unknown_home_is_a_not_found(api, admin_headers):
    """Creating a unit under an unknown home resolves the path parent and stops there.

    Per the PRD: "Identifiers embedded in a path are resolved strictly left to right, and the first one that resolves to nothing determines the error."
    Per the PRD: "The identifier segments the system resolves are those addressing a veterans home, a care unit, an applicant, a clinical assessment, a resident, an income record, a care plan, a census day, a per diem claim and a trust fund transaction; the corresponding rejections are `ERR_HOME_NOT_FOUND`, `ERR_CARE_UNIT_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_INCOME_RECORD_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_CENSUS_DAY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_TRANSACTION_NOT_FOUND`, each HTTP 404."
    The body is otherwise a perfectly valid unit, so the only rule left to fail is
    the existence of the home named in the path.

    Design: Corner/entities/entity_care_unit_under_unknown_parent_home_not_found
    """
    fx.set_clock(api, CLOCK_EPOCH)

    response = api.create_care_unit(
        NON_EXISTENT_UUID,
        f.care_unit_payload(
            unit_name="Orphan Unit",
            care_level="NURSING",
            licensed_bed_count=4,
            out_of_service_bed_count=0,
        ),
        admin_headers,
    )

    validate_error(response, "ERR_HOME_NOT_FOUND", expected_status=404)


def test_census_day_class_and_date_window_filters_intersect(api, bom_headers):
    """The census-day filters narrow the same set together rather than widening it.

    Per the PRD: "The census day collection filters on `resident_id`, `care_unit_id`, `per_diem_claim_id`, `census_class` and `claimed`, and additionally accepts the inclusive date-window bounds `service_date_from` and `service_date_to`."
    Per the PRD: "A date is a hold day when `hold_start` is present and the date falls at or after `hold_start` and strictly before `hold_end`."
    Per the PRD: "The consequences are worth stating plainly: the `hospitalization_start_date` is itself a `BED_HOLD_DAY`, and the `readmission_date` is itself a `RESIDENT_DAY`."
    The hold runs from the twentieth up to but excluding the twenty-fourth, so the
    four hold days are exactly the four dates the window names, and asking for hold
    days in the window that follows the readmission must return nothing at all.

    Design: Corner/entities/entity_census_day_listing_filters_by_class_and_date_window
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-08-05",
        application_date="2026-08-01",
        clock_before_decision="2026-08-05T00:00:00Z",
        care_level="NURSING",
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-20", clock="2026-08-20T00:00:00Z")
    fx.readmit(api, scenario.resident_id, "2026-08-24", clock="2026-08-24T00:00:00Z")
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)

    by_class, class_meta = validate_paginated(
        api.list_census_days(
            bom_headers,
            {"resident_id": scenario.resident_id, "census_class": "BED_HOLD_DAY", "limit": 100},
        )
    )
    by_window, window_meta = validate_paginated(
        api.list_census_days(
            bom_headers,
            {
                "resident_id": scenario.resident_id,
                "service_date_from": "2026-08-20",
                "service_date_to": "2026-08-23",
                "limit": 100,
            },
        )
    )
    combined, combined_meta = validate_paginated(
        api.list_census_days(
            bom_headers,
            {
                "resident_id": scenario.resident_id,
                "census_class": "BED_HOLD_DAY",
                "service_date_from": "2026-08-24",
                "service_date_to": "2026-08-31",
                "limit": 100,
            },
        )
    )

    assert class_meta["total_count"] == 4, (
        f"expected four bed-hold days, got {class_meta['total_count']}"
    )
    assert by_class[0]["census_class"] == "BED_HOLD_DAY"
    assert by_class[0]["service_date"] == "2026-08-20", (
        f"the hospitalization start date is itself a bed-hold day, got {by_class[0]['service_date']!r}"
    )
    assert window_meta["total_count"] == 4, (
        f"expected four days inside the hold window, got {window_meta['total_count']}"
    )
    assert by_window[0]["census_class"] == "BED_HOLD_DAY"
    assert combined_meta["total_count"] == 0, (
        f"no bed-hold day may fall after the readmission, got {combined_meta['total_count']}"
    )
    assert len(combined) == 0, f"expected an empty page, got {len(combined)}"
