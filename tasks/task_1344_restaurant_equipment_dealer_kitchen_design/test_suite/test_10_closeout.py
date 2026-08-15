"""Closeout: punch-list gating, retainage release, completion, cancellation."""
from test_helpers import (
    TEST_USERS,
    accept_quote_flow,
    create_punch_list_item_payload,
    get_success_data,
    make_customer_headers,
    setup_commissioned_project,
    setup_quote_presented,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
SM = TEST_USERS["service_manager_headers"]
PC = TEST_USERS["permit_coordinator_headers"]


def test_punch_close_gated_on_health_permit(api):
    """PRD §3.8: "the project's `HEALTH_DEPT` permit filing must be `APPROVED`
    (`ERR_HEALTH_PERMIT_NOT_APPROVED`)"."

    Design: Difficulty/cross_entity_state_dependency/punch_close_gated_on_health_permit
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project()
    )
    # HEALTH_DEPT filing exists but is still DRAFT (never submitted).
    get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )

    proj_v = get_success_data(api.get_project(project["id"], PM))["version"]
    res = api.close_punch_list(project["id"], proj_v, PM)
    validate_error(res, "ERR_HEALTH_PERMIT_NOT_APPROVED", expected_status=422)


def test_punch_close_succeeds_with_approved_health_permit(api):
    """PRD §3.8: "On success the project moves to `PUNCH_CLOSED`, every
    still-`OPEN` `COSMETIC` punch item is voided, `retainage_held_cents` drops
    to 0, the released retainage amount is debited from the customer's
    `outstanding_exposure_cents`, and the project's `version` increments
    by 1."

    Design: Difficulty/cross_entity_state_dependency/punch_close_gated_on_health_permit
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project()
    )
    filing = get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )
    get_success_data(api.submit_permit_filing(project["id"], filing["id"], PC))
    get_success_data(
        api.record_permit_decision(project["id"], filing["id"], "APPROVED", PC)
    )

    proj_v = get_success_data(api.get_project(project["id"], PM))["version"]
    closed = validate_success(api.close_punch_list(project["id"], proj_v, PM), 200)
    assert closed["status"] == "PUNCH_CLOSED"
    assert closed["retainage_held_cents"] == 0
    assert closed["version"] == proj_v + 1


def test_retainage_release_conserves_customer_exposure(api):
    """PRD §3.3: "The project freezes `quote_baseline_cents` to the final
    `grand_total_cents`, computes `retainage_held_cents` as the baseline
    multiplied by `retainage_pct` rounded half-up to whole cents". PRD §3.8:
    "the released retainage amount is debited from the customer's
    `outstanding_exposure_cents`"."

    Design: Difficulty/compensating_invariant/retainage_release_conserves_customer_exposure
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project(
            item_overrides_list=[
                {"model_no": "RANGE", "quantity": 1, "unit_price_cents": 100_000,
                 "lead_time_days": 5}
            ]
        )
    )
    # grand_total = 100,000 + 6,000 + 295,000 + 210,000 = 611,000.
    assert project["quote_baseline_cents"] == 611_000
    # retainage = round_half_up(611,000 * 0.10) = 61,100.
    assert project["retainage_held_cents"] == 61_100

    cust = get_success_data(api.get_customer(customer["id"], PM))
    exposure_after_accept = cust["outstanding_exposure_cents"]
    # PRD 3.3: exposure = "the newly accepted net balance plus the withheld
    # retainage" = 611,000 + 61,100. (Only this reading lets completion
    # "close the account's exposure for the job": 672,100 - 61,100 released
    # at punch close - 611,000 baseline at completion = 0.)
    assert exposure_after_accept == 611_000 + 61_100

    filing = get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )
    get_success_data(api.submit_permit_filing(project["id"], filing["id"], PC))
    get_success_data(
        api.record_permit_decision(project["id"], filing["id"], "APPROVED", PC)
    )
    proj_v = get_success_data(api.get_project(project["id"], PM))["version"]
    validate_success(api.close_punch_list(project["id"], proj_v, PM), 200)

    cust_after = get_success_data(api.get_customer(customer["id"], PM))
    # Exposure debited by exactly the released retainage amount.
    assert cust_after["outstanding_exposure_cents"] == (
        exposure_after_accept - 61_100
    )


def test_retainage_released_and_baseline_frozen(api):
    """PRD §3.8: "`retainage_held_cents` drops to 0" on punch close. PRD §3.3:
    "The project freezes `quote_baseline_cents` to the final
    `grand_total_cents`"."

    Design: Difficulty/compensating_invariant/retainage_release_conserves_customer_exposure
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project(
            item_overrides_list=[
                {"model_no": "RANGE", "quantity": 1, "unit_price_cents": 100_000,
                 "lead_time_days": 5}
            ]
        )
    )
    assert project["retainage_held_cents"] > 0

    filing = get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )
    get_success_data(api.submit_permit_filing(project["id"], filing["id"], PC))
    get_success_data(
        api.record_permit_decision(project["id"], filing["id"], "APPROVED", PC)
    )
    proj_v = get_success_data(api.get_project(project["id"], PM))["version"]
    closed = validate_success(api.close_punch_list(project["id"], proj_v, PM), 200)
    assert closed["retainage_held_cents"] == 0
    assert closed["quote_baseline_cents"] == 611_000


