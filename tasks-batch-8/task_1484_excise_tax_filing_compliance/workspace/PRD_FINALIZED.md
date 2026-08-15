# Excise Tax Filing & Compliance API — Product Requirements Document

## 1. Introduction

Excise tax compliance lives or dies on timing: rates change mid-quarter, bonded goods cross jurisdictions under tax suspension, deposits fall due twice a month, and a single late filing compounds into penalties. This document specifies an API for an excise tax filing and compliance team responsible for the full cycle of that work — identifying taxable activity and the product class it belongs to, determining the correct rate for each taxing jurisdiction, documenting exemption certificates and bonded movements, preparing returns together with their deposit schedules, claiming credits for bad debts and exports, maintaining registrations and surety bonds, supporting audits with records intact, and absorbing announced rate changes without corrupting in-flight filings.

Two design commitments shape every workflow below. First, history is never rewritten: a filed return pins the rates it actually used, corrections flow through amendments rather than edits, and credit reversals restore liability instead of erasing it. Second, time is explicit — the server runs on a logical clock that administrators advance deliberately, and every expiry, default, and late marker in the system is a consequence of that clock, never of the wall clock. Around those commitments sits a strict segregation-of-duties regime between preparers and reviewers, optimistic concurrency on the two operations whose content can drift under the caller, and an audit records hold that freezes covered periods while an examination runs.

## 2. Global Specifications & System-Wide Principles

This section states the rules that apply uniformly across the API. Behavior that differs per workflow is deferred to §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. A request missing either header, presenting a malformed value, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `ComplianceAdmin`, `TaxAnalyst`, `TaxReviewer`, `JurisdictionAuditor`, and `System`.

A `ComplianceAdmin` is the compliance team administrator: it owns configuration (jurisdictions, product classes, tax rates), registrants, registrations and their lifecycle, bonds and their lifecycle, rate-notice application, deposit waivers, records purges, bonded-movement default declarations, and the logical clock. A `ComplianceAdmin` may also perform preparer and reviewer operations, but segregation of duties still binds the same `X-User-ID` (§2.9).

A `TaxAnalyst` is the compliance preparer: it records taxable activity, classifies and rates events, prepares returns and pays deposits, drafts and submits credit claims, documents bonded movements and exemption certificates, and records rate-change notices. It cannot file returns or approve claims. A `TaxReviewer` is the compliance reviewer and approver: it files submitted returns, approves, denies, or reverses credit claims, verifies or revokes exemption certificates, validates or rejects rate notices, and discharges bonded movements. It cannot prepare the objects it approves. A `JurisdictionAuditor` is an external jurisdiction auditor with read access to everything and write access to audit cases only. `System` names internal automation — the clock sweep and its cascades — appears in no endpoint's authorized role list, and is never a value a client presents in `X-User-Role`.

For each of the four client-facing roles — `ComplianceAdmin`, `TaxAnalyst`, `TaxReviewer`, and `JurisdictionAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, for example as `prepared_by_user_id` or `filed_by_user_id` on a return, as `submitted_by_user_id` or `reviewed_by_user_id` on a credit claim, or as `opened_by_user_id` on an audit case, but it never compares it to any entity's `id`.

Role enforcement is uniform: if the caller's role is declared but not listed among the endpoint's authorized roles, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All read endpoints are open to all four client-facing roles.

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

List endpoints accept two query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order; the deposit list is the single exception, sorted by `due_date` ascending and then `created_at` ascending. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Scheduled Sweeps

The server keeps a logical clock decoupled from the wall clock. Before any client interaction the clock reads exactly 2026-08-01T00:00:00Z. A `ComplianceAdmin` advances it through a test-driving capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`. Advancing the clock runs the daily sweep, which performs every time-based transition in the system: exemption certificates whose validity has passed expire; bonds whose coverage window has closed expire; bonded movements still in transit past their deadline are declared defaulted; unpaid scheduled deposits past their due date are marked late; tax rates activate as their windows begin and retire as their windows end; registrants whose registrations have stayed bond-deficient for a prolonged period are suspended; and ACTUAL-method deposit schedules are computed at each window close. Each of these transitions is described with its owning entity in §3.

### 2.5. Common Resource Properties

Every resource in the API carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation.

Recomputation of a computed field on a resource counts as a mutation of that resource: it refreshes `updated_at` and increments `version`. This applies, for example, when a return's totals are recomputed because an event was rated into it.

### 2.6. Money, Milli-Cent Rates, and Rounding Discipline

All monetary amounts are integers denominated in whole cents — fields named with the `_cents` suffix never carry fractional parts. Tax rates are expressed more finely, in milli-cents (thousandths of a cent) per base unit: a rate of 24.3 cents per gallon is carried as the integer 24300 in `rate_millicents_per_unit`, and one thousand milli-cents make one cent. Converting a rate into a tax therefore multiplies a quantity by milli-cents per unit and divides by one thousand.

Rounding is pinned per taxable event: each event's tax is rounded half-up to whole cents at rating time, and return totals are plain sums of those pre-rounded per-event amounts that are never re-rounded — sum-then-round aggregation is forbidden. Penalties, deposit schedules, credit ceilings, and bond requirements likewise round half-up to whole cents, component by component, at the moment each is computed.

### 2.7. Period Keys and Validity Windows

Return periods are keyed by short strings: `YYYY-MM` (for example `2026-08`) for a jurisdiction with `MONTHLY` return frequency, and `YYYY-Qn` (for example `2026-Q3`) for a `QUARTERLY` one. Audit cases cover inclusive ranges of month buckets, always keyed `YYYY-MM` regardless of frequency. A period key that does not match the shape its context requires is a malformed-body rejection (`ERR_INVALID_REQUEST`).

Tax rate windows are half-open: a rate governs from its `effective_from` instant inclusive until its `effective_to` instant exclusive, and a null `effective_to` leaves the window open-ended. An event dated exactly at a window's `effective_from` belongs to that window; an event dated exactly at its `effective_to` belongs to the next window — or fails rate resolution if none exists. Exemption certificate validity windows behave differently: they are closed intervals, inclusive at both `valid_from` and `valid_to`. Bond coverage windows are likewise inclusive at both ends.

### 2.8. Optimistic Concurrency Control

Exactly two write operations guard against stale content with optimistic concurrency:

- Filing a return requires the request body to carry `expected_return_version` equal to the return's current `version`. A return's version can legitimately advance between submission and filing — for instance when a late taxable event is rated into the return — so if the value presented does not match the current version, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412), because the content the filer reviewed is stale.
- Applying a rate-change notice requires the request body to carry `expected_jurisdiction_version` equal to the jurisdiction's current `version`. Notice application supersedes rates and increments the jurisdiction's version, so a stale presentation is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the rate schedule is stale.

Endpoints not named here do not accept a version field at all.

### 2.9. Segregation of Duties

Preparer and approver must be different operators on every approval-style workflow, compared by `X-User-ID`. The operator who files a return must not be the operator recorded as that return's `prepared_by_user_id`; the operator who approves or denies a credit claim must not be the operator recorded as that claim's `submitted_by_user_id`. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule binds `ComplianceAdmin` operators exactly as it binds everyone else: an administrator who prepared a return cannot file it under the same `X-User-ID`, and an administrator who submitted a claim cannot approve or deny it.

