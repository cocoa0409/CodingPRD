"""Screening for extraordinary circumstances: the unbounded return-and-resubmit
cycle, and the escalation cascade a triggered screen fires.
"""
from test_helpers import (
    NEPA_COORDINATOR_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    assert_ec_screen,
    assert_sequence_contiguous,
    document_payload,
    ec_adjudication_payload,
    ec_finding,
    entries_with_code,
    find_entry,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The first rework: the wetland finding is now declared, but at severity 1,
#: which is below the office's severity trigger threshold of 3.
FIRST_REWORK_FINDINGS = [
    ec_finding("EC_HISTORIC", False, 0, "No historic properties in the action area"),
    ec_finding("EC_ENDANGERED_SPECIES", True, 2,
               "Lynx transit habitat, discountable effects"),
    ec_finding("EC_WETLAND", True, 1, "0.2 ha incidental wetland, avoided by design"),
]

#: The second rework, which finally describes the avoidance design.
SECOND_REWORK_FINDINGS = [
    ec_finding("EC_HISTORIC", False, 0, "No historic properties in the action area"),
    ec_finding("EC_ENDANGERED_SPECIES", True, 2,
               "Lynx transit habitat, discountable effects"),
    ec_finding("EC_WETLAND", True, 1,
               "0.2 ha wetland avoided by a 30 m equipment exclusion buffer"),
]

#: A screen whose endangered-species finding is present at a severity above the
#: office trigger threshold, so its triggered_codes list is non-empty.
OCCUPIED_NEST_FINDINGS = [
    ec_finding("EC_ENDANGERED_SPECIES", True, 4,
               "Occupied nest within the treatment unit"),
    ec_finding("EC_HISTORIC", False, 0, "No recorded properties"),
    ec_finding("EC_WETLAND", False, 0, "No mapped wetland"),
]


class TestReturnAndResubmitCycle:
    """The screen may travel SUBMITTED → RETURNED → SUBMITTED without limit."""

    def test_two_rework_rounds_carry_the_screen_round_to_three(self, client):
        """Each resubmission adds one to `screen_round`, replaces the findings,
        recomputes the derived fields and clears the adjudicator's note.

        PRD 3.2: "A new screen is created with `screen_round` equal to 1,
        `status` `SUBMITTED`, and `adjudicator_note` null."
        PRD 3.2: "A screen that was returned can be reworked without limit.
        Resubmission by a `NepaCoordinator` moves the screen `RETURNED →
        SUBMITTED`, replaces `findings` with the resubmitted array subject to the
        same constraints, increments `screen_round` by one, recomputes
        `triggered_codes` and `max_severity` from the new array, and clears
        `adjudicator_note` back to null."

        Design: Difficulty/non_linear_state_machine/ec_screen_returned_resubmit_cycle_tracks_round_count
        """
        ctx = fixtures.setup_office_and_action()
        screen = fixtures.submit_screen(ctx["action"]["id"],
                                        findings=fixtures.CLEARED_SCREEN_FINDINGS)
        assert screen["screen_round"] == 1, "a new screen opens on round 1"
        assert screen["status"] == "SUBMITTED"
        assert screen["adjudicator_note"] is None

        returned = validate_success(
            client.adjudicate_ec_screen(
                screen["id"],
                ec_adjudication_payload(
                    "RETURNED",
                    adjudicator_note=("Narrative for the wetland code is missing "
                                      "supporting survey data"),
                ),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["screen_round"] == 1, (
            "a return does not advance the round counter; the resubmission does"
        )
        assert returned["adjudicator_note"], "a RETURNED disposition records its note"

        resubmitted = validate_success(
            client.resubmit_ec_screen(screen["id"],
                                      {"findings": FIRST_REWORK_FINDINGS},
                                      NEPA_COORDINATOR_HEADERS)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["screen_round"] == 2
        assert resubmitted["adjudicator_note"] is None, (
            "resubmission clears the note the adjudicator left behind"
        )
        assert_ec_screen(resubmitted)

        returned_again = validate_success(
            client.adjudicate_ec_screen(
                screen["id"],
                ec_adjudication_payload(
                    "RETURNED",
                    adjudicator_note="Wetland avoidance design still not described",
                ),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert returned_again["status"] == "RETURNED"
        assert returned_again["screen_round"] == 2

        third_round = validate_success(
            client.resubmit_ec_screen(screen["id"],
                                      {"findings": SECOND_REWORK_FINDINGS},
                                      NEPA_COORDINATOR_HEADERS)
        )
        assert third_round["screen_round"] == 3, (
            "the cycle is unbounded and the round counter records how many "
            "rounds it took"
        )
        assert third_round["max_severity"] == 2, (
            "the largest severity among the present findings is the lynx finding"
        )
        assert third_round["triggered_codes"] == [], (
            "no present finding reaches the office severity trigger threshold"
        )

        cleared = validate_success(
            client.adjudicate_ec_screen(
                screen["id"],
                ec_adjudication_payload(
                    "CLEARED",
                    adjudicator_note=("Avoidance design accepted; no extraordinary "
                                      "circumstance triggered"),
                ),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["screen_round"] == 3, (
            "clearing the screen leaves the round count where the rework left it"
        )

    def test_returns_leave_the_action_untouched_until_an_outcome_lands(self, client):
        """Across both returns the action keeps its null outcome and its stage,
        and only the clearing adjudication moves it and writes the record.

        PRD 3.2: "Critically, a return is not an adjudicated outcome: the action's
        `ec_screen_outcome` and `extraordinary_circumstance_flag` are left exactly
        as they were, the action's `review_stage` does not move, and no record
        entry is appended."
        PRD 3.2: "Adjudicating `SUBMITTED → CLEARED` sets the action's
        `ec_screen_outcome` to `CLEARED` and its `extraordinary_circumstance_flag`
        to false; if the action's `review_stage` was `INTAKE`, it advances `INTAKE
        → SCREENED`; and an entry with `entry_code` `EC_SCREEN_ADJUDICATED` is
        appended, incrementing `record_entry_count`."

        Design: Difficulty/non_linear_state_machine/ec_screen_returned_resubmit_cycle_tracks_round_count
        """
        ctx = fixtures.setup_office_and_action()
        action_id = ctx["action"]["id"]
        screen = fixtures.submit_screen(action_id,
                                        findings=fixtures.CLEARED_SCREEN_FINDINGS)

        fixtures.adjudicate_screen(
            screen["id"], "RETURNED",
            adjudicator_note="Narrative for the wetland code is missing supporting "
                             "survey data",
        )
        after_first_return = fixtures.read_action(action_id)
        assert after_first_return["ec_screen_outcome"] is None, (
            "a return is not an adjudicated outcome"
        )
        assert after_first_return["review_stage"] == "INTAKE"
        assert after_first_return["extraordinary_circumstance_flag"] is False
        assert after_first_return["record_entry_count"] == 0, (
            "no record entry is appended by a return"
        )

        fixtures.resubmit_screen(screen["id"], FIRST_REWORK_FINDINGS)
        fixtures.adjudicate_screen(
            screen["id"], "RETURNED",
            adjudicator_note="Wetland avoidance design still not described",
        )
        after_second_return = fixtures.read_action(action_id)
        assert after_second_return["ec_screen_outcome"] is None
        assert after_second_return["review_stage"] == "INTAKE"
        assert after_second_return["record_entry_count"] == 0

        fixtures.resubmit_screen(screen["id"], SECOND_REWORK_FINDINGS)
        fixtures.adjudicate_screen(
            screen["id"], "CLEARED",
            adjudicator_note="Avoidance design accepted; no extraordinary "
                             "circumstance triggered",
        )
        decided = fixtures.read_action(action_id)
        assert decided["ec_screen_outcome"] == "CLEARED"
        assert decided["review_stage"] == "SCREENED"
        assert decided["extraordinary_circumstance_flag"] is False
        assert decided["record_entry_count"] == 1

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert [entry["entry_code"] for entry in entries] == ["EC_SCREEN_ADJUDICATED"], (
            "the two returns wrote nothing; only the cleared outcome did"
        )


class TestTriggeredScreenCascade:
    """A triggered circumstance escalates the pathway and supersedes the
    memorandum the lighter pathway had produced."""

    def test_trigger_escalates_the_classification_and_supersedes_the_memorandum(
        self, client
    ):
        """The flag flip escalates a categorical exclusion to an environmental
        assessment, and that escalation is what supersedes the memorandum.

        PRD 3.2: "The first hop sets the action's `ec_screen_outcome` to
        `TRIGGERED` and its `extraordinary_circumstance_flag` to true. The second
        hop follows from the flag becoming true: if the action's `classification`
        is `CATEGORICAL_EXCLUSION`, that `classification` becomes
        `ENVIRONMENTAL_ASSESSMENT`, the `review_stage` is set to `CLASSIFIED`, and
        an entry with `entry_code` `CLASSIFICATION_ESCALATED` is appended. The
        third hop follows from the classification having moved away from
        `CATEGORICAL_EXCLUSION`: every `NepaDocument` of the action whose
        `document_type` is `CE_MEMORANDUM` and whose `publication_status` is
        either `DRAFT` or `PUBLISHED` has its `publication_status` set to
        `SUPERSEDED` and its `comment_status` set to `CLOSED`, with one
        `DOCUMENT_SUPERSEDED` entry appended per superseded document."

        Design: Difficulty/transitive_cascade/ec_trigger_escalates_classification_and_supersedes_ce_memorandum
        """
        ctx = fixtures.setup_ce_memorandum_with_pending_trigger()
        action_id = ctx["action"]["id"]

        assert ctx["action"]["classification"] == "CATEGORICAL_EXCLUSION", (
            "2.0 hectares with every sensitivity flag false is a categorical "
            "exclusion before the trigger"
        )
        assert ctx["document"]["publication_status"] == "DRAFT"

        screen = validate_success(
            client.adjudicate_ec_screen(
                ctx["second_screen"]["id"],
                ec_adjudication_payload(
                    "TRIGGERED",
                    adjudicator_note="Wetland impact is an extraordinary circumstance",
                ),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert screen["status"] == "TRIGGERED"
        assert screen["triggered_codes"] == ["EC_WETLAND"]
        assert screen["max_severity"] == 4

        action = fixtures.read_action(action_id)
        assert action["ec_screen_outcome"] == "TRIGGERED"
        assert action["extraordinary_circumstance_flag"] is True
        assert action["classification"] == "ENVIRONMENTAL_ASSESSMENT", (
            "the flag flip escalates the categorical exclusion"
        )
        assert action["review_stage"] == "CLASSIFIED"

        document = fixtures.read_document(ctx["document"]["id"])
        assert document["publication_status"] == "SUPERSEDED", (
            "the memorandum cannot survive the pathway moving away from a "
            "categorical exclusion"
        )
        assert document["comment_status"] == "CLOSED"

    def test_cascade_entries_are_appended_in_cause_before_effect_order(self, client):
        """The escalation entry is written before the supersession entry it
        causes, and the record stays gap-free.

        PRD 2.4: "When a single request appends more than one entry, the entries
        are appended in the cascade order documented for that operation — the
        first-order effect before the effect it causes, and that before the effect
        the second causes — and `sequence_no` increases by one per entry in that
        order."
        PRD 3.3: "When `extraordinary_circumstance_flag` flips from false to true
        while the current `classification` is `CATEGORICAL_EXCLUSION`, the
        `classification` becomes `ENVIRONMENTAL_ASSESSMENT` and a
        `CLASSIFICATION_ESCALATED` entry is appended."

        Design: Difficulty/transitive_cascade/ec_trigger_escalates_classification_and_supersedes_ce_memorandum
        """
        ctx = fixtures.setup_ce_memorandum_with_pending_trigger()
        action_id = ctx["action"]["id"]

        before, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert [entry["entry_code"] for entry in before] == [
            "EC_SCREEN_ADJUDICATED",
            "CLASSIFICATION_ASSIGNED",
        ]

        fixtures.adjudicate_screen(
            ctx["second_screen"]["id"], "TRIGGERED",
            adjudicator_note="Wetland impact is an extraordinary circumstance",
        )

        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert_sequence_contiguous(entries)

        escalated = find_entry(entries, "CLASSIFICATION_ESCALATED")
        superseded = find_entry(entries, "DOCUMENT_SUPERSEDED")
        assert escalated is not None, "the escalation must be recorded"
        assert superseded is not None, "the supersession must be recorded"
        assert len(entries_with_code(entries, "DOCUMENT_SUPERSEDED")) == 1, (
            "one entry is appended per superseded document, and there is one "
            "memorandum"
        )
        assert escalated["sequence_no"] < superseded["sequence_no"], (
            "the supersession follows from the escalation, so it is appended after "
            "it"
        )
        assert escalated["sequence_no"] > 2, (
            "both cascade entries land after the entries the first screening and "
            "the original classification wrote"
        )
        assert fixtures.read_action(action_id)["record_entry_count"] == len(entries)

    def test_cleared_disposition_contradicting_the_triggered_codes_is_refused(
        self, client
    ):
        """A present finding at severity 4 puts a code in `triggered_codes`, so
        only a `TRIGGERED` disposition is admissible.

        PRD 3.2: "`triggered_codes` lists the codes of those findings whose
        `present` is true and whose `severity` is at least the office's
        `ec_severity_trigger_threshold`, ordered as those codes appear in the
        office's `extraordinary_circumstance_codes` list."
        PRD 3.2: "A `CLEARED` disposition is admissible only when
        `triggered_codes` is empty, and a `TRIGGERED` disposition only when
        `triggered_codes` is non-empty; a disposition that contradicts the
        computed codes in either direction is rejected with
        `ERR_EC_SCREEN_NOT_TRIGGERED`."

        Design: Corner/errors/corner_error_ec_screen_not_triggered_rejects_cleared_adjudication
        """
        ctx = fixtures.setup_office_and_action()
        screen = fixtures.submit_screen(ctx["action"]["id"],
                                        findings=OCCUPIED_NEST_FINDINGS)
        assert screen["triggered_codes"] == ["EC_ENDANGERED_SPECIES"]
        assert screen["max_severity"] == 4

        rejected = client.adjudicate_ec_screen(
            screen["id"],
            ec_adjudication_payload(
                "CLEARED",
                adjudicator_note="Treat the nest through timing restrictions",
            ),
            REVIEWING_OFFICIAL_HEADERS,
        )
        validate_error(rejected, ApiErrorId.EC_SCREEN_NOT_TRIGGERED.value,
                       expected_status=409)
        assert fixtures.read_action(ctx["action"]["id"])["ec_screen_outcome"] is None, (
            "the refused adjudication records no outcome on the action"
        )
        unchanged = validate_success(
            client.get_ec_screen(screen["id"], REVIEWING_OFFICIAL_HEADERS)
        )
        assert unchanged["status"] == "SUBMITTED", (
            "the screen stays submitted after the contradicting disposition"
        )

        accepted = validate_success(
            client.adjudicate_ec_screen(
                screen["id"],
                ec_adjudication_payload(
                    "TRIGGERED",
                    adjudicator_note="Occupied nest is an extraordinary circumstance",
                ),
                REVIEWING_OFFICIAL_HEADERS,
            )
        )
        assert accepted["status"] == "TRIGGERED"

        action = fixtures.read_action(ctx["action"]["id"])
        assert action["ec_screen_outcome"] == "TRIGGERED"
        assert action["extraordinary_circumstance_flag"] is True

    def test_memorandum_on_an_assessment_action_is_a_reference_mismatch(self, client):
        """A document class that disagrees with the owning action's classification
        is refused as an incoherent reference, not as a missing one.

        PRD 2.6: "Resolving is not the same as being coherent. A referenced row
        must also belong to the right aggregate and be in an admissible state, and
        a violation of that stronger requirement yields `ERR_REFERENCE_MISMATCH`
        (HTTP 409)."
        PRD 3.8: "A `NepaCoordinator` creates a document with a `document_type` of
        `CE_MEMORANDUM`, `ENVIRONMENTAL_ASSESSMENT` or
        `ENVIRONMENTAL_IMPACT_STATEMENT` and a `title`; the type must match the
        action's `classification` per §2.6."

        Design: Corner/errors/corner_error_reference_mismatch_rejects_wrong_document_type
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        assert ctx["action"]["classification"] == "ENVIRONMENTAL_ASSESSMENT"

        mismatched = client.create_document(
            action_id,
            document_payload(document_type="CE_MEMORANDUM",
                             title="Ridgeline Categorical Exclusion Memorandum"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(mismatched, ApiErrorId.REFERENCE_MISMATCH.value,
                       expected_status=409)

        accepted = validate_success(
            client.create_document(
                action_id,
                document_payload(
                    document_type="ENVIRONMENTAL_ASSESSMENT",
                    title="Ridgeline Fuels Treatment Environmental Assessment",
                ),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert accepted["publication_status"] == "DRAFT"

        _, meta = validate_paginated(
            client.list_documents(action_id, NEPA_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 1, (
            "only the matching document type was created"
        )
