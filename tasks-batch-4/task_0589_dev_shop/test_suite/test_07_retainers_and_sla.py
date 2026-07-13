"""Maintenance retainers and the support SLA: the cooldown-buffered coverage
calendar, the two clocks that measure the same span, the strict breach comparison,
and the credits that net off the retainer invoice."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_lines_sum_to_subtotal,
    assert_total_is_subtotal_plus_tax,
    fixtures,
    factories as F,
)

AM = TEST_USERS["account_manager_headers"]
DL = TEST_USERS["delivery_lead_headers"]
ENG = TEST_USERS["engineer_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def test_retainer_invoice_nets_the_sla_credit_against_the_monthly_fee(api):
    """PRD 3.8: "For a `RETAINER` invoice, the first line is labelled `Monthly retainer` and its `amount` is the retainer's `monthly_fee`. Then the SLA credits are netted: the `sla_credit_amount` values of every support incident under that retainer which is `RESOLVED` and whose `resolved_at` date falls inside the inclusive window from `period_start` through `period_end` are summed, and if that sum is greater than zero a second line labelled `SLA credit` is appended carrying the **negative** of the rounded credit sum."
    PRD 3.9: "If `sla_resolution_breached` is also true, the same tier percentage is added a second time — so a `GOLD` retainer with both clocks blown accrues 20 percent."

    Design: Corner/calculations/retainer_invoice_nets_sla_credit_line_against_monthly_fee
    """
    ctx = fixtures.setup_resolved_incident(
        severity="SEV1",
        sla_tier="GOLD",
        monthly_fee=4000.00,
        opened_at="2026-05-01T16:00:00Z",
        responded_at="2026-05-04T10:00:00Z",
        resolved_at="2026-05-04T10:30:00Z",
    )
    incident = ctx["incident"]
    assert incident["resolution_minutes"] == 3990, (
        f"the SEV1 calendar clock measures from opened_at, got "
        f"{incident['resolution_minutes']}"
    )
    assert incident["sla_resolution_breached"] is True, "3990 minutes is far beyond the 480 target"
    assert incident["sla_credit_amount"] == pytest.approx(800.00, abs=0.01), (
        "both clocks blown on a GOLD retainer is 20 percent of 4,000.00"
    )

    invoice = fixtures.create_invoice(
        ctx["engagement"]["id"],
        "RETAINER",
        retainer_id=ctx["retainer"]["id"],
        period_start="2026-05-01",
        period_end="2026-05-31",
    )
    assert len(invoice["lines"]) == 2, f"fee line plus credit line, got {len(invoice['lines'])}"
    assert invoice["lines"][0]["amount"] == pytest.approx(4000.00, abs=0.01)
    assert invoice["lines"][1]["amount"] == pytest.approx(-800.00, abs=0.01), (
        "the credit line carries the negative of the credit sum"
    )
    assert invoice["subtotal"] == pytest.approx(3200.00, abs=0.01)
    assert invoice["tax"] == pytest.approx(264.00, abs=0.01)
    assert invoice["total"] == pytest.approx(3464.00, abs=0.01)
    assert_lines_sum_to_subtotal(invoice)
    assert_total_is_subtotal_plus_tax(invoice)


def test_sla_credit_on_a_silver_retainer_with_a_single_breach(api):
    """PRD 3.9: "`sla_credit_amount` starts from a credit percentage of zero. If `sla_response_breached` is true, the retainer's tier percentage is added: 10 percent for a `GOLD` retainer, 5 percent for `SILVER`, 2 percent for `BRONZE`."
    PRD 3.9: "The accumulated percentage is then capped at 25 percent, and `sla_credit_amount` is the retainer's `monthly_fee` multiplied by the capped percentage, rounded half up to 2 decimal places."

    Design: Corner/calculations/sla_credit_silver_tier_single_breach_uses_tier_constant
    """
    ctx = fixtures.setup_resolved_incident(
        severity="SEV1",
        sla_tier="SILVER",
        monthly_fee=4000.00,
        opened_at="2026-05-04T09:00:00Z",
        responded_at="2026-05-04T11:00:00Z",
        resolved_at="2026-05-04T15:00:00Z",
    )
    incident = ctx["incident"]

    assert incident["response_minutes"] == 120
    assert incident["sla_response_breached"] is True, "120 minutes exceeds the SEV1 60-minute target"
    assert incident["resolution_minutes"] == 360
    assert incident["sla_resolution_breached"] is False, (
        "360 minutes is inside the SEV1 480-minute resolution target"
    )
    assert incident["sla_credit_amount"] == pytest.approx(200.00, abs=0.01), (
        f"a single breach on a SILVER retainer is 5 percent of 4,000.00; got "
        f"{incident['sla_credit_amount']}"
    )
    assert incident["status"] == "RESOLVED"


def test_support_incident_raised_after_the_retainer_lapses_is_rejected(api):
    """PRD 3.9: "Incidents may only be raised while cover is live: the logical clock's current date must fall inside the retainer's closed window, on or after its `start_date` and on or before its `end_date`. An incident raised before cover starts or after it lapses is rejected with `ERR_RETAINER_WINDOW_INACTIVE` (HTTP 422)."

    Design: Corner/validations/support_incident_outside_retainer_window_is_rejected
    """
    ctx = fixtures.setup_retainer(start_date="2026-05-01", end_date="2026-07-31")
    fixtures.set_clock("2026-08-01T09:00:00Z")

    resp = api.create_support_incident(
        F.create_support_incident_payload(
            retainer_id=ctx["retainer"]["id"], severity="SEV3", summary="Cosmetic bug"
        ),
        ctx["client_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RETAINER_WINDOW_INACTIVE.value)

    incidents = validate_success(
        api.list_support_incidents(DL, params={"retainer_id": ctx["retainer"]["id"]})
    )
    assert len(incidents) == 0, "one day past the inclusive end_date, cover has lapsed"


# ---------------------------------------------------------------------------
# The two SLA clocks
# ---------------------------------------------------------------------------
def test_sev1_incident_is_measured_on_the_calendar_clock(api):
    """PRD 3.9: "For a `SEV1` incident the coverage is round-the-clock and the **calendar clock** applies: every wall-clock minute of the span counts, including nights and weekends, and the elapsed time is converted to whole minutes by discarding any fractional minute."
    PRD 3.9: "`sla_response_breached` is set true when `response_minutes` is strictly greater than the response target for the incident's severity, and it is computed at response time."

    Design: Difficulty/dual_variant_calc/sla_clock_calendar_vs_business_hours_variant_divergence
    """
    ctx = fixtures.setup_retainer(sla_tier="GOLD", monthly_fee=4000.00)
    incident = fixtures.open_incident(
        ctx, severity="SEV1", summary="Checkout returns 500", opened_at="2026-05-01T16:00:00Z"
    )
    fixtures.set_clock("2026-05-04T10:00:00Z")

    responded = validate_success(api.respond_incident(incident["id"], ENG))
    assert responded["status"] == "RESPONDED"
    assert responded["response_minutes"] == 3960, (
        f"Friday 16:00 to Monday 10:00 is 66 wall-clock hours = 3960 minutes; got "
        f"{responded['response_minutes']}"
    )
    assert responded["sla_response_breached"] is True, (
        "3960 minutes is strictly greater than the SEV1 60-minute target"
    )


def test_sev2_incident_over_the_same_span_is_measured_on_the_business_hours_clock(api):
    """PRD 3.9: "For a `SEV2` or `SEV3` incident the **business-hours clock** applies: only minutes falling inside the window from 09:00 up to (but not including) 17:00 UTC, on Mondays through Fridays, are counted; every minute outside that daily window and every minute of a Saturday or Sunday contributes nothing."
    PRD 3.9: "The response target is 60 minutes (one hour) for `SEV1`, 240 minutes (four hours) for `SEV2`, and 480 minutes (eight hours) for `SEV3`."

    Design: Difficulty/dual_variant_calc/sla_clock_calendar_vs_business_hours_variant_divergence
    """
    ctx = fixtures.setup_retainer(sla_tier="GOLD", monthly_fee=4000.00)
    sev1 = fixtures.open_incident(
        ctx, severity="SEV1", summary="Checkout returns 500", opened_at="2026-05-01T16:00:00Z"
    )
    sev2 = fixtures.open_incident(ctx, severity="SEV2", summary="Admin list is slow")
    fixtures.set_clock("2026-05-04T10:00:00Z")

    sev1_responded = validate_success(api.respond_incident(sev1["id"], ENG))
    sev2_responded = validate_success(api.respond_incident(sev2["id"], ENG))

    assert sev2_responded["status"] == "RESPONDED"
    assert sev2_responded["response_minutes"] == 120, (
        f"only Friday 16:00-17:00 (60) plus Monday 09:00-10:00 (60) count; the weekend "
        f"contributes nothing. Got {sev2_responded['response_minutes']}"
    )
    assert sev2_responded["sla_response_breached"] is False, (
        "120 minutes is inside the SEV2 240-minute target"
    )
    assert sev1_responded["response_minutes"] == 3960, (
        "the identical span under SEV1 counts every wall-clock minute"
    )
    assert sev2_responded["response_minutes"] != sev1_responded["response_minutes"], (
        "the severity chooses the clock, and the two clocks disagree over this span"
    )


# ---------------------------------------------------------------------------
# The strict breach comparison
# ---------------------------------------------------------------------------
def test_sla_response_exactly_at_the_target_is_not_a_breach(api):
    """PRD 3.9: "Breach is judged by comparing those minute counts against the severity's targets, and the comparison is **strict** — a duration exactly equal to its target is not a breach."
    PRD 3.9: "An incident that breaches neither clock earns a credit of exactly 0.00, and incidents still `OPEN` or `RESPONDED` carry an `sla_credit_amount` of 0 because the credit is only computed at resolution."

    Design: Difficulty/boundary_precision_check/sla_response_exactly_at_threshold_is_not_a_breach
    """
    ctx = fixtures.setup_retainer(sla_tier="GOLD", monthly_fee=4000.00)
    incident = fixtures.open_incident(
        ctx, severity="SEV1", summary="Search index stale", opened_at="2026-05-04T09:00:00Z"
    )
    fixtures.set_clock("2026-05-04T10:00:00Z")

    responded = validate_success(api.respond_incident(incident["id"], ENG, note="Engineer paged"))
    assert responded["response_minutes"] == 60
    assert responded["sla_response_breached"] is False, (
        "a breach needs response_minutes strictly greater than the 60-minute target"
    )
    assert responded["status"] == "RESPONDED"
    assert responded["sla_credit_amount"] == 0


def test_sla_response_one_minute_past_the_target_is_a_breach(api):
    """PRD 3.9: "Breach is judged by comparing those minute counts against the severity's targets, and the comparison is **strict** — a duration exactly equal to its target is not a breach."
    PRD 3.9: "The response target is 60 minutes (one hour) for `SEV1`, 240 minutes (four hours) for `SEV2`, and 480 minutes (eight hours) for `SEV3`."

    Design: Difficulty/boundary_precision_check/sla_response_exactly_at_threshold_is_not_a_breach
    """
    ctx = fixtures.setup_retainer(sla_tier="GOLD", monthly_fee=4000.00)
    incident = fixtures.open_incident(
        ctx, severity="SEV1", summary="Search index stale", opened_at="2026-05-04T09:00:00Z"
    )
    fixtures.set_clock("2026-05-04T10:01:00Z")

    responded = validate_success(api.respond_incident(incident["id"], ENG))
    assert responded["response_minutes"] == 61
    assert responded["sla_response_breached"] is True, (
        "61 minutes is strictly greater than the 60-minute target, so it is a breach"
    )


# ---------------------------------------------------------------------------
# The cooldown-buffered retainer calendar
# ---------------------------------------------------------------------------
def test_retainer_starting_inside_the_cooldown_buffer_is_rejected(api):
    """PRD 3.9: "A cooldown buffer of 7 days is applied on both sides of every existing window: a new retainer collides with an existing retainer of the same client when the new `start_date` falls on or before the existing `end_date` plus 7 days *and* the existing `start_date` falls on or before the new `end_date` plus 7 days. A collision is rejected with `ERR_RETAINER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/retainer_closed_interval_with_cooldown_buffer_conflict_rejected
    """
    ctx = fixtures.setup_retainer(start_date="2026-05-01", end_date="2026-07-31", sla_tier="GOLD")

    resp = api.create_retainer(
        F.create_retainer_payload(
            client_id=ctx["client"]["id"],
            engagement_id=ctx["engagement"]["id"],
            start_date="2026-08-05",
            end_date="2026-10-31",
            sla_tier="SILVER",
        ),
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_RETAINER_WINDOW_CONFLICT.value)

    retainers = validate_success(
        api.list_retainers(AM, params={"client_id": ctx["client"]["id"]})
    )
    assert len(retainers) == 1, (
        "2026-08-05 falls inside the 7-day buffer running through 2026-08-07"
    )


def test_retainer_starting_after_the_cooldown_buffer_elapses_is_accepted(api):
    """PRD 3.9: "**Retainer coverage windows are closed at both ends** — a retainer covers its `start_date` and its `end_date` and every day between — and a client may not hold two retainers back to back without a break."
    PRD 3.9: "A cooldown buffer of 7 days is applied on both sides of every existing window: a new retainer collides with an existing retainer of the same client when the new `start_date` falls on or before the existing `end_date` plus 7 days *and* the existing `start_date` falls on or before the new `end_date` plus 7 days. A collision is rejected with `ERR_RETAINER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/retainer_closed_interval_with_cooldown_buffer_conflict_rejected
    """
    ctx = fixtures.setup_retainer(start_date="2026-05-01", end_date="2026-07-31", sla_tier="GOLD")
    validate_error(
        api.create_retainer(
            F.create_retainer_payload(
                client_id=ctx["client"]["id"],
                engagement_id=ctx["engagement"]["id"],
                start_date="2026-08-05",
                end_date="2026-10-31",
                sla_tier="SILVER",
            ),
            AM,
        ),
        ApiErrorId.ERR_RETAINER_WINDOW_CONFLICT.value,
    )

    accepted = validate_success(
        api.create_retainer(
            F.create_retainer_payload(
                client_id=ctx["client"]["id"],
                engagement_id=ctx["engagement"]["id"],
                start_date="2026-08-08",
                end_date="2026-10-31",
                sla_tier="SILVER",
            ),
            AM,
        ),
        expected_status=201,
    )
    assert accepted["sla_tier"] == "SILVER"
    assert accepted["start_date"] == "2026-08-08", (
        "2026-08-08 is past the 7-day buffer, so the window is free"
    )

    retainers = validate_success(
        api.list_retainers(AM, params={"client_id": ctx["client"]["id"]})
    )
    assert len(retainers) == 2
