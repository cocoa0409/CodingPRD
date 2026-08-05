"""Composite setup helpers.

The harness restarts the API server before every test, so every fixture below
builds its preconditions from scratch through published endpoints only.

The recurring preamble in this domain is long — move the clock, publish a plan
tier, register a panel physician, open a household, register a child, enrol the
child, then issue and pay the cycle invoice so the membership activates — and
almost every interesting behaviour sits behind it.  These helpers encapsulate
that chain so tests can focus on assertions.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_payload,
    cancel_membership_payload,
    create_child_payload,
    create_consult_booking_payload,
    create_encounter_payload,
    create_family_payload,
    create_form_request_payload,
    create_immunization_dose_payload,
    create_insurance_policy_payload,
    create_invoice_payload,
    create_membership_payload,
    create_physician_payload,
    create_waitlist_entry_payload,
    plus_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_headers,
    make_parent_headers,
    make_physician_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# ==========================================================================
# Primitives
# ==========================================================================


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the server's logical clock forward. Returns the clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_plan(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    body = dict(payload) if payload else plus_plan_payload()
    body.update(overrides)
    return get_success_data(api_client.create_membership_plan(body, ADMIN))


def create_physician(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_physician(create_physician_payload(**overrides), ADMIN)
    )


def create_family(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_family(create_family_payload(**overrides), ADMIN)
    )


def create_child(family_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_child(create_child_payload(family_id, **overrides), ADMIN)
    )


def create_policy(family_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_insurance_policy(
            create_insurance_policy_payload(family_id, **overrides), BILLING
        )
    )


def family_version(family_id: str) -> int:
    """Re-read the household's concurrency token."""
    return get_success_data(api_client.get_family(family_id, ADMIN))["version"]


def policy_version(policy_id: str) -> int:
    return get_success_data(api_client.get_insurance_policy(policy_id, BILLING))["version"]


def enroll(
    child_id: str,
    plan_id: str,
    physician_id: str,
    start_date: str,
    family_id: str,
    expected_family_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Enrol a child, reading the household version first unless one is given."""
    version = (
        expected_family_version
        if expected_family_version is not None
        else family_version(family_id)
    )
    payload = create_membership_payload(
        child_id, plan_id, physician_id, start_date, version
    )
    return get_success_data(api_client.create_membership(payload, headers or ADMIN))


def cancel(membership_id: str, family_id: str, effective_date: str) -> Dict[str, Any]:
    payload = cancel_membership_payload(effective_date, family_version(family_id))
    return get_success_data(api_client.cancel_membership(membership_id, payload, ADMIN))


# ==========================================================================
# Invoices
# ==========================================================================


def list_invoices(family_id: str, **filters) -> List[Dict[str, Any]]:
    params = {"family_id": family_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_invoices(BILLING, params=params))


def find_invoice(family_id: str, cycle_start_date: Optional[str] = None) -> Dict[str, Any]:
    """Return the household's invoice, optionally narrowed to one cycle."""
    filters = {}
    if cycle_start_date:
        filters["cycle_start_date"] = cycle_start_date
    rows = list_invoices(family_id, **filters)
    assert rows, f"Setup failed: no invoice for family {family_id} {filters}"
    return rows[0]


def get_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(invoice_id, BILLING))


def issue_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def pay_invoice(invoice_id: str, amount_paid_cents: Optional[int] = None) -> Dict[str, Any]:
    """Settle an issued invoice exactly; the amount defaults to its total."""
    amount = (
        amount_paid_cents
        if amount_paid_cents is not None
        else get_invoice(invoice_id)["total_cents"]
    )
    return get_success_data(
        api_client.pay_invoice(invoice_id, {"amount_paid_cents": amount}, BILLING)
    )


def issue_and_pay(family_id: str, cycle_start_date: Optional[str] = None) -> Dict[str, Any]:
    """Drive the household's cycle invoice DRAFT -> ISSUED -> PAID.

    Paying the cycle invoice is the only route to membership activation.
    """
    invoice = find_invoice(family_id, cycle_start_date)
    issue_invoice(invoice["id"])
    return pay_invoice(invoice["id"])


