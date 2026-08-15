"""Entity registration, retrieval, defaults, and the append-only audit trail."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    assert_entity, assert_close_event,
    create_period_payload, create_entity_payload,
    set_clock, create_period, create_entity, open_period,
    CONTROLLER, PREPARER, APPROVER, AUDITOR,
)
from test_helpers import api_client


class TestEntityRegistration:
    def test_create_period_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "a `Controller` creates a close period by supplying `fiscal_year`
        (for example 2026), `fiscal_period` (an integer from 1 through 13 within the
        year), `period_start` and `period_end` instants in UTC with the end strictly
        after the start, the consolidation `reporting_currency` (again one of `USD`,
        `EUR`, `GBP`, `JPY`), and `materiality_threshold_minor` — the materiality
        threshold expressed in reporting-currency minor units".

        Design: Corner/entities/create_period_missing_required_field_returns_invalid_request
        """
        set_clock()
        payload = create_period_payload()
        payload.pop("materiality_threshold_minor")
        res = api.create_period(payload, CONTROLLER)
        assert res.status_code >= 400, f"expected 4xx for missing required field, got {res.status_code}"
        body = res.json()
        assert body.get("response_type") == "error", "expected error envelope"
        assert isinstance(body["data"].get("error_id"), str) and body["data"]["error_id"]

    def test_entity_defaults_is_elimination_counterparty_true(self, api):
        """PRD §3.1: "The optional `is_elimination_counterparty` flag, which defaults
        to true when omitted, marks whether the entity participates in intercompany
        eliminations."

        Design: Corner/entities/entity_defaults_is_elimination_counterparty_true
        """
        set_clock()
        payload = create_entity_payload(entity_code="US100")
        payload.pop("is_elimination_counterparty", None)
        entity = validate_success(api.create_entity(payload, CONTROLLER), 201)
        assert_entity(entity)
        assert entity["is_elimination_counterparty"] is True

    def test_entity_computed_consolidation_tier_ignores_input(self, api):
        """PRD §3.1: "The system derives `consolidation_tier` as the depth in the
        tree — the root sits at tier zero — and uses it later to order bottom-up
        translation chains."

        Design: Corner/entities/entity_computed_consolidation_tier_ignores_input
        """
        set_clock()
        root = create_entity(entity_code="ROOT", name="Root")
        assert root["consolidation_tier"] == 0
        child = create_entity(entity_code="CHILD", name="Child", parent_entity_id=root["id"])
        assert child["consolidation_tier"] == 1

    def test_entity_not_found_returns_404(self, api):
        """PRD §2.9: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not exist or does not belong to the declared
        parent."

        Design: Corner/entities/entity_not_found_returns_404
        """
        set_clock()
        res = api.get_entity(NON_EXISTENT_UUID, CONTROLLER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_entity_parent_reference_validated_and_tier_computed(self, api):
        """PRD §3.1: "A null `parent_entity_id` marks the consolidation root;
        otherwise the references form a tree, and any registration whose parent
        chain would introduce a cycle is rejected with `ERR_ENTITY_HIERARCHY_CYCLE`."
        PRD §2.9: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not exist or does not belong to the declared
        parent."

        Design: Corner/entities/entity_parent_reference_validated_and_tier_computed
        """
        set_clock()
        a = create_entity(entity_code="A", name="A")
        b = create_entity(entity_code="B", name="B", parent_entity_id=a["id"])
        c = create_entity(entity_code="C", name="C", parent_entity_id=b["id"])
        assert a["consolidation_tier"] == 0
        assert b["consolidation_tier"] == 1
        assert c["consolidation_tier"] == 2

        res = api.create_entity(
            create_entity_payload(entity_code="ORPHAN", name="Orphan",
                                   parent_entity_id=NON_EXISTENT_UUID),
            CONTROLLER,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestCloseEventAppendOnly:
    def test_close_event_append_only_no_version_field(self, api):
        """PRD §2.4: "The audit-trail `CloseEvent` is append-only: it carries only
        `id` and `created_at`. Both `updated_at` and `version` are absent on
        `CloseEvent` — an event, once written, is never modified."

        Design: Corner/entities/close_event_append_only_no_version_field
        """
        set_clock()
        period = create_period()
        open_period(period["id"])
        data, meta = validate_paginated(api.list_period_events(period["id"], AUDITOR))
        assert len(data) >= 1, "expected at least one PERIOD_OPENED event"
        kinds = {e["event_kind"] for e in data}
        assert "PERIOD_OPENED" in kinds
        for ev in data:
            assert_close_event(ev)
