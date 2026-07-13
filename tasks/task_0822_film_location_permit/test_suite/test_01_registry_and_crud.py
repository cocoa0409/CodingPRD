"""Registry, CRUD, and read-model behaviour translated from the corner-design index."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
)


def test_production_company_system_fields_minted(api):
    """PRD §3.1: "On registration, three behavioral counters — late_wrap_count,
    damage_incident_count, and missed_notification_count — start at 0, and the company's
    compliance_score starts at 100."
    PRD §2.4: "Each resource also carries an integer version that begins at 1 and increments
    by one on every mutation of that resource."

    Design: Corner/entities/production_company_system_fields_minted
    """
    resp = api.create_production_company(
        th.production_company_payload(legal_name="Sys Co", contact_email="s@x.test", primary_contact="Q"),
        th.make_coordinator_headers(),
    )
    data = validate_success(resp, 201)
    th.assert_production_company(data)
    assert data["version"] == 1
    assert data["compliance_score"] == 100
    assert data["late_wrap_count"] == 0
    assert data["damage_incident_count"] == 0
    assert data["missed_notification_count"] == 0


def test_application_initial_state_is_draft(api):
    """PRD §3.2: "An applicant opens a new application in DRAFT status by supplying the owning
    production_company_id, a title, a synopsis, the requested shoot_start_at and shoot_end_at
    instants, the total crew_size (which must be at least 1), and two booleans,
    requires_road_closure and requires_parking, each defaulting to false."
    PRD §2.4: "Each resource also carries an integer version that begins at 1 and increments
    by one on every mutation of that resource."

    Design: Corner/entities/application_initial_state_is_draft
    """
    pc = th.make_company(api, legal_name="Init Co", contact_email="i@x.test", primary_contact="S")
    resp = api.create_application(
        th.application_payload(pc["id"], title="Init", synopsis="x"),
        th.make_production_company_headers(pc["id"]),
    )
    data = validate_success(resp, 201)
    th.assert_application(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1


def test_department_create_invalid_enum(api):
    """PRD §3.1: "A Department is created with a code — one of POLICE, PARKING, FIRE, or
    PUBLIC_WORKS — a human-readable name, and a trigger_condition that declares which
    applications require this department's review."
    PRD §2.8: "Then the body is checked for well-formedness — required fields present, enum
    values in range, constrained integers non-negative — yielding ERR_INVALID_REQUEST (400)."

    Design: Corner/entities/department_create_invalid_enum
    """
    resp = api.create_department(
        {"code": "MAYOR", "name": "Mayor", "trigger_condition": "ALL_APPLICATIONS"},
        th.make_coordinator_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_application_create_missing_required_synopsis(api):
    """PRD §2.8: "Then the body is checked for well-formedness — required fields present, enum
    values in range, constrained integers non-negative — yielding ERR_INVALID_REQUEST (400)."
    PRD §3.2: "An applicant opens a new application in DRAFT status by supplying the owning
    production_company_id, a title, a synopsis, the requested shoot_start_at and shoot_end_at
    instants, the total crew_size (which must be at least 1) ..."

    Design: Corner/entities/application_create_missing_required_field
    """
    pc = th.make_company(api, legal_name="C1", contact_email="c1@x.test", primary_contact="Z")
    resp = api.create_application(
        {"production_company_id": pc["id"], "title": "NoSyn",
         "shoot_start_at": "2026-06-01T08:00:00Z", "shoot_end_at": "2026-06-01T18:00:00Z", "crew_size": 5},
        th.make_production_company_headers(pc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_application_get_not_found(api):
    """PRD §2.8: "Then path existence is verified left-to-right — for a nested path, each id
    segment is resolved in order, and the first that does not resolve yields ERR_NOT_FOUND
    (404)."

    Design: Corner/entities/application_get_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_application_list_pagination_envelope(api):
    """PRD §2.3: "The response's meta object carries limit, offset, total_count (the total
    number of matching records before pagination), and has_more (true when records beyond the
    current page remain)."

    Design: Corner/entities/application_list_pagination_envelope
    """
    pc = th.make_company(api, legal_name="List Co", contact_email="l@x.test", primary_contact="R")
    th.make_application(api, pc["id"], title="L1")
    th.make_application(api, pc["id"], title="L2", shoot_start_at="2026-06-02T08:00:00Z",
                        shoot_end_at="2026-06-02T18:00:00Z")
    resp = api.list_applications(th.make_coordinator_headers(),
                                 params={"production_company_id": pc["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_application_immediate_read_after_write(api):
    """PRD §3.2: "An applicant opens a new application in DRAFT status by supplying the owning
    production_company_id, a title, a synopsis, the requested shoot_start_at and shoot_end_at
    instants, the total crew_size (which must be at least 1) ..."

    Design: Corner/consistency_model/immediate_read_after_write
    """
    pc = th.make_company(api, legal_name="Imm Co", contact_email="im@x.test", primary_contact="LL")
    created = th.make_application(api, pc["id"], title="Imm")
    resp = api.get_application(created["id"], th.make_coordinator_headers())
    data = validate_success(resp, 200)
    assert data["id"] == created["id"]
    assert data["status"] == "DRAFT"


def test_application_invalid_time_range(api):
    """PRD §3.2: "The shoot_end_at must be strictly after shoot_start_at; otherwise the creation
    is rejected with ERR_INVALID_TIME_RANGE."

    Design: Corner/validations/application_invalid_time_range
    """
    pc = th.make_company(api, legal_name="Time Co", contact_email="tm@x.test", primary_contact="AA")
    resp = api.create_application(
        th.application_payload(pc["id"], title="Bad", synopsis="x",
                               shoot_start_at="2026-06-01T18:00:00Z",
                               shoot_end_at="2026-06-01T08:00:00Z"),
        th.make_production_company_headers(pc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


def test_coi_verify_submitted_to_verified(api):
    """PRD §3.6: "A verification decision is either VERIFY, moving the certificate
    SUBMITTED → VERIFIED, or REJECT, moving it SUBMITTED → REJECTED; both require the
    certificate to currently be SUBMITTED, else the decision is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/coi_verify_valid_transition
    """
    pc = th.make_company(api, legal_name="Coi Co", contact_email="co@x.test", primary_contact="V")
    app = th.make_application(api, pc["id"], title="Coi")
    coi = th.add_coi(api, app["id"], pc["id"], policy_number="POL-C")
    assert coi["status"] == "SUBMITTED"
    resp = api.verify_insurance_certificate(coi["id"], {"decision": "VERIFY"}, th.make_coordinator_headers())
    data = validate_success(resp, 200)
    assert data["status"] == "VERIFIED"
