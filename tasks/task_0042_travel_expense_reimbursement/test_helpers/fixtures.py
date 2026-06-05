"""Composite setup helpers for Travel & Expense tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.

Fixtures use get_success_data() (lenient 2xx) for setup so failures surface as
clear "Setup failed" rather than confusing assertion errors.

Identity threading (PRD §2.1): Traveler/Approver are entity_backed, so ownership-
gated calls thread the real entity id via make_traveler_headers / make_approver_headers.
FinanceAdmin is opaque and uses the shared admin headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_finance_admin_headers,
    make_traveler_headers,
    make_approver_headers,
)
from .factories import (
    create_approver_payload,
    create_traveler_payload,
    create_travel_policy_payload,
    create_per_diem_rate_payload,
    create_trip_request_payload,
    issue_virtual_card_payload,
    create_expense_report_payload,
    create_expense_line_payload,
    create_receipt_payload,
    ocr_receipt_payload,
    create_approval_step_payload,
)

ADMIN = make_finance_admin_headers()


# --------------------------------------------------------------------------
# Tier 0: Identity & config primitives
# --------------------------------------------------------------------------
def create_approver(approval_limit_cents=1_000_000, **overrides) -> dict:
    """Create an Approver (ACTIVE). Returns the approver entity."""
    payload = create_approver_payload(
        approval_limit_cents=approval_limit_cents,
        email=f"mgr-{_uniq()}@x.com",
        **overrides,
    )
    return get_success_data(api_client.create_approver(payload, ADMIN))


def create_traveler(manager_id, **overrides) -> dict:
    """Create a Traveler (ACTIVE) managed by manager_id. Returns the traveler entity."""
    payload = create_traveler_payload(
        manager_id=manager_id,
        email=f"trav-{_uniq()}@x.com",
        **overrides,
    )
    return get_success_data(api_client.create_traveler(payload, ADMIN))


def create_active_policy(**overrides) -> dict:
    """Create a TravelPolicy and activate it. Returns the ACTIVE policy entity."""
    policy = get_success_data(
        api_client.create_travel_policy(create_travel_policy_payload(**overrides), ADMIN)
    )
    get_success_data(api_client.activate_travel_policy(policy["id"], ADMIN))
    return policy


def create_draft_policy(**overrides) -> dict:
    """Create a TravelPolicy in DRAFT (not activated). Returns the policy entity."""
    return get_success_data(
        api_client.create_travel_policy(create_travel_policy_payload(**overrides), ADMIN)
    )


def create_per_diem_rate(state_code="CA", lodging_cap_cents=20000, mie_cents=8000) -> dict:
    """Create a PerDiemRate (immutable GSA reference). Returns the rate entity."""
    return get_success_data(
        api_client.create_per_diem_rate(
            create_per_diem_rate_payload(
                state_code=state_code,
                lodging_cap_cents=lodging_cap_cents,
                mie_cents=mie_cents,
            ),
            ADMIN,
        )
    )


_COUNTER = [0]


def _uniq() -> int:
    _COUNTER[0] += 1
    return _COUNTER[0]


# --------------------------------------------------------------------------
# Tier 1: Base environment (policy + rate + approver + traveler)
# --------------------------------------------------------------------------
def setup_base_env(
    lodging_cap_cents=20000,
    mie_cents=8000,
    state_code="CA",
    approval_limit_cents=1_000_000,
    **policy_overrides,
) -> dict:
    """ACTIVE policy + per-diem rate + approver + traveler.

    Returns dict with keys: policy, rate, approver, traveler, admin_headers,
    traveler_headers, approver_headers.
    """
    approver = create_approver(approval_limit_cents=approval_limit_cents)
    traveler = create_traveler(manager_id=approver["id"])
    policy = create_active_policy(**policy_overrides)
    rate = create_per_diem_rate(
        state_code=state_code, lodging_cap_cents=lodging_cap_cents, mie_cents=mie_cents
    )
    return {
        "policy": policy,
        "rate": rate,
        "approver": approver,
        "traveler": traveler,
        "admin_headers": ADMIN,
        "traveler_headers": make_traveler_headers(traveler["id"]),
        "approver_headers": make_approver_headers(approver["id"]),
    }


# --------------------------------------------------------------------------
# Tier 1/2: Trip creation & state progression
# --------------------------------------------------------------------------
def create_pending_trip(env, budget_total_cents=100000,
                        start_date="2026-06-01", end_date="2026-06-03",
                        destination_state="CA") -> dict:
    """Create a PENDING trip for env's traveler. Returns the trip entity."""
    payload = create_trip_request_payload(
        env["traveler"]["id"],
        budget_total_cents=budget_total_cents,
        start_date=start_date,
        end_date=end_date,
        destination_state=destination_state,
    )
    return get_success_data(
        api_client.create_trip_request(payload, env["traveler_headers"])
    )


