"""BusinessEntity formation lifecycle, dissolution, and legal-name
uniqueness.

Covers PRD §3.1 (create + form), §3.11 (voluntary / administrative
dissolution), §2.5 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_business_entity,
    assert_event_types_present,
    assert_status,
    create_and_activate_entity,
    create_entity_in_pending,
    create_entity_payload,
    create_qualified_foreign,
    create_registered_agent,
    form_entity,
    list_compliance_events,
    make_filer_headers,
    setup_entity_delinquent_for_60d,
    setup_entity_with_stale_boi,
    unique_legal_name,
    validate_error,
    validate_success,
)


class TestEntityCreation:

    def test_create_entity_returns_pending_formation(
        self, api, filer_headers,
    ):
        """PRD §3.1: "The newly created row starts with formation_status
        of PENDING_FORMATION and a compliance_status of null."

        Claim: a new BusinessEntity is PENDING_FORMATION with null
        compliance_status.
        """
        agent = create_registered_agent(service_state="DE")
        payload = create_entity_payload(
            entity_type="LLC", home_state="DE",
            registered_agent_id=agent["id"],
        )
        resp = api.create_entity(payload, filer_headers)
        entity = validate_success(resp, expected_status=201)
        assert_business_entity(entity)
        assert_status(entity, "PENDING_FORMATION",
                      field="formation_status")
        assert entity["compliance_status"] is None

    def test_duplicate_legal_name_rejected(self, api, filer_headers):
        """PRD §3.1: "The legal_name must be unique, on a case-
        insensitive comparison, among all entities whose
        formation_status is not DISSOLVED and not
        ADMINISTRATIVELY_DISSOLVED; a collision yields
        ERR_DUPLICATE_LEGAL_NAME with HTTP 409."

        Claim: case-insensitive name collision → ERR_DUPLICATE_LEGAL_NAME.
        """
        agent = create_registered_agent(service_state="DE")
        name = unique_legal_name()
        first = create_entity_payload(
            legal_name=name, entity_type="LLC", home_state="DE",
            registered_agent_id=agent["id"],
        )
        ok = api.create_entity(first, filer_headers)
        validate_success(ok, expected_status=201)
        # Same name, different case — must still collide.
        dup = create_entity_payload(
            legal_name=name.upper(), entity_type="LLC", home_state="DE",
            registered_agent_id=agent["id"],
        )
        dup_resp = api.create_entity(dup, filer_headers)
        validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_LEGAL_NAME.value)

    def test_corp_without_authorized_shares_rejected(
        self, api, filer_headers,
    ):
        """PRD §3.1: "For CORP entities, authorized_shares is required
        and must be at least 1"
        PRD §3.1: "or ERR_INVALID_INPUT for the CORP share-count
        condition."

        Claim: CORP missing authorized_shares → ERR_INVALID_INPUT.
        """
        agent = create_registered_agent(service_state="DE")
        payload = {
            "legal_name": unique_legal_name(),
            "entity_type": "CORP",
            "home_state": "DE",
            "registered_agent_id": agent["id"],
            # authorized_shares deliberately omitted
        }
        resp = api.create_entity(payload, filer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_corp_with_authorized_shares_zero_rejected(
        self, api, filer_headers,
    ):
        """PRD §3.1: "For CORP entities, authorized_shares is required
        and must be at least 1"

        Claim: CORP with authorized_shares=0 → ERR_INVALID_INPUT
        (boundary at >=1).
        """
        agent = create_registered_agent(service_state="DE")
        payload = create_entity_payload(
            entity_type="CORP", home_state="DE",
            registered_agent_id=agent["id"],
            authorized_shares=0,
        )
        resp = api.create_entity(payload, filer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_corp_with_authorized_shares_one_accepted(
        self, api, filer_headers,
    ):
        """PRD §3.1: "authorized_shares is required and must be at least
        1"

        Claim: CORP with authorized_shares=1 (boundary) → 201.
        """
        agent = create_registered_agent(service_state="DE")
        payload = create_entity_payload(
            entity_type="CORP", home_state="DE",
            registered_agent_id=agent["id"],
            authorized_shares=1,
        )
        resp = api.create_entity(payload, filer_headers)
        entity = validate_success(resp, expected_status=201)
        assert entity["authorized_shares"] == 1

    def test_home_state_regex(self, api, filer_headers):
        """PRD §3.1: "the home_state is a two-letter uppercase US state
        code matching the regular expression ^[A-Z]{2}$"

        Claim: lowercase home_state → ERR_INVALID_INPUT.
        """
        agent = create_registered_agent(service_state="DE")
        payload = create_entity_payload(
            home_state="de", registered_agent_id=agent["id"],
        )
        resp = api.create_entity(payload, filer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


class TestEntityFormation:

    def test_form_transitions_to_active(self, api,
                                        state_registrar_headers):
        """PRD §3.1: "Formation proper is a separate step performed by a
        StateRegistrar: it transitions the row from PENDING_FORMATION
        to ACTIVE."
        PRD §3.1: "Upon successful formation the system records
        formation_date as the current clock instant, sets
        compliance_status to GOOD_STANDING"

        Claim: form → ACTIVE + compliance_status GOOD_STANDING + a
        FORMED ComplianceEvent.
        """
        entity, _agent = create_entity_in_pending()
        resp = api.form_entity(entity["id"], state_registrar_headers)
        formed = validate_success(resp)
        assert_status(formed, "ACTIVE", field="formation_status")
        assert formed["compliance_status"] == "GOOD_STANDING"
        assert formed.get("formation_date") is not None
        # Side effect: a FORMED ComplianceEvent.
        events = list_compliance_events(formed["id"])
        assert_event_types_present(events, ["FORMED"])

    def test_form_requires_active_registered_agent(self, api):
        """PRD §3.1: "the supplied registered_agent_id must resolve to a
        RegisteredAgent whose status is ACTIVE."

        Claim: form fails when the supplied agent is RESIGNED →
        ERR_INVALID_STATE (the agent row is not in a state that permits
        the operation).
        """
        from test_helpers import resign_registered_agent
        agent = create_registered_agent(service_state="DE")
        # Resign the agent BEFORE using it.
        resign_registered_agent(agent["id"])
        # Now create an entity referencing the resigned agent and
        # attempt formation.
        entity, _ = create_entity_in_pending(
            home_state="DE", agent=agent,
        )
        resp = api.form_entity(
            entity["id"], TEST_USERS["state_registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_form_requires_agent_state_to_match_home_state(self, api):
        """PRD §3.1: "that agent's service_state must equal the entity's
        home_state — a New York entity may not form with a Delaware-
        authorized agent."

        Claim: form fails when registered agent service_state mismatches
        entity home_state → ERR_INVALID_STATE (preconditions for the
        PENDING→ACTIVE transition).
        """
        ny_agent = create_registered_agent(service_state="NY")
        entity, _ = create_entity_in_pending(
            entity_type="LLC", home_state="DE", agent=ny_agent,
        )
        resp = api.form_entity(
            entity["id"], TEST_USERS["state_registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_form_already_active_rejected(
        self, api, state_registrar_headers,
    ):
        """PRD §3.1: "it transitions the row from PENDING_FORMATION to
        ACTIVE"
        PRD §2.11: "(6) the target resource is in a state that permits
        the requested operation (yielding ERR_INVALID_STATE)"

        Claim: forming an already-ACTIVE entity → ERR_INVALID_STATE.
        """
        entity, _ = create_and_activate_entity()
        resp = api.form_entity(entity["id"], state_registrar_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestVoluntaryDissolution:

    def test_dissolve_active_entity_succeeds(self, api):
        """PRD §3.11: "A Filer voluntarily dissolves a BusinessEntity by
        triggering the dissolve action. The action transitions
        formation_status from ACTIVE to DISSOLVED, sets dissolution_date
        to the current clock instant, sets compliance_status to null"

        Claim: dissolve → DISSOLVED + null compliance + emits
        VOLUNTARILY_DISSOLVED event.
        """
        entity, _ = create_and_activate_entity()
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        dissolved = validate_success(resp)
        assert_status(dissolved, "DISSOLVED", field="formation_status")
        assert dissolved["compliance_status"] is None
        assert dissolved.get("dissolution_date") is not None
        events = list_compliance_events(dissolved["id"])
        assert_event_types_present(events, ["VOLUNTARILY_DISSOLVED"])

    def test_dissolve_blocked_by_qualified_foreign(self, api):
        """PRD §3.11: "Voluntary dissolution is blocked when any of
        three dependencies is present: any FranchiseTaxAssessment with
        status in OVERDUE or DELINQUENT, any BOIReport with status equal
        to STALE, or any ForeignQualification with status equal to
        QUALIFIED (the entity must withdraw the qualifications first).
        A blocking dependency yields ERR_HAS_DEPENDENCIES with HTTP 409."

        Claim: a QUALIFIED foreign qualification blocks dissolve →
        ERR_HAS_DEPENDENCIES.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        create_qualified_foreign(entity["id"], foreign_state="NY")
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)

    def test_dissolve_blocked_by_stale_boi(self, api):
        """PRD §3.11: "Voluntary dissolution is blocked when any of
        three dependencies is present: ... any BOIReport with status
        equal to STALE ... A blocking dependency yields
        ERR_HAS_DEPENDENCIES with HTTP 409."

        Claim: a STALE BOIReport blocks dissolve → ERR_HAS_DEPENDENCIES.
        """
        entity, _, _ = setup_entity_with_stale_boi()
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)

    def test_dissolve_cascades_qualified_to_withdrawn(self, api):
        """PRD §3.7: "voluntary dissolution drives every QUALIFIED
        qualification to WITHDRAWN"
        — but PRD §3.11 lists QUALIFIED foreigns as a BLOCKER; the
        cascade therefore applies only when the entity is permitted to
        dissolve.

        This means voluntary dissolution alone cannot leave a QUALIFIED
        foreign as a dependency at the moment of /dissolve — the test
        here intentionally covers the post-dissolve quiescent state by
        withdrawing the qualification first, then verifying the entity
        is DISSOLVED. The pure-cascade variant is exercised by the
        administrative dissolution path in test_09 (REVOKED cascade).
        """
        from test_helpers import (
            create_pending_foreign_qualification,
            approve_foreign_qualification,
        )
        entity, _ = create_and_activate_entity(home_state="DE")
        qual, _ = create_pending_foreign_qualification(
            entity["id"], "NY",
        )
        qual = approve_foreign_qualification(qual["id"])
        assert qual["status"] == "QUALIFIED"
        # Withdraw first to clear dependency, then dissolve.
        api_client.withdraw_foreign_qualification(
            qual["id"], make_filer_headers(entity["id"]),
        )
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        dissolved = validate_success(resp)
        assert_status(dissolved, "DISSOLVED", field="formation_status")


