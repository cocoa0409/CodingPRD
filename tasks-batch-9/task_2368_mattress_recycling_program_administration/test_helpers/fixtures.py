"""Composite setup helpers.

Every helper drives the public API only — the same endpoints a client would use —
so the state each one leaves behind is reachable by any caller of this API. All
setup calls go through `get_success_data`, so a broken precondition surfaces as a
setup failure rather than as a misleading assertion failure inside a test.

Each composite returns a dict that carries the created records *and* the role
headers bound to the real entity ids, because four of the six roles identify
themselves with the id of the entity they act as.
"""

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    ca_program_payload,
    create_collection_site_payload,
    create_commodity_output_record_payload,
    create_exemption_claim_payload,
    create_fee_rate_schedule_payload,
    create_hauler_payload,
    create_load_inspection_payload,
    create_pickup_order_payload,
    create_recycler_payload,
    create_registrant_payload,
    create_sales_remittance_payload,
    create_state_program_payload,
    create_take_back_delivery_payload,
    create_volume_report_payload,
    wa_program_payload,
)
from .test_users import (
    TEST_USERS,
    make_hauler_headers,
    make_recycler_headers,
    make_registrant_headers,
    make_site_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_2 = TEST_USERS["admin_2_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
AUDITOR_2 = TEST_USERS["auditor_2_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str) -> dict:
    """Move the server's logical clock; every later comparison reads the new value."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# State programs
# ---------------------------------------------------------------------------


def create_program(api, **overrides) -> dict:
    return get_success_data(
        api.create_state_program(create_state_program_payload(**overrides), ADMIN)
    )


def create_ca_program(api, **overrides) -> dict:
    return get_success_data(api.create_state_program(ca_program_payload(**overrides), ADMIN))


def create_wa_program(api, **overrides) -> dict:
    return get_success_data(api.create_state_program(wa_program_payload(**overrides), ADMIN))


def read_program(api, program_id, headers=None) -> dict:
    return get_success_data(api.get_state_program(program_id, headers or ADMIN))


def revise_forecast(api, program_id, payload, headers=None) -> dict:
    return get_success_data(api.update_cost_forecast(program_id, payload, headers or ADMIN))


def read_fee_adequacy(api, program_id, headers=None) -> dict:
    return get_success_data(api.get_fee_adequacy(program_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Fee rate schedules
# ---------------------------------------------------------------------------


def propose_rate(
    api,
    program_id,
    unit_class="MATTRESS",
    fee_cents_per_unit=1100,
    effective_from="2026-01-01T00:00:00Z",
    effective_to=None,
    headers=None,
    expected_state_program_version=None,
) -> dict:
    """Propose a rate, pinning the program version the proposer last observed."""
    if expected_state_program_version is None:
        expected_state_program_version = read_program(api, program_id)["version"]
    payload = create_fee_rate_schedule_payload(
        program_id,
        expected_state_program_version,
        unit_class=unit_class,
        fee_cents_per_unit=fee_cents_per_unit,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api.create_fee_rate_schedule(payload, headers or ADMIN))


def approve_rate(api, schedule_id, headers=None) -> dict:
    """Approval needs a second administrator user, so it defaults to admin-2."""
    return get_success_data(api.approve_fee_rate_schedule(schedule_id, headers or ADMIN_2))


def activate_rate(api, schedule_id, headers=None) -> dict:
    return get_success_data(api.activate_fee_rate_schedule(schedule_id, headers or ADMIN))


def create_active_rate(
    api,
    program_id,
    unit_class="MATTRESS",
    fee_cents_per_unit=1100,
    effective_from="2026-01-01T00:00:00Z",
    effective_to=None,
) -> dict:
    """Propose, approve and activate one rate.

    The logical clock must already have reached `effective_from`, because a rate
    cannot be activated before it takes effect.
    """
    schedule = propose_rate(
        api,
        program_id,
        unit_class=unit_class,
        fee_cents_per_unit=fee_cents_per_unit,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    approve_rate(api, schedule["id"])
    return activate_rate(api, schedule["id"])


def create_approved_rate(
    api,
    program_id,
    unit_class="MATTRESS",
    fee_cents_per_unit=1100,
    effective_from="2026-01-01T00:00:00Z",
    effective_to=None,
) -> dict:
    schedule = propose_rate(
        api,
        program_id,
        unit_class=unit_class,
        fee_cents_per_unit=fee_cents_per_unit,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    return approve_rate(api, schedule["id"])


# ---------------------------------------------------------------------------
# Registrants and remittances
# ---------------------------------------------------------------------------


def create_registrant(api, **overrides) -> dict:
    return get_success_data(
        api.create_registrant(create_registrant_payload(**overrides), ADMIN)
    )


def create_remittance(api, registrant_id, program_id, **overrides) -> dict:
    return get_success_data(
        api.create_sales_remittance(
            create_sales_remittance_payload(registrant_id, program_id, **overrides),
            make_registrant_headers(registrant_id),
        )
    )


def attach_claim(api, remittance_id, registrant_id, **overrides) -> dict:
    """Attach one exemption claim. A `documentation_reference` of None means the
    registrant has no certificate, so the optional field is left off the request."""
    payload = create_exemption_claim_payload(**overrides)
    if payload.get("documentation_reference") is None:
        payload.pop("documentation_reference", None)
    return get_success_data(
        api.create_exemption_claim(
            remittance_id, payload, make_registrant_headers(registrant_id)
        )
    )


def file_remittance(api, remittance_id, registrant_id) -> dict:
    return get_success_data(
        api.file_sales_remittance(remittance_id, make_registrant_headers(registrant_id))
    )


def pay_remittance(api, remittance_id, registrant_id, amount_cents) -> dict:
    return get_success_data(
        api.pay_sales_remittance(
            remittance_id,
            {"amount_cents": amount_cents},
            make_registrant_headers(registrant_id),
        )
    )


def open_audit(api, remittance_id, headers=None) -> dict:
    return get_success_data(api.open_remittance_audit(remittance_id, headers or AUDITOR))


def adjudicate_claim(api, claim_id, decision, disallow_reason=None, headers=None) -> dict:
    payload = {"decision": decision}
    if disallow_reason is not None:
        payload["disallow_reason"] = disallow_reason
    return get_success_data(
        api.adjudicate_exemption_claim(claim_id, payload, headers or AUDITOR)
    )


def request_amendment(api, remittance_id, note, headers=None) -> dict:
    return get_success_data(
        api.request_remittance_amendment(remittance_id, {"note": note}, headers or AUDITOR)
    )


def submit_amendment(
    api,
    remittance_id,
    registrant_id,
    units_sold_mattress,
    units_sold_foundation,
    expected_remittance_version,
) -> dict:
    """Returns the audited parent, which is what this operation responds with."""
    return get_success_data(
        api.create_remittance_amendment(
            remittance_id,
            {
                "units_sold_mattress": units_sold_mattress,
                "units_sold_foundation": units_sold_foundation,
                "expected_remittance_version": expected_remittance_version,
            },
            make_registrant_headers(registrant_id),
        )
    )


def close_audit(api, remittance_id, headers=None) -> dict:
    """Closing defaults to auditor-2 so the segregation-of-duties rule is satisfied
    even when auditor-1 requested an amendment."""
    return get_success_data(api.close_remittance_audit(remittance_id, headers or AUDITOR_2))


# ---------------------------------------------------------------------------
# Collection sites and volume reports
# ---------------------------------------------------------------------------


def create_site(api, program_id, **overrides) -> dict:
    return get_success_data(
        api.create_collection_site(
            create_collection_site_payload(program_id, **overrides), ADMIN
        )
    )


def enroll_site(api, site_id) -> dict:
    return get_success_data(api.enroll_collection_site(site_id, ADMIN))


def create_enrolled_site(api, program_id, **overrides) -> dict:
    site = create_site(api, program_id, **overrides)
    return enroll_site(api, site["id"])


def suspend_site(api, site_id, reason) -> dict:
    return get_success_data(api.suspend_collection_site(site_id, {"reason": reason}, ADMIN))


def reinstate_site(api, site_id) -> dict:
    return get_success_data(api.reinstate_collection_site(site_id, ADMIN))


def submit_volume_report(api, site_id, **overrides) -> dict:
    return get_success_data(
        api.create_volume_report(
            site_id,
            create_volume_report_payload(**overrides),
            make_site_operator_headers(site_id),
        )
    )


def accept_volume_report(api, report_id, headers=None) -> dict:
    return get_success_data(api.accept_volume_report(report_id, headers or ADMIN))


def create_accepted_volume_report(api, site_id, **overrides) -> dict:
    report = submit_volume_report(api, site_id, **overrides)
    return accept_volume_report(api, report["id"])


# ---------------------------------------------------------------------------
# Haulers, recyclers and commodity output
# ---------------------------------------------------------------------------


def create_hauler(api, program_id, **overrides) -> dict:
    return get_success_data(
        api.create_hauler(create_hauler_payload(program_id, **overrides), ADMIN)
    )


def create_recycler(api, program_id, **overrides) -> dict:
    return get_success_data(
        api.create_recycler(create_recycler_payload(program_id, **overrides), ADMIN)
    )


def certify_recycler(api, recycler_id) -> dict:
    return get_success_data(api.certify_recycler(recycler_id, ADMIN))


def create_certified_recycler(api, program_id, **overrides) -> dict:
    recycler = create_recycler(api, program_id, **overrides)
    return certify_recycler(api, recycler["id"])


def suspend_certification(api, recycler_id, reason) -> dict:
    return get_success_data(
        api.suspend_recycler_certification(recycler_id, {"reason": reason}, ADMIN)
    )


def submit_commodity_output(api, recycler_id, **overrides) -> dict:
    return get_success_data(
        api.create_commodity_output_record(
            recycler_id,
            create_commodity_output_record_payload(**overrides),
            make_recycler_headers(recycler_id),
        )
    )


def verify_commodity_output(api, record_id, headers=None) -> dict:
    return get_success_data(
        api.verify_commodity_output_record(record_id, headers or AUDITOR)
    )


def create_verified_commodity_output(api, recycler_id, **overrides) -> dict:
    record = submit_commodity_output(api, recycler_id, **overrides)
    return verify_commodity_output(api, record["id"])


# ---------------------------------------------------------------------------
# Pickup orders, inspections and settlement
# ---------------------------------------------------------------------------


def dispatch_order(api, site_id, recycler_id, **overrides) -> dict:
    return get_success_data(
        api.create_pickup_order(
            create_pickup_order_payload(site_id, recycler_id, **overrides),
            make_site_operator_headers(site_id),
        )
    )


def confirm_pickup(api, order_id, hauler_id) -> dict:
    return get_success_data(api.confirm_pickup(order_id, make_hauler_headers(hauler_id)))


def deliver_order(api, order_id, hauler_id, units_delivered) -> dict:
    return get_success_data(
        api.deliver_pickup_order(
            order_id,
            {"units_delivered": units_delivered},
            make_hauler_headers(hauler_id),
        )
    )


def pickup_and_deliver(api, order_id, hauler_id, units_delivered) -> dict:
    confirm_pickup(api, order_id, hauler_id)
    return deliver_order(api, order_id, hauler_id, units_delivered)


def inspect_load(
    api, order_id, recycler_id, contaminated_unit_count, infestation_finding="NONE"
) -> dict:
    return get_success_data(
        api.create_load_inspection(
            order_id,
            create_load_inspection_payload(
                contaminated_unit_count=contaminated_unit_count,
                infestation_finding=infestation_finding,
            ),
            make_recycler_headers(recycler_id),
        )
    )


def finalize_settlement(api, order_id, headers=None) -> dict:
    return get_success_data(api.finalize_settlement(order_id, headers or ADMIN))


def void_order(api, order_id, site_id, reason) -> dict:
    return get_success_data(
        api.void_pickup_order(
            order_id, {"reason": reason}, make_site_operator_headers(site_id)
        )
    )


# ---------------------------------------------------------------------------
# Take-back deliveries
# ---------------------------------------------------------------------------


def create_take_back(api, registrant_id, site_id, **overrides) -> dict:
    return get_success_data(
        api.create_take_back_delivery(
            create_take_back_delivery_payload(registrant_id, site_id, **overrides),
            make_registrant_headers(registrant_id),
        )
    )


def complete_take_back(api, delivery_id, registrant_id, units_takeback_collected) -> dict:
    return get_success_data(
        api.complete_takeback(
            delivery_id,
            {"units_takeback_collected": units_takeback_collected},
            make_registrant_headers(registrant_id),
        )
    )


def waive_take_back(api, delivery_id, registrant_id, waiver_reference) -> dict:
    return get_success_data(
        api.waive_takeback(
            delivery_id,
            {"waiver_reference": waiver_reference},
            make_registrant_headers(registrant_id),
        )
    )


# ---------------------------------------------------------------------------
# Composite chains — remittance side
# ---------------------------------------------------------------------------


def setup_draft_remittance(api) -> dict:
    """California program, one ACTIVE mattress rate of 1100 cents effective from
    2026-01-01, one registrant, and a DRAFT 2026Q2 remittance for 500 mattress
    units and no foundation units.

    Filing on the startup clock (2026-08-01) is past twenty days after the
    quarter's end, so the filing is not early and the self-assessed fee is the
    undiscounted 550,000 cents.
    """
    program = create_ca_program(api)
    schedule = create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    return {
        "program": program,
        "program_id": program["id"],
        "schedule": schedule,
        "schedule_id": schedule["id"],
        "registrant": registrant,
        "registrant_id": registrant["id"],
        "registrant_headers": make_registrant_headers(registrant["id"]),
        "remittance": remittance,
        "remittance_id": remittance["id"],
    }


def setup_filed_remittance(api) -> dict:
    chain = setup_draft_remittance(api)
    chain["remittance"] = file_remittance(api, chain["remittance_id"], chain["registrant_id"])
    return chain


def setup_paid_remittance(api) -> dict:
    chain = setup_filed_remittance(api)
    chain["remittance"] = pay_remittance(
        api, chain["remittance_id"], chain["registrant_id"], 550000
    )
    return chain


def setup_remittance_under_audit(api) -> dict:
    chain = setup_paid_remittance(api)
    chain["remittance"] = open_audit(api, chain["remittance_id"])
    return chain


def setup_amendment_required_remittance(
    api, note="Reconcile 2026Q2 unit counts against the shipment log"
) -> dict:
    chain = setup_remittance_under_audit(api)
    chain["remittance"] = request_amendment(api, chain["remittance_id"], note)
    chain["amendment_note"] = note
    return chain


def setup_ca_quarterly_fee_chain(api, with_mattress_successor=True) -> dict:
    """The California fourth-quarter filing that both fee variants are read from.

    Foundation is priced at 900 cents from 2026-08-01 through 2027-01-01, and
    mattress at 1100 cents from 2026-08-01. When a successor is requested the
    mattress rate rises to 1200 cents from 2026-11-01, which supersedes the
    1100-cent schedule mid-quarter, so the two variants read different mattress
    rates: the self-assessed variant prices at `period_start` and the
    audit-reconciled variant prices at `period_end`.

    The clock ends at 2027-01-10, inside the twenty-day early-filing window.
    """
    program = create_ca_program(api)
    foundation = create_active_rate(
        api,
        program["id"],
        unit_class="FOUNDATION",
        fee_cents_per_unit=900,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )
    mattress = create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z" if with_mattress_successor else None,
    )
    successor = None
    if with_mattress_successor:
        set_clock(api, "2026-11-01T00:00:00Z")
        successor = create_active_rate(
            api,
            program["id"],
            unit_class="MATTRESS",
            fee_cents_per_unit=1200,
            effective_from="2026-11-01T00:00:00Z",
        )
    set_clock(api, "2027-01-10T00:00:00Z")
    registrant = create_registrant(
        api,
        legal_name="Pacific Bedding Retail LLC",
        registrant_type="RETAILER",
        home_state_code="CA",
    )
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q4",
        units_sold_mattress=1001,
        units_sold_foundation=400,
    )
    foundation_claim = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="OUT_OF_STATE_SHIPMENT",
        unit_class="FOUNDATION",
        units=43,
        documentation_reference="BOL-CA-4471",
    )
    mattress_claim = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="EXEMPT_SALE",
        unit_class="MATTRESS",
        units=120,
        documentation_reference=None,
    )
    return {
        "program": program,
        "program_id": program["id"],
        "foundation_schedule": foundation,
        "mattress_schedule": mattress,
        "mattress_successor": successor,
        "registrant": registrant,
        "registrant_id": registrant["id"],
        "registrant_headers": make_registrant_headers(registrant["id"]),
        "remittance": remittance,
        "remittance_id": remittance["id"],
        "foundation_claim": foundation_claim,
        "foundation_claim_id": foundation_claim["id"],
        "mattress_claim": mattress_claim,
        "mattress_claim_id": mattress_claim["id"],
    }


def setup_ca_quarterly_filed_and_paid(api, with_mattress_successor=True) -> dict:
    """The California fourth-quarter filing, filed early and paid in full at the
    self-assessed 1,271,043 cents."""
    chain = setup_ca_quarterly_fee_chain(
        api, with_mattress_successor=with_mattress_successor
    )
    chain["remittance"] = file_remittance(api, chain["remittance_id"], chain["registrant_id"])
    chain["remittance"] = pay_remittance(
        api, chain["remittance_id"], chain["registrant_id"], 1271043
    )
    return chain


def setup_ca_quarterly_audit_adjudicated(api) -> dict:
    """The California fourth-quarter filing under audit with its foundation claim
    substantiated and its undocumented mattress claim disallowed."""
    chain = setup_ca_quarterly_filed_and_paid(api, with_mattress_successor=True)
    chain["remittance"] = open_audit(api, chain["remittance_id"])
    chain["foundation_claim"] = adjudicate_claim(
        api, chain["foundation_claim_id"], "SUBSTANTIATE"
    )
    chain["mattress_claim"] = adjudicate_claim(
        api, chain["mattress_claim_id"], "DISALLOW", disallow_reason="MISSING_DOCUMENTATION"
    )
    return chain


def setup_ca_amendment_cycle_chain(api) -> dict:
    """A California filing with open-ended foundation and mattress rates, filed
    early and paid at 719,050 cents, and opened for audit."""
    program = create_ca_program(api)
    foundation = create_active_rate(
        api,
        program["id"],
        unit_class="FOUNDATION",
        fee_cents_per_unit=900,
        effective_from="2026-08-01T00:00:00Z",
    )
    mattress = create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-08-01T00:00:00Z",
    )
    set_clock(api, "2027-01-10T00:00:00Z")
    registrant = create_registrant(
        api,
        legal_name="Bay Sleep Manufacturing Inc",
        registrant_type="MANUFACTURER",
        home_state_code="CA",
    )
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q4",
        units_sold_mattress=500,
        units_sold_foundation=200,
    )
    file_remittance(api, remittance["id"], registrant["id"])
    pay_remittance(api, remittance["id"], registrant["id"], 719050)
    remittance = open_audit(api, remittance["id"])
    return {
        "program": program,
        "program_id": program["id"],
        "foundation_schedule": foundation,
        "mattress_schedule": mattress,
        "registrant": registrant,
        "registrant_id": registrant["id"],
        "registrant_headers": make_registrant_headers(registrant["id"]),
        "remittance": remittance,
        "remittance_id": remittance["id"],
    }


# ---------------------------------------------------------------------------
# Composite chains — logistics side
# ---------------------------------------------------------------------------


def setup_enrolled_site(api) -> dict:
    """A Washington program with one ENROLLED transfer station in region NORTH."""
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    return {
        "program": program,
        "program_id": program["id"],
        "site": site,
        "site_id": site["id"],
        "site_headers": make_site_operator_headers(site["id"]),
    }


def setup_logistics_chain(api, units_mattress=320, units_foundation=190) -> dict:
    """A Washington program with an ENROLLED NORTH site holding stock, one NORTH
    hauler and one CERTIFIED recycler.

    The site's stock arrives through an accepted 2026-08 volume report, so the
    default 320 plus 190 units clear the 500-unit bonus threshold and leave 510
    units on hand.
    """
    chain = setup_enrolled_site(api)
    hauler = create_hauler(api, chain["program_id"])
    recycler = create_certified_recycler(api, chain["program_id"])
    report = create_accepted_volume_report(
        api,
        chain["site_id"],
        period_month="2026-08",
        units_mattress=units_mattress,
        units_foundation=units_foundation,
    )
    chain.update(
        {
            "hauler": hauler,
            "hauler_id": hauler["id"],
            "hauler_headers": make_hauler_headers(hauler["id"]),
            "recycler": recycler,
            "recycler_id": recycler["id"],
            "recycler_headers": make_recycler_headers(recycler["id"]),
            "report": report,
            "report_id": report["id"],
        }
    )
    return chain


def setup_scheduled_order(api, **order_overrides) -> dict:
    """The logistics chain with one SCHEDULED pickup order on it."""
    chain = setup_logistics_chain(api)
    order = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        **order_overrides,
    )
    chain["order"] = order
    chain["order_id"] = order["id"]
    return chain


def setup_delivered_order(api, units_delivered=240, **order_overrides) -> dict:
    """The logistics chain with one order picked up and delivered, so its
    fulfillment axis sits at DELIVERED and its settlement axis at ESTIMATED."""
    chain = setup_scheduled_order(api, **order_overrides)
    chain["order"] = pickup_and_deliver(
        api, chain["order_id"], chain["hauler_id"], units_delivered
    )
    return chain


def setup_inspected_order(
    api,
    contaminated_unit_count=12,
    units_delivered=240,
    infestation_finding="NONE",
    **order_overrides,
) -> dict:
    """The logistics chain with one delivered and inspected order."""
    chain = setup_delivered_order(api, units_delivered=units_delivered, **order_overrides)
    chain["inspection"] = inspect_load(
        api,
        chain["order_id"],
        chain["recycler_id"],
        contaminated_unit_count,
        infestation_finding=infestation_finding,
    )
    return chain


def setup_site_with_contamination_strikes(api, strikes=2) -> dict:
    """The logistics chain after `strikes` fully rejected loads, each one a
    100-unit order inspected at six contaminated units — six percent, above the
    five percent ceiling — on its own non-overlapping day.

    The strike counter is left one below the three-strike suspension threshold
    when two strikes are requested.
    """
    chain = setup_logistics_chain(api)
    chain["strike_orders"] = []
    for index in range(strikes):
        day = 5 + index * 2
        order = dispatch_order(
            api,
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=100,
            route_distance_km=40.0,
            pickup_window_start=f"2026-08-{day:02d}T09:00:00Z",
            pickup_window_end=f"2026-08-{day:02d}T11:00:00Z",
        )
        pickup_and_deliver(api, order["id"], chain["hauler_id"], 100)
        inspect_load(api, order["id"], chain["recycler_id"], 6)
        chain["strike_orders"].append(order)
    return chain


def setup_quarantined_site(api) -> dict:
    """The logistics chain after a bed-bug finding on a delivered load, which
    quarantines the source site for fourteen days from the inspection instant."""
    chain = setup_delivered_order(
        api,
        units_delivered=100,
        units_manifested=100,
        route_distance_km=40.0,
    )
    chain["inspection"] = inspect_load(
        api, chain["order_id"], chain["recycler_id"], 0, infestation_finding="BED_BUG"
    )
    return chain
