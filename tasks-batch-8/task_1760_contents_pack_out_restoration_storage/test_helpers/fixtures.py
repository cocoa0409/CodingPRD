"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() so a failed setup step raises a clear
"Setup step failed" error instead of a confusing assertion failure deep in a
test. OCC-guarded calls always capture the entity version fresh via a GET
immediately before the guarded write, because rollups and cascades may have
bumped the version since the entity was created.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_pack_out_job_payload, create_room_payload, create_item_payload,
    create_vault_payload, create_subcontractor_payload,
    create_specialty_referral_payload, create_custody_event_payload,
    create_handling_claim_payload, create_pack_back_schedule_payload,
    create_storage_statement_payload, triage_payload, clock_payload,
)
from .test_users import TEST_USERS, make_subcontractor_contact_headers

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
CARRIER = TEST_USERS["carrier_representative_headers"]


# --- Tier 1/2: job tree primitives -------------------------------------------

def create_job(**overrides) -> dict:
    """Create a pack-out job. Returns the created job (INTAKE/PENDING)."""
    return get_success_data(
        api_client.create_pack_out_job(create_pack_out_job_payload(**overrides), PM)
    )


def create_room(job_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_room(job_id, create_room_payload(**overrides), PM)
    )


def register_item(room_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_item(room_id, create_item_payload(**overrides), TECH)
    )


def setup_job_with_room(job_overrides=None, room_overrides=None):
    """Job + one room. Returns (job, room)."""
    job = create_job(**(job_overrides or {}))
    room = create_room(job["id"], **(room_overrides or {}))
    return job, room


def get_job(job_id: str) -> dict:
    return get_success_data(api_client.get_pack_out_job(job_id, CLERK))


def get_job_version(job_id: str) -> int:
    """Fresh job version for OCC-guarded statement creation."""
    return get_job(job_id)["version"]


def get_item(item_id: str) -> dict:
    return get_success_data(api_client.get_item(item_id, TECH))


def get_item_version(item_id: str) -> int:
    return get_item(item_id)["version"]


# --- Triage / cleaning ---------------------------------------------------------

def triage_item(item_id: str, expected_version: int, determination: str = "SALVAGEABLE") -> dict:
    return get_success_data(
        api_client.triage_item(item_id, triage_payload(expected_version, determination), TECH)
    )


def create_cleaning_task(item_id: str) -> dict:
    return get_success_data(api_client.create_cleaning_task(item_id, {}, TECH))


def transition_cleaning_task(task_id: str, action: str, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_cleaning_task(task_id, payload, TECH))


def drive_item_to_cleaned(room_id: str, item_overrides=None):
    """Register -> triage SALVAGEABLE -> task -> START -> QA_PASS.

    Returns (item, task) with the item in CLEANED and the task PASSED.
    """
    item = register_item(room_id, **(item_overrides or {}))
    triage_item(item["id"], item["version"], "SALVAGEABLE")
    task = create_cleaning_task(item["id"])
    transition_cleaning_task(task["id"], "START")
    task = transition_cleaning_task(task["id"], "QA_PASS")
    return get_item(item["id"]), task


def setup_cleaned_item(job_overrides=None, room_overrides=None, item_overrides=None):
    """Job + room + one CLEANED item. Returns (job, room, item, task)."""
    job, room = setup_job_with_room(job_overrides, room_overrides)
    item, task = drive_item_to_cleaned(room["id"], item_overrides)
    return job, room, item, task


# --- Vault / placement -----------------------------------------------------------

def create_vault(**overrides) -> dict:
    return get_success_data(api_client.create_vault(create_vault_payload(**overrides), PM))


def get_vault(vault_id: str) -> dict:
    return get_success_data(api_client.get_vault(vault_id, TECH))


def place_item(item_id: str, vault_id: str) -> dict:
    """Activate a placement (expects success). Returns the ACTIVE placement."""
    return get_success_data(
        api_client.create_placement(item_id, {"vault_id": vault_id}, TECH)
    )


def release_placement(placement_id: str) -> dict:
    return get_success_data(api_client.release_placement(placement_id, TECH))


