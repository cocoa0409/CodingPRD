"""Composite setup helpers for the Massage Therapy Practice API.

The server is reset before every test, so each fixture builds its preconditions from
scratch using only PRD-declared endpoints. All setup calls use get_success_data() (lenient)
so a setup failure surfaces clearly. Ownership-gated calls thread the real entity id through
make_therapist_headers / make_client_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_therapist_headers,
    make_client_headers,
)
from . import factories as F

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitive creates
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the server logical clock to an explicit UTC instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_modality(**overrides):
    return get_success_data(api_client.create_modality(F.create_modality_payload(**overrides), ADMIN))


def create_therapist(**overrides):
    return get_success_data(api_client.create_therapist(F.create_therapist_payload(**overrides), ADMIN))


def create_table(**overrides):
    return get_success_data(api_client.create_table(F.create_table_payload(**overrides), ADMIN))


def create_client(**overrides):
    return get_success_data(api_client.create_client(F.create_client_payload(**overrides), FRONT))


def create_plan(**overrides):
    return get_success_data(api_client.create_plan(F.create_plan_payload(**overrides), ADMIN))


def create_commission_tier(tier_index, floor_revenue_cents, commission_pct):
    return get_success_data(api_client.create_commission_tier(
        F.create_commission_tier_payload(tier_index, floor_revenue_cents, commission_pct), ADMIN))


def create_signed_intake(client_id, **overrides):
    """Create a DRAFT intake then sign it (front desk) -> ACTIVE."""
    intake = get_success_data(api_client.create_intake(
        F.create_intake_payload(client_id, **overrides), FRONT))
    get_success_data(api_client.sign_intake(intake["id"], FRONT))
    return intake


def create_consent(client_id, **overrides):
    return get_success_data(api_client.create_consent(
        F.create_consent_payload(client_id, **overrides), FRONT))


def create_package(client_id, plan_id, **overrides):
    return get_success_data(api_client.create_package(
        F.create_package_payload(client_id, plan_id, **overrides), FRONT))


# ---------------------------------------------------------------------------
# Tier 1: a fully bookable scenario (client + therapist + table + modality +
# signed intake + active consent). Returns a dict of ids/objects.
# ---------------------------------------------------------------------------
def bookable_scenario(modality_overrides=None, therapist_overrides=None,
                      table_overrides=None, client_overrides=None,
                      intake_overrides=None, consent_overrides=None):
    """Build everything needed to book one appointment. Returns dict with keys:
    modality, therapist, table, client, intake, consent (each the full object)."""
    modality = create_modality(**(modality_overrides or {}))
    therapist = create_therapist(**(therapist_overrides or {}))
    table = create_table(**(table_overrides or {}))
    client = create_client(**(client_overrides or {}))
    intake = create_signed_intake(client["id"], **(intake_overrides or {}))
    consent = create_consent(client["id"], **(consent_overrides or {}))
    return {
        "modality": modality,
        "therapist": therapist,
        "table": table,
        "client": client,
        "intake": intake,
        "consent": consent,
    }


def book_appointment(scn, table=None, **appt_overrides):
    """Book an appointment against a bookable scenario dict.

    Reads the current table version fresh (the table is the OCC anchor) unless an
    expected_table_version override is supplied. `table` lets a caller book onto a
    different table than scn['table'] (re-read via GET to get a fresh version)."""
    tbl = table or scn["table"]
    if "expected_table_version" not in appt_overrides:
        fresh = get_success_data(api_client.get_table(tbl["id"], ADMIN))
        appt_overrides["expected_table_version"] = fresh["version"]
    payload = F.create_appointment_payload(
        client_id=scn["client"]["id"],
        therapist_id=scn["therapist"]["id"],
        table_id=tbl["id"],
        modality_id=scn["modality"]["id"],
        consent_id=scn["consent"]["id"],
        expected_table_version=appt_overrides.pop("expected_table_version"),
        **appt_overrides,
    )
    return get_success_data(api_client.create_appointment(payload, FRONT))


def create_draft_note(appointment_id, therapist_id, **overrides):
    """Therapist (owner) creates a DRAFT SOAP note for the appointment."""
    headers = make_therapist_headers(therapist_id)
    return get_success_data(api_client.create_soap_note(
        F.create_soap_note_payload(appointment_id, **overrides), headers))


def finalize_note(note_id, therapist_id):
    return get_success_data(api_client.finalize_soap_note(note_id, make_therapist_headers(therapist_id)))


# ---------------------------------------------------------------------------
# Tier 2 / 3: lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_with_finalized_note(scn, table=None, **appt_overrides):
    """Book an appointment + create & finalize its SOAP note. Returns (appointment, note)."""
    appt = book_appointment(scn, table=table, **appt_overrides)
    note = create_draft_note(appt["id"], scn["therapist"]["id"])
    finalize_note(note["id"], scn["therapist"]["id"])
    return appt, note


def drive_to_completed(scn, table=None, **appt_overrides):
    """Book -> create note -> check-in -> finalize note -> complete. Returns (appointment, note).

    Order matches the corner/difficulty recipes: note created, check-in, finalize, complete.
    Completion is performed by the assigned therapist."""
    appt = book_appointment(scn, table=table, **appt_overrides)
    t_id = scn["therapist"]["id"]
    note = create_draft_note(appt["id"], t_id)
    get_success_data(api_client.check_in_appointment(appt["id"], FRONT))
    finalize_note(note["id"], t_id)
    get_success_data(api_client.complete_appointment(appt["id"], make_therapist_headers(t_id)))
    return appt, note


def drive_to_priced(scn, table=None, **appt_overrides):
    """drive_to_completed then price. Returns (appointment, note)."""
    appt, note = drive_to_completed(scn, table=table, **appt_overrides)
    get_success_data(api_client.price_appointment(appt["id"], FRONT))
    return appt, note


def drive_to_paid(scn, gratuity_cents=0, table=None, **appt_overrides):
    """drive_to_priced then pay. Returns (appointment, note)."""
    appt, note = drive_to_priced(scn, table=table, **appt_overrides)
    get_success_data(api_client.pay_appointment(appt["id"], {"gratuity_cents": gratuity_cents}, FRONT))
    return appt, note


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_tiered_commission_tiers():
    """Create the global tiers floor 0@0.40, 20000@0.50, 40000@0.55."""
    create_commission_tier(0, 0, 0.40)
    create_commission_tier(1, 20000, 0.50)
    create_commission_tier(2, 40000, 0.55)


def raise_client_strikes_to(scn, target, base_start="2026-03-01T08:00:00Z"):
    """Drive Client.no_show_strikes up to `target` by booking + no-showing `target` 30-min
    Swedish appointments on distinct tables/slots. Clock is advanced past each start_at so the
    no-show is permitted. Leaves the clock at the last no-show instant. Returns nothing."""
    import datetime as _dt
    start = _dt.datetime.fromisoformat(base_start.replace("Z", "+00:00"))
    for i in range(target):
        slot = start + _dt.timedelta(hours=i)
        tbl = create_table()
        appt = book_appointment(
            scn, table=tbl,
            start_at=slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_minutes=30,
        )
        after = slot + _dt.timedelta(minutes=31)
        set_clock(after.strftime("%Y-%m-%dT%H:%M:%SZ"))
        get_success_data(api_client.no_show_appointment(appt["id"], FRONT))
