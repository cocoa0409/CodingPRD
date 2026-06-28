"""Corner coverage: entity creation/defaults/system-fields, listing envelope, and
state-machine invalid-transition / terminal-lockdown / side-effect / bubble-up behaviors."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    set_clock, create_patient, create_provider, create_encounter,
    setup_encounter_in_progress, setup_biopsy_in_state, setup_active_membership,
    setup_cosmetic_encounter_with_membership, redeem_treatment,
    setup_prior_authorization,
    assert_same_instant,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.test_users import make_provider_headers

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PATHLAB = TEST_USERS["path_lab_headers"]
ADMIN = TEST_USERS["practice_admin_headers"]
PROVIDER = TEST_USERS["provider_headers"]


# ---- entities section ----
def test_create_patient_minimal_required_fields(api):
    """PRD §3.2: "The `has_active_insurance` flag, defaulting to `false`, marks whether the
    patient carries billable insurance"
    PRD §3.2: "The `insurance_coinsurance_rate`, defaulting to `0.2`, is the fraction of the
    insurer-allowed remainder the patient owes"
    PRD §3.2: "The `insurance_deductible_remaining_cents`, defaulting to 0, is the patient's
    remaining unmet deductible in cents"
    PRD §3.2: "A patient also carries a computed `last_skin_check_at`, which starts null"

    Design: Corner/entities/create_patient_minimal_required_fields
    """
    pat = validate_success(api.create_patient(
        {"full_name": "New Pat", "date_of_birth": "1995-06-06"}, FRONT), 201)
    assert pat["has_active_insurance"] is False
    assert pat["insurance_coinsurance_rate"] == 0.2
    assert pat["insurance_deductible_remaining_cents"] == 0
    assert pat["last_skin_check_at"] is None
    assert pat["version"] == 1


def test_create_encounter_missing_required_field_rejected(api):
    """PRD §2.8: "A request whose body is malformed, is missing a required field, or carries
    an out-of-range enum value that is not otherwise covered by a more specific rule is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_encounter_missing_required_field_rejected
    """
    provider = create_provider(full_name="Dr Req")
    patient = create_patient(full_name="Req Pat", date_of_birth="1990-01-01")
    res = api.create_encounter({
        "patient_id": patient["id"], "provider_id": provider["id"],
        "scheduled_at": "2026-01-20T09:00:00Z",  # visit_type omitted
    }, FRONT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_biopsy_nonexistent_returns_not_found(api):
    """PRD §2.8: "The not-found error is resource-specific: an unresolved patient yields
    `ERR_PATIENT_NOT_FOUND`, a provider `ERR_PROVIDER_NOT_FOUND`, a room `ERR_ROOM_NOT_FOUND`,
    an encounter `ERR_ENCOUNTER_NOT_FOUND`, a biopsy `ERR_BIOPSY_NOT_FOUND`"

    Design: Corner/entities/get_biopsy_nonexistent_returns_not_found
    """
    res = api.get_biopsy(NON_EXISTENT_UUID, PROVIDER)
    validate_error(res, "ERR_BIOPSY_NOT_FOUND")


def test_encounter_system_fields_ignore_client_input(api):
    """PRD §3.3: "On creation the encounter's `clinical_status` is `SCHEDULED`, its
    `billing_status` is `BILLING_OPEN`, and its `open_biopsy_count` is 0."

    Design: Corner/entities/encounter_system_fields_ignore_client_input
    """
    provider = create_provider(full_name="Dr Sys")
    patient = create_patient(full_name="Sys Pat", date_of_birth="1990-02-02")
    enc = validate_success(api.create_encounter({
        "patient_id": patient["id"], "provider_id": provider["id"],
        "visit_type": "MEDICAL", "scheduled_at": "2026-01-20T10:00:00Z",
    }, FRONT), 201)
    assert enc["clinical_status"] == "SCHEDULED"
    assert enc["billing_status"] == "BILLING_OPEN"
    assert enc["open_biopsy_count"] == 0
    assert enc["version"] == 1


def test_cosmetic_encounter_pay_path_forced_cash(api):
    """PRD §2.9: "An encounter's own pay path is `INSURANCE` or `CASH`, defaulting for
    `MEDICAL` and `SKIN_CHECK` visits from the patient's `has_active_insurance` flag when
    omitted, and always forced to `CASH` for `COSMETIC` visits."

    Design: Corner/entities/cosmetic_encounter_pay_path_forced_cash
    """
    provider = create_provider(full_name="Dr Cash")
    patient = create_patient(full_name="Cash Pat2", date_of_birth="1990-03-03",
                             has_active_insurance=True)
    enc = validate_success(api.create_encounter({
        "patient_id": patient["id"], "provider_id": provider["id"],
        "visit_type": "COSMETIC", "scheduled_at": "2026-01-20T11:00:00Z",
        "pay_path": "INSURANCE",
    }, FRONT), 201)
    assert enc["pay_path"] == "CASH"


def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    create_patient(full_name="List Pat", date_of_birth="1990-04-04")
    data, meta = validate_paginated(api.list_patients(FRONT, params={"limit": 10, "offset": 0}))
    assert len(data) >= 1
    assert "total_count" in meta
    assert "has_more" in meta


# ---- state_machines section ----
def test_biopsy_send_to_lab_from_resulted_invalid(api):
    """PRD §3.5: "A `Provider` sends a specimen to the lab, moving `COLLECTED → AT_LAB`,
    permitted only from `COLLECTED` (otherwise `ERR_BIOPSY_BAD_STATE`)"

    Design: Corner/state_machines/biopsy_send_to_lab_from_resulted_invalid
    """
    provider, patient, enc, biopsy = setup_biopsy_in_state("RESULTED", result="BENIGN")
    prov_headers = make_provider_headers(provider["id"])
    res = api.send_biopsy_to_lab(biopsy["id"], prov_headers)
    validate_error(res, "ERR_BIOPSY_BAD_STATE")
    after = validate_success(api.get_biopsy(biopsy["id"], prov_headers), 200)
    assert after["status"] == "RESULTED"


def test_charge_pay_from_paid_terminal_locked(api):
    """PRD §3.7: "A `BillingSpecialist` may transition a charge `POSTED → PAID`, permitted
    only from `POSTED` (otherwise `ERR_CHARGE_BAD_STATE`); paying increments the charge's
    `version`."

    Design: Corner/state_machines/charge_pay_from_paid_terminal_locked
    """
    provider = create_provider(full_name="Dr Pay")
    patient = create_patient(full_name="Pay Pat", date_of_birth="1973-06-06")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-21T10:00:00Z")
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000,
    }, BILLING), 201)
    validate_success(api.pay_charge(ch["id"], BILLING), 200)
    res = api.pay_charge(ch["id"], BILLING)
    validate_error(res, "ERR_CHARGE_BAD_STATE")


def test_recall_sweep_fires_only_due_pending(api):
    """PRD §3.10: "A reminder reaches `SENT` only through the recall sweep, an administrative
    capability runnable by a `PracticeAdmin` or `FrontDesk` that fires all `PENDING`
    reminders whose `due_at` is at or before the clock's current time, transitioning each
    `PENDING → SENT` and incrementing each swept reminder's `version`; the sweep returns the
    swept reminders. A reminder whose `due_at` is still in the future is simply skipped by the
    sweep, not errored."

    Design: Corner/state_machines/recall_sweep_fires_only_due_pending
    """
    set_clock("2026-03-01T00:00:00Z")
    patient = create_patient(full_name="Swp Pat", date_of_birth="1960-07-07")
    due = validate_success(api.create_recall_reminder({
        "patient_id": patient["id"], "reason": "ROUTINE_SKIN_CHECK",
        "due_at": "2026-02-01T00:00:00Z",
    }, FRONT), 201)
    future = validate_success(api.create_recall_reminder({
        "patient_id": patient["id"], "reason": "ROUTINE_SKIN_CHECK",
        "due_at": "2027-01-01T00:00:00Z",
    }, FRONT), 201)
    validate_success(api.recall_sweep(ADMIN), 200)
    due_after = validate_success(api.get_recall_reminder(due["id"], FRONT), 200)
    future_after = validate_success(api.get_recall_reminder(future["id"], FRONT), 200)
    assert due_after["status"] == "SENT"
    assert future_after["status"] == "PENDING"


def test_skincheck_close_sets_last_skin_check_and_spawns_routine_recall(api):
    """PRD §3.2: "That same clinical-close event spawns a routine recall: a `RecallReminder`
    is created with `reason` of `ROUTINE_SKIN_CHECK`, a null `biopsy_id`, a `due_at` set to
    twelve months after the clock's current time, and a `status` of `PENDING`."
    PRD §3.2: "A patient also carries a computed `last_skin_check_at`, which starts null and
    is set to the clock's current time whenever one of the patient's `SKIN_CHECK` encounters
    is clinically closed."

    Design: Corner/state_machines/skincheck_close_sets_last_skin_check_and_spawns_routine_recall
    """
    set_clock("2026-04-01T00:00:00Z")
    provider, patient, enc = setup_encounter_in_progress(
        encounter_overrides={"visit_type": "SKIN_CHECK",
                             "scheduled_at": "2026-04-01T09:00:00Z"},
    )
    prov_headers = make_provider_headers(provider["id"])
    closed = validate_success(api.clinical_close_encounter(enc["id"], prov_headers), 200)
    assert closed["clinical_status"] == "CLINICALLY_CLOSED"

    pat_after = validate_success(api.get_patient(patient["id"], FRONT), 200)
    # PRD §3.2 pins last_skin_check_at to "the clock's current time" (the instant),
    # but does not pin its serialization (the three-fractional-digit rule covers only
    # created_at/updated_at/api_request_timestamp). Compare by instant.
    assert_same_instant(pat_after["last_skin_check_at"], "2026-04-01T00:00:00Z")

    data, _ = validate_paginated(
        api.list_recall_reminders(FRONT, params={"patient_id": patient["id"]}))
    routines = [r for r in data if r["reason"] == "ROUTINE_SKIN_CHECK"]
    assert len(routines) == 1
    r = routines[0]
    assert r["biopsy_id"] is None
    # due_at is "twelve months after the clock's current time" (instant pinned, format not).
    assert_same_instant(r["due_at"], "2027-04-01T00:00:00Z")
    assert r["status"] == "PENDING"


def test_pa_adjudicate_from_draft_invalid(api):
    """PRD §3.9: "A `BillingSpecialist` then adjudicates a submitted prior authorization by
    supplying a `decision`. When the decision is to approve, the prior authorization moves
    `SUBMITTED → APPROVED`; when the decision is to deny, it moves `SUBMITTED → DENIED`;
    either transition requires the current status to be `SUBMITTED` (otherwise
    `ERR_PA_BAD_STATE`) and increments the `version`."

    Design: Corner/state_machines/pa_adjudicate_from_draft_invalid
    """
    patient, pa = setup_prior_authorization(required_step_count=0, list_price_cents=50000)
    assert pa["status"] == "DRAFT"
    res = api.adjudicate_prior_authorization(pa["id"], {"decision": "APPROVE"}, BILLING)
    validate_error(res, "ERR_PA_BAD_STATE")


def test_open_biopsy_blocks_clinical_close(api):
    """PRD §3.3: "A `Provider` clinically closes the visit, moving
    `IN_PROGRESS → CLINICALLY_CLOSED`, permitted only from `IN_PROGRESS` (otherwise
    `ERR_ENCOUNTER_BAD_CLINICAL_STATE`) and only when `open_biopsy_count` is exactly 0, that
    is, no child biopsy remains in `COLLECTED` or `AT_LAB` (otherwise
    `ERR_OPEN_BIOPSY_BLOCKS_CLOSE`)."

    Design: Corner/state_machines/open_biopsy_blocks_clinical_close
    """
    provider, patient, enc, biopsy = setup_biopsy_in_state("COLLECTED")
    prov_headers = make_provider_headers(provider["id"])
    res = api.clinical_close_encounter(enc["id"], prov_headers)
    validate_error(res, "ERR_OPEN_BIOPSY_BLOCKS_CLOSE")
    enc_after = validate_success(api.get_encounter(enc["id"], FRONT), 200)
    assert enc_after["open_biopsy_count"] == 1


def test_membership_auto_exhausts_on_full_drain(api):
    """PRD §3.6: "If the debit leaves `unit_balance_cents` at exactly 0, the membership
    auto-transitions `ACTIVE → EXHAUSTED` as a bubble-up, which itself increments the
    membership's `version`."

    Design: Corner/state_machines/membership_auto_exhausts_on_full_drain
    """
    # SILVER purchased 9000 -> wallet 9000; list 10000 -> disc 9500, redeemed 9000, out 500.
    provider, patient, enc, mem = setup_cosmetic_encounter_with_membership(
        tier="SILVER", purchased_unit_cents=9000
    )
    t = redeem_treatment(enc["id"], mem["id"], mem["version"],
                         service_name="peel", list_price_cents=10000)
    assert t["redeemed_cents"] == 9000
    assert t["out_of_pocket_cents"] == 500
    mem_after = validate_success(api.get_cosmetic_membership(mem["id"], BILLING), 200)
    assert mem_after["unit_balance_cents"] == 0
    assert mem_after["status"] == "EXHAUSTED"
