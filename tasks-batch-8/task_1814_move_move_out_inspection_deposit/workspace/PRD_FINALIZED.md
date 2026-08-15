# Move-In/Move-Out Inspection & Deposit Accounting API — Product Requirements Document

## 1. Introduction

Residential security-deposit administration is a statute-driven discipline: every jurisdiction fixes its own deadline for returning an itemized deduction statement after move-out, some require deposits to accrue interest for the tenant, and most punish a late statement with enhanced damages exposure in small claims court. Property managers who miss these rules by even a day convert a routine refund into bad-faith liability, while unclaimed refund checks eventually become an escheatment obligation owed to the state. This document specifies the Move-In/Move-Out Inspection & Deposit Accounting API, a system that operationalizes that entire lifecycle for a residential property-management company.

The API, mounted under `/pm`, governs condition documentation with photo evidence at move-in, damage-versus-normal-wear determination at move-out against carpet and paint depreciation schedules, itemized deduction statements issued within the statutory deadline, deposit interest accrual under two jurisdictional variants, key and fob return accounting with optional lock-change charges, a tenant dispute workflow with counter-offers and small-claims escalation, and the disbursement ledger that carries a refund from issuance through cashing, stale-dating, reversal, and final escheatment of unclaimed funds. Four operator roles cooperate across the lifecycle, and every money movement is reconciled against a per-tenancy balance invariant so the books always tie out.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `ManagerAdmin`, `PropertyManager`, `Inspector`, and `Tenant`. A request whose headers are missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenancy`; ownership checks on any resource that references a tenancy compare the resource's `tenancy_id` foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `ManagerAdmin`, `PropertyManager`, or `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `inspector_user_id` on an `Inspection` when an inspection is scheduled) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — jurisdiction profiles, properties, units, tenancies, inspections, inspection items, deductions, statements, disputes, and disbursements — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T09:15:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; refreshed on every mutation.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource, including mutations driven by cascading side effects and automatic state reconciliation.

Because cascades are first-class in this domain, a mutation that fans out — recomputing a tenancy's money counters when a deduction is created, for example — updates the affected resource's `updated_at` and increments its `version` just as a direct client write would.

### 2.5. The Logical Clock and the Daily Ops Cycle

All time-dependent behavior in the system — appointment windows, completion timestamps, statutory deadlines, dispute windows, stale-check aging — is evaluated against a single server-side logical clock, never against wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any clock-setting call the clock returns this default and never falls back to the host's wall-clock time. A `ManagerAdmin` may advance the clock by supplying a `to_iso8601` timestamp, and the response reports the clock's new value as `current_utc`. Timestamps stamped by the system, such as an inspection's `completed_at` or a disbursement's `sent_at`, are always drawn from this clock.

The daily operational checkpoint is an explicit, admin-driven sweep rather than a background timer. When a `ManagerAdmin` triggers the daily cycle, the system examines every disbursement still in `SENT` status and flips each one whose `sent_at` plus the governing jurisdiction's `stale_check_days` falls strictly before the logical clock — equality alone does not stale-date a check — to `STALE_DATED`, voiding the uncashed check. Each flip releases that disbursement's reservation: the owning tenancy's `reserved_cents` is decremented by the check amount and its `balance_remaining_cents` is recomputed. The sweep response reports how many checks were voided as `stale_dated_count` and lists their identifiers as `stale_dated_disbursement_ids`.

### 2.6. Monetary Values and Precision

All monetary quantities are represented as integer cents; the API never carries fractional cents, floats, or decimal strings for money. Wherever a computation produces a fractional cent — deposit interest and depreciated damage charges are the two cases — the result is rounded half-up to the nearest whole cent at the point the rule specifies, and the rounding order is part of the contract: per-line amounts are rounded at line creation and only then summed into totals. Fee schedules, deduction amounts, balances, and exposure figures are all stored and returned as these integer-cent values.

### 2.7. The Deposit Ledger Invariant

Each tenancy behaves as a small ledger whose parts must always reconcile. The tenancy's `balance_remaining_cents` is defined at all times as its `deposit_cents`, plus `interest_accrued_cents`, minus `total_deductions_cents`, plus `released_cents`, minus `refund_paid_cents`, minus `escheated_cents`, minus `reserved_cents`. The terms are themselves aggregates maintained by the system: `total_deductions_cents` sums the `amount_cents` of the tenancy's deduction lines in `BILLED` status; `pending_deductions_cents` sums those still in `DRAFT`; `released_cents` mirrors the current statement's released amount; `reserved_cents` sums `REFUND` disbursements still in `SENT` status (funds in flight); `refund_paid_cents` sums `CASHED` refund amounts; and `escheated_cents` sums amounts from disbursements that reached `ESCHEATED`. Penalty money lives outside the deposit ledger: cashed penalty checks accumulate into `penalty_paid_cents` and never touch the balance equation. This invariant is re-evaluated on every mutation of the tenancy's money fields.

