"""Petition lifecycle: threshold boundary, state gating of signatures,
retraction accounting, immutability of the event record, and the deadline
sweep (PRD §2.4, §2.5, §3.2)."""
from test_helpers import (
    TE,
    ApiErrorId,
    api_client,
    assert_signature,
    assert_timestamp_equals,
    create_resident,
    create_segment,
    file_request,
    get_request,
    make_resident_headers,
    open_petition,
    required_signatures_for,
    set_clock,
    setup_petition_open,
    sign_petition,
    validate_error,
    validate_success,
)


class TestPetitionThresholdBoundary:
    def test_signature_count_below_threshold_keeps_petition_open(self):
        """PRD §3.2: "Opening stamps `petition_opened_at` from the logical clock, sets `petition_deadline_at` ninety days later, snapshots `required_signatures` as the segment's `household_count` multiplied by sixty percent and rounded up to the next whole number, initializes `signature_count` to zero, and advances the request from `SUBMITTED` to `PETITION_OPEN`."

        Design: Difficulty/boundary_precision_check/petition_threshold_exact_count_flips
        """
        ctx = setup_petition_open(
            name="Holly Ave", household_count=10, resident_prefix="bp",
            signatures=4,
        )
        opened = ctx["opened"]
        assert opened["required_signatures"] == 6, (
            f"required_signatures must be ceil(10 * 60%) = 6, "
            f"got {opened['required_signatures']}"
        )
        assert required_signatures_for(10) == 6

        req = ctx["request"]
        sign_petition(req["id"], ctx["residents"][4]["id"])
        after5 = get_request(req["id"])
        assert after5["signature_count"] == 5, (
            f"signature_count must be 5 after five households signed, "
            f"got {after5['signature_count']}"
        )
        assert after5["status"] == "PETITION_OPEN", (
            f"at 5 of 6 the request must remain PETITION_OPEN, "
            f"got {after5['status']}"
        )

    def test_signature_count_exactly_at_threshold_flips_to_met(self):
        """PRD §3.2: "the moment that count reaches `required_signatures` — an exactly equal count is sufficient, the boundary is inclusive — the request flips automatically from `PETITION_OPEN` to `PETITION_MET`."

        Design: Difficulty/boundary_precision_check/petition_threshold_exact_count_flips
        """
        ctx = setup_petition_open(
            name="Holly Ave", household_count=10, resident_prefix="bp",
            signatures=4,
        )
        req = ctx["request"]
        sign_petition(req["id"], ctx["residents"][4]["id"])
        sign_petition(req["id"], ctx["residents"][5]["id"])
        after6 = get_request(req["id"])
        assert after6["signature_count"] == 6, (
            f"signature_count must be 6 after six households signed, "
            f"got {after6['signature_count']}"
        )
        assert after6["status"] == "PETITION_MET", (
            f"at exactly required_signatures the request must flip to "
            f"PETITION_MET, got {after6['status']}"
        )


class TestSignatureStateGating:
    def test_signature_rejected_while_request_submitted(self):
        """PRD §3.2: "Signatures are accepted only while the request remains `PETITION_OPEN` and the logical clock has not passed `petition_deadline_at`."

        Design: Difficulty/cross_entity_state_dependency/signature_rejected_before_petition_opened
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(name="Kalmia Dr", household_count=4)
        resident = create_resident(seg["id"], "R1", "ce2-r1@example.com", "H1")
        req = file_request(seg["id"], resident["id"], title="Calm Kalmia Dr",
                           requested_budget_cents=70000)
        assert req["status"] == "SUBMITTED"
        resp = api_client.sign_petition(
            req["id"], make_resident_headers(resident["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)

    def test_signature_accepted_once_petition_opened(self):
        """PRD §3.2: "Signatures are accepted only while the request remains `PETITION_OPEN` and the logical clock has not passed `petition_deadline_at`."
        PRD §3.2: "Every accepted signature recomputes the request's `signature_count`"

        Design: Difficulty/cross_entity_state_dependency/signature_rejected_before_petition_opened
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(name="Kalmia Dr", household_count=4)
        resident = create_resident(seg["id"], "R1", "ce2-r1@example.com", "H1")
        req = file_request(seg["id"], resident["id"], title="Calm Kalmia Dr",
                           requested_budget_cents=70000)
        rejected = api_client.sign_petition(
            req["id"], make_resident_headers(resident["id"])
        )
        validate_error(rejected, ApiErrorId.ERR_REQUEST_INVALID_STATE)

        open_petition(req["id"])
        sig = sign_petition(req["id"], resident["id"])
        assert_signature(sig)
        after = get_request(req["id"])
        assert after["signature_count"] == 1, (
            f"after open-petition the same signature call succeeds and "
            f"signature_count is 1, got {after['signature_count']}"
        )


