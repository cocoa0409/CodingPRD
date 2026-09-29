"""
Rejections that only a second operator can provoke, and the envelope every
rejection has to answer with.

The first group walks the file / decide / compensate chain one adjacent pair at
a time. Each pair is probed twice with a byte-identical payload: once by the
operator identifier already recorded in the previous step, which must be
refused, and once by a fresh identifier, which must succeed. The success arm is
what makes the refusal attributable to the acting identifier rather than to the
payload, the role or the entity's state.

The second group fires one request per HTTP status class against a single
held reservation and inspects the body rather than only the status line: the
error envelope's `meta` carries exactly two fields, its `data` carries exactly
two fields, and no partial entity or pagination block leaks into either.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ERROR_HTTP_STATUS
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    CARE_ISSUER_HEADERS,
    CARE_REVOKER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    GUEST_SERVICES_FILER_ID,
    GUEST_SERVICES_ISSUER_ID,
    make_guest_headers,
    make_kitchen_headers,
)

# The recurring Thursday service the whole file trades on. Thursday is the
# neutral 10000 basis-point day-of-week factor and the STANDARD tier is 10000
# too, so a 12000-cent cover lists at exactly 12000 and a party of two settles
# on round figures: subtotal 24000, service charge 1740, grand total 25740 and
# a 3000 basis-point deposit of 7722.
SEATING_START = "2026-09-10T22:00:00Z"
DEPOSIT_DUE_CENTS = 7722
GRAND_TOTAL_CENTS = 25740
ONE_CENT_SHORT_OF_DEPOSIT = DEPOSIT_DUE_CENTS - 1

# Exactly 48.0 hours before seating_start_utc, which the STANDARD ladder bands
# at 5000 basis points: raw forfeiture 3861 on the 7722-cent deposit basis, a
# 500-cent rebooking fee, so 4361 retained and 3361 refunded.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"
FORFEITED_AFTER_CANCEL = 4361
REFUNDED_AFTER_CANCEL = 3361

# The head-room a refund exception may ask for: amount_paid less refunded.
REQUESTED_CENTS = 4361
APPROVED_CENTS = 1000
SHORTFALL_CENTS = REQUESTED_CENTS - APPROVED_CENTS
CREDIT_EXPIRES_AT = "2027-01-01T00:00:00Z"

# A well-formed UUID that resolves to nothing.
MISSING_RESERVATION_ID = "00000000-0000-4000-8000-0000000000ff"

# "an ISO 8601 UTC timestamp with three fractional digits".
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _assert_error_envelope(response, expected_error_id):
    """Assert the documented error envelope in full, then return its data.

    The envelope is checked field by field rather than only by status code:
    `response_type` reads "error", `meta` carries exactly the two documented
    fields with a `req_`-prefixed identifier and a millisecond timestamp, and
    `data` carries exactly `error_id` and `message` — no entity fields and no
    pagination block.
    """
    expected_status = ERROR_HTTP_STATUS[expected_error_id]
    body = response.json()

    assert body["response_type"] == "error", (
        f"response_type should be 'error' for {expected_error_id}, got "
        f"{body['response_type']!r}"
    )

    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the meta of an error response carries only api_request_id and "
        f"api_request_timestamp, got {sorted(meta.keys())}"
    )
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert _TIMESTAMP_RE.match(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC instant with three "
        f"fractional digits, got {meta['api_request_timestamp']!r}"
    )

    data = body["data"]
    assert set(data.keys()) == {"error_id", "message"}, (
        "the data of an error response carries exactly error_id and message, "
        f"got {sorted(data.keys())}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "message must be a non-empty human-readable explanation"
    )

    # error_id and the HTTP status are cross-checked against the catalogue.
    return validate_error(response, expected_error_id, expected_status)


def _settled_world(api):
    """A cancelled, part-forfeited booking with an exception already on file.

    The exception is filed by the care operator whose identifier is thereafter
    barred from deciding it, and the clock is left at the cancellation instant.
    """
    world = FX.build_world(api, guests=1)
    guest_id = world["guest_id"]
    reservation = FX.settled_cancelled_reservation(
        api, world, guest_id, party_size=2, cancel_at=CANCEL_AT_48H
    )
    exception = FX.file_refund_exception(
        api, reservation["id"], REQUESTED_CENTS, headers=CARE_FILER_HEADERS
    )
    world["guest_headers"] = make_guest_headers(guest_id)
    world["reservation"] = reservation
    world["exception"] = exception
    return world


def _decide(api, exception_id, headers):
    """Adjudicate with one fixed approval payload, varying only the operator."""
    return api.decide_refund_exception(
        exception_id,
        F.decide_payload(
            decision="APPROVED",
            approved_cents=APPROVED_CENTS,
            decision_note_code="PARTIAL_GOODWILL",
        ),
        headers,
    )


def _issue(api, exception_id, headers, issued_cents=SHORTFALL_CENTS):
    """Issue a compensating credit, varying only the operator."""
    return api.create_goodwill_credit(
        F.goodwill_credit_payload(exception_id, issued_cents, CREDIT_EXPIRES_AT),
        headers,
    )


def _revoke(api, credit_id, headers):
    """Claw the remainder back, varying only the operator."""
    return api.revoke_goodwill_credit(
        credit_id, headers, {"reason_code": "POLICY_REVIEW"}
    )


class TestSegregationOfDutiesAcrossTheAdjudicationChain:
    """Three adjacent pairs, three recorded columns, one refusal each."""

    def test_the_filing_operator_may_not_decide_its_own_exception(self, api):
        """The identifier recorded at filing time is barred from adjudicating.

        "The operator deciding a refund exception must have an `X-User-ID`
        different from the `requested_by_user_id` recorded when the exception
        was filed." The refusal leaves the exception exactly as filing left it:
        "A new exception starts in `REQUESTED` with `decided_by_user_id` null,
        `approved_cents` 0, `shortfall_cents` 0 and `decision_note_code` null."

        Design: Corner/errors/segregation_of_duties_blocks_file_decide_issue_and_revoke_reuse
        """
        world = _settled_world(api)
        exception_id = world["exception"]["id"]
        reservation_id = world["reservation"]["id"]

        # The settlement the exception contests, and the operator on record.
        assert world["reservation"]["forfeited_cents"] == FORFEITED_AFTER_CANCEL
        assert world["reservation"]["refunded_cents"] == REFUNDED_AFTER_CANCEL
        assert world["exception"]["requested_by_user_id"] == GUEST_SERVICES_FILER_ID
        rows_before = FX.ledger_rows(api, reservation_id, CARE_FILER_HEADERS)

        refused = _decide(api, exception_id, CARE_FILER_HEADERS)
        _assert_error_envelope(refused, E.ERR_SEGREGATION_OF_DUTIES)

        undecided = validate_success(
            api.get_refund_exception(exception_id, CARE_FILER_HEADERS)
        )
        assert undecided["status"] == "REQUESTED"
        assert undecided["approved_cents"] == 0
        assert undecided["shortfall_cents"] == 0
        assert undecided["decided_by_user_id"] is None
        assert undecided["decision_note_code"] is None
        assert FX.ledger_rows(api, reservation_id, CARE_FILER_HEADERS) == rows_before

        # The identical payload from an untainted operator is accepted, which is
        # what attributes the refusal to the identifier alone.
        decided = validate_success(_decide(api, exception_id, CARE_DECIDER_HEADERS))
        assert decided["status"] == "APPROVED"
        assert decided["approved_cents"] == APPROVED_CENTS
        assert decided["shortfall_cents"] == SHORTFALL_CENTS
        assert decided["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        rows_after = FX.ledger_rows(api, reservation_id, CARE_FILER_HEADERS)
        new_rows = rows_after[len(rows_before):]
        assert sorted(row["kind"] for row in new_rows) == [
            "FORFEITURE_REVERSAL",
            "REFUND",
        ]
        for row in new_rows:
            assert row["amount_cents"] == APPROVED_CENTS
            assert row["memo_code"] == "REFUND_EXCEPTION"
            A.assert_signed_amount(row)

    def test_the_deciding_operator_may_not_issue_the_compensating_credit(self, api):
        """The identifier recorded at decision time is barred from issuing.

        "The operator issuing a goodwill credit against a decided exception must
        have an `X-User-ID` different from the `decided_by_user_id` recorded on
        that exception." A credit that does clear the check "copies `guest_id`
        and `restaurant_id` from the exception's reservation and its service, so
        a credit is scoped to one guest at one restaurant".

        Design: Corner/errors/segregation_of_duties_blocks_file_decide_issue_and_revoke_reuse
        """
        world = _settled_world(api)
        exception_id = world["exception"]["id"]
        decided = FX.decide_refund_exception(
            api,
            exception_id,
            decision="APPROVED",
            approved_cents=APPROVED_CENTS,
            decision_note_code="PARTIAL_GOODWILL",
        )
        assert decided["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID
        assert decided["shortfall_cents"] == SHORTFALL_CENTS

        refused = _issue(api, exception_id, CARE_DECIDER_HEADERS)
        _assert_error_envelope(refused, E.ERR_SEGREGATION_OF_DUTIES)

        assert (
            validate_success(
                api.list_goodwill_credits(
                    ADMIN_HEADERS, {"refund_exception_id": exception_id, "limit": 100}
                )
            )
            == []
        )

        credit = validate_success(_issue(api, exception_id, CARE_ISSUER_HEADERS), 201)
        assert credit["issued_cents"] == SHORTFALL_CENTS
        assert credit["remaining_cents"] == SHORTFALL_CENTS
        assert credit["redeemed_cents"] == 0
        assert credit["revoked_cents"] == 0
        assert credit["status"] == "ISSUED"
        assert credit["issued_by_user_id"] == GUEST_SERVICES_ISSUER_ID
        assert credit["guest_id"] == world["guest_id"]
        assert credit["restaurant_id"] == world["restaurant_id"]
        A.assert_credit_status(credit)

    def test_the_issuing_operator_may_not_revoke_its_own_credit(self, api):
        """The identifier recorded at issue time is barred from clawing back.

        "The operator revoking a goodwill credit must have an `X-User-ID`
        different from the `issued_by_user_id` recorded on that credit."
        Revocation moves no money either way: "It writes **no**
        `PaymentTransaction` row at all: cents the guest has already spent stay
        spent, on the reservations they were spent against."

        Design: Corner/errors/segregation_of_duties_blocks_file_decide_issue_and_revoke_reuse
        """
        world = _settled_world(api)
        reservation_id = world["reservation"]["id"]
        FX.decide_refund_exception(
            api,
            world["exception"]["id"],
            decision="APPROVED",
            approved_cents=APPROVED_CENTS,
            decision_note_code="PARTIAL_GOODWILL",
        )
        credit = FX.issue_goodwill_credit(
            api, world["exception"]["id"], SHORTFALL_CENTS, CREDIT_EXPIRES_AT
        )
        assert credit["issued_by_user_id"] == GUEST_SERVICES_ISSUER_ID
        rows_before = FX.ledger_rows(api, reservation_id, world["guest_headers"])

        refused = _revoke(api, credit["id"], CARE_ISSUER_HEADERS)
        _assert_error_envelope(refused, E.ERR_SEGREGATION_OF_DUTIES)

        intact = FX.read_credit(api, credit["id"], CARE_ISSUER_HEADERS)
        assert intact["status"] == "ISSUED"
        assert intact["remaining_cents"] == SHORTFALL_CENTS
        assert intact["revoked_cents"] == 0

        revoked = validate_success(_revoke(api, credit["id"], CARE_REVOKER_HEADERS))
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_cents"] == SHORTFALL_CENTS
        assert revoked["remaining_cents"] == 0
        assert revoked["redeemed_cents"] == 0
        A.assert_credit_status(revoked)

        # Neither revoke attempt touched the ledger or the reservation's money.
        assert FX.ledger_rows(api, reservation_id, world["guest_headers"]) == rows_before
        settled = FX.read_reservation(api, reservation_id, world["guest_headers"])
        A.assert_money_breakdown(
            settled,
            amount_paid=DEPOSIT_DUE_CENTS,
            refunded=REFUNDED_AFTER_CANCEL + APPROVED_CENTS,
            forfeited=FORFEITED_AFTER_CANCEL - APPROVED_CENTS,
        )


def _envelope_world(api):
    """One held reservation plus a second guest who holds nothing.

    The class version read *before* the hold is retained: the hold advanced the
    class's version, so replaying the retained token is a genuine stale view.
    The second guest exists so that the out-of-band party attempt cannot be
    shadowed by the one-live-booking-per-service rule.
    """
    world = FX.build_world(api, guests=2)
    guest_one, guest_two = world["guests"]
    world["headers_one"] = make_guest_headers(guest_one["id"])
    world["headers_two"] = make_guest_headers(guest_two["id"])
    world["stale_version"] = FX.ticket_class_version(
        api, world["ticket_class_id"], world["headers_one"]
    )
    world["reservation"] = FX.hold_seats(
        api,
        world["ticket_class_id"],
        guest_one["id"],
        party_size=2,
        primary_guest_name="Envelope One",
    )
    world["fresh_version"] = FX.ticket_class_version(
        api, world["ticket_class_id"], world["headers_two"]
    )
    return world


def _pagination_probe(api):
    """A limit of 0, one below the declared minimum of 1."""
    return api.list_reservations(ADMIN_HEADERS, {"limit": 0})


def _payment_probe(api, world):
    """A first payment one cent under the reservation's deposit_due_cents."""
    return api.take_payment(
        world["reservation"]["id"],
        F.payment_payload(ONE_CENT_SHORT_OF_DEPOSIT),
        world["headers_one"],
    )


