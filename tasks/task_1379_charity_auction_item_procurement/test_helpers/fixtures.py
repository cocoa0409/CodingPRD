"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bidder_payload,
    create_blackout_window_payload,
    create_bundle_payload,
    create_donor_payload,
    create_gala_event_payload,
    create_item_payload,
    create_payment_payload,
    create_solicitation_payload,
    place_bid_payload,
    submit_valuation_payload,
)
from .test_users import TEST_USERS, make_bidder_headers, make_donor_headers

ADMIN = TEST_USERS["gala_admin_headers"]
PO = TEST_USERS["procurement_officer_headers"]
VA = TEST_USERS["valuation_approver_headers"]
CM = TEST_USERS["catalog_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]

# OCC identity convention: valuations are submitted by po_1 and decided by
# va_1 so the segregation-of-duties rule is always satisfied in fixtures.
SUBMITTER_HEADERS = PO
APPROVER_HEADERS = VA


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 1 — event lifecycle
# ---------------------------------------------------------------------------

def create_event(**overrides):
    """Create a gala event (standard policy config by default)."""
    resp = api_client.create_gala_event(create_gala_event_payload(**overrides),
                                        ADMIN)
    return _ok("create_gala_event", resp)


def advance_event(event_id):
    resp = api_client.advance_gala_event(event_id, ADMIN)
    return _ok("advance_gala_event", resp)


def create_event_in_status(status="SOLICITING", **overrides):
    """Create an event and advance it along the linear lifecycle chain."""
    chain = ["DRAFT", "SOLICITING", "CATALOGING", "BIDDING_OPEN",
             "BIDDING_CLOSED", "SETTLEMENT"]
    event = create_event(**overrides)
    for _ in range(chain.index(status)):
        event = advance_event(event["id"])
    return event


# ---------------------------------------------------------------------------
# Tier 1 — donors, bidders, solicitations
# ---------------------------------------------------------------------------

def create_donor(**overrides):
    resp = api_client.create_donor(create_donor_payload(**overrides), PO)
    return _ok("create_donor", resp)


def create_bidder(event_id, **overrides):
    resp = api_client.create_bidder(
        create_bidder_payload(event_id, **overrides), ADMIN)
    return _ok("create_bidder", resp)


def create_solicitation(donor_id, event_id, **overrides):
    resp = api_client.create_solicitation(
        create_solicitation_payload(donor_id, event_id, **overrides), PO)
    return _ok("create_solicitation", resp)


def send_solicitation(solicitation_id):
    resp = api_client.send_solicitation(solicitation_id, PO)
    return _ok("send_solicitation", resp)


def record_solicitation_outcome(solicitation_id, outcome):
    resp = api_client.record_solicitation_response(
        solicitation_id, {"outcome": outcome}, PO)
    return _ok("record_solicitation_response", resp)


def create_pledged_solicitation(donor_id, event_id, **overrides):
    """Create -> send -> record PLEDGED."""
    sol = create_solicitation(donor_id, event_id, **overrides)
    send_solicitation(sol["id"])
    return record_solicitation_outcome(sol["id"], "PLEDGED")


# ---------------------------------------------------------------------------
# Tier 2 — items and valuations
# ---------------------------------------------------------------------------

def receive_item(solicitation_id, **overrides):
    resp = api_client.create_item(
        create_item_payload(solicitation_id, **overrides), PO)
    return _ok("create_item", resp)


def submit_valuation(item_id, fmv_cents, fmv_source="APPRAISAL"):
    """Submit a valuation as the procurement officer, reading the item's
    current version first for the OCC precondition."""
    item = _ok("get_item(pre-submit)",
               api_client.get_item(item_id, PO))
    resp = api_client.submit_valuation(
        item_id,
        submit_valuation_payload(fmv_cents, item["version"],
                                 fmv_source=fmv_source),
        SUBMITTER_HEADERS,
    )
    return _ok("submit_valuation", resp)


def approve_valuation(valuation_id):
    resp = api_client.approve_valuation(valuation_id, APPROVER_HEADERS)
    return _ok("approve_valuation", resp)


def setup_valued_item(event_id, fmv_cents, kind="PHYSICAL", donor=None,
                      title=None, description=None):
    """Donor + pledged solicitation + received item + approved valuation.

    Returns a dict with donor, solicitation, item (post-approval state),
    and valuation.
    """
    donor = donor or create_donor()
    sol = create_pledged_solicitation(
        donor["id"], event_id,
        ask_estimate_cents=fmv_cents,
        **({"ask_description": title} if title else {}),
    )
    item_kwargs = {}
    if title:
        item_kwargs["title"] = title
    if description:
        item_kwargs["description"] = description
    item = receive_item(sol["id"], kind=kind, **item_kwargs)
    valuation = submit_valuation(item["id"], fmv_cents)
    approve_valuation(valuation["id"])
    item = _ok("get_item(post-approve)", api_client.get_item(item["id"], PO))
    return {
        "donor": donor,
        "solicitation": sol,
        "item": item,
        "valuation": valuation,
    }


# ---------------------------------------------------------------------------
# Tier 2/3 — bundles, publish, bidding
# ---------------------------------------------------------------------------

def create_bundle(event_id, **overrides):
    resp = api_client.create_bundle(
        create_bundle_payload(event_id, **overrides), CM)
    return _ok("create_bundle", resp)


def attach_item(bundle_id, item_id):
    resp = api_client.attach_item(bundle_id, {"item_id": item_id}, CM)
    return _ok("attach_item", resp)


def detach_item(bundle_id, item_id):
    resp = api_client.detach_item(bundle_id, item_id, CM)
    return _ok("detach_item", resp)


def publish_bundle(bundle_id):
    resp = api_client.publish_bundle(bundle_id, CM)
    return _ok("publish_bundle", resp)


def setup_published_bundle(event_id, item_ids, title=None):
    """Create a bundle, attach the given (VALUED) items, publish it.
    Returns the published bundle (carrying its post-publish version)."""
    bundle = create_bundle(event_id, **({"title": title} if title else {}))
    for item_id in item_ids:
        bundle = attach_item(bundle["id"], item_id)
    return publish_bundle(bundle["id"])


def place_bid(bundle_id, amount_cents, bidder_id):
    """Place a bid as the given bidder, reading the bundle's current version
    first for the OCC precondition."""
    bundle = _ok("get_bundle(pre-bid)", api_client.get_bundle(bundle_id, ADMIN))
    resp = api_client.place_bid(
        bundle_id,
        place_bid_payload(amount_cents, bundle["version"]),
        make_bidder_headers(bidder_id),
    )
    return _ok("place_bid", resp)


# ---------------------------------------------------------------------------
# Tier 3 — full sale pipeline shortcuts
# ---------------------------------------------------------------------------

def setup_bidding_open_scenario(fmv_cents=40000, kind="PHYSICAL",
                                item_fmvs=None, title=None):
    """Event advanced to BIDDING_OPEN with one PUBLISHED bundle.

    item_fmvs (list) overrides fmv_cents for multi-item bundles. Returns a
    dict with event, bundle (post-publish), items, donors, valuations.
    """
    fmvs = item_fmvs if item_fmvs is not None else [fmv_cents]
    event = create_event()
    advance_event(event["id"])  # -> SOLICITING
    parts = [
        setup_valued_item(event["id"], fmv, kind=kind,
                          title=f"{title or 'Lot'} {i + 1}")
        for i, fmv in enumerate(fmvs)
    ]
    advance_event(event["id"])  # -> CATALOGING
    bundle = setup_published_bundle(
        event["id"], [p["item"]["id"] for p in parts], title=title)
    advance_event(event["id"])  # -> BIDDING_OPEN
    return {
        "event": _ok("get_event", api_client.get_gala_event(event["id"],
                                                            ADMIN)),
        "bundle": bundle,
        "items": [p["item"] for p in parts],
        "donors": [p["donor"] for p in parts],
        "valuations": [p["valuation"] for p in parts],
    }


def close_bidding(event_id):
    """Advance BIDDING_OPEN -> BIDDING_CLOSED (fires the close cascade)."""
    return advance_event(event_id)


def get_invoice_for_bundle(bundle_id):
    data, _meta = _paginated(
        "list_invoices",
        api_client.list_invoices(ADMIN, params={"bundle_id": bundle_id}),
    )
    assert len(data) == 1, \
        f"Setup failed: expected exactly 1 invoice for bundle, got {len(data)}"
    return data[0]


def get_disposition_for_item(item_id):
    data, _meta = _paginated(
        "list_dispositions",
        api_client.list_dispositions(ADMIN, params={"item_id": item_id}),
    )
    assert len(data) >= 1, \
        "Setup failed: expected at least 1 disposition for item"
    return data[0]


def get_acknowledgment_for_item(item_id, status=None):
    params = {"item_id": item_id}
    if status:
        params["status"] = status
    data, _meta = _paginated(
        "list_acknowledgments",
        api_client.list_acknowledgments(FO, params=params),
    )
    assert len(data) >= 1, \
        "Setup failed: expected at least 1 acknowledgment for item"
    return data[0]


def get_certificate_for_invoice(invoice_id):
    data, _meta = _paginated(
        "list_invoice_certificates",
        api_client.list_invoice_certificates(invoice_id, ADMIN),
    )
    assert len(data) == 1, \
        f"Setup failed: expected exactly 1 certificate, got {len(data)}"
    return data[0]


def _paginated(step, resp):
    from prd_bench_local_runner.testing import validate_paginated
    try:
        return validate_paginated(resp)
    except AssertionError:
        _fail(step, resp)


def setup_sold_scenario(fmv_cents=40000, bid_amount=50000, kind="PHYSICAL",
                        item_fmvs=None):
    """Full pipeline through the close cascade with one winning bid.

    Returns a dict with event, bundle, items, donors, bidder, winning bid,
    and invoice (UNPAID / PENDING).
    """
    ctx = setup_bidding_open_scenario(fmv_cents=fmv_cents, kind=kind,
                                      item_fmvs=item_fmvs)
    bidder = create_bidder(ctx["event"]["id"])
    bid = place_bid(ctx["bundle"]["id"], bid_amount, bidder["id"])
    close_bidding(ctx["event"]["id"])
    invoice = get_invoice_for_bundle(ctx["bundle"]["id"])
    ctx.update({"bidder": bidder, "bid": bid, "invoice": invoice})
    return ctx


def pay_invoice_in_full(invoice, bidder_id):
    """Create a payment covering the full outstanding balance and settle it
    as SUCCEEDED. Returns the payment."""
    current = _ok("get_invoice(pre-pay)",
                  api_client.get_invoice(invoice["id"], FO))
    outstanding = current["winning_bid_cents"] - current["amount_paid_cents"]
    resp = api_client.create_payment(
        invoice["id"], create_payment_payload(outstanding),
        make_bidder_headers(bidder_id))
    payment = _ok("create_payment", resp)
    resp = api_client.simulate_payment(
        {"payment_id": payment["id"], "outcome": "SUCCEEDED"}, ADMIN)
    return _ok("simulate_payment", resp)


def setup_paid_scenario(fmv_cents=40000, bid_amount=50000, kind="PHYSICAL"):
    """Sold scenario whose invoice is fully PAID (fulfillment READY; an
    EXPERIENCE sale additionally holds an ISSUED certificate)."""
    ctx = setup_sold_scenario(fmv_cents=fmv_cents, bid_amount=bid_amount,
                              kind=kind)
    payment = pay_invoice_in_full(ctx["invoice"], ctx["bidder"]["id"])
    invoice = _ok("get_invoice(post-pay)",
                  api_client.get_invoice(ctx["invoice"]["id"], FO))
    ctx["payment"] = payment
    ctx["invoice"] = invoice
    if kind == "EXPERIENCE":
        ctx["certificate"] = get_certificate_for_invoice(invoice["id"])
    return ctx


def setup_unsold_scenario(fmv_cents=40000, kind="PHYSICAL"):
    """Full pipeline through close with NO bids: bundle UNSOLD, item UNSOLD,
    one PROPOSED disposition per member item."""
    ctx = setup_bidding_open_scenario(fmv_cents=fmv_cents, kind=kind)
    close_bidding(ctx["event"]["id"])
    dispositions = [
        get_disposition_for_item(item["id"]) for item in ctx["items"]
    ]
    ctx["dispositions"] = dispositions
    ctx["bundle"] = _ok("get_bundle(post-close)",
                        api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — paired certificates for boundary tests
# ---------------------------------------------------------------------------

def setup_two_issued_certificates(blackouts=False):
    """Two EXPERIENCE bundles, each FMV 40000 sold for 50000 to its own
    bidder, both invoices fully paid at the default clock. Returns a dict
    with two certificate contexts (cert_a / cert_b with their bidders) plus
    the event. With blackouts=True both items carry the standard blackout
    window 2027-08-05 .. 2027-08-12."""
    event = create_event()
    advance_event(event["id"])  # SOLICITING
    parts = []
    for i, title in enumerate(["Experience A", "Experience B"]):
        part = setup_valued_item(event["id"], 40000, kind="EXPERIENCE",
                                 title=title)
        parts.append(part)
    if blackouts:
        for part in parts:
            resp = api_client.create_blackout_window(
                part["item"]["id"], create_blackout_window_payload(), CM)
            _ok("create_blackout_window", resp)
    advance_event(event["id"])  # CATALOGING
    bundles = [
        setup_published_bundle(event["id"], [p["item"]["id"]],
                               title=f"Bundle {i + 1}")
        for i, p in enumerate(parts)
    ]
    advance_event(event["id"])  # BIDDING_OPEN
    bidders = [create_bidder(event["id"], full_name=f"Bidder {i + 1}")
               for i in range(2)]
    for bundle, bidder in zip(bundles, bidders):
        place_bid(bundle["id"], 50000, bidder["id"])
    close_bidding(event["id"])
    certs = []
    for bundle, bidder in zip(bundles, bidders):
        invoice = get_invoice_for_bundle(bundle["id"])
        pay_invoice_in_full(invoice, bidder["id"])
        cert = get_certificate_for_invoice(invoice["id"])
        certs.append({
            "bundle": bundle,
            "bidder": bidder,
            "invoice": invoice,
            "certificate": cert,
        })
    return {
        "event": _ok("get_event", api_client.get_gala_event(event["id"],
                                                            ADMIN)),
        "cert_a": certs[0],
        "cert_b": certs[1],
    }
