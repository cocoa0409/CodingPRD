"""Participants, enrollment creation/election, activation, deposits, ledger."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_enrollment,
    assert_ledger_entry,
    assert_participant,
    assert_shares_equal,
    create_active_plan,
    create_enrollment_payload,
    create_participant_payload,
    create_plan,
    deposit_shares,
    enroll_participant,
    get_enrollment,
    get_success_data,
    is_valid_uuid,
    list_fees,
    list_ledger_entries,
    make_participant_headers,
    register_participant,
    setup_active_enrollment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestParticipantCreation:
    def test_participant_create_returns_stored_fields(self, api):
        """PRD §3.2: "A `PlanAdmin` registers each investor as a participant,
        supplying `full_name` and `email` — the email must be unique across
        participants — and optionally setting `fee_waiver_eligible`, which
        defaults to false and, when true, causes OCP fees for that participant's
        enrollments to be automatically waived (§2.10)."
        PRD §4: "Operations that create a new resource return a `201 Created`
        status code."

        Design: Corner/entities/participant_create_returns_stored_fields
        """
        resp = api.create_participant(
            create_participant_payload(full_name="Pat C", email="pc@x.com"), ADMIN)
        participant = validate_success(resp, expected_status=201)
        assert_participant(participant)
        assert participant["full_name"] == "Pat C"
        assert participant["email"] == "pc@x.com"
        assert participant["fee_waiver_eligible"] is False, \
            "fee_waiver_eligible defaults to false when omitted"

    def test_participant_create_injected_id_input_ignored(self, api):
        """PRD §2.6: "Every primary resource carries a standard set of
        system-managed fields: `id`, a server-minted UUID with no type prefix"

        Design: Corner/entities/participant_create_injected_id_input_ignored
        """
        injected = "11111111-2222-4333-8444-555555555555"
        payload = create_participant_payload(full_name="Pat I", email="pi@x.com")
        payload["id"] = injected
        resp = api.create_participant(payload, ADMIN)
        participant = validate_success(resp, expected_status=201)
        assert is_valid_uuid(participant["id"]), "server mints its own UUID"
        assert participant["id"] != injected, \
            "a client-supplied id is ignored in favor of the server-minted one"


class TestEnrollmentCreation:
    def test_enrollment_create_starts_pending(self, api):
        """PRD §3.2: "The created enrollment records its owner through
        `participant_id` and the plan it belongs to through its `plan_id`, and
        it starts in `PENDING`."
        PRD §2.9: "An enrollment's `share_balance` is a derived figure: the sum
        of `quantity` over every ledger entry of the enrollment, kept at four
        decimal places."

        Design: Corner/entities/enrollment_create_starts_pending
        """
        plan = create_active_plan(issuer_name="Pend Corp", ticker="PND",
                                  name="PND DRIP")
        participant = register_participant("Pat N2", "pn2@x.com")
        resp = api.create_enrollment(
            plan["id"], create_enrollment_payload(participant["id"], "CASH_ONLY"),
            make_participant_headers(participant["id"]))
        enrollment = validate_success(resp, expected_status=201)
        assert_enrollment(enrollment)
        assert enrollment["status"] == "PENDING"
        assert enrollment["participant_id"] == participant["id"]
        assert enrollment["plan_id"] == plan["id"]
        assert_shares_equal(enrollment["share_balance"], "0.0000")
        assert enrollment["total_cost_basis_cents"] == 0

    def test_enrollment_create_invalid_enum_election(self, api):
        """PRD §2.11: "then request body shape — required fields present, enum
        members valid, and numeric ranges sane, such as strictly positive
        quantities and amounts and the participation-election percentage rules —
        reported as `ERR_VALIDATION` (HTTP 400)."
        PRD §3.2: "an `election` of `FULL_REINVEST`, `PARTIAL_REINVEST`, or
        `CASH_ONLY`"

        Design: Corner/entities/enrollment_create_invalid_enum_election
        """
        plan = create_active_plan(issuer_name="Enum Corp", ticker="ENU",
                                  name="ENU DRIP")
        participant = register_participant("Pat E", "pe@x.com")
        resp = api.create_enrollment(
            plan["id"], create_enrollment_payload(participant["id"], "HALF"),
            make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_election_partial_requires_pct_rejected(self, api):
        """PRD §3.2: "The election payload rules are strict and violations are
        rejected with `ERR_INVALID_ELECTION` (HTTP 422): when the election is
        `PARTIAL_REINVEST`, `reinvest_pct` must be present and strictly greater
        than zero and strictly less than one; for either other election,
        `reinvest_pct` must be absent entirely."

        Design: Corner/validations/election_partial_requires_pct_rejected
        """
        plan = create_active_plan(issuer_name="El Corp", ticker="ELC",
                                  name="ELC DRIP")
        participant = register_participant("Pat El", "pel@x.com")
        payload = {"participant_id": participant["id"],
                   "election": "PARTIAL_REINVEST"}
        resp = api.create_enrollment(plan["id"], payload,
                                     make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ELECTION)

    def test_already_enrolled_duplicate_rejected(self, api):
        """PRD §3.2: "One participant may hold only one non-terminal enrollment
        per plan — a second enrollment while one exists in `PENDING`, `ACTIVE`,
        or `SUSPENDED` is rejected with `ERR_ALREADY_ENROLLED` (HTTP 409)."

        Design: Corner/validations/already_enrolled_duplicate_rejected
        """
        plan = create_active_plan(issuer_name="Dup Corp", ticker="DUP",
                                  name="DUP DRIP")
        participant = register_participant("Pat D", "pd@x.com")
        enroll_participant(plan["id"], participant["id"], "FULL_REINVEST")
        resp = api.create_enrollment(
            plan["id"], create_enrollment_payload(participant["id"], "CASH_ONLY"),
            make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_ENROLLED)


class TestEnrollmentActivation:
    def test_activate_assesses_enrollment_fee(self, api):
        """PRD §3.2: "Activation assesses the one-time enrollment fee — a fee
        assessment of type `ENROLLMENT` whose `computed_cents` equals the plan's
        `enrollment_fee_cents`, recorded with `ACTIVATION` provenance — and
        increments the enrollment's `version`."
        PRD §2.10: "`charged_cents`, which is 0 when the assessment is waived
        and otherwise equals `computed_cents`."

        Design: Corner/state_machines/activate_assesses_enrollment_fee
        """
        plan = create_active_plan(issuer_name="FeeCorp2", ticker="FE2",
                                  name="FE2 DRIP")
        participant = register_participant("Pat F2", "pf2@x.com")
        enrollment = enroll_participant(plan["id"], participant["id"], "CASH_ONLY")
        get_success_data(api.activate_enrollment(enrollment["id"], ADMIN))
        fees = list_fees(enrollment["id"])
        assert len(fees) == 1, "activation creates exactly one fee assessment"
        fee = fees[0]
        assert fee["fee_type"] == "ENROLLMENT"
        assert fee["computed_cents"] == 1000
        assert fee["charged_cents"] == 1000
        assert fee["waived"] is False

    def test_enrollment_second_activate_rejected(self, api):
        """PRD §2.8: "Any state-machine trigger attempted from a state where it
        is not defined — including any action against an entity already in a
        terminal state, or repeating a transition already taken — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: "Activation assesses the one-time enrollment fee — a fee
        assessment of type `ENROLLMENT` whose `computed_cents` equals the plan's
        `enrollment_fee_cents`, recorded with `ACTIVATION` provenance — and
        increments the enrollment's `version`."

        Design: Corner/state_machines/enrollment_second_activate_rejected
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Twice Corp", "ticker": "TWC",
                            "name": "TWC DRIP"},
            participant_email="ptw@x.com")
        resp = api.activate_enrollment(enrollment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fees = [f for f in list_fees(enrollment["id"])
                if f["fee_type"] == "ENROLLMENT"]
        assert len(fees) == 1, "the rejected repeat activation adds no second fee"


class TestDepositsAndLedger:
    def test_ledger_entry_immutable_no_version_field(self, api):
        """PRD §2.6: "One entity is exempt: a share ledger entry is an immutable
        record and carries only `id` and `created_at` — both `updated_at` and
        `version` are absent on ledger entries."
        PRD §3.3: "The deposit creates an `INITIAL` ledger entry — positive
        `quantity`, `price_cents` set to the supplied cost, provenance `DEPOSIT`"

        Design: Corner/entities/ledger_entry_immutable_no_version_field
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Log Corp", "ticker": "LOG",
                            "name": "LOG DRIP"},
            participant_email="pl2@x.com")
        deposit_shares(enrollment["id"], 3.0, 1000)
        entries = list_ledger_entries(enrollment["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert_ledger_entry(entry)
        assert entry["entry_type"] == "INITIAL"
        assert_shares_equal(entry["quantity"], "3.0000")
        assert entry["price_cents"] == 1000

    def test_deposit_immediately_visible_in_enrollment(self, api):
        """PRD §3.3: "alongside an `INITIAL` tax lot, and then recomputes the
        enrollment's derived position: `share_balance` becomes the sum of ledger
        quantities per §2.9, and `total_cost_basis_cents` is recomputed per the
        tax-lot aggregation of §2.9."

        Design: Corner/consistency_model/deposit_immediately_visible_in_enrollment
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Imm Corp", "ticker": "IMM",
                            "name": "IMM DRIP"},
            participant_email="pim@x.com")
        deposit_shares(enrollment["id"], 20.0, 1000)
        fetched = get_enrollment(enrollment["id"])
        assert_shares_equal(fetched["share_balance"], "20.0000")
        assert fetched["total_cost_basis_cents"] == 20000


