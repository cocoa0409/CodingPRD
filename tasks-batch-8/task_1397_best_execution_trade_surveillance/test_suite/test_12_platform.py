"""Platform-wide contracts: response envelopes, logical clock, auth,
pagination-adjacent plumbing, arrangement OCC, the ops-run checkpoint, and
immediate consistency (PRD §2.1-§2.6, §2.9)."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    make_employee,
    make_personal_trade,
    make_venue,
    make_active_arrangement,
    approve_trade,
    create_restricted_entry_payload,
    ops_run,
    publish_policy,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_covered_employee_headers

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]

MISSING_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestEnvelopes:
    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" and
        'The `response_type` is either "object" for a single resource or
        "array" for a list of resources.' PRD §2.2: "All error API responses
        (4xx status codes) follow this standard envelope format" carrying
        `data.error_id` and `data.message`.

        Design: Corner/endpoints/success_and_error_envelope_shapes
        """
        venue = make_venue(venue_code="NYSE", name="New York Stock Exchange")

        # Any role may read; CoveredEmployee identity is not compared on GETs.
        ok = api.get_venue(venue["id"], make_covered_employee_headers(MISSING_ID))
        data = validate_success(ok)
        body = ok.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert data["venue_code"] == "NYSE"

        missing = api.get_venue(MISSING_ID, CA)
        err = validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
        body = missing.json()
        assert body["response_type"] == "error"
        assert err["message"], "error envelope carries a human-readable message"

    def test_get_missing_venue_returns_404(self, api):
        """PRD §2.5: "every identifier in the path — and every resource
        identifier supplied in the request body, such as an `arrangement_id`,
        a list of `snapshot_ids`, or venue identifiers — is validated left to
        right, and the first identifier that does not resolve to an existing
        resource fails the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_missing_venue_returns_404
        """
        resp = api.get_venue(MISSING_ID, CA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.json()["response_type"] == "error"


class TestClock:
    def test_clock_set_endpoint_and_monotonic_guard(self, api):
        """PRD §2.4: "At server startup the clock reads exactly
        2026-08-01T00:00:00Z" and "The clock is monotonic: the supplied
        `to_iso8601` must be greater than or equal to the current clock value,
        and any attempt to move it backwards is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 409)."

        Design: Corner/endpoints/clock_set_endpoint_and_monotonic_guard
        """
        # The set succeeds, proving the untouched default is not ahead of
        # 2026-08-02; the response echoes the resulting current_utc.
        data = validate_success(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, OPS))
        assert _parse(data["current_utc"]) == _parse("2026-08-02T00:00:00Z")

        resp = api.set_clock({"to_iso8601": "2026-08-01T12:00:00Z"}, OPS)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


class TestAuthentication:
    def test_request_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these seven roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_missing_role_header_returns_unauthenticated
        """
        resp = api.get_venue(MISSING_ID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestArrangementOcc:
    def test_occ_arrangement_amend_stale_version_rejected(self, api):
        """PRD §2.6: "Amending a routing arrangement requires
        `expected_arrangement_version`, matched against the arrangement's
        current `version`. A successful amendment increments the arrangement's
        `version` by one." and "if the resource's current `version` has
        advanced beyond that observed value, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/complexity_layers/occ_arrangement_amend_stale_version_rejected
        """
        venue = make_venue(venue_code="NYSE")
        arrangement = make_active_arrangement(venue["id"])
        observed = arrangement["version"]  # version after the activation bump

        amended = validate_success(api.amend_arrangement(
            arrangement["id"],
            {"expected_arrangement_version": observed, "routing_fee_bps": 5},
            CA))
        assert amended["version"] == observed + 1

        stale = api.amend_arrangement(
            arrangement["id"],
            {"expected_arrangement_version": observed, "routing_fee_bps": 7},
            CA)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestOpsRunCheckpoint:
    def test_ops_run_checkpoint_flips_four_epochs(self, api):
        """PRD §2.4: "an `OpsAdmin`-only capability that evaluates the current
        logical clock and fires every due epoch sweep in one pass:
        restricted-list entries activate or expire, approved-but-unexecuted
        personal trades lapse, attestation windows roll from current to due to
        lapsed, and training assignments slip to overdue. The checkpoint
        response reports per-category tallies — `restricted_activated`,
        `restricted_expired`, `preclearances_expired`, `preclearances_denied`,
        `attestations_due`, `attestations_lapsed`, and
        `training_marked_overdue`".

        Design: Corner/complexity_layers/ops_run_checkpoint_flips_four_epochs
        """
        e1 = make_employee(employee_ref="EMP-E1", full_name="Ep One",
                           attestation_due_at="2026-09-01T00:00:00Z")
        # 31 days of runway at the 2026-08-01 default clock -> CURRENT.
        assert e1["attestation_status"] == "CURRENT"
        e2 = make_employee(employee_ref="EMP-E2", full_name="Ep Two")
        trade = make_personal_trade(e2["id"], symbol="ZZZ", side="BUY", quantity=10)
        approve_trade(trade["id"])  # expires_at = 2026-08-03T00:00:00Z
        validate_success(api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="ALL",
            effective_from="2026-08-02T00:00:00Z", effective_to="2026-08-05T00:00:00Z",
        ), CA), expected_status=201)
        publish_policy(version_label="v2026.1")  # assignments due 2026-08-31 for both

        # Run 1: entry activates; E1 enters the 30-day due window (due minus
        # 30 days is exactly 2026-08-02).
        set_clock("2026-08-02T00:00:00Z")
        run1 = ops_run()
        assert run1["restricted_activated"] == 1
        assert run1["attestations_due"] == 1
        assert run1["preclearances_expired"] == 0

        # Run 2: the approved trade is past its 48-hour expiry.
        set_clock("2026-08-04T00:00:01Z")
        run2 = ops_run()
        assert run2["preclearances_expired"] == 1

        # Run 3: both assignments slip overdue; the entry expires; E1 lapses.
        set_clock("2026-09-01T00:00:00Z")
        run3 = ops_run()
        assert run3["training_marked_overdue"] == 2
        assert run3["restricted_expired"] == 1
        assert run3["attestations_lapsed"] == 1


class TestImmediateConsistency:
    def test_mutations_visible_immediately_in_same_and_next_read(self, api):
        """PRD §4: "reads, modifications, transitions, and action endpoints
        respond with HTTP 200 and the affected resource". PRD §2.8: "Once
        frozen, values never silently recompute — a frozen surface changes
        only through an explicit lifecycle action defined in §3."

        Design: Corner/consistency_model/mutations_visible_immediately_in_same_and_next_read
        """
        created = make_venue(venue_code="NYSE", name="New York Stock Exchange")
        assert created["status"] == "ACTIVE"

        transitioned = validate_success(api.venue_transition(created["id"], {"to_status": "SUSPENDED"}, CA))
        assert transitioned["status"] == "SUSPENDED", "the transition response carries the new state"

        reread = validate_success(api.get_venue(created["id"], CA))
        assert reread["status"] == "SUSPENDED", "the next read agrees — no eventual lag"
