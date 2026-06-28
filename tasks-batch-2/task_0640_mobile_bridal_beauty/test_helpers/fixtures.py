"""Composite setup helpers for the Bridal Beauty API.

Every test starts against an empty database (the runner restarts the server before each
test). These helpers build the multi-step preconditions each test needs, using only
PRD-declared endpoints, and return dicts of the captured ids/values tests assert on.

Identity threading: Artist is entity_backed, so any ownership-gated artist call (trial
complete, assignment start/complete) uses make_artist_headers(artist_id). Client ownership
compares X-User-ID to the owning event's client_id, so client calls use the event's
client_id as the acting identity.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_coordinator_headers, make_client_headers, make_artist_headers
from .factories import (
    create_artist_payload,
    create_event_payload,
    create_face_payload,
)

COORD = make_coordinator_headers()


# ─── Tier 0: clock ────────────────────────────────────
def set_clock(iso8601: str):
    """Advance the server logical clock (Coordinator-only)."""
    return get_success_data(api_client.set_clock(iso8601, COORD))


# ─── Tier 1: roster ───────────────────────────────────
def create_artist(**overrides) -> dict:
    """Register one artist. Returns the Artist resource dict."""
    return get_success_data(api_client.create_artist(create_artist_payload(**overrides), COORD))


# ─── Tier 1/2: events + faces ─────────────────────────
def create_event(client_id="client-1", **overrides) -> dict:
    """Open one DRAFT event owned by client_id. Returns the BridalEvent dict."""
    payload = create_event_payload(client_id=client_id, **overrides)
    return get_success_data(api_client.create_event(payload, make_client_headers(client_id)))


def add_face(event_id, client_id, person_label, service_type, is_bride=False) -> dict:
    """Add one PENDING face to an event."""
    payload = create_face_payload(
        person_label=person_label, service_type=service_type, is_bride=is_bride
    )
    return get_success_data(api_client.add_face(event_id, payload, make_client_headers(client_id)))


def confirm_face(face_id, client_id) -> dict:
    return get_success_data(api_client.confirm_face(face_id, make_client_headers(client_id)))


def quote_event(event_id) -> dict:
    """Issue/re-issue a quote (Coordinator). Returns the updated event."""
    return get_success_data(api_client.quote_event(event_id, COORD))


# ─── Tier 2/3: a quoted event with a configured party ─
def setup_quoted_event(
    client_id="client-1",
    artist_overrides=None,
    event_overrides=None,
    faces=None,
):
    """Create a LEAD artist + event + faces, confirm the requested faces, and quote once.

    `faces` is a list of dicts: {person_label, service_type, is_bride?, confirm?}.
    Default: one CONFIRMED bride HAIR face.

    Returns a dict with keys:
      artist, lead_artist_id, event, event_id, quote_version, faces (list of face dicts).
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(**(artist_overrides or {}))
    event = create_event(client_id=client_id, **(event_overrides or {}))
    event_id = event["id"]

    if faces is None:
        faces = [{"person_label": "BRIDE", "service_type": "HAIR", "is_bride": True, "confirm": True}]

    face_objs = []
    for f in faces:
        face = add_face(
            event_id, client_id, f["person_label"], f["service_type"], f.get("is_bride", False)
        )
        if f.get("confirm", False):
            face = confirm_face(face["id"], client_id)
        face_objs.append(face)

    quoted = quote_event(event_id)
    return {
        "artist": artist,
        "lead_artist_id": artist["id"],
        "event": quoted,
        "event_id": event_id,
        "quote_version": quoted["version"],
        "faces": face_objs,
        "client_id": client_id,
    }


# ─── Tier 3: signed contract + open invoice ───────────
def sign_contract(event_id, lead_artist_id, expected_event_version, client_id) -> dict:
    """Sign a contract for a QUOTED event. Returns the Contract dict."""
    payload = {
        "event_id": event_id,
        "lead_artist_id": lead_artist_id,
        "expected_event_version": expected_event_version,
    }
    return get_success_data(api_client.create_contract(payload, make_client_headers(client_id)))


def get_invoice_for_event(event_id, client_id) -> dict:
    """Fetch the invoice opened for an event (first match)."""
    data, _ = _list(api_client.list_invoices(make_client_headers(client_id), params={"event_id": event_id}))
    return data[0]


def _list(response):
    body = get_success_data(response)
    # get_success_data returns the data payload; meta is on the envelope, but for list
    # helpers we only need the data array here.
    return body, None


def setup_contracted_event(
    client_id="client-1",
    artist_overrides=None,
    event_overrides=None,
    faces=None,
):
    """Quoted event -> signed contract -> open invoice (deposit DUE, balance NOT_DUE).

    Returns a dict extending setup_quoted_event with:
      contract, contract_id, deposit_due_cents, contracted_total_cents,
      invoice, invoice_id, post_contract_version (event.version after the sign cascade).
    """
    base = setup_quoted_event(
        client_id=client_id,
        artist_overrides=artist_overrides,
        event_overrides=event_overrides,
        faces=faces,
    )
    contract = sign_contract(
        base["event_id"], base["lead_artist_id"], base["quote_version"], client_id
    )
    invoice = get_invoice_for_event(base["event_id"], client_id)
    event_after = get_success_data(api_client.get_event(base["event_id"], COORD))
    base.update({
        "contract": contract,
        "contract_id": contract["id"],
        "deposit_due_cents": contract["deposit_due_cents"],
        "contracted_total_cents": contract["contracted_total_cents"],
        "invoice": invoice,
        "invoice_id": invoice["id"],
        "post_contract_version": event_after["version"],
    })
    return base


