# Food Ingredient Sourcing API — Product Requirements Document

## 1. Introduction

A food manufacturer's procurement organization lives and dies by its approved source list. Every ingredient that enters a formula carries a specification, and every specification is anchored to a supplier who has been qualified, audited, declared allergen-clean (or allergen-known), and contractually bound to a price index. When any one of those anchors moves — a spec is superseded, a supplier's risk score climbs past a threshold, a certificate of analysis reveals an out-of-spec analyte, a country-of-origin declaration lapses — the sourcing stack must respond in a coordinated, auditable way.

This document specifies a REST API for the food-ingredient sourcing and specification-management domain. The platform manages the full lifecycle of an ingredient (from draft record to active, dual-sourced commodity to discontinued legacy), the versioned specifications that define its acceptance envelope, the suppliers who are qualified to ship it, the contracts that price each lot against a market index, the certificates of analysis that gate every shipment, the regulatory declarations that guard allergen and country-of-origin truth, the substitution requests that allow procurement to pivot when supply breaks, and the audit-and-corrective-action loop that keeps the supply base honest. All endpoints are mounted under `/sourcing`.

A central design tenet is **segregation of duties**: the person who authors a specification cannot approve it; the engineer who registers a certificate of analysis cannot close its review; the procurement manager who requests a substitution cannot approve it. A second tenet is **time discipline**: the platform runs on a logical clock that a platform administrator can advance, and every temporal guard — effective dates, contract windows, audit windows, declaration validity windows, CAPA due dates, the trailing twelve-month CoA window — is evaluated against that clock, never against wall time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 400). Once the headers are present, the role named in `X-User-Role` is checked against the RBAC matrix for the target endpoint; a role that is not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are recognized, with these exact spellings:

- **`SpecAuthor`** — R&D specification author. Drafts and submits spec versions, adds parameters, and revises rejected specs; cannot approve a spec they authored.
- **`QualityManager`** — Quality organization approver. Approves and rejects specs, makes them effective, retires them; reviews and closes CoAs; decides supplier qualifications; suspends and disqualifies suppliers; approves and rejects substitution requests; closes and cancels audits; raises and verifies corrective actions.
- **`ProcurementManager`** — Procurement owner. Creates and discontinues ingredients; registers suppliers; creates, activates, suspends, reinstates, and revokes approved sources; creates, activates, and terminates contracts; creates, executes, and cancels substitution requests.
- **`SupplierQualityEngineer`** — Supplier-facing quality engineer. Opens qualifications, registers CoAs, runs substitution assessments, schedules and executes audits, and submits CAPA responses.
- **`RegulatoryAffairs`** — Regulatory affairs collector. Collects allergen and country-of-origin declarations and records regulatory sign-off on substitution requests.
- **`PlatformAdmin`** — System operator. Drives the logical clock and records price-index observations.

