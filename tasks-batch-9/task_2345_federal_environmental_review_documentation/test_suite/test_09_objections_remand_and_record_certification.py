"""Objections against a signed decision: the half-open filing window, standing,
the denial that changes nothing, the remand cascade that unwinds the decision and
restores the office ledger, and the terminal certification of the record.
"""
from test_helpers import (
    DECIDING_OFFICIAL_HEADERS,
    DECIDING_OFFICIAL_USER_ID,
    OBJECTION_REVIEWING_OFFICER_HEADERS,
    OBJECTION_REVIEWING_OFFICER_USER_ID,
    PUBLIC_COMMENTER_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    approx_score,
    assert_instant_equals,
    assert_objection,
    assert_office_ledger_equals,
    assert_sequence_contiguous,
    entries_with_code,
    find_entry,
    fixtures,
    make_objection_reviewing_officer_headers,
    objection_payload,
    resolve_objection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The objector the design pins, filing on the resource area of the analysis.
RIVERA_OBJECTION = {
    "objector_name": "J. Rivera",
    "objector_type": "COMMENTER",
    "basis_issue_area": "BIOLOGICAL",
    "standing_basis": "SUBSTANTIVE_COMMENT",
}

#: An objector who never participated during the comment period.
UNAFFILIATED_OBJECTION = {
    "objector_name": "Unaffiliated Party",
    "objector_type": "OTHER",
    "basis_issue_area": "AIR",
    "standing_basis": "NONE",
}

#: A single commitment package, contrasting with the canonical pair.
SINGLE_COMMITMENT = [
    {"measure_text": "Seasonal timing restriction on the treatment unit",
     "cost_estimate_cents": 1200000, "monitoring_years": 3,
     "annual_monitoring_cost_cents": 450000, "reduction_points": 9.0},
]

REMAND_NOTE = "Winter range analysis must be reopened before a decision may issue"
DENIAL_NOTE = "The published analysis already addresses the raised issue"


def _mitigated_decision_with_objection():
    """The canonical mitigated finding, signed and objected to."""
    return fixtures.setup_filed_objection(
        decision_type="MITIGATED_FONSI",
        mitigations=fixtures.CANONICAL_MITIGATIONS,
        objection_overrides=dict(RIVERA_OBJECTION),
    )


def _signed_fonsi_with_objection():
    """A plain finding of no significant impact, signed and objected to."""
    return fixtures.setup_filed_objection(
        decision_type="FONSI",
        objection_overrides=dict(RIVERA_OBJECTION),
    )


class TestRemandCascade:
    """The remand is the head of a three-hop unwinding."""

    def test_the_remand_vacates_the_decision_releases_the_commitments_and_reverts_the_document(
        self, client
    ):
        """Remanding the objection vacates the decision, which releases both
        commitments and debits the ledger, which reverts the assessment and the
        review stage.

        PRD 3.9: "Because the decision is vacated, every `MitigationCommitment`
        of that decision whose `status` is `BINDING` moves `BINDING → RELEASED`
        with its `monitoring_status` set to `RELEASED`, and the decision's
        `binding_obligation_cents` is subtracted from the office's
        `binding_obligation_cents`, restoring the ledger to its exact
        pre-signature value."
        PRD 3.9: "Because the decision is vacated, every `NepaDocument` of the
        action whose `publication_status` is `FINAL` reverts that axis `FINAL →
        DRAFT` while its `comment_status` stays `CLOSED`, and the action reverts
        `DECIDED → COMMENT_CLOSED`."

        Design: Difficulty/transitive_cascade/objection_remand_vacates_decision_releases_commitments_and_reverts_document
        """
        ctx = _mitigated_decision_with_objection()
        action_id = ctx["action"]["id"]
        assert ctx["decision"]["status"] == "SIGNED"
        assert ctx["decision"]["binding_obligation_cents"] == 3487823
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]),
                                   3487823)

        remanded = validate_success(
            client.resolve_objection(
                ctx["objection"]["id"],
                resolve_objection_payload("REMANDED", resolution_note=REMAND_NOTE),
                OBJECTION_REVIEWING_OFFICER_HEADERS,
            )
        )
        assert remanded["status"] == "REMANDED", "hop one: the objection is remanded"
        assert remanded["resolution_note"] == REMAND_NOTE
        assert_objection(remanded)

        vacated = fixtures.read_decision(ctx["decision"]["id"])
        assert vacated["status"] == "VACATED", "hop two: the decision is unwound"
        assert vacated["binding_obligation_cents"] == 3487823, (
            "the vacated decision keeps its cent fields as the historical record"
        )
        for commitment in ctx["mitigations"]:
            released = fixtures.read_mitigation(commitment["id"])
            assert released["status"] == "RELEASED"
            assert released["monitoring_status"] == "RELEASED"
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "DRAFT", (
            "hop three: the publication axis reverts"
        )
        assert document["comment_status"] == "CLOSED", (
            "the comment axis is untouched by the cascade"
        )
        assert fixtures.read_action(action_id)["review_stage"] == "COMMENT_CLOSED"

        entries = fixtures.read_record_entries(action_id)
        resolved_entry = find_entry(entries, "OBJECTION_RESOLVED")
        vacated_entry = find_entry(entries, "DECISION_VACATED")
        assert resolved_entry is not None and vacated_entry is not None
        assert resolved_entry["sequence_no"] < vacated_entry["sequence_no"], (
            "the resolution is recorded before the cascade it causes"
        )

    def test_a_denial_fires_none_of_the_three_hops(self, client):
        """The same objection denied instead of remanded leaves the decision, the
        commitments, the ledger, the document and the stage exactly as they were.

        PRD 3.9: "A denial deliberately triggers no cascade: the decision's
        `status` stays `SIGNED`, every `BINDING` commitment stays `BINDING` with
        its `monitoring_status` unchanged, the office's `binding_obligation_cents`
        is untouched, every document keeps its `publication_status`, and the
        action stays at `review_stage` `DECIDED`."
        PRD 3.9: "A denial records the `resolution_note`, moves the objection
        `FILED → DENIED`, and appends an `OBJECTION_RESOLVED` entry with the
        corresponding `record_entry_count` increment."

        Design: Difficulty/transitive_cascade/objection_remand_vacates_decision_releases_commitments_and_reverts_document
        """
        ctx = _mitigated_decision_with_objection()
        action_id = ctx["action"]["id"]

        denied = validate_success(
            client.resolve_objection(
                ctx["objection"]["id"],
                resolve_objection_payload("DENIED", resolution_note=DENIAL_NOTE),
                OBJECTION_REVIEWING_OFFICER_HEADERS,
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["resolution_note"] == DENIAL_NOTE

        decision = fixtures.read_decision(ctx["decision"]["id"])
        assert decision["status"] == "SIGNED", "a denial does not vacate"
        assert decision["objection_count"] == 1, (
            "a denied objection still counts toward the decision's tally"
        )
        for commitment in ctx["mitigations"]:
            untouched = fixtures.read_mitigation(commitment["id"])
            assert untouched["status"] == "BINDING"
            assert untouched["monitoring_status"] == "SCHEDULED"
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]),
                                   3487823)

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "FINAL"
        assert document["comment_status"] == "CLOSED"
        assert fixtures.read_action(action_id)["review_stage"] == "DECIDED"

        entries = fixtures.read_record_entries(action_id)
        assert entries_with_code(entries, "DECISION_VACATED") == [], (
            "no vacatur was recorded"
        )
        assert len(entries_with_code(entries, "OBJECTION_RESOLVED")) == 1


