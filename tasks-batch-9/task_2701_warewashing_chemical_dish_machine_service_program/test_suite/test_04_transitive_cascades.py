"""
Four-link causal chains: a clock advance that reaches alert suppression, and a
single telemetry sample that reaches the kitchen's service posture.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_axes, assert_lockout, assert_sweep_counters
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS, PLATFORM_ADMIN_HEADERS
from test_helpers.types import (
    AGREEMENT_EXPIRED,
    AGREEMENT_RENEWAL_PENDING,
    ALERT_LOW_RINSE_PRESSURE,
    ALERT_OPEN,
    ALERT_SUPPRESSED,
    DISPENSER_ACTIVE,
    DISPENSER_LOCKED_OUT,
    LOCKOUT_AGREEMENT_ENDED,
    OP_DEGRADED,
    OP_DOWN,
    ORIGIN_TELEMETRY_AUTO,
    PLACEMENT_INSTALLED,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    POSTURE_CRITICAL,
    POSTURE_NORMAL,
    SEVERITY_CRITICAL,
    SYMPTOM_MACHINE_DOWN,
    TICKET_CANCELLED,
    TICKET_QUEUED,
)


def _one_month_agreement_about_to_lapse(api):
    """
    A one-month agreement whose term ends 2026-09-01, carrying an INSTALLED
    placement with an ACTIVE dispenser, one OPEN WARNING alert and one QUEUED
    customer report. The clock is left at 2026-08-28, four days out, so the
    agreement is already RENEWAL_PENDING.
    """
    base = X.program_base(
        api,
        agreement_overrides={
            "start_date": "2026-08-01",
            "minimum_term_months": 1,
            "renewal_notice_days": 5,
        },
    )
    placement = X.installed_placement(api, base, asset_tag="AT-501")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.ingest_reading_at_clock(
        api, placement["id"], "2026-08-03T12:00:00Z", 500, rinse_pressure_psi=14
    )
    alerts = X.list_alerts_for_placement(api, placement["id"])
    assert len(alerts) == 1
    assert alerts[0]["status"] == ALERT_OPEN

    ticket = X.file_ticket(api, base, placement["id"])

    notice = validate_success(
        api.set_clock(F.clock_payload("2026-08-28T00:00:00Z"), PLATFORM_ADMIN_HEADERS)
    )

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "alert_id": alerts[0]["id"],
            "ticket_id": ticket["id"],
            "notice_sweep": notice,
        }
    )
    return base


def test_clock_expiry_reaches_alert_suppression_four_links_deep(api):
    """
    Moving the clock past the term end is the only input: the agreement expires,
    which schedules its INSTALLED placement for retrieval, which locks the
    dispenser out as AGREEMENT_ENDED, which suppresses the placement's OPEN
    alert. Nothing in the request names any of those rows.

    PRD §3.2: "3. Caused by each placement reaching `RETRIEVAL_SCHEDULED`: every
    dispenser of that placement whose `dispenser_status` is `ACTIVE` transitions
    `ACTIVE → LOCKED_OUT` with `lockout_reason` set to `AGREEMENT_ENDED`."

    Design: Difficulty/transitive_cascade/cascade_alpha_clock_expiry_reaches_alert_suppression_four_links_deep
    """
    base = _one_month_agreement_about_to_lapse(api)

    sweep = validate_success(
        api.set_clock(F.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN_HEADERS)
    )
    assert_sweep_counters(sweep, agreements_expired=1, current_utc="2026-09-01T00:00:00Z")

    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["status"] == AGREEMENT_EXPIRED

    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert customer["active_agreement_count"] == 0

    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(placement, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_LOCKED_OUT, LOCKOUT_AGREEMENT_ENDED)

    alert = get_success_data(
        api.get_telemetry_alert(base["alert_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert alert["status"] == ALERT_SUPPRESSED
    assert placement["open_alert_count"] == 0


def test_cascade_alpha_uses_the_thirty_day_due_date_and_stops_at_scheduled(api):
    """
    The notice hop runs first, and the cascade's own retrieval order dates itself
    30 days out from the clock rather than the manual 14. The chain stops there:
    the placement is not RETRIEVED, its health axis is untouched at DEGRADED, and
    the QUEUED ticket is cancelled.

    PRD §3.3: "Note that a retrieval order driven by cascade alpha rather than by
    an account manager uses a due date of the current clock's date plus 30 days,
    not 14 — the manual default and the cascade default differ deliberately."

    Design: Difficulty/transitive_cascade/cascade_alpha_clock_expiry_reaches_alert_suppression_four_links_deep
    """
    base = _one_month_agreement_about_to_lapse(api)

    assert base["notice_sweep"]["agreements_moved_to_renewal_pending"] == 1
    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["status"] == AGREEMENT_RENEWAL_PENDING

    validate_success(
        api.set_clock(F.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN_HEADERS)
    )

    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert placement["retrieval_due_date"] == "2026-10-01"
    assert_axes(
        placement,
        placement_status=PLACEMENT_RETRIEVAL_SCHEDULED,
        operational_status=OP_DEGRADED,
    )
    assert placement["retrieved_at"] is None

    ticket = get_success_data(
        api.get_service_ticket(base["ticket_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert ticket["status"] == TICKET_CANCELLED

    site = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert site["open_ticket_count"] == 0


def _healthy_placement_in_operating_hours(api):
    """
    One INSTALLED, UP placement in a STANDARD kitchen with no tickets and no
    alerts, and the clock at 2026-08-05T14:00Z — minute 840, inside the site's
    600-to-1320 operating window.
    """
    base = X.program_base(api, site_overrides={"priority_tier": "STANDARD"})
    placement = X.installed_placement(api, base, asset_tag="AT-601")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    X.set_clock(api, "2026-08-05T14:00:00Z")

    site = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert site["service_posture"] == POSTURE_NORMAL
    assert site["open_ticket_count"] == 0

    base.update({"placement_id": placement["id"], "dispenser_id": dispenser["id"]})
    return base


def test_critical_reading_drives_health_down_and_auto_raises_a_ticket(api):
    """
    11 psi is 4 psi under the 15 psi minimum, so the alert opens CRITICAL, the
    health axis goes UP to DOWN with the lifecycle axis untouched, and the
    placement auto-raises a TELEMETRY_AUTO MACHINE_DOWN ticket pointing at that
    alert.

    PRD §3.4: "A placement that is driven to `DOWN` — whether from `UP` or from
    `DEGRADED` — auto-raises a service ticket with `origin` `TELEMETRY_AUTO`,
    `reported_symptom` `MACHINE_DOWN`, `alert_id` pointing at the triggering
    alert, `reported_by_user_id` null, and a priority score stamped from the
    state as it stands after the alert has been applied."

    Design: Difficulty/transitive_cascade/cascade_beta_critical_reading_reaches_site_posture_four_links_deep
    """
    base = _healthy_placement_in_operating_hours(api)

    reading = validate_success(
        api.create_telemetry_reading(
            base["placement_id"],
            F.telemetry_reading_payload(
                "2026-08-05T14:00:00Z", 600, rinse_pressure_psi=11
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assert reading["triggered_alert_types"] == [ALERT_LOW_RINSE_PRESSURE]

    alerts = X.list_alerts_for_placement(api, base["placement_id"])
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["severity"] == SEVERITY_CRITICAL
    assert alert["measured_value"] == 11
    assert alert["triggering_reading_id"] == reading["id"]

    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        placement,
        placement_status=PLACEMENT_INSTALLED,
        operational_status=OP_DOWN,
    )

    tickets, _meta = _tickets_for(api, base["placement_id"])
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket["origin"] == ORIGIN_TELEMETRY_AUTO
    assert ticket["reported_symptom"] == SYMPTOM_MACHINE_DOWN
    assert ticket["alert_id"] == alert["id"]
    assert ticket["reported_by_user_id"] is None
    assert ticket["status"] == TICKET_QUEUED


def _tickets_for(api, placement_id):
    """Every ticket standing against one placement, via the flat list of §2.9."""
    return validate_paginated(
        api.list_service_tickets(
            ACCOUNT_MANAGER_HEADERS, {"placement_id": placement_id, "limit": 100}
        )
    )


def test_auto_ticket_score_of_700_re_derives_the_posture_to_critical(api):
    """
    The auto-ticket scores 400 for MACHINE_DOWN plus 300 for a machine down
    inside operating hours, giving exactly 700 and a 120-minute commitment; a
    700 score then re-derives the kitchen's posture to CRITICAL. Because the
    posture is read before the row is inserted, the ticket does not add the
    80-point ELEVATED component to its own score.

    PRD §3.5: "**Every input to the score is read from the state as it stands
    immediately before the ticket row is inserted.**"

    Design: Difficulty/transitive_cascade/cascade_beta_critical_reading_reaches_site_posture_four_links_deep
    """
    base = _healthy_placement_in_operating_hours(api)

    X.ingest_reading(
        api, base["placement_id"], "2026-08-05T14:00:00Z", 600, rinse_pressure_psi=11
    )

    tickets, _meta = _tickets_for(api, base["placement_id"])
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket["priority_score"] == 700
    assert ticket["priority_score"] != 780
    assert ticket["response_deadline_at"] == "2026-08-05T16:00:00Z"

    site = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert site["open_ticket_count"] == 1
    assert site["service_posture"] == POSTURE_CRITICAL

    # Unlike cascade alpha, nothing is locked out and nothing is suppressed.
    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_ACTIVE, None)


def test_a_second_identical_breach_opens_no_second_alert_or_ticket(api):
    """
    An alert of the same type already standing OPEN suppresses a second one, and
    with no new alert the placement raises no second ticket, so the kitchen's
    open-ticket count stays at one.

    PRD §3.4: "De-duplication is general: an alert of the same `alert_type`
    already standing in `OPEN` or `ACKNOWLEDGED` on this placement suppresses the
    opening of a second one, and the existing alert's `measured_value` is **not**
    refreshed with the newer breach."

    Design: Difficulty/transitive_cascade/cascade_beta_critical_reading_reaches_site_posture_four_links_deep
    """
    base = _healthy_placement_in_operating_hours(api)

    X.ingest_reading(
        api, base["placement_id"], "2026-08-05T14:00:00Z", 600, rinse_pressure_psi=11
    )
    second = X.ingest_reading_at_clock(
        api, base["placement_id"], "2026-08-05T15:00:00Z", 600, rinse_pressure_psi=11
    )

    assert second["triggered_alert_types"] == []
    assert len(X.list_alerts_for_placement(api, base["placement_id"])) == 1

    tickets, _meta = _tickets_for(api, base["placement_id"])
    assert len(tickets) == 1

    site = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert site["open_ticket_count"] == 1
