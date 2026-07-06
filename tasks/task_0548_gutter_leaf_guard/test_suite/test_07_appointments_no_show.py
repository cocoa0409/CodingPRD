"""No-show cascades and their boundary, plus the state-before-measurement
priority ordering on the appointment-completion path.
"""
from test_helpers import (
    ApiErrorId,
    create_appointment,
    create_lead,
    create_product,
    create_quote,
    create_sales_rep,
    transition_appointment,
    validate_error,
    validate_success,
)


def _lead_with_prior_no_show_and_open_work():
    """A lead with a DRAFT quote (backed by a still-SCHEDULED appointment), one
    prior NO_SHOW appointment (1 strike), and a second SCHEDULED appointment
    ready to be marked NO_SHOW."""
    product = create_product()
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO8", address="8 Spruce St", phone="555-0108")
    appt_q = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T10:00:00Z",
    )
    quote = create_quote(lead["id"], appt_q["id"], rep["id"], product["id"], "WHITE", 180)
    appt1 = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T11:00:00Z", scheduled_end="2026-06-02T12:00:00Z",
    )
    transition_appointment(appt1["id"], "NO_SHOW")
    appt2 = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T13:00:00Z", scheduled_end="2026-06-02T14:00:00Z",
    )
    return {"lead": lead, "quote": quote, "appt_q": appt_q, "appt2": appt2}


# ----------------------------------------------------------- no-show cascade
def test_second_no_show_marks_lead_lost(api, admin_headers):
    """PRD §3.3: "First the lead's `no_show_strikes` is recomputed as the count of
    that lead's `NO_SHOW` appointments. Then, if that count reaches two or more,
    the lead is automatically moved to `LOST`, which in turn runs the lost-lead
    cleanup from Section 3.2 — declining the lead's open quotes and cancelling its
    remaining open appointments."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2
    """
    ctx = _lead_with_prior_no_show_and_open_work()
    transition_appointment(ctx["appt2"]["id"], "NO_SHOW")
    lead = validate_success(api.get_lead(ctx["lead"]["id"], admin_headers))
    assert lead["no_show_strikes"] == 2
    assert lead["status"] == "LOST"


def test_lost_lead_declines_quote_and_cancels_open_appointment(api, admin_headers):
    """PRD §3.2: "Every quote for the lead that is in `DRAFT`, `PRESENTED`, or
    `REVISION_REQUESTED` is moved to `DECLINED`, and every appointment for the
    lead that is in `SCHEDULED` or `CONFIRMED` is moved to `CANCELED`, releasing
    those rep windows."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2
    """
    ctx = _lead_with_prior_no_show_and_open_work()
    transition_appointment(ctx["appt2"]["id"], "NO_SHOW")
    quote = validate_success(api.get_quote(ctx["quote"]["id"], admin_headers))
    assert quote["status"] == "DECLINED"
    appt_q = validate_success(api.get_appointment(ctx["appt_q"]["id"], admin_headers))
    assert appt_q["status"] == "CANCELED"


# --------------------------------------------------------- no-show boundary
def test_one_no_show_below_limit_keeps_lead_active(api, admin_headers):
    """PRD §3.3: "Then, if that count reaches two or more, the lead is
    automatically moved to `LOST`, which in turn runs the lost-lead cleanup from
    Section 3.2 — declining the lead's open quotes and cancelling its remaining
    open appointments."

    Design: Difficulty/boundary_precision_check/no_show_strike_boundary_2
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO13", address="13 Fir St", phone="555-0113")
    appt1 = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T10:00:00Z",
    )
    transition_appointment(appt1["id"], "NO_SHOW")
    lead = validate_success(api.get_lead(lead["id"], admin_headers))
    assert lead["no_show_strikes"] == 1
    assert lead["status"] != "LOST"


def test_second_no_show_reaches_limit_and_marks_lost(api, admin_headers):
    """PRD §3.3: "First the lead's `no_show_strikes` is recomputed as the count of
    that lead's `NO_SHOW` appointments. Then, if that count reaches two or more,
    the lead is automatically moved to `LOST`, which in turn runs the lost-lead
    cleanup from Section 3.2 — declining the lead's open quotes and cancelling its
    remaining open appointments."

    Design: Difficulty/boundary_precision_check/no_show_strike_boundary_2
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO13", address="13 Fir St", phone="555-0113")
    appt1 = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T10:00:00Z",
    )
    transition_appointment(appt1["id"], "NO_SHOW")
    appt2 = create_appointment(
        lead["id"], rep["id"],
        scheduled_start="2026-06-02T11:00:00Z", scheduled_end="2026-06-02T12:00:00Z",
    )
    transition_appointment(appt2["id"], "NO_SHOW")
    lead = validate_success(api.get_lead(lead["id"], admin_headers))
    assert lead["no_show_strikes"] == 2
    assert lead["status"] == "LOST"


# --------------------------------------- state check precedes measurement check
def test_completed_on_canceled_appointment_is_invalid_state(api, admin_headers):
    """PRD §2.6: "The target resource must be in a valid originating state for the
    requested transition, including cross-entity state preconditions."
    PRD §2.6: "`ERR_INVALID_STATE` for a plain illegal transition"

    Design: Difficulty/priority_pair_validation_conflict/complete_appt_state_beats_measurement
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO11", address="11 Fir St", phone="555-0111")
    appt = create_appointment(lead["id"], rep["id"])
    transition_appointment(appt["id"], "CANCELED")
    # measured_linear_feet=0 would also fail (priority 8), but the state check
    # (priority 4) is evaluated first, so ERR_INVALID_STATE is returned.
    resp = api.transition_appointment(
        appt["id"], {"to_status": "COMPLETED", "measured_linear_feet": 0}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_state_beats_measurement_leaves_appointment_canceled(api, admin_headers):
    """PRD §3.3: "`COMPLETED`, `CANCELED`, and `NO_SHOW` are terminal appointment
    states."
    PRD §2.6: "the server evaluates checks in a fixed priority order and returns
    the error of the first check that fails."

    Design: Difficulty/priority_pair_validation_conflict/complete_appt_state_beats_measurement
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO11", address="11 Fir St", phone="555-0111")
    appt = create_appointment(lead["id"], rep["id"])
    transition_appointment(appt["id"], "CANCELED")
    api.transition_appointment(
        appt["id"], {"to_status": "COMPLETED", "measured_linear_feet": 0}, admin_headers
    )
    after = validate_success(api.get_appointment(appt["id"], admin_headers))
    assert after["status"] == "CANCELED"
