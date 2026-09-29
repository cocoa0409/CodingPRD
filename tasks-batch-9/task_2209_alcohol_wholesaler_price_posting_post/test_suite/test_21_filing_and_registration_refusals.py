"""Refusals that guard filing: licence standing, brand registration, uniqueness,
segregation of duties, the certification window, and the clean on-time path.

Each refusal is paired with the neighbouring admission that proves the boundary is
where the PRD puts it and not one step away from it.
"""

from typing import Any, Dict

from test_helpers import (
    approve_brand,
    certify_schedule,
    create_brand_payload,
    create_compliance_audit_payload,
    create_price_schedule_item_payload,
    create_price_schedule_payload,
    list_findings,
    make_certifying_officer_headers,
    make_filing_agent_headers,
    new_brand,
    new_certifying_officer,
    new_dual_role_user,
    new_filing_agent,
    new_invoice,
    new_invoice_line,
    new_item,
    new_schedule,
    new_state_program,
    new_wholesaler,
    read_audit,
    read_brand,
    read_invoice,
    read_invoice_line,
    read_item,
    read_schedule,
    read_wholesaler,
    regulator_headers,
    set_clock,
    set_license_status,
    setup_draft_schedule,
    setup_effective_schedule,
    setup_licensee_base,
    submit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Local scene helper
# --------------------------------------------------------------------------

def _two_wholesalers_submitted(clock: str) -> Dict[str, Any]:
    """Two wholesalers of one program, each with a submitted (not yet certified) 2026-09
    schedule. The clock is left at `clock`, which is also each schedule's `filed_at`."""
    set_clock(clock)
    program = new_state_program()

    wholesaler_a = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Beverage"
    )
    wholesaler_b = new_wholesaler(
        program["id"], license_number="W-2002", legal_name="Gulf Coast Distributing"
    )
    agent_a, agent_a_headers = new_filing_agent(wholesaler_a["id"], "Fay Filer")
    certifier_a, certifier_a_headers = new_certifying_officer(wholesaler_a["id"], "Cora Certifier")
    agent_b, agent_b_headers = new_filing_agent(wholesaler_b["id"], "Ben Filer")
    certifier_b, certifier_b_headers = new_certifying_officer(wholesaler_b["id"], "Bea Certifier")

    brand_a = new_brand(wholesaler_a["id"], agent_a_headers, approve=True)
    brand_b = new_brand(wholesaler_b["id"], agent_b_headers, approve=True)

    schedule_a = new_schedule(
        wholesaler_a["id"], program["id"], agent_a_headers, posting_month="2026-09"
    )
    item_a = new_item(schedule_a["id"], brand_a["id"], agent_a_headers)
    schedule_a = submit_schedule(schedule_a["id"], agent_a_headers)

    schedule_b = new_schedule(
        wholesaler_b["id"], program["id"], agent_b_headers, posting_month="2026-09"
    )
    item_b = new_item(
        schedule_b["id"],
        brand_b["id"],
        agent_b_headers,
        case_price_cents=110_000,
        unit_price_cents=10_000,
    )
    schedule_b = submit_schedule(schedule_b["id"], agent_b_headers)

    return {
        "program": program,
        "wholesaler_a": wholesaler_a,
        "wholesaler_b": wholesaler_b,
        "agent_a": agent_a,
        "agent_a_headers": agent_a_headers,
        "certifier_a": certifier_a,
        "certifier_a_headers": certifier_a_headers,
        "agent_b": agent_b,
        "agent_b_headers": agent_b_headers,
        "certifier_b": certifier_b,
        "certifier_b_headers": certifier_b_headers,
        "schedule_a": schedule_a,
        "item_a": item_a,
        "schedule_b": schedule_b,
        "item_b": item_b,
    }


# --------------------------------------------------------------------------
# Licence standing (priority 9)
# --------------------------------------------------------------------------

