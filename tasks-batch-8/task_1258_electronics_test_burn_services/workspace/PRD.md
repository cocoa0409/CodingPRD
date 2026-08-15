# Electronics Test & Burn-In Services API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Electronics Test & Burn-In Services API, the operating system of a third-party test house. The house receives serialized electronic parts from customer programs, develops test programs and the fixtures that execute them, books burn-in chamber capacity in discrete slot windows, records pass/fail outcomes insertion by insertion, and dispositions finished lots. Customers range from standard commercial accounts to strategic partners whose parts carry electrostatic-discharge (ESD) certification obligations, and some customers loan their own testers and handlers to the house, which introduces a calibration discipline the system must enforce at the moment a result is recorded.

The requirements that follow cover the full operational arc: test program development, validation, release, and revision supersession; fixture commissioning and maintenance; chamber registration and reservation under overlap, capacity, and thermal-purge constraints; serialized result recording with a bounded, segregation-of-duties retest policy; dual-variant yield reporting; Material Review Board (MRB) disposition of marginal lots; customer-owned equipment calibration and maintenance windows; ESD program audits that gate scheduling; and the RMA failure-analysis loop that pulls field escapes back into lot containment.

Three design commitments run through every section. First, all time-dependent behavior — reservation windows, authorization expiry, calibration due dates, utilization accounting — is evaluated against a single logical clock, never the wall clock. Second, a unit's pass/fail standing is never stored as a bare flag: it is derived by replaying that unit's effective test results, so voids and rework decisions rewrite the present without erasing the past. Third, quality authority is segregated from production authority: the engineer who recorded a failing result may not authorize its retest, and only quality engineers may void results, close audits, decide dispositions, and close the RMA loop.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly four roles: `CustomerRep`, `TestEngineer`, `OperationsManager`, and `QualityEngineer`. A request that arrives without both headers, or whose role header does not name one of these four roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not listed among the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`.

Role identity binds to resources as follows. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. Consequently, a `CustomerRep` may create lots, register serialized units, and open RMA cases only within their own customer scope — lot creation must carry a `customer_id` equal to `X-User-ID`, unit registration must target a lot belonging to that customer, and RMA creation must reference a lot and unit belonging to that customer — and any scope mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`. When `X-User-Role` is `TestEngineer`, `OperationsManager`, or `QualityEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `recorded_by_user_id` on a test result, `authorized_by_user_id` on a retest authorization, `auditor_user_id` on an ESD audit, or `decided_by_user_id` on a disposition review — but does not compare it to any entity's `id`.

Responsibilities divide along production and quality lines. A `CustomerRep` owns lot creation and RMA intake for their own customer and may declare serial numbers on their own lots; they share read access to every resource. A `TestEngineer` develops test programs and fixtures, validates and releases programs, mints revisions, records test insertions, and issues or revokes retest authorizations. An `OperationsManager` administers customer accounts, registers chambers, owns all slot scheduling, drives the lot pipeline transitions, registers and returns customer-owned equipment, schedules and executes maintenance orders, and alone may set the logical clock. A `QualityEngineer` voids test results, opens and closes ESD audits, opens and decides lot disposition reviews, and runs the failure-analysis stages of an RMA case. Every role may use all read endpoints; unit registration is the one write shared between an `OperationsManager` (registering on receipt) and a `CustomerRep` (declaring serials for their own lots).

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — customers, test programs, fixtures, chambers, chamber reservations, lots, units, retest authorizations, customer equipment, maintenance orders, ESD audits, RMA cases, and lot disposition reviews — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed upon any modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, including state transitions and cascaded mutations performed by the system.

A **TestResult** is the deliberate exception: as an immutable event record it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a test result, even after the result is later voided.

### 2.5. The Logical Clock and Lazily Derived States

Every time-dependent rule in the system — reservation window gating, retest authorization expiry, calibration due derivation, and the elapsed-window portion of actual utilization — is evaluated against a single logical clock rather than the wall clock. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any operator intervention the clock holds this default and never drifts with real time.

An admin-only, test-driving capability — restricted to an `OperationsManager` — sets the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Advancing the clock does not, by itself, rewrite any stored state; instead, the two lazily derived states re-evaluate against the new clock on the next read or gating check. A piece of customer equipment whose stored status is `IN_SERVICE` is thereafter reported as `CALIBRATION_DUE` once the clock has reached or passed its `next_calibration_due`. A retest authorization is likewise treated as `EXPIRED` once its `expires_at` is at or before the clock. Because these derivations are lazy, reading a resource after a clock advance may show a different effective status than the same read before the advance, with no explicit transition event in between.

### 2.6. Optimistic Concurrency Control

Two write operations carry an optimistic concurrency guard, each keyed to the version of the resource being acted upon.

Minting a successor revision of a test program requires the request to carry `expected_test_program_version`, a non-optional field holding the source program's `version` as the client last observed it. If the source program's current `version` has advanced beyond that value since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from minting a revision against a lineage it has not observed.

Rescheduling a chamber reservation requires the request to carry `expected_chamber_reservation_version`, a non-optional field holding the reservation's `version` as the client last observed it. If the reservation's current `version` has advanced beyond that value, the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently undoing a reschedule it never observed.

Endpoints not named above do not accept a version field; all other mutations proceed without an optimistic concurrency check.

### 2.7. Numeric Precision, Rounding, and Threshold Comparisons

Yield and utilization ratios are carried internally as exact fractions and serialized as numbers rounded to exactly 4 decimal places using the round-half-up method. Threshold comparisons — the disposition gates in particular — are always evaluated against the exact fraction before any serialization rounding, so a first-pass yield of exactly three quarters satisfies an at-least-0.75 threshold.

Planned burn-in durations are whole minutes. Each profile segment's ramp time is rounded half-up to a whole number of minutes first, and the per-segment results are then summed; rounding only once at the end is not compliant. Slot counts, unit tallies, retest counts, and escape counts are integers. Timestamp comparisons, such as calibration due checks, are performed at second precision.

### 2.8. Chamber Slot Ledger and Capacity Accounting

Each chamber's availability is maintained as a slot ledger. The committed load on a chamber is the sum of `slot_count` over that chamber's reservations whose status is `RESERVED` or `IN_PROGRESS`, and the chamber's `available_slots` is its total `slot_count` minus that committed load. The ledger is recomputed immediately — within the same request — whenever a reservation is created, rescheduled with a changed slot count, cancelled, or completed, and whenever a cascade (fixture maintenance, chamber offlining, or program supersession) cancels reservations on the chamber.

The ledger honors a compensating-pair invariant: creating a reservation and then cancelling that same reservation returns `available_slots` to exactly the value it held before the create. At creation, a reservation's `slot_count` must be at least 1 and at most the chamber's current `available_slots`; booking every remaining slot is permitted, while requesting one more than available is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`.