### 2.8. Optimistic Concurrency Control

Exactly one write operation in the API is guarded by optimistic concurrency control: the creation of a deposit statement. The request must carry `expected_tenancy_version`, holding the `version` of the target tenancy as the client last observed it. If the tenancy's current `version` no longer matches — because another writer has advanced it since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building a statement on top of state it has not observed. A successful statement creation itself increments the tenancy's `version`, so a second create carrying the previously observed value is necessarily working from stale state and must fail. No other endpoint takes a version field; all other writes proceed without an OCC check.

### 2.9. Validation Order and Nested Resource Retrieval

Every request passes through a fixed validation pipeline, and the ordering is observable behavior. The checks are evaluated in this sequence: first, the presence and well-formedness of the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization, including the tenant-ownership comparison (`ERR_FORBIDDEN_FOR_ROLE`); third, request-body schema — the body must parse and contain all required fields with well-typed, non-negative values, and this schema check deliberately precedes any identifier resolution (`ERR_INVALID_REQUEST`); fourth, existence of every referenced resource id, validated left-to-right so the first missing identifier in the path or body determines the `ERR_NOT_FOUND` rejection; fifth, state preconditions on the target resources (the state-guard errors such as `ERR_INVALID_STATE_TRANSITION` and `ERR_TENANCY_NOT_VACATED`); sixth, temporal business rules such as the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`); seventh, referential-liveness rules such as current-statement and move-in-item linkage (`ERR_STATEMENT_SUPERSEDED`, `ERR_ITEM_LINK_MISMATCH`); eighth, uniqueness and scheduling constraints (for example `ERR_UNIT_OCCUPANCY_OVERLAP` and `ERR_INSPECTOR_SCHEDULE_CONFLICT`); ninth, compliance-documentation requirements (`ERR_PHOTO_DOCUMENTATION_REQUIRED`, `ERR_ITEM_NOT_ASSESSED`); and tenth, money-sanity limits (`ERR_AMOUNT_EXCEEDS_BALANCE` and its siblings). Because existence is checked left-to-right, a request addressing a nested resource under a non-existent parent reports the parent as missing before the child is ever considered.

### 2.10. Jurisdictional Rule Profiles

Statutory variation is modeled as configuration. A `JurisdictionProfile` captures, under a unique `code` (attempting to register a duplicate code is rejected with `ERR_DUPLICATE_JURISDICTION_CODE`), the complete rule set for one jurisdiction: `deposit_return_deadline_days`, the calendar days after move-out within which the itemized statement must be issued; `dispute_window_days`, the calendar days after statement issuance during which a tenant may open a dispute; `interest_required`, whether deposits must accrue interest at all; `annual_interest_rate_bp`, the annual deposit interest rate expressed in basis points; `interest_basis`, selecting the interest variant as either `ACTUAL_DAYS` or `WHOLE_YEARS`; `stale_check_days`, the number of days after `sent_at` when an uncashed disbursement becomes stale; `small_claims_cap_cents`, the maximum total tenant recovery in small claims; `bad_faith_multiplier`, the damages multiplier applied when a statement was issued late; `lock_change_allowed`, whether a lock-change charge may be billed for unreturned keys; and `allow_actual_cost_charge`, whether a documented actual repair cost may be charged instead of depreciated value. Every property is bound to exactly one profile through its `jurisdiction_profile_id`, and that binding governs deadlines, interest, penalties, and charge eligibility for everything that happens at the property.

## 3. Business Logic & Workflows

### 3.1. Configuring the Portfolio: Properties and Units

Before any tenancy can exist, a `ManagerAdmin` builds out the portfolio. A property is registered with a display `name`, a street `address`, the `jurisdiction_profile_id` that binds it to a rule profile, and its fee schedule: `key_charge_cents` per unreturned key, `fob_charge_cents` per unreturned fob, and `lock_change_cents` as the lock-change charge billed when at least one key is unreturned and the jurisdiction permits it. The property list can be filtered by `jurisdiction_profile_id`.

Beneath each property, units are created with a `property_id`, a `unit_number` label, and the two depreciation schedules that later drive damage charges: `carpet_installed_on` (the date the current carpet was installed, in `YYYY-MM-DD` form) paired with `carpet_life_years`, and `paint_applied_on` paired with `paint_life_years`. Each life in years is converted to days using a 365-day year when depreciation is computed. A unit also exposes a derived `occupancy_status`, recomputed on tenancy creation and on every tenancy status change, considering only that unit's tenancies that have not reached `SETTLED` or `ESCHEATED`: if any such tenancy is `OCCUPIED` the unit is `OCCUPIED`; otherwise, if any such tenancy is `NOTICE_GIVEN` or `PENDING_MOVE_IN` the unit is `RESERVED`; otherwise the unit is `AVAILABLE`. A freshly created unit therefore reads `AVAILABLE`. The unit list can be filtered by `property_id`.

### 3.2. Onboarding a Tenancy and Documenting Move-In

A `PropertyManager` opens a tenancy on a unit by supplying the `unit_id`, the `tenant_display_name`, the lease dates `lease_start_on` and `lease_end_on`, the `monthly_rent_cents`, the `deposit_cents` held, and the counts `keys_issued` and `fobs_issued` handed over at move-in; an optional `forwarding_address` records where the eventual refund should be mailed and may be set until the statement is issued. The lease period is a half-open interval that includes the start date and excludes the end date: two tenancies on the same unit whose intervals merely touch — one ending on the day the next begins — are adjacent and allowed, while any genuine overlap is rejected with `ERR_UNIT_OCCUPANCY_OVERLAP`. A new tenancy starts in `PENDING_MOVE_IN` with `keys_returned` and `fobs_returned` at zero and every money counter at zero, and its creation immediately recomputes the unit's `occupancy_status` — a pending move-in already counts as `RESERVED`. The tenancy list can be filtered by `unit_id` and by `status`.

Condition documentation happens through inspections. A `PropertyManager` schedules an inspection by naming the `tenancy_id`, the `kind` (`MOVE_IN` or `MOVE_OUT`), the `inspector_user_id` of the field inspector who will perform it, and the appointment window `scheduled_start_at` through `scheduled_end_at`. A new inspection is born in `DRAFT`. Inspector calendars are protected: the windows of an inspector's `DRAFT` inspections are closed intervals that must not touch or overlap, so a new window conflicts — and is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT` — whenever the new start falls at or before an existing window's end while that existing window's start falls at or before the new end; mere adjacency at an endpoint therefore already counts as a conflict. The inspection list can be filtered by `tenancy_id`, `inspector_user_id`, or `status`.

