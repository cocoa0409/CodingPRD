"""Drift complaints: filing rules, investigation holds, and the disciplinary
cascade (penalty points -> suspension/revocation -> schedule revert -> void)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_neighbor_customer, create_work_order, must_schedule, post_weather,
    set_clock, must_start, complete_work_order,
    create_drift_complaint_payload, file_and_open_complaint, substantiate,
    get_invoice_for_work_order, certify_record,
    base_environment, scheduled_environment, completed_environment,
    certified_environment, make_grower_headers, make_applicator_headers,
    EXPECTED, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _complete_second_job(env, start_date, acres=50, actual_p1=1.5, actual_p2=0.4):
    """Drive a second work order on the same field/prescription to COMPLETED."""
    wo = create_work_order(env["customer"]["id"], env["field"]["id"],
                           env["prescription"]["id"], acres_to_treat=acres)
    must_schedule(wo["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start=f"{start_date}T08:00:00Z",
                  scheduled_end=f"{start_date}T11:00:00Z")
    post_weather(env["applicator"]["id"], observed_at=f"{start_date}T07:30:00Z")
    set_clock(f"{start_date}T08:00:00Z")
    must_start(wo["id"], env["applicator"]["id"])
    set_clock(f"{start_date}T10:30:00Z")
    lines = [{"product_id": env["p1"]["id"], "actual_rate_per_acre": actual_p1}]
    if env.get("p2") is not None:
        lines.append({"product_id": env["p2"]["id"], "actual_rate_per_acre": actual_p2})
    return get_success_data(complete_work_order(wo["id"], env["applicator"]["id"], lines))


def test_complaint_after_30_day_window_rejected(api):
    """PRD §3.8: "Filing must happen within 30 days of the work order's
    completion; a complaint arriving later is rejected with
    `ERR_COMPLAINT_WINDOW_CLOSED`."

    Design: Corner/validations/complaint_after_30_day_window_rejected
    """
    env = completed_environment(num_products=1)  # completed 2026-05-10T10:30:00Z
    neighbor = create_neighbor_customer()
    set_clock("2026-06-10T00:00:00Z")  # more than 30 days after completion
    res = api_client.create_drift_complaint(
        create_drift_complaint_payload(env["work_order"]["id"],
                                       description="late drift claim"),
        make_grower_headers(neighbor["id"]))
    validate_error(res, "ERR_COMPLAINT_WINDOW_CLOSED", expected_status=409)


def test_duplicate_open_complaint_rejected(api):
    """PRD §3.8: "Only one open complaint may exist per work order: if a
    complaint for the same order is already `FILED` or `INVESTIGATING`, the new
    filing is rejected with `ERR_DUPLICATE_OPEN_COMPLAINT`."
    PRD §3.8: "Dismissal is the quiet ending: `INVESTIGATING` to the terminal
    `DISMISSED`, with `findings_note` recorded, the complaint's `version`
    incremented, and no applicator change at all"

    Design: Corner/validations/duplicate_open_complaint_rejected
    """
    env = completed_environment(num_products=1)
    neighbor = create_neighbor_customer()
    wo_id = env["work_order"]["id"]

    first = validate_success(api_client.create_drift_complaint(
        create_drift_complaint_payload(wo_id, description="first report"),
        make_grower_headers(neighbor["id"])), 201)

    res = api_client.create_drift_complaint(
        create_drift_complaint_payload(wo_id, description="second report", severity="MAJOR"),
        make_grower_headers(env["customer"]["id"]))
    validate_error(res, "ERR_DUPLICATE_OPEN_COMPLAINT", expected_status=409)

    # After the first complaint is DISMISSED (terminal, no longer open),
    # a fresh filing is accepted again.
    validate_success(api_client.open_complaint_investigation(first["id"], COMPLIANCE), 200)
    validate_success(api_client.dismiss_complaint(
        first["id"], {"findings_note": "unfounded"}, COMPLIANCE), 200)
    third = validate_success(api_client.create_drift_complaint(
        create_drift_complaint_payload(wo_id, description="third report after dismissal"),
        make_grower_headers(env["customer"]["id"])), 201)
    assert third["status"] == "FILED"


def test_complaint_against_unfinished_work_order_rejected(api):
    """PRD §3.8: "A `Grower` files a DriftComplaint against a `COMPLETED` work
    order — filing against an order in any other state is `ERR_INVALID_STATE`"

    Design: Corner/validations/complaint_against_unfinished_work_order_rejected
    """
    env = scheduled_environment(num_products=1)
    neighbor = create_neighbor_customer()
    res = api_client.create_drift_complaint(
        create_drift_complaint_payload(env["work_order"]["id"], description="premature"),
        make_grower_headers(neighbor["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_applicator_rolling_vs_lifetime_score(api):
    """PRD §3.8: "Hop one lands penalty weight on the applicator: two points
    for a `MINOR` complaint, five for a `MAJOR`. The weight adds to
    `penalty_points_lifetime`, the sum over all substantiated complaints with
    no time window and no multiplier. The same substantiation recomputes
    `rolling_score_365`: the sum of weights over complaints substantiated
    within the trailing 365 days (the substantiation timestamp is the
    `updated_at` of the complaint's transition into `SUBSTANTIATED`), doubled
    whenever at least two substantiations fall within the trailing 90 days."
    PRD §3.8: "an `ACTIVE` applicator becomes `SUSPENDED` when the recomputed
    rolling score is below ten points"

    Design: Difficulty/dual_variant_calc/applicator_rolling_vs_lifetime_score
    """
    env = completed_environment(acres_to_treat=50)  # WO_A completed 2026-05-10
    wo_a = env["work_order"]["id"]
    neighbor = create_neighbor_customer()
    wo_b = _complete_second_job(env, "2026-05-13")["id"]

    cmp_a = file_and_open_complaint(wo_a, neighbor["id"], severity="MINOR",
                                    description="Spray drift onto my bees")
    cmp_b = file_and_open_complaint(wo_b, neighbor["id"], severity="MINOR",
                                    description="Odor and residue on garden")
    substantiate(cmp_a["id"], "residue confirmed")
    substantiate(cmp_b["id"], "residue confirmed")

    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    assert ap["penalty_points_lifetime"] == 4, \
        f"2 + 2 with no window and no multiplier, got {ap['penalty_points_lifetime']}"
    assert ap["rolling_score_365"] == 8, \
        f"(2+2) doubled by the 90-day recency rule, got {ap['rolling_score_365']}"
    assert ap["status"] == "SUSPENDED", "rolling 8 < 10 suspends but does not revoke"


def test_single_minor_substantiation_scores_without_doubler(api):
    """PRD §3.8: "two points for a `MINOR` complaint, five for a `MAJOR`. The
    weight adds to `penalty_points_lifetime`, the sum over all substantiated
    complaints with no time window and no multiplier."
    PRD §3.8: "doubled whenever at least two substantiations fall within the
    trailing 90 days."

    Design: Difficulty/dual_variant_calc/applicator_rolling_vs_lifetime_score
    """
    env = completed_environment(num_products=1)
    neighbor = create_neighbor_customer()
    cmp1 = file_and_open_complaint(env["work_order"]["id"], neighbor["id"],
                                   severity="MINOR", description="drift")
    substantiate(cmp1["id"])

    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    # One substantiation: the recency doubler cannot fire, so both variants agree.
    assert ap["penalty_points_lifetime"] == 2
    assert ap["rolling_score_365"] == 2
    assert ap["status"] == "SUSPENDED"


def test_complaint_substantiation_revocation_cascade(api):
    """PRD §3.8: "Hop two moves the license: an `ACTIVE` applicator becomes
    `SUSPENDED` when the recomputed rolling score is below ten points, while a
    `SUSPENDED` applicator becomes `REVOKED` — terminal — when the recomputed
    rolling score reaches at least ten; exactly ten revokes."
    PRD §3.8: "Hop three protects future work: every `SCHEDULED` work order
    assigned to that applicator reverts to `DRAFT` with its assignment cleared,
    per §2.8."
    PRD §3.8: "Separately, the complained work order's own invoice is voided in
    the same breath: a `DRAFT` or `ISSUED` invoice moves to `VOIDED`"

    Design: Difficulty/transitive_cascade/complaint_substantiation_revocation_cascade
    """
    env = completed_environment(acres_to_treat=50)  # WO_A completed 2026-05-10
    wo_a = env["work_order"]["id"]
    neighbor = create_neighbor_customer()
    wo_b = _complete_second_job(env, "2026-05-13")["id"]

    # A third job is SCHEDULED for the still-active applicator.
    wo_c = create_work_order(env["customer"]["id"], env["field"]["id"],
                             env["prescription"]["id"], acres_to_treat=40)
    must_schedule(wo_c["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start="2026-05-14T08:00:00Z",
                  scheduled_end="2026-05-14T10:00:00Z")

    # First MAJOR substantiation: ACTIVE -> SUSPENDED (rolling 5 < 10), and the
    # suspension cascade reverts the scheduled job to DRAFT.
    cmp_a = file_and_open_complaint(wo_a, neighbor["id"], severity="MAJOR",
                                    description="drift on pasture")
    substantiate(cmp_a["id"], "confirmed")
    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    assert ap["status"] == "SUSPENDED" and ap["rolling_score_365"] == 5
    woc = get_success_data(api.get_work_order(wo_c["id"], DISPATCHER))
    assert woc["status"] == "DRAFT" and woc["applicator_id"] is None
    assert woc["equipment_id"] is None and woc["estimated_total_cents"] is None

    # Second MAJOR substantiation while SUSPENDED: rolling (5+5)*2 = 20 >= 10
    # (two substantiations inside 90 days double) -> REVOKED; the complained
    # job's DRAFT invoice is voided.
    cmp_b = file_and_open_complaint(wo_b, neighbor["id"], severity="MAJOR",
                                    description="drift on pond")
    substantiate(cmp_b["id"], "confirmed, fish kill")
    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    assert ap["rolling_score_365"] == 20, \
        f"(5+5) with the 90-day doubler, got {ap['rolling_score_365']}"
    assert ap["status"] == "REVOKED", "rolling 20 >= 10 revokes a SUSPENDED applicator"
    assert ap["penalty_points_lifetime"] == 10

    inv_b = get_invoice_for_work_order(wo_b)
    assert inv_b["status"] == "VOIDED", \
        "substantiation voids the complained work order's invoice"


def test_substantiation_voids_issued_invoice_and_credits_balance(api):
    """PRD §3.8: "a `DRAFT` or `ISSUED` invoice moves to `VOIDED`, and if it
    had been issued, the customer's `outstanding_cents` is credited by the
    invoice's `final_amount_cents` with the Customer's `version` incrementing."

    Design: Difficulty/transitive_cascade/complaint_substantiation_revocation_cascade
    """
    env = certified_environment(num_products=1)
    neighbor = create_neighbor_customer()
    validate_success(api_client.issue_invoice(env["invoice"]["id"], ADMIN), 200)
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == EXPECTED["SINGLE_PRODUCT_100AC"]

    cmp1 = file_and_open_complaint(env["work_order"]["id"], neighbor["id"],
                                   severity="MINOR", description="drift")
    substantiate(cmp1["id"], "confirmed")

    invoice = get_success_data(api.get_invoice(env["invoice"]["id"], ADMIN))
    assert invoice["status"] == "VOIDED", "issued invoice is voided by substantiation"
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == 0, "the issued amount is credited back"
    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    assert ap["status"] == "SUSPENDED" and ap["rolling_score_365"] == 2


def test_reinstate_blocked_while_investigation_pending(api):
    """PRD §3.3: "Reinstatement is blocked while any drift complaint naming
    that applicator is still `INVESTIGATING` — the attempt is rejected with
    `ERR_INVESTIGATION_PENDING` — because the co-op does not restore a license
    mid-inquiry."
    PRD §3.3: "A suspended applicator returns to duty only through a
    `ComplianceOfficer`'s reinstatement, which moves `SUSPENDED` back to
    `ACTIVE` and increments the Applicator's `version`."

    Design: Corner/validations/reinstate_blocked_while_investigation_pending
    """
    env = completed_environment(num_products=1, acres_to_treat=40)  # WO1 2026-05-10
    neighbor = create_neighbor_customer()
    wo2 = _complete_second_job(env, "2026-05-12", acres=40)["id"]

    cmp1 = file_and_open_complaint(env["work_order"]["id"], neighbor["id"],
                                   severity="MINOR", description="drift A")
    substantiate(cmp1["id"], "confirmed")  # rolling 2 -> SUSPENDED
    ap = get_success_data(api.get_applicator(env["applicator"]["id"], ADMIN))
    assert ap["status"] == "SUSPENDED"

    cmp2 = file_and_open_complaint(wo2, neighbor["id"], severity="MINOR",
                                   description="drift B")
    res = api_client.reinstate_applicator(env["applicator"]["id"], COMPLIANCE)
    validate_error(res, "ERR_INVESTIGATION_PENDING", expected_status=409)

    validate_success(api_client.dismiss_complaint(
        cmp2["id"], {"findings_note": "unfounded"}, COMPLIANCE), 200)
    reinstated = validate_success(
        api_client.reinstate_applicator(env["applicator"]["id"], COMPLIANCE), 200)
    assert reinstated["status"] == "ACTIVE"


def test_schedule_with_suspended_applicator_rejected(api):
    """PRD §3.4: "The named applicator must exist and be `ACTIVE`, else
    `ERR_APPLICATOR_NOT_ACTIVE`."

    Design: Corner/validations/schedule_with_suspended_applicator_rejected
    """
    env = completed_environment(num_products=1, acres_to_treat=40)
    neighbor = create_neighbor_customer()
    cmp1 = file_and_open_complaint(env["work_order"]["id"], neighbor["id"],
                                   severity="MINOR", description="drift")
    substantiate(cmp1["id"], "confirmed")  # rolling 2 -> SUSPENDED

    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=40)
    res = api_client.schedule_work_order(
        wo2["id"],
        {"applicator_id": env["applicator"]["id"],
         "equipment_id": env["equipment"]["id"],
         "scheduled_start": "2026-05-20T08:00:00Z",
         "scheduled_end": "2026-05-20T11:00:00Z"},
        DISPATCHER)
    validate_error(res, "ERR_APPLICATOR_NOT_ACTIVE", expected_status=409)


def test_revocation_threshold_exactly_10(api):
    """PRD §3.8: "a `SUSPENDED` applicator becomes `REVOKED` — terminal — when
    the recomputed rolling score reaches at least ten; exactly ten revokes."
    PRD §3.8: "the sum of weights over complaints substantiated within the
    trailing 365 days (the substantiation timestamp is the `updated_at` of the
    complaint's transition into `SUBSTANTIATED`), doubled whenever at least two
    substantiations fall within the trailing 90 days."

    Design: Corner/cross_cutting_complexity_layers/revocation_threshold_exactly_10
    """
    env = base_environment(num_products=1, acres_to_treat=40,
                           prescription_overrides={"valid_to": "2026-12-31T23:59:59Z"})
    ap = env["applicator"]["id"]
    neighbor = create_neighbor_customer()

    # Both jobs are completed while the applicator is still ACTIVE.
    wo1 = env["work_order"]
    must_schedule(wo1["id"], ap, env["equipment"]["id"],
                  scheduled_start="2026-05-10T08:00:00Z",
                  scheduled_end="2026-05-10T11:00:00Z")
    post_weather(ap, observed_at="2026-05-10T07:30:00Z")
    set_clock("2026-05-10T08:00:00Z")
    must_start(wo1["id"], ap)
    set_clock("2026-05-10T10:30:00Z")
    get_success_data(complete_work_order(wo1["id"], ap, [
        {"product_id": env["p1"]["id"], "actual_rate_per_acre": 1.5}]))
    wo2_id = _complete_second_job(env, "2026-05-13", acres=40)["id"]

    # First MAJOR: substantiated 2026-05-13 -> rolling 5 -> SUSPENDED.
    cmp1 = file_and_open_complaint(wo1["id"], neighbor["id"], severity="MAJOR",
                                   description="drift A")
    substantiate(cmp1["id"], "confirmed")
    ap_now = get_success_data(api.get_applicator(ap, ADMIN))
    assert ap_now["status"] == "SUSPENDED" and ap_now["rolling_score_365"] == 5

    # Second MAJOR: filed within its 30-day window, substantiated 104 days
    # later so the 90-day recency doubler does NOT fire: rolling == 5 + 5 = 10.
    cmp2 = file_and_open_complaint(wo2_id, neighbor["id"], severity="MAJOR",
                                   description="drift B")
    set_clock("2026-08-25T00:00:00Z")
    substantiate(cmp2["id"], "confirmed")

    ap_after = get_success_data(api.get_applicator(ap, ADMIN))
    assert ap_after["rolling_score_365"] == 10, \
        f"exactly 10 (no doubler 104 days apart), got {ap_after['rolling_score_365']}"
    assert ap_after["status"] == "REVOKED", "the >= threshold is inclusive: exactly ten revokes"