### 2.9. Reservation Windows, Purge Buffers, and Maintenance Intervals

Reservation windows use half-open interval semantics: a booking occupies the span from its `start_at` (inclusive) to its `end_at` (exclusive). A well-formed window requires `start_at` to be at or after the current logical clock and `end_at` to be strictly after `start_at`; malformed or past windows are rejected with `ERR_INVALID_REQUEST`. Two reservations on the same chamber collide when the new window's start falls before an existing reservation's end and that existing reservation's start falls before the new window's end — the standard half-open overlap test — evaluated against all reservations on that chamber that are not `CANCELLED`. A colliding booking is rejected with `ERR_SLOT_OVERLAP`. When a reservation is rescheduled, the reservation itself is excluded from its own overlap scan.

Thermal discipline adds a purge buffer on top of raw overlap. Runs on the same chamber that use different `profile_class` values must be separated by a thirty-minute gap, giving the chamber time to purge between thermal profiles; runs of the same profile class may abut directly, with one run's `end_at` equal to the next run's `start_at`. A booking that places a different-class run adjacent to a non-cancelled neighbor without the half-hour gap is rejected with `ERR_PROFILE_BUFFER_VIOLATION`, on initial booking and on reschedule alike.

Maintenance orders, by contrast, use closed interval semantics: a maintenance window occupies both its `window_start` and its `window_end`, and a well-formed order satisfies `window_start` at or before `window_end`. A new order conflicts with an existing `OPEN` or `IN_PROGRESS` order on the same target whenever the new `window_start` falls at or before the existing window's end and the existing window's start falls at or before the new `window_end` — which means two windows that merely touch, one's start landing exactly on the other's end, still conflict. Such a collision is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT`.

### 2.10. ESD Certification Containment

The ESD containment predicate guards chamber scheduling for sensitive customers. An area is under containment while there exists an ESD audit on that `area_code` that is `OPEN` and carries at least one finding of severity `MAJOR`. When a chamber sits in a contained area and the lot being booked belongs to a customer whose `requires_esd_certification` flag is true, the reservation request — whether an initial booking or a reschedule — is rejected with `ERR_ESD_CONTAINMENT`. Customers without the certification requirement, and areas whose open audits carry only `MINOR` findings or no findings, are unaffected.

### 2.11. Validation Order and Identifier Resolution

Incoming requests are validated against a fixed priority ladder, and the first failing rung determines the error returned — a request that would fail several checks surfaces only the earliest rung's error. The ladder runs:

1. **Authentication**: both headers present and the role declared — otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization and customer scope**: the role is permitted on the endpoint, and a `CustomerRep`'s customer scope matches — otherwise `ERR_UNAUTHORIZED_ROLE` or `ERR_FORBIDDEN_OWNERSHIP`.
3. **Existence**: every identifier referenced in the path and body exists, validated left-to-right — path identifiers first, then body fields in their declared order — otherwise `ERR_NOT_FOUND`. For nested paths this means a missing parent id is reported before a missing child id is even examined.
4. **Lifecycle state**: the target resource's own state permits the operation — a lot `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a review `PENDING` for a decision, an audit `OPEN` for close, a reservation `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED` for validate or release — otherwise `ERR_INVALID_STATE`; and, as an aggregate state gate, no second disposition review may be opened while one is `PENDING` for the lot, otherwise `ERR_REVIEW_PENDING`.
5. **Optimistic concurrency**: the carried expected version matches the current version on the two OCC-guarded writes — otherwise `ERR_STALE_VERSION`.
6. **Business safety**: the customer account is not suspended (`ERR_CUSTOMER_SUSPENDED`), ESD containment does not block the booking (`ERR_ESD_CONTAINMENT`), and retest segregation of duties holds (`ERR_RETEST_SEGREGATION`).
7. **Business temporal**: reservation and maintenance windows are well-formed (`ERR_INVALID_REQUEST`), the referenced lot is `QUEUED` when a reservation is created (`ERR_INVALID_STATE`), the slot-overlap test passes (`ERR_SLOT_OVERLAP`), the purge buffer is honored (`ERR_PROFILE_BUFFER_VIOLATION`), maintenance windows do not collide (`ERR_MAINTENANCE_WINDOW_CONFLICT`), and any consumed retest authorization is still live (`ERR_AUTHORIZATION_EXPIRED`).
8. **Business referential**: the program is `RELEASED` where required (`ERR_PROGRAM_NOT_RELEASED`) and not `OBSOLETE` at recording time (`ERR_PROGRAM_SUPERSEDED`), the referenced fixture is `AVAILABLE` (`ERR_FIXTURE_NOT_AVAILABLE`) and belongs to the lot's program (`ERR_FIXTURE_PROGRAM_MISMATCH`), the chamber is `ONLINE` (`ERR_CHAMBER_NOT_ONLINE`), provided equipment is effectively `IN_SERVICE` (`ERR_EQUIPMENT_NOT_IN_SERVICE`), and program validation finds at least one available fixture (`ERR_NO_AVAILABLE_FIXTURE`).
9. **Business constraints**: the observed bin is mapped (`ERR_BIN_NOT_MAPPED`), the retest policy admits the unit (`ERR_HARD_FAIL_NO_RETEST`, `ERR_RETEST_LIMIT_REACHED`), a retest insertion has an authorization to consume (`ERR_NO_ACTIVE_AUTHORIZATION`), result immutability holds (`ERR_RESULT_IMMUTABLE`), serial numbers stay unique within a lot (`ERR_DUPLICATE_SERIAL`), unit registration stays within the declared quantity (`ERR_QUANTITY_EXCEEDED`), pipeline gates find every unit registered and tested (`ERR_UNITS_INCOMPLETE`), slot capacity and profile support hold (`ERR_SLOT_CAPACITY_EXCEEDED`, `ERR_PROFILE_NOT_SUPPORTED`), audit closure covers every major finding (`ERR_MISSING_CORRECTIVE_ACTION`), direct shipment is permitted (`ERR_DISPOSITION_REVIEW_REQUIRED`), and a lot's part number agrees with its program (`ERR_INVALID_REQUEST`).

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Account Standing

