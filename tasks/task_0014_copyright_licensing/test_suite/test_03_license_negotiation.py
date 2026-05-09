"""License creation and negotiation rounds (PRD §3.3)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_draft_work,
    create_offered_license,
    create_license_payload,
    submit_round,
    accept_offered_license,
    list_negotiation_rounds,
    list_audit_logs_filtered,
    assert_license,
    assert_negotiation_round,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# License creation: licensor must own the work; term well-formedness
# ---------------------------------------------------------------------------

class TestLicenseCreationGuards:
    """PRD §3.3: "The licensor is required, by referential check, to be
    either the work's primary_owner_id or one of the holders in co_owners;
    if the caller is neither, the request is rejected with ERR_FORBIDDEN."
    """

    def test_create_license_by_non_owner_rejected(self, api):
        """PRD §3.3: caller is neither primary_owner nor co_owner → ERR_FORBIDDEN."""
        rh_a = create_rights_holder(api, legal_name="Owner")
        rh_b = create_rights_holder(api, legal_name="Stranger")
        rh_c = create_rights_holder(api, legal_name="Licensee")
        work, _ = create_registered_work(api, owner=rh_a)
        # rh_b is neither primary_owner nor co_owner of the work.
        payload = create_license_payload(work_id=work["id"],
                                          licensor_id=rh_b["id"],
                                          licensee_id=rh_c["id"])
        headers = make_rights_holder_headers(rh_b["id"])
        resp = api.create_license(payload, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_license_term_start_after_term_end_rejected(self, api):
        """PRD §3.3: 'The license must respect term_start strictly before
        term_end ... otherwise the server returns ERR_INVALID_TERM.'"""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        payload = create_license_payload(
            work_id=work["id"],
            licensor_id=licensor["id"],
            licensee_id=licensee["id"],
            term_start="2099-12-31T00:00:00.000Z",
            term_end="2099-01-01T00:00:00.000Z",
        )
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.create_license(payload, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM.value)

    def test_create_license_initial_state_offered_round_one(self, api):
        """PRD §3.3: 'The license is created with status of OFFERED and
        current_round of 1; the server simultaneously persists a first
        NegotiationRound row whose round_number is 1, whose action is OFFER,
        and whose proposed_by_id is the licensor.'"""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        assert_license(license_data)
        assert license_data["status"] == "OFFERED"
        assert license_data["current_round"] == 1
        rounds = list_negotiation_rounds(api, license_data["id"])
        assert len(rounds) == 1
        first = rounds[0]
        assert first["round_number"] == 1
        assert first["action"] == "OFFER"
        assert first["proposed_by_id"] == licensor["id"]


# ---------------------------------------------------------------------------
# Counter-offer turn alternation
# ---------------------------------------------------------------------------

