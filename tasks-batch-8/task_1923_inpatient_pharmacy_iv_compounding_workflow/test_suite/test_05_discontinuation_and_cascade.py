"""Discontinuation: terminal lockdown, prescriber ownership, L1-L3 cascade (PRD §3.3)."""
from test_helpers import (
    fixtures,
    make_prescriber_headers,
    place_order,
    setup_batch,
    setup_verified_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _discontinue(api, ns, reason="therapy changed"):
    return api.discontinue_order(
        ns.order["id"], {"reason": reason},
        make_prescriber_headers(ns.prescriber["id"]),
    )


class TestTerminalLockdown:
    def _setup_discontinued(self, api):
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        resp = _discontinue(api, ns, reason="stop")
        validate_success(resp, 200)
        return ns

    def test_verify_on_discontinued_order_rejected_terminal(self, api):
        """PRD §3.3: "Any mutation attempted on an order whose verification is already `DISCONTINUED` or `SUPERSEDED`, or whose fulfillment is `ADMINISTERED`, is rejected outright with `ERR_ORDER_ALREADY_TERMINAL`."

        Design: Corner/state_machines/order_discontinue_terminal_lockdown
        """
        ns = self._setup_discontinued(api)
        resp = api.verify_order(ns.order["id"], {}, ns.pharmacist_headers)
        validate_error(resp, "ERR_ORDER_ALREADY_TERMINAL", 409)

    def test_second_discontinue_rejected_terminal(self, api):
        """PRD §3.3: "Any mutation attempted on an order whose verification is already `DISCONTINUED` or `SUPERSEDED`, or whose fulfillment is `ADMINISTERED`, is rejected outright with `ERR_ORDER_ALREADY_TERMINAL`."

        Design: Corner/state_machines/order_discontinue_terminal_lockdown
        """
        ns = self._setup_discontinued(api)
        resp = _discontinue(api, ns, reason="again")
        validate_error(resp, "ERR_ORDER_ALREADY_TERMINAL", 409)

    # NOTE: Corner/state_machines/order_discontinue_terminal_lockdown's third
    # probe (plain intervention append on a DISCONTINUED order ->
    # ERR_ORDER_ALREADY_TERMINAL) was removed: PRD §3.3's "any mutation
    # attempted on an order" does not uniquely determine whether creating an
    # append-only ClinicalIntervention child (placed_on_hold=false mutates no
    # order field; §3.3 says "Every call appends an immutable
    # ClinicalIntervention row") counts as such a mutation. Two faithful
    # PRD-only implementations diverge on it, so the assertion is not uniquely
    # derivable.


class TestOnlyOrderingPrescriberMayDiscontinue:
    def test_other_prescriber_discontinue_rejected(self, api):
        """PRD §3.3: "Discontinuation is the prescriber's prerogative, and only the ordering prescriber may exercise it: the caller's `X-User-ID` must equal the order's `prescriber_staff_id`, otherwise the call is rejected with `ERR_NOT_ORDER_PRESCRIBER`."

        Design: Corner/errors/error_not_order_prescriber
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        other_prescriber, other_headers = fixtures.make_prescriber()
        resp = api.discontinue_order(
            ns.order["id"], {"reason": "not mine"}, other_headers
        )
        validate_error(resp, "ERR_NOT_ORDER_PRESCRIBER", 403)
        fetched = validate_success(
            api.get_medication_order(ns.order["id"], ns.pharmacist_headers), 200
        )
        assert fetched["verification_status"] == "VERIFIED"


class TestDiscontinueCascade:
    def _setup_batched_order_then_discontinue(self, api):
        # SCHEDULED session (not started): batch DRAFT with one PLANNED preparation.
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = setup_batch([ns.order["id"]], start_session=False)
        # Batch creation moved the order QUEUED -> COMPOUNDING (PRD §3.5), which
        # itself increments the order's version (PRD §2.4); re-fetch so the
        # +1 assertion compares against the true pre-discontinue baseline.
        pre = validate_success(
            api.get_medication_order(ns.order["id"], ns.pharmacist_headers), 200
        )
        resp = _discontinue(api, ns)
        discontinued = validate_success(resp, 200)
        return ns, batch_ns, discontinued, pre

    def test_discontinue_stores_reason_and_moves_verification(self, api):
        """PRD §3.3: "A successful discontinuation stores the supplied `reason` in `discontinue_reason`, moves verification to `DISCONTINUED`, increments the order's `version`, and runs a three-level cascade."

        Design: Difficulty/transitive_cascade/order_discontinue_cascade
        """
        ns, _, discontinued, pre = self._setup_batched_order_then_discontinue(api)
        assert discontinued["verification_status"] == "DISCONTINUED"
        assert discontinued["discontinue_reason"] == "therapy changed"
        assert discontinued["version"] == pre["version"] + 1

    def test_discontinue_cancels_preparation_batch_and_hood_session(self, api, admin_headers):
        """PRD §3.3: "Level one: every `CompoundedPreparation` of this order in `PLANNED` or `COMPOUNDED` moves to `CANCELLED`. Level two: each affected batch recomputes its `demand_ml` and `vials_used`, and a batch left with zero preparations in `PLANNED`, `COMPOUNDED`, or `QA_PASSED` auto-transitions from `DRAFT` or `IN_PROGRESS` to `CANCELLED`. Level three: a batch cancelled at level two cancels its hood session when that session is `SCHEDULED` or `IN_USE`."

        Design: Difficulty/transitive_cascade/order_discontinue_cascade
        """
        ns, batch_ns, _, _ = self._setup_batched_order_then_discontinue(api)
        preps, _ = validate_paginated(
            api.list_preparations(admin_headers, params={"order_id": ns.order["id"]})
        )
        assert len(preps) == 1
        assert preps[0]["status"] == "CANCELLED"
        batch = validate_success(api.get_batch(batch_ns.batch["id"], admin_headers), 200)
        assert batch["status"] == "CANCELLED"
        session = validate_success(
            api.get_hood_session(batch_ns.session["id"], admin_headers), 200
        )
        assert session["status"] == "CANCELLED"
