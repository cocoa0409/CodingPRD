"""The carrier and qualification-review machines: the fork, and the declared edges.

A qualification review is a fork that joins on results rather than on call count,
and the carrier row it governs moves only on the edges the specification declares.
These tests drive one prong at a time, replay the cyclic remediation edge, and
push at the two edges that do not exist: fast-tracking a never-screened carrier,
and walking a disqualified one back.
"""

from test_helpers import (
    ANALYST,
    COMPLIANCE,
    DEFAULT_CLOCK,
    api_client,
    assert_same_instant,
    carrier_status_change_payload,
    create_carrier,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    create_screened_review,
    decision_payload,
    get_success_data,
    insurance_verification_payload,
    invite_carrier,
    open_qualification_review,
    read_carrier,
    set_clock,
    validate_error,
    validate_success,
)

# 0.40 x 100.00 mode coverage + 0.30 x 60.00 fleet adequacy (120 of the 200-unit
# target) + 0.30 x 100.00 insurance headroom.
CAPABILITY_SCORE = 88.00

# A freshly registered carrier: 0.70 x the provisional baseline of 90.00, plus
# 0.20 x a capability score still at 0.00, plus 0.10 x full insurance headroom.
FRESH_COMPOSITE_SCORE = 73.00

# The same composite once the review has been approved: 0.70 x 90.00 + 0.20 x
# 88.00 + 0.10 x 100.00.
QUALIFIED_COMPOSITE_SCORE = 90.60

REGISTERED_AUTO_LIABILITY_USD = 1000000.00
REGISTERED_CARGO_USD = 250000.00
REGISTERED_INSURANCE_EXPIRY = "2027-06-30T00:00:00Z"

# An auto-liability certificate at half the review's declared minimum, with the
# cargo limit and the expiry date both still comfortably above their thresholds.
SHORT_AUTO_LIABILITY_USD = 500000.00

DISQUALIFICATION_REASON = "Fraudulent certificate"


def _verify_insurance(review_id, **overrides):
    """Runs the insurance prong without asserting the outcome."""
    return api_client.verify_insurance(
        review_id, insurance_verification_payload(**overrides), COMPLIANCE
    )


def _screen_capability(review_id):
    """Runs the capability prong, which takes no payload of its own."""
    return api_client.screen_capability(review_id, COMPLIANCE, {})


def _decide(review_id, **overrides):
    """Records a decision on a review without asserting the outcome."""
    return api_client.decide_qualification_review(
        review_id, decision_payload(**overrides), COMPLIANCE
    )


def _change_status(carrier_id, **overrides):
    """Attempts an administrative carrier status change."""
    return api_client.change_carrier_status(
        carrier_id, carrier_status_change_payload(**overrides), COMPLIANCE
    )


def _read_review(carrier_id, review_id):
    """Re-reads one review from its carrier's review collection."""
    body = get_success_data(
        api_client.list_qualification_reviews(carrier_id, COMPLIANCE)
    )
    rows = body["data"] if isinstance(body, dict) and "data" in body else body
    matching = [row for row in rows if row["id"] == review_id]
    assert matching, f"review {review_id} is missing from the carrier's collection"
    return matching[0]


def _read_invitation(invitation_id):
    return get_success_data(api_client.get_invitation(invitation_id, ANALYST))


