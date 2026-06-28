"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the server (empty database) before every test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient validator) internally so setup failures
surface as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: the Technician role is entity_backed; ownership-gated clinical
calls (patch-test read, appointment start/finish/complete, healing logs) thread
make_technician_headers(technician_id) using the real Technician.id. StudioAdmin,
FrontDesk, and ComplianceOfficer are opaque and use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_studio_payload,
    create_technician_payload,
    create_color_formula_payload,
    create_client_payload,
    create_consent_payload,
    create_patch_test_payload,
    read_patch_test_payload,
    create_appointment_payload,
    deposit_payload,
    pay_balance_payload,
    create_healing_log_payload,
)
from .test_users import TEST_USERS, make_technician_headers


ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock (StudioAdmin only)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


# ─── Tier 1/2: Studio building blocks ────────────────────────────────────────
def create_studio(**overrides):
    """Create a studio. Returns the studio dict."""
    return get_success_data(api_client.create_studio(create_studio_payload(**overrides), ADMIN))


def create_technician(studio_id, **overrides):
    """Register a technician on a studio (begins LICENSE_ACTIVE)."""
    return get_success_data(
        api_client.create_technician(create_technician_payload(studio_id, **overrides), ADMIN)
    )


def create_color_formula(studio_id, **overrides):
    """Create a color formula (StudioAdmin)."""
    return get_success_data(
        api_client.create_color_formula(create_color_formula_payload(studio_id, **overrides), ADMIN)
    )


def create_client(studio_id, **overrides):
    """Register a client (FrontDesk)."""
    return get_success_data(
        api_client.create_client(create_client_payload(studio_id, **overrides), FRONT)
    )


def create_consent(client_id, **overrides):
    """Record a consent (FrontDesk)."""
    return get_success_data(
        api_client.create_consent_record(create_consent_payload(client_id, **overrides), FRONT)
    )


def apply_patch_test(client_id):
    """Apply a patch test (Technician). Returns the APPLIED patch test."""
    return get_success_data(
        api_client.create_patch_test(create_patch_test_payload(client_id), TEST_USERS["technician_headers"])
    )


def read_patch_test(patch_test_id, technician_id, reaction_grade=1):
    """Read a patch test result (Technician, ownership-gated identity threaded)."""
    return get_success_data(
        api_client.read_patch_test(
            patch_test_id,
            read_patch_test_payload(reaction_grade=reaction_grade),
            make_technician_headers(technician_id),
        )
    )


# ─── Tier 2: Booking-ready scenario ──────────────────────────────────────────
def setup_booking_ready(
    *,
    sterile_kit_total=10,
    pigment_count=2,
    procedure_type="BROWS",
    formula_procedure_type=None,
    state_code="CA",
    min_client_age=None,
    client_overrides=None,
    technician_overrides=None,
    consent=True,
    patch_reaction_grade=1,
    apply_clock="2026-01-01T00:00:00Z",
    read_clock="2026-01-03T01:00:00Z",
):
    """Full pre-booking setup: clock at 2026-01-01, studio, LICENSE_ACTIVE
    technician, color formula, client, optional PROCEDURE_CONSENT, and a patch
    test that is READ (clock advanced to read_clock) with the given reaction
    grade (default grade 1 -> PASS).

    Returns dict with keys: studio, technician, formula, client, patch_test.
    """
    set_clock(apply_clock)
    studio_kwargs = {"state_code": state_code, "sterile_kit_total": sterile_kit_total}
    if min_client_age is not None:
        studio_kwargs["min_client_age"] = min_client_age
    studio = create_studio(**studio_kwargs)

    technician = create_technician(studio["id"], **(technician_overrides or {}))
    formula = create_color_formula(
        studio["id"],
        procedure_type=formula_procedure_type or procedure_type,
        pigment_count=pigment_count,
    )
    client = create_client(studio["id"], **(client_overrides or {}))
    if consent:
        create_consent(client["id"])

    patch_test = apply_patch_test(client["id"])
    set_clock(read_clock)
    read_patch_test(patch_test["id"], technician["id"], reaction_grade=patch_reaction_grade)

    return {
        "studio": studio,
        "technician": technician,
        "formula": formula,
        "client": client,
        "patch_test": patch_test,
    }


def book_initial_appointment(ctx, *, scheduled_start="2026-01-06T10:00:00Z", **overrides):
    """Book an INITIAL appointment from a setup_booking_ready ctx. Returns the
    BOOKED, AWAITING_DEPOSIT appointment."""
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type=overrides.pop("procedure_type", ctx["formula"]["procedure_type"]),
        scheduled_start=scheduled_start,
        **overrides,
    )
    return get_success_data(api_client.create_appointment(payload, FRONT))


def pay_deposit(appointment):
    """Pay the exact required deposit on a BOOKED appointment. Returns updated."""
    return get_success_data(
        api_client.deposit(
            appointment["id"],
            deposit_payload(appointment["deposit_required_cents"]),
            FRONT,
        )
    )


def setup_deposited_appointment(ctx=None, *, scheduled_start="2026-01-06T10:00:00Z", **ctx_overrides):
    """Booking-ready ctx + a BOOKED appointment with deposit paid (DEPOSIT_PAID).
    Returns (ctx, appointment)."""
    if ctx is None:
        ctx = setup_booking_ready(**ctx_overrides)
    appt = book_initial_appointment(ctx, scheduled_start=scheduled_start)
    appt = pay_deposit(appt)
    return ctx, appt


def setup_started_appointment(ctx=None, *, scheduled_start="2026-01-06T10:00:00Z", **ctx_overrides):
    """Deposited appointment advanced through /start (IN_PROCEDURE, kit consumed).
    Returns (ctx, appointment)."""
    ctx, appt = setup_deposited_appointment(ctx, scheduled_start=scheduled_start, **ctx_overrides)
    appt = get_success_data(
        api_client.start_appointment(appt["id"], make_technician_headers(ctx["technician"]["id"]))
    )
    return ctx, appt


def setup_completed_appointment(
    ctx=None,
    *,
    scheduled_start="2026-01-06T10:00:00Z",
    healing_outcome_flag="GOOD",
    complete_clock="2026-02-01T00:00:00Z",
    healing_day_offset=14,
    **ctx_overrides,
):
    """Full lifecycle to COMPLETED:
    book -> deposit -> start -> finish-procedure -> pay-balance -> healing log ->
    (advance clock to complete_clock) -> complete.

    healing_outcome_flag controls the recorded HealingLog (GOOD or POOR), which
    determines the completed appointment's healing_outcome. Returns (ctx, appointment).
    """
    ctx, appt = setup_started_appointment(ctx, scheduled_start=scheduled_start, **ctx_overrides)
    tech_headers = make_technician_headers(ctx["technician"]["id"])

    appt = get_success_data(api_client.finish_procedure(appt["id"], tech_headers))
    appt = get_success_data(
        api_client.pay_balance(appt["id"], pay_balance_payload(appt["balance_due_cents"]), FRONT)
    )
    get_success_data(
        api_client.create_healing_log(
            create_healing_log_payload(
                appt["id"], day_offset=healing_day_offset, outcome_flag=healing_outcome_flag
            ),
            tech_headers,
        )
    )
    set_clock(complete_clock)
    appt = get_success_data(api_client.complete_appointment(appt["id"], tech_headers))
    return ctx, appt
