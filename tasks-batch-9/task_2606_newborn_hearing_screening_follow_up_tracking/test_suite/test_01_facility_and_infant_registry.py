"""Registry-level behaviour: facility, provider and infant rows as stored and read."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_audiologist_headers,
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()

UNKNOWN_INFANT_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_FACILITY_ID = "00000000-0000-4000-8000-0000000000ff"


def test_new_facility_seeds_its_ledger_fields(client):
    """A registered facility comes back with every computed ledger field seeded.

    PRD: "A newly registered facility starts with `navigation_budget_units_remaining`
    equal to `navigation_budget_units_total`, a `penalty_points_balance` of 0, a
    `manual_adjustment_points_total` of 0, a `reporting_compliance_status` of
    `COMPLIANT`, and null in `performance_score`,
    `encounter_basis_performance_score`, and `last_closed_period_label`".

    Design: Corner/entities/create_facility_returns_201_with_computed_ledger_fields_initialised
    """
    response = client.create_facility(
        factories.facility_payload(
            name="Riverside Birth Hospital",
            facility_type="BIRTH_HOSPITAL",
            region_code="R1",
            navigation_budget_units_total=60,
        ),
        headers=ADMIN,
    )
    check.assert_envelope(response, "object")
    facility = check.assert_created(response)

    assert facility["name"] == "Riverside Birth Hospital"
    assert facility["facility_type"] == "BIRTH_HOSPITAL"
    assert facility["region_code"] == "R1"
    assert facility["navigation_budget_units_total"] == 60
    assert facility["navigation_budget_units_remaining"] == 60
    check.assert_facility_ledger(
        facility,
        penalty_points_balance=0,
        reporting_compliance_status="COMPLIANT",
        manual_adjustment_points_total=0,
    )
    check.assert_nulls(
        facility,
        ["performance_score", "encounter_basis_performance_score", "last_closed_period_label"],
    )
    check.assert_versioned(facility, 1)


def test_provider_read_echoes_the_stored_row(client):
    """A freshly registered navigator reads back exactly as filed, with no live workload.

    PRD: "The server also maintains `open_task_count`, initialised to 0, which
    always equals the number of navigation tasks assigned to that provider whose
    status is `OPEN`."

    Design: Corner/entities/get_provider_returns_stored_row_for_every_reader_role
    """
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R2")
    created = check.assert_created(
        client.create_provider(
            factories.provider_payload(
                facility_id=clinic["id"],
                provider_type="NAVIGATOR",
                full_name="Nia Ortiz",
                region_code="R2",
                languages=["EN", "ES"],
                max_open_tasks=3,
            ),
            headers=make_facility_admin_headers(clinic["id"]),
        )
    )

    response = client.get_provider(created["id"], headers=AUDITOR)
    provider = check.assert_ok(response)
    assert provider["facility_id"] == clinic["id"]
    assert provider["provider_type"] == "NAVIGATOR"
    assert provider["full_name"] == "Nia Ortiz"
    assert provider["region_code"] == "R2"
    assert provider["languages"] == ["EN", "ES"]
    assert provider["max_open_tasks"] == 3
    assert provider["credential_status"] == "ACTIVE"
    assert provider["open_task_count"] == 0


def test_infant_worklist_pages_report_the_filtered_total(client):
    """total_count counts every matching infant, not the rows on the page.

    PRD: "`offset` controls how many rows are skipped before the page begins: it
    defaults to 0 and its minimum accepted value is 0."

    Design: Corner/entities/list_infants_paginates_with_total_count_and_has_more
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    screener_headers = make_facility_screener_headers(screener["id"])
    for index, hour in enumerate((1, 2, 3), start=1):
        check.assert_created(
            client.create_infant(
                factories.infant_payload(
                    birth_facility_id=hospital["id"],
                    birth_datetime=clock.at(hours=hour),
                    birth_setting="INPATIENT",
                    gestational_age_weeks=39,
                    guardian_name="G-{0}".format(index),
                    guardian_contact_phone="555200{0}".format(index),
                ),
                headers=screener_headers,
            )
        )

    first = client.list_infants(
        headers=ADMIN, limit=2, offset=0, birth_facility_id=hospital["id"]
    )
    check.assert_envelope(first, "array")
    first_rows, first_meta = check.assert_page(first, 2, 3, True)
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second = client.list_infants(
        headers=ADMIN, limit=2, offset=2, birth_facility_id=hospital["id"]
    )
    second_rows, second_meta = check.assert_page(second, 1, 3, False)
    assert second_meta["offset"] == 2
    for row in first_rows + second_rows:
        assert row["birth_facility_id"] == hospital["id"]


