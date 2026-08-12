"""Farm enrollment, compliance documents, suspension cascade, reinstatement."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_agreement,
    assert_compliance_document,
    assert_farm,
    assert_invoice,
    assert_offering,
    create_accepted_delivery,
    create_agreement,
    create_approved_farm,
    create_farm,
    create_invoice,
    create_kitchen,
    create_receiving_window,
    make_farm_manager_headers,
    make_kitchen_manager_headers,
    schedule_delivery,
    setup_procurement_chain,
    sign_agreement,
    upload_liability_insurance,
    upload_safety_cert,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_farm_initial_state_applied(api):
    """PRD section 3.2: "A grower enters the program when a
    `DistrictProgramAdmin` registers the farm with its `legal_name`,
    `contact_email`, the `distance_miles_to_hub` in road miles from the
    district hub (zero or more), and the farmed `acres` (greater than zero);
    the farm begins `APPLIED`."

    Design: Corner/state_machines/sm_farm_initial_state_applied
    """
    farm = create_farm()
    assert_farm(farm)
    assert farm["status"] == "APPLIED", (
        f"a newly registered farm must begin APPLIED, got {farm['status']}"
    )


def test_farm_create_missing_required_field(api):
    """PRD section 2.5: "The user-context headers are checked, then required
    body fields and their types. Missing or malformed fields fail as
    `ERR_INVALID_REQUEST`"

    Design: Corner/entities/ent_farm_create_missing_required_field
    """
    resp = api.create_farm(
        {"legal_name": "No Acres", "contact_email": "n@x.com",
         "distance_miles_to_hub": 30},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_document_conditional_coverage_required(api):
    """PRD section 3.2: "A liability policy must additionally declare its
    `coverage_cents` — omitting it is `ERR_COVERAGE_REQUIRED`, and a figure
    below the farm's `required_insurance_cents` is `ERR_COVERAGE_BELOW_MINIMUM`,
    while coverage exactly equal to the requirement satisfies it."

    Design: Corner/entities/ent_document_conditional_coverage_required
    """
    farm = create_farm()
    headers = make_farm_manager_headers(farm["id"])

    resp = api.create_compliance_document(
        {
            "farm_id": farm["id"],
            "doc_type": "LIABILITY_INSURANCE",
            "issuer": "InsCo",
            "effective_on": "2026-01-01",
            "expires_on": "2027-12-31",
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_REQUIRED)

    resp = api.create_compliance_document(
        {
            "farm_id": farm["id"],
            "doc_type": "SAFETY_CERT",
            "issuer": "StateAg",
            "effective_on": "2026-01-01",
            "expires_on": "2027-12-31",
        },
        headers,
    )
    doc = validate_success(resp, 201)
    assert_compliance_document(doc)
    assert doc["status"] == "ACTIVE"


def test_document_invalid_date_range_rejected(api):
    """PRD section 3.2: "`expires_on` must be later than `effective_on`,
    failing which the upload is rejected as `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/ent_document_invalid_date_range_rejected
    """
    farm = create_farm()
    resp = api.create_compliance_document(
        {
            "farm_id": farm["id"],
            "doc_type": "SAFETY_CERT",
            "issuer": "StateAg",
            "effective_on": "2026-06-01",
            "expires_on": "2026-06-01",
        },
        make_farm_manager_headers(farm["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_insurance_minimum_acreage_boundary(api):
    """PRD section 3.2: "The `is_small_farm` flag is true when the farm works
    at most five hundred acres — a farm of exactly five hundred acres qualifies
    as small. The `required_insurance_cents` floor is 500,000 cents of
    liability coverage for a small farm and 1,000,000 cents for a larger one."
    PRD section 3.2: "a figure below the farm's `required_insurance_cents` is
    `ERR_COVERAGE_BELOW_MINIMUM`, while coverage exactly equal to the
    requirement satisfies it."
    PRD section 3.2: "its compliance file to be complete at the current clock
    date: a valid safety certificate and sufficient in-date insurance must both
    exist, failing which approval is rejected with
    `ERR_FARM_COMPLIANCE_INCOMPLETE`."

    Design: Corner/calculations/calc_insurance_minimum_acreage_boundary
    """
    f100 = create_farm(legal_name="A100", acres=100)
    f500 = create_farm(legal_name="A500", acres=500)
    f501 = create_farm(legal_name="A501", acres=501)

    assert f500["required_insurance_cents"] == 500000, (
        "a farm of exactly five hundred acres qualifies as small"
    )
    assert f501["required_insurance_cents"] == 1000000

    # Below-minimum coverage is rejected at document creation.
    resp = api.create_compliance_document(
        {
            "farm_id": f100["id"],
            "doc_type": "LIABILITY_INSURANCE",
            "issuer": "InsCo",
            "coverage_cents": 400000,
            "effective_on": "2026-01-01",
            "expires_on": "2027-12-31",
        },
        make_farm_manager_headers(f100["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM)

    # Coverage exactly equal to the requirement satisfies it.
    upload_safety_cert(f500["id"])
    upload_liability_insurance(f500["id"], coverage_cents=500000)
    farm500 = validate_success(api.approve_farm(f500["id"], ADMIN), 200)
    assert farm500["status"] == "APPROVED"

    # A 501-acre farm needs 1,000,000: a 600,000 policy is rejected at upload,
    # and approval without in-date insurance is incomplete.
    upload_safety_cert(f501["id"])
    resp = api.create_compliance_document(
        {
            "farm_id": f501["id"],
            "doc_type": "LIABILITY_INSURANCE",
            "issuer": "InsCo",
            "coverage_cents": 600000,
            "effective_on": "2026-01-01",
            "expires_on": "2027-12-31",
        },
        make_farm_manager_headers(f501["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM)
    resp = api.approve_farm(f501["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_FARM_COMPLIANCE_INCOMPLETE)


def test_clock_sweep_expires_document(api):
    """PRD section 2.8: "Compliance documents whose `expires_on` now lies in
    the past move from `ACTIVE` to `EXPIRED`."
    PRD section 3.2: "Against a reference date, the posture is `COMPLIANT` when
    the farm is `APPROVED` and holds at least one `ACTIVE` safety certificate
    whose date range brackets the reference date and at least one `ACTIVE`
    liability policy whose date range brackets the reference date and whose
    coverage meets the farm's requirement; otherwise the posture is
    `NON_COMPLIANT`."

    Design: Corner/state_machines/sm_clock_sweep_expires_document
    """
    farm = create_farm()
    cert = upload_safety_cert(farm["id"], expires_on="2026-08-01")
    upload_liability_insurance(farm["id"])
    approve_resp = validate_success(api.approve_farm(farm["id"], ADMIN), 200)
    assert approve_resp["status"] == "APPROVED"

    advance_clock("2026-08-02T00:00:00Z")

    doc = validate_success(api.get_compliance_document(cert["id"], ADMIN), 200)
    assert doc["status"] == "EXPIRED", (
        f"clock sweep past expires_on must expire the document, got {doc['status']}"
    )
    farm_after = validate_success(api.get_farm(farm["id"], ADMIN), 200)
    assert farm_after["compliance_posture"] == "NON_COMPLIANT"


def test_document_revoke_twice_error(api):
    """PRD section 3.2: "a `StateGrantAuditor` may revoke an `ACTIVE` document
    outright (any other state draws `ERR_DOCUMENT_NOT_ACTIVE`), leaving it
    `REVOKED`."

    Design: Corner/state_machines/sm_document_revoke_twice_error
    """
    farm = create_farm()
    cert = upload_safety_cert(farm["id"])
    doc = validate_success(api.revoke_compliance_document(cert["id"], AUDITOR), 200)
    assert doc["status"] == "REVOKED"
    resp = api.revoke_compliance_document(cert["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_ACTIVE)


def test_reinstate_restores_offerings_not_agreements(api):
    """PRD section 3.2: "On reinstatement, each of the farm's offerings in
    `SUSPENDED` returns to `VERIFIED`. Breached agreements are not resurrected:
    `BREACHED` is terminal, and the released quantities stay released."

    Design: Corner/state_machines/sm_reinstate_restores_offerings_not_agreements
    """
    chain = setup_procurement_chain()
    validate_success(api.suspend_farm(chain.farm["id"], ADMIN), 200)
    farm = validate_success(api.reinstate_farm(chain.farm["id"], ADMIN), 200)
    assert farm["status"] == "APPROVED"

    offering = validate_success(api.get_offering(chain.offering["id"], ADMIN), 200)
    assert offering["status"] == "VERIFIED", (
        f"suspended offering must return to VERIFIED, got {offering['status']}"
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "BREACHED", (
        f"breached agreements are not resurrected, got {agreement['status']}"
    )


def _setup_suspension_cascade():
    """Farm with a VERIFIED offering and a FULFILLING agreement carrying one
    ACCEPTED delivery (invoiced, DRAFT), one SCHEDULED delivery, and one
    CHECKED_IN delivery."""
    chain = setup_procurement_chain(committed_quantity=200, window_capacity=5)
    farm_id = chain.farm["id"]
    kit_id = chain.kitchen["id"]
    win_id = chain.window["id"]
    agr_id = chain.agreement["id"]

    del_accepted = create_accepted_delivery(
        agr_id, kit_id, win_id, farm_id, "2026-08-10", 40
    )
    invoice = validate_success(
        create_invoice(del_accepted["id"], farm_id, "INV-A"), 201
    )
    del_scheduled = validate_success(
        schedule_delivery(agr_id, kit_id, win_id, farm_id, "2026-08-17", 40), 201
    )
    del_checked = validate_success(
        schedule_delivery(agr_id, kit_id, win_id, farm_id, "2026-08-17", 10), 201
    )
    check_in = api_client.check_in_delivery(
        del_checked["id"], make_kitchen_manager_headers(kit_id)
    )
    validate_success(check_in, 200)
    return chain, del_scheduled["id"], del_checked["id"], invoice["id"]


def test_farm_suspension_cascade_offerings_and_agreements(api):
    """PRD section 3.2: "Suspension is deliberately destructive, and the
    cascade that follows it is exact: every offering of the farm in `VERIFIED`
    moves to `SUSPENDED`; every planting agreement whose offering was just
    suspended and that stands in `SIGNED`, `AMENDMENT_PROPOSED`, or
    `FULFILLING` is breached, setting its `released_quantity` to the committed
    quantity minus what has been delivered and its `remaining_quantity` to
    zero"

    Design: Difficulty/transitive_cascade/farm_suspension_depth4_cascade
    """
    chain, _del_s, _del_c, _inv = _setup_suspension_cascade()
    resp = api.suspend_farm(chain.farm["id"], ADMIN)
    farm = validate_success(resp, 200)
    assert farm["status"] == "SUSPENDED"

    offering = validate_success(api.get_offering(chain.offering["id"], ADMIN), 200)
    assert offering["status"] == "SUSPENDED", "link 1: VERIFIED offering suspends"

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert_agreement(agreement)
    assert agreement["status"] == "BREACHED", "link 2: agreement breaches"
    assert agreement["delivered_quantity"] == 40
    assert agreement["released_quantity"] == 160, (
        "released_quantity is the committed quantity minus what has been delivered"
    )
    assert agreement["remaining_quantity"] == 0


def test_farm_suspension_cascade_deliveries_and_invoices(api):
    """PRD section 3.2: "every `SCHEDULED` delivery of a just-breached
    agreement moves to `CANCELLED`, while `CHECKED_IN` deliveries are left
    untouched; and every `DRAFT` invoice belonging to a just-breached agreement
    moves to `VOIDED`."

    Design: Difficulty/transitive_cascade/farm_suspension_depth4_cascade
    """
    chain, del_s_id, del_c_id, inv_id = _setup_suspension_cascade()
    resp = api.suspend_farm(chain.farm["id"], ADMIN)
    validate_success(resp, 200)

    del_s = validate_success(api.get_delivery(del_s_id, ADMIN), 200)
    assert del_s["status"] == "CANCELLED", "link 3: SCHEDULED delivery cancels"

    del_c = validate_success(api.get_delivery(del_c_id, ADMIN), 200)
    assert del_c["status"] == "CHECKED_IN", (
        "conditional cascade: the in-transit CHECKED_IN delivery is untouched"
    )

    invoice = validate_success(api.get_invoice(inv_id, ADMIN), 200)
    assert_invoice(invoice)
    assert invoice["status"] == "VOIDED", "link 4: DRAFT invoice voids"
