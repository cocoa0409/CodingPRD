"""Society registration lifecycle, copyright recordals, the ISWC assignment
side effect, and the confirmed-split-set gate on submission."""
from test_helpers import (
    ApiErrorId,
    create_society,
    create_society_registration_payload,
    create_split_set,
    create_work,
    create_writer,
    get_work,
    setup_confirmed_split_set,
    setup_registered_work,
    submit_split_set,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COPYRIGHT


def _draft_registration(api, work_id, society_id):
    return validate_success(
        api.create_society_registration(
            create_society_registration_payload(work_id, society_id),
            COPYRIGHT),
        201)


class TestSubmissionGate:
    def test_registration_submit_rejected_without_confirmed_split_set(self, api):
        """PRD §3.2: "Two cross-entity gates guard submission: the work's `copyright_status` must not be `TERMINATED` (else `ERR_WORK_RIGHTS_TERMINATED`), and the work must have a SplitSet in `CONFIRMED` status (else `ERR_NO_CONFIRMED_SPLIT_SET`) — a publisher does not register a work with a society before the ownership splits are settled."

        Design: Difficulty/cross_entity_state_dependency/society_registration_submit_gated_on_confirmed_split_set
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Gated Song")
        # Split set exists but is only DRAFT — never submitted or confirmed.
        create_split_set(work["id"], [(writer["id"], 10000)])
        society = create_society()
        registration = _draft_registration(api, work["id"], society["id"])

        resp = api.submit_society_registration(registration["id"], COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_SPLIT_SET)

    def test_registration_submit_succeeds_once_split_set_confirmed(self, api):
        """PRD §3.2: "the work must have a SplitSet in `CONFIRMED` status (else `ERR_NO_CONFIRMED_SPLIT_SET`) — a publisher does not register a work with a society before the ownership splits are settled."
        PRD §3.2: "Once any registration for a work enters `SUBMITTED`, the work's `registration_status` bubbles up from `UNREGISTERED` to `PENDING_SOCIETY`."

        Design: Difficulty/cross_entity_state_dependency/society_registration_submit_gated_on_confirmed_split_set
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Gated Song 2")
        split_set = create_split_set(work["id"], [(writer["id"], 10000)])
        society = create_society()
        registration = _draft_registration(api, work["id"], society["id"])

        # The gate opens once the same call is retried with a CONFIRMED set.
        submit_split_set(split_set["id"])
        from test_helpers import confirm_all_split_lines
        confirm_all_split_lines(split_set["id"])

        submitted = validate_success(
            api.submit_society_registration(registration["id"], COPYRIGHT))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None

        work_after = get_work(work["id"])
        assert work_after["registration_status"] == "PENDING_SOCIETY", (
            "submission must bubble the work up to PENDING_SOCIETY, "
            f"got {work_after['registration_status']}")


class TestRegistrationCycle:
    def test_society_registration_reject_resubmit_cycle(self, api):
        """PRD §3.2: "Rejection moves it to `REJECTED` and captures the supplied `reason` into `rejection_reason`; if that rejection leaves no other registration of the same work in `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, or `REGISTERED`, the work's `registration_status` falls back from `PENDING_SOCIETY` to `UNREGISTERED`."
        PRD §3.2: "A rejected registration is not terminal: resubmitting moves it from `REJECTED` back to `SUBMITTED`, clears `rejection_reason` to null, refreshes `submitted_at`, and re-applies both cross-entity gates (non-terminated work, confirmed split set) exactly as on a first submission."

        Design: Corner/state_machines/society_registration_reject_resubmit_cycle
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Cycle Reg Song")
        split_set = create_split_set(work["id"], [(writer["id"], 10000)])
        submit_split_set(split_set["id"])
        from test_helpers import confirm_all_split_lines
        confirm_all_split_lines(split_set["id"])
        society = create_society()
        registration = _draft_registration(api, work["id"], society["id"])
        validate_success(
            api.submit_society_registration(registration["id"], COPYRIGHT))

        rejected = validate_success(api.reject_society_registration(
            registration["id"], "metadata mismatch", COPYRIGHT))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "metadata mismatch"
        assert get_work(work["id"])["registration_status"] == "UNREGISTERED", (
            "with no live registrations left the work falls back to "
            "UNREGISTERED")

        resubmitted = validate_success(
            api.submit_society_registration(registration["id"], COPYRIGHT))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["rejection_reason"] is None, (
            "resubmit clears rejection_reason to null")
        assert get_work(work["id"])["registration_status"] == "PENDING_SOCIETY"

    def test_society_registration_acknowledge_from_draft_rejected(self, api):
        """PRD §3.2: "From `SUBMITTED`, the society's response is recorded in one of two directions. Acknowledgement moves the registration to `ACKNOWLEDGED` and captures the society-assigned `society_work_number` from the call."
        PRD §2.8: "5. **State preconditions** — the target entity's state machine permits the trigger, and cross-entity state gates hold (a confirmed split set exists where required; an amended statement is in the right state), else `ERR_INVALID_STATE_TRANSITION`, `ERR_NO_CONFIRMED_SPLIT_SET`, `ERR_AMENDED_STATEMENT_NOT_FINAL`, or `ERR_STATEMENT_ALREADY_SUPERSEDED`."

        Design: Corner/state_machines/society_registration_acknowledge_from_draft_rejected
        """
        work = create_work(title="Draft Reg Song")
        society = create_society()
        registration = _draft_registration(api, work["id"], society["id"])
        assert registration["status"] == "DRAFT"

        resp = api.acknowledge_society_registration(
            registration["id"], "880000999", COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_society_registration_terminal_lockdown(self, api):
        """PRD §3.2: "Submitting from any state other than `DRAFT` or `REJECTED` is rejected with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.2: "From `SUBMITTED`, the society's response is recorded in one of two directions. Acknowledgement moves the registration to `ACKNOWLEDGED` and captures the society-assigned `society_work_number` from the call. Rejection moves it to `REJECTED` and captures the supplied `reason` into `rejection_reason`"

        Design: Corner/state_machines/society_registration_terminal_lockdown
        """
        ctx = setup_registered_work(title="Terminal Song")
        registration = ctx["registration"]
        assert registration["status"] == "REGISTERED"

        resp1 = api.reject_society_registration(registration["id"], "too late",
                                                COPYRIGHT)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp2 = api.submit_society_registration(registration["id"], COPYRIGHT)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(
            api.get_society_registration(registration["id"], ADMIN))
        assert after["status"] == "REGISTERED", "terminal state must not drift"


class TestCopyrightDimension:
    def test_work_parallel_dimensions_independent(self, api):
        """PRD §3.1: "The work starts with `registration_status` set to `UNREGISTERED` and `copyright_status` set to `UNFILED` — two parallel status dimensions that evolve independently"
        PRD §3.2: "Filing the copyright application — a call carrying a `filing_ref` — moves `copyright_status` from `UNFILED` to `FILED`; attempting it from any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. Recording the copyright-office registration — a call carrying a `registration_number` — then moves the work from `FILED` to `COPCO_REGISTERED`, again with `ERR_INVALID_STATE_TRANSITION` from any other state."

        Design: Corner/state_machines/work_parallel_dimensions_independent
        """
        work = create_work(title="Parallel Song")
        filed = validate_success(
            api.file_copyright(work["id"], "PA-2026-001", COPYRIGHT))
        assert filed["copyright_status"] == "FILED"
        assert filed["registration_status"] == "UNREGISTERED", (
            "copyright filing must not touch the registration dimension")

        registered = validate_success(
            api.register_copyright(work["id"], "PA0001234567", COPYRIGHT))
        assert registered["copyright_status"] == "COPCO_REGISTERED"
        assert registered["registration_status"] == "UNREGISTERED"

    def test_work_iswc_assigned_on_pro_registration(self, api):
        """PRD §3.2: "The register call may optionally carry an `iswc`: when the registration's society has `society_type` `PRO`, and the work does not yet have one, the provided `iswc` is assigned to the work — this is the only path by which a work acquires its International Standard Work Code, and a work that already has an `iswc` keeps it."
        PRD §3.2: "recording registration moves an `ACKNOWLEDGED` registration to `REGISTERED`, stamps `registered_at` from the logical clock, and lifts the work's `registration_status` to `REGISTERED`."

        Design: Corner/state_machines/work_iswc_assigned_on_pro_registration
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="ISWC Song")
        setup_confirmed_split_set(work["id"], [(writer["id"], 10000)])
        society = create_society()
        registration = _draft_registration(api, work["id"], society["id"])
        validate_success(
            api.submit_society_registration(registration["id"], COPYRIGHT))
        validate_success(api.acknowledge_society_registration(
            registration["id"], "880000997", COPYRIGHT))

        registered = validate_success(api.register_society_registration(
            registration["id"], COPYRIGHT, iswc="T-900000997-4"))
        assert registered["status"] == "REGISTERED"
        assert registered["registered_at"] is not None

        work_after = get_work(work["id"])
        assert work_after["iswc"] == "T-900000997-4"
        assert work_after["registration_status"] == "REGISTERED"

    def test_duplicate_society_registration_rejected(self, api):
        """PRD §3.2: "At most one registration per work-and-society pair may exist in any of `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, or `REGISTERED`; a conflicting create is rejected with `ERR_DUPLICATE_SOCIETY_REGISTRATION`."

        Design: Corner/validations/duplicate_society_registration_rejected
        """
        work = create_work(title="Dup Reg Song")
        society = create_society()
        first = _draft_registration(api, work["id"], society["id"])
        assert first["status"] == "DRAFT"

        resp = api.create_society_registration(
            create_society_registration_payload(work["id"], society["id"]),
            COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SOCIETY_REGISTRATION)
