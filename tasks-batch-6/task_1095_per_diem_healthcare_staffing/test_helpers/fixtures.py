"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints only — the test harness restarts the server with an empty database
before each test. Setup calls use get_success_data() (lenient 2xx validator) so
a broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion failure.

Identity threading: FacilityScheduler / FacilityVerifier act with the Facility.id
as X-User-ID and Clinician acts with the Clinician.id, via the make_* builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_scheduler_headers,
    make_verifier_headers,
    make_clinician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
BILLER = TEST_USERS["billing_agent_headers"]
BILLER_BETA = TEST_USERS["billing_agent_beta_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Atomic helpers — one API call each, returning the created/updated resource.
# --------------------------------------------------------------------------- #
def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def new_facility(**overrides) -> dict:
    return get_success_data(api_client.create_facility(f.create_facility_payload(**overrides), ADMIN))


def add_rate_card(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card(facility_id, f.create_rate_card_payload(**overrides), ADMIN)
    )


def new_clinician(**overrides) -> dict:
    return get_success_data(api_client.create_clinician(f.create_clinician_payload(**overrides), ADMIN))


def add_credential(clinician_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_credential(
            clinician_id, f.create_credential_payload(**overrides), make_clinician_headers(clinician_id)
        )
    )


def verify_credential(credential_id: str, **payload) -> dict:
    body = {"decision": "VERIFIED"}
    body.update(payload)
    return get_success_data(api_client.verify_credential(credential_id, body, OFFICER))


def add_verified_credential(clinician_id: str, cred_overrides=None, verify_overrides=None) -> dict:
    cred = add_credential(clinician_id, **(cred_overrides or {}))
    verify_credential(cred["id"], **(verify_overrides or {}))
    return cred


def new_order(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            f.create_order_payload(facility_id, **overrides), make_scheduler_headers(facility_id)
        )
    )


def add_shift(order_id: str, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_shift(
            order_id, f.create_shift_payload(**overrides), make_scheduler_headers(facility_id)
        )
    )


def place_claim(shift_id: str, clinician_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(
            shift_id, f.create_claim_payload(clinician_id, **overrides), make_clinician_headers(clinician_id)
        )
    )


def read_shift_version(shift_id: str, facility_id: str) -> int:
    return get_success_data(api_client.get_shift(shift_id, make_scheduler_headers(facility_id)))["version"]


def award(shift_id: str, facility_id: str, claim_id=None, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = read_shift_version(shift_id, facility_id)
    payload = {"expected_shift_version": expected_version}
    if claim_id is not None:
        payload["claim_id"] = claim_id
    return get_success_data(api_client.award_shift(shift_id, payload, make_scheduler_headers(facility_id)))


def confirm(assignment_id: str, clinician_id: str) -> dict:
    return get_success_data(
        api_client.confirm_assignment(assignment_id, {}, make_clinician_headers(clinician_id))
    )


def submit_timesheet(assignment_id: str, clinician_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_timesheet(
            assignment_id, f.submit_timesheet_payload(**overrides), make_clinician_headers(clinician_id)
        )
    )


def verify_timesheet(timesheet_id: str, facility_id: str) -> dict:
    return get_success_data(
        api_client.verify_timesheet(timesheet_id, {}, make_verifier_headers(facility_id))
    )


def no_show(assignment_id: str, facility_id: str, note: str = "absent") -> dict:
    return get_success_data(
        api_client.no_show_assignment(assignment_id, {"note": note}, make_verifier_headers(facility_id))
    )


def read_facility_version(facility_id: str) -> int:
    return get_success_data(api_client.get_facility(facility_id, BILLER))["version"]


def generate_invoice(facility_id: str, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = read_facility_version(facility_id)
    return get_success_data(
        api_client.create_invoice(
            f.create_invoice_payload(facility_id, expected_version, **overrides), BILLER
        )
    )


def issue_invoice(invoice_id: str, headers=None) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, {}, headers or BILLER))


# --------------------------------------------------------------------------- #
# Composite builders.
# --------------------------------------------------------------------------- #
def setup_facility_with_verified_clinician(
    facility_overrides=None,
    rate_overrides=None,
    clinician_overrides=None,
    cred_overrides=None,
    verify_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Clock set, facility + RN rate card + one clinician holding a VERIFIED
    credential. Returns dict(facility, clinician, credential)."""
    if clock is not None:
        set_clock(clock)
    facility = new_facility(**(facility_overrides or {}))
    add_rate_card(facility["id"], **(rate_overrides or {}))
    clinician = new_clinician(**(clinician_overrides or {}))
    credential = add_verified_credential(clinician["id"], cred_overrides, verify_overrides)
    return {"facility": facility, "clinician": clinician, "credential": credential}


def setup_awarded_assignment(
    order_overrides=None,
    shift_overrides=None,
    facility_overrides=None,
    rate_overrides=None,
    clinician_overrides=None,
    cred_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """Full chain up to an AWARDED assignment (work_status PENDING_CONFIRMATION,
    pay_status UNBILLED). Returns dict with facility, clinician, credential,
    order, shift, claim, assignment."""
    base = setup_facility_with_verified_clinician(
        facility_overrides=facility_overrides,
        rate_overrides=rate_overrides,
        clinician_overrides=clinician_overrides,
        cred_overrides=cred_overrides,
        clock=clock,
    )
    fac_id = base["facility"]["id"]
    cl_id = base["clinician"]["id"]
    order = new_order(fac_id, **(order_overrides or {}))
    shift = add_shift(order["id"], fac_id, **(shift_overrides or {}))
    claim = place_claim(shift["id"], cl_id)
    assignment = award(shift["id"], fac_id, claim_id=claim["id"])
    base.update({"order": order, "shift": shift, "claim": claim, "assignment": assignment})
    return base


def setup_confirmed_assignment(**kwargs):
    """setup_awarded_assignment then the clinician confirms. Requires the clock to
    still be before the shift start (default clock 2026-06-01, default shift
    2026-06-08 satisfy this)."""
    bundle = setup_awarded_assignment(**kwargs)
    bundle["assignment"] = confirm(bundle["assignment"]["id"], bundle["clinician"]["id"])
    return bundle


def setup_submitted_timesheet(
    submit_after_clock: str = "2026-06-08T19:30:00Z",
    timesheet_overrides=None,
    **kwargs,
):
    """Confirmed assignment, clock advanced past the shift end, timesheet submitted
    (assignment work_status WORKED, pay_status TIMESHEET_PENDING). Returns the
    confirmed-assignment bundle plus 'timesheet'."""
    bundle = setup_confirmed_assignment(**kwargs)
    set_clock(submit_after_clock)
    ts = submit_timesheet(
        bundle["assignment"]["id"], bundle["clinician"]["id"], **(timesheet_overrides or {})
    )
    bundle["timesheet"] = ts
    return bundle


def setup_verified_timesheet(**kwargs):
    """setup_submitted_timesheet then the verifier verifies it (timesheet VERIFIED,
    assignment pay_status PAYABLE, shift COMPLETED). Returns the bundle with the
    verified 'timesheet'."""
    bundle = setup_submitted_timesheet(**kwargs)
    bundle["timesheet"] = verify_timesheet(bundle["timesheet"]["id"], bundle["facility"]["id"])
    return bundle
