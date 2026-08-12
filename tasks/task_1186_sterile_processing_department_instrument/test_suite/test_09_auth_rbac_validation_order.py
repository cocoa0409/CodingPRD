"""The screening gauntlet: header presence, role authorization, path
existence, and the priority ordering between validation categories; plus the
role-exclusive write surface.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_supervisor_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]
AUDIT = TEST_USERS["quality_auditor_headers"]


def test_missing_auth_headers_returns_400(api):
    """PRD §2.6: "Header presence. `X-User-ID` and `X-User-Role` are present
    and the role is declared — otherwise
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    resp = api.create_tray(
        f.create_tray_payload(NON_EXISTENT_UUID, label="X"), {}
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_gate_beats_existence_gate(api):
    """PRD §2.6: "Role authorization. The caller's role is listed for the
    endpoint (`Any` admits every declared role) — otherwise
    `ERR_FORBIDDEN_ROLE` (403)." precedes "Path existence." — "When several
    checks could fail on the same request, the earliest one in this order
    determines the rejection".

    Design: Corner/validations/role_gate_beats_existence_gate
    """
    resp = api.release_load(NON_EXISTENT_UUID, SCHED)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_existence_gate_beats_state_gate(api):
    """PRD §2.6: "Path existence. Resource identifiers in the path are
    validated left to right — the leftmost missing id wins with
    `ERR_NOT_FOUND` (404)." precedes "State-machine preconditions." — "When
    several checks could fail on the same request, the earliest one in this
    order determines the rejection".

    Design: Corner/validations/existence_gate_beats_state_gate
    """
    tech = fx.create_technician(api)
    resp = api.start_decontamination(
        NON_EXISTENT_UUID, make_technician_headers(tech["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_scheduler_cannot_release_load(api):
    """PRD §4: the release row authorizes only `SpdSupervisor`; PRD §2.1: "a
    caller whose role is not listed for the endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_release_load
    """
    tech = fx.create_technician(api)
    sg = fx.create_sterilizer(api)
    load = fx.create_load(api, sg["id"], tech["id"])
    resp = api.release_load(load["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_technician_cannot_create_case(api):
    """PRD §4: the case-scheduling row authorizes only `OrScheduler`; PRD
    §2.1: "a caller whose role is not listed for the endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/technician_cannot_create_case
    """
    tech = fx.create_technician(api)
    resp = api.create_or_case(
        f.create_or_case_payload(case_number="C-Z", surgeon="Dr Z"),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_auditor_cannot_operate_load_start(api):
    """PRD §4: the load-start row authorizes only `SpdTechnician`; PRD §2.1:
    "a caller whose role is not listed for the endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_operate_load_start
    """
    tech = fx.create_technician(api)
    sg = fx.create_sterilizer(api)
    load = fx.create_load(api, sg["id"], tech["id"])
    resp = api.start_load(load["id"], AUDIT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_facility_admin_cannot_record_bi_result(api):
    """PRD §4: the record-result row authorizes only `QualityAuditor`; PRD
    §2.1: "a caller whose role is not listed for the endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/facility_admin_cannot_record_bi_result
    """
    resp = api.record_bi_result(NON_EXISTENT_UUID, {"result": "NEGATIVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_shared_read_allowed_for_business_roles(api):
    """PRD §2.1: "the conventional marker `Any` used in this document to mean
    that every declared role may perform the operation (in practice, all read
    operations)".

    Design: Corner/rbac/shared_read_allowed_for_business_roles
    """
    resp = api.list_trays(SCHED)
    rows, meta = validate_paginated(resp)
    assert rows == [] and meta["total_count"] == 0
    assert resp.json()["response_type"] == "array"


class TestReleaseStateGateBeatsSegregation:
    """One call violating both the state gate and the segregation gate
    resolves to the state error (two tests, one design instance)."""

    def test_state_error_wins_over_segregation(self, api):
        """PRD §2.6: "When several checks could fail on the same request, the
        earliest one in this order determines the rejection" — step 6
        "State-machine preconditions" precede step 7 "Patient-safety gates",
        and PRD §3.5: "The load must be `COMPLETED` (else
        `ERR_LOAD_NOT_RELEASABLE`)".

        Design: Difficulty/priority_pair_validation_conflict/release_state_gate_beats_segregation
        """
        s = fx.setup_release_conflict_scenario(api)
        # Caller carries the load operator's own Technician id under the
        # supervisor role: the segregation gate is also violated.
        resp = api.release_load(s.ls["id"], make_supervisor_headers(s.tech_a["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_RELEASABLE)

    def test_rejected_release_leaves_load_running(self, api):
        """PRD §3.5: "The load must be `COMPLETED` (else
        `ERR_LOAD_NOT_RELEASABLE`)"; PRD §2.6: "State-machine preconditions"
        are screened before "Patient-safety gates" ("the segregation-of-duties
        check (`ERR_RELEASE_OPERATOR_SEGREGATION`, 403)").

        Design: Difficulty/priority_pair_validation_conflict/release_state_gate_beats_segregation
        """
        s = fx.setup_release_conflict_scenario(api)
        resp = api.release_load(s.ls["id"], make_supervisor_headers(s.tech_a["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_RELEASABLE)
        load = validate_success(api.get_sterilization_load(s.ls["id"], ADMIN))
        assert load["status"] == "RUNNING", "the rejection had no side effects"


class TestReservationSafetyExpiryBeatsTemporalOverlap:
    """One reservation violating both the sterility safety gate and the
    turnover temporal gate resolves to the safety error (two tests, one
    design instance)."""

    def test_sterility_error_wins_over_temporal_conflict(self, api):
        """PRD §2.6: "On reservation creation, the sterility-expiry gate
        (`ERR_STERILITY_EXPIRED_FOR_CASE`) precedes every temporal gate." PRD
        §3.6: "The tray must be `STERILE` as stored (post-sweep, else
        `ERR_TRAY_NOT_STERILE`) with a `sterility_expires_at` strictly later
        than the case's `scheduled_start_at`".

        Design: Difficulty/priority_pair_validation_conflict/reservation_safety_expiry_beats_temporal_overlap
        """
        s = fx.setup_reservation_priority_scenario(api)
        # Case CB starts 2026-06-08T10:30 — after the tray's 10:00 expiry —
        # AND its expanded window sits 30 minutes after case CA's (both gates
        # violated on the same call).
        resp = api.create_reservation(
            s.cb["id"],
            f.create_reservation_payload(s.tx["id"], s.cb["version"]),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_STERILITY_EXPIRED_FOR_CASE)

    def test_rejected_reservation_persists_nothing(self, api):
        """PRD §2.6: "On reservation creation, the sterility-expiry gate
        (`ERR_STERILITY_EXPIRED_FOR_CASE`) precedes every temporal gate";
        rejections at screening step 7 persist no reservation.

        Design: Difficulty/priority_pair_validation_conflict/reservation_safety_expiry_beats_temporal_overlap
        """
        s = fx.setup_reservation_priority_scenario(api)
        resp = api.create_reservation(
            s.cb["id"],
            f.create_reservation_payload(s.tx["id"], s.cb["version"]),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_STERILITY_EXPIRED_FOR_CASE)
        rows, meta = validate_paginated(
            api.list_tray_reservations(ADMIN, params={"case_id": s.cb["id"]})
        )
        assert meta["total_count"] == 0, f"no reservation persists: {rows}"
