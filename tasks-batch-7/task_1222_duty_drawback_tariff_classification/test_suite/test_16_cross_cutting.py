"""Cross-cutting layers: optimistic concurrency on claims, entries, and
classification supersede; fan-out version bumps on line creation; derived-field
reconciliation on measure revoke; the inclusive ops sweep; and immediate
consistency of computed fields in the creation response."""
from test_helpers import ApiErrorId, add_certified_classification, add_claim, add_measure, get_records_for_claim, onboard_client, set_clock, setup_paid_claim, setup_trade_scenario, TEST_USERS, validate_error, validate_success
from test_helpers.factories import create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_claim_update_stale_version_rejected(api):
    """PRD 2.6: "Updating a draft claim's period or type requires the request to
    carry `expected_claim_version` equal to the claim's current `version`.
    Posting a correction to an import entry requires
    `expected_import_entry_version` equal to the entry's current `version`.
    Superseding a classification requires `expected_classification_version`
    equal to the classification's current `version`. In each case, if the
    supplied value does not match the resource's current `version` — because
    another write has advanced the resource since the client last read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    client from silently overwriting state it has not observed."

    Design: Corner/cross_cutting_layers/claim_update_stale_version_rejected
    """
    client = onboard_client()
    claim = add_claim(client["id"])
    observed_version = claim["version"]

    updated = validate_success(
        api.update_claim(
            claim["id"],
            {"period_end": "2026-04-30T00:00:00Z",
             "expected_claim_version": observed_version},
            ANALYST,
        )
    )
    assert updated["version"] == 2

    res = api.update_claim(
        claim["id"],
        {"period_end": "2026-05-31T00:00:00Z",
         "expected_claim_version": observed_version},
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    claim_after = validate_success(api.get_claim(claim["id"], ANALYST))
    assert claim_after["period_end"] == "2026-04-30T00:00:00Z"


def test_entry_correction_stale_version_rejected(api):
    """PRD 2.6: "Posting a correction to an import entry requires
    `expected_import_entry_version` equal to the entry's current `version`."
    PRD 2.6: "In each case, if the supplied value does not match the resource's
    current `version` — because another write has advanced the resource since
    the client last read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from silently overwriting state it has not
    observed."

    Design: Corner/cross_cutting_layers/entry_correction_stale_version_rejected
    """
    ctx = setup_trade_scenario()
    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    observed_version = entry["version"]

    corrected = validate_success(
        api.correct_import_entry(
            ctx["entry"]["id"],
            {"duty_paid_cents": 80000,
             "expected_import_entry_version": observed_version},
            ANALYST,
        )
    )
    assert corrected["version"] == 2
    assert corrected["drawback_eligible_duty_cents"] == 80000

    res = api.correct_import_entry(
        ctx["entry"]["id"],
        {"duty_paid_cents": 70000,
         "expected_import_entry_version": observed_version},
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry_after["duty_paid_cents"] == 80000


def test_classification_supersede_occ_flow(api):
    """PRD 3.2: "On success, the existing classification transitions `CERTIFIED
    → SUPERSEDED` (its terminal state) with its `version` incremented, and a
    brand-new classification is created in `DRAFT` carrying the payload's fields
    and a `supersedes_id` pointing back at the superseded record;
    `supersedes_id` is null on any classification not born of a supersede."
    PRD 2.6: "Superseding a classification requires
    `expected_classification_version` equal to the classification's current
    `version`."

    Design: Corner/cross_cutting_layers/classification_supersede_occ_flow
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    cls_now = validate_success(api.get_classification(cls["id"], ANALYST))

    successor = validate_success(
        api.supersede_classification(
            cls["id"],
            {
                "product_sku": "PANT-01",
                "hts_code": "6203.42.4036",
                "country_of_origin": "CN",
                "duty_rate_bps": 1200,
                "declared_unit_value_cents": 5000,
                "expected_classification_version": cls_now["version"],
            },
            ANALYST,
        ),
        201,
    )
    assert successor["status"] == "DRAFT"
    assert successor["supersedes_id"] == cls["id"], "the self-referential link"

    old = validate_success(api.get_classification(cls["id"], ANALYST))
    assert old["status"] == "SUPERSEDED"

    data = validate_success(
        api.list_classifications(ANALYST, params={"supersedes_id": cls["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == successor["id"]


def test_cascading_side_effects_version_bumps(api):
    """PRD 3.4: "Creating a line mutates three resources beyond the line itself:
    the entry's `matched_quantity` and `unclaimed_duty_cents` absorb the
    consumption, the shipment's `matched_quantity` and `value_pool_remaining_cents`
    do likewise, and the claim's `estimate_cents` is recomputed — with `version`
    incremented on every touched resource and entry/export status bands
    re-evaluated."
    PRD 2.5: "The `version` is an integer that starts at 1 on creation and
    increments by one on every mutation of the resource — including mutations
    driven by cross-entity cascades, so a single client-visible operation may
    advance the versions of several resources at once."

    Design: Corner/cross_cutting_layers/cascading_side_effects_version_bumps
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])

    assert ctx["entry"]["version"] == 1
    assert ctx["export"]["version"] == 1
    assert claim["version"] == 1

    validate_success(
        api.add_claim_line(
            claim["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 40,
            },
            ANALYST,
        ),
        201,
    )

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    export = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    claim_after = validate_success(api.get_claim(claim["id"], ANALYST))
    assert entry["version"] == 2
    assert export["version"] == 2
    assert claim_after["version"] == 2
    assert claim_after["estimate_cents"] == 32670


