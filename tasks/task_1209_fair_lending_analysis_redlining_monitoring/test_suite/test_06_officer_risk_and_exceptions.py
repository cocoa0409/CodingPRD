"""Officer risk scorecard, exception tier cascade, and ledger conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_application_rows,
    create_confirmed_override,
    create_pricing_exception,
    make_loan_officer_headers,
    setup_market_branch_officer,
    setup_officer_at_watch_65,
    validate_applications,
    validate_error,
    validate_success,
)

def _scorecard(api, officer_id):
    return validate_success(
        api.get_risk_scorecard(officer_id, TEST_USERS["analyst_headers"])
    )


def test_officer_risk_score_two_signal_watch_state(api, officer_headers):
    """PRD §3.1: "The override rate is the officer's
    `confirmed_override_count` divided by A; it contributes 40 points
    times the lesser of 1 and the override rate divided by 0.20."
    PRD §3.1: "Analysts, officers, and directors can read any officer's
    current posture through the risk scorecard, which reports
    `application_count`, `confirmed_override_count`, `override_rate`,
    `approved_exception_count`, `exception_approval_rate`,
    `pricing_dispersion_bps`, `risk_score`, and `monitoring_tier`."

    Design: Difficulty/combinatorial_formula/officer_risk_score_multicomponent_tiers
    """
    _market, _branch, officer, _apps, _ovs = setup_officer_at_watch_65()
    card = _scorecard(api, officer["id"])
    assert card["confirmed_override_count"] == 2
    assert card["override_rate"] == pytest.approx(0.20, abs=1e-9)
    assert card["pricing_dispersion_bps"] == pytest.approx(70, abs=1e-9)
    assert card["risk_score"] == pytest.approx(65.00, abs=1e-2), (
        f"2 overrides over 10 apps with dispersion 70: 40 + 0 + 25, got "
        f"{card['risk_score']}"
    )
    assert card["monitoring_tier"] == "WATCH"


def test_officer_risk_score_third_signal_binds_cap_at_red(api, officer_headers):
    """PRD §3.1: "The score is the sum of the three contributions, capped
    at 100, then rounded half-up to 2 decimal places. Tiering evaluates
    the rounded score: at least 70 is `RED`, at least 40 but below 70 is
    `WATCH`, and below 40 is `GREEN`."
    PRD §3.6: "Approval moves the exception to `APPROVED`, stamps
    `decided_by_user_id` and `decided_at`, flips the application's
    `has_exception` to `APPROVED` (which excludes the row from the
    exception-adjusted pricing spread), increments the officer's
    `approved_exception_count`, and recomputes the officer's risk".

    Design: Difficulty/combinatorial_formula/officer_risk_score_multicomponent_tiers
    """
    _market, _branch, officer, apps, _ovs = setup_officer_at_watch_65()
    exception = create_pricing_exception(
        apps["a7"]["id"], officer["id"], kind="RATE_ABOVE_CAP",
        requested_rate_bps=770, justification="strategic relationship",
    )
    pre = _scorecard(api, officer["id"])
    assert pre["risk_score"] == pytest.approx(65.00, abs=1e-2)
    assert pre["monitoring_tier"] == "WATCH"
    approved = validate_success(
        api.approve_pricing_exception(exception["id"], officer_headers)
    )
    assert approved["status"] == "APPROVED"
    post = _scorecard(api, officer["id"])
    assert post["override_rate"] == pytest.approx(0.20, abs=1e-9)
    assert post["exception_approval_rate"] == pytest.approx(0.10, abs=1e-9)
    assert post["pricing_dispersion_bps"] == pytest.approx(70, abs=1e-9)
    assert post["risk_score"] == pytest.approx(100.00, abs=1e-2), (
        f"40 + 35 + 25 = 100, outer cap binds, got {post['risk_score']}"
    )
    assert post["monitoring_tier"] == "RED"
    app_now = validate_success(
        api.get_application(apps["a7"]["id"], TEST_USERS["data_ops_headers"])
    )
    assert app_now["has_exception"] == "APPROVED"


def test_exception_approve_cascades_red_crossing_to_sibling_escalation(
    api, officer_headers
):
    """PRD §2.10: "An upward crossing of an officer's monitoring tier into
    `RED` escalates every one of that officer's pricing exceptions still
    sitting in `REQUESTED` to `ESCALATED` — a one-way ratchet, since a
    later downward tier move never returns an `ESCALATED` exception to
    `REQUESTED`."

    Design: Difficulty/transitive_cascade/exception_approve_to_tier_red_to_exception_escalation
    """
    _market, _branch, officer, apps, _ovs = setup_officer_at_watch_65()
    e1 = create_pricing_exception(
        apps["a7"]["id"], officer["id"], kind="RATE_ABOVE_CAP",
        requested_rate_bps=770, justification="strategic relationship",
    )
    e2 = create_pricing_exception(
        apps["a6"]["id"], officer["id"], kind="FEE_WAIVER",
        requested_rate_bps=700, justification="fee concession",
    )
    approved = validate_success(
        api.approve_pricing_exception(e1["id"], officer_headers)
    )
    assert approved["status"] == "APPROVED"
    card = _scorecard(api, officer["id"])
    assert card["risk_score"] == pytest.approx(100.00, abs=1e-2)
    assert card["monitoring_tier"] == "RED", "crossed upward from WATCH 65.00"
    e2_now = validate_success(
        api.get_pricing_exception(e2["id"], officer_headers)
    )
    assert e2_now["status"] == "ESCALATED", (
        f"sibling REQUESTED exception escalates on the RED crossing, got "
        f"{e2_now['status']}"
    )


def test_escalated_exception_requires_director_approval(api, officer_headers):
    """PRD §2.9: "The three heightened cases are approving a pricing
    exception whose owning officer sits in the `RED` monitoring tier,
    approving an exception already in `ESCALATED` status, and approving a
    corrective action plan whose `pool_cents` is at least 25000000 cents.
    Any other actor attempting one of these is rejected with
    `ERR_DIRECTOR_APPROVAL_REQUIRED` (HTTP 403)."

    Design: Difficulty/transitive_cascade/exception_approve_to_tier_red_to_exception_escalation
    """
    _market, _branch, officer, apps, _ovs = setup_officer_at_watch_65()
    e1 = create_pricing_exception(
        apps["a7"]["id"], officer["id"], kind="RATE_ABOVE_CAP",
        requested_rate_bps=770, justification="strategic relationship",
    )
    e2 = create_pricing_exception(
        apps["a6"]["id"], officer["id"], kind="FEE_WAIVER",
        requested_rate_bps=700, justification="fee concession",
    )
    validate_success(api.approve_pricing_exception(e1["id"], officer_headers))
    e2_now = validate_success(api.get_pricing_exception(e2["id"], officer_headers))
    assert e2_now["status"] == "ESCALATED"
    resp = api.approve_pricing_exception(e2["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_DIRECTOR_APPROVAL_REQUIRED,
                   expected_status=403)
    ok = api.approve_pricing_exception(e2["id"], TEST_USERS["director_headers"])
    data = validate_success(ok)
    assert data["status"] == "APPROVED"


def test_officer_ledger_counts_conserved_under_rescind(api, officer_headers,
                                                       analyst_headers):
    """PRD §3.6: "Rescission is the compensating officer act on an
    `APPROVED` exception: it is blocked when the application sits frozen in
    a `FINALIZED` or `ARCHIVED` snapshot (`ERR_APPLICATION_LOCKED`), and
    otherwise moves the exception to terminal `RESCINDED`, returns
    `has_exception` to `NONE`, decrements `approved_exception_count`, and
    recomputes risk — deliberately without un-escalating any of the
    officer's other `ESCALATED` exceptions, since the ratchet is one-way."

    Design: Difficulty/compensating_invariant/officer_ledger_counts_conserved_under_rescind_and_reverse
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"],
                             credit_score=720)
    validate_applications([app["id"]])
    exception = create_pricing_exception(app["id"], officer["id"])
    baseline = _scorecard(api, officer["id"])
    assert baseline["approved_exception_count"] == 0
    assert baseline["risk_score"] == pytest.approx(0.0, abs=1e-9)
    validate_success(api.approve_pricing_exception(exception["id"], officer_headers))
    mid = _scorecard(api, officer["id"])
    assert mid["approved_exception_count"] == 1
    assert mid["risk_score"] == pytest.approx(35.00, abs=1e-2), (
        f"exception rate 1/1 contributes 35 x 1.0, got {mid['risk_score']}"
    )
    validate_success(api.rescind_pricing_exception(exception["id"], officer_headers))
    end = _scorecard(api, officer["id"])
    assert end["approved_exception_count"] == 0, "rescind decrements the count"
    assert end["risk_score"] == pytest.approx(0.0, abs=1e-9), (
        "ledger restored exactly: no drift in the conserved count"
    )
    assert end["monitoring_tier"] == "GREEN"