An `OperationsManager` onboards a customer by registering its legal `name`, commercial `tier` — one of `STANDARD` or `STRATEGIC` — and, optionally, the `requires_esd_certification` flag, which defaults to false when omitted. New accounts begin with `account_status` set to `ACTIVE`. The certification flag is not decorative: while it is true, chamber reservations for that customer's lots are blocked whenever the chamber's area is under ESD containment, as described in §2.10.

Account standing is managed through modification of the customer resource, which may suspend or reactivate the account or change its `tier`; each such modification increments the customer's `version`. Suspending a customer transitions `account_status` from `ACTIVE` to `SUSPENDED`, and reactivation returns it to `ACTIVE`. A suspended account blocks new lot creation: any attempt by that customer's representative to create a lot while the account is `SUSPENDED` is rejected with `ERR_CUSTOMER_SUSPENDED`. Suspension has no retroactive effect on lots already in the pipeline.

### 3.2. Test Program Development, Fixtures, and Revision Supersession

A `TestEngineer` authors a test program by supplying the owning `customer_id`, the `part_number` the program tests, a `bin_map`, a `max_retests_per_unit` ceiling, and a `burn_profile`. The `bin_map` is an object mapping each bin code — a string of an integer — to one of `PASS`, `SOFT_FAIL`, or `HARD_FAIL`; bin 1 conventionally denotes a pass. The `burn_profile` is an ordered array of segments, each carrying a `target_temp_c`, a `ramp_rate_c_per_min`, and a `soak_minutes`, and it drives the planned duration of every chamber reservation booked against lots of this program. A new program begins at `revision` 1 in `DRAFT` status, with `supersedes_program_id` null.

Fixtures are the physical adapters that execute a program. Creating one requires the `program_id` it belongs to, a `serial_number`, and a `site_count` describing how many units it tests in parallel per insertion; a new fixture begins in `COMMISSIONING`. Commissioning moves it to `AVAILABLE`, and it may later cycle `AVAILABLE` → `UNDER_MAINTENANCE` → `AVAILABLE` as the house pulls it for service and returns it. Sending a fixture to maintenance has scheduling consequences beyond the fixture itself: every chamber reservation in `RESERVED` status that references the fixture is cancelled, and each such cancellation frees the reservation's slots in the affected chamber's ledger.

Validation advances a program from `DRAFT` to `VALIDATED` and is permitted only while at least one fixture belonging to the program is `AVAILABLE`; attempting validation without one is rejected with `ERR_NO_AVAILABLE_FIXTURE`. Validation increments the program's `version`. Release then advances the program from `VALIDATED` to `RELEASED`, incrementing its `version` again, and fires the supersession cascade. The previously `RELEASED` program for the same `customer_id` and `part_number`, if one exists, transitions to `OBSOLETE` with its own `version` incremented. Every fixture of that superseded program whose `status` is `COMMISSIONING`, `AVAILABLE`, or `UNDER_MAINTENANCE` transitions to `DECOMMISSIONED`, again incrementing each fixture's `version`. Every chamber reservation still in `RESERVED` status that references one of those `DECOMMISSIONED` fixtures is cancelled, incrementing each reservation's `version`. Finally, each of those cancellations recomputes the affected chamber's `available_slots`, freeing the cancelled reservations' slots. Supersession is the only path to `OBSOLETE` — there is no manual obsolete endpoint — and it is always triggered by a release.

Revisioning is deliberately decoupled from release. Minting a successor revision is requested against a source program whose status is `RELEASED` — any other source status is rejected with `ERR_INVALID_STATE` — and the request must carry `expected_test_program_version` per §2.6. The mint creates an entirely new program row: its `revision` is the source's revision plus one, its status is `DRAFT`, its `supersedes_program_id` is the source program's `id`, and its `customer_id`, `part_number`, `bin_map`, `max_retests_per_unit`, and `burn_profile` are copied from the source. The source program's own `version` increments by one even though its status is unchanged, which is precisely what the OCC guard keys on. The new draft then walks the ordinary validate-and-release path; only when it is eventually released does the supersession cascade retire the source.

### 3.3. Chamber Registration and Slot Reservation

An `OperationsManager` registers a burn-in chamber with a `name`, the `area_code` of the ESD audit area it belongs to, a total `slot_count`, and the `supported_profile_classes` it can run — an array drawn from the thermal profile classes `A`, `B`, and `C`. A new chamber comes up `ONLINE` with `available_slots` equal to its full `slot_count`. Chamber status may later move `ONLINE` ↔ `MAINTENANCE`, either by direct operator modification or as the side effect of a maintenance order starting and completing against the chamber. Taking a chamber `OFFLINE` is terminal and forceful: every reservation still `RESERVED` on that chamber is cancelled and the slot ledger is recomputed.

Booking chamber capacity is the system's central scheduling act. An `OperationsManager` reserves slots by supplying the `chamber_id`, the `lot_id` that will occupy the slots, the `fixture_id` that will hold the units, the `profile_class` to run, the `start_at` and `end_at` window, and the number of slots as `slot_count`. Burn-in scheduling happens before test start, so the referenced lot must be `QUEUED`; booking against a lot in any other status is rejected with `ERR_INVALID_STATE`. The chamber must be `ONLINE`, otherwise `ERR_CHAMBER_NOT_ONLINE`. The fixture must be `AVAILABLE`, otherwise `ERR_FIXTURE_NOT_AVAILABLE`, and the fixture's program must be the same program pinned on the lot — a cross-reference checked as `fixture_id` lineage against the lot's `program_id` — otherwise the booking is rejected with `ERR_FIXTURE_PROGRAM_MISMATCH`. The requested `profile_class` must appear among the chamber's `supported_profile_classes`, otherwise `ERR_PROFILE_NOT_SUPPORTED`. Window well-formedness, the half-open overlap test, the thirty-minute purge buffer, the slot-capacity ceiling, and the ESD containment gate all apply as specified in §2.8 through §2.10.

