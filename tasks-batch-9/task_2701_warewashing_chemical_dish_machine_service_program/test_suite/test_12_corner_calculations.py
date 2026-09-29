"""
Derived-figure arithmetic: rounding order, window attribution, alert margins,
ranking keys and the frozen figures a chargeback is computed from.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_alert,
    assert_axes,
    assert_case,
    assert_cents,
    assert_delivery,
    assert_pct,
    assert_review,
    assert_ticket,
    assert_workload,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    ALERT_CALIBRATION_OVERDUE,
    ALERT_HIGH_CYCLE_RATE,
    ALERT_LOW_FINAL_RINSE_TEMP,
    ALERT_LOW_RINSE_PRESSURE,
    ALERT_LOW_WASH_TEMP,
    ALERT_OPEN,
    BASIS_NAMEPLATE,
    CASE_EVIDENCE_GATHERING,
    CASE_PENDING_REVIEW,
    CASE_SUBSTANTIATED,
    CERT_L1,
    CERT_L2,
    CERT_SANITATION,
    CLASS_THEFT_SUSPECT,
    DECISION_SUBSTANTIATE,
    DELIVERY_DELIVERED,
    DISPENSER_ACTIVE,
    DOSSIER_DEFICIENT,
    DOSSIER_READY,
    EFFICACY_PASS,
    EVIDENCE_DELIVERY_LOG,
    EVIDENCE_INVENTORY_COUNT,
    OP_DEGRADED,
    OP_DOWN,
    ORIGIN_TELEMETRY_AUTO,
    POSTURE_CRITICAL,
    REASON_SUSPECTED_THEFT,
    REMEDIATION_CHARGEBACK,
    REVIEW_CLOSED,
    REVIEW_DRAFT,
    REVIEW_ESCALATED,
    REVIEW_PUBLISHED,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SOURCE_DEVICE,
    SOURCE_MANUAL_AUDIT,
    SUSTAINABILITY_BASIS_RATED,
    SYMPTOM_LEAK,
    SYMPTOM_MACHINE_DOWN,
    SYMPTOM_RACK_QUALITY,
    TICKET_DISPATCHED,
    TIER_STANDARD,
    VERDICT_PASS,
    VISIT_VERIFIED,
)

# The catalog container used by the delivery-tier test: a list price of 9605
# cents makes both discounted unit prices land off a whole cent, so the order of
# rounding and multiplication is observable.
TIERED_SKU = "DET-105"
TIERED_LIST_PRICE_CENTS = 9605


def _account_with_a_tiered_container(api):
    """
    One account, one kitchen and an active agreement covering a single 20000 ml
    detergent whose list price is 9605 cents per container.
    """
    customer = X.create_customer(api)
    product = X.create_detergent(
        api, sku=TIERED_SKU, unit_price_cents=TIERED_LIST_PRICE_CENTS
    )
    site = X.create_site(api, customer["id"])
    X.create_active_agreement(api, customer["id"], [product["id"]])
    return {
        "customer_id": customer["id"],
        "site_id": site["id"],
        "product_id": product["id"],
    }


def _deliver(api, ctx, unit_count):
    """Book one delivery of `unit_count` containers on the opening instant of the
    programme, re-reading the kitchen's version token first."""
    payload = F.chemical_delivery_payload(
        ctx["site_id"],
        ctx["product_id"],
        X.site_version(api, ctx["site_id"]),
        unit_count=unit_count,
        delivered_at="2026-08-01T00:00:00Z",
    )
    delivery = validate_success(
        api.create_chemical_delivery(payload, ACCOUNT_MANAGER_HEADERS), 201
    )
    assert_delivery(delivery)
    assert delivery["status"] == DELIVERY_DELIVERED
    assert delivery["unit_count"] == unit_count
    return delivery