class TestSignatureCountConservation:
    def test_three_signatures_accumulate_without_flip(self):
        """PRD §3.2: "Every accepted signature recomputes the request's `signature_count`"

        Design: Difficulty/compensating_invariant/signature_count_conserved_across_add_and_retract
        """
        ctx = setup_petition_open(
            name="Nutwood St", household_count=10, resident_prefix="ci2",
            resident_count=3, signatures=0,
        )
        req = ctx["request"]
        for resident in ctx["residents"]:
            sign_petition(req["id"], resident["id"])
        after = get_request(req["id"])
        assert after["signature_count"] == 3, (
            f"three accepted signatures must give signature_count 3, "
            f"got {after['signature_count']}"
        )
        assert after["status"] == "PETITION_OPEN", (
            f"3 of 6 required must leave the request PETITION_OPEN, "
            f"got {after['status']}"
        )

    def test_retraction_decrements_and_readd_is_allowed(self):
        """PRD §3.2: "retraction removes the record with a 204 No Content response and recomputes — that is, decrements — the request's `signature_count`."
        PRD §3.2: "each household may hold at most one live signature on a given request"

        Design: Difficulty/compensating_invariant/signature_count_conserved_across_add_and_retract
        """
        ctx = setup_petition_open(
            name="Nutwood St", household_count=10, resident_prefix="ci2",
            resident_count=3, signatures=0,
        )
        req = ctx["request"]
        sig1 = sign_petition(req["id"], ctx["residents"][0]["id"])
        sign_petition(req["id"], ctx["residents"][1]["id"])
        sign_petition(req["id"], ctx["residents"][2]["id"])
        assert get_request(req["id"])["signature_count"] == 3

        resp = api_client.retract_signature(
            sig1["id"], make_resident_headers(ctx["residents"][0]["id"])
        )
        assert resp.status_code == 204, (
            f"retraction must return 204 No Content, got {resp.status_code}"
        )
        after_retract = get_request(req["id"])
        assert after_retract["signature_count"] == 2, (
            f"one retraction must decrement the count to exactly 2, "
            f"got {after_retract['signature_count']}"
        )

        # Live-row uniqueness: the retracted household may sign again.
        sign_petition(req["id"], ctx["residents"][0]["id"])
        after_readd = get_request(req["id"])
        assert after_readd["signature_count"] == 3, (
            f"re-signing after retraction must restore the count to 3, "
            f"got {after_readd['signature_count']}"
        )


class TestSignatureRecordShape:
    def test_signature_is_immutable_event_record(self):
        """PRD §2.5: "A petition signature, a study observation, and a ballot vote are immutable once created, and each therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from them."
        PRD §3.2: "each accepted signature records the `request_id`, the `resident_id` taken from the header, the signer's `household_ref` copied from their profile, and `signed_at` stamped from the logical clock."

        Design: Corner/entities/signature_entity_is_immutable_common_fields_false
        """
        ctx = setup_petition_open(
            name="Imm Ave", household_count=4, resident_prefix="imm",
            resident_count=1, signatures=0,
        )
        req = ctx["request"]
        resident = ctx["residents"][0]
        resp = api_client.sign_petition(
            req["id"], make_resident_headers(resident["id"])
        )
        sig = validate_success(resp, expected_status=201)
        assert_signature(sig)
        assert_timestamp_equals(sig["signed_at"], "2026-08-01T00:00:00Z",
                                "signed_at")
        assert sig["resident_id"] == resident["id"]
        assert sig["household_ref"] == resident["household_ref"], (
            "household_ref must be copied from the signer's profile, "
            f"got {sig['household_ref']}"
        )
        assert sig["request_id"] == req["id"]


class TestSignatureRetraction:
    def test_retract_unknown_signature_returns_404(self):
        """PRD §3.2: "A signature identifier that does not exist, or whose signature was already retracted, yields `ERR_SIGNATURE_NOT_FOUND`."

        Design: Corner/entities/retract_unknown_signature_returns_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.retract_signature(
            "99999999-8888-7777-6666-555555555555", TE
        )
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_NOT_FOUND)

    def test_duplicate_household_signature_rejected(self):
        """PRD §3.2: "each household may hold at most one live signature on a given request: a second signature from the same household fails with `ERR_DUPLICATE_HOUSEHOLD_SIGNATURE`."

        Design: Corner/validations/duplicate_household_signature_rejected
        """
        ctx = setup_petition_open(
            name="DupSig Ave", household_count=10, resident_prefix="dsig",
            resident_count=1, signatures=0,
        )
        req = ctx["request"]
        resident = ctx["residents"][0]
        sign_petition(req["id"], resident["id"])
        resp = api_client.sign_petition(
            req["id"], make_resident_headers(resident["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOUSEHOLD_SIGNATURE)
        assert get_request(req["id"])["signature_count"] == 1, (
            "the rejected second signature must not move signature_count"
        )


class TestPetitionDeadlineSweep:
    def test_petition_deadline_sweep_fails_open_petition(self):
        """PRD §3.2: "When the logical clock advances past a petition's `petition_deadline_at` while its `signature_count` is still below `required_signatures`, the petition-deadline sweep moves the request from `PETITION_OPEN` to `PETITION_FAILED`, a terminal stage."
        PRD §3.2: "Signatures are accepted only while the request remains `PETITION_OPEN` and the logical clock has not passed `petition_deadline_at`."

        Design: Corner/validations/petition_deadline_sweep_fails_open_petition
        """
        ctx = setup_petition_open(
            name="Late Ave", household_count=10, resident_prefix="late",
            resident_count=2, signatures=1,
        )
        req = ctx["request"]
        # Deadline is opened_at + 90 days = 2026-10-30T00:00:00Z; advance past it.
        set_clock("2026-11-01T00:00:00Z")
        swept = get_request(req["id"])
        assert swept["status"] == "PETITION_FAILED", (
            f"the sweep must fail the stalled petition, got {swept['status']}"
        )
        assert swept["signature_count"] == 1

        resp = api_client.sign_petition(
            req["id"], make_resident_headers(ctx["residents"][1]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert get_request(req["id"])["signature_count"] == 1
