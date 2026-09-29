"""Scenario builders.

The server is restarted before every test, so every test starts against an
empty database and each builder below constructs its state from scratch through
the documented endpoints.  Nothing is inserted behind the API's back.

Each builder takes the client as its first argument and returns the created
resource, or a context dictionary when it assembles several rows at once.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    SPEC_AUTHOR_ID,
    SPEC_RELEASER_ID,
    THIRD_PARTY_TESTER_ID,
    make_body_engineer_headers,
    make_customer_committee_rep_headers,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    make_third_party_tester_headers,
)


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(api, current_utc, headers=None):
    """Move the logical plant clock.  Moving it never transitions anything."""
    headers = headers or make_program_admin_headers()
    return get_success_data(api.set_clock(current_utc, headers))


# ─── Apparatus programs ───────────────────────────────────────────────────

def create_program(api, **overrides):
    """Open a program; it lands in DRAFT with committed_cents at 0."""
    headers = make_program_admin_headers()
    return get_success_data(
        api.create_program(f.build_program_payload(**overrides), headers), 201
    )


def create_active_program(api, **overrides):
    """Open a program and activate it, so unit orders may be awarded."""
    admin = make_program_admin_headers()
    program = create_program(api, **overrides)
    return get_success_data(api.activate_program(program["id"], admin))


def read_program(api, program_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_program(program_id, headers))


# ─── Bid specifications ───────────────────────────────────────────────────

def create_draft_specification(api, program_id, author=SPEC_AUTHOR_ID, **overrides):
    headers = make_purchasing_officer_headers(author)
    return get_success_data(
        api.create_specification(
            f.build_specification_payload(program_id, **overrides), headers
        ),
        201,
    )


def add_clause(api, specification_id, author=SPEC_AUTHOR_ID, **overrides):
    headers = make_purchasing_officer_headers(author)
    return get_success_data(
        api.add_clause(specification_id, f.build_clause_payload(**overrides), headers),
        201,
    )


def file_compliance_entry(api, specification_id, clause_id, engineer="eng-1",
                          **overrides):
    headers = make_body_engineer_headers(engineer)
    return get_success_data(
        api.create_compliance_entry(
            f.build_compliance_entry_payload(specification_id, clause_id, **overrides),
            headers,
        ),
        201,
    )


def dispose_entry(api, compliance_entry_id, disposition="ACCEPTED",
                  officer=SPEC_AUTHOR_ID, **overrides):
    headers = make_purchasing_officer_headers(officer)
    payload = f.build_disposition_payload(disposition=disposition, **overrides)
    return get_success_data(
        api.dispose_compliance_entry(compliance_entry_id, payload, headers)
    )


def submit_specification_for_review(api, specification_id, officer=SPEC_AUTHOR_ID):
    headers = make_purchasing_officer_headers(officer)
    return get_success_data(
        api.submit_specification_for_review(specification_id, headers)
    )


def release_specification(api, specification_id, releaser=SPEC_RELEASER_ID):
    """Release must be signed by someone other than the specification's author."""
    headers = make_purchasing_officer_headers(releaser)
    return get_success_data(api.release_specification(specification_id, headers))


DEFAULT_CLAUSES = [
    {
        "clause_code": "C1",
        "category": "PUMP",
        "requirement_text": "1500 gpm single stage pump",
        "mandatory": True,
        "is_restrictive": False,
    },
]


def create_released_specification(api, program_id, clauses=None,
                                  author=SPEC_AUTHOR_ID, releaser=SPEC_RELEASER_ID,
                                  respond=True, **spec_overrides):
    """Draft, answer, review and release one specification.

    The default clause book is a single mandatory non-restrictive clause
    answered ``COMPLY``, which puts ``compliance_score_strict`` at 100.00 and
    ``restrictive_clause_ratio_pct`` at 0.00 — comfortably inside the release
    gates of at least 75.00 and at most 40.00.
    """
    clauses = DEFAULT_CLAUSES if clauses is None else clauses
    spec = create_draft_specification(api, program_id, author=author, **spec_overrides)
    clause_ids = []
    for clause in clauses:
        created = add_clause(api, spec["id"], author=author, **clause)
        clause_ids.append(created["id"])
    entry_ids = []
    if respond:
        for clause_id in clause_ids:
            entry_ids.append(
                file_compliance_entry(api, spec["id"], clause_id)["id"]
            )
    submit_specification_for_review(api, spec["id"], officer=author)
    released = release_specification(api, spec["id"], releaser=releaser)
    return {
        "specification": released,
        "specification_id": released["id"],
        "clause_ids": clause_ids,
        "entry_ids": entry_ids,
    }