Once scheduled, the assigned `Inspector` records one condition item per area or surface: an `area_name` such as living_room_carpet, a `category` of `CARPET`, `PAINT`, or `OTHER` (which later selects the depreciation schedule), an observed `condition` of `NEW`, `GOOD`, `FAIR`, `WORN`, `DAMAGED`, or `MISSING`, and a `photo_count` of attached condition photos. Photographic evidence is mandatory for anything below move-in-ready: an item whose condition is `WORN`, `DAMAGED`, or `MISSING` must carry a `photo_count` of at least one, or the item write is rejected with `ERR_PHOTO_DOCUMENTATION_REQUIRED`. Each item also carries a `determination` — `UNASSESSED` by default, later set to `NORMAL_WEAR` or `TENANT_DAMAGE` — and optional `notes`. Move-out items may point back through `linked_move_in_item_id` to the matching item from the same tenancy's `COMPLETED` move-in inspection; a link pointing anywhere else — an item of another tenancy, or of an inspection that never reached `COMPLETED` — is rejected with `ERR_ITEM_LINK_MISMATCH`. Two damage-pricing inputs ride on the item: `replacement_cost_cents`, which is required whenever the determination is `TENANT_DAMAGE` (its absence is an `ERR_INVALID_REQUEST`), and `actual_repair_cents`, the documented actual repair cost that selects the actual-cost charging variant where the jurisdiction allows it. Items may only be added while the inspection is still `DRAFT`, and the item list can be filtered by `inspection_id` or `linked_move_in_item_id`.