def test_the_discount_is_applied_to_one_container_before_the_count_multiplies(api):
    """
    A 9605-cent container discounted by five percent costs 9124.75 cents, which
    rounds to 9125 before the count multiplies: ten containers cost 91250, not the
    91248 that rounding the total once would give. At the twelve-percent tier
    8452.4 rounds down to 8452, so twenty-five containers cost 211300 rather than
    211310 — and, because the tier boundary is inclusive, twenty-five containers
    cost less in total than twenty-four.

    PRD §3.7: "The discounted **unit** price is then computed by multiplying the
    product's `unit_price_cents` by one minus that rate and rounding half up to
    whole cents, and `amount_cents` is that rounded unit price multiplied by
    `unit_count`."

    Design: Corner/calculations/delivery_tiers_round_the_discounted_unit_price_before_multiplying
    """
    ctx = _account_with_a_tiered_container(api)

    # Below the first tier: the list price applies untouched.
    nine = _deliver(api, ctx, 9)
    assert nine["quantity_ml"] == 180000
    assert_cents(nine["amount_cents"], 86445)

    # Exactly at the 10-unit boundary: 9605 * 0.95 = 9124.75 -> 9125 per container.
    ten = _deliver(api, ctx, 10)
    assert ten["quantity_ml"] == 200000
    assert_cents(ten["amount_cents"], 91250)
    assert ten["amount_cents"] != 91248

    # 24 units still earn only five percent: 9125 * 24.
    twenty_four = _deliver(api, ctx, 24)
    assert_cents(twenty_four["amount_cents"], 219000)

    # Exactly at the 25-unit boundary: 9605 * 0.88 = 8452.4 -> 8452 per container.
    twenty_five = _deliver(api, ctx, 25)
    assert twenty_five["quantity_ml"] == 500000
    assert_cents(twenty_five["amount_cents"], 211300)
    assert twenty_five["amount_cents"] != 211310
    assert twenty_five["amount_cents"] < twenty_four["amount_cents"]