def test_01_suspended_licence_blocks_submission_and_reinstatement_lets_it_through(api):
    """PRD §2.10: "The governing wholesaler's `license_status` is `ACTIVE`. Otherwise
    `ERR_LICENSE_NOT_ACTIVE` (409). Applies to exactly two endpoints:
    `POST /price-schedules/{id}/submit` and `POST /retailer-invoices/{id}/validate`.
    A suspended licensee may neither file nor invoice."
    PRD §3.3: "When `is_late` comes out `false`, none of this happens: no counter moves,
    no penalty accrues, and the wholesaler's `version` and `updated_at` are left exactly
    as they were."

    Design: Corner/validations/suspended_license_blocks_submission_and_reinstatement_lets_the_same_schedule_through
    """
    scene = setup_draft_schedule(setup_licensee_base())
    schedule_id = scene["schedule"]["id"]
    wholesaler_id = scene["wholesaler"]["id"]

    set_license_status(wholesaler_id, "SUSPENDED")
    validate_error(
        api.submit_price_schedule(schedule_id, scene["agent_headers"]),
        "ERR_LICENSE_NOT_ACTIVE",
        409,
    )

    blocked = read_schedule(schedule_id)
    assert blocked["status"] == "DRAFT", (
        f"the refused schedule stays DRAFT, got {blocked['status']}"
    )
    assert blocked["filed_at"] is None, (
        f"filed_at must stay unset, got {blocked['filed_at']}"
    )
    assert blocked["filed_by_user_id"] is None, (
        f"filed_by_user_id must stay unset, got {blocked['filed_by_user_id']}"
    )
    assert blocked["is_late"] is False, (
        f"is_late must stay false, got {blocked['is_late']}"
    )

    # Reinstatement makes the very same schedule filable.
    set_license_status(wholesaler_id, "ACTIVE")
    filed = validate_success(api.submit_price_schedule(schedule_id, scene["agent_headers"]))
    assert filed["status"] == "SUBMITTED", (
        f"the reinstated licensee's filing must land in SUBMITTED, got {filed['status']}"
    )
    assert filed["filed_by_user_id"] == scene["agent"]["id"], (
        f"filed_by_user_id must record the acting agent {scene['agent']['id']}, got "
        f"{filed['filed_by_user_id']}"
    )
    assert filed["is_late"] is False, (
        f"filing on 2026-08-01 beats the 2026-09-10 deadline, got is_late {filed['is_late']}"
    )

    wholesaler_after = read_wholesaler(wholesaler_id)
    assert wholesaler_after["license_status"] == "ACTIVE", (
        f"the licence is back to ACTIVE, got {wholesaler_after['license_status']}"
    )
    assert wholesaler_after["late_filing_count"] == 0, (
        f"an on-time filing moves no counter, got {wholesaler_after['late_filing_count']}"
    )
    assert wholesaler_after["late_filing_penalty_accrued_cents"] == 0, (
        f"an on-time filing accrues nothing, got "
        f"{wholesaler_after['late_filing_penalty_accrued_cents']}"
    )


def test_02_suspended_licence_blocks_invoice_validation_of_an_already_built_invoice(api):
    """PRD §3.8: "It is invoked by a `FilingAgent` on the invoice's own wholesaler, and
    it requires that wholesaler's `license_status` to be `ACTIVE` (otherwise
    `ERR_LICENSE_NOT_ACTIVE`), that the invoice carry at least one line, and that the
    invoice's `audit_status` be `NOT_AUDITED` (either failure being `ERR_INVALID_STATE`)."
    PRD §3.8: "Every computed field of a new line — `gross_cents`,
    `quantity_discount_cents`, `allowed_promotional_cents`, `excess_promotional_cents`,
    `allowed_depletion_cents`, `excess_depletion_cents`, `net_price_cents`,
    `posted_gross_cents`, `variance_cents`, `finding_variance_cents` — starts at 0, and
    `is_off_posted` starts `false`; nothing is priced until validation runs."

    Design: Corner/validations/suspended_license_blocks_invoice_validation_of_an_already_built_invoice
    """
    scene = setup_effective_schedule()
    item = scene["items"][0]
    invoice = new_invoice(scene["wholesaler"]["id"], "2026-10-05T00:00:00Z", scene["agent_headers"])
    line = new_invoice_line(
        invoice["id"], item["id"], 120_000, 11_000, scene["agent_headers"], cases_quantity=2
    )

    set_license_status(scene["wholesaler"]["id"], "SUSPENDED")
    validate_error(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]),
        "ERR_LICENSE_NOT_ACTIVE",
        409,
    )

    blocked_invoice = read_invoice(invoice["id"])
    assert blocked_invoice["validation_status"] == "DRAFT", (
        f"the refused invoice stays DRAFT, got {blocked_invoice['validation_status']}"
    )
    assert blocked_invoice["subtotal_cents"] == 0, (
        f"nothing is priced before validation runs, got {blocked_invoice['subtotal_cents']}"
    )
    assert blocked_invoice["total_cents"] == 0, (
        f"nothing is priced before validation runs, got {blocked_invoice['total_cents']}"
    )
    assert blocked_invoice["line_count"] == 1, (
        f"the line survives the refusal, got line_count {blocked_invoice['line_count']}"
    )

    blocked_line = read_invoice_line(line["id"])
    assert blocked_line["gross_cents"] == 0, (
        f"gross_cents stays 0 until validation, got {blocked_line['gross_cents']}"
    )
    assert blocked_line["posted_gross_cents"] == 0, (
        f"posted_gross_cents stays 0 until validation, got {blocked_line['posted_gross_cents']}"
    )
    assert blocked_line["is_off_posted"] is False, (
        f"is_off_posted stays false until validation, got {blocked_line['is_off_posted']}"
    )

    set_license_status(scene["wholesaler"]["id"], "ACTIVE")
    validated = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"])
    )
    assert validated["validation_status"] == "VALIDATED", (
        f"two cases charged at the posted price are compliant, got "
        f"{validated['validation_status']}"
    )
    assert validated["subtotal_cents"] == 240_000, (
        f"two cases at 120,000 net to a 240,000 subtotal, got {validated['subtotal_cents']}"
    )
    assert validated["surcharge_cents"] == 0, (
        f"a 240,000 subtotal sits in the zero-rate band, got {validated['surcharge_cents']}"
    )
    assert validated["total_cents"] == 240_000, (
        f"total is subtotal plus surcharge, got {validated['total_cents']}"
    )


