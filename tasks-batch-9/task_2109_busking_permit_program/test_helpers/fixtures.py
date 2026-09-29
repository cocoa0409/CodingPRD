"""Composite setup helpers for the Busking Permit Program workflows.

Every helper uses get_success_data() so a broken preamble surfaces as a clear
"Setup step failed" assertion rather than a confusing downstream error.

The test harness restarts the API server before every test, so each helper
builds its preconditions from scratch through PRD-declared endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_zone_payload,
    create_pitch_payload,
    create_performer_payload,
    create_application_payload,
    decision_payload,
    revision_payload,
    create_audition_payload,
    create_audition_score_payload,
    payment_payload,
    renew_payload,
    revoke_payload,
    reinstate_payload,
    create_lottery_draw_payload,
    create_lottery_entry_payload,
    create_session_booking_payload,
    cancel_booking_payload,
    create_noise_reading_payload,
    create_complaint_payload,
    triage_payload,
    adjudicate_payload,
    create_closure_order_payload,
)
from .test_users import (
    make_officer_headers,
    make_performer_headers,
    make_panelist_headers,
    make_inspector_headers,
    make_resident_headers,
    OFFICER_ALPHA,
    OFFICER_BETA,
)


# ---------------------------------------------------------------------------
# Tier 1 — single-call creations and reads
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, officer=OFFICER_ALPHA):
    """Move the program clock and return {current_utc, previous_utc}."""
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, make_officer_headers(officer)))


def run_epoch_advance(officer=OFFICER_ALPHA):
    """Invoke the epoch advance and return its report."""
    return get_success_data(api_client.run_epoch_advance(make_officer_headers(officer)))


def create_zone(officer=OFFICER_ALPHA, **overrides):
    return get_success_data(api_client.create_zone(
        create_zone_payload(**overrides), make_officer_headers(officer)))


def create_pitch(zone_id, officer=OFFICER_ALPHA, **overrides):
    return get_success_data(api_client.create_pitch(
        create_pitch_payload(zone_id, **overrides), make_officer_headers(officer)))


def create_performer(officer=OFFICER_ALPHA, **overrides):
    return get_success_data(api_client.create_performer(
        create_performer_payload(**overrides), make_officer_headers(officer)))


def create_application(performer_id, zone_id, **overrides):
    return get_success_data(api_client.create_application(
        create_application_payload(performer_id, zone_id, **overrides),
        make_performer_headers(performer_id)))


def submit_application(application_id, performer_id):
    return get_success_data(api_client.submit_application(
        application_id, make_performer_headers(performer_id)))


def review_application(application_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.review_application(
        application_id, make_officer_headers(officer)))


def decide_application(application_id, outcome, decision_note=None,
                       officer=OFFICER_BETA):
    return get_success_data(api_client.decide_application(
        application_id, decision_payload(outcome, decision_note),
        make_officer_headers(officer)))


def revise_application(application_id, performer_id,
                       expected_application_version, **overrides):
    return get_success_data(api_client.revise_application(
        application_id,
        revision_payload(expected_application_version, **overrides),
        make_performer_headers(performer_id)))


def read_zone(zone_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_zone(zone_id, make_officer_headers(officer)))


def read_pitch(pitch_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_pitch(pitch_id, make_officer_headers(officer)))


def read_performer(performer_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_performer(
        performer_id, make_officer_headers(officer)))


def read_application(application_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_application(
        application_id, make_officer_headers(officer)))


def read_audition(audition_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_audition(
        audition_id, make_officer_headers(officer)))


def read_permit(permit_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_permit(
        permit_id, make_officer_headers(officer)))


def read_booking(booking_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_session_booking(
        booking_id, make_officer_headers(officer)))


def read_draw(draw_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_lottery_draw(
        draw_id, make_officer_headers(officer)))


def read_entry(entry_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_lottery_entry(
        entry_id, make_officer_headers(officer)))


def read_complaint(complaint_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_complaint(
        complaint_id, make_officer_headers(officer)))


def read_closure(closure_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.get_closure_order(
        closure_id, make_officer_headers(officer)))


def permit_version(permit_id, officer=OFFICER_ALPHA):
    """Re-read the permit and hand back its current version — the value a
    booking must carry as expected_permit_version."""
    return read_permit(permit_id, officer)["version"]


def application_version(application_id, officer=OFFICER_ALPHA):
    return read_application(application_id, officer)["version"]


# ---------------------------------------------------------------------------
# Tier 2 — discovery of cascade-minted rows
# ---------------------------------------------------------------------------

def find_permit_for_application(application_id, officer=OFFICER_ALPHA):
    """Permit listings are the only way to find a permit an approval minted."""
    rows = get_success_data(api_client.list_permits(
        make_officer_headers(officer), params={"application_id": application_id}))
    assert rows, f"Setup step failed: no permit was minted for application {application_id}"
    return rows[0]


def list_permit_invoices(permit_id, officer=OFFICER_ALPHA, **params):
    return get_success_data(api_client.list_permit_invoices(
        permit_id, make_officer_headers(officer), params=params or None))


def first_permit_invoice(permit_id, officer=OFFICER_ALPHA, **params):
    rows = list_permit_invoices(permit_id, officer, **params)
    assert rows, f"Setup step failed: permit {permit_id} carries no invoice"
    return rows[0]


def list_bookings(officer=OFFICER_ALPHA, **params):
    return get_success_data(api_client.list_session_bookings(
        make_officer_headers(officer), params=params or None))


def list_entries(officer=OFFICER_ALPHA, **params):
    return get_success_data(api_client.list_lottery_entries(
        make_officer_headers(officer), params=params or None))


# ---------------------------------------------------------------------------
# Tier 3 — application lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_permit_pending_fee(zone_id, performer=None, act_type="ACOUSTIC_MUSIC",
                             amplification_requested=False, season_year=2026,
                             review_officer=OFFICER_ALPHA,
                             decision_officer=OFFICER_BETA,
                             performer_overrides=None):
    """Enroll a performer, lodge an application, review it and approve it.

    Returns {"performer", "application", "permit", "invoice"} with the permit in
    PENDING_FEE / CLEAR and its INITIAL invoice PENDING.
    """
    if performer is None:
        overrides = dict(performer_overrides or {})
        overrides.setdefault("act_type", act_type)
        performer = create_performer(**overrides)
    application = create_application(
        performer["id"], zone_id, season_year=season_year,
        requested_act_type=act_type,
        amplification_requested=amplification_requested)
    submit_application(application["id"], performer["id"])
    review_application(application["id"], review_officer)
    application = decide_application(
        application["id"], "APPROVED", "Approved on the papers", decision_officer)
    permit = find_permit_for_application(application["id"])
    invoice = first_permit_invoice(permit["id"])
    return {"performer": performer, "application": application,
            "permit": permit, "invoice": invoice}


def pay_invoice(invoice, performer_id=None, officer=None, amount_cents=None):
    """Settle an invoice for exactly its amount_due_cents unless told otherwise."""
    amount = invoice["amount_due_cents"] if amount_cents is None else amount_cents
    headers = (make_officer_headers(officer) if performer_id is None
               else make_performer_headers(performer_id))
    return get_success_data(api_client.pay_invoice(
        invoice["id"], payment_payload(amount), headers))


def setup_active_permit(zone_id, performer=None, act_type="ACOUSTIC_MUSIC",
                        amplification_requested=False, season_year=2026,
                        review_officer=OFFICER_ALPHA,
                        decision_officer=OFFICER_BETA,
                        performer_overrides=None):
    """setup_permit_pending_fee plus payment of the INITIAL invoice, leaving the
    permit ACTIVE / CLEAR. Returns the same dict with permit and invoice re-read."""
    ctx = setup_permit_pending_fee(
        zone_id, performer=performer, act_type=act_type,
        amplification_requested=amplification_requested, season_year=season_year,
        review_officer=review_officer, decision_officer=decision_officer,
        performer_overrides=performer_overrides)
    ctx["invoice"] = pay_invoice(ctx["invoice"], ctx["performer"]["id"])
    ctx["permit"] = read_permit(ctx["permit"]["id"])
    return ctx


def setup_district_pitch_and_active_permit(zone_overrides=None,
                                           pitch_overrides=None, **kwargs):
    """Register a district and one pitch inside it, then bring a performer all
    the way to an ACTIVE permit. Returns {"zone","pitch",...}."""
    zone = create_zone(**(zone_overrides or {}))
    pitch = create_pitch(zone["id"], **(pitch_overrides or {}))
    ctx = setup_active_permit(zone["id"], **kwargs)
    ctx["zone"] = zone
    ctx["pitch"] = pitch
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b — vetting shortcuts
# ---------------------------------------------------------------------------

def schedule_audition(application_id, scheduled_for="2026-08-06T10:00:00Z",
                      officer=OFFICER_ALPHA):
    return get_success_data(api_client.create_audition(
        create_audition_payload(application_id, scheduled_for=scheduled_for),
        make_officer_headers(officer)))


def file_panel_score(audition_id, technical_score, suitability_score,
                     safety_score, panelist="panelist-1"):
    return get_success_data(api_client.create_audition_score(
        audition_id,
        create_audition_score_payload(technical_score, suitability_score,
                                      safety_score),
        make_panelist_headers(panelist)))


def file_panel_scores(audition_id, triples, panelists=None):
    """File one score per panelist, in order. triples is a list of
    (technical_score, suitability_score, safety_score)."""
    names = panelists or [f"panelist-{i + 1}" for i in range(len(triples))]
    return [file_panel_score(audition_id, t, s, sa, names[i])
            for i, (t, s, sa) in enumerate(triples)]


def finalize_audition(audition_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.finalize_audition(
        audition_id, make_officer_headers(officer)))


def setup_audition_scheduled(zone_id, performer=None,
                             act_type="AMPLIFIED_MUSIC",
                             amplification_requested=True, season_year=2026,
                             scheduled_for="2026-08-06T10:00:00Z",
                             review_officer=OFFICER_ALPHA,
                             performer_overrides=None):
    """Lodge an application that requires vetting, review it into
    AUDITION_REQUIRED and schedule the sitting.

    Returns {"performer", "application", "audition"}.
    """
    if performer is None:
        overrides = dict(performer_overrides or {})
        overrides.setdefault("act_type", act_type)
        overrides.setdefault("legal_name", "Bo Kestrel")
        overrides.setdefault("stage_name", "Bo K")
        overrides.setdefault("email", "bo@example.org")
        performer = create_performer(**overrides)
    application = create_application(
        performer["id"], zone_id, season_year=season_year,
        requested_act_type=act_type,
        amplification_requested=amplification_requested)
    submit_application(application["id"], performer["id"])
    application = review_application(application["id"], review_officer)
    audition = schedule_audition(application["id"], scheduled_for, review_officer)
    return {"performer": performer, "application": application,
            "audition": audition}


def setup_audition_passed(zone_id, finalize_officer=OFFICER_ALPHA, **kwargs):
    """Vetting branch driven all the way to AUDITION_PASSED with panel_score 7.90
    from the (9,8,8), (8,8,7), (7,8,8) panel."""
    ctx = setup_audition_scheduled(zone_id, **kwargs)
    file_panel_scores(ctx["audition"]["id"], [(9, 8, 8), (8, 8, 7), (7, 8, 8)])
    ctx["audition"] = finalize_audition(ctx["audition"]["id"], finalize_officer)
    ctx["application"] = read_application(ctx["application"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — occupation, metering and accumulation
# ---------------------------------------------------------------------------

def book_session(permit_id, pitch_id, start_at, end_at, performer_id,
                 expected_permit_version=None, **overrides):
    """Reserve a pitch window, reading the permit's current version when the
    caller does not supply one."""
    version = (permit_version(permit_id) if expected_permit_version is None
               else expected_permit_version)
    return get_success_data(api_client.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id, start_at, end_at,
                                       version, **overrides),
        make_performer_headers(performer_id)))


def book_series(permit_id, pitch_id, performer_id, windows, **overrides):
    """Reserve a run of windows back to back, refreshing the permit version
    between each one. windows is a list of (start_at, end_at) pairs."""
    return [book_session(permit_id, pitch_id, start, end, performer_id, **overrides)
            for start, end in windows]


def cancel_booking(booking_id, performer_id=None, officer=None, reason=None):
    headers = (make_officer_headers(officer) if performer_id is None
               else make_performer_headers(performer_id))
    return get_success_data(api_client.cancel_session_booking(
        booking_id, cancel_booking_payload(reason), headers))


def file_noise_reading(booking_id, taken_at, reading_db, inspector="inspector-1"):
    return get_success_data(api_client.create_noise_reading(
        create_noise_reading_payload(booking_id, taken_at, reading_db),
        make_inspector_headers(inspector)))


def file_noise_readings(booking_id, instants, reading_db=85,
                        inspector="inspector-1"):
    return [file_noise_reading(booking_id, taken_at, reading_db, inspector)
            for taken_at in instants]


# ---------------------------------------------------------------------------
# Tier 4b — complaints and conduct
# ---------------------------------------------------------------------------

def file_complaint(permit_id, resident="resident-1", **overrides):
    return get_success_data(api_client.create_complaint(
        create_complaint_payload(permit_id, **overrides),
        make_resident_headers(resident)))


def triage_complaint(complaint_id, severity, route="DIRECT",
                     officer=OFFICER_ALPHA):
    return get_success_data(api_client.triage_complaint(
        complaint_id, triage_payload(severity, route),
        make_officer_headers(officer)))


def adjudicate_complaint(complaint_id, outcome, officer=OFFICER_BETA,
                         resolution_note=None):
    return get_success_data(api_client.adjudicate_complaint(
        complaint_id, adjudicate_payload(outcome, resolution_note),
        make_officer_headers(officer)))


def uphold_new_complaint(permit_id, severity, route="DIRECT",
                         resident="resident-1", triage_officer=OFFICER_ALPHA,
                         adjudicate_officer=OFFICER_BETA, **overrides):
    """File a complaint, triage it with the given severity and route, and
    uphold it. Returns the resolved complaint."""
    complaint = file_complaint(permit_id, resident, **overrides)
    triage_complaint(complaint["id"], severity, route, triage_officer)
    return adjudicate_complaint(complaint["id"], "UPHELD", adjudicate_officer)


# ---------------------------------------------------------------------------
# Tier 4c — enforcement shortcuts
# ---------------------------------------------------------------------------

def revoke_permit(permit_id, reason="Permit surrendered by the holder",
                  refund_mode=None, officer=OFFICER_ALPHA):
    return get_success_data(api_client.revoke_permit(
        permit_id, revoke_payload(reason, refund_mode),
        make_officer_headers(officer)))


def reinstate_permit(permit_id, note=None, officer=OFFICER_ALPHA):
    return get_success_data(api_client.reinstate_permit(
        permit_id, reinstate_payload(note), make_officer_headers(officer)))


def renew_permit(permit_id, performer_id, season_year):
    return get_success_data(api_client.renew_permit(
        permit_id, renew_payload(season_year), make_performer_headers(performer_id)))


# ---------------------------------------------------------------------------
# Tier 4d — rotation draws
# ---------------------------------------------------------------------------

def open_draw(pitch_id, officer=OFFICER_ALPHA, **overrides):
    return get_success_data(api_client.create_lottery_draw(
        create_lottery_draw_payload(pitch_id, **overrides),
        make_officer_headers(officer)))


def enter_draw(draw_id, permit_id, performer_id):
    return get_success_data(api_client.create_lottery_entry(
        draw_id, create_lottery_entry_payload(permit_id),
        make_performer_headers(performer_id)))


def execute_draw(draw_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.execute_lottery_draw(
        draw_id, make_officer_headers(officer)))


# ---------------------------------------------------------------------------
# Tier 5 — closures
# ---------------------------------------------------------------------------

def draft_closure(zone_id, starts_at, ends_at, reason="SPECIAL_EVENT",
                  pitch_id=None, officer=OFFICER_ALPHA):
    overrides = {"reason": reason}
    if pitch_id is not None:
        overrides["pitch_id"] = pitch_id
    return get_success_data(api_client.create_closure_order(
        create_closure_order_payload(zone_id, starts_at, ends_at, **overrides),
        make_officer_headers(officer)))


def activate_closure(closure_id, officer=OFFICER_ALPHA):
    return get_success_data(api_client.activate_closure_order(
        closure_id, make_officer_headers(officer)))


def draft_and_activate_closure(zone_id, starts_at, ends_at,
                               reason="SPECIAL_EVENT", pitch_id=None,
                               officer=OFFICER_ALPHA):
    closure = draft_closure(zone_id, starts_at, ends_at, reason, pitch_id, officer)
    return activate_closure(closure["id"], officer)
