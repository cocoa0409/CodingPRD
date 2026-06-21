"""Completion: the complete cascade (slot release + certificate), certificate
immutability, segregation-of-duties RBAC, and the completion-requirement guard.

Covers transitive_cascade (complete depth-2), the certificate-immutability and
completion-requirement corners, and the segregation-of-duties RBAC corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_certificate,
    create_sponsor,
    create_qualified_journeyworker,
    create_apprentice,
    create_active_program,
    create_active_agreement,
    setup_active_agreement,
    setup_completion_ready_agreement,
    setup_completed_agreement_with_certificate,
    complete_agreement,
    log_ojt_entry,
    log_and_approve_ojt,
    record_rti,
    AGENCY,
    COORD,
)
from test_helpers.test_users import (
    make_sponsor_headers,
    make_apprentice_headers,
)


# ===========================================================================
# Difficulty: transitive_cascade / agreement_complete_cascade_certificate_and_slot_release_depth2
# ===========================================================================
def test_complete_releases_slot_and_decrements_journeyworker(api):
    """PRD §3.7: "On completion the agreement's status becomes `COMPLETED`, its
    `end_date` is set to the issuance date, the program's `active_agreement_count`
    decreases by one, the supervising journeyworker's `active_apprentice_count`
    decreases by one, and the program's `available_apprentice_slots` is recomputed."

    Completing the only agreement (ratio 4, one QUALIFIED journeyworker) drives
    journeyworker.active_apprentice_count 1->0, which recomputes the program's
    available_apprentice_slots back up to 4.

    Design: Difficulty/transitive_cascade/agreement_complete_cascade_certificate_and_slot_release_depth2
    """
    sc = setup_completion_ready_agreement()  # ratio 4 default, HOURS_BASED, met
    headers = make_sponsor_headers(sc.sponsor_id)
    completed = complete_agreement(sc.agreement_id)
    assert completed["status"] == "COMPLETED"

    jw = get_success_data(api.get_journeyworker(sc.journeyworker_id, headers))
    assert jw["active_apprentice_count"] == 0
    prog = get_success_data(api.get_program(sc.program_id, headers))
    assert prog["available_apprentice_slots"] == 4
    assert prog["active_agreement_count"] == 0


def test_complete_cascade_creates_certificate(api):
    """PRD §3.7: "As a cascade, a `CompletionCertificate` is created exactly once
    for the agreement, snapshotting the moment of certification: it captures the
    certified agreement via `agreement_id`, the `program_id`, the program's
    `occupation_code` at issuance, the agreement's then-current on-the-job total
    as `certified_ojt_hours` and instruction total as `certified_rti_hours`, and
    the `issued_by_user_id` recording the `X-User-ID` of the issuing
    `RegistrationAgency` operator."

    Completion creates exactly one certificate naming the agreement and
    snapshotting the certified OJT hours.

    Design: Difficulty/transitive_cascade/agreement_complete_cascade_certificate_and_slot_release_depth2
    """
    sc = setup_completion_ready_agreement()
    headers = make_sponsor_headers(sc.sponsor_id)
    complete_agreement(sc.agreement_id)

    certs = get_success_data(
        api.list_certificates(headers, params={"agreement_id": sc.agreement_id})
    )
    assert len(certs) == 1, f"expected exactly 1 certificate, got {len(certs)}"
    cert = certs[0]
    assert cert["agreement_id"] == sc.agreement_id
    assert cert["certified_ojt_hours"] == 16


# ===========================================================================
# Corner: entities / certificate_immutable_no_version_field
# ===========================================================================
def test_certificate_has_no_version_field(api):
    """PRD §2.4: "Two resources are immutable artifacts and therefore carry only
    `id` and `created_at` - they have neither `updated_at` nor `version`."
    PRD §3.7: "it captures the certified agreement via `agreement_id`, the
    `program_id`, the program's `occupation_code` at issuance."

    The cascade-created certificate exposes no version field and snapshots the
    program's occupation_code (47-2111.00).

    Design: Corner/entities/certificate_immutable_no_version_field
    """
    sc, cert = setup_completed_agreement_with_certificate()
    assert cert is not None, "certificate should have been created on completion"
    fetched = get_success_data(
        api.get_certificate(cert["id"], make_sponsor_headers(sc.sponsor_id))
    )
    assert_certificate(fetched)
    assert "version" not in fetched, "certificate must not expose a version field"
    assert fetched["occupation_code"] == "47-2111.00"
    assert fetched["certified_ojt_hours"] == 16


# ===========================================================================
# Corner: errors / completion_requirements_not_met_already_path
# ===========================================================================
def test_complete_ineligible_agreement_rejected(api):
    """PRD §3.7: "the agreement must be `ACTIVE` (otherwise
    `ERR_AGREEMENT_NOT_ACTIVE`) and `completion_eligible` must already be true
    (otherwise `ERR_COMPLETION_REQUIREMENTS_NOT_MET`)."

    Completing an ACTIVE agreement with 0 approved hours (completion_eligible
    false) is rejected with ERR_COMPLETION_REQUIREMENTS_NOT_MET.

    Design: Corner/errors/completion_requirements_not_met_already_path
    """
    sc = setup_active_agreement()  # no hours/RTI -> ineligible
    res = api.complete_agreement(sc.agreement_id, AGENCY)
    validate_error(res, ApiErrorId.ERR_COMPLETION_REQUIREMENTS_NOT_MET.value)


# ===========================================================================
# Corner: rbac / sponsor_cannot_complete_agreement_segregation
# ===========================================================================
def test_sponsor_cannot_complete_agreement(api):
    """PRD §2.1: "A sponsor cannot approve training data and cannot self-certify
    completion."
    PRD §3.7: "Completion itself is reserved to the `RegistrationAgency`, never
    the sponsor - this is where self-certification is forbidden."

    A Sponsor attempting to complete an (eligible) agreement is rejected with
    ERR_INSUFFICIENT_PERMISSIONS; only RegistrationAgency may.

    Design: Corner/rbac/sponsor_cannot_complete_agreement_segregation
    """
    sc = setup_completion_ready_agreement()
    res = api.complete_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ===========================================================================
# Corner: rbac / sponsor_cannot_approve_ojt_segregation
# ===========================================================================
def test_sponsor_cannot_approve_ojt_entry(api):
    """PRD §2.1: "A sponsor cannot approve training data and cannot self-certify
    completion."
    PRD §3.4: "A `TrainingCoordinator` - and only a coordinator, never the party
    that logged the session - reviews each pending entry."

    The Sponsor who logs hours cannot approve them; approve as Sponsor is
    rejected with ERR_INSUFFICIENT_PERMISSIONS.

    Design: Corner/rbac/sponsor_cannot_approve_ojt_segregation
    """
    sc = setup_active_agreement()
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 600, 2)
    res = api.approve_ojt_entry(entry["id"], make_sponsor_headers(sc.sponsor_id))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ===========================================================================
# Corner: rbac / apprentice_can_log_own_ojt_shared_operation
# ===========================================================================
def test_apprentice_can_log_own_ojt(api):
    """PRD §2.1: "An apprentice may log their own on-the-job sessions for later
    approval and may read their own training data, but may not approve hours or
    alter agreements."
    PRD §3.4: "A `Sponsor` or the `Apprentice` themself logs a session by
    supplying the `agreement_id`, the `work_date` (an ISO 8601 date with no time
    component), a `start_time` and `end_time` expressed as minutes-from-midnight,
    and the `credited_hours` to apply toward the on-the-job requirement."

    The Apprentice role may POST an OJT entry, returning 201 with status PENDING.

    Design: Corner/rbac/apprentice_can_log_own_ojt_shared_operation
    """
    sc = setup_active_agreement()
    res = api.create_ojt_entry(
        {"agreement_id": sc.agreement_id, "work_date": "2026-02-01",
         "start_time": 480, "end_time": 600, "credited_hours": 2},
        make_apprentice_headers(sc.apprentice_id),
    )
    entry = validate_success(res, 201)
    assert entry["status"] == "PENDING"