A successfully created reservation lands in `RESERVED` status. Its `planned_duration_minutes` is computed at creation from the burn profile of the lot's pinned program: computation begins from an ambient baseline of 25 °C; for each profile segment in array order, the absolute temperature gap between the segment's target and the previous segment's target (the ambient baseline for the first segment) is divided by that segment's ramp rate, the quotient is rounded half-up to a whole number of ramp minutes, and the segment's soak minutes are added; the planned duration is the sum of these per-segment totals. Rounding each segment's ramp before summing is part of the contract — summing raw ramp minutes and rounding once at the end produces a different integer and is not compliant.

A reservation still in `RESERVED` may be rescheduled: the window, the slot count, and the profile class may all change. The reschedule request must carry `expected_chamber_reservation_version` per §2.6, and the booking is then re-validated against the new values end-to-end: the window must again be well-formed, the chamber must still be `ONLINE`, the fixture must still be `AVAILABLE`, the profile class must still be supported by the chamber, slot capacity must still suffice, and the overlap test, the purge buffer, and the ESD gate are all re-run — with the reservation itself excluded from its own overlap scan. A successful reschedule increments the reservation's `version` and recomputes the chamber's `available_slots` whenever the slot count changed.

Starting a reservation moves it from `RESERVED` to `IN_PROGRESS` and is gated on time and chamber health: the logical clock must have reached `start_at` but not yet reached `end_at`, otherwise `ERR_INVALID_STATE`, and the chamber must be `ONLINE`, otherwise `ERR_CHAMBER_NOT_ONLINE`. Completing a reservation moves it from `IN_PROGRESS` to `COMPLETED` once the clock has reached or passed `end_at`, otherwise `ERR_INVALID_STATE`, and frees its slots in the ledger. Cancelling moves a `RESERVED` reservation to `CANCELLED` and likewise frees its slots — cancellation is the exact compensating action of creation, restoring `available_slots` to its prior value. Both terminal states, `COMPLETED` and `CANCELLED`, are final.

For capacity planning, the system computes a chamber's slot utilization over a caller-supplied window defined by `window_start` and `window_end`, under a `basis` that selects one of two variants. Each selected reservation contributes its `slot_count` multiplied by its overlap with the window, where the overlap is the number of minutes from the later of the reservation's `start_at` and the window start to the earlier of its `end_at` and the window end, floored at zero; these products sum to `numerator_slot_minutes`. Under the `SCHEDULED` basis — the forward-looking measure — reservations in `RESERVED`, `IN_PROGRESS`, or `COMPLETED` status are counted, and `denominator_slot_minutes` is the chamber's total `slot_count` multiplied by the full window length in minutes. Under the `ACTUAL` basis — the chronological measure of completed work — only `COMPLETED` reservations are counted, and the denominator covers only the portion of the window that has already elapsed at the current logical clock, measured from the window start to the earlier of the window end and the clock. The `utilization_ratio` is the numerator divided by the denominator, reported as zero whenever the denominator is zero or negative, and serialized per §2.7. `CANCELLED` reservations are never counted under either basis. The report carries the echoed `basis`, the `utilization_ratio`, `numerator_slot_minutes`, and `denominator_slot_minutes`.

### 3.4. Lot Intake, Unit Registration, and the Test Pipeline

A lot begins when a `CustomerRep` declares an incoming shipment: the payload carries the `customer_id` — which must equal the representative's own identity per §2.1 — the `program_id` of the test program to run, the `part_number`, and the `quantity` of serialized units in the lot, which must be at least 1. The referenced program must be `RELEASED`, otherwise `ERR_PROGRAM_NOT_RELEASED`, and the lot's `part_number` must equal the program's part number, otherwise `ERR_INVALID_REQUEST`. The account must be in good standing per §3.1. A new lot lands in `RECEIVED` status with its tallies zeroed — `units_registered`, `units_untested`, `units_passed`, `units_failed`, and `retested_unit_count` all start at zero — `escape_count` at zero, and `suggested_disposition` null.

Serialized units are registered onto a `RECEIVED` lot, either by the owning `CustomerRep` declaring their serials or by an `OperationsManager` registering on physical receipt; registration on a lot past `RECEIVED` is rejected with `ERR_INVALID_STATE`. Each registration carries the `lot_id` and a `serial_number` that must be unique within the lot — a duplicate is rejected with `ERR_DUPLICATE_SERIAL`. Registration is bounded by the declared quantity: the lot accepts registrations while `units_registered` is below `quantity`, the registration that brings the count exactly to `quantity` is allowed, and any registration beyond that is rejected with `ERR_QUANTITY_EXCEEDED`. A new unit starts `UNTESTED` with `retest_count` zero and `current_bin` null, and the lot's `units_registered` is recomputed.

The pipeline itself is driven by an `OperationsManager` through four transitions. Enqueue moves the lot from `RECEIVED` to `QUEUED` and requires the manifest to be complete — `units_registered` equal to `quantity`, otherwise `ERR_UNITS_INCOMPLETE` — with the program still `RELEASED`, otherwise `ERR_PROGRAM_NOT_RELEASED`. Starting test moves the lot from `QUEUED` to `IN_TEST`. Completing test moves it from `IN_TEST` to `AWAITING_DISPOSITION` and requires every unit to have been tested — `units_untested` equal to zero, otherwise `ERR_UNITS_INCOMPLETE`. At that moment the system computes the lot's `suggested_disposition` per §3.6, and whenever the suggestion is anything other than `SHIP` the system automatically opens a lot disposition review in `PENDING` status with a snapshot of that suggestion. Shipping moves the lot from `AWAITING_DISPOSITION` to `SHIPPED`, but a direct ship is permitted only when the lot's `suggested_disposition` is `SHIP` and no `PENDING` disposition review exists for the lot — otherwise the request is rejected with `ERR_DISPOSITION_REVIEW_REQUIRED` and the lot must instead pass through the MRB decision described in §3.6.

