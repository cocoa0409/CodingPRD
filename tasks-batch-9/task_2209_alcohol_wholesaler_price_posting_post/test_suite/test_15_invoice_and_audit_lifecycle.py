"""Retailer invoice validation and compliance audit state machines.

Every test builds its own program, wholesaler, staff, brand, effective schedule
and invoices through PRD-declared endpoints, because the server is restarted
against an empty database before each test.
"""

from typing import Any, Dict, Tuple

import pytest

from test_helpers import (
    accept_amendment,
    assess_audit,
    close_audit,
    collect_audit,
    new_audit,
    new_invoice,
    read_audit,
    read_invoice,
    read_invoice_line,
    read_wholesaler,
    regulator_headers,
    revoke_amendment,
    run_posting,
    set_clock,
    setup_effective_schedule,
    setup_invoice_with_lines,
    setup_licensee_base,
    setup_pending_amendment,
    validate_error,
    validate_paginated,
    validate_success,
    void_compliance_audit_payload,
)


def _flagged_undercharged_invoice_scene() -> Dict[str, Any]:
    """Effective schedule plus one FLAGGED invoice: two cases charged 5,000 cents light.

    The single line charges 115,000 per case against a posted 120,000, so the line
    is undercharged by 10,000 cents in total.
    """
    scene = setup_effective_schedule(
        posting_month="2026-09", clock_before_run="2026-10-01T00:00:00Z"
    )
    return setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": scene["items"][0]["id"],
                "cases_quantity": 2,
                "case_price_charged_cents": 115_000,
                "unit_price_charged_cents": 11_000,
            }
        ],
        validate=True,
    )