def setup_program_with_released_spec(api, program_overrides=None, clauses=None):
    """An ACTIVE program carrying one RELEASED specification."""
    program = create_active_program(api, **(program_overrides or {}))
    spec = create_released_specification(api, program["id"], clauses=clauses)
    return {
        "program": program,
        "program_id": program["id"],
        "specification": spec["specification"],
        "specification_id": spec["specification_id"],
        "clause_ids": spec["clause_ids"],
        "entry_ids": spec["entry_ids"],
    }


# ─── Unit orders ──────────────────────────────────────────────────────────

def award_unit(api, program_id, specification_id, officer=SPEC_RELEASER_ID,
               **overrides):
    """Award one unit; it lands SPEC_LOCKED / NOT_SUBMITTED / NOT_RESERVED."""
    headers = make_purchasing_officer_headers(officer)
    payload = f.build_unit_order_payload(program_id, specification_id, **overrides)
    return get_success_data(api.create_unit_order(payload, headers), 201)


def read_unit(api, unit_order_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_unit_order(unit_order_id, headers))


def fresh_unit_version(api, unit_order_id, headers=None):
    """Re-read the unit so a change-order writer echoes the current version."""
    return read_unit(api, unit_order_id, headers)["version"]


def setup_awarded_unit(api, program_overrides=None, clauses=None, **unit_overrides):
    """An ACTIVE program, a RELEASED specification and one SPEC_LOCKED unit."""
    ctx = setup_program_with_released_spec(
        api, program_overrides=program_overrides, clauses=clauses
    )
    unit = award_unit(api, ctx["program_id"], ctx["specification_id"], **unit_overrides)
    ctx["unit"] = unit
    ctx["unit_id"] = unit["id"]
    return ctx


# ─── Plant bays and inspection trips ──────────────────────────────────────

def create_plant_bay(api, **overrides):
    headers = make_program_admin_headers()
    return get_success_data(
        api.create_plant_bay(f.build_plant_bay_payload(**overrides), headers), 201
    )


def schedule_trip(api, unit_order_id, plant_bay_id, **overrides):
    headers = make_program_admin_headers()
    payload = f.build_inspection_trip_payload(unit_order_id, plant_bay_id, **overrides)
    return get_success_data(api.create_inspection_trip(payload, headers), 201)


def hold_trip(api, inspection_trip_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.hold_inspection_trip(inspection_trip_id, headers))


def cancel_trip(api, inspection_trip_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.cancel_inspection_trip(inspection_trip_id, headers))


def read_trip(api, inspection_trip_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_inspection_trip(inspection_trip_id, headers))


# ─── Supplier slot lines and chassis reservations ─────────────────────────

def create_slot_line(api, **overrides):
    headers = make_program_admin_headers()
    return get_success_data(
        api.create_slot_line(f.build_slot_line_payload(**overrides), headers), 201
    )


def read_slot_line(api, slot_line_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_slot_line(slot_line_id, headers))


def fresh_slot_line_version(api, slot_line_id, headers=None):
    """Re-read the line so a booking echoes the free-slot picture it observed."""
    return read_slot_line(api, slot_line_id, headers)["version"]


def reserve_slot(api, program_id, slot_line_id, expected_slot_line_version=None,
                 **overrides):
    """Book one slot, picking up the line's current version when none is given."""
    headers = make_program_admin_headers()
    if expected_slot_line_version is None:
        expected_slot_line_version = fresh_slot_line_version(api, slot_line_id)
    payload = f.build_reservation_payload(
        program_id, slot_line_id, expected_slot_line_version, **overrides
    )
    return get_success_data(api.create_chassis_reservation(payload, headers), 201)


def confirm_reservation(api, reservation_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.confirm_chassis_reservation(reservation_id, headers))


def release_reservation(api, reservation_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.release_chassis_reservation(reservation_id, headers))


def read_reservation(api, reservation_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_chassis_reservation(reservation_id, headers))


# ─── Change orders ────────────────────────────────────────────────────────

def raise_change_order(api, unit_order_id, inspection_trip_id, program_id,
                       expected_unit_order_version=None, **overrides):
    """Raise a change order as the committee of the owning program.

    The committee's ``X-User-ID`` is the program id, and the request must echo
    the unit order's current version.
    """
    headers = make_customer_committee_rep_headers(program_id)
    if expected_unit_order_version is None:
        expected_unit_order_version = fresh_unit_version(api, unit_order_id)
    payload = f.build_change_order_payload(
        unit_order_id, inspection_trip_id, expected_unit_order_version, **overrides
    )
    return get_success_data(api.create_change_order(payload, headers), 201)


