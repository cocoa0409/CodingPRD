"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup steps use the lenient
get_success_data() validator so a broken precondition surfaces as a clear
"Setup step failed" error.

Common chains:
  setup_member_with_active_prescription  — member ACTIVE + referral CONSUMED
                                           + prescription ACTIVE
  setup_frozen_cycle                     — ... + catalog items + cycle FROZEN
  setup_scheduled_delivery               — ... + authorization APPROVED
                                           + route + delivery SCHEDULED
  setup_delivered_delivery               — ... + delivery DELIVERED
  setup_draft_claim                      — ... + claim DRAFT
  setup_member_with_delivery_history     — member with N resolved deliveries
                                           inside the adherence window
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_member_payload,
    create_referral_payload,
    create_prescription_payload,
    create_menu_item_payload,
    create_menu_cycle_payload,
    create_cycle_item_payload,
    create_route_payload,
    create_delivery_payload,
    create_cold_chain_reading_payload,
    create_reauthorization_payload,
    create_outcome_assessment_payload,
    create_claim_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_billing_specialist_headers

_ADMIN = TEST_USERS["program_admin_headers"]
_COORD = TEST_USERS["care_coordinator_headers"]
_PROVIDER = TEST_USERS["referring_provider_headers"]
_DIETITIAN = TEST_USERS["dietitian_headers"]
_LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
_DRIVER = TEST_USERS["driver_headers"]
_BILLING = TEST_USERS["billing_specialist_headers"]
_PAYER = TEST_USERS["payer_reviewer_headers"]


# --- members ---------------------------------------------------------------

def create_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(create_member_payload(**overrides), _COORD))


def transition_member(member_id: str, target_status: str) -> dict:
    return get_success_data(api_client.set_member_status(member_id, target_status, _COORD))


def activate_member(member_id: str) -> dict:
    """INTAKE -> ACTIVE."""
    return transition_member(member_id, "ACTIVE")


def create_active_member(**overrides) -> dict:
    member = create_member(**overrides)
    return activate_member(member["id"])


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, _COORD))


# --- referrals ---------------------------------------------------------------

def create_referral(member_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_referral(create_referral_payload(member_id, **overrides), _PROVIDER))


def decide_referral(referral_id: str, decision: str) -> dict:
    return get_success_data(api_client.decide_referral(referral_id, decision, _COORD))


def create_accepted_referral(member_id: str, **overrides) -> dict:
    """SUBMITTED -> TRIAGED -> ACCEPTED."""
    referral = create_referral(member_id, **overrides)
    decide_referral(referral["id"], "TRIAGE")
    return decide_referral(referral["id"], "ACCEPT")


# --- diet prescriptions ------------------------------------------------------

def create_draft_prescription(member_id: str, referral_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_prescription(
        create_prescription_payload(member_id, referral_id, **overrides), _DIETITIAN))


def activate_prescription(prescription_id: str, member_id: str) -> dict:
    """DRAFT -> ACTIVE. Reads the member's current version for the required
    expected_member_version field (PRD §2.7)."""
    member = get_member(member_id)
    return get_success_data(
        api_client.activate_prescription(prescription_id, member["version"], _DIETITIAN))


def setup_member_with_active_prescription(member_overrides=None,
                                          referral_overrides=None,
                                          prescription_overrides=None) -> dict:
    """ACTIVE member + ACCEPTED referral + ACTIVE diet prescription."""
    member = create_active_member(**(member_overrides or {}))
    referral = create_accepted_referral(member["id"], **(referral_overrides or {}))
    prescription = create_draft_prescription(member["id"], referral["id"],
                                             **(prescription_overrides or {}))
    prescription = activate_prescription(prescription["id"], member["id"])
    return {"member": member, "referral": referral, "prescription": prescription}


# --- menu items and cycles ---------------------------------------------------

def create_menu_item(recipe: str = "rice_bowl", **overrides) -> dict:
    return get_success_data(
        api_client.create_menu_item(create_menu_item_payload(recipe, **overrides), _ADMIN))


def create_planned_cycle(member_id: str, prescription_id: str,
                         week_start_date: str = "2026-05-04",
                         item_lines=None) -> dict:
    """PLANNED cycle plus item lines. item_lines is a list of
    (menu_item_id, quantity) tuples."""
    cycle = get_success_data(api_client.create_menu_cycle(
        create_menu_cycle_payload(member_id, prescription_id,
                                  week_start_date=week_start_date),
        _DIETITIAN))
    lines = []
    for menu_item_id, quantity in (item_lines or []):
        lines.append(get_success_data(api_client.add_cycle_item(
            cycle["id"], create_cycle_item_payload(menu_item_id, quantity), _DIETITIAN)))
    cycle = get_success_data(api_client.get_menu_cycle(cycle["id"], _DIETITIAN))
    return {"cycle": cycle, "lines": lines}


