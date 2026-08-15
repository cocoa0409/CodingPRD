"""Optimistic-concurrency writes (shift staffing, order amend, waiver create),
per-action role splits, and the state-vs-safety priority pair."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_line_payload, create_order_payload, create_waiver_payload,
    create_shift_payload,
    make_line, make_shift, make_order,
    setup_running_shift_with_run,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
OP = TEST_USERS["line_operator_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
PLAN = TEST_USERS["order_planner_headers"]


class TestOptimisticConcurrency:

    def test_occ_stale_shift_version_rejected(self, api):
        """PRD §2.7: "A `POST /poultry/shifts/{id}/staffing` request must carry
        `expected_shift_version` equal to the shift's current `version`; the
        shift's staffing fields feed the effective line-speed ceiling and the
        water and projection denominators, so a writer holding a stale view of
        the shift must re-read before writing, and a mismatch is rejected with
        `ERR_STALE_SHIFT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_shift_version_rejected
        """
        shift = make_shift()
        v0 = shift["version"]
        payload = {"shacklers_present": 10, "eviscerators_present": 20,
                   "deboners_present": 12, "qa_techs_present": 2,
                   "expected_shift_version": v0}
        updated = validate_success(api.set_shift_staffing(shift["id"], payload, SUP))
        assert updated["version"] == v0 + 1

        stale = dict(payload, shacklers_present=8)
        resp = api.set_shift_staffing(shift["id"], stale, SUP)
        validate_error(resp, ApiErrorId.ERR_STALE_SHIFT_VERSION)
        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["shacklers_present"] == 10

    def test_occ_stale_order_version_rejected(self, api):
        """PRD §2.7: "A `PUT /poultry/orders/{id}` request must carry
        `expected_order_version` equal to the order's current `version`; two
        sequential amendments each legitimately succeed under product
        semantics, so a second writer working from a stale read is rejected
        purely on the version, with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_order_version_rejected
        """
        order = make_order(pounds_ordered=500.0)
        v0 = order["version"]
        amended = validate_success(api.amend_order(
            order["id"], {"pounds_ordered": 600.0, "expected_order_version": v0}, PLAN))
        assert amended["version"] == v0 + 1
        assert amended["pounds_ordered"] == pytest.approx(600.0)

        resp = api.amend_order(
            order["id"], {"pounds_ordered": 700.0, "expected_order_version": v0}, PLAN)
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
        after = get_success_data(api.get_order(order["id"], PLAN))
        assert after["pounds_ordered"] == pytest.approx(600.0)

    def test_occ_stale_line_version_on_waiver_create(self, api):
        """PRD §2.7: "A `POST /poultry/lines/{id}/waivers` request must carry
        `expected_line_version` equal to the line's current `version`; waiver
        creation legitimately supersedes a prior draft or submitted waiver with
        an overlapping window on the same line, and that supersession itself
        advances the line's `version`, so a creator holding a stale line
        version must re-read before creating — a mismatch is rejected with
        `ERR_STALE_LINE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_line_version_on_waiver_create
        """
        line = make_line()
        v0 = line["version"]
        get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                v0, effective_from="2026-08-01T06:00:00Z",
                effective_to="2026-08-01T14:00:00Z"), PM))
        line_after = get_success_data(api.get_line(line["id"], PM))
        assert line_after["version"] == v0 + 1

        resp = api.create_waiver(
            line["id"], create_waiver_payload(
                v0, max_speed_bpm=190,
                effective_from="2026-08-02T06:00:00Z",
                effective_to="2026-08-02T14:00:00Z"), PM)
        validate_error(resp, ApiErrorId.ERR_STALE_LINE_VERSION)


class TestRoleDenials:

    def test_receiving_clerk_cannot_create_line_forbidden(self, api):
        """PRD §2.1: "An authenticated operator who attempts an operation
        outside their role's mandate is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)".
        PRD §2.1: "A `PlantManager` owns plant configuration — registering
        processing lines and production shifts".

        Design: Corner/rbac/receiving_clerk_cannot_create_line_forbidden
        """
        resp = api.create_line(create_line_payload(), RCV)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestValidationPriorityPair:

    def test_set_speed_suspended_and_unauthorized_state_wins(self, api):
        """PRD §2.6: "State-machine admissibility (priority 4). The target
        entity's own from-state must admit the requested transition, and where
        the operation executes inside a production shift the enclosing shift's
        status must admit it: run starts, speed changes, batch starts, batch
        resumes, and suspensions require the shift in `RUNNING` (else
        `ERR_SHIFT_NOT_RUNNING`)".
        PRD §2.6: "Regulatory and safety gates (priority 5). Line-speed
        authorization, segregation of duties, and the chiller-limit fresh block
        — `ERR_LINE_SPEED_NOT_AUTHORIZED`, `ERR_SOD_PREOP_SANITATION`,
        `ERR_SOD_CONDEMNATION_SELF_CERTIFY`, and
        `ERR_CHILLER_LIMIT_FRESH_BLOCKED` (HTTP 403)."
        PRD §2.6: "Every request is evaluated against an ordered ladder of
        checks; the first rung that fails stops evaluation and produces that
        rung's error."

        Design: Difficulty/priority_pair_validation_conflict/set_speed_suspended_and_unauthorized_state_wins
        """
        env = setup_running_shift_with_run()
        rid, sid = env["run"]["id"], env["shift"]["id"]
        # Suspend the shift (run auto-pauses); no waiver: base cap 175.
        get_success_data(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "MANUAL"}, SUP))
        # 196 would violate the speed ceiling AND the shift is not RUNNING;
        # the priority-4 state rung fires first.
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 196}, OP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_RUNNING)
        after = get_success_data(api.get_line_run(rid, OP))
        assert after["current_speed_bpm"] == 175
