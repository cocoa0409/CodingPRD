"""Evidence packet readiness (vacuous truth, attach/detach/waive cycles),
LEVEL_3 filing gating on packet readiness, packet immutability after
submission, and waiver authority."""
from test_helpers import (
    ApiErrorId,
    add_packet_item,
    attach_item,
    create_packet,
    detach_item,
    get_packet,
    setup_level3_appeal,
    submit_packet,
    validate_error,
    validate_paginated,
    validate_success,
    waive_item,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["specialist_headers"]


class TestPacketReadinessCycle:
    def test_readiness_cycles_with_required_item_mutations(self, api):
        """PRD §3.6: "A new packet starts in `ASSEMBLING`, and its readiness is
        evaluated immediately: with no required items yet, the required set is
        empty and the packet is `READY` at creation by vacuous truth."
        PRD §3.6: "Readiness is recomputed after every item mutation: the
        packet is `READY` exactly when every item with `required` true is in
        `ATTACHED` or `WAIVED`, and whenever a required item enters `PENDING` —
        newly added or detached — a `READY` packet reverts to `ASSEMBLING`."

        Design: Difficulty/non_linear_state_machine/evidence_packet_compound_revert_cycle
        """
        _ctx, appeal = setup_level3_appeal()
        assert appeal["level"] == "LEVEL_3"
        packet = create_packet(appeal["id"])
        assert packet["status"] == "READY", (
            "Empty required set is vacuously READY at creation")
        item = add_packet_item(packet["id"], "MEDICAL_RECORD", required=True)
        assert get_packet(packet["id"])["status"] == "ASSEMBLING", (
            "A required PENDING item reverts READY to ASSEMBLING")
        attach_item(packet["id"], item["id"], "doc-1")
        assert get_packet(packet["id"])["status"] == "READY", (
            "Attaching the only required item restores READY")
        detach_item(packet["id"], item["id"])
        assert get_packet(packet["id"])["status"] == "ASSEMBLING", (
            "Detaching a required item reverts readiness again")

    def test_waive_satisfies_readiness_and_packet_submits(self, api):
        """PRD §3.6: "the packet is `READY` exactly when every item with
        `required` true is in `ATTACHED` or `WAIVED`"
        PRD §3.6: "Submission moves the packet `READY → SUBMITTED` and stamps
        `submitted_at` with the logical now; `SUBMITTED` is terminal for the
        packet."

        Design: Difficulty/non_linear_state_machine/evidence_packet_compound_revert_cycle
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        item1 = add_packet_item(packet["id"], "MEDICAL_RECORD", required=True)
        attach_item(packet["id"], item1["id"], "doc-2")
        item2 = add_packet_item(packet["id"], "PHYSICIAN_LETTER", required=True)
        assert get_packet(packet["id"])["status"] == "ASSEMBLING", (
            "The second required PENDING item reverts readiness")
        waive_item(packet["id"], item2["id"])
        assert get_packet(packet["id"])["status"] == "READY", (
            "A waived required item satisfies readiness")
        submitted = submit_packet(packet["id"])
        assert submitted["status"] == "SUBMITTED"


class TestVacuousReadiness:
    def test_packet_with_empty_required_set_born_ready(self, api):
        """PRD §3.6: "with no required items yet, the required set is empty and
        the packet is `READY` at creation by vacuous truth."

        Design: Difficulty/boundary_precision_check/packet_empty_required_set_vacuous_ready
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        assert packet["status"] == "READY"

    def test_optional_pending_item_does_not_gate_readiness(self, api):
        """PRD §3.6: "the packet is `READY` exactly when every item with
        `required` true is in `ATTACHED` or `WAIVED`"

        Design: Difficulty/boundary_precision_check/packet_empty_required_set_vacuous_ready
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        item = add_packet_item(packet["id"], "EXPERT_REVIEW", required=False)
        assert item["status"] == "PENDING"
        assert get_packet(packet["id"])["status"] == "READY", (
            "An optional PENDING item does not gate readiness")


class TestLevel3FilingGate:
    def test_level3_file_blocked_while_packet_assembling(self, api):
        """PRD §3.4: "A `LEVEL_3` filing — `ALJ` on the Medicare track,
        `EXTERNAL_REVIEW` on the commercial track — additionally requires the
        appeal's evidence packet to exist in `READY` or `SUBMITTED` status;
        filing a third-level appeal without a ready packet is rejected with
        `ERR_EVIDENCE_PACKET_NOT_READY` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/level3_file_gated_by_packet_readiness
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        add_packet_item(packet["id"], "MEDICAL_RECORD", required=True)
        resp = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_PACKET_NOT_READY)

    def test_level3_file_succeeds_once_packet_ready(self, api):
        """PRD §3.4: "A `LEVEL_3` filing — `ALJ` on the Medicare track,
        `EXTERNAL_REVIEW` on the commercial track — additionally requires the
        appeal's evidence packet to exist in `READY` or `SUBMITTED` status"
        PRD §3.4: "When the logical clock reads at or before
        `filed_deadline_at`, filing moves the appeal `DRAFT →
        PENDING_DECISION` and stamps `filed_at` with the logical now."

        Design: Difficulty/cross_entity_state_dependency/level3_file_gated_by_packet_readiness
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        item = add_packet_item(packet["id"], "MEDICAL_RECORD", required=True)
        resp = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_PACKET_NOT_READY)
        attach_item(packet["id"], item["id"], "doc-1")
        filed = validate_success(api.file_appeal(appeal["id"], SPECIALIST), 200)
        assert filed["status"] == "PENDING_DECISION"


class TestPacketCardinalityAndImmutability:
    def test_second_packet_for_same_appeal_rejected(self, api):
        """PRD §3.6: "the relationship is strictly one packet per appeal,
        recorded through the packet's `appeal_id`, and a second creation
        attempt against the same appeal is rejected with
        `ERR_PACKET_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_packet_rejected
        """
        _ctx, appeal = setup_level3_appeal()
        create_packet(appeal["id"])
        resp = api.create_evidence_packet(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_PACKET_ALREADY_EXISTS)

    def test_item_mutation_after_submit_rejected(self, api):
        """PRD §3.6: "Once a packet is `SUBMITTED` it is sealed: creating items
        on it, or mutating any of its items, is rejected with
        `ERR_PACKET_IMMUTABLE` (HTTP 409)."

        Design: Corner/validations/packet_item_mutation_after_submit_rejected
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        item = add_packet_item(packet["id"], "EXPERT_REVIEW", required=False)
        submitted = submit_packet(packet["id"])
        assert submitted["status"] == "SUBMITTED"
        resp = api.attach_packet_item(packet["id"], item["id"],
                                      {"document_ref": "doc-late"}, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_PACKET_IMMUTABLE)


class TestWaiverAuthority:
    def test_specialist_cannot_waive_required_item(self, api,
                                                   specialist_headers):
        """PRD §3.6: "A `DepartmentDirector` may waive a pending item, moving
        it `PENDING → WAIVED` — director authority is required precisely
        because waiving lowers the evidentiary bar."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/specialist_cannot_waive_item
        """
        _ctx, appeal = setup_level3_appeal()
        packet = create_packet(appeal["id"])
        item = add_packet_item(packet["id"], "MEDICAL_RECORD", required=True)
        resp = api.waive_packet_item(packet["id"], item["id"],
                                     specialist_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        items, _meta = validate_paginated(
            api.list_packet_items(packet["id"], specialist_headers))
        assert items[0]["status"] == "PENDING"
