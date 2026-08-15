"""Discretionary use authorizations: cell gates, uniqueness, decide lifecycle,
and the amendment freeze (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    STANDARD_MATRIX,
    create_recorded_easement,
    create_requested_use_authorization,
    create_submitted_amendment,
    create_use_authorization_payload,
    decide_use_authorization_payload,
    make_coordinator_headers,
    make_landowner_headers,
    validate_error,
    validate_success,
)


class TestUseAuthorizationCreation:
    def test_use_auth_on_prohibited_cell_rejected(self, api):
        """PRD §3.5: "the matrix cell must be `DISCRETIONARY` at request time,
        because a `PERMITTED` use needs no approval and a `PROHIBITED` use is
        never authorizable, either case drawing `ERR_USE_NOT_DISCRETIONARY`
        (422)"

        Design: Corner/validations/use_auth_on_prohibited_cell_rejected
        """
        ctx = create_recorded_easement(name="E-UP", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        resp = api.create_use_authorization(
            create_use_authorization_payload(
                ctx["easement"]["id"], use_type="SUBDIVISION",
                justification="split lot",
            ),
            make_landowner_headers(ctx["landowner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_USE_NOT_DISCRETIONARY)

    def test_duplicate_active_use_authorization_rejected(self, api):
        """PRD §3.5: "no active authorization — one in `REQUESTED`, `APPROVED`,
        or `APPROVED_WITH_CONDITIONS` — may already cover the same use type on
        the same easement, else `ERR_USE_CURRENTLY_AUTHORIZED` (409)"

        Design: Corner/validations/duplicate_active_use_authorization_rejected
        """
        ctx = create_recorded_easement(name="E-DU", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "TIMBER_HARVEST": "DISCRETIONARY"})
        landowner_id = ctx["landowner"]["id"]
        create_requested_use_authorization(
            ctx["easement"]["id"], landowner_id, use_type="TIMBER_HARVEST",
            justification="first",
        )
        resp = api.create_use_authorization(
            create_use_authorization_payload(
                ctx["easement"]["id"], use_type="TIMBER_HARVEST",
                justification="second",
            ),
            make_landowner_headers(landowner_id),
        )
        validate_error(resp, ApiErrorId.ERR_USE_CURRENTLY_AUTHORIZED)


class TestUseAuthorizationDecide:
    def test_use_auth_double_decide_rejected(self, api, coordinator_headers,
                                             trust_admin_headers):
        """PRD §3.5: "A `StewardshipCoordinator` decides a `REQUESTED`
        authorization; deciding from any other state is rejected with
        `ERR_INVALID_USE_AUTHORIZATION_STATE`."

        Design: Corner/state_machines/use_auth_double_decide_rejected
        """
        ctx = create_recorded_easement(name="E-UD", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "TIMBER_HARVEST": "DISCRETIONARY"})
        authorization = create_requested_use_authorization(
            ctx["easement"]["id"], ctx["landowner"]["id"], use_type="TIMBER_HARVEST"
        )
        decided = validate_success(
            api.decide_use_authorization(
                authorization["id"], decide_use_authorization_payload("APPROVED"),
                coordinator_headers,
            ),
            200,
        )
        assert decided["status"] == "APPROVED"

        resp = api.decide_use_authorization(
            authorization["id"], decide_use_authorization_payload("DENIED"),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_USE_AUTHORIZATION_STATE)
        after = validate_success(
            api.get_use_authorization(authorization["id"], trust_admin_headers), 200
        )
        assert after["status"] == "APPROVED"
        assert after["decision"] == "APPROVED"


class TestAmendmentFreeze:
    def test_use_auth_decide_frozen_by_inflight_amendment(self, api, coordinator_headers,
                                                          trust_admin_headers):
        """PRD §3.5: "Before any decision, a freeze check applies: if any
        amendment request of the same easement is in flight — `SUBMITTED`,
        `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` — and its
        `requested_changes` include this authorization's `use_type`, the decide
        is rejected with `ERR_AMENDMENT_FREEZE_CONFLICT` (409), because the
        cell's very meaning is under review."

        Design: Difficulty/cross_entity_state_dependency/use_auth_decide_frozen_by_inflight_amendment
        """
        ctx = create_recorded_easement(name="E-CE2", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        easement_id = ctx["easement"]["id"]
        authorization = create_requested_use_authorization(
            easement_id, ctx["landowner"]["id"], use_type="TIMBER_HARVEST",
            justification="thinning",
        )
        amendment = create_submitted_amendment(
            easement_id,
            ctx["version"],
            requested_changes=[{"use_type": "TIMBER_HARVEST",
                                "new_level": "PROHIBITED"}],
            affected_acreage=100,
        )
        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)

        resp = api.decide_use_authorization(
            authorization["id"], decide_use_authorization_payload("APPROVED"),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_FREEZE_CONFLICT)
        after = validate_success(
            api.get_use_authorization(authorization["id"], trust_admin_headers), 200
        )
        assert after["status"] == "REQUESTED", "frozen decide leaves the authorization untouched"

    def test_use_auth_decide_allowed_after_amendment_withdrawn(self, api, coordinator_headers):
        """PRD §3.5: "if any amendment request of the same easement is in flight
        — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` —
        and its `requested_changes` include this authorization's `use_type`, the
        decide is rejected with `ERR_AMENDMENT_FREEZE_CONFLICT` (409)"
        PRD §3.6: "A coordinator may withdraw the request from any non-terminal
        state — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or
        `BOARD_REVIEW` — moving it to `WITHDRAWN`."
        PRD §3.5: "A `decision` of `APPROVED` moves the authorization to
        `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/use_auth_decide_frozen_by_inflight_amendment
        """
        ctx = create_recorded_easement(name="E-CE2B", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        easement_id = ctx["easement"]["id"]
        authorization = create_requested_use_authorization(
            easement_id, ctx["landowner"]["id"], use_type="TIMBER_HARVEST",
            justification="thinning",
        )
        amendment = create_submitted_amendment(
            easement_id,
            ctx["version"],
            requested_changes=[{"use_type": "TIMBER_HARVEST",
                                "new_level": "PROHIBITED"}],
            affected_acreage=100,
        )
        # WITHDRAWN is terminal, so nothing remains in flight and the freeze lifts.
        validate_success(api.withdraw_amendment_request(amendment["id"], coordinator_headers), 200)

        decided = validate_success(
            api.decide_use_authorization(
                authorization["id"], decide_use_authorization_payload("APPROVED"),
                coordinator_headers,
            ),
            200,
        )
        assert decided["status"] == "APPROVED"
        assert decided["decision"] == "APPROVED"
