"""
Composite setup helpers for multi-step test prerequisites.

The runner kills and restarts the API server before EVERY test, so each fixture
builds all of its preconditions from scratch against an empty database and the
logical-clock startup default of 2026-05-01T00:00:00Z (PRD §2.8).

All helpers use get_success_data() (lenient validator) so setup failures surface
as clear "Setup failed" errors, not confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_cemetery_payload, create_plot_payload, create_holder_payload,
    create_decedent_payload, create_deed_payload, create_interment_payload,
    create_disinterment_payload, create_marker_permit_payload,
    create_payment_payload, create_care_fund_entry_payload,
)
from .test_users import TEST_USERS, make_right_holder_headers, make_cemetery_director_headers
from .constants import CLOCK_DEFAULT

REG = TEST_USERS["registrar_headers"]
DIR = TEST_USERS["cemetery_director_headers"]
FIN = TEST_USERS["finance_officer_headers"]
GF = TEST_USERS["grounds_foreman_headers"]
HEALTH = TEST_USERS["health_officer_headers"]


# ─── Primitive builders ────────────────────────────────────────────────

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, REG))


def create_cemetery(crew_team_count=1, name="Oakwood"):
    return get_success_data(api_client.create_cemetery(
        create_cemetery_payload(name=name, crew_team_count=crew_team_count), DIR))


def create_plot(cemetery_id, plot_type="GRAVE", interment_capacity=2,
                section_code="A", row="1", plot_number="1", gis_lng=2.0):
    return get_success_data(api_client.create_plot(
        create_plot_payload(cemetery_id, plot_type=plot_type,
                            interment_capacity=interment_capacity,
                            section_code=section_code, row=row,
                            plot_number=plot_number, gis_lng=gis_lng), REG))


def create_holder(full_name="H One", email="h1@x.com", phone="1"):
    return get_success_data(api_client.create_holder(
        create_holder_payload(full_name=full_name, email=email, phone=phone), REG))


def create_decedent(full_name="Dec A", date_of_death="2026-04-01", **kw):
    return get_success_data(api_client.create_decedent(
        create_decedent_payload(full_name=full_name, date_of_death=date_of_death, **kw), REG))


def pay_invoice(invoice_id, method="CARD"):
    """GET the invoice then pay exactly its total_cents (PRD §3.7)."""
    inv = get_success_data(api_client.get_invoice(invoice_id, FIN))
    return get_success_data(api_client.create_payment(
        create_payment_payload(invoice_id, inv["total_cents"], method), FIN))


# ─── Tier 1/2: Deed lifecycle ──────────────────────────────────────────

def setup_pending_deed(purchase_price_cents=1000000, sale_type="NEW_SALE",
                       crew_team_count=1, plot_type="GRAVE", interment_capacity=2,
                       deed_headers=None):
    """cemetery + plot + holder + PENDING_PAYMENT deed (RESERVED plot).

    Returns dict with cemetery, holder, plot, deed, sale_invoice_id.
    """
    cem = create_cemetery(crew_team_count)
    holder = create_holder()
    plot = create_plot(cem["id"], plot_type=plot_type, interment_capacity=interment_capacity)
    deed = get_success_data(api_client.create_deed(
        create_deed_payload(plot["id"], holder["id"], plot["version"],
                            purchase_price_cents=purchase_price_cents,
                            sale_type=sale_type),
        deed_headers or REG))
    return {
        "cemetery": cem, "holder": holder, "plot": plot,
        "deed": deed, "sale_invoice_id": deed["sale_invoice_id"],
    }


def setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE",
                      crew_team_count=1, plot_type="GRAVE", interment_capacity=2):
    """cemetery + plot + holder + ISSUED deed (DEED_SALE invoice paid, plot SOLD).

    Returns dict with cemetery, holder, plot (SOLD), deed (ISSUED), sale_invoice_id.
    """
    r = setup_pending_deed(purchase_price_cents, sale_type, crew_team_count,
                           plot_type, interment_capacity)
    pay_invoice(r["sale_invoice_id"])
    r["deed"] = get_success_data(api_client.get_deed(r["deed"]["id"], REG))
    r["plot"] = get_success_data(api_client.get_plot(r["plot"]["id"], REG))
    return r


# ─── Tier 3: Interment lifecycle ───────────────────────────────────────

def setup_scheduled_interment(purchase_price_cents=1000000, sale_type="NEW_SALE",
                              crew_team_count=1, plot_type="GRAVE",
                              interment_capacity=2, depth_position=1,
                              interment_type="BURIAL",
                              scheduled_date="2026-06-01",
                              scheduled_start="2026-06-01T09:00:00Z",
                              scheduled_end="2026-06-01T11:00:00Z",
                              clock=CLOCK_DEFAULT, pay_service=False):
    """Issued deed + decedent + SCHEDULED interment (billing INVOICED).

    Returns dict adding decedent, interment, service_invoice_id to setup_issued_deed.
    """
    set_clock(clock)
    r = setup_issued_deed(purchase_price_cents, sale_type, crew_team_count,
                          plot_type, interment_capacity)
    dec = create_decedent()
    interment = get_success_data(api_client.create_interment(
        create_interment_payload(r["plot"]["id"], dec["id"], r["deed"]["id"],
                                 interment_type=interment_type,
                                 depth_position=depth_position,
                                 scheduled_date=scheduled_date,
                                 scheduled_start=scheduled_start,
                                 scheduled_end=scheduled_end), REG))
    r["decedent"] = dec
    r["interment"] = interment
    r["service_invoice_id"] = interment["service_invoice_id"]
    if pay_service:
        pay_invoice(r["service_invoice_id"])
        r["interment"] = get_success_data(api_client.get_interment(interment["id"], REG))
    return r


def add_second_interment(r, decedent=None, deed_id=None, plot_id=None,
                         interment_type="ENTOMBMENT", depth_position=2,
                         scheduled_date="2026-06-08",
                         scheduled_start="2026-06-08T09:00:00Z",
                         scheduled_end="2026-06-08T11:00:00Z"):
    """Schedule a second interment on the same plot/deed. Returns the interment."""
    dec = decedent or create_decedent(full_name="Dec B", date_of_death="2026-04-02")
    return get_success_data(api_client.create_interment(
        create_interment_payload(plot_id or r["plot"]["id"], dec["id"],
                                 deed_id or r["deed"]["id"],
                                 interment_type=interment_type,
                                 depth_position=depth_position,
                                 scheduled_date=scheduled_date,
                                 scheduled_start=scheduled_start,
                                 scheduled_end=scheduled_end), REG))


def setup_completed_interment(scheduled_date="2026-06-01", **kwargs):
    """Schedule + pay service + open + complete. Interment ends COMPLETED.

    Returns the setup_scheduled_interment dict with interment now COMPLETED.
    """
    r = setup_scheduled_interment(scheduled_date=scheduled_date, pay_service=True, **kwargs)
    set_clock(scheduled_date + "T00:00:00Z")
    get_success_data(api_client.open_interment(r["interment"]["id"], GF))
    get_success_data(api_client.complete_interment(r["interment"]["id"], GF))
    r["interment"] = get_success_data(api_client.get_interment(r["interment"]["id"], REG))
    return r


# ─── Tier 4: Disinterment lifecycle ────────────────────────────────────

def setup_disinterment_requested(disinterment_type="REMOVAL", target_plot_id=None,
                                 reason="removal", **kwargs):
    """Completed interment + REQUESTED DisintermentAuthorization (invoice unpaid).

    Returns dict adding auth and disinterment_invoice_id.
    """
    r = setup_completed_interment(**kwargs)
    tp = r["plot"]["id"] if (disinterment_type == "RELOCATION" and target_plot_id is None) else target_plot_id
    auth = get_success_data(api_client.create_disinterment(
        create_disinterment_payload(r["interment"]["id"], reason=reason,
                                    disinterment_type=disinterment_type,
                                    target_plot_id=tp), REG))
    r["auth"] = auth
    r["disinterment_invoice_id"] = auth["disinterment_invoice_id"]
    return r


def setup_disinterment_approved(disinterment_type="REMOVAL", approver_id="dir-approver",
                                pay_disinterment=True, **kwargs):
    """Fork-join complete + APPROVED (by approver_id). Optionally pays DISINTERMENT invoice.

    Returns dict adding approver_id; auth ends APPROVED.
    """
    r = setup_disinterment_requested(disinterment_type=disinterment_type, **kwargs)
    get_success_data(api_client.record_clearance(r["auth"]["id"], HEALTH))
    get_success_data(api_client.record_consent(
        r["auth"]["id"], make_right_holder_headers(r["holder"]["id"])))
    get_success_data(api_client.approve_disinterment(
        r["auth"]["id"], make_cemetery_director_headers(approver_id)))
    if pay_disinterment:
        pay_invoice(r["disinterment_invoice_id"])
    r["auth"] = get_success_data(api_client.get_disinterment(r["auth"]["id"], REG))
    r["approver_id"] = approver_id
    return r


# ─── Tier 5: Marker permit lifecycle ───────────────────────────────────

def setup_applied_marker(marker_type="FLAT", **deed_kwargs):
    """Issued deed + APPLIED MarkerPermit (foundation invoice unpaid).

    Returns dict adding permit and foundation_invoice_id.
    """
    r = setup_issued_deed(**deed_kwargs)
    permit = get_success_data(api_client.create_marker_permit(
        create_marker_permit_payload(r["plot"]["id"], r["deed"]["id"],
                                     marker_type=marker_type), REG))
    r["permit"] = permit
    r["foundation_invoice_id"] = permit["foundation_invoice_id"]
    return r


def setup_approved_marker(marker_type="FLAT", pay_foundation=True, **deed_kwargs):
    """APPROVED MarkerPermit; optionally pays the MARKER_FOUNDATION invoice.

    Returns dict adding permit (APPROVED) and foundation_invoice_id.
    """
    r = setup_applied_marker(marker_type=marker_type, **deed_kwargs)
    get_success_data(api_client.approve_marker_permit(r["permit"]["id"], DIR))
    if pay_foundation:
        pay_invoice(r["foundation_invoice_id"])
    r["permit"] = get_success_data(api_client.get_marker_permit(r["permit"]["id"], REG))
    return r


# ─── Care-fund helper ──────────────────────────────────────────────────

def post_care_entry(cemetery_id, entry_type, amount_cents, source_deed_id=None, note=None):
    return api_client.create_care_fund_entry(
        create_care_fund_entry_payload(cemetery_id, entry_type, amount_cents,
                                       source_deed_id=source_deed_id, note=note), FIN)


def get_cemetery_balance(cemetery_id):
    cem = get_success_data(api_client.get_cemetery(cemetery_id, FIN))
    return cem["perpetual_care_fund_balance_cents"]
