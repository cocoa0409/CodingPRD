"""Obligations, controls, and obligation-control mappings."""
from test_helpers import (
    ApiErrorId,
    create_approved_mapping,
    create_change,
    create_control,
    create_control_payload,
    create_mapping,
    create_mapping_payload,
    create_obligation,
    create_obligation_payload,
    create_triaged_change,
    get_control_now,
    list_gaps_for_obligation,
    make_officer_headers,
    setup_accepted_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    OFFICER_A,
    OFFICER_B,
    api_client,
)


class TestObligationLifecycle:
    def test_reinstate_cycle_keeps_mappings_retired(self, api, officer_a_headers):
        """PRD §3.2: "A successful retirement also retires every currently
        `APPROVED` mapping of the obligation. Reinstatement (`RETIRED` → `ACTIVE`)
        takes a `rationale` and is always permitted from `RETIRED`, but it does
        not resurrect the mappings that retirement took down — coverage must be
        rebuilt explicitly with fresh mappings."

        Design: Corner/state_machines/sm_obligation_reinstate_cycle_keeps_mappings_retired
        """
        change = create_triaged_change(citation="SM-7")
        obl = create_obligation(change["id"], obligation_code="OBL-SM-7", criticality="LOW")
        ctl = create_control(control_code="CTL-SM-7")
        mapping = create_approved_mapping(obl["id"], ctl["id"], coverage_weight=3)

        resp = api.retire_obligation(obl["id"], officer_a_headers)
        retired = validate_success(resp, 200)
        assert retired["status"] == "RETIRED"
        m_resp = api.get_mapping(mapping["id"], officer_a_headers)
        assert validate_success(m_resp)["status"] == "RETIRED", "Retire cascades to APPROVED mappings"

        resp = api.reinstate_obligation(
            obl["id"], {"rationale": "Retirement was premature"}, officer_a_headers
        )
        reinstated = validate_success(resp, 200)
        assert reinstated["status"] == "ACTIVE"
        m_resp = api.get_mapping(mapping["id"], officer_a_headers)
        assert validate_success(m_resp)["status"] == "RETIRED", "Reinstatement must not resurrect mappings"

    def test_obligation_in_use_blocks_retire(self, api, officer_a_headers):
        """PRD §3.2: "Retirement (`ACTIVE` → `RETIRED`) is refused with
        `ERR_OBLIGATION_IN_USE` while the obligation still has a gap analysis in
        `OPEN` or `IN_REVIEW`, or any implementation plan that has not reached
        `VERIFIED`".

        Design: Corner/validations/val_obligation_in_use_blocks_retire
        """
        pipe = setup_accepted_assessment(citation="VI-1", criticality="CRITICAL")
        obl = pipe["obligation"]
        assert pipe["gaps"] and pipe["gaps"][0]["status"] == "OPEN", "Setup failed: no OPEN gap"
        resp = api.retire_obligation(obl["id"], officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_OBLIGATION_IN_USE)
        data = validate_success(api.get_obligation(obl["id"], officer_a_headers), 200)
        assert data["status"] == "ACTIVE"


class TestControlRetire:
    def test_control_in_use_blocks_retire(self, api, officer_a_headers):
        """PRD §3.3: "A control can be retired (`ACTIVE` → `RETIRED`, terminal)
        only while no mapping referencing it stands `PROPOSED` or `APPROVED`;
        otherwise the retirement is rejected with `ERR_CONTROL_IN_USE`."

        Design: Corner/validations/val_control_in_use_blocks_retire
        """
        change = create_triaged_change(citation="VI-2")
        obl = create_obligation(change["id"], obligation_code="OBL-VI-2", criticality="LOW")
        ctl = create_control(control_code="CTL-VI-2")
        mapping = create_approved_mapping(obl["id"], ctl["id"], coverage_weight=2)

        resp = api.retire_control(ctl["id"], officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_CONTROL_IN_USE)

        retire_m = api.retire_mapping(mapping["id"], officer_a_headers)
        assert retire_m.status_code == 200, f"Setup failed: {retire_m.text}"
        resp = api.retire_control(ctl["id"], officer_a_headers)
        retired = validate_success(resp, 200)
        assert retired["status"] == "RETIRED"