def test_unknown_infant_id_is_a_typed_not_found(client):
    """An unknown but well-formed infant id is a 404, not an empty success.

    PRD: "The first unresolvable segment determines the code:
    `ERR_FACILITY_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_INFANT_NOT_FOUND`".

    Design: Corner/entities/get_unknown_infant_returns_infant_not_found
    """
    response = client.get_infant(UNKNOWN_INFANT_ID, headers=ADMIN)
    check.assert_error_envelope(response, errors.ERR_INFANT_NOT_FOUND)
    assert response.status_code == 404


def test_registration_without_birth_datetime_is_refused(client):
    """A missing mandatory attribute is a schema rejection that writes nothing.

    PRD: "Request schema on every write endpoint — every required body field
    present; every enum value inside its declared set; every integer inside its
    declared range; every datetime a well-formed ISO 8601 UTC instant".

    Design: Corner/entities/create_infant_missing_birth_datetime_returns_invalid_request
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")

    response = client.create_infant(
        {
            "birth_facility_id": hospital["id"],
            "birth_setting": "INPATIENT",
            "gestational_age_weeks": 39,
            "guardian_name": "G-X",
            "guardian_contact_phone": "5552101",
        },
        headers=make_facility_screener_headers(screener["id"]),
    )
    check.assert_error_envelope(response, errors.ERR_INVALID_REQUEST)
    check.assert_total_count(
        client.list_infants(headers=ADMIN, birth_facility_id=hospital["id"]), 0
    )


def test_omitted_optional_inputs_take_their_declared_defaults(client):
    """Every optional attribute materialises at its documented default.

    PRD: "Four further attributes are optional: `nicu_stay_days`, the NICU length
    of stay in days, defaulting to 0 and constrained to 0 through 365;
    `preferred_language`, drawn from `EN`, `ES`, `ZH`, `VI`, `AR`, `ASL`, and
    `OTHER` and defaulting to `EN`, which governs every piece of program
    communication with the family; `interpreter_required`, a boolean defaulting to
    false; and `guardian_consent_status`, one of `PENDING`, `GRANTED`, and
    `REFUSED`, defaulting to `GRANTED`."

    Design: Corner/entities/omitted_optional_fields_take_declared_defaults
    """
    fixtures.set_clock(client, clock.at(hours=6))
    center = check.assert_created(
        client.create_facility(
            {"name": "BC1", "facility_type": "BIRTHING_CENTER", "region_code": "R3"},
            headers=ADMIN,
        )
    )
    assert center["navigation_budget_units_total"] == 40
    assert center["navigation_budget_units_remaining"] == 40

    screener = check.assert_created(
        client.create_provider(
            {
                "facility_id": center["id"],
                "provider_type": "SCREENER",
                "full_name": "S9",
                "region_code": "R3",
            },
            headers=ADMIN,
        )
    )
    assert screener["max_open_tasks"] == 5
    assert screener["credential_status"] == "ACTIVE"
    assert screener["languages"] == ["EN"]

    infant = check.assert_created(
        client.create_infant(
            {
                "birth_facility_id": center["id"],
                "birth_datetime": clock.at(hours=2),
                "birth_setting": "BIRTHING_CENTER",
                "gestational_age_weeks": 38,
                "guardian_name": "G-9",
                "guardian_contact_phone": "5552201",
            },
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    assert infant["preferred_language"] == "EN"
    assert infant["interpreter_required"] is False
    assert infant["nicu_stay_days"] == 0
    assert infant["guardian_consent_status"] == "GRANTED"
    assert infant["discharge_datetime"] is None
    check.assert_infant_dimensions(infant, "NOT_SCREENED", "NOT_APPLICABLE")
    check.assert_risk(infant, 8, "LOW")


def test_encounter_verdict_and_age_are_computed_from_the_inputs(client):
    """The encounter's verdict, age and before-discharge flag are all derived.

    PRD: "`before_discharge` is true when the `encounter_type` is
    `BIRTH_ADMISSION` and either the infant has no `discharge_datetime` yet or the
    `performed_at` instant is at or before that `discharge_datetime`, and it is
    what the cohort-basis screening rate counts; `age_days_at_encounter` is the
    number of whole days from the infant's `birth_datetime` to `performed_at`,
    computed as the elapsed seconds divided by 86400 with the remainder
    discarded."

    Design: Corner/entities/encounter_overall_result_and_age_days_are_computed_not_accepted
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, "2026-08-03T12:00:00Z")
    screener_headers = make_facility_screener_headers(screener["id"])
    infant = check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=CLOCK_START,
                guardian_name="G-C",
                guardian_contact_phone="5552301",
            ),
            headers=screener_headers,
        )
    )

    encounter = check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-03T00:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="REFER",
            ),
            headers=screener_headers,
        )
    )
    assert encounter["overall_result"] == "REFER"
    assert encounter["age_days_at_encounter"] == 2
    assert encounter["before_discharge"] is True

    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "REFERRED"
    episodes = fixtures.episodes_of(client, infant["id"])
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["episode_type"] == "RESCREEN"
    check.assert_episode_state(episode, "PENDING_SCHEDULING", benchmark_days=30)
    check.assert_instant_equals(episode["due_date"], "2026-08-31T00:00:00Z")


