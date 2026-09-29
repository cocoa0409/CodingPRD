"""Error identity and the order in which competing rejections are reported.

The API answers a fixed catalogue of error identifiers, and two things about that
catalogue are contractual rather than incidental. Each identifier is specific:
every addressable row type carries its own 404, and an absent header is never
reported as a role failure or as a shape failure. And the identifiers are
ordered: when a request breaks several rules at once, the rung the PRD lists
first is the one the client is told about, so the same call answers a different
identifier depending only on which rung it trips first.

These tests drive each rejection from an otherwise legal request, so the only
reason the call fails is the single rule under examination, and they check the
surrounding record afterwards to show the refused write left nothing behind.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_CARE_PLAN_NOT_FOUND,
    ERR_CENSUS_DAY_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_HOME_RECOGNITION_STATE_INVALID,
    ERR_INCOME_RECORD_NOT_FOUND,
    ERR_INCOME_RECORD_STATE_INVALID,
    ERR_NO_WAITLIST_ENTRY_FOR_UNIT,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RESIDENT_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TRANSACTION_ALREADY_REVERSED,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_bed_counts, assert_fields
from test_helpers.test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_BOM_USER,
    SECOND_BOM_USER,
    make_admissions_coordinator_headers,
    make_business_office_manager_headers,
    make_clinical_assessor_headers,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_headers_unknown_role,
    make_resident_representative_headers,
    make_state_program_admin_headers,
    make_survey_agency_headers,
)

THIRD_BOM_USER = "bom-3"


# ---------------------------------------------------------------------------
# Private scenario helpers
# ---------------------------------------------------------------------------
def _one_home(api):
    """A single recognized home, so the addressed collection is non-empty."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return fx.create_home(
        api, name="Gladstone State Veterans Home", recognition_effective_date="2026-07-01"
    )


def _decision_response(api, applicant_id, care_unit_id, assessment_id, headers,
                       admission_date="2026-08-01"):
    """Post an admission decision under arbitrary headers, pinning the unit version."""
    unit_version = fx.read_unit(api, care_unit_id)["version"]
    payload = f.admission_decision_payload(
        care_unit_id, assessment_id, unit_version, admission_date
    )
    return api.admission_decision(applicant_id, payload, headers)


