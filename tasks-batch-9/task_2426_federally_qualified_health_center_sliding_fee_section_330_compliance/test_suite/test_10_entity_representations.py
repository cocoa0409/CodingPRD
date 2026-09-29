"""Entity representations: seeded defaults, computed fields, envelopes and integrity."""

import re

import pytest

from test_helpers import (
    ADMIN,
    BILLER,
    OFFICER,
    REP,
    VERIFIER,
    ApiErrorId,
    api_client,
    create_board_member_payload,
    create_discount_tier_payload,
    create_encounter_payload,
    create_health_center_payload,
    create_patient_payload,
    create_poverty_guideline_payload,
    is_valid_uuid,
    refresh_patient,
    same_instant,
    seed_poverty_guidelines,
    setup_baseline_site,
    setup_boot_core,
    setup_boot_pt,
    setup_draft_fee_schedule,
    setup_encounter,
    setup_grantee,
    setup_income_verification,
    setup_patient,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification_payload,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_FEE_SCHEDULE_UUID = "22222222-2222-4222-8222-222222222222"
THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_registering_a_grantee_echoes_its_inputs_and_seeds_the_weakest_posture():
    """A brand-new grantee starts at version 1 with every counter at zero.

    PRD 3.1: "A freshly registered grantee is deliberately in the weakest possible
    posture. `scope_baseline_locked` is false, meaning the Notice-of-Award baseline
    listing is still open. `open_condition_count`, `in_scope_site_count`,
    `in_scope_service_count`, `seated_board_count` and `wraparound_receivable_cents`
    are all zero and `patient_seat_pct` is 0. `operational_status` is `ACTIVE` and
    `scope_posture` is `OPEN`, because no condition sits on the award yet.
    `governance_posture`, however, is `GOVERNANCE_DEFICIENT`: an empty board cannot
    hold a patient majority, so scope expansion is blocked until seats are filled."

    Design: Corner/entities/health_center_creation_returns_declared_and_system_seeded_fields
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)

    response = api_client.create_health_center(
        create_health_center_payload(
            legal_name="Corner Community Health",
            grant_number="H80CS00500",
            pps_base_rate_cents=20000,
            medicare_upper_limit_cents=15000,
            nominal_fee_cap_cents=2500,
        ),
        ADMIN,
    )
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert data["legal_name"] == "Corner Community Health"
    assert data["grant_number"] == "H80CS00500"
    assert data["pps_base_rate_cents"] == 20000
    assert data["medicare_upper_limit_cents"] == 15000
    assert data["nominal_fee_cap_cents"] == 2500
    assert data["version"] == 1
    assert data["scope_baseline_locked"] is False
    assert data["operational_status"] == "ACTIVE"
    assert data["scope_posture"] == "OPEN"
    assert data["governance_posture"] == "GOVERNANCE_DEFICIENT", (
        "zero seats can never hold a patient majority, got "
        f"{data['governance_posture']}"
    )
    assert data["open_condition_count"] == 0
    assert data["in_scope_site_count"] == 0
    assert data["in_scope_service_count"] == 0
    assert data["seated_board_count"] == 0
    assert data["patient_seat_pct"] == pytest.approx(0.00, abs=0.01)
    assert data["wraparound_receivable_cents"] == 0


def test_reading_back_an_adopted_schedule_returns_exactly_what_adoption_produced():
    """Adoption is also the first annual review, and the read shows every stamp.

    PRD 3.3: "A successful adoption moves the schedule `DRAFT → ADOPTED` and stamps
    `adopted_at` and `last_reviewed_at` with the logical clock, records the adopting
    chair's identifier in `adopted_by_user_id`, and sets
    `reviewed_against_guideline_year` to the schedule's own `fpg_year` — adoption *is*
    the first annual review."

    Design: Corner/entities/fee_schedule_retrieval_returns_the_stored_adopted_row
    """
    ctx = setup_boot_core()

    response = api_client.get_fee_schedule(ctx["fee_schedule_id"], OFFICER)
    schedule = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert schedule["health_center_id"] == ctx["health_center_id"]
    assert schedule["status"] == "ADOPTED"
    assert schedule["fpg_year"] == 2026
    assert same_instant(schedule["effective_start"]) == "2026-01-01T00:00:00Z"
    assert same_instant(schedule["effective_end"]) == "2027-01-01T00:00:00Z"
    assert schedule["nominal_fee_cents"] == 2500
    assert same_instant(schedule["adopted_at"]) == "2026-08-01T00:00:00Z"
    assert schedule["adopted_by_user_id"] == ctx["chair_id"], (
        "the adopting chair recorded is the acting board member's identifier"
    )
    assert same_instant(schedule["last_reviewed_at"]) == "2026-08-01T00:00:00Z"
    assert schedule["reviewed_against_guideline_year"] == 2026
    assert schedule["review_status"] == "CURRENT"
    assert schedule["superseded_by_fee_schedule_id"] is None


def test_verifying_income_populates_five_fields_the_client_never_supplied():
    """Both percentages, both years, the expiry and the tier are all server-derived.

    PRD 3.4: "The percentage for a year is then the verification's
    `declared_annual_income_cents` divided by that guideline amount, multiplied by
    100, rounded half up to two decimal places." PRD 3.4 adds the expiry: "its
    `expires_at` is set to exactly 365 days after `effective_date` — making the
    verification's closed window run from `effective_date` through `expires_at`
    inclusive"

    Design: Corner/entities/income_verification_computed_fields_populated_on_verify
    """
    ctx = setup_boot_core()
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)
    submitted = setup_income_verification(
        patient,
        declared_annual_income_cents=1000000,
        household_size=1,
        documentation_type="TAX_RETURN",
        effective_date="2026-03-01T00:00:00Z",
    )
    assert submitted["status"] == "SUBMITTED"

    verified = validate_success(
        api_client.verify_income_verification(
            submitted["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        )
    )

    assert verified["status"] == "VERIFIED"
    assert verified["guideline_year_used"] == 2026
    assert verified["fpg_percent"] == pytest.approx(61.73, abs=0.01), (
        "1000000 over a household-of-one guideline amount of 1620000 is 61.7283…, "
        f"which rounds half up to 61.73, got {verified['fpg_percent']}"
    )
    assert verified["uds_guideline_year_used"] == 2026
    assert verified["uds_fpg_percent"] == pytest.approx(61.73, abs=0.01)
    assert (
        verified["assigned_discount_tier_id"]
        == ctx["tiers_by_label"]["NOMINAL_FULL"]["id"]
    ), "61.73 falls in the band that runs from 0 up to but excluding 100"
    assert verified["assigned_tier_label"] == "NOMINAL_FULL"
    assert same_instant(verified["expires_at"]) == "2027-03-01T00:00:00Z", (
        f"365 days after 2026-03-01 is 2027-03-01, got {verified['expires_at']}"
    )
    assert verified["verified_by_user_id"] == "ev-1"
    assert verified["supersedes_income_verification_id"] is None
    assert refresh_patient(patient["id"])["sliding_fee_status"] == "VERIFIED"


def test_listing_encounters_reports_the_total_count_and_the_declared_defaults():
    """Two rows in the table produce a paginated envelope with limit 10 and offset 0.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope. `total_count` is the number of rows
    matching the filter before pagination is applied, and `has_more` is true when rows
    remain beyond the returned page."

    Design: Corner/entities/encounter_listing_returns_paginated_envelope_with_total_count
    """
    ctx = setup_boot_pt()
    first = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )
    second = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-04-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )

    response = api_client.list_encounters(BILLER)
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "an omitted limit defaults to 10"
    assert meta["offset"] == 0, "an omitted offset defaults to 0"
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_a_well_formed_but_unknown_patient_identifier_is_a_typed_not_found():
    """The unresolved path identifier decides the response with HTTP 404.

    PRD 2.10: "Identifiers embedded in a URL path are resolved **left to right**, and
    the first one that does not resolve decides the response with HTTP 404." PRD 2.10
    lists the codes: "The full set of existence codes is
    `ERR_HEALTH_CENTER_NOT_FOUND`, `ERR_POVERTY_GUIDELINE_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_SERVICE_SITE_NOT_FOUND`,
    `ERR_SERVICE_DEFINITION_NOT_FOUND`, `ERR_SCOPE_CHANGE_REQUEST_NOT_FOUND`,
    `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_DISCOUNT_TIER_NOT_FOUND`,
    `ERR_INCOME_VERIFICATION_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_WAIVER_NOT_FOUND`, `ERR_BOARD_MEMBER_NOT_FOUND`,
    `ERR_UDS_REPORT_NOT_FOUND`, `ERR_QUALITY_MEASURE_RESULT_NOT_FOUND`,
    `ERR_SITE_VISIT_FINDING_NOT_FOUND` and `ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND`,
    each returned with HTTP 404."

    Design: Corner/entities/patient_retrieval_with_unknown_id_not_found
    """
    existing = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)

    response = api_client.get_patient(UNKNOWN_UUID, REP)
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)

    assert response.json()["response_type"] == "error"
    assert refresh_patient(existing["id"])["sliding_fee_status"] == "UNVERIFIED", (
        "the real patient is untouched by the miss on a different identifier"
    )


def test_registering_a_patient_without_a_household_size_is_refused():
    """The household size of record has no default, so its absence is a shape error.

    PRD 3.4: "A `PatientServicesRep` registers a **patient** with an `mrn` — the
    medical record number, unique across all patients and non-empty — a `full_name`,
    and a `household_size` of at least 1 recording the declared family size of
    record." PRD 2.12 rung 4: "On every write endpoint, the body contains every
    required input field, every enum-typed value is a declared member of that enum,
    every integer and number satisfies its declared constraint, and no system-managed
    or computed field is supplied by the client — otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/patient_creation_missing_required_household_size_returns_invalid_request
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    payload = create_patient_payload(mrn="MRN-C99", full_name="Nia Bell")
    payload.pop("household_size")

    validate_error(
        api_client.create_patient(payload, REP),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )

    _rows, meta = validate_paginated(api_client.list_patients(REP))
    assert meta["total_count"] == 0, (
        "the refused registration persisted no partial row"
    )


def test_two_omitted_optional_inputs_take_their_declared_defaults():
    """The nominal fee cap falls back to twenty-five dollars and the industry flag to false.

    PRD 3.1: "A fourth field, `nominal_fee_cap_cents`, is optional: it is the
    regulatory ceiling that a fee schedule's nominal charge may not exceed, it must be
    greater than zero, and when the registration omits it the grantee is created with
    a cap of 2,500 cents — that is, twenty-five dollars." PRD 3.2: "The boolean
    `derives_over_10pct_income_from_healthcare`, which records that a member draws
    more than ten percent of annual income from the health care industry, defaults to
    false and may only be set true on a `NON_PATIENT` seat."

    Design: Corner/entities/health_center_nominal_fee_cap_default_applied_when_omitted
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee_payload = create_health_center_payload(
        legal_name="Default Cap Health",
        grant_number="H80CS00501",
        pps_base_rate_cents=17000,
        medicare_upper_limit_cents=16000,
    )
    grantee_payload.pop("nominal_fee_cap_cents")

    grantee = validate_success(
        api_client.create_health_center(grantee_payload, ADMIN), 201
    )
    member = validate_success(
        api_client.create_board_member(
            grantee["id"],
            create_board_member_payload(seat_number=1, expertise_category="LEGAL"),
            OFFICER,
        ),
        201,
    )

    assert grantee["nominal_fee_cap_cents"] == 2500
    assert member["derives_over_10pct_income_from_healthcare"] is False
    assert member["status"] == "SEATED"
    assert member["patient_seat_qualified"] is False, (
        "a non-patient seat is never a qualified patient seat"
    )
    assert member["resignation_date"] is None


def test_an_encounters_state_fields_are_server_seeded_and_may_not_be_supplied():
    """The system mints the identity and the claim state; a client value is refused.

    PRD 3.5: "`pps_claim_status` starts at `UNBILLED` and `wraparound_status` starts
    at `NOT_APPLICABLE`; `charge_adjustment_cents`, `waived_amount_cents` and
    `mco_paid_cents` all start at 0; `claim_reference` and `void_reason` start null."
    PRD 2.4: "`id` (string): a server-minted UUID. It carries no type prefix and no
    embedded meaning; clients never supply it."

    Design: Corner/entities/encounter_system_fields_generated_and_client_input_ignored
    """
    ctx = setup_boot_pt()

    encounter = validate_success(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                ctx["site_id"],
                ctx["service_id"],
                encounter_date="2026-03-15T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        201,
    )

    assert is_valid_uuid(encounter["id"]), (
        f"the identifier is a bare UUID with no type prefix, got {encounter['id']}"
    )
    assert encounter["version"] == 1
    assert THREE_FRACTIONAL_DIGITS.match(encounter["created_at"]), (
        "created_at is an ISO 8601 UTC timestamp with three fractional digits, got "
        f"{encounter['created_at']}"
    )
    assert encounter["pps_claim_status"] == "UNBILLED"
    assert encounter["wraparound_status"] == "NOT_APPLICABLE"
    assert encounter["charge_adjustment_cents"] == 0
    assert encounter["waived_amount_cents"] == 0
    assert encounter["claim_reference"] is None

    smuggled = create_encounter_payload(
        ctx["patient_id"],
        ctx["site_id"],
        ctx["service_id"],
        encounter_date="2026-03-16T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
        pps_claim_status="PAID",
    )
    validate_error(
        api_client.create_encounter(smuggled, BILLER),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )


def test_an_undeclared_enum_member_and_two_out_of_range_numbers_are_all_refused():
    """Three distinct shape violations answer with the one shape error.

    PRD 2.12 rung 4: "On every write endpoint, the body contains every required input
    field, every enum-typed value is a declared member of that enum, every integer and
    number satisfies its declared constraint, and no system-managed or computed field
    is supplied by the client — otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/invalid_enum_and_out_of_range_numeric_inputs_rejected
    """
    ctx = setup_boot_pt()

    validate_error(
        api_client.create_board_member(
            ctx["health_center_id"],
            create_board_member_payload(seat_number=2, seat_type="OWNER"),
            OFFICER,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )
    validate_error(
        api_client.create_patient(
            create_patient_payload(
                mrn="MRN-C98", full_name="Zero Household", household_size=0
            ),
            REP,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )
    validate_error(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                ctx["site_id"],
                ctx["service_id"],
                encounter_date="2026-03-15T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=0,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )

    _members, member_meta = validate_paginated(
        api_client.list_board_members(
            OFFICER, params={"health_center_id": ctx["health_center_id"]}
        )
    )
    assert member_meta["total_count"] == 1, (
        "only the bootstrap seat survives the refused seating"
    )
    _encounters, encounter_meta = validate_paginated(api_client.list_encounters(BILLER))
    assert encounter_meta["total_count"] == 0


def test_a_published_guideline_year_carries_no_version_and_cannot_be_republished():
    """The guideline table is the one entity outside the versioned-record contract.

    PRD 2.4: "`PovertyGuideline` is the single exception. A published guideline year is
    immutable — there is no endpoint that modifies one — so a `PovertyGuideline` row
    carries only `id` and `created_at`. It has no `updated_at` field and no `version`
    field, and neither field appears in its response payload." PRD 3.1: "Both amounts
    must be greater than zero, and a duplicate `guideline_year` is rejected with
    `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/poverty_guideline_is_immutable_with_no_version_and_no_update_endpoint
    """
    published = seed_poverty_guidelines(CORNER_2026_GUIDELINE)[2026]

    stored = validate_success(
        api_client.get_poverty_guideline(published["id"], OFFICER)
    )
    assert set(stored) == {
        "id",
        "created_at",
        "guideline_year",
        "base_amount_cents",
        "increment_cents",
    }, f"the guideline payload carries exactly five fields, got {sorted(stored)}"
    assert "version" not in stored
    assert "updated_at" not in stored

    validate_error(
        api_client.create_poverty_guideline(
            create_poverty_guideline_payload(
                guideline_year=2026,
                base_amount_cents=9990000,
                increment_cents=990000,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
        409,
    )

    unchanged = validate_success(
        api_client.get_poverty_guideline(published["id"], OFFICER)
    )
    assert unchanged["base_amount_cents"] == 1620000, (
        "the refused re-publication did not overwrite the published figures"
    )
    assert unchanged["increment_cents"] == 570000


def test_a_tier_cannot_be_hung_on_a_fee_schedule_that_does_not_exist():
    """The path identifier is resolved before any body-level tier rule runs.

    PRD 2.12 rung 6: "On every endpoint carrying a path identifier, each path
    identifier resolves, left to right — otherwise the matching not-found code of the
    unresolved entity, drawn from the list in section 2.10 (404)."

    Design: Corner/entities/discount_tier_parent_fee_schedule_must_exist_not_found
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
        medicare_upper_limit_cents=15000,
        nominal_fee_cap_cents=2500,
    )
    draft = setup_draft_fee_schedule(grantee["id"], ladder=None)

    validate_error(
        api_client.create_discount_tier(
            UNKNOWN_FEE_SCHEDULE_UUID,
            create_discount_tier_payload(tier_label="ORPHAN"),
            OFFICER,
        ),
        ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND.value,
        404,
    )

    _tiers, meta = validate_paginated(
        api_client.list_fee_schedule_discount_tiers(
            draft["fee_schedule"]["id"], OFFICER
        )
    )
    assert meta["total_count"] == 0, (
        "the real schedule's ladder gained nothing from the refused call"
    )


def test_an_encounter_whose_site_and_service_belong_to_different_grantees_is_refused():
    """Both rows exist and both are in scope, but they are not the same grantee's.

    PRD 2.10: "Existence is not enough — a reference must also belong to the right
    grantee." PRD 3.5 states it for this endpoint: "And the site and the service must
    belong to one and the same grantee, or the request is rejected with
    `ERR_CROSS_GRANTEE_REFERENCE`."

    Design: Corner/entities/encounter_site_and_service_from_different_grantees_rejected
    """
    ctx = setup_boot_pt()
    other = setup_grantee(
        legal_name="Second Corner Health",
        grant_number="H80CS00502",
        pps_base_rate_cents=19000,
        medicare_upper_limit_cents=15000,
        nominal_fee_cap_cents=2500,
    )
    other_site = setup_baseline_site(
        other["id"],
        site_name="Second Corner Clinic",
        address_line="9 Other St",
        weekly_service_hours=30,
    )
    assert other_site["status"] == "IN_SCOPE"

    validate_error(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                other_site["id"],
                ctx["service_id"],
                encounter_date="2026-03-15T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_CROSS_GRANTEE_REFERENCE.value,
        409,
    )

    _rows, meta = validate_paginated(api_client.list_encounters(BILLER))
    assert meta["total_count"] == 0
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0, (
        "no ledger movement followed the refused encounter"
    )
