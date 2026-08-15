"""Validation priority pairs: when two rules could reject the same request,
the earlier rule in the PRD §2.9 order produces the response."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    TEST_USERS, create_booking_payload,
    make_researcher_headers, make_external_client_headers,
    setup_canonical_stack, create_user, enroll_and_certify,
    create_booking_request, create_approved_booking,
    get_booking, get_grant, list_all_bookings,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestStateBeatsFiscal:
    def _setup(self, api):
        """b1 REQUESTED then cancelled; the grant is amended down to 1 cent of
        total budget via its OCC-guarded PUT."""
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        validate_success(
            api.cancel_booking(
                b1["id"], make_researcher_headers(stack["u1"]["id"])
            ),
            200,
        )
        validate_success(
            api.amend_grant(
                stack["g1"]["id"],
                {"expected_grant_version": stack["g1"]["version"],
                 "budget_total_cents": 1},
                FINANCE,
            ),
            200,
        )
        return stack, b1

    def test_state_error_surfaces_not_fiscal(self, api):
        """PRD §2.9: "When multiple validation rules could reject the same
        request, the server evaluates them in a fixed priority order, and the
        earliest failing rule produces the response." with "6. State-machine
        legality (`ERR_INVALID_STATE`)" ordered before "35. Fiscal capacity
        (`ERR_GRANT_BUDGET_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_approve
        """
        stack, b1 = self._setup(api)
        res = api.approve_booking(b1["id"], STAFF)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_failed_approve_has_no_side_effects(self, api):
        """PRD §2.9: "State-machine legality (`ERR_INVALID_STATE`): the target
        resource's current state must permit the requested transition".
        PRD §3.6: "For an internal booking, `encumbered_cents` is set equal to
        `estimated_charge_cents` and the grant's `budget_encumbered_cents`
        increases by that amount" — a rejected approval pins and encumbers
        nothing.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_approve
        """
        stack, b1 = self._setup(api)
        validate_error(api.approve_booking(b1["id"], STAFF), "ERR_INVALID_STATE")
        assert get_booking(b1["id"])["status"] == "CANCELLED"
        assert get_grant(stack["g1"]["id"])["budget_encumbered_cents"] == 0


class TestSafetyBeatsTemporal:
    def _setup(self, api):
        """b1 APPROVED occupies [09:00, 11:00) with the 30-minute buffer;
        u2 is an EXTERNAL client with no training record on the instrument."""
        stack = setup_canonical_stack()
        u2 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        b1 = create_approved_booking(stack)
        return stack, u2, b1

    def test_training_error_surfaces_not_overlap(self, api):
        """PRD §2.9: "When multiple validation rules could reject the same
        request, the server evaluates them in a fixed priority order, and the
        earliest failing rule produces the response." with "12. Training
        requirement (`ERR_TRAINING_REQUIRED`)" ordered before "16. Booking
        overlap (`ERR_BOOKING_OVERLAP`)". PRD §3.3: "At booking creation and
        again at booking approval, when the instrument requires training the
        user must hold a record whose effective status is `CERTIFIED`; absence
        of one is rejected with `ERR_TRAINING_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_booking_create
        """
        stack, u2, b1 = self._setup(api)
        res = api.create_booking(
            create_booking_payload(
                u2["id"], stack["i1"]["id"],
                start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T11:00:00Z",
            ),
            make_external_client_headers(u2["id"]),
        )
        # The window collides with b1's buffered interval AND u2 has no
        # training record; the training rule (12) reports first.
        validate_error(res, "ERR_TRAINING_REQUIRED", expected_status=422)

    def test_rejected_create_persists_no_booking(self, api):
        """PRD §3.3: "absence of one is rejected with
        `ERR_TRAINING_REQUIRED`" — a rejected creation persists no booking.
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_booking_create
        """
        stack, u2, b1 = self._setup(api)
        validate_error(
            api.create_booking(
                create_booking_payload(
                    u2["id"], stack["i1"]["id"],
                    start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T11:00:00Z",
                ),
                make_external_client_headers(u2["id"]),
            ),
            "ERR_TRAINING_REQUIRED",
        )
        bookings = [
            b for b in list_all_bookings()
            if b.get("instrument_id") == stack["i1"]["id"]
        ]
        assert [b["id"] for b in bookings] == [b1["id"]], (
            "only the pre-existing booking exists for the instrument"
        )


class TestAuthorizationBeatsExistence:
    def test_forbidden_role_never_reaches_id_resolution(self, api):
        """PRD §2.9: "When multiple validation rules could reject the same
        request, the server evaluates them in a fixed priority order, and the
        earliest failing rule produces the response." with "2. Authorization
        (`ERR_FORBIDDEN`)" ordered before "4. Existence (`ERR_NOT_FOUND`)".
        PRD §4: POST /recharge-batches/{id}/finalize is authorized for
        FinanceOfficer.

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_existence_on_batch_finalize
        """
        u1 = create_user(is_pi=True)
        res = api.finalize_recharge_batch(
            NON_EXISTENT_UUID, make_researcher_headers(u1["id"])
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_authorized_role_gets_not_found_for_bogus_id(self, api):
        """PRD §2.7: "Path identifiers are resolved first, in path order; the
        first identifier that does not resolve to an existing resource is
        rejected with `ERR_NOT_FOUND` (HTTP 404)." — for an authorized caller
        the same bogus id resolves to ERR_NOT_FOUND, confirming the
        authorization gate (not id resolution) produced the sibling outcome.

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_existence_on_batch_finalize
        """
        create_user(is_pi=True)
        res = api.finalize_recharge_batch(NON_EXISTENT_UUID, FINANCE)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)