def _role_probe(api, world):
    """A KitchenLead reaching for the manager's publication endpoint."""
    return api.publish_service(
        world["service_id"], make_kitchen_headers(world["restaurant_id"])
    )


def _missing_probe(api):
    """A path identifier that resolves to nothing."""
    return api.get_reservation(MISSING_RESERVATION_ID, ADMIN_HEADERS)


def _state_probe(api, world):
    """Seating a reservation that is still only a hold."""
    return api.seat_reservation(
        world["reservation"]["id"], world["manager_headers"]
    )


def _stale_probe(api, world):
    """A create quoting the class version the existing hold superseded."""
    return api.create_reservation(
        F.reservation_payload(
            world["ticket_class_id"],
            world["guests"][1]["id"],
            world["stale_version"],
            party_size=2,
            primary_guest_name="Envelope Two",
        ),
        world["headers_two"],
    )


def _band_probe(api, world):
    """A party of 9 against a class whose band tops out at 8."""
    return api.create_reservation(
        F.reservation_payload(
            world["ticket_class_id"],
            world["guests"][1]["id"],
            world["fresh_version"],
            party_size=9,
            primary_guest_name="Envelope Two",
        ),
        world["headers_two"],
    )


class TestErrorEnvelopeShapeAcrossEveryStatusClass:
    """One reservation, seven rejections, one envelope."""

    def test_pagination_and_payment_rejections_carry_the_documented_envelope(
        self, api
    ):
        """The 400 and the 402 arms answer with the same two-field envelope.

        "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)." A payment is refused on the money
        rung instead: "the very first payment on a reservation must be at least
        `deposit_due_cents` (`ERR_PAYMENT_BELOW_DEPOSIT`)". Neither body may
        carry more than the envelope allows, because "The `meta` object for
        error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_returns_400_402_403_404_409_and_412_uniformly
        """
        world = _envelope_world(api)
        assert world["reservation"]["deposit_due_cents"] == DEPOSIT_DUE_CENTS
        assert world["reservation"]["grand_total_cents"] == GRAND_TOTAL_CENTS

        # A rejected list request carries no pagination block of its own, and a
        # rejected payment leaks no part of the reservation it was aimed at.
        pagination = _pagination_probe(api)
        assert pagination.status_code == 400
        _assert_error_envelope(pagination, E.ERR_INVALID_PAGINATION)

        payment = _payment_probe(api, world)
        assert payment.status_code == 402
        _assert_error_envelope(payment, E.ERR_PAYMENT_BELOW_DEPOSIT)

    def test_authorization_and_not_found_rejections_carry_the_documented_envelope(
        self, api
    ):
        """The 403 and the 404 arms answer with the same two-field envelope.

        "If the acting role is not among the roles listed for the endpoint being
        called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)." A path
        identifier that resolves to nothing is caught further down the same
        ladder: "Every identifier in the request path exists, validated left to
        right, on every endpoint that has a path identifier — otherwise the
        matching not-found code from §2.9." Both bodies are traceable, because
        "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/errors/error_envelope_shape_returns_400_402_403_404_409_and_412_uniformly
        """
        world = _envelope_world(api)

        unauthorized = _role_probe(api, world)
        assert unauthorized.status_code == 403
        _assert_error_envelope(unauthorized, E.ERR_UNAUTHORIZED)

        missing = _missing_probe(api)
        assert missing.status_code == 404
        _assert_error_envelope(missing, E.ERR_RESERVATION_NOT_FOUND)

        # The role rejection fires ahead of the service-state check, so the
        # already-published service is never even consulted.
        assert (
            FX.read_service(api, world["service_id"], world["manager_headers"])[
                "status"
            ]
            == "PUBLISHED"
        )

    def test_state_and_stale_view_rejections_carry_the_documented_envelope(self, api):
        """The 409 and the 412 arms answer with the same two-field envelope.

        Seating a hold breaks the seating state machine: "The reservation's
        `fulfillment_status` permits the operation per the seating state machine,
        on confirm, payment, add-on append, dietary-note capture, table
        assignment, seating, completion, no-show declaration, cancellation, name
        change and transfer — otherwise `ERR_RESERVATION_INVALID_STATE`." The
        replayed class version breaks the stale-view rule instead: "If it does
        not equal that ticket class's current `version`, the create is rejected
        with `ERR_STALE_TICKET_CLASS_VERSION` (HTTP 412)." Both bodies are
        stamped, because "The `api_request_timestamp` is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Design: Corner/errors/error_envelope_shape_returns_400_402_403_404_409_and_412_uniformly
        """
        world = _envelope_world(api)
        # The hold advanced the class's version, so the retained token is stale.
        assert world["fresh_version"] == world["stale_version"] + 1

        invalid_state = _state_probe(api, world)
        assert invalid_state.status_code == 409
        _assert_error_envelope(invalid_state, E.ERR_RESERVATION_INVALID_STATE)

        stale = _stale_probe(api, world)
        assert stale.status_code == 412
        _assert_error_envelope(stale, E.ERR_STALE_TICKET_CLASS_VERSION)

        # The state rung answers ahead of the missing table assignment and ahead
        # of the seating-time check, and the stale rung ahead of the seat pool.
        still_held = FX.read_reservation(
            api, world["reservation"]["id"], world["headers_one"]
        )
        assert still_held["fulfillment_status"] == "PENDING"
        assert still_held["assigned_table_id"] is None
        assert still_held["seat_to_utc"] is None

    def test_the_band_rejection_and_none_of_the_seven_moves_a_seat_or_a_cent(
        self, api
    ):
        """The 422 arm closes the set, and no rejected call leaves a trace.

        "The party size must sit inside the class's own band, or the create fails
        with `ERR_PARTY_SIZE_OUT_OF_BAND`." Every one of the seven refusals is
        answered from the same catalogue — "Every rejection returns the error
        envelope of §2.2 with the `error_id` set to one of the identifiers below
        and the HTTP status shown beside it." — and none of them may commit, so
        the only seat movement on record remains the one the accepted hold made:
        "`party_size` seats move out of `seats_available` and into `seats_held`,
        after which the class's status is re-derived against the precedence
        ladder and the class's `version` advances by one."

        Design: Corner/errors/error_envelope_shape_returns_400_402_403_404_409_and_412_uniformly
        """
        world = _envelope_world(api)

        out_of_band = _assert_error_envelope(
            _band_probe(api, world), E.ERR_PARTY_SIZE_OUT_OF_BAND
        )
        assert out_of_band["error_id"] == "ERR_PARTY_SIZE_OUT_OF_BAND"

        # Fire the whole set once more, one request per status class.
        probes = [
            (_pagination_probe(api), E.ERR_INVALID_PAGINATION),
            (_payment_probe(api, world), E.ERR_PAYMENT_BELOW_DEPOSIT),
            (_role_probe(api, world), E.ERR_UNAUTHORIZED),
            (_missing_probe(api), E.ERR_RESERVATION_NOT_FOUND),
            (_state_probe(api, world), E.ERR_RESERVATION_INVALID_STATE),
            (_stale_probe(api, world), E.ERR_STALE_TICKET_CLASS_VERSION),
            (_band_probe(api, world), E.ERR_PARTY_SIZE_OUT_OF_BAND),
        ]
        assert [response.status_code for response, _ in probes] == [
            ERROR_HTTP_STATUS[error_id] for _, error_id in probes
        ]
        for response, error_id in probes:
            assert response.json()["data"]["error_id"] == error_id

        # Not one of them incremented the class's version or moved a seat.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        assert ticket_class["version"] == world["fresh_version"]
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )

        held = FX.read_reservation(
            api, world["reservation"]["id"], world["headers_one"]
        )
        assert held["fulfillment_status"] == "PENDING"
        assert held["payment_status"] == "UNPAID"
        assert held["amount_paid_cents"] == 0

        # The second guest still owns nothing at all.
        assert (
            validate_success(
                api.list_reservations(
                    ADMIN_HEADERS,
                    {"guest_id": world["guests"][1]["id"], "limit": 100},
                )
            )
            == []
        )