def _admitted_plus_second_candidate(api):
    """One admitted resident, plus a second candidate whose decision is otherwise legal."""
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=3
    )
    queued = fx.queue_second_applicant(api, scenario)
    assessment = fx.create_assessment(
        api,
        queued["applicant"]["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    fx.submit_assessment(api, assessment["id"], DEFAULT_ASSESSOR_USER)
    return scenario, queued["applicant"]["id"], assessment["id"]


def _resident_with_two_august_income_records(api):
    """An admitted resident with two undecided August income streams."""
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    ssa = fx.declare_income(
        api, scenario.resident_id, "SSA", 114000, "2026-08", verify=False,
        bom_user_id=DEFAULT_BOM_USER,
    )
    compensation = fx.declare_income(
        api, scenario.resident_id, "VA_COMPENSATION", 50000, "2026-08", verify=False,
        bom_user_id=DEFAULT_BOM_USER,
    )
    return scenario, ssa, compensation


def _resident_with_deposit(api):
    """An admitted resident carrying a single 50,000-cent deposit recorded by bom-1."""
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    deposit = validate_success(
        fx.post_trust_entry(
            api,
            scenario.resident_id,
            "DEPOSIT",
            50000,
            "2026-08-01",
            memo="family deposit",
            bom_user_id=DEFAULT_BOM_USER,
        ),
        201,
    )
    return scenario, deposit


def _two_homes_of_different_standing(api):
    """A recognized home and a provisional one, neither carrying any care unit."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    recognized = fx.create_home(
        api, name="Larkspur State Veterans Home", recognition_effective_date="2026-07-01"
    )
    provisional = fx.create_home(
        api,
        name="Meadowlark State Veterans Home",
        recognition_status="PROVISIONAL",
        recognition_effective_date="2026-07-15",
    )
    return recognized, provisional


def _queued_on_the_first_of_two_nursing_units(api):
    """One eligible applicant queued on Nursing A only, with a submitted nursing assessment."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(
        api, name="Northfield State Veterans Home", recognition_effective_date="2026-07-01"
    )
    unit_a = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    unit_b = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry_a = fx.create_waitlist_entry(api, applicant["id"], unit_a["id"])
    assessment = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    fx.submit_assessment(api, assessment["id"], DEFAULT_ASSESSOR_USER)
    return {
        "home_id": home["id"],
        "unit_a_id": unit_a["id"],
        "unit_b_id": unit_b["id"],
        "applicant_id": applicant["id"],
        "entry_a_id": entry_a["id"],
        "assessment_id": assessment["id"],
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_missing_or_unknown_auth_headers_are_all_unauthenticated(api):
    """An absent role header, an absent user header and an unrecognised role all answer 401.

    Per the PRD: "If either header is absent, or if `X-User-Role` is not one of
    the seven role names the system recognizes, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." The same read succeeds once a recognised
    role presents both headers, so the rejection is about the headers alone and
    not about the collection being unreadable.

    Design: Corner/errors/err_unauthenticated_missing_header_or_unknown_role
    """
    _one_home(api)

    no_role = api.list_veterans_homes(make_headers_missing_role("admin-1"), {"limit": 10})
    validate_error(no_role, ERR_UNAUTHENTICATED, 401)

    no_user_id = api.list_veterans_homes(
        make_headers_missing_user_id("StateProgramAdmin"), {"limit": 10}
    )
    validate_error(no_user_id, ERR_UNAUTHENTICATED, 401)

    unknown_role = api.list_veterans_homes(make_headers_unknown_role("janitor-1"), {"limit": 10})
    validate_error(unknown_role, ERR_UNAUTHENTICATED, 401)

    permitted = api.list_veterans_homes(make_survey_agency_headers("survey-1"), {"limit": 10})
    _rows, meta = validate_paginated(permitted)
    assert meta["total_count"] == 1


def test_authentication_is_reported_before_request_shape_validation(api):
    """A malformed body sent under an unrecognised role reports the authentication failure.

    Per the PRD: "Every endpoint evaluates its applicable rules in the following
    sequence, and the first rule that fails is the one reported." Authentication
    is the first rung and request shape the third, so a registration payload
    missing its required `name` and `recognition_effective_date` still answers
    `ERR_UNAUTHENTICATED` rather than the shape rejection, and no home is
    registered.

    Design: Corner/errors/err_unauthenticated_missing_header_or_unknown_role
    """
    _one_home(api)

    response = api.create_veterans_home(
        {"state_code": "MN"}, make_headers_unknown_role("janitor-1")
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)

    _rows, meta = validate_paginated(
        api.list_veterans_homes(make_state_program_admin_headers(), {"limit": 10})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Existence: one identifier per addressable row type
# ---------------------------------------------------------------------------
def test_each_addressable_row_type_answers_its_own_not_found_identifier(api):
    """Six different addressable row types answer six different 404 identifiers.

    Per the PRD: "The identifier segments the system resolves are those
    addressing a veterans home, a care unit, an applicant, a clinical assessment,
    a resident, an income record, a care plan, a census day, a per diem claim and
    a trust fund transaction; the corresponding rejections are
    `ERR_HOME_NOT_FOUND`, `ERR_CARE_UNIT_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_INCOME_RECORD_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`,
    `ERR_CENSUS_DAY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and
    `ERR_TRANSACTION_NOT_FOUND`, each HTTP 404." The two writes among them are
    refused on the missing path identifier alone, before any state rule of the
    endpoint could be consulted.

    Design: Corner/errors/err_addressed_row_not_found_ids_are_distinct
    """
    home = _one_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )

    submit = api.submit_clinical_assessment(
        NON_EXISTENT_UUID, {}, make_clinical_assessor_headers()
    )
    validate_error(submit, ERR_ASSESSMENT_NOT_FOUND, 404)

    verify = api.verify_income_record(
        NON_EXISTENT_UUID,
        f.income_verification_payload("VERIFIED"),
        make_business_office_manager_headers(),
    )
    validate_error(verify, ERR_INCOME_RECORD_NOT_FOUND, 404)

    care_plan = api.get_care_plan(NON_EXISTENT_UUID, make_clinical_assessor_headers())
    validate_error(care_plan, ERR_CARE_PLAN_NOT_FOUND, 404)

    census_day = api.get_census_day(NON_EXISTENT_UUID, make_business_office_manager_headers())
    validate_error(census_day, ERR_CENSUS_DAY_NOT_FOUND, 404)

    claim = api.get_per_diem_claim(NON_EXISTENT_UUID, make_business_office_manager_headers())
    validate_error(claim, ERR_CLAIM_NOT_FOUND, 404)

    transaction = api.get_trust_fund_transaction(
        NON_EXISTENT_UUID, make_business_office_manager_headers()
    )
    validate_error(transaction, ERR_TRANSACTION_NOT_FOUND, 404)

    still_there = validate_success(
        api.get_care_unit(unit["id"], make_business_office_manager_headers()), 200
    )
    assert still_there["certification_status"] == "CERTIFIED"


# ---------------------------------------------------------------------------
# The role rung, the not-found rung and the ownership rung
# ---------------------------------------------------------------------------
def test_survey_agency_may_not_record_an_admission_decision(api):
    """An otherwise legal admission decision taken by the survey agency is refused on role alone.

    Per the PRD: "If the headers are well-formed but the declared role is not
    among the roles authorized for the target operation in the endpoint table of
    §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." The
    admission decision authorises the admissions coordinator only, so the survey
    agency is turned away even though the applicant is waitlisted, the assessment
    is submitted, the unit is certified, open, level-matched and has free beds.

    Design: Corner/errors/err_role_check_precedes_ownership_and_survey_agency_cannot_admit
    """
    scenario, applicant_id, assessment_id = _admitted_plus_second_candidate(api)

    response = _decision_response(
        api,
        applicant_id,
        scenario.unit_id,
        assessment_id,
        make_survey_agency_headers("survey-1"),
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

    applicant = fx.read_applicant(api, applicant_id)
    assert applicant["status"] == "WAITLISTED"


def test_resident_representative_write_is_refused_at_the_role_rung(api):
    """A representative writing an income record for their own resident is refused on role, not ownership.

    Per the PRD: "A `ResidentRepresentative` is the resident or the resident's
    legal representative and is read-only throughout." Declaring an income stream
    authorises the business office manager only, so the representative's write is
    rejected with `ERR_ROLE_NOT_PERMITTED` even though the resident addressed is
    the very resident they act for, and no income record is created.

    Design: Corner/errors/err_role_check_precedes_ownership_and_survey_agency_cannot_admit
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=3
    )

    response = api.create_income_record(
        scenario.resident_id,
        f.income_record_payload("SSA", 114000, "2026-08"),
        make_resident_representative_headers(scenario.resident_id),
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

    _rows, meta = validate_paginated(
        api.list_income_records(
            scenario.resident_id, make_business_office_manager_headers(), {"limit": 10}
        )
    )
    assert meta["total_count"] == 0


def test_a_missing_resident_outranks_owner_scoping_for_a_representative(api):
    """A representative reading a missing resident learns it is missing; reading another's is an ownership failure.

    Per the PRD: "A `ResidentRepresentative` reaching for another resident's
    record, income, cost-share determinations, care plans or trust-fund activity
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." Path existence is
    resolved before owner scoping, so the same non-owner caller gets
    `ERR_RESIDENT_NOT_FOUND` for an absent identifier and
    `ERR_NOT_RESOURCE_OWNER` only once the addressed resident really exists,
    while the owner's own read succeeds.

    Design: Corner/errors/err_role_check_precedes_ownership_and_survey_agency_cannot_admit
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=3
    )
    outsider = make_resident_representative_headers("outsider-1")

    missing = api.get_resident(NON_EXISTENT_UUID, outsider)
    validate_error(missing, ERR_RESIDENT_NOT_FOUND, 404)

    not_owner = api.get_resident(scenario.resident_id, outsider)
    validate_error(not_owner, ERR_NOT_RESOURCE_OWNER, 403)

    owned = validate_success(
        api.get_resident(
            scenario.resident_id, make_resident_representative_headers(scenario.resident_id)
        ),
        200,
    )
    assert_fields(owned, occupancy_status="ADMITTED", care_unit_id=scenario.unit_id)

    _rows, meta = validate_paginated(
        api.list_residents(
            make_business_office_manager_headers(),
            {"care_unit_id": scenario.unit_id, "limit": 10},
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Income verification is a one-shot transition
# ---------------------------------------------------------------------------
def test_second_verification_of_a_verified_income_record_is_refused(api):
    """A verified record cannot be decided again, and the second caller does not overwrite the first.

    Per the PRD: "Only a record whose `verification_status` is still `UNVERIFIED`
    may be decided; a second attempt on an already-decided record is rejected with
    `ERR_INCOME_RECORD_STATE_INVALID` (HTTP 409)." Per the PRD: "The decision is
    written to `verification_status`, `verified_by_user_id` is taken from the
    acting `X-User-ID`, the record's own `version` increments and so does the
    parent resident's." The refused second decision therefore leaves both the
    status and the recorded verifier exactly as the first decision left them.

    Design: Corner/errors/err_income_record_state_invalid_on_second_verification
    """
    scenario, ssa, _compensation = _resident_with_two_august_income_records(api)
    assert ssa["verification_status"] == "UNVERIFIED"

    verified = validate_success(
        api.verify_income_record(
            ssa["id"],
            f.income_verification_payload("VERIFIED"),
            make_business_office_manager_headers(DEFAULT_BOM_USER),
        ),
        200,
    )
    assert_fields(verified, verification_status="VERIFIED", verified_by_user_id=DEFAULT_BOM_USER)

    second = api.verify_income_record(
        ssa["id"],
        f.income_verification_payload("REJECTED"),
        make_business_office_manager_headers(SECOND_BOM_USER),
    )
    validate_error(second, ERR_INCOME_RECORD_STATE_INVALID, 409)

    rows, meta = validate_paginated(
        api.list_income_records(
            scenario.resident_id,
            make_business_office_manager_headers(),
            {"effective_month": "2026-08", "verification_status": "VERIFIED", "limit": 10},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ssa["id"]
    assert rows[0]["verified_by_user_id"] == DEFAULT_BOM_USER


def test_second_verification_of_a_rejected_income_record_is_refused(api):
    """A rejected record is decided too, so a later verification attempt is refused as well.

    Per the PRD: "Only a record whose `verification_status` is still `UNVERIFIED`
    may be decided; a second attempt on an already-decided record is rejected with
    `ERR_INCOME_RECORD_STATE_INVALID` (HTTP 409)." Both landing statuses close the
    record, so the rejected stream stays `REJECTED` and the resident keeps both
    of the month's declared streams.

    Design: Corner/errors/err_income_record_state_invalid_on_second_verification
    """
    scenario, _ssa, compensation = _resident_with_two_august_income_records(api)

    rejected = validate_success(
        api.verify_income_record(
            compensation["id"],
            f.income_verification_payload("REJECTED"),
            make_business_office_manager_headers(DEFAULT_BOM_USER),
        ),
        200,
    )
    assert rejected["verification_status"] == "REJECTED"

    second = api.verify_income_record(
        compensation["id"],
        f.income_verification_payload("VERIFIED"),
        make_business_office_manager_headers(SECOND_BOM_USER),
    )
    validate_error(second, ERR_INCOME_RECORD_STATE_INVALID, 409)

    still_rejected, rejected_meta = validate_paginated(
        api.list_income_records(
            scenario.resident_id,
            make_business_office_manager_headers(),
            {"effective_month": "2026-08", "verification_status": "REJECTED", "limit": 10},
        )
    )
    assert rejected_meta["total_count"] == 1
    assert still_rejected[0]["id"] == compensation["id"]

    _rows, meta = validate_paginated(
        api.list_income_records(
            scenario.resident_id,
            make_business_office_manager_headers(),
            {"effective_month": "2026-08", "limit": 10},
        )
    )
    assert meta["total_count"] == 2


def test_the_countable_rate_of_a_declared_stream_is_fixed_by_its_income_type(api):
    """Each declared stream carries the countable rate and countable amount its type dictates.

    Per the PRD: "`countable_rate_bps` is set from the countable-rate schedule, in
    basis points of the gross: 10,000 basis points — the whole amount — for `SSA`,
    `MILITARY_RETIREMENT` and `OTHER`; 8,000 basis points, that is eighty percent,
    for `VA_COMPENSATION`; and 0 basis points for `VA_PENSION`, which therefore
    never contributes to cost share at all." Both streams start undecided, so the
    rate is settled at declaration rather than at verification.

    Design: Corner/errors/err_income_record_state_invalid_on_second_verification
    """
    _scenario, ssa, compensation = _resident_with_two_august_income_records(api)

    assert_fields(
        ssa,
        countable_rate_bps=10000,
        countable_amount_cents=114000,
        verification_status="UNVERIFIED",
    )
    assert_fields(
        compensation,
        countable_rate_bps=8000,
        countable_amount_cents=40000,
        verification_status="UNVERIFIED",
    )


# ---------------------------------------------------------------------------
# Trust-fund reversal: the state rung outranks segregation of duties
# ---------------------------------------------------------------------------
def test_the_recorder_of_a_posting_may_not_reverse_it(api):
    """While the deposit stands un-reversed, its own recorder's reversal is a segregation failure.

    Per the PRD: "Second, the operator who reverses a trust-fund posting must not
    be the operator who recorded it: if the acting `X-User-ID` equals the target
    posting's `recorded_by_user_id`, the reversal is rejected with the same
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." The refused attempt writes nothing:
    the deposit keeps its signed amount, its balance and a false `reversed` flag.

    Design: Corner/errors/err_transaction_already_reversed_outranks_segregation_of_duties
    """
    scenario, deposit = _resident_with_deposit(api)
    assert_fields(
        deposit,
        signed_amount_cents=50000,
        balance_after_cents=50000,
        reversed=False,
        recorded_by_user_id=DEFAULT_BOM_USER,
    )

    response = api.reverse_trust_fund_transaction(
        deposit["id"],
        f.reversal_payload("recorder tries to undo their own entry"),
        make_business_office_manager_headers(DEFAULT_BOM_USER),
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = fx.read_transaction(api, deposit["id"])
    assert_fields(unchanged, reversed=False, signed_amount_cents=50000)
    assert fx.read_resident(api, scenario.resident_id)["trust_fund_balance_cents"] == 50000


def test_an_already_reversed_posting_reports_the_state_rung_not_segregation(api):
    """Once another operator has reversed the deposit, the recorder's next attempt is a state failure.

    Per the PRD: "A row may be reversed only once and a `REVERSAL` may not itself
    be reversed: an attempt on a row whose `reversed` flag is already true, or on a
    row whose `txn_type` is `REVERSAL`, is rejected with
    `ERR_TRANSACTION_ALREADY_REVERSED` (HTTP 409)." State preconditions are
    evaluated before segregation of duties, so the original recorder's second
    attempt reports exactly `ERR_TRANSACTION_ALREADY_REVERSED` even though their
    segregation violation is still present.

    Design: Corner/errors/err_transaction_already_reversed_outranks_segregation_of_duties
    """
    scenario, deposit = _resident_with_deposit(api)

    reversal = validate_success(
        api.reverse_trust_fund_transaction(
            deposit["id"],
            f.reversal_payload("second operator reverses"),
            make_business_office_manager_headers(SECOND_BOM_USER),
        ),
        201,
    )
    assert_fields(
        reversal,
        txn_type="REVERSAL",
        amount_cents=50000,
        signed_amount_cents=-50000,
        balance_after_cents=0,
        reverses_transaction_id=deposit["id"],
        recorded_by_user_id=SECOND_BOM_USER,
    )

    again = api.reverse_trust_fund_transaction(
        deposit["id"],
        f.reversal_payload("third attempt by the original recorder"),
        make_business_office_manager_headers(DEFAULT_BOM_USER),
    )
    validate_error(again, ERR_TRANSACTION_ALREADY_REVERSED, 409)

    assert fx.read_transaction(api, deposit["id"])["reversed"] is True
    assert fx.read_resident(api, scenario.resident_id)["trust_fund_balance_cents"] == 0

    _all_rows, all_meta = validate_paginated(
        api.list_trust_fund_transactions(
            make_business_office_manager_headers(),
            {"resident_id": scenario.resident_id, "limit": 10},
        )
    )
    assert all_meta["total_count"] == 2

    reversed_rows, reversed_meta = validate_paginated(
        api.list_trust_fund_transactions(
            make_business_office_manager_headers(),
            {"resident_id": scenario.resident_id, "reversed": "true", "limit": 10},
        )
    )
    assert reversed_meta["total_count"] == 1
    assert reversed_rows[0]["id"] == deposit["id"]


def test_a_reversal_row_may_not_itself_be_reversed(api):
    """The compensating row is not itself reversible, whoever asks.

    Per the PRD: "A row may be reversed only once and a `REVERSAL` may not itself
    be reversed: an attempt on a row whose `reversed` flag is already true, or on a
    row whose `txn_type` is `REVERSAL`, is rejected with
    `ERR_TRANSACTION_ALREADY_REVERSED` (HTTP 409)." A third operator, who recorded
    neither row and so breaks no segregation rule, is still refused, and the
    resident's balance stays where the reversal left it.

    Design: Corner/errors/err_transaction_already_reversed_outranks_segregation_of_duties
    """
    scenario, deposit = _resident_with_deposit(api)
    reversal = validate_success(
        api.reverse_trust_fund_transaction(
            deposit["id"],
            f.reversal_payload("second operator reverses"),
            make_business_office_manager_headers(SECOND_BOM_USER),
        ),
        201,
    )

    chained = api.reverse_trust_fund_transaction(
        reversal["id"],
        f.reversal_payload("reversing the reversal"),
        make_business_office_manager_headers(THIRD_BOM_USER),
    )
    validate_error(chained, ERR_TRANSACTION_ALREADY_REVERSED, 409)

    _rows, meta = validate_paginated(
        api.list_trust_fund_transactions(
            make_business_office_manager_headers(),
            {"resident_id": scenario.resident_id, "limit": 10},
        )
    )
    assert meta["total_count"] == 2
    assert fx.read_resident(api, scenario.resident_id)["trust_fund_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Recognition actions are legal from exactly one standing
# ---------------------------------------------------------------------------
def test_a_recognition_action_that_mismatches_the_home_standing_is_refused(api):
    """A grant or a restore on a recognized home, and a suspend on a provisional one, are all refused.

    Per the PRD: "An action that does not match the home's current standing — a
    `GRANT` on a home that is not `PROVISIONAL`, a `SUSPEND` on a home that is not
    `RECOGNIZED`, a `RESTORE` on a home that is not `SUSPENDED` — is rejected with
    `ERR_HOME_RECOGNITION_STATE_INVALID` (HTTP 409), and so is a `RESTORE`
    attempted while at least one of the home's units is still decertified." The
    action is not an idempotent setter: the refused calls leave both
    `recognition_status` and `recognition_effective_date` exactly as registered.

    Design: Corner/errors/err_home_recognition_state_invalid_for_mismatched_action
    """
    recognized, provisional = _two_homes_of_different_standing(api)
    assert_fields(
        recognized,
        recognition_status="RECOGNIZED",
        recognition_effective_date="2026-07-01",
        decertified_unit_count=0,
    )
    assert provisional["recognition_status"] == "PROVISIONAL"
    admin = make_state_program_admin_headers()

    grant = api.set_recognition(
        recognized["id"],
        f.recognition_payload("GRANT", "2026-08-01", "grant on an already recognized home"),
        admin,
    )
    validate_error(grant, ERR_HOME_RECOGNITION_STATE_INVALID, 409)

    restore = api.set_recognition(
        recognized["id"],
        f.recognition_payload("RESTORE", "2026-08-01", "restore on a recognized home"),
        admin,
    )
    validate_error(restore, ERR_HOME_RECOGNITION_STATE_INVALID, 409)

    suspend = api.set_recognition(
        provisional["id"],
        f.recognition_payload("SUSPEND", "2026-08-01", "suspend on a provisional home"),
        admin,
    )
    validate_error(suspend, ERR_HOME_RECOGNITION_STATE_INVALID, 409)

    untouched = fx.read_home(api, recognized["id"])
    assert_fields(
        untouched, recognition_status="RECOGNIZED", recognition_effective_date="2026-07-01"
    )


def test_each_recognition_action_moves_the_home_from_its_one_legal_standing(api):
    """Grant, suspend and restore each fire from the one standing that admits them.

    Per the PRD: "The `GRANT` action moves a home from `PROVISIONAL` to
    `RECOGNIZED` and is permitted only while `decertified_unit_count` is 0; the
    `SUSPEND` action moves a home from `RECOGNIZED` to `SUSPENDED`; the `RESTORE`
    action moves a home from `SUSPENDED` back to `RECOGNIZED` and, like `GRANT`,
    requires `decertified_unit_count` to be 0." Per the PRD: "A `SUSPEND` sets
    `recognition_suspended_reason` to `UNIT_DECERTIFIED`; a `GRANT` or a `RESTORE`
    sets it back to null." A second suspend on the now-suspended home no longer
    matches its standing and is refused, while the restore that follows carries the
    supplied effective date onto the home.

    Design: Corner/errors/err_home_recognition_state_invalid_for_mismatched_action
    """
    recognized, provisional = _two_homes_of_different_standing(api)
    # Every effective_date this test supplies must already have passed on the
    # logical clock: "an `effective_date` ... that lies in the future relative to
    # the current logical clock is rejected with `ERR_DATE_OUT_OF_RANGE`".
    fx.set_clock(api, "2026-08-04T00:00:00Z")
    admin = make_state_program_admin_headers()

    granted = validate_success(
        api.set_recognition(
            provisional["id"],
            f.recognition_payload("GRANT", "2026-08-01", "federal recognition granted"),
            admin,
        ),
        200,
    )
    assert_fields(
        granted,
        recognition_status="RECOGNIZED",
        recognition_effective_date="2026-08-01",
        recognition_suspended_reason=None,
    )

    suspended = validate_success(
        api.set_recognition(
            recognized["id"],
            f.recognition_payload("SUSPEND", "2026-08-02", "state-initiated suspension"),
            admin,
        ),
        200,
    )
    assert_fields(
        suspended,
        recognition_status="SUSPENDED",
        recognition_suspended_reason="UNIT_DECERTIFIED",
    )

    again = api.set_recognition(
        recognized["id"], f.recognition_payload("SUSPEND", "2026-08-03", "suspend twice"), admin
    )
    validate_error(again, ERR_HOME_RECOGNITION_STATE_INVALID, 409)

    restored = validate_success(
        api.set_recognition(
            recognized["id"],
            f.recognition_payload("RESTORE", "2026-08-04", "restored after review"),
            admin,
        ),
        200,
    )
    assert_fields(
        restored,
        recognition_status="RECOGNIZED",
        recognition_effective_date="2026-08-04",
        recognition_suspended_reason=None,
    )


# ---------------------------------------------------------------------------
# The waitlist entry must sit on the decided unit
# ---------------------------------------------------------------------------
def test_admission_decision_requires_a_waitlist_entry_on_the_decided_unit(api):
    """An applicant queued only on Nursing A cannot be admitted to Nursing B.

    Per the PRD: "Before either branch runs, the decision passes a long gate
    sequence in the ladder order of §2.11: the applicant must be `WAITLISTED`;
    `expected_care_unit_version` must equal the target unit's current `version`,
    else `ERR_CARE_UNIT_VERSION_STALE`; the cited assessment must belong to this
    applicant and be `SUBMITTED`, else `ERR_ASSESSMENT_STATE_INVALID`; the acting
    `X-User-ID` must differ from that assessment's `assessor_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`; the target unit's `certification_status` must be
    exactly `CERTIFIED`, else `ERR_UNIT_NOT_CERTIFIED`; the target unit's
    `operational_posture` must be `OPEN`, else `ERR_UNIT_POSTURE_BLOCKED`; the
    cited assessment's `assessed_care_level` must equal the target unit's
    `care_level`, else `ERR_CARE_LEVEL_MISMATCH`; the applicant must hold an entry
    on that very unit whose status is `ACTIVE` or `OFFERED`, else
    `ERR_NO_WAITLIST_ENTRY_FOR_UNIT` (HTTP 409); and the unit must have at least
    one free bed in `available_bed_count`, else `ERR_NO_AVAILABLE_BED` (HTTP 409)."
    Nursing B is certified, open, level-matched and has both beds free, so the
    entry-to-unit alignment is the only gate the decision can trip.

    Design: Corner/errors/err_no_waitlist_entry_for_unit_on_admission_decision
    """
    setup = _queued_on_the_first_of_two_nursing_units(api)

    unit_b = fx.read_unit(api, setup["unit_b_id"])
    assert_bed_counts(unit_b, occupied=0, held=0, available=2, posture="OPEN")

    response = _decision_response(
        api,
        setup["applicant_id"],
        setup["unit_b_id"],
        setup["assessment_id"],
        make_admissions_coordinator_headers("coordinator-1"),
    )
    validate_error(response, ERR_NO_WAITLIST_ENTRY_FOR_UNIT, 409)

    assert fx.read_applicant(api, setup["applicant_id"])["status"] == "WAITLISTED"
    assert_bed_counts(fx.read_unit(api, setup["unit_b_id"]), occupied=0, available=2)


def test_the_same_decision_succeeds_once_the_entry_on_that_unit_exists(api):
    """Adding the Nursing B entry makes the identical decision succeed and cancels the Nursing A entry.

    Per the PRD: "First, the applicant's entry on the admitting unit moves to
    `ADMITTED` with `queue_position` 0 and that unit's `waitlist_active_count`
    decremented by 1, while every *other* entry of this applicant on other units
    whose status was `ACTIVE` or `OFFERED` moves to `CANCELLED` with
    `offer_expires_at` cleared, `queue_position` 0, each of those units'
    `waitlist_active_count` decremented by 1 and each of those units' `version`
    incremented." The error was therefore about which unit the entry sat on, not
    about the applicant's standing in the queue.

    Design: Corner/errors/err_no_waitlist_entry_for_unit_on_admission_decision
    """
    setup = _queued_on_the_first_of_two_nursing_units(api)
    coordinator = make_admissions_coordinator_headers("coordinator-1")

    refused = _decision_response(
        api, setup["applicant_id"], setup["unit_b_id"], setup["assessment_id"], coordinator
    )
    validate_error(refused, ERR_NO_WAITLIST_ENTRY_FOR_UNIT, 409)

    entry_b = fx.create_waitlist_entry(api, setup["applicant_id"], setup["unit_b_id"])
    assert entry_b["status"] == "ACTIVE"

    resident = validate_success(
        _decision_response(
            api, setup["applicant_id"], setup["unit_b_id"], setup["assessment_id"], coordinator
        ),
        201,
    )
    assert_fields(
        resident,
        care_unit_id=setup["unit_b_id"],
        current_care_level="NURSING",
        occupancy_status="ADMITTED",
    )

    a_rows, a_meta = validate_paginated(
        api.list_unit_waitlist_entries(setup["unit_a_id"], coordinator, {"limit": 10})
    )
    assert a_meta["total_count"] == 1
    assert_fields(a_rows[0], status="CANCELLED", queue_position=0)

    b_rows, b_meta = validate_paginated(
        api.list_unit_waitlist_entries(setup["unit_b_id"], coordinator, {"limit": 10})
    )
    assert b_meta["total_count"] == 1
    assert_fields(b_rows[0], status="ADMITTED", queue_position=0)

    admitting_unit = fx.read_unit(api, setup["unit_b_id"])
    assert_bed_counts(admitting_unit, occupied=1, held=0, available=1)
    assert admitting_unit["waitlist_active_count"] == 0

    source_unit = fx.read_unit(api, setup["unit_a_id"])
    assert_bed_counts(source_unit, occupied=0, held=0, available=2)
    assert source_unit["waitlist_active_count"] == 0