Completing the move-in inspection is the gate that hands the unit to the tenant. An `Inspector` completes a `DRAFT` inspection of kind `MOVE_IN` only while its tenancy is `PENDING_MOVE_IN`; any other tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION`, and every item must still satisfy the photo-documentation rule at completion time. Completion moves the inspection itself from `DRAFT` to `COMPLETED`, stamps `completed_at` from the logical clock, sets the tenancy's `move_in_on` to the clock's date, moves the tenancy from `PENDING_MOVE_IN` to `OCCUPIED`, and recomputes the unit to `OCCUPIED`. Completing an inspection also supersedes any prior `COMPLETED` inspection of the same tenancy and kind, keeping only the freshest documentation authoritative.

### 3.3. Notice to Vacate and Key Returns

When the tenant gives notice, a `PropertyManager` records it against an `OCCUPIED` tenancy: the tenancy moves from `OCCUPIED` to `NOTICE_GIVEN`, `notice_given_on` is stamped with the logical clock's date, the tenancy's `version` increments, and the unit's derived occupancy flips to `RESERVED`.

Key and fob returns are tracked as absolute running counts, not deltas. While the tenancy is `OCCUPIED` or `NOTICE_GIVEN` — and only then — a `PropertyManager` may record the absolute `keys_returned` and `fobs_returned` tallies; each accepted write increments the tenancy's `version`. A returned count that exceeds the corresponding issued count is rejected with `ERR_RETURN_COUNT_EXCEEDS_ISSUED`. Once the tenancy reaches `VACATED` the books on physical returns close: the counts snapshotted at move-out completion are the final word for the key, fob, and lock charges described below.

### 3.4. Move-Out Completion: Assessment and the Deduction Cascade

The move-out inspection mirrors the move-in one but carries far more weight. An `Inspector` completes a `DRAFT` inspection of kind `MOVE_OUT` only while its tenancy is `NOTICE_GIVEN`; completion against any other tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION`. Two documentation gates apply on top of the photo rule: every single item must have been assessed — a `determination` still reading `UNASSESSED` blocks completion with `ERR_ITEM_NOT_ASSESSED` — and the photo rule is re-checked, so an undocumented `WORN`, `DAMAGED`, or `MISSING` item blocks completion with `ERR_PHOTO_DOCUMENTATION_REQUIRED`.

