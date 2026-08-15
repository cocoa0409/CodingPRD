"""Corrective-action rework loop and segregation of duties on verification."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_inspector_headers,
    make_pi_headers,
    setup_lab_with_completed_inspection,
    validate_error,
    validate_success,
)


def test_rework_loop_open_submitted_reopened_submitted_verified(api):
    """PRD §3.5: "The lab's PI submits remediation evidence by supplying a
    `resolution_note`, moving the action from `OPEN` — or from `REOPENED` on a
    rework pass — to `SUBMITTED`; the note is stored on submit and overwritten if
    the action is resubmitted after a reopen." and "A `decision` of `APPROVE` moves
    the action from `SUBMITTED` to `VERIFIED`, its terminal state, and stamps
    `verified_by` with the verifying inspector's id; a `decision` of `REJECT` moves
    it back to `REOPENED`, restarting the loop."

    Design: Difficulty/non_linear_state_machine/corrective_action_rework_loop
    """
    ctx = setup_lab_with_completed_inspection(
        [{"severity": "MINOR", "description": "fridge temp log gap"}],
        inspector_id="insp-1", name="Bio F", room="206",
    )
    pi, ca = ctx["pi"], ctx["corrective_actions"][0]
    assert ca["status"] == "OPEN"

    submitted = validate_success(
        api.submit_corrective_action(
            ca["id"], {"resolution_note": "log fixed"}, make_pi_headers(pi["id"])
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["resolution_note"] == "log fixed"

    reopened = validate_success(
        api.verify_corrective_action(
            ca["id"], {"decision": "REJECT"}, make_inspector_headers("insp-2")
        ),
        200,
    )
    assert reopened["status"] == "REOPENED"

    resubmitted = validate_success(
        api.submit_corrective_action(
            ca["id"], {"resolution_note": "log fixed, photo attached"},
            make_pi_headers(pi["id"]),
        ),
        200,
    )
    assert resubmitted["status"] == "SUBMITTED", "rework pass: REOPENED -> SUBMITTED"

    verified = validate_success(
        api.verify_corrective_action(
            ca["id"], {"decision": "APPROVE"}, make_inspector_headers("insp-2")
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by"] == "insp-2"
    assert verified["resolution_note"] == "log fixed, photo attached", (
        "the resubmitted note overwrites the earlier one"
    )


def test_verify_reject_reopens_the_loop(api):
    """PRD §3.5: "a `decision` of `REJECT` moves it back to `REOPENED`, restarting
    the loop." and "Verification then requires a different pair of hands: the
    verifying `EHSInspector` supplies a `decision`, and segregation of duties forbids
    the verifying inspector's `X-User-ID` from equalling the parent inspection's
    `completed_by_inspector_id`"

    Design: Difficulty/non_linear_state_machine/corrective_action_rework_loop
    """
    ctx = setup_lab_with_completed_inspection(
        [{"severity": "MINOR", "description": "label faded"}],
        inspector_id="insp-1", name="Bio F2", room="206",
    )
    pi, ca = ctx["pi"], ctx["corrective_actions"][0]

    validate_success(
        api.submit_corrective_action(
            ca["id"], {"resolution_note": "relabeled"}, make_pi_headers(pi["id"])
        ),
        200,
    )
    reopened = validate_success(
        api.verify_corrective_action(
            ca["id"], {"decision": "REJECT"}, make_inspector_headers("insp-2")
        ),
        200,
    )
    assert reopened["status"] == "REOPENED", "REJECT restarts the loop"
    assert reopened["verified_by"] is None


def test_same_inspector_cannot_verify_own_inspection_action(api):
    """PRD §3.5: "Verification then requires a different pair of hands: the verifying
    `EHSInspector` supplies a `decision`, and segregation of duties forbids the
    verifying inspector's `X-User-ID` from equalling the parent inspection's
    `completed_by_inspector_id` — a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `decision` of `APPROVE` moves the
    action from `SUBMITTED` to `VERIFIED`, its terminal state, and stamps
    `verified_by` with the verifying inspector's id"

    Design: Corner/validations/sod_same_inspector_cannot_verify
    """
    ctx = setup_lab_with_completed_inspection(
        [{"severity": "MINOR", "description": "label faded"}],
        inspector_id="insp-1", name="Lab Z2", room="211",
    )
    pi, ca = ctx["pi"], ctx["corrective_actions"][0]
    validate_success(
        api.submit_corrective_action(
            ca["id"], {"resolution_note": "relabeled"}, make_pi_headers(pi["id"])
        ),
        200,
    )

    res = api.verify_corrective_action(
        ca["id"], {"decision": "APPROVE"}, make_inspector_headers("insp-1")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    verified = validate_success(
        api.verify_corrective_action(
            ca["id"], {"decision": "APPROVE"}, make_inspector_headers("insp-2")
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by"] == "insp-2"