def create_approved_trip(env, budget_total_cents=100000,
                         start_date="2026-06-01", end_date="2026-06-03",
                         destination_state="CA") -> dict:
    """Create an in-policy trip and submit it so it AUTO_APPROVED->APPROVED.

    Caller must size budget so requires_oop is false (budget <= 2*baseline*nights).
    Returns the trip entity AFTER submission (status APPROVED, version bumped).
    """
    trip = create_pending_trip(
        env, budget_total_cents=budget_total_cents,
        start_date=start_date, end_date=end_date,
        destination_state=destination_state,
    )
    submitted = get_success_data(
        api_client.submit_trip_request(trip["id"], env["traveler_headers"])
    )
    return submitted


def setup_approved_trip(budget_total_cents=100000,
                        start_date="2026-06-01", end_date="2026-06-03",
                        lodging_cap_cents=20000, mie_cents=8000,
                        **policy_overrides) -> dict:
    """Base env + an APPROVED in-policy CA trip.

    Returns the env dict augmented with key 'trip' (the APPROVED trip entity).
    """
    env = setup_base_env(
        lodging_cap_cents=lodging_cap_cents, mie_cents=mie_cents, **policy_overrides
    )
    env["trip"] = create_approved_trip(
        env, budget_total_cents=budget_total_cents,
        start_date=start_date, end_date=end_date,
    )
    return env


# --------------------------------------------------------------------------
# Tier 3: Virtual card
# --------------------------------------------------------------------------
def issue_card(env, trip, load_limit_cents=100000) -> dict:
    """Issue an ACTIVE virtual card against an APPROVED trip using its current version.

    Re-reads the trip version to avoid stale-version rejection. Returns the card entity.
    """
    fresh = get_success_data(
        api_client.get_trip_request(trip["id"], env["admin_headers"])
    )
    return get_success_data(
        api_client.issue_virtual_card(
            trip["id"],
            issue_virtual_card_payload(fresh["version"], load_limit_cents=load_limit_cents),
            env["admin_headers"],
        )
    )


def setup_approved_trip_with_card(load_limit_cents=100000, budget_total_cents=100000,
                                  **trip_overrides) -> dict:
    """APPROVED trip + an ACTIVE virtual card. Returns env augmented with 'card'."""
    env = setup_approved_trip(budget_total_cents=budget_total_cents, **trip_overrides)
    env["card"] = issue_card(env, env["trip"], load_limit_cents=load_limit_cents)
    return env


# --------------------------------------------------------------------------
# Tier 2/3: Reports and lines
# --------------------------------------------------------------------------
def create_report(env, trip, per_diem_method=None, title="Test Report") -> dict:
    """Create a DRAFT expense report against a trip. Returns the report entity."""
    overrides = {"title": title}
    if per_diem_method is not None:
        overrides["per_diem_method"] = per_diem_method
    payload = create_expense_report_payload(trip["id"], **overrides)
    return get_success_data(
        api_client.create_expense_report(payload, env["traveler_headers"])
    )