def test_officer_ledger_counts_conserved_under_reverse(api, officer_headers):
    """PRD §3.6: "Reversal is the compensating act: from `RECORDED` it
    simply moves to terminal `REVERSED`; from `CONFIRMED` it additionally
    decrements `confirmed_override_count` and recomputes risk."

    Design: Difficulty/compensating_invariant/officer_ledger_counts_conserved_under_rescind_and_reverse
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"],
                             credit_score=720)
    validate_applications([app["id"]])
    override = validate_success(
        api.create_underwriting_override(
            {"application_id": app["id"], "original_decision": "DENY",
             "overridden_decision": "APPROVE",
             "justification": "compensating factors"},
            make_loan_officer_headers(officer["id"]),
        ),
        expected_status=201,
    )
    baseline = _scorecard(api, officer["id"])
    assert baseline["confirmed_override_count"] == 0
    assert baseline["risk_score"] == pytest.approx(0.0, abs=1e-9)
    validate_success(
        api.confirm_underwriting_override(override["id"], officer_headers)
    )
    mid = _scorecard(api, officer["id"])
    assert mid["confirmed_override_count"] == 1
    assert mid["risk_score"] == pytest.approx(40.00, abs=1e-2), (
        f"override rate 1/1 contributes 40 x 1.0, got {mid['risk_score']}"
    )
    assert mid["monitoring_tier"] == "WATCH", "40.00 meets the WATCH floor"
    validate_success(
        api.reverse_underwriting_override(
            override["id"], {"reason": "documented error"}, officer_headers
        )
    )
    end = _scorecard(api, officer["id"])
    assert end["confirmed_override_count"] == 0, "reverse decrements the count"
    assert end["risk_score"] == pytest.approx(0.0, abs=1e-9)
    assert end["monitoring_tier"] == "GREEN"


def test_officer_watch_boundary_exactly_40(api, officer_headers):
    """PRD §3.1: "Tiering evaluates the rounded score: at least 70 is
    `RED`, at least 40 but below 70 is `WATCH`, and below 40 is `GREEN`."

    Design: Corner/calculations/officer_watch_boundary_exactly_40
    """
    market, branch, officer = setup_market_branch_officer()
    rows = [
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED",
         "note_rate_bps": 700, "credit_score": 720 + i}
        for i in range(10)
    ]
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    create_confirmed_override(apps[0]["id"], officer["id"])
    card1 = _scorecard(api, officer["id"])
    assert card1["risk_score"] == pytest.approx(20.00, abs=1e-2), (
        f"1 override over 10 apps: 40 x 0.5, got {card1['risk_score']}"
    )
    assert card1["monitoring_tier"] == "GREEN", "below 40 stays GREEN"
    create_confirmed_override(apps[1]["id"], officer["id"])
    card2 = _scorecard(api, officer["id"])
    assert card2["risk_score"] == pytest.approx(40.00, abs=1e-2)
    assert card2["monitoring_tier"] == "WATCH", (
        "the WATCH floor is inclusive: exactly 40.00 lands WATCH"
    )


def test_suspended_officer_blocked_from_exception_create(
    api, director_headers, data_ops_headers
):
    """PRD §3.6: "Creation requires the application to be `VALIDATED` and
    the owning officer `ACTIVE` — a suspended officer's attempt is rejected
    with `ERR_OFFICER_SUSPENDED`".
    PRD §3.6: "The record lands in `RECORDED` with `loan_officer_id`
    copied from the application; the suspended-officer block applies at
    creation."

    Design: Corner/validations/suspended_officer_blocked_from_exception_create
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    validate_success(api.suspend_loan_officer(officer["id"], director_headers))
    resp1 = api.create_pricing_exception(
        {"application_id": app["id"], "kind": "FEE_WAIVER",
         "requested_rate_bps": 700, "justification": "fee"},
        make_loan_officer_headers(officer["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_OFFICER_SUSPENDED, expected_status=409)
    resp2 = api.create_underwriting_override(
        {"application_id": app["id"], "original_decision": "DENY",
         "overridden_decision": "APPROVE", "justification": "comp factors"},
        make_loan_officer_headers(officer["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_OFFICER_SUSPENDED, expected_status=409)


def test_override_invalid_decision_pair(api):
    """PRD §3.6: "An officer records an override on an own `VALIDATED`
    application with `original_decision` and `overridden_decision` each
    drawn from `APPROVE` or `DENY` — and the two must differ, since an
    override that does not flip the decision is rejected with
    `ERR_INVALID_DECISION_PAIR` (HTTP 422) — plus a `justification`."

    Design: Corner/validations/override_invalid_decision_pair
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    resp = api.create_underwriting_override(
        {"application_id": app["id"], "original_decision": "DENY",
         "overridden_decision": "DENY", "justification": "not a flip"},
        make_loan_officer_headers(officer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DECISION_PAIR, expected_status=422)


def test_immediate_consistency_read_after_write(api, officer_headers,
                                                data_ops_headers):
    """PRD §3.6: "Approval moves the exception to `APPROVED`, stamps
    `decided_by_user_id` and `decided_at`, flips the application's
    `has_exception` to `APPROVED` (which excludes the row from the
    exception-adjusted pricing spread), increments the officer's
    `approved_exception_count`, and recomputes the officer's risk — and if
    that recompute crosses upward into `RED`, every other `REQUESTED`
    exception of the same officer escalates to `ESCALATED`."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    exception = create_pricing_exception(app["id"], officer["id"])
    approved = validate_success(
        api.approve_pricing_exception(exception["id"], officer_headers)
    )
    assert approved["status"] == "APPROVED", (
        "the approve response body already shows APPROVED"
    )
    assert approved.get("decided_by_user_id"), (
        "decided_by_user_id visible in the same request"
    )
    got = validate_success(
        api.get_pricing_exception(exception["id"], officer_headers)
    )
    assert got["status"] == "APPROVED"
    app_now = validate_success(api.get_application(app["id"], data_ops_headers))
    assert app_now["has_exception"] == "APPROVED"
    card = _scorecard(api, officer["id"])
    assert card["approved_exception_count"] == 1, (
        "scorecard reflects the approval with no reconciliation lag"
    )