class TestLedgerCompensation:
    """Signing and vacating are exactly compensating on the office ledger."""

    def test_the_ledger_returns_to_its_exact_pre_signature_value(self, client):
        """The ledger runs 0, 3487823 and back to 0 while the administrative
        record only grows.

        PRD 2.12: "The pair is exactly compensating: signing a decision and later
        vacating it restores `binding_obligation_cents` to its exact pre-signature
        value with no drift, even though the vacated decision retains its
        historical cent fields as part of the record."
        PRD 3.9: "A `DECISION_VACATED` entry is appended alongside the
        `OBJECTION_RESOLVED` entry, in the cascade order of §2.4, and
        `record_entry_count` rises for each."

        Design: Difficulty/compensating_invariant/office_obligation_ledger_restored_exactly_after_sign_then_remand
        """
        ctx = fixtures.setup_drafted_decision(
            decision_type="MITIGATED_FONSI",
            mitigations=fixtures.CANONICAL_MITIGATIONS,
        )
        action_id = ctx["action"]["id"]
        before = fixtures.read_action(action_id)
        entries_before_signature = before["record_entry_count"]
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)

        fixtures.set_clock(fixtures.SIGNATURE_INSTANT)
        signed = validate_success(
            client.sign_decision(ctx["decision"]["id"], DECIDING_OFFICIAL_HEADERS)
        )
        assert signed["binding_obligation_cents"] == 3487823
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]),
                                   3487823)
        assert fixtures.read_action(action_id)["record_entry_count"] == (
            entries_before_signature + 1
        ), "the signature appends exactly one entry"

        objection = fixtures.file_objection(ctx["decision"]["id"],
                                           **RIVERA_OBJECTION)
        fixtures.resolve_objection(objection["id"], "REMANDED",
                                   resolution_note=REMAND_NOTE)

        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)
        after = fixtures.read_action(action_id)
        assert after["record_entry_count"] == entries_before_signature + 4, (
            "the signature, the filing, the resolution and the vacatur each "
            "appended one entry"
        )
        assert after["record_entry_count"] > entries_before_signature + 1, (
            "the record only ever grows"
        )
        assert fixtures.read_decision(ctx["decision"]["id"])[
            "binding_obligation_cents"] == 3487823, (
            "the vacated row keeps the figure the ledger no longer counts"
        )

        entries = fixtures.read_record_entries(action_id)
        assert len(entries) == after["record_entry_count"]
        assert_sequence_contiguous(entries)

    def test_the_compensation_is_exact_for_a_different_commitment_package(
        self, client
    ):
        """A single commitment credits and debits the same figure, whatever that
        figure is.

        PRD 2.12: "Signing a decision adds that decision's
        `binding_obligation_cents` to the office total. The vacatur of a signed
        decision on remand subtracts the same amount."
        PRD 3.9: "`RELEASED` is terminal for a commitment and `VACATED` is
        terminal for a decision, so the review must be re-decided on a fresh
        draft."

        Design: Difficulty/compensating_invariant/office_obligation_ledger_restored_exactly_after_sign_then_remand
        """
        ctx = fixtures.setup_signed_decision(decision_type="MITIGATED_FONSI",
                                            mitigations=SINGLE_COMMITMENT)
        decision = ctx["decision"]
        assert decision["base_obligation_cents"] == 2597250, (
            "three years of 450000 cents escalated by 1.035 add 1397250 cents"
        )
        assert decision["binding_obligation_cents"] == (
            decision["base_obligation_cents"] + decision["contingency_fee_cents"]
        )
        credited = decision["binding_obligation_cents"]
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]),
                                   credited)

        objection = fixtures.file_objection(decision["id"], **RIVERA_OBJECTION)
        fixtures.resolve_objection(objection["id"], "REMANDED",
                                   resolution_note=REMAND_NOTE)

        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)
        vacated = fixtures.read_decision(decision["id"])
        assert vacated["status"] == "VACATED"
        assert vacated["binding_obligation_cents"] == credited, (
            "the debit matched the credit exactly and left the history intact"
        )
        assert fixtures.read_mitigation(ctx["mitigations"][0]["id"])["status"] == (
            "RELEASED"
        )