def add_line(env, report, line_type, claimed_amount_cents=0, **type_fields) -> dict:
    """Add an expense line to a DRAFT report. Returns the line entity."""
    payload = create_expense_line_payload(
        report["id"], line_type, claimed_amount_cents=claimed_amount_cents, **type_fields
    )
    return get_success_data(
        api_client.create_expense_line(payload, env["traveler_headers"])
    )


def add_flight_line(env, report, claimed_amount_cents, cabin_class="ECONOMY",
                    scheduled_hours=4, advance_days=20, virtual_card_id=None) -> dict:
    """Add a FLIGHT line (PRD §3.5)."""
    extra = {
        "cabin_class": cabin_class,
        "scheduled_hours": scheduled_hours,
        "advance_days": advance_days,
    }
    if virtual_card_id is not None:
        extra["virtual_card_id"] = virtual_card_id
    return add_line(env, report, "FLIGHT", claimed_amount_cents=claimed_amount_cents, **extra)


def add_flight_line_with_receipt(env, report, claimed_amount_cents, cabin_class="ECONOMY",
                                 scheduled_hours=4, advance_days=20,
                                 virtual_card_id=None) -> dict:
    """Add a FLIGHT line and substantiate it with a VERIFIED receipt (PRD §3.7).

    PRD §3.7: "Any line whose computed reimbursable_amount_cents is at or above the
    policy's receipt_required_threshold_cents must have a VERIFIED receipt before its
    report may be submitted." A material flight line (reimbursable >= threshold) must
    therefore carry a verified receipt for the report to clear the submit gate. The
    receipt's ocr_amount_cents must equal the line's claimed_amount_cents to verify
    (PRD §3.7), so the receipt is OCR'd to the claimed amount.
    """
    line = add_flight_line(
        env, report, claimed_amount_cents, cabin_class=cabin_class,
        scheduled_hours=scheduled_hours, advance_days=advance_days,
        virtual_card_id=virtual_card_id,
    )
    upload_ocr_verified_receipt(env, line, ocr_amount_cents=claimed_amount_cents)
    return line


def add_lodging_line(env, report, claimed_amount_cents, check_in_date, check_out_date,
                     virtual_card_id=None) -> dict:
    """Add a LODGING line (PRD §3.5)."""
    extra = {"check_in_date": check_in_date, "check_out_date": check_out_date}
    if virtual_card_id is not None:
        extra["virtual_card_id"] = virtual_card_id
    return add_line(env, report, "LODGING", claimed_amount_cents=claimed_amount_cents, **extra)


def add_meal_line(env, report, claimed_amount_cents) -> dict:
    """Add a MEAL line (PRD §3.5 — per-line reimbursable is 0; meal handled at report level)."""
    return add_line(env, report, "MEAL", claimed_amount_cents=claimed_amount_cents)


def add_cdw_line(env, report, claimed_amount_cents, rental_days) -> dict:
    """Add a RENTAL_CDW line (PRD §3.5)."""
    return add_line(env, report, "RENTAL_CDW",
                    claimed_amount_cents=claimed_amount_cents, rental_days=rental_days)


def add_mileage_line(env, report, miles) -> dict:
    """Add an out-of-pocket MILEAGE line (PRD §3.5, claimed_amount_cents is 0)."""
    return add_line(env, report, "MILEAGE", claimed_amount_cents=0, miles=miles)


def submit_report(env, report) -> dict:
    """Submit a DRAFT report for review. Returns the SUBMITTED report entity."""
    return get_success_data(
        api_client.submit_expense_report(report["id"], env["traveler_headers"])
    )


def decide_report(env, report, decision, return_reason=None) -> dict:
    """Approver decides a SUBMITTED report. Returns the response data."""
    payload = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return get_success_data(
        api_client.decide_expense_report(report["id"], payload, env["approver_headers"])
    )


