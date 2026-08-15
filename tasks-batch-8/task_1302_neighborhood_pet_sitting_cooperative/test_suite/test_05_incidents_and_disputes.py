"""Incidents, disputes, escalation, and their ledger/reliability effects
(PRD §2.5, §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_incident_payload, create_dispute_payload,
    make_member_headers,
    bootstrap_founders, setup_confirmed_sit, setup_completed_sit, setup_settled_sit,
    file_incident, resolve_incident_at_fault, open_dispute, setup_dispute_in_mediation,
    escalate_dispute, resolve_dispute, get_member, list_ledger,
    ADMIN,
)


class TestIncidents:
    def test_incident_creation_filed_with_reporter(self, api):
        """PRD §3.7: "When something goes wrong during a sit, a member files an
        incident on the assignment, giving a `severity` of `MINOR`, `MAJOR`, or
        `EMERGENCY`, a `description` of at least 30 characters, and a `vet_involved`
        flag recording whether the emergency veterinarian was contacted. The caller
        is recorded as `reporter_member_id` and the incident begins `FILED`."

        Design: Corner/endpoints/incident_creation_filed_with_reporter
        """
        sit = setup_confirmed_sit()
        res = api.create_incident(sit["assignment"]["id"], create_incident_payload(
            severity="EMERGENCY",
            description="Pet collapsed; rushed to emergency vet clinic.",
            vet_involved=True), make_member_headers(sit["sitter"]["id"]))
        incident = validate_success(res, 201)
        assert incident["status"] == "FILED"
        assert incident["reporter_member_id"] == sit["sitter"]["id"]
        assert incident["at_fault_member_id"] is None

        fetched = validate_success(api.get_incident(incident["id"], ADMIN), 200)
        assert fetched["severity"] == "EMERGENCY"
        assert fetched["vet_involved"] is True
        assert fetched["sitting_assignment_id"] == sit["assignment"]["id"]

    def test_incident_description_min_length(self, api):
        """PRD §3.7: "When something goes wrong during a sit, a member files an
        incident on the assignment, giving a `severity` of `MINOR`, `MAJOR`, or
        `EMERGENCY`, a `description` of at least 30 characters, and a `vet_involved`
        flag recording whether the emergency veterinarian was contacted."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/incident_description_min_length
        """
        sit = setup_confirmed_sit()
        res = api.create_incident(sit["assignment"]["id"], create_incident_payload(
            description="Twenty-nine chars xxxxxxxxxxx"),  # 29 chars
            make_member_headers(sit["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        ok = api.create_incident(sit["assignment"]["id"], create_incident_payload(
            description="Thirty chars exactly xxxxxxxxx"),  # 30 chars
            make_member_headers(sit["owner"]["id"]))
        incident = validate_success(ok, 201)
        assert incident["status"] == "FILED"
        assert incident["reporter_member_id"] == sit["owner"]["id"]

    def test_resolve_filed_incident_rejected(self, api):
        """PRD §3.7: "An administrator takes it under review, moving it `FILED` →
        `UNDER_REVIEW`, and may dismiss an incident from either of those states,
        ending it as `DISMISSED`."
        PRD §3.7: "Resolution comes in two flavors. Resolving with `outcome` set to
        `AT_FAULT` requires the payload to name an `at_fault_member_id` (omitting it
        fails with `ERR_INVALID_REQUEST`) and ends the incident as
        `RESOLVED_AT_FAULT`: ..."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/resolve_filed_incident_returns_invalid_state
        """
        sit = setup_confirmed_sit()
        incident = file_incident(sit["assignment"]["id"], sit["owner"],
                                 description="Water bowl was empty on arrival.")
        res = api.resolve_incident(incident["id"], {"outcome": "NO_FAULT"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_incident(incident["id"], ADMIN), 200)
        assert after["status"] == "FILED"

    def test_incident_review_then_dismiss_unblocks_settle(self, api):
        """PRD §3.7: "An administrator takes it under review, moving it `FILED` →
        `UNDER_REVIEW`, and may dismiss an incident from either of those states,
        ending it as `DISMISSED`."
        PRD §3.6: "An administrator settles an assignment in
        `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while
        no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open
        incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`."

        Design: Corner/state_machines/incident_review_then_dismiss_valid
        """
        sit = setup_completed_sit()
        incident = file_incident(sit["assignment"]["id"], sit["owner"],
                                 description="Litter box not scooped on day two.")
        reviewed = validate_success(api.begin_review_incident(incident["id"], ADMIN), 200)
        assert reviewed["status"] == "UNDER_REVIEW"
        dismissed = validate_success(api.dismiss_incident(incident["id"], ADMIN), 200)
        assert dismissed["status"] == "DISMISSED"

        settled = validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert settled["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

    def test_incident_penalty_requires_settled_ordering(self, api):
        """PRD §3.7: "Resolving with `outcome` set to `AT_FAULT` requires the
        payload to name an `at_fault_member_id` (omitting it fails with
        `ERR_INVALID_REQUEST`) and ends the incident as `RESOLVED_AT_FAULT`: the
        at-fault member's `reliability_score` drops by 15, and if the assignment was
        already `SETTLED`, an `INCIDENT_PENALTY` entry debits that member half of
        the assignment's `credit_hours_settled`, rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/incident_penalty_requires_settled_ordering
        """
        f = bootstrap_founders()
        # Sit 1: incident resolved AT_FAULT before settle -> no INCIDENT_PENALTY row.
        sit1 = setup_completed_sit(founders=f)
        inc_a = file_incident(sit1["assignment"]["id"], sit1["owner"],
                              description="Pre-settle at-fault incident on sit one.")
        resolve_incident_at_fault(inc_a["id"], f["f2"]["id"])
        validate_success(api.settle_assignment(sit1["assignment"]["id"], ADMIN), 200)
        # Sit 2: settle first, then the at-fault resolution posts the penalty.
        sit2 = setup_settled_sit(founders=f, start_at="2026-09-12T10:00:00Z",
                                 end_at="2026-09-12T14:00:00Z",
                                 owner=f["f1"], pet=sit1["pet"])
        inc_b = file_incident(sit2["assignment"]["id"], sit2["owner"],
                              description="Post-settle at-fault incident on sit two.")
        get_success_data(api.begin_review_incident(inc_b["id"], ADMIN))
        validate_success(api.resolve_incident(
            inc_b["id"], {"outcome": "AT_FAULT", "at_fault_member_id": f["f2"]["id"]}, ADMIN), 200)

        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "INCIDENT_PENALTY"})
        assert len(penalties) == 1, (
            f"Only the post-settle resolution may post INCIDENT_PENALTY, got {len(penalties)}")
        assert penalties[0]["delta_hours"] == pytest.approx(-2.0, abs=0.001)  # 4.00 x 0.5
        assert penalties[0]["sitting_assignment_id"] == sit2["assignment"]["id"]

        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(16.0, abs=0.001)  # 10 + 4 + 4 - 2
        assert f2["reliability_score"] == 24  # 50 - 15 + 2 + 2 - 15

    def test_incident_penalty_posted_only_after_settle(self, api):
        """PRD §3.7: "...the at-fault member's `reliability_score` drops by 15, and
        if the assignment was already `SETTLED`, an `INCIDENT_PENALTY` entry debits
        that member half of the assignment's `credit_hours_settled`, rounded half-up
        to 2 decimal places."

        Design: Difficulty/combinatorial_formula/incident_penalty_requires_settled_ordering
        """
        f = bootstrap_founders()
        # Resolve AT_FAULT while the assignment is still COMPLETED_PENDING_REVIEW:
        # no INCIDENT_PENALTY may post because the assignment is not SETTLED.
        sit = setup_completed_sit(founders=f)
        inc = file_incident(sit["assignment"]["id"], sit["owner"],
                            description="At-fault incident before settlement.")
        resolve_incident_at_fault(inc["id"], f["f2"]["id"])
        assert list_ledger(f["f2"]["id"], params={"entry_type": "INCIDENT_PENALTY"}) == []
        assert get_member(f["f2"]["id"])["reliability_score"] == 35  # 50 - 15


class TestDisputes:
    def test_dispute_creation_links_assignment(self, api):
        """PRD §3.7: "The caller becomes `initiator_member_id` and the dispute
        begins `FILED`. When the dispute references an assignment that is sitting in
        `COMPLETED_PENDING_REVIEW`, that assignment moves to `DISPUTED` and its
        settlement is blocked until the dispute resolves."
        PRD §2.3: "Several collections support equality filters beyond pagination,
        each named after the field it matches: ... disputes filter by `status`,
        `initiator_member_id`, and `respondent_member_id`; ..."

        Design: Corner/endpoints/dispute_creation_links_assignment_and_disputes_it
        """
        sit = setup_completed_sit()
        res = api.create_dispute(create_dispute_payload(
            sit["sitter"]["id"], dispute_type="SITTING_QUALITY",
            statement="Medication schedule was not followed during the sit.",
            sitting_assignment_id=sit["assignment"]["id"]),
            make_member_headers(sit["owner"]["id"]))
        dispute = validate_success(res, 201)
        assert dispute["status"] == "FILED"
        assert dispute["initiator_member_id"] == sit["owner"]["id"]
        assert dispute["sitting_assignment_id"] == sit["assignment"]["id"]

        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "DISPUTED"

        filtered = get_success_data(api.list_disputes(
            ADMIN, params={"respondent_member_id": sit["sitter"]["id"]}))
        assert [d["id"] for d in filtered] == [dispute["id"]]

    def test_dispute_statement_and_conditional_assignment(self, api):
        """PRD §3.7: "A member opens a dispute naming the `respondent_member_id`, a
        `dispute_type` of `SITTING_QUALITY`, `CREDIT_BALANCE`, `ACCESS_DAMAGE`, or
        `BEHAVIOR`, and a `statement` of at least 40 characters; a
        `sitting_assignment_id` may supply context and is required when the type is
        `SITTING_QUALITY`."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/dispute_statement_and_conditional_assignment_requirement
        """
        f = bootstrap_founders()
        res = api.create_dispute(create_dispute_payload(
            f["f2"]["id"], dispute_type="BEHAVIOR",
            statement="Thirty-nine chars xxxxxxxxxxxxxxxxxxxxx"),  # 39 chars
            make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        res = api.create_dispute(create_dispute_payload(
            f["f2"]["id"], dispute_type="SITTING_QUALITY",
            statement="The sitter skipped two scheduled feedings entirely."),
            make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        ok = api.create_dispute(create_dispute_payload(
            f["f2"]["id"], dispute_type="BEHAVIOR",
            statement="Repeatedly rude and dismissive during key handoff."),
            make_member_headers(f["f1"]["id"]))
        dispute = validate_success(ok, 201)
        assert dispute["status"] == "FILED"
        assert dispute["initiator_member_id"] == f["f1"]["id"]

    def test_mediator_without_flag_rejected(self, api):
        """PRD §3.7: "An administrator then assigns a mediator, moving the dispute
        to `MEDIATION`; the proposed `mediator_member_id` must belong to a `VETTED`
        member whose `mediator_flag` is true (otherwise `ERR_MEDIATOR_INVALID`) and
        must be neither the initiator nor the respondent (otherwise
        `ERR_MEDIATOR_CONFLICT`)."

        Design: Corner/validations/mediator_without_flag_returns_mediator_invalid
        """
        f = bootstrap_founders()
        dispute = open_dispute(f["f3"], f["f1"], dispute_type="BEHAVIOR",
                               statement="Keys were returned late three times in a row now.")
        res = api.assign_mediator(dispute["id"], {"mediator_member_id": f["f2"]["id"]}, ADMIN)
        validate_error(res, ApiErrorId.ERR_MEDIATOR_INVALID, expected_status=409)
        after = validate_success(api.get_dispute(dispute["id"], ADMIN), 200)
        assert after["status"] == "FILED"
        assert after["mediator_member_id"] is None

    def test_mediator_is_party_rejected(self, api):
        """PRD §3.7: "An administrator then assigns a mediator, moving the dispute
        to `MEDIATION`; the proposed `mediator_member_id` must belong to a `VETTED`
        member whose `mediator_flag` is true (otherwise `ERR_MEDIATOR_INVALID`) and
        must be neither the initiator nor the respondent (otherwise
        `ERR_MEDIATOR_CONFLICT`)."

        Design: Corner/validations/mediator_is_party_returns_mediator_conflict
        """
        f = bootstrap_founders()
        dispute = open_dispute(f["f3"], f["f2"], dispute_type="ACCESS_DAMAGE",
                               statement="Lockbox found scratched and jammed after the weekend sit.")
        res = api.assign_mediator(dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN)
        validate_error(res, ApiErrorId.ERR_MEDIATOR_CONFLICT, expected_status=409)
        after = validate_success(api.get_dispute(dispute["id"], ADMIN), 200)
        assert after["status"] == "FILED"

    def test_dispute_upheld_posts_ledger_pair(self, api):
        """PRD §3.7: "For a `CREDIT_BALANCE` dispute, the mediator may include a
        non-zero `credit_adjustment_hours`, which posts a `MEDIATION_ADJUSTMENT`
        entry crediting the initiator by that amount and a matching entry debiting
        the respondent by the same amount."
        PRD §2.4: "Entries of type `MEDIATION_ADJUSTMENT` record the originating
        dispute in `dispute_id`; for every other entry type that field is null."

        Design: Corner/state_machines/dispute_upheld_credit_adjustment_posts_ledger_pair
        """
        f = bootstrap_founders()
        dispute = setup_dispute_in_mediation(
            f, initiator_key="f1", respondent_key="f2", dispute_type="CREDIT_BALANCE",
            statement="Believes a prior sit was under-credited by one and a half hours.")
        resolved = resolve_dispute(dispute, f["f3"], "UPHELD",
                                   resolution_notes="Records support the initiator's claim.",
                                   credit_adjustment_hours=1.50)
        assert resolved["status"] == "RESOLVED_UPHELD"
        assert resolved["resolution_notes"] == "Records support the initiator's claim."

        initiator_adj = list_ledger(f["f1"]["id"], params={"entry_type": "MEDIATION_ADJUSTMENT"})
        respondent_adj = list_ledger(f["f2"]["id"], params={"entry_type": "MEDIATION_ADJUSTMENT"})
        assert len(initiator_adj) == 1
        assert initiator_adj[0]["delta_hours"] == pytest.approx(1.5, abs=0.001)
        assert initiator_adj[0]["dispute_id"] == dispute["id"]
        assert len(respondent_adj) == 1
        assert respondent_adj[0]["delta_hours"] == pytest.approx(-1.5, abs=0.001)
        assert respondent_adj[0]["dispute_id"] == dispute["id"]

        assert get_member(f["f1"]["id"])["credit_balance_hours"] == pytest.approx(11.5, abs=0.001)
        assert get_member(f["f2"]["id"])["credit_balance_hours"] == pytest.approx(8.5, abs=0.001)

    def test_escalate_after_resolve_rejected(self, api):
        """PRD §3.7: "From `MEDIATION`, the assigned mediator — and only the
        mediator, verified by identity (`ERR_FORBIDDEN`) — steers the dispute to one
        of three endings."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/escalate_after_resolve_returns_invalid_state
        """
        f = bootstrap_founders()
        dispute = setup_dispute_in_mediation(
            f, initiator_key="f1", respondent_key="f2", dispute_type="BEHAVIOR",
            statement="Disagreement over arrival times and communication tone.")
        resolve_dispute(dispute, f["f3"], "DISMISSED",
                        resolution_notes="Misunderstanding; both parties agreed to drop it.")

        res = api.escalate_dispute(dispute["id"], {"resolution_notes": "Attempting late escalation."},
                                   make_member_headers(f["f3"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_dispute(dispute["id"], ADMIN), 200)
        assert after["status"] == "RESOLVED_DISMISSED"
        assert get_member(f["f2"]["id"])["reliability_score"] == 50

    def test_dispute_resolve_transitive_settlement_chain(self, api):
        """PRD §3.7: "In either resolution, when the dispute references an
        assignment currently `DISPUTED`, the assignment settles — running the same
        settlement cascade as §3.6, from the final-variant computation through the
        reliability bonus."
        PRD §3.6: "The cascade then settles accounts: the sitter's
        `credit_balance_hours` increases by `credit_hours_settled` with a
        `SIT_EARNED` entry, the owner's `credit_balance_hours` decreases by the same
        amount with a `SIT_SPENT` entry, the sitter's `provisional_credit_hours` is
        reduced by the request's `credit_hours_offered`, and the sitter's
        `reliability_score` gains 2 points, capped at 100."

        Design: Difficulty/transitive_cascade/dispute_resolve_transitive_settlement_ledger_chain
        """
        f = bootstrap_founders()
        sit = setup_completed_sit(founders=f)
        dispute = open_dispute(
            f["f1"], f["f2"], dispute_type="SITTING_QUALITY",
            statement="Feeding instructions were not followed on day one.",
            sitting_assignment_id=sit["assignment"]["id"])
        get_success_data(api.assign_mediator(
            dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))

        resolved = resolve_dispute(dispute, f["f3"], "DISMISSED",
                                   resolution_notes="Instructions ambiguous; both parties acted in good faith.")
        assert resolved["status"] == "RESOLVED_DISMISSED"

        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "SETTLED"
        assert asg["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

        sitter = get_member(f["f2"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(14.0, abs=0.001)
        assert sitter["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert sitter["reliability_score"] == 52
        owner = get_member(f["f1"]["id"])
        assert owner["credit_balance_hours"] == pytest.approx(6.0, abs=0.001)

        earned = list_ledger(f["f2"]["id"], params={"entry_type": "SIT_EARNED"})
        assert len(earned) == 1 and earned[0]["delta_hours"] == pytest.approx(4.0, abs=0.001)
        spent = list_ledger(f["f1"]["id"], params={"entry_type": "SIT_SPENT"})
        assert len(spent) == 1 and spent[0]["delta_hours"] == pytest.approx(-4.0, abs=0.001)

        req = validate_success(api.get_sitting_request(sit["request"]["id"], ADMIN), 200)
        assert req["status"] == "COMPLETED"

    def test_dispute_dismissed_settles_assignment(self, api):
        """PRD §3.7: "In either resolution, when the dispute references an
        assignment currently `DISPUTED`, the assignment settles — running the same
        settlement cascade as §3.6, from the final-variant computation through the
        reliability bonus."

        Design: Difficulty/transitive_cascade/dispute_resolve_transitive_settlement_ledger_chain
        """
        f = bootstrap_founders()
        sit = setup_completed_sit(founders=f)
        dispute = open_dispute(
            f["f1"], f["f2"], dispute_type="SITTING_QUALITY",
            statement="Medication schedule appeared not to be followed.",
            sitting_assignment_id=sit["assignment"]["id"])
        get_success_data(api.assign_mediator(
            dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        asg_mid = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg_mid["status"] == "DISPUTED"

        resolve_dispute(dispute, f["f3"], "DISMISSED",
                        resolution_notes="Records show the schedule was followed.")
        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "SETTLED"
        assert asg["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)
        assert get_member(f["f2"]["id"])["reliability_score"] == 52

    def test_assignment_fork_rejoin_settlement(self, api):
        """PRD §3.7: "In either resolution, when the dispute references an
        assignment currently `DISPUTED`, the assignment settles — running the same
        settlement cascade as §3.6, from the final-variant computation through the
        reliability bonus."
        PRD §3.6: "An administrator settles an assignment in
        `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while
        no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open
        incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`."

        Design: Difficulty/non_linear_state_machine/assignment_disputed_fork_rejoin_settlement
        """
        f = bootstrap_founders()
        # Branch A: direct COMPLETED_PENDING_REVIEW -> SETTLED.
        sit_a = setup_completed_sit(founders=f)
        # Branch B: COMPLETED_PENDING_REVIEW -> DISPUTED -> SETTLED via dismissal.
        sit_b = setup_completed_sit(founders=f, start_at="2026-09-11T10:00:00Z",
                                    end_at="2026-09-11T14:00:00Z",
                                    owner=f["f1"], pet=sit_a["pet"])
        dispute = open_dispute(
            f["f1"], f["f2"], dispute_type="SITTING_QUALITY",
            statement="Sitter left the gate open and the dog got out twice.",
            sitting_assignment_id=sit_b["assignment"]["id"])
        get_success_data(api.assign_mediator(
            dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        asg_b_mid = validate_success(api.get_assignment(sit_b["assignment"]["id"], ADMIN), 200)
        assert asg_b_mid["status"] == "DISPUTED"
        resolve_dispute(dispute, f["f3"], "DISMISSED",
                        resolution_notes="Gate latch was faulty; no sitter negligence found.")

        settled_a = validate_success(api.settle_assignment(sit_a["assignment"]["id"], ADMIN), 200)
        assert settled_a["status"] == "SETTLED"
        assert settled_a["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

        asg_b = validate_success(api.get_assignment(sit_b["assignment"]["id"], ADMIN), 200)
        assert asg_b["status"] == "SETTLED"
        assert asg_b["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

        sitter = get_member(f["f2"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(18.0, abs=0.001)  # 10 + 4 + 4
        assert sitter["reliability_score"] == 54  # 50 + 2 + 2
        assert validate_success(api.get_dispute(dispute["id"], ADMIN), 200)["status"] == "RESOLVED_DISMISSED"

    def test_both_branches_converge_identical_settlement(self, api):
        """PRD §3.7: "In either resolution, when the dispute references an
        assignment currently `DISPUTED`, the assignment settles — running the same
        settlement cascade as §3.6, from the final-variant computation through the
        reliability bonus."
        PRD §3.6: "The cascade then settles accounts: the sitter's
        `credit_balance_hours` increases by `credit_hours_settled` with a
        `SIT_EARNED` entry, ..."

        Design: Difficulty/non_linear_state_machine/assignment_disputed_fork_rejoin_settlement
        """
        f = bootstrap_founders()
        sit_a = setup_completed_sit(founders=f)
        sit_b = setup_completed_sit(founders=f, start_at="2026-09-11T10:00:00Z",
                                    end_at="2026-09-11T14:00:00Z",
                                    owner=f["f1"], pet=sit_a["pet"])
        dispute = open_dispute(
            f["f1"], f["f2"], dispute_type="SITTING_QUALITY",
            statement="Visit instructions were not followed during the sit.",
            sitting_assignment_id=sit_b["assignment"]["id"])
        get_success_data(api.assign_mediator(
            dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        resolve_dispute(dispute, f["f3"], "DISMISSED",
                        resolution_notes="No negligence established on the record.")
        validate_success(api.settle_assignment(sit_a["assignment"]["id"], ADMIN), 200)

        earned = list_ledger(f["f2"]["id"], params={"entry_type": "SIT_EARNED"})
        assert len(earned) == 2
        assert all(row["delta_hours"] == pytest.approx(4.0, abs=0.001) for row in earned)
        assert get_member(f["f2"]["id"])["credit_balance_hours"] == pytest.approx(18.0, abs=0.001)
