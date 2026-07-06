"""Listing/pagination endpoints, RBAC role enforcement, authentication, and the
delivery-time segregation-of-duties control.

Covers Queue B (Corner) sections: endpoints, rbac.
"""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers.test_users import TEST_USERS, make_physician_headers, make_practitioner_headers
from test_helpers.factories import (
    create_physician_payload, create_patient_payload, create_prescription_payload,
    deliver_payload,
)
from test_helpers.fixtures import (
    setup_delivered_no_auth_with_lines, set_clock, create_physician, create_patient,
    setup_order_auth_pending, setup_order_ready_no_auth,
)


# ─── Queue B: endpoints ──────────────────────────────────────────────

def test_list_claim_lines_by_order(api):
    """PRD §4 (Endpoint Definitions): "GET | `/op/claim-lines` | List claim lines;
    filterable by device order | BillingSpecialist, ComplianceOfficer"

    Design: Corner/endpoints/list_claim_lines_by_order_reverse_reachability
    """
    cast, lines = setup_delivered_no_auth_with_lines([
        {"l_code": "L1960", "modifier": "NONE", "billed_units": 1, "fee_schedule_cents": 10000},
        {"l_code": "L1970", "modifier": "RT", "billed_units": 1, "fee_schedule_cents": 20000},
    ])
    data, meta = validate_paginated(
        api.list_claim_lines(TEST_USERS["billing_headers"],
                             params={"device_order_id": cast["ord_id"]}))
    assert meta["total_count"] == 2
    assert all(cl["device_order_id"] == cast["ord_id"] for cl in data)


def test_list_prescriptions_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return.
    If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated list-based responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_prescriptions_pagination_envelope
    """
    phys = validate_success(api.create_physician(
        create_physician_payload(full_name="Dr P", npi="1111111111", pecos_enrolled=True),
        TEST_USERS["compliance_headers"]), 201)
    patient = validate_success(api.create_patient(
        create_patient_payload(full_name="Pat P1", payer_type="COMMERCIAL"),
        TEST_USERS["billing_headers"]), 201)
    for d in ("2026-05-20", "2026-05-21"):
        validate_success(api.create_prescription(
            create_prescription_payload(patient["id"], phys["id"],
                                        device_category="SPINAL_ORTHOSIS",
                                        primary_diagnosis_code="M54.5",
                                        face_to_face_date=d),
            make_physician_headers(phys["id"])), 201)
    data, meta = validate_paginated(
        api.list_prescriptions(make_physician_headers(phys["id"]),
                               params={"physician_id": phys["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Queue B: rbac ───────────────────────────────────────────────────

def test_billing_specialist_cannot_sign_prescription(api):
    """PRD §2.1: "When an authenticated role attempts an operation it is not authorized to
    perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 (Endpoint Definitions): "POST | `/op/prescriptions/{id}/sign` | Sign a draft
    prescription | Physician"

    Design: Corner/rbac/billing_specialist_cannot_sign_prescription
    """
    phys = validate_success(api.create_physician(
        create_physician_payload(full_name="Dr A", npi="1111111111", pecos_enrolled=True),
        TEST_USERS["compliance_headers"]), 201)
    patient = validate_success(api.create_patient(
        create_patient_payload(full_name="Pat F", payer_type="COMMERCIAL"),
        TEST_USERS["billing_headers"]), 201)
    rx = validate_success(api.create_prescription(
        create_prescription_payload(patient["id"], phys["id"],
                                    device_category="SPINAL_ORTHOSIS",
                                    primary_diagnosis_code="M54.5",
                                    face_to_face_date="2026-05-20"),
        make_physician_headers(phys["id"])), 201)
    res = api.sign_prescription(rx["id"], TEST_USERS["billing_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.create_patient(
        create_patient_payload(full_name="Anon", payer_type="COMMERCIAL"),
        headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_practitioner_cannot_approve_prior_auth(api):
    """PRD §2.1: "When an authenticated role attempts an operation it is not authorized to
    perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 (Endpoint Definitions): "POST | `/op/prior-auths/{id}/approve` | Approve an
    auth | ComplianceOfficer"

    Design: Corner/rbac/practitioner_cannot_approve_prior_auth
    """
    cast = setup_order_auth_pending()
    res = api.approve_prior_auth(cast["pa_id"], make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_segregation_of_duties_at_delivery(api):
    """PRD §3.5: "Third — surfaced as its own distinct rejection — the order's
    `fitting_practitioner_id` must differ from the owning prescription's `physician_id`;
    when they are equal, delivery is rejected with `ERR_SEGREGATION_OF_DUTIES`, reflecting
    the anti-self-referral control that the same physician may not both prescribe and
    attest the fitting of one device."

    Design: Corner/rbac/segregation_of_duties_at_delivery
    """
    # fitting_practitioner_id == prescribing physician_id (single physician serves both).
    cast = setup_order_ready_no_auth(same_practitioner_as_physician=True,
                                     supplier_overrides={"accreditation_expiry": "2028-01-01T00:00:00Z",
                                                         "surety_bond_active": True})
    res = api.deliver_order(cast["ord_id"], deliver_payload(cast["ord_v"]),
                            make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
