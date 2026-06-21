"""Supervision posture: the ceiling-based required-supervision computation, the
inclusive boundary, and the payment gate keyed off supervision_status."""
from test_helpers import (
    get_success_data,
    validate_success,
    TEST_USERS,
    make_rbt_headers,
    make_bcba_headers,
    setup_active_authorization,
    schedule_session,
    deliver_session,
    deliver_supervision_units,
    get_authorization,
    create_submitted_claim,
)


def _deliver_direct(api, sc, units, start, end):
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_start=start, scheduled_end=end,
                               scheduled_units=units)
    return deliver_session(api, session["id"], sc["rbt"]["id"], "RBT", units)


# ─── Difficulty: ceiling discontinuity (81 direct, ratio 0.10 -> required 9) ──

def test_supervision_ceiling_jumps_required_from_eight_to_nine(api):
    """PRD §3.8: "the system takes the authorization's `delivered_direct_units`,
    multiplies by the payer's `supervision_ratio_pct`, and rounds that product up
    to the next whole unit to obtain the required supervision units."

    Design: Difficulty/combinatorial_formula/supervision_ratio_nonlinear_ceiling_over_three_inputs
    """
    sc = setup_active_authorization(api, authorized_direct_units=200,
                                    authorized_supervision_units=40)
    _deliver_direct(api, sc, 81, "2026-04-01T09:00:00Z", "2026-04-02T05:15:00Z")
    deliver_supervision_units(api, sc, scheduled_units=8, delivered_units=8,
                              scheduled_start="2026-04-02T09:00:00Z",
                              scheduled_end="2026-04-02T11:00:00Z")
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["delivered_direct_units"] == 81
    assert auth["delivered_supervision_units"] == 8
    # required = ceil(81 * 0.10) = 9, so 8 < 9 -> DEFICIENT.
    assert auth["supervision_status"] == "DEFICIENT", auth["supervision_status"]


def test_supervision_deficient_below_ratio_with_ceiling(api):
    """PRD §3.8: "If the authorization's `delivered_supervision_units` is greater
    than or equal to that required figure, the supervision status is `COMPLIANT`;
    otherwise it is `DEFICIENT`."

    Design: Difficulty/combinatorial_formula/supervision_ratio_nonlinear_ceiling_over_three_inputs
    """
    sc = setup_active_authorization(api, authorized_direct_units=200,
                                    authorized_supervision_units=40)
    _deliver_direct(api, sc, 81, "2026-04-01T09:00:00Z", "2026-04-02T05:15:00Z")
    deliver_supervision_units(api, sc, scheduled_units=8, delivered_units=8,
                              scheduled_start="2026-04-02T09:00:00Z",
                              scheduled_end="2026-04-02T11:00:00Z")
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["supervision_status"] == "DEFICIENT"


# ─── Difficulty: exact threshold gate on claim pay (80 direct -> required 8) ──

def test_supervision_exactly_at_required_is_compliant(api):
    """PRD §3.8: "The comparison is inclusive at the boundary — meeting the
    required figure exactly is compliant."

    Design: Difficulty/boundary_precision_check/supervision_ratio_exact_threshold_gate_on_claim_pay
    """
    sc = setup_active_authorization(api, authorized_direct_units=200,
                                    authorized_supervision_units=40)
    direct = _deliver_direct(api, sc, 80, "2026-09-01T09:00:00Z",
                             "2026-09-02T05:00:00Z")
    deliver_supervision_units(api, sc, scheduled_units=8, delivered_units=8,
                              scheduled_start="2026-09-03T09:00:00Z",
                              scheduled_end="2026-09-03T11:00:00Z")
    auth = get_authorization(api, sc["authorization"]["id"])
    # required = ceil(80 * 0.10) = 8, delivered supervision 8 >= 8 -> COMPLIANT.
    assert auth["delivered_supervision_units"] == 8
    assert auth["supervision_status"] == "COMPLIANT", auth["supervision_status"]
    sc["_direct"] = direct


def test_claim_pay_passes_at_exact_supervision_boundary(api):
    """PRD §3.9: "A decision of `PAY` is gated on supervision: the owning
    authorization's `supervision_status` must be `COMPLIANT`, or the payment is
    rejected with `ERR_SUPERVISION_DEFICIENT`."

    Design: Difficulty/boundary_precision_check/supervision_ratio_exact_threshold_gate_on_claim_pay
    """
    sc = setup_active_authorization(api, authorized_direct_units=200,
                                    authorized_supervision_units=40)
    direct = _deliver_direct(api, sc, 80, "2026-09-01T09:00:00Z",
                             "2026-09-02T05:00:00Z")
    deliver_supervision_units(api, sc, scheduled_units=8, delivered_units=8,
                              scheduled_start="2026-09-03T09:00:00Z",
                              scheduled_end="2026-09-03T11:00:00Z")
    claim = create_submitted_claim(api, direct["id"])
    resp = api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                                TEST_USERS["billing_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "PAID", data["status"]


# ─── Corner: supervision deficient when below ratio (50 direct, 4 supervision) ─

def test_supervision_deficient_with_four_below_required_five(api):
    """PRD §3.8: "If the authorization's `delivered_supervision_units` is greater
    than or equal to that required figure, the supervision status is `COMPLIANT`;
    otherwise it is `DEFICIENT`."

    Design: Corner/calculations/supervision_status_deficient_when_below_ratio
    """
    sc = setup_active_authorization(api, authorized_direct_units=200,
                                    authorized_supervision_units=40)
    _deliver_direct(api, sc, 50, "2026-02-02T09:00:00Z", "2026-02-02T21:30:00Z")
    deliver_supervision_units(api, sc, scheduled_units=4, delivered_units=4,
                              scheduled_start="2026-02-03T09:00:00Z",
                              scheduled_end="2026-02-03T10:00:00Z")
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["delivered_direct_units"] == 50
    assert auth["delivered_supervision_units"] == 4
    # required = ceil(50 * 0.10) = 5, delivered 4 < 5 -> DEFICIENT.
    assert auth["supervision_status"] == "DEFICIENT", auth["supervision_status"]
