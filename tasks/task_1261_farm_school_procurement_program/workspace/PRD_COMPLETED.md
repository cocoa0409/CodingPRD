# Farm School Procurement API — Product Requirements Document

## 1. Introduction

A district farm-to-school program buys food directly from growers near its schools and pays for it, in part, with a state grant that rewards local sourcing. Running that program means coordinating five very different actors — district administrators, farm managers, kitchen staff, claims coordinators, and state auditors — across a chain that begins with a farm's food-safety paperwork and ends with a line-by-line audit of a monthly reimbursement claim. The Farm School Procurement API is the system of record for that entire chain.

This document specifies the API's behavior for the full operating cycle: program-year setup with a configurable geographic preference policy; farm enrollment gated on insurance and safety certification; a seasonal product catalog and per-farm offerings; weekly menu forecasts and the planting agreements that cover them; delivery scheduling into kitchen receiving windows; invoicing with a local-purchase incentive; monthly reimbursement claims adjudicated against a conserved grant ledger; substitutions when seasonal supply falls short; and program reporting. All resources are served under the `/f2s` prefix, and every date-dependent rule keys off a logical clock rather than the wall clock so that expirations, seasonal windows, and settlement sweeps behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Five roles are recognized, spelled exactly as follows: `DistrictProgramAdmin`, `FarmManager`, `KitchenManager`, `ClaimsCoordinator`, and `StateGrantAuditor`. Each endpoint admits a fixed set of roles (Section 4); a caller whose role is not admitted to the endpoint is rejected with `ERR_FORBIDDEN`.