def _flagged_invoice_with_open_audit() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The flagged-invoice scene plus one `OPEN` compliance audit for 2026-10."""
    scene = _flagged_undercharged_invoice_scene()
    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-10")
    return scene, audit


def test_01_retailer_invoice_revalidation_cycles_from_flagged_back_to_validated(api):
    """PRD §3.8: "A previously flagged invoice that now prices clean goes
    `FLAGGED → VALIDATED`, and in that one branch the system additionally clears
    `off_posted_line_count` and `total_variance_cents` to 0 explicitly, so no
    residue of the earlier finding survives; a previously flagged invoice that
    still prices dirty goes `FLAGGED → FLAGGED`."
    PRD §3.8: "Every invocation reprices every line from scratch against the
    *currently* resolved posted prices, recomputes every invoice rollup, and
    advances the invoice's `version` by 1."
    PRD §3.8: "Finally, `is_off_posted` is `true` exactly when
    `finding_variance_cents` is not zero, and `false` when it is zero."

    Design: Corner/state_machines/retailer_invoice_revalidation_cycles_from_flagged_back_to_validated
    """
    scene = setup_pending_amendment(
        new_case_price_cents=115_000, new_unit_price_cents=10_500
    )
    accept_amendment(scene["amendment"]["id"])

    set_clock("2026-10-01T00:00:00Z")
    run_posting(scene["program"]["id"])

    scene = setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": scene["items_a"][0]["id"],
                "cases_quantity": 2,
                "case_price_charged_cents": 120_000,
                "unit_price_charged_cents": 11_000,
            }
        ],
        validate=True,
        wholesaler_key="wholesaler_a",
        agent_key="agent_a_headers",
    )
    first_pass = scene["invoice"]
    assert first_pass["validation_status"] == "FLAGGED", (
        f"charging 240000 against an amended posted total of 230000 must flag the "
        f"invoice, got {first_pass['validation_status']!r}"
    )
    assert first_pass["off_posted_line_count"] == 1, (
        f"the one line must be counted off posted, got {first_pass['off_posted_line_count']}"
    )
    assert first_pass["total_variance_cents"] == 10_000, (
        f"total_variance_cents must be |230000 - 240000| = 10000, "
        f"got {first_pass['total_variance_cents']}"
    )
    assert first_pass["subtotal_cents"] == 240_000, (
        f"subtotal_cents must be the charged net 240000, got {first_pass['subtotal_cents']}"
    )
    assert first_pass["surcharge_cents"] == 0, (
        f"a subtotal below 500000 cents attracts no surcharge, "
        f"got {first_pass['surcharge_cents']}"
    )
    assert first_pass["total_cents"] == 240_000, (
        f"total_cents must be 240000 plus 0, got {first_pass['total_cents']}"
    )

    revoke_amendment(scene["amendment"]["id"], "competitor posting was withdrawn")

    data = validate_success(
        api.validate_retailer_invoice(scene["invoice"]["id"], scene["agent_a_headers"]),
        200,
    )
    assert data["validation_status"] == "VALIDATED", (
        f"with the posted price restored to 120000 the invoice prices clean, "
        f"got {data['validation_status']!r}"
    )
    assert data["off_posted_line_count"] == 0, (
        f"the FLAGGED to VALIDATED branch clears off_posted_line_count to 0, "
        f"got {data['off_posted_line_count']}"
    )
    assert data["total_variance_cents"] == 0, (
        f"the FLAGGED to VALIDATED branch clears total_variance_cents to 0, "
        f"got {data['total_variance_cents']}"
    )
    assert data["subtotal_cents"] == 240_000, (
        f"the charged money is unchanged by revalidation, got {data['subtotal_cents']}"
    )
    assert data["surcharge_cents"] == 0, (
        f"surcharge_cents must stay 0, got {data['surcharge_cents']}"
    )
    assert data["total_cents"] == 240_000, (
        f"total_cents must stay 240000, got {data['total_cents']}"
    )

    line = read_invoice_line(scene["lines"][0]["id"])
    assert line["posted_gross_cents"] == 240_000, (
        f"posted_gross_cents must be repriced from scratch to 2 * 120000 = 240000, "
        f"got {line['posted_gross_cents']}"
    )
    assert line["variance_cents"] == 0, (
        f"variance_cents must be 240000 - 240000 = 0, got {line['variance_cents']}"
    )
    assert line["finding_variance_cents"] == 0, (
        f"finding_variance_cents must be 0, got {line['finding_variance_cents']}"
    )
    assert line["is_off_posted"] is False, (
        "is_off_posted must be false exactly when finding_variance_cents is zero"
    )

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["audit_status"] == "NOT_AUDITED", (
        f"validation never touches audit custody, got {invoice['audit_status']!r}"
    )


def test_02_retailer_invoice_validate_with_zero_lines_returns_invalid_state(api):
    """PRD §3.8: "It is invoked by a `FilingAgent` on the invoice's own
    wholesaler, and it requires that wholesaler's `license_status` to be `ACTIVE`
    (otherwise `ERR_LICENSE_NOT_ACTIVE`), that the invoice carry at least one
    line, and that the invoice's `audit_status` be `NOT_AUDITED` (either failure
    being `ERR_INVALID_STATE`)."
    PRD §2.5: "Conversely, a record whose stored fields are not changed by a
    request keeps its `updated_at` and its `version` untouched."

    Design: Corner/state_machines/retailer_invoice_validate_with_zero_lines_returns_invalid_state
    """
    scene = setup_licensee_base(with_certifier=False, with_brand=False)
    invoice = new_invoice(
        scene["wholesaler"]["id"], "2026-08-15T00:00:00Z", scene["agent_headers"]
    )
    version_at_creation = invoice["version"]

    response = api.validate_retailer_invoice(invoice["id"], scene["agent_headers"])
    assert response.status_code == 409, (
        f"validating a line-less invoice must be a 409 conflict, got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    invoice_after = read_invoice(invoice["id"])
    assert invoice_after["validation_status"] == "DRAFT", (
        f"the refused validation must leave the invoice in DRAFT, "
        f"got {invoice_after['validation_status']!r}"
    )
    assert invoice_after["line_count"] == 0, (
        f"line_count must stay 0, got {invoice_after['line_count']}"
    )
    assert invoice_after["subtotal_cents"] == 0, (
        f"subtotal_cents must stay 0, got {invoice_after['subtotal_cents']}"
    )
    assert invoice_after["total_cents"] == 0, (
        f"total_cents must stay 0, got {invoice_after['total_cents']}"
    )
    assert invoice_after["version"] == version_at_creation, (
        f"a refused request changes no stored field, so version must stay "
        f"{version_at_creation}, got {invoice_after['version']}"
    )


def test_03_compliance_audit_assess_before_collect_returns_invalid_state(api):
    """PRD §3.9: "**Assessment** is the `COLLECTED → ASSESSED` transition,
    requiring `COLLECTED` status (otherwise `ERR_INVALID_STATE`)."
    PRD §3.9: "The new audit begins in `OPEN` with `finding_count`,
    `total_variance_cents`, `base_penalty_cents`, `penalty_assessed_cents` and
    `prior_violation_count` all 0, `tier_multiplier` at `1.0`, and `void_reason`
    unset."
    PRD §3.9: "Opening an audit increments the audited wholesaler's
    `open_audit_count` by 1 and advances that wholesaler's `version` by 1."

    Design: Corner/state_machines/compliance_audit_assess_before_collect_returns_invalid_state
    """
    scene, audit = _flagged_invoice_with_open_audit()

    response = api.assess_compliance_audit(audit["id"], regulator_headers())
    assert response.status_code == 409, (
        f"assessing an OPEN audit must be a 409 conflict, got {response.status_code}"
    )
    validate_error(response, "ERR_INVALID_STATE")

    audit_after = read_audit(audit["id"])
    assert audit_after["status"] == "OPEN", (
        f"the refused assessment must leave the audit OPEN, got {audit_after['status']!r}"
    )
    for field in (
        "finding_count",
        "total_variance_cents",
        "base_penalty_cents",
        "penalty_assessed_cents",
        "prior_violation_count",
    ):
        assert audit_after[field] == 0, (
            f"an audit that never collected must keep {field} at 0, "
            f"got {audit_after[field]}"
        )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 0, (
        f"no penalty may reach the wholesaler, got {wholesaler['assessed_penalty_cents']}"
    )
    assert wholesaler["off_posted_violation_count"] == 0, (
        f"no violation may be counted, got {wholesaler['off_posted_violation_count']}"
    )
    assert wholesaler["open_audit_count"] == 1, (
        f"opening the audit incremented open_audit_count to 1 and the refused "
        f"assessment must not change it, got {wholesaler['open_audit_count']}"
    )

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["audit_status"] == "NOT_AUDITED", (
        f"an uncollected invoice stays NOT_AUDITED, got {invoice['audit_status']!r}"
    )
    assert invoice.get("audit_id") is None, (
        f"an uncollected invoice's audit_id stays unset, got {invoice.get('audit_id')!r}"
    )


def test_04_compliance_audit_collect_pulls_flagged_invoices_under_audit_and_records_one_finding_per_line(api):
    """PRD §3.9: "Every such flagged invoice is collected: its `audit_status`
    moves to `UNDER_AUDIT` and its `audit_id` is stamped with this audit's
    identifier, which also freezes it against further line additions and further
    validation."
    PRD §3.9: "Each finding's `penalty_component_cents` is that finding's
    `variance_cents` multiplied by the program's `off_posted_penalty_rate_pct` —
    with the default rate, two fifths of the variance — rounded half up to whole
    cents."
    PRD §3.9: "Collection also sets the audit's `finding_count` to the number of
    findings recorded and its `total_variance_cents` to the sum of their
    `variance_cents`, and advances the audit's `version` by 1."
    PRD §3.9: "The `finding_type` is chosen by the first matching clause of this
    sequence: `UNPOSTED_BRAND` when no posted price could be resolved for the
    line's item as of the invoice date; otherwise `OFF_POSTED_UNDERCHARGE` when
    the line's `variance_cents` is greater than 0; otherwise
    `OFF_POSTED_OVERCHARGE` when the line's `variance_cents` is less than 0;
    otherwise `EXCESS_PROMOTIONAL_ALLOWANCE` when the line's
    `excess_promotional_cents` is greater than 0; otherwise
    `EXCESS_DEPLETION_ALLOWANCE`."

    Design: Corner/state_machines/compliance_audit_collect_pulls_flagged_invoices_under_audit_and_records_one_finding_per_line
    """
    scene, audit = _flagged_invoice_with_open_audit()

    data = validate_success(
        api.collect_compliance_audit(audit["id"], regulator_headers()), 200
    )
    assert data["status"] == "COLLECTED", (
        f"collect must move the audit to COLLECTED, got {data['status']!r}"
    )
    assert data["finding_count"] == 1, (
        f"the one off-posted line must produce exactly one finding, "
        f"got {data['finding_count']}"
    )
    assert data["total_variance_cents"] == 10_000, (
        f"total_variance_cents must be the single finding's 10000, "
        f"got {data['total_variance_cents']}"
    )
    assert data["base_penalty_cents"] == 4_000, (
        f"base_penalty_cents must be round_half_up(10000 * 0.40) = 4000, "
        f"got {data['base_penalty_cents']}"
    )
    assert data["penalty_assessed_cents"] == 0, (
        f"collection does not assess, so penalty_assessed_cents stays 0, "
        f"got {data['penalty_assessed_cents']}"
    )
    assert data["prior_violation_count"] == 0, (
        f"prior_violation_count is captured at assessment, not collection, "
        f"got {data['prior_violation_count']}"
    )

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["audit_status"] == "UNDER_AUDIT", (
        f"the collected invoice must move to UNDER_AUDIT, got {invoice['audit_status']!r}"
    )
    assert invoice["audit_id"] == audit["id"], (
        f"the collected invoice's audit_id must be stamped with {audit['id']}, "
        f"got {invoice.get('audit_id')!r}"
    )
    assert invoice["validation_status"] == "FLAGGED", (
        f"collection does not change validation_status, got {invoice['validation_status']!r}"
    )
    assert invoice["subtotal_cents"] == 230_000, (
        f"the charged net 2 * 115000 = 230000 is untouched, got {invoice['subtotal_cents']}"
    )
    assert invoice["total_cents"] == 230_000, (
        f"total_cents must stay 230000, got {invoice['total_cents']}"
    )
    assert invoice["total_variance_cents"] == 10_000, (
        f"the invoice's own total_variance_cents stays 10000, "
        f"got {invoice['total_variance_cents']}"
    )

    findings, meta = validate_paginated(
        api.list_audit_findings(regulator_headers(), params={"audit_id": audit["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one finding must be recorded, got {meta['total_count']}"
    )
    finding = findings[0]
    assert finding["invoice_line_id"] == scene["lines"][0]["id"], (
        f"the finding must point at the line that produced it, "
        f"got {finding['invoice_line_id']!r}"
    )
    assert finding["finding_type"] == "OFF_POSTED_UNDERCHARGE", (
        f"a line with variance_cents greater than 0 is an OFF_POSTED_UNDERCHARGE, "
        f"got {finding['finding_type']!r}"
    )
    assert finding["variance_cents"] == 10_000, (
        f"the finding's variance_cents must equal the line's finding_variance_cents "
        f"10000, got {finding['variance_cents']}"
    )
    assert finding["penalty_component_cents"] == 4_000, (
        f"penalty_component_cents must be round_half_up(10000 * 0.40) = 4000, "
        f"got {finding['penalty_component_cents']}"
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 0, (
        f"collection reaches no further than the audit and its invoices, "
        f"got {wholesaler['assessed_penalty_cents']}"
    )
    assert wholesaler["off_posted_violation_count"] == 0, (
        f"violations are counted at assessment, got {wholesaler['off_posted_violation_count']}"
    )


def test_05_compliance_audit_void_compensates_the_whole_assessment_across_wholesaler_and_invoices(api):
    """PRD §3.9: "**Voiding** is the `ASSESSED → VOID` transition, likewise
    requiring `ASSESSED` status (otherwise `ERR_INVALID_STATE`), and it unwinds
    the assessment exactly: it records the supplied `void_reason`, subtracts the
    audit's `penalty_assessed_cents` from the wholesaler's
    `assessed_penalty_cents`, subtracts the audit's `finding_count` from the
    wholesaler's `off_posted_violation_count`, recomputes `penalty_exposure_cents`,
    advances the wholesaler's `version` by 1, returns every invoice the audit
    collected to `audit_status` `NOT_AUDITED` and clears each such invoice's
    `audit_id` back to unset, and advances the audit's `version` by 1."
    PRD §3.9: "Note that voiding does not delete the audit's findings — they
    remain readable, and their `variance_cents` and `penalty_component_cents`
    stand as a record of what the regulator had computed."
    PRD §3.9: "The `penalty_assessed_cents` is then `base_penalty_cents`
    multiplied by `tier_multiplier`, rounded half up to whole cents — a second
    rounding, applied after the per-finding rounding that produced
    `base_penalty_cents`."

    Design: Corner/state_machines/compliance_audit_void_compensates_the_whole_assessment_across_wholesaler_and_invoices
    """
    scene, audit = _flagged_invoice_with_open_audit()
    collect_audit(audit["id"])
    assessed = assess_audit(audit["id"])

    assert assessed["status"] == "ASSESSED", (
        f"the audit must reach ASSESSED before voiding, got {assessed['status']!r}"
    )
    assert assessed["prior_violation_count"] == 0, (
        f"a first-time offender's prior_violation_count is 0, "
        f"got {assessed['prior_violation_count']}"
    )
    assert assessed["tier_multiplier"] == pytest.approx(1.0, abs=1e-9), (
        f"a prior_violation_count of 2 or fewer yields a tier_multiplier of 1.00, "
        f"got {assessed['tier_multiplier']!r}"
    )
    assert assessed["penalty_assessed_cents"] == 4_000, (
        f"penalty_assessed_cents must be round_half_up(4000 * 1.00) = 4000, "
        f"got {assessed['penalty_assessed_cents']}"
    )

    wholesaler_after_assess = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_after_assess["assessed_penalty_cents"] == 4_000, (
        f"assessment must add 4000 to the wholesaler's assessed_penalty_cents, "
        f"got {wholesaler_after_assess['assessed_penalty_cents']}"
    )
    assert wholesaler_after_assess["off_posted_violation_count"] == 1, (
        f"assessment must add the audit's finding_count of 1, "
        f"got {wholesaler_after_assess['off_posted_violation_count']}"
    )
    assert wholesaler_after_assess["penalty_exposure_cents"] == 4_000, (
        f"penalty_exposure_cents must pick up the assessed 4000, "
        f"got {wholesaler_after_assess['penalty_exposure_cents']}"
    )

    data = validate_success(
        api.void_compliance_audit(
            audit["id"],
            void_compliance_audit_payload("invoice was reissued by the retailer"),
            regulator_headers(),
        ),
        200,
    )
    assert data["status"] == "VOID", (
        f"void must move the audit to VOID, got {data['status']!r}"
    )
    assert data["void_reason"] == "invoice was reissued by the retailer", (
        f"void must record the supplied reason, got {data['void_reason']!r}"
    )
    assert data["penalty_assessed_cents"] == 4_000, (
        f"voiding reverses the wholesaler's totals but leaves the audit's own "
        f"penalty_assessed_cents at 4000, got {data['penalty_assessed_cents']}"
    )
    assert data["finding_count"] == 1, (
        f"the audit keeps its finding_count of 1, got {data['finding_count']}"
    )
    assert data["base_penalty_cents"] == 4_000, (
        f"the audit keeps its base_penalty_cents of 4000, got {data['base_penalty_cents']}"
    )

    wholesaler_after_void = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler_after_void["assessed_penalty_cents"] == 0, (
        f"voiding must subtract the assessed 4000 back off, "
        f"got {wholesaler_after_void['assessed_penalty_cents']}"
    )
    assert wholesaler_after_void["off_posted_violation_count"] == 0, (
        f"voiding must subtract the audit's finding_count back off, "
        f"got {wholesaler_after_void['off_posted_violation_count']}"
    )
    assert wholesaler_after_void["penalty_exposure_cents"] == 0, (
        f"penalty_exposure_cents must be recomputed to 0, "
        f"got {wholesaler_after_void['penalty_exposure_cents']}"
    )

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["audit_status"] == "NOT_AUDITED", (
        f"voiding must return the collected invoice to NOT_AUDITED, "
        f"got {invoice['audit_status']!r}"
    )
    assert invoice.get("audit_id") is None, (
        f"voiding must clear the invoice's audit_id back to unset, "
        f"got {invoice.get('audit_id')!r}"
    )

    findings, meta = validate_paginated(
        api.list_audit_findings(regulator_headers(), params={"audit_id": audit["id"]})
    )
    assert meta["total_count"] == 1, (
        f"voiding does not delete the audit's findings, got {meta['total_count']}"
    )
    assert findings[0]["variance_cents"] == 10_000, (
        f"the surviving finding's variance_cents must still read 10000, "
        f"got {findings[0]['variance_cents']}"
    )
    assert findings[0]["penalty_component_cents"] == 4_000, (
        f"the surviving finding's penalty_component_cents must still read 4000, "
        f"got {findings[0]['penalty_component_cents']}"
    )


def test_06_closed_compliance_audit_is_terminal_and_void_is_refused(api):
    """PRD §3.9: "**Closing** is the `ASSESSED → CLOSED` transition, requiring
    `ASSESSED` status (otherwise `ERR_INVALID_STATE`); it changes nothing but the
    status and advances the audit's `version` by 1."
    PRD §3.9: "Collected invoices remain `ASSESSED`, the wholesaler's totals
    stand, and `CLOSED` is terminal."
    PRD §3.9: "**Voiding** is the `ASSESSED → VOID` transition, likewise
    requiring `ASSESSED` status (otherwise `ERR_INVALID_STATE`), and it unwinds
    the assessment exactly: it records the supplied `void_reason`, subtracts the
    audit's `penalty_assessed_cents` from the wholesaler's
    `assessed_penalty_cents`, subtracts the audit's `finding_count` from the
    wholesaler's `off_posted_violation_count`, recomputes `penalty_exposure_cents`,
    advances the wholesaler's `version` by 1, returns every invoice the audit
    collected to `audit_status` `NOT_AUDITED` and clears each such invoice's
    `audit_id` back to unset, and advances the audit's `version` by 1."

    Design: Corner/state_machines/closed_compliance_audit_is_terminal_and_void_is_refused
    """
    scene, audit = _flagged_invoice_with_open_audit()
    collect_audit(audit["id"])
    assess_audit(audit["id"])
    closed = close_audit(audit["id"])
    assert closed["status"] == "CLOSED", (
        f"the audit must reach CLOSED, got {closed['status']!r}"
    )
    version_after_close = closed["version"]

    void_response = api.void_compliance_audit(
        audit["id"],
        void_compliance_audit_payload("regulator changed their mind"),
        regulator_headers(),
    )
    assert void_response.status_code == 409, (
        f"voiding a CLOSED audit must be a 409 conflict, got {void_response.status_code}"
    )
    validate_error(void_response, "ERR_INVALID_STATE")

    assess_response = api.assess_compliance_audit(audit["id"], regulator_headers())
    assert assess_response.status_code == 409, (
        f"re-assessing a CLOSED audit must be a 409 conflict, "
        f"got {assess_response.status_code}"
    )
    validate_error(assess_response, "ERR_INVALID_STATE")

    audit_after = read_audit(audit["id"])
    assert audit_after["status"] == "CLOSED", (
        f"CLOSED is terminal, got {audit_after['status']!r}"
    )
    assert audit_after.get("void_reason") is None, (
        f"the refused void must not record a void_reason, "
        f"got {audit_after.get('void_reason')!r}"
    )
    assert audit_after["version"] == version_after_close, (
        f"two refused requests change no stored field, so version must stay "
        f"{version_after_close}, got {audit_after['version']}"
    )
    assert audit_after["penalty_assessed_cents"] == 4_000, (
        f"the closed audit keeps its penalty_assessed_cents of 4000, "
        f"got {audit_after['penalty_assessed_cents']}"
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 4_000, (
        f"the wholesaler's totals stand after closing, "
        f"got {wholesaler['assessed_penalty_cents']}"
    )
    assert wholesaler["off_posted_violation_count"] == 1, (
        f"the wholesaler's violation count stands after closing, "
        f"got {wholesaler['off_posted_violation_count']}"
    )
    assert wholesaler["penalty_exposure_cents"] == 4_000, (
        f"penalty_exposure_cents must stand at 4000, "
        f"got {wholesaler['penalty_exposure_cents']}"
    )

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["audit_status"] == "ASSESSED", (
        f"collected invoices remain ASSESSED after closing, "
        f"got {invoice['audit_status']!r}"
    )
    assert invoice["audit_id"] == audit["id"], (
        f"the closed audit keeps custody of its invoice, got {invoice.get('audit_id')!r}"
    )
