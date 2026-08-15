"""Operators and certification windows: closed-interval overlap geometry,
issuance-time temporal guards, revocation and re-issuance, and the exact
expiry instant against the logical clock."""
from test_helpers import (
    ApiErrorId,
    assert_operator_certification,
    get_success_data,
    make_certification,
    make_operator,
    record_continuity,
    setup_order_in_build,
    advance_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import make_quality_inspector_headers

QM = TEST_USERS["quality_manager_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestCertificationWindowGeometry:
    def test_cert_touching_existing_window_rejected(self, api):
        """PRD §3.3: "Overlap uses closed-interval semantics — the new window overlaps an existing one when the new `issued_at` is on or before the existing `expires_at` and the existing `issued_at` is on or before the new `expires_at` — so windows that merely touch at an endpoint are rejected, and the rejection is `ERR_CERT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certification_closed_interval_touch_rejected
        """
        operator = make_operator(api, name="OP TO2", badge="B-OP-TO2")
        make_certification(
            api, operator_id=operator["id"], workmanship_class="IPC_CLASS_2",
            issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        )
        # New window starts exactly at the existing window's expires_at: touching
        # endpoints count as overlap under closed-interval semantics.
        resp = api.create_operator_certification(
            {
                "operator_id": operator["id"],
                "workmanship_class": "IPC_CLASS_2",
                "issued_at": "2027-01-01T00:00:00Z",
                "expires_at": "2028-01-01T00:00:00Z",
            },
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_OVERLAP)

    def test_cert_starting_one_second_after_existing_window_accepted(self, api):
        """PRD §3.3: "Overlap uses closed-interval semantics — the new window overlaps an existing one when the new `issued_at` is on or before the existing `expires_at` and the existing `issued_at` is on or before the new `expires_at` — so windows that merely touch at an endpoint are rejected, and the rejection is `ERR_CERT_WINDOW_OVERLAP`."
        PRD §3.3: "The status is `REVOKED` when `revoked_at` is set; otherwise `EXPIRED` once the logical clock reaches or passes `expires_at` (holding an `ACTIVE` certification strictly requires the clock to read earlier than `expires_at`); otherwise `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/certification_closed_interval_touch_rejected
        """
        operator = make_operator(api, name="OP TO2B", badge="B-OP-TO2B")
        make_certification(
            api, operator_id=operator["id"], workmanship_class="IPC_CLASS_2",
            issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        )
        # One second after the existing expires_at: strictly disjoint.
        resp = api.create_operator_certification(
            {
                "operator_id": operator["id"],
                "workmanship_class": "IPC_CLASS_2",
                "issued_at": "2027-01-01T00:00:01Z",
                "expires_at": "2028-01-01T00:00:00Z",
            },
            QM,
        )
        data = validate_success(resp, 201)
        assert_operator_certification(data)
        assert data["status"] == "ACTIVE", (
            f"a disjoint future window against the logical clock default is ACTIVE: {data}"
        )


class TestCertificationIssuanceTemporalGuards:
    def test_cert_window_format_and_past_expiry_errors(self, api):
        """PRD §2.6: "and field constraints hold (`qty_per_harness` at least 1, `qty_ordered` at least 1, `qty_received` at least 1, `planned_end_at` strictly after `planned_start_at`, `expires_at` strictly after `issued_at`, `wire_gauge_awg` an integer between 12 and 26 inclusive, cost-per-piece fields at least 0, cut and strip lengths strictly greater than 0, `opens_count` at least 0). Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "Second, `expires_at` must lie strictly in the future of the logical clock at issuance; an already-expired certification cannot be issued and is rejected with `ERR_CERT_EXPIRY_NOT_FUTURE`."
        PRD §2.5: "At server startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/validations/c_cert_window_format_errors
        """
        operator = make_operator(api, name="OP V9", badge="B-OP-V9")
        # Malformed window: expires_at is not strictly after issued_at.
        resp = api.create_operator_certification(
            {
                "operator_id": operator["id"],
                "workmanship_class": "IPC_CLASS_2",
                "issued_at": "2027-01-01T00:00:00Z",
                "expires_at": "2026-06-01T00:00:00Z",
            },
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Well-formed but already expired against the clock default (2026-08-01).
        resp = api.create_operator_certification(
            {
                "operator_id": operator["id"],
                "workmanship_class": "IPC_CLASS_2",
                "issued_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-07-01T00:00:00Z",
            },
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_CERT_EXPIRY_NOT_FUTURE)


class TestCertificationRevokeAndExpiry:
    def test_cert_revoke_blocks_testing_then_reissue_restores(self, api):
        """PRD §3.3: "The `QualityManager` may revoke a certification while its `revoked_at` is still null; revocation stamps `revoked_at` from the logical clock and increments `version`, after which the computed status reads `REVOKED`."
        PRD §2.9: "A missing, expired, or revoked certification rejects the recording with `ERR_OPERATOR_NOT_CERTIFIED` (HTTP 409)."
        PRD §3.3: "First, the new window must not overlap any non-`REVOKED` certification already held by the same operator for the same class."

        Design: Corner/state_machines/c_cert_revoke_then_reissue_allows_overlap
        """
        ctx = setup_order_in_build(api, tag="S11", qty_ordered=1, units=1)
        inspector = ctx["line"]["inspector"]
        cert = ctx["line"]["cert"]
        unit = ctx["units"][0]

        revoke = validate_success(
            api.revoke_operator_certification(cert["id"], QM), 200
        )
        assert revoke["status"] == "REVOKED", f"computed status reads REVOKED: {revoke}"

        blocked = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_OPERATOR_NOT_CERTIFIED)

        # The REVOKED cert no longer counts for the overlap guard: the identical
        # window can be re-issued.
        reissued = validate_success(
            api.create_operator_certification(
                {
                    "operator_id": inspector["id"],
                    "workmanship_class": "IPC_CLASS_2",
                    "issued_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2027-01-01T00:00:00Z",
                },
                QM,
            ),
            201,
        )
        assert reissued["status"] == "ACTIVE", (
            f"overlap with a REVOKED cert is allowed; new cert is ACTIVE: {reissued}"
        )
        record = record_continuity(api, unit["id"], inspector["id"], opens_count=0)
        assert record["result"] == "PASS", f"testing resumes after re-issuance: {record}"

    def test_cert_active_one_second_before_expiry(self, api):
        """PRD §3.3: "The status is `REVOKED` when `revoked_at` is set; otherwise `EXPIRED` once the logical clock reaches or passes `expires_at` (holding an `ACTIVE` certification strictly requires the clock to read earlier than `expires_at`); otherwise `ACTIVE`."
        PRD §2.5: "A `QualityManager` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`; the server never falls back to wall-clock time at any point."

        Design: Difficulty/boundary_precision_check/certification_expires_at_exact_instant
        """
        ctx = setup_order_in_build(
            api, tag="BP2", qty_ordered=1, units=1,
            line_kwargs={"cert_expires_at": "2026-09-01T00:00:00Z"},
        )
        inspector = ctx["line"]["inspector"]
        unit = ctx["units"][0]
        # One second before expiry the certification is still ACTIVE.
        advance_clock(api, "2026-08-31T23:59:59Z")
        record = record_continuity(api, unit["id"], inspector["id"], opens_count=0)
        assert record["result"] == "PASS", (
            f"at now < expires_at the cert gates nothing; the record passes: {record}"
        )
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["continuity_pass"] is True

    def test_cert_expired_at_exact_expiry_instant(self, api):
        """PRD §3.3: "The status is `REVOKED` when `revoked_at` is set; otherwise `EXPIRED` once the logical clock reaches or passes `expires_at` (holding an `ACTIVE` certification strictly requires the clock to read earlier than `expires_at`); otherwise `ACTIVE`."
        PRD §2.9: "A missing, expired, or revoked certification rejects the recording with `ERR_OPERATOR_NOT_CERTIFIED` (HTTP 409)."
        PRD §2.5: "A `QualityManager` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`; the server never falls back to wall-clock time at any point."

        Design: Difficulty/boundary_precision_check/certification_expires_at_exact_instant
        """
        ctx = setup_order_in_build(
            api, tag="BP2X", qty_ordered=1, units=1,
            line_kwargs={"cert_expires_at": "2026-09-01T00:00:00Z"},
        )
        inspector = ctx["line"]["inspector"]
        unit = ctx["units"][0]
        # At now == expires_at exactly, the certification is EXPIRED (strict <).
        advance_clock(api, "2026-09-01T00:00:00Z")
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "HIPOT",
                "hipot_voltage_v": 1000.0,
                "dwell_seconds": 2.0,
                "measured_leakage_ua": 5.0,
                "leakage_limit_ua": 10.0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_CERTIFIED)
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["status"] == "BUILT", f"rejected recording changes nothing: {unit_after}"
        assert unit_after["hipot_pass"] is False, f"no flag is set by a rejected record: {unit_after}"