def open_invoice(family_id: str, cycle_start_date: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(family_id, cycle_start_date), BILLING
        )
    )


# ==========================================================================
# Composite scenarios
# ==========================================================================


def setup_practice(
    clock: str = "2026-06-01T00:00:00Z",
    plan: Optional[Dict[str, Any]] = None,
    panel_slot_cap: float = 20.0,
    licensed_state_codes: Optional[List[str]] = None,
    physician_name: str = "Dr Ada Reyes",
) -> Dict[str, Any]:
    """Clock + one plan tier + one panel physician.

    Returns dict(plan, physician, physician_headers).
    """
    set_clock(clock)
    plan_row = create_plan(plan)
    physician = create_physician(
        full_name=physician_name,
        panel_slot_cap=panel_slot_cap,
        licensed_state_codes=list(licensed_state_codes or ["CA"]),
    )
    return {
        "plan": plan_row,
        "physician": physician,
        "physician_headers": make_physician_headers(physician["id"]),
    }


def setup_household(
    household_name: str = "Test Household",
    family_monthly_cap_cents: int = 100_000,
    child_first_name: str = "Test Child",
    date_of_birth: str = "2026-04-01",
) -> Dict[str, Any]:
    """One household with one registered child.

    Returns dict(family, child, parent_headers).
    """
    family = create_family(
        household_name=household_name,
        family_monthly_cap_cents=family_monthly_cap_cents,
    )
    child = create_child(
        family["id"], first_name=child_first_name, date_of_birth=date_of_birth
    )
    return {
        "family": family,
        "child": child,
        "parent_headers": make_parent_headers(family["id"]),
    }


