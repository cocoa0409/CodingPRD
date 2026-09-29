"""
State-machine corners: entry states, valid transitions and their side effects,
undeclared triggers on terminal rows, conditional cascades and one closed cycle.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_EFFICACY_FAILURE_UNRESOLVED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PLACEMENT_NOT_INSTALLED,
    ERR_VISIT_NOT_IN_PROGRESS,
)
from test_helpers.assertions import (
    assert_alert,
    assert_axes,
    assert_cents,
    assert_equipment_ledger,
    assert_instant_equals,
    assert_pct,
    assert_sweep_counters,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    AGREEMENT_ACTIVE,
    AGREEMENT_DRAFT,
    AGREEMENT_EXPIRED,
    AGREEMENT_TERMINATED,
    ALERT_ACKNOWLEDGED,
    ALERT_LOW_RINSE_PRESSURE,
    ALERT_OPEN,
    DECISION_VERIFIED,
    DISPENSER_ACTIVE,
    DISPENSER_LOCKED_OUT,
    EFFICACY_FAIL,
    EFFICACY_PASS,
    LOCKOUT_AGREEMENT_ENDED,
    LOCKOUT_EFFICACY_FAILURE,
    OP_DEGRADED,
    OP_DOWN,
    OP_OFFLINE,
    OP_UP,
    ORIGIN_CUSTOMER_REPORT,
    PLACEMENT_INSTALLED,
    PLACEMENT_PENDING_INSTALL,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    PLACEMENT_RETRIEVED,
    POSTURE_CRITICAL,
    POSTURE_ELEVATED,
    POSTURE_NORMAL,
    SEVERITY_WARNING,
    SYMPTOM_LOW_TEMP,
    SYMPTOM_MACHINE_DOWN,
    SYMPTOM_RACK_QUALITY,
    TICKET_CANCELLED,
    TICKET_CLOSED,
    TICKET_ON_SITE,
    TICKET_QUEUED,
    TIER_PREMIUM,
    VERDICT_FAIL,
    VERDICT_PASS,
    VISIT_IN_PROGRESS,
    VISIT_SCHEDULED,
    VISIT_SUBMITTED,
    VISIT_VERIFIED,
)


def test_activation_derives_the_term_end_and_lifts_the_account_counter(api):
    """
    Activation is the only writer of term_end_date: 2026-08-01 plus 36 calendar
    months is 2029-08-01 on the same day of month, not a 30-day multiple. The same
    request raises the account's live-agreement counter to one and the agreement's
    own version to two, while leaving the renewal and termination fields alone.

    PRD §3.2: "Activation is also where `term_end_date` is computed: the
    `start_date` advanced by `minimum_term_months` calendar months, keeping the same
    day of month, and clamping to the last day of the target month when the source
    day does not exist there — a term of one month starting on 31 January ends on
    28 February in a common year."

    Design: Corner/state_machines/agreement_activation_computes_term_end_and_lifts_customer_count
    """
    customer = X.create_customer(api)
    detergent = X.create_detergent(api)
    draft = X.create_draft_agreement(api, customer["id"], [detergent["id"]])
    assert draft["status"] == AGREEMENT_DRAFT
    assert draft["version"] == 1
    assert draft["term_end_date"] is None

    activated = X.activate_agreement(api, draft["id"])
    assert activated["status"] == AGREEMENT_ACTIVE
    assert activated["term_end_date"] == "2029-08-01"
    assert activated["version"] == 2
    assert activated["renewal_count"] == 0
    assert activated["early_termination_fee_cents"] is None
    assert activated["termination_effective_date"] is None

    holder = get_success_data(api.get_customer(customer["id"], ACCOUNT_MANAGER_HEADERS))
    assert holder["active_agreement_count"] == 1


def test_installing_under_a_terminated_agreement_reports_the_agreement_rule(api):
    """
    The placement itself is still PENDING_INSTALL, so its own precondition holds;
    what fails is the cross-entity requirement that the financing agreement still be
    live, and the refusal names that rule rather than the generic transition error.
    The same terminate also pins the fee at the larger of the two recovery theories,
    493333 cents from the unamortized-equipment view.

    PRD §3.3: "It requires the placement to be in `PENDING_INSTALL`, the financing
    agreement to still be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`), and the
    site to be `ACTIVE`."

    Design: Corner/state_machines/install_of_a_pending_placement_after_termination_reports_agreement_not_active
    """
    base = X.program_base(api)
    placement = X.create_placement(api, base, asset_tag="AT-C01")
    assert_axes(placement, placement_status=PLACEMENT_PENDING_INSTALL)

    terminated = validate_success(
        api.terminate_service_agreement(
            base["agreement_id"],
            F.terminate_payload(effective_date="2026-08-01"),
            ACCOUNT_MANAGER_HEADERS,
        )
    )
    assert terminated["status"] == AGREEMENT_TERMINATED
    assert terminated["termination_effective_date"] == "2026-08-01"
    assert_cents(terminated["early_termination_fee_cents"], 493333)

    validate_error(
        api.install_machine_placement(placement["id"], base["technician_headers"]),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    unchanged = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        unchanged,
        placement_status=PLACEMENT_PENDING_INSTALL,
        operational_status=OP_UP,
    )
    assert unchanged["installed_at"] is None


def _placement_with_one_low_pressure_alert(api):
    """
    One INSTALLED DT-88 whose single DEVICE sample reports 14 psi against a 15 psi
    minimum — inside the 3 psi critical margin, so the breach is a WARNING — which
    opens one LOW_RINSE_PRESSURE alert and drives the health axis to DEGRADED.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")

    reading = X.ingest_reading(
        api, placement["id"], "2026-08-01T00:00:00Z", 30, rinse_pressure_psi=14
    )
    assert reading["triggered_alert_types"] == [ALERT_LOW_RINSE_PRESSURE]

    alerts = X.list_alerts_for_placement(api, placement["id"])
    assert len(alerts) == 1
    alert = alerts[0]
    assert_alert(alert)
    assert alert["alert_type"] == ALERT_LOW_RINSE_PRESSURE
    assert alert["severity"] == SEVERITY_WARNING
    assert alert["measured_value"] == pytest.approx(14, abs=0.01)
    assert alert["status"] == ALERT_OPEN

    base.update(
        {
            "placement_id": placement["id"],
            "alert": alert,
            "alert_id": alert["id"],
        }
    )
    return base


def test_acknowledging_an_alert_stamps_the_actor_without_closing_it(api):
    """
    Acknowledgement is bookkeeping: the acting engineer's identity is recorded and
    the alert's version advances, but the alert still counts as open and the machine
    is still DEGRADED — nothing about the breach has been repaired.

    PRD §3.4: "Acknowledgement is bookkeeping only: it does not clear the alert,
    does not change the placement's health axis, does not stop the alert from feeding
    the dispatch score, and leaves `open_alert_count` unchanged, because that counter
    treats `OPEN` and `ACKNOWLEDGED` alike."

    Design: Corner/state_machines/alert_acknowledgement_stamps_the_actor_and_keeps_the_alert_open
    """
    base = _placement_with_one_low_pressure_alert(api)

    acknowledged = validate_success(
        api.acknowledge_telemetry_alert(base["alert_id"], base["technician_headers"])
    )
    assert acknowledged["status"] == ALERT_ACKNOWLEDGED
    assert acknowledged["acknowledged_by_user_id"] == base["technician_id"]
    assert acknowledged["version"] == base["alert"]["version"] + 1

    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], base["technician_headers"])
    )
    assert placement["open_alert_count"] == 1
    assert_axes(placement, operational_status=OP_DEGRADED)


def test_a_second_acknowledgement_is_refused_and_keeps_the_first_actor(api):
    """
    The acknowledge trigger is declared only from OPEN, so a second attempt — here
    by a different engineer — is an undeclared transition rather than a silent
    no-op, and the first engineer's identity survives untouched with no version bump.

    PRD §2.8: "9. **State legality** — the addressed row must be in a state from
    which the requested action is declared. The generic failure is
    `ERR_INVALID_STATE_TRANSITION` (409)"

    Design: Corner/state_machines/acknowledging_the_same_alert_twice_is_rejected
    """
    base = _placement_with_one_low_pressure_alert(api)
    second_engineer = X.create_technician(api, name="Dara Okoye")
    second_headers = make_technician_headers(second_engineer["id"])

    first = validate_success(
        api.acknowledge_telemetry_alert(base["alert_id"], base["technician_headers"])
    )

    validate_error(
        api.acknowledge_telemetry_alert(base["alert_id"], second_headers),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    alert = get_success_data(api.get_telemetry_alert(base["alert_id"], second_headers))
    assert alert["status"] == ALERT_ACKNOWLEDGED
    assert alert["acknowledged_by_user_id"] == base["technician_id"]
    assert alert["version"] == first["version"]


def test_a_retrieved_machine_refuses_every_further_trigger(api):
    """
    Both axes are terminal once the machine has physically left, and each refused
    trigger reports the rule its own endpoint declares: two lifecycle triggers give
    the generic transition error while telemetry ingest gives the placement-specific
    one, and no reading is ever stored.

    PRD §3.3: "Installing a machine does not touch its health axis; a machine going
    down does not change its placement status; both `RETRIEVED` and `CANCELLED` are
    terminal on the lifecycle axis and `OFFLINE` is terminal on the health axis."

    Design: Corner/state_machines/a_retrieved_placement_rejects_every_further_trigger
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")

    scheduled = validate_success(
        api.create_retrieval_order(
            placement["id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-01"),
        )
    )
    assert_axes(scheduled, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)
    assert scheduled["retrieval_due_date"] == "2026-09-01"

    retrieved = validate_success(
        api.complete_retrieval(placement["id"], base["technician_headers"])
    )
    assert_axes(
        retrieved,
        placement_status=PLACEMENT_RETRIEVED,
        operational_status=OP_OFFLINE,
    )
    assert_instant_equals(retrieved["retrieved_at"], "2026-08-01T00:00:00Z", "retrieved_at")

    validate_error(
        api.complete_retrieval(placement["id"], base["technician_headers"]),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.install_machine_placement(placement["id"], base["technician_headers"]),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.create_telemetry_reading(
            placement["id"],
            F.telemetry_reading_payload("2026-08-01T00:00:00Z", 5),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_PLACEMENT_NOT_INSTALLED,
        409,
    )

    assert X.list_readings_for_placement(api, placement["id"]) == []


def test_every_new_row_lands_on_its_own_declared_entry_state(api):
    """
    One chain walks five entry points: a fresh agreement is DRAFT, a fresh placement
    is PENDING_INSTALL on the lifecycle axis while independently UP on the health
    axis, a fresh dispenser is ACTIVE, a fresh ticket is QUEUED with no engineer and
    no breach, and a fresh visit is SCHEDULED with no arrival and no evidence.

    PRD §3.6: "A booked visit begins with `visit_status` `SCHEDULED`, `arrival_at`
    null, `calibration_record_count` 0, `repair_confirmed` false, and
    `rejection_reason` and `verified_by_user_id` both null."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    base = X.program_base(api, activate=False)
    assert base["agreement"]["status"] == AGREEMENT_DRAFT

    X.set_clock(api, "2026-08-01T10:00:00Z")
    X.activate_agreement(api, base["agreement_id"])

    placement = X.create_placement(api, base, asset_tag="AT-C01")
    assert_axes(
        placement,
        placement_status=PLACEMENT_PENDING_INSTALL,
        operational_status=OP_UP,
    )

    X.install_placement(api, base, placement["id"])
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    assert dispenser["dispenser_status"] == DISPENSER_ACTIVE

    ticket = X.file_ticket(
        api, base, placement["id"], reported_symptom=SYMPTOM_RACK_QUALITY
    )
    assert ticket["status"] == TICKET_QUEUED
    assert ticket["origin"] == ORIGIN_CUSTOMER_REPORT
    assert ticket["alert_id"] is None
    assert ticket["assigned_technician_id"] is None
    assert ticket["sla_breached"] is False
    assert ticket["escalation_level"] == 0

    X.dispatch_ticket(api, ticket["id"])
    visit = X.book_visit(
        api,
        base,
        ticket["id"],
        scheduled_start_at="2026-08-01T11:00:00Z",
        scheduled_end_at="2026-08-01T12:00:00Z",
    )
    assert visit["visit_status"] == VISIT_SCHEDULED
    assert visit["arrival_at"] is None
    assert visit["calibration_record_count"] == 0
    assert visit["repair_confirmed"] is False
    assert visit["rejection_reason"] is None
    assert visit["verified_by_user_id"] is None


def test_the_visit_ladder_refuses_both_out_of_order_hops(api):
    """
    From SCHEDULED the only declared trigger is arrival, so submitting is an
    undeclared transition while attaching evidence is refused by the calibration
    endpoint's own rule — two different codes for the same underlying state. Once the
    visit is IN_PROGRESS, verifying is undeclared in turn, and the visit still holds
    no evidence and no verifier.

    PRD §3.6: "While a visit is `IN_PROGRESS` — and only then, with any other
    `visit_status` refused as `ERR_VISIT_NOT_IN_PROGRESS` — the engineer records one
    `CalibrationRecord` per dispenser measured."

    Design: Corner/state_machines/visit_submit_before_arrival_and_verify_before_submit_are_rejected
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    ticket = X.file_ticket(api, base, placement["id"])
    X.dispatch_ticket(api, ticket["id"])
    visit = X.book_visit(api, base, ticket["id"])
    assert visit["visit_status"] == VISIT_SCHEDULED

    validate_error(
        api.submit_service_visit(
            visit["id"], base["technician_headers"], F.submit_visit_payload(True)
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.create_calibration_record(
            visit["id"],
            F.calibration_record_payload(
                dispenser["id"], 1200, 8.00, dispenser["version"]
            ),
            base["technician_headers"],
        ),
        ERR_VISIT_NOT_IN_PROGRESS,
        409,
    )

    arrived = X.arrive_visit(api, base, visit["id"])
    assert arrived["visit_status"] == VISIT_IN_PROGRESS
    on_site = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert on_site["status"] == TICKET_ON_SITE

    validate_error(
        api.verify_service_visit(
            visit["id"], F.verify_visit_payload(DECISION_VERIFIED), AUDITOR_1_HEADERS
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    still_open = get_success_data(
        api.get_service_visit(visit["id"], base["technician_headers"])
    )
    assert still_open["visit_status"] == VISIT_IN_PROGRESS
    assert still_open["calibration_record_count"] == 0
    assert still_open["verified_by_user_id"] is None


def test_the_expiry_cascade_sweeps_only_the_installed_child(api):
    """
    Two machines hang off one expiring agreement and only the installed one is swept
    into RETRIEVAL_SCHEDULED with a 30-day due date; its never-installed sibling keeps
    its state, its null due date and its healthy axis. The jump lands exactly on the
    term end, so the renewal hop is skipped and the equipment ledger, which counts
    both machines, does not move at all.

    PRD §2.10: "2. Caused by the agreement leaving live status: every placement of
    this agreement whose `placement_status` is `INSTALLED` transitions `INSTALLED →
    RETRIEVAL_SCHEDULED`, processed in placement `created_at` ascending order, with
    `retrieval_due_date` set to the current clock's date plus 30 days."

    Design: Corner/state_machines/agreement_expiry_cascade_skips_pending_install_placements
    """
    base = X.program_base(
        api,
        agreement_overrides={"minimum_term_months": 1, "renewal_notice_days": 5},
    )
    assert base["agreement"]["term_end_date"] == "2026-09-01"

    installed = X.create_placement(api, base, asset_tag="AT-C01")
    pending = X.create_placement(api, base, asset_tag="AT-C02")
    X.install_placement(api, base, installed["id"])
    dispenser = X.fit_dispenser(api, base, installed["id"], dose=8.00)

    sweep = X.set_clock(api, "2026-09-01T00:00:00Z")
    assert_sweep_counters(
        sweep,
        agreements_moved_to_renewal_pending=0,
        agreements_expired=1,
        tickets_escalated=0,
    )

    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["status"] == AGREEMENT_EXPIRED

    swept = get_success_data(
        api.get_machine_placement(installed["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(swept, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)
    assert swept["retrieval_due_date"] == "2026-10-01"

    skipped = get_success_data(
        api.get_machine_placement(pending["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        skipped,
        placement_status=PLACEMENT_PENDING_INSTALL,
        operational_status=OP_UP,
    )
    assert skipped["retrieval_due_date"] is None

    locked = get_success_data(
        api.get_dispenser(dispenser["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert locked["dispenser_status"] == DISPENSER_LOCKED_OUT
    assert locked["lockout_reason"] == LOCKOUT_AGREEMENT_ENDED

    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 960000)
    assert customer["active_agreement_count"] == 0


def test_site_posture_is_re_derived_downward_when_the_backlog_clears(api):
    """
    Posture is recomputed from the whole open-ticket mix rather than latched at its
    worst value: a 520-point report makes the kitchen ELEVATED, an 800-point report
    pushes it to CRITICAL, and cancelling both by raising a retrieval order takes it
    all the way back to NORMAL with an empty backlog.

    PRD §3.1: "`service_posture` grades that backlog into one of three values,
    evaluated in this order: it is `CRITICAL` when at least one of those open tickets
    carries a `priority_score` of 700 or more; otherwise it is `ELEVATED` when at
    least one such open ticket exists at all; otherwise it is `NORMAL`."

    Design: Corner/state_machines/site_posture_returns_to_normal_when_every_open_ticket_reaches_a_terminal_state
    """
    base = X.program_base(api, site_overrides={"priority_tier": TIER_PREMIUM})
    assert base["site"]["service_posture"] == POSTURE_NORMAL
    assert base["site"]["open_ticket_count"] == 0

    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    X.set_clock(api, "2026-08-01T14:00:00Z")

    first = X.file_ticket(
        api, base, placement["id"], reported_symptom=SYMPTOM_MACHINE_DOWN
    )
    assert first["priority_score"] == 520
    assert first["response_deadline_at"] == "2026-08-01T18:00:00Z"

    elevated = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert elevated["service_posture"] == POSTURE_ELEVATED
    assert elevated["open_ticket_count"] == 1

    second = X.file_ticket(
        api, base, placement["id"], reported_symptom=SYMPTOM_LOW_TEMP
    )
    assert second["priority_score"] == 800
    assert second["response_deadline_at"] == "2026-08-01T16:00:00Z"
    assert second["requires_sanitation_cert"] is True

    critical = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert critical["service_posture"] == POSTURE_CRITICAL
    assert critical["open_ticket_count"] == 2

    scheduled = validate_success(
        api.create_retrieval_order(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(scheduled, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)

    for ticket_id in (first["id"], second["id"]):
        cancelled = get_success_data(
            api.get_service_ticket(ticket_id, ACCOUNT_MANAGER_HEADERS)
        )
        assert cancelled["status"] == TICKET_CANCELLED

    back_to_normal = get_success_data(
        api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert back_to_normal["service_posture"] == POSTURE_NORMAL
    assert back_to_normal["open_ticket_count"] == 0


def test_an_efficacy_lockout_is_cleared_only_by_a_later_pass_and_a_verify(api):
    """
    The sanitizer feed walks ACTIVE to LOCKED_OUT and back inside one visit. The
    failing record's drift is exactly 0.00, so the FAIL comes from the contact-time
    breach and not from any concentration threshold; the lockout blocks submission
    but not further titration; and the loop closes only once a later PASS on the same
    feed is carried by a verified visit, with the dispenser updated from that last
    record.

    PRD §3.4: "A dispenser locked out for `EFFICACY_FAILURE` returns `LOCKED_OUT →
    ACTIVE`, with `lockout_reason` cleared to null and its `version` incremented, when
    a later calibration on that dispenser achieves an efficacy pass inside a visit
    that is subsequently verified — that is the entire recovery path, and it closes
    the `ACTIVE → LOCKED_OUT → ACTIVE` cycle."

    Design: Corner/state_machines/dispenser_efficacy_lockout_and_recovery_close_the_active_locked_active_loop
    """
    base = X.program_base(api, with_sanitizer=True)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(
        api, base, placement["id"], product_id=base["sanitizer_id"], dose=2.00
    )
    assert dispenser["dispenser_status"] == DISPENSER_ACTIVE

    X.set_clock(api, "2026-08-01T10:00:00Z")
    ticket = X.file_ticket(api, base, placement["id"])
    assert ticket["priority_score"] == 100
    assert ticket["response_deadline_at"] == "2026-08-01T18:00:00Z"

    X.dispatch_ticket(api, ticket["id"])
    visit = X.book_visit(
        api,
        base,
        ticket["id"],
        scheduled_start_at="2026-08-01T10:30:00Z",
        scheduled_end_at="2026-08-01T11:30:00Z",
    )
    X.arrive_visit(api, base, visit["id"])

    failing = X.record_calibration(
        api,
        base,
        visit["id"],
        dispenser["id"],
        measured_ppm=200,
        measured_dose_ml_per_rack=2.00,
        contact_seconds=5,
    )
    assert_pct(failing["drift_pct"], 0.00)
    assert failing["efficacy_result"] == EFFICACY_FAIL
    assert failing["calibration_verdict"] == VERDICT_FAIL

    locked = get_success_data(
        api.get_dispenser(dispenser["id"], base["technician_headers"])
    )
    assert locked["dispenser_status"] == DISPENSER_LOCKED_OUT
    assert locked["lockout_reason"] == LOCKOUT_EFFICACY_FAILURE
    down = get_success_data(
        api.get_machine_placement(placement["id"], base["technician_headers"])
    )
    assert_axes(down, operational_status=OP_DOWN)

    validate_error(
        api.submit_service_visit(
            visit["id"], base["technician_headers"], F.submit_visit_payload(True)
        ),
        ERR_EFFICACY_FAILURE_UNRESOLVED,
        409,
    )

    passing = X.record_calibration(
        api,
        base,
        visit["id"],
        dispenser["id"],
        measured_ppm=200,
        measured_dose_ml_per_rack=2.00,
        contact_seconds=10,
    )
    assert passing["efficacy_result"] == EFFICACY_PASS
    assert_pct(passing["drift_pct"], 0.00)
    assert passing["calibration_verdict"] == VERDICT_PASS

    submitted = X.submit_visit(api, base, visit["id"], repair_confirmed=True)
    assert submitted["visit_status"] == VISIT_SUBMITTED
    assert submitted["calibration_record_count"] == 2

    verified = X.verify_visit(
        api, visit["id"], auditor_headers=AUDITOR_1_HEADERS
    )
    assert verified["visit_status"] == VISIT_VERIFIED
    assert verified["verified_by_user_id"] == AUDITOR_1_HEADERS["X-User-ID"]

    recovered = get_success_data(
        api.get_dispenser(dispenser["id"], base["technician_headers"])
    )
    assert recovered["dispenser_status"] == DISPENSER_ACTIVE
    assert recovered["lockout_reason"] is None
    assert recovered["calibrated_dose_ml_per_rack"] == pytest.approx(2.00, abs=0.01)
    assert recovered["prior_dose_ml_per_rack"] == pytest.approx(2.00, abs=0.01)
    assert_pct(recovered["last_drift_pct"], 0.00)
    assert_instant_equals(recovered["last_calibrated_at"], "2026-08-01T10:00:00Z", "last_calibrated_at")

    healthy = get_success_data(
        api.get_machine_placement(placement["id"], base["technician_headers"])
    )
    assert_axes(healthy, operational_status=OP_UP)
    assert healthy["cycles_since_calibration"] == 0

    # Only PASS and ADJUSTED verdicts are applied; the FAIL record stays unapplied
    # even though the visit that carried it was verified.
    unapplied = get_success_data(
        api.get_calibration_record(failing["id"], base["technician_headers"])
    )
    assert unapplied["applied"] is False
    applied = get_success_data(
        api.get_calibration_record(passing["id"], base["technician_headers"])
    )
    assert applied["applied"] is True

    closed = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert closed["status"] == TICKET_CLOSED
    engineer = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert engineer["open_ticket_count"] == 0
