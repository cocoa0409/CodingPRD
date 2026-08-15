"""Composite setup helpers for the rental reimbursement & loss-of-use desk.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch through the public API.
Setup calls use the lenient ``get_success_data`` validator so that setup
failures surface as clear "Setup step failed" errors.

Context convention: composite builders return a ``dict`` with entity payloads
under these keys (populated progressively):

    policyholder, shop, partner, claim, verification, repair_order,
    reservation, milestone, extension, class_change, invoice, recovery_case,
    lou_claim
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_claim_payload,
    create_class_change_payload,
    create_communication_log_payload,
    create_coverage_verification_payload,
    create_extension_request_payload,
    create_invoice_payload,
    create_loss_of_use_claim_payload,
    create_milestone_payload,
    create_policyholder_payload,
    create_rental_partner_payload,
    create_rental_reservation_payload,
    create_repair_order_payload,
    create_repair_shop_payload,
    decide_coverage_verification_payload,
    record_recovery_payment_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_rental_partner_headers,
    make_repair_shop_headers,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]
DESK = TEST_USERS["rental_desk_agent_headers"]
SETTLEMENT = TEST_USERS["settlement_approver_headers"]
RECOVERY = TEST_USERS["recovery_specialist_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# --------------------------------------------------------------------- clock


def set_clock(to_iso8601: str):
    """Advance the server's logical clock (SystemAdmin capability)."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


# --------------------------------------------------------------- directories


def register_policyholder(**overrides) -> dict:
    return get_success_data(api_client.create_policyholder(
        create_policyholder_payload(**overrides), ADMIN))


def register_repair_shop(**overrides) -> dict:
    return get_success_data(api_client.create_repair_shop(
        create_repair_shop_payload(**overrides), ADMIN))


def register_rental_partner(**overrides) -> dict:
    return get_success_data(api_client.create_rental_partner(
        create_rental_partner_payload(**overrides), ADMIN))


# ---------------------------------------------------------------- claim core


def open_claim(policyholder_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_claim(
        create_claim_payload(policyholder_id, **overrides), ADJUSTER))


def get_claim_view(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADJUSTER))


def get_reservation_view(reservation_id: str) -> dict:
    return get_success_data(api_client.get_rental_reservation(reservation_id, DESK))


def get_invoice_view(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ADJUSTER))


def get_extension_view(extension_request_id: str) -> dict:
    return get_success_data(api_client.get_extension_request(extension_request_id, DESK))


def get_repair_order_view(repair_order_id: str) -> dict:
    return get_success_data(api_client.get_repair_order(repair_order_id, ADJUSTER))


def get_lou_view(lou_id: str) -> dict:
    return get_success_data(api_client.get_loss_of_use_claim(lou_id, ADJUSTER))


# ------------------------------------------------------ coverage verificaton


def create_pending_verification(claim_id: str, expected_claim_version: Optional[int] = None) -> dict:
    if expected_claim_version is None:
        expected_claim_version = get_claim_view(claim_id)["version"]
    payload = create_coverage_verification_payload(claim_id, expected_claim_version)
    return get_success_data(api_client.create_coverage_verification(payload, ADJUSTER))


def decide_verification(verification_id: str, decision: str = "VERIFIED",
                        rental_eligible: bool = True, loss_of_use_eligible: bool = True,
                        denial_reason: Optional[str] = None) -> dict:
    payload = decide_coverage_verification_payload(
        decision=decision, rental_eligible=rental_eligible,
        loss_of_use_eligible=loss_of_use_eligible)
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.decide_coverage_verification(verification_id, payload, ADJUSTER))


def verify_claim_coverage(claim_id: str, rental_eligible: bool = True,
                          loss_of_use_eligible: bool = True) -> dict:
    """Create a verification and decide it VERIFIED. Returns the decision payload."""
    verification = create_pending_verification(claim_id)
    return decide_verification(verification["id"], "VERIFIED",
                               rental_eligible, loss_of_use_eligible)


# ------------------------------------------------------------- repair orders


def create_repair_order(claim_id: str, shop_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_repair_order(
        create_repair_order_payload(claim_id, **overrides),
        make_repair_shop_headers(shop_id)))


