"""Regulatory change intake, triage cycle, supersession, and list behavior."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_business_owner,
    create_change,
    create_change_payload,
    create_triaged_change,
    get_change,
    make_business_owner_headers,
    make_officer_headers,
    parse_iso,
    triage_change,
    validate_error,
    validate_paginated,
    validate_success,
    OFFICER_A,
    OFFICER_B,
    api_client,
)


class TestChangeCreation:
    def test_create_defaults(self, api, officer_a_headers):
        """PRD §3.1: "The new record enters as `PENDING_TRIAGE` with `applicability`
        set to `UNDETERMINED` and `triage_round` at zero, and `created_by_user_id`
        is stamped from the caller."
        PRD §3.1: "The `triaged_by_user_id` and `business_owner_id` fields remain
        empty until a first triage and a first assessment respectively,
        `superseded_by_id` stays empty unless a newer revision supersedes the
        record, and `risk_tier` stays unset until an assessment is first accepted."
        PRD §2.4: "the logical clock reads exactly 2026-08-01T00:00:00Z".

        Design: Corner/entities/entity_change_create_defaults
        """
        resp = api.create_regulatory_change(
            create_change_payload(citation="DFLT-1", severity_hint="MEDIUM"), officer_a_headers
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING_TRIAGE"
        assert data["applicability"] == "UNDETERMINED"
        assert data["triage_round"] == 0
        assert data["version"] == 1
        assert data["created_by_user_id"] == "officer-a"
        assert data["superseded_by_id"] is None
        assert data["risk_tier"] is None
        assert parse_iso(data["created_at"]) == parse_iso("2026-08-01T00:00:00Z")

    def test_create_missing_required_citation_returns_400(self, api, officer_a_headers):
        """PRD §2.10: "Priority 2.5 — request-body shape: a missing required field,
        a type mismatch, an invalid enum member, or an unparseable datetime yields
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: ingestion supplies "its `citation` (for example, "12 CFR Part
        1005"), a `title`, a free-text `summary`, the `feed_source`".

        Design: Corner/entities/entity_change_missing_required_returns_400
        """
        payload = create_change_payload(title="No citation")
        del payload["citation"]
        resp = api.create_regulatory_change(payload, officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_regulatory_changes(officer_a_headers))
        assert meta["total_count"] == 0, f"No row may be created, got {meta['total_count']}"

    def test_create_invalid_feed_source_rejected(self, api, officer_a_headers):
        """PRD §2.10: "Priority 2.5 — request-body shape: a missing required field,
        a type mismatch, an invalid enum member, or an unparseable datetime yields
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: "the `feed_source` — one of `FED_REGISTER`, `STATE_BULLETIN`,
        `INT_JOURNAL`, or `MANUAL_ENTRY`".

        Design: Corner/entities/entity_change_invalid_feed_source_rejected
        """
        resp = api.create_regulatory_change(
            create_change_payload(citation="EN-1", feed_source="TWITTER"), officer_a_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_change_not_found(self, api, officer_a_headers):
        """PRD §2.10: "Priority 3 — existence: path identifiers are validated
        left-to-right, then foreign keys carried in the body
        (`regulatory_change_id`, `business_owner_id`, `obligation_id`,
        `control_id`, `gap_analysis_id`, `implementation_plan_id`,
        `supersedes_change_id`); any miss yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/entity_get_change_not_found
        """
        resp = api.get_regulatory_change(NON_EXISTENT_UUID, officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_pagination(self, api, officer_a_headers):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of list responses carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/entity_changes_list_pagination
        """
        for i in range(1, 4):
            resp = api.create_regulatory_change(create_change_payload(citation=f"PG-{i}"), officer_a_headers)
            assert resp.status_code == 201, f"Setup failed: {resp.text}"
        page1, meta1 = validate_paginated(
            api.list_regulatory_changes(officer_a_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_regulatory_changes(officer_a_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False

    def test_list_pagination_with_filter(self, api, officer_a_headers):
        """PRD §3.1: "Analysts can browse the backlog filtered by `status`,
        `jurisdiction`, `severity_hint`, or `business_owner_id`".
        PRD §2.3: "The `meta` object of list responses carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_layers/layer_pagination_with_filter_interaction
        """
        api.create_regulatory_change(
            create_change_payload(citation="PF-1", jurisdiction="US-FED"), officer_a_headers
        )
        api.create_regulatory_change(
            create_change_payload(citation="PF-2", jurisdiction="US-CA", regulator="DFPI"), officer_a_headers
        )
        api.create_regulatory_change(
            create_change_payload(citation="PF-3", jurisdiction="US-FED", severity_hint="HIGH"), officer_a_headers
        )
        page1, meta1 = validate_paginated(
            api.list_regulatory_changes(
                officer_a_headers, params={"jurisdiction": "US-FED", "limit": 1, "offset": 0}
            )
        )
        assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
        assert all(c["jurisdiction"] == "US-FED" for c in page1)
        page2, meta2 = validate_paginated(
            api.list_regulatory_changes(
                officer_a_headers, params={"jurisdiction": "US-FED", "limit": 1, "offset": 1}
            )
        )
        assert len(page2) == 1 and meta2["total_count"] == 2 and meta2["has_more"] is False


class TestTriageCycle:
    def test_triage_from_triaged_applicable_rejected(self, api, officer_a_headers, officer_b_headers):
        """PRD §3.1: "The change must currently be `PENDING_TRIAGE` (otherwise
        `ERR_INVALID_STATE`)".
        PRD §3.1: "`triage_round` increments by one on every triage decision".

        Design: Corner/state_machines/sm_triage_from_triaged_applicable_rejected
        """
        change = create_triaged_change(citation="SM-1")
        resp = api.triage_regulatory_change(
            change["id"], {"verdict": "NOT_APPLICABLE", "rationale": "changed mind"}, officer_b_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_change(change["id"])
        assert after["status"] == "TRIAGED_APPLICABLE"
        assert after["triage_round"] == 1

    def test_retriage_cycle_accumulates_rounds(self, api, officer_b_headers):
        """PRD §3.1: "A `ComplianceOfficer` — again, never the original ingester —
        may pull a `TRIAGED_NOT_APPLICABLE` change back into `PENDING_TRIAGE` by
        supplying a fresh `rationale`. This retriage resets `applicability` to
        `UNDETERMINED`, overwrites `triage_rationale` with the retriage rationale,
        leaves `triaged_by_user_id` unchanged, and advances the change's `version`
        by one."

        Design: Difficulty/non_linear_state_machine/nsm_change_retriage_cycle
        """
        change = create_change(citation="RT-1")
        triaged = triage_change(change["id"], verdict="NOT_APPLICABLE", rationale="No NY footprint")
        assert triaged["status"] == "TRIAGED_NOT_APPLICABLE"
        assert triaged["triage_round"] == 1
        resp = api.retriage_regulatory_change(
            change["id"], {"rationale": "Legal flagged for re-review"}, officer_b_headers
        )
        back = validate_success(resp, 200)
        assert back["status"] == "PENDING_TRIAGE"
        assert back["applicability"] == "UNDETERMINED"

    def test_retriage_then_second_triage_round_two(self, api, officer_b_headers):
        """PRD §3.1: "The cycle can repeat any number of times; a retriage
        pull-back is not a verdict, so the triage round counter is not advanced
        by it."
        PRD §3.1: "`triage_round` increments by one on every triage decision".

        Design: Difficulty/non_linear_state_machine/nsm_change_retriage_cycle
        """
        change = create_change(citation="RT-2")
        triage_change(change["id"], verdict="NOT_APPLICABLE", rationale="No NY footprint")
        api.retriage_regulatory_change(
            change["id"], {"rationale": "Legal flagged for re-review"}, officer_b_headers
        )
        resp = api.triage_regulatory_change(
            change["id"],
            {"verdict": "APPLICABLE", "rationale": "Applies after revised interpretation"},
            officer_b_headers,
        )
        final = validate_success(resp, 200)
        assert final["status"] == "TRIAGED_APPLICABLE"
        assert final["applicability"] == "APPLICABLE"
        assert final["triage_round"] == 2, "Cycle accumulates rounds; retriage does not reset"


class TestSupersession:
    def test_superseded_terminal_lockdown(self, api, officer_a_headers, officer_b_headers):
        """PRD §3.1: "On success the older change moves to `SUPERSEDED` — a
        terminal state — with its `superseded_by_id` pointing at the new record."
        PRD §3.1: "The change must currently be `PENDING_TRIAGE` (otherwise
        `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/sm_superseded_terminal_lockdown
        """
        change_a = create_change(citation="SM-3A", title="old rev")
        resp = api.create_regulatory_change(
            create_change_payload(citation="SM-3B", title="new rev", supersedes_change_id=change_a["id"]),
            officer_a_headers,
        )
        change_b = validate_success(resp, 201)
        old = get_change(change_a["id"])
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_id"] == change_b["id"]
        resp = api.triage_regulatory_change(
            change_a["id"], {"verdict": "APPLICABLE", "rationale": "r"}, officer_b_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_supersede_triaged_applicable_rejected(self, api, officer_a_headers):
        """PRD §3.1: "the named change must exist (`ERR_NOT_FOUND`) and must still
        stand in `PENDING_TRIAGE` or `TRIAGED_NOT_APPLICABLE`; targeting a change
        in any other status is rejected on the creating call with
        `ERR_CHANGE_NOT_SUPERSEDABLE` (409)".

        Design: Corner/errors/err_change_not_supersedeable_after_applicable
        """
        change_a = create_triaged_change(citation="NS-1", verdict="APPLICABLE")
        resp = api.create_regulatory_change(
            create_change_payload(citation="NS-2", supersedes_change_id=change_a["id"]),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_NOT_SUPERSEDABLE)
        old = get_change(change_a["id"])
        assert old["status"] == "TRIAGED_APPLICABLE"
        assert old["superseded_by_id"] is None


class TestTriageConsistency:
    def test_triage_response_matches_immediate_read(self, api, officer_a_headers, officer_b_headers, secretary_1_headers):
        """PRD §3.1: "Either way, the rationale is stored as `triage_rationale`,
        `triage_round` increments by one on every triage decision,
        `triaged_by_user_id` records the actor, the change's `version` advances by
        one, and the system computes a `provisional_risk_tier`."
        PRD §3.1: "The provisional rating maps the analyst's `severity_hint` to a
        severity score — `LOW` counts 1, `MEDIUM` counts 2, `HIGH` counts 4,
        `CRITICAL` counts 5 — multiplies that score by an assumed likelihood of 3
        and a scope multiplier fixed at 1.0, and tiers the resulting raw product
        as follows: below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at
        least 12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`."

        Design: Corner/consistency_model/consistency_immediate_read_after_write
        """
        change = create_change(citation="IM-2", severity_hint="HIGH")
        resp = api.triage_regulatory_change(
            change["id"], {"verdict": "APPLICABLE", "rationale": "r"}, officer_b_headers
        )
        triaged = validate_success(resp, 200)
        assert triaged["status"] == "TRIAGED_APPLICABLE"
        assert triaged["provisional_risk_tier"] == "HIGH", "4 x 3 x 1.0 = 12.0 -> HIGH"
        assert triaged["version"] == change["version"] + 1
        reread = validate_success(api.get_regulatory_change(change["id"], secretary_1_headers), 200)
        assert reread["status"] == triaged["status"]
        assert reread["provisional_risk_tier"] == triaged["provisional_risk_tier"]
        assert reread["version"] == triaged["version"]