### 2.10. Request Validation Order

When a request would fail several checks, the server evaluates them in a fixed order and reports the earliest failure, so a caller always sees the same error for the same combination of defects. The order is: (1) presence and validity of the authentication headers; (2) role authorization for the endpoint; (3) body well-formedness — required fields present, enum members valid, integer fields at or above their minimums such as `quantity_units` of at least one and amounts of at least one cent; (4) existence — path identifiers validated left to right, then foreign-key identifiers referenced in the body, with the first missing identifier yielding `ERR_NOT_FOUND` (HTTP 404); (5) state legality of the requested transition, including terminal-state lockdown, yielding `ERR_INVALID_STATE` (HTTP 409); (6) optimistic concurrency, yielding `ERR_STALE_VERSION`; (7) segregation of duties; (8) the audit records hold; (9) registration-active requirements; (10) temporal rules in the order period lock, bad-debt earliest date, claim latest date, bond window elapsed, and records retention; (11) uniqueness constraints in the order registrant tax identifier, authority and product codes, registration, return, open amendment, rate window overlap, certificate window overlap, and audit range overlap; (12) movement receipt quantity bounds; (13) registrant-chain referential integrity; (14) registration–jurisdiction consistency; (15) linkability of certificates, movements, claim events, export documentation, and rate resolution; (16) fiscal checks — bond sufficiency, claim ceiling, reversal bound, and open liability.

Body well-formedness covers several domain shapes explicitly and all are rejected with `ERR_INVALID_REQUEST` (HTTP 400): a malformed period key; a `QUARTERLY` jurisdiction declared with `SEMI_MONTHLY` deposit frequency; a tax rate whose `effective_to` does not lie after its `effective_from`; a certificate whose `valid_to` precedes its `valid_from`; an audit range whose `period_end` precedes its `period_start`; a `quantity_units` below one; and an `amount_cents` below one.

### 2.11. Registrant-Chain Scoping and Cross-Entity References

Every operational resource hangs off a registrant chain: a registration ties a registrant to a jurisdiction, and bonds, exemption certificates, bonded movements, taxable events, returns, credit claims, and audit cases all reference a registration and, through it, a registrant. Any referenced entity that belongs to a different registrant chain — a bond issued for another registration, events of another registration pulled into an amendment through `add_event_ids`, and so on — is rejected with `ERR_CROSS_REGISTRANT_REFERENCE` (HTTP 422). This chain check applies when creating registrations, bonds, exemption certificates, bonded movements, taxable events, returns, credit claims, and audit cases, and when including additional events in an amendment.

Two tighter alignment rules guard jurisdiction consistency, each rejected with `ERR_REGISTRATION_JURISDICTION_MISMATCH` (HTTP 422): a taxable event's `jurisdiction_id` must equal the jurisdiction of its registration, and a credit claim's `return_id` must name a return belonging to the same registration and jurisdiction as the claim itself.

## 3. Business Logic & Workflows

### 3.1. Registrants, Registrations, and Surety Bonds

A taxpayer enters the system when a `ComplianceAdmin` creates a registrant with its `legal_name` and its federal employer identification number `fein`. The `fein` must be unique across registrants; a duplicate is rejected with `ERR_DUPLICATE_FEIN`. A new registrant starts `ACTIVE` with `aggregate_open_liability_cents` and `overpayment_balance_cents` both at zero.

Those two balances form the registrant-level ledger. `aggregate_open_liability_cents` is the sum of `taxable_tax_cents` over all of the registrant's returns still in `DRAFT` or `SUBMITTED`, plus the sum of `net_due_cents` over returns that are `FILED` and still `AWAITING_PAYMENT`, across every jurisdiction. `overpayment_balance_cents` accumulates unrefunded excess cash: deposit over-application at filing, plus the negative net due credited when a return's settlement flips to `OVERPAID`, reduced again when a credit reversal flips a settlement back out of `OVERPAID`.

Before a registrant can operate in a jurisdiction, a `ComplianceAdmin` creates a registration carrying `registrant_id`, `jurisdiction_id`, and an elected `deposit_method` of either `SAFE_HARBOR` or `ACTUAL`. At most one non-`REVOKED` registration may exist for a registrant–jurisdiction pair; a conflicting creation is rejected with `ERR_DUPLICATE_REGISTRATION`. A new registration starts `PENDING`, with `bond_coverage_cents` at zero, `requirement_variant` at `STANDARD`, and `bond_required_cents` computed immediately — which, with no filing history, is the standard floor described below. The registration list can be filtered by `registrant_id`, `jurisdiction_id`, or `status`.

The bond requirement is recomputed whenever a registration is activated or reinstated, whenever a return is filed, whenever a bonded movement defaults, whenever a claim is reversed, and whenever a bond is activated, cancelled, or expires. It looks only at the registration's original returns — never amendments — that have reached `FILED`, taken newest period first. Under the `STANDARD` variant, the window is the six most recent such periods: if there is no filed history the requirement is a floor of 1,000,000 cents (ten thousand dollars); otherwise the average `taxable_tax_cents` across those periods is computed, rounded half-up to a whole cent, and the requirement is the larger of three times that average and the floor. The `AGGRAVATED` variant applies whenever any bonded movement of the registration reached `DEFAULTED` or `PARTIAL_DEFAULT`, or any credit claim reached `REVERSED`, within the trailing twelve months: the window widens to the twelve most recent filed periods, the multiplier rises to five, and the floor rises to 2,500,000 cents (twenty-five thousand dollars), so an identical liability history yields a strictly larger requirement whenever the six-month average is positive. The registration exposes the variant currently in force as `requirement_variant` and the resulting requirement as `bond_required_cents`.

Coverage comes from surety bonds. A `ComplianceAdmin` creates a bond with `registration_id`, `surety_name`, `principal_amount_cents`, and a coverage window running inclusively from `effective_from` through `effective_to`; the bond starts as `DRAFT`. Activating a bond requires that its window not be fully elapsed — its `effective_to` must not lie before the current logical date, or the attempt fails with `ERR_BOND_WINDOW_ELAPSED` — and that the registration be in `PENDING`, `ACTIVE`, `BOND_DEFICIENT`, or `SUSPENDED`, failing with `ERR_INVALID_STATE` otherwise. A registration's `bond_coverage_cents` is the sum of `principal_amount_cents` over its `ACTIVE` bonds, recomputed whenever a bond activates, is cancelled, or expires. Cancelling a bond moves it from `ACTIVE` to `CANCELLED`; the clock sweep moves an `ACTIVE` bond whose `effective_to` has passed to `EXPIRED`; either transition recomputes coverage, and if coverage has fallen below the requirement the registration flips to `BOND_DEFICIENT`. Activating a bond can flip a `BOND_DEFICIENT` registration back to `ACTIVE` by the same recomputation. The bond list filters by `registration_id` and `status`. A computed bond-position read for a registration returns its `registration_id`, `bond_required_cents`, `bond_coverage_cents`, `requirement_variant`, and a boolean `deficient` flag.