def approve_repair_order(repair_order_id: str) -> dict:
    return get_success_data(api_client.approve_repair_order(repair_order_id, ADJUSTER))


def start_repair_order(repair_order_id: str, shop_id: str) -> dict:
    return get_success_data(api_client.start_repair_order(
        repair_order_id, make_repair_shop_headers(shop_id)))


def complete_repair_order(repair_order_id: str, shop_id: str,
                          clock: Optional[str] = C.REPAIR_COMPLETION_CLOCK) -> dict:
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.complete_repair_order(
        repair_order_id, make_repair_shop_headers(shop_id)))


def report_milestone(repair_order_id: str, shop_id: str, milestone_type: str,
                     clock: Optional[str] = None, **overrides) -> dict:
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_milestone(
        repair_order_id, create_milestone_payload(milestone_type, **overrides),
        make_repair_shop_headers(shop_id)))


def report_delay(repair_order_id: str, shop_id: str, new_estimated_completion_date: str,
                 clock: Optional[str] = None, note: Optional[str] = None) -> dict:
    overrides = {"new_estimated_completion_date": new_estimated_completion_date}
    if note is not None:
        overrides["note"] = note
    return report_milestone(repair_order_id, shop_id, "DELAY_REPORTED",
                            clock=clock, **overrides)


# --------------------------------------------------------------- reservations


def book_reservation(claim_id: str, partner_id: str, repair_order_id: str,
                     expected_claim_version: Optional[int] = None, **overrides) -> dict:
    """Book a reservation in DRAFT. Reads the claim fresh for the OCC version
    unless the caller passes an explicit expected_claim_version."""
    if expected_claim_version is None:
        expected_claim_version = get_claim_view(claim_id)["version"]
    payload = create_rental_reservation_payload(
        claim_id, partner_id, repair_order_id, expected_claim_version, **overrides)
    return get_success_data(api_client.create_rental_reservation(payload, DESK))


def authorize_reservation(reservation_id: str) -> dict:
    return get_success_data(
        api_client.authorize_rental_reservation(reservation_id, DESK))


def activate_reservation(reservation_id: str, partner_id: str,
                         clock: Optional[str] = C.ACTIVATION_CLOCK) -> dict:
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.activate_rental_reservation(
        reservation_id, make_rental_partner_headers(partner_id)))


def return_reservation(reservation_id: str, partner_id: str,
                       clock: Optional[str] = C.RETURN_CLOCK) -> dict:
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.return_rental_reservation(
        reservation_id, make_rental_partner_headers(partner_id)))


def cancel_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.cancel_rental_reservation(reservation_id, DESK))


def close_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.close_rental_reservation(reservation_id, DESK))


# ------------------------------------------------------------- extensions


def request_extension(reservation_id: str, milestone_id: str,
                      requested_additional_days: int,
                      expected_reservation_version: Optional[int] = None) -> dict:
    """Create an extension request. Reads the reservation fresh for the OCC
    version unless the caller passes an explicit expected_reservation_version."""
    if expected_reservation_version is None:
        expected_reservation_version = get_reservation_view(reservation_id)["version"]
    payload = create_extension_request_payload(
        reservation_id, milestone_id, requested_additional_days,
        expected_reservation_version)
    return get_success_data(api_client.create_extension_request(payload, DESK))


# ------------------------------------------------------------- class changes


def record_class_change(reservation_id: str, to_class: str, effective_date: str,
                        **overrides) -> dict:
    payload = create_class_change_payload(reservation_id, to_class, effective_date, **overrides)
    return get_success_data(api_client.create_class_change(payload, DESK))


# ------------------------------------------------------------ loss of use


def submit_lou_claim(claim_id: str, policyholder_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_loss_of_use_claim(
        create_loss_of_use_claim_payload(claim_id, **overrides),
        make_customer_headers(policyholder_id)))


# ------------------------------------------------------------------ invoices


def submit_invoice(reservation_id: str, partner_id: str, invoice_number: str,
                   **overrides) -> dict:
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(reservation_id, invoice_number, **overrides),
        make_rental_partner_headers(partner_id)))


# ------------------------------------------------------------ communications


def log_communication(claim_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_communication_log(
        create_communication_log_payload(claim_id, **overrides), DESK))


