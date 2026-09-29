"""Authentication, role authorization, identity binding and the validation ladder."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_audiologist_headers,
    make_ei_coordinator_headers,
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_headers,
    make_navigator_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000aa"


def test_the_role_check_fires_before_the_body_is_validated(client):
    """A forbidden role is answered before the missing field is ever noticed.

    PRD: "When a single request violates several rules at once, the response is
    decidable: checks are evaluated strictly in the order below, and the **first**
    failing check determines the error and status code."

    Design: Corner/validations/forbidden_role_outranks_a_missing_required_field
    """
    response = client.create_facility(
        {"name": "Rogue Facility", "facility_type": "BIRTH_HOSPITAL"}, headers=AUDITOR
    )
    check.assert_error_envelope(response, errors.ERR_FORBIDDEN_ROLE)
    assert response.status_code == 403


def test_pagination_is_screened_before_the_path_id_is_resolved(client):
    """Two wrongs on one read, and the earlier check names the error.

    PRD: "4. Pagination bounds on every list endpoint, else `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/invalid_pagination_outranks_the_unknown_parent_facility
    """
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")

    both_wrong = client.list_facility_providers(UNKNOWN_ID, headers=ADMIN, limit=0, offset=0)
    check.assert_error_envelope(both_wrong, errors.ERR_INVALID_PAGINATION)
    assert both_wrong.status_code == 400

    only_path_wrong = client.list_facility_providers(
        UNKNOWN_ID, headers=ADMIN, limit=10, offset=0
    )
    check.assert_error_envelope(only_path_wrong, errors.ERR_FACILITY_NOT_FOUND)
    assert only_path_wrong.status_code == 404

    only_page_wrong = client.list_facility_providers(
        clinic["id"], headers=ADMIN, limit=10, offset=-1
    )
    check.assert_error_envelope(only_page_wrong, errors.ERR_INVALID_PAGINATION)


def test_each_collection_answers_an_unknown_id_with_its_own_code(client):
    """Nine reads of the same absent id yield nine collection-specific 404s.

    PRD: "The first unresolvable segment determines the code:
    `ERR_FACILITY_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_INFANT_NOT_FOUND`,
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, or
    `ERR_REPORT_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_unknown_id_returns_its_own_entity_specific_not_found
    """
    reads = [
        (client.get_provider, errors.ERR_PROVIDER_NOT_FOUND),
        (client.get_encounter, errors.ERR_ENCOUNTER_NOT_FOUND),
        (client.get_slot, errors.ERR_SLOT_NOT_FOUND),
        (client.get_appointment, errors.ERR_APPOINTMENT_NOT_FOUND),
        (client.get_evaluation, errors.ERR_EVALUATION_NOT_FOUND),
        (client.get_referral, errors.ERR_REFERRAL_NOT_FOUND),
        (client.get_task, errors.ERR_TASK_NOT_FOUND),
        (client.get_period, errors.ERR_PERIOD_NOT_FOUND),
        (client.get_report, errors.ERR_REPORT_NOT_FOUND),
    ]
    for read, expected_error in reads:
        response = read(UNKNOWN_ID, headers=ADMIN)
        data = check.assert_error_envelope(response, expected_error)
        assert response.status_code == 404
        assert data["message"]
        envelope = response.json()
        assert envelope["meta"]["api_request_id"]
        assert envelope["meta"]["api_request_timestamp"]


def test_a_missing_or_unrecognised_role_is_unauthenticated(client):
    """Authentication is settled before the body or the path is looked at.

    PRD: "1. Header authentication — `X-User-ID` and `X-User-Role` present and the
    role recognized, else `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/absent_or_unknown_role_header_returns_unauthenticated_before_shape_checks
    """
    headerless = client.create_facility({}, headers={"X-User-ID": "admin-1"})
    check.assert_error_envelope(headerless, errors.ERR_UNAUTHENTICATED)
    assert headerless.status_code == 401

    unknown_role = client.get_facility(
        UNKNOWN_ID, headers=make_headers("admin-1", "RegionalDirector")
    )
    check.assert_error_envelope(unknown_role, errors.ERR_UNAUTHENTICATED)
    assert unknown_role.status_code == 401

    authenticated = client.get_facility(UNKNOWN_ID, headers=ADMIN)
    check.assert_error_envelope(authenticated, errors.ERR_FACILITY_NOT_FOUND)


def test_a_facility_admin_may_only_file_its_own_report(client):
    """The identity binding is checked even when role and version are both right.

    PRD: "When `X-User-Role` is `FacilityAdmin`, `X-User-ID` is the `id` of the
    acting `Facility`; ownership checks on any resource that references a `Facility`
    compare the resource's facility identifier field to `X-User-ID`."

    Design: Corner/errors/facility_admin_cannot_file_a_report_for_another_facility
    """
    first = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    second = fixtures.create_facility(client, "BH2", "BIRTH_HOSPITAL", "R1")
    period = fixtures.open_period(
        client, CLOCK_START, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    fixtures.set_clock(client, "2026-08-15T00:00:00Z")
    payload = factories.report_payload(
        facility_id=first["id"],
        reporting_period_id=period["id"],
        attested_screened_count=0,
        attested_refer_count=0,
        expected_facility_version=first["version"],
    )

    intruder = client.create_report(payload, headers=make_facility_admin_headers(second["id"]))
    check.assert_error_envelope(intruder, errors.ERR_IDENTITY_MISMATCH)
    assert intruder.status_code == 403
    check.assert_total_count(
        client.list_reports(headers=AUDITOR, facility_id=first["id"]), 0
    )

    own = check.assert_created(
        client.create_report(payload, headers=make_facility_admin_headers(first["id"]))
    )
    assert own["status"] == "SUBMITTED"
    assert own["facility_id"] == first["id"]
    assert own["auto_generated"] is False
    check.assert_instant_equals(own["submitted_at"], "2026-08-15T00:00:00Z")
    assert own["submitted_late"] is False


def test_the_threshold_rule_and_the_second_reader_rule_both_bind(client, registry):
    """A declared outcome must match the thresholds, and the performer may not attest.

    PRD: "the acting `X-User-ID` must resolve to a provider whose `provider_type` is
    `AUDIOLOGIST` with `credential_status` `ACTIVE` and must not equal the
    evaluation's `performed_by_provider_id` — an audiologist may not attest their own
    work, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/outcome_must_agree_with_thresholds_and_the_attester_must_be_a_second_audiologist
    """
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-SD",
        guardian_contact_phone="5555601",
    )
    track = fixtures.diagnostic_track(client, registry, infant["id"], clock.at(hours=4))
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], track["episode"]["id"], clock.at(hours=5)
    )

    mismatched = client.submit_evaluation(
        evaluation["id"],
        factories.submit_payload(30, 10, "BILATERAL_LOSS"),
        headers=registry.a1,
    )
    check.assert_error_envelope(mismatched, errors.ERR_OUTCOME_THRESHOLD_MISMATCH)
    still_draft = fixtures.read_evaluation(client, evaluation["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["left_ear_threshold_db"] is None

    submitted = fixtures.submit_evaluation(
        client, registry, evaluation["id"], 30, 10, "UNILATERAL_LOSS"
    )
    assert submitted["status"] == "PENDING_ATTESTATION"
    assert submitted["left_ear_threshold_db"] == 30
    assert submitted["right_ear_threshold_db"] == 10
    assert submitted["outcome"] == "UNILATERAL_LOSS"

    self_attested = client.attest_evaluation(
        evaluation["id"], {"decision": "ACCEPT"}, headers=registry.a1
    )
    check.assert_error_envelope(self_attested, errors.ERR_SEGREGATION_OF_DUTIES)
    unattested = fixtures.read_evaluation(client, evaluation["id"])
    assert unattested["status"] == "PENDING_ATTESTATION"
    assert unattested["attested_by_provider_id"] is None

    attested = fixtures.attest_evaluation(
        client, registry, evaluation["id"], "ACCEPT", note="thresholds reviewed"
    )
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_provider_id"] == registry.a2_id
    assert attested["attestation_note"] == "thresholds reviewed"


def test_a_named_provider_must_be_credentialed_and_of_the_fitting_type(client, registry):
    """Credential standing is judged first, then the provider's type.

    PRD: "20. through 25. Referential fitness — provider credential standing
    (`ERR_PROVIDER_NOT_CREDENTIALED`), provider type fitness
    (`ERR_PROVIDER_TYPE_MISMATCH`), slot type fitness (`ERR_SLOT_TYPE_MISMATCH`),
    cross-reference linkage integrity (`ERR_LINKAGE_MISMATCH`), the diagnostic-track
    requirement on the infant (`ERR_INFANT_NOT_REFERRED`), and facility type fitness
    (`ERR_FACILITY_TYPE_MISMATCH`) — in that relative order."

    Design: Corner/errors/referenced_providers_must_be_credentialed_and_of_the_fitting_type
    """
    lapsed = fixtures.create_provider(
        client, registry.ac_id, "AUDIOLOGIST", "AL", "R1", credential_status="LAPSED"
    )
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-PF",
        guardian_contact_phone="5555701",
    )
    track = fixtures.diagnostic_track(client, registry, infant["id"], clock.at(hours=4))

    def _open_with(performer_id):
        return client.create_evaluation(
            factories.evaluation_payload(
                infant_id=infant["id"],
                episode_id=track["episode"]["id"],
                facility_id=registry.ac_id,
                performed_by_provider_id=performer_id,
                evaluation_datetime=clock.at(hours=5, minutes=30),
                method="ASSR",
            ),
            headers=ADMIN,
        )

    not_credentialed = _open_with(lapsed["id"])
    check.assert_error_envelope(not_credentialed, errors.ERR_PROVIDER_NOT_CREDENTIALED)
    check.assert_total_count(
        client.list_evaluations(headers=ADMIN, infant_id=infant["id"]), 0
    )

    wrong_type = _open_with(registry.s1_id)
    check.assert_error_envelope(wrong_type, errors.ERR_PROVIDER_TYPE_MISMATCH)

    opened = check.assert_created(_open_with(registry.a1_id))
    assert opened["status"] == "DRAFT"
    assert opened["performed_by_provider_id"] == registry.a1_id
    check.assert_total_count(
        client.list_evaluations(headers=ADMIN, infant_id=infant["id"]), 1
    )


def test_every_exclusive_operation_is_refused_to_the_wrong_role(client):
    """Nine exclusive operations, nine role refusals, and never a 404 instead.

    PRD: "2. Role authorization — the acting role appears among the endpoint's
    authorized roles in §4, else `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/each_roles_exclusive_operations_are_forbidden_to_the_other_roles
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    program = fixtures.create_facility(client, "EI1", "EI_PROGRAM", "R1")
    coordinator = fixtures.create_provider(
        client, program["id"], "EI_COORDINATOR", "C1", "R1"
    )
    hospital_admin = make_facility_admin_headers(hospital["id"])

    refusals = [
        client.create_facility(
            factories.facility_payload(name="BH-X"), headers=AUDITOR
        ),
        client.create_period(
            factories.period_payload(
                period_start=CLOCK_START,
                period_end="2026-09-01T00:00:00Z",
                submission_due_datetime="2026-09-05T00:00:00Z",
            ),
            headers=hospital_admin,
        ),
        client.close_period(UNKNOWN_ID, {}, headers=AUDITOR),
        client.review_report(UNKNOWN_ID, {"decision": "ACCEPT"}, headers=ADMIN),
        client.create_report(
            factories.report_payload(
                facility_id=hospital["id"],
                reporting_period_id=UNKNOWN_ID,
                attested_screened_count=0,
                attested_refer_count=0,
                expected_facility_version=hospital["version"],
            ),
            headers=ADMIN,
        ),
        client.submit_evaluation(
            UNKNOWN_ID, factories.submit_payload(10, 10, "NO_LOSS"), headers=hospital_admin
        ),
        client.enroll_referral(
            UNKNOWN_ID,
            {"ifsp_date": CLOCK_START},
            headers=make_navigator_headers(navigator["id"]),
        ),
        client.waive_report_penalty(
            UNKNOWN_ID, {"waiver_reason": "auditor overreach"}, headers=AUDITOR
        ),
        client.assign_referral_program(
            UNKNOWN_ID,
            {"ei_program_facility_id": program["id"]},
            headers=make_ei_coordinator_headers(coordinator["id"]),
        ),
    ]
    for response in refusals:
        check.assert_error_envelope(response, errors.ERR_FORBIDDEN_ROLE)
        assert response.status_code == 403


def test_registration_is_shared_by_three_roles_while_the_read_is_open_to_all(client):
    """Three roles may register a newborn; all seven may read the row back.

    PRD: "A `FacilityScreener` is a birth-facility screening technician who records
    physiologic screens and registers newborns."

    Design: Corner/rbac/infant_registration_is_shared_by_three_roles_while_reads_are_open_to_all_seven
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    program = fixtures.create_facility(client, "EI1", "EI_PROGRAM", "R1")
    coordinator = fixtures.create_provider(
        client, program["id"], "EI_COORDINATOR", "C1", "R1"
    )
    fixtures.set_clock(client, clock.at(hours=6))

    def _register(headers, suffix):
        return client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=CLOCK_START,
                birth_setting="INPATIENT",
                gestational_age_weeks=39,
                guardian_name="G-R{0}".format(suffix),
                guardian_contact_phone="555640{0}".format(suffix),
            ),
            headers=headers,
        )

    first = check.assert_created(_register(ADMIN, 1))
    check.assert_created(_register(make_facility_admin_headers(hospital["id"]), 2))
    check.assert_created(_register(make_facility_screener_headers(screener["id"]), 3))
    check.assert_total_count(
        client.list_infants(headers=ADMIN, birth_facility_id=hospital["id"]), 3
    )

    refused = _register(make_audiologist_headers(audiologist["id"]), 4)
    check.assert_error_envelope(refused, errors.ERR_FORBIDDEN_ROLE)
    check.assert_total_count(
        client.list_infants(headers=ADMIN, birth_facility_id=hospital["id"]), 3
    )

    readers = [
        ADMIN,
        AUDITOR,
        make_facility_admin_headers(hospital["id"]),
        make_facility_screener_headers(screener["id"]),
        make_audiologist_headers(audiologist["id"]),
        make_navigator_headers(navigator["id"]),
        make_ei_coordinator_headers(coordinator["id"]),
    ]
    for headers in readers:
        row = check.assert_ok(client.get_infant(first["id"], headers=headers))
        assert row["id"] == first["id"]
        assert row["screening_status"] == "NOT_SCREENED"
        check.assert_risk(row, 0, "LOW")
