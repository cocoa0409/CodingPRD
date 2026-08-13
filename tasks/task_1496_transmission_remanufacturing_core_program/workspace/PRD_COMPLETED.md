# Transmission Reman Core Program API — Product Requirements Document

## 1. Introduction

Remanufactured automatic transmissions live and die by two economics that rarely meet inside one system. On the build side, hard-part inventory, interchange rules, valve-body calibration with TCM flash, and dynamometer shift-quality verification decide whether a unit is allowed to ship. On the core side, a deposit collected at sale must later be reconciled against whatever greasy, incomplete, or late core actually comes back through the dock. This document specifies the Transmission Reman Core Program API, a single service that orchestrates both sides of that business: core intake and completeness inspection, hard-part inventory with an interchange catalog, build specifications keyed by year, make, and model, dyno and shift-quality testing, the core deposit invoice and credit lifecycle, installer warranty with labor allowances, and defective-return routing.

The API is built for a plant floor with real contention and real audit requirements. Kit allocation is all-or-nothing against conserved inventory, dyno capacity is scheduled through explicit cell windows, calibration verification is segregation-of-duties controlled, and a hard dyno attempt budget pushes failing builds through rework and ultimately into engineering review. Financially, every shipment opens a core deposit invoice whose provisional estimate is later replaced by a graded settlement, with a dispute and re-inspection cycle for contested cores and an adjusted-settlement escape hatch. A server-side logical clock governs every timestamp and every time-based rule, so behavior is deterministic and reproducible; two inventory- and order-facing writes are additionally guarded by optimistic concurrency control.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, resource identity, the logical clock, numeric precision, concurrency control, and the ordered validation pipeline every request passes through. All endpoints are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Eleven role strings are recognized, spelled exactly as follows: `ProgramAdmin`, who owns the transmission model catalog, dispute resolution, and the logical clock; `InventoryPlanner`, who owns hard-part inventory and the interchange catalog; `RemanPlanner`, who plans builds by creating orders, reserving kits, resyncing specifications, shipping, and cancelling; `RemanTechnician`, who builds units and books dyno cells; `Calibrator`, who drafts and verifies valve-body calibrations; `DynoOperator`, who records dynamometer test runs; `CoreIntakeClerk`, who registers returned cores and files deposit disputes; `CoreInspector`, who performs completeness inspection and grading; `Installer`, who files warranty claims and ships defective units back; `WarrantyAdjuster`, who adjudicates claims, pays allowances, and receives defective returns; and `Any`, a wildcard role standing in for any authenticated caller on the read endpoints. A role string outside these eleven still counts as an authenticated caller on the `Any` read endpoints and is rejected with `ERR_INSUFFICIENT_PERMISSIONS` on every restricted endpoint.

For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server never compares it against any entity's `id`. Two resources nevertheless record the caller's identifier for later comparison. When a `Calibrator` writes a calibration draft, the acting `X-User-ID` is stored as `cal_created_by_id` on the order, and a later verification must arrive under a different identifier (§3.3). When an `Installer` files a warranty claim, the acting `X-User-ID` is stored as `installer_id` on the claim, and the subsequent return-shipment action is accepted only from that same identifier (§3.8).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock UTC at request time; it does not read the logical clock of §2.5.
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
- The `message` provides a human-readable explanation of what went wrong. Requests to an undefined path, requests using an unsupported method on a defined path, and unexpected server failures are also answered in this envelope, carrying `ERR_INVALID_REQUEST` with HTTP 404, 405, and 400 respectively.

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, and an unparseable value falls back to the default. The `offset` parameter states how many items to skip and defaults to 0; a negative value is clamped to 0 and an unparseable value falls back to the default.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope. `total_count` counts every resource matching the filters before pagination, and `has_more` is true exactly when `offset` plus `limit` is less than `total_count`. Resources sharing the same `created_at` instant retain their insertion order within the sort.

### 2.4. Common Resource Properties

Primary mutable resources — transmission models, hard parts, reman orders, core units, core deposit invoices, and warranty claims — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation.
- `version` (integer): a system-managed counter that starts at 1 on creation, increments with every modification to the resource, and backs the optimistic concurrency rules of §2.7.

Three resources are immutable records and therefore carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. They are the interchange mapping, the dyno booking, and the dyno test run. All timestamps the server writes, including `created_at` and `updated_at`, read the logical clock described in §2.5.

### 2.5. The Logical Clock

Time inside this system is logical, not wall-clock. The server maintains a logical clock whose startup default, before any call adjusts it, is exactly 2026-08-01T00:00:00Z, and the clock never falls back to wall-clock time. Every timestamp the system writes — `created_at`, `issued_at`, `shipped_at`, `received_at`, and `cal_created_at` — reads this clock, and every time-based rule (booking windows, calibration staleness, warranty windows, core lateness) evaluates against it. A `ProgramAdmin`-only capability advances or sets the clock to a supplied `to_iso8601` instant.

### 2.6. Money, Scores, and Rounding

