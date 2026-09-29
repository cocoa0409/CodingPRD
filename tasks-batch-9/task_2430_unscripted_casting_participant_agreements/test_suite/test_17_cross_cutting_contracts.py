"""Four cross-cutting layers, each proved by what happens on the second attempt:
the applicant version guard replayed against itself, the agreement version guard
outranking the state precondition it shadows, a refused execution that must leave
no fragment of its four-link cascade behind, and an epoch that advances only when
an operator asks for it and only for the production they addressed.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_agreement_payload,
    counter_offer_payload,
    create_docusoap_production_payload,
    get_agreement,
    get_applicant,
    get_applicant_version,
    get_production,
    make_applicant_headers,
    record_screening_items,
    set_clock,
    setup_active_welfare_protocol,
    setup_applicant,
    setup_docusoap_production,
    setup_published_casting_call,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]

# A two-episode per-episode deal at a 100,000-cent episode rate.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

THREE_ADULT_INSTRUMENTS = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
)


def _harbour_nights(**overrides):
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


def _referral_call(production_id, **overrides):
    kwargs = {
        "channel": "REFERRAL",
        "min_age": 13,
        "max_age": 60,
        "exclusivity_window_days": 0,
    }
    kwargs.update(overrides)
    return setup_published_casting_call(production_id, **kwargs)


def _cleared_adult(call_id, legal_name, date_of_birth):
    applicant = setup_applicant(
        call_id,
        legal_name=legal_name,
        date_of_birth=date_of_birth,
        residency_state_code="GA",
    )
    record_screening_items(applicant["id"], THREE_ADULT_INSTRUMENTS)
    return applicant


class TestApplicantVersionGuard:
    """The drafting guard is proved in both directions: one value behind is stale,
    and replaying the accepted value is stale too, which is only possible if the
    accepted write moved the version."""

    def test_a_replayed_version_is_stale_and_the_current_one_meets_the_next_rung(
        self, api
    ):
        """PRD §2.9: "Drafting a participant agreement requires
        `expected_applicant_version`, carrying the client's last observed `version`
        of the target `Applicant`. If the applicant's current `version` differs
        from the supplied value — most typically because another `BusinessAffairs`
        writer has already drafted an agreement for that applicant, an act that
        legitimately supersedes the earlier one when `supersedes_agreement_id`
        names it — then the drafting client's view of the applicant, including its
        `screening_status` and its existing agreements, is stale, and the request
        is rejected with `ERR_STALE_APPLICANT_VERSION` (HTTP 412)."
        PRD §3.6: "Drafting opens the agreement at `status` `DRAFTED` with
        `round_number` at 0, both stipend figures at 0, `welfare_hold` false, and
        it increments the applicant's `version` by one."
        PRD §2.6: "On agreement drafting, the applicant has no other agreement
        whose `status` is `DRAFTED`, `SENT`, `COUNTERED`, `REVISED` or `EXECUTED`,
        unless `supersedes_agreement_id` names exactly that agreement. Otherwise
        `ERR_DUPLICATE_AGREEMENT` (409)."
        PRD §2.6: "Because most operations in this API are guarded by several
        independent rules at once, the order in which those rules are evaluated is
        part of the contract: the first rule that fails determines the response,
        and no later rule is evaluated."

        Design: Corner/cross_cutting_complexity_layers/agreement_create_with_stale_applicant_version_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        assert get_applicant(ada["id"])["screening_status"] == "CLEARED"
        observed = get_applicant_version(ada["id"])

        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"], production["id"], observed - 1, **BASE_TERMS
                ),
                BA1,
            ),
            ApiErrorId.ERR_STALE_APPLICANT_VERSION.value,
            412,
        )

        drafted = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"], production["id"], observed, **BASE_TERMS
                ),
                BA1,
            ),
            201,
        )
        assert drafted["status"] == "DRAFTED"
        assert drafted["round_number"] == 0

        # The accepted draft moved the applicant on, so the same value is now
        # behind and the concurrency rung answers before the duplicate rung.
        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"], production["id"], observed, **BASE_TERMS
                ),
                BA1,
            ),
            ApiErrorId.ERR_STALE_APPLICANT_VERSION.value,
            412,
        )

        # With the version corrected the concurrency rung passes and the caller
        # hears the next rule down instead.
        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"], production["id"], observed + 1, **BASE_TERMS
                ),
                BA1,
            ),
            ApiErrorId.ERR_DUPLICATE_AGREEMENT.value,
            409,
        )

        assert get_applicant_version(ada["id"]) == observed + 1


