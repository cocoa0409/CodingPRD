"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server DB is empty before
each test) and uses get_success_data() so setup failures surface clearly.

Gardener is entity-backed: ownership-gated calls thread make_gardener_headers(id).
GardenManager / Treasurer are opaque operator roles using the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_gardener_headers
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

DEFAULT_CLOCK = "2026-03-10T00:00:00Z"


# --------------------------------------------------------------------------
# Low-level primitives (each returns the parsed resource dict)
# --------------------------------------------------------------------------

def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, MANAGER))


def new_garden(api, **overrides):
    return get_success_data(api.create_garden(f.create_garden_payload(**overrides), MANAGER))


def new_plot(api, garden_id, size="MEDIUM", label="P-1", **overrides):
    return get_success_data(
        api.create_plot(f.create_plot_payload(garden_id, size=size, label=label, **overrides), MANAGER)
    )


def new_gardener(api, full_name="Test Gardener", email=None, **overrides):
    return get_success_data(
        api.create_gardener(f.create_gardener_payload(full_name=full_name, email=email, **overrides), MANAGER)
    )


def direct_assign(api, plot_id, gardener_id, expected_plot_version):
    return get_success_data(
        api.assign_plot(plot_id, f.assign_plot_payload(gardener_id, expected_plot_version), MANAGER)
    )


def new_application(api, gardener_id, garden_id, requested_size="MEDIUM"):
    headers = make_gardener_headers(gardener_id)
    return get_success_data(
        api.create_application(
            f.create_application_payload(gardener_id, garden_id, requested_size), headers
        )
    )


def add_water_reading(api, assignment_id, gardener_id, period_index, gallons_used,
                      recorded_on="2026-04-01T00:00:00Z"):
    headers = make_gardener_headers(gardener_id)
    return get_success_data(
        api.create_water_reading(
            f.create_water_reading_payload(assignment_id, period_index, gallons_used, recorded_on),
            headers,
        )
    )


def add_work_log(api, assignment_id, gardener_id, hours, logged_on="2026-06-15T00:00:00Z"):
    headers = make_gardener_headers(gardener_id)
    return get_success_data(
        api.create_work_log(f.create_work_log_payload(assignment_id, hours, logged_on), headers)
    )


def open_compliance_case(api, assignment_id, violation_type="NEGLECT"):
    return get_success_data(
        api.create_compliance_case(
            f.create_compliance_case_payload(assignment_id, violation_type), MANAGER
        )
    )


def new_tool(api, garden_id, name="Wheelbarrow 1", category="CART", **overrides):
    return get_success_data(
        api.create_tool(f.create_tool_payload(garden_id, name=name, category=category, **overrides), MANAGER)
    )


def new_tool_loan(api, tool_id, gardener_id, checked_out_at, due_at):
    headers = make_gardener_headers(gardener_id)
    return get_success_data(
        api.create_tool_loan(
            f.create_tool_loan_payload(tool_id, gardener_id, checked_out_at, due_at), headers
        )
    )


def new_shed_booking(api, garden_id, gardener_id, starts_at, ends_at, purpose="STORAGE"):
    headers = make_gardener_headers(gardener_id)
    return get_success_data(
        api.create_shed_booking(
            f.create_shed_booking_payload(garden_id, gardener_id, starts_at, ends_at, purpose), headers
        )
    )


def pay_full(api, assignment_id, amount_cents):
    return get_success_data(api.pay_assignment(assignment_id, {"amount_cents": amount_cents}, TREASURER))


# --------------------------------------------------------------------------
# Composite: a single directly-assigned plot (the most reused preamble)
# --------------------------------------------------------------------------

def setup_assigned_plot(api, size="MEDIUM", clock=DEFAULT_CLOCK, garden_overrides=None,
                        gardener_email=None, label="M-1"):
    """clock -> garden -> plot(size) -> gardener -> direct assign.

    Returns dict: garden, plot, gardener, gardener_headers, assignment.
    """
    if clock is not None:
        set_clock(api, clock)
    garden = new_garden(api, **(garden_overrides or {}))
    plot = new_plot(api, garden["id"], size=size, label=label)
    gardener = new_gardener(api, email=gardener_email)
    assignment = direct_assign(api, plot["id"], gardener["id"], plot["version"])
    return {
        "garden": garden,
        "plot": plot,
        "gardener": gardener,
        "gardener_headers": make_gardener_headers(gardener["id"]),
        "assignment": assignment,
    }


