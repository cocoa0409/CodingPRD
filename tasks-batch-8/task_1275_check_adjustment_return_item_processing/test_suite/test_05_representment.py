"""Re-presentment: the PRESENTED -> RETURNED -> PRESENTED cycle and its gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    setup_coded_return,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PROCESSOR


def _cycle_item_once_returned():
    """Item presented once, returned, coded NSF (eligible): count == 1."""
    return setup_coded_return(
        reason_code="NSF", amount_cents=50000, opening_balance_cents=500000,
        bank_overrides={"name": "CB Cyc", "routing_number": "111000029"},
        item_reference="ITM-CYC",
    )


class TestRepresentCycle:
    def test_represent_cycles_item_back_to_presented(self, api):
        """PRD §3.4: "A `RETURNED` item may be re-presented, cycling back to
        `PRESENTED`" and "A successful re-presentment increments
        `presentment_count` by one and refreshes `presented_at`."

        Design: Difficulty/non_linear_state_machine/check_item_return_represent_cycle
        """
        ctx = _cycle_item_once_returned()
        represented = validate_success(
            api.represent_check_item(ctx["item"]["id"], PROCESSOR), 200
        )
        assert represented["status"] == "PRESENTED"
        assert represented["presentment_count"] == 2

    def test_third_presentment_rejected_after_second_return(self, api):
        """PRD §3.4: "and `presentment_count` must still be below 2 — a third
        presentment attempt is rejected with `ERR_MAX_PRESENTMENTS_EXCEEDED`."
        PRD §3.4: "The `PRESENTED` → `RETURNED` → `PRESENTED` cycle may
        repeat until the count reaches 2 total presentments."

        Design: Difficulty/non_linear_state_machine/check_item_return_represent_cycle
        """
        ctx = _cycle_item_once_returned()
        item_id = ctx["item"]["id"]
        validate_success(api.represent_check_item(item_id, PROCESSOR), 200)
        re2 = validate_success(api.create_return_event(item_id, PROCESSOR), 201)
        validate_success(
            api.code_return_event(re2["id"], {"reason_code": "NSF"}, PROCESSOR), 200
        )
        res = api.represent_check_item(item_id, PROCESSOR)
        validate_error(res, ApiErrorId.ERR_MAX_PRESENTMENTS_EXCEEDED)


class TestRepresentCountBoundary:
    def test_represent_allowed_when_count_is_one(self, api):
        """PRD §3.4: "and `presentment_count` must still be below 2 — a third
        presentment attempt is rejected with `ERR_MAX_PRESENTMENTS_EXCEEDED`"
        — at count 1 (below 2) the re-presentment gate passes.

        Design: Difficulty/boundary_precision_check/represent_count_boundary
        """
        ctx = _cycle_item_once_returned()
        represented = validate_success(
            api.represent_check_item(ctx["item"]["id"], PROCESSOR), 200
        )
        assert represented["status"] == "PRESENTED"
        assert represented["presentment_count"] == 2

    def test_represent_rejected_when_count_reaches_two(self, api):
        """PRD §3.4: "and `presentment_count` must still be below 2 — a third
        presentment attempt is rejected with `ERR_MAX_PRESENTMENTS_EXCEEDED`"
        — at count 2 (== the maximum) the gate fails.

        Design: Difficulty/boundary_precision_check/represent_count_boundary
        """
        ctx = _cycle_item_once_returned()
        item_id = ctx["item"]["id"]
        validate_success(api.represent_check_item(item_id, PROCESSOR), 200)
        re2 = validate_success(api.create_return_event(item_id, PROCESSOR), 201)
        validate_success(
            api.code_return_event(re2["id"], {"reason_code": "NSF"}, PROCESSOR), 200
        )
        res = api.represent_check_item(item_id, PROCESSOR)
        validate_error(res, ApiErrorId.ERR_MAX_PRESENTMENTS_EXCEEDED)


class TestRepresentEligibility:
    def test_represent_not_eligible_reason_rejected(self, api):
        """PRD §3.4: "Coding computes `re_presentment_eligible`: it is true
        exactly when the reason is `NSF`, `MISSING_ENDORSEMENT`,
        `IMAGE_NONCONFORMING`, or `REFER_TO_MAKER`, and false for
        `STOP_PAYMENT`, `CLOSED_ACCOUNT`, `ALTERED_OR_FICTITIOUS`, and
        `DUPLICATE_PRESENTMENT`." and "that return's
        `re_presentment_eligible` must be true — otherwise
        `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`"

        Design: Corner/validations/represent_not_eligible_reason_rejected
        """
        ctx = setup_coded_return(
            reason_code="STOP_PAYMENT", amount_cents=5000,
            opening_balance_cents=100000,
            bank_overrides={"name": "CB SP", "routing_number": "222000034"},
            item_reference="ITM-SP",
        )
        assert ctx["return_event"]["re_presentment_eligible"] is False
        res = api.represent_check_item(ctx["item"]["id"], PROCESSOR)
        validate_error(res, ApiErrorId.ERR_RE_PRESENTMENT_NOT_ELIGIBLE)
