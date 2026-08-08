"""Covenant attainment forks (MET vs BREACHED), the inclusive 100.00 attainment boundary,
closed-interval window overlap, the program-floor guard, and waive legality."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_agreement, setup_executed_agreement,
    add_covenant, submit_report, accept_report,
    make_director_headers, make_analyst_headers,
)

DIRECTOR = make_director_headers("director-1")
ANALYST = make_analyst_headers("analyst-1")


def _two_covenants_after_report(api, inv_target=100_000_000, inv_window_year=2028):
    """Active GRANT agreement with a JOBS(100) and an INVESTMENT(inv_target) covenant, then
    one accepted report (actual_jobs 80, actual_investment 150,000,000). Returns ids."""
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov_jobs = add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                            measurement_start_date="2027-01-01T00:00:00.000Z",
                            measurement_end_date="2027-12-31T00:00:00.000Z")
    cov_inv = add_covenant(agr_id, covenant_type="INVESTMENT", target_value=inv_target,
                           measurement_start_date=f"{inv_window_year}-01-01T00:00:00.000Z",
                           measurement_end_date=f"{inv_window_year}-12-31T00:00:00.000Z")
    rep = submit_report(agr_id, actual_jobs=80, actual_investment_cents=150_000_000, attestation=True)
    accept_report(rep["id"])
    return {"agr_id": agr_id, "cov_jobs_id": cov_jobs["id"], "cov_inv_id": cov_inv["id"]}


def test_accept_forks_jobs_covenant_to_breached(api):
    """PRD §3.5: "A covenant whose recomputed attainment is greater than or equal to 100.00
    advances to `MET`; a covenant below 100.00 advances to `BREACHED`." Jobs 80/100 -> 80.00%.

    Design: Difficulty/non_linear_state_machine/covenant_branching_met_and_breached
    """
    ids = _two_covenants_after_report(api)
    cov = validate_success(api.get_covenant(ids["cov_jobs_id"], DIRECTOR))
    assert cov["attainment_pct"] == 80.0, cov["attainment_pct"]
    assert cov["status"] == "BREACHED"


def test_accept_forks_investment_covenant_to_met(api):
    """PRD §3.5: "the attainment percentage is that actual divided by the covenant's
    `target_value`, multiplied by 100, and rounded half up to two decimal places." Investment
    150,000,000/100,000,000 -> 150.00% drives the INVESTMENT covenant to MET.

    Design: Difficulty/non_linear_state_machine/covenant_branching_met_and_breached
    """
    ids = _two_covenants_after_report(api)
    cov = validate_success(api.get_covenant(ids["cov_inv_id"], DIRECTOR))
    assert cov["attainment_pct"] == 150.0, cov["attainment_pct"]
    assert cov["status"] == "MET"


def test_covenant_attainment_exactly_100_is_met(api):
    """PRD §3.5: "A covenant whose recomputed attainment is greater than or equal to 100.00
    advances to `MET`; a covenant below 100.00 advances to `BREACHED`." Jobs 100/100 == 100.00%.

    Design: Difficulty/boundary_precision_check/covenant_attainment_at_100_is_met
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov = add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    rep = submit_report(agr_id, actual_jobs=100, attestation=True)
    accept_report(rep["id"])
    got = validate_success(api.get_covenant(cov["id"], DIRECTOR))
    assert got["attainment_pct"] == 100.0, got["attainment_pct"]
    assert got["status"] == "MET"


