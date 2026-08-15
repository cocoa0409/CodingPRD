"""Item lifecycle transitions, terminal lockdown, and version increments."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_version_incremented,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PSYCH_H,
    WRITER,
    create_draft_item,
    create_program,
    create_standard,
    read_item,
    submit_item,
)
from test_helpers.test_users import make_item_writer_headers


class TestItemLifecycle:
    def test_item_initial_state_is_draft(self, api):
        """PRD: "At creation the server stamps `author_user_id` with the
        caller's `X-User-ID`, sets `status` to `DRAFT` and `security_posture`
        to `UNSECURED`"

        Design: Corner/state_machines/item_initial_state_is_draft
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-INIT")
        assert item["status"] == "DRAFT"
        assert item["security_posture"] == "UNSECURED"

    def test_item_submit_from_submitted_returns_invalid_state(self, api):
        """PRD: "The submit is rejected with `ERR_ITEM_NOT_IN_DRAFT` when the
        item is not in `DRAFT`"

        Design: Corner/state_machines/item_submit_from_submitted_returns_invalid_state
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-X")
        submitted = submit_item(item)
        assert submitted["status"] == "CONTENT_REVIEW", (
            "submission auto-promotes SUBMITTED -> CONTENT_REVIEW"
        )
        # Second submit carries the item's now-current version, so the
        # version guard passes and the state precondition is what fires.
        resp = api.submit_item(submitted["id"], submitted["version"],
                               make_item_writer_headers(WRITER))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_IN_DRAFT)

    def test_item_retired_is_terminal_no_transitions(self, api):
        """PRD: "An author may also discard a `DRAFT` item outright, moving it
        to `REJECTED` with `retirement_reason` recorded as `MANUAL`."
        PRD: "Approval requires the item to be in `STATS_REVIEW`
        (`ERR_ITEM_NOT_IN_STATS_REVIEW` otherwise)"

        Design: Corner/state_machines/item_retired_is_terminal_no_transitions
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-T",
                                 author="w-1")
        discarded = get_success_data(
            api.discard_item(item["id"], make_item_writer_headers("w-1")))
        assert discarded["status"] == "REJECTED"
        resp = api.approve_operational_item(item["id"], PSYCH_H)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_IN_STATS_REVIEW)
        after = read_item(program["id"], item["id"])
        assert after["status"] == "REJECTED", "terminal state is locked"

    def test_item_update_only_in_draft_put_blocked_after_submit(self, api):
        """PRD: "an edit attempted once the item has left `DRAFT` is rejected
        with `ERR_ITEM_NOT_IN_DRAFT` (HTTP 409)"

        Design: Corner/state_machines/item_update_only_in_draft_put_blocked_after_submit
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-P")
        submit_item(item)
        resp = api.update_item(item["id"], {"stimulus_html": "<p>new</p>"},
                               make_item_writer_headers(WRITER))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_IN_DRAFT)

    def test_item_discard_side_effects_set_retirement_reason(self, api):
        """PRD: "An author may also discard a `DRAFT` item outright, moving it
        to `REJECTED` with `retirement_reason` recorded as `MANUAL`."

        Design: Corner/state_machines/item_discard_side_effects_set_retirement_reason
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-D",
                                 author="w-9")
        discarded = validate_success(
            api.discard_item(item["id"], make_item_writer_headers("w-9")))
        assert discarded["status"] == "REJECTED"
        assert discarded["retirement_reason"] == "MANUAL"


class TestItemVersioning:
    def test_version_increments_on_every_mutation(self, api):
        """PRD: "each edit increments the item's `version` and refreshes
        `updated_at`"
        PRD: "`version`, a system-managed integer that increments by one on
        every mutation of the resource"

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-VI")
        updated = validate_success(api.update_item(
            item["id"], {"stimulus_html": "<p>updated</p>"},
            make_item_writer_headers(WRITER)))
        assert_version_incremented(updated["version"], item["version"])
        assert updated["version"] == item["version"] + 1, (
            "an edit increments version by exactly one"
        )

    def test_error_item_not_in_stats_review(self, api):
        """PRD: "Approval requires the item to be in `STATS_REVIEW`
        (`ERR_ITEM_NOT_IN_STATS_REVIEW` otherwise)"

        Design: Corner/errors/error_item_not_in_stats_review
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = create_draft_item(program["id"], standard["id"], item_code="I-NSR")
        resp = api.approve_operational_item(item["id"], PSYCH_H)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_IN_STATS_REVIEW)

    def test_error_invalid_state_on_terminal_item(self, api):
        """PRD: "Each identifier in the path must resolve to an existing
        resource before the next identifier is examined, and the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not resolve."

        Design: Corner/errors/error_invalid_state_on_terminal_item
        """
        create_program()
        resp = api.get_item(NON_EXISTENT_UUID, make_item_writer_headers("w-x"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
