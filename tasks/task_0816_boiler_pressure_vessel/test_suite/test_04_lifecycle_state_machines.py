"""State-machine behavior: the vessel's two parallel dimensions, the deficiency
reinspection cycle, invalid/idempotent transitions, segregation of duties, the FAIL
side effect, policy expiry gating, and the conserved deficiency counter.

Difficulty queue A: non_linear_state_machine, compensating_invariant (count).
Corner queue B: state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_inspector_headers,
    setup_registered_vessel, setup_certified_vessel, setup_deficiency_in_reinspection,
    new_jurisdiction, new_owner, new_inspector, commission, new_vessel,
    new_inspection, raise_deficiency, record_result,
    new_insurance_company, new_policy, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / vessel_parallel_dimensions_evolve_independently
# ---------------------------------------------------------------------------
def test_certificate_moves_service_axis_leaving_registration(api):
    """PRD §3.7: "When the certificate is a first issuance against a `NOT_IN_SERVICE`
    vessel that rests on a `PASSED` inspection with `open_critical_deficiency_count` at
    zero, the vessel's `service_status` advances `NOT_IN_SERVICE → IN_SERVICE` and its
    risk scores are recomputed."

    Design: Difficulty/non_linear_state_machine/vessel_parallel_dimensions_evolve_independently
    """
    ctx = setup_certified_vessel()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["service_status"] == "IN_SERVICE"


def test_registration_axis_stays_registered_independently(api):
    """PRD §2.9: "A vessel carries two **independent** status dimensions that evolve
    separately."
    PRD §2.9: "Registering a vessel changes only its registration axis and leaves it
    `NOT_IN_SERVICE`; putting a vessel into or out of service moves only the service axis."

    Design: Difficulty/non_linear_state_machine/vessel_parallel_dimensions_evolve_independently
    """
    ctx = setup_certified_vessel()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["registration_status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# non_linear_state_machine / deficiency_reinspect_cycle_returns_to_open
# ---------------------------------------------------------------------------
def test_failed_reinspection_returns_deficiency_to_open(api):
    """PRD §3.6: "`outcome` of FAIL returns the deficiency `REINSPECTION → OPEN` (the
    cyclic edge)."

    Design: Difficulty/non_linear_state_machine/deficiency_reinspect_cycle_returns_to_open
    """
    ctx = setup_deficiency_in_reinspection(severity="NON_CRITICAL")
    get_success_data(api.reinspect_deficiency(ctx["d1_id"], {"outcome": "FAIL"},
                                              make_inspector_headers(ctx["insp_b_id"])))
    data = validate_success(api.get_deficiency(ctx["d1_id"], ADMIN))
    assert data["status"] == "OPEN"


def test_failed_reinspection_clears_repair_order_id(api):
    """PRD §3.6: "It clears the deficiency's `repair_order_id` back to null so the owner
    may raise a fresh repair order, and it recomputes the risk scores."

    Design: Difficulty/non_linear_state_machine/deficiency_reinspect_cycle_returns_to_open
    """
    ctx = setup_deficiency_in_reinspection(severity="NON_CRITICAL")
    get_success_data(api.reinspect_deficiency(ctx["d1_id"], {"outcome": "FAIL"},
                                              make_inspector_headers(ctx["insp_b_id"])))
    data = validate_success(api.get_deficiency(ctx["d1_id"], ADMIN))
    assert data["repair_order_id"] is None


# ---------------------------------------------------------------------------
# Corner / state_machines
# ---------------------------------------------------------------------------
def test_reinspect_open_deficiency_returns_invalid_state(api):
    """PRD §3.6: "A reinspection is permitted only when the deficiency is in
    `REINSPECTION`; otherwise it fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reinspect_open_deficiency_returns_invalid_state
    """
    ctx = setup_registered_vessel()
    insp_b = new_inspector(ctx["jur_id"], name="Insp B", commission_number="NBC-B")
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="pitting")
    resp = api.reinspect_deficiency(d1["id"], {"outcome": "PASS"}, make_inspector_headers(insp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_revoke_already_revoked_certificate_returns_invalid_state(api):
    """PRD §3.7: "either transition attempted on a non-`ACTIVE` certificate fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revoke_already_revoked_certificate_returns_invalid_state
    """
    ctx = setup_certified_vessel()
    get_success_data(api.revoke_certificate(ctx["cert1_id"], ADMIN))
    resp = api.revoke_certificate(ctx["cert1_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_commission_already_commissioned_inspector_returns_invalid_state(api):
    """PRD §3.1: "attempting one from a state that does not permit it fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/commission_already_commissioned_inspector_returns_invalid_state
    """
    jur = new_jurisdiction()
    insp = new_inspector(jur["id"])
    commission(insp["id"])
    resp = api.commission_inspector(insp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reinspect_by_originating_inspector_returns_segregation(api):
    """PRD §3.6: "the acting inspector (`X-User-ID`) must not be the inspector of the
    deficiency's originating inspection, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/sod_reinspect_by_originating_inspector_returns_segregation
    """
    ctx = setup_deficiency_in_reinspection(severity="NON_CRITICAL")
    resp = api.reinspect_deficiency(ctx["d1_id"], {"outcome": "PASS"},
                                    make_inspector_headers(ctx["insp_a_id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_fail_inspection_sets_vessel_out_of_service(api):
    """PRD §3.5: "advances the inspection `SCHEDULED → FAILED`. It is permitted only when
    one or more `CRITICAL` deficiencies are attached."
    PRD §3.5: "as its divergent side effect it moves a vessel that is `IN_SERVICE` to
    `OUT_OF_SERVICE`".

    Design: Corner/state_machines/fail_inspection_sets_vessel_out_of_service
    """
    ctx = setup_certified_vessel()
    insp2 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL",
                           scheduled_start="2026-06-03T09:00:00Z", scheduled_end="2026-06-03T11:00:00Z")
    raise_deficiency(insp2["id"], ctx["insp_a_id"], severity="CRITICAL", description="shell crack")
    result = get_success_data(api.record_inspection_result(insp2["id"], {"result": "FAIL"},
                                                           make_inspector_headers(ctx["insp_a_id"])))
    assert result["status"] == "FAILED"
    vessel = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert vessel["service_status"] == "OUT_OF_SERVICE"


def test_policy_expire_before_coverage_end_returns_not_expirable(api):
    """PRD §3.3: "Expiry additionally requires that the logical clock now is strictly
    after `coverage_end` (past the inclusive closed-interval end); attempting to expire
    before that instant is rejected with `ERR_POLICY_NOT_EXPIRABLE`".

    Design: Corner/state_machines/policy_expire_before_coverage_end_returns_not_expirable
    """
    set_clock("2026-06-01T00:00:00Z")
    jur = new_jurisdiction()
    owner = new_owner()
    ins_x = new_insurance_company()
    vessel = new_vessel(owner["id"], jur["id"])
    pol1 = new_policy(vessel["id"], ins_x["id"], "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z")
    resp = api.expire_policy(pol1["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_EXPIRABLE.value)


# ---------------------------------------------------------------------------
# compensating_invariant / deficiency_count_conserved_on_raise_then_withdraw_count
# ---------------------------------------------------------------------------
def _raise_then_withdraw_ctx():
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="minor pitting")
    get_success_data(api_withdraw(d1["id"], ctx["insp_a_id"]))
    return ctx, d1


def api_withdraw(deficiency_id, inspector_id):
    from test_helpers.api_client import api_client
    return api_client.withdraw_deficiency(deficiency_id, make_inspector_headers(inspector_id))


def test_withdraw_returns_deficiency_to_terminal_withdrawn(api):
    """PRD §3.6: "Withdrawal advances the deficiency `OPEN → WITHDRAWN` (terminal), and
    as a compensating action for the original raise it decrements the vessel's
    `open_deficiency_count`".

    Design: Difficulty/compensating_invariant/deficiency_count_conserved_on_raise_then_withdraw_count
    """
    ctx, d1 = _raise_then_withdraw_ctx()
    data = validate_success(api.get_deficiency(d1["id"], ADMIN))
    assert data["status"] == "WITHDRAWN"


def test_open_deficiency_count_conserved_after_raise_then_withdraw(api):
    """PRD §3.5: "Raising it increments the vessel's `open_deficiency_count`". PRD §3.6:
    "as a compensating action for the original raise it decrements the vessel's
    `open_deficiency_count`".

    Design: Difficulty/compensating_invariant/deficiency_count_conserved_on_raise_then_withdraw_count
    """
    ctx, _d1 = _raise_then_withdraw_ctx()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["open_deficiency_count"] == 0
