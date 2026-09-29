"""Validation freezes the publishable inclusion set; publication thaws it again."""
from test_helpers import (
    setup_base, create_active_item, create_payer_contract,
    build_transparency_file, file_lifecycle, read_file,
    read_item, read_facility, set_clock,
    assert_transparency_file,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """One ACTIVE priced item plus one ACTIVE payer contract, with a BUILDING file over them."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    assert item["version"] == 5 and item["gross_charge_cents"] == 240000
    create_payer_contract(
        base["facility"]["id"], payer_code="BCBS", product_line="MEDICARE_ADVANTAGE",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
    )
    facility = read_facility(base["facility"]["id"])
    assert facility["version"] == 2, (
        "only the activation mutated the facility row after its creation"
    )
    tfile = build_transparency_file(facility["id"], facility["version"])
    base.update(item=item, transparency_file=tfile)
    return base


def test_validation_freezes_the_inclusion_set_and_seals_the_chargemaster():
    """PRD §3.10: "The `VALIDATE` action routes `BUILDING → VALIDATED` when the recomputed
    `validation_errors` array is empty, and `BUILDING → FAILED` when it is non-empty — the two
    outcomes are the same request with opposite verdicts, and the non-empty case arises when at
    least one `ACTIVE` item is `PRICE_STALE` or when `payer_column_count` is 0. On the `VALIDATED`
    branch, every charge item of the facility whose `lifecycle_status` is `ACTIVE` and whose
    `price_status` is `PRICED_CURRENT` transitions to `PRICE_FROZEN` with each item's `version`
    advancing by 1, and the facility's posture is re-derived to `FROZEN` with `Facility.version`
    advancing by 1."
    PRD §3.10: "**The build** captures `as_of_datetime` from the logical clock, and the inclusion
    set is evaluated at that instant: every `ChargeItem` of the file's facility whose
    `lifecycle_status` is `ACTIVE`, whose `price_status` is either `PRICED_CURRENT` or
    `PRICE_FROZEN`, and whose `duplicate_of_item_id` is null."
    PRD §3.10: "`payer_column_count` is the number of distinct `payer_code` and `product_line`
    pairs among the facility's `PayerContract` rows whose `status` is `ACTIVE` and whose closed term
    contains `as_of_datetime`"

    Design: Corner/state_machines/transparency_validate_freezes_active_priced_items_and_freezes_facility
    """
    base = _setup()
    building = base["transparency_file"]
    assert_transparency_file(building)
    assert building["status"] == "BUILDING"
    assert building["included_item_count"] == 1
    assert building["total_gross_charge_cents"] == 240000
    assert building["payer_column_count"] == 1
    assert building["published_at"] is None
    assert building["superseded_by_file_id"] is None

    validated = file_lifecycle(building["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert validated["validation_errors"] == []
    assert validated["as_of_datetime"].startswith("2026-09-01T00:00:00")
    assert validated["version"] == 2, "one build plus one validation"

    item = read_item(base["item"]["id"])
    assert item["price_status"] == "PRICE_FROZEN"
    assert item["lifecycle_status"] == "ACTIVE", "only the pricing dimension is frozen"
    assert item["version"] == 6

    facility = read_facility(base["facility"]["id"])
    assert facility["chargemaster_posture"] == "FROZEN", (
        "a file in BUILDING or VALIDATED outranks every other derivation rule"
    )
    assert facility["transparency_status"] == "NEEDS_REFRESH"
    assert facility["published_transparency_file_id"] is None


def test_publication_thaws_every_frozen_item_and_records_the_outcome():
    """PRD §3.10: "On success `status` becomes `PUBLISHED` and `published_at` takes the logical now.
    Any *other* transparency file of the facility still in `PUBLISHED` transitions to `SUPERSEDED`
    with its `superseded_by_file_id` set to this file's identifier. Every charge item of the facility
    whose `price_status` is `PRICE_FROZEN` thaws back to `PRICED_CURRENT`, each advancing its own
    `version` by 1. And the facility records the outcome: `published_transparency_file_id` takes this
    file's identifier, `transparency_status` becomes `CURRENT`, `chargemaster_posture` is re-derived,
    and `Facility.version` advances by 1."
    PRD §2.7: "1. `FROZEN`, when at least one `TransparencyFile` belonging to this facility has
    `status` of either `BUILDING` or `VALIDATED`."
    PRD §3.10: "Publication, `VALIDATED → PUBLISHED`, carries two preconditions. No
    `CodeUpdateCycle` of the facility may be in `MAPPING` or `CROSSWALK_APPROVED` status —
    publishing during a crosswalk blackout is refused with `ERR_TRANSPARENCY_BLACKOUT` (409) — and
    `included_item_count` must be at least 1, otherwise `ERR_NO_PUBLISHABLE_ITEMS` (422)."

    Design: Corner/state_machines/transparency_publish_thaws_frozen_items_and_sets_transparency_current
    """
    base = _setup()
    validated = file_lifecycle(base["transparency_file"]["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert read_item(base["item"]["id"])["price_status"] == "PRICE_FROZEN"

    published = file_lifecycle(base["transparency_file"]["id"], "PUBLISH",
                              note="Posted to the public site")
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-09-01T00:00:00")
    assert published["superseded_by_file_id"] is None, "no earlier file existed to supersede"
    assert published["included_item_count"] == 1
    assert published["version"] == 3, "build, validate, publish"
    assert read_file(published["id"])["status"] == "PUBLISHED"

    item = read_item(base["item"]["id"])
    assert item["price_status"] == "PRICED_CURRENT", "the thaw releases the frozen price"
    assert item["version"] == 7

    facility = read_facility(base["facility"]["id"])
    assert facility["published_transparency_file_id"] == published["id"]
    assert facility["transparency_status"] == "CURRENT"
    assert facility["chargemaster_posture"] == "OPEN", (
        "no file is left in BUILDING or VALIDATED, so rule 1 releases the facility"
    )
