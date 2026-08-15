# Vaccine Inventory & VFC Program Management API — Product Requirements Document

## 1. Introduction

Provider sites enrolled in the federal Vaccines for Children (VFC) program receive publicly funded vaccine stock at no cost and are obligated to administer it only to children who meet strict eligibility criteria, while the same refrigerators often also hold privately purchased inventory intended for commercially insured patients. Every dose of public stock must be accounted for — received, administered, wasted, or transferred — and state program officers and compliance auditors hold the site responsible for reconciling that ledger at any time. Temperature failures, short-dated vials, and emergency stock-outs are facts of clinic life, and the program's answer to each of them (quarantine and disposition, redistribution to higher-volume sites, documented borrowing across stocks with later payback) is itself tightly regulated.

This document specifies an API that serves as the system of record for that entire operating reality. It covers provider site enrollment and sanction, storage unit registration and probe-based temperature surveillance, excursion response and loss reporting, ordering and allocation from the state program, lot-level inventory with expiration tracking, per-visit eligibility screening, dose administration documentation with immunization registry submission, inter-stock borrowing and payback reconciliation, short-dated stock transfers between sites, and the compliance site visit that closes the accountability loop. The design deliberately separates duties across three operator roles — the site-level vaccine manager, the state program officer, and the compliance auditor — so that no single actor can both execute and approve the sensitive transitions. A server-maintained logical clock, rather than wall-clock time, governs every date-sensitive rule in the system so that expiration sweeps and eligibility computations are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across every endpoint and workflow.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or syntactically invalid is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly three roles: `VaccineManager`, the site-level operator who manages storage units, lots, patients, screenings, dose administration, orders, borrow tickets, transfers, and temperature readings; `StateProgramOfficer`, the state VFC program official who approves orders and allocates doses; and `ComplianceAuditor`, the state or federal auditor who manages provider sites and the product catalog, conducts site visit audits, and advances the logical clock. An `X-User-Role` value naming anything other than these three roles is treated as a syntactically invalid header and rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); an attempt to perform an operation outside the caller's recognized role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For each of the three roles — `VaccineManager`, `StateProgramOfficer`, and `ComplianceAuditor` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it for attribution where a workflow creates a record of human action — as `screened_by_user_id` on an eligibility screening, `administered_by_user_id` on a dose administration, `submitted_by_user_id` on a vaccine order, `opened_by_user_id` on a borrow ticket, and `conducted_by_user_id` on a site visit audit — but it never compares the header value against any resource's `id`, and no ownership rule is derived from it.

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

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and a non-integer value or one below 1 or above 100 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter states how many items to skip and defaults to 0; a non-integer or negative `offset` is likewise rejected with `ERR_INVALID_REQUEST`. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, with `has_more` true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order.

### 2.4. Common Resource Properties and Enum Discipline

All resources share a standard set of system-managed properties, with one deliberate exception noted below:

- `id` (string): a server-minted UUID, with no type prefix, uniquely identifying the resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations performed automatically by system-driven cascades such as quarantine, write-off, expiry, suspension, or allocation side effects.

The temperature reading is an append-only event log and is the single exception: a `TemperatureReading` carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, because a probe reading, once recorded, is never modified.

Enum-typed fields accept only their declared value sets; a value outside the declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400). Requests with a missing required field, a type mismatch, or a value outside its permitted range — for example, a dose quantity below 1 — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A request body that is absent, malformed, or not a JSON object is likewise rejected with `ERR_INVALID_REQUEST`.

### 2.5. Segregation of Public and Private Stock

The program's foundational invariant is the physical and logical segregation of publicly funded and privately purchased vaccine. Every lot in the system carries a `stock_type` of exactly `PUBLIC_VFC` or `PRIVATE`, and the two stocks are never mixed within a single lot row. Public stock enters the system through one door only: the posting of an allocation receipt against an approved state order, which creates the lot and stamps it with `received_via_order_id` pointing back at that order. Manual lot registration accepts private stock only; an attempt to register a `PUBLIC_VFC` lot directly is rejected with `ERR_INVALID_REQUEST`. Eligibility screening (§3.6) determines which stock a given patient visit may draw from, and the borrowing mechanism (§3.7) is the sole sanctioned bridge between the two stocks when one runs short.

### 2.6. Cold Chain Integrity: Monitoring, Quarantine, and Excursions

Each storage unit declares an acceptable Celsius range through `min_temp_c` and `max_temp_c`, and both bounds are inclusive: a reading exactly at either bound is in range. A recorded reading is flagged `is_out_of_range` when it falls below `min_temp_c` or rises above `max_temp_c`. While a unit has an excursion in the `OPEN` or `UNDER_REVIEW` state, the unit's `active_excursion_id` is non-null and its computed `is_quarantined` flag is true. Quarantine is a hard block: no new dose administration may draw from lots stored in a quarantined unit, no allocation receipt may be posted into it, and no short-date transfer may be received into it — each such attempt is rejected with `ERR_STORAGE_UNIT_QUARANTINED` (HTTP 409). The owning site's `excursion_count_open` reflects, at all times, the number of excursions in `OPEN` or `UNDER_REVIEW` across all of that site's storage units.

### 2.7. The Accountability Ledger and the Private Lending Balance

Two continuously maintained balances sit on every provider site and anchor the program's compliance posture.

The first is `accountability_balance_doses`, the running public-stock ledger: doses received into `PUBLIC_VFC` lots, minus doses administered from `PUBLIC_VFC` lots, minus doses reported wasted from `PUBLIC_VFC` lots, minus doses transferred out from `PUBLIC_VFC` lots. The ledger is recomputed incrementally on every event that touches any of its terms — allocation receipt, public-funded administration, excursion write-off or expiry of public stock, and the initiation, shipment, or cancellation of a public-stock transfer. This running, provisional view counts transfers that have been initiated but not yet shipped, and it counts nothing from excursions that are still open, since no write-off exists yet. The frozen audit snapshot described in §3.9 uses stricter end-of-day semantics: only transfers physically off the shelf count, and still-open excursions contribute zero to wastage. A negative `accountability_balance_doses` signals an accountability gap — public doses consumed beyond what receipts justify — and blocks audit closure.