Activating a `PENDING` registration requires coverage at least equal to the requirement, failing with `ERR_BOND_INSUFFICIENT` otherwise; on success the registration becomes `ACTIVE` and the system mints its `registration_number` in the form REG-<jurisdiction code>-<sequence number>. A `ComplianceAdmin` may suspend an `ACTIVE` registration, moving it to `SUSPENDED`, and may reinstate a `SUSPENDED` or `BOND_DEFICIENT` registration back to `ACTIVE`; reinstatement again requires coverage at least equal to the requirement (`ERR_BOND_INSUFFICIENT`), and reinstating from `SUSPENDED` additionally requires the registrant itself to be `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise. A `BOND_DEFICIENT` registration also returns to `ACTIVE` automatically once coverage again meets the requirement.

Bond deficiency cascades upward on a timer. When any registration stays `BOND_DEFICIENT` for more than thirty consecutive days — evaluated by the clock sweep — the registrant itself becomes `SUSPENDED`, and every `ACTIVE` registration of that registrant transitions to `SUSPENDED` with it. When no registration of the registrant remains `BOND_DEFICIENT`, whether discovered by the sweep or by a bond or registration mutation, the registrant returns to `ACTIVE`, and its `SUSPENDED` registrations whose coverage again meets the requirement return to `ACTIVE` as well. Once every registration of a registrant is `REVOKED` and its `aggregate_open_liability_cents` has reached zero, the system moves the registrant to `CANCELLED`; there is no direct endpoint for that transition.

Revocation is terminal and guarded. Revoking a registration requires that no return of the registration sit in `DRAFT` or `SUBMITTED` and that no `FILED` return remain `AWAITING_PAYMENT`, failing with `ERR_REGISTRATION_HAS_OPEN_LIABILITY` otherwise; revoking an `ACTIVE` registration additionally fails with `ERR_AUDIT_RECORDS_HOLD` while an audit records hold covers any of its periods. When a registration is revoked from `ACTIVE`, its `PENDING_VERIFICATION` and `ACTIVE` exemption certificates transition to `REVOKED`, and its `INITIATED` and `IN_TRANSIT` bonded movements transition to `DEFAULTED` for their full quantity — with the default-assessment cascade of §3.5 suppressed, because the registration is closed.

### 3.2. Jurisdictions, Product Classes, and the Rate Schedule

Configuration begins with taxing authorities. A `ComplianceAdmin` creates each jurisdiction with a unique `code` (for example US-TTB or CA-BOE), a display `name`, a `level` of `FEDERAL`, `STATE`, or `LOCAL`, a `return_frequency` of `MONTHLY` or `QUARTERLY`, and a `deposit_frequency` of `SEMI_MONTHLY` or `MONTHLY`. A `QUARTERLY` jurisdiction must use `MONTHLY` deposit frequency; the mismatched combination is rejected with `ERR_INVALID_REQUEST`. A `SEMI_MONTHLY` deposit frequency splits each month into two windows — window `A` covering days 1 through 15 and window `B` covering day 16 through month end — while `MONTHLY` deposit frequency uses a single window `M` spanning the whole return period. Duplicate jurisdiction codes are rejected with `ERR_DUPLICATE_CODE`. A jurisdiction begins `ACTIVE`; `RETIRED` marks one withdrawn from use.

Product classes follow the same pattern: a `ComplianceAdmin` creates each with a unique `code` (DIESEL, GASOLINE, SPIRITS, and the like), a `description` of what belongs to the class, and a `base_unit` of `GALLON`, `PROOF_GALLON`, `PACK`, or `UNIT`; duplicate codes likewise meet `ERR_DUPLICATE_CODE`. A product class begins `ACTIVE` and may later be `RETIRED`.

Rates attach a `rate_millicents_per_unit` to a jurisdiction–product-class pair over a half-open window. Direct rate creation — supplying `jurisdiction_id`, `product_class_id`, `rate_millicents_per_unit`, `effective_from`, and optionally `effective_to` — exists for initial schedules and for future or gap windows that do not collide with existing ones; superseding an existing window must go through a rate-change notice (§3.3). Windows of the same jurisdiction–product-class pair must never overlap, though adjacency — one window's `effective_from` equalling the prior window's `effective_to` — is allowed; an overlapping creation is rejected with `ERR_RATE_WINDOW_OVERLAP`, and an `effective_to` that does not lie after its `effective_from` is rejected with `ERR_INVALID_REQUEST`. Creating a rate also increments the jurisdiction's `version` by one. The rate's own `status` is derived from its window against the logical clock: `SCHEDULED` when `effective_from` lies in the future, `ACTIVE` when the window contains the current instant, `RETIRED` once `effective_to` has been reached. The clock sweep moves rates from `SCHEDULED` to `ACTIVE` and from `ACTIVE` to `RETIRED`. Notice application can additionally stamp a rate `SUPERSEDED` — either a scheduled rate clamped before it ever activated, or an active rate whose window is cut short — and the active case triggers the retroactive re-rate cascade described in §3.3.

Crucially, that informational `status` plays no part in rate selection. When an event is rated, the system resolves the rate by window containment alone: among rates of the event's jurisdiction and product class, the candidate is the one whose `effective_from` is on or before the `event_date` and whose `effective_to` is either null or after the `event_date`. Because windows are validated non-overlapping at creation and at supersession, at most one candidate can exist; when none does, rating fails with `ERR_NO_APPLICABLE_RATE`. A `RETIRED` or `SUPERSEDED` rate therefore still governs its historical window. The rate list can be filtered by `jurisdiction_id`, `product_class_id`, `status`, `source_notice_id`, or `supersedes_rate_id`.

### 3.3. Rate Change Notices and Retroactive Re-Rating

Rate change monitoring begins when a `TaxAnalyst` or `ComplianceAdmin` records a notice with `jurisdiction_id`, `product_class_id`, the announced `new_rate_millicents_per_unit`, the `announced_effective_from` instant — which may lie in the past (a retroactive change) or in the future — and a `source_reference` citing the bulletin or statute. The server stamps `detected_at` with the current logical clock time, and the notice starts in `DETECTED`. A `TaxReviewer` or `ComplianceAdmin` then verifies the notice against the official bulletin, moving it from `DETECTED` to `VALIDATED`, or rejects a spurious notice, moving it to `REJECTED` from either `DETECTED` or `VALIDATED`. The notice list can be filtered by `jurisdiction_id`, `product_class_id`, `status`, or `applied_rate_id`.

Application is the consequential step, restricted to a `ComplianceAdmin` and guarded by the jurisdiction optimistic-concurrency check of §2.8. Applying a `VALIDATED` notice creates a new tax rate whose `effective_from` equals the notice's `announced_effective_from`, whose `effective_to` equals the clamped prior window's end, whose `source_notice_id` points at the notice, and whose `supersedes_rate_id` points at the rate it replaces; the prior rate's `effective_to` is clamped to the announced start and its status becomes `SUPERSEDED`, and the jurisdiction's `version` increments by one. The retroactive cascade then re-rates every taxable event whose `event_date` falls inside the new window and whose status is `RATED`, but only while its containing return is still in `DRAFT` or `SUBMITTED` — events inside `FILED` returns are never touched, because each filed return's pinned rate snapshot governs them. Every affected return's totals are recomputed and its `version` bumped; the registrant's aggregate liability and the registration's bond requirement are recomputed, which may flip the registration between `ACTIVE` and `BOND_DEFICIENT`. The notice finishes in `APPLIED` with its `applied_rate_id` set to the rate it created.

### 3.4. Recording and Rating Taxable Activity

Taxable activity enters the system as events. A `TaxAnalyst` or `ComplianceAdmin` records a removal, sale, or use with `registration_id`, `jurisdiction_id`, `product_class_id`, `event_date`, and a `quantity_units` of at least one, plus an optional `customer_reference` — needed later if an exemption certificate is to be applied — and an `is_export` flag defaulting to false. Recording requires an `ACTIVE` registration, failing with `ERR_REGISTRATION_NOT_ACTIVE` otherwise; the same registration-active requirement, with the same error, guards classification, rating, bonded movement creation and dispatch, and return creation. The event's `jurisdiction_id` must equal the registration's own jurisdiction, failing with `ERR_REGISTRATION_JURISDICTION_MISMATCH` otherwise. The server derives the event's `period` from the `event_date` and the jurisdiction's return frequency, sets `determination` to `STANDARD`, and opens the event in `DRAFT` with `gross_tax_cents` and `tax_cents` at zero, `return_id` null, and no certificate or movement linkage. The event list can be filtered by `registration_id`, `jurisdiction_id`, `product_class_id`, `return_id`, `exemption_certificate_id`, `bonded_movement_id`, `status`, or `period`.

Classification confirms the product identification, moving an event from `DRAFT` to `CLASSIFIED`. The pairing of product class and jurisdiction must be taxable-identified — meaning a rate exists now or historically for the pair, or the class is exempt-eligible — and a pairing that is not is rejected with `ERR_NO_APPLICABLE_RATE`.

Rating determines the tax, moving an event from `CLASSIFIED` to `RATED`. Beyond an `ACTIVE` registration, rating requires the period of the `event_date` to be open: the latest non-superseded return for the registration, jurisdiction, and period must be in `DRAFT` or `SUBMITTED`, or must have an amendment in `DRAFT` or `SUBMITTED` — otherwise the period is locked and the request fails with `ERR_PERIOD_LOCKED`, because new ratings must then flow through an amendment. Exactly one rate window must contain the `event_date` (§3.2), failing with `ERR_NO_APPLICABLE_RATE` otherwise. The rating request may also link supporting documents. Linking an `exemption_certificate_id` requires the certificate to be `ACTIVE` at rating time, failing with `ERR_CERTIFICATE_NOT_ACTIVE` otherwise, and to actually cover the event: the `event_date` must lie within the certificate's closed validity window, the certificate's `product_class_id` must be null or match the event's class, the `customer_reference` must equal the event's, and an `EXPORT` certificate may only be applied to events whose `is_export` flag is set — any mismatch is rejected with `ERR_CERTIFICATE_NOT_APPLICABLE`. Linking a `bonded_movement_id` requires the movement to belong to the same registration and product class and to be in `IN_TRANSIT` or `RECEIVED`, failing with `ERR_MOVEMENT_NOT_LINKABLE` otherwise.

The tax computation itself resolves one rate window first, then branches. When a bonded movement is linked, the goods move in bond: the event's `gross_tax_cents` is its `quantity_units` multiplied by the resolved rate in milli-cents per unit and divided by one thousand, rounded half-up to whole cents, and its `tax_cents` is zero because the suspension holds. When an exemption certificate is linked instead, the gross is computed identically and `tax_cents` is likewise zero, with the relief recorded as exemption rather than suspension. In the plain case the gross is computed the same way and `tax_cents` equals the gross. Rounding is pinned per event as §2.6 states: each event rounds half-up to whole cents individually, and return totals are plain sums of those per-event amounts. System re-rates during notice application follow the same `STANDARD` determination; the `DEFAULT_ASSESSMENT` determination belongs to movement defaults and is described in §3.5.

Rating has wider consequences. The rated event is automatically included into the return of its period: if no return exists yet for the registration, jurisdiction, and period, the system creates one in `DRAFT` together with its deposit schedule; the containing return's totals are recomputed and its `version` bumped; and the registrant's `aggregate_open_liability_cents` is recomputed.

Corrections run through two loops. Sending a `RATED` event back for correction returns it to `CLASSIFIED`, zeroing its `tax_cents` and `gross_tax_cents`, clearing its exemption and movement links, recomputing the containing return's totals, and bumping the return's `version`; this loop is only available while the containing return is in `DRAFT` — if the return has been `SUBMITTED`, the attempt fails with `ERR_INVALID_STATE` and the submission must be withdrawn first. Once an event is `RETURNED`, correction is possible only inside an open amendment: an amendment of the event's return in `DRAFT` or `SUBMITTED` must exist and include the event, failing with `ERR_INVALID_STATE` otherwise, and no audit records hold may cover the period, failing with `ERR_AUDIT_RECORDS_HOLD`. Such a correction moves the event from `RETURNED` to `ADJUSTED`, again zeroing its tax fields and recomputing the amendment's totals. Re-rating an `ADJUSTED` event applies the same preconditions as ordinary rating — except that the period lock is satisfied by the open amendment itself — and the recomputed values land on the amendment return. When the containing return is filed, its `RATED` events become `RETURNED`; when the containing amendment is filed, its `ADJUSTED` events become `RETURNED`. Finally, an event in `DRAFT` or `CLASSIFIED` may be voided outright, ending in `VOIDED`.

### 3.5. Exemption Certificates and Bonded Movements

Exemption certificates document why a sale to a particular buyer escapes tax. A `TaxAnalyst` or `ComplianceAdmin` creates one with `registration_id` — the jurisdiction is implied by the registration — an optional `product_class_id` (null means the certificate covers every product class), the `customer_reference` of the buyer it covers, a `certificate_type` of `RESALE`, `GOVERNMENT`, or `EXPORT`, and a closed validity window from `valid_from` through `valid_to`, both inclusive. A `valid_to` earlier than `valid_from` is rejected with `ERR_INVALID_REQUEST`. For the same registration, customer reference, and product class (counting null as its own class), certificate windows must keep a gap of at least one day from any other certificate still in `PENDING_VERIFICATION` or `ACTIVE`; windows that touch or overlap are rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP`. A new certificate starts in `PENDING_VERIFICATION`. A `TaxReviewer` or `ComplianceAdmin` then verifies it, moving it to `ACTIVE`, or revokes it — revocation of an unverified certificate is a rejection, ending in `REJECTED`, while revocation of an `ACTIVE` certificate ends in `REVOKED`. The clock sweep expires an `ACTIVE` certificate once the current date passes its `valid_to`, moving it to `EXPIRED`. The certificate list filters by `registration_id`, `product_class_id`, `status`, or `certificate_type`.

