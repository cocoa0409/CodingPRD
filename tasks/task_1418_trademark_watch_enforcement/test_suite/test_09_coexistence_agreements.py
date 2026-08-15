"""Coexistence agreements: negotiation cycle, OCC on propose, overlap/adjacency,
cure cycle, clock-driven monitoring/expiry, round cap, and the breach cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equal,
    counter_agreement,
    create_agreement,
    execute_agreement,
    get_agreement,
    get_client,
    get_letter,
    get_matter,
    make_associate_headers,
    make_partner_headers,
    propose_agreement,
    satisfy_deadline,
    set_clock,
    setup_executed_agreement,
    setup_issued_letter,
    setup_published_record,
    validate_error,
    validate_paginated,
    validate_success,
    verify_deadline,
)


def _list_matter_deadlines(matter_id):
    return api_client.list_deadlines(TEST_USERS["paralegal_headers"],
                                     params={"enforcement_matter_id": matter_id})


def _record_complied(letter_id):
    return api_client.record_letter_response(letter_id,
                                             {"response_outcome": "COMPLIED"},
                                             TEST_USERS["paralegal_headers"])


def _resolve_settled(matter_id):
    return api_client.resolve_matter(matter_id, {"outcome": "SETTLED"},
                                     TEST_USERS["partner_headers"])


class TestNegotiationCycle:
    def test_propose_counter_propose_cycle_tracks_rounds(self, api):
        """PRD §3.8: "from `DRAFT` the first proposal sets `round_count` to 1"
        PRD §3.8: "Either way the proposal moves the agreement to `PROPOSED`,
        replaces `current_terms_text`, and increments the agreement's `version` by
        one. Countering carries `counter_terms_text`, moves `PROPOSED` to
        `COUNTERED`, replaces `current_terms_text`, and likewise consumes a round."

        Design: Difficulty/non_linear_state_machine/coexistence_propose_counter_cycle
        """
        _, record = setup_published_record()
        agreement = create_agreement(record["id"], counterparty_name="Rival Co",
                                     territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")

        proposed = propose_agreement(agreement["id"], agreement["version"],
                                     terms_text="round 1 terms")
        assert proposed["status"] == "PROPOSED"
        assert proposed["round_count"] == 1
        assert proposed["current_terms_text"] == "round 1 terms"

        countered = counter_agreement(agreement["id"], "counterparty counter")
        assert countered["status"] == "COUNTERED"
        assert countered["round_count"] == 2
        assert countered["current_terms_text"] == "counterparty counter"

        proposed2 = propose_agreement(agreement["id"], countered["version"],
                                      terms_text="round 3 amended terms")
        assert proposed2["status"] == "PROPOSED"
        assert proposed2["round_count"] == 3
        assert proposed2["current_terms_text"] == "round 3 amended terms"

    def test_cycle_concludes_with_execute(self, api):
        """PRD §3.8: "A `PartnerAttorney` executes from `PROPOSED` or `COUNTERED`
        once two guards pass: the record must be `PUBLISHED`, `REGISTERED`, or
        `UNDER_CHALLENGE` (else `ERR_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/coexistence_propose_counter_cycle
        """
        _, record = setup_published_record()
        agreement = create_agreement(record["id"], counterparty_name="Rival Co",
                                     territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")
        propose_agreement(agreement["id"], agreement["version"],
                          terms_text="round 1 terms")
        countered = counter_agreement(agreement["id"], "counterparty counter")
        propose_agreement(agreement["id"], countered["version"],
                          terms_text="round 3 amended terms")
        executed = execute_agreement(agreement["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["round_count"] == 3
        assert executed["current_terms_text"] == "round 3 amended terms"


class TestProposeOCC:
    def test_occ_stale_version_on_propose_rejected(self, api, associate_headers):
        """PRD §2.9: "Proposing terms on a coexistence agreement likewise requires
        `expected_agreement_version` matching the agreement's current `version`;
        each accepted proposal supersedes the outstanding terms and increments the
        agreement's `version` by one."
        PRD §2.9: "In both cases, a mismatch with the entity's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_on_propose_rejected
        """
        _, record = setup_published_record()
        agreement = create_agreement(record["id"], counterparty_name="Rival Co",
                                     territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")
        creation_version = agreement["version"]
        propose_agreement(agreement["id"], creation_version, terms_text="round 1")
        countered = counter_agreement(agreement["id"], "counter 1")

        res = api.propose_agreement(
            agreement["id"],
            {"terms_text": "stale proposal",
             "expected_agreement_version": creation_version},
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        stale = get_agreement(agreement["id"])
        assert stale["status"] == "COUNTERED"
        assert stale["round_count"] == 2

        fresh = propose_agreement(agreement["id"], countered["version"],
                                  terms_text="fresh proposal")
        assert fresh["status"] == "PROPOSED"
        assert fresh["round_count"] == 3


class TestOverlapAndAdjacency:
    def _executed_us_agreement(self, record_id):
        agreement = create_agreement(record_id, counterparty_name="Rival One",
                                     territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")
        propose_agreement(agreement["id"], agreement["version"], terms_text="t1")
        return execute_agreement(agreement["id"])

    def _proposed_agreement(self, record_id, name, territories, start, end):
        agreement = create_agreement(record_id, counterparty_name=name,
                                     territory_codes=territories,
                                     effective_start=start, effective_end=end)
        propose_agreement(agreement["id"], agreement["version"], terms_text="t")
        return agreement

    def test_adjacent_and_territory_disjoint_agreements_execute(self, api):
        """PRD §3.8: "no other agreement on the same record may be live — in
        `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` — with an
        intersecting territory set and an overlapping half-open term; mere adjacency,
        where the new term starts exactly when the existing one ends, is allowed. An
        overlap is rejected with `ERR_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_halfopen_overlap_and_adjacency
        """
        _, record = setup_published_record()
        self._executed_us_agreement(record["id"])

        adjacent = self._proposed_agreement(record["id"], "Rival Two", ["US"],
                                            "2027-09-01T00:00:00Z",
                                            "2028-09-01T00:00:00Z")
        executed_adjacent = execute_agreement(adjacent["id"])
        assert executed_adjacent["status"] == "EXECUTED"

        eu_only = self._proposed_agreement(record["id"], "Rival Four", ["EU"],
                                           "2027-08-31T00:00:00Z",
                                           "2028-08-31T00:00:00Z")
        executed_eu = execute_agreement(eu_only["id"])
        assert executed_eu["status"] == "EXECUTED"

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.8: "no other agreement on the same record may be live — in
        `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` — with an
        intersecting territory set and an overlapping half-open term; mere adjacency,
        where the new term starts exactly when the existing one ends, is allowed. An
        overlap is rejected with `ERR_AGREEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_halfopen_overlap_and_adjacency
        """
        _, record = setup_published_record()
        self._executed_us_agreement(record["id"])

        overlapping = self._proposed_agreement(record["id"], "Rival Three", ["US"],
                                               "2027-08-31T00:00:00Z",
                                               "2028-08-31T00:00:00Z")
        res = api.execute_agreement(overlapping["id"], make_partner_headers("partner_1"))
        validate_error(res, ApiErrorId.ERR_AGREEMENT_OVERLAP, expected_status=409)
        assert get_agreement(overlapping["id"])["status"] == "PROPOSED"


class TestCureAndClockTransitions:
    def _monitoring_agreement(self):
        """Agreement EXECUTED with term starting 2026-08-01, swept to MONITORING."""
        client, record, agreement = setup_executed_agreement(
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2027-08-01T00:00:00Z")
        set_clock("2026-08-02T00:00:00Z")
        return client, record, get_agreement(agreement["id"])

    def test_agreement_cure_cycle_restores_monitoring(self, api, paralegal_headers,
                                                      partner_headers):
        """PRD §3.8: "`GRANT` moves `BREACH_ALLEGED` to `CURE_PERIOD` and sets
        `cure_deadline` to `breach_claimed_at` plus `cure_period_days` calendar days.
        `CONFIRM_CURED` from `CURE_PERIOD` returns the agreement to `MONITORING` and
        clears `cure_deadline` to null."
        PRD §3.8: "An `AssociateAttorney` drafts a coexistence agreement on a record,
        supplying ... an optional `cure_period_days` defaulting to 30"

        Design: Corner/state_machines/agreement_cure_cycle_restores_monitoring
        """
        _, _, agreement = self._monitoring_agreement()
        assert agreement["status"] == "MONITORING"

        res = api.breach_agreement(agreement["id"],
                                   {"breach_notes": "territory incursion"},
                                   paralegal_headers)
        breached = validate_success(res, 200)
        assert breached["status"] == "BREACH_ALLEGED"
        assert_instant_equal(breached["breach_claimed_at"], "2026-08-02T00:00:00Z",
                             "breach_claimed_at")

        granted = validate_success(
            api.cure_agreement(agreement["id"], {"cure_action": "GRANT"},
                               partner_headers), 200)
        assert granted["status"] == "CURE_PERIOD"
        # Default cure_period_days is 30 calendar days from 2026-08-02.
        assert_instant_equal(granted["cure_deadline"], "2026-09-01T00:00:00Z",
                             "cure_deadline")

        cured = validate_success(
            api.cure_agreement(agreement["id"], {"cure_action": "CONFIRM_CURED"},
                               partner_headers), 200)
        assert cured["status"] == "MONITORING"
        assert cured["cure_deadline"] is None

    def test_agreement_auto_monitoring_and_expiry_on_clock(self, api,
                                                           paralegal_headers):
        """PRD §3.8: "The clock sweep moves an `EXECUTED` agreement to `MONITORING`
        once its `effective_start` arrives, and from `MONITORING` to `EXPIRED` once
        `effective_end` arrives, lifting the enforcement bar."

        Design: Corner/state_machines/agreement_auto_monitoring_and_expiry_on_clock
        """
        _, _, agreement = setup_executed_agreement(
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2026-10-01T00:00:00Z")

        set_clock("2026-08-15T00:00:00Z")
        assert get_agreement(agreement["id"])["status"] == "MONITORING"

        set_clock("2026-10-01T00:00:00Z")
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"


class TestRoundCap:
    def test_agreement_round_cap_at_8(self, api, associate_headers):
        """PRD §3.8: "from `COUNTERED` a further proposal requires `round_count`
        below 8 — the round cap, whose breach is rejected with
        `ERR_ROUND_CAP_REACHED` — and increments it."

        Design: Corner/validations/agreement_round_cap_at_8
        """
        _, record = setup_published_record()
        agreement = create_agreement(record["id"], counterparty_name="Rival Co",
                                     territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")
        version = agreement["version"]
        for round_no in range(1, 5):
            propose_agreement(agreement["id"], version, terms_text=f"r{round_no}")
            countered = counter_agreement(agreement["id"], f"c{round_no}")
            version = countered["version"]

        capped = get_agreement(agreement["id"])
        assert capped["round_count"] == 8
        assert capped["status"] == "COUNTERED"

        res = api.propose_agreement(
            agreement["id"],
            {"terms_text": "r5", "expected_agreement_version": version},
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROUND_CAP_REACHED, expected_status=422)
        after = get_agreement(agreement["id"])
        assert after["round_count"] == 8
        assert after["status"] == "COUNTERED"


class TestBreachCascade:
    def _resolved_matter_with_complied_letter_and_agreement(self):
        """Matter RESOLVED (SETTLED) with a COMPLIED letter and a MONITORING
        agreement naming the matter. Returns (client, record, alert, matter,
        letter, agreement)."""
        client, record, alert, matter, letter = setup_issued_letter(
            budget=1000000, response_due_days=14)
        # Verify and satisfy the auto-docketed response deadline so resolve is free.
        data, meta = validate_paginated(_list_matter_deadlines(matter["id"]))
        assert meta["total_count"] == 1
        d0 = data[0]
        verify_deadline(d0["id"], user_id="assoc_2")
        satisfy_deadline(d0["id"])

        validate_success(_record_complied(letter["id"]), 200)

        agreement = create_agreement(
            record["id"], counterparty_name="Rival Co", territory_codes=["US"],
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2027-08-01T00:00:00Z",
            enforcement_matter_id=matter["id"])
        propose_agreement(agreement["id"], agreement["version"],
                          terms_text="settlement coexistence terms")
        execute_agreement(agreement["id"])
        set_clock("2026-08-02T00:00:00Z")

        resolved = validate_success(_resolve_settled(matter["id"]), 200)
        assert resolved["status"] == "RESOLVED"
        return client, record, alert, matter, letter, get_agreement(agreement["id"])

    def test_breach_reopens_resolved_matter(self, api, paralegal_headers):
        """PRD §3.8: "A `Paralegal` alleges breach on a `MONITORING` agreement with
        `breach_notes`; `breach_claimed_at` is stamped and, when
        `enforcement_matter_id` names a `RESOLVED` matter, the cascade runs three
        levels deep: the matter reopens to `ACTIVE` exactly as in §3.4"
        PRD §3.4: "Either way, `resolution_outcome` is cleared to null"

        Design: Difficulty/transitive_cascade/breach_reopen_reissue_redocket_cascade
        """
        (client, record, alert, matter, letter, agreement) = (
            self._resolved_matter_with_complied_letter_and_agreement())
        res = api.breach_agreement(agreement["id"],
                                   {"breach_notes": "counterparty re-entered US market"},
                                   paralegal_headers)
        breached = validate_success(res, 200)
        assert breached["status"] == "BREACH_ALLEGED"
        assert_instant_equal(breached["breach_claimed_at"], "2026-08-02T00:00:00Z",
                             "breach_claimed_at")

        matter_after = get_matter(matter["id"])
        assert matter_after["status"] == "ACTIVE"
        assert matter_after["resolution_outcome"] is None

    def test_breach_reissues_letter_and_redockets_deadline(self, api,
                                                           paralegal_headers):
        """PRD §3.8: "every `COMPLIED` letter of that matter is reissued to `ISSUED`
        with its count bumped and the reissue fee accrued while the affordability
        check is bypassed, and each reissued letter gets a freshly auto-docketed
        `RESPONSE_DUE` deadline with `docketed_by_user_id` recorded as `system`."
        PRD §2.6: "Letter issuance accrues a flat fee of 75000 cents; each reissue —
        manual or cascade-driven — accrues 25000 cents."

        Design: Difficulty/transitive_cascade/breach_reopen_reissue_redocket_cascade
        """
        (client, record, alert, matter, letter, agreement) = (
            self._resolved_matter_with_complied_letter_and_agreement())
        validate_success(
            api.breach_agreement(agreement["id"],
                                 {"breach_notes": "counterparty re-entered US market"},
                                 paralegal_headers), 200)

        letter_after = get_letter(letter["id"])
        assert letter_after["status"] == "ISSUED"
        assert letter_after["reissue_count"] == 1

        data, meta = validate_paginated(_list_matter_deadlines(matter["id"]))
        assert meta["total_count"] == 2
        docketed = [d for d in data if d["status"] == "DOCKETED"]
        assert len(docketed) == 1
        assert docketed[0]["docketed_by_user_id"] == "system"

        # 75000 issue + 25000 cascade reissue (affordability check bypassed).
        assert get_client(client["id"])["budget_spent_cents"] == 100000
