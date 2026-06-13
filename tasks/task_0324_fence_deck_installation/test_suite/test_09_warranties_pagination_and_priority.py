"""Warranty claim/resolve cycle, the site-measure validation-priority pair,
list pagination, and estimate-scoped line-item filtering.

Translates Difficulty/priority_pair_validation_conflict (site-measure arm),
Corner/state_machines/warranty_claim_resolve_repaired_cycle, and
Corner/endpoints listing instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_project,
    create_line_item_payload,
    setup_accepted_estimate, setup_completed_project, make_customer_headers,
    FENCE_100_PLAIN,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]
FT = TEST_USERS["field_tech_headers"]


# ===========================================================================
# priority_pair_validation_conflict instance 1: state beats setback
# ===========================================================================
def test_site_measure_approve_state_error_beats_setback(api):
    """PRD §2.9: "Only after all of those does the system evaluate state-machine legality, yielding `ERR_INVALID_STATE` (HTTP 409) when the target resource is not in a state from which the requested transition is defined, followed by the domain-specific business gates described throughout §3 (setback, dock-window, crew-overlap, material-readiness, draw-gate and draw-sequence checks)."
    PRD §3.3: "Approval requires the project to be in `ESTIMATED` status (otherwise `ERR_INVALID_STATE`) and requires `setback_ok` to be true; an approval attempted while `setback_ok` is false is the property-line safety gate and is rejected with `ERR_SETBACK_VIOLATION`." When both fail, the state check
    (earlier in the fixed order) wins -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/site_measure_approve_state_beats_setback
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    li = ctx["line_items"][0]
    # Bad measure: setback_ok false (would fail setback if state allowed).
    sm_bad = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": li["id"], "measured_units": 100}],
        "property_line_note": "encroachment on south line", "setback_ok": False}, FT))
    # Good measure approved -> project leaves ESTIMATED for MEASURED.
    sm_good = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": li["id"], "measured_units": 100}],
        "property_line_note": "resurveyed, clear", "setback_ok": True}, FT))
    get_success_data(api.approve_site_measure(pid, sm_good["id"], PM))
    # Re-approving the bad measure now fails BOTH state (project MEASURED, not
    # ESTIMATED) and setback; state must be reported.
    resp = api.approve_site_measure(pid, sm_bad["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_site_measure_approve_state_conflict_leaves_project_measured(api):
    """PRD §3.3: "Approval requires the project to be in `ESTIMATED` status (otherwise `ERR_INVALID_STATE`) and requires `setback_ok` to be true; an approval attempted while `setback_ok` is false is the property-line safety gate and is rejected with `ERR_SETBACK_VIOLATION`."
    PRD §2.5: "approving a site measure moves it from `ESTIMATED` to `MEASURED`". The
    failed re-approve does not alter the project, which stays MEASURED.

    Design: Difficulty/priority_pair_validation_conflict/site_measure_approve_state_beats_setback
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    li = ctx["line_items"][0]
    sm_bad = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": li["id"], "measured_units": 100}],
        "property_line_note": "encroachment on south line", "setback_ok": False}, FT))
    sm_good = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": li["id"], "measured_units": 100}],
        "property_line_note": "resurveyed, clear", "setback_ok": True}, FT))
    get_success_data(api.approve_site_measure(pid, sm_good["id"], PM))
    resp = api.approve_site_measure(pid, sm_bad["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["status"] == "MEASURED"


# ===========================================================================
# Corner/state_machines: warranty claim -> resolve REPAIRED -> ISSUED cycle
# ===========================================================================
def test_warranty_claim_then_resolve_repaired_returns_to_issued(api):
    """PRD §3.9: "A `Customer` files a claim on their own completed project's warranty: the claim requires the acting `X-User-ID` to equal the project's `customer_id` (otherwise `ERR_FORBIDDEN`) and the project to be in `COMPLETED` status (otherwise `ERR_INVALID_STATE`), and it moves the warranty from `ISSUED` to `CLAIMED`."
    PRD §3.9: "a resolution of REPAIRED closes the claim and reopens coverage, moving the warranty from `CLAIMED` back to `ISSUED`; a resolution of DENIED voids it, moving it from `CLAIMED` to `VOIDED`."

    Design: Corner/state_machines/warranty_claim_resolve_repaired_cycle
    """
    ctx = setup_completed_project(line_specs=[FENCE_100_PLAIN])
    pid = ctx["project"]["id"]
    cust_id = ctx["customer"]["id"]
    warranties = get_success_data(api.list_warranties(pid, PM))
    war = warranties[0]
    get_success_data(api.claim_warranty(pid, war["id"], make_customer_headers(cust_id)))
    resp = api.resolve_warranty(pid, war["id"], {"resolution": "REPAIRED"}, PM)
    resolved = validate_success(resp, expected_status=200)
    assert resolved["status"] == "ISSUED"


# ===========================================================================
# Corner/endpoints: list projects pagination envelope
# ===========================================================================
def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps how many items a page returns; it defaults to 10 when omitted, and must lie between a minimum of 1 and a maximum of 100." With two projects and limit=1, exactly one is returned,
    total_count is 2, has_more true.

    Design: Corner/endpoints/list_projects_pagination_envelope
    """
    cust = create_customer()
    create_project(cust["id"], site_address="20 Pag", job_type="FENCE")
    create_project(cust["id"], site_address="21 Pag", job_type="DECK")
    resp = api.list_projects(PM, params={"customer_id": cust["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner/endpoints: list line items filtered by estimate
# ===========================================================================
def test_list_line_items_filtered_by_estimate(api):
    """PRD §2.6: "List endpoints support reverse-reachability filters — a project's estimates, permits, draws and so on are reachable by listing them under the project, and `/projects` itself accepts a `customer_id` filter that reaches projects from a customer."
    Filtering line items by estimate_id returns only the line items belonging to
    that estimate.

    Design: Corner/endpoints/list_line_items_filtered_by_estimate
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE_AND_DECK")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    get_success_data(api.create_line_item(create_line_item_payload(
        est["id"], work_type="FENCE", material="CEDAR", style="PRIVACY",
        quantity_units=100), EST))
    get_success_data(api.create_line_item(create_line_item_payload(
        est["id"], work_type="DECK", material="COMPOSITE", style="DECK_STANDARD",
        quantity_units=150), EST))
    resp = api.list_line_items(EST, params={"estimate_id": est["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(li["estimate_id"] == est["id"] for li in data)