def test_identity_and_audit_fields_are_stamped_by_the_server(client):
    """The server stamps the identifier, the timestamps and the opening version.

    PRD: "`version`, an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation."

    Design: Corner/entities/system_fields_are_server_generated_and_client_values_ignored
    """
    response = client.create_facility(
        {"name": "EI-North", "facility_type": "EI_PROGRAM", "region_code": "R4"},
        headers=ADMIN,
    )
    check.assert_envelope(response, "object")
    facility = check.assert_created(response)
    check.assert_record_identity(facility)
    check.assert_instant_equals(facility["created_at"], CLOCK_START)
    check.assert_instant_equals(facility["updated_at"], facility["created_at"])
    assert facility["version"] == 1


def test_out_of_set_enum_and_out_of_range_integer_are_both_schema_failures(client):
    """A value outside its declared set or range never reaches the business rules.

    PRD: "the completed `gestational_age_weeks` in the range 22 to 44 inclusive"

    Design: Corner/entities/invalid_birth_setting_enum_returns_invalid_request
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    screener_headers = make_facility_screener_headers(screener["id"])

    bad_enum = client.create_infant(
        factories.infant_payload(
            birth_facility_id=hospital["id"],
            birth_datetime=clock.at(hours=2),
            birth_setting="BIRTH_CENTRE",
            guardian_name="G-E",
            guardian_contact_phone="5552401",
        ),
        headers=screener_headers,
    )
    check.assert_error_envelope(bad_enum, errors.ERR_INVALID_REQUEST)

    bad_range = client.create_infant(
        factories.infant_payload(
            birth_facility_id=hospital["id"],
            birth_datetime=clock.at(hours=2),
            birth_setting="INPATIENT",
            gestational_age_weeks=19,
            guardian_name="G-E",
            guardian_contact_phone="5552401",
        ),
        headers=screener_headers,
    )
    check.assert_error_envelope(bad_range, errors.ERR_INVALID_REQUEST)

    check.assert_total_count(
        client.list_infants(headers=ADMIN, birth_facility_id=hospital["id"]), 0
    )


def test_screening_encounter_is_append_only_and_corrected_by_a_new_row(client):
    """An encounter carries no version or updated_at; corrections chain a new row.

    PRD: "`ScreeningEncounter` is the single exception: a screening encounter is an
    append-only clinical event with no update path at all, so it carries only `id`
    and `created_at` — it has neither an `updated_at` field nor a `version` field,
    and no operation ever modifies a screening encounter once it has been
    recorded."

    Design: Corner/entities/screening_encounter_is_append_only_with_no_version_field
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    screener_headers = make_facility_screener_headers(screener["id"])
    infant = check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=CLOCK_START,
                guardian_name="G-I",
                guardian_contact_phone="5552501",
            ),
            headers=screener_headers,
        )
    )
    first = check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at=clock.at(hours=4),
                encounter_type="BIRTH_ADMISSION",
                left_ear_result="REFER",
                right_ear_result="PASS",
            ),
            headers=screener_headers,
        )
    )
    # A surveillance screen answers the delayed-onset registry, so the infant must
    # carry an open entry for one to be recordable at all, and it is an audiologist
    # who runs it.
    fixtures.register_risk_factor(client, infant["id"], "CMV", CLOCK_START)
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    audiologist_headers = make_audiologist_headers(audiologist["id"])

    stored = check.assert_ok(client.get_encounter(first["id"], headers=AUDITOR))
    check.assert_append_only(stored)
    assert stored["left_ear_result"] == "REFER"
    assert stored["overall_result"] == "REFER"

    correction = check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=clinic["id"],
                performed_by_provider_id=audiologist["id"],
                performed_at=clock.at(hours=5),
                encounter_type="SURVEILLANCE",
                left_ear_result="PASS",
                right_ear_result="PASS",
                prior_encounter_id=first["id"],
            ),
            headers=audiologist_headers,
        )
    )
    assert correction["prior_encounter_id"] == first["id"]
    check.assert_append_only(correction)
    check.assert_total_count(
        client.list_encounters(headers=ADMIN, infant_id=infant["id"]), 2
    )


