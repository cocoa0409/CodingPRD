"""One call, many rows: cascades that reach rows the caller never names."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    admit_panelist,
    api_client,
    assert_all_mandatory_grounds,
    assert_fee_transaction,
    cast_seat_vote,
    case_payload,
    draft_decision,
    file_complaint,
    file_court_challenge,
    fund_case_to_assessment,
    issue_decision,
    issue_deficiency_notice,
    make_complainant_headers,
    post_ledger_line,
    read_appointment,
    read_case,
    read_complainant,
    read_decision,
    read_domain,
    read_panelist,
    register_domain,
    replace_seat,
    resolve_court_challenge,
    run_sweep,
    screen_seat,
    seat_panelist_cleanly,
    set_clock,
    setup_filed_case,
    setup_responded_case,
    setup_three_member_panel,
    validate_error,
    validate_paginated,
)

RDNH_DOCKET = {
    "iana_id": "IANA-1101",
    "domain_name": "rdnhcase.example",
    "legal_name": "Overreach Ltd",
    "country_code": "FR",
}
LAPSE_DOCKET = {
    "iana_id": "IANA-1202",
    "domain_name": "lapsed.example",
    "legal_name": "Lapse GmbH",
    "country_code": "FR",
}
VACATE_DOCKET = {
    "iana_id": "IANA-1303",
    "domain_name": "vacate.example",
    "legal_name": "Vacate Srl",
    "country_code": "FR",
}


def _denied_case_with_hijacking_finding():
    """A single-member case denied with a hijacking finding, issued 2026-08-20."""
    bundle = setup_responded_case(**RDNH_DOCKET)
    case_id = bundle["case"]["id"]
    fund_case_to_assessment(case_id)
    panelist = admit_panelist(
        full_name="Anna Bauer", nationality_code="DE",
        roster_admitted_at="2019-01-15T00:00:00Z",
    )
    set_clock("2026-08-10T00:00:00Z")
    appointment = seat_panelist_cleanly(case_id, "SOLE", panelist)
    set_clock("2026-08-20T00:00:00Z")
    decision = draft_decision(
        case_id, panelist["id"],
        draft_summary="The complaint fails on all three elements and was brought to harass the registrant.",
    )
    cast_seat_vote(
        decision["id"], panelist["id"], "SOLE", "DENY", rdnh_vote=True,
        rationale="The complainant knew of the registrant's prior legitimate trade.",
    )
    bundle["panelists"] = [panelist]
    bundle["appointments"] = [appointment]
    bundle["decision"] = issue_decision(decision["id"])
    bundle["case"] = read_case(case_id)
    return bundle


class TestSustainedChallengeCascade:
    def test_a_denied_complaint_with_hijacking_ballots_raises_the_signed_counter(self):
        """PRD §3.7: "`rdnh_finding` is true only when the `outcome` is
        `COMPLAINT_DENIED` and twice the number of ballots carrying `rdnh_vote`
        true exceeds `required_seat_count`; the hijacking ballots are counted
        across the whole panel, not merely among the seats that voted to deny, so
        a panel of three that denies the complaint two-to-one records a hijacking
        finding only if at least two seats — including possibly the dissenter —
        flagged it."
        PRD §3.7: "When `rdnh_finding` came out true, the complainant's
        `adverse_rdnh_findings` counter advances by one — the only place in the
        system that counter rises."

        Design: Difficulty/transitive_cascade/sustained_court_challenge_unwinds_six_links_including_the_rdnh_counter
        """
        bundle = _denied_case_with_hijacking_finding()
        decision = bundle["decision"]
        assert decision["outcome"] == "COMPLAINT_DENIED"
        assert decision["rdnh_finding"] is True
        assert decision["deny_votes"] == 1
        assert decision["transfer_votes"] == 0
        assert decision["cancellation_votes"] == 0
        assert decision["dissent_present"] is False
        assert decision["issued_at"] == "2026-08-20T00:00:00.000Z"
        assert decision["implementation_deadline_at"] == "2026-09-03T00:00:00.000Z"
        assert bundle["case"]["status"] == "IMPLEMENTATION_WAITING"
        complainant = read_complainant(bundle["complainant"]["id"])
        assert complainant["adverse_rdnh_findings"] == 1
        assert complainant["open_case_count"] == 1

    def test_one_sustained_disposition_unwinds_every_link_including_the_counter(self):
        """PRD §3.8: "A `SUSTAINED` disposition destroys the proceeding, in a
        cascade of five linked effects plus their counter adjustments."
        PRD §3.8: "In addition, the domain returns to `UNLOCKED`, the
        complainant's `open_case_count` drops by one, and where the voided
        decision had carried `rdnh_finding` true, that finding is **un-counted**
        from the complainant's `adverse_rdnh_findings`, which is the only place
        that counter ever falls."

        Design: Difficulty/transitive_cascade/sustained_court_challenge_unwinds_six_links_including_the_rdnh_counter
        """
        bundle = _denied_case_with_hijacking_finding()
        case_id = bundle["case"]["id"]
        decision_id = bundle["decision"]["id"]
        appointment_id = bundle["appointments"][0]["id"]
        panelist_id = bundle["panelists"][0]["id"]

        set_clock("2026-08-21T00:00:00Z")
        challenge = file_court_challenge(
            bundle, "COMPLAINANT", docket_number="3:26-cv-01199"
        )
        assert read_panelist(panelist_id)["active_case_load"] == 1
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "LOCKED"

        set_clock("2026-08-25T00:00:00Z")
        resolved = resolve_court_challenge(
            challenge["id"], "SUSTAINED",
            resolution_note="The court vacated the RDNH finding and the denial.",
        )
        assert resolved["status"] == "SUSTAINED"
        assert resolved["resolved_at"] == "2026-08-25T00:00:00.000Z"

        decision = read_decision(decision_id)
        assert decision["status"] == "VOIDED"
        assert decision["voided_at"] == "2026-08-25T00:00:00.000Z"
        assert decision["publication_status"] == "UNPUBLISHED"

        case = read_case(case_id)
        assert case["status"] == "TERMINATED_COURT"
        assert case["closed_at"] == "2026-08-25T00:00:00.000Z"
        assert case["refiling_bar_until"] == "2026-09-24T00:00:00.000Z"

        seat = read_appointment(appointment_id)
        assert seat["status"] == "DISCHARGED"
        assert read_panelist(panelist_id)["active_case_load"] == 0
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"

        complainant = read_complainant(bundle["complainant"]["id"])
        assert complainant["adverse_rdnh_findings"] == 0
        assert complainant["open_case_count"] == 0

        entries, entry_meta = validate_paginated(
            api_client.get_precedent_entry(decision_id, CASE_MANAGER)
        )
        assert entry_meta["total_count"] == 0
        assert entries == []


class TestExpiredCorrectionPeriodCascade:
    def _two_deficient_cases(self):
        bundle = setup_filed_case(**LAPSE_DOCKET)
        complainant = bundle["complainant"]
        second_domain = register_domain(bundle["registrar"]["id"], "stillopen.example")
        second_case = file_complaint(complainant, second_domain)
        assert_all_mandatory_grounds(second_case, complainant, evidence_count=1)
        post_ledger_line(
            second_case["id"], second_case["complainant_share_cents"],
            reference="WIRE-1202-B",
        )
        bundle["notice_a"] = issue_deficiency_notice(
            bundle["case"]["id"],
            deficiency_codes=["MUTUAL_JURISDICTION_ABSENT"], correction_days=5,
        )
        bundle["notice_b"] = issue_deficiency_notice(
            second_case["id"], deficiency_codes=["MISSING_SIGNATURE"], correction_days=10,
        )
        bundle["second_domain"] = second_domain
        bundle["second_case"] = read_case(second_case["id"])
        return bundle

    def test_the_sweep_expires_one_notice_and_reverses_that_case_s_whole_ledger(self):
        """PRD §3.4: "When the deadline sweep finds a notice in `OPEN` whose
        `correction_deadline_at` has passed, the notice becomes `EXPIRED` and the
        whole case is closed administratively: the case moves from `DEFICIENT` to
        `ADMIN_CLOSED`, `closed_at` is stamped from the clock, and
        `refiling_bar_until` is set 30 days later."
        PRD §3.4: "The automatic close always refunds in full, at 100 percent,
        regardless of how far the case had travelled, and its refund lines carry
        the reference `AUTO-CLOSE-REFUND` instead of the withdrawal reference."

        Design: Difficulty/transitive_cascade/expired_correction_period_closes_the_case_and_reverses_the_whole_ledger
        """
        bundle = self._two_deficient_cases()
        case_id = bundle["case"]["id"]
        assert bundle["notice_a"]["correction_deadline_at"] == "2026-08-06T00:00:00.000Z"
        assert bundle["notice_b"]["correction_deadline_at"] == "2026-08-11T00:00:00.000Z"
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 2

        set_clock("2026-08-07T00:00:00Z")
        counters = run_sweep()
        assert counters["expired_notice_count"] == 1
        assert counters["closed_case_count"] == 1
        assert counters["defaulted_case_count"] == 0

        notices, _ = validate_paginated(
            api_client.list_deficiency_notices(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert notices[0]["status"] == "EXPIRED"

        case = read_case(case_id)
        assert case["status"] == "ADMIN_CLOSED"
        assert case["closed_at"] == "2026-08-07T00:00:00.000Z"
        assert case["refiling_bar_until"] == "2026-09-06T00:00:00.000Z"
        assert case["paid_cents"] == 0
        assert case["complainant_paid_cents"] == 0
        assert case["respondent_paid_cents"] == 0

        ledger, ledger_meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert ledger_meta["total_count"] == 2
        refund = ledger[1]
        assert_fee_transaction(refund)
        assert refund["kind"] == "REFUND"
        assert refund["payer"] == "COMPLAINANT"
        assert refund["amount_cents"] == -150000
        assert refund["reference"] == "AUTO-CLOSE-REFUND"
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 1
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"

    def test_the_sweep_leaves_the_notice_still_in_its_window_alone_and_is_idempotent(self):
        """PRD §2.4: "It is idempotent — running it twice at the same clock reading
        changes nothing on the second pass and returns all four counters as zero."
        PRD §3.2: "Both endpoints of that interval are inclusive, so a filing
        attempted at the exact instant of `refiling_bar_until` is still barred with
        `ERR_REFILING_BAR_ACTIVE` and the domain frees up one instant later."

        Design: Difficulty/transitive_cascade/expired_correction_period_closes_the_case_and_reverses_the_whole_ledger
        """
        bundle = self._two_deficient_cases()
        case_id = bundle["case"]["id"]
        set_clock("2026-08-07T00:00:00Z")
        run_sweep()

        untouched_notices, _ = validate_paginated(
            api_client.list_deficiency_notices(
                bundle["second_case"]["id"], CASE_MANAGER, params={"limit": 10, "offset": 0}
            )
        )
        assert untouched_notices[0]["status"] == "OPEN"
        second = read_case(bundle["second_case"]["id"])
        assert second["status"] == "DEFICIENT"
        assert second["paid_cents"] == 150000

        again = run_sweep()
        assert again["expired_notice_count"] == 0
        assert again["overdue_verification_count"] == 0
        assert again["defaulted_case_count"] == 0
        assert again["closed_case_count"] == 0
        _, ledger_meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert ledger_meta["total_count"] == 2

        refiled = api_client.create_case(
            case_payload(bundle["complainant"]["id"], bundle["domain"]["id"]),
            make_complainant_headers(bundle["complainant"]["id"]),
        )
        validate_error(refiled, ApiErrorId.ERR_REFILING_BAR_ACTIVE.value, 409)


class TestSeatReplacementCascade:
    def _constituted_panel_with_a_draft(self):
        bundle = setup_three_member_panel(**VACATE_DOCKET)
        presiding = bundle["panelists"][0]
        substitute = admit_panelist(
            full_name="Bram de Vries", nationality_code="NL",
            roster_admitted_at="2018-11-11T00:00:00Z", firm_name="De Vries Advocaten",
        )
        decision = draft_decision(
            bundle["case"]["id"], presiding["id"],
            draft_summary="Draft prepared by the presiding panelist.",
        )
        vote = cast_seat_vote(
            decision["id"], presiding["id"], "PRESIDING", "TRANSFER",
            rationale="All three elements are made out.",
        )
        bundle["substitute"] = substitute
        bundle["decision"] = decision
        bundle["vote"] = vote
        bundle["case"] = read_case(bundle["case"]["id"])
        return bundle

    def test_vacating_a_seated_chair_unwinds_the_panel_and_voids_the_live_draft(self):
        """PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything
        that acceptance had built: the seat's `honoraria_cents` returns to 0, the
        neutral's `active_case_load` drops by one, the case falls back from
        `PANEL_CONSTITUTED` to `PANEL_APPOINTMENT`, and every decision on the case
        still in `DRAFT` is moved to `VOIDED` with `voided_at` stamped from the
        clock."
        PRD §3.6: "The ballots already cast on a voided draft remain readable but
        are dead — they never count toward any successor decision."

        Design: Difficulty/transitive_cascade/replacing_one_seated_panelist_unconstitutes_the_panel_and_voids_the_draft
        """
        bundle = self._constituted_panel_with_a_draft()
        case_id = bundle["case"]["id"]
        presiding_seat, co_one, co_two = bundle["appointments"]
        presiding = bundle["panelists"][0]
        assert bundle["case"]["status"] == "PANEL_CONSTITUTED"
        assert bundle["case"]["required_seat_count"] == 3
        assert bundle["case"]["honoraria_pool_cents"] == 280000
        assert read_appointment(presiding_seat["id"])["honoraria_cents"] == 112000
        assert read_appointment(co_one["id"])["honoraria_cents"] == 84000
        assert read_appointment(co_two["id"])["honoraria_cents"] == 84000
        assert read_panelist(presiding["id"])["active_case_load"] == 1
        version_before = bundle["case"]["version"]

        predecessor = replace_seat(
            presiding_seat["id"],
            replacement_panelist_id=bundle["substitute"]["id"],
            reason="The presiding panelist withdrew on personal grounds.",
        )
        assert predecessor["status"] == "REPLACED"
        assert predecessor["honoraria_cents"] == 0
        successor_id = predecessor["replaced_by_appointment_id"]
        assert successor_id is not None
        assert read_panelist(presiding["id"])["active_case_load"] == 0

        case = read_case(case_id)
        assert case["status"] == "PANEL_APPOINTMENT"
        assert case["version"] > version_before

        voided = read_decision(bundle["decision"]["id"])
        assert voided["status"] == "VOIDED"
        assert voided["voided_at"] == "2026-08-01T00:00:00.000Z"

        votes, vote_meta = validate_paginated(
            api_client.list_votes(bundle["decision"]["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert vote_meta["total_count"] == 1
        assert votes[0]["seat"] == "PRESIDING"
        assert votes[0]["vote"] == "TRANSFER"

        successor = read_appointment(successor_id)
        assert successor["status"] == "NOMINATED"
        assert successor["seat"] == "PRESIDING"
        assert successor["panelist_id"] == bundle["substitute"]["id"]
        assert successor["honoraria_cents"] == 0
        assert successor["conflict_score"] is None
        _, appointment_meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert appointment_meta["total_count"] == 4

    def test_the_voided_draft_blocks_issuance_and_the_successor_re_constitutes_the_panel(self):
        """PRD §3.7: "Issuance is a case manager's act on a decision still in
        `DRAFT`; a decision already `ISSUED`, `STAYED`, `IMPLEMENTED` or `VOIDED`
        is refused with `ERR_INVALID_DECISION_STATE`."
        PRD §3.6: "The other seats' `honoraria_cents` are left as they stand until
        the panel is constituted again, at which point allocation re-runs across
        the new set of accepted seats."

        Design: Difficulty/transitive_cascade/replacing_one_seated_panelist_unconstitutes_the_panel_and_voids_the_draft
        """
        bundle = self._constituted_panel_with_a_draft()
        case_id = bundle["case"]["id"]
        presiding_seat = bundle["appointments"][0]
        predecessor = replace_seat(
            presiding_seat["id"], replacement_panelist_id=bundle["substitute"]["id"]
        )
        successor_id = predecessor["replaced_by_appointment_id"]

        refused = api_client.issue_decision(bundle["decision"]["id"], CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_INVALID_DECISION_STATE.value, 409)

        seated = screen_seat(successor_id, bundle["substitute"]["id"])
        assert seated["status"] == "ACCEPTED"
        assert read_panelist(bundle["substitute"]["id"])["active_case_load"] == 1
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"
        assert read_appointment(successor_id)["honoraria_cents"] == 112000
        assert read_appointment(presiding_seat["id"])["honoraria_cents"] == 0
        assert read_appointment(bundle["appointments"][1]["id"])["honoraria_cents"] == 84000
        assert read_appointment(bundle["appointments"][2]["id"])["honoraria_cents"] == 84000
