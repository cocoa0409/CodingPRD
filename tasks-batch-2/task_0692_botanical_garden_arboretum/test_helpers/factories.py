"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides for the values
a test needs to control. FK ids must always be supplied by the caller.
"""


# --- Garden (PRD §3.1) -------------------------------------------------------
def create_garden_payload(**overrides) -> dict:
    payload = {"name": "Test Garden"}
    payload.update(overrides)
    return payload


# --- MembershipPlan (PRD §3.1) -----------------------------------------------
def create_plan_payload(garden_id, tier="INDIVIDUAL", annual_fee_cents=12000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "tier": tier,
        "annual_fee_cents": annual_fee_cents,
    }
    payload.update(overrides)
    return payload


# --- Membership (PRD §3.2) ---------------------------------------------------
def create_membership_payload(garden_id, plan_id, primary_member_name="Test Member", **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "plan_id": plan_id,
        "primary_member_name": primary_member_name,
    }
    payload.update(overrides)
    return payload


# --- TimeSlot (PRD §3.1) -----------------------------------------------------
def create_time_slot_payload(garden_id, starts_at, ends_at, capacity=10, ga_price_cents=2000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "ga_price_cents": ga_price_cents,
    }
    payload.update(overrides)
    return payload


# --- Reservation (PRD §3.3) --------------------------------------------------
def create_reservation_payload(garden_id, time_slot_id, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "time_slot_id": time_slot_id,
    }
    payload.update(overrides)
    return payload


# --- EventTicket (PRD §3.4) --------------------------------------------------
def create_event_ticket_payload(garden_id, exhibit_name="Test Exhibit", list_price_cents=2000, quantity=1, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "exhibit_name": exhibit_name,
        "list_price_cents": list_price_cents,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


# --- ProgramSession (PRD §3.1) -----------------------------------------------
def create_program_session_payload(garden_id, title="Test Session", starts_at="2026-07-01T09:00:00Z", capacity=5, tuition_cents=10000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "title": title,
        "starts_at": starts_at,
        "capacity": capacity,
        "tuition_cents": tuition_cents,
    }
    payload.update(overrides)
    return payload


# --- Registration (PRD §3.5) -------------------------------------------------
def create_registration_payload(garden_id, program_session_id, participant_name="Test Participant", **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "program_session_id": program_session_id,
        "participant_name": participant_name,
    }
    payload.update(overrides)
    return payload


# --- Venue (PRD §3.1) --------------------------------------------------------
def create_venue_payload(garden_id, name="Test Hall", hourly_rate_cents=20000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
    }
    payload.update(overrides)
    return payload


# --- Rental (PRD §3.6) -------------------------------------------------------
def create_rental_payload(garden_id, venue_id, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "venue_id": venue_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


# --- Donation (PRD §3.7) -----------------------------------------------------
def create_donation_payload(garden_id, amount_cents=5000, **overrides) -> dict:
    payload = {
        "garden_id": garden_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# --- ConservancyFund (PRD §3.7) ----------------------------------------------
def create_conservancy_fund_payload(garden_id, **overrides) -> dict:
    payload = {"garden_id": garden_id}
    payload.update(overrides)
    return payload
