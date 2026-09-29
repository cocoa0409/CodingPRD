"""Role authorisation, segregation of duties, optimistic concurrency and immediacy.

Covers the per-endpoint role gate and the entity-backed ownership gate of the
board's access-control rules, the two segregation-of-duties bars drawn on the
acting operator identity, the optimistic-concurrency guards on the two parent
records that carry a version field on their child create, and the promise that
every cascaded consequence is already visible in the response that caused it.
"""

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_LICENSING_OFFICER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_REVIEWER_2_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_pdh_value,
    factories,
    fixtures,
    make_applicant_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_TWO_WEEKS_ON = "2026-08-15T00:00:00Z"
CLOCK_TWO_WEEKS_ON_STAMPED = "2026-08-15T00:00:00.000Z"
SUBMITTED_AT_STAMPED = "2026-08-01T00:00:00.000Z"
AUTHORIZATION_EXPIRES_AT = "2027-08-01T00:00:00.000Z"
STANDARD_ONE_BLOCK_FEE_CENTS = 27500
UNLICENSED_PRACTICE_PENALTY_CENTS = 298000


# ---------------------------------------------------------------------------
# Local read helpers: every row is re-read through the public API so that a
# side effect is observed rather than inferred.
# ---------------------------------------------------------------------------
def _read_application(api, application_id):
    return validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_experience_record(api, experience_record_id):
    return validate_success(
        api.get_experience_record(experience_record_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_license(api, license_id):
    return validate_success(
        api.get_license(license_id, BOARD_LICENSING_OFFICER_HEADERS), 200
    )


def _read_cpc_report(api, cpc_report_id):
    return validate_success(
        api.get_cpc_report(cpc_report_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_cpc_audit(api, cpc_audit_id):
    return validate_success(
        api.get_cpc_audit(cpc_audit_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_case(api, case_id):
    return validate_success(api.get_case(case_id, BOARD_INVESTIGATOR_HEADERS), 200)


def _read_consent_order(api, consent_order_id):
    return validate_success(
        api.get_consent_order(consent_order_id, BOARD_INVESTIGATOR_HEADERS), 200
    )


def _submitted_reference_overrides():
    """A referee answer that clears the acceptance bar of an evaluation."""
    return {
        "evaluation_score": 5,
        "months_confirmed": 48,
        "responsibility_confirmed": True,
    }


# ---------------------------------------------------------------------------
# The board secretary's own operations
# ---------------------------------------------------------------------------
def test_board_secretary_registers_an_engineer_on_the_roster(api):
    """PRD §3.1: "A `BoardSecretary` registers an engineer by supplying `full_name` — a non-empty string of at most 120 characters"

    Design: Corner/rbac/board_secretary_performs_its_exclusive_roster_center_and_clock_operations
    """
    response = api.create_engineer(
        {
            "full_name": "Sig Aalto",
            "email": "sig.aalto@pe.test",
            "home_jurisdiction": "OR",
        },
        BOARD_SECRETARY_HEADERS,
    )
    engineer = validate_success(response, 201)

    assert engineer["full_name"] == "Sig Aalto"
    assert engineer["email"] == "sig.aalto@pe.test"
    assert engineer["home_jurisdiction"] == "OR"
    assert engineer["ncees_record_id"] is None
    assert engineer["active_license_number"] is None
    assert engineer["open_case_count"] == 0
    assert engineer["version"] == 1

    stored = validate_success(
        api.get_engineer(engineer["id"], BOARD_SECRETARY_HEADERS), 200
    )
    assert stored["id"] == engineer["id"]
    assert stored["full_name"] == "Sig Aalto"


def test_board_secretary_registers_a_test_centre_with_its_seat_inventory(api):
    """PRD §3.1: "Seating for the discipline examinations lives in a separate inventory that a `BoardSecretary` maintains."

    Design: Corner/rbac/board_secretary_performs_its_exclusive_roster_center_and_clock_operations
    """
    response = api.create_test_center(
        {
            "name": "Corvallis Testing Hall",
            "state_code": "OR",
            "seat_labels": ["S1"],
        },
        BOARD_SECRETARY_HEADERS,
    )
    center = validate_success(response, 201)

    assert center["name"] == "Corvallis Testing Hall"
    assert center["state_code"] == "OR"
    assert center["seat_labels"] == ["S1"]
    assert center["seat_count"] == 1
    assert center["seats_committed"] == 0
    assert center["seats_available"] == 1
    assert center["status"] == "OPEN"
    assert center["version"] == 1


def test_board_secretary_advances_the_logical_board_clock(api):
    """PRD §2.5: "A `BoardSecretary` moves the clock by supplying a `to_iso8601` instant."

    Design: Corner/rbac/board_secretary_performs_its_exclusive_roster_center_and_clock_operations
    """
    response = api.set_current_utc(
        factories.clock_payload(CLOCK_TWO_WEEKS_ON), BOARD_SECRETARY_HEADERS
    )
    summary = validate_success(response, 200)

    assert summary["current_utc"] == CLOCK_TWO_WEEKS_ON_STAMPED
    assert summary["expired_authorization_count"] == 0
    assert summary["expired_license_count"] == 0
    assert summary["expired_firm_count"] == 0
    assert summary["cancelled_appointment_count"] == 0
    assert summary["lapsed_firm_count"] == 0


# ---------------------------------------------------------------------------
# Authorisation is per endpoint, and ownership is per row
# ---------------------------------------------------------------------------
def test_authorisation_is_per_endpoint_not_board_versus_public(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the endpoint being called — the authorisation column of the endpoint table in §4 is the definitive list — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/role_cannot_invoke_another_roles_exclusive_operation
    """
    engineer = fixtures.create_engineer(api, full_name="Fay Orr")
    application = fixtures.create_application(api, engineer["id"])

    applicant_headers = make_applicant_headers(engineer["id"])
    refused_evaluation = api.evaluate_education(
        application["id"],
        factories.education_evaluation_payload(),
        applicant_headers,
    )
    validate_error(refused_evaluation, "ERR_UNAUTHORIZED")

    refused_issuance = api.create_license(
        factories.license_payload(engineer["id"]), BOARD_REVIEWER_HEADERS
    )
    validate_error(refused_issuance, "ERR_UNAUTHORIZED")

    stored = _read_application(api, application["id"])
    assert stored["education_status"] == "NOT_EVALUATED"
    assert stored["degree_level"] is None
    assert stored["version"] == application["version"]

    licenses, meta = validate_paginated(
        api.list_licenses(
            BOARD_LICENSING_OFFICER_HEADERS, {"engineer_id": engineer["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert licenses == []


def test_licensee_cannot_file_a_competency_report_on_a_peers_licence(api):
    """PRD §2.1: "A licensee renewing a licence, filing a competency report or affixing a seal must be the engineer named in the relevant `License`'s `engineer_id`."

    Design: Corner/rbac/licensee_cannot_file_a_cpc_report_against_another_engineers_license
    """
    holder, license_ = fixtures.create_licensed_engineer(api, full_name="Gita Ono")
    peer = fixtures.create_engineer(api, full_name="Hugo Ono")

    payload = factories.cpc_report_payload(
        license_["id"],
        license_["version"],
        period_start=license_["current_period_start"],
        period_end=license_["current_period_end"],
        self_certified_pdh=30,
        carryover_pdh_claimed=0,
    )
    response = api.create_cpc_report(payload, make_licensee_headers(peer["id"]))
    validate_error(response, "ERR_NOT_RESOURCE_OWNER")

    reports, meta = validate_paginated(
        api.list_cpc_reports(BOARD_REVIEWER_HEADERS, {"license_id": license_["id"]})
    )
    assert meta["total_count"] == 0
    assert reports == []

    stored = _read_license(api, license_["id"])
    assert stored["version"] == license_["version"]
    assert stored["engineer_id"] == holder["id"]


# ---------------------------------------------------------------------------
# Segregation of duties on the credit-determination stamp
# ---------------------------------------------------------------------------
def test_approve_exam_refused_for_the_officer_who_determined_the_credit(api):
    """PRD §3.4: "That stamp is the segregation-of-duties bar — the same operator may not later approve the examination or issue the licence on that file, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/approve_exam_blocked_for_the_user_who_determined_credit
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        submission_overrides=_submitted_reference_overrides(),
        credit_headers=BOARD_LICENSING_OFFICER_HEADERS,
    )
    application = track["application"]
    assert application["credit_determined_by_user_id"] == "LIC-1"
    assert application["verified_experience_months"] == 48
    assert application["status"] == "UNDER_REVIEW"

    response = api.approve_exam(application["id"], BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    stored = _read_application(api, application["id"])
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["credit_determined_by_user_id"] == "LIC-1"
    assert stored["version"] == application["version"]

    authorizations, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_LICENSING_OFFICER_HEADERS, {"application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert authorizations == []


def test_approve_exam_succeeds_for_a_second_officer_of_the_same_role(api):
    """PRD §2.11: "Because all five board and integration roles are opaque identities, two different officers holding the same role are distinguishable, and that is exactly the distinction being enforced."

    Design: Corner/rbac/approve_exam_blocked_for_the_user_who_determined_credit
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        submission_overrides=_submitted_reference_overrides(),
        credit_headers=BOARD_LICENSING_OFFICER_HEADERS,
    )
    application = track["application"]

    validate_error(
        api.approve_exam(application["id"], BOARD_LICENSING_OFFICER_HEADERS),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    response = api.approve_exam(application["id"], BOARD_LICENSING_OFFICER_2_HEADERS)
    authorization = validate_success(response, 201)

    assert authorization["status"] == "APPROVED_TO_SIT"
    assert authorization["attempt_number"] == 1
    assert authorization["result"] == "PENDING"
    assert authorization["raw_score"] is None
    assert authorization["retake_eligible_at"] is None
    assert authorization["ncees_transmission_id"] is None
    assert authorization["exam_code"] == "PE_CIVIL"
    assert authorization["authorization_expires_at"] == AUTHORIZATION_EXPIRES_AT
    assert authorization["version"] == 1

    stored = _read_application(api, application["id"])
    assert stored["status"] == "EXAM_APPROVED"
    assert stored["credit_determined_by_user_id"] == "LIC-1"
    assert stored["version"] == application["version"] + 1


# ---------------------------------------------------------------------------
# Segregation of duties on the audit draw
# ---------------------------------------------------------------------------
def _report_under_audit(api):
    """One ACCEPTED competency report drawn into an audit sample by REV-1."""
    setup = fixtures.setup_cleared_cpc_report(api)
    audit = fixtures.draw_audit(
        api,
        headers=BOARD_REVIEWER_HEADERS,
        sample_pct=1.0,
        as_of_period_end=setup["license"]["current_period_end"],
    )
    setup["audit"] = audit
    line_items, _ = validate_paginated(
        api.list_pdh_records(
            BOARD_REVIEWER_HEADERS, {"cpc_report_id": setup["report"]["id"]}
        )
    )
    setup["pdh_records"] = line_items
    return setup


def test_audit_decision_refused_for_the_reviewer_who_drew_the_sample(api):
    """PRD §2.11: "An audit decision on a competency report may not be taken by the operator whose `X-User-ID` was recorded as the deciding audit's `created_by_user_id`."

    Design: Corner/rbac/audit_decision_blocked_for_the_user_who_drew_the_sample
    """
    setup = _report_under_audit(api)
    report_id = setup["report"]["id"]
    audit = setup["audit"]

    assert audit["created_by_user_id"] == "REV-1"
    assert audit["status"] == "SAMPLED"
    assert audit["pool_size"] == 1
    assert audit["sampled_count"] == 1

    drawn = _read_cpc_report(api, report_id)
    assert drawn["status"] == "UNDER_AUDIT"
    assert drawn["audit_id"] == audit["id"]

    response = api.audit_decision(
        report_id, {"decision": "CLEAR"}, BOARD_REVIEWER_HEADERS
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    stored = _read_cpc_report(api, report_id)
    assert stored["status"] == "UNDER_AUDIT"
    assert stored["audit_decided_by_user_id"] is None
    assert stored["version"] == drawn["version"]

    stored_audit = _read_cpc_audit(api, audit["id"])
    assert stored_audit["status"] == "SAMPLED"
    assert stored_audit["created_by_user_id"] == "REV-1"


def test_second_reviewer_clears_the_audited_report_and_closes_the_cycle(api):
    """PRD §3.6: "When the decision leaves no report of that draw still standing in `UNDER_AUDIT`, the draw itself bubbles up `SAMPLED → CLOSED`."

    Design: Corner/rbac/audit_decision_blocked_for_the_user_who_drew_the_sample
    """
    setup = _report_under_audit(api)
    report_id = setup["report"]["id"]
    audit = setup["audit"]

    assert len(setup["pdh_records"]) == 2
    for line_item in setup["pdh_records"]:
        reviewed = fixtures.review_pdh_documentation(
            api, line_item["id"], "ACCEPT", BOARD_REVIEWER_HEADERS
        )
        assert reviewed["documentation_status"] == "ACCEPTED"

    proven = _read_cpc_report(api, report_id)
    assert_pdh_value(proven["audit_verified_total_pdh"], 30.0)
    assert_pdh_value(proven["shortfall_pdh"], 0.0)

    validate_error(
        api.audit_decision(report_id, {"decision": "CLEAR"}, BOARD_REVIEWER_HEADERS),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    response = api.audit_decision(
        report_id, {"decision": "CLEAR"}, BOARD_REVIEWER_2_HEADERS
    )
    decided = validate_success(response, 200)

    assert decided["status"] == "AUDIT_CLEARED"
    assert decided["audit_decided_by_user_id"] == "REV-2"
    assert_pdh_value(decided["audit_verified_total_pdh"], 30.0)
    assert_pdh_value(decided["shortfall_pdh"], 0.0)

    stored_audit = _read_cpc_audit(api, audit["id"])
    assert stored_audit["status"] == "CLOSED"
    assert stored_audit["created_by_user_id"] == "REV-1"
    assert stored_audit["pool_size"] == 1
    assert stored_audit["sampled_count"] == 1

    stored_license = _read_license(api, setup["license"]["id"])
    assert stored_license["discipline_flag"] is False


# ---------------------------------------------------------------------------
# Optimistic concurrency on the licence a competency report names
# ---------------------------------------------------------------------------
def _licence_with_one_submitted_report(api):
    """A licensee whose licence already carries one SUBMITTED report."""
    engineer, license_ = fixtures.create_licensed_engineer(api, full_name="Nils Ravn")
    report = fixtures.create_cpc_report(
        api,
        license_["id"],
        engineer["id"],
        license_["version"],
        period_start=license_["current_period_start"],
        period_end=license_["current_period_end"],
        self_certified_pdh=30,
        carryover_pdh_claimed=0,
    )
    return engineer, license_, report


def test_replacement_competency_report_on_a_stale_licence_version_conflicts(api):
    """PRD §2.6: "If that value does not equal the licence's current `version`, the create is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412), preventing the client from superseding a report it never observed."

    Design: Corner/cross-cutting complexity layers/cpc_report_create_with_stale_license_version_conflicts
    """
    engineer, license_, first = _licence_with_one_submitted_report(api)
    stale_version = license_["version"]

    payload = factories.cpc_report_payload(
        license_["id"],
        stale_version,
        period_start=license_["current_period_start"],
        period_end=license_["current_period_end"],
        self_certified_pdh=32,
        carryover_pdh_claimed=0,
    )
    response = api.create_cpc_report(payload, make_licensee_headers(engineer["id"]))
    validate_error(response, "ERR_STALE_LICENSE_VERSION")

    stored_first = _read_cpc_report(api, first["id"])
    assert stored_first["status"] == "SUBMITTED"
    assert stored_first["supersedes_report_id"] is None

    stored_license = _read_license(api, license_["id"])
    assert stored_license["version"] == stale_version + 1

    reports, meta = validate_paginated(
        api.list_cpc_reports(BOARD_REVIEWER_HEADERS, {"license_id": license_["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in reports] == [first["id"]]


def test_replacement_competency_report_supersedes_once_the_licence_is_re_read(api):
    """PRD §2.6: "On success the licence's `version` is itself incremented by 1, so a client filing two reports in sequence must re-read the licence between them."

    Design: Corner/cross-cutting complexity layers/cpc_report_create_with_stale_license_version_conflicts
    """
    engineer, license_, first = _licence_with_one_submitted_report(api)
    stale_version = license_["version"]
    licensee_headers = make_licensee_headers(engineer["id"])

    validate_error(
        api.create_cpc_report(
            factories.cpc_report_payload(
                license_["id"],
                stale_version,
                period_start=license_["current_period_start"],
                period_end=license_["current_period_end"],
                self_certified_pdh=32,
            ),
            licensee_headers,
        ),
        "ERR_STALE_LICENSE_VERSION",
    )

    observed = validate_success(api.get_license(license_["id"], licensee_headers), 200)
    assert observed["version"] == stale_version + 1

    response = api.create_cpc_report(
        factories.cpc_report_payload(
            license_["id"],
            observed["version"],
            period_start=license_["current_period_start"],
            period_end=license_["current_period_end"],
            self_certified_pdh=32,
            carryover_pdh_claimed=0,
        ),
        licensee_headers,
    )
    second = validate_success(response, 201)

    assert second["status"] == "SUBMITTED"
    assert_pdh_value(second["self_certified_pdh"], 32)
    assert second["supersedes_report_id"] == first["id"]
    assert second["audit_id"] is None
    assert second["audit_decided_by_user_id"] is None

    stored_first = _read_cpc_report(api, first["id"])
    assert stored_first["status"] == "SUPERSEDED"

    stored_license = _read_license(api, license_["id"])
    assert stored_license["version"] == stale_version + 2

    reports, meta = validate_paginated(
        api.list_cpc_reports(BOARD_REVIEWER_HEADERS, {"license_id": license_["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in reports) == sorted([first["id"], second["id"]])


# ---------------------------------------------------------------------------
# Optimistic concurrency on the case a consent order names
# ---------------------------------------------------------------------------
def _case_with_one_proposed_order(api):
    """An unlicensed-practice case at probable cause with one PROPOSED order."""
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="Deschutes County",
        unlicensed_respondent_name="Pim Sorel",
    )
    fixtures.open_investigation(api, case["id"])
    case = fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=0,
        mitigating_factor_count=0,
        violation_count=1,
    )
    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="REPRIMAND",
        penalty_paid_cents=UNLICENSED_PRACTICE_PENALTY_CENTS,
    )
    return case, order


def test_renegotiated_consent_order_on_a_stale_case_version_conflicts(api):
    """PRD §2.6: "If that value does not equal the case's current `version`, the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/consent_order_create_with_stale_case_version_conflicts
    """
    case, first = _case_with_one_proposed_order(api)
    stale_version = case["version"]

    assert case["assessed_penalty_cents"] == UNLICENSED_PRACTICE_PENALTY_CENTS
    assert first["penalty_cents"] == UNLICENSED_PRACTICE_PENALTY_CENTS

    payload = factories.consent_order_payload(
        case["id"],
        stale_version,
        sanction_type="SUSPENSION",
        suspension_months=6,
        penalty_paid_cents=UNLICENSED_PRACTICE_PENALTY_CENTS,
    )
    response = api.create_consent_order(payload, BOARD_INVESTIGATOR_HEADERS)
    validate_error(response, "ERR_STALE_CASE_VERSION")

    stored_first = _read_consent_order(api, first["id"])
    assert stored_first["status"] == "PROPOSED"
    assert stored_first["sanction_type"] == "REPRIMAND"

    stored_case = _read_case(api, case["id"])
    assert stored_case["sanction_status"] == "PROPOSED"
    assert stored_case["version"] == stale_version + 1

    orders, meta = validate_paginated(
        api.list_consent_orders(BOARD_INVESTIGATOR_HEADERS, {"case_id": case["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in orders] == [first["id"]]


def test_renegotiated_consent_order_supersedes_once_the_case_is_re_read(api):
    """PRD §3.9: "A second proposal on the same case is legitimate and is exactly why the concurrency guard exists: the outstanding order moves `PROPOSED → SUPERSEDED`, a replacement order is created in `PROPOSED`, and the sanction axis takes the `PROPOSED → PROPOSED` self-loop."

    Design: Corner/cross-cutting complexity layers/consent_order_create_with_stale_case_version_conflicts
    """
    case, first = _case_with_one_proposed_order(api)
    stale_version = case["version"]

    validate_error(
        api.create_consent_order(
            factories.consent_order_payload(
                case["id"],
                stale_version,
                sanction_type="SUSPENSION",
                suspension_months=6,
                penalty_paid_cents=UNLICENSED_PRACTICE_PENALTY_CENTS,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        "ERR_STALE_CASE_VERSION",
    )

    observed = _read_case(api, case["id"])
    assert observed["version"] == stale_version + 1

    response = api.create_consent_order(
        factories.consent_order_payload(
            case["id"],
            observed["version"],
            sanction_type="SUSPENSION",
            suspension_months=6,
            penalty_paid_cents=UNLICENSED_PRACTICE_PENALTY_CENTS,
        ),
        BOARD_INVESTIGATOR_HEADERS,
    )
    second = validate_success(response, 201)

    assert second["status"] == "PROPOSED"
    assert second["sanction_type"] == "SUSPENSION"
    assert second["suspension_months"] == 6
    assert second["penalty_cents"] == UNLICENSED_PRACTICE_PENALTY_CENTS
    assert second["executed_on"] is None
    assert second["executed_by_user_id"] is None

    stored_first = _read_consent_order(api, first["id"])
    assert stored_first["status"] == "SUPERSEDED"

    stored_case = _read_case(api, case["id"])
    assert stored_case["sanction_status"] == "PROPOSED"
    assert stored_case["investigation_status"] == "PROBABLE_CAUSE"
    assert stored_case["version"] == stale_version + 2

    orders, meta = validate_paginated(
        api.list_consent_orders(BOARD_INVESTIGATOR_HEADERS, {"case_id": case["id"]})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Immediate consistency: the submit cascade is already visible on return
# ---------------------------------------------------------------------------
def test_submit_cascade_is_visible_in_the_same_response_and_on_immediate_reads(api):
    """PRD §2.9: "When a request returns, every cascaded row already reflects its new state, with `version` incremented and `updated_at` refreshed."

    Design: Corner/consistency model/submit_cascade_is_visible_in_the_same_response_and_on_immediate_reads
    """
    track = fixtures.setup_exam_track(api, stop_after="paid")
    applicant_id = track["engineer"]["id"]
    application = track["application"]
    record = track["experience_record"]
    reference = track["reference"]
    applicant_headers = make_applicant_headers(applicant_id)

    assert application["status"] == "DRAFT"
    assert application["submitted_at"] is None
    # PRD §3.3: provisional_experience_months is written "when a block is added",
    # so the DRAFT file already carries the self-reported figure for its one block.
    assert application["provisional_experience_months"] == 48
    assert application["verified_experience_months"] == 0
    assert record["verification_status"] == "UNVERIFIED"

    submitted = validate_success(
        api.submit_application(application["id"], applicant_headers), 200
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] == SUBMITTED_AT_STAMPED
    assert submitted["fee_assessment_cents"] == STANDARD_ONE_BLOCK_FEE_CENTS
    assert submitted["fee_paid_cents"] == STANDARD_ONE_BLOCK_FEE_CENTS
    assert submitted["provisional_experience_months"] == 48
    assert submitted["verified_experience_months"] == 0
    assert submitted["version"] == application["version"] + 1

    stored_record = _read_experience_record(api, record["id"])
    assert stored_record["verification_status"] == "PENDING_VERIFICATION"
    assert stored_record["raw_months"] == 48
    assert round(float(stored_record["credit_multiplier"]), 2) == 1.0
    assert stored_record["credited_months"] == 0
    assert stored_record["version"] == record["version"] + 1

    stored_application = _read_application(api, application["id"])
    assert stored_application["status"] == "SUBMITTED"
    assert stored_application["submitted_at"] == SUBMITTED_AT_STAMPED
    assert stored_application["provisional_experience_months"] == 48
    assert stored_application["fee_assessment_cents"] == STANDARD_ONE_BLOCK_FEE_CENTS

    stored_reference = validate_success(
        api.get_reference(reference["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert stored_reference["status"] == "REQUESTED"
    assert stored_reference["submitted_at"] is None
