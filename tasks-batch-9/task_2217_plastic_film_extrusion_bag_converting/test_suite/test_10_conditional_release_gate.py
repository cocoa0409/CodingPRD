"""A CONDITIONAL lot may only be released behind an issued, conforming dossier."""
import pytest

from test_helpers import (
    CONVERTER,
    ApiErrorId,
    ISSUING_MANAGER,
    create_compliance_dossier_payload,
    get_success_data,
    is_iso8601_timestamp,
    setup_bag_lot_packed,
    validate_error,
    validate_success,
)

CONDITIONAL_PANEL = ((1, 22.0), (2, 22.0), (3, 19.0))


def _conditional_packed_lot(api):
    world = setup_bag_lot_packed(api, specimens=CONDITIONAL_PANEL,
                                requested_bags=22500)
    return world


def _draft_dossier(api, world):
    return get_success_data(api.create_compliance_dossier(
        create_compliance_dossier_payload(world["bag_lot"]["id"],
                                          dossier_code="CD-1",
                                          food_contact_declared=True,
                                          recycled_content_claim_pct=0.0),
        ISSUING_MANAGER))


class TestConditionalLotReleaseGate:
    """The blocking entity does not exist yet when the first release is tried."""

    def test_the_lot_is_packed_on_the_conditional_branch(self, api):
        """A CONDITIONAL verdict still admits the packout.

        PRD: "The first accepted packout moves the lot `QUALIFIED → PACKED` or
        `CONDITIONAL → PACKED`, applying identical allocation and counter updates
        on both branches".

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)

        assert world["bag_lot"]["status"] == "PACKED"
        assert world["bag_lot"]["seal_final_verdict"] == "CONDITIONAL"
        assert world["bag_lot"]["packed_bag_count"] == 22500

    def test_release_is_refused_while_no_dossier_exists(self, api):
        """With nothing issued the release gate cannot be satisfied.

        PRD: "Some compliance dossier for the lot must be in `ISSUED` status, or
        `ERR_DOSSIER_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)
        validate_error(api.release_bag_lot(world["bag_lot"]["id"], ISSUING_MANAGER),
                       ApiErrorId.ERR_DOSSIER_NOT_ISSUED, 409)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "PACKED"
        assert lot["seal_final_verdict"] == "CONDITIONAL"

    def test_a_fresh_dossier_starts_in_draft_and_does_not_open_the_gate(self, api):
        """Drafting is not issuing.

        PRD: "The dossier begins in `DRAFT` with `as_built_recycled_content_pct` and
        `claim_variance_pct` null and `claim_conformance` reading `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)
        validate_error(api.release_bag_lot(world["bag_lot"]["id"], ISSUING_MANAGER),
                       ApiErrorId.ERR_DOSSIER_NOT_ISSUED, 409)

        dossier = _draft_dossier(api, world)
        assert dossier["status"] == "DRAFT"
        assert dossier["claim_conformance"] == "PENDING"
        assert dossier["as_built_recycled_content_pct"] is None
        assert dossier["claim_variance_pct"] is None

    def test_issue_freezes_the_as_built_figure_and_reads_conforming(self, api):
        """A zero claim against a zero as-built figure varies by nothing.

        PRD: "sets `claim_conformance` to `CONFORMING` when the absolute value of
        that variance is no greater than 0.500 percentage points".

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)
        dossier = _draft_dossier(api, world)

        issued = validate_success(
            api.issue_compliance_dossier(dossier["id"], ISSUING_MANAGER), 200)
        assert issued["status"] == "ISSUED"
        assert issued["as_built_recycled_content_pct"] == pytest.approx(0.000,
                                                                       abs=0.01)
        assert issued["claim_variance_pct"] == pytest.approx(0.000, abs=0.01)
        assert issued["claim_conformance"] == "CONFORMING"

    def test_issue_stamps_the_acting_user_and_the_logical_clock(self, api):
        """The issuer is recorded from the request headers.

        PRD: "Issue also stamps `issued_by_user_id` with the acting `X-User-ID`
        and `issued_at` from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)
        dossier = _draft_dossier(api, world)
        issued = validate_success(
            api.issue_compliance_dossier(dossier["id"], ISSUING_MANAGER), 200)

        assert issued["issued_by_user_id"] == "u-qm-1"
        assert is_iso8601_timestamp(issued["issued_at"])
        assert issued["issued_at"].startswith("2026-08-05T06:00:00")

    def test_the_identical_release_succeeds_once_the_dossier_is_issued(self, api):
        """The tightened gate is met by a CONFORMING claim.

        PRD: "When the lot's `seal_final_verdict` is `CONDITIONAL`, that dossier's
        `claim_conformance` must additionally be `CONFORMING`, and a shortfall
        here is likewise `ERR_DOSSIER_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/conditional_lot_release_requires_issued_dossier_with_conforming_claim
        """
        world = _conditional_packed_lot(api)
        validate_error(api.release_bag_lot(world["bag_lot"]["id"], ISSUING_MANAGER),
                       ApiErrorId.ERR_DOSSIER_NOT_ISSUED, 409)
        dossier = _draft_dossier(api, world)
        get_success_data(api.issue_compliance_dossier(dossier["id"], ISSUING_MANAGER))

        released = validate_success(
            api.release_bag_lot(world["bag_lot"]["id"], ISSUING_MANAGER), 200)
        assert released["status"] == "RELEASED"
        assert released["count_accuracy_conforming"] is True
        assert released["packed_bag_count"] == 22500
