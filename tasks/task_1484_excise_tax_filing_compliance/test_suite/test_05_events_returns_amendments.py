"""Taxable events, returns, and the amendment workflow (PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_classified_event,
    create_event,
    create_rated_event,
    file_return,
    new_analyst_headers,
    new_reviewer_headers,
    open_amendment,
    rate_event,
    setup_active_registration,
    setup_filed_return,
    setup_return_with_rated_event,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPerEventRounding:
    def test_per_event_rounding_rounds_each_event_individually(self, api):
        """PRD §2.6: "Rounding is pinned per taxable event: each event's tax
        is rounded half-up to whole cents at rating time" — 1 unit at 24300
        milli-cents is 24.3 cents, rounding to 24 per event.

        Design: Difficulty/combinatorial_formula/per_event_rounding_then_sum
        """
        ctx = setup_active_registration()
        for day in (3, 4, 5):
            rated = create_rated_event(
                ctx["registration"], ctx["jurisdiction"],
                ctx["product_class"],
                event_date=f"2026-08-0{day}T00:00:00Z", quantity_units=1)
            assert rated["tax_cents"] == 24, (
                f"round_half_up(24.3) == 24, got {rated['tax_cents']}")

    def test_return_totals_sum_prerounded_cents(self, api):
        """PRD §2.6: "return totals are plain sums of those pre-rounded
        per-event amounts that are never re-rounded — sum-then-round
        aggregation is forbidden." Three 24-cent events total 72, not
        round_half_up(72.9) == 73.

        Design: Difficulty/combinatorial_formula/per_event_rounding_then_sum
        """
        ctx = setup_active_registration()
        ret_id = None
        for day in (3, 4, 5):
            rated = create_rated_event(
                ctx["registration"], ctx["jurisdiction"],
                ctx["product_class"],
                event_date=f"2026-08-0{day}T00:00:00Z", quantity_units=1)
            ret_id = rated["return_id"]
        ret = validate_success(api.get_return(ret_id, new_analyst_headers()))
        assert ret["event_count"] == 3
        assert ret["gross_tax_cents"] == 72
        assert ret["taxable_tax_cents"] == 72, (
            "plain sum of per-event cents; sum-then-round would give 73")


class TestAutoCreatedReturn:
    def test_auto_created_return_initial_state(self, api):
        """PRD §3.4: "if no return exists yet for the registration,
        jurisdiction, and period, the system creates one in `DRAFT` together
        with its deposit schedule".
        PRD §3.6: "A new return starts with `filing_status` `DRAFT` and
        `settlement_status` `UNFILED`, its `amendment_of_id` null and
        `amendment_sequence` zero".

        Design: Corner/state_machines/auto_created_return_initial_state
        """
        ctx = setup_active_registration()
        ev = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                ctx["product_class"], quantity_units=100)
        ret = validate_success(
            api.get_return(ev["return_id"], new_analyst_headers()))
        assert ret["filing_status"] == "DRAFT"
        assert ret["settlement_status"] == "UNFILED"
        assert ret["amendment_of_id"] is None
        assert ret["amendment_sequence"] == 0
        assert ret["event_count"] == 1
        assert ret["taxable_tax_cents"] == 2430  # 100 units x 24300mc / 1000


class TestReturnFilingValidation:
    def test_file_draft_return_rejected(self, api):
        """PRD §3.6: "The filing dimension runs `DRAFT` to `SUBMITTED` to
        `FILED`" — filing a `DRAFT` return is not a transition, failing per
        §2.10 "(5) state legality of the requested transition, including
        terminal-state lockdown, yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/file_draft_return_rejected
        """
        ctx, _ev, ret = setup_return_with_rated_event()
        reviewer = new_reviewer_headers()
        version = validate_success(api.get_return(ret["id"], reviewer))["version"]
        resp = api.file_return(ret["id"], version, reviewer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_classify_not_idempotent_rejected(self, api):
        """PRD §3.4: "Classification confirms the product identification,
        moving an event from `DRAFT` to `CLASSIFIED`" — a second classify is
        not a transition and fails per §2.10 "(5) state legality of the
        requested transition, including terminal-state lockdown, yielding
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/second_classify_not_idempotent_rejected
        """
        ctx = setup_active_registration()
        ev = create_classified_event(ctx["registration"], ctx["jurisdiction"],
                                     ctx["product_class"], quantity_units=10)
        resp = api.classify_event(ev["id"], new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_return_rejected(self, api):
        """PRD §3.6: "at most one non-`SUPERSEDED` original return may exist
        per registration, jurisdiction, and period; a conflicting creation is
        rejected with `ERR_DUPLICATE_RETURN`."

        Design: Corner/validations/duplicate_return_rejected
        """
        ctx, _ev, _ret = setup_return_with_rated_event(quantity_units=10)
        resp = api.create_return(
            {"registration_id": ctx["registration"]["id"],
             "jurisdiction_id": ctx["jurisdiction"]["id"],
             "period": "2026-08"},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RETURN)

    def test_rate_into_filed_period_rejected(self, api):
        """PRD §3.4: "rating requires the period of the `event_date` to be
        open: the latest non-superseded return for the registration,
        jurisdiction, and period must be in `DRAFT` or `SUBMITTED`, or must
        have an amendment in `DRAFT` or `SUBMITTED` — otherwise the period is
        locked and the request fails with `ERR_PERIOD_LOCKED`, because new
        ratings must then flow through an amendment."

        Design: Corner/validations/rate_into_filed_period_rejected
        """
        ctx, _ev, _filed = setup_filed_return()
        ev2 = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            event_date="2026-08-10T00:00:00Z", quantity_units=5)
        resp = api.rate_event(ev2["id"], {}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_PERIOD_LOCKED)


class TestAmendments:
    def test_second_open_amendment_rejected(self, api):
        """PRD §3.6: "At most one open amendment — one in `DRAFT` or
        `SUBMITTED` — may exist per parent return; a second attempt is
        rejected with `ERR_AMENDMENT_ALREADY_OPEN`."

        Design: Corner/validations/second_open_amendment_rejected
        """
        _ctx, _ev, filed = setup_filed_return()
        open_amendment(filed["id"])
        resp = api.amend_return(
            filed["id"],
            {"expected_return_version":
             validate_success(api.get_return(filed["id"],
                                             new_analyst_headers()))["version"]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ALREADY_OPEN)

    def test_amendment_reverse_reachability_list(self, api):
        """PRD §3.6: "The amendment is created as a new return in `DRAFT` and
        `UNFILED`, its `amendment_of_id` naming the parent, its
        `amendment_sequence` one deeper than its parent's" and "The return
        list filters by `registration_id`, `jurisdiction_id`, `period`,
        `filing_status`, `settlement_status`, or `amendment_of_id`."

        Design: Corner/endpoints/amendment_reverse_reachability_list
        """
        _ctx, _ev, filed = setup_filed_return()
        amd = open_amendment(filed["id"])
        rows, meta = validate_paginated(api.list_returns(
            new_analyst_headers(), params={"amendment_of_id": filed["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == amd["id"]
        assert rows[0]["amendment_sequence"] == 1
        assert rows[0]["period"] == "2026-08"
        assert rows[0]["filing_status"] == "DRAFT"


class TestReturnAggregation:
    def test_returns_summary_computed_read(self, api):
        """PRD §3.6: "A computed summary read for any return returns its
        `return_id`, `period`, `event_count`, `gross_tax_cents`,
        `exempted_cents`, `taxable_tax_cents`, `credits_cents`,
        `deposits_applied_cents`, `penalty_cents`, `net_due_cents`,
        `filing_status`, and `settlement_status`." and "`event_count` counts
        the included events; `gross_tax_cents` sums their per-event gross
        amounts".

        Design: Corner/endpoints/returns_summary_computed_read
        """
        ctx = setup_active_registration()
        ev1 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"], quantity_units=1000)
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-08-04T00:00:00Z",
                           quantity_units=400)
        summary = validate_success(
            api.get_return_summary(ev1["return_id"], new_analyst_headers()))
        assert summary["return_id"] == ev1["return_id"]
        assert summary["event_count"] == 2
        assert summary["gross_tax_cents"] == 34020  # 24300 + 9720
        assert summary["taxable_tax_cents"] == 34020
        assert summary["exempted_cents"] == 0
        assert summary["filing_status"] == "DRAFT"

    def test_reclassified_then_voided_event_excluded_from_totals(self, api):
        """PRD §3.6: "A return's totals aggregate its included events — those
        whose `return_id` names this return and whose status is `RATED`,
        `RETURNED`, or `ADJUSTED`, while `DRAFT`, `CLASSIFIED`, and `VOIDED`
        events are excluded."

        Design: Corner/calculations/reclassified_then_voided_event_excluded_from_totals
        """
        ctx = setup_active_registration()
        ev1 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"], quantity_units=1000)
        ev2 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"],
                                 event_date="2026-08-04T00:00:00Z",
                                 quantity_units=400)
        ret_id = ev1["return_id"]

        validate_success(api.reclassify_event(ev2["id"], new_analyst_headers()))
        mid = validate_success(api.get_return(ret_id, new_analyst_headers()))
        assert mid["gross_tax_cents"] == 24300, (
            "CLASSIFIED event drops out of the aggregate")

        validate_success(api.void_event(ev2["id"], new_analyst_headers()))
        end = validate_success(api.get_return(ret_id, new_analyst_headers()))
        assert end["gross_tax_cents"] == 24300
        assert end["event_count"] == 1, "VOIDED events stay excluded"

    def test_derived_liability_recomputed_on_event_void(self, api):
        """PRD §3.1: "`aggregate_open_liability_cents` is the sum of
        `taxable_tax_cents` over all of the registrant's returns still in
        `DRAFT` or `SUBMITTED`".
        PRD §3.4: "the registrant's `aggregate_open_liability_cents` is
        recomputed."

        Design: Corner/cross_cutting_layers/derived_liability_recomputed_on_event_void
        """
        ctx = setup_active_registration()
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"], quantity_units=1000)
        ev2 = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"],
                                 event_date="2026-08-04T00:00:00Z",
                                 quantity_units=400)
        before = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert before["aggregate_open_liability_cents"] == 34020

        validate_success(api.reclassify_event(ev2["id"], new_analyst_headers()))
        validate_success(api.void_event(ev2["id"], new_analyst_headers()))
        after = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert after["aggregate_open_liability_cents"] == 24300


class TestZeroActivityReturn:
    def test_zero_activity_return_filing(self, api):
        """PRD §3.6: "a `TaxAnalyst` or `ComplianceAdmin` may also create one
        manually — including a zero-activity return" and "an underpayment
        penalty applies when the taxable tax is positive" (zero tax carries no
        underpayment penalty), and "zero settles it as `SETTLED`".

        Design: Corner/endpoints/zero_activity_return_filing
        """
        ctx = setup_active_registration()
        ret = validate_success(api.create_return(
            {"registration_id": ctx["registration"]["id"],
             "jurisdiction_id": ctx["jurisdiction"]["id"],
             "period": "2026-10"},
            new_analyst_headers()), expected_status=201)
        assert ret["event_count"] == 0

        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        filed = file_return(ret["id"])
        assert filed["penalty_cents"] == 0
        assert filed["net_due_cents"] == 0
        assert filed["settlement_status"] == "SETTLED"
        assert filed["filing_status"] == "FILED"


class TestEventCorrectionLoops:
    def test_event_pre_filing_correction_loop(self, api):
        """PRD §3.4: "Sending a `RATED` event back for correction returns it
        to `CLASSIFIED`, zeroing its `tax_cents` and `gross_tax_cents`,
        clearing its exemption and movement links, recomputing the containing
        return's totals, and bumping the return's `version`; this loop is only
        available while the containing return is in `DRAFT`".

        Design: Difficulty/non_linear_state_machine/taxable_event_rerate_and_amendment_cycle
        """
        ctx, ev, _ret = setup_return_with_rated_event()
        corrected = validate_success(
            api.reclassify_event(ev["id"], new_analyst_headers()))
        assert corrected["status"] == "CLASSIFIED"
        assert corrected["tax_cents"] == 0
        assert corrected["gross_tax_cents"] == 0

        rerated = rate_event(ev["id"])
        assert rerated["status"] == "RATED"
        assert rerated["tax_cents"] == 24300

    def test_event_amendment_loop_returned_adjusted_returned(self, api):
        """PRD §3.4: "Such a correction moves the event from `RETURNED` to
        `ADJUSTED`, again zeroing its tax fields and recomputing the
        amendment's totals" and "When the containing return is filed, its
        `RATED` events become `RETURNED`; when the containing amendment is
        filed, its `ADJUSTED` events become `RETURNED`."
        PRD §3.6: "When the return being filed is an amendment, its parent
        return's `filing_status` becomes `SUPERSEDED`".

        Design: Difficulty/non_linear_state_machine/taxable_event_rerate_and_amendment_cycle
        """
        ctx, ev, filed = setup_filed_return()
        event = validate_success(
            api.get_taxable_event(ev["id"], new_analyst_headers()))
        assert event["status"] == "RETURNED"

        amd = open_amendment(filed["id"])
        adjusted = validate_success(
            api.reclassify_event(ev["id"], new_analyst_headers()))
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["tax_cents"] == 0

        rerated = rate_event(ev["id"])
        assert rerated["status"] == "RATED"
        assert rerated["tax_cents"] == 24300
        assert rerated["return_id"] == amd["id"], (
            "recomputed values land on the amendment return")

        validate_success(api.submit_return(amd["id"], new_analyst_headers()))
        amd_filed = file_return(amd["id"])
        assert amd_filed["filing_status"] == "FILED"

        event = validate_success(
            api.get_taxable_event(ev["id"], new_analyst_headers()))
        assert event["status"] == "RETURNED"
        parent = validate_success(
            api.get_return(filed["id"], new_analyst_headers()))
        assert parent["filing_status"] == "SUPERSEDED"