class TestEnrollmentPlanActiveGate:
    def test_enrollment_activation_requires_plan_active(self, api):
        """PRD §2.8: "Nine operations require the plan to be `ACTIVE` and are
        otherwise rejected with `ERR_PLAN_NOT_ACTIVE` (HTTP 409): creating an
        enrollment in the plan, activating an enrollment, declaring a dividend,
        executing a dividend's reinvestment, creating a purchase window, opening
        a purchase window, submitting a purchase order, creating a transfer
        instruction, and executing a transfer instruction."

        Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_plan_active
        """
        plan = create_active_plan(issuer_name="Guard Corp", ticker="GRD",
                                  name="GRD DRIP")
        participant = register_participant("Pat G", "pg2@x.com")
        enrollment = enroll_participant(plan["id"], participant["id"],
                                        "FULL_REINVEST")
        get_success_data(api.suspend_plan(plan["id"], ADMIN))
        resp = api.activate_enrollment(enrollment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        assert get_enrollment(enrollment["id"])["status"] == "PENDING", \
            "the rejected activation leaves the enrollment PENDING"

    def test_enrollment_create_on_draft_plan_requires_plan_active(self, api):
        """PRD §2.8: "Nine operations require the plan to be `ACTIVE` and are
        otherwise rejected with `ERR_PLAN_NOT_ACTIVE` (HTTP 409): creating an
        enrollment in the plan, activating an enrollment, declaring a dividend,
        executing a dividend's reinvestment, creating a purchase window, opening
        a purchase window, submitting a purchase order, creating a transfer
        instruction, and executing a transfer instruction."
        PRD §3.1: "A new plan starts in `DRAFT` status."

        Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_plan_active
        """
        plan = create_plan(issuer_name="Guard Corp", ticker="GRD",
                           name="GRD DRIP")
        participant = register_participant("Pat G", "pg2@x.com")
        resp = api.create_enrollment(
            plan["id"],
            create_enrollment_payload(participant["id"], "FULL_REINVEST"),
            make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


class TestElectionChangeOcc:
    def test_occ_enrollment_election_stale_version(self, api):
        """PRD §2.7: "A `PATCH /drip/enrollments/{id}/election` request must
        carry `expected_enrollment_version`, holding the value of the
        enrollment's `version` the client last observed. A mismatch with the
        enrollment's current `version` — left behind by an intervening mutation
        such as a suspension cascade or a prior election change — is rejected
        with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), preventing the client
        from overwriting state it has not observed."

        Design: Corner/cross_cutting_layers/occ_enrollment_election_stale_version
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Occ2 Corp", "ticker": "OC2",
                            "name": "OC2 DRIP"},
            participant_email="po2b@x.com")
        observed_version = get_enrollment(enrollment["id"])["version"]
        owner = make_participant_headers(participant["id"])

        first = api.change_election(enrollment["id"], {
            "expected_enrollment_version": observed_version,
            "election": "CASH_ONLY",
        }, owner)
        changed = validate_success(first)
        assert changed["election"] == "CASH_ONLY"
        assert changed["version"] == observed_version + 1, \
            "a successful election change increments the version by exactly 1"

        replay = api.change_election(enrollment["id"], {
            "expected_enrollment_version": observed_version,
            "election": "FULL_REINVEST",
        }, owner)
        validate_error(replay, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION)


class TestEnrollmentRbac:
    def test_participant_cannot_activate_enrollment(self, api):
        """PRD §3.2: "Activation is an administrative act: a `PlanAdmin`
        activates a `PENDING` enrollment of an `ACTIVE` plan, moving it to
        `ACTIVE`."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or a `Participant`-role request that touches a resource owned by a
        different participant — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/participant_cannot_activate_enrollment
        """
        plan = create_active_plan(issuer_name="Act Corp", ticker="ACT",
                                  name="ACT DRIP")
        participant = register_participant("Pat Ac", "pac@x.com")
        enrollment = enroll_participant(plan["id"], participant["id"],
                                        "FULL_REINVEST")
        resp = api.activate_enrollment(
            enrollment["id"], make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_enrollment(enrollment["id"])["status"] == "PENDING"

    def test_participant_reads_other_enrollment_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint — or a `Participant`-role request that touches a resource
        owned by a different participant — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §2.1: "an enrollment is owned through its `participant_id`"

        Design: Corner/validations/participant_reads_other_enrollment_forbidden
        """
        plan = create_active_plan(issuer_name="Own Corp", ticker="OWN",
                                  name="OWN DRIP")
        owner = register_participant("Pat O1", "po1@x.com")
        enrollment = enroll_participant(plan["id"], owner["id"], "FULL_REINVEST")
        other = register_participant("Pat O2", "po2@x.com")
        resp = api.get_enrollment(enrollment["id"],
                                  make_participant_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
