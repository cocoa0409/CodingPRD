"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Fixtures use the lenient
get_success_data() validator internally so setup failures surface as clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_facilitator_headers,
    make_learner_headers,
)

DESIGNER = TEST_USERS["program_designer_headers"]
COORD = TEST_USERS["scheduling_coordinator_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


# ---------------------------------------------------------------------------
# Clock helpers (PRD §2.4 — logical clock; default 2026-03-01T00:00:00Z)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


# ---------------------------------------------------------------------------
# Tier 1 — building blocks: program, version (DRAFT/IN_REVIEW/APPROVED), facilitator
# ---------------------------------------------------------------------------
def create_program(category="TECHNICAL", delivery_mode="VIRTUAL", **overrides):
    payload = {"title": "Test Program", "category": category, "delivery_mode": delivery_mode}
    payload.update(overrides)
    return get_success_data(api_client.create_program(payload, DESIGNER))


def create_draft_version(program_id, pricing_model="PER_SEAT", **overrides):
    payload = {
        "program_id": program_id,
        "version_label": "v1",
        "duration_hours": 4,
        "pricing_model": pricing_model,
        "min_seats": 1,
    }
    if pricing_model == "PER_SEAT":
        payload["per_seat_cents"] = 50000
    else:
        payload["flat_fee_cents"] = 200000
    payload.update(overrides)
    return get_success_data(api_client.create_program_version(payload, DESIGNER))


def create_approved_version(category="TECHNICAL", delivery_mode="VIRTUAL",
                            pricing_model="PER_SEAT", program_overrides=None,
                            version_overrides=None):
    """Create program + version, submit, approve. Returns (program, version)."""
    program = create_program(category=category, delivery_mode=delivery_mode,
                             **(program_overrides or {}))
    version = create_draft_version(program["id"], pricing_model=pricing_model,
                                   **(version_overrides or {}))
    get_success_data(api_client.submit_program_version(version["id"], DESIGNER))
    get_success_data(api_client.approve_program_version(version["id"], DESIGNER))
    return program, version


def create_facilitator(certified_categories=None, travel_base_cents=0, email="fac@example.com",
                       full_name="Test Facilitator", **overrides):
    payload = {
        "full_name": full_name,
        "email": email,
        "certified_categories": certified_categories or ["TECHNICAL"],
        "travel_base_cents": travel_base_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_facilitator(payload, COORD))


def create_contract(budget_cents=500000, client_name="Test Client", **overrides):
    payload = {"client_name": client_name, "budget_cents": budget_cents}
    payload.update(overrides)
    return get_success_data(api_client.create_contract(payload, FINANCE))


# ---------------------------------------------------------------------------
# Tier 2 — scheduled / open cohort setup
# ---------------------------------------------------------------------------
def create_scheduled_cohort(version_id, facilitator_id, delivery_mode="VIRTUAL",
                            contract_id=None, seat_capacity=5, waitlist_capacity=0,
                            starts_at="2026-04-01T09:00:00Z", ends_at="2026-04-01T17:00:00Z",
                            enroll_deadline="2026-03-31T00:00:00Z"):
    payload = {
        "program_version_id": version_id,
        "lead_facilitator_id": facilitator_id,
        "seat_capacity": seat_capacity,
        "waitlist_capacity": waitlist_capacity,
        "delivery_mode": delivery_mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enroll_deadline": enroll_deadline,
    }
    if contract_id is not None:
        payload["contract_id"] = contract_id
    return get_success_data(api_client.create_cohort(payload, COORD))


def setup_open_cohort(category="TECHNICAL", delivery_mode="VIRTUAL", pricing_model="PER_SEAT",
                      seat_capacity=5, waitlist_capacity=0, contract_id=None,
                      travel_base_cents=0, version_overrides=None, cohort_overrides=None,
                      facilitator_email="fac@example.com"):
    """Approved version + facilitator + scheduled cohort, then opened.
    Returns dict with program, version, facilitator, cohort (refetched, OPEN)."""
    program, version = create_approved_version(
        category=category, delivery_mode=delivery_mode, pricing_model=pricing_model,
        version_overrides=version_overrides,
    )
    fac = create_facilitator(certified_categories=[category], travel_base_cents=travel_base_cents,
                             email=facilitator_email)
    co = cohort_overrides or {}
    cohort = create_scheduled_cohort(
        version["id"], fac["id"], delivery_mode=delivery_mode, contract_id=contract_id,
        seat_capacity=seat_capacity, waitlist_capacity=waitlist_capacity, **co,
    )
    get_success_data(api_client.open_cohort(cohort["id"], COORD))
    cohort = get_success_data(api_client.get_cohort(cohort["id"], COORD))
    return {
        "program": program,
        "version": version,
        "facilitator": fac,
        "cohort": cohort,
    }


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------
def register_learner(cohort_id, email, name=None):
    payload = {"learner_email": email, "learner_name": name or email}
    return get_success_data(api_client.create_registration(cohort_id, payload, COORD))


def confirm_learner(reg_id, email):
    return get_success_data(api_client.confirm_registration(reg_id, make_learner_headers(email)))


def register_and_confirm(cohort_id, email, name=None):
    reg = register_learner(cohort_id, email, name)
    confirm_learner(reg["id"], email)
    return reg


def current_cohort_version(cohort_id):
    return get_success_data(api_client.get_cohort(cohort_id, COORD))["version"]


def lock_cohort(cohort_id):
    """Lock with a freshly-read version so OCC always matches."""
    v = current_cohort_version(cohort_id)
    return get_success_data(api_client.lock_cohort(cohort_id, v, COORD))


# ---------------------------------------------------------------------------
# Tier 3/4 — full-lifecycle shortcuts producing diverging provisional/final money
# ---------------------------------------------------------------------------
def setup_locked_cohort_with_confirmed(num_confirmed, category="TECHNICAL",
                                       delivery_mode="ONSITE", pricing_model="PER_SEAT",
                                       contract_id=None, per_seat_cents=50000,
                                       materials_kit_cents=2500, flat_fee_cents=200000,
                                       travel_base_cents=10000, min_seats=1, seat_capacity=None,
                                       pass_threshold_pct=70):
    """Open a cohort, enroll+confirm `num_confirmed` learners, then lock (emits PROVISIONAL).
    Returns dict with program, version, facilitator, cohort (LOCKED), registrations (list)."""
    vo = {
        "min_seats": min_seats,
        "materials_kit_cents": materials_kit_cents,
        "pass_threshold_pct": pass_threshold_pct,
    }
    if pricing_model == "PER_SEAT":
        vo["per_seat_cents"] = per_seat_cents
    else:
        vo["flat_fee_cents"] = flat_fee_cents
    ctx = setup_open_cohort(
        category=category, delivery_mode=delivery_mode, pricing_model=pricing_model,
        seat_capacity=seat_capacity or max(num_confirmed, 1) + 2, contract_id=contract_id,
        travel_base_cents=travel_base_cents, version_overrides=vo,
    )
    regs = []
    for i in range(num_confirmed):
        email = f"learner{i}@example.com"
        regs.append(register_and_confirm(ctx["cohort"]["id"], email, f"Learner {i}"))
    lock_cohort(ctx["cohort"]["id"])
    ctx["cohort"] = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
    ctx["registrations"] = regs
    return ctx


def setup_delivered_cohort_with_attendance(num_confirmed, num_attended,
                                           starts_at="2026-04-01T09:00:00Z",
                                           ends_at="2026-04-01T17:00:00Z",
                                           enroll_deadline="2026-03-31T00:00:00Z",
                                           **lock_kwargs):
    """Lock a cohort with num_confirmed seats, start at starts_at, mark `num_attended` attended,
    deliver at ends_at (remaining confirmed -> NO_SHOW). Returns the LOCKED-then-DELIVERED ctx."""
    ctx = setup_locked_cohort_with_confirmed(
        num_confirmed,
        seat_capacity=lock_kwargs.pop("seat_capacity", num_confirmed + 2),
        **lock_kwargs,
    )
    coh_id = ctx["cohort"]["id"]
    fac_headers = make_facilitator_headers(ctx["facilitator"]["id"])
    set_clock(starts_at)
    get_success_data(api_client.start_cohort(coh_id, COORD))
    for reg in ctx["registrations"][:num_attended]:
        get_success_data(api_client.mark_attendance(reg["id"], fac_headers))
    set_clock(ends_at)
    get_success_data(api_client.deliver_cohort(coh_id, COORD))
    ctx["cohort"] = get_success_data(api_client.get_cohort(coh_id, COORD))
    return ctx


def get_cohort_invoices(cohort_id):
    return get_success_data(api_client.list_cohort_invoices(cohort_id, FINANCE))


def invoice_by_variant(cohort_id, variant):
    invoices = get_cohort_invoices(cohort_id)
    matches = [inv for inv in invoices if inv.get("variant") == variant]
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Tier 5 — running-cohort setup for assessment / certificate tests
# ---------------------------------------------------------------------------
def setup_running_cohort_one_attendee(category="TECHNICAL", delivery_mode="ONSITE",
                                      pass_threshold_pct=70, ceu_credits=0,
                                      starts_at="2026-06-04T09:00:00Z",
                                      ends_at="2026-06-04T13:00:00Z",
                                      enroll_deadline="2026-06-03T00:00:00Z"):
    """Open->confirm->lock->start a cohort, mark one learner attended.
    Cohort is RUNNING with one ATTENDED-eligible registration. Returns ctx with the registration
    (key 'registration') and facilitator headers (key 'fac_headers')."""
    program, version = create_approved_version(
        category=category, delivery_mode=delivery_mode, pricing_model="PER_SEAT",
        program_overrides={"ceu_credits": ceu_credits},
        version_overrides={"per_seat_cents": 10000, "min_seats": 1,
                           "pass_threshold_pct": pass_threshold_pct},
    )
    fac = create_facilitator(certified_categories=[category], email="facrun@example.com")
    cohort = create_scheduled_cohort(
        version["id"], fac["id"], delivery_mode=delivery_mode, seat_capacity=2,
        starts_at=starts_at, ends_at=ends_at, enroll_deadline=enroll_deadline,
    )
    get_success_data(api_client.open_cohort(cohort["id"], COORD))
    reg = register_and_confirm(cohort["id"], "attendee@example.com", "Attendee")
    lock_cohort(cohort["id"])
    set_clock(starts_at)
    get_success_data(api_client.start_cohort(cohort["id"], COORD))
    fac_headers = make_facilitator_headers(fac["id"])
    get_success_data(api_client.mark_attendance(reg["id"], fac_headers))
    return {
        "program": program,
        "version": version,
        "facilitator": fac,
        "fac_headers": fac_headers,
        "cohort": get_success_data(api_client.get_cohort(cohort["id"], COORD)),
        "registration": reg,
    }


# ---------------------------------------------------------------------------
# Onsite session setup (for room/facilitator overlap tests)
# ---------------------------------------------------------------------------
def setup_onsite_cohort_for_sessions(starts_at="2026-06-07T08:00:00Z",
                                     ends_at="2026-06-07T18:00:00Z",
                                     enroll_deadline="2026-06-06T00:00:00Z",
                                     duration_hours=8, lead_email="leadsess@example.com"):
    """SCHEDULED onsite cohort spanning a wide window so sessions can be placed within it.
    Returns dict with program, version, facilitator (lead), cohort (SCHEDULED)."""
    program, version = create_approved_version(
        category="TECHNICAL", delivery_mode="ONSITE", pricing_model="PER_SEAT",
        version_overrides={"per_seat_cents": 10000, "min_seats": 1,
                           "duration_hours": duration_hours},
    )
    fac = create_facilitator(certified_categories=["TECHNICAL"], email=lead_email,
                             full_name="Lead Fac")
    cohort = create_scheduled_cohort(
        version["id"], fac["id"], delivery_mode="ONSITE", seat_capacity=5,
        starts_at=starts_at, ends_at=ends_at, enroll_deadline=enroll_deadline,
    )
    return {"program": program, "version": version, "facilitator": fac, "cohort": cohort}


def add_session(cohort_id, title, starts_at, ends_at, room_or_url):
    payload = {"title": title, "starts_at": starts_at, "ends_at": ends_at,
               "room_or_url": room_or_url}
    return get_success_data(api_client.create_session(cohort_id, payload, COORD))
