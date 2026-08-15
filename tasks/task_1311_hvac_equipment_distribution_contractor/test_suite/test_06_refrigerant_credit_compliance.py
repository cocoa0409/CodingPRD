"""Refrigerant cylinder lifecycle, heel compliance, and the fiscal/compliance gates."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    make_contractor, make_cylinder, make_model, make_prebuy_program,
    setup_issued_cylinder, issue_cylinder, return_cylinder, get_contractor,
    create_draft_order, add_line, submit_order, set_clock, get_order,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def test_cylinder_initial_state_and_issue_cycle(api):
    """PRD §3.7: "A freshly registered cylinder is `IN_STOCK` with `current_weight_lbs` initialized to its full weight, no holder, and `issued_at` empty."
    PRD §3.7: "Issuing moves `IN_STOCK` → `ISSUED`, sets `holder_contractor_id` to the contractor, stamps `issued_at` from the clock, and appends a ledger entry of kind `ISSUE` with a zero weight delta."

    Design: Corner/state_machines/cylinder_initial_state_and_issue_cycle
    """
    contractor = make_contractor(license_number="LIC-C202")
    cylinder = make_cylinder(cylinder_tag="CYL-C202", refrigerant_type="R454B",
                             tare_weight_lbs=22.00, full_weight_lbs=55.00)
    assert cylinder["status"] == "IN_STOCK"
    assert cylinder["current_weight_lbs"] == pytest.approx(55.00)
    assert cylinder.get("holder_contractor_id") in (None, "")
    issued = issue_cylinder(cylinder["id"], contractor["id"])
    assert issued["status"] == "ISSUED"
    assert issued["holder_contractor_id"] == contractor["id"]
    assert issued.get("issued_at"), "issued_at must be stamped from the logical clock"
    events, _ = validate_paginated(api.list_cylinder_events(cylinder["id"], ADMIN))
    assert len(events) == 1
    assert events[0]["event_type"] == "ISSUE"
    assert events[0]["weight_delta_lbs"] == pytest.approx(0.00)


class TestHeelShortfallBoundary:
    """Full weight 50.00; ninety percent is exactly 45.00."""

    def test_return_at_exactly_ninety_percent_is_not_shortfall(self, api):
        """PRD §3.7: "The return also runs the **heel check**: a cylinder returned below ninety percent of its full weight — a heel shortfall exceeding ten percent of the charge — appends a further `ADJUSTMENT` entry whose `note` carries the marker text `HEEL_SHORTFALL`, and increments the holder's `heel_violation_count_12m`, counted over a rolling twelve-month window of the logical clock."

        Design: Corner/calculations/refrigerant_heel_shortfall_exact_boundary
        """
        ctx = setup_issued_cylinder(tare=20.00, full=50.00)
        contractor, cylinder = ctx["contractor"], ctx["cylinder"]
        returned = return_cylinder(cylinder["id"], 45.00)
        assert returned["status"] == "RETURNED"
        events, _ = validate_paginated(api.list_cylinder_events(cylinder["id"], ADMIN))
        assert not any(e.get("note") == "HEEL_SHORTFALL" for e in events), (
            "45.00 is exactly ninety percent — not below — so no shortfall may be recorded")
        contractor = get_contractor(contractor["id"])
        assert contractor["compliance_standing"] == "GOOD"
        assert contractor["heel_violation_count_12m"] == 0

    def test_return_below_ninety_percent_flags_watch(self, api):
        """PRD §3.7: "The return also runs the **heel check**: a cylinder returned below ninety percent of its full weight — a heel shortfall exceeding ten percent of the charge — appends a further `ADJUSTMENT` entry whose `note` carries the marker text `HEEL_SHORTFALL`, and increments the holder's `heel_violation_count_12m`, counted over a rolling twelve-month window of the logical clock."
        PRD §3.7: "The standing then recomputes: two or more heel violations inside the window force `HOLD`; exactly one forces `WATCH`."

        Design: Corner/calculations/refrigerant_heel_shortfall_exact_boundary
        """
        ctx = setup_issued_cylinder(tare=20.00, full=50.00)
        contractor, cylinder = ctx["contractor"], ctx["cylinder"]
        return_cylinder(cylinder["id"], 45.00)  # exactly 90%: no shortfall
        validate_success(api.refill_cylinder(cylinder["id"], ADMIN), 200)
        issue_cylinder(cylinder["id"], contractor["id"])
        return_cylinder(cylinder["id"], 44.99)  # below 90%: shortfall
        contractor = get_contractor(contractor["id"])
        assert contractor["compliance_standing"] == "WATCH"
        assert contractor["heel_violation_count_12m"] == 1
        events, _ = validate_paginated(api.list_cylinder_events(cylinder["id"], ADMIN))
        heel_events = [e for e in events if e.get("note") == "HEEL_SHORTFALL"]
        assert len(heel_events) == 1
        assert heel_events[0]["event_type"] == "ADJUSTMENT"


def test_compliance_hold_blocks_cylinder_issue(api):
    """PRD §2.10: "`HOLD` is an operational gate, not a label. A contractor in `HOLD` cannot submit orders and cannot be issued refrigerant cylinders; both attempts are rejected with `ERR_COMPLIANCE_HOLD` (422)."
    PRD §3.7: "The standing then recomputes: two or more heel violations inside the window force `HOLD`; exactly one forces `WATCH`."

    Design: Corner/errors/compliance_hold_blocks_cylinder_issue
    """
    contractor = make_contractor(license_number="LIC-C600")
    cyl1 = make_cylinder(cylinder_tag="CYL-H1", tare_weight_lbs=20.00, full_weight_lbs=50.00)
    cyl2 = make_cylinder(cylinder_tag="CYL-H2", tare_weight_lbs=20.00, full_weight_lbs=50.00)
    issue_cylinder(cyl1["id"], contractor["id"])
    return_cylinder(cyl1["id"], 44.00)  # shortfall #1 -> WATCH
    validate_success(api.refill_cylinder(cyl1["id"], ADMIN), 200)
    issue_cylinder(cyl1["id"], contractor["id"])
    return_cylinder(cyl1["id"], 44.00)  # shortfall #2 -> HOLD
    assert get_contractor(contractor["id"])["compliance_standing"] == "HOLD", (
        "setup: two heel violations inside the window must force HOLD")
    res = api.issue_cylinder(cyl2["id"], {"contractor_id": contractor["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD)
    assert get_success_data(api.get_cylinder(cyl2["id"], ADMIN))["status"] == "IN_STOCK"


def test_cylinder_return_below_tare_rejected(api):
    """PRD §3.7: "**Returning** a cylinder supplies the gross `returned_weight_lbs`, which must be at least the `tare_weight_lbs` and at most the `full_weight_lbs`; a weight outside that band is rejected with `ERR_INVALID_CYLINDER_WEIGHT` (422)."

    Design: Corner/validations/cylinder_weight_below_tare_rejected
    """
    ctx = setup_issued_cylinder(tare=20.00, full=50.00)
    cylinder = ctx["cylinder"]
    res = api.return_cylinder(cylinder["id"], {"returned_weight_lbs": 19.99}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_CYLINDER_WEIGHT)
    assert get_success_data(api.get_cylinder(cylinder["id"], ADMIN))["status"] == "ISSUED"


def test_refrigerant_event_ledger_has_no_version_fields(api):
    """PRD §2.5: "One entity is deliberately exempt. A `RefrigerantEvent` is an append-only ledger entry and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. Clients must not expect those fields on ledger entries."
    PRD §3.7: "Entries carry a `cylinder_id`, an `event_type` of `ISSUE`, `RECOVERY_IN`, `RETURN`, `RECLAIM`, or `ADJUSTMENT`, a signed two-decimal `weight_delta_lbs` (negative when gas leaves the cylinder), a system-stamped `recorded_at`, and an optional free-text `note`."

    Design: Corner/entities/refrigerant_event_immutable_no_version_field
    """
    ctx = setup_issued_cylinder()
    cylinder = ctx["cylinder"]
    events, _ = validate_paginated(api.list_cylinder_events(cylinder["id"], ADMIN))
    assert len(events) >= 1, "setup: issuing appends an ISSUE ledger entry"
    for event in events:
        for field in ("id", "cylinder_id", "event_type", "weight_delta_lbs", "recorded_at"):
            assert field in event, f"ledger entry must carry {field}"
        assert "version" not in event, "ledger entries carry no version"
        assert "updated_at" not in event, "ledger entries carry no updated_at"


def test_credit_hold_blocks_order_submit(api):
    """PRD §3.1: "Setting `credit_hold` to true blocks that dealer from submitting orders — the submission is rejected with `ERR_CREDIT_HOLD` (422) — and a `SUSPENDED` dealer is likewise barred from submission and from receiving cylinders."

    Design: Corner/errors/credit_hold_blocks_order_submit
    """
    contractor = make_contractor(license_number="LIC-C601", credit_hold=True)
    model = make_model(model_number="CU-C601", family_code="FAM-V5",
                       list_price_cents=500_000)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
    res = api.submit_order(order["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, ApiErrorId.ERR_CREDIT_HOLD)
    assert get_order(order["id"])["status"] == "DRAFT"


class TestValidationPriorityPairs:
    def test_state_error_beats_credit_hold_on_resubmit(self, api, admin_headers):
        """PRD §2.8: "Every request is evaluated against a fixed validation pipeline, and **the first failing check determines the error returned**."
        PRD §2.8: "5. **From-state legality** — the target resource must be in a legal from-state for the requested transition; failures yield `ERR_INVALID_STATE` (409)."
        PRD §2.8: "19. **Credit hold** — `ERR_CREDIT_HOLD` (422); see §3.1 and §3.4."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_vs_credit_hold_priority
        """
        contractor = make_contractor(license_number="LIC-009")
        model = make_model(model_number="CU-I9", family_code="FAM-S",
                           list_price_cents=700_000)
        order = create_draft_order(contractor)
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        order = submit_order(order["id"], contractor)
        assert order["status"] == "ALLOCATED", "setup: unrestricted order allocates"
        validate_success(api.patch_contractor(
            contractor["id"], {"credit_hold": True}, admin_headers), 200)
        res = api.submit_order(order["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "ALLOCATED"

    def test_state_error_fires_in_isolation_without_credit_hold(self, api):
        """PRD §2.8: "5. **From-state legality** — the target resource must be in a legal from-state for the requested transition; failures yield `ERR_INVALID_STATE` (409)."
        PRD §3.4: "Submission is gated by a series of checks, evaluated in the pipeline order of §2.8: the order must be `DRAFT` with at least one line; the contractor must be `ACTIVE`; a contractor in `HOLD` standing is rejected first with `ERR_COMPLIANCE_HOLD`; a pre-buy order submitted outside its program's window — before `window_start` or at or after `window_end`, or while the program is not `OPEN` — is rejected with `ERR_WINDOW_EXPIRED`; and a `credit_hold` on the account yields `ERR_CREDIT_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_vs_credit_hold_priority
        """
        contractor = make_contractor(license_number="LIC-009B")
        model = make_model(model_number="CU-I9B", family_code="FAM-S",
                           list_price_cents=700_000)
        order = create_draft_order(contractor)
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        order = submit_order(order["id"], contractor)
        assert order["status"] == "ALLOCATED", "setup"
        res = api.submit_order(order["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def _setup_window_closed_draft(self, with_credit_hold: bool):
        set_clock("2026-08-05T00:00:00Z")
        contractor = make_contractor(license_number="LIC-010")
        model = make_model(model_number="CU-K10", family_code="FAM-R",
                           list_price_cents=700_000)
        program = make_prebuy_program(
            name="P10", family_code="FAM-R",
            window_start="2026-08-01T00:00:00Z", window_end="2026-08-10T00:00:00Z",
            ship_by_date="2026-09-15T00:00:00Z")
        order = create_draft_order(contractor, prebuy_program_id=program["id"])
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        if with_credit_hold:
            validate_success(api_client.patch_contractor(
                contractor["id"], {"credit_hold": True}, ADMIN), 200)
        set_clock("2026-08-10T00:00:00Z")  # window_end is exclusive: window just closed
        return contractor, order

    def test_window_error_beats_credit_hold(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed validation pipeline, and **the first failing check determines the error returned**."
        PRD §2.8: "9. **Window validity** — `ERR_WINDOW_EXPIRED` (422) for pre-buy order windows, ship-by enforcement, registration deadlines, and rebate payout deadlines."
        PRD §2.8: "19. **Credit hold** — `ERR_CREDIT_HOLD` (422); see §3.1 and §3.4."

        Design: Difficulty/priority_pair_validation_conflict/submit_window_vs_credit_hold_priority
        """
        contractor, order = self._setup_window_closed_draft(with_credit_hold=True)
        res = api.submit_order(order["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_EXPIRED)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_window_error_fires_in_isolation_at_exclusive_end(self, api):
        """PRD §3.4: "Submission is gated by a series of checks, evaluated in the pipeline order of §2.8: the order must be `DRAFT` with at least one line; the contractor must be `ACTIVE`; a contractor in `HOLD` standing is rejected first with `ERR_COMPLIANCE_HOLD`; a pre-buy order submitted outside its program's window — before `window_start` or at or after `window_end`, or while the program is not `OPEN` — is rejected with `ERR_WINDOW_EXPIRED`; and a `credit_hold` on the account yields `ERR_CREDIT_HOLD`."
        PRD §3.3: "A `DistributorAdmin` creates a `PreBuyProgram` with a `name` (such as SPRING-2026-RES-AC), the `family_code` it prices, an order window from `window_start` (inclusive) to `window_end` (exclusive), a `ship_by_date` by which every order taken under the program must ship, a `deposit_pct` greater than zero and at most 0.5, and a `discount_pct` greater than zero and at most 0.20."

        Design: Difficulty/priority_pair_validation_conflict/submit_window_vs_credit_hold_priority
        """
        contractor, order = self._setup_window_closed_draft(with_credit_hold=False)
        res = api.submit_order(order["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_EXPIRED)
        assert get_order(order["id"])["status"] == "DRAFT"
