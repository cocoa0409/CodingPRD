"""Versioned consent, the de-consent cascade, and the notifications it mints."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_notification,
    assert_same_instant,
    attach_consent_to,
    book_procedure,
    make_physician_headers,
    new_patient,
    new_physician,
    new_standing_order,
    patient_notifications,
    patient_version,
    publish_protocol,
    read_consent,
    read_lot,
    read_patient,
    read_procedure,
    record_consult,
    run_delinquency,
    set_clock,
    setup_notified_consent_requirement,
    setup_pellet_procedure,
    sign_consent,
    validate_error,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def _consented_testosterone_procedure(api):
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", prescribed_dose_mg=1150,
        room_code="RM6", scheduled_start="2026-05-25T09:00:00Z",
        patient_name="Pat Eight", patient_email="p8@example.com",
    )
    attach_consent_to(api, ctx["procedure_id"], ctx["consent"]["id"])
    return ctx


def test_protocol_publication_de_consents_the_procedure_and_notifies_the_patient(api):
    """PRD §3.2: "Hop two supersedes consent: every `ConsentRecord` for that hormone type
    whose `status` is `ACTIVE` moves `ACTIVE → SUPERSEDED`, incrementing its `version`. Hop
    three reaches the schedule: every procedure sitting in `CONSENTED` that holds one of the
    consents just superseded moves back `CONSENTED → SCHEDULED`, with its `consent_record_id`
    set to null and its `version` incremented — this is a cyclic leg, and a procedure may be
    consented, de-consented by a protocol bump, and consented again under the new version
    without limit. Hop four notifies: for each such procedure the server mints a
    `PatientNotification` with `notification_type` of `CONSENT_REQUIRED`, `status` `PENDING`,
    a `severity_class` of null because no recall is involved, a human-readable `message`, and
    a `due_at` seven days after the moment of creation; the patient's
    `open_notification_count` rises by 1 and their `version` increments."

    Design: Difficulty/non_linear_state_machine/procedure_consent_cycle_via_protocol_publication
    """
    ctx = _consented_testosterone_procedure(api)
    assert read_procedure(api, ctx["procedure_id"])["status"] == "CONSENTED"

    publish_protocol(api, ctx["physician_id"], "TESTOSTERONE", "T pellet protocol v2")

    assert read_consent(api, ctx["consent"]["id"])["status"] == "SUPERSEDED"
    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SCHEDULED"
    assert procedure["consent_record_id"] is None

    notes = patient_notifications(api, ctx["patient_id"])
    assert len(notes) == 1, f"Exactly one re-consent notification expected, got {len(notes)}"
    note = notes[0]
    assert note["notification_type"] == "CONSENT_REQUIRED"
    assert note["status"] == "PENDING"
    assert note["severity_class"] is None
    assert_same_instant(note["due_at"], "2026-05-08T00:00:00Z", "due_at")
    assert_notification(note)
    assert read_patient(api, ctx["patient_id"])["open_notification_count"] == 1


def test_procedure_re_enters_consented_under_the_new_protocol_version(api):
    """PRD §3.2: "Hop three reaches the schedule: every procedure sitting in `CONSENTED` that
    holds one of the consents just superseded moves back `CONSENTED → SCHEDULED`, with its
    `consent_record_id` set to null and its `version` incremented — this is a cyclic leg, and
    a procedure may be consented, de-consented by a protocol bump, and consented again under
    the new version without limit."
    PRD §3.2: "Attaching a consent to a booked procedure is what moves it
    `SCHEDULED → CONSENTED`, and is available to `FrontDesk`, `Physician` and `Patient`."

    Design: Difficulty/non_linear_state_machine/procedure_consent_cycle_via_protocol_publication
    """
    ctx = _consented_testosterone_procedure(api)

    second_protocol = publish_protocol(
        api, ctx["physician_id"], "TESTOSTERONE", "T pellet protocol v2"
    )
    assert second_protocol["protocol_version"] == 2

    fresh_consent = sign_consent(
        api, ctx["patient_id"], "TESTOSTERONE", protocol_version=2, consented_max_dose_mg=2000
    )
    attach_consent_to(api, ctx["procedure_id"], fresh_consent["id"])

    assert read_consent(api, fresh_consent["id"])["status"] == "ACTIVE"
    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "CONSENTED", "The same row occupies CONSENTED a second time"
    assert procedure["consent_record_id"] == fresh_consent["id"]


def _supply_opened_then_republished(api):
    ctx = setup_pellet_procedure(
        api, target_status="SUPPLY_OPENED", prescribed_dose_mg=1000,
        room_code="RM16", scheduled_start="2026-05-16T09:00:00Z",
        patient_name="Pat TwentyThree", patient_email="p23@example.com",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )
    publish_protocol(api, ctx["physician_id"], "TESTOSTERONE", "T pellet protocol v2")
    set_clock(api, "2026-05-16T09:00:00Z")
    return ctx


def test_perform_is_refused_when_the_attached_consent_was_superseded(api):
    """PRD §2.9: "**Rung 16** — the consent attached to the procedure exists, has status
    `ACTIVE`, belongs to the same patient, covers the same `hormone_type`, and its
    `protocol_version` equals the highest published protocol version for that hormone type; at
    perform time the procedure's `consent_record_id` must additionally be non-null and still
    `ACTIVE`. Applies to `POST /clinic/procedures/{id}/consent-attach`,
    `POST /clinic/procedures/{id}/open-supply` and `POST /clinic/procedures/{id}/perform`.
    Otherwise `ERR_CONSENT_REQUIRED` (409)."

    Design: Difficulty/cross_entity_state_dependency/perform_blocked_by_consent_superseded_by_protocol_publication
    """
    ctx = _supply_opened_then_republished(api)

    response = api.perform_procedure(
        ctx["procedure_id"],
        {
            "expected_patient_version": patient_version(api, ctx["patient_id"]),
            "pellets_wasted": 0,
        },
        make_physician_headers(ctx["physician_id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_REQUIRED.value)
    assert response.status_code == 409

    assert read_consent(api, ctx["consent"]["id"])["status"] == "SUPERSEDED"
    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["pellets_inserted"] == 0
    assert procedure["delivered_total_mg"] == 0
    assert read_patient(api, ctx["patient_id"])["cumulative_mg_testosterone"] == 0


def test_supply_opened_procedure_keeps_its_consent_reference_through_the_publication(api):
    """PRD §3.2: "Hop three reaches the schedule: every procedure sitting in `CONSENTED` that
    holds one of the consents just superseded moves back `CONSENTED → SCHEDULED`, with its
    `consent_record_id` set to null and its `version` incremented — this is a cyclic leg, and
    a procedure may be consented, de-consented by a protocol bump, and consented again under
    the new version without limit."
    PRD §3.5: "Opening the sterile tray moves the procedure `CONSENTED → SUPPLY_OPENED` and
    may be done by a `NurseInjector` or a `Physician`; when the actor is a nurse, the
    delegated-authority gate of §2.8 applies."

    Design: Difficulty/cross_entity_state_dependency/perform_blocked_by_consent_superseded_by_protocol_publication
    """
    ctx = _supply_opened_then_republished(api)

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SUPPLY_OPENED", (
        "Hop three only de-consents procedures sitting in CONSENTED"
    )
    assert procedure["consent_record_id"] == ctx["consent"]["id"]

    lot = read_lot(api, ctx["lots"]["T200-A"]["id"])
    assert lot["qty_reserved"] == 5
    assert lot["qty_consumed"] == 0

    assert patient_notifications(api, ctx["patient_id"]) == [], (
        "No procedure moved CONSENTED to SCHEDULED, so hop four mints nothing"
    )


def test_consent_ceiling_below_the_planned_dose_rejects_the_attach(api):
    """PRD §3.2: "Separately, the consent's `consented_max_dose_mg` must be at least the
    procedure's `planned_total_mg`; a consent that covers too little dose is rejected with
    `ERR_CONSENT_DOSE_EXCEEDED`."
    PRD §2.9: "**Rung 17** — the consent's `consented_max_dose_mg` is greater than or equal to
    the procedure's `planned_total_mg`, on `POST /clinic/procedures/{id}/consent-attach`.
    Otherwise `ERR_CONSENT_DOSE_EXCEEDED` (422)."

    Design: Corner/validations/consent_ceiling_below_planned_dose_rejects_the_attach
    """
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", prescribed_dose_mg=1150, consented_max_dose_mg=1000,
        room_code="RM49", scheduled_start="2026-06-16T09:00:00Z",
        patient_name="Corner TwentyFive", patient_email="c25@example.com",
    )
    assert ctx["procedure"]["planned_total_mg"] == 1200

    response = api.attach_consent(
        ctx["procedure_id"], {"consent_record_id": ctx["consent"]["id"]}, FRONT_DESK
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_DOSE_EXCEEDED.value)
    assert response.status_code == 422

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SCHEDULED"
    assert procedure["consent_record_id"] is None
    assert read_consent(api, ctx["consent"]["id"])["status"] == "ACTIVE"


def test_consent_pinned_to_a_superseded_protocol_version_cannot_be_attached(api):
    """PRD §3.2: "Five conditions must all hold: the procedure is in `SCHEDULED`; the
    referenced consent's `status` is `ACTIVE`; its `patient_id` matches the procedure's
    patient; its `hormone_type` matches the procedure's; and its `protocol_version` equals the
    highest protocol version published for that hormone type, failing which the answer is
    `ERR_CONSENT_REQUIRED`."

    Design: Corner/validations/consent_signed_under_a_superseded_protocol_version_is_refused
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner TwentySix", "c26@example.com")
    publish_protocol(api, physician["id"], "TESTOSTERONE", "T v1")
    publish_protocol(api, physician["id"], "TESTOSTERONE", "T v2")

    stale_consent = sign_consent(
        api, patient["id"], "TESTOSTERONE", protocol_version=1, consented_max_dose_mg=2000
    )
    consult = record_consult(api, patient["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])
    procedure = book_procedure(
        api, patient["id"], physician["id"], consult["id"], order["id"],
        room_code="RM50", scheduled_start="2026-06-17T09:00:00Z",
    )

    response = api.attach_consent(
        procedure["id"], {"consent_record_id": stale_consent["id"]}, FRONT_DESK
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_REQUIRED.value)
    assert response.status_code == 409

    still_active = read_consent(api, stale_consent["id"])
    assert still_active["status"] == "ACTIVE", "The rung reads the version, not merely the status"
    assert still_active["protocol_version"] == 1
    assert read_procedure(api, procedure["id"])["status"] == "SCHEDULED"


def test_acknowledging_a_notification_twice_reports_already_terminal(api):
    """PRD §3.8: "Acknowledgement by `FrontDesk` or by the `Patient` moves it
    `PENDING → ACKNOWLEDGED` or `OVERDUE → ACKNOWLEDGED`, stamps `acknowledged_at` from the
    logical clock, decrements the patient's `open_notification_count` by 1 and increments the
    patient's `version` by 1, and increments the notification's own `version`. `ACKNOWLEDGED`
    is terminal."
    PRD §2.9: "**Rung 11** — the target row is not already in a terminal state for the axis
    being moved, on every action endpoint."

    Design: Corner/state_machines/notification_acknowledged_twice_returns_already_terminal
    """
    ctx = setup_notified_consent_requirement(api, patient_email="c9@example.com")

    validate_success(api.acknowledge_notification(ctx["notification_id"], FRONT_DESK), 200)

    response = api.acknowledge_notification(ctx["notification_id"], FRONT_DESK)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert response.status_code == 409

    note = validate_success(api.get_notification(ctx["notification_id"], FRONT_DESK), 200)
    assert note["status"] == "ACKNOWLEDGED"
    assert note["notification_type"] == "CONSENT_REQUIRED"

    assert read_patient(api, ctx["patient_id"])["open_notification_count"] == 0, (
        "The counter is decremented exactly once"
    )
    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SCHEDULED"
    assert procedure["consent_record_id"] is None


def test_ops_run_ages_a_pending_notification_without_moving_the_counter(api):
    """PRD §3.9: "**Phase two ages notifications**, and begins only after phase one has
    completely finished. Taking notifications in ascending `created_at`, every one whose
    `status` is `PENDING` and whose `due_at` lies strictly before now moves
    `PENDING → OVERDUE` with its `version` incremented."
    PRD §3.8: "The patient's `open_notification_count` counts notifications in `PENDING` and
    `OVERDUE` together, so ageing a notification does not change it."

    Design: Corner/endpoints/delinquency_run_ages_pending_notifications_to_overdue
    """
    ctx = setup_notified_consent_requirement(api, patient_email="c37@example.com")
    assert_same_instant(ctx["notification"]["due_at"], "2026-05-08T00:00:00Z", "due_at")

    set_clock(api, "2026-05-09T00:00:00Z")
    run_delinquency(api)

    note = validate_success(api.get_notification(ctx["notification_id"], FRONT_DESK), 200)
    assert note["status"] == "OVERDUE"
    assert read_patient(api, ctx["patient_id"])["open_notification_count"] == 1
