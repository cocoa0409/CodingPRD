# Vacant & Abandoned Property Registry API — Product Requirements Document

## 1. Introduction

Municipalities carry the burden of vacant and abandoned properties: securing them against trespass, holding responsible parties accountable for upkeep, recovering the public cost of neglect, and — when a structure cannot be salvaged — moving it toward demolition. This document specifies the API for a Vacant & Abandoned Property Registry that tracks the full compliance lifecycle of such properties. The registry lets responsible owners and foreclosing lenders register the properties they control, records the maintenance standards a jurisdiction enforces, schedules and completes field inspections, cites and escalates code violations, assesses and settles monetary fines, converts unpaid fines into recorded liens, orders nuisance abatement and recovers its cost, refers chronic cases to receivership, and maintains a prioritized demolition list.

The system is, at heart, a compliance-audit ledger. Every monetary consequence a property incurs — a registration fee, an assessed fine, the daily accrual on that fine, a payment, a waiver, a lien conversion, or a recovered abatement cost — is posted as an immutable entry to that property's ledger, and the property's outstanding balance is nothing more than the running signed sum of those entries. Because so many downstream decisions (auto-suspension of a registration, eligibility for the demolition list, the weighting of demolition priority) key off derived monetary and violation totals, the registry must recompute those derived figures deterministically on every mutation. A single property simultaneously advances along two independent axes — its registration lifecycle and its foreclosure lifecycle — and actions on one axis can cascade into violations, fines, liens, and demolition listings that reference the property.

Because the registry drives statutory notices, monetary liability, and the eventual destruction of real property, its behavior must be exact and reproducible. All time-dependent logic reads a server-controlled logical clock rather than wall-clock time, so that fine accrual, lien interest, cure deadlines, and vacancy duration are testable to the day. The sections below define the global contracts every endpoint obeys (Section 2), the business workflows and the rules scattered through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than self-service registrant creation must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is missing on a protected endpoint, or if `X-User-Role` is not one of the roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed and the role is known, but that role is not permitted to perform the requested operation — or the specific body action is not permitted for the role — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The registry recognizes exactly four roles:

- **`Anonymous`** — an unauthenticated caller. The only operation available to `Anonymous` is self-registering a registrant party; that single endpoint does not require the auth headers. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`Registrant`** — an owner or lender party acting on its own properties, fines, and liens. When `X-User-Role` is `Registrant`, `X-User-ID` is the `id` of the acting `Registrant`; ownership checks on any resource that references a `Registrant` compare the resource's `registrant_id` to `X-User-ID`.
- **`CodeOfficer`** — a municipal code-enforcement officer who schedules and completes inspections, and cures, escalates, and fines violations. When `X-User-Role` is `CodeOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`.
- **`ProgramAdmin`** — the registry program administrator, responsible for maintenance standards, dispute adjudication, lien recording and foreclosure, abatement, receivership, demolition, reporting, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Read operations (all `GET` endpoints) are shared by `Registrant`, `CodeOfficer`, and `ProgramAdmin`. Advancing or redeeming a property's foreclosure status is shared by `Registrant` and `ProgramAdmin`. Every other mutating operation is exclusive to exactly one role, as detailed in Section 3 and summarized in the authorized-role column of Section 4. Authorization is evaluated after authentication: a caller whose role is unknown always sees `ERR_UNAUTHENTICATED`, never `ERR_UNAUTHORIZED`.

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

All list endpoints accept two optional pagination parameters. `limit` controls the maximum number of records returned; it defaults to 10, must be at least 1, and may not exceed 100. `offset` controls how many records are skipped from the front of the result set; it defaults to 0 and must be at least 0. Every list endpoint returns records sorted by their `created_at` timestamp in ascending order (oldest first).

