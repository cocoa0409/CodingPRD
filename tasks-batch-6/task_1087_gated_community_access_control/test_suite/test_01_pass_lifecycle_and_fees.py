"""Guest / vendor passes: authorization axis, presence axis, and dual-variant fees.

Covers the estimated-vs-final pass fee, the parallel auth/presence axes, the
half-open gate window boundary, the sponsor eligibility gate, and the
referential-beats-temporal validation ordering.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_community, create_resident, create_pass, authorize_pass,
    record_gate_event, transition_resident, setup_community_and_resident,
    setup_approved_vendor_pass_onsite,
    OFFICER, ADMIN,
)


class TestPassDualVariantFee:
    """Tests for the pass_fee_estimated_vs_final rule (see per-test Design tags)."""

    def test_vendor_pass_estimated_fee_from_planned_window(self, api):
        """PRD §3.3: "On approval the system computes the provisional
        `estimated_fee_cents` from the planned window: the hourly rate is 500
        cents per hour for a `VENDOR` pass and 0 cents per hour for a `GUEST`
        pass; the planned span from `valid_from` to `valid_until` is converted
        to hours and rounded up to the next whole hour; and `estimated_fee_cents`
        is that whole-hour count multiplied by the rate."

        Design: Difficulty/dual_variant_calc/pass_fee_estimated_vs_final
        """
        set_clock("2026-06-01T08:00:00Z")
        _, resident = setup_community_and_resident()
        pass_obj = create_pass(
            resident["id"], pass_type="VENDOR", visitor_name="Ace Plumbing",
            visitor_plate="VEND01", valid_from="2026-06-01T09:00:00Z",
            valid_until="2026-06-01T13:00:00Z", vendor_company="Ace",
        )
        data = validate_success(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER))
        assert data["auth_status"] == "APPROVED"
        assert data["estimated_fee_cents"] == 2000, f"ceil(4h)*500 expected 2000, got {data['estimated_fee_cents']}"

    def test_vendor_pass_final_fee_from_dwell_and_overstay(self, api):
        """PRD §3.4: "The `final_fee_cents` is the billable hours multiplied by
        the rate, plus the overstay hours multiplied by the overstay surcharge of
        2,000 cents per hour."

        Design: Difficulty/dual_variant_calc/pass_fee_estimated_vs_final
        """
        community, _, pass_obj = setup_approved_vendor_pass_onsite(
            clock_iso="2026-06-01T08:00:00Z", valid_from="2026-06-01T09:00:00Z",
            valid_until="2026-06-01T13:00:00Z", entry_iso="2026-06-01T10:00:00Z",
            visitor_plate="VEND01",
        )
        set_clock("2026-06-01T14:30:00Z")
        record_gate_event(community["id"], "VEND01", "EXIT")
        data = validate_success(api.get_pass(pass_obj["id"], ADMIN))
        # billable = ceil(min(14:30,13:00)-10:00)=3h*500=1500 ; overstay=ceil(1.5)=2h*2000=4000
        assert data["final_fee_cents"] == 5500, f"expected 5500, got {data['final_fee_cents']}"
        assert data["estimated_fee_cents"] == 2000
        assert data["final_fee_cents"] != data["estimated_fee_cents"]
        assert data["presence_status"] == "DEPARTED"


class TestPassParallelAxes:
    """Tests for the pass_parallel_auth_and_presence_axes rule (see per-test Design tags)."""

    def test_revoke_pass_sets_auth_revoked(self, api):
        """PRD §3.3: "An `APPROVED` pass may be revoked by a `SecurityOfficer` or
        `CommunityAdmin`, moving `auth_status` to the terminal `REVOKED`; the
        delinquency cascade can also revoke an `APPROVED`/`OFFSITE` pass when its
        sponsor is suspended."

        Design: Difficulty/non_linear_state_machine/pass_parallel_auth_and_presence_axes
        """
        community, _, pass_obj = setup_approved_vendor_pass_onsite(
            clock_iso="2026-06-01T09:00:00Z", valid_from="2026-06-01T08:00:00Z",
            valid_until="2026-06-01T18:00:00Z", entry_iso="2026-06-01T10:00:00Z",
            visitor_plate="GUEST7",
        )
        data = validate_success(api.revoke_pass(pass_obj["id"], OFFICER))
        assert data["auth_status"] == "REVOKED"

    def test_revoke_pass_leaves_presence_onsite(self, api):
        """PRD §3.3: "A pass carries two independent status axes."
        PRD §3.4: "Gate events also drive the pass presence axis. When an `ENTRY`
        event matches an `APPROVED` pass whose presence is `OFFSITE` and whose
        window contains the event instant (`valid_from` at or before `event_at`,
        and `event_at` before `valid_until`), the pass's `presence_status`
        advances from `OFFSITE` to `ONSITE` and its `entry_at` is set to
        `event_at`; if the instant is outside the window, the event's decision is
        `DENY` and presence is unchanged."

        Design: Difficulty/non_linear_state_machine/pass_parallel_auth_and_presence_axes
        """
        community, _, pass_obj = setup_approved_vendor_pass_onsite(
            clock_iso="2026-06-01T09:00:00Z", valid_from="2026-06-01T08:00:00Z",
            valid_until="2026-06-01T18:00:00Z", entry_iso="2026-06-01T10:00:00Z",
            visitor_plate="GUEST7",
        )
        validate_success(api.revoke_pass(pass_obj["id"], OFFICER))
        data = validate_success(api.get_pass(pass_obj["id"], ADMIN))
        assert data["auth_status"] == "REVOKED"
        assert data["presence_status"] == "ONSITE", "presence axis unaffected by auth revoke"


class TestPassGateWindowBoundary:
    """Tests for the pass_window_half_open_at_gate_boundary rule (see per-test Design tags)."""

    def _setup_two_approved_passes(self):
        set_clock("2026-06-01T08:00:00Z")
        community, resident = setup_community_and_resident()
        pass_a = create_pass(
            resident["id"], pass_type="GUEST", visitor_name="Lower Bound",
            visitor_plate="GATEIN", valid_from="2026-06-01T09:00:00Z",
            valid_until="2026-06-01T13:00:00Z",
        )
        authorize_pass(pass_a["id"], "APPROVED")
        pass_b = create_pass(
            resident["id"], pass_type="GUEST", visitor_name="Upper Bound",
            visitor_plate="GATEUP", valid_from="2026-06-01T09:00:00Z",
            valid_until="2026-06-01T13:00:00Z",
        )
        authorize_pass(pass_b["id"], "APPROVED")
        return community, pass_a, pass_b

    def test_entry_at_valid_from_is_allowed(self, api):
        """PRD §3.4: "Failing a decal match, the read is checked against passes by
        `visitor_plate`, where a pass matches when its `auth_status` is `APPROVED`
        and the event's instant falls at or after `valid_from` and before
        `valid_until`."

        Design: Difficulty/boundary_precision_check/pass_window_half_open_at_gate_boundary
        """
        community, pass_a, _ = self._setup_two_approved_passes()
        set_clock("2026-06-01T09:00:00Z")
        ev = validate_success(api.create_gate_event(
            {"community_id": community["id"], "gate_id": "G1", "direction": "ENTRY", "plate_read": "GATEIN"},
            OFFICER), expected_status=201)
        assert ev["decision"] == "ALLOW", "event_at == valid_from is inside the half-open window"
        p = validate_success(api.get_pass(pass_a["id"], ADMIN))
        assert p["presence_status"] == "ONSITE"

    def test_entry_at_valid_until_is_denied(self, api):
        """PRD §3.4: "the event's instant falls at or after `valid_from` and
        before `valid_until`." and "a read that matches no valid credential yields
        `matched_type` of `UNMATCHED` and `decision` of `DENY`."

        Design: Difficulty/boundary_precision_check/pass_window_half_open_at_gate_boundary
        """
        community, _, pass_b = self._setup_two_approved_passes()
        set_clock("2026-06-01T13:00:00Z")
        ev = validate_success(api.create_gate_event(
            {"community_id": community["id"], "gate_id": "G1", "direction": "ENTRY", "plate_read": "GATEUP"},
            OFFICER), expected_status=201)
        assert ev["decision"] == "DENY", "event_at == valid_until is outside the exclusive upper bound"
        p = validate_success(api.get_pass(pass_b["id"], ADMIN))
        assert p["presence_status"] == "OFFSITE"


class TestPassSponsorEligibility:
    """Tests for the pass_authorize_depends_on_sponsor_resident_state rule (see per-test Design tags)."""

    def _setup_suspended_sponsor_pass(self, valid_from, valid_until, clock_before_authorize=None):
        set_clock("2026-06-01T08:00:00Z")
        community, resident = setup_community_and_resident()
        pass_obj = create_pass(
            resident["id"], pass_type="GUEST", visitor_name="Blocked Bob",
            visitor_plate="BLK001", valid_from=valid_from, valid_until=valid_until,
        )
        transition_resident(resident["id"], "SUSPENDED")
        if clock_before_authorize:
            set_clock(clock_before_authorize)
        return community, resident, pass_obj

    def test_authorize_suspended_sponsor_returns_sponsor_not_eligible(self, api):
        """PRD §3.3: "the sponsoring resident must be `ACTIVE` with `standing` of
        `GOOD`, failing which the request is refused with
        `ERR_SPONSOR_NOT_ELIGIBLE`".

        Design: Difficulty/cross_entity_state_dependency/pass_authorize_depends_on_sponsor_resident_state
        """
        _, _, pass_obj = self._setup_suspended_sponsor_pass(
            "2026-06-01T09:00:00Z", "2026-06-01T18:00:00Z")
        validate_error(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER),
                       ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value)

    def test_authorize_suspended_sponsor_leaves_pass_pending(self, api):
        """PRD §3.3: "A `decision` of `APPROVED` moves `auth_status` from
        `PENDING` to `APPROVED`, but only after two gates pass: the sponsoring
        resident must be `ACTIVE` with `standing` of `GOOD`, failing which the
        request is refused with `ERR_SPONSOR_NOT_ELIGIBLE`".

        Design: Difficulty/cross_entity_state_dependency/pass_authorize_depends_on_sponsor_resident_state
        """
        _, _, pass_obj = self._setup_suspended_sponsor_pass(
            "2026-06-01T09:00:00Z", "2026-06-01T18:00:00Z")
        validate_error(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER),
                       ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value)
        p = validate_success(api.get_pass(pass_obj["id"], ADMIN))
        assert p["auth_status"] == "PENDING"


class TestPassAuthorizeValidationOrdering:
    """Tests for the referential_beats_temporal_on_pass_authorize rule (see per-test Design tags)."""

    def _setup_suspended_sponsor_past_window(self):
        set_clock("2026-06-01T08:00:00Z")
        community, resident = setup_community_and_resident()
        pass_obj = create_pass(
            resident["id"], pass_type="GUEST", visitor_name="Late Larry",
            visitor_plate="LATE01", valid_from="2026-06-01T09:00:00Z",
            valid_until="2026-06-01T13:00:00Z",
        )
        transition_resident(resident["id"], "SUSPENDED")
        set_clock("2026-06-02T00:00:00Z")  # window now past
        return community, resident, pass_obj

    def test_referential_error_wins_over_temporal(self, api):
        """PRD §2.10: "cross-entity eligibility gates (`ERR_SPONSOR_NOT_ELIGIBLE`,
        `ERR_VEHICLE_INACTIVE`, `ERR_RESIDENT_NOT_ELIGIBLE`); temporal window and
        overlap gates (`ERR_PASS_WINDOW_INVALID`, `ERR_RESERVATION_WINDOW_INVALID`,
        `ERR_PATROL_OVERLAP`)".

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_pass_authorize
        """
        _, _, pass_obj = self._setup_suspended_sponsor_past_window()
        validate_error(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER),
                       ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value, expected_status=409)

    def test_referential_wins_leaves_pass_pending(self, api):
        """PRD §3.3: "the sponsoring resident must be `ACTIVE` with `standing` of
        `GOOD`, failing which the request is refused with
        `ERR_SPONSOR_NOT_ELIGIBLE`; and the pass window must be well-formed and
        not already past — that is, `valid_from` must be strictly before
        `valid_until`, and `valid_until` must be strictly after the current clock
        — failing which the request is refused with `ERR_PASS_WINDOW_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_pass_authorize
        """
        _, _, pass_obj = self._setup_suspended_sponsor_past_window()
        validate_error(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER),
                       ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE.value)
        p = validate_success(api.get_pass(pass_obj["id"], ADMIN))
        assert p["auth_status"] == "PENDING"


def test_guest_pass_estimated_fee_zero_rate(api):
    """PRD §3.3: "the hourly rate is 500 cents per hour for a `VENDOR` pass and
    0 cents per hour for a `GUEST` pass; the planned span from `valid_from` to
    `valid_until` is converted to hours and rounded up to the next whole hour;
    and `estimated_fee_cents` is that whole-hour count multiplied by the rate."

    Design: Corner/calculations/guest_pass_estimated_fee_zero_rate
    """
    set_clock("2026-06-01T08:00:00Z")
    _, resident = setup_community_and_resident()
    pass_obj = create_pass(
        resident["id"], pass_type="GUEST", visitor_name="Free Guest",
        visitor_plate="FREE01", valid_from="2026-06-01T09:00:00Z",
        valid_until="2026-06-01T11:00:00Z",
    )
    data = validate_success(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER))
    assert data["auth_status"] == "APPROVED"
    assert data["estimated_fee_cents"] == 0


def test_pass_authorize_past_window_returns_window_invalid(api):
    """PRD §3.3: "the pass window must be well-formed and not already past — that
    is, `valid_from` must be strictly before `valid_until`, and `valid_until`
    must be strictly after the current clock — failing which the request is
    refused with `ERR_PASS_WINDOW_INVALID`."

    Design: Corner/validations/pass_authorize_past_window_returns_window_invalid
    """
    set_clock("2026-06-05T00:00:00Z")
    _, resident = setup_community_and_resident()
    pass_obj = create_pass(
        resident["id"], pass_type="GUEST", visitor_name="Old Otto",
        visitor_plate="OLD777", valid_from="2026-06-01T09:00:00Z",
        valid_until="2026-06-01T13:00:00Z",
    )
    validate_error(api.authorize_pass(pass_obj["id"], {"decision": "APPROVED"}, OFFICER),
                   ApiErrorId.ERR_PASS_WINDOW_INVALID.value)
