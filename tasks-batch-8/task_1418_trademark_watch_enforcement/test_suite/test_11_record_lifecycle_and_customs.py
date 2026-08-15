"""Record lifecycle clock transitions, the cancellation moot cascade, and
customs recordation rules (registration gate, buffer gap, supersede renewal)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assess_alert,
    create_agreement,
    create_alert,
    create_client,
    create_record,
    create_recordation,
    execute_agreement,
    get_agreement,
    get_alert,
    get_record,
    make_associate_headers,
    make_partner_headers,
    propose_agreement,
    publish_record,
    set_clock,
    setup_published_record,
    setup_registered_record,
    triage_alert,
    validate_error,
    validate_success,
)


class TestPublicationComputation:
    def test_opposition_due_at_rolls_forward_over_weekend(self, api,
                                                          paralegal_headers):
        """PRD §3.2: "it moves the record from `APPLICATION_PENDING` to `PUBLISHED`
        and computes `opposition_due_at` as thirty calendar days after publication,
        rolled forward past any Saturday or Sunday under the `CALENDAR_ROLL_FORWARD`
        variant"

        Design: Corner/calculations/opposition_due_at_rolls_forward_over_weekend
        """
        client = create_client()
        record = create_record(client["id"], mark_text="ACME", classes=(9,),
                               app_no="US-909")
        # Publish on Friday 2026-07-31.
        published = publish_record(record["id"], "2026-07-31T00:00:00Z")
        assert published["status"] == "PUBLISHED"
        # 2026-07-31 + 30 calendar days = 2026-08-30 (a Sunday) -> Monday 2026-08-31.
        assert_instant_equal(published["opposition_due_at"], "2026-08-31T00:00:00Z",
                             "opposition_due_at")


class TestMootCascade:
    def test_record_cancelled_moot_cascade(self, api, paralegal_headers,
                                           partner_headers):
        """PRD §3.2: "an `ADVERSE` outcome on either matter type cancels the record
        outright. Cancellation is terminal and moots everything attached to the
        record: every watch alert of the record in `ESCALATED` moves to `DISMISSED`,
        every customs recordation in `ACTIVE` moves to `REVOKED`, and every
        coexistence agreement in `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or
        `CURE_PERIOD` moves to `TERMINATED`."

        Design: Corner/state_machines/record_cancelled_moot_cascade
        """
        _, record = setup_registered_record(classes=(9,))
        recordation = create_recordation(record["id"], recordation_number="CBP-1",
                                         term_start="2026-08-15T00:00:00Z",
                                         term_end="2027-08-15T00:00:00Z")
        agreement = create_agreement(record["id"], counterparty_name="Rival Co",
                                     territory_codes=["US"],
                                     effective_start="2026-08-01T00:00:00Z",
                                     effective_end="2027-08-01T00:00:00Z")
        propose_agreement(agreement["id"], agreement["version"], terms_text="terms")
        execute_agreement(agreement["id"])

        alert = create_alert(record["id"], 80, 70, 60)
        alert = triage_alert(alert["id"])
        alert = assess_alert(alert["id"], alert["version"])
        res = api.escalate_alert(alert["id"], {"matter_type": "CANCELLATION"},
                                 make_associate_headers("assoc_1"))
        matter = validate_success(res, 201)
        assert get_record(record["id"])["status"] == "UNDER_CHALLENGE"

        resolved = validate_success(
            api.resolve_matter(matter["id"], {"outcome": "ADVERSE"}, partner_headers),
            200)
        assert resolved["status"] == "RESOLVED"

        assert get_record(record["id"])["status"] == "CANCELLED"
        assert get_alert(alert["id"])["status"] == "DISMISSED"
        recordation_after = validate_success(
            api.get_customs_recordation(recordation["id"], paralegal_headers), 200)
        assert recordation_after["status"] == "REVOKED"
        assert get_agreement(agreement["id"])["status"] == "TERMINATED"


class TestCustomsRecordationRules:
    def test_customs_recordation_requires_registered_record(self, api,
                                                            paralegal_headers):
        """PRD §3.7: "A `Paralegal` records a mark with a customs authority
        (`US_CBP`, `EU_TAXUD`, or `CN_GACC`) on a record in `REGISTERED` or
        `MAINTENANCE_DUE` status — any other record state is rejected with
        `ERR_RECORD_NOT_REGISTERED` — supplying the `recordation_number`,
        `term_start`, and `term_end`."

        Design: Corner/validations/customs_recordation_requires_registered_record
        """
        _, record = setup_published_record(classes=(9,))
        res = api.create_customs_recordation(
            record["id"],
            {
                "customs_authority": "US_CBP",
                "recordation_number": "CBP-1",
                "term_start": "2026-08-15T00:00:00Z",
                "term_end": "2027-08-15T00:00:00Z",
            },
            paralegal_headers,
        )
        validate_error(res, ApiErrorId.ERR_RECORD_NOT_REGISTERED, expected_status=409)

    def test_recordation_gap_exactly_30_days_rejected(self, api, paralegal_headers):
        """PRD §3.7: "A buffer-gap rule keeps coverage continuous but never adjacent:
        for the same record and authority, the new `term_start` must be strictly more
        than thirty days after every existing non-superseded recordation's
        `term_end`, else `ERR_RECORDATION_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/customs_recordation_mandatory_buffer_gap
        """
        _, record = setup_registered_record(classes=(9, 25))
        first = create_recordation(record["id"], recordation_number="CBP-1",
                                   term_start="2026-08-15T00:00:00Z",
                                   term_end="2027-08-15T00:00:00Z")
        assert first["status"] == "ACTIVE"

        # term_end + 30 days == 2027-09-14 exactly: the strict '>' buffer forbids it.
        res = api.create_customs_recordation(
            record["id"],
            {
                "customs_authority": "US_CBP",
                "recordation_number": "CBP-2",
                "term_start": "2027-09-14T00:00:00Z",
                "term_end": "2028-09-14T00:00:00Z",
            },
            paralegal_headers,
        )
        validate_error(res, ApiErrorId.ERR_RECORDATION_GAP_VIOLATION,
                       expected_status=409)

    def test_recordation_beyond_buffer_accepted(self, api, paralegal_headers):
        """PRD §3.7: "A buffer-gap rule keeps coverage continuous but never adjacent:
        for the same record and authority, the new `term_start` must be strictly more
        than thirty days after every existing non-superseded recordation's
        `term_end`, else `ERR_RECORDATION_GAP_VIOLATION`."
        PRD §3.7: "Recordations begin `ACTIVE`"

        Design: Difficulty/resource_temporal_overlap/customs_recordation_mandatory_buffer_gap
        """
        _, record = setup_registered_record(classes=(9, 25))
        create_recordation(record["id"], recordation_number="CBP-1",
                           term_start="2026-08-15T00:00:00Z",
                           term_end="2027-08-15T00:00:00Z")

        # 2027-09-15 is strictly more than thirty days after 2027-08-15.
        second = create_recordation(record["id"], recordation_number="CBP-3",
                                    term_start="2027-09-15T00:00:00Z",
                                    term_end="2028-09-15T00:00:00Z")
        assert second["status"] == "ACTIVE"

    def test_customs_recordation_renewal_supersedes_without_gap_check(
        self, api, paralegal_headers
    ):
        """PRD §3.7: "Supplying `supersedes_recordation_id` waives the gap rule and
        flips the named recordation from `ACTIVE` to `RENEWED`, recording a renewal
        chain."

        Design: Corner/validations/customs_recordation_renewal_supersedes_without_gap_check
        """
        _, record = setup_registered_record(classes=(9,))
        first = create_recordation(record["id"], recordation_number="CBP-1",
                                   term_start="2026-08-15T00:00:00Z",
                                   term_end="2027-08-15T00:00:00Z")

        # The renewal overlaps the prior term; superseding waives the gap rule.
        renewal = create_recordation(
            record["id"], recordation_number="CBP-1-R",
            term_start="2027-08-01T00:00:00Z", term_end="2028-08-01T00:00:00Z",
            supersedes_recordation_id=first["id"])
        assert renewal["status"] == "ACTIVE"

        prior = validate_success(
            api.get_customs_recordation(first["id"], paralegal_headers), 200)
        assert prior["status"] == "RENEWED"