class TestCounterOfferTurns:
    """PRD §3.3: "The hard rule across all counters is turn alternation: the
    caller must be the *opposite* party from whoever submitted the previous
    round, where the opposite of the licensor is the licensee and vice versa.
    A caller who is the same party as the previous round's proposed_by_id is
    rejected with ERR_NOT_YOUR_TURN."
    """

    def test_counter_by_same_party_rejected(self, api):
        """PRD §3.3: licensor submitted OFFER, then licensor counters again →
        ERR_NOT_YOUR_TURN."""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        # Licensor (same party as OFFER) attempts a COUNTER → not their turn.
        headers = make_rights_holder_headers(licensor["id"])
        from test_helpers import round_payload
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="COUNTER",
                                                  clause_diff={"fixed_fee_cents": {"old": 100000, "new": 200000}},
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_NOT_YOUR_TURN.value)

    def test_counter_by_third_party_rejected(self, api):
        """PRD §3.3: 'A caller who is neither the licensor nor the licensee
        is rejected with ERR_FORBIDDEN before the turn check runs.'"""
        licensor = create_rights_holder(api, legal_name="L")
        licensee = create_rights_holder(api, legal_name="E")
        intruder = create_rights_holder(api, legal_name="X")
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        from test_helpers import round_payload
        headers = make_rights_holder_headers(intruder["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="COUNTER",
                                                  clause_diff={"fixed_fee_cents": {"old": 100000, "new": 200000}},
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_alternating_counters_increment_round_number(self, api):
        """PRD §3.3: 'A counter advances the license to COUNTERED, increments
        current_round by exactly one, persists the round.'

        # difficulty: non_linear_state_machine/license_negotiation_cycle
        """
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)

        # Round 2: licensee counters
        submit_round(api, license_data, licensee, action="COUNTER",
                       clause_diff={"fixed_fee_cents": {"old": 100000, "new": 200000}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "COUNTERED"
        assert license_data["current_round"] == 2

        # Round 3: licensor counters
        submit_round(api, license_data, licensor, action="COUNTER",
                       clause_diff={"fixed_fee_cents": {"old": 200000, "new": 150000}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "COUNTERED"
        assert license_data["current_round"] == 3

        # Round 4: licensee counters
        submit_round(api, license_data, licensee, action="COUNTER",
                       clause_diff={"revenue_share_bps": {"old": 1500, "new": 1800}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "COUNTERED"
        assert license_data["current_round"] == 4

        rounds = list_negotiation_rounds(api, license_data["id"])
        actions = [r["action"] for r in rounds]
        assert actions == ["OFFER", "COUNTER", "COUNTER", "COUNTER"], (
            f"PRD §3.3 (negotiation order): expected ['OFFER','COUNTER','COUNTER','COUNTER'], got {actions}"
        )

    def test_negotiation_cycle_returns_four_rounds_chronological(self, api):
        """PRD §3.3: 'Negotiation history is enumerated in chronological order
        through the rounds-list endpoint.'

        # difficulty: non_linear_state_machine/license_negotiation_cycle
        """
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        submit_round(api, license_data, licensee, action="COUNTER",
                       clause_diff={"fixed_fee_cents": {"old": 100000, "new": 200000}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        submit_round(api, license_data, licensor, action="COUNTER",
                       clause_diff={"fixed_fee_cents": {"old": 200000, "new": 175000}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        submit_round(api, license_data, licensee, action="COUNTER",
                       clause_diff={"revenue_share_bps": {"old": 1500, "new": 1700}})

        rounds = list_negotiation_rounds(api, license_data["id"])
        assert len(rounds) == 4, f"Expected 4 rounds, got {len(rounds)}"
        round_numbers = [r["round_number"] for r in rounds]
        assert round_numbers == sorted(round_numbers), (
            "PRD §3.3: rounds must be returned in chronological order"
        )


# ---------------------------------------------------------------------------
# Acceptance: requires REGISTERED Work + opposite-party caller
# ---------------------------------------------------------------------------

class TestLicenseAcceptance:
    """PRD §3.3: "Independently, the work must currently be in REGISTERED
    (any other state yields ERR_WORK_NOT_REGISTERED)."

    PRD §3.3: "From OFFERED to ACCEPTED, the licensee is the one who
    accepts; the caller must therefore be the licensee_id (otherwise
    ERR_NOT_YOUR_TURN)."
    """

    def test_accept_on_offered_by_licensee_succeeds(self, api):
        """PRD §3.3: licensee accepts OFFERED → ACCEPTED, pinned_work_version
        captured."""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        result = accept_offered_license(api, license_data, licensee)
        assert result["status"] == "ACCEPTED"
        assert result["pinned_work_version"] is not None, (
            "PRD §3.3: 'On a successful accept the server captures the work's "
            "current version into the license's pinned_work_version.'"
        )

    def test_accept_by_licensor_on_offered_rejected(self, api):
        """PRD §3.3: 'From OFFERED to ACCEPTED, the licensee is the one who
        accepts; the caller must therefore be the licensee_id (otherwise
        ERR_NOT_YOUR_TURN).'"""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        from test_helpers import round_payload
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="ACCEPT",
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_NOT_YOUR_TURN.value)

    def test_accept_on_unregistered_work_rejected(self, api):
        """PRD §3.3: 'the work must currently be in REGISTERED (any other
        state yields ERR_WORK_NOT_REGISTERED).'

        # difficulty: cross_entity_state_dependency/license_accept_requires_work_registered
        """
        licensor, licensee = create_two_rights_holders(api)
        # Work is in DRAFT (NOT registered).
        work = create_draft_work(api, licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        from test_helpers import round_payload
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="ACCEPT",
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_REGISTERED.value)

    def test_accept_on_unregistered_work_rejected_after_counter(self, api):
        """PRD §3.3: COUNTERED → ACCEPTED also requires REGISTERED Work.

        # difficulty: cross_entity_state_dependency/license_accept_requires_work_registered
        """
        licensor, licensee = create_two_rights_holders(api)
        work = create_draft_work(api, licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        # Licensee counters
        submit_round(api, license_data, licensee, action="COUNTER",
                       clause_diff={"fixed_fee_cents": {"old": 100000, "new": 150000}})
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        # Licensor (opposite party) tries to ACCEPT, but work is DRAFT.
        from test_helpers import round_payload
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="ACCEPT",
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_REGISTERED.value)


# ---------------------------------------------------------------------------
# Withdraw — licensor only
# ---------------------------------------------------------------------------

class TestLicenseWithdraw:
    """PRD §3.3: "A NegotiationRound with action of WITHDRAW from OFFERED or
    COUNTERED transitions the license to the terminal WITHDRAWN state and
    writes an AuditLog. Withdraw is restricted to the licensor (ERR_FORBIDDEN
    otherwise)."
    """

    def test_withdraw_from_offered_by_licensor_succeeds(self, api):
        """PRD §3.3: licensor WITHDRAW from OFFERED → WITHDRAWN."""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        from test_helpers import round_payload
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="WITHDRAW",
                                                  version=license_data["version"]),
                                  headers)
        validate_success(resp, expected_status=201)
        # Re-read License
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "WITHDRAWN"

    def test_withdraw_by_licensee_rejected(self, api):
        """PRD §3.3: 'Withdraw is restricted to the licensor (ERR_FORBIDDEN
        otherwise).'"""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        from test_helpers import round_payload
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.submit_round(license_data["id"],
                                  round_payload(action="WITHDRAW",
                                                  version=license_data["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