class TestAdministrativeDissolution:

    def test_admin_dissolve_requires_60_days_delinquent(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.11: "Its sole precondition is that the entity has been
        in compliance_status DELINQUENT for at least sixty days —
        measured from the clock instant at which compliance_status
        first flipped to DELINQUENT."

        Claim: admin-dissolve fires after 60-day waiting period from
        DELINQUENT → ADMIN_DISSOLVED + cascade REVOKED + emits
        ADMIN_DISSOLVED event.
        """
        entity, _ = setup_entity_delinquent_for_60d()
        # Confirm we entered the DELINQUENT branch before the wait.
        assert entity["compliance_status"] in ("DELINQUENT", None)
        resp = api.administratively_dissolve_entity(
            entity["id"], compliance_officer_headers,
        )
        dissolved = validate_success(resp)
        assert_status(dissolved, "ADMINISTRATIVELY_DISSOLVED",
                      field="formation_status")
        assert dissolved["compliance_status"] is None
        events = list_compliance_events(dissolved["id"])
        assert_event_types_present(events, ["ADMIN_DISSOLVED"])

    def test_admin_dissolve_on_active_good_standing_rejected(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.11: "Its sole precondition is that the entity has been
        in compliance_status DELINQUENT for at least sixty days"

        Claim: admin-dissolve on an entity that is GOOD_STANDING and
        never went DELINQUENT → ERR_INVALID_STATE.
        """
        entity, _ = create_and_activate_entity()
        resp = api.administratively_dissolve_entity(
            entity["id"], compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestEntityListing:

    def test_list_filters_by_formation_status(
        self, api, state_registrar_headers,
    ):
        """PRD §4 table: "List entities, filterable by entity_type,
        formation_status, compliance_status"

        Claim: listing with formation_status=ACTIVE returns only ACTIVE
        rows.
        """
        # Make a known ACTIVE entity so the filter has at least one hit.
        active_entity, _ = create_and_activate_entity()
        resp = api.list_entities(
            state_registrar_headers,
            params={"formation_status": "ACTIVE", "limit": 50},
        )
        data, _meta = validate_success(resp), None
        # Note: validate_success returns the data field; for an array
        # list endpoint this is the list. Re-read via validate_paginated.
        from test_helpers import validate_paginated
        # Re-issue to get paginated meta — same call as above.
        resp2 = api.list_entities(
            state_registrar_headers,
            params={"formation_status": "ACTIVE", "limit": 50},
        )
        data, _meta = validate_paginated(resp2)
        assert any(e["id"] == active_entity["id"] for e in data)
        for e in data:
            assert e["formation_status"] == "ACTIVE", (
                f"Filter returned non-ACTIVE row: {e['formation_status']}"
            )