The second balance is `private_lending_balance`: the sum, across all `OPEN` and `PARTIALLY_REPAID` borrow tickets at the site whose `direction` is `PUBLIC_FROM_PRIVATE`, of each ticket's `borrowed_quantity` minus its `paid_back_quantity`. A positive value means the site owes private stock a payback for VFC-eligible doses that were administered from the private shelf. For regulatory reporting, a gross lending view reports the outstanding balances of both directions separately rather than netting them.

Both balances are integer dose counts; no rounding applies.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of a parent entity before mutating under it, and each names its expectation explicitly in the request body.

Approval of a vaccine order requires the field `expected_provider_site_version`, carrying the `version` of the provider site as the approver last read it. If the site's current `version` has advanced since that read — because a prior approval, a receipt posting, a suspension, or an excursion cascade legitimately moved it forward — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), since the approver's view of the site's compliance posture is stale.

Recording a payback against a borrow ticket requires the field `expected_borrow_ticket_version`, carrying the ticket's `version` as the caller last observed it. If the ticket's current `version` differs — for example because another partial payback was posted after the caller's read, advancing the version and changing `paid_back_quantity` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; these two are the complete set of OCC-guarded writes.

### 2.9. Nested Resource Retrieval and Filtered Listings

Requests that target nested resources are validated strictly left to right along the path. Each identifier in the path is resolved in turn, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — for example, a request addressed to `/provider-sites/{id}/vaccine-orders/{orderId}` fails on the site before the order is ever examined when the site does not exist. The path template variables used throughout the API are `{id}` for the primary resource of a collection and, for nested action endpoints, `{orderId}` for vaccine orders, `{excursionId}` for temperature excursions, `{ticketId}` for borrow tickets, `{transferId}` for short-date transfers, `{auditId}` for site visit audits, and `{doseId}` for dose administrations. The same existence discipline applies to every id referenced in a request body: provider site, storage unit, lot, patient, screening, order, order line, receipt, borrow ticket, transfer, excursion, audit, and dose identifiers must all resolve to existing resources.

Alongside the nested collections, the API exposes top-level filtered list endpoints so that resources remain reachable by their foreign keys without knowing their parents — storage units filterable by `provider_site_id` or `active_excursion_id`; lots by `provider_site_id`, `storage_unit_id`, `vaccine_product_id`, `received_via_order_id`, `stock_type`, or `status`; readings and excursions by `storage_unit_id`; patients by `provider_site_id` or `is_active`; screenings by `patient_id` or `screening_date`; dose records by `provider_site_id`, `patient_id`, `eligibility_screening_id`, `lot_id`, `borrowed_context_ticket_id`, `funding_source`, or `registry_status`; orders by `provider_site_id` or `status`; order lines by `vaccine_order_id` or `vaccine_product_id`; receipts by `vaccine_order_id`, `order_line_id`, `storage_unit_id`, or `lot_id`; borrow tickets by `provider_site_id`, `from_lot_id`, `to_lot_id`, `status`, or `direction`; audits by `provider_site_id` or `status`; and transfers by `provider_site_id`, `from_lot_id`, `destination_site_id`, `destination_storage_unit_id`, `new_lot_id`, or `status`. Boolean-valued filters (`vfc_program_eligible`, `is_active`) accept the strings `true` and `false` case-insensitively; any other value leaves that filter unapplied.

### 2.10. The Logical Clock and Date Semantics

The server maintains a logical clock that governs every date- and time-sensitive rule in the system. At boot, the logical clock reads exactly 2026-08-01T00:00:00Z, and before any clock-setting call it must return precisely this default — it must never fall back to real wall-clock time. A `ComplianceAuditor` may advance the logical clock to an arbitrary ISO-8601 UTC instant by supplying `to_iso8601`; the response reports the new `current_utc`.

Each advance of the clock triggers an expiration sweep: every lot still `AVAILABLE` whose manufacturer expiration date now lies strictly in the past — the current calendar date is later than the lot's `expires_on` — and whose `quantity_on_hand` is still above zero transitions to `EXPIRED`, its `quantity_on_hand` is set to zero, and for every `PUBLIC_VFC` lot swept this way the owning site's `accountability_balance_doses` is recomputed on the wasted side of the ledger.

Calendar date fields throughout the API — `date_of_birth`, `screening_date`, `administration_date`, `visit_date`, `expires_on` — use the ISO-8601 `YYYY-MM-DD` form. Administration from a lot is permitted while the administration date is on or before the lot's `expires_on`; it is forbidden once that date has passed.

### 2.11. Numeric Precision and Rounding

Temperature readings and bounds are Celsius values carried to one decimal place. The server accepts any JSON number for these fields and stores it unchanged; the one-decimal convention is a data-entry convention, not a validation or rounding rule. All dose counts — on-hand quantities, requested, approved, and received amounts, borrowed and paid-back quantities, write-offs, and both site balances — are integers with no rounding. The audit's wastage rate (§3.9) is reported rounded to four decimal places using the round-half-up method, but the comparisons that assign the rate to its tier are always performed against the unrounded rate.

### 2.12. Request Validation Order