For every role listed above, the value carried in `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it onto specific ownership fields when a workflow calls for a segregation-of-duties anchor — for example, `author_user_id` on a newly created `IngredientSpec`, `reviewed_by_user_id` when a `QualityManager` approves, `registered_by_user_id` on a registered CoA, `requested_by_user_id` on a substitution request, `evaluated_by_user_id` on a decided qualification, `collected_by_user_id` on a collected declaration, and `approved_by_user_id` on an activated source — but it never compares `X-User-ID` to any entity's `id`. Segregation-of-duties checks compare `X-User-ID` against these recorded anchor fields, never against the entity's primary key.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits and a `Z` suffix, read from the wall clock; it is the only wall-clock read in the platform (entity timestamps derive from the logical clock, §2.4).
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

List endpoints accept two query parameters: `limit` and `offset`. The default value of `limit` is 10; the minimum accepted value is 1 and the maximum is 100. The default value of `offset` is 0. A non-integer `limit` or `offset`, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses always include the four pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope. Rows are returned ordered by `created_at` ascending (earliest created first); when two rows share the same `created_at` millisecond, the tie is broken by the server's insertion sequence. The random `id` value is never used for ordering. In addition to pagination, list endpoints accept optional exact-match query filters on selected resource fields (such as `status`, `risk_tier`, `supplier_id`, `active_spec_id`, `requires_dual_source`, `ingredient_id`, `supersedes_spec_id`, `declaration_type`, `contract_id`, `disposition`, and `index_name`, as applicable per endpoint); multiple filters combine conjunctively, unrecognized query parameters are ignored, and a boolean filter such as `requires_dual_source` accepts only the literals `true` and `false` (anything else is rejected with `ERR_INVALID_REQUEST`).

### 2.4. Common Resource Properties

Every persisted entity carries an `id` field that is a server-minted UUID with no type prefix, and a `created_at` field that is an ISO 8601 UTC timestamp with three fractional digits and a `Z` suffix, stamped from the logical clock (never wall time). Most entities additionally carry `updated_at` (same timestamp format, likewise logical-clock) and `version` (an integer that starts at 1 at creation and increments by one on every mutation of the row; a derived recompute that leaves a row's values unchanged is not a mutation and bumps neither `version` nor `updated_at`). Client-supplied datetime fields (such as `effective_date`, `valid_from`, `valid_until`, `window_start`, `window_end`, `received_at`, `observed_at`, `due_date`, and a manually scheduled audit's window) are stored and echoed verbatim as the submitted string, while system-stamped datetime fields (such as `last_audit_closed_at` and the windows of an auto-scheduled audit) are rendered in the canonical three-fractional-digit `Z` format. One entity is exempt: `PriceIndexObservation` is an immutable observation log and carries only `id` and `created_at` — `updated_at` and `version` are absent on that entity and no endpoint mutates it.

### 2.5. Numeric Precision and Rounding

All monetary and score arithmetic in the platform rounds half-up. The deviation-score pipeline rounds each finding's `excess_ratio` to four decimal places, then rounds the aggregate score to two decimal places. The contract-tier-price pipeline rounds each tier slice's adjusted base to four decimal places, multiplies by the kilogram quantity in that slice (kilograms are exact integers), sums the slice values, then divides by total lot kilograms and rounds the resulting unit price to four decimal places. The annual-rebate pipeline rounds each per-lot rebate line to two decimal places, then sums the rounded lines exactly — the alternative order (sum first, round once) is not used. The supplier composite risk score is rounded half-up once at the end to two decimal places. The substitution-impact pipeline rounds each per-parameter `delta` and `cost_delta` to four decimal places, then rounds the final sum to four decimal places.

### 2.6. Logical Clock and Time-Based Sweeps

The server maintains a logical clock. At startup, before any administrator action, the clock reads exactly `2026-08-01T00:00:00Z`. The clock never falls back to wall-clock time. A `PlatformAdmin` advances the clock by posting a `to_iso8601` instant; any parseable ISO 8601 instant is accepted (no monotonicity guard rejects a backwards move), and the success response's `data` is an object carrying `current_utc`, the posted `to_iso8601` string echoed verbatim. Every clock-set operation runs three time-based sweeps in order:

1. **Contract expiry sweep** — every `ACTIVE` supply contract whose `window_end` is at or before the new clock transitions to `EXPIRED`.
2. **Declaration expiry sweep** — every `CURRENT` regulatory declaration whose `valid_until` is at or before the new clock transitions to `EXPIRED`; its parent approved source, if it was `ACTIVE`, transitions to `SUSPENDED` with `suspension_reason` set to `MANUAL`; and the supplier's composite risk score is recomputed (the declaration-lapse component becomes 100).
3. **Overdue CAPA sweep** — every supplier's `open_overdue_capa_count` is recomputed; the supplier's composite risk score is then recomputed; if the resulting score is at least 70 and the supplier is `QUALIFIED`, the supplier is automatically suspended.

### 2.7. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control on a parent entity's `version`. The client must supply the parent's last-observed `version` in a required request field; if it does not match the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). An absent or non-integer `expected_*_version` field is instead rejected with `ERR_INVALID_REQUEST` (HTTP 400) — only an integer that differs from the parent's current `version` yields `ERR_STALE_VERSION`, and that comparison runs after every other check (§2.12).

- Creating a new spec version under an ingredient requires `expected_ingredient_version`. If another writer has advanced the ingredient's version since the client last read it — for example, by making a different spec `EFFECTIVE`, which reassigns `active_spec_id` — the create is rejected.
- Creating an approved source under an ingredient also requires `expected_ingredient_version`. A concurrent spec supersede changes which spec version is `EFFECTIVE`, invalidating the pin the client intended.
- Creating a supply contract under an approved source requires `expected_approved_source_version`. A prior contract creation or a source suspension has already changed the source row, so the overlap-window computation the client assumed no longer holds.

Endpoints not listed here do not take a version field.

### 2.8. Nested Resource Path Validation

Endpoints whose URLs traverse a resource hierarchy validate path identifiers left-to-right. An ingredient id is resolved before a spec id nested under it; a spec id is resolved before a parameter or finding nested under it; an approved-source id is resolved before a contract, CoA, declaration, or finding nested under it; a supplier id is resolved before a qualification, audit, or corrective action nested under it. The first identifier that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404). A request URL that matches no endpoint at all is likewise rejected with `ERR_NOT_FOUND` (HTTP 404), and a known path addressed with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Cross-Reference Coherence

Beyond existence, foreign keys carried in a request body must be coherent with the path hierarchy. The `pinned_spec_id` on an approved-source create must reference a spec that belongs to the path ingredient. The `contract_id` on a CoA register must reference a contract that belongs to the path approved source. The `from_approved_source_id` and `to_approved_source_id` on a substitution request must both reference sources of the path ingredient. The `supersedes_spec_id` on a spec create, when non-null, must reference a spec of the same ingredient. Any violation is rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422).

### 2.10. Uniqueness Rules

The platform enforces business uniqueness at creation time. `ingredient_code` is unique across all ingredients. `supplier_code` is unique across all suppliers. `spec_version_label` is unique within an ingredient. `parameter_name` is unique within a spec. `lot_number` is unique within an approved source. The pair (`index_name`, `observed_at`) is unique across all price-index observations. The triple (`ingredient_id`, `supplier_id`, `pinned_spec_id`) is unique among approved sources that are not in `REVOKED` status. Any collision is rejected with `ERR_DUPLICATE` (HTTP 409).

### 2.11. Segregation of Duties

Five segregation-of-duties rules are enforced, each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- Only the spec's author (the `SpecAuthor` whose `X-User-ID` matches the spec's `author_user_id`) may submit that spec for review or revise it after a rejection.
- The `QualityManager` approving or rejecting a spec must not be the spec's author.
- The `QualityManager` closing a CoA review must not be the CoA's registrar (the `SupplierQualityEngineer` whose `X-User-ID` matches `registered_by_user_id`).
- The `QualityManager` approving or rejecting a substitution request must not be the requester (`requested_by_user_id`).
- Only the requester of a substitution request may cancel it.

### 2.12. Validation Priority Ordering

When a request would fail multiple checks, the server reports the highest-priority failure. The order is: missing auth headers first; then forbidden role; then path resource existence (left-to-right); then body-referenced foreign-key existence; then cross-reference coherence; then state-machine permission for the requested transition; then segregation-of-duties; then temporal guards; then qualification gates (questionnaire score before document pack); then spec parameter bounds; then uniqueness; then contract-window overlap; then declaration coverage; then measured-values completeness; then undisposed findings; then reject-lot guard; then deviation-score ceiling; then substitution impact-delta threshold; then regulatory sign-off presence; then regulatory sign-off necessity; then cascade guards (active sources, open substitutions, open CAPAs, active contract, spec in use, duplicate in-progress qualification, second open audit); then basic request shape (positive quantities, valid enum values); and finally OCC stale-version. Because OCC is last, a request that is simultaneously stale and malformed surfaces the malformed-request error first.

## 3. Business Logic & Workflows

### 3.1. Ingredient Lifecycle

A `ProcurementManager` introduces a new ingredient by posting its `ingredient_code`, display `name`, an `allergen_profile` drawn from the fixed allergen tag set (`MILK`, `EGG`, `FISH`, `SHELLFISH`, `TREE_NUT`, `PEANUT`, `WHEAT`, `SOY`, `SESAME`, `NONE`), and a `requires_dual_source` boolean that flags the ingredient for business-continuity dual sourcing. The ingredient is born with `status` set to `DRAFT`. Its `active_spec_id` is null until a spec becomes `EFFECTIVE`, and its `current_dual_source_breach` flag starts at false.

Activation moves the ingredient from `DRAFT` to `ACTIVE`. The activation is rejected with `ERR_INVALID_STATE` if the ingredient is not in `DRAFT`, and with `ERR_NO_EFFECTIVE_SPEC` if no spec of this ingredient is currently `EFFECTIVE`.

Discontinuation moves the ingredient from `ACTIVE` to `DISCONTINUED` (terminal). It is rejected with `ERR_INVALID_STATE` if the ingredient is not `ACTIVE`, with `ERR_ACTIVE_SOURCES_EXIST` if any approved source of the ingredient is in `PROVISIONAL` or `ACTIVE` status, and with `ERR_OPEN_SUBSTITUTIONS_EXIST` if any substitution request of the ingredient is in `REQUESTED`, `IMPACT_ASSESSED`, `PENDING_REGULATORY`, or `APPROVED` status. On discontinuation the `EFFECTIVE` spec, if any, transitions to `RETIRED`, and `active_spec_id` is set to null.

### 3.2. Specification Authoring, Review, and Effectivity

A `SpecAuthor` drafts a new spec version under an ingredient. The create payload carries `spec_version_label`, `effective_date`, a free-text `version_note`, optionally `supersedes_spec_id` (null for the first spec of an ingredient, otherwise a reference to a prior spec of the same ingredient), and the OCC field `expected_ingredient_version`. The new spec is born in `DRAFT` status with `ingredient_id` pointing at the parent ingredient, its `author_user_id` is set to the acting `SpecAuthor`'s `X-User-ID`, and the parent ingredient's `version` increments by one. Each `SpecParameter` added under the spec carries a `spec_id` back-reference. Specs that are still `DRAFT` accept parameters: the author posts `parameter_name`, `criticality` (one of `CRITICAL`, `MAJOR`, `MINOR`), `uom` (a free unit string such as `percent` or `ppm`), `target_value`, `min_value`, and `max_value`. Adding a parameter to a spec that is no longer `DRAFT` is rejected with `ERR_INVALID_STATE`; adding a parameter does not increment the spec's `version` (the parameter is its own row). Parameter bounds are constrained so that `min_value` is strictly less than `max_value` and `target_value` lies within the inclusive `[min_value, max_value]` range; this is enforced at approval time rather than at parameter create.

Submitting a spec moves it from `DRAFT` to `PENDING_REVIEW`. The submit checks fire in this order: `ERR_INVALID_STATE` if the spec is not `DRAFT`, `ERR_SEGREGATION_OF_DUTIES` if the acting `SpecAuthor` is not the spec's recorded author, `ERR_NO_SPEC_PARAMETERS` if the spec has zero parameters, and `ERR_INVALID_REQUEST` if `version_note` is shorter than ten characters.

Review of a `PENDING_REVIEW` spec has three outcomes. Approve moves the spec to `APPROVED` and sets `reviewed_by_user_id` to the acting `QualityManager`'s `X-User-ID`; it is rejected with `ERR_INVALID_STATE` if the spec is not in review, with `ERR_SEGREGATION_OF_DUTIES` if the approver is the author, and with `ERR_PARAMETER_BOUNDS_INVALID` if any parameter violates the bounds rule. Reject moves the spec to `REJECTED`. Revise moves a `REJECTED` spec back to `DRAFT` so the author can edit parameters and resubmit; both reject and revise carry the same state and segregation guards. Retire moves a `DRAFT` or `REJECTED` spec to `RETIRED` and is rejected with `ERR_SPEC_IN_USE` if any approved source still references the spec in `PROVISIONAL` or `ACTIVE` status.

Make-effective moves an `APPROVED` spec to `EFFECTIVE`. It is rejected with `ERR_INVALID_STATE` if the spec is not `APPROVED`, with `ERR_SPEC_NOT_YET_EFFECTIVE` if the logical clock is before the spec's `effective_date`, and with `ERR_SUPERSEDES_NOT_EFFECTIVE` if the spec carries a non-null `supersedes_spec_id` whose referenced spec is not currently `EFFECTIVE`. On success, several side effects fire: the referenced prior spec transitions from `EFFECTIVE` to `SUPERSEDED`; the ingredient's `active_spec_id` is updated to the newly effective spec; every approved source of the ingredient whose `pinned_spec_id` matches the superseded spec and whose status is `ACTIVE` transitions to `SUSPENDED` with `suspension_reason` set to `MANUAL` (the stale-pin sweep); and the ingredient's `current_dual_source_breach` is recomputed. Two transitions are system-driven and never directly invocable: the automatic `EFFECTIVE` to `SUPERSEDED` on supersede, and the automatic `EFFECTIVE` to `RETIRED` on ingredient discontinuation.

### 3.3. Supplier Registration, Qualification, and Standing

A `ProcurementManager` registers a supplier by posting `supplier_code`, `legal_name`, `risk_tier` (one of `TIER_A`, `TIER_B`, `TIER_C` — which drives the audit cadence months of twelve, six, or three respectively), and `country_of_operation` as an ISO 3166-1 alpha-2 code. The supplier is born in `PROSPECT` status with `composite_risk_score` zero, `last_audit_closed_at` null, `open_overdue_capa_count` zero, and `requalification_cycle` zero.

A `SupplierQualityEngineer` opens a qualification by posting `questionnaire_score` (an integer between 0 and 100) and `document_pack_complete`. The open is rejected with `ERR_INVALID_STATE` if the supplier is not in `PROSPECT` or `SUSPENDED` status, and with `ERR_QUALIFICATION_IN_PROGRESS` if another qualification for the same supplier is already `SUBMITTED` or `UNDER_EVALUATION`. Opening the qualification moves the supplier to `IN_QUALIFICATION` and creates the new `SupplierQualification` in `SUBMITTED` status; if the supplier's previous status was `SUSPENDED`, the supplier's `requalification_cycle` increments by one.

A `QualityManager` moves a `SUBMITTED` qualification to `UNDER_EVALUATION` via the evaluate action, then decides it. The decide payload carries `decision` and `decision_note`. Approving requires three checks: the `questionnaire_score` must be at least 70 (exactly 70 passes; anything below is rejected with `ERR_QUALIFICATION_SCORE_TOO_LOW`), `document_pack_complete` must be true (otherwise `ERR_DOCUMENT_PACK_INCOMPLETE`), and `decision_note` must be present (otherwise `ERR_INVALID_REQUEST`). Rejection likewise requires a non-empty `decision_note` (otherwise `ERR_INVALID_REQUEST`), and a `decision` value other than `APPROVE` or `REJECT` is rejected with `ERR_INVALID_REQUEST`. On approval the qualification becomes `APPROVED`, `evaluated_by_user_id` is set, the supplier transitions from `IN_QUALIFICATION` to `QUALIFIED`, and the supplier's `composite_risk_score` is recomputed. On rejection the qualification becomes `REJECTED` and the supplier's return path depends on its history: if `requalification_cycle` is zero the supplier returns to `PROSPECT`; if the cycle is greater than zero (a requalification after a suspension), the supplier returns to `SUSPENDED`. Both supplier transitions are system-driven consequences of the qualification decision, not separate calls.

Suspension of a supplier can happen two ways. A `QualityManager` may manually suspend a `QUALIFIED` supplier; the manual path is rejected with `ERR_INVALID_STATE` if the supplier is not `QUALIFIED`. The system also suspends a `QUALIFIED` supplier automatically whenever its `composite_risk_score` reaches at least 70. Either way, the same cascade fires: every approved source of that supplier in `ACTIVE` status transitions to `SUSPENDED` with `suspension_reason` set to `SUPPLIER_SUSPENDED`; for each such source, if its ingredient now has fewer than two `ACTIVE` approved sources on the `EFFECTIVE` spec and `requires_dual_source` is true, the ingredient's `current_dual_source_breach` is set to true; and the next audit the supplier schedules is marked with `cadence_source` of `ESCALATED`.

Disqualification moves a `SUSPENDED` supplier to `DISQUALIFIED` (terminal). It is rejected with `ERR_INVALID_STATE` if the supplier is not `SUSPENDED`, and with `ERR_OPEN_CAPAS_EXIST` if any corrective action for this supplier is in `OPEN`, `SUBMITTED`, or `REJECTED` status. On disqualification, every approved source of the supplier in `PROVISIONAL`, `ACTIVE`, or `SUSPENDED` status transitions to `REVOKED`, and each affected ingredient recomputes its `current_dual_source_breach`.

### 3.4. Approved Source Lifecycle and Regulatory Declarations

An approved source is the join between an ingredient, a supplier, and a pinned spec version. A `ProcurementManager` creates one by posting `supplier_id`, `pinned_spec_id`, and the OCC field `expected_ingredient_version`. The source is born in `PROVISIONAL` status, with `suspension_reason` of `NONE`, and creating it increments the parent ingredient's `version` by one.

Activation moves a source from `PROVISIONAL` to `ACTIVE`. The activation is rejected with `ERR_INVALID_STATE` if the source is not `PROVISIONAL`, with `ERR_SUPPLIER_NOT_QUALIFIED` if the referenced supplier is not `QUALIFIED`, with `ERR_SPEC_NOT_EFFECTIVE` if the pinned spec is not currently `EFFECTIVE`, and with `ERR_DECLARATION_MISSING` if either of the two required regulatory declarations is absent. Both declarations must exist in `CURRENT` status with the logical clock inside the `[valid_from, valid_until)` window: one of `declaration_type` `ALLERGEN` and one of `declaration_type` `COUNTRY_OF_ORIGIN`. On success the source's `approved_by_user_id` is set to the acting `ProcurementManager` and the ingredient's `current_dual_source_breach` is recomputed.

Suspension moves an `ACTIVE` source to `SUSPENDED`. The manual path is invoked by a `ProcurementManager` and is rejected with `ERR_INVALID_STATE` if the source is not `ACTIVE`. The system cascades the same transition on two triggers: when the supplier is suspended (`suspension_reason` becomes `SUPPLIER_SUSPENDED`), and when the stale-pin sweep fires on spec supersede (`suspension_reason` becomes `MANUAL`). A `MANUAL` value is also used when the source is parked during substitution execution. While a source is `SUSPENDED`, its contracts remain `ACTIVE` (they are not terminated) but new CoA registration against the source is blocked. Reinstatement moves a `SUSPENDED` source back to `ACTIVE` and clears `suspension_reason` to `NONE`; reinstatement carries the same guards as activation — supplier must be `QUALIFIED`, pinned spec must be `EFFECTIVE`, and both declarations must be current and within their validity windows.

Revocation moves a source from `PROVISIONAL`, `ACTIVE`, or `SUSPENDED` to `REVOKED` (terminal). The manual path is rejected with `ERR_INVALID_STATE` if the source is not in one of those three statuses, and with `ERR_ACTIVE_CONTRACT_EXISTS` if any contract of the source is `ACTIVE`. The system cascade fires on supplier disqualification. On revocation, every `CURRENT` regulatory declaration of the source transitions to `SUPERSEDED`, and the ingredient's `current_dual_source_breach` is recomputed.

A `RegulatoryAffairs` operator collects a declaration by posting `declaration_type` (one of `ALLERGEN`, `COUNTRY_OF_ORIGIN`), a `payload` (for an allergen declaration, an object with an `allergen_tags` array; for a country-of-origin declaration, an object with a `country_codes` array of ISO alpha-2 codes and a single `primary_country` code), and the validity window `[valid_from, valid_until)` with `valid_until` strictly after `valid_from` — a window that violates this is rejected with `ERR_TEMPORAL_GUARD_VIOLATION` (HTTP 422). Collecting a declaration supersedes any prior `CURRENT` declaration of the same `declaration_type` for the same approved source — only one `CURRENT` declaration per (source, type) pair exists at any time — and `collected_by_user_id` records the acting operator.

### 3.5. Supply Contracts and Price-Index Observations

A `ProcurementManager` creates a supply contract under an approved source by posting `annual_committed_volume_kg` (a positive integer), `index_base_value` (a positive number, the market index level at signing), `index_pass_through_pct` (the fraction of index movement passed into price, strictly greater than 0 and at most 1), `window_start` and `window_end` (with `window_end` strictly after `window_start`), and the OCC field `expected_approved_source_version`. The contract is born in `PENDING` status, its `approved_source_id` field references the parent source, and `cumulative_shipped_kg` starts at zero; creating it increments the parent source's `version` by one.

Activation moves a `PENDING` contract to `ACTIVE`. It is rejected with `ERR_INVALID_STATE` if the contract is not `PENDING`, with `ERR_SOURCE_NOT_ACTIVE` if the parent source is not `ACTIVE`, with `ERR_CONTRACT_WINDOW_NOT_OPEN` if the logical clock is before `window_start` or at or after `window_end`, and with `ERR_CONTRACT_WINDOW_OVERLAP` if another `ACTIVE` contract of the same source has a window that overlaps this one. Overlap is judged with half-open interval arithmetic: `[window_start, window_end)` intervals that merely touch at an endpoint do not overlap.

Termination moves a contract from `PENDING` or `ACTIVE` to `TERMINATED` (terminal); it is rejected with `ERR_INVALID_STATE` if the contract is in any other status. Expiration is system-driven: the contract-expiry sweep on the logical clock moves an `ACTIVE` contract whose `window_end` has been reached to `EXPIRED`.

A `PlatformAdmin` records market index observations by posting `index_name`, `observed_at`, and a positive `index_value`. Observations form an immutable append-only log and are never mutated after creation.

### 3.6. Certificate of Analysis Review and Pricing

When a lot arrives, a `SupplierQualityEngineer` registers a certificate of analysis by posting `contract_id`, `lot_number`, a positive integer `shipped_qty_kg`, `received_at`, and `measured_values` — an array of `(parameter_name, observed_value)` pairs that must cover every spec parameter of the source's pinned spec exactly once, with each `observed_value` numeric. Registration is rejected with `ERR_MEASURED_VALUES_INCOMPLETE` if the coverage is wrong or any entry is malformed (a non-numeric `observed_value`, a duplicate `parameter_name`, or a name no pinned-spec parameter carries), with `ERR_SOURCE_NOT_ACTIVE` if the source is not `ACTIVE`, with `ERR_INVALID_STATE` if the referenced contract is not `ACTIVE`, and with `ERR_INVALID_REQUEST` if `shipped_qty_kg` is not a positive integer. The new CoA is born in `REGISTERED` status with `registered_by_user_id` set to the acting engineer, `provisional_deviation_score` at zero, and `final_deviation_score` and `unit_price_applied` both null.

Starting review moves a `REGISTERED` CoA to `UNDER_REVIEW`. On entry the system creates one `CoAOutOfSpecFinding` per measured parameter whose `observed_value` falls outside the pinned spec's inclusive `[min_value, max_value]` range. Each finding's `coa_id` references its owning CoA, and the finding snapshots `parameter_name`, `observed_value`, the `violated_bound` (the min or max bound that was exceeded), and `criticality_at_finding` copied from the spec parameter. Findings are persisted in the spec's parameter creation order, and the findings list endpoint returns them in that same order — deterministic, with no id-based ordering. The provisional deviation score is then computed (see below) and stored on `provisional_deviation_score`.

While the CoA is `UNDER_REVIEW`, a `QualityManager` dispositions each finding by posting `disposition` (one of `ACCEPT_AS_IS`, `DOWNGRADED_TO_MINOR`, `REJECT_LOT`) and a `disposition_note` of at least ten characters. Findings start in `REPORTED` disposition. Attempting to disposition a finding on a CoA that is no longer `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`.

Closing the review has two outcomes, selected by the `outcome` field of the close-review payload. The guards fire in this order: the CoA must be `UNDER_REVIEW` (`ERR_INVALID_STATE`); the closer must not be the CoA's registrar (`ERR_SEGREGATION_OF_DUTIES`); every finding must have a disposition other than `REPORTED` (otherwise `ERR_FINDINGS_UNDISPOSITIONED`); and the `outcome` value itself must be `ACCEPT` or `REJECT` (otherwise `ERR_INVALID_REQUEST`) — for this endpoint the enum check sits ahead of the reject-lot and deviation-ceiling guards. For `outcome=ACCEPT`, two further guards apply: no finding may have disposition `REJECT_LOT` (otherwise `ERR_FINDINGS_REQUIRE_REJECTION`), and the deviation score must be strictly below 150 (exactly 150 blocks the accept; `ERR_DEVIATION_SCORE_TOO_HIGH`). The score check is satisfied either by a `provisional_deviation_score` strictly below 150, or, when the provisional score is at or above 150, by all findings being dispositioned `ACCEPT_AS_IS` with the recomputed final score strictly below 150. On a successful accept the system computes `final_deviation_score` per the final variant, computes `unit_price_applied` per the contract-tier-price rule, adds `shipped_qty_kg` to the contract's `cumulative_shipped_kg`, recomputes the supplier's composite risk score (the accepted lot enters the twelve-month CoA window), and lands the CoA in `ACCEPTED` status — or in `CONDITIONALLY_ACCEPTED` if at least one finding carries disposition `ACCEPT_AS_IS`. Both `ACCEPTED` and `CONDITIONALLY_ACCEPTED` are terminal acceptance states. Tier crossings are not retroactive: if adding this lot's volume pushes `cumulative_shipped_kg` across a tier boundary, only subsequent lots price at the new tier.

For `outcome=REJECT`, the state and segregation and undisposed-findings guards are the same, but the lot is not priced: `final_deviation_score` is computed, `cumulative_shipped_kg` is left unchanged, and the CoA lands in `REJECTED`. The rejected lot still enters the twelve-month CoA window, so the supplier's composite risk score is recomputed; if the new score is at least 70, the supplier auto-suspends per the supplier machine.

### 3.7. Deviation Score and Contract Pricing Calculations

The **deviation score** measures how far a lot's findings deviate from spec. For each finding, the system first computes `excess_ratio`: the absolute difference between `observed_value` and `violated_bound`, divided by the spec parameter's full range (`max_value` minus `min_value`), rounded half-up to four decimal places. Each finding is then weighted by criticality: `CRITICAL` weighs 3, `MAJOR` weighs 2, `MINOR` weighs 1. The score is the sum of each finding's `excess_ratio` times its effective weight, multiplied by 100, rounded half-up to two decimal places.

Two variants exist. The **provisional** variant, computed when the CoA enters `UNDER_REVIEW`, weights every finding at its snapshot `criticality_at_finding` regardless of disposition. The **final** variant, computed when the review closes, weights any finding dispositioned `DOWNGRADED_TO_MINOR` as `MINOR` (weight 1) regardless of its snapshot criticality; findings dispositioned `REJECT_LOT` still count at full weight. Provisional and final diverge whenever any finding is downgraded. The acceptance ceiling is 150: a final score of exactly 150 blocks the accept.

The **contract tier price** prices a lot at acceptance. Tiers are defined on cumulative committed/shipped kilograms per contract: the first tier covers zero up to (but not including) 10,000 kg at a base of 4.50; the second tier covers 10,000 kg up to (but not including) 50,000 kg at a base of 4.20; the third tier covers 50,000 kg and beyond at a base of 3.95. The lot's kilograms are allocated marginally across tiers, starting from the contract's `cumulative_shipped_kg` before the lot. For each tier slice, the adjusted base is the tier base multiplied by (1 plus `index_pass_through_pct` times the relative index movement), where the relative index movement is (`index_current` minus `index_base_value`) divided by `index_base_value`; the adjusted base is rounded half-up to four decimal places. The slice value is the slice's kilograms times its adjusted base. Slice values are summed, then divided by the lot's total kilograms and rounded half-up to four decimal places to produce `unit_price_applied`. The `index_current` selector is the most recent `PriceIndexObservation` whose `index_name` is `INGREDIENT-SPOT` and whose `observed_at` is at or before the current clock, ordered by `observed_at` descending; ties on `observed_at` are broken by earliest `created_at`. If no such observation exists, the contract's `index_base_value` is used as `index_current`.

The **annual rebate** is exposed as a computed read over a contract. The rebate rate is 0.02 when the contract's `accepted_value_total` is at least 250,000 and 0.015 otherwise; `accepted_value_total` is the sum, at full precision, of `shipped_qty_kg` times `unit_price_applied` over all CoAs of the contract in `ACCEPTED` or `CONDITIONALLY_ACCEPTED` status whose `received_at` falls within the contract's `[window_start, window_end)` window. The rebate itself is computed per line: for each qualifying CoA, the line rebate is `shipped_qty_kg` times `unit_price_applied` times the rebate rate, rounded half-up to two decimal places; the total rebate is the exact sum of the rounded lines. This per-line-then-sum order is pinned — the alternative (sum first, round once) is not used because the two orders diverge. The rebate response carries `contract_id`, `rebate_rate`, `accepted_value_total`, `total_rebate`, and `line_count`.

### 3.8. Substitution Requests and Formula Impact Assessment

A `ProcurementManager` opens a substitution request against an ingredient by posting `from_approved_source_id`, `to_approved_source_id`, a `reason_code` (one of `SUPPLY_SHORTAGE`, `COST_REDUCTION`, `QUALITY_ESCAPE`, `DUAL_SOURCE_BREACH`), and `formula_unit_cost_sensitivities` — an array of `(parameter_name, cost_per_unit_delta)` pairs that parameterize the cost model. The request is born in `REQUESTED` status with `requested_by_user_id` set, `impact_delta_per_unit` null, and `requires_regulatory_signoff` false.

Assessment moves a `REQUESTED` request to `IMPACT_ASSESSED`. It is rejected with `ERR_INVALID_STATE` if the request is not `REQUESTED`, with `ERR_INVALID_REQUEST` if `from_approved_source_id` and `to_approved_source_id` are the same, with `ERR_SOURCE_NOT_ACTIVE` if the to-source is not `ACTIVE`, and with `ERR_SPEC_NOT_EFFECTIVE` if the to-source's pinned spec is not `EFFECTIVE`. On assessment the system creates a `FormulaImpactAssessment` (its `substitution_request_id` references the parent request) and fills in four computed fields; the assess endpoint's response returns the updated substitution request object, not the assessment. `parameter_deltas` walks the union of parameter names across both pinned specs in a deterministic order — every parameter of the from-source's pinned spec in that spec's parameter creation order, then every parameter found only on the to-source's pinned spec in its own creation order; for each parameter, `from_target` and `to_target` are read from the respective spec (zero when the parameter is absent on either side), `delta` is `to_target` minus `from_target` rounded half-up to four decimal places, and `cost_delta` is `delta` times the matching `cost_per_unit_delta` from the request's sensitivities (zero when the parameter is not named), rounded half-up to four decimal places. `total_delta_per_unit` is the sum of all `cost_delta` values rounded half-up to four decimal places. `allergen_delta_tags` is the set difference of the to-source's `CURRENT` allergen declaration tags minus the ingredient's `allergen_profile` tags, sorted ascending (empty when the to-source has no `CURRENT` allergen declaration). `coo_changed` is true when the to-source's `CURRENT` country-of-origin `primary_country` differs from the from-source's; a side without a `CURRENT` country-of-origin declaration compares as null, so `coo_changed` is true when exactly one side lacks the declaration and false when both lack it. The request's `requires_regulatory_signoff` is set to true when `allergen_delta_tags` is non-empty or `coo_changed` is true, and `impact_delta_per_unit` is set to `total_delta_per_unit`. Both assessment read endpoints (the nested path and the flat alias) return the standard list envelope (`response_type` `"array"`) containing zero or one assessment, not a bare object.

Routing to regulatory moves an `IMPACT_ASSESSED` request to `PENDING_REGULATORY`; it is rejected with `ERR_REGULATORY_SIGNOFF_NOT_REQUIRED` when `requires_regulatory_signoff` is false. A `RegulatoryAffairs` operator then records sign-off by posting `signoff_note`; the sign-off endpoint is rejected with `ERR_INVALID_STATE` unless the request is `PENDING_REGULATORY` and with `ERR_INVALID_REQUEST` when `signoff_note` is missing or empty, and the request's status does not change at that step.

Approval moves a request from `IMPACT_ASSESSED` or `PENDING_REGULATORY` to `APPROVED`. The approver must not be the requester (`ERR_SEGREGATION_OF_DUTIES`). Two regulatory gates apply: from `IMPACT_ASSESSED`, approval is rejected with `ERR_REGULATORY_SIGNOFF_REQUIRED` when `requires_regulatory_signoff` is true; from `PENDING_REGULATORY`, approval is rejected with the same error when no sign-off has been recorded. Independently, a fiscal gate caps the auto-approvable size — but it is evaluated only on the direct `IMPACT_ASSESSED` approval path, ahead of the sign-off necessity check: the absolute value of `impact_delta_per_unit` must be at most 0.5000 (exactly 0.5000 passes); larger absolute deltas are rejected with `ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD` and require the `PENDING_REGULATORY` path regardless of the sign-off flag. Approval from `PENDING_REGULATORY` checks only that a sign-off has been recorded; the fiscal gate is not re-evaluated there. Rejection moves a request from `IMPACT_ASSESSED` or `PENDING_REGULATORY` to `REJECTED` (terminal) under the same segregation guard.

Execution moves an `APPROVED` request to `EXECUTED` (terminal). It is rejected with `ERR_INVALID_STATE` if the request is not `APPROVED`, and with `ERR_SOURCE_NOT_ACTIVE` if the to-source is no longer `ACTIVE`. On execution the from-source transitions from `ACTIVE` to `SUSPENDED` with `suspension_reason` of `MANUAL` — the replaced source is parked; a from-source that is no longer `ACTIVE` at execution time is left unchanged without error — and the ingredient's `current_dual_source_breach` is recomputed.

Cancellation moves a request from `REQUESTED`, `IMPACT_ASSESSED`, or `PENDING_REGULATORY` to `CANCELLED` (terminal). Only the requester may cancel; anyone else is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 3.9. Supplier Audits and Corrective Actions

A `SupplierQualityEngineer` schedules an audit by posting `scheduled_window_start` and `scheduled_window_end` (end strictly after start). The audit is born in `SCHEDULED` status, and its `cadence_source` is computed at creation: `ESCALATED` when the supplier is `SUSPENDED` or has any overdue CAPAs at schedule time, `TIER_CADENCE` otherwise.

Starting an audit moves it from `SCHEDULED` to `IN_PROGRESS`. It is rejected with `ERR_INVALID_STATE` if the audit is not `SCHEDULED`, with `ERR_AUDIT_WINDOW_NOT_OPEN` if the logical clock is outside the `[scheduled_window_start, scheduled_window_end)` window, and with `ERR_AUDIT_ALREADY_OPEN` if another audit of the same supplier is `IN_PROGRESS` or `REPORT_ISSUED`.

Issuing the report moves an `IN_PROGRESS` audit to `REPORT_ISSUED`. The engineer posts `audit_score` (an integer between 0 and 100) and `findings_summary`; both are required (`ERR_INVALID_REQUEST` when absent). Importantly, no corrective action is auto-created at report issue — CAPAs are raised explicitly — and the score does not feed supplier risk until the audit closes; a score below 70 does not by itself suspend the supplier.

A `QualityManager` raises a corrective action on a `REPORT_ISSUED` audit by posting `description` (at least ten characters) and `due_date` (strictly after the audit's report-issue time — a `due_date` at or before the report-issue time is rejected with `ERR_TEMPORAL_GUARD_VIOLATION`, HTTP 422). The CAPA is born in `OPEN` status with its `audit_id` referencing the parent audit, and raising it recomputes the supplier's `open_overdue_capa_count` (the composite risk score is not recomputed at raise time). The supplier's `open_overdue_capa_count` is the count of corrective actions in `SUBMITTED` or `REJECTED` status whose `due_date` is strictly before the current clock, plus `OPEN` rows past due.

A `SupplierQualityEngineer` submits a CAPA response by posting `response_text`; this moves the CAPA from `OPEN` to `SUBMITTED`, and the same action resubmits a `REJECTED` CAPA back to `SUBMITTED` (the resubmission loop is cyclic). A `QualityManager` then verifies the response by posting `verification_note` of at least ten characters, moving the CAPA to `VERIFIED` (terminal), or rejects it by posting a similar note, moving it back to `REJECTED`. Verification recomputes both `open_overdue_capa_count` and the supplier's composite risk; rejection recomputes `open_overdue_capa_count` only.

Closing the audit moves a `REPORT_ISSUED` audit to `CLOSED`. It is rejected with `ERR_OPEN_CAPAS_EXIST` if any corrective action of the audit is not in `VERIFIED` status. On close, the supplier's `last_audit_closed_at` is set to the clock, the supplier's composite risk score is recomputed (the audit component becomes 100 minus the `audit_score`), and the next audit is auto-scheduled per the cadence rule. A `QualityManager` may also cancel a `SCHEDULED` audit, moving it to `CANCELLED` (terminal).

### 3.10. Composite Risk, Audit Cadence, and Dual-Source Thresholds

The **supplier composite risk score** is recomputed on CoA acceptance or rejection, on audit close, on CAPA verify or reject, on the declaration-lapse sweep, on the overdue-CAPA sweep, and on qualification approval. It is a weighted sum of four components, each itself on a 0–100 scale. The CoA component looks at the trailing twelve-month window of CoAs across all of the supplier's approved sources — those with `received_at` in the inclusive range from the clock minus 365 days through the clock itself (CoAs dated after the clock are excluded) — and computes the reject rate: the count of CoAs in `REJECTED` status divided by the count of CoAs in `ACCEPTED`, `CONDITIONALLY_ACCEPTED`, or `REJECTED` status (with the denominator clamped to at least 1), times 100. The audit component is 100 minus the most recently closed audit's `audit_score`, or zero when no audit has ever closed. The overdue component is the supplier's `open_overdue_capa_count` times 25, capped at 100. The declaration component is 100 when any of the supplier's approved sources in `ACTIVE` status lacks a `CURRENT` declaration of either required type within its validity window, and zero otherwise. The composite is 0.35 times the CoA component, plus 0.30 times the audit component, plus 0.20 times the overdue component, plus 0.15 times the declaration component, rounded half-up once at the end to two decimal places and clamped to the inclusive [0, 100] range. When the composite reaches at least 70 while the supplier is `QUALIFIED`, the supplier is automatically suspended.

The **audit cadence schedule** runs at audit close. The base cadence is twelve months for a `TIER_A` supplier, six months for `TIER_B`, and three months for `TIER_C`. When the supplier is `SUSPENDED` at close or `open_overdue_capa_count` is greater than zero, the next audit's `scheduled_window_start` is the clock plus 7 days and the audit is marked with `cadence_source` of `ESCALATED`. Otherwise the next `scheduled_window_start` is `last_audit_closed_at` plus the base cadence in whole months (same day-of-month, clamped to month end), and `cadence_source` is `TIER_CADENCE`. In both cases `scheduled_window_end` is `scheduled_window_start` plus 14 days — a fixed audit-window length.

The **dual-source breach** check runs on approved-source activation, suspension, reinstatement, revocation, on the stale-pin sweep at spec supersede, and on substitution execution. For an ingredient, count the approved sources that are in `ACTIVE` status and pinned to the ingredient's `active_spec_id`. When `requires_dual_source` is true and that count is less than two, `current_dual_source_breach` is set to true; when the count is exactly two or more, the breach is cleared.

## 4. Endpoint Definitions

All endpoints return the standard envelope from §2.2. Resource-creation endpoints (POST that creates a new resource) return HTTP 201; endpoints that mutate or transition an existing resource return HTTP 200. The endpoints listed as 201 in the table are the creation endpoints; all others are 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/sourcing/_clock/set_current_utc` | Set the logical clock and run all time-based sweeps | PlatformAdmin |
| POST | `/sourcing/ingredients` | Create an ingredient (DRAFT) | ProcurementManager |
| GET | `/sourcing/ingredients` | List ingredients | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/ingredients/{id}` | Get one ingredient | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/activate` | Activate ingredient (requires an EFFECTIVE spec) | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/discontinue` | Discontinue ingredient | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/specs` | Create a spec version (DRAFT); OCC-guarded on ingredient version | SpecAuthor |
| GET | `/sourcing/ingredients/{id}/specs` | List spec versions of an ingredient | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/ingredients/{id}/specs/{specId}` | Get one spec | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/parameters` | Add a spec parameter (spec must be DRAFT) | SpecAuthor |
| GET | `/sourcing/ingredients/{id}/specs/{specId}/parameters` | List parameters of a spec | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/submit` | Submit spec for review (author only) | SpecAuthor |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/approve` | Approve spec (not the author) | QualityManager |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/reject` | Reject spec (not the author) | QualityManager |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/revise` | Return rejected spec to DRAFT (author only) | SpecAuthor |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/make-effective` | Make approved spec effective at/after effective_date | QualityManager |
| POST | `/sourcing/ingredients/{id}/specs/{specId}/retire` | Retire a DRAFT/REJECTED spec not in use | QualityManager |
| POST | `/sourcing/suppliers` | Register a supplier (PROSPECT) | ProcurementManager |
| GET | `/sourcing/suppliers` | List suppliers | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/suppliers/{id}` | Get one supplier | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/suppliers/{id}/suspend` | Manually suspend a QUALIFIED supplier | QualityManager |
| POST | `/sourcing/suppliers/{id}/disqualify` | Disqualify a SUSPENDED supplier with no open CAPAs | QualityManager |
| POST | `/sourcing/suppliers/{id}/qualifications` | Open a qualification (supplier PROSPECT or SUSPENDED) | SupplierQualityEngineer |
| GET | `/sourcing/suppliers/{id}/qualifications` | List qualifications of a supplier | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/suppliers/{id}/qualifications/{qualificationId}/evaluate` | Move qualification to UNDER_EVALUATION | QualityManager |
| POST | `/sourcing/suppliers/{id}/qualifications/{qualificationId}/decide` | Approve or reject a qualification under evaluation | QualityManager |
| POST | `/sourcing/ingredients/{id}/approved-sources` | Create an ApprovedSource (PROVISIONAL); OCC-guarded on ingredient version | ProcurementManager |
| GET | `/sourcing/ingredients/{id}/approved-sources` | List approved sources of an ingredient | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/approved-sources/{id}` | Get one approved source | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/approved-sources/{sourceId}/activate` | Activate a PROVISIONAL source | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/approved-sources/{sourceId}/suspend` | Manually suspend an ACTIVE source | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/approved-sources/{sourceId}/reinstate` | Reinstate a SUSPENDED source | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/approved-sources/{sourceId}/revoke` | Revoke a source with no ACTIVE contract | ProcurementManager |
| POST | `/sourcing/approved-sources/{id}/declarations` | Collect a regulatory declaration; supersedes any CURRENT one of the same type | RegulatoryAffairs |
| GET | `/sourcing/approved-sources/{id}/declarations` | List declarations of a source | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/approved-sources/{id}/contracts` | Create a supply contract (PENDING); OCC-guarded on approved source version | ProcurementManager |
| GET | `/sourcing/approved-sources/{id}/contracts` | List contracts of a source | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/approved-sources/{id}/contracts/{contractId}/activate` | Activate a PENDING contract inside its window | ProcurementManager |
| POST | `/sourcing/approved-sources/{id}/contracts/{contractId}/terminate` | Terminate a PENDING or ACTIVE contract | ProcurementManager |
| GET | `/sourcing/approved-sources/{id}/contracts/{contractId}/rebate` | Computed read: annual rebate for a contract | ProcurementManager, QualityManager, PlatformAdmin |
| GET | `/sourcing/specs` | List spec versions across ingredients (filtered) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/specs/{specId}` | Get one spec by id (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/specs/{id}/parameters` | List parameters of a spec (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/specs/{id}/approved-sources` | List approved sources pinned to a spec (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/suppliers/{id}/approved-sources` | List approved sources of a supplier (reverse lookup) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| GET | `/sourcing/contracts/{contractId}` | Get one contract by id (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/contracts/{id}/coas` | List CoAs registered against a contract (reverse lookup) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/coas/{coaId}` | Get one CoA by id (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/coas/{id}/findings` | List OOS findings of a CoA (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/approved-sources/{id}/substitution-requests` | List substitution requests referencing a source as from or to | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/substitution-requests/{requestId}` | Get one substitution request by id (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/substitution-requests/{id}/assessment` | Get the FormulaImpactAssessment of a request (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/audits/{auditId}` | Get one audit by id (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/audits/{id}/corrective-actions` | List CAPAs of an audit (flat alias) | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/price-index-observations` | Record a market price index observation | PlatformAdmin |
| GET | `/sourcing/price-index-observations` | List index observations | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, SpecAuthor, PlatformAdmin |
| POST | `/sourcing/approved-sources/{id}/coas` | Register a CoA lot (source must be ACTIVE; contract must be ACTIVE) | SupplierQualityEngineer |
| GET | `/sourcing/approved-sources/{id}/coas` | List CoAs of a source | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| GET | `/sourcing/approved-sources/{id}/coas/{coaId}` | Get one CoA | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/approved-sources/{id}/coas/{coaId}/start-review` | Start CoA review: findings auto-created, provisional score computed | QualityManager |
| GET | `/sourcing/approved-sources/{id}/coas/{coaId}/findings` | List OOS findings of a CoA | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/approved-sources/{id}/coas/{coaId}/findings/{findingId}/disposition` | Disposition a finding | QualityManager |
| POST | `/sourcing/approved-sources/{id}/coas/{coaId}/close-review` | Close CoA review with ACCEPT or REJECT (not the registrar) | QualityManager |
| POST | `/sourcing/ingredients/{id}/substitution-requests` | Create a substitution request (REQUESTED) | ProcurementManager |
| GET | `/sourcing/ingredients/{id}/substitution-requests` | List substitution requests of an ingredient | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/assess` | Run formula impact assessment | SupplierQualityEngineer |
| GET | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/assessment` | Get the FormulaImpactAssessment of a request | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/route-regulatory` | Route an assessed request to regulatory when sign-off required | SupplierQualityEngineer |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/regulatory-signoff` | Record Regulatory Affairs sign-off | RegulatoryAffairs |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/approve` | Approve an assessed or regulatory-cleared request (not the requester) | QualityManager |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/reject` | Reject a request (not the requester) | QualityManager |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/execute` | Execute an approved substitution; suspends the replaced source | ProcurementManager |
| POST | `/sourcing/ingredients/{id}/substitution-requests/{requestId}/cancel` | Cancel a non-terminal request (requester only) | ProcurementManager |
| POST | `/sourcing/suppliers/{id}/audits` | Schedule a supplier audit | SupplierQualityEngineer |
| GET | `/sourcing/suppliers/{id}/audits` | List audits of a supplier | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/start` | Start a scheduled audit inside its window | SupplierQualityEngineer |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/issue-report` | Issue audit report with score | SupplierQualityEngineer |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/close` | Close an audit once all CAPAs verified; schedules next audit per cadence | QualityManager |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/cancel` | Cancel a SCHEDULED audit | QualityManager |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/corrective-actions` | Raise a CAPA on a REPORT_ISSUED audit | QualityManager |
| GET | `/sourcing/suppliers/{id}/audits/{auditId}/corrective-actions` | List CAPAs of an audit | ProcurementManager, QualityManager, SupplierQualityEngineer, RegulatoryAffairs, PlatformAdmin |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/corrective-actions/{capaId}/submit-response` | Submit or resubmit a CAPA response | SupplierQualityEngineer |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/corrective-actions/{capaId}/verify` | Verify a submitted CAPA | QualityManager |
| POST | `/sourcing/suppliers/{id}/audits/{auditId}/corrective-actions/{capaId}/reject-response` | Reject a submitted CAPA response | QualityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE` | 409 |
| `ERR_NO_SPEC_PARAMETERS` | 409 |
| `ERR_PARAMETER_BOUNDS_INVALID` | 422 |
| `ERR_SPEC_NOT_YET_EFFECTIVE` | 422 |
| `ERR_SUPERSEDES_NOT_EFFECTIVE` | 409 |
| `ERR_SPEC_IN_USE` | 409 |
| `ERR_NO_EFFECTIVE_SPEC` | 409 |
| `ERR_SPEC_NOT_EFFECTIVE` | 409 |
| `ERR_ACTIVE_SOURCES_EXIST` | 409 |
| `ERR_OPEN_SUBSTITUTIONS_EXIST` | 409 |
| `ERR_QUALIFICATION_IN_PROGRESS` | 409 |
| `ERR_QUALIFICATION_SCORE_TOO_LOW` | 422 |
| `ERR_DOCUMENT_PACK_INCOMPLETE` | 422 |
| `ERR_SUPPLIER_NOT_QUALIFIED` | 409 |
| `ERR_OPEN_CAPAS_EXIST` | 409 |
| `ERR_DECLARATION_MISSING` | 422 |
| `ERR_SOURCE_NOT_ACTIVE` | 409 |
| `ERR_ACTIVE_CONTRACT_EXISTS` | 409 |
| `ERR_CONTRACT_WINDOW_NOT_OPEN` | 422 |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 |
| `ERR_MEASURED_VALUES_INCOMPLETE` | 422 |
| `ERR_FINDINGS_UNDISPOSITIONED` | 409 |
| `ERR_FINDINGS_REQUIRE_REJECTION` | 422 |
| `ERR_DEVIATION_SCORE_TOO_HIGH` | 422 |
| `ERR_REGULATORY_SIGNOFF_REQUIRED` | 422 |
| `ERR_REGULATORY_SIGNOFF_NOT_REQUIRED` | 422 |
| `ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD` | 422 |
| `ERR_AUDIT_WINDOW_NOT_OPEN` | 422 |
| `ERR_AUDIT_ALREADY_OPEN` | 409 |
| `ERR_TEMPORAL_GUARD_VIOLATION` | 422 |
