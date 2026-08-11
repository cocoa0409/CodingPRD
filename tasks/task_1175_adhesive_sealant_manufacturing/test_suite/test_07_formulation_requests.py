"""Technical-service formulation request pipeline: cycles, branches, conversion."""
from test_helpers import (
    ApiErrorId,
    create_convert_payload,
    create_distributor,
    create_formulation_request_payload,
    make_distributor_headers,
    validate_error,
    validate_success,
)


def _new_request(api, distributor, name="Lee", substrate="aluminum", strength=15.0, notes="high peel strength"):
    return validate_success(
        api.create_formulation_request(
            create_formulation_request_payload(
                distributor["id"], contact_name=name, target_substrate=substrate,
                required_bond_strength_mpa=strength, application_notes=notes,
            ),
            make_distributor_headers(distributor["id"]),
        ),
        expected_status=201,
    )


class TestRequestCycleThenApproveBranch:
    """Difficulty instance formulation_request_cycle_then_approve_branch."""

    def _setup_looped_twice_approved(self, api, tech_service_headers):
        distributor = create_distributor(name="Dist FR", contact_email="f@x.com")
        dist_headers = make_distributor_headers(distributor["id"])
        request = _new_request(api, distributor)
        rid = request["id"]
        validate_success(api.start_review(rid, tech_service_headers))
        # Loop 1
        req = validate_success(api.request_info(rid, {"info_request_note": "need temperature range"}, tech_service_headers))
        assert req["status"] == "NEEDS_INFO"
        req = validate_success(api.respond(rid, {"response_note": "-40 to 120 C service"}, dist_headers))
        assert req["status"] == "TECH_REVIEW"
        # Loop 2
        req = validate_success(api.request_info(rid, {"info_request_note": "need target viscosity"}, tech_service_headers))
        assert req["status"] == "NEEDS_INFO"
        req = validate_success(api.respond(rid, {"response_note": "5000 cP"}, dist_headers))
        assert req["status"] == "TECH_REVIEW"
        # Branch: APPROVED
        req = validate_success(api.decide(rid, {"outcome": "APPROVED", "decision_note": "feasible"}, tech_service_headers))
        assert req["status"] == "APPROVED"
        assert req["decision_outcome"] == "APPROVED"
        req = validate_success(api.start_development(rid, tech_service_headers))
        assert req["status"] == "IN_DEVELOPMENT"
        return distributor, rid

    def test_info_cycle_traversed_twice_then_converted(self, api, tech_service_headers):
        """PRD §3.7: "From `TECH_REVIEW` the engineer may either request more information — moving the request to `NEEDS_INFO` and recording the payload's note into `info_request_note` — or decide it. The owning distributor answers an information request by calling respond, which cycles the request from `NEEDS_INFO` back into `TECH_REVIEW` and records the payload's `response_note`; only the distributor whose `distributor_id` owns the request may respond, otherwise `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Difficulty/non_linear_state_machine/formulation_request_cycle_then_approve_branch
        """
        _distributor, rid = self._setup_looped_twice_approved(api, tech_service_headers)
        # Cycle evidence: the request survived two NEEDS_INFO -> TECH_REVIEW loops
        # (asserted inline above) and is now IN_DEVELOPMENT on the APPROVED branch.
        current = validate_success(api.get_formulation_request(rid, tech_service_headers))
        assert current["status"] == "IN_DEVELOPMENT"
        assert current["info_request_note"] == "need target viscosity"
        assert current["response_note"] == "5000 cP"

        converted = validate_success(api.convert(rid, create_convert_payload(), tech_service_headers))
        assert converted["status"] == "CONVERTED"
        assert converted["resulting_formulation_id"]

    def test_convert_mints_new_draft_formulation(self, api, tech_service_headers, plant_manager_headers):
        """PRD §3.7: "the convert action completes the pipeline: it creates a brand-new `Formulation` in `DRAFT` from the convert payload's `formulation_code`, `formulation_name`, `chemistry_family`, `moisture_sensitive`, `solvent_content_pct`, `flash_point_c`, `pot_life_minutes`, `shelf_life_months`, `spec_min_bond_strength_mpa`, and `min_remaining_shelf_life_days`, sets the request's `resulting_formulation_id` to the new formulation's id, and moves the request to `CONVERTED`."

        Design: Difficulty/non_linear_state_machine/formulation_request_cycle_then_approve_branch
        """
        _distributor, rid = self._setup_looped_twice_approved(api, tech_service_headers)
        converted = validate_success(api.convert(rid, create_convert_payload(), tech_service_headers))
        new_id = converted["resulting_formulation_id"]
        assert converted["status"] == "CONVERTED"

        formulation = validate_success(api.get_formulation(new_id, plant_manager_headers))
        assert formulation["status"] == "DRAFT"
        assert formulation["code"] == "TS-9001"
        assert formulation["spec_min_bond_strength_mpa"] == 15.0


class TestRequestInvalidTransitions:
    def test_decide_from_submitted_returns_409(self, api, tech_service_headers):
        """PRD §3.7: "Every step requires the request to be in the expected from-state, failing with `ERR_REQUEST_INVALID_STATE` otherwise."

        Design: Corner/state_machines/decide_from_submitted_returns_409
        """
        distributor = create_distributor(name="Dist DC", contact_email="dc@x.com")
        request = _new_request(api, distributor, name="Ana", substrate="steel", strength=14.0, notes="structural")
        resp = api.decide(request["id"], {"outcome": "APPROVED"}, tech_service_headers)
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        after = validate_success(api.get_formulation_request(request["id"], tech_service_headers))
        assert after["status"] == "SUBMITTED"