For list responses, the `meta` object carries the pagination bookkeeping fields `limit`, `offset`, `total_count`, and `has_more`: `total_count` is the number of records matching the query before pagination is applied, and `has_more` is true when records remain beyond the current page (that is, when `offset` plus the number of returned records is less than `total_count`).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` — a UUID string with no type prefix — at creation. Most resources also carry three common bookkeeping fields: `created_at`, the ISO 8601 UTC instant the resource was first stored (with three fractional digits); `updated_at`, the ISO 8601 UTC instant of the most recent mutation; and `version`, an integer that starts at 1 and is incremented by exactly 1 on every mutation of the resource. Whenever a rule below says a resource's state changes, that change also refreshes `updated_at` and increments `version`, unless explicitly stated otherwise.

Two resource kinds are lightweight records that are never mutated after creation and therefore carry only `id` and `created_at`: a maintenance standard (`MaintenanceStandard`) and a ledger entry (`LedgerEntry`). Neither of these carries `updated_at` and neither carries `version`; there is no versioning or optimistic-concurrency semantics for them. Every other resource kind — registrants, properties, inspections, violations, fines, liens, abatement orders, receivership referrals, and demolition listings — carries the full `created_at`, `updated_at`, and `version` triple.

Note that the timestamps recorded in a resource's own business fields (for example a property's `registered_at`, a fine's `assessed_at`, or a lien's `recorded_at`) are read from the logical clock described in Section 2.5, and are conceptually distinct from the `created_at`/`updated_at` audit timestamps.

### 2.5. The Logical Clock

All time-dependent behavior in the registry reads a single server-controlled logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an administrator sets it, every read returns that default — the system never falls back to real wall-clock time. A `ProgramAdmin` may set the clock to any instant by supplying `to_iso8601`. The clock is the basis for every business timestamp the system stamps — a property's `registered_at`, an inspection's `performed_at`, a violation's `cited_at`, a fine's `assessed_at`, a lien's `recorded_at`, an abatement order's `ordered_at`, and so on — and for every elapsed-time computation: fine accrual, lien interest, violation cure deadlines, vacancy duration, and abatement-window buffers all measure against the current clock reading.

### 2.6. The Property Ledger and Derived Balances

Every property owns an append-only ledger of `LedgerEntry` rows. Each entry records a signed `amount_cents` (positive amounts increase the property's outstanding balance, negative amounts decrease it), an `entry_type` classifying the movement, a polymorphic `source_type` and `source_id` naming the originating entity for audit, an `occurred_at` instant read from the logical clock, and a human-readable `memo`. The `source_type` is one of `PROPERTY`, `FINE`, `LIEN`, or `ABATEMENT_ORDER`, and `source_id` is the id of that originating entity resolved against `source_type` rather than a single-entity foreign key. The `entry_type` is one of seven kinds: `REGISTRATION_FEE`, `FINE_ASSESSED`, `FINE_ACCRUAL`, `FINE_PAYMENT`, `FINE_WAIVED`, `FINE_LIENED`, and `ABATEMENT_RECOVERY`. Of these, `REGISTRATION_FEE`, `FINE_ASSESSED`, `FINE_ACCRUAL`, and `ABATEMENT_RECOVERY` post positive amounts, while `FINE_PAYMENT`, `FINE_WAIVED`, and `FINE_LIENED` post negative amounts.

A property exposes three derived (computed) totals that the system recomputes deterministically rather than storing as independent inputs. The `outstanding_balance_cents` is the signed sum of `amount_cents` across every `LedgerEntry` belonging to the property, recomputed on every ledger insert affecting that property (the ledger is append-only, so no status filter applies and summation order is immaterial). The `lien_balance_cents` is the sum of `principal_cents` across the property's liens whose status is `RECORDED` only — liens that have become `SATISFIED` or `FORECLOSED` no longer contribute — and it is recomputed whenever a lien is recorded, satisfied, or foreclosed. The `open_violation_count` is the number of the property's violations whose status is `OPEN` or `ESCALATED`.

Two ledger invariants follow from these definitions and must hold. First, a fine's full life contributes a net of zero to the outstanding balance once it settles by payment: the `FINE_ASSESSED` credit plus the `FINE_ACCRUAL` credit is exactly offset by the `FINE_PAYMENT` debit. Second, lien principal is conserved on the `lien_balance_cents` axis: recording a lien adds its `principal_cents` to the balance, and satisfying or foreclosing that lien removes exactly the same `principal_cents`.

### 2.7. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up (a value at the exact halfway point rounds away from zero to the next whole cent). Where a formula specifies that individual components are rounded before being combined, each component is rounded half up independently and the rounded components are then summed — this ordering is significant and is called out explicitly for fine accrual, lien payoff, and the abatement cost-recovery charge. The single non-integer figure in the system, a demolition listing's `priority_score`, is a number rounded half up to two decimal places.

### 2.8. Optimistic Concurrency Control on Renewal

Renewing a property's registration is guarded by optimistic concurrency control on the property's `version`. A renewal request must carry `expected_property_version`, and the server compares it to the target property's current `version`. If the value the client supplies does not equal the property's current `version` — because a prior renewal, a cascade, or any other mutation has advanced the property since the client last read it — the renewal is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412), rather than silently extending a stale view of the registration. A renewal legitimately supersedes the prior expiry, so a second renewal carrying the version observed before the first renewal is exactly the case this check rejects. Renewal is the only endpoint that takes a version field; no other endpoint accepts or requires `expected_property_version`.

### 2.9. Dual-Axis Property State and Cascade Consistency

A property advances along two fully independent state axes. The `registration_status` axis governs the registration lifecycle and moves among `ACTIVE`, `SUSPENDED`, and the terminal `DEMOLISHED`. The `foreclosure_status` axis governs foreclosure tracking and moves among `NONE`, `NOTICE_OF_DEFAULT`, `LIS_PENDENS`, `AUCTION_SCHEDULED`, and the terminal `REO`. The two axes are advanced and redeemed independently: a change to one never implicitly changes the other except through the explicit cascades described in Section 3.

Whenever an operation mutates more than one resource, every secondary effect is part of the same operation and must complete atomically with the primary change. In particular, marking a property demolished and redeeming a property's foreclosure each cascade into that property's dependent violations, fines, and demolition listings, and settling a fine cascades into the ledger and (for a lien conversion) into a new lien. Each resource touched by a cascade has its own `updated_at` refreshed and its own `version` incremented as a result of that touch. These cascades are specified in full within the relevant workflow narratives in Section 3.

### 2.10. Nested Path Resolution and Validation Ordering

Several endpoints address a child resource through a property in the URL, or address a single resource by its id. Path resources are validated left to right: a missing property in a nested path is reported before anything nested under it is considered, and each resource kind reports its own not-found error — a missing property yields `ERR_PROPERTY_NOT_FOUND`, a missing inspection `ERR_INSPECTION_NOT_FOUND`, a missing violation `ERR_VIOLATION_NOT_FOUND`, a missing fine `ERR_FINE_NOT_FOUND`, a missing lien `ERR_LIEN_NOT_FOUND`, a missing abatement order `ERR_ABATEMENT_ORDER_NOT_FOUND`, a missing receivership referral `ERR_RECEIVERSHIP_NOT_FOUND`, and a missing demolition listing `ERR_DEMOLITION_NOT_FOUND` (all HTTP 404).

Validation checks are applied in a fixed precedence so that a request failing several checks always reports the same, highest-priority error. The order is: (1) authentication (`ERR_UNAUTHENTICATED`); (2) authorization, including whether the specific body action is allowed for the role, such as a lien's `PAY` versus its foreclosure action (`ERR_UNAUTHORIZED`); (3) existence of the path resources, validated left to right (the entity-specific not-found errors above); (4) existence of body foreign keys — the `registrant_id` on property creation resolving to a real registrant (`ERR_REGISTRANT_NOT_FOUND`), and the `property_id` on inspection, abatement-order, receivership-referral, and demolition-listing creation resolving to a real property (`ERR_PROPERTY_NOT_FOUND`); (5) body well-formedness — required fields present, enum values legal, and window fields well-typed (`ERR_VALIDATION`, HTTP 422). Only once all five of these pass does the system evaluate the domain-specific business rules — license requirements, type matching, uniqueness, state legality, temporal windows, fiscal thresholds, and the renewal version check — described alongside the workflows they guard in Section 3. Where several business rules apply to one endpoint, their relative order is stated within that workflow.

## 3. Business Logic & Workflows

### 3.1. Party Registration and Property Onboarding

Participation begins with a responsible party self-registering. Anyone may create a `Registrant` without authentication, supplying a `legal_name`, a `party_type`, an `email`, a `contact_phone`, and a `mailing_address` for statutory notices. The `party_type` classifies the party as either the property `OWNER` or the foreclosing `LENDER`. A lender is a licensed entity, so `license_number` (the state lender license number) must be present when `party_type` is `LENDER`; if it is omitted in that case the registration is rejected with `ERR_LICENSE_REQUIRED`. When `party_type` is `OWNER`, `license_number` carries no value and is left null. A missing required field or an illegal `party_type` value is caught earlier as `ERR_VALIDATION`.

Once a party exists, a `Registrant` registers the vacant or abandoned properties it controls. Registration of a `Property` supplies the `registrant_id` of the responsible party, the county-assessor `parcel_id`, the `street_address`, the field-observed `occupancy_status` (either `VACANT` or `ABANDONED`), and the `registration_type` under which the filing is made (either `LENDER` or `OWNER`). The `registrant_id` must resolve to an existing registrant, or the request fails with `ERR_REGISTRANT_NOT_FOUND`. The `registration_type` must equal the referenced registrant's `party_type`; a filing that claims to be a lender registration against an owner party (or vice versa) is rejected with `ERR_TYPE_MISMATCH`. The `parcel_id` must be unique across all properties; a second property claiming a parcel already on file is rejected with `ERR_DUPLICATE_PARCEL`. When more than one of these business conditions could apply, they are evaluated in this order: the type-match check precedes the parcel-uniqueness check (both, of course, after the generic well-formedness check that would otherwise raise `ERR_VALIDATION`).

A newly registered property starts life on the `ACTIVE` registration axis and the `NONE` foreclosure axis. At creation the system stamps `registered_at` from the logical clock and sets `registration_expires_at` to exactly 365 days after `registered_at`. It also computes the property's one-time `registration_fee_cents` and posts it to the ledger. The registration fee is tiered by filing type and occupancy: the base fee is 20000 cents for a `LENDER` registration and 10000 cents for an `OWNER` registration; if the property's `occupancy_status` is `ABANDONED`, a surcharge equal to 50 percent of that base fee, rounded half up to whole cents, is added, and if the occupancy is `VACANT` no surcharge applies. The `registration_fee_cents` is the base plus this surcharge. The system posts a `REGISTRATION_FEE` `LedgerEntry` whose `amount_cents` is the positive registration fee and then recomputes the property's `outstanding_balance_cents`.

Fetching a single property returns its stored fields together with the three computed figures — `outstanding_balance_cents`, `lien_balance_cents`, and `open_violation_count`. The property list supports filtering and reverse lookup by `registrant_id`, by `registration_status`, and by `foreclosure_status`, alongside the standard `limit` and `offset` pagination parameters; this is how a caller finds every property a given registrant controls. A property's ledger is retrieved as its own list of `LedgerEntry` rows (a reverse lookup on `LedgerEntry.property_id`), likewise paged with `limit` and `offset`.

Renewing a registration extends the property's `registration_expires_at` by a further 365 days beyond its current value and increments the property's `version`. Renewal is available to the `Registrant` and is guarded by the optimistic-concurrency check of Section 2.8: the request must carry `expected_property_version` equal to the property's current `version`, failing which it is rejected with `ERR_STALE_PROPERTY_VERSION`.

**Automatic suspension and reinstatement.** The `registration_status` axis reacts automatically to the property's balance. Whenever a ledger insert leaves the recomputed `outstanding_balance_cents` at or above 100000 cents, an `ACTIVE` property is transitioned to `SUSPENDED` (the boundary is inclusive — a balance of exactly 100000 cents suspends). Conversely, whenever a ledger insert leaves the recomputed balance below 100000 cents, a `SUSPENDED` property is transitioned back to `ACTIVE`, completing the reinstatement cycle. Each such automatic transition refreshes the property's `updated_at` and increments its `version`. These transitions are driven entirely by the system as a side effect of ledger movements; there is no direct suspend or reinstate operation.

### 3.2. Foreclosure Tracking and Redemption

The foreclosure axis is driven by an operation that carries an `action` of either `ADVANCE` or `REDEEM`; it is available to both the `Registrant` and a `ProgramAdmin`. Advancing walks the property forward one stage at a time along the fixed sequence `NONE → NOTICE_OF_DEFAULT → LIS_PENDENS → AUCTION_SCHEDULED → REO`: an `ADVANCE` from `NONE` moves the property to `NOTICE_OF_DEFAULT`, from `NOTICE_OF_DEFAULT` to `LIS_PENDENS`, from `LIS_PENDENS` to `AUCTION_SCHEDULED`, and from `AUCTION_SCHEDULED` to `REO`, which is terminal for this axis. A property whose `registration_status` is `DEMOLISHED` cannot advance its foreclosure status at all; such an attempt is rejected as an invalid state (`ERR_INVALID_STATE`). Attempting to `ADVANCE` a property that is already `REO` has nowhere to go and is rejected with `ERR_FORECLOSURE_TERMINAL`.

Redeeming resets the axis. A `REDEEM` action returns the property's `foreclosure_status` to `NONE` from any of `NOTICE_OF_DEFAULT`, `LIS_PENDENS`, or `AUCTION_SCHEDULED`, and it behaves identically regardless of which of those three stages the property was in. A property that has reached `REO` can no longer be redeemed, and a property already at `NONE` has nothing to redeem; a `REDEEM` in either of those situations is rejected with `ERR_FORECLOSURE_TERMINAL`. Every successful advance or redemption refreshes the property's `updated_at` and increments its `version`.

Redemption also carries a cascade: because reaching the demolition list presumes a distressed foreclosure posture, redeeming a property clears it from that list. Every `DemolitionListing` of the property whose status is `LISTED` or `SCHEDULED` is transitioned to `REMOVED` as part of the same operation, each such listing having its own `updated_at` refreshed and `version` incremented.

### 3.3. Maintenance Standards and Inspections

The jurisdiction's enforceable maintenance standards are configured by a `ProgramAdmin`. A `MaintenanceStandard` carries a short `code` (for example `SEC-01`) that is unique across all standards, a `category` (one of `SECURING`, `LANDSCAPING`, `STRUCTURAL`, `SANITATION`, or `POOL_SAFETY`), a human-readable `description`, a `severity_weight` that is an integer from 1 through 10 inclusive and feeds both condition scoring and demolition priority, a `cure_period_days` that is an integer of at least 1 and sets how long a cited violation of the standard may run before it can be escalated, and a `base_fine_cents` that is an integer of at least 0 and becomes the base amount of any fine assessed for a violation of the standard. Standards are immutable reference records: each carries only an `id` and a `created_at`, with no `updated_at` and no `version`. The standards list can be filtered by `category` and is paged with `limit` and `offset`.

Field inspections are scheduled by a `CodeOfficer`. Scheduling an `Inspection` supplies the `property_id` being inspected, the opaque `inspector_badge` of the assigned inspector, and a window given by `scheduled_start` (inclusive) and `scheduled_end` (exclusive). The `property_id` must resolve to an existing property, or the request fails with `ERR_PROPERTY_NOT_FOUND`. The window must be well-formed with `scheduled_end` strictly after `scheduled_start`; otherwise the request is rejected with `ERR_INVALID_WINDOW`. An inspector cannot be double-booked: if any other `SCHEDULED` inspection bearing the same `inspector_badge` has a window that overlaps the new one, the request is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. Overlap is measured on the half-open interval — the window runs from `scheduled_start` up to but not including `scheduled_end` — so two windows that merely touch, where one ends exactly when the other begins, are permitted. A new inspection begins in status `SCHEDULED` with a null `result`, an empty `failed_standard_codes`, and a null `performed_at`. Inspections may be fetched individually and listed with reverse lookup by `property_id`, by `inspector_badge`, and by `status`.

Completing an inspection is likewise a `CodeOfficer` action and records the outcome. It supplies a `result` of either `PASS` or `FAIL` and, on failure, the `failed_standard_codes` — the `code` values of the standards that failed. The inspection must be in status `SCHEDULED`, or the completion is rejected with `ERR_INVALID_STATE`. The body must be internally consistent: a `PASS` result requires `failed_standard_codes` to be empty, while a `FAIL` result requires `failed_standard_codes` to be non-empty and requires every listed code to match a declared `MaintenanceStandard.code`; a body that violates this is rejected with `ERR_VALIDATION`. On completion the inspection's status becomes `COMPLETED`, its `result` is stored, and `performed_at` is stamped from the logical clock (advancing the inspection `SCHEDULED → COMPLETED`).

A failing inspection cites violations. For each entry in `failed_standard_codes`, the system either creates a new `Violation` in status `OPEN` or reopens the property's existing `CURED` violation of the same standard code, as described in Section 3.4. Each newly cited violation records the `property_id` and the `inspection_id` that produced it, copies the offending standard's `code` into `standard_code`, copies that standard's `severity_weight`, stamps `cited_at` from the clock, and computes its cure deadline as described next.

### 3.4. Violation Lifecycle: Citation, Cure, Escalation, Reopening

A `Violation` moves through the states `OPEN`, `CURED`, `ESCALATED`, `FINED`, and the terminal `VOIDED`; the lifecycle is cyclic, because a cured violation can reopen. Every violation begins `OPEN` when cited. At citation the system fixes the violation's `cure_deadline_at` as the `cited_at` instant plus the cited standard's `cure_period_days` — that is, the deadline is that many days after the violation was cited — and this deadline is the earliest instant the violation may be escalated. A violation exposes its computed `cure_deadline_at` when fetched, and violations can be listed with reverse lookup by `property_id`, by `inspection_id`, and by `status`.

A `CodeOfficer` drives the violation forward through a single operation carrying an `action` of `CURE` or `ESCALATE`. Curing marks the standard corrected: it is allowed from either `OPEN` or `ESCALATED`, sets the violation's status to `CURED`, and stamps `cured_at` from the logical clock (curing an already-escalated violation is a permitted late cure and behaves identically). Escalating is allowed only from `OPEN` and only once the cure period has elapsed: the current clock must be at or after the violation's `cure_deadline_at`. An escalation attempted while the violation is not `OPEN` is rejected as an invalid state (`ERR_INVALID_STATE`); an escalation of an `OPEN` violation attempted before its `cure_deadline_at` is reached is rejected with `ERR_CURE_PERIOD_ACTIVE` — the state check takes precedence, so a violation in the wrong state always reports the invalid-state error rather than the cure-period error. A successful escalation moves the violation `OPEN → ESCALATED`.

Reopening closes the cycle. When a later failing inspection re-cites a standard code for which the property already holds a `CURED` violation, the system does not create a duplicate; instead it reopens that existing violation. Reopening sets its status back to `OPEN`, clears `cured_at`, and re-stamps `cited_at` to the current clock, then recomputes `cure_deadline_at` from that fresh citation instant and the standard's cure period. This `CURED → OPEN` edge means a property that lets a corrected problem recur restarts the cure clock. A violation that is `ESCALATED` may proceed to `FINED` through fine assessment (Section 3.5), and any violation may be voided by the demolition cascade (Section 3.9).

### 3.5. Fines: Assessment, Accrual, Dispute, and Settlement

A `CodeOfficer` assesses a monetary fine against an escalated violation. Assessment requires the violation to be in status `ESCALATED`; an attempt against a violation in any other state is rejected with `ERR_INVALID_STATE`. On success the violation advances `ESCALATED → FINED` and a new `Fine` is created in status `ASSESSED`. The fine records the `violation_id` it punishes and, denormalized for ledger and reporting convenience, the `property_id`; it copies the offending standard's `base_fine_cents` into `base_amount_cents`, stamps `assessed_at` from the logical clock (this is the accrual epoch), and captures the per-day escalation penalty `daily_penalty_cents`, which is 500 cents. The system posts a `FINE_ASSESSED` `LedgerEntry` whose `amount_cents` is the positive `base_amount_cents` and recomputes the property's `outstanding_balance_cents`. A fine may be fetched — its response includes the provisional `accrued_amount_cents` computed to the current clock — and fines can be listed with reverse lookup by `violation_id`, by `property_id`, and by `status`.

**How a fine accrues.** From its `assessed_at` epoch a fine grows with time, and the accrual is computed the same way whether it is read provisionally or frozen at settlement. First determine the number of whole elapsed days from `assessed_at` to the evaluation instant, discarding any partial day. The first 30 of those overdue days each add one `daily_penalty_cents` (500 cents) to the base; every overdue day on or after the 30th day adds twice `daily_penalty_cents` (1000 cents) per day. Concretely, the raw amount is `base_amount_cents`, plus 500 cents for each of the first up-to-30 overdue days, plus 1000 cents for each overdue day beyond the 30th. The accrued figure is this raw amount capped so that it never exceeds three times `base_amount_cents` — once accrual reaches triple the base, it stops growing. This accrual appears in two forms. The **provisional** form evaluates at the current clock, so the value grows as the clock advances; it is exposed as `accrued_amount_cents` and is never written to the ledger. The **finalized** form evaluates at the settlement instant, is frozen into `finalized_amount_cents` (which is null until the fine settles), and is reconciled into the ledger.

**Owner and lender actions.** The `Registrant` acts on its own fine through an operation carrying an `action` of `PAY` or `DISPUTE`, each requiring the fine to be `ASSESSED` (otherwise `ERR_INVALID_STATE`). Paying settles the fine: the system freezes `finalized_amount_cents` to the finalized accrual at the current clock, stamps `paid_at`, and reconciles the ledger with two entries — a `FINE_ACCRUAL` entry whose `amount_cents` is the positive difference between `finalized_amount_cents` and `base_amount_cents` (the interest that accrued since assessment), followed by a `FINE_PAYMENT` entry whose `amount_cents` is the negative `finalized_amount_cents`. The fine advances `ASSESSED → PAID` and the property's `outstanding_balance_cents` is recomputed. As Section 2.6 notes, these three entries together (assessment, accrual, payment) leave the fine's net contribution to the balance at zero. Disputing instead moves the fine `ASSESSED → DISPUTED`: the system stamps `disputed_at` and stores the supplied `dispute_reason`, leaving the accrual epoch untouched.

**Adjudication.** A `ProgramAdmin` resolves a disputed fine through an operation carrying a `decision` of `DENY` or `WAIVE`, each requiring the fine to be `DISPUTED` (otherwise `ERR_INVALID_STATE`). Denying the dispute reverts the fine `DISPUTED → ASSESSED`, leaving the `assessed_at` accrual epoch unchanged so that accrual resumes as if the dispute had never paused it. Waiving forgives the fine: it moves the fine `DISPUTED → WAIVED`, posts a `FINE_WAIVED` `LedgerEntry` whose `amount_cents` is the negative `base_amount_cents`, and recomputes the property's `outstanding_balance_cents`.

**Conversion to a lien.** A `ProgramAdmin` may convert an unpaid fine directly into a recorded lien. Conversion requires the fine to be `ASSESSED`; an attempt against any other state is rejected with `ERR_INVALID_STATE`. It further requires that the fine's finalized accrual to the current clock be worth at least 25000 cents — a fine whose finalized accrual falls below this floor is rejected with `ERR_LIEN_AMOUNT_TOO_LOW`, and this fiscal-floor check is evaluated only after the state check passes. When both hold, the system freezes `finalized_amount_cents` to that finalized accrual, posts a `FINE_ACCRUAL` entry of the positive difference between `finalized_amount_cents` and `base_amount_cents` followed by a `FINE_LIENED` entry of the negative `finalized_amount_cents`, moves the fine `ASSESSED → LIENED`, and recomputes `outstanding_balance_cents`. As a cascade of the same operation it also records a new lien, described in Section 3.6.

### 3.6. Liens: Recording, Interest, Payoff, and Discharge

A `Lien` comes into being only as the cascade of converting a fine (Section 3.5). The new lien starts in status `RECORDED`, references the encumbered `property_id` and the `source_fine_id` it was converted from, and sets its `principal_cents` to that source fine's frozen `finalized_amount_cents` at recording. It captures an annual interest rate of 1000 basis points into `interest_rate_bps` and stamps `recorded_at` from the logical clock as its interest epoch. Recording the lien increases the property's `lien_balance_cents` by the new `principal_cents`, since a lien contributes to that balance only while `RECORDED`.

**Payoff computation.** A lien accrues simple interest on its principal from `recorded_at`. The daily interest rate is the annual `interest_rate_bps` divided by 10000 (to convert basis points to a fraction) and then divided by 365 days. The number of whole elapsed days is the days from `recorded_at` to the evaluation instant with any partial day discarded. From these the system exposes two payoff figures that differ only in when rounding happens. The authoritative `payoff_amount_cents` (the accrued variant) rounds each single day's interest to whole cents first — one day's interest is `principal_cents` times the daily rate, rounded half up — and then multiplies that rounded per-day interest by the number of days and adds it to `principal_cents`; this round-each-day-then-sum ordering is the pinned order. The informational `payoff_quoted_cents` (the quoted variant) instead multiplies the principal, the daily rate, and the whole number of days together, rounds that full-period interest half up exactly once, and adds it to `principal_cents`. Because the accrued variant absorbs a rounding step every day while the quoted variant rounds only at the end, the two figures diverge by the accumulated per-day rounding remainder. A lien's response exposes both `payoff_amount_cents` and `payoff_quoted_cents` computed to the current clock, and liens can be listed with reverse lookup by `property_id`, by `source_fine_id`, and by `status`.

**Discharge.** A recorded lien leaves the balance in one of two ways, and either way its `principal_cents` leaves the `RECORDED` pool, decreasing the property's `lien_balance_cents` by exactly that principal — the compensating movement to the increase applied at recording. The `Registrant` satisfies its own lien by paying it off: this requires the lien to be `RECORDED` (otherwise `ERR_INVALID_STATE`), moves it `RECORDED → SATISFIED`, and stamps `satisfied_at` from the clock. A `ProgramAdmin` forecloses a lien: foreclosure also requires the lien to be `RECORDED` (otherwise `ERR_INVALID_STATE`) and additionally requires the encumbered property to have reached `REO` on its foreclosure axis — a foreclosure attempt while the property's `foreclosure_status` is anything other than `REO` is rejected with `ERR_PROPERTY_NOT_REO`, a check evaluated only after the lien's state has been confirmed `RECORDED`. A successful foreclosure moves the lien `RECORDED → FORECLOSED` and likewise stamps `satisfied_at`.

### 3.7. Nuisance Abatement and Cost Recovery

When a property's neglect rises to a nuisance, a `ProgramAdmin` orders on-site abatement work against that property. Ordering an `AbatementOrder` supplies the on-site work window as `scheduled_start` (inclusive) and `scheduled_end` (inclusive), together with an `estimated_cost_cents` that is an integer of at least 0; the property is identified in the path and must exist (`ERR_PROPERTY_NOT_FOUND`). Several conditions gate the order and are evaluated in the following relative order. The window must be well-formed with `scheduled_end` strictly after `scheduled_start`, or the order is rejected with `ERR_INVALID_WINDOW`. Next, the new window must not crowd an existing one: if any other non-terminal abatement order on the same property has a window within 24 hours of the new window, the order is rejected with `ERR_ABATEMENT_WINDOW_CONFLICT`. This buffer is measured on the closed interval from `scheduled_start` through `scheduled_end` inclusive, and adjacency falling inside the 24-hour buffer is itself a conflict — two windows must be separated by more than 24 hours. Finally, abatement presupposes an enforcement predicate: the property must have at least one `Violation` whose status is `ESCALATED` or `FINED`, or the order is rejected with `ERR_NO_ABATABLE_VIOLATION`. A new order begins in status `ORDERED` with `ordered_at` stamped from the clock and with `actual_cost_cents`, `admin_fee_cents`, and `recovered_amount_cents` all null. A property's abatement orders can be listed (reverse lookup on `property_id`) filtered by `status`.

Completing an abatement order is also a `ProgramAdmin` action and records what the work actually cost. It supplies `actual_cost_cents`, which must be present and at least 0, and requires the order to be in status `ORDERED` (otherwise `ERR_INVALID_STATE`). On completion the order moves `ORDERED → COMPLETED`, stores `actual_cost_cents`, and the system computes the municipality's cost recovery. The administrative surcharge `admin_fee_cents` is tiered on the actual cost: if `actual_cost_cents` is at most 100000 cents, the fee is 15 percent of `actual_cost_cents`, rounded half up; if `actual_cost_cents` exceeds 100000 cents, the fee is 15 percent of the first 100000 cents plus 10 percent of the portion above 100000 cents, where each of the two tier amounts is rounded half up independently and the two rounded amounts are then summed. The `recovered_amount_cents` is the sum of `actual_cost_cents`, the computed `admin_fee_cents`, and a flat inspection reimbursement of 5000 cents. The system posts an `ABATEMENT_RECOVERY` `LedgerEntry` whose `amount_cents` is the positive `recovered_amount_cents` and recomputes the property's `outstanding_balance_cents`.

### 3.8. Receivership Referral

A `ProgramAdmin` may refer a property to receivership when its foreclosure is under way but not yet advanced. Creating a `ReceivershipReferral` identifies the property in the path and supplies a statutory `ground` — one of `CHRONIC_NUISANCE`, `STRUCTURAL_HAZARD`, or `TAX_DELINQUENCY` — and a proposed `receiver_name`. Referral is permitted only when the property's `foreclosure_status` is either `NOTICE_OF_DEFAULT` or `LIS_PENDENS`; a referral attempted at any other foreclosure stage (including `NONE`, `AUCTION_SCHEDULED`, and `REO`) is rejected with `ERR_FORECLOSURE_STAGE_INVALID`. A new referral begins in status `REFERRED` with `referred_at` stamped from the clock and a null `decided_at`. A property's referrals can be listed (reverse lookup on `property_id`) filtered by `status`.

Deciding a referral is a `ProgramAdmin` action carrying a `decision` of `ACCEPT` or `DENY`, and it requires the referral to still be in status `REFERRED` (otherwise `ERR_INVALID_STATE`). Accepting moves the referral `REFERRED → ACCEPTED` and denying moves it `REFERRED → DENIED`; either decision stamps `decided_at` from the clock.

### 3.9. Demolition Listing and Property Termination

The most severe outcome is placement on the demolition list, and then demolition itself. A `ProgramAdmin` places a property on the list by creating a `DemolitionListing` referencing the `property_id`, which must resolve to an existing property (`ERR_PROPERTY_NOT_FOUND`). Two eligibility gates apply, evaluated in this relative order. First the property must have accumulated at least 3 open violations — that is, its `open_violation_count` must be at least 3 — or the listing is rejected with `ERR_INSUFFICIENT_VIOLATIONS`. Then the property must carry a material balance: its `outstanding_balance_cents` must be at least 50000 cents, or the listing is rejected with `ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD`. A new listing begins in status `LISTED` with `listed_at` stamped from the clock and a null `demolition_date`, and its `priority_score` is computed at listing time. A property's demolition listings can be listed (reverse lookup on `property_id`) filtered by `status`.

**Priority scoring.** The `priority_score` is the sum of four capped components, rounded half up to two decimal places. The severity component is the sum of the `severity_weight` of every violation on the property whose status is `OPEN` or `ESCALATED`, capped at 40. The vacancy component first counts the whole months the property has been vacant — the whole number of 30-day periods from the property's `registered_at` to the current clock, discarding any partial period — then awards 2 points per such month, capped at 20. The balance component awards 1 point for every whole 10000 cents of `outstanding_balance_cents` (that is, the balance in cents divided by 10000, rounded down), capped at 25. The foreclosure component is fixed by the property's `foreclosure_status`: 15 for `REO`, 10 for `AUCTION_SCHEDULED`, 7 for `LIS_PENDENS`, 4 for `NOTICE_OF_DEFAULT`, and 0 for `NONE`. The `priority_score` is the sum of these four components.

Scheduling a listed property for demolition is a `ProgramAdmin` action that supplies a `demolition_date`. It requires the listing to be in status `LISTED` and a `demolition_date` to be present; a scheduling attempt against a listing in any other state is rejected with `ERR_INVALID_STATE`. On success the listing moves `LISTED → SCHEDULED` and stores the `demolition_date`.

**Demolishing the property.** A `ProgramAdmin` marks a property demolished. This is permitted only when the property's `registration_status` is `ACTIVE` or `SUSPENDED`; a property already `DEMOLISHED` cannot be demolished again and the attempt is rejected with `ERR_INVALID_STATE`. Demolition drives `registration_status` to the terminal `DEMOLISHED` and then runs a cascade over the property's dependents, all as part of the same atomic operation. In the first hop, every `Violation` of the property whose status is `OPEN`, `ESCALATED`, or `FINED` is transitioned to `VOIDED`. In the second hop, caused by those violations being voided, every `Fine` belonging to a just-voided violation whose status is `ASSESSED` or `DISPUTED` is transitioned to `WAIVED`, and for each such waiver the system posts a `FINE_WAIVED` `LedgerEntry` of the negative `base_amount_cents` and recomputes the property's `outstanding_balance_cents`. Separately, every `DemolitionListing` of the property whose status is `LISTED` or `SCHEDULED` is transitioned to `DEMOLISHED`. Each resource touched by any hop of this cascade has its own `updated_at` refreshed and its own `version` incremented, and the property's own `updated_at` and `version` are updated as well.

### 3.10. Reporting and Clock Administration

A `ProgramAdmin` retrieves an aggregate registry report that summarizes the portfolio. The report can be narrowed by `registration_status` and by `foreclosure_status`, applied as filters over the properties counted. Its response reports `total_properties` (the number of properties in scope), a `by_registration_status` object breaking that count down by registration axis, a `by_foreclosure_status` object breaking it down by foreclosure axis, the `total_outstanding_balance_cents` and `total_lien_balance_cents` summed across the in-scope properties, and a `demolition_listed_count` of properties currently on the demolition list.

As described in Section 2.5, a `ProgramAdmin` also administers the logical clock: an administrative capability sets the clock to a supplied `to_iso8601` instant, and every time-dependent computation in the workflows above measures against the clock's current reading.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Creating a new resource returns HTTP 201; modifying an existing resource, reading, and administrative actions return HTTP 200. Request bodies, response bodies, and side effects are intentionally omitted here — reconstruct them from the workflow narratives in Section 3. All paths are mounted under the `/registry` prefix.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/registry/_clock/set_current_utc` | Set the logical clock to a supplied instant. | ProgramAdmin |
| POST | `/registry/registrants` | Self-register an owner or lender party. | Anonymous |
| POST | `/registry/properties` | Register a vacant/abandoned property; charges the registration fee. | Registrant |
| GET | `/registry/properties/{id}` | Fetch a property with its computed balances and open-violation count. | Registrant, CodeOfficer, ProgramAdmin |
| GET | `/registry/properties` | List/filter properties (reverse lookup by registrant). | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/properties/{id}/renew` | Renew registration; OCC-guarded on the property version. | Registrant |
| POST | `/registry/properties/{id}/foreclosure` | Advance or redeem the foreclosure status. | Registrant, ProgramAdmin |
| POST | `/registry/properties/{id}/demolish` | Mark the property demolished and run the demolition cascade. | ProgramAdmin |
| GET | `/registry/properties/{id}/ledger` | List the property's ledger entries. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/maintenance-standards` | Create a maintenance standard. | ProgramAdmin |
| GET | `/registry/maintenance-standards` | List maintenance standards. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/inspections` | Schedule an inspection window for a property. | CodeOfficer |
| GET | `/registry/inspections/{id}` | Fetch an inspection. | Registrant, CodeOfficer, ProgramAdmin |
| GET | `/registry/inspections` | List/filter inspections. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/inspections/{id}/complete` | Complete an inspection; FAIL cites violations. | CodeOfficer |
| GET | `/registry/violations/{id}` | Fetch a violation with its computed cure deadline. | Registrant, CodeOfficer, ProgramAdmin |
| GET | `/registry/violations` | List/filter violations. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/violations/{id}/transition` | Cure or escalate a violation. | CodeOfficer |
| POST | `/registry/violations/{id}/fines` | Assess a fine on an escalated violation. | CodeOfficer |
| GET | `/registry/fines/{id}` | Fetch a fine with its provisional accrual. | Registrant, CodeOfficer, ProgramAdmin |
| GET | `/registry/fines` | List/filter fines. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/fines/{id}/transition` | Pay or dispute a fine. | Registrant |
| POST | `/registry/fines/{id}/resolve-dispute` | Deny or waive a disputed fine. | ProgramAdmin |
| POST | `/registry/fines/{id}/record-lien` | Convert an assessed fine into a recorded lien. | ProgramAdmin |
| GET | `/registry/liens/{id}` | Fetch a lien with its computed payoff figures. | Registrant, CodeOfficer, ProgramAdmin |
| GET | `/registry/liens` | List/filter liens. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/liens/{id}/pay` | Satisfy a recorded lien. | Registrant |
| POST | `/registry/liens/{id}/foreclose` | Foreclose a recorded lien; requires the property at REO. | ProgramAdmin |
| POST | `/registry/properties/{id}/abatement-orders` | Order nuisance abatement on a property. | ProgramAdmin |
| GET | `/registry/properties/{id}/abatement-orders` | List a property's abatement orders. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/abatement-orders/{id}/complete` | Complete an abatement order and recover cost. | ProgramAdmin |
| POST | `/registry/properties/{id}/receivership-referrals` | Refer a property to receivership. | ProgramAdmin |
| GET | `/registry/properties/{id}/receivership-referrals` | List a property's receivership referrals. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/receivership-referrals/{id}/decide` | Accept or deny a receivership referral. | ProgramAdmin |
| POST | `/registry/demolition-listings` | Place a property on the demolition list. | ProgramAdmin |
| GET | `/registry/properties/{id}/demolition-listings` | List a property's demolition listings. | Registrant, CodeOfficer, ProgramAdmin |
| POST | `/registry/demolition-listings/{id}/schedule` | Schedule a listed property for demolition. | ProgramAdmin |
| GET | `/registry/reports/registry-summary` | Aggregate registry report. | ProgramAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the relevant narratives of Sections 2 and 3; this table lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_REGISTRANT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_VIOLATION_NOT_FOUND` | 404 |
| `ERR_FINE_NOT_FOUND` | 404 |
| `ERR_LIEN_NOT_FOUND` | 404 |
| `ERR_ABATEMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_RECEIVERSHIP_NOT_FOUND` | 404 |
| `ERR_DEMOLITION_NOT_FOUND` | 404 |
| `ERR_LICENSE_REQUIRED` | 422 |
| `ERR_TYPE_MISMATCH` | 422 |
| `ERR_DUPLICATE_PARCEL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_ABATEMENT_WINDOW_CONFLICT` | 409 |
| `ERR_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_FORECLOSURE_STAGE_INVALID` | 409 |
| `ERR_NO_ABATABLE_VIOLATION` | 409 |
| `ERR_INSUFFICIENT_VIOLATIONS` | 409 |
| `ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD` | 409 |
| `ERR_LIEN_AMOUNT_TOO_LOW` | 409 |
| `ERR_PROPERTY_NOT_REO` | 409 |
| `ERR_FORECLOSURE_TERMINAL` | 409 |
| `ERR_STALE_PROPERTY_VERSION` | 412 |

