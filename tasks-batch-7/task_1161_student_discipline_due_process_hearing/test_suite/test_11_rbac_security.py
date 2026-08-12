"""RBAC and identity rules: role exclusivity, guardian/officer ownership, and
segregation of duties."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_student_payload, create_case_payload, create_classify_payload,
    create_appeal_decision_payload, create_evidence_payload,
    create_evidence_ruling_payload, create_hearing_decision_payload,
    create_appeal_payload,
    set_clock, create_offense_code, create_offense_code_with_bands,
    create_student, create_case, create_classified_case, refer_expulsion,
    setup_notice_issued_case, setup_appeal_filed_case,
    setup_expulsion_referred_case, create_hearing, submit_evidence,
    rule_evidence, serve_packet, setup_hearing_held, get_case,
    make_school_admin_headers, make_parent_guardian_headers,
    make_hearing_officer_headers, make_student_services_headers,
    make_district_admin_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
CLS = TEST_USERS["school_classifier_headers"]
REF = TEST_USERS["school_referrer_headers"]
SSD = TEST_USERS["student_services_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their
    operational capacity. A request missing either header, or presenting a
    role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_student(
        create_student_payload(full_name="No Headers", guardian_id="gnh"),
        headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_guardian_cannot_create_case_unauthorized(api):
    """PRD §2.1: "Access to each operation is restricted to the roles listed
    for it in §4; an authenticated user attempting an operation outside their
    role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." §4 lists incident
    referral under SchoolAdministrator only.
    PRD §2.1: "`ParentGuardian` — parent or guardian of a student: files
    appeals and expungement requests and reads their own student's records."

    Design: Corner/rbac/guardian_cannot_create_case_unauthorized
    """
    student = create_student(full_name="Stu RB", guardian_id="gq1")
    res = api.create_case(
        create_case_payload(student["id"], "2026-05-04T08:00:00Z",
                            description="guardian attempt"),
        make_parent_guardian_headers("gq1"))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_admin_cannot_decide_appeal_unauthorized(api):
    """PRD §2.1: "Access to each operation is restricted to the roles listed
    for it in §4; an authenticated user attempting an operation outside their
    role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." §4 lists appeal
    decisions under DistrictAdmin only.
    PRD §3.4: "A `DistrictAdmin` decides the appeal".

    Design: Corner/rbac/admin_cannot_decide_appeal_unauthorized
    """
    bundle = setup_appeal_filed_case(
        guardian_id="gq2", full_name="Stu RB2", clock="2026-05-04T09:00:00Z",
        appeal_clock="2026-05-05T09:00:00Z", grounds="g")
    res = api.decide_appeal(
        bundle["appeal"]["id"], create_appeal_decision_payload("UPHELD"), CLS)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    appeals = validate_success(api.list_appeals(bundle["case"]["id"], CLS), 200)
    assert appeals[0]["status"] == "FILED", "the denied decision changes nothing"


def test_admin_cannot_rule_evidence_unauthorized(api):
    """PRD §2.1: "Access to each operation is restricted to the roles listed
    for it in §4; an authenticated user attempting an operation outside their
    role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`HearingOfficer` — independent hearing officer: rules on
    evidence admissibility, convenes hearings, and issues expulsion
    decisions."

    Design: Corner/rbac/admin_cannot_rule_evidence_unauthorized
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="gq3", full_name="Stu RB3")
    hearing = create_hearing(bundle["case"]["id"], "ho_1",
                             "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    evidence = submit_evidence(hearing["id"], "DOCUMENT", "report")

    # The submitting school administrator may not rule on admissibility.
    res = api.rule_evidence(
        evidence["id"], create_evidence_ruling_payload("ADMITTED"), CLS)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    packet = validate_success(api.list_evidence(hearing["id"], CLS), 200)
    assert packet[0]["status"] == "SUBMITTED"


def test_director_cannot_classify_unauthorized(api):
    """PRD §2.1: "Access to each operation is restricted to the roles listed
    for it in §4; an authenticated user attempting an operation outside their
    role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." §4 lists
    classification under SchoolAdministrator only.
    PRD §3.2: "A school administrator classifies a `SUBMITTED` case".

    Design: Corner/rbac/director_cannot_classify_unauthorized
    """
    oc = create_offense_code()
    student = create_student(full_name="Stu RB4", guardian_id="gq4")
    case = create_case(student["id"], "2026-05-04T08:00:00Z")
    res = api.classify_case(
        case["id"], create_classify_payload(oc["id"], case["version"]), SSD)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    settled = get_case(case["id"])
    assert settled["status"] == "SUBMITTED"


def test_guardian_ownership_mismatch_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `ParentGuardian`, the opaque
    identifier is compared against the `guardian_id` stored on the student for
    every guardian-scoped operation — filing an appeal, requesting an
    expungement, or reading a student, case, notice, conference, appeal, or
    expungement record belonging to that student — and a mismatch is rejected
    with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/guardian_ownership_mismatch_forbidden
    """
    bundle = setup_notice_issued_case(
        guardian_id="g_own", full_name="Stu Own", clock="2026-05-04T09:00:00Z")
    set_clock("2026-05-05T09:00:00Z")  # inside the filing window
    res = api.file_appeal(
        bundle["case"]["id"], create_appeal_payload("not my child"),
        make_parent_guardian_headers("g_intruder"))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)


def test_officer_ruling_ownership_mismatch_forbidden(api):
    """PRD §3.5: "a `ruling` of `ADMITTED` or `EXCLUDED` is accepted only
    while the hearing is still `SCHEDULED` and only from the officer whose
    `X-User-ID` equals the hearing's `hearing_officer_id`, any other officer
    drawing `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/officer_ruling_ownership_mismatch_forbidden
    """
    bundle = setup_expulsion_referred_case(
        guardian_id="goo", full_name="Stu OO")
    hearing = create_hearing(bundle["case"]["id"], "ho_1",
                             "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    evidence = submit_evidence(hearing["id"], "DOCUMENT", "report")

    res = api.rule_evidence(
        evidence["id"], create_evidence_ruling_payload("ADMITTED"),
        make_hearing_officer_headers("ho_2"))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)


def test_segregation_referrer_cannot_classify_forbidden(api):
    """PRD §3.2: "the classifier must not be the administrator who referred
    the incident, so a request whose `X-User-ID` equals the case's
    `referrer_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/rbac/segregation_referrer_cannot_classify_forbidden
    """
    oc = create_offense_code()
    student = create_student(full_name="Stu SoD", guardian_id="gsod")
    case = create_case(student["id"], "2026-05-04T08:00:00Z",
                       referrer_id="admin_ref_1")
    # The referrer attempts to classify their own referral.
    res = api.classify_case(
        case["id"], create_classify_payload(oc["id"], case["version"]),
        make_school_admin_headers("admin_ref_1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)


def test_segregation_hearing_officer_is_referrer_forbidden(api):
    """PRD §3.5: "Ownership is enforced once more, and segregation of duties
    bars a decider who served as the case's referrer or classifier
    (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/segregation_hearing_officer_is_referrer_forbidden
    """
    # Hearing assigned to hearing_officer_id "admin_ref_1" — the same person
    # as the case's referrer. Rule and convene pass ownership; the decision
    # fails segregation.
    bundle = setup_expulsion_referred_case(
        guardian_id="gsod2", full_name="Stu SoD2", referrer_id="admin_ref_1")
    held = setup_hearing_held(bundle["case"]["id"], "admin_ref_1",
                              "2026-05-08T10:00:00Z", "2026-05-08T12:00:00Z")
    assert held["hearing"]["status"] == "HELD"

    res = api.decide_hearing(
        held["hearing"]["id"],
        create_hearing_decision_payload("EXPULSION_ORDERED"),
        make_hearing_officer_headers("admin_ref_1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    hearing = validate_success(
        api.get_hearing(held["hearing"]["id"], make_hearing_officer_headers("admin_ref_1")),
        200)
    assert hearing["status"] == "HELD"
    case = get_case(bundle["case"]["id"])
    assert case["status"] == "EXPULSION_REFERRED"
