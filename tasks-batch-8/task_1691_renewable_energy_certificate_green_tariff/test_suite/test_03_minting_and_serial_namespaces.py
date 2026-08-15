"""Mint runs: the 1000-kWh REC boundary, cross-month carryover, calendar-year
carryover reset, chronological bucket ordering, mint idempotence, immediate
consistency of derived holdings, mint-time snapshot immunity, and the
OCC-guarded generator amendment."""
from test_helpers import (
    ApiErrorId,
    assert_certificate,
    create_accepted_reading,
    create_active_generator,
    create_generator,
    get_account,
    get_certificate,
    get_generator,
    get_generator_account,
    get_meter_reading,
    list_certificates,
    patch_generator,
    run_mint,
    set_clock,
    setup_minted_generator,
    validate_error,
    validate_success,
)

from test_helpers import TEST_USERS

ADMIN = TEST_USERS["registry_admin_headers"]


def test_mint_exact_1000_kwh_mints_one_rec_with_zero_carryover(api):
    """PRD §3.3: "One thousand kilowatt-hours make one REC" and "The number
    of whole RECs in a pool is the pool divided by one thousand and rounded
    down."

    Design: Difficulty/boundary_precision_check/mint_carryover_exact_1000_kwh
    """
    setup = setup_minted_generator(
        readings=[{
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
            "metered_kwh": 1000,
        }],
        legal_name="Exact Solar", facility_code="EX1",
    )
    mint = setup["mint"]
    assert mint["minted_count"] == 1, (
        f"exact 1000 kWh must mint exactly 1 REC (inclusive floor), got {mint['minted_count']}"
    )
    assert mint["carryover_kwh"] == 0
    assert mint["total_minted_mwh"] == 1

    cert = setup["certificates"][0]
    assert_certificate(cert)
    assert cert["vintage_month"] == "2026-07"
    assert cert["serial_start"] == 1 and cert["serial_end"] == 1
    assert cert["quantity_mwh"] == 1


def test_mint_carryover_accumulates_across_months_to_cross_threshold(api):
    """PRD §3.3: "The remainder — the pool minus one thousand times the
    minted quantity — becomes the carry into the next bucket, provided the
    next bucket lies in the same calendar year".

    Design: Difficulty/boundary_precision_check/mint_carryover_exact_1000_kwh
    """
    gen = create_active_generator(legal_name="Under Solar", facility_code="UN1",
                                  technology="WIND", region_code="ERCOT")
    # 999 kWh in July: below the 1000-kWh boundary, mints nothing alone.
    create_accepted_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 999
    )
    set_clock("2026-09-01T00:00:00Z")
    # +1 kWh in August: the same-year carry crosses the threshold (999+1=1000).
    create_accepted_reading(
        gen["id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", 1
    )

    mint = run_mint(gen["id"])
    assert mint["minted_count"] == 1, (
        "999 July kWh carries into August; 999 + 1 = 1000 crosses the boundary"
    )
    assert mint["carryover_kwh"] == 0

    certs = list_certificates(generator_id=gen["id"])
    assert len(certs) == 1
    cert = certs[0]
    assert cert["vintage_month"] == "2026-08", (
        "the threshold is crossed inside the August bucket, so the certificate "
        "takes the August vintage"
    )
    assert cert["serial_start"] == 1 and cert["serial_end"] == 1
    assert cert["quantity_mwh"] == 1

    readings = validate_success(
        api.list_meter_readings(
            ADMIN, params={"generator_id": gen["id"]}
        )
    )
    assert all(r["minted"] is True for r in readings), (
        "every reading in a processed bucket is marked minted"
    )


def test_carryover_reset_at_calendar_year_boundary(api):
    """PRD §3.3: "Carryover never crosses a calendar-year boundary: if the
    first bucket of the run belongs to a later calendar year than the year
    that produced the stored carryover, that carryover is discarded to zero
    before processing begins." and "The remainder ... becomes the carry into
    the next bucket, provided the next bucket lies in the same calendar year;
    otherwise it is discarded at the year boundary."

    Design: Corner/calculations/carryover_reset_at_calendar_year_boundary
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    set_clock("2026-12-15T00:00:00Z")
    create_accepted_reading(
        gen["id"], "2026-12-01T00:00:00Z", "2026-12-15T00:00:00Z", 600
    )
    set_clock("2027-01-10T00:00:00Z")
    r2 = create_accepted_reading(
        gen["id"], "2027-01-01T00:00:00Z", "2027-01-10T00:00:00Z", 400
    )

    mint = run_mint(gen["id"])
    assert mint["minted_count"] == 0, (
        "December's 600-kWh remainder is discarded at the year boundary; "
        "January's pool is 400 alone, which mints nothing"
    )
    assert mint["carryover_kwh"] == 400
    assert get_generator(gen["id"])["lifetime_minted_mwh"] == 0
    assert get_meter_reading(r2["id"])["minted"] is True, (
        "readings in a processed bucket are consumed even when nothing mints"
    )


def test_mint_buckets_chronological_not_insertion_order(api):
    """PRD §3.3: "the run collects every reading of this generator in
    `ACCEPTED` status with `minted` still false ... and orders them by
    `period_start` ascending, breaking ties by `created_at` ascending" and
    "buckets are processed in chronological order".
    PRD §2.9: "The batch's `serial_prefix` joins the generator's
    `facility_code` and the batch's `vintage_month` with a hyphen separator".

    Design: Corner/calculations/mint_buckets_chronological_not_insertion_order
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    set_clock("2026-08-12T00:00:00Z")
    # August bucket created FIRST (insertion order), July bucket second.
    create_accepted_reading(
        gen["id"], "2026-08-05T00:00:00Z", "2026-08-10T00:00:00Z", 1000
    )
    create_accepted_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 1000
    )

    mint = run_mint(gen["id"])
    assert mint["minted_count"] == 2

    c_jul = list_certificates(generator_id=gen["id"], vintage_month="2026-07")[0]
    c_aug = list_certificates(generator_id=gen["id"], vintage_month="2026-08")[0]
    assert c_jul["serial_start"] == 1 and c_jul["serial_end"] == 1, (
        "the July bucket mints first despite its reading being created later"
    )
    assert c_aug["serial_start"] == 2 and c_aug["serial_end"] == 2
    assert c_jul["serial_prefix"] == "SS1-2026-07"
    assert c_aug["serial_prefix"] == "SS1-2026-08"


