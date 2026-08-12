"""Continuing review: submission window, revision loop, lapse cascade, and
late-approval recovery (PRD §2.4, §3.7, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    adjudicate_continuing_review_ok,
    assert_timestamp_equals,
    get_protocol,
    get_success_data,
    make_pi_headers,
    register_investigator,
    set_clock,
    setup_approved_protocol,
    submit_continuing_review_ok,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestContinuingReviewRevisionLoop:
    def test_continuing_review_changes_requested_resubmit_cycle(self, api):
        """PRD §3.7: "The owning PI submits the cycle while it sits in
        `PENDING_SUBMISSION` or `CHANGES_REQUESTED` — any other status draws
        `ERR_INVALID_STATE`" and "A `REQUIRE_CHANGES` outcome returns the cycle
        to `CHANGES_REQUESTED` for the PI to revise and resubmit inside the
        same window."

        Design: Corner/state_machines/continuing_review_changes_requested_resubmit_cycle
        """
        scenario = setup_approved_protocol(risk_level="MINIMAL")
        inv, chair, proto = (
            scenario["investigator"], scenario["chair"], scenario["protocol"],
        )
        cr1 = scenario["continuing_reviews"][0]

        # Inside the window [2027-03-02, 2027-05-01].
        set_clock("2027-03-15T00:00:00Z")

        submitted = submit_continuing_review_ok(cr1["id"], inv["id"])
        assert submitted["status"] == "SUBMITTED"

        changes = adjudicate_continuing_review_ok(cr1["id"], chair["id"],
                                                  "REQUIRE_CHANGES")
        assert changes["status"] == "CHANGES_REQUESTED"

        resubmitted = submit_continuing_review_ok(cr1["id"], inv["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["cycle_index"] == 1, (
            "The revision loop stays on cycle 1"
        )
        assert get_protocol(proto["id"])["status"] == "APPROVED"


class TestContinuingReviewWindow:
    def test_cr_submit_before_window_rejected(self, api):
        """PRD §3.7: "Submission is accepted only inside the window: before
        `window_opens_at` the submit is rejected with
        `ERR_CR_WINDOW_NOT_OPEN`, and once the current time has passed `due_at`
        the sweep will already have moved the cycle to `LAPSED`."

        Design: Corner/validations/cr_submit_before_window_rejected
        """
        scenario = setup_approved_protocol(risk_level="MINIMAL")
        inv, proto = scenario["investigator"], scenario["protocol"]
        cr1 = scenario["continuing_reviews"][0]

        # 2027-01-15 is before window_opens_at 2027-03-02T00:00:00Z.
        set_clock("2027-01-15T00:00:00Z")
        resp = api.submit_continuing_review(cr1["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_CR_WINDOW_NOT_OPEN)

        cr_after = get_success_data(api.get_continuing_review(cr1["id"], COORDINATOR))
        assert cr_after["status"] == "PENDING_SUBMISSION"


class TestLapseCascade:
    def _setup_lapsed(self, api):
        """Protocol APPROVED (MINIMAL) at the startup clock; the cycle-1
        continuing review lapses when the clock passes its due date."""
        scenario = setup_approved_protocol(
            risk_level="MINIMAL", training_expires_at="2028-01-01T00:00:00Z",
        )
        cr1 = scenario["continuing_reviews"][0]
        # due_at 2027-05-01T00:00:00Z; one second past it lapses the cycle.
        set_clock("2027-05-01T00:00:01Z")
        return scenario, cr1

    def test_clock_sweep_lapse_cascade_protocol_and_case(self, api):
        """PRD §3.7: "A cycle in `PENDING_SUBMISSION` or `SUBMITTED` whose
        `due_at` falls strictly before the current logical time moves to
        `LAPSED` — sitting exactly at `due_at` still counts as open — and the
        lapse cascades in three linked steps: the protocol moves `APPROVED` →
        `EXPIRED`, halting enrollment; a non-compliance case of source
        `LAPSED_CR` opens in `OPENED`; and the investigator's provisional score
        is recomputed with the new open case weighing five points."

        Design: Difficulty/transitive_cascade/clock_sweep_lapse_cascade_to_investigator_score
        """
        scenario, cr1 = self._setup_lapsed(api)
        proto = scenario["protocol"]

        cr_after = get_success_data(api.get_continuing_review(cr1["id"], COORDINATOR))
        assert cr_after["status"] == "LAPSED"
        assert get_protocol(proto["id"])["status"] == "EXPIRED"

        cases, meta = validate_paginated(
            api.list_non_compliance_cases(proto["id"], COORDINATOR)
        )
        assert len(cases) == 1, f"Exactly one LAPSED_CR case, got {len(cases)}"
        assert cases[0]["source"] == "LAPSED_CR"
        assert cases[0]["status"] == "OPENED"

    def test_clock_sweep_lapse_cascade_investigator_scores(self, api):
        """PRD §3.8: "The `provisional_compliance_score` deducts those same
        confirmed findings and, on top, 5 points per case in `OPENED` or
        `INVESTIGATION` and 8 points per late report still standing in
        `FILED`." PRD §3.8: "The `final_compliance_score` deducts 20 points per
        confirmed finding — cases with `finding_confirmed` true sitting in
        `FINDING_CONFIRMED` or `CLOSED`."

        Design: Difficulty/transitive_cascade/clock_sweep_lapse_cascade_to_investigator_score
        """
        scenario, _cr1 = self._setup_lapsed(api)
        inv = scenario["investigator"]

        inv_after = get_success_data(api.get_investigator(inv["id"], COORDINATOR))
        # One open case (-5), no confirmed findings.
        assert inv_after["provisional_compliance_score"] == 95, (
            f"provisional = 100 - 5, got {inv_after['provisional_compliance_score']}"
        )
        assert inv_after["final_compliance_score"] == 100, (
            f"final unchanged without confirmed findings, got {inv_after['final_compliance_score']}"
        )


class TestLapsedRecovery:
    def test_lapsed_cr_late_approval_reinstates_protocol(self, api):
        """PRD §3.7: "approving a `LAPSED` cycle returns the protocol from
        `EXPIRED` to `APPROVED`, recomputes `approval_expires_at` from the
        adjudication instant, and creates the next cycle, while the `LAPSED_CR`
        case deliberately stays open until the compliance process of §3.8
        investigates and closes it." PRD §3.7: "the next cycle springs into
        existence with its `cycle_index` incremented by one, a freshly computed
        `due_at` and `window_opens_at`, and status `PENDING_SUBMISSION`."

        Design: Corner/state_machines/lapsed_cr_late_approval_reinstates_protocol
        """
        scenario = setup_approved_protocol(
            risk_level="MINIMAL", training_expires_at="2028-06-01T00:00:00Z",
        )
        inv, chair, proto = (
            scenario["investigator"], scenario["chair"], scenario["protocol"],
        )
        cr1 = scenario["continuing_reviews"][0]

        # Past the cycle-1 due date (2027-05-01T00:00:00Z): the sweep lapses it.
        set_clock("2027-05-02T00:00:00Z")
        assert get_protocol(proto["id"])["status"] == "EXPIRED"

        approved = adjudicate_continuing_review_ok(cr1["id"], chair["id"], "APPROVE")
        assert approved["status"] == "APPROVED"

        proto_after = get_protocol(proto["id"])
        assert proto_after["status"] == "APPROVED"
        # Adjudication instant 2027-05-02 + 365 days (span includes the
        # 2028-02-29 leap day) = 2028-05-01T00:00:00Z.
        assert_timestamp_equals(
            proto_after["approval_expires_at"], "2028-05-01T00:00:00Z"
        )

        rows, _meta = validate_paginated(
            api.list_continuing_reviews(proto["id"], COORDINATOR)
        )
        assert len(rows) == 2, f"A next cycle must exist, got {len(rows)}"
        cycle2 = [r for r in rows if r["cycle_index"] == 2]
        assert len(cycle2) == 1
        assert cycle2[0]["status"] == "PENDING_SUBMISSION"
        assert_timestamp_equals(cycle2[0]["due_at"], "2028-05-01T00:00:00Z")

        cases, _meta = validate_paginated(
            api.list_non_compliance_cases(proto["id"], COORDINATOR)
        )
        lapsed_cases = [c for c in cases if c["source"] == "LAPSED_CR"]
        assert len(lapsed_cases) == 1
        assert lapsed_cases[0]["status"] == "OPENED", (
            "The LAPSED_CR case deliberately stays open after late approval"
        )
