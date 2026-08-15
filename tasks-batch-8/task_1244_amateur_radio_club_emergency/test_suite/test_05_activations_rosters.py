"""Served-agency agreements, emergency activations, and rosters (PRD §3.4):
activation gating, segregation of duties, roster capacity boundary, readiness
gating, validation ordering, OCC on activation creation, and no-show fallout."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    accumulate_closed_check_ins,
    activation_set_status,
    assert_activation_invariants,
    assert_emergency_activation,
    confirm_roster_entry,
    create_activation,
    create_active_member,
    create_emergency_activation_payload,
    create_member,
    create_net_control,
    create_served_agreement,
    get_success_data,
    make_ec_headers,
    make_member_headers,
    setup_operational_repeater,
    validate_error,
    volunteer,
)


def _ec_member(callsign="W1EC"):
    """A member row to back the EmergencyCoordinator role identity."""
    return create_member(callsign)


def _provisional_member(api, admin_headers, callsign="K1OPR"):
    """Member with exactly 3 closed-net check-ins: 50*(3/6)+20 = 45 -> PROVISIONAL."""
    _, repeater = setup_operational_repeater()
    nc = create_net_control()
    member = create_active_member(callsign)
    accumulate_closed_check_ins([member["id"]], 3, repeater["id"], nc["id"])
    return member


class TestActivationGating:
    def test_activation_under_draft_agreement_rejected(self, api, admin_headers):
        """PRD §3.4: "Moving an activation to `ACTIVATED` (`STANDBY` →
        `ACTIVATED`) requires the agreement to currently be `ACTIVE`
        (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/activation_requires_agreement_active
        """
        ec = _ec_member()
        agreement = create_served_agreement(status="DRAFT")
        activation = create_activation(agreement["id"], ec["id"], required_operators=3)
        resp = api.emergency_activation_set_status(
            activation["id"], {"to": "ACTIVATED"}, make_ec_headers(ec["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_rejected_activation_stays_standby(self, api, admin_headers):
        """PRD §3.4: "Moving an activation to `ACTIVATED` (`STANDBY` →
        `ACTIVATED`) requires the agreement to currently be `ACTIVE`
        (`ERR_AGREEMENT_NOT_ACTIVE` otherwise); the transition records the
        calling member as `activated_by_member_id` and stamps `activated_at`."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_agreement_active
        """
        ec = _ec_member()
        agreement = create_served_agreement(status="DRAFT")
        activation = create_activation(agreement["id"], ec["id"], required_operators=3)
        api.emergency_activation_set_status(
            activation["id"], {"to": "ACTIVATED"}, make_ec_headers(ec["id"]))
        after = get_success_data(api.get_emergency_activation(activation["id"], admin_headers))
        assert after["status"] == "STANDBY"


class TestRosterEligibility:
    def test_ineligible_member_cannot_volunteer(self, api, admin_headers):
        """PRD §3.4: "Volunteering requires the activation to be in `STANDBY`
        or `ACTIVATED` (else `ERR_ACTIVATION_NOT_OPEN`), the member's
        `membership_status` to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and
        the member's `readiness_tier` to be anything but `INELIGIBLE`
        (`ERR_ROSTER_ENTRY_INELIGIBLE`)."

        Design: Corner/state_machines/roster_volunteer_ineligible_member_rejected
        """
        ec = _ec_member()
        member = create_active_member("K1OPR")
        # No participation: score 20 -> INELIGIBLE (PRD §3.1).
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec["id"], required_operators=2)
        resp = api.create_roster_entry({"activation_id": activation["id"]},
                                       make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ROSTER_ENTRY_INELIGIBLE)

    def test_volunteer_with_nonexistent_activation_returns_not_found(self, api, admin_headers):
        """PRD §2.10: "Third, existence: path and body references resolved
        left-to-right (failures are `ERR_NOT_FOUND`)." and "Eighth, the state
        of referenced entities: active membership, equipment privilege
        standing, readiness tier, agreement and site status, coordination
        grants, and dues currency." — and "the reported error is always the
        earliest applicable one."

        Design: Corner/validations/roster_volunteer_existence_beats_business
        """
        member = create_active_member("K1OPR")
        # Member has zero activity (would fail the readiness-tier check), but
        # the non-existent activation is screened first.
        resp = api.create_roster_entry({"activation_id": NON_EXISTENT_UUID},
                                       make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_volunteer_to_cancelled_activation_rejected(self, api, admin_headers):
        """PRD §3.4: "Volunteering requires the activation to be in `STANDBY`
        or `ACTIVATED` (else `ERR_ACTIVATION_NOT_OPEN`)".

        Design: Corner/errors/volunteer_to_cancelled_activation_rejected
        """
        ec = _ec_member()
        member = create_active_member("K1OPR")
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec["id"], required_operators=2)
        activation_set_status(activation["id"], "CANCELLED", ec["id"])
        resp = api.create_roster_entry({"activation_id": activation["id"]},
                                       make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ACTIVATION_NOT_OPEN)


class TestDemobilizeSegregationOfDuties:
    def test_activator_cannot_demobilize(self, api, admin_headers):
        """PRD §3.4: "the member who demobilizes must not be the member
        recorded as `activated_by_member_id`, and a violation is rejected with
        `ERR_SOD_DEMOBILIZE`."

        Design: Corner/state_machines/demobilize_segregation_of_duties
        """
        ec1 = _ec_member("W1EC1")
        _ec_member("W2EC2")
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec1["id"], required_operators=2)
        activation_set_status(activation["id"], "ACTIVATED", ec1["id"])
        resp = api.emergency_activation_set_status(
            activation["id"], {"to": "DEMOBILIZED"}, make_ec_headers(ec1["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_DEMOBILIZE)

    def test_different_coordinator_demobilizes(self, api, admin_headers):
        """PRD §3.4: "Demobilization stamps `demobilized_at` and resolves the
        roster in two sibling branches — every `CONFIRMED` entry transitions to
        `RELEASED` and every `VOLUNTEERED` entry transitions to `WITHDRAWN` —
        after which the activation's `confirmed_count` and `staffing_posture`
        are recomputed."
        PRD §3.4: "the transition records the calling member as
        `activated_by_member_id` and stamps `activated_at`."

        Design: Corner/state_machines/demobilize_segregation_of_duties
        """
        ec1 = _ec_member("W1EC1")
        ec2 = _ec_member("W2EC2")
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec1["id"], required_operators=2)
        activation_set_status(activation["id"], "ACTIVATED", ec1["id"])
        demobilized = activation_set_status(activation["id"], "DEMOBILIZED", ec2["id"])
        assert demobilized["status"] == "DEMOBILIZED"
        assert demobilized["activated_by_member_id"] == ec1["id"]
        assert_emergency_activation(demobilized)
        assert_activation_invariants(demobilized)


class TestRosterCapacityBoundary:
    def _setup_full_roster(self, api, admin_headers):
        """required_operators 1; member A CONFIRMED (roster full, ADEQUATE);
        member B VOLUNTEERED."""
        ec = _ec_member()
        m1 = _provisional_member(api, admin_headers, "K1A")
        m2 = _provisional_member(api, admin_headers, "K2B")
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec["id"],
                                       title="Flood", required_operators=1)
        entry_a = volunteer(activation["id"], m1["id"])
        entry_a = confirm_roster_entry(entry_a["id"], ec["id"])
        entry_b = volunteer(activation["id"], m2["id"])
        return ec, m1, m2, activation, entry_a, entry_b

    def test_confirm_at_capacity_rejected_roster_full(self, api, admin_headers):
        """PRD §3.4: "The boundary is inclusive — a count exactly equal to the
        requirement is adequate and simultaneously blocks any further
        confirmation with `ERR_ROSTER_FULL`."

        Design: Difficulty/boundary_precision_check/roster_confirm_at_capacity_boundary
        """
        ec, _, _, activation, _, entry_b = self._setup_full_roster(api, admin_headers)
        resp = api.roster_entry_set_status(
            entry_b["id"], {"to": "CONFIRMED"}, make_ec_headers(ec["id"]))
        validate_error(resp, ApiErrorId.ERR_ROSTER_FULL)
        entry_b_after = get_success_data(api.get_roster_entry(entry_b["id"], admin_headers))
        assert entry_b_after["status"] == "VOLUNTEERED"

    def test_full_roster_reports_adequate_posture(self, api, admin_headers):
        """PRD §3.4: "`confirmed_count` is the number of entries in
        `CONFIRMED`; `staffing_posture` reads `ADEQUATE` when `confirmed_count`
        is at least `required_operators` and `UNDERSTAFFED` otherwise."

        Design: Difficulty/boundary_precision_check/roster_confirm_at_capacity_boundary
        """
        ec, _, _, activation, _, entry_b = self._setup_full_roster(api, admin_headers)
        api.roster_entry_set_status(
            entry_b["id"], {"to": "CONFIRMED"}, make_ec_headers(ec["id"]))
        after = get_success_data(api.get_emergency_activation(activation["id"], admin_headers))
        assert after["confirmed_count"] == 1
        assert after["staffing_posture"] == "ADEQUATE"
        assert_activation_invariants(after)


class TestRosterValidationOrder:
    def _setup_withdrawn_entry_on_full_roster(self, api, admin_headers):
        """required_operators 1; A CONFIRMED (full); B volunteered then
        withdrew -> B's entry is WITHDRAWN on a full activation."""
        ec, m1, m2, activation, entry_a, entry_b = \
            TestRosterCapacityBoundary._setup_full_roster(self, api, admin_headers)
        withdrawn = get_success_data(api.roster_entry_set_status(
            entry_b["id"], {"to": "WITHDRAWN"}, make_member_headers(m2["id"])))
        assert withdrawn["status"] == "WITHDRAWN"
        return ec, m2, activation, entry_b

    def test_confirm_withdrawn_entry_returns_invalid_state_not_full(self, api, admin_headers):
        """PRD §2.10: "Fourth, the from-state of the primary resource for the
        requested transition — generic invalid-from rejections are
        `ERR_INVALID_STATE`" and "Ninth and last, capacity and quota checks:
        roster fullness and exam session fullness." — and "the reported error
        is always the earliest applicable one."
        PRD §3.4: "Confirmation (`VOLUNTEERED` → `CONFIRMED`) is performed by
        an `EmergencyCoordinator`".

        Design: Difficulty/priority_pair_validation_conflict/roster_confirm_state_beats_capacity
        """
        ec, _, activation, entry_b = \
            self._setup_withdrawn_entry_on_full_roster(api, admin_headers)
        resp = api.roster_entry_set_status(
            entry_b["id"], {"to": "CONFIRMED"}, make_ec_headers(ec["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_confirm_leaves_state_untouched(self, api, admin_headers):
        """PRD §3.4: "`RELEASED`, `WITHDRAWN`, and `NO_SHOW` are terminal." —
        the WITHDRAWN entry stays WITHDRAWN and the full activation keeps its
        single confirmed seat.
        PRD §3.4: "`confirmed_count` is the number of entries in `CONFIRMED`".

        Design: Difficulty/priority_pair_validation_conflict/roster_confirm_state_beats_capacity
        """
        ec, _, activation, entry_b = \
            self._setup_withdrawn_entry_on_full_roster(api, admin_headers)
        api.roster_entry_set_status(
            entry_b["id"], {"to": "CONFIRMED"}, make_ec_headers(ec["id"]))
        entry_after = get_success_data(api.get_roster_entry(entry_b["id"], admin_headers))
        assert entry_after["status"] == "WITHDRAWN"
        act_after = get_success_data(api.get_emergency_activation(activation["id"], admin_headers))
        assert act_after["confirmed_count"] == 1


class TestRosterRbac:
    def test_member_cannot_confirm_own_roster_entry(self, api, admin_headers):
        """PRD §4: the roster set-status endpoint is described "Confirm,
        revert, release, no-show (EC); withdraw (self)" for roles
        "EmergencyCoordinator, Member", and §2.1: "A request whose role is not
        listed for the target endpoint, or that fails a declared ownership
        sub-check ... is rejected with `ERR_FORBIDDEN`."
        PRD §3.4: "Confirmation (`VOLUNTEERED` → `CONFIRMED`) is performed by
        an `EmergencyCoordinator`".

        Design: Corner/rbac/member_cannot_confirm_roster
        """
        ec = _ec_member()
        member = _provisional_member(api, admin_headers)
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec["id"], required_operators=2)
        entry = volunteer(activation["id"], member["id"])
        resp = api.roster_entry_set_status(
            entry["id"], {"to": "CONFIRMED"}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        entry_after = get_success_data(api.get_roster_entry(entry["id"], admin_headers))
        assert entry_after["status"] == "VOLUNTEERED"


class TestNoShowReadinessPenalty:
    def test_no_show_strips_bonus_and_recomputes_counts(self, api, admin_headers):
        """PRD §3.4: "or may be marked `NO_SHOW` (`CONFIRMED` → `NO_SHOW`) once
        the activation is `ACTIVATED` — the latter also recomputes the member's
        readiness, because the no-show lands in `no_shows_12m_count` and
        forfeits the no-show-free bonus for the following year."

        Design: Corner/state_machines/no_show_readiness_penalty
        """
        ec = _ec_member()
        member = _provisional_member(api, admin_headers)
        agreement = create_served_agreement(status="ACTIVE")
        activation = create_activation(agreement["id"], ec["id"],
                                       title="Flood", required_operators=1)
        entry = volunteer(activation["id"], member["id"])
        entry = confirm_roster_entry(entry["id"], ec["id"])
        activation_set_status(activation["id"], "ACTIVATED", ec["id"])
        marked = get_success_data(api.roster_entry_set_status(
            entry["id"], {"to": "NO_SHOW"}, make_ec_headers(ec["id"])))
        assert marked["status"] == "NO_SHOW"
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["no_shows_12m_count"] == 1
        # 3 closed-net check-ins: 50*(3/6) = 25; the no-show forfeits the +20
        # bonus, so the verified score drops 45 -> 25.
        assert detail["readiness_score"] == 25
        act_after = get_success_data(api.get_emergency_activation(activation["id"], admin_headers))
        assert act_after["confirmed_count"] == 0


class TestActivationCreationConstraints:
    def test_required_operators_exceeding_agreement_rejected(self, api, admin_headers):
        """PRD §3.4: "and `required_operators` must be greater than zero and no
        greater than the agreement's `max_operators` (else
        `ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT`)."

        Design: Corner/validations/required_operators_exceed_agreement_rejected
        """
        ec = _ec_member()
        agreement = create_served_agreement(status="DRAFT", max_operators=2)
        resp = api.create_emergency_activation(
            create_emergency_activation_payload(
                agreement["id"], agreement["version"], required_operators=5),
            make_ec_headers(ec["id"]))
        validate_error(resp, ApiErrorId.ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT)

    def test_stale_agreement_version_rejected_then_fresh_create_supersedes(
            self, api, admin_headers):
        """PRD §2.9: "If the supplied value does not match the agreement's
        current `version`, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.4: "Opening a new activation supersedes the old one: any prior
        `STANDBY` activation for the same agreement transitions to `CANCELLED`
        with the full roster cascade, and the agreement's `version` is bumped."

        Design: Corner/cross_cutting_complexity_layers/activation_create_stale_version_rejected
        """
        ec = _ec_member()
        agreement = create_served_agreement(status="ACTIVE")
        act1 = get_success_data(api.create_emergency_activation(
            create_emergency_activation_payload(
                agreement["id"], agreement["version"], title="Flood",
                required_operators=2),
            make_ec_headers(ec["id"])))
        # The first create bumped the agreement's version; the observed value
        # is now stale.
        stale = api.create_emergency_activation(
            create_emergency_activation_payload(
                agreement["id"], agreement["version"], title="Storm",
                required_operators=3),
            make_ec_headers(ec["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(
            api.get_served_agency_agreement(agreement["id"], admin_headers))
        act2 = get_success_data(api.create_emergency_activation(
            create_emergency_activation_payload(
                agreement["id"], fresh["version"], title="Storm",
                required_operators=3),
            make_ec_headers(ec["id"])))
        assert act2["status"] == "STANDBY"
        act1_after = get_success_data(api.get_emergency_activation(act1["id"], admin_headers))
        assert act1_after["status"] == "CANCELLED"