def submit_change_order(api, change_order_id, program_id):
    headers = make_customer_committee_rep_headers(program_id)
    return get_success_data(api.submit_change_order(change_order_id, headers))


def negotiate_change_order(api, change_order_id, officer=None):
    headers = make_purchasing_officer_headers(officer) if officer \
        else make_purchasing_officer_headers()
    return get_success_data(api.negotiate_change_order(change_order_id, headers))


def revise_change_order(api, change_order_id, program_id, **overrides):
    headers = make_customer_committee_rep_headers(program_id)
    payload = f.build_revision_payload(**overrides)
    return get_success_data(api.revise_change_order(change_order_id, payload, headers))


def approve_change_order(api, change_order_id, officer=None):
    headers = make_purchasing_officer_headers(officer) if officer \
        else make_purchasing_officer_headers()
    return get_success_data(api.approve_change_order(change_order_id, headers))


def reject_change_order(api, change_order_id, officer=None):
    headers = make_purchasing_officer_headers(officer) if officer \
        else make_purchasing_officer_headers()
    return get_success_data(api.reject_change_order(change_order_id, headers))


def rescind_change_order(api, change_order_id, officer=None):
    headers = make_purchasing_officer_headers(officer) if officer \
        else make_purchasing_officer_headers()
    return get_success_data(api.rescind_change_order(change_order_id, headers))


def read_change_order(api, change_order_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_change_order(change_order_id, headers))


def approved_change_order(api, unit_order_id, inspection_trip_id, program_id,
                          **overrides):
    """Raise, submit and approve one change order against a held trip."""
    change_order = raise_change_order(
        api, unit_order_id, inspection_trip_id, program_id, **overrides
    )
    submit_change_order(api, change_order["id"], program_id)
    return approve_change_order(api, change_order["id"])


# ─── Certification tests ──────────────────────────────────────────────────

def submit_certification_test(api, unit_order_id, tester=THIRD_PARTY_TESTER_ID,
                              **overrides):
    headers = make_third_party_tester_headers(tester)
    payload = f.build_certification_test_payload(unit_order_id, **overrides)
    return get_success_data(api.create_certification_test(payload, headers), 201)


def record_test_result(api, certification_test_id, tester=THIRD_PARTY_TESTER_ID,
                       **overrides):
    """The signer must differ from the unit's weight calculation engineer."""
    headers = make_third_party_tester_headers(tester)
    payload = f.build_test_result_payload(**overrides)
    return get_success_data(api.record_test_result(certification_test_id, payload,
                                                   headers))


def read_certification_test(api, certification_test_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_certification_test(certification_test_id, headers))


# ─── Delivery and warranty ────────────────────────────────────────────────

def deliver_unit(api, unit_order_id, **overrides):
    headers = make_program_admin_headers()
    payload = f.build_delivery_payload(**overrides)
    return get_success_data(api.deliver_unit_order(unit_order_id, payload, headers))


def warranty_for_unit(api, unit_order_id, headers=None):
    """Delivery returns the unit order, so its warranty row is found by filter."""
    headers = headers or make_program_admin_headers()
    body = get_success_data(
        api.list_warranty_startups(headers, {"unit_order_id": unit_order_id})
    )
    return body[0] if body else None


def complete_training(api, warranty_startup_id, **overrides):
    headers = make_program_admin_headers()
    payload = f.build_training_payload(**overrides)
    return get_success_data(api.complete_training(warranty_startup_id, payload, headers))


def read_warranty(api, warranty_startup_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.get_warranty_startup(warranty_startup_id, headers))


# ─── Program sweep ────────────────────────────────────────────────────────

def run_sweep(api, program_id, headers=None):
    headers = headers or make_program_admin_headers()
    return get_success_data(api.ops_run(program_id, headers))


# ─── The build ladder, driven one stage at a time ─────────────────────────

STAGES = (
    "SPEC_LOCKED",
    "PRE_CON_HELD",
    "IN_PRODUCTION",
    "MID_CON_HELD",
    "CERTIFIED",
    "FINAL_INSPECTED",
    "DELIVERED",
)


