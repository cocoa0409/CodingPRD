"""IPRight lifecycle tests for the IP Management API.

Covers PRD §3.2:
- DRAFT creation
- DRAFT → MATERIALS_READY (preconditions: agent verified for AGENCY,
  assigned_agent_id == null for SELF, agent jurisdiction must match for AGENCY)
- MATERIALS_READY → FILED on first jurisdiction filing
"""

from test_helpers import (
    ApiErrorId,
    assert_ip_right,
    create_agent,
    create_business_unit,
    create_business_unit_payload,
    create_filing_payload,
    create_ip_right_in_draft,
    create_ip_right_payload,
    setup_foundation,
    validate_error,
    validate_success,
)


# ─────────────────────────────────────────────────────────────
# Creation in DRAFT (PRD §3.2)
# ─────────────────────────────────────────────────────────────


class TestIPRightCreation:
    """A newly-created IPRight enters DRAFT (PRD §3.2)."""

    def test_create_in_draft_with_agency_handling(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "The newly created right enters `DRAFT` status."

        Claim: POST /ip-rights with AGENCY + verified agent → 201 with
        status == DRAFT.
        """
        found = setup_foundation(api)
        payload = create_ip_right_payload(
            assigned_agent_id=found["agent"]["id"],
            business_unit_id=found["business_unit"]["id"],
        )
        resp = api.create_ip_right(payload, ip_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_ip_right(data)
        assert data["status"] == "DRAFT"
        assert data["handling_mode"] == "AGENCY"

    def test_create_self_handling_with_null_agent(self, api, ip_manager_headers):
        """PRD §3.2: "an optional `assigned_agent_id` (required when
        `handling_mode` is `AGENCY` and required to be null when
        `handling_mode` is `SELF`)."

        Claim: SELF handling with assigned_agent_id == null → 201, DRAFT.
        """
        bu = create_business_unit(api)
        payload = create_ip_right_payload(
            handling_mode="SELF",
            assigned_agent_id=None,
            business_unit_id=bu["id"],
        )
        resp = api.create_ip_right(payload, ip_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["handling_mode"] == "SELF"


# ─────────────────────────────────────────────────────────────
# DRAFT → MATERIALS_READY preconditions (PRD §3.2)
# ─────────────────────────────────────────────────────────────


class TestMaterialsReadyTransition:
    """DRAFT → MATERIALS_READY rules per PRD §3.2."""

    def test_materials_ready_success(self, api, ip_manager_headers):
        """PRD §3.2: "Marking application materials ready advances the right
        from `DRAFT` to `MATERIALS_READY`."

        Claim: with a verified agent matching jurisdiction, materials-ready
        succeeds and status becomes MATERIALS_READY.
        """
        found = setup_foundation(api, agent_jurisdictions=["US"])
        ip = create_ip_right_in_draft(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        resp = api.mark_materials_ready(ip["id"], {}, ip_manager_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "MATERIALS_READY"

    def test_create_agency_with_unverified_agent_rejected(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "An unverified agent on an `AGENCY` right is rejected
        with `ERR_AGENT_QUALIFICATION_UNVERIFIED`."

        Claim: AGENCY-mode IPRight create with qualification_verified==false
        agent → ERR_AGENT_QUALIFICATION_UNVERIFIED. (PRD §3.2 names the
        check at create-time; we exercise it on POST /ip-rights.)
        """
        bu = create_business_unit(api)
        unverified = create_agent(api, verified=False, jurisdictions=["US"])
        payload = create_ip_right_payload(
            assigned_agent_id=unverified["id"],
            business_unit_id=bu["id"],
        )
        resp = api.create_ip_right(payload, ip_manager_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_AGENT_QUALIFICATION_UNVERIFIED,
            expected_status=422,
        )

    def test_create_agency_agent_jurisdiction_mismatch(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "An `AGENCY` right whose assigned `Agent` does not list
        the right's `primary_jurisdiction` in its `jurisdictions` array is
        rejected with `ERR_AGENT_JURISDICTION_MISMATCH` at creation time."

        Claim: AGENCY-mode IPRight where agent jurisdictions exclude the
        right's primary_jurisdiction → ERR_AGENT_JURISDICTION_MISMATCH.
        """
        bu = create_business_unit(api)
        agent_jp = create_agent(api, verified=True, jurisdictions=["JP"])
        payload = create_ip_right_payload(
            assigned_agent_id=agent_jp["id"],
            business_unit_id=bu["id"],
            primary_jurisdiction="US",
        )
        resp = api.create_ip_right(payload, ip_manager_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_AGENT_JURISDICTION_MISMATCH,
            expected_status=422,
        )


# ─────────────────────────────────────────────────────────────
# Invalid-state transitions (PRD §2.7 priority 5 + §3.2)
# ─────────────────────────────────────────────────────────────


class TestInvalidStateTransitions:
    """An action invoked on a wrong-state target returns ERR_INVALID_STATE,
    per PRD §2.7."""

    def test_materials_ready_on_non_draft_rejected(self, api, ip_manager_headers):
        """PRD §2.7: "an action endpoint invoked on an entity that is not in
        a state from which the requested transition is defined returns
        `ERR_INVALID_STATE`."

        Claim: calling materials-ready twice → second call returns
        ERR_INVALID_STATE.
        """
        found = setup_foundation(api)
        ip = create_ip_right_in_draft(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        api.mark_materials_ready(ip["id"], {}, ip_manager_headers)
        resp2 = api.mark_materials_ready(ip["id"], {}, ip_manager_headers)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─────────────────────────────────────────────────────────────
# Body foreign-key resolution (PRD §2.6, §2.7 priority 4)
# ─────────────────────────────────────────────────────────────


class TestBodyForeignKey:
    """Missing body FK references resolve to ERR_REFERENCED_ENTITY_NOT_FOUND
    (422), per PRD §2.6."""

    def test_unknown_business_unit_in_body(self, api, ip_manager_headers):
        """PRD §2.6: "a foreign-key reference carried in the request body ...
        is treated as a business-input validation: a missing referent
        returns `ERR_REFERENCED_ENTITY_NOT_FOUND` at HTTP 422."

        Claim: POST /ip-rights with unknown business_unit_id →
        ERR_REFERENCED_ENTITY_NOT_FOUND (422).
        """
        payload = create_ip_right_payload(
            handling_mode="SELF",
            assigned_agent_id=None,
            business_unit_id="00000000-0000-0000-0000-000000000000",
        )
        resp = api.create_ip_right(payload, ip_manager_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
            expected_status=422,
        )
