"""Composite setup helpers.

These encapsulate the multi-step preambles that the design instances share:
standing up an institution with a logical clock, a term, a student, a plan
template, then a pending enrollment with charges/aid, activating it, settling
the down payment and installments, advancing the clock and running delinquency,
and reaching withdrawal. Every helper builds its preconditions from scratch
(the harness restarts the server with an empty database before each test) and
uses get_success_data() so setup failures surface as clear "Setup failed" errors.

Identity threading: the Student role is entity-backed, so Student-initiated calls
use make_student_headers(student_id). Registrar/Bursar are opaque operators.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_student_headers,
)
from .constants import (
    TERM_START,
    TERM_END,
    ENROLL_OPEN,
    ENROLL_CLOSE,
    DEFAULT_CLOCK,
)
from . import factories


REGISTRAR = TEST_USERS["registrar_headers"]
BURSAR = TEST_USERS["bursar_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / 2: base scaffolding (institution + clock + term + student + template)
# ---------------------------------------------------------------------------
def create_institution(refund_policy="DATE_BASED", currency="USD", name="Test Institution",
                       clock=DEFAULT_CLOCK):
    """Create an institution and set its logical clock. Returns the institution dict."""
    inst = get_success_data(
        api_client.create_institution(
            factories.create_institution_payload(
                name=name, currency=currency, refund_policy=refund_policy
            ),
            REGISTRAR,
        )
    )
    if clock is not None:
        get_success_data(
            api_client.set_clock(inst["id"], factories.set_clock_payload(clock), REGISTRAR)
        )
    return inst


def set_clock(institution_id, to_iso8601):
    """Advance an institution's logical clock to an instant."""
    return get_success_data(
        api_client.set_clock(institution_id, factories.set_clock_payload(to_iso8601), REGISTRAR)
    )


def create_term(institution_id, code="FALL2026", term_start=TERM_START, term_end=TERM_END,
                enroll_open=ENROLL_OPEN, enroll_close=ENROLL_CLOSE):
    """Create an OPEN academic term. Returns the term dict."""
    return get_success_data(
        api_client.create_term(
            factories.create_term_payload(
                institution_id,
                code=code,
                term_start=term_start,
                term_end=term_end,
                enroll_open=enroll_open,
                enroll_close=enroll_close,
            ),
            REGISTRAR,
        )
    )


def create_student(institution_id, external_ref="S1", full_name="Test Student",
                   email="student@example.edu"):
    """Create a student. Returns the student dict."""
    return get_success_data(
        api_client.create_student(
            factories.create_student_payload(
                institution_id, external_ref=external_ref, full_name=full_name, email=email
            ),
            REGISTRAR,
        )
    )


def create_plan_template(institution_id, name="4PAY", installment_count=4,
                         down_payment_pct=0.20, plan_fee_cents=4500,
                         late_fee_grace_days=3, autopay_required=None):
    """Create an ACTIVE plan template. Returns the template dict."""
    overrides = {}
    if autopay_required is not None:
        overrides["autopay_required"] = autopay_required
    return get_success_data(
        api_client.create_plan_template(
            factories.create_plan_template_payload(
                institution_id,
                name=name,
                installment_count=installment_count,
                down_payment_pct=down_payment_pct,
                plan_fee_cents=plan_fee_cents,
                late_fee_grace_days=late_fee_grace_days,
                **overrides,
            ),
            REGISTRAR,
        )
    )


def setup_base(refund_policy="DATE_BASED", clock=DEFAULT_CLOCK, installment_count=4,
               down_payment_pct=0.20, plan_fee_cents=4500, late_fee_grace_days=3,
               autopay_required=None, term_overrides=None):
    """Institution (+clock) + OPEN term + student + ACTIVE template.

    Returns dict: {institution, term, student, template}.
    """
    inst = create_institution(refund_policy=refund_policy, clock=clock)
    term = create_term(inst["id"], **(term_overrides or {}))
    student = create_student(inst["id"])
    template = create_plan_template(
        inst["id"],
        installment_count=installment_count,
        down_payment_pct=down_payment_pct,
        plan_fee_cents=plan_fee_cents,
        late_fee_grace_days=late_fee_grace_days,
        autopay_required=autopay_required,
    )
    return {"institution": inst, "term": term, "student": student, "template": template}