Bonded movements document taxable product travelling between bonded facilities under suspension. A `TaxAnalyst` or `ComplianceAdmin` creates one with `registration_id`, `bond_id`, `product_class_id`, `quantity_units`, `origin_facility`, and `destination_facility`, plus an optional `transit_deadline_days` that defaults to thirty days; the bond must belong to the same registration, and creation requires the registration to be `ACTIVE`. The movement starts in `INITIATED`, with `dispatched_at`, `received_at`, and `quantity_received_units` null and `defaulted_quantity_units` zero. The movement list filters by `registration_id`, `bond_id`, `product_class_id`, or `status`.

Dispatch marks the goods shipped, moving the movement from `INITIATED` to `IN_TRANSIT` and stamping `dispatched_at` with the logical clock; dispatch requires an `ACTIVE` registration (`ERR_REGISTRATION_NOT_ACTIVE`) and an `ACTIVE` bond (`ERR_MOVEMENT_NOT_LINKABLE`). Receipt confirmation moves it from `IN_TRANSIT` to `RECEIVED`, stamping `received_at` and recording `quantity_received_units`, which must lie between zero and the shipped `quantity_units` inclusive — anything outside that range is rejected with `ERR_MOVEMENT_QUANTITY_EXCEEDS`. Discharge by a `TaxReviewer` or `ComplianceAdmin` relieves the bond and confirms the suspension with no tax assessed, moving the movement from `RECEIVED` to `DISCHARGED`; it demands exact reconciliation, so the received quantity must equal the shipped quantity — a shortfall must be defaulted first.

