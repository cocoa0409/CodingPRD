"""Discount-rate tables: terminal retirement and half-open window semantics."""
from test_helpers import (
    ApiErrorId,
    assert_rate_table,
    create_rate_table_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestRateTableTerminalState:
    def test_rate_table_retire_is_terminal(self, api, compliance_headers):
        """PRD §3.2: "A transition with `action` `RETIRE` moves a `DRAFT` or
        `ACTIVE` table to the terminal `RETIRED` status".
        PRD §2.10: "State-machine legality for the requested transition or
        action — `ERR_INVALID_STATE`, including terminal-state lockdown".

        Design: Corner/state_machines/rate_table_retire_is_terminal
        """
        table = validate_success(
            api.create_rate_table(create_rate_table_payload(label="T"), compliance_headers),
            201,
        )
        validate_success(
            api.transition_rate_table(table["id"], {"action": "ACTIVATE"}, compliance_headers)
        )
        retired = validate_success(
            api.transition_rate_table(table["id"], {"action": "RETIRE"}, compliance_headers)
        )
        assert retired["status"] == "RETIRED"

        resp = api.transition_rate_table(table["id"], {"action": "ACTIVATE"}, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409


class TestRateTableWindowOverlap:
    def _create_t1(self, api, compliance_headers):
        table = validate_success(
            api.create_rate_table(
                create_rate_table_payload(
                    label="H1-2026",
                    effective_from="2026-01-01T00:00:00Z",
                    effective_to="2026-07-01T00:00:00Z",
                ),
                compliance_headers,
            ),
            201,
        )
        return table

    def test_intersecting_and_open_ended_windows_rejected(self, api, compliance_headers):
        """PRD §2.7: "Among tables in `DRAFT` or `ACTIVE` status, no two windows
        may intersect; adjacency — one table's `effective_from` equal to
        another's `effective_to` — is **not** an overlap. A violation, detected
        at table creation or at activation, is rejected with
        `ERR_RATE_WINDOW_OVERLAP` (HTTP 409)."
        PRD §2.7: "A null `effective_to` reads as open-ended, extending to
        infinity."

        Design: Difficulty/resource_temporal_overlap/rate_table_half_open_window_adjacency
        """
        self._create_t1(api, compliance_headers)

        # One-month intersection with H1-2026's window -> rejected.
        resp = api.create_rate_table(
            create_rate_table_payload(
                label="overlap-June",
                discount_rate_bps=520,
                effective_from="2026-06-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z",
            ),
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)
        assert resp.status_code == 409

        # Adjacent successor accepted, then an open-ended window intersecting it.
        adjacent = validate_success(
            api.create_rate_table(
                create_rate_table_payload(
                    label="H2-2026",
                    discount_rate_bps=520,
                    effective_from="2026-07-01T00:00:00Z",
                    effective_to="2027-01-01T00:00:00Z",
                ),
                compliance_headers,
            ),
            201,
        )
        assert adjacent["status"] == "DRAFT"

        resp = api.create_rate_table(
            create_rate_table_payload(
                label="open-ended",
                discount_rate_bps=540,
                effective_from="2026-08-01T00:00:00Z",
            ),
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)
        assert resp.status_code == 409

    def test_adjacent_window_accepted_half_open_semantics(self, api, compliance_headers):
        """PRD §2.7: "A `RateTable` carries a `label`, a `discount_rate_bps` rate
        in basis points, and an effectiveness window defined by `effective_from`
        (inclusive) and `effective_to` (exclusive) — a **half-open interval**."
        PRD §2.7: "adjacency — one table's `effective_from` equal to another's
        `effective_to` — is **not** an overlap."

        Design: Difficulty/resource_temporal_overlap/rate_table_half_open_window_adjacency
        """
        t1 = self._create_t1(api, compliance_headers)

        resp = api.create_rate_table(
            create_rate_table_payload(
                label="H2-2026",
                discount_rate_bps=520,
                effective_from="2026-07-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z",
            ),
            compliance_headers,
        )
        adjacent = validate_success(resp, 201)
        assert_rate_table(adjacent)
        assert adjacent["status"] == "DRAFT"
        assert adjacent["effective_from"] != t1["effective_from"]
        assert is_valid_uuid(adjacent["id"])

    def test_activation_rechecks_window_overlap(self, api, compliance_headers):
        """PRD §3.2: "From `DRAFT`, a transition with `action` `ACTIVATE` moves it
        to `ACTIVE`, re-checking the window against every other `DRAFT` or
        `ACTIVE` table (`ERR_RATE_WINDOW_OVERLAP` on intersection)."

        Adjacent tables activate cleanly against each other under half-open
        semantics (adjacency is not an overlap, per PRD §2.7).

        Design: Difficulty/resource_temporal_overlap/rate_table_half_open_window_adjacency
        """
        t1 = self._create_t1(api, compliance_headers)
        active = validate_success(
            api.transition_rate_table(t1["id"], {"action": "ACTIVATE"}, compliance_headers)
        )
        assert active["status"] == "ACTIVE"

        t2 = validate_success(
            api.create_rate_table(
                create_rate_table_payload(
                    label="H2-2026",
                    discount_rate_bps=520,
                    effective_from="2026-07-01T00:00:00Z",
                    effective_to="2027-01-01T00:00:00Z",
                ),
                compliance_headers,
            ),
            201,
        )
        activated = validate_success(
            api.transition_rate_table(t2["id"], {"action": "ACTIVATE"}, compliance_headers)
        )
        assert activated["status"] == "ACTIVE"
