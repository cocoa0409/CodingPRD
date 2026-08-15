"""Telescope fleet: maintenance ticket cycle, condition ledger, retirement,
certification revocation cascade, OCC on telescope updates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ticket,
    create_certification,
    create_checked_out_loan,
    create_member_with_paid_dues,
    create_reserved_loan,
    create_telescope,
    get_success_data,
    make_member_headers,
    open_ticket,
    push_ticket_to_verification,
    setup_member_with_cert_and_scope,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]
CHAIR = TEST_USERS["equipment_chair_headers"]


class TestMaintenanceVerificationCycle:
    def test_verification_reopen_cycle_then_close(self, api):
        """PRD: "Starting work moves `OPEN → IN_PROGRESS`; submitting the
        work for verification moves `IN_PROGRESS → VERIFICATION`; a failed
        verification reopens the ticket `VERIFICATION → IN_PROGRESS` so work
        continues; and a passed verification closes it `VERIFICATION →
        CLOSED`."

        Design: Difficulty/non_linear_state_machine/maintenance_ticket_verification_cycle
        """
        scope = create_telescope(name="12in Dob", equipment_class="DOBSONIAN")
        ticket = open_ticket(scope["id"], kind="COLLIMATION",
                             severity="MEDIUM", condition_delta=-5)

        get_success_data(api.start_maintenance_ticket(ticket["id"], CHAIR))
        get_success_data(
            api.submit_ticket_verification(ticket["id"], CHAIR))
        looped = validate_success(
            api.reopen_maintenance_ticket(ticket["id"], CHAIR))
        assert looped["status"] == "IN_PROGRESS", (
            "The cycle VERIFICATION -> IN_PROGRESS is traversed on reopen")

        get_success_data(
            api.submit_ticket_verification(ticket["id"], CHAIR))
        closed = validate_success(
            api.close_maintenance_ticket(ticket["id"], CHAIR))
        assert closed["status"] == "CLOSED"

    def test_condition_delta_applies_once_despite_cycle(self, api):
        """PRD: "The recompute is a full reconciliation over the closed set
        on every close, which makes it commutative and idempotent: a
        ticket's delta applies exactly once no matter how many times the
        ticket cycled between in-progress and verification before closing."
        PRD: "when no other non-`CLOSED` ticket remains for that telescope,
        returns the telescope `MAINTENANCE → AVAILABLE`"

        Design: Difficulty/non_linear_state_machine/maintenance_ticket_verification_cycle
        """
        scope = create_telescope(name="Cycle Dob", equipment_class="DOBSONIAN")
        ticket = open_ticket(scope["id"], kind="COLLIMATION",
                             severity="MEDIUM", condition_delta=-5)
        get_success_data(api.start_maintenance_ticket(ticket["id"], CHAIR))
        get_success_data(api.submit_ticket_verification(ticket["id"], CHAIR))
        get_success_data(api.reopen_maintenance_ticket(ticket["id"], CHAIR))
        get_success_data(api.submit_ticket_verification(ticket["id"], CHAIR))
        get_success_data(api.close_maintenance_ticket(ticket["id"], CHAIR))

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["condition_score"] == 95, (
            "100 - 5 applied exactly once, on close, not per loop")
        assert scope_after["status"] == "AVAILABLE", (
            "Last ticket closed returns the telescope to AVAILABLE")


class TestRetirement:
    def test_retire_telescope_with_open_tickets_closes_them(self, api):
        """PRD: "From `MAINTENANCE`, retirement is the write-off path for
        equipment damaged beyond repair: it requires only that no
        reservation is `CHECKED_OUT` or `OVERDUE`, and as a side effect
        every non-`CLOSED` maintenance ticket for the telescope is forced to
        `CLOSED` with its `condition_delta` applied through the normal
        condition recompute."

        Design: Corner/endpoints/retire_telescope_with_open_tickets_closes_them
        """
        scope = create_telescope(name="Writeoff", equipment_class="SCT")
        ticket = open_ticket(scope["id"], kind="REPAIR", severity="HIGH",
                             condition_delta=-30)
        push_ticket_to_verification(ticket["id"])

        retired = validate_success(api.retire_telescope(scope["id"], CHAIR))
        assert retired["status"] == "RETIRED"
        assert retired["condition_score"] == 70, (
            "100 - 30 applied exactly once through the retire cascade")

        ticket_after = validate_success(
            api.get_maintenance_ticket(ticket["id"], CHAIR))
        assert ticket_after["status"] == "CLOSED", (
            "Non-CLOSED tickets are forced CLOSED on retirement")


class TestConditionScoreReconciliation:
    def test_derived_condition_score_reconciles_across_tickets(self, api):
        """PRD: "a telescope's `condition_score` is recomputed on every
        ticket close as 100 plus the sum of `condition_delta` across **all**
        of that telescope's tickets in `CLOSED` status, floored at 0"

        Design: Corner/cross_cutting_layers/derived_condition_score_reconciles_across_tickets
        """
        scope = create_telescope(name="Score Scope", equipment_class="SCT")
        t1 = open_ticket(scope["id"], kind="REPAIR", severity="LOW",
                         condition_delta=-10)
        close_ticket(t1["id"])
        t2 = open_ticket(scope["id"], kind="CLEANING", severity="LOW",
                         condition_delta=-5)
        push_ticket_to_verification(t2["id"])
        get_success_data(api.close_maintenance_ticket(t2["id"], CHAIR))

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["condition_score"] == 85, "100 - 10 - 5"
        assert scope_after["status"] == "AVAILABLE", (
            "All tickets closed: telescope returns to AVAILABLE")


class TestCertificationRevocationCascade:
    def test_revocation_cancels_matching_reserved_loan(self, api):
        """PRD: "when the `EquipmentChair` revokes a certification, every
        reservation in `RESERVED` status whose telescope's `equipment_class`
        matches the revoked class moves to `CANCELLED`, releasing those
        telescopes in turn."

        Design: Difficulty/transitive_cascade/certification_revocation_cascade_depth2
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            full_name="Revokee")
        scope = create_telescope(name="SCT-8", equipment_class="SCT")
        cert = create_certification(member["id"], "SCT",
                                    "2027-06-01T00:00:00Z")
        loan = create_reserved_loan(member, scope, "2026-08-05T00:00:00Z",
                                    "2026-08-09T00:00:00Z")

        get_success_data(api.revoke_training_certification(cert["id"], CHAIR))

        cert_after = validate_success(
            api.get_training_certification(cert["id"], CHAIR))
        assert cert_after["status"] == "REVOKED", "Link 1: cert revoked"
        loan_after = validate_success(api.get_loan_reservation(loan["id"], CHAIR))
        assert loan_after["status"] == "CANCELLED", (
            "Link 2: class-matched RESERVED loan cancelled")
        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "AVAILABLE", (
            "Link 3: telescope released by the loan cancellation")

    def test_revocation_leaves_non_matching_reserved_loan_alone(self, api):
        """PRD: "every reservation in `RESERVED` status whose telescope's
        `equipment_class` matches the revoked class moves to `CANCELLED`"

        Design: Difficulty/transitive_cascade/certification_revocation_cascade_depth2
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            full_name="Match Mary")
        scope_sct = create_telescope(name="SCT-9", equipment_class="SCT")
        scope_ref = create_telescope(name="Ref-1", equipment_class="REFRACTOR")
        cert_sct = create_certification(member["id"], "SCT",
                                        "2027-06-01T00:00:00Z")
        create_certification(member["id"], "REFRACTOR",
                             "2027-06-01T00:00:00Z")
        loan_sct = create_reserved_loan(member, scope_sct,
                                        "2026-08-05T00:00:00Z",
                                        "2026-08-09T00:00:00Z")
        loan_ref = create_reserved_loan(member, scope_ref,
                                        "2026-08-12T00:00:00Z",
                                        "2026-08-15T00:00:00Z")

        get_success_data(api.revoke_training_certification(cert_sct["id"], CHAIR))

        loan_sct_after = validate_success(
            api.get_loan_reservation(loan_sct["id"], CHAIR))
        assert loan_sct_after["status"] == "CANCELLED", (
            "Class-matched loan is cancelled")
        loan_ref_after = validate_success(
            api.get_loan_reservation(loan_ref["id"], CHAIR))
        assert loan_ref_after["status"] == "RESERVED", (
            "Non-matching class loan is untouched by the cascade")


class TestDamageOnReturnConsistency:
    def test_immediate_visibility_of_cascade_in_same_read(self, api):
        """PRD: "With `damage_reported` true, the telescope instead moves
        `ON_LOAN → MAINTENANCE` and a maintenance ticket is opened against
        it automatically."
        PRD: "the observable state of the system after a clock advance is
        identical to the state a sequence of manual transitions would have
        produced."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Imm Ian")
        loan = create_checked_out_loan(
            member, scope, "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z",
            checkout_clock="2026-08-02T12:00:00Z")

        returned = validate_success(
            api.return_loan(loan["id"], CHAIR, damage_reported=True))
        assert returned["status"] == "RETURNED"

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "MAINTENANCE", (
            "Damage return routes the telescope to MAINTENANCE immediately")

        tickets, _meta = validate_paginated(
            api.list_maintenance_tickets(CHAIR,
                                         params={"telescope_id": scope["id"]}))
        assert len(tickets) >= 1
        assert tickets[0]["status"] == "OPEN", (
            "Auto-opened damage ticket is discoverable via the filtered list")