Default is where suspension is lost. A `ComplianceAdmin` may declare a default, and the clock sweep declares one automatically when the current date passes `dispatched_at` plus `transit_deadline_days` while the movement is still in transit. From `IN_TRANSIT`, the default is full: `defaulted_quantity_units` equals the shipped `quantity_units` and the movement ends in `DEFAULTED`. From `RECEIVED`, only the shortfall defaults: `defaulted_quantity_units` is the shipped quantity minus the received quantity, which must be strictly less than the shipped quantity, and the movement ends in `PARTIAL_DEFAULT`. Either way, a three-link cascade follows. First, the system creates a taxable event with `determination` `DEFAULT_ASSESSMENT`, quantity equal to the defaulted quantity, `event_date` equal to the default date, its `bonded_movement_id` naming the defaulted movement, and status already `RATED`. Second, that event is auto-included into the `DRAFT` or `SUBMITTED` return of its period — created if missing — and the return's totals are recomputed; if the period is locked (its latest return `FILED` with no open amendment), the event instead stays `RATED` with `return_id` null until an amendment pulls it in through `add_event_ids`. Third, ACTUAL-method deposits of that period are recomputed, and the registration's bond requirement is recomputed, which may flip the `requirement_variant` to `AGGRAVATED`.

A default assessment is deliberately punitive about rate selection. Rather than the event's own product class rate, it uses one and a half times the highest `rate_millicents_per_unit` among all tax rates of the registration's jurisdiction whose windows contain the default date, across every product class; if no window of that jurisdiction contains the default date, the maximum is taken over all rates of that jurisdiction regardless of window. Both the gross and the tax due equal the defaulted quantity multiplied by that punitive rate and divided by one thousand, rounded half-up to whole cents — no exemption or suspension applies. One further default path exists with no cascade at all: when a registration is revoked, its `INITIATED` and `IN_TRANSIT` movements transition to `DEFAULTED` for their full quantity with the default-assessment cascade suppressed, because the registration is closed.

### 3.6. Returns: Preparation, Filing, Settlement, and Amendment

A return gathers a registration's rated activity for one jurisdiction and one period. Returns usually come into being automatically the first time an event is rated into a period, but a `TaxAnalyst` or `ComplianceAdmin` may also create one manually — including a zero-activity return — by supplying `registration_id`, `jurisdiction_id`, and a `period` key matching the jurisdiction's frequency. Manual creation requires an `ACTIVE` registration, and at most one non-`SUPERSEDED` original return may exist per registration, jurisdiction, and period; a conflicting creation is rejected with `ERR_DUPLICATE_RETURN`. A new return starts with `filing_status` `DRAFT` and `settlement_status` `UNFILED`, its `amendment_of_id` null and `amendment_sequence` zero, its `prepared_by_user_id`, `filed_by_user_id`, and `filed_at` unset, all of its money totals at zero, its `pinned_rate_snapshot` an empty list, and its deposit schedule created according to the registration's `deposit_method` (§3.7). The system computes its `due_date` as the first day of the month following the period end, advanced by twenty-four days — the twenty-fifth of the following month for a monthly period. The return list filters by `registration_id`, `jurisdiction_id`, `period`, `filing_status`, `settlement_status`, or `amendment_of_id`.

Two state dimensions then evolve independently. The filing dimension runs `DRAFT` to `SUBMITTED` to `FILED`, with `SUPERSEDED` as its terminal state; the settlement dimension runs from `UNFILED` through `AWAITING_PAYMENT` to `SETTLED` or `OVERPAID`. A settlement transition never changes the filing status, and a filing transition never changes the settlement status directly.

A return's totals aggregate its included events — those whose `return_id` names this return and whose status is `RATED`, `RETURNED`, or `ADJUSTED`, while `DRAFT`, `CLASSIFIED`, and `VOIDED` events are excluded. `event_count` counts the included events; `gross_tax_cents` sums their per-event gross amounts; `taxable_tax_cents` sums their per-event tax due; and `exempted_cents` is the difference between the two sums — the total relieved by exemptions and bonded suspensions. These figures recompute on every membership or event-value change, and since the summands are pre-rounded per-event cents, no further rounding occurs and event order is irrelevant.

Submitting a `DRAFT` return records `prepared_by_user_id` as the caller's `X-User-ID`, moves the return to `SUBMITTED`, and bumps its `version`; withdrawing a submission returns it to `DRAFT`, clears `prepared_by_user_id`, and bumps `version` again. Filing is reserved to a `TaxReviewer` or `ComplianceAdmin` and is protected twice: the optimistic-concurrency check on `expected_return_version` of §2.8, and segregation of duties against the recorded preparer per §2.9. Filing stamps `filed_at` with the logical clock, records `filed_by_user_id`, and computes settlement in a pinned evaluation order that breaks the circular-looking dependency between deposits and penalties.

Settlement proceeds in five pinned steps. First, `taxable_tax_cents` is taken as the current aggregate. Second, `credits_cents` is summed as `applied_cents` minus `reversed_cents` over claims on the return's chain whose status is `APPLIED` or `REVERSED` — for an original return this is always zero at filing, since claims require a `FILED` return, while an amendment carries its chain's credits forward. Third, the deposit waterfall runs: the eligible deposits are the `PAID` deposits of the same registration, jurisdiction, and period, ordered by `due_date` ascending and then `created_at` ascending; a remaining-need figure starts at the taxable tax minus credits, and each deposit in turn contributes the smaller of its `paid_amount_cents` and the remaining need — that portion becomes the deposit's `applied_amount_cents`, the remaining need shrinks accordingly, and any paid cash beyond the portion taken flows into the registrant's `overpayment_balance_cents`. The sum of the portions taken becomes the return's `deposits_applied_cents`, and each deposit touched transitions from `PAID` to `APPLIED` with `applied_return_id` set. Fourth, penalties are computed: an underpayment penalty applies when the taxable tax is positive and the deposits applied fall short of ninety percent of the taxable tax rounded up to the next whole cent — the penalty is ten percent of the difference between the taxable tax and the deposits applied, rounded half-up; and a late-filing penalty applies when the filing date falls after the `due_date` — five percent of the taxable tax for each started thirty-day month of lateness, capped at twenty-five percent of the taxable tax, each rounded half-up. The two components sum to `penalty_cents`. Fifth, `net_due_cents` is the taxable tax minus credits minus deposits applied plus penalties, and it may be negative, which means the return is overpaid.

