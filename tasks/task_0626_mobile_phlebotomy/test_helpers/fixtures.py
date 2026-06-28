"""Composite setup helpers for the Mobile Phlebotomy API.

These encapsulate the multi-step preambles (catalog -> phlebotomist -> route day ->
order -> appointment -> draw -> manifest -> accession/result -> invoice) that nearly
every interesting claim requires. Every fixture builds its preconditions from scratch
using only PRD-declared endpoints; the test harness restarts the server (empty DB)
before each test.

Phlebotomist is the one entity-backed role: ownership-gated on-site actions (arrive,
collect, complete-draw, add-specimen) MUST be issued with make_phlebotomist_headers(phleb_id)
carrying the real Phlebotomist.id, never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_phlebotomist_headers
from . import factories as F


_LABOPS = TEST_USERS["lab_ops_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]
_PROVIDER = TEST_USERS["ordering_provider_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: catalog + field building blocks
# ---------------------------------------------------------------------------

def create_panel(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000, name="CMP", **overrides):
    payload = F.create_test_panel_payload(
        panel_code=panel_code, name=name,
        required_tube_count=required_tube_count, base_lab_fee_cents=base_lab_fee_cents,
        **overrides,
    )
    return get_success_data(api_client.create_test_panel(payload, _LABOPS))


def create_partner(name="Quest", accepted_panel_codes=None, courier_sla_hours=24,
                   stat_surcharge_cents=None, **overrides):
    if accepted_panel_codes is None:
        accepted_panel_codes = ["CMP14"]
    payload = F.create_lab_partner_payload(
        name=name, courier_sla_hours=courier_sla_hours,
        accepted_panel_codes=accepted_panel_codes, **overrides,
    )
    if stat_surcharge_cents is not None:
        payload["stat_surcharge_cents"] = stat_surcharge_cents
    return get_success_data(api_client.create_lab_partner(payload, _DISPATCHER if False else _LABOPS))


def create_phleb(full_name="Pat", territory_code="SF_BAY", **overrides):
    payload = F.create_phlebotomist_payload(full_name=full_name, territory_code=territory_code, **overrides)
    return get_success_data(api_client.create_phlebotomist(payload, _DISPATCHER))


def create_route_day(phleb_id, territory_code="SF_BAY", service_date="2026-02-01",
                     shift_start_utc="2026-02-01T08:00:00Z", shift_end_utc="2026-02-01T18:00:00Z",
                     stop_capacity=10, **overrides):
    payload = F.create_route_day_payload(
        territory_code=territory_code, service_date=service_date,
        shift_start_utc=shift_start_utc, shift_end_utc=shift_end_utc,
        stop_capacity=stop_capacity, **overrides,
    )
    return get_success_data(api_client.create_route_day(phleb_id, payload, _DISPATCHER))


def create_order(partner_id, panel_code="CMP14", billing_mode="SELF_PAY", priority=None,
                 patient_territory_code="SF_BAY", insurance_member_id=None,
                 patient_full_name="Sam", **overrides):
    payload = F.create_lab_order_payload(
        panel_code=panel_code, lab_partner_id=partner_id, billing_mode=billing_mode,
        patient_territory_code=patient_territory_code, patient_full_name=patient_full_name,
        **overrides,
    )
    if priority is not None:
        payload["priority"] = priority
    if insurance_member_id is not None:
        payload["insurance_member_id"] = insurance_member_id
    return get_success_data(api_client.create_lab_order(payload, _PROVIDER))


def get_route_day_version(route_day_id):
    rd = get_success_data(api_client.get_route_day(route_day_id, _DISPATCHER))
    return rd["version"]


def book(order_id, route_day_id, expected_version,
         window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z"):
    payload = F.book_appointment_payload(
        route_day_id, expected_version,
        window_start_utc=window_start_utc, window_end_utc=window_end_utc,
    )
    return get_success_data(api_client.book_appointment(order_id, payload, _DISPATCHER))


def assign_kit(appt_id, tube_count=3, kit_lot_number="LOT1"):
    payload = F.assign_kit_payload(tube_count=tube_count, kit_lot_number=kit_lot_number)
    return get_success_data(api_client.assign_kit(appt_id, payload, _DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
                  accepted_panel_codes=None, stat_surcharge_cents=None, courier_sla_hours=24):
    """Active panel + partner accepting it. Returns (panel, partner)."""
    if accepted_panel_codes is None:
        accepted_panel_codes = [panel_code]
    panel = create_panel(panel_code=panel_code, required_tube_count=required_tube_count,
                         base_lab_fee_cents=base_lab_fee_cents)
    partner = create_partner(accepted_panel_codes=accepted_panel_codes,
                             stat_surcharge_cents=stat_surcharge_cents,
                             courier_sla_hours=courier_sla_hours)
    return panel, partner


def setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
                                billing_mode="SELF_PAY", priority=None, stat_surcharge_cents=None,
                                insurance_member_id=None,
                                service_date="2026-02-01",
                                shift_start_utc="2026-02-01T08:00:00Z",
                                shift_end_utc="2026-02-01T18:00:00Z",
                                window_start_utc="2026-02-01T09:00:00Z",
                                window_end_utc="2026-02-01T09:30:00Z",
                                stop_capacity=10):
    """Panel + partner + phlebotomist + OPEN route day + ORDERED order + SCHEDULED appointment.

    Returns a dict with keys: panel, partner, phleb, phleb_id, route_day, route_day_id,
    order, order_id, appointment, appt_id.
    """
    panel, partner = setup_catalog(panel_code=panel_code, required_tube_count=required_tube_count,
                                   base_lab_fee_cents=base_lab_fee_cents,
                                   accepted_panel_codes=[panel_code],
                                   stat_surcharge_cents=stat_surcharge_cents)
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], service_date=service_date, shift_start_utc=shift_start_utc,
                          shift_end_utc=shift_end_utc, stop_capacity=stop_capacity)
    order = create_order(partner["id"], panel_code=panel_code, billing_mode=billing_mode,
                         priority=priority, insurance_member_id=insurance_member_id)
    appt = book(order["id"], rd["id"], rd["version"],
                window_start_utc=window_start_utc, window_end_utc=window_end_utc)
    return {
        "panel": panel, "partner": partner, "partner_id": partner["id"],
        "phleb": phleb, "phleb_id": phleb["id"],
        "route_day": rd, "route_day_id": rd["id"],
        "order": order, "order_id": order["id"],
        "appointment": appt, "appt_id": appt["id"],
    }


def drive_to_arrived(ctx, kit_tube_count=None):
    """From a SCHEDULED-appointment ctx: assign kit, dispatch, arrive. Mutates and returns ctx."""
    if kit_tube_count is None:
        kit_tube_count = ctx["order"]["specimens_required_count"]
    assign_kit(ctx["appt_id"], tube_count=kit_tube_count)
    get_success_data(api_client.dispatch_appointment(ctx["appt_id"], _DISPATCHER))
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(api_client.arrive_appointment(ctx["appt_id"], phleb_headers))
    return ctx


def collect_specimens(ctx, tube_labels):
    """Collect one specimen per label using the assigned phlebotomist. Returns list of specimens."""
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    specimens = []
    for label in tube_labels:
        sp = get_success_data(
            api_client.collect_specimen(ctx["appt_id"], F.collect_specimen_payload(label), phleb_headers)
        )
        specimens.append(sp)
    return specimens


def drive_to_draw_completed(ctx, tube_labels=None):
    """From a SCHEDULED-appointment ctx: assign kit, dispatch, arrive, collect all tubes,
    complete-draw. Stores ctx['specimens']. Returns ctx."""
    required = ctx["order"]["specimens_required_count"]
    if tube_labels is None:
        tube_labels = [f"T{i+1}" for i in range(required)]
    drive_to_arrived(ctx, kit_tube_count=max(required, len(tube_labels)))
    ctx["specimens"] = collect_specimens(ctx, tube_labels)
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(api_client.complete_draw(ctx["appt_id"], phleb_headers))
    return ctx


def build_in_transit_manifest(ctx, specimen_ids=None, territory_code="SF_BAY"):
    """Open a manifest for the order's partner, add the given specimens (default: all of
    ctx['specimens']), record pickup. Returns the IN_TRANSIT manifest dict."""
    if specimen_ids is None:
        specimen_ids = [sp["id"] for sp in ctx["specimens"]]
    manifest = get_success_data(
        api_client.create_manifest(F.create_manifest_payload(ctx["partner_id"], territory_code=territory_code), _DISPATCHER)
    )
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    for sid in specimen_ids:
        get_success_data(
            api_client.add_specimen_to_manifest(manifest["id"], {"specimen_id": sid}, phleb_headers)
        )
    manifest = get_success_data(api_client.pickup_manifest(manifest["id"], _DISPATCHER))
    return manifest


def accession_all(specimen_ids):
    """Accession each specimen (LabOps)."""
    for sid in specimen_ids:
        get_success_data(api_client.accession_specimen(sid, _LABOPS))


def setup_resulted_order(billing_mode="SELF_PAY", priority=None, panel_code="CMP14",
                         required_tube_count=3, base_lab_fee_cents=4000,
                         stat_surcharge_cents=None, insurance_member_id=None,
                         shift_start_utc="2026-02-01T06:00:00Z",
                         shift_end_utc="2026-02-01T22:00:00Z"):
    """Full happy path to a RESULTED order with all specimens accessioned and a DRAFT invoice.

    Returns dict with: order_id, partner_id, phleb_id, route_day_id, specimens, manifest,
    invoice_id, order (final fetch).
    """
    ctx = setup_scheduled_appointment(
        panel_code=panel_code, required_tube_count=required_tube_count,
        base_lab_fee_cents=base_lab_fee_cents, billing_mode=billing_mode, priority=priority,
        stat_surcharge_cents=stat_surcharge_cents, insurance_member_id=insurance_member_id,
        shift_start_utc=shift_start_utc, shift_end_utc=shift_end_utc,
    )
    drive_to_draw_completed(ctx)
    manifest = build_in_transit_manifest(ctx)
    accession_all([sp["id"] for sp in ctx["specimens"]])
    get_success_data(api_client.post_results(ctx["order_id"], F.post_results_payload(), _LABOPS))
    invoices, _ = _list(api_client.list_order_invoices(ctx["order_id"], _BILLING))
    ctx["invoice_id"] = invoices[0]["id"]
    ctx["manifest"] = manifest
    ctx["order"] = get_success_data(api_client.get_lab_order(ctx["order_id"], _PROVIDER))
    return ctx


def setup_resulted_order_after_one_redraw(billing_mode="SELF_PAY", priority="STAT",
                                          panel_code="CMP14", required_tube_count=3,
                                          base_lab_fee_cents=4000, stat_surcharge_cents=1500,
                                          insurance_member_id=None):
    """First draw fully QNS-rejected (redraw_count -> 1), re-drawn and driven to RESULTED with
    a DRAFT invoice. Returns dict with order_id, invoice_id, partner_id, phleb_id."""
    ctx = setup_scheduled_appointment(
        panel_code=panel_code, required_tube_count=required_tube_count,
        base_lab_fee_cents=base_lab_fee_cents, billing_mode=billing_mode, priority=priority,
        stat_surcharge_cents=stat_surcharge_cents, insurance_member_id=insurance_member_id,
        shift_start_utc="2026-02-01T06:00:00Z", shift_end_utc="2026-02-01T22:00:00Z",
        window_start_utc="2026-02-01T09:00:00Z", window_end_utc="2026-02-01T09:30:00Z",
    )
    # First draw: collect all required tubes, complete, manifest, pickup, then QNS-reject all.
    first_labels = [f"T{i+1}" for i in range(required_tube_count)]
    drive_to_draw_completed(ctx, tube_labels=first_labels)
    manifest1 = build_in_transit_manifest(ctx)
    for sp in ctx["specimens"]:
        get_success_data(api_client.reject_qns(sp["id"], _LABOPS))
    # Order is now REDRAW_REQUIRED (redraw_count == 1). Re-book a fresh appointment.
    rd_v = get_route_day_version(ctx["route_day_id"])
    rebook = book(ctx["order_id"], ctx["route_day_id"], rd_v,
                  window_start_utc="2026-02-01T11:00:00Z", window_end_utc="2026-02-01T11:30:00Z")
    ctx["appt_id"] = rebook["id"]
    ctx["appointment"] = rebook
    # Re-fetch order so specimens_required_count is fresh for the second draw.
    ctx["order"] = get_success_data(api_client.get_lab_order(ctx["order_id"], _PROVIDER))
    second_labels = [f"R{i+1}" for i in range(required_tube_count)]
    drive_to_draw_completed(ctx, tube_labels=second_labels)
    manifest2 = build_in_transit_manifest(ctx)
    accession_all([sp["id"] for sp in ctx["specimens"]])
    get_success_data(api_client.post_results(ctx["order_id"], F.post_results_payload(), _LABOPS))
    invoices, _ = _list(api_client.list_order_invoices(ctx["order_id"], _BILLING))
    ctx["invoice_id"] = invoices[0]["id"]
    ctx["order"] = get_success_data(api_client.get_lab_order(ctx["order_id"], _PROVIDER))
    return ctx


def setup_draw_completed_with_in_transit_specimens(billing_mode="SELF_PAY", panel_code="CMP14",
                                                   required_tube_count=3, base_lab_fee_cents=4000,
                                                   stat_surcharge_cents=None,
                                                   manifest_specimen_count=None):
    """DRAW_COMPLETED order whose specimens are all MANIFESTED on a single IN_TRANSIT manifest.

    manifest_specimen_count lets a caller add only a subset of specimens to the manifest
    (used e.g. for single-specimen redraw cascade tests). Returns the ctx dict including
    'specimens' and 'manifest'.
    """
    ctx = setup_scheduled_appointment(
        panel_code=panel_code, required_tube_count=required_tube_count,
        base_lab_fee_cents=base_lab_fee_cents, billing_mode=billing_mode,
        stat_surcharge_cents=stat_surcharge_cents,
    )
    drive_to_draw_completed(ctx)
    ids = [sp["id"] for sp in ctx["specimens"]]
    if manifest_specimen_count is not None:
        ids = ids[:manifest_specimen_count]
    ctx["manifest"] = build_in_transit_manifest(ctx, specimen_ids=ids)
    return ctx


def setup_manifested_specimen_on_building_manifest(panel_code="ONE", required_tube_count=1,
                                                   base_lab_fee_cents=1000):
    """One MANIFESTED specimen on a BUILDING manifest (pickup NOT recorded). Returns ctx with
    'specimens' (the single manifested specimen) and 'manifest' (BUILDING)."""
    ctx = setup_scheduled_appointment(
        panel_code=panel_code, required_tube_count=required_tube_count,
        base_lab_fee_cents=base_lab_fee_cents,
    )
    drive_to_draw_completed(ctx)
    manifest = get_success_data(
        api_client.create_manifest(F.create_manifest_payload(ctx["partner_id"]), _DISPATCHER)
    )
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(
        api_client.add_specimen_to_manifest(manifest["id"], {"specimen_id": ctx["specimens"][0]["id"]}, phleb_headers)
    )
    ctx["manifest"] = get_success_data(api_client.get_manifest(manifest["id"], _DISPATCHER))
    return ctx


def suspend_phlebotomist_via_three_strikes():
    """Drive one phlebotomist to SUSPENDED via 3 QNS-attributable redraws on single-tube
    self-pay orders, then leave a fresh SCHEDULED appointment (order D) with a kit assigned,
    ready to dispatch. Returns dict: phleb_id, route_day_id, partner_id, ready_appt_id."""
    panel, partner = setup_catalog(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
                                   accepted_panel_codes=["ONE"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], shift_start_utc="2026-02-01T06:00:00Z",
                          shift_end_utc="2026-02-01T22:00:00Z", stop_capacity=10)
    phleb_id = phleb["id"]
    partner_id = partner["id"]
    rd_id = rd["id"]
    windows = [("2026-02-01T07:00:00Z", "2026-02-01T07:30:00Z"),
               ("2026-02-01T08:00:00Z", "2026-02-01T08:30:00Z"),
               ("2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z")]
    phleb_headers = make_phlebotomist_headers(phleb_id)
    for i, (ws, we) in enumerate(windows):
        order = create_order(partner_id, panel_code="ONE", billing_mode="SELF_PAY")
        rd_v = get_route_day_version(rd_id)
        appt = book(order["id"], rd_id, rd_v, window_start_utc=ws, window_end_utc=we)
        assign_kit(appt["id"], tube_count=1, kit_lot_number=f"L{i+1}")
        get_success_data(api_client.dispatch_appointment(appt["id"], _DISPATCHER))
        get_success_data(api_client.arrive_appointment(appt["id"], phleb_headers))
        sp = get_success_data(
            api_client.collect_specimen(appt["id"], F.collect_specimen_payload("T1"), phleb_headers)
        )
        get_success_data(api_client.complete_draw(appt["id"], phleb_headers))
        manifest = get_success_data(
            api_client.create_manifest(F.create_manifest_payload(partner_id), _DISPATCHER)
        )
        get_success_data(
            api_client.add_specimen_to_manifest(manifest["id"], {"specimen_id": sp["id"]}, phleb_headers)
        )
        get_success_data(api_client.pickup_manifest(manifest["id"], _DISPATCHER))
        get_success_data(api_client.reject_qns(sp["id"], _LABOPS))
    # Fresh order D ready to dispatch.
    order_d = create_order(partner_id, panel_code="ONE", billing_mode="SELF_PAY")
    rd_v = get_route_day_version(rd_id)
    appt_d = book(order_d["id"], rd_id, rd_v,
                  window_start_utc="2026-02-01T12:00:00Z", window_end_utc="2026-02-01T12:30:00Z")
    assign_kit(appt_d["id"], tube_count=1, kit_lot_number="L4")
    return {
        "phleb_id": phleb_id, "route_day_id": rd_id, "partner_id": partner_id,
        "ready_appt_id": appt_d["id"], "order_d_id": order_d["id"],
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _list(response):
    """Lenient paginated read for setup chains: returns (data_list, meta)."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def first_invoice_id(order_id):
    invoices, _ = _list(api_client.list_order_invoices(order_id, _BILLING))
    return invoices[0]["id"]