def list_claim_recovery_cases(claim_id: str) -> list:
    return get_success_data(api_client.list_claim_recovery_cases(claim_id, RECOVERY))


def list_claim_communications(claim_id: str) -> list:
    return get_success_data(api_client.list_claim_communication_logs(claim_id, ADJUSTER))


# ============================================================ composite tiers


def setup_verified_claim_context(partner_overrides: Optional[dict] = None,
                                 claim_overrides: Optional[dict] = None,
                                 rental_eligible: bool = True,
                                 loss_of_use_eligible: bool = True) -> dict:
    """Policyholder + shop + partner + claim decided VERIFIED.

    Returns ctx with keys: policyholder, shop, partner, claim (fresh view),
    verification.
    """
    policyholder = register_policyholder()
    shop = register_repair_shop()
    partner = register_rental_partner(**(partner_overrides or {}))
    claim = open_claim(policyholder["id"], **(claim_overrides or {}))
    verification = verify_claim_coverage(claim["id"], rental_eligible, loss_of_use_eligible)
    return {
        "policyholder": policyholder,
        "shop": shop,
        "partner": partner,
        "claim": get_claim_view(claim["id"]),
        "verification": verification,
    }


def add_approved_repair_order(ctx: dict, estimated_completion_date: str = C.BASE_REPAIR_ESTIMATE,
                              labor_hours_estimate: int = 12) -> dict:
    order = create_repair_order(ctx["claim"]["id"], ctx["shop"]["id"],
                                estimated_completion_date=estimated_completion_date,
                                labor_hours_estimate=labor_hours_estimate)
    ctx["repair_order"] = approve_repair_order(order["id"])
    return ctx["repair_order"]


def add_repair_order_in_progress(ctx: dict,
                                 estimated_completion_date: str = C.BASE_REPAIR_ESTIMATE,
                                 labor_hours_estimate: int = 12) -> dict:
    order = create_repair_order(ctx["claim"]["id"], ctx["shop"]["id"],
                                estimated_completion_date=estimated_completion_date,
                                labor_hours_estimate=labor_hours_estimate)
    approve_repair_order(order["id"])
    ctx["repair_order"] = start_repair_order(order["id"], ctx["shop"]["id"])
    return ctx["repair_order"]