Filing also freezes the evidence. The `pinned_rate_snapshot` records, for each product class taxed, the `product_class_id`, the `tax_rate_id`, and the `rate_millicents_per_unit` actually used; once filed it is immutable, and it is what later retroactive rate changes leave untouched. Included events in `RATED` or `ADJUSTED` become `RETURNED`. The settlement status is then set from the sign of the net due: positive leaves the return `AWAITING_PAYMENT`, zero settles it as `SETTLED`, and negative marks it `OVERPAID`, with the excess cash handled through the overpayment balance. When the return being filed is an amendment, its parent return's `filing_status` becomes `SUPERSEDED` and the parent's `deposits_applied_cents` carries forward into the amendment. Finally the registrant's aggregate liability and the registration's bond requirement are recomputed.

Settlement continues to move after filing as claims are applied and reversed. When a claim application reduces a return's net due to zero or below, its settlement flips from `AWAITING_PAYMENT` to `SETTLED` or `OVERPAID`, and a negative net due adds its absolute amount to the registrant's `overpayment_balance_cents`. When a claim reversal pushes the net due back above zero, the settlement flips from `SETTLED` or `OVERPAID` back to `AWAITING_PAYMENT`, and a reversal out of `OVERPAID` reduces the overpayment balance by the previously credited excess.

Amendment is how a filed return changes. A `TaxAnalyst` or `ComplianceAdmin` opens an amendment of a `FILED` return, carrying the optimistic-concurrency field `expected_return_version` of §2.8 and optionally `add_event_ids` naming additional events of the same registration to pull in. At most one open amendment — one in `DRAFT` or `SUBMITTED` — may exist per parent return; a second attempt is rejected with `ERR_AMENDMENT_ALREADY_OPEN`. An audit records hold covering the period blocks amendment with `ERR_AUDIT_RECORDS_HOLD`. The amendment is created as a new return in `DRAFT` and `UNFILED`, its `amendment_of_id` naming the parent, its `amendment_sequence` one deeper than its parent's, containing the parent's `RETURNED` events plus any events named in `add_event_ids`; creating it increments the parent return's `version` by one. A computed summary read for any return returns its `return_id`, `period`, `event_count`, `gross_tax_cents`, `exempted_cents`, `taxable_tax_cents`, `credits_cents`, `deposits_applied_cents`, `penalty_cents`, `net_due_cents`, `filing_status`, and `settlement_status`.

### 3.7. Deposit Schedules, Payments, and Late Penalties

Every return carries a deposit schedule, created with the return — whether the return arose automatically at first rating or manually — and shaped by the registration's `deposit_method`. The windows follow the jurisdiction's deposit frequency: under `SEMI_MONTHLY` (available only to `MONTHLY` jurisdictions), window `A` covers days 1 through 15 of the month and falls due on the twenty-fifth of the same month, while window `B` covers day 16 through month end and falls due on the tenth of the next month; under `MONTHLY`, the single window `M` spans the whole return period — a month or a quarter — and falls due on the twenty-fifth of the month following the period end. Each deposit records its `registration_id`, `jurisdiction_id`, `period`, `window`, `scheduled_amount_cents`, and `due_date`, and starts in `SCHEDULED` with `paid_amount_cents` and `paid_at` unset, `penalty_cents` at zero, `applied_amount_cents` at zero, and `applied_return_id` null.

The two deposit methods compute `scheduled_amount_cents` very differently. Under the `SAFE_HARBOR` variant, the scheduled amount is a forward-looking estimate known immediately at return creation: one half of the prior period's final `taxable_tax_cents`, rounded half-up to whole cents, where "the prior period" means the immediately preceding period's latest non-superseded `FILED` return — amendments supersede, so the newest non-superseded one's figure governs. When no such prior filed return exists, the schedule falls back to a floor of 10,000 cents (one hundred dollars) per deposit. Identical activity in the current period does not move a safe-harbor schedule. Under the `ACTUAL` variant, the scheduled amount starts at zero and accumulates the period's own activity: the clock sweep at each window close sets the scheduled amount to the sum of `tax_cents` over the registration's events in that jurisdiction whose `event_date` falls inside the window and whose status is `RATED`, `RETURNED`, or `ADJUSTED`.

Payment is a `TaxAnalyst` or `ComplianceAdmin` operation on a `SCHEDULED` or `LATE` deposit, carrying `amount_cents` of at least one cent (`ERR_INVALID_REQUEST` below that). Paying stamps `paid_at` with the logical clock, records `paid_amount_cents`, moves the deposit to `PAID`, and computes the late-payment penalty from the calendar. The penalty compares the paid date with the due date in calendar days; a deposit paid on or before its due date owes nothing. Paid one to five days late — five days exactly still falls inside this tier — the penalty is two percent of the scheduled amount, rounded half-up to a whole cent. Paid six to fifteen days late, the penalty is five percent, rounded half-up. Paid sixteen or more days late, the penalty is ten percent of the scheduled amount plus daily interest of 0.05 percent of the scheduled amount for each day late, each of the two components rounded half-up to whole cents separately before they are summed. The result lands on the deposit's `penalty_cents`.

A deposit that stays unpaid past its `due_date` is marked `LATE` by the clock sweep. A `ComplianceAdmin` may instead waive a `SCHEDULED` or `LATE` deposit, moving it to `WAIVED`. The final transition happens at filing: as §3.6's waterfall runs, each `PAID` deposit of the period transitions to `APPLIED` with `applied_return_id` set to the filed return and `applied_amount_cents` recording the portion consumed, while any excess paid cash flows to the registrant's `overpayment_balance_cents`. The deposit list filters by `registration_id`, `jurisdiction_id`, `period`, `status`, or `applied_return_id`, and — the exception to §2.3's default ordering — returns deposits sorted by `due_date` ascending and then `created_at` ascending.

### 3.8. Credit and Refund Claims

Credits recover tax already paid, in two flavors: `BAD_DEBT` claims for uncollectible receivables and `EXPORT` claims for goods that left the country. A `TaxAnalyst` or `ComplianceAdmin` drafts a claim with `registration_id`, the `return_id` of the `FILED` return whose tax the claim refunds, the `claim_type`, the `claimed_cents` requested, the supporting `event_ids`, and a free-text `justification`. The named return must belong to the same registration and jurisdiction as the claim, failing with `ERR_REGISTRATION_JURISDICTION_MISMATCH` otherwise, and every referenced entity must share the registrant chain (`ERR_CROSS_REGISTRANT_REFERENCE`). A new claim starts in `DRAFT` with `submitted_by_user_id` and `reviewed_by_user_id` unset, `eligible_cents` at zero, `approved_cents` unset, and `applied_cents` and `reversed_cents` at zero. The claim list filters by `registration_id`, `return_id`, `status`, or `claim_type`.

Submission is where the windows bite. The claim's return must be `FILED`, failing with `ERR_INVALID_STATE` otherwise. A `BAD_DEBT` claim may be submitted no earlier than one hundred eighty-three days after the return's `filed_at` — earlier attempts fail with `ERR_BAD_DEBT_TOO_EARLY` — and no later than seven hundred thirty-one days after it, as are `EXPORT` claims, with later attempts failing with `ERR_CLAIM_WINDOW_EXPIRED`. An `EXPORT` claim must list only events whose `is_export` flag is set, failing with `ERR_EXPORT_DOCUMENTATION_MISSING` otherwise. And no listed event may already appear on another claim in `SUBMITTED`, `APPROVED`, or `APPLIED`, failing with `ERR_EVENT_ALREADY_CLAIMED`. On a valid submission the server records `submitted_by_user_id` and computes `eligible_cents`: the sum of `tax_cents` over the claim's listed events whose status is `RETURNED` or `ADJUSTED`, that share the claim's registration and jurisdiction, and that no other live claim lists — only tax actually paid is refundable. For record-keeping, the claim's amount is allocated to its eligible events in `event_date` ascending and then `created_at` ascending order. The claim moves to `SUBMITTED`.