def setup_item_in_storage(job_overrides=None, room_overrides=None,
                          item_overrides=None, vault_overrides=None,
                          placed_clock_iso: str = None):
    """Job + room + CLEANED item + vault + ACTIVE placement.

    Returns dict(job, room, item, task, vault, placement) with the item
    IN_STORAGE. If placed_clock_iso is given, the logical clock is set to that
    instant before activation (controls placed_on).
    """
    job, room, item, task = setup_cleaned_item(job_overrides, room_overrides, item_overrides)
    vault = create_vault(**(vault_overrides or {}))
    if placed_clock_iso is not None:
        set_clock(placed_clock_iso)
    placement = place_item(item["id"], vault["id"])
    return {
        "job": job, "room": room, "item": get_item(item["id"]),
        "task": task, "vault": vault, "placement": placement,
    }


# --- Logical clock / statements / billing run ------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), CLERK))


def create_statement(job_id: str, period_start: str = None, period_end: str = None,
                     supersedes_statement_id: str = None) -> dict:
    """Create a PROVISIONAL statement with a freshly captured job version (OCC)."""
    payload = create_storage_statement_payload(
        get_job_version(job_id),
        period_start=period_start or TEST_DEFAULTS["PERIOD_START"],
        period_end=period_end or TEST_DEFAULTS["PERIOD_END"],
    )
    if supersedes_statement_id is not None:
        payload["supersedes_statement_id"] = supersedes_statement_id
    return get_success_data(api_client.create_storage_statement(job_id, payload, CLERK))


def get_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_storage_statement(statement_id, CLERK))


def run_billing() -> dict:
    """Execute a billing run; returns {finalized_count, finalized_statement_ids}."""
    return get_success_data(api_client.run_billing(CLERK))


def setup_finalized_statement_job(job_overrides=None, period_start=None, period_end=None,
                                  finalize_clock_iso: str = None):
    """Job + one PROVISIONAL statement, then clock advanced and billing run so
    the statement is FINALIZED (no placements -> final_total_cents 0).

    Returns (job, statement).
    """
    job = create_job(**(job_overrides or {}))
    stmt = create_statement(job["id"], period_start, period_end)
    set_clock(finalize_clock_iso or TEST_DEFAULTS["FINALIZE_CLOCK_ISO"])
    run_billing()
    return job, get_statement(stmt["id"])


def setup_finalized_storage_scenario(job_overrides=None, item_overrides=None,
                                     vault_overrides=None,
                                     placed_clock_iso="2026-08-10T09:00:00Z",
                                     statement_clock_iso="2026-08-15T09:00:00Z",
                                     released_clock_iso="2026-08-31T10:00:00Z",
                                     period_start="2026-08-01",
                                     period_end="2026-09-01",
                                     finalize_clock_iso="2026-09-01T00:00:00Z"):
    """Item placed, statement created while ACTIVE, placement released, then a
    billing run at/after period_end finalizes the statement.

    With the default timeline (vol 40 @ 150 cents/cu ft -> monthly 6000, placed
    2026-08-10, released 2026-08-31) the statement carries provisional 6000 and
    final 4137 (daily 197 x 21 occupied days).
    Returns the setup dict with an added FINALIZED "statement".
    """
    ctx = setup_item_in_storage(
        job_overrides=job_overrides,
        room_overrides={"name": "Lounge", "room_type": "LIVING"},
        item_overrides=item_overrides,
        vault_overrides=vault_overrides,
        placed_clock_iso=placed_clock_iso)
    set_clock(statement_clock_iso)
    stmt = create_statement(ctx["job"]["id"], period_start, period_end)
    set_clock(released_clock_iso)
    release_placement(ctx["placement"]["id"])
    set_clock(finalize_clock_iso)
    run_billing()
    ctx["statement"] = get_statement(stmt["id"])
    assert ctx["statement"]["status"] == "FINALIZED", (
        f"Setup failed: statement not FINALIZED, got {ctx['statement']['status']}")
    return ctx


# --- Carrier invoices --------------------------------------------------------------

