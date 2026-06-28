"""Role-based access control, ownership enforcement, and table optimistic concurrency.

Covers corner queue B `rbac` and `cross_cutting_complexity_layers` section instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    bookable_scenario,
    book_appointment,
    create_draft_note,
    set_clock,
    create_appointment_payload,
    create_intake_payload,
    make_client_headers,
    make_therapist_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_frontdesk_cannot_create_modality(api):
    """PRD §2.1: "When the role and identity are present and well-formed but the role is not
    permitted to invoke the requested operation ... the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)." PRD §2.1: "A PracticeAdmin ... configures modalities."

    FrontDesk calling POST /practice/modalities (a PracticeAdmin operation) returns
    ERR_UNAUTHORIZED.

    Design: Corner/rbac/frontdesk_cannot_create_modality
    """
    validate_error(
        api.create_modality({"name": "Swedish RB", "code": "SWEDRB", "base_price_cents": 12000}, FRONT),
        ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_sign_others_intake(api):
    """PRD §2.1: "an entity-backed caller attempts to act on a resource it does not own — the
    request is rejected with ERR_UNAUTHORIZED (HTTP 403)." PRD §2.1: "A Client may sign only its
    own intake."

    Client B signing client A's intake returns ERR_UNAUTHORIZED; the intake stays DRAFT.

    Design: Corner/rbac/client_cannot_sign_others_intake
    """
    client_a = validate_success(api.create_client({"full_name": "Owner A", "email": "ownera@example.com"}, FRONT), expected_status=201)
    client_b = validate_success(api.create_client({"full_name": "Other B", "email": "otherb@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(create_intake_payload(client_a["id"]), FRONT), expected_status=201)
    validate_error(api.sign_intake(itk["id"], make_client_headers(client_b["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED.value)
    fetched = validate_success(api.get_intake(itk["id"], FRONT))
    assert fetched["intake_status"] == "DRAFT"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of the four roles defined below ... the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    validate_error(api.list_modalities({}), ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_therapist_cannot_finalize_others_note(api):
    """PRD §2.1: "only the therapist assigned to an appointment may finalize that appointment's
    clinical note." PRD §3.5: "Finalizing is permitted only while the note is DRAFT ... and only
    when the acting therapist is the one assigned to the appointment."

    A therapist who is not the appointment's assigned therapist gets ERR_UNAUTHORIZED on
    finalize; the note stays DRAFT.

    Design: Corner/rbac/therapist_cannot_finalize_others_note
    """
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario()
    other_t = validate_success(api.create_therapist(
        {"full_name": "Other T2", "license_number": "LMT-991002", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    appt = book_appointment(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    note = create_draft_note(appt["id"], scn["therapist"]["id"])
    validate_error(api.finalize_soap_note(note["id"], make_therapist_headers(other_t["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED.value)
    fetched = validate_success(api.get_soap_note(note["id"], make_therapist_headers(scn["therapist"]["id"])))
    assert fetched["note_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner queue B — cross_cutting_complexity_layers (OCC on Table.version)
# ---------------------------------------------------------------------------
def test_occ_stale_table_version_on_appointment_create(api):
    """PRD §2.8: "The server compares it to the table's current version; if they do not match —
    because a prior booking against that same table has since advanced the table's version ...
    the booking is rejected with ERR_STALE_VERSION (HTTP 412)." PRD §2.8: "A successful booking
    itself advances the table's version by 1."

    Booking A advances the table version; a second booking carrying the pre-A version is
    rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_table_version_on_appointment_create
    """
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario()
    therapist2 = validate_success(api.create_therapist(
        {"full_name": "T OC2", "license_number": "LMT-992002", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    stale_version = scn["table"]["version"]
    book_appointment(scn, expected_table_version=stale_version,
                     start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    # Second booking still carrying the stale version.
    payload = create_appointment_payload(
        scn["client"]["id"], therapist2["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], stale_version,
        start_at="2026-01-05T13:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_table_version_succeeds(api):
    """PRD §2.8: "the caller must re-read the table and retry with the fresh version." PRD §2.8:
    "A successful booking itself advances the table's version by 1, which is what makes it the
    concurrency anchor for the next writer."

    Re-reading the fresh table version after the first booking lets a non-overlapping second
    booking succeed.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_table_version_succeeds
    """
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario()
    therapist2 = validate_success(api.create_therapist(
        {"full_name": "T OK2", "license_number": "LMT-993002", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    book_appointment(scn, expected_table_version=scn["table"]["version"],
                     start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    fresh = validate_success(api.get_table(scn["table"]["id"], FRONT))
    payload = create_appointment_payload(
        scn["client"]["id"], therapist2["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-01-05T13:00:00Z", duration_minutes=60, payer="CASH")
    appt2 = validate_success(api.create_appointment(payload, FRONT), expected_status=201)
    assert appt2["scheduling_status"] == "SCHEDULED"
    assert appt2["settlement_status"] == "UNSETTLED"