def test_project_cancel_cascade_only_non_terminal(api):
    """PRD §3.9: "Every non-terminal quote becomes `SUPERSEDED`; every
    non-terminal fabrication order becomes `CANCELLED`; every non-terminal
    delivery job becomes `CANCELLED`; every non-terminal equipment item
    becomes `CANCELLED`; every `OPEN` punch item becomes `VOID`; every `OPEN`
    service assignment becomes `CLOSED`." Only OPEN punch items void —
    VERIFIED items are terminal and untouched.

    Design: Corner/state_machines/project_cancel_cascade_only_non_terminal
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project()
    )
    p_cos = get_success_data(
        api.create_punch_list_item(
            project["id"],
            create_punch_list_item_payload(
                description="Scratch on door", severity="COSMETIC"
            ),
            PM,
        )
    )
    p_fun = get_success_data(
        api.create_punch_list_item(
            project["id"],
            create_punch_list_item_payload(
                description="Fix valve", severity="FUNCTIONAL"
            ),
            PM,
        )
    )
    get_success_data(api.verify_punch_list_item(project["id"], p_fun["id"], PM))

    validate_success(api.cancel_project(project["id"], PM), 200)

    cos_after = get_success_data(
        api.get_punch_list_item(project["id"], p_cos["id"], PM)
    )
    fun_after = get_success_data(
        api.get_punch_list_item(project["id"], p_fun["id"], PM)
    )
    assert cos_after["status"] == "VOID"
    assert fun_after["status"] == "VERIFIED"


def test_project_cancel_cascade_closes_open_assignment(api):
    """PRD §3.9: "every `OPEN` service assignment becomes `CLOSED`. Any
    retainage being held is released — `retainage_held_cents` drops to 0 — and
    the customer's `outstanding_exposure_cents` is reduced by this project's
    contribution, unwinding the exposure the deal had accumulated."

    Design: Corner/state_machines/project_cancel_cascade_only_non_terminal
    """
    customer, project, layout, items, quote, job, agency, sessions = (
        setup_commissioned_project()
    )
    assignments = get_success_data(api.list_service_assignments(project["id"], SM))
    assert assignments[0]["status"] == "OPEN"

    validate_success(api.cancel_project(project["id"], PM), 200)

    asgn_after = get_success_data(
        api.get_service_assignment(project["id"], assignments[0]["id"], SM)
    )
    assert asgn_after["status"] == "CLOSED"
    project_after = get_success_data(api.get_project(project["id"], PM))
    assert project_after["status"] == "CANCELLED"
    assert project_after["retainage_held_cents"] == 0
