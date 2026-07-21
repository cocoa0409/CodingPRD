"""Composite setup helpers.

Each helper builds its preconditions from scratch through PRD-declared endpoints
(the test harness resets the server and empties the DB before every test). All
setup runs as the opaque Operator, which is authorized for every endpoint used
here; ownership-gated GroupLeader/Traveler calls are exercised directly in the
relevant tests, not in these helpers.

Setup calls use get_success_data() (lenient 2xx) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing downstream assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import OPERATOR
from . import factories as F


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, OPERATOR))


def make_tour(api, **overrides):
    return get_success_data(api.create_tour(F.create_tour_payload(**overrides), OPERATOR))


def make_group_leader(api, **overrides):
    return get_success_data(api.create_group_leader(F.create_group_leader_payload(**overrides), OPERATOR))


def make_departure(api, tour_id, gl_id, **overrides):
    """Create a DRAFT departure."""
    return get_success_data(
        api.create_departure(F.create_departure_payload(tour_id, gl_id, **overrides), OPERATOR)
    )


def open_departure(api, dep_id):
    return get_success_data(api.open_departure(dep_id, OPERATOR))


def enroll(api, departure_id, **overrides):
    return get_success_data(api.create_enrollment(F.create_enrollment_payload(departure_id, **overrides), OPERATOR))


def make_plan(api, enrollment_id, expected_version, **overrides):
    return get_success_data(
        api.create_payment_plan(
            F.create_payment_plan_payload(enrollment_id, expected_version, **overrides), OPERATOR
        )
    )


def pay(api, plan_id, amount_cents, kind="INSTALLMENT", **overrides):
    return get_success_data(
        api.create_payment(F.create_payment_payload(plan_id, amount_cents, kind=kind, **overrides), OPERATOR)
    )


def get_enrollment(api, enr_id):
    return get_success_data(api.get_enrollment(enr_id, OPERATOR))


def get_departure(api, dep_id):
    return get_success_data(api.get_departure(dep_id, OPERATOR))


def get_plan(api, plan_id):
    return get_success_data(api.get_payment_plan(plan_id, OPERATOR))


def list_plan_payments(api, plan_id):
    resp = api.list_payment_plan_payments(plan_id, OPERATOR, params={"limit": 100, "offset": 0})
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 1/2: catalog + open departure
# --------------------------------------------------------------------------
def setup_open_departure(api, clock=None, tour_overrides=None, gl_overrides=None, **dep_overrides):
    """Clock (optional) + tour + group leader + OPEN departure.

    Returns dict with keys: tour, group_leader, departure (the OPEN departure).
    """
    if clock is not None:
        set_clock(api, clock)
    tour = make_tour(api, **(tour_overrides or {}))
    gl = make_group_leader(api, **(gl_overrides or {}))
    dep = make_departure(api, tour["id"], gl["id"], **dep_overrides)
    dep = open_departure(api, dep["id"])
    return {"tour": tour, "group_leader": gl, "departure": dep}


def setup_draft_departure(api, clock=None, tour_overrides=None, gl_overrides=None, **dep_overrides):
    """Clock (optional) + tour + group leader + DRAFT departure (NOT opened)."""
    if clock is not None:
        set_clock(api, clock)
    tour = make_tour(api, **(tour_overrides or {}))
    gl = make_group_leader(api, **(gl_overrides or {}))
    dep = make_departure(api, tour["id"], gl["id"], **dep_overrides)
    return {"tour": tour, "group_leader": gl, "departure": dep}


# --------------------------------------------------------------------------
# Tier 3/4: enrollment with a payment plan and accumulated payment state
# --------------------------------------------------------------------------
def setup_enrollment_with_deposit(api, clock=None, dep_overrides=None, enr_overrides=None,
                                  deposit_cents=30000, installment_count=1, on_draft=False):
    """OPEN (or DRAFT) departure + one enrollment + ACTIVE plan + deposit paid.

    Returns dict: tour, group_leader, departure, enrollment, plan, deposit_payment.
    The enrollment's payment_status ends at PARTIAL (deposit < total) unless the
    deposit equals the total.
    """
    if on_draft:
        ctx = setup_draft_departure(api, clock=clock, **(dep_overrides or {}))
    else:
        ctx = setup_open_departure(api, clock=clock, **(dep_overrides or {}))
    enr = enroll(api, ctx["departure"]["id"], **(enr_overrides or {}))
    plan = make_plan(api, enr["id"], enr["version"], installment_count=installment_count)
    deposit = pay(api, plan["id"], deposit_cents, kind="DEPOSIT")
    ctx.update({"enrollment": enr, "plan": plan, "deposit_payment": deposit})
    return ctx


def setup_paid_in_full_enrollment(api, clock=None, dep_overrides=None, enr_overrides=None,
                                  price_cents=250000):
    """OPEN departure + one enrollment + ACTIVE plan + single full payment.

    The enrollment ends PAID_IN_FULL and the plan PAID (the paid-in-full cascade
    has fired). Returns dict: tour, group_leader, departure, enrollment, plan.
    """
    ctx = setup_open_departure(api, clock=clock, **(dep_overrides or {}))
    enr = enroll(api, ctx["departure"]["id"], **(enr_overrides or {}))
    plan = make_plan(api, enr["id"], enr["version"], installment_count=1)
    pay(api, plan["id"], price_cents, kind="DEPOSIT")
    ctx.update({"enrollment": enr, "plan": plan})
    return ctx


def setup_confirmed_enrollment(api, clock=None, dep_overrides=None, enr_overrides=None,
                               deposit_cents=30000):
    """OPEN departure + enrollment + plan + deposit paid + CONFIRMED lifecycle."""
    ctx = setup_enrollment_with_deposit(api, clock=clock, dep_overrides=dep_overrides,
                                        enr_overrides=enr_overrides, deposit_cents=deposit_cents)
    ctx["enrollment"] = get_success_data(api.confirm_enrollment(ctx["enrollment"]["id"], OPERATOR))
    return ctx


# --------------------------------------------------------------------------
# Tier 5: permission-form progression
# --------------------------------------------------------------------------
def make_permission_form(api, enrollment_id, **overrides):
    return get_success_data(
        api.create_permission_form(F.create_permission_form_payload(enrollment_id, **overrides), OPERATOR)
    )


def setup_permission_form_changes_requested(api, clock=None):
    """OPEN departure + enrollment + a form submitted then sent back (CHANGES_REQUESTED)."""
    ctx = setup_open_departure(api, clock=clock)
    enr = enroll(api, ctx["departure"]["id"], traveler_gender="FEMALE")
    pf = make_permission_form(api, enr["id"], passport_number="X1234567")
    get_success_data(api.submit_permission_form(pf["id"], OPERATOR))
    pf = get_success_data(api.review_permission_form(pf["id"], {"decision": "REQUEST_CHANGES"}, OPERATOR))
    ctx.update({"enrollment": enr, "permission_form": pf})
    return ctx


def setup_approved_permission_form(api, enrollment_id):
    """Create -> submit -> approve a permission form for an existing enrollment.
    Returns the APPROVED form data; the enrollment's doc_complete becomes true."""
    pf = make_permission_form(api, enrollment_id)
    get_success_data(api.submit_permission_form(pf["id"], OPERATOR))
    return get_success_data(api.review_permission_form(pf["id"], {"decision": "APPROVE"}, OPERATOR))


# --------------------------------------------------------------------------
# Rooming helpers
# --------------------------------------------------------------------------
def make_room(api, departure_id, **overrides):
    return get_success_data(
        api.create_rooming_assignment(F.create_rooming_payload(departure_id, **overrides), OPERATOR)
    )


def add_member(api, room_id, enrollment_id):
    return get_success_data(api.add_rooming_member(room_id, {"enrollment_id": enrollment_id}, OPERATOR))


# --------------------------------------------------------------------------
# Supplier helpers
# --------------------------------------------------------------------------
def make_supplier(api, **overrides):
    return get_success_data(api.create_supplier(F.create_supplier_payload(**overrides), OPERATOR))


def make_supplier_booking(api, departure_id, supplier_id, start, end, **overrides):
    return get_success_data(
        api.create_supplier_booking(
            F.create_supplier_booking_payload(departure_id, supplier_id, start, end, **overrides), OPERATOR
        )
    )


# --------------------------------------------------------------------------
# Chaperone helper
# --------------------------------------------------------------------------
def make_chaperone(api, departure_id, **overrides):
    return get_success_data(api.create_chaperone(F.create_chaperone_payload(departure_id, **overrides), OPERATOR))
