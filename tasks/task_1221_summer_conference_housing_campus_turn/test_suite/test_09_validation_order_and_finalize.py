"""Validation ordering pairs and the finalize gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    add_participants,
    create_building_turn_active,
    create_group,
    create_revision_payload,
    get_assignment_for_participant,
    get_group,
    get_success_data,
    make_coordinator_headers,
    set_clock,
    setup_checked_in_group,
    submit_group,
    submit_screening,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
SCREENING = TEST_USERS["screening_headers"]


class TestSafetyBeatsFiscal:
    def _unsafe_underfunded_group(self, api):
        """Minor-flagged group, SUBMITTED, screening only SUBMITTED (never
        decided), deposit 0 — both a safety and a fiscal violation hold."""
        building, rooms = create_building_turn_active(name="Lyman Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group = create_group(building["id"], client_name="Math Circle",
                             arrival_date="2026-06-22", departure_date="2026-06-26",
                             contracted_bed_count=2, has_minor_participants=True)
        participants = add_participants(group["id"], [
            ("Chap One", "1982-09-09", "CHAPERONE"),
            ("Kid One", "2013-02-02", "ATTENDEE"),
        ])
        screening = submit_screening(participants[0]["id"], group["id"], "CONS-2")
        headers = make_coordinator_headers(group["id"])
        version = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"],
            create_revision_payload(version, [
                {"participant_id": participants[0]["id"], "room_id": rooms["R1"]["id"],
                 "checkin_at": "2026-06-22T15:00:00Z",
                 "checkout_at": "2026-06-26T11:00:00Z"},
                {"participant_id": participants[1]["id"], "room_id": rooms["R1"]["id"],
                 "checkin_at": "2026-06-22T15:00:00Z",
                 "checkout_at": "2026-06-26T11:00:00Z"},
            ]),
            headers))
        submit_group(group["id"])
        return group, screening

    def test_safety_beats_fiscal_on_confirm(self, api):
        """PRD: "the checks run in a fixed sequence: the host building must be
        TURN_ACTIVE (else ERR_BUILDING_NOT_RELEASED); then, for minor-flagged
        groups, the safety gates of §3.3 in their stated order — chaperone ratio
        (ERR_CHAPERONE_RATIO_UNMET), screening clearance
        (ERR_SCREENING_NOT_CLEARED), screening freshness (ERR_SCREENING_EXPIRED);
        then the rooming-list gates ... and finally the fiscal gate"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm
        """
        group, screening = self._unsafe_underfunded_group(api)
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)
        group_after = get_group(group["id"])
        assert group_after["status"] == "SUBMITTED"
        assert group_after["provisional_invoice_id"] is None, "no invoice is created"

    def test_fiscal_error_surfaces_once_safety_passes(self, api):
        """PRD: "and finally the fiscal gate — the deposit must cover at least
        one quarter of the provisional bed-night estimate, evaluated integer-exact
        as deposit_paid_cents multiplied by four being at least the estimate in
        cents (else ERR_DEPOSIT_INSUFFICIENT)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm
        """
        group, screening = self._unsafe_underfunded_group(api)
        # Clear the safety violation; the deposit-0 fiscal violation remains and
        # must now be the surfaced error, proving the safety gate ran first.
        get_success_data(api.begin_review_screening(screening["id"], SCREENING))
        get_success_data(api.decide_screening(screening["id"], "CLEAR", SCREENING))
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)
        assert get_group(group["id"])["status"] == "SUBMITTED"


class TestFinalizeGate:
    def test_finalize_before_closeout_rejected(self, api):
        """PRD: "A `FinanceOfficer` finalizes the invoice, moving `PROVISIONAL` to
        `FINALIZED`, permitted only while the group is `DEPARTED` — otherwise
        `ERR_INVOICE_NOT_FINALIZABLE`."

        Design: Corner/validations/finalize_before_closeout_rejected
        """
        building, rooms = create_building_turn_active(name="Beta Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, assignments, invoice_id = setup_checked_in_group(
            building, rooms, client_name="Early Finalize")
        assert get_group(group["id"])["status"] == "IN_HOUSE"
        resp = api.finalize_invoice(invoice_id, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FINALIZABLE)
        invoice = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice["status"] == "PROVISIONAL"
        assert invoice["total_cents"] is None
