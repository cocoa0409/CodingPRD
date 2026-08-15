"""Contribution reports: dual dues variants and inclusion-set rules (PRD §3.7)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_provisional_includes_open_logs(api):
    """PRD §3.7: "The provisional variant runs at creation: for each listed log
    whose status is `OPEN` or `SUBMITTED`, the log's wage contribution is the
    lesser of its assignment's `daily_rate_cents` and the production tier's
    daily wage cap — 100,000 cents (one thousand dollars) for
    `ULTRA_LOW_BUDGET`" and "`provisional_contributions_due_cents` multiplies
    that base by the tier's rate numerator — 17 for `ULTRA_LOW_BUDGET`".
    A SUBMITTED CAMERA log at 120,000 caps to 100,000; an OPEN SOUND log at
    80,000 still counts: gross 180,000, dues 180,000 x 17/100 = 30,600 cents.

    Design: Difficulty/dual_variant_calc/contribution_report_provisional_includes_open_logs_final_excludes
    """
    bundle = th.create_in_production(
        "Canyon Films LLC", "12-3456789", title="Desert Night",
        crew=(("W-CAM-1", "CAMERA", "DIRECTOR_OF_PHOTOGRAPHY", 120_000),
              ("W-GRIP-1", "GRIP_ELECTRIC", "KEY_GRIP", 90_000),
              ("W-SND-1", "SOUND", "SOUND_MIXER", 80_000)),
        activate=("W-CAM-1", "W-SND-1"),
    )
    company = bundle["company"]
    log1 = th.submit_log(th.record_log(bundle["assignments"]["W-CAM-1"], company,
                                       "2026-08-10"), company)
    log2 = th.record_log(bundle["assignments"]["W-SND-1"], company,
                         "2026-08-10", 480, 900)  # left OPEN

    report = th.create_report(bundle["production"], company, 1,
                              [log1["id"], log2["id"]])
    th.assert_contribution_report(report)
    assert report["status"] == "DRAFT"
    assert report["provisional_gross_wages_cents"] == 180_000
    assert report["provisional_contributions_due_cents"] == 30_600


def test_final_excludes_open_logs(api):
    """PRD §3.7: "Submission locks the final numbers. Moving a report from
    `DRAFT` to `SUBMITTED` ... computes the final variant: only listed logs
    whose status is `SUBMITTED` contribute — logs still `OPEN` contribute
    zero". Same inclusion set as at creation, but the still-OPEN SOUND log
    drops out: final gross 100,000 (the capped 120,000 CAMERA log), final dues
    17,000 cents at the ULB rate.

    Design: Difficulty/dual_variant_calc/contribution_report_provisional_includes_open_logs_final_excludes
    """
    bundle = th.create_in_production(
        "Canyon Films LLC", "12-3456789", title="Desert Night",
        crew=(("W-CAM-1", "CAMERA", "DIRECTOR_OF_PHOTOGRAPHY", 120_000),
              ("W-GRIP-1", "GRIP_ELECTRIC", "KEY_GRIP", 90_000),
              ("W-SND-1", "SOUND", "SOUND_MIXER", 80_000)),
        activate=("W-CAM-1", "W-SND-1"),
    )
    company = bundle["company"]
    log1 = th.submit_log(th.record_log(bundle["assignments"]["W-CAM-1"], company,
                                       "2026-08-10"), company)
    log2 = th.record_log(bundle["assignments"]["W-SND-1"], company,
                         "2026-08-10", 480, 900)  # left OPEN

    report = th.create_report(bundle["production"], company, 1,
                              [log1["id"], log2["id"]])
    submitted = th.submit_report(report, company)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["final_gross_wages_cents"] == 100_000
    assert submitted["final_contributions_due_cents"] == 17_000


def test_final_gross_applies_tier_wage_cap(api):
    """PRD §3.7: "the log's wage contribution is the lesser of its assignment's
    `daily_rate_cents` and the production tier's daily wage cap — 100,000 cents
    (one thousand dollars) for `ULTRA_LOW_BUDGET`". Of three SUBMITTED logs at
    120,000 / 95,000 / 80,000, only the CAMERA log caps: final gross is
    100,000 + 95,000 + 80,000 = 275,000 cents.

    Design: Difficulty/combinatorial_formula/contribution_dues_tier_cap_branch_and_single_rounding
    """
    bundle = th.create_in_production(
        "Delta Motion LLC", "22-1111111", title="Delta Run", scope="TELEVISION",
        crew=(("W-CAM-1", "CAMERA", "DIRECTOR_OF_PHOTOGRAPHY", 120_000),
              ("W-GRIP-1", "GRIP_ELECTRIC", "KEY_GRIP", 95_000),
              ("W-SND-1", "SOUND", "SOUND_MIXER", 80_000)),
        activate=("W-CAM-1", "W-GRIP-1", "W-SND-1"),
    )
    company = bundle["company"]
    logs = [
        th.submit_log(th.record_log(bundle["assignments"][ref], company, date),
                      company)
        for ref, date in (("W-CAM-1", "2026-08-10"), ("W-GRIP-1", "2026-08-11"),
                          ("W-SND-1", "2026-08-12"))
    ]
    report = th.create_report(bundle["production"], company, 1,
                              [l["id"] for l in logs])
    submitted = th.submit_report(report, company)
    assert submitted["final_gross_wages_cents"] == 275_000


def test_final_dues_single_rounding(api):
    """PRD §3.7: "`provisional_contributions_due_cents` multiplies that base by
    the tier's rate numerator — 17 for `ULTRA_LOW_BUDGET`, 18 for
    `MODIFIED_LOW_BUDGET`, 19 for `LOW_BUDGET`, 20 for `BASIC` — and divides by
    100, with the multiplication performed first and a single round-half-up to
    whole cents at the end." Gross 275,000 at rate 17: 275,000 x 17 / 100 =
    46,750 exactly.

    Design: Difficulty/combinatorial_formula/contribution_dues_tier_cap_branch_and_single_rounding
    """
    bundle = th.create_in_production(
        "Delta Motion LLC", "22-1111111", title="Delta Run", scope="TELEVISION",
        crew=(("W-CAM-1", "CAMERA", "DIRECTOR_OF_PHOTOGRAPHY", 120_000),
              ("W-GRIP-1", "GRIP_ELECTRIC", "KEY_GRIP", 95_000),
              ("W-SND-1", "SOUND", "SOUND_MIXER", 80_000)),
        activate=("W-CAM-1", "W-GRIP-1", "W-SND-1"),
    )
    company = bundle["company"]
    logs = [
        th.submit_log(th.record_log(bundle["assignments"][ref], company, date),
                      company)
        for ref, date in (("W-CAM-1", "2026-08-10"), ("W-GRIP-1", "2026-08-11"),
                          ("W-SND-1", "2026-08-12"))
    ]
    report = th.create_report(bundle["production"], company, 1,
                              [l["id"] for l in logs])
    submitted = th.submit_report(report, company)
    assert submitted["final_contributions_due_cents"] == 46_750


def test_empty_log_set_rejected(api):
    """PRD §3.7: "a `period_index` of at least 1, and a `work_day_log_ids`
    list — an explicit, non-empty inclusion set; an empty list is
    `ERR_EMPTY_REPORT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/contribution_report_empty_log_set_rejected
    """
    bundle = _production_with_active_cam("Orchid Peak LLC", "12-0000001")
    production, company = bundle["production"], bundle["company"]

    resp = api.create_contribution_report(
        th.create_contribution_report_payload(
            production_id=production["id"], period_index=1, work_day_log_ids=[],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_EMPTY_REPORT)


def _production_with_active_cam(name, fein):
    return th.create_in_production(legal_name=name, fein=fein, scope="NEW_MEDIA",
                                   activate=("W-CAM-1",))


def test_single_log_report_created(api):
    """PRD §3.7: "a `work_day_log_ids` list — an explicit, non-empty inclusion
    set; an empty list is `ERR_EMPTY_REPORT` (HTTP 422). A new report starts
    `DRAFT`." A one-element inclusion set clears the non-empty boundary.

    Design: Difficulty/boundary_precision_check/contribution_report_empty_log_set_rejected
    """
    bundle = _production_with_active_cam("Orchid Peak LLC", "12-0000001")
    production, company = bundle["production"], bundle["company"]
    log = th.record_log(bundle["assignments"]["W-CAM-1"], company, "2026-08-10")

    report = th.create_report(production, company, 1, [log["id"]])
    th.assert_contribution_report(report)
    assert report["status"] == "DRAFT"


def test_voided_log_dropped_from_final(api):
    """PRD §3.5: "From the moment it is voided, the log is excluded from all
    contribution and audit aggregates." PRD §3.7: "only listed logs whose
    status is `SUBMITTED` contribute". Provisional at creation covers both
    SUBMITTED logs (100,000 + 95,000 at the ULB cap/rate: 195,000 x 17/100 =
    33,150); after one is voided, the final variant covers only the survivor:
    100,000 x 17/100 = 17,000.

    Design: Corner/calculations/voided_log_excluded_from_report_final
    """
    bundle = th.create_in_production(
        "Amaranth LLC", "20-0000026", title="Amaranth Bed",
        crew=(("W-CAM-1", "CAMERA", "CAMERA_OPERATOR", 100_000),
              ("W-GRIP-1", "GRIP_ELECTRIC", "GAFFER", 95_000),
              ("W-SND-1", "SOUND", "BOOM_OPERATOR", 80_000)),
        activate=("W-CAM-1", "W-GRIP-1"),
    )
    company = bundle["company"]
    log1 = th.submit_log(th.record_log(bundle["assignments"]["W-CAM-1"], company,
                                       "2026-08-10"), company)
    log2 = th.submit_log(th.record_log(bundle["assignments"]["W-GRIP-1"], company,
                                       "2026-08-11"), company)
    report = th.create_report(bundle["production"], company, 1,
                              [log1["id"], log2["id"]])
    assert report["provisional_contributions_due_cents"] == 33_150

    th.void_log(log2, company)
    submitted = th.submit_report(report, company)
    assert submitted["final_gross_wages_cents"] == 100_000
    assert submitted["final_contributions_due_cents"] == 17_000


def test_review_draft_report_rejected(api, fund_trustee_headers):
    """PRD §3.7: "A `FundTrustee` then reviews a `SUBMITTED` report with a
    `decision`." Review requires the report to be SUBMITTED; the contribution
    report from-state gate is `ERR_REPORT_STATE` (PRD §2.10: "the from-state
    gates for ... contribution reports (`ERR_REPORT_STATE`)").

    Design: Corner/state_machines/report_review_from_draft_rejected
    """
    bundle = _production_with_active_cam("Knotweed LLC", "20-0000011")
    production, company = bundle["production"], bundle["company"]
    log = th.submit_log(
        th.record_log(bundle["assignments"]["W-CAM-1"], company, "2026-08-10"),
        company,
    )
    report = th.create_report(production, company, 1, [log["id"]])
    assert report["status"] == "DRAFT"

    resp = api.review_contribution_report(report["id"], {"decision": "ACCEPT"},
                                          fund_trustee_headers)
    th.validate_error(resp, E.ERR_REPORT_STATE)

    reports, _ = th.validate_paginated(
        api.list_production_contribution_reports(production["id"],
                                                 th.owner_headers(company))
    )
    current = next(r for r in reports if r["id"] == report["id"])
    assert current["status"] == "DRAFT", "rejected review must not change state"


def test_duplicate_period_then_freed_by_rejection(api, fund_trustee_headers):
    """PRD §3.7: "Only one report per production and period may occupy the live
    statuses — a `DRAFT`, `SUBMITTED`, or `ACCEPTED` report already covering
    the same `period_index` triggers `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409)"
    and "Rejection requires a `rejection_reason`, records it, moves the report
    to `REJECTED`, and frees the listed logs for a replacement report."

    Design: Corner/validations/duplicate_report_period_rejected_then_freed_by_rejection
    """
    bundle = _production_with_active_cam("Hartstongue LLC", "20-0000035")
    production, company = bundle["production"], bundle["company"]
    log = th.submit_log(
        th.record_log(bundle["assignments"]["W-CAM-1"], company, "2026-08-10"),
        company,
    )
    report1 = th.create_report(production, company, 1, [log["id"]])

    resp = api.create_contribution_report(
        th.create_contribution_report_payload(
            production_id=production["id"], period_index=1,
            work_day_log_ids=[log["id"]],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_DUPLICATE_REPORT_PERIOD)

    th.submit_report(report1, company)
    rejected = th.review_report(report1, "REJECT", "ft_1",
                                reason="Missing supporting timecards")
    assert rejected["status"] == "REJECTED"

    report2 = th.create_report(production, company, 1, [log["id"]])
    assert report2["status"] == "DRAFT", "period and log freed after rejection"
    assert report2["id"] != report1["id"]


def test_already_reported_log_rejected(api, fund_trustee_headers):
    """PRD §3.7: "must not already appear on another `ACCEPTED` report of the
    production (`ERR_LOG_ALREADY_REPORTED`, HTTP 409)" and "Acceptance moves it
    to `ACCEPTED` and marks every listed log as reported, so future reports
    naming those logs fail with `ERR_LOG_ALREADY_REPORTED`."

    Design: Corner/validations/already_reported_log_rejected_from_second_report
    """
    bundle = th.setup_accepted_report("Iceplant LLC", "20-0000036", period=1)
    production, company, log = bundle["production"], bundle["company"], bundle["log"]

    resp = api.create_contribution_report(
        th.create_contribution_report_payload(
            production_id=production["id"], period_index=2,
            work_day_log_ids=[log["id"]],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_LOG_ALREADY_REPORTED)

    reports, _ = th.validate_paginated(
        api.list_production_contribution_reports(production["id"],
                                                 th.owner_headers(company))
    )
    assert len(reports) == 1, "rejected create must not add a report"


def test_unionrep_cannot_review_report(api, union_rep_headers):
    """PRD §2.1: "A request whose role is authenticated but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD §3.7: "A `FundTrustee` then reviews a `SUBMITTED` report
    with a `decision`."

    Design: Corner/rbac/unionrep_cannot_review_contribution_report
    """
    bundle = _production_with_active_cam("Valerian LLC", "20-0000049")
    production, company = bundle["production"], bundle["company"]
    log = th.submit_log(
        th.record_log(bundle["assignments"]["W-CAM-1"], company, "2026-08-10"),
        company,
    )
    report = th.submit_report(th.create_report(production, company, 1, [log["id"]]),
                              company)
    assert report["status"] == "SUBMITTED"

    resp = api.review_contribution_report(report["id"], {"decision": "ACCEPT"},
                                          union_rep_headers)
    th.validate_error(resp, E.ERR_UNAUTHORIZED_ROLE)

    reports, _ = th.validate_paginated(
        api.list_production_contribution_reports(production["id"],
                                                 th.owner_headers(company))
    )
    current = next(r for r in reports if r["id"] == report["id"])
    assert current["status"] == "SUBMITTED", "denied review must not change state"
