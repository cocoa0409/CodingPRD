"""Grievances and evictions: the overruled-eviction termination cascade, the
sustained fork, terminal-state lockdown, and not-found."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    setup_active_tenancy, file_grievance, decide_grievance,
)

HS = TEST_USERS["housing_specialist_headers"]
PM = TEST_USERS["property_manager_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / grievance_eviction_overruled_branch_cascade
# ---------------------------------------------------------------------------
def test_eviction_overruled_terminates_tenancy(api):
    """PRD §3.8: "overruling an EVICTION terminates the tenancy — the tenancy moves from
    ACTIVE to TERMINATED, its lease_end_date is set from the logical clock".

    Design: Difficulty/non_linear_state_machine/grievance_eviction_overruled_branch_cascade
    """
    ctx = setup_active_tenancy(api, applicant_name="Grieve")
    griev = file_grievance(api, ctx["tenancy"]["id"], "EVICTION", "chronic nonpayment")
    decided = decide_grievance(api, griev["id"], "OVERRULED")
    assert decided["status"] == "OVERRULED"
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    assert tenancy["status"] == "TERMINATED"
    assert tenancy["lease_end_date"] is not None, "lease_end_date must be stamped on termination"


def test_eviction_overruled_frees_unit_and_records_lease_end(api):
    """PRD §3.8: "this cascades to the unit, which moves from OCCUPIED back to AVAILABLE
    and records the freed lease's end date into its last_lease_end_date".

    Design: Difficulty/non_linear_state_machine/grievance_eviction_overruled_branch_cascade
    """
    ctx = setup_active_tenancy(api, applicant_name="Grieve2")
    griev = file_grievance(api, ctx["tenancy"]["id"], "EVICTION", "chronic nonpayment")
    decide_grievance(api, griev["id"], "OVERRULED")
    tenancy = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], HS))
    assert unit["status"] == "AVAILABLE"
    assert unit["last_lease_end_date"] == tenancy["lease_end_date"], \
        "the unit records the freed lease's end date"


# ---------------------------------------------------------------------------
# Corner: grievance_sustained_leaves_tenancy_active
# ---------------------------------------------------------------------------
def test_sustained_eviction_leaves_tenancy_active(api):
    """PRD §3.8: "A SUSTAINED outcome upholds the tenant's position and never terminates
    the tenancy, regardless of grievance_type."

    Design: Corner/state_machines/grievance_sustained_leaves_tenancy_active
    """
    ctx = setup_active_tenancy(api, applicant_name="SM5")
    griev = file_grievance(api, ctx["tenancy"]["id"], "EVICTION", "cause")
    decided = decide_grievance(api, griev["id"], "SUSTAINED")
    assert decided["status"] == "SUSTAINED"
    assert get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))["status"] == "ACTIVE"
    assert get_success_data(api.get_unit(ctx["unit"]["id"], HS))["status"] == "OCCUPIED"


# ---------------------------------------------------------------------------
# Corner: decide_already_decided_grievance_rejected
# ---------------------------------------------------------------------------
def test_decide_already_decided_grievance_rejected(api):
    """PRD §3.8: "A PropertyManager decides a filed grievance by supplying an outcome,
    and only a grievance in FILED may be decided (else ERR_INVALID_STATE)."

    Design: Corner/state_machines/decide_already_decided_grievance_rejected
    """
    ctx = setup_active_tenancy(api, applicant_name="SM4")
    griev = file_grievance(api, ctx["tenancy"]["id"], "GRIEVANCE", "repair",
                           as_applicant=ctx["applicant"]["id"])
    decide_grievance(api, griev["id"], "SUSTAINED")
    resp = api.decide_grievance(griev["id"], {"outcome": "OVERRULED"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: decide_unknown_grievance_returns_404
# ---------------------------------------------------------------------------
def test_decide_unknown_grievance_returns_404(api):
    """PRD §2.5: "the system resolves them left to right and rejects the request at the
    first identifier that does not correspond to a live resource, returning the not-found
    error specific to that resource — ... ERR_GRIEVANCE_NOT_FOUND ... (all HTTP 404)."

    Design: Corner/errors/decide_unknown_grievance_returns_404
    """
    resp = api.decide_grievance(NON_EXISTENT_UUID, {"outcome": "SUSTAINED"}, PM)
    validate_error(resp, ApiErrorId.ERR_GRIEVANCE_NOT_FOUND)