def test_manual_audit_racks_and_closing_boundary_racks_are_both_excluded(api):
    """
    Four samples land on one machine: an opening sample with a zero delta, a DEVICE
    sample carrying 300 racks, a MANUAL_AUDIT sample carrying 500 and a closing
    DEVICE sample carrying 600 measured from the last DEVICE predecessor, not from
    the audit row. A window closing on the fourth sample's instant counts 300
    racks; widening the window to admit it counts 900.

    PRD §3.7: "Placements still in `PENDING_INSTALL` and placements in `CANCELLED`
    contribute nothing, and `MANUAL_AUDIT` readings are excluded from every rack
    count."

    Design: Corner/calculations/rack_counts_exclude_manual_audit_readings_and_the_closing_boundary
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=100
    )
    X.set_clock(api, "2026-08-10T00:00:00Z")

    opening = X.ingest_reading(api, placement["id"], "2026-08-01T00:00:00Z", 100)
    assert opening["cycle_delta"] == 0
    assert opening["source"] == SOURCE_DEVICE

    inside = X.ingest_reading(api, placement["id"], "2026-08-05T00:00:00Z", 400)
    assert inside["cycle_delta"] == 300

    audit = X.ingest_reading(
        api,
        placement["id"],
        "2026-08-06T00:00:00Z",
        900,
        source=SOURCE_MANUAL_AUDIT,
        wash_temp_f=100,
        final_rinse_temp_f=100,
        rinse_pressure_psi=1,
    )
    assert audit["source"] == SOURCE_MANUAL_AUDIT
    assert audit["cycle_delta"] == 500
    # An audit sample opens no alert however far under the minima it reads.
    assert audit["triggered_alert_types"] == []
    assert X.list_alerts_for_placement(api, placement["id"]) == []

    # The predecessor is the 08-05 DEVICE row, so the delta skips the audit row.
    closing = X.ingest_reading(api, placement["id"], "2026-08-10T00:00:00Z", 1000)
    assert closing["cycle_delta"] == 600

    report = get_success_data(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-10T00:00:00Z",
                basis=SUSTAINABILITY_BASIS_RATED,
            ),
        )
    )
    assert report["rack_count"] == 300
    assert report["water_saved_l"] == pytest.approx(138.0, abs=0.01)
    assert_cents(report["water_savings_cents"], 66)
    assert_cents(report["energy_savings_cents"], 882)
    assert_cents(report["gross_savings_cents"], 948)
    assert_cents(report["service_fee_cents"], 0)
    assert_cents(report["sustainability_credit_cents"], 47)
    assert_cents(report["net_program_cost_cents"], 24953)
    assert_pct(report["goal_attainment_pct"], 0.03)

    widened = get_success_data(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-11T00:00:00Z",
                basis=SUSTAINABILITY_BASIS_RATED,
            ),
        )
    )
    assert widened["rack_count"] == 900


def test_a_huge_saving_is_capped_at_fifteen_thousand_cents_over_a_base_fee(api):
    """
    A hundred thousand racks save 316080 cents gross, five percent of which is
    15804 — above the cap, so the credit is exactly 15000. The 25000-cent base fee
    is still charged even though no chemical was bought, so the net cost is 10000
    rather than a negative figure, and the fee tier is read off the pre-credit
    25000.

    PRD §3.9: "`sustainability_credit_cents` is 0 whenever `gross_savings_cents` is
    zero or negative; otherwise it is `gross_savings_cents` multiplied by 0.05 and
    rounded half up to whole cents, then capped at 15000 cents by taking whichever
    of the two is smaller."

    Design: Corner/calculations/sustainability_credit_is_capped_and_the_base_fee_still_applies
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    X.set_clock(api, "2026-08-02T00:00:00Z")

    reading = X.ingest_reading(api, placement["id"], "2026-08-02T00:00:00Z", 100000)
    assert reading["cycle_delta"] == 100000
    # No predecessor DEVICE sample exists, so the rate alert cannot fire; only the
    # calibration odometer trips.
    assert reading["triggered_alert_types"] == [ALERT_CALIBRATION_OVERDUE]

    report = get_success_data(
        api.get_sustainability_report(
            base["site_id"],
            base["customer_headers"],
            F.report_params(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-03T00:00:00Z",
                basis=SUSTAINABILITY_BASIS_RATED,
            ),
        )
    )
    assert report["rack_count"] == 100000
    assert report["water_saved_l"] == pytest.approx(46000.0, abs=0.01)
    assert report["energy_saved_kwh"] == pytest.approx(21000.0, abs=0.01)
    assert_cents(report["water_savings_cents"], 22080)
    assert_cents(report["energy_savings_cents"], 294000)
    assert_cents(report["gross_savings_cents"], 316080)
    assert_cents(report["chemical_spend_cents"], 0)
    assert_cents(report["gross_program_cost_cents"], 25000)
    assert report["service_fee_rate"] == pytest.approx(0.08, abs=0.0001)
    assert_cents(report["service_fee_cents"], 0)
    assert_cents(report["sustainability_credit_cents"], 15000)
    assert report["sustainability_credit_cents"] != 15804
    assert_cents(report["net_program_cost_cents"], 10000)
    assert_pct(report["goal_attainment_pct"], 9.20)

    machine = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(machine, operational_status=OP_DEGRADED)
    assert machine["cycles_since_calibration"] == 100000


def _alerts_by_type(api, placement_id):
    """The placement's alerts keyed by `alert_type`, asserting one row per type."""
    rows = X.list_alerts_for_placement(api, placement_id)
    by_type = {}
    for row in rows:
        assert_alert(row)
        assert row["alert_type"] not in by_type
        by_type[row["alert_type"]] = row
    return by_type


def _tickets_for(api, placement_id):
    rows = get_success_data(
        api.list_service_tickets(ACCOUNT_MANAGER_HEADERS, {"limit": 100})
    )
    return [row for row in rows if row["placement_id"] == placement_id]