# ---------------------------------------------------------------------------
# Enrollment building blocks
# ---------------------------------------------------------------------------
def create_enrollment(student_id, term_id, plan_template_id, autopay_enabled=None):
    """Create a PENDING enrollment. Returns the enrollment dict."""
    overrides = {}
    if autopay_enabled is not None:
        overrides["autopay_enabled"] = autopay_enabled
    return get_success_data(
        api_client.create_enrollment(
            factories.create_enrollment_payload(
                student_id, term_id, plan_template_id, **overrides
            ),
            REGISTRAR,
        )
    )


def post_charge(enrollment_id, amount_cents, kind="TUITION"):
    """Post a charge against an enrollment. Returns the charge dict."""
    return get_success_data(
        api_client.create_charge(
            factories.create_charge_payload(enrollment_id, kind=kind, amount_cents=amount_cents),
            REGISTRAR,
        )
    )


def apply_aid(enrollment_id, amount_cents, source="GRANT"):
    """Apply financial aid to an enrollment. Returns the aid dict."""
    return get_success_data(
        api_client.create_aid(
            factories.create_aid_payload(enrollment_id, source=source, amount_cents=amount_cents),
            REGISTRAR,
        )
    )


def current_version(enrollment_id):
    """Read the enrollment's current version (for OCC-guarded calls)."""
    enr = get_success_data(api_client.get_enrollment(enrollment_id, REGISTRAR))
    return enr["version"]


def activate(enrollment_id, expected_version=None):
    """Activate an enrollment using its current version (or a supplied one)."""
    if expected_version is None:
        expected_version = current_version(enrollment_id)
    return get_success_data(
        api_client.activate_enrollment(
            enrollment_id, factories.activate_payload(expected_version), REGISTRAR
        )
    )


def get_enrollment(enrollment_id):
    """Read the full enrollment resource."""
    return get_success_data(api_client.get_enrollment(enrollment_id, REGISTRAR))


def list_installments(enrollment_id):
    """List an enrollment's installments in sequence order. Returns the list."""
    resp = api_client.list_installments(REGISTRAR, params={"enrollment_id": enrollment_id})
    data = get_success_data(resp)
    if isinstance(data, dict):
        # Some envelopes nest the array; be defensive.
        data = data.get("items", data)
    items = list(data)
    items.sort(key=lambda i: i["sequence_index"])
    return items


# ---------------------------------------------------------------------------
# Tier 3: enrollment lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_active_enrollment(charges_cents=500000, aid_cents=100000, refund_policy="DATE_BASED",
                            clock=DEFAULT_CLOCK, installment_count=4, down_payment_pct=0.20,
                            plan_fee_cents=4500, late_fee_grace_days=3, autopay_enabled=None,
                            autopay_required=None):
    """Stand up an ACTIVE enrollment: base scaffolding + charges (+optional aid) + activate.

    Returns dict: {institution, term, student, template, enrollment, installments}.
    """
    base = setup_base(
        refund_policy=refund_policy,
        clock=clock,
        installment_count=installment_count,
        down_payment_pct=down_payment_pct,
        plan_fee_cents=plan_fee_cents,
        late_fee_grace_days=late_fee_grace_days,
        autopay_required=autopay_required,
    )
    enr = create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"],
        autopay_enabled=autopay_enabled,
    )
    if charges_cents:
        post_charge(enr["id"], charges_cents)
    if aid_cents:
        apply_aid(enr["id"], aid_cents)
    activate(enr["id"])
    base["enrollment"] = get_enrollment(enr["id"])
    base["installments"] = list_installments(enr["id"])
    return base


def setup_pending_enrollment(charges_cents=500000, aid_cents=0, refund_policy="DATE_BASED",
                             clock=DEFAULT_CLOCK, installment_count=4, down_payment_pct=0.20,
                             plan_fee_cents=4500, late_fee_grace_days=3, autopay_enabled=None,
                             autopay_required=None):
    """Stand up a PENDING enrollment with charges/aid posted but NOT activated.

    Returns dict: {institution, term, student, template, enrollment}.
    """
    base = setup_base(
        refund_policy=refund_policy,
        clock=clock,
        installment_count=installment_count,
        down_payment_pct=down_payment_pct,
        plan_fee_cents=plan_fee_cents,
        late_fee_grace_days=late_fee_grace_days,
        autopay_required=autopay_required,
    )
    enr = create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"],
        autopay_enabled=autopay_enabled,
    )
    if charges_cents:
        post_charge(enr["id"], charges_cents)
    if aid_cents:
        apply_aid(enr["id"], aid_cents)
    base["enrollment"] = get_enrollment(enr["id"])
    return base