Review is segregated per §2.9: the approver or denier must not be the operator who submitted the claim, with violations rejected as `ERR_SEGREGATION_OF_DUTIES`. Approving takes an `approved_cents` that may not exceed the smallest of the `claimed_cents`, the computed `eligible_cents`, and a statutory cap of 5,000,000 cents (fifty thousand dollars); an amount above that ceiling is rejected with `ERR_CLAIM_EXCEEDS_ELIGIBLE`. Approval moves the claim to `APPROVED` and records `reviewed_by_user_id`. Denial takes a `reason`, moves the claim to `DENIED`, and likewise records `reviewed_by_user_id`. A denied claim is not dead: resubmission sends it from `DENIED` back to `DRAFT`, clearing `submitted_by_user_id`, `reviewed_by_user_id`, and `eligible_cents` so the cycle can run again. A claim in `DRAFT` or `SUBMITTED` may instead be withdrawn, ending in `WITHDRAWN`.

Applying an `APPROVED` claim is the step that moves money, and an audit records hold covering the claim return's period blocks it with `ERR_AUDIT_RECORDS_HOLD`. Application sets `applied_cents` equal to `approved_cents`, adds that amount to the return's `credits_cents`, recomputes `net_due_cents`, and flips the settlement status per §3.6 — with any `OVERPAID` excess accruing to the registrant's `overpayment_balance_cents`. The claim ends in `APPLIED`.

Reversal claws credit back, for instance when a bad debt is later recovered. Reversal takes an `amount_cents` no greater than the not-yet-reversed portion — `applied_cents` minus `reversed_cents` — failing with `ERR_REVERSE_EXCEEDS_APPLIED` above that. Each reversal adds to `reversed_cents`, subtracts the amount from the return's `credits_cents`, recomputes the net due, flips the settlement back toward `AWAITING_PAYMENT` when the net due turns positive again, reduces the overpayment balance accordingly, and recomputes the registration's bond requirement, which may flip the `requirement_variant` to `AGGRAVATED`. A claim whose reversed total has not yet reached its applied amount stays `APPLIED`; when the reversed total reaches the applied amount, the claim moves to `REVERSED`.

### 3.9. Audit Cases and Records Retention

An examination begins when a `JurisdictionAuditor` opens an audit case with `registration_id`, `jurisdiction_id`, and an inclusive month-bucket range from `period_start` to `period_end`, both keyed `YYYY-MM`; a `period_end` earlier than `period_start` is rejected with `ERR_INVALID_REQUEST`. Two cases for the same registration and jurisdiction may not share any month bucket while the existing case is non-terminal, failing with `ERR_AUDIT_RANGE_OVERLAP`. A new case starts in `OPENED` with `records_hold` true, `assessment_cents` unset, and `opened_by_user_id` recording the auditor's `X-User-ID`. The case list filters by `registration_id`, `jurisdiction_id`, or `status`.

The records hold is the case's teeth. It stays true while the case is in `OPENED`, `DOCUMENTS_REQUESTED`, or `UNDER_REVIEW`, and while it covers a period it blocks five operations outright, each rejected with `ERR_AUDIT_RECORDS_HOLD`: opening an amendment of a return of the period, reclassifying a `RETURNED` event inside an amendment of the period, applying an approved credit claim against a return of the period, purging the period's expired records, and revoking the registration.

Working the case is a short ladder. The auditor requests documents, moving the case from `OPENED` to `DOCUMENTS_REQUESTED`, and begins review, moving from `DOCUMENTS_REQUESTED` to `UNDER_REVIEW` — or directly from `OPENED` to `UNDER_REVIEW` on the fast path. Closing takes an `outcome`: `NO_CHANGE` ends the case in `CLOSED_NO_CHANGE`, while `ASSESSMENT` requires an `assessment_cents` of at least one cent (`ERR_INVALID_REQUEST` otherwise), records the assessment on the case, and ends it in `CLOSED_ASSESSMENT`. Either close releases the records hold.

