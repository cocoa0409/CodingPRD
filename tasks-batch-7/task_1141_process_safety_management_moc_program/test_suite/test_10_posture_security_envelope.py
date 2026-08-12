"""Posture bands, validation priority pairs, auth/RBAC, clock, error envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    classify,
    classify_payload,
    drive_moc_to_implemented,
    drive_unit_to_frozen_via_overdue_and_study,
    get_moc,
    get_pha_study,
    get_unit,
    make_requester_headers,
    new_draft_moc,
    new_incident,
    new_manual_item,
    new_personnel,
    new_unit,
    set_clock,
    setup_unit_with_study,
    validate_error,
    validate_success,
    withdraw,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestPostureBands:
    def test_posture_restricted_band_lower_edge_exact_40(self, api):
        """PRD §2.10: "fifteen points per overdue open action item" plus "ten per
        open high-severity incident", and "an index below 40 is `NORMAL`, an
        index of at least 40 but below 70 is `RESTRICTED`, and an index of 70 or
        higher is `FROZEN` — so exactly 40 is `RESTRICTED` and exactly 70 is
        `FROZEN`." Two overdue P1 items give 30 (NORMAL); one open HIGH
        investigation adds 10 and lands exactly on 40.

        Design: Corner/calculations/posture_restricted_band_lower_edge_exact_40
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        inv = new_personnel("Inv", "E-INV")
        new_manual_item(unit["id"], req["id"], priority="P1", due_in_days=1, title="a1")
        new_manual_item(unit["id"], req["id"], priority="P1", due_in_days=1, title="a2")
        set_clock("2026-05-03T00:00:00Z")

        before = get_unit(unit["id"])
        assert before["process_safety_index"] == 30
        assert before["psm_posture"] == "NORMAL"

        new_incident(unit["id"], inv["id"], severity_class="HIGH", occurred_at="2026-04-20")
        after = get_unit(unit["id"])
        assert after["process_safety_index"] == 40
        assert after["psm_posture"] == "RESTRICTED", "exactly 40 is RESTRICTED (inclusive-low band)"

    def test_process_safety_index_capped_at_100(self, api):
        """PRD §2.10: the index is "a composite score capped between 0 and 100"
        composed of "fifteen points per overdue open action item" with "the total
        capped at one hundred" — seven overdue P1 items sum to 105 raw but store
        as exactly 100, and "an index of 70 or higher is `FROZEN`".

        Design: Corner/calculations/process_safety_index_capped_at_100
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        for i in range(7):
            new_manual_item(unit["id"], req["id"], priority="P1", due_in_days=1, title=f"a{i + 1}")
        set_clock("2026-05-03T00:00:00Z")

        after = get_unit(unit["id"])
        assert after["overdue_action_count"] == 7
        assert after["process_safety_index"] == 100, (
            f"raw 105 must be capped at 100, got {after['process_safety_index']}"
        )
        assert after["psm_posture"] == "FROZEN"


class TestSubmitPriorityPair:
    def _frozen_unit_with_withdrawn_moc(self):
        """Unit driven to index 70 (FROZEN) after the MOC was withdrawn while
        NORMAL: 3 overdue P1 items (45) + study OVERDUE (25)."""
        unit, study = setup_unit_with_study(validated_at="2026-01-15")
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        classify(moc["id"], change_class="PERMANENT", severity=1, likelihood=1)
        withdraw(moc["id"], req["id"])
        frozen = drive_unit_to_frozen_via_overdue_and_study(unit["id"], req["id"],
                                                            clock_iso="2027-01-11")
        return unit, req, moc, frozen

    def test_frozen_unit_reached_before_conflicting_submit(self, api):
        """PRD §2.10: "an index of 70 or higher is `FROZEN`" — three overdue P1
        items (3 × 15) plus an OVERDUE study (25) land the unit on exactly 70, so
        both the state rule and the posture gate are live for the submit attempt.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_safety_posture
        """
        unit, req, moc, frozen = self._frozen_unit_with_withdrawn_moc()
        assert frozen["process_safety_index"] == 70
        assert frozen["psm_posture"] == "FROZEN"
        assert get_moc(moc["id"])["status"] == "WITHDRAWN"

    def test_submit_state_error_beats_posture_error(self, api):
        """PRD §2.9: "Every request is validated in a fixed pipeline order, and
        the first failing check determines the error returned; later checks are
        never consulted once an earlier one has fired."
        PRD §2.9 step 5: "The target entity is in a valid from-state for the
        requested transition — otherwise the entity's state error (for example
        `ERR_MOC_INVALID_STATE`" — checked before step 6's business-safety
        sub-order, which includes "then unit posture gates
        (`ERR_UNIT_POSTURE_FROZEN`, `ERR_UNIT_POSTURE_RESTRICTED`)". Submitting a
        WITHDRAWN MOC on a FROZEN unit therefore yields ERR_MOC_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_safety_posture
        """
        unit, req, moc, frozen = self._frozen_unit_with_withdrawn_moc()
        resp = api.submit_moc(moc["id"], make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_MOC_INVALID_STATE.value)
        assert get_moc(moc["id"])["status"] == "WITHDRAWN"


class TestAuthorizePriorityPair:
    def _frozen_unit_with_unimplemented_pssr_gate(self):
        """PERMANENT MOC at IMPLEMENTED_PSSR_PENDING with NO PSSR, on a unit then
        driven FROZEN (index 70)."""
        unit, study = setup_unit_with_study(validated_at="2026-01-15")
        req = new_personnel("Req", "E-REQ")
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_implemented(unit["id"], req["id"], rev["id"], app["id"],
                                       change_class="PERMANENT", severity=2, likelihood=2)
        frozen = drive_unit_to_frozen_via_overdue_and_study(unit["id"], req["id"],
                                                            clock_iso="2027-01-11")
        return unit, moc, frozen

    def test_authorize_setup_frozen_without_approved_pssr(self, api):
        """PRD §3.5: "Startup authorization itself is a `PsmManager` act on a MOC
        in `IMPLEMENTED_PSSR_PENDING`" and "when `requires_pssr` holds, a linked
        PSSR in `APPROVED` status must exist (`ERR_PSSR_NOT_APPROVED`)" — both the
        posture gate (unit FROZEN, PRD §2.10: "an index of 70 or higher is
        `FROZEN`") and the PSSR gate are live for this MOC.

        Design: Difficulty/priority_pair_validation_conflict/authorize_safety_beats_referential_pssr
        """
        unit, moc, frozen = self._frozen_unit_with_unimplemented_pssr_gate()
        assert frozen["psm_posture"] == "FROZEN"
        assert frozen["process_safety_index"] == 70
        after = get_moc(moc["id"])
        assert after["status"] == "IMPLEMENTED_PSSR_PENDING"
        assert after["requires_pssr"] is True

    def test_authorize_safety_beats_referential_pssr(self, api):
        """PRD §2.9: "the first failing check determines the error returned" and
        the pipeline puts step 6's business-safety sub-order including "then unit
        posture gates (`ERR_UNIT_POSTURE_FROZEN`, `ERR_UNIT_POSTURE_RESTRICTED`)"
        before step 9's "**Cross-entity completion gates.** Final gate checks that
        depend on the state of other entities: `ERR_PSSR_NOT_APPROVED`". On a
        FROZEN unit with no APPROVED PSSR, authorize-startup yields
        ERR_UNIT_POSTURE_FROZEN.

        Design: Difficulty/priority_pair_validation_conflict/authorize_safety_beats_referential_pssr
        """
        unit, moc, frozen = self._frozen_unit_with_unimplemented_pssr_gate()
        resp = api.authorize_startup(moc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNIT_POSTURE_FROZEN.value)
        assert get_moc(moc["id"])["status"] == "IMPLEMENTED_PSSR_PENDING"


class TestAuthAndRbac:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_units({})  # no X-User-ID / X-User-Role headers at all
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
        assert resp.status_code == 400

    def test_training_coordinator_cannot_classify(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /psm/moc-requests/{id}/classify is authorized for PsmManager
        only.

        Design: Corner/rbac/training_coordinator_cannot_classify
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        resp = api.classify_moc(moc["id"], classify_payload(change_class="PERMANENT",
                                                            screening_severity=1,
                                                            screening_likelihood=1), COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        assert resp.status_code == 403

    def test_submit_by_other_requester_returns_not_owner(self, api):
        """PRD §3.3: "Submitting a `CLASSIFIED` MOC is the requester's own action;
        any other user is turned away with `ERR_NOT_RESOURCE_OWNER`" — a second
        Requester with a valid role but the wrong identity cannot submit it.

        Design: Corner/validations/submit_by_other_requester_returns_not_owner
        """
        unit, _ = setup_unit_with_study()
        r1 = new_personnel("R1", "E-R1")
        r2 = new_personnel("R2", "E-R2")
        moc = new_draft_moc(unit["id"], r1["id"])
        classify(moc["id"], change_class="PERMANENT", severity=2, likelihood=2)

        resp = api.submit_moc(moc["id"], make_requester_headers(r2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
        assert resp.status_code == 403
        assert get_moc(moc["id"])["status"] == "CLASSIFIED"


class TestTemporalGates:
    def test_submit_with_overdue_pha_returns_pha_not_current(self, api):
        """PRD §3.3: "the unit must hold a PHA study in `CURRENT` or `DUE_SOON`
        status — a unit with no study, or a study that is `OVERDUE`,
        `REVALIDATION_REQUIRED`, or `IN_REVALIDATION`, blocks submission with
        `ERR_PHA_NOT_CURRENT`."

        Design: Corner/validations/submit_with_overdue_pha_returns_pha_not_current
        """
        unit, study = setup_unit_with_study(validated_at="2026-01-15")
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        classify(moc["id"], change_class="PERMANENT", severity=2, likelihood=2)
        set_clock("2027-01-11T00:00:00Z")  # past effective due 2027-01-10
        assert get_pha_study(study["id"])["status"] == "OVERDUE"

        resp = api.submit_moc(moc["id"], make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_PHA_NOT_CURRENT.value)
        assert get_moc(moc["id"])["status"] == "CLASSIFIED"

    def test_clock_regression_returns_409(self, api):
        """PRD §2.4: "the supplied instant must be at or after the current logical
        time, and an attempt to move the clock backward is rejected with
        `ERR_CLOCK_REGRESSION`."

        Design: Corner/validations/clock_regression_returns_409
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.set_clock({"to_iso8601": "2026-05-15T00:00:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION.value)
        # The clock stayed at 2026-06-01: a later attempt at 2026-05-20 still regresses.
        resp2 = api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN)
        validate_error(resp2, ApiErrorId.ERR_CLOCK_REGRESSION.value)
        ok = validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN), 200)
        assert ok["current_utc"] == "2026-06-01T00:00:00Z"


class TestNotFoundAndEnvelope:
    def test_moc_get_nonexistent_returns_not_found(self, api):
        """PRD §2.8: "The first identifier that does not correspond to an existing
        resource produces that resource type's not-found error" — for a MOC id
        that is `ERR_MOC_NOT_FOUND` (PRD §5 maps it to 404).

        Design: Corner/entities/moc_get_nonexistent_returns_not_found
        """
        resp = api.get_moc(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOC_NOT_FOUND.value)
        assert resp.status_code == 404

    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_moc(NON_EXISTENT_UUID, MANAGER)
        error = validate_error(resp, ApiErrorId.ERR_MOC_NOT_FOUND.value)
        assert error["message"].strip(), "error message must be non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