def settle_down_payment(enrollment_id, amount_cents, headers=None, as_student_id=None):
    """Create + settle a DOWN_PAYMENT. Returns the settled payment dict."""
    create_headers = headers if headers is not None else BURSAR
    if as_student_id is not None:
        create_headers = make_student_headers(as_student_id)
    pay = get_success_data(
        api_client.create_payment(
            factories.create_payment_payload(enrollment_id, "DOWN_PAYMENT", amount_cents),
            create_headers,
        )
    )
    return get_success_data(api_client.settle_payment(pay["id"], BURSAR))


def settle_installment(enrollment_id, installment_id, amount_cents):
    """Create + settle an INSTALLMENT payment against a target installment."""
    pay = get_success_data(
        api_client.create_payment(
            factories.create_payment_payload(
                enrollment_id, "INSTALLMENT", amount_cents, installment_id=installment_id
            ),
            BURSAR,
        )
    )
    return get_success_data(api_client.settle_payment(pay["id"], BURSAR))


def run_delinquency(enrollment_id):
    """Run the delinquency sweep on an enrollment."""
    return get_success_data(api_client.run_delinquency(enrollment_id, REGISTRAR))


def list_late_fees(enrollment_id):
    """List an enrollment's late fees. Returns the list."""
    data = get_success_data(
        api_client.list_late_fees(REGISTRAR, params={"enrollment_id": enrollment_id})
    )
    if isinstance(data, dict):
        data = data.get("items", data)
    return list(data)


def list_holds(enrollment_id):
    """List an enrollment's holds. Returns the list."""
    data = get_success_data(
        api_client.list_holds(REGISTRAR, params={"enrollment_id": enrollment_id})
    )
    if isinstance(data, dict):
        data = data.get("items", data)
    return list(data)


def list_withdrawals(enrollment_id):
    """List an enrollment's withdrawals. Returns the list."""
    data = get_success_data(
        api_client.list_withdrawals(REGISTRAR, params={"enrollment_id": enrollment_id})
    )
    if isinstance(data, dict):
        data = data.get("items", data)
    return list(data)


def get_student(student_id):
    """Read a student resource."""
    return get_success_data(api_client.get_student(student_id, REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_delinquent_enrollment(charges_cents=500000, aid_cents=100000, installment_count=4,
                                down_payment_pct=0.20, settle_down=True, down_amount=80000,
                                delinquency_clock="2026-10-28T00:00:00.000Z",
                                refund_policy="DATE_BASED"):
    """ACTIVE enrollment swept into delinquency.

    Defaults reproduce the 4PAY [80000 x4] plan with the clock advanced to
    2026-10-28 so installments 1 and 2 are OVERDUE (total 160000 >= 150000),
    raising a DELINQUENCY_AMOUNT hold. Returns dict including the resolved
    enrollment, installments, holds, and late_fees.
    """
    base = setup_active_enrollment(
        charges_cents=charges_cents,
        aid_cents=aid_cents,
        refund_policy=refund_policy,
        installment_count=installment_count,
        down_payment_pct=down_payment_pct,
    )
    if settle_down and down_amount:
        settle_down_payment(base["enrollment"]["id"], down_amount)
    set_clock(base["institution"]["id"], delinquency_clock)
    run_delinquency(base["enrollment"]["id"])
    base["enrollment"] = get_enrollment(base["enrollment"]["id"])
    base["installments"] = list_installments(base["enrollment"]["id"])
    base["holds"] = list_holds(base["enrollment"]["id"])
    base["late_fees"] = list_late_fees(base["enrollment"]["id"])
    return base


def withdraw(enrollment_id, effective_date, expected_version=None):
    """Withdraw an enrollment. Returns the withdrawn enrollment dict."""
    if expected_version is None:
        expected_version = current_version(enrollment_id)
    return get_success_data(
        api_client.withdraw_enrollment(
            enrollment_id,
            factories.withdraw_payload(effective_date, expected_version),
            REGISTRAR,
        )
    )
