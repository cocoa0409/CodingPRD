"""
Read-your-write consistency: one ticket create must expose its own cascade — the
machine's health, the kitchen's backlog and the stamped commitment — at once.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_axes
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS
from test_helpers.types import (
    OP_DOWN,
    OP_UP,
    ORIGIN_CUSTOMER_REPORT,
    PLACEMENT_INSTALLED,
    POSTURE_ELEVATED,
    POSTURE_NORMAL,
    SYMPTOM_MACHINE_DOWN,
    TICKET_QUEUED,
)


def test_one_ticket_write_exposes_its_whole_cascade_in_the_same_response(api):
    """
    Filing one breakdown report writes four rows' worth of consequence and every one of
    them is visible to the very next read: the create response already carries the score
    and the commitment it selected, the machine has moved to down, and the kitchen's
    backlog and posture have been re-derived. The score is the bare symptom base, because
    the health component and the posture component are both read from the state as it
    stood before the row was inserted — an implementation that scores after applying its
    own cascade would add the down-during-service weight and the backlog weight and land
    in the two-hour band instead. Re-reading the ticket returns the same two stamped
    values, never a recomputation.

    PRD §3.5: "**Every input to the score is read from the state as it stands immediately
    before the ticket row is inserted.** Two consequences follow directly and are the most
    common source of off-by-one-band errors: the ticket being created never counts towards
    the site-posture component, and a customer report of `MACHINE_DOWN` is scored against
    the placement's health as it was *before* the request, because that request's own
    drive of the machine to `DOWN` is applied only after the score has been stamped."

    PRD §3.5: "The stamped score then selects a response commitment, and each band
    boundary is inclusive on its own side: a score of 700 or more gets 120 minutes, a
    score of 400 or more but under 700 gets 240 minutes, and anything below 400 gets 480
    minutes. `response_deadline_at` is the ticket's creation instant advanced by exactly
    that many minutes, expressed as an ISO 8601 UTC instant to whole seconds."

    PRD §3.1: "`service_posture` grades that backlog into one of three values, evaluated
    in this order: it is `CRITICAL` when at least one of those open tickets carries a
    `priority_score` of 700 or more; otherwise it is `ELEVATED` when at least one such
    open ticket exists at all; otherwise it is `NORMAL`."

    Design: Corner/consistency_model/one_ticket_write_exposes_its_whole_cascade_in_the_same_response
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    assert_axes(
        placement,
        placement_status=PLACEMENT_INSTALLED,
        operational_status=OP_UP,
    )

    quiet_site = get_success_data(
        api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert quiet_site["open_ticket_count"] == 0
    assert quiet_site["service_posture"] == POSTURE_NORMAL

    # Midday sits inside the kitchen's 10:00-22:00 operating window, so a machine
    # already down would have carried the 300-point in-service weight.
    X.set_clock(api, "2026-08-01T12:00:00Z")

    ticket = validate_success(
        api.create_service_ticket(
            F.service_ticket_payload(placement["id"], SYMPTOM_MACHINE_DOWN),
            base["customer_headers"],
        ),
        201,
    )
    assert ticket["origin"] == ORIGIN_CUSTOMER_REPORT
    assert ticket["status"] == TICKET_QUEUED
    # 400 symptom base alone: the machine was UP and the posture NORMAL when read.
    assert ticket["priority_score"] == 400
    # 400 falls in the [400, 700) band: 240 minutes from 12:00 UTC.
    assert ticket["response_deadline_at"] == "2026-08-01T16:00:00Z"

    downed = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        downed,
        placement_status=PLACEMENT_INSTALLED,
        operational_status=OP_DOWN,
    )
    assert downed["open_alert_count"] == 0

    busy_site = get_success_data(
        api.get_site(base["site_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert busy_site["open_ticket_count"] == 1
    assert busy_site["service_posture"] == POSTURE_ELEVATED

    reread = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert reread["priority_score"] == ticket["priority_score"]
    assert reread["response_deadline_at"] == ticket["response_deadline_at"]