def add_draft_reservation(ctx: dict, **overrides) -> dict:
    ctx["reservation"] = book_reservation(
        ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"], **overrides)
    return ctx["reservation"]


def setup_authorized_rental_scenario(partner_overrides: Optional[dict] = None,
                                     claim_overrides: Optional[dict] = None,
                                     repair_estimate: str = C.BASE_REPAIR_ESTIMATE,
                                     labor_hours_estimate: int = 12,
                                     reservation_overrides: Optional[dict] = None) -> dict:
    """Verified claim + repair order IN_PROGRESS + reservation AUTHORIZED."""
    ctx = setup_verified_claim_context(partner_overrides, claim_overrides)
    add_repair_order_in_progress(ctx, repair_estimate, labor_hours_estimate)
    reservation = add_draft_reservation(ctx, **(reservation_overrides or {}))
    ctx["reservation"] = authorize_reservation(reservation["id"])
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_active_rental_scenario(activation_clock: Optional[str] = C.ACTIVATION_CLOCK,
                                 **kwargs) -> dict:
    """Full base chain through pickup: reservation ACTIVE."""
    ctx = setup_authorized_rental_scenario(**kwargs)
    ctx["reservation"] = activate_reservation(
        ctx["reservation"]["id"], ctx["partner"]["id"], activation_clock)
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_returned_rental_scenario(return_clock: Optional[str] = C.RETURN_CLOCK,
                                   **kwargs) -> dict:
    """Base chain through vehicle return: reservation RETURNED (repair still
    IN_PROGRESS unless the caller completed it, so no overstay case by default)."""
    ctx = setup_active_rental_scenario(**kwargs)
    ctx["reservation"] = return_reservation(
        ctx["reservation"]["id"], ctx["partner"]["id"], return_clock)
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_pending_extension_scenario(new_estimated_completion_date: str = "2026-08-18",
                                     requested_additional_days: int = 4,
                                     delay_clock: Optional[str] = None,
                                     **kwargs) -> dict:
    """Active rental + DELAY_REPORTED milestone + SUBMITTED extension request.

    The delay cascade flips the reservation to EXTENSION_REVIEW; the extension
    request is then created against it and stays SUBMITTED.
    """
    ctx = setup_active_rental_scenario(**kwargs)
    milestone = report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"],
                             new_estimated_completion_date, clock=delay_clock)
    extension = request_extension(ctx["reservation"]["id"], milestone["id"],
                                  requested_additional_days)
    ctx["milestone"] = milestone
    ctx["extension"] = extension
    ctx["reservation"] = get_reservation_view(ctx["reservation"]["id"])
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_overstay_recovery_scenario(complete_clock: Optional[str] = C.REPAIR_COMPLETION_CLOCK,
                                     return_clock: Optional[str] = "2026-08-17T10:00:00Z",
                                     **kwargs) -> dict:
    """Repair completed 2026-08-14, vehicle returned 2026-08-17: the return
    assessment opens a RETURN_OVERSTAY recovery case (2 days x 6000 = 12000)."""
    ctx = setup_active_rental_scenario(**kwargs)
    ctx["repair_order"] = complete_repair_order(
        ctx["repair_order"]["id"], ctx["shop"]["id"], complete_clock)
    ctx["reservation"] = return_reservation(
        ctx["reservation"]["id"], ctx["partner"]["id"], return_clock)
    cases = list_claim_recovery_cases(ctx["claim"]["id"])
    assert len(cases) == 1, f"Setup failed: expected 1 recovery case, got {len(cases)}"
    ctx["recovery_case"] = cases[0]
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_manual_review_invoice_scenario(invoice_overrides: Optional[dict] = None,
                                         **kwargs) -> dict:
    """Returned rental + an over-window invoice that routes to MANUAL_REVIEW
    (billed 2026-08-05..2026-08-17 against the 2026-08-05..2026-08-15 window)."""
    ctx = setup_returned_rental_scenario(**kwargs)
    overrides = {"period_start": "2026-08-05", "period_end": "2026-08-17",
                 "daily_rate_cents": 6000, "tax_cents": 5280, "fees_cents": 0}
    overrides.update(invoice_overrides or {})
    invoice_number = overrides.pop("invoice_number", "INV-WIDE")
    ctx["invoice"] = submit_invoice(ctx["reservation"]["id"], ctx["partner"]["id"],
                                    invoice_number, **overrides)
    return ctx


def setup_auto_approved_invoice_scenario(invoice_overrides: Optional[dict] = None,
                                         **kwargs) -> dict:
    """Returned rental + a clean invoice that auto-adjudicates to AUTO_APPROVED
    (in-window, snapshot rate, per-day-rounded tax 4800, fees within the cap)."""
    ctx = setup_returned_rental_scenario(**kwargs)
    overrides = {"period_start": "2026-08-05", "period_end": "2026-08-15",
                 "daily_rate_cents": 6000, "tax_cents": 4800, "fees_cents": 2000}
    overrides.update(invoice_overrides or {})
    invoice_number = overrides.pop("invoice_number", "INV-CLEAN")
    ctx["invoice"] = submit_invoice(ctx["reservation"]["id"], ctx["partner"]["id"],
                                    invoice_number, **overrides)
    return ctx


def setup_lou_submitted_scenario(lou_overrides: Optional[dict] = None,
                                 **kwargs) -> dict:
    """Verified claim (loss-of-use eligible) + one SUBMITTED loss-of-use claim."""
    ctx = setup_verified_claim_context(**kwargs)
    ctx["lou_claim"] = submit_lou_claim(
        ctx["claim"]["id"], ctx["policyholder"]["id"], **(lou_overrides or {}))
    ctx["claim"] = get_claim_view(ctx["claim"]["id"])
    return ctx


def setup_settled_childless_claim() -> dict:
    """Claim with no children, settled by the settlement authority."""
    policyholder = register_policyholder()
    claim = open_claim(policyholder["id"])
    claim = get_success_data(api_client.settle_claim(claim["id"], SETTLEMENT))
    return {"policyholder": policyholder, "claim": claim}