### 3.5. Recording Test Results, the Retest Loop, and Result Voids

Once a lot is `IN_TEST`, a `TestEngineer` records serialized test insertions. Each insertion payload names the `unit_id`, the `fixture_id` used, the observed `bin_code`, and optionally the `equipment_id` of a customer-owned tester or handler used for the insertion. Recording is refused unless the lot is `IN_TEST`, otherwise `ERR_INVALID_STATE`. The program revision pinned on the lot must not have gone `OBSOLETE` — recording against a superseded program is rejected with `ERR_PROGRAM_SUPERSEDED`. The fixture must be `AVAILABLE`, otherwise `ERR_FIXTURE_NOT_AVAILABLE`, and must belong to the lot's program, otherwise `ERR_FIXTURE_PROGRAM_MISMATCH`. When `equipment_id` is provided, that equipment must be effectively `IN_SERVICE` — equipment that has lazily become `CALIBRATION_DUE`, is `IN_MAINTENANCE`, or has been `RETURNED` is rejected with `ERR_EQUIPMENT_NOT_IN_SERVICE`. Finally, the observed `bin_code` must be a key of the pinned program's `bin_map`, otherwise `ERR_BIN_NOT_MAPPED`.

A recorded result is an event, not a state. Its `passed` flag is computed as true exactly when the program's `bin_map` maps the observed bin to `PASS`. Its `insertion_index` is assigned chronologically as the one-based count of the unit's tally-effective results including this one — so a unit's first effective insertion is index 1. The result also denormalizes the unit's `lot_id` and the lot's `program_id` onto itself at creation, pinning the exact program revision used, and captures the recording engineer's identity as `recorded_by_user_id`. A fresh result is neither `voided` nor `excluded_from_tally`, and its `void_reason` and `consumed_authorization_id` begin null.

Unit state is a projection over these events. Replaying a unit's results that are neither voided nor excluded — in creation order, with insertion index breaking ties — yields the unit's `test_status`: `UNTESTED` when the replay set is empty, `PASSED` when the latest effective result passed, and `FAILED` otherwise. The unit's `current_bin` is the latest effective result's bin code, or null while `UNTESTED`. Every insertion recomputes this projection for the unit and recomputes the lot's tallies — `units_untested`, `units_passed`, and `units_failed` count the units in each status, and the three always sum to the lot's `quantity`, before and after any record, void, rework, or escape mutation. A unit that stands `PASSED` accepts no further insertions: the attempt is rejected with `ERR_RESULT_IMMUTABLE`.

The retest loop is where insertions beyond the first become regulated. When a unit stands `FAILED`, recording another insertion requires a live retest authorization to consume. Authorization is granted by a `TestEngineer` supplying the `unit_id` and a free-text `reason`. Four gates apply at grant time, and their ordering follows the ladder in §2.11. The unit must currently stand `FAILED` — otherwise `ERR_INVALID_STATE`. The authorizing engineer's identity must differ from the `recorded_by_user_id` of the unit's latest tally-effective result — the engineer who recorded the failure may not authorize its retest, and a self-authorization is rejected with `ERR_RETEST_SEGREGATION`. The unit's latest bin must map to `SOFT_FAIL` in the program's bin map; units whose latest bin maps to `HARD_FAIL` may never be retested, and the request is rejected with `ERR_HARD_FAIL_NO_RETEST`. And the unit's `retest_count` must be strictly below the program's `max_retests_per_unit` — a count already equal to the ceiling is rejected with `ERR_RETEST_LIMIT_REACHED`. A granted authorization begins `ACTIVE` with `authorized_by_user_id` recorded and an `expires_at` exactly 48 hours after its creation.

Consuming an authorization happens inside result recording. When the new insertion's index would be 2 or higher, the recording must find an `ACTIVE` authorization for the unit — with none present the insertion is rejected with `ERR_NO_ACTIVE_AUTHORIZATION` — and that authorization must still be live against the logical clock: an authorization whose `expires_at` has been reached or passed is treated as `EXPIRED` and the insertion is rejected with `ERR_AUTHORIZATION_EXPIRED`. A successful retest insertion consumes the authorization — it transitions to `CONSUMED` and its id is stored on the result as `consumed_authorization_id` — and increments the unit's `retest_count` by one. The loop may repeat: a retest that still fails leaves the unit `FAILED` and may be authorized again, each cycle consuming one authorization and bounded by the retest ceiling, while a passing retest moves the unit to `PASSED`. The lot's `retested_unit_count` — the number of units with `retest_count` of at least 1 — is recomputed alongside the tallies. An authorization may also be withdrawn before use: revocation moves it from `ACTIVE` to `REVOKED`. Expiry itself is lazy per §2.5 — nothing is stamped until a read or a consume attempt observes the lapsed deadline.

Voiding is the quality counterweight to recording. A `QualityEngineer` voids a result, supplying a `reason` that is captured as the result's `void_reason`. Only the unit's latest tally-effective result may be voided — voiding an older result is rejected with `ERR_INVALID_STATE` — and the void is refused while the lot is `SHIPPED`, also with `ERR_INVALID_STATE`. A result already voided may not be voided again, which is rejected with `ERR_RESULT_IMMUTABLE`. The void flips the result's `voided` flag to true and replays the unit's remaining effective results: the unit's `test_status` and `current_bin` are recomputed from the new latest result, or return to `UNTESTED` and null when none remain. The lot's tallies are recomputed, but the unit's `retest_count` is deliberately not decremented — authorization history is preserved even when the result it enabled is struck from the tally.

### 3.6. Yield Reporting and Lot Disposition

Yield is reported in two variants because the house and its customers read quality differently. The report for a lot — recomputed at completion of test and again on every read of the yield report — carries the `lot_id`, both yield variants, the tallies `units_registered`, `units_passed`, `units_failed`, and `units_untested`, the `retested_unit_count`, the `escape_count`, a `bin_counts` histogram of effective results by bin, and the current `suggested_disposition`.

