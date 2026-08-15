"""Transition slots (window buffer, open-default gate, invalid transitions),
response envelope shape, OCC stale-version rules, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_active_lease,
    create_default_case,
    create_draft_lease,
    create_lessee,
    create_return_case_in_negotiation,
    make_lessee_rep_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestSlotWindowBuffer:
    def test_buffer_conflict_and_boundary(self, api):
        """PRD §3.8: "Two guards run at creation, in pipeline order: the
        buffer rule rejects the slot with `ERR_SLOT_WINDOW_CONFLICT` unless
        its window clears every other `TENTATIVE` or `CONFIRMED` window on
        the same aircraft by more than two whole days on one side or the
        other — adjacency within the two-day buffer counts as a conflict"

        Design: Corner/validations/slot_window_buffer_conflict
        """
        lease, aircraft, _lessee = create_active_lease()
        validate_success(
            api.create_transition_slot(
                aircraft["id"],
                {"window_start": "2026-09-10", "window_end": "2026-09-20"},
                ADMIN),
            expected_status=201)

        # Starts only 2 whole days after the 2026-09-20 end: inside buffer.
        resp = api.create_transition_slot(
            aircraft["id"],
            {"window_start": "2026-09-22", "window_end": "2026-09-30"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_CONFLICT, expected_status=409)

        # Starts exactly 3 whole days after the end: buffer satisfied.
        slot2 = validate_success(
            api.create_transition_slot(
                aircraft["id"],
                {"window_start": "2026-09-23", "window_end": "2026-09-30"},
                ADMIN),
            expected_status=201)
        assert slot2["status"] == "TENTATIVE"


class TestSlotDefaultGate:
    def test_slot_creation_blocked_by_open_default_case(self, api):
        """PRD §3.8: "and the default rule rejects it with
        `ERR_DEFAULT_CASE_OPEN` if the lease currently holding the aircraft
        (one in `ACTIVE`, `RETURN_INITIATED`, or `DEFAULTED`) has a default
        case in `DECLARED` or `REPOSSESSION_AUTHORIZED`."

        Design: Corner/validations/default_case_open_blocks_slot_creation
        """
        lease, aircraft, _lessee = create_active_lease()
        create_default_case(lease["id"], declared_by="cred_1",
                            reason="rent arrears", cure_period_days=30)
        resp = api.create_transition_slot(
            aircraft["id"],
            {"window_start": "2026-10-01", "window_end": "2026-10-10"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEFAULT_CASE_OPEN, expected_status=409)


class TestSlotTransitions:
    def test_slot_advance_skipping_confirmed_rejected(self, api):
        """PRD §3.8: "From `TENTATIVE`, a `LessorAdmin` advances the slot to
        `CONFIRMED` once the aircraft is physically back — that is, when the
        aircraft's `status` is `IN_TRANSITION` or `REPOSSESSED` — or the
        settle cascade of §3.6 may confirm a covering slot automatically.
        Advancing a `CONFIRMED` slot to `COMPLETED` marks the transition
        done"
        PRD §2.8 (5): "State preconditions — the target resource is in a
        from-state the transition allows, including terminal-state lockdown
        and the one-open-child rules (else `ERR_INVALID_STATE`, HTTP 409; ...)"

        Design: Corner/state_machines/slot_advance_skipping_confirmed_returns_invalid_state
        """
        lease, aircraft, _lessee = create_active_lease()
        slot = validate_success(
            api.create_transition_slot(
                aircraft["id"],
                {"window_start": "2026-09-10", "window_end": "2026-09-20"},
                ADMIN),
            expected_status=201)
        resp = api.advance_transition_slot(slot["id"], {"to": "COMPLETED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestResponseEnvelope:
    def test_envelope_shape_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        lessee = create_lessee(legal_name="Env Air")

        ok = api.get_lessee(lessee["id"], ADMIN)
        body = ok.json()
        assert body.get("response_type") == "object"
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
        assert isinstance(body.get("data"), dict)

        err = api.get_lessee(NON_EXISTENT_UUID, ADMIN)
        err_body = err.json()
        assert err_body.get("response_type") == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"].get("message"), str) and err_body["data"]["message"]
        validate_error(err, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestOccLeaseAmend:
    def test_lease_amend_stale_version(self, api):
        """PRD §2.7: "Amending a lease requires the request to carry
        `expected_lease_version`, equal to the lease's `version` the client
        last observed. If the lease's current `version` has advanced —
        whether by a prior amendment or by any cascade that bumped it, such
        as activation or a novation reassignment — the write is refused with
        `ERR_STALE_VERSION` (HTTP 412) rather than silently layered over a
        state the client never saw."

        Design: Corner/cross_cutting_layers/occ_lease_amend_stale_version
        """
        lease, _aircraft, _lessee = create_draft_lease()
        observed_version = lease["version"]

        amended = validate_success(
            api.amend_lease(
                lease["id"],
                {"expected_lease_version": observed_version, "monthly_rent_cents": 1100000},
                ADMIN))
        assert amended["version"] == observed_version + 1

        # The same, now-stale version is refused.
        resp = api.amend_lease(
            lease["id"],
            {"expected_lease_version": observed_version, "monthly_rent_cents": 1200000},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["monthly_rent_cents"] == 1100000, (
            "the rejected amendment must not be applied")

    def test_lease_amend_echo_is_immediately_consistent(self, api):
        """PRD §3.2: "While a lease is in `DRAFT` or `ACTIVE`, a
        `LessorAdmin` may amend its terms. ... A successful amendment
        increments the lease's `version` by one."
        PRD §2.9: "Every event that touches one of the three source fields
        recomputes the balance in the same atomic mutation, so the invariant
        holds after every API call."

        Design: Corner/consistency_model/immediate_consistency_patch_echo
        """
        lease, _aircraft, _lessee = create_draft_lease()
        observed_version = lease["version"]
        amended = validate_success(
            api.amend_lease(
                lease["id"],
                {"expected_lease_version": observed_version,
                 "monthly_rent_cents": 1250000, "monthly_hour_cap": 320},
                ADMIN))
        # The PATCH response itself carries the amended fields — immediate
        # visibility, no re-read needed.
        assert amended["monthly_rent_cents"] == 1250000
        assert amended["monthly_hour_cap"] == 320
        assert amended["version"] == observed_version + 1


class TestOccReturnAgree:
    def test_return_agree_stale_version(self, api):
        """PRD §2.7: "Recording agreement on a return case requires the
        request to carry `expected_return_case_version`, equal to the return
        case's `version` the client last observed. If the case's `version`
        has advanced — for example because a further proposal round or a
        re-inspection loop superseded the standing proposal — the agreement
        is rejected with `ERR_STALE_VERSION` (HTTP 412), since it would
        otherwise bind terms the counterparty never saw."

        Design: Corner/cross_cutting_layers/occ_return_agree_stale_version
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        proposed = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 200000}, ADMIN))
        stale_version = proposed["version"]
        # A LESSEE counter-proposal bumps the version past what the lessor
        # last observed.
        counter = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 150000},
                                make_lessee_rep_headers(lessee["id"])))

        resp = api.agree_return_case(
            rc["id"], {"expected_return_case_version": stale_version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Re-reading and agreeing with the fresh version succeeds; the
        # standing proposal is the LESSEE counter-proposal.
        agreed = validate_success(
            api.agree_return_case(
                rc["id"], {"expected_return_case_version": counter["version"]}, ADMIN))
        assert agreed["status"] == "AGREED"
        assert agreed["agreed_total_cents"] == 150000

    def test_return_agree_requires_current_version_each_round(self, api):
        """PRD §2.7: "Recording agreement on a return case requires the
        request to carry `expected_return_case_version`, equal to the return
        case's `version` the client last observed."
        PRD §3.6: "Agreement captures the standing proposal as
        `agreed_total_cents` — null until this moment, thereafter the final
        compensation figure, which generally differs from the provisional
        estimate for the same items — and moves the case `NEGOTIATION →
        AGREED`."

        Design: Corner/cross_cutting_layers/occ_return_agree_stale_version
        """
        lease, _aircraft, lessee, rc, _insp = create_return_case_in_negotiation(
            non_compliant={"ENGINE": 80000})
        proposed = validate_success(
            api.create_proposal(rc["id"], {"amount_cents": 90000}, ADMIN))
        agreed = validate_success(
            api.agree_return_case(
                rc["id"], {"expected_return_case_version": proposed["version"]},
                make_lessee_rep_headers(lessee["id"])))
        assert agreed["status"] == "AGREED"
        assert agreed["agreed_total_cents"] == 90000
        assert agreed["version"] == proposed["version"] + 1
