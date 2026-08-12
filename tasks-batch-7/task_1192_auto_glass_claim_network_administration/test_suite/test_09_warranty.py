"""Warranty claims: filing window, open-claim uniqueness, strikes, suspension."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_warranty_claim_payload, decide_warranty_payload,
    make_policyholder_headers, make_shop_operator_headers,
    make_claim, add_disclosure, verify_claim, route_claim,
    accept_work_order, schedule_work_order, complete_work_order,
    get_shop, set_clock,
    setup_network, setup_work_order_completed, setup_warranty_filed,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _file_warranty(api, work_order_id, policyholder_id, description="leak"):
    return api.create_warranty_claim(
        work_order_id, create_warranty_claim_payload(issue_description=description),
        make_policyholder_headers(policyholder_id))


class TestWarrantyFilingWindow:
    def test_warranty_in_shop_window_730_days(self, api):
        """PRD §3.7: "The warranty window depends on how the service was
        delivered: three hundred sixty-five days after completion for `MOBILE`
        service, seven hundred thirty days for `IN_SHOP` service. Filing at or
        before the completion timestamp plus the window is allowed — the
        boundary is inclusive — while filing later is rejected with
        `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/calculations/warranty_in_shop_window_730_days
        """
        ctx = setup_work_order_completed(
            service_mode="IN_SHOP",
            start="2026-05-01T10:00:00Z", end="2026-05-01T11:00:00Z",
            complete_at="2026-05-01T12:00:00Z",
            claim_overrides={"part_category": "SIDE_GLASS"},
        )
        # 400 days after completion: past the 365-day MOBILE window but well
        # inside the 730-day IN_SHOP window.
        set_clock("2027-06-05T12:00:00Z")
        resp = _file_warranty(api, ctx["work_order"]["id"],
                              ctx["policyholder"]["id"],
                              "400 days later, still within 730d IN_SHOP window")
        assert validate_success(resp, 201)["status"] == "FILED"

    def test_second_open_warranty_claim_rejected(self, api):
        """PRD §3.7: "A second warranty claim while another for the same work
        order is still `FILED` or `APPROVED_REWORK` is rejected with
        `ERR_WARRANTY_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/second_open_warranty_claim_rejected
        """
        ctx = setup_warranty_filed(
            claim_overrides={"part_category": "SIDE_GLASS"})
        resp = _file_warranty(api, ctx["work_order"]["id"],
                              ctx["policyholder"]["id"],
                              "second while first open")
        validate_error(resp, ApiErrorId.ERR_WARRANTY_ALREADY_OPEN)
        _data, meta = validate_paginated(api.list_work_order_warranty_claims(
            ctx["work_order"]["id"], ADMIN))
        assert meta["total_count"] == 1


class TestWarrantyDecide:
    def test_warranty_decide_from_approved_rejected(self, api):
        """PRD §3.7: "A `NetworkAuditor` decides a `FILED` warranty claim (else
        `ERR_WARRANTY_NOT_FILED`...)."
        PRD §3.7: "Approving rework moves it to `APPROVED_REWORK` ... the
        responsible shop's `warranty_strike_count` increments by one..."

        Design: Corner/state_machines/warranty_decide_from_approved_rejected
        """
        ctx = setup_warranty_filed(
            claim_overrides={"part_category": "SIDE_GLASS"})
        first = api.decide_warranty_claim(
            ctx["warranty_claim"]["id"],
            decide_warranty_payload("APPROVE_REWORK", decision_notes="approve"),
            AUDITOR)
        assert validate_success(first, 200)["status"] == "APPROVED_REWORK"
        again = api.decide_warranty_claim(
            ctx["warranty_claim"]["id"],
            decide_warranty_payload("DENY", decision_notes="second decide"),
            AUDITOR)
        validate_error(again, ApiErrorId.ERR_WARRANTY_NOT_FILED)
        assert get_shop(ctx["shop"]["id"])["warranty_strike_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: warranty filing deadline boundary (MOBILE 365 days, inclusive)
# ---------------------------------------------------------------------------

class TestWarrantyWindowBoundary:
    def _setup_mobile_completed(self):
        """MOBILE work order completed at exactly 2026-05-01T12:00:00Z."""
        return setup_work_order_completed(
            service_mode="MOBILE",
            start="2026-05-01T10:00:00Z", end="2026-05-01T11:00:00Z",
            complete_at="2026-05-01T12:00:00Z",
            shop_overrides={"mobile_capable": True, "mobile_unit_count": 1},
        )

    def test_filing_exactly_at_deadline_allowed(self, api):
        """PRD §3.7: "Filing at or before the completion timestamp plus the
        window is allowed — the boundary is inclusive — while filing later is
        rejected with `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_window_inclusive_deadline
        """
        ctx = self._setup_mobile_completed()
        # Deadline: 2026-05-01T12:00:00Z + 365 days = 2027-05-01T12:00:00Z.
        set_clock("2027-05-01T12:00:00Z")
        resp = _file_warranty(api, ctx["work_order"]["id"],
                              ctx["policyholder"]["id"], "at deadline")
        assert validate_success(resp, 201)["status"] == "FILED"

    def test_filing_one_second_past_deadline_rejected(self, api):
        """PRD §3.7: "Filing at or before the completion timestamp plus the
        window is allowed — the boundary is inclusive — while filing later is
        rejected with `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_window_inclusive_deadline
        """
        ctx = self._setup_mobile_completed()
        set_clock("2027-05-01T12:00:01Z")  # one second past the deadline
        resp = _file_warranty(api, ctx["work_order"]["id"],
                              ctx["policyholder"]["id"], "one second late")
        validate_error(resp, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED)


# ---------------------------------------------------------------------------
# Difficulty: warranty strike -> shop suspension cascade (depth 3)
# ---------------------------------------------------------------------------

def _complete_work_order_on_shop(api, net, shop, description, date, hour):
    """File a claim, route to shop, accept, schedule, complete. Returns WO."""
    claim = make_claim(net["policyholder"], net["policy"],
                       part_category="SIDE_GLASS", loss_date=date,
                       description=description, estimated_repair_cost_cents=80000)
    add_disclosure(claim["id"], net["policyholder"]["id"])
    verified = verify_claim(claim["id"])
    wo = route_claim(claim["id"], expected_claim_version=verified["version"],
                     requested_shop_id=shop["id"])
    wo = accept_work_order(wo["id"], shop["id"])
    schedule_work_order(wo["id"], shop["id"],
                        start=f"2026-05-01T{hour:02d}:00:00Z",
                        end=f"2026-05-01T{hour + 1:02d}:00:00Z",
                        expected_work_order_version=wo["version"])
    # Logical clock must reach scheduled_start before completion.
    set_clock(f"2026-05-01T{hour + 2:02d}:00:00Z")
    complete_work_order(wo["id"], shop["id"])
    return wo


def _file_and_approve_warranty(api, net, wo):
    resp = _file_warranty(api, wo["id"], net["policyholder"]["id"])
    wc = validate_success(resp, 201)
    decided = api.decide_warranty_claim(
        wc["id"], decide_warranty_payload("APPROVE_REWORK"), AUDITOR)
    return validate_success(decided, 200)


class TestWarrantyStrikeSuspensionCascade:
    def _setup_three_strikes_pending(self, api):
        """Shop with warranty_strike_count == 2 and a third filed warranty
        claim; also a fresh OFFERED work order on the shop to probe the block."""
        net = setup_network(
            shop_overrides={"bay_count": 2})
        shop = net["shop"]
        set_clock("2026-05-01T08:00:00Z")
        wo1 = _complete_work_order_on_shop(api, net, shop, "w1", "2026-04-01", 9)
        _file_and_approve_warranty(api, net, wo1)          # strike 1
        wo2 = _complete_work_order_on_shop(api, net, shop, "w2", "2026-04-02", 13)
        _file_and_approve_warranty(api, net, wo2)          # strike 2
        wo3 = _complete_work_order_on_shop(api, net, shop, "w3", "2026-04-03", 15)
        resp = _file_warranty(api, wo3["id"], net["policyholder"]["id"], "leak 3")
        wc3 = validate_success(resp, 201)
        # Fresh claim routed to the same shop, work order OFFERED.
        c4 = make_claim(net["policyholder"], net["policy"],
                        part_category="SIDE_GLASS", loss_date="2026-04-04",
                        description="w4", estimated_repair_cost_cents=80000)
        add_disclosure(c4["id"], net["policyholder"]["id"])
        c4v = verify_claim(c4["id"])
        w4 = route_claim(c4["id"], expected_claim_version=c4v["version"],
                         requested_shop_id=shop["id"])
        return net, shop, wc3, w4

    def test_third_strike_suspends_shop(self, api):
        """PRD §3.7: "Approving rework moves it to `APPROVED_REWORK` and has
        three effects: a rework work order is created against the same claim and
        the same shop as the original work order, with its `warranty_claim_id`
        pointing back to this warranty claim and its `status` `OFFERED`; the
        responsible shop's `warranty_strike_count` increments by one; and when
        that count reaches three, the shop's `network_status` is moved to
        `SUSPENDED`, removing it from selector eligibility and blocking new
        acceptances."

        Design: Difficulty/transitive_cascade/warranty_strike_suspension_cascade_depth3
        """
        net, shop, wc3, _w4 = self._setup_three_strikes_pending(api)
        resp = api.decide_warranty_claim(
            wc3["id"], decide_warranty_payload("APPROVE_REWORK",
                                               decision_notes="fix 3"), AUDITOR)
        validate_success(resp, 200)
        shop_after = get_shop(shop["id"])
        assert shop_after["warranty_strike_count"] == 3
        assert shop_after["network_status"] == "SUSPENDED"
        # The rework work order exists and points back to the warranty claim.
        rework, meta = validate_paginated(
            api.list_warranty_work_orders(wc3["id"], ADMIN))
        assert meta["total_count"] == 1
        assert rework[0]["warranty_claim_id"] == wc3["id"]
        assert rework[0]["status"] == "OFFERED"

    def test_suspended_shop_blocks_acceptance(self, api):
        """PRD §3.4: "provided the shop's `network_status` is `ACTIVE` (a
        suspended shop's acceptance is rejected with `ERR_SHOP_SUSPENDED`,
        HTTP 409)..."

        Design: Difficulty/transitive_cascade/warranty_strike_suspension_cascade_depth3
        """
        _net, shop, wc3, w4 = self._setup_three_strikes_pending(api)
        api.decide_warranty_claim(
            wc3["id"], decide_warranty_payload("APPROVE_REWORK",
                                               decision_notes="fix 3"), AUDITOR)
        resp = api.accept_work_order(
            w4["id"], make_shop_operator_headers(shop["id"]))
        validate_error(resp, ApiErrorId.ERR_SHOP_SUSPENDED)
