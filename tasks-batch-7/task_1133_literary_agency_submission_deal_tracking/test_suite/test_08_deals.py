"""Deals: the advance waterfall, commission-split variants, amendment,
execution OCC, activation, and termination cascades."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    assert_advance_installment,
    assert_deal_invariants,
    create_accepted_manuscript,
    create_agency,
    create_agent,
    create_author,
    create_editor,
    create_round,
    create_signed_agreement,
    create_statement,
    execute_deal,
    get_deal,
    get_deal_for_offer,
    get_installment,
    make_contracts_manager_headers,
    open_round,
    queue_submission,
    record_offer,
    send_submission,
    setup_active_deal,
    setup_executed_deal,
    setup_negotiating_deal,
    validate_error,
    validate_paginated,
    validate_success,
)


def _base_ctx(name):
    agency = create_agency(name=name)
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    return {"agency": agency, "agent": agent, "author": author}


def _run_pipeline_to_executed_deal(ctx, editor_name, title, advance_cents,
                                   commission_pct_override=None,
                                   genre="FICTION", word_count=90000, eval_score=80):
    """Within an existing agency: manuscript -> signed agreement -> round ->
    sent submission -> offer -> accept -> execute. Returns the EXECUTED deal."""
    agent_id = ctx["agent"]["id"]
    pipe = create_accepted_manuscript(
        ctx["agency"]["id"], agent_id, ctx["author"]["id"],
        genre=genre, word_count=word_count, title=title, eval_score=eval_score,
    )
    create_signed_agreement(
        ctx["agency"]["id"], agent_id, ctx["author"]["id"], pipe["manuscript"]["id"],
        commission_pct_override=commission_pct_override,
    )
    editor = create_editor(ctx["agency"]["id"], display_name=editor_name)
    round_data = create_round(pipe["manuscript"]["id"], agent_id)
    submission = queue_submission(round_data["id"], editor["id"], agent_id)
    open_round(round_data, agent_id)
    send_submission(submission["id"], agent_id)
    offer = record_offer(submission["id"], agent_id, advance_cents=advance_cents)
    accept_offer(offer["id"])
    return execute_deal(get_deal_for_offer(offer["id"]))


class TestAdvanceWaterfall:
    def test_waterfall_amounts_remainder_bucket_absorbs_rounding(self, api):
        """PRD 3.7: "The `ON_SIGNING` installment is the advance multiplied by one half, floored to whole cents. The `ON_DELIVERY` installment is the advance multiplied by one quarter, floored to whole cents. The `ON_PUBLICATION` installment is whatever remains — the advance minus the signing and delivery amounts — so the three installments always sum exactly to the advance; an advance of 100,001 cents, for instance, splits 50,000 / 25,000 / 25,001."

        Design: Difficulty/combinatorial_formula/advance_waterfall_remainder_bucket_absorbs_rounding
        """
        ctx = setup_executed_deal(advance_cents=100001, agency_name="Agency WF")
        deal_id = ctx["deal"]["id"]

        signing = get_installment(deal_id, "ON_SIGNING")
        delivery = get_installment(deal_id, "ON_DELIVERY")
        publication = get_installment(deal_id, "ON_PUBLICATION")
        for inst in (signing, delivery, publication):
            assert_advance_installment(inst)

        assert signing["amount_cents"] == 50000, "floor(100001 * 0.50)"
        assert delivery["amount_cents"] == 25000, "floor(100001 * 0.25)"
        assert publication["amount_cents"] == 25001, (
            "the publication remainder bucket absorbs the rounding cent"
        )
        total = signing["amount_cents"] + delivery["amount_cents"] + publication["amount_cents"]
        assert total == 100001, "the three installments must sum exactly to the advance"

    def test_waterfall_due_schedule_anchored_to_execution_period(self, api):
        """PRD 3.7: "`ON_SIGNING` is due in `executed_period_index` itself, `ON_DELIVERY` one period later, and `ON_PUBLICATION` two periods later, with `due_period_index` stamped accordingly"
        PRD 3.7: "A successful execution stamps `executed_period_index` with the current `period_index`, increments the deal's `version` by one, moves the winning submission — still `OFFER_EXTENDED` — to `WITHDRAWN`, and cuts the advance payment schedule."

        Design: Difficulty/combinatorial_formula/advance_waterfall_remainder_bucket_absorbs_rounding
        """
        ctx = setup_executed_deal(advance_cents=100001, agency_name="Agency WF")
        deal = ctx["deal"]
        assert deal["status"] == "EXECUTED"
        executed_at = deal["executed_period_index"]
        assert executed_at == 0

        assert get_installment(deal["id"], "ON_SIGNING")["due_period_index"] == executed_at
        assert get_installment(deal["id"], "ON_DELIVERY")["due_period_index"] == executed_at + 1
        assert get_installment(deal["id"], "ON_PUBLICATION")["due_period_index"] == executed_at + 2

        winner = validate_success(
            api.get_submission(ctx["submission"]["id"], make_contracts_manager_headers()), 200
        )
        assert winner["status"] == "WITHDRAWN"


class TestCommissionSplitVariants:
    def test_installment_commission_provisional_variant(self, api, royalties_accountant_headers):
        """PRD 3.8: "For an identical underlying amount the variants diverge exactly as the fraction does: a 250,000-cent installment (or statement line) against an agency rate of 0.15 yields 37,500 cents of commission under the provisional variant, while a locked override of 0.10 yields 25,000."
        PRD 3.7: "the installment's `agency_commission_cents` is the installment's `amount_cents` multiplied by the applicable commission fraction, floored to whole cents, where the fraction is the signed agreement's locked `commission_pct_override` when one exists and otherwise the agency's `commission_pct` read at payment time"

        Design: Difficulty/dual_variant_calc/commission_split_provisional_vs_final_on_installments
        """
        ctx = _base_ctx("Agency DV")
        deal = _run_pipeline_to_executed_deal(
            ctx, "Ed A", "Book A", advance_cents=500000, commission_pct_override=None
        )
        signing = get_installment(deal["id"], "ON_SIGNING")
        assert signing["amount_cents"] == 250000, "floor(500000 * 0.50)"

        paid = validate_success(
            api.mark_installment_paid(signing["id"], royalties_accountant_headers), 200
        )
        assert paid["status"] == "PAID"
        assert paid["agency_commission_cents"] == 37500, (
            "provisional variant: floor(250000 * 0.15 agency rate at payment time)"
        )

    def test_installment_commission_final_variant_diverges(self, api, royalties_accountant_headers):
        """PRD 3.8: "For an identical underlying amount the variants diverge exactly as the fraction does: a 250,000-cent installment (or statement line) against an agency rate of 0.15 yields 37,500 cents of commission under the provisional variant, while a locked override of 0.10 yields 25,000."

        Design: Difficulty/dual_variant_calc/commission_split_provisional_vs_final_on_installments
        """
        ctx = _base_ctx("Agency DV")
        deal_a = _run_pipeline_to_executed_deal(
            ctx, "Ed A", "Book A", advance_cents=500000, commission_pct_override=None
        )
        deal_b = _run_pipeline_to_executed_deal(
            ctx, "Ed B", "Book B", advance_cents=500000,
            commission_pct_override=0.10, genre="NONFICTION", word_count=80000,
            eval_score=85,
        )

        paid_a = validate_success(
            api.mark_installment_paid(get_installment(deal_a["id"], "ON_SIGNING")["id"],
                                      royalties_accountant_headers),
            200,
        )
        paid_b = validate_success(
            api.mark_installment_paid(get_installment(deal_b["id"], "ON_SIGNING")["id"],
                                      royalties_accountant_headers),
            200,
        )
        assert paid_a["amount_cents"] == 250000
        assert paid_b["amount_cents"] == 250000
        assert paid_b["agency_commission_cents"] == 25000, (
            "final variant: floor(250000 * 0.10 locked override)"
        )
        assert paid_a["agency_commission_cents"] == 37500
        assert paid_a["agency_commission_cents"] != paid_b["agency_commission_cents"], (
            "the variant is selected by the agreement's override, not by the amount"
        )


class TestDealAmendmentAndExecution:
    def test_deal_patch_while_negotiating_updates_terms(self, api, contracts_manager_headers):
        """PRD 3.7: "While the deal is `NEGOTIATING`, a `ContractsManager` may amend it, changing `advance_cents` and any of `retains_film_rights`, `retains_foreign_rights`, or `retains_audio_rights`; each amendment increments the deal's `version` by one, and any amendment attempt outside `NEGOTIATING` is rejected with `ERR_INVALID_STATE`."
        PRD 3.6: "the three retention flags are inverted from the demands — `retains_film_rights` starts true exactly when `includes_film_rights` was false, and likewise for `retains_foreign_rights` and `retains_audio_rights`."

        Design: Corner/endpoints/deal_patch_while_negotiating_updates_terms
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency DP")
        deal = ctx["deal"]
        assert deal["retains_film_rights"] is True, (
            "the offer demanded no film rights, so the deal retains them"
        )

        patched = validate_success(
            api.patch_deal(
                deal["id"],
                {"advance_cents": 600000, "retains_film_rights": False},
                contracts_manager_headers,
            ),
            200,
        )
        assert patched["advance_cents"] == 600000
        assert patched["retains_film_rights"] is False
        assert patched["version"] == deal["version"] + 1

        executed = validate_success(
            api.execute_deal(
                deal["id"], {"expected_deal_version": patched["version"]},
                contracts_manager_headers,
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"

        blocked = api.patch_deal(deal["id"], {"advance_cents": 700000}, contracts_manager_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

    def test_occ_deal_execute_stale_version_returns_412(self, api, contracts_manager_headers):
        """PRD 2.10: "Executing a deal likewise requires `expected_deal_version` matching the deal's current `version`; a mismatch — for example because another writer amended the deal's terms between the client's read and the execute call — is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.7: "each amendment increments the deal's `version` by one"

        Design: Corner/cross_cutting_layers/occ_deal_execute_stale_version_returns_412
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency OC2")
        deal = ctx["deal"]
        stale_version = deal["version"]

        amended = validate_success(
            api.patch_deal(deal["id"], {"advance_cents": 600000}, contracts_manager_headers), 200
        )
        assert amended["version"] == stale_version + 1

        stale = api.execute_deal(
            deal["id"], {"expected_deal_version": stale_version}, contracts_manager_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        executed = validate_success(
            api.execute_deal(
                deal["id"], {"expected_deal_version": amended["version"]},
                contracts_manager_headers,
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"
        assert executed["advance_cents"] == 600000, (
            "the amended terms are what execution persists"
        )


class TestDealActivationAndTermination:
    def test_first_installment_paid_activates_deal(self, api, royalties_accountant_headers):
        """PRD 3.7: "The first installment on a deal to reach `PAID` flips the deal from `EXECUTED` to `ACTIVE`; the period-close sweep re-checks this condition as a backstop."
        PRD 3.8: "a 250,000-cent installment (or statement line) against an agency rate of 0.15 yields 37,500 cents of commission under the provisional variant"

        Design: Corner/state_machines/first_installment_paid_activates_deal
        """
        ctx = setup_executed_deal(advance_cents=500000, agency_name="Agency PA")
        deal_id = ctx["deal"]["id"]

        signing = get_installment(deal_id, "ON_SIGNING")
        paid = validate_success(
            api.mark_installment_paid(signing["id"], royalties_accountant_headers), 200
        )
        assert paid["status"] == "PAID"
        assert paid["agency_commission_cents"] == 37500, "floor(250000 * 0.15)"
        assert paid["paid_period_index"] == 0

        deal_now = get_deal(deal_id)
        assert deal_now["status"] == "ACTIVE", "the first PAID installment must flip the deal to ACTIVE"
        assert_deal_invariants(deal_now)

    def test_deal_terminate_waives_scheduled_installments(self, api, contracts_manager_headers):
        """PRD 3.7: "The termination cascade has two counted links: the deal moves to `TERMINATED`, and every installment of the deal still in `SCHEDULED` or `DUE` is waived to `WAIVED` — a waiver caused by the termination. `LATE` installments are deliberately not waived, and `PAID` installments stay `PAID`."

        Design: Corner/state_machines/deal_terminate_waives_scheduled_installments
        """
        ctx = setup_active_deal(advance_cents=1000000, agency_name="Agency DT")
        deal_id = ctx["deal"]["id"]

        terminated = validate_success(api.terminate_deal(deal_id, contracts_manager_headers), 200)
        assert terminated["status"] == "TERMINATED"

        assert get_installment(deal_id, "ON_SIGNING")["status"] == "PAID", (
            "paid installments are not waived"
        )
        assert get_installment(deal_id, "ON_DELIVERY")["status"] == "WAIVED"
        assert get_installment(deal_id, "ON_PUBLICATION")["status"] == "WAIVED"

    def test_terminate_deal_with_received_statement_rejected(self, api, contracts_manager_headers):
        """PRD 3.7: "A `ContractsManager` may terminate a deal from `EXECUTED` or `ACTIVE`, but only while no royalty statement for the deal sits in `RECEIVED` or `AUDIT_OPEN` — unresolved statements block termination with `ERR_STATEMENTS_UNRESOLVED`."

        Design: Corner/validations/terminate_deal_with_received_statement_rejected
        """
        ctx = setup_executed_deal(advance_cents=500000, agency_name="Agency SU")
        deal_id = ctx["deal"]["id"]
        statement = create_statement(
            deal_id, period_index=0, units=(100, 0, 0), receipts=(100000, 0, 0),
            publisher_reported_royalty_cents=10000,
        )
        assert statement["status"] == "RECEIVED"

        resp = api.terminate_deal(deal_id, contracts_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STATEMENTS_UNRESOLVED.value)

        assert get_deal(deal_id)["status"] == "EXECUTED"

    def test_fk_reverse_reachability_filtered_lists(self, api, agency_admin_headers):
        """PRD 4: "manuscripts by `author_id`, `query_letter_id`, and `reader_agent_id`; client agreements by `author_id`, `manuscript_id`, and `agent_id`; submission rounds by `manuscript_id` and `agent_id`; submissions by `submission_round_id` and `editor_id`; offers by `submission_id`; deals by `offer_id`, `submission_id`, and `client_agreement_id`; royalty statements by `deal_id` and `period_index`; and advance installments by `deal_id` and `milestone`"
        PRD 3.7: "The schedule is a fixed three-milestone waterfall over `advance_cents`, computed in a pinned order."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        ctx = setup_executed_deal(advance_cents=100000, agency_name="Agency FK")

        manuscripts, _ = validate_paginated(
            api.list_manuscripts(agency_admin_headers,
                                 params={"query_letter_id": ctx["query"]["id"]})
        )
        assert [m["id"] for m in manuscripts] == [ctx["manuscript"]["id"]]

        deals, _ = validate_paginated(
            api.list_deals(agency_admin_headers, params={"offer_id": ctx["offer"]["id"]})
        )
        assert [d["id"] for d in deals] == [ctx["deal"]["id"]]

        installments, _ = validate_paginated(
            api.list_advance_installments(agency_admin_headers,
                                          params={"deal_id": ctx["deal"]["id"]})
        )
        assert len(installments) == 3
        assert {i["milestone"] for i in installments} == {
            "ON_SIGNING", "ON_DELIVERY", "ON_PUBLICATION"
        }
