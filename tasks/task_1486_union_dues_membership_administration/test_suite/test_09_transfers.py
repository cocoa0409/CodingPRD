"""Member transfers between locals: lifecycle, guards, OCC, and per-capita
headcount conservation."""
import pytest

from test_helpers import (
    CLERK,
    SECRETARY_TREASURER_1_HEADERS,
    ST,
    ApiErrorId,
    assert_transfer,
    create_transfer_payload,
    drive_member_delinquent,
    get_member,
    get_transfer,
    is_valid_uuid,
    make_classification,
    make_local,
    make_member,
    make_member_headers,
    make_percapita_report,
    make_transfer,
    set_clock,
    setup_flat_local_with_journeyman,
    validate_error,
    validate_success,
)


def _setup_two_flat_locals(api):
    local1, cls = setup_flat_local_with_journeyman(local_name="Local 200")
    local2 = make_local("FLAT", name="Local 400", default_flat_dues_cents=1000)
    set_clock("2026-08-01T00:00:00Z")
    return local1, cls, local2


class TestTransferBranches:
    def test_transfer_reject_branch_then_terminal_lockdown(self, api, office_clerk_headers):
        """PRD section on transfers: the target side "rejects it to
        `REJECTED_BY_TARGET`, optionally recording a `reason` that is stored
        on the transfer as `reject_reason`", and "`REJECTED_BY_TARGET`,
        `COMPLETED`, `CANCELLED`, and `SUPERSEDED` are the terminal transfer
        states." A later accept violates the state guard
        (`ERR_TRANSFER_STATE_FORBIDDEN` is the validation order's transfer
        state-guard error).

        Design: Corner/state_machines/transfer_reject_branch_then_terminal_lockdown
        """
        local1, cls, local2 = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Branch Brad", member_number="M-001")
        transfer = make_transfer(member["id"], local2["id"], "2026-09")
        validate_success(api.certify_transfer(transfer["id"], office_clerk_headers), 200)
        rejected = validate_success(
            api.reject_transfer(transfer["id"], {"reason": "target local at capacity"}, office_clerk_headers),
            200,
        )
        assert rejected["status"] == "REJECTED_BY_TARGET"
        assert rejected["reject_reason"] == "target local at capacity"
        resp = api.accept_transfer(transfer["id"], office_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_STATE_FORBIDDEN)

    def test_transfer_complete_before_effective_period_rejected(self, api):
        """PRD section on transfers: "the current clock period must have
        reached the `effective_period` (`ERR_TRANSFER_NOT_READY` when
        completion is attempted earlier)".

        Design: Corner/validations/transfer_complete_before_effective_period_rejected
        """
        local1, cls, local2 = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Early Erin", member_number="M-001")
        transfer = make_transfer(member["id"], local2["id"], "2026-09")
        validate_success(api.certify_transfer(transfer["id"], CLERK), 200)
        validate_success(api.accept_transfer(transfer["id"], CLERK), 200)
        resp = api.complete_transfer(transfer["id"], SECRETARY_TREASURER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_READY)

    def test_transfer_to_same_local_rejected(self, api):
        """PRD section on transfers: "The target local must exist, be
        `ACTIVE`, and differ from the origin local
        (`ERR_TARGET_LOCAL_UNAVAILABLE`)".

        Design: Corner/errors/transfer_to_same_local_rejected
        """
        local1, cls, _ = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Loop Leo", member_number="M-001")
        fresh = get_member(member["id"])
        resp = api.create_transfer(
            member["id"],
            create_transfer_payload(local1["id"], "2026-09", fresh["version"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TARGET_LOCAL_UNAVAILABLE)


class TestTransferInitiationStanding:
    """Initiation is gated on the member's good standing even when the OCC
    version is fresh."""

    def _setup_delinquent_member(self, api):
        local1, cls, local2 = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Gated Gail", member_number="M-001")
        drive_member_delinquent(local1["id"], member["id"], ("2026-05", "2026-06"))
        return local1, local2, member

    def test_delinquent_member_initiation_rejected_despite_fresh_version(self, api):
        """PRD section on transfers: "the member must be in good standing at
        initiation (`ERR_NOT_GOOD_STANDING`)", and on members: "`good_standing`
        is true precisely when the member's `status` is `ACTIVE` and
        `arrears_cents` is zero".

        Design: Difficulty/cross_entity_state_dependency/transfer_initiate_requires_good_standing
        """
        _, local2, member = self._setup_delinquent_member(api)
        fresh = get_member(member["id"])
        assert fresh["good_standing"] is False, "DELINQUENT member is not in good standing"
        resp = api.create_transfer(
            member["id"],
            create_transfer_payload(local2["id"], "2026-09", fresh["version"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_GOOD_STANDING)

    def test_good_standing_member_with_fresh_version_initiates(self, api):
        """PRD section on transfers: "A new transfer starts `INITIATED` with
        `from_local_id` pinned to the member's current local, and initiation
        increments the member's `version`." A member in good standing carrying
        the current version passes both guards.

        Design: Difficulty/cross_entity_state_dependency/transfer_initiate_requires_good_standing
        """
        local1, cls, local2 = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Good Gwen", member_number="M-001")
        fresh = get_member(member["id"])
        assert fresh["good_standing"] is True
        resp = api.create_transfer(
            member["id"],
            create_transfer_payload(local2["id"], "2026-09", fresh["version"]),
            make_member_headers(member["id"]),
        )
        transfer = validate_success(resp, 201)
        assert_transfer(transfer)
        assert transfer["status"] == "INITIATED"
        assert transfer["from_local_id"] == local1["id"]
        assert transfer["to_local_id"] == local2["id"]


class TestTransferOcc:
    def test_occ_transfer_stale_member_version_rejected(self, api):
        """PRD section on optimistic concurrency: "If `expected_member_version`
        does not equal the member's current `version`, the initiation is
        rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412)." The first
        initiation bumps the member's version, so replaying the observed
        version is stale.

        Design: Corner/cross_cutting_layers/occ_transfer_stale_member_version_rejected
        """
        local1, cls, local2 = _setup_two_flat_locals(api)
        member = make_member(local1["id"], cls["id"], full_name="Occ Olga", member_number="M-001")
        fresh = get_member(member["id"])
        assert fresh["version"] == 1
        payload = create_transfer_payload(local2["id"], "2026-09", fresh["version"])
        first = validate_success(
            api.create_transfer(member["id"], payload, make_member_headers(member["id"])), 201
        )
        assert is_valid_uuid(first["id"])
        resp = api.create_transfer(
            member["id"],
            create_transfer_payload(local2["id"], "2026-10", fresh["version"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION, 412)


class TestTransferHeadcountConservation:
    """A completed transfer shifts the per-capita headcount at the period
    boundary, and the reverse transfer restores it; the cross-local tax sum
    is conserved at every observation."""

    def _setup_two_locals_with_members(self, api):
        local_a = make_local("FLAT", name="Local A")
        local_b = make_local("FLAT", name="Local B", default_flat_dues_cents=1000)
        cls = make_classification(local_a["id"], "JOURNEYMAN", 0)
        set_clock("2026-08-01T00:00:00Z")
        stayer = make_member(local_a["id"], cls["id"], full_name="Stayer Stan", member_number="A-001")
        mover = make_member(local_a["id"], cls["id"], full_name="Mover Mona", member_number="A-002")
        return local_a, local_b, stayer, mover

    def _complete_transfer(self, api, member_id, to_local_id, effective_period):
        transfer = make_transfer(member_id, to_local_id, effective_period)
        validate_success(api.certify_transfer(transfer["id"], CLERK), 200)
        validate_success(api.accept_transfer(transfer["id"], CLERK), 200)
        completed = validate_success(api.complete_transfer(transfer["id"], SECRETARY_TREASURER_1_HEADERS), 200)
        assert completed["status"] == "COMPLETED"
        return completed

    def test_completed_transfer_shifts_headcount_at_boundary(self, api):
        """PRD section on per-capita tax: "a transfer whose `effective_period`
        equals the report period counts the member at the target local for
        that period, and at the origin local for every earlier period."
        Before: 2 + 0; after T -> LB effective 2026-08: 1 + 1.

        Design: Difficulty/compensating_invariant/transfer_roundtrip_conserves_percapita_headcount
        """
        local_a, local_b, _, mover = self._setup_two_locals_with_members(api)
        report_a = make_percapita_report(local_a["id"], "2026-08")
        report_b = make_percapita_report(local_b["id"], "2026-08")
        assert (report_a["member_count"], report_a["tax_due_cents"]) == (2, 3000)
        assert (report_b["member_count"], report_b["tax_due_cents"]) == (0, 0)
        self._complete_transfer(api, mover["id"], local_b["id"], "2026-08")
        assert get_member(mover["id"])["local_id"] == local_b["id"]
        report_a2 = make_percapita_report(local_a["id"], "2026-08")
        report_b2 = make_percapita_report(local_b["id"], "2026-08")
        assert (report_a2["member_count"], report_a2["tax_due_cents"]) == (1, 1500)
        assert (report_b2["member_count"], report_b2["tax_due_cents"]) == (1, 1500)
        assert report_a2["tax_due_cents"] + report_b2["tax_due_cents"] == 3000, (
            "cross-local headcount x rate is conserved"
        )

    def test_reverse_transfer_restores_original_counts(self, api):
        """PRD section on per-capita tax: "a transfer whose `effective_period`
        equals the report period counts the member at the target local for
        that period, and at the origin local for every earlier period." The
        compensating reverse transfer restores 2 + 0.

        Design: Difficulty/compensating_invariant/transfer_roundtrip_conserves_percapita_headcount
        """
        local_a, local_b, _, mover = self._setup_two_locals_with_members(api)
        self._complete_transfer(api, mover["id"], local_b["id"], "2026-08")
        self._complete_transfer(api, mover["id"], local_a["id"], "2026-08")
        assert get_member(mover["id"])["local_id"] == local_a["id"]
        report_a3 = make_percapita_report(local_a["id"], "2026-08")
        report_b3 = make_percapita_report(local_b["id"], "2026-08")
        assert (report_a3["member_count"], report_a3["tax_due_cents"]) == (2, 3000)
        assert (report_b3["member_count"], report_b3["tax_due_cents"]) == (0, 0)
