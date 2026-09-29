"""Where two rules are broken at once, and which one is allowed to answer.

The first half walks the ladder's low rungs: a forbidden role must answer before
an unknown path id, an unknown path parent before a malformed body, and a
malformed body before an unresolvable body foreign key. The second half covers
two conditional gates — the NDA requirement, which lives on the invitation rather
than on the carrier, and the blocking data-quality flags, which are only two of
the six a lane can carry.
"""

from test_helpers import (
    ANALYST,
    COMPLIANCE,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    add_lane,
    api_client,
    create_bid_event,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    invitation_payload,
    invitation_response_payload,
    lane_payload,
    make_carrier_rep_headers,
    qualification_review_payload,
    read_event,
    read_lane,
    second_carrier_overrides,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A well-formed identity that declares no role at all.
NO_ROLE_HEADERS = {"X-User-ID": "pa-001", "Content-Type": "application/json"}
#: The fallback CarrierRep identity: a role that is not on this endpoint's list.
CARRIER_REP = TEST_USERS["carrier_rep_headers"]

#: An equipment type outside the declared enumeration.
UNDECLARED_EQUIPMENT_TYPE = "SPACESHIP"
DANGLING_INCUMBENT = {
    "incumbent_carrier_id": NON_EXISTENT_UUID,
    "incumbent_rate_per_mile": TEST_DEFAULTS["LANE_A_INCUMBENT_RATE_PER_MILE"],
}
PROBE_LANE_CODE = "L-X"

#: A lane that trips both blocking flags at once: too long, and no trailing volume.
BLOCKED_LANE = {
    "lane_code": "L-BAD",
    "mileage": 3500,
    "trailing_12m_actual_loads": 0,
}
MAX_LANE_MILES = 3200
LANE_PLAN_LOADS = TEST_DEFAULTS["LANE_A_ANNUAL_VOLUME_LOADS"]
BLOCKING_FLAGS = {"MILEAGE_IMPLAUSIBLE", "MISSING_TRAILING_VOLUME"}


def _open_review(carrier_id, headers):
    """Attempts to open a qualification review without asserting the outcome."""
    return api_client.create_qualification_review(
        carrier_id, qualification_review_payload(), headers
    )


def _create_lane(event_id, **overrides):
    """Attempts a lane creation as the analyst, without asserting the outcome."""
    return api_client.create_lane(event_id, lane_payload(**overrides), ANALYST)


def _count_lanes(event_id):
    _rows, meta = validate_paginated(
        api_client.list_lanes(ANALYST, {"bid_event_id": event_id})
    )
    return meta["total_count"]


def _respond(invitation_id, carrier_id, **overrides):
    """Responds to an invitation as the owning carrier, without asserting."""
    return api_client.respond_to_invitation(
        invitation_id,
        invitation_response_payload(**overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _invite(event_id, carrier_id, **overrides):
    return validate_success(
        api_client.create_invitation(
            event_id, invitation_payload(carrier_id, **overrides), ANALYST
        ),
        201,
    )


def _read_invitation(invitation_id):
    return validate_success(api_client.get_invitation(invitation_id, ANALYST))


class TestForbiddenRoleAnswersBeforeAnUnknownPathId:
    """A caller without permission must not learn which identifiers exist."""

    def test_the_role_refusal_hides_whether_the_carrier_id_resolves(self):
        """403 for the unlisted role; the listed role proves the id is really unknown.

        PRD §2.9: "**Role authorisation.** The acting role appears in the endpoint's
        authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every
        endpoint."
        PRD §2.9: "**Path identifiers.** Every identifier appearing in the request path
        must resolve to an existing row, validated **left to right**"
        PRD §2.1: "If the headers are well formed but the acting role is not among the
        roles authorised for the endpoint being called, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/forbidden_role_is_reported_before_an_unknown_path_id
        """
        set_clock(DEFAULT_CLOCK)

        forbidden = _open_review(NON_EXISTENT_UUID, CARRIER_REP)
        validate_error(forbidden, "ERR_FORBIDDEN_ROLE", 403)
        assert forbidden.json()["data"]["error_id"] != "ERR_CARRIER_NOT_FOUND"
        assert forbidden.status_code != 404

        # The same call from a listed role reaches the path check and 404s there.
        listed = _open_review(NON_EXISTENT_UUID, COMPLIANCE)
        validate_error(listed, "ERR_CARRIER_NOT_FOUND", 404)

    def test_a_missing_role_header_outranks_the_role_authorisation_itself(self):
        """401 comes first: an unreadable role cannot be checked against a list.

        PRD §2.9: "**Header integrity.** Both `X-User-ID` and `X-User-Role` are present
        and the role is one of the five declared names, otherwise `ERR_UNAUTHENTICATED`
        (401). This applies to every endpoint except the logical-clock endpoint."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those
        five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/forbidden_role_is_reported_before_an_unknown_path_id
        """
        set_clock(DEFAULT_CLOCK)

        anonymous = _open_review(NON_EXISTENT_UUID, NO_ROLE_HEADERS)
        validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)
        assert anonymous.json()["data"]["error_id"] != "ERR_FORBIDDEN_ROLE"
        assert anonymous.json()["data"]["error_id"] != "ERR_CARRIER_NOT_FOUND"


class TestPathThenShapeThenBodyForeignKey:
    """Three adjacent rungs, separated by one walk over the same endpoint."""

    def test_each_rung_hides_the_next_until_the_one_above_it_is_clean(self):
        """404 on the parent, then 400 on the enum, then 404 on the body key.

        PRD §2.9: "so a request naming a non-existent parent fails on the parent even
        when the child identifier is also wrong"
        PRD §2.9: "**Body shape.** On every POST endpoint, each input field that has no
        declared default must be present; each supplied value must match its declared
        type; each enum value must be a declared member of its enumeration"
        PRD §2.9: "**Body foreign keys.** Every foreign key supplied in the request
        **body** must resolve to an existing row, checked in the order the fields are
        declared for that endpoint, each raising that entity's own 404 from the list in
        rung 3."
        PRD §3.3: "Each lane carries a `lane_code` of 1 to 32 characters, unique within
        its bid event"

        Design: Corner/validations/path_existence_outranks_body_shape_which_outranks_body_foreign_keys
        """
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event()

        unknown_parent = _create_lane(
            NON_EXISTENT_UUID,
            lane_code=PROBE_LANE_CODE,
            equipment_type=UNDECLARED_EQUIPMENT_TYPE,
        )
        validate_error(unknown_parent, "ERR_BID_EVENT_NOT_FOUND", 404)

        bad_shape = _create_lane(
            event["id"],
            lane_code=PROBE_LANE_CODE,
            equipment_type=UNDECLARED_EQUIPMENT_TYPE,
            **DANGLING_INCUMBENT,
        )
        validate_error(bad_shape, "ERR_INVALID_REQUEST", 400)
        assert bad_shape.json()["data"]["error_id"] != "ERR_CARRIER_NOT_FOUND"

        dangling_key = _create_lane(
            event["id"], lane_code=PROBE_LANE_CODE, **DANGLING_INCUMBENT
        )
        validate_error(dangling_key, "ERR_CARRIER_NOT_FOUND", 404)

        assert _count_lanes(event["id"]) == 0
        assert read_event(event["id"])["lane_count"] == 0


class TestNdaGateIsKeyedOnTheInvitation:
    """The flag lives on the invitation, not on the carrier or the event."""

    @staticmethod
    def _two_invitations():
        """One invitation requiring an NDA and one not, on the same locked event."""
        set_clock(DEFAULT_CLOCK)
        signer = create_qualified_carrier()
        plain_bidder = create_qualified_carrier(
            carrier_overrides=second_carrier_overrides()
        )
        event, _lanes = create_event_with_locked_lanes()
        return {
            "signer": signer,
            "plain_bidder": plain_bidder,
            "event": event,
            "nda_invitation": _invite(event["id"], signer["id"], nda_required=True),
            "plain_invitation": _invite(
                event["id"], plain_bidder["id"], nda_required=False
            ),
        }

    def test_accepting_an_nda_invitation_unsigned_is_refused_then_admitted_signed(self):
        """An absent `nda_signed` counts as false, and the retry is the same call.

        PRD §3.4: "if the invitation's `nda_required` is `true`, the payload's
        `nda_signed` must be `true`, otherwise the acceptance is rejected with
        `ERR_NDA_NOT_SIGNED` (409)."
        PRD §2.9: "an invitation requiring an NDA cannot be accepted without one
        (`ERR_NDA_NOT_SIGNED`)"
        PRD §3.4: "The invitation moves from `SENT` to `ACCEPTED`, `nda_signed` takes
        the payload value, `responded_at` is set to the clock, and the event's
        `accepted_invitation_count` is increased by one."

        Design: Corner/validations/nda_gate_applies_only_when_the_invitation_requires_it
        """
        ctx = self._two_invitations()
        assert ctx["nda_invitation"]["nda_required"] is True

        refused = _respond(ctx["nda_invitation"]["id"], ctx["signer"]["id"])
        validate_error(refused, "ERR_NDA_NOT_SIGNED", 409)
        assert _read_invitation(ctx["nda_invitation"]["id"])["status"] == "SENT"
        assert read_event(ctx["event"]["id"])["accepted_invitation_count"] == 0

        signed = validate_success(
            _respond(
                ctx["nda_invitation"]["id"], ctx["signer"]["id"], nda_signed=True
            )
        )
        assert signed["status"] == "ACCEPTED"
        assert signed["nda_signed"] is True
        assert read_event(ctx["event"]["id"])["accepted_invitation_count"] == 1

    def test_the_identical_bare_payload_is_admitted_on_a_non_nda_invitation(self):
        """Same payload, same carrier standing, different invitation flag.

        PRD §3.4: "The payload names the `carrier_id` and may state `nda_required`,
        which defaults to `true`."
        PRD §3.4: "A carrier representative responds on its own invitation, which must
        be `SENT`. The payload carries `accept`, a boolean, and may carry `nda_signed`
        and `decline_reason`."
        PRD §3.4: "The invitation is created with `status` `SENT`, `nda_signed` `false`,
        `snapshot_stale` `false`, and `responded_at`, `decline_reason` and
        `revoked_reason` null."
        PRD §2.12: "`BidEvent.invited_carrier_count` counts invitations whose status is
        `SENT`, `ACCEPTED` or `DECLINED`, so a revoked invitation drops out of it."

        Design: Corner/validations/nda_gate_applies_only_when_the_invitation_requires_it
        """
        ctx = self._two_invitations()
        assert ctx["plain_invitation"]["nda_required"] is False

        accepted = validate_success(
            _respond(ctx["plain_invitation"]["id"], ctx["plain_bidder"]["id"])
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["nda_signed"] is False

        validate_success(
            _respond(
                ctx["nda_invitation"]["id"], ctx["signer"]["id"], nda_signed=True
            )
        )
        event = read_event(ctx["event"]["id"])
        assert event["invited_carrier_count"] == 2
        assert event["accepted_invitation_count"] == 2


class TestBlockingFlagsRefuseValidationOutright:
    """Two of the six flags block, and a blocked lane blocks its event too."""

    @staticmethod
    def _event_with_a_blocked_lane():
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event()
        return event, add_lane(event["id"], **BLOCKED_LANE)

    def test_the_refused_validation_applies_none_of_its_side_effects(self):
        """The lane stays DRAFT with no baseline and no validated_at.

        PRD §2.9: "**Lane data quality.** The lane carries no blocking data-quality flag
        when it is validated or when its event's lanes are locked, otherwise
        `ERR_LANE_DATA_QUALITY_BLOCKED` (409)."
        PRD §3.3: "Validation recomputes the flags from scratch first; if the resulting
        list contains either blocking flag, the request is rejected with
        `ERR_LANE_DATA_QUALITY_BLOCKED` (409) and the lane stays in `DRAFT`."
        PRD §3.3: "A new lane is created with `status` `DRAFT`,
        `unallocated_volume_loads` equal to its `annual_volume_loads`,
        `awarded_coverage_pct` `0.00`, and `baseline_cost_usd` and `validated_at` null."
        PRD §3.3: "`MILEAGE_IMPLAUSIBLE` fires when `mileage` is below the plausible
        minimum of 25 miles or above the plausible maximum of 3200 miles."

        Design: Corner/validations/lane_with_blocking_data_quality_flags_cannot_be_validated
        """
        event, blocked = self._event_with_a_blocked_lane()
        assert blocked["mileage"] > MAX_LANE_MILES
        assert BLOCKING_FLAGS.issubset(set(blocked["data_quality_flags"]))

        validate_error(
            api_client.validate_lane(blocked["id"], ANALYST),
            "ERR_LANE_DATA_QUALITY_BLOCKED",
            409,
        )

        unchanged = read_lane(blocked["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["baseline_cost_usd"] is None
        assert unchanged["validated_at"] is None
        assert unchanged["unallocated_volume_loads"] == LANE_PLAN_LOADS
        assert unchanged["data_quality_flags"] == blocked["data_quality_flags"]

        # A lane that cannot be validated also stops the event's scope from freezing.
        validate_error(
            api_client.lock_lanes(event["id"], ANALYST), "ERR_LANE_NOT_VALIDATED", 409
        )
        assert read_event(event["id"])["status"] == "DRAFT"

    def test_an_advisory_only_sibling_lane_validates_normally(self):
        """`NO_INCUMBENT_BASELINE` alone never blocks anything.

        PRD §3.3: "The other four — `VOLUME_VARIANCE_HIGH`, `SEASONALITY_EXTREME`,
        `NO_INCUMBENT_BASELINE` and `ACCESSORIAL_OUTLIER` — are advisory: they are
        recorded and they can affect downstream arithmetic, but they never stop a lane
        from progressing."
        PRD §3.3: "`MISSING_TRAILING_VOLUME` fires when `trailing_12m_actual_loads` is
        null, or when it is present but equal to zero."
        PRD §3.3: "When `incumbent_rate_per_mile` is null the baseline is `0.00`
        outright."

        Design: Corner/validations/lane_with_blocking_data_quality_flags_cannot_be_validated
        """
        event, blocked = self._event_with_a_blocked_lane()
        sibling = add_lane(event["id"], lane_code="L-GOOD")
        assert sibling["data_quality_flags"] == ["NO_INCUMBENT_BASELINE"]

        validated = validate_success(api_client.validate_lane(sibling["id"], ANALYST))
        assert validated["status"] == "VALIDATED"
        assert validated["data_quality_flags"] == ["NO_INCUMBENT_BASELINE"]
        assert float(validated["baseline_cost_usd"]) == 0.00
        assert read_lane(blocked["id"])["status"] == "DRAFT"