class TestQualificationForkJoin:
    """The join closes on the second non-`PENDING` result, in either order."""

    @staticmethod
    def _fresh_review():
        """A registered carrier with one open review, both prongs `PENDING`."""
        set_clock(DEFAULT_CLOCK)
        carrier = create_carrier()
        assert carrier["status"] == "REGISTERED"
        review = open_qualification_review(carrier["id"])
        return carrier, review

    def test_opening_a_review_moves_the_carrier_and_arms_both_prongs(self):
        """The review starts `SUBMITTED` with nothing resolved on either arm.

        PRD §3.1: "Opening the review moves the carrier from `REGISTERED` to
        `SCREENING` and creates the review with `status` `SUBMITTED`,
        `insurance_result` `PENDING`, `capability_result` `PENDING`,
        `remediation_count` `0`, and `insurance_verified_at`,
        `capability_screened_at`, `decision_outcome`, `decision_note` and
        `decision_by_user_id` all null."
        PRD §3.1: "The review then runs as a **fork with two independent arms that
        must both complete before the review may be decided**."

        Design: Corner/state_machines/qualification_review_reaches_screened_only_after_both_fork_prongs_complete
        """
        carrier, review = self._fresh_review()

        assert review["status"] == "SUBMITTED"
        assert review["insurance_result"] == "PENDING"
        assert review["capability_result"] == "PENDING"
        assert review["remediation_count"] == 0
        assert review["insurance_verified_at"] is None
        assert review["capability_screened_at"] is None
        assert review["decision_outcome"] is None
        assert review["decision_note"] is None
        assert review["decision_by_user_id"] is None
        assert review["carrier_id"] == carrier["id"]
        assert read_carrier(carrier["id"])["status"] == "SCREENING"

    def test_one_prong_records_its_result_without_closing_the_join(self):
        """Capability passes, the review stays `SUBMITTED`, the carrier is re-scored.

        PRD §3.1: "each is performed by a compliance officer; and the review
        advances from `SUBMITTED` to `SCREENED` at the moment the second arm records
        a non-`PENDING` result. Neither arm alone advances the review."
        PRD §3.1: "Multiply the mode coverage by `0.40`, the fleet adequacy by `0.30`
        and the insurance headroom by `0.30`, add the three products, and round to 2
        decimal places."
        PRD §3.1: "The carrier's own `capability_score` is updated to the computed
        figure **whether the result is `PASS` or `FAIL`**"

        Design: Corner/state_machines/qualification_review_reaches_screened_only_after_both_fork_prongs_complete
        """
        carrier, review = self._fresh_review()

        screened = validate_success(_screen_capability(review["id"]))
        assert screened["status"] == "SUBMITTED", "one prong is never enough"
        assert screened["capability_result"] == "PASS"
        assert float(screened["capability_score"]) == CAPABILITY_SCORE
        assert_same_instant(
            screened["capability_screened_at"], DEFAULT_CLOCK, "capability_screened_at"
        )
        assert screened["insurance_result"] == "PENDING"
        assert screened["insurance_verified_at"] is None

        refreshed = read_carrier(carrier["id"])
        assert float(refreshed["capability_score"]) == CAPABILITY_SCORE
        assert refreshed["status"] == "SCREENING"

    def test_the_second_prong_closes_the_join_but_does_not_qualify_the_carrier(self):
        """Reaching `SCREENED` is the review's business, not the carrier's.

        PRD §3.1: "Either way, `insurance_verified_at` is set to the clock."
        PRD §3.1: "If `capability_result` is already `PASS` or `FAIL` when this arm
        completes, the review advances from `SUBMITTED` to `SCREENED`."
        PRD §3.1: "The carrier moves from `SCREENING` to `QUALIFIED`, its
        `capability_score` is set from the review's `capability_score`, its
        `qualified_at` is set to the logical clock"

        Design: Corner/state_machines/qualification_review_reaches_screened_only_after_both_fork_prongs_complete
        """
        carrier, review = self._fresh_review()
        validate_success(_screen_capability(review["id"]))

        verified = validate_success(_verify_insurance(review["id"]))
        assert verified["status"] == "SCREENED"
        assert verified["insurance_result"] == "PASS"
        assert_same_instant(
            verified["insurance_verified_at"], DEFAULT_CLOCK, "insurance_verified_at"
        )

        refreshed = read_carrier(carrier["id"])
        assert refreshed["status"] == "SCREENING", (
            "only the decision qualifies a carrier, not the screening"
        )
        assert refreshed["qualified_at"] is None

    def test_a_decision_taken_before_the_join_closes_is_refused(self):
        """One `PENDING` prong makes the decision a rung-9 state conflict.

        PRD §3.1: "A decision attempted while the review is still `SUBMITTED` or
        `REMEDIATION` is rejected with `ERR_REVIEW_NOT_SCREENED` (409)."
        PRD §2.9: "deciding a qualification review that has not reached `SCREENED`
        raises `ERR_REVIEW_NOT_SCREENED`"
        PRD §3.2: "A carrier's `composite_score` is recomputed on every qualification
        decision, on every scorecard publication and on every administrative status
        change."

        Design: Corner/state_machines/qualification_decision_before_both_prongs_returns_review_not_screened
        """
        carrier, review = self._fresh_review()
        validate_success(_screen_capability(review["id"]))

        validate_error(
            _decide(review["id"], outcome="APPROVE", decision_note="Looks fine"),
            "ERR_REVIEW_NOT_SCREENED",
            409,
        )

        unchanged = _read_review(carrier["id"], review["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["decision_outcome"] is None
        assert unchanged["decision_by_user_id"] is None

        refreshed = read_carrier(carrier["id"])
        assert refreshed["status"] == "SCREENING"
        assert refreshed["qualified_at"] is None
        # No decision was recorded, so the composite still reads its registration
        # figure even though the capability prong has already moved.
        assert float(refreshed["composite_score"]) == FRESH_COMPOSITE_SCORE
        assert refreshed["composite_score_variant"] == "PROVISIONAL_SCREENING"


class TestInsuranceArmCopyForward:
    """The verified figures are always recorded; the copy-forward is conditional."""

    def test_a_shortfall_on_one_limit_fails_the_arm_and_copies_nothing(self):
        """`FAIL` records the certificate but leaves the carrier as registered.

        PRD §3.1: "The result is `PASS` when all three of the following hold —
        `verified_auto_liability_usd` is greater than or equal to the review's
        `min_auto_liability_usd`, `verified_cargo_usd` is greater than or equal to its
        `min_cargo_usd`, and `verified_expiry_date` is strictly after the current
        logical clock instant — and `FAIL` if any of the three does not hold."
        PRD §3.1: "**Only on a `PASS`** are the verified figures written back to the
        carrier, overwriting `auto_liability_limit_usd`, `cargo_limit_usd` and
        `insurance_expiry_date` with the verified values; on a `FAIL` the carrier's own
        insurance fields are left exactly as registered."
        PRD §3.1: "and it may optionally state `min_auto_liability_usd`, defaulting to
        `1000000.00`, and `min_cargo_usd`, defaulting to `100000.00`, the insurance
        thresholds the carrier will be measured against."

        Design: Corner/state_machines/insurance_verification_below_declared_minimum_writes_fail_and_copies_nothing
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_carrier()
        review = open_qualification_review(carrier["id"])

        failed = validate_success(
            _verify_insurance(
                review["id"], verified_auto_liability_usd=SHORT_AUTO_LIABILITY_USD
            )
        )
        assert failed["insurance_result"] == "FAIL", (
            "one limit below its minimum fails the arm however good the others are"
        )
        assert float(failed["verified_auto_liability_usd"]) == SHORT_AUTO_LIABILITY_USD
        assert float(failed["verified_cargo_usd"]) == REGISTERED_CARGO_USD
        assert_same_instant(
            failed["insurance_verified_at"], DEFAULT_CLOCK, "insurance_verified_at"
        )
        assert failed["status"] == "SUBMITTED", "the capability prong is still PENDING"
        assert failed["capability_result"] == "PENDING"

        refreshed = read_carrier(carrier["id"])
        assert float(refreshed["auto_liability_limit_usd"]) == (
            REGISTERED_AUTO_LIABILITY_USD
        ), "a FAIL must not copy the shortfall onto the carrier"
        assert float(refreshed["cargo_limit_usd"]) == REGISTERED_CARGO_USD
        assert_same_instant(
            refreshed["insurance_expiry_date"],
            REGISTERED_INSURANCE_EXPIRY,
            "insurance_expiry_date",
        )


class TestRemediationReopensTheFork:
    """`REMEDIATE` is the cyclic edge: it clears both prongs and holds the carrier."""

    def test_remediate_clears_both_results_and_leaves_the_carrier_screening(self):
        """The counter moves, the prongs reset, the carrier row is untouched.

        PRD §3.1: "The review moves from `SCREENED` to `REMEDIATION`,
        `remediation_count` increases by one, and **both** arm results are reset to
        `PENDING`, reopening the fork. The carrier remains in `SCREENING`; nothing on
        the carrier is rewritten."
        PRD §3.1: "In every branch the review records `decision_outcome`,
        `decision_note` and `decision_by_user_id` set to the acting `X-User-ID`."

        Design: Corner/state_machines/remediation_decision_reopens_the_fork_and_clears_both_prong_results
        """
        carrier, review = create_screened_review()
        assert review["status"] == "SCREENED"

        remediated = validate_success(
            _decide(
                review["id"],
                outcome="REMEDIATE",
                decision_note="Provide a current certificate of insurance",
            )
        )
        assert remediated["status"] == "REMEDIATION"
        assert remediated["remediation_count"] == 1
        assert remediated["insurance_result"] == "PENDING"
        assert remediated["capability_result"] == "PENDING"
        assert remediated["decision_outcome"] == "REMEDIATE"

        refreshed = read_carrier(carrier["id"])
        assert refreshed["status"] == "SCREENING", (
            "the SCREENING self-loop leaves the carrier where it was"
        )
        assert refreshed["qualified_at"] is None

    def test_re_running_one_prong_returns_the_review_to_submitted(self):
        """The fork genuinely reopened: one prong resolved, one still `PENDING`.

        PRD §3.1: "Re-running either arm on a review in `REMEDIATION` returns it to
        `SUBMITTED`, from which the ordinary fork-and-join behaviour resumes: the
        second arm to complete moves it to `SCREENED` again."
        PRD §3.1: "**`REMEDIATE`** requires that the review's `remediation_count` is
        strictly less than the remediation ceiling of 2; a third attempt to send the
        same review back is rejected with `ERR_REMEDIATION_LIMIT_EXCEEDED` (409)."

        Design: Corner/state_machines/remediation_decision_reopens_the_fork_and_clears_both_prong_results
        """
        carrier, review = create_screened_review()
        validate_success(
            _decide(
                review["id"],
                outcome="REMEDIATE",
                decision_note="Provide a current certificate of insurance",
            )
        )

        reopened = validate_success(_verify_insurance(review["id"]))
        assert reopened["status"] == "SUBMITTED"
        assert reopened["insurance_result"] == "PASS"
        assert reopened["capability_result"] == "PENDING"
        assert reopened["remediation_count"] == 1, (
            "re-screening does not increment the counter; only a REMEDIATE decision does"
        )
        assert read_carrier(carrier["id"])["status"] == "SCREENING"


class TestDeclaredCarrierEdges:
    """Only the declared pairings move a carrier, and one state absorbs them all."""

    def test_a_registered_carrier_cannot_be_fast_tracked_to_qualified(self):
        """`QUALIFIED` is reachable through the review or from `SUSPENDED`, not here.

        PRD §3.1: "A compliance officer may also move a carrier's `status` directly,
        supplying the target as `to_status` together with a mandatory `reason` that is
        written to `status_reason`. Only the following pairings are declared, and any
        other pairing of current status and `to_status` is rejected with
        `ERR_CARRIER_NOT_QUALIFIED` (409)"
        PRD §3.1: "A carrier whose `status` is `REGISTERED`, `SCREENING`, `QUALIFIED`,
        `WATCHLIST` or `CONDITIONALLY_QUALIFIED` may be moved to `SUSPENDED`."
        PRD §3.1: "A newly registered carrier is created with `status` set to
        `REGISTERED`, `status_reason` null, `capability_score` `0.00`,
        `published_scorecard_count` `0`, `active_primary_lane_count` `0`,
        `committed_volume_loads` `0` and `qualified_at` null."

        Design: Corner/state_machines/registered_carrier_status_change_to_qualified_is_not_a_declared_edge
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_carrier()

        validate_error(
            _change_status(
                carrier["id"], to_status="QUALIFIED", reason="Fast-track this one"
            ),
            "ERR_CARRIER_NOT_QUALIFIED",
            409,
        )

        unchanged = read_carrier(carrier["id"])
        assert unchanged["status"] == "REGISTERED"
        assert unchanged["qualified_at"] is None
        assert unchanged["status_reason"] is None
        assert float(unchanged["capability_score"]) == 0.00
        assert float(unchanged["composite_score"]) == FRESH_COMPOSITE_SCORE

        # The same endpoint on a declared pairing succeeds, so the refusal above is
        # about the target state rather than about the operation.
        suspended = validate_success(
            _change_status(
                carrier["id"],
                to_status="SUSPENDED",
                reason="Insurance audit in progress",
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["status_reason"] == "Insurance audit in progress"

    def test_disqualified_absorbs_every_target_and_keeps_its_revocations(self):
        """No edge leaves `DISQUALIFIED`, and the withdrawal cascade is not undone.

        PRD §3.1: "`REGISTERED` is where every carrier begins, and `DISQUALIFIED` is
        terminal: once a carrier reaches it, no transition out exists, and any attempt
        to move it elsewhere is rejected under rung 9 of §2.9 with
        `ERR_CARRIER_NOT_QUALIFIED`."
        PRD §3.1: "A carrier may be moved to `DISQUALIFIED` from any status other than
        `DISQUALIFIED` itself. This is terminal, and it triggers a withdrawal cascade
        in two links. First, every invitation held by that carrier whose status is
        `SENT` or `ACCEPTED` moves to `REVOKED`."
        PRD §2.9: "and a carrier status change whose current-status-to-target-status
        pair is not one of the declared carrier transitions — including every attempt
        to leave the terminal `DISQUALIFIED` state — raises
        `ERR_CARRIER_NOT_QUALIFIED`"

        Design: Corner/state_machines/terminal_disqualified_carrier_cannot_be_returned_to_qualified
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        assert float(carrier["composite_score"]) == QUALIFIED_COMPOSITE_SCORE
        event, _lanes = create_event_with_locked_lanes()
        invitation = invite_carrier(event["id"], carrier["id"])
        assert invitation["status"] == "SENT"

        disqualified = validate_success(
            _change_status(
                carrier["id"],
                to_status="DISQUALIFIED",
                reason=DISQUALIFICATION_REASON,
            )
        )
        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["status_reason"] == DISQUALIFICATION_REASON
        assert _read_invitation(invitation["id"])["status"] == "REVOKED"

        # The state is absorbing for every target, not only for QUALIFIED.
        for target in ("QUALIFIED", "SUSPENDED", "DISQUALIFIED"):
            validate_error(
                _change_status(
                    carrier["id"],
                    to_status=target,
                    reason="Documents finally produced",
                ),
                "ERR_CARRIER_NOT_QUALIFIED",
                409,
            )

        assert read_carrier(carrier["id"])["status"] == "DISQUALIFIED"
        assert _read_invitation(invitation["id"])["status"] == "REVOKED", (
            "a refused status change may not un-revoke the withdrawal cascade"
        )