def test_each_alert_type_carries_its_own_margin_and_its_own_dedup_slot(api):
    """
    On a 180/150/15 machine, 141 degrees of wash water is one degree inside the
    ten-degree critical margin and only warns, while 140 is exactly at it and goes
    critical; 13 psi warns and 12 psi is exactly at the three-psi margin and goes
    critical; 176 degrees of final rinse is one degree inside the five-degree margin
    and only warns. A second breach of an already-open type opens nothing and does
    not restamp the standing alert, yet a different type on the same reading still
    opens normally.

    PRD §3.4: "De-duplication is general: an alert of the same `alert_type` already
    standing in `OPEN` or `ACKNOWLEDGED` on this placement suppresses the opening of
    a second one, and the existing alert's `measured_value` is **not** refreshed with
    the newer breach."

    Design: Corner/calculations/alert_severity_margins_and_dedup_are_evaluated_per_alert_type
    """
    base = X.program_base(api)
    assert base["site"]["priority_tier"] == TIER_STANDARD
    first = X.installed_placement(api, base, asset_tag="AT-C01", initial_cycle_count=0)
    second = X.installed_placement(api, base, asset_tag="AT-C02", initial_cycle_count=0)
    third = X.installed_placement(api, base, asset_tag="AT-C03", initial_cycle_count=0)

    # One degree inside the wash margin: warning only, so no ticket is raised.
    warned = X.ingest_reading(
        api, first["id"], "2026-08-01T00:00:00Z", 10, wash_temp_f=141
    )
    assert warned["triggered_alert_types"] == [ALERT_LOW_WASH_TEMP]
    wash_alert = _alerts_by_type(api, first["id"])[ALERT_LOW_WASH_TEMP]
    assert wash_alert["severity"] == SEVERITY_WARNING
    assert wash_alert["measured_value"] == pytest.approx(141, abs=0.01)
    assert wash_alert["status"] == ALERT_OPEN
    assert _tickets_for(api, first["id"]) == []

    # Exactly at the wash margin on a second machine: critical, so the machine goes
    # down and cascade beta raises the auto-ticket while the backlog is still empty.
    downed = X.ingest_reading(
        api, second["id"], "2026-08-01T00:00:00Z", 10, wash_temp_f=140
    )
    assert downed["triggered_alert_types"] == [ALERT_LOW_WASH_TEMP]
    assert (
        _alerts_by_type(api, second["id"])[ALERT_LOW_WASH_TEMP]["severity"]
        == SEVERITY_CRITICAL
    )
    assert_axes(
        get_success_data(
            api.get_machine_placement(second["id"], ACCOUNT_MANAGER_HEADERS)
        ),
        operational_status=OP_DOWN,
    )
    (auto_one,) = _tickets_for(api, second["id"])
    assert_ticket(auto_one)
    assert auto_one["origin"] == ORIGIN_TELEMETRY_AUTO
    assert auto_one["reported_symptom"] == SYMPTOM_MACHINE_DOWN
    # 400 symptom + 90 out-of-hours health; the tier, exposure and backlog
    # components all contribute nothing here.
    assert auto_one["priority_score"] == 490
    assert auto_one["response_deadline_at"] == "2026-08-01T04:00:00Z"

    # Two types breach on one reading of the third machine and both open, in the
    # order §3.4 numbers them; the critical pressure alert drives the health axis.
    both = X.ingest_reading(
        api,
        third["id"],
        "2026-08-01T00:00:00Z",
        10,
        final_rinse_temp_f=176,
        rinse_pressure_psi=12,
    )
    assert both["triggered_alert_types"] == [
        ALERT_LOW_FINAL_RINSE_TEMP,
        ALERT_LOW_RINSE_PRESSURE,
    ]
    third_alerts = _alerts_by_type(api, third["id"])
    assert third_alerts[ALERT_LOW_FINAL_RINSE_TEMP]["severity"] == SEVERITY_WARNING
    assert third_alerts[ALERT_LOW_RINSE_PRESSURE]["severity"] == SEVERITY_CRITICAL
    third_row = get_success_data(
        api.get_machine_placement(third["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(third_row, operational_status=OP_DOWN)
    assert third_row["open_alert_count"] == 2
    (auto_two,) = _tickets_for(api, third["id"])
    # 400 symptom + 90 out-of-hours health + 200 sanitation exposure from the
    # standing final-rinse alert + 80 for the ELEVATED backlog the first
    # auto-ticket created.
    assert auto_two["priority_score"] == 770
    assert auto_two["response_deadline_at"] == "2026-08-01T02:00:00Z"

    # Back to the first machine: a critical wash breach is swallowed by the standing
    # warning of the same type, while the new pressure type opens on its own margin.
    X.set_clock(api, "2026-08-01T01:00:00Z")
    deduped = X.ingest_reading(
        api,
        first["id"],
        "2026-08-01T01:00:00Z",
        20,
        wash_temp_f=130,
        rinse_pressure_psi=13,
    )
    assert deduped["triggered_alert_types"] == [ALERT_LOW_RINSE_PRESSURE]
    first_alerts = _alerts_by_type(api, first["id"])
    assert len(first_alerts) == 2
    standing = first_alerts[ALERT_LOW_WASH_TEMP]
    assert standing["id"] == wash_alert["id"]
    assert standing["severity"] == SEVERITY_WARNING
    assert standing["measured_value"] == pytest.approx(141, abs=0.01)
    assert standing["version"] == wash_alert["version"]
    assert first_alerts[ALERT_LOW_RINSE_PRESSURE]["severity"] == SEVERITY_WARNING
    assert first_alerts[ALERT_LOW_RINSE_PRESSURE]["measured_value"] == pytest.approx(
        13, abs=0.01
    )

    first_row = get_success_data(
        api.get_machine_placement(first["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(first_row, operational_status=OP_DEGRADED)
    assert first_row["open_alert_count"] == 2
    assert _tickets_for(api, first["id"]) == []

    site = get_success_data(api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS))
    assert site["service_posture"] == POSTURE_CRITICAL
    assert site["open_ticket_count"] == 2


def test_the_rate_alert_needs_a_predecessor_and_a_strictly_higher_rate(api):
    """
    A 60-rack-per-hour machine tolerates exactly 66 racks in an hour, so the first
    sample — which has no predecessor at all — and the 66-rack sample both pass; 67
    racks in an hour is the first rate strictly above the tolerance and opens the
    alert. A far worse fourth hour opens nothing, because the type is already
    standing.

    PRD §3.4: "`HIGH_CYCLE_RATE` fires only when a preceding `DEVICE` reading
    exists, and then only when the observed rack rate exceeds the model's rated
    throughput by more than ten percent: divide this reading's `cycle_delta` by the
    exact number of hours between the predecessor's `reading_at` and this reading's
    `reading_at`, and compare against `racks_per_hour` multiplied by 1.10."

    Design: Corner/calculations/high_cycle_rate_needs_a_predecessor_and_fires_only_above_the_tolerance
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )

    # No predecessor exists, so the rate alert cannot fire on the opening sample.
    opening = X.ingest_reading(api, placement["id"], "2026-08-01T00:00:00Z", 0)
    assert opening["cycle_delta"] == 0
    assert opening["triggered_alert_types"] == []

    X.set_clock(api, "2026-08-01T03:00:00Z")

    # 66 racks in exactly one hour equals 60 * 1.10 and is therefore not above it.
    at_tolerance = X.ingest_reading(api, placement["id"], "2026-08-01T01:00:00Z", 66)
    assert at_tolerance["cycle_delta"] == 66
    assert at_tolerance["triggered_alert_types"] == []
    assert X.list_alerts_for_placement(api, placement["id"]) == []

    # 67 racks in the next hour is the first rate strictly above the tolerance.
    above = X.ingest_reading(api, placement["id"], "2026-08-01T02:00:00Z", 133)
    assert above["cycle_delta"] == 67
    assert above["triggered_alert_types"] == [ALERT_HIGH_CYCLE_RATE]
    rate_alert = _alerts_by_type(api, placement["id"])[ALERT_HIGH_CYCLE_RATE]
    assert rate_alert["severity"] == SEVERITY_WARNING
    assert rate_alert["status"] == ALERT_OPEN
    assert_axes(
        get_success_data(
            api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
        ),
        operational_status=OP_DEGRADED,
    )

    # A much worse hour changes nothing: the type is already standing.
    worse = X.ingest_reading(api, placement["id"], "2026-08-01T03:00:00Z", 300)
    assert worse["cycle_delta"] == 167
    assert worse["triggered_alert_types"] == []

    final_alerts = _alerts_by_type(api, placement["id"])
    assert len(final_alerts) == 1
    assert final_alerts[ALERT_HIGH_CYCLE_RATE]["id"] == rate_alert["id"]
    machine = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(machine, operational_status=OP_DEGRADED)
    assert machine["open_alert_count"] == 1
    assert machine["cycles_since_calibration"] == 300


def test_the_selector_settles_load_then_certification_then_tenure_in_that_order(api):
    """
    Four engineers share one region: two hold `L2`, one holds `L1` and one is
    sanitation-certified, and the second `L2` was hired an hour after the first. An
    override consumes the certified engineer's only slot; the next unassigned job
    then goes to the senior `L2` because certification eliminates the `L1` before
    tenure is ever consulted, and the third job goes to the junior `L2` over the
    still-idle `L1` — proving certification outranks tenure rather than the reverse.

    PRD §3.5: "**Ranking** then orders the survivors by `open_ticket_count`
    ascending — least loaded first — and, among equally loaded candidates, by
    certification rank descending, where `SANITATION_CERTIFIED` ranks 3, `L2` ranks
    2 and `L1` ranks 1."

    Design: Corner/calculations/dispatch_ranks_by_load_then_certification_then_tenure
    """
    base = X.program_base(
        api,
        technician_overrides={"name": "Anders Holm", "certification_level": CERT_L2},
    )
    anders = base["technician"]
    baptiste = X.create_technician(
        api, name="Baptiste Roy", certification_level=CERT_L1
    )
    chen = X.create_technician(
        api, name="Chen Wu", certification_level=CERT_SANITATION
    )

    # The junior L2 joins the roster an hour later, so tenure separates the two L2s.
    X.set_clock(api, "2026-08-01T01:00:00Z")
    ekhart = X.create_technician(
        api, name="Ekhart Voss", certification_level=CERT_L2
    )
    assert ekhart["created_at"] > anders["created_at"]

    first = X.installed_placement(api, base, asset_tag="AT-C01")
    second = X.installed_placement(api, base, asset_tag="AT-C02")
    third = X.installed_placement(api, base, asset_tag="AT-C03")
    # RACK_QUALITY needs no sanitation certification, so the whole roster is eligible.
    ticket_one = X.file_ticket(api, base, first["id"], SYMPTOM_RACK_QUALITY)
    ticket_two = X.file_ticket(api, base, second["id"], SYMPTOM_RACK_QUALITY)
    ticket_three = X.file_ticket(api, base, third["id"], SYMPTOM_RACK_QUALITY)
    assert ticket_one["requires_sanitation_cert"] is False

    # The override skips ranking entirely and loads the certified engineer.
    forced = X.dispatch_ticket(api, ticket_one["id"], override_technician_id=chen["id"])
    assert forced["status"] == TICKET_DISPATCHED
    assert forced["assigned_technician_id"] == chen["id"]

    # Three engineers are level on load; certification drops the L1 and tenure
    # then picks the senior L2.
    selected = X.dispatch_ticket(api, ticket_two["id"])
    assert selected["assigned_technician_id"] == anders["id"]

    # Two engineers remain level on load; certification alone settles it, so the
    # junior L2 wins over the longer-tenured L1.
    junior = X.dispatch_ticket(api, ticket_three["id"])
    assert junior["assigned_technician_id"] == ekhart["id"]

    for technician, expected in (
        (anders, 1),
        (baptiste, 0),
        (chen, 1),
        (ekhart, 1),
    ):
        assert_workload(
            get_success_data(
                api.get_technician(technician["id"], PLATFORM_ADMIN_HEADERS)
            ),
            expected,
        )


def test_only_an_adjudicated_visits_evidence_reaches_the_dossier(api):
    """
    A sanitizer test on a `VERIFIED` visit is counted; an identical test taken on a
    second visit that has only arrived is not, so the dossier is byte-for-byte the
    same before and after it. A single sub-minimum final rinse sample then condemns
    the pack even though the sanitizer evidence is still perfect.

    PRD §3.9: "Its cardinal rule is that **only evidence from `VERIFIED` visits
    counts**: calibration records attached to visits standing in `SCHEDULED`,
    `IN_PROGRESS`, `SUBMITTED`, `REJECTED` or `CANCELLED` are excluded entirely,
    however good their readings were."

    Design: Corner/calculations/inspection_dossier_counts_only_verified_visit_evidence
    """
    base = X.program_base(api, with_sanitizer=True)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    dispenser = X.fit_dispenser(
        api, base, placement["id"], product_id=base["sanitizer_id"], dose=2.00
    )

    work = X.visit_in_progress(api, base, placement["id"])
    passing = X.record_calibration(
        api,
        base,
        work["visit_id"],
        dispenser["id"],
        measured_ppm=200,
        measured_dose_ml_per_rack=2.00,
        contact_seconds=10,
    )
    assert passing["calibration_verdict"] == VERDICT_PASS
    assert passing["efficacy_result"] == EFFICACY_PASS
    X.submit_visit(api, base, work["visit_id"], repair_confirmed=True)
    verified = X.verify_visit(api, work["visit_id"])
    assert verified["visit_status"] == VISIT_VERIFIED

    window = F.report_params(
        period_start="2026-08-01T00:00:00Z", period_end="2026-08-02T00:00:00Z"
    )
    ready = get_success_data(
        api.get_inspection_dossier(base["site_id"], AUDITOR_1_HEADERS, window)
    )
    assert ready["calibration_records_total"] == 1
    assert ready["sanitizer_tests_total"] == 1
    assert ready["sanitizer_tests_passed"] == 1
    assert ready["latest_efficacy_result"] == EFFICACY_PASS
    assert ready["final_rinse_temp_readings_total"] == 0
    assert ready["final_rinse_temp_exceptions"] == 0
    assert ready["open_critical_alert_count"] == 0
    assert ready["dossier_status"] == DOSSIER_READY

    # A second, unadjudicated visit files an equally good sanitizer test.
    leak = X.file_ticket(api, base, placement["id"], SYMPTOM_LEAK)
    X.dispatch_ticket(api, leak["id"])
    second_visit = X.book_visit(
        api,
        base,
        leak["id"],
        "2026-08-01T13:00:00Z",
        "2026-08-01T14:00:00Z",
    )
    X.set_clock(api, "2026-08-01T13:00:00Z")
    X.arrive_visit(api, base, second_visit["id"])
    unadjudicated = X.record_calibration(
        api,
        base,
        second_visit["id"],
        dispenser["id"],
        measured_ppm=200,
        measured_dose_ml_per_rack=2.00,
        contact_seconds=10,
    )
    assert unadjudicated["efficacy_result"] == EFFICACY_PASS
    assert unadjudicated["applied"] is False

    unchanged = get_success_data(
        api.get_inspection_dossier(base["site_id"], AUDITOR_1_HEADERS, window)
    )
    assert unchanged["calibration_records_total"] == 1
    assert unchanged["sanitizer_tests_total"] == 1
    assert unchanged["sanitizer_tests_passed"] == 1
    assert unchanged["latest_efficacy_result"] == EFFICACY_PASS
    assert unchanged["dossier_status"] == DOSSIER_READY

    # One sample below the model's 180-degree minimum is a temperature exception,
    # and a single exception is enough to condemn the pack.
    X.set_clock(api, "2026-08-01T14:00:00Z")
    sample = X.ingest_reading(
        api, placement["id"], "2026-08-01T14:00:00Z", 50, final_rinse_temp_f=176
    )
    assert sample["triggered_alert_types"] == [ALERT_LOW_FINAL_RINSE_TEMP]
    assert (
        _alerts_by_type(api, placement["id"])[ALERT_LOW_FINAL_RINSE_TEMP]["severity"]
        == SEVERITY_WARNING
    )

    deficient = get_success_data(
        api.get_inspection_dossier(base["site_id"], AUDITOR_1_HEADERS, window)
    )
    assert deficient["calibration_records_total"] == 1
    assert deficient["sanitizer_tests_total"] == 1
    assert deficient["latest_efficacy_result"] == EFFICACY_PASS
    assert deficient["final_rinse_temp_readings_total"] == 1
    assert deficient["final_rinse_temp_exceptions"] == 1
    assert deficient["open_critical_alert_count"] == 0
    assert deficient["dossier_status"] == DOSSIER_DEFICIENT


def test_a_chargeback_bills_whole_containers_at_the_undiscounted_list_price(api):
    """
    A hundred racks should have drunk 800 ml but 40801 ml left the store, so the
    excess of 40001 ml is 2.00005 containers — billed as three whole 20000 ml
    containers at the 9600-cent list price, never at a volume-discounted price and
    never as a fractional container. Closing the case leaves the review's frozen
    figures exactly as published.

    PRD §3.8: "take `actual_consumption_ml` minus `expected_consumption_ml`, keep it
    only if positive and otherwise treat the excess as zero, divide that excess by
    the product's `unit_size_ml` and round **up** to the next whole container, and
    multiply the resulting container count by the product's `unit_price_cents` — the
    list price, with no volume discount, because excess consumption is not a
    purchase."

    Design: Corner/calculations/theft_chargeback_rounds_up_to_whole_containers_at_list_price
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    sample = X.ingest_reading(api, placement["id"], "2026-08-01T00:00:00Z", 100)
    assert sample["cycle_delta"] == 100

    delivery = X.record_delivery(
        api, base, unit_count=1, delivered_at="2026-08-01T00:00:00Z"
    )
    assert delivery["quantity_ml"] == 20000
    assert_cents(delivery["amount_cents"], 9600)

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-02T00:00:00Z",
        basis=BASIS_NAMEPLATE,
        opening_inventory_ml=30000,
        ending_inventory_ml=9199,
    )
    assert_review(review)
    assert review["rack_count_in_period"] == 100
    assert review["expected_consumption_ml"] == 800
    assert review["actual_consumption_ml"] == 40801
    assert_pct(review["variance_pct"], 5000.13)
    assert review["classification"] == CLASS_THEFT_SUSPECT
    assert review["status"] == REVIEW_DRAFT

    published = X.publish_review(api, review["id"])
    assert published["status"] == REVIEW_PUBLISHED

    case = X.open_case(api, review["id"], REASON_SUSPECTED_THEFT)
    assert_case(case)
    assert case["case_status"] == CASE_EVIDENCE_GATHERING
    assert case["evidence_item_count"] == 0
    assert_cents(case["chargeback_cents"], 0)
    escalated = get_success_data(
        api.get_usage_variance_review(review["id"], AUDITOR_1_HEADERS)
    )
    assert escalated["status"] == REVIEW_ESCALATED

    submitted = X.submit_case(
        api, case["id"], [EVIDENCE_DELIVERY_LOG, EVIDENCE_INVENTORY_COUNT]
    )
    assert submitted["case_status"] == CASE_PENDING_REVIEW
    assert submitted["evidence_item_count"] == 2

    adjudicated = X.review_case(
        api,
        case["id"],
        DECISION_SUBSTANTIATE,
        remediation=REMEDIATION_CHARGEBACK,
        finding_note="Inventory count and delivery log agree on the shortfall.",
    )
    assert adjudicated["case_status"] == CASE_SUBSTANTIATED
    # ceil(40001 / 20000) == 3 containers, each billed at the 9600-cent list price.
    assert_cents(adjudicated["chargeback_cents"], 28800)

    closed = get_success_data(
        api.get_usage_variance_review(review["id"], AUDITOR_1_HEADERS)
    )
    assert closed["status"] == REVIEW_CLOSED
    assert closed["expected_consumption_ml"] == 800
    assert closed["actual_consumption_ml"] == 40801

    settled = get_success_data(
        api.get_dispenser(dispenser["id"], base["technician_headers"])
    )
    assert settled["dispenser_status"] == DISPENSER_ACTIVE
    assert settled["lockout_reason"] is None