Monetary values are integer cents everywhere: deposits, credits, forfeitures, allowances, caps, part costs, and labor rates. Credit and allowance computations round half-up to zero decimal places, that is, to whole cents. Dyno scoring works at a finer grain: each per-gear penalty and the resulting `shift_quality_score` are rounded half-up to two decimal places. Every settled invoice honors the deposit invariant: `final_credit_cents` plus `forfeited_cents` always equals `deposit_cents`.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are version-gated, and on both the version field is non-optional. Re-pinning an order to its model's current specification requires `expected_reman_order_version` matching the order's current `version`; applying a stock adjustment to a hard part requires `expected_hard_part_version` matching the part's current `version`. When the supplied value no longer matches the parent resource's current `version` — because another writer has advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The product semantics deliberately allow any number of sequential resyncs and any number of sequential adjustments to succeed on their own merits, so the version check is the only deterministic signal that the caller based the request on a stale view of the order or the part. Successful gated writes themselves advance `version` by 1, so a retry with the same expected version fails. No endpoint other than these two accepts a version field.

### 2.8. The Request Validation Pipeline

Every request is evaluated against a fixed pipeline of check families, in the order below, and the first failing family determines the error returned:

1. **Authentication context** — `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — the role is permitted on this endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Request body shape** — required fields present, enum values valid, types correct, every window's end strictly after its start, `year_end` at least `year_start`, and quantities, rates, and deposits positive, else `ERR_INVALID_REQUEST`; fields beyond an endpoint's documented contract are ignored.
4. **Resource existence** — identifiers in the path are validated first, then foreign-key identifiers in the body, working left to right; the first unknown identifier yields its specific 404: `ERR_MODEL_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_INTERCHANGE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_DYNO_RUN_NOT_FOUND`, `ERR_CORE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`.
5. **Optimistic concurrency** — on the two version-gated writes of §2.7, the expected version must match, else `ERR_STALE_VERSION`.
6. **State gates** — the target entity must be in a status that permits the operation, including the sibling gates that a covering dyno booking exists and that an invoice is `OPEN` and unlinked before core registration; failures surface the state-family errors `ERR_ORDER_NOT_READY_FOR_KIT`, `ERR_ORDER_NOT_READY_FOR_ASSEMBLY`, `ERR_ORDER_NOT_READY_FOR_CALIBRATION`, `ERR_CAL_NOT_DRAFT`, `ERR_ORDER_NOT_IN_DYNO_QUEUE`, `ERR_NO_ACTIVE_DYNO_BOOKING`, `ERR_ORDER_NOT_SHIPPABLE`, `ERR_ORDER_NOT_CANCELLABLE`, `ERR_ORDER_NOT_RESYNCABLE`, `ERR_INVOICE_NOT_OPEN`, `ERR_CORE_NOT_INSPECTABLE`, `ERR_INVOICE_NOT_DISPUTABLE`, `ERR_INVOICE_NOT_DISPUTED`, `ERR_ORDER_NOT_SHIPPED`, `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_CLAIM_NOT_PAYABLE`, `ERR_RETURN_NOT_SHIPPABLE`, `ERR_RETURN_NOT_RECEIVABLE`, and `ERR_RETURN_NOT_RECEIVED`.
7. **Segregation of duties** — on calibration verification only, the verifier must differ from the drafter, else `ERR_SOD_VERIFICATION_FORBIDDEN`.
8. **Temporal guards** — a dyno booking must end after the current logical time (`ERR_BOOKING_IN_PAST`), a calibration draft must be at most 72 hours old at verification (`ERR_CAL_STALE`), and a warranty claim must be filed within the warranty window pinned on the order (`ERR_WARRANTY_WINDOW_EXPIRED`).
9. **Constraint checks** — no duplicate interchange pair (`ERR_DUPLICATE_INTERCHANGE`), no overlapping dyno cell window (`ERR_DYNO_CELL_OVERLAP`), no conflicting dock appointment (`ERR_DOCK_OVERLAP`), and the dyno attempt budget still has room (`ERR_DYNO_ATTEMPT_EXHAUSTED`).
10. **Fiscal floors** — a stock adjustment must not drive `qty_on_hand` below zero (`ERR_NEGATIVE_STOCK`), and a dispute adjustment must lie within the deposit range (`ERR_ADJUSTMENT_OUT_OF_RANGE`).

Ordering matters wherever several families apply to one call. On calibration verification, a missing header surfaces before the state gate, the state gate surfaces before the segregation-of-duties check, and segregation surfaces before draft staleness. On a stock adjustment, a stale `expected_hard_part_version` answers `ERR_STALE_VERSION` even when the requested delta would also breach the negative-stock floor. On a dyno run, an order in the wrong status answers `ERR_ORDER_NOT_IN_DYNO_QUEUE` before booking coverage is considered, and booking coverage precedes the attempt budget. On core registration, a malformed dock window answers `ERR_INVALID_REQUEST` before the invoice's existence or status is examined, and the invoice's `OPEN` gate precedes the dock-overlap check.

### 2.9. Inventory Conservation and the Promotion Scan

Inventory is conserved. A hard part's `availability` — the read-only difference between `qty_on_hand` and `qty_reserved` — is the only measure the kit allocator consults, and a requirement line is allocatable only when a candidate's availability is at least the needed quantity. `qty_on_hand` changes through exactly three channels: stock adjustments, reservation consumption at ship time, and salvage restock from warranty returns; it must never go negative. `qty_reserved` changes through kit reservation, promotion, release on cancellation or engineering review, and consumption at ship.

Waiting builds are rescued automatically. After any availability-increasing event — a positive stock adjustment, a reservation release (from a cancellation or a third dyno failure), or a salvage restock — the promotion scan walks all `PART_HOLD` orders in `created_at` ascending order, re-runs the full allocation for each, and promotes every order that now fully resolves from `PART_HOLD` to `ASSEMBLY` with fresh reservations. Availability is re-checked after each promotion, so an earlier waiting order consumes stock before later orders are evaluated.

### 2.10. Build-Spec Pinning and Model Versioning

Build specifications are pinned, not chased. A model's `spec_version` starts at 1 on creation and increments by exactly 1 on every update; the update also increments the model's `version`. Each order snapshots the model's `required_parts`, `dyno_targets`, `flat_rate_hours`, `labor_cap_cents`, `core_deposit_cents`, and `warranty_days` into its `pinned_spec` at creation and records the then-current `spec_version` as `model_spec_version_pin`. Later model updates never rewrite an existing order's pin — deposits, labor guides, dyno targets, and kit contents are all judged against the snapshot. The only way to re-point an order at the live spec is the explicit, version-gated resync described in §3.3.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Models, Hard Parts, and Interchange

A `ProgramAdmin` curates the transmission catalog. Creating a model requires a `model_code` unique across all models (a duplicate is rejected with `ERR_INVALID_REQUEST`), the applicable year range `year_start` through `year_end` with the end year at least the start year, the vehicle `make` and `model`, the `core_deposit_cents` charged at sale for the family, the `flat_rate_hours` labor guide for a remove-and-replace on the model, the `labor_cap_cents` ceiling on warranty labor payouts, the `dyno_targets` array — one entry per gear pairing a `gear` number with a `target_pressure_kpa`, iterated ascending by gear during scoring — and the `required_parts` kit specification, an array of `part_family` and `qty` pairs describing what one build consumes. An optional `warranty_days` sets the coverage window in days from shipment; it must be a positive integer when supplied and defaults to 365 when omitted. Updating a model accepts any subset of `core_deposit_cents`, `flat_rate_hours`, `labor_cap_cents`, `warranty_days`, `dyno_targets`, and `required_parts`; every update bumps the model's `spec_version` and `version` per §2.10 while existing orders keep their pinned snapshots.

An `InventoryPlanner` maintains the hard-part catalog. A new part carries a `part_number` unique across all hard parts (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `part_family` naming the functional grouping used by build specs (families such as pump, planetary, or drum), a `unit_cost_cents` that doubles as the allocation ranking key within a tier (any integer is accepted; no positivity floor applies), and an initial `qty_on_hand` (a non-negative integer — zero is permitted). The system-managed `qty_reserved` starts at 0, and the read-only `availability` always reflects the on-hand quantity minus the reserved quantity.

Stock corrections flow through a single version-gated adjustment. The request applies a signed `qty_delta` to `qty_on_hand` and must carry `expected_hard_part_version` equal to the part's current `version`, failing with `ERR_STALE_VERSION` when it does not (§2.7). Any adjustment that would push `qty_on_hand` below zero is rejected with `ERR_NEGATIVE_STOCK`. A successful adjustment increments the part's `version` by 1, and a positive delta fires the `PART_HOLD` promotion scan of §2.9.

The interchange catalog declares which parts fit which models. Creating a mapping names a `hard_part_id`, a `transmission_model_id`, and a `tier` of `DIRECT` or `ADAPTED`; the pair of part and model must be unique, and a duplicate is rejected with `ERR_DUPLICATE_INTERCHANGE`. Picking an `ADAPTED` part during kitting adds 30 surcharge labor minutes to the build (§3.2). The mapping collection accepts optional `hard_part_id` and `transmission_model_id` filters.

### 3.2. Order Creation and Kit Reservation

A `RemanPlanner` opens a build by creating a reman order with a `transmission_model_id` and an opaque `buyer_ref` that will later be copied onto the core deposit invoice. At creation the server snapshots the model's current build spec into `pinned_spec` and records the model's `spec_version` in `model_spec_version_pin`, per §2.10. A new order starts in `QUEUED` status with `core_settlement_status` `PENDING`, `cal_status` `NONE`, `cal_generation` at 0, `dyno_attempts_used` at 0, `surcharge_labor_minutes` at 0, and `shortage_parts` and `reserved_parts` both empty. The order collection accepts optional `transmission_model_id` and `status` filters.

Kit reservation is the first gated transition and is strictly all-or-nothing. A `RemanPlanner` may request kitting only while the order is `QUEUED` or `PART_HOLD`; in any other status the request is rejected with `ERR_ORDER_NOT_READY_FOR_KIT`. The allocator processes the pinned `required_parts` lines sorted by `part_family` ascending. For each line, the candidates are hard parts whose `part_family` matches the line, that carry an interchange mapping to the order's `transmission_model_id`, and whose `availability` is at least the needed quantity. Quantities hypothetically reserved for lines already resolved earlier in the same allocation run count against a candidate's remaining availability, so two lines drawing on the same part cannot both spend the same stock. Candidates rank `DIRECT` before `ADAPTED`, then by `unit_cost_cents` ascending, with ties broken by the part's `created_at` ascending — never by identifier. The first candidate in that ranking is picked.

When every line resolves, each pick increments its part's `qty_reserved` by the reserved quantity, every `ADAPTED` pick adds 30 minutes to the order's `surcharge_labor_minutes`, the picks are recorded in `reserved_parts` as lines of `hard_part_id`, `part_family`, `qty`, and `tier`, `shortage_parts` clears to empty, and the order advances `QUEUED` → `ASSEMBLY` with its `version` incremented by 1. When even one line has no allocatable candidate, nothing is reserved at all: the unallocatable families are recorded in `shortage_parts`, `reserved_parts` stays empty, and the order slides `QUEUED` → `PART_HOLD`. Re-requesting kitting against a `PART_HOLD` order retries the same allocation — success promotes it to `ASSEMBLY` with fresh reservations, while a persistent shortage leaves it in `PART_HOLD` with `shortage_parts` refreshed. Waiting orders are also rescued without any client action by the promotion scan of §2.9, which applies the identical allocation and promotes each fully resolving order `PART_HOLD` → `ASSEMBLY`.

### 3.3. Assembly, Calibration, and Mid-Flight Specification Changes

Once parts are kitted, a `RemanTechnician` marks assembly complete, moving the order from `ASSEMBLY` to `CALIBRATION`; against any other status the attempt fails with `ERR_ORDER_NOT_READY_FOR_ASSEMBLY`.

Valve-body calibration is drafted by a `Calibrator` and is permitted only while the order is `CALIBRATION` or `REWORK` — otherwise `ERR_ORDER_NOT_READY_FOR_CALIBRATION`. Each draft write requires `solenoid_trims` (an array) and `tcm_flash_version` (a non-empty string) and replaces the current draft wholesale: the payload's `solenoid_trims` and `tcm_flash_version` are stored, `cal_status` becomes `DRAFT`, `cal_generation` increments by 1, `cal_created_by_id` records the drafter's `X-User-ID`, and `cal_created_at` reads the logical clock.

Verification is a second `Calibrator` act guarded by segregation of duties. From either `CALIBRATION` or `REWORK`, verification requires the order to be in one of those two statuses (`ERR_ORDER_NOT_READY_FOR_CALIBRATION`), a calibration currently in `DRAFT` (`ERR_CAL_NOT_DRAFT`), a verifier whose `X-User-ID` differs from `cal_created_by_id` (`ERR_SOD_VERIFICATION_FORBIDDEN`), and a draft whose age from `cal_created_at` to the current logical time is at most 72 hours (`ERR_CAL_STALE`). A successful verification flips `cal_status` from `DRAFT` to `VERIFIED`, applies the TCM flash by copying `tcm_flash_version` into `tcm_flash_version_applied` — a field that stays null until the first verification — and advances the order to `DYNO_QUEUE`.

Specifications drift while builds wait, so a `RemanPlanner` may re-pin an order to the model's current spec: the resync replaces `pinned_spec` with the model's live spec and updates `model_spec_version_pin` to the model's current `spec_version`. Resync is allowed only while the order is `QUEUED`, `PART_HOLD`, `ASSEMBLY`, `CALIBRATION`, or `REWORK`; against any other status the request is rejected with `ERR_ORDER_NOT_RESYNCABLE`. The operation is version-gated per §2.7: the request must carry `expected_reman_order_version` matching the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful resync increments the order's `version` by 1, and because any number of resyncs may legitimately succeed in sequence, that stale-version rejection is the only signal that the caller's view of the pinned spec is out of date.

A build may be abandoned before dyno. A `RemanPlanner` may cancel while the order is `QUEUED`, `PART_HOLD`, `ASSEMBLY`, or `CALIBRATION`; at any later stage the request is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling from `ASSEMBLY` releases every reserved line, decrementing each part's `qty_reserved`, and fires the promotion scan. Cancelling from `CALIBRATION` does the same release and scan, and additionally supersedes the calibration if it is still `DRAFT`. Cancelling from `QUEUED` releases any reservations that exist (normally none) and fires the scan; cancelling from `PART_HOLD` — where nothing was ever reserved — releases nothing but likewise fires the scan. `CANCELLED` is terminal, as are `SHIPPED` and `ENGINEERING_REVIEW`.

### 3.4. Dyno Testing, Scoring, and the Rework Cycle

Dyno capacity is scheduled explicitly. A `RemanTechnician` books a cell window for an order that must already sit in `DYNO_QUEUE` (`ERR_ORDER_NOT_IN_DYNO_QUEUE`), supplying `dyno_cell_code`, `start_utc`, and `end_utc`. The end must be strictly after the start and strictly after the current logical time, failing with `ERR_INVALID_REQUEST` and `ERR_BOOKING_IN_PAST` respectively. A window occupies the half-open interval that includes `start_utc` and excludes `end_utc`, so back-to-back windows on the same cell are permitted, but any true overlap with an existing window on the same cell is rejected with `ERR_DYNO_CELL_OVERLAP`. A booking is created in `BOOKED` status and is immutable — it never transitions. The booking collection accepts optional `reman_order_id` and `dyno_cell_code` filters.

A `DynoOperator` records a test run with a payload of `reman_order_id` and `gear_pressures_kpa`, the measured mainline pressures aligned ascending by gear against the order's pinned `dyno_targets`, with matching array length required (`ERR_INVALID_REQUEST`). The order must be in `DYNO_QUEUE` (`ERR_ORDER_NOT_IN_DYNO_QUEUE`), and a `BOOKED` booking for the order must cover the current logical time — its `start_utc` at or before now and its `end_utc` after now — otherwise `ERR_NO_ACTIVE_DYNO_BOOKING`. The order's `dyno_attempts_used` must still be below the budget of 3 attempts, otherwise `ERR_DYNO_ATTEMPT_EXHAUSTED`. On acceptance the server resolves the covering booking into `dyno_booking_id` — the earliest-created covering booking, if several cover the current instant — sets `attempt_number` to the count of prior runs for the order plus one, increments `dyno_attempts_used` by 1, and stores the run's score in `last_shift_quality_score`, which stays null before the first run. The run collection accepts optional `reman_order_id` and `dyno_booking_id` filters.

Shift quality is scored against the pinned targets, never the live model. For each gear in ascending order, the per-gear penalty is the absolute difference between the measured pressure and that gear's `target_pressure_kpa`, multiplied by 2.0, with the penalty itself rounded half-up to two decimal places. The `shift_quality_score` is then 100 minus the sum of those already-rounded penalties, rounded half-up to two decimal places, and never allowed to fall below zero. The rounding order is pinned: each per-gear penalty is rounded before the summation, and summing raw penalties before rounding is forbidden because it yields different cents. The `verdict` bands are `PASS` for a score of at least 90.00, `MARGINAL` for at least 80.00 but below 90.00, and `FAIL` below 80.00.

Verdicts drive the build. `PASS` moves the order `DYNO_QUEUE` → `DYNO_PASSED`. `MARGINAL` leaves the order in `DYNO_QUEUE` with `cal_status` still `VERIFIED`, free to book another run while attempts remain. A `FAIL` with attempts remaining — the run's `attempt_number` below 3 — sends the order to `REWORK` and supersedes the calibration (`VERIFIED` → `SUPERSEDED`), forcing a fresh draft and a fresh verification; the kit reservations are kept through rework. A `FAIL` on the third attempt — `attempt_number` exactly 3 — is terminal for the build: the order moves to `ENGINEERING_REVIEW`, the verified calibration is likewise superseded, every reserved line is released back with `qty_reserved` decremented per line and `reserved_parts` emptied, and the resulting availability increase fires the promotion scan, so the oldest resolvable `PART_HOLD` orders auto-promote to `ASSEMBLY` with fresh reservations.

### 3.5. Shipping and the Core Deposit Invoice

Shipping is the point of no return, and only a `RemanPlanner` may do it, only from `DYNO_PASSED` (`ERR_ORDER_NOT_SHIPPABLE`). The ship cascade stamps `shipped_at` from the logical clock, consumes the kit reservations line by line — each reserved part's `qty_reserved` and `qty_on_hand` both decrease by the reserved quantity — and opens the core deposit invoice in a single atomic act.

The new invoice carries the order's `reman_order_id` and `buyer_ref`, a `deposit_cents` copied from the pinned spec's `core_deposit_cents` (never from the live model record), an `issued_at` at ship time, and an initial status of `OPEN`. Because a core takes time to come back, the invoice opens with a provisional estimate: `provisional_credit_cents` is 80% of the deposit, rounded half-up to whole cents, on the assumption of a complete, grade-`A`-equivalent return and with no inspection input. That estimate is superseded by `final_credit_cents` at grading; both `final_credit_cents` and `forfeited_cents` stay null until the first settlement. `SHIPPED` is terminal for the order. The invoice collection accepts optional `reman_order_id` and `status` filters.

### 3.6. Core Intake, Inspection, and Graded Settlement

Cores come back through the receiving dock. A `CoreIntakeClerk` registers a returned core against an invoice that must still be `OPEN`, failing with `ERR_INVOICE_NOT_OPEN` otherwise; because registration atomically flips the invoice `OPEN` → `AWAITING_GRADE`, an `OPEN` invoice also guarantees no other core references it — at most one core ever attaches to one invoice. Registration names the `core_deposit_invoice_id`, a `dock_code`, and a dock appointment from `dock_start_utc` to `dock_end_utc` with the end strictly after the start (`ERR_INVALID_REQUEST`). Dock appointments occupy closed intervals, and each appointment carries a 30-minute turnaround buffer appended after its end, so an existing appointment's buffer-padded occupancy is the closed interval from its `dock_start_utc` through its `dock_end_utc` plus 30 minutes, inclusive of that final instant; a new appointment whose closed interval shares any instant with an existing appointment's buffer-padded occupancy on the same dock is rejected with `ERR_DOCK_OVERLAP` — touching at a single instant already counts as a conflict, so a new appointment starting at exactly an existing appointment's `dock_end_utc` plus 30 minutes is rejected. The new core starts in `RECEIVED` status with `case_cracked`, `deduction_score`, and `grade` null and `findings` empty, `received_at` reads the logical clock, and `days_late` is computed as the whole days between the invoice's `issued_at` and `received_at` — the elapsed seconds divided by 86400 and rounded down. The core collection accepts optional `core_deposit_invoice_id` and `status` filters.

A `CoreInspector` then grades the core, permitted while it is `RECEIVED` or in `RE_INSPECTION` (`ERR_CORE_NOT_INSPECTABLE` otherwise). Inspection records `case_cracked` and a `findings` list whose entries are drawn from `TORQUE_CONVERTER_MISSING`, `VALVE_BODY_MISSING`, `SENSOR_HARNESS_MISSING`, `BELL_HOUSING_DAMAGED`, and `PAN_MISSING`. The `deduction_score` sums the finding weights: a missing torque converter costs 20 points, a missing valve body 25, a missing sensor harness 10, a damaged bell housing 15, and a missing pan 5. The `grade` — null until the first inspection — is forced to `REJECTED` whenever the case is cracked; otherwise a `deduction_score` of at most 5 earns grade `A`, at most 15 earns `B`, at most 30 earns `C`, and anything higher is `REJECTED`.

Lateness discounts the credit independently of condition. A core received at most 30 days after the invoice was issued earns the full late factor of 1.0; from 31 through 45 days the factor drops to 0.75; beyond 45 days the credit is forfeited outright. Settlement then branches. When the grade is `REJECTED` or the core arrived more than 45 days late, the outcome is harsh: `final_credit_cents` becomes 0, `forfeited_cents` becomes the full `deposit_cents`, the invoice moves `AWAITING_GRADE` → `FORFEITED`, and the core's status records `REJECTED`. Otherwise the final credit is the deposit multiplied by the grade multiplier — 1.0 for `A`, 0.75 for `B`, 0.5 for `C` — and then by the late factor, rounded half-up to whole cents; `forfeited_cents` is the deposit minus that credit; the invoice settles `AWAITING_GRADE` → `SETTLED_FULL` when the credit exactly equals the deposit and `AWAITING_GRADE` → `SETTLED_PARTIAL` when it falls short; and the core's status records `GRADED`. Whenever an invoice reaches `SETTLED_FULL`, the linked order's `core_settlement_status` flips from `PENDING` to `CLOSED`, completing the deposit lifecycle for that build.

### 3.7. Disputes, Re-Inspection, and Adjusted Settlement

A buyer who disagrees with a partial settlement or an outright forfeiture can have a `CoreIntakeClerk` dispute the invoice. Disputing is allowed only from `SETTLED_PARTIAL` or `FORFEITED` (`ERR_INVOICE_NOT_DISPUTABLE`) and moves the invoice to `DISPUTED`.

Resolution is a `ProgramAdmin` act requiring `DISPUTED` status (`ERR_INVOICE_NOT_DISPUTED`) and an `action`. Choosing `REINSPECT` reopens grading: the invoice returns to `AWAITING_GRADE` and the linked core — whether `GRADED` or `REJECTED` — moves to `RE_INSPECTION`, from which the next inspection re-runs the full grading and settlement cascade of §3.6 and overwrites the prior `final_credit_cents` and `forfeited_cents`. Choosing `ADJUST` settles immediately at a supplied `adjusted_credit_cents`, which must lie between 0 and `deposit_cents` inclusive (`ERR_ADJUSTMENT_OUT_OF_RANGE`): `final_credit_cents` takes the adjusted value, `forfeited_cents` becomes the deposit minus it, the invoice lands in `SETTLED_ADJUSTED`, and the linked order's `core_settlement_status` flips from `PENDING` to `CLOSED`. `SETTLED_FULL` and `SETTLED_ADJUSTED` are the invoice's terminal states; `FORFEITED` and `SETTLED_PARTIAL` remain disputable, and `DISPUTED` always resolves through one of these two actions.

### 3.8. Warranty Claims, Labor Allowances, and Defective Returns

An `Installer` files a warranty claim against an order that must already be `SHIPPED` (`ERR_ORDER_NOT_SHIPPED`), supplying the `reman_order_id`, a `failure_code` of `CONVERTER_FAILURE`, `GEAR_CLUNK`, `PRESSURE_LEAK`, or `ELECTRICAL_TCM`, the `claimed_labor_hours` actually spent, the `installer_labor_rate_cents` hourly rate — both labor inputs must be positive — and an `allowance_policy` of `BOOK_HOURS` or `ACTUAL_HOURS`. Filing must occur no later than the order's pinned `warranty_days` (per §2.10, never the live model's) after the order's `shipped_at`; a later filing is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`. The claim records the filer's `X-User-ID` as `installer_id` and opens with `claim_status` `SUBMITTED`, `return_status` `NONE`, `deny_reason` null, `labor_allowance_cents` null until approval, and `salvaged_parts` empty. The claim collection accepts optional `reman_order_id` and `claim_status` filters.