def test_covenant_attainment_below_100_is_breached(api):
    """PRD §3.5: "A covenant whose recomputed attainment is greater than or equal to 100.00
    advances to `MET`; a covenant below 100.00 advances to `BREACHED`." Jobs 99/100 == 99.00%.

    Design: Difficulty/boundary_precision_check/covenant_attainment_at_100_is_met
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov = add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    rep = submit_report(agr_id, actual_jobs=99, attestation=True)
    accept_report(rep["id"])
    got = validate_success(api.get_covenant(cov["id"], DIRECTOR))
    assert got["attainment_pct"] == 99.0, got["attainment_pct"]
    assert got["status"] == "BREACHED"


def test_covenant_window_shared_endpoint_overlaps(api):
    """PRD §3.4: "the new covenant's closed measurement window must not overlap the window
    of any existing covenant of the same `covenant_type` on the same agreement; an overlap is
    rejected with `ERR_COVENANT_WINDOW_OVERLAP` (HTTP 409)." A second JOBS window starting on
    the first window's end date 2027-12-31 shares that boundary (closed intervals).

    Design: Difficulty/resource_temporal_overlap/covenant_window_overlap_closed_intervals
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                 measurement_start_date="2027-01-01T00:00:00.000Z",
                 measurement_end_date="2027-12-31T00:00:00.000Z")
    resp = api.create_covenant(agr_id, {
        "covenant_type": "JOBS", "target_value": 120,
        "measurement_start_date": "2027-12-31T00:00:00.000Z",
        "measurement_end_date": "2028-06-30T00:00:00.000Z"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_COVENANT_WINDOW_OVERLAP)


def test_covenant_different_type_may_overlap(api):
    """PRD §3.4: "Covenants of different types may overlap freely." An INVESTMENT covenant
    sharing the JOBS covenant's window is accepted.

    Design: Difficulty/resource_temporal_overlap/covenant_window_overlap_closed_intervals
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                 measurement_start_date="2027-01-01T00:00:00.000Z",
                 measurement_end_date="2027-12-31T00:00:00.000Z")
    inv = validate_success(api.create_covenant(agr_id, {
        "covenant_type": "INVESTMENT", "target_value": 100_000_000,
        "measurement_start_date": "2027-01-01T00:00:00.000Z",
        "measurement_end_date": "2027-12-31T00:00:00.000Z"}, DIRECTOR), expected_status=201)
    assert inv["covenant_type"] == "INVESTMENT"
    assert inv["status"] == "ACTIVE"


def test_covenant_target_below_minimum_returns_422(api):
    """PRD §3.4: "The `target_value` must meet or exceed the program's floor for its type — at
    least `min_jobs_required` for a `JOBS` covenant, or at least `min_investment_cents` for an
    `INVESTMENT` covenant — otherwise the request is rejected with
    `ERR_COVENANT_TARGET_BELOW_MINIMUM` (HTTP 422)." Target 5 < min_jobs_required 50.

    Design: Corner/validations/covenant_target_below_minimum_returns_422
    """
    ctx = setup_executed_agreement(app_overrides={"but_for_attested": True})
    resp = api.create_covenant(ctx["agreement"]["id"], {
        "covenant_type": "JOBS", "target_value": 5,
        "measurement_start_date": "2027-01-01T00:00:00.000Z",
        "measurement_end_date": "2027-12-31T00:00:00.000Z"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_COVENANT_TARGET_BELOW_MINIMUM)


def test_waive_met_covenant_returns_invalid_state(api):
    """PRD §3.4: "a director may waive a covenant that is `ACTIVE` or `BREACHED`, advancing it
    to `WAIVED` with an optional `reason`; waiving from any other state yields
    `ERR_COVENANT_INVALID_STATE`." The JOBS covenant is driven to terminal MET.

    Design: Corner/state_machines/waive_met_covenant_returns_invalid_state
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov_jobs = add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                            measurement_start_date="2027-01-01T00:00:00.000Z",
                            measurement_end_date="2027-12-31T00:00:00.000Z")
    # A second, unmet INVESTMENT covenant keeps the agreement ACTIVE after acceptance.
    add_covenant(agr_id, covenant_type="INVESTMENT", target_value=300_000_000,
                 measurement_start_date="2028-01-01T00:00:00.000Z",
                 measurement_end_date="2028-12-31T00:00:00.000Z")
    rep = submit_report(agr_id, actual_jobs=100, actual_investment_cents=150_000_000, attestation=True)
    accept_report(rep["id"])
    met = validate_success(api.get_covenant(cov_jobs["id"], DIRECTOR))
    assert met["status"] == "MET"
    validate_error(api.waive_covenant(cov_jobs["id"], DIRECTOR, {"reason": "n/a"}),
                   ApiErrorId.ERR_COVENANT_INVALID_STATE)
