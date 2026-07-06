"""Composite setup helpers for the Mobile Screening API.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test.
Setup calls use get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]
BC = TEST_USERS["billing_clerk_headers"]
NAV = TEST_USERS["patient_navigator_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: program backbone + published event
# ---------------------------------------------------------------------------
def create_unit(modality="BLOOD_PANEL", daily_capacity=10, name="Van B"):
    return get_success_data(
        api_client.create_mobile_unit(
            f.create_mobile_unit_payload(name=name, modality=modality, daily_capacity=daily_capacity), PM
        )
    )


def create_staff(role_type, modality, full_name="Staff"):
    return get_success_data(
        api_client.create_staff(
            f.create_staff_payload(full_name=full_name, role_type=role_type, modality=modality), PM
        )
    )


def create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1", name="Acme"):
    return get_success_data(
        api_client.create_sponsor(
            f.create_sponsor_payload(name=name, sponsor_type=sponsor_type, viewer_user_id=viewer_user_id), PM
        )
    )


def create_grant(sponsor_id, total_budget_cents=10000, name="Fund"):
    return get_success_data(
        api_client.create_grant(
            f.create_grant_payload(sponsor_id, name=name, total_budget_cents=total_budget_cents), PM
        )
    )


def create_event(sponsor_id, unit_id, modality="BLOOD_PANEL", event_date="2026-06-11",
                 site_label="L1", window_start_min=540, window_end_min=720):
    return get_success_data(
        api_client.create_event(
            f.create_event_payload(
                sponsor_id, unit_id, modality=modality, event_date=event_date, site_label=site_label,
                window_start_min=window_start_min, window_end_min=window_end_min,
            ),
            PM,
        )
    )


def publish_event(event):
    return get_success_data(
        api_client.publish_event(event["id"], {"expected_event_version": event["version"]}, PM)
    )


def create_published_event(modality="BLOOD_PANEL", daily_capacity=10, event_date="2026-06-11",
                           sponsor_type="EMPLOYER", viewer_user_id="sv1",
                           window_start_min=540, window_end_min=720):
    """Create unit + sponsor + event and publish it. Returns (unit, sponsor, event)."""
    unit = create_unit(modality=modality, daily_capacity=daily_capacity)
    sponsor = create_sponsor(sponsor_type=sponsor_type, viewer_user_id=viewer_user_id)
    event = create_event(sponsor["id"], unit["id"], modality=modality, event_date=event_date,
                         window_start_min=window_start_min, window_end_min=window_end_min)
    published = publish_event(event)
    return unit, sponsor, published


def register_participant(pay_type="SELF_PAY", grant_id=None, insurance_member_id=None,
                         full_name="P", date_of_birth="1980-01-01"):
    payload = f.create_participant_payload(full_name=full_name, date_of_birth=date_of_birth, pay_type=pay_type)
    if grant_id is not None:
        payload["grant_id"] = grant_id
    if insurance_member_id is not None:
        payload["insurance_member_id"] = insurance_member_id
    return get_success_data(api_client.create_participant(payload, PM))


def book_appointment(event_id, participant_id, slot_start_min=560, slot_duration_min=30):
    return get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(event_id, participant_id,
                                         slot_start_min=slot_start_min, slot_duration_min=slot_duration_min),
            PM,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: appointment lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_screened_appointment(pay_type="SELF_PAY", modality="BLOOD_PANEL",
                                grant_id=None, insurance_member_id=None,
                                grant_total_budget_cents=None, event_date="2026-06-11",
                                slot_start_min=560):
    """Full chain: unit + credentialed staff + sponsor (+grant) + published event +
    participant + appointment consented, checked-in, and SCREENED (charge created).

    Returns dict with keys: unit, sponsor, grant, event, participant, appointment, charge.
    """
    screen_role = "TECHNOLOGIST" if modality in ("MAMMOGRAPHY", "BONE_DENSITY", "SKIN") else "PHLEBOTOMIST"
    if modality == "BLOOD_PANEL":
        screen_role = "PHLEBOTOMIST"

    unit = create_unit(modality=modality)
    create_staff(screen_role, modality, full_name="Screener")
    if modality == "MAMMOGRAPHY":
        create_staff("RADIOLOGIST", "MAMMOGRAPHY", full_name="Rad R")

    grant = None
    if pay_type == "GRANT":
        sponsor = create_sponsor(sponsor_type="GRANT", viewer_user_id="sv2", name="GrantBody")
        budget = grant_total_budget_cents if grant_total_budget_cents is not None else 10000
        grant = create_grant(sponsor["id"], total_budget_cents=budget)
        if grant_id is None:
            grant_id = grant["id"]
    else:
        sponsor = create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")

    event = create_event(sponsor["id"], unit["id"], modality=modality, event_date=event_date)
    event = publish_event(event)

    participant = register_participant(pay_type=pay_type, grant_id=grant_id,
                                       insurance_member_id=insurance_member_id)
    appt = book_appointment(event["id"], participant["id"], slot_start_min=slot_start_min)
    get_success_data(api_client.consent_appointment(appt["id"], CS))
    get_success_data(api_client.checkin_appointment(appt["id"], CS))
    appt = get_success_data(api_client.screen_appointment(appt["id"], CS))

    charges = get_success_data(api_client.list_charges(BC, params={"appointment_id": appt["id"]}))
    charge = charges[0] if charges else None
    return {
        "unit": unit, "sponsor": sponsor, "grant": grant, "event": event,
        "participant": participant, "appointment": appt, "charge": charge,
    }


def create_result_ready_appointment(result="ABNORMAL", flagged_urgent=False, modality="MAMMOGRAPHY",
                                    pay_type="SELF_PAY"):
    """Screened appointment advanced to RESULT_READY with the given result.
    Returns dict from create_screened_appointment plus 'appointment' updated and 'referral' (or None)."""
    ctx = create_screened_appointment(pay_type=pay_type, modality=modality)
    payload = f.deliver_result_payload(result=result)
    if result == "ABNORMAL":
        payload["flagged_urgent"] = flagged_urgent
    appt = get_success_data(api_client.deliver_result(ctx["appointment"]["id"], payload, CS))
    ctx["appointment"] = appt
    referral = None
    if result == "ABNORMAL":
        refs = get_success_data(api_client.list_referrals(NAV, params={"appointment_id": appt["id"]}))
        referral = refs[0] if refs else None
    ctx["referral"] = referral
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: no-show / block accumulation
# ---------------------------------------------------------------------------
def create_blocked_participant(unit_id=None, sponsor_id=None, num_no_shows=3):
    """Register a participant and drive it through `num_no_shows` no-shows on distinct
    closed events (reaching BLOCKED when num_no_shows >= strike limit 3).

    Returns (participant, unit_id, sponsor_id).
    """
    if unit_id is None:
        unit_id = create_unit(modality="BLOOD_PANEL")["id"]
    if sponsor_id is None:
        sponsor_id = create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")["id"]
    participant = register_participant(pay_type="SELF_PAY", full_name="Pat N")

    for i in range(num_no_shows):
        # each no-show needs its own event day (unit occupies a whole day exclusively)
        event = create_event(sponsor_id, unit_id, modality="BLOOD_PANEL",
                             event_date=f"2026-06-0{i + 1}", site_label=f"L{i + 1}")
        event = publish_event(event)
        appt = book_appointment(event["id"], participant["id"], slot_start_min=540)
        get_success_data(api_client.close_event(event["id"], PM))
        get_success_data(api_client.mark_no_show(appt["id"], PM))

    participant = get_success_data(api_client.get_participant(participant["id"], PM))
    return participant, unit_id, sponsor_id


def create_participant_with_two_strikes():
    """Participant with no_show_strikes == 2 plus a third CLOSED event holding a
    SCHEDULED (not-yet-no-showed) appointment. Returns (participant, third_appointment_id)."""
    unit_id = create_unit(modality="BLOOD_PANEL")["id"]
    sponsor_id = create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")["id"]
    participant = register_participant(pay_type="SELF_PAY", full_name="Pat N")

    for i in range(2):
        event = create_event(sponsor_id, unit_id, modality="BLOOD_PANEL",
                             event_date=f"2026-06-0{i + 1}", site_label=f"L{i + 1}")
        event = publish_event(event)
        appt = book_appointment(event["id"], participant["id"], slot_start_min=540)
        get_success_data(api_client.close_event(event["id"], PM))
        get_success_data(api_client.mark_no_show(appt["id"], PM))

    event3 = create_event(sponsor_id, unit_id, modality="BLOOD_PANEL",
                         event_date="2026-06-03", site_label="L3")
    event3 = publish_event(event3)
    appt3 = book_appointment(event3["id"], participant["id"], slot_start_min=540)
    get_success_data(api_client.close_event(event3["id"], PM))
    # Re-read so the returned participant reflects the two accumulated strikes
    # (register_participant returned the pre-no-show snapshot with strikes==0).
    participant = get_success_data(api_client.get_participant(participant["id"], PM))
    return participant, appt3["id"]