# --------------------------------------------------------------------------
# Brand registration and interval conflict (priorities 10 and 13)
# --------------------------------------------------------------------------

def test_03_submitting_a_schedule_whose_brand_is_still_pending_is_refused(api):
    """PRD §3.2: "A brand that is still `PENDING`, a brand that was `REJECTED`, or an
    approved brand whose registration expires before the month the prices would take
    effect all produce the same refusal, `ERR_BRAND_NOT_REGISTERED`."
    PRD §3.2: "The prerequisite bites at submission time rather than at item-creation
    time."
    PRD §3.3: "Items remain `DRAFT` right through submission; it is certification, not
    filing, that posts them."

    Design: Corner/validations/submitting_a_schedule_whose_brand_is_still_pending_returns_brand_not_registered
    """
    scene = setup_licensee_base(approve_brand_registration=False)
    schedule = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"]
    )
    # Item creation succeeds against a PENDING brand: the prerequisite bites at submit.
    item = new_item(schedule["id"], scene["brand"]["id"], scene["agent_headers"])

    validate_error(
        api.submit_price_schedule(schedule["id"], scene["agent_headers"]),
        "ERR_BRAND_NOT_REGISTERED",
        409,
    )
    assert read_brand(scene["brand"]["id"])["registration_status"] == "PENDING", (
        "the brand behind the refused filing is still awaiting approval"
    )
    assert read_schedule(schedule["id"])["status"] == "DRAFT", (
        "the refused schedule stays DRAFT"
    )

    approve_brand(scene["brand"]["id"])
    filed = validate_success(api.submit_price_schedule(schedule["id"], scene["agent_headers"]))
    assert filed["status"] == "SUBMITTED", (
        f"approval unblocks the identical filing, got {filed['status']}"
    )
    assert filed["item_count"] == 1, (
        f"the schedule still carries its single item, got {filed['item_count']}"
    )

    item_after = read_item(item["id"])
    assert item_after["status"] == "DRAFT", (
        f"items remain DRAFT right through submission, got {item_after['status']}"
    )


def test_04_brand_registration_interval_must_contain_the_effective_date(api):
    """PRD §3.2: "When a schedule is filed, every brand behind every one of its items
    must be in `APPROVED` status, and each such brand's closed registration interval must
    contain the schedule's `effective_date` — meaning `registration_effective_from` is at
    or before `effective_date` and `registration_expires_on` is at or after it."
    PRD §3.3: "A `posting_month` of `2026-09` therefore yields an `effective_date` of
    `2026-10-01T00:00:00.000Z`, and a `posting_month` of `2026-12` yields
    `2027-01-01T00:00:00.000Z`."

    Design: Corner/validations/brand_registration_interval_must_contain_the_effective_date_not_merely_the_filing_date
    """
    scene = setup_licensee_base(
        brand_overrides={"registration_expires_on": "2026-09-15T00:00:00Z"}
    )
    brand_id = scene["brand"]["id"]

    # 2026-08 takes effect on 2026-09-01, inside the registration; 2026-09 takes effect
    # on 2026-10-01, outside it. Both are filed on 2026-08-01, inside the registration.
    schedule_aug = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"],
        posting_month="2026-08",
    )
    new_item(schedule_aug["id"], brand_id, scene["agent_headers"])
    schedule_sep = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"],
        posting_month="2026-09",
    )
    new_item(schedule_sep["id"], brand_id, scene["agent_headers"])

    filed_aug = validate_success(
        api.submit_price_schedule(schedule_aug["id"], scene["agent_headers"])
    )
    assert filed_aug["status"] == "SUBMITTED", (
        f"the August schedule's effective date falls inside the registration, got "
        f"{filed_aug['status']}"
    )
    assert filed_aug["effective_date"] == "2026-09-01T00:00:00.000Z", (
        f"a posting_month of 2026-08 takes effect on 2026-09-01, got "
        f"{filed_aug['effective_date']}"
    )
    assert filed_aug["is_late"] is False, (
        f"filing on 2026-08-01 beats the 2026-08-10 deadline, got {filed_aug['is_late']}"
    )

    validate_error(
        api.submit_price_schedule(schedule_sep["id"], scene["agent_headers"]),
        "ERR_BRAND_NOT_REGISTERED",
        409,
    )
    refused = read_schedule(schedule_sep["id"])
    assert refused["status"] == "DRAFT", (
        f"the September schedule stays DRAFT, got {refused['status']}"
    )
    assert refused["filed_at"] is None, (
        f"the refused filing leaves filed_at unset, got {refused['filed_at']}"
    )
    assert read_brand(brand_id)["registration_status"] == "APPROVED", (
        "the brand is approved throughout — only the interval fails the September test"
    )