Two roles are entity-backed. When `X-User-Role` is `FarmManager`, `X-User-ID` is the `id` of the acting Farm; ownership checks on any resource that references a Farm — a compliance document's `farm_id`, an offering's `farm_id`, and the farm reached transitively through an agreement's offering or a delivery's agreement — compare that reference to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP`. When `X-User-Role` is `KitchenManager`, `X-User-ID` is the `id` of the acting Kitchen, and the same comparison applies to receiving windows (through `kitchen_id`) and to deliveries addressed to a kitchen. The remaining roles — `DistrictProgramAdmin`, `ClaimsCoordinator`, and `StateGrantAuditor` — carry opaque operator identifiers not tied to any persisted entity; the server may record them (for example, as `approved_by_user_id` on an invoice or `submitted_by_user_id` on a claim) but never compares them to any entity's `id`.

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

Two framework-level rejections sit outside the business rules of Sections 3 and 4: a request whose path matches no route is rejected with `ERR_NOT_FOUND` (404 Not Found), and a matched path invoked with an unsupported method is rejected with `ERR_METHOD_NOT_ALLOWED` (405 Method Not Allowed).

---

### 2.3. Pagination

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items before results are returned and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; integer-valued filters (such as `week_number`) likewise reject non-integer filter values with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending, with ties — common under the logical clock, which stamps many records identically — broken by creation order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

Many list endpoints additionally accept resource-specific filters — for example `status`, `farm_id`, `doc_type`, `category`, `product_id`, `program_year_id`, `week_number`, `kitchen_id`, `weekday`, `agreement_id`, `window_id`, `delivery_date`, `delivery_id`, `period_month`, `claim_id`, `invoice_id`, `audit_status`, `forecast_line_id`, and `substitute_product_id`. Filters restrict the result set and combine freely with pagination.

### 2.4. Common Resource Properties

Every primary resource — program years, farms, compliance documents, products, offerings, forecast lines, kitchens, planting agreements, amendments, deliveries, invoices, reimbursement claims, claim lines, and substitution requests — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed upon every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource, including system-driven cascade mutations.

Receiving windows are the single exception: a receiving window is immutable after creation and carries only `id` and `created_at` — both `updated_at` and `version` are absent on that resource.

### 2.5. Validation Order and Error Precedence

Inbound requests are validated as an ordered pipeline; a request that fails an earlier stage is rejected with that stage's error and never reaches later stages. The stages, in order:

1. **Authentication and request shape.** The user-context headers are checked, then required body fields and their types. Missing or malformed fields fail as `ERR_INVALID_REQUEST`; conditionally required fields fail here too — a liability policy without `coverage_cents` is `ERR_COVERAGE_REQUIRED`. Unrecognized body fields are ignored.
2. **Role permission.** The caller's role must be admitted to the endpoint, else `ERR_FORBIDDEN`.
3. **Existence.** Path identifiers are resolved left to right, then body foreign keys; each resource family reports its own not-found error (see §2.6).
4. **Ownership.** Entity-backed ownership and amendment counterparty checks — `ERR_RESOURCE_OWNERSHIP` and `ERR_NOT_COUNTERPARTY`.
5. **Program-year gate.** Creating an offering, a forecast line, a planting agreement, a reimbursement claim, or a substitution request requires the program year to be `OPEN`, else `ERR_PROGRAM_YEAR_NOT_OPEN`.
6. **State preconditions.** The target resource must be in the state the operation requires (the `ERR_*_NOT_*` state family), including state-gated creations: offering creation requires an `APPROVED` farm and an `ACTIVE` product, agreement creation requires a `VERIFIED` offering, and invoice creation requires an `ACCEPTED` delivery.
7. **Farm compliance.** Approval completeness (`ERR_FARM_COMPLIANCE_INCOMPLETE`), posture gates (`ERR_FARM_NOT_COMPLIANT`), and coverage adequacy (`ERR_COVERAGE_BELOW_MINIMUM`).
8. **Cross-resource coherence.** Agreement year versus offering year, window-to-kitchen ownership, window weekday alignment, substitution product distinctness, and the claim-line compliance snapshot.
9. **Temporal windows.** Date-range shape failures are `ERR_INVALID_DATE_RANGE` (HTTP 400); window conflicts — harvest windows outside a season, delivery dates in the past, and their kin — are HTTP 409.
10. **Uniqueness, capacity, and caps.** Duplicate forecast lines and invoice numbers, window overlap and capacity, substitution gap and cap, non-empty claims, amendment floors, segregation of duties, and quantity limits.
11. **Fiscal limits.** `ERR_COMMITMENT_EXCEEDS_UNCOVERED` and `ERR_GRANT_EXHAUSTED`, both HTTP 402.
12. **Optimistic concurrency.** The stale-version check of §2.9 runs last.

This ordering matters whenever several violations coincide: a request that would fail both a state check and a fiscal check is always rejected with the state error, never the fiscal one.

### 2.6. Nested Resource Retrieval

Most resources in this API are addressed flatly by their own `id`. Two creation routes are nested — proposing an amendment lives under a planting agreement's path, and adding a claim line lives under a reimbursement claim's path — and for those the system validates path identifiers in strict left-to-right order. The parent is resolved before the request body is examined: an amendment proposal under an unknown agreement id fails with `ERR_AGREEMENT_NOT_FOUND` regardless of what the payload contains, and a line addition under an unknown claim id fails with `ERR_CLAIM_NOT_FOUND`. The same discipline applies to any nested retrieval: the first identifier, reading left to right, that does not correspond to an existing resource determines the error.

Each resource family reports its own absence: `ERR_PROGRAM_YEAR_NOT_FOUND`, `ERR_FARM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_FORECAST_LINE_NOT_FOUND`, `ERR_KITCHEN_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND`, and `ERR_SUBSTITUTION_NOT_FOUND`. Body-supplied foreign keys — a `farm_id`, `product_id`, `offering_id`, `window_id`, `delivery_id`, or `invoice_id` that names nothing — fail at the same existence stage with the corresponding family's error, after all path identifiers have resolved. When a body carries several foreign keys, they are resolved in the order the endpoint's narrative names them (for a delivery: `agreement_id`, then `kitchen_id`, then `window_id`).

### 2.7. Money, Precision, and Rounding

All monetary values in the system are integer cents: prices, insurance coverage, invoice totals, claim amounts, and the grant ledger alike. Arithmetic never stores fractional cents. Wherever a computation can yield a fraction — the geographic incentive credit and the grant match credit — the result is rounded half-up to the nearest whole cent at exactly the step the business rule specifies, and nowhere else. Preference points, week numbers, distances, and quantities are integers with no rounding. The one non-integer output in the system is the local-spend share percentage, reported rounded half-up to two decimal places.

### 2.8. The Program Calendar and the Logical Clock

A program year spans exactly 52 weeks, numbered 1 through 52, with week 1 beginning on the year's `start_date`. A date's week number within the year is the number of whole seven-day periods elapsed between `start_date` and that date, plus one; deliveries store this derivation in their `week_number` field. Seasonal and harvest windows are inclusive week ranges and may wrap across the year boundary: for a window from a start week to an end week, a given week lies inside the window either when the start does not exceed the end and the week falls between them inclusively, or — in the wraparound case, when the start exceeds the end — when the week is at least the start or at most the end. A window whose start equals its end covers a single week. This one containment rule governs product seasons, offering harvest windows, and agreement windows alike.

All date-dependent behavior keys off a logical clock, never the wall clock. Before any operator has touched it, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. Every server-generated timestamp — the envelope's `api_request_timestamp`, each resource's `created_at` and `updated_at`, and an invoice's `paid_at` — reads this logical clock. A `DistrictProgramAdmin` advances the clock by supplying a `to_iso8601` instant; the clock is monotonic, and an attempt to move it to an earlier instant is rejected with `ERR_CLOCK_REGRESSION`. Advancing the clock triggers three sweeps in its wake. Compliance documents whose `expires_on` now lies in the past move from `ACTIVE` to `EXPIRED`. Deliveries still `SCHEDULED` whose `delivery_date` now lies in the past become `NO_SHOW`. And agreements in `SIGNED`, `AMENDMENT_PROPOSED`, or `FULFILLING` whose harvest window has closed — the current week lying beyond the agreement's `harvest_end_week` — are settled: an agreement that has delivered its full commitment becomes `COMPLETED`, while one that has delivered less becomes `BREACHED`, with the release bookkeeping, pending-amendment rejection, delivery cancellation, and invoice voiding described in §3.4 and §3.5.

### 2.9. Optimistic Concurrency Control

Exactly two write operations in the API are version-guarded. Proposing an amendment against a planting agreement (`POST /f2s/planting-agreements/{id}/amendments`) requires the request body to carry `expected_agreement_version`, holding the agreement `version` the client last observed. Adding a line to a reimbursement claim (`POST /f2s/reimbursement-claims/{id}/lines`) likewise requires `expected_claim_version`, holding the claim `version` the client last observed. In both cases, if the supplied value does not match the parent resource's current `version` — because another write has advanced the parent since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent before retrying. The field is not optional on these two endpoints. No other endpoint accepts a version field.

### 2.10. Hierarchical Consistency and Cascading State Changes

Derived values are never stale. A forecast line's `reserved_quantity` and `uncovered_quantity`, an agreement's `delivered_quantity`, a claim's totals, and a farm's `compliance_posture` are recomputed from their sources whenever the underlying data changes; the farm posture in particular is re-evaluated against a reference date on every read rather than persisted. State changes propagate downward so that a parent which becomes non-operational resolves its dependents: suspending a farm cascades through its offerings, agreements, deliveries, and invoices (§3.2), and breaching or cancelling an agreement resolves its pending amendments, scheduled deliveries, and draft invoices (§3.4). Every mutation — including each individual cascade step — refreshes the affected resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Program Year

A `DistrictProgramAdmin` opens each buying cycle by creating the **program year**: a human-readable `school_year_label` such as "2026-27", the `start_date` on which week 1 begins, and an `end_date` that must come after the `start_date` — the only creation-time date constraint, with no fixed span length enforced; an `end_date` that does not come later than the `start_date` is rejected as `ERR_INVALID_DATE_RANGE`. The year also carries the district's geographic policy. The `local_radius_miles` field sets the greatest road distance at which a farm still counts as local, and it may not be less than 25 miles. The `preference_model` field selects how geographic preference points are scored and takes one of the exact values `LINEAR` or `TIERED`, defaulting to `LINEAR` when omitted. The fiscal frame completes the setup: `grant_award_cents` is the state's award pool in cents (zero or more), and `local_spend_target_pct` is the reporting target as a JSON number, where a value of 30 means 30.00%.

A new program year is born `DRAFT` with `grant_drawn_cents` at zero. Opening the year — a `DRAFT` → `OPEN` transition that fails with `ERR_PROGRAM_YEAR_NOT_DRAFT` unless the year is `DRAFT` — unlocks child creation: offerings, forecast lines, planting agreements, reimbursement claims, and substitution requests may only be created while the year is `OPEN`, and attempts against a year in any other state are rejected with `ERR_PROGRAM_YEAR_NOT_OPEN`. Closing the year requires it to stand in `OPEN` — any other state draws `ERR_PROGRAM_YEAR_NOT_OPEN` — and moves it to `CLOSED`, the terminal state; closure is also refused with `ERR_CLAIMS_UNRESOLVED` while any of the year's reimbursement claims remain `OPEN`, `SUBMITTED`, or `UNDER_REVIEW`.

The year's grant ledger is conserved at all times. The `grant_drawn_cents` figure is the sum of `total_awarded_cents` over the year's claims currently in `RECONCILED` status — a claim that is later reversed no longer counts toward the draw — and `grant_remaining_cents` is always the award minus the drawn amount.

### 3.2. Farm Enrollment, Compliance Documents, and Suspension

A grower enters the program when a `DistrictProgramAdmin` registers the farm with its `legal_name`, `contact_email`, the `distance_miles_to_hub` in road miles from the district hub (zero or more), and the farmed `acres` (any number greater than zero, fractional values included); the farm begins `APPLIED`. Two values derive from the acreage. The `is_small_farm` flag is true when the farm works at most five hundred acres — a farm of exactly five hundred acres qualifies as small. The `required_insurance_cents` floor is 500,000 cents of liability coverage for a small farm and 1,000,000 cents for a larger one.

Before the district will approve the farm, the `FarmManager` uploads the farm's paperwork as compliance documents. Each document names its owning `farm_id`, a `doc_type` of exactly `SAFETY_CERT` or `LIABILITY_INSURANCE`, the issuing body under `issuer`, and a coverage period running from `effective_on` through `expires_on`, both dates inclusive; `expires_on` must be later than `effective_on`, failing which the upload is rejected as `ERR_INVALID_DATE_RANGE`. A liability policy must additionally declare its `coverage_cents` — omitting it is `ERR_COVERAGE_REQUIRED`, and a figure below the farm's `required_insurance_cents` is `ERR_COVERAGE_BELOW_MINIMUM`, while coverage exactly equal to the requirement satisfies it. Documents are born `ACTIVE`; the clock sweep moves a document whose `expires_on` has passed to `EXPIRED`, and a `StateGrantAuditor` may revoke an `ACTIVE` document outright (any other state draws `ERR_DOCUMENT_NOT_ACTIVE`), leaving it `REVOKED`. Both `EXPIRED` and `REVOKED` are terminal.

The farm's `compliance_posture` is a derived value, recomputed whenever it is read rather than stored. Against a reference date, the posture is `COMPLIANT` when the farm is `APPROVED` and holds at least one `ACTIVE` safety certificate whose date range brackets the reference date and at least one `ACTIVE` liability policy whose date range brackets the reference date and whose coverage meets the farm's requirement; otherwise the posture is `NON_COMPLIANT`. The reference date is the current clock date for gating decisions, and the delivery's own date for the invoice snapshot described in §3.6.

Approving a farm — the `APPLIED` → `APPROVED` transition, performed by a `DistrictProgramAdmin` — requires the farm to be `APPLIED` (otherwise `ERR_FARM_NOT_APPLIED`) and its compliance file to be complete at the current clock date: a valid safety certificate and sufficient in-date insurance must both exist, failing which approval is rejected with `ERR_FARM_COMPLIANCE_INCOMPLETE`. Suspension (`APPROVED` → `SUSPENDED`) may be invoked by a `DistrictProgramAdmin` or a `StateGrantAuditor` on a farm that is currently `APPROVED`, failing which `ERR_FARM_NOT_APPROVED`. Suspension is deliberately destructive, and the cascade that follows it is exact: every offering of the farm in `VERIFIED` moves to `SUSPENDED`; every planting agreement whose offering was just suspended and that stands in `SIGNED`, `AMENDMENT_PROPOSED`, or `FULFILLING` is breached, setting its `released_quantity` to the committed quantity minus what has been delivered and its `remaining_quantity` to zero; each such agreement's still-`PROPOSED` amendments move to `REJECTED`; every `SCHEDULED` delivery of a just-breached agreement moves to `CANCELLED`, while `CHECKED_IN` deliveries are left untouched; and every `DRAFT` invoice belonging to a just-breached agreement moves to `VOIDED`.

Reinstatement returns `SUSPENDED` → `APPROVED` and is performed by a `DistrictProgramAdmin`. It demands that the farm actually be `SUSPENDED` (`ERR_FARM_NOT_SUSPENDED`) and that its compliance file be complete at the current clock date — a valid safety certificate and sufficient in-date liability coverage, evaluated on the documents alone, without regard to the farm's own status, which a `compliance_posture` reading could never satisfy for a suspended farm — failing which the attempt is rejected with `ERR_FARM_NOT_COMPLIANT`. On reinstatement, each of the farm's offerings in `SUSPENDED` returns to `VERIFIED`. Breached agreements are not resurrected: `BREACHED` is terminal, and the released quantities stay released.

### 3.3. The Product Catalog and Farm Offerings

The district's catalog is managed by a `DistrictProgramAdmin`, who creates each product with a `name` (say, Roma Tomato), a `category` of exactly `PRODUCE`, `DAIRY`, `PROTEIN`, or `GRAIN`, a selling `unit` of exactly `LB`, `CASE`, `GALLON`, or `DOZEN`, and the product's season as `season_start_week` and `season_end_week`, each an integer from 1 to 52. Seasons follow the wraparound containment rule of §2.8, and a season whose start equals its end covers a single week. A product is born `ACTIVE`; discontinuing it moves `ACTIVE` → `DISCONTINUED` (anything else draws `ERR_PRODUCT_NOT_ACTIVE`), and `DISCONTINUED` is terminal. Discontinuation is not retroactive — existing offerings and agreements built on the product are unaffected — but only an `ACTIVE` product may anchor a new offering.

With the catalog in place, a `FarmManager` offers a product into a program year by supplying `farm_id`, `program_year_id`, `product_id`, a `price_cents_per_unit` greater than zero, a `max_weekly_quantity` greater than zero, and a harvest window as `harvest_start_week` and `harvest_end_week` (each 1 to 52, wraparound permitted in mirror of the season). The harvest window must lie entirely inside the product's season under the same containment rule, failing which creation is rejected with `ERR_HARVEST_WINDOW_OUTSIDE_SEASON`. Creation is gated on all three parents: the program year must be `OPEN`, the farm must be `APPROVED` (`ERR_FARM_NOT_APPROVED`), and the product must be `ACTIVE` (`ERR_PRODUCT_NOT_ACTIVE`).

Creation also pins two computed values onto the offering for its entire life. The `is_local_eligible` flag records whether the farm's `distance_miles_to_hub` is at most the program year's `local_radius_miles`. The `preference_points` score then quantifies the geographic preference under the year's chosen model. When the farm lies beyond the radius, the flag is false and the score is zero under both models. When the farm is within the radius, `LINEAR` awards one hundred points minus the farm's distance in miles — a farm at the hub scores 100, and a farm exactly at the radius scores one hundred minus the radius. `TIERED` instead scores by fixed bands: at most 25 miles earns 100 points, more than 25 and at most 50 miles earns 75, more than 50 and at most 100 miles earns 50, and more than 100 miles but still within the radius earns 25. The two models legitimately disagree: a farm 30 miles out under a 100-mile radius scores 70 under `LINEAR` and 75 under `TIERED`. Both pinned values are immutable snapshots of the farm and year as they stood at creation.

An offering's life begins in `DRAFT`. The farm's `FarmManager` submits it (`DRAFT` → `SUBMITTED`), which fails with `ERR_OFFERING_NOT_SUBMITTABLE` from any other state and still requires the farm to be `APPROVED`. A `DistrictProgramAdmin` then verifies or rejects the submission: verification (`SUBMITTED` → `VERIFIED`) requires the farm to be `APPROVED` and its `compliance_posture` at the current clock date to be `COMPLIANT` (`ERR_FARM_NOT_COMPLIANT`), while rejection accepts an optional `reason` (accepted but not persisted on the offering); both demand the offering currently be `SUBMITTED`, failing which `ERR_OFFERING_NOT_VERIFIABLE`. The farm may also withdraw an offering from `DRAFT`, `SUBMITTED`, or `VERIFIED` — any other state draws `ERR_OFFERING_NOT_WITHDRAWABLE` — except that withdrawal from `VERIFIED` is blocked with `ERR_OFFERING_HAS_ACTIVE_AGREEMENTS` whenever a planting agreement referencing the offering stands in `PROPOSED`, `SIGNED`, `AMENDMENT_PROPOSED`, or `FULFILLING`. `REJECTED` and `WITHDRAWN` are terminal. The remaining two transitions belong to the farm cascade alone: suspension of the farm moves `VERIFIED` offerings to `SUSPENDED`, and reinstatement returns them to `VERIFIED`.

### 3.4. Menu Forecasts, Planting Agreements, and Amendments

Demand planning begins with the weekly menu forecast. For each program year, a `DistrictProgramAdmin` posts forecast lines naming the `program_year_id`, the `product_id`, the `week_number` (1 to 52), and the `planned_quantity` — the units needed district-wide that week, at least 1. The triple of year, product, and week is unique: a second line for the same combination is rejected with `ERR_FORECAST_LINE_EXISTS`. Two quantities are computed on every read of a forecast line. An agreement covers the line when the agreement's product (reached through its offering) is the line's product, the agreement belongs to the same program year, the agreement stands in `SIGNED`, `AMENDMENT_PROPOSED`, or `FULFILLING` — `PROPOSED`, `COMPLETED`, `BREACHED`, and `CANCELLED` never count — and the line's week falls inside the agreement's harvest window under the §2.8 containment rule. The `reserved_quantity` is the sum of `committed_quantity` over all covering agreements, and the `uncovered_quantity` is the planned quantity minus the reserved quantity, floored at zero, so a fully reserved line reports an uncovered quantity of exactly zero. Coverage is recomputed whenever agreements are created, signed, amended to new terms, cancelled, or breached.

Against a `VERIFIED` offering, a `DistrictProgramAdmin` proposes a **planting agreement** carrying `program_year_id`, `offering_id`, a `committed_quantity` of at least 1, and its own `harvest_start_week` and `harvest_end_week`. Three coherence checks bind the proposal together. The agreement's year must equal the offering's year (`ERR_OFFERING_YEAR_MISMATCH`). The agreement's window must lie inside the offering's harvest window (`ERR_AGREEMENT_WINDOW_OUTSIDE_OFFERING`). And the offering itself must be `VERIFIED` (`ERR_OFFERING_NOT_VERIFIED`). A fiscal guard then caps the commitment: the `committed_quantity` may not exceed the smallest `uncovered_quantity` among the forecast lines for the same product in the same year whose week falls inside the agreement's window — weeks in the window with no forecast line at all impose no constraint — and an over-committed proposal is rejected with `ERR_COMMITMENT_EXCEEDS_UNCOVERED` (HTTP 402). At creation the agreement pins its `unit_price_cents` from the offering's `price_cents_per_unit` and its `local_eligible` flag from the offering's `is_local_eligible`; both are snapshots that later offering changes cannot disturb. An agreement is born `PROPOSED` with `delivered_quantity` at zero; its `remaining_quantity` is the committed quantity minus the delivered quantity while the agreement is active and zero in terminal states, and its `released_quantity` stays zero until the agreement ends short, as described below.

The grower's `FarmManager` signs the proposal (`PROPOSED` → `SIGNED`), which requires the agreement to be `PROPOSED` (`ERR_AGREEMENT_NOT_PROPOSED`), the offering still `VERIFIED`, and the farm still `APPROVED`; signing increments the agreement's `version`. The first delivery scheduled against the agreement then flips it, system-side, from `SIGNED` to `FULFILLING`. Fulfillment ends in one of three ways. When a delivery acceptance brings the `delivered_quantity` exactly to the `committed_quantity`, an agreement standing in `FULFILLING` becomes `COMPLETED` — a terminal state; a delivery accepted while the agreement stands in `AMENDMENT_PROPOSED` does not complete it — and overshoot is impossible because scheduling caps each delivery at the uncommitted remainder (§3.5). The clock sweep settles any agreement whose harvest window closes with deliveries outstanding: such an agreement becomes `BREACHED`, its `released_quantity` is set to the committed quantity minus the delivered quantity, its `remaining_quantity` becomes zero, its `SCHEDULED` deliveries are cancelled, its `DRAFT` invoices are voided, and any still-`PROPOSED` amendments are rejected first; the farm-suspension cascade of §3.2 breaches agreements identically. Finally, either a `DistrictProgramAdmin` or the grower's `FarmManager` may cancel an agreement standing in `PROPOSED`, `SIGNED`, or `AMENDMENT_PROPOSED` (any other state draws `ERR_AGREEMENT_NOT_CANCELLABLE`), which applies the same release bookkeeping — released equals committed minus delivered, remaining becomes zero, pending amendments are rejected, and scheduled deliveries are cancelled, although none can exist before fulfillment begins — except that cancellation does not void draft invoices the way breach does.

While an agreement stands in `SIGNED`, `AMENDMENT_PROPOSED`, or `FULFILLING`, either party — the district admin or the owning farm's `FarmManager` — may propose an **amendment**; from any other agreement state the attempt fails with `ERR_AGREEMENT_NOT_AMENDABLE`. The proposal carries at least one of `new_committed_quantity` or `new_unit_price_cents` — a proposal with neither is `ERR_AMENDMENT_EMPTY`, checked after the agreement's amendable-state gate — and each is constrained: a new committed quantity must be an integer of at least 1 and a new unit price an integer greater than zero (either violation fails the shape stage as `ERR_INVALID_REQUEST`), and a new committed quantity may not fall below the agreement's `delivered_quantity` (`ERR_AMENDMENT_BELOW_DELIVERED`). The request must also carry `expected_agreement_version` under the optimistic-concurrency rule of §2.9. The system records the proposing party in `proposed_by_role` from the caller's role header, marks any earlier still-`PROPOSED` amendment on the same agreement `SUPERSEDED`, moves an agreement in `SIGNED` or `FULFILLING` to `AMENDMENT_PROPOSED`, and increments the agreement's `version`.

Only the counterparty may answer an amendment: a `DistrictProgramAdmin` answers one whose `proposed_by_role` is `FarmManager`, and the owning farm's `FarmManager` answers one proposed by the district; the proposing role answering its own proposal is rejected with `ERR_NOT_COUNTERPARTY`. Acceptance requires the amendment to be `PROPOSED` (`ERR_AMENDMENT_NOT_OPEN`) and the agreement to stand in `AMENDMENT_PROPOSED` (`ERR_AGREEMENT_NOT_AMENDABLE`); it applies the new terms — replacing the `committed_quantity`, the `unit_price_cents`, or both — increments the agreement's `version`, and returns the agreement to `FULFILLING` when at least one delivery exists for it, otherwise to `SIGNED`. Rejection requires the amendment to be `PROPOSED` and leaves the agreement's terms unchanged, returning it by the same rule: `FULFILLING` if it has deliveries, `SIGNED` otherwise. `ACCEPTED`, `REJECTED`, and `SUPERSEDED` are all terminal for the amendment.

### 3.5. Kitchen Receiving and the Delivery Workflow

Kitchens enter the system when a `DistrictProgramAdmin` creates them with a `name`. Each kitchen's `KitchenManager` then defines its weekly **receiving windows**: the owning `kitchen_id`, a `weekday` of exactly `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`, a `start_minute` from 0 to 1439, an `end_minute` from 1 to 1440 that must exceed the `start_minute` (otherwise `ERR_INVALID_DATE_RANGE`), and a `capacity_deliveries` of at least 1. A window is a half-open interval — it admits deliveries from the start minute up to but not including the end minute — so two windows on the same kitchen and weekday may touch but never overlap: an incoming window whose interval intersects an existing one is rejected with `ERR_WINDOW_OVERLAP`, while one whose start equals the other's end is lawful adjacency. Windows are immutable and deletable only while unused: deletion is blocked with `ERR_WINDOW_IN_USE` as long as any `SCHEDULED` or `CHECKED_IN` delivery references the window. Capacity is enforced per date — the number of deliveries standing in `SCHEDULED` or `CHECKED_IN` against a window on one date must stay below `capacity_deliveries` (deliveries in terminal states do not count), and a booking that would meet the cap is rejected with `ERR_WINDOW_CAPACITY_FULL`.

With logistics in place, a `FarmManager` schedules a delivery against one of the farm's own agreements, supplying `agreement_id`, `kitchen_id`, `window_id`, `delivery_date`, and `quantity`. Scheduling enforces a stack of rules. The agreement must stand in `SIGNED` or `FULFILLING` (`ERR_AGREEMENT_NOT_ACTIVE`), and the farm's `compliance_posture` at the current clock date must be `COMPLIANT` (`ERR_FARM_NOT_COMPLIANT`). The window must belong to the named kitchen (`ERR_WINDOW_KITCHEN_MISMATCH`), and the window's weekday must equal the weekday of the `delivery_date` (`ERR_WINDOW_WEEKDAY_MISMATCH`). The date must not precede the current logical clock date (`ERR_DELIVERY_DATE_IN_PAST`), and the delivery's derived `week_number` must fall inside the agreement's harvest window and within the program year (`ERR_DELIVERY_OUTSIDE_HARVEST_WINDOW`). Finally, the `quantity` must be at least 1 and may not exceed the agreement's committed quantity minus what has been delivered and minus the quantities still held by that agreement's `SCHEDULED` and `CHECKED_IN` deliveries (`ERR_QUANTITY_EXCEEDS_REMAINING`). A scheduled delivery is born `SCHEDULED` with its `week_number` computed, and the very first delivery against an agreement flips that agreement from `SIGNED` to `FULFILLING`.

When the truck arrives, the receiving kitchen's `KitchenManager` checks the delivery in (`SCHEDULED` → `CHECKED_IN`; from any other state, `ERR_DELIVERY_NOT_SCHEDULED`). From `CHECKED_IN` the kitchen either accepts or rejects the goods. Acceptance records an `accepted_quantity` between 1 and the delivery's full `quantity` inclusive — outside that range is `ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE`, and a delivery not in `CHECKED_IN` draws `ERR_DELIVERY_NOT_CHECKED_IN` — and moves the delivery to `ACCEPTED`. Each acceptance recomputes the agreement's `delivered_quantity` as the sum of `accepted_quantity` over all of the agreement's `ACCEPTED` deliveries, evaluated in delivery-date order with creation time as the tie-break so the completion check is deterministic; the moment the delivered total equals the committed total, an agreement standing in `FULFILLING` becomes `COMPLETED` (the completion check fires only from `FULFILLING`, never from `AMENDMENT_PROPOSED`). Rejection instead requires a `reason`, which is stored on the delivery as `rejection_reason`, moves the delivery to `REJECTED`, and leaves the agreement's delivered total unchanged.

A grower who disputes the kitchen's verdict may escalate: the farm's `FarmManager` moves a `REJECTED` delivery to `DISPUTED` (`ERR_DELIVERY_NOT_REJECTED` from any other state). A `DistrictProgramAdmin` then resolves the dispute by supplying a `resolution` of exactly `ACCEPTED` or `CLOSED_REJECTED`; a delivery that is not `DISPUTED` draws `ERR_DELIVERY_NOT_DISPUTED`. Resolving to `ACCEPTED` carries an `accepted_quantity` in the same 1-to-`quantity` range (`ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE`) and produces exactly the same downstream effects as a kitchen acceptance — the delivered total is recomputed and a fully delivered agreement completes. Resolving to `CLOSED_REJECTED` simply closes the matter. Before any of this, the grower may still cancel outright: cancelling a `SCHEDULED` delivery moves it to `CANCELLED`, and the same transition arrives by cascade when the underlying agreement is breached or cancelled. Should the `delivery_date` pass with the delivery still `SCHEDULED`, the clock sweep marks it `NO_SHOW`. `ACCEPTED`, `CLOSED_REJECTED`, `CANCELLED`, and `NO_SHOW` are the delivery's terminal states.

### 3.6. Invoicing and the Local-Purchase Incentive

Once a delivery has been accepted, the grower's `FarmManager` invoices it by supplying the `delivery_id` and an `invoice_number`. The delivery must stand in `ACCEPTED` (`ERR_DELIVERY_NOT_ACCEPTED`), it may carry at most one invoice ever — an existing invoice of any status, even `VOIDED`, bars a second (`ERR_INVOICE_EXISTS_FOR_DELIVERY`) — and the invoice number must be unique among this farm's invoices across all statuses (`ERR_DUPLICATE_INVOICE_NUMBER`); when both uniqueness rules would fail at once, the duplicate-number error is reported first. Creation derives the invoice's `farm_id` and `agreement_id` by walking the delivery's chain through its agreement to the offering's farm, pins `quantity_billed` from the delivery's `accepted_quantity` and `unit_price_cents` from the agreement, and snapshots `farm_compliant_at_delivery` — the farm's `compliance_posture` evaluated at the delivery's `delivery_date`, kept as a permanent audit trail even if the farm's posture later changes.

Pricing follows a pinned evaluation order. First, `subtotal_cents` is the billed quantity multiplied by the unit price. Second, the incentive tier is read from the farm's year-to-date local invoicing: the sum of `subtotal_cents` over this farm's invoices in `APPROVED` or `PAID` status for the same program year whose agreements are local-eligible, excluding the invoice being created. While that year-to-date figure is below 1,000,000 cents the rate is two percent; below 5,000,000 cents it is three percent; at or beyond that mark it is five percent. Third, `incentive_credit_cents` is the subtotal multiplied by that rate, rounded half-up to a whole cent, when the agreement is local-eligible — and zero otherwise. Fourth, `total_cents` is the subtotal plus the incentive credit. Because the tier is read excluding the current invoice, an invoice that itself crosses a threshold does not change its own rate.

The invoice lifecycle then runs through review. A new invoice is `DRAFT`; the farm's `FarmManager` submits it (`DRAFT` → `SUBMITTED`), which requires a `DRAFT` invoice (`ERR_INVOICE_NOT_SUBMITTABLE`) and a farm still `APPROVED` (`ERR_FARM_NOT_APPROVED`). A `DistrictProgramAdmin` adjudicates submissions: approval moves `SUBMITTED` → `APPROVED` and captures the approver's identity in `approved_by_user_id`, while rejection — which carries a mandatory `reason` that is not persisted on the invoice — moves the invoice to `REJECTED`; both require a `SUBMITTED` invoice (`ERR_INVOICE_NOT_APPROVABLE`). Rejection is not the end: the farm may revise, returning `REJECTED` → `DRAFT` (`ERR_INVOICE_NOT_REVISABLE` from any other state) for correction and resubmission. Payment moves `APPROVED` → `PAID` (`ERR_INVOICE_NOT_PAYABLE` otherwise) and stamps `paid_at` with the current logical clock timestamp, rendered in the same ISO 8601 UTC format with three fractional digits as `created_at` and `updated_at`. Two terminal states exist — `PAID` and `VOIDED` — the latter reached only by cascade when the invoice's agreement is breached while the invoice is still `DRAFT`.

### 3.7. Reimbursement Claims, Audit Adjudication, and the Grant Ledger

Monthly, a `ClaimsCoordinator` opens a reimbursement claim against a program year by supplying the `program_year_id` and a `period_month` in year-month form; the period must overlap the program year, failing which creation is rejected with `ERR_PERIOD_OUTSIDE_YEAR`. A claim is born `OPEN` with `total_claimed_cents`, `total_awarded_cents`, and `match_provisional_cents` all at zero and `match_final_cents` still null.

While the claim is `OPEN`, the coordinator adds invoices to it as claim lines, each request naming the `invoice_id` and carrying `expected_claim_version` under the optimistic-concurrency rule of §2.9; adding to a claim in any other state fails with `ERR_CLAIM_NOT_OPEN`. Lines are added under the claim's path and carry its id as `claim_id`. The invoice's own lifecycle status is not gated. Four rules gate each line, and when several would fail at once they report in this order: the invoice's `farm_compliant_at_delivery` snapshot must be true (`ERR_LINE_FARM_NONCOMPLIANT`); the month of the invoice's delivery date must equal the claim's `period_month` (`ERR_INVOICE_OUTSIDE_PERIOD`); an invoice may appear on at most one claim line anywhere in the system (`ERR_INVOICE_ALREADY_CLAIMED`); and the invoice's agreement must be local-eligible, since only local purchases are grant-reimbursable (`ERR_LINE_NOT_LOCAL`). The §2.9 stale-version check runs after all four. Each new line snapshots its `claimed_amount_cents` from the invoice's `total_cents`, begins with `audit_status` `PENDING` and `disallowed_amount_cents` at zero, recomputes the claim's claimed total and provisional match, and increments the claim's `version`.

The district documents fifty cents of match per grant dollar, and the rounding order is pinned: each line's match is rounded half-up to a whole cent first, and only then are the per-line amounts summed — rounding after summation is not equivalent and is not permitted. Two lines claiming 153 and 255 cents contribute 77 and 128 matched cents respectively, totaling 205; summing first would wrongly yield 204. The `match_provisional_cents` figure applies this per-line rounding to claimed amounts and refreshes as lines are added, while `match_final_cents` applies it to awarded amounts and remains null until adjudication completes.

Submitting the claim (`OPEN` → `SUBMITTED`) requires at least one line (`ERR_CLAIM_EMPTY`) and enforces segregation of duties: the submitter's `X-User-ID` must differ from the `approved_by_user_id` recorded on every line's invoice, failing which submission is rejected with `ERR_SOD_VIOLATION`; a successful submission stamps `submitted_by_user_id` with the caller's identity. A `StateGrantAuditor` then takes the claim under review (`SUBMITTED` → `UNDER_REVIEW`; otherwise `ERR_CLAIM_NOT_SUBMITTED`).

Adjudication proceeds line by line. Allowing a line requires the claim to be `UNDER_REVIEW` (`ERR_CLAIM_NOT_UNDER_REVIEW`) and the line still `PENDING` (`ERR_CLAIM_LINE_NOT_PENDING`); it moves the line's `audit_status` to `ALLOWED` and awards the line's full claimed amount. Disallowing requires the same two gates plus a `disallowed_amount_cents` between 1 and the line's claimed amount inclusive (`ERR_DISALLOWANCE_OUT_OF_RANGE`) and a reason — supplied under `reason` or `disallowance_reason` — recorded on the line as `disallowance_reason`; it moves the line to `DISALLOWED` and awards its claimed amount minus the disallowed portion. Lines still `PENDING` award nothing, so the claim's `total_awarded_cents` — the sum over lines of each line's awarded amount — grows as adjudication proceeds. When the last `PENDING` line is adjudicated, the claim transitions on its own: to `AWARDED` when every line stands in `ALLOWED`, to `PARTIALLY_AWARDED` when some lines stand in `DISALLOWED` but the awarded total is still greater than zero, and to `REJECTED` when the awarded total is exactly zero; in all three cases `match_final_cents` is computed on awarded amounts (zero for a rejected claim).

Reconciliation is where the grant moves. A `StateGrantAuditor` reconciles a claim in `AWARDED` or `PARTIALLY_AWARDED` (any other state draws `ERR_CLAIM_NOT_AWARDED`) provided its `total_awarded_cents` fits within the program year's `grant_remaining_cents` — an award beyond the remaining balance is rejected with `ERR_GRANT_EXHAUSTED` (HTTP 402). On success the claim becomes `RECONCILED`, and the year's `grant_drawn_cents` rises while `grant_remaining_cents` falls by the awarded total. Reversal is the compensating action: reversing a `RECONCILED` claim (`ERR_CLAIM_NOT_RECONCILED` from any other state) moves it to `REVERSED` and restores the awarded total to the remaining balance. `RECONCILED`, `REJECTED`, and `REVERSED` are terminal.

### 3.8. Substitutions for Uncovered Demand

When a forecast line still shows uncovered demand, a `DistrictProgramAdmin` may request a substitution: the `forecast_line_id`, a `substitute_product_id` that must differ from the line's own product (`ERR_SAME_PRODUCT_SUBSTITUTION`), a `quantity` of at least 1 that may not exceed the line's `uncovered_quantity` (`ERR_SUBSTITUTION_EXCEEDS_GAP`), and a `reason` of exactly `SEASONALITY_GAP`, `SUPPLY_SHORTFALL`, or `QUALITY_FAILURE`. A line with no gap at all — an `uncovered_quantity` of zero — cannot anchor a request (`ERR_NO_SEASONALITY_GAP`, which takes precedence over `ERR_SUBSTITUTION_EXCEEDS_GAP` when both would apply). A new request is `REQUESTED`.

A program-wide cap disciplines substitutions. The request's product and program year are read from its anchored forecast line: the product is the line's own product — the demand being substituted, not the substitute product named on the request — and the year is the line's program year. For that product in that year, the cap is twenty percent of the total `planned_quantity` across all of that product's forecast lines in the year, rounded down to a whole unit. The sum of `quantity` over already-`APPROVED` requests whose forecast lines share that product and year, plus the quantity under consideration, may not exceed the cap — and a request landing exactly on the cap is permitted. The cap is enforced when the request is created and checked again at approval time, since intervening approvals may have consumed the remaining room; a breach at either point is rejected with `ERR_SUBSTITUTION_CAP_EXCEEDED`. A `StateGrantAuditor` approves or denies a request standing in `REQUESTED` (any other state draws `ERR_SUBSTITUTION_NOT_PENDING`); both `APPROVED` and `DENIED` are terminal.

### 3.9. Program Reporting and Grant Match Rollup

An administrator-facing reporting capability returns a computed monthly report for a program year, keyed by a required `month` query parameter in `YYYY-MM` form — a missing or malformed `month` is `ERR_INVALID_REQUEST`. The report walks the year's invoices — `VOIDED` excluded — twice, on two bases. The accrual basis includes invoices in `DRAFT`, `SUBMITTED`, `APPROVED`, or `PAID` whose delivery's `delivery_date` falls in the report month; the cash basis includes only `PAID` invoices whose `paid_at` falls in the report month. Both bases value invoices at `subtotal_cents`, and each basis carries a local column restricted to invoices whose agreements are local-eligible. The share figures are zero when their basis total is zero, and otherwise one hundred times the local amount divided by the total, rounded half-up to two decimal places; a share that meets or exceeds the year's `local_spend_target_pct` counts as meeting the target. A delivery accepted in August but paid in September therefore lands in the August accrual column and the September cash column — different months, different totals, same underlying data.

The report's response fields are: `month`, `cash_local_spend_cents`, `accrual_local_spend_cents`, `cash_total_spend_cents`, `accrual_total_spend_cents`, `cash_local_share_pct`, `accrual_local_share_pct`, `meets_target_cash`, `meets_target_accrual`, the grant ledger trio `grant_award_cents`, `grant_drawn_cents`, and `grant_remaining_cents`, and the match rollups `match_provisional_cents` and `match_final_cents`. The provisional rollup sums the provisional match over every claim of the year; the final rollup sums the final match only over claims that have moved past `UNDER_REVIEW`, with claims still awaiting adjudication contributing zero.

## 4. Endpoint Definitions

Endpoints that create a new resource — including sub-resources such as an amendment or a claim line — return `201 Created` with the created resource in the response body. Endpoints that modify an existing resource or drive a state transition return `200 OK` with the updated resource. Deleting a receiving window returns `204 No Content` with an empty body (no envelope); the clock-advance capability returns `200 OK` with an empty `data` object. The complete request and response semantics of each operation are defined by the narratives of Sections 2 and 3; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/f2s/program-years` | Create a program year | DistrictProgramAdmin |
| GET | `/f2s/program-years` | List program years | All roles |
| GET | `/f2s/program-years/{id}` | Get a program year | All roles |
| POST | `/f2s/program-years/{id}/open` | Open a draft year (DRAFT → OPEN) | DistrictProgramAdmin |
| POST | `/f2s/program-years/{id}/close` | Close an open year (OPEN → CLOSED) | DistrictProgramAdmin |
| GET | `/f2s/program-years/{id}/report` | Computed monthly program report (cash and accrual bases, grant ledger, match rollups) | All roles |
| POST | `/f2s/farms` | Register an applicant farm | DistrictProgramAdmin |
| GET | `/f2s/farms` | List farms | All roles |
| GET | `/f2s/farms/{id}` | Get a farm | All roles |
| POST | `/f2s/farms/{id}/approve` | Approve a farm (compliance gate) | DistrictProgramAdmin |
| POST | `/f2s/farms/{id}/suspend` | Suspend a farm, cascading to offerings, agreements, deliveries, and invoices | DistrictProgramAdmin, StateGrantAuditor |
| POST | `/f2s/farms/{id}/reinstate` | Reinstate a suspended farm (compliance gate) | DistrictProgramAdmin |
| POST | `/f2s/compliance-documents` | Upload a safety certificate or insurance policy | FarmManager |
| GET | `/f2s/compliance-documents` | List compliance documents | All roles |
| GET | `/f2s/compliance-documents/{id}` | Get a compliance document | All roles |
| POST | `/f2s/compliance-documents/{id}/revoke` | Revoke an active document | StateGrantAuditor |
| POST | `/f2s/products` | Create a catalog product | DistrictProgramAdmin |
| GET | `/f2s/products` | List products | All roles |
| GET | `/f2s/products/{id}` | Get a product | All roles |
| POST | `/f2s/products/{id}/discontinue` | Discontinue a product | DistrictProgramAdmin |
| POST | `/f2s/offerings` | Offer a product into a program year; eligibility and preference points pinned | FarmManager |
| GET | `/f2s/offerings` | List offerings | All roles |
| GET | `/f2s/offerings/{id}` | Get an offering | All roles |
| POST | `/f2s/offerings/{id}/submit` | Submit an offering for verification | FarmManager |
| POST | `/f2s/offerings/{id}/verify` | Verify a submitted offering (farm compliance gate) | DistrictProgramAdmin |
| POST | `/f2s/offerings/{id}/reject` | Reject a submitted offering | DistrictProgramAdmin |
| POST | `/f2s/offerings/{id}/withdraw` | Withdraw an offering (blocked while agreements are active) | FarmManager |
| POST | `/f2s/forecast-lines` | Create a weekly menu forecast line | DistrictProgramAdmin |
| GET | `/f2s/forecast-lines` | List forecast lines | All roles |
| GET | `/f2s/forecast-lines/{id}` | Get a forecast line (with reserved and uncovered quantities) | All roles |
| POST | `/f2s/kitchens` | Create a school kitchen | DistrictProgramAdmin |
| GET | `/f2s/kitchens` | List kitchens | All roles |
| GET | `/f2s/kitchens/{id}` | Get a kitchen | All roles |
| POST | `/f2s/receiving-windows` | Create a weekly receiving window (half-open overlap check) | KitchenManager |
| GET | `/f2s/receiving-windows` | List receiving windows | All roles |
| GET | `/f2s/receiving-windows/{id}` | Get a receiving window | All roles |
| DELETE | `/f2s/receiving-windows/{id}` | Delete a window (blocked while in use) | KitchenManager |
| POST | `/f2s/planting-agreements` | Propose a planting agreement against a verified offering | DistrictProgramAdmin |
| GET | `/f2s/planting-agreements` | List planting agreements | All roles |
| GET | `/f2s/planting-agreements/{id}` | Get a planting agreement | All roles |
| POST | `/f2s/planting-agreements/{id}/sign` | Grower signs a proposed agreement | FarmManager |
| POST | `/f2s/planting-agreements/{id}/cancel` | Cancel an agreement before fulfillment | DistrictProgramAdmin, FarmManager |
| POST | `/f2s/planting-agreements/{id}/amendments` | Propose an amendment (version-guarded; supersedes the prior open amendment) | DistrictProgramAdmin, FarmManager |
| GET | `/f2s/planting-agreements/{id}/amendments` | List an agreement's amendments | All roles |
| GET | `/f2s/agreement-amendments/{id}` | Get an amendment | All roles |
| POST | `/f2s/agreement-amendments/{id}/accept` | Counterparty accepts; terms applied to the agreement | DistrictProgramAdmin, FarmManager (counterparty only) |
| POST | `/f2s/agreement-amendments/{id}/reject` | Counterparty rejects; agreement terms unchanged | DistrictProgramAdmin, FarmManager (counterparty only) |
| POST | `/f2s/deliveries` | Schedule a delivery into a kitchen receiving window | FarmManager |
| GET | `/f2s/deliveries` | List deliveries | All roles |
| GET | `/f2s/deliveries/{id}` | Get a delivery | All roles |
| POST | `/f2s/deliveries/{id}/check-in` | Check in a scheduled delivery | KitchenManager |
| POST | `/f2s/deliveries/{id}/accept` | Accept a checked-in delivery with an accepted quantity | KitchenManager |
| POST | `/f2s/deliveries/{id}/reject` | Reject a checked-in delivery with a reason | KitchenManager |
| POST | `/f2s/deliveries/{id}/dispute` | Dispute a rejected delivery | FarmManager |
| POST | `/f2s/deliveries/{id}/resolve-dispute` | Resolve a dispute to accepted or closed-rejected | DistrictProgramAdmin |
| POST | `/f2s/deliveries/{id}/cancel` | Cancel a scheduled delivery | FarmManager |
| POST | `/f2s/invoices` | Create an invoice for an accepted delivery | FarmManager |
| GET | `/f2s/invoices` | List invoices | All roles |
| GET | `/f2s/invoices/{id}` | Get an invoice | All roles |
| POST | `/f2s/invoices/{id}/submit` | Submit a draft invoice | FarmManager |
| POST | `/f2s/invoices/{id}/approve` | Approve a submitted invoice; captures the approver's identity | DistrictProgramAdmin |
| POST | `/f2s/invoices/{id}/reject` | Reject a submitted invoice | DistrictProgramAdmin |
| POST | `/f2s/invoices/{id}/revise` | Return a rejected invoice to draft for correction | FarmManager |
| POST | `/f2s/invoices/{id}/pay` | Pay an approved invoice; stamps the logical-clock timestamp | DistrictProgramAdmin |
| POST | `/f2s/reimbursement-claims` | Create a monthly reimbursement claim batch | ClaimsCoordinator |
| GET | `/f2s/reimbursement-claims` | List reimbursement claims | All roles |
| GET | `/f2s/reimbursement-claims/{id}` | Get a claim (with totals and match fields) | All roles |
| POST | `/f2s/reimbursement-claims/{id}/lines` | Add an invoice as a claim line (version-guarded) | ClaimsCoordinator |
| GET | `/f2s/claim-lines` | List claim lines | All roles |
| GET | `/f2s/claim-lines/{id}` | Get a claim line | All roles |
| POST | `/f2s/reimbursement-claims/{id}/submit` | Submit an open claim (segregation-of-duties gate) | ClaimsCoordinator |
| POST | `/f2s/reimbursement-claims/{id}/start-review` | Take a submitted claim under review | StateGrantAuditor |
| POST | `/f2s/claim-lines/{id}/allow` | Allow a pending line; may complete adjudication of the claim | StateGrantAuditor |
| POST | `/f2s/claim-lines/{id}/disallow` | Disallow a pending line with an amount and reason | StateGrantAuditor |
| POST | `/f2s/reimbursement-claims/{id}/reconcile` | Reconcile an awarded claim, drawing down the grant | StateGrantAuditor |
| POST | `/f2s/reimbursement-claims/{id}/reverse` | Reverse a reconciled claim, restoring the grant (compensating action) | StateGrantAuditor |
| POST | `/f2s/substitution-requests` | Request a substitution for an uncovered forecast gap | DistrictProgramAdmin |
| GET | `/f2s/substitution-requests` | List substitution requests | All roles |
| GET | `/f2s/substitution-requests/{id}` | Get a substitution request | All roles |
| POST | `/f2s/substitution-requests/{id}/approve` | Approve a substitution request (cap re-checked) | StateGrantAuditor |
| POST | `/f2s/substitution-requests/{id}/deny` | Deny a substitution request | StateGrantAuditor |
| POST | `/f2s/_clock/set_current_utc` | Advance the logical clock; runs the expiry, no-show, and window-close sweeps | DistrictProgramAdmin |