class TestTelescopeOcc:
    def test_stale_telescope_version_rejected(self, api):
        """PRD: "Updating a telescope's descriptive fields requires the
        request to carry `expected_telescope_version` matching the
        telescope's current `version` ... a descriptive edit made from a
        superseded snapshot is rejected with `ERR_STALE_VERSION` (HTTP 412)
        rather than silently overwriting a fresher state."
        PRD: "Reservation, checkout, and return cascades all bump the
        telescope's `version` on every status change"

        Design: Corner/cross_cutting_layers/stale_telescope_version_rejected
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="OCC Olga")
        v0 = scope["version"]
        loan = create_reserved_loan(member, scope, "2026-08-05T00:00:00Z",
                                    "2026-08-07T00:00:00Z")
        get_success_data(api.cancel_loan(loan["id"], CHAIR))
        refreshed = validate_success(api.get_telescope(scope["id"], CHAIR))
        v1 = refreshed["version"]
        assert v1 > v0, "Reserve/cancel cascades bumped the version"

        stale = api.update_telescope(
            scope["id"], {"name": "Renamed", "expected_telescope_version": v0},
            CHAIR)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        ok = validate_success(api.update_telescope(
            scope["id"], {"name": "Renamed", "expected_telescope_version": v1},
            CHAIR))
        assert ok["name"] == "Renamed"
        assert ok["version"] == v1 + 1, (
            "A successful update bumps the telescope's version by 1")
