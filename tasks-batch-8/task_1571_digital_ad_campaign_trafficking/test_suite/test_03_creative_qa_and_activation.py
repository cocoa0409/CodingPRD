"""Creative QA loop, tagging, activation guards, and terminal lockdown."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_io, create_line_item, create_creative, transition_io,
    transition_line_item, transition_creative, walk_creative_to_tagged,
    setup_live_line_item, get_creative,
    AD_TAG,
)


class TestCreativeQA:
    def test_creative_initial_state_uploaded(self, api, trafficker_headers):
        """PRD §3.3: "A new creative lands in `UPLOADED` with `ad_tag` and
        `qa_failure_reason` both null."

        Design: Corner/entities/creative_initial_state_uploaded
        """
        io = create_io()
        li = create_line_item(io["id"])
        res = api.create_creative(
            {"line_item_id": li["id"], "name": "CR1",
             "asset_url": "https://cdn.example.com/a.jpg",
             "width": 300, "height": 250},
            trafficker_headers)
        cr = validate_success(res, 201)
        assert cr["status"] == "UPLOADED"
        assert cr["ad_tag"] is None
        assert cr["qa_failure_reason"] is None

    def test_tag_transition_without_ad_tag_rejected(
            self, api, trafficker_headers):
        """PRD §3.3: "the transition payload must carry a non-empty
        `ad_tag`, again enforced with `ERR_TAG_REQUIRED`, and the value is
        stored on the creative."

        Design: Corner/validations/tag_transition_without_ad_tag_rejected
        """
        io = create_io()
        li = create_line_item(io["id"], goal_impressions=1000)
        cr = create_creative(li["id"])
        transition_creative(cr["id"], "SUBMIT_QA")
        transition_creative(cr["id"], "PASS_QA")

        res = api.transition_creative(cr["id"], {"action": "TAG"},
                                      trafficker_headers)
        validate_error(res, ApiErrorId.ERR_TAG_REQUIRED.value, 400)
        assert get_creative(cr["id"])["status"] == "QA_PASSED"

    def test_qa_revision_loop_clears_failure_reason(
            self, api, trafficker_headers):
        """PRD §3.3: "A fail moves it to `QA_FAILED` and requires a non-empty
        `qa_failure_reason` in the transition payload — a missing or empty
        reason is rejected with `ERR_TAG_REQUIRED` — and the reason is stored
        on the creative. Revision (`QA_FAILED` → `IN_QA`) clears
        `qa_failure_reason` back to null, and the fail-revise loop may repeat
        as assets are reworked."

        Design: Difficulty/non_linear_state_machine/creative_qa_revision_loop
        """
        io = create_io()
        li = create_line_item(io["id"])
        transition_io(io["id"], "APPROVE")
        cr = create_creative(li["id"])
        transition_creative(cr["id"], "SUBMIT_QA")

        failed = validate_success(
            api.transition_creative(
                cr["id"], {"action": "FAIL_QA",
                           "qa_failure_reason": "click macro broken"},
                trafficker_headers), 200)
        assert failed["status"] == "QA_FAILED"
        assert failed["qa_failure_reason"] == "click macro broken"

        revised = validate_success(
            api.transition_creative(cr["id"], {"action": "REVISE"},
                                    trafficker_headers), 200)
        assert revised["status"] == "IN_QA"
        assert revised["qa_failure_reason"] is None, (
            "REVISE must clear qa_failure_reason back to null")

        transition_creative(cr["id"], "PASS_QA")
        tagged = validate_success(
            api.transition_creative(cr["id"],
                                    {"action": "TAG", "ad_tag": AD_TAG},
                                    trafficker_headers), 200)
        assert tagged["status"] == "TAGGED"
        assert tagged["ad_tag"] == AD_TAG

    def test_qa_fail_revise_loop_repeats(self, api, trafficker_headers):
        """PRD §3.3: "Revision (`QA_FAILED` → `IN_QA`) clears
        `qa_failure_reason` back to null, and the fail-revise loop may repeat
        as assets are reworked."

        Design: Difficulty/non_linear_state_machine/creative_qa_revision_loop
        """
        io = create_io()
        li = create_line_item(io["id"])
        cr = create_creative(li["id"])
        transition_creative(cr["id"], "SUBMIT_QA")

        for reason in ("tracker 404", "expansion broken"):
            failed = validate_success(
                api.transition_creative(
                    cr["id"], {"action": "FAIL_QA",
                               "qa_failure_reason": reason},
                    trafficker_headers), 200)
            assert failed["status"] == "QA_FAILED"
            assert failed["qa_failure_reason"] == reason
            revised = validate_success(
                api.transition_creative(cr["id"], {"action": "REVISE"},
                                        trafficker_headers), 200)
            assert revised["status"] == "IN_QA"
            assert revised["qa_failure_reason"] is None

        transition_creative(cr["id"], "PASS_QA")
        tagged = transition_creative(cr["id"], "TAG", ad_tag=AD_TAG)
        assert tagged["status"] == "TAGGED"


class TestCreativeActivation:
    def test_activate_requires_line_item_live(self, api, trafficker_headers):
        """PRD §3.3: "Activation (`TAGGED` → `LIVE`) may be requested
        directly by a `Trafficker`, in which case the parent line item must
        be `LIVE` (`ERR_LINE_ITEM_NOT_LIVE`)"

        Design: Difficulty/cross_entity_state_dependency/creative_activate_requires_line_item_live
        """
        io = create_io()
        li = create_line_item(io["id"])
        transition_io(io["id"], "APPROVE")
        cr1 = create_creative(li["id"], name="CR1")
        walk_creative_to_tagged(cr1["id"], ad_tag="<script>1</script>")
        transition_line_item(li["id"], "TRAFFIC")
        cr2 = create_creative(li["id"], name="CR2")
        walk_creative_to_tagged(cr2["id"], ad_tag="<script>2</script>")

        res = api.transition_creative(cr2["id"], {"action": "ACTIVATE"},
                                      trafficker_headers)
        validate_error(res, ApiErrorId.ERR_LINE_ITEM_NOT_LIVE.value, 409)
        assert get_creative(cr2["id"])["status"] == "TAGGED"

    def test_activate_succeeds_after_line_item_live(
            self, api, trafficker_headers):
        """PRD §3.3: "Activation (`TAGGED` → `LIVE`) may be requested
        directly by a `Trafficker`, in which case the parent line item must
        be `LIVE` (`ERR_LINE_ITEM_NOT_LIVE`) and its `fraud_posture` must be
        `CLEAR` (`ERR_FRAUD_HOLD`)"

        Design: Difficulty/cross_entity_state_dependency/creative_activate_requires_line_item_live
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        cr2 = create_creative(li_id, name="CR2")
        walk_creative_to_tagged(cr2["id"], ad_tag="<script>2</script>")

        activated = validate_success(
            api.transition_creative(cr2["id"], {"action": "ACTIVATE"},
                                    trafficker_headers), 200)
        assert activated["status"] == "LIVE"

    def test_creative_archived_terminal_lockdown(self, api,
                                                 trafficker_headers):
        """PRD §3.3: "`ARCHIVED` is terminal, and every creative transition
        increments the creative's `version` by one."
        PRD §2.8: "Sixth, state validity: the target resource must be in a
        valid from-state for the requested action, with terminal states
        locked against any further transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/creative_archived_terminal_lockdown
        """
        io = create_io()
        li = create_line_item(io["id"], goal_impressions=1000)
        cr = create_creative(li["id"])
        transition_line_item(li["id"], "CANCEL")
        assert get_creative(cr["id"])["status"] == "ARCHIVED"

        res = api.transition_creative(cr["id"], {"action": "SUBMIT_QA"},
                                      trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert get_creative(cr["id"])["status"] == "ARCHIVED"