def create_invoice(job_id: str, adjustment_cents: int = None) -> dict:
    payload = {}
    if adjustment_cents is not None:
        payload["adjustment_cents"] = adjustment_cents
    return get_success_data(api_client.create_carrier_invoice(job_id, payload, CLERK))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_carrier_invoice(invoice_id, CLERK))


def transition_invoice(invoice_id: str, action: str, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return api_client.transition_carrier_invoice(invoice_id, payload, headers or CLERK)


def setup_draft_invoice(adjustment_cents: int = 1000, job_overrides=None):
    """Job with a FINALIZED (empty, final 0) statement swept into a DRAFT invoice.

    Returns (job, invoice). With adjustment 1000: fee 50 (5% tier), total 1050.
    """
    job, _stmt = setup_finalized_statement_job(job_overrides=job_overrides)
    invoice = create_invoice(job["id"], adjustment_cents=adjustment_cents)
    return job, invoice


def setup_submitted_invoice(adjustment_cents: int = 1000, job_overrides=None):
    """DRAFT invoice then SUBMIT. Returns (job, invoice) with invoice SUBMITTED."""
    job, invoice = setup_draft_invoice(adjustment_cents=adjustment_cents, job_overrides=job_overrides)
    invoice = get_success_data(transition_invoice(invoice["id"], "SUBMIT"))
    return job, invoice


# --- Handling claims -----------------------------------------------------------------

def file_claim(item_id: str, filer_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_handling_claim(
            item_id, create_handling_claim_payload(**overrides),
            filer_headers or TEST_USERS["pm1_headers"],
        )
    )


def transition_claim(claim_id: str, action: str, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return api_client.transition_handling_claim(claim_id, payload, headers or TEST_USERS["adj1_headers"])


def submit_claim_for_review(claim_id: str, headers=None) -> dict:
    return get_success_data(transition_claim(claim_id, "SUBMIT_REVIEW", headers=headers))


def approve_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(transition_claim(claim_id, "APPROVE", headers=headers))


def setup_approved_claim(item_overrides=None, claim_overrides=None,
                         job_overrides=None, filer_headers=None, approver_headers=None):
    """Job + room + item + claim filed by one operator and approved by another
    (SoD-distinct). Returns dict(job, room, item, claim) with claim APPROVED.
    """
    job, room = setup_job_with_room(job_overrides)
    item = register_item(room["id"], **(item_overrides or {}))
    claim = file_claim(item["id"], filer_headers=filer_headers, **(claim_overrides or {}))
    submit_claim_for_review(claim["id"], headers=approver_headers)
    claim = approve_claim(claim["id"], headers=approver_headers)
    return {"job": job, "room": room, "item": item, "claim": claim}


# --- Structure / pack-back -------------------------------------------------------------

def drive_structure_complete(job_id: str):
    """PENDING -> IN_PROGRESS -> COMPLETE."""
    get_success_data(api_client.transition_pack_out_job(job_id, {"action": "STRUCTURE_START"}, PM))
    get_success_data(api_client.transition_pack_out_job(job_id, {"action": "STRUCTURE_COMPLETE"}, PM))


def create_schedule(job_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pack_back_schedule(job_id, create_pack_back_schedule_payload(**overrides), PM)
    )


def get_schedule(job_id: str, schedule_id: str) -> dict:
    schedules = get_success_data(api_client.list_pack_back_schedules(job_id, PM))
    for s in schedules:
        if s["id"] == schedule_id:
            return s
    raise AssertionError(f"Setup failed: schedule {schedule_id} not found in job list")


def transition_schedule(schedule_id: str, action: str, **extra):
    payload = {"action": action}
    payload.update(extra)
    return api_client.transition_pack_back_schedule(schedule_id, payload, PM)


def setup_packback_ready(item_overrides=None, vault_overrides=None, schedule_overrides=None):
    """Structure COMPLETE job + one IN_STORAGE eligible item + one REQUESTED
    schedule. Returns dict(job, room, item, vault, placement, schedule).
    """
    ctx = setup_item_in_storage(item_overrides=item_overrides, vault_overrides=vault_overrides)
    drive_structure_complete(ctx["job"]["id"])
    schedule = create_schedule(ctx["job"]["id"], **(schedule_overrides or {}))
    ctx["schedule"] = schedule
    return ctx


# --- Subcontractors / referrals / custody -------------------------------------------------

def create_subcontractor(**overrides) -> dict:
    return get_success_data(
        api_client.create_subcontractor(create_subcontractor_payload(**overrides), PM)
    )


def get_subcontractor(sub_id: str) -> dict:
    return get_success_data(api_client.get_subcontractor(sub_id, PM))


def create_referral(item_id: str, subcontractor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_specialty_referral(
            item_id, create_specialty_referral_payload(subcontractor_id, **overrides), PM)
    )


def get_referral(referral_id: str) -> dict:
    return get_success_data(
        api_client.get_specialty_referral(referral_id, PM)
    )


def transition_referral(referral_id: str, action: str, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return api_client.transition_specialty_referral(referral_id, payload, headers or PM)


def dispatch_referral(referral_id: str) -> dict:
    return get_success_data(transition_referral(referral_id, "DISPATCH"))


def receive_referral(referral_id: str, subcontractor_id: str) -> dict:
    return get_success_data(transition_referral(
        referral_id, "RECEIVE", headers=make_subcontractor_contact_headers(subcontractor_id)))


def return_referral(referral_id: str, subcontractor_id: str) -> dict:
    return get_success_data(transition_referral(
        referral_id, "RETURN", headers=make_subcontractor_contact_headers(subcontractor_id)))


def setup_dispatched_referral(item_overrides=None, sub_overrides=None, referral_overrides=None):
    """Subcontractor + job/room/item triaged SALVAGEABLE + referral DISPATCHED.

    Returns dict(sub, job, room, item, referral).
    """
    sub = create_subcontractor(**(sub_overrides or {}))
    job, room = setup_job_with_room()
    item = register_item(room["id"], **(item_overrides or {}))
    triage_item(item["id"], item["version"], "SALVAGEABLE")
    referral = create_referral(item["id"], sub["id"], **(referral_overrides or {}))
    referral = dispatch_referral(referral["id"])
    return {"sub": sub, "job": job, "room": room,
            "item": get_item(item["id"]), "referral": referral}


def append_custody_event(referral_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_custody_event(
            referral_id, create_custody_event_payload(**overrides), headers or TECH)
    )


# --- Disposal pipeline -----------------------------------------------------------------------

def get_disposal_record_for_item(item_id: str):
    """Returns the item's disposal record list (0 or 1 entries)."""
    return get_success_data(api_client.get_disposal_record(item_id, TECH))


def setup_documented_disposal(item_overrides=None, documenter_headers=None,
                              document_overrides=None):
    """Item triaged NON_SALVAGEABLE with its disposal record DOCUMENTED.

    Returns dict(job, room, item, record) with record DOCUMENTED.
    """
    job, room = setup_job_with_room()
    item = register_item(room["id"], **(item_overrides or {}))
    triage_item(item["id"], item["version"], "NON_SALVAGEABLE")
    records = get_disposal_record_for_item(item["id"])
    assert len(records) == 1, "Setup failed: expected one auto-created DRAFT disposal record"
    record = records[0]
    payload = {"action": "DOCUMENT", "disposal_method": "LANDFILL",
               "facility_name": "City Landfill"}
    payload.update(document_overrides or {})
    record = get_success_data(api_client.transition_disposal_record(
        record["id"], payload, documenter_headers or TEST_USERS["tech1_headers"]))
    return {"job": job, "room": room, "item": get_item(item["id"]), "record": record}


def setup_disposed_item(item_overrides=None):
    """Full disposal pipeline: item reaches terminal DISPOSED.

    Returns dict(job, room, item, record) with record VERIFIED.
    Documenter and verifier are distinct operators (segregation of duties).
    """
    ctx = setup_documented_disposal(item_overrides=item_overrides)
    record = get_success_data(api_client.transition_disposal_record(
        ctx["record"]["id"], {"action": "VERIFY"}, TEST_USERS["pm9_headers"]))
    ctx["record"] = record
    ctx["item"] = get_item(ctx["item"]["id"])
    return ctx