Adjudication belongs to the `WarrantyAdjuster`. Approval requires `SUBMITTED` (`ERR_CLAIM_NOT_REVIEWABLE`) and computes the labor allowance from the order's pinned spec. Under `BOOK_HOURS`, the payable hours are the pinned `flat_rate_hours` in full, regardless of what the installer claimed; under `ACTUAL_HOURS`, the payable hours are the lesser of `claimed_labor_hours` and the pinned `flat_rate_hours`, so identical inputs pay less whenever the claim comes in under the guide. The raw allowance is those payable hours multiplied by `installer_labor_rate_cents`, rounded half-up to whole cents, and `labor_allowance_cents` is the lesser of that raw allowance and the pinned `labor_cap_cents` — an uncapped allowance exactly equal to the cap pays the cap value. The routing selector then computes `routing_type` top to bottom with the first matching rule winning: an `ELECTRICAL_TCM` failure routes `RETURN_TO_DISTRIBUTOR`; otherwise a `labor_allowance_cents` of at least 50000 cents routes `RETURN_TO_PLANT`; anything else routes `LOCAL_SCRAP`. `return_required` is true unless the routing is `LOCAL_SCRAP`, and when a return is required the claim's `return_status` opens `NONE` → `ISSUED`. Denial is likewise only from `SUBMITTED` (`ERR_CLAIM_NOT_REVIEWABLE`); the `reason` field is optional, a supplied `reason` is recorded in `deny_reason` (which otherwise stays null), and the claim ends at `DENIED`.

