"""Sanctions disposition: the two-tier desk, single-shot dispositions, and
the confirm cascade across hit, wire, and account."""
from test_helpers import (
    ApiErrorId,
    assert_sanctions_hit,
    assert_wire,
    create_submitted_wire,
    get_account,
    get_wire,
    list_wire_sanctions_hits,
    repair_wire,
    setup_wire_room,
    simulate_hit,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
SCREENER = TEST_USERS["sanctions_screener_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestEscalationTierGating:
    def test_sanctions_escalated_release_forbidden_for_screener(self, api):
        """PRD §3.6: "A `SanctionsScreener` may disposition only `OPEN` hits;
        a hit in `ESCALATED` status is beyond screener authority, and a
        screener's attempt to release or confirm it is rejected with
        `ERR_FORBIDDEN_ROLE`. A `ComplianceOfficer` is required for
        `ESCALATED` hits — only a compliance officer may disposition one."
        PRD §3.6: "When the released hit was the wire's **last unresolved
        hit**, the wire's `screening_status` transitions from `REVIEW` to
        `CLEAR`"

        The screener escalates, then is denied; the officer's release
        dispositions the hit and returns the wire's screening to CLEAR.

        Design: Corner/state_machines/sanctions_escalated_release_forbidden_for_screener
        """
        room = setup_wire_room(business_date="2026-09-01")
        wire = create_submitted_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-01",
            300000)
        hit = simulate_hit(wire["id"], matched_list="EU_CONSOLIDATED",
                           matched_party="SM Ben8", match_score=74)
        escalated = validate_success(api.escalate_sanctions_hit(
            hit["id"], {"rationale": "ambiguous transliteration"}, SCREENER), 200)
        assert escalated["status"] == "ESCALATED"

        resp = api.release_sanctions_hit(
            hit["id"], {"rationale": "screener overreach"}, SCREENER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        released = validate_success(api.release_sanctions_hit(
            hit["id"], {"rationale": "officer review: false positive"}, OFFICER), 200)
        assert_sanctions_hit(released)
        assert released["status"] == "RELEASED_FALSE_POSITIVE"
        assert released["decided_by"] == "co-1"
        assert released["decided_at"] is not None

        wire_after = get_wire(wire["id"])
        assert wire_after["screening_status"] == "CLEAR"
        assert wire_after["status"] == "PENDING_APPROVAL"


class TestSingleShotDisposition:
    def test_sanctions_hit_double_disposition_rejected(self, api):
        """PRD §3.6: "In both tiers, a hit already in
        `RELEASED_FALSE_POSITIVE` or `CONFIRMED` is terminal, and any further
        disposition attempt is rejected with `ERR_HIT_ALREADY_RESOLVED`."

        A released hit rejects both a second release and a confirm.

        Design: Corner/state_machines/sanctions_hit_double_disposition_rejected
        """
        room = setup_wire_room(business_date="2026-09-09")
        wire = create_submitted_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-09",
            300000)
        hit = simulate_hit(wire["id"], matched_list="INTERNAL_WATCH",
                           matched_party="SM Ben14", match_score=66)

        released = validate_success(api.release_sanctions_hit(
            hit["id"], {"rationale": "false positive"}, SCREENER), 200)
        assert released["status"] == "RELEASED_FALSE_POSITIVE"

        resp_release = api.release_sanctions_hit(
            hit["id"], {"rationale": "again"}, SCREENER)
        validate_error(resp_release, ApiErrorId.ERR_HIT_ALREADY_RESOLVED)

        resp_confirm = api.confirm_sanctions_hit(
            hit["id"], {"rationale": "changed my mind"}, SCREENER)
        validate_error(resp_confirm, ApiErrorId.ERR_HIT_ALREADY_RESOLVED)


class TestSanctionsRoleGate:
    def test_sanctions_release_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/sanctions-hits/{id}/release is authorized for
        `SanctionsScreener, ComplianceOfficer`.

        The WireOperator who operates the wire still cannot disposition its
        hit.

        Design: Corner/rbac/sanctions_release_forbidden_for_operator
        """
        room = setup_wire_room(business_date="2026-10-01")
        wire = create_submitted_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-10-01",
            300000)
        hit = simulate_hit(wire["id"], matched_list="OFAC_SDN",
                           matched_party="RBAC Ben4", match_score=82)

        resp = api.release_sanctions_hit(
            hit["id"], {"rationale": "operator overreach"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        hit_after = validate_success(api.get_sanctions_hit(hit["id"], SCREENER), 200)
        assert hit_after["status"] == "OPEN"

    def test_screening_simulate_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/_screening/simulate is authorized for
        `SanctionsScreener` only.

        An operator cannot self-serve screening outcomes; the wire carries no
        hits afterwards.

        Design: Corner/rbac/screening_simulate_forbidden_for_operator
        """
        room = setup_wire_room()
        wire = validate_success(api.create_wire(
            {
                "ordering_account_id": room["account"]["id"],
                "beneficiary_id": room["beneficiary"]["id"],
                "amount_cents": 100000,
                "method": "Fedwire",
                "purpose": "rbac simulate",
            },
            OPERATOR,
        ), 201)

        resp = api.simulate_screening_hit(
            {"wire_id": wire["id"], "matched_list": "OFAC_SDN",
             "matched_party": "RBAC Ben9", "match_score": 90},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        hits = list_wire_sanctions_hits(wire["id"])
        assert hits == [], f"no sanctions hit may exist, got {len(hits)}"


class TestConfirmCascade:
    def test_sanctions_confirm_cascades_hit_wire_account(self, api):
        """PRD §3.6: "A confirm disposition — again with a `rationale` —
        moves the hit to `CONFIRMED` and drives the wire's `screening_status`
        to `CONFIRMED_HIT`. Confirmation is fatal to a wire still in the
        pipeline: if the wire's status is `PENDING_APPROVAL` or `REPAIR`, the
        wire transitions to `REJECTED`, its reservation is released back to
        the account with `reservation_active` set false, its
        `hold_reason_code` is cleared to null, and the confirmation is
        audit-logged as `sanctions.confirm`."

        One confirm call propagates hit -> wire -> account: CONFIRMED hit,
        REJECTED wire with the reservation flag cleared, and the account's
        reserved tally debited by the wire amount.

        Design: Difficulty/transitive_cascade/sanctions_confirm_cascades_hit_wire_account
        """
        room = setup_wire_room(business_date="2026-08-10")
        account = room["account"]
        wire = create_submitted_wire(
            account["id"], room["beneficiary"]["id"], "2026-08-10", 400000,
            clear_hits=False)
        hit = simulate_hit(wire["id"], matched_list="OFAC_SDN",
                           matched_party="Vendor Seven", match_score=97)
        assert get_account(account["id"])["daily_reserved_cents"] == 400000

        confirmed = validate_success(api.confirm_sanctions_hit(
            hit["id"], {"rationale": "exact match on SDN entry"}, SCREENER), 200)
        assert_sanctions_hit(confirmed)
        assert confirmed["status"] == "CONFIRMED"

        wire_after = get_wire(wire["id"])
        assert_wire(wire_after)
        assert wire_after["status"] == "REJECTED"
        assert wire_after["screening_status"] == "CONFIRMED_HIT"
        assert wire_after["reservation_active"] is False

        account_after = get_account(account["id"])
        assert account_after["daily_reserved_cents"] == 0, (
            f"the wire's rejection debits the reservation, got "
            f"{account_after['daily_reserved_cents']}")

    def test_sanctions_confirm_from_repair_releases_reservation(self, api):
        """PRD §3.6: "Confirmation is fatal to a wire still in the pipeline:
        if the wire's status is `PENDING_APPROVAL` or `REPAIR`, the wire
        transitions to `REJECTED`, its reservation is released back to the
        account with `reservation_active` set false, its `hold_reason_code` is
        cleared to null"
        PRD §2.6: "Any path that ends a wire before execution — rejection,
        cancellation from `PENDING_APPROVAL` or `REPAIR`, or a sanctions
        confirmation that rejects the wire — releases the reservation"

        The same cascade fires while the wire sits in REPAIR: confirmation
        rejects the wire and the reservation is released.

        Design: Difficulty/transitive_cascade/sanctions_confirm_cascades_hit_wire_account
        """
        room = setup_wire_room(business_date="2026-08-10")
        account = room["account"]
        wire = create_submitted_wire(
            account["id"], room["beneficiary"]["id"], "2026-08-10", 400000,
            clear_hits=False)
        hit = simulate_hit(wire["id"], matched_list="INTERNAL_WATCH",
                           matched_party="Vendor Seven", match_score=88)

        repaired = repair_wire(wire["id"], purpose="corrected field")
        assert repaired["status"] == "REPAIR"
        assert repaired["screening_status"] == "REVIEW", (
            "the unresolved hit survives the repair's re-screening")
        assert get_account(account["id"])["daily_reserved_cents"] == 400000

        confirmed = validate_success(api.confirm_sanctions_hit(
            hit["id"], {"rationale": "true match"}, SCREENER), 200)
        assert confirmed["status"] == "CONFIRMED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "REJECTED"
        assert wire_after["reservation_active"] is False
        assert get_account(account["id"])["daily_reserved_cents"] == 0
