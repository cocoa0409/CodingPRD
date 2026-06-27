"""Booking-gate ordering, cross-entity preconditions, and resource overlap semantics.

Covers difficulty queue A instances on validation-priority conflicts, cross-entity state
dependencies (complete-needs-finalized-note, check-in-needs-active-license), and the
table-buffer vs therapist-no-buffer overlap rules, plus corner queue B validation claims.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    bookable_scenario,
    book_appointment,
    create_draft_note,
    create_table,
    create_modality,
    set_clock,
    make_therapist_headers,
    create_appointment_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_consent_gate_beats_intake_gate(api):
    """PRD §3.4: "the domain gates fire in this order: first the consent gate
    (ERR_CONSENT_REQUIRED), ... then the intake gate (ERR_INTAKE_INVALID)." PRD §3.3: "The
    consent gate requires that the referenced consent be ACTIVE, that its draping_policy is not
    DECLINE_TREATMENT ... Any of these failing raises ERR_CONSENT_REQUIRED."

    A booking with a DECLINE_TREATMENT consent AND an expired intake surfaces the
    higher-priority ERR_CONSENT_REQUIRED.

    Design: Difficulty/priority_pair_validation_conflict/consent_safety_beats_contraindication_safety_vs_intake
    """
    set_clock("2026-03-02T08:00:00Z")
    modality = create_modality(name="SwedishPC", code="SWEDPC", base_price_cents=12000)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T PC", "license_number": "LMT-900001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C PC", "email": "cpc@example.com"}, FRONT), expected_status=201)
    # Intake that is ACTIVE but already expired.
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-03-02T07:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "DECLINE_TREATMENT"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-03-02T10:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_CONSENT_REQUIRED.value)


def test_decline_treatment_consent_alone_blocks_booking(api):
    """PRD §3.2: "A consent whose draping_policy is DECLINE_TREATMENT can never be used to
    book." PRD §3.3: "Any of these failing raises ERR_CONSENT_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/consent_safety_beats_contraindication_safety_vs_intake
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario(consent_overrides={"draping_policy": "DECLINE_TREATMENT"})
    fresh = validate_success(api.get_table(scn["table"]["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], scn["therapist"]["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-03-02T10:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_CONSENT_REQUIRED.value)


def test_state_check_beats_hsa_funds_gate_on_pay(api):
    """PRD §2.10: "then the state-machine precondition that the target is in a state from which
    the transition is legal (ERR_INVALID_STATE) ... Only after all of those pass are the
    domain-specific booking gates evaluated." PRD §3.9: "Payment of a priced session ... is
    allowed only while settlement_status is PRICED."

    Paying a COMPLETED-but-UNSETTLED HSA appointment with hsa_balance 0 returns ERR_INVALID_STATE
    (the state precondition), not ERR_INSUFFICIENT_HSA.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_vs_insufficient_hsa
    """
    from test_helpers import drive_to_completed
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario(client_overrides={"hsa_balance_cents": 0})
    appt, _ = drive_to_completed(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="HSA")
    # Not priced — pay must be rejected for state, before the HSA funds check.
    validate_error(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_unsettled_rejected_for_state(api):
    """PRD §3.9: "is allowed only while settlement_status is PRICED." PRD §2.10: "a wrong-state
    transition is reported before the booking's safety and fiscal gates are even consulted."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_vs_insufficient_hsa
    """
    from test_helpers import drive_to_completed
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario(client_overrides={"hsa_balance_cents": 0})
    appt, _ = drive_to_completed(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="HSA")
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["settlement_status"] == "UNSETTLED"
    validate_error(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_complete_requires_finalized_soapnote(api):
    """PRD §3.5: "A Therapist or FrontDesk operator completes the session, which is allowed only
    while scheduling_status is CHECKED_IN and only when a SOAP note for this appointment exists
    in FINALIZED or AMENDED status."

    A CHECKED_IN appointment whose SOAP note is still DRAFT cannot be completed; complete returns
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/complete_requires_finalized_soapnote
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    t_id = scn["therapist"]["id"]
    create_draft_note(appt["id"], t_id)  # left DRAFT
    validate_success(api.check_in_appointment(appt["id"], FRONT))
    validate_error(api.complete_appointment(appt["id"], make_therapist_headers(t_id)),
                   ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "CHECKED_IN"


def test_complete_succeeds_after_note_finalized(api):
    """PRD §3.5: "Completion advances scheduling_status from CHECKED_IN to COMPLETED." PRD §3.5:
    "only when a SOAP note for this appointment exists in FINALIZED or AMENDED status."

    Design: Difficulty/cross_entity_state_dependency/complete_requires_finalized_soapnote
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    t_id = scn["therapist"]["id"]
    th = make_therapist_headers(t_id)
    note = create_draft_note(appt["id"], t_id)
    validate_success(api.check_in_appointment(appt["id"], FRONT))
    validate_success(api.finalize_soap_note(note["id"], th))
    completed = validate_success(api.complete_appointment(appt["id"], th))
    assert completed["scheduling_status"] == "COMPLETED"


def test_checkin_requires_active_license(api):
    """PRD §3.5: "Check-in is allowed only while scheduling_status is SCHEDULED, only while the
    clock is strictly before the session's end_at ..., only while the assigned therapist's
    license is ACTIVE at the current clock, and only while the governing consent is still
    ACTIVE." PRD §3.3: "a lapsed license raises ERR_LICENSE_EXPIRED."

    A SCHEDULED appointment whose therapist's license has lapsed (clock advanced past
    license_expiry) cannot be checked in.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_active_license
    """
    set_clock("2026-03-02T08:00:00Z")
    modality = create_modality(name="SwedishCL", code="SWEDCL", base_price_cents=12000)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T CL", "license_number": "LMT-150001", "license_expiry": "2026-03-02T12:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C CL", "email": "ccl@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-03-02T13:00:00Z", duration_minutes=60, payer="CASH")
    appt = validate_success(api.create_appointment(payload, FRONT), expected_status=201)
    set_clock("2026-03-02T12:45:00Z")  # past license_expiry
    validate_error(api.check_in_appointment(appt["id"], FRONT), ApiErrorId.ERR_LICENSE_EXPIRED.value)
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "SCHEDULED"


def test_checkin_succeeds_while_license_active(api):
    """PRD §3.5: "A successful check-in advances scheduling_status from SCHEDULED to
    CHECKED_IN." PRD §3.5: "only while the assigned therapist's license is ACTIVE at the current
    clock."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_active_license
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario(therapist_overrides={"license_expiry": "2027-01-01T00:00:00Z"})
    appt = book_appointment(scn, start_at="2026-03-02T13:00:00Z", duration_minutes=60, payer="CASH")
    checked = validate_success(api.check_in_appointment(appt["id"], FRONT))
    assert checked["scheduling_status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_table_overlap_within_turnover_buffer_rejected(api):
    """PRD §3.4: "The table-overlap gate then checks the requested interval, extended by the
    table's turnover_buffer_minutes, against every non-terminal appointment already on that same
    table; if the buffered intervals are closer together than the buffer allows ... the booking
    is rejected with ERR_TABLE_DOUBLE_BOOKED."

    With a 15-minute buffer, a second booking starting 10 minutes after the first ends (gap 10 <
    15) collides.

    Design: Difficulty/resource_temporal_overlap/table_overlap_with_turnover_buffer
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario(table_overrides={"turnover_buffer_minutes": 15})
    therapist2 = validate_success(api.create_therapist(
        {"full_name": "T2 TB", "license_number": "LMT-160002", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    fresh = validate_success(api.get_table(scn["table"]["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], therapist2["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-03-02T10:10:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_TABLE_DOUBLE_BOOKED.value)


def test_table_booking_respecting_turnover_buffer_allowed(api):
    """PRD §3.4: "The table-overlap gate then checks the requested interval, extended by the
    table's turnover_buffer_minutes, against every non-terminal appointment already on that same
    table; if the buffered intervals are closer together than the buffer allows ... the booking
    is rejected with ERR_TABLE_DOUBLE_BOOKED." PRD §3.1: "two sessions whose intervals on this
    table sit closer together than this buffer collide."

    With a 15-minute buffer and a first session ending 10:00, a second booking starting 10:15
    (gap 15, not closer than the buffer) is allowed.

    Design: Difficulty/resource_temporal_overlap/table_overlap_with_turnover_buffer
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario(table_overrides={"turnover_buffer_minutes": 15})
    therapist2 = validate_success(api.create_therapist(
        {"full_name": "T2 TBok", "license_number": "LMT-160003", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    fresh = validate_success(api.get_table(scn["table"]["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], therapist2["id"], scn["table"]["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-03-02T10:15:00Z", duration_minutes=60, payer="CASH")
    appt2 = validate_success(api.create_appointment(payload, FRONT), expected_status=201)
    assert appt2["scheduling_status"] == "SCHEDULED"


def test_therapist_overlap_true_overlap_rejected(api):
    """PRD §3.4: "The therapist-overlap gate finally checks the requested interval against every
    other non-terminal appointment for the same therapist; here there is no buffer and the
    comparison is on the closed interval, so two sessions that merely touch end-to-start are
    allowed, but any genuine overlap raises ERR_THERAPIST_DOUBLE_BOOKED."

    The same therapist booked 09:00-10:00 on table X cannot also be booked 09:30 on table Y.

    Design: Difficulty/resource_temporal_overlap/therapist_overlap_no_buffer_adjacency_allowed
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    tableY = create_table()
    book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    fresh = validate_success(api.get_table(tableY["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], scn["therapist"]["id"], tableY["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-03-02T09:30:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value)


def test_therapist_back_to_back_touching_allowed(api):
    """PRD §3.4: "so two sessions that merely touch end-to-start are allowed, but any genuine
    overlap raises ERR_THERAPIST_DOUBLE_BOOKED."

    The same therapist booked 09:00-10:00 on table X may also be booked starting exactly 10:00
    on table Y — the closed intervals only touch.

    Design: Difficulty/resource_temporal_overlap/therapist_overlap_no_buffer_adjacency_allowed
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    tableY = create_table()
    book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    fresh = validate_success(api.get_table(tableY["id"], ADMIN))
    payload = create_appointment_payload(
        scn["client"]["id"], scn["therapist"]["id"], tableY["id"],
        scn["modality"]["id"], scn["consent"]["id"], fresh["version"],
        start_at="2026-03-02T10:00:00Z", duration_minutes=60, payer="CASH")
    appt2 = validate_success(api.create_appointment(payload, FRONT), expected_status=201)
    assert appt2["scheduling_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner queue B — validations
# ---------------------------------------------------------------------------
def test_contraindication_blocks_without_clearing_note(api):
    """PRD §3.3: "The contraindication gate compares the modality's contraindication_tags
    against the client's currently ACTIVE intake's risk_flags. For each tag present in both,
    there must exist a finalized clinical note ... that has cleared that tag for this client; if
    any matching tag lacks such a clearing note, booking is blocked with ERR_CONTRAINDICATION."

    Design: Corner/validations/contraindication_blocks_without_clearing_note
    """
    set_clock("2026-01-05T07:00:00Z")
    modality = create_modality(name="DeepTissueCI", code="DEEPTCI", base_price_cents=15000,
                               contraindication_tags=["PREGNANCY"])
    therapist = validate_success(api.create_therapist(
        {"full_name": "T CI", "license_number": "LMT-980001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C CI", "email": "cci@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "risk_flags": ["PREGNANCY"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE", "sensitive_area_consent": True}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_CONTRAINDICATION.value)


def test_license_expired_blocks_booking(api):
    """PRD §3.3: "The license gate requires the assigned therapist's license_status to be ACTIVE
    — equivalently, license_expiry strictly after the clock — and it is enforced both at booking
    and at check-in; a lapsed license raises ERR_LICENSE_EXPIRED."

    Design: Corner/validations/license_expired_blocks_booking
    """
    set_clock("2026-06-01T00:00:00Z")
    modality = create_modality(name="SwedishLE", code="SWEDLE", base_price_cents=12000)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T LE", "license_number": "LMT-981001", "license_expiry": "2026-05-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C LE", "email": "cle@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-06-02T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_LICENSE_EXPIRED.value)


def test_certification_required_blocks_booking(api):
    """PRD §3.3: "The certification gate applies only when the chosen modality has
    requires_certification true: the assigned therapist must then hold a TherapistCertification
    whose modality_code matches the modality's code and whose cert_status is ACTIVE. Absent such
    a certification, booking is blocked with ERR_CERTIFICATION_REQUIRED."

    Design: Corner/validations/certification_required_blocks_booking
    """
    set_clock("2026-01-05T07:00:00Z")
    modality = create_modality(name="LymphaticNC", code="LYMPHNC", base_price_cents=11000,
                               requires_certification=True)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T NC", "license_number": "LMT-982001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C NC", "email": "cnc@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_CERTIFICATION_REQUIRED.value)


def test_prenatal_table_unsuitable(api):
    """PRD §3.4: "The table-suitability gate rejects a PRENATAL modality on a table whose
    supports_prenatal is false, and rejects any booking onto an archived table, with
    ERR_TABLE_UNSUITABLE."

    Design: Corner/validations/prenatal_table_unsuitable
    """
    set_clock("2026-01-05T07:00:00Z")
    modality = create_modality(name="PrenatalTU", code="PRENATAL", base_price_cents=13000)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T PN", "license_number": "LMT-983001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table(supports_prenatal=False)
    client = validate_success(api.create_client({"full_name": "C PN", "email": "cpn@example.com"}, FRONT), expected_status=201)
    itk = validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)
    validate_success(api.sign_intake(itk["id"], FRONT))
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_TABLE_UNSUITABLE.value)


def test_intake_invalid_when_unsigned(api):
    """PRD §3.3: "The intake gate requires the client to have an intake that is ACTIVE and whose
    expires_at is strictly after the clock; failing this raises ERR_INTAKE_INVALID." PRD §3.2:
    "Only an intake that is currently ACTIVE ... satisfies the booking precondition."

    A client whose only intake is still DRAFT (never signed) cannot be booked.

    Design: Corner/validations/intake_invalid_when_unsigned
    """
    set_clock("2026-01-05T07:00:00Z")
    modality = create_modality(name="SwedishIN", code="SWEDIN", base_price_cents=12000)
    therapist = validate_success(api.create_therapist(
        {"full_name": "T IN", "license_number": "LMT-984001", "license_expiry": "2027-01-01T00:00:00Z"}, ADMIN), expected_status=201)
    table = create_table()
    client = validate_success(api.create_client({"full_name": "C IN", "email": "cin@example.com"}, FRONT), expected_status=201)
    validate_success(api.create_intake(
        {"client_id": client["id"], "expires_at": "2026-12-31T00:00:00Z"}, FRONT), expected_status=201)  # left DRAFT
    consent = validate_success(api.create_consent(
        {"client_id": client["id"], "draping_policy": "FULL_DRAPE"}, FRONT), expected_status=201)
    fresh = validate_success(api.get_table(table["id"], ADMIN))
    payload = create_appointment_payload(
        client["id"], therapist["id"], table["id"], modality["id"], consent["id"], fresh["version"],
        start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    validate_error(api.create_appointment(payload, FRONT), ApiErrorId.ERR_INTAKE_INVALID.value)


def test_superbill_not_billable_for_membership(api):
    """PRD §3.11: "The issuing superbill gate requires that the appointment's settlement_status
    is PAID and that its payer is not MEMBERSHIP — membership-redeemed sessions are not
    insurance-billable — and a request that violates either condition is rejected with
    ERR_NOT_BILLABLE."

    Design: Corner/validations/superbill_not_billable_for_membership
    """
    from test_helpers import drive_to_paid, create_plan, create_package, create_superbill_payload
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="SBPlanMem", monthly_fee_cents=9000, included_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"])
    appt, _ = drive_to_paid(scn, gratuity_cents=0, package_id=pkg["id"],
                            start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    validate_error(api.create_superbill(create_superbill_payload(appt["id"]), FRONT),
                   ApiErrorId.ERR_NOT_BILLABLE.value)
