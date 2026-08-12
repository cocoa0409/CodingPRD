"""Fraud signal accumulation, threshold gate, alert resolution and reversal."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_claim_payload, create_choice_disclosure_payload,
    make_policyholder_headers, make_shop,
    make_claim, verify_claim, route_claim,
    accept_work_order, schedule_work_order, complete_work_order,
    get_claim, get_policyholder, set_clock,
    setup_network,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


def _solicitation_disclosure(api, claim_id, policyholder_id):
    resp = api.create_choice_disclosure(
        claim_id,
        create_choice_disclosure_payload(
            disclosure_channel="IN_PERSON", shop_solicited=True,
            customer_selected_shop_name="Solo Glass"),
        make_policyholder_headers(policyholder_id))
    assert resp.status_code == 201, f"Setup failed (solicitation): {resp.text}"
    return resp


def _alerts_for_claim(api, claim_id):
    data, _meta = validate_paginated(
        api.list_fraud_alerts(INVESTIGATOR, params={"claim_id": claim_id}))
    return data


def _drive_to_score_110(api):
    """policyholder with score 110 and a claim parked in FRAUD_HOLD.

    c1 (no signal) -> solicitation +35 (35) -> c2 repeat-window +40 (75)
    -> solicitation +35 (110, crossing adds a SCORE_THRESHOLD alert on c2)
    -> c3 intake at 110 (>= 100) lands in FRAUD_HOLD with its own
    SCORE_THRESHOLD alert.
    """
    net = setup_network(with_shop=False, with_part=False)
    ph, pol = net["policyholder"], net["policy"]
    c1 = make_claim(ph, pol, loss_date="2026-02-01", description="f1",
                    estimated_repair_cost_cents=50000)
    _solicitation_disclosure(api, c1["id"], ph["id"])
    c2 = make_claim(ph, pol, loss_date="2026-03-01", description="f2",
                    estimated_repair_cost_cents=50000)
    _solicitation_disclosure(api, c2["id"], ph["id"])
    c3 = make_claim(ph, pol, loss_date="2026-04-01", description="f3",
                    estimated_repair_cost_cents=50000)
    return net, c3


class TestAlertResolution:
    def test_fraud_alert_resolve_twice_rejected(self, api):
        """PRD §3.6: "Investigation is performed by a `FraudInvestigator`
        resolving an `OPEN` alert (else `ERR_ALERT_NOT_OPEN`...)."
        PRD §3.6: "A `DISMISSED` resolution reverses the alert's
        `score_contribution` from the policyholder's `fraud_score`, floored at
        zero..."

        Design: Corner/state_machines/fraud_alert_resolve_twice_rejected
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        _solicitation_disclosure(api, claim["id"], net["policyholder"]["id"])
        alert_id = _alerts_for_claim(api, claim["id"])[0]["id"]
        first = api.resolve_fraud_alert(
            alert_id, {"resolution": "DISMISSED", "resolution_notes": "ok"},
            INVESTIGATOR)
        assert validate_success(first, 200)["status"] == "DISMISSED"
        again = api.resolve_fraud_alert(
            alert_id, {"resolution": "DISMISSED", "resolution_notes": "again"},
            INVESTIGATOR)
        validate_error(again, ApiErrorId.ERR_ALERT_NOT_OPEN)
        # Reversal applied exactly once (35 - 35, floor 0).
        assert get_policyholder(net["policyholder"]["id"])["fraud_score"] == 0

    def test_rbac_adjuster_cannot_resolve_fraud_alerts(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_adjuster_cannot_resolve_fraud_alerts
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        _solicitation_disclosure(api, claim["id"], net["policyholder"]["id"])
        alert_id = _alerts_for_claim(api, claim["id"])[0]["id"]
        resp = api.resolve_fraud_alert(
            alert_id, {"resolution": "DISMISSED",
                       "resolution_notes": "adjuster attempt"}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        alert = validate_success(api.get_fraud_alert(alert_id, INVESTIGATOR), 200)
        assert alert["status"] == "OPEN"


class TestSuspensionBarsFiling:
    def test_suspended_policyholder_cannot_file_claim(self, api):
        """PRD §3.2: "A policyholder whose `status` is `SUSPENDED` may not file;
        the attempt is rejected with `ERR_POLICYHOLDER_SUSPENDED` (HTTP 422)."
        PRD §3.6: "A `CONFIRMED` resolution on a `SCORE_THRESHOLD` alert whose
        linked claim sits in `FRAUD_HOLD` denies the claim ... and suspends the
        policyholder, moving their `status` to `SUSPENDED`, which bars further
        claim filings."

        Design: Corner/validations/suspended_policyholder_cannot_file_claim
        """
        net, c3 = _drive_to_score_110(api)
        alert_id = _alerts_for_claim(api, c3["id"])[0]["id"]
        api.resolve_fraud_alert(
            alert_id, {"resolution": "CONFIRMED",
                       "resolution_notes": "fraud confirmed"}, INVESTIGATOR)
        assert get_policyholder(net["policyholder"]["id"])["status"] == "SUSPENDED"
        resp = api.create_claim(
            create_claim_payload(net["policy"]["id"], loss_date="2026-04-20",
                                 description="sp4",
                                 estimated_repair_cost_cents=50000),
            make_policyholder_headers(net["policyholder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_POLICYHOLDER_SUSPENDED)


class TestFraudAlertListing:
    def test_fraud_alert_filtered_list(self, api):
        """PRD §3.6: "The alert list supports filtering by `policyholder_id`,
        `claim_id`, and `status`, and is visible to `ClaimAdjuster`,
        `NetworkAuditor`, `FraudInvestigator`, and `NetworkAdmin` readers."
        PRD §3.6: "The `SOLICITATION` signal, worth 35 points, fires when a
        choice disclosure is recorded with `shop_solicited` set to true."

        Design: Corner/endpoints/fraud_alert_filtered_list
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        _solicitation_disclosure(api, claim["id"], net["policyholder"]["id"])
        by_claim, meta = validate_paginated(api.list_fraud_alerts(
            INVESTIGATOR, params={"claim_id": claim["id"], "status": "OPEN"}))
        assert meta["total_count"] == 1
        assert by_claim[0]["alert_type"] == "SOLICITATION"
        assert by_claim[0]["score_contribution"] == 35
        by_ph, meta2 = validate_paginated(api.list_fraud_alerts(
            INVESTIGATOR, params={"policyholder_id": net["policyholder"]["id"]}))
        assert meta2["total_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: fraud threshold boundary at exactly 100
# ---------------------------------------------------------------------------

class TestFraudThresholdBoundary:
    def test_intake_below_100_proceeds_submitted(self, api):
        """PRD §3.2: "If the policyholder's `fraud_score` is already at least
        100 before the new claim's own signals are applied — the boundary is
        inclusive, so a score of exactly 100 triggers the hold — the new claim
        is created directly in `FRAUD_HOLD` status instead of `SUBMITTED`...
        Otherwise the claim begins life in `SUBMITTED`."

        Design: Difficulty/boundary_precision_check/fraud_score_threshold_at_exactly_100
        """
        net = setup_network(with_shop=False, with_part=False)
        ph, pol = net["policyholder"], net["policy"]
        c1 = make_claim(ph, pol, loss_date="2026-02-01", part_category="SIDE_GLASS",
                        description="pa1", estimated_repair_cost_cents=50000)
        _solicitation_disclosure(api, c1["id"], ph["id"])           # +35
        make_claim(ph, pol, loss_date="2026-03-01",
                   part_category="SIDE_GLASS", description="pa2",
                   estimated_repair_cost_cents=50000)               # +40 repeat
        assert get_policyholder(ph["id"])["fraud_score"] == 75
        pa3 = make_claim(ph, pol, loss_date="2026-04-01",
                         part_category="SIDE_GLASS", description="pa3",
                         estimated_repair_cost_cents=50000)
        assert pa3["status"] == "SUBMITTED"

    def test_intake_at_exactly_100_diverts_to_fraud_hold(self, api):
        """PRD §3.2: "If the policyholder's `fraud_score` is already at least
        100 before the new claim's own signals are applied — the boundary is
        inclusive, so a score of exactly 100 triggers the hold — the new claim
        is created directly in `FRAUD_HOLD` status instead of `SUBMITTED`, and a
        `SCORE_THRESHOLD` fraud alert with a zero point contribution is opened
        against it."

        Design: Difficulty/boundary_precision_check/fraud_score_threshold_at_exactly_100
        """
        net = setup_network(with_shop=False, with_part=False)
        shop = make_shop(shop_name="Edge Shop", bay_count=2)
        ph, pol = net["policyholder"], net["policy"]
        # +35 solicitation
        c1 = make_claim(ph, pol, loss_date="2026-02-01", description="pb1",
                        estimated_repair_cost_cents=50000)
        _solicitation_disclosure(api, c1["id"], ph["id"])
        # +25 rapid completion on the WINDSHIELD claim (30 min < 45)
        c1v = verify_claim(c1["id"])
        wo = route_claim(c1["id"], expected_claim_version=c1v["version"],
                         requested_shop_id=shop["id"])
        wo = accept_work_order(wo["id"], shop["id"])
        schedule_work_order(wo["id"], shop["id"],
                            start="2026-05-01T10:00:00Z",
                            end="2026-05-01T11:00:00Z",
                            expected_work_order_version=wo["version"])
        set_clock("2026-05-01T10:30:00Z")
        complete_work_order(wo["id"], shop["id"])
        # +40 repeat window -> 100
        make_claim(ph, pol, loss_date="2026-03-01", description="pb2",
                   estimated_repair_cost_cents=50000)
        assert get_policyholder(ph["id"])["fraud_score"] == 100
        pb3 = make_claim(ph, pol, loss_date="2026-04-01", description="pb3",
                         estimated_repair_cost_cents=50000)
        assert pb3["status"] == "FRAUD_HOLD"
        alerts = _alerts_for_claim(api, pb3["id"])
        threshold = [a for a in alerts if a["alert_type"] == "SCORE_THRESHOLD"]
        assert len(threshold) == 1
        assert threshold[0]["score_contribution"] == 0


# ---------------------------------------------------------------------------
# Difficulty: CONFIRMED threshold cascade
# ---------------------------------------------------------------------------

class TestFraudConfirmCascade:
    def test_fraud_hold_claim_denied_and_policyholder_suspended(self, api):
        """PRD §3.6: "A `CONFIRMED` resolution on a `SCORE_THRESHOLD` alert
        whose linked claim sits in `FRAUD_HOLD` denies the claim — moving it
        `FRAUD_HOLD` → `DENIED` — and suspends the policyholder, moving their
        `status` to `SUSPENDED`, which bars further claim filings."

        Design: Difficulty/transitive_cascade/fraud_confirm_suspends_policyholder_and_denies_claim_depth2
        """
        net, c3 = _drive_to_score_110(api)
        assert c3["status"] == "FRAUD_HOLD"
        alert_id = _alerts_for_claim(api, c3["id"])[0]["id"]
        resp = api.resolve_fraud_alert(
            alert_id, {"resolution": "CONFIRMED",
                       "resolution_notes": "confirmed fraud ring"}, INVESTIGATOR)
        assert validate_success(resp, 200)["status"] == "CONFIRMED"
        assert get_claim(c3["id"])["status"] == "DENIED"
        assert get_policyholder(net["policyholder"]["id"])["status"] == "SUSPENDED"

    def test_confirmed_resolution_does_not_reverse_score(self, api):
        """PRD §3.6: "A `DISMISSED` resolution reverses the alert's
        `score_contribution` from the policyholder's `fraud_score`, floored at
        zero..." (only DISMISSED reverses; CONFIRMED leaves the score in place.)

        Design: Difficulty/transitive_cascade/fraud_confirm_suspends_policyholder_and_denies_claim_depth2
        """
        net, c3 = _drive_to_score_110(api)
        before = get_policyholder(net["policyholder"]["id"])["fraud_score"]
        assert before >= 110
        alert_id = _alerts_for_claim(api, c3["id"])[0]["id"]
        api.resolve_fraud_alert(
            alert_id, {"resolution": "CONFIRMED",
                       "resolution_notes": "confirmed fraud ring"}, INVESTIGATOR)
        assert get_policyholder(net["policyholder"]["id"])["fraud_score"] == before


# ---------------------------------------------------------------------------
# Difficulty: fraud score conservation under signal + dismissal
# ---------------------------------------------------------------------------

class TestFraudScoreConservation:
    def test_solicitation_signal_adds_exactly_35(self, api):
        """PRD §3.6: "The `SOLICITATION` signal, worth 35 points, fires when a
        choice disclosure is recorded with `shop_solicited` set to true."

        Design: Difficulty/compensating_invariant/fraud_score_conservation_signal_dismiss_reversal
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        _solicitation_disclosure(api, claim["id"], net["policyholder"]["id"])
        assert get_policyholder(net["policyholder"]["id"])["fraud_score"] == 35
        alert = _alerts_for_claim(api, claim["id"])[0]
        assert alert["alert_type"] == "SOLICITATION"
        assert alert["score_contribution"] == 35
        assert alert["status"] == "OPEN"

    def test_dismissal_reverses_signal_exactly(self, api):
        """PRD §3.6: "A `DISMISSED` resolution reverses the alert's
        `score_contribution` from the policyholder's `fraud_score`, floored at
        zero; when the dismissed alert is a `SCORE_THRESHOLD` alert whose linked
        claim sits in `FRAUD_HOLD`, the claim is released back to `SUBMITTED`."

        Design: Difficulty/compensating_invariant/fraud_score_conservation_signal_dismiss_reversal
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        _solicitation_disclosure(api, claim["id"], net["policyholder"]["id"])
        alert_id = _alerts_for_claim(api, claim["id"])[0]["id"]
        resp = api.resolve_fraud_alert(
            alert_id, {"resolution": "DISMISSED",
                       "resolution_notes": "legitimate referral"}, INVESTIGATOR)
        assert validate_success(resp, 200)["status"] == "DISMISSED"
        # 35 - 35: exact reversal, no drift.
        assert get_policyholder(net["policyholder"]["id"])["fraud_score"] == 0
        assert get_claim(claim["id"])["status"] == "SUBMITTED"