The return leg evolves as its own dimension, independent of adjudication once the claim is approved. The filing installer — and only that installer, with `X-User-ID` matched against `installer_id` — ships the defective unit back while the claim is `APPROVED` and the return leg is `ISSUED` (`ERR_RETURN_NOT_SHIPPABLE`), moving it to `IN_TRANSIT`; a caller whose `X-User-ID` differs from `installer_id` is rejected with `ERR_INSUFFICIENT_PERMISSIONS`, a check evaluated after the return-ship state gate. A `WarrantyAdjuster` receives and dispositions an `IN_TRANSIT` return (`ERR_RETURN_NOT_RECEIVABLE`), moving it to `DISPOSITIONED`; the `salvaged_parts` field is optional and defaults to an empty list; each supplied line names a `hard_part_id` that must exist (an unknown one is rejected with `ERR_PART_NOT_FOUND`, ahead of the return-state gate) and a positive `qty`, and restocks inventory by adding its `qty` back to that part's `qty_on_hand`; the availability increase fires the `PART_HOLD` promotion scan of §2.9, which runs only when at least one line restocks. Payment requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_PAYABLE`) and, when a return is required, the return leg must already be `DISPOSITIONED` (`ERR_RETURN_NOT_RECEIVED`); a claim routed `LOCAL_SCRAP` needs no return and may be paid directly. Payment lands the claim in `PAID`, which together with `DENIED` forms its terminal states, while `DISPOSITIONED` closes the return leg.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with `201 Created`; endpoints that modify an existing resource or drive a state transition respond with `200 OK`. Request payloads, computed fields, and cascades are as narrated in §3; list endpoints follow the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/transmission-models` | Create a transmission model with its build spec | ProgramAdmin |
| PUT | `/api/transmission-models/{id}` | Update a model's build spec; bumps `spec_version` | ProgramAdmin |
| GET | `/api/transmission-models/{id}` | Get one transmission model | Any |
| POST | `/api/hard-parts` | Create a hard-part inventory record | InventoryPlanner |
| GET | `/api/hard-parts/{id}` | Get one hard part | Any |
| POST | `/api/hard-parts/{id}/stock-adjustments` | Adjust `qty_on_hand` by a signed delta under OCC | InventoryPlanner |
| POST | `/api/interchange-mappings` | Declare that a hard part fits a model at a tier | InventoryPlanner |
| GET | `/api/interchange-mappings` | List interchange mappings with optional filters | Any |
| GET | `/api/interchange-mappings/{id}` | Get one interchange mapping | Any |
| POST | `/api/reman-orders` | Create a reman order; pins the model's current spec | RemanPlanner |
| GET | `/api/reman-orders` | List reman orders with optional filters | Any |
| GET | `/api/reman-orders/{id}` | Get one reman order | Any |
| POST | `/api/reman-orders/{id}/kit-reserve` | Allocate and reserve all spec parts (all-or-nothing) | RemanPlanner |
| POST | `/api/reman-orders/{id}/complete-assembly` | Mark assembly complete | RemanTechnician |
| PUT | `/api/reman-orders/{id}/calibration` | Write or replace the calibration draft | Calibrator |
| POST | `/api/reman-orders/{id}/verify-calibration` | Verify the calibration draft; advance to dyno queue | Calibrator |
| POST | `/api/reman-orders/{id}/resync-spec` | Re-pin the order to the model's current spec under OCC | RemanPlanner |
| POST | `/api/reman-orders/{id}/ship` | Ship a dyno-passed unit; issue the core deposit invoice | RemanPlanner |
| POST | `/api/reman-orders/{id}/cancel` | Cancel an order before dyno | RemanPlanner |
| POST | `/api/dyno-bookings` | Book a dyno cell window for an order in `DYNO_QUEUE` | RemanTechnician |
| GET | `/api/dyno-bookings` | List dyno bookings with optional filters | Any |
| GET | `/api/dyno-bookings/{id}` | Get one dyno booking | Any |
| POST | `/api/dyno-test-runs` | Record a dyno run; compute score and verdict | DynoOperator |
| GET | `/api/dyno-test-runs` | List dyno test runs with optional filters | Any |
| GET | `/api/dyno-test-runs/{id}` | Get one dyno test run | Any |
| POST | `/api/core-units` | Register a returned core against an `OPEN` invoice | CoreIntakeClerk |
| GET | `/api/core-units` | List core units with optional filters | Any |
| GET | `/api/core-units/{id}` | Get one core unit | Any |
| POST | `/api/core-units/{id}/inspect` | Record completeness findings; grade and settle | CoreInspector |
| GET | `/api/core-deposit-invoices` | List core deposit invoices with optional filters | Any |
| GET | `/api/core-deposit-invoices/{id}` | Get one core deposit invoice | Any |
| POST | `/api/core-deposit-invoices/{id}/dispute` | Dispute a partial settlement or forfeiture | CoreIntakeClerk |
| POST | `/api/core-deposit-invoices/{id}/resolve-dispute` | Resolve a dispute via `REINSPECT` or `ADJUST` | ProgramAdmin |
| POST | `/api/warranty-claims` | File an installer warranty claim | Installer |
| GET | `/api/warranty-claims` | List warranty claims with optional filters | Any |
| GET | `/api/warranty-claims/{id}` | Get one warranty claim | Any |
| POST | `/api/warranty-claims/{id}/approve` | Approve a claim; compute allowance and routing | WarrantyAdjuster |
| POST | `/api/warranty-claims/{id}/deny` | Deny a claim with a reason | WarrantyAdjuster |
| POST | `/api/warranty-claims/{id}/pay` | Pay an approved claim | WarrantyAdjuster |
| POST | `/api/warranty-claims/{id}/return-ship` | Installer ships the defective unit back | Installer |
| POST | `/api/warranty-claims/{id}/return-receive` | Receive and disposition the returned unit | WarrantyAdjuster |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_INTERCHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_DYNO_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_CORE_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_NOT_READY_FOR_KIT` | 409 Conflict |
| `ERR_ORDER_NOT_READY_FOR_ASSEMBLY` | 409 Conflict |
| `ERR_ORDER_NOT_READY_FOR_CALIBRATION` | 409 Conflict |
| `ERR_CAL_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_IN_DYNO_QUEUE` | 409 Conflict |
| `ERR_NO_ACTIVE_DYNO_BOOKING` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_RESYNCABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_OPEN` | 409 Conflict |
| `ERR_CORE_NOT_INSPECTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTED` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPED` | 409 Conflict |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_RETURN_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_RETURN_NOT_RECEIVABLE` | 409 Conflict |
| `ERR_RETURN_NOT_RECEIVED` | 409 Conflict |
| `ERR_SOD_VERIFICATION_FORBIDDEN` | 403 Forbidden |
| `ERR_CAL_STALE` | 422 Unprocessable Entity |
| `ERR_BOOKING_IN_PAST` | 422 Unprocessable Entity |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INTERCHANGE` | 409 Conflict |
| `ERR_DYNO_CELL_OVERLAP` | 409 Conflict |
| `ERR_DOCK_OVERLAP` | 409 Conflict |
| `ERR_DYNO_ATTEMPT_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_STOCK` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_OUT_OF_RANGE` | 422 Unprocessable Entity |