def test_05_registration_intervals_overlap_only_within_one_name_and_class(api):
    """PRD §3.2: "Registration intervals cannot overlap for a given combination of
    wholesaler, brand name and beverage class."
    PRD §3.2: "Because these are closed intervals, two registrations conflict when the
    requested `registration_effective_from` is at or before an existing registration's
    `registration_expires_on` **and** that existing registration's
    `registration_effective_from` is at or before the requested `registration_expires_on`
    — intervals that merely touch at an endpoint do overlap."

    Design: Corner/validations/brand_registration_intervals_overlap_only_within_the_same_brand_name_and_beverage_class
    """
    scene = setup_licensee_base()
    wholesaler_id = scene["wholesaler"]["id"]
    agent_headers = scene["agent_headers"]

    # Same interval, different beverage class: no conflict.
    other_class = validate_success(
        api.create_brand(
            create_brand_payload(
                wholesaler_id,
                brand_name="Rio Reserve",
                beverage_class="WINE",
                registration_effective_from="2026-01-01T00:00:00Z",
                registration_expires_on="2027-12-31T23:59:59Z",
            ),
            agent_headers,
        ),
        201,
    )
    assert other_class["beverage_class"] == "WINE", (
        f"the second registration is a WINE registration, got {other_class['beverage_class']}"
    )

    # Same interval and class, different brand name: no conflict.
    other_name = validate_success(
        api.create_brand(
            create_brand_payload(
                wholesaler_id,
                brand_name="Rio Reserve Cask",
                beverage_class="SPIRITS",
                registration_effective_from="2026-01-01T00:00:00Z",
                registration_expires_on="2027-12-31T23:59:59Z",
            ),
            agent_headers,
        ),
        201,
    )
    assert other_name["brand_name"] == "Rio Reserve Cask", (
        f"the third registration carries a distinct name, got {other_name['brand_name']}"
    )

    # Same name and class, touching the incumbent interval at its closing endpoint.
    validate_error(
        api.create_brand(
            create_brand_payload(
                wholesaler_id,
                brand_name="Rio Reserve",
                beverage_class="SPIRITS",
                registration_effective_from="2027-12-31T23:59:59Z",
                registration_expires_on="2028-06-30T23:59:59Z",
            ),
            agent_headers,
        ),
        "ERR_BRAND_REGISTRATION_OVERLAP",
        409,
    )

    _, meta = validate_paginated(
        api.list_brands(regulator_headers(), params={"wholesaler_id": wholesaler_id})
    )
    assert meta["total_count"] == 3, (
        f"only the three non-conflicting registrations may exist, found {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Uniqueness (priority 14)
# --------------------------------------------------------------------------

def test_06_duplicate_item_and_duplicate_posting_month_are_refused(api):
    """PRD §3.3: "Within one schedule the triple of brand, `size_ml` and
    `bottles_per_case` must be unique; a repeat is refused with
    `ERR_DUPLICATE_SCHEDULE_ITEM`."
    PRD §3.3: "A wholesaler may not hold two live schedules for the same posting month:
    if it already has a schedule for that `posting_month` in any status other than
    `WITHDRAWN`, the create is refused with `ERR_DUPLICATE_POSTING_MONTH`."

    Design: Corner/validations/duplicate_schedule_item_and_duplicate_posting_month_are_both_refused_while_a_new_package_is_admitted
    """
    scene = setup_draft_schedule(setup_licensee_base())
    schedule_id = scene["schedule"]["id"]
    brand_id = scene["brand"]["id"]
    agent_headers = scene["agent_headers"]

    # Same brand, same size_ml, same bottles_per_case — a different price does not help.
    validate_error(
        api.create_price_schedule_item(
            create_price_schedule_item_payload(
                schedule_id, brand_id,
                size_ml=750, bottles_per_case=12,
                case_price_cents=118_000, unit_price_cents=10_500,
            ),
            agent_headers,
        ),
        "ERR_DUPLICATE_SCHEDULE_ITEM",
        409,
    )

    validate_error(
        api.create_price_schedule(
            create_price_schedule_payload(
                scene["wholesaler"]["id"], scene["program"]["id"], posting_month="2026-09"
            ),
            agent_headers,
        ),
        "ERR_DUPLICATE_POSTING_MONTH",
        409,
    )

    # A genuinely different package on the same brand is admitted.
    admitted = validate_success(
        api.create_price_schedule_item(
            create_price_schedule_item_payload(
                schedule_id, brand_id,
                size_ml=375, bottles_per_case=6,
                case_price_cents=30_000, unit_price_cents=5_500,
            ),
            agent_headers,
        ),
        201,
    )
    assert admitted["size_ml"] == 375, (
        f"the admitted package is the 375 ml six-pack, got {admitted['size_ml']}"
    )

    schedule_after = read_schedule(schedule_id)
    assert schedule_after["item_count"] == 2, (
        f"only one of the three item attempts landed on top of the original, got "
        f"item_count {schedule_after['item_count']}"
    )
    assert schedule_after["status"] == "DRAFT", (
        f"the schedule is still DRAFT, got {schedule_after['status']}"
    )

    _, meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(), params={"wholesaler_id": scene["wholesaler"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused create must not add a second schedule, found {meta['total_count']}"
    )


def test_07_a_second_audit_for_the_same_month_is_refused_and_the_next_month_is_not(api):
    """PRD §3.9: "A wholesaler may not be under two live audits for the same month: an
    existing audit for that `audit_period_month` in any status other than `VOID` refuses
    the create with `ERR_DUPLICATE_AUDIT_PERIOD`."
    PRD §3.9: "The new audit begins in `OPEN` with `finding_count`,
    `total_variance_cents`, `base_penalty_cents`, `penalty_assessed_cents` and
    `prior_violation_count` all 0, `tier_multiplier` at `1.0`, and `void_reason` unset."
    PRD §3.9: "Opening an audit increments the audited wholesaler's `open_audit_count`
    by 1 and advances that wholesaler's `version` by 1."

    Design: Corner/validations/a_second_audit_for_the_same_period_month_is_refused_while_the_next_month_is_admitted
    """
    scene = setup_licensee_base()
    wholesaler_id = scene["wholesaler"]["id"]
    program_id = scene["program"]["id"]

    version_before = read_wholesaler(wholesaler_id)["version"]
    first = validate_success(
        api.create_compliance_audit(
            create_compliance_audit_payload(
                wholesaler_id, program_id, "2026-10", version_before
            ),
            regulator_headers(),
        ),
        201,
    )
    assert first["status"] == "OPEN", f"a new audit begins OPEN, got {first['status']}"

    version_after_first = read_wholesaler(wholesaler_id)["version"]
    assert version_after_first == version_before + 1, (
        f"opening an audit advances the wholesaler's version by 1, got "
        f"{version_after_first} from {version_before}"
    )

    validate_error(
        api.create_compliance_audit(
            create_compliance_audit_payload(
                wholesaler_id, program_id, "2026-10", version_after_first
            ),
            regulator_headers(),
        ),
        "ERR_DUPLICATE_AUDIT_PERIOD",
        409,
    )

    second = validate_success(
        api.create_compliance_audit(
            create_compliance_audit_payload(
                wholesaler_id, program_id, "2026-11", version_after_first
            ),
            regulator_headers(),
        ),
        201,
    )
    assert second["audit_period_month"] == "2026-11", (
        f"the following month is a different period, got {second['audit_period_month']}"
    )
    assert second["status"] == "OPEN", f"a new audit begins OPEN, got {second['status']}"
    assert second["finding_count"] == 0, (
        f"a new audit begins with finding_count 0, got {second['finding_count']}"
    )
    assert second["tier_multiplier"] == 1.0, (
        f"a new audit begins with tier_multiplier 1.0, got {second['tier_multiplier']}"
    )

    wholesaler_after = read_wholesaler(wholesaler_id)
    assert wholesaler_after["open_audit_count"] == 2, (
        f"exactly two audits were opened, got {wholesaler_after['open_audit_count']}"
    )

    _, meta = validate_paginated(
        api.list_compliance_audits(regulator_headers(), params={"wholesaler_id": wholesaler_id})
    )
    assert meta["total_count"] == 2, (
        f"the refused create must not persist an audit, found {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Segregation of duties (priority 16)
# --------------------------------------------------------------------------

def test_08_certifying_the_schedule_you_filed_yourself_is_refused(api):
    """PRD §3.4: "the acting licensee user must not be the user recorded in the
    schedule's `filed_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`"
    PRD §3.4: "Note that a person holding `DUAL_ROLE` can legitimately file and certify —
    but not the same schedule, because the segregation test compares licensee user
    identities, not capacities."
    PRD §3.4: "Certification stamps `certified_at` with the current server time, records
    the acting user in `certified_by_user_id`, and computes `hold_window_ends_at` as
    `certified_at` advanced by the program's `hold_window_days` multiplied by 86,400
    seconds."

    Design: Corner/validations/certifying_the_schedule_you_filed_yourself_returns_segregation_of_duties
    """
    set_clock("2026-08-01T00:00:00Z")
    program = new_state_program()
    wholesaler = new_wholesaler(program["id"])
    dual = new_dual_role_user(wholesaler["id"], full_name="Dana Dual")
    dual_as_agent = make_filing_agent_headers(dual["id"])
    dual_as_certifier = make_certifying_officer_headers(dual["id"])
    other_certifier, other_certifier_headers = new_certifying_officer(
        wholesaler["id"], "Cora Certifier"
    )

    brand = new_brand(wholesaler["id"], dual_as_agent, approve=True)
    schedule = new_schedule(wholesaler["id"], program["id"], dual_as_agent)
    new_item(schedule["id"], brand["id"], dual_as_agent)
    filed = submit_schedule(schedule["id"], dual_as_agent)
    assert filed["filed_by_user_id"] == dual["id"], (
        f"the dual-role user is on record as the filer, got {filed['filed_by_user_id']}"
    )

    # The same human, now acting as CertifyingOfficer, is still the filer.
    validate_error(
        api.certify_price_schedule(schedule["id"], dual_as_certifier),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )
    blocked = read_schedule(schedule["id"])
    assert blocked["status"] == "SUBMITTED", (
        f"the refused certification leaves the schedule SUBMITTED, got {blocked['status']}"
    )
    assert blocked["certified_at"] is None, (
        f"certified_at must stay unset, got {blocked['certified_at']}"
    )
    assert blocked["certified_by_user_id"] is None, (
        f"certified_by_user_id must stay unset, got {blocked['certified_by_user_id']}"
    )

    # A different licensee user certifies the identical schedule.
    certified = validate_success(
        api.certify_price_schedule(schedule["id"], other_certifier_headers)
    )
    assert certified["status"] == "POSTED", (
        f"certification posts the schedule, got {certified['status']}"
    )
    assert certified["certified_by_user_id"] == other_certifier["id"], (
        f"certified_by_user_id records the second user {other_certifier['id']}, got "
        f"{certified['certified_by_user_id']}"
    )
    assert certified["certified_at"] == "2026-08-01T00:00:00.000Z", (
        f"certified_at is stamped from the logical clock, got {certified['certified_at']}"
    )
    assert certified["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        f"three hold-window days is 259,200 seconds after certification, got "
        f"{certified['hold_window_ends_at']}"
    )
    assert certified["filed_by_user_id"] == dual["id"], (
        f"the filer of record is unchanged, got {certified['filed_by_user_id']}"
    )


# --------------------------------------------------------------------------
# Cardinality (priority 19)
# --------------------------------------------------------------------------

def test_09_submitting_a_schedule_with_no_items_is_refused(api):
    """PRD §3.3: "the schedule must carry at least one item or the filing is refused with
    `ERR_SCHEDULE_HAS_NO_ITEMS`"
    PRD §2.10: "A schedule being submitted has at least one item
    (`ERR_SCHEDULE_HAS_NO_ITEMS` on `POST /price-schedules/{id}/submit`)"

    Design: Corner/validations/submitting_a_schedule_with_no_items_returns_schedule_has_no_items
    """
    scene = setup_licensee_base()
    schedule = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"]
    )

    validate_error(
        api.submit_price_schedule(schedule["id"], scene["agent_headers"]),
        "ERR_SCHEDULE_HAS_NO_ITEMS",
        422,
    )

    schedule_after = read_schedule(schedule["id"])
    assert schedule_after["status"] == "DRAFT", (
        f"the refused schedule stays DRAFT, got {schedule_after['status']}"
    )
    assert schedule_after["item_count"] == 0, (
        f"the schedule is still empty, got {schedule_after['item_count']}"
    )
    assert schedule_after["filed_at"] is None, (
        f"filed_at must stay unset, got {schedule_after['filed_at']}"
    )
    assert schedule_after["is_late"] is False, (
        f"a refused filing never decides lateness, got {schedule_after['is_late']}"
    )

    wholesaler_after = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_after["late_filing_count"] == 0, (
        f"a refused filing moves no counter, got {wholesaler_after['late_filing_count']}"
    )
    assert wholesaler_after["penalty_exposure_cents"] == 0, (
        f"a refused filing accrues nothing, got {wholesaler_after['penalty_exposure_cents']}"
    )


# --------------------------------------------------------------------------
# The certification window boundary
# --------------------------------------------------------------------------

def test_10_certifying_so_late_that_the_hold_window_reaches_the_effective_date(api):
    """PRD §3.4: "That end instant must fall strictly before `effective_date`; a
    `hold_window_ends_at` exactly equal to `effective_date` fails the test and produces
    `ERR_HOLD_WINDOW_OVERRUNS_EFFECTIVE`."
    PRD §2.7: "A three-day hold window is 259,200 seconds after `certified_at`;
    a fifteen-day correction window is 1,296,000 seconds after `certified_at`;
    a seven-day cooldown buffer is 604,800 seconds."

    Design: Corner/validations/certifying_so_late_that_the_hold_window_reaches_the_effective_date_is_refused_at_the_boundary
    """
    # One millisecond before the last certifiable instant for a 2026-09 posting month.
    scene = _two_wholesalers_submitted("2026-09-27T23:59:59.999Z")

    certified = validate_success(
        api.certify_price_schedule(scene["schedule_a"]["id"], scene["certifier_a_headers"])
    )
    assert certified["status"] == "POSTED", (
        f"a window ending strictly before the effective date is admitted, got "
        f"{certified['status']}"
    )
    assert certified["certified_at"] == "2026-09-27T23:59:59.999Z", (
        f"certified_at is stamped from the logical clock, got {certified['certified_at']}"
    )
    assert certified["hold_window_ends_at"] == "2026-09-30T23:59:59.999Z", (
        f"259,200 seconds later is one millisecond before the 2026-10-01 effective date, "
        f"got {certified['hold_window_ends_at']}"
    )

    # One millisecond later the window would end exactly on the effective date.
    set_clock("2026-09-28T00:00:00.000Z")
    validate_error(
        api.certify_price_schedule(scene["schedule_b"]["id"], scene["certifier_b_headers"]),
        "ERR_HOLD_WINDOW_OVERRUNS_EFFECTIVE",
        409,
    )

    refused = read_schedule(scene["schedule_b"]["id"])
    assert refused["status"] == "SUBMITTED", (
        f"the refused schedule stays SUBMITTED, got {refused['status']}"
    )
    assert refused["certified_at"] is None, (
        f"certified_at must stay unset, got {refused['certified_at']}"
    )
    assert refused["hold_window_ends_at"] is None, (
        f"hold_window_ends_at must stay unset, got {refused['hold_window_ends_at']}"
    )

    item_b_after = read_item(scene["item_b"]["id"])
    assert item_b_after["status"] == "DRAFT", (
        f"an uncertified item is never posted, got {item_b_after['status']}"
    )
    assert item_b_after["certified_case_price_cents"] is None, (
        f"certified_case_price_cents must stay unset, got "
        f"{item_b_after['certified_case_price_cents']}"
    )


# --------------------------------------------------------------------------
# Audit collection prerequisites
# --------------------------------------------------------------------------

def test_11_collecting_an_audit_whose_month_holds_no_flagged_invoice_is_refused(api):
    """PRD §3.9: "It requires the audit to be in `OPEN` (otherwise `ERR_INVALID_STATE`)
    and requires at least one invoice of the audited wholesaler whose `validation_status`
    is `FLAGGED` and whose `invoice_date` falls inside the `audit_period_month` — that is,
    whose UTC year and month equal the audited month; when there is none, the collection
    is refused with `ERR_NO_FLAGGED_INVOICES`."

    Design: Corner/validations/collecting_an_audit_whose_period_month_holds_no_flagged_invoice_returns_no_flagged_invoices
    """
    scene = setup_effective_schedule()
    item = scene["items"][0]
    invoice = new_invoice(scene["wholesaler"]["id"], "2026-10-05T00:00:00Z", scene["agent_headers"])
    new_invoice_line(
        invoice["id"], item["id"], 115_000, 11_000, scene["agent_headers"], cases_quantity=2
    )
    flagged = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"])
    )
    assert flagged["validation_status"] == "FLAGGED", (
        f"undercharging the posted case price flags the invoice, got "
        f"{flagged['validation_status']}"
    )

    # The only flagged invoice is dated October; the audit period is September.
    version = read_wholesaler(scene["wholesaler"]["id"])["version"]
    audit = validate_success(
        api.create_compliance_audit(
            create_compliance_audit_payload(
                scene["wholesaler"]["id"], scene["program"]["id"], "2026-09", version
            ),
            regulator_headers(),
        ),
        201,
    )

    validate_error(
        api.collect_compliance_audit(audit["id"], regulator_headers()),
        "ERR_NO_FLAGGED_INVOICES",
        409,
    )

    audit_after = read_audit(audit["id"])
    assert audit_after["status"] == "OPEN", (
        f"the refused collection leaves the audit OPEN, got {audit_after['status']}"
    )
    assert audit_after["finding_count"] == 0, (
        f"no finding may be written, got {audit_after['finding_count']}"
    )
    assert audit_after["total_variance_cents"] == 0, (
        f"no variance may be tallied, got {audit_after['total_variance_cents']}"
    )
    assert list_findings(audit["id"]) == [], (
        "a refused collection produces no findings at all"
    )

    invoice_after = read_invoice(invoice["id"])
    assert invoice_after["audit_status"] == "NOT_AUDITED", (
        f"the out-of-period invoice is never pulled in, got {invoice_after['audit_status']}"
    )
    assert invoice_after["audit_id"] is None, (
        f"the out-of-period invoice is never linked to the audit, got "
        f"{invoice_after['audit_id']}"
    )


# --------------------------------------------------------------------------
# The clean path accrues nothing
# --------------------------------------------------------------------------

def test_12_an_on_time_filing_that_satisfies_every_rule_accrues_nothing(api):
    """PRD §3.3: "`is_late` is set to `true` when `filed_at` is strictly after the
    deadline instant and to `false` otherwise; a `filed_at` exactly equal to the deadline
    instant is on time."
    PRD §3.3: "When `is_late` comes out `false`, none of this happens: no counter moves,
    no penalty accrues, and the wholesaler's `version` and `updated_at` are left exactly
    as they were."
    PRD §2.9: "The stored field `penalty_exposure_cents` is always the plain sum of those
    four buckets, recomputed and rewritten in the same request as any accrual or reversal
    that touched any of them."

    Design: Corner/validations/an_on_time_filing_that_satisfies_every_business_rule_accrues_nothing_anywhere
    """
    scene = setup_draft_schedule(setup_licensee_base(clock="2026-09-10T00:00:00Z"))
    schedule_id = scene["schedule"]["id"]
    version_before = read_wholesaler(scene["wholesaler"]["id"])["version"]

    filed = validate_success(api.submit_price_schedule(schedule_id, scene["agent_headers"]))
    assert filed["status"] == "SUBMITTED", (
        f"the filing is admitted, got {filed['status']}"
    )
    assert filed["filed_at"] == "2026-09-10T00:00:00.000Z", (
        f"filed_at is stamped from the logical clock, got {filed['filed_at']}"
    )
    assert filed["is_late"] is False, (
        f"2026-09-10T00:00:00.000Z precedes the 2026-09-10T23:59:59.999Z deadline, got "
        f"is_late {filed['is_late']}"
    )

    certified = certify_schedule(schedule_id, scene["certifier_headers"])
    assert certified["status"] == "POSTED", (
        f"certification posts the schedule, got {certified['status']}"
    )
    assert certified["certified_at"] == "2026-09-10T00:00:00.000Z", (
        f"certified_at is stamped from the logical clock, got {certified['certified_at']}"
    )
    assert certified["hold_window_ends_at"] == "2026-09-13T00:00:00.000Z", (
        f"259,200 seconds after certification, strictly before the 2026-10-01 effective "
        f"date, got {certified['hold_window_ends_at']}"
    )
    assert certified["correction_count"] == 0, (
        f"no correction has been filed, got {certified['correction_count']}"
    )
    assert certified["return_count"] == 0, (
        f"the schedule was never returned, got {certified['return_count']}"
    )

    item_after = read_item(scene["items"][0]["id"])
    assert item_after["status"] == "POSTED", (
        f"certification posts the item, got {item_after['status']}"
    )
    assert item_after["certified_case_price_cents"] == 120_000, (
        f"the certified case price freezes the filed price, got "
        f"{item_after['certified_case_price_cents']}"
    )
    assert item_after["amendment_count"] == 0, (
        f"no amendment has been filed, got {item_after['amendment_count']}"
    )
    assert item_after["correction_count"] == 0, (
        f"no correction has been filed, got {item_after['correction_count']}"
    )

    wholesaler_after = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_after["version"] == version_before, (
        f"an on-time filing leaves the wholesaler's version exactly as it was, got "
        f"{wholesaler_after['version']} against {version_before}"
    )
    for bucket in (
        "late_filing_penalty_accrued_cents",
        "correction_penalty_accrued_cents",
        "amendment_penalty_accrued_cents",
        "assessed_penalty_cents",
        "penalty_exposure_cents",
    ):
        assert wholesaler_after[bucket] == 0, (
            f"{bucket} must stay 0 on a clean filing, got {wholesaler_after[bucket]}"
        )
    for counter in (
        "late_filing_count",
        "frivolous_amendment_count",
        "off_posted_violation_count",
        "open_audit_count",
    ):
        assert wholesaler_after[counter] == 0, (
            f"{counter} must stay 0 on a clean filing, got {wholesaler_after[counter]}"
        )