## 5. Error Code Catalogue

The catalogue below lists every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of Sections 2 and 3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_AMENDMENT_EMPTY` | 400 Bad Request |
| `ERR_COVERAGE_REQUIRED` | 400 Bad Request |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_COUNTERPARTY` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PROGRAM_YEAR_NOT_FOUND` | 404 Not Found |
| `ERR_FARM_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFERING_NOT_FOUND` | 404 Not Found |
| `ERR_FORECAST_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_KITCHEN_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AMENDMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_NOT_ALLOWED` | 405 Method Not Allowed |
| `ERR_PROGRAM_YEAR_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_CLAIMS_UNRESOLVED` | 409 Conflict |
| `ERR_FARM_NOT_APPLIED` | 409 Conflict |
| `ERR_FARM_NOT_APPROVED` | 409 Conflict |
| `ERR_FARM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_DOCUMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRODUCT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OFFERING_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_OFFERING_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_OFFERING_NOT_VERIFIED` | 409 Conflict |
| `ERR_OFFERING_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_AMENDABLE` | 409 Conflict |
| `ERR_AMENDMENT_NOT_OPEN` | 409 Conflict |
| `ERR_DELIVERY_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DELIVERY_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_DELIVERY_NOT_REJECTED` | 409 Conflict |
| `ERR_DELIVERY_NOT_DISPUTED` | 409 Conflict |
| `ERR_DELIVERY_NOT_ACCEPTED` | 409 Conflict |
| `ERR_INVOICE_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_APPROVABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_REVISABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_OPEN` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_LINE_NOT_PENDING` | 409 Conflict |
| `ERR_CLAIM_NOT_AWARDED` | 409 Conflict |
| `ERR_CLAIM_NOT_RECONCILED` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_PENDING` | 409 Conflict |
| `ERR_FARM_COMPLIANCE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_FARM_NOT_COMPLIANT` | 422 Unprocessable Entity |
| `ERR_COVERAGE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_OFFERING_YEAR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WINDOW_KITCHEN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WINDOW_WEEKDAY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SAME_PRODUCT_SUBSTITUTION` | 422 Unprocessable Entity |
| `ERR_LINE_FARM_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DISALLOWANCE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_HARVEST_WINDOW_OUTSIDE_SEASON` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OUTSIDE_OFFERING` | 409 Conflict |
| `ERR_DELIVERY_OUTSIDE_HARVEST_WINDOW` | 409 Conflict |
| `ERR_DELIVERY_DATE_IN_PAST` | 409 Conflict |
| `ERR_PERIOD_OUTSIDE_YEAR` | 409 Conflict |
| `ERR_INVOICE_OUTSIDE_PERIOD` | 409 Conflict |
| `ERR_FORECAST_LINE_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_INVOICE_EXISTS_FOR_DELIVERY` | 409 Conflict |
| `ERR_INVOICE_ALREADY_CLAIMED` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_CAPACITY_FULL` | 409 Conflict |
| `ERR_WINDOW_IN_USE` | 409 Conflict |
| `ERR_NO_SEASONALITY_GAP` | 409 Conflict |
| `ERR_SUBSTITUTION_EXCEEDS_GAP` | 409 Conflict |
| `ERR_SUBSTITUTION_CAP_EXCEEDED` | 409 Conflict |
| `ERR_CLAIM_EMPTY` | 409 Conflict |
| `ERR_OFFERING_HAS_ACTIVE_AGREEMENTS` | 409 Conflict |
| `ERR_AMENDMENT_BELOW_DELIVERED` | 409 Conflict |
| `ERR_LINE_NOT_LOCAL` | 409 Conflict |
| `ERR_QUANTITY_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_COMMITMENT_EXCEEDS_UNCOVERED` | 402 Payment Required |
| `ERR_GRANT_EXHAUSTED` | 402 Payment Required |
