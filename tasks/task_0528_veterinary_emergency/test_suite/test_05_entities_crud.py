"""Entity CRUD, defaults, required-field and parent-relationship corner cases.

Corner queue: entities section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_triage_nurse_headers,
    register_patient,
    get_invoice,
    api_client,
)


def test_create_patient_returns_201_all_fields(api):
    """PRD §3.1: "Registration captures the animal's `name`, its `species` — one
    of `CANINE`, `FELINE`, or `EXOTIC` — its `weight_kg`, which must be strictly
    greater than zero, and the `owner_user_id` identifying the owning client."

    Design: Corner/entities/patient_create_returns_201_all_fields
    """
    nurse = make_triage_nurse_headers()
    resp = api.create_patient({
        "name": "Rex", "species": "CANINE", "weight_kg": 30,
        "owner_user_id": "owner-1"}, nurse)
    patient = validate_success(resp, expected_status=201)
    assert patient["name"] == "Rex"
    assert patient["species"] == "CANINE"
    assert patient["owner_user_id"] == "owner-1"


def test_get_patient_not_found_returns_404(api):
    """PRD §2.5: "If the Visit named in the path does not exist, the request fails
    with `ERR_NOT_FOUND` before the child is ever considered; only once the
    parent resolves does the system look up the child, again returning
    `ERR_NOT_FOUND` if the child is absent."

    Design: Corner/entities/patient_get_not_found_returns_404
    """
    nurse = make_triage_nurse_headers()
    resp = api.get_patient(NON_EXISTENT_UUID, nurse)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_patient_missing_species_invalid_request(api):
    """PRD §2.6: "fourth, malformed-request checks on the body such as a missing
    required field or a bad enum value (`ERR_INVALID_REQUEST`)"
    PRD §3.1: "Registration captures the animal's `name`, its `species` — one of
    `CANINE`, `FELINE`, or `EXOTIC` — its `weight_kg` ... and the `owner_user_id`"

    Design: Corner/entities/patient_create_missing_species_returns_invalid_request
    """
    nurse = make_triage_nurse_headers()
    resp = api.create_patient({
        "name": "Rex", "weight_kg": 30, "owner_user_id": "owner-1"}, nurse)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_patient_nonpositive_weight_invalid_request(api):
    """PRD §3.1: "its `weight_kg`, which must be strictly greater than zero ...
    A non-positive `weight_kg` is a malformed request and is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/patient_create_nonpositive_weight_returns_invalid_request
    """
    nurse = make_triage_nurse_headers()
    resp = api.create_patient({
        "name": "Rex", "species": "CANINE", "weight_kg": 0,
        "owner_user_id": "owner-1"}, nurse)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_visit_defaults_and_open_invoice(api):
    """PRD §3.1: "A newly opened Visit begins in `REGISTERED` status with its
    `department` set to `ER`, its `triage_level` still unset, its
    `authorized_ceiling_cents` and `charges_committed_cents` both at zero, and
    its `version` at 1."
    PRD §3.1: "the system creates the single open Invoice that will accumulate
    this case's charges; there is exactly one invoice per visit, and it starts in
    `OPEN` status."

    Design: Corner/entities/visit_create_defaults_er_registered_open_invoice
    """
    nurse = make_triage_nurse_headers()
    patient = register_patient(owner_user_id="owner-1")
    resp = api.create_visit({
        "patient_id": patient["id"], "chief_complaint": "collapse"}, nurse)
    visit = validate_success(resp, expected_status=201)
    assert visit["status"] == "REGISTERED"
    assert visit["department"] == "ER"
    assert visit["version"] == 1
    assert visit["triage_level"] is None
    invoice_list = get_success_data(api.get_invoice(visit["id"], nurse))
    assert isinstance(invoice_list, list)
    assert len(invoice_list) == 1
    assert invoice_list[0]["status"] == "OPEN"


def test_create_visit_bad_patient_not_found(api):
    """PRD §2.5: "The system validates the existence of each path-referenced
    resource left to right, parent before child."
    PRD §3.1: "A `TriageNurse` opens an emergency-room case by registering a
    Visit for a patient, supplying the `patient_id` and a free-text
    `chief_complaint`."

    Design: Corner/entities/visit_create_bad_patient_returns_not_found
    """
    nurse = make_triage_nurse_headers()
    resp = api.create_visit({
        "patient_id": NON_EXISTENT_UUID, "chief_complaint": "x"}, nurse)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
