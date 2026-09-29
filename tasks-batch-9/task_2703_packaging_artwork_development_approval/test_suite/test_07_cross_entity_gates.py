"""Writes blocked by the state of a row two hops up, and of a child row."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approved_version,
    coord,
    create_plate_order_payload,
    decide_brief,
    decide_color,
    decide_substrate,
    new_asset,
    new_brief,
    new_printer,
    new_proof,
    new_version,
    plate_orders_for_version,
    read_asset,
    read_brief,
    read_version,
    release,
    release_payload,
    routes_for,
    current_route,
    submit,
    submit_payload,
    validate_error,
    validate_success,
    verify,
)


class TestSubmitReadsTheGrandparentBrief:
    """A flawless version whose only obstacle is the brief two hops up."""

    def _verified_under_a_draft_brief(self):
        brief = new_brief()
        assert brief["status"] == "DRAFT"
        asset = new_asset(brief["id"])
        version = new_version(asset)
        verified = verify(version["id"])
        assert verified["state"] == "ELEMENTS_VERIFIED"
        assert verified["failed_element_count"] == 0
        assert verified["compliance_score"] == 100.0
        assert verified["route_count"] == 0
        return brief, version

    def test_a_draft_brief_blocks_a_version_that_is_otherwise_submittable(self):
        """Nothing on the version is wrong; the blocking status lives on the brief.

        PRD §3.1: "Approval is deliberately *not* a prerequisite for downstream
        drafting. Assets and artwork versions may be created and edited under a brief
        that is still in `DRAFT`; it is only the moment a version is pushed into
        review that the owning brief's `status` must read `APPROVED`, and a submission
        under a `DRAFT` or `REJECTED` brief is refused with
        `ERR_BRIEF_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_grandparent_brief_status_not_on_version_state
        """
        _brief, version = self._verified_under_a_draft_brief()

        response = api_client.submit_artwork_version(
            version["id"], submit_payload(), coord()
        )
        validate_error(response, ApiErrorId.ERR_BRIEF_NOT_APPROVED.value, 409)

        after = read_version(version["id"])
        assert after["state"] == "ELEMENTS_VERIFIED"
        assert after["route_count"] == 0
        assert routes_for(version["id"]) == []

    def test_approving_only_the_brief_admits_the_identical_submission(self):
        """The brief decision is the single change that opens the gate.

        PRD §3.5: "The owning brief's `status` must be `APPROVED`, else
        `ERR_BRIEF_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_grandparent_brief_status_not_on_version_state
        """
        brief, version = self._verified_under_a_draft_brief()

        refused = api_client.submit_artwork_version(
            version["id"], submit_payload(), coord()
        )
        validate_error(refused, ApiErrorId.ERR_BRIEF_NOT_APPROVED.value, 409)

        decide_brief(brief["id"], "APPROVED")
        assert read_brief(brief["id"])["status"] == "APPROVED"

        submitted = submit(version["id"])
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["route_count"] == 1

        route = current_route(version["id"])
        assert route["current_stage_no"] == 1
        assert route["status"] == "IN_PROGRESS"


class TestReleaseAndPlateOrderReadTheChildProof:
    """Two endpoints consulting one derived child state."""

    def _half_resolved_proof(self):
        _brief, asset, version = approved_version(
            asset_overrides={"brand_critical_color": False, "plate_budget_cents": 500000}
        )
        printer = new_printer()
        proof = new_proof(version["id"], printer)
        assert proof["press_check_required"] is False
        assert proof["press_check_status"] == "NOT_REQUIRED"

        after_color = decide_color(proof["id"], 1.2)
        assert after_color["color_status"] == "COLOR_PASS"
        assert after_color["substrate_status"] == "SUBSTRATE_PENDING"
        assert after_color["proof_state"] == "PROOF_IN_REVIEW"
        return asset, version, printer, proof

    def test_release_waits_for_the_derived_proof_state(self):
        """A substrate decision that never names the version flips the release gate.

        PRD §3.5: "And at least one proof of the version must read `PROOF_APPROVED`,
        else `ERR_PROOF_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/release_and_plate_order_gated_on_child_proof_state_resolution
        """
        _asset, version, _printer, proof = self._half_resolved_proof()

        response = api_client.release_to_print(
            version["id"], release_payload(), coord()
        )
        validate_error(response, ApiErrorId.ERR_PROOF_NOT_APPROVED.value, 422)
        assert read_version(version["id"])["state"] == "APPROVED"

        resolved = decide_substrate(proof["id"], "SUBSTRATE_APPROVED")
        assert resolved["substrate_status"] == "SUBSTRATE_APPROVED"
        assert resolved["proof_state"] == "PROOF_APPROVED"

        released = release(version["id"])
        assert released["state"] == "RELEASED_TO_PRINT"

    def test_the_plate_order_consults_the_same_child_state(self):
        """The order is refused on the proof, not on the budget it comfortably fits.

        PRD §3.7: "And the named proof's `proof_state` must read `PROOF_APPROVED`,
        else `ERR_PROOF_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/release_and_plate_order_gated_on_child_proof_state_resolution
        """
        asset, version, printer, proof = self._half_resolved_proof()
        payload = create_plate_order_payload(
            version["id"], printer["id"], proof["id"], plate_set_count=6
        )

        refused = api_client.create_plate_order(payload, coord())
        validate_error(refused, ApiErrorId.ERR_PROOF_NOT_APPROVED.value, 422)
        assert plate_orders_for_version(version["id"]) == []
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        decide_substrate(proof["id"], "SUBSTRATE_APPROVED")

        accepted = validate_success(
            api_client.create_plate_order(payload, coord()), 201
        )
        assert accepted["status"] == "ORDERED"
        # 4 * 18000 + 2 * 15500 + a 60000 setup fee.
        assert accepted["cost_cents"] == 163000
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 163000
