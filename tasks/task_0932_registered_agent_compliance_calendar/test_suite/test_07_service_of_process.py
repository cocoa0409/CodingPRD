"""Service of process: business-hour deadlines, pre-emption and the ack clock."""
from test_helpers import (
    DE_RULE_MIN,
    SOP,
    ApiErrorId,
    assert_same_instant,
    assert_sop_document,
    read_registration,
    read_sop,
    receive_sop,
    scan_sop,
    set_clock,
    setup_active_home_registration,
    setup_forwarded_sop,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_litigation_receipt_defers_the_open_ordinary_document(api):
    """PRD §3.9: "Every `ORDINARY` document on that registration whose `status` is
    `RECEIVED` or `SCANNED` — that is, every ordinary document not yet forwarded — has
    its `forward_deadline_at` advanced by a further 8 business hours along the same
    cursor, has `deferred` set true, and has `deferral_count` increased by one."
    PRD §3.9: "A `LITIGATION` document gets 4 business hours — half a business day, so a
    Friday-morning receipt lands Friday afternoon and a Friday-afternoon receipt lands
    Monday morning. An `ORDINARY` document gets 16 business hours, which is two full
    business days, so a Friday receipt lands on Tuesday."
    PRD §3.9: "The registration's `sop_priority_hold` becomes true."

    Design: Corner/state_machines/corner_litigation_receipt_defers_open_ordinary_document
    """
    scene = setup_active_home_registration(DE_RULE_MIN)
    set_clock("2026-06-05T14:00:00Z")
    ordinary = receive_sop(scene["registration"]["id"], "ORDINARY")
    # Friday 14:00 plus 16 business hours: 3 hours to 17:00 Friday, 8 hours Monday,
    # then 5 hours from 09:00 Tuesday lands at 2026-06-09T14:00Z.
    assert_same_instant(
        ordinary["forward_deadline_at"],
        "2026-06-09T14:00:00Z",
        "ordinary forward_deadline_at before pre-emption",
    )

    set_clock("2026-06-09T14:00:00Z")
    litigation = validate_success(
        api.create_sop_document(
            scene["registration"]["id"],
            {
                "sop_class": "LITIGATION",
                "plaintiff_name": "Acme Trading Co",
                "court_case_number": "N26C-0417",
            },
            SOP,
        ),
        201,
    )

    deferred = read_sop(ordinary["id"])
    assert_sop_document(deferred)
    # A further 8 business hours from 2026-06-09T14:00Z: 3 hours to 17:00 Tuesday,
    # then 5 hours from 09:00 Wednesday lands at 2026-06-10T14:00Z.
    assert_same_instant(
        deferred["forward_deadline_at"],
        "2026-06-10T14:00:00Z",
        "ordinary forward_deadline_at after pre-emption",
    )
    assert deferred["deferred"] is True
    assert deferred["deferral_count"] == 1
    assert deferred["status"] == "RECEIVED"

    # The litigation document's own 4 business hours: 3 hours to 17:00 Tuesday, then
    # 1 hour from 09:00 Wednesday lands at 2026-06-10T10:00Z.
    assert_same_instant(
        litigation["forward_deadline_at"],
        "2026-06-10T10:00:00Z",
        "litigation forward_deadline_at",
    )
    assert read_registration(scene["registration"]["id"])["sop_priority_hold"] is True


def test_papers_scanned_as_not_our_entity_are_terminal(api):
    """PRD §3.9: "With `not_our_entity` true, the document moves `RECEIVED →
    REJECTED_NOT_OUR_ENTITY` instead, `scanned_at` is still stamped, and the
    registration's `sop_priority_hold` is cleared if no other litigation document on
    that registration remains open."
    PRD §3.9: "Either way the document's `version` increases by 1, and
    `REJECTED_NOT_OUR_ENTITY` is terminal."
    PRD §3.9: "This same action is also how a document is re-forwarded after an
    escalation, so it is accepted from `SCANNED` and from `ESCALATED`; from any other
    status it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_sop_scan_marks_document_not_our_entity
    """
    scene = setup_active_home_registration(DE_RULE_MIN)
    set_clock("2026-06-05T14:00:00Z")
    document = receive_sop(scene["registration"]["id"], "ORDINARY")

    scanned = scan_sop(document["id"], not_our_entity=True)
    assert scanned["status"] == "REJECTED_NOT_OUR_ENTITY"
    assert_same_instant(scanned["scanned_at"], "2026-06-05T14:00:00Z", "scanned_at")

    response = api.forward_sop_document(document["id"], SOP)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_sop(document["id"])["forwarded_at"] is None


def test_escalating_before_the_ack_deadline_is_refused(api):
    """PRD §3.9: "`ack_deadline_at` is set to `forwarded_at` advanced by 8 business
    hours."
    PRD §3.9: "the current logical clock instant must have reached `ack_deadline_at`,
    else `ERR_SOP_ACK_NOT_DUE` — the comparison is inclusive, so escalating exactly at
    `ack_deadline_at` is permitted and only strictly before it is refused; and
    `escalation_level` must be strictly below 3, else
    `ERR_SOP_ESCALATION_CAP_REACHED`."
    PRD §3.9: "`forwarded_late` is then set to true when `forwarded_at` is **strictly**
    later than `forward_deadline_at`, and false otherwise — forwarding exactly at the
    deadline instant is on time."

    Design: Corner/validations/corner_escalation_before_the_ack_deadline_is_refused
    """
    scene = setup_forwarded_sop(DE_RULE_MIN)
    document = scene["document"]

    # Forwarded Monday 2026-06-08T10:00Z: 7 hours to 17:00 that day, then 1 hour from
    # 09:00 Tuesday, so the acknowledgment clock runs out at 2026-06-09T10:00Z.
    assert_same_instant(
        document["ack_deadline_at"], "2026-06-09T10:00:00Z", "ack_deadline_at"
    )
    assert document["forwarded_late"] is False

    set_clock("2026-06-08T16:00:00Z")
    response = api.escalate_sop_document(document["id"], SOP)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SOP_ACK_NOT_DUE.value)

    after = read_sop(document["id"])
    assert after["escalation_level"] == 0
    assert after["status"] == "FORWARDED"

    _rows, meta = validate_paginated(api.list_sop_escalations(document["id"], SOP))
    assert meta["total_count"] == 0