class TestObjectionFilingWindow:
    """The window is half-open, and standing is a business rule rather than an
    input rule."""

    def test_a_filing_at_the_closing_instant_is_refused(self, client):
        """The closing instant is excluded, so a filing at exactly that instant is
        outside the window.

        PRD 3.9: "A `PublicCommenter` or an `AgencyLiaison` may file an
        `Objection` at or after `objection_window_opens_at` and strictly before
        `objection_window_closes_at`; filing outside that span is rejected with
        `ERR_OBJECTION_WINDOW_CLOSED`."
        PRD 3.9: "An objection names an `objector_name`, an `objector_type` of
        `COMMENTER`, `AGENCY`, `TRIBE` or `OTHER`, a `basis_issue_area` naming the
        resource area it is grounded in, and a `standing_basis` of
        `SUBSTANTIVE_COMMENT`, `AGENCY_CONSULTATION` or `NONE`."

        Design: Corner/validations/corner_objection_filed_at_window_close_instant_is_rejected
        """
        ctx = fixtures.setup_signed_fonsi()
        decision_id = ctx["decision"]["id"]
        assert_instant_equals(ctx["decision"]["objection_window_closes_at"],
                              fixtures.OBJECTION_WINDOW_CLOSE)

        fixtures.set_clock(fixtures.OBJECTION_WINDOW_CLOSE)
        refused = client.file_objection(decision_id,
                                       objection_payload(**RIVERA_OBJECTION),
                                       PUBLIC_COMMENTER_HEADERS)
        validate_error(refused, ApiErrorId.OBJECTION_WINDOW_CLOSED.value,
                       expected_status=409)

        decision = fixtures.read_decision(decision_id)
        assert decision["objection_count"] == 0
        assert decision["status"] == "SIGNED"
        _, meta = validate_paginated(
            client.list_decision_objections(decision_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert meta["total_count"] == 0, "no objection row was created"

    def test_a_filing_without_standing_is_refused_as_a_business_failure(
        self, client
    ):
        """`NONE` is a valid enum member that the filing rule nonetheless refuses,
        and a participant's filing is accepted.

        PRD 3.9: "A `standing_basis` of `NONE` means the objector did not
        participate during the comment period and is rejected with
        `ERR_OBJECTION_STANDING_MISSING`."
        PRD 3.9: "A filed objection has `status` `FILED` and `resolution_note`
        null, refreshes the decision's `objection_count` — the number of that
        decision's objections whose `status` is `FILED`, `REMANDED` or `DENIED` —
        and appends an `OBJECTION_FILED` entry with the corresponding
        `record_entry_count` increment."

        Design: Corner/errors/corner_error_objection_standing_missing_rejects_filing
        """
        ctx = fixtures.setup_signed_fonsi()
        decision_id = ctx["decision"]["id"]

        refused = client.file_objection(decision_id,
                                       objection_payload(**UNAFFILIATED_OBJECTION),
                                       PUBLIC_COMMENTER_HEADERS)
        validate_error(refused, ApiErrorId.OBJECTION_STANDING_MISSING.value,
                       expected_status=409)
        assert fixtures.read_decision(decision_id)["objection_count"] == 0

        accepted = validate_success(
            client.file_objection(decision_id,
                                  objection_payload(**RIVERA_OBJECTION),
                                  PUBLIC_COMMENTER_HEADERS),
            expected_status=201,
        )
        assert accepted["status"] == "FILED"
        assert accepted["resolution_note"] is None
        assert_objection(accepted)
        assert fixtures.read_decision(decision_id)["objection_count"] == 1


class TestObjectionResolutionGuards:
    """A resolution happens once, and never by the signer."""

    def test_a_resolved_objection_cannot_be_resolved_again(self, client):
        """A denial is terminal, so replaying the resolution with a remand is
        refused and nothing cascades.

        PRD 2.5: "8. State admissibility of the target row and of every row named
        in the transition's preconditions — `ERR_INVALID_STATE`."
        PRD 3.9: "An `ObjectionReviewingOfficer` resolves a `FILED` objection with
        a `disposition` of `DENIED` or `REMANDED` and a `resolution_note` that
        must be present and non-empty, and whose own `X-User-ID` must differ from
        the decision's `signed_by_user_id` per §2.11."

        Design: Corner/state_machines/corner_resolve_objection_twice_is_rejected
        """
        ctx = _signed_fonsi_with_objection()
        action_id = ctx["action"]["id"]
        objection_id = ctx["objection"]["id"]
        fixtures.resolve_objection(objection_id, "DENIED",
                                   resolution_note=DENIAL_NOTE)

        refused = client.resolve_objection(
            objection_id,
            resolve_objection_payload(
                "REMANDED", resolution_note="Second attempt at the same objection"),
            OBJECTION_REVIEWING_OFFICER_HEADERS,
        )
        validate_error(refused, ApiErrorId.INVALID_STATE.value,
                       expected_status=409)

        objection = fixtures.read_objection(objection_id)
        assert objection["status"] == "DENIED"
        assert objection["resolution_note"] == DENIAL_NOTE, (
            "the first resolution note is intact"
        )
        assert fixtures.read_decision(ctx["decision"]["id"])["status"] == "SIGNED", (
            "the replayed call did not vacate the decision"
        )
        assert_office_ledger_equals(fixtures.read_office(ctx["office"]["id"]), 0)
        assert fixtures.read_action(action_id)["review_stage"] == "DECIDED"

        entries = fixtures.read_record_entries(action_id)
        assert len(entries_with_code(entries, "OBJECTION_RESOLVED")) == 1, (
            "exactly one resolution is recorded"
        )

    def test_the_signer_may_not_resolve_an_objection_to_their_own_decision(
        self, client
    ):
        """The reviewing officer's identifier must differ from the signer's, and a
        different officer's identical call succeeds.

        PRD 2.11: "At objection resolution, the resolving
        `ObjectionReviewingOfficer`'s `X-User-ID` must differ from the decision's
        `signed_by_user_id`."
        PRD 3.9: "A denial deliberately triggers no cascade: the decision's
        `status` stays `SIGNED`, every `BINDING` commitment stays `BINDING` with
        its `monitoring_status` unchanged, the office's `binding_obligation_cents`
        is untouched, every document keeps its `publication_status`, and the
        action stays at `review_stage` `DECIDED`."

        Design: Corner/rbac/corner_signer_cannot_resolve_an_objection_to_their_own_decision
        """
        ctx = _signed_fonsi_with_objection()
        objection_id = ctx["objection"]["id"]
        assert ctx["decision"]["signed_by_user_id"] == DECIDING_OFFICIAL_USER_ID

        refused = client.resolve_objection(
            objection_id,
            resolve_objection_payload(
                "DENIED",
                resolution_note=("Signer attempting to close the challenge to "
                                 "their own signature")),
            make_objection_reviewing_officer_headers(DECIDING_OFFICIAL_USER_ID),
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value,
                       expected_status=403)

        untouched = fixtures.read_objection(objection_id)
        assert untouched["status"] == "FILED"
        assert untouched["resolution_note"] is None

        accepted = validate_success(
            client.resolve_objection(
                objection_id,
                resolve_objection_payload("DENIED", resolution_note=DENIAL_NOTE),
                make_objection_reviewing_officer_headers(
                    OBJECTION_REVIEWING_OFFICER_USER_ID),
            )
        )
        assert accepted["status"] == "DENIED"
        assert fixtures.read_decision(ctx["decision"]["id"])["status"] == "SIGNED", (
            "a denial leaves the signature standing"
        )


class TestRecordCertification:
    """Certification is the terminal act, and it happens once."""

    def test_a_still_filed_objection_blocks_certification(self, client):
        """The temporal gate passes at the closing instant, yet the pending
        objection blocks certification until it is resolved.

        PRD 3.9: "Certification requires the action's `review_stage` to be
        `DECIDED`, the decision's `status` to be `SIGNED`, the current logical
        time to be at or after `objection_window_closes_at` — an earlier attempt
        is rejected with `ERR_TEMPORAL_CONFLICT` — and no objection on the
        decision to remain with `status` `FILED`, with a still-pending objection
        rejected as `ERR_OBJECTIONS_PENDING`."
        PRD 3.9: "Certification sets the action's `record_certified_at` to the
        current logical time, advances the action `DECIDED → RECORD_CERTIFIED`,
        appends a `RECORD_CERTIFIED` entry and increments `record_entry_count`."

        Design: Corner/validations/corner_certify_record_while_objection_still_filed_is_rejected
        """
        ctx = _signed_fonsi_with_objection()
        action_id = ctx["action"]["id"]
        decision_id = ctx["decision"]["id"]
        fixtures.set_clock(fixtures.OBJECTION_WINDOW_CLOSE)

        refused = client.certify_record(decision_id, REVIEWING_OFFICIAL_HEADERS)
        validate_error(refused, ApiErrorId.OBJECTIONS_PENDING.value,
                       expected_status=409)
        blocked = fixtures.read_action(action_id)
        assert blocked["review_stage"] == "DECIDED"
        assert blocked["record_certified_at"] is None

        denied = fixtures.resolve_objection(ctx["objection"]["id"], "DENIED",
                                           resolution_note=DENIAL_NOTE)
        assert denied["status"] == "DENIED"
        assert fixtures.read_decision(decision_id)["status"] == "SIGNED"

        validate_success(client.certify_record(decision_id,
                                              REVIEWING_OFFICIAL_HEADERS))
        certified = fixtures.read_action(action_id)
        assert certified["review_stage"] == "RECORD_CERTIFIED"
        assert_instant_equals(certified["record_certified_at"],
                              "2026-12-16T12:00:00Z",
                              "record_certified_at is the current logical time")

    def test_a_certified_record_refuses_a_second_certification(self, client):
        """The terminal stage locks the action, and the certification instant does
        not move.

        PRD 3.9: "Because `record_certified_at` is then non-null, a second
        certification, like a later remand, is rejected with
        `ERR_RECORD_ALREADY_CERTIFIED`, and `RECORD_CERTIFIED` is terminal for the
        action."
        PRD 3.9: "Certifying the litigation record is the terminal act, and it
        belongs to a `ReviewingOfficial` rather than to the office that prepared
        the review."

        Design: Corner/state_machines/corner_certified_record_is_terminal_and_rejects_recertification
        """
        ctx = fixtures.setup_signed_fonsi()
        action_id = ctx["action"]["id"]
        decision_id = ctx["decision"]["id"]
        fixtures.set_clock(fixtures.OBJECTION_WINDOW_CLOSE)

        validate_success(client.certify_record(decision_id,
                                              REVIEWING_OFFICIAL_HEADERS))
        certified = fixtures.read_action(action_id)
        assert certified["review_stage"] == "RECORD_CERTIFIED"
        assert_instant_equals(certified["record_certified_at"],
                              "2026-12-16T12:00:00Z")

        refused = client.certify_record(decision_id, REVIEWING_OFFICIAL_HEADERS)
        validate_error(refused, ApiErrorId.RECORD_ALREADY_CERTIFIED.value,
                       expected_status=409)

        unchanged = fixtures.read_action(action_id)
        assert unchanged["review_stage"] == "RECORD_CERTIFIED"
        assert_instant_equals(unchanged["record_certified_at"],
                              "2026-12-16T12:00:00Z",
                              "the certification instant did not move")
        assert unchanged["max_unmitigated_score"] == approx_score(70.21), (
            "certification rewrites none of the action's derived figures"
        )

        entries = fixtures.read_record_entries(action_id)
        assert len(entries_with_code(entries, "RECORD_CERTIFIED")) == 1, (
            "exactly one certification is recorded"
        )
        assert_sequence_contiguous(entries)
