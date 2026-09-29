"""Endpoint-surface corners: withdrawal, arrears payment, generic not-found,
allowance guarding, conditional termination and booking cancellation.

Every state ladder is rebuilt from scratch inside each test, because the harness
restarts the service against an empty store before each one.
"""
from test_helpers import (
    COMPLIANCE_OFFICER,
    LEASING_AGENT,
    NON_EXISTENT_UUID,
    PROPERTY_MANAGER,
    ApiErrorId,
    assert_line_split,
    assert_mix_figures,
    assert_money_equals,
    assert_project_rollups,
    assert_total_count,
    assert_version_advanced_by,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as tf
from test_helpers import fixtures as fx


def test_withdrawing_a_draft_lease_retains_the_row_and_disqualifies_its_appraisals(api):
    """A DELETE on a draft lease is a terminal state change, not a row removal.

    "Withdrawal is available only while a lease is still `DRAFT`, and only when no tenant-improvement project on the lease survives in any status other than `CANCELLED`."
    "Withdrawal takes the lease `DRAFT → WITHDRAWN`, which is terminal — the row is retained rather than deleted — and it disqualifies the paper trail behind it: every appraisal on that lease still in `SUBMITTED` or `QUALIFIED` moves to `DISQUALIFIED` with `decision_reason` recorded as "lease withdrawn"."
    "The lease's `version` advances by 1."
    "A violation is `ERR_INVALID_LEASE_STATE` (409)."
    "Leases can be listed and narrowed by `building_id`, `suite_id`, `tenant_id`, `master_lease_id`, `status` and `lease_type`; the `master_lease_id` filter is how the subleases hanging under a hospital master lease are discovered."
    "Suite occupancy is never set directly by any client-facing operation."
    "Every new suite begins `VACANT` with `last_vacated_on` null, and adding a suite advances the owning building's `version` by 1."

    Design: Corner/endpoints/delete_withdraws_the_draft_lease_and_disqualifies_its_appraisals
    """
    ctx = fx.drafted_lease(api, tenant_overrides={
        "legal_name": "Lakeside Oncology Partners LLP",
        "primary_specialty": "ONCOLOGY",
        "is_physician_owned": True,
    })
    lease_id = ctx["lease"]["id"]
    appraisal = fx.file_appraisal(api, lease_id, ctx["lease"]["version"],
                                  appraiser_firm="Harbor Valuation LLC")
    fx.qualify_appraisal(api, appraisal["id"], "Independent opinion accepted for the file")

    before = fx.read_lease(api, lease_id)
    assert before["status"] == "DRAFT", "the lease must still be DRAFT before withdrawal"

    withdrawn = validate_success(api.withdraw_lease(lease_id, LEASING_AGENT), 200)
    assert withdrawn["status"] == "WITHDRAWN", (
        "expected WITHDRAWN, got {}".format(withdrawn["status"]))
    assert_version_advanced_by(before, withdrawn, 1)

    survivor = validate_success(api.get_lease(lease_id, LEASING_AGENT), 200)
    assert survivor["status"] == "WITHDRAWN", "the withdrawn row must remain readable"

    rows, _meta = validate_paginated(api.list_lease_appraisals(lease_id, COMPLIANCE_OFFICER))
    assert len(rows) == 1, "expected the single filed appraisal, got {}".format(len(rows))
    assert rows[0]["status"] == "DISQUALIFIED", (
        "expected DISQUALIFIED, got {}".format(rows[0]["status"]))
    assert rows[0]["decision_reason"] == "lease withdrawn", (
        "expected decision_reason 'lease withdrawn', got {}".format(rows[0]["decision_reason"]))

    validate_error(api.withdraw_lease(lease_id, LEASING_AGENT),
                   ApiErrorId.ERR_INVALID_LEASE_STATE)

    listed, meta = validate_paginated(api.list_leases(
        LEASING_AGENT, {"building_id": ctx["building"]["id"], "status": "WITHDRAWN"}))
    assert_total_count(meta, 1)
    assert ids_of(listed) == [lease_id], "the WITHDRAWN filter must return the withdrawn lease"

    suite = fx.read_suite(api, ctx["suite"]["id"])
    assert suite["occupancy_status"] == "VACANT", (
        "a withdrawn draft never held the suite, got {}".format(suite["occupancy_status"]))
    assert suite["last_vacated_on"] is None, (
        "last_vacated_on must still be null, got {}".format(suite["last_vacated_on"]))


def test_paying_a_delinquent_invoice_settles_the_balance_without_relieving_the_risk(api):
    """Settling arrears clears the balance yet retains the frozen delinquency weight.

    "**Step 1** derives `base_rent_amount` as the lease's `effective_base_rent_annual` divided by 12 — the annual figure is a year's rent and a month is a twelfth of it — rounded half up to 2 decimal places."
    "**Step 2** derives `cam_amount`, the common-area recovery, as the building's `operating_expense_annual_psf` multiplied by the suite's `rentable_sf` and divided by 12, rounded half up to 2 decimal places."
    "**Step 6** derives `total_amount`, the amount owed, as `pre_waiver_total` less `parking_waiver_amount`."
    "The weight tiers are keyed on the day count itself rather than on days past grace, which means the day an invoice becomes delinquent it is already worth 15 points: a day count of at most 30 carries a weight of 15, a count of at most 60 carries 30, and a count beyond 60 carries 50."
    "A partial payment and an overpayment are both refused with `ERR_INVALID_REQUEST`."
    "Payment is admissible from `ISSUED` or from `DELINQUENT`, and both routes converge: `amount_paid` becomes `total_amount`, `paid_on` is stamped with the clock date, `days_past_due` is refreshed to the whole number of days between the clock date and `due_date` (never below zero), and `version` advances."
    "`days_past_due_at_flag` and `delinquency_tier_weight` are both retained unchanged, so the tenant's `referral_compliance_risk_score` does not fall when the money finally arrives — the remuneration event happened, and the only relief is the rolling window eventually ageing it out."
    "A `RENT_DELINQUENCY` case may be cured only when no rent invoice of that tenant remains in `DELINQUENT` — writing off or paying every delinquent invoice is the precondition, not a formality."
    "`referral_compliance_risk_score` is the **rolling twelve-month** operational figure: it considers only those events whose `due_date` falls on or after the clock date minus 365 days, sums their weights, and then caps the result at 100."
    "`strict_cumulative_risk_score` is the **audit** figure: it sums the weights of every qualifying event of that tenant with no date window at all and applies no cap, which is the number an external reviewer reconstructs from the ledger."
    "`compliance_watch_status` reads `WATCH` when the rolling `referral_compliance_risk_score` is at least 45, or when the tenant has any compliance case in status `OPEN`, `REMEDIATION_PLANNED` or `REPORTED`; otherwise it reads `CLEAR`."
    "**Hop 3** fires when the recomputed **rolling** score is at least 45: the tenant's `compliance_watch_status` becomes `WATCH` and the system opens a compliance case against that tenant with `case_type` `RENT_DELINQUENCY` in status `OPEN`, at `HIGH` severity when the recomputed rolling score is at least 90 and `MEDIUM` otherwise, with `scoring_variant` `ROLLING_12M`, `risk_score_at_open` set to that recomputed rolling score, `opened_on` set to the clock date, `opened_by_user_id` recorded as the literal value `system`, and `remediation_due_on` set to the clock date plus 30 days."

    Design: Corner/endpoints/paying_a_delinquent_invoice_cures_the_balance_but_not_the_risk_score
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]
    tenant_id = ctx["tenant"]["id"]
    invoice = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")

    flagged = fx.flag_delinquent(api, lease_id, "2026-11-07")
    assert flagged["id"] == invoice["id"], "the close must flag the September invoice"
    assert flagged["status"] == "DELINQUENT", (
        "expected DELINQUENT, got {}".format(flagged["status"]))
    assert_money_equals(flagged["total_amount"], 16500.00, "total_amount")
    assert flagged["days_past_due"] == 63, (
        "expected 63 days past due, got {}".format(flagged["days_past_due"]))
    assert flagged["days_past_due_at_flag"] == 63, (
        "expected days_past_due_at_flag 63, got {}".format(flagged["days_past_due_at_flag"]))
    assert flagged["delinquency_tier_weight"] == 50, (
        "expected weight 50 beyond 60 days, got {}".format(flagged["delinquency_tier_weight"]))

    validate_error(api.pay_rent_invoice(invoice["id"], tf.payment_payload(10000.00),
                                        PROPERTY_MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST)
    rows, _meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    assert_money_equals(rows[0]["amount_paid"], 0.00, "amount_paid after a refused part payment")
    assert rows[0]["status"] == "DELINQUENT", "a refused payment must not move the invoice"

    paid = validate_success(api.pay_rent_invoice(invoice["id"], tf.payment_payload(16500.00),
                                                 PROPERTY_MANAGER), 200)
    assert_money_equals(paid["amount_paid"], 16500.00, "amount_paid")
    assert paid["paid_on"] == "2026-11-07", (
        "expected paid_on 2026-11-07, got {}".format(paid["paid_on"]))
    assert paid["days_past_due"] == 63, (
        "expected days_past_due 63, got {}".format(paid["days_past_due"]))
    assert paid["status"] != "DELINQUENT", "a settled invoice no longer remains DELINQUENT"
    assert paid["days_past_due_at_flag"] == 63, (
        "days_past_due_at_flag must be retained, got {}".format(paid["days_past_due_at_flag"]))
    assert paid["delinquency_tier_weight"] == 50, (
        "delinquency_tier_weight must be retained, got {}".format(
            paid["delinquency_tier_weight"]))

    tenant = fx.read_tenant(api, tenant_id)
    assert tenant["referral_compliance_risk_score"] == 50, (
        "the rolling score must not fall on payment, got {}".format(
            tenant["referral_compliance_risk_score"]))
    assert tenant["strict_cumulative_risk_score"] == 50, (
        "the strict score must not fall on payment, got {}".format(
            tenant["strict_cumulative_risk_score"]))
    assert tenant["compliance_watch_status"] == "WATCH", (
        "the tenant must stay on WATCH, got {}".format(tenant["compliance_watch_status"]))

    cases, case_meta = validate_paginated(api.list_tenant_compliance_cases(
        tenant_id, COMPLIANCE_OFFICER, {"status": "OPEN"}))
    assert_total_count(case_meta, 1)
    assert cases[0]["case_type"] == "RENT_DELINQUENCY", (
        "expected a RENT_DELINQUENCY case, got {}".format(cases[0]["case_type"]))
    assert cases[0]["severity"] == "MEDIUM", (
        "a rolling score of 50 opens at MEDIUM, got {}".format(cases[0]["severity"]))


def test_unknown_child_record_ids_answer_the_generic_resource_not_found(api):
    """Unknown child rows answer one generic 404 while leases and suites keep their own.

    "Path parameters are resolved left to right before the body is examined."
    "A `suite_id` appearing in the path or the body identifies an existing suite, and where a building is named in the same request the suite's `building_id` matches it — otherwise `ERR_SUITE_NOT_FOUND` (404)."
    "A lease reference in the path or the body — including a `master_lease_id` on a sublease and a `lease_id` on a booking or a parking allocation — identifies an existing lease, otherwise `ERR_LEASE_NOT_FOUND` (404)."
    "Any other addressed resource — an appraisal, a tenant-improvement project, a line item, a rent invoice, a compliance case, a shared space, a shared-space booking or a parking allocation — identifies an existing row of that type, otherwise `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/endpoints/unknown_child_record_ids_return_the_generic_resource_not_found
    """
    fx.leasing_baseline(api)

    validate_error(api.pay_rent_invoice(NON_EXISTENT_UUID, tf.payment_payload(100.00),
                                        PROPERTY_MANAGER),
                   ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    validate_error(api.decide_appraisal(
        NON_EXISTENT_UUID, tf.appraisal_decision_payload("QUALIFY", "Nothing to qualify"),
        COMPLIANCE_OFFICER), ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    validate_error(api.get_booking(NON_EXISTENT_UUID, LEASING_AGENT),
                   ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    validate_error(api.revoke_parking_allocation(
        NON_EXISTENT_UUID, tf.revoke_allocation_payload("Nothing to revoke"), PROPERTY_MANAGER),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    validate_error(api.transition_compliance_case(
        NON_EXISTENT_UUID,
        tf.case_transition_payload("REMEDIATION_PLAN", remediation_summary="Nothing to plan"),
        COMPLIANCE_OFFICER), ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    validate_error(api.get_lease(NON_EXISTENT_UUID, LEASING_AGENT),
                   ApiErrorId.ERR_LEASE_NOT_FOUND)
    validate_error(api.get_suite(NON_EXISTENT_UUID, LEASING_AGENT),
                   ApiErrorId.ERR_SUITE_NOT_FOUND)


def test_line_item_is_refused_when_the_landlord_share_would_overdraw_the_allowance(api):
    """The allowance guard rejects only the overdrawing line; a smaller one still appends.

    "Third, the project default: otherwise `effective_share_pct` takes the project's `landlord_share_pct`."
    "From the resolved share, `landlord_share_amount` is the line's `cost_amount` multiplied by `effective_share_pct`, rounded half up to 2 decimal places, and `tenant_share_amount` is the line's `cost_amount` **less** that rounded landlord amount."
    "The project's totals are then sums of the **already-rounded** per-line figures, taken over the lines in `sequence_no` order: `landlord_committed_amount` sums the per-line landlord amounts, `tenant_committed_amount` sums the per-line tenant amounts, and `allowance_remaining` is `authorized_allowance_total` less `landlord_committed_amount`."
    "Appending a line also increments `line_item_count` by 1 and advances the project's `version` by 1."
    "A line whose landlord share would drive `allowance_remaining` below zero is refused with `ERR_TI_ALLOWANCE_EXCEEDED`."
    "The server sets the line's `ti_project_id` from the addressed project rather than from the request body, and assigns `sequence_no`, a 1-based index that increases monotonically within the project and is the pinned processing order for every cost figure derived below."

    Design: Corner/endpoints/ti_line_item_refused_when_the_landlord_share_would_overdraw_the_allowance
    """
    ctx = fx.drafted_lease(api, suite_overrides={"power_amps_available": 400,
                                                 "medical_gas_available": True})
    project = fx.open_ti_project(api, ctx["lease"]["id"], ctx["suite"]["id"],
                                 target_suite_class="PROCEDURE",
                                 power_amps_requested=120,
                                 medical_gas_requested=False,
                                 authorized_allowance_total=100000.00,
                                 landlord_share_pct=0.60)

    first = fx.add_line_item(api, project["id"], project["version"],
                             description="Procedure room shell to finish",
                             category="FINISHES", cost_amount=150000.00)
    assert first["sequence_no"] == 1, (
        "the first line takes sequence_no 1, got {}".format(first["sequence_no"]))
    assert_line_split(first, 0.6000, 90000.00, 60000.00)

    after_first = fx.read_project(api, project["id"])
    assert_project_rollups(after_first, 90000.00, 60000.00, 10000.00, 1)
    assert_version_advanced_by(project, after_first, 1)

    refused = api.create_ti_line_item(
        project["id"],
        tf.create_ti_line_item_payload(after_first["version"],
                                       description="Medical gas rough-in, full floor",
                                       category="MEDICAL_GAS", cost_amount=20000.00),
        LEASING_AGENT)
    validate_error(refused, ApiErrorId.ERR_TI_ALLOWANCE_EXCEEDED)

    unchanged = fx.read_project(api, project["id"])
    assert_project_rollups(unchanged, 90000.00, 60000.00, 10000.00, 1)
    assert unchanged["version"] == after_first["version"], (
        "a refused append must not advance the project version")

    second = fx.add_line_item(api, project["id"], after_first["version"],
                              description="Medical gas rough-in, single room",
                              category="MEDICAL_GAS", cost_amount=16000.00)
    assert second["sequence_no"] == 2, (
        "the surviving second line takes sequence_no 2, got {}".format(second["sequence_no"]))
    assert_line_split(second, 0.6000, 9600.00, 6400.00)

    final = fx.read_project(api, project["id"])
    assert_project_rollups(final, 99600.00, 66400.00, 400.00, 2)

    rows, meta = validate_paginated(api.list_ti_line_items(project["id"], LEASING_AGENT))
    assert_total_count(meta, 2)
    assert [row["sequence_no"] for row in rows] == [1, 2], (
        "the refused line must leave no gap in sequence_no")


def test_termination_is_blocked_by_outstanding_rent_unless_the_reason_is_default(api):
    """Only a DEFAULT termination bypasses the arrears gate; the suite and mix follow.

    "Termination is also the `PropertyManager`'s act and is admissible from `EXECUTED`, `ACTIVE` or `HOLDOVER`."
    "Unless the reason is `DEFAULT`, no invoice on the lease may still be in status `ISSUED` or `DELINQUENT`; otherwise the request is refused with `ERR_OUTSTANDING_RENT_BALANCE`."
    "A default termination bypasses that check precisely because unpaid rent is the usual reason for it."
    "**Hop 1** stamps `terminated_on` with the clock date, moves the demised suite to `VACANT`, sets that suite's `last_vacated_on` to the clock date and advances the suite's `version`."
    "Both routes back to `VACANT` stamp `last_vacated_on` with the clock date and advance the suite's `version`."
    "The counted lease set for a building comprises the leases whose `building_id` is that building, whose status is `EXECUTED`, `ACTIVE` or `HOLDOVER`, and whose `lease_type` is `DIRECT` or `MASTER`."
    "`leased_rentable_sf` is the sum of those two figures, and `vacant_rentable_sf` is the building's `total_rentable_sf` less `leased_rentable_sf` — the two are conserved partners and must always add back to `total_rentable_sf`."
    "`anchor_share_pct` is `anchor_rentable_sf` divided by `leased_rentable_sf`, rounded half up to 4 decimal places; when `leased_rentable_sf` is zero the share reads 0.0000 rather than being undefined."
    "Otherwise, if `anchor_share_pct` is strictly greater than 0.7500 the posture is `RESTRICTED`; otherwise, if it is strictly greater than 0.6000 the posture is `ANCHOR_CONCENTRATED`; otherwise it is `BALANCED`."

    Design: Corner/endpoints/terminate_blocked_by_outstanding_rent_unless_the_reason_is_default
    """
    ctx = fx.active_lease(api)
    lease_a = ctx["lease"]
    extra = fx.add_lease_on_new_suite(api, ctx, tenant_overrides={
        "legal_name": "Cedar Ridge Eye Associates PC",
        "primary_specialty": "OPHTHALMOLOGY",
    })
    lease_b = fx.drive_to_active(api, extra["lease"], extra["tenant"])

    invoice_a = fx.issue_invoice(api, lease_a["id"], "2026-09-01", "2026-09-30", "2026-09-30")
    fx.issue_invoice(api, lease_b["id"], "2026-09-01", "2026-09-30", "2026-09-30")

    validate_error(api.terminate_lease(lease_a["id"], tf.terminate_payload("MUTUAL"),
                                       PROPERTY_MANAGER),
                   ApiErrorId.ERR_OUTSTANDING_RENT_BALANCE)
    assert fx.read_lease(api, lease_a["id"])["status"] == "ACTIVE", (
        "a refused termination leaves the lease ACTIVE")
    assert fx.read_suite(api, ctx["suite"]["id"])["occupancy_status"] == "OCCUPIED", (
        "a refused termination leaves the suite OCCUPIED")

    defaulted = validate_success(api.terminate_lease(
        lease_b["id"], tf.terminate_payload("DEFAULT"), PROPERTY_MANAGER), 200)
    assert defaulted["status"] == "TERMINATED", (
        "a DEFAULT termination bypasses the arrears gate, got {}".format(defaulted["status"]))
    assert defaulted["terminated_on"] == "2026-09-01", (
        "terminated_on takes the clock date, got {}".format(defaulted["terminated_on"]))
    rows_b, _meta_b = validate_paginated(
        api.list_lease_rent_invoices(lease_b["id"], PROPERTY_MANAGER))
    assert rows_b[0]["status"] == "ISSUED", (
        "the unpaid invoice survives a DEFAULT termination, got {}".format(rows_b[0]["status"]))

    paid = validate_success(api.pay_rent_invoice(invoice_a["id"],
                                                 tf.payment_payload(16500.00),
                                                 PROPERTY_MANAGER), 200)
    assert_money_equals(paid["amount_paid"], 16500.00, "amount_paid")
    assert paid["days_past_due"] == 0, (
        "a payment before the due date reads zero days past due, got {}".format(
            paid["days_past_due"]))

    mutual = validate_success(api.terminate_lease(
        lease_a["id"], tf.terminate_payload("MUTUAL"), PROPERTY_MANAGER), 200)
    assert mutual["status"] == "TERMINATED", (
        "with the balance settled MUTUAL is admissible, got {}".format(mutual["status"]))
    assert mutual["termination_reason"] == "MUTUAL", (
        "expected termination_reason MUTUAL, got {}".format(mutual["termination_reason"]))
    assert mutual["terminated_on"] == "2026-09-01", (
        "terminated_on takes the clock date, got {}".format(mutual["terminated_on"]))

    suite_a = fx.read_suite(api, ctx["suite"]["id"])
    assert suite_a["occupancy_status"] == "VACANT", (
        "termination returns the suite to VACANT, got {}".format(suite_a["occupancy_status"]))
    assert suite_a["last_vacated_on"] == "2026-09-01", (
        "last_vacated_on takes the clock date, got {}".format(suite_a["last_vacated_on"]))

    building = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(building, 0, 0, 0, 100000, 0.0000, "BALANCED")


def test_booking_cancellation_is_refused_once_the_window_has_started(api):
    """Cancellation is admissible strictly before the window opens, and only once.

    "Cancellation is admissible only while `window_start` is still later than the clock — a booking already under way cannot be cancelled — and it moves the booking `BOOKED → CANCELLED` with `cancellation_source` recorded as `REQUESTED` and `version` advanced."
    "33. The clock date is on or after `term_start` for a commencement, and a booking cancellation is attempted strictly before `window_start` — otherwise `ERR_TERM_NOT_YET_STARTED` (422). This guards `POST /leases/{id}/commence` and `POST /shared-space-bookings/{id}/cancel`."
    "A violation is `ERR_INVALID_RECORD_STATE` (409)."
    "Bookings can be listed and narrowed by `shared_space_id`, by `lease_id` and by `status`, which is the only channel through which cascade-cancelled bookings become visible."

    Design: Corner/endpoints/booking_cancel_is_refused_once_the_window_has_started
    """
    ctx = fx.bookable_lease(api, space_overrides={
        "name": "Level 3 Infusion Bay",
        "space_type": "INFUSION_BAY",
        "capacity_seats": 8,
    })
    space_id = ctx["shared_space"]["id"]
    lease_id = ctx["lease"]["id"]

    started = fx.book(api, space_id, lease_id, "2026-09-10T09:00:00Z",
                      "2026-09-10T10:00:00Z", 3)
    future = fx.book(api, space_id, lease_id, "2026-09-20T09:00:00Z",
                     "2026-09-20T10:00:00Z", 3)

    fx.set_clock(api, "2026-09-10T09:30:00Z")

    validate_error(api.cancel_booking(started["id"],
                                      tf.cancel_booking_payload("Too late to stand down"),
                                      LEASING_AGENT),
                   ApiErrorId.ERR_TERM_NOT_YET_STARTED)
    still_booked = validate_success(api.get_booking(started["id"], LEASING_AGENT), 200)
    assert still_booked["status"] == "BOOKED", (
        "the in-flight booking stays BOOKED, got {}".format(still_booked["status"]))
    assert still_booked["version"] == started["version"], (
        "a refused cancellation must not advance the booking version")

    cancelled = validate_success(api.cancel_booking(
        future["id"], tf.cancel_booking_payload("Clinic rescheduled"), LEASING_AGENT), 200)
    assert cancelled["status"] == "CANCELLED", (
        "expected CANCELLED, got {}".format(cancelled["status"]))
    assert cancelled["cancellation_source"] == "REQUESTED", (
        "expected cancellation_source REQUESTED, got {}".format(
            cancelled["cancellation_source"]))
    assert_version_advanced_by(future, cancelled, 1)

    validate_error(api.cancel_booking(future["id"],
                                      tf.cancel_booking_payload("Already stood down"),
                                      LEASING_AGENT),
                   ApiErrorId.ERR_INVALID_RECORD_STATE)

    rows, meta = validate_paginated(api.list_bookings(
        LEASING_AGENT, {"shared_space_id": space_id, "status": "BOOKED"}))
    assert_total_count(meta, 1)
    assert ids_of(rows) == [started["id"]], (
        "only the in-flight booking remains BOOKED")