def freeze_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.freeze_cycle(cycle_id, _DIETITIAN))


def setup_frozen_cycle(member_overrides=None, prescription_overrides=None,
                       item_specs=(("rice_bowl", 5),),
                       week_start_date: str = "2026-05-04") -> dict:
    """ACTIVE member + ACTIVE prescription + FROZEN cycle.

    item_specs: tuple of (recipe_name, quantity) pairs.
    """
    ctx = setup_member_with_active_prescription(member_overrides, None,
                                                prescription_overrides)
    menu_items = [create_menu_item(recipe) for recipe, _ in item_specs]
    planned = create_planned_cycle(
        ctx["member"]["id"], ctx["prescription"]["id"], week_start_date,
        [(item["id"], qty) for item, (_, qty) in zip(menu_items, item_specs)])
    cycle = freeze_cycle(planned["cycle"]["id"])
    ctx.update({"menu_items": menu_items, "cycle": cycle, "cycle_lines": planned["lines"]})
    return ctx


# --- outcome assessments and reauthorizations --------------------------------

def create_outcome_assessment(member_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_outcome_assessment(
        create_outcome_assessment_payload(member_id, **overrides), _DIETITIAN))


def create_reauthorization(member_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_reauthorization(
        create_reauthorization_payload(member_id, **overrides), _COORD))


def create_approved_authorization(member_id: str, authorization_number: str = "AUTH-1",
                                  assessed_at: str = "2026-04-20", **overrides) -> dict:
    """Outcome assessment on file + PENDING -> APPROVED reauthorization.

    Approval is taken while the adherence window is still vacuous
    (100.00 with no deliveries, PRD §3.6), so call this BEFORE scheduling
    any deliveries that are meant to count against adherence.
    """
    create_outcome_assessment(member_id, assessed_at=assessed_at)
    auth = create_reauthorization(member_id, **overrides)
    return get_success_data(
        api_client.approve_reauthorization(auth["id"], authorization_number, _PAYER))


def get_reauthorization(authorization_id: str) -> dict:
    return get_success_data(api_client.get_reauthorization(authorization_id, _LOGISTICS))


# --- routes and deliveries ---------------------------------------------------

def create_route(dispatch: bool = False, **overrides) -> dict:
    route = get_success_data(
        api_client.create_route(create_route_payload(**overrides), _LOGISTICS))
    if dispatch:
        route = get_success_data(api_client.dispatch_route(route["id"], _LOGISTICS))
    return route


def schedule_delivery(member_id: str, menu_cycle_id: str, route_id: str,
                      service_date: str) -> dict:
    return get_success_data(api_client.create_delivery(
        create_delivery_payload(member_id, menu_cycle_id, route_id,
                                service_date=service_date),
        _LOGISTICS))


def out_for_delivery(delivery_id: str) -> dict:
    return get_success_data(api_client.out_for_delivery(delivery_id, _DRIVER))


def mark_delivered(delivery_id: str) -> dict:
    return get_success_data(api_client.mark_delivered(delivery_id, _DRIVER))


def mark_failed(delivery_id: str) -> dict:
    return get_success_data(api_client.mark_failed(delivery_id, _DRIVER))


def get_delivery(delivery_id: str) -> dict:
    return get_success_data(api_client.get_delivery(delivery_id, _LOGISTICS))


def add_reading(delivery_id: str, recorded_at: str, temp_celsius: float) -> dict:
    return get_success_data(api_client.add_cold_chain_reading(
        delivery_id, create_cold_chain_reading_payload(recorded_at, temp_celsius), _DRIVER))


def setup_scheduled_delivery(auth_overrides=None, route_overrides=None,
                             dispatch_route: bool = True, **frozen_kwargs) -> dict:
    """FROZEN cycle + APPROVED authorization + route + SCHEDULED delivery."""
    ctx = setup_frozen_cycle(**frozen_kwargs)
    route_date = (route_overrides or {}).get("route_date", "2026-05-06")
    ctx["authorization"] = create_approved_authorization(
        ctx["member"]["id"], **(auth_overrides or {}))
    ctx["route"] = create_route(dispatch=dispatch_route, **(route_overrides or {}))
    ctx["delivery"] = schedule_delivery(ctx["member"]["id"], ctx["cycle"]["id"],
                                        ctx["route"]["id"], service_date=route_date)
    return ctx


def setup_out_for_delivery(**kwargs) -> dict:
    """SCHEDULED delivery taken OUT_FOR_DELIVERY (route must be DISPATCHED)."""
    ctx = setup_scheduled_delivery(dispatch_route=True, **kwargs)
    ctx["delivery"] = out_for_delivery(ctx["delivery"]["id"])
    return ctx


def setup_delivered_delivery(**kwargs) -> dict:
    """Delivery driven SCHEDULED -> OUT_FOR_DELIVERY -> DELIVERED."""
    ctx = setup_out_for_delivery(**kwargs)
    ctx["delivery"] = mark_delivered(ctx["delivery"]["id"])
    return ctx


