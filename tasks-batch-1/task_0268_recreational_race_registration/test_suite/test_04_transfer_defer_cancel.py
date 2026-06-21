"""Transfers, deferral, cancellation lockdown, ownership, and the event-cancel cascade.

Covers difficulty rules non_linear_state_machine (deferral self-reference),
transitive_cascade (event cancel), and corner instances under sections
state_machines, validations, rbac, and consistency_model.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_participant_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_REGULAR

RD = TEST_USERS["race_director_headers"]


# ---------------------------------------------------------------------------
# Cancel terminal lockdown / ownership (corner: state_machines, rbac)
# ---------------------------------------------------------------------------
def test_cancel_from_cancelled_returns_invalid_state(api):
    """PRD §3.4: "A participant may cancel their own registration from any of
    `PENDING_PAYMENT`, `CONFIRMED`, `BIB_ASSIGNED`, or `WAITLISTED`; cancelling from
    any other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=5)
    headers = make_participant_headers(participant["id"])
    fx.api_cancel(reg, participant)  # now CANCELLED (terminal)
    resp = api.cancel_registration(reg["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_participant_cannot_cancel_another_participants_registration(api):
    """PRD §2.1: "a participant may only mutate a `Registration`, `FundraisingPledge`,
    or `TransferRequest` whose owning `participant_id` equals their `X-User-ID`; a
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/participant_cannot_cancel_another_participants_registration
    """
    event, distance, wave, p1, reg = fx.setup_confirmed_registration(capacity_total=50)
    p2 = fx.create_participant()
    resp = api.cancel_registration(reg["id"], make_participant_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ---------------------------------------------------------------------------
# Transfer accept moves slot immediately (corner: consistency_model)
# ---------------------------------------------------------------------------
def test_transfer_accept_moves_slot_immediately(api):
    """PRD §3.4: "Acceptance moves the transfer to `ACCEPTED`, moves the original
    registration to terminal `TRANSFERRED`, and creates a new `Registration` for the
    recipient that inherits the same distance and wave, starts already `CONFIRMED`
    with `amount_paid_cents` of 0 because the paid slot simply carries over, and takes
    `entry_type` `STANDARD`. The distance's `confirmed_count` is unchanged because the
    slot moves rather than being freed, but `Distance.version` is still bumped."

    Design: Corner/consistency_model/transfer_accept_moves_slot_immediately
    """
    event, distance, wave, p1, reg = fx.setup_confirmed_registration(capacity_total=5)
    p2 = fx.create_participant()
    h1 = make_participant_headers(p1["id"])
    h2 = make_participant_headers(p2["id"])
    tr = validate_success(api.create_transfer_request(
        {"registration_id": reg["id"], "to_participant_id": p2["id"]}, h1),
        expected_status=201)
    resp = api.accept_transfer_request(tr["id"], h2)
    accepted = validate_success(resp)
    assert accepted["status"] == "ACCEPTED", f"expected ACCEPTED, got {accepted['status']}"
    reg_after = fx.get_registration_data(reg["id"])
    assert reg_after["status"] == "TRANSFERRED", \
        f"original registration must move to TRANSFERRED, got {reg_after['status']}"
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 1, \
        f"slot moves not frees: confirmed_count stays 1, got {dist['confirmed_count']}"


# ---------------------------------------------------------------------------
# Deferral self-referential cycle (difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
def test_deferral_creates_self_referential_pending_registration(api):
    """PRD §3.4: "Deferral computes `deferral_credit_cents` as the net base —
    `amount_paid_cents` minus the non-transferable `processing_fee_cents` — reduced by
    the deferral fee of 1500 cents, with the result floored at 0 so the credit is
    never negative."
    PRD §3.4: "The original registration moves to terminal `DEFERRED`, a new
    `PENDING_PAYMENT` registration is created on the target event's matching distance
    with `deferred_to_registration_id` on the original pointing to it".

    Design: Difficulty/non_linear_state_machine/registration_deferral_self_referential_cycle
    """
    # Source MARATHON CONFIRMED at REGULAR: paid 5660, fee 160 -> net 5500;
    # credit = max(5500 - 1500, 0) = 4000.
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195)
    headers = make_participant_headers(participant["id"])
    # Target DRAFT event next year with a matching MARATHON distance.
    target = fx.create_event(name="Next Year Marathon", race_date_utc="2027-07-05T00:00:00Z",
                             registration_opens_utc="2027-01-01T00:00:00Z",
                             registration_closes_utc="2027-07-01T00:00:00Z")
    target_dist = fx.create_distance(target["id"], label="MARATHON", distance_km=42.195)
    fx.create_wave(target_dist["id"])
    fx.create_pricing_tier(target_dist["id"], tier_name="REGULAR",
                           effective_from_utc="2027-05-01T00:00:00Z", base_price_cents=6000)

    resp = api.defer_registration(reg["id"], {"target_event_id": target["id"]}, headers)
    deferred = validate_success(resp)
    assert deferred["status"] == "DEFERRED", f"expected DEFERRED, got {deferred['status']}"
    assert deferred["deferral_credit_cents"] == 4000, \
        f"expected deferral_credit_cents 4000, got {deferred['deferral_credit_cents']}"
    new_id = deferred["deferred_to_registration_id"]
    assert new_id, "deferred_to_registration_id must be set (self-reference to the new registration)"
    new_reg = fx.get_registration_data(new_id)
    assert new_reg["status"] == "PENDING_PAYMENT", \
        f"the deferred-into registration must be PENDING_PAYMENT, got {new_reg['status']}"


def test_deferral_frees_original_distance_slot(api):
    """PRD §3.4: "the original distance's `confirmed_count` is decremented and
    `Distance.version` bumped, and the freed slot promotes the head queued waitlist
    entry to `OFFERED`."

    Design: Difficulty/non_linear_state_machine/registration_deferral_self_referential_cycle
    """
    # Source MARATHON CONFIRMED -> confirmed_count 1; after deferral it drops to 0.
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195)
    headers = make_participant_headers(participant["id"])
    assert fx.get_distance_data(distance["id"])["confirmed_count"] == 1
    target = fx.create_event(name="Next Year Marathon", race_date_utc="2027-07-05T00:00:00Z",
                             registration_opens_utc="2027-01-01T00:00:00Z",
                             registration_closes_utc="2027-07-01T00:00:00Z")
    target_dist = fx.create_distance(target["id"], label="MARATHON", distance_km=42.195)
    fx.create_wave(target_dist["id"])
    fx.create_pricing_tier(target_dist["id"], tier_name="REGULAR",
                           effective_from_utc="2027-05-01T00:00:00Z", base_price_cents=6000)
    validate_success(api.defer_registration(reg["id"], {"target_event_id": target["id"]}, headers))
    assert fx.get_distance_data(distance["id"])["confirmed_count"] == 0, \
        "deferral must free the original distance's confirmed slot"


def test_defer_to_same_event_rejected(api):
    """PRD §3.4: "Deferring ... requires a `target_event_id` in the body whose event
    is in `DRAFT` or `OPEN`, differs from the current event, and offers a distance
    whose `label` matches the source distance's label; a target failing any of these
    conditions is rejected with `ERR_TARGET_EVENT_INVALID`."

    Design: Corner/validations/defer_target_event_same_as_source_rejected
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195)
    headers = make_participant_headers(participant["id"])
    resp = api.defer_registration(reg["id"], {"target_event_id": event["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_TARGET_EVENT_INVALID.value)


# ---------------------------------------------------------------------------
# Event cancel depth-3 cascade (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
def test_event_cancel_cascades_to_registrations_and_waitlist(api):
    """PRD §3.9: "Every non-terminal registration on every distance of the event is
    moved to `CANCELLED`, which in turn releases that distance's capacity and
    recomputes `confirmed_count`; every `QUEUED` or `OFFERED` waitlist entry on every
    distance is moved to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_to_registration_then_distance_then_waitlist
    """
    # Capacity 1: P1 CONFIRMED, P2 WAITLISTED (QUEUED). Cancel the event.
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=1)
    p2, reg2, wl2 = resolved[0]
    resp = api.cancel_event(event["id"], RD)
    cancelled_event = validate_success(resp)
    assert cancelled_event["status"] == "CANCELLED"
    assert fx.get_registration_data(reg1["id"])["status"] == "CANCELLED", \
        "confirmed registration must cascade to CANCELLED"
    assert fx.get_registration_data(reg2["id"])["status"] == "CANCELLED", \
        "waitlisted registration must cascade to CANCELLED"
    assert fx.get_waitlist_entry_data(wl2["id"])["status"] == "WITHDRAWN", \
        "queued waitlist entry must cascade to WITHDRAWN"
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 0, \
        f"capacity must be released, confirmed_count 0, got {dist['confirmed_count']}"


def test_event_cancel_increments_event_version(api):
    """PRD §3.9: "Cancelling moves the event to terminal `CANCELLED`, increments
    `Event.version`, and cascades across the whole event."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_to_registration_then_distance_then_waitlist
    """
    event, distance, wave, p1, reg1, resolved = fx.setup_capacity_one_with_waitlist(num_waitlisted=1)
    before = fx.get_event_data(event["id"])["version"]
    resp = api.cancel_event(event["id"], RD)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == before + 1, \
        f"Event.version must advance by 1 on cancel, was {before}, now {cancelled['version']}"