# ─── Tier 3/4: deposit paid ───────────────────────────
def pay_deposit(invoice_id, amount_cents, client_id) -> dict:
    payload = {"applies_to": "DEPOSIT", "amount_cents": amount_cents}
    return get_success_data(api_client.record_payment(invoice_id, payload, make_client_headers(client_id)))


def setup_deposit_paid_event(
    client_id="client-1",
    artist_overrides=None,
    event_overrides=None,
    faces=None,
):
    """Contracted event with the full deposit paid (deposit_status PAID).

    Returns setup_contracted_event's dict, with post_deposit_version refreshed
    (event.version after the deposit payment — used as expected_event_version when
    scheduling the assignment).
    """
    base = setup_contracted_event(
        client_id=client_id,
        artist_overrides=artist_overrides,
        event_overrides=event_overrides,
        faces=faces,
    )
    pay_deposit(base["invoice_id"], base["deposit_due_cents"], client_id)
    event_after = get_success_data(api_client.get_event(base["event_id"], COORD))
    base["post_deposit_version"] = event_after["version"]
    return base


# ─── Tier 3/4: scheduled assignment ───────────────────
def schedule_assignment(
    event_id,
    artist_id,
    expected_event_version,
    window_start_utc="2026-07-15T08:00:00Z",
    window_end_utc="2026-07-15T10:00:00Z",
    assistant_artist_id=None,
) -> dict:
    payload = {
        "event_id": event_id,
        "artist_id": artist_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "expected_event_version": expected_event_version,
    }
    if assistant_artist_id is not None:
        payload["assistant_artist_id"] = assistant_artist_id
    return get_success_data(api_client.create_assignment(payload, COORD))


def setup_scheduled_event(
    client_id="client-1",
    artist_overrides=None,
    event_overrides=None,
    faces=None,
    window_start_utc="2026-07-15T08:00:00Z",
    window_end_utc="2026-07-15T10:00:00Z",
):
    """Deposit-paid event advanced to SCHEDULED with one on-location assignment.

    Returns setup_deposit_paid_event's dict, plus:
      assignment, assignment_id, post_schedule_version.
    """
    base = setup_deposit_paid_event(
        client_id=client_id,
        artist_overrides=artist_overrides,
        event_overrides=event_overrides,
        faces=faces,
    )
    assignment = schedule_assignment(
        base["event_id"], base["lead_artist_id"], base["post_deposit_version"],
        window_start_utc=window_start_utc, window_end_utc=window_end_utc,
    )
    event_after = get_success_data(api_client.get_event(base["event_id"], COORD))
    base.update({
        "assignment": assignment,
        "assignment_id": assignment["id"],
        "post_schedule_version": event_after["version"],
    })
    return base


# ─── Tier 4: add-ons & assignment lifecycle ───────────
def apply_addon(assignment_id, addon_type, quantity) -> dict:
    payload = {"addon_type": addon_type, "quantity": quantity}
    return get_success_data(api_client.add_addon(assignment_id, payload, COORD))


def start_assignment(assignment_id, artist_id) -> dict:
    return get_success_data(api_client.start_assignment(assignment_id, make_artist_headers(artist_id)))


def complete_assignment(assignment_id, artist_id) -> dict:
    return get_success_data(api_client.complete_assignment(assignment_id, make_artist_headers(artist_id)))


def setup_balance_due_event(
    client_id="client-1",
    artist_overrides=None,
    event_overrides=None,
    faces=None,
    window_start_utc="2026-07-15T08:00:00Z",
    window_end_utc="2026-07-15T10:00:00Z",
    start_clock="2026-07-15T08:00:00Z",
):
    """Scheduled event whose single assignment has been started and completed, advancing
    the invoice balance_status from NOT_DUE to DUE.

    Returns setup_scheduled_event's dict, plus the refreshed invoice under key
    invoice_after (with balance_status == DUE).
    """
    base = setup_scheduled_event(
        client_id=client_id,
        artist_overrides=artist_overrides,
        event_overrides=event_overrides,
        faces=faces,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )
    set_clock(start_clock)
    start_assignment(base["assignment_id"], base["lead_artist_id"])
    complete_assignment(base["assignment_id"], base["lead_artist_id"])
    base["invoice_after"] = get_success_data(api_client.get_invoice(base["invoice_id"], COORD))
    return base


# ─── Trials ───────────────────────────────────────────
def book_trial(event_id, artist_id, start_utc, end_utc, trial_fee_cents=5000) -> dict:
    payload = {
        "event_id": event_id,
        "artist_id": artist_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "trial_fee_cents": trial_fee_cents,
    }
    return get_success_data(api_client.create_trial(payload, COORD))


def complete_trial(trial_id, artist_id) -> dict:
    return get_success_data(api_client.complete_trial(trial_id, make_artist_headers(artist_id)))


# ─── Portfolio ────────────────────────────────────────
def add_portfolio_item(artist_id, look_name="Soft Glam", category="MAKEUP", as_coordinator=True) -> dict:
    headers = COORD if as_coordinator else make_artist_headers(artist_id)
    payload = {"look_name": look_name, "category": category}
    return get_success_data(api_client.create_portfolio_item(artist_id, payload, headers))