class TestAgreementVersionGuard:
    """The counter-offer guard outranks the state precondition it shadows: a stale
    replay against an already-countered agreement still answers 412."""

    def test_the_stale_version_answers_before_the_state_precondition(self, api):
        """PRD §2.9: "A participant counter-offer requires
        `expected_agreement_version`, carrying the participant's last observed
        `version` of the `ParticipantAgreement` being countered. If the agreement's
        current `version` differs, the terms the participant is countering have
        already been replaced by a newer round or a production-side revision, and
        accepting the counter would negotiate against text the participant never
        saw; the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP
        412)."
        PRD §3.6: "A negotiation round is appended against the `agreement_id` of
        the agreement under negotiation, recording `proposed_by` as `PARTICIPANT`,
        `disposition` as `COUNTERED`, `proposer_user_id` as the caller's
        `X-User-ID`, `recorded_at` at the logical clock, and `round_number` as one
        more than the agreement's current round count; the agreement's own
        `round_number` is incremented by one, its `status` becomes `COUNTERED`, and
        its `version` is incremented by one."
        PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409).
        This rung applies to every action endpoint."
        PRD §2.6: "A client that fixes the reported problem and retries may then
        encounter the next rule down the ladder."

        Design: Corner/cross_cutting_complexity_layers/counter_offer_with_stale_agreement_version_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        as_ada = make_applicant_headers(ada["id"])

        drafted = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    **BASE_TERMS,
                ),
                BA1,
            ),
            201,
        )
        sent = validate_success(api.send_agreement(drafted["id"], BA1))
        assert sent["status"] == "SENT"
        observed = sent["version"]

        terms = {
            "requested_base_stipend_cents": 150_000,
            "requested_exclusivity_window_days": 0,
            "requested_depiction_rights_scope": "FULL",
        }
        validate_error(
            api.counter_offer_agreement(
                drafted["id"], counter_offer_payload(observed - 1, **terms), as_ada
            ),
            ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
            412,
        )

        countered = validate_success(
            api.counter_offer_agreement(
                drafted["id"], counter_offer_payload(observed, **terms), as_ada
            )
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 1
        assert countered["version"] == observed + 1

        # The agreement is no longer SENT, so both the concurrency rung and the
        # state rung would fail; the higher rung is the one that answers.
        validate_error(
            api.counter_offer_agreement(
                drafted["id"],
                counter_offer_payload(
                    observed, **dict(terms, requested_base_stipend_cents=160_000)
                ),
                as_ada,
            ),
            ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
            412,
        )

        # Only once the version is current does the state precondition surface.
        validate_error(
            api.counter_offer_agreement(
                drafted["id"],
                counter_offer_payload(
                    observed + 1, **dict(terms, requested_base_stipend_cents=160_000)
                ),
                as_ada,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        assert get_agreement(drafted["id"])["round_number"] == 1


class TestRefusedExecutionIsAtomic:
    """A refused execution leaves nothing of its cascade behind: no stipend, no
    audit stamps, no status move, no obligations and no rollup contribution."""

    def test_the_pool_guard_reads_the_final_variant_and_rolls_nothing_back_in(
        self, api
    ):
        """PRD §3.6: "Execution moves the agreement `SENT → EXECUTED` and is
        admitted only from `SENT`, only while `welfare_hold` is false, only while
        the production's posture is not `FROZEN`, only when the four-eyes execution
        rule of §2.10 is satisfied, only while the applicant's `screening_status`
        and `medical_status` are both `CLEARED`, only when a minor applicant still
        fits under the cap — the production's `minor_participant_count` plus one
        must be no greater than `minor_participant_cap`, failing which the answer
        is `ERR_MINOR_CAP_EXCEEDED` — and only when `stipend_committed_cents` plus
        this agreement's final stipend figure stay within `stipend_pool_cents`."
        PRD §3.6: "The **provisional** variant, written to
        `provisional_stipend_cents` on every send transition and read by the
        send-time pool guard, is a deliberately forward-looking worst case over
        that same row."
        PRD §3.6: "First, the final stipend variant is written to
        `total_stipend_commitment_cents`, the status becomes `EXECUTED`,
        `executed_by_user_id` is stamped with the caller's `X-User-ID`,
        `executed_at` is stamped with the logical clock, and the applicant's
        `screening_status` moves to `CAST`."
        PRD §3.9: "Executing an agreement automatically creates the participant's
        post-production obligations, in a pinned creation order and with fees drawn
        from the same rate constants the stipend computation uses, so that the
        obligations always reconcile with the components the participant was paid
        for."
        PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."

        Design: Corner/cross_cutting_complexity_layers/rejected_execute_leaves_no_partial_cascade
        """
        production = validate_success(
            api.create_production(
                create_docusoap_production_payload(
                    title="Ridgeline Pilot",
                    episode_order=1,
                    stipend_pool_cents=1_500_000,
                    welfare_budget_cents=2_000_000,
                    minor_participant_cap=0,
                ),
                PA,
            ),
            201,
        )
        call = _referral_call(production["id"], min_age=18)
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        bo = _cleared_adult(call["id"], "Bo Lindqvist", "1990-01-10")

        agreement_a = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    exclusivity_window_days=0,
                    confidentiality_tier="STANDARD",
                    depiction_rights_scope="FULL",
                    stipend_structure="PER_EPISODE",
                    base_stipend_cents=900_000,
                    episodes_committed=1,
                    press_appearance_obligation_count=1,
                    reunion_obligation=True,
                ),
                BA1,
            ),
            201,
        )
        agreement_b = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    bo["id"],
                    production["id"],
                    get_applicant_version(bo["id"]),
                    exclusivity_window_days=0,
                    confidentiality_tier="STANDARD",
                    depiction_rights_scope="FULL",
                    stipend_structure="PER_EPISODE",
                    base_stipend_cents=950_000,
                    episodes_committed=1,
                ),
                BA1,
            ),
            201,
        )

        # Nothing is committed yet, so both worst-case figures clear the send
        # guard on their own: 900,000 + 3 x 25,000 + 150,000 and
        # 950,000 + 2 x 25,000 + 150,000.
        sent_a = validate_success(api.send_agreement(agreement_a["id"], BA1))
        assert_money(
            sent_a["provisional_stipend_cents"], 1_125_000, "provisional stipend A"
        )
        sent_b = validate_success(api.send_agreement(agreement_b["id"], BA1))
        assert_money(
            sent_b["provisional_stipend_cents"], 1_150_000, "provisional stipend B"
        )
        version_b_at_send = sent_b["version"]

        executed_a = validate_success(api.execute_agreement(agreement_a["id"], BA2))
        assert executed_a["status"] == "EXECUTED"
        # The final variant drops the press reserve: 900,000 + 25,000 + 150,000.
        assert_money(
            executed_a["total_stipend_commitment_cents"], 1_075_000, "final stipend A"
        )
        _, obligations_a = validate_paginated(
            api.list_post_obligations(
                agreement_a["id"], BA2, params={"limit": 10, "offset": 0}
            )
        )
        assert obligations_a["total_count"] == 2

        # 1,075,000 already committed plus B's final 950,000 overruns the pool.
        validate_error(
            api.execute_agreement(agreement_b["id"], BA2),
            ApiErrorId.ERR_STIPEND_POOL_EXCEEDED.value,
            409,
        )

        untouched = get_agreement(agreement_b["id"])
        assert untouched["status"] == "SENT"
        assert_money(
            untouched["total_stipend_commitment_cents"], 0, "refused final stipend"
        )
        assert untouched.get("executed_at") is None
        assert untouched.get("executed_by_user_id") is None
        assert untouched["version"] == version_b_at_send

        _, obligations_b = validate_paginated(
            api.list_post_obligations(
                agreement_b["id"], BA2, params={"limit": 10, "offset": 0}
            )
        )
        assert obligations_b["total_count"] == 0
        assert get_applicant(bo["id"])["screening_status"] == "CLEARED"

        final = get_production(production["id"])
        assert_money(
            final["stipend_committed_cents"], 1_075_000, "committed stipend"
        )
        # 1,075,000 x 100 falls short of 1,500,000 x 90, and no minor is admitted.
        assert final["casting_posture"] == "OPEN"


class TestWelfareEpochIsExplicitAndScoped:
    """The epoch advances only when an operator invokes it, and only for the
    production named in the path."""

    def test_moving_the_clock_changes_nothing_and_the_run_touches_one_production(
        self, api
    ):
        """PRD §3.7: "The welfare epoch sweep moves an `ACTIVE` protocol to
        `EXPIRED` once its `coverage_end_utc` falls at or before the logical
        clock."
        PRD §3.7: "The sweep is the only mechanism that applies expiry, lapse and
        breach; moving the logical clock alone changes nothing."
        PRD §3.7: "The welfare epoch sweep is an operator-driven checkpoint,
        invoked by a `ProductionAdmin` against one production, that applies
        everything the passage of the logical clock has made true."
        PRD §3.7: "Step one sums `cost_cents` over the production's protocols whose
        `status` is `PLANNED` or `ACTIVE`, excluding both `EXPIRED` and `CANCELLED`
        rows, to give the protocol subtotal; coverage dates play no part in
        membership, only the sweep's expiry transition does."

        Design: Corner/cross_cutting_complexity_layers/welfare_run_is_explicitly_triggered_and_scoped_to_one_production
        """
        first = _harbour_nights()
        second = setup_docusoap_production(
            title="Harbour Nights S2", season_number=2
        )

        coverage = {
            "coverage_start_utc": "2026-08-01T00:00:00Z",
            "coverage_end_utc": "2026-08-20T00:00:00Z",
            "cost_cents": 500_000,
        }
        protocol_one = setup_active_welfare_protocol(
            first["id"],
            kind="INSURANCE_RIDER",
            carrier_certificate_number="CERT-P1-0001",
            **coverage,
        )
        protocol_two = setup_active_welfare_protocol(
            second["id"],
            kind="INSURANCE_RIDER",
            carrier_certificate_number="CERT-P2-0001",
            **coverage,
        )
        assert protocol_one["status"] == "ACTIVE"
        assert protocol_two["status"] == "ACTIVE"

        # 500,000 sits in the lowest band, so the surcharge is four hundredths at
        # the STANDARD tier factor of one.
        assert_money(
            get_production(first["id"])["welfare_committed_cents"],
            520_000,
            "committed welfare",
        )

        set_clock("2026-09-01T00:00:00Z")

        rows, _ = validate_paginated(
            api.list_welfare_protocols(
                first["id"], WO1, params={"limit": 10, "offset": 0}
            )
        )
        assert [row["status"] for row in rows] == ["ACTIVE"]
        assert_money(
            get_production(first["id"])["welfare_committed_cents"],
            520_000,
            "committed welfare after the clock moved",
        )

        swept = validate_success(api.run_welfare_epoch(first["id"], PA))
        assert_money(
            swept["welfare_committed_cents"], 0, "committed welfare after the sweep"
        )
        rows, _ = validate_paginated(
            api.list_welfare_protocols(
                first["id"], WO1, params={"limit": 10, "offset": 0}
            )
        )
        assert [row["status"] for row in rows] == ["EXPIRED"]

        # The neighbouring production was not addressed, so it was not swept.
        rows, _ = validate_paginated(
            api.list_welfare_protocols(
                second["id"], WO1, params={"limit": 10, "offset": 0}
            )
        )
        assert [row["status"] for row in rows] == ["ACTIVE"]
        assert_money(
            get_production(second["id"])["welfare_committed_cents"],
            520_000,
            "neighbouring committed welfare",
        )

        swept_second = validate_success(api.run_welfare_epoch(second["id"], PA))
        assert_money(
            swept_second["welfare_committed_cents"],
            0,
            "neighbouring committed welfare after its own sweep",
        )
        rows, _ = validate_paginated(
            api.list_welfare_protocols(
                second["id"], WO1, params={"limit": 10, "offset": 0}
            )
        )
        assert [row["status"] for row in rows] == ["EXPIRED"]
