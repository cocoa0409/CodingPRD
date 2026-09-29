"""State machines that loop and branch rather than advance: a listing whose two
dimensions move independently, and a recall plan cycle that runs out of rounds
instead of escalating.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import OFFICER_HEADERS, REVIEWER_HEADERS
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _listed_and_substantiated(api):
    """A rinse-off skin peel on the register with a cleared 65.00 dossier behind it."""
    bundle = X.registered_facility_with_listing(
        api,
        listing_overrides={
            "product_name": "Coastline Weekly Peel Rinse",
            "category_code": "11E",
            "product_form": K.PRODUCT_FORM_RINSE_OFF,
        },
    )
    first = X.dossier_at_decision(
        api, bundle["listing_id"], bundle["agent"],
        X.PASSING_EVIDENCE, K.REVIEW_MODE_FULL, REVIEWER_HEADERS,
    )
    assert first["adequacy_score"] == 65.00
    assert first["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE

    get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
    listed = get_success_data(
        api.decide_listing(
            bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
        )
    )
    assert listed["listing_status"] == K.LISTING_STATUS_LISTED
    assert listed["marketable"] is True
    bundle["listing"] = listed
    return bundle, first


class TestListingDimensionsMoveIndependently:
    """The register dimension holds still while the safety dimension resets."""

    def test_a_fresh_dossier_supersedes_its_predecessor_and_resets_the_safety_status(self, api):
        """Filing a second dossier against a marketed product retires the cleared one and
        drops the listing out of marketable standing, without moving it off the register.

        PRD: "Opening a dossier is destructive to its predecessors, and deliberately so — the newest dossier is the only live one."
        PRD: "In the same request the listing's `safety_status` resets to `UNSUBSTANTIATED` and `marketable` is recomputed to false — and this holds even when `listing_status` is `LISTED`, so filing a fresh dossier for a marketed product immediately takes that product out of marketable standing."

        Design: Difficulty/non_linear_state_machine/listing_register_dimension_holds_while_safety_dimension_resets
        """
        bundle, first = _listed_and_substantiated(api)

        second = X.open_dossier(api, bundle["listing_id"], bundle["agent"])

        assert second["status"] == K.SUBSTANTIATION_STATUS_DRAFT
        assert second["revision_round"] == 0
        assert X.read_substantiation(api, first["id"])["status"] == (
            K.SUBSTANTIATION_STATUS_SUPERSEDED
        )

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
        assert listing["marketable"] is False
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED

    def test_the_register_position_survives_a_full_safety_cycle(self, api):
        """Across supersession, resubmission and a second decision the listing keeps its
        register number and the establishment keeps counting it as a listed product.

        PRD: "`SUBMITTED → LISTED` mints the register number into `listing_number`, formatted as the literal prefix `CPL-` followed by a six-digit zero-padded ordinal that is the listing's position among all listed listings ordered by ascending `created_at`; the number is minted only on the **first** listing decision, so a product that is later suspended and restored, or delisted and re-registered, keeps the number it was first given."

        Design: Difficulty/non_linear_state_machine/listing_register_dimension_holds_while_safety_dimension_resets
        """
        bundle, _first = _listed_and_substantiated(api)
        minted = bundle["listing"]["listing_number"]
        A.assert_listing_number_format(minted, 1)

        second = X.open_dossier(api, bundle["listing_id"], bundle["agent"])
        assert X.read_listing(api, bundle["listing_id"])["listing_number"] == minted
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

        X.attach_items(api, second["id"], bundle["agent"], X.PASSING_EVIDENCE)
        X.submit_dossier(api, second["id"], bundle["agent"])
        mid_cycle = X.read_listing(api, bundle["listing_id"])
        assert mid_cycle["safety_status"] == K.SAFETY_STATUS_UNDER_SUBSTANTIATION
        assert mid_cycle["listing_status"] == K.LISTING_STATUS_LISTED
        assert mid_cycle["listing_number"] == minted
        assert mid_cycle["marketable"] is False

        X.decide_dossier(api, second["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)
        closed = X.read_listing(api, bundle["listing_id"])
        assert closed["listing_status"] == K.LISTING_STATUS_LISTED
        assert closed["listing_number"] == minted
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

    def test_the_second_decision_restores_marketable_standing_on_its_own(self, api):
        """Clearing the replacement dossier is enough to make the product marketable again,
        because nothing ever moved the submission dimension.

        PRD: "A product that was `LISTED` stays `LISTED` and merely becomes non-marketable — the two dimensions of a listing's state machine move independently, and no review decision has ever moved the submission dimension."

        Design: Difficulty/non_linear_state_machine/listing_register_dimension_holds_while_safety_dimension_resets
        """
        bundle, _first = _listed_and_substantiated(api)
        second = X.open_dossier(api, bundle["listing_id"], bundle["agent"])
        X.attach_items(api, second["id"], bundle["agent"], X.PASSING_EVIDENCE)
        X.submit_dossier(api, second["id"], bundle["agent"])

        decided = X.decide_dossier(api, second["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)

        assert decided["adequacy_score"] == 65.00
        assert decided["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATED
        assert listing["marketable"] is True


def _exhausted_voluntary_recall(api):
    """A voluntary recall whose three permitted plans have all been rejected."""
    bundle = X.registered_facility_with_listing(
        api,
        listing_overrides={"product_name": "Saltmarsh Bath Oil", "category_code": "02C"},
    )
    recall = X.open_recall(
        api, bundle["listing_id"], K.INITIATION_BASIS_VOLUNTARY, "CLASS_III", OFFICER_HEADERS
    )
    assert recall["status"] == K.RECALL_STATUS_PLAN_REQUIRED
    assert recall["plan_round"] == 0

    rounds = []
    for expected_round in (1, 2, 3):
        submitted = get_success_data(
            api.submit_recall_plan(recall["id"], F.recall_plan_payload(), bundle["agent"])
        )
        rejected = get_success_data(
            api.decide_recall_plan(
                recall["id"], F.plan_decision_payload("REJECT"), OFFICER_HEADERS
            )
        )
        assert submitted["plan_round"] == expected_round
        rounds.append((submitted, rejected))
    return bundle, recall, rounds


class TestRecallPlanRevisionCycle:
    """Three trips round the submit-and-reject loop, then no more."""

    def test_each_revision_raises_the_plan_round_and_returns_the_file(self, api):
        """The loop runs three times: every submission lifts the round counter by one and
        every rejection hands the file back for revision, recording the deciding officer.

        PRD: "A submission is admissible from `PLAN_REQUIRED` or `PLAN_REJECTED`, and both edges into `PLAN_SUBMITTED` behave identically: `plan_round` rises by 1, `plan_submitted_at` is set to the logical clock, the stored narrative and depth are replaced by the newest ones, and the recall's `version` rises by 1."
        PRD: "Every decision, whichever way it goes, records the deciding officer's `X-User-ID` in `plan_decision_user_id` and the instant in `plan_decision_at`, and bumps the recall's `version` by 1."

        Design: Difficulty/non_linear_state_machine/recall_plan_revision_cycle_terminates_at_third_round
        """
        _bundle, _recall, rounds = _exhausted_voluntary_recall(api)

        for expected_round, (submitted, rejected) in enumerate(rounds, start=1):
            assert submitted["status"] == K.RECALL_STATUS_PLAN_SUBMITTED
            assert submitted["plan_round"] == expected_round
            assert submitted["plan_submitted_at"] == K.DEFAULT_CLOCK_UTC
            assert rejected["status"] == K.RECALL_STATUS_PLAN_REJECTED
            assert rejected["plan_round"] == expected_round
            assert rejected["plan_decision_user_id"] == OFFICER_HEADERS["X-User-ID"]
            assert rejected["plan_decision_at"] == K.DEFAULT_CLOCK_UTC

    def test_a_voluntary_recall_is_never_escalated_by_rejection_alone(self, api):
        """The third rejection of a voluntary notice takes the ordinary edge and leaves a
        live but exhausted recall, so nothing suspends the listing and nothing freezes the
        establishment.

        PRD: "A `VOLUNTARY_NOTICE` recall is never escalated to a mandatory recall by rejection alone."
        PRD: "Its third rejection takes the ordinary `PLAN_SUBMITTED → PLAN_REJECTED` edge and leaves it sitting in `PLAN_REJECTED` with `plan_round` 3 — a live but exhausted recall, where the agency has rejected the sponsor's last permitted plan and the sponsor may not submit another."

        Design: Difficulty/non_linear_state_machine/recall_plan_revision_cycle_terminates_at_third_round
        """
        bundle, recall, _rounds = _exhausted_voluntary_recall(api)

        stored = X.read_recall(api, recall["id"])
        assert stored["status"] == K.RECALL_STATUS_PLAN_REJECTED
        assert stored["plan_round"] == K.MAX_PLAN_ROUNDS
        assert stored["effectiveness_rate_final"] is None

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_DRAFT
        assert listing["suspension_reason"] is None
        assert listing["open_recall_count"] == 1
        assert X.read_facility(api, bundle["facility_id"])["compliance_posture"] == (
            K.POSTURE_OPEN
        )

    def test_a_fourth_plan_submission_is_refused_and_changes_nothing(self, api):
        """Once the round counter has reached three the revision edge is closed: the fourth
        submission is rejected on the rounds guard and the recall is left exactly as it was.

        PRD: "At most three submissions are ever accepted: the submission is refused with `ERR_RECALL_PLAN_ROUNDS_EXHAUSTED` (HTTP 409) once `plan_round` has reached 3, so the revision edge from `PLAN_REJECTED` back to `PLAN_SUBMITTED` can fire at most twice."

        Design: Difficulty/non_linear_state_machine/recall_plan_revision_cycle_terminates_at_third_round
        """
        bundle, recall, _rounds = _exhausted_voluntary_recall(api)
        before = X.read_recall(api, recall["id"])

        validate_error(
            api.submit_recall_plan(recall["id"], F.recall_plan_payload(), bundle["agent"]),
            E.ERR_RECALL_PLAN_ROUNDS_EXHAUSTED,
        )

        after = X.read_recall(api, recall["id"])
        assert after["status"] == K.RECALL_STATUS_PLAN_REJECTED
        assert after["plan_round"] == K.MAX_PLAN_ROUNDS
        A.assert_version_is(after, before["version"], "recall")
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 1