When several checks could reject the same request, the server applies them in a fixed global order so that the error a caller receives is deterministic. First, the user-context headers are verified (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the declared role is checked against the endpoint's permissions (`ERR_INSUFFICIENT_PERMISSIONS`). Third, every identifier referenced by the path and body is resolved (`ERR_NOT_FOUND`); request-body field validation (missing, mistyped, or out-of-range fields drawing `ERR_INVALID_REQUEST` or `ERR_INVALID_ENUM`) runs as the body is parsed — after the path identifiers are resolved and before the identifiers referenced inside the body are resolved — except where §3 states a different order for a specific endpoint. Fourth, where §2.8 applies, the expected-version field is compared against the parent's current `version` (`ERR_STALE_VERSION`). Fifth, the target resource's current state is checked against the requested transition (`ERR_INVALID_STATE`). Only then do the endpoint-specific business and safety rules run, in the relative orders stated throughout §3 — quarantine and lot-availability safety checks ahead of eligibility and referential checks, and fiscal checks such as allocation consistency last.

## 3. Business Logic & Workflows

### 3.1. Enrolling and Managing Provider Sites

A `ComplianceAuditor` enrolls a new provider site by supplying a `site_name` and the state-issued `vfc_pin`, a provider identification number that is unique across all sites. That uniqueness is a data expectation rather than a server-enforced rule: enrollment accepts a duplicate `vfc_pin` without error. The new site's `status` begins as `ACTIVE`, and its three computed counters — `excursion_count_open`, `accountability_balance_doses`, and `private_lending_balance` — all begin at zero.

When an auditor finds ordering abuse, suspension moves the site from `ACTIVE` to `SUSPENDED_ORDERING`; attempting the transition from any other state is rejected with `ERR_INVALID_STATE`. While suspended, the site cannot submit vaccine orders — submission is refused with `ERR_SITE_SUSPENDED_ORDERING` — although its other operations continue. Reinstatement returns a `SUSPENDED_ORDERING` site to `ACTIVE`, and again any other source state draws `ERR_INVALID_STATE`. Both transitions are site mutations and increment the site's `version` by one.

Termination is the heaviest transition in the site lifecycle and may be invoked from either `ACTIVE` or `SUSPENDED_ORDERING`. It is blocked while any of the site's storage units has an excursion in `OPEN` or `UNDER_REVIEW` (`ERR_OPEN_EXCURSION_EXISTS`), while any borrow ticket at the site is `OPEN` or `PARTIALLY_REPAID` (`ERR_OPEN_BORROW_TICKET_EXISTS`), and while any site visit audit is `SCHEDULED` or `IN_PROGRESS` (`ERR_OPEN_AUDIT_EXISTS`) — in that order of evaluation. A successful termination moves the site to `TERMINATED` and cascades to its inventory: every lot still `AVAILABLE` at the site transitions to `WASTED_CLOSED` and its `quantity_on_hand` is set to zero. Termination also increments the site's `version` by one.

### 3.2. Storage Units and the Vaccine Product Catalog

With a site enrolled, a `VaccineManager` registers its cold-storage hardware. Each unit is created with an operator-facing `unit_label` (for example, "Fridge-1"), a `unit_kind` of `REFRIGERATOR` or `FREEZER`, and the acceptable range bounds `min_temp_c` and `max_temp_c` — a typical refrigerator runs 2.0 to 8.0 degrees Celsius, inclusive. The server does not validate the ordering of the two bounds; any two numbers are accepted. The unit is anchored to its owning site through `provider_site_id`, recorded by the system at creation.

The product catalog is maintained by a `ComplianceAuditor`. Registering a product requires its `ndc_code` — the National Drug Code, expected unique across the catalog, though the server does not reject a duplicate — along with a `display_name`, a `presentation` of `SINGLE_DOSE_VIAL`, `MULTI_DOSE_VIAL`, or `PRE_FILLED_SYRINGE`, the `doses_per_container` yielded by one container (at least 1), a `vfc_program_eligible` flag marking whether the state program funds the product for eligible children, and a `storage_requirement` of `REFRIGERATED_2_8C`, `FROZEN_MINUS_50_MINUS_15C`, or `ULTRA_COLD_MINUS_90_MINUS_60C`. The catalog listing may be filtered by `vfc_program_eligible` so managers can plan public and private ordering separately.

### 3.3. Temperature Surveillance and Excursion Disposition

A `VaccineManager` records each probe reading against a storage unit with the `recorded_at` timestamp — the ISO-8601 UTC instant the probe sampled — and `temperature_c` to one decimal place. The server immediately classifies the reading against the unit's bounds and stores the verdict in `is_out_of_range`. What happens next depends on the reading and on whether the unit already has an active excursion.

When an out-of-range reading arrives and the unit has no active excursion, the system opens one: a new excursion is created in `OPEN` status with `opened_at` set to the reading's `recorded_at` and `peak_temperature_c` initialized to the reading's `temperature_c`; the unit's `active_excursion_id` is set and `is_quarantined` becomes true; every `AVAILABLE` lot stored in the unit transitions automatically to `QUARANTINED`; and the site's `excursion_count_open` increases by one. When a further out-of-range reading arrives while an excursion is active, the excursion's peak is reconsidered: the reading's candidate deviation is how far it exceeds its violated bound — the reading minus `max_temp_c` when it is above the range, or `min_temp_c` minus the reading when it is below — and the existing deviation is derived from the current `peak_temperature_c` against whichever bound it violated. The incoming reading replaces `peak_temperature_c` only when its candidate deviation is strictly greater than the existing deviation; readings in range are never candidates. When an in-range reading arrives while an excursion is active, the excursion closes: `closed_at` is set to the reading's `recorded_at`, and `duration_minutes` is computed as the whole minutes elapsed between `opened_at` and `closed_at`, any partial minute discarded. Should further in-range readings arrive while the excursion remains active (including after it has moved to `UNDER_REVIEW`), each one re-sets `closed_at` to its own `recorded_at` and recomputes `duration_minutes` from the same `opened_at`. While an excursion remains open, `closed_at` is null and `duration_minutes` reads zero.

Disposition is human. A `VaccineManager` begins review of an excursion, moving it from `OPEN` to `UNDER_REVIEW`; this is rejected with `ERR_INVALID_STATE` when the excursion is not `OPEN`, and with `ERR_EXCURSION_STILL_OPEN` when no in-range reading has yet closed it, since a still-open excursion cannot meaningfully be reviewed. From `UNDER_REVIEW` there are exactly two exits. Resolving as viable — with free-text `resolution_notes`, which are optional and stored as null when omitted — moves the excursion to `RESOLVED_VIABLE`, returns every `QUARANTINED` lot in the unit to `AVAILABLE`, clears the unit's `active_excursion_id` and drops `is_quarantined` to false, and decrements the site's `excursion_count_open` by one. Resolving as wasted — again with optional `resolution_notes` — moves the excursion to `RESOLVED_WASTED` and writes the inventory off: every `QUARANTINED` lot in the unit transitions to `WASTED_CLOSED`, the sum of their pre-write-off `quantity_on_hand` values is recorded as the excursion's `doses_written_off`, and each of those lots is zeroed; the unit is cleared of quarantine exactly as in the viable path; the open-excursion count decreases by one; and for each `PUBLIC_VFC` lot written off, the site's `accountability_balance_doses` is recomputed on the wasted side of the ledger.

### 3.4. Lot Registration, Storage, and Expiration

Private stock enters inventory through manual registration by a `VaccineManager`, whose payload names the `storage_unit_id` that physically holds the vials, the `vaccine_product_id`, the manufacturer `lot_number`, the `stock_type`, the initial `quantity_on_hand` (which may be zero), and the printed `expires_on` date. Two constraints guard the door: the storage unit must belong to the same provider site the lot is registered under, or the request fails with `ERR_UNIT_SITE_MISMATCH`; and manual registration accepts only `PRIVATE` stock — a manual `PUBLIC_VFC` registration is rejected with `ERR_INVALID_REQUEST`, because public lots arise exclusively from allocation receipts (§3.5). The `lot_number` is unique per pairing of product and stock type, so the same physical lot can legitimately appear once in each stock; the server does not enforce this pairing uniqueness at registration and accepts a duplicate `lot_number` without error. Newly registered lots begin `AVAILABLE` with `quantity_borrowed_in` at zero.

A lot's `status` walks a small machine with three terminal states. From `AVAILABLE`, a lot is pulled to `QUARANTINED` automatically whenever its unit opens an excursion, and it returns to `AVAILABLE` only if that excursion resolves viable. When `quantity_on_hand` reaches zero through administration, transfer shipment, or payback outflow, the lot transitions to `DEPLETED`. When the logical clock's expiration sweep (§2.10) finds an `AVAILABLE` lot past its `expires_on` with doses remaining, the lot becomes `EXPIRED` and its on-hand is zeroed — a public-lot expiry also recomputing the site's accountability ledger. Finally, site termination cascades every remaining `AVAILABLE` lot to `WASTED_CLOSED` with its quantity zeroed.

Any operation that draws doses from a lot — dose administration, transfer shipment, opening a borrow from it, or using it as the source of a payback — requires the lot to be `AVAILABLE`. A lot that is `QUARANTINED`, `EXPIRED`, `DEPLETED`, or `WASTED_CLOSED` rejects such draws with `ERR_LOT_NOT_AVAILABLE` (HTTP 409), and a lot whose `quantity_on_hand` is smaller than the requested draw rejects them with `ERR_INSUFFICIENT_STOCK` (HTTP 422).

### 3.5. Ordering from the State Program and Receiving Allocations

Restocking public inventory begins when a `VaccineManager` drafts an order for the site, declaring the `expected_vfc_doses` being requested — at least one dose. The server mints an `order_number` unique within the site — the literal prefix `ORD-` followed by a zero-padded six-digit per-site sequence beginning at `ORD-000001` — records the operator as `submitted_by_user_id`, and opens the order in `DRAFT` status with `approved_vfc_doses` and `received_vfc_doses` both at zero. While the order is in `DRAFT`, the manager adds lines to it — an attempt against an order in any other state is rejected with `ERR_INVALID_STATE`, a check that runs before the line's fields and `vaccine_product_id` are examined — each naming a `vaccine_product_id` and the `requested_doses` sought for that product — again at least one. Every line is anchored to its order through `vaccine_order_id` and tracks two further counters: `approved_doses`, set at approval time and initially null, and `received_doses`, the cumulative receipts against the line, initially zero.

Submission moves the order from `DRAFT` to `SUBMITTED` and enforces three checks in order: the order must currently be `DRAFT` (`ERR_INVALID_STATE` otherwise), at least one line must exist (`ERR_EMPTY_ORDER`), and the site must be `ACTIVE` rather than `SUSPENDED_ORDERING` (`ERR_SITE_SUSPENDED_ORDERING`). A `VaccineManager` may also cancel an order while it is in `DRAFT` or `SUBMITTED`, moving it to `CANCELLED`; any other source state draws `ERR_INVALID_STATE`.

Approval belongs to the `StateProgramOfficer` alone and is one of the two OCC-guarded writes in the system. The request carries `approved_vfc_doses` — the state's allocation, any non-negative integer (zero included), which may be smaller than the requested total — together with `expected_provider_site_version` and an optional `line_allocations` breakdown. The breakdown may be given either as an object mapping order-line ids to approved doses or as a list of `{"order_line_id", "approved_doses"}` entries; each allocated value must be a non-negative integer (`ERR_INVALID_REQUEST` otherwise), and entries naming lines that do not belong to the order are ignored. The checks run in a fixed order: first the expected site version is compared against the site's current `version`, rejecting a stale view with `ERR_STALE_VERSION`; then the order's state must be `SUBMITTED` (`ERR_INVALID_STATE`); then every line must carry an `approved_doses` value — when `line_allocations` is omitted the server distributes the approved total across the lines proportionally to their `requested_doses`, walking the lines in creation order so that every line but the last receives `⌊approved_vfc_doses × requested_doses ÷ total requested⌋` and the last-created line receives the remaining doses, but either way a line left without an allocation rejects the approval with `ERR_LINE_ALLOCATION_MISSING`; and finally the sum of the per-line `approved_doses` must equal the order-level `approved_vfc_doses` exactly, rejecting mismatches with `ERR_ALLOCATION_MISMATCH`. A successful approval moves the order to `APPROVED` and increments the site's `version` by one.

Shipments against an approved order are posted by a `VaccineManager` as allocation receipts, each naming the `order_line_id` it satisfies, the `storage_unit_id` that will hold the new stock, the `lot_number` and `expires_on` printed on the vials, and the `quantity_doses` in the shipment — at least one. Receipts are accepted only while the order is `APPROVED` or `PARTIALLY_RECEIVED`; posting against an order in any other state is rejected with `ERR_INVALID_STATE`. The destination unit must not be quarantined (`ERR_STORAGE_UNIT_QUARANTINED`, checked first per §2.12) and must belong to the order's site (`ERR_UNIT_SITE_MISMATCH`). Posting a receipt creates the physical stock: a new lot with `stock_type` `PUBLIC_VFC`, `quantity_on_hand` equal to `quantity_doses`, status `AVAILABLE`, and `received_via_order_id` pointing at the order; the receipt's own `lot_id` is set to the created lot. The line's `received_doses` then grows by the receipt quantity, and it may never exceed the line's `approved_doses` — an over-shipment is rejected with `ERR_OVER_RECEIPT`. The order's `received_vfc_doses` is always the sum of its lines' `received_doses`; the first receipt that lifts that sum above zero (while it remains below the approved total) moves the order automatically from `APPROVED` to `PARTIALLY_RECEIVED`, and the moment the running total equals `approved_vfc_doses` the order becomes `FULLY_RECEIVED` — including the case where a single receipt covers the entire allocation in one posting. Every posted receipt also recomputes the site's `accountability_balance_doses` on the received side of the ledger.

### 3.6. Patients, Eligibility Screening, and Dose Administration

A `VaccineManager` registers each pediatric patient at the site with a `full_name`, a `date_of_birth`, and an `insurance_category` drawn from `MEDICAID`, `UNINSURED`, `UNDERINSURED`, `AMERICAN_INDIAN_ALASKA_NATIVE`, or `COMMERCIAL`. The first four categories are VFC-eligible; `COMMERCIAL` is not. The patient's `is_active` flag defaults to true when omitted from the registration payload — the payload may set it false at creation — and is set false when the patient is inactivated, for example after moving away.

Every visit that may end in a vaccination begins with an eligibility screening. The manager records the `screening_date` and the `insurance_category_at_visit` — the category verified at this visit, captured on the screening so that a later change to the patient record cannot rewrite history — while the server stamps `screened_by_user_id` from the acting header. The screening's `vfc_eligible` is then computed from two conjuncts: the patient's age on the screening date, taken as the number of days between `date_of_birth` and `screening_date` divided by 365.25 and rounded down to whole years, is less than nineteen; and the `insurance_category_at_visit` is one of the four VFC-eligible categories. The derived `outcome` reads `VFC_ELIGIBLE` when both conjuncts hold and `PRIVATE_ONLY` otherwise.

Recording an administered dose is the most heavily guarded write in the system. The payload names the `patient_id`, the `eligibility_screening_id` supporting this visit, the `lot_id` the dose was drawn from, and the `administration_date`, and it may carry a `borrowed_context_ticket_id` when borrowing covered the dose. The checks run in this order. First, the storage unit holding the lot must not be quarantined (`ERR_STORAGE_UNIT_QUARANTINED`). Second, the lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`). Third, the `administration_date` must be on or before the lot's `expires_on` (`ERR_LOT_EXPIRED`). Fourth, the lot's `stock_type` must agree with the screening `outcome`: a `VFC_ELIGIBLE` outcome requires a `PUBLIC_VFC` lot and a `PRIVATE_ONLY` outcome requires a `PRIVATE` lot, and a mismatch is rejected with `ERR_STOCK_ELIGIBILITY_MISMATCH` unless an `OPEN` borrow ticket covers the dose and `borrowed_context_ticket_id` is set to reference it — a ticket covers the dose when it is `OPEN` and names the dose's lot as its `from_lot_id` or `to_lot_id`. Fifth, the screening must belong to the same patient as the dose and its `screening_date` must equal the `administration_date` (`ERR_SCREENING_MISMATCH`). Sixth, when the dose draws from a `PUBLIC_VFC` lot, the patient must be active and still under nineteen years of age on the `administration_date` (`ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE`). Finally, the lot must hold at least one dose (`ERR_INSUFFICIENT_STOCK`).

A recorded administration takes immediate effect: the lot's `quantity_on_hand` decreases by one; `funding_source` is derived from the lot's `stock_type` — `PUBLIC_VFC` stock yields a `PUBLIC_VFC` funding source and `PRIVATE` stock yields `PRIVATE`; `registry_status` opens at `PENDING_SUBMISSION`; the operator is recorded as `administered_by_user_id`; the site's accountability ledger is recomputed; and a lot whose on-hand reaches zero transitions to `DEPLETED`.

Registry submission is its own small lifecycle. A dose awaiting submission may be marked `SUBMITTED` once the state immunization registry accepts the filing, or marked `REJECTED_BY_REGISTRY` when the registry bounces it; both transitions require the dose to currently be `PENDING_SUBMISSION`, drawing `ERR_INVALID_STATE` otherwise. A rejected dose is not terminal: resetting it returns the record from `REJECTED_BY_REGISTRY` to `PENDING_SUBMISSION` so the clinic can correct and re-file. The dose listing supports filters on `patient_id`, `lot_id`, `funding_source`, `registry_status`, and `administration_date` for daily reconciliation work.

### 3.7. Inter-Stock Borrowing and Payback Reconciliation

Program rules permit borrowing only across the stock divide — never within the same stock. When a `VaccineManager` opens a borrow ticket, the payload names the `from_lot_id` the physical doses were pulled from, the `to_lot_id` whose program conceptually consumed them, the `direction`, the `borrowed_quantity` of at least one dose, and a `reason_code` of `STOCK_OUT`, `SHORT_DATE_AVOIDANCE`, or `EMERGENCY_CLINIC`; the server records `opened_by_user_id`. The `direction` value `PUBLIC_FROM_PRIVATE` means a VFC-eligible dose was administered from private stock, so public stock owes private a payback; `PRIVATE_FROM_PUBLIC` is the mirror image, a private patient dosed from public stock. The two lots must sit on opposite sides of the divide consistently with the declared direction: a same-stock borrow, or a direction inconsistent with the two lots' `stock_type` values, is rejected with `ERR_SAME_STOCK_BORROW`. The lender lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`) and must hold at least `borrowed_quantity` doses (`ERR_INSUFFICIENT_STOCK`).

