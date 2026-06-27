"""Entity creation, defaults, computed/system fields, immutability, and listing claims.

Covers corner queue B `entities` and `endpoints` section instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_modality,
    assert_ledger_entry,
    bookable_scenario,
    drive_to_paid,
    set_clock,
    create_plan,
    create_package,
    create_appointment_payload,
    create_superbill_payload,
    create_certification_payload,
    create_modality,
    create_table,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_create_modality_returns_201_with_fields(api):
    """PRD §4: "Creating a new resource returns HTTP 201 with the created resource in data." PRD
    §3.1: "A modality's base_price_cents is the list price for a sixty-minute session." PRD §2.7:
    "Modality ... records carry an archived flag that is false at creation."

    Design: Corner/entities/create_modality_returns_201_with_fields
    """
    resp = api.create_modality(
        {"name": "Swedish Crt", "code": "SWEDCRT", "base_price_cents": 12000,
         "contraindication_tags": ["PREGNANCY"]}, ADMIN)
    mod = validate_success(resp, expected_status=201)
    assert mod["code"] == "SWEDCRT"
    assert mod["base_price_cents"] == 12000
    assert mod["archived"] is False
    assert_modality(mod)


def test_get_modality_not_found(api):
    """PRD §2.9: "that resource must exist ... the first reference that does not resolve yields
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_modality_not_found
    """
    validate_error(api.get_modality(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_modality_missing_required_field(api):
    """PRD §2.10: "then request well-formedness — required fields present, enums valid, integers
    within their declared ranges (ERR_INVALID_REQUEST)." PRD §3.1: "A modality's
    base_price_cents is the list price for a sixty-minute session of this modality."

    Omitting base_price_cents on modality create returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_modality_missing_required_field
    """
    validate_error(api.create_modality({"name": "NoPrice", "code": "NOPRICE"}, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_modality_requires_certification_default_false(api):
    """PRD §3.1: "When requires_certification is true (it defaults to false), only a therapist
    holding an active certification for this modality's code may be assigned to its sessions."

    Design: Corner/entities/modality_requires_certification_default_false
    """
    mod = validate_success(
        api.create_modality({"name": "LymphDef", "code": "LYMPHDEF", "base_price_cents": 11000}, ADMIN),
        expected_status=201)
    assert mod["requires_certification"] is False


def test_therapist_license_status_computed_active(api):
    """PRD §3.1: "the derived license_status reads ACTIVE while license_expiry is strictly after
    the clock's current value and LICENSE_EXPIRED once license_expiry is at or before the clock."

    At the default clock (2026-01-01) a therapist with expiry 2027-06-01 reads ACTIVE.

    Design: Corner/entities/therapist_license_status_computed_active
    """
    therapist = validate_success(api.create_therapist(
        {"full_name": "Lic Test", "license_number": "LMT-900100",
         "license_expiry": "2027-06-01T00:00:00Z"}, ADMIN), expected_status=201)
    assert therapist["license_status"] == "ACTIVE"


def test_client_system_fields_generated(api):
    """PRD §2.4: "version, an integer that begins at 1 when the resource is created." PRD §3.2:
    "wallet_credit_cents is a store-credit balance (default 0) ...; no_show_strikes (default 0)
    counts recent no-shows."

    Design: Corner/entities/client_system_fields_generated
    """
    client = validate_success(
        api.create_client({"full_name": "Sys Fields", "email": "sysfields@example.com"}, FRONT),
        expected_status=201)
    assert client["version"] == 1
    assert client["wallet_credit_cents"] == 0
    assert client["no_show_strikes"] == 0


def test_appointment_invalid_duration_enum(api):
    """PRD §3.4: "an optional duration_minutes (one of 30, 60, 90, or 120; default 60)." PRD
    §2.10: "request well-formedness — required fields present, enums valid, integers within
    their declared ranges (ERR_INVALID_REQUEST)."

    Booking with duration_minutes 45 (not in the allowed set) returns ERR_INVALID_REQUEST.

    Design: Corner/entities/appointment_invalid_duration_enum
    """
    scn = bookable_scenario()
    fresh = validate_success(api.get_table(scn["table"]["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], scn["therapist"]["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-01-05T09:00:00Z", duration_minutes=45, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_credit_ledger_entry_immutable_no_version(api):
    """PRD §2.4: "A CreditLedgerEntry is an append-only audit record and carries only id and
    created_at; it has no updated_at and no version, because it is never mutated after it is
    written." PRD §3.10: "Enrolling a client grants the plan's included_sessions as the opening
    credit balance — recorded as a CreditLedgerEntry with reason GRANT."

    Design: Corner/entities/credit_ledger_entry_immutable_no_version
    """
    plan = create_plan(name="LedgerPlan", monthly_fee_cents=9000, included_sessions=2)
    client = validate_success(api.create_client(
        {"full_name": "Ledger Cli", "email": "ledgercli@example.com"}, FRONT), expected_status=201)
    pkg = create_package(client["id"], plan["id"])
    ledger = validate_success(api.get_package_ledger(pkg["id"], ADMIN))
    assert len(ledger) == 1
    assert ledger[0]["reason"] == "GRANT"
    assert ledger[0]["balance_after"] == 2
    assert_ledger_entry(ledger[0])


def test_package_requires_existing_plan(api):
    """PRD §2.9: "through a foreign-key body field such as ... plan_id ... that resource must
    exist ... the first reference that does not resolve yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/package_requires_existing_plan
    """
    client = validate_success(api.create_client(
        {"full_name": "NoPlan Cli", "email": "noplancli@example.com"}, FRONT), expected_status=201)
    validate_error(api.create_package({"client_id": client["id"], "plan_id": NON_EXISTENT_UUID}, FRONT),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_list_appointments_pagination_envelope(api):
    """PRD §2.3: "The meta object of a list response reports limit, offset, total_count (the
    total number of matching records before the page window is applied), and has_more (true when
    records beyond the current window remain)." PRD §2.2: "The response_type is either object for
    a single resource or array for a list of resources."

    On an empty database the appointments list reports total_count 0 and has_more false.

    Design: Corner/entities/list_appointments_pagination_envelope
    """
    data, meta = validate_paginated(api.list_appointments(FRONT))
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_modality_archived_excluded_from_default_list(api):
    """PRD §2.7: "Archived records are hidden from default list responses ... List endpoints for
    these collections accept an include_archived flag; when it is set, archived records are
    included in the result."

    The default modality list returns only non-archived records.

    Design: Corner/entities/modality_archived_excluded_from_default_list
    """
    create_modality(name="SwedishArc", code="SWEDARC", base_price_cents=12000)
    data, _ = validate_paginated(api.list_modalities(FRONT))
    assert all(m["archived"] is False for m in data), "default list must exclude archived modalities"


# ---------------------------------------------------------------------------
# Corner queue B — endpoints
# ---------------------------------------------------------------------------
def test_superbill_billable_amount_equals_service_charge(api):
    """PRD §3.11: "On issue, the superbill denormalizes the patient's client_id from the
    appointment, sets billable_amount_cents equal to the appointment's service_charge_cents
    (gratuity and any membership discount are excluded from the claim), and starts in
    superbill_status ISSUED."

    A CASH Swedish-60 paid with gratuity 1500 yields a superbill with billable_amount_cents
    12000, the client denormalized, and status ISSUED.

    Design: Corner/endpoints/superbill_billable_amount_equals_service_charge
    """
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario(client_overrides={"hsa_balance_cents": 0})
    appt, _ = drive_to_paid(scn, gratuity_cents=1500,
                            start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    sb = validate_success(api.create_superbill(create_superbill_payload(appt["id"]), FRONT), expected_status=201)
    assert sb["billable_amount_cents"] == 12000
    assert sb["client_id"] == scn["client"]["id"]
    assert sb["superbill_status"] == "ISSUED"


def test_list_certifications_filtered_by_therapist(api):
    """PRD §2.9: "List endpoints support reverse lookup: ... certifications by therapist_id."

    Design: Corner/endpoints/list_certifications_filtered_by_therapist
    """
    validate_success(api.create_modality(
        {"name": "LymphCert", "code": "LYMPHCRT", "requires_certification": True,
         "base_price_cents": 11000}, ADMIN), expected_status=201)
    therapist = validate_success(api.create_therapist(
        {"full_name": "Cert T", "license_number": "LMT-989001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    cert = validate_success(api.create_certification(
        create_certification_payload(therapist["id"], "LYMPHCRT"), ADMIN), expected_status=201)
    data, _ = validate_paginated(api.list_certifications(ADMIN, params={"therapist_id": therapist["id"]}))
    matching = [c for c in data if c["id"] == cert["id"]]
    assert len(matching) == 1
    assert matching[0]["cert_status"] == "ACTIVE"