def test_provider_under_an_unknown_facility_is_a_typed_not_found(client):
    """The parent arrives as a body foreign key and must resolve.

    PRD: "Body foreign-key resolution — `birth_facility_id`, `facility_id`,
    `provider_id`, `performed_by_provider_id`, `infant_id`, `episode_id`,
    `slot_id`, `appointment_id`, `prior_encounter_id`, `supersedes_episode_id`,
    `supersedes_report_id`, `reporting_period_id`, `assigned_provider_id`, and
    `ei_program_facility_id` must all resolve, yielding the same HTTP 404 codes as
    above"

    Design: Corner/entities/create_provider_under_unknown_facility_returns_facility_not_found
    """
    ghost = client.create_provider(
        factories.provider_payload(
            facility_id=UNKNOWN_FACILITY_ID,
            provider_type="AUDIOLOGIST",
            full_name="A-ghost",
            region_code="R1",
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(ghost, errors.ERR_FACILITY_NOT_FOUND)

    clinic = fixtures.create_facility(client, "AC2", "AUDIOLOGY_CLINIC", "R1")
    provider = check.assert_created(
        client.create_provider(
            factories.provider_payload(
                facility_id=clinic["id"],
                provider_type="AUDIOLOGIST",
                full_name="A-real",
                region_code="R1",
            ),
            headers=ADMIN,
        )
    )
    assert provider["facility_id"] == clinic["id"]
    rows = check.assert_total_count(
        client.list_facility_providers(clinic["id"], headers=ADMIN), 1
    )
    assert rows[0]["id"] == provider["id"]
