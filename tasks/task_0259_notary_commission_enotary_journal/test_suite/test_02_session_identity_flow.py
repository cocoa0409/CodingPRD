"""RON session creation, the identity flow, and the notarize cross-entity gate.

Covers the session window validation corner, identity-branch difficulty pair,
cross-entity enotary/signer gates, and the precondition-enforcement corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_session_payload,
    create_document_payload,
    create_signer_payload,
    make_notary_headers,
    TEST_USERS,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]


# ===========================================================================
# Session creation validation
# ===========================================================================
def test_create_session_end_not_after_start_returns_validation_422(api):
    """PRD §2.9: "a value that is syntactically present but semantically illegal —
    negative cents, a commission term outside the allowed set, or an interval whose
    end is not after its start — yields `ERR_VALIDATION` (422)"
    PRD §3.4: "The scheduled end must be strictly after the scheduled start."

    Design: Corner/entities/create_session_end_before_start_returns_validation_422
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "badwin@x.com"})["notary"]
    payload = create_session_payload(
        notary["id"], "2026-07-08T10:00:00Z", "2026-07-08T09:00:00Z"
    )
    resp = api.create_session(payload, make_notary_headers(notary["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_create_document_invalid_act_type_returns_400(api):
    """PRD §2.9: "a missing required field, a wrongly typed value, or an enum value
    outside its declared set yields `ERR_INVALID_REQUEST` (400)"
    PRD §3.1: "The `act_type` is one of `ACKNOWLEDGMENT`, `JURAT`, `OATH`,
    `COPY_CERTIFICATION`, or `SIGNATURE_WITNESS`"

    Design: Corner/entities/create_document_invalid_act_type_enum_returns_400
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "enum@x.com"})["notary"]
    sess = th.create_session(notary["id"], "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    signer = th.add_signer(sess["id"], notary["id"])
    payload = create_document_payload(signer["id"], "MARRIAGE", 100)
    resp = api.add_document(sess["id"], payload, make_notary_headers(notary["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# ===========================================================================
# begin-identity preconditions
# ===========================================================================
def test_begin_identity_without_signer_returns_no_signer(api):
    """PRD §3.5: "Beginning the identity phase advances the session from
    `SCHEDULED` to `IDENTITY_PENDING`. This step requires the session to be
    `SCHEDULED` (else `ERR_INVALID_STATE`), the presiding notary's
    `enotary_authorized` to be `true` (else `ERR_ENOTARY_NOT_AUTHORIZED`), and at
    least one signer to be attached (else `ERR_NO_SIGNER`)."

    Design: Corner/state_machines/begin_identity_without_signer_returns_no_signer
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nosig@x.com"})["notary"]
    sess = th.create_session(notary["id"], "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    resp = api.begin_identity(sess["id"], make_notary_headers(notary["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_SIGNER.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "SCHEDULED"


# ===========================================================================
# cross_entity_state_dependency: begin-identity requires enotary_authorized
# ===========================================================================
def test_begin_identity_requires_enotary_authorized(api):
    """PRD §3.5: "Beginning the identity phase advances the session from
    `SCHEDULED` to `IDENTITY_PENDING`. This step requires the session to be
    `SCHEDULED` (else `ERR_INVALID_STATE`), the presiding notary's
    `enotary_authorized` to be `true` (else `ERR_ENOTARY_NOT_AUTHORIZED`), and at
    least one signer to be attached (else `ERR_NO_SIGNER`)."

    Design: Difficulty/cross_entity_state_dependency/session_begin_requires_notary_enotary_authorized
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": False, "email": "nce1@x.com"})["notary"]
    assert notary["enotary_authorized"] is False
    sess = th.create_session(notary["id"], "2026-06-18T09:00:00Z", "2026-06-18T10:00:00Z")
    th.add_signer(sess["id"], notary["id"])
    resp = api.begin_identity(sess["id"], make_notary_headers(notary["id"]))
    validate_error(resp, ApiErrorId.ERR_ENOTARY_NOT_AUTHORIZED.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "SCHEDULED"


def test_begin_identity_succeeds_when_enotary_authorized(api):
    """PRD §3.2: "At the same moment it computes `enotary_authorized`, which becomes
    `true` only when the jurisdiction's `ron_allowed` is `true`, the applicant's
    `enotary_requested` is `true`, and the bound bond is `ACTIVE`"
    PRD §3.5: "the presiding notary's `enotary_authorized` to be `true` (else
    `ERR_ENOTARY_NOT_AUTHORIZED`)"

    Design: Difficulty/cross_entity_state_dependency/session_begin_requires_notary_enotary_authorized
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nce1b@x.com"})["notary"]
    assert notary["enotary_authorized"] is True
    sess = th.create_session(notary["id"], "2026-06-18T11:00:00Z", "2026-06-18T12:00:00Z")
    th.add_signer(sess["id"], notary["id"])
    data = validate_success(api.begin_identity(sess["id"], make_notary_headers(notary["id"])))
    assert data["status"] == "IDENTITY_PENDING"


# ===========================================================================
# resolve-identity branches (non_linear_state_machine difficulty pair)
# ===========================================================================
def test_resolve_identity_failed_branch_sets_signer_failed(api):
    """PRD §3.5: "When the notary resolves with a failed outcome, the session moves
    from `IDENTITY_PENDING` to `ID_FAILED`; this branch likewise requires the
    session to be `IDENTITY_PENDING` (else `ERR_INVALID_STATE`) and requires that
    at least one signer is still missing either `kba_passed` or
    `credential_analysis_passed` ... On a failed resolution, each signer that lacks
    either check has its `id_status` set to `FAILED`."

    Design: Difficulty/non_linear_state_machine/session_identity_branch_verified_vs_failed
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nbr@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z")
    signer = th.add_signer(sess["id"], notary["id"], full_name="S Bad",
                          kba_passed=False, credential_analysis_passed=True)
    validate_success(api.begin_identity(sess["id"], hdr))
    data = validate_success(api.resolve_identity(sess["id"], {"outcome": "FAILED"}, hdr))
    assert data["status"] == "ID_FAILED"
    refreshed_signer = validate_success(api.get_signer(signer["id"], CA))
    assert refreshed_signer["id_status"] == "FAILED"


def test_resolve_identity_verified_branch_sets_signer_verified(api):
    """PRD §3.5: "When the notary resolves with a verified outcome, the session
    moves from `IDENTITY_PENDING` to `ID_VERIFIED`; this branch requires the
    session to be `IDENTITY_PENDING` (else `ERR_INVALID_STATE`) and requires
    *every* attached signer to have both `kba_passed` and
    `credential_analysis_passed` set to `true` ... On success every signer's
    `id_status` becomes `VERIFIED`."

    Design: Difficulty/non_linear_state_machine/session_identity_branch_verified_vs_failed
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nbr2@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-06-13T11:00:00Z", "2026-06-13T12:00:00Z")
    signer = th.add_signer(sess["id"], notary["id"], full_name="S Good",
                          kba_passed=True, credential_analysis_passed=True)
    validate_success(api.begin_identity(sess["id"], hdr))
    data = validate_success(api.resolve_identity(sess["id"], {"outcome": "VERIFIED"}, hdr))
    assert data["status"] == "ID_VERIFIED"
    refreshed_signer = validate_success(api.get_signer(signer["id"], CA))
    assert refreshed_signer["id_status"] == "VERIFIED"


def test_resolve_verified_with_unverified_signer_returns_credential_not_verified(api):
    """PRD §3.5: "this branch requires the session to be `IDENTITY_PENDING` (else
    `ERR_INVALID_STATE`) and requires *every* attached signer to have both
    `kba_passed` and `credential_analysis_passed` set to `true`, failing with
    `ERR_CREDENTIAL_NOT_VERIFIED` if any signer is missing either check."

    Design: Corner/state_machines/resolve_identity_verified_with_unverified_signer_returns_credential_not_verified
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "cred@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-07-04T09:00:00Z", "2026-07-04T10:00:00Z")
    th.add_signer(sess["id"], notary["id"], full_name="S Cred",
                  kba_passed=True, credential_analysis_passed=False)
    validate_success(api.begin_identity(sess["id"], hdr))
    resp = api.resolve_identity(sess["id"], {"outcome": "VERIFIED"}, hdr)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_VERIFIED.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "IDENTITY_PENDING"


def test_resolve_failed_when_all_verified_returns_already_verified(api):
    """PRD §3.5: "if in fact every signer is already fully verified, the failed
    outcome is rejected with `ERR_CREDENTIAL_ALREADY_VERIFIED`."

    Design: Corner/state_machines/resolve_identity_failed_when_all_verified_returns_already_verified
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "alrv@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-07-05T09:00:00Z", "2026-07-05T10:00:00Z")
    th.add_signer(sess["id"], notary["id"], full_name="S AllOk",
                  kba_passed=True, credential_analysis_passed=True)
    validate_success(api.begin_identity(sess["id"], hdr))
    resp = api.resolve_identity(sess["id"], {"outcome": "FAILED"}, hdr)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_ALREADY_VERIFIED.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "IDENTITY_PENDING"


# ===========================================================================
# start preconditions
# ===========================================================================
def test_start_session_without_document_returns_no_document(api):
    """PRD §3.5: "From `ID_VERIFIED`, starting the active notarization phase moves
    the session to `ACTIVE`. This requires the session to be `ID_VERIFIED` (else
    `ERR_INVALID_STATE`) and at least one document to be attached (else
    `ERR_NO_DOCUMENT`)."

    Design: Corner/state_machines/start_session_without_document_returns_no_document
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nodoc@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-07-03T09:00:00Z", "2026-07-03T10:00:00Z")
    th.add_signer(sess["id"], notary["id"])
    validate_success(api.begin_identity(sess["id"], hdr))
    validate_success(api.resolve_identity(sess["id"], {"outcome": "VERIFIED"}, hdr))
    resp = api.start_session(sess["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_NO_DOCUMENT.value, expected_status=409)
    refreshed = validate_success(api.get_session(sess["id"], CA))
    assert refreshed["status"] == "ID_VERIFIED"


# ===========================================================================
# cross_entity_state_dependency: notarize requires signer VERIFIED
# ===========================================================================
def test_notarize_document_requires_signer_verified(api):
    """PRD §3.5: "Notarizing a document moves it from `PENDING` to `NOTARIZED`;
    this requires the document to be `PENDING` (else `ERR_INVALID_STATE`), its
    parent session to be `ACTIVE` (else `ERR_INVALID_STATE`), and the document's
    linked signer to have an `id_status` of `VERIFIED` (else
    `ERR_SIGNER_NOT_VERIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/document_notarize_requires_signer_verified
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nce2@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    sess = th.create_session(notary["id"], "2026-06-19T09:00:00Z", "2026-06-19T10:00:00Z")
    signer_a = th.add_signer(sess["id"], notary["id"], full_name="S A", kba_passed=True, credential_analysis_passed=True)
    # A document for the verified signer satisfies start's ERR_NO_DOCUMENT gate
    # (PRD §3.5: start requires at least one document attached).
    th.add_document(sess["id"], notary["id"], signer_a["id"], "ACKNOWLEDGMENT", 400)
    validate_success(api.begin_identity(sess["id"], hdr))
    validate_success(api.resolve_identity(sess["id"], {"outcome": "VERIFIED"}, hdr))
    validate_success(api.start_session(sess["id"], hdr))
    # attach a second UNVERIFIED signer and bind a document to it
    signer_b = th.add_signer(sess["id"], notary["id"], full_name="S B",
                            kba_passed=False, credential_analysis_passed=False)
    doc_b = th.add_document(sess["id"], notary["id"], signer_b["id"], "JURAT", 400)
    resp = api.notarize_document(sess["id"], doc_b["id"], {}, hdr)
    validate_error(resp, ApiErrorId.ERR_SIGNER_NOT_VERIFIED.value, expected_status=409)
    refreshed_doc = validate_success(api.get_document(doc_b["id"], CA))
    assert refreshed_doc["status"] == "PENDING"
    refreshed_signer = validate_success(api.get_signer(signer_b["id"], CA))
    assert refreshed_signer["id_status"] == "UNVERIFIED"


def test_notarize_document_with_verified_signer_succeeds(api):
    """PRD §3.5: "Notarizing a document moves it from `PENDING` to `NOTARIZED`;
    this requires the document to be `PENDING` (else `ERR_INVALID_STATE`), its
    parent session to be `ACTIVE` (else `ERR_INVALID_STATE`), and the document's
    linked signer to have an `id_status` of `VERIFIED` (else
    `ERR_SIGNER_NOT_VERIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/document_notarize_requires_signer_verified
    """
    notary = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "nce2b@x.com"})["notary"]
    hdr = make_notary_headers(notary["id"])
    built = th.setup_session_to_active(
        notary["id"], "2026-06-19T11:00:00Z", "2026-06-19T12:00:00Z",
        documents=[("JURAT", 400)],
    )
    doc = built["documents"][0]
    data = validate_success(api.notarize_document(built["session"]["id"], doc["id"], {}, hdr))
    assert data["status"] == "NOTARIZED"