class TestUniqueness:
    def test_duplicate_codes_rejected(self, api, officer_a_headers):
        """PRD §3.2: "the `obligation_code` is unique across all obligations ever
        created, and reuse is rejected with `ERR_DUPLICATE_OBLIGATION_CODE`."
        PRD §3.3: "Duplicate codes are rejected with `ERR_DUPLICATE_CONTROL_CODE`."

        Design: Corner/validations/val_duplicate_codes_rejected
        """
        change = create_triaged_change(citation="VD-2")
        create_obligation(change["id"], obligation_code="OBL-DUP-1", activate=False)
        resp = api.create_obligation(
            create_obligation_payload(
                obligation_code="OBL-DUP-1", regulatory_change_id=change["id"], criticality="HIGH"
            ),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OBLIGATION_CODE)

        create_control(control_code="CTL-DUP-1")
        resp = api.create_control(
            create_control_payload(control_code="CTL-DUP-1", owner_department="OPS", review_frequency_days=30),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONTROL_CODE)

    def test_duplicate_mapping_pair_and_reject_frees_slot(self, api, officer_a_headers):
        """PRD §3.3: "at most one non-terminal mapping may exist for a given
        obligation–control pair: a second mapping for the same pair while one
        stands `PROPOSED` or `APPROVED` is rejected with `ERR_DUPLICATE_MAPPING`."

        Design: Corner/validations/val_duplicate_mapping_pair_and_reject_frees_slot
        """
        change = create_triaged_change(citation="VD-3")
        obl = create_obligation(change["id"], obligation_code="OBL-VD-3", criticality="LOW")
        ctl = create_control(control_code="CTL-VD-3")
        first = create_mapping(obl["id"], ctl["id"], coverage_weight=3)

        resp = api.create_mapping(
            create_mapping_payload(obligation_id=obl["id"], control_id=ctl["id"], coverage_weight=5),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MAPPING)

        rej = api.reject_mapping(first["id"], {"reason": "Wrong weight"}, officer_a_headers)
        assert rej.status_code == 200, f"Setup failed: {rej.text}"
        resp = api.create_mapping(
            create_mapping_payload(obligation_id=obl["id"], control_id=ctl["id"], coverage_weight=5),
            officer_a_headers,
        )
        second = validate_success(resp, 201)
        assert second["coverage_weight"] == 5
        assert second["status"] == "PROPOSED"


class TestMappingCrossEntityGates:
    def test_mapping_with_draft_obligation_rejected(self, api, officer_a_headers):
        """PRD §3.3: "Both referenced records must be `ACTIVE` — failures surface
        as `ERR_OBLIGATION_NOT_ACTIVE` and `ERR_CONTROL_NOT_ACTIVE` respectively".

        Design: Difficulty/cross_entity_state_dependency/ced_mapping_requires_active_obligation_and_control
        """
        change = create_triaged_change(citation="CE-2")
        obl = create_obligation(change["id"], obligation_code="OBL-CE-2", criticality="MEDIUM", activate=False)
        ctl = create_control(control_code="CTL-CE2")
        resp = api.create_mapping(
            create_mapping_payload(obligation_id=obl["id"], control_id=ctl["id"], coverage_weight=5),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_ACTIVE)
        data, meta = validate_paginated(
            api.list_mappings(officer_a_headers, params={"obligation_id": obl["id"]})
        )
        assert meta["total_count"] == 0, "No mapping row may be created on failure"

    def test_mapping_with_retired_control_rejected(self, api, officer_a_headers):
        """PRD §3.3: "Both referenced records must be `ACTIVE` — failures surface
        as `ERR_OBLIGATION_NOT_ACTIVE` and `ERR_CONTROL_NOT_ACTIVE` respectively".
        PRD §3.3: "A control can be retired (`ACTIVE` → `RETIRED`, terminal) only
        while no mapping referencing it stands `PROPOSED` or `APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/ced_mapping_requires_active_obligation_and_control
        """
        change = create_triaged_change(citation="CE-2B")
        obl = create_obligation(change["id"], obligation_code="OBL-CE-2B", criticality="MEDIUM")
        ctl = create_control(control_code="CTL-CE2B")
        resp = api.retire_control(ctl["id"], officer_a_headers)
        assert resp.status_code == 200, f"Setup failed: {resp.text}"
        resp = api.create_mapping(
            create_mapping_payload(obligation_id=obl["id"], control_id=ctl["id"], coverage_weight=5),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTROL_NOT_ACTIVE)
        _data, meta = validate_paginated(
            api.list_mappings(officer_a_headers, params={"obligation_id": obl["id"]})
        )
        assert meta["total_count"] == 0
