"""Death-certificate lifecycle: signing gates, cascades, segregation, OCC, void branch."""
from test_helpers import (
    validate_success, validate_error,
    create_investigator, create_pathologist, create_cooler,
    set_clock, create_investigating_case,
    store_body, schedule_autopsy, complete_autopsy,
    draft_certificate,
    make_investigator_headers, make_medical_examiner_headers,
    sign_death_certificate_payload,
    create_death_certificate_payload,
)


def test_sign_cascades_case_certified_then_body_unblocked(api):
    """PRD §3.6: "A successful sign-off sets cert_status to SIGNED, records the
    certifying_me_user_id, and stamps signed_at from the clock. It then cascades: the parent
    case advances INVESTIGATING -> CERTIFIED, and because the case is now certified, the case's
    stored body has its release_blocked cleared so the body becomes releasable."

    Design: Difficulty/transitive_cascade/sign_cert_cascades_case_certified_then_body_unblocked
    """
    inv = create_investigator("Inv G")
    me = create_pathologist("ME G", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    body = store_body(inv, body, cooler)
    cert = draft_certificate(me, case, manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    signed = validate_success(
        api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers),
        200,
    )
    assert signed["cert_status"] == "SIGNED"

    case_after = validate_success(api.get_case(case["id"], me_headers), 200)
    assert case_after["status"] == "CERTIFIED"
    body_after = validate_success(api.get_body(body["id"], me_headers), 200)
    assert body_after["release_blocked"] is False


def test_void_draft_certificate_reaches_void_without_cascade(api):
    """PRD §3.6: "A draft may be discarded outright, moving it DRAFT -> VOID, a terminal state."

    Design: Difficulty/non_linear_state_machine/certificate_branch_draft_to_signed_and_void
    """
    inv = create_investigator("Inv F")
    me = create_pathologist("ME F", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    cert = draft_certificate(me, case, manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    voided = validate_success(api.void_death_certificate(cert["id"], me_headers), 200)
    assert voided["cert_status"] == "VOID"

    case_after = validate_success(api.get_case(case["id"], me_headers), 200)
    assert case_after["status"] == "INVESTIGATING"


def test_sign_requires_autopsy_completed(api):
    """PRD §3.6: "If the case's autopsy_required is true, the case's autopsy exam must be
    COMPLETED, else the sign-off is rejected with ERR_AUTOPSY_INCOMPLETE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cert_sign_requires_autopsy_completed
    """
    inv = create_investigator("Inv M")
    path = create_pathologist("Path M", is_medical_examiner=False)
    me = create_pathologist("ME M", is_medical_examiner=True)
    set_clock("2026-05-10T00:00:00Z")
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    # AutopsyExam scheduled but NOT completed.
    schedule_autopsy(path, case, "2026-05-11T00:00:00Z", 60)
    cert = draft_certificate(me, case, cause_of_death="gunshot", manner_of_death="HOMICIDE")

    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    res = api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers)
    validate_error(res, "ERR_AUTOPSY_INCOMPLETE", expected_status=409)


def test_sign_segregation_beats_manner_inconsistent(api):
    """PRD §3.6: "The segregation-of-duties rule of Section 2.11 applies: the acting examiner's
    identity must not equal the case's autopsy pathologist_user_id, else
    ERR_SEGREGATION_VIOLATION." PRD §2.12: "Where a segregation-of-duties rule and a state
    check both apply to the same sign-off or approval, the segregation violation is the
    higher-priority business-safety guard."

    Design: Difficulty/priority_pair_validation_conflict/sign_segregation_beats_manner_inconsistent
    """
    inv = create_investigator("Inv I")
    me = create_pathologist("ME I", is_medical_examiner=True)
    set_clock("2026-05-10T00:00:00Z")
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    # The ME both performs the autopsy AND drafts a manner-inconsistent cert.
    exam = schedule_autopsy(me, case, "2026-05-10T00:00:00Z", 60)
    complete_autopsy(me, exam, "gsw", "gunshot")
    cert = draft_certificate(me, case, cause_of_death="gunshot", manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    res = api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers)
    validate_error(res, "ERR_SEGREGATION_VIOLATION", expected_status=403)


def test_sign_manner_inconsistent_alone_returns_422(api):
    """PRD §3.6: "The asserted manner_of_death must be consistent with the case's case_type
    lane: a HOMICIDE case may not be certified with a NATURAL manner, a NATURAL case may not
    be certified with a HOMICIDE manner, and any inconsistent pairing is rejected with
    ERR_MANNER_INCONSISTENT (HTTP 422); a manner of UNDETERMINED is always permitted regardless
    of lane."

    Design: Corner/validations/manner_inconsistent_alone_returns_422
    """
    inv = create_investigator("Inv CV3")
    path = create_pathologist("Path CV3", is_medical_examiner=False)
    me = create_pathologist("ME CV3", is_medical_examiner=True)
    set_clock("2026-05-10T00:00:00Z")
    case, body = create_investigating_case(inv, case_type="HOMICIDE")
    # Distinct pathologist completes autopsy; a separate ME drafts manner NATURAL.
    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 60)
    complete_autopsy(path, exam, "gsw", "gunshot")
    cert = draft_certificate(me, case, cause_of_death="gunshot", manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    res = api.sign_death_certificate(cert["id"], sign_death_certificate_payload(case_v), me_headers)
    validate_error(res, "ERR_MANNER_INCONSISTENT", expected_status=422)


def test_non_me_pathologist_cannot_sign_certificate(api):
    """PRD §3.6: "The acting user must be a pathologist whose is_medical_examiner flag is true."
    PRD §2.1: "For any role backed by an entity, if X-User-ID does not resolve to an existing
    record of that role's entity type, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP
    403)."

    Design: Corner/rbac/non_me_pathologist_cannot_sign_certificate
    """
    inv = create_investigator("Inv CR3")
    me = create_pathologist("ME CR3", is_medical_examiner=True)
    nonme = create_pathologist("Path CR3", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    cert = draft_certificate(me, case, manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    case_v = validate_success(api.get_case(case["id"], me_headers), 200)["version"]
    # A non-ME pathologist acting as MedicalExaminer.
    nonme_headers = make_medical_examiner_headers(nonme["id"])
    res = api.sign_death_certificate(
        cert["id"], sign_death_certificate_payload(case_v), nonme_headers
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_sign_stale_case_version_rejected(api):
    """PRD §2.5: "When a medical examiner signs a death certificate, the request must carry
    expected_case_version matching the current version of the certificate's parent case. If
    the case's version has advanced since the examiner last read it ... the examiner's view of
    readiness is stale and the sign-off is rejected with ERR_STALE_VERSION (HTTP 412) before
    any state change occurs." PRD §3.3: "Intaking the first body is the event that advances the
    case ACCEPTED -> INVESTIGATING, and both the new body and the parent case's version
    increment as a result."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_sign
    """
    inv = create_investigator("Inv CX2")
    me = create_pathologist("ME CX2", is_medical_examiner=True)
    inv_headers = make_investigator_headers(inv["id"])

    from test_helpers import (
        create_reported_case, triage_payload, create_body_payload,
    )
    case = create_reported_case(inv, decedent_name="Doe CX2")
    accepted = validate_success(
        api.triage_case(case["id"], triage_payload("NATURAL"), inv_headers), 200
    )
    stale_case_version = accepted["version"]  # observed at ACCEPTED

    # First body cascades case -> INVESTIGATING and bumps its version.
    validate_success(
        api.create_body(case["id"], create_body_payload(tag_no="CX-T2"), inv_headers), 201
    )
    cert = draft_certificate(me, accepted, manner_of_death="NATURAL")

    me_headers = make_medical_examiner_headers(me["id"])
    res = api.sign_death_certificate(
        cert["id"], sign_death_certificate_payload(stale_case_version), me_headers
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