# --------------------------------------------------------------------------
# Tier 3: Receipts
# --------------------------------------------------------------------------
def upload_receipt(env, line) -> dict:
    """Upload a receipt (UPLOADED) for a line. Returns the receipt entity."""
    return get_success_data(
        api_client.create_receipt(create_receipt_payload(line["id"]), env["traveler_headers"])
    )


def upload_ocr_verified_receipt(env, line, ocr_amount_cents) -> dict:
    """Upload -> OCR -> VERIFY a receipt for a line.

    ocr_amount_cents must equal the line's claimed_amount_cents for VERIFY to succeed.
    Returns the VERIFIED receipt entity.
    """
    receipt = upload_receipt(env, line)
    get_success_data(
        api_client.ocr_receipt(
            receipt["id"], ocr_receipt_payload(ocr_amount_cents), env["admin_headers"]
        )
    )
    return get_success_data(api_client.verify_receipt(receipt["id"], env["admin_headers"]))


# --------------------------------------------------------------------------
# Tier 3: Out-of-policy approval chain
# --------------------------------------------------------------------------
def add_approval_step(env, report, approver_id, step_order) -> dict:
    """Add a PENDING out-of-policy approval step to a report. Returns the step entity."""
    payload = create_approval_step_payload(report["id"], approver_id, step_order)
    return get_success_data(api_client.create_approval_step(payload, env["admin_headers"]))


# --------------------------------------------------------------------------
# Tier 4/5: Full-lifecycle shortcuts used by cascade / invariant tests
# --------------------------------------------------------------------------
def setup_submitted_report_with_card_line(
    load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
) -> dict:
    """APPROVED trip + ACTIVE card + SUBMITTED report holding one in-policy ECONOMY
    FLIGHT line charged to the card (PENDING hold).

    Returns env augmented with: trip, card, report, line.
    Used by the approve/reject cascade and card-conservation tests.
    """
    env = setup_approved_trip_with_card(
        load_limit_cents=load_limit_cents, budget_total_cents=budget_total_cents
    )
    # ITEMIZED so the no-meal-line report's meal_reimbursable_cents is min(0, per-diem
    # total) = 0 (PRD §3.6). Under the default PER_DIEM method, meal_reimbursable_cents
    # is the full GSA per-diem total regardless of meal lines, which would add the trip's
    # per-diem to total_reimbursable_cents and obscure the single flight line's
    # contribution that the card-capture / trip-commit cascade assertions isolate.
    report = create_report(env, env["trip"], per_diem_method="ITEMIZED",
                           title="Card Line Report")
    line = add_flight_line(
        env, report, claimed_amount_cents=line_claimed_cents,
        cabin_class="ECONOMY", scheduled_hours=4, advance_days=20,
        virtual_card_id=env["card"]["id"],
    )
    # PRD §3.7: a material line (reimbursable >= receipt_required_threshold_cents,
    # default 7500) must carry a VERIFIED receipt before its report may be submitted.
    # The in-policy ECONOMY flight's reimbursable equals its claimed amount, which is
    # well above the default threshold, so substantiate it before submitting.
    upload_ocr_verified_receipt(env, line, ocr_amount_cents=line_claimed_cents)
    env["report"] = submit_report(env, report)
    env["line"] = line
    return env


def setup_submitted_report_out_of_pocket_flight(
    budget_total_cents=100000, claimed_cents=30000
) -> dict:
    """APPROVED trip + SUBMITTED report with one in-policy ECONOMY out-of-pocket FLIGHT line.

    Returns env augmented with: trip, report, line.
    """
    env = setup_approved_trip(budget_total_cents=budget_total_cents)
    report = create_report(env, env["trip"], title="OOP Flight Report")
    line = add_flight_line(
        env, report, claimed_amount_cents=claimed_cents,
        cabin_class="ECONOMY", scheduled_hours=4, advance_days=20,
    )
    # PRD §3.7: material line needs a VERIFIED receipt before submit.
    upload_ocr_verified_receipt(env, line, ocr_amount_cents=claimed_cents)
    env["report"] = submit_report(env, report)
    env["line"] = line
    return env