The `first_pass_yield` is the first-pass quality measure: its numerator counts the units whose first tally-effective result — the insertion at index 1 — passed, and its denominator counts only the units that have at least one tally-effective result at all; it is reported as zero when no unit has been tested. The `final_yield` is the shippable quality measure after retests: its numerator counts the units currently standing `PASSED`, and its denominator is the lot's full `quantity`. Because the two measures differ in both numerator and denominator, identical lot data produces different numbers whenever any unit failed its first insertion. Both ratios are carried as exact fractions and serialized per §2.7.

The `suggested_disposition` converts those measurements into a recommendation, evaluated top-down with the first matching branch winning. When the lot's `escape_count` is at least 1, the suggestion is `SCRAP_REVIEW`. Otherwise, when the first-pass yield is below 0.50 — fewer than half of tested units passing on their first insertion — the suggestion is also `SCRAP_REVIEW`. Otherwise, when the first-pass yield is at least 0.75, the escape count is exactly zero, and the retest rate — `retested_unit_count` divided by `quantity` — is at most 0.25, the suggestion is `SHIP`. Every other combination falls through to `MRB_REVIEW`. All comparisons run against exact fractions with no rounding applied before the comparison. The suggestion is computed when the lot completes test and recomputed if an RMA escape later contains the lot, and it remains null until first computed.

The MRB acts through lot disposition reviews. A `QualityEngineer` opens a review for a lot in `AWAITING_DISPOSITION` or `CONTAINED` by supplying the `lot_id`; the lot's lifecycle refusing otherwise is surfaced as `ERR_INVALID_STATE`. Only one `PENDING` review may exist for a lot at a time — opening a second is rejected with `ERR_REVIEW_PENDING`. The new review snapshots the lot's current `suggested_disposition` at creation, starts `PENDING`, and has `decision`, `rationale`, and `decided_by_user_id` all null. Reviews are also opened automatically: completing test with any non-`SHIP` suggestion creates one, and an RMA escape containment creates another.

Deciding a review moves it from `PENDING` to `DECIDED`. The `QualityEngineer` supplies a `decision` of `SHIP`, `SCRAP`, or `REWORK` together with a `rationale`; the decider's identity is recorded as `decided_by_user_id`. The decision drives the lot. For a lot in `AWAITING_DISPOSITION`: `SHIP` moves it to `SHIPPED`, `SCRAP` moves it to `SCRAPPED`, and `REWORK` loops it back to `QUEUED`. For a lot in `CONTAINED`: `SHIP` releases containment and returns it to `SHIPPED`, `SCRAP` moves it to `SCRAPPED`, and `REWORK` likewise loops it back to `QUEUED`. A decision against a review no longer `PENDING` is rejected with `ERR_INVALID_STATE`.

Rework is a full reset of the lot's test genealogy. Every unit of the lot returns to `UNTESTED` with `current_bin` null and `retest_count` reset to zero. Every non-voided test result of the lot is marked `excluded_from_tally`, so excluded rows no longer drive unit state or tallies — though they remain recorded history. The lot's tallies are recomputed with `units_untested` equal to `quantity`, ready for the lot to cycle through the queue, test, and disposition stages again; a lot may loop this way repeatedly.

### 3.7. Customer-Owned Equipment and Maintenance Operations

Customers may loan their own testers, handlers, and probers to the house. An `OperationsManager` registers such equipment with the owning `customer_id`, an `equipment_type` of `TESTER`, `HANDLER`, or `PROBER`, a `serial_number`, a `calibration_interval_days` of at least 1, and the `last_calibrated_at` timestamp. Registration computes `next_calibration_due` as `last_calibrated_at` plus the calibration interval in days, and the equipment begins `IN_SERVICE`.

Calibration discipline is enforced lazily and at the point of use. Equipment whose stored status is `IN_SERVICE` is effectively `CALIBRATION_DUE` whenever the logical clock has reached or passed `next_calibration_due` — the boundary is inclusive, so a clock exactly equal to the due timestamp already reads as due. Only effectively in-service equipment may be named on a test insertion; anything else — due for calibration, in maintenance, or returned — is rejected with `ERR_EQUIPMENT_NOT_IN_SERVICE`, as described in §3.5. When the loan ends, an `OperationsManager` returns the equipment: from `IN_SERVICE`, `CALIBRATION_DUE`, or `IN_MAINTENANCE` it transitions to the terminal `RETURNED` status.