def test_derived_field_reconciliation_on_revoke(api):
    """PRD 3.3: "A `FirmAdmin` may also revoke an `ACTIVE` measure outright; the
    measure becomes `REVOKED`, and matching entries are recomputed in the same
    way, with revocation only ever removing surcharges and therefore never
    shrinking eligible duty."
    PRD 3.3: "These derived figures are recomputed on entry creation, on entry
    correction, on measure creation, on measure revocation, and when the ops
    sweep expires a measure — and every recomputation increments the touched
    entry's `version`."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_revoke
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    measure = add_measure(
        hts_code_prefix="6203", measure_type="SECTION_301", surcharge_bps=500,
        effective_from="2026-01-01T00:00:00Z",
    )
    entry = validate_success(
        api.create_import_entry(
            create_import_entry_payload(client["id"], cls["id"]), ANALYST
        ),
        201,
    )
    assert entry["drawback_eligible_duty_cents"] == 57500

    revoked = validate_success(api.revoke_tariff_measure(measure["id"], ADMIN))
    assert revoked["status"] == "REVOKED"

    entry_after = validate_success(api.get_import_entry(entry["id"], ANALYST))
    assert entry_after["non_drawbackable_cents"] == 0
    assert entry_after["drawback_eligible_duty_cents"] == 82500
    assert entry_after["unclaimed_duty_cents"] == 82500


def test_measure_expiry_and_retention_sweep_inclusive(api):
    """PRD 2.8: "Running the sweep transitions every `ACTIVE` tariff measure
    whose `effective_to` is set and is less than or equal to the logical clock —
    the comparison is inclusive at the exact expiry second — into `EXPIRED`, and
    transitions every compliance record whose `retention_until` is set and is
    less than or equal to the logical clock, also inclusive, from `RETAINED` to
    `ELIGIBLE_FOR_DESTRUCTION`. The sweep response names what it touched as
    `expired_measure_ids` and `eligible_record_ids`."
    PRD 3.9: "Only then may a `ComplianceManager` certify destruction, moving
    the record to its terminal `DESTROYED` state; attempting destruction from
    any other status is rejected with `ERR_RECORD_NOT_ELIGIBLE`."

    Design: Corner/cross_cutting_layers/measure_expiry_and_retention_sweep_inclusive
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)  # paid at default clock
    measure = add_measure(
        hts_code_prefix="8479", measure_type="AD_CVD", surcharge_bps=5000,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
    )

    # One second before retention_until (2029-05-01T00:00:00Z): records not yet
    # eligible; the measure's expiry second (2026-06-01) is long past.
    set_clock("2029-04-30T23:59:59Z")
    sweep1 = validate_success(api.run_sweep(ADMIN))
    assert sweep1["eligible_record_ids"] == []
    assert measure["id"] in sweep1["expired_measure_ids"]

    # At exactly retention_until: all three records flip, inclusively.
    set_clock("2029-05-01T00:00:00Z")
    sweep2 = validate_success(api.run_sweep(ADMIN))
    assert len(sweep2["eligible_record_ids"]) == 3

    records = get_records_for_claim(ctx["claim"]["id"])
    for rec in records:
        assert rec["status"] == "ELIGIBLE_FOR_DESTRUCTION"

    destroyed = validate_success(api.destroy_record(records[0]["id"], COMPLIANCE))
    assert destroyed["status"] == "DESTROYED"


def test_immediate_consistency_in_creation_response(api):
    """PRD 3.3: "These derived figures are recomputed on entry creation, on
    entry correction, on measure creation, on measure revocation, and when the
    ops sweep expires a measure — and every recomputation increments the touched
    entry's `version`."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_consistency_in_creation_response
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    add_measure(
        hts_code_prefix="6203", measure_type="SECTION_301", surcharge_bps=500,
        effective_from="2026-01-01T00:00:00Z",
    )

    entry = validate_success(
        api.create_import_entry(
            create_import_entry_payload(client["id"], cls["id"]), ANALYST
        ),
        201,
    )
    # All computed fields are final inside the 201 response itself.
    assert entry["non_drawbackable_cents"] == 25000
    assert entry["drawback_eligible_duty_cents"] == 57500
    assert entry["unclaimed_duty_cents"] == 57500
    assert entry["status"] == "UNMATCHED"
