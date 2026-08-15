"""Supplier onboarding, program constraint validation, program lifecycle
preconditions, enrollment gates, and program amendment OCC.

Covers program creation constraints (tier schedule shape, exclusivity
threshold, enum values, program-code uniqueness), supplier/program
cross-entity state dependencies, termination/deactivation preconditions,
enrollment member-active gate, and optimistic concurrency on amendment.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    bootstrap_coop,
    create_pending_member,
    create_active_member,
    create_supplier,
    create_onboarded_supplier,
    create_draft_program,
    create_open_program,
    enroll_member,
    create_supplier_program_payload,
    amend_supplier_program_payload,
    make_supplier_rep_headers,
)


class TestProgramCreationConstraints:
    def test_invalid_holdback_policy_enum_returns_invalid_request(
        self, api, admin_headers
    ):
        """PRD §3.3: "A `SupplierRep` or `CoopAdmin` creates a program beneath
        its supplier with a supplier-scoped `program_code`, an
        `exclusivity_required` flag, an `exclusivity_threshold_pct`, a
        `tier_schedule`, and a `holdback_policy` of `FLAT` or `RISK_ADJUSTED`."
        PRD §2.9: "any request whose body fails schema validation — a missing
        required field, a value of the wrong type, or a negative amount where
        a positive one is required — is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/supplier_program_create_with_invalid_enum_returns_invalid_request
        """
        bootstrap_coop()
        supplier = create_supplier()
        payload = create_supplier_program_payload(
            program_code="P-BAD", holdback_policy="BOGUS"
        )
        resp = api.create_supplier_program(
            supplier["id"], payload, make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_tier_schedule_rejected_at_create(self, api, admin_headers):
        """PRD §3.3: "the `tier_schedule` must be non-empty and ascending by
        `min_qty` with every `rate_bps` between 0 and 10,000 inclusive, else
        `ERR_INVALID_TIER_SCHEDULE` (HTTP 422)".

        A schedule whose tiers are not ascending by min_qty violates the
        shape rule at creation time.

        Design: Corner/validations/invalid_tier_schedule_rejected_at_create
        """
        bootstrap_coop()
        supplier = create_supplier()
        payload = create_supplier_program_payload(
            program_code="P-BADT",
            tier_schedule=[
                {"min_qty": 100, "rate_bps": 500},
                {"min_qty": 50, "rate_bps": 200},
            ],
        )
        resp = api.create_supplier_program(
            supplier["id"], payload, make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIER_SCHEDULE)

    def test_invalid_exclusivity_threshold_rejected(self, api, admin_headers):
        """PRD §3.3: "whenever `exclusivity_required` is true the
        `exclusivity_threshold_pct` must sit between 1 and 100 inclusive,
        else `ERR_INVALID_EXCLUSIVITY` (HTTP 422)".

        exclusivity_required=true with threshold 0 is below the inclusive
        [1, 100] band.

        Design: Corner/validations/invalid_exclusivity_threshold_rejected
        """
        bootstrap_coop()
        supplier = create_supplier()
        payload = create_supplier_program_payload(
            program_code="P-BADX",
            exclusivity_required=True,
            exclusivity_threshold_pct=0,
        )
        resp = api.create_supplier_program(
            supplier["id"], payload, make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_EXCLUSIVITY)

    def test_duplicate_program_code_rejected(self, api, admin_headers):
        """PRD §3.3: "the `program_code` must not collide with another of the
        same supplier's programs that has not reached `TERMINATED`, else
        `ERR_DUPLICATE_PROGRAM_CODE` (HTTP 409)."

        Design: Corner/validations/duplicate_program_code_rejected
        """
        bootstrap_coop()
        supplier = create_supplier()
        headers = make_supplier_rep_headers(supplier["id"])
        first = api.create_supplier_program(
            supplier["id"], create_supplier_program_payload(program_code="P-DUP"), headers
        )
        validate_success(first, 201)
        resp = api.create_supplier_program(
            supplier["id"],
            create_supplier_program_payload(
                program_code="P-DUP",
                tier_schedule=[{"min_qty": 0, "rate_bps": 200}],
                holdback_policy="RISK_ADJUSTED",
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROGRAM_CODE)


class TestProgramLifecyclePreconditions:
    def test_program_open_blocked_when_supplier_not_onboarded(
        self, api, admin_headers
    ):
        """PRD §3.3: "its parent supplier must be `ONBOARDED` — opening a
        program under a `PROSPECT` or `INACTIVE` supplier fails with
        `ERR_SUPPLIER_NOT_ONBOARDED` (HTTP 409)."

        The program is created while the supplier is still PROSPECT; the open
        attempt is rejected and the program remains in DRAFT.

        Design: Difficulty/cross_entity_state_dependency/program_open_blocked_when_supplier_not_onboarded
        """
        bootstrap_coop()
        supplier = create_supplier()  # PROSPECT — never onboarded
        program = create_draft_program(supplier, program_code="P-CE1")
        assert program["status"] == "DRAFT"

        resp = api.open_program(
            program["id"], make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ONBOARDED)

        after = get_success_data(api.get_supplier_program(program["id"], admin_headers))
        assert after["status"] == "DRAFT", "rejected open must not move the program"

    def test_program_open_succeeds_once_supplier_onboarded(self, api, admin_headers):
        """PRD §3.3: "Opening moves a `DRAFT` program to `OPEN`, and re-runs
        the full gauntlet: the program must currently be `DRAFT` (else
        `ERR_INVALID_STATE`), its tier schedule and exclusivity threshold are
        re-validated exactly as at creation, and its parent supplier must be
        `ONBOARDED` — opening a program under a `PROSPECT` or `INACTIVE`
        supplier fails with `ERR_SUPPLIER_NOT_ONBOARDED` (HTTP 409)."

        The same program that was blocked while the supplier was PROSPECT
        opens successfully once the supplier is ONBOARDED — confirming the
        dependency is on the parent supplier's state, not on the program.

        Design: Difficulty/cross_entity_state_dependency/program_open_blocked_when_supplier_not_onboarded
        """
        bootstrap_coop()
        supplier = create_supplier()
        program = create_draft_program(supplier, program_code="P-CE1B")
        blocked = api.open_program(
            program["id"], make_supplier_rep_headers(supplier["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_SUPPLIER_NOT_ONBOARDED)

        get_success_data(api.onboard_supplier(supplier["id"], admin_headers))
        opened = validate_success(
            api.open_program(program["id"], make_supplier_rep_headers(supplier["id"])),
            200,
        )
        assert opened["status"] == "OPEN"
        assert opened["version"] == program["version"] + 1

    def test_supplier_deactivate_blocked_with_open_program(self, api, admin_headers):
        """PRD §3.3: "Deactivation moves an `ONBOARDED` supplier to
        `INACTIVE`, but only while none of its programs is `OPEN`,
        `CLOSED_TO_NEW`, or `REOPENED`; a live program blocks deactivation
        with `ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS` (HTTP 409)".

        Design: Corner/state_machines/supplier_deactivate_blocked_with_open_program
        """
        bootstrap_coop()
        supplier = create_onboarded_supplier()
        create_open_program(supplier, program_code="P-DEACT")
        resp = api.deactivate_supplier(supplier["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS)
        after = get_success_data(api.get_supplier(supplier["id"], admin_headers))
        assert after["status"] == "ONBOARDED"

    def test_supplier_program_terminate_blocked_with_active_enrollments(
        self, api, admin_headers
    ):
        """PRD §3.3: "From `OPEN`, `CLOSED_TO_NEW`, or `REOPENED`,
        termination is permitted only while the program has no enrollments in
        `ACTIVE` or `SUSPENDED` status — live enrollments block it with
        `ERR_PROGRAM_HAS_ENROLLMENTS` (HTTP 409)."

        Design: Corner/state_machines/supplier_program_terminate_blocked_with_active_enrollments
        """
        bootstrap_coop()
        member = create_active_member()
        supplier = create_onboarded_supplier()
        program = create_open_program(supplier, program_code="P-TERM")
        enroll_member(member, program)
        resp = api.terminate_program(
            program["id"], make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_ENROLLMENTS)
        after = get_success_data(api.get_supplier_program(program["id"], admin_headers))
        assert after["status"] == "OPEN"


class TestEnrollmentGates:
    def test_enrollment_blocked_when_member_pending(self, api, admin_headers):
        """PRD §3.4: "Two business gates then apply, in pipeline order: the
        member must be `ACTIVE` — a `PENDING`, `SUSPENDED`, or `CHURNED`
        member fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)".

        A PENDING member (never activated) cannot be enrolled.

        Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_when_member_not_active
        """
        bootstrap_coop()
        member = create_pending_member()  # stays PENDING
        supplier = create_onboarded_supplier()
        program = create_open_program(supplier, program_code="P-CE2")
        resp = api.create_enrollment(
            {"member_id": member["id"], "program_id": program["id"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_enrollment_blocked_when_member_suspended(self, api, admin_headers):
        """PRD §3.4: "Two business gates then apply, in pipeline order: the
        member must be `ACTIVE` — a `PENDING`, `SUSPENDED`, or `CHURNED`
        member fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409) — and the
        program must be `OPEN` or `REOPENED`, with any other program status
        failing as `ERR_PROGRAM_NOT_OPEN` (HTTP 409)."

        A member activated and then suspended is equally blocked — the gate
        depends on the member's live status, not on prior activation.

        Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_when_member_not_active
        """
        bootstrap_coop()
        member = create_active_member()
        supplier = create_onboarded_supplier()
        program = create_open_program(supplier, program_code="P-CE2B")
        get_success_data(api.suspend_member(member["id"], admin_headers))
        resp = api.create_enrollment(
            {"member_id": member["id"], "program_id": program["id"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)


class TestExistenceBeforeBusinessConstraints:
    def test_missing_supplier_yields_not_found_even_with_invalid_tier_schedule(
        self, api, admin_headers
    ):
        """PRD §2.9: "Every request is subjected to the checks below, in
        exactly this order; the first failing check short-circuits the rest,
        and its error is the one returned."
        PRD §2.9: "Resource ids templated into the URL path must resolve to
        existing entities, validated left to right along the path, on every
        resource endpoint. Failure: `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.9: "A program's `tier_schedule` must be non-empty, ordered
        ascending by `min_qty`, and every `rate_bps` must lie between 0 and
        10,000 inclusive. Applies to program creation, program amendment,
        and program opening. Failure: `ERR_INVALID_TIER_SCHEDULE` (HTTP
        422)."

        When the path's supplier id does not resolve AND the body's tier
        schedule is non-ascending, path existence fires first.

        Design: Difficulty/priority_pair_validation_conflict/existence_trumps_business_constraint_on_program_create
        """
        bootstrap_coop()
        ghost = NON_EXISTENT_UUID
        payload = create_supplier_program_payload(
            program_code="P-X",
            tier_schedule=[
                {"min_qty": 100, "rate_bps": 500},
                {"min_qty": 0, "rate_bps": 200},
            ],
        )
        resp = api.create_supplier_program(
            ghost, payload, make_supplier_rep_headers(ghost)
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_supplier_yields_not_found_and_creates_nothing(
        self, api, admin_headers
    ):
        """PRD §2.10: "Path-templated ids are validated left to right — the
        parent must exist before the child beneath it is examined — and the
        first id that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404)."

        Even with an otherwise fully valid program payload, the missing
        parent supplier short-circuits creation and no program is persisted.

        Design: Difficulty/priority_pair_validation_conflict/existence_trumps_business_constraint_on_program_create
        """
        bootstrap_coop()
        ghost = NON_EXISTENT_UUID
        resp = api.create_supplier_program(
            ghost,
            create_supplier_program_payload(program_code="P-VALID"),
            make_supplier_rep_headers(ghost),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        data, meta = validate_paginated(api.list_supplier_programs(admin_headers))
        assert meta["total_count"] == 0, f"no program may be created, got {data}"


class TestProgramAmendmentOcc:
    def test_program_amend_stale_version_rejected(self, api, admin_headers):
        """PRD §2.8: "If the program's current `version` has moved past that
        value — for instance because another `SupplierRep` completed a
        renegotiation round that supersedes the terms the caller saw — the
        amendment is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412),
        and nothing is written."
        PRD §3.3: "A successful amendment may update the `tier_schedule`,
        `exclusivity_required`, `exclusivity_threshold_pct`, or
        `holdback_policy` — the tier schedule and exclusivity threshold are
        re-validated under the same rules as creation — and increments both
        `negotiation_round` and the program's `version`."

        After a first successful amendment bumps the program version, a
        second amendment replaying the originally observed version is
        rejected and negotiation_round reflects only the successful round.

        Design: Corner/endpoints/program_amend_stale_version_rejected
        """
        bootstrap_coop()
        supplier = create_supplier()
        headers = make_supplier_rep_headers(supplier["id"])
        program = create_draft_program(supplier, program_code="P-OCC")
        observed_version = program["version"]

        amended = validate_success(
            api.amend_supplier_program(
                program["id"],
                amend_supplier_program_payload(
                    observed_version, holdback_policy="RISK_ADJUSTED"
                ),
                headers,
            ),
            200,
        )
        assert amended["negotiation_round"] == program["negotiation_round"] + 1
        assert amended["version"] == observed_version + 1

        stale = api.amend_supplier_program(
            program["id"],
            amend_supplier_program_payload(observed_version, holdback_policy="FLAT"),
            headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

        after = get_success_data(api.get_supplier_program(program["id"], admin_headers))
        assert after["negotiation_round"] == 1, "rejected amendment writes nothing"
        assert after["version"] == observed_version + 1