def test_mint_run_idempotent_over_consumed_readings(api):
    """PRD §3.3: "the run collects every reading of this generator in
    `ACCEPTED` status with `minted` still false" and "every reading in a
    processed bucket is marked with `minted` true ... so a reading is never
    consumed twice."
    PRD §3.3: "The mint run responds with a summary object rather than a
    resource: `minted_count` batches created, `total_minted_mwh` whole RECs
    issued, the closing `carryover_kwh`, and the `certificate_ids` of the new
    batches in mint order."

    Design: Corner/endpoints/mint_run_idempotent_over_consumed_readings
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    create_accepted_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 1500
    )

    first = run_mint(gen["id"])
    assert first["minted_count"] == 1  # 1500 -> 1 REC, carry 500
    assert first["carryover_kwh"] == 500

    second = run_mint(gen["id"])
    assert second["minted_count"] == 0
    assert second["total_minted_mwh"] == 0
    assert second["carryover_kwh"] == 500, "carryover is untouched when nothing is consumed"
    assert second["certificate_ids"] == []
    assert len(list_certificates(generator_id=gen["id"])) == 1


def test_immediate_consistency_after_mint(api):
    """PRD §3.3: "Ownership is assigned to the generator's own `GENERATOR`
    account, so the batch lands in that account's `active_holdings_mwh`." and
    "every reading in a processed bucket is marked with `minted` true and
    `minted_vintage_month` set to its bucket".

    Design: Corner/consistency_model/immediate_consistency_after_mint
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_accepted_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 2500
    )

    mint = run_mint(gen["id"])
    # 2500 kWh in one July bucket: pool // 1000 = 2 whole RECs in a single
    # batch (minted_count counts batches; total_minted_mwh counts RECs).
    assert mint["minted_count"] == 1
    assert mint["total_minted_mwh"] == 2  # 2500 -> 2 RECs, carry 500
    assert mint["carryover_kwh"] == 500

    certs = list_certificates(generator_id=gen["id"])
    assert len(certs) == 1
    cert = certs[0]
    assert_certificate(cert)
    assert cert["quantity_mwh"] == 2
    assert cert["serial_start"] == 1 and cert["serial_end"] == 2

    account = get_generator_account(gen["id"])
    assert account["active_holdings_mwh"] == 2, (
        "derived holdings reconcile within the same request sequence"
    )

    reading_after = get_meter_reading(reading["id"])
    assert reading_after["minted"] is True
    assert reading_after["minted_vintage_month"] == "2026-07"


def test_certificate_region_snapshot_immune_to_generator_patch(api):
    """PRD §2.9: "later amendments to the generator's configuration —
    including a `region_code` change — never retro-alter certificates already
    minted."
    PRD §3.1: "a `region_code` amendment never retro-alters the snapshots on
    certificates already minted."

    Design: Corner/entities/certificate_region_snapshot_immune_to_generator_patch
    """
    setup = setup_minted_generator(
        readings=[{
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
            "metered_kwh": 1000,
        }],
        legal_name="Sierra Solar", facility_code="SS1", region_code="CAISO",
        technology="SOLAR",
    )
    gen = setup["generator"]
    cert = setup["certificates"][0]
    assert cert["region_code"] == "CAISO"

    patched = patch_generator(gen["id"], region_code="ERCOT")
    assert patched["region_code"] == "ERCOT"

    after = get_certificate(cert["id"])
    assert after["region_code"] == "CAISO", "mint-time region snapshot is immutable"
    assert after["technology"] == "SOLAR"
    assert after["vintage_month"] == "2026-07"


def test_occ_generator_patch_stale_version(api):
    """PRD §2.7: "Amending a generator's configuration requires
    `expected_generator_version`, matched against that generator's current
    `version`." and "a value that does not equal the parent entity's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of
    the write is applied."
    PRD §3.1: "This write is guarded by `expected_generator_version` as
    described in §2.7, increments the generator's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_generator_patch_stale_version
    """
    gen = create_generator(legal_name="Sierra Solar", facility_code="SS1",
                           region_code="CAISO")
    observed_version = gen["version"]

    first = patch_generator(
        gen["id"], expected_generator_version=observed_version,
        legal_name="Sierra Solar LLC",
    )
    assert first["legal_name"] == "Sierra Solar LLC"
    assert first["version"] == observed_version + 1

    stale = api.patch_generator(
        gen["id"],
        {"expected_generator_version": observed_version, "region_code": "ERCOT"},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_generator(gen["id"])["region_code"] == "CAISO", (
        "a stale-version write applies nothing"
    )

    retry = patch_generator(
        gen["id"], expected_generator_version=first["version"], region_code="ERCOT"
    )
    assert retry["region_code"] == "ERCOT"