Opening the ticket moves value but not product between the books: the lender lot's `quantity_on_hand` decreases by `borrowed_quantity` as the physical doses leave it, while the borrower lot's `quantity_borrowed_in` increases by the same amount to record the IOU — its `quantity_on_hand` does not change, because the physical doses went into a patient, not onto a shelf. The ticket opens in `OPEN` status with `paid_back_quantity` at zero, and the site's `private_lending_balance` is recomputed.

Payback is the second OCC-guarded write in the system. Each payback request carries the `payback_quantity`, the `paying_lot_id` sourcing the replacement doses, and `expected_borrow_ticket_version` holding the caller's last-observed ticket `version`. The checks run in a fixed order: the expected version must match the ticket's current `version` (`ERR_STALE_VERSION`); the ticket must be `OPEN` or `PARTIALLY_REPAID` (`ERR_INVALID_STATE`); the `payback_quantity` must be at least one (`ERR_INVALID_REQUEST`); the cumulative `paid_back_quantity` plus this `payback_quantity` must not exceed `borrowed_quantity` (`ERR_PAYBACK_EXCEEDS_BORROWED`) — a payback of exactly the remaining balance is allowed and closes the ticket; the paying lot's `stock_type` must match the borrower lot's `stock_type`, so for `PUBLIC_FROM_PRIVATE` a `PUBLIC_VFC` lot replenishes the private lender while for `PRIVATE_FROM_PUBLIC` a `PRIVATE` lot replenishes the public lender — a paying lot on the wrong side of the divide is rejected with `ERR_SAME_STOCK_BORROW`; and the paying lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`) holding at least `payback_quantity` doses (`ERR_INSUFFICIENT_STOCK`). A successful payback adds the quantity to `paid_back_quantity`, draws it out of the paying lot's `quantity_on_hand`, returns it to the lender lot's `quantity_on_hand` (quantity only — the lender lot's `status` is left unchanged, so a `DEPLETED` or otherwise terminal lot is not resurrected), and amortizes the borrower lot's `quantity_borrowed_in` by the same amount; the site's `private_lending_balance` is recomputed, and the ticket's `version` increments by one. When the cumulative payback equals `borrowed_quantity` the ticket moves automatically to `REPAID` — whether from `OPEN` in a single payment or from `PARTIALLY_REPAID` — and any smaller payment lands it in (or keeps it in) `PARTIALLY_REPAID`, the self-loop permitting as many partial paybacks as needed.

A ticket opened in error can be voided, but only while it is `OPEN` (`ERR_INVALID_STATE`), only while `paid_back_quantity` is still zero (`ERR_TICKET_HAS_PAYBACK`), and only while the borrower lot's IOU is still intact — its `quantity_borrowed_in` must be at least the ticket's `borrowed_quantity`, or the borrowed doses are considered consumed and the void fails with `ERR_BORROWED_DOSES_CONSUMED`. Voiding reverses the original open exactly: the borrower lot's `quantity_borrowed_in` decreases by `borrowed_quantity`, cancelling the IOU, and the lender lot's `quantity_on_hand` increases by `borrowed_quantity` as the physical doses return (again without altering the lender lot's `status`); the ticket becomes `VOIDED` and the lending balance is recomputed. `REPAID` and `VOIDED` are terminal.

### 3.8. Short-Dated Stock Redistribution Between Sites

When doses approach expiration faster than one site can use them, a `VaccineManager` initiates a transfer to a higher-volume site, naming the `from_lot_id`, the `destination_site_id`, the `destination_storage_unit_id` that will receive the stock, the `quantity_doses` of at least one, and a free-text `reason` such as reallocating short-dated stock. Initiation itself already requires the source lot to be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`) and to hold at least `quantity_doses` (`ERR_INSUFFICIENT_STOCK`), and the same guards run again at shipment. The transfer opens in `INITIATED` status and may be cancelled only from that state — while no doses have yet left the shelf — moving it to `CANCELLED`, with any other source state rejected as `ERR_INVALID_STATE`.

