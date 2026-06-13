"""Optimistic concurrency (record-version pinning on copy issuance) and
validation-priority conflicts. Difficulty (queue A) + corner (queue B)."""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    create_certified_copy_payload,
    create_amendment_payload,
    make_applicant_headers,
    make_registrar_headers,
    setup_registered_record,
    issue_copy,
    seal_record,
    CLERK_1,
    CLERK_2,
    REGISTRAR_1,
    REGISTRAR_2,
)


# ===========================================================================
# Priority pair: ERR_INVALID_STATE (p6) beats ERR_SEGREGATION_OF_DUTIES (p8)
# (queue A: priority_pair_validation_conflict)
# ===========================================================================
def test_reaccept_accepted_return_by_approving_clerk_returns_invalid_state(api):
    """PRD §3.10: "Then the state check: the target must be in a state from which the
    requested transition is defined, or ERR_INVALID_STATE is returned. Only after all
    of these structural gates pass does the system evaluate the cross-entity,
    segregation, temporal, eligibility, and fiscal business rules".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_return_accept
    """
    base = setup_registered_record()  # return already ACCEPTED by registrar-1
    # Re-accept by the very user (clerk-1) who approved the application, acting as Registrar:
    # this violates both state (already ACCEPTED) and segregation, but state wins.
    resp = api.accept_return(base["return"]["id"], make_registrar_headers("clerk-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_reaccept_accepted_return_leaves_status_accepted(api):
    """PRD §3.4: "A registrar accepts a SUBMITTED return, advancing it from SUBMITTED
    to ACCEPTED."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_return_accept
    """
    base = setup_registered_record()
    api.accept_return(base["return"]["id"], make_registrar_headers("clerk-1"))
    assert get_success_data(api.get_return(base["return"]["id"], CLERK_1))["status"] == "ACCEPTED"


# ===========================================================================
# Priority pair: ERR_RECORD_SEALED (p7) beats ERR_CONFIDENTIAL_ACCESS_DENIED (p10)
# (queue A: priority_pair_validation_conflict)
# ===========================================================================
def _seal_record_with_public_copy(api):
    """Helper: REGISTERED record, deny an initial PUBLIC copy, seal the record (now
    confidential), then create a fresh PENDING PUBLIC copy on the sealed record."""
    base = setup_registered_record()
    # First PUBLIC copy must be removed from PENDING before the record can seal.
    c0 = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 2), CLERK_1))
    get_success_data(api.decide_certified_copy(c0["id"], {"decision": "DENY"}, CLERK_2))
    seal_record(base["record"]["id"], REGISTRAR_1)  # forces is_confidential=true
    c1 = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 2), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    base["copy"] = c1
    base["record"] = rec
    return base


def test_public_copy_issue_on_sealed_confidential_record_returns_record_sealed(api):
    """PRD §3.6: "A sealed record may be copied only for a GOVERNMENT requester; any
    other requester against a SEALED record is rejected with ERR_RECORD_SEALED."

    Design: Difficulty/priority_pair_validation_conflict/record_sealed_beats_confidential_access_on_copy_issue
    """
    base = _seal_record_with_public_copy(api)
    resp = api.decide_certified_copy(base["copy"]["id"], {
        "decision": "ISSUE",
        "expected_record_version": base["record"]["version"],
    }, CLERK_2)
    validate_error(resp, ApiErrorId.ERR_RECORD_SEALED.value, expected_status=409)


def test_public_copy_issue_on_sealed_record_stays_pending(api):
    """PRD §3.6: "A decision to issue advances it from PENDING to ISSUED and is the
    most heavily guarded operation in the system."

    Design: Difficulty/priority_pair_validation_conflict/record_sealed_beats_confidential_access_on_copy_issue
    """
    base = _seal_record_with_public_copy(api)
    api.decide_certified_copy(base["copy"]["id"], {
        "decision": "ISSUE",
        "expected_record_version": base["record"]["version"],
    }, CLERK_2)
    assert get_success_data(api.get_certified_copy(base["copy"]["id"], CLERK_1))["status"] == "PENDING"


# ===========================================================================
# OCC stale record version on copy issue (queue B: cross_cutting_complexity_layers)
# ===========================================================================
def test_occ_stale_record_version_on_copy_issue_rejected(api):
    """PRD §2.7: "If the record's version has advanced since the client last read it
    — for instance because another writer applied an amendment that bumped the
    record's version and may have changed its seal or confidentiality posture — the
    decision is rejected with ERR_STALE_VERSION (HTTP 412), forcing the client to
    re-read the record before deciding."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_record_version_on_copy_issue
    """
    base = setup_registered_record()
    # Capture the record version BEFORE the amendment bumps it.
    stale_version = get_success_data(api.get_record(base["record"]["id"], CLERK_1))["version"]
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 1), CLERK_1))
    amendment = get_success_data(api.create_amendment(
        create_amendment_payload(base["record"]["id"], "CLERICAL", new_value="Oc Alpha"),
        make_applicant_headers(base["applicant_a"]["id"])))
    # Applying the amendment bumps the record's version (record -> AMENDED).
    get_success_data(api.decide_amendment(amendment["id"], {"decision": "APPLY"}, REGISTRAR_2))
    resp = api.decide_certified_copy(copy["id"], {
        "decision": "ISSUE",
        "expected_record_version": stale_version,
    }, CLERK_2)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    assert get_success_data(api.get_certified_copy(copy["id"], CLERK_1))["status"] == "PENDING"


def test_occ_correct_record_version_on_copy_issue_succeeds(api):
    """PRD §2.7: "if the client supplies expected_record_version, that value must
    equal the current version of the MarriageRecord the copy is drawn from."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_record_version_succeeds
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 1), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["status"] == "ISSUED"
    assert data["fee_cents"] == 1500  # one copy at first-tier rate
