"""Corner sections: errors, cross_cutting_complexity_layers, consistency_model
(PRD §2.8, §2.9, §3.2, §3.3, §3.5, §3.6).

Offering-duration upper bound, run-purchase stale-version, segregation of duties,
correct-version run success, contribution-rate boundary, accrual reconciliation,
and immediate contribution-accumulator visibility.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_plan_payload,
    create_offering_payload,
    create_participant_payload,
    create_enrollment_payload,
    create_purchase_period_payload,
    create_contribution_payload,
    run_purchase_payload,
    make_participant_headers,
    make_admin_headers,
    make_officer_headers,
)


# ─── errors ────────────────────────────────────────────────────────
def test_error_offering_duration_exceeds_max(api, admin_headers):
    """PRD §3.2: "The duration_months must be at least 6 and at most 24; a value
    outside that inclusive range is rejected with ERR_OFFERING_DURATION (HTTP 422)."

    duration_months = 25 is one above the inclusive upper bound => ERR_OFFERING_DURATION.

    Design: Corner/errors/error_offering_duration_exceeds_max
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    resp = api.create_offering_period(
        create_offering_payload(plan["id"], duration_months=25), admin_headers
    )
    validate_error(resp, "ERR_OFFERING_DURATION")


def _certified_batch(api, admin_headers, officer_id="officer1"):
    """ENROLLMENT_CLOSED offering, one enrolled+contributing participant, batch opened
    and certified by officer_id. Returns (participant, batch_id, open_version,
    certify_version)."""
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(
            create_offering_payload(plan["id"], duration_months=6, grant_date_fmv_cents=1000),
            admin_headers,
        )
    )
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=10
            ),
            make_participant_headers(participant["id"]),
        )
    )
    get_success_data(
        api.create_contribution(
            create_contribution_payload(enrollment["id"]), admin_headers
        )
    )
    get_success_data(api.close_enrollment(offering["id"], admin_headers))
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"],
            create_purchase_period_payload(
                purchase_date="2024-06-30T00:00:00.000Z", purchase_date_fmv_cents=1200
            ),
            admin_headers,
        )
    )
    opened = get_success_data(api.open_purchase_period(batch["id"], admin_headers))
    certified = get_success_data(
        api.certify_purchase_period(batch["id"], make_officer_headers(officer_id))
    )
    return participant, batch["id"], opened["version"], certified["version"]


def test_error_stale_version_on_run_purchase(api, admin_headers):
    """PRD §3.5: "The supplied expected_purchase_period_version must equal the batch's
    current version, or the run is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §2.8: "The server compares this value against the purchase period's current
    version; if they do not match ... the run is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Running with current_version - 1 (and a different admin than the certifier to avoid
    the segregation guard) => ERR_STALE_VERSION.

    Design: Corner/errors/error_stale_version_on_run_purchase
    """
    _, batch_id, _, version = _certified_batch(api, admin_headers, officer_id="officer1")
    resp = api.run_purchase(
        batch_id, run_purchase_payload(version - 1), make_admin_headers("admin2")
    )
    validate_error(resp, "ERR_STALE_VERSION")


# ─── cross_cutting_complexity_layers ───────────────────────────────
def test_occ_correct_version_run_purchase_succeeds(api, admin_headers):
    """PRD §3.5: "An administrator runs the buy against a CERTIFIED batch, supplying
    expected_purchase_period_version; the batch advances from CERTIFIED to PURCHASED."
    PRD §2.4: "an integer version that begins at 1 and increments by one on every
    mutation."

    Running with the correct current version (different admin than the certifier)
    succeeds (200), moves the batch to PURCHASED, and bumps version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_run_purchase_succeeds
    """
    _, batch_id, _, version = _certified_batch(api, admin_headers, officer_id="officer1")
    result = validate_success(
        api.run_purchase(batch_id, run_purchase_payload(version), make_admin_headers("admin2"))
    )
    assert result["status"] == "PURCHASED", result
    assert result["version"] == version + 1, result


def test_rate_threshold_at_exact_max_accepted(api, admin_headers):
    """PRD §3.3: "then it rejects a contribution_rate_pct that is not greater than 0 or
    that exceeds the plan's max_contribution_rate_pct with ERR_RATE_EXCEEDS_LIMIT
    (HTTP 422)".
    PRD §3.1: "a max_contribution_rate_pct capping the per-paycheck withholding rate
    (defaulting to 15, and constrained to be greater than 0 and at most 15)".

    A rate exactly equal to the plan max (15) does not exceed it => accepted (201).

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_at_exact_max_accepted
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    enr = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=15
            ),
            make_participant_headers(participant["id"]),
        ),
        expected_status=201,
    )
    assert enr["contribution_rate_pct"] == 15, enr


def test_accrual_derived_field_reconciled_after_purchase(api, admin_headers):
    """PRD §3.6: "After the buy, the charged grant_date_value_applied_cents is added
    into the participant-year's accrued_grant_value_cents, and the
    remaining_capacity_cents is recomputed accordingly."
    PRD §3.6: "the remaining_capacity_cents, which is the plan's annual limit in
    dollars multiplied by 100 minus the accrued grant value, floored at 0 ... With the
    default limit of 25000 dollars, the annual ceiling is 2,500,000 cents".

    gross 1000000 at 10% => 100000c; price 850 => 117 shares; grant value 117*1000 =
    117000; remaining 2500000 - 117000 = 2383000.

    Design: Corner/cross_cutting_complexity_layers/accrual_derived_field_reconciled_after_purchase
    """
    participant, batch_id, _, version = _certified_batch(api, admin_headers, "officer1")
    get_success_data(
        api.run_purchase(batch_id, run_purchase_payload(version), make_admin_headers("admin2"))
    )
    ledgers, _ = _list(api, api.list_accrual_ledgers, admin_headers,
                       {"participant_id": participant["id"], "calendar_year": 2024})
    rows = [l for l in ledgers if l["calendar_year"] == 2024]
    assert len(rows) == 1, ledgers
    assert rows[0]["accrued_grant_value_cents"] == 117000, rows[0]
    assert rows[0]["remaining_capacity_cents"] == 2383000, rows[0]


# ─── consistency_model ─────────────────────────────────────────────
def test_contribution_accumulator_visible_immediately(api, admin_headers):
    """PRD §3.3: "The system computes the withheld amount_cents by multiplying
    gross_pay_cents by the enrollment's contribution_rate_pct, dividing by 100, and
    taking the floor of the result. That amount is added to the enrollment's
    accumulated_contribution_cents."

    Two contributions (gross 500000 + 300000 at 10% => 50000 + 30000) make
    accumulated_contribution_cents == 80000, visible on the immediately following GET.

    Design: Corner/consistency_model/contribution_accumulator_visible_immediately
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=10
            ),
            make_participant_headers(participant["id"]),
        )
    )
    get_success_data(
        api.create_contribution(
            create_contribution_payload(enrollment["id"], gross_pay_cents=500000),
            admin_headers,
        )
    )
    get_success_data(
        api.create_contribution(
            create_contribution_payload(enrollment["id"], gross_pay_cents=300000),
            admin_headers,
        )
    )
    refreshed = validate_success(api.get_enrollment(enrollment["id"], admin_headers))
    assert refreshed["accumulated_contribution_cents"] == 80000, refreshed


def _list(api, list_fn, headers, params):
    resp = list_fn(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]
