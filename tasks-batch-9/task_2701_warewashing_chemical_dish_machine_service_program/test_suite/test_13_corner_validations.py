"""
Validation scoping: which key a uniqueness rule is keyed on, which sibling field
switches a requirement on, and which end of an interval is inclusive.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ADJUSTED_DOSE_REQUIRED,
    ERR_ASSET_TAG_TAKEN,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_DELIVERY_IN_CLOSED_PERIOD,
    ERR_DISPENSER_PLACEMENT_MISMATCH,
    ERR_DUPLICATE_DISPENSER_PRODUCT,
    ERR_DUPLICATE_OPEN_TICKET,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NON_MONOTONIC_CYCLE_COUNT,
    ERR_PERIOD_OUTSIDE_AGREEMENT_TERM,
    ERR_READING_BEFORE_INSTALL,
    ERR_RENEWAL_WINDOW_NOT_OPEN,
    ERR_SANITIZER_LOCKOUT_ACTIVE,
    ERR_TECHNICIAN_REGION_MISMATCH,
)
from test_helpers.assertions import (
    assert_axes,
    assert_cents,
    assert_instant_equals,
    assert_pct,
    assert_sweep_counters,
    assert_workload,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    AGREEMENT_ACTIVE,
    AGREEMENT_EXPIRED,
    AGREEMENT_RENEWAL_PENDING,
    AGREEMENT_TERMINATED,
    BASIS_AS_CALIBRATED,
    BILLING_CREDIT_HOLD,
    CLASS_INSUFFICIENT_DATA,
    CLASS_THEFT_SUSPECT,
    DELIVERY_VOIDED,
    DISPENSER_ACTIVE,
    DISPENSER_LOCKED_OUT,
    LOCKOUT_AGREEMENT_ENDED,
    OP_OFFLINE,
    PLACEMENT_CANCELLED,
    PLACEMENT_PENDING_INSTALL,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    REVIEW_DRAFT,
    REVIEW_PUBLISHED,
    SOURCE_DEVICE,
    SOURCE_MANUAL_AUDIT,
    SYMPTOM_LEAK,
    SYMPTOM_MACHINE_DOWN,
    SYMPTOM_RACK_QUALITY,
    TICKET_DISPATCHED,
    TICKET_QUEUED,
    VERDICT_ADJUSTED,
    VERDICT_PASS,
    VISIT_IN_PROGRESS,
)


def test_the_dispenser_slot_is_reserved_per_product_not_per_machine(api):
    """
    A second detergent feed on the same machine collides, yet a sanitizer feed on
    that very machine is fitted in the next call — so the constraint is keyed on the
    machine-and-product pair rather than on the machine. The rejected attempt leaves
    exactly one detergent feed behind.

    PRD §3.4: "At most one dispenser whose `dispenser_status` is `ACTIVE` or
    `LOCKED_OUT` may meter a given product on a given placement, so fitting a second
    feed for the same product is refused with `ERR_DUPLICATE_DISPENSER_PRODUCT`; a
    `REMOVED` dispenser frees the slot and a replacement may then be fitted."

    Design: Corner/validations/a_second_dispenser_for_the_same_product_is_rejected_while_another_product_is_accepted
    """
    base = X.program_base(api, with_sanitizer=True)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    engineer = base["technician_headers"]

    first = validate_success(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], base["detergent_id"], 8.00), engineer
        ),
        201,
    )
    assert first["dispenser_status"] == DISPENSER_ACTIVE

    validate_error(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], base["detergent_id"], 7.00), engineer
        ),
        ERR_DUPLICATE_DISPENSER_PRODUCT,
        409,
    )

    second = validate_success(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], base["sanitizer_id"], 2.00), engineer
        ),
        201,
    )
    assert second["dispenser_status"] == DISPENSER_ACTIVE

    rows, meta = validate_paginated(
        api.list_dispensers(
            engineer,
            {"placement_id": placement["id"], "product_id": base["detergent_id"]},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


def test_the_open_ticket_constraint_is_keyed_on_the_symptom(api):
    """
    A repeat report of the same symptom is refused while a different symptom on the
    same machine is accepted, and the second ticket's score proves the refused
    attempt changed nothing: 200 for the leak, 90 because the machine is now down
    outside operating hours, and 80 because the first ticket left the kitchen
    elevated.

    PRD §3.5: "A placement may not carry two tickets with the same
    `reported_symptom` while both stand in `QUEUED`, `DISPATCHED`, `ON_SITE` or
    `PENDING_VERIFICATION`; a customer's duplicate is refused with
    `ERR_DUPLICATE_OPEN_TICKET`, and the auto-ticket of cascade beta obeys the same
    rule but is skipped in silence instead of erroring."

    Design: Corner/validations/the_same_symptom_cannot_be_reported_twice_while_a_different_symptom_is_accepted
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    contact = base["customer_headers"]

    # The machine is still UP when this score is stamped, so health adds nothing.
    first = validate_success(
        api.create_service_ticket(
            F.service_ticket_payload(placement["id"], SYMPTOM_MACHINE_DOWN), contact
        ),
        201,
    )
    assert first["priority_score"] == 400

    validate_error(
        api.create_service_ticket(
            F.service_ticket_payload(placement["id"], SYMPTOM_MACHINE_DOWN), contact
        ),
        ERR_DUPLICATE_OPEN_TICKET,
        409,
    )

    second = validate_success(
        api.create_service_ticket(
            F.service_ticket_payload(placement["id"], SYMPTOM_LEAK), contact
        ),
        201,
    )
    assert second["priority_score"] == 370
    assert second["response_deadline_at"] == "2026-08-01T08:00:00Z"

    _, meta = validate_paginated(
        api.list_service_tickets(
            ACCOUNT_MANAGER_HEADERS, {"placement_id": placement["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_a_cancellation_frees_the_asset_tag_for_exactly_one_reuse(api):
    """
    A never-installed machine is cancelled outright and its tag becomes available
    again, but only once: a third machine carrying the same tag collides with the
    live one. Cancellation drives the health axis straight to offline without ever
    passing through a scheduled retrieval.

    PRD §3.3: "Four business rules guard the create, and they are reported in the
    ladder order of §2.8: the referenced agreement must be in `ACTIVE`, and a
    `DRAFT`, `RENEWAL_PENDING`, `EXPIRED`, `TERMINATED` or `VOID` agreement is
    refused with `ERR_AGREEMENT_NOT_ACTIVE`; the site's owning customer must be the
    same customer the agreement belongs to, and a cross-account pairing is refused
    with `ERR_UNKNOWN_REFERENCE`; the `asset_tag` must not already be held by any
    placement whose `placement_status` is anything other than `CANCELLED`, and a
    collision is refused with `ERR_ASSET_TAG_TAKEN`; and finally the customer's
    `billing_status` must be `CURRENT`, with a `CREDIT_HOLD` account refused with
    `ERR_CUSTOMER_CREDIT_HOLD` only once everything else about the request has
    passed."

    Design: Corner/validations/a_cancelled_placement_frees_its_asset_tag_for_reuse
    """
    base = X.program_base(api)
    first = X.create_placement(api, base, asset_tag="AT-C01")

    cancelled = validate_success(
        api.create_retrieval_order(first["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        cancelled,
        placement_status=PLACEMENT_CANCELLED,
        operational_status=OP_OFFLINE,
    )

    # Each create moves the agreement, so the token is re-read every time.
    reused = X.create_placement(api, base, asset_tag="AT-C01")
    assert reused["asset_tag"] == "AT-C01"
    assert reused["placement_status"] == PLACEMENT_PENDING_INSTALL

    validate_error(
        api.create_machine_placement(
            F.machine_placement_payload(
                base["site_id"],
                base["agreement_id"],
                base["model_id"],
                X.agreement_version(api, base["agreement_id"]),
                asset_tag="AT-C01",
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        ERR_ASSET_TAG_TAKEN,
        409,
    )

    _, meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS, {"agreement_id": base["agreement_id"]}
        )
    )
    assert meta["total_count"] == 2


def test_only_device_odometers_must_climb_and_equality_is_allowed(api):
    """
    A repeat of the same odometer value is accepted and yields a zero delta, a lower
    DEVICE value is refused, and a much lower MANUAL_AUDIT value is accepted because
    the rule never reaches it — after which the next DEVICE sample is still measured
    against the last DEVICE odometer rather than against the audit row.

    PRD §3.4: "And a `DEVICE` reading's `cycle_count_total` must be at least the
    `cycle_count_total` of the preceding `DEVICE` reading on that placement, or at
    least the placement's `initial_cycle_count` when there is no preceding one; a
    lower value is refused with `ERR_NON_MONOTONIC_CYCLE_COUNT`."

    Design: Corner/validations/cycle_counts_must_not_decrease_while_equality_and_manual_audits_are_allowed
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    X.set_clock(api, "2026-08-01T04:00:00Z")

    opening = X.ingest_reading(api, placement["id"], "2026-08-01T00:00:00Z", 100)
    assert opening["cycle_delta"] == 100

    # Equality is legal and simply produces a zero delta.
    repeat = X.ingest_reading(api, placement["id"], "2026-08-01T01:00:00Z", 100)
    assert repeat["cycle_delta"] == 0

    validate_error(
        api.create_telemetry_reading(
            placement["id"],
            F.telemetry_reading_payload("2026-08-01T02:00:00Z", 99),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_NON_MONOTONIC_CYCLE_COUNT,
        422,
    )

    # An audit row may read anything at all: the monotonicity rule is not its rule.
    audit = X.ingest_reading(
        api,
        placement["id"],
        "2026-08-01T03:00:00Z",
        50,
        source=SOURCE_MANUAL_AUDIT,
    )
    assert audit["source"] == SOURCE_MANUAL_AUDIT
    assert audit["cycle_delta"] == -50

    # The predecessor is the 100-cycle DEVICE row, not the 50-cycle audit row.
    resumed = X.ingest_reading(api, placement["id"], "2026-08-01T04:00:00Z", 120)
    assert resumed["cycle_delta"] == 20
    assert resumed["source"] == SOURCE_DEVICE

    _, meta = validate_paginated(
        api.list_telemetry_readings(
            PLATFORM_ADMIN_HEADERS,
            {"placement_id": placement["id"], "source": SOURCE_DEVICE},
        )
    )
    assert meta["total_count"] == 3


def test_a_page_outside_the_legal_range_is_refused_rather_than_trimmed(api):
    """
    Zero rows, one hundred and one rows and a negative offset are each refused
    outright instead of being nudged to 1, 100 and 0, while a limit of exactly one
    hundred — the inclusive top of the range — returns the page.

    PRD §2.9: "Values that are not integers, or that fall outside those ranges, are
    **rejected** with `ERR_INVALID_PAGINATION` rather than silently clamped to the
    nearest legal value."

    Design: Corner/validations/pagination_bounds_are_rejected_rather_than_clamped
    """
    customer = X.create_customer(api)
    X.create_site(api, customer["id"], name="Harbour Point Galley 2")
    X.create_site(api, customer["id"], name="Harbour Point Galley 3")

    for params in (
        {"customer_id": customer["id"], "limit": 0},
        {"customer_id": customer["id"], "limit": 101},
        {"customer_id": customer["id"], "offset": -1},
    ):
        validate_error(
            api.list_sites(ACCOUNT_MANAGER_HEADERS, params),
            ERR_INVALID_PAGINATION,
            400,
        )

    rows, meta = validate_paginated(
        api.list_sites(
            ACCOUNT_MANAGER_HEADERS, {"customer_id": customer["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert rows[0]["id"]


def test_the_sanitizer_window_is_mandatory_forbidden_or_nested_by_one_sibling(api):
    """
    The same two bounds are required on a sanitizer, forbidden on a detergent, and
    when present must straddle the label target — a lower bound of 250 against a
    target of 200 is rejected. Only the compliant sanitizer is stored, and it takes
    the declared tolerance default.

    PRD §3.1: "All three are **required** when `product_type` is `SANITIZER` and must
    be **omitted** for a `DETERGENT` or a `RINSE_AID`; supplying them on a
    non-sanitizer, or leaving them off a sanitizer, is an `ERR_INVALID_REQUEST`."

    Design: Corner/validations/sanitizer_window_fields_are_required_only_for_sanitizer_products
    """
    # A sanitizer without its efficacy window.
    validate_error(
        api.create_chemical_product(
            F.sanitizer_payload(
                sku="SAN-201",
                concentration_target_ppm=200,
                spec_dose_ml_per_rack=2.00,
                unit_size_ml=10000,
                unit_price_cents=4200,
                sanitizer_min_ppm=None,
                sanitizer_max_ppm=None,
                min_contact_seconds=7,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # A detergent carrying a window it may not have.
    validate_error(
        api.create_chemical_product(
            F.detergent_payload(
                sku="DET-101", sanitizer_min_ppm=150, sanitizer_max_ppm=250
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # A window that does not straddle the label target.
    validate_error(
        api.create_chemical_product(
            F.sanitizer_payload(
                sku="SAN-202",
                concentration_target_ppm=200,
                spec_dose_ml_per_rack=2.00,
                unit_size_ml=10000,
                unit_price_cents=4200,
                sanitizer_min_ppm=250,
                sanitizer_max_ppm=300,
                min_contact_seconds=7,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    compliant = validate_success(
        api.create_chemical_product(
            F.sanitizer_payload(
                sku="SAN-200",
                concentration_target_ppm=200,
                spec_dose_ml_per_rack=2.00,
                unit_size_ml=10000,
                unit_price_cents=4200,
                sanitizer_min_ppm=150,
                sanitizer_max_ppm=250,
                min_contact_seconds=7,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assert compliant["sku"] == "SAN-200"
    assert compliant["concentration_tolerance_pct"] == pytest.approx(10.00, abs=0.01)
    assert compliant["min_contact_seconds"] == 7


def test_a_credit_hold_stops_equipment_and_stock_but_not_the_contract(api):
    """
    The hold is a property of the account, yet it is enforced on two child creates
    that never name the account — the machine reaches it through its kitchen and the
    drop through its kitchen too — and it stops nothing else: the agreement on that
    same held account still activates. Both refusals carry the catalog's unusual
    payment-required status and persist nothing.

    PRD §3.7: "As with a placement, a customer on `SUSPENDED` billing cannot receive
    stock, and that credit hold is reported last of all, as
    `ERR_CUSTOMER_CREDIT_HOLD`, only once the request is otherwise entirely valid."

    Design: Corner/validations/a_credit_hold_blocks_placements_and_deliveries_and_nothing_else
    """
    base = X.program_base(
        api,
        activate=False,
        customer_overrides={"billing_status": BILLING_CREDIT_HOLD},
    )
    assert base["customer"]["billing_status"] == BILLING_CREDIT_HOLD

    activated = validate_success(
        api.activate_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert activated["status"] == AGREEMENT_ACTIVE

    opening_site_version = X.site_version(api, base["site_id"])

    validate_error(
        api.create_machine_placement(
            F.machine_placement_payload(
                base["site_id"],
                base["agreement_id"],
                base["model_id"],
                activated["version"],
                asset_tag="AT-C01",
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        ERR_CUSTOMER_CREDIT_HOLD,
        402,
    )

    validate_error(
        api.create_chemical_delivery(
            F.chemical_delivery_payload(
                base["site_id"],
                base["detergent_id"],
                opening_site_version,
                10,
                "2026-08-01T00:00:00Z",
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        ERR_CUSTOMER_CREDIT_HOLD,
        402,
    )

    _, placements = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS, {"agreement_id": base["agreement_id"]}
        )
    )
    assert placements["total_count"] == 0
    _, deliveries = validate_paginated(
        api.list_chemical_deliveries(
            ACCOUNT_MANAGER_HEADERS, {"site_id": base["site_id"]}
        )
    )
    assert deliveries["total_count"] == 0
    assert X.site_version(api, base["site_id"]) == opening_site_version


def test_whether_the_adjusted_dose_is_required_is_decided_by_the_drift_first(api):
    """
    Twelve percent of drift makes the field mandatory and its absence fatal; ten
    percent of drift — exactly the tolerance — passes and the identically shaped
    payload is accepted. A dependent check that ran before the drift was computed
    could not tell the two requests apart. Neither record reaches the live dose,
    because nothing is applied before verification.

    PRD §3.6: "When the verdict comes out `ADJUSTED`, `adjusted_dose_ml_per_rack`
    must be present and greater than zero, or the record is refused with
    `ERR_ADJUSTED_DOSE_REQUIRED`."

    Design: Corner/validations/the_adjusted_dose_requirement_depends_on_the_drift_verdict_computed_first
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    work = X.visit_in_progress(api, base, placement["id"])

    validate_error(
        api.create_calibration_record(
            work["visit_id"],
            F.calibration_record_payload(
                dispenser["id"],
                1344,
                8.00,
                X.dispenser_version(api, dispenser["id"], base["technician_id"]),
            ),
            base["technician_headers"],
        ),
        ERR_ADJUSTED_DOSE_REQUIRED,
        422,
    )

    adjusted = X.record_calibration(
        api,
        base,
        work["visit_id"],
        dispenser["id"],
        measured_ppm=1344,
        measured_dose_ml_per_rack=8.00,
        adjusted_dose_ml_per_rack=9.00,
    )
    assert adjusted["calibration_verdict"] == VERDICT_ADJUSTED
    assert_pct(adjusted["drift_pct"], 12.00)
    assert adjusted["applied"] is False

    staged = get_success_data(
        api.get_dispenser(dispenser["id"], base["technician_headers"])
    )
    assert staged["calibrated_dose_ml_per_rack"] == pytest.approx(8.00, abs=0.01)

    # Exactly at tolerance the verdict is PASS, so the field is not required at all.
    passing = X.record_calibration(
        api,
        base,
        work["visit_id"],
        dispenser["id"],
        measured_ppm=1320,
        measured_dose_ml_per_rack=8.00,
    )
    assert passing["calibration_verdict"] == VERDICT_PASS
    assert_pct(passing["drift_pct"], 10.00)


def test_a_record_must_name_a_feed_on_the_machine_the_visit_is_about(api):
    """
    The foreign feed resolves, the visit is in the right state and the payload shape
    is identical — yet the pair is refused, because the record has to belong to the
    machine the visit concerns. The very same call naming the visit's own feed is
    accepted, and the rejected attempt never counted against the visit.

    PRD §3.6: "The named dispenser must be fitted to the very placement this visit's
    ticket concerns; a dispenser on any other placement is refused with
    `ERR_DISPENSER_PLACEMENT_MISMATCH`."

    Design: Corner/validations/a_calibration_record_cannot_name_a_dispenser_from_a_different_machine
    """
    base = X.program_base(api)
    machine_a = X.installed_placement(api, base, asset_tag="AT-C01")
    machine_b = X.installed_placement(api, base, asset_tag="AT-C02")
    feed_a = X.fit_dispenser(api, base, machine_a["id"], dose=8.00)
    feed_b = X.fit_dispenser(api, base, machine_b["id"], dose=8.00)

    work = X.visit_in_progress(api, base, machine_a["id"])

    validate_error(
        api.create_calibration_record(
            work["visit_id"],
            F.calibration_record_payload(
                feed_b["id"],
                1200,
                8.00,
                X.dispenser_version(api, feed_b["id"], base["technician_id"]),
            ),
            base["technician_headers"],
        ),
        ERR_DISPENSER_PLACEMENT_MISMATCH,
        422,
    )

    accepted = X.record_calibration(
        api,
        base,
        work["visit_id"],
        feed_a["id"],
        measured_ppm=1200,
        measured_dose_ml_per_rack=8.00,
    )
    assert accepted["calibration_verdict"] == VERDICT_PASS
    assert_pct(accepted["drift_pct"], 0.00)

    visit = get_success_data(
        api.get_service_visit(work["visit_id"], base["technician_headers"])
    )
    assert visit["visit_status"] == VISIT_IN_PROGRESS
    assert visit["calibration_record_count"] == 1


def test_an_override_still_has_to_clear_the_region_filter(api):
    """
    Naming an engineer from another region skips the ranking but not eligibility, and
    the refusal mutates nothing at all: the job stays queued and unassigned and the
    out-of-region engineer never takes the load. Overriding onto the in-region
    engineer afterwards succeeds, so the failed attempt did not poison the job.

    PRD §3.5: "When the request does supply `override_technician_id`, the ranking and
    tie-break stages are skipped, but the named engineer must still satisfy the whole
    eligibility filter: a region mismatch is reported as
    `ERR_TECHNICIAN_REGION_MISMATCH`, and any other eligibility failure — unavailable
    status, missing sanitation certification, or a full workload — is reported as
    `ERR_NO_ELIGIBLE_TECHNICIAN`."

    Design: Corner/validations/an_out_of_region_technician_cannot_be_forced_onto_a_site
    """
    base = X.program_base(api)
    assert base["site"]["region_code"] == "NW"
    assert base["technician"]["region_code"] == "NW"
    out_of_region = X.create_technician(api, name="Sven Ek", region_code="SE")

    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    ticket = X.file_ticket(api, base, placement["id"], SYMPTOM_RACK_QUALITY)

    validate_error(
        api.dispatch_service_ticket(
            ticket["id"],
            PLATFORM_ADMIN_HEADERS,
            F.dispatch_payload(out_of_region["id"]),
        ),
        ERR_TECHNICIAN_REGION_MISMATCH,
        422,
    )

    untouched = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert untouched["status"] == TICKET_QUEUED
    assert untouched["assigned_technician_id"] is None
    assert untouched["escalation_level"] == 0

    assert_workload(
        get_success_data(
            api.get_technician(out_of_region["id"], PLATFORM_ADMIN_HEADERS)
        ),
        0,
    )

    dispatched = X.dispatch_ticket(
        api, ticket["id"], override_technician_id=base["technician_id"]
    )
    assert dispatched["status"] == TICKET_DISPATCHED
    assert dispatched["assigned_technician_id"] == base["technician_id"]


def test_both_ends_of_the_ingest_interval_are_inclusive(api):
    """
    One rule guards two ends of the same interval and both ends admit the boundary: a
    sample one second before installation and a sample one second after the clock are
    both refused by that single rule, while samples stamped exactly at installation
    and exactly at the clock are stored.

    PRD §3.4: "Two temporal rules guard ingest: `reading_at` must be at or after the
    placement's `installed_at` and at or before the current logical clock, so both
    back-dated and future-dated samples are refused with
    `ERR_READING_BEFORE_INSTALL`."

    Design: Corner/validations/readings_are_rejected_before_installation_and_after_the_current_clock
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    # Installation stamps the logical clock, not wall time.
    assert_instant_equals(placement["installed_at"], "2026-08-01T00:00:00Z", "installed_at")
    X.set_clock(api, "2026-08-05T00:00:00Z")

    for instant in ("2026-07-31T23:59:59Z", "2026-08-05T00:00:01Z"):
        validate_error(
            api.create_telemetry_reading(
                placement["id"],
                F.telemetry_reading_payload(instant, 10),
                PLATFORM_ADMIN_HEADERS,
            ),
            ERR_READING_BEFORE_INSTALL,
            422,
        )

    at_install = X.ingest_reading(api, placement["id"], "2026-08-01T00:00:00Z", 10)
    assert at_install["cycle_delta"] == 10
    assert at_install["source"] == SOURCE_DEVICE

    at_clock = X.ingest_reading(api, placement["id"], "2026-08-05T00:00:00Z", 310)
    assert at_clock["cycle_delta"] == 300

    _, meta = validate_paginated(
        api.list_telemetry_readings(
            PLATFORM_ADMIN_HEADERS, {"placement_id": placement["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_renewal_is_refused_one_second_short_of_the_notice_window(api):
    """
    A one-month term ending on the first of September with five days of notice opens
    its window at the twenty-seventh of August. At midnight on the twenty-sixth six
    whole days still remain, so the §2.4 sweep leaves the contract `ACTIVE` and the
    renewal is refused even though the contract is live and renewing a live contract
    is legal; that is the last instant at which the refusal is reachable, because from
    one second later the sweep itself finds five whole days remaining and moves the
    contract to renewal-pending. Once the window has opened the clock sweep — not the
    renewal call — has already moved the contract, and the same call extends the term
    by another month. Once the term has lapsed the state rule answers first and
    reports a transition error instead.

    PRD §3.2: "Renewing an agreement that is still `ACTIVE` is a self-loop — the
    status does not change, only the term extends — and it is permitted only inside
    the notice window: the clock must be at or after the term end minus
    `renewal_notice_days`, and strictly before the term end."

    Design: Corner/validations/renewal_is_refused_one_second_before_the_notice_window_opens
    """
    base = X.program_base(
        api,
        agreement_overrides={"minimum_term_months": 1, "renewal_notice_days": 5},
    )
    agreement_id = base["agreement_id"]
    assert base["agreement"]["term_end_date"] == "2026-09-01"
    assert base["agreement"]["renewal_notice_days"] == 5
    assert base["agreement"]["status"] == AGREEMENT_ACTIVE

    # PRD §2.4 part 1 measures "whole days remaining" as
    # floor((midnight(term_end_date) - clock) / 1 day). At 2026-08-26T00:00:00Z that is
    # exactly 6, which is greater than the 5 notice days, so the sweep leaves the
    # agreement ACTIVE and the §3.2 window (opening 2026-08-27T00:00:00Z) is still shut.
    early = X.set_clock(api, "2026-08-26T00:00:00Z")
    assert_sweep_counters(early, agreements_moved_to_renewal_pending=0)
    validate_error(
        api.renew_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS),
        ERR_RENEWAL_WINDOW_NOT_OPEN,
        409,
    )

    opened = X.set_clock(api, "2026-08-27T00:00:00Z")
    assert_sweep_counters(opened, agreements_moved_to_renewal_pending=1)
    pending = get_success_data(
        api.get_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
    )
    assert pending["status"] == AGREEMENT_RENEWAL_PENDING

    renewed = validate_success(
        api.renew_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
    )
    assert renewed["status"] == AGREEMENT_ACTIVE
    assert renewed["term_end_date"] == "2026-10-01"
    assert renewed["renewal_count"] == 1

    lapsed = X.set_clock(api, "2026-10-01T00:00:00Z")
    assert_sweep_counters(lapsed, agreements_expired=1)
    assert (
        get_success_data(
            api.get_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
        )["status"]
        == AGREEMENT_EXPIRED
    )
    validate_error(
        api.renew_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )


def test_a_review_window_must_sit_inside_the_covering_contract(api):
    """
    Two different rules police the same pair of instants and they answer in a fixed
    order: a window starting one day before the contract begins is a term violation,
    while a window whose end precedes its start is refused earlier still as a shape
    error, because the interval is not even well formed. A window fully inside the
    term is drafted even when it saw no racks at all.

    PRD §3.7: "The window must lie inside the covering agreement's `[start_date,
    term_end_date]` — the agreement of the site's customer standing in `ACTIVE` or
    `RENEWAL_PENDING`, or, when none is live, the most recently terminated or expired
    one — and a window straying outside it is refused with
    `ERR_PERIOD_OUTSIDE_AGREEMENT_TERM`."

    PRD §3.7: "A `QualityAuditor` opens a `UsageVarianceReview` over one `site_id` and
    one `product_id` for the half-open window `[period_start, period_end)`, where
    `period_end` must be strictly later than `period_start`."

    Design: Corner/validations/a_review_period_must_fall_inside_the_agreement_term
    """
    base = X.program_base(api)
    assert base["agreement"]["start_date"] == "2026-08-01"
    assert base["agreement"]["term_end_date"] == "2029-08-01"

    validate_error(
        api.create_usage_variance_review(
            F.usage_variance_review_payload(
                base["site_id"],
                base["detergent_id"],
                period_start="2026-07-31T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
                basis=BASIS_AS_CALIBRATED,
                opening_inventory_ml=0,
                ending_inventory_ml=0,
            ),
            AUDITOR_1_HEADERS,
        ),
        ERR_PERIOD_OUTSIDE_AGREEMENT_TERM,
        422,
    )

    validate_error(
        api.create_usage_variance_review(
            F.usage_variance_review_payload(
                base["site_id"],
                base["detergent_id"],
                period_start="2026-08-08T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                basis=BASIS_AS_CALIBRATED,
                opening_inventory_ml=0,
                ending_inventory_ml=0,
            ),
            AUDITOR_1_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-08T00:00:00Z",
        basis=BASIS_AS_CALIBRATED,
        opening_inventory_ml=0,
        ending_inventory_ml=0,
    )
    assert review["status"] == REVIEW_DRAFT
    assert review["rack_count_in_period"] == 0
    assert review["expected_consumption_ml"] == 0
    assert review["classification"] == CLASS_INSUFFICIENT_DATA
    assert review["variance_pct"] is None


def test_publication_freezes_the_drops_inside_the_window_but_not_the_one_at_its_end(api):
    """
    Voiding is legal one moment and illegal the next purely because a review was
    published over the drop's instant, and the freeze reads the window with the same
    half-open convention as every other period rule: the drop inside the window is
    refused, while the drop stamped exactly at `period_end` voids normally. The
    published figures are not recomputed by that later void.

    PRD §3.7: "A void is refused outright, with `ERR_DELIVERY_IN_CLOSED_PERIOD`, when
    any usage-variance review of the **same site and same product** standing in
    `PUBLISHED`, `ESCALATED` or `CLOSED` has a window containing the delivery's
    `delivered_at` — a published variance figure may not be rewritten underneath
    itself. Window containment is half-open, so a delivery stamped exactly at a
    published review's `period_end` is still voidable, while one stamped exactly at
    its `period_start` is not."

    Design: Corner/validations/a_published_review_freezes_the_deliveries_inside_its_half_open_window
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-02T00:00:00Z")
    drop_inside = X.record_delivery(
        api, base, unit_count=1, delivered_at="2026-08-02T00:00:00Z"
    )
    assert drop_inside["quantity_ml"] == 20000

    X.set_clock(api, "2026-08-08T00:00:00Z")
    drop_at_edge = X.record_delivery(
        api, base, unit_count=1, delivered_at="2026-08-08T00:00:00Z"
    )

    X.ingest_reading(api, placement["id"], "2026-08-02T12:00:00Z", 100)
    # Attribution is by reading_at, so this sample sits outside the window entirely.
    X.ingest_reading(api, placement["id"], "2026-08-08T00:00:00Z", 200)

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-08T00:00:00Z",
        basis=BASIS_AS_CALIBRATED,
        opening_inventory_ml=20000,
        ending_inventory_ml=0,
    )
    assert review["rack_count_in_period"] == 100
    assert review["expected_consumption_ml"] == 800
    assert review["actual_consumption_ml"] == 40000
    assert review["classification"] == CLASS_THEFT_SUSPECT

    published = X.publish_review(api, review["id"])
    assert published["status"] == REVIEW_PUBLISHED

    validate_error(
        api.void_chemical_delivery(drop_inside["id"], ACCOUNT_MANAGER_HEADERS),
        ERR_DELIVERY_IN_CLOSED_PERIOD,
        409,
    )

    voided = validate_success(
        api.void_chemical_delivery(drop_at_edge["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert voided["status"] == DELIVERY_VOIDED

    frozen = get_success_data(
        api.get_usage_variance_review(review["id"], AUDITOR_1_HEADERS)
    )
    assert frozen["actual_consumption_ml"] == 40000
    assert frozen["classification"] == CLASS_THEFT_SUSPECT


def test_the_lockout_gate_reads_the_reason_and_not_the_status(api):
    """
    A feed locked out by the termination cascade is refused a new record altogether,
    where a feed locked out by an efficacy failure would accept the record that clears
    it — so the gate is keyed on why the lock was stamped, not on the fact of being
    locked. The visit that was already under way when the contract ended survives
    intact; only the record endpoint is closed.

    PRD §3.4: "Lockouts stamped `AGREEMENT_ENDED` or `INVESTIGATION_HOLD` are never
    cleared by re-calibration; a dispenser standing in either of those two states
    accepts no new calibration record at all and rejects the attempt with
    `ERR_SANITIZER_LOCKOUT_ACTIVE`."

    Design: Corner/validations/an_agreement_ended_lockout_refuses_calibration_records_a_failure_lockout_accepts
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    assert dispenser["dispenser_status"] == DISPENSER_ACTIVE
    work = X.visit_in_progress(api, base, placement["id"])

    terminated = validate_success(
        api.terminate_service_agreement(
            base["agreement_id"],
            F.terminate_payload("2026-08-01"),
            ACCOUNT_MANAGER_HEADERS,
        )
    )
    assert terminated["status"] == AGREEMENT_TERMINATED
    assert_cents(terminated["early_termination_fee_cents"], 493333)

    locked = get_success_data(
        api.get_dispenser(dispenser["id"], base["technician_headers"])
    )
    assert locked["dispenser_status"] == DISPENSER_LOCKED_OUT
    assert locked["lockout_reason"] == LOCKOUT_AGREEMENT_ENDED

    assert_axes(
        get_success_data(
            api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
        ),
        placement_status=PLACEMENT_RETRIEVAL_SCHEDULED,
    )

    validate_error(
        api.create_calibration_record(
            work["visit_id"],
            F.calibration_record_payload(
                dispenser["id"], 1200, 8.00, locked["version"]
            ),
            base["technician_headers"],
        ),
        ERR_SANITIZER_LOCKOUT_ACTIVE,
        409,
    )

    visit = get_success_data(
        api.get_service_visit(work["visit_id"], base["technician_headers"])
    )
    assert visit["visit_status"] == VISIT_IN_PROGRESS
    assert visit["calibration_record_count"] == 0