Maintenance itself is scheduled through maintenance orders, which are polymorphic: the `target_type` of `EQUIPMENT` or `CHAMBER` selects which aggregate the `target_id` references — customer equipment in the first case, a chamber in the second. Each order carries a `kind` of `CALIBRATION`, `REPAIR`, or `PREVENTIVE` and a closed window from `window_start` through `window_end`; the window must be well-formed per §2.9, and closed-interval conflicts against other live orders on the same target are rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT`. A new order begins `OPEN`.

Starting an order moves it from `OPEN` to `IN_PROGRESS` and pulls its target out of service. The logical clock must fall within the closed window — at or after `window_start` and at or before `window_end` — otherwise `ERR_INVALID_STATE`, and the target must not already be `RETURNED` or `OFFLINE`, also `ERR_INVALID_STATE`. On a successful start, equipment moves to `IN_MAINTENANCE` (from either `IN_SERVICE` or `CALIBRATION_DUE`) and a chamber moves to `MAINTENANCE`. Completing an order moves it from `IN_PROGRESS` to `DONE` and returns the target to service — equipment to `IN_SERVICE`, a chamber to `ONLINE`. When the completed order targets equipment and its kind is `CALIBRATION`, completion also stamps `last_calibrated_at` with the current logical clock and recomputes `next_calibration_due` from it. An order still `OPEN` may instead be cancelled, moving it to `CANCELLED` and freeing its window.

### 3.8. ESD Program Audits

A `QualityEngineer` opens an ESD program audit on an area by supplying its `area_code` and the `findings` observed — an array of entries each pairing a `severity` of `MINOR` or `MAJOR` with a `description`, and possibly empty when the area is clean. The audit begins `OPEN`, records the auditor's identity as `auditor_user_id`, starts with an empty `corrective_actions` list, and has no `outcome` yet — it remains null until close. An `OPEN` audit is already consequential: while it carries any `MAJOR` finding, its area is under containment per §2.10, blocking chamber reservations for certification-requiring customers in that area with `ERR_ESD_CONTAINMENT`.

Closing an audit moves it from `OPEN` to `CLOSED`. The closer supplies `corrective_actions`, an array of entries each pairing a `finding_index` with the corrective `action` taken. Every `MAJOR` finding index must be covered by a corrective action — an incomplete covering is rejected with `ERR_MISSING_CORRECTIVE_ACTION`. On a successful close the `outcome` is computed: `PASS` when the audit recorded no findings at all, `PASS_WITH_MINOR` when findings exist but all are `MINOR`, and `FAIL` when any finding is `MAJOR`. Once closed, the audit no longer holds its area in containment.

### 3.9. RMA Failure Analysis and Test-Escape Containment

When a shipped unit fails in the field, the owning `CustomerRep` opens an RMA case supplying the `lot_id`, the `unit_id` of the returned serialized unit, and a `failure_mode` describing the customer-reported symptom. The case is admissible only for a genuinely shippable lineage: the unit must belong to the referenced lot, the lot must be `SHIPPED`, and the unit must stand `PASSED` — otherwise the request is rejected with `ERR_INVALID_STATE`. Ownership scoping per §2.1 applies, so the lot must belong to the representative's own customer. The new case begins with its `fa_status` at `INTAKE`, with `created_by_customer_id` recorded from the representative's identity and no `fa_conclusion` yet.

Failure analysis is a `QualityEngineer` workflow in three steps. Starting analysis moves the case from `INTAKE` to `FA_IN_PROGRESS`. Completing analysis moves it to `FA_COMPLETE` and records the engineer's `fa_conclusion` — one of `TEST_ESCAPE`, `CUSTOMER_INDUCED`, or `NO_TROUBLE_FOUND`. Closing the case moves it from `FA_COMPLETE` to `CLOSED`.

The close is where a test escape bites. When the recorded conclusion is `TEST_ESCAPE`, closing fires the containment cascade on the source lot: the lot's `escape_count` increments by one; the escaped unit's `test_status` flips to `FAILED` with its `current_bin` nulled; the lot's tallies are recomputed, moving one unit from the passed count to the failed count; the lot itself transitions from `SHIPPED` to `CONTAINED`; and its `suggested_disposition` is recomputed — with an escape count of at least 1, the first branch of the suggestion rule forces `SCRAP_REVIEW`. A lot disposition review is then created automatically in `PENDING` status carrying that `SCRAP_REVIEW` suggestion, and the MRB decides containment per §3.6 — releasing the lot back to `SHIPPED`, scrapping it, or looping it through rework. Conclusions of `CUSTOMER_INDUCED` or `NO_TROUBLE_FOUND` close the case with no effect on the lot at all.

## 4. Endpoint Definitions

Operations that create new resources — registering a customer, program, fixture, chamber, reservation, lot, unit, result, authorization, equipment record, maintenance order, audit, RMA case, disposition review, or minting a program revision — return a `201 Created` status code. Operations that modify an existing resource, including every state transition, return `200 OK`. Read endpoints return `200 OK`. The request and response payloads of each endpoint are governed by the narratives in §3 together with the global envelope in §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock used by every time-dependent rule | OperationsManager |
| POST | `/api/customers` | Register a customer | OperationsManager |
| GET | `/api/customers/{customer_id}` | Get a customer | All roles |
| PATCH | `/api/customers/{customer_id}` | Suspend or activate the account, or change tier | OperationsManager |
| POST | `/api/test-programs` | Create a DRAFT test program (revision 1) | TestEngineer |
| GET | `/api/test-programs/{program_id}` | Get a test program | All roles |
| GET | `/api/test-programs` | List test programs, filterable by customer, supersession link, and status | All roles |
| POST | `/api/test-programs/{program_id}/validate` | DRAFT to VALIDATED (requires an AVAILABLE fixture) | TestEngineer |
| POST | `/api/test-programs/{program_id}/release` | VALIDATED to RELEASED; supersedes the prior released revision | TestEngineer |
| POST | `/api/test-programs/{program_id}/revisions` | Mint the next revision as a new DRAFT row (OCC-guarded) | TestEngineer |
| POST | `/api/fixtures` | Create a fixture for a program (COMMISSIONING) | TestEngineer |
| GET | `/api/fixtures/{fixture_id}` | Get a fixture | All roles |
| GET | `/api/fixtures` | List fixtures, filterable by program and status | All roles |
| POST | `/api/fixtures/{fixture_id}/commission` | COMMISSIONING to AVAILABLE | TestEngineer |
| POST | `/api/fixtures/{fixture_id}/maintenance` | AVAILABLE to UNDER_MAINTENANCE; cancels future RESERVED reservations using it | TestEngineer |
| POST | `/api/fixtures/{fixture_id}/return-from-maintenance` | UNDER_MAINTENANCE to AVAILABLE | TestEngineer |
| POST | `/api/chambers` | Register a burn-in chamber (ONLINE) | OperationsManager |
| GET | `/api/chambers/{chamber_id}` | Get a chamber, including computed `available_slots` | All roles |
| PATCH | `/api/chambers/{chamber_id}` | Chamber status transitions ONLINE to/from MAINTENANCE, or ONLINE to terminal OFFLINE | OperationsManager |
| GET | `/api/chambers/{chamber_id}/utilization` | Computed slot utilization over a window; `basis` selects the variant | All roles |
| POST | `/api/chamber-reservations` | Reserve chamber slots for a lot's burn-in window | OperationsManager |
| GET | `/api/chamber-reservations/{reservation_id}` | Get a reservation | All roles |
| GET | `/api/chamber-reservations` | List reservations, filterable by chamber, lot, fixture, and status | All roles |
| PATCH | `/api/chamber-reservations/{reservation_id}` | Reschedule a RESERVED reservation (window, slots, profile class; OCC-guarded) | OperationsManager |
| POST | `/api/chamber-reservations/{reservation_id}/start` | RESERVED to IN_PROGRESS within the window | OperationsManager |
| POST | `/api/chamber-reservations/{reservation_id}/complete` | IN_PROGRESS to COMPLETED; frees slots | OperationsManager |
| POST | `/api/chamber-reservations/{reservation_id}/cancel` | RESERVED to CANCELLED; frees slots | OperationsManager |
| POST | `/api/lots` | Create a lot (RECEIVED) | CustomerRep |
| GET | `/api/lots/{lot_id}` | Get a lot, including computed tallies, escapes, and suggestion | All roles |
| GET | `/api/lots` | List lots, filterable by customer, program, and status | All roles |
| POST | `/api/lots/{lot_id}/enqueue` | RECEIVED to QUEUED (all units registered; program released) | OperationsManager |
| POST | `/api/lots/{lot_id}/start-test` | QUEUED to IN_TEST | OperationsManager |
| POST | `/api/lots/{lot_id}/complete-test` | IN_TEST to AWAITING_DISPOSITION; computes suggestion and may open a review | OperationsManager |
| POST | `/api/lots/{lot_id}/ship` | Direct ship from AWAITING_DISPOSITION when the suggestion is SHIP and no review is pending | OperationsManager |
| GET | `/api/lots/{lot_id}/yield-report` | Computed yield report with dual-variant yields, tallies, bin histogram, and suggestion | All roles |
| POST | `/api/units` | Register a serialized unit on a RECEIVED lot | OperationsManager, CustomerRep |
| GET | `/api/units/{unit_id}` | Get a unit | All roles |
| GET | `/api/units` | List units, filterable by lot and test status | All roles |
| POST | `/api/test-results` | Record a serialized test insertion; consumes an authorization beyond the first insertion | TestEngineer |
| GET | `/api/test-results/{result_id}` | Get a test result | All roles |
| GET | `/api/test-results` | List test results, filterable by unit, lot, fixture, equipment, and program | All roles |
| POST | `/api/test-results/{result_id}/void` | Void the unit's latest tally-effective result and replay the remainder | QualityEngineer |
| POST | `/api/retest-authorizations` | Authorize one more insertion for a FAILED soft-fail unit (48-hour validity) | TestEngineer |
| GET | `/api/retest-authorizations/{authorization_id}` | Get a retest authorization | All roles |
| GET | `/api/retest-authorizations` | List retest authorizations, filterable by unit and status | All roles |
| POST | `/api/retest-authorizations/{authorization_id}/revoke` | ACTIVE to REVOKED | TestEngineer |
| POST | `/api/customer-equipment` | Register customer-owned equipment (IN_SERVICE) | OperationsManager |
| GET | `/api/customer-equipment/{equipment_id}` | Get equipment with lazy calibration-due derivation applied | All roles |
| GET | `/api/customer-equipment` | List customer equipment, filterable by customer and status | All roles |
| POST | `/api/customer-equipment/{equipment_id}/return` | Any non-terminal status to RETURNED | OperationsManager |
| POST | `/api/maintenance-orders` | Schedule a maintenance window on equipment or a chamber | OperationsManager |
| GET | `/api/maintenance-orders/{order_id}` | Get a maintenance order | All roles |
| GET | `/api/maintenance-orders` | List maintenance orders, filterable by target and status | All roles |
| POST | `/api/maintenance-orders/{order_id}/start` | OPEN to IN_PROGRESS within the window; target leaves service | OperationsManager |
| POST | `/api/maintenance-orders/{order_id}/complete` | IN_PROGRESS to DONE; target returns to service; calibration restamps the due date | OperationsManager |
| POST | `/api/maintenance-orders/{order_id}/cancel` | OPEN to CANCELLED; frees the window | OperationsManager |
| POST | `/api/esd-audits` | Open an ESD program audit on an area | QualityEngineer |
| GET | `/api/esd-audits/{audit_id}` | Get an ESD audit | All roles |
| GET | `/api/esd-audits` | List ESD audits, filterable by area and status | All roles |
| POST | `/api/esd-audits/{audit_id}/close` | OPEN to CLOSED; every MAJOR finding needs a corrective action; outcome computed | QualityEngineer |
| POST | `/api/rma-cases` | Open an RMA for a PASSED unit of a SHIPPED lot | CustomerRep |
| GET | `/api/rma-cases/{rma_id}` | Get an RMA case | All roles |
| GET | `/api/rma-cases` | List RMA cases, filterable by lot, unit, and FA status | All roles |
| POST | `/api/rma-cases/{rma_id}/start-fa` | INTAKE to FA_IN_PROGRESS | QualityEngineer |
| POST | `/api/rma-cases/{rma_id}/complete-fa` | FA_IN_PROGRESS to FA_COMPLETE with a failure-analysis conclusion | QualityEngineer |
| POST | `/api/rma-cases/{rma_id}/close` | FA_COMPLETE to CLOSED; a test escape fires lot containment | QualityEngineer |
| POST | `/api/lot-disposition-reviews` | Open an MRB review for an AWAITING_DISPOSITION or CONTAINED lot | QualityEngineer |
| GET | `/api/lot-disposition-reviews/{review_id}` | Get a review | All roles |
| GET | `/api/lot-disposition-reviews` | List reviews, filterable by lot and status | All roles |
| POST | `/api/lot-disposition-reviews/{review_id}/decide` | PENDING to DECIDED; drives the lot transition per decision | QualityEngineer |

## 5. Error Code Catalogue

The trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_PENDING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_ESD_CONTAINMENT` | 409 Conflict |
| `ERR_RETEST_SEGREGATION` | 403 Forbidden |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_PROFILE_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_AUTHORIZATION_EXPIRED` | 409 Conflict |
| `ERR_PROGRAM_NOT_RELEASED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_SUPERSEDED` | 409 Conflict |
| `ERR_FIXTURE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_FIXTURE_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CHAMBER_NOT_ONLINE` | 409 Conflict |
| `ERR_EQUIPMENT_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_NO_AVAILABLE_FIXTURE` | 422 Unprocessable Entity |
| `ERR_BIN_NOT_MAPPED` | 422 Unprocessable Entity |
| `ERR_HARD_FAIL_NO_RETEST` | 422 Unprocessable Entity |
| `ERR_RETEST_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_AUTHORIZATION` | 409 Conflict |
| `ERR_RESULT_IMMUTABLE` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_QUANTITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNITS_INCOMPLETE` | 409 Conflict |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROFILE_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_MISSING_CORRECTIVE_ACTION` | 422 Unprocessable Entity |
| `ERR_DISPOSITION_REVIEW_REQUIRED` | 409 Conflict |
