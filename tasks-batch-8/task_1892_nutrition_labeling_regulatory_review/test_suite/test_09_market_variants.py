"""Market variants: creation guards (same-market, duplicate, window shape,
half-open overlap), activation gating on the base label and the logical
clock, and retirement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_label,
    create_label_draft,
    create_market_variant,
    create_market_variant_payload,
    set_clock,
    setup_wafer_workspace,
    submit_label,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]


def _list_variants(api, label_version_id):
    return validate_paginated(api.list_market_variants(label_version_id, ADMIN))


class TestVariantCreationGuards:
    def test_same_market_variant_rejected(self, api):
        """PRD §3.8: "The target market must differ from the base label's
        market — a same-market variant is rejected with
        `ERR_SAME_MARKET_VARIANT` — and only one non-retired variant may exist
        per base label and target market (`ERR_DUPLICATE_MARKET_VARIANT`)."

        Design: Corner/validations/val_same_market_variant_rejected
        """
        ws = setup_wafer_workspace()
        resp = api.create_market_variant(
            ws["label"]["id"],
            create_market_variant_payload("2026-09-01T00:00:00Z",
                                          market_code="US_FDA"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_SAME_MARKET_VARIANT,
                       expected_status=422)

    def test_duplicate_market_variant_rejected(self, api):
        """PRD §3.8: "The target market must differ from the base label's
        market — a same-market variant is rejected with
        `ERR_SAME_MARKET_VARIANT` — and only one non-retired variant may exist
        per base label and target market (`ERR_DUPLICATE_MARKET_VARIANT`)."

        Design: Corner/validations/val_duplicate_market_variant_rejected
        """
        ws = setup_wafer_workspace()
        create_market_variant(ws["label"]["id"], market_code="CA_CFIA",
                              effective_start="2026-09-01T00:00:00Z",
                              effective_end="2027-03-01T00:00:00Z")
        # A disjoint window still collides: the base label + market pair is taken.
        resp = api.create_market_variant(
            ws["label"]["id"],
            create_market_variant_payload("2027-06-01T00:00:00Z",
                                          market_code="CA_CFIA"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MARKET_VARIANT,
                       expected_status=409)

    def test_window_invalid_rejected(self, api):
        """PRD §3.8: "The effective window must be well-formed, with
        `effective_end`, when present, strictly after `effective_start`
        (`ERR_WINDOW_INVALID`), and it must not overlap the windows of other
        non-retired variants for the same product and market under the
        half-open semantics of §2.7 — adjacency is allowed, overlap is
        `ERR_MARKET_WINDOW_OVERLAP`."

        Design: Corner/validations/val_window_invalid_rejected
        """
        ws = setup_wafer_workspace()
        resp = api.create_market_variant(
            ws["label"]["id"],
            create_market_variant_payload("2027-03-01T00:00:00Z",
                                          market_code="CA_CFIA",
                                          effective_end="2027-03-01T00:00:00Z"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID, expected_status=422)


class TestVariantWindowOverlap:
    def test_adjacent_windows_accepted(self, api):
        """PRD §2.7: "Market-variant effective windows are half-open
        intervals: the window includes `effective_start`, excludes
        `effective_end`, and a missing `effective_end` means the window is
        open-ended; two windows that merely touch at a boundary do not
        overlap."
        PRD §3.8: "A new variant starts in `DRAFT` status."

        Design: Difficulty/resource_temporal_overlap/mv_window_halfopen_adjacency
        """
        ws = setup_wafer_workspace(submit=True)
        create_market_variant(ws["label"]["id"], market_code="CA_CFIA",
                              effective_start="2026-09-01T00:00:00Z",
                              effective_end="2027-03-01T00:00:00Z")

        lv2 = create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                                 statement_recipe_id=ws["recipe"]["id"])
        # Starts exactly at the first variant's end: adjacency, not overlap.
        resp = api.create_market_variant(
            lv2["id"],
            create_market_variant_payload("2027-03-01T00:00:00Z",
                                          market_code="CA_CFIA"),
            ANALYST)
        variant = validate_success(resp, 201)
        assert variant["status"] == "DRAFT"

    def test_overlapping_window_rejected(self, api):
        """PRD §2.7: "Market-variant effective windows are half-open
        intervals: the window includes `effective_start`, excludes
        `effective_end`, and a missing `effective_end` means the window is
        open-ended; two windows that merely touch at a boundary do not
        overlap."
        PRD §3.8: "The effective window must be well-formed, with
        `effective_end`, when present, strictly after `effective_start`
        (`ERR_WINDOW_INVALID`), and it must not overlap the windows of other
        non-retired variants for the same product and market under the
        half-open semantics of §2.7 — adjacency is allowed, overlap is
        `ERR_MARKET_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/mv_window_halfopen_adjacency
        """
        ws = setup_wafer_workspace(submit=True)
        create_market_variant(ws["label"]["id"], market_code="CA_CFIA",
                              effective_start="2026-09-01T00:00:00Z",
                              effective_end="2027-03-01T00:00:00Z")

        lv2 = create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                                 statement_recipe_id=ws["recipe"]["id"])
        resp = api.create_market_variant(
            lv2["id"],
            create_market_variant_payload("2027-02-01T00:00:00Z",
                                          market_code="CA_CFIA",
                                          effective_end="2027-06-01T00:00:00Z"),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_MARKET_WINDOW_OVERLAP,
                       expected_status=409)


class TestVariantActivation:
    def test_activation_blocked_while_label_in_review(self, api):
        """PRD §3.8: "Activation requires the variant to be `DRAFT`
        (`ERR_INVALID_STATE_TRANSITION`), requires the base label's
        `review_status` to be `APPROVED` (`ERR_LABEL_NOT_APPROVED`), and
        requires the logical clock to read at or after `effective_start` and —
        when the window is bounded — strictly before `effective_end`
        (`ERR_VARIANT_NOT_IN_WINDOW`); the overlap check against sibling
        non-retired variants is re-run at this moment, so a window that became
        conflicting since creation is still caught with
        `ERR_MARKET_WINDOW_OVERLAP`."

        Design: Difficulty/cross_entity_state_dependency/variant_activation_blocked_by_unapproved_label
        """
        ws = setup_wafer_workspace(submit=True)
        assert ws["label"]["review_status"] == "IN_REVIEW"
        variant = create_market_variant(
            ws["label"]["id"], market_code="CA_CFIA",
            effective_start="2026-09-01T00:00:00Z",
            effective_end="2027-03-01T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")  # inside the window

        resp = api.activate_market_variant(variant["id"],
                                           ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED,
                       expected_status=409)
        variants, _meta = _list_variants(api, ws["label"]["id"])
        assert variants[0]["status"] == "DRAFT"

    def test_activation_succeeds_once_label_approved(self, api):
        """PRD §3.8: "Activation moves the variant to `ACTIVE` and increments
        its `version`."
        PRD §3.8: "Activation requires the variant to be `DRAFT`
        (`ERR_INVALID_STATE_TRANSITION`), requires the base label's
        `review_status` to be `APPROVED` (`ERR_LABEL_NOT_APPROVED`), and
        requires the logical clock to read at or after `effective_start` and —
        when the window is bounded — strictly before `effective_end`
        (`ERR_VARIANT_NOT_IN_WINDOW`); the overlap check against sibling
        non-retired variants is re-run at this moment, so a window that became
        conflicting since creation is still caught with
        `ERR_MARKET_WINDOW_OVERLAP`."

        Design: Difficulty/cross_entity_state_dependency/variant_activation_blocked_by_unapproved_label
        """
        ws = setup_wafer_workspace(submit=True)
        variant = create_market_variant(
            ws["label"]["id"], market_code="CA_CFIA",
            effective_start="2026-09-01T00:00:00Z",
            effective_end="2027-03-01T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        approve_label(ws["label"]["id"])

        activated = validate_success(
            api.activate_market_variant(variant["id"],
                                        ws["quality_manager_headers"]),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == variant["version"] + 1

    def test_variant_not_in_window_rejected(self, api):
        """PRD §3.8: "Activation requires the variant to be `DRAFT`
        (`ERR_INVALID_STATE_TRANSITION`), requires the base label's
        `review_status` to be `APPROVED` (`ERR_LABEL_NOT_APPROVED`), and
        requires the logical clock to read at or after `effective_start` and —
        when the window is bounded — strictly before `effective_end`
        (`ERR_VARIANT_NOT_IN_WINDOW`); the overlap check against sibling
        non-retired variants is re-run at this moment, so a window that became
        conflicting since creation is still caught with
        `ERR_MARKET_WINDOW_OVERLAP`."
        PRD §2.7: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before any administrative set call, the clock
        continues to read this default and never falls back to wall-clock
        time."

        Design: Corner/validations/val_variant_not_in_window_rejected
        """
        ws = setup_wafer_workspace(submit=True)
        approve_label(ws["label"]["id"])
        variant = create_market_variant(
            ws["label"]["id"], market_code="CA_CFIA",
            effective_start="2026-09-01T00:00:00Z",
            effective_end="2027-03-01T00:00:00Z")
        set_clock("2027-06-01T00:00:00Z")  # past the bounded window's end

        resp = api.activate_market_variant(variant["id"],
                                           ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_VARIANT_NOT_IN_WINDOW,
                       expected_status=409)
        variants, _meta = _list_variants(api, ws["label"]["id"])
        assert variants[0]["status"] == "DRAFT"


class TestVariantRetirement:
    def test_retire_from_draft_returns_invalid_state(self, api):
        """PRD §3.8: "Retirement moves an `ACTIVE` variant to `RETIRED` —
        again guarded by `ERR_INVALID_STATE_TRANSITION` — increments
        `version`, and frees its window for future variants."

        Design: Corner/state_machines/sm_market_variant_retire_from_draft_returns_invalid_state
        """
        ws = setup_wafer_workspace()
        variant = create_market_variant(
            ws["label"]["id"], market_code="CA_CFIA",
            effective_start="2026-09-01T00:00:00Z",
            effective_end="2027-03-01T00:00:00Z")
        assert variant["status"] == "DRAFT"
        resp = api.retire_market_variant(variant["id"],
                                         ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)