def setup_assignment_with_usage(api, size="MEDIUM", readings=None, hours=None,
                                clock=DEFAULT_CLOCK):
    """Assigned plot plus per-period water readings and a single work-log tally,
    positioned for a settle/forfeit final-fee computation.

    readings: list of gallons for period 1..3 (missing periods -> omitted).
    hours: total logged work hours (None -> no work log).
    """
    ctx = setup_assigned_plot(api, size=size, clock=clock)
    asg_id = ctx["assignment"]["id"]
    gid = ctx["gardener"]["id"]
    if readings:
        month = 4
        for idx, gallons in enumerate(readings, start=1):
            add_water_reading(api, asg_id, gid, idx, gallons,
                              recorded_on=f"2026-0{month}-01T00:00:00Z")
            month += 1
    if hours is not None:
        add_work_log(api, asg_id, gid, hours)
    return ctx


# --------------------------------------------------------------------------
# Composite: an OFFERED application on a plot (waitlist happy path)
# --------------------------------------------------------------------------

def setup_offered_application(api, size="MEDIUM", clock="2026-03-10T00:00:00Z",
                              garden_overrides=None):
    """clock -> garden -> plot -> gardener -> application(WAITLISTED) -> offer.

    Returns dict: garden, plot, gardener, gardener_headers, application (OFFERED).
    """
    if clock is not None:
        set_clock(api, clock)
    garden = new_garden(api, **(garden_overrides or {}))
    plot = new_plot(api, garden["id"], size=size, label="OF-1")
    gardener = new_gardener(api)
    application = new_application(api, gardener["id"], garden["id"], requested_size=size)
    offered = get_success_data(api.offer_plot(plot["id"], MANAGER))
    return {
        "garden": garden,
        "plot": plot,
        "gardener": gardener,
        "gardener_headers": make_gardener_headers(gardener["id"]),
        "application": offered,
    }


# --------------------------------------------------------------------------
# Composite: assigned plot with a waitlisted rival (forfeiture cascade)
# --------------------------------------------------------------------------

def setup_assigned_with_waitlisted_rival(api, size="MEDIUM", clock=DEFAULT_CLOCK):
    """One plot directly assigned to gardener A; gardener B WAITLISTED for the same
    size in the same garden. Returns garden, plot, holder assignment, and rival app.
    """
    set_clock(api, clock)
    garden = new_garden(api)
    plot = new_plot(api, garden["id"], size=size, label="RV-1")
    holder = new_gardener(api, full_name="Holder A")
    rival = new_gardener(api, full_name="Rival B")
    assignment = direct_assign(api, plot["id"], holder["id"], plot["version"])
    rival_app = new_application(api, rival["id"], garden["id"], requested_size=size)
    return {
        "garden": garden,
        "plot": plot,
        "holder": holder,
        "assignment": assignment,
        "rival": rival,
        "rival_app": rival_app,
    }


# --------------------------------------------------------------------------
# Composite: a WARNED compliance case on an assigned plot
# --------------------------------------------------------------------------

def setup_warned_case(api, size="MEDIUM", violation_type="RULE_BREACH",
                      warn_clock="2026-03-15T00:00:00Z"):
    """Assigned plot -> open compliance case -> warn (sets cure_deadline = warn_clock + 14d).

    Returns dict: garden, plot, gardener, assignment, case (WARNED).
    """
    ctx = setup_assigned_plot(api, size=size, clock=warn_clock, label="CC-1")
    case = open_compliance_case(api, ctx["assignment"]["id"], violation_type)
    warned = get_success_data(api.warn_case(case["id"], MANAGER))
    ctx["case"] = warned
    return ctx


# --------------------------------------------------------------------------
# Composite: an active gardener with a tool available in the shed
# --------------------------------------------------------------------------

def setup_active_gardener_with_tool(api, clock="2026-03-15T00:00:00Z",
                                    cleaning_buffer_hours=4, category="CART"):
    """Assigned (ACTIVE) plot + a tool in the same garden. Returns garden, plot,
    gardener, gardener_headers, assignment, tool.
    """
    ctx = setup_assigned_plot(api, size="MEDIUM", clock=clock, label="TL-1")
    tool = new_tool(api, ctx["garden"]["id"], name="Tool 1", category=category,
                    cleaning_buffer_hours=cleaning_buffer_hours)
    ctx["tool"] = tool
    return ctx