# --- claims ------------------------------------------------------------------

def create_claim(member_id: str, menu_cycle_id: str, authorization_id: str) -> dict:
    """DRAFT claim; reads the authorization's current version for the
    required expected_reauthorization_version field (PRD §2.7)."""
    auth = get_reauthorization(authorization_id)
    return get_success_data(api_client.create_claim(
        create_claim_payload(member_id, menu_cycle_id, authorization_id,
                             auth["version"]),
        _BILLING))


def submit_claim(claim_id: str, submitted_by: str = "bill-1") -> dict:
    """DRAFT -> SUBMITTED; stamps submitted_by_user_id from X-User-ID."""
    return get_success_data(api_client.submit_claim(
        claim_id, make_billing_specialist_headers(submitted_by)))


def setup_draft_claim(extra_open_deliveries: int = 0, **kwargs) -> dict:
    """Delivered cycle + DRAFT claim against the APPROVED authorization.

    extra_open_deliveries schedules additional deliveries that are left
    SCHEDULED (keeping the cycle FROZEN instead of auto-FULFILLED). They are
    scheduled while the primary delivery is still OUT_FOR_DELIVERY, because
    PRD §3.5 auto-flips the cycle to FULFILLED the moment every delivery is
    terminal with at least one DELIVERED, and PRD §3.5 only permits
    scheduling against a FROZEN cycle.
    """
    ctx = setup_out_for_delivery(**kwargs)
    ctx["open_deliveries"] = [
        schedule_delivery(ctx["member"]["id"], ctx["cycle"]["id"],
                          ctx["route"]["id"], ctx["delivery"]["service_date"])
        for _ in range(extra_open_deliveries)
    ]
    ctx["delivery"] = mark_delivered(ctx["delivery"]["id"])
    ctx["claim"] = create_claim(ctx["member"]["id"], ctx["cycle"]["id"],
                                ctx["authorization"]["id"])
    return ctx


def setup_submitted_claim(submitted_by: str = "bill-1", **kwargs) -> dict:
    ctx = setup_draft_claim(**kwargs)
    ctx["claim"] = submit_claim(ctx["claim"]["id"], submitted_by=submitted_by)
    return ctx


# --- adherence history ---------------------------------------------------------

def setup_member_with_delivery_history(delivered_count: int, failed_count: int,
                                       member_overrides=None,
                                       week_start_date: str = "2026-04-13",
                                       route_date: str = "2026-04-15",
                                       assessed_at: str = "2026-04-10",
                                       auth_overrides=None) -> dict:
    """Member with resolved deliveries inside the trailing 84-day adherence
    window: `delivered_count` DELIVERED + `failed_count` FAILED.

    The authorization is requested and APPROVED while the adherence window is
    still vacuous (100.00), then the deliveries are driven to their terminal
    states. Returns ctx with keys: member, referral, prescription, cycle,
    authorization, route, deliveries_delivered, deliveries_failed.
    """
    total = delivered_count + failed_count
    ctx = setup_frozen_cycle(member_overrides=member_overrides,
                             item_specs=(("rice_bowl", total),),
                             week_start_date=week_start_date)
    auth_ov = {"authorized_units": max(total, 1), "max_amount_cents": 500_000,
               "start_date": "2026-01-01", "end_date": "2026-06-30"}
    auth_ov.update(auth_overrides or {})
    ctx["authorization"] = create_approved_authorization(
        ctx["member"]["id"], authorization_number="AUTH-HIST",
        assessed_at=assessed_at, **auth_ov)
    ctx["route"] = create_route(dispatch=True, route_date=route_date, driver_id="drv-hist")
    # Schedule every delivery first: per PRD §3.5 the cycle auto-flips to
    # FULFILLED the moment all its deliveries are terminal with at least one
    # DELIVERED, and scheduling is only permitted against a FROZEN cycle.
    # Driving the batch terminal one at a time would flip the cycle as soon
    # as the delivered prefix resolves, blocking the remaining schedules.
    pending = [
        schedule_delivery(ctx["member"]["id"], ctx["cycle"]["id"],
                          ctx["route"]["id"], service_date=route_date)
        for _ in range(total)
    ]
    for d in pending:
        out_for_delivery(d["id"])
    delivered = [mark_delivered(d["id"]) for d in pending[:delivered_count]]
    failed = [mark_failed(d["id"]) for d in pending[delivered_count:]]
    ctx["deliveries_delivered"] = delivered
    ctx["deliveries_failed"] = failed
    return ctx


def confirm_receipt(delivery_id: str, member_id: str) -> dict:
    """Member confirms receipt of their own DELIVERED delivery (PRD §3.5);
    identity is entity-backed so X-User-ID must equal the member id."""
    return get_success_data(
        api_client.confirm_receipt(delivery_id, make_member_headers(member_id)))
