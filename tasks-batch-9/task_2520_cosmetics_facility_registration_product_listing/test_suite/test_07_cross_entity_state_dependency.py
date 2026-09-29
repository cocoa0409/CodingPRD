"""Writes whose admissibility is decided by another entity's state: a listing
submission gated by its parent establishment's posture, and a listing's own
delisting gated by the state of a recall beneath it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import OFFICER_2_HEADERS, OFFICER_HEADERS
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import fixtures as X


def _registered_but_frozen_establishment(api):
    """An establishment still REGISTERED whose points have frozen its posture."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Ashcroft Cream Plant",
            "owner_operator_name": "Ashcroft Ltd",
            "state_or_province": "GA",
        },
        listing_overrides={
            "product_name": "Ashcroft Skin Peel",
            "category_code": "11E",
        },
    )
    X.freeze_facility_with_points(api, bundle)
    return bundle


class TestListingSubmitGatedByParentPosture:
    """The child write is refused for a state field that belongs to the parent."""

    def test_three_capped_late_reports_freeze_a_still_registered_establishment(self, api):
        """Three consumer reports each more than ten days late score the late base at the
        capped factor, and 30.00 points is past the frozen threshold — yet the registration
        itself is untouched, which is the only combination that makes the posture gate
        reachable.

        PRD: "The points component of the posture is `FROZEN` at 25.00 or more, `RESTRICTED` at 10.00 or more, and `OPEN` below that, with both comparisons inclusive at the boundary and made against the two-decimal stored value: 9.50 leaves the establishment `OPEN`, 10.00 exactly makes it `RESTRICTED`, 24.99 is still `RESTRICTED` and 25.00 is `FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/listing_submit_gated_by_parent_facility_posture_while_still_registered
        """
        bundle = _registered_but_frozen_establishment(api)

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        A.assert_two_decimal_value(facility["serious_event_points"], 30.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_FROZEN

    def test_the_frozen_parent_alone_refuses_the_listing_submission(self, api):
        """The listing is not substantiated either, but the caller is told about the parent's
        posture, because the posture gate is evaluated before every safety gate — and the
        registration check ahead of it is satisfied.

        PRD: "First the governing establishment must be admissibly registered — `registration_status` `REGISTERED` or `RENEWAL_DUE` — or the submission fails with `ERR_FACILITY_NOT_REGISTERED`. Second the establishment's `compliance_posture` must not be `FROZEN`, or it fails with `ERR_FACILITY_POSTURE_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/listing_submit_gated_by_parent_facility_posture_while_still_registered
        """
        bundle = _registered_but_frozen_establishment(api)

        validate_error(
            api.submit_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_FACILITY_POSTURE_FROZEN,
        )

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_DRAFT
        assert listing["marketable"] is False
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 0

    def test_dossier_assembly_is_permitted_while_its_submission_is_not(self, api):
        """The same parent state is probed from both sides: opening a dossier against a
        listing that is not delisted succeeds and evidence attaches to it, but submitting
        that dossier is refused on the parent's posture before the dossier's own state is
        even considered.

        PRD: "The call answers 201 and may be made against a listing in any state except `DELISTED`, which rejects with `ERR_INVALID_LISTING_STATE`."
        PRD: "Two further conditions apply, and the order between them and the state check follows §2.8: the governing establishment's `compliance_posture` must not be `FROZEN`, or the submission is refused with `ERR_FACILITY_POSTURE_FROZEN` (HTTP 409), and this posture check runs *before* the dossier-state check; the dossier must then hold at least one evidence item, or the submission is refused with `ERR_NO_REVIEW_ITEMS` (HTTP 422), which is checked *after* the state check."

        Design: Difficulty/cross_entity_state_dependency/listing_submit_gated_by_parent_facility_posture_while_still_registered
        """
        bundle = _registered_but_frozen_establishment(api)

        dossier = X.open_dossier(api, bundle["listing_id"], bundle["agent"])
        assert dossier["status"] == K.SUBSTANTIATION_STATUS_DRAFT
        items = X.attach_items(
            api, dossier["id"], bundle["agent"],
            [(K.EVIDENCE_CLINICAL, K.CREDENTIAL_BOARD_CERTIFIED)],
        )
        assert len(items) == 1

        validate_error(
            api.submit_substantiation(dossier["id"], bundle["agent"]),
            E.ERR_FACILITY_POSTURE_FROZEN,
        )

        stored = X.read_substantiation(api, dossier["id"])
        assert stored["status"] == K.SUBSTANTIATION_STATUS_DRAFT
        assert stored["revision_round"] == 0
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
        assert listing["marketable"] is False


LOT_UNITS = 1000
VERIFIED_UNITS = 900


def _listing_with_an_executing_recall(api):
    """A marketed product with one shipment of 1000 units, 900 of them verified back.

    The plan is accepted by OFF-1 so that OFF-2 is free to open the withdrawal
    round and run the closing review on it.
    """
    bundle = X.listed_bundle(
        api,
        listing_overrides={
            "product_name": "Larkspur Eyeliner Pro",
            "category_code": "03B",
            "lot_authorized_units": LOT_UNITS,
        },
        person_overrides={"legal_name": "Larkspur Brands LLC"},
    )
    records = X.create_distribution_records(
        api, bundle["listing_id"], bundle["agent"],
        [{"lot_code": "LOT-K1", "ship_date": "2026-08-03", "delivery_date": "2026-08-07",
          "units_shipped": LOT_UNITS}],
    )
    recall = X.recall_with_accepted_plan(
        api, bundle["listing_id"], bundle["agent"],
        initiation_basis=K.INITIATION_BASIS_VOLUNTARY, officer=OFFICER_HEADERS,
    )
    withdrawal = X.open_withdrawal(api, recall, OFFICER_2_HEADERS, K.DEPTH_CONSUMER)
    X.produce_records(api, withdrawal["id"], [records[0]["id"]], bundle["agent"])
    X.post_recovery(
        api, withdrawal["id"], records[0]["id"], VERIFIED_UNITS, bundle["agent"],
        K.ENTRY_KIND_VERIFIED_RETURN,
    )
    bundle["recall"] = recall
    bundle["withdrawal_id"] = withdrawal["id"]
    return bundle


class TestDelistGatedByAnOpenRecall:
    """The parent listing's own transition waits on the child recall's closure."""

    def test_an_unfinished_recall_refuses_the_delisting(self, api):
        """While the recall is executing the product carries one open recall, and the
        delisting is refused: a product cannot be quietly removed from the register while
        an unfinished recall is still attached to it.

        PRD: "One business condition guards it: the listing's `open_recall_count` must be 0, or the request is refused with `ERR_OPEN_RECALL_BLOCKS_DELIST` (HTTP 409) — a product cannot be quietly removed from the register while an unfinished recall is still attached to it."

        Design: Difficulty/cross_entity_state_dependency/delist_gated_by_open_recall_then_permitted_after_effective_closure
        """
        bundle = _listing_with_an_executing_recall(api)

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED
        assert listing["open_recall_count"] == 1
        assert X.read_recall(api, bundle["recall"]["id"])["status"] == K.RECALL_STATUS_EXECUTING

        validate_error(
            api.delist_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_OPEN_RECALL_BLOCKS_DELIST,
        )

        assert X.read_listing(api, bundle["listing_id"])["listing_status"] == (
            K.LISTING_STATUS_LISTED
        )

    def test_nine_hundred_of_a_thousand_verified_lands_on_the_inclusive_threshold(self, api):
        """900 verified of 1000 shipped is a provisional 90.00, which is inclusive of the
        high tier, so no credit is granted, the denominator stays whole and the final rate
        is 90.00 — effective on the threshold's own inclusive boundary.

        PRD: "At the tier boundary, 1000 shipped with exactly 900 verified gives a provisional 90.00, which is inclusive of the high tier, so no credit at all and a final rate of 90.00 — `EFFECTIVE` on the effectiveness threshold's own inclusive boundary."

        Design: Difficulty/cross_entity_state_dependency/delist_gated_by_open_recall_then_permitted_after_effective_closure
        """
        bundle = _listing_with_an_executing_recall(api)

        closed = X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert closed["verified_recovered_units"] == VERIFIED_UNITS
        A.assert_two_decimal_value(
            closed["provisional_verified_rate"], 90.00, "provisional_verified_rate"
        )
        assert closed["unreachable_credit_pct"] == 0
        assert closed["adjusted_denominator_units"] == LOT_UNITS
        A.assert_two_decimal_value(
            closed["verified_recovery_rate"], 90.00, "verified_recovery_rate"
        )
        assert closed["outstanding_units_total"] == LOT_UNITS - VERIFIED_UNITS
        assert closed["effectiveness_verdict"] == K.VERDICT_EFFECTIVE

    def test_the_closure_clears_the_open_recall_from_the_listing(self, api):
        """An effective review closes the round and the recall together, stores the final
        rate on the recall and releases the listing's open-recall count.

        PRD: "An effective verified review closes the round and the recall together: the withdrawal takes `RECORDS_PRODUCED → CLOSED_EFFECTIVE` or `INTERIM_REVIEWED → CLOSED_EFFECTIVE`, which is terminal; the parent recall moves `EXECUTING → CLOSED_EFFECTIVE`, also terminal, storing `effectiveness_rate_final` as the withdrawal's `verified_recovery_rate`; the listing's `open_recall_count` falls by 1 and its `marketable` flag is recomputed; and one `WITHDRAWAL_CLOSURE` ledger entry is appended against the withdrawal."

        Design: Difficulty/cross_entity_state_dependency/delist_gated_by_open_recall_then_permitted_after_effective_closure
        """
        bundle = _listing_with_an_executing_recall(api)

        closed = X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )
        assert closed["status"] == K.WITHDRAWAL_STATUS_CLOSED_EFFECTIVE

        recall = X.read_recall(api, bundle["recall"]["id"])
        assert recall["status"] == K.RECALL_STATUS_CLOSED_EFFECTIVE
        A.assert_two_decimal_value(
            recall["effectiveness_rate_final"], 90.00, "effectiveness_rate_final"
        )
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 0

    def test_the_identical_delist_request_succeeds_once_the_recall_has_closed(self, api):
        """The same request that was refused now goes through: the product leaves the
        register, the establishment stops counting it and the designee gives up its slot.

        PRD: "Delisting sets `listing_status` to `DELISTED`, which is terminal, clears `suspension_reason` to null, decrements the designee's `active_designation_count` by 1 whenever the listing held a slot immediately beforehand (that is, when its prior `listing_status` was `SUBMITTED` or `LISTED`) and flips that designee to `DORMANT` at 0, decrements the establishment's `listed_product_count` by 1 when the prior status was `LISTED`, recomputes `marketable` to false, appends a `STATE_TRANSITION` ledger entry, and increments the listing's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/delist_gated_by_open_recall_then_permitted_after_effective_closure
        """
        bundle = _listing_with_an_executing_recall(api)
        validate_error(
            api.delist_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_OPEN_RECALL_BLOCKS_DELIST,
        )
        X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        delisted = get_success_data(
            api.delist_listing(
                bundle["listing_id"], bundle["agent"], {"reason": "Line discontinued"}
            )
        )

        assert delisted["listing_status"] == K.LISTING_STATUS_DELISTED
        assert delisted["suspension_reason"] is None
        assert delisted["marketable"] is False
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 0
        designee = X.read_responsible_person(api, bundle["person_id"])
        assert designee["active_designation_count"] == 0
        assert designee["status"] == K.RP_STATUS_DORMANT
