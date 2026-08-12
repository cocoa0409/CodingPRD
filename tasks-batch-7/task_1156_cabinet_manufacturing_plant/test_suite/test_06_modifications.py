"""Modification requests: surcharge pricing, engineering review, resubmit cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_box_line_payload,
    create_dealer_payload,
    create_finish_spec_payload,
    create_modification_payload,
    get_success_data,
    make_dealer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _draft_order_with_box_line(api, unit_price=10000, qty=1, upcharge_pct=0.0):
    dealer = get_success_data(api.create_dealer(create_dealer_payload(price_level="L3"), ADMIN))
    finish = get_success_data(
        api.create_finish_spec(create_finish_spec_payload(upcharge_pct=upcharge_pct), ADMIN)
    )
    order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
    line = get_success_data(
        api.create_order_line(
            order["id"],
            create_box_line_payload(finish["id"], qty=qty, unit_list_price_cents=unit_price),
            make_dealer_headers(dealer["id"]),
        )
    )
    return dealer, order, line


class TestSurchargeFormula:
    def test_mod_surcharge_cap_binds_over_tiered_raw(self, api):
        """PRD §3.3: "The raw surcharge is a per-code base fee — 2,500 cents for
        `REDUCED_DEPTH`, 4,000 cents for `INCREASED_DEPTH`, 2,500 cents for
        `REDUCED_WIDTH`, 4,000 cents for `INCREASED_WIDTH`, 5,500 cents for
        `TOE_KICK_NOTCH`, and 3,000 cents for `CUSTOM_BORE` — plus the line list
        multiplied by the tier percentage and rounded half up to whole cents. The
        cap is forty percent of `line_list_cents`, rounded half up. The final
        `surcharge_cents` is the smaller of the raw surcharge and the cap, with the
        cap applied strictly after the tiered fee is formed."
        PRD §3.3: "The tiered percentage is fifteen percent of `line_list_cents`
        when the delta is six inches or more, ten percent when the delta is at
        least three but fewer than six inches, and five percent when the delta is
        below three inches."

        Design: Difficulty/combinatorial_formula/mod_surcharge_tiered_formula_with_cap
        """
        _dealer, _order, line = _draft_order_with_box_line(api, unit_price=10000, qty=1)
        # delta = |20 - 12| = 8 -> 15% tier; raw = 4,000 + round(10,000 x 0.15)
        # = 5,500; cap = round(10,000 x 0.40) = 4,000 -> cap binds.
        resp = api.create_modification(
            line["id"],
            create_modification_payload(mod_code="INCREASED_DEPTH", new_dimension_in=20),
            make_dealer_headers(_dealer["id"]),
        )
        mod = validate_success(resp, 201)
        assert mod["surcharge_cents"] == 4000, (
            f"cap (4,000) must bind over the tiered raw fee (5,500); got {mod['surcharge_cents']}"
        )

    def test_mod_born_under_review_with_revision_one(self, api):
        """PRD §3.3: "The request is born in `UNDER_REVIEW` with `revision` 1, and
        its `surcharge_cents` is computed immediately."

        Design: Difficulty/combinatorial_formula/mod_surcharge_tiered_formula_with_cap
        """
        dealer, _order, line = _draft_order_with_box_line(api, unit_price=10000, qty=1)
        resp = api.create_modification(
            line["id"],
            create_modification_payload(mod_code="INCREASED_DEPTH", new_dimension_in=20),
            make_dealer_headers(dealer["id"]),
        )
        mod = validate_success(resp, 201)
        assert mod["status"] == "UNDER_REVIEW"
        assert mod["revision"] == 1


class TestReviewResubmitCycle:
    def _changes_requested_mod(self, api):
        dealer, order, line = _draft_order_with_box_line(api, unit_price=200000, qty=10, upcharge_pct=0.10)
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="INCREASED_DEPTH", new_dimension_in=20),
                make_dealer_headers(dealer["id"]),
            )
        )
        get_success_data(
            api.review_modification(mod["id"], {"decision": "REQUEST_CHANGES", "note": "too deep"}, ENGINEER)
        )
        return dealer, order, line, mod

    def test_resubmit_recomputes_surcharge_and_bumps_revision(self, api):
        """PRD §3.3: "Resubmission recomputes `surcharge_cents` through the same
        surcharge rule, increments `revision` by 1, and returns the request to
        `UNDER_REVIEW` — the review cycle may loop any number of times."

        Design: Difficulty/non_linear_state_machine/modification_request_changes_resubmit_cycle
        """
        dealer, _order, _line, mod = self._changes_requested_mod(api)
        # line_list is 2,000,000; revised delta |14 - 12| = 2 -> 5% tier:
        # 4,000 + round(2,000,000 x 0.05) = 104,000; cap 800,000 does not bind.
        data = validate_success(
            api.resubmit_modification(
                mod["id"], {"new_dimension_in": 14}, make_dealer_headers(dealer["id"])
            )
        )
        assert data["status"] == "UNDER_REVIEW"
        assert data["revision"] == 2
        assert data["surcharge_cents"] == 104000, (
            f"resubmission must recompute the surcharge from the revised dimension; got {data['surcharge_cents']}"
        )

    def test_resubmit_cycles_back_to_review_then_approves(self, api):
        """PRD §3.3: "A dealer resubmits a `CHANGES_REQUESTED` request with a
        revised `new_dimension_in`; resubmission from any other state is rejected
        with `ERR_MOD_NOT_RESUBMITTABLE`, and the acting dealer must own the parent
        order (`ERR_RESOURCE_OWNERSHIP_MISMATCH`). Resubmission recomputes
        `surcharge_cents` through the same surcharge rule, increments `revision` by
        1, and returns the request to `UNDER_REVIEW` — the review cycle may loop
        any number of times."
        PRD §3.3: "`APPROVE` moves the request to `APPROVED`; the line's
        `mod_surcharge_cents` — always the sum of the surcharges of the line's
        `APPROVED` modification requests — then takes effect at the order's next
        pricing event, whether that is submission or dispatch."

        Design: Difficulty/non_linear_state_machine/modification_request_changes_resubmit_cycle
        """
        dealer, _order, _line, mod = self._changes_requested_mod(api)
        resubmitted = validate_success(
            api.resubmit_modification(
                mod["id"], {"new_dimension_in": 14}, make_dealer_headers(dealer["id"])
            )
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        approved = validate_success(
            api.review_modification(mod["id"], {"decision": "APPROVE", "note": "ok now"}, ENGINEER)
        )
        assert approved["status"] == "APPROVED"


class TestTerminalAndInvalidReviewTransitions:
    def test_review_already_approved_mod_rejected(self, api):
        """PRD §3.3: "Review requires the request to be in `UNDER_REVIEW`; any other
        state is rejected with `ERR_MOD_NOT_REVIEWABLE` (HTTP 409)."
        PRD §3.3: "`APPROVE` moves the request to `APPROVED`; the line's
        `mod_surcharge_cents` — always the sum of the surcharges of the line's
        `APPROVED` modification requests — then takes effect at the order's next
        pricing event, whether that is submission or dispatch. `REJECT` moves the
        request to `REJECTED`. Both are terminal."

        Design: Corner/state_machines/review_already_approved_mod_rejected
        """
        dealer, _order, line = _draft_order_with_box_line(api, unit_price=50000, qty=1)
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="TOE_KICK_NOTCH", new_dimension_in=4),
                make_dealer_headers(dealer["id"]),
            )
        )
        get_success_data(api.review_modification(mod["id"], {"decision": "APPROVE"}, ENGINEER))
        resp = api.review_modification(mod["id"], {"decision": "REJECT", "note": "changed mind"}, ENGINEER)
        validate_error(resp, ApiErrorId.ERR_MOD_NOT_REVIEWABLE)
        mods, _meta = validate_paginated(api.list_modifications(line["id"], ADMIN))
        assert mods[0]["status"] == "APPROVED", "the terminal APPROVED state must be untouched"

    def test_resubmit_under_review_mod_rejected(self, api):
        """PRD §3.3: "A dealer resubmits a `CHANGES_REQUESTED` request with a
        revised `new_dimension_in`; resubmission from any other state is rejected
        with `ERR_MOD_NOT_RESUBMITTABLE`, and the acting dealer must own the parent
        order (`ERR_RESOURCE_OWNERSHIP_MISMATCH`)."

        Design: Corner/state_machines/resubmit_under_review_mod_rejected
        """
        dealer, _order, line = _draft_order_with_box_line(api, unit_price=50000, qty=1)
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="CUSTOM_BORE", new_dimension_in=3),
                make_dealer_headers(dealer["id"]),
            )
        )
        resp = api.resubmit_modification(
            mod["id"], {"new_dimension_in": 4}, make_dealer_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_MOD_NOT_RESUBMITTABLE)
        mods, _meta = validate_paginated(api.list_modifications(line["id"], ADMIN))
        assert mods[0]["revision"] == 1, "a rejected resubmit must not bump the revision"

    def test_cancel_draft_order_rejects_open_mod(self, api, plant_admin_headers):
        """PRD §3.7: "Cancelling a `DRAFT` order moves all of its lines to
        `CANCELLED`, moves every non-terminal modification request on its lines to
        `REJECTED` with `reviewer_note` set to the literal text `ORDER_CANCELLED`,
        and increments the order's `version`."

        Design: Corner/state_machines/cancel_draft_order_rejects_open_mod
        """
        dealer, order, line = _draft_order_with_box_line(api, unit_price=50000, qty=1)
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="REDUCED_DEPTH", new_dimension_in=10),
                make_dealer_headers(dealer["id"]),
            )
        )
        cancelled = validate_success(api.cancel_order(order["id"], make_dealer_headers(dealer["id"])))
        assert cancelled["status"] == "CANCELLED"
        mods, _meta = validate_paginated(api.list_modifications(line["id"], plant_admin_headers))
        assert mods[0]["id"] == mod["id"]
        assert mods[0]["status"] == "REJECTED"
        assert mods[0]["reviewer_note"] == "ORDER_CANCELLED"
