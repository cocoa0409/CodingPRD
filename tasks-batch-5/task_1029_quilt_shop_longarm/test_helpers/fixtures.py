"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is reset before every individual test. Helpers use the lenient
get_success_data() validator so a broken setup surfaces as a clear "Setup failed".

Clerk is the default staff actor for setup (opaque role, no ownership gate). Member-owned
flows that need ownership threading accept an explicit `member_headers` argument built from
make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_member_headers
from . import factories as f


def _clerk():
    return TEST_USERS["clerk_headers"]


def _manager():
    return TEST_USERS["manager_headers"]


# --------------------------------------------------------------------------- members
def create_member(api, headers=None, **overrides):
    resp = api.create_member(f.create_member_payload(**overrides), headers or _clerk())
    return get_success_data(resp)


# ----------------------------------------------------------------- fabric bolts / cuts
def create_bolt(api, headers=None, **overrides):
    resp = api.create_fabric_bolt(f.create_fabric_bolt_payload(**overrides), headers or _clerk())
    return get_success_data(resp)


def create_cut(api, bolt_id, yards_requested, headers=None, **overrides):
    resp = api.create_fabric_cut(
        f.create_fabric_cut_payload(bolt_id, yards_requested, **overrides), headers or _clerk())
    return get_success_data(resp)


def create_bolt_with_cut(api, yards_requested, bolt_overrides=None, cut_overrides=None):
    """A bolt plus a single CUT row. Returns (bolt, cut)."""
    bolt = create_bolt(api, **(bolt_overrides or {}))
    cut = create_cut(api, bolt["id"], yards_requested, **(cut_overrides or {}))
    return bolt, cut


# ------------------------------------------------------------------------------- kits
def create_kit_for_bolt(api, bolt_id, yards_per_kit=2, quantity=1, headers=None, **overrides):
    """A kit whose single component references the given bolt. Returns the kit."""
    components = [{"bolt_id": bolt_id, "yards_per_kit": yards_per_kit, "quantity": quantity}]
    resp = api.create_kit(f.create_kit_payload(components, **overrides), headers or _clerk())
    return get_success_data(resp)


# ----------------------------------------------------------------- longarm machines/jobs
def create_machine(api, headers=None, **overrides):
    resp = api.create_longarm_machine(f.create_longarm_machine_payload(**overrides), headers or _clerk())
    return get_success_data(resp)


def create_queued_job(api, member_id=None, headers=None, **overrides):
    """A QUEUED longarm job. Creates a member if member_id is not supplied.
    Returns (job, member_id)."""
    if member_id is None:
        member_id = create_member(api)["id"]
    resp = api.create_longarm_job(
        f.create_longarm_job_payload(member_id, **overrides), headers or _clerk())
    return get_success_data(resp), member_id


def start_job(api, job_id, machine_id, scheduled_start, scheduled_end, headers=None):
    resp = api.start_longarm_job(
        job_id,
        {"machine_id": machine_id, "scheduled_start": scheduled_start, "scheduled_end": scheduled_end},
        headers or _clerk())
    return get_success_data(resp)


def setup_in_progress_job(api, scheduled_start, scheduled_end,
                          job_overrides=None, machine_overrides=None):
    """Member + AVAILABLE machine + a job walked to IN_PROGRESS on the given slot.
    Returns dict(member_id, machine, job)."""
    member_id = create_member(api)["id"]
    machine = create_machine(api, **(machine_overrides or {}))
    job, _ = create_queued_job(api, member_id=member_id, **(job_overrides or {}))
    started = start_job(api, job["id"], machine["id"], scheduled_start, scheduled_end)
    return {"member_id": member_id, "machine": machine, "job": started}


def setup_completed_job(api, scheduled_start, scheduled_end,
                        measured_width_in, measured_length_in,
                        job_overrides=None, machine_overrides=None):
    """A job walked all the way to COMPLETED. Returns dict(member_id, machine, job)."""
    ctx = setup_in_progress_job(api, scheduled_start, scheduled_end,
                                job_overrides=job_overrides, machine_overrides=machine_overrides)
    resp = api.complete_longarm_job(
        ctx["job"]["id"],
        {"measured_width_in": measured_width_in, "measured_length_in": measured_length_in},
        _clerk())
    ctx["job"] = get_success_data(resp)
    return ctx


# --------------------------------------------------------------------- classes/enrollments
def create_class(api, headers=None, **overrides):
    resp = api.create_class(f.create_class_payload(**overrides), headers or _clerk())
    return get_success_data(resp)


def enroll(api, class_event_id, member_id, headers=None):
    resp = api.create_enrollment(
        f.create_enrollment_payload(class_event_id, member_id), headers or _clerk())
    return get_success_data(resp)


def setup_member_enrolled(api, class_overrides=None, member_overrides=None):
    """A member enrolled in one OPEN class. Returns dict(member, class_event, enrollment)."""
    member = create_member(api, **(member_overrides or {}))
    class_event = create_class(api, **(class_overrides or {}))
    enrollment = enroll(api, class_event["id"], member["id"])
    return {"member": member, "class_event": class_event, "enrollment": enrollment}


# --------------------------------------------------------------------------- special orders
def create_special_order(api, member_id=None, headers=None, **overrides):
    """A QUOTED special order. Creates a member if member_id is not supplied.
    Returns (order, member_id)."""
    if member_id is None:
        member_id = create_member(api)["id"]
    resp = api.create_special_order(
        f.create_special_order_payload(member_id, **overrides), headers or _clerk())
    return get_success_data(resp), member_id


def revise_order(api, order_id, est_unit_cost, quantity, expected_version, headers=None):
    resp = api.revise_special_order(
        order_id,
        {"est_unit_cost": est_unit_cost, "quantity": quantity,
         "expected_special_order_version": expected_version},
        headers or _clerk())
    return get_success_data(resp)
