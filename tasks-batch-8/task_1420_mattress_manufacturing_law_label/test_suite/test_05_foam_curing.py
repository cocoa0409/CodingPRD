"""Foam pours, cure windows, chamber capacity, quarantine cycles (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_foam_batch,
    assert_instant_equal,
    create_foam_batch_payload,
    create_poured_batch,
    create_retailer_account,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]


def test_foam_batch_rejects_unknown_density_class(api):
    """PRD §2.8: "4. Request-body well-formedness (`ERR_VALIDATION_FAILED`,
    400): required input fields present, enum values valid, `quantity` at
    least 1, masses strictly greater than zero, `unit_price_cents` strictly
    greater than zero, `expires_on` strictly after `issued_on`."
    PRD §3.5: "A `LineSupervisor` pours a foam lot by naming its
    `foam_density_class` — `STANDARD`, `HIGH_DENSITY`, or `MEMORY` — the
    `poured_mass_kg` (strictly greater than zero), and the `chamber_id` of
    the cure chamber it will occupy."

    Design: Corner/entities/foam_batch_invalid_enum_rejected
    """
    resp = api.create_foam_batch(
        create_foam_batch_payload(foam_density_class="GEL_SUPER"), LS1
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_memory_batch_cool_tier_cure_eligible_at_84_hours(api):
    """PRD §3.5: "The operator supplies an `ambient_temp_c` reading; the
    server stamps `cure_started_at` from the logical clock, increments
    `cure_cycles` by one, and computes `cure_eligible_at` as `cure_started_at`
    plus a base cure length by density class — 24 hours for `STANDARD`, 48
    hours for `HIGH_DENSITY`, 72 hours for `MEMORY` — plus an ambient
    adjustment: when `ambient_temp_c` is below 18 °C, twelve hours are added;
    when it lies between 18 °C and 27 °C inclusive on both ends, nothing is
    added; when it exceeds 27 °C, six hours are subtracted."

    Design: Corner/calculations/cure_memory_class_cool_tier_constants
    """
    batch = create_poured_batch(chamber_id="CH-M", poured_mass_kg=100,
                                foam_density_class="MEMORY")
    started = validate_success(
        api.start_cure(batch["id"], {"ambient_temp_c": 10}, LS1)
    )
    # 72h base + 12h COOL adjustment from the 2026-08-01T00:00:00Z default clock.
    assert_instant_equal(started["cure_eligible_at"], "2026-08-04T12:00:00Z",
                         label="cure_eligible_at")
    assert started["cure_cycles"] == 1

    get_success_data(api.set_clock("2026-08-04T12:00:00Z", PM))
    cured = validate_success(api.certify_cured(batch["id"], QC1))
    assert cured["status"] == "CURED"


def test_certify_cured_one_second_before_eligible_rejected(api):
    """PRD §3.5: "The logical clock must be at or after `cure_eligible_at` —
    the boundary is inclusive, so exact equality passes; a strictly earlier
    clock is rejected with `ERR_CURE_INCOMPLETE` (409)."

    Design: Difficulty/boundary_precision_check/cure_certify_exact_boundary
    """
    batch = create_poured_batch(chamber_id="CH-BND", poured_mass_kg=500)
    started = validate_success(
        api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1)
    )
    # STANDARD at 20C (NORMAL tier): 24h from 2026-08-01T00:00:00Z.
    assert_instant_equal(started["cure_eligible_at"], "2026-08-02T00:00:00Z",
                         label="cure_eligible_at")

    get_success_data(api.set_clock("2026-08-01T23:59:59Z", PM))
    resp = api.certify_cured(batch["id"], QC1)
    validate_error(resp, ApiErrorId.ERR_CURE_INCOMPLETE)


def test_certify_cured_exactly_at_eligible_succeeds(api):
    """PRD §3.5: "The logical clock must be at or after `cure_eligible_at` —
    the boundary is inclusive, so exact equality passes; a strictly earlier
    clock is rejected with `ERR_CURE_INCOMPLETE` (409)."

    Design: Difficulty/boundary_precision_check/cure_certify_exact_boundary
    """
    batch = create_poured_batch(chamber_id="CH-BND", poured_mass_kg=500)
    started = validate_success(
        api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1)
    )
    assert_instant_equal(started["cure_eligible_at"], "2026-08-02T00:00:00Z",
                         label="cure_eligible_at")

    get_success_data(api.set_clock("2026-08-02T00:00:00Z", PM))
    cured = validate_success(api.certify_cured(batch["id"], QC1))
    assert_foam_batch(cured)
    assert cured["status"] == "CURED"
    assert cured["certified_by_user_id"] == "qc-1"


def test_recure_cycle_increments_cycles_and_extends_eligibility(api):
    """PRD §3.5: "A `LineSupervisor` may release the batch back to cure
    (`QUARANTINED` → `CURING`; `ERR_BATCH_NOT_QUARANTINED` guards both
    quarantine exits): the re-cure increments `cure_cycles` by one and extends
    `cure_eligible_at` by twelve hours while leaving `cure_started_at`
    untouched, and the returning batch does not re-run the chamber capacity
    check against its own previous window, because it left `CURING` at
    quarantine."

    Design: Difficulty/non_linear_state_machine/foam_batch_recure_cycle
    """
    batch = create_poured_batch(chamber_id="CH-CYC", poured_mass_kg=500)
    started = validate_success(
        api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1)
    )
    assert_instant_equal(started["cure_eligible_at"], "2026-08-02T00:00:00Z",
                         label="initial cure_eligible_at")

    get_success_data(api.quarantine_batch(batch["id"], QC1))
    recure = validate_success(api.release_to_cure(batch["id"], LS1))
    assert recure["status"] == "CURING"
    assert recure["cure_cycles"] == 2, (
        f"Re-entering CURING must bump cure_cycles to 2, got {recure['cure_cycles']}"
    )
    # 24h base + 12h re-cure penalty: 36h from the 2026-08-01T00:00:00Z start.
    assert_instant_equal(recure["cure_eligible_at"], "2026-08-02T12:00:00Z",
                         label="extended cure_eligible_at")
    assert_instant_equal(recure["cure_started_at"], "2026-08-01T00:00:00Z",
                         label="cure_started_at")


def test_recured_batch_certify_boundary_uses_extended_eligibility(api):
    """PRD §3.5: "the re-cure increments `cure_cycles` by one and extends
    `cure_eligible_at` by twelve hours while leaving `cure_started_at`
    untouched"
    PRD §3.5: "The logical clock must be at or after `cure_eligible_at` — the
    boundary is inclusive, so exact equality passes; a strictly earlier clock
    is rejected with `ERR_CURE_INCOMPLETE` (409)."

    Design: Difficulty/non_linear_state_machine/foam_batch_recure_cycle
    """
    batch = create_poured_batch(chamber_id="CH-CYC", poured_mass_kg=500)
    get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))
    get_success_data(api.quarantine_batch(batch["id"], QC1))
    get_success_data(api.release_to_cure(batch["id"], LS1))

    # 30h in (6h before the extended 36h eligibility): still incomplete.
    get_success_data(api.set_clock("2026-08-02T06:00:00Z", PM))
    early = api.certify_cured(batch["id"], QC1)
    validate_error(early, ApiErrorId.ERR_CURE_INCOMPLETE)

    # Exactly at the extended 36h mark: certifies.
    get_success_data(api.set_clock("2026-08-02T12:00:00Z", PM))
    cured = validate_success(api.certify_cured(batch["id"], QC1))
    assert cured["status"] == "CURED"


def test_chamber_admits_third_concurrent_batch_rejects_fourth(api):
    """PRD §3.5: "The chamber is a capacity-limited resource: at most three
    batches may cure concurrently with overlapping windows on the same
    `chamber_id`."
    PRD §3.5: "If two or more other batches are already `CURING` on the same
    chamber whose [`cure_started_at`, `cure_eligible_at`) windows overlap
    that estimated window, the start is rejected with
    `ERR_CHAMBER_CAPACITY_EXCEEDED` (409) — so a batch may become the third
    concurrent occupant of its chamber, never the fourth."

    Design: Difficulty/resource_temporal_overlap/cure_chamber_aggregate_capacity
    """
    batches = [
        create_poured_batch(chamber_id="CH-CAP", poured_mass_kg=100) for _ in range(4)
    ]
    for batch in batches[:3]:
        started = validate_success(
            api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1)
        )
        assert started["status"] == "CURING"

    fourth = api.start_cure(batches[3]["id"], {"ambient_temp_c": 20}, LS1)
    validate_error(fourth, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED)


def test_chamber_capacity_is_scoped_per_chamber(api):
    """PRD §3.5: "If two or more other batches are already `CURING` on the
    same chamber whose [`cure_started_at`, `cure_eligible_at`) windows overlap
    that estimated window, the start is rejected with
    `ERR_CHAMBER_CAPACITY_EXCEEDED` (409) — so a batch may become the third
    concurrent occupant of its chamber, never the fourth."

    Design: Difficulty/resource_temporal_overlap/cure_chamber_aggregate_capacity
    """
    full_chamber = [
        create_poured_batch(chamber_id="CH-CAP", poured_mass_kg=100) for _ in range(3)
    ]
    for batch in full_chamber:
        get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))

    other = create_poured_batch(chamber_id="CH-OTHER", poured_mass_kg=100)
    started = validate_success(
        api.start_cure(other["id"], {"ambient_temp_c": 20}, LS1)
    )
    assert started["status"] == "CURING", (
        "A batch in a different chamber must not be blocked by CH-CAP's occupancy"
    )


def test_quarantined_batch_frees_chamber_slot(api):
    """PRD §3.5: "Batches in `POURED`, `QUARANTINED`, or `CURED` never count
    as occupants."

    Design: Corner/calculations/chamber_capacity_ignores_quarantined_batches
    """
    batches = [
        create_poured_batch(chamber_id="CH-F", poured_mass_kg=100) for _ in range(4)
    ]
    for batch in batches[:3]:
        get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))

    blocked = api.start_cure(batches[3]["id"], {"ambient_temp_c": 20}, LS1)
    validate_error(blocked, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED)

    # Quarantining one occupant frees its slot for the previously rejected batch.
    get_success_data(api.quarantine_batch(batches[2]["id"], QC1))
    started = validate_success(
        api.start_cure(batches[3]["id"], {"ambient_temp_c": 20}, LS1)
    )
    assert started["status"] == "CURING"


def test_certify_cured_on_poured_batch_rejected(api):
    """PRD §3.5: "Certifying the cure is a `QcInspector` action moving
    `CURING` → `CURED` (any other status answers `ERR_BATCH_NOT_CURING`)."

    Design: Corner/state_machines/certify_cured_from_poured_rejected
    """
    batch = create_poured_batch(chamber_id="CH-1", poured_mass_kg=100)
    assert batch["status"] == "POURED"

    resp = api.certify_cured(batch["id"], QC1)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_CURING)

    reloaded = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert reloaded["status"] == "POURED"


def test_scrapped_batch_is_terminal_and_writes_off_mass(api):
    """PRD §3.5: "Alternatively, a `QcInspector` scraps the batch
    (`QUARANTINED` → `SCRAPPED`): `scrapped_mass_kg` becomes the full
    `available_mass_kg` and `available_mass_kg` drops to zero, preserving the
    mass-conservation invariant of §2.6."
    PRD §3.5: "Starting the cure moves `POURED` → `CURING` (a batch not in
    `POURED` answers `ERR_BATCH_NOT_POURED`)."

    Design: Corner/state_machines/scrapped_batch_terminal_lockdown
    """
    batch = create_poured_batch(chamber_id="CH-TL", poured_mass_kg=100)
    get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))
    get_success_data(api.quarantine_batch(batch["id"], QC1))

    scrapped = validate_success(api.scrap_batch(batch["id"], QC1))
    assert_foam_batch(scrapped)
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["scrapped_mass_kg"] == 100
    assert scrapped["available_mass_kg"] == 0

    resp = api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_POURED)


def test_retailer_cannot_pour_foam_batch(api):
    """PRD §2.1: "If the caller's role is well-formed but not in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /plant/foam-batches is authorized for LineSupervisor only.

    Design: Corner/validations/forbidden_role_on_foam_pour
    """
    retailer = create_retailer_account()
    resp = api.create_foam_batch(
        create_foam_batch_payload(),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