def setup_pending_membership(
    clock: str = "2026-06-01T00:00:00Z",
    plan: Optional[Dict[str, Any]] = None,
    panel_slot_cap: float = 20.0,
    licensed_state_codes: Optional[List[str]] = None,
    household_name: str = "Test Household",
    family_monthly_cap_cents: int = 100_000,
    child_first_name: str = "Test Child",
    date_of_birth: str = "2026-04-01",
    start_date: str = "2026-06-01",
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Practice + household + one enrolled membership still PENDING_ACTIVATION.

    Returns dict(plan, physician, physician_headers, family, child,
    parent_headers, membership, invoice, policy).
    """
    practice = setup_practice(
        clock=clock,
        plan=plan,
        panel_slot_cap=panel_slot_cap,
        licensed_state_codes=licensed_state_codes,
    )
    household = setup_household(
        household_name=household_name,
        family_monthly_cap_cents=family_monthly_cap_cents,
        child_first_name=child_first_name,
        date_of_birth=date_of_birth,
    )
    policy_row = None
    if policy is not None:
        policy_row = create_policy(household["family"]["id"], **policy)

    membership = enroll(
        household["child"]["id"],
        practice["plan"]["id"],
        practice["physician"]["id"],
        start_date,
        household["family"]["id"],
    )
    invoice = find_invoice(household["family"]["id"])
    return {
        **practice,
        **household,
        "membership": membership,
        "invoice": invoice,
        "policy": policy_row,
    }


def setup_active_membership(
    advance_clock_to: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """The workhorse: an ACTIVE membership whose cycle invoice is PAID.

    Accepts every keyword `setup_pending_membership` accepts, plus
    `advance_clock_to` to move the logical clock after activation.

    Returns the same dict, with `membership` and `invoice` re-read after
    payment so the membership reads ACTIVE.
    """
    scenario = setup_pending_membership(**kwargs)
    paid_invoice = issue_and_pay(scenario["family"]["id"])
    scenario["invoice"] = paid_invoice
    if advance_clock_to:
        set_clock(advance_clock_to)
    scenario["membership"] = get_success_data(
        api_client.get_membership(scenario["membership"]["id"], ADMIN)
    )
    return scenario


def setup_insured_active_membership(
    deductible_cents: int = 50_000,
    coinsurance_rate: float = 0.20,
    carrier_name: str = "BlueRidge",
    **kwargs,
) -> Dict[str, Any]:
    """An ACTIVE membership whose household holds one ACTIVE insurance policy."""
    kwargs.setdefault(
        "policy",
        {
            "carrier_name": carrier_name,
            "deductible_cents": deductible_cents,
            "coinsurance_rate": coinsurance_rate,
            "status": "ACTIVE",
        },
    )
    return setup_active_membership(**kwargs)


# ==========================================================================
# Encounters and service lines
# ==========================================================================


def open_encounter(
    membership_id: str,
    started_at: str,
    encounter_type: str = "SICK_VISIT",
    modality: str = "IN_PERSON",
    patient_state_code: str = "CA",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_encounter_payload(
        membership_id,
        started_at,
        encounter_type=encounter_type,
        modality=modality,
        patient_state_code=patient_state_code,
    )
    return get_success_data(api_client.create_encounter(payload, headers or COORDINATOR))


def complete_clinical(encounter_id: str, physician_id: str, note: str = "Seen and assessed"):
    return get_success_data(
        api_client.complete_clinical_encounter(
            encounter_id, {"clinical_note": note}, make_physician_headers(physician_id)
        )
    )


def submit_billing(encounter_id: str, submitter_user_id: str = "bs-submit") -> Dict[str, Any]:
    """Route an encounter's charges, stamping `submitted_by_user_id`."""
    return get_success_data(
        api_client.submit_encounter_billing(
            encounter_id, make_billing_headers(submitter_user_id)
        )
    )


def service_lines_for_encounter(encounter_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_service_lines(
            BILLING, params={"encounter_id": encounter_id, "limit": 100}
        )
    )


def service_lines_for_membership(membership_id: str, **filters) -> List[Dict[str, Any]]:
    params = {"membership_id": membership_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_service_lines(BILLING, params=params))


def get_service_line(service_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_service_line(service_line_id, BILLING))


def adjudicate(
    service_line_id: str,
    allowed_amount_cents: int,
    policy_id: str,
    adjudicator_user_id: str = "bs-adjudicate",
    **extra,
) -> Dict[str, Any]:
    payload = adjudicate_payload(
        allowed_amount_cents, policy_version(policy_id), **extra
    )
    return get_success_data(
        api_client.adjudicate_service_line(
            service_line_id, payload, make_billing_headers(adjudicator_user_id)
        )
    )


def setup_routed_insurance_line(
    submitter_user_id: str = "bs-submit",
    started_at: str = "2026-06-15T10:00:00Z",
    advance_clock_to: str = "2026-06-15T20:00:00Z",
    complete_clinical_first: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """An insured household with one SICK_VISIT encounter already routed to
    insurance, so exactly one ServiceLine sits in status ROUTED.

    Returns the scenario dict plus `encounter` and `service_line`.
    """
    scenario = setup_insured_active_membership(advance_clock_to=advance_clock_to, **kwargs)
    encounter = open_encounter(scenario["membership"]["id"], started_at)
    if complete_clinical_first:
        complete_clinical(encounter["id"], scenario["physician"]["id"])
    submit_billing(encounter["id"], submitter_user_id)
    lines = service_lines_for_encounter(encounter["id"])
    assert len(lines) == 1, f"Setup failed: expected 1 service line, got {len(lines)}"
    scenario["encounter"] = get_success_data(
        api_client.get_encounter(encounter["id"], BILLING)
    )
    scenario["service_line"] = lines[0]
    return scenario


# ==========================================================================
# Entitlement grants and consult bookings
# ==========================================================================


def grants_for(membership_id: str, **filters) -> List[Dict[str, Any]]:
    params = {"membership_id": membership_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_entitlement_grants(COORDINATOR, params=params))


def grant_for(membership_id: str, benefit_type: str) -> Dict[str, Any]:
    rows = grants_for(membership_id, benefit_type=benefit_type)
    assert rows, f"Setup failed: no {benefit_type} grant for membership {membership_id}"
    return rows[0]


def get_grant(grant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_entitlement_grant(grant_id, COORDINATOR))


def book_consult(
    membership_id: str,
    consultant_physician_id: str,
    scheduled_start: str,
    scheduled_end: str,
    consult_type: str = "LACTATION_CONSULT",
    modality: str = "IN_PERSON",
    patient_state_code: str = "CA",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_consult_booking_payload(
        membership_id,
        consultant_physician_id,
        scheduled_start,
        scheduled_end,
        consult_type=consult_type,
        modality=modality,
        patient_state_code=patient_state_code,
    )
    return get_success_data(
        api_client.create_consult_booking(payload, headers or COORDINATOR)
    )


def get_booking(booking_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_consult_booking(booking_id, COORDINATOR))


# ==========================================================================
# Well visits, doses, forms
# ==========================================================================


def well_visits_for(membership_id: str, **filters) -> List[Dict[str, Any]]:
    params = {"membership_id": membership_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_well_visits(COORDINATOR, params=params))


def well_visit_for(membership_id: str, milestone_code: str) -> Dict[str, Any]:
    rows = well_visits_for(membership_id, milestone_code=milestone_code)
    assert rows, f"Setup failed: no {milestone_code} well visit for {membership_id}"
    return rows[0]


def get_well_visit(well_visit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_well_visit(well_visit_id, COORDINATOR))


def complete_well_visit(well_visit_id: str, physician_id: str, completed_date: str):
    return get_success_data(
        api_client.complete_well_visit(
            well_visit_id,
            {"completed_date": completed_date},
            make_physician_headers(physician_id),
        )
    )


def record_dose(child_id: str, vaccine_code: str, administered_date: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_immunization_dose(
            create_immunization_dose_payload(child_id, vaccine_code, administered_date),
            ADMIN,
        )
    )


def get_dose(dose_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_immunization_dose(dose_id, ADMIN))


def doses_for(child_id: str, **filters) -> List[Dict[str, Any]]:
    params = {"child_id": child_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_immunization_doses(ADMIN, params=params))


def request_form(
    membership_id: str,
    form_type: str = "SCHOOL",
    needed_by_date: str = "2026-08-01",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_form_request_payload(
        membership_id, form_type=form_type, needed_by_date=needed_by_date
    )
    return get_success_data(api_client.create_form_request(payload, headers or COORDINATOR))


def get_form_request(form_request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_form_request(form_request_id, COORDINATOR))


# ==========================================================================
# Waitlist and panel reads
# ==========================================================================


def queue_for_panel(physician_id: str, child_id: str, requested_plan_id: str):
    return get_success_data(
        api_client.create_waitlist_entry(
            create_waitlist_entry_payload(physician_id, child_id, requested_plan_id),
            COORDINATOR,
        )
    )


def waitlist_entries(**filters) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_waitlist_entries(COORDINATOR, params=params))


def get_waitlist_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_waitlist_entry(entry_id, COORDINATOR))


def panel_summary(physician_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_physician_panel(physician_id, ADMIN))


def get_physician(physician_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_physician(physician_id, ADMIN))


def get_child(child_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_child(child_id, ADMIN))


def get_family(family_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_family(family_id, ADMIN))


def get_membership(membership_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_membership(membership_id, ADMIN))


def get_policy(policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_insurance_policy(policy_id, BILLING))


def get_encounter(encounter_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_encounter(encounter_id, BILLING))


def memberships_where(**filters) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_memberships(ADMIN, params=params))


def consult_bookings_where(**filters) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_consult_bookings(COORDINATOR, params=params))


def encounters_where(**filters) -> List[Dict[str, Any]]:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_encounters(COORDINATOR, params=params))
