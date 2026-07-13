"""Composite setup helpers for the registry test suite.

Every test runs against a freshly restarted server, so the logical clock reads
the PRD default 2026-03-01T00:00:00Z at the start of each test and every helper
below builds its preconditions from scratch through PRD-declared endpoints.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error downstream.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_registrant_headers
from .factories import (
    create_registrant_payload,
    create_property_payload,
    create_maintenance_standard_payload,
    create_inspection_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["code_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Granular building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


def create_registrant(api, party_type="OWNER", license_number=None, **overrides):
    payload = create_registrant_payload(
        party_type=party_type, license_number=license_number, **overrides
    )
    return get_success_data(api.create_registrant(payload, ANON))


def create_property(api, registrant, occupancy_status="VACANT",
                    registration_type=None, parcel_id=None, **overrides):
    registration_type = registration_type or registrant["party_type"]
    payload = create_property_payload(
        registrant_id=registrant["id"],
        occupancy_status=occupancy_status,
        registration_type=registration_type,
        parcel_id=parcel_id,
        **overrides,
    )
    return get_success_data(
        api.create_property(payload, make_registrant_headers(registrant["id"]))
    )


def create_standard(api, code=None, category="SECURING", severity_weight=5,
                    cure_period_days=5, base_fine_cents=20000, description="std"):
    payload = create_maintenance_standard_payload(
        category=category, severity_weight=severity_weight,
        cure_period_days=cure_period_days, base_fine_cents=base_fine_cents,
        description=description,
    )
    if code is not None:
        payload["code"] = code
    return get_success_data(api.create_maintenance_standard(payload, ADMIN))


def create_inspection(api, property_id, inspector_badge=None,
                      scheduled_start="2026-03-02T09:00:00Z",
                      scheduled_end="2026-03-02T11:00:00Z"):
    payload = create_inspection_payload(
        property_id=property_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    if inspector_badge is not None:
        payload["inspector_badge"] = inspector_badge
    return get_success_data(api.create_inspection(payload, OFFICER))


def complete_inspection(api, inspection_id, result="FAIL", failed_standard_codes=None):
    payload = {"result": result}
    if result == "FAIL":
        payload["failed_standard_codes"] = failed_standard_codes or []
    return get_success_data(api.complete_inspection(inspection_id, payload, OFFICER))


def violations_for_inspection(api, inspection_id):
    resp = api.list_violations(OFFICER, params={"inspection_id": inspection_id})
    return get_success_data(resp)


def transition_violation(api, violation_id, action):
    return get_success_data(
        api.transition_violation(violation_id, {"action": action}, OFFICER)
    )


def assess_fine(api, violation_id):
    return get_success_data(api.assess_fine(violation_id, OFFICER))


def dispute_fine(api, fine_id, registrant_id, reason="disputed"):
    return get_success_data(api.transition_fine(
        fine_id, {"action": "DISPUTE", "dispute_reason": reason},
        make_registrant_headers(registrant_id),
    ))


def pay_fine(api, fine_id, registrant_id):
    return get_success_data(api.transition_fine(
        fine_id, {"action": "PAY"}, make_registrant_headers(registrant_id),
    ))


def record_lien(api, fine_id):
    """Convert an ASSESSED fine to a lien; return the created Lien row."""
    get_success_data(api.record_lien(fine_id, ADMIN))
    liens = get_success_data(api.list_liens(ADMIN, params={"source_fine_id": fine_id}))
    return liens[0]


def advance_foreclosure(api, property_id, registrant_id):
    return get_success_data(api.foreclosure_property(
        property_id, {"action": "ADVANCE"}, make_registrant_headers(registrant_id),
    ))


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_open_violation(api, *, category="SECURING", severity_weight=5,
                         cure_period_days=5, base_fine_cents=20000,
                         occupancy_status="VACANT", inspector_badge=None,
                         party_type="OWNER"):
    """OWNER/VACANT property whose only inspection FAILED one standard, leaving a
    single OPEN violation cited at the current clock. Returns a dict with keys:
    registrant, property, standard, inspection, violation.
    """
    standard = create_standard(
        api, category=category, severity_weight=severity_weight,
        cure_period_days=cure_period_days, base_fine_cents=base_fine_cents,
    )
    registrant = create_registrant(api, party_type=party_type)
    prop = create_property(
        api, registrant, occupancy_status=occupancy_status,
        registration_type=party_type,
    )
    inspection = create_inspection(api, prop["id"], inspector_badge=inspector_badge)
    complete_inspection(api, inspection["id"], "FAIL", [standard["code"]])
    violation = violations_for_inspection(api, inspection["id"])[0]
    return {
        "registrant": registrant,
        "property": prop,
        "standard": standard,
        "inspection": inspection,
        "violation": violation,
    }


def setup_escalated_violation(api, *, escalate_clock="2026-03-06T00:00:00Z", **kw):
    """setup_open_violation, then escalate the violation at escalate_clock
    (which must be >= cure_deadline_at). Returns the same dict."""
    ctx = setup_open_violation(api, **kw)
    set_clock(api, escalate_clock)
    transition_violation(api, ctx["violation"]["id"], "ESCALATE")
    return ctx


def setup_assessed_fine(api, *, escalate_clock="2026-03-06T00:00:00Z", **kw):
    """Escalate then assess a fine. Adds 'fine' to the returned dict."""
    ctx = setup_escalated_violation(api, escalate_clock=escalate_clock, **kw)
    ctx["fine"] = assess_fine(api, ctx["violation"]["id"])
    return ctx


def setup_recorded_lien(api, *, escalate_clock="2026-03-06T00:00:00Z",
                        base_fine_cents=30000, **kw):
    """Escalate, assess, and record a lien. Adds 'fine' and 'lien' to the dict.
    The lien is recorded at escalate_clock (0 days overdue) so principal equals
    base_fine_cents."""
    ctx = setup_assessed_fine(
        api, escalate_clock=escalate_clock, base_fine_cents=base_fine_cents, **kw
    )
    ctx["lien"] = record_lien(api, ctx["fine"]["id"])
    return ctx


def setup_property_with_n_open_violations(api, *, n, base_fine_cents=30000,
                                          severity_weight=8, cure_period_days=5,
                                          category="SANITATION"):
    """One property with a single inspection failing n distinct standards, i.e.
    n OPEN violations. Returns dict: registrant, property, standards(list),
    inspection, violations(list)."""
    standards = [
        create_standard(
            api, category=category, severity_weight=severity_weight,
            cure_period_days=cure_period_days, base_fine_cents=base_fine_cents,
        )
        for _ in range(n)
    ]
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, occupancy_status="VACANT",
                           registration_type="OWNER")
    inspection = create_inspection(api, prop["id"])
    complete_inspection(api, inspection["id"], "FAIL",
                        [s["code"] for s in standards])
    violations = violations_for_inspection(api, inspection["id"])
    return {
        "registrant": registrant,
        "property": prop,
        "standards": standards,
        "inspection": inspection,
        "violations": violations,
    }


def get_property(api, property_id):
    return get_success_data(api.get_property(property_id, ADMIN))
