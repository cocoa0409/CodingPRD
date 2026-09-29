"""Publication is gated on a sibling CodeUpdateCycle's status, not on the file's own."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_northgate_item_scenario,
    reprice_item, item_lifecycle, read_item, read_facility, create_payer_contract,
    build_transparency_file, file_lifecycle, read_file,
    create_cycle, create_entry, cycle_lifecycle, disposition_entry, read_cycle, read_entry,
    ANALYST, APPROVER, COMPLIANCE,
)


def _setup():
    """A VALIDATED transparency file on a FROZEN facility, plus a MAPPING code-update cycle
    whose single CROSSWALK entry is MAPPED onto the same item."""
    s = setup_northgate_item_scenario()
    item = reprice_item(s["item"]["id"])
    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    item_lifecycle(item["id"], "APPROVE", APPROVER)
    s["item"] = item_lifecycle(item["id"], "ACTIVATE", APPROVER)
    s["contract"] = create_payer_contract(
        s["facility"]["id"], payer_code="BCBS_STATE", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=4500,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        trailing_units=100, renegotiation_notice_days=30,
    )
    facility = read_facility(s["facility"]["id"])
    tfile = build_transparency_file(facility["id"], facility["version"], file_format="CSV")
    s["transparency_file"] = file_lifecycle(tfile["id"], "VALIDATE")

    cycle = create_cycle(s["facility"]["id"], cycle_year=2027, code_set="CPT")
    entry = create_entry(cycle["id"], "CROSSWALK", old_code_value="80053",
                         new_code_value="80053A")
    cycle_lifecycle(cycle["id"], "START_MAPPING")
    s["cycle"] = read_cycle(cycle["id"])
    s["entry"] = disposition_entry(entry["id"], "MAP")
    return s


def test_publication_is_refused_while_a_sibling_cycle_sits_in_mapping():
    """PRD §3.10: "Publication, `VALIDATED → PUBLISHED`, carries two preconditions. No
    `CodeUpdateCycle` of the facility may be in `MAPPING` or `CROSSWALK_APPROVED` status —
    publishing during a crosswalk blackout is refused with `ERR_TRANSPARENCY_BLACKOUT` (409)"
    PRD §3.7: "On success the cycle's `status` becomes `MAPPING`, and re-deriving the
    facility's posture yields `RESTRICTED` by rule 2 unless a transparency file is holding it
    at `FROZEN`; `Facility.version` advances by 1."
    PRD §3.7: "On success `target_charge_item_id` records the resolved item,
    `mapped_by_user_id` records `X-User-ID`, `carried_gross_charge_cents` is computed as
    described next, `status` becomes `MAPPED`, and the cycle's `unmapped_entry_count` is
    recomputed with `CodeUpdateCycle.version` advancing by 1."
    PRD §3.7: "When `new_revenue_code_id` is null, or when it names the same revenue code the
    item already has, the carry is again the target item's current `gross_charge_cents`: a pure
    code substitution carries the price forward."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__transparency_publish_gated_by_mapping_code_update_cycle
    """
    s = _setup()
    assert s["item"]["version"] == 5
    assert s["transparency_file"]["status"] == "VALIDATED"
    assert s["transparency_file"]["included_item_count"] == 1
    assert s["transparency_file"]["total_gross_charge_cents"] == 144000
    assert s["transparency_file"]["payer_column_count"] == 1
    assert s["transparency_file"]["validation_errors"] == []
    assert s["cycle"]["status"] == "MAPPING"
    assert s["entry"]["status"] == "MAPPED"
    assert s["entry"]["target_charge_item_id"] == s["item"]["id"]
    assert s["entry"]["carried_gross_charge_cents"] == 144000
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "FROZEN", (
        "the VALIDATED file holds rule 1, which outranks the cycle's RESTRICTED rule 2"
    )

    validate_error(
        api_client.transparency_file_lifecycle(
            s["transparency_file"]["id"], {"action": "PUBLISH"}, COMPLIANCE
        ),
        ApiErrorId.ERR_TRANSPARENCY_BLACKOUT.value,
        409,
    )

    unchanged = read_file(s["transparency_file"]["id"])
    assert unchanged["status"] == "VALIDATED"
    assert unchanged["published_at"] is None
    assert read_item(s["item"]["id"])["price_status"] == "PRICE_FROZEN"
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "FROZEN"


def test_cancelling_the_cycle_lets_the_identical_publish_call_succeed():
    """PRD §3.7: "Cancellation sets `status` to `CANCELLED` and transitions every entry whose
    `status` is `PENDING` or `MAPPED` to `DEFERRED` with `defer_reason` set to
    `'CYCLE_CANCELLED'`, then re-derives the facility's posture — the second derivation rule no
    longer holds for this cycle — with `Facility.version` advancing by 1."
    PRD §3.7: "When a mapped entry's target item transitions `INACTIVE → ARCHIVED`, or when the
    owning cycle is cancelled, the entry moves to `DEFERRED` with `defer_reason` set to
    `'TARGET_ARCHIVED'` or `'CYCLE_CANCELLED'` respectively, its `target_charge_item_id` cleared
    to null, its `version` advanced by 1, and the cycle's `unmapped_entry_count` recomputed"
    PRD §3.10: "On success `status` becomes `PUBLISHED` and `published_at` takes the logical
    now."
    PRD §3.10: "Every charge item of the facility whose `price_status` is `PRICE_FROZEN` thaws
    back to `PRICED_CURRENT`, each advancing its own `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_state_dependency__transparency_publish_gated_by_mapping_code_update_cycle
    """
    s = _setup()
    validate_error(
        api_client.transparency_file_lifecycle(
            s["transparency_file"]["id"], {"action": "PUBLISH"}, COMPLIANCE
        ),
        ApiErrorId.ERR_TRANSPARENCY_BLACKOUT.value,
        409,
    )

    cancelled = cycle_lifecycle(s["cycle"]["id"], "CANCEL",
                                note="2027 crosswalk deferred to the next release window")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["applied_entry_count"] == 0
    assert cancelled["unmapped_entry_count"] == 0

    entry = read_entry(s["entry"]["id"])
    assert entry["status"] == "DEFERRED"
    assert entry["defer_reason"] == "CYCLE_CANCELLED"
    assert entry["target_charge_item_id"] is None

    published = file_lifecycle(s["transparency_file"]["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED", (
        "the identical call now succeeds; only the sibling cycle's status moved"
    )
    assert published["published_at"].startswith("2026-09-01T00:00:00")
    assert published["included_item_count"] == 1
    assert published["total_gross_charge_cents"] == 144000

    item = read_item(s["item"]["id"])
    assert item["price_status"] == "PRICED_CURRENT"
    assert item["code_value"] == "80053", (
        "a cancelled cycle never rewrites its target item's code"
    )
    assert item["gross_charge_cents"] == 144000
    assert item["version"] == 7, (
        "create, reprice, submit, approve, activate, freeze, thaw: got "
        f"{item['version']}"
    )

    facility = read_facility(s["facility"]["id"])
    assert facility["published_transparency_file_id"] == s["transparency_file"]["id"]
    assert facility["transparency_status"] == "CURRENT"
    assert facility["chargemaster_posture"] == "OPEN"
    assert facility["stale_price_item_count"] == 0