Completion sets `completed_at`, sets the tenancy's `move_out_on` to the logical clock's date — the anchor for both the statutory deadline and the interest cutoff — moves the tenancy from `NOTICE_GIVEN` to `VACATED`, recomputes the unit back to `AVAILABLE`, and then fires a three-link deduction cascade. First, the system creates deduction lines: one per item whose determination is `TENANT_DAMAGE` and whose computed charge is greater than zero, plus the key, fob, and lock lines derived from the unreturned counts. Second, each created line recomputes the tenancy's `pending_deductions_cents`, the running sum of `DRAFT` deduction amounts. Third, that change cascades into the tenancy's `DRAFT` statement when one exists, refreshing its `projected_deductions_cents` (which mirrors the tenancy's pending total while the statement is in draft) and its `projected_refund_cents` (the deposit plus accrued interest minus the projected deductions).

Damage charges follow a straight-line residual schedule against a 365-day year. For a `CARPET` item the installation date is the unit's `carpet_installed_on` and the expected life in days is `carpet_life_years` times 365; for a `PAINT` item the analogous `paint_applied_on` and `paint_life_years` apply. The item's age in days is the span from its installation date to `move_out_on`, and the residual fraction is the life remaining — the life in days minus the age in days, floored at zero so an item at or beyond its end of life has no residual — divided by the life in days. The default `DEPRECIATED` variant charges the item's `replacement_cost_cents` multiplied by that residual fraction, rounded half-up to whole cents, so the charge shrinks with age and reaches zero at end of life. The `ACTUAL_COST` variant applies only when the jurisdiction's `allow_actual_cost_charge` flag is set and the item carries a documented `actual_repair_cents`: the charge is then the lesser of `actual_repair_cents` and `replacement_cost_cents`, with no depreciation for age. Items in the `OTHER` category have no schedule and are charged at full `replacement_cost_cents`. A determination of `NORMAL_WEAR` never creates a deduction, and a computed charge of exactly zero creates no line either. System-created damage lines record their origin in `inspection_item_id` and carry the source `MOVE_OUT_DAMAGE`; each such line's `amount_cents` is the system-computed charge, its `description` is carried onto the eventual statement, and its `quantity` is one.

After damage lines come the turnover-hardware charges, computed from the snapshot counts: the missing keys are `keys_issued` minus `keys_returned`, and the missing fobs are `fobs_issued` minus `fobs_returned`. When at least one key is missing, a line with source `KEY_NOT_RETURNED` is created whose `quantity` is the missing-key count and whose `amount_cents` is that count multiplied by the property's `key_charge_cents`. When at least one fob is missing, a `FOB_NOT_RETURNED` line is created symmetrically from the missing-fob count and `fob_charge_cents`. The lock-change branch is conditional on both facts: only when at least one key is missing and the jurisdiction's `lock_change_allowed` is set does a `LOCK_CHANGE` line appear, always with `quantity` one and `amount_cents` equal to the property's `lock_change_cents`.

The same completion also runs deposit interest accrual. When the governing jurisdiction's `interest_required` is false, no interest accrues and `interest_accrued_cents` stays zero. Under the `ACTUAL_DAYS` basis, interest accrues for the exact whole-day span from `move_in_on` through `move_out_on`, including partial years: the accrued amount is `deposit_cents` multiplied by `annual_interest_rate_bp` divided by 10000, multiplied by the number of days, divided by 365, with a single round half-up to whole cents at the end. Under the `WHOLE_YEARS` basis, only completed 365-day years accrue: the number of completed years is the day span divided by 365 rounded down, the per-year interest of `deposit_cents` times `annual_interest_rate_bp` divided by 10000 is rounded half-up to whole cents once per completed year, and those per-year amounts are then summed — the rounding order is pinned, so the system must not multiply the years by the unrounded annual amount and round once. The result is stored as the tenancy's `interest_accrued_cents`.

Not every charge comes from the inspection. While the tenancy is `NOTICE_GIVEN` or `VACATED`, a `PropertyManager` may record manual deductions — sources `UNPAID_RENT`, `CLEANING`, or `OTHER` — by supplying the `tenancy_id`, the `source`, a statement-ready `description`, and the `amount_cents`, which is copied from the input rather than computed. Manual lines are born in `DRAFT` with `quantity` one, and each creation recomputes `pending_deductions_cents` and, through it, the draft statement's projections. Attempting to add a manual deduction in any other tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION`. The deduction list can be filtered by `tenancy_id`, `inspection_item_id`, `statement_id`, or `status`.

### 3.5. The Deposit Statement: Issuance, Deadline, and Reopening

The itemized deduction statement is the document the statute cares about. A `PropertyManager` creates one for a tenancy in `NOTICE_GIVEN` or `VACATED` — creation against any other tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION` — by naming the `tenancy_id` and the OCC guard `expected_tenancy_version` described in §2.8, a mismatch producing `ERR_STALE_VERSION`. Only one active statement may exist per tenancy: if a `DRAFT` or `ISSUED` statement already exists, creation is rejected with `ERR_STATEMENT_ALREADY_ACTIVE`. Creating against a tenancy whose previous statement is `DISPUTED` is the deliberate create-with-supersede path: the predecessor flips to `SUPERSEDED`, any active dispute riding on it is withdrawn, and the new statement takes the next per-tenancy `statement_seq` (the sequence starts at one and increments per tenancy, providing the ordering key for supersession and for identifying the current statement). A new statement is born in `DRAFT` with `refund_due_cents` reading zero and its `projected_deductions_cents` and `projected_refund_cents` shadowing the tenancy's live pending figures until issuance. The statement list can be filtered by `tenancy_id` and `status`.

Issuance is the statutory moment, and it requires the tenancy to be `VACATED`; issuing earlier is rejected with `ERR_TENANCY_NOT_VACATED`. At issuance the system stamps `issued_at` from the logical clock, computes `deadline_on` as `move_out_on` plus the jurisdiction's `deposit_return_deadline_days`, and sets the `late` flag: issuance is timely when the calendar date of `issued_at` is on or before `deadline_on`, and `late` is true exactly when the issuance date falls after `deadline_on`. Every `DRAFT` deduction line of the tenancy is then swept to `BILLED` with its `statement_id` set to this statement — deductions are billed even when the statement is late, because lateness is exposed through the `late` flag and punished through the small-claims multiplier rather than by forfeiting the charges. The statement's totals are computed at this point: `interest_cents` snapshots the tenancy's accrued interest, `deduction_total_cents` sums the swept lines (each already rounded to cents at creation, then summed), and `refund_due_cents` is the deposit plus `interest_cents` minus `deduction_total_cents`. The tenancy's `total_deductions_cents` and `pending_deductions_cents` are recomputed accordingly, and the tenancy's `version` increments.

A statement under dispute can be pulled back for revision: reopening a `DISPUTED` statement — which requires an active dispute in `OPEN`, `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS` to exist — is a compensating action that returns the statement to `DRAFT`. Its `BILLED` lines revert to `DRAFT` with `statement_id` cleared, `released_cents` resets to zero, `refund_due_cents` resets to zero, `issued_at`, `deadline_on`, and `late` are cleared, the active dispute moves to `WITHDRAWN`, and the tenancy's deduction counters and `version` are recomputed. Reopening a statement that is not `DISPUTED` is rejected with `ERR_INVALID_STATE_TRANSITION`.

Between issuance and settlement the statement responds automatically to events around it. Opening a dispute against an `ISSUED` statement moves it to `DISPUTED`; when the active dispute later reaches `CLOSED_AGREED` or `COURT_RESOLVED`, the statement returns from `DISPUTED` to `ISSUED` with its `refund_due_cents` recomputed from the updated `released_cents`; and when the refund has actually been paid — `refund_paid_cents` reaching at least `refund_due_cents` with no dispute of this statement in `OPEN`, `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS` — the statement settles to `SETTLED`, which bubbles up and moves the tenancy from `VACATED` to `SETTLED`.

### 3.6. Disputes and Small-Claims Escalation

A `Tenant` disputes a statement by naming its `statement_id`, the `disputed_amount_cents` — the portion of the deduction total being challenged — and a free-text `reason`. The target statement must be `ISSUED` or `DISPUTED` (otherwise `ERR_STATEMENT_NOT_DISPUTABLE`), and the dispute must arrive within the statutory window: the creation date must fall on or before the statement's issuance date plus the jurisdiction's `dispute_window_days`, or the attempt is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. The disputed amount must be at least one cent and no more than the statement's `deduction_total_cents` (`ERR_DISPUTE_AMOUNT_INVALID`), at most one dispute per statement may sit in `OPEN`, `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS` (`ERR_DISPUTE_ALREADY_OPEN`), and the acting tenant's identity must equal the statement's tenancy — the dispute copies its `tenancy_id` from the statement at creation. A successfully opened dispute starts in `OPEN` and pushes the statement from `ISSUED` to `DISPUTED`. The dispute list can be filtered by `statement_id`, `tenancy_id`, or `status`.

The manager's first response is a counter-offer: a `PropertyManager` records `counter_amount_cents`, the amount of the disputed portion the manager intends to keep, which may not exceed the disputed amount (an over-large counter is an `ERR_INVALID_REQUEST`). The dispute moves from `OPEN` to `MANAGER_COUNTERED`. From there the tenant has two roads. Accepting the counter — an action only the owning `Tenant` may perform, with the identity check against the dispute's tenancy enforced as `ERR_FORBIDDEN_FOR_ROLE` — closes the dispute as `CLOSED_AGREED`, releases the un-kept remainder (the disputed amount minus the counter amount) into the statement's `released_cents`, and returns the statement to `ISSUED` with `refund_due_cents` recomputed as the deposit plus interest minus the deduction total plus the released amount. Escalating instead — likewise restricted to the owning tenant, and available from either `OPEN` or `MANAGER_COUNTERED` — moves the dispute to `ESCALATED_SMALL_CLAIMS` and computes the court exposure. The exposure base is the `disputed_amount_cents`; when the statement's `late` flag is set, the base is first multiplied by the jurisdiction's `bad_faith_multiplier`; the dispute's `exposure_cents` is then the smaller of that base and the jurisdiction's `small_claims_cap_cents`.

Court resolution is recorded by a `PropertyManager` supplying `awarded_amount_cents`, the portion of the disputed amount awarded back to the tenant, which may not exceed the disputed amount (`ERR_AWARD_EXCEEDS_DISPUTED`). Resolution moves the dispute from `ESCALATED_SMALL_CLAIMS` to `COURT_RESOLVED`, adds the awarded amount into the statement's `released_cents`, returns the statement to `ISSUED`, and recomputes `refund_due_cents`. When the statement was late, resolution additionally manufactures the penalty: the tenant's total recovery is the smaller of the dispute's `exposure_cents` and the awarded amount multiplied by the `bad_faith_multiplier` (or simply the awarded amount when the statement was not late); the recovery minus the awarded amount is the penalty portion, and whenever that penalty is greater than zero the system automatically creates a `PENALTY` disbursement for it in `SENT` status. Penalty money is tracked outside the deposit ledger through `penalty_paid_cents`. Disputes also end without agreement when the ground shifts beneath them: reopening or superseding the statement moves an active dispute — whether `OPEN` or `MANAGER_COUNTERED` — to `WITHDRAWN`.

### 3.7. Disbursements, Stale Checks, and Escheatment

Money leaves the system through disbursements. A `PropertyManager` creates one by supplying the `tenancy_id`, the `statement_id`, the `kind` (`REFUND` or `PENALTY`), the `amount_cents`, and the `payee_name` on the check. The referenced statement must be the tenancy's current statement — the one with the latest `statement_seq`, never a superseded one — or creation is rejected with `ERR_STATEMENT_SUPERSEDED`; and that current statement must be `ISSUED` or `SETTLED`, so writing a check against a `DRAFT` (or dispute-locked) current statement is rejected with `ERR_INVALID_STATE_TRANSITION`. A `REFUND` may not exceed the tenancy's `balance_remaining_cents` (`ERR_AMOUNT_EXCEEDS_BALANCE`); a `PENALTY` is exempt from that balance check because it is paid outside the deposit ledger. A created disbursement starts in `SENT` with `sent_at` stamped from the logical clock — checks are considered mailed immediately — and a `REFUND` immediately reserves its amount by adding it to the tenancy's `reserved_cents`, shrinking the remaining balance until the check clears. The disbursement list can be filtered by `tenancy_id`, `statement_id`, or `status`.

When the tenant deposits the check, a `PropertyManager` marks the `SENT` disbursement cashed: `cashed_at` is stamped from the logical clock, the reservation is released by subtracting the amount from `reserved_cents`, and the kind determines the ledger effect — a `REFUND` adds its amount to `refund_paid_cents`, while a `PENALTY` adds to `penalty_paid_cents`. Cashing a refund can close the loop: when `refund_paid_cents` reaches at least the statement's `refund_due_cents` and no dispute of that statement is in `OPEN`, `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS`, the statement moves from `ISSUED` to `SETTLED` and the tenancy bubbles up from `VACATED` to `SETTLED`.

Checks go wrong in both directions of time. A returned or stop-payment check is reversed by a `PropertyManager`, moving a `CASHED` disbursement to `REVERSED` and compensating the paid counters — a reversed refund subtracts from `refund_paid_cents`, a reversed penalty from `penalty_paid_cents`. When the tenancy had already settled and the reversal drags `refund_paid_cents` back below the statement's `refund_due_cents`, settlement unwinds: the statement reverts from `SETTLED` to `ISSUED` and the tenancy from `SETTLED` back to `VACATED`. In the other direction, a check the tenant never cashes ages through the daily ops cycle into `STALE_DATED` (§2.5), and from there a `PropertyManager` escheats it to the state by supplying a non-empty `escheatment_reference` (an empty reference is an `ERR_INVALID_REQUEST`). Escheatment moves the disbursement from `STALE_DATED` to `ESCHEATED`, records the reference, adds the amount to the tenancy's `escheated_cents`, and subtracts it from `balance_remaining_cents`. When an escheat leaves the balance at exactly zero and no disbursements remain in `SENT`, the tenancy itself moves from `VACATED` to its terminal `ESCHEATED` state — the books on the deposit are closed and the unclaimed funds rest with the state.

## 4. Endpoint Definitions

Operations that create new resources (a jurisdiction profile, property, unit, tenancy, inspection, inspection item, deduction, statement, dispute, or disbursement) return a `201 Created` status code. Operations that modify an existing resource in place — completing an inspection, recording notice or key returns, issuing or reopening a statement, driving a dispute through counter/accept/escalate/court-resolution, marking a disbursement cashed, reversing or escheating it, setting the clock, or running the daily cycle — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pm/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | ManagerAdmin |
| POST | `/pm/ops/run_daily_cycle` | Ops-run checkpoint: stale-date aged SENT disbursements and release their reservations | ManagerAdmin |
| POST | `/pm/jurisdiction-profiles` | Create a jurisdiction rule profile | ManagerAdmin |
| GET | `/pm/jurisdiction-profiles/{id}` | Get a jurisdiction profile | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/properties` | Create a property with its key/fob/lock fee schedule | ManagerAdmin |
| GET | `/pm/properties/{id}` | Get a property | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/properties` | List properties | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/units` | Create a unit with carpet/paint depreciation schedules | ManagerAdmin |
| GET | `/pm/units/{id}` | Get a unit | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/units` | List units | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/tenancies` | Create a tenancy; half-open lease interval must not overlap another tenancy on the unit | PropertyManager |
| GET | `/pm/tenancies/{id}` | Get a tenancy | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/tenancies` | List tenancies | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/tenancies/{id}/give_notice` | Record tenant's notice to vacate; OCCUPIED → NOTICE_GIVEN | PropertyManager |
| POST | `/pm/tenancies/{id}/record_key_return` | Record absolute returned key/fob counts while OCCUPIED or NOTICE_GIVEN | PropertyManager |
| POST | `/pm/inspections` | Schedule an inspection; inspector's DRAFT closed windows must not touch or overlap | PropertyManager |
| GET | `/pm/inspections/{id}` | Get an inspection | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/inspections` | List inspections | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/inspections/{id}/items` | Add a condition item with photo count to a DRAFT inspection | Inspector |
| POST | `/pm/inspections/{id}/complete` | Complete an inspection; fires the tenancy transition and, for MOVE_OUT, the deduction cascade and interest accrual | Inspector |
| GET | `/pm/inspection-items/{id}` | Get an inspection item | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/inspection-items` | List inspection items | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/deductions` | Create a manual deduction (UNPAID_RENT, CLEANING, OTHER) while NOTICE_GIVEN or VACATED | PropertyManager |
| GET | `/pm/deductions/{id}` | Get a deduction | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/deductions` | List deductions | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/statements` | Create a DRAFT statement (OCC-guarded); supersedes a DISPUTED predecessor | PropertyManager |
| GET | `/pm/statements/{id}` | Get a statement | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/statements` | List statements | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/statements/{id}/issue` | Issue the itemized statement; sweeps DRAFT deductions to BILLED and stamps the late flag | PropertyManager |
| POST | `/pm/statements/{id}/reopen` | Reopen a DISPUTED statement; compensates billed lines back to DRAFT and withdraws the active dispute | PropertyManager |
| POST | `/pm/disputes` | Tenant opens a dispute against an ISSUED or DISPUTED statement within the dispute window | Tenant |
| GET | `/pm/disputes/{id}` | Get a dispute | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/disputes` | List disputes | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/disputes/{id}/counter` | Manager counter-offers: keeps counter_amount_cents of the disputed portion | PropertyManager |
| POST | `/pm/disputes/{id}/close_agreed` | Tenant accepts the counter; the rest of the disputed portion is released back | Tenant |
| POST | `/pm/disputes/{id}/escalate` | Tenant escalates to small claims; computes exposure_cents | Tenant |
| POST | `/pm/disputes/{id}/resolve_court` | Record the court outcome; awards part of the disputed amount and auto-creates penalty when late | PropertyManager |
| POST | `/pm/disbursements` | Create a disbursement against the current statement; REFUND reserves against the balance immediately | PropertyManager |
| GET | `/pm/disbursements/{id}` | Get a disbursement | ManagerAdmin, PropertyManager, Inspector, Tenant |
| GET | `/pm/disbursements` | List disbursements | ManagerAdmin, PropertyManager, Inspector, Tenant |
| POST | `/pm/disbursements/{id}/mark_cashed` | Mark a SENT disbursement as cashed | PropertyManager |
| POST | `/pm/disbursements/{id}/reverse` | Reverse a CASHED disbursement; compensates paid counters and reopens settlement | PropertyManager |
| POST | `/pm/disbursements/{id}/escheat` | Remit a stale-dated (unclaimed) disbursement to the state | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_JURISDICTION_CODE` | 409 Conflict |
| `ERR_UNIT_OCCUPANCY_OVERLAP` | 409 Conflict |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_TENANCY_NOT_VACATED` | 409 Conflict |
| `ERR_STATEMENT_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_STATEMENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_STATEMENT_SUPERSEDED` | 409 Conflict |
| `ERR_ITEM_LINK_MISMATCH` | 409 Conflict |
| `ERR_ITEM_NOT_ASSESSED` | 409 Conflict |
| `ERR_PHOTO_DOCUMENTATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AMOUNT_EXCEEDS_BALANCE` | 409 Conflict |
| `ERR_DISPUTE_AMOUNT_INVALID` | 409 Conflict |
| `ERR_AWARD_EXCEEDS_DISPUTED` | 409 Conflict |
| `ERR_RETURN_COUNT_EXCEEDS_ISSUED` | 422 Unprocessable Entity |