Shipping moves the transfer from `INITIATED` to `IN_TRANSIT`. The source lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`) and hold at least `quantity_doses` (`ERR_INSUFFICIENT_STOCK`); on shipment its `quantity_on_hand` decreases by `quantity_doses`, and for public stock the origin site's `accountability_balance_doses` is recomputed on the transferred-out side. Receipt at the destination moves the transfer from `IN_TRANSIT` to `RECEIVED` — again, any other source state draws `ERR_INVALID_STATE` — and enforces two checks in this order: the `destination_storage_unit_id` must actually belong to the `destination_site_id` (`ERR_UNIT_SITE_MISMATCH`), and that unit must not be quarantined (`ERR_STORAGE_UNIT_QUARANTINED`).

Receipt materializes the stock at the destination. If the destination site already holds an `AVAILABLE` lot with the same `lot_number`, `stock_type`, and `vaccine_product_id`, the shipment merges into it: that lot's `quantity_on_hand` increases by `quantity_doses`. Otherwise a successor lot is created at the destination site, inheriting `lot_number`, `expires_on`, `stock_type`, and `vaccine_product_id` from the source lot, stored in the destination unit, with `quantity_on_hand` equal to `quantity_doses`; its `received_via_order_id` is null — transfer-created lots do not point back at any order. Either way the transfer's `new_lot_id` is set to the destination lot — the merged one or the newly created one. `RECEIVED` and `CANCELLED` are terminal.

### 3.9. Compliance Site Visits and the Accountability Audit

The compliance cycle begins when a `ComplianceAuditor` schedules a site visit, supplying the `visit_date`; the server records the auditor as `conducted_by_user_id` and opens the audit in `SCHEDULED`. The snapshot and rate fields (`public_doses_received`, `public_doses_administered`, `public_doses_wasted`, `public_doses_transferred_out`, `accountability_gap`, `on_hand_public_total`, `wastage_rate`, `wastage_tier`) remain null until findings are issued. A scheduled audit may be cancelled, moving it to `CANCELLED`, or begun, moving it to `IN_PROGRESS`; both transitions require the audit to currently be `SCHEDULED` and otherwise draw `ERR_INVALID_STATE`.

Issuing findings requires the audit to be `IN_PROGRESS` and moves it to `FINDINGS_ISSUED`; any other source state draws `ERR_INVALID_STATE`. It is the pivotal act: it freezes the accountability snapshot onto the audit record. `public_doses_received` totals every allocation receipt quantity across the site's orders, over all time. `public_doses_administered` counts the site's dose records whose `funding_source` is `PUBLIC_VFC`. `public_doses_wasted` adds the excursion write-offs attributed to the site's public lots — the public-stock portion of each wasted resolution's write-off, so private lots written off in the same excursion count toward the excursion's own `doses_written_off` but not toward this figure — to the pre-zero on-hand quantities of public lots that expired. `public_doses_transferred_out` totals the `quantity_doses` of the site's public-stock transfers that are `IN_TRANSIT` or `RECEIVED` — doses physically off the shelf — while transfers still merely `INITIATED` do not count, and excursions still `OPEN` contribute nothing to the wasted figure. The `accountability_gap` is then received minus administered minus wasted minus transferred out, and `on_hand_public_total` sums `quantity_on_hand` across the site's `PUBLIC_VFC` lots in `AVAILABLE` or `QUARANTINED` status. These frozen values, computed under the final snapshot semantics, are what closure is judged against.

Alongside the gap, the audit reports a tiered wastage rate. The rate is `public_doses_wasted` divided by the larger of `public_doses_received` and one — so a site that received nothing cannot divide by zero — and it is reported rounded to four decimal places, round half up. Tier assignment, however, compares the unrounded rate: below 0.05 the site is GREEN; from 0.05 up to but not including 0.10 it is AMBER; at 0.10 or above it is RED. A RED tier compels the auditor to close the audit through the failure path rather than passing the site.

Closing the audit as passed requires the audit to be `FINDINGS_ISSUED` (`ERR_INVALID_STATE` otherwise), and then three conditions in order: the frozen `accountability_gap` must equal the `on_hand_public_total` exactly, or closure fails with `ERR_ACCOUNTABILITY_GAP_UNRESOLVED`; no excursion anywhere at the site may be `OPEN` or `UNDER_REVIEW` (`ERR_OPEN_EXCURSION_EXISTS`); and no borrow ticket may remain `OPEN` or `PARTIALLY_REPAID` (`ERR_OPEN_BORROW_TICKET_EXISTS`). Passing lands the audit in `CLOSED_PASS`. Closing as failed requires only the `FINDINGS_ISSUED` state and lands the audit in `CLOSED_FAIL` with a consequential cascade: the site's `status` is set to `SUSPENDED_ORDERING`, cutting off new orders until the compliance posture is restored. `CLOSED_PASS`, `CLOSED_FAIL`, and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — a provider site, storage unit, reading, product, lot, patient, screening, dose record, order, order line, receipt, borrow ticket, transfer, or audit — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Error responses use the codes catalogued in §5. Request and response payloads for every endpoint follow the envelope in §2.2 and the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/provider-sites` | Create a VFC provider site | ComplianceAuditor |
| GET | `/provider-sites` | List provider sites (filter: `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/provider-sites/{id}` | Get one provider site | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/suspend-ordering` | Suspend ordering privileges | ComplianceAuditor |
| POST | `/provider-sites/{id}/reinstate-ordering` | Reinstate ordering privileges | ComplianceAuditor |
| POST | `/provider-sites/{id}/terminate` | Terminate site enrollment; cascades lots to `WASTED_CLOSED` | ComplianceAuditor |
| POST | `/provider-sites/{id}/storage-units` | Register a refrigerator or freezer at a site | VaccineManager |
| GET | `/provider-sites/{id}/storage-units` | List storage units for a site | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/storage-units/{id}` | Get one storage unit | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/storage-units/{id}/temperature-readings` | Record a probe reading; opens or closes excursions as a side effect | VaccineManager |
| GET | `/storage-units/{id}/temperature-readings` | List readings for a unit | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/storage-units/{id}/excursions` | List excursions for a unit (filter: `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/storage-units/{id}/excursions/{excursionId}` | Get one excursion | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/storage-units/{id}/excursions/{excursionId}/begin-review` | Move an excursion from `OPEN` to `UNDER_REVIEW` | VaccineManager |
| POST | `/storage-units/{id}/excursions/{excursionId}/resolve-viable` | Resolve an excursion as viable; quarantined lots return to `AVAILABLE` | VaccineManager |
| POST | `/storage-units/{id}/excursions/{excursionId}/resolve-wasted` | Resolve an excursion as wasted; quarantined lots written off | VaccineManager |
| POST | `/vaccine-products` | Register a vaccine product in the catalog | ComplianceAuditor |
| GET | `/vaccine-products` | List catalog products (filter: `vfc_program_eligible`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/vaccine-products/{id}` | Get one product | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/lots` | Manually register a private-stock lot | VaccineManager |
| GET | `/provider-sites/{id}/lots` | List lots for a site (filters: `stock_type`, `status`, `storage_unit_id`, `vaccine_product_id`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/lots/{id}` | Get one lot | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/patients` | Register a pediatric patient at a site | VaccineManager |
| GET | `/provider-sites/{id}/patients` | List patients at a site (filter: `is_active`) | ComplianceAuditor, VaccineManager |
| GET | `/patients/{id}` | Get one patient | ComplianceAuditor, VaccineManager |
| POST | `/patients/{id}/eligibility-screenings` | Record an eligibility screening for a patient on a visit date | VaccineManager |
| GET | `/patients/{id}/eligibility-screenings` | List screenings for a patient (filter: `screening_date`) | ComplianceAuditor, VaccineManager |
| GET | `/eligibility-screenings/{id}` | Get one screening | ComplianceAuditor, VaccineManager |
| POST | `/provider-sites/{id}/dose-administrations` | Record an administered dose | VaccineManager |
| GET | `/provider-sites/{id}/dose-administrations` | List doses administered at a site (filters: `patient_id`, `lot_id`, `funding_source`, `registry_status`, `administration_date`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/dose-administrations/{id}` | Get one dose administration | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/dose-administrations/{doseId}/submit-registry` | Mark a dose `PENDING_SUBMISSION` to `SUBMITTED` | VaccineManager |
| POST | `/provider-sites/{id}/dose-administrations/{doseId}/mark-registry-rejected` | Mark a dose `PENDING_SUBMISSION` to `REJECTED_BY_REGISTRY` | VaccineManager |
| POST | `/provider-sites/{id}/dose-administrations/{doseId}/reset-registry` | Return a dose from `REJECTED_BY_REGISTRY` to `PENDING_SUBMISSION` | VaccineManager |
| POST | `/provider-sites/{id}/vaccine-orders` | Create a draft VFC order | VaccineManager |
| GET | `/provider-sites/{id}/vaccine-orders` | List orders for a site (filter: `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/provider-sites/{id}/vaccine-orders/{orderId}` | Get one order | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/vaccine-orders/{orderId}/lines` | Add an order line to a `DRAFT` order | VaccineManager |
| GET | `/provider-sites/{id}/vaccine-orders/{orderId}/lines` | List lines of an order | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/vaccine-orders/{orderId}/submit` | Submit a `DRAFT` order to the state program | VaccineManager |
| POST | `/provider-sites/{id}/vaccine-orders/{orderId}/approve` | State program approves an order with allocation | StateProgramOfficer |
| POST | `/provider-sites/{id}/vaccine-orders/{orderId}/cancel` | Cancel a `DRAFT` or `SUBMITTED` order | VaccineManager |
| POST | `/provider-sites/{id}/vaccine-orders/{orderId}/allocation-receipts` | Post a shipment receipt against an order line; creates the `PUBLIC_VFC` lot | VaccineManager |
| GET | `/provider-sites/{id}/vaccine-orders/{orderId}/allocation-receipts` | List receipts for an order | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/allocation-receipts/{id}` | Get one receipt | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/borrow-tickets` | Open a borrow ticket across stocks | VaccineManager |
| GET | `/provider-sites/{id}/borrow-tickets` | List borrow tickets for a site (filters: `status`, `direction`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/borrow-tickets/{id}` | Get one borrow ticket | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/borrow-tickets/{ticketId}/record-payback` | Record a (possibly partial) payback against an open ticket | VaccineManager |
| POST | `/provider-sites/{id}/borrow-tickets/{ticketId}/void` | Void an `OPEN` ticket with no paybacks and an intact IOU | VaccineManager |
| POST | `/provider-sites/{id}/short-date-transfers` | Initiate a short-date transfer to another provider site | VaccineManager |
| GET | `/provider-sites/{id}/short-date-transfers` | List transfers originating at a site (filter: `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/short-date-transfers/{id}` | Get one transfer | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/short-date-transfers/{transferId}/ship` | Ship an `INITIATED` transfer; decrements the source lot | VaccineManager |
| POST | `/provider-sites/{id}/short-date-transfers/{transferId}/receive` | Receive an `IN_TRANSIT` transfer; creates or merges the destination lot | VaccineManager |
| POST | `/provider-sites/{id}/short-date-transfers/{transferId}/cancel` | Cancel an `INITIATED` transfer | VaccineManager |
| POST | `/provider-sites/{id}/site-visit-audits` | Schedule a compliance site visit | ComplianceAuditor |
| GET | `/provider-sites/{id}/site-visit-audits` | List audits for a site (filter: `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/site-visit-audits/{id}` | Get one audit | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| POST | `/provider-sites/{id}/site-visit-audits/{auditId}/begin` | Begin a scheduled audit | ComplianceAuditor |
| POST | `/provider-sites/{id}/site-visit-audits/{auditId}/issue-findings` | Freeze the accountability snapshot and issue findings | ComplianceAuditor |
| POST | `/provider-sites/{id}/site-visit-audits/{auditId}/close-pass` | Close an audit as passed | ComplianceAuditor |
| POST | `/provider-sites/{id}/site-visit-audits/{auditId}/close-fail` | Close an audit as failed; suspends site ordering | ComplianceAuditor |
| POST | `/provider-sites/{id}/site-visit-audits/{auditId}/cancel` | Cancel a `SCHEDULED` audit | ComplianceAuditor |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | ComplianceAuditor |
| GET | `/storage-units` | Filtered list of storage units across all sites (filters: `provider_site_id`, `active_excursion_id`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/lots` | Filtered list of lots across all sites (filters: `provider_site_id`, `storage_unit_id`, `vaccine_product_id`, `received_via_order_id`, `stock_type`, `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/temperature-readings` | Filtered list of temperature readings (filter: `storage_unit_id`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/temperature-excursions` | Filtered list of excursions (filters: `storage_unit_id`, `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/patients` | Filtered list of patients (filters: `provider_site_id`, `is_active`) | ComplianceAuditor, VaccineManager |
| GET | `/eligibility-screenings` | Filtered list of screenings (filters: `patient_id`, `screening_date`) | ComplianceAuditor, VaccineManager |
| GET | `/dose-administrations` | Filtered list of doses (filters: `provider_site_id`, `patient_id`, `eligibility_screening_id`, `lot_id`, `borrowed_context_ticket_id`, `funding_source`, `registry_status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/vaccine-orders` | Filtered list of orders across all sites (filters: `provider_site_id`, `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/order-lines` | Filtered list of order lines (filters: `vaccine_order_id`, `vaccine_product_id`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/order-lines/{id}` | Get one order line | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/allocation-receipts` | Filtered list of allocation receipts (filters: `vaccine_order_id`, `order_line_id`, `storage_unit_id`, `lot_id`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/borrow-tickets` | Filtered list of borrow tickets across all sites (filters: `provider_site_id`, `from_lot_id`, `to_lot_id`, `status`, `direction`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/site-visit-audits` | Filtered list of audits across all sites (filters: `provider_site_id`, `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |
| GET | `/short-date-transfers` | Filtered list of transfers across all sites (filters: `provider_site_id`, `from_lot_id`, `destination_site_id`, `destination_storage_unit_id`, `new_lot_id`, `status`) | ComplianceAuditor, VaccineManager, StateProgramOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STORAGE_UNIT_QUARANTINED` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_STOCK_ELIGIBILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SCREENING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE` | 422 Unprocessable Entity |
| `ERR_UNIT_SITE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_SAME_STOCK_BORROW` | 422 Unprocessable Entity |
| `ERR_PAYBACK_EXCEEDS_BORROWED` | 422 Unprocessable Entity |
| `ERR_TICKET_HAS_PAYBACK` | 409 Conflict |
| `ERR_BORROWED_DOSES_CONSUMED` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LINE_ALLOCATION_MISSING` | 422 Unprocessable Entity |
| `ERR_SITE_SUSPENDED_ORDERING` | 409 Conflict |
| `ERR_ACCOUNTABILITY_GAP_UNRESOLVED` | 422 Unprocessable Entity |
| `ERR_OPEN_EXCURSION_EXISTS` | 409 Conflict |
| `ERR_OPEN_BORROW_TICKET_EXISTS` | 409 Conflict |
| `ERR_OPEN_AUDIT_EXISTS` | 409 Conflict |
| `ERR_EXCURSION_STILL_OPEN` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_INVALID_ENUM` | 400 Bad Request |