Retention is the other side of record-keeping. A period becomes eligible for purge once seven years have elapsed between its retention anchor and the current logical date, where the anchor is the `filed_at` of the period's latest non-superseded `FILED` return, or the period end when no return was ever filed. A `ComplianceAdmin` purges an eligible period by naming it (`period`), and the operation deletes the period's `VOIDED` events and `SUPERSEDED` returns and reports the counts as `purged_event_count` and `purged_return_count`. Attempting a purge before the anchor has aged seven years is rejected with `ERR_RETENTION_NOT_ELAPSED`, and an audit records hold covering the period blocks it with `ERR_AUDIT_RECORDS_HOLD`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: this covers the creation of jurisdictions, product classes, tax rates, rate-change notices, registrants, registrations, bonds, exemption certificates, bonded movements, taxable events, returns (including the amendment operation, which creates a new amendment return), credit claims, and audit cases. All other successful operations — reads, lifecycle transitions, payments, the clock advance, and the records purge — return `200 OK`. The table below is a summary only; request fields, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the daily sweep | ComplianceAdmin |
| POST | `/jurisdictions` | Create a taxing jurisdiction | ComplianceAdmin |
| GET | `/jurisdictions/{id}` | Get a jurisdiction | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/product-classes` | Create a taxable product class | ComplianceAdmin |
| GET | `/product-classes/{id}` | Get a product class | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/tax-rates` | Directly create a rate (initial schedules and non-overlapping future/gap windows) | ComplianceAdmin |
| GET | `/tax-rates/{id}` | Get a tax rate | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/tax-rates` | List tax rates with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/rate-change-notices` | Record a detected rate change announcement | TaxAnalyst, ComplianceAdmin |
| GET | `/rate-change-notices/{id}` | Get a rate change notice | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/rate-change-notices` | List rate change notices with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/rate-change-notices/{id}/validate` | Mark a detected notice verified against the official bulletin | TaxReviewer, ComplianceAdmin |
| POST | `/rate-change-notices/{id}/reject` | Reject a spurious notice | TaxReviewer, ComplianceAdmin |
| POST | `/rate-change-notices/{id}/apply` | Apply a validated notice: create the new rate, supersede the prior window, run the re-rate cascade | ComplianceAdmin |
| POST | `/registrants` | Create a taxpayer registrant | ComplianceAdmin |
| GET | `/registrants/{id}` | Get a registrant | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/registrations` | Register a registrant with a jurisdiction | ComplianceAdmin |
| GET | `/registrations/{id}` | Get a registration | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/registrations` | List registrations with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/registrations/{id}/activate` | Activate a PENDING registration (requires sufficient bond coverage) | ComplianceAdmin |
| POST | `/registrations/{id}/suspend` | Suspend an ACTIVE registration | ComplianceAdmin |
| POST | `/registrations/{id}/reinstate` | Reinstate a SUSPENDED or BOND_DEFICIENT registration | ComplianceAdmin |
| POST | `/registrations/{id}/revoke` | Revoke a registration (terminal) | ComplianceAdmin |
| GET | `/registrations/{id}/bond-status` | Computed read: current bond requirement versus coverage | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/registrations/{id}/purge-expired-records` | Purge one period's VOIDED events and SUPERSEDED returns after retention | ComplianceAdmin |
| POST | `/bonds` | Create a surety bond (DRAFT) for a registration | ComplianceAdmin |
| GET | `/bonds/{id}` | Get a bond | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/bonds` | List bonds with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/bonds/{id}/activate` | Activate a DRAFT bond | ComplianceAdmin |
| POST | `/bonds/{id}/cancel` | Cancel an ACTIVE bond | ComplianceAdmin |
| POST | `/exemption-certificates` | Create an exemption certificate (PENDING_VERIFICATION) | TaxAnalyst, ComplianceAdmin |
| GET | `/exemption-certificates/{id}` | Get an exemption certificate | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/exemption-certificates` | List exemption certificates with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/exemption-certificates/{id}/verify` | Verify a certificate | TaxReviewer, ComplianceAdmin |
| POST | `/exemption-certificates/{id}/revoke` | Revoke an ACTIVE certificate or reject an unverified one | TaxReviewer, ComplianceAdmin |
| POST | `/bonded-movements` | Document an in-bond movement of taxable product | TaxAnalyst, ComplianceAdmin |
| GET | `/bonded-movements/{id}` | Get a bonded movement | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/bonded-movements` | List bonded movements with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/bonded-movements/{id}/dispatch` | Mark the movement dispatched | TaxAnalyst, ComplianceAdmin |
| POST | `/bonded-movements/{id}/receive` | Confirm receipt quantity | TaxAnalyst, ComplianceAdmin |
| POST | `/bonded-movements/{id}/discharge` | Discharge the bond after exact quantity reconciliation | TaxReviewer, ComplianceAdmin |
| POST | `/bonded-movements/{id}/default` | Declare a full or shortfall default and run the default-assessment cascade | ComplianceAdmin |
| POST | `/taxable-events` | Record a taxable activity (removal, sale, or use) | TaxAnalyst, ComplianceAdmin |
| GET | `/taxable-events/{id}` | Get a taxable event | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/taxable-events` | List taxable events with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/taxable-events/{id}/classify` | Confirm product identification | TaxAnalyst, ComplianceAdmin |
| POST | `/taxable-events/{id}/rate` | Determine the tax, optionally linking a certificate or movement, and include the event in its period return | TaxAnalyst, ComplianceAdmin |
| POST | `/taxable-events/{id}/reclassify` | Send a rated or returned event back for correction | TaxAnalyst, ComplianceAdmin |
| POST | `/taxable-events/{id}/void` | Void a DRAFT or CLASSIFIED event | TaxAnalyst, ComplianceAdmin |
| POST | `/returns` | Manually create an original DRAFT return (including zero-activity returns) with its deposit schedule | TaxAnalyst, ComplianceAdmin |
| GET | `/returns/{id}` | Get a tax return | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/returns` | List returns with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/returns/{id}/summary` | Computed read: full liability breakdown of a return | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/returns/{id}/submit` | Preparer submits a DRAFT return for review | TaxAnalyst, ComplianceAdmin |
| POST | `/returns/{id}/withdraw` | Withdraw a submission | TaxAnalyst, ComplianceAdmin |
| POST | `/returns/{id}/file` | Reviewer files a SUBMITTED return (OCC- and SoD-guarded) | TaxReviewer, ComplianceAdmin |
| POST | `/returns/{id}/amend` | Open an amendment of a FILED return | TaxAnalyst, ComplianceAdmin |
| GET | `/deposits/{id}` | Get a deposit | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/deposits` | List deposits with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/deposits/{id}/pay` | Pay a SCHEDULED or LATE deposit | TaxAnalyst, ComplianceAdmin |
| POST | `/deposits/{id}/waive` | Waive an unpaid deposit | ComplianceAdmin |
| POST | `/credit-claims` | Create a credit/refund claim against a FILED return | TaxAnalyst, ComplianceAdmin |
| GET | `/credit-claims/{id}` | Get a credit claim | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/credit-claims` | List credit claims with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/credit-claims/{id}/submit` | Submit a claim for review | TaxAnalyst, ComplianceAdmin |
| POST | `/credit-claims/{id}/approve` | Approve a SUBMITTED claim | TaxReviewer, ComplianceAdmin |
| POST | `/credit-claims/{id}/deny` | Deny a SUBMITTED claim | TaxReviewer, ComplianceAdmin |
| POST | `/credit-claims/{id}/apply` | Apply an APPROVED claim to its return | TaxAnalyst, ComplianceAdmin |
| POST | `/credit-claims/{id}/reverse` | Claw back an applied credit (full reversal ends in REVERSED) | TaxReviewer, ComplianceAdmin |
| POST | `/credit-claims/{id}/withdraw` | Withdraw a DRAFT or SUBMITTED claim | TaxAnalyst, ComplianceAdmin |
| POST | `/credit-claims/{id}/resubmit` | Send a DENIED claim back to DRAFT for correction | TaxAnalyst, ComplianceAdmin |
| POST | `/audit-cases` | Open an audit case over a month-bucket period range | JurisdictionAuditor |
| GET | `/audit-cases/{id}` | Get an audit case | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| GET | `/audit-cases` | List audit cases with filters | ComplianceAdmin, TaxAnalyst, TaxReviewer, JurisdictionAuditor |
| POST | `/audit-cases/{id}/request-documents` | Move an OPENED case to DOCUMENTS_REQUESTED | JurisdictionAuditor |
| POST | `/audit-cases/{id}/begin-review` | Move a case to UNDER_REVIEW | JurisdictionAuditor |
| POST | `/audit-cases/{id}/close` | Close a case under review, with or without assessment | JurisdictionAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUDIT_RECORDS_HOLD` | 409 Conflict |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_LOCKED` | 409 Conflict |
| `ERR_BAD_DEBT_TOO_EARLY` | 409 Conflict |
| `ERR_CLAIM_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_BOND_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_RETENTION_NOT_ELAPSED` | 409 Conflict |
| `ERR_DUPLICATE_FEIN` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_DUPLICATE_RETURN` | 409 Conflict |
| `ERR_AMENDMENT_ALREADY_OPEN` | 409 Conflict |
| `ERR_RATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CERTIFICATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_RANGE_OVERLAP` | 409 Conflict |
| `ERR_MOVEMENT_QUANTITY_EXCEEDS` | 422 Unprocessable Entity |
| `ERR_CROSS_REGISTRANT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_JURISDICTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CERTIFICATE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_MOVEMENT_NOT_LINKABLE` | 422 Unprocessable Entity |
| `ERR_EVENT_ALREADY_CLAIMED` | 409 Conflict |
| `ERR_EXPORT_DOCUMENTATION_MISSING` | 422 Unprocessable Entity |
| `ERR_NO_APPLICABLE_RATE` | 422 Unprocessable Entity |
| `ERR_BOND_INSUFFICIENT` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_REVERSE_EXCEEDS_APPLIED` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_HAS_OPEN_LIABILITY` | 409 Conflict |