def setup_unit_at_stage(api, stage, program_overrides=None, clauses=None,
                        unit_overrides=None, bay_overrides=None,
                        pre_trip_overrides=None, slot_line_overrides=None,
                        reservation_overrides=None, mid_trip_overrides=None,
                        test_overrides=None, result_overrides=None,
                        delivery_overrides=None):
    """Drive one unit up the build ladder to the requested stage.

    ``CERTIFIED`` means the build dimension rests at ``MID_CON_HELD`` while the
    certification dimension reads ``CERTIFIED``; the two dimensions advance on
    entirely different triggers.  Returns a context dictionary naming every row
    the ladder created.
    """
    assert stage in STAGES, f"unknown stage {stage}"
    reached = STAGES.index(stage)

    ctx = setup_awarded_unit(
        api,
        program_overrides=program_overrides,
        clauses=clauses,
        **(unit_overrides or {}),
    )
    if reached == 0:
        return ctx

    # PRE_CON_HELD: a held pre-construction trip advances the build dimension.
    bay = create_plant_bay(api, **(bay_overrides or {}))
    ctx["bay"] = bay
    ctx["bay_id"] = bay["id"]
    pre_trip_fields = {"trip_type": "PRE_CONSTRUCTION"}
    pre_trip_fields.update(pre_trip_overrides or {})
    pre_trip = schedule_trip(api, ctx["unit_id"], bay["id"], **pre_trip_fields)
    ctx["pre_trip"] = hold_trip(api, pre_trip["id"])
    ctx["pre_trip_id"] = pre_trip["id"]
    if reached == 1:
        ctx["unit"] = read_unit(api, ctx["unit_id"])
        return ctx

    # IN_PRODUCTION: production start needs a CONFIRMED reservation, which it
    # then consumes.
    line = create_slot_line(api, **(slot_line_overrides or {}))
    ctx["slot_line"] = line
    ctx["slot_line_id"] = line["id"]
    reservation = reserve_slot(
        api, ctx["program_id"], line["id"],
        unit_order_id=ctx["unit_id"], **(reservation_overrides or {}),
    )
    ctx["reservation_id"] = reservation["id"]
    ctx["reservation"] = confirm_reservation(api, reservation["id"])
    admin = make_program_admin_headers()
    ctx["unit"] = get_success_data(api.start_production(ctx["unit_id"], admin))
    if reached == 2:
        return ctx

    # MID_CON_HELD: a held mid-construction trip advances the build dimension.
    mid_trip_fields = {
        "trip_type": "MID_CONSTRUCTION",
        "scheduled_start": "2026-09-20T08:00:00Z",
        "scheduled_end": "2026-09-20T16:00:00Z",
    }
    mid_trip_fields.update(mid_trip_overrides or {})
    mid_trip = schedule_trip(api, ctx["unit_id"], bay["id"], **mid_trip_fields)
    ctx["mid_trip"] = hold_trip(api, mid_trip["id"])
    ctx["mid_trip_id"] = mid_trip["id"]
    ctx["unit"] = read_unit(api, ctx["unit_id"])
    if reached == 3:
        return ctx

    # CERTIFIED: a passed standards test certifies the unit.
    test = submit_certification_test(api, ctx["unit_id"], **(test_overrides or {}))
    ctx["certification_test_id"] = test["id"]
    ctx["certification_test"] = record_test_result(
        api, test["id"], **(result_overrides or {})
    )
    ctx["unit"] = read_unit(api, ctx["unit_id"])
    if reached == 4:
        return ctx

    # FINAL_INSPECTED: within axle limits, certified, no open amendments.
    ctx["unit"] = get_success_data(api.final_inspection(ctx["unit_id"], admin))
    if reached == 5:
        return ctx

    # DELIVERED: the handover creates the warranty startup in PENDING_TRAINING.
    ctx["unit"] = deliver_unit(api, ctx["unit_id"], **(delivery_overrides or {}))
    ctx["warranty"] = warranty_for_unit(api, ctx["unit_id"])
    ctx["warranty_id"] = ctx["warranty"]["id"]
    return ctx


# ─── Multi-program and multi-unit scenarios ───────────────────────────────

def setup_two_program_scenario(api):
    """Two independent ACTIVE programs, each with a released spec and a unit."""
    first = setup_awarded_unit(api)
    second = setup_awarded_unit(api)
    return {"first": first, "second": second}


def setup_supersession_scenario(api, clauses=None):
    """A released predecessor plus a draft successor that names it.

    Releasing the successor drives the supersession cascade over the
    predecessor, the units that pinned it and their certifications.
    """
    ctx = setup_program_with_released_spec(api, clauses=clauses)
    successor = create_draft_specification(
        api, ctx["program_id"], supersedes_spec_id=ctx["specification_id"]
    )
    ctx["successor"] = successor
    ctx["successor_id"] = successor["id"]
    return ctx
