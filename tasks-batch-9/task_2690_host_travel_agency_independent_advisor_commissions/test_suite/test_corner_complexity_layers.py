"""Cross-cutting layers: version echoes on two parents and one reconciled derived field."""
from test_helpers import (
    api_client,
    claim_resolution_payload,
    commission_claim_payload,
    confirm_booking,
    controller,
    create_advisor_agreement_payload,
    list_client_ledger,
    make_advisor_headers,
    new_advisor,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    ops,
    read_advisor,
    read_agreement,
    read_booking,
    read_client,
    read_supplier,
    record_receipt,
    setup_active_advisor,
    trust_ledger_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
ELITE_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.75},
    {"tier_level": 2, "min_production_cents": 4_000_000, "advisor_pct": 0.85},
]
LEGACY_TIERS = [{"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.65}]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def test_a_replayed_advisor_version_cannot_sign_a_second_agreement():
    """PRD §2.7: "If it does not equal the advisor's current `version`, the create is rejected
    with `ERR_ADVISOR_VERSION_STALE` (HTTP 412) and no agreement row is written."

    Design: Corner/cross-cutting complexity layers/corner_stale_advisor_version_is_rejected_on_agreement_create
    """
    first_schedule = _standard_schedule()
    second_schedule = new_split_schedule(
        name="Elite 2026",
        tiers=ELITE_TIERS,
        platform_fee_tiers=[{"min_share_cents": 0, "fee_pct": 0.04}],
    )
    third_schedule = new_split_schedule(
        name="Legacy 2025",
        tiers=LEGACY_TIERS,
        platform_fee_tiers=[{"min_share_cents": 0, "fee_pct": 0.06}],
    )
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    baseline = advisor["version"]

    first = validate_success(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                first_schedule["id"],
                baseline,
                effective_date="2026-01-01",
                post_departure_advisor_pct=0.50,
            ),
            ops(),
        ),
        201,
    )
    assert first["status"] == "ACTIVE"
    assert read_advisor(advisor["id"])["version"] == baseline + 1

    validate_error(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                second_schedule["id"],
                baseline,
                effective_date="2026-02-01",
                post_departure_advisor_pct=0.55,
            ),
            ops(),
        ),
        "ERR_ADVISOR_VERSION_STALE",
        412,
    )

    refreshed = read_advisor(advisor["id"])
    assert refreshed["version"] == baseline + 1
    assert read_agreement(first["id"])["status"] == "ACTIVE"
    _, rejected_meta = validate_paginated(
        api_client.list_advisor_agreements(
            ops(), {"split_schedule_id": second_schedule["id"]}
        )
    )
    assert rejected_meta["total_count"] == 0

    third = validate_success(
        api_client.create_advisor_agreement(
            advisor["id"],
            create_advisor_agreement_payload(
                third_schedule["id"],
                refreshed["version"],
                effective_date="2026-03-01",
                post_departure_advisor_pct=0.45,
            ),
            ops(),
        ),
        201,
    )
    assert third["status"] == "ACTIVE"
    assert read_agreement(first["id"])["status"] == "SUPERSEDED"
    assert read_advisor(advisor["id"])["version"] == baseline + 2

    rows, meta = validate_paginated(
        api_client.list_advisor_agreements(ops(), {"advisor_id": advisor["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], third["id"]]


def test_a_disbursement_prepared_against_a_moved_balance_is_refused():
    """PRD §2.7: "A mismatch with the client's current `version` is rejected with
    `ERR_CLIENT_VERSION_STALE` (HTTP 412) and nothing is appended."

    Design: Corner/cross-cutting complexity layers/corner_stale_client_version_is_rejected_on_trust_line_append
    """
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=_standard_schedule(),
    )
    advisor = ctx["advisor"]
    client = new_client(advisor["id"], full_name="Marta Vidal", home_state_code="CA")
    baseline = client["version"]

    deposit = validate_success(
        api_client.create_trust_ledger_entry(
            client["id"],
            trust_ledger_entry_payload(
                "DEPOSIT", 300_000, baseline, memo="Initial deposit"
            ),
            make_advisor_headers(advisor["id"]),
        ),
        201,
    )
    assert deposit["balance_after_cents"] == 300_000
    assert read_client(client["id"])["version"] == baseline + 1

    validate_error(
        api_client.create_trust_ledger_entry(
            client["id"],
            trust_ledger_entry_payload(
                "DISBURSEMENT",
                300_000,
                baseline,
                memo="Prepared against the pre-deposit read",
            ),
            controller("ctrl-1"),
        ),
        "ERR_CLIENT_VERSION_STALE",
        412,
    )

    unmoved = read_client(client["id"])
    assert unmoved["trust_balance_cents"] == 300_000
    assert unmoved["version"] == baseline + 1

    disbursement = validate_success(
        api_client.create_trust_ledger_entry(
            client["id"],
            trust_ledger_entry_payload(
                "DISBURSEMENT", 120_000, unmoved["version"], memo="Supplier payment"
            ),
            controller("ctrl-1"),
        ),
        201,
    )
    assert disbursement["balance_after_cents"] == 180_000
    assert read_client(client["id"])["version"] == baseline + 2

    lines = list_client_ledger(client["id"])
    assert len(lines) == 2
    assert [line["signed_amount_cents"] for line in lines] == [300_000, -120_000]
    assert [line["balance_after_cents"] for line in lines] == [300_000, 180_000]
    for line in lines:
        assert "version" not in line


def test_the_supplier_receivable_total_reconciles_after_every_source_change():
    """PRD §3.7: "A booking joins the supplier's aging cohort when its `booking_status` is
    `CONFIRMED` or `TRAVELED`, its `commission_status` is `EXPECTED` or `CLAIMED`, and its due
    date has arrived — the due date being the UTC calendar date of its `travel_end_date`
    advanced by the supplier's `remit_terms_days`."
    PRD §3.7: "`total_outstanding_cents` is the sum of the four buckets, and an empty cohort
    leaves all five figures at 0 rather than null."

    Design: Corner/cross-cutting complexity layers/corner_supplier_outstanding_reconciles_across_the_receivable_lifecycle
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )

    def _booking(gross):
        return new_booking(
            advisor["id"],
            supplier["id"],
            client["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=gross,
            travel_start_date="2026-06-01",
            travel_end_date="2026-06-10",
        )

    kept = _booking(1_000_000)
    doomed = _booking(500_000)
    confirm_booking(kept["id"], supplier["id"])
    confirm_booking(doomed["id"], supplier["id"])

    after_confirm = read_supplier(supplier["id"])
    assert after_confirm["total_outstanding_cents"] == 150_000
    assert after_confirm["aging_0_30_cents"] == 150_000

    validate_success(
        api_client.cancel_booking(
            doomed["id"],
            {"cancellation_reason": "CLIENT_INITIATED"},
            make_advisor_headers(advisor["id"]),
        )
    )
    assert read_supplier(supplier["id"])["total_outstanding_cents"] == 100_000

    record_receipt(kept["id"], supplier["id"], 60_000, "2026-08-01")
    assert read_supplier(supplier["id"])["total_outstanding_cents"] == 0

    claim = validate_success(
        api_client.create_commission_claim(
            kept["id"],
            commission_claim_payload(40_000),
            make_advisor_headers(advisor["id"]),
        ),
        201,
    )
    after_claim = read_supplier(supplier["id"])
    assert after_claim["total_outstanding_cents"] == 40_000
    assert after_claim["aging_0_30_cents"] == 40_000

    validate_success(
        api_client.resolve_commission_claim(
            claim["id"], claim_resolution_payload("PAID", 40_000), ops()
        )
    )

    settled = read_supplier(supplier["id"])
    assert settled["total_outstanding_cents"] == 0
    assert settled["aging_0_30_cents"] == 0
    assert settled["aging_31_60_cents"] == 0
    assert settled["aging_61_90_cents"] == 0
    assert settled["aging_over_90_cents"] == 0
    assert settled["chargeback_count"] == 0

    collected = read_booking(kept["id"])
    assert collected["received_commission_cents"] == 100_000
    assert collected["shortfall_cents"] == 0
