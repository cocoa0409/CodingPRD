"""Authentication, authorization, and existence-vs-state error ordering."""
from test_helpers import (
    HISTOTECH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    accession_specimen,
    create_case,
    create_patient,
    get_specimen,
    validate_error,
)


def test_auth_missing_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role
    outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.9: "The broad funnel runs as follows: authentication of the headers
    (priority 1) comes before role authorization and entity-backed ownership
    checks (priority 2), which come before request-shape validation
    (priority 3), which comes before resource-existence checks ordered left to
    right across path identifiers and then body-referenced identifiers
    (priority 4)"

    Design: Corner/validations/auth_missing_header_returns_unauthenticated
    """
    # No X-User-Role / X-User-ID headers at all; the unknown id would otherwise
    # produce a 404, but authentication runs first.
    resp = api.get_case(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_existence_beats_state_qc_review_on_unknown_slide(api):
    """PRD §2.9: "resource-existence checks ordered left to right across path
    identifiers and then body-referenced identifiers (priority 4), which come
    before the case-terminal guard on child mutations (priority 5). The
    specific state, safety, constraint, referential, temporal, and
    tissue-budget rules then follow in their declared order."
    PRD §2.6: "returning `ERR_NOT_FOUND` (HTTP 404) for the first path
    identifier that does not resolve"

    Design: Corner/validations/existence_beats_state_qc_review_on_unknown_slide
    """
    resp = api.qc_review_slide(
        NON_EXISTENT_UUID, {"result": "PASS"}, HISTOTECH_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_gross_by_histotech_forbidden(api):
    """PRD §3.2: "Grossing is performed by a `PathologyAssistant`."
    PRD §2.1: "A request whose role is not on the endpoint's authorized list —
    or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/gross_by_histotech_forbidden
    """
    patient = create_patient(mrn="MRN-RB1", full_name="Rbac One")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(case["id"], patient_mrn="MRN-RB1")

    resp = api.gross_specimen(
        specimen["id"], {"gross_description": "wrong role"}, HISTOTECH_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_specimen(specimen["id"])["status"] == "ACCESSIONED"
